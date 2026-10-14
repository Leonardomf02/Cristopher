import { guardar as guardarNaFila, guardavel } from './outbox';

const BASE = '/api';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
  } catch (erroDeRede) {
    // Sem ligação: as acções que se podem repetir sem estragar nada ficam
    // guardadas e saem quando a rede voltar (apontar um gasto na rua, por
    // exemplo). O resto falha como antes.
    if (guardavel(path, options?.method || 'GET')) {
      guardarNaFila(path, options || {});
      return { offline: true, queued: true } as unknown as T;
    }
    throw erroDeRede;
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Request failed' }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

// ── Events ──────────────────────────────────────────────────────

export const eventsApi = {
  list: (params?: { start_date?: string; end_date?: string; category?: string }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    if (params?.category) qs.set('category', params.category);
    return request<any[]>(`/events/?${qs}`);
  },
  create: (data: any) => request<any>('/events/', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: any) => request<any>(`/events/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: number) => request<any>(`/events/${id}`, { method: 'DELETE' }),
  excludeDate: (id: number, date: string) => request<any>(`/events/${id}/exclude-date?target_date=${date}`, { method: 'POST' }),
  setOccurrenceCompleted: (id: number, date: string, completed: boolean, completedAt?: string | null) => {
    const qs = new URLSearchParams({ target_date: date, completed: String(completed) });
    if (completed && completedAt) qs.set('completed_at', completedAt);
    return request<any>(`/events/${id}/occurrence?${qs}`, { method: 'PUT' });
  },
  appleCalendars: () => request<{ calendars: string[] }>('/events/apple-calendars'),
  importAppleCalendar: (data: { calendars: string[]; days_back?: number; days_forward?: number }) =>
    request<{ imported: number; skipped: number; errors: number }>('/events/import-apple-calendar', { method: 'POST', body: JSON.stringify(data) }),
  exportAppleCalendar: (data?: { calendars?: string[]; days_back?: number; days_forward?: number }) =>
    request<{ exported: number; skipped: number; errors: number }>('/events/export-apple-calendar', { method: 'POST', body: JSON.stringify(data || {}) }),
};

// ── Expenses ────────────────────────────────────────────────────

export interface CitySpending {
  year: number | null;
  days: number | null;
  total: number;
  unknown: { total: number; count: number };
  cities: {
    city: string;
    country: string;
    country_name: string;
    flag: string;
    lat: number;
    lon: number;
    total: number;
    count: number;
    avg: number;
    first: string;
    last: string;
    days: number;
    per_day: number | null;
    top_category: string | null;
    trip: { id: number; destination: string } | null;
  }[];
}

export type ExpenseKind = 'spend' | 'income' | 'transfer' | 'reversal';

export interface Movements {
  spent: number;
  income: number;
  transfers: number;
  reversed: number;
  net: number;
  counts: Record<string, number>;
  month: number | null;
  year: number | null;
  transfer_rows: { date: string; description: string; amount: number }[];
}

// Uma compra em prestações: as que o banco já mostra (`payments`, com o número
// de cada uma) e as que faltam.
export interface KlarnaPlano {
  expense_id: number;
  description: string;
  amount: number;
  of: number;
  paid: number;
  payments: { expense_id: number; date: string; n: number }[];
  pending: { due: string; n: number }[];
}

export interface KlarnaPorPagar {
  total: number;
  months: {
    month: string;   // "2026-10"
    total: number;
    items: { expense_id: number; description: string; amount: number; due: string; n: number; of: number }[];
  }[];
  plans: KlarnaPlano[];
}

export interface DiaDeSalario {
  month: string;       // "2026-09"
  date: string;
  amount: number | null;
  description: string | null;
  source: 'banco' | 'manual' | 'estimado';
}

export interface CategoriaDeGasto { value: string; label: string; emoji: string }

export interface MovimentoCurto {
  id: number; description: string; amount: number; date: string; category: string;
  split_people: number | null; my_share: number | null;
}

export interface Reembolsos {
  // uma conta com os MB Ways de quem devolveu, ou um MB Way por várias contas
  suggestions: { expenses: MovimentoCurto[]; incomes: MovimentoCurto[]; share_after: number }[];
  pending: { expense: MovimentoCurto; expected: number; received: number; missing: number; missing_people: number | null; share: number }[];
  total_pending: number;
}

export interface ContaParaDescontar {
  id: number; description: string; amount: number; date: string;
  parts: number | null; split_people: number | null; reimbursed: number;
}

export const expensesApi = {
  list: (params?: { start_date?: string; end_date?: string; category?: string; trip_id?: number }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    if (params?.category) qs.set('category', params.category);
    if (params?.trip_id != null) qs.set('trip_id', String(params.trip_id));
    return request<any[]>(`/expenses/?${qs}`);
  },
  summary: (params?: { month?: number; year?: number }) => {
    const qs = new URLSearchParams();
    if (params?.month) qs.set('month', String(params.month));
    if (params?.year) qs.set('year', String(params.year));
    return request<any[]>(`/expenses/summary?${qs}`);
  },
  yearly: (year: number) => request<any>(`/expenses/yearly?year=${year}`),
  // Prestações da Klarna que ainda faltam, agrupadas pelo mês em que vencem.
  klarna: () => request<KlarnaPorPagar>('/expenses/klarna'),
  // Como ficava este gasto em N vezes, antes de gravar.
  klarnaPlano: (id: number, vezes: number) => request<KlarnaPlano>(`/expenses/${id}/klarna?vezes=${vezes}`),
  // O que passou na conta separado por natureza: gasto, entrada, dinheiro a
  // mudar de conta e compras revertidas. Um número só mentia.
  movements: (params?: { month?: number; year?: number }) => {
    const qs = new URLSearchParams();
    if (params?.month) qs.set('month', String(params.month));
    if (params?.year) qs.set('year', String(params.year));
    return request<Movements>(`/expenses/movements?${qs}`);
  },
  create: (data: any) => request<any>('/expenses/', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: any) => request<any>(`/expenses/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: number) => request<any>(`/expenses/${id}`, { method: 'DELETE' }),
  uploadReceipt: async (id: number, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${BASE}/expenses/${id}/receipt`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error('Upload failed');
    return res.json();
  },
  byCity: (year?: number, days?: number) => {
    const qs = new URLSearchParams();
    if (year) qs.set('year', String(year));
    if (days) qs.set('days', String(days));
    return request<CitySpending>(`/expenses/by-city?${qs}`);
  },
  byHour: (days = 365) =>
    request<{
      days: number;
      hours: { hour: number; total: number; count: number }[];
      peak: { hour: number; total: number; count: number } | null;
      with_time: number;
      without_time: number;
      total: number;
    }>(`/expenses/by-hour?days=${days}`),
  scanReceipt: async (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${BASE}/expenses/scan-receipt`, { method: 'POST', body: formData });
    if (!res.ok) {
      const erro = await res.json().catch(() => null);
      throw new Error(erro?.detail || 'Não consegui ler o recibo');
    }
    return res.json() as Promise<{
      receipt_path: string;
      text: string;
      merchant: string;
      items: string[];
      currency: string;
      confidence?: string;
      source?: string;
      suggestion: { description: string; amount: number | null; category: string; date: string; time_of_day: string | null; merchant_city: string | null; notes: string };
    }>;
  },
  attachReceipt: (id: number, path: string) =>
    request<any>(`/expenses/${id}/attach-receipt`, { method: 'POST', body: JSON.stringify({ path }) }),
  importCSV: async (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${BASE}/expenses/import/csv`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error('Import failed');
    return res.json();
  },
  importPDF: async (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${BASE}/expenses/import/pdf`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error('Import failed');
    return res.json();
  },
  recategorize: (month: number, year: number) =>
    request<{ updated: number; total: number }>(`/expenses/recategorize?month=${month}&year=${year}`, { method: 'POST' }),
  recategorizeYear: (year: number) =>
    request<{ updated: number; total: number }>(`/expenses/recategorize?year=${year}`, { method: 'POST' }),
  getIncome: (month: number, year: number) =>
    request<{ amount: number }>(`/expenses/income?month=${month}&year=${year}`),
  setIncome: (month: number, year: number, amount: number) =>
    request<{ amount: number }>(`/expenses/income?month=${month}&year=${year}&amount=${amount}`, { method: 'PUT' }),
  paydays: () => request<{ paydays: DiaDeSalario[]; typical_day: number }>('/expenses/paydays'),
  setPayday: (date: string, amount?: number) =>
    request<{ month: string; date: string }>('/expenses/paydays', { method: 'PUT', body: JSON.stringify({ date, amount: amount ?? null }) }),
  resetPayday: (month: string) => request<{ ok: boolean }>(`/expenses/paydays/${month}`, { method: 'DELETE' }),
  categories: () => request<CategoriaDeGasto[]>('/expenses/categories'),
  reimbursements: () => request<Reembolsos>('/expenses/reimbursements'),
  dismissReimbursement: (income_id: number, expense_id: number) =>
    request<{ ok: boolean }>('/expenses/reimbursements/dismiss', { method: 'POST', body: JSON.stringify({ income_id, expense_id }) }),
  reimburseCandidates: (incomeId: number) => request<ContaParaDescontar[]>(`/expenses/${incomeId}/reimburse-candidates`),
  linkReimbursement: (incomeId: number, expenseIds: number[]) =>
    request<any>(`/expenses/${incomeId}/reimburses`, { method: 'POST', body: JSON.stringify({ expense_ids: expenseIds }) }),
  unlinkReimbursement: (incomeId: number) => request<any>(`/expenses/${incomeId}/reimburses`, { method: 'DELETE' }),
  createCategory: (label: string, emoji: string) =>
    request<CategoriaDeGasto>('/expenses/categories', { method: 'POST', body: JSON.stringify({ label, emoji }) }),
  deleteCategory: (value: string) => request<{ ok: boolean }>(`/expenses/categories/${encodeURIComponent(value)}`, { method: 'DELETE' }),
};

// ── Wishlist ────────────────────────────────────────────────────

export interface WishCandidate {
  id: number; date: string; description: string; amount: number; category: string;
  klarna_installments: number | null; likely: boolean;
}

export const wishlistApi = {
  list: () => request<any[]>('/wishlist/'),
  summary: () => request<{ count: number; total_wanted: number; total_saved: number; total_remaining: number }>('/wishlist/summary'),
  create: (data: any) => request<any>('/wishlist/', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: any) => request<any>(`/wishlist/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: number) => request<any>(`/wishlist/${id}`, { method: 'DELETE' }),
  addSaving: (id: number, amount: number) => request<any>(`/wishlist/${id}/save?amount=${amount}`, { method: 'POST' }),
  // A compra liga-se a uma transacção que já está na conta — nunca se cria outra.
  purchase: (id: number, expenseId: number) =>
    request<any>(`/wishlist/${id}/purchase`, { method: 'POST', body: JSON.stringify({ expense_id: expenseId }) }),
  candidates: (id: number, q?: string) =>
    request<WishCandidate[]>(`/wishlist/${id}/candidates${q?.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''}`),
  unpurchase: (id: number) => request<any>(`/wishlist/${id}/unpurchase`, { method: 'POST' }),
  createWatch: (id: number) =>
    request<{ watch_id: number; created: boolean; title: string }>(`/wishlist/${id}/watch`, { method: 'POST' }),
  plan: (id: number) => request<WishPlan>(`/wishlist/${id}/plan`),
};

export interface WishPlan {
  item_id: number;
  name: string;
  price: number;
  saved: number;
  missing: number;
  weekly_leftover: number;
  weeks_needed: number | null;
  target_date: string | null;
  watch_id: number | null;
  best_deal: { id: number; title: string; price: number; url: string; rating: number | null } | null;
}

// ── LoL Games ───────────────────────────────────────────────────

export interface LolFactor {
  dimension: string;
  dimension_label: string;
  value: string;
  games: number;
  winrate: number;
  rest_winrate: number;
  diff: number;
  z: number;
  proven: boolean;
  games_needed: number | null;
}

export interface LolPerfFinding {
  metric: string;
  label: string;
  group_a: string;
  group_b: string;
  median_a: number;
  median_b: number;
  n_a: number;
  n_b: number;
  diff: number;
  diff_pct: number | null;
  z: number;
  p: number;
  better_in_a: boolean;
}

export interface LolDuelMetric {
  metric: string; label: string; moment: 'cedo' | 'jogo';
  mine: number; theirs: number | null; diff: number;
  games: number; win_pct: number | null; tie_pct: number;
  z: number; p: number; proven: boolean;
  in_my_favour: boolean; higher_is_better: boolean;
}

export interface LolDuel {
  games: number; games_total: number; with_timeline: number; winrate: number;
  metrics: LolDuelMetric[]; proven_count: number;
  by_champion: Record<string, any>[];
  critical_window: {
    points: { minute: number; wins: number; losses: number; gap: number;
              n_wins: number; n_losses: number }[];
    splits_at: number | null;
  } | null;
  edge: { champion: string; games: number; winrate: number; meta_wr: number;
          edge: number; edge_shrunk: number; meta_tier: number | null }[];
  map_side: {
    blue: { games: number; winrate: number };
    red: { games: number; winrate: number };
    diff: number; z: number; proven: boolean; better_side: 'red' | 'blue';
    causes: { metric: string; label: string; blue: number; red: number;
              diff: number; z: number; better_on_red: boolean }[];
  } | null;
  message: string;
}

export interface LolPick {
  champion: string; expected_wr: number;
  meta_wr: number; meta_wr_used: number; meta_games: number | null;
  meta_tier: number | null; pick_rate: number | null;
  matchup: number; synergy: number; comfort: number; comfort_label: string; comp: number;
  with: { ally: string; effect: number; raw_effect: number; games: number; role: string }[];
  games: number; my_wr: number | null; mastery: number; damage: string;
  vs: { enemy: string; effect: number; raw_effect: number; games: number }[];
  comp_reasons: string[];
}

export interface LolPicks {
  pool: LolPick[]; meta: LolPick[];
  enemies: string[]; allies?: string[]; enemies_without_matchup: string[];
  synergy_available?: boolean;
  spread: number; message?: string;
}

export interface LolCoach {
  in_game: boolean;
  side?: 'blue' | 'red' | null;
  game_time?: number;
  champion?: string | null;
  cs?: number | null;
  alerts: { key: string; level: 'aviso' | 'bom'; title: string; text: string; since: number }[];
}

export interface LolBans {
  bans: {
    champion: string; gain: number; cost_if_faced: number;
    best_answer: string; best_answer_wr: number; in_my_pool: boolean;
    encounters: number; encounter_pct: number;
    meta_wr: number | null; ban_rate: number | null;
  }[];
  days?: number; encounters?: number; message: string;
}

export interface LolWorthLearning {
  champions: {
    champion: string; meta_wr: number; meta_wr_used: number; meta_games: number | null;
    matchup: number; vs_my_enemies: number; learning_cost: number; worth_it: number;
    familiarity: string; mastery: number; games: number; coverage: number;
    already_playing: boolean;
    counter_exposure: number | null;
    worst_matchups: { enemy: string; effect: number; games: number }[];
  }[];
  encounters: number; distinct_enemies?: number; days?: number;
  top_enemies?: { champion: string; games: number }[];
  message: string;
}

export interface LolPerformance {
  games: number;
  games_total: number;
  baseline: Record<string, { label: string; median: number; p25: number; p75: number; n: number }>;
  findings: LolPerfFinding[];
  tested: { a: string; b: string; n_a: number; n_b: number }[];
  message: string;
}

export interface LolChampionPool {
  total: number;
  overall_wr: number | null;
  core_size: number;
  potential_wins: number;
  min_games: number;
  most_played: any;
  best: any[];
  worst: any[];
  champions: {
    champion: string; games: number; wins: number; winrate: number;
    ci_low: number; ci_high: number; share: number; role: string; kda: number | null;
    recent_form: string; verdict: string; proven: boolean; z: number;
    games_needed: number | null; vs_overall: number;
  }[];
}

export interface LolStopSignal {
  days: number;
  after_losses: { after_losses: number; games: number; winrate: number; baseline: number | null; z: number | null; proven: boolean }[];
  by_position: { position: number; games: number; winrate: number; z: number | null; proven: boolean }[];
  warnings: { key: string; text: string }[];
  today: { games: number; wins: number; losing_streak: number };
  should_stop: boolean;
}

export interface LolGoalBucket {
  days: number; games: number; wins: number; pct: number | null;
  positive_days: number; negative_days: number; tied_days: number;
  positive_pct: number | null; negative_pct: number | null;
}

export const lolApi = {
  performance: (days = 365) => request<LolPerformance>(`/lol/performance?days=${days}`),
  championPool: (minGames = 8, days?: number) =>
    request<LolChampionPool>(`/lol/champion-pool?min_games=${minGames}${days ? `&days=${days}` : ''}`),
  factors: (days?: number) =>
    request<{ total: number; overall_wr: number; factors: LolFactor[]; proven: LolFactor[]; noise_count: number }>(
      `/lol/factors${days ? `?days=${days}` : ''}`
    ),
  readiness: () =>
    request<{
      enough_data: boolean; reason?: string; base_wr: number; expected_wr: number;
      verdict: string; color: string; games_today: number; sleep_hours: number | null;
      factors: { key: string; label: string; wr: number | null; delta: number; samples: number | null }[];
      sample_size: number;
    }>('/lol/readiness'),
  list: (params?: { start_date?: string; end_date?: string; champion?: string; season_id?: number }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    if (params?.champion) qs.set('champion', params.champion);
    if (params?.season_id != null) qs.set('season_id', String(params.season_id));
    return request<any[]>(`/lol/?${qs}`);
  },
  stats: (params?: { start_date?: string; end_date?: string; season_id?: number }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    if (params?.season_id != null) qs.set('season_id', String(params.season_id));
    return request<any>(`/lol/stats?${qs}`);
  },
  daily: (date: string) => request<any>(`/lol/daily?target_date=${date}`),
  dailyGoal: (days = 180) => request<{
    target: number; enough: boolean; days_played: number; days_on_target: number;
    days_over: number; days_under: number; days_goal_met: number;
    goal_rate_pct: number; exact_rate_pct: number; streak: number;
    on_target: LolGoalBucket;
    off_target: LolGoalBucket;
    diff_pp: number | null; z: number | null; proven: boolean; verdict: string;
    days_diff_pp: number | null; days_z: number | null; days_proven: boolean;
    by_count: ({ games_that_day: number } & LolGoalBucket)[];
  }>(`/lol/daily-goal?days=${days}`),
  stopSignal: (days = 180) => request<LolStopSignal>(`/lol/stop-signal?days=${days}`),
  create: (data: any) => request<any>('/lol/', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: any) => request<any>(`/lol/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: number) => request<any>(`/lol/${id}`, { method: 'DELETE' }),
  // Riot API sync
  getRiotConfig: () => request<any>('/lol/riot/config'),
  setRiotConfig: (data: { game_name?: string; tag_line?: string; api_key?: string }) =>
    request<any>('/lol/riot/config', { method: 'POST', body: JSON.stringify(data) }),
  syncRiot: (days?: number, season?: boolean) => {
    const params = new URLSearchParams();
    if (days) params.set('days', String(days));
    if (season) params.set('season', 'true');
    const qs = params.toString();
    return request<any>(`/lol/riot/sync${qs ? `?${qs}` : ''}`, { method: 'POST', body: JSON.stringify({}) });
  },
  // Riot API — extra data
  getRank: () => request<any>('/lol/riot/rank'),
  getLive: () => request<any>('/lol/riot/live'),
  getLiveDetailed: () => request<any>('/lol/riot/live/detailed'),
  getLiveWinprob: () => request<any>('/lol/live-client/winprob'),
  getMastery: (top?: number) => request<any[]>(`/lol/riot/mastery${top ? `?top=${top}` : ''}`),
  getTimeline: (matchId: string) => request<any>(`/lol/riot/timeline/${matchId}`),
  getSummoner: () => request<any>('/lol/riot/summoner'),
  getPosition: () => request<any>('/lol/riot/position'),
  getPeak: () => request<any>('/lol/riot/peak'),
  getReplays: () => request<any[]>('/lol/riot/replays'),
  // Meta de jungle (patch actual)
  jungleInsights: () => request<any>('/lol/jungle/insights'),
  junglePatch: () => request<any>('/lol/jungle/patch'),
  jungleBuild: (champion: string) => request<any>(`/lol/jungle/build/${champion}`),
  jungleTips: (force?: boolean) => request<any>(`/lol/jungle/tips${force ? '?force=true' : ''}`),
  // Champ Select
  getChampSelectStatus: () => request<any>('/lol/champ-select/status'),
  getChampSelectSession: () => request<any>('/lol/champ-select/session'),
  getMetaStats: (source?: string) => request<any>('/lol/meta-stats' + (source && source !== 'all' ? `?source=${source}` : '')),
  counterPick: (enemy: string, role: string = 'jungle') =>
    request<{ enemy: string; role: string; personal: any[]; counters: any[]; strong_against: any[] }>(
      `/lol/counter-pick?enemy=${encodeURIComponent(enemy)}&role=${encodeURIComponent(role)}`
    ),
  championsList: () =>
    request<{ ddragon_key: string; name: string; title: string }[]>('/lol/champions-list'),
  seasonStats: (seasonId?: number) => request<any>('/lol/season-stats' + (seasonId ? `?season_id=${seasonId}` : '')),
  // Seasons (auto-archive on reset)
  listSeasons: () => request<any[]>('/lol/seasons'),
  seasonStatsById: (seasonId: number) => request<any>(`/lol/seasons/${seasonId}/stats`),
  resetSeason: () => request<any>('/lol/seasons/reset', { method: 'POST', body: JSON.stringify({}) }),
  renameSeason: (seasonId: number, label: string) => request<any>(`/lol/seasons/${seasonId}`, { method: 'PUT', body: JSON.stringify({ label }) }),
  detailedStats: (params?: { start_date?: string; end_date?: string; season_id?: number }) => {
    const qs = params ? Object.entries(params).filter(([,v]) => v != null && v !== '').map(([k,v]) => `${k}=${v}`).join('&') : '';
    return request<any>('/lol/detailed-stats' + (qs ? `?${qs}` : ''));
  },
  backfill: () => request<any>('/lol/riot/backfill', { method: 'POST', body: JSON.stringify({}) }),
  purgeAll: () => request<any>('/lol/purge/all', { method: 'DELETE' }),
  // AI Predictions
  getPredictions: (limit?: number) => request<any[]>(`/lol/predictions${limit ? `?limit=${limit}` : ''}`),
  getPredictionStats: () => request<any>('/lol/predictions/stats'),
  getPredictionCalibration: () => request<any>('/lol/predictions/calibration'),
  resolvePredictions: () => request<any>('/lol/predictions/resolve', { method: 'POST', body: JSON.stringify({}) }),
  // Duelo com o jungler adversário + recomendação de campeões
  duel: (days = 365) => request<LolDuel>(`/lol/duel?days=${days}`),
  picks: (enemies: string[] = [], role = 'jungle', taken: string[] = [], allies: string[] = []) =>
    request<LolPicks>(
      `/lol/picks?role=${role}`
      + (enemies.length ? `&enemies=${encodeURIComponent(enemies.join(','))}` : '')
      + (taken.length ? `&taken=${encodeURIComponent(taken.join(','))}` : '')
      + (allies.length ? `&allies=${encodeURIComponent(allies.join(','))}` : '')
    ),
  coach: () => request<LolCoach>('/lol/live-client/coach'),
  bans: (days = 180, role = 'jungle') =>
    request<LolBans>(`/lol/bans?days=${days}&role=${role}`),
  worthLearning: (days = 180, role = 'jungle') =>
    request<LolWorthLearning>(`/lol/worth-learning?days=${days}&role=${role}`),
};

// ── Trips ───────────────────────────────────────────────────────

export interface TripDetection {
  applied: boolean;
  trips_created: number;
  expenses_linked: number;
  home_by_month: Record<string, string>;
  looks_like_home: { id: number; destination: string; start_date: string; end_date: string | null }[];
  trips: {
    destination: string; country: string; start_date: string; end_date: string;
    cities: string[]; expenses: number; total: number; existing: boolean; id?: number;
  }[];
}

export const tripsApi = {
  list: () => request<any[]>('/trips/'),
  get: (id: number) => request<any>(`/trips/${id}`),
  create: (data: any) => request<any>('/trips/', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: any) => request<any>(`/trips/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: number) => request<any>(`/trips/${id}`, { method: 'DELETE' }),
  listPlaces: (tripId: number) => request<any[]>(`/trips/${tripId}/places`),
  addPlace: (tripId: number, data: any) => request<any>(`/trips/${tripId}/places`, { method: 'POST', body: JSON.stringify(data) }),
  updatePlace: (placeId: number, data: any) => request<any>(`/trips/places/${placeId}`, { method: 'PUT', body: JSON.stringify(data) }),
  deletePlace: (placeId: number) => request<any>(`/trips/places/${placeId}`, { method: 'DELETE' }),
  listExpenses: (tripId: number) => request<any[]>(`/trips/${tripId}/expenses`),
  autoDetect: () => request<any>('/trips/auto-detect', { method: 'POST' }),
  // Idas fora de casa, a partir das despesas (sabe onde ele vive em cada mês).
  detect: (apply = false) =>
    request<TripDetection>(`/trips/detect?apply=${apply}`, { method: 'POST' }),
  linkExpenses: (apply = false) =>
    request<{ applied: boolean; linked: number; by_trip: { trip_id: number; destination: string; count: number; amount: number; sample: string[] }[] }>(
      `/trips/link-expenses?apply=${apply}`, { method: 'POST' }
    ),
  cost: (tripId: number) =>
    request<{ trip_id: number; destination: string; days: number; expenses_total: number; expenses_count: number; fixed_total: number; total: number; per_day: number; by_category: { category: string; amount: number }[] }>(
      `/trips/${tripId}/cost`
    ),
  // Free-form ratings (comida, sítios, noite, encontros, etc.)
  listRatings: (tripId: number) => request<any[]>(`/trips/${tripId}/ratings`),
  addRating: (tripId: number, data: any) => request<any>(`/trips/${tripId}/ratings`, { method: 'POST', body: JSON.stringify(data) }),
  updateRating: (ratingId: number, data: any) => request<any>(`/trips/ratings/${ratingId}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteRating: (ratingId: number) => request<any>(`/trips/ratings/${ratingId}`, { method: 'DELETE' }),
};

// ── Lists ───────────────────────────────────────────────────────

export const listsApi = {
  list: () => request<any[]>('/lists/'),
  create: (data: { name: string; icon?: string; color?: string }) =>
    request<any>('/lists/', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: { name?: string; icon?: string; color?: string }) =>
    request<any>(`/lists/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: number) => request<any>(`/lists/${id}`, { method: 'DELETE' }),
  reorder: (ids: number[]) =>
    request<{ ok: true; count: number }>('/lists/reorder', { method: 'POST', body: JSON.stringify({ ids }) }),
  getItems: (listId: number) => request<any[]>(`/lists/${listId}/items`),
  addItem: (listId: number, data: { text: string; notes?: string; due_date?: string | null; due_time?: string | null; priority?: number }) =>
    request<any>(`/lists/${listId}/items`, { method: 'POST', body: JSON.stringify(data) }),
  updateItem: (itemId: number, data: { list_id?: number; text?: string; checked?: boolean; position?: number; notes?: string; due_date?: string | null; due_time?: string | null; priority?: number }) =>
    request<any>(`/lists/items/${itemId}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteItem: (itemId: number) => request<any>(`/lists/items/${itemId}`, { method: 'DELETE' }),
  getReminders: (params?: { start_date?: string; end_date?: string }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    return request<any[]>(`/lists/reminders?${qs}`);
  },
  pendingItems: () => request<any[]>('/lists/items/pending'),
  appleStatus: () => request<{
    disponivel: boolean; acesso?: boolean; motivo?: string;
    listas?: string[]; reminders?: number;
    last_run?: string; last_ok?: boolean; last_detail?: string;
  }>('/lists/apple/status'),
  appleSync: () => request<{ ok: true; resumo: string }>('/lists/apple/sync', { method: 'POST' }),
};

// ── Relógio Garmin ──────────────────────────────────────────────

export interface GarminDay {
  date: string;
  sleep: {
    start: string | null; end: string | null; hours: number | null;
    deep_min: number | null; light_min: number | null; rem_min: number | null;
    awake_min: number | null; nap_min: number | null; awake_count: number | null;
    score: number | null; qualifier: string | null; need_min: number | null;
    feedback: string | null; avg_stress: number | null;
    spo2_avg: number | null; spo2_min: number | null; resp_avg: number | null;
    skin_temp_dev_c: number | null;
  };
  recovery: {
    resting_hr: number | null; hrv: number | null; hrv_high: number | null;
    hrv_weekly: number | null; hrv_status: string | null;
    hrv_low: number | null; hrv_up: number | null; hrv_feedback: string | null;
  };
  body_battery: { start: number | null; end: number | null; min: number | null; max: number | null; charged: number | null; drained: number | null };
  stress: { avg: number | null; max: number | null; rest_min: number | null; low_min: number | null; medium_min: number | null; high_min: number | null };
  activity: {
    steps: number | null; step_goal: number | null; distance_m: number | null;
    calories: number | null; active_calories: number | null;
    moderate_min: number | null; vigorous_min: number | null;
    hr_min: number | null; hr_max: number | null;
  };
  training: {
    readiness: number | null; level: string | null; feedback: string | null;
    status: string | null; vo2max: number | null; acute_load: number | null; recovery_min: number | null;
    factors: { sleep: number | null; hrv: number | null; recovery: number | null; load: number | null; stress: number | null };
  };
  body: {
    fitness_age: number | null; achievable_age: number | null; bmi: number | null;
    weight_kg: number | null; weight_date?: string; vigorous_min: number | null; vigorous_days: number | null;
  };
  synced_at: string | null;
}

export interface GarminActivity {
  id: string; date: string; start: string | null; type: string; name: string;
  auto: boolean;               // detectado pelo relógio (Move IQ), não gravado por ele
  duration_s: number | null; distance_m: number | null; calories: number | null;
  avg_hr: number | null; max_hr: number | null; avg_speed: number | null;
  avg_cadence: number | null; avg_power: number | null;
  aerobic_te: number | null; anaerobic_te: number | null;
  location: string; lat: number | null; lon: number | null;
}

/** Um bloco da linha do dia: dormir, uma sesta, ou movimento (Move IQ). */
export interface GarminEvent {
  kind: 'sono' | 'sesta' | 'movimento';
  start: number; end: number;
  impact?: number | null;      // o que fez ao Body Battery
  type?: string; name?: string; auto?: boolean;
}

export interface GarminSeries {
  stress: [number, number][]; body_battery: [number, number][];
  hr: [number, number][]; steps: [number, number][];
  events: GarminEvent[];
}

export interface GarminSnapshot {
  uuid: string; date: string; start: string | null; duration_s: number | null;
  name: string; device: string;
  hr_avg: number | null; hr_min: number | null; hr_max: number | null;
  hrv_rmssd: number | null; hrv_sdrr: number | null;
  spo2_avg: number | null; spo2_min: number | null;
  resp_avg: number | null; resp_max: number | null;
  stress_avg: number | null; stress_max: number | null;
}

export interface GarminStatus {
  connected: boolean; enabled: boolean;
  watch_synced_at: string | null;
  last_day: string | null; last_sync: string | null;
  nights: number; nights_for_hrv: number; has_hrv: boolean;
  days: number; activities: number;
}

/** Uma sesta, com hora e duração. O `nap_min` do dia só dá o total. */
export interface GarminNap {
  start: number; end: number; min: number; impact: number | null;
}

export interface GarminHistoryPoint {
  date: string;
  sleep_hours: number | null; sleep_score: number | null;
  sleep_need_min: number | null; awake_count: number | null;
  avg_sleep_stress: number | null; resp_avg: number | null;
  nap_min: number | null; naps: GarminNap[];
  deep_min: number | null; light_min: number | null; rem_min: number | null; awake_min: number | null;
  hrv: number | null; hrv_status: string | null;
  hrv_weekly_avg: number | null; hrv_avg7: number | null;
  resting_hr: number | null; rhr_avg7: number | null;
  hr_min: number | null; hr_max: number | null;
  bb_start: number | null; bb_end: number | null;
  bb_min: number | null; bb_max: number | null;
  bb_charged: number | null; bb_drained: number | null;
  stress_avg: number | null; stress_max: number | null;
  stress_rest_min: number | null; stress_low_min: number | null;
  stress_medium_min: number | null; stress_high_min: number | null;
  steps: number | null; step_goal: number | null;
  distance_m: number | null; calories: number | null; active_calories: number | null;
  moderate_min: number | null; vigorous_min: number | null; intensity_7d: number | null;
  readiness: number | null; recovery_min: number | null; vo2max: number | null;
  fitness_age: number | null; weight_kg: number | null;
}

/** A faixa do costume dele numa métrica: mediana ± desvio robusto. `median` vem
 *  a null enquanto não houver `min_days` leituras — é o que evita desenhar uma
 *  régua feita de três dias. */
export interface GarminBaseline {
  median: number | null; low: number | null; high: number | null;
  n: number; source: 'app' | 'garmin';
}

export interface GarminBaselines {
  days: number;
  min_days: number;
  metrics: Record<string, GarminBaseline>;
  alerts: string[];
}

export interface GarminFact {
  key: string; text: string; strength: number; kind: 'desvio' | 'alvo' | 'padrao' | 'dia';
  good?: boolean; value?: number; median?: number; z?: number; target?: number;
}

export interface GarminRelation {
  key: string; text: string; rho: number; p: number; n: number; strength: number;
}

export interface GarminReading {
  date: string;
  facts: GarminFact[];
  relations: GarminRelation[];
  theme: string | null;
  headline: string;
  text: string;
  linked?: boolean;
  source: 'agente' | 'local' | 'regras' | 'vazio';
  days_measured: number;
  days_for_baseline: number;
  days_for_relations: number;
}

export interface GarminHrZones {
  floors: number[];            // piso das zonas 1 a 5, em bpm
  max: number;
  resting: number | null;
  method: string | null;
  minutes: number[];           // minutos do dia por zona; índice 0 = abaixo da zona 1
}

export interface GarminDayView {
  day: GarminDay | null;
  series: GarminSeries;
  coverage: { from: string | null; to: string | null; readings: number; hours_ago: number | null };
  hr_zones: GarminHrZones | null;
  activities: GarminActivity[];
  snapshots: GarminSnapshot[];
  stale: boolean;
  prev: string | null;
  next: string | null;
}

export const garminApi = {
  status: () => request<GarminStatus>('/garmin/status'),
  today: () => request<GarminDayView>('/garmin/today'),
  day: (date: string) => request<GarminDayView>(`/garmin/day/${date}`),
  history: (days = 30) => request<GarminHistoryPoint[]>(`/garmin/history?days=${days}`),
  baselines: (days = 30) => request<GarminBaselines>(`/garmin/baselines?days=${days}`),
  activities: (days = 30) => request<GarminActivity[]>(`/garmin/activities?days=${days}`),
  snapshots: (days = 30) => request<GarminSnapshot[]>(`/garmin/snapshots?days=${days}`),
  reading: (date?: string) => request<GarminReading>(`/garmin/reading${date ? `?date=${date}` : ''}`),
  sync: (days = 2) => request<{ dias: number; noites: number; treinos: number; message: string }>(`/garmin/sync?days=${days}`, { method: 'POST' }),
};

// ── Sleep ────────────────────────────────────────────────────────

export interface SleepAnalysis {
  days: number;
  nights: number;
  min_nights: number;
  composition: { key: string; name: string; nights: number; pct: number; minutes: number | null;
    reference: [number, number] | null; verdict: 'baixo' | 'típico' | 'alto' | null }[];
  summary: { key: string; name: string; n: number; median: string }[];
  drivers: { key: string; name: string; rho: number; p: number; n: number; text: string }[];
  tested: { key: string; name: string; n: number; reason: string; rho?: number; p?: number }[];
  good_vs_bad: {
    good: number; bad: number;
    rows: { key: string; name: string; good: string; bad: string; gap: number; notable: boolean }[];
  };
}

export interface SleepRhythm {
  days: number;
  nights: number;
  points: { date: string; weekday: number; bedtime: string | null; wake_time: string | null; bed_min: number | null; wake_min: number | null; hours: number | null; score: number | null }[];
  weeks: { week: string; bedtime: string; bed_min: number; nights: number }[];
  median_bedtime: string | null;
  median_wake: string | null;
  median_hours: number | null;
  bed_variation_h: number;
  wake_variation_h: number;
  weekend_shift_h: number | null;
  early: { days: number; winrate: number | null; games: number; code_hours: number; spend: number };
  late: { days: number; winrate: number | null; games: number; code_hours: number; spend: number };
}

export interface SleepMismatch {
  date: string;
  acao: 'criar' | 'corrigir';
  diferenca_h?: number;
  antigo: { bedtime: string; wake_time: string; hours: number; source: string } | null;
  novo: { bedtime: string; wake_time: string; hours: number; fact: string; confidence: string };
}

export const sleepApi = {
  powerEvents: (days = 14) =>
    request<{ slept_at: string; woke_at: string; minutes: number; hours: number; source: string; detail: string }[]>(
      `/sleep/power-events?days=${days}`
    ),
  reconcile: (days = 14, apply = false) =>
    request<{ days: number; applied: boolean; changes: SleepMismatch[] }>(
      `/sleep/reconcile?days=${days}&apply=${apply}`, { method: 'POST' }
    ),
  rhythm: (days = 120) => request<SleepRhythm>(`/sleep/rhythm?days=${days}`),
  analysis: (days = 90) => request<SleepAnalysis>(`/sleep/analysis?days=${days}`),
  suspect: (days = 60) =>
    request<{ id: number; date: string; hours: number; bedtime: string; wake_time: string; reason: string }[]>(
      `/sleep/suspect?days=${days}`
    ),
  confirm: (id: number) => request<any>(`/sleep/${id}/confirm`, { method: 'POST' }),
  list: (params?: { start_date?: string; end_date?: string }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    return request<any[]>(`/sleep/?${qs}`);
  },
  stats: (days?: number) => request<any>(`/sleep/stats${days ? `?days=${days}` : ''}`),
  create: (data: any) => request<any>('/sleep/', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: any) => request<any>(`/sleep/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: number) => request<any>(`/sleep/${id}`, { method: 'DELETE' }),
  estimate: (date?: string) =>
    request<{ date: string; bedtime: string; wake_time: string; hours: number; last_activity: string; first_activity: string; source: string }>(
      `/sleep/estimate${date ? `?date=${date}` : ''}`
    ),
};

// ── Day Types ───────────────────────────────────────────────────

export const dayTypesApi = {
  list: (params?: { start_date?: string; end_date?: string }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    return request<any[]>(`/day-types/?${qs}`);
  },
  set: (data: { date: string; type_name: string; color?: string; note?: string }) =>
    request<any>('/day-types/', { method: 'POST', body: JSON.stringify(data) }),
  delete: (id: number) => request<any>(`/day-types/${id}`, { method: 'DELETE' }),
};

// ── Flow Timer ──────────────────────────────────────────────────

export const flowApi = {
  // Presets
  listPresets: () => request<any[]>('/flow/presets'),
  createPreset: (data: any) => request<any>('/flow/presets', { method: 'POST', body: JSON.stringify(data) }),
  updatePreset: (id: number, data: any) => request<any>(`/flow/presets/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deletePreset: (id: number) => request<any>(`/flow/presets/${id}`, { method: 'DELETE' }),
  // Sessions
  listSessions: (params?: { start_date?: string; end_date?: string; preset_name?: string }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    if (params?.preset_name) qs.set('preset_name', params.preset_name);
    return request<any[]>(`/flow/sessions?${qs}`);
  },
  createSession: (data: any) => request<any>('/flow/sessions', { method: 'POST', body: JSON.stringify(data) }),
  deleteSession: (id: number) => request<any>(`/flow/sessions/${id}`, { method: 'DELETE' }),
  // Stats
  stats: (params?: { start_date?: string; end_date?: string }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    return request<any>(`/flow/stats?${qs}`);
  },
};

// ── Notes ────────────────────────────────────────────────────────

export const notesApi = {
  // Folders
  listFolders: () => request<any[]>('/notes/folders'),
  createFolder: (data: { name: string; icon?: string; color?: string }) =>
    request<any>('/notes/folders', { method: 'POST', body: JSON.stringify(data) }),
  updateFolder: (id: number, data: { name?: string; icon?: string; color?: string; position?: number }) =>
    request<any>(`/notes/folders/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteFolder: (id: number) => request<any>(`/notes/folders/${id}`, { method: 'DELETE' }),
  // Notes
  list: (params?: { folder_id?: number; search?: string; project_path?: string }) => {
    const qs = new URLSearchParams();
    if (params?.folder_id != null) qs.set('folder_id', String(params.folder_id));
    if (params?.search) qs.set('search', params.search);
    if (params?.project_path) qs.set('project_path', params.project_path);
    return request<any[]>(`/notes/?${qs}`);
  },
  get: (id: number) => request<any>(`/notes/${id}`),
  create: (data: { title?: string; content?: string; folder_id?: number | null; pinned?: boolean; color?: string; project_path?: string | null }) =>
    request<any>('/notes/', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: { title?: string; content?: string; folder_id?: number | null; pinned?: boolean; color?: string; project_path?: string | null }) =>
    request<any>(`/notes/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: number) => request<any>(`/notes/${id}`, { method: 'DELETE' }),
};

// ── Investments ──────────────────────────────────────────────────

export type T212Status = {
  configured: boolean;
  month?: string;
  positions: number;
  value_eur?: number;
  instruments: string[];
  trades?: number;
  transactions?: number;
  last_sync: string | null;
  ok: boolean | null;
  detail: string;
};

export type T212Sync = {
  positions: number; trades: number; transactions: number; dividends: number;
  account_value: number | null; errors: string[]; at: string;
};

export const investmentsApi = {
  t212Status: () => request<T212Status>('/investments/t212/status'),
  t212Sync: (full = false) =>
    request<T212Sync>(`/investments/t212/sync?full=${full}`, { method: 'POST' }),
  refreshPrices: () => request<{
    updated: { instrument: string; price: number; currency: string; value_eur: number; return_eur: number; source: string }[];
    failed: string[];
    at: string;
  }>('/investments/refresh-prices', { method: 'POST' }),
  valueHistory: (days = 180) => request<{
    days: number;
    points: { date: string; value: number; invested: number; return_eur: number }[];
    change_eur: number | null;
    priced_at: string | null;
  }>(`/investments/value-history?days=${days}`),
  contributions: (months = 6) =>
    request<{
      invest_pct: number; avg_done: number; total_done: number; total_planned: number;
      months: { month: string; planned: number; done: number; diff: number; source: string }[];
    }>(`/investments/contributions?months=${months}`),
  positions: () => request<any[]>('/investments/positions'),
  trades: () => request<any[]>('/investments/trades'),
  transactions: () => request<any[]>('/investments/transactions'),
  summary: () => request<any>('/investments/summary'),
  taxInsight: () => request<{ gross_return_eur: number; tax_estimate_eur: number; after_tax_eur: number; positions: any[]; nudges: string[]; note: string }>('/investments/tax-insight'),
  importPDF: (file: File, month?: string) => {
    const form = new FormData();
    form.append('file', file);
    if (month) form.append('month', month);
    return fetch('/api/investments/import/pdf', { method: 'POST', body: form }).then(async res => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
        throw new Error(err.detail || 'Upload failed');
      }
      return res.json();
    });
  },
  importFinstCSV: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return fetch('/api/investments/import/finst-csv', { method: 'POST', body: form }).then(async res => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
        throw new Error(err.detail || 'Upload failed');
      }
      return res.json();
    });
  },
  refreshCryptoPrices: () =>
    fetch('/api/investments/prices/crypto', { method: 'POST' }).then(async res => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Erro' }));
        throw new Error(err.detail || 'Erro');
      }
      return res.json();
    }),
  updatePositionPrice: (id: number, price: number) =>
    fetch(`/api/investments/positions/${id}/price`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_price: price }),
    }).then(async res => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Erro' }));
        throw new Error(err.detail || 'Erro');
      }
      return res.json();
    }),
  importFinstScreenshot: (file: File, month: string) => {
    const form = new FormData();
    form.append('file', file);
    form.append('month', month);
    return fetch('/api/investments/import/finst-screenshot', { method: 'POST', body: form }).then(async res => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Erro ao processar screenshot' }));
        throw new Error(err.detail || 'Erro ao processar screenshot');
      }
      return res.json();
    });
  },
  // Plans CRUD
  plans: () => request<any[]>('/investments/plans'),
  searchAsset: (q: string) => request<any[]>(`/investments/search-asset?q=${encodeURIComponent(q)}`),
  createPlan: (data: { name: string; instrument: string; asset_type?: string; target_amount_eur?: number }) =>
    fetch('/api/investments/plans', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then(async res => {
      if (!res.ok) { const err = await res.json().catch(() => ({ detail: 'Erro' })); throw new Error(err.detail || 'Erro'); }
      return res.json();
    }),
  updatePlan: (id: number, data: Record<string, any>) =>
    fetch(`/api/investments/plans/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then(async res => {
      if (!res.ok) { const err = await res.json().catch(() => ({ detail: 'Erro' })); throw new Error(err.detail || 'Erro'); }
      return res.json();
    }),
  deletePlan: (id: number) =>
    fetch(`/api/investments/plans/${id}`, { method: 'DELETE' }).then(async res => {
      if (!res.ok) { const err = await res.json().catch(() => ({ detail: 'Erro' })); throw new Error(err.detail || 'Erro'); }
      return res.json();
    }),
  // Allocations
  allocations: () => request<any[]>('/investments/allocations'),
  createAllocation: (data: { name: string; ticker: string; asset_type?: string; percentage: number; sort_order?: number }) =>
    fetch('/api/investments/allocations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then(async res => {
      if (!res.ok) { const err = await res.json().catch(() => ({ detail: 'Erro' })); throw new Error(err.detail || 'Erro'); }
      return res.json();
    }),
  updateAllocation: (id: number, data: Record<string, any>) =>
    fetch(`/api/investments/allocations/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then(async res => {
      if (!res.ok) { const err = await res.json().catch(() => ({ detail: 'Erro' })); throw new Error(err.detail || 'Erro'); }
      return res.json();
    }),
  deleteAllocation: (id: number) =>
    fetch(`/api/investments/allocations/${id}`, { method: 'DELETE' }).then(async res => {
      if (!res.ok) { const err = await res.json().catch(() => ({ detail: 'Erro' })); throw new Error(err.detail || 'Erro'); }
      return res.json();
    }),
  // Monthly plans
  monthlyPlan: (month: string) => request<any>(`/investments/monthly-plan/${month}`),
  updateMonthlyPlan: (month: string, data: { budget?: number; rotational_choices?: Record<string, string> }) =>
    fetch(`/api/investments/monthly-plan/${month}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then(async res => {
      if (!res.ok) { const err = await res.json().catch(() => ({ detail: 'Erro' })); throw new Error(err.detail || 'Erro'); }
      return res.json();
    }),
  executeMonthlyPlan: (month: string) =>
    fetch(`/api/investments/monthly-plan/${month}/execute`, { method: 'POST' }).then(async res => {
      if (!res.ok) { const err = await res.json().catch(() => ({ detail: 'Erro' })); throw new Error(err.detail || 'Erro'); }
      return res.json();
    }),
  unexecuteMonthlyPlan: (month: string) =>
    fetch(`/api/investments/monthly-plan/${month}/execute`, { method: 'DELETE' }).then(async res => {
      if (!res.ok) { const err = await res.json().catch(() => ({ detail: 'Erro' })); throw new Error(err.detail || 'Erro'); }
      return res.json();
    }),
  saveMonthlySnapshot: (month: string, entries: { ticker: string; name: string; asset_type: string; amount_eur: number; percentage?: number | null; source: string }[]) =>
    fetch(`/api/investments/monthly-plan/${month}/snapshot`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ entries }) }).then(async res => {
      if (!res.ok) { const err = await res.json().catch(() => ({ detail: 'Erro' })); throw new Error(err.detail || 'Erro'); }
      return res.json();
    }),
  monthlyPlanHistory: (limit?: number) =>
    request<any[]>(`/investments/monthly-plan-history${limit ? `?limit=${limit}` : ''}`),
  suggestions: () => request<any>('/investments/suggestions'),
  signalsAnalyzePlan: (extraQuestion?: string, excludedTickers?: string[]) =>
    fetch('/api/investments/signals/analyze-plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ extra_question: extraQuestion || '', excluded_tickers: excludedTickers || [] }),
    }).then(async res => {
      if (!res.ok) { const err = await res.json().catch(() => ({ detail: 'Erro' })); throw new Error(err.detail || 'Erro'); }
      return res.json();
    }),
  signalsPlanAnalysisLatest: () => request<any>('/investments/signals/plan-analysis-latest'),
  signalsPlanAnalysisDelete: () =>
    fetch('/api/investments/signals/plan-analysis-latest', { method: 'DELETE' }).then(r => r.json()),

  // Daily AI signals (news-based suggestions)
  signalsList: (limit = 30) => request<any[]>(`/investments/signals?limit=${limit}`),
  signalsLatest: () => request<any>('/investments/signals/latest'),
  marketPulse: () => request<{ available: boolean; drawdown_pct?: number; level?: string; hint?: string }>('/investments/signals/market-pulse'),
  signalsGenerate: (extraQuestion?: string) =>
    fetch('/api/investments/signals/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ extra_question: extraQuestion || '' }),
    }).then(async res => {
      if (!res.ok) { const err = await res.json().catch(() => ({ detail: 'Erro' })); throw new Error(err.detail || 'Erro'); }
      return res.json();
    }),
  signalsDelete: (id: number) =>
    fetch(`/api/investments/signals/${id}`, { method: 'DELETE' }).then(async res => {
      if (!res.ok) { const err = await res.json().catch(() => ({ detail: 'Erro' })); throw new Error(err.detail || 'Erro'); }
      return res.json();
    }),
  signalsPreviewNews: () => request<any>('/investments/signals/preview-news'),
  signalsRefreshPerformance: (id: number) =>
    fetch(`/api/investments/signals/${id}/refresh-performance`, { method: 'POST' }).then(async res => {
      if (!res.ok) { const err = await res.json().catch(() => ({ detail: 'Erro' })); throw new Error(err.detail || 'Erro'); }
      return res.json();
    }),
  signalsRefreshAll: () =>
    fetch('/api/investments/signals/refresh-all-performance', { method: 'POST' }).then(async res => {
      if (!res.ok) { const err = await res.json().catch(() => ({ detail: 'Erro' })); throw new Error(err.detail || 'Erro'); }
      return res.json();
    }),
  signalsHealth: () => request<any>('/investments/signals/health'),
  signalsCalibration: () => request<any>('/investments/signals/calibration'),
  signalsBacktest: () => request<any>('/investments/signals/backtest'),
  signalsPreviewMacro: () => request<any>('/investments/signals/preview-macro'),
  signalsPreviewOnchain: () => request<any>('/investments/signals/preview-onchain'),
  signalsPreviewFundamentals: () => request<any>('/investments/signals/preview-fundamentals'),
  signalsPreviewEarnings: () => request<any>('/investments/signals/preview-earnings'),
  signalsPreviewInsider: () => request<any>('/investments/signals/preview-insider'),
  signalsPreviewRegime: () => request<any>('/investments/signals/preview-regime'),
  signalsPreviewEarningsMomentum: () => request<any>('/investments/signals/preview-earnings-momentum'),
  signalsPreviewSentimentDelta: () => request<any>('/investments/signals/preview-sentiment-delta'),
  signalsPreviewFunding: () => request<any>('/investments/signals/preview-funding'),
  signalsHistoryRegime: (days = 60) => request<any>(`/investments/signals/history-regime?days=${days}`),
  signalsHistorySentiment: (days = 60) => request<any>(`/investments/signals/history-sentiment?days=${days}`),
  signalsHistoryFunding: (days = 60) => request<any>(`/investments/signals/history-funding?days=${days}`),
  signalsCalibrationByContext: () => request<any>('/investments/signals/calibration-by-context'),
  signalsCalibrationDecay: () => request<any>('/investments/signals/calibration-decay'),
  signalsDataSources: () => request<any>('/investments/signals/data-sources'),
  signalsAlerts: () => request<any>('/investments/signals/alerts'),
  signalsCritique: (id: number) =>
    fetch(`/api/investments/signals/${id}/critique`, { method: 'POST' }).then(async res => {
      if (!res.ok) { const err = await res.json().catch(() => ({ detail: 'Erro' })); throw new Error(err.detail || 'Erro'); }
      return res.json();
    }),
};


// ── Habits ──────────────────────────────────────────────────────

export const habitsApi = {
  suggestions: () =>
    request<{ habit_id: number; name: string; icon: string; reason: string }[]>('/habits/suggestions'),
  list: (activeOnly = true) => request<any[]>(`/habits/?active_only=${activeOnly}`),
  create: (data: any) => request<any>('/habits/', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: any) => request<any>(`/habits/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: number) => request<any>(`/habits/${id}`, { method: 'DELETE' }),

  completions: (habitId: number, startDate?: string, endDate?: string) => {
    const params = new URLSearchParams();
    if (startDate) params.set('start_date', startDate);
    if (endDate) params.set('end_date', endDate);
    return request<any[]>(`/habits/${habitId}/completions?${params}`);
  },
  complete: (habitId: number, data: { date: string; completed_at: string; notes?: string }) =>
    request<any>(`/habits/${habitId}/completions`, { method: 'POST', body: JSON.stringify(data) }),
  deleteCompletion: (habitId: number, completionId: number) =>
    request<any>(`/habits/${habitId}/completions/${completionId}`, { method: 'DELETE' }),

  completionsRange: (startDate: string, endDate: string) =>
    request<any[]>(`/habits/completions/range?start_date=${startDate}&end_date=${endDate}`),
  today: () => request<any[]>('/habits/today'),
  analytics: (days = 90) => request<any>(`/habits/analytics?days=${days}`),
  analyticsPeriodo: (start: string, end: string) =>
    request<any>(`/habits/analytics?start_date=${start}&end_date=${end}`),
};

// ── Dashboard / Weekly Review ───────────────────────────────────

export interface Anomaly {
  date: string;
  key: string;
  icon: string;
  title: string;
  text: string;
  direction: 'acima' | 'abaixo';
  score: number;
  severity: 'alta' | 'media';
}

export interface OnThisDay {
  label: string;
  date: string;
  spent: number;
  top_expense: { description: string; amount: number; category: string } | null;
  sleep_hours: number | null;
  mood: number | null;
  mood_note: string | null;
  journal: string | null;
  code_seconds: number;
  top_project: { name: string; seconds: number } | null;
  lol: { games: number; wins: number } | null;
  events: string[];
  trip: string | null;
  notes: number;
}

export const dashboardApi = {
  anomalies: (days = 14, baselineDays = 120) =>
    request<{ days: number; count: number; anomalies: Anomaly[] }>(
      `/dashboard/anomalies?days=${days}&baseline_days=${baselineDays}`
    ),
  onThisDay: (day?: string) =>
    request<{ today: string; entries: OnThisDay[] }>(`/dashboard/on-this-day${day ? `?day=${day}` : ''}`),
  monthlyReview: (month?: number, year?: number) => {
    const qs = new URLSearchParams();
    if (month) qs.set('month', String(month));
    if (year) qs.set('year', String(year));
    return request<any>(`/dashboard/monthly-review?${qs}`);
  },
  monthlyReviewPdf: async (month?: number, year?: number) => {
    const qs = new URLSearchParams();
    if (month) qs.set('month', String(month));
    if (year) qs.set('year', String(year));
    const res = await fetch(`/api/dashboard/monthly-review/pdf?${qs}`, { method: 'POST' });
    if (!res.ok) throw new Error('Não consegui gerar a retrospectiva');
    const disp = res.headers.get('Content-Disposition') || '';
    const m = disp.match(/filename="?([^"]+)"?/);
    return { blob: await res.blob(), filename: m?.[1] || 'retrospectiva.pdf' };
  },
  consistency: (days = 30) =>
    request<{
      today: { date: string; score: number; done: number; total: number; parts: { key: string; label: string; ok: boolean }[] } | null;
      streak: number; best_streak: number; average: number;
      series: { date: string; score: number }[];
    }>(`/dashboard/consistency?days=${days}`),
  insight: () =>
    request<{ week_start: string; week_end: string; insights: { key: string; icon: string; text: string }[] }>(
      '/dashboard/insight'
    ),
  weeklyReview: (weekOffset = 0) => request<any>(`/dashboard/weekly-review?week_offset=${weekOffset}`),
  correlations: () => request<any>('/dashboard/correlations'),
};

// ── Mood & Journal ──────────────────────────────────────────────

export const moodApi = {
  list: (params?: { start_date?: string; end_date?: string }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    return request<any[]>(`/mood/?${qs}`);
  },
  create: (data: { date: string; mood: number; quality?: string; note?: string; tags?: string }) =>
    request<any>('/mood/', { method: 'POST', body: JSON.stringify(data) }),
  delete: (id: number) => request<any>(`/mood/${id}`, { method: 'DELETE' }),
  today: () => request<any>('/mood/today'),
  journal: (params?: { start_date?: string; end_date?: string }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    return request<any[]>(`/mood/journal?${qs}`);
  },
  dayFacts: (day?: string) =>
    request<{ date: string; facts: { key: string; icon: string; label: string }[]; prompt: string }>(
      `/mood/day-facts${day ? `?day=${day}` : ''}`
    ),
  journalDraft: (day?: string) =>
    request<{ date: string; text: string; sources: string[]; empty: boolean }>(
      `/mood/journal-draft${day ? `?day=${day}` : ''}`
    ),
  journalPrompts: (day?: string) =>
    request<{ date: string; prompts: { key: string; icon: string; question: string }[] }>(
      `/mood/journal-prompts${day ? `?day=${day}` : ''}`
    ),
  saveJournal: (data: { date: string; content: string }) =>
    request<any>('/mood/journal', { method: 'POST', body: JSON.stringify(data) }),
  deleteJournal: (id: number) => request<any>(`/mood/journal/${id}`, { method: 'DELETE' }),

  // A app pergunta sobre os dias que fugiram ao padrão; a resposta vai para o
  // diário desse dia.
  perguntas: (days = 14, limit = 4) =>
    request<{ days: number; total: number; questions: DayQuestion[] }>(
      `/mood/questions?days=${days}&limit=${limit}`
    ),
  responderPergunta: (data: { date: string; key: string; question: string; answer: string }) =>
    request<{ ok: boolean; date: string }>('/mood/questions/answer', { method: 'POST', body: JSON.stringify(data) }),
  dispensarPergunta: (data: { date: string; key: string; question?: string }) =>
    request<{ ok: boolean }>('/mood/questions/dismiss', { method: 'POST', body: JSON.stringify(data) }),
  perguntasRespondidas: (limit = 20) =>
    request<{ date: string; key: string; question: string; answer: string; answered_at: string | null }[]>(
      `/mood/questions/answered?limit=${limit}`
    ),
};

export interface DayQuestion {
  date: string;
  key: string;
  icon: string;
  question: string;
  score: number | null;
  has_journal: boolean;
}

// ── Budgets & Subscriptions ─────────────────────────────────────

export interface WeeklyEnvelopes {
  week_start: string;
  week_end: string;
  is_current: boolean;
  days_left: number;
  total_envelope: number;
  total_spent: number;
  total_remaining: number;
  per_day_left: number;
  categories: {
    category: string;
    color: string | null;
    source: 'limite' | 'media';
    monthly_limit: number;
    envelope: number;
    base: number;
    rollover: number;
    spent: number;
    remaining: number;
    percentage: number;
    per_day_left: number;
    status: 'ok' | 'warning' | 'danger';
  }[];
}

export interface BankStatus {
  configured: boolean;
  synced_expenses: number;
  learned_merchants: number;
  unknown_merchants: number;
  app: { name: string; environment: string; active: boolean; redirect_urls: string[]; countries: number } | null;
  warning: string;
  connections: {
    id: number; institution: string; institution_id: string; status: string; link: string;
    expires_at: string | null; expires_in_days: number | null;
    last_sync: string | null; last_error: string;
    accounts: { id: number; name: string; iban: string; balance: number | null; currency: string; last_transaction: string | null }[];
  }[];
}

// Regra criada quando ele corrige a categoria de um movimento do banco.
export interface BankRule {
  id: number; key: string; label: string; category: string;
  expenses: number; updated_at: string | null;
}

// Saldo de cada banco (somadas as contas dele) na última sincronização.
export interface BankBalances {
  banks: {
    id: number; name: string; institution: string; balance: number; status: string; as_of: string | null;
    accounts: { iban: string; currency: string; balance: number; balance_eur: number }[];
    missing_fx: string[];
    cards: { currency: string; balance: number }[];   // sem IBAN: o cartão, fora da soma
  }[];
  total: number;
}

export const bankingApi = {
  status: () => request<BankStatus>('/banking/status'),
  balances: () => request<BankBalances>('/banking/balances'),
  institutions: (country = 'PT') =>
    request<{ id: string; name: string; logo: string | null; days: string; sandbox: boolean; personal: boolean }[]>(
      `/banking/institutions?country=${country}`
    ),
  connect: (institution_id: string, redirect_url: string) =>
    request<{ id: number; link: string; status: string; redirect_url: string }>('/banking/connect', {
      method: 'POST', body: JSON.stringify({ institution_id, redirect_url }),
    }),
  finish: (id: number, code: string) =>
    request<{ status: string; accounts: number; new: number; imported?: number; hint?: string }>(
      `/banking/connections/${id}/finish`, { method: 'POST', body: JSON.stringify({ code }) }
    ),
  learn: () => request<{ perguntadas: number; aprendidas: number; despesas: number }>(
    '/banking/learn', { method: 'POST' }
  ),
  sync: (days = 30, force = true) =>
    request<{ accounts: number; results: any[] }>(`/banking/sync?days=${days}&force=${force}`, { method: 'POST' }),
  remove: (id: number) => request<{ ok: boolean }>(`/banking/connections/${id}`, { method: 'DELETE' }),
  rules: () => request<BankRule[]>('/banking/rules'),
  updateRule: (id: number, category: string) =>
    request<BankRule & { changed: number }>(`/banking/rules/${id}`, { method: 'PUT', body: JSON.stringify({ category }) }),
  removeRule: (id: number) => request<{ ok: boolean }>(`/banking/rules/${id}`, { method: 'DELETE' }),
};

export const budgetsApi = {
  costOfLiving: (months = 6) => request<{
    months: number; enough: boolean;
    fixed_monthly: number; variable_monthly: number; monthly_cost: number;
    occasional_monthly: number; occasional_total: number; occasional_categories: string[];
    income_monthly: number; saving_rate_pct: number | null;
    buffer_eur: number; months_covered: number | null;
    by_month: { month: string; fixed: number; variable: number; income: number }[];
    biggest_variable: { category: string; total: number; share: number }[];
  }>(`/budgets/cost-of-living?months=${months}`),
  envelopes: (weekOffset = 0) =>
    request<WeeklyEnvelopes>(`/budgets/envelopes?week_offset=${weekOffset}`),
  forecast: (month?: number, year?: number) => {
    const qs = new URLSearchParams();
    if (month) qs.set('month', String(month));
    if (year) qs.set('year', String(year));
    return request<{
      month: number; year: number; days_elapsed: number; days_in_month: number;
      spent: number; income_extra: number; daily_rate: number; projected: number;
      salary: number; plan_target: number; verdict: string; over_by: number | null;
      categories: { category: string; spent: number; projected: number; limit: number | null; over_limit: boolean }[];
    }>(`/budgets/forecast?${qs}`);
  },
  detectSubscriptions: () =>
    request<{ key: string; name: string; amount: number; months: number; occurrences: number; last_date: string; category: string; yearly: number }[]>(
      '/budgets/subscriptions/detect'
    ),
  limitSuggestions: () =>
    request<{ category: string; avg_3m: number; suggested: number; has_limit: boolean }[]>('/budgets/limits/suggestions'),
  limits: () => request<any[]>('/budgets/limits'),
  createLimit: (data: { category: string; monthly_limit: number; color?: string }) =>
    request<any>('/budgets/limits', { method: 'POST', body: JSON.stringify(data) }),
  updateLimit: (id: number, data: { monthly_limit?: number; color?: string }) =>
    request<any>(`/budgets/limits/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteLimit: (id: number) => request<any>(`/budgets/limits/${id}`, { method: 'DELETE' }),
  status: (month?: number, year?: number) => {
    const qs = new URLSearchParams();
    if (month) qs.set('month', String(month));
    if (year) qs.set('year', String(year));
    return request<any>(`/budgets/status?${qs}`);
  },
  subscriptions: () => request<any[]>('/budgets/subscriptions'),
  createSubscription: (data: any) =>
    request<any>('/budgets/subscriptions', { method: 'POST', body: JSON.stringify(data) }),
  updateSubscription: (id: number, data: any) =>
    request<any>(`/budgets/subscriptions/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteSubscription: (id: number) =>
    request<any>(`/budgets/subscriptions/${id}`, { method: 'DELETE' }),
  subscriptionsSummary: () => request<any>('/budgets/subscriptions/summary'),

  // Plano do salário (grupos por % do salário)
  buckets: () => request<any[]>('/budgets/buckets'),
  createBucket: (data: { name: string; percentage: number; categories: string[]; kind?: string; color?: string; sort_order?: number }) =>
    request<any>('/budgets/buckets', { method: 'POST', body: JSON.stringify(data) }),
  updateBucket: (id: number, data: any) =>
    request<any>(`/budgets/buckets/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteBucket: (id: number) => request<any>(`/budgets/buckets/${id}`, { method: 'DELETE' }),
  salaryPlan: (p: { month?: number; year?: number; start?: string; end?: string; salary?: number }) => {
    const qs = new URLSearchParams();
    if (p.month) qs.set('month', String(p.month));
    if (p.year) qs.set('year', String(p.year));
    if (p.start) qs.set('start_date', p.start);
    if (p.end) qs.set('end_date', p.end);
    if (p.salary != null) qs.set('salary', String(p.salary));
    return request<any>(`/budgets/salary-plan?${qs}`);
  },
};

// ── Day Templates ───────────────────────────────────────────────

export const templatesApi = {
  list: () => request<any[]>('/templates/'),
  create: (data: { name: string; icon?: string; color?: string; events_json: string }) =>
    request<any>('/templates/', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: any) =>
    request<any>(`/templates/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: number) => request<any>(`/templates/${id}`, { method: 'DELETE' }),
};

// ── App Usage ───────────────────────────────────────────────────

export interface AppUsageSession {
  id: number;
  app_name: string;
  window_title: string;
  bundle_id: string | null;
  date: string;
  start_time: string;
  end_time: string;
  duration_seconds: number;
}

export interface AppUsageSummary {
  total_seconds: number;
  total_hours: number;
  by_app: {
    app_name: string;
    total_seconds: number;
    total_hours: number;
    session_count: number;
    percentage: number;
  }[];
}

export interface AppUsageCategory {
  category: string;
  label: string;
  color: string;
  total_seconds: number;
  total_hours: number;
  app_count: number;
  percentage: number;
}

export interface AppUsageAppRow {
  app_name: string;
  bundle_id: string | null;
  category: string;
  total_seconds: number;
  total_hours: number;
  session_count: number;
  percentage: number;
}

export interface AppUsageFullSummary {
  total_seconds: number;
  total_hours: number;
  by_app: AppUsageAppRow[];
  by_category: AppUsageCategory[];
}

export interface BrowserDomains {
  sites: { domain: string; seconds: number; sessions: number; days: number; category: string; percentage: number }[];
  total_seconds: number;
  distinct_domains: number;
  unknown_seconds: number;
  by_category: { category: string; label: string; color: string; seconds: number; percentage: number }[];
}

export interface FlowOverlap {
  flow_id: number;
  flow_name: string;
  flow_color: string;
  date: string;
  start_time: string;
  end_time: string;
  flow_duration_seconds: number;
  tracked_seconds: number;
  focus_ratio_pct: number;
  by_app: { app_name: string; seconds: number }[];
  by_category: { category: string; label: string; color: string; seconds: number }[];
}

export interface WeeklyTrend {
  start_date: string;
  end_date: string;
  label: string;
  total_seconds: number;
  by_category: { category: string; label: string; color: string; seconds: number }[];
}

export const appUsageApi = {
  selfUsage: (days = 30) => request<{
    days: number;
    total_seconds: number;
    unnamed_seconds: number;
    sections: { section: string; seconds: number; visits: number; last: string | null; share: number }[];
  }>(`/app-usage/self-usage?days=${days}`),
  sessions: (params?: { start_date?: string; end_date?: string; app_name?: string; min_seconds?: number }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    if (params?.app_name) qs.set('app_name', params.app_name);
    if (params?.min_seconds != null) qs.set('min_seconds', String(params.min_seconds));
    return request<AppUsageSession[]>(`/app-usage/sessions?${qs}`);
  },
  summary: (params?: { start_date?: string; end_date?: string }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    return request<AppUsageFullSummary>(`/app-usage/summary?${qs}`);
  },
  heatmap: (start_date: string, end_date: string) =>
    request<{ days: string[]; matrix: number[][] }>(`/app-usage/heatmap?start_date=${start_date}&end_date=${end_date}`),
  byTitle: (app_name: string, params?: { start_date?: string; end_date?: string; limit?: number }) => {
    const qs = new URLSearchParams({ app_name });
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    if (params?.limit) qs.set('limit', String(params.limit));
    return request<{ window_title: string; total_seconds: number; session_count: number; percentage: number }[]>(`/app-usage/by-title?${qs}`);
  },
  byDomain: (params?: { start_date?: string; end_date?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    if (params?.limit) qs.set('limit', String(params.limit));
    return request<BrowserDomains>(`/app-usage/by-domain?${qs}`);
  },
  flowOverlap: (params?: { start_date?: string; end_date?: string }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    return request<FlowOverlap[]>(`/app-usage/flow-overlap?${qs}`);
  },
  weeklyTrend: (weeks: number = 4) => request<WeeklyTrend[]>(`/app-usage/weekly-trend?weeks=${weeks}`),
  exportCsvUrl: (start_date?: string, end_date?: string) => {
    const qs = new URLSearchParams();
    if (start_date) qs.set('start_date', start_date);
    if (end_date) qs.set('end_date', end_date);
    return `/api/app-usage/export.csv?${qs}`;
  },
  categories: () => request<{ category: string; label: string; color: string }[]>('/app-usage/categories'),
  setCategoryOverride: (data: { app_name?: string; bundle_id?: string | null; category: string }) =>
    request<{ ok: true }>('/app-usage/categories/override', { method: 'POST', body: JSON.stringify(data) }),
  blocklist: () => request<{ id: number; app_name: string | null; bundle_id: string | null }[]>('/app-usage/blocklist'),
  addBlocklist: (data: { app_name?: string | null; bundle_id?: string | null }) =>
    request<{ id: number }>('/app-usage/blocklist', { method: 'POST', body: JSON.stringify(data) }),
  deleteBlocklist: (id: number) => request<{ ok: true }>(`/app-usage/blocklist/${id}`, { method: 'DELETE' }),
  status: () => request<{ running: boolean; last_seen: string | null; current_app: string | null; current_category: string | null; seconds_since?: number }>('/app-usage/status'),
  delete: (id: number) => request<any>(`/app-usage/sessions/${id}`, { method: 'DELETE' }),
  cleanup: (merge_gap_seconds = 5, retention_days = 0) =>
    request<{ merged: number; purged: number }>(`/app-usage/cleanup?merge_gap_seconds=${merge_gap_seconds}&retention_days=${retention_days}`, { method: 'POST' }),
};

// ── App Insights ────────────────────────────────────────────────

export interface FocusScoreDay {
  date: string;
  score: number | null;
  total_seconds: number;
  productive_seconds: number;
  distraction_seconds: number;
  deep_work_blocks: number;
  context_switches: number;
  switches_per_hour?: number;
  flow_distractions: number;
}

export interface Correlation {
  kind: string;
  text: string;
  metric: number;
  baseline: number;
  delta: number;
  samples_high: number;
  samples_low: number;
  category?: string;
  habit_name?: string;
}

export interface TransitionRow {
  from_app: string;
  to_app: string;
  count: number;
  pct_from: number;
}

export interface DeepWorkHour {
  hour: number;
  score: number | null;
  productive_seconds: number;
  distraction_seconds: number;
  total_seconds: number;
}

export interface CurrentState {
  has_data: boolean;
  tracker_running?: boolean;
  current_app?: string | null;
  current_category?: string | null;
  is_distraction?: boolean;
  active_flow?: { id: number; name: string; start_time: string; end_time: string | null } | null;
}

export const appInsightsApi = {
  focusScore: (start_date: string, end_date: string) =>
    request<{ average: number | null; days_scored: number; best_day: FocusScoreDay | null; worst_day: FocusScoreDay | null; series: FocusScoreDay[] }>(`/app-insights/focus-score?start_date=${start_date}&end_date=${end_date}`),
  deepWork: (days: number = 30) => request<{ hours: DeepWorkHour[]; best_hour: DeepWorkHour | null; worst_hour: DeepWorkHour | null; window_days: number }>(`/app-insights/deep-work?days=${days}`),
  transitions: (days: number = 30, limit: number = 20) =>
    request<{ window_days: number; transitions: TransitionRow[] }>(`/app-insights/transitions?days=${days}&limit=${limit}`),
  firstDistraction: (days: number = 30) =>
    request<{ samples: number; median_minutes: number | null; mean_minutes: number | null }>(`/app-insights/first-distraction?days=${days}`),
  correlations: (days: number = 30) =>
    request<{ window_days: number; insights: Correlation[] }>(`/app-insights/correlations?days=${days}`),
  currentState: () => request<CurrentState>('/app-insights/current-state'),
};

// ── App Goals ───────────────────────────────────────────────────

export interface AppGoal {
  id: number;
  category: string;
  direction: string;
  target_seconds: number;
  active: boolean;
}

export interface AppGoalProgress {
  id: number;
  category: string;
  label: string;
  color: string;
  direction: string;
  target_seconds: number;
  today_seconds: number;
  percentage: number;
  on_track: boolean;
  current_streak: number;
  best_streak: number;
}

// ── Ideas → Todos ─────────────────────────────────────────────────

export interface ExtractedTodo {
  text: string;
  priority: number;
  due_date: string | null;
  notes: string;
}

export const ideasApi = {
  process: (text: string) =>
    request<{ todos: ExtractedTodo[] }>('/ideas/process', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
};

// ── Screen Time (Apple knowledgeC.db) ───────────────────────────

export interface ScreenTimeDevice {
  device_id: string;
  last_seen: number | null;
  event_count: number;
  label?: string;
  kind?: string;
}

export interface ScreenTimeAppRow {
  bundle_id: string;
  app_name?: string;      // só a fonte tracker o traz
  device_id: string;
  category: string;
  total_seconds: number;
  session_count: number;
  label?: string;
  kind?: string;
}

export interface ScreenTimeDeviceRow {
  device_id: string;
  total_seconds: number;
  session_count: number;
  app_count: number;
  label?: string;
  kind?: string;
}

export interface ScreenTimeCategoryRow {
  category: string;
  total_seconds: number;
  app_count: number;
}

export const screenTimeApi = {
  // apple_local: o knowledgeC está neste servidor. Na NAS não está — as horas
  // medidas chegam pelo agente do Mac, e a leitura da Apple não existe.
  health: () => request<{ available: boolean; apple_local?: boolean; reason: string; db_path: string }>('/screen-time/health'),
  openSettings: () =>
    fetch('/api/screen-time/open-settings', { method: 'POST' }).then(async res => {
      if (!res.ok) throw new Error('Não consegui abrir System Settings');
      return res.json() as Promise<{ opened: boolean }>;
    }),
  devices: () => request<ScreenTimeDevice[]>('/screen-time/devices'),
  labelDevice: (device_id: string, data: { label: string; kind: string }) =>
    fetch(`/api/screen-time/devices/${encodeURIComponent(device_id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(async res => {
      if (!res.ok) throw new Error('Erro ao guardar etiqueta');
      return res.json();
    }),
  // weekday (0 = segunda) e category respondem a "que apps fazem as 2h45 de
  // Productivity & Finance às quartas". Só a fonte tracker os aceita.
  byApp: (params?: { start_date?: string; end_date?: string; device_id?: string; mode?: 'raw' | 'apple'; source?: 'tracker' | 'apple'; weekday?: number; category?: string }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    if (params?.device_id) qs.set('device_id', params.device_id);
    if (params?.source) qs.set('source', params.source);
    if (params?.mode) qs.set('mode', params.mode);
    if (params?.weekday !== undefined) qs.set('weekday', String(params.weekday));
    if (params?.category) qs.set('category', params.category);
    return request<ScreenTimeAppRow[]>(`/screen-time/by-app?${qs}`);
  },
  byCategory: (params?: { start_date?: string; end_date?: string; device_id?: string; mode?: 'raw' | 'apple'; source?: 'tracker' | 'apple' }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    if (params?.device_id) qs.set('device_id', params.device_id);
    if (params?.source) qs.set('source', params.source);
    if (params?.mode) qs.set('mode', params.mode);
    return request<ScreenTimeCategoryRow[]>(`/screen-time/by-category?${qs}`);
  },
  byDevice: (params?: { start_date?: string; end_date?: string; mode?: 'raw' | 'apple'; source?: 'tracker' | 'apple' }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    if (params?.mode) qs.set('mode', params.mode);
    if (params?.source) qs.set('source', params.source);
    return request<ScreenTimeDeviceRow[]>(`/screen-time/by-device?${qs}`);
  },
  // Meta de ecrã por categoria — um alvo de horas por dia. Dia/semana/mês são
  // só formas de VER o progresso (o status devolve as três de uma vez), não
  // três metas diferentes.
  goals: () =>
    request<{ id: number; category: string; target_hours: number; days: string;
      active: boolean; habit_id: number | null; habit_name: string | null; habit_icon: string | null }[]>('/screen-time/goals'),
  setGoal: (category: string, target_hours: number, days: string, habit_id?: number | null) =>
    request<any>('/screen-time/goals', { method: 'PUT', body: JSON.stringify({ category, target_hours, days, habit_id: habit_id ?? null }) }),
  // refDate ancora as três vistas noutro dia (ex: um mês passado) — sem ele,
  // fica ancorado em hoje.
  goalsStatus: (refDate?: string) =>
    request<{
      date: string;
      goals: {
        category: string; days: string; target_hours: number; scheduled_today: boolean;
        views: Record<'day' | 'week' | 'month', {
          used_seconds: number; target_seconds: number; pct: number | null;
          remaining_seconds: number; reached: boolean; period_start: string; period_end: string;
        }>;
        habit_id: number | null; habit_name: string | null; habit_icon: string | null; habit_checked_today: boolean | null;
      }[];
    }>(`/screen-time/goals/status${refDate ? `?ref_date=${refDate}` : ''}`),
  byHour: (category: string, days = 30) =>
    request<{ hours: number[]; window_days: number }>(`/screen-time/by-hour?category=${encodeURIComponent(category)}&days=${days}`),
  timeseriesStacked: (params?: { start_date?: string; end_date?: string; bucket?: 'hour' | 'day'; device_id?: string; mode?: 'raw' | 'apple'; source?: 'tracker' | 'apple' }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    if (params?.bucket) qs.set('bucket', params.bucket);
    if (params?.device_id) qs.set('device_id', params.device_id);
    if (params?.mode) qs.set('mode', params.mode);
    if (params?.source) qs.set('source', params.source);
    return request<{ bucket_start: number; categories: Record<string, number> }[]>(`/screen-time/timeseries-stacked?${qs}`);
  },
  timeseries: (params?: { start_date?: string; end_date?: string; bucket?: 'hour' | 'day'; device_id?: string; mode?: 'raw' | 'apple' }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    if (params?.bucket) qs.set('bucket', params.bucket);
    if (params?.device_id) qs.set('device_id', params.device_id);
    if (params?.mode) qs.set('mode', params.mode);
    return request<{ bucket_start: number; total_seconds: number }[]>(`/screen-time/timeseries?${qs}`);
  },
  insights: (params: { start_date?: string; end_date?: string; bucket?: 'day' | 'month' }) => {
    const qs = new URLSearchParams();
    if (params.start_date) qs.set('start_date', params.start_date);
    if (params.end_date) qs.set('end_date', params.end_date);
    if (params.bucket) qs.set('bucket', params.bucket);
    return request<ScreenTimeInsights>(`/screen-time/insights?${qs}`);
  },
  snapshot: (daysBack = 45) =>
    fetch(`/api/screen-time/snapshot?days_back=${daysBack}`, { method: 'POST' })
      .then(res => res.json() as Promise<{ days_written: number }>),
};

export interface ScreenTimeInsights {
  start: string;
  end: string;
  bucket: 'day' | 'month';
  tracked_days: number;
  first_date: string | null;
  last_date: string | null;
  total_all_seconds: number;
  total_period_seconds: number;
  daily_avg_seconds: number;
  total_prev_seconds: number;
  delta_pct: number | null;
  busiest_day: { date: string; seconds: number } | null;
  quietest_day: { date: string; seconds: number } | null;
  timeseries: { date: string; seconds: number }[];
  top_apps: { bundle_id: string; seconds: number; category: string }[];
  by_category: { category: string; seconds: number }[];
  by_weekday: { weekday: number; avg_seconds: number }[];
}

// ── VS Code Activity ──────────────────────────────────────────────

export interface CodeActivityFile {
  abs_path: string;
  rel_path: string;
  filename: string;
  saves: number;
  sources: string[];
  last_ts: number;
}

export interface CodeActivityProject {
  name: string;
  path: string;
  saves: number;
  files_count: number;
  files: CodeActivityFile[];
  last_ts: number;
}

export interface CodeActivityDay {
  date: string;
  total_saves: number;
  total_files: number;
  projects: CodeActivityProject[];
  history_dir: string | null;
}

export interface CodeProjectTodo {
  id: number;
  project_path: string;
  content: string;
  done: boolean;
  created_at: string;
  done_at: string | null;
}

export interface CodeProjectNote {
  id: number;
  project_path: string;
  content: string;
  source: 'manual' | 'ai';
  note_date: string | null;
  created_at: string;
}

export interface CodeKnownProject {
  path: string;
  name: string;
  open_todos: number;
  total_todos: number;
  notes_count: number;
  last_activity: string | null;
  favorite: boolean;
}

export interface WakaAiTrend {
  since: string;
  months: { month: string; cost: number; ai_lines: number; human_lines: number; ai_pct: number; sessions: number; prompts: number; seconds: number }[];
  projects: { name: string; cost: number; ai_lines: number; human_lines: number; ai_pct: number; seconds: number; cost_per_hour: number | null }[];
  total_cost: number;
  total_ai_lines: number;
  total_human_lines: number;
  ai_pct: number;
}

export const codeActivityApi = {
  forDate: (date?: string) => {
    const qs = new URLSearchParams();
    if (date) qs.set('date', date);
    return request<CodeActivityDay>(`/code-activity/?${qs}`);
  },
  range: (days: number = 7) =>
    request<{ days: { date: string; total_saves: number; total_files: number; project_count: number }[] }>(
      `/code-activity/range?days=${days}`
    ),
  totals: () =>
    request<{ open_todos: number; total_notes: number }>(`/code-activity/totals`),
  stalled: (days = 7) =>
    request<{ path: string; name: string; open_todos: number; last_touch: string | null; days: number | null }[]>(
      `/code-activity/stalled?days=${days}`
    ),
  openTodos: (limit = 20) =>
    request<{ id: number; content: string; project_path: string; project: string; created_at: string | null }[]>(
      `/code-activity/todos/open?limit=${limit}`
    ),
  projectsWithTodos: () =>
    request<{ path: string; name: string }[]>(`/code-activity/projects-with-todos`),
  allProjects: () =>
    request<CodeKnownProject[]>(`/code-activity/all-projects`),
  noteToTodos: (noteId: number) =>
    request<CodeProjectTodo[]>(`/code-activity/notes/${noteId}/to-todos`, { method: 'POST' }),
  setFavorite: (projectPath: string, favorite: boolean) =>
    request<{ path: string; favorite: boolean }>(
      `/code-activity/project/favorite?project_path=${encodeURIComponent(projectPath)}`,
      { method: 'PUT', body: JSON.stringify({ favorite }) }
    ),
  listTodos: (projectPath: string) =>
    request<CodeProjectTodo[]>(`/code-activity/project/todos?project_path=${encodeURIComponent(projectPath)}`),
  createTodo: (projectPath: string, content: string) =>
    request<CodeProjectTodo>(`/code-activity/project/todos?project_path=${encodeURIComponent(projectPath)}`, {
      method: 'POST', body: JSON.stringify({ content }),
    }),
  updateTodo: (id: number, patch: { content?: string; done?: boolean }) =>
    request<CodeProjectTodo>(`/code-activity/todos/${id}`, {
      method: 'PATCH', body: JSON.stringify(patch),
    }),
  deleteTodo: (id: number) =>
    request<{ deleted: number }>(`/code-activity/todos/${id}`, { method: 'DELETE' }),
  listNotes: (projectPath: string) =>
    request<CodeProjectNote[]>(`/code-activity/project/notes?project_path=${encodeURIComponent(projectPath)}`),
  createNote: (projectPath: string, content: string, noteDate?: string) =>
    request<CodeProjectNote>(`/code-activity/project/notes?project_path=${encodeURIComponent(projectPath)}`, {
      method: 'POST', body: JSON.stringify({ content, note_date: noteDate || null }),
    }),
  generateNote: (projectPath: string, date: string) =>
    request<CodeProjectNote>(
      `/code-activity/project/notes/generate?project_path=${encodeURIComponent(projectPath)}&date=${date}`,
      { method: 'POST' }
    ),
  // Relatório PDF do projecto (a IA organiza as notas do período). Devolve o blob.
  notesReport: async (projectPath: string, days: number) => {
    const res = await fetch(
      `/api/code-activity/project/notes/report?project_path=${encodeURIComponent(projectPath)}&days=${days}`,
      { method: 'POST' }
    );
    if (!res.ok) {
      let detail = 'Erro a gerar o relatório';
      try { detail = (await res.json()).detail || detail; } catch { /* corpo não-JSON */ }
      throw new Error(detail);
    }
    const disposition = res.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="?([^"]+)"?/);
    return { blob: await res.blob(), filename: match?.[1] || 'relatorio.pdf' };
  },
  weeklySummary: (weeksBack = 0, refresh = false) =>
    request<{
      week_start: string; week_end: string; total_seconds: number;
      projects: { name: string; seconds: number }[];
      note_count: number; todos_done: number; bullets: string[]; generated: boolean;
    }>(`/code-activity/weekly-summary?weeks_back=${weeksBack}${refresh ? '&refresh=true' : ''}`),
  updateNote: (id: number, content: string) =>
    request<CodeProjectNote>(`/code-activity/notes/${id}`, {
      method: 'PATCH', body: JSON.stringify({ content }),
    }),
  deleteNote: (id: number) =>
    request<{ deleted: number }>(`/code-activity/notes/${id}`, { method: 'DELETE' }),
};

export interface WakaBreakdownItem {
  name: string;
  total_seconds: number;
  text: string;
}

export interface WakaDay {
  date: string;
  total_seconds: number;
  ai_seconds: number;
  text: string;
}

export interface WakaAgent {
  name: string;
  lines: number;
  lines_text: string;
  pct: number;
}

export interface WakaProjectDetail {
  name: string;
  seconds: number;
  text: string;
  ai_changes: number;
  ai_changes_text: string;
  ai_changes_pct: number;
  human_changes: number;
  human_changes_text: string;
  human_changes_pct: number;
  ai_prompts: number;
  ai_prompt_avg_chars: number;
  ai_sessions: number;
  ai_avg_prompts_per_session: number;
  input_tokens: number;
  output_tokens: number;
  tokens_text: string;
  input_tokens_text: string;
  output_tokens_text: string;
  ai_cost: number;
  ai_cost_text: string;
}

export const WAKA_RANGES: { key: string; label: string }[] = [
  { key: 'today', label: 'Hoje' },
  { key: 'last_7_days', label: 'Últimos 7 dias' },
  { key: 'last_14_days', label: 'Últimos 14 dias' },
  { key: 'last_30_days', label: 'Últimos 30 dias' },
  { key: 'this_week', label: 'Esta semana' },
  { key: 'last_week', label: 'Semana passada' },
  { key: 'this_month', label: 'Este mês' },
  { key: 'last_month', label: 'Mês passado' },
];

export const WAKA_PROJECT_RANGES: { key: string; label: string }[] = [
  ...WAKA_RANGES,
  { key: 'all_time', label: 'Desde sempre' },
];

export interface WakaAi {
  coding_pct: number;
  ai_lines: number;
  ai_lines_text: string;
  human_lines: number;
  human_lines_text: string;
  ai_line_pct: number;
  input_tokens: number;
  output_tokens: number;
  tokens_text: string;
  input_tokens_text: string;
  output_tokens_text: string;
  sessions: number;
  prompts: number;
  cost: number;
  cost_text: string;
}

export interface WakaSummary {
  configured: boolean;
  range_key: string;
  range_label: string;
  start?: string;
  end?: string;
  days: WakaDay[];
  projects: WakaBreakdownItem[];
  today_projects: WakaBreakdownItem[];
  project_details: WakaProjectDetail[];
  agents: WakaAgent[];
  languages: WakaBreakdownItem[];
  editors: WakaBreakdownItem[];
  categories: WakaBreakdownItem[];
  dependencies: WakaBreakdownItem[];
  ai: WakaAi;
  total_seconds: number;
  total_text?: string;
  today_seconds: number;
  today_text?: string;
  daily_average_seconds: number;
  daily_average_text?: string;
  today_vs_avg_pct: number;
  active_days: number;
  best_day: WakaDay | null;
}

export interface WakaHours {
  configured: boolean;
  hours: { hour: number; seconds: number; text: string }[];
  total_seconds: number;
  peak_hour: number | null;
  quiet_hour: number | null;
}

export const wakatimeApi = {
  aiTrend: (months = 6) => request<WakaAiTrend>(`/wakatime/ai-trend?months=${months}`),
  summary: (arg: string | { range?: string; month?: string; year?: number } = 'last_7_days') => {
    const qs = new URLSearchParams();
    if (typeof arg === 'string') {
      if (arg) qs.set('range', arg);
    } else {
      if (arg.range) qs.set('range', arg.range);
      if (arg.month) qs.set('month', arg.month);
      if (arg.year != null) qs.set('year', String(arg.year));
    }
    return request<WakaSummary>(`/wakatime/summary?${qs}`);
  },
  periods: () => request<{ months: string[]; years: number[] }>(`/wakatime/periods`),
  hours: (arg: string | { range?: string; month?: string; year?: number } = 'last_30_days') => {
    const qs = new URLSearchParams();
    if (typeof arg === 'string') { if (arg) qs.set('range', arg); }
    else {
      if (arg.range) qs.set('range', arg.range);
      if (arg.month) qs.set('month', arg.month);
      if (arg.year != null) qs.set('year', String(arg.year));
    }
    return request<WakaHours>(`/wakatime/hours?${qs}`);
  },
  sync: (days: number = 14) => request<{ synced_days: number }>(`/wakatime/sync?days=${days}`, { method: 'POST' }),
  status: () => request<{ configured: boolean; api_url: string }>(`/wakatime/status`),
};

export const appUsageTitlesApi = {
  rules: () => request<{ id: number; pattern: string; category: string; source: string }[]>('/app-usage/title-rules'),
  setRule: (pattern: string, category: string) =>
    request<any>('/app-usage/title-rules', { method: 'PUT', body: JSON.stringify({ pattern, category }) }),
  deleteRule: (id: number) => request<any>(`/app-usage/title-rules/${id}`, { method: 'DELETE' }),
  unclassified: (days = 60, limit = 15) =>
    request<{ titles: { title: string; seconds: number }[]; total_seconds: number; untitled_seconds: number }>(
      `/app-usage/unclassified-titles?days=${days}&limit=${limit}`
    ),
  learn: (days = 60) =>
    request<{ learned: number; rules: { pattern: string; category: string }[]; reason?: string }>(
      `/app-usage/title-rules/learn?days=${days}`, { method: 'POST' }
    ),
};

export const appGoalsApi = {
  list: () => request<AppGoal[]>('/app-goals/'),
  create: (data: { category: string; direction: string; target_seconds: number }) =>
    request<AppGoal>('/app-goals/', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: { direction?: string; target_seconds?: number; active?: boolean }) =>
    request<AppGoal>(`/app-goals/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: number) => request<{ ok: true }>(`/app-goals/${id}`, { method: 'DELETE' }),
  progress: (on_date?: string, streak_window_days: number = 30) => {
    const qs = new URLSearchParams();
    if (on_date) qs.set('on_date', on_date);
    qs.set('streak_window_days', String(streak_window_days));
    return request<{ date: string; goals: AppGoalProgress[] }>(`/app-goals/progress?${qs}`);
  },
};

// ── Deals (caça-deals) ──────────────────────────────────────────

export interface DealCriteria {
  year_min?: number | null;
  year_max?: number | null;
  km_max?: number | null;
  power_kw_min?: number | null;
  power_kw_max?: number | null;
  colors?: string[];
  price_max?: number | null;
  must_include?: string[];
  must_exclude?: string[];
}

export interface DealCheck {
  key: string;
  label: string;
  status: 'ok' | 'fail' | 'unknown';
  detail: string;
}

export interface DealWatch {
  id: number;
  title: string;
  query: string;
  category: string;
  condition: string;          // any | new | used
  sources: string;            // all | vinted | csv
  max_price: number | null;
  min_rating: number;
  ai_context: string;
  exclude_keywords: string;
  kind: string;               // specific | generic
  criteria: DealCriteria;
  notify: boolean;
  active: boolean;
  last_checked_at: string | null;
  new_count: number;
  total_count: number;
  pending_count: number;
  gone_count: number;
  scanning: boolean;
}

export interface DealResult {
  id: number;
  watch_id: number;
  source: string;
  title: string;
  description: string;
  price: number | null;
  currency: string;
  condition: string;
  url: string;
  image_url: string;
  location: string;
  seller: string;
  ai_rating: number | null;
  ai_match: boolean;
  ai_reason: string;
  status: string;             // new | seen | saved | dismissed
  first_seen_at: string | null;
  last_seen_at: string | null;
  gone_at: string | null;
  reappeared_at: string | null;
  price_percentile: number | null;
  vs_median: number | null;
  attrs: { year: number | null; km: number | null; power_kw: number | null; color: string | null };
  checks: DealCheck[];
  verdict: '' | 'ok' | 'fail' | 'unknown';
  fair_price: number | null;
  fair_basis: string;
  vs_fair: number | null;
}

export interface DealPriceStats {
  watch_id: number;
  count: number;
  enough: boolean;
  min?: number;
  p10?: number;
  p25?: number;
  median?: number;
  p75?: number;
  p90?: number;
  max?: number;
  months?: { month: string; median: number; count: number }[];
}

export type DealWatchInput = {
  title: string;
  query: string;
  category?: string;
  condition?: string;
  sources?: string;
  max_price?: number | null;
  min_rating?: number;
  ai_context?: string;
  exclude_keywords?: string;
  kind?: string;
  criteria?: DealCriteria;
  notify?: boolean;
  active?: boolean;
};

export interface TriageItem {
  attrs?: { year: number | null; km: number | null; power_kw: number | null; color: string | null };
  checks?: DealCheck[];
  verdict?: string;
  fair_price?: number | null;
  fair_basis?: string;
  vs_fair?: number | null;
  id: number;
  watch_id: number;
  watch_title: string;
  title: string;
  price: number | null;
  currency: string;
  url: string;
  image_url: string;
  location: string;
  source: string;
  condition: string;
  ai_rating: number | null;
  ai_reason: string;
  status: string;
  price_percentile: number | null;
  vs_median: number | null;
  first_seen_at: string | null;
}

export const dealsApi = {
  triage: (limit = 20) => request<{ pending: number; items: TriageItem[] }>(`/deals/triage?limit=${limit}`),
  triageApply: (saved: number[], dismissed: number[]) =>
    request<{ ok: true; updated: number }>('/deals/triage', {
      method: 'POST', body: JSON.stringify({ saved, dismissed }),
    }),
  priceStats: (watchId: number) => request<DealPriceStats>(`/deals/watches/${watchId}/price-stats`),
  weeklyTop: (limit = 3, days = 7) =>
    request<{ id: number; title: string; price: number | null; currency: string; rating: number | null; source: string; url: string; image_url: string; location: string }[]>(
      `/deals/weekly-top?limit=${limit}&days=${days}`
    ),
  priceDrops: (days = 30) =>
    request<{ id: number; title: string; price: number; previous_price: number; drop: number; drop_pct: number; currency: string; url: string; source: string; saved: boolean; changed_at: string | null }[]>(
      `/deals/price-drops?days=${days}`
    ),
  listWatches: () => request<DealWatch[]>('/deals/watches'),
  createWatch: (data: DealWatchInput) =>
    request<DealWatch>('/deals/watches', { method: 'POST', body: JSON.stringify(data) }),
  updateWatch: (id: number, data: Partial<DealWatchInput>) =>
    request<DealWatch>(`/deals/watches/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteWatch: (id: number) =>
    request<{ ok: true }>(`/deals/watches/${id}`, { method: 'DELETE' }),
  runWatch: (id: number) =>
    request<DealWatch>(`/deals/watches/${id}/run`, { method: 'POST' }),
  prune: (days = 10) => request<{ archived: number; days: number }>(`/deals/prune?days=${days}`, { method: 'POST' }),
  results: (watch_id: number, opts?: { status?: string; include_unmatched?: boolean; include_gone?: boolean; include_failed?: boolean }) => {
    const qs = new URLSearchParams({ watch_id: String(watch_id) });
    if (opts?.status) qs.set('status', opts.status);
    if (opts?.include_unmatched) qs.set('include_unmatched', 'true');
    if (opts?.include_gone) qs.set('include_gone', 'true');
    if (opts?.include_failed) qs.set('include_failed', 'true');
    return request<DealResult[]>(`/deals/results?${qs}`);
  },
  patchResult: (id: number, status: string) =>
    request<DealResult>(`/deals/results/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  markSeen: (watch_id: number) =>
    request<{ ok: true }>(`/deals/results/mark-seen?watch_id=${watch_id}`, { method: 'POST' }),
  summary: () => request<{
    new_count: number;
    watch_count: number;
    ai: { rate_limited: boolean; seconds_ago: number | null; message: string };
  }>('/deals/summary'),
  aiCheck: () => request<{ rate_limited: boolean; seconds_ago: number | null; message: string }>(
    '/deals/ai-check', { method: 'POST' }),
};

// ── Stories (histórias explicadas pela IA) ──────────────────────

export type StoryLevel = 'simple' | 'medium' | 'long';

export interface StorySource {
  title: string;
  url: string;
}

export interface StoryVersion {
  level: StoryLevel;
  body: string;
  sources: StorySource[];
  created_at: string;
}

export interface Story {
  id: number;
  query: string;
  title: string;
  last_level: StoryLevel;
  created_at: string;
  versions: StoryVersion[];
}

export interface StoryListItem {
  id: number;
  query: string;
  title: string;
  last_level: StoryLevel;
  created_at: string;
  levels: StoryLevel[];
  snippet: string;
}

export interface StorySuggestion {
  id: number;
  story_id: number | null;   // null = sugestão geral; senão, relacionada com essa história
  query: string;
  title: string;
  reason: string;
  category: string;
}

export const storiesApi = {
  list: () => request<StoryListItem[]>('/stories'),
  get: (id: number) => request<Story>(`/stories/${id}`),
  create: (data: { query: string; level: StoryLevel; suggestion_id?: number }) =>
    request<Story>('/stories', { method: 'POST', body: JSON.stringify(data) }),
  setLevel: (id: number, level: StoryLevel) =>
    request<StoryVersion>(`/stories/${id}/level`, { method: 'POST', body: JSON.stringify({ level }) }),
  remove: (id: number) => request<{ ok: true }>(`/stories/${id}`, { method: 'DELETE' }),
  suggestions: (storyId?: number) =>
    request<StorySuggestion[]>(`/stories/suggestions${storyId ? `?story_id=${storyId}` : ''}`),
  refreshSuggestions: (storyId?: number) =>
    request<StorySuggestion[]>('/stories/suggestions/refresh', {
      method: 'POST', body: JSON.stringify({ story_id: storyId ?? null }),
    }),
  dismissSuggestion: (id: number) =>
    request<{ ok: true }>(`/stories/suggestions/${id}/dismiss`, { method: 'POST' }),
};

// ── Spotify Curator ─────────────────────────────────────────────

export interface SpotifyPlaylist {
  id: number;
  name: string;
  vibe: string;
  is_favorites: boolean;
  track_count: number;
  analyzed_at: string | null;
  created_at: string;
}

export interface SpotifyTrack {
  id: number;
  position: number;
  title: string;
  artist: string;
  album: string;
  spotify_url: string;
}

export interface SpotifyAnalysis {
  summary: string;
  intruders: { track_id: number; title: string; artist: string; reason: string }[];
  additions: { title: string; artist: string; reason: string; search_url: string }[];
  analyzed_at: string | null;
}

export interface SpotifyOverview {
  summary: string;
  groups: { name: string; playlist_name: string; mood: string; tracks: { title: string; artist: string; from: string }[] }[];
  relocations: { title: string; artist: string; from: string; to: string; reason: string }[];
  duplicates: { title: string; artist: string; count: number; playlist: string }[];
  playlist_count: number;
  track_count: number;
  truncated: boolean;
  analyzed_at: string | null;
}

export interface SpotifySearchResult {
  title: string;
  artist: string;
  album: string;
  search_url: string;
}

export interface SpotifyPlacement {
  playlist_id: number;
  playlist_name: string;
  reason: string;
}

export interface SpotifySuggestion {
  id: number;
  title: string;
  artist: string;
  reason: string;
  accepted: boolean;
  search_url: string;
}

export interface SpotifyListening {
  days: number;
  since: string;
  plays: number;
  total_seconds: number;
  artists: { artist: string; seconds: number; plays: number }[];
  tracks: { track: string; artist: string; seconds: number; plays: number }[];
  by_hour: { hour: number; seconds: number }[];
  by_activity: { category: string; seconds: number }[];
}

export const spotifyApi = {
  listeningStats: (days = 30) => request<SpotifyListening>(`/spotify/listening-stats?days=${days}`),
  history: (days = 7, limit = 60) =>
    request<{ id: number; track: string; artist: string; album: string; date: string; started_at: string; seconds: number; track_seconds: number | null }[]>(
      `/spotify/history?days=${days}&limit=${limit}`
    ),
  list: () => request<SpotifyPlaylist[]>('/spotify/playlists'),
  create: (data: { name: string; vibe?: string; is_favorites?: boolean }) =>
    request<SpotifyPlaylist>('/spotify/playlists', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: { name?: string; vibe?: string; is_favorites?: boolean }) =>
    request<SpotifyPlaylist>(`/spotify/playlists/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  remove: (id: number) => request<{ ok: true }>(`/spotify/playlists/${id}`, { method: 'DELETE' }),
  tracks: (id: number) => request<SpotifyTrack[]>(`/spotify/playlists/${id}/tracks`),
  import: (id: number, text: string, mode: 'replace' | 'append' = 'replace') =>
    request<{ imported: number; total: number }>(`/spotify/playlists/${id}/import`, {
      method: 'POST', body: JSON.stringify({ text, mode }),
    }),
  importLink: (url: string) =>
    request<{ playlist: SpotifyPlaylist; imported: number }>('/spotify/import-link', {
      method: 'POST', body: JSON.stringify({ url }),
    }),
  removeTrack: (trackId: number) => request<{ ok: true }>(`/spotify/tracks/${trackId}`, { method: 'DELETE' }),
  analysis: (id: number) => request<SpotifyAnalysis>(`/spotify/playlists/${id}/analysis`),
  analyze: (id: number) => request<SpotifyAnalysis>(`/spotify/playlists/${id}/analyze`, { method: 'POST' }),
  overview: () => request<SpotifyOverview>('/spotify/overview'),
  analyzeOverview: () => request<SpotifyOverview>('/spotify/overview/analyze', { method: 'POST' }),
  suggestions: (id: number) => request<SpotifySuggestion[]>(`/spotify/playlists/${id}/suggestions`),
  toggleSuggestion: (sid: number) => request<SpotifySuggestion>(`/spotify/suggestions/${sid}/toggle`, { method: 'POST' }),
  groupSuggestions: () => request<Record<string, SpotifySuggestion[]>>('/spotify/overview/group-suggestions'),
  dedupe: () => request<{ removed: number }>('/spotify/dedupe', { method: 'POST' }),
  search: (q: string) => request<SpotifySearchResult[]>(`/spotify/search?q=${encodeURIComponent(q)}`),
  place: (title: string, artist: string) =>
    request<SpotifyPlacement[]>('/spotify/place', { method: 'POST', body: JSON.stringify({ title, artist }) }),
  addTrack: (id: number, data: { title: string; artist?: string; album?: string; spotify_url?: string }) =>
    request<{ ok: boolean; already: boolean; total: number }>(`/spotify/playlists/${id}/add-track`, {
      method: 'POST', body: JSON.stringify(data),
    }),
};

// ── Day Planner ─────────────────────────────────────────────────

export type DayWindow = 'any' | 'produtivo' | 'morning' | 'afternoon' | 'evening' | 'before_lunch' | 'after_lunch';

export interface ProductiveHours {
  enough: boolean;
  days: number;
  needed_days?: number;
  total_seconds?: number;
  hours: { hour: number; seconds: number; share: number; top: boolean }[];
  top: number[];
  window: { start: string; end: string } | null;
}

export interface DayActivity {
  id: number;
  name: string;
  icon: string;
  color: string;
  duration_min: number;
  duration_max: number | null;
  window: DayWindow;
  fixed_time: string | null;
  priority: number;
  splittable: boolean;
  chunk_max: number | null;
  enabled: boolean;
  position: number;
}

export interface PlanBlock {
  activity_id: number | null;
  name: string;
  icon: string;
  color: string;
  start: string;
  end: string;
  note: string;
  done: boolean;
}

export interface DayPlan {
  mode: string;
  wake_time: string;
  blocks: PlanBlock[];
  unplaced: string[];
  advice: string;
  plan_date: string | null;
  day_end: string | null;
  preferences: string;
}

export interface DayPlanSummary {
  plan_date: string;
  wake_time: string;
  mode: string;
  block_count: number;
}

export interface PlanReality {
  date: string;
  tracked: boolean;
  blocks: {
    index: number; name: string; icon: string; color: string; start: string; end: string;
    planned_min: number; actual_min: number | null; pct: number | null;
    away_from_pc: boolean; screen_min: number; unknown: boolean;
    top: { category: string; minutes: number }[];
  }[];
  summary: {
    planned_min: number; actual_min: number; pct: number; kept: number; total: number;
    unknown: number; unknown_min: number;
    worst: { name: string; start: string; end: string; pct: number; planned_min: number }[];
  } | null;
}

export interface RecurringBlocks {
  days: number;
  plans: number;
  blocks: {
    name: string; icon: string; planned: number; done: number; unknown: number;
    planned_min: number; actual_min: number; rate: number | null;
  }[];
}

export const dayPlannerApi = {
  // O plano fecha-se sozinho com o que o tracker viu.
  close: (planDate: string) =>
    request<{ date: string; closed: number; tracked: boolean; pct?: number }>(
      `/day-planner/plans/${planDate}/close`, { method: 'POST' }),
  recurring: (days = 30) => request<RecurringBlocks>(`/day-planner/recurring?days=${days}`),
  reality: (planDate: string) => request<PlanReality>(`/day-planner/plans/${planDate}/reality`),
  productiveHours: () => request<ProductiveHours>('/day-planner/productive-hours'),
  list: () => request<DayActivity[]>('/day-planner/activities'),
  create: (data: Partial<DayActivity>) =>
    request<DayActivity>('/day-planner/activities', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: Partial<DayActivity>) =>
    request<DayActivity>(`/day-planner/activities/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  remove: (id: number) => request<{ ok: true }>(`/day-planner/activities/${id}`, { method: 'DELETE' }),
  // As horas do dia dele vêm do relógio; o planeador já não as pergunta.
  dayBounds: () => request<{ wake_time: string; day_end: string | null; wake_source: string; measured_today: boolean }>(
    '/day-planner/day-bounds'),
  plan: (data: { wake_time?: string; mode: 'local' | 'ai'; day_end?: string; activity_ids?: number[]; preferences?: string; plan_date?: string }) =>
    request<DayPlan>('/day-planner/plan', { method: 'POST', body: JSON.stringify(data) }),
  // Garante que hoje já tem plano (chamado uma vez por dia pela app).
  ensureToday: () =>
    request<{ created: boolean; reason: string; plan_date: string; plan: DayPlan | null }>(
      '/day-planner/ensure-today', { method: 'POST' }
    ),
  history: () => request<DayPlanSummary[]>('/day-planner/plans'),
  getPlan: (date: string) => request<DayPlan>(`/day-planner/plans/${date}`),
  deletePlan: (date: string) => request<{ ok: true }>(`/day-planner/plans/${date}`, { method: 'DELETE' }),
  addBlock: (date: string, data: { name: string; icon?: string; color?: string; start: string; end: string; note?: string }) =>
    request<DayPlan>(`/day-planner/plans/${date}/blocks`, { method: 'POST', body: JSON.stringify(data) }),
  toggleBlock: (date: string, index: number) =>
    request<DayPlan>(`/day-planner/plans/${date}/blocks/${index}/toggle`, { method: 'POST' }),
  updateBlock: (date: string, index: number, data: { name?: string; start?: string; end?: string; note?: string }) =>
    request<DayPlan>(`/day-planner/plans/${date}/blocks/${index}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteBlock: (date: string, index: number) =>
    request<DayPlan>(`/day-planner/plans/${date}/blocks/${index}`, { method: 'DELETE' }),
  reorderBlock: (date: string, index: number, newIndex: number) =>
    request<DayPlan>(`/day-planner/plans/${date}/blocks/${index}/reorder/${newIndex}`, { method: 'POST' }),
};

// ── Pesquisa global ──────────────────────────────────────────────

export interface SearchHit {
  type: string;
  icon: string;
  title: string;
  subtitle: string;
  url: string;
}

export const quickApi = {
  capture: (text: string, kind?: string) =>
    request<{ ok: boolean; kind: string; id?: number; summary: string }>('/quick/capture', {
      method: 'POST',
      body: JSON.stringify({ text, ...(kind ? { kind } : {}) }),
    }),
};

export interface DayTimelineItem {
  kind: 'sleep' | 'plan' | 'screen' | 'game' | 'expense' | 'event' | 'task' | 'music';
  start: string;
  end?: string;
  text?: string;
  detail?: string | null;
  app?: string;
  category?: string;
  seconds?: number;
  titles?: string[];
  done?: boolean;
  won?: boolean;
  no_time?: boolean;
}

export interface DaySummary {
  date: string;
  prev: string;
  next: string;
  timeline: DayTimelineItem[];
  summary: {
    sleep_hours: number | null; bedtime: string | null; wake_time: string | null;
    code_seconds: number; top_projects: { name: string; seconds: number }[];
    screen_seconds: number; games: number; wins: number; spent: number; notes: number;
    music_seconds: number; mood: number | null; mood_note: string | null;
    journal: string | null; trip: string | null; plan_blocks: number;
  };
}

export const dayApi = {
  get: (date: string) => request<DaySummary>(`/day/${date}`),
};

export const seguranca = {
  exposicao: () => request<{
    auth_required: boolean;
    listening: Record<string, string[]>;
    open_to_network: boolean;
    local_ip: string;
    risk: boolean;
    hint: string;
  }>('/quick/exposure'),
};

export const pushApi = {
  key: () => request<{ public_key: string }>('/push/key'),
  devices: () => request<{ id: number; label: string; active: boolean; created_at: string | null; last_sent_at: string | null; last_error: string }[]>('/push/devices'),
  subscribe: (subscription: any, label: string) =>
    request<{ ok: boolean; id: number; novo: boolean }>('/push/subscribe', {
      method: 'POST', body: JSON.stringify({ subscription, label }),
    }),
  remove: (id: number) => request<{ ok: boolean }>(`/push/devices/${id}`, { method: 'DELETE' }),
  test: () => request<{ sent: number; failed: number }>('/push/test', { method: 'POST' }),
};

export interface Scorecard {
  days: number;
  measured: number;
  total: number;
  cards: {
    area: string; icon: string; title: string; enough: boolean;
    n?: number; hit_rate?: number; detail?: string; verdict?: string; note?: string; url?: string;
    breakdown?: { label: string; n: number; hit_rate: number; promised?: number }[];
  }[];
}

export const scorecardApi = {
  get: (days = 90) => request<Scorecard>(`/scorecard/?days=${days}`),
};

export const searchApi = {
  query: (q: string, limit = 8) =>
    request<{ query: string; count: number; results: SearchHit[] }>(
      `/search/?q=${encodeURIComponent(q)}&limit=${limit}`
    ),
};

// ── Saúde dos dados e trabalhos automáticos ──────────────────────

export interface BackupFile {
  name: string;
  path: string;
  bytes: number;
  mb: number;
  created_at: string;
}

export interface OffsiteBackupState {
  enabled: boolean;
  dir: string;
  has_passphrase: boolean;
  count: number;
  last: BackupFile | null;
  hours_ago: number | null;
  stale: boolean;
  backups: BackupFile[];
}

export interface BackupState {
  dir: string;
  count: number;
  keep_days: number;
  total_mb: number;
  last: BackupFile | null;
  hours_ago: number | null;
  stale: boolean;
  backups: BackupFile[];
  offsite: OffsiteBackupState;
}

export interface DataHealth {
  checked_at: string;
  ok: boolean;
  problems: string[];
  sources: { key: string; label: string; last: string | null; hours_ago: number | null; days_ago: number | null; limit_hours: number; stale: boolean }[];
  jobs: { name: string; label: string; schedule: string; last_run: string | null; hours_ago: number | null; ok: boolean | null; detail: string; stale: boolean }[];
  backups: BackupState;
}

export const healthApi = {
  data: () => request<DataHealth>('/health/data'),
  runJob: (name: string) => request<{ name: string; ok: boolean; detail: string }>(`/jobs/${name}/run`, { method: 'POST' }),
  backups: () => request<BackupState>('/backups'),
  runBackup: () => request<{ ok: boolean; file: string; mb: number; source_mb: number }>('/backups/run', { method: 'POST' }),
};

// ── Perguntar aos próprios dados ─────────────────────────────────

export interface AskResult {
  question: string;
  title: string;
  sql: string;
  chart: 'table' | 'bar' | 'line';
  columns: string[];
  rows: any[][];
  row_count: number;
  answer: string;
}

export interface PinnedQuestion {
  id: number;
  question: string;
  title: string;
  chart: 'table' | 'bar' | 'line';
  sql: string;
  value: string | null;
  previous: string | null;
  columns: string[];
  rows: any[][];
  row_count: number;
  error: string | null;
}

export const askApi = {
  // `context` são as perguntas já feitas nesta conversa (com o SQL delas): é o
  // que deixa perguntar "e no mês passado?" sem repetir o assunto.
  ask: (question: string, context: { question: string; sql: string }[] = []) =>
    request<AskResult>('/ask/', { method: 'POST', body: JSON.stringify({ question, context }) }),
  examples: () => request<{ examples: string[] }>('/ask/examples'),
  pinned: () => request<PinnedQuestion[]>('/ask/pinned'),
  pin: (data: { question: string; title: string; sql: string; chart: string }) =>
    request<{ id: number; updated: boolean }>('/ask/pinned', { method: 'POST', body: JSON.stringify(data) }),
  unpin: (id: number) => request<{ ok: true }>(`/ask/pinned/${id}`, { method: 'DELETE' }),
};

// ── Alimentação ─────────────────────────────────────────────────

export interface MealSlotRow {
  id: number; key: string; name: string; start_time: string; end_time: string;
  notify: boolean; active: boolean; position: number;
}
export interface MealLogRow { id: number; eaten_at: string; description: string }
export interface SupplementRow {
  id: number; name: string; dose: string; time_hint: string | null;
  notify: boolean; active?: boolean; position?: number;
  taken_at?: string | null;
}
export interface SupplementScore {
  days: { date: string; score: number | null; taken: number; total: number }[];
  avg_7: number | null; streak: number; good_day: number;
}
export interface MealDay {
  date: string; score: number | null; decided: number; total: number; tracked: boolean;
  supplements: SupplementRow[];
  supplements_score: { score: number | null; taken: number; total: number };
  slots: {
    key: string; name: string; start_time: string; end_time: string; notify: boolean;
    state: 'feito' | 'fora' | 'falhado' | 'aberto' | 'por_vir';
    log: MealLogRow | null;
  }[];
  snacks: MealLogRow[];
}
export interface MealScore {
  days: { date: string; score: number | null; decided: number; total: number }[];
  avg_7: number | null; streak: number; good_day: number;
}

export const mealsApi = {
  slots: () => request<MealSlotRow[]>('/meals/slots'),
  createSlot: (data: { name: string; start_time: string; end_time: string; notify?: boolean }) =>
    request<{ id: number; key: string }>('/meals/slots', { method: 'POST', body: JSON.stringify(data) }),
  updateSlot: (id: number, data: { name: string; start_time: string; end_time: string; notify: boolean; active: boolean }) =>
    request<any>(`/meals/slots/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteSlot: (id: number) => request<any>(`/meals/slots/${id}`, { method: 'DELETE' }),

  day: (date?: string) => request<MealDay>(`/meals/day${date ? `?data=${date}` : ''}`),
  log: (data: { slot_key?: string | null; description?: string; eaten_at?: string; date?: string }) =>
    request<{ id: number; updated: boolean }>('/meals/log', { method: 'POST', body: JSON.stringify(data) }),
  updateLog: (id: number, data: { description?: string; eaten_at?: string }) =>
    request<any>(`/meals/log/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteLog: (id: number) => request<any>(`/meals/log/${id}`, { method: 'DELETE' }),

  // o que ele já escreveu para aquela refeição, do mais repetido para o menos
  suggestions: (slotKey?: string | null) =>
    request<{ text: string; times: number }[]>(`/meals/suggestions?slot_key=${slotKey ?? ''}`),
  score: (days = 30) => request<MealScore>(`/meals/score?days=${days}`),

  // Suplementos: a lista é dele — proteína e creatina são só o que vem proposto
  supplements: () => request<SupplementRow[]>('/meals/supplements'),
  createSupplement: (data: { name: string; dose?: string; time_hint?: string | null; notify?: boolean }) =>
    request<{ id: number }>('/meals/supplements', { method: 'POST', body: JSON.stringify(data) }),
  updateSupplement: (id: number, data: { name: string; dose: string; time_hint: string | null; notify: boolean; active: boolean }) =>
    request<any>(`/meals/supplements/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteSupplement: (id: number) => request<any>(`/meals/supplements/${id}`, { method: 'DELETE' }),
  takeSupplement: (id: number, taken: boolean, date?: string) =>
    request<any>(`/meals/supplements/${id}/take`, { method: 'POST', body: JSON.stringify({ taken, date }) }),
  // score próprio: anda ao lado do das refeições, não dentro dele
  supplementsScore: (days = 30) => request<SupplementScore>(`/meals/supplements/score?days=${days}`),
};

// Saídas à noite. `date` é o dia em que a noite começou (sábado à noite = sábado).
// 1 pouco, 2 médio, 3 muito. Null nas noites antigas, marcadas antes de haver nível.
export type DrinkLevel = 1 | 2 | 3;
export interface NightOut { date: string; went_out: boolean; drank: boolean; drink_level: DrinkLevel | null }
export interface NightOutDay extends NightOut {
  // gastos na Noite entre as 18h desse dia e as 6h do seguinte — pista, não prova
  evidence: { description: string; amount: number; date: string; time: string | null }[];
}
export interface NightOutEffect {
  days: number; drank: number; home: number; sober_out: number; min: number;
  rows: { key: string; name: string; unit: string; drank: string; home: string; worse: boolean; p: number | null }[];
}

export const nightsApi = {
  list: (days = 90) => request<NightOut[]>(`/nights?days=${days}`),
  get: (date: string) => request<NightOutDay>(`/nights/${date}`),
  set: (date: string, drank: boolean, level: DrinkLevel | null = null) =>
    request<NightOutDay>(`/nights/${date}`, { method: 'PUT', body: JSON.stringify({ drank, level }) }),
  clear: (date: string) => request<NightOutDay>(`/nights/${date}`, { method: 'DELETE' }),
  effect: (days = 365) => request<NightOutEffect>(`/nights/effect?days=${days}`),
};
