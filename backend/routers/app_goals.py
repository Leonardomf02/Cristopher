"""Goals per category (min/max daily targets) + progress + streaks."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import date, timedelta
from collections import defaultdict

from database import get_db
from models import AppUsageSession, AppUsageGoal, AppCategoryOverride
from schemas import AppUsageGoalCreate, AppUsageGoalUpdate, AppUsageGoalOut
from app_categories import categorize, CATEGORY_COLORS, CATEGORY_LABELS, categorize_browser_title, is_browser

router = APIRouter(prefix="/api/app-goals", tags=["App Goals"])


_RULES_CACHE: dict = {"at": 0.0, "map": {}}


def _learned_rules(db: Session) -> dict[str, str]:
    """Regras título→categoria aprendidas (IA/utilizador), com cache de 60s."""
    import time as _t
    from models import BrowserTitleRule
    if _t.time() - _RULES_CACHE["at"] < 60:
        return _RULES_CACHE["map"]
    try:
        m = {r.pattern: r.category for r in db.query(BrowserTitleRule).all()}
    except Exception:
        m = {}
    _RULES_CACHE.update({"at": _t.time(), "map": m})
    return m


_OVERRIDES_CACHE: dict = {"at": 0.0, "bundles": {}, "apps": {}}


def _overrides(db: Session) -> tuple[dict, dict]:
    """Categorias definidas à mão, em memória (60s) — antes era uma consulta à
    base por cada sessão."""
    import time as _t
    if _t.time() - _OVERRIDES_CACHE["at"] < 60:
        return _OVERRIDES_CACHE["bundles"], _OVERRIDES_CACHE["apps"]
    bundles: dict[str, str] = {}
    apps: dict[str, str] = {}
    try:
        for o in db.query(AppCategoryOverride).all():
            if o.bundle_id:
                bundles[o.bundle_id] = o.category
            if o.app_name:
                apps[o.app_name] = o.category
    except Exception:
        pass
    _OVERRIDES_CACHE.update({"at": _t.time(), "bundles": bundles, "apps": apps})
    return bundles, apps


def _category_for(db: Session, session: AppUsageSession) -> str:
    bundles, apps = _overrides(db)
    if session.bundle_id and session.bundle_id in bundles:
        return bundles[session.bundle_id]
    if session.app_name and session.app_name in apps:
        return apps[session.app_name]
    # Browser: 183h/mês caíam todas em "browser". O título diz o site, e o site
    # diz se aquilo era trabalho, redes ou streaming.
    if is_browser(session.bundle_id, session.app_name):
        pelo_titulo = categorize_browser_title(getattr(session, "window_title", None), _learned_rules(db), getattr(session, "domain", None))
        if pelo_titulo:
            return pelo_titulo
    return categorize(session.bundle_id, session.app_name)


@router.get("/", response_model=list[AppUsageGoalOut])
def list_goals(db: Session = Depends(get_db)):
    return db.query(AppUsageGoal).order_by(AppUsageGoal.category).all()


@router.post("/", response_model=AppUsageGoalOut)
def create_goal(data: AppUsageGoalCreate, db: Session = Depends(get_db)):
    if data.direction not in ("min", "max"):
        raise HTTPException(status_code=400, detail="direction must be 'min' or 'max'")
    if data.category not in CATEGORY_LABELS:
        raise HTTPException(status_code=400, detail="invalid category")
    existing = db.query(AppUsageGoal).filter(
        AppUsageGoal.category == data.category,
        AppUsageGoal.direction == data.direction,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="goal already exists for this category+direction")
    goal = AppUsageGoal(**data.model_dump())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


@router.put("/{goal_id}", response_model=AppUsageGoalOut)
def update_goal(goal_id: int, data: AppUsageGoalUpdate, db: Session = Depends(get_db)):
    goal = db.query(AppUsageGoal).filter(AppUsageGoal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(goal, k, v)
    db.commit()
    db.refresh(goal)
    return goal


@router.delete("/{goal_id}")
def delete_goal(goal_id: int, db: Session = Depends(get_db)):
    goal = db.query(AppUsageGoal).filter(AppUsageGoal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(goal)
    db.commit()
    return {"ok": True}


def _day_totals_by_category(db: Session, start: date, end: date) -> dict[date, dict[str, int]]:
    sessions = db.query(AppUsageSession).filter(
        AppUsageSession.date >= start, AppUsageSession.date <= end,
    ).all()
    out: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for s in sessions:
        out[s.date][_category_for(db, s)] += s.duration_seconds
    return {d: dict(v) for d, v in out.items()}


def _day_meets_goal(seconds: int, direction: str, target: int) -> bool:
    if direction == "max":
        return seconds <= target
    return seconds >= target


@router.get("/progress")
def goals_progress(
    on_date: date | None = Query(None),
    streak_window_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Progress for today (or `on_date`) + current/best streaks over recent window."""
    today = on_date or date.today()
    goals = db.query(AppUsageGoal).filter(AppUsageGoal.active == True).all()

    if not goals:
        return {"date": today.isoformat(), "goals": []}

    start = today - timedelta(days=streak_window_days - 1)
    totals = _day_totals_by_category(db, start, today)

    out = []
    for g in goals:
        today_seconds = totals.get(today, {}).get(g.category, 0)
        if g.direction == "max":
            pct = round(min(100, today_seconds / g.target_seconds * 100), 1) if g.target_seconds else 0
            ok = today_seconds <= g.target_seconds
        else:
            pct = round(min(100, today_seconds / g.target_seconds * 100), 1) if g.target_seconds else 0
            ok = today_seconds >= g.target_seconds

        # Current streak (consecutive days ending today that met the goal)
        current_streak = 0
        cur = today
        while cur >= start:
            day_sec = totals.get(cur, {}).get(g.category, 0)
            if _day_meets_goal(day_sec, g.direction, g.target_seconds):
                current_streak += 1
                cur -= timedelta(days=1)
            else:
                break

        # Best streak in the window
        best_streak = 0
        run = 0
        d = start
        while d <= today:
            day_sec = totals.get(d, {}).get(g.category, 0)
            if _day_meets_goal(day_sec, g.direction, g.target_seconds):
                run += 1
                best_streak = max(best_streak, run)
            else:
                run = 0
            d += timedelta(days=1)

        out.append({
            "id": g.id,
            "category": g.category,
            "label": CATEGORY_LABELS.get(g.category, g.category),
            "color": CATEGORY_COLORS.get(g.category, "#9CA3AF"),
            "direction": g.direction,
            "target_seconds": g.target_seconds,
            "today_seconds": today_seconds,
            "percentage": pct,
            "on_track": ok,
            "current_streak": current_streak,
            "best_streak": best_streak,
        })
    return {"date": today.isoformat(), "goals": out}
