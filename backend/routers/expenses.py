from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from datetime import date, datetime
from typing import Optional
import os
import uuid
import csv
import io
import re
import subprocess
import tempfile
import json
import socket
import httpx
import logging

from database import get_db
from models import Expense, MonthlyIncome
from schemas import ExpenseCreate, ExpenseUpdate, ExpenseOut

router = APIRouter(prefix="/api/expenses", tags=["Expenses"])
logger = logging.getLogger(__name__)

UPLOAD_DIR = os.path.join(os.getenv("UPLOADS_DIR", "uploads"), "receipts")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ── Revolut CSV Auto-categorization ─────────────────────────────

CATEGORY_KEYWORDS = {
    "food": [
        "uber eats", "glovo", "bolt food", "mcdonalds", "mcdonald", "burger king",
        "kfc", "pizza", "starbucks", "cafe", "café", "restaurant", "restaurante",
        "padaria", "pastelaria", "sushi", "wok", "kebab",
        "telepizza", "dominos", "subway", "taco bell", "nando", "five guys",
        "bakery", "coffee", "food", "eat", "lunch", "dinner", "breakfast",
        "hesburger", "max burgers", "coffeebreak", "automat",
        "żabka", "zabka", "iki", "rimi",
    ],
    "groceries": [
        "supermercado", "mercado", "pingo doce", "continente",
        "lidl", "aldi", "minipreço", "intermarché",
        "biedronka", "netto", "carrefour", "albert", "tesco",
    ],
    "transport": [
        "uber", "bolt", "cabify", "taxi", "metro", "bus", "comboio",
        "cp ", "carris", "viva viagem", "combustível", "gasolina", "gasóleo",
        "fuel", "parking", "estacionamento", "portagem", "toll", "via verde",
        "stb bucuresti", "kauno autobusai", "jak dojad",
        "rigas satiksme", "rīgas satiksme",
    ],
    "travel": [
        "ryanair", "tap", "easyjet", "wizz", "vueling", "flight",
        "flixbus", "ecolines", "ltg link", "train",
        "hotel", "hostel", "airbnb", "booking", "trivago", "alojamento",
        "accommodation", "bagagem", "luggage",
    ],
    "entertainment": [
        "netflix", "spotify", "hbo", "disney", "apple tv", "youtube premium",
        "cinema", "bilhete", "ticket", "steam", "playstation", "xbox", "nintendo",
        "twitch", "gaming", "concert", "festival", "bar", "pub", "club", "discoteca",
        "skansen", "museum", "museu",
    ],
    "subscriptions": [
        "subscription", "subscrição", "mensal", "monthly", "annual", "anual",
        "icloud", "google one", "chatgpt", "openai", "github", "notion",
        "adobe", "office 365", "microsoft", "amazon prime",
    ],
    "shopping": [
        "zara", "h&m", "primark", "bershka", "pull&bear", "stradivarius",
        "nike", "adidas", "amazon", "aliexpress", "shein", "fnac", "worten",
        "ikea", "leroy merlin", "decathlon",
        "flying tiger", "cloudshop", "michelle art",
    ],
    "health": [
        "farmácia", "pharmacy", "médico", "doctor", "hospital", "clínica",
        "clinic", "dentista", "gym", "ginásio", "fitness", "saúde",
        "apteka",
    ],
    "bills": [
        "edp", "meo", "nos", "vodafone", "água", "water", "eletricidade",
        "electricity", "gás", "renda", "rent", "seguro", "insurance",
    ],
}


def _auto_categorize(description: str, notes: str = "") -> str:
    # For transfers, check the reference/notes for category hints
    text_to_check = f"{description} {notes}".lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text_to_check:
                return category
    return "other"


# ── AI Categorization ───────────────────────────────────────────

AI_API_URL = "https://api.iaedu.pt/agent-chat//api/v1/agent/cmamvd3n40000c801qeacoad2/stream"
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_CHANNEL_ID = "cmnauzuoxjik3hv01gjna24hw"

VALID_CATEGORIES = {"food", "groceries", "transport", "entertainment", "subscriptions", "shopping", "health", "bills", "travel", "other"}


# ── DNS Fallback ────────────────────────────────────────────────
# macOS DNS can fail while external DNS servers work fine.
# Patch socket.getaddrinfo to fall back to dig @8.8.8.8.

_original_getaddrinfo = socket.getaddrinfo
_dns_fallback_cache: dict[str, str] = {}


def _getaddrinfo_with_fallback(host, port, family=0, type=0, proto=0, flags=0):
    """getaddrinfo that falls back to dig @8.8.8.8 when system DNS fails."""
    # If we already have a cached fallback for this host, use it
    if host in _dns_fallback_cache:
        ip = _dns_fallback_cache[host]
        port_int = int(port) if port is not None else 0
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port_int)),
            (socket.AF_INET, socket.SOCK_DGRAM, 17, '', (ip, port_int)),
        ]
    try:
        return _original_getaddrinfo(host, port, family, type, proto, flags)
    except socket.gaierror:
        # System DNS failed — try external DNS
        try:
            result = subprocess.run(
                ["dig", "+short", host, "@8.8.8.8"],
                capture_output=True, text=True, timeout=10,
            )
            lines = [l.strip() for l in result.stdout.strip().split("\n")
                     if l.strip() and not l.strip().startswith(";")]
            if lines:
                ip = lines[0]
                _dns_fallback_cache[host] = ip
                logger.info(f"DNS fallback: {host} -> {ip}")
                port_int = int(port) if port is not None else 0
                return [
                    (socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port_int)),
                    (socket.AF_INET, socket.SOCK_DGRAM, 17, '', (ip, port_int)),
                ]
        except Exception as e:
            logger.warning(f"DNS fallback also failed for {host}: {e}")
        raise


socket.getaddrinfo = _getaddrinfo_with_fallback


async def _ai_categorize_batch(items: list[dict]) -> dict[int, str]:
    """
    Send a batch of expense descriptions to AI for categorization.
    items: list of dicts with at least 'idx' and 'description', optionally 'merchant_city', 'merchant_country'
    Returns: dict mapping idx -> category string
    """
    if not items:
        return {}

    # Build the prompt
    lines = []
    for item in items:
        extra = ""
        if item.get("notes"):
            extra += f" — {item['notes']}"
        if item.get("merchant_city"):
            extra += f" (em {item['merchant_city']}"
            if item.get("merchant_country"):
                extra += f", {item['merchant_country']}"
            extra += ")"
        if item.get("original_currency") and item["original_currency"] != "EUR":
            extra += f" [{item['original_currency']}]"
        lines.append(f"{item['idx']}. {item['description']}{extra}")

    descriptions_text = "\n".join(lines)

    prompt = f"""Categoriza cada gasto numa destas categorias EXATAS:
food, groceries, transport, entertainment, subscriptions, shopping, health, bills, travel, other

Contexto das categorias:
- food: restaurantes, cafés, fast food, comida pronta (McDonald's, Hesburger, etc)
- groceries: supermercados, mercearias, compras de comida para cozinhar (Lidl, Żabka, Rimi, IKI, etc)
- transport: transportes LOCAIS do dia-a-dia (metro, autocarro urbano, táxi, Uber, Bolt, combustível, parking)
- travel: viagens — voos (Ryanair, Wizz Air), autocarros longa distância (FlixBus, Ecolines), comboios, hotéis, alojamento, Booking
- entertainment: cinema, jogos, bares, streaming, eventos, museus
- subscriptions: subscrições mensais/anuais (GitHub, Netflix, iCloud, etc)
- shopping: roupa, eletrónica, lojas em geral (Flying Tiger, CloudShop, etc), presentes, souvenirs
- health: farmácias, médicos, ginásios
- bills: contas de casa (água, luz, renda)
- other: APENAS se realmente não encaixar em nenhuma — evita usar other

ATENÇÃO:
- Transferências bancárias ("Transfer to...") devem ser categorizadas pelo DESTINO indicado nas notas.
  Ex: "Transfer to X — Para Ryanair" = travel, "Transfer to X — Para Booking.com" = travel
- Transporte LOCAL no estrangeiro (metro, autocarro urbano) durante viagem = travel, NÃO transport.
  Ex: STB Bucuresti [RON] = travel, Rīgas satiksme [EUR em Letónia] = travel
- transport é APENAS para deslocações do dia-a-dia em Portugal.

Responde APENAS com um JSON object no formato: {{"1": "food", "2": "transport", ...}}
Sem texto extra, apenas o JSON.

Gastos:
{descriptions_text}"""

    try:
        thread_id = uuid.uuid4().hex[:20]

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                AI_API_URL,
                headers={"x-api-key": AI_API_KEY},
                data={
                    "channel_id": AI_CHANNEL_ID,
                    "thread_id": thread_id,
                    "user_info": "{}",
                    "message": prompt,
                },
            )

            if response.status_code != 200:
                logger.warning(f"AI categorization failed: HTTP {response.status_code}")
                return {}

            # Parse response — each line is a JSON object with type/content fields
            # Look for the "message" event which has the full AI response,
            # or accumulate "token" events as fallback
            full_text = ""
            token_text = ""
            for line in response.text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if event.get("type") == "message":
                        content = event.get("content", {})
                        if isinstance(content, dict):
                            full_text = content.get("content", "")
                        else:
                            full_text = str(content)
                        break
                    elif event.get("type") == "token":
                        token_text += event.get("content", "")
                except json.JSONDecodeError:
                    continue

            if not full_text:
                full_text = token_text

            logger.info(f"AI response ({len(full_text)} chars): {full_text[:200]}")

        # Extract JSON — AI may wrap it in ```json ... ```
        code_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', full_text, re.DOTALL)
        if code_match:
            json_str = code_match.group(1)
        else:
            json_match = re.search(r'\{[^{}]*\}', full_text, re.DOTALL)
            if not json_match:
                logger.warning(f"AI response has no JSON: {full_text[:300]}")
                return {}
            json_str = json_match.group()

        result = json.loads(json_str)

        # Validate and map
        categorized = {}
        for key, val in result.items():
            idx = int(key)
            cat = val.strip().lower()
            if cat in VALID_CATEGORIES:
                categorized[idx] = cat
            else:
                logger.warning(f"AI returned invalid category '{cat}' for item {idx}")

        return categorized

    except Exception as e:
        logger.warning(f"AI categorization error: {e}")
        return {}


async def _smart_categorize(descriptions: list[dict]) -> dict[int, str]:
    """
    Try AI first, fall back to keyword-based for any items AI didn't categorize.
    descriptions: list of dicts with 'idx', 'description', and optional location fields.
    Returns: dict mapping idx -> category
    """
    # Try AI batch categorization
    ai_results = await _ai_categorize_batch(descriptions)

    # Merge: AI wins if it gives a specific category, keyword fallback otherwise
    results = {}
    for item in descriptions:
        idx = item["idx"]
        ai_cat = ai_results.get(idx)
        kw_cat = _auto_categorize(item["description"], item.get("notes", ""))

        if ai_cat and ai_cat != "other":
            results[idx] = ai_cat
        elif kw_cat != "other":
            results[idx] = kw_cat
        elif ai_cat:
            results[idx] = ai_cat
        else:
            results[idx] = kw_cat

        # Post-processing for abroad expenses
        country = (item.get("merchant_country") or "").upper().strip()
        currency = (item.get("original_currency") or "").upper().strip()
        is_abroad = (
            (country and country not in ("", "PRT", "PT", "POR", "PORTUGAL"))
            or (currency and currency not in ("", "EUR"))
        )
        if is_abroad:
            # transport abroad = travel
            if results[idx] == "transport":
                results[idx] = "travel"

        # Convenience stores → food (they sell ready-made food, not groceries)
        desc_lower = item.get("description", "").lower()
        convenience_stores = ["żabka", "zabka", "iki", "rimi"]
        if results[idx] == "groceries" and any(s in desc_lower for s in convenience_stores):
            results[idx] = "food"

    return results


@router.get("/", response_model=list[ExpenseOut])
def list_expenses(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    category: Optional[str] = Query(None),
    trip_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Expense)
    if start_date:
        q = q.filter(Expense.date >= start_date)
    if end_date:
        q = q.filter(Expense.date <= end_date)
    if category:
        q = q.filter(Expense.category == category)
    if trip_id is not None:
        q = q.filter(Expense.trip_id == trip_id)
    return q.order_by(Expense.date.desc()).all()


@router.get("/summary")
def expense_summary(
    month: Optional[int] = Query(None),
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(
        Expense.category,
        func.sum(Expense.amount).label("total"),
        func.count(Expense.id).label("count"),
    )
    if month and year:
        q = q.filter(
            extract("month", Expense.date) == month,
            extract("year", Expense.date) == year,
        )
    elif year:
        q = q.filter(extract("year", Expense.date) == year)

    rows = q.group_by(Expense.category).all()
    return [{"category": r.category, "total": r.total, "count": r.count} for r in rows]


DEFAULT_INCOME = 1040.98


@router.get("/income")
def get_income(
    month: int = Query(...),
    year: int = Query(...),
    db: Session = Depends(get_db),
):
    row = db.query(MonthlyIncome).filter(
        MonthlyIncome.month == month,
        MonthlyIncome.year == year,
    ).first()
    return {"amount": row.amount if row else DEFAULT_INCOME}


@router.put("/income")
def set_income(
    month: int = Query(...),
    year: int = Query(...),
    amount: float = Query(...),
    db: Session = Depends(get_db),
):
    row = db.query(MonthlyIncome).filter(
        MonthlyIncome.month == month,
        MonthlyIncome.year == year,
    ).first()
    if row:
        row.amount = amount
    else:
        row = MonthlyIncome(month=month, year=year, amount=amount)
        db.add(row)
    db.commit()
    return {"amount": row.amount}


@router.get("/{expense_id}", response_model=ExpenseOut)
def get_expense(expense_id: int, db: Session = Depends(get_db)):
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    return expense


@router.post("/", response_model=ExpenseOut)
def create_expense(data: ExpenseCreate, db: Session = Depends(get_db)):
    expense = Expense(**data.model_dump())
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.post("/{expense_id}/receipt", response_model=ExpenseOut)
async def upload_receipt(expense_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    ext = os.path.splitext(file.filename or "img.png")[1]
    allowed_extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}
    if ext.lower() not in allowed_extensions:
        raise HTTPException(status_code=400, detail="File type not allowed")

    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")
    with open(filepath, "wb") as f:
        f.write(content)

    expense.receipt_image = filepath
    db.commit()
    db.refresh(expense)
    return expense


@router.put("/{expense_id}", response_model=ExpenseOut)
def update_expense(expense_id: int, data: ExpenseUpdate, db: Session = Depends(get_db)):
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(expense, key, value)
    db.commit()
    db.refresh(expense)
    return expense


@router.delete("/{expense_id}")
def delete_expense(expense_id: int, db: Session = Depends(get_db)):
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    db.delete(expense)
    db.commit()
    return {"ok": True}


# ── AI Re-categorize existing expenses ───────────────────────────

@router.post("/recategorize")
async def recategorize_expenses(
    month: Optional[int] = Query(None),
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Re-categorize all expenses for a given month/year using AI."""
    q = db.query(Expense)
    if month and year:
        q = q.filter(
            extract("month", Expense.date) == month,
            extract("year", Expense.date) == year,
        )
    elif year:
        q = q.filter(extract("year", Expense.date) == year)
    else:
        raise HTTPException(status_code=400, detail="Provide at least year")

    expenses = q.all()
    if not expenses:
        return {"updated": 0}

    items = []
    for i, exp in enumerate(expenses):
        items.append({
            "idx": i,
            "description": exp.description,
            "notes": exp.notes or "",
            "merchant_city": exp.merchant_city,
            "merchant_country": exp.merchant_country,
            "original_currency": exp.original_currency,
        })

    categories = await _smart_categorize(items)

    updated = 0
    for i, exp in enumerate(expenses):
        new_cat = categories.get(i, exp.category)
        if new_cat != exp.category:
            exp.category = new_cat
            updated += 1

    db.commit()
    return {"updated": updated, "total": len(expenses)}


# ── Revolut CSV Import ───────────────────────────────────────────

@router.post("/import/csv")
async def import_revolut_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file")

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")

    text = content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    skipped = 0
    errors = []
    pending_items = []  # items to categorize and insert

    for row_num, row in enumerate(reader, start=2):
        try:
            desc = row.get("Description", "").strip()
            amount_str = row.get("Amount", "0").strip()
            state = row.get("State", "").strip().upper()
            date_str = row.get("Completed Date", row.get("Started Date", "")).strip()

            if state not in ("COMPLETED", ""):
                skipped += 1
                continue

            amount = float(amount_str)
            if amount >= 0:
                skipped += 1
                continue

            amount = abs(amount)

            parsed_date = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d %b %Y", "%d/%m/%Y"):
                try:
                    parsed_date = datetime.strptime(date_str.split(" ")[0] if " " in date_str and fmt == "%Y-%m-%d" else date_str, fmt).date()
                    break
                except ValueError:
                    continue

            if not parsed_date:
                try:
                    parsed_date = datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
                except Exception:
                    errors.append(f"Row {row_num}: Could not parse date '{date_str}'")
                    continue

            if not desc:
                desc = row.get("Type", "Revolut Transaction")

            # Dedup
            existing = db.query(Expense).filter(
                Expense.description == desc,
                Expense.amount == round(amount, 2),
                Expense.date == parsed_date,
            ).first()
            if existing:
                skipped += 1
                continue

            pending_items.append({
                "idx": len(pending_items),
                "description": desc,
                "amount": round(amount, 2),
                "date": parsed_date,
            })

        except Exception as e:
            errors.append(f"Row {row_num}: {str(e)}")

    # AI batch categorization
    categories = await _smart_categorize(pending_items)

    imported = 0
    for item in pending_items:
        expense = Expense(
            description=item["description"],
            amount=item["amount"],
            category=categories.get(item["idx"], "other"),
            date=item["date"],
            notes="Importado do Revolut",
        )
        db.add(expense)
        imported += 1

    db.commit()
    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors[:10],
    }


# ── Revolut PDF Import ───────────────────────────────────────────

MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

# Country code to flag emoji + name
COUNTRY_INFO = {
    "POL": ("🇵🇱", "Polónia"), "SWE": ("🇸🇪", "Suécia"), "ROM": ("🇷🇴", "Roménia"),
    "LTU": ("🇱🇹", "Lituânia"), "LVA": ("🇱🇻", "Letónia"), "EST": ("🇪🇪", "Estónia"),
    "D": ("🇩🇪", "Alemanha"), "DEU": ("🇩🇪", "Alemanha"), "FRA": ("🇫🇷", "França"),
    "ESP": ("🇪🇸", "Espanha"), "ITA": ("🇮🇹", "Itália"), "GBR": ("🇬🇧", "Reino Unido"),
    "USA": ("🇺🇸", "EUA"), "NLD": ("🇳🇱", "Holanda"), "BEL": ("🇧🇪", "Bélgica"),
    "AUT": ("🇦🇹", "Áustria"), "CHE": ("🇨🇭", "Suíça"), "PRT": ("🇵🇹", "Portugal"),
    "GRC": ("🇬🇷", "Grécia"), "CZE": ("🇨🇿", "Chéquia"), "HUN": ("🇭🇺", "Hungria"),
    "HRV": ("🇭🇷", "Croácia"), "BGR": ("🇧🇬", "Bulgária"), "DNK": ("🇩🇰", "Dinamarca"),
    "FIN": ("🇫🇮", "Finlândia"), "NOR": ("🇳🇴", "Noruega"), "IRL": ("🇮🇪", "Irlanda"),
    "TUR": ("🇹🇷", "Turquia"), "MAR": ("🇲🇦", "Marrocos"), "BRA": ("🇧🇷", "Brasil"),
    "B": ("🇧🇪", "Bélgica"),
}


def _parse_revolut_pdf(text: str) -> list[dict]:
    """Parse Revolut PDF text into transaction dicts."""
    lines = text.split("\n")
    transactions = []

    # Date pattern: "Apr 1, 2026" or "Apr 08, 2026"
    date_re = re.compile(
        r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),\s+(\d{4})\s+"
    )
    # Money pattern: €1,234.56 or €1.17
    money_re = re.compile(r"€([\d,]+\.\d{2})")
    # Revolut rate line with original amount
    rate_re = re.compile(r"Revolut Rate.*?([\d,.]+)\s+([A-Z]{3})\s*$")
    # Original amount at end of line (e.g., "5.00 PLN" or "80.00 RON")
    orig_amount_re = re.compile(r"([\d,.]+)\s+([A-Z]{3})\s*$")
    # To: line with merchant info
    to_re = re.compile(r"^To:\s+(.+)")
    # Reference line for transfers
    ref_re = re.compile(r"^Reference:\s+(.+)")

    # Find sections
    in_account_section = False
    in_pending_section = False
    in_reverted_section = False

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Detect sections
        if "Account transactions from" in line:
            in_account_section = True
            in_pending_section = False
            in_reverted_section = False
            i += 1
            continue
        if "Pending from" in line:
            in_pending_section = True
            in_account_section = False
            in_reverted_section = False
            i += 1
            continue
        if "Reverted from" in line:
            in_reverted_section = True
            in_account_section = False
            in_pending_section = False
            i += 1
            continue
        # Skip header rows
        if line in ("Date Description Money out Money in Balance",
                     "Start date Description Money out Money in",
                     "Start date Description Money out Money in Balance"):
            i += 1
            continue

        # Only process account transactions (completed)
        if not in_account_section:
            i += 1
            continue

        # Try to match a transaction start line
        m = date_re.match(line)
        if m:
            month_str, day_str, year_str = m.group(1), m.group(2), m.group(3)
            tx_date = date(int(year_str), MONTH_MAP[month_str], int(day_str))

            # Rest of line after date
            rest = line[m.end():].strip()

            # Extract EUR amounts from the line
            amounts = money_re.findall(rest)
            # Remove the amounts from rest to get description
            desc_part = money_re.sub("", rest).strip()
            # Clean up extra spaces
            desc_part = re.sub(r"\s{2,}", " ", desc_part).strip()

            money_out = None
            money_in = None
            if len(amounts) >= 1:
                # Determine if it's money out or money in
                # If there's balance at end, last amount is balance
                # For "money out" lines: amount balance
                # For "money in" lines: amount balance (but amount is in "Money in" column)
                # We detect "money in" by checking if it has 2+ amounts and description doesn't suggest expense
                first_amount = float(amounts[0].replace(",", ""))

                # Revolut credits the user with these patterns — treat as money_in:
                #   "Apple Pay deposit by *XXXX", "Top-up by ...", "Transfer from PERSON",
                #   "Refund from ...", "Incoming ..."
                desc_lower = desc_part.lower()
                is_money_in = any(kw in desc_lower for kw in [
                    "top-up", "incoming", "refund", "deposit", "transfer from",
                ])

                if len(amounts) >= 2:
                    if is_money_in:
                        money_in = first_amount
                    else:
                        money_out = first_amount
                elif len(amounts) == 1:
                    if is_money_in:
                        money_in = first_amount
                    else:
                        money_out = first_amount

            if money_out is None and money_in is None:
                i += 1
                continue

            # Now collect detail lines until next date line or section change
            original_amount = None
            original_currency = None
            merchant_city = None
            merchant_country = None
            reference = None

            j = i + 1
            while j < len(lines):
                detail = lines[j].strip()
                if not detail or date_re.match(detail):
                    break
                if "Account transactions from" in detail or "Pending from" in detail or "Reverted from" in detail:
                    break
                if detail.startswith("Date ") or detail.startswith("Start date "):
                    break
                # Skip page footer/header lines
                if any(kw in detail for kw in ["Revolut Bank UAB", "Page ", "Report lost",
                                                  "© 20", "EUR Statement", "Generated on",
                                                  "Get help", "Scan the QR"]):
                    j += 1
                    continue

                # Revolut Rate line (original amount)
                rate_m = orig_amount_re.search(detail)
                if "Revolut Rate" in detail and rate_m:
                    original_amount = float(rate_m.group(1).replace(",", ""))
                    original_currency = rate_m.group(2)
                elif rate_m and detail[0].isdigit() and not detail.startswith("To:"):
                    # Standalone original amount line like "5.00 PLN"
                    original_amount = float(rate_m.group(1).replace(",", ""))
                    original_currency = rate_m.group(2)

                # To: line
                to_m = to_re.match(detail)
                if to_m:
                    to_parts = to_m.group(1).split(",")
                    to_parts = [p.strip() for p in to_parts if p.strip()]
                    if len(to_parts) >= 3:
                        merchant_city = to_parts[-2]
                        merchant_country = to_parts[-1]
                        # Clean up numeric-only city/country (sometimes address numbers)
                        if merchant_country.isdigit():
                            merchant_country = None
                        if merchant_city and merchant_city.isdigit():
                            merchant_city = to_parts[-3] if len(to_parts) >= 4 else None
                    elif len(to_parts) == 2:
                        merchant_city = to_parts[-1]

                # Reference line
                ref_m = ref_re.match(detail)
                if ref_m:
                    reference = ref_m.group(1)

                j += 1

            # Skip incoming money (top-ups)
            if money_in and not money_out:
                i = j
                continue

            amt = money_out or 0.0

            # For transfers, clean up description and add reference
            notes_parts = []
            if reference:
                notes_parts.append(reference)
            if original_currency and original_currency != "EUR":
                notes_parts.append(f"{original_amount} {original_currency}")

            # If no original currency, it's EUR
            if not original_currency:
                original_currency = "EUR"
                original_amount = amt

            tx = {
                "description": desc_part,
                "amount": round(amt, 2),
                "date": tx_date,
                "original_amount": original_amount,
                "original_currency": original_currency,
                "merchant_city": merchant_city,
                "merchant_country": merchant_country,
                "notes": " · ".join(notes_parts) if notes_parts else "",
            }
            transactions.append(tx)
            i = j
            continue

        i += 1

    return transactions


@router.post("/import/pdf")
async def import_revolut_pdf(
    file: UploadFile = File(...),
    clean: bool = False,
    db: Session = Depends(get_db),
):
    """Import a Revolut monthly statement PDF.

    With `clean=true`, before importing, deletes any expense in the PDF's date range
    that looks like a wrongly-categorized deposit (Apple Pay deposit, Top-up,
    Transfer from …) so reimporting doesn't leave stale junk behind.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    # Write to temp file for pdftotext
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["pdftotext", "-layout", tmp_path, "-"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"pdftotext failed: {result.stderr}")
        pdf_text = result.stdout
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="pdftotext not installed (brew install poppler)")
    finally:
        os.unlink(tmp_path)

    transactions = _parse_revolut_pdf(pdf_text)

    cleaned = 0
    if clean and transactions:
        min_d = min(tx["date"] for tx in transactions)
        max_d = max(tx["date"] for tx in transactions)
        cleaned = (
            db.query(Expense)
            .filter(
                Expense.date >= min_d,
                Expense.date <= max_d,
                (
                    Expense.description.like("Apple Pay deposit%")
                    | Expense.description.like("Transfer from%")
                    | Expense.description.like("Top-up%")
                ),
            )
            .delete(synchronize_session=False)
        )
        db.commit()

    imported = 0
    skipped = 0
    errors = []

    # First pass: dedup and collect new items for AI categorization
    pending_items = []
    pending_txs = []

    for tx in transactions:
        try:
            existing = db.query(Expense).filter(
                Expense.description == tx["description"],
                Expense.amount == tx["amount"],
                Expense.date == tx["date"],
            ).first()
            if existing:
                # Update existing with new PDF fields if missing
                if not existing.original_currency and tx.get("original_currency"):
                    existing.original_currency = tx["original_currency"]
                    existing.original_amount = tx.get("original_amount")
                if not existing.merchant_city and tx.get("merchant_city"):
                    existing.merchant_city = tx["merchant_city"]
                if not existing.merchant_country and tx.get("merchant_country"):
                    existing.merchant_country = tx["merchant_country"]
                skipped += 1
                continue

            pending_items.append({
                "idx": len(pending_items),
                "description": tx["description"],
                "merchant_city": tx.get("merchant_city"),
                "merchant_country": tx.get("merchant_country"),
                "original_currency": tx.get("original_currency"),
            })
            pending_txs.append(tx)

        except Exception as e:
            errors.append(f"{tx.get('description', '?')}: {str(e)}")

    # AI batch categorization
    categories = await _smart_categorize(pending_items)

    for i, tx in enumerate(pending_txs):
        expense = Expense(
            description=tx["description"],
            amount=tx["amount"],
            category=categories.get(i, "other"),
            date=tx["date"],
            notes=tx.get("notes", "") or "Importado do Revolut PDF",
            original_amount=tx.get("original_amount"),
            original_currency=tx.get("original_currency"),
            merchant_city=tx.get("merchant_city"),
            merchant_country=tx.get("merchant_country"),
        )
        db.add(expense)
        imported += 1

    db.commit()
    return {
        "imported": imported,
        "skipped": skipped,
        "cleaned": cleaned,
        "errors": errors[:10],
        "total_parsed": len(transactions),
    }
