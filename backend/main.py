from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

# Load .env if present (FMP_API_KEY, FINNHUB_API_KEY, etc.)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from typing import Optional
from sqlalchemy import text
from database import engine, Base, SessionLocal
from routers import events, expenses, lol, trips, lists, sleep, day_types, flow, notes, investments, investment_signals, habits, dashboard, mood, budgets, templates, app_usage, app_insights, app_goals, ideas, code_activity, screen_time, wakatime, deals, stories, spotify, day_planner, wishlist, search, ask, quick, day, push_router, scorecard, banking, garmin, meals, nights

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

# Relógio: peso da prontidão por factor, idade de fitness e peso corporal —
# tudo o que a Garmin sabe e não estava a ser lido.
_cur.execute("PRAGMA table_info(garmin_days)")
_cols = {row[1] for row in _cur.fetchall()}
for _coluna in ("readiness_sleep_pct", "readiness_hrv_pct", "readiness_recovery_pct",
                "readiness_load_pct", "readiness_stress_pct"):
    if _coluna not in _cols:
        _cur.execute(f"ALTER TABLE garmin_days ADD COLUMN {_coluna} INTEGER")
for _coluna in ("fitness_age", "fitness_age_achievable", "vigorous_min_avg",
                "vigorous_days_avg", "bmi", "weight_kg"):
    if _coluna not in _cols:
        _cur.execute(f"ALTER TABLE garmin_days ADD COLUMN {_coluna} FLOAT")
_cur.execute("PRAGMA table_info(garmin_series)")
_serie_cols = {row[1] for row in _cur.fetchall()}
for _coluna in ("steps_json", "events_json"):
    if _coluna not in _serie_cols:
        _cur.execute(f"ALTER TABLE garmin_series ADD COLUMN {_coluna} TEXT DEFAULT ''")
_cur.execute("PRAGMA table_info(garmin_activities)")
if "auto" not in {row[1] for row in _cur.fetchall()}:
    _cur.execute("ALTER TABLE garmin_activities ADD COLUMN auto BOOLEAN DEFAULT 0")
_cur.execute("PRAGMA table_info(garmin_activities)")
_ga_cols = {row[1] for row in _cur.fetchall()}
if _ga_cols and "habit_checked" not in _ga_cols:
    _cur.execute("ALTER TABLE garmin_activities ADD COLUMN habit_checked BOOLEAN DEFAULT 0")
_cur.execute("PRAGMA table_info(night_outs)")
_no_cols = {row[1] for row in _cur.fetchall()}
if _no_cols and "drink_level" not in _no_cols:
    _cur.execute("ALTER TABLE night_outs ADD COLUMN drink_level INTEGER")
_conn.commit()
# Ordem das listas dos Reminders, arrastada por ele em vez da data de criação
_cur.execute("PRAGMA table_info(user_lists)")
_ul_cols = {row[1] for row in _cur.fetchall()}
if _ul_cols and "position" not in _ul_cols:
    _cur.execute("ALTER TABLE user_lists ADD COLUMN position INTEGER DEFAULT 0")
    _cur.execute("UPDATE user_lists SET position = id")
    _conn.commit()
# Ligação ao Reminders da Apple: que lista/reminder cada coisa espelha, e quando
# foi alterada deste lado (é isso que decide quem ganha um conflito)
if _ul_cols and "apple_id" not in _ul_cols:
    _cur.execute("ALTER TABLE user_lists ADD COLUMN apple_id TEXT")
    _conn.commit()
_cur.execute("PRAGMA table_info(list_items)")
_li_cols = {row[1] for row in _cur.fetchall()}
if _li_cols and "apple_id" not in _li_cols:
    _cur.execute("ALTER TABLE list_items ADD COLUMN apple_id TEXT")
    _cur.execute("CREATE INDEX IF NOT EXISTS ix_list_items_apple_id ON list_items (apple_id)")
    _conn.commit()
if _li_cols and "updated_at" not in _li_cols:
    _cur.execute("ALTER TABLE list_items ADD COLUMN updated_at DATETIME")
    # Sem isto, tudo o que já existia parecia mais velho do que qualquer reminder
    # e a primeira sincronização deixava a Apple ganhar todos os conflitos.
    _cur.execute("UPDATE list_items SET updated_at = COALESCE(checked_at, created_at)")
    _conn.commit()
# Quando cada conta do banco foi sincronizada (o banco limita pedidos por dia)
_cur.execute("PRAGMA table_info(bank_accounts)")
_ba_cols = {row[1] for row in _cur.fetchall()}
if _ba_cols and "last_sync_at" not in _ba_cols:
    _cur.execute("ALTER TABLE bank_accounts ADD COLUMN last_sync_at DATETIME")
    _conn.commit()
# Add kind to waka_project_days
_cur.execute("PRAGMA table_info(waka_project_days)")
_waka_cols = {row[1] for row in _cur.fetchall()}
if _waka_cols and "kind" not in _waka_cols:
    _cur.execute("ALTER TABLE waka_project_days ADD COLUMN kind TEXT NOT NULL DEFAULT 'project'")
    _conn.commit()
# Add is_rotational to investment_allocations
_cur.execute("PRAGMA table_info(investment_allocations)")
_alloc_cols = {row[1] for row in _cur.fetchall()}
if _alloc_cols and "is_rotational" not in _alloc_cols:
    _cur.execute("ALTER TABLE investment_allocations ADD COLUMN is_rotational BOOLEAN DEFAULT 0")
    _conn.commit()
# Monthly plan execution snapshot (locker)
_cur.execute("PRAGMA table_info(investment_monthly_plans)")
_mp_cols = {row[1] for row in _cur.fetchall()}
if _mp_cols and "executed_at" not in _mp_cols:
    _cur.execute("ALTER TABLE investment_monthly_plans ADD COLUMN executed_at DATETIME")
    _conn.commit()
if _mp_cols and "executed_snapshot" not in _mp_cols:
    _cur.execute("ALTER TABLE investment_monthly_plans ADD COLUMN executed_snapshot TEXT")
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
# Mood: migrate from 1-5 scale to 0-10 rating + quality category
if _mood_cols and "quality" not in _mood_cols:
    _cur.execute("ALTER TABLE mood_entries ADD COLUMN quality TEXT DEFAULT ''")
    # Existing rows used a 1-5 mood; convert to 0-10 and assign a category once.
    _cur.execute("SELECT id, mood FROM mood_entries")
    for _id, _old in _cur.fetchall():
        _r = max(0, min(10, (_old or 0) * 2))
        _q = "great" if _r >= 9 else "good" if _r >= 7 else "meh" if _r >= 4 else "bad"
        _cur.execute("UPDATE mood_entries SET mood = ?, quality = ? WHERE id = ?", (_r, _q, _id))
    _conn.commit()
# Add source (manual|auto) to sleep_entries
_cur.execute("PRAGMA table_info(sleep_entries)")
_sleep_cols = {row[1] for row in _cur.fetchall()}
if _sleep_cols and "source" not in _sleep_cols:
    _cur.execute("ALTER TABLE sleep_entries ADD COLUMN source TEXT DEFAULT 'manual'")
    _conn.commit()
# Tipo de movimento: gasto, entrada, transferência entre contas dele, estorno.
# Sem isto, mandar 300€ para a corretora contava como ter gasto 300€.
_cur.execute("PRAGMA table_info(expenses)")
_exp_cols = {row[1] for row in _cur.fetchall()}
if _exp_cols and "kind" not in _exp_cols:
    _cur.execute("ALTER TABLE expenses ADD COLUMN kind TEXT DEFAULT 'spend'")
    _cur.execute("CREATE INDEX IF NOT EXISTS ix_expenses_kind ON expenses(kind)")
    _conn.commit()
# Id do movimento/execução no broker: é o que evita duplicar o que a API do
# Trading 212 traz todos os dias em cima do que já veio dos extractos.
for _tabela in ("investment_trades", "investment_transactions"):
    _cur.execute(f"PRAGMA table_info({_tabela})")
    _cols_broker = {row[1] for row in _cur.fetchall()}
    if _cols_broker and "external_id" not in _cols_broker:
        _cur.execute(f"ALTER TABLE {_tabela} ADD COLUMN external_id TEXT")
        _cur.execute(f"CREATE INDEX IF NOT EXISTS ix_{_tabela}_external_id ON {_tabela}(external_id)")
        _conn.commit()
# Tipos de dia: conjunto reduzido (Trabalho/Aulas/Projetos/Livre/Férias) — remapeia os antigos
_cur.execute("PRAGMA table_info(day_types)")
if {row[1] for row in _cur.fetchall()}:
    for _old, _new, _color in [
        ("Dia Livre", "Livre", "#22C55E"),
        ("Folga", "Livre", "#22C55E"),
        ("Lazer", "Livre", "#22C55E"),
        ("Pessoal", "Projetos", "#06B6D4"),
        ("Estudo", "Aulas", "#F97316"),
        ("Viagem", "Férias", "#8B5CF6"),
        ("Doente", "Férias", "#8B5CF6"),
    ]:
        _cur.execute("UPDATE day_types SET type_name = ?, color = ? WHERE type_name = ?", (_new, _color, _old))
    _conn.commit()
# Per-occurrence completion for recurring events (instâncias virtuais não têm linha própria)
_cur.execute("PRAGMA table_info(events)")
_ev_cols = {row[1] for row in _cur.fetchall()}
if _ev_cols and "recurrence_completions" not in _ev_cols:
    _cur.execute("ALTER TABLE events ADD COLUMN recurrence_completions TEXT DEFAULT '[]'")
    _conn.commit()
if _ev_cols and "completed_at" not in _ev_cols:
    _cur.execute("ALTER TABLE events ADD COLUMN completed_at TEXT")
    _conn.commit()
# Notes: clear the old orange default colour (it was never user-selectable) → black
_cur.execute("PRAGMA table_info(notes)")
_notes_cols = {row[1] for row in _cur.fetchall()}
if _notes_cols:
    _cur.execute("UPDATE notes SET color = '' WHERE color = '#F59E0B'")
    _conn.commit()
if _notes_cols and "project_path" not in _notes_cols:
    _cur.execute("ALTER TABLE notes ADD COLUMN project_path TEXT")
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
# Day planner: split activities into multiple blocks
_cur.execute("PRAGMA table_info(day_activities)")
_da_cols = {row[1] for row in _cur.fetchall()}
if _da_cols and "splittable" not in _da_cols:
    _cur.execute("ALTER TABLE day_activities ADD COLUMN splittable BOOLEAN DEFAULT 0")
    _conn.commit()
if _da_cols and "chunk_max" not in _da_cols:
    _cur.execute("ALTER TABLE day_activities ADD COLUMN chunk_max INTEGER")
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

# ── LoL: duelo com o jungler adversário ──
# Tabela nova (o create_all trata dela); isto só apanha bases criadas antes das
# colunas da timeline existirem.
_cur.execute("PRAGMA table_info(lol_duels)")
_duel_cols = {row[1] for row in _cur.fetchall()}
if _duel_cols:
    for _col, _tipo in (("gd10", "INTEGER"), ("gd15", "INTEGER"), ("gd20", "INTEGER"),
                        ("xd10", "INTEGER"), ("xd15", "INTEGER"),
                        ("enemy_half_pct", "REAL"), ("has_timeline", "BOOLEAN")):
        if _col not in _duel_cols:
            _cur.execute(f"ALTER TABLE lol_duels ADD COLUMN {_col} {_tipo}")
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

# Tracker: domínio do separador activo do browser (o URL já era lido e deitado fora)
_cur.execute("PRAGMA table_info(app_usage_sessions)")
_aus_cols = {row[1] for row in _cur.fetchall()}
if _aus_cols and "domain" not in _aus_cols:
    _cur.execute("ALTER TABLE app_usage_sessions ADD COLUMN domain TEXT")
    _cur.execute("CREATE INDEX IF NOT EXISTS ix_app_usage_domain ON app_usage_sessions(domain)")
    _conn.commit()

# Spotify: sugestões podem ser de um grupo de género (Visão Geral), não só de playlist
_cur.execute("PRAGMA table_info(spotify_suggestions)")
_sug_cols = {row[1] for row in _cur.fetchall()}
if _sug_cols and "group_name" not in _sug_cols:
    _cur.execute("ALTER TABLE spotify_suggestions ADD COLUMN group_name TEXT")
    _conn.commit()

# Metas de ecrã: tectos semanais e metas diárias eram duas tabelas para a
# mesma ideia (uma meta por categoria) — juntam-se numa só. Dia/semana/mês não
# são metas diferentes, são só a forma de ver o progresso (a semana multiplica
# o alvo diário pelos dias que contam nela — ver screen_time.goals_status),
# por isso a tabela não tem period nenhum. As tabelas antigas ficam por tocar
# (ninguém as lê mais, e apagar arrisca perder dados por um bug de migração
# que só se via depois).
_cur.execute("PRAGMA table_info(screen_time_goals)")
_stg_cols = {row[1] for row in _cur.fetchall()}
if _stg_cols and "period" in _stg_cols:
    # Versão intermédia desta tabela (tinha period, uma linha por categoria e
    # ritmo) — volta a ser uma linha por categoria, preferindo a que tiver
    # hábito associado (é a mais informativa das repetidas).
    _cur.execute("""
        CREATE TABLE screen_time_goals_new (
            id INTEGER PRIMARY KEY,
            category TEXT NOT NULL UNIQUE,
            target_hours REAL NOT NULL,
            days TEXT DEFAULT 'daily',
            habit_id INTEGER,
            active BOOLEAN DEFAULT 1,
            created_at DATETIME
        )
    """)
    _cur.execute("""
        INSERT OR IGNORE INTO screen_time_goals_new (category, target_hours, days, habit_id, active, created_at)
        SELECT category, target_hours, days, habit_id, active, created_at
        FROM screen_time_goals
        ORDER BY (habit_id IS NULL), id
    """)
    _cur.execute("DROP TABLE screen_time_goals")
    _cur.execute("ALTER TABLE screen_time_goals_new RENAME TO screen_time_goals")
    _conn.commit()

_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='screen_time_limits'")
if _cur.fetchone():
    _cur.execute("SELECT category, weekly_hours, active FROM screen_time_limits")
    for _cat, _hours, _active in _cur.fetchall():
        _cur.execute(
            "INSERT OR IGNORE INTO screen_time_goals (category, target_hours, days, habit_id, active) "
            "VALUES (?, ?, 'daily', NULL, ?)",
            (_cat, round(_hours / 7, 2), _active),
        )
    _conn.commit()
_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='screen_time_daily_goals'")
if _cur.fetchone():
    _cur.execute("SELECT category, target_hours, habit_id, active FROM screen_time_daily_goals")
    for _cat, _hours, _habit_id, _active in _cur.fetchall():
        _cur.execute(
            "INSERT OR IGNORE INTO screen_time_goals (category, target_hours, days, habit_id, active) "
            "VALUES (?, ?, 'daily', ?, ?)",
            (_cat, _hours, _habit_id, _active),
        )
    _conn.commit()

_conn.commit()
_conn.close()

# Com password (na NAS, aberta à internet) o mapa da API não fica à vista de quem passa.
_docs_publicos = not os.getenv("CRISTOPHER_PASSWORD")
app = FastAPI(title="Cristopher", description="Personal Life Manager", version="1.0.0",
              docs_url="/docs" if _docs_publicos else None,
              redoc_url="/redoc" if _docs_publicos else None,
              openapi_url="/openapi.json" if _docs_publicos else None)

# CORS: aceita localhost (qualquer porta), IPs locais (192.168/10/172.16-31)
# e qualquer host *.ts.net (Tailscale). Origens extra via ALLOWED_ORIGINS.
_extra_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
_origin_regex = (
    r"^(https?://localhost(:\d+)?"
    r"|https?://127\.0\.0\.1(:\d+)?"
    r"|https?://192\.168\.\d+\.\d+(:\d+)?"
    r"|https?://10\.\d+\.\d+\.\d+(:\d+)?"
    r"|https?://172\.(1[6-9]|2\d|3[01])\.\d+\.\d+(:\d+)?"
    r"|https://([a-z0-9-]+\.)*pages\.dev"
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

_UPLOADS_DIR = os.getenv("UPLOADS_DIR", "uploads")
os.makedirs(os.path.join(_UPLOADS_DIR, "receipts"), exist_ok=True)

# Routers — protegidos por require_auth. Em dev local (sem CRISTOPHER_PASSWORD)
# a auth está desligada e tudo passa; em produção basta definir a password.
from fastapi import Depends
from auth import require_auth, router as auth_router
from routers import ingest

_protected = [
    events, expenses, lol, trips, lists, sleep, day_types, flow, notes,
    investments, investment_signals, habits, dashboard, mood, budgets,
    templates, app_usage, app_insights, app_goals, ideas, code_activity,
    screen_time, wakatime, deals, stories, spotify, day_planner, wishlist, search, ask, quick, day,
    push_router, scorecard, banking, garmin, meals, nights,
]
for _m in _protected:
    app.include_router(_m.router, dependencies=[Depends(require_auth)])

app.include_router(auth_router)    # /api/auth/login + /status — públicos
app.include_router(ingest.router)  # /api/ingest/* — token próprio (agente local)


# Recibos. Eram um StaticFiles aberto a quem adivinhasse o nome, e um mount não
# aceita a dependência da auth — por isso passaram a rota.
@app.get("/uploads/{caminho:path}", dependencies=[Depends(require_auth)])
def ficheiro_carregado(caminho: str):
    from fastapi.responses import FileResponse
    raiz = os.path.realpath(_UPLOADS_DIR)
    alvo = os.path.realpath(os.path.join(raiz, caminho))
    if not alvo.startswith(raiz + os.sep) or not os.path.isfile(alvo):
        raise HTTPException(status_code=404, detail="Não existe")
    return FileResponse(alvo)


# Com login: diz o que a app fez hoje (gastos, cópias, carteira), e a NAS está
# aberta à internet.
@app.get("/api/health/data", dependencies=[Depends(require_auth)])
def data_health():
    """Frescura de cada fonte de dados + estado dos trabalhos automáticos.
    Existe porque houve 56 dias de sinais parados sem ninguém dar por nada."""
    import scheduler
    from datetime import datetime as _dt, timedelta as _td

    agora = _dt.now()
    db = SessionLocal()
    try:
        def idade(sql: str) -> tuple[Optional[str], Optional[float]]:
            try:
                valor = db.execute(text(sql)).scalar()
            except Exception:
                return None, None
            if not valor:
                return None, None
            txt = str(valor)
            try:
                quando = _dt.fromisoformat(txt[:19]) if len(txt) > 10 else _dt.fromisoformat(txt[:10])
            except ValueError:
                return txt, None
            return txt[:19], round((agora - quando).total_seconds() / 3600, 1)

        # (chave, nome, sql, horas até ficar "atrasado")
        fontes = [
            ("codigo", "Tempo de código (WakaTime)", "SELECT MAX(day) FROM waka_project_days", 48),
            ("screen_time", "Screen Time", "SELECT MAX(date) FROM screen_time_daily_apps", 48),
            ("app_tracker", "Tracker de apps", "SELECT MAX(date) FROM app_usage_sessions", 36),
            ("sono", "Sono", "SELECT MAX(date) FROM sleep_entries", 48),
            ("gastos", "Gastos", "SELECT MAX(date) FROM expenses", 24 * 14),
            ("lol", "LoL", "SELECT MAX(date) FROM lol_games", 24 * 10),
            ("sinais", "Sinais de investimento", "SELECT MAX(generated_at) FROM investment_signals", 48),
            ("carteira", "Valor da carteira", "SELECT MAX(date) FROM portfolio_snapshots", 48),
            ("deals", "Scan de deals", "SELECT MAX(first_seen_at) FROM deal_results", 36),
            ("notas_ia", "Notas IA de projecto", "SELECT MAX(created_at) FROM code_project_notes", 24 * 7),
        ]

        # Só depois de o relógio estar ligado: sem token, uma linha eternamente
        # atrasada era ruído a fingir problema.
        import garmin_api as _garmin
        if _garmin.activo():
            fontes.append(("garmin", "Relógio Garmin", "SELECT MAX(date) FROM garmin_days", 36))

        out_fontes = []
        for chave, nome, sql, limite in fontes:
            ultimo, horas = idade(sql)
            atrasado = horas is not None and horas > limite
            out_fontes.append({
                "key": chave, "label": nome, "last": ultimo,
                "hours_ago": horas, "days_ago": round(horas / 24, 1) if horas is not None else None,
                "limit_hours": limite, "stale": bool(atrasado or ultimo is None),
            })

        out_jobs = []
        for job in scheduler.jobs():
            r = scheduler.last_run(job.name)
            horas = round((agora - r.started_at).total_seconds() / 3600, 1) if (r and r.started_at) else None
            out_jobs.append({
                "name": job.name, "label": job.label,
                "schedule": scheduler._marca_do_dia(job, _dt.now()).strftime("%H:%M"),
                "relative": job.apos_acordar_min is not None,
                "last_run": r.started_at.isoformat() if (r and r.started_at) else None,
                "hours_ago": horas,
                "ok": bool(r.ok) if r else None,
                "detail": (r.detail or "")[:160] if r else "",
                "stale": horas is None or horas > job.max_age_hours or (r is not None and not r.ok),
            })
    finally:
        db.close()

    import ai_budget
    import backup
    copias = backup.estado()

    problemas = [f["label"] for f in out_fontes if f["stale"]] + [j["label"] for j in out_jobs if j["stale"]]

    # Jogos de jungle sem o duelo medido. A sincronização apanha-os sozinha ao
    # fim de umas passagens; se ficarem acumulados, é porque alguma coisa está a
    # falhar em silêncio — e sem isto ninguém dava por ela, que foi exactamente o
    # que aconteceu com os sinais durante 56 dias.
    try:
        _db2 = SessionLocal()
        _sem = _db2.execute(text(
            "SELECT COUNT(*) FROM lol_games g WHERE g.role='jungle' "
            "AND g.match_id IS NOT NULL AND g.date >= date('now','-30 day') "
            "AND NOT EXISTS (SELECT 1 FROM lol_duels d WHERE d.match_id = g.match_id)"
        )).scalar() or 0
        _db2.close()
        if _sem >= 15:
            problemas.append(f"{_sem} jogos de LoL sem o duelo medido")
    except Exception:
        pass
    if copias["stale"]:
        problemas.append("Cópia de segurança da base")
    if copias.get("offsite", {}).get("stale"):
        problemas.append("Cópia fora do Mac")

    # Quem está a responder pela IA. A app andou doze dias com o agente principal
    # apagado e a funcionar pela reserva sem ninguém dar por nada — funcionar com
    # a rede de segurança tem de aparecer como problema, não como silêncio.
    import ai as _ai
    motores = _ai.ai_status()
    if motores["engine"] == _ai.RESERVA:
        problemas.append("IA a funcionar com o agente de reserva")
    elif motores["engine"] == _ai.LOCAL:
        problemas.append("IA a funcionar só com o modelo local")

    return {"checked_at": agora.isoformat(), "sources": out_fontes, "jobs": out_jobs,
            "backups": copias, "ai": ai_budget.estado(), "ai_engine": motores,
            "problems": problemas, "ok": len(problemas) == 0}


@app.get("/api/backups")
def list_backups():
    import backup
    return backup.estado()


@app.post("/api/backups/run")
def run_backup():
    import backup
    try:
        return {"ok": True, **backup.cria_copia()}
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"cópia falhou: {ex}")


@app.get("/api/jobs")
def list_jobs():
    """Estado dos trabalhos automáticos: quando correram e se correram bem."""
    from datetime import datetime as _dt
    import scheduler
    out = []
    for job in scheduler.jobs():
        r = scheduler.last_run(job.name)
        out.append({
            "name": job.name,
            "label": job.label,
            "schedule": scheduler._marca_do_dia(job, _dt.now()).strftime("%H:%M"),
            "relative": job.apos_acordar_min is not None,
            "last_run": r.started_at.isoformat() if r and r.started_at else None,
            "ok": bool(r.ok) if r else None,
            "detail": (r.detail or "") if r else "",
            "duration_ms": (r.duration_ms or 0) if r else 0,
            "max_age_hours": job.max_age_hours,
        })
    return out


@app.post("/api/jobs/{name}/run")
async def run_job_now(name: str):
    """Corre um trabalho à mão (útil para recuperar dias em falta)."""
    import scheduler
    job = next((j for j in scheduler.jobs() if j.name == name), None)
    if not job:
        raise HTTPException(status_code=404, detail="Trabalho não encontrado")
    ok, detail = await scheduler.run_job(job)
    return {"name": name, "ok": ok, "detail": detail}


@app.get("/api/health")
def health():
    return {"status": "ok", "app": "Cristopher"}


# Colunas novas em deal_results (histórico de preço) — SQLite não faz isto sozinho.
def _migrate_banking():
    import sqlite3
    try:
        conn = sqlite3.connect(_DB_PATH)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(expenses)")}
        if "bank_tx_id" not in cols:
            conn.execute("ALTER TABLE expenses ADD COLUMN bank_tx_id VARCHAR")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_expenses_bank_tx ON expenses(bank_tx_id)")
        conn.commit()
        conn.close()
    except Exception as ex:
        print(f"[migrate] expenses.bank_tx_id: {ex}")


_migrate_banking()


def _migrate_wishlist_watch():
    import sqlite3
    try:
        conn = sqlite3.connect(_DB_PATH)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(wishlist_items)")}
        if "watch_id" not in cols:
            conn.execute("ALTER TABLE wishlist_items ADD COLUMN watch_id INTEGER")
        conn.commit()
        conn.close()
    except Exception as ex:
        print(f"[migrate] wishlist_items.watch_id: {ex}")


_migrate_wishlist_watch()


def _migrate_list_item_checked_at():
    import sqlite3
    try:
        conn = sqlite3.connect(_DB_PATH)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(list_items)")}
        if "checked_at" not in cols:
            conn.execute("ALTER TABLE list_items ADD COLUMN checked_at DATETIME")
        conn.commit()
        conn.close()
    except Exception as ex:
        print(f"[migrate] list_items.checked_at: {ex}")


_migrate_list_item_checked_at()


def _migrate_portfolio_prices():
    import sqlite3
    try:
        conn = sqlite3.connect(_DB_PATH)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(investment_positions)")}
        if "price_updated_at" not in cols:
            conn.execute("ALTER TABLE investment_positions ADD COLUMN price_updated_at DATETIME")
        conn.commit()
        conn.close()
    except Exception as ex:
        print(f"[migrate] investment_positions.price_updated_at: {ex}")


_migrate_portfolio_prices()


def _migrate_expense_time():
    import sqlite3
    try:
        conn = sqlite3.connect(_DB_PATH)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(expenses)")}
        if "time_of_day" not in cols:
            conn.execute("ALTER TABLE expenses ADD COLUMN time_of_day VARCHAR")
        conn.commit()
        conn.close()
    except Exception as ex:
        print(f"[migrate] expenses.time_of_day: {ex}")


_migrate_expense_time()


def _migrate_expense_extraordinary():
    """Compra grande e pontual: conta no total do mês, fica fora das réguas."""
    import sqlite3
    try:
        conn = sqlite3.connect(_DB_PATH)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(expenses)")}
        if "extraordinary" not in cols:
            conn.execute("ALTER TABLE expenses ADD COLUMN extraordinary BOOLEAN DEFAULT 0")
        conn.commit()
        conn.close()
    except Exception as ex:
        print(f"[migrate] expenses.extraordinary: {ex}")


_migrate_expense_extraordinary()


def _migrate_expense_klarna():
    """Pago com Klarna em N vezes (vazio = não é Klarna)."""
    import sqlite3
    try:
        conn = sqlite3.connect(_DB_PATH)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(expenses)")}
        if "klarna_installments" not in cols:
            conn.execute("ALTER TABLE expenses ADD COLUMN klarna_installments INTEGER")
        conn.commit()
        conn.close()
    except Exception as ex:
        print(f"[migrate] expenses.klarna_installments: {ex}")


_migrate_expense_klarna()


def _migrate_expense_reembolsos():
    """Reembolsos dos amigos ligados à conta que ele pagou."""
    import sqlite3
    try:
        conn = sqlite3.connect(_DB_PATH)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(expenses)")}
        if "reimburses_id" not in cols:
            conn.execute("ALTER TABLE expenses ADD COLUMN reimburses_id INTEGER")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_expenses_reimburses_id ON expenses (reimburses_id)")
        if "split_people" not in cols:
            conn.execute("ALTER TABLE expenses ADD COLUMN split_people INTEGER")
        if "my_share" not in cols:
            conn.execute("ALTER TABLE expenses ADD COLUMN my_share REAL")
        # Os reembolsos ligados antes de haver repartição descontavam tudo numa
        # conta só: passam a uma linha de repartição com o valor inteiro.
        conn.execute("""
            INSERT INTO reimbursement_links (income_id, expense_id, amount)
            SELECT e.id, e.reimburses_id, -e.amount FROM expenses e
            WHERE e.reimburses_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM reimbursement_links l WHERE l.income_id = e.id)""")
        conn.commit()
        conn.close()
    except Exception as ex:
        print(f"[migrate] expenses.reimburses_id: {ex}")


_migrate_expense_reembolsos()


def _migrate_salary_amount():
    """O valor do salário quando ele marca um movimento como sendo o salário."""
    import sqlite3
    try:
        conn = sqlite3.connect(_DB_PATH)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(salary_paydays)")}
        if cols and "amount" not in cols:
            conn.execute("ALTER TABLE salary_paydays ADD COLUMN amount REAL")
        conn.commit()
        conn.close()
    except Exception as ex:
        print(f"[migrate] salary_paydays.amount: {ex}")


_migrate_salary_amount()


def _migrate_deal_price_columns():
    import sqlite3
    try:
        conn = sqlite3.connect(_DB_PATH)
        wcols = {r[1] for r in conn.execute("PRAGMA table_info(deal_watches)")}
        if "kind" not in wcols:
            conn.execute("ALTER TABLE deal_watches ADD COLUMN kind VARCHAR DEFAULT 'specific'")
        if "notify" not in wcols:
            conn.execute("ALTER TABLE deal_watches ADD COLUMN notify BOOLEAN DEFAULT 1")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(deal_results)")}
        if "previous_price" not in cols:
            conn.execute("ALTER TABLE deal_results ADD COLUMN previous_price FLOAT")
        if "price_changed_at" not in cols:
            conn.execute("ALTER TABLE deal_results ADD COLUMN price_changed_at DATETIME")
        if "gone_at" not in cols:
            conn.execute("ALTER TABLE deal_results ADD COLUMN gone_at DATETIME")
        if "reappeared_at" not in cols:
            conn.execute("ALTER TABLE deal_results ADD COLUMN reappeared_at DATETIME")
        if "criteria_json" not in wcols:
            conn.execute("ALTER TABLE deal_watches ADD COLUMN criteria_json TEXT DEFAULT ''")
        for coluna, tipo in (("attr_year", "INTEGER"), ("attr_km", "INTEGER"),
                             ("attr_power_kw", "INTEGER"), ("attr_color", "VARCHAR"),
                             ("attr_color_src", "VARCHAR")):
            if coluna not in cols:
                conn.execute(f"ALTER TABLE deal_results ADD COLUMN {coluna} {tipo}")
        conn.commit()
        conn.close()
    except Exception as ex:
        print(f"[migrate] deal_results: {ex}")


_migrate_deal_price_columns()


def _migrate_categoria_noite():
    """A categoria Noite nasceu depois dos envelopes: sem isto os gastos dela
    caíam em "fora do orçamento". Vai para onde está o Entretenimento. Só uma
    vez — enquanto não houver gastos na Noite; depois disso, se ele a tirar do
    envelope, é porque quis."""
    import sqlite3
    try:
        conn = sqlite3.connect(_DB_PATH)
        envelopes = conn.execute("SELECT id, categories FROM salary_buckets").fetchall()
        ja_tem = any("nightlife" in (c or "").split(",") for _, c in envelopes)
        usada = conn.execute("SELECT 1 FROM expenses WHERE category = 'nightlife' LIMIT 1").fetchone()
        if not ja_tem and not usada:
            for bid, cats in envelopes:
                lista = [c for c in (cats or "").split(",") if c]
                if "entertainment" in lista:
                    lista.insert(lista.index("entertainment") + 1, "nightlife")
                    conn.execute("UPDATE salary_buckets SET categories = ? WHERE id = ?",
                                 (",".join(lista), bid))
                    conn.commit()
                    break
        conn.close()
    except Exception as ex:
        print(f"[migrate] categoria noite: {ex}")


_migrate_categoria_noite()


def _migrate_user_lists_apple_name():
    import sqlite3
    try:
        conn = sqlite3.connect(_DB_PATH)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(user_lists)")}
        for coluna in ("apple_name", "apple_icon", "apple_color"):
            if cols and coluna not in cols:
                conn.execute(f"ALTER TABLE user_lists ADD COLUMN {coluna} VARCHAR")
        conn.commit()
        conn.close()
    except Exception as ex:
        print(f"[migrate] user_lists.apple_name: {ex}")


_migrate_user_lists_apple_name()


def _migrate_lol_metric_columns():
    """Desempenho de cada jogo (CS, ouro, dano, visão). A Riot já mandava isto
    em cada partida e era deitado fora — ver `models.LolGame`."""
    import sqlite3
    try:
        conn = sqlite3.connect(_DB_PATH)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(lol_games)")}
        for coluna in ("cs", "cs_jungle", "gold", "damage", "damage_taken",
                       "vision", "team_kills"):
            if coluna not in cols:
                conn.execute(f"ALTER TABLE lol_games ADD COLUMN {coluna} INTEGER")
        conn.commit()
        conn.close()
    except Exception as ex:
        print(f"[migrate] lol_games: {ex}")


_migrate_lol_metric_columns()


# ── Trabalhos automáticos (substituem os LaunchAgents que o macOS bloqueava) ──

@app.on_event("startup")
def _start_scheduler():
    import scheduler
    from scheduler import Job

    async def _sinais_investimento_async():
        from routers.investment_signals import generate_signal, refresh_all_performance, GenerateRequest
        db = SessionLocal()
        try:
            atualizados = refresh_all_performance(db)
            sinal = await generate_signal(GenerateRequest(skip_if_exists_today=True), db)
            headline = (sinal or {}).get("headline") if isinstance(sinal, dict) else getattr(sinal, "headline", "")
            return f"performance atualizada, sinal: {str(headline)[:80]}"
        finally:
            db.close()

    def _snapshot_dados_locais():
        from routers.sleep import auto_register_recent_sleep
        from routers.screen_time import snapshot_screen_time
        noites = auto_register_recent_sleep(days_back=7)
        dias = snapshot_screen_time(days_back=45)
        return f"{noites} noites de sono, {dias} dias de screen time"

    def _sync_wakatime():
        from routers.wakatime import sync_recent
        db = SessionLocal()
        try:
            return f"{sync_recent(db, days=14)} dias sincronizados"
        finally:
            db.close()

    scheduler.register(Job(
        name="sinais_investimento", label="Sinais IA de investimento",
        fn=_sinais_investimento_async, hour=8, minute=30, max_age_hours=48,
    ))
    if sys.platform == "darwin" and os.getenv("CLOUD") != "1":
        scheduler.register(Job(
            name="snapshot_local", label="Snapshot de sono e Screen Time",
            fn=_snapshot_dados_locais, hour=7, minute=45, max_age_hours=30,
        ))
    async def _aquecer_ia():
        """Deixa prontas as respostas de IA que os painéis mostram.

        Estas chamadas demoram 30-120s à primeira: sem isto, abrir os Avisos numa
        segunda-feira (cache nova) deixava a secção da semana pendurada até a IA
        responder."""
        feitos = []
        db = SessionLocal()
        try:
            from routers.code_activity import weekly_summary
            try:
                await weekly_summary(weeks_back=0, refresh=False, db=db)
                feitos.append("resumo da semana")
            except Exception as ex:
                feitos.append(f"resumo da semana falhou ({type(ex).__name__})")
        finally:
            db.close()

        db = SessionLocal()
        try:
            from routers.lol import jungle_tips
            try:
                await jungle_tips(force=False, db=db)
                feitos.append("dicas de jungle")
            except Exception as ex:
                feitos.append(f"dicas de jungle falharam ({type(ex).__name__})")
        finally:
            db.close()
        return ", ".join(feitos)

    scheduler.register(Job(
        name="aquecer_ia", label="Preparar as respostas de IA dos painéis",
        fn=_aquecer_ia, hour=6, minute=30, max_age_hours=30,
    ))

    def _arquivar_deals():
        from routers.deals import prune
        db = SessionLocal()
        try:
            r = prune(days=10, db=db)   # `days` tem um Query() por omissão: fora do FastAPI é preciso dar o valor
            return f"{r['archived']} anúncios arquivados"
        finally:
            db.close()

    def _sync_banco():
        from datetime import date as _hoje
        from notifier import notify
        from routers.banking import sincronizar
        from models import BankConnection
        import openbanking as ob
        if not ob.configurado():
            return "banco não configurado"
        db = SessionLocal()
        try:
            r = sincronizar(days=30, db=db)
            novas = sum(x.get("created", 0) for x in r["results"])
            erros = [x["error"] for x in r["results"] if x.get("error")]

            # A autorização caduca (PSD2) e, no Revolut, o histórico completo só
            # vem nos primeiros minutos a seguir a renovar — avisar a tempo.
            for lig in db.query(BankConnection).filter(BankConnection.status == "ligado").all():
                if not lig.expires_at:
                    continue
                faltam = (lig.expires_at.date() - _hoje.today()).days
                if 0 < faltam <= 14:
                    notify(
                        "Banco: autorização a acabar",
                        f"A ligação ao {lig.institution_name} caduca em {faltam} dias. "
                        "Renova em Gastos → Banco para as despesas continuarem a entrar.",
                        severity="warning",
                    )
                    break
            return f"{novas} despesas novas" + (f" · {len(erros)} erros" if erros else "")
        finally:
            db.close()

    scheduler.register(Job(
        name="sync_banco", label="Trazer movimentos do banco",
        fn=_sync_banco, hour=9, minute=30, max_age_hours=30,
    ))

    def _lojas_por_classificar():
        from bank_ai import aplica_regras, classifica_desconhecidas
        db = SessionLocal()
        try:
            ja = aplica_regras(db)
            r = classifica_desconhecidas(db)
            return (f"{r['aprendidas']} lojas novas · {r['despesas'] + ja} despesas arrumadas"
                    if r.get("aprendidas") or ja else "nada por classificar")
        finally:
            db.close()

    async def _jogos_lol():
        from lol_goal import marca_dias
        from routers.lol import sync_riot_games
        db = SessionLocal()
        try:
            r = await sync_riot_games(days=0, season=False, db=db)
            marcados = marca_dias(db, dias_atras=30)     # hábito dos 3 jogos por dia
            texto = r.get("message") or f"{r.get('imported', 0)} jogos importados"
            return texto + (f" · hábito actualizado ({marcados})" if marcados else "")
        finally:
            db.close()

    scheduler.register(Job(
        name="jogos_lol", label="Trazer jogos de LoL",
        fn=_jogos_lol, cada_min=20, max_age_hours=6, catch_up=False,
    ))

    if sys.platform == "darwin":
        async def _previsao_lol():
            from routers.lol import apanha_previsao_em_segundo_plano
            return await apanha_previsao_em_segundo_plano()

        # De 5 em 5 minutos enquanto o cliente estiver aberto: uma partida dura
        # 25-35 min, por isso nenhuma escapa. Com o cliente fechado não gasta
        # nada — nem sequer chega a falar com a Riot.
        scheduler.register(Job(
            name="previsao_lol", label="Guardar previsão da partida a decorrer",
            fn=_previsao_lol, cada_min=5, max_age_hours=24 * 30, catch_up=False,
        ))

        # O que a app mediu nele só serve enquanto o jogo ainda dá para mudar, e
        # ele está a jogar em ecrã inteiro — a página do LoL num segundo monitor
        # não chega. Vai por notificação do Mac, uma vez cada aviso por partida.
        # O que já foi dito nesta partida. O cliente não dá um id de jogo, mas dá
        # o relógio: quando o tempo de jogo anda para trás, começou outra. Sem
        # isto, dois Jarvans seguidos partilhavam a memória e o segundo saía mudo.
        _ditos: set[str] = set()
        _relogio = {"t": 0.0}

        async def _treinador_lol():
            import lol_coach
            from live_winprob import get_live_client_data
            from routers.lol import _medidas_para_o_coach

            dados = await get_live_client_data()
            if not dados:
                _ditos.clear()                 # fora de jogo, esquece o que disse
                _relogio["t"] = 0.0
                return "sem jogo"
            db = SessionLocal()
            try:
                estado = lol_coach.avisos(dados, _medidas_para_o_coach(db))
            finally:
                db.close()
            if not estado.get("in_game"):
                return "cliente aberto, sem partida"

            agora = float(estado.get("game_time") or 0)
            if agora < _relogio["t"] - 30:     # o relógio recuou: é outra partida
                _ditos.clear()
            _relogio["t"] = agora

            novos = [a for a in estado.get("alerts", [])
                     if a["key"] not in _ditos and a["level"] == "aviso"]
            if not novos:
                return f"{len(estado.get('alerts', []))} avisos, nada novo"
            import notifier
            for a in novos:
                _ditos.add(a["key"])
                notifier.send_macos(a["title"], a["text"])
            return "avisou: " + ", ".join(a["key"] for a in novos)

        scheduler.register(Job(
            name="treinador_lol", label="Avisar durante a partida",
            fn=_treinador_lol, cada_min=1, max_age_hours=24 * 30, catch_up=False,
        ))

    scheduler.register(Job(
        name="lojas_banco", label="Classificar lojas novas do banco",
        fn=_lojas_por_classificar, hour=9, minute=45, max_age_hours=30,
    ))

    def _fecha_planos():
        """Carimba o plano com o que o tracker viu. Em nove planos ele marcou
        zero blocos — pedir para carimbar o dia não funciona."""
        from datetime import date as _d, timedelta as _td
        from routers.day_planner import fecha_plano
        db = SessionLocal()
        try:
            fechados = 0
            for atras in range(1, 4):          # ontem e os dois dias antes
                dia = (_d.today() - _td(days=atras)).isoformat()
                try:
                    fechados += fecha_plano(dia, db).get("closed", 0)
                except HTTPException:
                    continue                    # dia sem plano
            return f"{fechados} blocos carimbados" if fechados else "nada a carimbar"
        finally:
            db.close()

    scheduler.register(Job(
        name="fecha_planos", label="Fechar o plano com o que aconteceu",
        fn=_fecha_planos, hour=8, minute=45, max_age_hours=30,
    ))

    def _viagens_do_banco():
        """As idas fora de casa saem das despesas. Corre depois do banco: as
        viagens estiveram três meses paradas porque isto era um botão."""
        from routers.trips import detectar_viagens
        db = SessionLocal()
        try:
            r = detectar_viagens(apply=True, db=db)
            if not r["trips_created"] and not r["expenses_linked"]:
                return "sem viagens novas"
            return f"{r['trips_created']} viagens novas · {r['expenses_linked']} despesas ligadas"
        finally:
            db.close()

    scheduler.register(Job(
        name="viagens", label="Detectar viagens pelas despesas",
        fn=_viagens_do_banco, hour=10, minute=0, max_age_hours=30,
    ))

    def _precos_carteira():
        from routers.investments import refresh_prices
        db = SessionLocal()
        try:
            r = refresh_prices(db=db)
            return f"{len(r['updated'])} cotações actualizadas"
        finally:
            db.close()

    def _carteira_t212():
        """Quantidades reais do Trading 212. Corre antes dos preços: não vale a
        pena cotar posições que já não são as dele."""
        import trading212
        db = SessionLocal()
        try:
            r = trading212.sincroniza(db)
            partes = [f"{r['positions']} posições"]
            for chave, etiqueta in (("trades", "ordens"), ("transactions", "movimentos"),
                                    ("dividends", "dividendos")):
                if r[chave]:
                    partes.append(f"{r[chave]} {etiqueta}")
            if r["errors"]:
                partes.append("· " + "; ".join(r["errors"])[:120])
            return " · ".join(partes)
        finally:
            db.close()

    # Registado antes dos preços de propósito: o agendador corre-os por esta
    # ordem, e cotar quantidades velhas não serve de nada. Só existe se houver
    # chave — senão o painel de saúde acusava um trabalho parado que nunca teve
    # nada para fazer.
    import trading212 as _t212
    if _t212.configurado():
        scheduler.register(Job(
            name="sync_t212", label="Carteira do Trading 212",
            fn=_carteira_t212, hour=18, minute=5, max_age_hours=30,
        ))
    scheduler.register(Job(
        name="precos_carteira", label="Preços da carteira",
        fn=_precos_carteira, hour=18, minute=15, max_age_hours=30,
    ))
    scheduler.register(Job(
        name="arquivar_deals", label="Arrumar deals que já não existem",
        fn=_arquivar_deals, hour=7, minute=30, max_age_hours=48,
    ))
    scheduler.register(Job(
        name="sync_wakatime", label="Sync do WakaTime",
        fn=_sync_wakatime, hour=8, minute=0, max_age_hours=30,
    ))

    def _sync_reminders():
        import apple_reminders
        db = SessionLocal()
        try:
            return apple_reminders.resumo(apple_reminders.sincroniza(db))
        finally:
            db.close()

    # A ponte para os Reminders compila-se à primeira passagem, não aqui: o
    # swiftc leva ~10s e isso é tempo de arranque da app.
    if sys.platform == "darwin" and os.getenv("CLOUD") != "1":
        scheduler.register(Job(
            name="sync_reminders", label="Reminders da Apple",
            fn=_sync_reminders, hour=8, minute=15, cada_min=60, max_age_hours=6,
        ))

    def _copia_de_seguranca():
        import backup
        r = backup.cria_copia()
        fora = r.get("offsite") or {}
        if fora.get("sent"):
            estado_fora = " · cifrada para fora do Mac"
        elif fora.get("enabled"):
            estado_fora = f" · FORA DO MAC FALHOU: {fora.get('reason', '')[:60]}"
        else:
            estado_fora = ""
        return (f"{r['file']} · {r['mb']}MB (de {r['source_mb']}MB)"
                + (f" · {r['pruned']} antigas apagadas" if r["pruned"] else "")
                + estado_fora)

    scheduler.register(Job(
        name="backup_db", label="Cópia de segurança da base",
        fn=_copia_de_seguranca, hour=5, minute=0, max_age_hours=30,
    ))

    # ── Avisos pontuais: a app fala primeiro, em vez de esperar que a abram ──

    def _aviso_manha():
        from notifier import send_macos
        from routers.day_planner import ensure_today_sync
        from routers.lists import get_pending_items
        db = SessionLocal()
        try:
            plano = ensure_today_sync(db)
            blocos = [b for b in (plano or []) if not b.get("done")]
            atrasados = [i for i in get_pending_items(db)
                         if i["due_date"] and i["due_date"] < _date.today().isoformat()]
            if not blocos and not atrasados:
                return "nada a avisar"
            partes = []
            if blocos:
                primeiro = blocos[0]
                partes.append(f"{len(blocos)} blocos — começa com {primeiro['name']} às {primeiro['start']}")
            if atrasados:
                partes.append(f"{len(atrasados)} tarefas atrasadas")
            corpo = " · ".join(partes)
            send_macos("☀️ O teu dia", corpo)
            return corpo
        finally:
            db.close()

    def _aviso_fim_de_tarde():
        from notifier import send_macos
        from routers.day_planner import today_blocks
        from routers.lists import get_pending_items
        db = SessionLocal()
        try:
            blocos = today_blocks(db)
            falta = [b for b in blocos if not b.get("done")]
            hoje = _date.today().isoformat()
            tarefas = [i for i in get_pending_items(db) if i["due_date"] == hoje]
            if not falta and not tarefas:
                send_macos("✅ Dia fechado", "Plano e tarefas de hoje sem nada em falta.")
                return "dia limpo"
            corpo = " · ".join(filter(None, [
                f"{len(falta)} bloco{'s' if len(falta) != 1 else ''} do plano por fazer" if falta else "",
                f"{len(tarefas)} tarefa{'s' if len(tarefas) != 1 else ''} de hoje" if tarefas else "",
            ]))
            send_macos("🌆 Falta fechar o dia", corpo)
            return corpo
        finally:
            db.close()

    def _aviso_orcamento():
        from notifier import send_macos
        from routers.budgets import month_forecast
        db = SessionLocal()
        try:
            f = month_forecast(None, None, db)
            if f["plan_target"] <= 0 or f["spent"] <= 0:
                return "sem plano ou sem gastos"
            pct = f["projected"] / f["plan_target"] * 100
            if pct < 100:
                return f"dentro do plano ({round(pct)}%)"
            corpo = (f"Previsão €{f['projected']:.0f} vs plano €{f['plan_target']:.0f} — "
                     f"a estourar €{abs(f['over_by'] or 0):.0f} ao ritmo de €{f['daily_rate']:.0f}/dia")
            send_macos("💸 Gastos acima do plano", corpo)
            return corpo
        finally:
            db.close()

    # O relógio não tem Wi-Fi: os dados só chegam à nuvem quando ele passa pelo
    # telemóvel, a horas imprevisíveis. Em vez de uma hora marcada, pergunta-se de
    # quarto em quarto de hora se houve sincronização nova — é um pedido — e só se
    # vai buscar tudo quando houve. Assim os dados aparecem aqui poucos minutos
    # depois de chegarem à Garmin, sem ninguém carregar em nada.
    _garmin_avisado: list = []

    def _sync_garmin():
        import garmin_api
        import garmin_sync
        from notifier import notify
        if not garmin_api.activo():
            return "desligado (sem token — correr scripts/garmin_login.py)"
        try:
            vale, motivo = garmin_sync.ha_coisa_nova()
            if not vale:
                return motivo
            return f"{garmin_sync.sincroniza(dias=7)['message']} ({motivo})"
        except garmin_api.GarminIndisponivel as e:
            hoje = _date.today()
            if "expirou" in str(e) and _garmin_avisado[:1] != [hoje]:
                _garmin_avisado[:] = [hoje]
                notify("Relógio: é preciso entrar outra vez",
                       "O acesso à conta Garmin caducou. Corre `python scripts/garmin_login.py` "
                       "para os dados do relógio voltarem a entrar.",
                       severity="warning")
            raise RuntimeError(str(e)) from e

    scheduler.register(Job(
        name="sync_garmin", label="Trazer dados do relógio",
        fn=_sync_garmin, cada_min=15, max_age_hours=3, catch_up=False,
    ))

    def _metas_ecra():
        from routers.screen_time import checar_metas_diarias
        db = SessionLocal()
        try:
            return checar_metas_diarias(db)
        finally:
            db.close()

    def _avisos_refeicoes():
        from routers.meals import avisa_refeicoes
        db = SessionLocal()
        try:
            return avisa_refeicoes(db)
        finally:
            db.close()

    # De 5 em 5 minutos: uma janela que abre às 12:30 não pode ser avisada às 13h.
    scheduler.register(Job(
        name="avisos_refeicoes", label="Avisar as horas das refeições",
        fn=_avisos_refeicoes, cada_min=5, max_age_hours=3, catch_up=False,
    ))

    scheduler.register(Job(
        name="metas_ecra", label="Checar metas diárias de ecrã",
        fn=_metas_ecra, cada_min=15, max_age_hours=3, catch_up=False,
    ))

    if os.getenv("NOTIFY_NUDGES", "1") == "1" and sys.platform == "darwin":
        # Horas relativas ao acordar dele (mediana ~11:30), não ao relógio: às
        # 09:00 estes avisos apanhavam-no a dormir, e a recuperação de atrasos
        # chegou a enviá-los às 02:00.
        scheduler.register(Job(name="aviso_manha", label="Aviso da manhã (plano do dia)",
                               fn=_aviso_manha, hour=11, minute=30, apos_acordar_min=20,
                               so_acordado=True, max_age_hours=30))
        scheduler.register(Job(name="aviso_orcamento", label="Aviso de orçamento",
                               fn=_aviso_orcamento, hour=15, minute=0, apos_acordar_min=4 * 60,
                               so_acordado=True, max_age_hours=30))
        scheduler.register(Job(name="aviso_tarde", label="Aviso do fim da tarde",
                               fn=_aviso_fim_de_tarde, hour=20, minute=0, apos_acordar_min=9 * 60,
                               so_acordado=True, max_age_hours=30))

    scheduler.start(asyncio.get_event_loop())


# ── App-usage tracker auto-start ─────────────────────────────────
# Garante que o tracker (app_tracker.py) está sempre a correr enquanto o
# backend está vivo. Usa um pidfile para não duplicar processos quando o
# uvicorn --reload reinicia o app.

import sys
import subprocess
import asyncio
import atexit
from datetime import date as _date
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
    if os.getenv("CLOUD") == "1":
        return  # na cloud a recolha local é feita pelo agente no Mac
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


@app.on_event("startup")
def _start_callback_https():
    """Porta https só para o banco devolver o utilizador à app (ver callback_https)."""
    import callback_https
    callback_https.arranca()


@app.on_event("startup")
def _start_sleep_auto_register():
    """Regista o sono automaticamente (estimado do uso do PC) ao arrancar e
    depois de 6 em 6h. Só corre em macOS local; em Linux/Codespaces o estimador
    devolve None e este loop não faz nada."""
    if os.getenv("CLOUD") == "1":
        return  # snapshots de sono/screen-time vêm do agente local
    if sys.platform != "darwin":
        return
    import threading
    import time as _time

    def _loop():
        from routers.sleep import auto_register_recent_sleep
        from routers.screen_time import snapshot_screen_time
        while True:
            try:
                auto_register_recent_sleep(days_back=7)
            except Exception:
                pass
            try:
                snapshot_screen_time(days_back=45)
            except Exception:
                pass
            _time.sleep(6 * 3600)

    threading.Thread(target=_loop, daemon=True).start()


@app.on_event("startup")
def _start_deals_scanner():
    """Caça-deals: pesquisa fontes e avalia com IA periodicamente. Intervalo em
    DEALS_SCAN_INTERVAL_HOURS (default 12h — a quota da IA é apertada, por isso não
    de hora a hora). Corre em qualquer plataforma. Desliga com DEALS_AUTOSCAN=0."""
    if os.getenv("DEALS_AUTOSCAN", "1") != "1":
        return
    import threading
    import time as _time

    try:
        interval = max(1.0, float(os.getenv("DEALS_SCAN_INTERVAL_HOURS", "12"))) * 3600
    except ValueError:
        interval = 12 * 3600

    def _loop():
        from routers.deals import run_all_watches
        _time.sleep(60)  # deixa o arranque assentar antes do 1º scan
        while True:
            try:
                run_all_watches()
            except Exception as e:
                print(f"[main] deals scan falhou: {e}", file=sys.stderr)
            _time.sleep(interval)

    threading.Thread(target=_loop, daemon=True).start()


@app.on_event("startup")
def _start_event_notifier():
    """Notifica (balão nativo do macOS) quando a hora de um evento chega.
    Verifica a cada 30s; janela de 90s + memória do que já foi avisado evitam
    duplicados. Só corre em macOS local. Desliga com EVENT_NOTIFY=0."""
    if os.getenv("EVENT_NOTIFY", "1") != "1":
        return
    if sys.platform != "darwin":
        return
    import threading
    import time as _time
    from datetime import datetime as _dt

    notified: set[str] = set()
    state = {"day": None}

    def _loop():
        from database import SessionLocal
        from routers.events import events_due_now
        from notifier import send_macos
        while True:
            try:
                now = _dt.now()
                if state["day"] != now.date():
                    notified.clear()
                    state["day"] = now.date()
                db = SessionLocal()
                try:
                    for key, title, when in events_due_now(db, now):
                        if key in notified:
                            continue
                        notified.add(key)
                        send_macos(title, when)
                finally:
                    db.close()
            except Exception as e:
                print(f"[main] event notifier falhou: {e}", file=sys.stderr)
            _time.sleep(30)

    threading.Thread(target=_loop, daemon=True).start()


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


# Na NAS o mesmo servidor serve o build do React (STATIC_DIR): uma porta só, sem
# CORS e com o HTTPS resolvido de uma vez no reverse proxy. Fica no fim de
# propósito — um mount em "/" apanha tudo o que as rotas acima não apanharam.
_STATIC_DIR = os.getenv("STATIC_DIR", "")
if _STATIC_DIR and os.path.isdir(_STATIC_DIR):
    from starlette.exceptions import HTTPException as _StarletteHTTPException

    # O que não tem hash no nome tem de ser revalidado: um index.html velho em
    # cache aponta para ficheiros do build que já não existem depois de actualizar.
    _SEM_CACHE = {"", ".", "index.html", "sw.js", "manifest.webmanifest"}

    class _SPAStaticFiles(StaticFiles):
        """Ficheiro inexistente → index.html, para os links directos abrirem a app."""

        async def get_response(self, path, scope):
            try:
                resposta = await super().get_response(path, scope)
            except _StarletteHTTPException as exc:
                # um /api/... desconhecido continua a ser 404, não a página inicial
                if exc.status_code != 404 or path.startswith(("api/", "uploads/")):
                    raise
                path = "index.html"
                resposta = await super().get_response(path, scope)
            if path in _SEM_CACHE:
                resposta.headers["Cache-Control"] = "no-cache"
            return resposta

    app.mount("/", _SPAStaticFiles(directory=_STATIC_DIR, html=True), name="frontend")
