from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel
import time
import logging

logger = logging.getLogger(__name__)

from database import get_db, SessionLocal
from models import LolGame, LolRankSnapshot, LolPrediction, LolSeason
from schemas import LolGameCreate, LolGameUpdate, LolGameOut
from riot_api import (
    fetch_recent_games, RiotAPIError, get_puuid,
    get_rank_info, get_live_game, get_live_game_detailed, get_mastery_data,
    get_match_timeline, parse_timeline,
    get_summoner_level, get_master_position, get_replay_links,
    build_matchup_stats, get_leagueofgraphs_ranking,
)
from lcu_api import get_champ_select_session, get_gameflow_phase, is_client_running
from champion_data import (
    ensure_champion_data, champion_name, analyze_team_comp,
    suggest_picks, get_damage_type, get_champion_class,
    set_matchup_data, get_matchup_data, _id_to_key,
)
from meta_stats import fetch_meta_stats, get_meta_stats, _to_ddragon_key
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

    resolved = 0
    for pred in unresolved:
        # Strategy 1: Match by game_start_time hour (±1 hour for edge cases)
        if pred.game_start_time:
            game_dt = datetime.fromtimestamp(pred.game_start_time / 1000)
            game_hour = game_dt.hour
            possible_hours = [game_hour, (game_hour + 1) % 24]
            game = (
                db.query(LolGame)
                .filter(
                    LolGame.date == pred.date,
                    LolGame.champion_played == pred.champion_played,
                    LolGame.game_hour.in_(possible_hours),
                )
                .order_by(LolGame.match_id.desc())
                .first()
            )
            if game:
                pred.match_id = game.match_id
                pred.actual_win = game.won
                pred.correct = pred.predicted_win == game.won
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
        if game:
            pred.match_id = game.match_id
            pred.actual_win = game.won
            pred.correct = pred.predicted_win == game.won
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
        if len(games) == 1:
            pred.match_id = games[0].match_id
            pred.actual_win = games[0].won
            pred.correct = pred.predicted_win == games[0].won
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

# Store config in memory (persists across requests while server runs)
_riot_config: dict = {
    "game_name": "Cristóvão",
    "tag_line": "2002",
    "api_key": "RGAPI-3f91f4bc-01d9-4296-9516-34bac1e29718",
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
            season_id=active_season_id,
            notes="",
        )
        db.add(game)
        imported += 1

    if imported > 0:
        db.commit()
        _response_cache.pop("rank", None)
        _response_cache.pop("position", None)
        _response_cache.pop("matchup_stats", None)
        set_matchup_data(None)  # force rebuild from DB on next access

    # Always try to resolve predictions (even if 0 new games imported)
    resolved = _resolve_predictions(db)

    return {
        "ok": True,
        "imported": imported,
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
            existing.tier = rank.get("tier")
            existing.rank = rank.get("rank")
            existing.lp = rank.get("lp")
            existing.wins = rank.get("wins")
            existing.losses = rank.get("losses")
            existing.season_id = season_id
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
    """Get the player's real ranking from League of Graphs."""
    cached = _cache_get("position", ttl=1800)
    if cached is not None:
        return cached
    try:
        result = await get_leagueofgraphs_ranking(
            _riot_config["game_name"],
            _riot_config["tag_line"],
        )
        if result is None:
            result = {"position": None, "message": "Não foi possível obter ranking do League of Graphs"}
        else:
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
def get_peak_stats(db: Session = Depends(get_db)):
    """Get peak LP and best EU ranking from historical snapshots."""
    snapshots = db.query(LolRankSnapshot).all()
    if not snapshots:
        return {"has_data": False}

    # Compute effective LP for tier comparison (Master 0LP = 0, GM 0LP = higher, etc.)
    tier_base = {"IRON": 0, "BRONZE": 400, "SILVER": 800, "GOLD": 1200,
                 "PLATINUM": 1600, "EMERALD": 2000, "DIAMOND": 2400,
                 "MASTER": 2800, "GRANDMASTER": 3200, "CHALLENGER": 3600}

    peak_lp_snap = None
    peak_effective = -1
    best_euw_snap = None
    best_euw_val = 999999

    for s in snapshots:
        if s.lp is not None and s.tier:
            effective = tier_base.get(s.tier, 0) + (s.lp or 0)
            if effective > peak_effective:
                peak_effective = effective
                peak_lp_snap = s
        if s.euw_rank and s.euw_rank < best_euw_val:
            best_euw_val = s.euw_rank
            best_euw_snap = s

    result: dict = {"has_data": True}
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


def _get_enemy_counters(enemy_names: list[str]) -> dict:
    """For each visible enemy, return user's picks vs that champion sorted by games."""
    data = get_matchup_data()
    if not data:
        return {}
    matchups = data.get("matchups", {})
    counters: dict[str, list] = {}
    for enemy in enemy_names:
        picks_vs: list[dict] = []
        for my_champ, vs_map in matchups.items():
            if enemy in vs_map:
                s = vs_map[enemy]
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
    counters = _get_enemy_counters([champion_name])
    return {"champion": champion_name, "counters": counters.get(champion_name, [])}


@router.get("/champ-select/status")
async def champ_select_status():
    """Check if League Client is running and if we're in champ select."""
    client_ok = await is_client_running()
    if not client_ok:
        return {"client_running": False, "phase": None, "in_champ_select": False}

    phase = await get_gameflow_phase()
    return {
        "client_running": True,
        "phase": phase,
        "in_champ_select": phase == "ChampSelect",
    }


@router.get("/champ-select/session")
async def champ_select_data():
    """Get full champ select analysis: picks, bans, team comp, suggestions."""
    await ensure_champion_data()

    session = await get_champ_select_session()
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

    # Suggest jungle picks based on personal data + global meta
    suggestions = suggest_picks(
        enemy_ids=their_ids,
        ally_ids=[cid for cid in my_ids],
        meta_stats=cached_meta,
    )

    # Enemy counters: for each visible enemy champ, user's picks vs them
    enemy_key_names = [_id_to_key.get(cid, "") for cid in their_ids if cid != 0]
    enemy_counters = _get_enemy_counters([n for n in enemy_key_names if n])

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
        "suggestions": suggestions[:8],
        "enemy_counters": enemy_counters,
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
