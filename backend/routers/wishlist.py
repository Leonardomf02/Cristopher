from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date

from database import get_db
from models import WishlistItem, Expense
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


@router.get("/", response_model=list[WishlistItemOut])
def list_items(db: Session = Depends(get_db)):
    items = db.query(WishlistItem).all()
    return sorted(items, key=_sort_key)


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
    """Mark as purchased and create a real expense on the given date/amount."""
    item = db.query(WishlistItem).filter(WishlistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.purchased:
        raise HTTPException(status_code=400, detail="Already purchased")

    when = payload.date or date.today()
    amount = payload.amount if payload.amount is not None else item.price

    expense = Expense(
        description=item.name,
        amount=round(amount, 2),
        category=item.category or "other",
        date=when,
        notes="Da wishlist",
        kind="spend",
    )
    db.add(expense)
    db.flush()

    item.purchased = True
    item.purchased_date = when
    item.expense_id = expense.id
    db.commit()
    db.refresh(item)
    return item


@router.post("/{item_id}/unpurchase", response_model=WishlistItemOut)
def unpurchase(item_id: int, db: Session = Depends(get_db)):
    """Undo a purchase: delete the created expense and reopen the item."""
    item = db.query(WishlistItem).filter(WishlistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.expense_id:
        exp = db.query(Expense).filter(Expense.id == item.expense_id).first()
        if exp:
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
