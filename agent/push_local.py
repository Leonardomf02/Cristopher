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


def _post(path: str, payload: dict, quiet: bool = False) -> None:
    try:
        r = httpx.post(
            CLOUD_URL + path,
            json=payload,
            headers={"X-Ingest-Token": INGEST_TOKEN},
            timeout=30,
        )
        r.raise_for_status()
        if not quiet:      # o champ select vai de 3 em 3 segundos: não se escreve
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


def push_champ_select() -> None:
    """O cliente do LoL só fala com quem está no Mac. Enquanto ele estiver
    aberto, o estado do champ select vai para a app de 3 em 3 segundos — é o
    que faz o draft aparecer na NAS e no telemóvel.

    Corre à parte do resto: um ciclo de 5 minutos não serve para um draft que
    dura um minuto."""
    import asyncio
    import lcu_api

    cliente_estava_aberto = False
    while True:
        try:
            if lcu_api.parse_lockfile() is None:
                if cliente_estava_aberto:      # fechou: dizer uma vez e calar
                    _post("/api/ingest/lol-champ-select", {"client_running": False}, quiet=True)
                    cliente_estava_aberto = False
                time.sleep(20)
                continue

            fase = asyncio.run(lcu_api.get_gameflow_phase())
            sessao = asyncio.run(lcu_api.get_champ_select_session()) if fase == "ChampSelect" else None
            _post("/api/ingest/lol-champ-select",
                  {"client_running": True, "phase": fase, "session": sessao}, quiet=True)
            cliente_estava_aberto = True
            time.sleep(3 if fase == "ChampSelect" else 12)
        except Exception as e:
            print(f"[agent] champ select erro: {e}", file=sys.stderr, flush=True)
            time.sleep(20)


# ── Reminders da Apple ───────────────────────────────────────────
# A NAS decide, o Mac escreve: só o Mac fala com os Reminders (EventKit). O
# agente fica pendurado em /reminders/wait e sincroniza no segundo em que alguma
# coisa muda nas Listas; os Reminders do iPhone são lidos de 25 em 25 segundos.
REMINDERS_PENDENTE = AGENT_DIR / "reminders-aplicado.json"


def _pedido(metodo: str, path: str, timeout: float = 60, **kw) -> dict:
    r = httpx.request(metodo, CLOUD_URL + path, headers={"X-Ingest-Token": INGEST_TOKEN},
                      timeout=timeout, **kw)
    r.raise_for_status()
    return r.json()


def _entrega_pendente() -> dict | None:
    """O que foi escrito na Apple e a NAS ainda não sabe. Tem de chegar lá antes
    de um plano novo, senão o que foi criado ia ser criado outra vez."""
    import json
    if not REMINDERS_PENDENTE.exists():
        return None
    resposta = _pedido("POST", "/api/ingest/reminders/applied",
                       json=json.loads(REMINDERS_PENDENTE.read_text()))
    REMINDERS_PENDENTE.unlink()
    return resposta


def _passagem_reminders(dump: dict) -> str:
    """Uma passagem completa. Devolve a impressão das Listas na NAS depois dela."""
    import json
    import apple_reminders as ar

    _entrega_pendente()
    plano = _pedido("POST", "/api/ingest/reminders/plan", json={"dump": dump})
    ops = plano["ops"]
    if not any(ops.values()):
        return plano["fp"]
    resultado = ar.aplica(ops)
    REMINDERS_PENDENTE.write_text(json.dumps({"ops": ops, "result": resultado, "conta": plano["conta"]}))
    fp = _entrega_pendente()["fp"]
    print(f"[agent] reminders: {ar.resumo(plano['conta'])}", flush=True)
    return fp


def sync_reminders() -> None:
    import hashlib
    import json
    import apple_reminders as ar

    def _marca(d: dict) -> str:
        return hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()

    fp = ""
    ultimo_dump = None
    ultima_passagem = 0.0
    forcar = True
    while True:
        try:
            dump = ar.le_apple()
            if ar.repara_emblemas(dump):
                print("[agent] reminders: ícones das listas reescritos em emoji", flush=True)
                dump = ar.le_apple()
            # de dez em dez minutos passa-se na mesma: uma edição no iPhone no
            # segundo em que o agente estava a escrever ficava de fora da marca
            forcar = forcar or time.time() - ultima_passagem > 600
            if forcar or _marca(dump) != ultimo_dump:
                fp = _passagem_reminders(dump)
                ultima_passagem = time.time()
                # o que o próprio agente escreveu não conta como mudança no iPhone
                ultimo_dump = _marca(ar.le_apple())
            # Pendurado na NAS até 25s: acorda no segundo em que ele mexe nas
            # Listas; se nada mudar, volta a ler os Reminders do iPhone.
            espera = _pedido("GET", "/api/ingest/reminders/wait", timeout=40,
                             params={"since": fp, "timeout": 25})
            forcar = bool(espera.get("changed"))
        except ar.SemAcesso as e:
            print(f"[agent] reminders sem acesso: {e}", file=sys.stderr, flush=True)
            try:
                _pedido("POST", "/api/ingest/reminders/error", json={
                    "error": "O Mac não deu acesso aos Reminders ao agente. Definições do Sistema → "
                             "Privacidade e Segurança → Lembretes."})
            except Exception:
                pass
            time.sleep(300)
        except Exception as e:
            print(f"[agent] reminders erro: {e}", file=sys.stderr, flush=True)
            forcar = True
            time.sleep(20)


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

    if sys.platform == "darwin":
        import threading
        threading.Thread(target=push_champ_select, daemon=True).start()
        if os.environ.get("AGENT_REMINDERS", "1") == "1":
            threading.Thread(target=sync_reminders, daemon=True).start()

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
