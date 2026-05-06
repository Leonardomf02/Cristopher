from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional

from database import get_db
from models import DayType
from schemas import DayTypeCreate, DayTypeOut

router = APIRouter(prefix="/api/day-types", tags=["Day Types"])


@router.get("/", response_model=list[DayTypeOut])
def list_day_types(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(DayType)
    if start_date:
        q = q.filter(DayType.date >= start_date)
    if end_date:
        q = q.filter(DayType.date <= end_date)
    return q.order_by(DayType.date).all()


@router.post("/", response_model=DayTypeOut)
def set_day_type(data: DayTypeCreate, db: Session = Depends(get_db)):
    existing = db.query(DayType).filter(DayType.date == data.date).first()
    if existing:
        for key, value in data.model_dump().items():
            setattr(existing, key, value)
        db.commit()
        db.refresh(existing)
        return existing
    dt = DayType(**data.model_dump())
    db.add(dt)
    db.commit()
    db.refresh(dt)
    return dt


@router.delete("/{day_type_id}")
def delete_day_type(day_type_id: int, db: Session = Depends(get_db)):
    dt = db.query(DayType).filter(DayType.id == day_type_id).first()
    if not dt:
        raise HTTPException(status_code=404, detail="Day type not found")
    db.delete(dt)
    db.commit()
    return {"ok": True}
