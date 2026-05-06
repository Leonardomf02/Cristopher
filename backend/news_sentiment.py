"""News sentiment classifier with progressive fallback.

Three engines, picked at runtime in this order:
  1. FinBERT (ProsusAI) — if `transformers` + `torch` are installed.
  2. VADER (NLTK) — if `nltk` + `vader_lexicon` are installed.
  3. Loughran-McDonald lexicon — built-in, zero deps. Always available.

Output per headline: {title, label: pos|neg|neutral, score: -1..+1, engine}
We aggregate to a 24h sentiment summary that's added to the LLM prompt.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

logger = logging.getLogger(__name__)

# ── Loughran-McDonald financial lexicon (truncated, high-signal subset) ──
# Positive financial terms
LM_POSITIVE = {
    "beat", "beats", "beating", "exceed", "exceeded", "exceeds", "outperform", "outperforms",
    "surge", "surged", "rally", "rallied", "soar", "soared", "jump", "jumped", "gain", "gains",
    "growth", "growing", "grew", "up", "rise", "rose", "rising", "high", "record", "strong",
    "strongest", "boost", "boosted", "boosts", "advance", "advances", "improve", "improved",
    "improves", "upgrade", "upgraded", "upgrades", "buy", "bullish", "optimistic", "positive",
    "profit", "profits", "profitable", "earnings", "dividend", "dividends", "approval", "approved",
    "win", "winning", "won", "breakthrough", "innovation", "expand", "expansion", "deal", "deals",
    "acquired", "acquires", "acquisition", "partnership", "milestone", "success", "successful",
    "rebound", "rebounded", "recover", "recovered", "recovery", "boom", "rocket", "skyrocket",
    "all-time-high", "ath", "moon", "breakout", "breakouts",
}

# Negative financial terms
LM_NEGATIVE = {
    "miss", "misses", "missed", "fall", "fell", "falling", "drop", "dropped", "dropping", "plunge",
    "plunged", "tumble", "tumbled", "crash", "crashed", "slump", "slumped", "slide", "slid",
    "decline", "declined", "decrease", "decreased", "down", "low", "weak", "weakness", "weaker",
    "loss", "losses", "lose", "lost", "losing", "negative", "warning", "warned", "concern",
    "concerns", "concerning", "fear", "fears", "feared", "panic", "sell-off", "selloff", "bearish",
    "downgrade", "downgraded", "downgrades", "cut", "cuts", "lawsuit", "fraud", "investigation",
    "scandal", "bankruptcy", "default", "defaults", "delisted", "halt", "halted", "ban", "banned",
    "fired", "layoffs", "layoff", "delay", "delayed", "delays", "miss", "shortfall", "underperform",
    "underperforms", "recession", "inflation", "rate-hike", "hike", "hiked", "tightening", "risk",
    "risks", "volatile", "volatility", "uncertainty", "uncertain", "downturn", "correction",
    "bear-market", "crash", "wipeout", "rugpull", "rug-pull", "exploit", "hack", "hacked",
}

# Hedging/uncertainty terms (small negative weight)
LM_UNCERTAIN = {
    "may", "might", "could", "possibly", "perhaps", "uncertainty", "uncertain", "doubt", "doubtful",
    "speculation", "speculative", "appears", "seems", "tentative", "anticipated",
}

_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z\-]+")


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]


# ── Engine 1: FinBERT (lazy import) ────────────────────────────

_finbert_pipeline = None
_finbert_failed = False


def _try_load_finbert():
    """Returns a HuggingFace pipeline or None if torch/transformers missing."""
    global _finbert_pipeline, _finbert_failed
    if _finbert_pipeline is not None or _finbert_failed:
        return _finbert_pipeline
    try:
        from transformers import pipeline  # type: ignore
        _finbert_pipeline = pipeline(
            "sentiment-analysis",
            model="ProsusAI/finbert",
            tokenizer="ProsusAI/finbert",
        )
        logger.info("FinBERT loaded")
        return _finbert_pipeline
    except Exception as e:
        logger.info(f"FinBERT not available, falling back: {e}")
        _finbert_failed = True
        return None


def _classify_finbert(text: str, pipe) -> tuple[str, float]:
    """Returns (label in {pos, neg, neutral}, score in -1..+1)."""
    try:
        res = pipe(text[:512])[0]
        label_raw = res["label"].lower()      # 'positive' | 'negative' | 'neutral'
        conf = float(res["score"])
        if label_raw.startswith("pos"):
            return "pos", conf
        if label_raw.startswith("neg"):
            return "neg", -conf
        return "neutral", 0.0
    except Exception:
        return "neutral", 0.0


# ── Engine 2: VADER (lazy) ─────────────────────────────────────

_vader = None
_vader_failed = False


def _try_load_vader():
    global _vader, _vader_failed
    if _vader is not None or _vader_failed:
        return _vader
    try:
        from nltk.sentiment.vader import SentimentIntensityAnalyzer  # type: ignore
        _vader = SentimentIntensityAnalyzer()
        return _vader
    except Exception:
        _vader_failed = True
        return None


def _classify_vader(text: str, analyzer) -> tuple[str, float]:
    s = analyzer.polarity_scores(text)
    compound = s["compound"]
    if compound >= 0.15:
        return "pos", compound
    if compound <= -0.15:
        return "neg", compound
    return "neutral", compound


# ── Engine 3: Loughran-McDonald (built-in) ─────────────────────

def _classify_lm(text: str) -> tuple[str, float]:
    tokens = _tokenize(text)
    if not tokens:
        return "neutral", 0.0
    pos = sum(1 for t in tokens if t in LM_POSITIVE)
    neg = sum(1 for t in tokens if t in LM_NEGATIVE)
    unc = sum(1 for t in tokens if t in LM_UNCERTAIN)
    # Length-independent: divide by a fixed scale so a 5-word headline with 1 hit
    # gets the same score as a 50-word one with 1 hit. Saturates at 5 hits.
    raw = pos - neg - 0.3 * unc
    score = max(-1.0, min(1.0, raw / 3.0))
    if score >= 0.15:
        return "pos", round(score, 3)
    if score <= -0.15:
        return "neg", round(score, 3)
    return "neutral", round(score, 3)


# ── Public API ─────────────────────────────────────────────────

def classify_headlines(headlines: list[dict]) -> list[dict]:
    """In-place enrich: each item gets {sentiment_label, sentiment_score, sentiment_engine}.
    `headlines` is a list of {title, source, url, ...} dicts.
    """
    fb = _try_load_finbert()
    vd = _try_load_vader() if not fb else None
    engine_name = "finbert" if fb else "vader" if vd else "lm-lexicon"

    for h in headlines:
        text = (h.get("title") or "") + ". " + (h.get("summary") or "")[:200]
        if fb:
            label, score = _classify_finbert(text, fb)
        elif vd:
            label, score = _classify_vader(text, vd)
        else:
            label, score = _classify_lm(text)
        h["sentiment_label"] = label
        h["sentiment_score"] = score
        h["sentiment_engine"] = engine_name
    return headlines


def aggregate_sentiment(headlines: list[dict]) -> dict:
    """Return summary: {avg, pos_n, neg_n, neutral_n, top_pos, top_neg, engine}."""
    if not headlines:
        return {"avg": 0.0, "pos_n": 0, "neg_n": 0, "neutral_n": 0, "engine": None}

    scores = [h.get("sentiment_score", 0) for h in headlines if "sentiment_score" in h]
    if not scores:
        return {"avg": 0.0, "pos_n": 0, "neg_n": 0, "neutral_n": 0, "engine": None}

    pos = [h for h in headlines if h.get("sentiment_label") == "pos"]
    neg = [h for h in headlines if h.get("sentiment_label") == "neg"]
    neu = [h for h in headlines if h.get("sentiment_label") == "neutral"]

    pos_sorted = sorted(pos, key=lambda h: h.get("sentiment_score", 0), reverse=True)
    neg_sorted = sorted(neg, key=lambda h: h.get("sentiment_score", 0))

    return {
        "avg": round(sum(scores) / len(scores), 3),
        "pos_n": len(pos),
        "neg_n": len(neg),
        "neutral_n": len(neu),
        "top_pos": [{"title": h["title"][:120], "source": h["source"], "score": h["sentiment_score"]} for h in pos_sorted[:3]],
        "top_neg": [{"title": h["title"][:120], "source": h["source"], "score": h["sentiment_score"]} for h in neg_sorted[:3]],
        "engine": headlines[0].get("sentiment_engine"),
    }


def filter_by_relevance(headlines: list[dict], top_k: int = 25) -> list[dict]:
    """Keep top-K by |sentiment_score| (most informative), tie-break by recency."""
    scored = [h for h in headlines if "sentiment_score" in h]
    if not scored:
        return headlines[:top_k]
    scored.sort(key=lambda h: abs(h.get("sentiment_score") or 0), reverse=True)
    return scored[:top_k]


def format_sentiment_for_prompt(agg: dict) -> str:
    if not agg or agg.get("engine") is None:
        return "  (sentiment indisponível)"
    avg = agg["avg"]
    tag = " (otimista)" if avg > 0.15 else " (pessimista)" if avg < -0.15 else " (misto)"
    parts = [
        f"score médio {avg:+.2f}{tag}",
        f"+{agg['pos_n']} / -{agg['neg_n']} / ={agg['neutral_n']}",
        f"engine={agg['engine']}",
    ]
    return "  - " + ", ".join(parts)


# ── Sentiment time series (MA7 / MA30 / z-score) ───────────────

import sqlite3
from datetime import datetime, date, timedelta


def persist_daily_sentiment(agg: dict, db_path: str = "cristopher.db") -> None:
    """Upsert today's sentiment aggregate into daily_sentiment table."""
    if not agg or agg.get("engine") is None:
        return
    today = date.today().isoformat()
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("""
            INSERT INTO daily_sentiment (date, avg_score, pos_n, neg_n, neutral_n, engine)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                avg_score=excluded.avg_score,
                pos_n=excluded.pos_n,
                neg_n=excluded.neg_n,
                neutral_n=excluded.neutral_n,
                engine=excluded.engine
        """, (
            today, float(agg.get("avg") or 0),
            int(agg.get("pos_n") or 0), int(agg.get("neg_n") or 0),
            int(agg.get("neutral_n") or 0), agg.get("engine"),
        ))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"persist_daily_sentiment failed: {e}")


def compute_sentiment_delta(db_path: str = "cristopher.db") -> dict:
    """Return MA7 / MA30 / z-score delta for the sentiment time series.

    z-score interpretation:
      |z| > 1.5 → notable regime change
      z > 2     → strong positive swing (potential rally setup)
      z < -2    → strong negative swing (panic / capitulation)
    """
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT date, avg_score FROM daily_sentiment ORDER BY date DESC LIMIT 60"
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"compute_sentiment_delta failed: {e}")
        return {"available": False}

    if len(rows) < 7:
        return {"available": False, "n_days": len(rows)}

    scores = [r[1] for r in rows]   # newest first
    last7 = scores[:7]
    last30 = scores[:30] if len(scores) >= 30 else scores

    ma7 = sum(last7) / len(last7)
    ma30 = sum(last30) / len(last30)
    delta = ma7 - ma30

    # z-score: how many std devs is delta vs the historical (rolling) noise
    if len(last30) >= 10:
        mean30 = ma30
        var30 = sum((s - mean30) ** 2 for s in last30) / (len(last30) - 1)
        std30 = math.sqrt(var30) if var30 > 0 else 0.0
        z = delta / std30 if std30 > 1e-6 else 0.0
    else:
        z = 0.0

    interpretation = (
        "regime change positivo" if z >= 1.5 else
        "regime change negativo" if z <= -1.5 else
        "neutro"
    )

    return {
        "available": True,
        "n_days": len(rows),
        "ma7": round(ma7, 3),
        "ma30": round(ma30, 3),
        "delta": round(delta, 3),
        "z_score": round(z, 2),
        "interpretation": interpretation,
    }


def fetch_sentiment_history(days: int = 60, db_path: str = "cristopher.db") -> list[dict]:
    """Chronological list (oldest → newest) for charting."""
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT date, avg_score, pos_n, neg_n, neutral_n FROM daily_sentiment "
            "ORDER BY date DESC LIMIT ?",
            (days,),
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"fetch_sentiment_history failed: {e}")
        return []
    return [
        {"date": r[0], "avg_score": r[1], "pos_n": r[2], "neg_n": r[3], "neutral_n": r[4]}
        for r in reversed(rows)
    ]


def format_sentiment_delta_for_prompt(delta: dict) -> str:
    if not delta or not delta.get("available"):
        n = (delta or {}).get("n_days", 0)
        return f"  (sentiment delta indisponível — apenas {n}d de histórico, mínimo 7d)"
    z = delta.get("z_score", 0)
    sig = "📈" if z >= 1.5 else "📉" if z <= -1.5 else "—"
    return (
        f"  MA7={delta['ma7']:+.2f}, MA30={delta['ma30']:+.2f}, "
        f"delta={delta['delta']:+.2f}, z-score={z:+.2f} {sig} ({delta['interpretation']})"
    )


# Need math import here for std calc
import math
