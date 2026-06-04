from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from datetime import date, datetime, time, timedelta
from typing import Optional

from database import get_db, SessionLocal
from models import SleepEntry
from schemas import SleepCreate, SleepUpdate, SleepOut

router = APIRouter(prefix="/api/sleep", tags=["Sleep"])


def _estimate_for_night(reader_mod, prev_day: date, next_day: date) -> Optional[dict]:
    """Estimate sleep for the night between prev_day and next_day, by finding
    the longest inactivity gap in [prev_day 18:00, next_day 12:00].

    bedtime = last activity end + 45min ; wake = first activity start - 30min.
    """
    activity_start = datetime.combine(prev_day, time(12, 0)).timestamp()
    activity_end = datetime.combine(next_day, time(18, 0)).timestamp()
    try:
        sessions = reader_mod.fetch_sessions(activity_start, activity_end, min_seconds=30)
    except Exception:
        return None
    if not sessions:
        return None

    intervals = sorted([(float(s["start_unix"]), float(s["end_unix"])) for s in sessions])
    merged: list[tuple[float, float]] = []
    for st, en in intervals:
        if merged and st <= merged[-1][1] + 60:
            merged[-1] = (merged[-1][0], max(merged[-1][1], en))
        else:
            merged.append((st, en))
    if len(merged) < 2:
        return None

    sleep_win_start = datetime.combine(prev_day, time(18, 0)).timestamp()
    sleep_win_end = datetime.combine(next_day, time(12, 0)).timestamp()

    best: Optional[tuple[float, float, float]] = None
    for i in range(len(merged) - 1):
        gap_start = merged[i][1]
        gap_end = merged[i + 1][0]
        gap = gap_end - gap_start
        if gap < 2 * 3600:
            continue
        ovl_start = max(gap_start, sleep_win_start)
        ovl_end = min(gap_end, sleep_win_end)
        if ovl_end - ovl_start < 3600:
            continue
        if best is None or gap > best[2]:
            best = (gap_start, gap_end, gap)
    if best is None:
        return None

    last_end, first_start, _ = best
    bedtime_ts = last_end + 45 * 60
    waketime_ts = first_start - 30 * 60
    if waketime_ts - bedtime_ts < 2 * 3600:
        return None

    bedtime_dt = datetime.fromtimestamp(bedtime_ts)
    waketime_dt = datetime.fromtimestamp(waketime_ts)
    hours = round((waketime_ts - bedtime_ts) / 3600.0 * 10) / 10
    return {
        "bedtime": bedtime_dt.strftime("%H:%M"),
        "wake_time": waketime_dt.strftime("%H:%M"),
        "hours": hours,
        "last_activity": datetime.fromtimestamp(last_end).strftime("%Y-%m-%d %H:%M"),
        "first_activity": datetime.fromtimestamp(first_start).strftime("%Y-%m-%d %H:%M"),
        "source": "screen_time",
    }


def _estimate_sleep_from_pc(target_date: date) -> Optional[dict]:
    """Heuristic sleep estimate from local PC activity (knowledgeC.db).

    Tries both possible nights for the given date and picks the one with usable
    activity (a clear 2h+ gap surrounded by activity on both sides):
    - night ENDING on target_date (prev_day = target_date - 1, next_day = target_date)
    - night STARTING on target_date (prev_day = target_date, next_day = target_date + 1)

    Prefers the night that has already fully ended (clearer signal). Returns
    None if neither night has a usable gap.
    """
    try:
        import screen_time_reader as reader
    except ImportError:
        return None
    ok, _ = reader.is_available()
    if not ok:
        return None

    # Tentar a noite que termina em target_date (last night, do ponto de vista
    # de quem acordou hoje). É a mais fiável porque já aconteceu inteira.
    ended = _estimate_for_night(reader, target_date - timedelta(days=1), target_date)
    if ended:
        ended["date"] = target_date.isoformat()
        ended["night_label"] = f"noite de {(target_date - timedelta(days=1)).strftime('%d/%m')} → {target_date.strftime('%d/%m')}"
        return ended

    # Fallback: a noite que começa hoje (só faz sentido se já é manhã do dia seguinte).
    starting = _estimate_for_night(reader, target_date, target_date + timedelta(days=1))
    if starting:
        starting["date"] = target_date.isoformat()
        starting["night_label"] = f"noite de {target_date.strftime('%d/%m')} → {(target_date + timedelta(days=1)).strftime('%d/%m')}"
        return starting

    return None


def auto_register_recent_sleep(days_back: int = 7) -> int:
    """Estima e regista automaticamente o sono das últimas noites a partir do
    uso do PC, criando apenas entradas em falta (source='auto'). Nunca toca em
    entradas existentes (manuais ou já auto-registadas), por isso é seguro
    correr repetidamente. Devolve o número de noites registadas.

    Cada entrada usa SÓ a noite que TERMINA nesse dia (acordar = data da entrada),
    para que cada noite seja atribuída a exactamente um dia (sem duplicados)."""
    try:
        import screen_time_reader as reader
    except ImportError:
        return 0
    ok, _ = reader.is_available()
    if not ok:
        return 0

    created = 0
    db = SessionLocal()
    try:
        today = date.today()
        for offset in range(days_back + 1):
            d = today - timedelta(days=offset)
            if db.query(SleepEntry).filter(SleepEntry.date == d).first():
                continue
            est = _estimate_for_night(reader, d - timedelta(days=1), d)
            if not est:
                continue
            db.add(SleepEntry(
                date=d,
                bedtime=est["bedtime"],
                wake_time=est["wake_time"],
                hours=est["hours"],
                quality=None,
                notes="",
                source="auto",
            ))
            created += 1
        if created:
            db.commit()
    finally:
        db.close()
    return created


@router.post("/auto-register")
def trigger_auto_register(days_back: int = Query(7, ge=1, le=60)):
    """Força um ciclo de auto-registo (usado pelo arranque e opcionalmente pela UI)."""
    return {"created": auto_register_recent_sleep(days_back)}


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
    days: int = Query(30, ge=1, le=36500),
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
    entry.source = "manual"  # editado pelo utilizador deixa de ser auto
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


@router.get("/estimate")
def estimate_sleep(target_date: Optional[date] = Query(None, alias="date")):
    """Estimate sleep hours for the night following `date` based on PC activity."""
    d = target_date or (date.today() - timedelta(days=1))
    est = _estimate_sleep_from_pc(d)
    if not est:
        raise HTTPException(
            status_code=404,
            detail="Sem actividade no PC suficiente para estimar o sono dessa noite.",
        )
    return est
