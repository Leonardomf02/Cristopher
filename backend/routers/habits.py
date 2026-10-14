from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, timedelta
from typing import Optional

from database import get_db
from models import (
    Habit, HabitCompletion, DayType, WakaProjectDay, AppUsageSession,
    ScreenTimeDailyApp, Event,
)
from schemas import HabitCreate, HabitUpdate, HabitOut, HabitCompletionCreate, HabitCompletionOut

# Day type names that protect habit streaks (habits optional, don't break streak)
STREAK_PROTECTED_TYPES = {"Férias"}

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


def _to_minutes(hhmm: str) -> int | None:
    """'07:30' → 450. None se a hora não for válida."""
    try:
        h, m = (int(x) for x in str(hhmm).split(":")[:2])
    except (ValueError, AttributeError):
        return None
    return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None


def _time_stats(entries: list[dict]) -> dict | None:
    """Estatísticas da hora a que um hábito é feito.

    A média é circular (trata 23:50 e 00:10 como próximos, não como 12h de distância),
    senão hábitos nocturnos davam médias absurdas a meio da tarde."""
    import math

    mins = [e["minutes"] for e in entries if e["minutes"] is not None]
    if not mins:
        return None

    angles = [m / 1440 * 2 * math.pi for m in mins]
    avg_angle = math.atan2(
        sum(math.sin(a) for a in angles) / len(angles),
        sum(math.cos(a) for a in angles) / len(angles),
    )
    avg_min = int(round(avg_angle / (2 * math.pi) * 1440)) % 1440

    # Dispersão: 0 = sempre à mesma hora, 1 = completamente espalhado.
    r = math.hypot(
        sum(math.sin(a) for a in angles) / len(angles),
        sum(math.cos(a) for a in angles) / len(angles),
    )

    by_hour = [0] * 24
    for m in mins:
        by_hour[m // 60] += 1

    ordered = sorted(mins)
    return {
        "count": len(mins),
        "avg": f"{avg_min // 60:02d}:{avg_min % 60:02d}",
        "earliest": f"{ordered[0] // 60:02d}:{ordered[0] % 60:02d}",
        "latest": f"{ordered[-1] // 60:02d}:{ordered[-1] % 60:02d}",
        "median": f"{ordered[len(ordered) // 2] // 60:02d}:{ordered[len(ordered) // 2] % 60:02d}",
        "consistency": round(r * 100),
        "by_hour": by_hour,
    }


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
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """Full analytics: completion rates, streaks, heatmap, best/worst days.
    Com start_date/end_date (um mês, um ano) a janela é essa em vez dos últimos
    `days`; o que ainda não chegou não conta como falhado."""
    today = date.today()
    if start_date:
        cutoff = start_date
        fim = min(end_date or today, today)
    else:
        cutoff = today - timedelta(days=days)
        fim = today
    # A streak actual é sempre a de hoje, seja qual for o período que se está a ver.
    desde = min(cutoff, today - timedelta(days=400))

    habits = db.query(Habit).filter(Habit.active == True).order_by(Habit.position, Habit.id).all()
    todas = db.query(HabitCompletion).filter(HabitCompletion.date >= desde).all()
    all_completions = [c for c in todas if cutoff <= c.date <= fim]

    # Get protected day types in range (Férias, Aulas, Doente, Viagem) — streak skips these days
    protected_dates = {
        str(dt.date) for dt in db.query(DayType).filter(
            DayType.date >= desde,
            DayType.type_name.in_(STREAK_PROTECTED_TYPES),
        ).all()
    }

    # Group completions by habit
    comp_by_habit: dict[int, set[str]] = {}
    times_by_habit: dict[int, list[dict]] = {}
    for c in todas:
        comp_by_habit.setdefault(c.habit_id, set()).add(str(c.date))
    for c in all_completions:
        times_by_habit.setdefault(c.habit_id, []).append({
            "date": str(c.date),
            "time": c.completed_at,
            "minutes": _to_minutes(c.completed_at),
            "notes": c.notes or "",
        })

    # Heatmap: all dates with count of completions
    heatmap: dict[str, int] = {}
    for c in all_completions:
        ds = str(c.date)
        heatmap[ds] = heatmap.get(ds, 0) + 1

    habit_details = []
    for h in habits:
        todas_feitas = comp_by_habit.get(h.id, set())
        dates_completed = {ds for ds in todas_feitas if str(cutoff) <= ds <= str(fim)}
        entries = times_by_habit.get(h.id, [])
        time_by_date = {e["date"]: e["time"] for e in entries}

        # Count scheduled days and completions
        scheduled = 0
        completed = 0
        by_weekday = [0] * 7  # completions per weekday
        by_weekday_scheduled = [0] * 7

        d = cutoff
        while d <= fim:
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
        while d >= desde:
            if str(d) in protected_dates:
                d -= timedelta(days=1)
                continue
            if _is_scheduled(h.days, d.weekday()):
                if str(d) in todas_feitas:
                    current_streak += 1
                else:
                    break
            d -= timedelta(days=1)

        # Best streak ever in range (also protected-day aware)
        best_streak = 0
        streak = 0
        d = cutoff
        while d <= fim:
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
            "days": h.days,
            "fixed_time": h.fixed_time,
            "scheduled": scheduled,
            "completed": completed,
            "rate": rate,
            "current_streak": current_streak,
            "best_streak": best_streak,
            "by_weekday": weekday_rates,
            "dates_completed": sorted(dates_completed),
            # Mapa de actividade só deste hábito: feito / falhado / não estava marcado.
            "heatmap": [
                {
                    "date": str(d),
                    "done": str(d) in dates_completed,
                    "scheduled": _is_scheduled(h.days, d.weekday()),
                    "protected": str(d) in protected_dates,
                    "time": time_by_date.get(str(d)),
                }
                for d in (cutoff + timedelta(days=i) for i in range((fim - cutoff).days + 1))
            ],
            "times": sorted(entries, key=lambda e: e["date"], reverse=True),
            "time_stats": _time_stats(entries),
        })

    # Global heatmap for last N days
    heatmap_list = []
    d = cutoff
    while d <= fim:
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


# ── Detecção automática ──────────────────────────────────────────
#
# Marcar hábitos à mão não pega. Aqui a app olha para o que já sabe do dia
# (tempo de código, apps usadas, ecrã, eventos do calendário) e propõe o
# check — falta só confirmar.

_KEYWORDS = {
    "codigo": ["pesquisa", "estud", "código", "codigo", "program", "trabalh", "tese", "projecto", "projeto"],
    "treino": ["gym", "ginásio", "ginasio", "treino", "corr", "muscula", "desporto", "bike", "nata"],
    "leitura": ["ler", "leitura", "livro"],
}


def _kind(name: str) -> Optional[str]:
    low = (name or "").lower()
    for kind, words in _KEYWORDS.items():
        if any(w in low for w in words):
            return kind
    return None


def _hm(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m // 60}h{m % 60:02d}" if m >= 60 else f"{m}min"


@router.get("/suggestions")
def habit_suggestions(day: Optional[date] = Query(None), db: Session = Depends(get_db)):
    """Hábitos de hoje que a app acha que já fizeste, com a razão."""
    d = day or date.today()
    weekday = d.weekday()
    habits = db.query(Habit).filter(Habit.active == True).all()
    done = {c.habit_id for c in db.query(HabitCompletion).filter(HabitCompletion.date == d).all()}

    code_seconds = float(
        db.query(func.coalesce(func.sum(WakaProjectDay.seconds), 0))
        .filter(WakaProjectDay.day == d, WakaProjectDay.kind == "project")
        .scalar() or 0
    )
    dev_seconds = float(
        db.query(func.coalesce(func.sum(AppUsageSession.duration_seconds), 0))
        .filter(AppUsageSession.date == d)
        .filter(func.lower(AppUsageSession.app_name).like("%code%"))
        .scalar() or 0
    )
    reading_seconds = float(
        db.query(func.coalesce(func.sum(ScreenTimeDailyApp.seconds), 0))
        .filter(ScreenTimeDailyApp.date == d, ScreenTimeDailyApp.category == "Information & Reading")
        .scalar() or 0
    )
    eventos = db.query(Event).filter(Event.date == d).all()

    # Maior intervalo longe do computador entre as 7h e as 23h — serve de sinal
    # para hábitos fora do PC (gym, corrida...).
    sessions = (
        db.query(AppUsageSession)
        .filter(AppUsageSession.date == d)
        .order_by(AppUsageSession.start_time)
        .all()
    )
    def _to_min(t) -> int:
        s = str(t)[:5]
        try:
            h, m = s.split(":")
            return int(h) * 60 + int(m)
        except Exception:
            return 0
    marcos = [(_to_min(s.start_time), _to_min(s.end_time or s.start_time)) for s in sessions if s.start_time]
    marcos.sort()
    maior_gap, gap_inicio = 0, None
    limite_inicio, limite_fim = 7 * 60, 23 * 60
    anterior = limite_inicio
    for ini, fim in marcos:
        if ini > anterior and anterior >= limite_inicio and ini <= limite_fim:
            if ini - anterior > maior_gap:
                maior_gap, gap_inicio = ini - anterior, anterior
        anterior = max(anterior, fim)

    out = []
    for h in habits:
        if h.id in done or not _is_scheduled(h.days, weekday):
            continue
        kind = _kind(h.name)
        razao = None
        if kind == "codigo":
            if code_seconds >= 1800:
                razao = f"{_hm(code_seconds)} de código hoje"
            elif dev_seconds >= 1800:
                razao = f"{_hm(dev_seconds)} no editor hoje"
        elif kind == "treino":
            ev = next((e for e in eventos if _kind(e.title or "") == "treino"), None)
            if ev:
                razao = f"tens '{ev.title}' no calendário"
            elif maior_gap >= 60 and gap_inicio is not None:
                razao = f"{_hm(maior_gap * 60)} longe do PC a partir das {gap_inicio // 60:02d}:{gap_inicio % 60:02d}"
        elif kind == "leitura" and reading_seconds >= 900:
            razao = f"{_hm(reading_seconds)} a ler no telemóvel"

        if razao:
            out.append({"habit_id": h.id, "name": h.name, "icon": h.icon, "reason": razao})
    return out
