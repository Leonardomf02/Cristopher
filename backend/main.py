from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

# Load .env if present (FMP_API_KEY, FINNHUB_API_KEY, etc.)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from database import engine, Base
from routers import events, expenses, lol, trips, lists, sleep, day_types, flow, notes, investments, investment_signals, habits, dashboard, mood, budgets, templates, app_usage, app_insights, app_goals, ideas, code_activity, screen_time

# Create all tables
Base.metadata.create_all(bind=engine)

# Migrations — add missing columns
import sqlite3
_DB_PATH = os.getenv("DATABASE_URL", "sqlite:///./cristopher.db").replace("sqlite:///", "")
_conn = sqlite3.connect(_DB_PATH)
_cur = _conn.cursor()
_cur.execute("PRAGMA table_info(investment_plans)")
_cols = {row[1] for row in _cur.fetchall()}
if "name" not in _cols:
    _cur.execute("ALTER TABLE investment_plans ADD COLUMN name TEXT NOT NULL DEFAULT ''")
    _conn.commit()
# Add is_rotational to investment_allocations
_cur.execute("PRAGMA table_info(investment_allocations)")
_alloc_cols = {row[1] for row in _cur.fetchall()}
if _alloc_cols and "is_rotational" not in _alloc_cols:
    _cur.execute("ALTER TABLE investment_allocations ADD COLUMN is_rotational BOOLEAN DEFAULT 0")
    _conn.commit()
# Add game_hour and team_side to lol_games
_cur.execute("PRAGMA table_info(lol_games)")
_lol_cols = {row[1] for row in _cur.fetchall()}
if _lol_cols and "game_hour" not in _lol_cols:
    _cur.execute("ALTER TABLE lol_games ADD COLUMN game_hour INTEGER")
    _conn.commit()
if _lol_cols and "team_side" not in _lol_cols:
    _cur.execute("ALTER TABLE lol_games ADD COLUMN team_side TEXT")
    _conn.commit()
# Add game_start_time to lol_predictions
_cur.execute("PRAGMA table_info(lol_predictions)")
_pred_cols = {row[1] for row in _cur.fetchall()}
if _pred_cols and "game_start_time" not in _pred_cols:
    _cur.execute("ALTER TABLE lol_predictions ADD COLUMN game_start_time INTEGER")
    _conn.commit()
# Add tags to mood_entries
_cur.execute("PRAGMA table_info(mood_entries)")
_mood_cols = {row[1] for row in _cur.fetchall()}
if _mood_cols and "tags" not in _mood_cols:
    _cur.execute("ALTER TABLE mood_entries ADD COLUMN tags TEXT DEFAULT ''")
    _conn.commit()
# Add audit columns to investment_signals
_cur.execute("PRAGMA table_info(investment_signals)")
_sig_cols = {row[1] for row in _cur.fetchall()}
if _sig_cols and "prompt_hash" not in _sig_cols:
    _cur.execute("ALTER TABLE investment_signals ADD COLUMN prompt_hash TEXT")
    _conn.commit()
if _sig_cols and "prompt_version" not in _sig_cols:
    _cur.execute("ALTER TABLE investment_signals ADD COLUMN prompt_version TEXT DEFAULT 'v1'")
    _conn.commit()
if _sig_cols and "risk_critique_json" not in _sig_cols:
    _cur.execute("ALTER TABLE investment_signals ADD COLUMN risk_critique_json TEXT DEFAULT ''")
    _conn.commit()
# Daily sentiment history (for MA7-MA30 z-score regime detection)
_cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_sentiment (
        date TEXT PRIMARY KEY,
        avg_score REAL NOT NULL,
        pos_n INTEGER NOT NULL DEFAULT 0,
        neg_n INTEGER NOT NULL DEFAULT 0,
        neutral_n INTEGER NOT NULL DEFAULT 0,
        engine TEXT
    )
""")
# Daily funding rate history (BTC perp, for persistence detection)
_cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_funding (
        date TEXT NOT NULL,
        symbol TEXT NOT NULL,
        rate_pct REAL NOT NULL,
        PRIMARY KEY (date, symbol)
    )
""")
# Daily regime classification history (P(risk-off) over time)
_cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_regime (
        date TEXT PRIMARY KEY,
        p_risk_off REAL NOT NULL,
        p_risk_off_rule REAL,
        p_risk_off_hmm REAL,
        classification TEXT NOT NULL
    )
""")
# ── Trip ratings (per-trip aggregate + per-place + free-form entries) ──
_cur.execute("PRAGMA table_info(trips)")
_trip_cols = {row[1] for row in _cur.fetchall()}
for col in ("rating_food", "rating_places", "rating_nightlife", "rating_gajas", "rating_overall"):
    if _trip_cols and col not in _trip_cols:
        _cur.execute(f"ALTER TABLE trips ADD COLUMN {col} REAL")
        _conn.commit()
        _trip_cols.add(col)
# Drop legacy columns from trip_gajas (simplified to name + 5 ratings only)
_cur.execute("PRAGMA table_info(trip_gajas)")
_tg_cols = {row[1] for row in _cur.fetchall()}
for _legacy in ("nationality", "where_met", "notes", "date", "instagram", "hooked_up"):
    if _legacy in _tg_cols:
        try:
            _cur.execute(f"ALTER TABLE trip_gajas DROP COLUMN {_legacy}")
            _conn.commit()
        except Exception:
            pass
# Make rating_overall nullable in trip_gajas — SQLite can't ALTER, so rebuild only if needed
_cur.execute("PRAGMA table_info(trip_gajas)")
_tg_info = _cur.fetchall()
_overall_notnull = any(r[1] == "rating_overall" and r[3] == 1 for r in _tg_info)
if _overall_notnull:
    _cur.execute("""
        CREATE TABLE trip_gajas_new (
            id INTEGER PRIMARY KEY,
            trip_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            rating_face REAL,
            rating_body REAL,
            rating_vibe REAL,
            rating_personality REAL,
            rating_overall REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    _cur.execute("""
        INSERT INTO trip_gajas_new (id, trip_id, name, rating_face, rating_body, rating_vibe, rating_personality, rating_overall, created_at)
        SELECT id, trip_id, name, rating_face, rating_body, rating_vibe, rating_personality, rating_overall, created_at FROM trip_gajas
    """)
    _cur.execute("DROP TABLE trip_gajas")
    _cur.execute("ALTER TABLE trip_gajas_new RENAME TO trip_gajas")
    _cur.execute("CREATE INDEX ix_trip_gajas_trip_id ON trip_gajas(trip_id)")
    _conn.commit()

_cur.execute("PRAGMA table_info(trip_places)")
_tp_cols = {row[1] for row in _cur.fetchall()}
if _tp_cols and "rating" not in _tp_cols:
    _cur.execute("ALTER TABLE trip_places ADD COLUMN rating REAL")
    _conn.commit()
if _tp_cols and "review" not in _tp_cols:
    _cur.execute("ALTER TABLE trip_places ADD COLUMN review TEXT DEFAULT ''")
    _conn.commit()

# ── LoL seasons (auto-archive on reset detection) ──
_cur.execute("PRAGMA table_info(lol_games)")
_lg_cols = {row[1] for row in _cur.fetchall()}
if _lg_cols and "season_id" not in _lg_cols:
    _cur.execute("ALTER TABLE lol_games ADD COLUMN season_id INTEGER")
    _conn.commit()
_cur.execute("PRAGMA table_info(lol_rank_snapshots)")
_lrs_cols = {row[1] for row in _cur.fetchall()}
if _lrs_cols and "season_id" not in _lrs_cols:
    _cur.execute("ALTER TABLE lol_rank_snapshots ADD COLUMN season_id INTEGER")
    _conn.commit()
_cur.execute("PRAGMA table_info(lol_predictions)")
_lp_cols = {row[1] for row in _cur.fetchall()}
if _lp_cols and "season_id" not in _lp_cols:
    _cur.execute("ALTER TABLE lol_predictions ADD COLUMN season_id INTEGER")
    _conn.commit()

# Bootstrap initial active season if none exists, and tag legacy rows
_cur.execute("SELECT id FROM lol_seasons LIMIT 1")
if not _cur.fetchone():
    # Find earliest game date for season start; fall back to today
    _cur.execute("SELECT MIN(date) FROM lol_games")
    _row = _cur.fetchone()
    _start = (_row[0] if _row and _row[0] else None)
    if not _start:
        from datetime import date as _d
        _start = _d.today().isoformat()
    # Seed max_ranked_total from latest rank snapshot if available
    _cur.execute("SELECT wins, losses FROM lol_rank_snapshots ORDER BY date DESC LIMIT 1")
    _rs = _cur.fetchone()
    _max_total = (_rs[0] or 0) + (_rs[1] or 0) if _rs else 0
    # Compute totals from games
    _cur.execute("SELECT COUNT(*), SUM(CASE WHEN won THEN 1 ELSE 0 END) FROM lol_games")
    _g = _cur.fetchone()
    _total = _g[0] or 0
    _wins = _g[1] or 0
    _cur.execute(
        "INSERT INTO lol_seasons (label, start_date, end_date, max_ranked_total, total_games, total_wins, total_losses) "
        "VALUES (?, ?, NULL, ?, ?, ?, ?)",
        ("Season 1", _start, _max_total, _total, _wins, _total - _wins),
    )
    _conn.commit()
    _season_id = _cur.lastrowid
    # Backfill all existing rows to this season
    _cur.execute("UPDATE lol_games SET season_id = ? WHERE season_id IS NULL", (_season_id,))
    _cur.execute("UPDATE lol_rank_snapshots SET season_id = ? WHERE season_id IS NULL", (_season_id,))
    _cur.execute("UPDATE lol_predictions SET season_id = ? WHERE season_id IS NULL", (_season_id,))
    _conn.commit()

_conn.commit()
_conn.close()

app = FastAPI(title="Cristopher", description="Personal Life Manager", version="1.0.0")

# CORS: aceita localhost (qualquer porta), IPs locais (192.168/10/172.16-31)
# e qualquer host *.ts.net (Tailscale). Origens extra via ALLOWED_ORIGINS.
_extra_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
_origin_regex = (
    r"^(https?://localhost(:\d+)?"
    r"|https?://127\.0\.0\.1(:\d+)?"
    r"|https?://192\.168\.\d+\.\d+(:\d+)?"
    r"|https?://10\.\d+\.\d+\.\d+(:\d+)?"
    r"|https?://172\.(1[6-9]|2\d|3[01])\.\d+\.\d+(:\d+)?"
    r"|https?://[a-zA-Z0-9-]+\.[a-zA-Z0-9-]+\.ts\.net(:\d+)?)$"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_extra_origins,
    allow_origin_regex=_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for uploaded receipts
_UPLOADS_DIR = os.getenv("UPLOADS_DIR", "uploads")
os.makedirs(os.path.join(_UPLOADS_DIR, "receipts"), exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_UPLOADS_DIR), name="uploads")

# Routers
app.include_router(events.router)
app.include_router(expenses.router)
app.include_router(lol.router)
app.include_router(trips.router)
app.include_router(lists.router)
app.include_router(sleep.router)
app.include_router(day_types.router)
app.include_router(flow.router)
app.include_router(notes.router)
app.include_router(investments.router)
app.include_router(investment_signals.router)
app.include_router(habits.router)
app.include_router(dashboard.router)
app.include_router(mood.router)
app.include_router(budgets.router)
app.include_router(templates.router)
app.include_router(app_usage.router)
app.include_router(app_insights.router)
app.include_router(app_goals.router)
app.include_router(ideas.router)
app.include_router(code_activity.router)
app.include_router(screen_time.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": "Cristopher"}


# ── App-usage tracker auto-start ─────────────────────────────────
# Garante que o tracker (app_tracker.py) está sempre a correr enquanto o
# backend está vivo. Usa um pidfile para não duplicar processos quando o
# uvicorn --reload reinicia o app.

import sys
import subprocess
import atexit
import signal as _signal_mod
from pathlib import Path

_TRACKER_DIR = Path(__file__).parent
_TRACKER_PIDFILE = _TRACKER_DIR / "app_tracker.pid"
_TRACKER_SCRIPT = _TRACKER_DIR / "app_tracker.py"
_tracker_proc: subprocess.Popen | None = None


def _tracker_pid_alive() -> int | None:
    if not _TRACKER_PIDFILE.exists():
        return None
    try:
        pid = int(_TRACKER_PIDFILE.read_text().strip())
        os.kill(pid, 0)  # raises if dead
        return pid
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        try:
            _TRACKER_PIDFILE.unlink(missing_ok=True)
        except Exception:
            pass
        return None


@app.on_event("startup")
def _start_app_tracker():
    global _tracker_proc
    if os.getenv("TRACKER_AUTOSTART", "1") != "1":
        return
    if sys.platform != "darwin":
        return
    if not _TRACKER_SCRIPT.exists():
        return
    if _tracker_pid_alive() is not None:
        return  # já está a correr (provavelmente de um reload anterior)
    try:
        _tracker_proc = subprocess.Popen(
            [sys.executable, str(_TRACKER_SCRIPT)],
            cwd=str(_TRACKER_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _TRACKER_PIDFILE.write_text(str(_tracker_proc.pid))
    except Exception as e:
        print(f"[main] failed to start app_tracker: {e}", file=sys.stderr)


@app.on_event("shutdown")
def _stop_app_tracker():
    global _tracker_proc
    pid = _tracker_pid_alive()
    if pid is None:
        return
    try:
        os.kill(pid, _signal_mod.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        _TRACKER_PIDFILE.unlink(missing_ok=True)
    except Exception:
        pass
    _tracker_proc = None


atexit.register(_stop_app_tracker)
