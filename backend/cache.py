"""SQLite-backed cache with TTL.

Persists across reloads (the in-memory dicts in fundamentals_data and SPY history
disappear on every uvicorn --reload). Single-table schema, zero deps.

Usage:
    from cache import cached, cache_get, cache_set

    @cached("fred:macro_snapshot", ttl_seconds=86400)   # 24h
    def fetch_macro_snapshot():
        ...

The decorator includes args in the key so different inputs cache independently.
"""
from __future__ import annotations

import json
import sqlite3
import logging
import threading
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

DB_PATH = "cristopher.db"
TABLE = "api_cache"
_INIT_LOCK = threading.Lock()
_INITIALIZED = False


def _ensure_table() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _INIT_LOCK:
        if _INITIALIZED:
            return
        conn = sqlite3.connect(DB_PATH)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                ttl_seconds INTEGER NOT NULL
            )
        """)
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_fetched_at ON {TABLE}(fetched_at)")
        conn.commit()
        conn.close()
        _INITIALIZED = True


def cache_get(key: str) -> Optional[Any]:
    """Returns cached value or None if missing / expired."""
    _ensure_table()
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            f"SELECT value, fetched_at, ttl_seconds FROM {TABLE} WHERE key = ?",
            (key,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        try:
            fetched = datetime.fromisoformat(row[1])
        except (ValueError, TypeError):
            return None
        age = (datetime.now() - fetched).total_seconds()
        if age > row[2]:
            return None
        return json.loads(row[0])
    except (sqlite3.Error, json.JSONDecodeError) as e:
        logger.debug(f"cache_get({key}) failed: {e}")
        return None


def cache_set(key: str, value: Any, ttl_seconds: int) -> None:
    _ensure_table()
    try:
        payload = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as e:
        logger.warning(f"cache_set({key}): not JSON-serializable: {e}")
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            f"INSERT OR REPLACE INTO {TABLE} (key, value, fetched_at, ttl_seconds) VALUES (?, ?, ?, ?)",
            (key, payload, datetime.now().isoformat(timespec="seconds"), int(ttl_seconds)),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"cache_set({key}) failed: {e}")


def cache_invalidate(prefix: str = "") -> int:
    """Delete all entries matching prefix. Empty string = wipe everything."""
    _ensure_table()
    try:
        conn = sqlite3.connect(DB_PATH)
        if prefix:
            cur = conn.execute(f"DELETE FROM {TABLE} WHERE key LIKE ?", (f"{prefix}%",))
        else:
            cur = conn.execute(f"DELETE FROM {TABLE}")
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return deleted
    except sqlite3.Error as e:
        logger.warning(f"cache_invalidate({prefix}) failed: {e}")
        return 0


def cache_stats() -> dict:
    _ensure_table()
    try:
        conn = sqlite3.connect(DB_PATH)
        total = conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
        rows = conn.execute(
            f"SELECT key, fetched_at, ttl_seconds FROM {TABLE} ORDER BY fetched_at DESC LIMIT 20"
        ).fetchall()
        conn.close()
        recent = []
        now = datetime.now()
        for k, fa, ttl in rows:
            try:
                age = (now - datetime.fromisoformat(fa)).total_seconds()
                recent.append({"key": k, "age_seconds": int(age), "ttl_seconds": ttl, "expired": age > ttl})
            except (ValueError, TypeError):
                continue
        return {"total_entries": total, "recent": recent}
    except sqlite3.Error as e:
        return {"error": str(e), "total_entries": 0, "recent": []}


def cached(key_prefix: str, ttl_seconds: int) -> Callable:
    """Decorator that caches a function's output by (prefix + repr(args)).

    Skip caching by passing `_skip_cache=True` (kwarg, popped before call).
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if kwargs.pop("_skip_cache", False):
                return fn(*args, **kwargs)
            # Build a stable key. Sort kwargs for determinism.
            arg_part = ":".join(repr(a) for a in args)
            kw_part = ":".join(f"{k}={v!r}" for k, v in sorted(kwargs.items()))
            full_key = f"{key_prefix}:{arg_part}:{kw_part}".replace(" ", "")
            cached_val = cache_get(full_key)
            if cached_val is not None:
                return cached_val
            result = fn(*args, **kwargs)
            # Don't cache empty/None — caller can retry next request
            if result not in (None, {}, []):
                cache_set(full_key, result, ttl_seconds)
            return result
        return wrapper
    return decorator
