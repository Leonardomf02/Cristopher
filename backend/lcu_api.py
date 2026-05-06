"""
League Client Update (LCU) API client.
Connects to the local League of Legends client to get champ select data.
"""

import httpx
import os
import logging
import warnings

logger = logging.getLogger(__name__)

# Suppress SSL warnings for LCU self-signed cert
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

LOCKFILE_PATH = "/Applications/League of Legends.app/Contents/LoL/lockfile"


def parse_lockfile() -> dict | None:
    """Parse the lockfile to get port and auth token."""
    if not os.path.exists(LOCKFILE_PATH):
        return None
    try:
        with open(LOCKFILE_PATH, "r") as f:
            content = f.read().strip()
        # Format: LeagueClient:{pid}:{port}:{password}:{protocol}
        parts = content.split(":")
        if len(parts) < 5:
            return None
        return {
            "process": parts[0],
            "pid": int(parts[1]),
            "port": int(parts[2]),
            "password": parts[3],
            "protocol": parts[4],
        }
    except Exception as e:
        logger.error(f"Failed to parse lockfile: {e}")
        return None


async def _lcu_get(endpoint: str) -> dict | list | None:
    """Make a GET request to the LCU API."""
    lock = parse_lockfile()
    if not lock:
        return None

    import base64
    auth = base64.b64encode(f"riot:{lock['password']}".encode()).decode()
    url = f"https://127.0.0.1:{lock['port']}{endpoint}"

    async with httpx.AsyncClient(verify=False, timeout=5.0) as client:
        try:
            resp = await client.get(url, headers={"Authorization": f"Basic {auth}"})
            if resp.status_code == 200:
                return resp.json()
            return None
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return None


async def is_client_running() -> bool:
    """Check if the League Client is running and reachable."""
    result = await _lcu_get("/lol-summoner/v1/current-summoner")
    return result is not None


async def get_champ_select_session() -> dict | None:
    """Get the current champ select session, or None if not in champ select."""
    return await _lcu_get("/lol-champ-select/v1/session")


async def get_current_summoner() -> dict | None:
    """Get the current logged-in summoner."""
    return await _lcu_get("/lol-summoner/v1/current-summoner")


async def get_gameflow_phase() -> str | None:
    """Get the current gameflow phase (None, Lobby, ChampSelect, InProgress, etc.)."""
    result = await _lcu_get("/lol-gameflow/v1/gameflow-phase")
    if isinstance(result, str):
        return result
    return None
