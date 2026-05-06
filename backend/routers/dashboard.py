from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc
from datetime import date, timedelta
from typing import Optional

from database import get_db
from models import (
    Event, Expense, LolGame, SleepEntry, FlowSession, Habit, HabitCompletion,
    MoodEntry, DailyJournal,
)

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


def _week_range(week_offset: int = 0) -> tuple[date, date]:
    """Get Monday–Sunday for a given week offset (0=this week, -1=last week)."""
    today = date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _is_scheduled(days: str, weekday: int) -> bool:
    if days == "daily":
        return True
    if days == "weekdays":
        return weekday < 5
    try:
        allowed = {int(d.strip()) for d in days.split(",")}
        return weekday in allowed
    except ValueError:
        return True


@router.get("/weekly-review")
def weekly_review(
    week_offset: int = Query(0, ge=-52, le=0),
    db: Session = Depends(get_db),
):
    """
    Aggregate weekly stats for the report card.
    week_offset=0 is current week, -1 is last week, etc.
    """
    monday, sunday = _week_range(week_offset)
    prev_monday, prev_sunday = _week_range(week_offset - 1)

    # ── Events ───────────────────────────────────────────────────
    events = db.query(Event).filter(Event.date >= monday, Event.date <= sunday).all()
    events_total = len(events)
    events_completed = sum(1 for e in events if e.completed)

    # ── Expenses ─────────────────────────────────────────────────
    expenses = db.query(Expense).filter(Expense.date >= monday, Expense.date <= sunday).all()
    expenses_total = round(sum(e.amount for e in expenses), 2)
    expenses_by_cat: dict = {}
    for e in expenses:
        cat = e.category or "other"
        expenses_by_cat[cat] = round(expenses_by_cat.get(cat, 0) + e.amount, 2)

    # Previous week for comparison
    prev_expenses = db.query(Expense).filter(Expense.date >= prev_monday, Expense.date <= prev_sunday).all()
    prev_expenses_total = round(sum(e.amount for e in prev_expenses), 2)

    # ── LoL Games ────────────────────────────────────────────────
    games = db.query(LolGame).filter(LolGame.date >= monday, LolGame.date <= sunday).all()
    games_total = len(games)
    games_won = sum(1 for g in games if g.won)
    games_wr = round(games_won / games_total * 100, 1) if games_total > 0 else 0

    prev_games = db.query(LolGame).filter(LolGame.date >= prev_monday, LolGame.date <= prev_sunday).all()
    prev_wr = round(sum(1 for g in prev_games if g.won) / len(prev_games) * 100, 1) if prev_games else 0

    # ── Sleep ────────────────────────────────────────────────────
    sleep_entries = db.query(SleepEntry).filter(
        SleepEntry.date >= monday, SleepEntry.date <= sunday
    ).all()
    sleep_avg = round(sum(s.hours for s in sleep_entries) / len(sleep_entries), 1) if sleep_entries else 0
    sleep_quality_avg = 0
    quality_list = [s.quality for s in sleep_entries if s.quality]
    if quality_list:
        sleep_quality_avg = round(sum(quality_list) / len(quality_list), 1)

    prev_sleep = db.query(SleepEntry).filter(
        SleepEntry.date >= prev_monday, SleepEntry.date <= prev_sunday
    ).all()
    prev_sleep_avg = round(sum(s.hours for s in prev_sleep) / len(prev_sleep), 1) if prev_sleep else 0

    # ── Flow Sessions ────────────────────────────────────────────
    flow_sessions = db.query(FlowSession).filter(
        FlowSession.date >= monday, FlowSession.date <= sunday
    ).all()
    flow_total_min = sum(s.actual_minutes or s.planned_minutes for s in flow_sessions)
    flow_total_hours = round(flow_total_min / 60, 1)
    flow_sessions_count = len(flow_sessions)

    prev_flow = db.query(FlowSession).filter(
        FlowSession.date >= prev_monday, FlowSession.date <= prev_sunday
    ).all()
    prev_flow_hours = round(sum(s.actual_minutes or s.planned_minutes for s in prev_flow) / 60, 1)

    # By preset
    flow_by_preset: dict = {}
    for s in flow_sessions:
        name = s.preset_name
        if name not in flow_by_preset:
            flow_by_preset[name] = {"minutes": 0, "sessions": 0, "color": s.color}
        flow_by_preset[name]["minutes"] += s.actual_minutes or s.planned_minutes
        flow_by_preset[name]["sessions"] += 1

    # ── Habits ───────────────────────────────────────────────────
    habits = db.query(Habit).filter(Habit.active == True).all()
    completions = db.query(HabitCompletion).filter(
        HabitCompletion.date >= monday, HabitCompletion.date <= sunday
    ).all()
    completion_set = {(c.habit_id, str(c.date)) for c in completions}

    # Count scheduled slots and completed
    total_scheduled = 0
    total_completed = 0
    habit_stats = []
    for h in habits:
        scheduled = 0
        completed = 0
        d = monday
        while d <= min(sunday, date.today()):
            if _is_scheduled(h.days, d.weekday()):
                scheduled += 1
                if (h.id, str(d)) in completion_set:
                    completed += 1
            d += timedelta(days=1)
        total_scheduled += scheduled
        total_completed += completed
        if scheduled > 0:
            habit_stats.append({
                "name": h.name,
                "icon": h.icon,
                "color": h.color,
                "scheduled": scheduled,
                "completed": completed,
                "rate": round(completed / scheduled * 100, 1),
            })

    habits_rate = round(total_completed / total_scheduled * 100, 1) if total_scheduled > 0 else 0

    # ── Mood (average for the week) ──────────────────────────────
    moods = db.query(MoodEntry).filter(
        MoodEntry.date >= monday, MoodEntry.date <= sunday
    ).all()
    mood_avg = round(sum(m.mood for m in moods) / len(moods), 1) if moods else None
    mood_entries = [{"date": str(m.date), "mood": m.mood, "note": m.note} for m in moods]

    return {
        "week_start": str(monday),
        "week_end": str(sunday),
        "events": {
            "total": events_total,
            "completed": events_completed,
            "rate": round(events_completed / events_total * 100, 1) if events_total > 0 else 0,
        },
        "expenses": {
            "total": expenses_total,
            "prev_total": prev_expenses_total,
            "delta": round(expenses_total - prev_expenses_total, 2),
            "by_category": expenses_by_cat,
        },
        "lol": {
            "games": games_total,
            "wins": games_won,
            "losses": games_total - games_won,
            "winrate": games_wr,
            "prev_winrate": prev_wr,
        },
        "sleep": {
            "avg_hours": sleep_avg,
            "avg_quality": sleep_quality_avg,
            "entries": len(sleep_entries),
            "prev_avg_hours": prev_sleep_avg,
        },
        "flow": {
            "total_hours": flow_total_hours,
            "sessions": flow_sessions_count,
            "prev_total_hours": prev_flow_hours,
            "by_preset": flow_by_preset,
        },
        "habits": {
            "total_scheduled": total_scheduled,
            "total_completed": total_completed,
            "rate": habits_rate,
            "by_habit": sorted(habit_stats, key=lambda x: x["rate"], reverse=True),
        },
        "mood": {
            "average": mood_avg,
            "entries": mood_entries,
        },
    }


@router.get("/correlations")
def correlations(db: Session = Depends(get_db)):
    """
    Cross-data correlations: sleep vs LoL WR, sleep vs flow, expenses by weekday.
    Uses last 90 days of data.
    """
    cutoff = date.today() - timedelta(days=90)

    # Get all sleep entries
    sleep_entries = db.query(SleepEntry).filter(SleepEntry.date >= cutoff).all()
    sleep_by_date = {str(s.date): s.hours for s in sleep_entries}

    # Get all LoL games
    games = db.query(LolGame).filter(LolGame.date >= cutoff).all()

    # Get all flow sessions
    flow_sessions = db.query(FlowSession).filter(FlowSession.date >= cutoff).all()

    # Get all expenses
    expenses = db.query(Expense).filter(Expense.date >= cutoff).all()

    # Get all moods
    moods = db.query(MoodEntry).filter(MoodEntry.date >= cutoff).all()
    mood_by_date = {str(m.date): m.mood for m in moods}

    # ── Sleep vs LoL WR ──────────────────────────────────────────
    good_sleep_games = []  # games on days with >=7h sleep
    bad_sleep_games = []   # games on days with <6h sleep
    mid_sleep_games = []   # 6-7h

    for g in games:
        sleep_h = sleep_by_date.get(str(g.date))
        if sleep_h is None:
            continue
        if sleep_h >= 7:
            good_sleep_games.append(g.won)
        elif sleep_h < 6:
            bad_sleep_games.append(g.won)
        else:
            mid_sleep_games.append(g.won)

    def wr(lst):
        if not lst:
            return None
        return round(sum(1 for w in lst if w) / len(lst) * 100, 1)

    # ── Sleep vs Flow productivity ───────────────────────────────
    good_sleep_flow = []
    bad_sleep_flow = []
    for s in flow_sessions:
        sleep_h = sleep_by_date.get(str(s.date))
        if sleep_h is None:
            continue
        mins = s.actual_minutes or s.planned_minutes
        if sleep_h >= 7:
            good_sleep_flow.append(mins)
        elif sleep_h < 6:
            bad_sleep_flow.append(mins)

    # ── Expenses by day of week ──────────────────────────────────
    day_names = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    expenses_by_weekday = [0.0] * 7
    expenses_count_by_weekday = [0] * 7
    for e in expenses:
        wd = e.date.weekday()
        expenses_by_weekday[wd] += e.amount
        expenses_count_by_weekday[wd] += 1

    # ── Mood vs sleep ────────────────────────────────────────────
    mood_good_sleep = []
    mood_bad_sleep = []
    for m in moods:
        sleep_h = sleep_by_date.get(str(m.date))
        if sleep_h is None:
            continue
        if sleep_h >= 7:
            mood_good_sleep.append(m.mood)
        elif sleep_h < 6:
            mood_bad_sleep.append(m.mood)

    # ── Mood vs LoL (did playing affect mood?) ───────────────────
    game_dates = {str(g.date) for g in games}
    mood_game_days = [m.mood for m in moods if str(m.date) in game_dates]
    mood_no_game_days = [m.mood for m in moods if str(m.date) not in game_dates]

    def avg(lst):
        if not lst:
            return None
        return round(sum(lst) / len(lst), 2)

    return {
        "sleep_vs_lol": {
            "good_sleep_wr": wr(good_sleep_games),
            "good_sleep_games": len(good_sleep_games),
            "mid_sleep_wr": wr(mid_sleep_games),
            "mid_sleep_games": len(mid_sleep_games),
            "bad_sleep_wr": wr(bad_sleep_games),
            "bad_sleep_games": len(bad_sleep_games),
        },
        "sleep_vs_flow": {
            "good_sleep_avg_min": round(avg(good_sleep_flow) or 0, 1),
            "good_sleep_sessions": len(good_sleep_flow),
            "bad_sleep_avg_min": round(avg(bad_sleep_flow) or 0, 1),
            "bad_sleep_sessions": len(bad_sleep_flow),
        },
        "expenses_by_weekday": [
            {
                "day": day_names[i],
                "total": round(expenses_by_weekday[i], 2),
                "count": expenses_count_by_weekday[i],
                "avg": round(expenses_by_weekday[i] / max(expenses_count_by_weekday[i], 1), 2),
            }
            for i in range(7)
        ],
        "mood_vs_sleep": {
            "good_sleep_mood": avg(mood_good_sleep),
            "bad_sleep_mood": avg(mood_bad_sleep),
        },
        "mood_vs_gaming": {
            "game_day_mood": avg(mood_game_days),
            "no_game_mood": avg(mood_no_game_days),
        },
    }
