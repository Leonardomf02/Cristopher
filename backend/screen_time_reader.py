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

import math
import os
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from screen_time_categories import category_for, CATEGORY_ORDER

# "Modo Apple": parâmetros que aproximam a agregação que o Settings → Screen Time
# da Apple mostra. Foram afinados via reverse-engineering público (mac4n6,
# ActivityWatch import-screentime). Não chega a 100% — Apple usa lógica privada
# no ScreenTimeAgent que combina vários streams.
APPLE_GAP_MERGE_SECONDS = 30
APPLE_CEIL_TO_MINUTE = True

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
        # mode=ro: read-only. Sem immutable=1 — a Apple escreve continuamente neste
        # ficheiro e immutable=1 levava o SQLite a servir snapshots stale.
        uri = f"file:{KNOWLEDGE_DB}?mode=ro"
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


def _apple_merge_sessions(
    sessions: list[dict],
    gap_seconds: float = APPLE_GAP_MERGE_SECONDS,
) -> list[dict]:
    """Funde sessões consecutivas da mesma (bundle_id, device_id) com gap curto,
    desde que nenhuma outra app esteja em foreground durante o gap.

    Replica o gap-merge da Apple. A condição de "nenhuma outra app" evita inflar
    valores quando o user alterna entre apps rapidamente.
    """
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for s in sessions:
        groups[(s["bundle_id"], s["device_id"])].append(s)

    # Para cada device, lista de (start, end, bundle) ordenada — usada para detectar
    # overlap de outras apps no gap.
    by_device: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
    for s in sessions:
        by_device[s["device_id"]].append((s["start_unix"], s["end_unix"], s["bundle_id"]))
    for dev_id in by_device:
        by_device[dev_id].sort()

    def gap_is_clear(dev_id: str, bundle: str, gap_start: float, gap_end: float) -> bool:
        for st, en, b in by_device.get(dev_id, ()):
            if b == bundle:
                continue
            if st >= gap_end:
                break
            if en > gap_start:
                return False
        return True

    merged: list[dict] = []
    for (bundle_id, dev_id), group in groups.items():
        group.sort(key=lambda x: x["start_unix"])
        current: Optional[dict] = None
        for s in group:
            if current is None:
                current = dict(s)
                continue
            gap = s["start_unix"] - current["end_unix"]
            if gap < gap_seconds and gap_is_clear(dev_id, bundle_id, current["end_unix"], s["start_unix"]):
                current["end_unix"] = max(current["end_unix"], s["end_unix"])
                current["duration_seconds"] = current["end_unix"] - current["start_unix"]
            else:
                merged.append(current)
                current = dict(s)
        if current is not None:
            merged.append(current)
    return merged


def _apple_ceil_minute(rows: list[dict], key: str = "total_seconds") -> list[dict]:
    """Arredonda totais ao minuto superior (replica o ceil que a Apple aplica no Settings)."""
    for r in rows:
        sec = float(r.get(key, 0) or 0)
        if sec > 0:
            r[key] = math.ceil(sec / 60.0) * 60
    return rows


def summary_by_app(
    start_unix: float,
    end_unix: float,
    device_id: Optional[str] = None,
    mode: str = "raw",
) -> list[dict]:
    """Agregado por app/bundle_id no intervalo dado.

    mode='raw' (default): soma directa das durações em /app/usage.
    mode='apple': aplica gap-merge (60s) + ceil ao minuto por app — aproxima Settings.
    """
    if mode == "apple":
        sessions = fetch_sessions(start_unix, end_unix, device_id=device_id)
        merged = _apple_merge_sessions(sessions)
        agg: dict[tuple[str, str], dict] = {}
        for s in merged:
            key = (s["bundle_id"], s["device_id"])
            row = agg.setdefault(key, {
                "bundle_id": s["bundle_id"],
                "device_id": s["device_id"],
                "category": category_for(s["bundle_id"]),
                "total_seconds": 0.0,
                "session_count": 0,
            })
            row["total_seconds"] += float(s["duration_seconds"] or 0)
            row["session_count"] += 1
        rows = sorted(agg.values(), key=lambda r: r["total_seconds"], reverse=True)
        if APPLE_CEIL_TO_MINUTE:
            rows = _apple_ceil_minute(rows)
        return rows

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
            bid = bundle_id or "(unknown)"
            out.append({
                "bundle_id": bid,
                "device_id": dev,
                "category": category_for(bid),
                "total_seconds": float(total or 0),
                "session_count": int(n or 0),
            })
    return out


def summary_timeseries(
    start_unix: float,
    end_unix: float,
    bucket: str = "hour",
    device_id: Optional[str] = None,
    mode: str = "raw",
) -> list[dict]:
    """Soma duração por bucket temporal ("hour" ou "day") no intervalo [start, end).

    Sessões que cruzam fronteiras de buckets são repartidas proporcionalmente — assim
    uma sessão de 23:50 a 00:30 conta 10min na hora 23 e 30min na hora 0 (igual ao
    que a Apple mostra). Devolve TODOS os buckets do intervalo, mesmo com total=0.

    mode='apple' aplica gap-merge antes de bucketing (sem ceil — ceil só aplica em
    totais por app).
    """
    if bucket not in ("hour", "day"):
        raise ValueError(f"bucket inválido: {bucket}")
    step = 3600 if bucket == "hour" else 86400

    # alinha o início no bucket
    aligned_start = (int(start_unix) // step) * step
    aligned_end = ((int(end_unix) - 1) // step + 1) * step
    n_buckets = int((aligned_end - aligned_start) // step)
    totals = [0.0] * n_buckets

    sessions = fetch_sessions(start_unix, end_unix, device_id=device_id)
    if mode == "apple":
        sessions = _apple_merge_sessions(sessions)
    for s in sessions:
        s_start = max(float(s["start_unix"]), float(aligned_start))
        s_end = min(float(s["end_unix"]), float(aligned_end))
        if s_end <= s_start:
            continue
        # reparte por buckets
        t = s_start
        while t < s_end:
            bucket_idx = int((t - aligned_start) // step)
            bucket_end = aligned_start + (bucket_idx + 1) * step
            slice_end = min(bucket_end, s_end)
            totals[bucket_idx] += (slice_end - t)
            t = slice_end

    return [
        {
            "bucket_start": aligned_start + i * step,
            "total_seconds": totals[i],
        }
        for i in range(n_buckets)
    ]


def summary_by_category(
    start_unix: float,
    end_unix: float,
    device_id: Optional[str] = None,
    mode: str = "raw",
) -> list[dict]:
    """Agregado por categoria estilo Apple (Social, Productivity & Finance, etc.).

    Reutiliza summary_by_app e mapeia bundle_id → categoria. A primeira entrada é
    sempre 'All Usage' (total). Categorias com 0s não são incluídas.
    """
    app_rows = summary_by_app(start_unix, end_unix, device_id=device_id, mode=mode)
    cat_totals: dict[str, dict] = {}
    grand_total = 0.0
    grand_apps: set[str] = set()
    for r in app_rows:
        cat = category_for(r["bundle_id"])
        entry = cat_totals.setdefault(cat, {
            "category": cat,
            "total_seconds": 0.0,
            "app_count": 0,
            "apps": set(),
        })
        entry["total_seconds"] += float(r["total_seconds"] or 0)
        entry["apps"].add(r["bundle_id"])
        grand_total += float(r["total_seconds"] or 0)
        grand_apps.add(r["bundle_id"])

    out: list[dict] = [{
        "category": "All Usage",
        "total_seconds": grand_total,
        "app_count": len(grand_apps),
    }]
    # Ordena pela ordem que a Apple usa, ignorando categorias vazias.
    for cat in CATEGORY_ORDER:
        if cat not in cat_totals:
            continue
        e = cat_totals[cat]
        out.append({
            "category": cat,
            "total_seconds": e["total_seconds"],
            "app_count": len(e["apps"]),
        })
    return out


def timeseries_stacked_by_category(
    start_unix: float,
    end_unix: float,
    bucket: str = "hour",
    device_id: Optional[str] = None,
    mode: str = "raw",
) -> list[dict]:
    """Por bucket, retorna soma por categoria. Usado para o gráfico empilhado.

    Output: [{bucket_start, categories: {Social: 120, 'Productivity & Finance': 300, ...}}].
    Sessões que cruzam fronteiras são repartidas proporcionalmente.
    """
    if bucket not in ("hour", "day"):
        raise ValueError(f"bucket inválido: {bucket}")
    step = 3600 if bucket == "hour" else 86400

    aligned_start = (int(start_unix) // step) * step
    aligned_end = ((int(end_unix) - 1) // step + 1) * step
    n_buckets = int((aligned_end - aligned_start) // step)
    bucket_data: list[defaultdict] = [defaultdict(float) for _ in range(n_buckets)]

    sessions = fetch_sessions(start_unix, end_unix, device_id=device_id)
    if mode == "apple":
        sessions = _apple_merge_sessions(sessions)

    for s in sessions:
        cat = category_for(s["bundle_id"])
        s_start = max(float(s["start_unix"]), float(aligned_start))
        s_end = min(float(s["end_unix"]), float(aligned_end))
        if s_end <= s_start:
            continue
        t = s_start
        while t < s_end:
            bucket_idx = int((t - aligned_start) // step)
            bucket_end = aligned_start + (bucket_idx + 1) * step
            slice_end = min(bucket_end, s_end)
            bucket_data[bucket_idx][cat] += (slice_end - t)
            t = slice_end

    return [
        {
            "bucket_start": aligned_start + i * step,
            "categories": dict(bucket_data[i]),
        }
        for i in range(n_buckets)
    ]


def summary_by_device(start_unix: float, end_unix: float, mode: str = "raw") -> list[dict]:
    """Total agregado por device no intervalo. mode='apple' aplica gap-merge + ceil."""
    if mode == "apple":
        sessions = fetch_sessions(start_unix, end_unix)
        merged = _apple_merge_sessions(sessions)
        agg: dict[str, dict] = {}
        apps_per_dev: dict[str, set] = defaultdict(set)
        for s in merged:
            dev = s["device_id"]
            row = agg.setdefault(dev, {
                "device_id": dev,
                "total_seconds": 0.0,
                "session_count": 0,
                "app_count": 0,
            })
            row["total_seconds"] += float(s["duration_seconds"] or 0)
            row["session_count"] += 1
            apps_per_dev[dev].add(s["bundle_id"])
        for dev, row in agg.items():
            row["app_count"] = len(apps_per_dev[dev])
        rows = sorted(agg.values(), key=lambda r: r["total_seconds"], reverse=True)
        if APPLE_CEIL_TO_MINUTE:
            rows = _apple_ceil_minute(rows)
        return rows

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
