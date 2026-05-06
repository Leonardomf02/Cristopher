"""Quality guards run on every suggestion the LLM produces.

These don't reject suggestions — they annotate them with `quality_flags`
so the UI can surface trust/risk signals. The user keeps full agency.

Checks:
  - ticker_valid:           ticker resolves to a real symbol
  - numbers_grounded:       numbers cited in the thesis appear in input context
  - no_contradictions:      action vs technicals don't contradict
  - conviction_supported:   "high" only if thesis cites concrete data
  - amount_reasonable:      amount_eur fits within monthly budget
  - amount_above_min:       buy amount >= MIN_BUY_AMOUNT_EUR (forçado)
  - confidence_pct:         percentagem real calculada com breakdown
"""
from __future__ import annotations

import re
import logging
from typing import Iterable

from market_data import get_quick_price

logger = logging.getLogger(__name__)

# Mínimo prático para uma compra (corretoras europeias têm fees fixos / mínimos).
MIN_BUY_AMOUNT_EUR = 25

# Words that contradict each action when paired in the same thesis.
ACTION_CONTRADICTIONS: dict[str, list[str]] = {
    "buy": [
        r"\boverbought\b", r"\bsobrecomprad",
        # RSI clearly in overbought territory: 70-99
        r"RSI\s*[>≥]\s*(?:7[0-9]|8[0-9]|9\d)\b",
        r"RSI\s*(?:7[0-9]|8[0-9]|9\d)(?:\.\d+)?\s*\(sobrec",
        r"\bdowntrend\b", r"tendência de queda",
        r"\bbearish\b", r"\bsobrevalorizado\b",
        r"abaixo da SMA\s*200",
    ],
    "reduce": [
        r"\boversold\b", r"\bsobrevendid",
        # RSI clearly in oversold territory: 0-29
        r"RSI\s*[<≤]\s*(?:[12]?\d|29)\b",
        r"\bbullish\b",
        r"\buptrend\b", r"tendência de subida",
        r"\bsubvalorizado\b", r"acima da SMA\s*50",
    ],
    "sell": [
        r"\boversold\b", r"\bbullish\b", r"\buptrend\b", r"acima da SMA\s*50",
    ],
}


def _extract_numbers(text: str) -> list[str]:
    """Extract candidate factual numbers from a thesis (skips common date/year noise)."""
    if not text:
        return []
    # Match: 70.1, 32.4%, +15.4%, 25.4% vs 33%, etc.
    pattern = r"[+-]?\d{1,3}(?:[.,]\d+)?%?"
    matches = re.findall(pattern, text)
    cleaned = []
    for m in matches:
        m = m.strip()
        if not m:
            continue
        # Filter pure years (1900-2099) — those aren't factual claims
        if re.fullmatch(r"20[0-9]{2}|19[0-9]{2}", m):
            continue
        cleaned.append(m)
    return cleaned


def _to_float(s: str) -> float | None:
    """Parse a number that may use either ',' or '.' as decimal. Returns None if invalid.
    Strips %, +, − signs."""
    if not s:
        return None
    cleaned = s.strip().replace("%", "").replace("+", "").replace("−", "-")
    # If there's both '.' and ',', assume European: '.' is thousands sep.
    if "." in cleaned and "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        # Single comma → decimal (PT format)
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def check_numbers_grounded(thesis: str, context_blob: str) -> tuple[bool, list[str]]:
    """Returns (ok, list of unverified numbers). 'ok' = at least 60% match.

    Compare numerically (with 1% tolerance) so PT vs EN decimal separators
    don't cause spurious mismatches.
    """
    numbers = _extract_numbers(thesis)
    if not numbers:
        return True, []

    # Pre-extract numerical tokens from the context for cheaper lookup.
    ctx_numbers_raw = re.findall(r"[+-]?\d{1,3}(?:[.,]\d+)?", context_blob)
    ctx_floats = []
    for c in ctx_numbers_raw:
        f = _to_float(c)
        if f is not None:
            ctx_floats.append(f)

    unverified = []
    matched = 0
    for n in numbers:
        f = _to_float(n)
        if f is None:
            unverified.append(n)
            continue
        # Match if any context number is within 1% tolerance (or exact for small ints)
        tol = max(abs(f) * 0.01, 0.01)
        if any(abs(f - cf) <= tol for cf in ctx_floats):
            matched += 1
        else:
            unverified.append(n)

    ratio = matched / len(numbers) if numbers else 1.0
    return ratio >= 0.6, unverified


def check_contradictions(action: str, thesis: str) -> list[str]:
    """Return regex patterns that fired contradicting the action."""
    patterns = ACTION_CONTRADICTIONS.get(action.lower(), [])
    hits = []
    for p in patterns:
        if re.search(p, thesis, re.IGNORECASE):
            hits.append(p)
    return hits


def check_conviction_supported(conviction: str, thesis: str) -> bool:
    """High conviction must cite at least 1 number AND have a thesis ≥120 chars."""
    if conviction != "high":
        return True
    nums = _extract_numbers(thesis)
    return len(nums) >= 1 and len(thesis or "") >= 120


def check_ticker_valid(ticker: str, asset_type: str | None) -> bool:
    """Verify via Yahoo / CoinGecko that the ticker is real."""
    if not ticker:
        return False
    try:
        price = get_quick_price(ticker, asset_type)
        return price is not None and price > 0
    except Exception as e:
        logger.debug(f"Ticker validation failed for {ticker}: {e}")
        return False


_SOURCE_PATTERN = re.compile(
    r"\b(coindesk|cointelegraph|decrypt|yahoo|bloomberg|reuters|fed|ecb|forbes|"
    r"cnbc|seekingalpha|investing|marketwatch|finnhub|notícia|news|sentiment)\b",
    re.IGNORECASE,
)
_METRIC_PATTERN = re.compile(
    r"\b(rsi|sma|ema|momentum|p/?e|p/?b|roe|roi|debt|atr|macd|fng|fear|greed|"
    r"vix|breakeven|funding|mvrv|earnings|guidance|cash[-\s]?flow|ebitda|"
    r"revenue|margin|drawdown|volatil|uptrend|downtrend|breakout|oversold|overbought)\b",
    re.IGNORECASE,
)

# Famílias de sinais — uma tese forte cruza ≥2 destas. Usado para evitar que a IA
# sustente uma sugestão num só sinal técnico (ex: só RSI) ignorando todo o resto.
_SIGNAL_FAMILIES: dict[str, re.Pattern[str]] = {
    "técnico": re.compile(
        r"\b(rsi|sma|ema|macd|atr|breakout|breakdown|momentum|oversold|"
        r"overbought|sobreven[dt]id|sobrecomprad|uptrend|downtrend|tendência|"
        r"resistência|suporte|range\s*52w?|52[-\s]?week)\b",
        re.IGNORECASE,
    ),
    "fundamental": re.compile(
        r"\b(p/?e|p/?b|roe|roi|eps|revenue|receita|guidance|"
        r"earnings\s+(?:beat|surprise|miss)|"
        r"\d+\s*beats?(?:\s*consecut)?|surprise\s*(?:médio|positivo|de)|surprise\s*[+\-−]?\d|"
        r"margin|margem|cash[-\s]?flow|ebitda|debt|dívida|valuation|"
        r"fundamentais|fundamentals|free[-\s]?cash[-\s]?flow|fcf)\b",
        re.IGNORECASE,
    ),
    "sentimento": re.compile(
        r"\b(coindesk|cointelegraph|decrypt|yahoo|bloomberg|reuters|forbes|cnbc|"
        r"seekingalpha|marketwatch|finnhub|notíci|news|sentiment(?:o)?|"
        r"manchete|headline)\b",
        re.IGNORECASE,
    ),
    "macro": re.compile(
        r"\b(vix|fed\b|ecb\b|fng|fear\s*&?\s*greed|risk[-\s]?(?:on|off)|"
        r"regime|inflação|inflation|cpi|powell|lagarde|yields|treasury|10y|"
        r"taxa\s+de\s+juro|rate\s*cut|rate\s*hike)\b",
        re.IGNORECASE,
    ),
    "on-chain": re.compile(
        r"\b(funding|on[-\s]?chain|mvrv|nupl|whale|exchange[-\s]?flow|"
        r"hashrate|stablecoin|usdc|usdt|tether)\b",
        re.IGNORECASE,
    ),
    "insider": re.compile(
        r"\b(insider|cluster\s+buy|cluster\s+sell|form\s*4|10b5[-\s]?1|"
        r"executive\s+buy|ceo\s+buy|cfo\s+buy)\b",
        re.IGNORECASE,
    ),
}


def detect_signal_families(thesis: str) -> set[str]:
    """Devolve as famílias de sinais distintas citadas na tese."""
    if not thesis:
        return set()
    found: set[str] = set()
    for fam, pattern in _SIGNAL_FAMILIES.items():
        if pattern.search(thesis):
            found.add(fam)
    return found


def compute_confidence(
    *,
    conviction: str,
    thesis: str,
    flags: list[str],
    grounded_ratio: float,
    has_contradiction: bool,
    is_auto_filled: bool,
    n_families: int = 0,
) -> tuple[float, dict]:
    """Calcula confiança real (0-99%) com breakdown por componente.

    Componentes:
      - convicção (40%): base atribuída pela IA, ajustada pela robustez da thesis.
      - fundamentação (30%): números factuais verificados + métricas concretas + fontes citadas.
      - consistência (30%): ausência de contradições e flags graves.

    Nunca devolve 100% — não há certeza absoluta em mercados.
    Auto-filled (fallback) fica capado a ~30%.
    """
    conv = (conviction or "").lower()
    base_conv = {"high": 85.0, "medium": 60.0, "low": 35.0}.get(conv, 40.0)

    # Convicção: bonus por thesis substanciada, penalização por curta/vazia
    thesis_len = len(thesis or "")
    if thesis_len >= 180:
        base_conv += 5
    elif thesis_len < 60:
        base_conv -= 10
    if "weak_conviction" in [f.split(":")[0] for f in flags]:
        base_conv -= 10
    score_conv = max(0.0, min(95.0, base_conv))

    # Fundamentação: números verificados + densidade de métricas + fontes citadas
    # + diversidade de famílias de sinais (técnico+fundamental+sentimento+macro+...).
    nums = _extract_numbers(thesis)
    n_metrics = len(_METRIC_PATTERN.findall(thesis))
    has_source = bool(_SOURCE_PATTERN.search(thesis))

    # grounded_ratio: 0..1 de quantos números do thesis batem com o contexto
    fund = 20.0
    if nums:
        fund += min(35.0, grounded_ratio * 35.0)  # até +35 por verificação numérica
    fund += min(15.0, n_metrics * 4.0)  # até +15 por densidade de métricas
    if has_source:
        fund += 8.0
    # Diversidade de famílias: 1 família = sinal isolado (penaliza), ≥3 = robusto.
    if n_families >= 3:
        fund += 20.0
    elif n_families == 2:
        fund += 10.0
    elif n_families <= 1:
        fund -= 15.0  # tese mono-dimensional: castigo pesado
    if "unverified_numbers" in [f.split(":")[0] for f in flags]:
        fund -= 15.0
    if "single_dimension" in [f.split(":")[0] for f in flags]:
        fund -= 5.0  # extra além da penalização já aplicada por n_families
    score_fund = max(0.0, min(95.0, fund))

    # Consistência: penaliza contradições/flags graves
    cons = 90.0
    if has_contradiction:
        cons -= 40.0
    flag_keys = {f.split(":")[0] for f in flags}
    if "ticker_invalid" in flag_keys:
        cons -= 60.0
    if "amount_over_budget" in flag_keys:
        cons -= 10.0
    if "amount_too_small" in flag_keys or "amount_raised_to_min" in flag_keys:
        cons -= 5.0
    score_cons = max(0.0, min(95.0, cons))

    pct = 0.4 * score_conv + 0.3 * score_fund + 0.3 * score_cons

    # Cap auto-filled fallbacks (a IA não deu leitura específica)
    if is_auto_filled:
        pct = min(pct, 30.0)

    pct = max(0.0, min(99.0, pct))
    breakdown = {
        "convicção": round(score_conv, 1),
        "fundamentação": round(score_fund, 1),
        "consistência": round(score_cons, 1),
    }
    return round(pct, 1), breakdown


def validate_suggestions(
    suggestions: list[dict],
    context_blob: str,
    monthly_budget: float | None = None,
) -> list[dict]:
    """Annotate each suggestion with `quality_flags` and `confidence_pct`.

    Possible flags:
      - "ticker_invalid"
      - "unverified_numbers:<n,m,...>"
      - "contradiction:<patterns>"
      - "weak_conviction"          (high conv but thesis lacks data)
      - "amount_over_budget"
      - "amount_raised_to_min:<original>"  (montante elevado para o mínimo prático)
    """
    out = []
    for sug in suggestions:
        if not isinstance(sug, dict):
            continue
        sug = dict(sug)
        flags: list[str] = []

        ticker = (sug.get("ticker") or "").strip().upper()
        action = (sug.get("action") or "").strip().lower()
        conviction = (sug.get("conviction") or "").strip().lower()
        thesis = sug.get("thesis") or ""
        amount = sug.get("amount_eur")

        if not check_ticker_valid(ticker, sug.get("asset_type")):
            flags.append("ticker_invalid")

        ok_nums, unverified = check_numbers_grounded(thesis, context_blob)
        # grounded_ratio: aproveita o cálculo já feito para alimentar o confidence
        nums_total = len(_extract_numbers(thesis))
        grounded_ratio = (
            (nums_total - len(unverified)) / nums_total if nums_total else 0.5
        )
        if not ok_nums and unverified:
            flags.append(f"unverified_numbers:{','.join(unverified[:3])}")

        contradictions = check_contradictions(action, thesis)
        if contradictions:
            flags.append("contradiction")

        # Diversidade de sinais: tese forte cruza ≥2 famílias (técnico, fundamental,
        # sentimento, macro, on-chain, insider). Mono-dimensional = ruído.
        families = detect_signal_families(thesis)
        sug["signal_families"] = sorted(families)
        if action == "buy" and len(families) < 2:
            flags.append(f"single_dimension:{','.join(sorted(families)) or 'none'}")

        if not check_conviction_supported(conviction, thesis):
            flags.append("weak_conviction")
            # Auto-downgrade to medium so the UI doesn't lie
            sug["conviction"] = "medium"
            sug["original_conviction"] = "high"
            conviction = "medium"

        if (
            monthly_budget is not None
            and isinstance(amount, (int, float))
            and amount > monthly_budget
        ):
            flags.append("amount_over_budget")

        # Mínimo prático: <25€ num "buy" não é investível.
        # Eleva para o mínimo (capped pelo budget) e marca a flag para visibilidade.
        if action == "buy" and isinstance(amount, (int, float)) and 0 < amount < MIN_BUY_AMOUNT_EUR:
            original = amount
            new_amount = MIN_BUY_AMOUNT_EUR
            if monthly_budget is not None:
                new_amount = min(new_amount, float(monthly_budget))
            sug["amount_eur"] = new_amount
            sug["original_amount_eur"] = original
            flags.append(f"amount_raised_to_min:{original:.0f}€→{new_amount:.0f}€")

        sug["quality_flags"] = flags

        # Confidence real (0-99%) + breakdown — substitui a string conviction como fonte de verdade
        pct, breakdown = compute_confidence(
            conviction=conviction,
            thesis=thesis,
            flags=flags,
            grounded_ratio=grounded_ratio,
            has_contradiction=bool(contradictions),
            is_auto_filled=bool(sug.get("auto_filled")),
            n_families=len(families),
        )
        sug["confidence_pct"] = pct
        sug["confidence_breakdown"] = breakdown

        out.append(sug)
    return out


def summarize_flags(suggestions: Iterable[dict]) -> dict:
    """Aggregate counts across a signal's suggestions for quick UI badge."""
    counts: dict[str, int] = {}
    total = 0
    for s in suggestions:
        total += 1
        for f in s.get("quality_flags") or []:
            key = f.split(":")[0]
            counts[key] = counts.get(key, 0) + 1
    return {"total": total, "counts": counts}
