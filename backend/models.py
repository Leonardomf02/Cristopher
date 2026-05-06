from sqlalchemy import Column, Integer, String, Float, Boolean, Date, DateTime, Text, Enum as SAEnum
from sqlalchemy.sql import func
from database import Base
import enum


# ── Day Types ────────────────────────────────────────────────────

class DayType(Base):
    __tablename__ = "day_types"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, unique=True, index=True)
    type_name = Column(String, nullable=False)  # trabalho, viagem, folga, férias, etc.
    color = Column(String, default="#3B82F6")    # hex color
    note = Column(Text, default="")


# ── Calendar Events ──────────────────────────────────────────────

class EventType(str, enum.Enum):
    FIXED = "fixed"          # Fixed time (e.g., meeting at 10:00)
    FLEXIBLE = "flexible"    # Can be done anytime during the day


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    date = Column(Date, nullable=False)
    start_time = Column(String, nullable=True)    # HH:MM, null if flexible
    end_time = Column(String, nullable=True)       # HH:MM, null if flexible
    event_type = Column(String, default=EventType.FIXED)
    category = Column(String, default="general")   # gym, work, personal, etc.
    color = Column(String, default="#3B82F6")
    completed = Column(Boolean, default=False)
    # Recurrence
    recurrence = Column(String, default="none")    # none, daily, weekdays, weekly, biweekly, monthly, yearly
    recurrence_end = Column(Date, nullable=True)   # null = forever
    recurrence_exceptions = Column(Text, default="[]")  # JSON list of excluded dates
    created_at = Column(DateTime, server_default=func.now())


# ── Expenses ─────────────────────────────────────────────────────

class ExpenseCategory(str, enum.Enum):
    FOOD = "food"
    TRANSPORT = "transport"
    ENTERTAINMENT = "entertainment"
    SUBSCRIPTIONS = "subscriptions"
    SHOPPING = "shopping"
    HEALTH = "health"
    BILLS = "bills"
    TRAVEL = "travel"
    OTHER = "other"


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    description = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    category = Column(String, default=ExpenseCategory.OTHER)
    date = Column(Date, nullable=False)
    receipt_image = Column(String, nullable=True)  # file path to receipt photo
    trip_id = Column(Integer, nullable=True)       # link to trip if travel expense
    notes = Column(Text, default="")
    original_amount = Column(Float, nullable=True)    # amount in original currency
    original_currency = Column(String, nullable=True) # e.g. PLN, SEK, RON
    merchant_city = Column(String, nullable=True)     # e.g. Krakow, Stockholm
    merchant_country = Column(String, nullable=True)  # e.g. POL, SWE, LTU
    created_at = Column(DateTime, server_default=func.now())


class MonthlyIncome(Base):
    __tablename__ = "monthly_income"

    id = Column(Integer, primary_key=True, index=True)
    month = Column(Integer, nullable=False)   # 1-12
    year = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False, default=1040.98)


# ── League of Legends Tracker ────────────────────────────────────

class LolSeason(Base):
    __tablename__ = "lol_seasons"

    id = Column(Integer, primary_key=True, index=True)
    label = Column(String, nullable=False)          # "Season 2026.1", "Pre-reset", etc.
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)          # NULL = currently active
    # Snapshot when season ended:
    peak_tier = Column(String, nullable=True)
    peak_rank = Column(String, nullable=True)
    peak_lp = Column(Integer, nullable=True)
    final_tier = Column(String, nullable=True)
    final_rank = Column(String, nullable=True)
    final_lp = Column(Integer, nullable=True)
    total_games = Column(Integer, default=0)
    total_wins = Column(Integer, default=0)
    total_losses = Column(Integer, default=0)
    # Highest wins+losses ever observed via Riot API for this season — used for reset detection
    max_ranked_total = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())


class LolRankSnapshot(Base):
    __tablename__ = "lol_rank_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    season_id = Column(Integer, nullable=True, index=True)
    date = Column(Date, nullable=False)
    tier = Column(String, nullable=True)       # MASTER, GRANDMASTER, etc.
    rank = Column(String, nullable=True)       # I, II, III, IV
    lp = Column(Integer, nullable=True)
    wins = Column(Integer, nullable=True)
    losses = Column(Integer, nullable=True)
    euw_rank = Column(Integer, nullable=True)  # EU position from LoG
    global_rank = Column(Integer, nullable=True)
    top_percent = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class LolGame(Base):
    __tablename__ = "lol_games"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(String, nullable=True, unique=True, index=True)  # Riot match ID for dedup
    season_id = Column(Integer, nullable=True, index=True)
    date = Column(Date, nullable=False)
    won = Column(Boolean, nullable=False)
    champion_played = Column(String, nullable=True)
    champion_against = Column(String, nullable=True)
    role = Column(String, nullable=True)           # top, jungle, mid, adc, support
    my_fault = Column(Boolean, nullable=True)      # was the result my fault?
    kills = Column(Integer, nullable=True)
    deaths = Column(Integer, nullable=True)
    assists = Column(Integer, nullable=True)
    game_duration = Column(Integer, nullable=True)  # seconds
    game_hour = Column(Integer, nullable=True)       # 0-23, hour of day game started
    team_side = Column(String, nullable=True)        # "blue" or "red"
    notes = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())


class LolPrediction(Base):
    __tablename__ = "lol_predictions"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(String, nullable=True, unique=True, index=True)
    game_start_time = Column(Integer, nullable=True, unique=True, index=True)  # epoch ms from spectator API
    season_id = Column(Integer, nullable=True, index=True)
    date = Column(Date, nullable=False)
    champion_played = Column(String, nullable=True)
    champion_against = Column(String, nullable=True)
    predicted_win = Column(Boolean, nullable=False)          # True = predicted win
    confidence = Column(Float, nullable=False)               # 0-100 probability
    confidence_level = Column(String, nullable=True)         # "high", "medium", "low"
    factors = Column(Text, default="")                       # JSON string of factors
    actual_win = Column(Boolean, nullable=True)              # filled after game ends
    correct = Column(Boolean, nullable=True)                 # predicted_win == actual_win
    created_at = Column(DateTime, server_default=func.now())


# ── Trips / Travel ───────────────────────────────────────────────

class Trip(Base):
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True, index=True)
    destination = Column(String, nullable=False)   # e.g., "Estocolmo, Suécia"
    country = Column(String, nullable=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    cover_image = Column(String, nullable=True)
    notes = Column(Text, default="")
    flights_cost = Column(Float, default=0)
    accommodation_cost = Column(Float, default=0)
    food_budget = Column(Float, default=0)
    other_costs = Column(Float, default=0)
    # Aggregate ratings 0-10 (nullable = não classificado)
    rating_food = Column(Float, nullable=True)
    rating_places = Column(Float, nullable=True)
    rating_nightlife = Column(Float, nullable=True)
    rating_gajas = Column(Float, nullable=True)
    rating_overall = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class TripPlace(Base):
    __tablename__ = "trip_places"

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    is_free = Column(Boolean, default=True)
    estimated_cost = Column(Float, default=0)
    visited = Column(Boolean, default=False)
    suggested = Column(Boolean, default=False)     # True if auto-suggested
    address = Column(String, nullable=True)
    url = Column(String, nullable=True)
    rating = Column(Float, nullable=True)          # 0-10
    review = Column(Text, default="")              # post-visit notes


class TripRating(Base):
    """Free-form ratings: meals, encounters, experiences — anything not tied to a TripPlace."""
    __tablename__ = "trip_ratings"

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, nullable=False, index=True)
    category = Column(String, nullable=False)     # comida, sitio, noite, encontro, experiencia, outro
    name = Column(String, nullable=False)
    rating = Column(Float, nullable=False)         # 0-10
    notes = Column(Text, default="")
    date = Column(Date, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class TripGaja(Base):
    __tablename__ = "trip_gajas"

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, nullable=False, index=True)
    name = Column(String, nullable=False)
    rating_face = Column(Float, nullable=True)
    rating_body = Column(Float, nullable=True)
    rating_vibe = Column(Float, nullable=True)
    rating_personality = Column(Float, nullable=True)
    rating_overall = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# ── Lists ────────────────────────────────────────────────────────

class UserList(Base):
    __tablename__ = "user_lists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)           # compras, pessoal, desejos
    icon = Column(String, default="📝")
    color = Column(String, default="#3B82F6")
    created_at = Column(DateTime, server_default=func.now())


class ListItem(Base):
    __tablename__ = "list_items"

    id = Column(Integer, primary_key=True, index=True)
    list_id = Column(Integer, nullable=False, index=True)
    text = Column(String, nullable=False)
    checked = Column(Boolean, default=False)
    position = Column(Integer, default=0)           # for ordering
    notes = Column(Text, default="")               # Apple Reminders-style note
    due_date = Column(Date, nullable=True)          # optional deadline
    due_time = Column(String, nullable=True)        # optional time HH:MM
    priority = Column(Integer, default=0)           # 0=none, 1=low, 2=medium, 3=high
    created_at = Column(DateTime, server_default=func.now())


# ── Sleep ────────────────────────────────────────────────────────

class SleepEntry(Base):
    __tablename__ = "sleep_entries"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, unique=True, index=True)
    bedtime = Column(String, nullable=True)         # HH:MM (time went to bed)
    wake_time = Column(String, nullable=True)       # HH:MM (time woke up)
    hours = Column(Float, nullable=False)            # total hours slept
    quality = Column(Integer, nullable=True)         # 1-5 subjective rating
    notes = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())


# ── Flow Timer ───────────────────────────────────────────────────

class FlowPreset(Base):
    __tablename__ = "flow_presets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)           # "Programming", "Gym", etc.
    work_minutes = Column(Integer, default=50)
    break_minutes = Column(Integer, default=10)
    color = Column(String, default="#3B82F6")
    icon = Column(String, default="⏱️")
    created_at = Column(DateTime, server_default=func.now())


class FlowSession(Base):
    __tablename__ = "flow_sessions"

    id = Column(Integer, primary_key=True, index=True)
    preset_id = Column(Integer, nullable=True)       # link to FlowPreset
    preset_name = Column(String, nullable=False)     # denormalized for history
    date = Column(Date, nullable=False)
    start_time = Column(String, nullable=False)      # HH:MM
    end_time = Column(String, nullable=True)         # HH:MM (null if still running)
    planned_minutes = Column(Integer, nullable=False) # intended work duration
    actual_minutes = Column(Integer, nullable=True)  # actual duration (if stopped early)
    completed = Column(Boolean, default=False)       # finished full cycle?
    color = Column(String, default="#3B82F6")
    notes = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())


# ── Habits / Routines ────────────────────────────────────────────

class Habit(Base):
    __tablename__ = "habits"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)            # "Gym", "Meditação", etc.
    icon = Column(String, default="✅")
    color = Column(String, default="#10B981")
    days = Column(String, default="daily")           # "daily", "weekdays", or "0,1,3,5" (Mon=0..Sun=6)
    fixed_time = Column(String, nullable=True)       # HH:MM if fixed time, null if flexible
    active = Column(Boolean, default=True)
    position = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())


class HabitCompletion(Base):
    __tablename__ = "habit_completions"

    id = Column(Integer, primary_key=True, index=True)
    habit_id = Column(Integer, nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    completed_at = Column(String, nullable=False)    # HH:MM - time user did it
    notes = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())


# ── Notes ────────────────────────────────────────────────────────

class NoteFolder(Base):
    __tablename__ = "note_folders"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    icon = Column(String, default="📁")
    color = Column(String, default="#F59E0B")
    position = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, default="")
    folder_id = Column(Integer, nullable=True, index=True)
    pinned = Column(Boolean, default=False)
    color = Column(String, default="#F59E0B")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ── Investments ──────────────────────────────────────────────────

class InvestmentPosition(Base):
    __tablename__ = "investment_positions"

    id = Column(Integer, primary_key=True, index=True)
    instrument = Column(String, nullable=False)
    isin = Column(String, nullable=True)
    currency = Column(String, default="EUR")
    quantity = Column(Float, nullable=False)
    avg_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=True)
    current_value_eur = Column(Float, nullable=True)
    return_eur = Column(Float, nullable=True)
    fx_rate = Column(Float, default=1.0)
    source = Column(String, default="trading212")  # trading212 / finst
    statement_date = Column(String, nullable=True)  # YYYY-MM for monthly snapshots
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class InvestmentTrade(Base):
    __tablename__ = "investment_trades"

    id = Column(Integer, primary_key=True, index=True)
    execution_time = Column(DateTime, nullable=False)
    instrument = Column(String, nullable=False)
    isin = Column(String, nullable=True)
    currency = Column(String, default="EUR")
    direction = Column(String, nullable=False)  # Buy / Sell
    quantity = Column(Float, nullable=False)
    execution_price = Column(Float, nullable=False)
    value = Column(Float, nullable=False)
    value_eur = Column(Float, nullable=False)
    fx_rate = Column(Float, default=1.0)
    fx_fee = Column(Float, default=0.0)
    source = Column(String, default="trading212")  # trading212 / finst


class InvestmentTransaction(Base):
    __tablename__ = "investment_transactions"

    id = Column(Integer, primary_key=True, index=True)
    time = Column(DateTime, nullable=False)
    type = Column(String, nullable=False)  # Deposit, Withdrawal, Dividend
    currency = Column(String, default="EUR")
    amount = Column(Float, nullable=False)
    source = Column(String, default="trading212")  # trading212 / finst


class InvestmentSummary(Base):
    __tablename__ = "investment_summary"

    id = Column(Integer, primary_key=True, index=True)
    statement_date = Column(Date, nullable=False)
    account_value = Column(Float, default=0.0)
    deposits = Column(Float, default=0.0)
    withdrawals = Column(Float, default=0.0)
    open_return = Column(Float, default=0.0)
    fx_fees = Column(Float, default=0.0)
    dividends = Column(Float, default=0.0)


class InvestmentAllocation(Base):
    __tablename__ = "investment_allocations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)              # display name
    ticker = Column(String, nullable=False)            # ticker symbol
    asset_type = Column(String, default="etf")        # etf, crypto, stock
    percentage = Column(Float, nullable=False)          # 0-100
    sort_order = Column(Integer, default=0)
    is_rotational = Column(Boolean, default=False)     # true for "ação rotativa" slots


class InvestmentMonthlyPlan(Base):
    __tablename__ = "investment_monthly_plans"

    id = Column(Integer, primary_key=True, index=True)
    month = Column(String, nullable=False, unique=True)   # "2026-04"
    budget = Column(Float, nullable=False, default=300)
    rotational_choices = Column(Text, default="{}")        # JSON: {"alloc_id": "GOOG - Alphabet"}
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class PlanAnalysisLatest(Base):
    """Latest "Análise IA do Plano" — single-row, overwritten on every generation."""
    __tablename__ = "plan_analysis_latest"

    id = Column(Integer, primary_key=True)                 # always 1
    generated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    payload_json = Column(Text, nullable=False, default="{}")  # full analysis dict


class InvestmentPlan(Base):
    __tablename__ = "investment_plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)              # display name: "Vanguard S&P 500", "Anthropic"
    instrument = Column(String, nullable=False)        # ticker: VUAA, ANTHR, etc.
    asset_type = Column(String, default="etf")        # etf, crypto, stock
    target_amount_eur = Column(Float, nullable=True)   # quanto quer investir (€)
    status = Column(String, default="pending")         # pending, bought, cancelled
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class InvestmentSignal(Base):
    """Daily AI-generated investment signal based on market news + portfolio."""
    __tablename__ = "investment_signals"

    id = Column(Integer, primary_key=True, index=True)
    generated_at = Column(DateTime, server_default=func.now(), index=True)
    headline = Column(String, nullable=False)           # short summary, e.g. "Reforçar BTC este mês"
    market_summary = Column(Text, default="")           # AI's read of the market
    suggestions_json = Column(Text, default="[]")       # JSON list: [{ticker, name, asset_type, action, conviction, amount_eur, thesis}]
    sources_json = Column(Text, default="[]")           # JSON list of news headlines + urls used
    raw_response = Column(Text, default="")             # full raw model output (debug)
    model = Column(String, default="gpt-4o-mini")
    cost_usd = Column(Float, nullable=True)              # estimated cost of this call
    prompt_hash = Column(String, nullable=True)          # SHA256 of the user prompt (audit/repro)
    prompt_version = Column(String, default="v1")        # bump when prompt template changes
    risk_critique_json = Column(Text, default="")        # optional 2nd-pass critique by signal-level


# ── Mood Tracker ─────────────────────────────────────────────────

class MoodEntry(Base):
    __tablename__ = "mood_entries"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, unique=True, index=True)
    mood = Column(Integer, nullable=False)             # 1=😢, 2=😕, 3=😐, 4=😊, 5=🤩
    note = Column(Text, default="")
    # Multiple feeling tags stored as comma-separated: "sono,stress,cansado"
    tags = Column(String, default="")
    created_at = Column(DateTime, server_default=func.now())


# ── Daily Journal (Diário Rápido) ────────────────────────────────

class DailyJournal(Base):
    __tablename__ = "daily_journals"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, unique=True, index=True)
    content = Column(Text, default="")                 # max ~3 sentences
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ── Budget Limits ────────────────────────────────────────────────

class BudgetLimit(Base):
    __tablename__ = "budget_limits"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, nullable=False, unique=True, index=True)
    monthly_limit = Column(Float, nullable=False)
    color = Column(String, default="#3B82F6")
    created_at = Column(DateTime, server_default=func.now())


# ── Subscriptions ────────────────────────────────────────────────

class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="EUR")
    billing_cycle = Column(String, default="monthly")  # monthly, yearly, weekly
    next_renewal = Column(Date, nullable=True)
    category = Column(String, default="subscriptions")
    active = Column(Boolean, default=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())


# ── Day Templates ────────────────────────────────────────────────

class DayTemplate(Base):
    __tablename__ = "day_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)              # "Dia de trabalho", "Dia de descanso"
    icon = Column(String, default="📋")
    color = Column(String, default="#3B82F6")
    events_json = Column(Text, default="[]")           # JSON array of event templates
    created_at = Column(DateTime, server_default=func.now())


# ── App Usage Tracker ────────────────────────────────────────────

class AppUsageSession(Base):
    __tablename__ = "app_usage_sessions"

    id = Column(Integer, primary_key=True, index=True)
    app_name = Column(String, nullable=False, index=True)  # e.g. "Visual Studio Code"
    window_title = Column(String, default="")              # current window title
    bundle_id = Column(String, nullable=True)              # e.g. com.microsoft.VSCode
    date = Column(Date, nullable=False, index=True)        # local date the session started
    start_time = Column(DateTime, nullable=False)          # full timestamp
    end_time = Column(DateTime, nullable=False)            # full timestamp
    duration_seconds = Column(Integer, nullable=False)     # end - start
    created_at = Column(DateTime, server_default=func.now())


class AppUsageBlocklist(Base):
    __tablename__ = "app_usage_blocklist"

    id = Column(Integer, primary_key=True, index=True)
    # Match either by bundle_id (preferred, exact) or app_name (fallback).
    bundle_id = Column(String, nullable=True, index=True)
    app_name = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now())


class AppCategoryOverride(Base):
    """User override for app → category mapping. Not set → use the built-in rules."""
    __tablename__ = "app_category_overrides"

    id = Column(Integer, primary_key=True, index=True)
    bundle_id = Column(String, nullable=True, index=True)
    app_name = Column(String, nullable=True, index=True)
    category = Column(String, nullable=False)  # productivity, gaming, social, communication, entertainment, other
    created_at = Column(DateTime, server_default=func.now())


class AppUsageGoal(Base):
    """Goals set by the user per category. direction='min' → want at least; 'max' → want at most."""
    __tablename__ = "app_usage_goals"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, nullable=False, index=True)
    direction = Column(String, nullable=False, default="max")   # 'min' or 'max'
    target_seconds = Column(Integer, nullable=False)            # daily target
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class CodeProjectTodo(Base):
    """Per-project TODO bound to a project_path detected by the VS Code activity scanner."""
    __tablename__ = "code_project_todos"

    id = Column(Integer, primary_key=True, index=True)
    project_path = Column(String, nullable=False, index=True)
    content = Column(Text, nullable=False)
    done = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    done_at = Column(DateTime, nullable=True)


class CodeProjectNote(Base):
    """Per-project note. source='manual' or 'ai' (AI-generated changelog entry)."""
    __tablename__ = "code_project_notes"

    id = Column(Integer, primary_key=True, index=True)
    project_path = Column(String, nullable=False, index=True)
    content = Column(Text, nullable=False)
    source = Column(String, nullable=False, default="manual")
    note_date = Column(Date, nullable=True, index=True)  # the activity day this note refers to
    created_at = Column(DateTime, server_default=func.now())


class CodeFileSnapshot(Base):
    """Periodic baseline snapshot of a code file. Used to compute reliable diffs for
    AI notes when neither VS Code Local History nor git can provide one (e.g. files
    edited via Claude Code/terminal in non-git projects)."""
    __tablename__ = "code_file_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    project_path = Column(String, nullable=False, index=True)
    abs_path = Column(String, nullable=False, index=True)
    captured_at = Column(DateTime, nullable=False, index=True)
    content_hash = Column(String, nullable=False)
    content = Column(Text, nullable=False)


# ── Screen Time (knowledgeC.db) ──────────────────────────────────

class ScreenTimeDeviceLabel(Base):
    """Etiqueta humana atribuída a um device_id do knowledgeC.db.
    Permite distinguir Mac/iPhone/iPad nas listagens."""
    __tablename__ = "screen_time_device_labels"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, nullable=False, unique=True, index=True)
    label = Column(String, nullable=False, default="")
    kind = Column(String, nullable=False, default="unknown")  # mac, iphone, ipad, watch, unknown
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
