"""Standalone daily script — collects news, calls the iaedu.pt agent, stores a new signal.

Run manually:
    cd backend && source venv/bin/activate && python scripts/daily_signal.py

Or via launchd / cron (see scripts/com.cristopher.daily-signal.plist).
"""
import sys
import os
import json
import asyncio
import logging

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("daily_signal")


async def _run() -> int:
    from datetime import datetime, date
    from database import SessionLocal
    from models import InvestmentSignal
    from routers.investment_signals import (
        collect_news, collect_sentiment, collect_market_data, _portfolio_snapshot,
        _build_user_prompt, _call_agent, _extract_json, SYSTEM_PROMPT,
        _enrich_suggestions_with_prices, WATCHLIST, PROMPT_VERSION,
    )
    import hashlib
    from macro_data import fetch_macro_snapshot
    from signal_validation import validate_suggestions
    from onchain_data import fetch_onchain_snapshot
    from insider_data import fetch_insider_batch, TICKER_TO_CIK
    from news_sentiment import classify_headlines, aggregate_sentiment, filter_by_relevance
    from fundamentals_data import fetch_fundamentals_batch
    from earnings_data import fetch_earnings_for_tickers
    from risk_management import apply_risk_overlays
    from notifier import notify

    db = SessionLocal()
    try:
        # Skip if we already generated a signal today (prevents double-runs from RunAtLoad)
        today = date.today()
        existing = (
            db.query(InvestmentSignal)
            .filter(InvestmentSignal.generated_at >= datetime.combine(today, datetime.min.time()))
            .first()
        )
        if existing and not os.getenv("FORCE"):
            log.info(f"Already have signal #{existing.id} from today ({existing.generated_at}). Skipping. (Set FORCE=1 to override)")
            return 0

        log.info("Collecting news…")
        news = collect_news(per_feed=8)
        if not news:
            log.error("No news collected. Aborting.")
            return 1
        log.info(f"Got {len(news)} headlines")

        sentiment = collect_sentiment()
        portfolio = _portfolio_snapshot(db)
        log.info("Fetching market data for portfolio + watchlist…")
        market_data = collect_market_data(portfolio["candidate_tickers"])
        log.info(f"Got metrics for {len(market_data)} tickers")
        log.info("Fetching FRED macro snapshot…")
        macro = fetch_macro_snapshot()
        log.info(f"Macro regime: {macro.get('regime')}")

        log.info("Fetching on-chain crypto…")
        onchain = fetch_onchain_snapshot()

        # Stock-only universe for fundamentals/earnings/insider
        all_tickers = portfolio["candidate_tickers"] + WATCHLIST
        seen_t: set[str] = set()
        deduped = []
        for t, at in all_tickers:
            u = t.upper()
            if u in seen_t:
                continue
            seen_t.add(u)
            deduped.append((t, at))
        stock_tickers = [t for t, at in deduped if at == "stock"]
        insider_targets = [t for t in stock_tickers if t.upper() in TICKER_TO_CIK]

        log.info("Fetching fundamentals (FMP)…")
        fundamentals = fetch_fundamentals_batch(stock_tickers)
        log.info(f"FMP fundamentals: {sum(1 for f in fundamentals.values() if f.get('available'))}/{len(stock_tickers)}")

        log.info("Fetching earnings calendar (Finnhub)…")
        earnings = fetch_earnings_for_tickers(stock_tickers, 30)
        upcoming = [t for t, e in earnings.items() if e]
        log.info(f"Tickers with earnings ≤30d: {len(upcoming)}")

        log.info("Fetching insider activity (SEC EDGAR)…")
        insider = fetch_insider_batch(insider_targets, 30)

        log.info("Classifying headlines…")
        classified = classify_headlines(news)
        agg = aggregate_sentiment(classified)
        log.info(f"News sentiment avg={agg.get('avg')}, engine={agg.get('engine')}")
        top_news = filter_by_relevance(classified, top_k=25)

        prompt = _build_user_prompt(
            portfolio, top_news, sentiment, market_data, macro,
            onchain=onchain, fundamentals=fundamentals, earnings=earnings,
            insider=insider, news_sentiment_agg=agg,
        )

        log.info("Calling iaedu.pt agent…")
        raw = await _call_agent(SYSTEM_PROMPT, prompt)
        parsed = _extract_json(raw)

        sources = [{"title": n["title"], "url": n["url"], "source": n["source"]} for n in news[:50]]
        validated = validate_suggestions(parsed.get("suggestions", []), prompt, portfolio.get("monthly_budget"))
        enriched = _enrich_suggestions_with_prices(validated)
        suggestions = apply_risk_overlays(
            enriched, market_data,
            monthly_budget=portfolio.get("monthly_budget", 300),
            total_portfolio_value=portfolio.get("total_value", 0),
        )

        signal = InvestmentSignal(
            headline=str(parsed.get("headline", ""))[:500],
            market_summary=str(parsed.get("market_summary", "")),
            suggestions_json=json.dumps(suggestions, ensure_ascii=False),
            sources_json=json.dumps(sources, ensure_ascii=False),
            raw_response=raw,
            model="iaedu-agent",
            cost_usd=None,
            prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
            prompt_version=PROMPT_VERSION,
        )
        db.add(signal)
        db.commit()
        db.refresh(signal)
        log.info(f"✓ Saved signal #{signal.id}: {signal.headline}")

        # Notify on success — short summary of top suggestions
        try:
            top_buys = [s for s in suggestions if (s.get("action") or "").lower() == "buy"][:3]
            lines = [f"_{signal.headline}_", ""]
            if macro and macro.get("regime"):
                lines.append(f"Regime: *{macro['regime']}*")
            if top_buys:
                lines.append("\nTop sugestões:")
                for s in top_buys:
                    amt = f" {s.get('amount_eur'):.0f}€" if s.get("amount_eur") else ""
                    lines.append(f"• *{s['ticker']}* {s.get('conviction','?')}{amt}")
            n_flags = sum(1 for s in suggestions if s.get("quality_flags"))
            if n_flags:
                lines.append(f"\n⚠️ {n_flags} sugestões com flags")
            notify(f"Sinal #{signal.id}", "\n".join(lines), severity="info")
        except Exception as e:
            log.debug(f"Notify failed (non-critical): {e}")
        return 0
    except Exception as e:
        log.exception(f"Failed: {e}")
        try:
            notify("Cristopher: signal diário falhou", str(e)[:300], severity="critical")
        except Exception:
            pass
        return 2
    finally:
        db.close()


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
