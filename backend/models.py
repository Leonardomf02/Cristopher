from sqlalchemy import Column, Integer, String, Float, Boolean, Date, DateTime, Text, Enum as SAEnum, UniqueConstraint
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
    completed_at = Column(String, nullable=True)   # HH:MM a que foi dado check (tarefas flexíveis)
    # Recurrence
    recurrence = Column(String, default="none")    # none, daily, weekdays, weekly, biweekly, monthly, yearly
    recurrence_end = Column(Date, nullable=True)   # null = forever
    recurrence_exceptions = Column(Text, default="[]")  # JSON list of excluded dates
    # Instâncias recorrentes são virtuais (não têm linha própria), por isso o "concluído"
    # de cada ocorrência vive aqui: JSON list de datas concluídas.
    recurrence_completions = Column(Text, default="[]")
    created_at = Column(DateTime, server_default=func.now())


# ── Expenses ─────────────────────────────────────────────────────

class ExpenseCategory(str, enum.Enum):
    FOOD = "food"
    TRANSPORT = "transport"
    ENTERTAINMENT = "entertainment"
    NIGHTLIFE = "nightlife"
    SUBSCRIPTIONS = "subscriptions"
    SHOPPING = "shopping"
    HEALTH = "health"
    BILLS = "bills"
    TRAVEL = "travel"
    INVEST = "invest"
    OTHER = "other"


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    description = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    category = Column(String, default=ExpenseCategory.OTHER)
    date = Column(Date, nullable=False)
    time_of_day = Column(String, nullable=True)    # "HH:MM" quando o extracto ou o recibo traz a hora
    bank_tx_id = Column(String, nullable=True, index=True)   # id da transacção no banco (evita duplicados)
    receipt_image = Column(String, nullable=True)  # file path to receipt photo
    trip_id = Column(Integer, nullable=True)       # link to trip if travel expense
    notes = Column(Text, default="")
    original_amount = Column(Float, nullable=True)    # amount in original currency
    original_currency = Column(String, nullable=True) # e.g. PLN, SEK, RON
    merchant_city = Column(String, nullable=True)     # e.g. Krakow, Stockholm
    merchant_country = Column(String, nullable=True)  # e.g. POL, SWE, LTU
    # spend | income | transfer | reversal — nem tudo o que passa na conta é gasto
    # (ver expense_kind.py). Só `spend` conta para os totais.
    kind = Column(String, default="spend", index=True)
    # Compra grande e pontual (a mota de 7.300€). Conta no total do mês, mas fica
    # fora das réguas: comparar um mês com mota contra um mês de supermercado não
    # diz nada, e as médias, a previsão e o "dia caro" passavam a ser sobre ela.
    extraordinary = Column(Boolean, default=False, index=True)
    # Pago com Klarna em N vezes (vazio = não é Klarna). O movimento é a primeira
    # prestação, que é o que o banco cobra no dia da compra — ver klarna.py.
    klarna_installments = Column(Integer, nullable=True)
    # O gás de 35,60€ que ele paga pela casa e os amigos devolvem por MB Way: o
    # dinheiro deles liga-se à conta (`reimburses_id`) e passa a gasto negativo da
    # mesma categoria, por isso todas as somas de `spend` já dão só a parte dele.
    # `split_people` é por quantos se divide (com ele), para saber quem falta.
    # Com várias contas (os dois levantamentos de 70€ e 30€ e o Rafael a mandar
    # 75€), `reimburses_id` é a primeira e a repartição vive em
    # `reimbursement_links`. `my_share` é a parte dele quando a divisão não é por
    # igual — a alternativa a `split_people`.
    reimburses_id = Column(Integer, nullable=True, index=True)
    split_people = Column(Integer, nullable=True)
    my_share = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class MonthlyIncome(Base):
    __tablename__ = "monthly_income"

    id = Column(Integer, primary_key=True, index=True)
    month = Column(Integer, nullable=False)   # 1-12
    year = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False, default=1040.98)


class ReimbursementLink(Base):
    """Quanto de uma entrada desconta em cada conta."""
    __tablename__ = "reimbursement_links"

    id = Column(Integer, primary_key=True, index=True)
    income_id = Column(Integer, nullable=False, index=True)
    expense_id = Column(Integer, nullable=False, index=True)
    amount = Column(Float, nullable=False)


class ReimbursementDismissed(Base):
    """"Não é" a uma sugestão de reembolso — senão voltava em cada visita."""
    __tablename__ = "reimbursement_dismissed"
    __table_args__ = (UniqueConstraint("income_id", "expense_id"),)

    id = Column(Integer, primary_key=True, index=True)
    income_id = Column(Integer, nullable=False, index=True)
    expense_id = Column(Integer, nullable=False)


class SalaryPayday(Base):
    """O dia em que o salário entrou, quando ele o corrige à mão. Substitui o que
    a conta mostra nesse mês."""
    __tablename__ = "salary_paydays"

    id = Column(Integer, primary_key=True, index=True)
    month = Column(String, nullable=False, unique=True)   # YYYY-MM
    date = Column(Date, nullable=False)
    amount = Column(Float, nullable=True)                 # quando marcou o movimento


class ExpenseCategory(Base):
    """Categorias que ele cria. As de origem vivem no código (`bank_categories.CATEGORIAS`)."""
    __tablename__ = "expense_categories"

    id = Column(Integer, primary_key=True, index=True)
    value = Column(String, nullable=False, unique=True)
    label = Column(String, nullable=False)
    emoji = Column(String, default="🏷️")
    created_at = Column(DateTime, server_default=func.now())


class WishlistItem(Base):
    __tablename__ = "wishlist_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)              # target price / goal
    priority = Column(String, default="medium")        # high | medium | low
    category = Column(String, default="other")         # expense category used when purchased
    url = Column(String, nullable=True)                # link to the product
    notes = Column(Text, default="")
    saved_amount = Column(Float, default=0.0)          # how much already put aside
    purchased = Column(Boolean, default=False)
    purchased_date = Column(Date, nullable=True)
    expense_id = Column(Integer, nullable=True)         # expense created on purchase
    watch_id = Column(Integer, nullable=True)           # deal watch a vigiar este item
    created_at = Column(DateTime, server_default=func.now())


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
    # Desempenho. A Riot manda isto em cada jogo e era deitado fora: ficavam 488
    # jogos só com vitória/derrota. Com winrate, provar que ele joga melhor de
    # Wukong que de Lee Sin dava z=1,6 em 142 jogos — não chega. Estes são
    # contínuos: cada jogo é uma medição em vez de uma moeda ao ar, e ~30 jogos
    # bastam para a diferença aparecer.
    cs = Column(Integer, nullable=True)              # minions + monstros
    cs_jungle = Column(Integer, nullable=True)       # só monstros (é jungler)
    gold = Column(Integer, nullable=True)
    damage = Column(Integer, nullable=True)          # dano a campeões
    damage_taken = Column(Integer, nullable=True)
    vision = Column(Integer, nullable=True)          # vision score
    team_kills = Column(Integer, nullable=True)      # para a participação em abates
    notes = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())


class LolDuel(Base):
    """O jogo dele contra o jungler adversário, medida a medida.

    A Riot não publica referências por elo, e as dos sites são de outra amostra e
    outro patch. Mas em cada partida dele há um jungler do mesmo elo, no mesmo
    patch, no mesmo jogo — 500 comparações emparelhadas de graça. É a régua.

    Tabela à parte para não inchar `lol_games`, com colunas nomeadas (e não um
    JSON) porque é isso que deixa o Perguntar escrever SQL sobre elas, como em
    `garmin_days`. `challenges_json` guarda a cauda dos 128 campos que a Riot
    manda em cada partida, para acrescentar métricas sem re-sincronizar 500 jogos.
    """

    __tablename__ = "lol_duels"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(String, nullable=False, unique=True, index=True)
    date = Column(Date, nullable=False, index=True)
    won = Column(Boolean, nullable=False)
    duration = Column(Integer, nullable=True)          # segundos
    champion = Column(String, nullable=True)
    opp_champion = Column(String, nullable=True)

    # Antes de o jogo se decidir. Aos 10 minutos as vitórias e as derrotas dele
    # são indistinguíveis no ouro; aos 15 já está decidido. É esta janela que
    # separa conselho de descrição do resultado.
    jungle_cs10 = Column(Float, nullable=True)
    opp_jungle_cs10 = Column(Float, nullable=True)
    takedowns10 = Column(Integer, nullable=True)
    opp_takedowns10 = Column(Integer, nullable=True)
    early_ganks = Column(Integer, nullable=True)       # abates em laners na selva cedo
    opp_early_ganks = Column(Integer, nullable=True)

    # Acumulado ao longo do jogo: sobe porque se ganha tanto quanto faz ganhar.
    cs_min = Column(Float, nullable=True)
    opp_cs_min = Column(Float, nullable=True)
    gold_min = Column(Float, nullable=True)
    opp_gold_min = Column(Float, nullable=True)
    damage_min = Column(Float, nullable=True)
    opp_damage_min = Column(Float, nullable=True)
    vision_min = Column(Float, nullable=True)
    opp_vision_min = Column(Float, nullable=True)
    control_wards = Column(Integer, nullable=True)
    opp_control_wards = Column(Integer, nullable=True)
    deaths = Column(Integer, nullable=True)
    opp_deaths = Column(Integer, nullable=True)
    time_dead_pct = Column(Float, nullable=True)       # % da partida passada morto
    opp_time_dead_pct = Column(Float, nullable=True)
    enemy_jungle_cs = Column(Integer, nullable=True)   # selva do adversário comida
    opp_enemy_jungle_cs = Column(Integer, nullable=True)
    damage_share = Column(Float, nullable=True)        # % do dano da equipa
    opp_damage_share = Column(Float, nullable=True)
    kill_participation = Column(Float, nullable=True)
    opp_kill_participation = Column(Float, nullable=True)
    dragons = Column(Integer, nullable=True)
    opp_dragons = Column(Integer, nullable=True)
    turret_plates = Column(Integer, nullable=True)
    opp_turret_plates = Column(Integer, nullable=True)

    # Da timeline (ouro e XP ao minuto). Diferença dele para o jungler adversário.
    gd10 = Column(Integer, nullable=True)
    gd15 = Column(Integer, nullable=True)
    gd20 = Column(Integer, nullable=True)
    xd10 = Column(Integer, nullable=True)
    xd15 = Column(Integer, nullable=True)
    enemy_half_pct = Column(Float, nullable=True)      # % dos 15 min na metade inimiga
    has_timeline = Column(Boolean, default=False)

    challenges_json = Column(Text, nullable=True)
    opp_challenges_json = Column(Text, nullable=True)
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
    position = Column(Integer, default=0)           # a ordem em que ele as arrastou
    # Lista do Reminders da Apple que esta espelha. A ligação é por id, não por
    # nome: mudar o nome de um dos lados não desliga a sincronização.
    apple_id = Column(String, nullable=True, index=True)
    # O último nome que os dois lados tinham em comum. É o que diz de que lado
    # veio uma mudança de nome: quem já não o tem foi quem mudou.
    apple_name = Column(String, nullable=True)
    apple_icon = Column(String, nullable=True)      # o mesmo, para o ícone e a cor
    apple_color = Column(String, nullable=True)
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
    checked_at = Column(DateTime, nullable=True)    # quando foi dado como feito
    # Reminder da Apple que este item espelha, e a data da última alteração deste
    # lado — é ela que decide quem ganha quando os dois lados mudaram.
    apple_id = Column(String, nullable=True, index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ReminderTombstone(Base):
    """Reminder apagado no Cristopher, à espera de ser apagado na Apple.

    Sem isto o item voltava a nascer: "não existe deste lado" é exactamente o que
    também se parece com "acabou de ser criado do outro"."""
    __tablename__ = "reminder_tombstones"

    id = Column(Integer, primary_key=True, index=True)
    apple_id = Column(String, nullable=False, unique=True, index=True)
    deleted_at = Column(DateTime, server_default=func.now())


# ── Day Planner ──────────────────────────────────────────────────

class DayActivity(Base):
    """Atividade reutilizável do planeador de dia (gym, trabalho, LoL, refeições…).

    O planeador encaixa estas no dia a partir da hora de acordar, respeitando
    janela, hora fixa, prioridade e duração (fixa ou flexível min–máx)."""
    __tablename__ = "day_activities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    icon = Column(String, default="⏱️")
    color = Column(String, default="#3B82F6")
    duration_min = Column(Integer, default=60)          # minutos (mínimo se flex)
    duration_max = Column(Integer, nullable=True)       # minutos; se != None → duração flexível
    window = Column(String, default="any")              # any|morning|afternoon|evening|before_lunch|after_lunch
    fixed_time = Column(String, nullable=True)          # HH:MM — âncora opcional
    priority = Column(Integer, default=1)               # 0=baixa … 3=alta (encaixadas primeiro)
    splittable = Column(Boolean, default=False)         # pode ser dividida em vários blocos (ex: trabalho)
    chunk_max = Column(Integer, nullable=True)          # minutos máx por bloco quando splittable (default 120)
    enabled = Column(Boolean, default=True)             # incluir no plano de hoje
    position = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())


class DayPlanRecord(Base):
    """Plano gerado e guardado para uma data (1 por dia — o mais recente ganha)."""
    __tablename__ = "day_plans"

    id = Column(Integer, primary_key=True, index=True)
    plan_date = Column(Date, unique=True, index=True, nullable=False)
    wake_time = Column(String, nullable=False)
    day_end = Column(String, nullable=True)
    mode = Column(String, default="local")
    preferences = Column(Text, default="")
    advice = Column(Text, default="")
    blocks_json = Column(Text, default="[]")            # lista de blocos serializada
    unplaced_json = Column(Text, default="[]")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


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
    source = Column(String, default="manual")        # manual | auto (estimado do PC)
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
    color = Column(String, default="")
    project_path = Column(String, nullable=True, index=True)  # liga a nota a um projecto do VS Code
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
    price_updated_at = Column(DateTime, nullable=True)   # última cotação buscada
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
    external_id = Column(String, nullable=True, index=True)  # id da execução na API do broker


class InvestmentTransaction(Base):
    __tablename__ = "investment_transactions"

    id = Column(Integer, primary_key=True, index=True)
    time = Column(DateTime, nullable=False)
    type = Column(String, nullable=False)  # Depósito, Levantamento, Dividendo, Taxa, Juros
    currency = Column(String, default="EUR")
    amount = Column(Float, nullable=False)
    source = Column(String, default="trading212")  # trading212 / finst
    external_id = Column(String, nullable=True, index=True)  # referência do movimento na API


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
    executed_at = Column(DateTime, nullable=True)          # null = plano por executar
    executed_snapshot = Column(Text, nullable=True)        # JSON: [{ticker, name, asset_type, percentage, amount_eur}]
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
    mood = Column(Integer, nullable=False)             # day rating 0-10
    quality = Column(String, default="")               # bad | meh | good | great
    note = Column(Text, default="")
    tags = Column(String, default="")                  # legacy (feeling tags), unused
    created_at = Column(DateTime, server_default=func.now())


# ── Daily Journal (Diário Rápido) ────────────────────────────────

class DailyJournal(Base):
    __tablename__ = "daily_journals"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, unique=True, index=True)
    content = Column(Text, default="")                 # max ~3 sentences
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class DayQuestion(Base):
    """Uma pergunta que a app fez sobre um dia concreto, e o que ele respondeu.

    O diário tinha UMA entrada em 115 dias: a folha em branco não funciona. Um dia
    que fugiu ao padrão (uma noite de 4h, um dia de 120€) é precisamente o dia em
    que o "porquê" só existe na cabeça dele e se perde numa semana — por isso a
    app pergunta sobre esse dia, e a resposta vai para o diário desse dia."""
    __tablename__ = "day_questions"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    key = Column(String, nullable=False)               # que anomalia deu origem
    question = Column(Text, nullable=False)
    answer = Column(Text, default="")
    dismissed = Column(Boolean, default=False)         # "não interessa" — não volta
    created_at = Column(DateTime, server_default=func.now())
    answered_at = Column(DateTime, nullable=True)


# ── Budget Limits ────────────────────────────────────────────────

class BudgetLimit(Base):
    __tablename__ = "budget_limits"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, nullable=False, unique=True, index=True)
    monthly_limit = Column(Float, nullable=False)
    color = Column(String, default="#3B82F6")
    created_at = Column(DateTime, server_default=func.now())


class SalaryBucket(Base):
    """Grupo do plano do salário (ex: Despesas 50%, Pessoal 10%, Investir 20%).
    Cada grupo agrega categorias de gasto e define uma % do salário como alvo."""
    __tablename__ = "salary_buckets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    percentage = Column(Float, nullable=False, default=0)     # % do salário
    categories = Column(Text, default="")                    # CSV das categorias de gasto que agrega
    kind = Column(String, default="spend")                   # "spend" (menos é melhor) | "save" (mais é melhor)
    color = Column(String, default="#3B82F6")
    sort_order = Column(Integer, default=0)
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
    # Só para browsers: o domínio do separador activo (youtube.com). É a pista
    # mais fiável do que se está a fazer — o título muda a cada vídeo e em ecrã
    # inteiro nem existe.
    domain = Column(String, nullable=True, index=True)
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


class WakaProjectDay(Base):
    """Cached WakaTime coding time per day, broken down by kind (project / language /
    editor / os). Built up daily from the WakaTime API so we keep unlimited history
    beyond the free 14-day window."""
    __tablename__ = "waka_project_days"

    id = Column(Integer, primary_key=True, index=True)
    day = Column(Date, nullable=False, index=True)
    kind = Column(String, nullable=False, default="project", index=True)
    project = Column(String, nullable=False, default="")  # the name within `kind`
    seconds = Column(Integer, nullable=False, default=0)


class WakaHourDay(Base):
    """Segundos de código por hora-do-dia (0-23), por dia. Construído a partir do
    endpoint /durations do WakaTime, para o gráfico de 'a que horas programo mais'."""
    __tablename__ = "waka_hour_days"

    id = Column(Integer, primary_key=True, index=True)
    day = Column(Date, nullable=False, index=True)
    hour = Column(Integer, nullable=False)  # 0-23 (hora local)
    seconds = Column(Integer, nullable=False, default=0)


class WakaDayMetrics(Base):
    """Cached WakaTime per-day totals + AI-coding metrics (from grand_total)."""
    __tablename__ = "waka_day_metrics"

    id = Column(Integer, primary_key=True, index=True)
    day = Column(Date, nullable=False, unique=True, index=True)
    total_seconds = Column(Integer, nullable=False, default=0)
    ai_seconds = Column(Integer, nullable=False, default=0)  # time in the "AI Coding" category
    ai_additions = Column(Integer, nullable=False, default=0)
    ai_deletions = Column(Integer, nullable=False, default=0)
    human_additions = Column(Integer, nullable=False, default=0)
    human_deletions = Column(Integer, nullable=False, default=0)
    ai_agent_line_changes = Column(Integer, nullable=False, default=0)
    ai_input_tokens = Column(Integer, nullable=False, default=0)
    ai_output_tokens = Column(Integer, nullable=False, default=0)
    ai_sessions = Column(Integer, nullable=False, default=0)
    ai_prompt_events = Column(Integer, nullable=False, default=0)
    ai_cost = Column(Float, nullable=False, default=0.0)


class WakaProjectDayMetrics(Base):
    """Cached WakaTime per-day, per-project totals + AI-coding metrics.

    Mirrors WakaDayMetrics but split by project, so the detailed Projects section
    can show time / AI changes / prompts / sessions / tokens / spend per project."""
    __tablename__ = "waka_project_day_metrics"

    id = Column(Integer, primary_key=True, index=True)
    day = Column(Date, nullable=False, index=True)
    project = Column(String, nullable=False, default="", index=True)
    seconds = Column(Integer, nullable=False, default=0)
    ai_additions = Column(Integer, nullable=False, default=0)
    ai_deletions = Column(Integer, nullable=False, default=0)
    human_additions = Column(Integer, nullable=False, default=0)
    human_deletions = Column(Integer, nullable=False, default=0)
    ai_lines = Column(Integer, nullable=False, default=0)  # ai_agent_line_changes total
    ai_input_tokens = Column(Integer, nullable=False, default=0)
    ai_output_tokens = Column(Integer, nullable=False, default=0)
    ai_prompt_events = Column(Integer, nullable=False, default=0)
    ai_prompt_length_sum = Column(Integer, nullable=False, default=0)
    ai_sessions = Column(Integer, nullable=False, default=0)
    ai_cost = Column(Float, nullable=False, default=0.0)


class CodeProjectFavorite(Base):
    """A project_path the user pinned — shows first in the 'all projects' list."""
    __tablename__ = "code_project_favorites"

    id = Column(Integer, primary_key=True, index=True)
    project_path = Column(String, nullable=False, unique=True, index=True)
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


class BrowserTitleRule(Base):
    """Regra aprendida (IA ou eu) que mapeia um pedaço de título de janela a uma
    categoria — é o que permite saber que 183h de browser não são 183h de trabalho."""
    __tablename__ = "browser_title_rules"

    id = Column(Integer, primary_key=True, index=True)
    pattern = Column(String, nullable=False, unique=True)
    category = Column(String, nullable=False)
    source = Column(String, default="ai")
    created_at = Column(DateTime, server_default=func.now())


class JobRun(Base):
    """Registo de cada execução dos trabalhos automáticos — é o que permite dizer
    'os sinais estão parados há 56 dias' em vez de ninguém dar por nada."""
    __tablename__ = "job_runs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    ok = Column(Boolean, default=True)
    detail = Column(Text, default="")
    duration_ms = Column(Integer, default=0)


class ScreenTimeGoal(Base):
    """Meta de ecrã por categoria — um alvo de horas **por dia**. Dia, semana e
    mês são só formas de ver o progresso (a semana multiplica o alvo pelos dias
    que contam nela), não três metas separadas: 5h/dia é sempre a mesma meta,
    vista a três zoons diferentes — ver `screen_time.goals_status`.

    Substitui os antigos tectos semanais (`screen_time_limits`) e metas diárias
    (`screen_time_daily_goals`), que eram a mesma ideia espalhada em duas
    tabelas — a migração em main.py junta as duas aqui.

    `days` filtra que dias contam (`daily`, `weekdays`, ou uma lista tipo
    "0,2,4", Seg=0) — sábado de código não devia contar para quem só quer medir
    dias úteis. `habit_id`, a existir, marca-se sozinho ao chegar ao alvo do
    dia (só o "dia" tem uma hora certa em que isso pode acontecer)."""
    __tablename__ = "screen_time_goals"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, nullable=False, unique=True)
    target_hours = Column(Float, nullable=False)  # por dia
    days = Column(String, default="daily")
    habit_id = Column(Integer, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class ScreenTimeDailyApp(Base):
    """Snapshot diário do uso por app (lido do knowledgeC). A Apple só guarda
    ~4 semanas no knowledgeC; isto persiste agregados por dia para histórico de
    longo prazo e estatísticas. Valores em modo 'apple' (gap-merge + ceil)."""
    __tablename__ = "screen_time_daily_apps"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    device_id = Column(String, nullable=False, default="__local__")
    bundle_id = Column(String, nullable=False)
    category = Column(String, default="")
    seconds = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("date", "device_id", "bundle_id", name="uq_stda_day_dev_bundle"),
    )


# ── Deals (caça-deals automático) ────────────────────────────────

class DealWatch(Base):
    """Uma 'wish' que o utilizador quer monitorizar (ex: 'Yamaha MT-07').
    De hora a hora as fontes são pesquisadas e a IA avalia/filtra os resultados."""
    __tablename__ = "deal_watches"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)              # rótulo humano: "iPhone 17"
    query = Column(String, nullable=False)              # termos de pesquisa
    category = Column(String, default="")               # phone, motorcycle, accessory, other (ajuda a IA)
    condition = Column(String, default="any")           # any | new | used
    sources = Column(String, default="all")             # all | vinted | csv ("vinted,olx")
    max_price = Column(Float, nullable=True)            # filtro duro (None = sem limite)
    min_rating = Column(Integer, default=60)            # só notifica acima disto
    ai_context = Column(Text, default="")               # "é o normal, NÃO o 17e nem plus"
    exclude_keywords = Column(Text, default="")         # csv de palavras a excluir (pré-filtro barato)
    # Critérios em campos, não em texto solto: ano, km, potência, cor, palavras
    # obrigatórias. Antes só havia o `ai_context` e bastava a IA ler mal para o
    # anúncio errado passar. Ver `deal_criteria`.
    criteria_json = Column(Text, default="")            # JSON: {"year_min":…, "km_max":…}
    kind = Column(String, default="specific")           # specific = um produto | generic = "o que houver de bom em X"
    notify = Column(Boolean, default=True)              # avisa quando aparece um achado bom
    active = Column(Boolean, default=True)
    last_checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class DealResult(Base):
    """Um anúncio encontrado para um DealWatch. Dedupe por (source, external_id)."""
    __tablename__ = "deal_results"

    id = Column(Integer, primary_key=True, index=True)
    watch_id = Column(Integer, nullable=False, index=True)
    source = Column(String, nullable=False)             # vinted | olx
    external_id = Column(String, nullable=False)        # id do anúncio na fonte
    title = Column(String, nullable=False, default="")
    description = Column(Text, default="")
    price = Column(Float, nullable=True)
    currency = Column(String, default="EUR")
    condition = Column(String, default="")              # texto da fonte (Novo/Usado/Muito bom…)
    url = Column(String, default="")
    image_url = Column(String, default="")
    location = Column(String, default="")
    seller = Column(String, default="")
    ai_rating = Column(Integer, nullable=True)          # 0-100 (None = ainda não avaliado)
    ai_match = Column(Boolean, default=True)            # é mesmo o item pedido?
    ai_reason = Column(Text, default="")                # justificação curta da IA
    status = Column(String, default="new")              # new | seen | saved | dismissed | gone
    gone_at = Column(DateTime, nullable=True)           # deixou de aparecer nas fontes
    reappeared_at = Column(DateTime, nullable=True)     # voltou a aparecer depois de sumir
    # Lido do texto do anúncio uma vez (`deal_attrs`), para os filtros e o preço
    # justo não terem de o reler a cada pedido. None = o anúncio não diz.
    attr_year = Column(Integer, nullable=True)
    attr_km = Column(Integer, nullable=True)
    attr_power_kw = Column(Integer, nullable=True)
    attr_color = Column(String, nullable=True)
    attr_color_src = Column(String, nullable=True)   # "texto" | "foto" (ver deal_vision)
    previous_price = Column(Float, nullable=True)       # preço anterior, quando o anúncio muda
    price_changed_at = Column(DateTime, nullable=True)
    first_seen_at = Column(DateTime, server_default=func.now())
    last_seen_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source", "external_id", "watch_id", name="uq_deal_src_ext_watch"),
    )


# ── Stories (pesquisas explicadas pela IA) ───────────────────────

class Story(Base):
    """Um tema que o utilizador mandou explicar (ex: 'o que aconteceu em Chernobyl').
    Cada nível de profundidade (simples/médio/grande) é gerado on-demand e guardado
    como um StoryVersion, para alternar sem repetir a chamada à IA."""
    __tablename__ = "stories"

    id = Column(Integer, primary_key=True, index=True)
    query = Column(String, nullable=False)              # o que o utilizador escreveu
    title = Column(String, nullable=False, default="")  # título limpo gerado pela IA
    last_level = Column(String, nullable=False, default="medium")  # nível visto por último
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class StoryVersion(Base):
    """A explicação de uma Story a um nível específico. Markdown + fontes web (JSON)."""
    __tablename__ = "story_versions"

    id = Column(Integer, primary_key=True, index=True)
    story_id = Column(Integer, nullable=False, index=True)
    level = Column(String, nullable=False)              # simple | medium | long
    body = Column(Text, nullable=False, default="")     # explicação em markdown
    sources = Column(Text, nullable=False, default="[]")  # JSON: [{"title","url"}]
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("story_id", "level", name="uq_story_version_level"),
    )


class StorySuggestion(Base):
    """Tema recomendado pela IA para explorar a seguir. Se `story_id` estiver preenchido é
    uma sugestão relacionada com essa história ('continuar a explorar'); a NULL é uma
    sugestão geral, com base em tudo o que o utilizador já pesquisou. `dismissed` fica True
    quando é descartada ou já foi transformada em história — serve de blacklist."""
    __tablename__ = "story_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    story_id = Column(Integer, nullable=True, index=True)  # NULL = sugestão geral
    query = Column(String, nullable=False)                 # tema a pesquisar
    title = Column(String, nullable=False, default="")
    reason = Column(String, nullable=False, default="")    # porquê recomendado
    category = Column(String, nullable=False, default="")  # História, Ciência, …
    dismissed = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


# ── Spotify Curator ──────────────────────────────────────────────

class SpotifyPlaylist(Base):
    """Playlist importada manualmente (colar ou CSV). A 'vibe' descreve o espírito que
    a IA usa para curar (ex: 'triste/melancólica', 'rock + hype'). A última análise fica
    em cache (JSON) para reabrir sem repetir a chamada à IA."""
    __tablename__ = "spotify_playlists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    vibe = Column(Text, nullable=False, default="")
    is_favorites = Column(Boolean, default=False)             # a "playlist" das músicas gostadas
    last_analysis = Column(Text, nullable=False, default="")  # JSON do último resultado da IA
    analyzed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class SpotifyTrack(Base):
    """Uma faixa dentro de uma playlist importada."""
    __tablename__ = "spotify_tracks"

    id = Column(Integer, primary_key=True, index=True)
    playlist_id = Column(Integer, nullable=False, index=True)
    position = Column(Integer, default=0)
    title = Column(String, nullable=False)
    artist = Column(String, nullable=False, default="")
    album = Column(String, nullable=False, default="")
    spotify_url = Column(String, nullable=False, default="")


class SpotifyOverview(Base):
    """Cache (singleton, id=1) da análise transversal a TODAS as playlists: duplicados,
    agrupamento por género/mood e recolocações. Recalculada a pedido pelo utilizador."""
    __tablename__ = "spotify_overview"

    id = Column(Integer, primary_key=True, index=True)
    last_analysis = Column(Text, nullable=False, default="")  # JSON do último resultado
    analyzed_at = Column(DateTime, nullable=True)


class SpotifySuggestion(Base):
    """Música nova recomendada para uma playlist OU para um grupo de género da Visão Geral.
    `accepted` fica True quando o utilizador a 'adiciona' — aí entra na lista a copiar.
    Se `group_name` estiver preenchido é uma sugestão de grupo (playlist_id fica a 0)."""
    __tablename__ = "spotify_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    playlist_id = Column(Integer, nullable=False, index=True)
    group_name = Column(String, nullable=True, index=True)   # grupo de género (Visão Geral) ou NULL
    title = Column(String, nullable=False)
    artist = Column(String, nullable=False, default="")
    reason = Column(String, nullable=False, default="")
    accepted = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


class PortfolioSnapshot(Base):
    """Valor da carteira num dia. Os extractos só dão fotografias soltas de mês a
    mês; isto guarda a série, que é o que permite ver a carteira a andar."""
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, unique=True, index=True)
    total_value_eur = Column(Float, nullable=False)
    total_invested_eur = Column(Float, nullable=False)
    return_eur = Column(Float, nullable=False)
    positions = Column(Integer, default=0)
    priced_at = Column(DateTime, nullable=True)
    source = Column(String, default="live")
    created_at = Column(DateTime, server_default=func.now())


class SpotifyPlay(Base):
    """O que tocou no Spotify e durante quanto tempo.

    A app só tinha fotografias das playlists — nada do que era realmente ouvido.
    O tracker pergunta ao Spotify (AppleScript) mesmo com ele em segundo plano,
    por isso apanha a música que toca enquanto se programa ou joga."""
    __tablename__ = "spotify_plays"

    id = Column(Integer, primary_key=True, index=True)
    track = Column(String, nullable=False)
    artist = Column(String, default="")
    album = Column(String, default="")
    spotify_id = Column(String, nullable=True, index=True)
    date = Column(Date, nullable=False, index=True)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    seconds = Column(Integer, default=0)
    track_seconds = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class PowerEvent(Base):
    """Quando o Mac adormeceu e quando acordou.

    O sono da app era metade adivinhado (metade dos registos manuais foram
    escritos antes da noite acontecer) e a outra metade vinha de uma leitura
    aproximada da Apple. Isto guarda factos: o momento exacto em que a máquina
    parou e em que voltou, que é o sinal mais próximo de "fui dormir"."""
    __tablename__ = "power_events"

    id = Column(Integer, primary_key=True, index=True)
    slept_at = Column(DateTime, nullable=False, index=True)
    woke_at = Column(DateTime, nullable=False)
    minutes = Column(Integer, nullable=False)
    source = Column(String, default="tracker")     # tracker | pmset
    detail = Column(String, default="")            # razão do wake, quando se sabe
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("slept_at", "source", name="uq_power_sleep"),)


class PushDevice(Base):
    """Um telemóvel/tablet inscrito para receber avisos da app."""
    __tablename__ = "push_devices"

    id = Column(Integer, primary_key=True, index=True)
    endpoint = Column(String, nullable=False, unique=True)
    subscription = Column(Text, nullable=False)      # JSON com as chaves do browser
    label = Column(String, default="")               # "iPhone", "iPad"…
    active = Column(Boolean, default=True)
    last_sent_at = Column(DateTime, nullable=True)
    last_error = Column(String, default="")
    created_at = Column(DateTime, server_default=func.now())


class BankConnection(Base):
    """Autorização dada ao banco (uma por instituição).

    A regulação obriga a renovar o acesso de tempos a tempos; quando isso
    acontece a app avisa em vez de deixar as despesas silenciosamente paradas."""
    __tablename__ = "bank_connections"

    id = Column(Integer, primary_key=True, index=True)
    institution_id = Column(String, nullable=False)
    institution_name = Column(String, default="")
    requisition_id = Column(String, nullable=False, unique=True)
    agreement_id = Column(String, default="")
    status = Column(String, default="pendente")     # pendente | ligado | expirado | erro
    link = Column(Text, default="")                  # url de autorização
    expires_at = Column(DateTime, nullable=True)
    last_sync_at = Column(DateTime, nullable=True)
    last_error = Column(String, default="")
    created_at = Column(DateTime, server_default=func.now())


class MerchantRule(Base):
    """Loja → categoria, aprendida.

    As regras fixas não chegam: cada viagem traz lojas novas que não estão em
    lista nenhuma. Isto guarda o que já foi decidido — por ele (a corrigir uma
    despesa) ou pela IA — para a próxima vez ser imediato e de graça."""
    __tablename__ = "merchant_rules"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, nullable=False, unique=True, index=True)   # nome normalizado
    label = Column(String, default="")                              # como aparece no extracto
    category = Column(String, nullable=False)
    source = Column(String, default="ia")                           # ia | manual
    hits = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, nullable=True)


class BankIgnoredTx(Base):
    """Movimentos do banco que ele apagou de propósito.

    Sem isto, apagar uma despesa vinda do banco não servia de nada: a
    sincronização do dia seguinte via que faltava e voltava a criá-la."""
    __tablename__ = "bank_ignored_tx"

    id = Column(Integer, primary_key=True, index=True)
    tx_id = Column(String, nullable=False, unique=True, index=True)
    description = Column(String, default="")
    created_at = Column(DateTime, server_default=func.now())


class SavedQuestion(Base):
    """Uma pergunta do Perguntar fixada no painel.

    Guarda-se o SQL que a IA escreveu, não a pergunta: assim o número volta a ser
    calculado de graça e num instante sempre que se abre a app, em vez de gastar
    uma chamada à IA. A pergunta fica para se saber o que aquilo quer dizer."""
    __tablename__ = "saved_questions"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(String, nullable=False)
    title = Column(String, nullable=False, default="")
    sql = Column(Text, nullable=False)
    chart = Column(String, default="table")      # table | bar | line
    position = Column(Integer, default=0)
    last_value = Column(String, default="")       # último resultado, para comparar
    last_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class BankAccount(Base):
    """Conta trazida por uma ligação."""
    __tablename__ = "bank_accounts"

    id = Column(Integer, primary_key=True, index=True)
    connection_id = Column(Integer, nullable=False, index=True)
    account_id = Column(String, nullable=False, unique=True)
    name = Column(String, default="")
    iban = Column(String, default="")
    currency = Column(String, default="EUR")
    balance = Column(Float, nullable=True)
    active = Column(Boolean, default=True)
    last_transaction_date = Column(Date, nullable=True)
    last_sync_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# ── Relógio Garmin ───────────────────────────────────────────────

class GarminDay(Base):
    """O que o relógio mediu num dia.

    Colunas com nome em vez de um JSON só: o Perguntar escreve SQL sobre estas
    tabelas, e uma coluna chamada `sleep_score` responde a perguntas que um blob
    não responde. O detalhe ao minuto vive em `GarminSeries`.

    Campos que este relógio não calcula ficam a NULL e a app esconde-os: sem
    barómetro não há andares nem elevação, e o estado de HRV só aparece depois
    de ~19 noites."""
    __tablename__ = "garmin_days"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, unique=True, index=True)

    # Sono
    sleep_start = Column(DateTime, nullable=True)      # hora local a que adormeceu
    sleep_end = Column(DateTime, nullable=True)
    sleep_hours = Column(Float, nullable=True)
    deep_min = Column(Integer, nullable=True)
    light_min = Column(Integer, nullable=True)
    rem_min = Column(Integer, nullable=True)
    awake_min = Column(Integer, nullable=True)
    nap_min = Column(Integer, nullable=True)
    awake_count = Column(Integer, nullable=True)
    sleep_score = Column(Integer, nullable=True)        # 0-100
    sleep_qualifier = Column(String, nullable=True)     # POOR | FAIR | GOOD | EXCELLENT
    sleep_need_min = Column(Integer, nullable=True)     # quanto o relógio diz que precisa
    sleep_feedback = Column(String, nullable=True)
    avg_sleep_stress = Column(Float, nullable=True)
    spo2_avg = Column(Float, nullable=True)
    spo2_min = Column(Float, nullable=True)
    resp_avg = Column(Float, nullable=True)
    skin_temp_dev_c = Column(Float, nullable=True)      # só se o aparelho medir

    # Recuperação
    resting_hr = Column(Integer, nullable=True)
    hrv_last_night = Column(Integer, nullable=True)     # ms
    hrv_5min_high = Column(Integer, nullable=True)
    hrv_weekly_avg = Column(Integer, nullable=True)
    hrv_status = Column(String, nullable=True)          # BALANCED | UNBALANCED | LOW | POOR
    hrv_baseline_low = Column(Integer, nullable=True)
    hrv_baseline_high = Column(Integer, nullable=True)
    hrv_feedback = Column(String, nullable=True)

    # Body Battery
    bb_start = Column(Integer, nullable=True)           # com quanto acordou
    bb_end = Column(Integer, nullable=True)
    bb_min = Column(Integer, nullable=True)
    bb_max = Column(Integer, nullable=True)
    bb_charged = Column(Integer, nullable=True)
    bb_drained = Column(Integer, nullable=True)

    # Stress
    stress_avg = Column(Integer, nullable=True)
    stress_max = Column(Integer, nullable=True)
    stress_rest_min = Column(Integer, nullable=True)
    stress_low_min = Column(Integer, nullable=True)
    stress_medium_min = Column(Integer, nullable=True)
    stress_high_min = Column(Integer, nullable=True)

    # Actividade do dia
    steps = Column(Integer, nullable=True)
    step_goal = Column(Integer, nullable=True)
    distance_m = Column(Float, nullable=True)
    calories = Column(Integer, nullable=True)
    active_calories = Column(Integer, nullable=True)
    intensity_moderate_min = Column(Integer, nullable=True)
    intensity_vigorous_min = Column(Integer, nullable=True)
    hr_min = Column(Integer, nullable=True)
    hr_max = Column(Integer, nullable=True)

    # Treino
    training_readiness = Column(Integer, nullable=True)   # 0-100
    readiness_level = Column(String, nullable=True)       # POOR … PRIME
    readiness_feedback = Column(String, nullable=True)
    training_status = Column(String, nullable=True)       # PRODUCTIVE | MAINTAINING | …
    vo2max = Column(Float, nullable=True)
    acute_load = Column(Float, nullable=True)
    recovery_min = Column(Integer, nullable=True)

    # Quanto é que cada coisa pesou na prontidão daquela manhã. Sem isto o número
    # afirma-se mas não se explica.
    readiness_sleep_pct = Column(Integer, nullable=True)
    readiness_hrv_pct = Column(Integer, nullable=True)
    readiness_recovery_pct = Column(Integer, nullable=True)
    readiness_load_pct = Column(Integer, nullable=True)
    readiness_stress_pct = Column(Integer, nullable=True)

    # Idade de fitness e o que falta para a baixar (o alvo da Garmin é 75 min
    # vigorosos por semana em 3 dias distintos).
    fitness_age = Column(Float, nullable=True)
    fitness_age_achievable = Column(Float, nullable=True)
    vigorous_min_avg = Column(Float, nullable=True)
    vigorous_days_avg = Column(Float, nullable=True)
    bmi = Column(Float, nullable=True)
    weight_kg = Column(Float, nullable=True)

    synced_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())


class GarminActivity(Base):
    """Um treino registado no relógio, ou um movimento que ele detectou sozinho.

    Os segundos (Move IQ) não são treinos gravados: o relógio percebe que se
    andou 25 minutos e regista isso na app da Garmin sem ninguém carregar em
    nada. Vêm de outro endereço, não têm distância nem frequência cardíaca, e
    ficam marcados com `auto` para a app não os apresentar como se fossem
    treinos a sério."""
    __tablename__ = "garmin_activities"

    id = Column(Integer, primary_key=True, index=True)
    activity_id = Column(String, nullable=False, unique=True, index=True)
    date = Column(Date, nullable=False, index=True)
    start_time = Column(DateTime, nullable=True)
    auto = Column(Boolean, default=False)             # detectado pelo relógio (Move IQ)
    # Já passou pelo hábito do gym. Sem isto, desmarcar o gym à mão não pegava:
    # a sincronização seguinte voltava a marcá-lo.
    habit_checked = Column(Boolean, default=False)
    type = Column(String, default="")                 # running, strength_training, walking…
    name = Column(String, default="")
    duration_s = Column(Float, nullable=True)
    distance_m = Column(Float, nullable=True)
    calories = Column(Integer, nullable=True)
    avg_hr = Column(Integer, nullable=True)
    max_hr = Column(Integer, nullable=True)
    avg_speed = Column(Float, nullable=True)          # m/s
    avg_cadence = Column(Float, nullable=True)
    avg_power = Column(Float, nullable=True)          # potência de corrida (pulso)
    aerobic_te = Column(Float, nullable=True)
    anaerobic_te = Column(Float, nullable=True)
    location = Column(String, default="")
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class GarminSnapshot(Base):
    """Health Snapshot: dois minutos parado a medir tudo de uma vez.

    Vale por si porque é a única leitura de HRV que não espera pelas 19 noites
    de linha de base — e porque é ele a decidir quando a faz, o que dá para
    comparar o antes e o depois de uma coisa concreta."""
    __tablename__ = "garmin_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String, nullable=False, unique=True, index=True)
    date = Column(Date, nullable=False, index=True)
    start_time = Column(DateTime, nullable=True)
    duration_s = Column(Integer, nullable=True)
    name = Column(String, default="")               # "Health Snapshot - Evening"

    hr_avg = Column(Float, nullable=True)
    hr_min = Column(Float, nullable=True)
    hr_max = Column(Float, nullable=True)
    hrv_rmssd = Column(Float, nullable=True)        # o HRV do costume, em ms
    hrv_sdrr = Column(Float, nullable=True)
    spo2_avg = Column(Float, nullable=True)
    spo2_min = Column(Float, nullable=True)
    resp_avg = Column(Float, nullable=True)
    resp_max = Column(Float, nullable=True)
    stress_avg = Column(Float, nullable=True)
    stress_max = Column(Float, nullable=True)

    device = Column(String, default="")
    created_at = Column(DateTime, server_default=func.now())


class GarminSeries(Base):
    """Stress, body battery e frequência cardíaca ao longo do dia.

    Guardar isto agora custa nada e é o que permite, mais tarde, pôr uma partida
    de LoL ou uma hora de código ao lado do que o corpo estava a fazer. Fica fora
    do `GarminDay` para o Perguntar não tropeçar em blobs."""
    __tablename__ = "garmin_series"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, unique=True, index=True)
    stress_json = Column(Text, default="")            # [[ts_ms, nivel], …]
    body_battery_json = Column(Text, default="")      # [[ts_ms, nivel], …]
    hr_json = Column(Text, default="")                # [[ts_ms, bpm], …]
    steps_json = Column(Text, default="")             # [[ts_ms, passos], …] de 15 em 15 min
    # A linha do dia: dormir, sestas e movimento, cada um com início e fim.
    # [{"kind": "sono|sesta|movimento", "start": ts_ms, "end": ts_ms, …}, …]
    events_json = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())


# ── Alimentação ──────────────────────────────────────────────────

class MealSlot(Base):
    """Uma refeição com hora marcada (pequeno-almoço, almoço, jantar).

    Os lanches não vivem aqui: apontam-se quando acontecem e não contam para o
    score — o que se está a medir é comer as principais a horas, e senão bastava
    petiscar para o dia parecer bom."""
    __tablename__ = "meal_slots"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False)   # breakfast | lunch | dinner | …
    name = Column(String, nullable=False)
    start_time = Column(String, nullable=False)         # "08:00"
    end_time = Column(String, nullable=False)           # "10:00"
    notify = Column(Boolean, default=True)
    active = Column(Boolean, default=True)
    position = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())


class MealLog(Base):
    """Uma refeição que aconteceu. `slot_key` a nulo é um lanche."""
    __tablename__ = "meal_logs"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    slot_key = Column(String, nullable=True, index=True)
    eaten_at = Column(DateTime, nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())


class MealNotice(Base):
    """O que já foi avisado, para o agendador não repetir o mesmo aviso de cinco
    em cinco minutos. Fica na base e não em memória: um reinício do backend não
    pode transformar-se em spam."""
    __tablename__ = "meal_notices"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    slot_key = Column(String, nullable=False)
    kind = Column(String, nullable=False)               # abriu | a_fechar
    sent_at = Column(DateTime, server_default=func.now())


class Supplement(Base):
    """Um suplemento que ele toma (proteína, creatina, …).

    Fica ao lado das refeições e não nos hábitos porque é alimentação, e porque
    a pergunta é a mesma: tomaste hoje ou não. A lista é dele — acrescenta e
    apaga o que quiser."""
    __tablename__ = "supplements"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    dose = Column(String, default="")                  # "30 g", "5 g", "1 cápsula"
    time_hint = Column(String, nullable=True)          # "09:00" — só para o aviso
    notify = Column(Boolean, default=False)
    active = Column(Boolean, default=True)
    position = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())


class SupplementLog(Base):
    """Um suplemento tomado num dia. Sem linha = não tomado."""
    __tablename__ = "supplement_logs"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    supplement_id = Column(Integer, nullable=False, index=True)
    taken_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class NightOut(Base):
    """Uma noite em que ele saiu, e se bebeu. Sem linha = ficou em casa.

    `date` é o dia em que a noite começou (sábado à noite é sábado), não o dia
    em que acordou: é assim que se diz "saí no sábado". A noite de sono que ela
    afecta é a do dia seguinte (`GarminDay.date` = date + 1)."""
    __tablename__ = "night_outs"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, unique=True, index=True)
    drank = Column(Boolean, default=False)
    drink_level = Column(Integer, nullable=True)     # 1 pouco, 2 médio, 3 muito
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
