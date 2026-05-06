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
    global _champion_cache, _id_to_key
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
        _id_to_key = {int(v["key"]): k for k, v in data.items()}
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


# ── Scoring Helpers ──────────────────────────────────────────────


def wilson_lower_bound(wins: float, total: float, z: float = 1.0) -> float:
    """
    Wilson score lower bound — conservative estimate of true win rate.
    Naturally penalizes small sample sizes.
    z=1.0 → ~68% CI, z=1.96 → ~95% CI.
    """
    if total == 0:
        return 0.0
    p = wins / total
    denom = 1 + z * z / total
    center = p + z * z / (2 * total)
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0.0, (center - spread) / denom)


# ── Data-Driven Pick Suggestions ─────────────────────────────────
# Uses the player's actual match history for matchup winrates.
# Wilson score + Bayesian smoothing for statistically sound scoring.

# Bayesian prior strength: total pseudo-games added to regularize small samples.
# The prior center comes from global meta WR when available, else 50%.
PRIOR_STRENGTH = 6  # total pseudo-games (split between wins/losses by meta WR)

_matchup_cache: dict | None = None  # set by router after fetching from Riot API


def set_matchup_data(data: dict):
    """Store matchup data from Riot API."""
    global _matchup_cache
    _matchup_cache = data


def get_matchup_data() -> dict | None:
    return _matchup_cache


def suggest_picks(
    enemy_ids: list[int],
    ally_ids: list[int],
    meta_stats: dict[str, dict] | None = None,
) -> list[dict]:
    """
    Suggest picks based on:
    1. Wilson-score with meta-informed Bayesian prior (global WR as center)
    2. Bayesian matchup adjustments vs visible enemies
    3. Team comp needs with urgency scaling
    4. Meta tier bonus/penalty based on global stats
    5. Recency-weighted stats when available
    """
    ally_comp = analyze_team_comp(ally_ids)
    enemy_names = [_id_to_key.get(cid, "") for cid in enemy_ids if cid != 0]

    needs_ap = ally_comp["damage_balance"] == "heavy_ad"
    needs_ad = ally_comp["damage_balance"] == "heavy_ap"
    needs_engage = not ally_comp["has_engage"]
    needs_tank = not ally_comp["has_tank"]

    if not _matchup_cache:
        return []

    matchups = _matchup_cache.get("matchups", {})
    champ_totals = _matchup_cache.get("champion_totals", {})
    # Use recency-weighted stats for scoring if available
    w_matchups = _matchup_cache.get("weighted_matchups", matchups)
    w_totals = _matchup_cache.get("weighted_totals", champ_totals)

    suggestions = []

    for my_champ, totals in champ_totals.items():
        games = totals["games"]
        wins = totals["wins"]
        raw_wr = totals["winrate"]

        # Recency-weighted stats (fall back to raw if unavailable)
        wt = w_totals.get(my_champ, totals)
        w_games = wt.get("games", games)
        w_wins = wt.get("wins", wins)

        # Meta-informed Bayesian prior: center pseudo-games on global WR
        # If meta says this champ wins 55%, prior adds 3.3 pseudo-wins + 2.7 pseudo-losses
        # instead of flat 3+3. This gives meta-strong champs a boost with few personal games.
        meta = meta_stats.get(normalize_name(my_champ)) if meta_stats else None
        if meta and meta["games"] > 50:
            meta_wr = meta["wr"] / 100.0
            prior_wins = meta_wr * PRIOR_STRENGTH
            prior_losses = (1 - meta_wr) * PRIOR_STRENGTH
        else:
            prior_wins = PRIOR_STRENGTH / 2
            prior_losses = PRIOR_STRENGTH / 2

        # Base score: Wilson lower bound with meta-informed prior
        score = wilson_lower_bound(
            w_wins + prior_wins, w_games + prior_wins + prior_losses, z=1.0
        ) * 100
        reasons = [f"{raw_wr}% WR ({games}g)"]

        my_matchups_raw = matchups.get(my_champ, {})
        my_matchups_w = w_matchups.get(my_champ, my_matchups_raw)

        # Matchup adjustment: Bayesian estimate per visible enemy
        matchup_details = []
        for enemy_name in enemy_names:
            raw_m = my_matchups_raw.get(enemy_name)
            if raw_m and raw_m["games"] >= 1:
                w_m = my_matchups_w.get(enemy_name, raw_m)
                # Laplace-smoothed WR (add 1 pseudo-win + 1 pseudo-loss)
                bayes_wr = (w_m["wins"] + 1) / (w_m["games"] + 2)
                delta = bayes_wr - 0.5
                # Scale weight with confidence: more games = stronger signal
                confidence = min(1.0, raw_m["games"] / 4)
                score += delta * 60 * confidence

                display_wr = raw_m["winrate"]
                display_g = raw_m["games"]
                if display_wr >= 55:
                    matchup_details.append(f"✅ {display_wr}% vs {enemy_name} ({display_g}g)")
                elif display_wr <= 45:
                    matchup_details.append(f"❌ {display_wr}% vs {enemy_name} ({display_g}g)")
                else:
                    matchup_details.append(f"➖ {display_wr}% vs {enemy_name} ({display_g}g)")

        reasons.extend(matchup_details)

        # Meta tier bonus: champions strong in the global meta get a small boost
        meta_wr_display = None
        if meta and meta["games"] > 50:
            meta_wr_display = meta["wr"]
            meta_delta = meta["wr"] - 50.0
            # Scale: +/-5% WR in meta = +/-5 score points (capped at +/-8)
            meta_bonus = max(-8, min(8, meta_delta * 1.0))
            score += meta_bonus
            if meta["tier"] <= 3:
                reasons.append(f"🌍 Meta forte ({meta['wr']}% WR global, tier {meta['tier']})")
            elif meta["tier"] >= 12:
                reasons.append(f"🌍 Meta fraco ({meta['wr']}% WR global, tier {meta['tier']})")

        # Team comp bonus (urgency scales with locked ally picks)
        ally_locked = len([cid for cid in ally_ids if cid != 0])
        urgency = 1.0 + ally_locked * 0.25

        champ_dmg = _get_champ_damage_type(my_champ)
        champ_tags = _get_champ_tags(my_champ)

        if needs_ap and champ_dmg == "AP":
            score += round(12 * urgency)
            reasons.append("Equipa precisa de AP")
        elif needs_ad and champ_dmg == "AD":
            score += round(12 * urgency)
            reasons.append("Equipa precisa de AD")

        if needs_engage and _is_engage_by_name(my_champ):
            score += round(10 * urgency)
            reasons.append("Equipa precisa de engage")

        if needs_tank and "Tank" in champ_tags:
            score += round(7 * urgency)
            reasons.append("Equipa precisa de tank")

        suggestions.append({
            "champion": my_champ,
            "champion_name": my_champ,
            "score": max(0, min(100, round(score))),
            "damage": champ_dmg,
            "winrate": raw_wr,
            "games": games,
            "meta_wr": meta_wr_display,
            "reasons": reasons,
        })

    suggestions.sort(key=lambda s: s["score"], reverse=True)
    return suggestions


def _get_champ_damage_type(name: str) -> str:
    """Get damage type from champion name."""
    cid = _key_to_id(name)
    if cid:
        return get_damage_type(cid)
    # Fallback heuristics for common Data Dragon name mismatches
    ap_champs = {"Diana", "Lillia", "Elise", "Evelynn", "Ekko", "Nidalee",
                 "Karthus", "Amumu", "Sejuani", "Fiddlesticks", "Zac", "Maokai"}
    if name in ap_champs:
        return "AP"
    return "AD"


def _get_champ_tags(name: str) -> list[str]:
    """Get champion tags from name."""
    cid = _key_to_id(name)
    if cid:
        return get_champion_class(cid)
    return []


_ENGAGE_CHAMPS = {
    "Malphite", "Leona", "Nautilus", "Amumu", "Sejuani", "Zac",
    "Ornn", "Maokai", "Alistar", "Rakan", "Rell", "JarvanIV",
    "Hecarim", "Diana", "Wukong", "Gragas", "Vi", "Nocturne", "Skarner",
}


def _is_engage_by_name(name: str) -> bool:
    if name in _ENGAGE_CHAMPS:
        return True
    tags = _get_champ_tags(name)
    return "Tank" in tags


def _key_to_id(key: str) -> int | None:
    """Reverse lookup: champion key to numeric ID."""
    return _key_to_id_map.get(key)
