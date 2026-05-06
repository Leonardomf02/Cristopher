"""Market regime detection — risk-on / risk-off posterior probability.

Two engines, picked at runtime:
  1. HMM 2-state Gaussian (via hmmlearn) — if installed, trained on 2y of features.
  2. Rule-based logistic blend — built-in fallback, transparent and stable.

Features used (all available without API keys):
  - VIX level + 20d change           (FRED VIXCLS)
  - 10Y-2Y yield spread             (FRED DGS10 - DGS2)
  - SPY 20d realized vol            (Yahoo)
  - SPY return vs SMA200            (Yahoo)
  - Copper/Gold ratio change 60d    (Yahoo HG=F, GC=F)

Output: P(risk_off) ∈ [0, 1]. The LLM gets this as a single number to
multiply position sizing — risk-off = smaller bets, more defensive bias.
"""
from __future__ import annotations

import math
import logging
import sqlite3
from datetime import date
from typing import Optional

from cache import cached
from market_data import _fetch_yahoo_chart
from macro_data import _fetch_fred_series

logger = logging.getLogger(__name__)


# ── Feature extraction ─────────────────────────────────────────

def _vix_features() -> dict:
    series = _fetch_fred_series("VIXCLS", last_n=60)
    if not series:
        return {}
    vals = [v for _, v in series]
    if len(vals) < 21:
        return {}
    latest = vals[-1]
    past = vals[-21]
    return {
        "vix_level": latest,
        "vix_20d_chg_pct": round((latest / past - 1) * 100, 2) if past else None,
    }


def _yield_curve_features() -> dict:
    s10 = _fetch_fred_series("DGS10", last_n=5)
    s2 = _fetch_fred_series("DGS2", last_n=5)
    if not s10 or not s2:
        return {}
    return {"yc_10y2y": round(s10[-1][1] - s2[-1][1], 2)}


def _spy_features() -> dict:
    chart = _fetch_yahoo_chart("SPY", "1y", "1d")
    closes = chart.get("closes") or []
    if len(closes) < 200:
        return {}

    # 20d realized vol (annualized %)
    rets = []
    for i in range(len(closes) - 21, len(closes)):
        if closes[i - 1] in (None, 0) or closes[i] is None:
            continue
        rets.append(math.log(closes[i] / closes[i - 1]))
    if len(rets) >= 10:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        spy_vol_20d = math.sqrt(var) * math.sqrt(252) * 100
    else:
        spy_vol_20d = None

    sma200 = sum(closes[-200:]) / 200
    cp = closes[-1]
    spy_above_sma200 = (cp / sma200 - 1) * 100 if sma200 else None

    return {
        "spy_vol_20d_pct": round(spy_vol_20d, 2) if spy_vol_20d is not None else None,
        "spy_pct_vs_sma200": round(spy_above_sma200, 2) if spy_above_sma200 is not None else None,
    }


def _copper_gold_features() -> dict:
    cu = _fetch_yahoo_chart("HG=F", "3mo", "1d")
    au = _fetch_yahoo_chart("GC=F", "3mo", "1d")
    cu_closes = cu.get("closes") or []
    au_closes = au.get("closes") or []
    if len(cu_closes) < 60 or len(au_closes) < 60:
        return {}
    n = min(len(cu_closes), len(au_closes))
    ratio_now = (cu_closes[-1] / au_closes[-1]) * 1000 if au_closes[-1] else None
    ratio_60d_ago = (cu_closes[-60] / au_closes[-60]) * 1000 if au_closes[-60] else None
    if ratio_now and ratio_60d_ago:
        chg = (ratio_now / ratio_60d_ago - 1) * 100
        return {"cu_au_ratio": round(ratio_now, 2), "cu_au_60d_chg_pct": round(chg, 2)}
    return {}


@cached("regime:features", ttl_seconds=2 * 3600)   # 2h
def fetch_regime_features() -> dict:
    feats: dict = {}
    feats.update(_vix_features())
    feats.update(_yield_curve_features())
    feats.update(_spy_features())
    feats.update(_copper_gold_features())
    return feats


# ── Rule-based blend (transparent, no ML) ──────────────────────

def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _rule_based_posterior(feats: dict) -> tuple[float, list[str]]:
    """Logistic blend of risk indicators. Returns (p_risk_off, reasoning_lines).

    Each indicator contributes a weighted signed score; logits → P(risk-off).
    """
    score = 0.0
    reasoning: list[str] = []

    vix = feats.get("vix_level")
    if vix is not None:
        # VIX 14→0 (calm), 25→+1 (stress), 35→+2.5 (panic)
        contrib = max(-1.0, (vix - 18) / 7)
        score += contrib
        if abs(contrib) > 0.3:
            reasoning.append(f"VIX {vix:.1f} → {contrib:+.2f}")

    vix_chg = feats.get("vix_20d_chg_pct")
    if vix_chg is not None:
        contrib = max(-0.5, min(1.0, vix_chg / 30))
        score += contrib * 0.5
        if abs(contrib) > 0.4:
            reasoning.append(f"VIX 20d {vix_chg:+.0f}% → {contrib * 0.5:+.2f}")

    yc = feats.get("yc_10y2y")
    if yc is not None:
        # Inverted curve = recession warning
        contrib = max(-0.5, min(1.0, (-yc + 0.2) / 0.5))
        score += contrib * 0.7
        if abs(contrib) > 0.3:
            reasoning.append(f"YC {yc:+.2f}pp → {contrib * 0.7:+.2f}")

    spy_vol = feats.get("spy_vol_20d_pct")
    if spy_vol is not None:
        # SPY vol 12 (normal) → 0, 25+ (stress) → +1
        contrib = max(-0.5, (spy_vol - 14) / 10)
        score += contrib * 0.6
        if abs(contrib) > 0.3:
            reasoning.append(f"SPY vol 20d {spy_vol:.1f}% → {contrib * 0.6:+.2f}")

    spy_sma = feats.get("spy_pct_vs_sma200")
    if spy_sma is not None:
        # SPY below SMA200 = bear-ish
        contrib = max(-1.0, min(1.0, -spy_sma / 5))
        score += contrib * 0.5
        if abs(contrib) > 0.2:
            reasoning.append(f"SPY {spy_sma:+.1f}% vs SMA200 → {contrib * 0.5:+.2f}")

    cu_au_chg = feats.get("cu_au_60d_chg_pct")
    if cu_au_chg is not None:
        # Copper/gold falling 60d → defensive demand → risk-off
        contrib = max(-1.0, min(1.0, -cu_au_chg / 15))
        score += contrib * 0.4
        if abs(contrib) > 0.3:
            reasoning.append(f"Cu/Au 60d {cu_au_chg:+.1f}% → {contrib * 0.4:+.2f}")

    p_risk_off = _sigmoid(score)
    return p_risk_off, reasoning


# ── HMM (optional, falls back if hmmlearn missing) ─────────────

_HMM_MODEL = None
_HMM_FAILED = False


def _try_load_hmm():
    global _HMM_MODEL, _HMM_FAILED
    if _HMM_MODEL is not None or _HMM_FAILED:
        return _HMM_MODEL
    try:
        from hmmlearn.hmm import GaussianHMM  # type: ignore
        # Train on demand once per process
        _HMM_MODEL = _train_hmm_now(GaussianHMM)
        return _HMM_MODEL
    except Exception as e:
        logger.info(f"HMM unavailable ({e}); using rule-based regime")
        _HMM_FAILED = True
        return None


def _train_hmm_now(GaussianHMM):
    """Train 2-state HMM on 2y of [VIX_level, SPY_vol_20d, YC_spread]."""
    import numpy as np  # type: ignore

    vix_series = _fetch_fred_series("VIXCLS", last_n=500)
    s10 = _fetch_fred_series("DGS10", last_n=500)
    s2 = _fetch_fred_series("DGS2", last_n=500)
    spy = _fetch_yahoo_chart("SPY", "2y", "1d").get("closes") or []

    if not (vix_series and s10 and s2 and len(spy) > 250):
        raise ValueError("insufficient data to train HMM")

    # Align by length — take the last min N points of each
    n = min(len(vix_series), len(s10), len(s2), len(spy) - 21)
    if n < 100:
        raise ValueError(f"only {n} aligned points")

    vix = np.array([v for _, v in vix_series[-n:]])
    yc = np.array([s10[-n + i][1] - s2[-n + i][1] for i in range(n)])
    # SPY 20d rolling vol
    spy_returns = np.diff(np.log(spy[-(n + 21):]))
    spy_vol = []
    for i in range(n):
        window = spy_returns[i:i + 21]
        if len(window) < 5:
            spy_vol.append(0.0)
            continue
        spy_vol.append(float(np.std(window) * np.sqrt(252) * 100))
    spy_vol_arr = np.array(spy_vol)

    X = np.column_stack([vix, yc, spy_vol_arr])
    model = GaussianHMM(n_components=2, covariance_type="diag", n_iter=100, random_state=42)
    model.fit(X)

    # Identify which state is "risk-off" by mean VIX
    means = model.means_
    risk_off_state = int(np.argmax(means[:, 0]))
    model._risk_off_state = risk_off_state  # type: ignore
    logger.info(f"HMM trained on {n} obs, risk_off_state={risk_off_state}, means VIX={means[:, 0]}")
    return model


def _hmm_posterior(feats: dict) -> Optional[float]:
    model = _try_load_hmm()
    if model is None:
        return None
    try:
        import numpy as np  # type: ignore
        vix = feats.get("vix_level")
        yc = feats.get("yc_10y2y")
        spy_vol = feats.get("spy_vol_20d_pct")
        if None in (vix, yc, spy_vol):
            return None
        x = np.array([[vix, yc, spy_vol]])
        # Posterior P(state | x)
        log_posterior = model.predict_proba(x)
        risk_off_state = getattr(model, "_risk_off_state", 1)
        return float(log_posterior[0, risk_off_state])
    except Exception as e:
        logger.debug(f"HMM predict failed: {e}")
        return None


# ── Public API ─────────────────────────────────────────────────

def fetch_regime_snapshot() -> dict:
    """Returns a dict with regime probability + features + classification."""
    feats = fetch_regime_features()
    if not feats:
        return {"available": False}

    p_rule, reasoning = _rule_based_posterior(feats)
    p_hmm = _hmm_posterior(feats)

    # Blend if both available — average them; rule is anchor, HMM adds market memory
    p_final = (p_rule + p_hmm) / 2 if p_hmm is not None else p_rule

    classification = (
        "risk-off" if p_final >= 0.65 else
        "risk-on" if p_final <= 0.35 else
        "neutral"
    )

    return {
        "available": True,
        "p_risk_off": round(p_final, 3),
        "p_risk_off_rule": round(p_rule, 3),
        "p_risk_off_hmm": round(p_hmm, 3) if p_hmm is not None else None,
        "classification": classification,
        "reasoning": reasoning,
        "features": feats,
    }


def format_regime_for_prompt(snap: dict) -> str:
    if not snap or not snap.get("available"):
        return "  (regime indisponível)"
    p = snap.get("p_risk_off", 0.5)
    cls = snap.get("classification", "neutral")
    parts = [f"P(risk-off) = {p:.2f} → {cls.upper()}"]
    if snap.get("p_risk_off_hmm") is not None:
        parts.append(f"(rule={snap.get('p_risk_off_rule')}, HMM={snap.get('p_risk_off_hmm')})")
    out = ["  " + " ".join(parts)]
    if snap.get("reasoning"):
        out.append("  drivers: " + "; ".join(snap["reasoning"]))
    return "\n".join(out)


def persist_daily_regime(snap: dict, db_path: str = "cristopher.db") -> None:
    """Upsert today's regime snapshot into daily_regime table."""
    if not snap or not snap.get("available"):
        return
    today = date.today().isoformat()
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("""
            INSERT INTO daily_regime (date, p_risk_off, p_risk_off_rule, p_risk_off_hmm, classification)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                p_risk_off=excluded.p_risk_off,
                p_risk_off_rule=excluded.p_risk_off_rule,
                p_risk_off_hmm=excluded.p_risk_off_hmm,
                classification=excluded.classification
        """, (
            today,
            float(snap.get("p_risk_off") or 0.5),
            float(snap["p_risk_off_rule"]) if snap.get("p_risk_off_rule") is not None else None,
            float(snap["p_risk_off_hmm"]) if snap.get("p_risk_off_hmm") is not None else None,
            snap.get("classification", "neutral"),
        ))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"persist_daily_regime failed: {e}")


def fetch_regime_history(days: int = 60, db_path: str = "cristopher.db") -> list[dict]:
    """Returns chronological list (oldest → newest) of past regime snapshots."""
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT date, p_risk_off, p_risk_off_rule, p_risk_off_hmm, classification "
            "FROM daily_regime ORDER BY date DESC LIMIT ?",
            (days,),
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"fetch_regime_history failed: {e}")
        return []
    return [
        {
            "date": r[0],
            "p_risk_off": r[1],
            "p_risk_off_rule": r[2],
            "p_risk_off_hmm": r[3],
            "classification": r[4],
        }
        for r in reversed(rows)
    ]
