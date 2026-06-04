"""Endpoints para o Screen Time agregado da Apple (Mac + iPhone + iPad via iCloud sync).

Lê o knowledgeC.db do macOS via screen_time_reader. Os dados de iPhone/iPad só
aparecem se "Share Across Devices" estiver activo no Screen Time da Apple.
"""
from __future__ import annotations

import platform
import subprocess
from collections import defaultdict
from datetime import datetime, date, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from models import ScreenTimeDeviceLabel, ScreenTimeDailyApp
import screen_time_reader as reader
from app_icons import get_icon_png_path

router = APIRouter(prefix="/api/screen-time", tags=["Screen Time"])


def _day_to_unix_range(d: date) -> tuple[float, float]:
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()
    end = start + 86400
    return start, end


def _range_to_unix(start_date: Optional[str], end_date: Optional[str]) -> tuple[float, float]:
    if start_date:
        sd = date.fromisoformat(start_date)
    else:
        sd = date.today() - timedelta(days=7)
    if end_date:
        ed = date.fromisoformat(end_date)
    else:
        ed = date.today()
    start_unix, _ = _day_to_unix_range(sd)
    _, end_unix = _day_to_unix_range(ed)
    return start_unix, end_unix


def _labels_map(db: Session) -> dict[str, dict]:
    rows = db.query(ScreenTimeDeviceLabel).all()
    return {
        r.device_id: {"label": r.label, "kind": r.kind}
        for r in rows
    }


def _attach_label(item: dict, labels: dict[str, dict]) -> dict:
    info = labels.get(item.get("device_id", ""), {})
    item["label"] = info.get("label", "")
    item["kind"] = info.get("kind", "unknown")
    return item


def snapshot_screen_time(days_back: int = 45) -> int:
    """Lê o knowledgeC e persiste agregados diários por app (modo 'apple') na
    tabela screen_time_daily_apps. Só sobrescreve um dia quando o knowledgeC
    ainda tem dados desse dia — dias que já saíram do knowledgeC mantêm o último
    snapshot guardado. Devolve o número de dias actualizados.

    É assim que ganhamos histórico de longo prazo: a Apple só guarda ~4 semanas."""
    ok, _ = reader.is_available()
    if not ok:
        return 0
    days_written = 0
    db = SessionLocal()
    try:
        today = date.today()
        for offset in range(days_back + 1):
            d = today - timedelta(days=offset)
            start_unix, end_unix = _day_to_unix_range(d)
            try:
                rows = reader.summary_by_app(start_unix, end_unix, mode="apple")
            except Exception:
                continue
            rows = [r for r in rows if (r.get("total_seconds") or 0) > 0]
            if not rows:
                continue  # sem dados no knowledgeC → preserva snapshot anterior
            db.query(ScreenTimeDailyApp).filter(ScreenTimeDailyApp.date == d).delete()
            for r in rows:
                db.add(ScreenTimeDailyApp(
                    date=d,
                    device_id=r.get("device_id", "__local__"),
                    bundle_id=r.get("bundle_id", "(unknown)"),
                    category=r.get("category", "") or "",
                    seconds=int(round(r.get("total_seconds") or 0)),
                ))
            days_written += 1
        db.commit()
    finally:
        db.close()
    return days_written


@router.get("/health")
def health():
    """Diz se a DB do Screen Time está acessível ao backend.

    Inclui o caminho do binário Python responsável (útil quando o utilizador
    precisa de dar FDA directamente à Python.framework como fallback)."""
    ok, reason = reader.is_available()
    python_app_path = ""
    if platform.system() == "Darwin":
        import sys
        from pathlib import Path
        candidates = [
            Path(sys.exec_prefix) / "Resources" / "Python.app",
            Path("/Library/Frameworks/Python.framework/Versions") / f"{sys.version_info.major}.{sys.version_info.minor}" / "Resources" / "Python.app",
        ]
        for c in candidates:
            if c.exists():
                python_app_path = str(c)
                break
    return {
        "available": ok,
        "reason": reason,
        "db_path": str(reader.KNOWLEDGE_DB),
        "python_app_path": python_app_path,
    }


@router.get("/app-icon")
def app_icon(bundle_id: str):
    """Devolve o PNG do ícone da app pelo bundle_id (extraído de /Applications).

    Cacheado em disco em uploads/app_icons. 404 se a app não estiver instalada
    localmente ou se o .icns não for extraível.
    """
    path = get_icon_png_path(bundle_id)
    if not path:
        return Response(status_code=404)
    # Cache forte: ícones quase nunca mudam — 1 dia
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.post("/open-settings")
def open_fda_settings():
    """Abre System Settings → Privacy & Security → Full Disk Access (só macOS)."""
    if platform.system() != "Darwin":
        raise HTTPException(400, "Só funciona em macOS")
    url = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
    try:
        subprocess.Popen(["open", url])
    except Exception as e:
        raise HTTPException(500, f"Falhou: {e}")
    return {"opened": True}


@router.get("/devices")
def list_devices(db: Session = Depends(get_db)):
    """Devices distintos vistos no Screen Time + label humana se existir."""
    try:
        items = reader.list_devices()
    except reader.ScreenTimeUnavailable as e:
        raise HTTPException(503, str(e))
    labels = _labels_map(db)
    return [_attach_label(it, labels) for it in items]


@router.put("/devices/{device_id}")
def label_device(
    device_id: str,
    payload: dict,
    db: Session = Depends(get_db),
):
    """Guarda etiqueta humana ('iPhone do Cris', kind=iphone) para um device_id."""
    label = (payload.get("label") or "").strip()
    kind = (payload.get("kind") or "unknown").strip()
    if kind not in ("mac", "iphone", "ipad", "watch", "unknown"):
        raise HTTPException(400, "kind inválido")
    row = db.query(ScreenTimeDeviceLabel).filter_by(device_id=device_id).first()
    if row is None:
        row = ScreenTimeDeviceLabel(device_id=device_id, label=label, kind=kind)
        db.add(row)
    else:
        row.label = label
        row.kind = kind
    db.commit()
    db.refresh(row)
    return {"device_id": row.device_id, "label": row.label, "kind": row.kind}


@router.get("/by-app")
def by_app(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    device_id: Optional[str] = None,
    mode: str = Query("raw", pattern="^(raw|apple)$"),
    db: Session = Depends(get_db),
):
    """Agregado por app + device. Default: últimos 7 dias.

    mode='apple' aplica gap-merge + ceil ao minuto para aproximar Settings da Apple.
    """
    try:
        s, e = _range_to_unix(start_date, end_date)
        items = reader.summary_by_app(s, e, device_id=device_id, mode=mode)
    except reader.ScreenTimeUnavailable as ex:
        raise HTTPException(503, str(ex))
    labels = _labels_map(db)
    return [_attach_label(it, labels) for it in items]


@router.get("/by-category")
def by_category(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    device_id: Optional[str] = None,
    mode: str = Query("raw", pattern="^(raw|apple)$"),
):
    """Agregado por categoria (estilo Apple Screen Time)."""
    try:
        s, e = _range_to_unix(start_date, end_date)
        return reader.summary_by_category(s, e, device_id=device_id, mode=mode)
    except reader.ScreenTimeUnavailable as ex:
        raise HTTPException(503, str(ex))


@router.get("/by-device")
def by_device(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    mode: str = Query("raw", pattern="^(raw|apple)$"),
    db: Session = Depends(get_db),
):
    """Total agregado por device no intervalo. Default: últimos 7 dias."""
    try:
        s, e = _range_to_unix(start_date, end_date)
        items = reader.summary_by_device(s, e, mode=mode)
    except reader.ScreenTimeUnavailable as ex:
        raise HTTPException(503, str(ex))
    labels = _labels_map(db)
    return [_attach_label(it, labels) for it in items]


@router.get("/timeseries")
def timeseries(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    bucket: str = Query("hour", pattern="^(hour|day)$"),
    device_id: Optional[str] = None,
    mode: str = Query("raw", pattern="^(raw|apple)$"),
):
    """Soma por hora ou por dia. Default: últimos 7 dias por dia."""
    try:
        s, e = _range_to_unix(start_date, end_date)
        items = reader.summary_timeseries(s, e, bucket=bucket, device_id=device_id, mode=mode)
    except reader.ScreenTimeUnavailable as ex:
        raise HTTPException(503, str(ex))
    return items


@router.get("/timeseries-stacked")
def timeseries_stacked(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    bucket: str = Query("hour", pattern="^(hour|day)$"),
    device_id: Optional[str] = None,
    mode: str = Query("raw", pattern="^(raw|apple)$"),
):
    """Soma por bucket E por categoria (para gráfico empilhado estilo Apple)."""
    try:
        s, e = _range_to_unix(start_date, end_date)
        return reader.timeseries_stacked_by_category(s, e, bucket=bucket, device_id=device_id, mode=mode)
    except reader.ScreenTimeUnavailable as ex:
        raise HTTPException(503, str(ex))


@router.get("/sessions")
def sessions(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    device_id: Optional[str] = None,
    min_seconds: int = 0,
    limit: int = 500,
    db: Session = Depends(get_db),
):
    """Sessões raw, mais recentes primeiro. Útil para debug/verificação."""
    try:
        s, e = _range_to_unix(start_date, end_date)
        items = reader.fetch_sessions(s, e, device_id=device_id, min_seconds=min_seconds)
    except reader.ScreenTimeUnavailable as ex:
        raise HTTPException(503, str(ex))
    return items[:limit]


@router.post("/snapshot")
def trigger_snapshot(days_back: int = Query(45, ge=1, le=730)):
    """Força um snapshot dos agregados diários (arranque chama isto periodicamente)."""
    return {"days_written": snapshot_screen_time(days_back)}


@router.get("/insights")
def insights(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    bucket: str = Query("day"),
    db: Session = Depends(get_db),
):
    """Estatísticas a partir dos snapshots diários guardados (histórico longo).

    Período em [start_date, end_date] (omitir start = desde o 1º dia guardado).
    bucket='day' → série por dia; bucket='month' → série por mês (períodos longos).
    """
    all_rows = db.query(ScreenTimeDailyApp).all()
    all_dates = {r.date for r in all_rows}
    tracked_days = len(all_dates)
    total_all = sum(r.seconds for r in all_rows)

    today = date.today()
    end = date.fromisoformat(end_date) if end_date else today
    if start_date:
        start = date.fromisoformat(start_date)
    elif all_dates:
        start = min(all_dates)
    else:
        start = end
    if start > end:
        start = end

    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)

    period = [r for r in all_rows if start <= r.date <= end]
    prev = [r for r in all_rows if prev_start <= r.date <= prev_end]

    by_day: dict[date, int] = defaultdict(int)
    for r in period:
        by_day[r.date] += r.seconds

    if bucket == "month":
        by_month: dict[str, int] = defaultdict(int)
        for d_, sec in by_day.items():
            by_month[d_.strftime("%Y-%m")] += sec
        timeseries = []
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            key = f"{y:04d}-{m:02d}"
            timeseries.append({"date": key, "seconds": by_month.get(key, 0)})
            m += 1
            if m > 12:
                m, y = 1, y + 1
    else:
        timeseries = [
            {"date": (start + timedelta(days=i)).isoformat(), "seconds": by_day.get(start + timedelta(days=i), 0)}
            for i in range(span)
        ]
    total_period = sum(by_day.values())
    tracked_in_period = len(by_day)
    daily_avg = round(total_period / tracked_in_period) if tracked_in_period else 0
    total_prev = sum(r.seconds for r in prev)
    delta_pct = round((total_period - total_prev) / total_prev * 100) if total_prev else None

    busiest = max(by_day.items(), key=lambda kv: kv[1], default=None)
    quietest = min(by_day.items(), key=lambda kv: kv[1], default=None)

    by_app: dict[str, dict] = defaultdict(lambda: {"seconds": 0, "category": ""})
    for r in period:
        e = by_app[r.bundle_id]
        e["seconds"] += r.seconds
        if r.category:
            e["category"] = r.category
    top_apps = sorted(
        ({"bundle_id": k, "seconds": v["seconds"], "category": v["category"]} for k, v in by_app.items()),
        key=lambda x: x["seconds"], reverse=True,
    )[:12]

    by_cat: dict[str, int] = defaultdict(int)
    for r in period:
        by_cat[r.category or "Other"] += r.seconds
    by_category = sorted(
        ({"category": k, "seconds": v} for k, v in by_cat.items()),
        key=lambda x: x["seconds"], reverse=True,
    )

    wd_total: dict[int, int] = defaultdict(int)
    wd_days: dict[int, set] = defaultdict(set)
    for d_, sec in by_day.items():
        wd_total[d_.weekday()] += sec
        wd_days[d_.weekday()].add(d_)
    by_weekday = [
        {"weekday": wd, "avg_seconds": round(wd_total[wd] / len(wd_days[wd])) if wd_days[wd] else 0}
        for wd in range(7)
    ]

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "bucket": bucket,
        "tracked_days": tracked_days,
        "first_date": min(all_dates).isoformat() if all_dates else None,
        "last_date": max(all_dates).isoformat() if all_dates else None,
        "total_all_seconds": total_all,
        "total_period_seconds": total_period,
        "daily_avg_seconds": daily_avg,
        "total_prev_seconds": total_prev,
        "delta_pct": delta_pct,
        "busiest_day": {"date": busiest[0].isoformat(), "seconds": busiest[1]} if busiest else None,
        "quietest_day": {"date": quietest[0].isoformat(), "seconds": quietest[1]} if quietest else None,
        "timeseries": timeseries,
        "top_apps": top_apps,
        "by_category": by_category,
        "by_weekday": by_weekday,
    }
