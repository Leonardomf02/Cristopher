"""
Live in-game win probability via Riot's Live Client Data API.

Unlike the pre-game predictor (which is near its ceiling at a fixed Master elo —
within-account games are matchmade to ~50/50), an in-game model reads the actual
game state and reaches ~73% accuracy by 15 min in the literature.

Data source: the local Live Client Data API at 127.0.0.1:2999 (no auth, self-signed
cert), available only while the player is in their own game — same locality as the
LCU champ-select integration.

The Live Client API does NOT expose other players' gold, so team gold is *estimated*
from the reliably-exposed fields (CS, kills) plus objective gold from the event log.
Coefficients are grounded in published data, not fit to the user's games:

  • Gold→win (EGR model, ~800 pro games): +750g@15→60%, +1500→70%, +2712→84%,
    i.e. logit ≈ 0.00059·gold. Solo-queue converts leads worse than pro, so the
    slope is discounted ~20% (K_GOLD below).
  • Objective win-rates (solo queue): first tower 70%, first dragon 69%, herald 72%,
    first baron 80%, soul/baron stack 87%. These already embed the correlated gold
    lead, so here they enter only as *marginal* buff/control terms on top of gold
    (to avoid double-counting), kept deliberately conservative.

Sources documented in the analysis; see docstring history.
"""

import math
import logging
import warnings

import httpx

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

LIVE_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"

# Gold proxies (team gold the API doesn't expose directly).
GOLD_PER_CS = 21.0       # blended minion/jungle value
GOLD_PER_KILL = 300.0    # net team gold per kill incl. avg bounty
GOLD_PER_TOWER = 350.0   # local + shared, blended across game

# Gold→logit slope. EGR (pro) ≈ 0.00059; discounted for solo-queue comebacks.
K_GOLD = 0.00045

# Marginal objective terms (logit) — buff/control value *beyond* the gold they bring.
DRAGON_EACH = 0.10       # per net elemental dragon (map control)
SOUL = 0.55              # holding dragon soul (4 elementals) — game-defining buff
ELDER = 0.60             # active Elder dragon buff
BARON = 0.45             # active Baron buff (recent kill)
INHIB_EACH = 0.35        # per net inhibitor (sieging / near-win pressure)
BARON_BUFF_SECONDS = 180
ELDER_BUFF_SECONDS = 150


async def get_live_client_data() -> dict | None:
    """Fetch the full live game state from the local client, or None if not in game."""
    async with httpx.AsyncClient(verify=False, timeout=4.0) as client:
        try:
            resp = await client.get(LIVE_URL)
            if resp.status_code == 200:
                return resp.json()
            return None
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
            return None  # client not running / not in a game
        except Exception as e:  # noqa: BLE001 — best-effort, never break the caller
            logger.warning(f"live client data: {e}")
            return None


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, x))))


def _player_name(p: dict) -> str:
    return p.get("riotId") or p.get("summonerName") or ""


def _short(name: str) -> str:
    """Game-name portion of a riot id ('Name#TAG' -> 'name')."""
    return (name or "").split("#")[0].strip().lower()


def compute_live_win_probability(data: dict | None) -> dict | None:
    """Estimate the active player's team win probability from live game state.

    Returns None when there's no usable game data. The point estimate is gold-driven
    (CS + kills + towers) with conservative objective adjustments; confidence widens
    early when little has happened.
    """
    if not data:
        return None
    all_players = data.get("allPlayers") or []
    if len(all_players) < 2:
        return None

    game = data.get("gameData") or {}
    game_time = float(game.get("gameTime", 0) or 0)
    game_min = game_time / 60.0

    # Identify the active player's team.
    active = data.get("activePlayer") or {}
    my_name = active.get("riotId") or active.get("summonerName") or active.get("riotIdGameName") or ""
    name_to_team: dict[str, str] = {}
    for p in all_players:
        nm = _short(_player_name(p))
        if nm:
            name_to_team[nm] = p.get("team", "")

    my_team = name_to_team.get(_short(my_name))
    if not my_team:
        my_team = "ORDER"  # sensible fallback
    teams = [t for t in {p.get("team", "") for p in all_players} if t]
    enemy_team = next((t for t in teams if t != my_team), None)
    if enemy_team is None:
        return None

    def _agg(team: str) -> tuple[int, int, int]:
        ps = [p for p in all_players if p.get("team") == team]
        kills = sum(int(p.get("scores", {}).get("kills", 0)) for p in ps)
        deaths = sum(int(p.get("scores", {}).get("deaths", 0)) for p in ps)
        cs = sum(int(p.get("scores", {}).get("creepScore", 0)) for p in ps)
        return kills, deaths, cs

    mk, md, mcs = _agg(my_team)
    ek, ed, ecs = _agg(enemy_team)
    kill_diff = mk - ek
    cs_diff = mcs - ecs

    # ── Objectives from the event log (best-effort) ──────────────────
    events = (data.get("events") or {}).get("Events") or []
    my_towers = en_towers = 0
    my_inhibs = en_inhibs = 0
    my_dragons = en_dragons = 0
    my_elder = en_elder = 0.0
    my_baron_t = en_baron_t = -1e9

    # "T1" structures belong to ORDER (blue); "T2" to CHAOS (red). The team that
    # *destroyed* a structure is the opposite of its owner.
    def _owner_of_struct(struct_id: str) -> str | None:
        if "T1" in struct_id:
            return "ORDER"
        if "T2" in struct_id:
            return "CHAOS"
        return None

    for ev in events:
        try:
            name = ev.get("EventName", "")
            t = float(ev.get("EventTime", 0) or 0)
            if name == "TurretKilled":
                owner = _owner_of_struct(ev.get("TurretKilled", ""))
                if owner == my_team:
                    en_towers += 1          # my turret fell → enemy scored
                elif owner == enemy_team:
                    my_towers += 1
            elif name == "InhibKilled":
                owner = _owner_of_struct(ev.get("InhibKilled", ""))
                if owner == my_team:
                    en_inhibs += 1
                elif owner == enemy_team:
                    my_inhibs += 1
            elif name == "DragonKill":
                killer_team = name_to_team.get(_short(ev.get("KillerName", "")))
                is_elder = ev.get("DragonType", "") == "Elder"
                if killer_team == my_team:
                    if is_elder:
                        my_elder = t
                    else:
                        my_dragons += 1
                elif killer_team == enemy_team:
                    if is_elder:
                        en_elder = t
                    else:
                        en_dragons += 1
            elif name == "BaronKill":
                killer_team = name_to_team.get(_short(ev.get("KillerName", "")))
                if killer_team == my_team:
                    my_baron_t = t
                elif killer_team == enemy_team:
                    en_baron_t = t
        except Exception:  # noqa: BLE001 — tolerate any unexpected event shape
            continue

    tower_diff = my_towers - en_towers
    dragon_diff = my_dragons - en_dragons
    inhib_diff = my_inhibs - en_inhibs

    # ── Gold estimate + logit ────────────────────────────────────────
    gold_diff = GOLD_PER_CS * cs_diff + GOLD_PER_KILL * kill_diff + GOLD_PER_TOWER * tower_diff
    logit = K_GOLD * gold_diff

    components = [
        {"name": "Ouro estimado", "detail": f"{round(gold_diff):+} g", "value": round(K_GOLD * gold_diff, 3)},
        {"name": "Abates", "detail": f"{kill_diff:+}", "value": None},
        {"name": "CS", "detail": f"{cs_diff:+}", "value": None},
        {"name": "Torres", "detail": f"{tower_diff:+}", "value": None},
    ]

    # Marginal objective buffs (beyond the gold they already bring).
    obj_logit = DRAGON_EACH * dragon_diff
    if my_dragons >= 4:
        obj_logit += SOUL
    if en_dragons >= 4:
        obj_logit -= SOUL
    if game_time - my_elder <= ELDER_BUFF_SECONDS:
        obj_logit += ELDER
    if game_time - en_elder <= ELDER_BUFF_SECONDS:
        obj_logit -= ELDER
    baron_state = None
    if game_time - my_baron_t <= BARON_BUFF_SECONDS:
        obj_logit += BARON
        baron_state = "mine"
    if game_time - en_baron_t <= BARON_BUFF_SECONDS:
        obj_logit -= BARON
        baron_state = "enemy" if baron_state is None else "both"
    obj_logit += INHIB_EACH * inhib_diff

    logit += obj_logit
    if dragon_diff or my_dragons >= 4 or en_dragons >= 4:
        components.append({"name": "Dragões", "detail": f"{my_dragons}–{en_dragons}", "value": round(DRAGON_EACH * dragon_diff + (SOUL if my_dragons >= 4 else 0) - (SOUL if en_dragons >= 4 else 0), 3)})
    if baron_state:
        components.append({"name": "Barão", "detail": baron_state, "value": round(BARON if baron_state == "mine" else -BARON, 3)})
    if inhib_diff:
        components.append({"name": "Inibidores", "detail": f"{inhib_diff:+}", "value": round(INHIB_EACH * inhib_diff, 3)})

    probability = round(_sigmoid(logit) * 100)
    probability = max(1, min(99, probability))

    dist = abs(probability - 50)
    if game_min < 4:
        confidence = "low"  # too early — little has happened
    elif dist >= 18 and game_min >= 10:
        confidence = "high"
    elif dist >= 8:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "in_game": True,
        "game_time": int(game_time),
        "game_minute": round(game_min, 1),
        "my_team": my_team,
        "probability": probability,
        "confidence": confidence,
        "gold_diff_est": round(gold_diff),
        "kill_diff": kill_diff,
        "cs_diff": cs_diff,
        "tower_diff": tower_diff,
        "dragon_diff": dragon_diff,
        "score": {"my": f"{mk}/{md}", "enemy": f"{ek}/{ed}"},
        "components": components,
    }


async def get_live_win_probability() -> dict:
    """Fetch live state and compute win probability. Always returns a dict."""
    data = await get_live_client_data()
    if not data:
        return {"in_game": False}
    result = compute_live_win_probability(data)
    return result or {"in_game": False}
