"""Preços de hoje para o que está em carteira.

A carteira vinha só dos extractos: o último era de 2 de Junho e trazia 2 das 12
posições, por isso o valor mostrado era uma mistura de fotografias de meses
diferentes. Isto vai buscar a cotação actual de cada instrumento e converte-a
para a moeda da posição, sem mexer em quantidades nem em preços médios.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ETFs europeus não existem no símbolo "nu": o mesmo fundo está em várias bolsas
# e cada uma cota na sua moeda. A ordem aqui é a que dá a moeda mais útil.
SIMBOLOS: dict[str, list[str]] = {
    "VUAA": ["VUAA.DE", "VUAA.L"],
    "VUSA": ["VUSA.AS", "VUSA.L"],
    "CNDX": ["CNDX.L", "CNDX.DE"],
    "SGLD": ["SGLD.L", "SGLD.DE"],
    "SSLN": ["SSLN.L"],
    "EQQQ": ["EQQQ.DE", "EQQQ.L"],
    "IWDA": ["IWDA.AS", "IWDA.L"],
    "VWCE": ["VWCE.DE"],
}

CRYPTO_COINGECKO = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "ADA": "cardano"}

_CACHE: dict[str, tuple[float, float]] = {}      # chave → (valor, timestamp)
_TTL = 900                                        # 15 min chega para uma carteira


def _cache_get(chave: str) -> Optional[float]:
    v = _CACHE.get(chave)
    return v[0] if v and time.time() - v[1] < _TTL else None


def _cache_set(chave: str, valor: float) -> float:
    _CACHE[chave] = (valor, time.time())
    return valor


def _yahoo(simbolo: str) -> tuple[Optional[float], Optional[str]]:
    from market_data import _fetch_yahoo_chart
    try:
        c = _fetch_yahoo_chart(simbolo, range_="5d", interval="1d")
        if c.get("current"):
            moeda = (c.get("currency") or "").strip()
            # A Yahoo escreve "GBp" quando a cotação vem em pence; em maiúsculas
            # ficava igual a GBP e o preço saía 100x maior.
            if moeda == "GBp":
                moeda = "GBX"
            return float(c["current"]), moeda
    except Exception as ex:
        logger.debug("yahoo %s falhou: %s", simbolo, ex)
    return None, None


def fx(de: str, para: str) -> Optional[float]:
    """Quanto vale 1 unidade de `de` em `para`. GBp são pence, não libras."""
    de, para = (de or "").upper(), (para or "").upper()
    if de == "GBP" and para == "GBX":
        return 100.0
    if de == "GBX" and para == "GBP":
        return 0.01
    if de == para:
        return 1.0
    if de == "GBX":
        base = fx("GBP", para)
        return base / 100 if base else None
    if para == "GBX":
        base = fx(de, "GBP")
        return base * 100 if base else None

    chave = f"fx:{de}:{para}"
    em_cache = _cache_get(chave)
    if em_cache is not None:
        return em_cache
    preco, _ = _yahoo(f"{de}{para}=X")
    if preco:
        return _cache_set(chave, preco)
    inverso, _ = _yahoo(f"{para}{de}=X")
    if inverso:
        return _cache_set(chave, 1 / inverso)
    return None


def _crypto_eur(ticker: str) -> Optional[float]:
    cg = CRYPTO_COINGECKO.get(ticker.upper())
    if not cg:
        return None
    chave = f"cg:{cg}"
    em_cache = _cache_get(chave)
    if em_cache is not None:
        return em_cache
    try:
        r = httpx.get(
            f"https://api.coingecko.com/api/v3/simple/price?ids={cg}&vs_currencies=eur",
            timeout=10,
        )
        if r.status_code == 200:
            valor = r.json().get(cg, {}).get("eur")
            if valor:
                return _cache_set(chave, float(valor))
    except Exception as ex:
        logger.debug("coingecko %s falhou: %s", cg, ex)
    return None


def preco_atual(instrument: str, moeda_posicao: str) -> Optional[tuple[float, str]]:
    """Cotação de agora, já convertida para a moeda em que a posição está guardada.
    Devolve (preço, símbolo usado) ou None se não se conseguir cotar."""
    ticker = (instrument or "").strip().upper()
    if not ticker:
        return None

    if ticker in CRYPTO_COINGECKO:
        eur = _crypto_eur(ticker)
        if eur is None:
            return None
        taxa = fx("EUR", moeda_posicao or "EUR") or 1.0
        return round(eur * taxa, 6), "coingecko"

    candidatos = SIMBOLOS.get(ticker, [])
    if not candidatos:
        try:
            from market_data import _candidate_symbols
            candidatos = _candidate_symbols(ticker, None)
        except Exception:
            candidatos = [ticker]

    for simbolo in candidatos:
        chave = f"px:{simbolo}"
        em_cache = _cache_get(chave)
        moeda = None
        if em_cache is not None:
            preco, moeda = em_cache, _CACHE.get(f"cy:{simbolo}", (None, 0))[0]
        else:
            preco, moeda = _yahoo(simbolo)
            if preco:
                _cache_set(chave, preco)
                _CACHE[f"cy:{simbolo}"] = (moeda, time.time())
        if not preco:
            continue
        taxa = fx(moeda or moeda_posicao or "EUR", moeda_posicao or "EUR")
        if taxa is None:
            continue
        return round(preco * taxa, 6), simbolo
    return None
