const BASE = '/api';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
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
  appleCalendars: () => request<{ calendars: string[] }>('/events/apple-calendars'),
  importAppleCalendar: (data: { calendars: string[]; days_back?: number; days_forward?: number }) =>
    request<{ imported: number; skipped: number; errors: number }>('/events/import-apple-calendar', { method: 'POST', body: JSON.stringify(data) }),
  exportAppleCalendar: (data?: { calendars?: string[]; days_back?: number; days_forward?: number }) =>
    request<{ exported: number; skipped: number; errors: number }>('/events/export-apple-calendar', { method: 'POST', body: JSON.stringify(data || {}) }),
};

// ── Expenses ────────────────────────────────────────────────────

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
  getIncome: (month: number, year: number) =>
    request<{ amount: number }>(`/expenses/income?month=${month}&year=${year}`),
  setIncome: (month: number, year: number, amount: number) =>
    request<{ amount: number }>(`/expenses/income?month=${month}&year=${year}&amount=${amount}`, { method: 'PUT' }),
};

// ── LoL Games ───────────────────────────────────────────────────

export const lolApi = {
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
  getMastery: (top?: number) => request<any[]>(`/lol/riot/mastery${top ? `?top=${top}` : ''}`),
  getTimeline: (matchId: string) => request<any>(`/lol/riot/timeline/${matchId}`),
  getSummoner: () => request<any>('/lol/riot/summoner'),
  getPosition: () => request<any>('/lol/riot/position'),
  getPeak: () => request<any>('/lol/riot/peak'),
  getReplays: () => request<any[]>('/lol/riot/replays'),
  // Champ Select
  getChampSelectStatus: () => request<any>('/lol/champ-select/status'),
  getChampSelectSession: () => request<any>('/lol/champ-select/session'),
  getMetaStats: (source?: string) => request<any>('/lol/meta-stats' + (source && source !== 'all' ? `?source=${source}` : '')),
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
};

// ── Trips ───────────────────────────────────────────────────────

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
  getItems: (listId: number) => request<any[]>(`/lists/${listId}/items`),
  addItem: (listId: number, data: { text: string; notes?: string; due_date?: string | null; due_time?: string | null; priority?: number }) =>
    request<any>(`/lists/${listId}/items`, { method: 'POST', body: JSON.stringify(data) }),
  updateItem: (itemId: number, data: { text?: string; checked?: boolean; position?: number; notes?: string; due_date?: string | null; due_time?: string | null; priority?: number }) =>
    request<any>(`/lists/items/${itemId}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteItem: (itemId: number) => request<any>(`/lists/items/${itemId}`, { method: 'DELETE' }),
  getReminders: (params?: { start_date?: string; end_date?: string }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    return request<any[]>(`/lists/reminders?${qs}`);
  },
  pendingItems: () => request<any[]>('/lists/items/pending'),
};

// ── Sleep ────────────────────────────────────────────────────────

export const sleepApi = {
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
  list: (params?: { folder_id?: number; search?: string }) => {
    const qs = new URLSearchParams();
    if (params?.folder_id != null) qs.set('folder_id', String(params.folder_id));
    if (params?.search) qs.set('search', params.search);
    return request<any[]>(`/notes/?${qs}`);
  },
  get: (id: number) => request<any>(`/notes/${id}`),
  create: (data: { title?: string; content?: string; folder_id?: number | null; pinned?: boolean; color?: string }) =>
    request<any>('/notes/', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: { title?: string; content?: string; folder_id?: number | null; pinned?: boolean; color?: string }) =>
    request<any>(`/notes/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: number) => request<any>(`/notes/${id}`, { method: 'DELETE' }),
};

// ── Investments ──────────────────────────────────────────────────

export const investmentsApi = {
  positions: () => request<any[]>('/investments/positions'),
  trades: () => request<any[]>('/investments/trades'),
  transactions: () => request<any[]>('/investments/transactions'),
  summary: () => request<any>('/investments/summary'),
  importPDF: (file: File) => {
    const form = new FormData();
    form.append('file', file);
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
};

// ── Dashboard / Weekly Review ───────────────────────────────────

export const dashboardApi = {
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
  create: (data: { date: string; mood: number; note?: string; tags?: string }) =>
    request<any>('/mood/', { method: 'POST', body: JSON.stringify(data) }),
  delete: (id: number) => request<any>(`/mood/${id}`, { method: 'DELETE' }),
  today: () => request<any>('/mood/today'),
  journal: (params?: { start_date?: string; end_date?: string }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    return request<any[]>(`/mood/journal?${qs}`);
  },
  saveJournal: (data: { date: string; content: string }) =>
    request<any>('/mood/journal', { method: 'POST', body: JSON.stringify(data) }),
  deleteJournal: (id: number) => request<any>(`/mood/journal/${id}`, { method: 'DELETE' }),
};

// ── Budgets & Subscriptions ─────────────────────────────────────

export const budgetsApi = {
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
  device_id: string;
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

export const screenTimeApi = {
  health: () => request<{ available: boolean; reason: string; db_path: string }>('/screen-time/health'),
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
  byApp: (params?: { start_date?: string; end_date?: string; device_id?: string }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    if (params?.device_id) qs.set('device_id', params.device_id);
    return request<ScreenTimeAppRow[]>(`/screen-time/by-app?${qs}`);
  },
  byDevice: (params?: { start_date?: string; end_date?: string }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    return request<ScreenTimeDeviceRow[]>(`/screen-time/by-device?${qs}`);
  },
};

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
  projectsWithTodos: () =>
    request<{ path: string; name: string }[]>(`/code-activity/projects-with-todos`),
  listTodos: (projectPath: string) =>
    request<CodeProjectTodo[]>(`/code-activity/projects/${encodeURIComponent(projectPath)}/todos`),
  createTodo: (projectPath: string, content: string) =>
    request<CodeProjectTodo>(`/code-activity/projects/${encodeURIComponent(projectPath)}/todos`, {
      method: 'POST', body: JSON.stringify({ content }),
    }),
  updateTodo: (id: number, patch: { content?: string; done?: boolean }) =>
    request<CodeProjectTodo>(`/code-activity/todos/${id}`, {
      method: 'PATCH', body: JSON.stringify(patch),
    }),
  deleteTodo: (id: number) =>
    request<{ deleted: number }>(`/code-activity/todos/${id}`, { method: 'DELETE' }),
  listNotes: (projectPath: string) =>
    request<CodeProjectNote[]>(`/code-activity/projects/${encodeURIComponent(projectPath)}/notes`),
  createNote: (projectPath: string, content: string, noteDate?: string) =>
    request<CodeProjectNote>(`/code-activity/projects/${encodeURIComponent(projectPath)}/notes`, {
      method: 'POST', body: JSON.stringify({ content, note_date: noteDate || null }),
    }),
  generateNote: (projectPath: string, date: string) =>
    request<CodeProjectNote>(
      `/code-activity/projects/${encodeURIComponent(projectPath)}/notes/generate?date=${date}`,
      { method: 'POST' }
    ),
  deleteNote: (id: number) =>
    request<{ deleted: number }>(`/code-activity/notes/${id}`, { method: 'DELETE' }),
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
