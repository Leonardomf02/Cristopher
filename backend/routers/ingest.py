"""Ingestão dos dados locais do Mac (modo híbrido).

O backend corre na cloud (sempre online), mas o Screen Time e o tracker de apps
só existem no Mac. Um agente local (agent/push_local.py) lê esses dados e faz
POST para aqui. Protegido por um token partilhado (env INGEST_TOKEN), não pela
sessão de login — para o agente poder correr sem interação.
"""
import os
from datetime import date as date_cls, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import ScreenTimeDailyApp, AppUsageSession

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

_TOKEN = os.getenv("INGEST_TOKEN", "")


def _check_token(token: str | None):
    if not _TOKEN:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Ingestão desativada (INGEST_TOKEN não definido)")
    if token != _TOKEN:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de ingestão inválido")


# ── Screen Time (snapshot diário por app) ────────────────────────

class ScreenTimeRow(BaseModel):
    date: date_cls
    device_id: str = "__local__"
    bundle_id: str
    category: str = ""
    seconds: int = 0


class ScreenTimePayload(BaseModel):
    rows: list[ScreenTimeRow]


@router.post("/screen-time")
def ingest_screen_time(
    payload: ScreenTimePayload,
    db: Session = Depends(get_db),
    x_ingest_token: str | None = Header(default=None),
):
    _check_token(x_ingest_token)
    upserted = 0
    for r in payload.rows:
        row = (
            db.query(ScreenTimeDailyApp)
            .filter_by(date=r.date, device_id=r.device_id, bundle_id=r.bundle_id)
            .first()
        )
        if row:
            row.seconds = r.seconds
            row.category = r.category
        else:
            db.add(ScreenTimeDailyApp(
                date=r.date, device_id=r.device_id, bundle_id=r.bundle_id,
                category=r.category, seconds=r.seconds,
            ))
        upserted += 1
    db.commit()
    return {"upserted": upserted}


# ── App usage (sessões de janela ativa) ──────────────────────────

class AppUsageRow(BaseModel):
    app_name: str
    window_title: str = ""
    bundle_id: str | None = None
    date: date_cls
    start_time: datetime
    end_time: datetime
    duration_seconds: int


class AppUsagePayload(BaseModel):
    sessions: list[AppUsageRow]


@router.post("/app-usage")
def ingest_app_usage(
    payload: AppUsagePayload,
    db: Session = Depends(get_db),
    x_ingest_token: str | None = Header(default=None),
):
    _check_token(x_ingest_token)
    upserted = 0
    for s in payload.sessions:
        # Dedup pela chave natural de uma sessão: (app_name, start_time).
        row = (
            db.query(AppUsageSession)
            .filter_by(app_name=s.app_name, start_time=s.start_time)
            .first()
        )
        if row:
            row.window_title = s.window_title
            row.end_time = s.end_time
            row.duration_seconds = s.duration_seconds
            row.bundle_id = s.bundle_id
        else:
            db.add(AppUsageSession(
                app_name=s.app_name, window_title=s.window_title, bundle_id=s.bundle_id,
                date=s.date, start_time=s.start_time, end_time=s.end_time,
                duration_seconds=s.duration_seconds,
            ))
        upserted += 1
    db.commit()
    return {"upserted": upserted}
