"""Reference universe for cross-sectional factor percentiles.

The factor percentiles (momentum, low-vol) used to be computed against the ~40
hand-picked watchlist names — almost all mega-cap tech — so "P80 momentum" was a
rank within a biased sample, not a real factor percentile. This module provides a
broad, liquid reference universe (~120 S&P leaders across sectors) whose momentum
and volatility distributions are cached daily; the percentiles are then computed
against THAT distribution.

Cheap-ish: ~120 Yahoo calls, but cached ~20h so only the first generation of the
day pays it. Falls back gracefully (returns None) so the caller keeps working with
the local-batch percentiles if the universe fetch fails.
"""
from __future__ import annotations

import logging
from typing import Optional

from cache import cached
from market_data import fetch_metrics_batch

logger = logging.getLogger(__name__)

# Liquid S&P leaders spread across sectors + a few broad ETFs. Not exhaustive —
# just a representative, stable cross-section so factor ranks mean something.
FACTOR_UNIVERSE: list[str] = [
    # Mega-cap tech / comms
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "NFLX", "ADBE", "CRM",
    "ORCL", "AMD", "AVGO", "QCOM", "TXN", "INTC", "MU", "AMAT", "LRCX", "KLAC",
    "ASML", "ARM", "MRVL", "NOW", "INTU", "PLTR", "SNOW", "UBER", "SHOP", "IBM",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "SCHW", "AXP", "V",
    "MA", "BRK-B", "SPGI", "CB", "PGR",
    # Healthcare
    "UNH", "LLY", "JNJ", "MRK", "ABBV", "PFE", "TMO", "ABT", "DHR", "AMGN",
    "ISRG", "BMY", "GILD", "VRTX", "REGN",
    # Consumer
    "WMT", "COST", "PG", "KO", "PEP", "MCD", "SBUX", "NKE", "HD", "LOW",
    "TGT", "DIS", "BKNG", "CMG", "MDLZ",
    # Industrials / energy / materials
    "CAT", "DE", "BA", "GE", "HON", "UNP", "RTX", "LMT", "UPS", "MMM",
    "XOM", "CVX", "COP", "SLB", "EOG", "LIN", "FCX", "NEM", "NUE", "DOW",
    # Utilities / REIT / staples-defensives
    "NEE", "DUK", "SO", "AEP", "PLD", "AMT", "EQIX", "O", "CCI", "SPG",
    # Broad / sector ETFs (give the distribution some low-beta anchors)
    "SPY", "QQQ", "VTI", "VT", "DIA", "IWM", "XLK", "XLF", "XLV", "XLE",
    "XLY", "XLI", "XLP", "GLD", "SLV", "SMH", "SOXX", "ARKK", "EFA", "EEM",
]


@cached("factor:universe", ttl_seconds=20 * 3600)   # ~daily — only first generation pays it
def fetch_universe_distributions() -> Optional[dict]:
    """Return {'momentums': [...], 'vols': [...]} for the factor universe.

    Lists of raw factor values (None-filtered) to rank candidates against.
    Returns None if too few names resolve (caller falls back to local batch).
    """
    targets = [(t, "etf" if t in _ETF_SET else "stock") for t in FACTOR_UNIVERSE]
    metrics = fetch_metrics_batch(targets, max_workers=8)
    momentums = [
        m.get("momentum_12_1_pct") for m in metrics.values()
        if m and m.get("momentum_12_1_pct") is not None
    ]
    vols = [
        m.get("realized_vol_252_pct") for m in metrics.values()
        if m and m.get("realized_vol_252_pct") is not None
    ]
    if len(momentums) < 30 or len(vols) < 30:
        logger.warning(f"factor universe too sparse (mom={len(momentums)}, vol={len(vols)}) — fallback to local batch")
        return None
    return {"momentums": momentums, "vols": vols}


_ETF_SET = {
    "SPY", "QQQ", "VTI", "VT", "DIA", "IWM", "XLK", "XLF", "XLV", "XLE",
    "XLY", "XLI", "XLP", "GLD", "SLV", "SMH", "SOXX", "ARKK", "EFA", "EEM",
}
