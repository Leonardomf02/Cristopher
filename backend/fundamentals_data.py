"""Fundamentals via Financial Modeling Prep (FMP).

Free tier: 250 requests / day. Set FMP_API_KEY in backend/.env to enable.
If the key is missing, every fetch returns {} silently — the rest of the
pipeline keeps working without fundamentals.

Get a key at https://site.financialmodelingprep.com/developer  (3-min signup).
"""
from __future__ import annotations

import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import httpx

from cache import cached

logger = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/api/v3"

# In-memory daily cache: ticker → metrics (avoid burning budget on hot reloads)
_FMP_CACHE: dict[str, dict] = {}


def _api_key() -> Optional[str]:
    key = os.getenv("FMP_API_KEY", "").strip()
    if not key or key.startswith("COLA_"):
        return None
    return key


def is_enabled() -> bool:
    return _api_key() is not None


def _get(path: str, params: dict | None = None) -> list | dict | None:
    key = _api_key()
    if not key:
        return None
    p = dict(params or {})
    p["apikey"] = key
    try:
        r = httpx.get(f"{FMP_BASE}/{path}", params=p, timeout=8)
        if r.status_code == 401:
            logger.warning("FMP 401 — chave inválida")
            return None
        if r.status_code == 429:
            logger.warning("FMP 429 — daily quota exceeded")
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.debug(f"FMP {path} failed: {e}")
        return None


@cached("fundamentals:fmp", ttl_seconds=24 * 3600)   # 24h — fundamentals only update on filings
def fetch_fundamentals(ticker: str) -> dict:
    """Returns key fundamentals for a single stock. {} for crypto/ETF/unknown."""
    t = ticker.strip().upper()
    if t in _FMP_CACHE:
        return _FMP_CACHE[t]

    # 1. Profile (sector, industry, market cap, beta)
    profile = _get(f"profile/{t}")
    profile_row = profile[0] if isinstance(profile, list) and profile else {}

    # 2. Ratios TTM (P/E, P/B, ROE, debt/equity, etc.)
    ratios = _get(f"ratios-ttm/{t}")
    ratios_row = ratios[0] if isinstance(ratios, list) and ratios else {}

    if not profile_row and not ratios_row:
        out: dict = {"ticker": t, "available": False}
    else:
        out = {
            "ticker": t,
            "available": True,
            "name": profile_row.get("companyName"),
            "sector": profile_row.get("sector"),
            "industry": profile_row.get("industry"),
            "country": profile_row.get("country"),
            "market_cap": profile_row.get("mktCap"),
            "beta": profile_row.get("beta"),
            # FMP returns lastDiv as the most recent dividend in $, not yield.
            "last_dividend_usd": profile_row.get("lastDiv"),
            # Real yield: from ratios endpoint when available
            "dividend_yield_pct": (ratios_row.get("dividendYielTTM") or ratios_row.get("dividendYieldTTM")),
            "pe_ttm": ratios_row.get("priceEarningsRatioTTM"),
            "pb_ttm": ratios_row.get("priceToBookRatioTTM"),
            "ev_ebitda": ratios_row.get("enterpriseValueMultipleTTM"),
            "roe_ttm": ratios_row.get("returnOnEquityTTM"),
            "roic_ttm": ratios_row.get("returnOnCapitalEmployedTTM"),
            "debt_equity": ratios_row.get("debtEquityRatioTTM"),
            "current_ratio": ratios_row.get("currentRatioTTM"),
            "gross_margin": ratios_row.get("grossProfitMarginTTM"),
            "net_margin": ratios_row.get("netProfitMarginTTM"),
            "fcf_yield": ratios_row.get("freeCashFlowYieldTTM"),
        }
    _FMP_CACHE[t] = out
    return out


def fetch_fundamentals_batch(tickers: list[str], max_workers: int = 6) -> dict[str, dict]:
    if not is_enabled():
        return {}
    out: dict[str, dict] = {}
    targets = [t for t in (t.upper() for t in tickers if t) if t not in _FMP_CACHE]
    if not targets:
        return {t.upper(): _FMP_CACHE[t.upper()] for t in tickers if t and t.upper() in _FMP_CACHE}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_fundamentals, t): t for t in targets}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                out[t] = fut.result()
            except Exception as e:
                logger.debug(f"FMP {t} failed: {e}")
                out[t] = {"ticker": t, "available": False, "error": str(e)[:80]}
    # Merge cached
    for t in tickers:
        u = t.upper()
        if u in _FMP_CACHE and u not in out:
            out[u] = _FMP_CACHE[u]
    return out


def format_fundamentals_for_prompt(by_ticker: dict[str, dict]) -> str:
    if not by_ticker:
        return "  (fundamentals indisponíveis — chave FMP não configurada)"
    lines = []
    for t, f in by_ticker.items():
        if not f.get("available"):
            continue
        parts = []
        sector = f.get("sector")
        if sector:
            parts.append(sector)
        if f.get("pe_ttm") is not None:
            parts.append(f"P/E {f['pe_ttm']:.1f}")
        if f.get("pb_ttm") is not None:
            parts.append(f"P/B {f['pb_ttm']:.1f}")
        if f.get("ev_ebitda") is not None:
            parts.append(f"EV/EBITDA {f['ev_ebitda']:.1f}")
        if f.get("roe_ttm") is not None:
            parts.append(f"ROE {f['roe_ttm'] * 100:.1f}%")
        if f.get("net_margin") is not None:
            parts.append(f"net margin {f['net_margin'] * 100:.1f}%")
        dy = f.get("dividend_yield_pct")
        if isinstance(dy, (int, float)) and dy > 0:
            # FMP TTM dividend yield is already a fraction (e.g. 0.015 = 1.5%)
            parts.append(f"div yield {dy * 100:.2f}%")
        if f.get("debt_equity") is not None:
            parts.append(f"D/E {f['debt_equity']:.2f}")
        if f.get("beta") is not None:
            parts.append(f"β {f['beta']:.2f}")
        if parts:
            lines.append(f"  - {t}: " + ", ".join(parts))
    return "\n".join(lines) if lines else "  (sem fundamentals para os tickers cobertos)"
