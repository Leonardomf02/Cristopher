export interface Event {
  id: number | string;
  title: string;
  description: string;
  date: string;
  start_time: string | null;
  end_time: string | null;
  event_type: 'fixed' | 'flexible';
  category: string;
  color: string;
  completed: boolean;
  recurrence: string;
  recurrence_end: string | null;
  is_recurring_instance?: boolean;
  parent_id?: number | null;
  is_reminder?: boolean;
}

export interface EventCreate {
  title: string;
  description?: string;
  date: string;
  start_time?: string | null;
  end_time?: string | null;
  event_type?: 'fixed' | 'flexible';
  category?: string;
  color?: string;
  recurrence?: string;
  recurrence_end?: string | null;
}

export interface Expense {
  id: number;
  description: string;
  amount: number;
  category: string;
  date: string;
  receipt_image: string | null;
  trip_id: number | null;
  notes: string;
  original_amount: number | null;
  original_currency: string | null;
  merchant_city: string | null;
  merchant_country: string | null;
}

export interface ExpenseCreate {
  description: string;
  amount: number;
  category?: string;
  date: string;
  trip_id?: number | null;
  notes?: string;
  original_amount?: number | null;
  original_currency?: string | null;
  merchant_city?: string | null;
  merchant_country?: string | null;
}

export interface ExpenseSummary {
  category: string;
  total: number;
  count: number;
}

export interface LolGame {
  id: number;
  date: string;
  won: boolean;
  champion_played: string | null;
  champion_against: string | null;
  role: string | null;
  my_fault: boolean | null;
  notes: string;
  match_id: string | null;
  kills: number | null;
  deaths: number | null;
  assists: number | null;
  game_duration: number | null;
}

export interface LolGameCreate {
  date: string;
  won: boolean;
  champion_played?: string | null;
  champion_against?: string | null;
  role?: string | null;
  my_fault?: boolean | null;
  notes?: string;
  match_id?: string | null;
  kills?: number | null;
  deaths?: number | null;
  assists?: number | null;
  game_duration?: number | null;
}

export interface OpggConfig {
  game_name: string;
  tag_line: string;
  region: string;
}

export interface SyncResult {
  imported: number;
  skipped: number;
  total_fetched: number;
}

export interface LolStats {
  total: number;
  wins: number;
  losses: number;
  winrate: number;
  my_fault_losses: number;
  champion_stats: Record<string, { wins: number; losses: number; games: number }>;
  month_games: number;
  month_wins: number;
  month_losses: number;
}

export interface LolSeason {
  id: number;
  label: string;
  start_date: string;
  end_date: string | null;
  active: boolean;
  peak_tier: string | null;
  peak_rank: string | null;
  peak_lp: number | null;
  final_tier: string | null;
  final_rank: string | null;
  final_lp: number | null;
  total_games: number;
  total_wins: number;
  total_losses: number;
}

export interface RankInfo {
  ranked: boolean;
  tier?: string;
  rank?: string;
  lp?: number;
  wins?: number;
  losses?: number;
  hot_streak?: boolean;
  winrate?: number;
}

export interface SummonerInfo {
  summoner_level: number;
  profile_icon_id: number;
}

export interface RankPosition {
  tier: string;
  position: number | null;
  total_master_plus: number;
  total_master: number;
  total_gm: number;
  total_challenger: number;
  approximate?: boolean;
}

export interface LiveGame {
  in_game: boolean;
  game_mode?: string;
  champion?: number;
  game_length_seconds?: number;
}

export interface LivePlayerRank {
  tier: string;
  rank: string;
  lp: number;
  wins: number;
  losses: number;
  winrate: number;
  hot_streak?: boolean;
}

export interface LiveChampionStats {
  games: number;
  wins: number;
  losses: number;
  winrate: number;
  avg_kills: number;
  avg_deaths: number;
  avg_assists: number;
  avg_kda: number;
  avg_cs_per_min: number;
}

export interface LivePlayerTag {
  text: string;
  color: string;
}

export interface LiveRecentGames {
  total: number;
  results: boolean[];
}

export interface LivePlayerAvgStats {
  avg_kda: number;
  gold_per_min: number;
  damage_per_min: number;
  vision_per_min: number;
}

export interface LivePlayer {
  summoner_name: string;
  puuid: string;
  champion_id: number;
  champion_name: string;
  team_id: number;
  is_me: boolean;
  spell1: number;
  spell2: number;
  rank: LivePlayerRank | null;
  mastery_points: number;
  mastery_level: number;
  champion_stats: LiveChampionStats | null;
  role: string | null;
  main_roles: string[];
  role_games: number;
  recent_games: LiveRecentGames;
  tags: LivePlayerTag[];
  avg_stats: LivePlayerAvgStats | null;
  // Advanced features
  unique_champions?: string[];
  games_today?: number;
  champion_pool?: ChampionPoolDepth;
  mental_state?: MentalState;
  rank_trajectory?: RankTrajectory;
}

export interface LiveTeamStats {
  avg_winrate: number | null;
  avg_rank_str: string | null;
  avg_kda: number | null;
  avg_gold_per_min: number | null;
  avg_damage_per_min: number | null;
  avg_vision_per_min: number | null;
}

export interface LiveGameDetailed {
  in_game: boolean;
  game_mode?: string;
  game_type?: string;
  game_length_seconds?: number;
  game_start_time?: number;
  map_id?: number;
  queue_id?: number;
  my_team?: LivePlayer[];
  enemy_team?: LivePlayer[];
  bans_my_team?: string[];
  bans_enemy_team?: string[];
  my_team_stats?: LiveTeamStats;
  enemy_team_stats?: LiveTeamStats;
  matchup_analysis?: MatchupAnalysis;
  // Advanced features
  duos_my_team?: DuoDetection[];
  duos_enemy_team?: DuoDetection[];
  head_to_head?: HeadToHead[];
  my_comp_analysis?: TeamCompAnalysis;
  enemy_comp_analysis?: TeamCompAnalysis;
  win_probability?: WinProbability;
  strategic_advice?: StrategicTip[];
  personal_matchups?: Record<string, {
    vs_enemy_all?: { wins: number; losses: number; games: number; winrate: number };
    my_champ_vs_enemy?: { wins: number; losses: number; games: number; winrate: number };
    best_picks?: Array<{ champion: string; wins: number; losses: number; games: number; winrate: number }>;
  }>;
}

export interface MatchupPlayerScore {
  name: string;
  champion: string;
  score: number;
  scores: {
    rank: number;
    season: number;
    mastery: number;
    champion: number;
    role_fit: number;
    momentum: number;
  };
}

export interface MatchupEntry {
  role: string;
  my_player: MatchupPlayerScore;
  enemy_player: MatchupPlayerScore;
  diff: number;
  winner: 'my_team' | 'enemy_team' | 'even';
  winner_name: string;
  winner_champ: string;
  verdict: 'clear' | 'slight' | 'even';
  confidence: 'high' | 'medium' | 'low';
  advantages_mine: string[];
  advantages_enemy: string[];
}

export interface MatchupSummary {
  my_team_score: number;
  enemy_team_score: number;
  lanes_won: number;
  lanes_lost: number;
  lanes_even: number;
  advantage: 'my_team' | 'enemy_team' | 'even';
}

export interface MatchupAnalysis {
  matchups: MatchupEntry[];
  summary: MatchupSummary;
}

// ── Advanced Live Game Features ─────────────────────────────────

export interface DuoDetection {
  player1: string;
  player2: string;
  games_together: number;
  roles: (string | null)[];
}

export interface ChampionPoolDepth {
  unique_champions: number;
  champions_played: string[];
  category: 'otp' | 'specialist' | 'versatile';
  label: string;
  on_main: boolean;
}

export interface MentalState {
  state: 'tilted' | 'stressed' | 'neutral' | 'fresh';
  label: string;
  color: string;
  tilt_score: number;
  signals: string[];
  games_today: number;
  marathon_label?: string;
}

export interface RankTrajectory {
  trajectory: 'climbing' | 'declining' | 'smurf' | 'hot' | 'cold' | 'stable' | 'unknown';
  label: string;
  detail?: string;
  color?: string;
}

export interface HeadToHead {
  player_name: string;
  champion: string;
  games_with: number;
  games_against: number;
  total: number;
  current_relation: 'ally' | 'enemy';
}

export interface TeamCompAnalysis {
  ad_count: number;
  ap_count: number;
  mixed_count: number;
  ad_pct: number;
  ap_pct: number;
  archetypes: Record<string, number>;
  identities: string[];
  scaling: string;
  scaling_label: string;
  engage_count: number;
  has_engage: boolean;
  has_tank: boolean;
  split_push: number;
  poke: number;
  warnings: string[];
}

export interface WinProbability {
  probability: number;
  confidence: 'high' | 'medium' | 'low';
  factors: { name: string; value: number }[];
}

export interface StrategicTip {
  type: string;
  icon: string;
  text: string;
  priority: 'high' | 'medium' | 'low';
}

export interface ChampionMastery {
  champion_id: number;
  champion_name: string;
  champion_level: number;
  champion_points: number;
  last_play_time: number;
  chest_granted: boolean;
}

export interface MatchTimeline {
  match_id: string;
  gold_at_10: number | null;
  gold_at_15: number | null;
  gold_diff_at_15: number | null;
  cs_at_10: number | null;
  cs_at_15: number | null;
  first_blood: boolean;
  first_blood_victim: boolean;
}

// ── Champ Select ────────────────────────────────────────────────

export interface ChampSelectStatus {
  client_running: boolean;
  phase: string | null;
  in_champ_select: boolean;
}

export interface ChampSelectPick {
  champion_id: number;
  champion_name: string | null;
  position: string;
  pick_intent?: number;
  spell1?: number;
  spell2?: number;
  is_local_player?: boolean;
}

export interface TeamComp {
  ad_count: number;
  ap_count: number;
  mixed_count: number;
  has_engage: boolean;
  has_tank: boolean;
  cc_count: number;
  damage_balance: string;
  warnings: string[];
  champions: string[];
}

export interface ChampSuggestion {
  champion: string;
  champion_name: string;
  score: number;
  damage: string;
  winrate: number;
  games: number;
  meta_wr: number | null;
  reasons: string[];
}

export interface ChampSelectSession {
  active: boolean;
  message?: string;
  my_team?: ChampSelectPick[];
  their_team?: ChampSelectPick[];
  my_bans?: string[];
  their_bans?: string[];
  my_comp?: TeamComp;
  their_comp?: TeamComp;
  suggestions?: ChampSuggestion[];
  enemy_counters?: Record<string, { champion: string; wins: number; losses: number; games: number; winrate: number }[]>;
  phase?: string;
  timer_remaining?: number;
}

export interface Trip {
  id: number;
  destination: string;
  country: string | null;
  start_date: string;
  end_date: string;
  cover_image: string | null;
  notes: string;
  flights_cost: number;
  accommodation_cost: number;
  food_budget: number;
  other_costs: number;
  total_cost: number;
  rating_food: number | null;
  rating_places: number | null;
  rating_nightlife: number | null;
  rating_gajas: number | null;
  rating_overall: number | null;
}

export interface TripCreate {
  destination: string;
  country?: string | null;
  start_date: string;
  end_date: string;
  notes?: string;
  flights_cost?: number;
  accommodation_cost?: number;
  food_budget?: number;
  other_costs?: number;
}

export interface TripPlace {
  id: number;
  trip_id: number;
  name: string;
  description: string;
  is_free: boolean;
  estimated_cost: number;
  visited: boolean;
  suggested: boolean;
  address: string | null;
  url: string | null;
  rating: number | null;
  review: string;
}

export type TripRatingCategory = 'comida' | 'sitio' | 'noite' | 'encontro' | 'experiencia' | 'outro';

export const TRIP_RATING_CATEGORIES: { value: TripRatingCategory; label: string; emoji: string }[] = [
  { value: 'comida', label: 'Comida', emoji: '🍔' },
  { value: 'sitio', label: 'Sítio', emoji: '📍' },
  { value: 'noite', label: 'Noite', emoji: '🍻' },
  { value: 'encontro', label: 'Encontro', emoji: '💋' },
  { value: 'experiencia', label: 'Experiência', emoji: '✨' },
  { value: 'outro', label: 'Outro', emoji: '📦' },
];

export interface TripRating {
  id: number;
  trip_id: number;
  category: TripRatingCategory;
  name: string;
  rating: number;
  notes: string;
  date: string | null;
}

export interface TripRatingCreate {
  category: TripRatingCategory;
  name: string;
  rating: number;
  notes?: string;
  date?: string | null;
}

export interface TripPlaceCreate {
  trip_id: number;
  name: string;
  description?: string;
  is_free?: boolean;
  estimated_cost?: number;
  address?: string | null;
  url?: string | null;
}

// ── Lists ───────────────────────────────────────────────────────

export interface UserList {
  id: number;
  name: string;
  icon: string;
  color: string;
  item_count: number;
  checked_count: number;
}

export interface ListItem {
  id: number;
  list_id: number;
  text: string;
  checked: boolean;
  position: number;
  notes: string;
  due_date: string | null;
  due_time: string | null;
  priority: number;
}

// ── Sleep ────────────────────────────────────────────────────────

export interface SleepEntry {
  id: number;
  date: string;
  bedtime: string | null;
  wake_time: string | null;
  hours: number;
  quality: number | null;
  notes: string;
}

export interface SleepStats {
  avg_hours: number;
  avg_quality: number;
  total_entries: number;
  best_day: { date: string; hours: number } | null;
  worst_day: { date: string; hours: number } | null;
  entries: SleepEntry[];
}

// ── Day Types ───────────────────────────────────────────────────

export interface DayTypeEntry {
  id: number;
  date: string;
  type_name: string;
  color: string;
  note: string;
}

export const DAY_TYPE_PRESETS = [
  { name: 'Trabalho', color: '#3B82F6', icon: '💼' },
  { name: 'Aulas', color: '#F97316', icon: '🎓' },
  { name: 'Folga', color: '#10B981', icon: '🏖️' },
  { name: 'Dia Livre', color: '#22C55E', icon: '🌞' },
  { name: 'Viagem', color: '#F59E0B', icon: '✈️' },
  { name: 'Férias', color: '#8B5CF6', icon: '🌴' },
  { name: 'Doente', color: '#EF4444', icon: '🤒' },
  { name: 'Estudo', color: '#06B6D4', icon: '📚' },
  { name: 'Pessoal', color: '#EC4899', icon: '🏠' },
] as const;

// Day types that protect habit streaks (mirrors backend STREAK_PROTECTED_TYPES)
export const STREAK_PROTECTED_DAY_TYPES: readonly string[] = ['Férias', 'Aulas', 'Doente', 'Viagem'];

export const EXPENSE_CATEGORIES = [
  { value: 'food', label: 'Comida', emoji: '🍔' },
  { value: 'groceries', label: 'Supermercado', emoji: '🛒' },
  { value: 'transport', label: 'Transporte', emoji: '🚗' },
  { value: 'travel', label: 'Viagens', emoji: '✈️' },
  { value: 'entertainment', label: 'Entretenimento', emoji: '🎮' },
  { value: 'subscriptions', label: 'Subscrições', emoji: '📱' },
  { value: 'shopping', label: 'Compras', emoji: '🛍️' },
  { value: 'health', label: 'Saúde', emoji: '💊' },
  { value: 'bills', label: 'Contas', emoji: '📄' },
  { value: 'other', label: 'Outro', emoji: '📦' },
] as const;

export const EVENT_CATEGORIES = [
  { value: 'gym', label: 'Gym', color: '#EF4444' },
  { value: 'work', label: 'Trabalho', color: '#3B82F6' },
  { value: 'personal', label: 'Pessoal', color: '#8B5CF6' },
  { value: 'study', label: 'Estudo', color: '#F59E0B' },
  { value: 'social', label: 'Social', color: '#10B981' },
  { value: 'health', label: 'Saúde', color: '#EC4899' },
  { value: 'general', label: 'Geral', color: '#6B7280' },
] as const;

export const LOL_ROLES = [
  { value: 'top', label: 'Top' },
  { value: 'jungle', label: 'Jungle' },
  { value: 'mid', label: 'Mid' },
  { value: 'adc', label: 'ADC' },
  { value: 'support', label: 'Support' },
] as const;

// ── Notes ───────────────────────────────────────────────────────

export interface NoteFolder {
  id: number;
  name: string;
  icon: string;
  color: string;
  position: number;
  note_count: number;
}

export interface Note {
  id: number;
  title: string;
  content: string;
  folder_id: number | null;
  pinned: boolean;
  color: string;
  created_at: string;
  updated_at: string;
}

export const RECURRENCE_OPTIONS = [
  { value: 'none', label: 'Sem repetição' },
  { value: 'daily', label: 'Todos os dias' },
  { value: 'weekdays', label: 'Dias úteis (Seg-Sex)' },
  { value: 'weekly', label: 'Todas as semanas' },
  { value: 'biweekly', label: 'De 2 em 2 semanas' },
  { value: 'monthly', label: 'Todos os meses' },
  { value: 'yearly', label: 'Todos os anos' },
] as const;
