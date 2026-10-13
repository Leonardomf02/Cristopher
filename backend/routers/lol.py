from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, case
from datetime import date, datetime, timedelta
from typing import Optional
from pydantic import BaseModel
import json
import os
import time
import logging

logger = logging.getLogger(__name__)

from database import get_db, SessionLocal
from models import LolDuel, LolGame, LolRankSnapshot, LolPrediction, LolSeason, SleepEntry
from schemas import LolGameCreate, LolGameUpdate, LolGameOut
from riot_api import (
    fetch_recent_games, RiotAPIError, get_puuid,
    get_rank_info, get_live_game, get_live_game_detailed, get_mastery_data,
    get_match_timeline, parse_timeline,
    get_summoner_level, get_master_position, get_replay_links,
    build_matchup_stats, get_leagueofgraphs_ranking, get_opgg_profile,
)
from lcu_api import get_champ_select_session, get_gameflow_phase, is_client_running
from champion_data import (
    ensure_champion_data, champion_name, analyze_team_comp,
    get_damage_type, get_champion_class,
    set_matchup_data, get_matchup_data, _id_to_key,
)
from meta_stats import (
    fetch_meta_stats, get_meta_stats, _to_ddragon_key, canon_slug, _ensure_slug_map,
    lane_provavel_cached, aquece_lane_shares,
)
import asyncio

router = APIRouter(prefix="/api/lol", tags=["League of Legends"])

# Background task to pre-warm meta stats cache
_meta_warmup_task: asyncio.Task | None = None

async def _ensure_meta_warmed():
    """Kick off a background fetch of meta stats if cache is empty. Non-blocking."""
    global _meta_warmup_task
    if get_meta_stats() is not None:
        return  # already cached
    if _meta_warmup_task and not _meta_warmup_task.done():
        return  # already fetching
    _meta_warmup_task = asyncio.create_task(fetch_meta_stats())


async def _meta_pronto(espera: float = 25.0) -> dict[str, dict]:
    """O meta, esperando por ele se for preciso.

    `_ensure_meta_warmed` é de propósito não-bloqueante — o champ select tem
    trinta segundos e não pode ficar preso à espera de três sites. Mas quem abre
    a página das recomendações abre-a para as ver, e devolver-lhe uma lista vazia
    porque a cache estava fria é pior do que esperar. Depois da primeira vez o
    meta fica seis horas em cache e isto devolve logo."""
    meta = get_meta_stats()
    if meta:
        return meta
    await _ensure_meta_warmed()
    if _meta_warmup_task:
        try:
            await asyncio.wait_for(asyncio.shield(_meta_warmup_task), timeout=espera)
        except (asyncio.TimeoutError, Exception):
            pass
    return get_meta_stats() or {}


# ── Response cache with TTL ──────────────────────────────────────
_response_cache: dict[str, tuple[float, any]] = {}

def _cache_get(key: str, ttl: int = 300) -> any:
    """Return cached value if exists and not expired, else None."""
    if key in _response_cache:
        ts, val = _response_cache[key]
        if time.time() - ts < ttl:
            return val
    return None

def _cache_set(key: str, val: any):
    _response_cache[key] = (time.time(), val)

# Track which game_start_time we already saved a prediction for (fast path)
_predicted_games: set[int] = set()
# Instante de início da partida em análise: serve para saber quando mudar de jogo.
_ultima_partida: int = 0


def _save_prediction_if_new(live_data: dict):
    """Save an AI prediction for the current live game if not already saved."""
    import json as _json
    wp = live_data.get("win_probability")
    if not wp:
        return
    game_start = live_data.get("game_start_time", 0)
    if not game_start:
        return

    # Only save predictions for ranked Solo/Duo (queue 420) and Flex (queue 440)
    queue_id = live_data.get("queue_id")
    if queue_id not in (420, 440):
        return

    # Fast path: in-memory check
    if game_start in _predicted_games:
        return

    probability = wp.get("probability", 50)
    predicted_win = probability > 50
    confidence_level = wp.get("confidence", "low")
    factors = wp.get("factors", [])

    # Find my champion and lane opponent (not just enemy jungler)
    my_champ = None
    my_role = None
    enemy_champ = None

    for p in live_data.get("my_team", []):
        if p.get("is_me"):
            my_champ = p.get("champion_name")
            my_role = p.get("_assigned_role") or p.get("role")
            break

    # Try to find direct lane opponent (same role on enemy team)
    if my_role:
        matchups = live_data.get("matchup_analysis", {}).get("matchups", [])
        for m in matchups:
            if m.get("role") == my_role:
                enemy_champ = m.get("enemy_player", {}).get("champion")
                break

    # Fallback: enemy jungler ONLY if I am the jungler
    if not enemy_champ and my_role == "jungle":
        for p in live_data.get("enemy_team", []):
            if p.get("role") == "jungle":
                enemy_champ = p.get("champion_name")
                break

    # Don't save prediction without both champion names
    if not my_champ or not enemy_champ:
        logger.warning(f"Cannot save prediction: missing champion data ({my_champ} vs {enemy_champ})")
        return

    db = SessionLocal()
    try:
        # DB-level dedup: check by time window (±5min) OR same date+champion+opponent
        time_window = 5 * 60 * 1000  # 5 minutes in ms
        existing = (
            db.query(LolPrediction)
            .filter(
                LolPrediction.game_start_time.between(
                    game_start - time_window, game_start + time_window
                )
            )
            .first()
        )
        if not existing:
            # Also check by date + champion matchup (covers edge cases)
            existing = (
                db.query(LolPrediction)
                .filter(
                    LolPrediction.date == date.today(),
                    LolPrediction.champion_played == my_champ,
                    LolPrediction.champion_against == enemy_champ,
                    LolPrediction.actual_win.is_(None),
                )
                .first()
            )
        if existing:
            _predicted_games.add(game_start)
            return

        pred = LolPrediction(
            game_start_time=game_start,
            date=date.today(),
            champion_played=my_champ,
            champion_against=enemy_champ,
            predicted_win=predicted_win,
            confidence=probability if predicted_win else (100 - probability),
            confidence_level=confidence_level,
            factors=_json.dumps(factors),
        )
        db.add(pred)
        db.commit()
        _predicted_games.add(game_start)  # Cache AFTER successful commit
    except Exception as exc:
        logger.warning(f"Failed to save prediction: {exc}")
        db.rollback()
    finally:
        db.close()


def _resolve_predictions(db: Session):
    """Resolve unresolved predictions by matching with games in the DB."""
    unresolved = db.query(LolPrediction).filter(LolPrediction.actual_win.is_(None)).all()
    if not unresolved:
        return 0

    # Duas previsões do mesmo dia com o mesmo campeão davam as duas o mesmo jogo,
    # e o `match_id` é único: o UNIQUE constraint rebentava e o
    # `/predictions/stats` respondia 500. Ele joga dois Sylas no mesmo dia com
    # frequência — a 21 de Agosto havia oito pares assim por resolver. Um jogo só
    # pode resolver uma previsão.
    usados = {
        m for (m,) in db.query(LolPrediction.match_id)
        .filter(LolPrediction.match_id.isnot(None)).all() if m
    }

    def fica_com(pred, game) -> bool:
        if not game.match_id or game.match_id in usados:
            return False
        usados.add(game.match_id)
        pred.match_id = game.match_id
        pred.actual_win = game.won
        pred.correct = pred.predicted_win == game.won
        return True

    resolved = 0
    for pred in unresolved:
        # Strategy 1: Match by game_start_time hour (±1 hour for edge cases)
        if pred.game_start_time:
            game_dt = datetime.fromtimestamp(pred.game_start_time / 1000)
            game_hour = game_dt.hour
            possible_hours = [game_hour, (game_hour + 1) % 24]
            candidatos = (
                db.query(LolGame)
                .filter(
                    LolGame.date == pred.date,
                    LolGame.champion_played == pred.champion_played,
                    LolGame.game_hour.in_(possible_hours),
                )
                .order_by(LolGame.match_id.desc())
                .all()
            )
            game = next((g for g in candidatos if g.match_id not in usados), None)
            if game and fica_com(pred, game):
                resolved += 1
                continue

        # Strategy 2: Match by date + champion + opponent
        game = (
            db.query(LolGame)
            .filter(
                LolGame.date == pred.date,
                LolGame.champion_played == pred.champion_played,
                LolGame.champion_against == pred.champion_against,
            )
            .first()
        )
        if game and fica_com(pred, game):
            resolved += 1
            continue

        # Strategy 3: Match by date + champion only (if only one game with that champ)
        games = (
            db.query(LolGame)
            .filter(
                LolGame.date == pred.date,
                LolGame.champion_played == pred.champion_played,
            )
            .all()
        )
        if len(games) == 1 and fica_com(pred, games[0]):
            resolved += 1
        else:
            logger.debug(
                f"Unresolved prediction id={pred.id}: {pred.champion_played} vs {pred.champion_against} "
                f"on {pred.date} (game_start={pred.game_start_time}, matched_games={len(games)})"
            )

    if resolved:
        db.commit()
    return resolved


@router.get("/", response_model=list[LolGameOut])
def list_games(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    champion: Optional[str] = Query(None),
    season_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(LolGame)
    if season_id is not None:
        q = q.filter(LolGame.season_id == season_id)
    if start_date:
        q = q.filter(LolGame.date >= start_date)
    if end_date:
        q = q.filter(LolGame.date <= end_date)
    if champion:
        q = q.filter(LolGame.champion_played == champion)
    return q.order_by(LolGame.date.desc(), LolGame.match_id.desc()).all()


@router.get("/stats")
def game_stats(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    season_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(LolGame)
    if season_id is not None:
        q = q.filter(LolGame.season_id == season_id)
    if start_date:
        q = q.filter(LolGame.date >= start_date)
    if end_date:
        q = q.filter(LolGame.date <= end_date)

    games = q.all()
    total = len(games)
    wins = sum(1 for g in games if g.won)
    losses = total - wins
    my_fault_losses = sum(1 for g in games if not g.won and g.my_fault is True)

    # Month stats (always current month)
    now = date.today()
    month_games_q = db.query(LolGame).filter(
        extract("month", LolGame.date) == now.month,
        extract("year", LolGame.date) == now.year,
    ).all()
    month_total = len(month_games_q)
    month_wins = sum(1 for g in month_games_q if g.won)
    month_losses = month_total - month_wins

    # Champion stats
    champ_stats: dict = {}
    for g in games:
        champ = g.champion_played or "Unknown"
        if champ not in champ_stats:
            champ_stats[champ] = {"wins": 0, "losses": 0, "games": 0}
        champ_stats[champ]["games"] += 1
        if g.won:
            champ_stats[champ]["wins"] += 1
        else:
            champ_stats[champ]["losses"] += 1

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "winrate": round(wins / total * 100, 1) if total > 0 else 0,
        "my_fault_losses": my_fault_losses,
        "champion_stats": champ_stats,
        "month_games": month_total,
        "month_wins": month_wins,
        "month_losses": month_losses,
    }


@router.get("/season-stats")
def season_stats(season_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    """Season-wide stats with best/worst matchup win rates.
    If season_id is omitted, defaults to the active season.
    """
    sid = _resolve_season_id(db, season_id)
    q = db.query(LolGame)
    if sid is not None:
        q = q.filter(LolGame.season_id == sid)
    games = q.all()
    total = len(games)
    if total == 0:
        return {"total": 0, "wins": 0, "losses": 0, "winrate": 0,
                "best_matchups": [], "worst_matchups": []}

    wins = sum(1 for g in games if g.won)
    losses = total - wins

    # Build matchup matrix: (champion_played, champion_against) -> {wins, losses}
    matchups: dict[tuple[str, str], dict] = {}
    for g in games:
        cp = g.champion_played
        ca = g.champion_against
        if not cp or not ca:
            continue
        key = (cp, ca)
        if key not in matchups:
            matchups[key] = {"wins": 0, "losses": 0}
        if g.won:
            matchups[key]["wins"] += 1
        else:
            matchups[key]["losses"] += 1

    # Calculate winrates and filter matchups with >= 2 games
    matchup_list = []
    for (cp, ca), data in matchups.items():
        games_count = data["wins"] + data["losses"]
        if games_count < 2:
            continue
        wr = round(data["wins"] / games_count * 100, 1)
        matchup_list.append({
            "champion_played": cp,
            "champion_against": ca,
            "wins": data["wins"],
            "losses": data["losses"],
            "games": games_count,
            "winrate": wr,
        })

    # Sort by winrate for best/worst
    best = sorted(matchup_list, key=lambda x: (-x["winrate"], -x["games"]))[:5]
    worst = sorted(matchup_list, key=lambda x: (x["winrate"], -x["games"]))[:5]

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "winrate": round(wins / total * 100, 1),
        "best_matchups": best,
        "worst_matchups": worst,
    }


@router.get("/detailed-stats")
def detailed_stats(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    season_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Comprehensive stats for the Stats tab."""
    q = db.query(LolGame)
    if season_id is not None:
        q = q.filter(LolGame.season_id == season_id)
    if start_date:
        q = q.filter(LolGame.date >= start_date)
    if end_date:
        q = q.filter(LolGame.date <= end_date)
    games = q.order_by(LolGame.date.asc(), LolGame.id.asc()).all()
    total = len(games)
    if total == 0:
        return {"total": 0}

    wins = sum(1 for g in games if g.won)
    losses = total - wins

    # ── Per-role stats ──
    role_stats: dict[str, dict] = {}
    for g in games:
        r = g.role or "unknown"
        if r not in role_stats:
            role_stats[r] = {"wins": 0, "losses": 0, "games": 0, "kills": 0, "deaths": 0, "assists": 0}
        role_stats[r]["games"] += 1
        if g.won:
            role_stats[r]["wins"] += 1
        else:
            role_stats[r]["losses"] += 1
        role_stats[r]["kills"] += g.kills or 0
        role_stats[r]["deaths"] += g.deaths or 0
        role_stats[r]["assists"] += g.assists or 0
    for r, s in role_stats.items():
        s["winrate"] = round(s["wins"] / s["games"] * 100, 1) if s["games"] else 0
        s["avg_kda"] = round((s["kills"] + s["assists"]) / max(s["deaths"], 1), 2)

    # ── Per-champion stats ──
    champ_stats: dict[str, dict] = {}
    for g in games:
        c = g.champion_played or "Unknown"
        if c not in champ_stats:
            champ_stats[c] = {"wins": 0, "losses": 0, "games": 0, "kills": 0, "deaths": 0, "assists": 0, "total_duration": 0}
        champ_stats[c]["games"] += 1
        if g.won:
            champ_stats[c]["wins"] += 1
        else:
            champ_stats[c]["losses"] += 1
        champ_stats[c]["kills"] += g.kills or 0
        champ_stats[c]["deaths"] += g.deaths or 0
        champ_stats[c]["assists"] += g.assists or 0
        champ_stats[c]["total_duration"] += g.game_duration or 0
    champ_list = []
    for name, s in champ_stats.items():
        s["winrate"] = round(s["wins"] / s["games"] * 100, 1) if s["games"] else 0
        s["avg_kda"] = round((s["kills"] + s["assists"]) / max(s["deaths"], 1), 2)
        s["avg_kills"] = round(s["kills"] / s["games"], 1)
        s["avg_deaths"] = round(s["deaths"] / s["games"], 1)
        s["avg_assists"] = round(s["assists"] / s["games"], 1)
        s["avg_duration"] = round(s["total_duration"] / s["games"] / 60, 1) if s["total_duration"] else 0
        champ_list.append({"champion": name, **s})
    champ_list.sort(key=lambda x: x["games"], reverse=True)

    # ── Winrate over time (rolling 10-game window) ──
    winrate_history = []
    for i in range(len(games)):
        window = games[max(0, i - 9):i + 1]
        w = sum(1 for g in window if g.won)
        winrate_history.append({
            "game_number": i + 1,
            "date": str(games[i].date),
            "winrate": round(w / len(window) * 100, 1),
            "won": games[i].won,
        })

    # ── Win/loss streaks ──
    current_streak = 0
    current_streak_type = None
    best_win_streak = 0
    worst_loss_streak = 0
    streak = 0
    prev_won = None
    for g in games:
        if g.won == prev_won:
            streak += 1
        else:
            streak = 1
        prev_won = g.won
        if g.won:
            best_win_streak = max(best_win_streak, streak)
        else:
            worst_loss_streak = max(worst_loss_streak, streak)
    current_streak = streak
    current_streak_type = "win" if prev_won else "loss"

    # ── Average KDA ──
    total_kills = sum(g.kills or 0 for g in games)
    total_deaths = sum(g.deaths or 0 for g in games)
    total_assists = sum(g.assists or 0 for g in games)
    avg_kda = round((total_kills + total_assists) / max(total_deaths, 1), 2)

    # ── Game duration stats ──
    durations = [g.game_duration for g in games if g.game_duration]
    avg_duration = round(sum(durations) / len(durations) / 60, 1) if durations else 0
    short_games = [g for g in games if g.game_duration and g.game_duration < 20 * 60]
    long_games = [g for g in games if g.game_duration and g.game_duration > 30 * 60]
    short_wr = round(sum(1 for g in short_games if g.won) / max(len(short_games), 1) * 100, 1) if short_games else 0
    long_wr = round(sum(1 for g in long_games if g.won) / max(len(long_games), 1) * 100, 1) if long_games else 0

    # ── Last 20 games WR (recent form) ──
    last20 = games[-20:] if len(games) >= 20 else games
    last20_wins = sum(1 for g in last20 if g.won)
    last20_wr = round(last20_wins / len(last20) * 100, 1) if last20 else 0

    # ── Most played champion ──
    most_played_champ = champ_list[0]["champion"] if champ_list else None
    most_played_games = champ_list[0]["games"] if champ_list else 0

    # ── Day-of-week performance ──
    dow_stats: dict[int, dict] = {}  # 0=Monday .. 6=Sunday
    for g in games:
        d = g.date
        if hasattr(d, 'weekday'):
            dow = d.weekday()  # 0=Mon, 6=Sun
        else:
            from datetime import date as date_cls
            dow = date_cls.fromisoformat(str(d)).weekday()
        if dow not in dow_stats:
            dow_stats[dow] = {"wins": 0, "losses": 0, "games": 0}
        dow_stats[dow]["games"] += 1
        if g.won:
            dow_stats[dow]["wins"] += 1
        else:
            dow_stats[dow]["losses"] += 1
    dow_names = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
    dow_list = []
    for i in range(7):
        s = dow_stats.get(i, {"wins": 0, "losses": 0, "games": 0})
        wr = round(s["wins"] / s["games"] * 100, 1) if s["games"] else 0
        dow_list.append({"day": dow_names[i], "day_index": i, **s, "winrate": wr})

    # ── Daily performance ──
    daily: dict[str, dict] = {}
    for g in games:
        d = str(g.date)
        if d not in daily:
            daily[d] = {"wins": 0, "losses": 0}
        if g.won:
            daily[d]["wins"] += 1
        else:
            daily[d]["losses"] += 1
    daily_list = [{"date": d, **s, "total": s["wins"] + s["losses"],
                   "winrate": round(s["wins"] / (s["wins"] + s["losses"]) * 100, 1)}
                  for d, s in daily.items()]
    daily_list.sort(key=lambda x: x["date"], reverse=True)

    # ── Most played against ──
    against_stats: dict[str, dict] = {}
    for g in games:
        ca = g.champion_against
        if not ca:
            continue
        if ca not in against_stats:
            against_stats[ca] = {"wins": 0, "losses": 0, "games": 0}
        against_stats[ca]["games"] += 1
        if g.won:
            against_stats[ca]["wins"] += 1
        else:
            against_stats[ca]["losses"] += 1
    against_list = []
    for name, s in against_stats.items():
        s["winrate"] = round(s["wins"] / s["games"] * 100, 1) if s["games"] else 0
        against_list.append({"champion": name, **s})
    against_list.sort(key=lambda x: x["games"], reverse=True)

    # ── 1. WR by hour of day ──
    hour_stats: dict[int, dict] = {}
    for g in games:
        h = g.game_hour
        if h is None:
            continue
        if h not in hour_stats:
            hour_stats[h] = {"wins": 0, "losses": 0, "games": 0}
        hour_stats[h]["games"] += 1
        if g.won:
            hour_stats[h]["wins"] += 1
        else:
            hour_stats[h]["losses"] += 1
    hour_list = []
    for h in range(24):
        s = hour_stats.get(h, {"wins": 0, "losses": 0, "games": 0})
        wr = round(s["wins"] / s["games"] * 100, 1) if s["games"] else 0
        hour_list.append({"hour": h, **s, "winrate": wr})

    # ── 2. WR post-streak (after 2+ losses) ──
    post_streak_games = 0
    post_streak_wins = 0
    loss_streak = 0
    for g in games:
        if loss_streak >= 2:
            # This game comes after 2+ consecutive losses
            post_streak_games += 1
            if g.won:
                post_streak_wins += 1
        if g.won:
            loss_streak = 0
        else:
            loss_streak += 1
    post_streak_wr = round(post_streak_wins / post_streak_games * 100, 1) if post_streak_games else None

    # ── 3. LP over time (from rank snapshots) ──
    snapshots = db.query(LolRankSnapshot).order_by(LolRankSnapshot.date.asc()).all()
    lp_history = []
    TIER_LP = {"IRON": 0, "BRONZE": 400, "SILVER": 800, "GOLD": 1200,
               "PLATINUM": 1600, "EMERALD": 2000, "DIAMOND": 2400, "MASTER": 2800,
               "GRANDMASTER": 2800, "CHALLENGER": 2800}
    RANK_LP = {"IV": 0, "III": 100, "II": 200, "I": 300}
    for snap in snapshots:
        tier = (snap.tier or "").upper()
        base = TIER_LP.get(tier, 0)
        if tier in ("MASTER", "GRANDMASTER", "CHALLENGER"):
            total_lp = base + (snap.lp or 0)
        else:
            total_lp = base + RANK_LP.get(snap.rank or "IV", 0) + (snap.lp or 0)
        lp_history.append({
            "date": str(snap.date),
            "tier": snap.tier,
            "rank": snap.rank,
            "lp": snap.lp,
            "total_lp": total_lp,
        })

    # ── 4. Blue/Red side WR ──
    side_stats: dict[str, dict] = {}
    for g in games:
        side = g.team_side
        if not side:
            continue
        if side not in side_stats:
            side_stats[side] = {"wins": 0, "losses": 0, "games": 0}
        side_stats[side]["games"] += 1
        if g.won:
            side_stats[side]["wins"] += 1
        else:
            side_stats[side]["losses"] += 1
    for s in side_stats.values():
        s["winrate"] = round(s["wins"] / s["games"] * 100, 1) if s["games"] else 0

    # ── 5. WR by game duration buckets ──
    duration_buckets = [
        {"label": "<20m", "min": 0, "max": 20 * 60},
        {"label": "20-25m", "min": 20 * 60, "max": 25 * 60},
        {"label": "25-30m", "min": 25 * 60, "max": 30 * 60},
        {"label": "30-35m", "min": 30 * 60, "max": 35 * 60},
        {"label": "35-40m", "min": 35 * 60, "max": 40 * 60},
        {"label": "40m+", "min": 40 * 60, "max": 999999},
    ]
    duration_wr = []
    for bucket in duration_buckets:
        bg = [g for g in games if g.game_duration and bucket["min"] <= g.game_duration < bucket["max"]]
        bw = sum(1 for g in bg if g.won)
        bl = len(bg) - bw
        wr = round(bw / len(bg) * 100, 1) if bg else 0
        duration_wr.append({"label": bucket["label"], "wins": bw, "losses": bl, "games": len(bg), "winrate": wr})

    # ── 6. Gold diff @15 (placeholder — needs timeline backfill) ──
    # Not computed here; would need stored timeline data per game

    # ── 7. Champion pool depth ──
    sorted_champs = sorted(champ_stats.items(), key=lambda x: x[1]["games"], reverse=True)
    cumulative = 0
    pool_80 = 0  # champs covering 80% of games
    pool_90 = 0
    for name, s in sorted_champs:
        cumulative += s["games"]
        if pool_80 == 0 and cumulative >= total * 0.8:
            pool_80 = sorted_champs.index((name, s)) + 1
        if pool_90 == 0 and cumulative >= total * 0.9:
            pool_90 = sorted_champs.index((name, s)) + 1
    unique_champs = len(champ_stats)
    top3_champs = [{"champion": name, "games": s["games"], "winrate": round(s["wins"] / s["games"] * 100, 1) if s["games"] else 0} for name, s in sorted_champs[:3]]

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "winrate": round(wins / total * 100, 1),
        "avg_kda": avg_kda,
        "avg_kills": round(total_kills / total, 1),
        "avg_deaths": round(total_deaths / total, 1),
        "avg_assists": round(total_assists / total, 1),
        "avg_duration": avg_duration,
        "short_game_wr": short_wr,
        "short_game_count": len(short_games),
        "long_game_wr": long_wr,
        "long_game_count": len(long_games),
        "last20_wr": last20_wr,
        "last20_count": len(last20),
        "most_played_champ": most_played_champ,
        "most_played_games": most_played_games,
        "best_win_streak": best_win_streak,
        "worst_loss_streak": worst_loss_streak,
        "current_streak": current_streak,
        "current_streak_type": current_streak_type,
        "role_stats": role_stats,
        "champion_stats": champ_list,
        "winrate_history": winrate_history,
        "daily_performance": daily_list,
        "dow_performance": dow_list,
        "most_faced": against_list[:15],
        # New stats
        "hour_performance": hour_list,
        "post_streak_wr": post_streak_wr,
        "post_streak_games": post_streak_games,
        "lp_history": lp_history,
        "side_performance": side_stats,
        "duration_buckets": duration_wr,
        "champion_pool": {
            "unique_champs": unique_champs,
            "pool_80": pool_80,
            "pool_90": pool_90,
            "top3": top3_champs,
        },
    }


@router.get("/daily-goal")
def objectivo_diario(days: int = Query(180, ge=14, le=730), db: Session = Depends(get_db)):
    """Objectivo dos 3 jogos por dia: quanto se cumpre e se muda alguma coisa no resultado."""
    from lol_goal import marca_dias, resumo
    marca_dias(db, dias_atras=days)
    return resumo(db, dias=days)


# ── Quando parar ─────────────────────────────────────────────────
# A app já mede tudo mas nunca diz "chega". Aqui olha-se para duas coisas que os
# dados dele sugerem: as derrotas seguidas e o nº de jogos já feitos no dia. Só
# se afirma o que passa num teste de duas proporções a 95% — o resto fica como
# "ainda não dá para dizer", que é a diferença entre um número e uma conclusão.

def _z_duas_proporcoes(v1: int, n1: int, v2: int, n2: int) -> Optional[float]:
    if n1 < 2 or n2 < 2:
        return None
    p1, p2 = v1 / n1, v2 / n2
    p = (v1 + v2) / (n1 + n2)
    se = (p * (1 - p) * (1 / n1 + 1 / n2)) ** 0.5
    return round((p1 - p2) / se, 2) if se else None


def _sequencias(db: Session, dias: int) -> list[list[LolGame]]:
    """Os jogos de cada dia por ordem, agrupados por dia."""
    desde = date.today() - timedelta(days=dias)
    por_dia: dict[date, list[LolGame]] = {}
    for g in (
        db.query(LolGame)
        .filter(LolGame.date >= desde, LolGame.game_hour.isnot(None))
        .order_by(LolGame.date, LolGame.game_hour)
        .all()
    ):
        por_dia.setdefault(g.date, []).append(g)
    return list(por_dia.values())


@router.get("/stop-signal")
def sinal_de_paragem(days: int = Query(180, ge=30, le=730), db: Session = Depends(get_db)):
    """Se vale a pena continuar a jogar hoje, com o que o histórico aguenta provar."""
    sessoes = _sequencias(db, days)

    # (a) depois de N derrotas seguidas vs. resto
    apos_derrotas = {1: [0, 0], 2: [0, 0], 3: [0, 0]}     # n -> [jogos, vitórias]
    normal = [0, 0]
    for jogos in sessoes:
        seguidas = 0
        for i, g in enumerate(jogos):
            if i > 0:
                alvo = apos_derrotas.get(min(seguidas, 3)) if seguidas else None
                destino = alvo if alvo else normal
                destino[0] += 1
                destino[1] += 1 if g.won else 0
            seguidas = seguidas + 1 if not g.won else 0

    derrotas = []
    for n, (total, vit) in sorted(apos_derrotas.items()):
        if total < 15:
            continue
        z = _z_duas_proporcoes(vit, total, normal[1], normal[0])
        derrotas.append({
            "after_losses": n, "games": total,
            "winrate": round(vit / total * 100, 1),
            "baseline": round(normal[1] / normal[0] * 100, 1) if normal[0] else None,
            "z": z, "proven": bool(z is not None and abs(z) >= 1.96),
        })

    # (b) o enésimo jogo do dia vs. os primeiros três
    por_posicao: dict[int, list[int]] = {}
    for jogos in sessoes:
        for i, g in enumerate(jogos):
            por_posicao.setdefault(min(i + 1, 7), [0, 0])
            por_posicao[min(i + 1, 7)][0] += 1
            por_posicao[min(i + 1, 7)][1] += 1 if g.won else 0
    cedo_n = sum(v[0] for k, v in por_posicao.items() if k <= 3)
    cedo_v = sum(v[1] for k, v in por_posicao.items() if k <= 3)
    posicoes = []
    for pos, (total, vit) in sorted(por_posicao.items()):
        if total < 15:
            continue
        z = _z_duas_proporcoes(vit, total, cedo_v, cedo_n) if pos > 3 else None
        posicoes.append({
            "position": pos, "games": total, "winrate": round(vit / total * 100, 1),
            "z": z, "proven": bool(z is not None and abs(z) >= 1.96),
        })

    # o que se pode mesmo afirmar
    avisos = []
    for d in derrotas:
        if d["proven"] and d["winrate"] < (d["baseline"] or 100):
            avisos.append({
                "key": f"derrotas-{d['after_losses']}",
                "text": (f"Depois de {d['after_losses']} derrota{'s' if d['after_losses'] > 1 else ''} seguida"
                         f"{'s' if d['after_losses'] > 1 else ''}, ganhas {d['winrate']}% "
                         f"(contra {d['baseline']}% no resto), em {d['games']} jogos."),
            })
    for p in posicoes:
        if p["proven"] and p["winrate"] < round(cedo_v / cedo_n * 100, 1):
            avisos.append({
                "key": f"posicao-{p['position']}",
                "text": (f"Do {p['position']}º jogo do dia em diante ganhas {p['winrate']}%, "
                         f"contra {round(cedo_v / cedo_n * 100, 1)}% nos três primeiros "
                         f"({p['games']} jogos)."),
            })

    hoje = db.query(LolGame).filter(LolGame.date == date.today()).order_by(LolGame.game_hour).all()
    seguidas_hoje = 0
    for g in reversed(hoje):
        if g.won:
            break
        seguidas_hoje += 1

    return {
        "days": days,
        "after_losses": derrotas,
        "by_position": posicoes,
        "warnings": avisos,
        "today": {
            "games": len(hoje),
            "wins": sum(1 for g in hoje if g.won),
            "losing_streak": seguidas_hoje,
        },
        # Só se sugere parar quando há prova e a situação de hoje bate certo com ela.
        "should_stop": bool(
            any(a["key"] == f"derrotas-{min(seguidas_hoje, 3)}" for a in avisos) and seguidas_hoje >= 1
            or any(a["key"].startswith("posicao-") and len(hoje) >= int(a["key"].split("-")[1]) for a in avisos)
        ),
    }


@router.get("/daily")
def daily_stats(
    target_date: date = Query(...),
    db: Session = Depends(get_db),
):
    games = db.query(LolGame).filter(LolGame.date == target_date).all()
    wins = sum(1 for g in games if g.won)
    losses = len(games) - wins
    return {
        "date": target_date,
        "total": len(games),
        "wins": wins,
        "losses": losses,
        "games": [LolGameOut.model_validate(g) for g in games],
    }


@router.post("/", response_model=LolGameOut)
def create_game(data: LolGameCreate, db: Session = Depends(get_db)):
    game = LolGame(**data.model_dump())
    db.add(game)
    db.commit()
    db.refresh(game)
    return game


@router.put("/{game_id}", response_model=LolGameOut)
def update_game(game_id: int, data: LolGameUpdate, db: Session = Depends(get_db)):
    game = db.query(LolGame).filter(LolGame.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(game, key, value)
    db.commit()
    db.refresh(game)
    return game


@router.delete("/{game_id}")
def delete_game(game_id: int, db: Session = Depends(get_db)):
    game = db.query(LolGame).filter(LolGame.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    db.delete(game)
    db.commit()
    return {"ok": True}


@router.delete("/purge/all")
def purge_all_games(db: Session = Depends(get_db)):
    """Delete all auto-imported games (those with a match_id). Used to re-sync with correct filters."""
    count = db.query(LolGame).filter(LolGame.match_id.isnot(None)).delete()
    db.commit()
    _response_cache.clear()
    return {"ok": True, "deleted": count}


# ── Riot API Sync ────────────────────────────────────────────────

# Store config in memory (persists across requests while server runs).
# A chave vem do .env: estava escrita aqui e este ficheiro está num repo público
# — cada chave nova que ele colasse ficava publicada com o commit seguinte.
_riot_config: dict = {
    "game_name": os.getenv("RIOT_GAME_NAME", "Cristóvão"),
    "tag_line": os.getenv("RIOT_TAG_LINE", "2002"),
    "api_key": os.getenv("RIOT_API_KEY", ""),
}


class RiotConfig(BaseModel):
    game_name: str = "Cristóvão"
    tag_line: str = "2002"
    api_key: str = ""


@router.get("/riot/config")
def get_riot_config():
    return {
        "game_name": _riot_config["game_name"],
        "tag_line": _riot_config["tag_line"],
        "has_api_key": bool(_riot_config.get("api_key")),
    }


@router.post("/riot/config")
def set_riot_config(config: RiotConfig):
    _riot_config["game_name"] = config.game_name
    _riot_config["tag_line"] = config.tag_line
    if config.api_key:
        _riot_config["api_key"] = config.api_key
    return {"ok": True, "game_name": config.game_name, "tag_line": config.tag_line}


def _aviso_do_lado(db: Session, lado: str) -> Optional[dict]:
    """O que os jogos dele dizem sobre o lado que lhe calhou.

    Só sai se o teste passar — e sai sempre com o número de jogos ao lado, porque
    o efeito foi encontrado nos próprios dados e encolheu para metade quando a
    amostra foi partida no tempo."""
    import lol_duel as ld

    limite = date.today() - timedelta(days=365)
    jogos = (
        db.query(LolGame)
        .filter(LolGame.role == "jungle", LolGame.date >= limite,
                LolGame.team_side.isnot(None))
        .all()
    )
    duelos = db.query(LolDuel).filter(LolDuel.date >= limite).all()
    por_jogo = {g.match_id: g.team_side for g in jogos if g.match_id}
    for d in duelos:
        d._lado = por_jogo.get(d.match_id)

    r = ld.lado_do_mapa(duelos, jogos)
    if not r or not r["proven"]:
        return None
    bom = r["better_side"] == lado
    # A causa mais forte, dita do lado em que ele está.
    causa = r["causes"][0] if r["causes"] else None
    return {
        "side": lado,
        "is_better_side": bom,
        "winrate": r[lado]["winrate"],
        "games": r[lado]["games"],
        "other_winrate": r["red" if lado == "blue" else "blue"]["winrate"],
        "diff": r["diff"] if lado == "red" else -r["diff"],
        "top_cause": causa,
    }


async def _guarda_duelos(db: Session, match_ids: list[str], api_key: str,
                         tecto: int = 12) -> int:
    """Guarda o duelo com o jungler adversário nos jogos de jungle que ainda não o
    têm — os acabados de importar e os que ficaram para trás.

    Apanhar só os novos era uma fuga silenciosa: um jogo em que a Riot recusasse
    o pedido ficava sem duelo **para sempre**, porque nunca mais era tentado. A
    lista sai da base a cada passagem, por isso qualquer falha se cura sozinha na
    seguinte. `tecto` limita o trabalho de uma passagem (são dois pedidos por
    jogo, e isto corre de 20 em 20 minutos); o histórico todo faz-se de uma vez
    com `scripts/preenche_duelos_lol.py`.

    Nada aqui pode travar a importação: um jogo sem duelo é um jogo sem duelo,
    não uma sincronização falhada."""
    from riot_api import get_match_detail, get_match_timeline, parse_duel

    if not match_ids:
        limite = date.today() - timedelta(days=30)
        com_duelo = {d[0] for d in db.query(LolDuel.match_id).all()}
        match_ids = [
            g.match_id for g in db.query(LolGame)
            .filter(LolGame.role == "jungle", LolGame.match_id.isnot(None),
                    LolGame.date >= limite)
            .order_by(LolGame.date.desc()).all()
            if g.match_id not in com_duelo
        ][:tecto]
        if not match_ids:
            return 0

    game_name = _riot_config.get("game_name", "Cristóvão")
    tag_line = _riot_config.get("tag_line", "2002")
    try:
        puuid = await get_puuid(game_name, tag_line, api_key)
    except Exception as e:
        logger.warning(f"duelos: sem puuid ({e})")
        return 0

    ja_tem = {
        d[0] for d in db.query(LolDuel.match_id)
        .filter(LolDuel.match_id.in_(match_ids)).all()
    }
    guardados = 0
    for mid in match_ids:
        if not mid or mid in ja_tem:
            continue
        try:
            partida = await get_match_detail(mid, api_key)
            try:
                timeline = await get_match_timeline(mid, api_key)
            except Exception:
                timeline = None
            linha = parse_duel(partida, puuid, timeline)
        except Exception as e:
            logger.warning(f"duelos: {mid} falhou ({e})")
            continue
        if not linha:
            continue
        db.add(LolDuel(**linha))
        guardados += 1
    if guardados:
        db.commit()
    return guardados


@router.post("/riot/sync")
async def sync_riot_games(
    days: int = Query(0, ge=0, le=365, description="Days of history to sync. 0 = today only."),
    season: bool = Query(False, description="Sync exact season games using ranked API count."),
    db: Session = Depends(get_db),
):
    """Fetch games from Riot API and import new ones.
    days=0: today only (default). season=true: exact season games.
    """
    game_name = _riot_config.get("game_name", "Cristóvão")
    tag_line = _riot_config.get("tag_line", "2002")
    api_key = _riot_config.get("api_key", "")

    if not api_key:
        raise HTTPException(status_code=400, detail="API key não configurada.")

    if season:
        # Get exact season game count from ranked API
        rank = await get_rank_info(game_name, tag_line, api_key)
        if not rank:
            raise HTTPException(status_code=400, detail="Não foi possível obter dados de ranked.")
        season_total = rank["wins"] + rank["losses"]

        # Get existing match IDs to skip already-imported games
        existing = db.query(LolGame.match_id).filter(LolGame.match_id.isnot(None)).all()
        existing_ids = {row[0] for row in existing}

        try:
            new_games = await fetch_recent_games(
                game_name=game_name,
                tag_line=tag_line,
                api_key=api_key,
                count=season_total,
                queue=420,
                start_time=None,  # No start_time — fetch exact count of most recent ranked games
                existing_match_ids=existing_ids,
            )
        except RiotAPIError as e:
            raise HTTPException(status_code=502, detail=e.message)

        # NOTE: previously this branch DELETED games not in the current ranked set,
        # which would wipe past-season data when Riot resets wins+losses. Disabled.
        # Old games stay tagged with their season_id; new games get the active season.
    else:
        # Get existing match IDs to avoid duplicates
        existing = db.query(LolGame.match_id).filter(LolGame.match_id.isnot(None)).all()
        existing_ids = {row[0] for row in existing}

        # Calculate start time based on days parameter
        if days > 0:
            from datetime import timedelta
            start_day = date.today() - timedelta(days=days)
            start_time = int(datetime.combine(start_day, datetime.min.time()).timestamp())
            fetch_count = min(500, days * 5)
        else:
            today = date.today()
            start_time = int(datetime.combine(today, datetime.min.time()).timestamp())
            fetch_count = 20

        try:
            new_games = await fetch_recent_games(
                game_name=game_name,
                tag_line=tag_line,
                api_key=api_key,
                count=fetch_count,
                queue=420,
                start_time=start_time,
                existing_match_ids=existing_ids,
            )
        except RiotAPIError as e:
            raise HTTPException(status_code=502, detail=e.message)

    # Save new games to DB — tag with active season
    active_season_id = _resolve_season_id(db, None)
    imported = 0
    for game_data in new_games:
        game = LolGame(
            match_id=game_data["match_id"],
            date=game_data["date"],
            won=game_data["won"],
            champion_played=game_data["champion_played"],
            champion_against=game_data.get("champion_against"),
            role=game_data.get("role"),
            kills=game_data.get("kills"),
            deaths=game_data.get("deaths"),
            assists=game_data.get("assists"),
            game_duration=game_data.get("game_duration"),
            game_hour=game_data.get("game_hour"),
            team_side=game_data.get("team_side"),
            cs=game_data.get("cs"),
            cs_jungle=game_data.get("cs_jungle"),
            gold=game_data.get("gold"),
            damage=game_data.get("damage"),
            damage_taken=game_data.get("damage_taken"),
            vision=game_data.get("vision"),
            team_kills=game_data.get("team_kills"),
            season_id=active_season_id,
            notes="",
        )
        db.add(game)
        imported += 1

    duelos = 0
    if imported > 0:
        db.commit()
        _response_cache.pop("rank", None)
        _response_cache.pop("position", None)
        _response_cache.pop("matchup_stats", None)
        _response_cache.pop("duel", None)
        set_matchup_data(None)  # force rebuild from DB on next access
        duelos = await _guarda_duelos(db, [], api_key)

    # Always try to resolve predictions (even if 0 new games imported)
    resolved = _resolve_predictions(db)

    return {
        "ok": True,
        "imported": imported,
        "duels": duelos,
        "resolved_predictions": resolved,
        "message": f"{imported} jogo{'s' if imported != 1 else ''} importado{'s' if imported != 1 else ''} de {game_name}#{tag_line}",
    }


@router.post("/riot/backfill")
async def backfill_game_data(db: Session = Depends(get_db)):
    """Re-fetch match data for games missing game_hour or team_side."""
    api_key = _riot_config.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key não configurada.")

    games = db.query(LolGame).filter(
        LolGame.match_id.isnot(None),
        (LolGame.game_hour.is_(None)) | (LolGame.team_side.is_(None)),
    ).all()

    if not games:
        return {"ok": True, "updated": 0, "message": "Todos os jogos já têm dados completos."}

    from riot_api import get_match_detail, parse_match, get_puuid
    game_name = _riot_config.get("game_name", "Cristóvão")
    tag_line = _riot_config.get("tag_line", "2002")
    puuid = await get_puuid(game_name, tag_line, api_key)

    updated = 0
    for game in games:
        try:
            match_data = await get_match_detail(game.match_id, api_key)
            parsed = parse_match(match_data, puuid)
            if parsed:
                if game.game_hour is None and parsed.get("game_hour") is not None:
                    game.game_hour = parsed["game_hour"]
                if game.team_side is None and parsed.get("team_side") is not None:
                    game.team_side = parsed["team_side"]
                updated += 1
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Backfill failed for {game.match_id}: {e}")
            if hasattr(e, 'status_code') and e.status_code == 429:
                import asyncio as _aio
                await _aio.sleep(130)
                continue

    if updated > 0:
        db.commit()

    return {"ok": True, "updated": updated, "message": f"{updated} jogos atualizados."}


# ── Riot API — Rank / LP ────────────────────────────────────────

@router.get("/riot/rank")
async def get_rank():
    """Get current ranked stats (tier, rank, LP, wins/losses)."""
    cached = _cache_get("rank", ttl=300)
    if cached is not None:
        return cached
    api_key = _riot_config.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key não configurada.")
    try:
        rank = await get_rank_info(
            _riot_config["game_name"],
            _riot_config["tag_line"],
            api_key,
        )
        if rank is None:
            result = {"ranked": False, "message": "Unranked"}
        else:
            result = {"ranked": True, **rank}
            # Save rank snapshot (at most once per day)
            _save_rank_snapshot(rank)
        _cache_set("rank", result)
        return result
    except RiotAPIError as e:
        raise HTTPException(status_code=502, detail=e.message)


_TIER_BASE = {"IRON": 0, "BRONZE": 400, "SILVER": 800, "GOLD": 1200,
              "PLATINUM": 1600, "EMERALD": 2000, "DIAMOND": 2400,
              "MASTER": 2800, "GRANDMASTER": 3200, "CHALLENGER": 3600}


def _effective_lp(tier: str | None, lp: int | None) -> int:
    """Cross-tier comparable LP (Master 0LP > Diamond I 100LP)."""
    return _TIER_BASE.get(tier or "", 0) + (lp or 0)


def _save_rank_snapshot(rank: dict):
    """Save a rank snapshot and run season-reset detection."""
    try:
        db = SessionLocal()
        today = date.today()
        # Reset detection: compares Riot's wins+losses against this season's max.
        # If lower, archive current season and start a new one.
        season = _detect_and_handle_reset(db, rank, today)
        season_id = season.id if season else None

        existing = db.query(LolRankSnapshot).filter(LolRankSnapshot.date == today).first()
        if existing:
            # Always refresh live counters...
            existing.wins = rank.get("wins")
            existing.losses = rank.get("losses")
            existing.season_id = season_id
            # ...but keep the day's PEAK rank, never overwrite it downward.
            # Otherwise a loss after a high would erase the intra-day peak.
            if _effective_lp(rank.get("tier"), rank.get("lp")) >= _effective_lp(existing.tier, existing.lp):
                existing.tier = rank.get("tier")
                existing.rank = rank.get("rank")
                existing.lp = rank.get("lp")
        else:
            snap = LolRankSnapshot(
                date=today,
                tier=rank.get("tier"),
                rank=rank.get("rank"),
                lp=rank.get("lp"),
                wins=rank.get("wins"),
                losses=rank.get("losses"),
                season_id=season_id,
            )
            db.add(snap)
        db.commit()
        db.close()
    except Exception:
        pass  # Non-critical, don't break rank fetch


# ── Season helpers ──────────────────────────────────────────────

def _get_active_season(db: Session) -> LolSeason | None:
    return (
        db.query(LolSeason)
        .filter(LolSeason.end_date.is_(None))
        .order_by(LolSeason.id.desc())
        .first()
    )


def _next_season_label(db: Session) -> str:
    n = db.query(LolSeason).count()
    return f"Season {n + 1}"


def _close_season(db: Session, season: LolSeason, on_date: date, last_known_rank: dict | None = None):
    """Close a season: end_date, snapshot final tier/lp, copy peak from snapshots, recompute totals from games."""
    season.end_date = on_date
    if last_known_rank:
        season.final_tier = last_known_rank.get("tier")
        season.final_rank = last_known_rank.get("rank")
        season.final_lp = last_known_rank.get("lp")

    # Peak (highest LP rank during season — naive: pick snapshot with highest LP within season)
    snaps = (
        db.query(LolRankSnapshot)
        .filter(LolRankSnapshot.season_id == season.id)
        .all()
    )
    if snaps:
        # Order tiers; pick one with highest tier, then highest LP
        TIER_ORDER = ["IRON","BRONZE","SILVER","GOLD","PLATINUM","EMERALD","DIAMOND","MASTER","GRANDMASTER","CHALLENGER"]
        def tier_rank(s):
            t = (s.tier or "").upper()
            return TIER_ORDER.index(t) if t in TIER_ORDER else -1
        peak = max(snaps, key=lambda s: (tier_rank(s), s.lp or 0))
        season.peak_tier = peak.tier
        season.peak_rank = peak.rank
        season.peak_lp = peak.lp

    # Recompute game totals
    games = db.query(LolGame).filter(LolGame.season_id == season.id).all()
    season.total_games = len(games)
    season.total_wins = sum(1 for g in games if g.won)
    season.total_losses = season.total_games - season.total_wins


def _detect_and_handle_reset(db: Session, rank: dict, today: date) -> LolSeason:
    """Detect season reset by comparing Riot's wins+losses to active season's max.
    Returns the now-active season (may be a brand-new one if reset happened).
    """
    season = _get_active_season(db)
    current_total = (rank.get("wins") or 0) + (rank.get("losses") or 0)

    # No active season → bootstrap one (defensive; main.py also does this on boot)
    if season is None:
        season = LolSeason(
            label=_next_season_label(db),
            start_date=today,
            max_ranked_total=current_total,
        )
        db.add(season)
        db.commit()
        db.refresh(season)
        return season

    # Reset detected: current count dropped below the max we've seen this season
    if current_total < (season.max_ranked_total or 0):
        # Capture last-known rank from the most recent snapshot (best proxy for "where I ended")
        last = (
            db.query(LolRankSnapshot)
            .filter(LolRankSnapshot.season_id == season.id)
            .order_by(LolRankSnapshot.date.desc())
            .first()
        )
        last_rank = {"tier": last.tier, "rank": last.rank, "lp": last.lp} if last else None
        _close_season(db, season, today, last_rank)
        db.commit()
        # Open a new season
        new_season = LolSeason(
            label=_next_season_label(db),
            start_date=today,
            max_ranked_total=current_total,
        )
        db.add(new_season)
        db.commit()
        db.refresh(new_season)
        return new_season

    # Same season — just bump the max if grew
    if current_total > (season.max_ranked_total or 0):
        season.max_ranked_total = current_total
        db.commit()
    return season


def _resolve_season_id(db: Session, season_id: int | None) -> int | None:
    """If season_id is None, return active season's id (or None if none exists)."""
    if season_id is not None:
        return season_id
    s = _get_active_season(db)
    return s.id if s else None


# ── Riot API — Live Game ────────────────────────────────────────

@router.get("/riot/live")
async def get_live_status():
    """Check if the player is currently in a game."""
    cached = _cache_get("live", ttl=30)
    if cached is not None:
        return cached
    api_key = _riot_config.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key não configurada.")
    try:
        live = await get_live_game(
            _riot_config["game_name"],
            _riot_config["tag_line"],
            api_key,
        )
        result = live if live else {"in_game": False}
        _cache_set("live", result)
        return result
    except RiotAPIError as e:
        raise HTTPException(status_code=502, detail=e.message)


@router.get("/riot/live/detailed")
async def get_live_detailed():
    """Get detailed live game stats for all players (Porofessor-style)."""
    cached = _cache_get("live_detailed", ttl=90)
    if cached is not None:
        return cached
    api_key = _riot_config.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key não configurada.")
    try:
        data = await get_live_game_detailed(
            _riot_config["game_name"],
            _riot_config["tag_line"],
            api_key,
        )
        result = data if data else {"in_game": False}

        # Partida nova → cache dos jogadores fora. Dentro da mesma partida nada
        # disto muda (é o que evita ~1.600 pedidos à Riot por jogo), mas entre
        # jogos os números dele próprio mudaram.
        global _ultima_partida
        agora = result.get("game_start_time") or 0
        if result.get("in_game") and agora and agora != _ultima_partida:
            from riot_api import limpa_cache_jogadores
            limpa_cache_jogadores()
            _ultima_partida = agora

        # Enrich with personal matchup WR from local DB
        if result.get("in_game"):
            await _ensure_matchup_data()
            mdata = get_matchup_data()
            matchups = mdata.get("matchups", {}) if mdata else {}

            # Find my champion in my_team
            my_champ = None
            for p in result.get("my_team", []):
                if p.get("is_me"):
                    my_champ = p.get("champion_name")
                    break

            # Build personal matchup data for each enemy
            personal_matchups = {}
            for p in result.get("enemy_team", []):
                enemy_champ = p.get("champion_name")
                if not enemy_champ:
                    continue

                entry: dict = {}

                # My WR against this enemy champ (any champion I played)
                total_vs = {"wins": 0, "losses": 0, "games": 0}
                for my_c, vs_map in matchups.items():
                    if enemy_champ in vs_map:
                        s = vs_map[enemy_champ]
                        total_vs["wins"] += s["wins"]
                        total_vs["losses"] += s["losses"]
                        total_vs["games"] += s["games"]
                if total_vs["games"] > 0:
                    total_vs["winrate"] = round(total_vs["wins"] / total_vs["games"] * 100, 1)
                    entry["vs_enemy_all"] = total_vs

                # My specific champion vs this enemy champ
                if my_champ and my_champ in matchups and enemy_champ in matchups[my_champ]:
                    s = matchups[my_champ][enemy_champ]
                    entry["my_champ_vs_enemy"] = {
                        "wins": s["wins"],
                        "losses": s["losses"],
                        "games": s["games"],
                        "winrate": s["winrate"],
                    }

                # Top 3 best picks against this enemy (for context)
                picks_vs = []
                for my_c, vs_map in matchups.items():
                    if enemy_champ in vs_map:
                        s = vs_map[enemy_champ]
                        if s["games"] >= 2:
                            picks_vs.append({"champion": my_c, **s})
                picks_vs.sort(key=lambda x: (-x["winrate"], -x["games"]))
                if picks_vs:
                    entry["best_picks"] = picks_vs[:3]

                if entry:
                    personal_matchups[enemy_champ] = entry

            result["personal_matchups"] = personal_matchups

            # Save AI prediction for this game (once per match)
            _save_prediction_if_new(result)

        _cache_set("live_detailed", result)
        return result
    except RiotAPIError as e:
        raise HTTPException(status_code=502, detail=e.message)


def cliente_aberto() -> bool:
    """O cliente do LoL está a correr? O lockfile só existe com ele aberto."""
    from lcu_api import parse_lockfile
    try:
        return parse_lockfile() is not None
    except Exception:                                        # noqa: BLE001
        return False


async def apanha_previsao_em_segundo_plano() -> str:
    """Grava a previsão da partida a decorrer, sem ninguém ter a página aberta.

    As previsões pararam a 17 de Junho e ele jogou 37 partidas em Julho: só se
    gravavam enquanto a página do LoL estava aberta, porque era o navegador a
    pedir a análise ao vivo. Agora é a app que pergunta."""
    if not cliente_aberto():
        return "cliente fechado"
    if not _riot_config.get("api_key"):
        return "sem chave da Riot"
    try:
        antes = len(_predicted_games)
        await get_live_detailed()          # grava a previsão se for jogo novo
        return "previsão guardada" if len(_predicted_games) > antes else "jogo já conhecido"
    except HTTPException as ex:
        return f"sem partida ({ex.detail})"[:120]
    except Exception as ex:                                  # noqa: BLE001
        return f"falhou: {ex}"[:120]


@router.get("/live-client/winprob")
async def live_client_winprob():
    """Live in-game win probability from the local Live Client Data API (port 2999).

    Only works while the user is in their own game (reads real game state: gold est.
    from CS+kills+towers, objectives from the event log). Far stronger than the
    pre-game predictor (~73% by 15 min in the literature vs ~61% pre-game)."""
    from live_winprob import get_live_win_probability
    return await get_live_win_probability()


# ── Riot API — Champion Mastery ──────────────────────────────────

@router.get("/riot/mastery")
async def get_mastery(top: int = Query(10, ge=1, le=50)):
    """Get top champion mastery data."""
    cache_key = f"mastery_{top}"
    cached = _cache_get(cache_key, ttl=600)
    if cached is not None:
        return cached
    api_key = _riot_config.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key não configurada.")
    try:
        mastery = await get_mastery_data(
            _riot_config["game_name"],
            _riot_config["tag_line"],
            api_key,
            top=top,
        )
        _cache_set(cache_key, mastery)
        return mastery
    except RiotAPIError as e:
        raise HTTPException(status_code=502, detail=e.message)


# ── Riot API — Match Timeline ───────────────────────────────────

@router.get("/riot/timeline/{match_id}")
async def get_game_timeline(match_id: str):
    """Get timeline analysis for a specific match."""
    api_key = _riot_config.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key não configurada.")
    try:
        puuid = await get_puuid(
            _riot_config["game_name"],
            _riot_config["tag_line"],
            api_key,
        )
        timeline = await get_match_timeline(match_id, api_key)
        parsed = parse_timeline(timeline, puuid)
        return {"match_id": match_id, **parsed}
    except RiotAPIError as e:
        raise HTTPException(status_code=502, detail=e.message)


# ── Riot API — Summoner Level ────────────────────────────────────

@router.get("/riot/summoner")
async def get_summoner():
    """Get account level and profile icon."""
    cached = _cache_get("summoner", ttl=600)
    if cached is not None:
        return cached
    api_key = _riot_config.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key não configurada.")
    try:
        result = await get_summoner_level(
            _riot_config["game_name"],
            _riot_config["tag_line"],
            api_key,
        )
        _cache_set("summoner", result)
        return result
    except RiotAPIError as e:
        raise HTTPException(status_code=502, detail=e.message)


# ── Riot API — Master Ranking Position ───────────────────────────

@router.get("/riot/position")
async def get_ranking_position():
    """Get the player's current ladder rank. Tries, in order: League of Graphs,
    op.gg (has the % of top), then the Riot Master+ ladder as a last resort."""
    cached = _cache_get("position", ttl=1800)
    if cached is not None:
        return cached
    try:
        result = await get_leagueofgraphs_ranking(
            _riot_config["game_name"],
            _riot_config["tag_line"],
        )
        # League of Graphs blocks scraping (403). Try op.gg next — it gives the
        # ladder rank with the top percentile, which the Riot API doesn't expose.
        if result is None:
            opgg = await get_opgg_profile(
                _riot_config["game_name"], _riot_config["tag_line"]
            )
            if opgg and opgg.get("euw_rank"):
                result = {
                    "euw_rank": opgg["euw_rank"],
                    "global_rank": None,
                    "top_percent": opgg.get("top_percent"),
                    "source": "op.gg",
                }
        # Last resort: the Riot Master+ ladder (no percentile, position only).
        if result is None:
            api_key = _riot_config.get("api_key", "")
            mp = await get_master_position(
                _riot_config["game_name"],
                _riot_config["tag_line"],
                api_key,
            ) if api_key else None
            if mp and mp.get("position"):
                result = {
                    "euw_rank": mp["position"],
                    "global_rank": None,
                    "top_percent": None,
                    "total_master_plus": mp.get("total_master_plus"),
                    "approximate": mp.get("approximate", False),
                    "source": "riot_master_ladder",
                }
            else:
                result = {"position": None, "message": "Não foi possível obter ranking"}

        if result.get("euw_rank") or result.get("global_rank"):
            # Save EU rank to today's snapshot
            _save_position_to_snapshot(result)
        _cache_set("position", result)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


def _save_position_to_snapshot(position: dict):
    """Update today's rank snapshot with EU/global ranking data."""
    try:
        db = SessionLocal()
        today = date.today()
        snap = db.query(LolRankSnapshot).filter(LolRankSnapshot.date == today).first()
        if snap:
            snap.euw_rank = position.get("euw_rank")
            snap.global_rank = position.get("global_rank")
            snap.top_percent = position.get("top_percent")
            db.commit()
        db.close()
    except Exception:
        pass


# ── Riot API — Peak LP & Ranking ─────────────────────────────────

@router.get("/riot/peak")
async def get_peak_stats(db: Session = Depends(get_db)):
    """Get peak LP and best EU ranking. Combines our own snapshots with op.gg's
    season peak ("Top Tier") — op.gg tracks LP continuously, so it recovers peaks
    we never captured ourselves."""
    snapshots = db.query(LolRankSnapshot).all()

    peak_lp_snap = None
    peak_effective = -1
    best_euw_snap = None
    best_euw_val = 999999

    for s in snapshots:
        if s.lp is not None and s.tier:
            effective = _effective_lp(s.tier, s.lp)
            if effective > peak_effective:
                peak_effective = effective
                peak_lp_snap = s
        if s.euw_rank and s.euw_rank < best_euw_val:
            best_euw_val = s.euw_rank
            best_euw_snap = s

    result: dict = {"has_data": bool(snapshots)}
    if peak_lp_snap:
        result["peak_lp"] = peak_lp_snap.lp
        result["peak_tier"] = peak_lp_snap.tier
        result["peak_rank"] = peak_lp_snap.rank
        result["peak_date"] = str(peak_lp_snap.date)
    if best_euw_snap:
        result["best_euw_rank"] = best_euw_snap.euw_rank
        result["best_global_rank"] = best_euw_snap.global_rank
        result["best_top_percent"] = best_euw_snap.top_percent
        result["best_rank_date"] = str(best_euw_snap.date)

    # Pull op.gg's data and merge: for each figure, keep whichever source is
    # better (higher peak LP, lower = better ladder rank).
    try:
        opgg = await get_opgg_profile(_riot_config["game_name"], _riot_config["tag_line"])
    except Exception:
        opgg = None
    if opgg:
        if opgg.get("peak_tier") and _effective_lp(opgg["peak_tier"], opgg["peak_lp"]) > max(peak_effective, 0):
            result["has_data"] = True
            result["peak_lp"] = opgg["peak_lp"]
            result["peak_tier"] = opgg["peak_tier"]
            result["peak_rank"] = None
            result["peak_source"] = "op.gg"
            result.pop("peak_date", None)
        if opgg.get("euw_rank") and opgg["euw_rank"] < best_euw_val:
            result["has_data"] = True
            result["best_euw_rank"] = opgg["euw_rank"]
            result["best_top_percent"] = opgg.get("top_percent")
            result["best_global_rank"] = None
            result["best_rank_source"] = "op.gg"
            result.pop("best_rank_date", None)

    return result


# ── Riot API — Replay Links ─────────────────────────────────────

@router.get("/riot/replays")
async def get_replays():
    """Get replay download links for recent matches."""
    api_key = _riot_config.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key não configurada.")
    try:
        return await get_replay_links(
            _riot_config["game_name"],
            _riot_config["tag_line"],
            api_key,
        )
    except RiotAPIError as e:
        raise HTTPException(status_code=502, detail=e.message)


# ── AI Predictions ───────────────────────────────────────────────

@router.get("/predictions")
def get_predictions(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Get AI prediction history with results."""
    preds = (
        db.query(LolPrediction)
        .order_by(LolPrediction.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": p.id,
            "date": str(p.date),
            "champion_played": p.champion_played,
            "champion_against": p.champion_against,
            "predicted_win": p.predicted_win,
            "confidence": p.confidence,
            "confidence_level": p.confidence_level,
            "actual_win": p.actual_win,
            "correct": p.correct,
            "match_id": p.match_id,
        }
        for p in preds
    ]


@router.get("/predictions/stats")
def get_prediction_stats(db: Session = Depends(get_db)):
    """Get AI prediction accuracy statistics."""
    import json as _json

    # Auto-resolve any pending predictions first
    _resolve_predictions(db)

    resolved = db.query(LolPrediction).filter(LolPrediction.actual_win.isnot(None)).all()
    all_preds = db.query(LolPrediction).count()
    unresolved = all_preds - len(resolved)

    if not resolved:
        return {
            "total_predictions": all_preds,
            "resolved": 0,
            "unresolved": unresolved,
            "correct": 0,
            "incorrect": 0,
            "accuracy": None,
            "by_confidence": {},
            "recent_streak": 0,
            "best_streak": 0,
        }

    correct = sum(1 for p in resolved if p.correct)
    incorrect = len(resolved) - correct
    accuracy = round(correct / len(resolved) * 100, 1)

    # Accuracy by confidence level
    by_conf: dict[str, dict] = {}
    for p in resolved:
        lvl = p.confidence_level or "low"
        if lvl not in by_conf:
            by_conf[lvl] = {"total": 0, "correct": 0}
        by_conf[lvl]["total"] += 1
        if p.correct:
            by_conf[lvl]["correct"] += 1

    for lvl, data in by_conf.items():
        data["accuracy"] = round(data["correct"] / data["total"] * 100, 1)

    # Streaks (ordered by date desc)
    ordered = sorted(resolved, key=lambda p: p.created_at or p.date, reverse=True)
    current_streak = 0
    for p in ordered:
        if p.correct:
            current_streak += 1
        else:
            break

    # Best streak ever
    best_streak = 0
    streak = 0
    for p in sorted(resolved, key=lambda p: p.created_at or p.date):
        if p.correct:
            streak += 1
            best_streak = max(best_streak, streak)
        else:
            streak = 0

    return {
        "total_predictions": all_preds,
        "resolved": len(resolved),
        "unresolved": unresolved,
        "correct": correct,
        "incorrect": incorrect,
        "accuracy": accuracy,
        "by_confidence": by_conf,
        "recent_streak": current_streak,
        "best_streak": best_streak,
    }


@router.post("/predictions/resolve")
def resolve_predictions_manual(db: Session = Depends(get_db)):
    """Manually resolve unresolved predictions by matching with existing games."""
    resolved_count = _resolve_predictions(db)
    if resolved_count == 0:
        return {"resolved": 0, "message": "Nenhuma previsão por resolver."}
    return {"resolved": resolved_count, "message": f"{resolved_count} previsão(ões) resolvida(s)."}


@router.get("/predictions/calibration")
def get_prediction_calibration(db: Session = Depends(get_db)):
    """Return calibration data: predicted probability bins vs actual win rate.

    This lets us see if the model is well-calibrated (e.g., when it predicts 70%,
    the actual win rate should be ~70%).
    """
    resolved = db.query(LolPrediction).filter(LolPrediction.actual_win.isnot(None)).all()
    if not resolved:
        return {"bins": [], "total": 0, "brier_score": None}

    # Build bins: 0-20, 20-30, 30-40, 40-50, 50-60, 60-70, 70-80, 80-100
    bin_edges = [(0, 20), (20, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 100)]
    bins = []

    for lo, hi in bin_edges:
        in_bin = []
        for p in resolved:
            prob = p.confidence if p.predicted_win else (100 - p.confidence)
            if lo <= prob < hi or (hi == 100 and prob == 100):
                in_bin.append(p)

        if in_bin:
            actual_wins = sum(1 for p in in_bin if p.actual_win)
            actual_wr = round(actual_wins / len(in_bin) * 100, 1)
            avg_predicted = round(sum(
                (p.confidence if p.predicted_win else (100 - p.confidence)) for p in in_bin
            ) / len(in_bin), 1)
            bins.append({
                "range": f"{lo}-{hi}%",
                "count": len(in_bin),
                "avg_predicted": avg_predicted,
                "actual_winrate": actual_wr,
                "deviation": round(actual_wr - avg_predicted, 1),
            })

    # Brier score (lower = better, 0 = perfect)
    brier_sum = 0.0
    for p in resolved:
        prob = (p.confidence if p.predicted_win else (100 - p.confidence)) / 100.0
        outcome = 1.0 if p.actual_win else 0.0
        brier_sum += (prob - outcome) ** 2
    brier_score = round(brier_sum / len(resolved), 4)

    return {
        "bins": bins,
        "total": len(resolved),
        "brier_score": brier_score,
    }


# ── Meta Stats ───────────────────────────────────────────────────

@router.get("/meta-stats")
async def get_meta_stats_endpoint(
    force: bool = Query(False),
    source: str = Query("all"),
):
    """Get global jungle champion stats from multiple sources (Master, EUW).
    source: 'all' or comma-separated list of: lolalytics,ugg,opgg,leagueofgraphs
    """
    from meta_stats import ALL_SOURCES
    import meta_stats as _ms

    sources_list = None
    if source and source != "all":
        sources_list = [s.strip() for s in source.split(",") if s.strip() in ALL_SOURCES]
        if not sources_list:
            sources_list = None

    meta = await fetch_meta_stats(force=force, sources=sources_list)
    if not meta:
        return {"loaded": False, "message": "Sem dados de meta stats"}
    # Sort by rank for display, include champion name in each entry
    champions = []
    for name, data in meta.items():
        ddragon_key = _to_ddragon_key(name)
        champions.append({"champion": name, "ddragon_key": ddragon_key, **data})
    champions.sort(key=lambda x: x.get("rank", 999))
    return {
        "loaded": True,
        "count": len(champions),
        "available_sources": list(_ms._source_cache.keys()),
        "active_sources": sources_list or list(_ms._source_cache.keys()),
        "champions": champions,
    }


# ── Insights de Jungle do patch ─────────────────────────────────

TIER_LABELS = {0: "S+", 2: "S", 4: "A", 6: "B", 9: "C", 12: "D"}

# Abaixo disto um campeão da tier list é ruído (off-meta pontual), não meta de jungle.
_JUNGLE_MIN_PR = 0.3


def _my_jungle_pool(db: Session, limit: int = 8) -> list[dict]:
    """Campeões de jungle do utilizador, por número de jogos."""
    games = (
        db.query(LolGame)
        .filter(LolGame.role == "jungle", LolGame.champion_played.isnot(None))
        .all()
    )
    agg: dict[str, dict] = {}
    for g in games:
        a = agg.setdefault(g.champion_played, {"games": 0, "wins": 0})
        a["games"] += 1
        a["wins"] += 1 if g.won else 0

    pool = [
        {
            "champion": champ,
            "games": a["games"],
            "wins": a["wins"],
            "losses": a["games"] - a["wins"],
            "winrate": round(a["wins"] / a["games"] * 100, 1),
        }
        for champ, a in agg.items()
    ]
    pool.sort(key=lambda p: -p["games"])
    return pool[:limit]


def _recent_jungle_form(db: Session, last_n: int = 20) -> dict:
    games = (
        db.query(LolGame)
        .filter(LolGame.role == "jungle")
        .order_by(LolGame.date.desc(), LolGame.id.desc())
        .limit(last_n)
        .all()
    )
    if not games:
        return {"games": 0}
    wins = sum(1 for g in games if g.won)
    deaths = [g.deaths for g in games if g.deaths is not None]
    return {
        "games": len(games),
        "wins": wins,
        "winrate": round(wins / len(games) * 100, 1),
        "avg_deaths": round(sum(deaths) / len(deaths), 1) if deaths else None,
    }


@router.get("/jungle/patch")
async def jungle_patch():
    """Patch actual + notas relevantes para a jungle (campeões de jungle, itens e sistemas)."""
    import jungle_meta as jm

    patch, notes, meta = await asyncio.gather(
        jm.get_patch(), jm.get_patch_notes(), fetch_meta_stats(), return_exceptions=True
    )
    patch = patch if isinstance(patch, dict) else {}
    notes = notes if isinstance(notes, dict) else None
    meta = meta if isinstance(meta, dict) else None

    if not notes:
        return {"patch": patch, "notes": None, "message": "Notas do patch indisponíveis"}

    jungle_names = {n for n, d in (meta or {}).items() if d.get("pr", 0) >= _JUNGLE_MIN_PR}

    champions = []
    for block in notes["champions"]:
        slug = canon_slug(block["name"])
        entry = (meta or {}).get(slug) or {}
        champions.append({
            **block,
            "champion_slug": slug,
            "is_jungle": slug in jungle_names,
            "winrate": entry.get("wr"),
            "pickrate": entry.get("pr"),
            "tier": TIER_LABELS.get(entry.get("tier")) if entry else None,
        })

    return {
        "patch": patch,
        "notes": {
            "patch": notes["patch"],
            "url": notes["url"],
            "is_current": notes.get("is_current", True),
            "champions": champions,
            "jungle_champions": [c for c in champions if c["is_jungle"]],
            "items": notes["items"],
            "systems": notes["systems"],
        },
    }


@router.get("/jungle/insights")
async def jungle_insights(top: int = Query(15, ge=5, le=40), db: Session = Depends(get_db)):
    """Painel de meta de jungle: patch, tier list EUW Master e o pool do utilizador
    cruzado com a meta (WR pessoal vs WR global, tier e se levou mexidas no patch)."""
    import jungle_meta as jm

    patch_res, notes, meta = await asyncio.gather(
        jm.get_patch(), jm.get_patch_notes(), fetch_meta_stats(), return_exceptions=True
    )
    patch = patch_res if isinstance(patch_res, dict) else {}
    notes = notes if isinstance(notes, dict) else None
    meta = meta if isinstance(meta, dict) else None

    # Campeões mexidos neste patch, por slug → resumo das alterações
    touched: dict[str, dict] = {}
    if notes:
        for block in notes["champions"]:
            touched[canon_slug(block["name"])] = {
                "name": block["name"],
                "context": block["context"],
                "changes": [c["text"] for g in block["groups"] for c in g["changes"]],
            }

    tier_list = []
    if meta:
        entries = [
            {"champion": name, "ddragon_key": _to_ddragon_key(name), **data}
            for name, data in meta.items()
            if data.get("pr", 0) >= _JUNGLE_MIN_PR
        ]
        entries.sort(key=lambda e: (e.get("tier", 99), -e.get("wr", 0)))
        for e in entries[:top]:
            tier_list.append({
                "champion": e["champion"],
                "ddragon_key": e["ddragon_key"],
                "winrate": e.get("wr"),
                "pickrate": e.get("pr"),
                "banrate": e.get("br"),
                "games": e.get("games"),
                "tier": TIER_LABELS.get(e.get("tier"), "—"),
                "delta": e.get("delta"),
                "sources": e.get("source", ""),
                "patch_changes": touched.get(e["champion"]),
            })

    avg_wr = None
    if meta:
        wrs = [d["wr"] for d in meta.values() if d.get("games", 0) > 50]
        avg_wr = round(sum(wrs) / len(wrs), 2) if wrs else None

    pool = []
    for p in _my_jungle_pool(db):
        slug = canon_slug(p["champion"])
        entry = (meta or {}).get(slug) or {}
        meta_wr = entry.get("wr")
        pool.append({
            **p,
            "champion_slug": slug,
            "meta_winrate": meta_wr,
            "tier": TIER_LABELS.get(entry.get("tier")) if entry else None,
            "pickrate": entry.get("pr"),
            "delta": entry.get("delta"),
            "edge": round(p["winrate"] - meta_wr, 1) if meta_wr else None,
            "patch_changes": touched.get(slug),
        })

    return {
        "patch": patch,
        "patch_notes_url": notes["url"] if notes else None,
        "patch_is_current": notes.get("is_current") if notes else None,
        "rank": "EUW · Master+",
        "average_winrate": avg_wr,
        "tier_list": tier_list,
        "my_pool": pool,
        "jungle_system_changes": notes["systems"] if notes else [],
        "jungle_champion_changes": [
            {**t, "champion_slug": s, "ddragon_key": _to_ddragon_key(s)}
            for s, t in touched.items()
            if meta and (meta.get(s, {}).get("pr", 0) >= _JUNGLE_MIN_PR)
        ],
        "recent_form": _recent_jungle_form(db),
    }


@router.get("/jungle/build/{champion}")
async def jungle_build(champion: str):
    """Build de jungle (Master+) de um campeão, com nomes e ícones já resolvidos."""
    import jungle_meta as jm

    build, assets = await asyncio.gather(jm.fetch_build(champion), jm.get_assets(), return_exceptions=True)
    if isinstance(build, Exception) or not build:
        raise HTTPException(status_code=404, detail=f"Sem build de jungle para {champion}")
    assets = assets if isinstance(assets, dict) else {"items": {}, "spells": {}, "runes": {}}

    items, spells, runes = assets.get("items", {}), assets.get("spells", {}), assets.get("runes", {})

    def _named(ids, table):
        out = []
        for i in ids or []:
            info = table.get(str(i)) or {}
            out.append({"id": i, "name": info.get("name") or str(i), "icon": info.get("icon"), "desc": info.get("desc")})
        return out

    for b in build["builds"]:
        b["starting_items"]["resolved"] = _named(b["starting_items"]["ids"], items)
        b["core_items"]["resolved"] = _named(b["core_items"]["ids"], items)
        for slot in ("item4", "item5", "item6"):
            for opt in b[slot]:
                info = items.get(str(opt["id"])) or {}
                opt["name"] = info.get("name") or str(opt["id"])
                opt["icon"] = info.get("icon")
        b["runes"]["primary_resolved"] = _named(b["runes"]["primary"], runes)
        b["runes"]["secondary_resolved"] = _named(b["runes"]["secondary"], runes)
        b["runes"]["shards_resolved"] = _named(b["runes"]["shards"], runes)
        b["summoners"]["resolved"] = _named(b["summoners"]["ids"], spells)

    return build


# Dicas: geradas pela IA e guardadas por patch (mudam quando o patch muda).
_tips_cache: dict[str, tuple[float, dict]] = {}
TIPS_TTL = 24 * 3600
# Quando a IA não responde (rate limit, por exemplo), o pedido custava ~1 minuto
# de chamadas de rede e era repetido a cada abertura do ecrã. A falha também fica
# guardada por uns minutos, e entretanto mostra-se a última resposta boa.
TIPS_TTL_FALHA = 20 * 60
_tips_falha: dict[str, float] = {}

_TIPS_CONTEXT = """És um coach de League of Legends especializado em JUNGLE a nível Master/Challenger na EUW.

Contexto do jogador:
- Rank: {rank} ({lp} LP). Role: jungle.
- Patch actual: {patch} (notas oficiais: {notes_url})
- Pool de jungle dele (jogos, winrate pessoal vs winrate global no Master+):
{pool}
- Forma recente (últimos {form_games} jogos de jungle): {form_wr}% WR, média de {form_deaths} mortes por jogo.
- Média global de KDA dele: {kda}. Média de mortes por jogo: {avg_deaths}.

Alterações deste patch com impacto na jungle:
{changes}

Meta de jungle no Master+ EUW agora (top picks por tier):
{tierlist}

Regras: português de Portugal, sem enchimento, sem frases genéricas tipo "faz bom CS".
Cada dica específica ao patch {patch}, ao rank Master+ e ao pool dele, com números
(timings, níveis, tempos de camp) sempre que fizer sentido.
Responde APENAS com JSON válido, sem texto à volta."""

# O agente corta a resposta aos 120s, por isso as dicas são pedidas em blocos pequenos
# e em paralelo em vez de um JSON gigante que nunca chega ao fim.
_TIPS_CHUNKS: list[tuple[str, str]] = [
    ("macro", """{context}

Pesquisa na web como se está a jogar a jungle no patch {patch} a nível Master+ e devolve:
{{
  "patch_impact": ["4-5 frases sobre o que este patch muda concretamente para ele e para a jungle"],
  "pathing": ["6-7 dicas de clear e pathing: rotas por primeiro camp, tempos de clear, full clear vs 3-camp gank, como trackar o jungler inimigo"],
  "objectives": ["5-6 dicas de controlo de objectivos: setup de dragão/arauto/baron/atakhan, timings, prio de wave, quando trocar"]
}}"""),
    ("play", """{context}

Devolve:
{{
  "matchups": ["6-7 dicas de matchup contra os junglers mais jogados da meta actual listada acima, um a um"],
  "fix_my_game": ["6-7 correcções concretas baseadas nos números dele: {avg_deaths} mortes/jogo, {form_wr}% nos últimos {form_games} jogos"]
}}"""),
    ("champs_a", """{context}

Só para estes campeões: {champs_a}. Devolve:
{{
  "champion_tips": [
    {{"champion": "<nome>", "verdict": "uma frase: vale a pena jogá-lo neste patch e porquê",
      "tips": ["5-6 dicas específicas: combos, power spikes, o que fazer early/mid/late, erros típicos"]}}
  ]
}}"""),
    ("champs_b", """{context}

Só para estes campeões: {champs_b}. Devolve:
{{
  "champion_tips": [
    {{"champion": "<nome>", "verdict": "uma frase: vale a pena jogá-lo neste patch e porquê",
      "tips": ["5-6 dicas específicas: combos, power spikes, o que fazer early/mid/late, erros típicos"]}}
  ]
}}"""),
]


def _repair_json(text: str):
    """Último recurso quando a resposta vem cortada a meio: fecha o que ficou aberto.

    O agente corta aos 120s, e uma resposta quase completa vale mais do que nada."""
    from ai_config import extract_json

    data = extract_json(text)
    if data is not None:
        return data
    start = text.find("{")
    if start < 0:
        return None
    frag = text[start:]
    # Corta no último elemento fechado para não deixar um valor a meio.
    cut = max(frag.rfind('"]'), frag.rfind("}"), frag.rfind("]"))
    if cut < 0:
        return None
    frag = frag[: cut + (2 if frag[cut:cut + 2] == '"]' else 1)]
    for _ in range(6):
        try:
            return json.loads(frag)
        except json.JSONDecodeError as e:
            if "Expecting" in str(e) or "Unterminated" in str(e):
                opens = frag.count("[") - frag.count("]")
                braces = frag.count("{") - frag.count("}")
                if opens <= 0 and braces <= 0:
                    return None
                frag += "]" * max(opens, 0) + "}" * max(braces, 0)
            else:
                return None
    return None


# Último patch conhecido: serve de chave para responder da cache sem ir à rede.
_ultimo_patch: dict[str, str] = {"label": ""}


@router.get("/jungle/tips")
async def jungle_tips(force: bool = Query(False), db: Session = Depends(get_db)):
    """Dicas de jungle geradas pela IA (com pesquisa web), ancoradas no patch actual,
    no rank do utilizador e nas suas estatísticas reais. Cache por patch (24h)."""
    import jungle_meta as jm
    from ai_config import ask_agent_async, ai_status

    # A resposta guardada é devolvida antes de ir buscar patch e meta: essas três
    # chamadas de rede demoravam ~1 minuto mesmo quando já havia resposta pronta,
    # e o ecrã ficava à espera à mesma.
    if not force and _ultimo_patch["label"]:
        etiqueta = _ultimo_patch["label"]
        pronto = _tips_cache.get(etiqueta)
        if pronto and time.time() - pronto[0] < TIPS_TTL:
            return {**pronto[1], "cached": True}
        falhou_ha_pouco = time.time() - _tips_falha.get(etiqueta, 0) < TIPS_TTL_FALHA
        if falhou_ha_pouco:
            if pronto:
                return {**pronto[1], "cached": True, "stale": True,
                        "message": "A IA não respondeu há pouco; estas dicas são as anteriores."}
            return {"patch": etiqueta, "generated": False, "cached": True,
                    "message": "A IA não respondeu há pouco. Tenta daqui a bocado."}

    patch_res, notes, meta = await asyncio.gather(
        jm.get_patch(), jm.get_patch_notes(), fetch_meta_stats(), return_exceptions=True
    )
    patch = patch_res if isinstance(patch_res, dict) else {}
    notes = notes if isinstance(notes, dict) else None
    meta = meta if isinstance(meta, dict) else None
    patch_label = patch.get("site") or patch.get("short") or "actual"

    cache_key = str(patch_label)
    _ultimo_patch["label"] = cache_key
    if not force:
        hit = _tips_cache.get(cache_key)
        if hit and time.time() - hit[0] < TIPS_TTL:
            return {**hit[1], "cached": True}

    pool = _my_jungle_pool(db, limit=6)
    pool_lines = []
    for p in pool:
        entry = (meta or {}).get(canon_slug(p["champion"])) or {}
        meta_wr = entry.get("wr")
        pool_lines.append(
            f"  - {p['champion']}: {p['games']} jogos, {p['winrate']}% pessoal"
            + (f" vs {meta_wr}% global (tier {TIER_LABELS.get(entry.get('tier'), '?')})" if meta_wr else "")
        )

    changes = []
    if notes:
        for s in notes["systems"]:
            for g in s["groups"]:
                for c in g["changes"]:
                    changes.append(f"  - [Sistema] {s['name']}: {c['text']}")
        for block in notes["champions"]:
            slug = canon_slug(block["name"])
            if meta and meta.get(slug, {}).get("pr", 0) >= _JUNGLE_MIN_PR:
                lines = "; ".join(c["text"] for g in block["groups"] for c in g["changes"])
                changes.append(f"  - [Campeão jungle] {block['name']}: {lines}")
        for it in notes["items"]:
            lines = "; ".join(c["text"] for g in it["groups"] for c in g["changes"])
            changes.append(f"  - [Item] {it['name']}: {lines}")

    tierlist_lines = []
    if meta:
        entries = [(n, d) for n, d in meta.items() if d.get("pr", 0) >= _JUNGLE_MIN_PR]
        entries.sort(key=lambda e: (e[1].get("tier", 99), -e[1].get("wr", 0)))
        for name, d in entries[:12]:
            tierlist_lines.append(
                f"  - {_to_ddragon_key(name)}: tier {TIER_LABELS.get(d.get('tier'), '?')}, "
                f"{d.get('wr')}% WR, {d.get('pr')}% pick"
            )

    form = _recent_jungle_form(db)
    rank_info = _cache_get("rank", ttl=3600) or {}
    if not rank_info and _riot_config.get("api_key"):
        try:
            rank_info = await get_rank_info(
                _riot_config["game_name"], _riot_config["tag_line"], _riot_config["api_key"]
            ) or {}
        except Exception:
            rank_info = {}

    all_jungle = db.query(LolGame).filter(LolGame.role == "jungle").all()
    deaths = [g.deaths for g in all_jungle if g.deaths is not None]
    kills = [g.kills for g in all_jungle if g.kills is not None]
    assists = [g.assists for g in all_jungle if g.assists is not None]
    avg_deaths = round(sum(deaths) / len(deaths), 1) if deaths else 0
    kda = round((sum(kills) + sum(assists)) / max(sum(deaths), 1), 2) if deaths else 0

    champ_names = [p["champion"] for p in pool]
    half = (len(champ_names) + 1) // 2
    fmt = {
        "rank": f"{rank_info.get('tier', 'Master')} {rank_info.get('rank') or ''}".strip(),
        "lp": rank_info.get("lp", "?"),
        "patch": patch_label,
        "notes_url": (notes or {}).get("url", "n/d"),
        "pool": "\n".join(pool_lines) or "  (sem jogos de jungle registados)",
        "form_games": form.get("games", 0),
        "form_wr": form.get("winrate", "?"),
        "form_deaths": form.get("avg_deaths", "?"),
        "kda": kda,
        "avg_deaths": avg_deaths,
        "changes": "\n".join(changes) or "  (sem alterações relevantes detectadas)",
        "tierlist": "\n".join(tierlist_lines) or "  (tier list indisponível)",
        "champs_a": ", ".join(champ_names[:half]) or "—",
        "champs_b": ", ".join(champ_names[half:]) or "—",
    }
    context = _TIPS_CONTEXT.format(**fmt)

    results = await asyncio.gather(
        *(ask_agent_async(tpl.format(context=context, **fmt), timeout=200.0, feature="outro") for _, tpl in _TIPS_CHUNKS),
        return_exceptions=True,
    )

    tips: dict = {}
    failed = []
    for (name, _), raw in zip(_TIPS_CHUNKS, results):
        if isinstance(raw, Exception) or not raw:
            failed.append(name)
            continue
        data = _repair_json(raw)
        if not isinstance(data, dict):
            failed.append(name)
            continue
        for key, value in data.items():
            if key == "champion_tips":
                tips.setdefault("champion_tips", []).extend(value or [])
            elif value:
                tips[key] = value

    if not tips:
        _tips_falha[cache_key] = time.time()
        anterior = _tips_cache.get(cache_key)
        if anterior:
            return {**anterior[1], "cached": True, "stale": True,
                    "message": "A IA não respondeu agora; estas dicas são as anteriores."}
        return {
            "patch": patch_label,
            "generated": False,
            "message": "A IA não devolveu dicas. Tenta outra vez daqui a pouco.",
            "ai_status": ai_status(),
        }

    result = {
        "patch": patch_label,
        "generated": True,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tips": tips,
        "partial": failed or None,
        "cached": False,
    }
    _tips_cache[cache_key] = (time.time(), result)
    _tips_falha.pop(cache_key, None)
    return result


# ── Champ Select Helper ─────────────────────────────────────────


def _build_matchup_stats_from_db() -> dict:
    """Build matchup stats from the local database (no API calls)."""
    db = SessionLocal()
    try:
        games = (
            db.query(LolGame)
            .filter(
                LolGame.role == "jungle",
                LolGame.champion_played.isnot(None),
                LolGame.champion_against.isnot(None),
            )
            .order_by(LolGame.date.desc())
            .all()
        )

        matchups: dict[str, dict[str, dict]] = {}
        champ_totals: dict[str, dict] = {}
        weighted_matchups: dict[str, dict[str, dict]] = {}
        weighted_totals: dict[str, dict] = {}
        RECENCY_DECAY = 0.99

        for idx, game in enumerate(games):
            my_champ = game.champion_played
            vs_champ = game.champion_against
            won = game.won
            weight = RECENCY_DECAY ** idx

            matchups.setdefault(my_champ, {}).setdefault(
                vs_champ, {"wins": 0, "losses": 0, "games": 0}
            )
            matchups[my_champ][vs_champ]["games"] += 1
            if won:
                matchups[my_champ][vs_champ]["wins"] += 1
            else:
                matchups[my_champ][vs_champ]["losses"] += 1

            champ_totals.setdefault(my_champ, {"wins": 0, "losses": 0, "games": 0})
            champ_totals[my_champ]["games"] += 1
            if won:
                champ_totals[my_champ]["wins"] += 1
            else:
                champ_totals[my_champ]["losses"] += 1

            weighted_matchups.setdefault(my_champ, {}).setdefault(
                vs_champ, {"wins": 0.0, "losses": 0.0, "games": 0.0}
            )
            weighted_matchups[my_champ][vs_champ]["games"] += weight
            if won:
                weighted_matchups[my_champ][vs_champ]["wins"] += weight
            else:
                weighted_matchups[my_champ][vs_champ]["losses"] += weight

            weighted_totals.setdefault(my_champ, {"wins": 0.0, "losses": 0.0, "games": 0.0})
            weighted_totals[my_champ]["games"] += weight
            if won:
                weighted_totals[my_champ]["wins"] += weight
            else:
                weighted_totals[my_champ]["losses"] += weight

        for champ, vs_map in matchups.items():
            for vs, stats in vs_map.items():
                stats["winrate"] = round(stats["wins"] / stats["games"] * 100) if stats["games"] > 0 else 0

        for champ, stats in champ_totals.items():
            stats["winrate"] = round(stats["wins"] / stats["games"] * 100) if stats["games"] > 0 else 0

        return {
            "matchups": matchups,
            "champion_totals": champ_totals,
            "weighted_matchups": weighted_matchups,
            "weighted_totals": weighted_totals,
            "total_games_analyzed": sum(s["games"] for s in champ_totals.values()),
        }
    finally:
        db.close()


def _historico_contra(db: Session, inimigo: str, meu_pick: str | None) -> dict | None:
    """Os jogos dele contra este jungler: o total, campeão a campeão, e os jogos
    um a um do campeão que ele tem escolhido agora.

    É a pergunta que ele faz em champ select — "já joguei isto contra ele?" — e
    a resposta estava na base há 500 jogos sem ter sítio nenhum na página."""
    alvo = canon_slug(inimigo)
    jogos = [
        g for g in db.query(LolGame)
        .filter(LolGame.role == "jungle",
                LolGame.champion_played.isnot(None),
                LolGame.champion_against.isnot(None))
        .order_by(LolGame.date.desc()).all()
        if canon_slug(g.champion_against) == alvo
    ]
    if not jogos:
        return None

    por_campeao: dict[str, dict] = {}
    for g in jogos:
        d = por_campeao.setdefault(g.champion_played, {"champion": g.champion_played,
                                                       "wins": 0, "losses": 0})
        d["wins" if g.won else "losses"] += 1
    linhas = []
    for d in por_campeao.values():
        n = d["wins"] + d["losses"]
        linhas.append({**d, "games": n, "winrate": round(d["wins"] / n * 100)})
    linhas.sort(key=lambda x: (-x["games"], -x["winrate"]))

    pick = canon_slug(meu_pick) if meu_pick else None
    meus = [
        {
            "date": g.date.isoformat(),
            "won": bool(g.won),
            "kda": f"{g.kills}/{g.deaths}/{g.assists}"
                   if g.kills is not None and g.deaths is not None and g.assists is not None
                   else None,
        }
        for g in jogos if pick and canon_slug(g.champion_played) == pick
    ]
    vitorias = sum(1 for g in jogos if g.won)
    return {
        "enemy": inimigo,
        "games": len(jogos),
        "wins": vitorias,
        "losses": len(jogos) - vitorias,
        "winrate": round(vitorias / len(jogos) * 100),
        "by_champion": linhas,
        "current_pick": meu_pick,
        "current_pick_games": meus,
    }


async def _get_enemy_counters(enemy_names: list[str]) -> dict:
    """For each visible enemy, return user's picks vs that champion sorted by games.
    Matches by canonical slug so a typed display name (e.g. 'Wukong') lines up with
    the DDragon key stored in the DB ('MonkeyKing')."""
    data = get_matchup_data()
    if not data:
        return {}
    matchups = data.get("matchups", {})
    await _ensure_slug_map()
    counters: dict[str, list] = {}
    for enemy in enemy_names:
        enemy_slug = canon_slug(enemy)
        picks_vs: list[dict] = []
        for my_champ, vs_map in matchups.items():
            for vs_champ, s in vs_map.items():
                if canon_slug(vs_champ) != enemy_slug:
                    continue
                picks_vs.append({
                    "champion": my_champ,
                    "wins": s["wins"],
                    "losses": s["losses"],
                    "games": s["games"],
                    "winrate": s["winrate"],
                })
        picks_vs.sort(key=lambda x: (-x["games"], -x["winrate"]))
        counters[enemy] = picks_vs
    return counters


async def _ensure_matchup_data():
    """Load matchup stats from DB."""
    cached = _cache_get("matchup_stats", ttl=300)
    if cached is not None:
        set_matchup_data(cached)
        return

    if get_matchup_data() is not None:
        return

    data = _build_matchup_stats_from_db()
    set_matchup_data(data)
    _cache_set("matchup_stats", data)


@router.get("/riot/matchups")
async def get_matchups(force: bool = Query(False)):
    """Get personal matchup stats from match history."""
    if force:
        _response_cache.pop("matchup_stats", None)
        set_matchup_data(None)

    await _ensure_matchup_data()
    data = get_matchup_data()
    if not data:
        return {"loaded": False, "message": "Sem dados de matchup"}
    return {"loaded": True, **data}


@router.get("/riot/counters/{champion_name}")
async def get_counters_for_champion(champion_name: str):
    """Get user's personal counter picks against a specific champion."""
    await _ensure_matchup_data()
    counters = await _get_enemy_counters([champion_name])
    return {"champion": champion_name, "counters": counters.get(champion_name, [])}


@router.get("/champions-list")
async def champions_list():
    """Lista todos os champions actuais (DDragon) para autocomplete no UI."""
    await ensure_champion_data()
    from champion_data import _champion_cache
    if not _champion_cache:
        return []
    out = []
    for ddkey, data in _champion_cache.items():
        out.append({
            "ddragon_key": ddkey,
            "name": data.get("name", ddkey),
            "title": data.get("title", ""),
        })
    out.sort(key=lambda x: x["name"])
    return out


@router.get("/counter-pick")
async def counter_pick(
    enemy: str = Query(..., min_length=2),
    role: str = Query("jungle"),
):
    """Suggest picks against `enemy`. Returns:
    - personal: from the user's own match history (sorted by games, then WR)
    - counters: champions that beat `enemy` (op.gg EUW Master+), hardest first
    - strong_against: champions `enemy` beats (op.gg EUW Master+), biggest gap first
    """
    from meta_stats import fetch_external_counters

    await _ensure_matchup_data()
    personal_map = await _get_enemy_counters([enemy])
    personal = personal_map.get(enemy, [])

    try:
        external = await fetch_external_counters(enemy, role=role)
    except Exception as e:
        logger.warning(f"external counters failed for {enemy}: {e}")
        external = {"counters": [], "strong_against": []}

    return {
        "enemy": enemy,
        "role": role,
        "personal": personal,
        "counters": external.get("counters", []),
        "strong_against": external.get("strong_against", []),
    }


@router.get("/champ-select/status")
async def champ_select_status():
    """Check if League Client is running and if we're in champ select."""
    client_ok = await is_client_running()
    if not client_ok:
        # Fora do Mac não há cliente para ver: vale o que o agente do Mac
        # empurrou há segundos (ver `lol_live`).
        import lol_live
        remoto = lol_live.estado()
        if remoto and remoto.get("client_running"):
            fase = remoto.get("phase")
            aquece_lane_shares()
            return {"client_running": True, "phase": fase,
                    "in_champ_select": fase == "ChampSelect", "source": "agente"}
        return {"client_running": False, "phase": None, "in_champ_select": False}

    phase = await get_gameflow_phase()
    # Com o cliente aberto, aquece-se já quem se joga em que lane: quando ele
    # entrar em champ select a resposta tem de ser imediata.
    aquece_lane_shares()
    return {
        "client_running": True,
        "phase": phase,
        "in_champ_select": phase == "ChampSelect",
    }


@router.get("/champ-select/session")
async def champ_select_data(db: Session = Depends(get_db)):
    """Get full champ select analysis: picks, bans, team comp, suggestions."""
    await ensure_champion_data()

    import lol_live
    session = await get_champ_select_session()
    if session is None:
        remoto = lol_live.estado()
        session = (remoto or {}).get("session")
    else:
        lol_live.lembra_draft(session)
    if session is None:
        return {"active": False, "message": "Não estás em champ select"}

    # Extract picks from both teams
    my_team_raw = session.get("myTeam", [])
    their_team_raw = session.get("theirTeam", [])

    my_team = []
    for p in my_team_raw:
        cid = p.get("championId", 0)
        my_team.append({
            "champion_id": cid,
            "champion_name": champion_name(cid) if cid else None,
            "position": p.get("assignedPosition", ""),
            "pick_intent": p.get("championPickIntent", 0),
            "spell1": p.get("spell1Id", 0),
            "spell2": p.get("spell2Id", 0),
            "is_local_player": p.get("cellId", -1) == session.get("localPlayerCellId", -2),
        })

    their_team = []
    for p in their_team_raw:
        cid = p.get("championId", 0)
        their_team.append({
            "champion_id": cid,
            "champion_name": champion_name(cid) if cid else None,
            "position": p.get("assignedPosition", ""),
        })

    # Extract bans
    bans = session.get("bans", {})
    my_bans = [champion_name(b) for b in bans.get("myTeamBans", []) if b > 0]
    their_bans = [champion_name(b) for b in bans.get("theirTeamBans", []) if b > 0]

    # Team comp analysis
    my_ids = [p.get("championId", 0) for p in my_team_raw if p.get("championId", 0) > 0]
    their_ids = [p.get("championId", 0) for p in their_team_raw if p.get("championId", 0) > 0]

    my_comp = analyze_team_comp(my_ids)
    their_comp = analyze_team_comp(their_ids)

    # Ensure matchup data is loaded for suggestions
    await _ensure_matchup_data()

    # Use cached meta stats (non-blocking). Kick off background refresh if needed.
    await _ensure_meta_warmed()
    cached_meta = get_meta_stats()

    # O matchup só se pede ao jungler adversário: a lolalytics dá matchups por
    # lane, e perguntar-lhe o que o top laner deles faz contra um jungler seria
    # ler uma tabela que não existe. Sem posições atribuídas fica só o meta e o
    # à-vontade dele — que já é melhor do que o que havia.
    jungler_inimigo = next(
        (p["champion_name"] for p in their_team
         if (p.get("position") or "").lower() == "jungle" and p.get("champion_name")),
        None,
    )
    # O LCU manda `assignedPosition` só para a equipa dele: os cinco inimigos vêm
    # sem posição nenhuma, e era por isso que o champ select ficava sempre "sem
    # jungler adversário conhecido" — sem matchup, sem histórico, sem counter
    # pick. Quem se joga em que lane sabe-se do meta: a Kindred é jungler em 100%
    # dos jogos dela e o Sylas em 43%, por isso num draft com os dois o smite é
    # dela. Só se aponta alguém acima de 15% — não se adivinha.
    fonte_do_jungler = "cliente" if jungler_inimigo else None
    if not jungler_inimigo:
        aquece_lane_shares()
        jungler_inimigo = lane_provavel_cached(
            [p["champion_name"] for p in their_team if p.get("champion_name")]
        )
        if jungler_inimigo:
            fonte_do_jungler = "inferido"
    # O lado sabe-se aqui: as cinco primeiras cadeiras são o lado azul. É a única
    # coisa do champ select que ele não escolhe e que mais lhe muda o jogo — 12,4
    # pontos de winrate entre os dois lados, e o mecanismo é ele jogar em casa
    # quando está de blue. Não muda a escolha do campeão; muda o que ele vai fazer
    # nos primeiros dez minutos.
    cadeira = session.get("localPlayerCellId", -1)
    meu_lado = "blue" if 0 <= cadeira <= 4 else "red" if cadeira >= 5 else None
    aviso_do_lado = _aviso_do_lado(db, meu_lado) if meu_lado else None

    ja_escolhidos = [
        n for n in (
            [p["champion_name"] for p in my_team if p.get("champion_name")]
            + [p["champion_name"] for p in their_team if p.get("champion_name")]
            + my_bans + their_bans
        ) if n
    ]
    meus_aliados = [
        p["champion_name"] for p in my_team
        if p.get("champion_name") and not p.get("is_local_player")
    ]
    try:
        recomendacao = await _recomenda(
            db, [jungler_inimigo] if jungler_inimigo else [], my_ids,
            indisponiveis=ja_escolhidos, aliados=meus_aliados,
        )
    except Exception as e:
        logger.warning(f"champ select: recomendação falhou ({e})")
        recomendacao = {"pool": [], "meta": [], "spread": 0}


    # Enemy counters: for each visible enemy champ, user's picks vs them
    enemy_key_names = [_id_to_key.get(cid, "") for cid in their_ids if cid != 0]
    enemy_counters = await _get_enemy_counters([n for n in enemy_key_names if n])

    # O que ele já fez contra este jungler, com o campeão que tem em mãos.
    eu = next((p for p in my_team if p.get("is_local_player")), None)
    meu_pick = (eu or {}).get("champion_name") or (
        champion_name(eu["pick_intent"]) if eu and eu.get("pick_intent") else None
    )
    historico_vs_jungler = (
        _historico_contra(db, jungler_inimigo, meu_pick) if jungler_inimigo else None
    )

    # Timer info
    timer = session.get("timer", {})

    return {
        "active": True,
        "my_team": my_team,
        "their_team": their_team,
        "my_bans": my_bans,
        "their_bans": their_bans,
        "my_comp": my_comp,
        "their_comp": their_comp,
        "picks": recomendacao,
        "my_side": meu_lado,
        "side_note": aviso_do_lado,
        "enemy_jungler": jungler_inimigo,
        "enemy_jungler_source": fonte_do_jungler,
        "enemy_counters": enemy_counters,
        "vs_enemy_jungler": historico_vs_jungler,
        "my_pick": meu_pick,
        "phase": timer.get("phase", ""),
        "timer_remaining": timer.get("adjustedTimeLeftInPhase", 0),
    }


# ── Seasons ─────────────────────────────────────────────────────

class SeasonRenameBody(BaseModel):
    label: str


@router.get("/seasons")
def list_seasons(db: Session = Depends(get_db)):
    """All seasons with totals — most recent first; active season at top."""
    seasons = db.query(LolSeason).order_by(LolSeason.id.desc()).all()
    out = []
    for s in seasons:
        out.append({
            "id": s.id,
            "label": s.label,
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "end_date": s.end_date.isoformat() if s.end_date else None,
            "active": s.end_date is None,
            "peak_tier": s.peak_tier,
            "peak_rank": s.peak_rank,
            "peak_lp": s.peak_lp,
            "final_tier": s.final_tier,
            "final_rank": s.final_rank,
            "final_lp": s.final_lp,
            "total_games": s.total_games or 0,
            "total_wins": s.total_wins or 0,
            "total_losses": s.total_losses or 0,
        })
    return out


@router.get("/seasons/{season_id}/stats")
def season_id_stats(season_id: int, db: Session = Depends(get_db)):
    """Stats scoped to a specific season (same shape as /season-stats)."""
    games = db.query(LolGame).filter(LolGame.season_id == season_id).all()
    total = len(games)
    if total == 0:
        return {"season_id": season_id, "total": 0, "wins": 0, "losses": 0,
                "winrate": 0, "best_matchups": [], "worst_matchups": []}

    wins = sum(1 for g in games if g.won)
    losses = total - wins

    matchups: dict[tuple[str, str], dict] = {}
    for g in games:
        cp, ca = g.champion_played, g.champion_against
        if not cp or not ca:
            continue
        key = (cp, ca)
        if key not in matchups:
            matchups[key] = {"wins": 0, "losses": 0}
        if g.won:
            matchups[key]["wins"] += 1
        else:
            matchups[key]["losses"] += 1

    matchup_list = []
    for (cp, ca), data in matchups.items():
        gc = data["wins"] + data["losses"]
        if gc < 2:
            continue
        wr = round(data["wins"] / gc * 100, 1)
        matchup_list.append({"champion_played": cp, "champion_against": ca,
                              "wins": data["wins"], "losses": data["losses"],
                              "games": gc, "winrate": wr})

    best = sorted(matchup_list, key=lambda x: (-x["winrate"], -x["games"]))[:5]
    worst = sorted(matchup_list, key=lambda x: (x["winrate"], -x["games"]))[:5]

    return {"season_id": season_id, "total": total, "wins": wins, "losses": losses,
            "winrate": round(wins / total * 100, 1),
            "best_matchups": best, "worst_matchups": worst}


@router.post("/seasons/reset")
def manual_season_reset(db: Session = Depends(get_db)):
    """Manual fallback: close the active season and start a new one (e.g. if auto-detect missed)."""
    today = date.today()
    season = _get_active_season(db)
    if season:
        last = (
            db.query(LolRankSnapshot)
            .filter(LolRankSnapshot.season_id == season.id)
            .order_by(LolRankSnapshot.date.desc())
            .first()
        )
        last_rank = {"tier": last.tier, "rank": last.rank, "lp": last.lp} if last else None
        _close_season(db, season, today, last_rank)
        db.commit()
    new_season = LolSeason(label=_next_season_label(db), start_date=today, max_ranked_total=0)
    db.add(new_season)
    db.commit()
    db.refresh(new_season)
    return {"closed_id": season.id if season else None, "new_id": new_season.id, "new_label": new_season.label}


@router.put("/seasons/{season_id}")
def rename_season(season_id: int, body: SeasonRenameBody, db: Session = Depends(get_db)):
    season = db.query(LolSeason).filter(LolSeason.id == season_id).first()
    if not season:
        raise HTTPException(status_code=404, detail="Season not found")
    season.label = body.label
    db.commit()
    return {"id": season.id, "label": season.label}


# ── Boa altura para jogar? ───────────────────────────────────────
#
# Não é astrologia: cada factor vem do histórico do próprio utilizador
# (sono, hora, número do jogo no dia, o que fez nas 3h antes).

@router.get("/readiness")
def readiness(db: Session = Depends(get_db)):
    from datetime import timedelta
    from models import SleepEntry, AppUsageSession
    from app_categories import categorize, categorize_browser_title, is_browser

    hoje = date.today()
    agora = datetime.now()
    jogos = db.query(LolGame).filter(LolGame.date >= hoje - timedelta(days=365)).all()
    if len(jogos) < 30:
        return {"enough_data": False, "reason": "poucos jogos para estimar"}

    base = sum(1 for g in jogos if g.won) / len(jogos) * 100

    def wr(lista):
        return (sum(1 for g in lista if g.won) / len(lista) * 100) if lista else None

    factores = []

    # 1) Sono da noite passada
    sono = db.query(SleepEntry).filter(SleepEntry.date == hoje).order_by(SleepEntry.id.desc()).first()
    horas_sono = sono.hours if sono else None
    if horas_sono is not None:
        sono_por_dia = {
            str(s.date): s.hours
            for s in db.query(SleepEntry).filter(SleepEntry.date >= hoje - timedelta(days=365)).all()
        }
        bem = [g for g in jogos if (sono_por_dia.get(str(g.date)) or 0) >= 7]
        mal = [g for g in jogos if 0 < (sono_por_dia.get(str(g.date)) or 0) < 7]
        if len(bem) >= 10 and len(mal) >= 10:
            alvo = wr(bem) if horas_sono >= 7 else wr(mal)
            factores.append({
                "key": "sono",
                "label": f"{horas_sono}h de sono" + (" (descansado)" if horas_sono >= 7 else " (pouco)"),
                "wr": round(alvo, 1),
                "delta": round(alvo - base, 1),
                "samples": len(bem if horas_sono >= 7 else mal),
            })

    # 2) Hora do dia
    hora = agora.hour
    mesma_hora = [g for g in jogos if g.game_hour == hora]
    if len(mesma_hora) >= 8:
        factores.append({
            "key": "hora",
            "label": f"às {hora:02d}h",
            "wr": round(wr(mesma_hora), 1),
            "delta": round(wr(mesma_hora) - base, 1),
            "samples": len(mesma_hora),
        })

    # 3) Quantos jogos já hoje (tilt)
    hoje_jogos = [g for g in jogos if str(g.date) == str(hoje)]
    n_hoje = len(hoje_jogos)
    ordem = n_hoje + 1
    por_ordem: dict[int, list] = {}
    for g in sorted(jogos, key=lambda x: (str(x.date), x.created_at or datetime.min)):
        dia = str(g.date)
        por_ordem.setdefault(dia, []).append(g)
    nesta_posicao = [lista[ordem - 1] for lista in por_ordem.values() if len(lista) >= ordem]
    if len(nesta_posicao) >= 8:
        factores.append({
            "key": "ordem",
            "label": f"{ordem}º jogo do dia" if ordem > 1 else "primeiro jogo do dia",
            "wr": round(wr(nesta_posicao), 1),
            "delta": round(wr(nesta_posicao) - base, 1),
            "samples": len(nesta_posicao),
        })

    # 4) O que fizeste nas últimas 3h (produtivo vs distracção)
    limite = agora - timedelta(hours=3)
    sessoes = (
        db.query(AppUsageSession)
        .filter(AppUsageSession.date >= str((agora - timedelta(days=1)).date()))
        .all()
    )
    prod = dist = 0.0
    for ses in sessoes:
        try:
            inicio = datetime.fromisoformat(str(ses.start_time))
        except (TypeError, ValueError):
            continue
        if inicio < limite:
            continue
        cat = categorize(ses.bundle_id, ses.app_name)
        if is_browser(ses.bundle_id, ses.app_name):
            t = categorize_browser_title(ses.window_title, None, getattr(ses, "domain", None))
            if t:
                cat = t
        if cat in ("development", "productivity", "finance"):
            prod += ses.duration_seconds or 0
        elif cat in ("social", "entertainment", "gaming", "shopping"):
            dist += ses.duration_seconds or 0
    if prod + dist > 900:   # pelo menos 15 min de contexto
        produtivo = prod >= dist
        factores.append({
            "key": "antes",
            "label": ("3h antes produtivas" if produtivo else "3h antes de distracção")
                     + f" ({round(prod/60)}min vs {round(dist/60)}min)",
            "wr": None,
            "delta": 4.0 if produtivo else -4.0,     # ordem de grandeza do teu histórico
            "samples": None,
        })

    estimativa = base + sum(f["delta"] for f in factores)
    estimativa = max(20.0, min(80.0, estimativa))
    if estimativa >= base + 3:
        veredicto, cor = "boa altura", "verde"
    elif estimativa <= base - 3:
        veredicto, cor = "má altura", "vermelho"
    else:
        veredicto, cor = "altura normal", "amarelo"

    return {
        "enough_data": True,
        "base_wr": round(base, 1),
        "expected_wr": round(estimativa, 1),
        "verdict": veredicto,
        "color": cor,
        "games_today": n_hoje,
        "sleep_hours": horas_sono,
        "factors": factores,
        "sample_size": len(jogos),
    }


# ── Pool de campeões ──────────────────────────────────────────────
# A lista de winrates por campeão já existia, mas não dizia nada: 47% em 114 jogos
# e 60% em 12 aparecem lado a lado como se valessem o mesmo. Isto mete intervalo
# de confiança (Wilson) e compara cada campeão com o próprio winrate global, para
# separar o que é sorte do que é mesmo pior.

def _compara(v1: int, n1: int, v2: int, n2: int) -> tuple[float, Optional[int]]:
    """Teste de duas proporções + quantos jogos faltavam para a diferença ser prova.
    Serve para não vender ruído como conclusão: 4pp em 100 jogos não é nada."""
    if n1 < 2 or n2 < 2:
        return (0.0, None)
    p1, p2 = v1 / n1, v2 / n2
    p = (v1 + v2) / (n1 + n2)
    se = (p * (1 - p) * (1 / n1 + 1 / n2)) ** 0.5
    z = (p1 - p2) / se if se else 0.0
    d = abs(p1 - p2)
    # n por grupo para 80% de poder a 5%: 15.7 * p(1-p) / d²
    precisa = int(15.7 * p * (1 - p) / (d * d)) if d >= 0.005 else None
    return (z, precisa if precisa and precisa > n1 else None)


def _wilson(vitorias: int, jogos: int, z: float = 1.96) -> tuple[float, float]:
    if jogos == 0:
        return (0.0, 100.0)
    p = vitorias / jogos
    denom = 1 + z * z / jogos
    centro = (p + z * z / (2 * jogos)) / denom
    margem = z * ((p * (1 - p) / jogos + z * z / (4 * jogos * jogos)) ** 0.5) / denom
    return (round(max(0.0, centro - margem) * 100, 1), round(min(1.0, centro + margem) * 100, 1))


@router.get("/champion-pool")
def champion_pool(
    season_id: Optional[int] = Query(None),
    min_games: int = Query(5, ge=1, le=50),
    days: Optional[int] = Query(None, ge=7, le=1825),
    db: Session = Depends(get_db),
):
    q = db.query(LolGame)
    if season_id is not None:
        q = q.filter(LolGame.season_id == season_id)
    if days:
        q = q.filter(LolGame.date >= date.today() - timedelta(days=days - 1))
    jogos = q.order_by(LolGame.date.asc(), LolGame.id.asc()).all()
    total = len(jogos)
    if total < 10:
        return {"total": total, "champions": [], "overall_wr": None}

    vitorias_totais = sum(1 for g in jogos if g.won)
    wr_global = vitorias_totais / total * 100

    por_campeao: dict[str, list] = {}
    for g in jogos:
        por_campeao.setdefault(g.champion_played or "Desconhecido", []).append(g)

    linhas = []
    for nome, gs in por_campeao.items():
        n = len(gs)
        v = sum(1 for g in gs if g.won)
        wr = v / n * 100
        baixo, alto = _wilson(v, n)
        papeis: dict[str, int] = {}
        for g in gs:
            papeis[g.role or "?"] = papeis.get(g.role or "?", 0) + 1
        principal = max(papeis.items(), key=lambda kv: kv[1])[0] if papeis else "?"
        recentes = gs[-10:]
        kda_num = sum((g.kills or 0) + (g.assists or 0) for g in gs)
        mortes = sum(g.deaths or 0 for g in gs)

        # Compara com os jogos nos OUTROS campeões (duas proporções), não com um
        # número fixo: é o único teste que distingue "é pior" de "teve azar".
        z_score, precisa = _compara(v, n, vitorias_totais - v, total - n)
        if n < min_games:
            veredicto, prova = "poucos jogos", False
        elif z_score <= -1.96:
            veredicto, prova = "pior, com prova", True
        elif z_score >= 1.96:
            veredicto, prova = "melhor, com prova", True
        else:
            veredicto, prova = "sem prova ainda", False

        linhas.append({
            "champion": nome,
            "games": n,
            "wins": v,
            "winrate": round(wr, 1),
            "ci_low": baixo,
            "ci_high": alto,
            "share": round(n / total * 100, 1),
            "role": principal,
            "kda": round(kda_num / mortes, 2) if mortes else None,
            "recent_form": f"{sum(1 for g in recentes if g.won)}-{len(recentes) - sum(1 for g in recentes if g.won)}",
            "verdict": veredicto,
            "proven": prova,
            "z": round(z_score, 2),
            "games_needed": precisa,
            "vs_overall": round(wr - wr_global, 1),
        })

    linhas.sort(key=lambda c: (-c["games"], -c["winrate"]))
    com_amostra = [c for c in linhas if c["games"] >= min_games]

    # Quantos campeões fazem 80% dos jogos — pool concentrada ou espalhada.
    acumulado, nucleo = 0.0, 0
    for c in sorted(linhas, key=lambda c: -c["games"]):
        acumulado += c["share"]
        nucleo += 1
        if acumulado >= 80:
            break

    melhores = sorted(com_amostra, key=lambda c: -c["winrate"])[:3]
    piores = [c for c in com_amostra if c["verdict"] == "pior, com prova"]
    mais_jogado = max(com_amostra, key=lambda c: c["games"]) if com_amostra else None

    # Se os jogos dos campeões fracos tivessem ido para os bons, quantas vitórias dava?
    ganho = 0.0
    if melhores:
        alvo = sum(c["winrate"] for c in melhores) / len(melhores)
        for c in piores:
            ganho += c["games"] * (alvo - c["winrate"]) / 100

    return {
        "total": total,
        "overall_wr": round(wr_global, 1),
        "champions": linhas,
        "core_size": nucleo,
        "best": melhores,
        "worst": piores,
        "most_played": mais_jogado,
        "potential_wins": round(ganho, 1),
        "min_games": min_games,
    }


@router.get("/factors")
def factors(
    season_id: Optional[int] = Query(None),
    days: Optional[int] = Query(None, ge=7, le=1825),
    db: Session = Depends(get_db),
):
    """O que muda mesmo o winrate, com teste estatístico. Sem isto, olhar para a
    tabela de winrates leva a decidir com base em ruído — a maior parte das
    diferenças que se vêem não sobrevivem a um teste."""
    q = db.query(LolGame)
    if season_id is not None:
        q = q.filter(LolGame.season_id == season_id)
    if days:
        q = q.filter(LolGame.date >= date.today() - timedelta(days=days - 1))
    jogos = q.order_by(LolGame.date.asc(), LolGame.id.asc()).all()
    total = len(jogos)
    if total < 30:
        return {"total": total, "factors": []}

    vitorias = sum(1 for g in jogos if g.won)

    # ordem do jogo dentro do dia e sono da noite anterior entram como factores
    por_dia: dict[date, list] = {}
    for g in jogos:
        por_dia.setdefault(g.date, []).append(g)
    ordem: dict[int, list] = {}
    for gs in por_dia.values():
        for i, g in enumerate(gs):
            ordem.setdefault(min(i + 1, 4), []).append(g)

    noites = {n.date: n.hours for n in db.query(SleepEntry).all() if n.hours}

    def bucket_sono(g) -> Optional[str]:
        h = noites.get(g.date)
        if h is None:
            return None
        return "≥8h de sono" if h >= 8 else "7-8h de sono" if h >= 7 else "menos de 7h de sono"

    def hora(g) -> Optional[str]:
        h = g.game_hour
        if h is None:
            return None
        return "madrugada (0-6h)" if h < 6 else "manhã (6-12h)" if h < 12 else "tarde (12-19h)" if h < 19 else "noite (19-24h)"

    def duracao(g) -> Optional[str]:
        d = g.game_duration or 0
        if not d:
            return None
        return "curtos (<25min)" if d < 1500 else "médios (25-32min)" if d < 1920 else "longos (>32min)"

    dimensoes: list[tuple[str, str, dict[str, list]]] = [
        ("lado", "Lado do mapa", {}),
        ("campeao", "Campeão", {}),
        ("hora", "Hora do dia", {}),
        ("duracao", "Duração", {}),
        ("ordem", "Ordem do jogo no dia", {}),
        ("sono", "Sono da noite anterior", {}),
        ("adversario", "Jungler adversário", {}),
    ]
    mapa = dict((k, d) for k, _, d in dimensoes)
    for g in jogos:
        if g.team_side:
            mapa["lado"].setdefault("lado " + g.team_side, []).append(g)
        if g.champion_played:
            mapa["campeao"].setdefault(g.champion_played, []).append(g)
        if hora(g):
            mapa["hora"].setdefault(hora(g), []).append(g)
        if duracao(g):
            mapa["duracao"].setdefault(duracao(g), []).append(g)
        if bucket_sono(g):
            mapa["sono"].setdefault(bucket_sono(g), []).append(g)
        if g.champion_against:
            mapa["adversario"].setdefault("contra " + g.champion_against, []).append(g)
    for k, gs in ordem.items():
        mapa["ordem"].setdefault(f"{k}º jogo do dia" if k < 4 else "4º ou mais", []).extend(gs)

    saida = []
    for chave, etiqueta, grupos in dimensoes:
        for nome, gs in grupos.items():
            n = len(gs)
            if n < 12:
                continue
            v = sum(1 for g in gs if g.won)
            z, precisa = _compara(v, n, vitorias - v, total - n)
            wr = v / n * 100
            resto = (vitorias - v) / (total - n) * 100 if total > n else 0
            saida.append({
                "dimension": chave,
                "dimension_label": etiqueta,
                "value": nome,
                "games": n,
                "winrate": round(wr, 1),
                "rest_winrate": round(resto, 1),
                "diff": round(wr - resto, 1),
                "z": round(z, 2),
                "proven": abs(z) >= 1.96,
                "games_needed": precisa,
            })

    saida.sort(key=lambda f: -abs(f["z"]))
    provados = [f for f in saida if f["proven"]]
    return {
        "total": total,
        "overall_wr": round(vitorias / total * 100, 1),
        "factors": saida[:24],
        "proven": provados,
        "noise_count": len(saida) - len(provados),
    }


# ── Desempenho medido (CS, ouro, dano) ───────────────────────────
# O winrate precisa de mais de um ano de jogos para provar seja o que for.
# Estas métricas são contínuas e chegam ~30 jogos — ver `lol_performance`.

@router.get("/performance")
def desempenho(
    days: int = Query(365, ge=30, le=1000),
    db: Session = Depends(get_db),
):
    """O que muda no desempenho dele, com teste estatístico por trás.

    Só aparece o que passa o teste. Uma diferença bonita que não passa não é
    uma descoberta — é o mesmo erro que o winrate andava a cometer."""
    import lol_performance as lp

    limite = date.today() - timedelta(days=days)
    jogos = (
        db.query(LolGame)
        .filter(LolGame.date >= limite, LolGame.cs.isnot(None))
        .order_by(LolGame.date, LolGame.game_hour, LolGame.id)
        .all()
    )
    total = db.query(LolGame).filter(LolGame.date >= limite).count()
    if len(jogos) < lp.MINIMO_POR_LADO * 2:
        return {
            "games": len(jogos), "games_total": total,
            "baseline": {}, "findings": [], "tested": [],
            "message": ("Ainda não há jogos com métricas. Corre "
                        "`python scripts/preenche_metricas_lol.py --todos`."),
        }

    # ── Como se parte a amostra ──────────────────────────────────
    por_dia: dict = {}
    for g in jogos:
        por_dia.setdefault(g.date, []).append(g)

    primeiro_do_dia, quarto_ou_mais = [], []
    sem_derrotas, com_duas_derrotas = [], []
    for _, lista in por_dia.items():
        perdas = 0
        for i, g in enumerate(lista):
            (primeiro_do_dia if i == 0 else quarto_ou_mais if i >= 3 else []).append(g)
            (sem_derrotas if perdas == 0 else com_duas_derrotas if perdas >= 2 else []).append(g)
            perdas = perdas + 1 if not g.won else 0

    sono = {s.date: s.hours for s in db.query(SleepEntry).filter(
        SleepEntry.date >= limite, SleepEntry.hours.isnot(None)).all()}
    dormiu_pouco = [g for g in jogos if (sono.get(g.date) or 99) < 6]
    dormiu_bem = [g for g in jogos if (sono.get(g.date) or 0) >= 7]

    de_madrugada = [g for g in jogos if g.game_hour is not None and g.game_hour < 6]
    de_dia = [g for g in jogos if g.game_hour is not None and 10 <= g.game_hour < 20]

    splits = [
        (sem_derrotas, com_duas_derrotas, "sem derrotas atrás", "depois de 2 derrotas"),
        (primeiro_do_dia, quarto_ou_mais, "1º jogo do dia", "4º jogo ou mais"),
        (dormiu_bem, dormiu_pouco, "dormiu 7h+", "dormiu menos de 6h"),
        (de_dia, de_madrugada, "de dia", "de madrugada"),
    ]

    # Cada campeão contra todos os outros: é a pergunta que ele faz sempre.
    contagem: dict = {}
    for g in jogos:
        contagem[g.champion_played] = contagem.get(g.champion_played, 0) + 1
    for campeao, n in sorted(contagem.items(), key=lambda kv: -kv[1])[:5]:
        if n >= lp.MINIMO_POR_LADO:
            splits.append((
                [g for g in jogos if g.champion_played == campeao],
                [g for g in jogos if g.champion_played != campeao],
                f"de {campeao}", "dos outros campeões",
            ))

    achados, testados = [], []
    for a, b, na, nb in splits:
        testados.append({"a": na, "b": nb, "n_a": len(a), "n_b": len(b)})
        achados.extend(lp.compara(a, b, na, nb))

    return {
        "games": len(jogos),
        "games_total": total,
        "baseline": lp.resumo(jogos),
        "findings": sorted(achados, key=lambda x: x["p"]),
        "tested": testados,
        "message": "",
    }


# ── O duelo com o jungler adversário ─────────────────────────────
# A app só o comparava com ele próprio. A Riot não publica referências por elo,
# mas cada partida traz um jungler do mesmo elo, do mesmo patch e do mesmo jogo.

def _encolhe(wr_dele: float, wr_meta: float, jogos: int, k: int = 30) -> float:
    """Quanto ele é melhor (ou pior) do que a média do elo dele com um campeão.

    Encolhido para zero conforme a amostra (empirical Bayes): 60% em 50 jogos é
    prova de alguma coisa, 100% em 2 não é nada. Sem isto, um campeão jogado
    duas vezes com sorte aparece no topo da lista."""
    return round((wr_dele - wr_meta) * jogos / (jogos + k), 1)


async def _edge_por_campeao(db: Session, days: int) -> list[dict]:
    """Winrate dele menos o winrate global no mesmo elo, campeão a campeão.

    É uma pergunta muito melhor do que "onde tenho mais winrate": separa "este
    campeão é forte no patch" de "eu sou bom com este campeão". A Diana está
    14pp acima da média Master e o meta chama-lhe tier 12 — as duas coisas são
    verdade ao mesmo tempo."""
    from meta_stats import normalize_name

    meta = await _meta_pronto()

    limite = date.today() - timedelta(days=days)
    linhas = []
    for campeao, n, v in (
        db.query(LolGame.champion_played, func.count(LolGame.id),
                 func.sum(case((LolGame.won, 1), else_=0)))
        .filter(LolGame.role == "jungle", LolGame.date >= limite,
                LolGame.champion_played.isnot(None))
        .group_by(LolGame.champion_played).having(func.count(LolGame.id) >= 5).all()
    ):
        m = meta.get(normalize_name(campeao))
        if not m:
            continue
        wr = 100 * (v or 0) / n
        linhas.append({
            "champion": campeao,
            "games": n,
            "winrate": round(wr, 1),
            "meta_wr": m["wr"],
            "edge": round(wr - m["wr"], 1),
            "edge_shrunk": _encolhe(wr, m["wr"], n),
            "meta_tier": m.get("tier"),
        })
    linhas.sort(key=lambda c: -c["edge_shrunk"])
    return linhas


@router.get("/duel")
async def duelo(
    days: int = Query(365, ge=30, le=1000),
    db: Session = Depends(get_db),
):
    """Ele contra o jungler adversário, medida a medida.

    A divisão entre "antes de se decidir" e "acumulado" não é cosmética: fazer
    mais dragões não é conselho, é a descrição de ter ganho. O que acontece nos
    primeiros quinze minutos é que é accionável."""
    import lol_duel as ld

    limite = date.today() - timedelta(days=days)
    duelos = (
        db.query(LolDuel)
        .filter(LolDuel.date >= limite)
        .order_by(LolDuel.date.desc())
        .all()
    )
    jogos = (
        db.query(LolGame)
        .filter(LolGame.role == "jungle", LolGame.date >= limite)
        .all()
    )
    jogos_jungle = len(jogos)
    # O lado do mapa vive em `lol_games`; anexa-se aos duelos para a análise do
    # lado o poder usar sem uma segunda consulta.
    lado_por_jogo = {g.match_id: g.team_side for g in jogos if g.match_id}
    for d in duelos:
        d._lado = lado_por_jogo.get(d.match_id)
    if len(duelos) < ld.MINIMO:
        return {
            "games": len(duelos), "games_total": jogos_jungle,
            "metrics": [], "by_champion": [], "edge": [], "critical_window": None,
            "message": ("Ainda não há duelos guardados. Corre "
                        "`python scripts/preenche_duelos_lol.py --todos`."),
        }

    metricas = ld.compara(duelos)
    return {
        "games": len(duelos),
        "games_total": jogos_jungle,
        "with_timeline": sum(1 for d in duelos if d.has_timeline),
        "winrate": round(100 * sum(1 for d in duelos if d.won) / len(duelos), 1),
        "metrics": metricas,
        "proven_count": sum(1 for m in metricas if m["proven"]),
        "by_champion": ld.por_campeao(duelos),
        "critical_window": ld.janela_critica(duelos),
        "map_side": ld.lado_do_mapa(duelos, jogos),
        "edge": await _edge_por_campeao(db, days),
        "message": "",
    }


# ── Recomendação de campeões ─────────────────────────────────────
# A antiga só sabia olhar para os campeões que ele já tinha jogado — ver
# `lol_picks` para o porquê de cada parcela.

async def _maestria_por_campeao(api_key: str) -> dict[str, int]:
    """Pontos de maestria por campeão, da Riot. Já existia o endpoint e nunca
    tinha servido para decidir nada — é ela que distingue "nunca jogaste isso"
    de "jogaste 800 vezes, só não de jungle"."""
    guardado = _cache_get("mastery_all", ttl=3600)
    if guardado is not None:
        return guardado
    try:
        linhas = await get_mastery_data(
            _riot_config["game_name"], _riot_config["tag_line"], api_key, top=200
        )
    except RiotAPIError as e:
        logger.warning(f"picks: maestria indisponível ({e.message})")
        return {}
    mapa = {m["champion_name"]: m["champion_points"] for m in linhas}
    _cache_set("mastery_all", mapa)
    return mapa


def _pool_dele(db: Session, role: str, days: int = 730) -> dict[str, dict]:
    limite = date.today() - timedelta(days=days)
    out = {}
    for campeao, n, v in (
        db.query(LolGame.champion_played, func.count(LolGame.id),
                 func.sum(case((LolGame.won, 1), else_=0)))
        .filter(LolGame.role == role, LolGame.date >= limite,
                LolGame.champion_played.isnot(None))
        .group_by(LolGame.champion_played).all()
    ):
        out[campeao] = {"games": n, "winrate": round(100 * (v or 0) / n, 1)}
    return out


def _info_campeao(nome: str) -> tuple[list[str], str]:
    """(tags, tipo de dano) do Data Dragon, pelo nome da chave."""
    from champion_data import _key_to_id_map, get_champion_class, get_damage_type
    cid = _key_to_id_map.get(nome)
    if not cid:
        return [], "Unknown"
    return get_champion_class(cid), get_damage_type(cid)


def _o_que_falta(ally_ids: list[int]) -> dict:
    """O que a equipa ainda não tem. Só conta quando já há picks que cheguem —
    dizer "falta tank" com um aliado escolhido não é informação."""
    comp = analyze_team_comp([c for c in ally_ids if c])
    if len([c for c in ally_ids if c]) < 2:
        return {}
    return {
        "ap": comp["damage_balance"] == "heavy_ad",
        "ad": comp["damage_balance"] == "heavy_ap",
        "engage": not comp["has_engage"],
        "tank": not comp["has_tank"],
    }


async def _recomenda(db: Session, inimigos: list[str], ally_ids: list[int],
                     role: str = "jungle", indisponiveis: list[str] | None = None,
                     aliados: list[str] | None = None) -> dict:
    import lol_picks as lp

    await ensure_champion_data()
    meta = await _meta_pronto()
    if not meta:
        return {"pool": [], "meta": [], "message": "Sem dados do meta neste momento."}

    api_key = _riot_config.get("api_key", "")
    maestria = await _maestria_por_campeao(api_key) if api_key else {}
    return await lp.recomenda(
        inimigos=[e for e in inimigos if e],
        meta=meta,
        pool=_pool_dele(db, role),
        maestria=maestria,
        precisa=_o_que_falta(ally_ids),
        info_campeao=_info_campeao,
        role=role,
        indisponiveis=indisponiveis,
        aliados=aliados,
    )


@router.get("/picks")
async def picks(
    enemies: str = Query("", description="junglers adversários, separados por vírgula"),
    allies: str = Query("", description="aliados já escolhidos, para a synergy"),
    taken: str = Query("", description="campeões já escolhidos ou banidos"),
    role: str = Query("jungle"),
    db: Session = Depends(get_db),
):
    """As duas listas: o pool dele, e o que o meta diz para este draft.

    Separadas de propósito. Dentro do pool a maestria já não separa ninguém (são
    todos campeões que ele domina), por isso quem decide é o matchup. Fora do
    pool a conta é outra: só vale a pena se o ganho do matchup pagar o que custa
    pegar num campeão que não se domina."""
    lista = [e.strip() for e in enemies.split(",") if e.strip()]
    fora = [c.strip() for c in taken.split(",") if c.strip()]
    meus = [a.strip() for a in allies.split(",") if a.strip()]
    return await _recomenda(db, lista, [], role, indisponiveis=fora, aliados=meus)


@router.get("/worth-learning")
async def vale_aprender(
    days: int = Query(180, ge=30, le=730),
    role: str = Query("jungle"),
    db: Session = Depends(get_db),
):
    """Que campeão render-lhe-ia mais nos próximos cem jogos.

    Não é a pergunta do champ select. Aqui o inimigo ainda não se sabe, por isso
    a conta é contra a distribuição real dos junglers que ele encontra — vale
    mais um campeão que se dá bem com o Hecarim, que ele apanha vinte vezes em
    seis meses, do que um que arrasa alguém que nunca aparece."""
    import lol_picks as lp

    await ensure_champion_data()
    meta = await _meta_pronto()
    limite = date.today() - timedelta(days=days)
    frequencia = {
        campeao: n
        for campeao, n in db.query(LolGame.champion_against, func.count(LolGame.id))
        .filter(LolGame.role == role, LolGame.date >= limite,
                LolGame.champion_against.isnot(None))
        .group_by(LolGame.champion_against).all()
    }
    if not frequencia:
        return {"champions": [], "encounters": 0,
                "message": "Ainda não há jogos de jungle neste período."}
    if not meta:
        return {"champions": [], "encounters": sum(frequencia.values()),
                "message": "Sem dados do meta neste momento — tenta daqui a pouco."}

    api_key = _riot_config.get("api_key", "")
    maestria = await _maestria_por_campeao(api_key) if api_key else {}
    linhas = await lp.vale_a_pena_aprender(
        frequencia=frequencia, meta=meta, pool=_pool_dele(db, role),
        maestria=maestria, role=role,
    )
    top = sorted(frequencia.items(), key=lambda kv: -kv[1])[:8]
    return {
        "champions": linhas,
        "encounters": sum(frequencia.values()),
        "distinct_enemies": len(frequencia),
        "days": days,
        "top_enemies": [{"champion": c, "games": n} for c, n in top],
        "message": "",
    }


@router.get("/bans")
async def bans(
    days: int = Query(180, ge=30, le=730),
    role: str = Query("jungle"),
    db: Session = Depends(get_db),
):
    """Que jungler adversário mais lhe estraga as opções.

    Não é "contra quem perco" — isso não tem resposta com 500 jogos. É quanto
    cada inimigo baixa o melhor pick que lhe resta, vezes a frequência com que
    aparece de facto. A fase de bans é antes dos picks, por isso a lista não
    depende do draft."""
    import lol_picks as lp

    await ensure_champion_data()
    meta = await _meta_pronto()
    limite = date.today() - timedelta(days=days)
    frequencia = {
        c: n for c, n in db.query(LolGame.champion_against, func.count(LolGame.id))
        .filter(LolGame.role == role, LolGame.date >= limite,
                LolGame.champion_against.isnot(None))
        .group_by(LolGame.champion_against).all()
    }
    if not meta or not frequencia:
        return {"bans": [], "message": "Sem dados suficientes."}
    linhas = await lp.quem_banir(frequencia, meta, _pool_dele(db, role), role=role)
    return {
        "bans": linhas,
        "days": days,
        "encounters": sum(frequencia.values()),
        "message": "",
    }


# ── Treinador ao vivo ────────────────────────────────────────────
# O que a app mediu nele só vale se aparecer enquanto o jogo ainda está a
# acontecer. Ver `lol_coach` para a regra: só entra o que passou um teste.

def _medidas_para_o_coach(db: Session) -> dict:
    """O que o duelo mediu nele, filtrado ao que tem prova.

    Fica em cache curta: isto é chamado de poucos em poucos segundos enquanto ele
    joga, e as medidas mudam uma vez por partida."""
    guardado = _cache_get("coach_medidas", ttl=600)
    if guardado is not None:
        return guardado

    import lol_duel as ld

    limite = date.today() - timedelta(days=365)
    jogos = (
        db.query(LolGame)
        .filter(LolGame.role == "jungle", LolGame.date >= limite,
                LolGame.team_side.isnot(None))
        .all()
    )
    duelos = db.query(LolDuel).filter(LolDuel.date >= limite).all()
    if len(duelos) < ld.MINIMO:
        return {}
    por_jogo = {g.match_id: g.team_side for g in jogos if g.match_id}
    for d in duelos:
        d._lado = por_jogo.get(d.match_id)

    medidas = {m["metric"]: m for m in ld.compara(duelos) if m["proven"]}
    medidas["map_side"] = ld.lado_do_mapa(duelos, jogos)
    _cache_set("coach_medidas", medidas)
    return medidas


@router.get("/live-client/coach")
async def treinador_ao_vivo(db: Session = Depends(get_db)):
    """O que dizer-lhe **agora**, com o jogo a decorrer.

    Lê o cliente local (não a API da Riot, que só sabe do jogo depois de ele
    acabar) e cruza com o que o duelo mediu. Fora de jogo devolve
    `in_game: false` e mais nada — a página trata disso."""
    import lol_coach
    from live_winprob import get_live_client_data

    dados = await get_live_client_data()
    if not dados:
        return {"in_game": False, "alerts": []}
    return lol_coach.avisos(dados, _medidas_para_o_coach(db))
