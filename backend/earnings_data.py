"""Earnings calendar via Finnhub.

Free tier: 60 calls/min, unlimited daily. Set FINNHUB_API_KEY in backend/.env.
Get a key at https://finnhub.io  (signup free, key visible in dashboard).

Surfaces upcoming earnings (next 30 days) for any ticker we care about.
Earnings are high-impact catalysts — knowing one is days away changes the
buy/hold/reduce calculus dramatically.
"""
from __future__ import annotations

import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Optional

import httpx

from cache import cached

logger = logging.getLogger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"

_EARNINGS_CACHE: dict[str, dict] = {}


def _api_key() -> Optional[str]:
    key = os.getenv("FINNHUB_API_KEY", "").strip()
    if not key or key.startswith("COLA_"):
        return None
    return key


def is_enabled() -> bool:
    return _api_key() is not None


@cached("earnings:calendar", ttl_seconds=4 * 3600)   # 4h — refresh during the trading day
def fetch_earnings_calendar(days_ahead: int = 30) -> list[dict]:
    """Returns all earnings between today and today+N days.
    Format per row: {date, symbol, eps_estimate, revenue_estimate, hour}.
    """
    key = _api_key()
    if not key:
        return []

    today = datetime.now().date()
    until = today + timedelta(days=days_ahead)
    try:
        r = httpx.get(
            f"{FINNHUB_BASE}/calendar/earnings",
            params={"from": today.isoformat(), "to": until.isoformat(), "token": key},
            timeout=10,
        )
        r.raise_for_status()
        rows = r.json().get("earningsCalendar", []) or []
        return [
            {
                "date": row.get("date"),
                "symbol": row.get("symbol"),
                "eps_estimate": row.get("epsEstimate"),
                "revenue_estimate": row.get("revenueEstimate"),
                "hour": row.get("hour"),
            }
            for row in rows
        ]
    except Exception as e:
        logger.warning(f"Finnhub earnings calendar failed: {e}")
        return []


def fetch_earnings_for_tickers(tickers: list[str], days_ahead: int = 30) -> dict[str, dict | None]:
    """Returns {TICKER: next earnings dict | None}."""
    if not is_enabled():
        return {}
    cal = fetch_earnings_calendar(days_ahead)
    by_symbol: dict[str, dict] = {}
    for row in cal:
        s = (row.get("symbol") or "").upper()
        if not s:
            continue
        # Keep the closest one per ticker
        if s not in by_symbol or row["date"] < by_symbol[s]["date"]:
            by_symbol[s] = row

    out: dict[str, dict | None] = {}
    today = datetime.now().date()
    for t in {(x or "").upper() for x in tickers}:
        if not t:
            continue
        row = by_symbol.get(t)
        if row:
            try:
                d = datetime.fromisoformat(row["date"]).date()
                row = dict(row)
                row["days_until"] = (d - today).days
            except (ValueError, TypeError):
                row["days_until"] = None
            out[t] = row
        else:
            out[t] = None
    return out


@cached("earnings:history", ttl_seconds=12 * 3600)   # 12h
def fetch_earnings_history(ticker: str, limit: int = 8) -> list[dict]:
    """Past earnings (last N quarters): actual vs estimate per quarter.

    Used for PEAD signal — Bernard-Thomas 1989: stocks with consecutive positive
    surprises drift up for 60d post-announcement.
    """
    key = _api_key()
    if not key:
        return []
    try:
        r = httpx.get(
            f"{FINNHUB_BASE}/stock/earnings",
            params={"symbol": ticker.upper(), "limit": limit, "token": key},
            timeout=10,
        )
        r.raise_for_status()
        rows = r.json() or []
        return [
            {
                "period": row.get("period"),
                "actual": row.get("actual"),
                "estimate": row.get("estimate"),
                "surprise": row.get("surprise"),
                "surprise_pct": row.get("surprisePercent"),
            }
            for row in rows
            if isinstance(row, dict)
        ]
    except Exception as e:
        logger.debug(f"Finnhub earnings history {ticker} failed: {e}")
        return []


def fetch_earnings_momentum(tickers: list[str]) -> dict[str, dict]:
    """For each ticker compute PEAD-style earnings momentum signal.

    Output per ticker:
      - history: last 8 quarters
      - consecutive_beats: how many quarters in a row beat estimate (positive surprise_pct)
      - avg_surprise_pct_4q: average over last 4 quarters
      - signal: 'strong_momentum' | 'neutral' | 'declining' | 'no_data'
    """
    if not is_enabled():
        return {}
    out: dict[str, dict] = {}
    for t in {(x or "").upper() for x in tickers if x}:
        history = fetch_earnings_history(t, limit=8)
        if not history:
            out[t] = {"signal": "no_data"}
            continue
        # newest first in Finnhub response — sort descending by period defensively
        try:
            history = sorted(history, key=lambda r: r.get("period") or "", reverse=True)
        except (TypeError, ValueError):
            pass

        consecutive = 0
        for row in history:
            sp = row.get("surprise_pct")
            if isinstance(sp, (int, float)) and sp > 0:
                consecutive += 1
            else:
                break

        last4 = [r.get("surprise_pct") for r in history[:4] if isinstance(r.get("surprise_pct"), (int, float))]
        avg4 = round(sum(last4) / len(last4), 2) if last4 else None

        if consecutive >= 3 and avg4 and avg4 > 5:
            signal = "strong_momentum"
        elif consecutive >= 2 and avg4 and avg4 > 0:
            signal = "positive_drift"
        elif consecutive == 0 and avg4 is not None and avg4 < -5:
            signal = "declining"
        else:
            signal = "neutral"

        out[t] = {
            "history": history[:4],
            "consecutive_beats": consecutive,
            "avg_surprise_pct_4q": avg4,
            "signal": signal,
        }
    return out


def format_earnings_momentum_for_prompt(by_ticker: dict[str, dict]) -> str:
    if not by_ticker:
        return "  (earnings momentum indisponível)"
    lines = []
    for t, info in by_ticker.items():
        sig = info.get("signal", "no_data")
        if sig in ("no_data", "neutral"):
            continue
        cb = info.get("consecutive_beats", 0)
        avg = info.get("avg_surprise_pct_4q")
        tag = ""
        if sig == "strong_momentum":
            tag = " 🔥 PEAD"
        elif sig == "declining":
            tag = " ⚠️ degradante"
        avg_str = f", surprise médio {avg:+.1f}%" if avg is not None else ""
        lines.append(f"  - {t}: {cb} beats consecutivos{avg_str} → {sig}{tag}")
    return "\n".join(lines) if lines else "  (sem padrões fortes de earnings momentum nos tickers)"


def fetch_company_news(ticker: str, days: int = 7) -> list[dict]:
    """Recent ticker-specific news (free tier). Returns [] if no key."""
    key = _api_key()
    if not key:
        return []
    until = datetime.now().date()
    since = until - timedelta(days=days)
    try:
        r = httpx.get(
            f"{FINNHUB_BASE}/company-news",
            params={
                "symbol": ticker.upper(),
                "from": since.isoformat(),
                "to": until.isoformat(),
                "token": key,
            },
            timeout=8,
        )
        r.raise_for_status()
        return r.json() or []
    except Exception as e:
        logger.debug(f"Finnhub news {ticker} failed: {e}")
        return []


def format_earnings_for_prompt(by_ticker: dict[str, dict | None]) -> str:
    if not by_ticker:
        return "  (calendário earnings indisponível — chave Finnhub não configurada)"
    lines = []
    for t, info in by_ticker.items():
        if not info:
            continue
        d = info.get("days_until")
        eps = info.get("eps_estimate")
        rev = info.get("revenue_estimate")
        urgency = ""
        if isinstance(d, int):
            if d <= 3:
                urgency = " 🚨 IMINENTE"
            elif d <= 7:
                urgency = " ⚠️"
        eps_str = f", EPS est. {eps:+.2f}" if isinstance(eps, (int, float)) else ""
        rev_str = f", revenue est. {rev / 1e9:.2f}B" if isinstance(rev, (int, float)) else ""
        lines.append(f"  - {t}: earnings em {info.get('date')} ({d}d){urgency}{eps_str}{rev_str}")
    return "\n".join(lines) if lines else "  (nenhum ticker com earnings nos próximos 30d)"
