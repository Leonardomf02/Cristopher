"""SEC EDGAR Form 4 (insider transactions) feed.

Free, no key. SEC requires a User-Agent identifying the requester.
We aggregate the last 30d of cluster buys/sells per ticker to surface
'unusual insider activity' as a contextual signal for the LLM.
"""
from __future__ import annotations

import os
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from xml.etree import ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

# SEC requires a contactable User-Agent. Uses a generic identifier (no personal email).
# Override via env CRISTOPHER_SEC_UA if SEC blocks default.
USER_AGENT = os.getenv(
    "CRISTOPHER_SEC_UA",
    "Cristopher Portfolio Tracker (personal-research) admin@cristopher.local",
)

# Atom feed by CIK (10-digit zero-padded). Map common tickers → CIK.
# (Yahoo doesn't expose CIK; we hardcode a small whitelist for now.)
TICKER_TO_CIK = {
    "AAPL":  "0000320193",
    "MSFT":  "0000789019",
    "NVDA":  "0001045810",
    "GOOGL": "0001652044",
    "AMZN":  "0001018724",
    "META":  "0001326801",
    "TSLA":  "0001318605",
    "AVGO":  "0001730168",
    "AMD":   "0000002488",
    "ORCL":  "0001341439",
    "NFLX":  "0001065280",
    "CRM":   "0001108524",
    "PLTR":  "0001321655",
    "COIN":  "0001679788",
    "MSTR":  "0001050446",
    "INTC":  "0000050863",
}


def _form4_atom_url(cik: str) -> str:
    return (
        f"https://www.sec.gov/cgi-bin/browse-edgar"
        f"?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=20&output=atom"
    )


def _parse_form4_atom(xml_text: str) -> list[dict]:
    """Return list of {date, title, url} from an EDGAR atom feed."""
    out = []
    try:
        # Strip default namespace for simpler XPath
        ns_re = re.compile(r' xmlns="[^"]+"')
        clean = ns_re.sub("", xml_text, count=1)
        root = ET.fromstring(clean)
    except ET.ParseError as e:
        logger.warning(f"EDGAR XML parse failed: {e}")
        return out

    for entry in root.findall("entry"):
        title = (entry.findtext("title") or "").strip()
        updated = (entry.findtext("updated") or "")[:10]
        link_el = entry.find("link")
        link = link_el.get("href") if link_el is not None else ""
        out.append({"date": updated, "title": title, "url": link})
    return out


def fetch_insider_for_ticker(ticker: str, days: int = 30) -> dict:
    """Returns {ticker, recent_filings: [...], cluster_signal: str | None}."""
    cik = TICKER_TO_CIK.get(ticker.upper())
    if not cik:
        return {"ticker": ticker.upper(), "available": False}

    try:
        r = httpx.get(_form4_atom_url(cik), headers={"User-Agent": USER_AGENT}, timeout=10)
        r.raise_for_status()
    except Exception as e:
        logger.warning(f"EDGAR fetch failed for {ticker}: {e}")
        return {"ticker": ticker.upper(), "available": False, "error": str(e)[:100]}

    entries = _parse_form4_atom(r.text)
    cutoff = datetime.now().date()
    recent = []
    for e in entries:
        try:
            d = datetime.fromisoformat(e["date"]).date()
            if (cutoff - d).days <= days:
                recent.append(e)
        except (ValueError, TypeError):
            continue

    # Form 4 atom titles are like "4 - Jeff Williams (CIK)" — without parsing the actual filings
    # we can only count them. A spike is informative on its own (cluster activity).
    return {
        "ticker": ticker.upper(),
        "available": True,
        "filings_30d": len(recent),
        "filings_recent": recent[:10],
        "spike": len(recent) >= 5,   # rough heuristic: ≥5 filings in a month
    }


def fetch_insider_batch(tickers: list[str], days: int = 30, max_workers: int = 6) -> dict[str, dict]:
    """Parallel fetch. Returns {TICKER: result_dict}."""
    out: dict[str, dict] = {}
    targets = [t.upper() for t in tickers if t]
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_insider_for_ticker, t, days): t for t in targets}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                out[t] = fut.result()
            except Exception as e:
                logger.debug(f"insider {t} failed: {e}")
                out[t] = {"ticker": t, "available": False, "error": str(e)[:100]}
    return out


def format_insider_for_prompt(by_ticker: dict[str, dict]) -> str:
    """Compact line per ticker with insider activity (only those with data)."""
    lines = []
    for t, info in by_ticker.items():
        if not info.get("available"):
            continue
        n = info.get("filings_30d", 0)
        if n == 0:
            continue
        flag = " ⚠️ atividade elevada" if info.get("spike") else ""
        lines.append(f"  - {t}: {n} formulários 4 nos últimos 30d{flag}")
    return "\n".join(lines) if lines else "  (sem atividade insider relevante nos tickers cobertos)"
