"""Derived analytics over app usage data: focus score, correlations, transitions, deep work, best hours."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import date, datetime, timedelta, time
from typing import Optional
from collections import defaultdict
from statistics import mean

from database import get_db
from models import (
    AppUsageSession, AppCategoryOverride, FlowSession,
    MoodEntry, SleepEntry, LolGame, HabitCompletion, Habit,
)
from app_categories import categorize, CATEGORY_COLORS, CATEGORY_LABELS

router = APIRouter(prefix="/api/app-insights", tags=["App Insights"])


# ── helpers ───────────────────────────────────────────────────────

def _category_for(db: Session, session: AppUsageSession) -> str:
    override = None
    if session.bundle_id:
        override = db.query(AppCategoryOverride).filter(AppCategoryOverride.bundle_id == session.bundle_id).first()
    if not override and session.app_name:
        override = db.query(AppCategoryOverride).filter(AppCategoryOverride.app_name == session.app_name).first()
    if override:
        return override.category
    return categorize(session.bundle_id, session.app_name)


PRODUCTIVE_CATS = {"development", "productivity", "communication"}
DISTRACTION_CATS = {"gaming", "social", "entertainment"}


def _iter_days(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


# ── Focus Score ───────────────────────────────────────────────────

@router.get("/focus-score")
def focus_score(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db),
):
    """
    Score 0–100 per day. Components:
      + time-in-productive-category        (40 pts)
      + long uninterrupted blocks (>25min) (30 pts)
      + low context switching              (20 pts)
      - distractions during Flow           (10 pts)

    Returns daily series + aggregate.
    """
    sessions = db.query(AppUsageSession).filter(
        AppUsageSession.date >= start_date,
        AppUsageSession.date <= end_date,
    ).order_by(AppUsageSession.start_time.asc()).all()

    by_day: dict[date, list[AppUsageSession]] = defaultdict(list)
    for s in sessions:
        by_day[s.date].append(s)

    # Pre-categorize
    cats: dict[int, str] = {s.id: _category_for(db, s) for s in sessions}

    flows = db.query(FlowSession).filter(
        FlowSession.date >= start_date,
        FlowSession.date <= end_date,
    ).all()
    flows_by_day: dict[date, list[FlowSession]] = defaultdict(list)
    for f in flows:
        flows_by_day[f.date].append(f)

    series = []
    for d in _iter_days(start_date, end_date):
        day_sessions = by_day.get(d, [])
        total = sum(s.duration_seconds for s in day_sessions)
        if total == 0:
            series.append({
                "date": d.isoformat(), "score": None, "total_seconds": 0,
                "productive_seconds": 0, "distraction_seconds": 0,
                "deep_work_blocks": 0, "context_switches": 0, "flow_distractions": 0,
            })
            continue

        productive = sum(s.duration_seconds for s in day_sessions if cats[s.id] in PRODUCTIVE_CATS)
        distraction = sum(s.duration_seconds for s in day_sessions if cats[s.id] in DISTRACTION_CATS)

        # Deep work: consecutive sessions same category productive, total >= 25min, gap <= 60s
        deep_blocks = 0
        if day_sessions:
            block_start = day_sessions[0].start_time
            block_end = day_sessions[0].end_time
            block_cat = cats[day_sessions[0].id]
            for s in day_sessions[1:]:
                gap = (s.start_time - block_end).total_seconds()
                if cats[s.id] == block_cat and gap <= 60:
                    block_end = s.end_time
                else:
                    if block_cat in PRODUCTIVE_CATS and (block_end - block_start).total_seconds() >= 25 * 60:
                        deep_blocks += 1
                    block_start = s.start_time
                    block_end = s.end_time
                    block_cat = cats[s.id]
            # final
            if block_cat in PRODUCTIVE_CATS and (block_end - block_start).total_seconds() >= 25 * 60:
                deep_blocks += 1

        # Context switches (different app in adjacent sessions)
        switches = sum(
            1 for i in range(1, len(day_sessions)) if day_sessions[i].app_name != day_sessions[i - 1].app_name
        )
        hours = max(1, total / 3600)
        switches_per_hour = switches / hours

        # Flow distractions: time in distraction cats during any flow session
        flow_distraction_seconds = 0
        for f in flows_by_day.get(d, []):
            if not f.start_time or not f.end_time:
                continue
            try:
                fs = datetime.combine(f.date, datetime.strptime(f.start_time, "%H:%M").time())
                fe = datetime.combine(f.date, datetime.strptime(f.end_time, "%H:%M").time())
            except ValueError:
                continue
            for s in day_sessions:
                if cats[s.id] not in DISTRACTION_CATS:
                    continue
                if s.end_time < fs or s.start_time > fe:
                    continue
                ov_start = max(s.start_time, fs)
                ov_end = min(s.end_time, fe)
                flow_distraction_seconds += max(0, int((ov_end - ov_start).total_seconds()))

        # Scoring
        prod_pts = min(40, (productive / total) * 40)
        deep_pts = min(30, deep_blocks * 10)          # 3 blocks = full
        ctx_pts = max(0, 20 - switches_per_hour * 2)  # 0 switches = 20, 10/h = 0
        flow_penalty = min(10, flow_distraction_seconds / 60)  # 1 pt per minute, capped at 10
        score = round(prod_pts + deep_pts + ctx_pts - flow_penalty, 1)
        score = max(0.0, min(100.0, score))

        series.append({
            "date": d.isoformat(),
            "score": score,
            "total_seconds": total,
            "productive_seconds": productive,
            "distraction_seconds": distraction,
            "deep_work_blocks": deep_blocks,
            "context_switches": switches,
            "switches_per_hour": round(switches_per_hour, 1),
            "flow_distractions": flow_distraction_seconds,
        })

    scored = [d for d in series if d["score"] is not None]
    avg = round(mean(d["score"] for d in scored), 1) if scored else None
    return {
        "average": avg,
        "days_scored": len(scored),
        "best_day": max(scored, key=lambda d: d["score"]) if scored else None,
        "worst_day": min(scored, key=lambda d: d["score"]) if scored else None,
        "series": series,
    }


# ── Deep work heatmap (hour-of-day × productivity) ────────────────

@router.get("/deep-work")
def deep_work(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    end = date.today()
    start = end - timedelta(days=days - 1)
    sessions = db.query(AppUsageSession).filter(
        AppUsageSession.date >= start, AppUsageSession.date <= end,
    ).all()

    # hour → (productive_sec, distraction_sec, switches)
    prod_by_hour = [0] * 24
    dist_by_hour = [0] * 24
    total_by_hour = [0] * 24
    prev_app_by_hour: dict[int, str] = {}
    switches_by_hour = [0] * 24

    for s in sorted(sessions, key=lambda x: x.start_time):
        cat = _category_for(db, s)
        remaining = s.duration_seconds
        cursor = s.start_time
        while remaining > 0:
            h = cursor.hour
            hour_end = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            chunk = min(remaining, int((hour_end - cursor).total_seconds()))
            total_by_hour[h] += chunk
            if cat in PRODUCTIVE_CATS:
                prod_by_hour[h] += chunk
            elif cat in DISTRACTION_CATS:
                dist_by_hour[h] += chunk
            if prev_app_by_hour.get(h) and prev_app_by_hour[h] != s.app_name:
                switches_by_hour[h] += 1
            prev_app_by_hour[h] = s.app_name
            remaining -= chunk
            cursor = hour_end

    hours = []
    for h in range(24):
        total = total_by_hour[h]
        if total == 0:
            hours.append({"hour": h, "score": None, "productive_seconds": 0, "distraction_seconds": 0, "total_seconds": 0})
            continue
        ratio = prod_by_hour[h] / total
        # score = productivity ratio (0-100) weighted down by switches
        sw_penalty = min(30, switches_by_hour[h] / max(1, total / 3600) * 3)
        score = max(0.0, min(100.0, ratio * 100 - sw_penalty))
        hours.append({
            "hour": h, "score": round(score, 1),
            "productive_seconds": prod_by_hour[h],
            "distraction_seconds": dist_by_hour[h],
            "total_seconds": total,
        })

    scored = [h for h in hours if h["score"] is not None]
    best = max(scored, key=lambda h: h["score"]) if scored else None
    worst = min(scored, key=lambda h: h["score"]) if scored else None
    return {"hours": hours, "best_hour": best, "worst_hour": worst, "window_days": days}


# ── Transitions (bigrams) ─────────────────────────────────────────

@router.get("/transitions")
def transitions(days: int = Query(30, ge=1, le=365), limit: int = Query(20), db: Session = Depends(get_db)):
    """Most frequent app→app transitions."""
    end = date.today()
    start = end - timedelta(days=days - 1)
    sessions = db.query(AppUsageSession).filter(
        AppUsageSession.date >= start, AppUsageSession.date <= end,
    ).order_by(AppUsageSession.start_time.asc()).all()

    bigrams: dict[tuple[str, str], int] = defaultdict(int)
    from_totals: dict[str, int] = defaultdict(int)
    prev: AppUsageSession | None = None
    for s in sessions:
        if prev and prev.app_name != s.app_name:
            # Only count adjacent transitions if gap < 5 min (same "work context")
            gap = (s.start_time - prev.end_time).total_seconds()
            if gap < 300:
                bigrams[(prev.app_name, s.app_name)] += 1
                from_totals[prev.app_name] += 1
        prev = s

    rows = sorted(
        [
            {
                "from_app": f, "to_app": t, "count": c,
                "pct_from": round(c / max(1, from_totals[f]) * 100, 1),
            }
            for (f, t), c in bigrams.items()
        ],
        key=lambda r: r["count"], reverse=True,
    )[:limit]
    return {"window_days": days, "transitions": rows}


# ── First distraction after starting work ─────────────────────────

@router.get("/first-distraction")
def first_distraction(days: int = Query(30), db: Session = Depends(get_db)):
    """Median time from first productive session of the day until first distraction session."""
    end = date.today()
    start = end - timedelta(days=days - 1)
    sessions = db.query(AppUsageSession).filter(
        AppUsageSession.date >= start, AppUsageSession.date <= end,
    ).order_by(AppUsageSession.start_time.asc()).all()

    by_day: dict[date, list[AppUsageSession]] = defaultdict(list)
    for s in sessions:
        by_day[s.date].append(s)

    times = []
    for d, day_sessions in by_day.items():
        first_prod = None
        for s in day_sessions:
            cat = _category_for(db, s)
            if cat in PRODUCTIVE_CATS:
                first_prod = s
                break
        if not first_prod:
            continue
        for s in day_sessions:
            if s.start_time <= first_prod.start_time:
                continue
            cat = _category_for(db, s)
            if cat in DISTRACTION_CATS:
                minutes = (s.start_time - first_prod.start_time).total_seconds() / 60
                times.append(minutes)
                break

    if not times:
        return {"samples": 0, "median_minutes": None, "mean_minutes": None}
    sorted_t = sorted(times)
    median = sorted_t[len(sorted_t) // 2]
    return {
        "samples": len(times),
        "median_minutes": round(median, 1),
        "mean_minutes": round(mean(times), 1),
    }


# ── Cross-feature correlations ────────────────────────────────────

def _day_totals(db: Session, start: date, end: date) -> dict[date, dict[str, int]]:
    """For each day in range: total and per-category seconds."""
    sessions = db.query(AppUsageSession).filter(
        AppUsageSession.date >= start, AppUsageSession.date <= end,
    ).all()
    totals: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for s in sessions:
        totals[s.date]["total"] += s.duration_seconds
        totals[s.date][_category_for(db, s)] += s.duration_seconds
    return {d: dict(v) for d, v in totals.items()}


@router.get("/correlations")
def correlations(days: int = Query(30, ge=7, le=365), db: Session = Depends(get_db)):
    end = date.today()
    start = end - timedelta(days=days - 1)
    day_totals = _day_totals(db, start, end)

    def splits(category: str, hours_threshold: float):
        """Return (high_days, low_days) lists of dates where usage in category > threshold vs not."""
        high, low = [], []
        for d in _iter_days(start, end):
            sec = day_totals.get(d, {}).get(category, 0)
            (high if sec / 3600 >= hours_threshold else low).append(d)
        return high, low

    insights: list[dict] = []

    # --- Mood ---
    moods = db.query(MoodEntry).filter(MoodEntry.date >= start, MoodEntry.date <= end).all()
    mood_map = {m.date: m.mood for m in moods}

    for cat, label, threshold in [
        ("development", "Desenvolvimento", 3),
        ("gaming", "Gaming", 2),
        ("social", "Social", 1.5),
    ]:
        high, low = splits(cat, threshold)
        high_moods = [mood_map[d] for d in high if d in mood_map]
        low_moods = [mood_map[d] for d in low if d in mood_map]
        if len(high_moods) >= 3 and len(low_moods) >= 3:
            diff = round(mean(high_moods) - mean(low_moods), 2)
            if abs(diff) >= 0.2:
                direction = "melhor" if diff > 0 else "pior"
                insights.append({
                    "kind": "mood",
                    "text": f"Mood médio em dias com > {threshold}h de {label.lower()}: {mean(high_moods):.2f} ({direction} por {abs(diff)} que restantes dias)",
                    "metric": round(mean(high_moods), 2),
                    "baseline": round(mean(low_moods), 2),
                    "delta": diff,
                    "samples_high": len(high_moods),
                    "samples_low": len(low_moods),
                    "category": cat,
                })

    # --- Sleep ---
    sleep = db.query(SleepEntry).filter(SleepEntry.date >= start, SleepEntry.date <= end).all()
    sleep_map = {s.date: s.hours for s in sleep if s.hours}

    for cat, label, threshold in [
        ("gaming", "Gaming", 2),
        ("entertainment", "Entretenimento", 2),
    ]:
        high, low = splits(cat, threshold)
        high_sleep = [sleep_map[d] for d in high if d in sleep_map]
        low_sleep = [sleep_map[d] for d in low if d in sleep_map]
        if len(high_sleep) >= 3 and len(low_sleep) >= 3:
            diff = round(mean(high_sleep) - mean(low_sleep), 2)
            if abs(diff) >= 0.3:
                direction = "mais" if diff > 0 else "menos"
                insights.append({
                    "kind": "sleep",
                    "text": f"Dormiste em média {abs(diff)}h {direction} em dias com > {threshold}h de {label.lower()}",
                    "metric": round(mean(high_sleep), 2),
                    "baseline": round(mean(low_sleep), 2),
                    "delta": diff,
                    "samples_high": len(high_sleep),
                    "samples_low": len(low_sleep),
                    "category": cat,
                })

    # --- Late-night gaming → sleep ---
    late_gaming_days: set[date] = set()
    sessions = db.query(AppUsageSession).filter(
        AppUsageSession.date >= start, AppUsageSession.date <= end,
    ).all()
    for s in sessions:
        if _category_for(db, s) == "gaming" and s.start_time.hour >= 23:
            late_gaming_days.add(s.date)
    non_late_days = set(_iter_days(start, end)) - late_gaming_days
    late_sleep = [sleep_map[d] for d in late_gaming_days if d in sleep_map]
    other_sleep = [sleep_map[d] for d in non_late_days if d in sleep_map]
    if len(late_sleep) >= 3 and len(other_sleep) >= 3:
        diff = round(mean(late_sleep) - mean(other_sleep), 2)
        if abs(diff) >= 0.3:
            direction = "menos" if diff < 0 else "mais"
            insights.append({
                "kind": "sleep_late_gaming",
                "text": f"Em noites com gaming ≥ 23h dormiste {abs(diff)}h {direction} em média",
                "metric": round(mean(late_sleep), 2),
                "baseline": round(mean(other_sleep), 2),
                "delta": diff,
                "samples_high": len(late_sleep),
                "samples_low": len(other_sleep),
            })

    # --- LoL winrate vs pre-game screen time ---
    lol_games = db.query(LolGame).filter(LolGame.date >= start, LolGame.date <= end).all()
    if lol_games:
        # Need game hour to slice the day. If missing, skip.
        cats_sessions = [(s.start_time, s.end_time, _category_for(db, s)) for s in sessions]
        buckets = {"focused_pre": [], "distracted_pre": []}
        for g in lol_games:
            if g.game_hour is None or g.won is None:
                continue
            game_dt = datetime.combine(g.date, time(g.game_hour, 0))
            window_start = game_dt - timedelta(hours=3)
            prod = dist = 0
            for s_start, s_end, s_cat in cats_sessions:
                if s_end < window_start or s_start > game_dt:
                    continue
                ov_start = max(s_start, window_start)
                ov_end = min(s_end, game_dt)
                sec = max(0, int((ov_end - ov_start).total_seconds()))
                if s_cat in PRODUCTIVE_CATS:
                    prod += sec
                elif s_cat in DISTRACTION_CATS:
                    dist += sec
            if prod > dist:
                buckets["focused_pre"].append(g.won)
            else:
                buckets["distracted_pre"].append(g.won)

        def wr(games: list[bool]) -> float | None:
            return round(sum(1 for w in games if w) / len(games) * 100, 1) if games else None

        fwr, dwr = wr(buckets["focused_pre"]), wr(buckets["distracted_pre"])
        if fwr is not None and dwr is not None and len(buckets["focused_pre"]) >= 3 and len(buckets["distracted_pre"]) >= 3:
            diff = round(fwr - dwr, 1)
            if abs(diff) >= 5:
                insights.append({
                    "kind": "lol_winrate",
                    "text": f"Winrate quando as 3h antes do jogo foram + produtivas: {fwr}% vs {dwr}% quando foram + distração ({'+' if diff > 0 else ''}{diff}pp)",
                    "metric": fwr,
                    "baseline": dwr,
                    "delta": diff,
                    "samples_high": len(buckets["focused_pre"]),
                    "samples_low": len(buckets["distracted_pre"]),
                })

    # --- Habit completion ↔ productive time ---
    habits = db.query(Habit).filter(Habit.active == True).all()
    completions = db.query(HabitCompletion).filter(
        HabitCompletion.date >= start, HabitCompletion.date <= end,
    ).all()
    comp_by_habit: dict[int, set[date]] = defaultdict(set)
    for c in completions:
        comp_by_habit[c.habit_id].add(c.date)

    for h in habits:
        done_days = comp_by_habit.get(h.id, set())
        not_done_days = set(_iter_days(start, end)) - done_days
        done_prod = [day_totals.get(d, {}).get("development", 0) / 3600 for d in done_days if d in day_totals]
        nd_prod = [day_totals.get(d, {}).get("development", 0) / 3600 for d in not_done_days if d in day_totals]
        if len(done_prod) >= 3 and len(nd_prod) >= 3:
            diff = round(mean(done_prod) - mean(nd_prod), 2)
            if abs(diff) >= 0.5:
                direction = "mais" if diff > 0 else "menos"
                insights.append({
                    "kind": "habit",
                    "text": f"Dias com '{h.name}' ✓: {abs(diff)}h {direction} de desenvolvimento (vs dias sem)",
                    "metric": round(mean(done_prod), 2),
                    "baseline": round(mean(nd_prod), 2),
                    "delta": diff,
                    "samples_high": len(done_prod),
                    "samples_low": len(nd_prod),
                    "habit_name": h.name,
                })

    return {"window_days": days, "insights": insights}


# ── Current distraction (for live alert in Flow) ──────────────────

@router.get("/current-state")
def current_state(db: Session = Depends(get_db)):
    """Used by the frontend to decide if a distraction toast should fire during a live Flow."""
    last = db.query(AppUsageSession).order_by(AppUsageSession.end_time.desc()).first()
    now = datetime.now()
    if not last:
        return {"has_data": False}
    seconds_since = (now - last.end_time).total_seconds()
    running = 0 <= seconds_since < 60
    category = _category_for(db, last) if last else None

    # Active flow?
    today = date.today()
    now_hm = now.strftime("%H:%M")
    active_flow = db.query(FlowSession).filter(
        FlowSession.date == today,
        FlowSession.start_time <= now_hm,
        (FlowSession.end_time == None) | (FlowSession.end_time >= now_hm),
    ).order_by(FlowSession.start_time.desc()).first()

    return {
        "has_data": True,
        "tracker_running": running,
        "current_app": last.app_name if running else None,
        "current_category": category if running else None,
        "is_distraction": running and category in DISTRACTION_CATS,
        "active_flow": {
            "id": active_flow.id,
            "name": active_flow.preset_name,
            "start_time": active_flow.start_time,
            "end_time": active_flow.end_time,
        } if active_flow else None,
    }
