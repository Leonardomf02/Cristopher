"""
Champion data module — loads champion metadata from Data Dragon
and provides team comp analysis + jungle counter picks.
"""

import httpx
import logging
import math
from meta_stats import normalize_name

logger = logging.getLogger(__name__)

DDRAGON_VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"
DDRAGON_CHAMPIONS_TPL = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"

# ── Cache ────────────────────────────────────────────────────────
_champion_cache: dict | None = None  # id(str) -> champion data
_id_to_key: dict[int, str] = {}     # champion numeric id -> key name
_key_to_id_map: dict[str, int] = {} # reverse lookup: key name -> numeric id


async def ensure_champion_data():
    """Load champion data from Data Dragon if not cached."""
    global _champion_cache
    if _champion_cache is not None:
        return

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Auto-detect latest DDragon version
        try:
            ver_resp = await client.get(DDRAGON_VERSIONS)
            versions = ver_resp.json() if ver_resp.status_code == 200 else []
            version = versions[0] if versions else "16.7.1"
        except Exception:
            version = "16.7.1"

        url = DDRAGON_CHAMPIONS_TPL.format(version=version)
        resp = await client.get(url)
        if resp.status_code != 200:
            logger.error(f"Failed to fetch DDragon champions: {resp.status_code}")
            return
        data = resp.json()["data"]
        _champion_cache = data
        # Actualizar em vez de reatribuir: quem faz `from champion_data import
        # _id_to_key` (o router do LoL) ficaria agarrado ao dicionário vazio do
        # arranque, e o champ select nunca reconhecia um único campeão inimigo.
        _id_to_key.clear()
        _id_to_key.update({int(v["key"]): k for k, v in data.items()})
        _key_to_id_map.update({k: int(v["key"]) for k, v in data.items()})
        logger.info(f"Loaded {len(data)} champions from Data Dragon v{version}")


def champion_name(champ_id: int) -> str:
    """Get champion name from numeric ID."""
    key = _id_to_key.get(champ_id)
    if not key or not _champion_cache:
        return f"Champion {champ_id}"
    return _champion_cache[key].get("name", key)


def champion_info(champ_id: int) -> dict | None:
    """Get full champion info from numeric ID."""
    key = _id_to_key.get(champ_id)
    if not key or not _champion_cache:
        return None
    return _champion_cache[key]


def get_damage_type(champ_id: int) -> str:
    """Determine if a champion deals primarily AD, AP, or Mixed damage."""
    info = champion_info(champ_id)
    if not info:
        return "Unknown"
    attack = info.get("info", {}).get("attack", 0)
    magic = info.get("info", {}).get("magic", 0)
    if attack >= magic + 3:
        return "AD"
    if magic >= attack + 3:
        return "AP"
    return "Mixed"


def get_champion_class(champ_id: int) -> list[str]:
    """Get champion tags/classes."""
    info = champion_info(champ_id)
    if not info:
        return []
    return info.get("tags", [])


def has_hard_cc(champ_id: int) -> bool:
    """Heuristic: champions with Tank or Support tags usually have CC."""
    tags = get_champion_class(champ_id)
    return any(t in tags for t in ["Tank", "Support"])


def is_engage(champ_id: int) -> bool:
    """Heuristic: tanks and some fighters have engage."""
    tags = get_champion_class(champ_id)
    name = _id_to_key.get(champ_id, "")
    engage_champs = {
        "Malphite", "Leona", "Nautilus", "Amumu", "Sejuani", "Zac",
        "Ornn", "Maokai", "Alistar", "Rakan", "Rell", "JarvanIV",
        "Hecarim", "Diana", "Kennen", "Wukong", "Gragas", "Vi",
        "Camille", "Nocturne", "Skarner",
    }
    return name in engage_champs or "Tank" in tags


# ── Team Comp Analysis ───────────────────────────────────────────

def analyze_team_comp(champion_ids: list[int]) -> dict:
    """Analyze a team composition given champion IDs."""
    if not champion_ids:
        return {
            "ad_count": 0, "ap_count": 0, "mixed_count": 0,
            "has_engage": False, "has_tank": False, "cc_count": 0,
            "damage_balance": "unknown",
            "warnings": [],
        }

    ad = ap = mixed = 0
    tanks = 0
    cc = 0
    engage = False
    names = []

    for cid in champion_ids:
        if cid == 0:
            continue
        dmg = get_damage_type(cid)
        if dmg == "AD":
            ad += 1
        elif dmg == "AP":
            ap += 1
        else:
            mixed += 1

        tags = get_champion_class(cid)
        if "Tank" in tags:
            tanks += 1
        if has_hard_cc(cid):
            cc += 1
        if is_engage(cid):
            engage = True
        names.append(champion_name(cid))

    total = ad + ap + mixed
    warnings = []

    if total >= 3:
        if ad >= 4:
            warnings.append("⚠️ Full AD — inimigo builda armor e anula tudo")
        elif ap >= 4:
            warnings.append("⚠️ Full AP — Magic Resist vai ser problema")
        if not engage:
            warnings.append("⚠️ Sem engage — difícil forçar fights")
        if tanks == 0:
            warnings.append("⚠️ Sem tank — equipa frágil em teamfights")
        if cc == 0:
            warnings.append("⚠️ Sem CC — sem lock-down para targets")

    if total > 0:
        if ad > ap + 1:
            balance = "heavy_ad"
        elif ap > ad + 1:
            balance = "heavy_ap"
        else:
            balance = "balanced"
    else:
        balance = "unknown"

    return {
        "ad_count": ad,
        "ap_count": ap,
        "mixed_count": mixed,
        "has_engage": engage,
        "has_tank": tanks > 0,
        "cc_count": cc,
        "damage_balance": balance,
        "warnings": warnings,
        "champions": names,
    }


# ── Matchups do histórico dele ───────────────────────────────────
# Aqui houve um `suggest_picks` que percorria só os campeões que ele já tinha
# jogado — era essa a razão de a app recomendar sempre os mesmos. Foi substituído
# por `lol_picks.recomenda`, que parte do meta e desconta o custo de aprender, e
# com ele foram-se o Wilson, o prior bayesiano e os mapas de engage que só ele
# usava. O que fica é o cache dos matchups do histórico, que ainda serve o painel
# de counters pessoais no champ select.

_matchup_cache: dict | None = None


def set_matchup_data(data: dict | None):
    """Guarda os matchups vindos da base (o router constrói-os)."""
    global _matchup_cache
    _matchup_cache = data


def get_matchup_data() -> dict | None:
    return _matchup_cache
