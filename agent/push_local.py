#!/usr/bin/env python3
"""Agente local do Cristopher (corre no Mac, modo híbrido).

O backend vive na cloud (sempre online), mas o Screen Time (knowledgeC) e o
tracker de apps ativas só existem no Mac. Este agente:
  1. arranca o app_tracker (escreve sessões numa BD local do agente);
  2. periodicamente lê Screen Time + sessões de apps e faz POST para o backend
     cloud em /api/ingest/* (autenticado com INGEST_TOKEN).

Quando o Mac está ligado, sincroniza; quando não está, a web continua online
com os últimos dados. Idempotente: os endpoints fazem upsert, por isso reenviar
as últimas horas/dias não duplica nada.

Env obrigatórias:  CRISTOPHER_CLOUD_URL, INGEST_TOKEN
Env opcionais:     AGENT_DB, PUSH_INTERVAL (s), PUSH_SCREEN_DAYS, PUSH_USAGE_HOURS
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

# Permite importar os módulos do backend (screen_time_reader, database, models)
BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

AGENT_DIR = Path(os.path.expanduser("~/.cristopher-agent"))
AGENT_DIR.mkdir(parents=True, exist_ok=True)
AGENT_DB = os.environ.get("AGENT_DB", str(AGENT_DIR / "agent.db"))

CLOUD_URL = os.environ.get("CRISTOPHER_CLOUD_URL", "").rstrip("/")
INGEST_TOKEN = os.environ.get("INGEST_TOKEN", "")
INTERVAL = int(os.environ.get("PUSH_INTERVAL", "300"))
SCREEN_DAYS = int(os.environ.get("PUSH_SCREEN_DAYS", "3"))
USAGE_HOURS = int(os.environ.get("PUSH_USAGE_HOURS", "48"))

if not CLOUD_URL or not INGEST_TOKEN:
    sys.exit("[agent] define CRISTOPHER_CLOUD_URL e INGEST_TOKEN")

# A BD do agente é dedicada (não a de dev). O tracker escreve aqui.
os.environ["DATABASE_URL"] = f"sqlite:///{AGENT_DB}"
os.environ["TRACKER_DB"] = AGENT_DB

import httpx  # noqa: E402
import database  # noqa: E402
import models  # noqa: F401,E402  (regista as tabelas no metadata)
import screen_time_reader as reader  # noqa: E402

# Garante o schema (cria app_usage_sessions e restantes tabelas na agent.db)
database.Base.metadata.create_all(bind=database.engine)


def _day_range(d: date) -> tuple[float, float]:
    start = datetime(d.year, d.month, d.day).timestamp()
    return start, start + 86400


def _post(path: str, payload: dict) -> None:
    try:
        r = httpx.post(
            CLOUD_URL + path,
            json=payload,
            headers={"X-Ingest-Token": INGEST_TOKEN},
            timeout=30,
        )
        r.raise_for_status()
        print(f"[agent] {path}: {r.json()}", flush=True)
    except Exception as e:
        print(f"[agent] {path} falhou: {e}", file=sys.stderr, flush=True)


def push_screen_time() -> None:
    ok, reason = reader.is_available()
    if not ok:
        print(f"[agent] screen-time indisponível: {reason}", file=sys.stderr, flush=True)
        return
    rows_out: list[dict] = []
    today = date.today()
    for offset in range(SCREEN_DAYS + 1):
        d = today - timedelta(days=offset)
        start_unix, end_unix = _day_range(d)
        try:
            rows = reader.summary_by_app(start_unix, end_unix, mode="apple")
        except Exception:
            continue
        for r in rows:
            seconds = int(round(r.get("total_seconds") or 0))
            if seconds <= 0:
                continue
            rows_out.append({
                "date": d.isoformat(),
                "device_id": r.get("device_id", "__local__"),
                "bundle_id": r.get("bundle_id", "(unknown)"),
                "category": r.get("category", "") or "",
                "seconds": seconds,
            })
    if rows_out:
        _post("/api/ingest/screen-time", {"rows": rows_out})


def push_app_usage() -> None:
    import sqlite3
    # cutoff no MESMO formato que o tracker grava ("YYYY-MM-DD HH:MM:SS"),
    # para a comparação de strings na BD ser correta.
    cutoff = (datetime.now() - timedelta(hours=USAGE_HOURS)).isoformat(sep=" ", timespec="seconds")
    conn = sqlite3.connect(AGENT_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT app_name, window_title, bundle_id, date, start_time, end_time, duration_seconds "
            "FROM app_usage_sessions WHERE end_time >= ? ORDER BY start_time",
            (cutoff,),
        ).fetchall()
    except sqlite3.OperationalError:
        return  # tabela ainda não existe (tracker ainda não escreveu)
    finally:
        conn.close()
    sessions = [{
        "app_name": r["app_name"],
        "window_title": r["window_title"] or "",
        "bundle_id": r["bundle_id"],
        "date": r["date"],
        "start_time": r["start_time"],
        "end_time": r["end_time"],
        "duration_seconds": r["duration_seconds"],
    } for r in rows]
    if sessions:
        _post("/api/ingest/app-usage", {"sessions": sessions})


def start_tracker() -> subprocess.Popen | None:
    script = BACKEND / "app_tracker.py"
    if not script.exists() or sys.platform != "darwin":
        return None
    return subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(BACKEND),
        env={**os.environ, "TRACKER_DB": AGENT_DB},
        start_new_session=True,
    )


def main() -> None:
    proc = start_tracker()

    def _stop(*_):
        if proc:
            proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    print(f"[agent] a empurrar para {CLOUD_URL} a cada {INTERVAL}s", flush=True)
    while True:
        try:
            push_screen_time()
        except Exception as e:
            print(f"[agent] screen-time erro: {e}", file=sys.stderr, flush=True)
        try:
            push_app_usage()
        except Exception as e:
            print(f"[agent] app-usage erro: {e}", file=sys.stderr, flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
