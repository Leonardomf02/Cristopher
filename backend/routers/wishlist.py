import re
import unicodedata
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import date, timedelta
from typing import Optional

from database import get_db
from models import WishlistItem, Expense
import expense_kind as ek
from schemas import (
    WishlistItemCreate, WishlistItemUpdate, WishlistItemOut, WishlistPurchase,
)

router = APIRouter(prefix="/api/wishlist", tags=["Wishlist"])

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _sort_key(item: WishlistItem):
    # not-purchased first, then by priority, then most expensive first
    return (
        item.purchased,
        PRIORITY_ORDER.get(item.priority, 1),
        -item.price,
    )


# Marca dos gastos que a wishlist criava sozinha ao carimbar "Comprei". Já não
# cria nenhum: a compra está sempre na conta, e criar outra era contá-la duas vezes.
NOTA_ANTIGA = "Da wishlist"


def _pago(db: Session, items: list[WishlistItem]) -> None:
    """Põe em cada item comprado o que saiu de facto da conta. Com a Klarna o
    movimento é uma prestação: diz-se de quantas, quantas já foram e o total."""
    ligados = [i for i in items if i.purchased and i.expense_id]
    if not ligados:
        return
    gastos = {e.id: e for e in db.query(Expense).filter(
        Expense.id.in_([i.expense_id for i in ligados])).all()}
    planos = None
    for i in ligados:
        e = gastos.get(i.expense_id)
        if not e:
            continue
        info = {"expense_id": e.id, "date": e.date.isoformat(), "description": e.description,
                "amount": round(e.amount, 2), "klarna": None,
                "made_here": (e.notes or "") == NOTA_ANTIGA and not e.bank_tx_id}
        if e.klarna_installments:
            if planos is None:
                from routers.expenses import _planos_klarna
                planos = _planos_klarna(db)
            p = next((p for p in planos if p["expense_id"] == e.id
                      or any(x["expense_id"] == e.id for x in p["payments"])), None)
            if p:
                info["klarna"] = {"of": p["of"], "paid": p["paid"], "installment": p["amount"],
                                  "total": round(p["amount"] * p["of"], 2)}
        i.paid = info


@router.get("/", response_model=list[WishlistItemOut])
def list_items(db: Session = Depends(get_db)):
    items = db.query(WishlistItem).all()
    _pago(db, items)
    return sorted(items, key=_sort_key)


def _palavras(texto: str) -> set[str]:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]+", t) if len(w) >= 3}


@router.get("/{item_id}/candidates")
def candidatos(item_id: int, q: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """As transacções que podem ser esta compra, da mais provável para a menos.
    O banco escreve a loja e não o produto ("youget.pt", "Klarna"), por isso o
    que pesa mais é o valor: o preço inteiro, ou uma prestação dele quando o
    movimento é da Klarna."""
    item = db.query(WishlistItem).filter(WishlistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    ja_ligados = {i.expense_id for i in db.query(WishlistItem).filter(
        WishlistItem.expense_id.isnot(None), WishlistItem.id != item_id).all()}

    query = db.query(Expense).filter(Expense.kind == ek.GASTO, Expense.amount > 0)
    if q and q.strip():
        query = query.filter(Expense.description.ilike(f"%{q.strip()}%"))
    else:
        query = query.filter(Expense.date >= date.today() - timedelta(days=120))
    gastos = [e for e in query.order_by(Expense.date.desc()).limit(400).all()
              if e.id not in ja_ligados and (e.notes or "") != NOTA_ANTIGA]

    preco = item.price or 0
    nome = _palavras(item.name)

    def perto(valor: float) -> bool:
        return preco > 0 and abs(valor - preco) <= max(2.0, preco * 0.15)

    def pontos(e: Expense) -> float:
        p = 0.0
        if nome & _palavras(f"{e.description} {e.notes or ''}"):
            p += 3
        if perto(e.amount):
            p += 3
        elif e.klarna_installments and perto(e.amount * e.klarna_installments):
            p += 3
        elif any(perto(e.amount * n) for n in (3, 4)) and "klarna" in (e.description or "").lower():
            p += 2
        if e.klarna_installments:
            p += 0.5
        return p

    fora = sorted(gastos, key=lambda e: (-pontos(e), -e.date.toordinal()))[:25]
    return [{
        "id": e.id, "date": e.date.isoformat(), "description": e.description,
        "amount": round(e.amount, 2), "category": e.category,
        "klarna_installments": e.klarna_installments, "likely": pontos(e) >= 3,
    } for e in fora]


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    open_items = db.query(WishlistItem).filter(WishlistItem.purchased == False).all()  # noqa: E712
    total_wanted = sum(i.price for i in open_items)
    total_saved = sum(min(i.saved_amount, i.price) for i in open_items)
    return {
        "count": len(open_items),
        "total_wanted": round(total_wanted, 2),
        "total_saved": round(total_saved, 2),
        "total_remaining": round(max(total_wanted - total_saved, 0), 2),
    }


@router.post("/", response_model=WishlistItemOut)
def create_item(payload: WishlistItemCreate, db: Session = Depends(get_db)):
    item = WishlistItem(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{item_id}", response_model=WishlistItemOut)
def update_item(item_id: int, payload: WishlistItemUpdate, db: Session = Depends(get_db)):
    item = db.query(WishlistItem).filter(WishlistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


@router.post("/{item_id}/save", response_model=WishlistItemOut)
def add_saving(item_id: int, amount: float, db: Session = Depends(get_db)):
    """Add (or subtract, with a negative amount) to the amount already put aside."""
    item = db.query(WishlistItem).filter(WishlistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    item.saved_amount = max(0.0, round((item.saved_amount or 0) + amount, 2))
    db.commit()
    db.refresh(item)
    return item


@router.post("/{item_id}/purchase", response_model=WishlistItemOut)
def purchase(item_id: int, payload: WishlistPurchase, db: Session = Depends(get_db)):
    """Liga o item à transacção da compra, que já está na conta. Nunca cria uma."""
    item = db.query(WishlistItem).filter(WishlistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.purchased:
        raise HTTPException(status_code=400, detail="Already purchased")
    e = db.query(Expense).filter(Expense.id == payload.expense_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Transação não encontrada")

    item.purchased = True
    item.purchased_date = e.date
    item.expense_id = e.id
    db.commit()
    db.refresh(item)
    _pago(db, [item])
    return item


@router.post("/{item_id}/unpurchase", response_model=WishlistItemOut)
def unpurchase(item_id: int, db: Session = Depends(get_db)):
    """Desfaz a compra: a transacção fica, só deixa de estar ligada. A excepção
    são os gastos que a wishlist inventava antes (sem banco, com a nota dela) —
    esses eram cópias e vão-se embora."""
    item = db.query(WishlistItem).filter(WishlistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.expense_id:
        exp = db.query(Expense).filter(Expense.id == item.expense_id).first()
        if exp and (exp.notes or "") == NOTA_ANTIGA and not exp.bank_tx_id:
            db.delete(exp)
    item.purchased = False
    item.purchased_date = None
    item.expense_id = None
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(WishlistItem).filter(WishlistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


# ── Ligação aos deals e ao que sobra do orçamento ─────────────────
# Um item da wishlist parado a 0€ poupados não é um plano, é um post-it. Aqui
# passa a ser vigiado nos anúncios e a app diz quando é que o dinheiro lá chega.

@router.post("/{item_id}/watch")
def criar_watch(item_id: int, db: Session = Depends(get_db)):
    """Põe os Deals a vigiar este item da wishlist."""
    from models import DealWatch
    from routers.deals import start_scan

    item = db.query(WishlistItem).filter(WishlistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado")

    if item.watch_id:
        existente = db.query(DealWatch).filter(DealWatch.id == item.watch_id).first()
        if existente:
            return {"watch_id": existente.id, "created": False, "title": existente.title}

    watch = DealWatch(
        title=item.name,
        query=item.name,
        category=item.category or "",
        condition="any",
        sources="all",
        max_price=round(item.price, 2) if item.price else None,
        min_rating=60,
        ai_context=(item.notes or "")[:500],
        kind="generic" if len((item.name or "").split()) <= 2 else "specific",
        notify=True,
        active=True,
    )
    db.add(watch)
    db.commit()
    db.refresh(watch)
    item.watch_id = watch.id
    db.commit()
    start_scan(watch.id)
    return {"watch_id": watch.id, "created": True, "title": watch.title}


@router.get("/{item_id}/plan")
def plano_de_poupanca(item_id: int, db: Session = Depends(get_db)):
    """Quando é que isto está pago, ao ritmo do que tem sobrado dos envelopes."""
    from datetime import timedelta
    from routers.budgets import weekly_envelopes

    item = db.query(WishlistItem).filter(WishlistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado")

    falta = max(0.0, (item.price or 0) - (item.saved_amount or 0))

    # Só conta como "sobra" o que ficou por gastar em categorias onde ele
    # realmente gastou nessa semana: um envelope de viagens intocado não é
    # dinheiro poupado, é uma categoria que não usou.
    sobras = []
    for offset in (-1, -2, -3, -4, -5, -6):
        try:
            semana = weekly_envelopes(week_offset=offset, db=db)
        except Exception:
            continue
        usadas = [c for c in semana.get("categories", []) if c["spent"] > 0]
        if not usadas:
            continue
        sobras.append(round(sum(max(0.0, c["remaining"]) for c in usadas), 2))

    sobras.sort()
    media = sobras[len(sobras) // 2] if sobras else 0.0

    semanas = None
    data_alvo = None
    if falta <= 0:
        semanas = 0
        data_alvo = date.today().isoformat()
    elif media > 0:
        semanas = int(falta / media) + (1 if falta % media else 0)
        data_alvo = (date.today() + timedelta(weeks=semanas)).isoformat()

    melhor = None
    if item.watch_id:
        from models import DealResult
        melhor_r = (
            db.query(DealResult)
            .filter(
                DealResult.watch_id == item.watch_id,
                DealResult.ai_match == True,  # noqa: E712
                DealResult.status != "gone",
                DealResult.price.isnot(None),
            )
            .order_by(DealResult.price.asc())
            .first()
        )
        if melhor_r:
            melhor = {"id": melhor_r.id, "title": melhor_r.title, "price": melhor_r.price,
                      "url": melhor_r.url, "rating": melhor_r.ai_rating}

    return {
        "item_id": item.id,
        "name": item.name,
        "price": item.price,
        "saved": item.saved_amount or 0,
        "missing": round(falta, 2),
        "weekly_leftover": media,
        "weeks_needed": semanas,
        "target_date": data_alvo,
        "watch_id": item.watch_id,
        "best_deal": melhor,
    }
