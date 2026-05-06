"""
Riot Games API integration for automatic LoL match history import.
Uses the official Riot API: https://developer.riotgames.com/

Requires a Riot API key (get one at https://developer.riotgames.com/).
"""

import httpx
from datetime import datetime, date
from typing import Optional
import logging
import asyncio
import re

logger = logging.getLogger(__name__)

# Riot API endpoints
ACCOUNT_V1 = "https://europe.api.riotgames.com/riot/account/v1"
MATCH_V5 = "https://europe.api.riotgames.com/lol/match/v5"
SUMMONER_V4 = "https://{platform}.api.riotgames.com/lol/summoner/v4"
LEAGUE_V4 = "https://euw1.api.riotgames.com/lol/league/v4"
LEAGUE_EXP_V4 = "https://euw1.api.riotgames.com/lol/league-exp/v4"
SPECTATOR_V5 = "https://euw1.api.riotgames.com/lol/spectator/v5"
CHAMPION_MASTERY_V4 = "https://euw1.api.riotgames.com/lol/champion-mastery/v4"
SUMMONER_V4_EUW = "https://euw1.api.riotgames.com/lol/summoner/v4"

# Map of lane/role to our simplified roles
ROLE_MAP = {
    "TOP": "top",
    "JUNGLE": "jungle",
    "MIDDLE": "mid",
    "BOTTOM": "adc",
    "UTILITY": "support",
}


class RiotAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Riot API error {status_code}: {message}")


async def _get(url: str, api_key: str, params: dict | None = None) -> dict | list:
    """Make an authenticated request to the Riot API with retry on rate limit."""
    headers = {"X-Riot-Token": api_key}
    async with httpx.AsyncClient(timeout=15.0) as client:
        for attempt in range(3):
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code == 429:
                retry_after = min(int(resp.headers.get("Retry-After", 2)), 10)
                logger.warning(f"Rate limited, retrying in {retry_after}s (attempt {attempt + 1})")
                await asyncio.sleep(retry_after)
                continue
            break
        if resp.status_code == 401:
            raise RiotAPIError(401, "API key inválida ou expirada. Vai a developer.riotgames.com para renovar.")
        if resp.status_code == 403:
            raise RiotAPIError(403, "API key sem permissão para este endpoint.")
        if resp.status_code == 404:
            raise RiotAPIError(404, "Conta não encontrada. Verifica o Riot ID.")
        if resp.status_code == 429:
            raise RiotAPIError(429, "Rate limit atingido. Espera um pouco e tenta novamente.")
        if resp.status_code != 200:
            raise RiotAPIError(resp.status_code, f"Erro inesperado: {resp.text[:200]}")
        return resp.json()


# ── PUUID cache ──────────────────────────────────────────────────
_puuid_cache: dict[str, str] = {}

async def get_puuid(game_name: str, tag_line: str, api_key: str) -> str:
    """Get the PUUID for a Riot account given gameName#tagLine (cached)."""
    cache_key = f"{game_name}#{tag_line}"
    if cache_key in _puuid_cache:
        return _puuid_cache[cache_key]
    url = f"{ACCOUNT_V1}/accounts/by-riot-id/{game_name}/{tag_line}"
    data = await _get(url, api_key)
    _puuid_cache[cache_key] = data["puuid"]
    return data["puuid"]


async def get_match_ids(
    puuid: str,
    api_key: str,
    count: int = 20,
    start: int = 0,
    queue: int | None = 420,  # 420 = ranked solo, None = all
    start_time: int | None = None,
) -> list[str]:
    """Get recent match IDs for a player."""
    url = f"{MATCH_V5}/matches/by-puuid/{puuid}/ids"
    params: dict = {"count": min(count, 100), "start": start}
    if queue is not None:
        params["queue"] = queue
    if start_time is not None:
        params["startTime"] = start_time
    return await _get(url, api_key, params)


async def get_match_detail(match_id: str, api_key: str) -> dict:
    """Get full match details."""
    url = f"{MATCH_V5}/matches/{match_id}"
    return await _get(url, api_key)


def parse_match(match_data: dict, puuid: str) -> dict | None:
    """
    Parse a Riot match response into our LolGame format.
    Returns None if the match is not a Summoner's Rift game.
    """
    info = match_data.get("info", {})

    # Only process Summoner's Rift games (mapId 11)
    if info.get("mapId") != 11:
        return None

    # Skip remakes (early surrenders under 5 minutes)
    if info.get("gameDuration", 0) < 300:
        is_remake = any(
            p.get("gameEndedInEarlySurrender", False)
            for p in info.get("participants", [])
        )
        if is_remake:
            return None

    # Find the player's participant data
    participant = None
    for p in info.get("participants", []):
        if p.get("puuid") == puuid:
            participant = p
            break

    if participant is None:
        return None

    # Find the lane opponent (same lane, different team)
    team_id = participant.get("teamId")
    lane = participant.get("teamPosition", "")
    opponent_champ = None
    for p in info.get("participants", []):
        if p.get("teamId") != team_id and p.get("teamPosition") == lane:
            opponent_champ = p.get("championName")
            break

    # Parse game timestamp (convert to local timezone for correct date)
    game_start = info.get("gameStartTimestamp", 0)
    game_date = datetime.fromtimestamp(game_start / 1000).date() if game_start else date.today()
    game_hour = datetime.fromtimestamp(game_start / 1000).hour if game_start else None

    # Team side: 100 = blue, 200 = red
    team_id_val = participant.get("teamId")
    team_side = "blue" if team_id_val == 100 else "red" if team_id_val == 200 else None

    return {
        "match_id": match_data.get("metadata", {}).get("matchId"),
        "date": game_date,
        "won": participant.get("win", False),
        "champion_played": participant.get("championName"),
        "champion_against": opponent_champ,
        "role": ROLE_MAP.get(lane, None),
        "kills": participant.get("kills", 0),
        "deaths": participant.get("deaths", 0),
        "assists": participant.get("assists", 0),
        "game_duration": info.get("gameDuration", 0),
        "game_hour": game_hour,
        "team_side": team_side,
        "notes": "",
    }


async def fetch_recent_games(
    game_name: str,
    tag_line: str,
    api_key: str,
    count: int = 20,
    queue: int | None = None,
    start_time: int | None = None,
    existing_match_ids: set[str] | None = None,
) -> list[dict]:
    """
    Fetch recent games for a player and return parsed game data.
    Skips matches that are already in existing_match_ids.
    """
    if existing_match_ids is None:
        existing_match_ids = set()

    # Step 1: Get PUUID
    puuid = await get_puuid(game_name, tag_line, api_key)

    # Step 2: Get match IDs (paginate if count > 100)
    match_ids: list[str] = []
    fetched = 0
    while fetched < count:
        batch_size = min(100, count - fetched)
        batch = await get_match_ids(puuid, api_key, count=batch_size, start=fetched, queue=queue, start_time=start_time)
        if not batch:
            break
        match_ids.extend(batch)
        fetched += len(batch)
        if len(batch) < batch_size:
            break  # No more matches available

    # Step 3: Fetch and parse each match (skip existing)
    new_games = []
    for mid in match_ids:
        if mid in existing_match_ids:
            continue
        try:
            match_data = await get_match_detail(mid, api_key)
            parsed = parse_match(match_data, puuid)
            if parsed:
                new_games.append(parsed)
        except RiotAPIError as e:
            logger.warning(f"Failed to fetch match {mid}: {e}")
            if e.status_code == 429:
                # Wait and retry once on rate limit
                logger.info("Rate limited during match fetch, waiting 130s...")
                await asyncio.sleep(130)
                try:
                    match_data = await get_match_detail(mid, api_key)
                    parsed = parse_match(match_data, puuid)
                    if parsed:
                        new_games.append(parsed)
                except RiotAPIError:
                    break  # Still rate limited, stop
            continue

    return new_games


# ── League V4 — Rank / LP ───────────────────────────────────────

async def get_ranked_stats(puuid: str, api_key: str) -> list[dict]:
    """Get ranked stats (tier, rank, LP, wins/losses) for a player."""
    url = f"{LEAGUE_V4}/entries/by-puuid/{puuid}"
    return await _get(url, api_key)


async def get_rank_info(game_name: str, tag_line: str, api_key: str) -> dict | None:
    """Get solo queue rank info for a player. Returns None if unranked."""
    puuid = await get_puuid(game_name, tag_line, api_key)
    entries = await get_ranked_stats(puuid, api_key)
    _NO_DIVISION_TIERS = {"MASTER", "GRANDMASTER", "CHALLENGER"}
    for entry in entries:
        if entry.get("queueType") == "RANKED_SOLO_5x5":
            tier = entry.get("tier")
            return {
                "tier": tier,
                "rank": None if tier in _NO_DIVISION_TIERS else entry.get("rank"),
                "lp": entry.get("leaguePoints", 0),
                "wins": entry.get("wins", 0),
                "losses": entry.get("losses", 0),
                "hot_streak": entry.get("hotStreak", False),
                "winrate": round(entry["wins"] / max(entry["wins"] + entry["losses"], 1) * 100, 1),
            }
    return None


# ── Match V5 Timeline — Gold diff, first blood, etc. ────────────

async def get_match_timeline(match_id: str, api_key: str) -> dict:
    """Get the timeline for a match."""
    url = f"{MATCH_V5}/matches/{match_id}/timeline"
    return await _get(url, api_key)


def parse_timeline(timeline_data: dict, puuid: str) -> dict:
    """Extract useful stats from a match timeline."""
    info = timeline_data.get("info", {})
    frames = info.get("frames", [])
    
    # Find participant ID for the puuid
    participants = timeline_data.get("metadata", {}).get("participants", [])
    participant_id = None
    for i, p in enumerate(participants):
        if p == puuid:
            participant_id = i + 1  # 1-indexed
            break
    
    if participant_id is None:
        return {}

    result = {
        "gold_at_10": None,
        "gold_at_15": None,
        "gold_diff_at_15": None,
        "cs_at_10": None,
        "cs_at_15": None,
        "first_blood": False,
        "first_blood_victim": False,
    }

    # Find lane opponent participant ID (from match data, not timeline)
    # We'll compute gold/cs at specific timestamps
    for frame in frames:
        timestamp_min = frame.get("timestamp", 0) // 60000
        pf = frame.get("participantFrames", {})
        my_frame = pf.get(str(participant_id), {})
        
        if timestamp_min == 10:
            result["gold_at_10"] = my_frame.get("totalGold", 0)
            result["cs_at_10"] = my_frame.get("minionsKilled", 0) + my_frame.get("jungleMinionsKilled", 0)
        elif timestamp_min == 15:
            result["gold_at_15"] = my_frame.get("totalGold", 0)
            result["cs_at_15"] = my_frame.get("minionsKilled", 0) + my_frame.get("jungleMinionsKilled", 0)
            # Gold diff at 15: sum all enemy gold vs all ally gold
            my_team = 1 if participant_id <= 5 else 2
            ally_gold = sum(pf.get(str(pid), {}).get("totalGold", 0) for pid in range(1, 11) if (pid <= 5) == (my_team == 1))
            enemy_gold = sum(pf.get(str(pid), {}).get("totalGold", 0) for pid in range(1, 11) if (pid <= 5) != (my_team == 1))
            result["gold_diff_at_15"] = ally_gold - enemy_gold

    # Check first blood events
    for frame in frames:
        for event in frame.get("events", []):
            if event.get("type") == "CHAMPION_KILL":
                # First kill in the game
                if event.get("killerId") == participant_id:
                    result["first_blood"] = True
                if event.get("victimId") == participant_id:
                    result["first_blood_victim"] = True
                break  # Only check the first kill event
        if result["first_blood"] or result["first_blood_victim"]:
            break

    return result


# ── Spectator V5 — Live game status ─────────────────────────────

async def get_active_game(puuid: str, api_key: str) -> dict | None:
    """Check if player is currently in a game. Returns game data or None."""
    url = f"{SPECTATOR_V5}/active-games/by-summoner/{puuid}"
    try:
        return await _get(url, api_key)
    except RiotAPIError as e:
        if e.status_code == 404:
            return None  # Not in game
        raise


async def get_live_game(game_name: str, tag_line: str, api_key: str) -> dict | None:
    """Check if a player is in a live game. Returns parsed info or None."""
    puuid = await get_puuid(game_name, tag_line, api_key)
    active = await get_active_game(puuid, api_key)
    if not active:
        return None
    
    # Find the player in the game
    my_data = None
    for p in active.get("participants", []):
        if p.get("puuid") == puuid:
            my_data = p
            break
    
    game_start = active.get("gameStartTime", 0)
    game_length = active.get("gameLength", 0)
    
    return {
        "in_game": True,
        "game_mode": active.get("gameMode"),
        "game_type": active.get("gameType"),
        "champion": my_data.get("championId") if my_data else None,
        "game_length_seconds": game_length,
        "game_start_time": game_start,
        "map_id": active.get("mapId"),
    }


async def _live_fetch_rank(puuid: str, api_key: str, sem: asyncio.Semaphore) -> dict | None:
    """Fetch ranked stats for a player (live game helper)."""
    try:
        async with sem:
            entries = await _get(f"{LEAGUE_V4}/entries/by-puuid/{puuid}", api_key)
        for entry in entries:
            if entry.get("queueType") == "RANKED_SOLO_5x5":
                wins = entry.get("wins", 0)
                losses = entry.get("losses", 0)
                total = wins + losses
                return {
                    "tier": entry.get("tier", "UNRANKED"),
                    "rank": entry.get("rank", ""),
                    "lp": entry.get("leaguePoints", 0),
                    "wins": wins,
                    "losses": losses,
                    "winrate": round(wins / max(total, 1) * 100, 1),
                    "hot_streak": entry.get("hotStreak", False),
                }
    except Exception:
        pass
    return None


async def _live_fetch_mastery(puuid: str, champ_id: int, api_key: str, sem: asyncio.Semaphore) -> dict:
    """Fetch champion mastery for current champion (live game helper)."""
    try:
        async with sem:
            url = f"{CHAMPION_MASTERY_V4}/champion-masteries/by-puuid/{puuid}/by-champion/{champ_id}"
            m = await _get(url, api_key)
        return {"points": m.get("championPoints", 0), "level": m.get("championLevel", 0)}
    except Exception:
        return {"points": 0, "level": 0}


async def _live_fetch_matches(
    puuid: str, champion_name: str, api_key: str, sem: asyncio.Semaphore,
    detail_count: int = 5,
) -> dict:
    """Fetch recent ranked matches and compute per-champion/role stats.
    Also extracts data needed for: duo detection, champion pool,
    tilt/mental state, rank trajectory, head-to-head, early game.
    """
    try:
        async with sem:
            match_ids = await _get(
                f"{MATCH_V5}/matches/by-puuid/{puuid}/ids",
                api_key,
                {"count": 20, "queue": 420},
            )
        if not match_ids:
            return {"champion_stats": None, "role_distribution": {}, "recent_results": [],
                    "total_recent": 0, "match_ids": [], "unique_champions": [],
                    "games_today": 0, "kda_trend": [], "co_players": {}}

        # Fetch match details (limited to detail_count)
        match_details = []
        for mid in match_ids[:detail_count]:
            try:
                async with sem:
                    detail = await _get(f"{MATCH_V5}/matches/{mid}", api_key)
                match_details.append(detail)
            except Exception:
                continue

        # Process matches
        champ_games = champ_wins = champ_kills = champ_deaths = champ_assists = 0
        champ_cs = champ_duration = 0
        champ_gold = champ_damage = champ_vision = 0
        role_counts: dict[str, int] = {}
        recent_results: list[bool] = []
        all_kills = all_deaths = all_assists = 0
        all_games = 0
        all_gold = all_damage = all_vision = all_duration = 0

        # Extra tracking for new features
        unique_champions: set[str] = set()
        games_today = 0
        kda_trend: list[float] = []  # KDA per game (most recent first)
        co_players: dict[str, dict] = {}  # puuid -> {count, same_team_count, games}
        now_ts = datetime.now().timestamp() * 1000

        for md in match_details:
            info = md.get("info", {})
            if info.get("gameDuration", 0) < 300:
                continue
            duration = info.get("gameDuration", 0)
            game_start_ts = info.get("gameStartTimestamp", 0)

            # Check if game was today (within last 24h)
            if game_start_ts and (now_ts - game_start_ts) < 86400000:
                games_today += 1

            # Find this player's data and teammates/opponents
            my_team_id = None
            my_participant = None
            for p in info.get("participants", []):
                if p.get("puuid") == puuid:
                    my_team_id = p.get("teamId")
                    my_participant = p
                    break

            if not my_participant:
                continue

            won = my_participant.get("win", False)
            recent_results.append(won)
            champ_played = my_participant.get("championName", "")
            unique_champions.add(champ_played)
            role = ROLE_MAP.get(my_participant.get("teamPosition", ""), None)
            if role:
                role_counts[role] = role_counts.get(role, 0) + 1

            kills = my_participant.get("kills", 0)
            deaths = my_participant.get("deaths", 0)
            assists = my_participant.get("assists", 0)
            cs = my_participant.get("totalMinionsKilled", 0) + my_participant.get("neutralMinionsKilled", 0)
            gold = my_participant.get("goldEarned", 0)
            damage = my_participant.get("totalDamageDealtToChampions", 0)
            vision = my_participant.get("visionScore", 0)

            # KDA trend
            game_kda = (kills + assists) / max(deaths, 1)
            kda_trend.append(round(game_kda, 2))

            all_games += 1
            all_kills += kills
            all_deaths += deaths
            all_assists += assists
            all_gold += gold
            all_damage += damage
            all_vision += vision
            all_duration += duration

            if champ_played == champion_name:
                champ_games += 1
                if won:
                    champ_wins += 1
                champ_kills += kills
                champ_deaths += deaths
                champ_assists += assists
                champ_cs += cs
                champ_duration += duration
                champ_gold += gold
                champ_damage += damage
                champ_vision += vision

            # Track co-players for duo detection + head-to-head
            match_id = md.get("metadata", {}).get("matchId", "")
            for p in info.get("participants", []):
                p_puuid = p.get("puuid", "")
                if p_puuid == puuid or not p_puuid:
                    continue
                same_team = p.get("teamId") == my_team_id
                if p_puuid not in co_players:
                    co_players[p_puuid] = {"count": 0, "same_team": 0, "enemy": 0, "matches": []}
                co_players[p_puuid]["count"] += 1
                if same_team:
                    co_players[p_puuid]["same_team"] += 1
                else:
                    co_players[p_puuid]["enemy"] += 1
                co_players[p_puuid]["matches"].append(match_id)

        champion_stats = None
        if champ_games > 0:
            champion_stats = {
                "games": champ_games,
                "wins": champ_wins,
                "losses": champ_games - champ_wins,
                "winrate": round(champ_wins / champ_games * 100, 1),
                "avg_kills": round(champ_kills / champ_games, 1),
                "avg_deaths": round(champ_deaths / champ_games, 1),
                "avg_assists": round(champ_assists / champ_games, 1),
                "avg_kda": round((champ_kills + champ_assists) / max(champ_deaths, 1), 2),
                "avg_cs_per_min": round(champ_cs / max(champ_duration / 60, 1), 1),
            }

        # Per-player averages for team stats
        avg_stats = None
        if all_games > 0:
            mins = max(all_duration / 60, 1)
            avg_stats = {
                "avg_kda": round((all_kills + all_assists) / max(all_deaths, 1), 2),
                "gold_per_min": round(all_gold / mins, 0),
                "damage_per_min": round(all_damage / mins, 0),
                "vision_per_min": round(all_vision / mins, 2),
            }

        return {
            "champion_stats": champion_stats,
            "role_distribution": role_counts,
            "recent_results": recent_results,
            "total_recent": len(match_ids),
            "avg_stats": avg_stats,
            # New fields for advanced features
            "match_ids": match_ids,
            "unique_champions": list(unique_champions),
            "games_today": games_today,
            "kda_trend": kda_trend,
            "co_players": co_players,
        }
    except Exception as e:
        logger.warning(f"Failed to fetch recent matches for {puuid}: {e}")
        return {"champion_stats": None, "role_distribution": {}, "recent_results": [],
                "total_recent": 0, "avg_stats": None, "match_ids": [],
                "unique_champions": [], "games_today": 0, "kda_trend": [], "co_players": {}}


def _generate_player_tags(
    rank: dict | None,
    mastery_points: int,
    mastery_level: int,
    champion_stats: dict | None,
    role_distribution: dict,
    detected_role: str | None,
    recent_results: list[bool],
    data_available: bool = True,
) -> list[dict]:
    """Generate Porofessor-style player tags. Returns list of {text, color}."""
    tags: list[dict] = []

    # Hot Streak from ranked API
    if rank and rank.get("hot_streak"):
        tags.append({"text": "Hot Streak 🔥", "color": "orange"})

    # Win/Loss streak from recent games
    if len(recent_results) >= 3:
        if all(recent_results[:3]):
            streak = sum(1 for r in recent_results if r)
            tags.append({"text": f"{streak}W Streak 🔥", "color": "green"})
        elif not any(recent_results[:3]):
            streak = sum(1 for r in recent_results if not r)
            tags.append({"text": f"{streak}L Streak ❄️", "color": "red"})

    # OTP / Main detection
    if mastery_points >= 200000:
        tags.append({"text": "OTP", "color": "purple"})
    elif mastery_points >= 80000:
        tags.append({"text": "Main", "color": "blue"})

    # First time champion — only tag if we actually have data for this player
    # (streamer mode / private profiles return 0 mastery + no stats, which is a false positive)
    if data_available and mastery_points < 3000 and (not champion_stats or champion_stats.get("games", 0) == 0):
        tags.append({"text": "First Time? 🆕", "color": "yellow"})

    # Private / Streamer mode — we couldn't fetch any data
    if not data_available:
        tags.append({"text": "Private 🔒", "color": "gray"})

    # AutoFilled detection
    if detected_role and role_distribution:
        total_games = sum(role_distribution.values())
        role_games = role_distribution.get(detected_role, 0)
        if total_games >= 3 and role_games == 0:
            tags.append({"text": "AutoFilled? 🎲", "color": "red"})
        elif total_games >= 4 and role_games / total_games < 0.15:
            tags.append({"text": "Off-Role ⚠️", "color": "yellow"})

    # Champion performance
    if champion_stats:
        wr = champion_stats.get("winrate", 0)
        games = champion_stats.get("games", 0)
        kda = champion_stats.get("avg_kda", 0)
        if wr >= 65 and games >= 3:
            tags.append({"text": f"{wr}% WR Champ ⬆️", "color": "green"})
        elif wr <= 35 and games >= 3:
            tags.append({"text": f"{wr}% WR Champ ⬇️", "color": "red"})
        if kda >= 5:
            tags.append({"text": "KDA Player", "color": "cyan"})

    # Season performance
    if rank:
        total = rank.get("wins", 0) + rank.get("losses", 0)
        wr = rank.get("winrate", 50)
        if total >= 50 and wr >= 56:
            tags.append({"text": "Climbing ⬆️", "color": "green"})
        elif total >= 50 and wr <= 44:
            tags.append({"text": "Struggling ⬇️", "color": "red"})
        if total <= 15:
            tags.append({"text": "Few Games", "color": "gray"})

    return tags


def _compute_team_stats(team: list[dict]) -> dict:
    """Compute aggregate team statistics."""
    if not team:
        return {}

    tier_values = {
        "IRON": 0, "BRONZE": 400, "SILVER": 800, "GOLD": 1200,
        "PLATINUM": 1600, "EMERALD": 2000, "DIAMOND": 2400,
        "MASTER": 2800, "GRANDMASTER": 3200, "CHALLENGER": 3600,
    }
    rank_div_values = {"IV": 0, "III": 100, "II": 200, "I": 300}

    winrates = []
    rank_values = []
    kdas = []
    gold_pms = []
    damage_pms = []
    vision_pms = []

    for p in team:
        r = p.get("rank")
        if r and r.get("winrate"):
            winrates.append(r["winrate"])
            base = tier_values.get(r.get("tier", ""), 0)
            if r.get("tier") in ("MASTER", "GRANDMASTER", "CHALLENGER"):
                rank_values.append(base + r.get("lp", 0))
            else:
                rank_values.append(base + rank_div_values.get(r.get("rank", ""), 0) + r.get("lp", 0))
        avg = p.get("avg_stats")
        if avg:
            kdas.append(avg.get("avg_kda", 0))
            gold_pms.append(avg.get("gold_per_min", 0))
            damage_pms.append(avg.get("damage_per_min", 0))
            vision_pms.append(avg.get("vision_per_min", 0))

    # Convert avg rank value back to tier/division string
    avg_rank_str = None
    if rank_values:
        avg_val = sum(rank_values) / len(rank_values)
        for tier_name, tier_base in sorted(tier_values.items(), key=lambda x: x[1], reverse=True):
            if avg_val >= tier_base:
                remainder = avg_val - tier_base
                if tier_name in ("MASTER", "GRANDMASTER", "CHALLENGER"):
                    avg_rank_str = f"{tier_name} {int(remainder)}LP"
                else:
                    for div_name, div_base in sorted(rank_div_values.items(), key=lambda x: x[1], reverse=True):
                        if remainder >= div_base:
                            avg_rank_str = f"{tier_name} {div_name}"
                            break
                break

    return {
        "avg_winrate": round(sum(winrates) / len(winrates), 1) if winrates else None,
        "avg_rank_str": avg_rank_str,
        "avg_kda": round(sum(kdas) / len(kdas), 2) if kdas else None,
        "avg_gold_per_min": round(sum(gold_pms) / len(gold_pms)) if gold_pms else None,
        "avg_damage_per_min": round(sum(damage_pms) / len(damage_pms)) if damage_pms else None,
        "avg_vision_per_min": round(sum(vision_pms) / len(vision_pms), 2) if vision_pms else None,
    }


# ── Matchup Scoring System ──────────────────────────────────────

_TIER_VALUES = {
    "IRON": 0, "BRONZE": 400, "SILVER": 800, "GOLD": 1200,
    "PLATINUM": 1600, "EMERALD": 2000, "DIAMOND": 2400,
    "MASTER": 2800, "GRANDMASTER": 3200, "CHALLENGER": 3600,
}
_RANK_DIV_VALUES = {"IV": 0, "III": 100, "II": 200, "I": 300}
_ROLE_ORDER = ["top", "jungle", "mid", "adc", "support"]


def _rank_to_numeric(rank: dict | None) -> int:
    """Convert rank dict to a numeric value. Unranked returns 800 (Silver)."""
    if not rank or rank.get("tier") == "UNRANKED":
        return 800
    base = _TIER_VALUES.get(rank.get("tier", ""), 800)
    if rank.get("tier") in ("MASTER", "GRANDMASTER", "CHALLENGER"):
        return base + rank.get("lp", 0)
    return base + _RANK_DIV_VALUES.get(rank.get("rank", ""), 0) + rank.get("lp", 0)


def _score_player(p: dict) -> dict:
    """Score a player on multiple dimensions (each 0–100). Returns breakdown + total."""

    rank = p.get("rank")
    cs = p.get("champion_stats")
    role = p.get("role")
    main_roles = p.get("main_roles", [])
    role_dist = {}
    if main_roles:
        # Rebuild rough distribution from main_roles order
        for i, r in enumerate(main_roles):
            role_dist[r] = max(5 - i * 2, 1)
    mastery_pts = p.get("mastery_points", 0)
    mastery_lvl = p.get("mastery_level", 0)
    recent = p.get("recent_games", {})
    recent_results = recent.get("results", [])

    # ── 1. Rank Score (0–100) ────────────────────────────
    # Scale: Iron IV (0) = 0, Challenger 1500LP (5100) ≈ 100
    rank_numeric = _rank_to_numeric(rank)
    rank_score = min(100, round(rank_numeric / 40))  # ~2800 Master = 70, ~3600 Chall = 90

    # ── 2. Season Performance (0–100) ────────────────────
    season_score = 50  # default
    if rank:
        wr = rank.get("winrate", 50)
        total_games = rank.get("wins", 0) + rank.get("losses", 0)
        # Base from winrate: 40% → 30, 50% → 50, 60% → 70
        season_score = min(100, max(0, round((wr - 30) * 100 / 40)))
        # Confidence: more games = more reliable (min 10 games for full weight)
        confidence = min(1.0, total_games / 50)
        # Blend towards 50 if few games
        season_score = round(50 + (season_score - 50) * confidence)
        # Bonus for lots of games played (experience)
        if total_games >= 500:
            season_score = min(100, season_score + 10)
        elif total_games >= 200:
            season_score = min(100, season_score + 5)

    # ── 3. Champion Mastery (0–100) ──────────────────────
    # Points: 0=0, 50k=40, 100k=60, 200k=75, 500k=90, 1M+=100
    if mastery_pts >= 1_000_000:
        mastery_score = 100
    elif mastery_pts >= 500_000:
        mastery_score = 90 + round((mastery_pts - 500_000) / 50_000)
    elif mastery_pts >= 200_000:
        mastery_score = 75 + round((mastery_pts - 200_000) / 20_000)
    elif mastery_pts >= 100_000:
        mastery_score = 60 + round((mastery_pts - 100_000) / 6_667)
    elif mastery_pts >= 50_000:
        mastery_score = 40 + round((mastery_pts - 50_000) / 2_500)
    elif mastery_pts >= 10_000:
        mastery_score = 15 + round((mastery_pts - 10_000) / 1_600)
    else:
        mastery_score = round(mastery_pts / 667)
    mastery_score = min(100, max(0, mastery_score))

    # ── 4. Champion Performance (0–100) ──────────────────
    data_available = p.get("data_available", True)
    if not data_available:
        mastery_score = 50  # Neutral – private profile
    champ_perf_score = 40  # default (no data = neutral-low)
    if not data_available:
        champ_perf_score = 50  # Neutral – private profile
    elif cs:
        champ_wr = cs.get("winrate", 50)
        champ_kda = cs.get("avg_kda", 2.0)
        champ_games = cs.get("games", 0)
        # WR component (40% → 20, 50% → 50, 70% → 90)
        wr_component = min(100, max(0, round((champ_wr - 30) * 100 / 50)))
        # KDA component (1.0 → 20, 3.0 → 60, 5.0 → 80, 8.0+ → 100)
        kda_component = min(100, max(0, round(champ_kda * 13)))
        # Games confidence
        game_factor = min(1.0, champ_games / 10)
        champ_perf_score = round(
            wr_component * 0.5 + kda_component * 0.3 + game_factor * 100 * 0.2
        )
    elif mastery_pts < 3000:
        champ_perf_score = 20  # First time champion

    # ── 5. Role Fit (0–100) ──────────────────────────────
    role_fit_score = 50  # default (unknown role)
    if role:
        if main_roles and role == main_roles[0]:
            role_fit_score = 100  # Main role
        elif main_roles and len(main_roles) > 1 and role == main_roles[1]:
            role_fit_score = 75  # Secondary role
        elif main_roles and role not in main_roles:
            # Check if any tag says autofilled
            tags = p.get("tags", [])
            is_autofilled = any("AutoFilled" in t.get("text", "") for t in tags)
            role_fit_score = 25 if is_autofilled else 40
        else:
            role_fit_score = 60  # No main role data but role detected

    # ── 6. Momentum / Form (0–100) ───────────────────────
    momentum_score = 50  # neutral default
    if recent_results:
        wins_recent = sum(1 for r in recent_results if r)
        total_recent = len(recent_results)
        recent_wr = wins_recent / total_recent * 100

        # Base from recent WR
        momentum_score = min(100, max(0, round(recent_wr)))

        # Streak detection (first 3 games)
        first3 = recent_results[:3]
        if len(first3) >= 3:
            if all(first3):
                momentum_score = min(100, momentum_score + 15)
            elif not any(first3):
                momentum_score = max(0, momentum_score - 15)

    # Hot streak from ranked API
    if rank and rank.get("hot_streak"):
        momentum_score = min(100, momentum_score + 10)

    # ── Total (weighted) ─────────────────────────────────
    weights = {
        "rank": 0.30,
        "season": 0.20,
        "mastery": 0.15,
        "champion": 0.15,
        "role_fit": 0.10,
        "momentum": 0.10,
    }
    scores = {
        "rank": rank_score,
        "season": season_score,
        "mastery": mastery_score,
        "champion": champ_perf_score,
        "role_fit": role_fit_score,
        "momentum": momentum_score,
    }
    total = sum(scores[k] * weights[k] for k in weights)

    return {
        "scores": scores,
        "total": round(total, 1),
    }


def _compute_matchups(my_team: list[dict], enemy_team: list[dict]) -> list[dict]:
    """Match players by role across teams and compare scores."""

    def _role_scores(p: dict) -> dict[str, float]:
        """Compute a probability-like score for each role based on match history + spells."""
        scores: dict[str, float] = {r: 0.0 for r in _ROLE_ORDER}
        role_dist = p.get("role_distribution", {}) or {}
        total_games = sum(role_dist.values()) if role_dist else 0

        # Match history signal (0-100)
        if total_games > 0:
            for role, count in role_dist.items():
                if role in scores:
                    scores[role] += (count / total_games) * 100

        # Summoner spell heuristic (bonus points)
        spells = {p.get("spell1", 0), p.get("spell2", 0)}
        if 11 in spells:     # Smite → Jungle (strong)
            scores["jungle"] += 200
        if 7 in spells:      # Heal → ADC
            scores["adc"] += 40
        if 21 in spells:     # Barrier → Mid
            scores["mid"] += 30
        if 12 in spells:     # Teleport → Top, sometimes Mid
            scores["top"] += 20
            scores["mid"] += 10
        if 3 in spells:      # Exhaust → Support
            scores["support"] += 25
        if 1 in spells:      # Cleanse → ADC or Mid
            scores["adc"] += 15
            scores["mid"] += 15

        return scores

    def _assign_roles(team: list[dict]) -> list[dict]:
        """Assign canonical roles using score-based constraint assignment.
        Each player gets a score per role from match history + spell heuristics.
        Greedy assignment picks the best (player, role) pair iteratively."""
        if not team:
            return []
        # Build score matrix
        player_scores = []
        for p in team:
            pid = p.get("puuid") or p.get("summoner_name") or id(p)
            player_scores.append((pid, p, _role_scores(p)))

        assigned = []
        used_pids: set = set()
        used_roles: set = set()

        # Greedy: pick highest-scoring (player, role) pair each iteration
        for _ in range(len(team)):
            best_score = -1
            best_pid = None
            best_player = None
            best_role = None
            for pid, p, scores in player_scores:
                if pid in used_pids:
                    continue
                for role in _ROLE_ORDER:
                    if role in used_roles:
                        continue
                    if scores[role] > best_score:
                        best_score = scores[role]
                        best_pid = pid
                        best_player = p
                        best_role = role
            if best_player is None:
                break
            assigned.append({**best_player, "_assigned_role": best_role})
            used_pids.add(best_pid)
            used_roles.add(best_role)

        return sorted(assigned, key=lambda x: _ROLE_ORDER.index(x.get("_assigned_role", "support")) if x.get("_assigned_role") in _ROLE_ORDER else 99)

    my_assigned = _assign_roles(my_team)
    enemy_assigned = _assign_roles(enemy_team)

    matchups = []
    for i, role in enumerate(_ROLE_ORDER):
        my_player = next((p for p in my_assigned if p.get("_assigned_role") == role), None)
        enemy_player = next((p for p in enemy_assigned if p.get("_assigned_role") == role), None)

        if not my_player or not enemy_player:
            continue

        my_scores = _score_player(my_player)
        enemy_scores = _score_player(enemy_player)

        my_total = my_scores["total"]
        enemy_total = enemy_scores["total"]
        diff = my_total - enemy_total

        # Determine advantages per dimension
        advantages_mine = []
        advantages_enemy = []
        dimension_labels = {
            "rank": "Rank",
            "season": "Season WR",
            "mastery": "Mastery",
            "champion": "Champion XP",
            "role_fit": "Role Fit",
            "momentum": "Momentum",
        }
        for dim in my_scores["scores"]:
            delta = my_scores["scores"][dim] - enemy_scores["scores"][dim]
            if delta >= 12:
                advantages_mine.append(dimension_labels.get(dim, dim))
            elif delta <= -12:
                advantages_enemy.append(dimension_labels.get(dim, dim))

        # Confidence: how clear is the advantage?
        abs_diff = abs(diff)
        if abs_diff >= 12:
            confidence = "high"
            verdict = "clear"
        elif abs_diff >= 3:
            confidence = "medium"
            verdict = "slight"
        else:
            confidence = "low"
            verdict = "even"

        if diff > 0:
            winner = "my_team"
            winner_name = my_player.get("summoner_name", "?")
            winner_champ = my_player.get("champion_name", "?")
            loser_name = enemy_player.get("summoner_name", "?")
            loser_champ = enemy_player.get("champion_name", "?")
        elif diff < 0:
            winner = "enemy_team"
            winner_name = enemy_player.get("summoner_name", "?")
            winner_champ = enemy_player.get("champion_name", "?")
            loser_name = my_player.get("summoner_name", "?")
            loser_champ = my_player.get("champion_name", "?")
        else:
            winner = "even"
            winner_name = ""
            winner_champ = ""
            loser_name = ""
            loser_champ = ""

        matchups.append({
            "role": role,
            "my_player": {
                "name": my_player.get("summoner_name", "?"),
                "champion": my_player.get("champion_name", "?"),
                "score": my_total,
                "scores": my_scores["scores"],
            },
            "enemy_player": {
                "name": enemy_player.get("summoner_name", "?"),
                "champion": enemy_player.get("champion_name", "?"),
                "score": enemy_total,
                "scores": enemy_scores["scores"],
            },
            "diff": round(diff, 1),
            "winner": winner,
            "winner_name": winner_name,
            "winner_champ": winner_champ,
            "verdict": verdict,
            "confidence": confidence,
            "advantages_mine": advantages_mine,
            "advantages_enemy": advantages_enemy,
        })

    # Overall team comparison
    my_total_score = sum(m["my_player"]["score"] for m in matchups)
    enemy_total_score = sum(m["enemy_player"]["score"] for m in matchups)
    lanes_won = sum(1 for m in matchups if m["winner"] == "my_team")
    lanes_lost = sum(1 for m in matchups if m["winner"] == "enemy_team")
    lanes_even = sum(1 for m in matchups if m["winner"] == "even")

    return {
        "matchups": matchups,
        "summary": {
            "my_team_score": round(my_total_score, 1),
            "enemy_team_score": round(enemy_total_score, 1),
            "lanes_won": lanes_won,
            "lanes_lost": lanes_lost,
            "lanes_even": lanes_even,
            "advantage": "my_team" if my_total_score > enemy_total_score else ("enemy_team" if enemy_total_score > my_total_score else "even"),
        },
    }


# ── Feature 2: Duo Detection ────────────────────────────────────

def _detect_duos(team: list[dict]) -> list[dict]:
    """Detect likely duo partners within a team by cross-referencing match IDs."""
    duos = []
    for i in range(len(team)):
        for j in range(i + 1, len(team)):
            p1 = team[i]
            p2 = team[j]
            p2_puuid = p2.get("puuid", "")
            co = p1.get("co_players", {}).get(p2_puuid)
            if co and co.get("same_team", 0) >= 2:
                duos.append({
                    "player1": p1.get("summoner_name", "?"),
                    "player2": p2.get("summoner_name", "?"),
                    "games_together": co["same_team"],
                    "roles": [p1.get("role"), p2.get("role")],
                })
    return duos


# ── Feature 3: Champion Pool Depth ──────────────────────────────

def _champion_pool_depth(p: dict) -> dict:
    """Classify champion pool depth for a player."""
    unique = p.get("unique_champions", [])
    count = len(unique)
    mastery = p.get("mastery_points", 0)
    champ_name = p.get("champion_name", "")

    if count <= 2:
        category = "otp"
        label = "OTP"
    elif count <= 4:
        category = "specialist"
        label = "Specialist"
    else:
        category = "versatile"
        label = "Versátil"

    # Check if playing their main champion
    on_main = champ_name in unique[:2] if unique else False

    return {
        "unique_champions": count,
        "champions_played": unique,
        "category": category,
        "label": label,
        "on_main": on_main,
    }


# ── Feature 4: Tilt / Mental State ──────────────────────────────

def _assess_mental_state(p: dict) -> dict:
    """Assess a player's current mental state / tilt level."""
    results = p.get("recent_games", {}).get("results", [])
    games_today = p.get("games_today", 0)
    kda_trend = p.get("kda_trend", [])
    tags = p.get("tags", [])
    mastery = p.get("mastery_points", 0)
    champ_stats = p.get("champion_stats")

    tilt_score = 0  # 0 = calm, 100 = hard tilt
    signals = []

    # Loss streak
    if len(results) >= 3 and not any(results[:3]):
        tilt_score += 30
        signals.append("loss_streak")
    elif len(results) >= 2 and not any(results[:2]):
        tilt_score += 15
        signals.append("losing")

    # Marathon — many games today
    if games_today >= 8:
        tilt_score += 25
        signals.append("marathon")
    elif games_today >= 5:
        tilt_score += 15
        signals.append("many_games")
    elif games_today >= 3:
        tilt_score += 5

    # KDA deteriorating (trend getting worse)
    if len(kda_trend) >= 3:
        recent_avg = sum(kda_trend[:2]) / 2 if len(kda_trend) >= 2 else kda_trend[0]
        older_avg = sum(kda_trend[2:]) / max(len(kda_trend) - 2, 1)
        if older_avg > 0 and recent_avg < older_avg * 0.6:
            tilt_score += 20
            signals.append("kda_dropping")
        elif older_avg > 0 and recent_avg < older_avg * 0.8:
            tilt_score += 10

    # First time champion in ranked — only if we have data (not streamer mode)
    data_available = p.get("data_available", True)
    if data_available and mastery < 3000 and (not champ_stats or champ_stats.get("games", 0) == 0):
        tilt_score += 10
        signals.append("first_time")

    # Unusual pick (off-role + low mastery)
    is_autofilled = any("AutoFilled" in t.get("text", "") for t in tags)
    if is_autofilled:
        tilt_score += 10
        signals.append("autofilled")

    # Determine state
    tilt_score = min(100, tilt_score)
    if tilt_score >= 50:
        state = "tilted"
        label = "Possível Tilt 🔥"
        color = "red"
    elif tilt_score >= 25:
        state = "stressed"
        label = "Sob Pressão 😤"
        color = "orange"
    elif games_today == 0 or (len(results) >= 2 and all(results[:2])):
        state = "fresh"
        label = "Jogador Fresh ❄️"
        color = "cyan"
    else:
        state = "neutral"
        label = "Estável"
        color = "gray"

    result = {
        "state": state,
        "label": label,
        "color": color,
        "tilt_score": tilt_score,
        "signals": signals,
        "games_today": games_today,
    }
    if games_today >= 5:
        result["marathon_label"] = f"Maratona 🏃 ({games_today} jogos hoje)"

    return result


# ── Feature 5: Rank Trajectory ───────────────────────────────────

def _rank_trajectory(p: dict) -> dict:
    """Determine if a player is climbing, declining, or is a smurf."""
    rank = p.get("rank")
    if not rank:
        return {"trajectory": "unknown", "label": "Sem dados"}

    total = rank.get("wins", 0) + rank.get("losses", 0)
    wr = rank.get("winrate", 50)
    recent = p.get("recent_games", {}).get("results", [])
    recent_wr = (sum(1 for r in recent if r) / max(len(recent), 1) * 100) if recent else 50

    # Smurf detection: few games + very high WR + strong KDA
    avg_stats = p.get("avg_stats")
    avg_kda = avg_stats.get("avg_kda", 2) if avg_stats else 2
    is_smurf = total <= 40 and wr >= 65 and avg_kda >= 4

    if is_smurf:
        return {
            "trajectory": "smurf",
            "label": "🎭 Possível Smurf",
            "detail": f"{wr}% WR em {total} jogos",
            "color": "purple",
        }

    if total >= 50 and wr >= 56:
        return {
            "trajectory": "climbing",
            "label": "📈 A Subir",
            "detail": f"{wr}% WR em {total} jogos",
            "color": "green",
        }

    if total >= 50 and wr <= 46:
        return {
            "trajectory": "declining",
            "label": "📉 A Descer",
            "detail": f"{wr}% WR em {total} jogos",
            "color": "red",
        }

    if total >= 30 and recent_wr >= 70:
        return {
            "trajectory": "hot",
            "label": "🔥 Em Forma",
            "detail": f"{int(recent_wr)}% WR recente",
            "color": "orange",
        }

    if total >= 30 and recent_wr <= 30:
        return {
            "trajectory": "cold",
            "label": "🥶 Em Baixa",
            "detail": f"{int(recent_wr)}% WR recente",
            "color": "blue",
        }

    return {
        "trajectory": "stable",
        "label": "➡️ Estável",
        "detail": f"{wr}% WR em {total} jogos",
        "color": "gray",
    }


# ── Feature 6: Head-to-Head Detection ───────────────────────────

def _detect_head_to_head(my_puuid: str, my_team: list[dict], enemy_team: list[dict]) -> list[dict]:
    """Cross-reference your match history with all other 9 players to find past encounters."""
    encounters = []
    me = None
    for p in my_team:
        if p.get("puuid") == my_puuid:
            me = p
            break
    if not me:
        return encounters

    my_co = me.get("co_players", {})
    all_others = [(p, "ally") for p in my_team if p.get("puuid") != my_puuid] + \
                 [(p, "enemy") for p in enemy_team]

    for player, relation in all_others:
        p_puuid = player.get("puuid", "")
        co = my_co.get(p_puuid)
        if co and co.get("count", 0) > 0:
            encounters.append({
                "player_name": player.get("summoner_name", "?"),
                "champion": player.get("champion_name", "?"),
                "games_with": co.get("same_team", 0),
                "games_against": co.get("enemy", 0),
                "total": co.get("count", 0),
                "current_relation": relation,
            })
    return encounters


# ── Feature 7: Team Comp Analysis (richer) ───────────────────────

# Champion archetype classification
_CHAMPION_ARCHETYPES = {
    # Tanks
    "Ornn": "tank", "Malphite": "tank", "Maokai": "tank", "Sion": "tank",
    "ChoGath": "tank", "Zac": "tank", "Sejuani": "tank", "Nautilus": "tank",
    "Leona": "tank", "TahmKench": "tank", "Alistar": "tank", "Braum": "tank",
    "Rell": "tank", "Poppy": "tank", "Skarner": "tank", "Amumu": "tank",
    "Rammus": "tank", "DrMundo": "tank", "Galio": "tank",
    # Bruisers / Fighters
    "Darius": "bruiser", "Garen": "bruiser", "Mordekaiser": "bruiser",
    "Aatrox": "bruiser", "Sett": "bruiser", "Volibear": "bruiser",
    "Renekton": "bruiser", "Illaoi": "bruiser", "Yorick": "bruiser",
    "Urgot": "bruiser", "Olaf": "bruiser", "Trundle": "bruiser",
    "Vi": "bruiser", "Warwick": "bruiser", "Hecarim": "bruiser",
    "JarvanIV": "bruiser", "XinZhao": "bruiser", "Wukong": "bruiser",
    "LeeSin": "bruiser", "RekSai": "bruiser", "Viego": "bruiser",
    "Irelia": "bruiser", "Jax": "bruiser", "Camille": "bruiser",
    "Fiora": "bruiser", "Riven": "bruiser", "Gwen": "bruiser",
    "KSante": "bruiser", "Briar": "bruiser", "Belveth": "bruiser",
    "Shyvana": "bruiser", "Udyr": "bruiser", "Nasus": "bruiser",
    "Tryndamere": "bruiser", "Kled": "bruiser", "Rengar": "bruiser",
    # Assassins
    "Zed": "assassin", "Talon": "assassin", "Qiyana": "assassin",
    "Akali": "assassin", "Katarina": "assassin", "Fizz": "assassin",
    "Ekko": "assassin", "Diana": "assassin", "Evelynn": "assassin",
    "KhaZix": "assassin", "Shaco": "assassin", "Pyke": "assassin",
    "Kayn": "assassin", "Nocturne": "assassin", "Naafiri": "assassin",
    "Yone": "assassin", "Yasuo": "assassin", "MasterYi": "assassin",
    "Kindred": "assassin", "Nidalee": "assassin", "Elise": "assassin",
    "Lillia": "assassin", "Graves": "assassin",
    # Mages
    "Syndra": "mage", "Orianna": "mage", "Viktor": "mage", "Azir": "mage",
    "AurelionSol": "mage", "Anivia": "mage", "Cassiopeia": "mage",
    "Malzahar": "mage", "Veigar": "mage", "Xerath": "mage",
    "Lux": "mage", "Ziggs": "mage", "VelKoz": "mage", "Brand": "mage",
    "Zyra": "mage", "Swain": "mage", "Ryze": "mage", "TwistedFate": "mage",
    "Ahri": "mage", "Neeko": "mage", "Vex": "mage", "Hwei": "mage",
    "Annie": "mage", "Lissandra": "mage", "Vladimir": "mage",
    "Kennen": "mage", "Rumble": "mage", "Heimerdinger": "mage",
    "Taliyah": "mage", "Sylas": "mage", "Kassadin": "mage",
    "Corki": "mage", "LeBlanc": "mage", "Smolder": "mage",
    "Gragas": "mage", "Karthus": "mage",
    # Marksmen
    "Jinx": "marksman", "KaiSa": "marksman", "Ezreal": "marksman",
    "Jhin": "marksman", "Caitlyn": "marksman", "Vayne": "marksman",
    "Ashe": "marksman", "MissFortune": "marksman", "Lucian": "marksman",
    "Draven": "marksman", "Tristana": "marksman", "Aphelios": "marksman",
    "Varus": "marksman", "Xayah": "marksman", "Sivir": "marksman",
    "KogMaw": "marksman", "Twitch": "marksman", "Samira": "marksman",
    "Zeri": "marksman", "Kalista": "marksman", "Nilah": "marksman",
    "Quinn": "marksman", "Teemo": "marksman",
    # Enchanters
    "Lulu": "enchanter", "Janna": "enchanter", "Nami": "enchanter",
    "Soraka": "enchanter", "Sona": "enchanter", "Yuumi": "enchanter",
    "Karma": "enchanter", "Seraphine": "enchanter", "Milio": "enchanter",
    "Renata": "enchanter", "Zilean": "enchanter", "Ivern": "enchanter",
    "Senna": "enchanter", "Bard": "enchanter", "Taric": "enchanter",
    "Thresh": "enchanter", "Rakan": "enchanter", "Blitzcrank": "enchanter",
    "Morgana": "enchanter", "Nunu": "enchanter",
}

# Scaling classification (late-game power)
_LATE_GAME_CHAMPS = {
    "Jinx", "Vayne", "KaiSa", "Aphelios", "Kassadin", "Vladimir",
    "Veigar", "Kayle", "Nasus", "Senna", "KogMaw", "Cassiopeia",
    "AurelionSol", "Azir", "Ryze", "Sivir", "Twitch", "Viktor",
    "Smolder", "Corki", "Tristana", "Jax", "Fiora", "Camille",
    "Gangplank", "Gwen",
}
_EARLY_GAME_CHAMPS = {
    "Draven", "Renekton", "LeeSin", "Elise", "Nidalee", "Pantheon",
    "Olaf", "Darius", "Rek'Sai", "JarvanIV", "XinZhao", "Caitlyn",
    "LeBlanc", "Talon", "Zed", "Qiyana", "Lucian", "Kalista",
    "Pyke", "Nautilus", "Leona", "Thresh", "Blitzcrank",
}

# Engage champions
_ENGAGE_CHAMPS = {
    "Malphite", "Leona", "Nautilus", "Amumu", "Sejuani", "Zac",
    "Ornn", "Maokai", "Alistar", "Rakan", "Rell", "JarvanIV",
    "Hecarim", "Diana", "Kennen", "Wukong", "Gragas", "Vi",
    "Camille", "Nocturne", "Skarner", "Yone", "Galio", "Annie",
    "Sett", "Rumble",
}

# Split push specialists
_SPLIT_PUSH_CHAMPS = {
    "Fiora", "Jax", "Tryndamere", "Camille", "Yorick", "Nasus",
    "Gwen", "Shen", "Sion", "Kayle",
}

# Poke champions
_POKE_CHAMPS = {
    "Xerath", "Lux", "Ziggs", "VelKoz", "Jayce", "Varus",
    "Ezreal", "Zoe", "Nidalee", "Corki", "Hwei", "KogMaw",
}


def _analyze_team_comp_detailed(team: list[dict]) -> dict:
    """Rich team comp analysis: damage split, archetypes, identity, scaling, CC, engage."""
    ad_champs = []
    ap_champs = []
    mixed_champs = []
    archetype_counts = {"tank": 0, "bruiser": 0, "assassin": 0, "mage": 0, "marksman": 0, "enchanter": 0}
    late_game_count = 0
    early_game_count = 0
    engage_count = 0
    split_push_count = 0
    poke_count = 0

    try:
        from champion_data import get_damage_type
    except Exception:
        get_damage_type = None

    for p in team:
        champ = p.get("champion_name", "")
        champ_id = p.get("champion_id", 0)

        # Damage type
        try:
            dmg = get_damage_type(champ_id) if get_damage_type else "Mixed"
        except Exception:
            dmg = "Mixed"
        if dmg == "AD":
            ad_champs.append(champ)
        elif dmg == "AP":
            ap_champs.append(champ)
        else:
            mixed_champs.append(champ)

        # Archetype
        archetype = _CHAMPION_ARCHETYPES.get(champ, "mage")
        archetype_counts[archetype] = archetype_counts.get(archetype, 0) + 1

        # Scaling
        if champ in _LATE_GAME_CHAMPS:
            late_game_count += 1
        if champ in _EARLY_GAME_CHAMPS:
            early_game_count += 1

        # Engage / Split / Poke
        if champ in _ENGAGE_CHAMPS:
            engage_count += 1
        if champ in _SPLIT_PUSH_CHAMPS:
            split_push_count += 1
        if champ in _POKE_CHAMPS:
            poke_count += 1

    total = len(team)
    ad_pct = round(len(ad_champs) / max(total, 1) * 100)
    ap_pct = round(len(ap_champs) / max(total, 1) * 100)

    # Determine comp identity
    identities = []
    if engage_count >= 2:
        identities.append("Teamfight")
    if poke_count >= 2:
        identities.append("Poke")
    if split_push_count >= 2:
        identities.append("Splitpush")
    if archetype_counts.get("assassin", 0) >= 2:
        identities.append("Pick")
    if not identities:
        if engage_count >= 1 and archetype_counts.get("marksman", 0) >= 1:
            identities.append("Teamfight")
        else:
            identities.append("Standard")

    # Scaling rating: -2 (very early) to +2 (very late)
    scaling_value = late_game_count - early_game_count
    if scaling_value >= 2:
        scaling = "late"
        scaling_label = "🕐 Late Game"
    elif scaling_value <= -2:
        scaling = "early"
        scaling_label = "⚡ Early Game"
    elif late_game_count >= 2:
        scaling = "mid_late"
        scaling_label = "🕑 Mid-Late"
    elif early_game_count >= 2:
        scaling = "early_mid"
        scaling_label = "⚡ Early-Mid"
    else:
        scaling = "balanced"
        scaling_label = "⚖️ Balanced"

    # Warnings
    warnings = []
    if len(ad_champs) >= 4:
        warnings.append("⚠️ Full AD — inimigo builda armor")
    if len(ap_champs) >= 4:
        warnings.append("⚠️ Full AP — MR vai ser problema")
    if engage_count == 0:
        warnings.append("⚠️ Sem engage — difícil forçar fights")
    if archetype_counts.get("tank", 0) == 0 and archetype_counts.get("bruiser", 0) == 0:
        warnings.append("⚠️ Sem frontline — equipa frágil")

    return {
        "ad_count": len(ad_champs),
        "ap_count": len(ap_champs),
        "mixed_count": len(mixed_champs),
        "ad_pct": ad_pct,
        "ap_pct": ap_pct,
        "archetypes": archetype_counts,
        "identities": identities,
        "scaling": scaling,
        "scaling_label": scaling_label,
        "engage_count": engage_count,
        "has_engage": engage_count > 0,
        "has_tank": archetype_counts.get("tank", 0) > 0,
        "split_push": split_push_count,
        "poke": poke_count,
        "warnings": warnings,
    }


# ── Feature 9: Win Probability ───────────────────────────────────

def _compute_win_probability(
    my_team: list[dict], enemy_team: list[dict],
    matchup_analysis: dict,
    my_comp: dict | None = None, enemy_comp: dict | None = None,
    duos_my: list | None = None, duos_enemy: list | None = None,
) -> dict:
    """Estimate win probability using a multi-factor model.

    Research (Chowdhury et al. 2025, Do et al. 2021) shows the most
    important pre-game predictors are:
      1. Rank difference (strongest single predictor)
      2. Champion-specific experience / win-rate
      3. Win/loss streak (momentum)
      4. Team composition factors (damage balance, engage, scaling)
      5. Role fit (autofilled players perform significantly worse)
      6. Duo synergy (coordinated pairs outperform solo players)

    The model uses logistic-style combination: each factor contributes
    additive adjustments to a base probability derived from per-lane
    player score comparisons.
    """
    summary = matchup_analysis.get("summary", {})
    my_score = summary.get("my_team_score", 0)
    en_score = summary.get("enemy_team_score", 0)
    total = my_score + en_score

    if total == 0:
        return {"probability": 50, "confidence": "low", "factors": []}

    # Base probability from per-lane matchup scores
    base_prob = round(my_score / total * 100)

    factors = []

    # ── 1. Rank Differential (strongest pre-game predictor) ──────
    my_ranks = [_rank_to_numeric(p.get("rank")) for p in my_team if p.get("rank")]
    en_ranks = [_rank_to_numeric(p.get("rank")) for p in enemy_team if p.get("rank")]
    if my_ranks and en_ranks:
        my_avg_rank = sum(my_ranks) / len(my_ranks)
        en_avg_rank = sum(en_ranks) / len(en_ranks)
        rank_diff = my_avg_rank - en_avg_rank
        if abs(rank_diff) > 50:
            # Each 100 rank points ≈ 1 division ≈ ~2% win shift
            adj = min(10, max(-10, round(rank_diff / 50)))
            factors.append({"name": "Rank Avg", "value": adj})

    # ── 2. Winrate Differential ──────────────────────────────────
    my_wrs = [p.get("rank", {}).get("winrate", 50) for p in my_team if p.get("rank")]
    en_wrs = [p.get("rank", {}).get("winrate", 50) for p in enemy_team if p.get("rank")]
    if my_wrs and en_wrs:
        wr_diff = (sum(my_wrs) / len(my_wrs)) - (sum(en_wrs) / len(en_wrs))
        if abs(wr_diff) > 1.5:
            adj = min(6, max(-6, round(wr_diff * 0.8)))
            factors.append({"name": "Winrate", "value": adj})

    # ── 3. Autofill Asymmetry ────────────────────────────────────
    my_autofills = sum(1 for p in my_team if any("AutoFilled" in t.get("text", "") for t in p.get("tags", [])))
    en_autofills = sum(1 for p in enemy_team if any("AutoFilled" in t.get("text", "") for t in p.get("tags", [])))
    if my_autofills != en_autofills:
        adj = (en_autofills - my_autofills) * 3
        factors.append({"name": "Autofill", "value": adj})

    # ── 4. First-Timer Asymmetry ─────────────────────────────────
    my_first = sum(1 for p in my_team if any("First Time" in t.get("text", "") for t in p.get("tags", [])))
    en_first = sum(1 for p in enemy_team if any("First Time" in t.get("text", "") for t in p.get("tags", [])))
    if my_first != en_first:
        adj = (en_first - my_first) * 2
        factors.append({"name": "First Time", "value": adj})

    # ── 5. Team Composition Factors ──────────────────────────────
    if my_comp and enemy_comp:
        comp_adj = 0

        # 5a. Full AD/AP penalty — enemy can stack one resistance
        my_warnings = my_comp.get("warnings", [])
        en_warnings = enemy_comp.get("warnings", [])
        my_full_dmg = any("Full AD" in w or "Full AP" in w for w in my_warnings)
        en_full_dmg = any("Full AD" in w or "Full AP" in w for w in en_warnings)
        if my_full_dmg and not en_full_dmg:
            comp_adj -= 4
            factors.append({"name": "Full AD/AP", "value": -4})
        elif en_full_dmg and not my_full_dmg:
            comp_adj += 4
            factors.append({"name": "Full AD/AP", "value": 4})

        # 5b. Engage advantage — teams with engage win teamfights
        my_engage = my_comp.get("engage_count", 0)
        en_engage = enemy_comp.get("engage_count", 0)
        if my_engage >= 2 and en_engage == 0:
            factors.append({"name": "Engage", "value": 3})
        elif en_engage >= 2 and my_engage == 0:
            factors.append({"name": "Engage", "value": -3})

        # 5c. No frontline penalty
        my_no_front = not my_comp.get("has_tank", False) and my_comp.get("archetypes", {}).get("bruiser", 0) == 0
        en_no_front = not enemy_comp.get("has_tank", False) and enemy_comp.get("archetypes", {}).get("bruiser", 0) == 0
        if my_no_front and not en_no_front:
            factors.append({"name": "No Frontline", "value": -2})
        elif en_no_front and not my_no_front:
            factors.append({"name": "No Frontline", "value": 2})

    # ── 6. Duo Synergy ──────────────────────────────────────────
    duos_my = duos_my or []
    duos_enemy = duos_enemy or []
    duo_diff = len(duos_my) - len(duos_enemy)
    if duo_diff != 0:
        adj = min(3, max(-3, duo_diff * 2))
        factors.append({"name": "Duo", "value": adj})

    # ── 7. Momentum / Streak Asymmetry ───────────────────────────
    def _team_momentum(team: list[dict]) -> float:
        """Avg momentum score across team."""
        vals = []
        for p in team:
            ms = p.get("mental_state", {})
            if ms:
                state = ms.get("state", "neutral")
                if state == "tilted":
                    vals.append(25)
                elif state == "on_fire":
                    vals.append(80)
                else:
                    vals.append(50)
            else:
                vals.append(50)
        return sum(vals) / len(vals) if vals else 50

    my_momentum = _team_momentum(my_team)
    en_momentum = _team_momentum(enemy_team)
    momentum_diff = my_momentum - en_momentum
    if abs(momentum_diff) > 8:
        adj = min(4, max(-4, round(momentum_diff / 8)))
        factors.append({"name": "Momentum", "value": adj})

    # ── Apply all factors ────────────────────────────────────────
    total_adj = sum(f["value"] for f in factors)
    probability = max(10, min(90, base_prob + total_adj))

    # Confidence: based on distance from 50 and data quality
    data_available_count = sum(1 for p in my_team + enemy_team if p.get("data_available", True))
    data_quality = data_available_count / max(len(my_team) + len(enemy_team), 1)

    dist = abs(probability - 50)
    if dist >= 15 and data_quality >= 0.7:
        confidence = "high"
    elif dist >= 7:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "probability": probability,
        "confidence": confidence,
        "factors": factors,
    }


# ── Feature 11: Strategic Advice ─────────────────────────────────

def _generate_strategic_advice(
    my_team: list[dict], enemy_team: list[dict],
    matchup_analysis: dict, my_comp: dict, enemy_comp: dict,
    duos_my: list, duos_enemy: list,
) -> list[dict]:
    """Generate automatic pre-game strategic advice based on all analysis."""
    tips = []
    matchups = matchup_analysis.get("matchups", [])

    # Tip: Focus strongest lane
    best_lane = max(matchups, key=lambda m: m.get("diff", 0), default=None) if matchups else None
    worst_lane = min(matchups, key=lambda m: m.get("diff", 0), default=None) if matchups else None
    _ROLE_LABELS = {"top": "Top", "jungle": "Jungle", "mid": "Mid", "adc": "ADC", "support": "Support"}

    if best_lane and best_lane.get("diff", 0) >= 8:
        role = best_lane["role"]
        tips.append({
            "type": "focus",
            "icon": "🎯",
            "text": f"Foca {_ROLE_LABELS.get(role, role)} — vantagem clara (+{best_lane['diff']:.0f} pts)",
            "priority": "high",
        })

    if worst_lane and worst_lane.get("diff", 0) <= -8:
        role = worst_lane["role"]
        enemy = worst_lane.get("enemy_player", {})
        tips.append({
            "type": "warning",
            "icon": "⚠️",
            "text": f"Cuidado com {enemy.get('name', '?').split('#')[0]} ({enemy.get('champion', '?')}) — domina {role}",
            "priority": "high",
        })

    # Tip: Enemy autofills
    for p in enemy_team:
        if any("AutoFilled" in t.get("text", "") for t in p.get("tags", [])):
            tips.append({
                "type": "opportunity",
                "icon": "🎲",
                "text": f"{p['summoner_name'].split('#')[0]} está autofilled ({p.get('role', '?')}) — explora essa lane",
                "priority": "medium",
            })

    # Tip: Enemy first-timers
    for p in enemy_team:
        if any("First Time" in t.get("text", "") for t in p.get("tags", [])):
            tips.append({
                "type": "opportunity",
                "icon": "🆕",
                "text": f"{p['summoner_name'].split('#')[0]} está first-time {p.get('champion_name', '?')} — punir early",
                "priority": "medium",
            })

    # Tip: OTP threats on enemy team
    for p in enemy_team:
        if any("OTP" in t.get("text", "") for t in p.get("tags", [])):
            cs = p.get("champion_stats")
            if cs and cs.get("winrate", 0) >= 55:
                tips.append({
                    "type": "danger",
                    "icon": "💀",
                    "text": f"Cuidado: {p['summoner_name'].split('#')[0]} é OTP de {p.get('champion_name', '?')} ({cs['winrate']}% WR)",
                    "priority": "high",
                })

    # Tip: Scaling advice
    my_scaling = my_comp.get("scaling", "balanced")
    en_scaling = enemy_comp.get("scaling", "balanced")
    if my_scaling in ("early", "early_mid") and en_scaling in ("late", "mid_late"):
        tips.append({
            "type": "strategy",
            "icon": "⏱️",
            "text": "A tua equipa é mais forte no early — fecha o jogo antes dos 30 min",
            "priority": "high",
        })
    elif my_scaling in ("late", "mid_late") and en_scaling in ("early", "early_mid"):
        tips.append({
            "type": "strategy",
            "icon": "🕐",
            "text": "A tua equipa scala melhor — joga safe no early e scala",
            "priority": "high",
        })

    # Tip: Damage type warnings
    for w in my_comp.get("warnings", []):
        tips.append({
            "type": "comp_warning",
            "icon": "🛡️",
            "text": w,
            "priority": "medium",
        })

    # Tip: Enemy duo
    for duo in duos_enemy:
        p1 = duo.get("player1", "?").split("#")[0]
        p2 = duo.get("player2", "?").split("#")[0]
        tips.append({
            "type": "info",
            "icon": "🤝",
            "text": f"{p1} + {p2} são duo ({duo['games_together']} jogos juntos) — comunicam melhor",
            "priority": "medium",
        })

    # Tip: Ally autofilled — help them
    for p in my_team:
        if any("AutoFilled" in t.get("text", "") for t in p.get("tags", [])) and not p.get("is_me"):
            tips.append({
                "type": "ally",
                "icon": "🆘",
                "text": f"{p['summoner_name'].split('#')[0]} está autofilled {p.get('role', '?')} — ajuda-o com ganks",
                "priority": "medium",
            })

    # Tip: Possible smurf warning
    for p in enemy_team:
        trajectory = _rank_trajectory(p)
        if trajectory.get("trajectory") == "smurf":
            tips.append({
                "type": "danger",
                "icon": "🎭",
                "text": f"{p['summoner_name'].split('#')[0]} é possível smurf ({trajectory.get('detail', '')})",
                "priority": "high",
            })

    # Sort by priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    tips.sort(key=lambda t: priority_order.get(t.get("priority", "low"), 2))

    return tips[:10]  # Cap at 10 tips


async def get_live_game_detailed(
    game_name: str, tag_line: str, api_key: str
) -> dict | None:
    """Get detailed live game stats for all participants (Porofessor-style).

    For each player: rank, winrate, champion mastery, recent match stats,
    champion-specific WR/KDA, role detection, player tags, team stats.
    """
    puuid = await get_puuid(game_name, tag_line, api_key)
    active = await get_active_game(puuid, api_key)
    if not active:
        return None

    await _ensure_champion_map()

    game_start = active.get("gameStartTime", 0)
    game_length = active.get("gameLength", 0)
    banned = active.get("bannedChampions", [])

    bans_blue = [
        _champion_id_map.get(b.get("championId", 0), "?")
        for b in banned if b.get("teamId") == 100 and b.get("championId", -1) > 0
    ]
    bans_red = [
        _champion_id_map.get(b.get("championId", 0), "?")
        for b in banned if b.get("teamId") == 200 and b.get("championId", -1) > 0
    ]

    participants = active.get("participants", [])
    my_team_id = None
    for p in participants:
        if p.get("puuid") == puuid:
            my_team_id = p.get("teamId")
            break

    # Semaphore to avoid hitting Riot rate limits (dev key: 20/s, 100/2min)
    sem = asyncio.Semaphore(8)

    async def _get_player_data(p: dict) -> dict:
        p_puuid = p.get("puuid", "")
        champ_id = p.get("championId", 0)
        champ_name = _champion_id_map.get(champ_id, f"Champion {champ_id}")
        team_id = p.get("teamId", 0)
        summoner_name = p.get("riotId", p.get("summonerName", "Unknown"))
        spell1 = p.get("spell1Id", 0)
        spell2 = p.get("spell2Id", 0)

        # Detect role from spells (Smite = Jungle)
        is_jungler = spell1 == 11 or spell2 == 11
        detected_role = "jungle" if is_jungler else None

        # Fetch rank, mastery, and match history concurrently per player
        rank, mastery_data, match_data = await asyncio.gather(
            _live_fetch_rank(p_puuid, api_key, sem),
            _live_fetch_mastery(p_puuid, champ_id, api_key, sem),
            _live_fetch_matches(p_puuid, champ_name, api_key, sem),
            return_exceptions=True,
        )

        if isinstance(rank, Exception):
            rank = None
        if isinstance(mastery_data, Exception):
            mastery_data = {"points": 0, "level": 0}
        if isinstance(match_data, Exception):
            match_data = {"champion_stats": None, "role_distribution": {}, "recent_results": [], "total_recent": 0, "avg_stats": None}

        # Detect streamer mode / private profile: all data fetches returned nothing useful
        has_rank = rank is not None
        has_mastery = mastery_data.get("points", 0) > 0 or mastery_data.get("level", 0) > 0
        has_matches = bool(match_data.get("recent_results")) or match_data.get("total_recent", 0) > 0
        data_available = has_rank or has_mastery or has_matches

        # Determine role from match history if not jungler
        role_dist = match_data.get("role_distribution", {})
        if not detected_role and role_dist:
            detected_role = max(role_dist, key=role_dist.get)

        # Main roles (top 2)
        main_roles = sorted(role_dist.keys(), key=lambda r: role_dist[r], reverse=True)[:2] if role_dist else []
        role_games = role_dist.get(detected_role, 0) if detected_role else 0

        # Generate player tags
        tags = _generate_player_tags(
            rank=rank,
            mastery_points=mastery_data.get("points", 0),
            mastery_level=mastery_data.get("level", 0),
            champion_stats=match_data.get("champion_stats"),
            role_distribution=role_dist,
            detected_role=detected_role,
            recent_results=match_data.get("recent_results", []),
            data_available=data_available,
        )

        return {
            "summoner_name": summoner_name,
            "puuid": p_puuid,
            "champion_id": champ_id,
            "champion_name": champ_name,
            "team_id": team_id,
            "is_me": p_puuid == puuid,
            "spell1": spell1,
            "spell2": spell2,
            "rank": rank,
            "mastery_points": mastery_data.get("points", 0),
            "mastery_level": mastery_data.get("level", 0),
            "champion_stats": match_data.get("champion_stats"),
            "role": detected_role,
            "role_distribution": role_dist,
            "main_roles": main_roles,
            "role_games": role_games,
            "recent_games": {
                "total": match_data.get("total_recent", 0),
                "results": match_data.get("recent_results", []),
            },
            "tags": tags,
            "avg_stats": match_data.get("avg_stats"),
            # New fields for advanced features
            "match_ids": match_data.get("match_ids", []),
            "unique_champions": match_data.get("unique_champions", []),
            "games_today": match_data.get("games_today", 0),
            "kda_trend": match_data.get("kda_trend", []),
            "co_players": match_data.get("co_players", {}),
            "data_available": data_available,
        }

    # Fetch all 10 players concurrently
    tasks = [_get_player_data(p) for p in participants]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    blue_team = []
    red_team = []
    for r in results:
        if isinstance(r, Exception):
            logger.warning(f"Failed to fetch player data: {r}")
            continue
        if r["team_id"] == 100:
            blue_team.append(r)
        else:
            red_team.append(r)

    if my_team_id == 100:
        my_team, enemy_team = blue_team, red_team
    else:
        my_team, enemy_team = red_team, blue_team

    my_team_stats = _compute_team_stats(my_team)
    enemy_team_stats = _compute_team_stats(enemy_team)
    matchup_analysis = _compute_matchups(my_team, enemy_team)

    # ── Advanced Features ──────────────────────────────────────
    # Feature 2: Duo detection
    duos_my = _detect_duos(my_team)
    duos_enemy = _detect_duos(enemy_team)

    # Feature 3: Champion pool depth
    for p in my_team + enemy_team:
        p["champion_pool"] = _champion_pool_depth(p)

    # Feature 4: Tilt / Mental state
    for p in my_team + enemy_team:
        p["mental_state"] = _assess_mental_state(p)

    # Feature 5: Rank trajectory
    for p in my_team + enemy_team:
        p["rank_trajectory"] = _rank_trajectory(p)

    # Feature 6: Head-to-head
    head_to_head = _detect_head_to_head(puuid, my_team, enemy_team)

    # Feature 7: Team comp analysis (detailed)
    try:
        from champion_data import ensure_champion_data
        await ensure_champion_data()
    except Exception:
        pass
    my_comp_analysis = _analyze_team_comp_detailed(my_team)
    enemy_comp_analysis = _analyze_team_comp_detailed(enemy_team)

    # Feature 9: Win probability
    win_probability = _compute_win_probability(
        my_team, enemy_team, matchup_analysis,
        my_comp=my_comp_analysis, enemy_comp=enemy_comp_analysis,
        duos_my=duos_my, duos_enemy=duos_enemy,
    )

    # Feature 11: Strategic advice
    strategic_advice = _generate_strategic_advice(
        my_team, enemy_team, matchup_analysis,
        my_comp_analysis, enemy_comp_analysis,
        duos_my, duos_enemy,
    )

    # Strip heavy internal fields before returning
    for p in my_team + enemy_team:
        p.pop("co_players", None)
        p.pop("match_ids", None)
        p.pop("kda_trend", None)

    return {
        "in_game": True,
        "game_mode": active.get("gameMode"),
        "game_type": active.get("gameType"),
        "game_length_seconds": game_length,
        "game_start_time": game_start,
        "map_id": active.get("mapId"),
        "queue_id": active.get("gameQueueConfigId"),
        "my_team": my_team,
        "enemy_team": enemy_team,
        "bans_my_team": bans_blue if my_team_id == 100 else bans_red,
        "bans_enemy_team": bans_red if my_team_id == 100 else bans_blue,
        "my_team_stats": my_team_stats,
        "enemy_team_stats": enemy_team_stats,
        "matchup_analysis": matchup_analysis,
        # New features
        "duos_my_team": duos_my,
        "duos_enemy_team": duos_enemy,
        "head_to_head": head_to_head,
        "my_comp_analysis": my_comp_analysis,
        "enemy_comp_analysis": enemy_comp_analysis,
        "win_probability": win_probability,
        "strategic_advice": strategic_advice,
    }


# ── Champion Mastery V4 ─────────────────────────────────────────

# Champion ID -> name mapping (loaded on first use from Data Dragon)
_champion_id_map: dict[int, str] = {}


async def _ensure_champion_map():
    """Load champion ID to name mapping from Data Dragon if not cached."""
    global _champion_id_map
    if _champion_id_map:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get latest version
            resp = await client.get("https://ddragon.leagueoflegends.com/api/versions.json")
            version = resp.json()[0]
            # Get champion data
            resp = await client.get(f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json")
            data = resp.json()
            for name, info in data["data"].items():
                _champion_id_map[int(info["key"])] = name
    except Exception as e:
        logger.warning(f"Failed to load champion map: {e}")


async def get_champion_mastery(puuid: str, api_key: str, top: int = 10) -> list[dict]:
    """Get top champion mastery for a player."""
    url = f"{CHAMPION_MASTERY_V4}/champion-masteries/by-puuid/{puuid}/top"
    params = {"count": top}
    return await _get(url, api_key, params)


async def get_mastery_data(game_name: str, tag_line: str, api_key: str, top: int = 10) -> list[dict]:
    """Get formatted champion mastery data with champion names."""
    await _ensure_champion_map()
    puuid = await get_puuid(game_name, tag_line, api_key)
    masteries = await get_champion_mastery(puuid, api_key, top)
    return [
        {
            "champion_id": m.get("championId"),
            "champion_name": _champion_id_map.get(m.get("championId", 0), f"Champion {m.get('championId')}"),
            "champion_level": m.get("championLevel", 0),
            "champion_points": m.get("championPoints", 0),
            "last_play_time": m.get("lastPlayTime", 0),
            "chest_granted": m.get("chestGranted", False),
        }
        for m in masteries
    ]


# ── Summoner V4 — Account Level ─────────────────────────────────

async def get_summoner_level(game_name: str, tag_line: str, api_key: str) -> dict:
    """Get account level for a player."""
    puuid = await get_puuid(game_name, tag_line, api_key)
    url = f"{SUMMONER_V4_EUW}/summoners/by-puuid/{puuid}"
    data = await _get(url, api_key)
    return {
        "summoner_level": data.get("summonerLevel", 0),
        "profile_icon_id": data.get("profileIconId", 0),
    }


# ── League V4 — Master Ranking Position ─────────────────────────

async def get_master_position(game_name: str, tag_line: str, api_key: str) -> dict | None:
    """Get the player's position in the Master+ ladder by LP.

    The Riot API exposes the top ~10K Master players via the bulk league
    endpoint. If the player is in that set, exact position is returned.
    Otherwise, we estimate position based on LP distribution.
    """
    puuid = await get_puuid(game_name, tag_line, api_key)

    # Get player's rank info
    entries = await get_ranked_stats(puuid, api_key)
    my_entry = None
    for entry in entries:
        if entry.get("queueType") == "RANKED_SOLO_5x5":
            my_entry = entry
            break

    if my_entry is None:
        return None

    my_tier = my_entry.get("tier", "")
    my_lp = my_entry.get("leaguePoints", 0)

    if my_tier not in ("MASTER", "GRANDMASTER", "CHALLENGER"):
        return {"tier": my_tier, "position": None, "total_master_plus": None,
                "total_master": 0, "total_gm": 0, "total_challenger": 0,
                "message": f"Não estás em Master+ (estás em {my_tier})"}

    # Fetch leagues: bulk endpoints (fast, ~1s total)
    master_data, gm_data, chall_data = await asyncio.gather(
        _get(f"{LEAGUE_V4}/masterleagues/by-queue/RANKED_SOLO_5x5", api_key),
        _get(f"{LEAGUE_V4}/grandmasterleagues/by-queue/RANKED_SOLO_5x5", api_key),
        _get(f"{LEAGUE_V4}/challengerleagues/by-queue/RANKED_SOLO_5x5", api_key),
    )

    master_entries = master_data.get("entries", [])
    gm_entries = gm_data.get("entries", [])
    chall_entries = chall_data.get("entries", [])

    # Try to find exact position by puuid
    all_entries = chall_entries + gm_entries + master_entries
    all_entries.sort(key=lambda e: e.get("leaguePoints", 0), reverse=True)

    position = None
    for i, e in enumerate(all_entries):
        if e.get("puuid") == puuid:
            position = i + 1
            break

    visible_count = len(all_entries)
    min_visible_lp = min((e.get("leaguePoints", 0) for e in master_entries), default=0) if master_entries else 0

    if position is None and my_lp >= min_visible_lp:
        # Player should be in list but puuid match failed — count by LP
        higher = sum(1 for e in all_entries if e.get("leaguePoints", 0) > my_lp)
        position = higher + 1

    if position is None:
        # Player is below the visible threshold (LP < min_visible_lp)
        # The API caps at ~10K Master entries. Estimate hidden Masters using LP density.
        visible_master_lps = sorted([e.get("leaguePoints", 0) for e in master_entries])
        if visible_master_lps:
            # Use density in the lower quartile of visible Masters to estimate below-threshold
            q1_lp = visible_master_lps[len(visible_master_lps) // 4]  # 25th percentile
            min_lp = visible_master_lps[0]
            players_in_q1 = sum(1 for lp in visible_master_lps if lp <= q1_lp)
            lp_range_q1 = max(q1_lp - min_lp, 1)
            density = players_in_q1 / lp_range_q1  # players per LP point

            # Estimate hidden players (LP from 0 to min_visible_lp - 1)
            hidden_total = int(min_visible_lp * density)
            hidden_above = int(max(0, min_visible_lp - my_lp) * density)

            position = visible_count + hidden_above
            estimated_total = visible_count + hidden_total
        else:
            position = visible_count + 1
            estimated_total = visible_count + 1

        return {
            "tier": my_tier,
            "position": position,
            "total_master_plus": estimated_total,
            "total_master": len(master_entries) + (estimated_total - visible_count),
            "total_gm": len(gm_entries),
            "total_challenger": len(chall_entries),
            "approximate": True,
        }

    return {
        "tier": my_tier,
        "position": position,
        "total_master_plus": visible_count,
        "total_master": len(master_entries),
        "total_gm": len(gm_entries),
        "total_challenger": len(chall_entries),
    }


# ── Match V5 — Replay Links ─────────────────────────────────────

async def get_replay_links(game_name: str, tag_line: str, api_key: str, count: int = 5) -> list[dict]:
    """Get replay download links for recent matches."""
    puuid = await get_puuid(game_name, tag_line, api_key)
    url = f"{MATCH_V5}/matches/by-puuid/{puuid}/replays"
    try:
        data = await _get(url, api_key)
        # The response is a list of replay objects
        return data if isinstance(data, list) else []
    except RiotAPIError as e:
        if e.status_code == 404:
            return []
        raise


# ── Personal Matchup Stats ──────────────────────────────────────

async def build_matchup_stats(
    game_name: str, tag_line: str, api_key: str, count: int = 200
) -> dict:
    """
    Fetch recent ranked games and build a personal matchup matrix.
    Returns {champion_played: {vs_champion: {wins, losses, games, winrate}}}.
    Also includes per-champion aggregate stats.
    """
    puuid = await get_puuid(game_name, tag_line, api_key)

    # Fetch match IDs in batches (API max 100 per call)
    all_match_ids: list[str] = []
    for start in range(0, count, 100):
        batch = await get_match_ids(
            puuid, api_key,
            count=min(100, count - start),
            start=start,
            queue=420,  # ranked solo only
        )
        all_match_ids.extend(batch)
        if len(batch) < 100:
            break
        await asyncio.sleep(0.5)  # rate limit breathing room

    logger.info(f"Fetching {len(all_match_ids)} matches for matchup stats")

    matchups: dict[str, dict[str, dict]] = {}
    champ_totals: dict[str, dict] = {}
    weighted_matchups: dict[str, dict[str, dict]] = {}
    weighted_totals: dict[str, dict] = {}
    RECENCY_DECAY = 0.99  # each older jungle game worth 1% less
    jungle_idx = 0

    for mid in all_match_ids:
        try:
            match_data = await get_match_detail(mid, api_key)
            parsed = parse_match(match_data, puuid)
            if not parsed or not parsed.get("role") == "jungle":
                continue  # Only jungle games

            my_champ = parsed["champion_played"]
            vs_champ = parsed.get("champion_against") or "Unknown"
            won = parsed["won"]
            weight = RECENCY_DECAY ** jungle_idx
            jungle_idx += 1

            # Per-matchup stats
            if my_champ not in matchups:
                matchups[my_champ] = {}
            if vs_champ not in matchups[my_champ]:
                matchups[my_champ][vs_champ] = {"wins": 0, "losses": 0, "games": 0}

            matchups[my_champ][vs_champ]["games"] += 1
            if won:
                matchups[my_champ][vs_champ]["wins"] += 1
            else:
                matchups[my_champ][vs_champ]["losses"] += 1

            # Per-champion totals
            if my_champ not in champ_totals:
                champ_totals[my_champ] = {"wins": 0, "losses": 0, "games": 0}
            champ_totals[my_champ]["games"] += 1
            if won:
                champ_totals[my_champ]["wins"] += 1
            else:
                champ_totals[my_champ]["losses"] += 1

            # Recency-weighted stats (recent games count more)
            weighted_matchups.setdefault(my_champ, {}).setdefault(
                vs_champ, {"wins": 0.0, "losses": 0.0, "games": 0.0}
            )
            weighted_matchups[my_champ][vs_champ]["games"] += weight
            if won:
                weighted_matchups[my_champ][vs_champ]["wins"] += weight
            else:
                weighted_matchups[my_champ][vs_champ]["losses"] += weight

            weighted_totals.setdefault(
                my_champ, {"wins": 0.0, "losses": 0.0, "games": 0.0}
            )
            weighted_totals[my_champ]["games"] += weight
            if won:
                weighted_totals[my_champ]["wins"] += weight
            else:
                weighted_totals[my_champ]["losses"] += weight

        except RiotAPIError as e:
            if e.status_code == 429:
                logger.warning("Rate limited during matchup fetch, stopping")
                break
            continue

    # Compute winrates
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


# ── League of Graphs — Real Ranking ─────────────────────────────

_LOG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_log_ranking_cache: dict[str, tuple[float, dict]] = {}
_LOG_CACHE_TTL = 1800  # 30 minutes


async def get_leagueofgraphs_ranking(game_name: str, tag_line: str, region: str = "euw") -> dict | None:
    """Scrape the player's real ranking from League of Graphs.
    Returns {global_rank, euw_rank, top_percent} or None on failure.
    """
    import urllib.parse

    cache_key = f"{game_name}#{tag_line}@{region}"
    if cache_key in _log_ranking_cache:
        ts, data = _log_ranking_cache[cache_key]
        if asyncio.get_event_loop().time() - ts < _LOG_CACHE_TTL:
            return data

    encoded_name = urllib.parse.quote(f"{game_name}-{tag_line}")
    url = f"https://www.leagueofgraphs.com/summoner/{region}/{encoded_name}"

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=_LOG_HEADERS)
            if resp.status_code != 200:
                logger.warning(f"League of Graphs returned {resp.status_code}")
                return None

            html = resp.text

            # Extract: Rank: <span class="highlight">81,587</span>
            global_match = re.search(r'Rank:\s*(?:<[^>]+>)?\s*([\d,]+)', html)
            # Extract: (EUW: 18,710)
            euw_match = re.search(r'\(EUW:\s*([\d,]+)\)', html)
            # Extract: Top 0.73%
            top_match = re.search(r'Top\s+([\d.]+)%', html)

            if not global_match and not euw_match:
                logger.warning("Could not parse ranking from League of Graphs HTML")
                return None

            result = {
                "global_rank": int(global_match.group(1).replace(',', '')) if global_match else None,
                "euw_rank": int(euw_match.group(1).replace(',', '')) if euw_match else None,
                "top_percent": float(top_match.group(1)) if top_match else None,
                "source": "leagueofgraphs",
            }

            _log_ranking_cache[cache_key] = (asyncio.get_event_loop().time(), result)
            return result

    except Exception as e:
        logger.warning(f"Failed to fetch League of Graphs ranking: {e}")
        return None
