"""Lê o knowledgeC.db do macOS para extrair Screen Time (Mac + iPhone + iPad sincronizados).

Requer Full Disk Access para o processo Python que corre o backend
(System Settings → Privacy & Security → Full Disk Access).

A DB usa o "Cocoa epoch" (segundos desde 2001-01-01 UTC). Convertemos sempre
para epoch Unix antes de devolver.

Schema relevante:
- ZOBJECT.ZSTREAMNAME = '/app/usage' → cada linha é uma sessão de uso
- ZOBJECT.ZVALUESTRING → bundle id (com.apple.Safari, etc.)
- ZOBJECT.ZSTARTDATE / ZENDDATE → cocoa epoch
- ZOBJECT.ZSOURCE → FK para ZSOURCE.Z_PK
- ZSOURCE.ZDEVICEID → identificador do device origem
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

KNOWLEDGE_DB = Path.home() / "Library" / "Application Support" / "Knowledge" / "knowledgeC.db"

# 978307200 = unix timestamp de 2001-01-01 00:00:00 UTC (origem do Cocoa epoch)
COCOA_EPOCH_OFFSET = 978307200


class ScreenTimeUnavailable(Exception):
    """Raised quando o knowledgeC.db não é legível (sem Full Disk Access ou inexistente)."""


def _to_unix(cocoa_ts: float | None) -> float | None:
    if cocoa_ts is None:
        return None
    return cocoa_ts + COCOA_EPOCH_OFFSET


def _from_unix(unix_ts: float) -> float:
    return unix_ts - COCOA_EPOCH_OFFSET


@contextmanager
def _open_db():
    if not KNOWLEDGE_DB.exists():
        raise ScreenTimeUnavailable(f"knowledgeC.db não existe em {KNOWLEDGE_DB}")
    try:
        # immutable=1 garante leitura sem locks (Apple processa em background)
        uri = f"file:{KNOWLEDGE_DB}?mode=ro&immutable=1"
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as e:
        raise ScreenTimeUnavailable(
            f"Não consegui abrir knowledgeC.db: {e}. "
            "Confirma que o processo Python tem Full Disk Access."
        )
    try:
        yield conn
    finally:
        conn.close()


def is_available() -> tuple[bool, str]:
    """Devolve (True, '') se a DB é acessível, (False, motivo) caso contrário."""
    if not KNOWLEDGE_DB.exists():
        return False, f"knowledgeC.db não existe em {KNOWLEDGE_DB}"
    try:
        with _open_db() as conn:
            conn.execute("SELECT COUNT(*) FROM ZOBJECT").fetchone()
        return True, ""
    except ScreenTimeUnavailable as e:
        return False, str(e)
    except Exception as e:
        return False, f"Erro inesperado: {e}"


def list_devices() -> list[dict]:
    """Lista os devices distintos vistos no knowledgeC.db.
    Cada item: {device_id, last_seen (unix ts), event_count}"""
    sql = """
        SELECT
          COALESCE(ZSOURCE.ZDEVICEID, '__local__') AS device_id,
          MAX(ZOBJECT.ZSTARTDATE) AS last_cocoa,
          COUNT(*) AS n
        FROM ZOBJECT
        LEFT JOIN ZSOURCE ON ZOBJECT.ZSOURCE = ZSOURCE.Z_PK
        WHERE ZOBJECT.ZSTREAMNAME = '/app/usage'
        GROUP BY device_id
        ORDER BY last_cocoa DESC
    """
    out = []
    with _open_db() as conn:
        for row in conn.execute(sql):
            out.append({
                "device_id": row[0],
                "last_seen": _to_unix(row[1]),
                "event_count": row[2],
            })
    return out


def fetch_sessions(
    start_unix: float,
    end_unix: float,
    device_id: Optional[str] = None,
    min_seconds: int = 0,
) -> list[dict]:
    """Devolve sessões de uso de app entre start/end (unix ts). Filtra por device se dado."""
    start_cocoa = _from_unix(start_unix)
    end_cocoa = _from_unix(end_unix)
    sql = """
        SELECT
          ZOBJECT.ZVALUESTRING AS bundle_id,
          ZOBJECT.ZSTARTDATE AS start_cocoa,
          ZOBJECT.ZENDDATE AS end_cocoa,
          (ZOBJECT.ZENDDATE - ZOBJECT.ZSTARTDATE) AS duration,
          COALESCE(ZSOURCE.ZDEVICEID, '__local__') AS device_id
        FROM ZOBJECT
        LEFT JOIN ZSOURCE ON ZOBJECT.ZSOURCE = ZSOURCE.Z_PK
        WHERE ZOBJECT.ZSTREAMNAME = '/app/usage'
          AND ZOBJECT.ZSTARTDATE >= ?
          AND ZOBJECT.ZSTARTDATE < ?
          AND (ZOBJECT.ZENDDATE - ZOBJECT.ZSTARTDATE) >= ?
    """
    params: list = [start_cocoa, end_cocoa, min_seconds]
    if device_id:
        sql += " AND COALESCE(ZSOURCE.ZDEVICEID, '__local__') = ?"
        params.append(device_id)
    sql += " ORDER BY ZOBJECT.ZSTARTDATE DESC"

    out: list[dict] = []
    with _open_db() as conn:
        for bundle_id, sc, ec, dur, dev in conn.execute(sql, params):
            out.append({
                "bundle_id": bundle_id or "(unknown)",
                "start_unix": _to_unix(sc),
                "end_unix": _to_unix(ec),
                "duration_seconds": float(dur or 0),
                "device_id": dev,
            })
    return out


def summary_by_app(
    start_unix: float,
    end_unix: float,
    device_id: Optional[str] = None,
) -> list[dict]:
    """Agregado por app/bundle_id no intervalo dado."""
    start_cocoa = _from_unix(start_unix)
    end_cocoa = _from_unix(end_unix)
    sql = """
        SELECT
          ZOBJECT.ZVALUESTRING AS bundle_id,
          COALESCE(ZSOURCE.ZDEVICEID, '__local__') AS device_id,
          SUM(ZOBJECT.ZENDDATE - ZOBJECT.ZSTARTDATE) AS total,
          COUNT(*) AS sessions
        FROM ZOBJECT
        LEFT JOIN ZSOURCE ON ZOBJECT.ZSOURCE = ZSOURCE.Z_PK
        WHERE ZOBJECT.ZSTREAMNAME = '/app/usage'
          AND ZOBJECT.ZSTARTDATE >= ?
          AND ZOBJECT.ZSTARTDATE < ?
    """
    params: list = [start_cocoa, end_cocoa]
    if device_id:
        sql += " AND COALESCE(ZSOURCE.ZDEVICEID, '__local__') = ?"
        params.append(device_id)
    sql += " GROUP BY bundle_id, device_id ORDER BY total DESC"

    out: list[dict] = []
    with _open_db() as conn:
        for bundle_id, dev, total, n in conn.execute(sql, params):
            out.append({
                "bundle_id": bundle_id or "(unknown)",
                "device_id": dev,
                "total_seconds": float(total or 0),
                "session_count": int(n or 0),
            })
    return out


def summary_by_device(start_unix: float, end_unix: float) -> list[dict]:
    """Total agregado por device no intervalo."""
    start_cocoa = _from_unix(start_unix)
    end_cocoa = _from_unix(end_unix)
    sql = """
        SELECT
          COALESCE(ZSOURCE.ZDEVICEID, '__local__') AS device_id,
          SUM(ZOBJECT.ZENDDATE - ZOBJECT.ZSTARTDATE) AS total,
          COUNT(*) AS sessions,
          COUNT(DISTINCT ZOBJECT.ZVALUESTRING) AS app_count
        FROM ZOBJECT
        LEFT JOIN ZSOURCE ON ZOBJECT.ZSOURCE = ZSOURCE.Z_PK
        WHERE ZOBJECT.ZSTREAMNAME = '/app/usage'
          AND ZOBJECT.ZSTARTDATE >= ?
          AND ZOBJECT.ZSTARTDATE < ?
        GROUP BY device_id
        ORDER BY total DESC
    """
    out: list[dict] = []
    with _open_db() as conn:
        for dev, total, n, apps in conn.execute(sql, [start_cocoa, end_cocoa]):
            out.append({
                "device_id": dev,
                "total_seconds": float(total or 0),
                "session_count": int(n or 0),
                "app_count": int(apps or 0),
            })
    return out
