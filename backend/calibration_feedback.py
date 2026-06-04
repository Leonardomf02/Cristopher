"""Closes the calibration feedback loop.

The pipeline already stores every suggestion's outcome (`pct_since_generation`)
and computes hit-rates per conviction/context — but nothing consumed those
numbers, so the system never learned. This module turns that history into:

  1. Empirical confidence — blends the model's theoretical confidence with the
     observed hit-rate of similar past suggestions (Bayesian shrinkage, so a tiny
     sample barely moves the prior and a large one dominates).
  2. Empirical conviction→probability — replaces the hardcoded CONVICTION_PROB.
  3. Family weight adjustments — nudges the engine's FAMILY_WEIGHTS toward the
     signal families that have actually been predictive.
  4. A short prompt blurb so the LLM knows its own track record.

All reads are plain sqlite3 (no SQLAlchemy / no router import) to stay free of
circular imports — investment_signals imports this, not the other way around.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)

HIT_THRESHOLD_PCT = 1.0          # cover round-trip fees before counting a "hit"
PRIOR_STRENGTH = 20              # pseudo-observations of the prior (shrinkage)
MIN_N_FOR_ADJUST = 8            # below this, don't trust an empirical bucket

# Theoretical priors (the old hardcoded mapping), in %.
PRIOR_CONVICTION_PCT = {"low": 55.0, "medium": 65.0, "high": 80.0}

# Engine signal families (mirror signal_engine.FAMILY_WEIGHTS keys; "sentimento"
# is market-wide so excluded from per-family attribution).
_FAMILIES = ("técnico", "fundamental", "earnings", "on-chain", "insider")


# ── Outcome loading ─────────────────────────────────────────────

def _load_outcomes(db_path: str = "cristopher.db") -> list[dict]:
    """Flatten every stored suggestion with a known outcome into rows.

    Joins each signal's date against daily_regime so we can bucket by regime.
    """
    try:
        conn = sqlite3.connect(db_path)
        sig_rows = conn.execute(
            "SELECT id, generated_at, suggestions_json FROM investment_signals"
        ).fetchall()
        regime_by_date = {
            r[0]: r[1]
            for r in conn.execute("SELECT date, classification FROM daily_regime").fetchall()
        }
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"_load_outcomes failed: {e}")
        return []

    out: list[dict] = []
    for _id, gen, sj in sig_rows:
        try:
            sugs = json.loads(sj or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        date_key = (gen or "")[:10]
        regime = regime_by_date.get(date_key, "no_data")
        for s in sugs:
            pct = s.get("pct_since_generation")
            if pct is None:
                continue
            out.append({
                "action": (s.get("action") or "").lower(),
                "conviction": (s.get("conviction") or "medium").lower(),
                "asset_type": s.get("asset_type", "stock"),
                "families": s.get("signal_families") or [],
                "regime": regime,
                "pct": pct,
                "hit": 1.0 if (pct or 0) > HIT_THRESHOLD_PCT else 0.0,
            })
    return out


def _rate(rows: list[dict]) -> Optional[float]:
    if not rows:
        return None
    return round(sum(r["hit"] for r in rows) / len(rows) * 100, 1)


# ── Public: aggregate stats ─────────────────────────────────────

def empirical_stats(db_path: str = "cristopher.db") -> dict:
    """Hit-rates + N per bucket. Cheap enough to call once per generation."""
    rows = [r for r in _load_outcomes(db_path) if r["action"] in ("buy", "hold", "watch")]
    if not rows:
        return {"n": 0, "by_conviction": {}, "by_asset_type": {}, "by_family": {}, "overall_rate": None}

    by_conv = {}
    for c in ("low", "medium", "high"):
        rs = [r for r in rows if r["conviction"] == c]
        if rs:
            by_conv[c] = {"n": len(rs), "rate": _rate(rs)}

    by_asset = {}
    for at in {r["asset_type"] for r in rows}:
        rs = [r for r in rows if r["asset_type"] == at]
        by_asset[at] = {"n": len(rs), "rate": _rate(rs)}

    by_family = {}
    for fam in _FAMILIES:
        rs = [r for r in rows if fam in r["families"]]
        if rs:
            by_family[fam] = {"n": len(rs), "rate": _rate(rs)}

    return {
        "n": len(rows),
        "overall_rate": _rate(rows),
        "by_conviction": by_conv,
        "by_asset_type": by_asset,
        "by_family": by_family,
    }


# ── Bayesian blend ──────────────────────────────────────────────

def bayesian_confidence(
    prior_pct: float,
    n: int,
    empirical_rate_pct: Optional[float],
    prior_strength: int = PRIOR_STRENGTH,
) -> float:
    """Shrink the empirical hit-rate toward the prior by sample size.

    (prior_strength·prior + n·empirical) / (prior_strength + n).
    With n=0 returns the prior unchanged; as n grows the empirical dominates.
    """
    if empirical_rate_pct is None or n <= 0:
        return round(prior_pct, 1)
    blended = (prior_strength * prior_pct + n * empirical_rate_pct) / (prior_strength + n)
    return round(blended, 1)


def blend_confidence(sug: dict, stats: dict) -> dict:
    """Mix a suggestion's model confidence with the empirical hit-rate of its
    bucket (conviction first, asset_type as a secondary signal). Records the
    components so the UI can show where the number came from.
    """
    sug = dict(sug)
    model_pct = sug.get("confidence_pct")
    if not isinstance(model_pct, (int, float)):
        return sug

    conv = (sug.get("conviction") or "medium").lower()
    at = sug.get("asset_type", "stock")
    cb = (stats.get("by_conviction") or {}).get(conv) or {}
    ab = (stats.get("by_asset_type") or {}).get(at) or {}

    # Pool the two buckets' evidence (weighted by their N).
    n = (cb.get("n") or 0) + (ab.get("n") or 0)
    rate = None
    if n > 0:
        num = (cb.get("n") or 0) * (cb.get("rate") or 0) + (ab.get("n") or 0) * (ab.get("rate") or 0)
        rate = num / n

    blended = bayesian_confidence(model_pct, n, rate)
    sug["confidence_pct_model"] = round(model_pct, 1)
    sug["confidence_pct"] = blended
    sug["empirical_n"] = n
    sug["empirical_rate"] = round(rate, 1) if rate is not None else None
    return sug


def empirical_conviction_prob(db_path: str = "cristopher.db") -> dict:
    """Replacement for the hardcoded CONVICTION_PROB: {low,medium,high} → prob 0-1,
    blended from history with fallback to the theoretical prior."""
    stats = empirical_stats(db_path)
    by_conv = stats.get("by_conviction") or {}
    out = {}
    for c, prior in PRIOR_CONVICTION_PCT.items():
        bucket = by_conv.get(c) or {}
        blended = bayesian_confidence(prior, bucket.get("n") or 0, bucket.get("rate"))
        out[c] = round(blended / 100.0, 3)
    return out


# ── Family weight adjustments for the engine ────────────────────

def family_weight_adjustments(db_path: str = "cristopher.db") -> dict:
    """Multiplier per family vs the overall hit-rate. Only buckets with enough
    history move; everything else stays at 1.0 (neutral). Clamped to [0.6, 1.4]
    so a noisy bucket can't dominate."""
    stats = empirical_stats(db_path)
    overall = stats.get("overall_rate")
    out = {fam: 1.0 for fam in _FAMILIES}
    if not overall or overall <= 0:
        return out
    for fam, b in (stats.get("by_family") or {}).items():
        if (b.get("n") or 0) < MIN_N_FOR_ADJUST or b.get("rate") is None:
            continue
        ratio = b["rate"] / overall
        out[fam] = round(max(0.6, min(1.4, ratio)), 3)
    return out


def adjusted_family_weights(base: dict, db_path: str = "cristopher.db") -> dict:
    """Apply family_weight_adjustments to a base FAMILY_WEIGHTS dict (renormalized)."""
    adj = family_weight_adjustments(db_path)
    out = {f: base.get(f, 0.0) * adj.get(f, 1.0) for f in base}
    total = sum(out.values())
    if total > 0:
        out = {f: round(w / total * sum(base.values()), 4) for f, w in out.items()}
    return out


# ── Prompt blurb ────────────────────────────────────────────────

def calibration_summary_for_prompt(db_path: str = "cristopher.db") -> str:
    """2-3 lines giving the LLM its own track record so it can self-correct."""
    stats = empirical_stats(db_path)
    if not stats.get("n"):
        return "  (sem histórico de calibração suficiente — ainda a recolher outcomes)"
    lines = [f"  Histórico: {stats['n']} sugestões avaliadas, hit-rate global {stats.get('overall_rate')}% (>+{HIT_THRESHOLD_PCT:.0f}%)."]
    cv = stats.get("by_conviction") or {}
    conv_bits = [f"{c}={cv[c]['rate']}% (n={cv[c]['n']})" for c in ("high", "medium", "low") if c in cv]
    if conv_bits:
        lines.append("  Por convicção: " + ", ".join(conv_bits) + ". Sê conservador onde o hit-rate < convicção implícita.")
    return "\n".join(lines)
