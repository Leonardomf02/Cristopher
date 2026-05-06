from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional

from database import get_db
from models import BudgetLimit, Subscription, Expense
from schemas import (
    BudgetLimitCreate, BudgetLimitUpdate, BudgetLimitOut,
    SubscriptionCreate, SubscriptionUpdate, SubscriptionOut,
)

router = APIRouter(prefix="/api/budgets", tags=["Budgets & Subscriptions"])


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
        .filter(extract("month", Expense.date) == m, extract("year", Expense.date) == y)
        .all()
    )

    # Sum by category
    spent_by_cat: dict[str, float] = {}
    for e in expenses:
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
