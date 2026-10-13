"""Converter movimentos em moeda estrangeira para euros, à taxa do próprio dia.

As contas do Revolut não são só em euros: há uma em zlótis e outra em libras.
Sem isto, 45 zlótis entravam na app como 45 € — quase o dobro do valor real.

Usa as taxas oficiais do BCE (frankfurter.app, sem chave). Se falhar, cai na
taxa de hoje que a app já usa para a carteira; se nem isso, devolve None e o
movimento não entra — vale mais faltar do que entrar errado.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_CACHE: dict[tuple[str, str], float] = {}


def taxa(moeda: str, dia: date) -> Optional[float]:
    """Quanto vale 1 unidade de `moeda` em euros, na data indicada."""
    moeda = (moeda or "EUR").upper()
    if moeda == "EUR":
        return 1.0
    chave = (moeda, dia.isoformat())
    if chave in _CACHE:
        return _CACHE[chave]
    try:
        r = httpx.get(f"https://api.frankfurter.app/{dia.isoformat()}",
                      params={"from": moeda, "to": "EUR"}, timeout=15)
        if r.status_code == 200:
            valor = float(r.json()["rates"]["EUR"])
            _CACHE[chave] = valor
            return valor
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as ex:
        logger.warning("taxa %s em %s: %s", moeda, dia, ex)
    try:
        from portfolio_prices import fx
        hoje = fx(moeda, "EUR")
        if hoje:
            _CACHE[chave] = hoje
            return hoje
    except Exception:
        pass
    return None


def para_euros(valor: float, moeda: str, dia: date) -> Optional[float]:
    t = taxa(moeda, dia)
    return round(valor * t, 2) if t else None
