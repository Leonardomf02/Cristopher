"""Inscrição dos telemóveis para receber avisos (Web Push)."""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import PushDevice
import push

router = APIRouter(prefix="/api/push", tags=["Push"])


class Subscricao(BaseModel):
    subscription: dict
    label: str = ""


@router.get("/key")
def chave_publica():
    """Chave que o browser precisa para se inscrever."""
    return {"public_key": push.chave_publica()}


@router.get("/devices")
def dispositivos(db: Session = Depends(get_db)):
    linhas = db.query(PushDevice).order_by(PushDevice.created_at.desc()).all()
    return [
        {"id": d.id, "label": d.label or "dispositivo", "active": d.active,
         "created_at": d.created_at.isoformat() if d.created_at else None,
         "last_sent_at": d.last_sent_at.isoformat() if d.last_sent_at else None,
         "last_error": d.last_error}
        for d in linhas
    ]


@router.post("/subscribe")
def subscrever(body: Subscricao, db: Session = Depends(get_db)):
    endpoint = (body.subscription or {}).get("endpoint")
    if not endpoint:
        raise HTTPException(status_code=400, detail="subscrição sem endpoint")
    existente = db.query(PushDevice).filter(PushDevice.endpoint == endpoint).first()
    if existente:
        existente.subscription = json.dumps(body.subscription)
        existente.active = True
        existente.last_error = ""
        if body.label:
            existente.label = body.label[:60]
        db.commit()
        return {"ok": True, "id": existente.id, "novo": False}
    d = PushDevice(endpoint=endpoint, subscription=json.dumps(body.subscription),
                   label=(body.label or "")[:60])
    db.add(d)
    db.commit()
    db.refresh(d)
    return {"ok": True, "id": d.id, "novo": True}


@router.delete("/devices/{device_id}")
def remover(device_id: int, db: Session = Depends(get_db)):
    d = db.query(PushDevice).filter(PushDevice.id == device_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="dispositivo não encontrado")
    db.delete(d)
    db.commit()
    return {"ok": True}


@router.post("/test")
def testar(db: Session = Depends(get_db)):
    from notifier import send_push
    enviados, falhas = send_push("Cristopher", "Se estás a ler isto no telemóvel, está a funcionar.", db=db)
    return {"sent": enviados, "failed": falhas}
