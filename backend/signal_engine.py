"""Deterministic signal engine — the decision-maker for investment signals.

This is the core of the "hybrid" architecture: instead of letting the LLM pick
tickers/actions/amounts from a text prompt (non-reproducible, bad at
cross-sectional ranking), a pure-Python engine scores every asset from the
quantitative signals already collected, applies decision gates *ex-ante*, sizes
positions with vol-targeting, and ranks candidates. The LLM then only narrates
the thesis and red-teams — it never decides the numbers.

All functions here are pure (no I/O, no DB) so the engine is fully testable and
reproducible: same input metrics → same candidates, every time.

Sub-scores are normalized to [-1, +1] where +1 = maximally bullish (good to buy).
The final 0-100 score is 50 + 50·(weighted mean of contributing families),
modulated by the market regime. Conviction and action derive from the score and
the gates — not from the LLM.
"""
from __future__ import annotations

import logging
from typing import Optional

from risk_management import _vol_targeted_size, MAX_SINGLE_NAME_PCT

logger = logging.getLogger(__name__)

ENGINE_VERSION = "engine-v1"

# Practical minimum buy for EU brokers (mirrors signal_validation.MIN_BUY_AMOUNT_EUR).
MIN_BUY_AMOUNT_EUR = 25

# ── Decision gates (ex-ante) ────────────────────────────────────
# The engine never emits a 'buy' that violates these — it downgrades to 'watch'
# with a recorded reason. Mirror the thresholds the old post-hoc gates used.
GATE_RSI_OVERBOUGHT = 70.0
GATE_EARNINGS_DAYS = 14
GATE_MIN_FAMILIES = 2          # a buy must cross ≥2 signal families
BUY_SCORE_THRESHOLD = 62.0     # score ≥ this + gates pass → buy candidate
WATCH_SCORE_THRESHOLD = 52.0   # below buy but worth watching

# Conviction cut-offs on the 0-100 score.
CONVICTION_HIGH = 72.0
CONVICTION_MEDIUM = 58.0

# Default family weights. Overridden per-run by calibration feedback
# (calibration_feedback.family_weight_adjustments) once enough history exists.
FAMILY_WEIGHTS: dict[str, float] = {
    "técnico":     0.30,
    "fundamental": 0.25,
    "earnings":    0.20,
    "on-chain":    0.15,
    "sentimento":  0.05,
    "insider":     0.05,
}


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ── Per-family sub-scores → (score in [-1,1], contributed: bool) ─────────────

def score_technical(m: dict) -> tuple[float, bool]:
    """RSI mean-reversion + trend filter (SMA200) + cross-sectional momentum + anomaly."""
    if not m or m.get("source") in ("none", "error"):
        return 0.0, False
    parts: list[float] = []

    rsi = m.get("rsi_14")
    if isinstance(rsi, (int, float)):
        # Oversold (<30) bullish for entry, overbought (>70) bearish. Linear around 50.
        parts.append(_clamp((50.0 - rsi) / 20.0))

    cp = m.get("current_price")
    sma200 = m.get("sma_200")
    if cp and sma200:
        # Trend filter: above the 200-day = structural uptrend.
        parts.append(0.4 if cp > sma200 else -0.4)

    mom_pctile = m.get("momentum_pctile")
    if isinstance(mom_pctile, (int, float)):
        parts.append(_clamp((mom_pctile - 50.0) / 50.0))

    anom = m.get("anomaly") or {}
    if anom.get("anomaly"):
        z = anom.get("z_score") or 0
        # An abnormal move adds caution proportional to its sign (down = bearish).
        parts.append(_clamp(z / 5.0))

    if not parts:
        return 0.0, False
    return _clamp(sum(parts) / len(parts)), True


def score_fundamental(f: Optional[dict]) -> tuple[float, bool]:
    """Quality (ROE, margin, low debt) minus rich valuation (P/E, EV/EBITDA)."""
    if not f or not f.get("available"):
        return 0.0, False
    parts: list[float] = []

    roe = f.get("roe_ttm")
    if isinstance(roe, (int, float)):
        # ROE 0→0, 0.20 (20%)→+0.5, 0.40→+1
        parts.append(_clamp(roe / 0.40))

    nm = f.get("net_margin")
    if isinstance(nm, (int, float)):
        parts.append(_clamp(nm / 0.30))

    de = f.get("debt_equity")
    if isinstance(de, (int, float)):
        # Low leverage good; D/E 0→+0.5, 1→0, 2+→-0.5
        parts.append(_clamp((1.0 - de) * 0.5))

    pe = f.get("pe_ttm")
    if isinstance(pe, (int, float)) and pe > 0:
        # Cheap (<15)→+, expensive (>40)→-. Centred near 25.
        parts.append(_clamp((25.0 - pe) / 25.0))

    ev = f.get("ev_ebitda")
    if isinstance(ev, (int, float)) and ev > 0:
        parts.append(_clamp((15.0 - ev) / 15.0))

    if not parts:
        return 0.0, False
    return _clamp(sum(parts) / len(parts)), True


def score_earnings(mom: Optional[dict]) -> tuple[float, bool]:
    """PEAD momentum: consecutive beats drift up; declining surprises drift down."""
    if not mom:
        return 0.0, False
    sig = mom.get("signal")
    mapping = {
        "strong_momentum": 0.8,
        "positive_drift": 0.4,
        "declining": -0.6,
        "neutral": 0.0,
    }
    if sig not in mapping or sig == "no_data":
        return 0.0, False
    return mapping[sig], sig != "neutral"


def score_onchain(
    asset_type: str,
    ticker: str,
    onchain: Optional[dict],
    funding: Optional[dict],
) -> tuple[float, bool]:
    """Crypto only: MVRV cycle position + funding-persistence contrarian squeeze."""
    if asset_type != "crypto" or not onchain:
        return 0.0, False
    t = ticker.upper().replace("-USD", "")
    prefix = "btc" if t == "BTC" else "eth" if t == "ETH" else None
    if prefix is None:
        return 0.0, False
    parts: list[float] = []

    mvrv = onchain.get(f"{prefix}_cm_mvrv")
    if isinstance(mvrv, (int, float)):
        # >3.5 cycle top (bearish), <1 deep value (bullish). Centred at ~2.
        if mvrv > 3.5:
            parts.append(_clamp(-(mvrv - 3.5) / 2.0 - 0.3))
        elif mvrv < 1.0:
            parts.append(_clamp((1.0 - mvrv) + 0.3))
        else:
            parts.append(_clamp((2.0 - mvrv) / 3.0))

    if funding and funding.get("available"):
        sig = funding.get("signal")
        # Contrarian: persistent long skew → squeeze down probable (bearish) & vice-versa.
        if sig == "contrarian_short":
            parts.append(-0.5)
        elif sig == "contrarian_long":
            parts.append(0.5)

    if not parts:
        return 0.0, False
    return _clamp(sum(parts) / len(parts)), True


def score_sentiment(sentiment_agg: Optional[dict], sentiment_delta: Optional[dict]) -> tuple[float, bool]:
    """Market-wide news sentiment + its swing (z-score). Same for every asset."""
    parts: list[float] = []
    if sentiment_agg:
        avg = sentiment_agg.get("avg")
        if isinstance(avg, (int, float)):
            parts.append(_clamp(avg * 2.0))   # avg is ~[-0.5,0.5]
    if sentiment_delta and sentiment_delta.get("available"):
        z = sentiment_delta.get("z_score")
        if isinstance(z, (int, float)):
            parts.append(_clamp(z / 3.0))
    if not parts:
        return 0.0, False
    return _clamp(sum(parts) / len(parts)), True


def score_insider(insider: Optional[dict]) -> tuple[float, bool]:
    """Weak, direction-ambiguous: Form-4 cluster only tells us *activity*, not buy/sell.
    Kept as a tiny tilt so it informs but never drives a decision."""
    if not insider or not insider.get("available"):
        return 0.0, False
    if insider.get("spike"):
        return 0.15, True
    return 0.0, False


# ── Regime overlay ──────────────────────────────────────────────

def regime_multiplier(asset_type: str, beta: Optional[float], regime: Optional[dict]) -> float:
    """Scale a bullish score by the market regime.

    Risk-off shrinks high-beta / crypto and slightly lifts low-beta defensives;
    risk-on does the opposite. Returns a multiplier in ~[0.6, 1.3].
    """
    if not regime or not regime.get("available"):
        return 1.0
    p_off = regime.get("p_risk_off", 0.5)
    # tilt: +1 fully risk-off, -1 fully risk-on
    tilt = (p_off - 0.5) * 2.0

    # How "risky" is this asset? crypto highest, then high-beta stocks, ETFs neutral.
    if asset_type == "crypto":
        riskiness = 1.0
    elif asset_type == "etf":
        riskiness = 0.3
    else:
        riskiness = 0.6 if beta is None else _clamp((beta - 1.0), -0.5, 1.0) * 0.6 + 0.6

    # Risk-off (tilt>0) penalizes risky assets; risk-on rewards them.
    return _clamp(1.0 - tilt * riskiness * 0.3, 0.6, 1.3)


# ── Compose the asset score ─────────────────────────────────────

def score_asset(
    ticker: str,
    asset_type: str,
    metrics: dict,
    ctx: dict,
) -> dict:
    """Score one asset across all families. Returns score 0-100 + breakdown + families.

    ctx holds the shared context: fundamentals/earnings/insider by ticker,
    onchain snapshot, funding by symbol, market-wide sentiment, regime, and the
    (possibly calibration-adjusted) family weights.
    """
    weights = ctx.get("family_weights") or FAMILY_WEIGHTS
    t = ticker.upper()

    fund = (ctx.get("fundamentals") or {}).get(t)
    mom = (ctx.get("earnings_momentum") or {}).get(t)
    insider = (ctx.get("insider") or {}).get(t)
    funding = None
    if asset_type == "crypto":
        base = t.replace("-USD", "")
        funding = ctx.get("funding_btc") if base == "BTC" else ctx.get("funding_eth") if base == "ETH" else None

    family_scores: dict[str, float] = {}
    contributed: dict[str, bool] = {}

    for fam, (s, c) in {
        "técnico":     score_technical(metrics),
        "fundamental": score_fundamental(fund),
        "earnings":    score_earnings(mom),
        "on-chain":    score_onchain(asset_type, t, ctx.get("onchain"), funding),
        "sentimento":  score_sentiment(ctx.get("sentiment_agg"), ctx.get("sentiment_delta")),
        "insider":     score_insider(insider),
    }.items():
        family_scores[fam] = round(s, 3)
        contributed[fam] = c

    # Weighted mean over families that actually contributed a non-trivial signal.
    num = 0.0
    den = 0.0
    active_families: list[str] = []
    for fam, s in family_scores.items():
        if not contributed[fam]:
            continue
        w = weights.get(fam, 0.0)
        num += w * s
        den += w
        # "sentimento" is market-wide — it's not an idiosyncratic family for the
        # ≥2-families gate, so we don't count it toward signal diversity.
        if fam != "sentimento":
            active_families.append(fam)

    raw = (num / den) if den > 0 else 0.0   # [-1, 1]

    beta = (fund or {}).get("beta")
    mult = regime_multiplier(asset_type, beta, ctx.get("regime"))
    adj = _clamp(raw * mult)

    score = round(_clamp(50.0 + 50.0 * adj, 0.0, 99.0), 1)

    return {
        "ticker": t,
        "asset_type": asset_type,
        "score": score,
        "raw_score": round(raw, 3),
        "regime_mult": round(mult, 3),
        "signal_breakdown": {f: family_scores[f] for f in family_scores if contributed[f]},
        "signal_families": sorted(set(active_families)),
    }


def conviction_from_score(score: float) -> str:
    if score >= CONVICTION_HIGH:
        return "high"
    if score >= CONVICTION_MEDIUM:
        return "medium"
    return "low"


# ── Gates + action decision (ex-ante) ───────────────────────────

def decide_action(
    scored: dict,
    metrics: dict,
    days_to_earnings: Optional[int],
) -> tuple[str, list[dict]]:
    """Decide buy/watch from score + ex-ante gates. Returns (action, gates_triggered).

    A 'buy' requires: score ≥ BUY_SCORE_THRESHOLD, RSI ≤ 70, no earnings within
    14d, and ≥2 contributing signal families. Any failure → 'watch' with reason.
    Below the watch threshold the caller drops the candidate entirely.
    """
    gates: list[dict] = []
    score = scored["score"]

    if score < BUY_SCORE_THRESHOLD:
        return ("watch" if score >= WATCH_SCORE_THRESHOLD else "skip"), gates

    rsi = metrics.get("rsi_14")
    if isinstance(rsi, (int, float)) and rsi > GATE_RSI_OVERBOUGHT:
        gates.append({"gate": "rsi_overbought", "reason": f"RSI {rsi:.1f} > {GATE_RSI_OVERBOUGHT:.0f}"})

    if isinstance(days_to_earnings, int) and 0 <= days_to_earnings <= GATE_EARNINGS_DAYS:
        gates.append({"gate": "earnings_too_close", "reason": f"earnings em {days_to_earnings}d (≤{GATE_EARNINGS_DAYS}d)"})

    fams = scored.get("signal_families") or []
    if len(fams) < GATE_MIN_FAMILIES:
        gates.append({"gate": "single_dimension", "reason": f"só {len(fams)} família(s): {','.join(fams) or 'nenhuma'}"})

    return ("watch" if gates else "buy"), gates


def size_new_idea(metrics: dict, monthly_budget: float) -> int:
    """Vol-targeted € amount for a discretionary buy, floored at the practical minimum."""
    vol = metrics.get("realized_vol_252_pct")
    suggested = _vol_targeted_size(vol, monthly_budget) if vol else None
    if not suggested:
        suggested = monthly_budget * 0.15
    amount = int(round(max(suggested, MIN_BUY_AMOUNT_EUR)))
    return min(amount, int(round(monthly_budget)))


# ── Orchestration ───────────────────────────────────────────────

def rank_universe(
    universe: list[tuple[str, str]],
    market_data: dict[str, dict],
    ctx: dict,
    monthly_budget: float,
    *,
    exclude: Optional[set[str]] = None,
    plan_tickers: Optional[set[str]] = None,
    top_n: int = 12,
) -> list[dict]:
    """Score every universe asset, keep buy/watch candidates, return top-N by score.

    Excludes plan tickers (covered separately) and user-rejected tickers. These
    are the engine's reproducible 'new ideas' — the LLM may add more but they go
    back through this same scoring.
    """
    exclude = {t.upper() for t in (exclude or set())}
    plan_tickers = {t.upper() for t in (plan_tickers or set())}

    candidates: list[dict] = []
    for ticker, asset_type in universe:
        t = ticker.upper()
        if t in exclude or t in plan_tickers:
            continue
        metrics = market_data.get(t) or market_data.get(t.replace("-", ".")) or {}
        if not metrics or metrics.get("source") in ("none", "error"):
            continue
        scored = score_asset(t, asset_type, metrics, ctx)
        d2e = ((ctx.get("earnings_cal") or {}).get(t) or {})
        days_to_earnings = d2e.get("days_until") if isinstance(d2e, dict) else None
        action, gates = decide_action(scored, metrics, days_to_earnings)
        if action == "skip":
            continue
        amount = size_new_idea(metrics, monthly_budget) if action == "buy" else 0
        candidates.append({
            **scored,
            "action": action,
            "conviction": conviction_from_score(scored["score"]),
            "amount_eur": amount,
            "gates_triggered": gates,
            "days_to_earnings": days_to_earnings if isinstance(days_to_earnings, int) else None,
            "is_plan_asset": False,
            "engine": True,
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:top_n]


def build_plan_candidates(
    plan_assets: list[dict],
    market_data: dict[str, dict],
    ctx: dict,
    monthly_budget: float,
    *,
    plan_only: bool = False,
) -> list[dict]:
    """One candidate per plan asset. DCA philosophy: default action is 'buy' at
    the plan weight; the score only modulates conviction and the thesis, never
    skips a DCA reinforcement.
    """
    out: list[dict] = []
    for p in plan_assets:
        ticker = (p.get("ticker") or "").upper()
        if not ticker:
            continue
        asset_type = p.get("asset_type", "stock")
        pct = float(p.get("percentage") or 0)
        metrics = market_data.get(ticker) or market_data.get(ticker.replace("-", ".")) or {}
        scored = score_asset(ticker, asset_type, metrics, ctx) if metrics else {
            "ticker": ticker, "asset_type": asset_type, "score": 50.0,
            "signal_breakdown": {}, "signal_families": [],
        }
        amount = int(round((pct / 100.0) * monthly_budget)) if monthly_budget else 0
        if amount and amount < MIN_BUY_AMOUNT_EUR:
            amount = MIN_BUY_AMOUNT_EUR
        out.append({
            **scored,
            "name": p.get("name") or ticker,
            "action": "buy",
            "conviction": conviction_from_score(scored["score"]),
            "amount_eur": amount,
            "percentage": pct,
            "gates_triggered": [],
            "is_plan_asset": True,
            "engine": True,
        })
    return out


def engine_generate(
    plan_assets: list[dict],
    universe: list[tuple[str, str]],
    market_data: dict[str, dict],
    ctx: dict,
    monthly_budget: float,
    *,
    plan_only: bool = False,
    exclude: Optional[set[str]] = None,
    top_n: int = 12,
) -> dict:
    """Full deterministic pass: plan candidates + ranked new-idea candidates.

    Returns {"plan": [...], "new_ideas": [...]}. In plan_only mode new_ideas is
    still computed (the user may want extras) but the caller decides what to keep.
    """
    plan_tickers = {(p.get("ticker") or "").upper() for p in plan_assets}
    plan_candidates = build_plan_candidates(
        plan_assets, market_data, ctx, monthly_budget, plan_only=plan_only
    )
    new_ideas = rank_universe(
        universe, market_data, ctx, monthly_budget,
        exclude=exclude, plan_tickers=plan_tickers, top_n=top_n,
    )
    return {"plan": plan_candidates, "new_ideas": new_ideas}
