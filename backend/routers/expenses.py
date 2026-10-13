from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Body
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from datetime import date, datetime, timedelta
from typing import Optional
import os
import shutil
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
from models import Expense, ExpenseCategory, MerchantRule, MonthlyIncome, ReimbursementLink, SalaryPayday
from schemas import ExpenseCreate, ExpenseUpdate, ExpenseOut
import expense_kind as ek
import receipt_ocr
from ai_config import AI_API_KEY, ask_agent_async, extract_json
from routers.budgets import resolve_income

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
        "twitch", "gaming", "concert", "festival",
        "skansen", "museum", "museu",
    ],
    "nightlife": ["discoteca", "club", "klub", "bar", "pub"],
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


# Overrides fortes: forçam a categoria mesmo contra a IA (para casos que a IA
# categoriza noutra coisa mas o utilizador quer fixo).
CATEGORY_OVERRIDES = {
    "rodrigo de sousa pascoal": "travel",   # despesas partilhadas em viagem
    "nuno jose freitas": "travel",          # despesas partilhadas em viagem
    "zeitraum": "bills",                    # renda da residência em Cracóvia
}


def _category_override(description: str, notes: str = "", amount: float | None = None) -> Optional[str]:
    text = f"{description} {notes}".lower()
    # Subscrição Claude cobrada via Apple (2,99€)
    if "apple" in text and amount is not None and abs(round(amount, 2)) == 2.99:
        return "bills"
    for kw, cat in CATEGORY_OVERRIDES.items():
        if kw in text:
            return cat
    return None


# ── AI Categorization ───────────────────────────────────────────
# Agente IA (URL/key/channel) vem de ai_config — partilhado e já no novo Opus 4.7.

VALID_CATEGORIES = {"food", "groceries", "transport", "entertainment", "nightlife", "subscriptions", "shopping", "health", "bills", "travel", "other"}


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
food, groceries, transport, entertainment, nightlife, subscriptions, shopping, health, bills, travel, other

Contexto das categorias:
- food: restaurantes, cafés, fast food, comida pronta (McDonald's, Hesburger, etc)
- groceries: supermercados, mercearias, compras de comida para cozinhar (Lidl, Żabka, Rimi, IKI, etc)
- transport: transportes LOCAIS do dia-a-dia (metro, autocarro urbano, táxi, Uber, Bolt, combustível, parking)
- travel: viagens — voos (Ryanair, Wizz Air), autocarros longa distância (FlixBus, Ecolines), comboios, hotéis, alojamento, Booking
- entertainment: cinema, jogos, streaming, eventos, museus
- nightlife: sair à noite — discotecas, clubes, bares à noite, entradas e bebidas
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
        # Escolher entre dez categorias não precisa do agente partilhado: o modelo
        # local do Mac chega, é de graça e não entra na fila. Só se ele não estiver
        # de pé é que se gasta quota.
        import asyncio as _asyncio
        import local_ai

        result = await _asyncio.to_thread(local_ai.pergunta_json, prompt, timeout=180.0)
        onde = "local"
        if not isinstance(result, dict):
            onde = "agente"
            full_text = await ask_agent_async(prompt, feature="lojas_banco")
            if not full_text:
                logger.warning("AI categorization: resposta vazia/indisponível")
                return {}
            result = extract_json(full_text)
        if not isinstance(result, dict):
            logger.warning("AI categorization: sem JSON utilizável")
            return {}
        logger.info("categorização de gastos por %s: %s itens", onde, len(result))

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

        # Overrides fortes ganham sobre a IA
        override = _category_override(item["description"], item.get("notes", ""), item.get("amount"))
        if override:
            results[idx] = override
            continue

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
    kind: Optional[str] = Query(None, description="spend | income | transfer | reversal"),
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
    if kind:
        q = q.filter(Expense.kind == kind)
    linhas = q.order_by(Expense.date.desc()).all()
    _junta_reembolsos(db, linhas)
    return linhas


def _junta_reembolsos(db: Session, linhas: list) -> None:
    """Põe em cada conta o que já foi devolvido, e em cada reembolso de que conta é
    — as duas pontas podem estar em meses diferentes da lista."""
    ids = [e.id for e in linhas if (e.amount or 0) > 0]
    devolvido = _devolvido(db, ids) if ids else {}
    entradas = [e.id for e in linhas if e.reimburses_id]
    contas_de: dict[int, list[int]] = {}
    if entradas:
        for l in db.query(ReimbursementLink).filter(ReimbursementLink.income_id.in_(entradas)).all():
            contas_de.setdefault(l.income_id, []).append(l.expense_id)
    todas = {c for cs in contas_de.values() for c in cs}
    nomes = ({c.id: c.description for c in db.query(Expense).filter(Expense.id.in_(todas)).all()}
             if todas else {})
    for e in linhas:
        total, n = devolvido.get(e.id, (0.0, 0))
        e.reimbursed_total = round(total, 2)
        e.reimbursed_count = n
        cs = sorted(contas_de.get(e.id, []), key=lambda c: c != e.reimburses_id)
        e.reimburses_description = (" + ".join(nomes.get(c, "?") for c in cs) or None) if e.reimburses_id else None


def _devolvido(db: Session, contas: Optional[list[int]] = None,
               excepto_entrada: Optional[int] = None) -> dict[int, tuple[float, int]]:
    """Por conta: quanto já foi devolvido e por quantas entradas."""
    q = db.query(ReimbursementLink)
    if contas is not None:
        q = q.filter(ReimbursementLink.expense_id.in_(contas or [-1]))
    saida: dict[int, tuple[float, int]] = {}
    for l in q.all():
        if l.income_id == excepto_entrada:
            continue
        total, n = saida.get(l.expense_id, (0.0, 0))
        saida[l.expense_id] = (total + l.amount, n + 1)
    return saida


def _acompanha_conta(db: Session, conta: Expense) -> None:
    """Os reembolsos de uma conta vivem na categoria dela, e saem das comparações
    se ela sair (compra extraordinária)."""
    for r in db.query(Expense).filter(Expense.reimburses_id == conta.id).all():
        r.category = conta.category
        r.extraordinary = conta.extraordinary


@router.get("/summary")
def expense_summary(
    month: Optional[int] = Query(None),
    year: Optional[int] = Query(None),
    recurring_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Gasto por categoria. Só conta consumo a sério: o dinheiro que foi para a
    corretora e as compras que voltaram atrás ficam de fora (ver /movements)."""
    q = db.query(
        Expense.category,
        func.sum(Expense.amount).label("total"),
        func.count(Expense.id).label("count"),
    ).filter(Expense.kind == ek.GASTO)
    if recurring_only:
        q = q.filter(Expense.extraordinary.is_(False))
    if month and year:
        q = q.filter(
            extract("month", Expense.date) == month,
            extract("year", Expense.date) == year,
        )
    elif year:
        q = q.filter(extract("year", Expense.date) == year)

    rows = q.group_by(Expense.category).all()
    return [{"category": r.category, "total": r.total, "count": r.count} for r in rows]


@router.get("/movements")
def movimentos_por_tipo(
    month: Optional[int] = Query(None),
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """O que passou na conta, separado por natureza.

    Existe porque um número só mentia: em Julho a app dizia 332€ gastos quando
    tinham saído 1.437€ — a diferença eram 1.091€ que voltaram da corretora e
    587€ de compras revertidas."""
    q = db.query(Expense)
    if month and year:
        q = q.filter(extract("month", Expense.date) == month,
                     extract("year", Expense.date) == year)
    elif year:
        q = q.filter(extract("year", Expense.date) == year)
    linhas = q.all()
    fora = ek.resume(linhas)
    fora["month"] = month
    fora["year"] = year
    # As transferências merecem detalhe: é dinheiro dele que mudou de sítio.
    fora["transfer_rows"] = [
        {"date": e.date.isoformat(), "description": e.description, "amount": round(e.amount, 2)}
        for e in sorted((x for x in linhas if x.kind == ek.TRANSFERENCIA), key=lambda x: x.date)
    ]
    return fora


def _planos_klarna(db: Session, ensaio: Optional[tuple] = None) -> list[dict]:
    """Os planos da Klarna com as prestações que o banco já mostra. `ensaio` é um
    par (despesa, vezes) para ver como ficava antes de gravar."""
    import klarna
    marcadas = [(e, e.klarna_installments)
                for e in db.query(Expense).filter(Expense.klarna_installments.isnot(None)).all()
                if not ensaio or e.id != ensaio[0].id]
    if ensaio:
        marcadas.append(ensaio)
    if not marcadas:
        return []
    desde = min(klarna.mais_meses(e.date, -(v - 1)) for e, v in marcadas) - klarna.FOLGA
    movimentos = db.query(Expense).filter(Expense.date >= desde, Expense.kind == ek.GASTO).all()
    return klarna.planos(marcadas, movimentos, date.today())


@router.get("/klarna")
def klarna_por_pagar(db: Session = Depends(get_db)):
    """Prestações da Klarna que ainda faltam, por mês: o que tem de ficar de lado."""
    import klarna
    return klarna.por_pagar(_planos_klarna(db))


@router.get("/yearly")
def yearly_breakdown(year: int = Query(...), db: Session = Depends(get_db)):
    """Totais por mês e por categoria de um ano — para a vista comparativa."""
    rows = (
        db.query(
            extract("month", Expense.date).label("month"),
            Expense.category,
            func.sum(Expense.amount).label("total"),
            func.count(Expense.id).label("count"),
        )
        .filter(extract("year", Expense.date) == year, Expense.kind == ek.GASTO)
        .group_by("month", Expense.category)
        .all()
    )

    months = [{"month": m, "total": 0.0, "by_category": {}} for m in range(1, 13)]
    cat_totals: dict[str, float] = {}
    for r in rows:
        mi = int(r.month) - 1
        months[mi]["by_category"][r.category] = round(r.total, 2)
        months[mi]["total"] = round(months[mi]["total"] + r.total, 2)
        cat_totals[r.category] = round(cat_totals.get(r.category, 0.0) + r.total, 2)

    # A compra grande e pontual vai assinalada à parte: um mês com a mota não se
    # compara com um mês de supermercado, mas o total também não a pode esconder.
    extras = {
        int(m): round(v or 0, 2) for m, v in
        db.query(extract("month", Expense.date), func.sum(Expense.amount))
        .filter(extract("year", Expense.date) == year, Expense.kind == ek.GASTO,
                Expense.extraordinary.is_(True))
        .group_by(extract("month", Expense.date)).all()
    }
    for linha in months:
        linha["extraordinary"] = extras.get(linha["month"], 0.0)
        linha["recurring"] = round(linha["total"] - linha["extraordinary"], 2)

    # Gasto vs recebido — pela natureza do movimento, não pelo sinal. Pelo sinal,
    # os 1.091€ que voltaram da corretora em Julho apareciam como "recebido" e
    # apagavam o mesmo valor aos gastos do ano.
    do_ano = db.query(Expense).filter(extract("year", Expense.date) == year).all()
    contas = ek.resume(do_ano)
    spent = contas["spent"]
    refunds = -contas["income"]

    # Salário recebido: só meses com actividade (gastos ou rendimento registado),
    # limitado ao mês actual no ano corrente. Evita salário "fantasma" em anos sem dados.
    today = date.today()
    month_limit = today.month if year == today.year else 12
    active_months = {i + 1 for i, mo in enumerate(months) if mo["by_category"]}
    active_months |= {int(r.month) for r in db.query(MonthlyIncome).filter(MonthlyIncome.year == year).all()}
    active_months = {m for m in active_months if m <= month_limit}
    total_salary = round(sum(resolve_income(db, m, year) for m in active_months), 2)

    return {
        "year": year,
        "categories": sorted(cat_totals, key=lambda c: -cat_totals[c]),
        "category_totals": cat_totals,
        "months": months,
        "total": round(sum(cat_totals.values()), 2),
        "total_spent": round(spent, 2),
        "total_refunds": round(abs(refunds), 2),
        "total_salary": total_salary,
        "total_received": round(abs(refunds) + total_salary, 2),
        "total_transfers": contas["transfers"],
        "total_reversed": contas["reversed"],
    }


DEFAULT_INCOME = 1040.98


@router.get("/income")
def get_income(
    month: int = Query(...),
    year: int = Query(...),
    db: Session = Depends(get_db),
):
    return {"amount": resolve_income(db, month, year)}


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


@router.get("/by-city")
def spending_by_city(
    year: Optional[int] = Query(None),
    days: Optional[int] = Query(None, ge=7, le=3650),
    db: Session = Depends(get_db),
):
    """Gastos por cidade, prontos para o mapa. Nomes normalizados (Warszawa/Warsaw
    é a mesma cidade) e o que não é cidade (IBANs, códigos de terminal) fica de fora."""
    import cities as cidades_mod
    from models import Trip

    q = db.query(Expense).filter(Expense.kind == ek.GASTO)
    if days:
        q = q.filter(Expense.date >= date.today() - timedelta(days=days - 1))
    elif year:
        q = q.filter(extract("year", Expense.date) == year)
    gastos = q.all()

    porcidade: dict[str, dict] = {}
    desconhecido = {"total": 0.0, "count": 0}
    for e in gastos:
        r = cidades_mod.resolve(e.merchant_city)
        if not r:
            desconhecido["total"] += e.amount
            desconhecido["count"] += 1
            continue
        nome, pais, lat, lon = r
        c = porcidade.setdefault(nome, {
            "city": nome, "country": pais, "lat": lat, "lon": lon,
            "total": 0.0, "count": 0, "first": e.date, "last": e.date,
            "categories": {},
        })
        c["total"] += e.amount
        c["count"] += 1
        c["first"] = min(c["first"], e.date)
        c["last"] = max(c["last"], e.date)
        cat = e.category or "other"
        c["categories"][cat] = c["categories"].get(cat, 0) + e.amount

    viagens = db.query(Trip).all()
    saida = []
    for c in porcidade.values():
        top = max(c["categories"].items(), key=lambda kv: kv[1]) if c["categories"] else None
        dias = (c["last"] - c["first"]).days + 1
        # A viagem certa é a do mesmo país (as datas sozinhas confundem estadias
        # longas com saltos curtos), preferindo a que apanha as datas dos gastos.
        nome_pais, iso2 = cidades_mod.pais(c["country"])
        do_pais = [t for t in viagens if (t.country or t.destination or "").strip().lower() == nome_pais.lower()]
        viagem = next(
            (t for t in do_pais
             if t.start_date and t.end_date and t.start_date <= c["last"] and t.end_date >= c["first"]),
            do_pais[0] if do_pais else None,
        )
        saida.append({
            "city": c["city"], "country": c["country"],
            "country_name": nome_pais, "flag": iso2,
            "lat": c["lat"], "lon": c["lon"],
            "total": round(c["total"], 2), "count": c["count"],
            "avg": round(c["total"] / c["count"], 2),
            "first": c["first"].isoformat(), "last": c["last"].isoformat(),
            "days": dias,
            "per_day": round(c["total"] / dias, 2) if dias > 0 else None,
            "top_category": top[0] if top else None,
            "trip": {"id": viagem.id, "destination": viagem.destination} if viagem else None,
        })

    saida.sort(key=lambda c: c["total"], reverse=True)
    return {
        "year": year,
        "days": days,
        "cities": saida,
        "total": round(sum(c["total"] for c in saida), 2),
        "unknown": {"total": round(desconhecido["total"], 2), "count": desconhecido["count"]},
    }


@router.get("/by-hour")
def spending_by_hour(days: int = Query(365, ge=30, le=1825), db: Session = Depends(get_db)):
    """A que horas do dia sai o dinheiro. Só conta despesas com hora guardada."""
    inicio = date.today() - timedelta(days=days - 1)
    rows = (
        db.query(Expense)
        .filter(Expense.date >= inicio, Expense.kind == ek.GASTO, Expense.time_of_day.isnot(None))
        .all()
    )
    faixas = {h: {"hour": h, "total": 0.0, "count": 0} for h in range(24)}
    for e in rows:
        try:
            h = int(str(e.time_of_day).split(":")[0])
        except (ValueError, IndexError):
            continue
        if 0 <= h <= 23:
            faixas[h]["total"] += e.amount
            faixas[h]["count"] += 1
    horas = [{**v, "total": round(v["total"], 2)} for v in faixas.values()]
    com_dados = [h for h in horas if h["count"]]
    pico = max(com_dados, key=lambda h: h["total"]) if com_dados else None
    total_com_hora = round(sum(h["total"] for h in horas), 2)
    sem_hora = (
        db.query(func.count(Expense.id))
        .filter(Expense.date >= inicio, Expense.kind == ek.GASTO, Expense.time_of_day.is_(None))
        .scalar()
    ) or 0
    return {
        "days": days,
        "hours": horas,
        "peak": pico,
        "with_time": sum(h["count"] for h in horas),
        "without_time": int(sem_hora),
        "total": total_com_hora,
    }


@router.get("/reimbursements")
def reembolsos_pendentes(db: Session = Depends(get_db)):
    """O que parece ser a parte dos amigos numa conta que ele pagou, e as contas
    divididas a que ainda falta dinheiro."""
    import reembolsos as rb
    from models import ReimbursementDismissed
    desde = rb.janela_de_procura(date.today())
    contas = (db.query(Expense)
              .filter(Expense.date >= desde, Expense.kind == ek.GASTO, Expense.amount > 0,
                      Expense.reimburses_id.is_(None))
              .all())
    entradas = (db.query(Expense)
                .filter(Expense.date >= desde, Expense.kind == ek.ENTRADA, Expense.amount < 0,
                        Expense.reimburses_id.is_(None))
                .all())
    devolvido = _devolvido(db)
    dispensadas = {(d.income_id, d.expense_id) for d in db.query(ReimbursementDismissed).all()}

    def mov(e):
        return {"id": e.id, "description": e.description, "amount": round(abs(e.amount), 2),
                "date": e.date, "category": e.category, "split_people": e.split_people, "my_share": e.my_share}

    sug = rb.sugestoes(entradas, contas, {k: v[0] for k, v in devolvido.items()}, dispensadas)
    divididas = (db.query(Expense)
                 .filter((Expense.split_people.isnot(None)) | (Expense.my_share.isnot(None)), Expense.amount > 0)
                 .all())
    falta = rb.por_receber(divididas, devolvido)
    return {
        "suggestions": [{"expenses": [mov(c) for c in g["expenses"]], "incomes": [mov(e) for e in g["incomes"]],
                         "share_after": g["share_after"]} for g in sug],
        "pending": [{**{k: v for k, v in p.items() if k != "expense"}, "expense": mov(p["expense"])} for p in falta],
        "total_pending": round(sum(p["missing"] for p in falta), 2),
    }


@router.post("/reimbursements/dismiss")
def dispensa_sugestao(income_id: int = Body(...), expense_id: int = Body(...), db: Session = Depends(get_db)):
    from models import ReimbursementDismissed
    if not db.query(ReimbursementDismissed).filter(ReimbursementDismissed.income_id == income_id,
                                                   ReimbursementDismissed.expense_id == expense_id).first():
        db.add(ReimbursementDismissed(income_id=income_id, expense_id=expense_id))
        db.commit()
    return {"ok": True}


@router.get("/paydays")
def dias_de_salario(db: Session = Depends(get_db)):
    """Em que dia entrou o salário de cada mês — é daí que se conta o "desde o salário"."""
    import salario
    entradas = db.query(Expense).filter(Expense.kind == ek.ENTRADA, Expense.amount < 0).all()
    correcoes = {r.month: (r.date, r.amount) for r in db.query(SalaryPayday).all()}
    primeiro = db.query(func.min(Expense.date)).scalar()
    return salario.dias_de_salario(entradas, lambda m, a: resolve_income(db, m, a),
                                   correcoes, primeiro, date.today())


@router.put("/paydays")
def corrige_dia_de_salario(dia: date = Body(..., alias="date"), amount: Optional[float] = Body(None),
                           db: Session = Depends(get_db)):
    """O salário desse mês entrou neste dia. Num mês que já tinha um, substitui-o;
    num que não tinha (o banco ainda não sincronizou), abre o ciclo. Com `amount`
    é um movimento que ele marcou como o salário, e o valor passa a ser esse."""
    month = f"{dia.year:04d}-{dia.month:02d}"
    row = db.query(SalaryPayday).filter(SalaryPayday.month == month).first()
    if row:
        row.date = dia
        row.amount = amount
    else:
        db.add(SalaryPayday(month=month, date=dia, amount=amount))
    db.commit()
    return {"month": month, "date": dia, "amount": amount}


@router.delete("/paydays/{month}")
def repoe_dia_de_salario(month: str, db: Session = Depends(get_db)):
    """Volta ao dia que a conta mostra."""
    db.query(SalaryPayday).filter(SalaryPayday.month == month).delete()
    db.commit()
    return {"ok": True}


def _categoria_out(c: ExpenseCategory) -> dict:
    return {"value": c.value, "label": c.label, "emoji": c.emoji or "🏷️"}


@router.get("/categories")
def categorias_dele(db: Session = Depends(get_db)):
    return [_categoria_out(c) for c in db.query(ExpenseCategory).order_by(ExpenseCategory.label).all()]


@router.post("/categories")
def cria_categoria(label: str = Body(...), emoji: str = Body("🏷️"), db: Session = Depends(get_db)):
    from bank_categories import CATEGORIAS, _sem_acentos
    nome = label.strip()[:40]
    if not nome:
        raise HTTPException(status_code=400, detail="falta o nome")
    existentes = {c.value: c for c in db.query(ExpenseCategory).all()}
    for c in existentes.values():
        if c.label.strip().lower() == nome.lower():
            return _categoria_out(c)
    base = re.sub(r"[^a-z0-9]+", "-", _sem_acentos(nome.lower())).strip("-") or "categoria"
    valor, n = base, 2
    while valor in CATEGORIAS or valor in existentes:
        valor, n = f"{base}-{n}", n + 1
    c = ExpenseCategory(value=valor, label=nome, emoji=(emoji or "🏷️").strip()[:8] or "🏷️")
    db.add(c)
    db.commit()
    return _categoria_out(c)


@router.delete("/categories/{value}")
def apaga_categoria(value: str, db: Session = Depends(get_db)):
    """Só se apaga uma categoria vazia: mandar os gastos dela para "Outro" sem ele
    ver era desfazer o trabalho de os arrumar."""
    from models import BudgetLimit
    c = db.query(ExpenseCategory).filter(ExpenseCategory.value == value).first()
    if not c:
        raise HTTPException(status_code=404, detail="categoria não encontrada")
    em_uso = db.query(func.count(Expense.id)).filter(Expense.category == value).scalar() or 0
    if em_uso:
        raise HTTPException(status_code=409, detail=f"{em_uso} gastos ainda estão em {c.label}; muda-os primeiro")
    db.query(MerchantRule).filter(MerchantRule.category == value).delete()
    db.query(BudgetLimit).filter(BudgetLimit.category == value).delete()
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.get("/{expense_id}", response_model=ExpenseOut)
def get_expense(expense_id: int, db: Session = Depends(get_db)):
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    return expense


@router.get("/{expense_id}/klarna")
def klarna_de_um_gasto(expense_id: int, vezes: int = Query(3, ge=2, le=36), db: Session = Depends(get_db)):
    """Como fica este gasto pago em N vezes: o que já saiu da conta e o que falta."""
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    plano = next((p for p in _planos_klarna(db, (expense, vezes)) if p["expense_id"] == expense_id), None)
    if not plano:
        raise HTTPException(status_code=400, detail="Só um gasto pode ser pago em prestações")
    return plano


@router.get("/{income_id}/reimburse-candidates")
def contas_para_descontar(income_id: int, db: Session = Depends(get_db)):
    """Para o "descontar em…" do editar: as contas das semanas antes desta entrada,
    com as que batem certo com uma divisão à frente."""
    import reembolsos as rb
    e = db.query(Expense).filter(Expense.id == income_id).first()
    if not e or (e.amount or 0) >= 0:
        raise HTTPException(status_code=404, detail="entrada não encontrada")
    contas = (db.query(Expense)
              .filter(Expense.date >= e.date - timedelta(days=60), Expense.date <= e.date + timedelta(days=3),
                      Expense.kind == ek.GASTO, Expense.amount > 0, Expense.reimburses_id.is_(None))
              .all())
    devolvido = {k: v[0] for k, v in _devolvido(db, [c.id for c in contas], excepto_entrada=e.id).items()}
    return [{"id": x["conta"].id, "description": x["conta"].description, "amount": x["conta"].amount,
             "date": x["conta"].date, "parts": x["partes"] or None, "split_people": x["conta"].split_people,
             "reimbursed": round(devolvido.get(x["conta"].id, 0.0), 2)}
            for x in rb.candidatas(e, contas, devolvido)[:40]]


@router.post("/{income_id}/reimburses", response_model=ExpenseOut)
def liga_reembolso(income_id: int, expense_id: Optional[int] = Body(None), expense_ids: list[int] = Body([]),
                   db: Session = Depends(get_db)):
    """Esta entrada é a parte de alguém nestas contas: sai das entradas e desconta-se
    nelas, repartida na proporção do que falta a cada uma."""
    import reembolsos as rb
    ids = list(dict.fromkeys(expense_ids or ([expense_id] if expense_id else [])))
    e = db.query(Expense).filter(Expense.id == income_id).first()
    if not e or not ids:
        raise HTTPException(status_code=404, detail="movimento não encontrado")
    if (e.amount or 0) >= 0 or (e.kind != ek.ENTRADA and not e.reimburses_id):
        raise HTTPException(status_code=400, detail="só dinheiro que entrou pode descontar numa conta")
    contas = {c.id: c for c in db.query(Expense).filter(Expense.id.in_(ids)).all()}
    if len(contas) != len(ids):
        raise HTTPException(status_code=404, detail="conta não encontrada")
    if any((c.amount or 0) <= 0 or c.kind != ek.GASTO or c.reimburses_id for c in contas.values()):
        raise HTTPException(status_code=400, detail="só se desconta em gastos")
    ja = _devolvido(db, ids, excepto_entrada=e.id)
    recebido = {cid: ja.get(cid, (0.0, 0))[0] for cid in ids}
    cabe = sum(contas[cid].amount - recebido[cid] for cid in ids)
    valor = -e.amount
    if valor > cabe + 0.01:
        raise HTTPException(status_code=400,
                            detail=f"€{valor:.2f} não cabem: as contas escolhidas só têm €{max(cabe, 0):.2f} por pagar")
    # Reparte-se pelo que os outros ainda devem a cada conta, quando ele o disse
    # (70€ e 5€ nos levantamentos do chá); sem isso, pelo que falta pagar.
    def peso(cid):
        esperado = rb.esperado_dos_outros(contas[cid])
        base = esperado if esperado is not None else contas[cid].amount
        return round(base - recebido[cid], 2)
    pesos = [(cid, peso(cid)) for cid in ids if peso(cid) > 0]
    if sum(p for _, p in pesos) < valor - 0.01:
        pesos = [(cid, round(contas[cid].amount - recebido[cid], 2)) for cid in ids]
    db.query(ReimbursementLink).filter(ReimbursementLink.income_id == e.id).delete()
    for cid, parte in rb.reparte(valor, [(c, f) for c, f in pesos if f > 0]).items():
        db.add(ReimbursementLink(income_id=e.id, expense_id=cid, amount=parte))
    principal = contas[ids[0]]
    e.reimburses_id = principal.id
    e.kind = ek.GASTO
    e.category = principal.category
    e.extraordinary = principal.extraordinary
    db.commit()
    db.refresh(e)
    _junta_reembolsos(db, [e])
    return e


@router.delete("/{income_id}/reimburses", response_model=ExpenseOut)
def desliga_reembolso(income_id: int, db: Session = Depends(get_db)):
    e = db.query(Expense).filter(Expense.id == income_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="movimento não encontrado")
    _desliga(db, e)
    db.commit()
    db.refresh(e)
    _junta_reembolsos(db, [e])
    return e


def _desliga(db: Session, e: Expense) -> None:
    db.query(ReimbursementLink).filter(ReimbursementLink.income_id == e.id).delete()
    e.reimburses_id = None
    e.kind = ek.ENTRADA
    e.extraordinary = False


@router.post("/", response_model=ExpenseOut)
def create_expense(data: ExpenseCreate, db: Session = Depends(get_db)):
    campos = data.model_dump()
    tipo = campos.pop("kind", None)
    expense = Expense(**campos)
    # Sem indicação em contrário, é a app que decide se isto é um gasto, uma
    # entrada ou dinheiro a mudar de conta.
    expense.kind = tipo if tipo in ek.TIPOS else ek.classifica(
        expense.description or "", expense.category or "", expense.amount or 0
    )
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


@router.post("/scan-receipt")
async def scan_receipt(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Lê um recibo (foto ou PDF) e devolve a despesa já preenchida, sem gravar.
    O ficheiro fica guardado para poder ser anexado quando a despesa for criada."""
    ext = os.path.splitext(file.filename or "img.png")[1].lower()
    if ext not in {".png", ".jpg", ".jpeg", ".heic", ".webp", ".pdf"}:
        raise HTTPException(status_code=400, detail="Só imagens ou PDF")

    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Ficheiro demasiado grande (máx 15MB)")

    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(content)

    texto = receipt_ocr.ocr(filepath)
    if not texto.strip():
        raise HTTPException(status_code=422, detail="Não consegui ler texto nesta imagem")

    dados = await receipt_ocr.interpreta(texto)
    descricao = dados["merchant"]
    if dados.get("items"):
        descricao = f"{descricao} — {', '.join(dados['items'][:3])}"[:120]

    return {
        "receipt_path": filepath,
        "text": texto[:2000],
        "suggestion": {
            "description": descricao,
            "amount": dados["amount"],
            "category": dados["category"],
            "date": dados["date"],
            "time_of_day": _hora_do_texto(texto),
            "merchant_city": dados.get("city"),
            "notes": ", ".join(dados.get("items") or [])[:300],
        },
        "merchant": dados["merchant"],
        "items": dados.get("items") or [],
        "currency": dados.get("currency", "EUR"),
        "confidence": dados.get("confidence"),
        "source": dados.get("source"),
    }


@router.post("/{expense_id}/attach-receipt", response_model=ExpenseOut)
def attach_receipt(expense_id: int, path: str = Body(..., embed=True), db: Session = Depends(get_db)):
    """Liga à despesa um recibo já enviado pelo scan (evita subir o ficheiro duas vezes)."""
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(UPLOAD_DIR)) or not os.path.exists(real):
        raise HTTPException(status_code=400, detail="Recibo inválido")
    expense.receipt_image = os.path.relpath(real, os.path.realpath(os.getcwd()))
    db.commit()
    db.refresh(expense)
    return expense


@router.put("/{expense_id}", response_model=ExpenseOut)
def update_expense(expense_id: int, data: ExpenseUpdate, db: Session = Depends(get_db)):
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    categoria_antes = expense.category
    campos = data.model_dump(exclude_unset=True)
    aplicar_aos_iguais = campos.pop("apply_to_similar", False)
    for key, value in campos.items():
        if key == "kind" and value not in ek.TIPOS:
            continue                      # tipo inválido não estraga o que lá está
        setattr(expense, key, value)

    # Corrigir a categoria de uma despesa do banco pode ensinar a app — a mesma
    # loja deixa de precisar de correcção, agora e nas que já lá estavam — mas só
    # quando ele o pede: um pagamento à associação de estudantes pode ser saúde
    # desta vez e noite da próxima.
    arrumadas = 0
    if (aplicar_aos_iguais and expense.bank_tx_id and expense.category
            and expense.category != categoria_antes):
        from bank_categories import aprende, arruma_iguais, chave
        aprende(expense.description, expense.category, db, fonte="manual")
        k = chave(expense.description)
        if k:
            arrumadas = arruma_iguais(db, k, expense.category, excepto=expense.id)
    db.commit()
    db.refresh(expense)
    if arrumadas:
        logger.info("categoria aprendida: %s despesas iguais arrumadas", arrumadas)
    _acompanha_conta(db, expense)
    db.commit()
    _junta_reembolsos(db, [expense])
    return expense


@router.delete("/{expense_id}")
def delete_expense(expense_id: int, db: Session = Depends(get_db)):
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    # apagar uma despesa do banco tem de ficar apagada: senão voltava amanhã
    if expense.bank_tx_id:
        from models import BankIgnoredTx
        if not db.query(BankIgnoredTx).filter(BankIgnoredTx.tx_id == expense.bank_tx_id).first():
            db.add(BankIgnoredTx(tx_id=expense.bank_tx_id, description=expense.description[:120]))
    # o dinheiro dos amigos não desaparece com a conta: volta a ser uma entrada
    # (inteiro, mesmo que descontasse também noutra — repartido já não batia certo)
    ligadas = {l.income_id for l in db.query(ReimbursementLink).filter(ReimbursementLink.expense_id == expense.id).all()}
    for r in db.query(Expense).filter(Expense.id.in_(ligadas | {-1})).all():
        _desliga(db, r)
    if expense.reimburses_id:
        db.query(ReimbursementLink).filter(ReimbursementLink.income_id == expense.id).delete()
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

    # os reembolsos seguem a categoria da conta, não a do nome de quem pagou
    expenses = q.filter(Expense.reimburses_id.is_(None)).all()
    if not expenses:
        return {"updated": 0}

    items = []
    for i, exp in enumerate(expenses):
        items.append({
            "idx": i,
            "description": exp.description,
            "notes": exp.notes or "",
            "amount": exp.amount,
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
            _acompanha_conta(db, exp)
            updated += 1

    db.commit()
    return {"updated": updated, "total": len(expenses)}


# ── Revolut CSV Import ───────────────────────────────────────────

_HORA = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")


def _hora_do_texto(texto: str) -> Optional[str]:
    """Hora \"HH:MM\" a partir de um timestamp do extracto. Sem hora, devolve None."""
    m = _HORA.search(texto or "")
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


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

            hora = _hora_do_texto(date_str)
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
                "time_of_day": hora,
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
            time_of_day=item.get("time_of_day"),
            notes="Importado do Revolut",
            kind=ek.classifica(item["description"], categories.get(item["idx"], "other"), item["amount"]),
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


# Column header of the account-transactions table (Money out | Money in | Balance)
HEADER_RE = re.compile(r"Money out\s+Money in\s+Balance")

# Movements that are NOT spending: money moving between the user's own accounts
# (top-ups, currency exchanges) or in/out of investment platforms. Matched against
# the transaction's description + detail lines (lowercased). Skipped in BOTH
# directions (money in and money out).
INTERNAL_KEYWORDS = [
    "top-up",                # Apple Pay / Open banking top-ups (loading own money into Revolut)
    "leonardo miguel",       # transfers to/from the user's own bank account
    "exchanged to",          # internal currency exchange
    "trading 212",           # investment platform (money moving in/out of investments)
    "finst",                 # Finst / Stichting Finst Custody brokerage
]


def _classify_column(pos: int, hp: dict) -> str:
    """Which table column a value at char-position `pos` belongs to, using the
    header positions. Boundaries are the midpoints between column starts."""
    b_out_in = (hp["out"] + hp["in"]) / 2
    b_in_bal = (hp["in"] + hp["bal"]) / 2
    if pos < b_out_in:
        return "out"
    if pos < b_in_bal:
        return "in"
    return "bal"


def _parse_revolut_pdf(text: str) -> list[dict]:
    """Parse Revolut PDF text into transaction dicts.

    Money out vs money in is decided by the *column* the value sits under
    (pdftotext -layout keeps columns aligned), not by guessing from the
    description. Money-in that is a real third-party refund/return becomes a
    negative-amount expense (nets against spending); internal movements
    (own-account top-ups, currency exchanges, investment platforms) are dropped.
    """
    lines = text.split("\n")
    transactions = []

    date_re = re.compile(
        r"^\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),\s+(\d{4})\s+"
    )
    money_re = re.compile(r"€([\d,]+\.\d{2})")
    orig_amount_re = re.compile(r"([\d,.]+)\s+([A-Z]{3})\s*$")
    to_re = re.compile(r"^To:\s+(.+)")
    ref_re = re.compile(r"^Reference:\s+(.+)")

    in_account_section = False
    hp = None  # current header column positions {"out","in","bal"}

    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        if "Account transactions from" in line:
            in_account_section = True
            i += 1
            continue
        if "Pending from" in line or "Reverted from" in line:
            in_account_section = False
            i += 1
            continue
        if HEADER_RE.search(raw):
            try:
                hp = {"out": raw.index("Money out"), "in": raw.index("Money in"), "bal": raw.index("Balance")}
            except ValueError:
                pass
            i += 1
            continue

        if not in_account_section or hp is None:
            i += 1
            continue

        m = date_re.match(raw)
        if not m:
            i += 1
            continue

        month_str, day_str, year_str = m.group(1), m.group(2), m.group(3)
        tx_date = date(int(year_str), MONTH_MAP[month_str], int(day_str))

        # € values with their absolute char positions → assign to columns
        cols: dict[str, float] = {}
        for mm in money_re.finditer(raw):
            col = _classify_column(mm.start(), hp)
            cols.setdefault(col, float(mm.group(1).replace(",", "")))
        money_out = cols.get("out")
        money_in = cols.get("in")

        desc_part = money_re.sub("", raw[m.end():]).strip()
        desc_part = re.sub(r"\s{2,}", " ", desc_part).strip()

        # Collect detail lines (merchant, reference, original amount)
        original_amount = None
        original_currency = None
        merchant_city = None
        merchant_country = None
        reference = None
        detail_blob = []

        j = i + 1
        while j < len(lines):
            draw = lines[j]
            detail = draw.strip()
            if not detail or date_re.match(draw):
                break
            if "Account transactions from" in detail or "Pending from" in detail or "Reverted from" in detail:
                break
            if HEADER_RE.search(draw) or detail.startswith("Date ") or detail.startswith("Start date "):
                break
            if any(kw in detail for kw in ["Revolut Bank UAB, ", "Page ", "Report lost",
                                              "© 20", "EUR Statement", "Generated on",
                                              "Get help", "Scan the QR"]):
                j += 1
                continue

            detail_blob.append(detail)

            rate_m = orig_amount_re.search(detail)
            if "Revolut Rate" in detail and rate_m:
                original_amount = float(rate_m.group(1).replace(",", ""))
                original_currency = rate_m.group(2)
            elif rate_m and detail[0].isdigit() and not detail.startswith("To:"):
                original_amount = float(rate_m.group(1).replace(",", ""))
                original_currency = rate_m.group(2)

            to_m = to_re.match(detail)
            if to_m:
                to_parts = [p.strip() for p in to_m.group(1).split(",") if p.strip()]
                if len(to_parts) >= 3:
                    merchant_city = to_parts[-2]
                    merchant_country = to_parts[-1]
                    if merchant_country.isdigit():
                        merchant_country = None
                    if merchant_city and merchant_city.isdigit():
                        merchant_city = to_parts[-3] if len(to_parts) >= 4 else None
                elif len(to_parts) == 2:
                    merchant_city = to_parts[-1]

            ref_m = ref_re.match(detail)
            if ref_m:
                reference = ref_m.group(1)

            j += 1

        # Drop internal movements (own accounts / exchanges / investments) both ways
        blob = (desc_part + " " + " ".join(detail_blob)).lower()
        if any(kw in blob for kw in INTERNAL_KEYWORDS):
            i = j
            continue

        # Decide amount & kind from the column
        if money_out is not None and money_in is None:
            amt = money_out
            kind = "expense"
        elif money_in is not None and money_out is None:
            amt = -money_in          # third-party refund/return → nets against spending
            kind = "refund"
        elif money_out is not None and money_in is not None:
            amt = money_out - money_in
            kind = "expense" if amt >= 0 else "refund"
        else:
            i = j
            continue

        notes_parts = []
        if kind == "refund":
            notes_parts.append("Reembolso/entrada")
        if reference:
            notes_parts.append(reference)
        if original_currency and original_currency != "EUR":
            notes_parts.append(f"{original_amount} {original_currency}")
        if not original_currency:
            original_currency = "EUR"
            original_amount = abs(amt)

        transactions.append({
            "description": desc_part,
            "amount": round(amt, 2),
            "date": tx_date,
            "original_amount": original_amount,
            "original_currency": original_currency,
            "merchant_city": merchant_city,
            "merchant_country": merchant_country,
            "notes": " · ".join(notes_parts) if notes_parts else "",
            "kind": kind,
        })
        i = j

    return transactions


@router.post("/import/pdf")
async def import_revolut_pdf(
    file: UploadFile = File(...),
    clean: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Import a Revolut monthly statement PDF.

    With `clean=true`, before importing, deletes any expense in the PDF's date range
    that looks like a wrongly-categorized deposit (Apple Pay deposit, Top-up,
    Transfer from …) so reimporting doesn't leave stale junk behind.

    `date_from` / `date_to` (ISO `YYYY-MM-DD`, inclusive) limit which transactions
    are imported — useful for a multi-month statement when some months are already
    curated in the DB and shouldn't be touched (avoids re-importing them under
    slightly different merchant names / dates).
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

    # Resolve pdftotext even when launched via LaunchAgent (no Homebrew in PATH)
    pdftotext_bin = shutil.which("pdftotext") or next(
        (p for p in ("/opt/homebrew/bin/pdftotext", "/usr/local/bin/pdftotext", "/usr/bin/pdftotext")
         if os.path.exists(p)),
        None,
    )
    if not pdftotext_bin:
        os.unlink(tmp_path)
        raise HTTPException(status_code=500, detail="pdftotext not installed (brew install poppler)")

    try:
        result = subprocess.run(
            [pdftotext_bin, "-layout", tmp_path, "-"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"pdftotext failed: {result.stderr}")
        pdf_text = result.stdout
    finally:
        os.unlink(tmp_path)

    transactions = _parse_revolut_pdf(pdf_text)

    if date_from:
        d0 = date.fromisoformat(date_from)
        transactions = [t for t in transactions if t["date"] >= d0]
    if date_to:
        d1 = date.fromisoformat(date_to)
        transactions = [t for t in transactions if t["date"] <= d1]

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
                "amount": tx.get("amount"),
                "notes": tx.get("notes", ""),
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
            kind=ek.classifica(tx["description"], categories.get(i, "other"), tx["amount"]),
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
