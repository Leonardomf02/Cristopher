"""Daily AI investment signals.

Reads market news from public RSS feeds, fetches sentiment indices,
combines with the user's portfolio, and asks the iaedu.pt agent for
actionable suggestions. Stored in DB so we keep history of past calls.
"""
from __future__ import annotations

import re
import ssl
import json
import hashlib
import logging
import asyncio
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import httpx
import feedparser
import aiohttp

from database import get_db
from models import (
    InvestmentSignal, InvestmentPosition, InvestmentTransaction,
    InvestmentAllocation, InvestmentMonthlyPlan, PlanAnalysisLatest,
)
from market_data import (
    fetch_metrics_batch, format_metrics_for_prompt, get_quick_price,
    compute_factor_panel,
)
from macro_data import fetch_macro_snapshot, format_macro_for_prompt
from signal_validation import validate_suggestions, summarize_flags
from onchain_data import (
    fetch_onchain_snapshot, format_onchain_for_prompt,
    persist_daily_funding, compute_funding_persistence, format_funding_persistence_for_prompt,
    fetch_funding_history,
)
from insider_data import fetch_insider_batch, format_insider_for_prompt, TICKER_TO_CIK
from news_sentiment import (
    classify_headlines, aggregate_sentiment, filter_by_relevance, format_sentiment_for_prompt,
    persist_daily_sentiment, compute_sentiment_delta, format_sentiment_delta_for_prompt,
    fetch_sentiment_history,
)
from fundamentals_data import fetch_fundamentals_batch, format_fundamentals_for_prompt, is_enabled as fmp_enabled
from earnings_data import (
    fetch_earnings_for_tickers, format_earnings_for_prompt, is_enabled as finnhub_enabled,
    fetch_earnings_momentum, format_earnings_momentum_for_prompt,
)
from regime_data import (
    fetch_regime_snapshot, format_regime_for_prompt,
    persist_daily_regime, fetch_regime_history,
)
from risk_management import apply_risk_overlays
from notifier import notify, telegram_enabled
from cache import cache_stats, cache_invalidate

from ai_config import AI_API_URL, AI_API_KEY, AI_CHANNEL_ID

router = APIRouter(prefix="/api/investments/signals", tags=["Investment Signals"])
logger = logging.getLogger(__name__)

PROMPT_VERSION = "v7-decision-gates"   # bump when SYSTEM_PROMPT or _build_user_prompt changes shape

MIN_BUY_AMOUNT_EUR = 25  # corretoras europeias têm mínimos práticos; <25€ não é investível


# ── News sources (RSS) ──────────────────────────────────────────

NEWS_FEEDS = [
    # General markets
    ("Yahoo Finance",      "https://finance.yahoo.com/news/rssindex"),
    ("MarketWatch",        "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("CNBC Markets",       "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"),
    ("Investing.com",      "https://www.investing.com/rss/news_25.rss"),
    ("Seeking Alpha",      "https://seekingalpha.com/market_currents.xml"),
    # Macro / central banks (high-impact catalysts)
    ("Fed Press",          "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    ("ECB Press",          "https://www.ecb.europa.eu/rss/press.html"),
    # Crypto
    ("CoinDesk",           "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph",      "https://cointelegraph.com/rss"),
    ("Decrypt",            "https://decrypt.co/feed"),
]

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Cristopher/1.0"

FNG_CRYPTO_URL = "https://api.alternative.me/fng/?limit=1"
CNN_FNG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

# In-memory health tracking — cleared on restart, good enough for diagnostics
_FEED_HEALTH: dict[str, dict] = {}


def _fetch_feed(name: str, url: str, limit: int = 8) -> list[dict]:
    try:
        r = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=10, follow_redirects=True)
        r.raise_for_status()
        parsed = feedparser.parse(r.content)
        items = []
        for entry in parsed.entries[:limit]:
            items.append({
                "title": entry.get("title", "").strip(),
                "url": entry.get("link", ""),
                "source": name,
                "published": entry.get("published", ""),
                "summary": (entry.get("summary", "") or "")[:400],
            })
        _FEED_HEALTH[name] = {
            "ok": True,
            "count": len(items),
            "last_check": datetime.now().isoformat(timespec="seconds"),
            "error": None,
        }
        return items
    except Exception as e:
        _FEED_HEALTH[name] = {
            "ok": False,
            "count": 0,
            "last_check": datetime.now().isoformat(timespec="seconds"),
            "error": str(e)[:200],
        }
        logger.warning(f"Feed {name} failed: {e}")
        return []


def collect_news(per_feed: int = 8) -> list[dict]:
    """Fetch all RSS feeds in parallel threads."""
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(NEWS_FEEDS)) as ex:
        futures = [ex.submit(_fetch_feed, name, url, per_feed) for name, url in NEWS_FEEDS]
        for f in futures:
            results.extend(f.result() or [])
    return results


def collect_sentiment() -> dict:
    """Fetch sentiment indices: crypto F&G + CNN equity F&G."""
    out: dict = {}

    # Crypto Fear & Greed
    try:
        r = httpx.get(FNG_CRYPTO_URL, timeout=8)
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                out["crypto_fng"] = {
                    "value": int(data[0]["value"]),
                    "classification": data[0]["value_classification"],
                }
    except Exception as e:
        logger.warning(f"Crypto FNG fetch failed: {e}")

    # CNN Equity Fear & Greed
    try:
        r = httpx.get(
            CNN_FNG_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=8,
            follow_redirects=True,
        )
        if r.status_code == 200:
            data = r.json()
            score = data.get("fear_and_greed", {}).get("score")
            rating = data.get("fear_and_greed", {}).get("rating")
            if score is not None:
                out["equity_fng"] = {"value": round(float(score)), "classification": rating or ""}
    except Exception as e:
        logger.warning(f"CNN FNG fetch failed: {e}")

    return out


# ── Portfolio context ───────────────────────────────────────────

# Map portfolio "source" / instrument shape to an asset_type guess (fallback: stock).
_SOURCE_TO_TYPE = {"finst": "crypto"}


def _guess_asset_type(instrument: str, source: str | None) -> str:
    if source in _SOURCE_TO_TYPE:
        return _SOURCE_TO_TYPE[source]
    # crude ETF heuristic
    upper = instrument.upper()
    etf_hints = ("VUAA", "CNDX", "SGLD", "SSLN", "VWCE", "EUNL", "CSPX", "VWRL", "IUSA", "EQQQ")
    if upper in etf_hints:
        return "etf"
    return "stock"


def _portfolio_snapshot(db: Session) -> dict:
    positions = db.query(InvestmentPosition).all()
    latest: dict[str, InvestmentPosition] = {}
    for p in positions:
        key = p.instrument
        if key not in latest or (p.statement_date or "") >= (latest[key].statement_date or ""):
            latest[key] = p

    total = sum(p.current_value_eur or 0 for p in latest.values())

    pos_lines = []
    candidate_tickers: list[tuple[str, str]] = []  # (ticker, asset_type)
    seen: set[str] = set()
    for p in sorted(latest.values(), key=lambda x: (x.current_value_eur or 0), reverse=True):
        pct = ((p.current_value_eur or 0) / total * 100) if total > 0 else 0
        ret = p.return_eur or 0
        pos_lines.append(
            f"  - {p.instrument}: {p.current_value_eur or 0:.2f}€ ({pct:.1f}%), retorno {ret:+.2f}€"
        )
        if p.instrument and p.instrument not in seen:
            candidate_tickers.append((p.instrument, _guess_asset_type(p.instrument, p.source)))
            seen.add(p.instrument)

    txns = db.query(InvestmentTransaction).all()
    deposits = sum(t.amount for t in txns if t.type == "Depósito")

    # Read this month's plan first — needed to resolve rotational asset choices
    month_str = datetime.now().strftime("%Y-%m")
    monthly = db.query(InvestmentMonthlyPlan).filter(InvestmentMonthlyPlan.month == month_str).first()
    budget = monthly.budget if monthly else 300
    rotational_choices: dict[str, str] = {}
    if monthly and monthly.rotational_choices:
        try:
            rotational_choices = json.loads(monthly.rotational_choices) or {}
        except (json.JSONDecodeError, TypeError):
            rotational_choices = {}

    allocs = db.query(InvestmentAllocation).order_by(InvestmentAllocation.sort_order).all()
    plan_lines: list[str] = []
    plan_assets: list[dict] = []
    for a in allocs:
        ticker = a.ticker
        name = a.name or a.ticker
        asset_type = a.asset_type or "stock"
        if a.is_rotational:
            choice = (rotational_choices.get(str(a.id)) or "").strip()
            if not choice:
                # Sem escolha para este mês — saltar (sem placeholder)
                continue
            # Aceita "TICKER - Nome" ou só "TICKER"
            if " - " in choice:
                t, n = choice.split(" - ", 1)
                ticker = t.strip().upper()
                name = n.strip() or ticker
            else:
                ticker = choice.strip().upper()
                name = a.name or ticker
        if not ticker:
            continue
        plan_lines.append(f"  - {name} ({ticker}, {asset_type}): {a.percentage:.0f}%")
        if ticker not in seen:
            candidate_tickers.append((ticker, asset_type))
            seen.add(ticker)
        plan_assets.append({
            "ticker": ticker,
            "name": name,
            "asset_type": asset_type,
            "percentage": float(a.percentage or 0),
        })

    return {
        "total_value": total,
        "deposits": deposits,
        "positions_text": "\n".join(pos_lines) if pos_lines else "  (sem posições)",
        "plan_text": "\n".join(plan_lines) if plan_lines else "  (sem plano definido)",
        "monthly_budget": budget,
        "candidate_tickers": candidate_tickers,
        "plan_assets": plan_assets,
    }


# ── Common watchlist for broad market context ──────────────────
# These give the AI a sense of regime even when not in user's portfolio.
WATCHLIST = [
    # Broad index + commodities
    ("SPY",  "etf"),     # S&P 500
    ("QQQ",  "etf"),     # Nasdaq 100
    ("VT",   "etf"),     # Vanguard Total World
    ("GLD",  "etf"),     # Gold
    ("SLV",  "etf"),     # Silver
    # Crypto
    ("BTC",  "crypto"),
    ("ETH",  "crypto"),
    ("SOL",  "crypto"),
    # Mega-cap tech
    ("NVDA", "stock"),
    ("AAPL", "stock"),
    ("MSFT", "stock"),
    ("GOOGL","stock"),
    ("AMZN", "stock"),
    ("META", "stock"),
    ("TSLA", "stock"),
    # Semis / AI
    ("AMD",  "stock"),
    ("AVGO", "stock"),
    ("TSM",  "stock"),
    # Other large-cap
    ("BRK-B","stock"),
    ("JPM",  "stock"),
    ("V",    "stock"),
    ("MA",   "stock"),
    ("UNH",  "stock"),
    ("LLY",  "stock"),
    ("COST", "stock"),
    ("NFLX", "stock"),
    ("CRM",  "stock"),
    ("PLTR", "stock"),
]


# ── Sector classification ───────────────────────────────────────
# Atribui um sector a cada sugestão para a UI agrupar (Semicondutores, Tech Mega-cap, etc.).
# Lookup por ticker; fallback baseado em asset_type.

SECTOR_MAP: dict[str, str] = {
    # Semicondutores
    "NVDA": "Semicondutores", "AMD": "Semicondutores", "AVGO": "Semicondutores",
    "TSM": "Semicondutores", "ASML": "Semicondutores", "QCOM": "Semicondutores",
    "INTC": "Semicondutores", "MU": "Semicondutores", "TXN": "Semicondutores",
    "ARM": "Semicondutores", "MRVL": "Semicondutores", "LRCX": "Semicondutores",
    "AMAT": "Semicondutores", "KLAC": "Semicondutores",
    # Tech Mega-cap (FAANG-style)
    "AAPL": "Tech Mega-cap", "MSFT": "Tech Mega-cap", "GOOGL": "Tech Mega-cap",
    "GOOG": "Tech Mega-cap", "AMZN": "Tech Mega-cap", "META": "Tech Mega-cap",
    "TSLA": "Tech Mega-cap",
    # Software / Cloud
    "CRM": "Software/Cloud", "ORCL": "Software/Cloud", "ADBE": "Software/Cloud",
    "NOW": "Software/Cloud", "PLTR": "Software/Cloud", "SNOW": "Software/Cloud",
    "NFLX": "Software/Cloud", "SHOP": "Software/Cloud", "INTU": "Software/Cloud",
    "IBM": "Software/Cloud", "UBER": "Software/Cloud",
    # Financeiro
    "JPM": "Financeiro", "V": "Financeiro", "MA": "Financeiro", "BAC": "Financeiro",
    "GS": "Financeiro", "BRK-B": "Financeiro", "BRK.B": "Financeiro", "WFC": "Financeiro",
    "MS": "Financeiro", "C": "Financeiro", "AXP": "Financeiro", "BLK": "Financeiro",
    "SCHW": "Financeiro",
    # Healthcare
    "UNH": "Healthcare", "LLY": "Healthcare", "JNJ": "Healthcare", "PFE": "Healthcare",
    "MRK": "Healthcare", "ABBV": "Healthcare", "TMO": "Healthcare", "ABT": "Healthcare",
    "DHR": "Healthcare", "AMGN": "Healthcare", "NVO": "Healthcare", "ISRG": "Healthcare",
    # Energia
    "XOM": "Energia", "CVX": "Energia", "COP": "Energia", "SHEL": "Energia",
    "BP": "Energia", "EOG": "Energia", "SLB": "Energia", "PSX": "Energia",
    "MPC": "Energia",
    # Consumo
    "COST": "Consumo", "WMT": "Consumo", "PG": "Consumo", "KO": "Consumo",
    "PEP": "Consumo", "MCD": "Consumo", "SBUX": "Consumo", "NKE": "Consumo",
    "HD": "Consumo", "LOW": "Consumo", "TGT": "Consumo", "DIS": "Consumo",
    "MO": "Consumo",
    # Industrial
    "CAT": "Industrial", "DE": "Industrial", "BA": "Industrial", "GE": "Industrial",
    "HON": "Industrial", "UNP": "Industrial", "RTX": "Industrial", "LMT": "Industrial",
    "MMM": "Industrial", "UPS": "Industrial",
    # Telecom
    "T": "Telecom", "VZ": "Telecom", "TMUS": "Telecom",
    # Utilities
    "NEE": "Utilities", "DUK": "Utilities", "SO": "Utilities", "AEP": "Utilities",
    # REIT
    "PLD": "Imobiliário/REIT", "AMT": "Imobiliário/REIT", "O": "Imobiliário/REIT",
    "EQIX": "Imobiliário/REIT", "SPG": "Imobiliário/REIT",
    # Crypto
    "BTC": "Crypto", "ETH": "Crypto", "SOL": "Crypto", "ADA": "Crypto",
    "DOT": "Crypto", "AVAX": "Crypto", "MATIC": "Crypto", "LINK": "Crypto",
    "XRP": "Crypto", "DOGE": "Crypto", "BNB": "Crypto", "TON": "Crypto",
    # Ouro / Commodities
    "GLD": "Ouro/Commodities", "SGLD": "Ouro/Commodities", "SLV": "Ouro/Commodities",
    "SSLN": "Ouro/Commodities", "PHAU": "Ouro/Commodities", "IAU": "Ouro/Commodities",
    "USO": "Ouro/Commodities", "DBC": "Ouro/Commodities",
    # ETF Amplo (mercado total / S&P)
    "SPY": "ETF Amplo", "VOO": "ETF Amplo", "VUAA": "ETF Amplo", "VT": "ETF Amplo",
    "VWCE": "ETF Amplo", "VWRL": "ETF Amplo", "EUNL": "ETF Amplo", "CSPX": "ETF Amplo",
    "IUSA": "ETF Amplo", "VTI": "ETF Amplo", "IWDA": "ETF Amplo",
    # ETF Sectorial / temático
    "QQQ": "ETF Sectorial", "EQQQ": "ETF Sectorial", "CNDX": "ETF Sectorial",
    "XLF": "ETF Sectorial", "XLE": "ETF Sectorial", "XLK": "ETF Sectorial",
    "XLV": "ETF Sectorial", "XLY": "ETF Sectorial", "XLI": "ETF Sectorial",
    "ARKK": "ETF Sectorial", "SMH": "ETF Sectorial", "SOXX": "ETF Sectorial",
    "IBIT": "ETF Sectorial",
}


def _classify_sector(ticker: str | None, asset_type: str | None) -> str:
    """Devolve o sector de um ticker. Fallback usa asset_type (crypto/etf) ou 'Outro'."""
    if not ticker:
        return "Outro"
    t = ticker.upper().replace(".", "-").strip()
    if t in SECTOR_MAP:
        return SECTOR_MAP[t]
    at = (asset_type or "").lower()
    if at == "crypto":
        return "Crypto"
    if at == "etf":
        return "ETF Amplo"
    return "Outro"


def collect_market_data(
    extra_tickers: list[tuple[str, str]] | None = None,
    include_watchlist: bool = True,
) -> dict[str, dict]:
    """Fetch metrics for watchlist + portfolio + plan tickers; add factor percentiles."""
    seen: set[str] = set()
    targets: list[tuple[str, str]] = []
    base = (extra_tickers or []) + (WATCHLIST if include_watchlist else [])
    for t, at in base:
        if t.upper() in seen:
            continue
        seen.add(t.upper())
        targets.append((t, at))
    metrics = fetch_metrics_batch(targets)
    return compute_factor_panel(metrics)


# ── OpenAI prompt ───────────────────────────────────────────────

SYSTEM_PROMPT = """És analista financeiro a aconselhar um investidor PT jovem (DCA, longo prazo, risco moderado-alto).

Princípio orientador: **qualidade > quantidade**. Não devolvas sugestões que não cumpram as regras. É melhor 0 ideias que 10 fracas — o backend rejeita as que falhem as gates de decisão.

Regras gerais:
- Baseia-te SÓ nos dados fornecidos (notícias, sentimento, dados quantitativos). Não inventes números.
- Sê concreto: ticker, ação (buy/hold/reduce/watch), montante €, convicção (high/medium/low).
- COBERTURA OBRIGATÓRIA: TENS de devolver UMA entrada em `plan_recommendations` para CADA ativo do "PLANO DE ALOCAÇÃO ALVO" (mesmo que a recomendação seja "hold" ou "watch"). Não saltes nenhum.

Regras DURAS para action='buy' (qualquer violação → backend converte para 'watch'):
- ❌ NÃO recomendes 'buy' se RSI > 70 (sobrecomprado). Usa 'watch' e diz "esperar correção".
- ❌ NÃO recomendes 'buy' se earnings em ≤14 dias. Usa 'watch' e diz "aguardar earnings em Xd". Earnings é evento binário, não setup.
- ❌ NÃO recomendes 'buy' se a tese só cita UMA família de sinais. Toda 'buy' TEM de cruzar ≥2 destas: técnico (RSI/SMA/MACD/breakout), fundamental (P/E, EPS, beats, margens), sentimento (notícias/fontes), macro (VIX/Fed/regime), on-chain (funding/MVRV — só crypto), insider (cluster buys).
- ❌ NÃO recomendes 'buy' com convicção 'high' se a tese tem <120 caracteres ou cita 0 dados numéricos.

IDEIAS NOVAS (`new_ideas`):
- SEM QUOTAS. Devolve só ideias com setup real. Aceitável devolver `new_ideas: []` se hoje não há nada genuíno. NÃO inventes ideias para "encher".
- Sem cobertura sectorial obrigatória. Se hoje só há setups bons em semis, devolves só semis.
- Conviction 'high' só com ≥3 sinais convergentes de famílias diferentes. 'medium' com ≥2 famílias.

Tese:
- 1 frase ≤150 caracteres com 2-3 dados quantitativos cruzados de famílias diferentes.
- Exemplo BOM (2 famílias): "RSI 32 oversold + 4 beats consecutivos com surprise médio +5.6% (técnico+fundamental)."
- Exemplo MAU (1 família, será rejeitada): "RSI 28 oversold, momentum positivo, acima da SMA50."

Montantes:
- amount_eur = 0 OBRIGATÓRIO para 'hold'/'watch'/'reduce'.
- Para 'buy': amount_eur >= 25€ E <= budget mensal. NUNCA 1€/5€/10€ (não dá para investir em corretoras EU). Se a % do plano der <25€, sobe para 25€ ou muda para 'watch'.

Sector: classifica em "Semicondutores", "Tech Mega-cap", "Software/Cloud", "Energia", "Healthcare", "Financeiro", "Consumo", "Industrial", "Telecom", "Utilities", "Imobiliário/REIT", "Crypto", "ETF Amplo", "ETF Sectorial", "Ouro/Commodities", "Outro". Se duvidoso → "Outro" (backend re-classifica).

OUTPUT: APENAS JSON puro, começa com { e acaba com }. SEM prefácio, SEM markdown, SEM ```json. Schema:
{
  "headline": "tema do dia",
  "market_summary": "2-3 frases sobre regime de mercado",
  "plan_recommendations": [
    {"ticker":"VUAA","name":"Vanguard S&P 500","asset_type":"etf","sector":"ETF Amplo","action":"hold","conviction":"medium","amount_eur":0,"thesis":"razão com métrica/fonte"}
  ],
  "new_ideas": [
    {"ticker":"NVDA","name":"NVIDIA","asset_type":"stock","sector":"Semicondutores","action":"buy","conviction":"high","amount_eur":50,"thesis":"RSI 45 + 4 beats c/ surprise +6% + sentiment positivo (CoinDesk)"}
  ]
}
asset_type: etf|crypto|stock. action: buy|hold|reduce|watch. conviction: high|medium|low."""


def _build_user_prompt(
    portfolio: dict,
    news: list[dict],
    sentiment: dict,
    market_data: dict,
    macro: dict | None = None,
    onchain: dict | None = None,
    fundamentals: dict | None = None,
    earnings: dict | None = None,
    insider: dict | None = None,
    news_sentiment_agg: dict | None = None,
    regime: dict | None = None,
    earnings_momentum: dict | None = None,
    sentiment_delta: dict | None = None,
    funding_btc: dict | None = None,
    funding_eth: dict | None = None,
) -> str:
    # Keep prompt small — agent rejects very large inputs.
    news_block = "\n".join(
        f"- [{n['source']}] {n['title'][:140]}"
        for n in news[:25]
    )
    cfng = sentiment.get("crypto_fng")
    efng = sentiment.get("equity_fng")
    sentiment_lines = []
    if efng:
        sentiment_lines.append(f"Fear & Greed (ações US, CNN): {efng['value']}/100 — {efng['classification']}")
    if cfng:
        sentiment_lines.append(f"Fear & Greed (crypto, alt.me): {cfng['value']}/100 — {cfng['classification']}")
    fng_line = "\n".join(sentiment_lines) if sentiment_lines else "Indicadores de sentimento: indisponíveis"

    if market_data:
        market_block = "\n".join(
            format_metrics_for_prompt(m)
            for m in market_data.values()
            if m.get("source") not in ("none", "error")
        )
    else:
        market_block = "  (dados quantitativos indisponíveis)"

    macro_block = format_macro_for_prompt(macro) if macro else "  (macro indisponível)"
    onchain_block = format_onchain_for_prompt(onchain) if onchain else "  (on-chain indisponível)"
    fundamentals_block = format_fundamentals_for_prompt(fundamentals or {})
    earnings_block = format_earnings_for_prompt(earnings or {})
    insider_block = format_insider_for_prompt(insider or {})
    news_sentiment_block = format_sentiment_for_prompt(news_sentiment_agg) if news_sentiment_agg else ""
    regime_block = format_regime_for_prompt(regime or {})
    earnings_mom_block = format_earnings_momentum_for_prompt(earnings_momentum or {})
    sentiment_delta_block = format_sentiment_delta_for_prompt(sentiment_delta or {})
    funding_lines = []
    if funding_btc:
        funding_lines.append(format_funding_persistence_for_prompt(funding_btc))
    if funding_eth:
        funding_lines.append(format_funding_persistence_for_prompt(funding_eth))
    funding_block = "\n".join(funding_lines) if funding_lines else "  (funding persistence indisponível)"

    return f"""Data: {datetime.now().strftime('%Y-%m-%d %H:%M')}

PORTFOLIO ATUAL ({portfolio['total_value']:.2f}€ total, {portfolio['deposits']:.2f}€ depositado):
{portfolio['positions_text']}

PLANO DE ALOCAÇÃO ALVO:
{portfolio['plan_text']}

Budget mensal: {portfolio['monthly_budget']:.0f}€

REGIME DE MERCADO (probabilidade risk-on/off):
{regime_block}

REGIME MACRO (yield curve, VIX, USD, breakeven, copper/gold):
{macro_block}

ON-CHAIN CRYPTO (MVRV, funding rates, atividade rede):
{onchain_block}

FUNDING PERSISTENCE (contrarian — 5+d em extremo = squeeze provável):
{funding_block}

INDICADORES DE SENTIMENTO (Fear & Greed):
{fng_line}

SENTIMENT DAS NOTÍCIAS (agregado, pré-classificado):
{news_sentiment_block}

SENTIMENT DELTA (MA7 vs MA30 z-score, regime change detection):
{sentiment_delta_block}

DADOS QUANTITATIVOS (preço, % mês/3m/12m, RSI 14, vs SMA 50/200, range 52w, percentis momentum 12-1 e low-vol):
{market_block}

FUNDAMENTALS (sector, P/E, P/B, EV/EBITDA, ROE, margens, debt/equity, beta):
{fundamentals_block}

CALENDÁRIO EARNINGS (próximos 30 dias):
{earnings_block}

EARNINGS MOMENTUM (PEAD — beats consecutivos):
{earnings_mom_block}

ATIVIDADE INSIDER (Form 4 SEC, últimos 30d):
{insider_block}

NOTÍCIAS DE HOJE ({len(news)} headlines top-relevância):
{news_block}

REGRA DE OUTPUT (recap):
- `plan_recommendations`: UMA entrada por CADA ativo listado em "PLANO DE ALOCAÇÃO ALVO" — sem exceções, sem saltar nenhum. Mesmo que a leitura seja neutra usa "hold"/"watch".
- `new_ideas`: alvo de 8-12 ideias FORA do plano. Aceita conviction="high" (≥3 sinais convergentes) OU "medium" (≥2 sinais positivos). Diversifica setores (mega-cap tech, financeiro, healthcare, industrial, energia, semicondutores, ETFs sectoriais, ouro). Cada `thesis` em 1 frase ≤150 caracteres — sê seco para caber tudo na resposta.

Com base APENAS no que está acima, dá sugestões. USA SEMPRE:
- regime de mercado (P risk-off ≥ 0.65 → reduz beta; ≤ 0.35 → adiciona risco)
- regime macro para escolher entre risk-on (beta, growth, crypto) e risk-off (defensivos, gold)
- on-chain (MVRV>3.5 = topo cycle BTC; funding alto = risco de squeeze)
- funding persistence (5+d longs pagando >15% anual ⇒ contrarian short setup; vice-versa)
- earnings iminentes (≤7d) → preferir HOLD/WATCH em vez de BUY
- earnings momentum PEAD (3+ beats consecutivos com surprise médio >5% ⇒ drift positivo 60d)
- fundamentals (P/E vs setor, ROE alto, debt baixo)
- atividade insider (cluster buys = bullish; cluster sells = caution)
- sentimento de notícias agregado (avg muito negativo ⇒ contrarian opportunity?)
- sentiment delta (z >= +1.5 = swing positivo; z <= -1.5 = capitulação possível)
- anomaly hoje (movimento >3σ ⇒ verificar catalisador antes de entrar)
- RSI extremos, momentum P>70, posição vs SMA200
Cita pelo menos 1 dado quantitativo concreto em CADA thesis. Devolve o JSON pedido."""


class AgentTransientError(Exception):
    """Retryable failure: rate limit, network blip, server error."""


async def _call_agent_once(system: str, user: str) -> str:
    """Single attempt. Raises AgentTransientError on retryable failures."""
    message = f"{system}\n\n---\n\n{user}"

    form = aiohttp.FormData()
    form.add_field("channel_id", AI_CHANNEL_ID)
    form.add_field("thread_id", f"cristopher-signal-{datetime.now().strftime('%Y%m%d%H%M%S')}")
    form.add_field("user_info", "{}")
    form.add_field("message", message)

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)

    full = ""
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.post(
            AI_API_URL,
            data=form,
            headers={"x-api-key": AI_API_KEY},
            timeout=aiohttp.ClientTimeout(total=180),
        ) as resp:
            if resp.status in (429, 500, 502, 503, 504):
                err = await resp.text()
                logger.warning(f"AI transient {resp.status}: {err[:200]}")
                raise AgentTransientError(f"{resp.status}")
            if resp.status != 200:
                err = await resp.text()
                logger.error(f"AI API error {resp.status}: {err[:300]}")
                raise HTTPException(status_code=502, detail=f"Agente IA devolveu {resp.status}")
            async for chunk in resp.content:
                full += chunk.decode("utf-8", errors="ignore")

    # Stream is JSON-lines: {"type":"token","content":"..."} per line
    cleaned = ""
    error_message = None
    for line in full.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload and payload != "[DONE]":
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                else:
                    continue
            else:
                continue
        if not isinstance(obj, dict):
            continue
        msg_type = obj.get("type", "")
        content = obj.get("content", "")
        if msg_type == "token" and content:
            cleaned += content
        elif msg_type == "error":
            error_message = content or "erro desconhecido no agente"
        elif msg_type in ("end", "done"):
            break

    if not cleaned and error_message:
        # "Rate limit reached" comes through here on the in-stream error frame
        if "rate limit" in error_message.lower() or "429" in error_message:
            raise AgentTransientError(error_message)
        raise HTTPException(status_code=502, detail=f"Agente IA: {error_message}")
    if not cleaned:
        raise AgentTransientError("empty response")
    return cleaned.strip()


async def _call_agent(system: str, user: str, max_retries: int = 3) -> str:
    """Call iaedu.pt with exponential backoff on rate-limit / 5xx / empty frames."""
    delay = 5.0
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return await _call_agent_once(system, user)
        except AgentTransientError as e:
            last_err = e
            if attempt < max_retries:
                logger.info(f"Agent retry {attempt}/{max_retries} in {delay:.0f}s ({e})")
                await asyncio.sleep(delay)
                delay = min(delay * 3, 60.0)
            else:
                logger.error(f"Agent gave up after {max_retries} attempts: {e}")
        except HTTPException:
            raise
        except Exception as e:
            last_err = e
            logger.error(f"Agent unexpected error: {e}")
            break
    raise HTTPException(status_code=502, detail=f"Agente IA falhou após {max_retries} tentativas: {last_err}")


def _repair_truncated_json(s: str) -> Optional[str]:
    """Best-effort repair for an LLM response cut off mid-stream.

    Strategy: find a prefix that is valid JSON when missing brackets are added
    on the right. Tries cutting at the end and walks backwards if the partial
    is malformed (string still open, dangling key/colon, etc.).
    """
    if not s or "{" not in s:
        return None

    def _scan(prefix: str):
        in_str = False
        esc = False
        stack: list[str] = []
        last_open_quote = -1
        for i, ch in enumerate(prefix):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                    last_open_quote = i
                elif ch in "{[":
                    stack.append("}" if ch == "{" else "]")
                elif ch in "}]":
                    if not stack:
                        return None
                    stack.pop()
        return in_str, stack, last_open_quote

    base = s
    scan = _scan(base)
    if scan is None:
        return None
    in_str, _, last_open_quote = scan
    if in_str and last_open_quote >= 0:
        base = s[:last_open_quote]

    # Try cutting back successively until the prefix + closing brackets parses.
    for cut in range(len(base), 0, -1):
        candidate = base[:cut].rstrip()
        if not candidate:
            break
        if candidate[-1] in ":,":
            continue  # dangling key/separator — keep walking back
        scan = _scan(candidate)
        if scan is None:
            continue
        c_in_str, c_stack, _ = scan
        if c_in_str:
            continue
        repaired = candidate + "".join(reversed(c_stack))
        try:
            json.loads(repaired)
            return repaired
        except json.JSONDecodeError:
            continue
    return None


def _extract_json(raw: str) -> dict:
    """Best-effort: find the JSON object in a model response that may include prose/markdown."""
    if not raw:
        raise ValueError("resposta vazia")
    # Try direct
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Strip ```json ... ``` fences
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    # Greedy first-{ to last-}
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass
    # Last resort: response was truncated mid-stream — try to repair from the first '{'
    if start != -1:
        repaired = _repair_truncated_json(raw[start:])
        if repaired:
            try:
                obj = json.loads(repaired)
                logger.warning(
                    f"_extract_json: usei repair de JSON truncado ({len(raw)} chars in, "
                    f"{len(repaired)} out)"
                )
                return obj
            except json.JSONDecodeError:
                pass
    raise ValueError("não foi possível extrair JSON da resposta")


# ── Endpoints ───────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    extra_question: str = ""
    plan_only: bool = False  # Quando True: foca só nos ativos do plano (sem watchlist, sem new_ideas) e não persiste
    excluded_tickers: list[str] = []  # tickers que o utilizador rejeitou — não devem voltar em new_ideas


class AnalyzePlanRequest(BaseModel):
    extra_question: str = ""
    excluded_tickers: list[str] = []  # tickers que o utilizador rejeitou — não devem voltar em new_ideas


def _serialize(s: InvestmentSignal) -> dict:
    suggestions = json.loads(s.suggestions_json or "[]")
    return {
        "id": s.id,
        "generated_at": s.generated_at.isoformat() if s.generated_at else None,
        "headline": s.headline,
        "market_summary": s.market_summary,
        "suggestions": suggestions,
        "sources": json.loads(s.sources_json or "[]"),
        "model": s.model,
        "cost_usd": s.cost_usd,
        "prompt_hash": getattr(s, "prompt_hash", None),
        "prompt_version": getattr(s, "prompt_version", None),
        "quality_summary": summarize_flags(suggestions),
    }


@router.get("")
def list_signals(limit: int = 30, db: Session = Depends(get_db)):
    rows = (
        db.query(InvestmentSignal)
        .order_by(InvestmentSignal.generated_at.desc())
        .limit(limit)
        .all()
    )
    return [_serialize(s) for s in rows]


@router.get("/latest")
def latest_signal(db: Session = Depends(get_db)):
    s = db.query(InvestmentSignal).order_by(InvestmentSignal.generated_at.desc()).first()
    if not s:
        return None
    return _serialize(s)


def _assemble_suggestions(
    parsed: dict,
    plan_assets: list[dict],
    *,
    plan_only: bool = False,
    monthly_budget: float = 0,
) -> list[dict]:
    """Combine plan_recommendations + new_ideas into a single annotated list.

    - Marks each entry with `is_plan_asset` (True/False).
    - Guarantees coverage: every plan asset has an entry; missing ones get a
      fallback. In plan_only mode (DCA) o fallback é "buy" com amount = %×budget;
      caso contrário é "watch" / amount=0.
    - Drops new_ideas whose conviction is not "high" (only confident extras pass).
    - Backwards compat: if the agent returns the old `suggestions` array,
      treats it as a single list and tags entries by ticker membership.
    """
    plan_index: dict[str, dict] = {p["ticker"].upper(): p for p in plan_assets if p.get("ticker")}

    plan_recs = parsed.get("plan_recommendations")
    new_ideas = parsed.get("new_ideas")

    # Legacy fallback: agent returned old single `suggestions` array
    if plan_recs is None and new_ideas is None:
        legacy = parsed.get("suggestions") or []
        plan_recs = [s for s in legacy if isinstance(s, dict) and (s.get("ticker") or "").upper() in plan_index]
        new_ideas = [s for s in legacy if isinstance(s, dict) and (s.get("ticker") or "").upper() not in plan_index]

    plan_recs = [s for s in (plan_recs or []) if isinstance(s, dict)]
    new_ideas = [s for s in (new_ideas or []) if isinstance(s, dict)]

    # Tag plan_recs and dedupe by ticker (keep first)
    out: list[dict] = []
    seen_plan: set[str] = set()
    for s in plan_recs:
        t = (s.get("ticker") or "").upper()
        if not t or t in seen_plan:
            continue
        seen_plan.add(t)
        s = dict(s)
        s["is_plan_asset"] = True
        out.append(s)

    # Backfill missing plan assets. Em plan_only (DCA mensal) defaultamos a "buy" com o montante do plano;
    # noutros casos mantemos "watch" para não forçar compras.
    for ticker_upper, p in plan_index.items():
        if ticker_upper in seen_plan:
            continue
        if plan_only:
            pct = float(p.get("percentage") or 0)
            amount = round((pct / 100) * monthly_budget) if monthly_budget else 0
            out.append({
                "ticker": p["ticker"],
                "name": p.get("name") or p["ticker"],
                "asset_type": p.get("asset_type", "stock"),
                "action": "buy",
                "conviction": "medium",
                "amount_eur": amount,
                "thesis": f"DCA mensal por defeito — {pct:.0f}% × {monthly_budget:.0f}€ = {amount}€. A IA não devolveu leitura específica para este ativo.",
                "is_plan_asset": True,
                "auto_filled": True,
            })
        else:
            out.append({
                "ticker": p["ticker"],
                "name": p.get("name") or p["ticker"],
                "asset_type": p.get("asset_type", "stock"),
                "action": "watch",
                "conviction": "low",
                "amount_eur": 0,
                "thesis": "Sem leitura clara nos dados de hoje — manter posição e DCA conforme plano.",
                "is_plan_asset": True,
                "auto_filled": True,
            })

    # New ideas: aceita high + medium (low é descartado por ser ruído), dedupe vs plan
    for s in new_ideas:
        t = (s.get("ticker") or "").upper()
        if not t or t in plan_index:
            continue
        if (s.get("conviction") or "").lower() not in ("high", "medium"):
            continue
        s = dict(s)
        s["is_plan_asset"] = False
        out.append(s)

    return out


def _score_suggestion(sug: dict) -> int:
    """Score 0-100 indicando quão forte é a sugestão.

    Base por convicção (high=85, medium=60, low=35), penalizada por quality_flags.
    Pequeno bónus para 'buy' com tese rica (>180 chars) — proxy de tese substanciada.
    """
    conviction = (sug.get("conviction") or "").lower()
    base = {"high": 85, "medium": 60, "low": 35}.get(conviction, 40)

    flags = sug.get("quality_flags") or []
    penalty = 0
    flag_weights = {
        "ticker_invalid": 40,
        "contradiction": 25,
        "weak_conviction": 15,
        "unverified_numbers": 10,
        "amount_over_budget": 5,
    }
    for f in flags:
        key = f.split(":")[0]
        penalty += flag_weights.get(key, 5)

    bonus = 0
    if (sug.get("action") or "").lower() == "buy" and len(sug.get("thesis") or "") >= 180:
        bonus = 5

    return max(0, min(100, base - penalty + bonus))


# ── Decision gates ──────────────────────────────────────────────
# Filtros DUROS aplicados depois de validate_suggestions e apply_risk_overlays.
# Convertem 'buy' para 'watch' quando há razões técnicas/fundamentais para não
# executar. Aplicam-se SÓ a new_ideas — em plan_assets a IA já recebeu
# instrução para não saltar DCA, e o utilizador escolheu o plano por uma razão.

# Limiares
GATE_RSI_OVERBOUGHT = 70.0           # acima disto, "buy" → watch
GATE_EARNINGS_DAYS = 14              # earnings em ≤Nd → watch
GATE_MIN_CONFIDENCE_PCT = 50.0       # abaixo disto, "buy" → watch
AUTO_CRITIQUE_CONFIDENCE_PCT = 60.0  # buys com confidence<60% disparam critique automática
AUTO_CRITIQUE_MAX = 3                # cap de critiques por análise (custo $)


def _annotate_earnings_proximity(suggestions: list[dict], earnings: dict | None) -> list[dict]:
    """Escreve days_to_earnings em cada sugestão quando há earnings agendadas."""
    if not earnings:
        return suggestions
    out = []
    for s in suggestions:
        if not isinstance(s, dict):
            continue
        s = dict(s)
        ticker = (s.get("ticker") or "").upper()
        info = earnings.get(ticker) or earnings.get(ticker.replace("-", "."))
        if isinstance(info, dict):
            d = info.get("days_until")
            if isinstance(d, int):
                s["days_to_earnings"] = d
                s["next_earnings_date"] = info.get("date")
        out.append(s)
    return out


def _convert_to_watch(sug: dict, gate: str, reason: str) -> dict:
    """Converte 'buy' em 'watch' e regista o motivo (gate)."""
    sug["original_action"] = sug.get("action")
    sug["original_amount_eur_gate"] = sug.get("amount_eur")
    sug["action"] = "watch"
    sug["amount_eur"] = 0
    gates = list(sug.get("gates_triggered") or [])
    gates.append({"gate": gate, "reason": reason})
    sug["gates_triggered"] = gates
    return sug


def apply_decision_gates(
    suggestions: list[dict],
    market_data: dict[str, dict],
    monthly_budget: float | None,
) -> list[dict]:
    """Filtros duros para new_ideas. Plan_assets passam sem mudança.

    Gates aplicadas em ordem (primeiro hit decide):
      1. rsi_overbought     RSI > 70
      2. vol_target_too_small  vol-target < MIN_BUY_AMOUNT_EUR
      3. earnings_too_close earnings em ≤14d
      4. single_dimension   tese cita só 1 família de sinais
      5. low_confidence     confidence_pct < 50%

    Após as gates por sugestão, corre uma gate de budget partilhado:
      6. budget_exhausted   ranqueia 'buy' restantes por confidence desc;
                            corta o que excede o budget mensal disponível.
    """
    out: list[dict] = []
    for sug in suggestions:
        if not isinstance(sug, dict):
            continue
        sug = dict(sug)
        # Plan assets passam — DCA é DCA. Apenas anotamos info p/ a UI.
        if sug.get("is_plan_asset"):
            out.append(sug)
            continue
        action = (sug.get("action") or "").lower()
        if action != "buy":
            out.append(sug)
            continue

        ticker = (sug.get("ticker") or "").upper()
        metrics = market_data.get(ticker) or market_data.get(ticker.replace("-", ".")) or {}

        rsi = metrics.get("rsi_14")
        if isinstance(rsi, (int, float)) and rsi > GATE_RSI_OVERBOUGHT:
            _convert_to_watch(sug, "rsi_overbought", f"RSI {rsi:.1f} > {GATE_RSI_OVERBOUGHT:.0f}")
            out.append(sug); continue

        vol_target = sug.get("suggested_amount_eur")
        if isinstance(vol_target, (int, float)) and vol_target < MIN_BUY_AMOUNT_EUR:
            _convert_to_watch(
                sug, "vol_target_too_small",
                f"vol-target {vol_target:.0f}€ < mínimo {MIN_BUY_AMOUNT_EUR}€ — posição demasiado volátil para sizar"
            )
            out.append(sug); continue

        d = sug.get("days_to_earnings")
        if isinstance(d, int) and 0 <= d <= GATE_EARNINGS_DAYS:
            _convert_to_watch(sug, "earnings_too_close", f"earnings em {d}d (≤{GATE_EARNINGS_DAYS}d)")
            out.append(sug); continue

        flag_keys = {(f.split(":")[0]) for f in (sug.get("quality_flags") or [])}
        if "single_dimension" in flag_keys:
            fams = sug.get("signal_families") or []
            _convert_to_watch(
                sug, "single_dimension",
                f"tese só cruza {len(fams)} família(s): {','.join(fams) or 'nenhuma'}"
            )
            out.append(sug); continue

        cpct = sug.get("confidence_pct")
        if isinstance(cpct, (int, float)) and cpct < GATE_MIN_CONFIDENCE_PCT:
            _convert_to_watch(
                sug, "low_confidence",
                f"confidence {cpct:.0f}% < {GATE_MIN_CONFIDENCE_PCT:.0f}%"
            )
            out.append(sug); continue

        out.append(sug)

    # Gate 6: budget partilhado entre todos os 'buy' (plan + new_ideas).
    # Plan assets têm prioridade (DCA mensal); new_ideas ranqueiam por confidence.
    if monthly_budget and monthly_budget > 0:
        plan_buy_total = sum(
            (s.get("amount_eur") or 0)
            for s in out
            if s.get("is_plan_asset") and (s.get("action") or "").lower() == "buy"
        )
        remaining = max(0.0, monthly_budget - plan_buy_total)
        new_buys = sorted(
            [s for s in out if not s.get("is_plan_asset") and (s.get("action") or "").lower() == "buy"],
            key=lambda s: -(s.get("confidence_pct") or 0),
        )
        running = 0.0
        for s in new_buys:
            amt = s.get("amount_eur") or 0
            if running + amt <= remaining:
                running += amt
            else:
                _convert_to_watch(
                    s, "budget_exhausted",
                    f"budget esgotado — plano usa {plan_buy_total:.0f}€ + {running:.0f}€ já alocados; "
                    f"sobram {(remaining - running):.0f}€ < {amt:.0f}€"
                )

    return out


async def _run_auto_critique(
    suggestions: list[dict],
    headline: str,
    market_summary: str,
) -> list[dict]:
    """Auto-critique de buys com confidence<60% (cap AUTO_CRITIQUE_MAX).

    Identifica buys frágeis que sobreviveram às gates mas têm convicção fraca,
    e dispara uma 2ª passagem do agente como risk officer. Faz merge do
    risk_critique de volta na sugestão para a UI mostrar fraquezas.
    Falha silenciosamente — não bloqueia o pipeline.
    """
    candidates = [
        s for s in suggestions
        if isinstance(s, dict)
        and not s.get("is_plan_asset")
        and (s.get("action") or "").lower() == "buy"
        and isinstance(s.get("confidence_pct"), (int, float))
        and s["confidence_pct"] < AUTO_CRITIQUE_CONFIDENCE_PCT
    ]
    if not candidates:
        return suggestions
    # Criticar primeiro as mais frágeis
    candidates.sort(key=lambda s: s.get("confidence_pct") or 0)
    candidates = candidates[:AUTO_CRITIQUE_MAX]

    sug_blob = json.dumps([
        {
            "ticker": x.get("ticker"),
            "action": x.get("action"),
            "conviction": x.get("conviction"),
            "thesis": x.get("thesis"),
            "amount_eur": x.get("amount_eur"),
            "confidence_pct": x.get("confidence_pct"),
        }
        for x in candidates
    ], ensure_ascii=False)

    user_prompt = f"""Headline: {headline}
Resumo do mercado: {market_summary}

Sugestões 'buy' com confidence baixa que sobreviveram às gates iniciais — vê se as devíamos rejeitar:
{sug_blob}

Identifica fraquezas. Devolve o JSON pedido."""

    try:
        raw = await _call_agent(CRITIQUE_PROMPT, user_prompt)
        parsed = _extract_json(raw)
    except Exception as e:
        logger.warning(f"Auto-critique falhou (não-fatal): {e}")
        return suggestions

    critiques = parsed.get("critiques", [])
    crit_by_ticker = {(c.get("ticker") or "").upper(): c for c in critiques if isinstance(c, dict)}

    out = []
    for s in suggestions:
        if not isinstance(s, dict):
            continue
        s = dict(s)
        t = (s.get("ticker") or "").upper()
        if t in crit_by_ticker:
            s["risk_critique"] = crit_by_ticker[t]
            s["auto_critique"] = True
            # Se o risk officer disser "reject", convertemos para watch automaticamente.
            verdict = (crit_by_ticker[t].get("verdict") or "").lower()
            if verdict == "reject" and (s.get("action") or "").lower() == "buy":
                _convert_to_watch(s, "auto_critique_reject", "risk officer: reject")
        out.append(s)
    return out


def _enrich_suggestions_with_prices(suggestions: list[dict]) -> list[dict]:
    """For each suggestion, fetch the current price and store as price_at_generation.

    Also pre-fills `current_price` and `pct_since_generation` (== 0 at this moment)
    so the UI can render uniformly across fresh and old signals.
    """
    out = []
    for s in suggestions:
        if not isinstance(s, dict):
            continue
        ticker = s.get("ticker", "").strip().upper()
        asset_type = s.get("asset_type", "stock")
        price = get_quick_price(ticker, asset_type) if ticker else None
        s = dict(s)
        s["price_at_generation"] = round(price, 4) if price else None
        s["current_price"] = round(price, 4) if price else None
        s["pct_since_generation"] = 0.0 if price else None
        s["last_price_check"] = datetime.now().isoformat(timespec="seconds")
        out.append(s)
    return out


@router.post("/generate")
async def generate_signal(body: GenerateRequest = GenerateRequest(), db: Session = Depends(get_db)):
    """Collect everything → call iaedu.pt agent → validate → store.

    plan_only=True restringe a análise aos ativos do plano (sem watchlist),
    força new_ideas vazio e não persiste o sinal — usado pela página Planeamento.
    """
    loop = asyncio.get_event_loop()
    portfolio = _portfolio_snapshot(db)

    # Modo plan_only: candidate_tickers fica restrito aos tickers do plano (para o prompt focar aí),
    # mas mantemos a WATCHLIST nas chamadas a market_data/fundamentals/earnings para a IA conseguir
    # avaliar new_ideas com base em dados quantitativos.
    if body.plan_only:
        plan_set = {(p.get("ticker") or "").upper() for p in (portfolio.get("plan_assets") or [])}
        if not plan_set:
            raise HTTPException(status_code=400, detail="Sem ativos no plano para analisar")
        portfolio["candidate_tickers"] = [
            (t, at) for (t, at) in portfolio["candidate_tickers"] if t.upper() in plan_set
        ]

    # Tickers candidatos: portfolio/plano + watchlist (watchlist sempre incluída para new_ideas)
    candidate_tickers_typed = portfolio["candidate_tickers"] + WATCHLIST
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for t, at in candidate_tickers_typed:
        if t.upper() in seen:
            continue
        seen.add(t.upper())
        deduped.append((t, at))
    stock_tickers = [t for t, at in deduped if at == "stock"]
    insider_targets = [t for t in stock_tickers if t.upper() in TICKER_TO_CIK]

    # Parallel I/O: tudo independente
    news_task = loop.run_in_executor(None, collect_news, 8)
    sentiment_task = loop.run_in_executor(None, collect_sentiment)
    # market_data inclui sempre a watchlist (mesmo em plan_only) para a IA poder sugerir new_ideas
    market_task = loop.run_in_executor(
        None, collect_market_data, portfolio["candidate_tickers"], True
    )
    macro_task = loop.run_in_executor(None, fetch_macro_snapshot)
    onchain_task = loop.run_in_executor(None, fetch_onchain_snapshot)
    fundamentals_task = loop.run_in_executor(None, fetch_fundamentals_batch, stock_tickers)
    earnings_task = loop.run_in_executor(None, fetch_earnings_for_tickers, stock_tickers, 30)
    insider_task = loop.run_in_executor(None, fetch_insider_batch, insider_targets, 30, 6)
    regime_task = loop.run_in_executor(None, fetch_regime_snapshot)
    earnings_mom_task = loop.run_in_executor(None, fetch_earnings_momentum, stock_tickers)

    (news, sentiment, market_data, macro, onchain, fundamentals,
     earnings, insider, regime, earnings_momentum) = await asyncio.gather(
        news_task, sentiment_task, market_task, macro_task,
        onchain_task, fundamentals_task, earnings_task, insider_task,
        regime_task, earnings_mom_task,
    )

    if not news:
        raise HTTPException(status_code=502, detail="Não foi possível obter notícias dos feeds")

    # Classify headlines, aggregate, then keep top-25 most informative
    classified = await loop.run_in_executor(None, classify_headlines, news)
    news_sentiment_agg = aggregate_sentiment(classified)
    top_news = filter_by_relevance(classified, top_k=25)

    # Persist daily series for delta/persistence signals (idempotent upsert)
    await loop.run_in_executor(None, persist_daily_sentiment, news_sentiment_agg)
    await loop.run_in_executor(None, persist_daily_funding, onchain)
    await loop.run_in_executor(None, persist_daily_regime, regime)

    sentiment_delta = await loop.run_in_executor(None, compute_sentiment_delta)
    funding_btc = await loop.run_in_executor(None, compute_funding_persistence, "BTC")
    funding_eth = await loop.run_in_executor(None, compute_funding_persistence, "ETH")

    user_prompt = _build_user_prompt(
        portfolio, top_news, sentiment, market_data, macro,
        onchain=onchain, fundamentals=fundamentals, earnings=earnings,
        insider=insider, news_sentiment_agg=news_sentiment_agg,
        regime=regime, earnings_momentum=earnings_momentum,
        sentiment_delta=sentiment_delta,
        funding_btc=funding_btc, funding_eth=funding_eth,
    )
    excluded_set: set[str] = {t.strip().upper() for t in (body.excluded_tickers or []) if t and t.strip()}
    if excluded_set:
        user_prompt += (
            f"\n\nEXCLUSÕES DO UTILIZADOR (NÃO sugerir em new_ideas, sob NENHUMA circunstância): "
            f"{', '.join(sorted(excluded_set))}. Escolhe alternativas diferentes."
        )
    if body.plan_only:
        user_prompt += (
            "\n\nMODO PLAN-ONLY (decisão mensal de DCA):\n"
            "FILOSOFIA: DCA é não-fazer-market-timing. O default é COMPRAR conforme o plano. "
            "Saltar reforço por causa de RSI alto = market timing, e estudos mostram que retail "
            "perde para DCA constante. Por isso a regra:\n"
            "\n"
            "Para CADA ativo do plano:\n"
            f"  - action='buy' (DEFAULT) → REFORÇAR este mês. amount_eur = round(% × budget mensal). NUNCA <{MIN_BUY_AMOUNT_EUR}€.\n"
            f"  - action='buy' com amount REDUZIDO → se houver razão técnica forte (RSI>70 + próximo ATH + earnings em ≤7d), reduzes o amount para 50% do plano (mas NUNCA <{MIN_BUY_AMOUNT_EUR}€). NÃO saltas para 0.\n"
            "  - action='hold' → SÓ se o utilizador já está sobreexposto e sinais técnicos são MUITO negativos (RSI>80 + abaixo SMA50 + sentiment negativo). Justificar com 3+ métricas.\n"
            "  - action='watch' → SÓ para earnings em ≤7d (evento binário). Não usar para 'achar que pode cair'.\n"
            "\n"
            "Em dúvida, escolhe 'buy' (a filosofia DCA é não-timing). Pull-the-trigger sobre 'hold'/'watch' tem de ser muito justificada.\n"
            "\n"
            "NEW IDEAS (fora do plano):\n"
            "- SEM QUOTAS. Devolve só o que tem setup real. 0 ideias é aceitável se não houver oportunidades.\n"
            "- Sem cobertura sectorial obrigatória.\n"
            "- Cada 'buy' TEM de cumprir as gates: RSI<70, earnings>14d, ≥2 famílias de sinais cruzadas. Caso contrário será rejeitado pelo backend.\n"
            "- TESE CURTA — 1 frase de ≤150 caracteres com 2-3 métricas de famílias diferentes."
        )
    if body.extra_question.strip():
        user_prompt += f"\n\nPERGUNTA EXTRA DO UTILIZADOR: {body.extra_question.strip()}"

    try:
        raw = await _call_agent(SYSTEM_PROMPT, user_prompt)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Agent call failed: {e}")
        raise HTTPException(status_code=502, detail=f"Erro a contactar o agente IA: {e}")

    try:
        parsed = _extract_json(raw)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=f"Resposta sem JSON válido ({e}): {raw[:300]}")

    sources = [{"title": n["title"], "url": n["url"], "source": n["source"]} for n in news[:50]]
    # Defensiva: descarta da resposta da IA quaisquer new_ideas em ativos excluídos
    if excluded_set and isinstance(parsed.get("new_ideas"), list):
        parsed["new_ideas"] = [
            s for s in parsed["new_ideas"]
            if isinstance(s, dict) and (s.get("ticker") or "").strip().upper() not in excluded_set
        ]
    # Em plan_only mantemos new_ideas se a IA tiver convicção alta — são oportunidades fora do plano
    # que o utilizador pode considerar adicionar. _assemble_suggestions já filtra por conviction=high.
    # Combine plan_recommendations + new_ideas into a single annotated list
    # (with `is_plan_asset` flag, plan-asset backfill, high-conviction-only extras).
    suggestions_raw = _assemble_suggestions(
        parsed,
        portfolio.get("plan_assets") or [],
        plan_only=body.plan_only,
        monthly_budget=portfolio.get("monthly_budget", 0),
    )
    # 1. Quality guards
    validated = await loop.run_in_executor(
        None, validate_suggestions, suggestions_raw, user_prompt, portfolio.get("monthly_budget")
    )
    # Re-stamp the marker (validate_suggestions copies the dict but preserves keys) + score + sector
    plan_tickers = {(p.get("ticker") or "").upper() for p in (portfolio.get("plan_assets") or [])}
    valid_sectors = set(SECTOR_MAP.values()) | {"Crypto", "ETF Amplo", "ETF Sectorial", "Outro"}
    for v in validated:
        v.setdefault("is_plan_asset", (v.get("ticker") or "").upper() in plan_tickers)
        v["score"] = _score_suggestion(v)
        # Sector: confia no que a IA devolveu se for um valor válido; caso contrário re-classifica.
        ai_sector = (v.get("sector") or "").strip()
        if ai_sector not in valid_sectors:
            v["sector"] = _classify_sector(v.get("ticker"), v.get("asset_type"))
    # 2. Enrich with current price → price_at_generation
    enriched = await loop.run_in_executor(None, _enrich_suggestions_with_prices, validated)
    # 3. Risk overlays: stop loss, vol-targeted sizing, position warnings
    overlaid = apply_risk_overlays(
        enriched, market_data,
        monthly_budget=portfolio.get("monthly_budget", 300),
        total_portfolio_value=portfolio.get("total_value", 0),
    )
    # 4. Anotar earnings proximity (days_to_earnings) para feed às gates
    overlaid = _annotate_earnings_proximity(overlaid, earnings)
    # 5. Decision gates: filtros duros que convertem 'buy' problemáticos para 'watch'.
    #    Aplica-se SÓ a new_ideas; plan_assets passam (DCA é DCA).
    gated = apply_decision_gates(
        overlaid, market_data,
        monthly_budget=portfolio.get("monthly_budget"),
    )
    # 6. Auto-critique para buys com confidence<60% — última passagem antes de persistir.
    suggestions = await _run_auto_critique(
        gated,
        headline=str(parsed.get("headline", "")),
        market_summary=str(parsed.get("market_summary", "")),
    )

    # Total de buys (para o user perceber compromisso vs budget)
    monthly_budget_val = portfolio.get("monthly_budget", 0) or 0
    total_buy_eur = round(sum(
        (s.get("amount_eur") or 0)
        for s in suggestions
        if (s.get("action") or "").lower() == "buy"
    ), 2)

    prompt_hash = hashlib.sha256(user_prompt.encode("utf-8")).hexdigest()[:16]

    if body.plan_only:
        # Análise do plano — não vai para o histórico de Sinais IA, mas sim para a tabela
        # PlanAnalysisLatest (single-row) para o utilizador não ter de re-gerar.
        out = {
            "id": None,
            "generated_at": datetime.now().isoformat(),
            "headline": str(parsed.get("headline", ""))[:500],
            "market_summary": str(parsed.get("market_summary", "")),
            "suggestions": suggestions,
            "sources": sources,
            "model": "iaedu-agent",
            "cost_usd": None,
            "prompt_hash": prompt_hash,
            "prompt_version": PROMPT_VERSION,
            "quality_summary": summarize_flags(suggestions),
            "plan_only": True,
            "monthly_budget": portfolio.get("monthly_budget", 0),
            "total_buy_eur": total_buy_eur,
        }
        # Upsert single-row latest analysis
        latest = db.query(PlanAnalysisLatest).first()
        if latest is None:
            latest = PlanAnalysisLatest(id=1, payload_json=json.dumps(out, ensure_ascii=False))
            db.add(latest)
        else:
            latest.payload_json = json.dumps(out, ensure_ascii=False)
            latest.generated_at = datetime.now()
        db.commit()
    else:
        signal = InvestmentSignal(
            headline=str(parsed.get("headline", ""))[:500],
            market_summary=str(parsed.get("market_summary", "")),
            suggestions_json=json.dumps(suggestions, ensure_ascii=False),
            sources_json=json.dumps(sources, ensure_ascii=False),
            raw_response=raw,
            model="iaedu-agent",
            cost_usd=None,
            prompt_hash=prompt_hash,
            prompt_version=PROMPT_VERSION,
        )
        db.add(signal)
        db.commit()
        db.refresh(signal)
        out = _serialize(signal)
    out["total_buy_eur"] = total_buy_eur
    out["monthly_budget"] = monthly_budget_val
    out["macro_snapshot"] = macro
    out["onchain_snapshot"] = onchain
    out["news_sentiment"] = news_sentiment_agg
    out["earnings_upcoming"] = {t: e for t, e in (earnings or {}).items() if e}
    out["fundamentals_count"] = sum(1 for f in (fundamentals or {}).values() if f.get("available"))
    out["insider_count"] = sum(1 for i in (insider or {}).values() if i.get("available"))
    out["quality_summary"] = summarize_flags(suggestions)
    return out


@router.get("/plan-analysis-latest")
def get_latest_plan_analysis(db: Session = Depends(get_db)):
    """Devolve a última análise do plano persistida, ou null se nunca foi gerada."""
    latest = db.query(PlanAnalysisLatest).first()
    if latest is None or not latest.payload_json:
        return None
    try:
        payload = json.loads(latest.payload_json)
    except (json.JSONDecodeError, TypeError):
        return None
    payload["persisted_at"] = latest.generated_at.isoformat() if latest.generated_at else None
    return payload


@router.delete("/plan-analysis-latest")
def delete_latest_plan_analysis(db: Session = Depends(get_db)):
    latest = db.query(PlanAnalysisLatest).first()
    if latest is not None:
        db.delete(latest)
        db.commit()
    return {"deleted": True}


@router.post("/analyze-plan")
async def analyze_plan(body: AnalyzePlanRequest = AnalyzePlanRequest(), db: Session = Depends(get_db)):
    """Atalho: corre o pipeline em modo plan_only (sem watchlist, sem persistir).

    Usado pela página Planeamento — devolve análise actual focada no plano de alocação.
    """
    return await generate_signal(
        GenerateRequest(
            extra_question=body.extra_question,
            plan_only=True,
            excluded_tickers=body.excluded_tickers,
        ),
        db,
    )


@router.post("/{signal_id}/refresh-performance")
def refresh_performance(signal_id: int, db: Session = Depends(get_db)):
    """Recompute current_price + pct_since_generation for every suggestion in this signal."""
    s = db.query(InvestmentSignal).filter(InvestmentSignal.id == signal_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Sinal não encontrado")

    suggestions = json.loads(s.suggestions_json or "[]")
    now_iso = datetime.now().isoformat(timespec="seconds")
    for sug in suggestions:
        ticker = sug.get("ticker", "").strip().upper()
        if not ticker:
            continue
        try:
            price = get_quick_price(ticker, sug.get("asset_type", "stock"))
        except Exception as e:
            logger.warning(f"Price fetch failed for {ticker}: {e}")
            price = None
        if price:
            sug["current_price"] = round(price, 4)
            base = sug.get("price_at_generation")
            if isinstance(base, (int, float)) and base > 1e-9:
                sug["pct_since_generation"] = round((price / base - 1) * 100, 2)
            elif not base:
                # Legacy signals without entry price: do NOT fake history.
                # Mark as backfilled so the UI knows pct_since is meaningless.
                sug["backfilled_price"] = True
                sug["pct_since_generation"] = None
        sug["last_price_check"] = now_iso

    s.suggestions_json = json.dumps(suggestions, ensure_ascii=False)
    db.commit()
    db.refresh(s)
    return _serialize(s)


@router.post("/refresh-all-performance")
def refresh_all_performance(db: Session = Depends(get_db)):
    """Refresh prices for every signal in the DB. Use sparingly — hits Yahoo for each ticker."""
    signals = db.query(InvestmentSignal).order_by(InvestmentSignal.generated_at.desc()).all()
    updated = 0
    for s in signals:
        suggestions = json.loads(s.suggestions_json or "[]")
        if not suggestions:
            continue
        now_iso = datetime.now().isoformat(timespec="seconds")
        for sug in suggestions:
            ticker = sug.get("ticker", "").strip().upper()
            if not ticker:
                continue
            price = get_quick_price(ticker, sug.get("asset_type", "stock"))
            if price:
                sug["current_price"] = round(price, 4)
                base = sug.get("price_at_generation")
                if base and base > 0:
                    sug["pct_since_generation"] = round((price / base - 1) * 100, 2)
                else:
                    sug["price_at_generation"] = round(price, 4)
                    sug["pct_since_generation"] = 0.0
            sug["last_price_check"] = now_iso
        s.suggestions_json = json.dumps(suggestions, ensure_ascii=False)
        updated += 1
    db.commit()
    return {"signals_updated": updated}


@router.delete("/{signal_id}")
def delete_signal(signal_id: int, db: Session = Depends(get_db)):
    s = db.query(InvestmentSignal).filter(InvestmentSignal.id == signal_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Sinal não encontrado")
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.get("/health")
def feeds_health():
    """Return last-known status of every news feed (in-memory, cleared on restart)."""
    return {
        "feeds": [
            {
                "name": name,
                **_FEED_HEALTH.get(name, {"ok": None, "count": 0, "last_check": None, "error": "ainda não verificado"}),
            }
            for name, _ in NEWS_FEEDS
        ]
    }


@router.get("/preview-news")
def preview_news():
    """Debug endpoint — see what the collector grabs without spending API tokens."""
    news = collect_news(per_feed=5)
    sentiment = collect_sentiment()
    return {"count": len(news), "sentiment": sentiment, "news": news[:30]}


@router.get("/preview-market")
def preview_market(db: Session = Depends(get_db)):
    """Debug endpoint — see the quantitative data block that's sent to the AI."""
    portfolio = _portfolio_snapshot(db)
    market = collect_market_data(portfolio["candidate_tickers"])
    return {
        "candidate_tickers": portfolio["candidate_tickers"],
        "metrics": market,
        "as_prompt": "\n".join(format_metrics_for_prompt(m) for m in market.values()),
    }


@router.get("/preview-macro")
def preview_macro():
    """Debug endpoint — current macro regime snapshot."""
    snap = fetch_macro_snapshot()
    return {"snapshot": snap, "as_prompt": format_macro_for_prompt(snap)}


@router.get("/preview-onchain")
def preview_onchain():
    snap = fetch_onchain_snapshot()
    return {"snapshot": snap, "as_prompt": format_onchain_for_prompt(snap)}


@router.get("/preview-fundamentals")
def preview_fundamentals(db: Session = Depends(get_db)):
    portfolio = _portfolio_snapshot(db)
    stock_tickers = [t for t, at in portfolio["candidate_tickers"] + WATCHLIST if at == "stock"]
    fund = fetch_fundamentals_batch(stock_tickers)
    return {
        "enabled": fmp_enabled(),
        "data": fund,
        "as_prompt": format_fundamentals_for_prompt(fund),
    }


@router.get("/preview-earnings")
def preview_earnings(db: Session = Depends(get_db)):
    portfolio = _portfolio_snapshot(db)
    stock_tickers = [t for t, at in portfolio["candidate_tickers"] + WATCHLIST if at == "stock"]
    cal = fetch_earnings_for_tickers(stock_tickers, 30)
    return {
        "enabled": finnhub_enabled(),
        "data": cal,
        "as_prompt": format_earnings_for_prompt(cal),
    }


@router.get("/preview-insider")
def preview_insider(db: Session = Depends(get_db)):
    portfolio = _portfolio_snapshot(db)
    stock_tickers = [t for t, at in portfolio["candidate_tickers"] + WATCHLIST if at == "stock"]
    targets = [t for t in stock_tickers if t.upper() in TICKER_TO_CIK]
    data = fetch_insider_batch(targets, 30)
    return {"data": data, "as_prompt": format_insider_for_prompt(data)}


@router.get("/preview-regime")
def preview_regime():
    snap = fetch_regime_snapshot()
    return {"snapshot": snap, "as_prompt": format_regime_for_prompt(snap)}


@router.get("/preview-earnings-momentum")
def preview_earnings_momentum(db: Session = Depends(get_db)):
    portfolio = _portfolio_snapshot(db)
    stock_tickers = [t for t, at in portfolio["candidate_tickers"] + WATCHLIST if at == "stock"]
    data = fetch_earnings_momentum(stock_tickers)
    return {
        "enabled": finnhub_enabled(),
        "data": data,
        "as_prompt": format_earnings_momentum_for_prompt(data),
    }


@router.get("/preview-sentiment-delta")
def preview_sentiment_delta():
    delta = compute_sentiment_delta()
    return {"data": delta, "as_prompt": format_sentiment_delta_for_prompt(delta)}


@router.get("/preview-funding")
def preview_funding():
    btc = compute_funding_persistence("BTC")
    eth = compute_funding_persistence("ETH")
    lines = []
    if btc:
        lines.append(format_funding_persistence_for_prompt(btc))
    if eth:
        lines.append(format_funding_persistence_for_prompt(eth))
    return {
        "btc": btc,
        "eth": eth,
        "as_prompt": "\n".join(lines) if lines else "  (funding persistence indisponível)",
    }


@router.get("/history-regime")
def history_regime(days: int = 60):
    return {"history": fetch_regime_history(days)}


@router.get("/history-sentiment")
def history_sentiment(days: int = 60):
    return {"history": fetch_sentiment_history(days)}


@router.get("/history-funding")
def history_funding(days: int = 60):
    return {
        "btc": fetch_funding_history("BTC", days),
        "eth": fetch_funding_history("ETH", days),
    }


CRITIQUE_PROMPT = """És um risk officer cético a rever sugestões de investimento de outro analista.
A tua função é encontrar fraquezas, vieses e contradições. Não és construtivo — és cirúrgico.

Para CADA sugestão recebida, devolves um item no array com:
- ticker
- weaknesses: lista de 1-3 fraquezas concretas (ex: "RSI 71 não suporta BUY", "tese ignora yield curve invertida")
- contradicting_evidence: 1-2 dados do contexto que contradizem a tese
- adjusted_conviction: tua opinião sobre a convicção (high|medium|low)
- verdict: "valid" | "weak" | "reject"

OUTPUT: APENAS JSON puro:
{
  "critiques": [
    {"ticker":"BTC","weaknesses":["..."],"contradicting_evidence":["..."],"adjusted_conviction":"low","verdict":"weak"}
  ]
}"""


@router.post("/{signal_id}/critique")
async def critique_signal(signal_id: int, db: Session = Depends(get_db)):
    """Run a 2nd-pass risk-officer review of an existing signal.

    Costs an extra agent call. Updates the signal with risk_critique JSON
    that the UI can render side-by-side with the original thesis.
    """
    s = db.query(InvestmentSignal).filter(InvestmentSignal.id == signal_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Sinal não encontrado")

    suggestions = json.loads(s.suggestions_json or "[]")
    if not suggestions:
        raise HTTPException(status_code=400, detail="Sinal sem sugestões a criticar")

    # Pass the original sugs back as input — keep the prompt small
    sug_blob = json.dumps([
        {
            "ticker": x.get("ticker"),
            "action": x.get("action"),
            "conviction": x.get("conviction"),
            "thesis": x.get("thesis"),
            "amount_eur": x.get("amount_eur"),
        }
        for x in suggestions
    ], ensure_ascii=False)

    user_prompt = f"""Headline original: {s.headline}
Resumo do mercado: {s.market_summary}

Sugestões a criticar (JSON):
{sug_blob}

Identifica fraquezas em cada uma. Devolve o JSON pedido."""

    try:
        raw = await _call_agent(CRITIQUE_PROMPT, user_prompt)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Critique agent call failed: {e}")
        raise HTTPException(status_code=502, detail=f"Erro a contactar o agente IA: {e}")

    try:
        parsed = _extract_json(raw)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=f"Critique sem JSON ({e}): {raw[:300]}")

    critiques = parsed.get("critiques", [])
    crit_by_ticker = {(c.get("ticker") or "").upper(): c for c in critiques if isinstance(c, dict)}

    # Merge into suggestions
    for sug in suggestions:
        t = (sug.get("ticker") or "").upper()
        if t in crit_by_ticker:
            sug["risk_critique"] = crit_by_ticker[t]

    s.suggestions_json = json.dumps(suggestions, ensure_ascii=False)
    db.commit()
    db.refresh(s)
    return _serialize(s)


@router.get("/alerts")
def alerts_endpoint(db: Session = Depends(get_db)):
    """Triage of action-worthy events from existing signals + upcoming earnings.

    Categories:
      - drawdown:        a recent BUY suggestion is down >5% in <14d
      - stop_hit:        current_price ≤ stop_loss_price
      - watch_breakout:  WATCH suggestion has run +3% since generation
      - earnings_soon:   any held / suggested ticker has earnings in ≤3d
      - flag_pending:    high-quality-flag count growing in recent signals
    """
    from datetime import timedelta as _td

    alerts: list[dict] = []
    rows = _collect_outcomes(db)
    now = datetime.now()

    # Latest signal id by ticker — only alert on the most recent suggestion per ticker
    latest_by_ticker: dict[str, dict] = {}
    for r in sorted(rows, key=lambda x: x.get("generated_at") or ""):
        latest_by_ticker[r["ticker"]] = r

    for ticker, r in latest_by_ticker.items():
        gen = r.get("generated_at")
        try:
            gen_dt = datetime.fromisoformat(gen) if gen else None
        except (ValueError, TypeError):
            gen_dt = None
        days_since = (now - gen_dt).days if gen_dt else None

        pct = r.get("pct_since_generation")

        # 1. Drawdown
        if r.get("action") == "buy" and pct is not None and pct < -5 and (days_since is None or days_since <= 14):
            alerts.append({
                "type": "drawdown",
                "severity": "high" if pct < -10 else "medium",
                "ticker": ticker,
                "signal_id": r["signal_id"],
                "title": f"{ticker} caiu {pct}% desde a sugestão",
                "detail": f"BUY há {days_since}d, preço atual {r.get('current_price')} vs entrada {r.get('price_at_generation')}",
            })

        # 2. Stop hit
        # Pull the suggestion to check stop_loss_price
        sig = db.query(InvestmentSignal).filter(InvestmentSignal.id == r["signal_id"]).first()
        if sig:
            for sug in json.loads(sig.suggestions_json or "[]"):
                if (sug.get("ticker") or "").upper() != ticker:
                    continue
                stop = sug.get("stop_loss_price")
                cur = sug.get("current_price")
                if stop and cur and cur <= stop and r.get("action") == "buy":
                    alerts.append({
                        "type": "stop_hit",
                        "severity": "high",
                        "ticker": ticker,
                        "signal_id": r["signal_id"],
                        "title": f"{ticker} bateu stop-loss",
                        "detail": f"preço {cur} ≤ stop {stop} (entrada {sug.get('price_at_generation')})",
                    })

        # 3. Watch breakout
        if r.get("action") == "watch" and pct is not None and pct > 3 and (days_since is None or days_since <= 14):
            alerts.append({
                "type": "watch_breakout",
                "severity": "medium",
                "ticker": ticker,
                "signal_id": r["signal_id"],
                "title": f"{ticker} subiu {pct}% desde 'watch'",
                "detail": "Pode ser entrada — re-avaliar tese",
            })

    # 4. Earnings ≤3d for any tracked ticker (portfolio + recent suggestions)
    if finnhub_enabled():
        portfolio = _portfolio_snapshot(db)
        all_t = list({t for t, _ in portfolio["candidate_tickers"] + WATCHLIST}) + list(latest_by_ticker.keys())
        seen: set[str] = set()
        unique_tickers = [t for t in all_t if not (t in seen or seen.add(t))]
        cal = fetch_earnings_for_tickers(unique_tickers, 7)
        for t, e in cal.items():
            if not e:
                continue
            d = e.get("days_until")
            if isinstance(d, int) and d <= 3:
                alerts.append({
                    "type": "earnings_soon",
                    "severity": "high" if d <= 1 else "medium",
                    "ticker": t,
                    "title": f"{t} earnings em {d}d",
                    "detail": f"data {e.get('date')}, EPS estimado {e.get('eps_estimate')}",
                })

    # Sort: high severity first, then by ticker
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: (severity_rank.get(a.get("severity"), 9), a.get("ticker", "")))

    return {"count": len(alerts), "alerts": alerts}


@router.get("/data-sources")
def data_sources_status():
    """Aggregate status of all data integrations."""
    return {
        "fmp_fundamentals":   {"enabled": fmp_enabled(),     "needs_key": "FMP_API_KEY"},
        "finnhub_earnings":   {"enabled": finnhub_enabled(), "needs_key": "FINNHUB_API_KEY"},
        "fred_macro":         {"enabled": True, "needs_key": None},
        "coinmetrics_onchain": {"enabled": True, "needs_key": None},
        "sec_edgar_insider":  {"enabled": True, "needs_key": None},
        "iaedu_agent":        {"enabled": True, "needs_key": None},
        "telegram_notify":    {"enabled": telegram_enabled(), "needs_key": "TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID"},
    }


@router.post("/test-notify")
def test_notify():
    """Send a test notification through every available channel. Useful after setting up Telegram."""
    result = notify(
        "Teste Cristopher",
        f"Notificação de teste enviada às {datetime.now().strftime('%H:%M:%S')}.",
        severity="info",
    )
    return {"sent": result, "telegram_configured": telegram_enabled()}


@router.get("/cache-stats")
def cache_stats_endpoint():
    """Inspect what's currently cached + ages."""
    return cache_stats()


@router.post("/cache-clear")
def cache_clear(prefix: str = ""):
    """Drop entries (default: all). Use prefix=`fundamentals:fmp` to target a single source."""
    deleted = cache_invalidate(prefix)
    return {"deleted": deleted, "prefix": prefix or "(all)"}


# ── Calibration & backtest ─────────────────────────────────────

# Maps conviction labels to implied probability of beating the hit threshold (not just zero).
CONVICTION_PROB = {"low": 0.55, "medium": 0.65, "high": 0.80}
HIT_THRESHOLD_PCT = 1.0    # cover round-trip fees + spread before counting a "hit"


def _collect_outcomes(db: Session) -> list[dict]:
    """Flatten all suggestions into rows with outcome data for stats.

    Returns rows: {ticker, asset_type, action, conviction, amount_eur,
                   pct_since_generation, days_since_signal, signal_id, generated_at}
    Only rows with `pct_since_generation != None` are included.
    """
    rows: list[dict] = []
    signals = db.query(InvestmentSignal).order_by(InvestmentSignal.generated_at.asc()).all()
    for s in signals:
        suggestions = json.loads(s.suggestions_json or "[]")
        gen = s.generated_at
        for sug in suggestions:
            pct = sug.get("pct_since_generation")
            if pct is None:
                continue
            days = (datetime.now() - gen).days if gen else 0
            rows.append({
                "signal_id": s.id,
                "generated_at": gen.isoformat() if gen else None,
                "ticker": (sug.get("ticker") or "").upper(),
                "name": sug.get("name"),
                "asset_type": sug.get("asset_type", "stock"),
                "action": sug.get("action", "buy"),
                "conviction": sug.get("conviction", "medium"),
                "amount_eur": sug.get("amount_eur"),
                "price_at_generation": sug.get("price_at_generation"),
                "current_price": sug.get("current_price"),
                "pct_since_generation": pct,
                "days_since_signal": days,
                "quality_flags": sug.get("quality_flags") or [],
            })
    return rows


@router.get("/calibration")
def calibration_stats(db: Session = Depends(get_db)):
    """Aggregate hit rate, Brier score and bias breakdown across all stored signals."""
    rows = _collect_outcomes(db)
    if not rows:
        return {"sample_size": 0, "message": "Sem sinais com performance registada ainda."}

    # Only count actionable signals (buy/hold/watch) for outcomes
    eligible = [r for r in rows if r["action"] in ("buy", "hold", "watch")]
    if not eligible:
        return {"sample_size": 0, "message": "Sem sugestões 'buy'/'hold'/'watch' suficientes."}

    def _hit_rate(rs: list[dict]) -> float | None:
        if not rs:
            return None
        hits = sum(1 for r in rs if (r["pct_since_generation"] or 0) > HIT_THRESHOLD_PCT)
        return round(hits / len(rs) * 100, 1)

    def _avg_return(rs: list[dict]) -> float | None:
        if not rs:
            return None
        return round(sum(r["pct_since_generation"] or 0 for r in rs) / len(rs), 2)

    # Overall
    overall = {
        "n": len(eligible),
        "hit_rate_pct": _hit_rate(eligible),
        "avg_return_pct": _avg_return(eligible),
        "avg_winner_pct": _avg_return([r for r in eligible if (r["pct_since_generation"] or 0) > 0]),
        "avg_loser_pct": _avg_return([r for r in eligible if (r["pct_since_generation"] or 0) < 0]),
    }

    # By conviction (this is the calibration check)
    by_conviction = {}
    brier_terms = []
    for c in ("high", "medium", "low"):
        rs = [r for r in eligible if r["conviction"] == c]
        if not rs:
            continue
        n = len(rs)
        hit = sum(1 for r in rs if (r["pct_since_generation"] or 0) > HIT_THRESHOLD_PCT) / n
        expected = CONVICTION_PROB.get(c, 0.5)
        # Brier: each obs contributes (expected - outcome)^2
        for r in rs:
            outcome = 1.0 if (r["pct_since_generation"] or 0) > HIT_THRESHOLD_PCT else 0.0
            brier_terms.append((expected - outcome) ** 2)
        by_conviction[c] = {
            "n": n,
            "expected_hit_rate_pct": round(expected * 100, 0),
            "actual_hit_rate_pct": round(hit * 100, 1),
            "calibration_gap_pct": round((hit - expected) * 100, 1),
            "avg_return_pct": _avg_return(rs),
        }

    brier_score = round(sum(brier_terms) / len(brier_terms), 4) if brier_terms else None

    # By asset_type
    by_asset = {}
    for at in set(r["asset_type"] for r in eligible):
        rs = [r for r in eligible if r["asset_type"] == at]
        by_asset[at] = {
            "n": len(rs),
            "hit_rate_pct": _hit_rate(rs),
            "avg_return_pct": _avg_return(rs),
        }

    # Best & worst suggestions (for trust calibration)
    sorted_by_ret = sorted(eligible, key=lambda r: r["pct_since_generation"] or 0)
    worst = sorted_by_ret[:3]
    best = list(reversed(sorted_by_ret[-3:]))

    # Quality flag impact: do flagged suggestions hit less often?
    flagged = [r for r in eligible if r["quality_flags"]]
    unflagged = [r for r in eligible if not r["quality_flags"]]
    flag_impact = {
        "flagged_n": len(flagged),
        "flagged_hit_rate_pct": _hit_rate(flagged),
        "unflagged_n": len(unflagged),
        "unflagged_hit_rate_pct": _hit_rate(unflagged),
    }

    return {
        "sample_size": len(eligible),
        "brier_score": brier_score,  # lower is better; <0.20 ok, <0.15 good
        "overall": overall,
        "by_conviction": by_conviction,
        "by_asset_type": by_asset,
        "best": [
            {"ticker": r["ticker"], "pct": r["pct_since_generation"], "signal_id": r["signal_id"]}
            for r in best
        ],
        "worst": [
            {"ticker": r["ticker"], "pct": r["pct_since_generation"], "signal_id": r["signal_id"]}
            for r in worst
        ],
        "flag_impact": flag_impact,
    }


@router.get("/calibration-decay")
def calibration_decay(db: Session = Depends(get_db)):
    """Average return + hit rate at fixed horizons post-signal (7d/14d/30d/60d).

    Tells us if signal alpha decays fast or persists. Uses Yahoo daily closes
    per-ticker (cached via _load_history). Signals younger than a horizon
    are excluded from that horizon's aggregate.
    """
    from datetime import timedelta as _td

    rows = _collect_outcomes(db)
    eligible = [r for r in rows if r["action"] == "buy" and r["price_at_generation"] and r["generated_at"]]
    if not eligible:
        return {"sample_size": 0, "message": "Sem 'buy' com price_at_generation."}

    horizons = [7, 14, 30, 60]
    buckets: dict[int, list[float]] = {h: [] for h in horizons}

    today = datetime.now().date()
    histories: dict[str, dict[str, float]] = {}

    for r in eligible:
        ticker = r["ticker"]
        if not ticker:
            continue
        # Try ticker as-is; for crypto, append -USD if missing
        symbol = ticker.upper()
        if r["asset_type"] == "crypto" and "-" not in symbol:
            symbol = f"{symbol}-USD"
        if symbol not in histories:
            histories[symbol] = _load_history(symbol)
        hist = histories[symbol]
        if not hist:
            continue

        try:
            gen_date = datetime.fromisoformat(r["generated_at"][:10]).date()
        except ValueError:
            continue

        entry_close = _spy_close_on_or_before(gen_date.isoformat(), hist)
        if not entry_close:
            continue

        for h in horizons:
            target_date = gen_date + _td(days=h)
            if target_date > today:
                continue   # not enough time elapsed yet
            future_close = _spy_close_on_or_before(target_date.isoformat(), hist)
            if not future_close:
                continue
            ret_pct = (future_close / entry_close - 1) * 100
            buckets[h].append(ret_pct)

    def _summarize(returns: list[float]) -> dict:
        n = len(returns)
        if n == 0:
            return {"n": 0, "hit_rate_pct": None, "avg_return_pct": None,
                    "median_return_pct": None}
        hits = sum(1 for x in returns if x > HIT_THRESHOLD_PCT)
        sorted_r = sorted(returns)
        median = sorted_r[n // 2] if n % 2 else (sorted_r[n // 2 - 1] + sorted_r[n // 2]) / 2
        return {
            "n": n,
            "hit_rate_pct": round(hits / n * 100, 1),
            "avg_return_pct": round(sum(returns) / n, 2),
            "median_return_pct": round(median, 2),
        }

    return {
        "sample_size": len(eligible),
        "by_horizon": {f"{h}d": _summarize(buckets[h]) for h in horizons},
    }


@router.get("/calibration-by-context")
def calibration_by_context(db: Session = Depends(get_db)):
    """Hit rate broken down by market context at the time of signal generation.

    Joins each signal's `generated_at` against `daily_regime`, `daily_sentiment`,
    `daily_funding`. Answers: "do regime/sentiment/funding signals predict outcome?"
    """
    rows = _collect_outcomes(db)
    eligible = [r for r in rows if r["action"] in ("buy", "hold", "watch")]
    if not eligible:
        return {"sample_size": 0, "message": "Sem sinais com performance registada."}

    # Pull all 3 history tables at once
    import sqlite3
    try:
        conn = sqlite3.connect("cristopher.db")
        regime_by_date = {
            r[0]: {"p_risk_off": r[1], "classification": r[2]}
            for r in conn.execute(
                "SELECT date, p_risk_off, classification FROM daily_regime"
            ).fetchall()
        }
        sentiment_by_date = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT date, avg_score FROM daily_sentiment"
            ).fetchall()
        }
        funding_btc_by_date = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT date, rate_pct FROM daily_funding WHERE symbol = 'BTC'"
            ).fetchall()
        }
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"calibration-by-context db read failed: {e}")
        return {"sample_size": 0, "message": "Erro a ler tabelas de contexto."}

    def _hit_rate(rs: list[dict]) -> float | None:
        if not rs:
            return None
        hits = sum(1 for r in rs if (r["pct_since_generation"] or 0) > HIT_THRESHOLD_PCT)
        return round(hits / len(rs) * 100, 1)

    def _avg_return(rs: list[dict]) -> float | None:
        if not rs:
            return None
        return round(sum(r["pct_since_generation"] or 0 for r in rs) / len(rs), 2)

    # Bucket by regime classification at generation date
    by_regime: dict[str, list[dict]] = {"risk-on": [], "neutral": [], "risk-off": [], "no_data": []}
    by_sentiment: dict[str, list[dict]] = {"negative_swing": [], "neutral": [], "positive_swing": [], "no_data": []}
    by_funding: dict[str, list[dict]] = {"long_skew_extreme": [], "short_skew_extreme": [], "neutral": [], "no_data": []}

    for r in eligible:
        gen_iso = r.get("generated_at")
        if not gen_iso:
            continue
        date_key = gen_iso[:10]   # ISO date

        cls = (regime_by_date.get(date_key) or {}).get("classification", "no_data")
        by_regime.setdefault(cls, []).append(r)

        s = sentiment_by_date.get(date_key)
        if s is None:
            sb = "no_data"
        elif s >= 0.10:
            sb = "positive_swing"
        elif s <= -0.10:
            sb = "negative_swing"
        else:
            sb = "neutral"
        by_sentiment[sb].append(r)

        f = funding_btc_by_date.get(date_key)
        if f is None:
            fb = "no_data"
        elif f >= 15.0:
            fb = "long_skew_extreme"
        elif f <= -15.0:
            fb = "short_skew_extreme"
        else:
            fb = "neutral"
        by_funding[fb].append(r)

    def _summarize(buckets: dict[str, list[dict]]) -> dict:
        return {
            k: {"n": len(v), "hit_rate_pct": _hit_rate(v), "avg_return_pct": _avg_return(v)}
            for k, v in buckets.items() if v
        }

    return {
        "sample_size": len(eligible),
        "by_regime": _summarize(by_regime),
        "by_sentiment": _summarize(by_sentiment),
        "by_funding": _summarize(by_funding),
    }


# ── Backtest vs SPY ────────────────────────────────────────────

# In-process cache for benchmark histories.
_BENCHMARK_HISTORY: dict[str, dict[str, float]] = {}
_BENCHMARK_FETCHED_AT: dict[str, datetime] = {}
_SPY_TTL_HOURS = 12

# Multi-asset benchmark composition matching this user's allocation plan
COMPOSITE_BENCHMARK = {
    "SPY": 0.60,    # equity (US-listed proxy for VWCE/world equity)
    "BTC-USD": 0.30,
    "GLD": 0.10,
}


def _load_history(symbol: str, force: bool = False) -> dict[str, float]:
    """Yahoo 2y daily closes for `symbol`, indexed by ISO date."""
    fetched = _BENCHMARK_FETCHED_AT.get(symbol)
    age_hours = (datetime.now() - fetched).total_seconds() / 3600 if fetched else 9999
    if symbol in _BENCHMARK_HISTORY and not force and age_hours < _SPY_TTL_HOURS:
        return _BENCHMARK_HISTORY[symbol]

    import httpx as _httpx
    try:
        r = _httpx.get(
            f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"range": "2y", "interval": "1d"},
            headers={"User-Agent": "Mozilla/5.0 Cristopher/1.0"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        chart = (data.get("chart") or {}).get("result") or []
        if not chart:
            return _BENCHMARK_HISTORY.get(symbol, {})
        c = chart[0]
        ts = c.get("timestamp") or []
        closes = ((c.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        out: dict[str, float] = {}
        for t, v in zip(ts, closes):
            if v is None:
                continue
            d = datetime.fromtimestamp(t).date().isoformat()
            out[d] = float(v)
        _BENCHMARK_HISTORY[symbol] = out
        _BENCHMARK_FETCHED_AT[symbol] = datetime.now()
        return out
    except Exception as e:
        logger.warning(f"history fetch failed for {symbol}: {e}")
        return _BENCHMARK_HISTORY.get(symbol, {})


def _load_spy_history(force: bool = False) -> dict[str, float]:
    return _load_history("SPY", force=force)


def _composite_close_on(date_iso: str, histories: dict[str, dict[str, float]]) -> Optional[float]:
    """Weighted-average normalized close at `date_iso`, where each asset is normalized
    to its own series start = 1.0. Returns None if any constituent is missing."""
    val = 0.0
    for symbol, weight in COMPOSITE_BENCHMARK.items():
        h = histories.get(symbol) or {}
        if not h:
            return None
        first = next(iter(h.values()))
        if not first:
            return None
        spot = _spy_close_on_or_before(date_iso, h)
        if spot is None:
            return None
        val += weight * (spot / first)
    return val


def _spy_close_on_or_before(date_iso: str, spy: dict[str, float]) -> float | None:
    """Find SPY close at the signal date or the closest prior trading day."""
    if not spy:
        return None
    if date_iso in spy:
        return spy[date_iso]
    # Walk back up to 7 days
    target = datetime.fromisoformat(date_iso).date()
    for delta in range(1, 8):
        from datetime import timedelta as _td
        prev = (target - _td(days=delta)).isoformat()
        if prev in spy:
            return spy[prev]
    return None


@router.get("/backtest")
def backtest_vs_spy(db: Session = Depends(get_db), benchmark: str = "spy"):
    """Compare each suggestion's return to a benchmark over the same period.

    benchmark: 'spy' (S&P 500) or 'composite' (60% SPY + 30% BTC + 10% GLD).
    """
    rows = _collect_outcomes(db)
    eligible = [r for r in rows if r["action"] == "buy" and r["price_at_generation"] is not None]
    if not eligible:
        return {"sample_size": 0, "message": "Sem sugestões 'buy' com preço de entrada registado.", "benchmark": benchmark}

    if benchmark == "composite":
        # Pre-load all constituent histories
        histories = {sym: _load_history(sym) for sym in COMPOSITE_BENCHMARK}
        if not all(histories.values()):
            raise HTTPException(status_code=502, detail="Falha a obter histórico para o benchmark composto")
        # Today's composite: same formula
        today_iso = max(max(h.keys()) for h in histories.values() if h)
        bench_now = _composite_close_on(today_iso, histories)
        bench_label = "60% SPY + 30% BTC + 10% GLD"
    else:
        spy = _load_spy_history()
        if not spy:
            raise HTTPException(status_code=502, detail="Falha a obter histórico do SPY")
        bench_now = list(spy.values())[-1]
        bench_label = "SPY"

    enriched = []
    alpha_sum = 0.0
    beat_count = 0
    for r in eligible:
        gen_date = (r["generated_at"] or "")[:10]
        if not gen_date:
            continue
        if benchmark == "composite":
            bench_at = _composite_close_on(gen_date, histories)
        else:
            bench_at = _spy_close_on_or_before(gen_date, spy)
        if not bench_at:
            continue
        bench_ret = (bench_now / bench_at - 1) * 100
        sug_ret = r["pct_since_generation"] or 0
        alpha = round(sug_ret - bench_ret, 2)
        alpha_sum += alpha
        beat = sug_ret > bench_ret
        if beat:
            beat_count += 1
        enriched.append({
            **r,
            "benchmark_at_signal": round(bench_at, 4),
            "benchmark_now": round(bench_now, 4),
            "benchmark_return_pct": round(bench_ret, 2),
            "alpha_pct": alpha,
            "beat_benchmark": beat,
        })

    if not enriched:
        return {"sample_size": 0, "message": "Sem dados suficientes do benchmark para o período.", "benchmark": benchmark}

    n = len(enriched)
    hit_pct = round(beat_count / n * 100, 1)
    avg_alpha = round(alpha_sum / n, 2)
    by_conviction: dict = {}
    for c in ("high", "medium", "low"):
        rs = [e for e in enriched if e["conviction"] == c]
        if not rs:
            continue
        by_conviction[c] = {
            "n": len(rs),
            "beat_benchmark_pct": round(sum(1 for e in rs if e["beat_benchmark"]) / len(rs) * 100, 1),
            "avg_alpha_pct": round(sum(e["alpha_pct"] for e in rs) / len(rs), 2),
        }

    return {
        "sample_size": n,
        "benchmark": benchmark,
        "benchmark_label": bench_label,
        "hit_rate_vs_benchmark_pct": hit_pct,
        "avg_alpha_pct": avg_alpha,
        "by_conviction": by_conviction,
        "rows": enriched[-30:],
        "benchmark_now": round(bench_now, 4),
    }
