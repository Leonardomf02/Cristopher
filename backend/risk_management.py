"""Risk overlays applied to every BUY suggestion before storing.

Adds the following to each suggestion:
  - stop_loss_price          ATR-based: entry − 2 × ATR(14)
  - stop_loss_pct            % below entry where stop sits
  - suggested_amount_eur     vol-targeted size (target_vol / realized_vol × budget)
  - sizing_warning           if LLM amount differs ≥30% from suggested size
  - position_after_buy_pct   share of total portfolio if executed
  - max_position_warning     if would push single name above MAX_SINGLE_PCT
  - risk_warnings            human-readable list of risk concerns

These don't reject suggestions — they annotate them. The user keeps full agency.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Risk parameters (sensible defaults for a long-term DCA portfolio)
TARGET_PORTFOLIO_VOL_PCT = 15.0    # annualized target volatility
MAX_SINGLE_NAME_PCT = 12.0          # max % of portfolio in any single position
ATR_STOP_MULTIPLIER = 2.0           # stop = entry - 2*ATR
MAX_HIGH_VOL_PCT = 80.0             # if vol >80%, treat as crypto-like (size differently)


def _atr_stop_loss(entry_price: Optional[float], atr_14: Optional[float]) -> tuple[Optional[float], Optional[float]]:
    """Returns (stop_price, stop_pct_below_entry). None if missing inputs."""
    if not entry_price or not atr_14 or atr_14 <= 0:
        return None, None
    stop = entry_price - ATR_STOP_MULTIPLIER * atr_14
    if stop <= 0:
        return None, None
    pct = round((entry_price - stop) / entry_price * 100, 2)
    return round(stop, 4), pct


def _vol_targeted_size(realized_vol_pct: Optional[float], monthly_budget: float, max_pct_of_budget: float = 1.0) -> Optional[float]:
    """How many € to allocate so that this position's vol contribution = target.

    Formula: amount = (target_vol / realized_vol) * budget
    Caps the result at max_pct_of_budget * budget to avoid all-in calls.
    """
    if not realized_vol_pct or realized_vol_pct <= 0 or monthly_budget <= 0:
        return None
    raw = (TARGET_PORTFOLIO_VOL_PCT / realized_vol_pct) * monthly_budget
    capped = min(raw, monthly_budget * max_pct_of_budget)
    return round(max(capped, 5.0), 2)   # never suggest <5€


def _build_risk_warnings(sug: dict, metrics: dict, total_portfolio: float) -> list[str]:
    warnings: list[str] = []

    rsi = metrics.get("rsi_14")
    if sug.get("action") == "buy" and rsi is not None and rsi > 75:
        warnings.append(f"RSI {rsi:.1f} — entrar agora pode apanhar topo")

    vol = metrics.get("realized_vol_252_pct")
    if vol and vol > MAX_HIGH_VOL_PCT:
        warnings.append(f"vol anualizada {vol:.0f}% — high-risk")

    # 52w position
    cp = metrics.get("current_price")
    hi52 = metrics.get("high_52w")
    if cp and hi52 and cp >= hi52 * 0.97:
        warnings.append("a <3% do high 52w — momentum pode reverter")

    # SMA 200 trend filter
    sma200 = metrics.get("sma_200")
    if sma200 and cp and cp < sma200 and sug.get("action") == "buy":
        warnings.append("preço abaixo SMA200 — contrarian buy, downtrend de fundo")

    # Position concentration
    amount = sug.get("amount_eur")
    if isinstance(amount, (int, float)) and total_portfolio > 0:
        pos_after = amount / (total_portfolio + amount) * 100
        if pos_after > MAX_SINGLE_NAME_PCT:
            warnings.append(f"esta compra leva {sug['ticker']} acima de {MAX_SINGLE_NAME_PCT:.0f}% do portfolio")

    return warnings


def apply_risk_overlays(
    suggestions: list[dict],
    market_data: dict[str, dict],
    monthly_budget: float,
    total_portfolio_value: float,
) -> list[dict]:
    """Annotates each suggestion with stop-loss, sizing, position warnings, risk_warnings."""
    out = []
    for sug in suggestions:
        if not isinstance(sug, dict):
            continue
        sug = dict(sug)
        ticker = (sug.get("ticker") or "").upper()
        action = (sug.get("action") or "").lower()
        metrics = market_data.get(ticker, {}) if market_data else {}

        # Use price_at_generation (already populated by enrich step) or current_price as entry
        entry = sug.get("price_at_generation") or sug.get("current_price") or metrics.get("current_price")
        atr = metrics.get("atr_14")
        stop, stop_pct = _atr_stop_loss(entry, atr)
        if stop is not None:
            sug["stop_loss_price"] = stop
            sug["stop_loss_pct"] = stop_pct

        # Suggested vol-targeted amount (only for buys)
        if action == "buy":
            vol = metrics.get("realized_vol_252_pct")
            suggested = _vol_targeted_size(vol, monthly_budget) if vol else None
            if suggested is not None:
                sug["suggested_amount_eur"] = suggested
                # Compare with what the LLM suggested. Tolerance scales with vol —
                # crypto-like (vol > 50%) gets more leeway than low-vol ETFs.
                amount = sug.get("amount_eur")
                if isinstance(amount, (int, float)) and amount > 0 and suggested > 0:
                    if vol is None:
                        threshold = 0.5
                    elif vol < 20:
                        threshold = 0.30
                    elif vol < 50:
                        threshold = 0.50
                    else:
                        threshold = 0.70
                    diff_ratio = abs(amount - suggested) / suggested
                    if diff_ratio > threshold:
                        if amount > suggested * (1 + threshold):
                            sug["sizing_warning"] = (
                                f"LLM sugere {amount:.0f}€ (>{int(threshold * 100)}% acima do vol-target {suggested:.0f}€) — assume mais risco"
                            )
                        elif amount < suggested * (1 - threshold):
                            sug["sizing_warning"] = (
                                f"LLM sugere {amount:.0f}€ (>{int(threshold * 100)}% abaixo do vol-target {suggested:.0f}€) — pode estar a sub-investir"
                            )

        # Position concentration after hypothetical buy
        amount = sug.get("amount_eur")
        if isinstance(amount, (int, float)) and total_portfolio_value > 0 and action == "buy":
            pos_after = amount / (total_portfolio_value + amount) * 100
            sug["position_after_buy_pct"] = round(pos_after, 2)
            if pos_after > MAX_SINGLE_NAME_PCT:
                sug["max_position_warning"] = True

        # Risk warnings (always evaluated)
        warnings = _build_risk_warnings(sug, metrics, total_portfolio_value)
        if warnings:
            sug["risk_warnings"] = warnings

        out.append(sug)
    return out
