"""
Meta stats module — fetches global champion win/pick/ban rates from
4 sources: LoLalytics, u.gg, op.gg, and League of Graphs.

LoLalytics: Qwik SSR state extracted from HTML (Master, EUW, Jungle).
u.gg: SSR tier list page with native composite scoring (Master, EUW, Jungle).
op.gg: HTML tier list scraping (Master, EUW, Jungle).
League of Graphs: HTML tier list scraping (Master+, EUW, Jungle).

When multiple sources return data, win rates are weighted-averaged by game count.
Sources can be filtered via the API. Cached for 6 hours.
"""

import re
import json
import time
import logging
import asyncio
import httpx

logger = logging.getLogger(__name__)

# All valid source names
ALL_SOURCES = ("lolalytics", "ugg", "opgg", "leagueofgraphs")

# ── Cache ────────────────────────────────────────────────────────
# Per-source raw caches (populated on fetch)
_source_cache: dict[str, dict[str, dict]] = {}  # source_name -> {champ_name -> stats}
_source_cache_ts: float = 0
META_CACHE_TTL = 6 * 3600  # 6 hours

# Merged cache (default = all sources)
_meta_cache: dict[str, dict] | None = None
_meta_cache_ts: float = 0

LOLALYTICS_URL = "https://lolalytics.com/lol/tierlist/?lane=jungle&tier=master&region=euw"

# u.gg tier list page — SSR data contains native tier/rank info
UGG_TIERLIST_URL = "https://u.gg/lol/jungle-tier-list?rank=master&region=euw1"
UGG_MIN_GAMES = 30  # Minimum games threshold for u.gg data reliability

OPGG_URL = "https://op.gg/lol/champions?tier=master&position=jungle&region=euw"
LOG_URL = "https://www.leagueofgraphs.com/champions/tier-list/euw/master/sr-ranked/jungle"

DDRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
DDRAGON_CHAMPIONS_TPL = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def _ref_to_idx(ref_str: str) -> int:
    """Decode LoLalytics Qwik base-36 reference string to array index."""
    result = 0
    for ch in ref_str:
        result = result * 36 + int(ch, 36)
    return result


def _resolve(objs: list, ref_str: str):
    """Resolve a base-36 ref to its actual value in the objs array."""
    idx = _ref_to_idx(ref_str)
    return objs[idx] if idx < len(objs) else None


def _lola_tier_to_standard(lola_tier: int) -> int:
    """Map LoLalytics tier (1-15) to standard tier system (0=S+, 2=S, 4=A, 6=B, 9=C, 12=D)."""
    if lola_tier <= 1:
        return 0   # S+
    if lola_tier <= 3:
        return 2   # S
    if lola_tier <= 5:
        return 4   # A
    if lola_tier <= 8:
        return 6   # B
    if lola_tier <= 10:
        return 9   # C
    return 12      # D


def _parse_ssr_state(html: str) -> dict[str, dict] | None:
    """
    Parse champion stats from the Qwik SSR state embedded in LoLalytics HTML.

    Returns dict mapping DDragon-style champion names (lowercase) to:
        {wr, pr, br, games, rank, tier, delta}
    """
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)

    for script in scripts:
        if len(script) < 5000 or '"objs"' not in script:
            continue

        try:
            data = json.loads(script)
        except (json.JSONDecodeError, ValueError):
            continue

        objs = data.get("objs", [])
        if len(objs) < 900:
            continue

        # Find the config object that contains champId mapping
        # It's typically at a fixed position but we search to be resilient
        champid_map = None
        for obj in objs:
            if isinstance(obj, dict) and "champId" in obj and "champPath" in obj:
                raw = _resolve(objs, obj["champId"])
                if isinstance(raw, dict) and len(raw) > 50:
                    champid_map = raw
                    break

        if not champid_map:
            logger.warning("meta_stats: could not find champId map in SSR state")
            return None

        # Build reverse map: numeric champion ID -> lowercase name
        id_to_name: dict[int, str] = {}
        for name, id_ref in champid_map.items():
            cid = _resolve(objs, id_ref)
            if isinstance(cid, (int, float)):
                id_to_name[int(cid)] = name

        # Extract all champion entries (objects with cid + row + $$nav)
        result: dict[str, dict] = {}
        for obj in objs:
            if not isinstance(obj, dict):
                continue
            if "cid" not in obj or "row" not in obj or "$$nav" not in obj:
                continue

            cid = _resolve(objs, obj["cid"])
            row = _resolve(objs, obj["row"])

            if not isinstance(row, dict) or "wr" not in row:
                continue

            cid_int = int(cid) if isinstance(cid, (int, float)) else None
            name = id_to_name.get(cid_int, f"id_{cid}")

            wr = _resolve(objs, row["wr"])
            pr = _resolve(objs, row.get("pr", "0"))
            br = _resolve(objs, row.get("br", "0"))
            games = _resolve(objs, row.get("games", "0"))
            rank = _resolve(objs, row.get("rank", "0"))
            tier = _resolve(objs, row.get("tier", "0"))
            delta = _resolve(objs, row.get("avgWrDelta", "0"))

            result[name] = {
                "cid": cid_int,
                "wr": float(wr) if wr is not None else 50.0,
                "pr": float(pr) if pr is not None else 0.0,
                "br": float(br) if br is not None else 0.0,
                "games": int(games) if games is not None else 0,
                "rank": int(rank) if rank is not None else 999,
                "tier": _lola_tier_to_standard(int(tier)) if tier is not None else 99,
                "delta": float(delta) if delta is not None else 0.0,
            }

        return result if result else None

    return None


# ── Name Normalization ───────────────────────────────────────────
# LoLalytics uses lowercase names without spaces/punctuation.
# DDragon keys are PascalCase (e.g. "JarvanIV", "LeeSin", "Belveth").
# We store everything lowercase for matching.

_DDRAGON_TO_LOLALYTICS: dict[str, str] = {
    # Most champions: just .lower() works. Exceptions listed here.
    "AurelionSol": "aurelionsol",
    "BelVeth": "belveth",
    "Chogath": "chogath",
    "DrMundo": "drmundo",
    "JarvanIV": "jarvaniv",
    "KSante": "ksante",
    "KaiSa": "kaisa",
    "LeeSin": "leesin",
    "MasterYi": "masteryi",
    "MissFortune": "missfortune",
    "MonkeyKing": "wukong",
    "Nunu": "nunu",
    "RekSai": "reksai",
    "TahmKench": "tahmkench",
    "TwistedFate": "twistedfate",
    "XinZhao": "xinzhao",
}

# Reverse mapping: lowercased name → DDragon key (built at import time + lazily from DDragon)
_LOLALYTICS_TO_DDRAGON: dict[str, str] = {v: k for k, v in _DDRAGON_TO_LOLALYTICS.items()}
# DDragon key cache (populated from CDN on first use)
_ddragon_keys: dict[str, str] = {}  # lowercase → PascalCase DDragon key


async def _ensure_ddragon_keys():
    """Load DDragon champion keys for name normalization."""
    global _ddragon_keys
    if _ddragon_keys:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(DDRAGON_VERSIONS_URL)
            version = resp.json()[0]
            resp = await client.get(DDRAGON_CHAMPIONS_TPL.format(version=version))
            data = resp.json()["data"]
            for key in data:
                _ddragon_keys[key.lower()] = key
    except Exception as e:
        logger.warning(f"Failed to load DDragon keys: {e}")


def _to_ddragon_key(lowercase_name: str) -> str:
    """Convert lowercase meta name to DDragon PascalCase key."""
    # Check explicit mapping first
    if lowercase_name in _LOLALYTICS_TO_DDRAGON:
        return _LOLALYTICS_TO_DDRAGON[lowercase_name]
    # Check DDragon cache
    if lowercase_name in _ddragon_keys:
        return _ddragon_keys[lowercase_name]
    # Fallback: capitalize first letter
    return lowercase_name.capitalize()


def normalize_name(ddragon_key: str) -> str:
    """Convert DDragon champion key to LoLalytics lowercase name."""
    if ddragon_key in _DDRAGON_TO_LOLALYTICS:
        return _DDRAGON_TO_LOLALYTICS[ddragon_key]
    return ddragon_key.lower()


# ── Public API ───────────────────────────────────────────────────

async def fetch_meta_stats(force: bool = False, sources: list[str] | None = None) -> dict[str, dict] | None:
    """
    Fetch EUW Master jungle champion stats from all sources.
    Returns dict mapping lowercase champion name -> {wr, pr, br, games, rank, tier, delta, source}.
    Cached for 6 hours. `sources` filters which sources to merge (default=all).
    """
    global _meta_cache, _meta_cache_ts, _source_cache, _source_cache_ts

    # Re-fetch raw data if stale or forced
    if force or not _source_cache or (time.time() - _source_cache_ts > META_CACHE_TTL):
        logger.info("meta_stats: fetching fresh data from all sources (EUW Master)...")
        await _ensure_ddragon_keys()

        # Fetch all 4 sources concurrently
        lola_result, ugg_result, opgg_result, log_result = await asyncio.gather(
            _fetch_lolalytics(),
            _fetch_ugg(),
            _fetch_opgg(),
            _fetch_leagueofgraphs(),
            return_exceptions=True,
        )

        for name, res in [("LoLalytics", lola_result), ("u.gg", ugg_result),
                          ("op.gg", opgg_result), ("LeagueOfGraphs", log_result)]:
            if isinstance(res, Exception):
                logger.error(f"meta_stats: {name} fetch failed: {res}")

        new_cache: dict[str, dict[str, dict]] = {}
        if not isinstance(lola_result, Exception) and lola_result:
            new_cache["lolalytics"] = lola_result
        if not isinstance(ugg_result, Exception) and ugg_result:
            new_cache["ugg"] = ugg_result
        if not isinstance(opgg_result, Exception) and opgg_result:
            new_cache["opgg"] = opgg_result
        if not isinstance(log_result, Exception) and log_result:
            new_cache["leagueofgraphs"] = log_result

        # Only replace cache if at least one source succeeded
        if new_cache:
            _source_cache = new_cache
            _source_cache_ts = time.time()
            for src, data in _source_cache.items():
                logger.info(f"meta_stats: {src}={len(data)} champs")
        else:
            logger.warning("meta_stats: all sources failed, keeping previous cache")

    if not _source_cache:
        logger.warning("meta_stats: all sources returned nothing")
        return _meta_cache

    # Filter sources
    use_sources = sources if sources else list(_source_cache.keys())
    filtered = {s: _source_cache[s] for s in use_sources if s in _source_cache}

    if not filtered:
        return _meta_cache

    result = _merge_sources_multi(filtered)

    if result:
        # Only update default cache when using all sources
        if not sources:
            _meta_cache = result
            _meta_cache_ts = time.time()
        logger.info(f"meta_stats: merged {len(result)} champions from {list(filtered.keys())}")
        return result

    return _meta_cache


def _assign_tiers_by_wr(data: dict[str, dict]) -> dict[str, dict]:
    """Assign tier and rank to champions based on WR percentile ranking."""
    if not data:
        return data
    # Sort by WR descending, then by pick rate descending as tiebreak
    sorted_names = sorted(data.keys(), key=lambda n: (-data[n].get("wr", 0), -data[n].get("pr", 0)))
    total = len(sorted_names)
    for rank_idx, name in enumerate(sorted_names):
        pct = rank_idx / total  # 0.0 = best, 1.0 = worst
        if pct < 0.05:
            tier = 0   # S+
        elif pct < 0.15:
            tier = 2   # S
        elif pct < 0.30:
            tier = 4   # A
        elif pct < 0.55:
            tier = 6   # B
        elif pct < 0.75:
            tier = 9   # C
        else:
            tier = 12  # D
        data[name]["tier"] = tier
        data[name]["rank"] = rank_idx + 1
    return data


def _assign_ranks_within_tiers(data: dict[str, dict]) -> dict[str, dict]:
    """Assign ranks within each tier, sorted by WR descending. Tiers already set from source averages."""
    if not data:
        return data
    sorted_names = sorted(data.keys(), key=lambda n: (-data[n].get("tier", 99), -data[n].get("wr", 0)))
    # Sort all by tier asc, then WR desc for global rank
    sorted_names = sorted(data.keys(), key=lambda n: (data[n].get("tier", 99), -data[n].get("wr", 0), -data[n].get("pr", 0)))
    for rank_idx, name in enumerate(sorted_names):
        data[name]["rank"] = rank_idx + 1
    return data

async def _fetch_opgg() -> dict[str, dict] | None:
    """
    Fetch from op.gg champion tier list (Next.js flight data).
    Returns dict mapping lowercase slug -> {wr, pr, br, tier, rank, games}.
    """
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(OPGG_URL, headers=_HEADERS)
        if resp.status_code != 200:
            logger.error(f"meta_stats: op.gg HTTP {resp.status_code}")
            return None

    html = resp.text

    # Extract total analyzed samples (e.g. "566,063") for game count estimation
    total_samples = 0
    m = re.search(r'([0-9]{1,3}(?:,[0-9]{3})+)', html)
    if m:
        total_samples = int(m.group(1).replace(",", ""))

    # op.gg embeds champion data in Next.js flight payloads with escaped JSON
    entries = re.findall(
        r'\\"key\\":\\"([^"\\]+)\\"[^}]*?'
        r'\\"positionWinRate\\":([0-9.]+)[^}]*?'
        r'\\"positionPickRate\\":([0-9.]+)[^}]*?'
        r'\\"positionBanRate\\":([0-9.]+)',
        html,
    )
    if not entries:
        logger.warning("meta_stats: op.gg - no champion entries found in HTML")
        return None

    # Extract tier and rank per champion: positionTier + positionRank
    # Note: positionTierData:{...} nested object precedes these fields,
    # so we must explicitly skip over it (the [^}]*? can't cross its closing brace)
    tier_data = re.findall(
        r'\\"key\\":\\"([^"\\]+)\\"[^}]*?'
        r'\\"positionTierData\\":\{[^}]*\},'
        r'\\"positionTier\\":([0-9]+),'
        r'\\"positionRank\\":([0-9]+)',
        html,
    )
    tier_map = {key: (int(tier), int(rank)) for key, tier, rank in tier_data}

    # op.gg tier values: 0=OP, 1=Tier1, 2=Tier2, 3=Tier3, 4=Tier4, 5=Tier5
    # Map to our tier system: 0=S+, 2=S, 4=A, 6=B, 9=C, 12=D
    OPGG_TIER_MAP = {0: 0, 1: 2, 2: 4, 3: 6, 4: 9, 5: 12}

    result: dict[str, dict] = {}
    for key, wr, pr, br in entries:
        name = key
        pr_val = round(float(pr), 2)
        # Estimate games from total samples and pick rate
        estimated_games = round(total_samples * pr_val / 100) if total_samples else 0
        opgg_tier, opgg_rank = tier_map.get(name, (None, None))

        result[name] = {
            "wr": round(float(wr), 2),
            "pr": pr_val,
            "br": round(float(br), 2),
            "games": estimated_games,
        }
        if opgg_tier is not None:
            result[name]["tier"] = OPGG_TIER_MAP.get(opgg_tier, 12)
            result[name]["rank"] = opgg_rank

    # For champions missing native tier data, fall back to WR-based assignment
    missing_tier = {n for n, d in result.items() if "tier" not in d}
    if missing_tier:
        _assign_tiers_by_wr(result)

    logger.info(f"meta_stats: op.gg returned {len(result)} jungle champions (total_samples={total_samples})")
    return result


async def _fetch_leagueofgraphs() -> dict[str, dict] | None:
    """
    Fetch from League of Graphs tier list (Vue.js :items attribute).
    Returns dict mapping lowercase slug -> {wr, pr, br, tier_letter, games}.
    """
    from html import unescape as html_unescape

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(LOG_URL, headers=_HEADERS)
        if resp.status_code != 200:
            logger.error(f"meta_stats: LeagueOfGraphs HTTP {resp.status_code}")
            return None

    html = resp.text
    # LoG embeds data as HTML-escaped JSON in a Vue.js :items attribute
    m = re.search(r":items='(\[.*?\])'", html)
    if not m:
        logger.warning("meta_stats: LeagueOfGraphs - no :items data found")
        return None

    try:
        items = json.loads(html_unescape(m.group(1)))
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"meta_stats: LeagueOfGraphs JSON parse failed: {e}")
        return None

    # Filter for JUNGLE role only
    result: dict[str, dict] = {}
    for item in items:
        role = item.get("role", {}).get("name", "")
        if role != "JUNGLE":
            continue

        # Extract slug from championLink: "/champions/builds/graves/euw/master" -> "graves"
        link = item.get("championLink", "")
        parts = link.split("/builds/")
        if len(parts) < 2:
            continue
        slug = parts[1].split("/")[0]

        pop = item.get("popularity", {})
        wr = round(pop.get("winRate", 0.5) * 100, 2)
        pr = round(pop.get("playedPercentage", 0) * 100, 2)
        br = round(item.get("banRate", 0) * 100, 2)
        tier_letter = item.get("tier", {}).get("tier", "f")

        # Map tier letter to numeric (matching our tier system: 0=S+, 2=S, 4=A, 6=B, 9=C, 12=D)
        tier_map = {"s": 2, "a": 4, "b": 6, "c": 9, "d": 12}
        tier_num = tier_map.get(tier_letter, 12)

        result[slug] = {
            "wr": wr,
            "pr": pr,
            "br": br,
            "games": 0,  # LoG doesn't provide per-champion game counts
            "tier_letter": tier_letter.upper(),
            "tier": tier_num,
        }

    # Assign ranks based on tier order (items come sorted from the website)
    for rank_idx, name in enumerate(result):
        result[name]["rank"] = rank_idx + 1

    logger.info(f"meta_stats: LeagueOfGraphs returned {len(result)} jungle champions")
    return result


def _merge_sources_multi(sources: dict[str, dict[str, dict]]) -> dict[str, dict]:
    """
    Merge data from multiple sources. WR is weighted by game count when available,
    otherwise simple averaged. PR/BR/tier taken from the best source.
    """
    is_single_source = len(sources) == 1

    # Collect all champion names across sources
    all_names: set[str] = set()
    for data in sources.values():
        all_names.update(data.keys())

    result: dict[str, dict] = {}
    lola = sources.get("lolalytics", {})

    for name in all_names:
        wr_weighted_sum = 0.0
        wr_total_games = 0
        wr_simple_sum = 0.0
        wr_simple_count = 0
        total_games = 0
        source_names = []

        for src_name, src_data in sources.items():
            entry = src_data.get(name)
            if not entry:
                continue
            source_names.append(src_name)
            games = entry.get("games", 0)
            wr = entry.get("wr", 50.0)

            if games > 0:
                wr_weighted_sum += wr * games
                wr_total_games += games
                total_games += games
            else:
                wr_simple_sum += wr
                wr_simple_count += 1

        if not source_names:
            continue

        # Compute merged WR: weighted where games exist, simple average otherwise
        if wr_total_games > 0 and wr_simple_count > 0:
            weighted_wr = wr_weighted_sum / wr_total_games
            simple_wr = wr_simple_sum / wr_simple_count
            # Weighted sources get 2/3 weight, simple sources get 1/3
            merged_wr = round((weighted_wr * 2 + simple_wr) / 3, 2)
        elif wr_total_games > 0:
            merged_wr = round(wr_weighted_sum / wr_total_games, 2)
        else:
            merged_wr = round(wr_simple_sum / wr_simple_count, 2)

        # Take metadata from LoLalytics (most detailed), fallback to first available
        l = lola.get(name, {})
        first_source = sources[source_names[0]].get(name, {})

        # When only 1 source, preserve its native tier/rank/pr/br
        if is_single_source:
            result[name] = {
                "cid": first_source.get("cid"),
                "wr": merged_wr,
                "pr": first_source.get("pr", 0.0),
                "br": first_source.get("br", 0.0),
                "games": total_games or 0,
                "rank": first_source.get("rank", 999),
                "tier": first_source.get("tier", 99),
                "delta": first_source.get("delta", 0.0),
                "source": ",".join(source_names),
            }
        else:
            # Average PR and BR across all sources that have data
            pr_sum = 0.0
            br_sum = 0.0
            pr_count = 0
            br_count = 0
            tier_sum = 0.0
            tier_count = 0
            for src_name in source_names:
                entry = sources[src_name].get(name, {})
                if entry.get("pr", 0) > 0:
                    pr_sum += entry["pr"]
                    pr_count += 1
                if entry.get("br", 0) > 0:
                    br_sum += entry["br"]
                    br_count += 1
                src_tier = entry.get("tier")
                if src_tier is not None and src_tier < 99:
                    tier_sum += src_tier
                    tier_count += 1

            # Compute merged tier as average of source tiers → snap to nearest standard
            if tier_count > 0:
                avg_tier = tier_sum / tier_count
                # Snap to nearest standard tier: 0=S+, 2=S, 4=A, 6=B, 9=C, 12=D
                _STANDARD_TIERS = [0, 2, 4, 6, 9, 12]
                merged_tier = min(_STANDARD_TIERS, key=lambda t: abs(t - avg_tier))
            else:
                merged_tier = 99

            result[name] = {
                "cid": l.get("cid") or first_source.get("cid"),
                "wr": merged_wr,
                "pr": round(pr_sum / pr_count, 2) if pr_count else 0.0,
                "br": round(br_sum / br_count, 2) if br_count else 0.0,
                "games": total_games or 0,
                "rank": 999,  # recomputed below
                "tier": merged_tier,
                "delta": l.get("delta", 0.0),
                "source": ",".join(source_names),
            }

    # Assign ranks within each tier (sorted by WR desc) when merging multiple sources
    if not is_single_source:
        _assign_ranks_within_tiers(result)

    return result


async def _fetch_lolalytics() -> dict[str, dict] | None:
    """Fetch from LoLalytics SSR."""
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(LOLALYTICS_URL, headers=_HEADERS)
        if resp.status_code != 200:
            logger.error(f"meta_stats: LoLalytics HTTP {resp.status_code}")
            return None
    return _parse_ssr_state(resp.text)


async def _fetch_ugg() -> dict[str, dict] | None:
    """
    Fetch from u.gg tier list page SSR data.
    Uses the embedded __SSR_DATA__ which contains champion_ranking with
    native tier scoring (stdevs composite) and exact match counts.
    Returns dict mapping lowercase DDragon name -> {wr, pr, br, games, tier, rank}.
    """
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(UGG_TIERLIST_URL, headers=_HEADERS)
        if resp.status_code != 200:
            logger.error(f"meta_stats: u.gg HTTP {resp.status_code}")
            return None

    html = resp.text

    # Extract SSR data embedded in the page
    m = re.search(r'window\.__SSR_DATA__\s*=\s*(\{.*?\})\s*\n', html, re.DOTALL)
    if not m:
        logger.warning("meta_stats: u.gg - no SSR data found in HTML")
        return None

    try:
        ssr = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"meta_stats: u.gg SSR parse failed: {e}")
        return None

    # Find champion_ranking data key
    ranking_key = next((k for k in ssr if "champion_ranking" in k), None)
    if not ranking_key:
        logger.warning("meta_stats: u.gg - no champion_ranking key in SSR")
        return None

    ranking_data = ssr[ranking_key].get("data", {})
    jungle = ranking_data.get("win_rates", {}).get("jungle", [])
    if not jungle:
        logger.warning("meta_stats: u.gg - no jungle data in SSR")
        return None

    # Build champion ID -> DDragon key map from embedded DDragon data
    # SSR DDragon uses numeric IDs as outer keys, 'id' field has the DDragon key
    dd_key = next((k for k in ssr if "/champion.json" in k), None)
    id_to_key: dict[str, str] = {}
    if dd_key:
        dd_data = ssr[dd_key].get("data", {})
        for _cid, info in dd_data.items():
            if isinstance(info, dict) and "key" in info and "id" in info:
                id_to_key[str(info["key"])] = info["id"]

    # Filter by minimum games and sort by stdevs (u.gg composite score)
    filtered = [c for c in jungle if c.get("matches", 0) >= UGG_MIN_GAMES]
    for c in filtered:
        c["_stdevs"] = c.get("tier", {}).get("stdevs", -999)
    filtered.sort(key=lambda x: x["_stdevs"], reverse=True)

    # Map stdevs to our tier system (thresholds from u.gg's frontend JS):
    #   S+ (0): >= 2.0σ | S (2): >= 0.75σ | A (4): >= 0.0σ
    #   B (6): >= -0.5σ | C (9): >= -0.75σ | D (12): < -0.75σ
    def _stdevs_to_tier(s: float) -> int:
        if s >= 2.0:
            return 0   # S+
        if s >= 0.75:
            return 2   # S
        if s >= 0.0:
            return 4   # A
        if s >= -0.5:
            return 6   # B
        if s >= -0.75:
            return 9   # C
        return 12      # D

    result: dict[str, dict] = {}
    for rank_idx, champ in enumerate(filtered):
        cid = str(champ["champion_id"])
        key = id_to_key.get(cid)
        if not key:
            continue
        name = normalize_name(key)
        stdevs = champ["_stdevs"]

        result[name] = {
            "wr": round(champ.get("win_rate", 50.0), 2),
            "pr": round(champ.get("pick_rate", 0.0), 2),
            "br": round(champ.get("ban_rate", 0.0), 2),
            "games": champ.get("matches", 0),
            "tier": _stdevs_to_tier(stdevs),
            "rank": rank_idx + 1,
        }

    logger.info(f"meta_stats: u.gg returned {len(result)} jungle champions (SSR tier list)")
    return result


def get_meta_stats() -> dict[str, dict] | None:
    """Return cached meta stats (sync, no fetch)."""
    return _meta_cache


def get_champion_meta(ddragon_key: str) -> dict | None:
    """Get meta stats for a single champion by DDragon key."""
    if not _meta_cache:
        return None
    name = normalize_name(ddragon_key)
    return _meta_cache.get(name)


def get_average_wr() -> float:
    """Return average win rate across all jungle champions in the meta."""
    if not _meta_cache:
        return 50.0
    wrs = [c["wr"] for c in _meta_cache.values() if c["games"] > 50]
    return sum(wrs) / len(wrs) if wrs else 50.0
