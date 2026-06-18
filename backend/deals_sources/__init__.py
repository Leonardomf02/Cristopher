"""Fontes de deals. Cada adapter expõe `search(...) -> list[Listing]` e é
best-effort: se rebentar, o dispatcher apanha e segue para a próxima fonte."""

import logging

from .base import Listing, matches_condition
from . import vinted, olx, ai_web

logger = logging.getLogger(__name__)

# nome → módulo adapter
SOURCES = {
    "vinted": vinted,
    "olx": olx,
    "web": ai_web,
}


def parse_sources(spec: str) -> list[str]:
    """'all' → todas; 'vinted' → só vinted; 'vinted,olx' → csv. Ignora nomes desconhecidos."""
    spec = (spec or "all").strip().lower()
    if spec in ("", "all", "todas", "todos"):
        return list(SOURCES.keys())
    names = [s.strip() for s in spec.split(",") if s.strip()]
    return [n for n in names if n in SOURCES] or list(SOURCES.keys())


def search_all(query: str, sources: str, *, max_price=None, condition="any", limit=40) -> list[Listing]:
    """Pesquisa em todas as fontes pedidas e devolve a lista agregada (best-effort).

    Aplica os filtros duros (condição + preço máximo) de forma uniforme a TODAS as
    fontes — cada adapter ainda pode filtrar no servidor, isto garante consistência."""
    results: list[Listing] = []
    for name in parse_sources(sources):
        adapter = SOURCES[name]
        try:
            found = adapter.search(query, max_price=max_price, condition=condition, limit=limit)
        except Exception as e:  # noqa: BLE001 — uma fonte não pode derrubar o scan
            logger.warning("source %s falhou: %s", name, e)
            continue
        for lst in found:
            if condition in ("new", "used") and not matches_condition(lst.condition, condition):
                continue
            if max_price and lst.price is not None and lst.price > max_price:
                continue
            results.append(lst)
    return results
