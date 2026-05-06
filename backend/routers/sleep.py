from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from datetime import date
from typing import Optional

from database import get_db
from models import SleepEntry
from schemas import SleepCreate, SleepUpdate, SleepOut

router = APIRouter(prefix="/api/sleep", tags=["Sleep"])


@router.get("/", response_model=list[SleepOut])
def list_sleep(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(SleepEntry)
    if start_date:
        q = q.filter(SleepEntry.date >= start_date)
    if end_date:
        q = q.filter(SleepEntry.date <= end_date)
    return q.order_by(SleepEntry.date.desc()).all()


@router.get("/stats")
def sleep_stats(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    from datetime import timedelta
    cutoff = date.today() - timedelta(days=days)
    entries = db.query(SleepEntry).filter(SleepEntry.date >= cutoff).order_by(SleepEntry.date.desc()).all()

    if not entries:
        return {
            "avg_hours": 0, "avg_quality": 0, "total_entries": 0,
            "best_day": None, "worst_day": None, "entries": [],
        }

    hours_list = [e.hours for e in entries]
    quality_list = [e.quality for e in entries if e.quality is not None]

    best = max(entries, key=lambda e: e.hours)
    worst = min(entries, key=lambda e: e.hours)

    return {
        "avg_hours": round(sum(hours_list) / len(hours_list), 1),
        "avg_quality": round(sum(quality_list) / max(len(quality_list), 1), 1),
        "total_entries": len(entries),
        "best_day": {"date": str(best.date), "hours": best.hours},
        "worst_day": {"date": str(worst.date), "hours": worst.hours},
        "entries": [SleepOut.model_validate(e).model_dump() for e in entries],
    }


@router.post("/", response_model=SleepOut)
def create_sleep(data: SleepCreate, db: Session = Depends(get_db)):
    existing = db.query(SleepEntry).filter(SleepEntry.date == data.date).first()
    if existing:
        # Update if entry exists for that date
        for key, value in data.model_dump().items():
            setattr(existing, key, value)
        db.commit()
        db.refresh(existing)
        return existing
    entry = SleepEntry(**data.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.put("/{entry_id}", response_model=SleepOut)
def update_sleep(entry_id: int, data: SleepUpdate, db: Session = Depends(get_db)):
    entry = db.query(SleepEntry).filter(SleepEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Sleep entry not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(entry, key, value)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}")
def delete_sleep(entry_id: int, db: Session = Depends(get_db)):
    entry = db.query(SleepEntry).filter(SleepEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Sleep entry not found")
    db.delete(entry)
    db.commit()
    return {"ok": True}
