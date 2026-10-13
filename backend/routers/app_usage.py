from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, datetime, timedelta
from pydantic import BaseModel
from typing import Optional
from collections import defaultdict
import csv
import io

from database import get_db
from models import AppUsageSession, AppUsageBlocklist, AppCategoryOverride, FlowSession
from schemas import AppUsageSessionCreate, AppUsageSessionOut
from app_categories import (
    categorize, CATEGORY_COLORS, CATEGORY_LABELS, categorize_browser_title, is_browser,
    e_ruido_do_browser, categorize_domain, BROWSER_BUNDLES,
)

router = APIRouter(prefix="/api/app-usage", tags=["App Usage"])


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
    """Categorias definidas à mão, em memória (60s).

    Antes era uma consulta à base por cada sessão: 16 mil sessões davam 32 mil
    consultas e três segundos de espera só para desenhar um gráfico."""
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


def _resolve_category(db: Session, session: AppUsageSession) -> str:
    """Apply user override, otherwise use the built-in mapping."""
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


# ── Sessions (CRUD) ───────────────────────────────────────────────

@router.post("/sessions", response_model=AppUsageSessionOut)
def create_session(data: AppUsageSessionCreate, db: Session = Depends(get_db)):
    duration = int((data.end_time - data.start_time).total_seconds())
    session = AppUsageSession(
        app_name=data.app_name,
        window_title=data.window_title,
        bundle_id=data.bundle_id,
        date=data.start_time.date(),
        start_time=data.start_time,
        end_time=data.end_time,
        duration_seconds=duration,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/sessions", response_model=list[AppUsageSessionOut])
def list_sessions(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    app_name: Optional[str] = Query(None),
    min_seconds: int = Query(0),
    db: Session = Depends(get_db),
):
    q = db.query(AppUsageSession)
    if start_date:
        q = q.filter(AppUsageSession.date >= start_date)
    if end_date:
        q = q.filter(AppUsageSession.date <= end_date)
    if app_name:
        q = q.filter(AppUsageSession.app_name == app_name)
    if min_seconds > 0:
        q = q.filter(AppUsageSession.duration_seconds >= min_seconds)
    return q.order_by(AppUsageSession.start_time.asc()).all()


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    session = db.query(AppUsageSession).filter(AppUsageSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(session)
    db.commit()
    return {"ok": True}


# ── Summary (per app + per category) ──────────────────────────────

@router.get("/summary")
def usage_summary(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(AppUsageSession)
    if start_date:
        q = q.filter(AppUsageSession.date >= start_date)
    if end_date:
        q = q.filter(AppUsageSession.date <= end_date)
    sessions = q.all()

    by_app: dict[str, dict] = {}
    by_category: dict[str, dict] = {}
    total = 0

    for s in sessions:
        total += s.duration_seconds
        cat = _resolve_category(db, s)

        if s.app_name not in by_app:
            by_app[s.app_name] = {
                "app_name": s.app_name,
                "bundle_id": s.bundle_id,
                "category": cat,
                "total_seconds": 0,
                "session_count": 0,
            }
        by_app[s.app_name]["total_seconds"] += s.duration_seconds
        by_app[s.app_name]["session_count"] += 1

        if cat not in by_category:
            by_category[cat] = {
                "category": cat,
                "label": CATEGORY_LABELS.get(cat, cat),
                "color": CATEGORY_COLORS.get(cat, "#9CA3AF"),
                "total_seconds": 0,
                "app_count": 0,
            }
        by_category[cat]["total_seconds"] += s.duration_seconds

    for cat_name in by_category:
        by_category[cat_name]["app_count"] = sum(1 for a in by_app.values() if a["category"] == cat_name)

    total_safe = total or 1
    apps_out = sorted(by_app.values(), key=lambda a: a["total_seconds"], reverse=True)
    for a in apps_out:
        a["total_hours"] = round(a["total_seconds"] / 3600, 2)
        a["percentage"] = round(a["total_seconds"] / total_safe * 100, 1)

    cats_out = sorted(by_category.values(), key=lambda c: c["total_seconds"], reverse=True)
    for c in cats_out:
        c["total_hours"] = round(c["total_seconds"] / 3600, 2)
        c["percentage"] = round(c["total_seconds"] / total_safe * 100, 1)

    return {
        "total_seconds": total,
        "total_hours": round(total / 3600, 2),
        "by_app": apps_out,
        "by_category": cats_out,
    }


# ── Heatmap (day × hour matrix) ───────────────────────────────────

@router.get("/heatmap")
def heatmap(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db),
):
    """Returns total seconds per (date, hour) cell."""
    sessions = db.query(AppUsageSession).filter(
        AppUsageSession.date >= start_date,
        AppUsageSession.date <= end_date,
    ).all()

    # (date_iso, hour) → seconds
    cells: dict[tuple[str, int], int] = defaultdict(int)
    for s in sessions:
        start = s.start_time
        remaining = s.duration_seconds
        cursor = start
        while remaining > 0:
            hour_end = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            chunk = min(remaining, int((hour_end - cursor).total_seconds()))
            cells[(cursor.date().isoformat(), cursor.hour)] += chunk
            remaining -= chunk
            cursor = hour_end

    days: list[str] = []
    cur = start_date
    while cur <= end_date:
        days.append(cur.isoformat())
        cur += timedelta(days=1)

    matrix = [
        [cells.get((d, h), 0) for h in range(24)]
        for d in days
    ]
    return {"days": days, "matrix": matrix}


# ── Breakdown by window title (for a single app) ──────────────────

@router.get("/by-title")
def by_title(
    app_name: str = Query(...),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(30),
    db: Session = Depends(get_db),
):
    q = db.query(
        AppUsageSession.window_title,
        func.sum(AppUsageSession.duration_seconds).label("total_seconds"),
        func.count(AppUsageSession.id).label("session_count"),
    ).filter(AppUsageSession.app_name == app_name)
    if start_date:
        q = q.filter(AppUsageSession.date >= start_date)
    if end_date:
        q = q.filter(AppUsageSession.date <= end_date)
    q = q.filter(AppUsageSession.window_title != "")
    rows = q.group_by(AppUsageSession.window_title).order_by(func.sum(AppUsageSession.duration_seconds).desc()).limit(limit).all()
    total = sum(r.total_seconds for r in rows) or 1
    return [
        {
            "window_title": r.window_title,
            "total_seconds": r.total_seconds,
            "session_count": r.session_count,
            "percentage": round(r.total_seconds / total * 100, 1),
        }
        for r in rows
    ]


# ── Onde é que ele vai no browser ─────────────────────────────────

@router.get("/by-domain")
def by_domain(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Tempo de browser por site. O maior número da app (258h de Brave) estava
    partido em 1970 títulos; por domínio são umas dezenas de sites."""
    q = (
        db.query(
            AppUsageSession.domain,
            func.sum(AppUsageSession.duration_seconds).label("seconds"),
            func.count(AppUsageSession.id).label("sessions"),
            func.count(func.distinct(AppUsageSession.date)).label("days"),
        )
        .filter(AppUsageSession.domain.isnot(None), AppUsageSession.domain != "")
    )
    if start_date:
        q = q.filter(AppUsageSession.date >= start_date)
    if end_date:
        q = q.filter(AppUsageSession.date <= end_date)
    linhas = q.group_by(AppUsageSession.domain).order_by(func.sum(AppUsageSession.duration_seconds).desc()).all()

    total = sum(r.seconds or 0 for r in linhas)
    sites = [
        {
            "domain": r.domain,
            "seconds": int(r.seconds or 0),
            "sessions": int(r.sessions or 0),
            "days": int(r.days or 0),
            "category": categorize_domain(r.domain) or "other",
            "percentage": round((r.seconds or 0) / total * 100, 1) if total else 0.0,
        }
        for r in linhas
    ]

    por_categoria: dict[str, int] = {}
    for s in sites:
        por_categoria[s["category"]] = por_categoria.get(s["category"], 0) + s["seconds"]

    # Quanto do browser ainda não tem domínio guardado (sessões anteriores a isto
    # existir) — sem este número os totais parecem menores do que são.
    sem = (
        db.query(func.coalesce(func.sum(AppUsageSession.duration_seconds), 0))
        .filter(AppUsageSession.domain.is_(None) | (AppUsageSession.domain == ""))
    )
    if start_date:
        sem = sem.filter(AppUsageSession.date >= start_date)
    if end_date:
        sem = sem.filter(AppUsageSession.date <= end_date)
    sem_dominio = int(
        sem.filter(AppUsageSession.bundle_id.in_(tuple(BROWSER_BUNDLES))).scalar() or 0
    )

    return {
        "sites": sites[:limit],
        "total_seconds": total,
        "distinct_domains": len(sites),
        "unknown_seconds": sem_dominio,
        "by_category": [
            {"category": c, "label": CATEGORY_LABELS.get(c, c), "color": CATEGORY_COLORS.get(c, "#9CA3AF"),
             "seconds": s, "percentage": round(s / total * 100, 1) if total else 0.0}
            for c, s in sorted(por_categoria.items(), key=lambda kv: -kv[1])
        ],
    }


# ── Cross-reference with Flow sessions ────────────────────────────

@router.get("/flow-overlap")
def flow_overlap(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """For each Flow session, compute which apps were used during it and for how long."""
    fq = db.query(FlowSession)
    if start_date:
        fq = fq.filter(FlowSession.date >= start_date)
    if end_date:
        fq = fq.filter(FlowSession.date <= end_date)
    flows = fq.order_by(FlowSession.date.asc(), FlowSession.start_time.asc()).all()

    results = []
    for f in flows:
        if not f.start_time or not f.end_time:
            continue
        try:
            fs = datetime.combine(f.date, datetime.strptime(f.start_time, "%H:%M").time())
            fe = datetime.combine(f.date, datetime.strptime(f.end_time, "%H:%M").time())
        except ValueError:
            continue

        sessions = db.query(AppUsageSession).filter(
            AppUsageSession.date == f.date,
            AppUsageSession.end_time >= fs,
            AppUsageSession.start_time <= fe,
        ).all()

        by_app: dict[str, int] = defaultdict(int)
        by_cat: dict[str, int] = defaultdict(int)
        total_overlap = 0
        for s in sessions:
            overlap_start = max(s.start_time, fs)
            overlap_end = min(s.end_time, fe)
            overlap = max(0, int((overlap_end - overlap_start).total_seconds()))
            if overlap == 0:
                continue
            by_app[s.app_name] += overlap
            by_cat[_resolve_category(db, s)] += overlap
            total_overlap += overlap

        flow_duration = int((fe - fs).total_seconds())
        focus_ratio = round(by_cat.get("development", 0) / flow_duration * 100, 1) if flow_duration else 0

        results.append({
            "flow_id": f.id,
            "flow_name": f.preset_name,
            "flow_color": f.color,
            "date": f.date.isoformat(),
            "start_time": f.start_time,
            "end_time": f.end_time,
            "flow_duration_seconds": flow_duration,
            "tracked_seconds": total_overlap,
            "focus_ratio_pct": focus_ratio,
            "by_app": sorted(
                [{"app_name": a, "seconds": s} for a, s in by_app.items()],
                key=lambda x: x["seconds"], reverse=True,
            ),
            "by_category": sorted(
                [{"category": c, "label": CATEGORY_LABELS.get(c, c), "color": CATEGORY_COLORS.get(c, "#9CA3AF"), "seconds": s}
                 for c, s in by_cat.items()],
                key=lambda x: x["seconds"], reverse=True,
            ),
        })
    return results


# ── Weekly trend ──────────────────────────────────────────────────

@router.get("/weekly-trend")
def weekly_trend(weeks: int = Query(4, ge=1, le=52), db: Session = Depends(get_db)):
    """Returns totals for the last N full weeks ending today."""
    today = date.today()
    result = []
    for i in range(weeks - 1, -1, -1):
        # Week starting Monday
        weekday = today.weekday()
        this_monday = today - timedelta(days=weekday)
        start = this_monday - timedelta(weeks=i)
        end = start + timedelta(days=6)

        sessions = db.query(AppUsageSession).filter(
            AppUsageSession.date >= start,
            AppUsageSession.date <= end,
        ).all()

        total = sum(s.duration_seconds for s in sessions)
        by_cat: dict[str, int] = defaultdict(int)
        for s in sessions:
            by_cat[_resolve_category(db, s)] += s.duration_seconds

        result.append({
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "label": f"{start.strftime('%d/%m')}–{end.strftime('%d/%m')}",
            "total_seconds": total,
            "by_category": [
                {"category": c, "label": CATEGORY_LABELS.get(c, c),
                 "color": CATEGORY_COLORS.get(c, "#9CA3AF"), "seconds": sec}
                for c, sec in sorted(by_cat.items(), key=lambda x: -x[1])
            ],
        })
    return result


# ── Export CSV ────────────────────────────────────────────────────

@router.get("/export.csv")
def export_csv(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(AppUsageSession)
    if start_date:
        q = q.filter(AppUsageSession.date >= start_date)
    if end_date:
        q = q.filter(AppUsageSession.date <= end_date)
    sessions = q.order_by(AppUsageSession.start_time.asc()).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "start_time", "end_time", "duration_seconds", "app_name", "bundle_id", "window_title", "category"])
    for s in sessions:
        writer.writerow([
            s.date.isoformat(),
            s.start_time.isoformat(sep=" ", timespec="seconds"),
            s.end_time.isoformat(sep=" ", timespec="seconds"),
            s.duration_seconds,
            s.app_name,
            s.bundle_id or "",
            s.window_title or "",
            _resolve_category(db, s),
        ])
    filename = f"app-usage-{start_date or 'all'}_{end_date or 'now'}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Categories (built-ins + overrides) ────────────────────────────

@router.get("/categories")
def categories_list():
    return [
        {"category": c, "label": CATEGORY_LABELS[c], "color": CATEGORY_COLORS[c]}
        for c in CATEGORY_LABELS
    ]


@router.post("/categories/override")
def set_category_override(
    data: dict,
    db: Session = Depends(get_db),
):
    """Body: { app_name?, bundle_id?, category }"""
    app_name = data.get("app_name")
    bundle_id = data.get("bundle_id")
    category = data.get("category")
    if not category or category not in CATEGORY_LABELS:
        raise HTTPException(status_code=400, detail="invalid category")
    if not app_name and not bundle_id:
        raise HTTPException(status_code=400, detail="app_name or bundle_id required")

    existing = None
    if bundle_id:
        existing = db.query(AppCategoryOverride).filter(AppCategoryOverride.bundle_id == bundle_id).first()
    if not existing and app_name:
        existing = db.query(AppCategoryOverride).filter(AppCategoryOverride.app_name == app_name).first()

    if existing:
        existing.category = category
    else:
        db.add(AppCategoryOverride(app_name=app_name, bundle_id=bundle_id, category=category))
    db.commit()
    return {"ok": True}


# ── Blocklist ─────────────────────────────────────────────────────

@router.get("/blocklist")
def get_blocklist(db: Session = Depends(get_db)):
    return [
        {"id": b.id, "app_name": b.app_name, "bundle_id": b.bundle_id}
        for b in db.query(AppUsageBlocklist).order_by(AppUsageBlocklist.app_name).all()
    ]


@router.post("/blocklist")
def add_blocklist(data: dict, db: Session = Depends(get_db)):
    app_name = data.get("app_name")
    bundle_id = data.get("bundle_id")
    if not app_name and not bundle_id:
        raise HTTPException(status_code=400, detail="app_name or bundle_id required")
    entry = AppUsageBlocklist(app_name=app_name, bundle_id=bundle_id)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {"id": entry.id}


@router.delete("/blocklist/{entry_id}")
def delete_blocklist(entry_id: int, db: Session = Depends(get_db)):
    entry = db.query(AppUsageBlocklist).filter(AppUsageBlocklist.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(entry)
    db.commit()
    return {"ok": True}


# ── Status ────────────────────────────────────────────────────────

@router.get("/status")
def tracker_status(db: Session = Depends(get_db)):
    last = db.query(AppUsageSession).order_by(AppUsageSession.end_time.desc()).first()
    if not last:
        return {"running": False, "last_seen": None, "current_app": None, "current_category": None}
    seconds_since = (datetime.now() - last.end_time).total_seconds()
    running = 0 <= seconds_since < 60
    return {
        "running": running,
        "last_seen": last.end_time.isoformat(),
        "current_app": last.app_name if running else None,
        "current_category": _resolve_category(db, last) if running else None,
        "seconds_since": int(seconds_since),
    }


# ── Maintenance: merge + retention ────────────────────────────────

@router.post("/cleanup")
def cleanup(
    merge_gap_seconds: int = Query(5, ge=1, le=60),
    retention_days: int = Query(0, ge=0, le=3650, description="Delete sessions older than N days; 0 = keep all"),
    db: Session = Depends(get_db),
):
    """Merges adjacent/overlapping (same app+title) sessions and optionally purges old data.

    Handles two failure modes:
      1. Adjacent sessions with a small gap (≤ merge_gap_seconds) — heartbeat splits.
      2. Overlapping sessions from duplicate tracker processes — multiple tracker
         instances writing for the same active window in parallel.
    """
    merged = 0
    # Group by (app, title, bundle) and merge intervals per group.
    grouped: dict[tuple[str, str, str], list[AppUsageSession]] = defaultdict(list)
    for s in db.query(AppUsageSession).order_by(AppUsageSession.start_time.asc()).all():
        key = (s.app_name, s.window_title or "", s.bundle_id or "")
        grouped[key].append(s)

    for sessions in grouped.values():
        if len(sessions) < 2:
            continue
        sessions.sort(key=lambda x: x.start_time)
        keeper = sessions[0]
        for s in sessions[1:]:
            gap = (s.start_time - keeper.end_time).total_seconds()
            # Merge if overlapping (gap < 0) or within merge_gap_seconds.
            if gap <= merge_gap_seconds:
                if s.end_time > keeper.end_time:
                    keeper.end_time = s.end_time
                    keeper.duration_seconds = int((keeper.end_time - keeper.start_time).total_seconds())
                db.delete(s)
                merged += 1
            else:
                keeper = s
    db.commit()

    purged = 0
    if retention_days > 0:
        cutoff = date.today() - timedelta(days=retention_days)
        purged = db.query(AppUsageSession).filter(AppUsageSession.date < cutoff).delete()
        db.commit()

    return {"merged": merged, "purged": purged}


# ── Regras de título do browser (aprender o que ainda é opaco) ────

class TitleRuleIn(BaseModel):
    pattern: str
    category: str


@router.get("/title-rules")
def list_title_rules(db: Session = Depends(get_db)):
    from models import BrowserTitleRule
    rows = db.query(BrowserTitleRule).order_by(BrowserTitleRule.created_at.desc()).all()
    return [{"id": r.id, "pattern": r.pattern, "category": r.category, "source": r.source} for r in rows]


@router.put("/title-rules")
def upsert_title_rule(data: TitleRuleIn, db: Session = Depends(get_db)):
    from models import BrowserTitleRule
    pattern = data.pattern.strip().lower()
    if not pattern:
        raise HTTPException(status_code=400, detail="Padrão vazio")
    if data.category not in CATEGORY_LABELS:
        raise HTTPException(status_code=400, detail="Categoria inválida")
    row = db.query(BrowserTitleRule).filter(BrowserTitleRule.pattern == pattern).first()
    if not row:
        row = BrowserTitleRule(pattern=pattern, category=data.category, source="user")
        db.add(row)
    else:
        row.category = data.category
        row.source = "user"
    db.commit()
    _RULES_CACHE["at"] = 0.0
    return {"pattern": pattern, "category": data.category}


@router.delete("/title-rules/{rule_id}")
def delete_title_rule(rule_id: int, db: Session = Depends(get_db)):
    from models import BrowserTitleRule
    n = db.query(BrowserTitleRule).filter(BrowserTitleRule.id == rule_id).delete()
    db.commit()
    _RULES_CACHE["at"] = 0.0
    return {"deleted": n}


@router.get("/unclassified-titles")
def unclassified_titles(days: int = Query(60, ge=1, le=365), limit: int = Query(25, ge=1, le=100),
                        db: Session = Depends(get_db)):
    """Títulos de browser com tempo relevante que ainda não caem em nenhuma categoria."""
    desde = (date.today() - timedelta(days=days)).isoformat()
    rows = (
        db.query(AppUsageSession.window_title, func.sum(AppUsageSession.duration_seconds))
        .filter(AppUsageSession.date >= desde)
        .filter(AppUsageSession.window_title.isnot(None), AppUsageSession.window_title != "")
        # só o browser: os títulos do VS Code e afins já vão pela app
        .filter(func.lower(AppUsageSession.app_name).in_([
            "brave browser", "google chrome", "safari", "firefox", "arc", "microsoft edge",
        ]))
        .group_by(AppUsageSession.window_title)
        .order_by(func.sum(AppUsageSession.duration_seconds).desc())
        .limit(400)
        .all()
    )
    regras = _learned_rules(db)
    out = []
    ruido_seg = 0
    for titulo, seg in rows:
        if e_ruido_do_browser(titulo):
            ruido_seg += int(seg or 0)      # é o browser a falar, não um site
            continue
        if categorize_browser_title(titulo, regras) is None:
            out.append({"title": titulo, "seconds": int(seg or 0)})
        if len(out) >= limit:
            break
    sem_titulo = (
        db.query(func.coalesce(func.sum(AppUsageSession.duration_seconds), 0))
        .filter(AppUsageSession.date >= desde)
        .filter(func.lower(AppUsageSession.app_name).in_([
            "brave browser", "google chrome", "safari", "firefox", "arc", "microsoft edge",
        ]))
        .filter((AppUsageSession.window_title.is_(None)) | (AppUsageSession.window_title == ""))
        .scalar()
    ) or 0
    total = sum(x["seconds"] for x in out)
    return {
        "titles": out,
        "total_seconds": total,
        "untitled_seconds": int(sem_titulo),
        "browser_noise_seconds": ruido_seg,   # popups e ecrãs do próprio browser
    }


@router.post("/title-rules/learn")
async def learn_title_rules(days: int = Query(60, ge=1, le=365), db: Session = Depends(get_db)):
    """Manda os títulos opacos à IA e guarda as regras que ela devolver."""
    from ai_config import ask_agent_async, extract_json
    from models import BrowserTitleRule

    alvo = unclassified_titles(days=days, limit=25, db=db)
    titulos = alvo["titles"]
    if not titulos:
        return {"learned": 0, "rules": [], "reason": "nada por classificar"}

    lista = "\n".join(f"- {t['title'][:90]} ({round(t['seconds']/3600, 1)}h)" for t in titulos)
    categorias = ", ".join(sorted(CATEGORY_LABELS.keys()))
    prompt = f"""Classifica títulos de janelas do meu computador em categorias de uso.

Categorias possíveis (usa exactamente estes nomes): {categorias}

Títulos (com o tempo que passei em cada um):
{lista}

Devolve SÓ um JSON: {{"rules": [{{"pattern": "pedaço curto e distintivo do título em minúsculas", "category": "uma das categorias"}}]}}

Regras:
- O "pattern" deve ser a parte estável do título (nome do site/app), 2 a 30 caracteres, minúsculas.
- Ignora títulos genéricos onde não se percebe o que é (ex.: "Copy", "Translate this page?").
- Só o que tiveres confiança. Menos regras boas é melhor que muitas erradas."""

    try:
        resposta = await ask_agent_async(prompt, timeout=120.0, feature="aquecer")
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"IA indisponível: {ex}")

    data = extract_json(resposta) or {}
    criadas = []
    for r in (data.get("rules") or []):
        pattern = str(r.get("pattern", "")).strip().lower()[:60]
        cat = str(r.get("category", "")).strip()
        if not pattern or len(pattern) < 2 or cat not in CATEGORY_LABELS:
            continue
        existe = db.query(BrowserTitleRule).filter(BrowserTitleRule.pattern == pattern).first()
        if existe:
            continue
        db.add(BrowserTitleRule(pattern=pattern, category=cat, source="ai"))
        criadas.append({"pattern": pattern, "category": cat})
    if criadas:
        db.commit()
        _RULES_CACHE["at"] = 0.0
    return {"learned": len(criadas), "rules": criadas}


@router.get("/self-usage")
def uso_da_propria_app(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    """Onde é que ele passa o tempo dentro do Cristopher.

    O tracker já grava o título do separador; desde que cada página passou a
    dizer o seu nome, isto mostra que secções são realmente usadas — e quais
    estão lá só a ocupar espaço no menu."""
    desde = date.today() - timedelta(days=days - 1)
    linhas = (
        db.query(AppUsageSession)
        .filter(AppUsageSession.date >= desde)
        .filter(AppUsageSession.window_title.ilike("%Cristopher%"))
        .all()
    )
    por_seccao: dict[str, dict] = {}
    sem_nome = 0
    for s in linhas:
        titulo = (s.window_title or "").strip()
        # "Gastos · Cristopher - Brave - Work" → "Gastos"
        if "·" in titulo:
            seccao = titulo.split("·")[0].strip()
        elif titulo.lower().startswith("cristopher"):
            sem_nome += s.duration_seconds or 0
            continue
        else:
            sem_nome += s.duration_seconds or 0
            continue
        d = por_seccao.setdefault(seccao, {"section": seccao, "seconds": 0, "visits": 0, "last": None})
        d["seconds"] += s.duration_seconds or 0
        d["visits"] += 1
        if not d["last"] or (s.start_time and s.start_time.date().isoformat() > d["last"]):
            d["last"] = s.start_time.date().isoformat() if s.start_time else None

    saida = sorted(por_seccao.values(), key=lambda r: -r["seconds"])
    total = sum(r["seconds"] for r in saida)
    for r in saida:
        r["share"] = round(r["seconds"] / total * 100, 1) if total else 0
    return {
        "days": days,
        "total_seconds": total,
        "unnamed_seconds": sem_nome,      # antes de as páginas passarem a dizer o nome
        "sections": saida,
    }
