from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional, List


# ── Day Types ────────────────────────────────────────────────────

class DayTypeCreate(BaseModel):
    date: date
    type_name: str
    color: str = "#3B82F6"
    note: str = ""


class DayTypeOut(BaseModel):
    id: int
    date: date
    type_name: str
    color: str
    note: str

    model_config = {"from_attributes": True}


# ── Events ───────────────────────────────────────────────────────

class EventCreate(BaseModel):
    title: str
    description: str = ""
    date: date
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    event_type: str = "fixed"
    category: str = "general"
    color: str = "#3B82F6"
    recurrence: str = "none"
    recurrence_end: Optional[date] = None


class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    date: Optional[date] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    event_type: Optional[str] = None
    category: Optional[str] = None
    color: Optional[str] = None
    completed: Optional[bool] = None
    recurrence: Optional[str] = None
    recurrence_end: Optional[date] = None


class EventOut(BaseModel):
    id: int
    title: str
    description: str
    date: date
    start_time: Optional[str]
    end_time: Optional[str]
    event_type: str
    category: str
    color: str
    completed: bool
    recurrence: str = "none"
    recurrence_end: Optional[date] = None
    is_recurring_instance: bool = False
    parent_id: Optional[int] = None

    model_config = {"from_attributes": True}


# ── Expenses ─────────────────────────────────────────────────────

class ExpenseCreate(BaseModel):
    description: str
    amount: float
    category: str = "other"
    date: date
    trip_id: Optional[int] = None
    notes: str = ""
    original_amount: Optional[float] = None
    original_currency: Optional[str] = None
    merchant_city: Optional[str] = None
    merchant_country: Optional[str] = None


class ExpenseUpdate(BaseModel):
    description: Optional[str] = None
    amount: Optional[float] = None
    category: Optional[str] = None
    date: Optional[date] = None
    trip_id: Optional[int] = None
    notes: Optional[str] = None
    original_amount: Optional[float] = None
    original_currency: Optional[str] = None
    merchant_city: Optional[str] = None
    merchant_country: Optional[str] = None


class ExpenseOut(BaseModel):
    id: int
    description: str
    amount: float
    category: str
    date: date
    receipt_image: Optional[str]
    trip_id: Optional[int]
    notes: str
    original_amount: Optional[float]
    original_currency: Optional[str]
    merchant_city: Optional[str]
    merchant_country: Optional[str]

    model_config = {"from_attributes": True}


# ── LoL Games ────────────────────────────────────────────────────

class LolGameCreate(BaseModel):
    date: date
    won: bool
    champion_played: Optional[str] = None
    champion_against: Optional[str] = None
    role: Optional[str] = None
    my_fault: Optional[bool] = None
    kills: Optional[int] = None
    deaths: Optional[int] = None
    assists: Optional[int] = None
    game_duration: Optional[int] = None
    match_id: Optional[str] = None
    notes: str = ""


class LolGameUpdate(BaseModel):
    date: Optional[date] = None
    won: Optional[bool] = None
    champion_played: Optional[str] = None
    champion_against: Optional[str] = None
    role: Optional[str] = None
    my_fault: Optional[bool] = None
    notes: Optional[str] = None


class LolGameOut(BaseModel):
    id: int
    match_id: Optional[str] = None
    date: date
    won: bool
    champion_played: Optional[str]
    champion_against: Optional[str]
    role: Optional[str]
    my_fault: Optional[bool]
    kills: Optional[int] = None
    deaths: Optional[int] = None
    assists: Optional[int] = None
    game_duration: Optional[int] = None
    notes: str

    model_config = {"from_attributes": True}


# ── Trips ────────────────────────────────────────────────────────

class TripCreate(BaseModel):
    destination: str
    country: Optional[str] = None
    start_date: date
    end_date: date
    notes: str = ""
    flights_cost: float = 0
    accommodation_cost: float = 0
    food_budget: float = 0
    other_costs: float = 0


class TripUpdate(BaseModel):
    destination: Optional[str] = None
    country: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notes: Optional[str] = None
    flights_cost: Optional[float] = None
    accommodation_cost: Optional[float] = None
    food_budget: Optional[float] = None
    other_costs: Optional[float] = None
    rating_food: Optional[float] = None
    rating_places: Optional[float] = None
    rating_nightlife: Optional[float] = None
    rating_gajas: Optional[float] = None
    rating_overall: Optional[float] = None


class TripOut(BaseModel):
    id: int
    destination: str
    country: Optional[str]
    start_date: date
    end_date: date
    cover_image: Optional[str]
    notes: str
    flights_cost: float
    accommodation_cost: float
    food_budget: float
    other_costs: float
    total_cost: float = 0
    rating_food: Optional[float] = None
    rating_places: Optional[float] = None
    rating_nightlife: Optional[float] = None
    rating_gajas: Optional[float] = None
    rating_overall: Optional[float] = None

    model_config = {"from_attributes": True}


class TripPlaceCreate(BaseModel):
    trip_id: int
    name: str
    description: str = ""
    is_free: bool = True
    estimated_cost: float = 0
    address: Optional[str] = None
    url: Optional[str] = None


class TripPlaceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_free: Optional[bool] = None
    estimated_cost: Optional[float] = None
    visited: Optional[bool] = None
    address: Optional[str] = None
    url: Optional[str] = None
    rating: Optional[float] = None
    review: Optional[str] = None


class TripPlaceOut(BaseModel):
    id: int
    trip_id: int
    name: str
    description: str
    is_free: bool
    estimated_cost: float
    visited: bool
    suggested: bool
    address: Optional[str]
    url: Optional[str]
    rating: Optional[float] = None
    review: str = ""

    model_config = {"from_attributes": True}


class TripRatingCreate(BaseModel):
    category: str   # comida, sitio, noite, encontro, experiencia, outro
    name: str
    rating: float
    notes: str = ""
    date: Optional[date] = None


class TripRatingUpdate(BaseModel):
    category: Optional[str] = None
    name: Optional[str] = None
    rating: Optional[float] = None
    notes: Optional[str] = None
    date: Optional[date] = None


class TripRatingOut(BaseModel):
    id: int
    trip_id: int
    category: str
    name: str
    rating: float
    notes: str
    date: Optional[date] = None

    model_config = {"from_attributes": True}


# ── Trip Gajas ────────────────────────────────────────────────────

class TripGajaCreate(BaseModel):
    name: str
    rating_face: Optional[float] = None
    rating_body: Optional[float] = None
    rating_vibe: Optional[float] = None
    rating_personality: Optional[float] = None
    rating_overall: Optional[float] = None


class TripGajaUpdate(BaseModel):
    name: Optional[str] = None
    rating_face: Optional[float] = None
    rating_body: Optional[float] = None
    rating_vibe: Optional[float] = None
    rating_personality: Optional[float] = None
    rating_overall: Optional[float] = None


class TripGajaOut(BaseModel):
    id: int
    trip_id: int
    name: str
    rating_face: Optional[float] = None
    rating_body: Optional[float] = None
    rating_vibe: Optional[float] = None
    rating_personality: Optional[float] = None
    rating_overall: Optional[float] = None

    model_config = {"from_attributes": True}


# ── Lists ────────────────────────────────────────────────────────

class UserListCreate(BaseModel):
    name: str
    icon: str = "📝"
    color: str = "#3B82F6"


class UserListUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None


class UserListOut(BaseModel):
    id: int
    name: str
    icon: str
    color: str
    item_count: int = 0
    checked_count: int = 0

    model_config = {"from_attributes": True}


class ListItemCreate(BaseModel):
    text: str
    position: int = 0
    notes: str = ""
    due_date: Optional[date] = None
    due_time: Optional[str] = None
    priority: int = 0


class ListItemUpdate(BaseModel):
    text: Optional[str] = None
    checked: Optional[bool] = None
    position: Optional[int] = None
    notes: Optional[str] = None
    due_date: Optional[date] = None
    due_time: Optional[str] = None
    priority: Optional[int] = None


class ListItemOut(BaseModel):
    id: int
    list_id: int
    text: str
    checked: bool
    position: int
    notes: str = ""
    due_date: Optional[date] = None
    due_time: Optional[str] = None
    priority: int = 0

    model_config = {"from_attributes": True}


# ── Sleep ────────────────────────────────────────────────────────

class SleepCreate(BaseModel):
    date: date
    bedtime: Optional[str] = None
    wake_time: Optional[str] = None
    hours: float
    quality: Optional[int] = None
    notes: str = ""


class SleepUpdate(BaseModel):
    date: Optional[date] = None
    bedtime: Optional[str] = None
    wake_time: Optional[str] = None
    hours: Optional[float] = None
    quality: Optional[int] = None
    notes: Optional[str] = None


class SleepOut(BaseModel):
    id: int
    date: date
    bedtime: Optional[str]
    wake_time: Optional[str]
    hours: float
    quality: Optional[int]
    notes: str

    model_config = {"from_attributes": True}


# ── Flow Timer ───────────────────────────────────────────────────

class FlowPresetCreate(BaseModel):
    name: str
    work_minutes: int = 50
    break_minutes: int = 10
    color: str = "#3B82F6"
    icon: str = "⏱️"


class FlowPresetUpdate(BaseModel):
    name: Optional[str] = None
    work_minutes: Optional[int] = None
    break_minutes: Optional[int] = None
    color: Optional[str] = None
    icon: Optional[str] = None


class FlowPresetOut(BaseModel):
    id: int
    name: str
    work_minutes: int
    break_minutes: int
    color: str
    icon: str

    model_config = {"from_attributes": True}


class FlowSessionCreate(BaseModel):
    preset_id: Optional[int] = None
    preset_name: str
    date: date
    start_time: str
    end_time: Optional[str] = None
    planned_minutes: int
    actual_minutes: Optional[int] = None
    completed: bool = False
    color: str = "#3B82F6"
    notes: str = ""


class FlowSessionOut(BaseModel):
    id: int
    preset_id: Optional[int]
    preset_name: str
    date: date
    start_time: str
    end_time: Optional[str]
    planned_minutes: int
    actual_minutes: Optional[int]
    completed: bool
    color: str
    notes: str

    model_config = {"from_attributes": True}


# ── Notes ────────────────────────────────────────────────────────

class NoteFolderCreate(BaseModel):
    name: str
    icon: str = "📁"
    color: str = "#F59E0B"


class NoteFolderUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    position: Optional[int] = None


class NoteFolderOut(BaseModel):
    id: int
    name: str
    icon: str
    color: str
    position: int
    note_count: int = 0

    model_config = {"from_attributes": True}


class NoteCreate(BaseModel):
    title: str = ""
    content: str = ""
    folder_id: Optional[int] = None
    pinned: bool = False
    color: str = "#F59E0B"


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    folder_id: Optional[int] = None
    pinned: Optional[bool] = None
    color: Optional[str] = None


class NoteOut(BaseModel):
    id: int
    title: str
    content: str
    folder_id: Optional[int]
    pinned: bool
    color: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Investments ──────────────────────────────────────────────────

class InvestmentPositionOut(BaseModel):
    id: int
    instrument: str
    isin: Optional[str]
    currency: str
    quantity: float
    avg_price: float
    current_price: Optional[float]
    current_value_eur: Optional[float]
    return_eur: Optional[float]
    fx_rate: float
    source: Optional[str] = "trading212"
    statement_date: Optional[str] = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class InvestmentTradeOut(BaseModel):
    id: int
    execution_time: datetime
    instrument: str
    isin: Optional[str]
    currency: str
    direction: str
    quantity: float
    execution_price: float
    value: float
    value_eur: float
    fx_rate: float
    fx_fee: float
    source: Optional[str] = "trading212"

    model_config = {"from_attributes": True}


class InvestmentTransactionOut(BaseModel):
    id: int
    time: datetime
    type: str
    currency: str
    amount: float
    source: Optional[str] = "trading212"

    model_config = {"from_attributes": True}


class InvestmentSummaryOut(BaseModel):
    id: int
    statement_date: date
    account_value: float
    deposits: float
    withdrawals: float
    open_return: float
    fx_fees: float
    dividends: float

    model_config = {"from_attributes": True}


# ── Investment Allocations ────────────────────────────────────────

class InvestmentAllocationCreate(BaseModel):
    name: str
    ticker: str
    asset_type: str = "etf"
    percentage: float
    sort_order: int = 0
    is_rotational: bool = False


class InvestmentAllocationUpdate(BaseModel):
    name: Optional[str] = None
    ticker: Optional[str] = None
    asset_type: Optional[str] = None
    percentage: Optional[float] = None
    sort_order: Optional[int] = None
    is_rotational: Optional[bool] = None


class InvestmentAllocationOut(BaseModel):
    id: int
    name: str
    ticker: str
    asset_type: str
    percentage: float
    sort_order: int
    is_rotational: bool

    model_config = {"from_attributes": True}


class MonthlyPlanUpdate(BaseModel):
    budget: Optional[float] = None
    rotational_choices: Optional[dict] = None


class MonthlyPlanOut(BaseModel):
    id: int
    month: str
    budget: float
    rotational_choices: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Investment Plans ─────────────────────────────────────────────

class InvestmentPlanCreate(BaseModel):
    name: str
    instrument: str
    asset_type: str = "etf"
    target_amount_eur: Optional[float] = None


class InvestmentPlanUpdate(BaseModel):
    target_amount_eur: Optional[float] = None
    status: Optional[str] = None


class InvestmentPlanOut(BaseModel):
    id: int
    name: str
    instrument: str
    asset_type: str
    target_amount_eur: Optional[float]
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Investment Signals (daily AI suggestions) ────────────────────

class SignalSuggestion(BaseModel):
    ticker: str
    name: str
    asset_type: str          # etf, crypto, stock
    action: str              # buy, hold, reduce, watch
    conviction: str          # high, medium, low
    amount_eur: Optional[float] = None
    thesis: str              # 2-3 lines explaining why


class SignalSource(BaseModel):
    title: str
    url: str
    source: str              # "Yahoo Finance", "CoinDesk", etc.


class InvestmentSignalOut(BaseModel):
    id: int
    generated_at: datetime
    headline: str
    market_summary: str
    suggestions: List[SignalSuggestion]
    sources: List[SignalSource]
    model: str
    cost_usd: Optional[float] = None

    model_config = {"from_attributes": True}


# ── Habits / Routines ────────────────────────────────────────────

class HabitCreate(BaseModel):
    name: str
    icon: str = "✅"
    color: str = "#10B981"
    days: str = "daily"              # "daily", "weekdays", or "0,1,3,5"
    fixed_time: Optional[str] = None # HH:MM or null
    position: int = 0


class HabitUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    days: Optional[str] = None
    fixed_time: Optional[str] = None
    active: Optional[bool] = None
    position: Optional[int] = None


class HabitOut(BaseModel):
    id: int
    name: str
    icon: str
    color: str
    days: str
    fixed_time: Optional[str]
    active: bool
    position: int
    created_at: datetime

    model_config = {"from_attributes": True}


class HabitCompletionCreate(BaseModel):
    date: date
    completed_at: str            # HH:MM
    notes: str = ""


class HabitCompletionOut(BaseModel):
    id: int
    habit_id: int
    date: date
    completed_at: str
    notes: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Mood Tracker ─────────────────────────────────────────────────

class MoodCreate(BaseModel):
    date: date
    mood: int              # 1-5
    note: str = ""
    tags: str = ""         # comma-separated: "sono,stress,cansado"


class MoodOut(BaseModel):
    id: int
    date: date
    mood: int
    note: str
    tags: str = ""
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Daily Journal ────────────────────────────────────────────────

class JournalCreate(BaseModel):
    date: date
    content: str = ""


class JournalOut(BaseModel):
    id: int
    date: date
    content: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Budget Limits ────────────────────────────────────────────────

class BudgetLimitCreate(BaseModel):
    category: str
    monthly_limit: float
    color: str = "#3B82F6"


class BudgetLimitUpdate(BaseModel):
    monthly_limit: Optional[float] = None
    color: Optional[str] = None


class BudgetLimitOut(BaseModel):
    id: int
    category: str
    monthly_limit: float
    color: str

    model_config = {"from_attributes": True}


# ── Subscriptions ────────────────────────────────────────────────

class SubscriptionCreate(BaseModel):
    name: str
    amount: float
    currency: str = "EUR"
    billing_cycle: str = "monthly"
    next_renewal: Optional[date] = None
    category: str = "subscriptions"
    notes: str = ""


class SubscriptionUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    billing_cycle: Optional[str] = None
    next_renewal: Optional[date] = None
    category: Optional[str] = None
    active: Optional[bool] = None
    notes: Optional[str] = None


class SubscriptionOut(BaseModel):
    id: int
    name: str
    amount: float
    currency: str
    billing_cycle: str
    next_renewal: Optional[date]
    category: str
    active: bool
    notes: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Day Templates ────────────────────────────────────────────────

class DayTemplateCreate(BaseModel):
    name: str
    icon: str = "📋"
    color: str = "#3B82F6"
    events_json: str = "[]"


class DayTemplateUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    events_json: Optional[str] = None


class DayTemplateOut(BaseModel):
    id: int
    name: str
    icon: str
    color: str
    events_json: str

    model_config = {"from_attributes": True}


# ── App Usage ─────────────────────────────────────────────────────

class AppUsageSessionCreate(BaseModel):
    app_name: str
    window_title: str = ""
    bundle_id: Optional[str] = None
    start_time: datetime
    end_time: datetime


class AppUsageSessionOut(BaseModel):
    id: int
    app_name: str
    window_title: str
    bundle_id: Optional[str]
    date: date
    start_time: datetime
    end_time: datetime
    duration_seconds: int

    model_config = {"from_attributes": True}


class AppUsageGoalCreate(BaseModel):
    category: str
    direction: str = "max"         # 'min' or 'max'
    target_seconds: int
    active: bool = True


class AppUsageGoalUpdate(BaseModel):
    direction: Optional[str] = None
    target_seconds: Optional[int] = None
    active: Optional[bool] = None


class AppUsageGoalOut(BaseModel):
    id: int
    category: str
    direction: str
    target_seconds: int
    active: bool

    model_config = {"from_attributes": True}
