"""
OP.GG scraper for automatic LoL match history import.
No API key required — uses op.gg's Next.js server actions.
"""

import httpx
import json
import re
import logging
import urllib.parse
from datetime import datetime, date

logger = logging.getLogger(__name__)

OPGG_BASE = "https://op.gg"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

ROLE_MAP = {
    "TOP": "top",
    "JUNGLE": "jungle",
    "MID": "mid",
    "MIDDLE": "mid",
    "ADC": "adc",
    "BOTTOM": "adc",
    "SUPPORT": "support",
    "UTILITY": "support",
}


class OpggError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def _get_puuid_and_action_id(
    client: httpx.AsyncClient, game_name: str, tag_line: str, region: str
) -> tuple[str, str]:
    """
    Fetch the summoner profile page to extract:
      1. The player's PUUID (from RSC payload)
      2. The getGames server action ID (from JS bundles)
    """
    encoded = urllib.parse.quote(f"{game_name}-{tag_line}")
    url = f"{OPGG_BASE}/lol/summoners/{region}/{encoded}"

    resp = await client.get(url, headers=HEADERS)
    if resp.status_code == 404:
        raise OpggError(f"Jogador '{game_name}#{tag_line}' não encontrado no op.gg ({region})")
    if resp.status_code != 200:
        raise OpggError(f"Erro ao aceder ao op.gg: HTTP {resp.status_code}")

    html = resp.text

    # Extract PUUID from RSC data (may be escaped as \" in script tags)
    puuid_match = re.search(r'puuid\\?":\\?"([A-Za-z0-9_-]{50,})', html)
    if not puuid_match:
        raise OpggError("Não foi possível encontrar o PUUID no op.gg")
    puuid = puuid_match.group(1)

    # Extract getGames action ID from JS bundles
    # The page references JS chunks; the action ID is in one of them.
    action_id = await _find_get_games_action_id(client, html)

    return puuid, action_id


async def _find_get_games_action_id(client: httpx.AsyncClient, html: str) -> str:
    """
    Find the getGames server action ID by downloading the relevant JS chunk.
    Falls back to a known action ID if extraction fails.
    """
    # Find JS chunk URLs from the page
    js_urls = list(set(re.findall(
        r'https://c-lol-web\.op\.gg/app-router/_next/static/chunks/[^"\']+\.js', html
    )))

    for url in js_urls:
        try:
            resp = await client.get(url, headers={"User-Agent": HEADERS["User-Agent"]})
            if resp.status_code != 200:
                continue
            # Look for: createServerReference("HASH",...,"getGames")
            match = re.search(
                r'ServerReference\)\("([0-9a-f]+)"[^"]*"getGames"\)', resp.text
            )
            if match:
                logger.info(f"Found getGames action ID: {match.group(1)}")
                return match.group(1)
        except Exception:
            continue

    # Fallback to last known action ID
    logger.warning("Could not find getGames action ID dynamically, using fallback")
    return "409a2b9ca50d15e50a4dace93552e3a40113dc2753"


async def _call_get_games(
    client: httpx.AsyncClient,
    action_id: str,
    region: str,
    summoner_slug: str,
    puuid: str,
    game_type: str = "TOTAL",
    ended_at: str = "",
) -> list[dict]:
    """Call the getGames Next.js server action and return parsed game list."""
    url = f"{OPGG_BASE}/lol/summoners/{region}/{summoner_slug}"
    body = json.dumps([{
        "locale": "en",
        "region": region,
        "puuid": puuid,
        "gameType": game_type,
        "endedAt": ended_at,
        "champion": "",
    }])

    resp = await client.post(
        url,
        content=body,
        headers={
            "User-Agent": HEADERS["User-Agent"],
            "Next-Action": action_id,
            "Content-Type": "text/plain;charset=UTF-8",
            "Accept": "text/x-component",
        },
    )

    if resp.status_code != 200:
        raise OpggError(f"Erro na server action do op.gg: HTTP {resp.status_code}")

    # Response format: line 0 is metadata, line 1 is "1:{json}"
    lines = resp.text.strip().split("\n")
    for line in lines:
        colon_idx = line.find(":")
        if colon_idx < 0:
            continue
        try:
            payload = json.loads(line[colon_idx + 1:])
            if isinstance(payload, dict) and "data" in payload:
                return payload["data"]
        except (json.JSONDecodeError, ValueError):
            continue

    raise OpggError("Resposta inesperada da server action do op.gg")


def _parse_game(game: dict) -> dict | None:
    """Convert an op.gg game object to our internal format."""
    try:
        game_id = game.get("id", "")
        result = game.get("game_result", "")
        created_at = game.get("created_at", "")
        game_length = game.get("game_length", 0)

        # Champion
        champ = game.get("champion", {})
        champion_played = champ.get("name") if isinstance(champ, dict) else None

        # Position
        position = game.get("position", "")
        role = ROLE_MAP.get(position)

        # Stats
        stats = game.get("stats", {})
        kda = stats.get("kda", {}) if isinstance(stats, dict) else {}
        kills = kda.get("kill", 0) if isinstance(kda, dict) else 0
        deaths = kda.get("death", 0) if isinstance(kda, dict) else 0
        assists = kda.get("assist", 0) if isinstance(kda, dict) else 0

        # Date — convert to local timezone so "today" filter works correctly
        if created_at:
            try:
                game_date = datetime.fromisoformat(created_at).astimezone().date()
            except ValueError:
                game_date = date.today()
        else:
            game_date = date.today()

        return {
            "match_id": game_id,
            "date": game_date,
            "won": result == "WIN",
            "champion_played": champion_played,
            "champion_against": None,
            "role": role,
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "game_duration": game_length,
        }
    except Exception as e:
        logger.warning(f"Failed to parse op.gg game: {e}")
        return None


async def fetch_recent_games(
    game_name: str,
    tag_line: str,
    region: str = "euw",
    count: int = 20,
    existing_match_ids: set[str] | None = None,
) -> list[dict]:
    """
    Fetch recent games from op.gg using their Next.js server action API.
    No API key required.
    """
    if existing_match_ids is None:
        existing_match_ids = set()

    encoded = urllib.parse.quote(f"{game_name}-{tag_line}")

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        puuid, action_id = await _get_puuid_and_action_id(
            client, game_name, tag_line, region
        )
        logger.info(f"PUUID: {puuid}, Action ID: {action_id}")

        raw_games = await _call_get_games(
            client, action_id, region, encoded, puuid
        )

    if not raw_games:
        raise OpggError(
            "Não foram encontrados jogos recentes no op.gg para este jogador."
        )

    games = []
    for g in raw_games:
        parsed = _parse_game(g)
        if parsed and parsed["match_id"] not in existing_match_ids:
            games.append(parsed)

    return games[:count]
