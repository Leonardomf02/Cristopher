"""On-chain crypto signals (BTC + ETH).

All sources are free and key-less:
  - mempool.space        BTC fees, mempool size, hashrate
  - CoinMetrics community  MVRV, active addresses, NVT, realized cap
  - Binance public         futures funding rate (proxy of leveraged sentiment)
  - alternative.me F&G    (already used elsewhere; keep complementary here)

Returns a flat dict ready to drop into the prompt. None on each missing field.
"""
from __future__ import annotations

import logging
import math
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta

import httpx

from cache import cached

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 Cristopher-Onchain/1.0"

COINMETRICS_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
MEMPOOL_BASE = "https://mempool.space/api"
BINANCE_FUTURES = "https://fapi.binance.com/fapi/v1/premiumIndex"
BLOCKCHAIN_COM = "https://api.blockchain.info"


# ── BTC: mempool.space ─────────────────────────────────────────

def _fetch_mempool() -> dict:
    """BTC mempool fees, hashrate, blocks. Returns {} on error."""
    out: dict = {}
    try:
        r = httpx.get(f"{MEMPOOL_BASE}/v1/fees/recommended", headers={"User-Agent": USER_AGENT}, timeout=8)
        if r.status_code == 200:
            d = r.json()
            out["btc_fee_fast_satvb"] = d.get("fastestFee")
            out["btc_fee_normal_satvb"] = d.get("halfHourFee")
    except Exception as e:
        logger.debug(f"mempool fees failed: {e}")

    try:
        r = httpx.get(f"{MEMPOOL_BASE}/v1/mining/hashrate/3d", headers={"User-Agent": USER_AGENT}, timeout=8)
        if r.status_code == 200:
            d = r.json()
            current = d.get("currentHashrate")
            if current:
                # In hashes/sec → display in EH/s
                out["btc_hashrate_ehs"] = round(current / 1e18, 1)
    except Exception as e:
        logger.debug(f"mempool hashrate failed: {e}")

    return out


# ── BTC: CoinMetrics community ─────────────────────────────────

CM_METRICS = [
    "CapMrktCurUSD",     # market cap (USD)
    "CapRealUSD",        # realized cap
    "AdrActCnt",         # active addresses
    "TxCnt",             # transaction count
    "FeeTotUSD",         # total fees (USD)
    "PriceUSD",          # close price
    "SplyCur",           # current supply
]


def _fetch_coinmetrics(asset: str) -> dict:
    """Returns most recent values for a basket of CM metrics."""
    try:
        r = httpx.get(
            COINMETRICS_URL,
            params={
                "assets": asset,
                "metrics": ",".join(CM_METRICS),
                "page_size": 7,
                "frequency": "1d",
            },
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=10,
        )
        r.raise_for_status()
        rows = r.json().get("data", [])
        if not rows:
            return {}
        latest = rows[-1]
        oldest = rows[0]
        out: dict = {}
        for k in CM_METRICS:
            v = latest.get(k)
            if v is None:
                continue
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                continue
        mv = out.get("CapMrktCurUSD")
        rv = out.get("CapRealUSD")
        if mv and rv:
            out["mvrv"] = round(mv / rv, 2)
        nvt_fees = out.get("FeeTotUSD")
        if mv and nvt_fees and nvt_fees > 0:
            out["nvt_fees"] = round(mv / nvt_fees, 1)
        try:
            old_active = float(oldest.get("AdrActCnt") or 0)
            new_active = float(latest.get("AdrActCnt") or 0)
            if old_active > 0:
                out["active_addr_7d_pct"] = round((new_active / old_active - 1) * 100, 1)
        except (TypeError, ValueError):
            pass
        return out
    except Exception as e:
        logger.debug(f"CoinMetrics {asset} unavailable: {e}")
        return {}


def _fetch_blockchain_com() -> dict:
    """BTC chain stats via blockchain.info (free, no auth)."""
    out: dict = {}
    try:
        r = httpx.get(f"{BLOCKCHAIN_COM}/stats", headers={"User-Agent": USER_AGENT}, timeout=8)
        if r.status_code == 200:
            d = r.json()
            out["n_tx_24h"] = d.get("n_tx")
            out["miners_revenue_24h_usd"] = d.get("miners_revenue_usd")
            out["mempool_size_bytes"] = d.get("mempool_size")
            out["difficulty"] = d.get("difficulty")
            mc = d.get("market_price_usd")
            if mc:
                out["btc_price_blockchain"] = mc
    except Exception as e:
        logger.debug(f"blockchain.info stats failed: {e}")
    return out


# ── Funding rates (Binance perpetual futures) ──────────────────

def _fetch_binance_funding(symbol: str = "BTCUSDT") -> dict:
    """Latest funding rate for a perpetual contract.
    Positive = longs paying shorts (bullish leverage), negative = bearish."""
    try:
        r = httpx.get(BINANCE_FUTURES, params={"symbol": symbol}, headers={"User-Agent": USER_AGENT}, timeout=8)
        r.raise_for_status()
        d = r.json()
        rate = float(d.get("lastFundingRate") or 0)
        # Annualized (3× per day × 365)
        annualized = rate * 3 * 365 * 100
        return {
            "funding_rate_pct": round(rate * 100, 4),
            "funding_rate_annualized_pct": round(annualized, 2),
            "mark_price": float(d.get("markPrice") or 0),
        }
    except Exception as e:
        logger.warning(f"Binance funding {symbol} failed: {e}")
        return {}


# ── Aggregate ──────────────────────────────────────────────────

@cached("onchain:snapshot", ttl_seconds=30 * 60)   # 30m — on-chain moves slowly day-to-day
def fetch_onchain_snapshot() -> dict:
    """Parallel fetch all on-chain sources. Returns flat dict."""
    out: dict = {"as_of": datetime.now().isoformat(timespec="seconds")}
    # Each fetcher writes into its own asset-prefixed namespace; no double-prefixing.
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {
            ex.submit(_fetch_mempool): ("btc", None),         # output already has btc_*
            ex.submit(_fetch_blockchain_com): ("btc", None),  # output already has btc_*
            ex.submit(_fetch_coinmetrics, "btc"): ("btc", "cm"),
            ex.submit(_fetch_coinmetrics, "eth"): ("eth", "cm"),
            ex.submit(_fetch_binance_funding, "BTCUSDT"): ("btc", "funding"),
            ex.submit(_fetch_binance_funding, "ETHUSDT"): ("eth", "funding"),
        }
        for fut in as_completed(futures):
            asset, sub = futures[fut]
            try:
                data = fut.result() or {}
            except Exception as e:
                logger.debug(f"on-chain {asset}/{sub} failed: {e}")
                data = {}
            for k, v in data.items():
                if sub is None:
                    # Mempool / blockchain.info already prefix with asset name → trust them
                    out[k] = v
                else:
                    # Explicit namespacing for CoinMetrics / Binance funding
                    out[f"{asset}_{sub}_{k}"] = v
    return out


def format_onchain_for_prompt(snap: dict) -> str:
    if not snap:
        return "  (on-chain indisponível)"

    lines = []

    # BTC chain health
    btc_chain_parts = []
    if snap.get("btc_fee_fast_satvb") is not None:
        btc_chain_parts.append(f"taxa rápida {snap['btc_fee_fast_satvb']} sat/vB")
    if snap.get("btc_hashrate_ehs") is not None:
        btc_chain_parts.append(f"hashrate {snap['btc_hashrate_ehs']} EH/s")
    if snap.get("n_tx_24h") is not None:
        btc_chain_parts.append(f"tx 24h {snap['n_tx_24h']:,}")
    if btc_chain_parts:
        lines.append("  BTC chain: " + ", ".join(btc_chain_parts))

    # BTC valuation/cycle
    btc_val_parts = []
    btc_mvrv = snap.get("btc_cm_mvrv")
    if btc_mvrv is not None:
        tag = " (top cycle)" if btc_mvrv > 3.5 else " (deep value)" if btc_mvrv < 1 else ""
        btc_val_parts.append(f"MVRV {btc_mvrv}{tag}")
    if snap.get("btc_cm_active_addr_7d_pct") is not None:
        btc_val_parts.append(f"endereços ativos 7d {snap['btc_cm_active_addr_7d_pct']:+.1f}%")
    if snap.get("btc_funding_funding_rate_annualized_pct") is not None:  # canonical key
        f = snap["btc_funding_funding_rate_annualized_pct"]
        tag = " (longs pagando)" if f > 10 else " (shorts pagando)" if f < -5 else ""
        btc_val_parts.append(f"funding rate anual {f:+.1f}%{tag}")
    if btc_val_parts:
        lines.append("  BTC sinais: " + ", ".join(btc_val_parts))

    # ETH cycle
    eth_parts = []
    eth_mvrv = snap.get("eth_cm_mvrv")
    if eth_mvrv is not None:
        tag = " (top)" if eth_mvrv > 3 else " (value)" if eth_mvrv < 1 else ""
        eth_parts.append(f"MVRV {eth_mvrv}{tag}")
    if snap.get("eth_cm_active_addr_7d_pct") is not None:
        eth_parts.append(f"endereços 7d {snap['eth_cm_active_addr_7d_pct']:+.1f}%")
    if snap.get("eth_funding_funding_rate_annualized_pct") is not None:
        eth_parts.append(f"funding {snap['eth_funding_funding_rate_annualized_pct']:+.1f}% anual")
    # Ethereum on-chain extras
    if snap.get("eth_cm_mvrv") is not None:
        pass  # already covered above
    if eth_parts:
        lines.append("  ETH sinais: " + ", ".join(eth_parts))

    return "\n".join(lines) if lines else "  (sem dados on-chain disponíveis)"


# ── Funding rate persistence (BTC contrarian signal) ───────────

def persist_daily_funding(snap: dict, db_path: str = "cristopher.db") -> None:
    """Upsert today's funding rate (BTC + ETH) into daily_funding table.

    Persistence is the contrarian signal: 5+ consecutive days of extreme
    funding (>15% annualized either direction) typically resolves with a
    squeeze in the opposite direction.
    """
    if not snap:
        return
    today = date.today().isoformat()
    rows = []
    btc = snap.get("btc_funding_funding_rate_annualized_pct")
    if isinstance(btc, (int, float)):
        rows.append((today, "BTC", float(btc)))
    eth = snap.get("eth_funding_funding_rate_annualized_pct")
    if isinstance(eth, (int, float)):
        rows.append((today, "ETH", float(eth)))
    if not rows:
        return
    try:
        conn = sqlite3.connect(db_path)
        conn.executemany("""
            INSERT INTO daily_funding (date, symbol, rate_pct)
            VALUES (?, ?, ?)
            ON CONFLICT(date, symbol) DO UPDATE SET rate_pct=excluded.rate_pct
        """, rows)
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"persist_daily_funding failed: {e}")


def compute_funding_persistence(symbol: str = "BTC", db_path: str = "cristopher.db") -> dict:
    """Detect persistent leverage skew.

    Returns:
      - n_days: days of history available
      - current_pct: most recent annualized rate
      - consecutive_extreme_days: streak above |15%| annualized
      - direction: 'long_skew' | 'short_skew' | 'neutral'
      - z_score: vs 30d mean/std
      - signal: 'contrarian_short' | 'contrarian_long' | 'neutral'
    """
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT date, rate_pct FROM daily_funding WHERE symbol = ? ORDER BY date DESC LIMIT 30",
            (symbol.upper(),),
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"compute_funding_persistence failed: {e}")
        return {"available": False}

    if len(rows) < 3:
        return {"available": False, "n_days": len(rows)}

    rates = [r[1] for r in rows]   # newest first
    current = rates[0]

    threshold = 15.0
    consecutive = 0
    direction = "neutral"
    if current >= threshold:
        direction = "long_skew"
        for r in rates:
            if r >= threshold:
                consecutive += 1
            else:
                break
    elif current <= -threshold:
        direction = "short_skew"
        for r in rates:
            if r <= -threshold:
                consecutive += 1
            else:
                break

    if len(rates) >= 10:
        mean = sum(rates) / len(rates)
        var = sum((x - mean) ** 2 for x in rates) / (len(rates) - 1)
        std = math.sqrt(var) if var > 0 else 0.0
        z = (current - mean) / std if std > 1e-6 else 0.0
    else:
        z = 0.0

    signal = "neutral"
    if consecutive >= 5 and direction == "long_skew":
        signal = "contrarian_short"
    elif consecutive >= 5 and direction == "short_skew":
        signal = "contrarian_long"

    return {
        "available": True,
        "symbol": symbol.upper(),
        "n_days": len(rates),
        "current_pct": round(current, 2),
        "consecutive_extreme_days": consecutive,
        "direction": direction,
        "z_score": round(z, 2),
        "signal": signal,
    }


def fetch_funding_history(symbol: str = "BTC", days: int = 60, db_path: str = "cristopher.db") -> list[dict]:
    """Chronological list (oldest → newest) for charting."""
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT date, rate_pct FROM daily_funding WHERE symbol = ? "
            "ORDER BY date DESC LIMIT ?",
            (symbol.upper(), days),
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"fetch_funding_history failed: {e}")
        return []
    return [{"date": r[0], "rate_pct": r[1]} for r in reversed(rows)]


def format_funding_persistence_for_prompt(p: dict) -> str:
    if not p or not p.get("available"):
        n = (p or {}).get("n_days", 0)
        return f"  (funding persistence indisponível — {n}d histórico, mínimo 3d)"
    sig = p.get("signal", "neutral")
    tag = ""
    if sig == "contrarian_short":
        tag = " ⚠️ squeeze short provável"
    elif sig == "contrarian_long":
        tag = " ⚠️ squeeze long provável"
    return (
        f"  {p['symbol']}: funding {p['current_pct']:+.1f}% anual, "
        f"{p['consecutive_extreme_days']}d {p['direction']}, "
        f"z={p['z_score']:+.2f}{tag}"
    )
