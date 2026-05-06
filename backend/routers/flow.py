from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional

from database import get_db
from models import FlowPreset, FlowSession
from schemas import (
    FlowPresetCreate, FlowPresetUpdate, FlowPresetOut,
    FlowSessionCreate, FlowSessionOut,
)

router = APIRouter(prefix="/api/flow", tags=["Flow Timer"])


# ── Presets ──────────────────────────────────────────────────────

@router.get("/presets", response_model=list[FlowPresetOut])
def list_presets(db: Session = Depends(get_db)):
    return db.query(FlowPreset).order_by(FlowPreset.name).all()


@router.post("/presets", response_model=FlowPresetOut)
def create_preset(data: FlowPresetCreate, db: Session = Depends(get_db)):
    preset = FlowPreset(**data.model_dump())
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return preset


@router.put("/presets/{preset_id}", response_model=FlowPresetOut)
def update_preset(preset_id: int, data: FlowPresetUpdate, db: Session = Depends(get_db)):
    preset = db.query(FlowPreset).filter(FlowPreset.id == preset_id).first()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(preset, key, value)
    db.commit()
    db.refresh(preset)
    return preset


@router.delete("/presets/{preset_id}")
def delete_preset(preset_id: int, db: Session = Depends(get_db)):
    preset = db.query(FlowPreset).filter(FlowPreset.id == preset_id).first()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    db.delete(preset)
    db.commit()
    return {"ok": True}


# ── Sessions ─────────────────────────────────────────────────────

@router.get("/sessions", response_model=list[FlowSessionOut])
def list_sessions(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    preset_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(FlowSession)
    if start_date:
        q = q.filter(FlowSession.date >= start_date)
    if end_date:
        q = q.filter(FlowSession.date <= end_date)
    if preset_name:
        q = q.filter(FlowSession.preset_name == preset_name)
    return q.order_by(FlowSession.date.desc(), FlowSession.start_time.desc()).all()


@router.post("/sessions", response_model=FlowSessionOut)
def create_session(data: FlowSessionCreate, db: Session = Depends(get_db)):
    session = FlowSession(**data.model_dump())
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    session = db.query(FlowSession).filter(FlowSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(session)
    db.commit()
    return {"ok": True}


# ── Stats ────────────────────────────────────────────────────────

@router.get("/stats")
def flow_stats(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(FlowSession)
    if start_date:
        q = q.filter(FlowSession.date >= start_date)
    if end_date:
        q = q.filter(FlowSession.date <= end_date)

    sessions = q.all()
    total_sessions = len(sessions)
    total_minutes = sum(s.actual_minutes or s.planned_minutes for s in sessions)
    completed = sum(1 for s in sessions if s.completed)

    # Group by preset
    by_preset: dict = {}
    for s in sessions:
        name = s.preset_name
        if name not in by_preset:
            by_preset[name] = {"sessions": 0, "minutes": 0, "completed": 0, "color": s.color}
        by_preset[name]["sessions"] += 1
        by_preset[name]["minutes"] += s.actual_minutes or s.planned_minutes
        if s.completed:
            by_preset[name]["completed"] += 1

    return {
        "total_sessions": total_sessions,
        "total_minutes": total_minutes,
        "total_hours": round(total_minutes / 60, 1),
        "completed": completed,
        "completion_rate": round(completed / total_sessions * 100, 1) if total_sessions > 0 else 0,
        "by_preset": by_preset,
    }
