"""Quantitative market data fetcher.

Pulls price history, fundamentals and computes simple technicals
(RSI 14, SMA 50/200, % change 1m/3m/12m) for any ticker.

Sources:
  - Yahoo Finance v8 chart API     (price history, no key needed)
  - Yahoo Finance v10 quoteSummary  (fundamentals)
  - CoinGecko simple price          (fallback for crypto)

Designed to be cheap: parallel fetching + ~5s timeout per request.
Returns None / partial dicts on errors — never raises.
"""
from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) Cristopher/1.0"

# Crypto symbol → CoinGecko id (extends the existing map in routers/investments.py)
CRYPTO_COINGECKO_MAP = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "ADA": "cardano",
    "DOT": "polkadot", "XRP": "ripple", "DOGE": "dogecoin", "AVAX": "avalanche-2",
    "LINK": "chainlink", "MATIC": "matic-network", "LTC": "litecoin", "ATOM": "cosmos",
    "UNI": "uniswap", "BNB": "binancecoin", "TRX": "tron",
}


# Crypto symbols use Yahoo's "BTC-USD" notation; let callers pass either.
def _yf_symbol(ticker: str, asset_type: str | None) -> str:
    t = ticker.strip().upper()
    if asset_type == "crypto" and "-" not in t:
        return f"{t}-USD"
    return t


# UCITS ETFs commonly held in EU brokers — map to LSE/Xetra suffix.
UCITS_SUFFIX_MAP = {
    "VUAA": "L", "VUSA": "L", "CSPX": "L", "CNDX": "L", "VWCE": "DE",
    "EUNL": "DE", "SGLD": "L", "SSLN": "L", "VWRL": "L", "IUSA": "L",
    "EQQQ": "L", "VEUR": "L", "VEVE": "L",
}


def _candidate_symbols(ticker: str, asset_type: str | None) -> list[str]:
    """Yahoo symbols to try in order. Stops at first success."""
    primary = _yf_symbol(ticker, asset_type)
    candidates = [primary]
    bare = ticker.strip().upper()
    if bare in UCITS_SUFFIX_MAP and "." not in bare:
        candidates.append(f"{bare}.{UCITS_SUFFIX_MAP[bare]}")
    return candidates


# ── Technicals ─────────────────────────────────────────────────

def _rsi(closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def _sma(closes: list[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 4)


def _pct_change(closes: list[float], days_ago: int) -> Optional[float]:
    # Need at least days_ago+1 historic points; refuse near-zero base to avoid blow-up.
    if len(closes) < days_ago + 1:
        return None
    latest = closes[-1]
    base = closes[-days_ago - 1]
    if latest is None or base is None or abs(base) < 1e-9:
        return None
    return round((latest / base - 1) * 100, 2)


def _momentum_12_1(closes: list[float]) -> Optional[float]:
    """Return % over t-252 to t-21 (skip last month to avoid short-term reversal)."""
    if len(closes) < 253:
        return None
    skip_recent = closes[-21]
    twelve_mo_ago = closes[-252]
    if twelve_mo_ago == 0:
        return None
    return round((skip_recent / twelve_mo_ago - 1) * 100, 2)


def _realized_vol(closes: list[float], period: int = 252) -> Optional[float]:
    """Annualized realized volatility from daily log returns (%)."""
    import math
    if len(closes) < period + 1:
        period = max(20, len(closes) - 1)
    if period < 20:
        return None
    rets = []
    for i in range(len(closes) - period, len(closes)):
        if closes[i - 1] in (None, 0) or closes[i] is None:
            continue
        rets.append(math.log(closes[i] / closes[i - 1]))
    if len(rets) < 10:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    daily_vol = math.sqrt(var)
    return round(daily_vol * math.sqrt(252) * 100, 2)


def _daily_anomaly(closes: list[float], window: int = 90) -> Optional[dict]:
    """Today's return as z-score vs rolling N-day distribution. |z|>3 = unusual.

    Returns {"return_pct": x, "z_score": z, "anomaly": bool} or None.
    """
    if len(closes) < window + 2:
        return None
    rets = []
    for i in range(len(closes) - window - 1, len(closes) - 1):
        if closes[i - 1] in (None, 0) or closes[i] is None:
            continue
        rets.append(closes[i] / closes[i - 1] - 1)
    if len(rets) < 30:
        return None
    today_ret = closes[-1] / closes[-2] - 1 if closes[-2] not in (None, 0) else None
    if today_ret is None:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    z = (today_ret - mean) / std if std > 1e-9 else 0.0
    return {
        "return_pct": round(today_ret * 100, 2),
        "z_score": round(z, 2),
        "anomaly": abs(z) > 3.0,
    }


def _drawdown_stats(closes: list[float], window: int = 252) -> Optional[dict]:
    """Max DD over `window`, current DD, days since ATH within window."""
    if len(closes) < 30:
        return None
    series = closes[-window:]
    peak = series[0]
    max_dd = 0.0
    days_since_peak = 0
    peak_idx = 0
    for i, c in enumerate(series):
        if c > peak:
            peak = c
            peak_idx = i
        dd = (c - peak) / peak if peak else 0
        if dd < max_dd:
            max_dd = dd
    days_since_peak = len(series) - 1 - peak_idx
    current_peak = max(series)
    current_dd = (series[-1] - current_peak) / current_peak if current_peak else 0
    return {
        "max_dd_pct": round(max_dd * 100, 2),
        "current_dd_pct": round(current_dd * 100, 2),
        "days_since_ath": days_since_peak,
    }


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> Optional[float]:
    """Average True Range — Wilder's smoothing. Used for ATR-based stop losses."""
    if not highs or not lows or not closes:
        return None
    n = min(len(highs), len(lows), len(closes))
    if n < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    # Initial ATR = simple mean of first `period` TRs, then Wilder smoothing
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return round(atr, 4)


def _percentile_rank(value: Optional[float], universe: list[float], lower_is_better: bool = False) -> Optional[int]:
    """Returns 0..100 percentile of `value` within `universe`. None if value missing."""
    if value is None:
        return None
    others = [v for v in universe if v is not None]
    if len(others) < 2:
        return None
    if lower_is_better:
        # Lower value → higher percentile (e.g. low-vol)
        pct = sum(1 for v in others if v >= value) / len(others) * 100
    else:
        pct = sum(1 for v in others if v <= value) / len(others) * 100
    return int(round(pct))


def compute_factor_panel(metrics_by_ticker: dict[str, dict]) -> dict[str, dict]:
    """Add cross-sectional factor percentiles in-place.

    Adds keys:
      - momentum_12_1_pct       (raw)
      - realized_vol_252_pct    (raw)
      - momentum_pctile         (0-100, higher = stronger momentum)
      - lowvol_pctile           (0-100, higher = lower vol = better)
    """
    # Universe lists (exclude None)
    momentums = [m.get("momentum_12_1_pct") for m in metrics_by_ticker.values() if m]
    vols = [m.get("realized_vol_252_pct") for m in metrics_by_ticker.values() if m]

    for t, m in metrics_by_ticker.items():
        if not m:
            continue
        m["momentum_pctile"] = _percentile_rank(m.get("momentum_12_1_pct"), momentums, lower_is_better=False)
        m["lowvol_pctile"] = _percentile_rank(m.get("realized_vol_252_pct"), vols, lower_is_better=True)
    return metrics_by_ticker


# ── Yahoo Finance fetchers ─────────────────────────────────────

# Yahoo's chart endpoint flakes with intermittent 5xx + connection resets; retry transparently.
_YAHOO_RETRY = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, httpx.HTTPStatusError)),
    reraise=True,
)


@_YAHOO_RETRY
def _yahoo_get(url: str, params: dict) -> httpx.Response:
    r = httpx.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=8)
    # Only retry server-side / rate-limit errors. 404 (delisted ticker) shouldn't retry.
    if r.status_code in (429, 500, 502, 503, 504):
        r.raise_for_status()
    return r


def _fetch_yahoo_chart(symbol: str, range_: str = "1y", interval: str = "1d") -> dict:
    """Returns {closes, highs, lows, current, currency, high_52w, low_52w} or {}."""
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
    try:
        r = _yahoo_get(url, {"range": range_, "interval": interval, "includePrePost": "false"})
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        data = r.json()
        chart = (data.get("chart") or {}).get("result") or []
        if not chart:
            return {}
        c = chart[0]
        meta = c.get("meta") or {}
        indicators = (c.get("indicators") or {}).get("quote") or [{}]
        q = indicators[0]

        def _clean(arr):
            return [v for v in (arr or []) if v is not None and not (isinstance(v, float) and math.isnan(v))]

        closes = _clean(q.get("close"))
        highs = _clean(q.get("high"))
        lows = _clean(q.get("low"))
        return {
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "current": meta.get("regularMarketPrice") or (closes[-1] if closes else None),
            "currency": meta.get("currency", "USD"),
            "high_52w": meta.get("fiftyTwoWeekHigh"),
            "low_52w": meta.get("fiftyTwoWeekLow"),
        }
    except Exception as e:
        logger.debug(f"Yahoo chart failed for {symbol}: {e}")
        return {}


def _fetch_yahoo_summary(symbol: str) -> dict:
    """Returns fundamentals: pe, dividendYield, marketCap, beta. {} on error."""
    url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
    try:
        r = httpx.get(
            url,
            params={"modules": "summaryDetail,defaultKeyStatistics,price"},
            headers={"User-Agent": USER_AGENT},
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
        result = ((data.get("quoteSummary") or {}).get("result") or [{}])[0]
        sd = result.get("summaryDetail") or {}
        ks = result.get("defaultKeyStatistics") or {}
        price = result.get("price") or {}

        def _raw(d: dict, key: str):
            v = d.get(key) or {}
            if isinstance(v, dict):
                return v.get("raw")
            return v

        return {
            "pe": _raw(sd, "trailingPE"),
            "forward_pe": _raw(sd, "forwardPE"),
            "dividend_yield": _raw(sd, "dividendYield"),
            "market_cap": _raw(price, "marketCap"),
            "beta": _raw(ks, "beta"),
            "name": price.get("shortName") or price.get("longName"),
        }
    except Exception as e:
        logger.debug(f"Yahoo summary failed for {symbol}: {e}")
        return {}


# ── Public API ─────────────────────────────────────────────────

def fetch_metrics(ticker: str, asset_type: str | None = None) -> dict:
    """All-in-one: chart + summary + technicals for a single ticker."""
    chart: dict = {}
    symbol = _yf_symbol(ticker, asset_type)
    for sym in _candidate_symbols(ticker, asset_type):
        chart = _fetch_yahoo_chart(sym, range_="1y", interval="1d")
        if chart and chart.get("closes"):
            symbol = sym
            break

    if not chart or not chart.get("closes"):
        # Crypto fallback via CoinGecko
        if asset_type == "crypto":
            cg_id = CRYPTO_COINGECKO_MAP.get(ticker.upper())
            if cg_id:
                try:
                    r = httpx.get(
                        f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd&include_24hr_change=true",
                        timeout=8,
                    )
                    if r.status_code == 200:
                        d = r.json().get(cg_id, {})
                        return {
                            "ticker": ticker.upper(),
                            "current_price": d.get("usd"),
                            "currency": "USD",
                            "change_1d_pct": round(d.get("usd_24h_change") or 0, 2),
                            "source": "coingecko",
                        }
                except Exception as e:
                    logger.debug(f"CoinGecko fallback failed for {ticker}: {e}")
        return {"ticker": ticker.upper(), "source": "none"}

    closes = chart["closes"]
    highs = chart.get("highs") or []
    lows = chart.get("lows") or []
    # Yahoo's quoteSummary now requires auth; skip to avoid wasted 401s.
    summary: dict = {}

    return {
        "ticker": ticker.upper(),
        "name": summary.get("name"),
        "current_price": chart.get("current"),
        "currency": chart.get("currency"),
        "high_52w": chart.get("high_52w"),
        "low_52w": chart.get("low_52w"),
        # Technicals
        "rsi_14": _rsi(closes, 14),
        "sma_50": _sma(closes, 50),
        "sma_200": _sma(closes, 200),
        "change_1m_pct": _pct_change(closes, 21),    # ~21 trading days
        "change_3m_pct": _pct_change(closes, 63),
        "change_12m_pct": _pct_change(closes, 252),
        # Factors (raw — percentiles added in compute_factor_panel)
        "momentum_12_1_pct": _momentum_12_1(closes),
        "realized_vol_252_pct": _realized_vol(closes, 252),
        # Risk + drawdown + anomaly
        "atr_14": _atr(highs, lows, closes, 14),
        "drawdown": _drawdown_stats(closes, 252),
        "anomaly": _daily_anomaly(closes, 90),
        # Fundamentals (NaN/None for crypto)
        "pe": summary.get("pe"),
        "forward_pe": summary.get("forward_pe"),
        "dividend_yield": summary.get("dividend_yield"),
        "market_cap": summary.get("market_cap"),
        "beta": summary.get("beta"),
        "source": "yahoo",
    }


def fetch_metrics_batch(tickers_with_type: list[tuple[str, str]], max_workers: int = 8) -> dict[str, dict]:
    """Parallel fetch. Returns {TICKER: metrics_dict}."""
    out: dict[str, dict] = {}
    if not tickers_with_type:
        return out
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(fetch_metrics, t, at): t.upper()
            for t, at in tickers_with_type
        }
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                out[t] = fut.result()
            except Exception as e:
                logger.warning(f"fetch_metrics({t}) failed: {e}")
                out[t] = {"ticker": t, "source": "error"}
    return out


def format_metrics_for_prompt(metrics: dict) -> str:
    """Compact one-line summary for the AI prompt."""
    if not metrics or metrics.get("source") in ("none", "error"):
        return f"  - {metrics.get('ticker', '?')}: dados indisponíveis"

    t = metrics["ticker"]
    cp = metrics.get("current_price")
    cur = metrics.get("currency", "")
    parts = [f"{t}"]
    if cp is not None:
        parts.append(f"{cp:.2f}{cur}")

    # Performance
    perf = []
    if metrics.get("change_1m_pct") is not None:
        perf.append(f"1m {metrics['change_1m_pct']:+.1f}%")
    if metrics.get("change_3m_pct") is not None:
        perf.append(f"3m {metrics['change_3m_pct']:+.1f}%")
    if metrics.get("change_12m_pct") is not None:
        perf.append(f"12m {metrics['change_12m_pct']:+.1f}%")
    if perf:
        parts.append("[" + ", ".join(perf) + "]")

    # Technicals
    tech = []
    if metrics.get("rsi_14") is not None:
        rsi = metrics["rsi_14"]
        marker = " (oversold)" if rsi < 30 else " (overbought)" if rsi > 70 else ""
        tech.append(f"RSI {rsi}{marker}")
    if metrics.get("sma_50") and cp:
        rel = "acima" if cp > metrics["sma_50"] else "abaixo"
        tech.append(f"{rel} SMA50")
    if metrics.get("sma_200") and cp:
        rel = "acima" if cp > metrics["sma_200"] else "abaixo"
        tech.append(f"{rel} SMA200")
    if tech:
        parts.append("⟨" + ", ".join(tech) + "⟩")

    # 52w range position
    hi, lo = metrics.get("high_52w"), metrics.get("low_52w")
    if hi and lo and cp:
        pos = (cp - lo) / (hi - lo) * 100
        parts.append(f"52w: {pos:.0f}% do range")

    # Factor percentiles (cross-sectional within this batch)
    fac = []
    if metrics.get("momentum_pctile") is not None:
        fac.append(f"mom12-1: P{metrics['momentum_pctile']}")
    if metrics.get("lowvol_pctile") is not None:
        fac.append(f"lowvol: P{metrics['lowvol_pctile']}")
    if fac:
        parts.append("〔" + ", ".join(fac) + "〕")

    # Drawdown
    dd = metrics.get("drawdown") or {}
    if dd.get("current_dd_pct") is not None and dd["current_dd_pct"] < -2:
        parts.append(f"DD atual {dd['current_dd_pct']}% (DD máx 252d: {dd.get('max_dd_pct')}%, ATH há {dd.get('days_since_ath')}d)")

    # Anomaly today
    anom = metrics.get("anomaly") or {}
    if anom.get("anomaly"):
        parts.append(f"⚠️ MOVIMENTO ANORMAL hoje: {anom.get('return_pct')}% (z={anom.get('z_score')})")

    # Fundamentals
    fund = []
    if metrics.get("pe") is not None:
        fund.append(f"P/E {metrics['pe']:.1f}")
    if metrics.get("dividend_yield"):
        fund.append(f"div {metrics['dividend_yield'] * 100:.2f}%")
    if metrics.get("beta") is not None:
        fund.append(f"β{metrics['beta']:.2f}")
    if fund:
        parts.append("(" + ", ".join(fund) + ")")

    return "  - " + " ".join(parts)


def get_quick_price(ticker: str, asset_type: str | None = None) -> Optional[float]:
    """Lightweight fetch — current price only. Used for performance tracking."""
    for sym in _candidate_symbols(ticker, asset_type):
        chart = _fetch_yahoo_chart(sym, range_="5d", interval="1d")
        if chart.get("current"):
            return float(chart["current"])

    if asset_type == "crypto":
        cg_id = CRYPTO_COINGECKO_MAP.get(ticker.upper())
        if cg_id:
            try:
                r = httpx.get(
                    f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd",
                    timeout=8,
                )
                if r.status_code == 200:
                    return float(r.json().get(cg_id, {}).get("usd"))
            except Exception:
                pass
    return None
