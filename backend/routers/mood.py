from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional

from database import get_db
from models import MoodEntry, DailyJournal
from schemas import MoodCreate, MoodOut, JournalCreate, JournalOut

router = APIRouter(prefix="/api/mood", tags=["Mood & Journal"])


# ── Mood CRUD ────────────────────────────────────────────────────

@router.get("/", response_model=list[MoodOut])
def list_moods(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(MoodEntry)
    if start_date:
        q = q.filter(MoodEntry.date >= start_date)
    if end_date:
        q = q.filter(MoodEntry.date <= end_date)
    return q.order_by(MoodEntry.date.desc()).all()


@router.post("/", response_model=MoodOut)
def create_or_update_mood(data: MoodCreate, db: Session = Depends(get_db)):
    if data.mood < 1 or data.mood > 5:
        raise HTTPException(400, "Mood must be between 1 and 5")
    existing = db.query(MoodEntry).filter(MoodEntry.date == data.date).first()
    if existing:
        existing.mood = data.mood
        existing.note = data.note
        existing.tags = data.tags
        db.commit()
        db.refresh(existing)
        return existing
    entry = MoodEntry(**data.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}")
def delete_mood(entry_id: int, db: Session = Depends(get_db)):
    entry = db.query(MoodEntry).filter(MoodEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Mood entry not found")
    db.delete(entry)
    db.commit()
    return {"ok": True}


@router.get("/today")
def mood_today(db: Session = Depends(get_db)):
    """Get today's mood and journal in one call."""
    today = date.today()
    mood = db.query(MoodEntry).filter(MoodEntry.date == today).first()
    journal = db.query(DailyJournal).filter(DailyJournal.date == today).first()
    return {
        "mood": MoodOut.model_validate(mood).model_dump() if mood else None,
        "journal": JournalOut.model_validate(journal).model_dump() if journal else None,
    }


# ── Journal CRUD ─────────────────────────────────────────────────

@router.get("/journal", response_model=list[JournalOut])
def list_journals(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(DailyJournal)
    if start_date:
        q = q.filter(DailyJournal.date >= start_date)
    if end_date:
        q = q.filter(DailyJournal.date <= end_date)
    return q.order_by(DailyJournal.date.desc()).all()


@router.post("/journal", response_model=JournalOut)
def create_or_update_journal(data: JournalCreate, db: Session = Depends(get_db)):
    existing = db.query(DailyJournal).filter(DailyJournal.date == data.date).first()
    if existing:
        existing.content = data.content
        db.commit()
        db.refresh(existing)
        return existing
    entry = DailyJournal(**data.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/journal/{entry_id}")
def delete_journal(entry_id: int, db: Session = Depends(get_db)):
    entry = db.query(DailyJournal).filter(DailyJournal.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Journal entry not found")
    db.delete(entry)
    db.commit()
    return {"ok": True}
