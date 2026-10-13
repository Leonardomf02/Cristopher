"""Adapter Facebook Marketplace (sem login).

A página de pesquisa devolve os anúncios embebidos no HTML server-side
(<script type="application/json">) — id, título, preço, cidade, foto. A
descrição só vem na página do item, por isso o router chama `fetch_description()`
para items novos (é aí que a IA apanha as descrições enganosas).

Fragilidades conhecidas (tudo best-effort):
- Às vezes o FB devolve a página SEM resultados embebidos (anti-bot transiente)
  → retry com pausa; se persistir, devolve [] e o scan segue com as outras fontes.
- Só slugs de cidade que o FB conhece funcionam; slugs inválidos caem numa
  localização default nos EUA → guarda abaixo descarta esse fallback (em PT o
  reverse_geocode vem com state vazio e preço em €).
"""

import json
import logging
import os
import re
import time

import httpx

from .base import Listing

logger = logging.getLogger(__name__)

_BASE = "https://www.facebook.com"
# "lisbon" é o único slug PT confirmado (raio ~100 km: Peniche–Setúbal–Torres Novas)
_CITY = os.getenv("FB_MARKETPLACE_CITY", "lisbon")
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}
_RETRIES = 2          # tentativas extra quando o HTML vem sem resultados embebidos
_RETRY_PAUSE = 2.0


def _get(url: str, params: dict | None = None) -> str:
    with httpx.Client(timeout=30.0, headers=_HEADERS, follow_redirects=True) as client:
        r = client.get(url, params=params)
        r.raise_for_status()
        return r.text


def _listing_nodes(html: str) -> list[dict]:
    """Extrai das <script type="application/json"> todos os objectos de anúncio."""
    nodes: list[dict] = []

    def walk(o):
        if isinstance(o, dict):
            if "marketplace_listing_title" in o:
                nodes.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for blob in re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', html, re.S):
        try:
            walk(json.loads(blob))
        except (json.JSONDecodeError, RecursionError):
            continue
    return nodes


def _price(node: dict) -> tuple:
    p = node.get("listing_price") or {}
    formatted = p.get("formatted_amount", "") or ""
    try:
        amount = float(p.get("amount"))
    except (TypeError, ValueError):
        amount = None
    currency = "EUR" if "€" in formatted else ("USD" if "$" in formatted else "EUR")
    return amount, currency, formatted


def _location(node: dict) -> tuple:
    geo = (node.get("location") or {}).get("reverse_geocode") or {}
    return geo.get("city", "") or "", geo.get("state", "") or ""


def _image(node: dict) -> str:
    photo = node.get("primary_listing_photo") or {}
    return ((photo.get("image") or {}).get("uri", "")) or ""


def search(query: str, *, max_price=None, condition="any", limit=40,
           extra_queries=None) -> list[Listing]:
    """Pesquisa no Marketplace. `extra_queries` são pesquisas alternativas.

    Sem login o Facebook devolve **24 resultados e ponto** — não há paginação e
    não há raio. A única forma de ver mais é perguntar de outra maneira: cada
    query devolve uma janela diferente de 24. Um anúncio que não aparecia em
    "Yamaha MT 07" aparecia em "yamaha mt-07 35kw"."""
    vistos: set[str] = set()
    juntos: list[Listing] = []
    for q in [query, *(extra_queries or [])]:
        if len(juntos) >= limit:
            break
        for lst in _search_uma(q, max_price=max_price, condition=condition, limit=limit):
            if lst.external_id in vistos:
                continue
            vistos.add(lst.external_id)
            juntos.append(lst)
            if len(juntos) >= limit:
                break
    return juntos


def _search_uma(query: str, *, max_price=None, condition="any", limit=40) -> list[Listing]:
    params = {"query": query, "sortBy": "creation_time_descend"}
    if max_price:
        params["maxPrice"] = str(int(max_price))
    # o FB filtra server-side; como a pesquisa não devolve o estado do item,
    # a condição do Listing fica com o que pedimos ao FB (honesto: ele filtrou)
    cond_label = ""
    if condition == "new":
        params["itemCondition"] = "new"
        cond_label = "Novo"
    elif condition == "used":
        params["itemCondition"] = "used_like_new,used_good,used_fair"
        cond_label = "Usado"

    url = f"{_BASE}/marketplace/{_CITY}/search"
    nodes: list[dict] = []
    for attempt in range(1 + _RETRIES):
        if attempt:
            time.sleep(_RETRY_PAUSE)
        nodes = _listing_nodes(_get(url, params))
        if nodes:
            break
    if not nodes:
        logger.warning("facebook: sem resultados embebidos para '%s' (anti-bot transiente?)", query)
        return []

    out: list[Listing] = []
    seen: set[str] = set()
    for node in nodes:
        ext = node.get("id")
        if not ext or str(ext) in seen:
            continue
        if node.get("is_sold") or node.get("is_pending") or node.get("is_live") is False:
            continue
        price, currency, formatted = _price(node)
        city, state = _location(node)
        # slug inválido → FB cai em São Francisco: nos EUA o state vem preenchido
        # e o preço em $; em PT o state é vazio e o preço em €
        if state or "$" in formatted:
            continue
        seen.add(str(ext))
        out.append(Listing(
            source="facebook",
            external_id=str(ext),
            title=node.get("marketplace_listing_title", "") or "",
            description="",
            price=price,
            currency=currency,
            condition=cond_label,
            url=f"{_BASE}/marketplace/item/{ext}/",
            image_url=_image(node),
            location=city,
            seller="",
        ))
        if len(out) >= limit:
            break
    if nodes and not out:
        logger.warning("facebook: %s nós mas 0 aproveitados (fallback de localização EUA?)", len(nodes))
    return out


def fetch_description(external_id: str) -> str:
    """Descrição da página do item (best-effort). Devolve "" em falha."""
    try:
        html = _get(f"{_BASE}/marketplace/item/{external_id}/")
        time.sleep(0.5)  # espaçar pedidos: o FB corta o SSR a bursts
        m = re.search(r'"redacted_description":\{"text":"((?:[^"\\]|\\.)*)"', html)
        return json.loads(f'"{m.group(1)}"').strip() if m else ""
    except Exception as e:  # noqa: BLE001
        logger.debug("facebook fetch_description %s falhou: %s", external_id, e)
        return ""


def esta_vivo(external_id: str) -> bool | None:
    """O anúncio ainda existe? None quando não se consegue saber.

    Faz falta porque a pesquisa do Facebook devolve **24 resultados e não pagina**:
    um anúncio vivo desaparece da vista à segunda semana e era marcado como
    vendido sem o ser. A página do item distingue os casos — um item que existe
    traz sempre o título embebido, um que não existe traz uma página de erro com
    um terço do tamanho."""
    try:
        html = _get(f"{_BASE}/marketplace/item/{external_id}/")
        time.sleep(0.5)             # espaçar pedidos: o FB corta o SSR a bursts
    except Exception as e:  # noqa: BLE001
        logger.debug("facebook esta_vivo %s: %s", external_id, e)
        return None
    if not html:
        return None
    if '"is_sold":true' in html or '"is_pending":true' in html:
        return False
    if '"marketplace_listing_title":"' in html:
        return True
    return False


_OG_IMAGE = re.compile(r'<meta property="og:image" content="([^"]+)"')


def foto_principal(external_id: str) -> str | None:
    """URL da foto do próprio anúncio, ido buscar agora.

    Os URLs de imagem do Facebook são assinados e caducam — o que ficou guardado
    devolve "URL signature expired" passado pouco tempo. E não serve ir buscar
    qualquer imagem da página: ela traz dezenas de outros anúncios (numa delas
    veio uma fotografia de uma piscina). A do anúncio é a do `og:image`."""
    try:
        html = _get(f"{_BASE}/marketplace/item/{external_id}/")
        time.sleep(0.5)
    except Exception as e:  # noqa: BLE001
        logger.debug("facebook foto_principal %s: %s", external_id, e)
        return None
    m = _OG_IMAGE.search(html or "")
    return m.group(1).replace("&amp;", "&") if m else None
