"""Insights de jungle do patch actual: notas do patch, builds e assets do DDragon.

Três fontes, todas públicas:
  - DDragon: versão do patch + nomes/ícones de itens, runas e feitiços.
  - leagueoflegends.com: notas do patch (Champions / Items / Systems), parseadas
    a partir do HTML — cada bloco traz o contexto do designer e linhas "antigo ⇒ novo".
  - lolalytics: build por campeão (jungle, master_plus) extraída do estado SSR Qwik
    da página de build. Cada página traz DOIS builds: o mais jogado e o de melhor
    winrate.

A tier list de jungle (EUW Master) já vem do `meta_stats`, não se duplica aqui.
"""

import re
import json
import time
import logging
import asyncio
from html import unescape

import httpx

from meta_stats import _browser_get, normalize_name

logger = logging.getLogger(__name__)

DDRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
DDRAGON_DATA_TPL = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/{file}"
DDRAGON_ITEM_IMG = "https://ddragon.leagueoflegends.com/cdn/{version}/img/item/{img}"
DDRAGON_SPELL_IMG = "https://ddragon.leagueoflegends.com/cdn/{version}/img/spell/{img}"
RUNE_IMG = "https://ddragon.leagueoflegends.com/cdn/img/{path}"

PATCH_NOTES_TPL = "https://www.leagueoflegends.com/en-us/news/game-updates/league-of-legends-patch-{p}-notes/"

# O DDragon numera 16.x; o site das notas usa 26.x para o mesmo patch.
_SITE_MAJOR_OFFSET = 10

CACHE_TTL = 6 * 3600
NOTES_CACHE_TTL = 12 * 3600


class _Cache:
    __slots__ = ("ts", "value")

    def __init__(self):
        self.ts = 0.0
        self.value = None

    def get(self, ttl: float):
        if self.value is not None and time.time() - self.ts < ttl:
            return self.value
        return None

    def set(self, value):
        self.value = value
        self.ts = time.time()
        return value


_patch_cache = _Cache()
_assets_cache = _Cache()
_notes_cache: dict[str, _Cache] = {}
_build_cache: dict[str, _Cache] = {}


# ── Patch ────────────────────────────────────────────────────────

async def get_patch() -> dict:
    """Patch actual: versão DDragon (16.14.1), curta (16.14) e a do site (26.14)."""
    cached = _patch_cache.get(CACHE_TTL)
    if cached:
        return cached
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            versions = (await client.get(DDRAGON_VERSIONS_URL)).json()
    except Exception as e:
        logger.warning(f"jungle_meta: DDragon versions falhou: {e}")
        return _patch_cache.value or {"version": None, "short": None, "site": None}

    version = versions[0]
    major, minor = version.split(".")[:2]
    short = f"{major}.{minor}"
    site = f"{int(major) + _SITE_MAJOR_OFFSET}.{minor}"
    prev_short = None
    for v in versions[1:]:
        s = ".".join(v.split(".")[:2])
        if s != short:
            prev_short = s
            break
    return _patch_cache.set({
        "version": version,
        "short": short,
        "site": site,
        "prev_short": prev_short,
    })


# ── Assets do DDragon (nomes + ícones) ───────────────────────────

async def get_assets() -> dict:
    """Mapas id→{name, icon} para itens, feitiços e runas do patch actual."""
    cached = _assets_cache.get(CACHE_TTL)
    if cached:
        return cached

    patch = await get_patch()
    version = patch.get("version")
    if not version:
        return _assets_cache.value or {"items": {}, "spells": {}, "runes": {}}

    async def _json(file: str):
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(DDRAGON_DATA_TPL.format(version=version, file=file))
            return r.json()

    try:
        item_data, summ_data, rune_data = await asyncio.gather(
            _json("item.json"), _json("summoner.json"), _json("runesReforged.json")
        )
    except Exception as e:
        logger.warning(f"jungle_meta: assets DDragon falharam: {e}")
        return _assets_cache.value or {"items": {}, "spells": {}, "runes": {}}

    items = {
        str(iid): {
            "name": info.get("name", ""),
            "icon": DDRAGON_ITEM_IMG.format(version=version, img=info["image"]["full"]),
        }
        for iid, info in item_data.get("data", {}).items()
        if info.get("image", {}).get("full")
    }

    # Os feitiços vêm com key numérica ("4" = Flash, "11" = Smite).
    spells = {
        str(info["key"]): {
            "name": info.get("name", ""),
            "icon": DDRAGON_SPELL_IMG.format(version=version, img=info["image"]["full"]),
        }
        for info in summ_data.get("data", {}).values()
        if info.get("key") and info.get("image", {}).get("full")
    }

    runes: dict[str, dict] = {}
    trees: dict[str, dict] = {}
    for tree in rune_data:
        trees[str(tree["id"])] = {"name": tree.get("name", ""), "icon": RUNE_IMG.format(path=tree.get("icon", ""))}
        runes[str(tree["id"])] = {
            "name": tree.get("name", ""),
            "icon": RUNE_IMG.format(path=tree.get("icon", "")),
            "tree": tree.get("name", ""),
        }
        for slot in tree.get("slots", []):
            for rune in slot.get("runes", []):
                runes[str(rune["id"])] = {
                    "name": rune.get("name", ""),
                    "icon": RUNE_IMG.format(path=rune.get("icon", "")),
                    "tree": tree.get("name", ""),
                    "desc": re.sub(r"<[^>]+>", "", rune.get("shortDesc", "")),
                }

    # Os shards (5001…5011) não vêm no runesReforged; são nomeados à mão.
    runes.update({
        "5001": {"name": "Vida", "tree": "Shards"},
        "5002": {"name": "Armadura", "tree": "Shards"},
        "5003": {"name": "Resist. Mágica", "tree": "Shards"},
        "5005": {"name": "Vel. de Ataque", "tree": "Shards"},
        "5007": {"name": "Ability Haste", "tree": "Shards"},
        "5008": {"name": "Força Adaptável", "tree": "Shards"},
        "5010": {"name": "Vel. Movimento", "tree": "Shards"},
        "5011": {"name": "Vida (escala)", "tree": "Shards"},
        "5013": {"name": "Tenacidade", "tree": "Shards"},
    })

    # A ordem das árvores no ficheiro é a mesma que o lolalytics usa em runes.page.
    tree_order = [str(t["id"]) for t in rune_data]
    return _assets_cache.set({
        "items": items,
        "spells": spells,
        "runes": runes,
        "trees": trees,
        "tree_order": tree_order,
    })


# ── Notas do patch ───────────────────────────────────────────────

_TAGS = re.compile(r"<[^>]+>")


def _text(html: str) -> str:
    return unescape(_TAGS.sub("", html)).replace(" ", " ").strip()


def _parse_changes(block_html: str) -> list[dict]:
    """Extrai as linhas de alteração de um bloco: agrupadas por habilidade/secção."""
    groups: list[dict] = []
    # Cada <h4 class="change-detail-title"> abre uma sub-secção; o que vem antes do
    # primeiro h4 (raro) fica numa secção sem título.
    parts = re.split(r'<h4[^>]*class="[^"]*change-detail-title[^"]*"[^>]*>(.*?)</h4>', block_html, flags=re.DOTALL)
    chunks = [("", parts[0])] + [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
    for title_html, body in chunks:
        lines = []
        for li in re.findall(r"<li>(.*?)</li>", body, re.DOTALL):
            txt = _text(li)
            if not txt:
                continue
            # "Damage: 60 / 75 ⇒ 60 / 80" → separa antes/depois
            if "⇒" in txt:
                label, _, rest = txt.partition(":")
                before, _, after = rest.partition("⇒")
                lines.append({
                    "label": label.strip() if rest else "",
                    "before": before.strip(),
                    "after": after.strip(),
                    "text": txt,
                })
            else:
                lines.append({"label": "", "before": "", "after": "", "text": txt})
        if lines:
            groups.append({"title": _text(title_html), "changes": lines})
    return groups


async def fetch_patch_notes(patch_site: str) -> dict | None:
    """Notas do patch estruturadas por secção. `patch_site` no formato '26.14'."""
    cache = _notes_cache.setdefault(patch_site, _Cache())
    cached = cache.get(NOTES_CACHE_TTL)
    if cached:
        return cached

    url = PATCH_NOTES_TPL.format(p=patch_site.replace(".", "-"))
    resp = await _browser_get(url, timeout=25.0)
    if resp is None or resp.status_code != 200:
        logger.warning(f"jungle_meta: patch notes {patch_site} HTTP {resp.status_code if resp else 'erro'}")
        return None

    html = resp.text
    body = html[html.find("patch-notes-container"):] or html

    # Divide o corpo pelas secções <h2 id="patch-...">
    sections: dict[str, str] = {}
    h2s = list(re.finditer(r'<h2[^>]*id="(patch-[^"]+)"[^>]*>(.*?)</h2>', body, re.DOTALL))
    for i, m in enumerate(h2s):
        end = h2s[i + 1].start() if i + 1 < len(h2s) else len(body)
        sections[_text(m.group(2)).lower()] = body[m.end():end]

    def _blocks(section_html: str, heading: str) -> list[dict]:
        """Blocos de alteração de uma secção. `heading` = h3 (campeões/itens) ou h4 (sistemas)."""
        out = []
        pat = (r'<h3[^>]*class="[^"]*change-title[^"]*"[^>]*>(.*?)</h3>' if heading == "h3"
               else r'<h4[^>]*class="[^"]*change-detail-title[^"]*"[^>]*>(.*?)</h4>')
        matches = list(re.finditer(pat, section_html, re.DOTALL))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(section_html)
            chunk = section_html[m.end():end]
            name = _text(m.group(1))
            if not name:
                continue
            ctx = re.search(r'<blockquote[^>]*class="[^"]*context[^"]*"[^>]*>(.*?)</blockquote>', chunk, re.DOTALL)
            groups = _parse_changes(chunk)
            # Nos sistemas o próprio h4 é o título, por isso as linhas ficam sem grupo.
            if heading == "h4" and not groups:
                lines = [{"label": "", "before": "", "after": "", "text": _text(li)}
                         for li in re.findall(r"<li>(.*?)</li>", chunk, re.DOTALL)]
                if lines:
                    groups = [{"title": "", "changes": lines}]
            if not groups and not ctx:
                continue
            out.append({
                "name": name,
                "context": _text(ctx.group(1)) if ctx else "",
                "groups": groups,
            })
        return out

    result = {
        "patch": patch_site,
        "url": url,
        "champions": _blocks(sections.get("champions", ""), "h3"),
        "items": _blocks(sections.get("items", ""), "h3"),
        "systems": _blocks(sections.get("systems", ""), "h4"),
    }
    logger.info(
        f"jungle_meta: patch {patch_site} → {len(result['champions'])} campeões, "
        f"{len(result['items'])} itens, {len(result['systems'])} sistemas"
    )
    return cache.set(result)


async def get_patch_notes() -> dict | None:
    """Notas do patch actual; se ainda não estiverem publicadas, cai no anterior."""
    patch = await get_patch()
    for key in ("site", "prev_site"):
        if key == "prev_site":
            prev = patch.get("prev_short")
            if not prev:
                break
            major, minor = prev.split(".")
            candidate = f"{int(major) + _SITE_MAJOR_OFFSET}.{minor}"
        else:
            candidate = patch.get("site")
        if not candidate:
            continue
        notes = await fetch_patch_notes(candidate)
        if notes:
            notes["is_current"] = key == "site"
            return notes
    return None


# ── Builds (lolalytics, jungle, master+) ─────────────────────────

LOLALYTICS_BUILD_TPL = "https://lolalytics.com/lol/{slug}/build/?lane=jungle&tier=master_plus"
_BUILD_KEYS = {"items", "runes", "skillorder", "skillpriority", "sums"}


def _qwik_objs(html: str) -> list | None:
    """Array `objs` do estado SSR Qwik embutido na página."""
    for script in re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL):
        if len(script) < 5000 or '"objs"' not in script:
            continue
        try:
            objs = json.loads(script).get("objs")
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(objs, list) and objs:
            return objs
    return None


def _resolver(objs: list):
    """Resolve as referências base-36 do Qwik recursivamente."""
    def deep(value, depth: int = 0):
        if depth > 9:
            return None
        if isinstance(value, str):
            try:
                idx = 0
                for ch in value:
                    idx = idx * 36 + int(ch, 36)
            except ValueError:
                return value
            if 0 <= idx < len(objs):
                return deep(objs[idx], depth + 1)
            return value
        if isinstance(value, dict):
            return {k: deep(v, depth + 1) for k, v in value.items()}
        if isinstance(value, list):
            return [deep(v, depth + 1) for v in value]
        return value
    return deep


def _skill_order(encoded) -> list[str]:
    """312114131343322 → ['W','Q','E','Q','Q','R',…] (1=Q, 2=W, 3=E, 4=R)."""
    letters = {"1": "Q", "2": "W", "3": "E", "4": "R"}
    return [letters[c] for c in str(encoded or "") if c in letters]


def _shape_build(raw: dict, label: str) -> dict:
    items = raw.get("items") or {}
    start = items.get("start") or {}
    core = items.get("core") or {}
    runes = raw.get("runes") or {}
    rune_set = runes.get("set") or {}
    sums = raw.get("sums") or {}
    prio = raw.get("skillpriority") or {}
    order = raw.get("skillorder") or {}

    def _opts(key):
        return [
            {"id": o.get("id"), "games": o.get("n"), "winrate": o.get("wr")}
            for o in (items.get(key) or []) if isinstance(o, dict) and o.get("id")
        ][:4]

    return {
        "label": label,
        "starting_items": {"ids": start.get("set") or [], "winrate": start.get("wr"), "games": start.get("n")},
        "core_items": {"ids": core.get("set") or [], "winrate": core.get("wr"), "games": core.get("n")},
        "item4": _opts("item4"),
        "item5": _opts("item5"),
        "item6": _opts("item6"),
        "runes": {
            "primary_tree": (runes.get("page") or {}).get("pri"),
            "secondary_tree": (runes.get("page") or {}).get("sec"),
            "primary": rune_set.get("pri") or [],
            "secondary": rune_set.get("sec") or [],
            "shards": rune_set.get("mod") or [],
            "winrate": runes.get("wr"),
            "games": runes.get("n"),
        },
        "summoners": {"ids": sums.get("ids") or [], "winrate": sums.get("wr"), "games": sums.get("n")},
        "skill_priority": {"order": prio.get("id"), "winrate": prio.get("wr"), "games": prio.get("n")},
        "skill_order": {"sequence": _skill_order(order.get("id")), "winrate": order.get("wr"), "games": order.get("n")},
    }


async def fetch_build(champion: str) -> dict | None:
    """Build de jungle (Master+) de um campeão: a mais jogada e a de melhor winrate.

    `champion` aceita chave DDragon ou nome do lolalytics (MonkeyKing → wukong)."""
    slug = normalize_name(champion) if champion[:1].isupper() else champion.lower()
    cache = _build_cache.setdefault(slug, _Cache())
    cached = cache.get(CACHE_TTL)
    if cached:
        return cached

    resp = await _browser_get(LOLALYTICS_BUILD_TPL.format(slug=slug), timeout=25.0)
    if resp is None or resp.status_code != 200:
        logger.warning(f"jungle_meta: build {slug} HTTP {resp.status_code if resp else 'erro'}")
        return None

    objs = _qwik_objs(resp.text)
    if not objs:
        logger.warning(f"jungle_meta: build {slug} sem estado SSR")
        return None

    deep = _resolver(objs)
    raws = []
    for obj in objs:
        if isinstance(obj, dict) and _BUILD_KEYS <= set(obj.keys()):
            try:
                raws.append(deep(obj))
            except Exception:
                continue
    if not raws:
        logger.warning(f"jungle_meta: build {slug} sem blocos de build")
        return None

    # A página traz dois builds; o de maior amostra é o mais jogado, o outro é o
    # optimizado por winrate (às vezes a ordem vem trocada, por isso ordena-se).
    def _n(b):
        return ((b.get("items") or {}).get("core") or {}).get("n") or 0

    raws.sort(key=_n, reverse=True)
    builds = [_shape_build(raws[0], "Mais jogada")]
    if len(raws) > 1:
        builds.append(_shape_build(raws[1], "Melhor winrate"))

    return cache.set({
        "champion": slug,
        "source": "lolalytics · jungle · Master+",
        "url": LOLALYTICS_BUILD_TPL.format(slug=slug),
        "builds": builds,
    })
