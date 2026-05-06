from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import date, timedelta
from typing import Optional

from database import get_db
from models import Habit, HabitCompletion, DayType
from schemas import HabitCreate, HabitUpdate, HabitOut, HabitCompletionCreate, HabitCompletionOut

# Day type names that protect habit streaks (habits optional, don't break streak)
STREAK_PROTECTED_TYPES = {"Férias", "Aulas", "Doente", "Viagem"}

router = APIRouter(prefix="/api/habits", tags=["Habits"])


# ── Habits CRUD ──────────────────────────────────────────────────

@router.get("/", response_model=list[HabitOut])
def list_habits(active_only: bool = True, db: Session = Depends(get_db)):
    q = db.query(Habit)
    if active_only:
        q = q.filter(Habit.active == True)
    return q.order_by(Habit.position, Habit.id).all()


@router.post("/", response_model=HabitOut)
def create_habit(data: HabitCreate, db: Session = Depends(get_db)):
    habit = Habit(**data.model_dump())
    db.add(habit)
    db.commit()
    db.refresh(habit)
    return habit


@router.put("/{habit_id}", response_model=HabitOut)
def update_habit(habit_id: int, data: HabitUpdate, db: Session = Depends(get_db)):
    habit = db.query(Habit).filter(Habit.id == habit_id).first()
    if not habit:
        raise HTTPException(404, "Habit not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(habit, k, v)
    db.commit()
    db.refresh(habit)
    return habit


@router.delete("/{habit_id}")
def delete_habit(habit_id: int, db: Session = Depends(get_db)):
    habit = db.query(Habit).filter(Habit.id == habit_id).first()
    if not habit:
        raise HTTPException(404, "Habit not found")
    db.query(HabitCompletion).filter(HabitCompletion.habit_id == habit_id).delete()
    db.delete(habit)
    db.commit()
    return {"ok": True}


# ── Completions ──────────────────────────────────────────────────

@router.get("/{habit_id}/completions", response_model=list[HabitCompletionOut])
def list_completions(
    habit_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(HabitCompletion).filter(HabitCompletion.habit_id == habit_id)
    if start_date:
        q = q.filter(HabitCompletion.date >= start_date)
    if end_date:
        q = q.filter(HabitCompletion.date <= end_date)
    return q.order_by(HabitCompletion.date.desc()).all()


@router.post("/{habit_id}/completions", response_model=HabitCompletionOut)
def complete_habit(habit_id: int, data: HabitCompletionCreate, db: Session = Depends(get_db)):
    habit = db.query(Habit).filter(Habit.id == habit_id).first()
    if not habit:
        raise HTTPException(404, "Habit not found")
    # Prevent duplicate completion on same date
    existing = db.query(HabitCompletion).filter(
        HabitCompletion.habit_id == habit_id,
        HabitCompletion.date == data.date,
    ).first()
    if existing:
        raise HTTPException(409, "Already completed for this date")
    completion = HabitCompletion(habit_id=habit_id, **data.model_dump())
    db.add(completion)
    db.commit()
    db.refresh(completion)
    return completion


@router.delete("/{habit_id}/completions/{completion_id}")
def delete_completion(habit_id: int, completion_id: int, db: Session = Depends(get_db)):
    comp = db.query(HabitCompletion).filter(
        HabitCompletion.id == completion_id,
        HabitCompletion.habit_id == habit_id,
    ).first()
    if not comp:
        raise HTTPException(404, "Completion not found")
    db.delete(comp)
    db.commit()
    return {"ok": True}


# ── Bulk completions for calendar ────────────────────────────────

@router.get("/completions/range")
def completions_in_range(
    start_date: str = Query(...),
    end_date: str = Query(...),
    db: Session = Depends(get_db),
):
    """Get all completions for all habits in a date range. Used by calendar to render habit events."""
    completions = (
        db.query(HabitCompletion)
        .filter(HabitCompletion.date >= start_date, HabitCompletion.date <= end_date)
        .all()
    )
    habits = {h.id: h for h in db.query(Habit).all()}
    result = []
    for c in completions:
        h = habits.get(c.habit_id)
        if not h:
            continue
        result.append({
            "id": c.id,
            "habit_id": c.habit_id,
            "habit_name": h.name,
            "habit_icon": h.icon,
            "habit_color": h.color,
            "date": str(c.date),
            "completed_at": c.completed_at,
            "notes": c.notes,
        })
    return result


@router.get("/today")
def habits_today(db: Session = Depends(get_db)):
    """Get all active habits for today with their completion status."""
    today = date.today()
    weekday = today.weekday()  # 0=Mon ... 6=Sun
    habits = db.query(Habit).filter(Habit.active == True).order_by(Habit.position, Habit.id).all()

    completions = {
        c.habit_id: c for c in
        db.query(HabitCompletion).filter(HabitCompletion.date == today).all()
    }

    # Check if today is a protected day (Férias, Aulas, Doente, Viagem)
    today_dt = db.query(DayType).filter(DayType.date == today).first()
    is_protected = today_dt is not None and today_dt.type_name in STREAK_PROTECTED_TYPES

    result = []
    for h in habits:
        if not _is_scheduled(h.days, weekday):
            continue
        comp = completions.get(h.id)
        result.append({
            "id": h.id,
            "name": h.name,
            "icon": h.icon,
            "color": h.color,
            "days": h.days,
            "fixed_time": h.fixed_time,
            "completed": comp is not None,
            "protected": is_protected,
            "day_type": today_dt.type_name if today_dt else None,
            "completion": {
                "id": comp.id,
                "completed_at": comp.completed_at,
                "notes": comp.notes,
            } if comp else None,
        })
    return result


def _is_scheduled(days: str, weekday: int) -> bool:
    """Check if a habit is scheduled for a given weekday (0=Mon..6=Sun)."""
    if days == "daily":
        return True
    if days == "weekdays":
        return weekday < 5
    # Specific days: "0,1,3,5" means Mon, Tue, Thu, Sat
    try:
        allowed = {int(d.strip()) for d in days.split(",")}
        return weekday in allowed
    except ValueError:
        return True


# ── Habit Analytics ──────────────────────────────────────────────

@router.get("/analytics")
def habit_analytics(
    days: int = Query(90, ge=7, le=365),
    db: Session = Depends(get_db),
):
    """Full analytics: completion rates, streaks, heatmap, best/worst days."""
    today = date.today()
    cutoff = today - timedelta(days=days)

    habits = db.query(Habit).filter(Habit.active == True).order_by(Habit.position, Habit.id).all()
    all_completions = (
        db.query(HabitCompletion)
        .filter(HabitCompletion.date >= cutoff)
        .all()
    )

    # Get protected day types in range (Férias, Aulas, Doente, Viagem) — streak skips these days
    protected_dates = {
        str(dt.date) for dt in db.query(DayType).filter(
            DayType.date >= cutoff,
            DayType.type_name.in_(STREAK_PROTECTED_TYPES),
        ).all()
    }

    # Group completions by habit
    comp_by_habit: dict[int, set[str]] = {}
    for c in all_completions:
        comp_by_habit.setdefault(c.habit_id, set()).add(str(c.date))

    # Heatmap: all dates with count of completions
    heatmap: dict[str, int] = {}
    for c in all_completions:
        ds = str(c.date)
        heatmap[ds] = heatmap.get(ds, 0) + 1

    habit_details = []
    for h in habits:
        dates_completed = comp_by_habit.get(h.id, set())

        # Count scheduled days and completions
        scheduled = 0
        completed = 0
        by_weekday = [0] * 7  # completions per weekday
        by_weekday_scheduled = [0] * 7

        d = cutoff
        while d <= today:
            if _is_scheduled(h.days, d.weekday()) and str(d) not in protected_dates:
                scheduled += 1
                by_weekday_scheduled[d.weekday()] += 1
                if str(d) in dates_completed:
                    completed += 1
                    by_weekday[d.weekday()] += 1
            d += timedelta(days=1)

        # Calculate streak — consecutive scheduled days completed, going back from today.
        # Protected days (Férias/Aulas/Doente/Viagem) are skipped and do not break the streak.
        current_streak = 0
        d = today
        while d >= cutoff:
            if str(d) in protected_dates:
                d -= timedelta(days=1)
                continue
            if _is_scheduled(h.days, d.weekday()):
                if str(d) in dates_completed:
                    current_streak += 1
                else:
                    break
            d -= timedelta(days=1)

        # Best streak ever in range (also protected-day aware)
        best_streak = 0
        streak = 0
        d = cutoff
        while d <= today:
            if str(d) in protected_dates:
                d += timedelta(days=1)
                continue
            if _is_scheduled(h.days, d.weekday()):
                if str(d) in dates_completed:
                    streak += 1
                    best_streak = max(best_streak, streak)
                else:
                    streak = 0
            d += timedelta(days=1)

        rate = round(completed / scheduled * 100, 1) if scheduled > 0 else 0

        # Best/worst weekday
        day_names = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
        weekday_rates = []
        for wd in range(7):
            if by_weekday_scheduled[wd] > 0:
                weekday_rates.append({
                    "day": day_names[wd],
                    "weekday": wd,
                    "completed": by_weekday[wd],
                    "scheduled": by_weekday_scheduled[wd],
                    "rate": round(by_weekday[wd] / by_weekday_scheduled[wd] * 100, 1),
                })

        habit_details.append({
            "id": h.id,
            "name": h.name,
            "icon": h.icon,
            "color": h.color,
            "scheduled": scheduled,
            "completed": completed,
            "rate": rate,
            "current_streak": current_streak,
            "best_streak": best_streak,
            "by_weekday": weekday_rates,
            "dates_completed": sorted(dates_completed),
        })

    # Global heatmap for last N days
    heatmap_list = []
    d = cutoff
    while d <= today:
        heatmap_list.append({
            "date": str(d),
            "count": heatmap.get(str(d), 0),
        })
        d += timedelta(days=1)

    return {
        "days": days,
        "habits": habit_details,
        "heatmap": heatmap_list,
    }
