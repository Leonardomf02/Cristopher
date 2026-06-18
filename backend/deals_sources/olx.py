"""Adapter OLX Portugal (olx.pt) via API pública `/api/v1/offers/`.

Devolve já a descrição completa, estado (novo/usado), modelo normalizado e
localização — ótimo para a desambiguação. Cobre telemóveis, acessórios e motos."""

import logging

import httpx

from .base import Listing

logger = logging.getLogger(__name__)

_API = "https://www.olx.pt/api/v1/offers/"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def _price_param(offer):
    for p in offer.get("params", []):
        if p.get("key") == "price":
            v = p.get("value") or {}
            return v.get("value"), v.get("currency") or "EUR"
    return None, "EUR"


def _state(offer):
    for p in offer.get("params", []):
        if p.get("key") == "state":
            return (p.get("value") or {}).get("label", "")
    return ""


def _image(offer):
    photos = offer.get("photos") or []
    if not photos:
        return ""
    link = photos[0].get("link") or ""
    return link.replace("{width}", "600").replace("{height}", "600")


def _location(offer):
    loc = offer.get("location") or {}
    city = (loc.get("city") or {}).get("name", "")
    region = (loc.get("region") or {}).get("name", "")
    return ", ".join(x for x in (city, region) if x)


def search(query: str, *, max_price=None, condition="any", limit=40) -> list[Listing]:
    params = {
        "offset": "0",
        "limit": str(min(limit, 50)),
        "query": query,
        "sort_by": "created_at:desc",
    }
    if max_price:
        params["filter_float_price:to"] = str(int(max_price))
    if condition == "new":
        params["filter_enum_state[0]"] = "new"
    elif condition == "used":
        params["filter_enum_state[0]"] = "used"

    with httpx.Client(timeout=30.0, headers={"User-Agent": _UA, "Accept": "application/json"}) as client:
        r = client.get(_API, params=params)
        r.raise_for_status()
        data = r.json().get("data", [])

    out: list[Listing] = []
    for offer in data:
        ext = offer.get("id")
        if ext is None:
            continue
        price, currency = _price_param(offer)
        cond = _state(offer)
        out.append(Listing(
            source="olx",
            external_id=str(ext),
            title=offer.get("title", "") or "",
            description=offer.get("description", "") or "",
            price=price,
            currency=currency,
            condition=cond,
            url=offer.get("url", "") or "",
            image_url=_image(offer),
            location=_location(offer),
            seller=((offer.get("user") or {}).get("name", "") or ""),
        ))
    return out
