"""Tests for the deterministic signal engine.

Runs standalone (no pytest needed):  python tests/test_signal_engine.py
Also discoverable by pytest if installed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import signal_engine as se


# ── Fixtures ────────────────────────────────────────────────────

def _metrics(**over):
    base = {
        "ticker": "TEST",
        "source": "yahoo",
        "current_price": 100.0,
        "rsi_14": 50.0,
        "sma_200": 90.0,
        "momentum_pctile": 60,
        "realized_vol_252_pct": 25.0,
        "atr_14": 2.0,
    }
    base.update(over)
    return base


def _ctx(**over):
    base = {
        "family_weights": se.FAMILY_WEIGHTS,
        "fundamentals": {},
        "earnings_momentum": {},
        "earnings_cal": {},
        "insider": {},
        "onchain": {},
        "funding_btc": None,
        "funding_eth": None,
        "sentiment_agg": None,
        "sentiment_delta": None,
        "regime": {"available": True, "p_risk_off": 0.5},
    }
    base.update(over)
    return base


# ── Reproducibility ─────────────────────────────────────────────

def test_score_is_reproducible():
    m = _metrics()
    a = se.score_asset("AAPL", "stock", m, _ctx())
    b = se.score_asset("AAPL", "stock", m, _ctx())
    assert a == b, "same input must yield identical score"


# ── Gates ───────────────────────────────────────────────────────

def test_rsi_overbought_never_buys():
    # Strong score but RSI 78 → must not be a buy
    m = _metrics(rsi_14=78.0, momentum_pctile=95)
    ctx = _ctx(
        fundamentals={"TEST": {"available": True, "roe_ttm": 0.35, "net_margin": 0.25, "debt_equity": 0.2, "pe_ttm": 18}},
        earnings_momentum={"TEST": {"signal": "strong_momentum", "consecutive_beats": 4, "avg_surprise_pct_4q": 6}},
    )
    scored = se.score_asset("TEST", "stock", m, ctx)
    action, gates = se.decide_action(scored, m, None)
    assert action != "buy", f"RSI>70 should block buy, got {action}"
    assert any(g["gate"] == "rsi_overbought" for g in gates)


def test_earnings_proximity_blocks_buy():
    m = _metrics(rsi_14=45.0, momentum_pctile=90)
    ctx = _ctx(
        fundamentals={"TEST": {"available": True, "roe_ttm": 0.35, "net_margin": 0.25, "debt_equity": 0.2, "pe_ttm": 15}},
        earnings_momentum={"TEST": {"signal": "strong_momentum", "consecutive_beats": 4, "avg_surprise_pct_4q": 7}},
    )
    scored = se.score_asset("TEST", "stock", m, ctx)
    action, gates = se.decide_action(scored, m, days_to_earnings=5)
    assert action == "watch", f"earnings in 5d should force watch, got {action}"
    assert any(g["gate"] == "earnings_too_close" for g in gates)


def test_single_family_blocks_buy():
    # Only technical contributes (no fundamentals/earnings) → <2 families → no buy
    m = _metrics(rsi_14=25.0, momentum_pctile=99, sma_200=80.0)
    scored = se.score_asset("LONE", "stock", m, _ctx())
    action, gates = se.decide_action(scored, m, None)
    if action == "buy":
        raise AssertionError("single-family thesis must not buy")


# ── Regime overlay ──────────────────────────────────────────────

def test_riskoff_shrinks_crypto():
    m = _metrics(rsi_14=40.0, momentum_pctile=70)
    on = {"btc_cm_mvrv": 1.5}
    risk_on = se.score_asset("BTC", "crypto", m, _ctx(onchain=on, regime={"available": True, "p_risk_off": 0.15}))
    risk_off = se.score_asset("BTC", "crypto", m, _ctx(onchain=on, regime={"available": True, "p_risk_off": 0.90}))
    assert risk_off["score"] < risk_on["score"], "risk-off must lower a bullish crypto score"


def test_regime_multiplier_bounds():
    for p in (0.0, 0.25, 0.5, 0.75, 1.0):
        mlt = se.regime_multiplier("crypto", None, {"available": True, "p_risk_off": p})
        assert 0.6 <= mlt <= 1.3


# ── Sizing ──────────────────────────────────────────────────────

def test_sizing_respects_min_and_budget():
    budget = 300.0
    # very high vol → tiny vol-target, but floored at MIN
    amt = se.size_new_idea(_metrics(realized_vol_252_pct=200.0), budget)
    assert amt >= se.MIN_BUY_AMOUNT_EUR
    assert amt <= budget


def test_plan_candidate_is_always_buy_at_weight():
    plan = [{"ticker": "VUAA", "name": "S&P 500", "asset_type": "etf", "percentage": 33}]
    md = {"VUAA": _metrics(ticker="VUAA", rsi_14=75.0)}  # overbought, but DCA buys anyway
    cands = se.build_plan_candidates(plan, md, _ctx(), 300.0)
    assert len(cands) == 1
    assert cands[0]["action"] == "buy"
    assert cands[0]["amount_eur"] == round(0.33 * 300)


def test_rank_excludes_plan_and_rejected():
    universe = [("AAPL", "stock"), ("NVDA", "stock"), ("MSFT", "stock")]
    md = {t: _metrics(ticker=t, rsi_14=40, momentum_pctile=80) for t, _ in universe}
    ctx = _ctx(
        fundamentals={t: {"available": True, "roe_ttm": 0.3, "net_margin": 0.2, "debt_equity": 0.3, "pe_ttm": 20} for t, _ in universe},
        earnings_momentum={t: {"signal": "positive_drift", "consecutive_beats": 2, "avg_surprise_pct_4q": 3} for t, _ in universe},
    )
    out = se.rank_universe(universe, md, ctx, 300.0, exclude={"NVDA"}, plan_tickers={"MSFT"})
    tickers = {c["ticker"] for c in out}
    assert "NVDA" not in tickers and "MSFT" not in tickers
    assert "AAPL" in tickers


# ── Runner ──────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
