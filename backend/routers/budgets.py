from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
import calendar
from datetime import date, timedelta
from typing import Optional

from database import get_db
from models import BudgetLimit, Subscription, Expense, SalaryBucket, MonthlyIncome
import expense_kind as ek
from schemas import (
    BudgetLimitCreate, BudgetLimitUpdate, BudgetLimitOut,
    SubscriptionCreate, SubscriptionUpdate, SubscriptionOut,
    SalaryBucketCreate, SalaryBucketUpdate, SalaryBucketOut,
)

router = APIRouter(prefix="/api/budgets", tags=["Budgets & Subscriptions"])

DEFAULT_INCOME = 1040.98


def resolve_income(db: Session, month: int, year: int) -> float:
    """Rendimento de um mês: valor guardado desse mês, senão o último salário
    conhecido até essa data, senão o mais antigo registado, senão o default.
    Evita mostrar um default desactualizado em meses sem registo."""
    rows = db.query(MonthlyIncome).order_by(MonthlyIncome.year, MonthlyIncome.month).all()
    if not rows:
        return DEFAULT_INCOME
    target = (year, month)
    best = None
    for r in rows:
        if (r.year, r.month) <= target:
            best = r
    return (best or rows[0]).amount

# Grupos por defeito na 1ª utilização (batem com o modelo 50/10/20 → 20% poupança)
DEFAULT_BUCKETS = [
    {"name": "Despesas", "percentage": 50, "kind": "spend", "color": "#EF4444", "sort_order": 0,
     "categories": ["food", "groceries", "bills", "health", "transport", "subscriptions", "travel"]},
    {"name": "Pessoal", "percentage": 10, "kind": "spend", "color": "#8B5CF6", "sort_order": 1,
     "categories": ["entertainment", "nightlife", "shopping", "other"]},
    {"name": "Investir", "percentage": 20, "kind": "save", "color": "#10B981", "sort_order": 2,
     "categories": ["invest"]},
]


def _split_cats(csv: str) -> list[str]:
    return [c.strip() for c in (csv or "").split(",") if c.strip()]


def _bucket_out(b: SalaryBucket) -> dict:
    return {
        "id": b.id, "name": b.name, "percentage": b.percentage,
        "categories": _split_cats(b.categories), "kind": b.kind or "spend",
        "color": b.color, "sort_order": b.sort_order or 0,
    }


def _ensure_buckets(db: Session) -> list[SalaryBucket]:
    buckets = db.query(SalaryBucket).order_by(SalaryBucket.sort_order, SalaryBucket.id).all()
    if buckets:
        return buckets
    for d in DEFAULT_BUCKETS:
        db.add(SalaryBucket(
            name=d["name"], percentage=d["percentage"], kind=d["kind"],
            color=d["color"], sort_order=d["sort_order"],
            categories=",".join(d["categories"]),
        ))
    db.commit()
    return db.query(SalaryBucket).order_by(SalaryBucket.sort_order, SalaryBucket.id).all()


# ── Budget Limits ────────────────────────────────────────────────

@router.get("/limits", response_model=list[BudgetLimitOut])
def list_limits(db: Session = Depends(get_db)):
    return db.query(BudgetLimit).order_by(BudgetLimit.category).all()


@router.post("/limits", response_model=BudgetLimitOut)
def create_limit(data: BudgetLimitCreate, db: Session = Depends(get_db)):
    existing = db.query(BudgetLimit).filter(BudgetLimit.category == data.category).first()
    if existing:
        existing.monthly_limit = data.monthly_limit
        existing.color = data.color
        db.commit()
        db.refresh(existing)
        return existing
    limit = BudgetLimit(**data.model_dump())
    db.add(limit)
    db.commit()
    db.refresh(limit)
    return limit


@router.put("/limits/{limit_id}", response_model=BudgetLimitOut)
def update_limit(limit_id: int, data: BudgetLimitUpdate, db: Session = Depends(get_db)):
    limit = db.query(BudgetLimit).filter(BudgetLimit.id == limit_id).first()
    if not limit:
        raise HTTPException(404, "Budget limit not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(limit, k, v)
    db.commit()
    db.refresh(limit)
    return limit


@router.delete("/limits/{limit_id}")
def delete_limit(limit_id: int, db: Session = Depends(get_db)):
    limit = db.query(BudgetLimit).filter(BudgetLimit.id == limit_id).first()
    if not limit:
        raise HTTPException(404, "Budget limit not found")
    db.delete(limit)
    db.commit()
    return {"ok": True}


@router.get("/limits/suggestions")
def limit_suggestions(db: Session = Depends(get_db)):
    """Sugere um limite por categoria a partir da média dos últimos 3 meses completos.
    Sem isto, definir orçamentos exige adivinhar números."""
    from sqlalchemy import extract

    today = date.today()
    # 3 meses completos antes do actual
    meses = []
    m, y = today.month, today.year
    for _ in range(3):
        m -= 1
        if m == 0:
            m, y = 12, y - 1
        meses.append((m, y))

    existentes = {l.category for l in db.query(BudgetLimit).all()}
    totais: dict[str, float] = {}
    for mm, yy in meses:
        rows = (
            db.query(Expense.category, func.sum(Expense.amount))
            .filter(extract("month", Expense.date) == mm, extract("year", Expense.date) == yy)
            .filter(Expense.kind == ek.GASTO, Expense.extraordinary.is_(False))
            .group_by(Expense.category)
            .all()
        )
        for cat, total in rows:
            totais[cat or "other"] = totais.get(cat or "other", 0) + float(total or 0)

    out = []
    for cat, total in totais.items():
        media = total / len(meses)
        if media < 5:
            continue
        sugestao = max(5, round(media / 5) * 5)   # múltiplos de 5€
        out.append({
            "category": cat,
            "avg_3m": round(media, 2),
            "suggested": sugestao,
            "has_limit": cat in existentes,
        })
    out.sort(key=lambda r: r["avg_3m"], reverse=True)
    return out


@router.get("/status")
def budget_status(
    month: Optional[int] = Query(None),
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Get current month's spending vs budget limits."""
    today = date.today()
    m = month or today.month
    y = year or today.year

    limits = db.query(BudgetLimit).all()
    if not limits:
        return {"categories": [], "total_budget": 0, "total_spent": 0}

    # Get all expenses for the month
    from sqlalchemy import extract
    expenses = (
        db.query(Expense)
        .filter(extract("month", Expense.date) == m, extract("year", Expense.date) == y,
                Expense.kind == ek.GASTO, Expense.extraordinary.is_(False))
        .all()
    )

    # Sum by category — só saídas (gasto bruto); reembolsos não abatem ao limite
    spent_by_cat: dict[str, float] = {}
    for e in expenses:
        if e.amount <= 0:
            continue
        cat = e.category or "other"
        spent_by_cat[cat] = spent_by_cat.get(cat, 0) + e.amount

    categories = []
    total_budget = 0
    total_spent = 0
    for limit in limits:
        spent = round(spent_by_cat.get(limit.category, 0), 2)
        pct = round(spent / limit.monthly_limit * 100, 1) if limit.monthly_limit > 0 else 0
        total_budget += limit.monthly_limit
        total_spent += spent
        categories.append({
            "category": limit.category,
            "limit": limit.monthly_limit,
            "spent": spent,
            "remaining": round(limit.monthly_limit - spent, 2),
            "percentage": pct,
            "color": limit.color,
            "status": "danger" if pct >= 100 else "warning" if pct >= 80 else "ok",
        })

    return {
        "month": m,
        "year": y,
        "categories": sorted(categories, key=lambda x: x["percentage"], reverse=True),
        "total_budget": round(total_budget, 2),
        "total_spent": round(total_spent, 2),
        "total_remaining": round(total_budget - total_spent, 2),
    }


# ── Salary Buckets (plano do salário por %) ──────────────────────

@router.get("/buckets", response_model=list[SalaryBucketOut])
def list_buckets(db: Session = Depends(get_db)):
    return [_bucket_out(b) for b in _ensure_buckets(db)]


@router.post("/buckets", response_model=SalaryBucketOut)
def create_bucket(data: SalaryBucketCreate, db: Session = Depends(get_db)):
    b = SalaryBucket(
        name=data.name, percentage=data.percentage, kind=data.kind,
        color=data.color, sort_order=data.sort_order,
        categories=",".join(data.categories),
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return _bucket_out(b)


@router.put("/buckets/{bucket_id}", response_model=SalaryBucketOut)
def update_bucket(bucket_id: int, data: SalaryBucketUpdate, db: Session = Depends(get_db)):
    b = db.query(SalaryBucket).filter(SalaryBucket.id == bucket_id).first()
    if not b:
        raise HTTPException(404, "Salary bucket not found")
    payload = data.model_dump(exclude_unset=True)
    if "categories" in payload:
        b.categories = ",".join(payload.pop("categories") or [])
    for k, v in payload.items():
        setattr(b, k, v)
    db.commit()
    db.refresh(b)
    return _bucket_out(b)


@router.delete("/buckets/{bucket_id}")
def delete_bucket(bucket_id: int, db: Session = Depends(get_db)):
    b = db.query(SalaryBucket).filter(SalaryBucket.id == bucket_id).first()
    if not b:
        raise HTTPException(404, "Salary bucket not found")
    db.delete(b)
    db.commit()
    return {"ok": True}


def _gasto_por_categoria(db: Session, inicio: date, fim: date) -> dict[str, float]:
    """Gasto por categoria entre duas datas, como os cartões dos Gastos o contam:
    só `spend`, sem o extraordinário, e com a parte dos amigos a descontar na
    conta (é gasto negativo da mesma categoria). Nenhuma categoria fica abaixo
    de zero — um reembolso do mês seguinte não faz um envelope crescer."""
    rows = (
        db.query(Expense.category, func.sum(Expense.amount))
        .filter(Expense.date >= inicio, Expense.date <= fim,
                Expense.kind == ek.GASTO, Expense.extraordinary.is_(False))
        .group_by(Expense.category)
        .all()
    )
    return {(c or "other"): max(0.0, float(t or 0)) for c, t in rows}


@router.get("/salary-plan")
def salary_plan(
    month: Optional[int] = Query(None),
    year: Optional[int] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    salary: Optional[float] = Query(None),
    db: Session = Depends(get_db),
):
    """Alvo (% do salário) vs gasto real por grupo, no mês — ou, com
    start_date/end_date, no período de salário a salário. Sobra = poupança."""
    today = date.today()
    m = month or today.month
    y = year or today.year
    if start_date:
        inicio, fim = start_date, end_date or today
    else:
        inicio = date(y, m, 1)
        fim = date(y, m, calendar.monthrange(y, m)[1])

    if salary is None:
        salary = resolve_income(db, inicio.month, inicio.year)

    spent_by_cat = {c: v for c, v in _gasto_por_categoria(db, inicio, fim).items() if v > 0}
    total_spent = round(sum(spent_by_cat.values()), 2)

    buckets = _ensure_buckets(db)
    groups = []
    allocated_pct = 0.0
    covered: set[str] = set()
    for b in buckets:
        cats = _split_cats(b.categories)
        covered.update(cats)
        target = round(salary * b.percentage / 100, 2)
        spent = round(sum(spent_by_cat.get(c, 0) for c in cats), 2)
        allocated_pct += b.percentage
        pct_used = round(spent / target * 100, 1) if target > 0 else 0
        kind = b.kind or "spend"
        if kind == "save":
            status = "met" if spent >= target and target > 0 else "under"
        else:
            status = "over" if pct_used > 100 else "warning" if pct_used >= 80 else "ok"
        groups.append({
            "id": b.id, "name": b.name, "percentage": b.percentage,
            "categories": cats, "kind": kind, "color": b.color,
            "target": target, "spent": spent,
            "remaining": round(target - spent, 2),
            "pct_used": pct_used, "status": status,
        })

    savings_pct = round(max(0.0, 100 - allocated_pct), 1)
    savings_target = round(salary * savings_pct / 100, 2)
    actual_saved = round(salary - total_spent, 2)

    unbudgeted = {c: round(v, 2) for c, v in spent_by_cat.items() if c not in covered and v > 0}

    return {
        "month": m, "year": y, "start_date": str(inicio), "end_date": str(fim),
        "salary": round(salary, 2),
        "groups": groups,
        "allocated_pct": round(allocated_pct, 1),
        "over_allocated": allocated_pct > 100,
        "savings_pct": savings_pct,
        "savings_target": savings_target,
        "total_target": round(salary * min(allocated_pct, 100) / 100, 2),
        "total_spent": total_spent,
        "actual_saved": actual_saved,
        "unbudgeted_spent": round(sum(unbudgeted.values()), 2),
        "unbudgeted": [{"category": c, "spent": v} for c, v in sorted(unbudgeted.items(), key=lambda x: -x[1])],
    }


# ── Subscriptions ────────────────────────────────────────────────

@router.get("/subscriptions", response_model=list[SubscriptionOut])
def list_subscriptions(active_only: bool = True, db: Session = Depends(get_db)):
    q = db.query(Subscription)
    if active_only:
        q = q.filter(Subscription.active == True)
    return q.order_by(Subscription.name).all()


@router.post("/subscriptions", response_model=SubscriptionOut)
def create_subscription(data: SubscriptionCreate, db: Session = Depends(get_db)):
    sub = Subscription(**data.model_dump())
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@router.put("/subscriptions/{sub_id}", response_model=SubscriptionOut)
def update_subscription(sub_id: int, data: SubscriptionUpdate, db: Session = Depends(get_db)):
    sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
    if not sub:
        raise HTTPException(404, "Subscription not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(sub, k, v)
    db.commit()
    db.refresh(sub)
    return sub


@router.delete("/subscriptions/{sub_id}")
def delete_subscription(sub_id: int, db: Session = Depends(get_db)):
    sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
    if not sub:
        raise HTTPException(404, "Subscription not found")
    db.delete(sub)
    db.commit()
    return {"ok": True}


@router.get("/subscriptions/summary")
def subscriptions_summary(db: Session = Depends(get_db)):
    """Get total monthly cost of active subscriptions."""
    subs = db.query(Subscription).filter(Subscription.active == True).all()
    monthly_total = 0.0
    for s in subs:
        if s.billing_cycle == "monthly":
            monthly_total += s.amount
        elif s.billing_cycle == "yearly":
            monthly_total += s.amount / 12
        elif s.billing_cycle == "weekly":
            monthly_total += s.amount * 4.33
    return {
        "count": len(subs),
        "monthly_total": round(monthly_total, 2),
        "yearly_total": round(monthly_total * 12, 2),
        "subscriptions": [SubscriptionOut.model_validate(s).model_dump() for s in subs],
    }


# ── Previsão de fim do mês ───────────────────────────────────────

@router.get("/forecast")
def month_forecast(
    month: Optional[int] = Query(None),
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Projecta o gasto do mês a partir do ritmo até agora e compara com o plano
    do salário. Serve para dar o aviso a meio do mês, não no fim."""
    from calendar import monthrange
    from sqlalchemy import extract

    today = date.today()
    m = month or today.month
    y = year or today.year
    dias_no_mes = monthrange(y, m)[1]
    hoje_no_mes = (m == today.month and y == today.year)
    dias_passados = today.day if hoje_no_mes else dias_no_mes

    despesas = (
        db.query(Expense)
        .filter(extract("month", Expense.date) == m, extract("year", Expense.date) == y,
                Expense.kind == ek.GASTO, Expense.extraordinary.is_(False))
        .all()
    )
    gasto = round(sum(e.amount for e in despesas if e.amount > 0), 2)
    entradas = round(sum(-e.amount for e in despesas if e.amount < 0), 2)
    # O que saiu mesmo: comprar 300€ na Vinted e receber 300€ de reembolso não é
    # ter gasto 300€. A previsão feita sobre o valor bruto dizia que ia estourar
    # o mês por causa de compras que foram devolvidas.
    gasto_liquido = round(gasto - entradas, 2)

    ritmo = max(0.0, gasto_liquido) / dias_passados if dias_passados else 0
    projeccao = round(ritmo * dias_no_mes, 2)

    por_cat: dict[str, float] = {}
    for e in despesas:
        c = e.category or "other"
        por_cat[c] = por_cat.get(c, 0) + e.amount      # reembolsos abatem na categoria
    por_cat = {c: v for c, v in por_cat.items() if v > 0.005}

    plano = salary_plan(m, y, start_date=None, end_date=None, salary=None, db=db)
    salario = plano.get("salary") or 0
    alvo_gasto = round(sum(g["target"] for g in plano.get("groups", []) if g.get("kind") == "spend"), 2)

    limites = {l.category: l.monthly_limit for l in db.query(BudgetLimit).all()}
    categorias = []
    for cat, valor in sorted(por_cat.items(), key=lambda kv: kv[1], reverse=True):
        proj = round(valor / dias_passados * dias_no_mes, 2) if dias_passados else valor
        limite = limites.get(cat)
        categorias.append({
            "category": cat,
            "spent": round(valor, 2),
            "projected": proj,
            "limit": limite,
            "over_limit": bool(limite and proj > limite),
        })

    if alvo_gasto > 0:
        veredicto = "acima do plano" if projeccao > alvo_gasto * 1.05 else "dentro do plano" if projeccao <= alvo_gasto else "no limite"
    elif salario > 0:
        veredicto = "acima do salário" if projeccao > salario else "dentro do salário"
    else:
        veredicto = "sem plano definido"

    return {
        "month": m,
        "year": y,
        "days_elapsed": dias_passados,
        "days_in_month": dias_no_mes,
        "spent": gasto,
        "net_spent": gasto_liquido,
        "income_extra": entradas,
        "daily_rate": round(ritmo, 2),
        "projected": projeccao,
        "salary": salario,
        "plan_target": alvo_gasto,
        "verdict": veredicto,
        "over_by": round(projeccao - alvo_gasto, 2) if alvo_gasto else None,
        "categories": categorias[:8],
    }


# ── Subscrições escondidas nos gastos ────────────────────────────

def _normaliza(desc: str) -> str:
    """Descrição sem números, datas nem ruído — para agrupar o mesmo comerciante."""
    import re
    txt = (desc or "").lower()
    txt = re.sub(r"\d+", " ", txt)
    txt = re.sub(r"[^a-zà-ÿ ]", " ", txt)
    txt = re.sub(r"\b(payment|pagamento|compra|to|de|da|do|no|na|em)\b", " ", txt)
    return " ".join(txt.split())[:40]


@router.get("/subscriptions/detect")
def detect_subscriptions(months: int = Query(6, ge=3, le=24), db: Session = Depends(get_db)):
    """Encontra pagamentos que se repetem mês a mês e ainda não estão registados
    como subscrição — o extracto tem sempre mais do que a gente se lembra."""
    from statistics import median

    inicio = date.today() - timedelta(days=months * 31)
    despesas = (
        db.query(Expense)
        .filter(Expense.date >= inicio, Expense.kind == ek.GASTO, Expense.extraordinary.is_(False))
        .order_by(Expense.date)
        .all()
    )

    grupos: dict[str, list] = {}
    for e in despesas:
        chave = _normaliza(e.description)
        if len(chave) < 3:
            continue
        grupos.setdefault(chave, []).append(e)

    ja_registadas = {(_normaliza(s.name)) for s in db.query(Subscription).all()}

    candidatos = []
    for chave, lista in grupos.items():
        # Uma subscrição repete o MESMO valor em meses diferentes. Lojas repetem o
        # nome mas nunca o valor — é isso que separa umas das outras.
        from collections import Counter
        contagem = Counter(round(e.amount, 2) for e in lista)
        valor, _ = contagem.most_common(1)[0]
        iguais = [e for e in lista if abs(e.amount - valor) <= max(0.02, valor * 0.02)]
        meses = sorted({(e.date.year, e.date.month) for e in iguais})
        if len(meses) < 3 or valor <= 0:
            continue
        if chave in ja_registadas or any(chave in r or r in chave for r in ja_registadas):
            continue
        ultima = max(e.date for e in iguais)
        candidatos.append({
            "key": chave,
            "name": max((e.description for e in iguais), key=len)[:60],
            "amount": round(valor, 2),
            "months": len(meses),
            "occurrences": len(iguais),
            "last_date": str(ultima),
            "category": iguais[-1].category or "subscriptions",
            "yearly": round(valor * 12, 2),
        })

    candidatos.sort(key=lambda c: (-c["months"], -c["amount"]))
    return candidatos[:10]


# ── Envelopes semanais ───────────────────────────────────────────
# O limite mensal só dá aviso quando já não há nada a fazer. Divide-se o mês em
# semanas: cada categoria tem um envelope semanal e o que sobra (ou falta) das
# semanas anteriores do mesmo mês é transportado para a semana actual.

def _dias_no_mes(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def _envelope_dias(limite_mensal: float, dias: list[date]) -> float:
    """Fatia do limite mensal que cabe nestes dias (aguenta semanas a cavalo de dois meses)."""
    return sum(limite_mensal / _dias_no_mes(d) for d in dias)


def _semana(offset: int) -> tuple[date, date]:
    hoje = date.today()
    inicio = hoje - timedelta(days=hoje.weekday()) + timedelta(weeks=offset)
    return inicio, inicio + timedelta(days=6)


def _referencias(db: Session) -> list[dict]:
    """Tecto por categoria. Sem tecto definido, usa a média dos 3 meses completos —
    assim os envelopes funcionam sem ser preciso configurar nada primeiro."""
    limites = db.query(BudgetLimit).all()
    refs = [
        {"category": l.category, "monthly": float(l.monthly_limit), "color": l.color, "source": "limite"}
        for l in limites if l.monthly_limit > 0
    ]
    tem = {r["category"] for r in refs}
    for s in limit_suggestions(db):
        if s["category"] in tem or s["avg_3m"] < 20:
            continue
        refs.append({
            "category": s["category"], "monthly": float(s["avg_3m"]),
            "color": None, "source": "media",
        })
    refs.sort(key=lambda r: r["monthly"], reverse=True)
    return refs[:8]


@router.get("/envelopes")
def weekly_envelopes(week_offset: int = Query(0), db: Session = Depends(get_db)):
    limites = _referencias(db)
    inicio, fim = _semana(week_offset)
    dias_semana = [inicio + timedelta(days=i) for i in range(7)]
    hoje = date.today()

    if not limites:
        return {
            "week_start": inicio.isoformat(), "week_end": fim.isoformat(),
            "categories": [], "total_envelope": 0, "total_spent": 0, "days_left": 0,
        }

    gastos = db.query(Expense).filter(
        Expense.date >= inicio, Expense.date <= fim, Expense.kind == ek.GASTO, Expense.extraordinary.is_(False)
    ).all()
    gasto_semana: dict[str, float] = {}
    for e in gastos:
        c = e.category or "other"
        gasto_semana[c] = gasto_semana.get(c, 0) + e.amount     # reembolsos abatem
    gasto_semana = {c: max(0.0, v) for c, v in gasto_semana.items()}

    # Transporte semana a semana, dentro do mês da segunda-feira. Limitado a um
    # envelope em cada sentido: sobrar não dá licença para gastar o mês todo numa
    # semana, e um estouro grande não apaga a categoria até ao fim do mês.
    mes_inicio = inicio.replace(day=1)
    semanas_antes: list[list[date]] = []
    d = mes_inicio
    atual: list[date] = []
    while d < inicio:
        if atual and d.weekday() == 0:
            semanas_antes.append(atual)
            atual = []
        atual.append(d)
        d += timedelta(days=1)
    if atual:
        semanas_antes.append(atual)

    gasto_dia: dict[tuple[str, date], float] = {}
    if semanas_antes:
        for e in db.query(Expense).filter(
            Expense.date >= mes_inicio, Expense.date < inicio, Expense.kind == ek.GASTO, Expense.extraordinary.is_(False)
        ).all():
            k = (e.category or "other", e.date)
            gasto_dia[k] = gasto_dia.get(k, 0) + e.amount

    def _transporte(cat: str, mensal: float) -> float:
        carry = 0.0
        for semana in semanas_antes:
            base_s = _envelope_dias(mensal, semana)
            gasto_s = sum(gasto_dia.get((cat, dia), 0) for dia in semana)
            carry = max(min(carry + base_s - gasto_s, base_s), -base_s)
        return carry

    dias_restantes = max(0, (fim - hoje).days + 1) if inicio <= hoje <= fim else (7 if hoje < inicio else 0)

    cats = []
    for lim in limites:
        cat, mensal = lim["category"], lim["monthly"]
        base = _envelope_dias(mensal, dias_semana)
        transporte = _transporte(cat, mensal) if semanas_antes else 0.0
        envelope = max(0.0, base + transporte)
        gasto = gasto_semana.get(cat, 0)
        pct = round(gasto / envelope * 100, 1) if envelope > 0 else (100.0 if gasto else 0.0)
        sobra = envelope - gasto
        cats.append({
            "category": cat,
            "color": lim["color"],
            "source": lim["source"],
            "monthly_limit": round(mensal, 2),
            "envelope": round(envelope, 2),
            "base": round(base, 2),
            "rollover": round(transporte, 2),
            "spent": round(gasto, 2),
            "remaining": round(sobra, 2),
            "percentage": pct,
            "per_day_left": round(sobra / dias_restantes, 2) if dias_restantes > 0 and sobra > 0 else 0.0,
            "status": "danger" if pct >= 100 else "warning" if pct >= 80 else "ok",
        })

    cats.sort(key=lambda c: c["percentage"], reverse=True)
    total_env = round(sum(c["envelope"] for c in cats), 2)
    total_gasto = round(sum(c["spent"] for c in cats), 2)
    return {
        "week_start": inicio.isoformat(),
        "week_end": fim.isoformat(),
        "is_current": inicio <= hoje <= fim,
        "days_left": dias_restantes,
        "categories": cats,
        "total_envelope": total_env,
        "total_spent": total_gasto,
        "total_remaining": round(total_env - total_gasto, 2),
        "per_day_left": round((total_env - total_gasto) / dias_restantes, 2) if dias_restantes > 0 and total_env > total_gasto else 0.0,
    }


# ── Quanto custa a tua vida ───────────────────────────────────────
# A app tinha orçamento por categoria, envelopes e previsão do mês, mas faltava
# o retrato simples: quanto é inevitável, quanto é escolha, e quanto tempo se
# aguenta se não entrar nada.

FIXAS = {"bills", "subscriptions"}
# Viagens e compras grandes não são o custo do mês: entram por fases (o Erasmus
# levou 50% do gasto variável) e distorcem a ideia do que a vida custa. Ficam à
# parte, com a sua própria média, em vez de inflacionarem o número principal.
OCASIONAIS = {"travel", "shopping"}


@router.get("/cost-of-living")
def custo_de_vida(months: int = Query(6, ge=2, le=24), db: Session = Depends(get_db)):
    from models import Subscription, InvestmentPosition, PortfolioSnapshot

    hoje = date.today()
    inicio = (hoje.replace(day=1) - timedelta(days=1)).replace(day=1)
    for _ in range(months - 1):
        inicio = (inicio - timedelta(days=1)).replace(day=1)

    gastos = db.query(Expense).filter(
        Expense.date >= inicio, Expense.date < hoje.replace(day=1),
        Expense.kind == ek.GASTO, Expense.extraordinary.is_(False),
    ).all()

    por_mes: dict[str, dict[str, float]] = {}
    for e in gastos:
        chave = e.date.strftime("%Y-%m")
        m = por_mes.setdefault(chave, {"fixo": 0.0, "variavel": 0.0, "ocasional": 0.0,
                                       "entrou": 0.0, "n": 0})
        m["n"] += 1
        cat = e.category or ""
        if e.amount < 0:
            m["entrou"] += -e.amount
        elif cat in FIXAS:
            m["fixo"] += e.amount
        elif cat in OCASIONAIS:
            m["ocasional"] += e.amount
        else:
            m["variavel"] += e.amount

    # Meses com meia dúzia de movimentos são meses por importar, não meses
    # baratos: contá-los puxava o custo de vida para baixo artificialmente.
    meses = sorted(m for m in por_mes if por_mes[m]["n"] >= 8)
    if not meses:
        return {"months": 0, "enough": False}

    def mediana(vals: list[float]) -> float:
        s = sorted(vals)
        n = len(s)
        return 0.0 if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2)

    fixo = mediana([por_mes[m]["fixo"] for m in meses])
    variavel = mediana([por_mes[m]["variavel"] for m in meses])
    ocasional = mediana([por_mes[m]["ocasional"] for m in meses])
    ocasional_total = sum(por_mes[m]["ocasional"] for m in meses)
    # subscrições activas contam mesmo que ainda não tenham saído este mês
    subs = sum(
        s.amount / (12 if (s.billing_cycle or "").lower() == "yearly" else 1)
        for s in db.query(Subscription).filter(Subscription.active == True).all()  # noqa: E712
    )
    fixo = max(fixo, subs)

    custo = fixo + variavel
    rendimento = resolve_income(db, hoje.month, hoje.year) or 0

    # o que existe para aguentar sem entrar nada
    carteira = (
        db.query(PortfolioSnapshot.total_value_eur)
        .order_by(PortfolioSnapshot.date.desc()).limit(1).scalar()
    ) or sum(p.current_value_eur or 0 for p in db.query(InvestmentPosition).all()) / max(1, 1)

    meses_folga = round(carteira / custo, 1) if custo > 0 else None
    poupanca_pct = round((rendimento - custo) / rendimento * 100, 1) if rendimento else None

    return {
        "months": len(meses),
        "enough": True,
        "fixed_monthly": round(fixo, 2),
        "variable_monthly": round(variavel, 2),
        "monthly_cost": round(custo, 2),
        "occasional_monthly": round(ocasional, 2),
        "occasional_total": round(ocasional_total, 2),
        "occasional_categories": sorted(OCASIONAIS),
        "income_monthly": round(rendimento, 2),
        "saving_rate_pct": poupanca_pct,
        "buffer_eur": round(carteira, 2),
        "months_covered": meses_folga,
        "by_month": [
            {"month": m, "fixed": round(por_mes[m]["fixo"], 2),
             "variable": round(por_mes[m]["variavel"], 2),
             "occasional": round(por_mes[m]["ocasional"], 2),
             "income": round(por_mes[m]["entrou"], 2)}
            for m in meses
        ],
        "biggest_variable": _maiores_variaveis(gastos),
    }


def _maiores_variaveis(gastos: list) -> list[dict]:
    por_cat: dict[str, float] = {}
    for e in gastos:
        cat = e.category or "other"
        if e.amount > 0 and cat not in FIXAS and cat not in OCASIONAIS:
            por_cat[cat] = por_cat.get(cat, 0) + e.amount
    total = sum(por_cat.values()) or 1
    return [
        {"category": c, "total": round(v, 2), "share": round(v / total * 100, 1)}
        for c, v in sorted(por_cat.items(), key=lambda kv: -kv[1])[:5]
    ]
