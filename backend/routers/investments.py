from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from datetime import datetime, date
import csv
import io
import re
import json
import subprocess
import tempfile
import logging
import httpx
from pydantic import BaseModel

from database import get_db
from models import InvestmentPosition, InvestmentTrade, InvestmentTransaction, InvestmentSummary, InvestmentPlan, InvestmentAllocation, InvestmentMonthlyPlan
from schemas import (
    InvestmentPositionOut, InvestmentTradeOut,
    InvestmentTransactionOut, InvestmentSummaryOut,
    InvestmentPlanCreate, InvestmentPlanUpdate, InvestmentPlanOut,
    InvestmentAllocationCreate, InvestmentAllocationUpdate, InvestmentAllocationOut,
    MonthlyPlanUpdate, MonthlyPlanOut,
)

router = APIRouter(prefix="/api/investments", tags=["Investments"])
logger = logging.getLogger(__name__)


# ── Endpoints ────────────────────────────────────────────────────

@router.get("/positions", response_model=list[InvestmentPositionOut])
def list_positions(db: Session = Depends(get_db)):
    return db.query(InvestmentPosition).order_by(InvestmentPosition.current_value_eur.desc()).all()


@router.get("/trades", response_model=list[InvestmentTradeOut])
def list_trades(db: Session = Depends(get_db)):
    return db.query(InvestmentTrade).order_by(InvestmentTrade.execution_time.desc()).all()


@router.get("/transactions", response_model=list[InvestmentTransactionOut])
def list_transactions(db: Session = Depends(get_db)):
    return db.query(InvestmentTransaction).order_by(InvestmentTransaction.time.desc()).all()


@router.get("/summary")
def get_summary(db: Session = Depends(get_db)):
    all_positions = db.query(InvestmentPosition).all()
    summaries = db.query(InvestmentSummary).order_by(InvestmentSummary.statement_date.desc()).all()
    latest = summaries[0] if summaries else None

    # Keep only the most recent snapshot per (instrument, source). Without this,
    # monthly snapshots stack: e.g. BTC in 2026-04 and 2026-05 would be summed twice.
    latest_per_key: dict[tuple[str, str], InvestmentPosition] = {}
    for p in all_positions:
        key = (p.instrument, p.source or "")
        existing = latest_per_key.get(key)
        if existing is None or (p.statement_date or "") > (existing.statement_date or ""):
            latest_per_key[key] = p
    positions = list(latest_per_key.values())

    total_value = sum(p.current_value_eur or 0 for p in positions)
    total_invested = sum(p.quantity * p.avg_price / (p.fx_rate if p.fx_rate and p.fx_rate != 0 else 1) for p in positions)
    total_return = sum(p.return_eur or 0 for p in positions)

    # Calculate deposits/withdrawals from actual transactions (covers all sources)
    transactions = db.query(InvestmentTransaction).all()
    total_deposits = sum(t.amount for t in transactions if t.type == "Depósito")
    total_withdrawals = sum(t.amount for t in transactions if t.type == "Levantamento")

    return {
        "total_value": round(total_value, 2),
        "total_invested": round(total_invested, 2),
        "total_return": round(total_return, 2),
        "total_return_pct": round((total_return / total_invested * 100) if total_invested else 0, 2),
        "total_deposits": round(total_deposits, 2),
        "total_withdrawals": round(total_withdrawals, 2),
        "positions_count": len(positions),
        "latest_statement": latest.statement_date.isoformat() if latest else None,
        "account_value": latest.account_value if latest else total_value,
    }


# ── Crypto Price Update ─────────────────────────────────────────

CRYPTO_COINGECKO_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "ADA": "cardano",
    "DOT": "polkadot",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "MATIC": "matic-network",
    "LTC": "litecoin",
}


@router.post("/prices/crypto")
def refresh_crypto_prices(db: Session = Depends(get_db)):
    """Fetch current crypto prices from CoinGecko and update Finst positions."""
    crypto_positions = (
        db.query(InvestmentPosition)
        .filter(InvestmentPosition.source == "finst")
        .all()
    )
    if not crypto_positions:
        raise HTTPException(status_code=404, detail="Sem posições crypto para atualizar")

    ids_map = {}
    for p in crypto_positions:
        cg_id = CRYPTO_COINGECKO_MAP.get(p.instrument.upper())
        if cg_id:
            ids_map[cg_id] = p

    if not ids_map:
        raise HTTPException(status_code=400, detail="Crypto não suportadas: " + ", ".join(p.instrument for p in crypto_positions))

    ids_str = ",".join(ids_map.keys())
    try:
        resp = httpx.get(
            f"https://api.coingecko.com/api/v3/simple/price?ids={ids_str}&vs_currencies=eur",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao contactar CoinGecko: {e}")

    updated = []
    for cg_id, pos in ids_map.items():
        price_eur = data.get(cg_id, {}).get("eur")
        if price_eur is not None:
            pos.current_price = price_eur
            pos.current_value_eur = round(pos.quantity * price_eur, 2)
            total_cost = pos.quantity * pos.avg_price
            pos.return_eur = round(pos.current_value_eur - total_cost, 2)
            updated.append({
                "instrument": pos.instrument,
                "current_price": price_eur,
                "current_value_eur": pos.current_value_eur,
                "return_eur": pos.return_eur,
            })

    db.commit()
    return {"updated": updated}


class PriceUpdate(BaseModel):
    current_price: float


@router.put("/positions/{position_id}/price")
def update_position_price(position_id: int, body: PriceUpdate, db: Session = Depends(get_db)):
    """Manually update the current price of a position."""
    pos = db.query(InvestmentPosition).filter(InvestmentPosition.id == position_id).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Posição não encontrada")

    pos.current_price = body.current_price
    pos.current_value_eur = round(pos.quantity * body.current_price / (pos.fx_rate if pos.fx_rate and pos.fx_rate != 0 else 1), 2)
    total_cost = pos.quantity * pos.avg_price / (pos.fx_rate if pos.fx_rate and pos.fx_rate != 0 else 1)
    pos.return_eur = round(pos.current_value_eur - total_cost, 2)
    db.commit()

    return {"id": pos.id, "instrument": pos.instrument, "current_price": pos.current_price, "current_value_eur": pos.current_value_eur, "return_eur": pos.return_eur}


# ── Finst Screenshot Import ─────────────────────────────────────

CRYPTO_NAMES_OCR = {
    # name variants (OCR can mangle these) -> symbol
    "bitcoin": "BTC", "sitcoin": "BTC", "bitco": "BTC", "8itcoin": "BTC", "biteoin": "BTC", "bitcoln": "BTC",
    "ethereum": "ETH", "ethere": "ETH", "etherium": "ETH", "etherewn": "ETH", "ethereun": "ETH",
    "solana": "SOL",
    "cardano": "ADA",
    "polkadot": "DOT",
    "ripple": "XRP",
    "dogecoin": "DOGE",
    "litecoin": "LTC",
    "avalanche": "AVAX",
    "chainlink": "LINK",
    "polygon": "MATIC",
}

CRYPTO_SYMBOLS = {"BTC", "ETH", "SOL", "ADA", "DOT", "XRP", "DOGE", "LTC", "AVAX", "LINK", "MATIC"}

# OCR ticker confusions — mapped back to canonical symbol. Tesseract regularly
# misreads short uppercase tickers when an icon bleeds into the glyphs.
SYMBOL_OCR_VARIANTS: dict[str, str] = {}
for _sym, _variants in {
    "BTC": ["BTC", "B7C", "8TC", "BIC", "BTG", "STC", "ETC", "BTL", "BTO", "8IC"],
    "ETH": ["ETH", "ETN", "FTH", "ET11"],
    "SOL": ["SOL", "S0L", "SQL"],
    "ADA": ["ADA"],
    "DOT": ["DOT", "OOT"],
    "XRP": ["XRP"],
    "DOGE": ["DOGE", "OOGE", "DO0E"],
    "LTC": ["LTC", "L7C", "LIC"],
    "AVAX": ["AVAX"],
    "LINK": ["LINK", "LlNK"],
    "MATIC": ["MATIC"],
}.items():
    for _v in _variants:
        SYMBOL_OCR_VARIANTS[_v.upper()] = _sym


def _parse_eur_number(s: str) -> float:
    """Parse European formatted number: 61.236,04 -> 61236.04"""
    s = s.strip().replace("\u00a0", "").replace(" ", "")
    s = s.replace(".", "").replace(",", ".")
    return float(s)


def _parse_qty_number(s: str) -> float:
    """Parse a crypto quantity that may use either `,` or `.` as decimal.
    OCR sometimes flips one into the other. Quantities never have thousands
    separators, so the rightmost separator is the decimal."""
    s = s.strip().replace("\u00a0", "").replace(" ", "")
    last_comma = s.rfind(",")
    last_dot = s.rfind(".")
    sep = max(last_comma, last_dot)
    if sep < 0:
        return float(s)
    return float(s[:sep].replace(",", "").replace(".", "") + "." + s[sep + 1:])


@router.post("/import/finst-screenshot")
async def import_finst_screenshot(
    file: UploadFile = File(...),
    month: str = Form(...),
    db: Session = Depends(get_db),
):
    """Parse a Finst wallet screenshot via OCR and store positions as a monthly snapshot.

    `month` must be in YYYY-MM format (e.g. "2026-04")."""
    import pytesseract
    from PIL import Image

    if not re.fullmatch(r"\d{4}-\d{2}", month or ""):
        raise HTTPException(status_code=400, detail="Mês inválido (esperado YYYY-MM)")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Ficheiro inválido")

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Ficheiro demasiado grande (max 20MB)")

    try:
        img = Image.open(io.BytesIO(content))
    except Exception:
        raise HTTPException(status_code=400, detail="Não foi possível abrir a imagem")

    # OCR
    try:
        text = pytesseract.image_to_string(img, lang="eng")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro OCR: {e}")

    logger.info(f"Finst screenshot OCR text:\n{text}")
    # Persist OCR text for offline debugging — overwrites on each import.
    try:
        with open("/tmp/cristopher-finst-ocr.txt", "w") as _f:
            _f.write(text)
    except Exception:
        pass

    lines = text.split("\n")
    # Euro amount pattern. The € glyph is fragile under OCR (often dropped or
    # read as "C"/"E"/"©"). Match the €-suffixed form, then OR a bare
    # European-formatted number that has thousands separators (so we don't
    # spuriously pick up "0,17" percentages but still catch "65.101,1682"
    # when the € is missing). Single-block decimals like "126,37" only count
    # when followed by € — otherwise too easy to confuse with percentages.
    eur_pattern = re.compile(
        r"([\d]+(?:\.[\d]{3})+,[\d]+)|([\d]+,[\d]+)\s*€",
    )

    def _iter_eurs(line: str):
        for m in eur_pattern.finditer(line):
            yield m.group(1) or m.group(2)
    # Quantity+symbol pattern, lenient: allow `,` or `.` decimal, optional noise
    # char between number and ticker, and a fuzzy ticker (matched against
    # SYMBOL_OCR_VARIANTS afterwards). Tesseract regularly drops a space
    # ("0,00184052BTC") or warps the ticker ("0,00184052 8TC").
    variants_alt = "|".join(sorted(SYMBOL_OCR_VARIANTS.keys(), key=len, reverse=True))
    qty_pattern = re.compile(
        r"(\d+[.,]\d+)\s*[^\w\s]?\s*(" + variants_alt + r")(?![A-Z])",
        re.IGNORECASE,
    )

    # Parse: find crypto lines and extract data
    parsed: list[dict] = []
    seen_symbols: set[str] = set()

    # Build trigger list: each tuple = (line_index, symbol). Match either the crypto
    # name (e.g. "Bitcoin") OR the quantity+symbol pattern (e.g. "0,00184052 BTC"),
    # since OCR often loses the name beside the colored icon.
    triggers: list[tuple[int, str]] = []
    triggered_symbols: set[str] = set()
    for i, line in enumerate(lines):
        line_lower = line.lower()
        for name_variant, symbol in CRYPTO_NAMES_OCR.items():
            if name_variant in line_lower and symbol not in triggered_symbols:
                triggers.append((i, symbol))
                triggered_symbols.add(symbol)
                break
    # Fallback: lines that carry a quantity+symbol but whose symbol wasn't already
    # picked up by a name match.
    for i, line in enumerate(lines):
        for qm in qty_pattern.finditer(line):
            raw = qm.group(2).upper()
            sym = SYMBOL_OCR_VARIANTS.get(raw)
            if sym and sym not in triggered_symbols:
                triggers.append((i, sym))
                triggered_symbols.add(sym)

    # Pre-collect every euro amount in the OCR with its line index. Used for
    # the qty×price≈value cross-check: tabular OCR can split a row across many
    # lines (or interleave them), so a tight per-trigger window is unreliable.
    all_eurs: list[tuple[int, float]] = []
    for j, line in enumerate(lines):
        for s in _iter_eurs(line):
            all_eurs.append((j, _parse_eur_number(s)))

    for i, found_symbol in triggers:
        if found_symbol in seen_symbols:
            continue

        # Search for quantity in nearby lines, restricted to the symbol we found.
        # Also grab the BEP (Break-Even / average buy price): in Finst's stacked
        # cell layout it appears right after the qty on the same OCR line, e.g.
        #   "0,00184052 BTC 65.101,1682€ +2,49% ... Realized -0,17€"
        # The BEP is the FIRST euro after the symbol position on that line.
        nearby_range = range(max(0, i - 4), min(len(lines), i + 6))
        quantity = None
        bep_price = None
        for j in nearby_range:
            qty_match = None
            for qm in qty_pattern.finditer(lines[j]):
                if SYMBOL_OCR_VARIANTS.get(qm.group(2).upper()) == found_symbol:
                    qty_match = qm
                    break
            if qty_match is not None:
                quantity = _parse_qty_number(qty_match.group(1))
                tail = lines[j][qty_match.end():]
                for s in _iter_eurs(tail):
                    bep_price = _parse_eur_number(s)
                    break
                break

        value_eur: float | None = None
        current_price: float | None = None

        # Best signal: find a (value, price) pair where value ≈ qty × price.
        # The Finst table puts value first then BEP/current price, so this
        # disambiguates between the row's main values and stray P/L numbers
        # (the qty row also contains the BEP price + small realized amounts).
        if quantity and quantity > 0:
            best_score = 0.10  # error budget: 5% match tolerance + line-distance penalty
            for ai in range(len(all_eurs)):
                for bi in range(len(all_eurs)):
                    if ai == bi:
                        continue
                    a_line, a = all_eurs[ai]
                    b_line, b = all_eurs[bi]
                    if b <= 0 or a <= 0:
                        continue
                    match_err = abs((quantity * b) - a) / max(a, 1e-9)
                    if match_err > 0.05:
                        continue
                    # Penalize pairs far from the trigger line and pairs where
                    # value/price come from different OCR lines.
                    distance = (abs(a_line - i) + abs(b_line - i)) / 2.0
                    score = match_err + 0.001 * distance
                    if a_line != b_line:
                        score += 0.005
                    if score < best_score:
                        best_score = score
                        value_eur = a
                        current_price = b

        # Fallback: pick the nearest line (preferring trigger line) with ≥2 euros
        # and take the first two as (value, price). Wider scan than before so
        # tabular layouts with extra blank lines still find the value row.
        if value_eur is None or current_price is None:
            offsets = [0]
            for d in range(1, 12):
                offsets.extend([-d, d])
            for d in offsets:
                j = i + d
                if 0 <= j < len(lines):
                    line_eurs = list(_iter_eurs(lines[j]))
                    if len(line_eurs) >= 2:
                        # Skip lines whose first 2 euros don't look like (value, price)
                        # for the symbol — i.e. the qty line where amounts[0] is the
                        # BEP price (large) and amounts[1] is a tiny "Realized" euro.
                        a = _parse_eur_number(line_eurs[0])
                        b = _parse_eur_number(line_eurs[1])
                        if quantity and quantity > 0 and b > 0:
                            implied = a / b
                            if abs(implied - quantity) / quantity > 0.5:
                                continue
                        value_eur = a
                        current_price = b
                        break

        # Parse euro amounts
        # Finst table: Value | Price,BEP | Daily P/L | Unrealized P/L | Position P/L | Total P/L
        if value_eur is not None and current_price is not None:
            entry = {
                "instrument": found_symbol,
                "current_price": current_price,
                "value_eur": value_eur,
                "quantity": quantity,
                "bep_price": bep_price,
            }

            seen_symbols.add(found_symbol)
            parsed.append(entry)

    if not parsed:
        raise HTTPException(
            status_code=400,
            detail=f"Não foi possível extrair dados crypto da imagem. Texto OCR: {text[:500]}"
        )

    # Upsert positions in DB as a monthly snapshot for the given month.
    # Quantity/avg are inferred from the most recent earlier finst snapshot when available;
    # otherwise we fall back to deriving them from the screenshot values.
    updated = []
    legacy_cleared = 0
    for p in parsed:
        # Drop legacy null-dated finst rows so they don't double-count alongside
        # the new monthly snapshot.
        legacy_cleared += (
            db.query(InvestmentPosition)
            .filter(
                InvestmentPosition.instrument == p["instrument"],
                InvestmentPosition.source == "finst",
                InvestmentPosition.statement_date.is_(None),
            )
            .delete(synchronize_session=False)
        )

        snap = (
            db.query(InvestmentPosition)
            .filter(
                InvestmentPosition.instrument == p["instrument"],
                InvestmentPosition.source == "finst",
                InvestmentPosition.statement_date == month,
            )
            .first()
        )

        prior = (
            db.query(InvestmentPosition)
            .filter(
                InvestmentPosition.instrument == p["instrument"],
                InvestmentPosition.source == "finst",
                InvestmentPosition.statement_date != month,
            )
            .order_by(InvestmentPosition.statement_date.desc().nullslast())
            .first()
        )

        screenshot_value = p.get("value_eur")
        screenshot_qty = p.get("quantity")
        screenshot_bep = p.get("bep_price")
        current_price = p["current_price"]

        # Prefer screenshot quantity, then prior snapshot quantity, then derive from value/price.
        if screenshot_qty:
            qty = screenshot_qty
        elif prior and prior.quantity:
            qty = prior.quantity
        elif screenshot_value and current_price:
            qty = round(screenshot_value / current_price, 8)
        else:
            continue

        # avg_price = the BEP from the screenshot (Finst's "Price, BEP" 2nd line).
        # The screenshot is authoritative; ignore prior snapshots whose avg may
        # have been written from a buggy parse before BEP extraction existed.
        if screenshot_bep:
            avg_price = screenshot_bep
        elif prior and prior.avg_price:
            avg_price = prior.avg_price
        else:
            avg_price = current_price
        value = round(qty * current_price, 2) if not screenshot_value else screenshot_value
        return_eur = round(value - qty * avg_price, 2)

        if snap:
            snap.quantity = qty
            snap.avg_price = avg_price
            snap.current_price = current_price
            snap.current_value_eur = value
            snap.return_eur = return_eur
        else:
            db.add(InvestmentPosition(
                instrument=p["instrument"],
                isin=None,
                currency="EUR",
                quantity=qty,
                avg_price=avg_price,
                current_price=current_price,
                current_value_eur=value,
                return_eur=return_eur,
                fx_rate=1.0,
                source="finst",
                statement_date=month,
            ))

        updated.append({
            "instrument": p["instrument"],
            "current_price": current_price,
            "current_value_eur": value,
            "return_eur": return_eur,
            "screenshot_value": screenshot_value,
        })

    db.commit()
    return {
        "updated": updated,
        "ocr_cryptos_found": len(parsed),
        "month": month,
        "legacy_cleared": legacy_cleared,
    }


# ── Trading 212 PDF Import ──────────────────────────────────────

def _extract_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF using pdftotext."""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        result = subprocess.run(
            ["pdftotext", "-layout", tmp.name, "-"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise HTTPException(status_code=400, detail="Falha ao processar PDF")
        return result.stdout


def _parse_overview(text: str) -> dict:
    """Parse the Overview section."""
    data = {}
    patterns = {
        "deposits": r"Deposits\s+€([\d,.]+)",
        "withdrawals": r"Withdrawals\s+€([\d,.]+)",
        "open_return": r"Open return\s+€([−-]?[\d,.]+)",
        "fx_fees": r"FX Fee\s+€([−-]?[\d,.]+)",
        "dividends": r"Dividends\s+€([\d,.]+)",
        "account_value": r"Account value\s+€([\d,.]+)",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, text)
        if m:
            val = m.group(1).replace(",", "").replace("−", "-")
            data[key] = float(val)
    
    # Statement date
    m = re.search(r"Generated by Trading 212.*?on (\d+ \w+ \d{4})", text)
    if m:
        try:
            data["statement_date"] = datetime.strptime(m.group(1), "%d %B %Y").date()
        except ValueError:
            data["statement_date"] = date.today()
    else:
        data["statement_date"] = date.today()
    
    # Period month: extract from "covering from ... to DD.MM.YYYY"
    m = re.search(r"covering from.*?to\s+(\d{2})\.(\d{2})\.(\d{4})", text)
    if m:
        data["period_month"] = f"{m.group(3)}-{m.group(2)}"  # e.g. "2026-03"
    else:
        # Fallback: use statement_date minus 1 month
        sd = data.get("statement_date", date.today())
        data["period_month"] = f"{sd.year}-{sd.month:02d}"
    
    return data


def _parse_trades(text: str) -> list[dict]:
    """Parse executed trades from Trading 212 PDF."""
    trades = []
    # Match trade lines: date time, instrument, ISIN, currency, order_id, direction, quantity, exec_price, value, ...
    # Format: 2026-03-17 08:00:10 CNDX IE00B53SZB19 USD 48113288169 Buy 0.03664405 1409.4 51.6461 Market OTC Regular hours 1.14947972 EUR 0.07 - - 45
    lines = text.split("\n")
    for line in lines:
        m = re.match(
            r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+"  # execution time
            r"(\w+)\s+"                                       # instrument
            r"([A-Z0-9]+)\s+"                                 # ISIN
            r"(\w+)\s+"                                       # currency
            r"(\d+)\s+"                                       # order_id
            r"(Buy|Sell)\s+"                                  # direction
            r"([\d.]+)\s+"                                    # quantity
            r"([\d.]+)\s+"                                    # price
            r"([\d.]+)\s+"                                    # value
            r".*?(\d+\.?\d*)\s+EUR\s+"                        # fx_rate ... EUR
            r"([\d.]+|-)",                                    # fx_fee
            line.strip()
        )
        if m:
            fx_fee = 0.0
            if m.group(11) != "-":
                fx_fee = float(m.group(11))
            
            fx_rate = float(m.group(10))
            value_raw = float(m.group(9))
            value_eur = value_raw / fx_rate if fx_rate > 1 else value_raw
            
            # Get the EUR value from end of line
            parts = line.strip().split()
            try:
                value_eur = float(parts[-1])
            except (ValueError, IndexError):
                pass
            
            trades.append({
                "execution_time": datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"),
                "instrument": m.group(2),
                "isin": m.group(3),
                "currency": m.group(4),
                "direction": m.group(6),
                "quantity": float(m.group(7)),
                "execution_price": float(m.group(8)),
                "value": value_raw,
                "value_eur": value_eur,
                "fx_rate": fx_rate,
                "fx_fee": fx_fee,
            })
    return trades


def _parse_positions(text: str) -> list[dict]:
    """Parse open positions from Trading 212 PDF."""
    positions = []
    lines = text.split("\n")
    in_positions = False
    
    for line in lines:
        if "Open positions" in line:
            in_positions = True
            continue
        if not in_positions:
            continue
        if "Pending orders" in line or "CFD account" in line:
            break
        
        # Match: CNDX IE00B53SZB19 USD 0.08568467 1433.04514098 1339 -8.06 114.7318 1.15545 €-5.54 €99.30
        m = re.match(
            r"(\w+)\s+"                     # instrument
            r"([A-Z0-9]+)\s+"               # ISIN
            r"(\w+)\s+"                      # currency
            r"([\d.]+)\s+"                   # quantity
            r"([\d.]+)\s+"                   # avg_price
            r"([\d.]+)\s+"                   # current_price
            r"([−-]?[\d.]+)\s+"             # return (raw)
            r"([\d.]+)\s+"                   # value (raw)
            r"([\d.]+)\s+"                   # fx_rate
            r"€([−-]?[\d.]+)\s+"            # return EUR
            r"€([\d.]+)",                    # value EUR
            line.strip()
        )
        if m:
            positions.append({
                "instrument": m.group(1),
                "isin": m.group(2),
                "currency": m.group(3),
                "quantity": float(m.group(4)),
                "avg_price": float(m.group(5)),
                "current_price": float(m.group(6)),
                "return_eur": float(m.group(10).replace("−", "-")),
                "current_value_eur": float(m.group(11)),
                "fx_rate": float(m.group(9)),
            })
    return positions


def _parse_transactions(text: str) -> list[dict]:
    """Parse transactions (deposits/withdrawals)."""
    transactions = []
    lines = text.split("\n")
    for line in lines:
        m = re.match(
            r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+"
            r"(\w+)\s+"        # type (Adyen, etc.)
            r"(\w+)\s+"        # currency
            r"([\d.]+)\s+"     # amount
            r"€([\d.]+)",      # amount EUR
            line.strip()
        )
        if m:
            transactions.append({
                "time": datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"),
                "type": "Depósito" if float(m.group(4)) > 0 else "Levantamento",
                "currency": m.group(3),
                "amount": float(m.group(5)),
            })
    return transactions


@router.post("/import/pdf")
async def import_trading212_pdf(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import a Trading 212 monthly statement PDF."""
    if not file.filename or not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Faz upload de um ficheiro PDF")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Ficheiro demasiado grande (max 10MB)")

    text = _extract_text(content)
    logger.info(f"Extracted {len(text)} chars from PDF")

    # Parse sections
    overview = _parse_overview(text)
    trades = _parse_trades(text)
    positions = _parse_positions(text)
    transactions = _parse_transactions(text)

    # Store summary
    existing_summary = (
        db.query(InvestmentSummary)
        .filter(InvestmentSummary.statement_date == overview.get("statement_date"))
        .first()
    )
    if existing_summary:
        for k, v in overview.items():
            if k != "statement_date" and v is not None:
                setattr(existing_summary, k, v)
    else:
        db.add(InvestmentSummary(
            statement_date=overview.get("statement_date", date.today()),
            account_value=overview.get("account_value", 0),
            deposits=overview.get("deposits", 0),
            withdrawals=overview.get("withdrawals", 0),
            open_return=overview.get("open_return", 0),
            fx_fees=overview.get("fx_fees", 0),
            dividends=overview.get("dividends", 0),
        ))

    # Store trades (avoid duplicates by execution_time + instrument)
    trades_added = 0
    for t in trades:
        exists = (
            db.query(InvestmentTrade)
            .filter(
                InvestmentTrade.execution_time == t["execution_time"],
                InvestmentTrade.instrument == t["instrument"],
                InvestmentTrade.quantity == t["quantity"],
                InvestmentTrade.source == "trading212",
            )
            .first()
        )
        if not exists:
            t["source"] = "trading212"
            db.add(InvestmentTrade(**t))
            trades_added += 1

    # Build statement month string (e.g. "2026-03") from overview period
    stmt_month = overview.get("period_month")

    # Update positions (upsert by instrument + source + statement_date)
    positions_updated = 0
    for p in positions:
        existing = (
            db.query(InvestmentPosition)
            .filter(
                InvestmentPosition.instrument == p["instrument"],
                InvestmentPosition.source == "trading212",
                InvestmentPosition.statement_date == stmt_month,
            )
            .first()
        )
        if existing:
            for k, v in p.items():
                setattr(existing, k, v)
        else:
            p["source"] = "trading212"
            p["statement_date"] = stmt_month
            db.add(InvestmentPosition(**p))
        positions_updated += 1

    # Store transactions
    txns_added = 0
    for t in transactions:
        exists = (
            db.query(InvestmentTransaction)
            .filter(
                InvestmentTransaction.time == t["time"],
                InvestmentTransaction.amount == t["amount"],
                InvestmentTransaction.source == "trading212",
            )
            .first()
        )
        if not exists:
            t["source"] = "trading212"
            db.add(InvestmentTransaction(**t))
            txns_added += 1

    db.commit()

    return {
        "overview": overview,
        "trades_added": trades_added,
        "trades_total": len(trades),
        "positions_updated": positions_updated,
        "transactions_added": txns_added,
        "statement_date": str(overview.get("statement_date", "")),
    }


# ── Finst CSV Import ────────────────────────────────────────────

CRYPTO_NAMES = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "XRP": "XRP",
    "SOL": "Solana",
    "ADA": "Cardano",
    "DOGE": "Dogecoin",
    "DOT": "Polkadot",
    "AVAX": "Avalanche",
    "LINK": "Chainlink",
    "MATIC": "Polygon",
    "UNI": "Uniswap",
    "ATOM": "Cosmos",
    "LTC": "Litecoin",
}


@router.post("/import/finst-csv")
async def import_finst_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import a Finst orders CSV export."""
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Faz upload de um ficheiro CSV")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Ficheiro demasiado grande (max 10MB)")

    text = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))

    trades_added = 0
    txns_added = 0
    total_deposits = 0.0
    total_withdrawals = 0.0

    for row in reader:
        status = row.get("Status", "").strip()
        if status != "EXECUTED":
            continue

        action = row.get("Action", "").strip()
        last_update = row.get("Last Update", "").strip()
        try:
            exec_time = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue

        if action in ("BUY", "SELL"):
            from_asset = row.get("From Asset", "EUR").strip()
            from_amount = float(row.get("From Amount", "0") or "0")
            to_asset = row.get("To Asset", "").strip()
            to_amount = float(row.get("To Amount", "0") or "0")
            fee_amount = float(row.get("Fee Amount", "0") or "0")

            instrument = to_asset if action == "BUY" else from_asset
            quantity = to_amount if action == "BUY" else from_amount
            value_eur = from_amount if action == "BUY" else to_amount
            exec_price = value_eur / quantity if quantity > 0 else 0

            # Dedup
            exists = (
                db.query(InvestmentTrade)
                .filter(
                    InvestmentTrade.execution_time == exec_time,
                    InvestmentTrade.instrument == instrument,
                    InvestmentTrade.quantity == quantity,
                    InvestmentTrade.source == "finst",
                )
                .first()
            )
            if not exists:
                db.add(InvestmentTrade(
                    execution_time=exec_time,
                    instrument=instrument,
                    isin=None,
                    currency="EUR",
                    direction="Buy" if action == "BUY" else "Sell",
                    quantity=quantity,
                    execution_price=round(exec_price, 8),
                    value=value_eur,
                    value_eur=value_eur,
                    fx_rate=1.0,
                    fx_fee=fee_amount,
                    source="finst",
                ))
                trades_added += 1

        elif action == "DEPOSIT":
            amount = float(row.get("To Amount", "0") or "0")
            total_deposits += amount
            exists = (
                db.query(InvestmentTransaction)
                .filter(
                    InvestmentTransaction.time == exec_time,
                    InvestmentTransaction.amount == amount,
                    InvestmentTransaction.source == "finst",
                )
                .first()
            )
            if not exists:
                db.add(InvestmentTransaction(
                    time=exec_time,
                    type="Depósito",
                    currency="EUR",
                    amount=amount,
                    source="finst",
                ))
                txns_added += 1

        elif action == "WITHDRAW":
            amount = float(row.get("From Amount", "0") or "0")
            total_withdrawals += amount
            exists = (
                db.query(InvestmentTransaction)
                .filter(
                    InvestmentTransaction.time == exec_time,
                    InvestmentTransaction.amount == amount,
                    InvestmentTransaction.source == "finst",
                )
                .first()
            )
            if not exists:
                db.add(InvestmentTransaction(
                    time=exec_time,
                    type="Levantamento",
                    currency="EUR",
                    amount=amount,
                    source="finst",
                ))
                txns_added += 1

    # Rebuild Finst positions from ALL trades in DB (not just this CSV)
    db.flush()  # ensure new trades are visible in queries
    finst_instruments = (
        db.query(InvestmentTrade.instrument)
        .filter(InvestmentTrade.source == "finst")
        .distinct()
        .all()
    )
    positions_updated = 0
    for (instrument,) in finst_instruments:
        all_trades = (
            db.query(InvestmentTrade)
            .filter(InvestmentTrade.instrument == instrument, InvestmentTrade.source == "finst")
            .all()
        )
        qty = 0.0
        cost = 0.0
        for t in all_trades:
            if t.direction == "Buy":
                qty += t.quantity
                cost += t.value_eur
            else:
                qty -= t.quantity
                cost -= t.value_eur

        existing = (
            db.query(InvestmentPosition)
            .filter(
                InvestmentPosition.instrument == instrument,
                InvestmentPosition.source == "finst",
            )
            .first()
        )
        if qty <= 0:
            if existing:
                db.delete(existing)
            continue

        avg_price = cost / qty if qty > 0 else 0
        if existing:
            existing.quantity = qty
            existing.avg_price = round(avg_price, 8)
        else:
            db.add(InvestmentPosition(
                instrument=instrument,
                isin=None,
                currency="EUR",
                quantity=qty,
                avg_price=round(avg_price, 8),
                current_price=None,
                current_value_eur=None,
                return_eur=None,
                fx_rate=1.0,
                source="finst",
            ))
        positions_updated += 1

    db.commit()

    return {
        "trades_added": trades_added,
        "transactions_added": txns_added,
        "positions_updated": positions_updated,
        "total_deposits": round(total_deposits, 2),
        "total_withdrawals": round(total_withdrawals, 2),
    }


# ── Investment Allocation Plan ────────────────────────────────────

DEFAULT_ALLOCATIONS = [
    {"name": "Vanguard S&P 500", "ticker": "VUAA", "asset_type": "etf", "percentage": 33, "sort_order": 0},
    {"name": "Invesco Physical Gold", "ticker": "SGLD", "asset_type": "etf", "percentage": 10, "sort_order": 1},
    {"name": "iShares Silver", "ticker": "SSLN", "asset_type": "etf", "percentage": 7, "sort_order": 2},
    {"name": "Bitcoin", "ticker": "BTC", "asset_type": "crypto", "percentage": 20, "sort_order": 3},
    {"name": "Ethereum", "ticker": "ETH", "asset_type": "crypto", "percentage": 10, "sort_order": 4},
    {"name": "Ação rotativa 1", "ticker": "STOCK1", "asset_type": "stock", "percentage": 10, "sort_order": 5, "is_rotational": True},
    {"name": "Ação rotativa 2", "ticker": "STOCK2", "asset_type": "stock", "percentage": 10, "sort_order": 6, "is_rotational": True},
]


@router.get("/allocations", response_model=list[InvestmentAllocationOut])
def list_allocations(db: Session = Depends(get_db)):
    allocs = db.query(InvestmentAllocation).order_by(InvestmentAllocation.sort_order.asc()).all()
    if not allocs:
        # Seed defaults on first access
        for a in DEFAULT_ALLOCATIONS:
            db.add(InvestmentAllocation(**a))
        db.commit()
        allocs = db.query(InvestmentAllocation).order_by(InvestmentAllocation.sort_order.asc()).all()
    return allocs


@router.post("/allocations", response_model=InvestmentAllocationOut)
def create_allocation(data: InvestmentAllocationCreate, db: Session = Depends(get_db)):
    alloc = InvestmentAllocation(**data.model_dump())
    db.add(alloc)
    db.commit()
    db.refresh(alloc)
    return alloc


@router.put("/allocations/{alloc_id}", response_model=InvestmentAllocationOut)
def update_allocation(alloc_id: int, data: InvestmentAllocationUpdate, db: Session = Depends(get_db)):
    alloc = db.query(InvestmentAllocation).filter(InvestmentAllocation.id == alloc_id).first()
    if not alloc:
        raise HTTPException(status_code=404, detail="Alocação não encontrada")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(alloc, k, v)
    db.commit()
    db.refresh(alloc)
    return alloc


@router.put("/allocations")
def bulk_update_allocations(data: list[InvestmentAllocationUpdate], db: Session = Depends(get_db)):
    """Bulk update all allocations (used when editing percentages)."""
    allocs = db.query(InvestmentAllocation).order_by(InvestmentAllocation.sort_order.asc()).all()
    for alloc, upd in zip(allocs, data):
        for k, v in upd.model_dump(exclude_unset=True).items():
            setattr(alloc, k, v)
    db.commit()
    return db.query(InvestmentAllocation).order_by(InvestmentAllocation.sort_order.asc()).all()


@router.delete("/allocations/{alloc_id}")
def delete_allocation(alloc_id: int, db: Session = Depends(get_db)):
    alloc = db.query(InvestmentAllocation).filter(InvestmentAllocation.id == alloc_id).first()
    if not alloc:
        raise HTTPException(status_code=404, detail="Alocação não encontrada")
    db.delete(alloc)
    db.commit()
    return {"ok": True}


# ── Monthly Plans ────────────────────────────────────────────────

@router.get("/monthly-plan/{month}")
def get_monthly_plan(month: str, db: Session = Depends(get_db)):
    """Get or create monthly plan for a given month (format: 2026-04)."""
    plan = db.query(InvestmentMonthlyPlan).filter(InvestmentMonthlyPlan.month == month).first()
    if not plan:
        plan = InvestmentMonthlyPlan(month=month, budget=300, rotational_choices="{}")
        db.add(plan)
        db.commit()
        db.refresh(plan)
    return {
        "id": plan.id,
        "month": plan.month,
        "budget": plan.budget,
        "rotational_choices": json.loads(plan.rotational_choices) if isinstance(plan.rotational_choices, str) else plan.rotational_choices,
    }


@router.put("/monthly-plan/{month}")
def update_monthly_plan(month: str, data: MonthlyPlanUpdate, db: Session = Depends(get_db)):
    plan = db.query(InvestmentMonthlyPlan).filter(InvestmentMonthlyPlan.month == month).first()
    if not plan:
        plan = InvestmentMonthlyPlan(month=month, budget=300, rotational_choices="{}")
        db.add(plan)
        db.commit()
        db.refresh(plan)
    if data.budget is not None:
        plan.budget = data.budget
    if data.rotational_choices is not None:
        plan.rotational_choices = json.dumps(data.rotational_choices)
    db.commit()
    db.refresh(plan)
    return {
        "id": plan.id,
        "month": plan.month,
        "budget": plan.budget,
        "rotational_choices": json.loads(plan.rotational_choices) if isinstance(plan.rotational_choices, str) else plan.rotational_choices,
    }


# ── Investment Plans CRUD ────────────────────────────────────────

@router.get("/search-asset")
async def search_asset(q: str):
    """Search for assets by name/ticker using Yahoo Finance."""
    if len(q.strip()) < 2:
        return []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://query2.finance.yahoo.com/v1/finance/search",
                params={"q": q.strip(), "quotesCount": 6, "newsCount": 0, "listsCount": 0},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []

    type_map = {"EQUITY": "stock", "ETF": "etf", "CRYPTOCURRENCY": "crypto", "MUTUALFUND": "fund"}
    results = []
    for item in data.get("quotes", []):
        qt = item.get("quoteType", "")
        asset_type = type_map.get(qt, "stock")
        results.append({
            "ticker": item.get("symbol", ""),
            "name": item.get("shortname") or item.get("longname") or item.get("symbol", ""),
            "asset_type": asset_type,
            "exchange": item.get("exchange", ""),
            "type_label": qt,
        })
    return results


@router.get("/plans", response_model=list[InvestmentPlanOut])
def list_plans(db: Session = Depends(get_db)):
    return db.query(InvestmentPlan).order_by(
        InvestmentPlan.status.asc(),  # pending first
        InvestmentPlan.created_at.desc(),
    ).all()


@router.post("/plans", response_model=InvestmentPlanOut)
def create_plan(data: InvestmentPlanCreate, db: Session = Depends(get_db)):
    plan = InvestmentPlan(**data.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.put("/plans/{plan_id}", response_model=InvestmentPlanOut)
def update_plan(plan_id: int, data: InvestmentPlanUpdate, db: Session = Depends(get_db)):
    plan = db.query(InvestmentPlan).filter(InvestmentPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plano não encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(plan, k, v)
    db.commit()
    db.refresh(plan)
    return plan


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(InvestmentPlan).filter(InvestmentPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plano não encontrado")
    db.delete(plan)
    db.commit()
    return {"ok": True}


# ── Investment Suggestions ───────────────────────────────────────

# Classification of assets
ASSET_TYPE_MAP = {
    "VUAA": "etf", "CNDX": "etf", "SSLN": "etf", "SGLD": "etf",
    "BTC": "crypto", "ETH": "crypto",
    "NVDA": "stock", "AAPL": "stock",
}

ASSET_NAMES = {
    "VUAA": "Vanguard S&P 500",
    "BTC": "Bitcoin",
    "CNDX": "iShares Nasdaq 100",
    "NVDA": "NVIDIA",
    "ETH": "Ethereum",
    "SSLN": "iShares Semiconductors",
    "SGLD": "Invesco Physical Gold",
    "AAPL": "Apple",
}

# Target allocation (ideal %)
TARGET_ALLOCATION = {
    "etf": 60.0,
    "crypto": 25.0,
    "stock": 15.0,
}


@router.get("/suggestions")
def get_suggestions(db: Session = Depends(get_db)):
    """Analyse portfolio and return actionable suggestions."""
    positions = db.query(InvestmentPosition).filter(
        InvestmentPosition.statement_date.is_(None) | (InvestmentPosition.current_value_eur > 0)
    ).all()

    # Get latest snapshot per instrument (no statement_date = live, or pick latest)
    latest: dict[str, InvestmentPosition] = {}
    for p in positions:
        key = p.instrument
        if key not in latest or (p.statement_date or "") >= (latest[key].statement_date or ""):
            latest[key] = p

    total_value = sum(p.current_value_eur or 0 for p in latest.values())
    if total_value <= 0:
        return {"suggestions": [], "allocation": {}}

    # Current allocation by type
    type_values: dict[str, float] = {}
    for p in latest.values():
        t = ASSET_TYPE_MAP.get(p.instrument, "other")
        type_values[t] = type_values.get(t, 0) + (p.current_value_eur or 0)

    current_alloc = {t: (v / total_value * 100) for t, v in type_values.items()}

    suggestions = []

    # 1. Rebalancing suggestions
    for asset_type, target_pct in TARGET_ALLOCATION.items():
        current_pct = current_alloc.get(asset_type, 0)
        diff = current_pct - target_pct
        if diff < -5:
            suggestions.append({
                "type": "rebalance",
                "severity": "high" if diff < -10 else "medium",
                "title": f"{asset_type.upper()} subponderado",
                "description": f"Tens {current_pct:.1f}% em {asset_type.upper()} (objetivo: {target_pct:.0f}%). Considera reforçar.",
                "action": f"Investir mais em {asset_type.upper()}",
            })
        elif diff > 10:
            suggestions.append({
                "type": "rebalance",
                "severity": "low",
                "title": f"{asset_type.upper()} sobreponderado",
                "description": f"Tens {current_pct:.1f}% em {asset_type.upper()} (objetivo: {target_pct:.0f}%). Atenção à concentração.",
                "action": f"Diversificar fora de {asset_type.upper()}",
            })

    # 2. Concentration warning
    sorted_positions = sorted(latest.values(), key=lambda p: (p.current_value_eur or 0), reverse=True)
    if len(sorted_positions) >= 3:
        top3_value = sum(p.current_value_eur or 0 for p in sorted_positions[:3])
        top3_pct = top3_value / total_value * 100
        if top3_pct > 75:
            names = ", ".join(ASSET_NAMES.get(p.instrument, p.instrument) for p in sorted_positions[:3])
            suggestions.append({
                "type": "concentration",
                "severity": "medium",
                "title": "Portfolio concentrado",
                "description": f"Top 3 ({names}) representam {top3_pct:.1f}% do portfolio.",
                "action": "Considerar diversificar em novos ativos",
            })

    # 3. Single asset > 30%
    for p in latest.values():
        pct = (p.current_value_eur or 0) / total_value * 100
        if pct > 30:
            name = ASSET_NAMES.get(p.instrument, p.instrument)
            suggestions.append({
                "type": "concentration",
                "severity": "medium",
                "title": f"{name} > 30%",
                "description": f"{name} representa {pct:.1f}% do portfolio. Risco de concentração.",
                "action": f"Limitar exposição a {name}",
            })

    # 4. Loss-making positions check
    for p in latest.values():
        ret = p.return_eur or 0
        val = p.current_value_eur or 1
        if ret < 0 and abs(ret) / val > 0.10:
            name = ASSET_NAMES.get(p.instrument, p.instrument)
            loss_pct = abs(ret) / (val + abs(ret)) * 100
            suggestions.append({
                "type": "review",
                "severity": "low",
                "title": f"{name} em perda ({loss_pct:.1f}%)",
                "description": f"{name} tem -{abs(ret):.2f}€ de retorno. Rever tese de investimento.",
                "action": "Avaliar se mantém ou reforça a posição",
            })

    # 5. Missing asset types suggestion
    all_types = set(TARGET_ALLOCATION.keys())
    held_types = set(type_values.keys())
    missing = all_types - held_types
    for t in missing:
        suggestions.append({
            "type": "diversification",
            "severity": "medium",
            "title": f"Sem exposição a {t.upper()}",
            "description": f"Não tens nenhuma posição em {t.upper()}. Objetivo: {TARGET_ALLOCATION[t]:.0f}%.",
            "action": f"Adicionar {t.upper()} ao portfolio",
        })

    # 6. DCA reminder (if not investing monthly)
    transactions = db.query(InvestmentTransaction).filter(
        InvestmentTransaction.type == "Depósito"
    ).order_by(InvestmentTransaction.time.desc()).all()
    if transactions:
        last_deposit = transactions[0].time
        days_since = (datetime.now() - last_deposit).days
        if days_since > 45:
            suggestions.append({
                "type": "dca",
                "severity": "high",
                "title": f"Sem depósito há {days_since} dias",
                "description": "A consistência é chave no DCA. Considera investir este mês.",
                "action": "Fazer depósito mensal",
            })

    return {
        "suggestions": suggestions,
        "allocation": {
            "current": {k: round(v, 1) for k, v in current_alloc.items()},
            "target": TARGET_ALLOCATION,
            "total_value": round(total_value, 2),
        },
    }


# Endpoint /ai-suggestions removido — a análise do plano vive agora em
# /investments/signals/analyze-plan (mesma IA dos Sinais IA, mas restrita ao plano de alocação).
