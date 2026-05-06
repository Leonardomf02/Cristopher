"""Endpoints para o Screen Time agregado da Apple (Mac + iPhone + iPad via iCloud sync).

Lê o knowledgeC.db do macOS via screen_time_reader. Os dados de iPhone/iPad só
aparecem se "Share Across Devices" estiver activo no Screen Time da Apple.
"""
from __future__ import annotations

from datetime import datetime, date, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import ScreenTimeDeviceLabel
import screen_time_reader as reader

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


@router.get("/health")
def health():
    """Diz se a DB do Screen Time está acessível ao backend."""
    ok, reason = reader.is_available()
    return {
        "available": ok,
        "reason": reason,
        "db_path": str(reader.KNOWLEDGE_DB),
    }


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
    db: Session = Depends(get_db),
):
    """Agregado por app + device. Default: últimos 7 dias."""
    try:
        s, e = _range_to_unix(start_date, end_date)
        items = reader.summary_by_app(s, e, device_id=device_id)
    except reader.ScreenTimeUnavailable as ex:
        raise HTTPException(503, str(ex))
    labels = _labels_map(db)
    return [_attach_label(it, labels) for it in items]


@router.get("/by-device")
def by_device(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Total agregado por device no intervalo. Default: últimos 7 dias."""
    try:
        s, e = _range_to_unix(start_date, end_date)
        items = reader.summary_by_device(s, e)
    except reader.ScreenTimeUnavailable as ex:
        raise HTTPException(503, str(ex))
    labels = _labels_map(db)
    return [_attach_label(it, labels) for it in items]


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
