"""Macro regime indicators — fetched live from FRED CSV (no API key needed).

These 5 numbers shift what the LLM assumes about the regime (risk-on vs risk-off):
  - 10Y-2Y yield spread  (recession proxy)
  - VIX level             (equity stress)
  - DXY 20d change        (USD pressure on EM/commodities)
  - Copper/Gold ratio     (cyclical demand vs defensive)
  - 5Y breakeven inflation (real-rate / inflation expectations)

FRED CSV endpoint accepts no auth and returns trivially parseable data.
"""
from __future__ import annotations

import io
import csv
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Optional

import httpx

from market_data import _fetch_yahoo_chart  # reuse for copper/gold
from cache import cached

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 Cristopher-MacroFetcher/1.0"

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"

SERIES = {
    "DGS10":   "10Y Treasury yield",
    "DGS2":    "2Y Treasury yield",
    "VIXCLS":  "CBOE VIX",
    "DTWEXBGS": "USD Broad Index",
    "T5YIE":   "5Y Breakeven Inflation",
}


def _fetch_fred_series(series_id: str, last_n: int = 30) -> list[tuple[str, float]]:
    """Returns [(date, value)] of last N non-null observations, oldest first."""
    url = FRED_CSV.format(series=series_id)
    try:
        r = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=10, follow_redirects=True)
        r.raise_for_status()
        text = r.text
    except Exception as e:
        logger.warning(f"FRED {series_id} failed: {e}")
        return []

    out: list[tuple[str, float]] = []
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    for row in reader:
        if len(row) < 2:
            continue
        date, val = row[0], row[1]
        if val in ("", ".", "NaN", "ND"):
            continue
        try:
            out.append((date, float(val)))
        except ValueError:
            continue
    return out[-last_n:]


def _latest(series: list[tuple[str, float]]) -> Optional[float]:
    return series[-1][1] if series else None


def _pct_change_n_business_days(series: list[tuple[str, float]], n: int) -> Optional[float]:
    """% change between last value and value n observations ago (assumes business-day series)."""
    if len(series) <= n:
        return None
    latest = series[-1][1]
    past = series[-n - 1][1]
    if past == 0:
        return None
    return round((latest / past - 1) * 100, 2)


@cached("macro:snapshot", ttl_seconds=6 * 3600)   # 6h — FRED updates daily
def fetch_macro_snapshot() -> dict:
    """Parallel fetch of all macro inputs. Returns dict with keys & metadata."""
    with ThreadPoolExecutor(max_workers=len(SERIES) + 2) as ex:
        fred_futures = {
            ex.submit(_fetch_fred_series, sid, 30): sid for sid in SERIES.keys()
        }
        # Copper/Gold via Yahoo (HG=F copper futures, GC=F gold futures)
        copper_fut = ex.submit(_fetch_yahoo_chart, "HG=F", "1mo", "1d")
        gold_fut = ex.submit(_fetch_yahoo_chart, "GC=F", "1mo", "1d")

        fred_data: dict[str, list] = {}
        for fut in as_completed(fred_futures):
            sid = fred_futures[fut]
            try:
                fred_data[sid] = fut.result()
            except Exception as e:
                logger.warning(f"FRED {sid}: {e}")
                fred_data[sid] = []

        copper = copper_fut.result() if copper_fut else {}
        gold = gold_fut.result() if gold_fut else {}

    dgs10 = _latest(fred_data.get("DGS10", []))
    dgs2 = _latest(fred_data.get("DGS2", []))
    vix = _latest(fred_data.get("VIXCLS", []))
    dxy = _latest(fred_data.get("DTWEXBGS", []))
    dxy_chg_20d = _pct_change_n_business_days(fred_data.get("DTWEXBGS", []), 20)
    be5y = _latest(fred_data.get("T5YIE", []))

    yc_spread = round(dgs10 - dgs2, 2) if (dgs10 is not None and dgs2 is not None) else None

    cu_close = copper.get("current") if copper else None
    au_close = gold.get("current") if gold else None
    # Raw ratio (copper $/lb ÷ gold $/oz) × 1000 to produce a readable number ~1-5
    cu_au = round((cu_close / au_close) * 1000, 2) if (cu_close and au_close and au_close > 0) else None

    snap = {
        "yield_10y": dgs10,
        "yield_2y": dgs2,
        "yield_curve_10y2y": yc_spread,
        "vix": vix,
        "dxy": dxy,
        "dxy_20d_pct": dxy_chg_20d,
        "breakeven_5y": be5y,
        "copper_gold_ratio": cu_au,
        "as_of": datetime.now().date().isoformat(),
    }
    snap["regime"] = _classify_regime(snap)
    return snap


def _classify_regime(snap: dict) -> str:
    """Heuristic risk-on / risk-off / neutral classifier (transparent to the LLM)."""
    score = 0
    if snap.get("vix") is not None:
        score += -1 if snap["vix"] > 25 else (+1 if snap["vix"] < 16 else 0)
    if snap.get("yield_curve_10y2y") is not None:
        score += -1 if snap["yield_curve_10y2y"] < 0 else 0   # inverted = warning
    if snap.get("dxy_20d_pct") is not None:
        score += -1 if snap["dxy_20d_pct"] > 1.5 else 0       # strong dollar = headwind
    if snap.get("copper_gold_ratio") is not None and snap["copper_gold_ratio"]:
        # Cu/Au ratio ×1000: historically ~1.5-2.5 = neutral, >2.5 cyclical optimism, <1 defensive
        cu_au = snap["copper_gold_ratio"]
        score += +1 if cu_au > 2.5 else (-1 if cu_au < 1.2 else 0)

    if score >= 2:
        return "risk-on"
    if score <= -2:
        return "risk-off"
    return "neutral"


def format_macro_for_prompt(snap: dict) -> str:
    if not snap:
        return "  (macro indisponível)"

    def _fmt(v, suffix=""):
        return f"{v:.2f}{suffix}" if isinstance(v, (int, float)) else "?"

    parts = []
    if snap.get("yield_curve_10y2y") is not None:
        sign = "invertida" if snap["yield_curve_10y2y"] < 0 else "normal"
        parts.append(f"yield curve 10Y-2Y: {_fmt(snap['yield_curve_10y2y'])}pp ({sign})")
    if snap.get("vix") is not None:
        v = snap["vix"]
        tag = "stress" if v > 25 else "calm" if v < 16 else "neutral"
        parts.append(f"VIX: {_fmt(v)} ({tag})")
    if snap.get("dxy_20d_pct") is not None:
        d = snap["dxy_20d_pct"]
        tag = "USD↑ (headwind p/ EM)" if d > 1 else "USD↓ (tailwind)" if d < -1 else "USD estável"
        parts.append(f"DXY 20d: {d:+.2f}% ({tag})")
    if snap.get("breakeven_5y") is not None:
        parts.append(f"breakeven inflation 5Y: {_fmt(snap['breakeven_5y'])}%")
    if snap.get("copper_gold_ratio") is not None:
        parts.append(f"copper/gold: {_fmt(snap['copper_gold_ratio'])}")

    body = "  - " + "\n  - ".join(parts) if parts else "  (sem indicadores)"
    return f"[regime estimado: {snap.get('regime', '?').upper()}]\n{body}"
