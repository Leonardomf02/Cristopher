"""WakaTime coding-time stats.

Pulls per-project coding time from the WakaTime API and caches it locally in
`waka_project_days`, so the dashboard keeps unlimited history even though the
free WakaTime plan only exposes the last ~14 days.

Works with WakaTime cloud (https://wakatime.com/api/v1) or any compatible
backend (e.g. self-hosted Wakapi) — just set WAKATIME_API_URL/WAKATIME_API_KEY.
"""

import base64
import logging
import os
from datetime import date as date_type, datetime, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import WakaProjectDay, WakaDayMetrics, WakaProjectDayMetrics

router = APIRouter(prefix="/api/wakatime", tags=["WakaTime"])
logger = logging.getLogger(__name__)

WAKATIME_API_URL = os.getenv("WAKATIME_API_URL", "https://wakatime.com/api/v1").rstrip("/")
WAKATIME_API_KEY = os.getenv("WAKATIME_API_KEY", "")

# WakaTime free plan only serves the last 14 days of summaries.
MAX_FETCH_DAYS = 14
# Don't hit the API more than once per this window when serving summaries.
_SYNC_TTL_SECONDS = 600
_last_sync_at: Optional[datetime] = None


def _is_configured() -> bool:
    return bool(WAKATIME_API_KEY)


def _auth_header() -> dict:
    token = base64.b64encode(WAKATIME_API_KEY.encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _fetch_summaries(start: date_type, end: date_type) -> Optional[list[dict]]:
    """Return WakaTime summaries (one entry per day) or None on failure."""
    url = f"{WAKATIME_API_URL}/users/current/summaries"
    params = {"start": start.isoformat(), "end": end.isoformat()}
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(url, params=params, headers=_auth_header())
            if r.status_code != 200:
                logger.warning(f"WakaTime summaries HTTP {r.status_code}: {r.text[:200]}")
                return None
            return r.json().get("data", [])
    except (httpx.HTTPError, ValueError) as e:
        logger.warning(f"WakaTime summaries failed: {e}")
        return None


# Which WakaTime summary arrays we cache, mapped to our `kind`.
_KINDS = {
    "projects": "project", "languages": "language", "editors": "editor",
    "operating_systems": "os", "categories": "category", "machines": "machine",
    "dependencies": "dependency",
}


def _agent_lines_total(value) -> int:
    """ai_agent_line_changes is a {agent: lines} dict (or sometimes a plain int)."""
    if isinstance(value, dict):
        return int(sum(v or 0 for v in value.values()))
    return int(value or 0)


def _upsert_day(db: Session, day: date_type, entry: dict) -> None:
    """Replace cached rows for `day` with the freshly fetched breakdowns + AI metrics."""
    db.query(WakaProjectDay).filter(WakaProjectDay.day == day).delete()
    for arr_key, kind in _KINDS.items():
        for item in entry.get(arr_key, []) or []:
            name = (item.get("name") or "").strip() or "Desconhecido"
            secs = int(round(item.get("total_seconds", 0) or 0))
            if secs <= 0:
                continue
            db.add(WakaProjectDay(day=day, kind=kind, project=name, seconds=secs))

    gt = entry.get("grand_total", {}) or {}

    # Per-agent line changes (kind="agent"): the `seconds` column holds the line
    # count here, not seconds — it's the only integer value slot we have.
    for agent, lines in (gt.get("ai_agent_line_changes") or {}).items():
        n = int(lines or 0)
        if n <= 0:
            continue
        db.add(WakaProjectDay(day=day, kind="agent", project=(agent or "").strip() or "Desconhecido", seconds=n))

    # Per-project AI metrics for the detailed Projects section.
    db.query(WakaProjectDayMetrics).filter(WakaProjectDayMetrics.day == day).delete()
    for p in entry.get("projects", []) or []:
        name = (p.get("name") or "").strip() or "Desconhecido"
        db.add(WakaProjectDayMetrics(
            day=day,
            project=name,
            seconds=int(round(p.get("total_seconds", 0) or 0)),
            ai_additions=int(p.get("ai_additions", 0) or 0),
            ai_deletions=int(p.get("ai_deletions", 0) or 0),
            human_additions=int(p.get("human_additions", 0) or 0),
            human_deletions=int(p.get("human_deletions", 0) or 0),
            ai_lines=_agent_lines_total(p.get("ai_agent_line_changes")),
            ai_input_tokens=int(p.get("ai_input_tokens", 0) or 0),
            ai_output_tokens=int(p.get("ai_output_tokens", 0) or 0),
            ai_prompt_events=int(p.get("ai_prompt_events_total", 0) or 0),
            ai_prompt_length_sum=int(p.get("ai_prompt_length_sum", 0) or 0),
            ai_sessions=int(p.get("ai_sessions", 0) or 0),
            ai_cost=float(p.get("ai_agent_total_cost", 0) or 0),
        ))

    ai_seconds = 0
    for c in entry.get("categories", []) or []:
        if (c.get("name") or "").lower() == "ai coding":
            ai_seconds = int(round(c.get("total_seconds", 0) or 0))
            break
    agent_lines_total = _agent_lines_total(gt.get("ai_agent_line_changes"))

    db.query(WakaDayMetrics).filter(WakaDayMetrics.day == day).delete()
    db.add(WakaDayMetrics(
        day=day,
        total_seconds=int(round(gt.get("total_seconds", 0) or 0)),
        ai_seconds=ai_seconds,
        ai_additions=int(gt.get("ai_additions", 0) or 0),
        ai_deletions=int(gt.get("ai_deletions", 0) or 0),
        human_additions=int(gt.get("human_additions", 0) or 0),
        human_deletions=int(gt.get("human_deletions", 0) or 0),
        ai_agent_line_changes=agent_lines_total,
        ai_input_tokens=int(gt.get("ai_input_tokens", 0) or 0),
        ai_output_tokens=int(gt.get("ai_output_tokens", 0) or 0),
        ai_sessions=int(gt.get("ai_sessions", 0) or 0),
        ai_prompt_events=int(gt.get("ai_prompt_events_total", 0) or 0),
        ai_cost=float(gt.get("ai_agent_total_cost", 0) or 0),
    ))


def sync_recent(db: Session, days: int = MAX_FETCH_DAYS) -> int:
    """Fetch the last `days` days from WakaTime and refresh the local cache."""
    days = max(1, min(days, MAX_FETCH_DAYS))
    end = date_type.today()
    start = end - timedelta(days=days - 1)
    data = _fetch_summaries(start, end)
    if data is None:
        return 0
    touched = 0
    for entry in data:
        d_str = (entry.get("range") or {}).get("date")
        if not d_str:
            continue
        try:
            d = date_type.fromisoformat(d_str[:10])
        except ValueError:
            continue
        _upsert_day(db, d, entry)
        touched += 1
    db.commit()
    return touched


def _maybe_sync(db: Session) -> None:
    global _last_sync_at
    if not _is_configured():
        return
    now = datetime.utcnow()
    if _last_sync_at and (now - _last_sync_at).total_seconds() < _SYNC_TTL_SECONDS:
        return
    try:
        sync_recent(db)
        _last_sync_at = now
    except Exception as e:
        logger.warning(f"WakaTime sync failed: {e}")
        db.rollback()


def _fmt(seconds: int) -> str:
    h, m = divmod(seconds // 60, 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


@router.get("/status")
def status(db: Session = Depends(get_db)):
    return {"configured": _is_configured(), "api_url": WAKATIME_API_URL}


@router.post("/sync")
def force_sync(days: int = Query(MAX_FETCH_DAYS, ge=1, le=MAX_FETCH_DAYS), db: Session = Depends(get_db)):
    if not _is_configured():
        raise HTTPException(status_code=400, detail="WAKATIME_API_KEY não configurada no backend/.env")
    global _last_sync_at
    n = sync_recent(db, days)
    _last_sync_at = datetime.utcnow()
    if n == 0:
        raise HTTPException(status_code=502, detail="WakaTime indisponível ou sem dados")
    return {"synced_days": n}


def _breakdown(per_name: dict[str, int]) -> list[dict]:
    return [
        {"name": k, "total_seconds": v, "text": _fmt(v)}
        for k, v in sorted(per_name.items(), key=lambda kv: -kv[1])
    ]


def _compact(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


_RANGE_LABELS = {
    "today": "Hoje",
    "last_7_days": "Últimos 7 dias",
    "last_14_days": "Últimos 14 dias",
    "last_30_days": "Últimos 30 dias",
    "this_week": "Esta semana",
    "last_week": "Semana passada",
    "this_month": "Este mês",
    "last_month": "Mês passado",
    "all_time": "Desde sempre",
}


def _range_bounds(range_key: str) -> tuple[date_type, date_type]:
    """Map a named range to (start, end) inclusive local dates. Weeks start Monday."""
    today = date_type.today()
    if range_key == "today":
        return today, today
    if range_key == "last_7_days":
        return today - timedelta(days=6), today
    if range_key == "last_14_days":
        return today - timedelta(days=13), today
    if range_key == "last_30_days":
        return today - timedelta(days=29), today
    if range_key == "this_week":
        return today - timedelta(days=today.weekday()), today
    if range_key == "last_week":
        this_mon = today - timedelta(days=today.weekday())
        return this_mon - timedelta(days=7), this_mon - timedelta(days=1)
    if range_key == "this_month":
        return today.replace(day=1), today
    if range_key == "last_month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), last_prev
    # Fallback: last 7 days
    return today - timedelta(days=6), today


def _cost_text(c: float) -> str:
    if c <= 0:
        return "$0"
    if c >= 0.01:
        return f"${c:.3f}"
    return f"${c:.4f}"


@router.get("/summary")
def summary(
    range_param: str = Query("last_7_days", alias="range"),
    days: Optional[int] = Query(None, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Coding time for the selected range from the local cache (refreshed from
    WakaTime in the background): per day, per project/language/editor, agents,
    detailed per-project AI metrics, plus totals, daily average and best day.

    `range` is one of: today, last_7_days, last_14_days, last_30_days,
    this_week, last_week, this_month, last_month. `days` (legacy) overrides it."""
    if not _is_configured():
        return {
            "configured": False, "days": [], "projects": [], "languages": [], "editors": [],
            "categories": [], "dependencies": [], "agents": [], "project_details": [],
            "today_projects": [], "total_seconds": 0, "today_seconds": 0,
            "daily_average_seconds": 0, "today_vs_avg_pct": 0, "best_day": None,
            "range_key": range_param, "range_label": _RANGE_LABELS.get(range_param, ""),
        }

    _maybe_sync(db)

    today = date_type.today()
    if days is not None:
        start, end = today - timedelta(days=days - 1), today
        range_key = f"last_{days}_days"
        range_label = f"Últimos {days} dias"
    elif range_param == "all_time":
        range_key = "all_time"
        range_label = _RANGE_LABELS["all_time"]
        earliest = db.query(func.min(WakaProjectDay.day)).scalar()
        start, end = (earliest or today), today
    else:
        range_key = range_param if range_param in _RANGE_LABELS else "last_7_days"
        start, end = _range_bounds(range_key)
        range_label = _RANGE_LABELS[range_key]
    num_days = (end - start).days + 1

    rows = (
        db.query(WakaProjectDay)
        .filter(WakaProjectDay.day >= start, WakaProjectDay.day <= end)
        .all()
    )

    per_day: dict[str, int] = {}
    per_kind: dict[str, dict[str, int]] = {
        "project": {}, "language": {}, "editor": {}, "os": {}, "category": {},
        "machine": {}, "dependency": {},
    }
    agent_lines: dict[str, int] = {}
    for r in rows:
        if r.kind == "agent":
            agent_lines[r.project] = agent_lines.get(r.project, 0) + r.seconds
            continue
        if r.kind == "project":
            iso = r.day.isoformat()
            per_day[iso] = per_day.get(iso, 0) + r.seconds
        bucket = per_kind.setdefault(r.kind, {})
        bucket[r.project] = bucket.get(r.project, 0) + r.seconds

    # AI seconds per day (for the AI-vs-human stacked daily chart).
    range_metrics = (
        db.query(WakaDayMetrics)
        .filter(WakaDayMetrics.day >= start, WakaDayMetrics.day <= end)
        .all()
    )
    ai_per_day = {m.day.isoformat(): m.ai_seconds for m in range_metrics}

    # Per-day series is only meaningful for bounded ranges; skip it for huge spans.
    days_list = []
    if num_days <= 366:
        for i in range(num_days):
            d = (start + timedelta(days=i)).isoformat()
            secs = per_day.get(d, 0)
            ai_secs = min(ai_per_day.get(d, 0), secs)
            days_list.append({"date": d, "total_seconds": secs, "ai_seconds": ai_secs, "text": _fmt(secs)})

    total = sum(per_kind["project"].values())
    active_days = [d for d in days_list if d["total_seconds"] > 0]
    daily_avg = total // len(active_days) if active_days else 0
    best = max(days_list, key=lambda d: d["total_seconds"]) if days_list else None
    best_day = best if best and best["total_seconds"] > 0 else None

    # Today's project breakdown — always today, regardless of the selected range.
    today_rows = (
        db.query(WakaProjectDay)
        .filter(WakaProjectDay.day == today, WakaProjectDay.kind == "project")
        .all()
    )
    today_projects_map: dict[str, int] = {}
    for r in today_rows:
        today_projects_map[r.project] = today_projects_map.get(r.project, 0) + r.seconds
    today_seconds = sum(today_projects_map.values())
    today_vs_avg_pct = round((today_seconds - daily_avg) / daily_avg * 100) if daily_avg else 0

    # Agents breakdown (lines, not seconds).
    agent_total = sum(agent_lines.values())
    agents = [
        {"name": k, "lines": v, "lines_text": _compact(v),
         "pct": round(v / agent_total * 100) if agent_total else 0}
        for k, v in sorted(agent_lines.items(), key=lambda kv: -kv[1])
    ]

    # AI coding metrics aggregated over the range (global).
    m_total = sum(m.total_seconds for m in range_metrics)
    ai_seconds = sum(m.ai_seconds for m in range_metrics)
    ai_lines = sum(m.ai_agent_line_changes for m in range_metrics)
    human_lines = sum(m.human_additions + m.human_deletions for m in range_metrics)
    in_tok = sum(m.ai_input_tokens for m in range_metrics)
    out_tok = sum(m.ai_output_tokens for m in range_metrics)
    ai_sessions = sum(m.ai_sessions for m in range_metrics)
    ai_prompts = sum(m.ai_prompt_events for m in range_metrics)
    ai_cost = sum(m.ai_cost for m in range_metrics)
    ai_pct = round(ai_seconds / m_total * 100) if m_total else 0
    line_total = ai_lines + human_lines
    ai_line_pct = round(ai_lines / line_total * 100) if line_total else 0

    ai = {
        "coding_pct": ai_pct,
        "ai_lines": ai_lines,
        "ai_lines_text": _compact(ai_lines),
        "human_lines": human_lines,
        "human_lines_text": _compact(human_lines),
        "ai_line_pct": ai_line_pct,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "tokens_text": _compact(in_tok + out_tok),
        "input_tokens_text": _compact(in_tok),
        "output_tokens_text": _compact(out_tok),
        "sessions": ai_sessions,
        "prompts": ai_prompts,
        "cost": round(ai_cost, 3),
        "cost_text": f"${ai_cost:.2f}" if ai_cost >= 0.01 else f"${ai_cost:.4f}",
    }

    # Detailed per-project metrics over the range.
    pm_rows = (
        db.query(WakaProjectDayMetrics)
        .filter(WakaProjectDayMetrics.day >= start, WakaProjectDayMetrics.day <= end)
        .all()
    )
    pm_agg: dict[str, dict] = {}
    for r in pm_rows:
        a = pm_agg.setdefault(r.project, {
            "ai_lines": 0, "human_changes": 0, "ai_prompts": 0,
            "prompt_len_sum": 0, "ai_sessions": 0, "in_tok": 0, "out_tok": 0, "cost": 0.0,
        })
        a["ai_lines"] += r.ai_lines
        a["human_changes"] += r.human_additions + r.human_deletions
        a["ai_prompts"] += r.ai_prompt_events
        a["prompt_len_sum"] += r.ai_prompt_length_sum
        a["ai_sessions"] += r.ai_sessions
        a["in_tok"] += r.ai_input_tokens
        a["out_tok"] += r.ai_output_tokens
        a["cost"] += r.ai_cost

    project_details = []
    for name, secs in per_kind["project"].items():
        m = pm_agg.get(name, {})
        ai_changes = m.get("ai_lines", 0)
        human_changes = m.get("human_changes", 0)
        lt = ai_changes + human_changes
        prompts = m.get("ai_prompts", 0)
        sessions = m.get("ai_sessions", 0)
        in_t = m.get("in_tok", 0)
        out_t = m.get("out_tok", 0)
        cost = m.get("cost", 0.0)
        project_details.append({
            "name": name,
            "seconds": secs,
            "text": _fmt(secs),
            "ai_changes": ai_changes,
            "ai_changes_text": _compact(ai_changes),
            "ai_changes_pct": round(ai_changes / lt * 100) if lt else 0,
            "human_changes": human_changes,
            "human_changes_text": _compact(human_changes),
            "human_changes_pct": round(human_changes / lt * 100) if lt else 0,
            "ai_prompts": prompts,
            "ai_prompt_avg_chars": round(m.get("prompt_len_sum", 0) / prompts) if prompts else 0,
            "ai_sessions": sessions,
            "ai_avg_prompts_per_session": round(prompts / sessions, 1) if sessions else 0,
            "input_tokens": in_t,
            "output_tokens": out_t,
            "tokens_text": _compact(in_t + out_t),
            "input_tokens_text": _compact(in_t),
            "output_tokens_text": _compact(out_t),
            "ai_cost": round(cost, 4),
            "ai_cost_text": _cost_text(cost),
        })
    project_details.sort(key=lambda d: -d["seconds"])

    return {
        "configured": True,
        "range_key": range_key,
        "range_label": range_label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": days_list,
        "projects": _breakdown(per_kind["project"]),
        "today_projects": _breakdown(today_projects_map),
        "project_details": project_details,
        "agents": agents,
        "languages": _breakdown(per_kind["language"]),
        "editors": _breakdown(per_kind["editor"]),
        "categories": _breakdown(per_kind["category"]),
        "dependencies": _breakdown(per_kind["dependency"]),
        "ai": ai,
        "total_seconds": total,
        "total_text": _fmt(total),
        "today_seconds": today_seconds,
        "today_text": _fmt(today_seconds),
        "daily_average_seconds": daily_avg,
        "daily_average_text": _fmt(daily_avg),
        "today_vs_avg_pct": today_vs_avg_pct,
        "active_days": len(active_days),
        "best_day": best_day,
    }
