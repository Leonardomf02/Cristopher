"""Adapter Vinted (vinted.pt) via lib não-oficial `vinted-scraper`.

A pesquisa NÃO devolve a descrição (vem só no detalhe). Para honrar o caso do
utilizador (descrições enganosas: '17' que é '17e'), o router chama
`fetch_description()` apenas para items NOVOS (dedupe garante 1 fetch por item)."""

import logging
import time

from .base import Listing

logger = logging.getLogger(__name__)

_DOMAIN = "https://www.vinted.pt"
_scraper = None


def _get_scraper():
    global _scraper
    if _scraper is None:
        from vinted_scraper import VintedScraper
        _scraper = VintedScraper(_DOMAIN)
    return _scraper


def _image_url(it) -> str:
    photos = getattr(it, "photos", None) or []
    if photos:
        u = getattr(photos[0], "url", None)
        if u:
            return u
    photo = getattr(it, "photo", None)
    if isinstance(photo, dict):
        return photo.get("url") or ""
    return ""


def search(query: str, *, max_price=None, condition="any", limit=40) -> list[Listing]:
    s = _get_scraper()
    params = {
        "search_text": query,
        "per_page": str(min(limit, 96)),
        "order": "newest_first",
        "currency": "EUR",
    }
    if max_price:
        params["price_to"] = str(int(max_price))
    items = s.search(params)

    out: list[Listing] = []
    for it in items:
        ext = getattr(it, "id", None)
        if ext is None:
            continue
        seller = ""
        user = getattr(it, "user", None)
        if user is not None:
            seller = getattr(user, "login", "") or ""
        # item_box.first_line = modelo classificado pela própria Vinted (ex: "Apple
        # iPhone 15 Plus"). Vem na pesquisa (sem 403) e é ótimo para desambiguar
        # (17 vs 17e). Mais fiável que o título escrito pelo vendedor.
        hint = ""
        box = getattr(it, "item_box", None)
        if isinstance(box, dict):
            hint = (box.get("first_line") or "").strip()
        out.append(Listing(
            source="vinted",
            external_id=str(ext),
            title=getattr(it, "title", "") or "",
            description=(f"[Vinted classifica como: {hint}]" if hint else ""),
            price=getattr(it, "price", None),
            currency=getattr(it, "currency", "EUR") or "EUR",
            condition=getattr(it, "status", "") or "",
            url=getattr(it, "url", "") or "",
            image_url=_image_url(it),
            location="",
            seller=seller,
        ))
    return out


def fetch_description(external_id: str) -> str:
    """Detalhe de um item (best-effort). Devolve "" em falha/403."""
    try:
        s = _get_scraper()
        item = s.item(external_id)
        time.sleep(0.4)  # espaçar pedidos para reduzir risco de 403
        return getattr(item, "description", "") or ""
    except Exception as e:  # noqa: BLE001
        logger.debug("vinted fetch_description %s falhou: %s", external_id, e)
        return ""
