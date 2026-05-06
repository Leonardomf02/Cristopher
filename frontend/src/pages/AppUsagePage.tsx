import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  format, addDays, subDays, parseISO, startOfWeek, endOfWeek, eachDayOfInterval,
  addWeeks, subWeeks, addMonths, subMonths, startOfMonth, endOfMonth,
  addYears, subYears, startOfYear, endOfYear, isToday,
} from 'date-fns';
import { pt } from 'date-fns/locale';
import {
  ChevronLeft, ChevronRight, ArrowLeft, Monitor, Trash2, RefreshCw,
  Flame, Timer, TrendingUp, Settings, Download, X, Plus,
  Brain, Target,
} from 'lucide-react';
import {
  appUsageApi, AppUsageSession, AppUsageFullSummary,
  FlowOverlap, WeeklyTrend,
} from '../api';
import { InsightsTab, GoalsTab, DistractionToast } from './AppUsageInsights';

type ViewMode = 'day' | 'week' | 'month' | 'year';
type Tab = 'timeline' | 'heatmap' | 'flow' | 'trend' | 'insights' | 'goals';
type TimelineDisplay = 'clean' | 'categories';
type TimelineRange = 'auto' | 'full';

const CATEGORY_LABELS: Record<string, string> = {
  productivity: 'Produtividade',
  development: 'Desenvolvimento',
  communication: 'Comunicação',
  social: 'Social',
  gaming: 'Gaming',
  entertainment: 'Entretenimento',
  system: 'Sistema',
  browser: 'Browser',
  other: 'Outros',
};
const HOUR_HEIGHT = 44;
const MERGE_GAP_SECONDS = 120;

function colorForApp(name: string): string {
  const palette = [
    '#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6',
    '#EC4899', '#14B8A6', '#F97316', '#6366F1', '#22C55E',
    '#06B6D4', '#A855F7', '#EAB308', '#D946EF',
  ];
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) | 0;
  return palette[Math.abs(h) % palette.length];
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem ? `${h}h ${rem}m` : `${h}h`;
}

export default function AppUsagePage() {
  const [viewMode, setViewMode] = useState<ViewMode>('day');
  const [tab, setTab] = useState<Tab>('timeline');
  const [anchor, setAnchor] = useState<Date>(new Date());

  const [sessions, setSessions] = useState<AppUsageSession[]>([]);
  const [summary, setSummary] = useState<AppUsageFullSummary | null>(null);
  const [status, setStatus] = useState<{ running: boolean; current_app: string | null } | null>(null);
  const [loading, setLoading] = useState(false);

  const [filterApp, setFilterApp] = useState<string | null>(null);
  const [filterCategory, setFilterCategory] = useState<string | null>(null);

  const [heatmap, setHeatmap] = useState<{ days: string[]; matrix: number[][] } | null>(null);
  const [flow, setFlow] = useState<FlowOverlap[]>([]);
  const [trend, setTrend] = useState<WeeklyTrend[]>([]);
  const [byTitle, setByTitle] = useState<{ window_title: string; total_seconds: number; session_count: number; percentage: number }[]>([]);

  const [showSettings, setShowSettings] = useState(false);
  const [timelineDisplay, setTimelineDisplay] = useState<TimelineDisplay>('clean');
  const [timelineRange, setTimelineRange] = useState<TimelineRange>('auto');

  const { startDate, endDate, days } = useMemo(() => {
    if (viewMode === 'day') return { startDate: anchor, endDate: anchor, days: [anchor] };
    if (viewMode === 'week') {
      const s = startOfWeek(anchor, { weekStartsOn: 1 });
      const e = endOfWeek(anchor, { weekStartsOn: 1 });
      return { startDate: s, endDate: e, days: eachDayOfInterval({ start: s, end: e }) };
    }
    if (viewMode === 'month') {
      const s = startOfMonth(anchor);
      const e = endOfMonth(anchor);
      return { startDate: s, endDate: e, days: eachDayOfInterval({ start: s, end: e }) };
    }
    const s = startOfYear(anchor);
    const e = endOfYear(anchor);
    return { startDate: s, endDate: e, days: eachDayOfInterval({ start: s, end: e }) };
  }, [anchor, viewMode]);

  const startStr = format(startDate, 'yyyy-MM-dd');
  const endStr = format(endDate, 'yyyy-MM-dd');

  async function load() {
    setLoading(true);
    try {
      const promises: any[] = [
        appUsageApi.summary({ start_date: startStr, end_date: endStr }),
        appUsageApi.status().catch(() => null),
      ];
      if (tab === 'timeline' && viewMode !== 'year' && viewMode !== 'month') {
        promises.push(appUsageApi.sessions({ start_date: startStr, end_date: endStr, min_seconds: 10 }));
      }
      if (tab === 'heatmap' || viewMode === 'month' || viewMode === 'year') {
        promises.push(appUsageApi.heatmap(startStr, endStr));
      }
      if (tab === 'flow') {
        promises.push(appUsageApi.flowOverlap({ start_date: startStr, end_date: endStr }));
      }
      if (tab === 'trend') {
        promises.push(appUsageApi.weeklyTrend(8));
      }

      const results = await Promise.all(promises);
      setSummary(results[0]);
      setStatus(results[1]);
      let idx = 2;
      if (tab === 'timeline' && viewMode !== 'year' && viewMode !== 'month') setSessions(results[idx++] || []);
      else setSessions([]);
      if (tab === 'heatmap' || viewMode === 'month' || viewMode === 'year') setHeatmap(results[idx++] || null);
      else setHeatmap(null);
      if (tab === 'flow') setFlow(results[idx++] || []);
      if (tab === 'trend') setTrend(results[idx++] || []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, [startStr, endStr, tab, viewMode]);

  useEffect(() => {
    if (filterApp) {
      appUsageApi.byTitle(filterApp, { start_date: startStr, end_date: endStr, limit: 20 }).then(setByTitle);
    } else {
      setByTitle([]);
    }
  }, [filterApp, startStr, endStr]);

  const filteredSessions = useMemo(() => {
    let out = sessions;
    if (filterApp) out = out.filter(s => s.app_name === filterApp);
    if (filterCategory) {
      const appsInCat = new Set(summary?.by_app.filter(a => a.category === filterCategory).map(a => a.app_name));
      out = out.filter(s => appsInCat.has(s.app_name));
    }
    return out;
  }, [sessions, filterApp, filterCategory, summary]);

  function nav(dir: -1 | 1) {
    const fn = {
      day: dir > 0 ? addDays : subDays,
      week: dir > 0 ? addWeeks : subWeeks,
      month: dir > 0 ? addMonths : subMonths,
      year: dir > 0 ? addYears : subYears,
    }[viewMode];
    setAnchor(fn(anchor, 1));
  }

  async function handleDelete(id: number) {
    if (!confirm('Apagar esta sessão?')) return;
    await appUsageApi.delete(id);
    load();
  }

  const headerLabel = useMemo(() => {
    if (viewMode === 'day') return format(anchor, "EEEE, d 'de' MMMM", { locale: pt });
    if (viewMode === 'week') return `${format(startDate, "d MMM", { locale: pt })} – ${format(endDate, "d MMM", { locale: pt })}`;
    if (viewMode === 'month') return format(anchor, "MMMM 'de' yyyy", { locale: pt });
    return format(anchor, 'yyyy');
  }, [anchor, viewMode, startDate, endDate]);

  const totalSeconds = summary?.total_seconds ?? 0;
  const avgPerDay = viewMode !== 'day' && days.length ? Math.round(totalSeconds / days.length) : null;

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <Link to="/calendar" className="p-2 rounded-lg hover:bg-white/5 text-gray-400 hover:text-white">
            <ArrowLeft size={20} />
          </Link>
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Monitor size={24} className="text-blue-400" />
              Uso de aplicações
            </h1>
            <p className="text-sm text-gray-500">Que janelas usaste, e quando</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {status && (
            <div className={`text-xs px-3 py-1.5 rounded-full border ${
              status.running
                ? 'border-green-500/40 bg-green-500/10 text-green-400'
                : 'border-red-500/40 bg-red-500/10 text-red-400'
            }`}>
              {status.running ? `Ativo${status.current_app ? ` · ${status.current_app}` : ''}` : 'Parado'}
            </div>
          )}
          <a
            href={appUsageApi.exportCsvUrl(startStr, endStr)}
            className="p-2 rounded-lg hover:bg-white/5 text-gray-400 hover:text-white"
            title="Exportar CSV"
          >
            <Download size={16} />
          </a>
          <button
            onClick={() => setShowSettings(true)}
            className="p-2 rounded-lg hover:bg-white/5 text-gray-400 hover:text-white"
            title="Definições"
          >
            <Settings size={16} />
          </button>
          <button onClick={load} className="p-2 rounded-lg hover:bg-white/5 text-gray-400 hover:text-white">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* Nav row */}
      <div className="flex items-center justify-between mb-4 bg-[#161616] border border-[#222] rounded-xl p-3 gap-3">
        <div className="flex bg-black/30 rounded-lg p-1">
          {(['day', 'week', 'month', 'year'] as ViewMode[]).map(m => (
            <button
              key={m}
              onClick={() => setViewMode(m)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                viewMode === m ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              {{ day: 'Dia', week: 'Semana', month: 'Mês', year: 'Ano' }[m]}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2 flex-1 justify-center">
          <button onClick={() => nav(-1)} className="p-2 rounded-lg hover:bg-white/5">
            <ChevronLeft size={18} />
          </button>
          <div className="text-center min-max-w-[90vw] w-[260px]">
            <div className="text-lg font-semibold capitalize">{headerLabel}</div>
            <button onClick={() => setAnchor(new Date())} className="text-xs text-blue-400 hover:text-blue-300">
              Hoje
            </button>
          </div>
          <button onClick={() => nav(1)} className="p-2 rounded-lg hover:bg-white/5">
            <ChevronRight size={18} />
          </button>
        </div>

        <div className="w-[84px]" />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b border-[#222] overflow-x-auto">
        {([
          { id: 'timeline', label: 'Timeline', icon: Monitor },
          { id: 'heatmap', label: 'Heatmap', icon: Flame },
          { id: 'flow', label: 'Flow', icon: Timer },
          { id: 'trend', label: 'Tendência', icon: TrendingUp },
          { id: 'insights', label: 'Insights', icon: Brain },
          { id: 'goals', label: 'Objetivos', icon: Target },
        ] as { id: Tab; label: string; icon: any }[]).map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`px-4 py-2 text-sm font-medium transition-colors flex items-center gap-1.5 border-b-2 -mb-px ${
              tab === id ? 'text-white border-blue-500' : 'text-gray-500 border-transparent hover:text-gray-300'
            }`}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {/* Summary cards — always visible */}
      <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <SummaryCard label="Total" value={formatDuration(totalSeconds)} />
        <SummaryCard
          label={viewMode === 'day' ? 'Sessões' : 'Média/dia'}
          value={viewMode === 'day' ? String(sessions.length) : avgPerDay != null ? formatDuration(avgPerDay) : '—'}
        />
        <SummaryCard label="Apps distintas" value={String(summary?.by_app.length ?? 0)} />
        <SummaryCard label="Mais usada" value={summary?.by_app[0]?.app_name || '—'} />
      </div>

      {/* Category pills */}
      {summary && summary.by_category.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-4">
          {summary.by_category.map(c => {
            const selected = filterCategory === c.category;
            return (
              <button
                key={c.category}
                onClick={() => setFilterCategory(selected ? null : c.category)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-all ${
                  selected ? 'bg-white/10 border-white/30' : 'border-transparent hover:bg-white/5'
                }`}
                style={{ color: c.color, borderColor: selected ? c.color : c.color + '40', backgroundColor: selected ? c.color + '20' : c.color + '10' }}
              >
                <span className="w-1.5 h-1.5 rounded-full inline-block mr-1.5" style={{ backgroundColor: c.color }} />
                {c.label} · {formatDuration(c.total_seconds)} · {c.percentage}%
              </button>
            );
          })}
        </div>
      )}

      {/* Tab content */}
      {tab === 'insights' ? (
        <InsightsTab startStr={startStr} endStr={endStr} />
      ) : tab === 'goals' ? (
        <GoalsTab />
      ) : (
        <div className="grid grid-cols-[1fr_320px] gap-6">
          <div className="min-w-0">
            {tab === 'timeline' && (
              <TimelineView
                days={days}
                viewMode={viewMode}
                sessions={filteredSessions}
                heatmap={heatmap}
                onDelete={handleDelete}
                summary={summary}
                display={timelineDisplay}
                onChangeDisplay={setTimelineDisplay}
                range={timelineRange}
                onChangeRange={setTimelineRange}
              />
            )}
            {tab === 'heatmap' && <HeatmapView heatmap={heatmap} />}
            {tab === 'flow' && <FlowView overlaps={flow} />}
            {tab === 'trend' && <TrendView trend={trend} />}
          </div>

          {/* Right sidebar: apps breakdown + optional titles */}
          <div className="space-y-4">
            <AppBreakdown
              summary={summary}
              filterApp={filterApp}
              onSelect={(name) => setFilterApp(filterApp === name ? null : name)}
            />
            {filterApp && byTitle.length > 0 && (
              <TitleBreakdown app={filterApp} rows={byTitle} />
            )}
          </div>
        </div>
      )}

      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}
      <DistractionToast />
    </div>
  );
}

// ── Summary card ──────────────────────────────────────────────────

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-[#161616] border border-[#222] rounded-xl p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">{label}</div>
      <div className="text-xl font-bold truncate">{value}</div>
    </div>
  );
}

// ── Timeline ──────────────────────────────────────────────────────

type TimelineBlock = {
  key: string;
  app_name: string;
  category: string;
  color: string;
  start: Date;
  end: Date;
  duration: number;
  ids: number[];
  count: number;
  titles: string[];
};

function buildAppMeta(summary: AppUsageFullSummary | null) {
  const map = new Map<string, { category: string; color: string }>();
  if (!summary) return map;
  const catColor = new Map<string, string>();
  for (const c of summary.by_category) catColor.set(c.category, c.color);
  for (const a of summary.by_app) {
    map.set(a.app_name, {
      category: a.category,
      color: catColor.get(a.category) || colorForApp(a.app_name),
    });
  }
  return map;
}

function mergeSessions(
  sessions: AppUsageSession[],
  appMeta: Map<string, { category: string; color: string }>,
): TimelineBlock[] {
  if (sessions.length === 0) return [];
  const sorted = [...sessions].sort(
    (a, b) => parseISO(a.start_time).getTime() - parseISO(b.start_time).getTime(),
  );
  const out: TimelineBlock[] = [];
  for (const s of sorted) {
    const start = parseISO(s.start_time);
    const end = parseISO(s.end_time);
    const meta = appMeta.get(s.app_name);
    const last = out[out.length - 1];
    if (
      last &&
      last.app_name === s.app_name &&
      (start.getTime() - last.end.getTime()) / 1000 <= MERGE_GAP_SECONDS
    ) {
      last.end = end > last.end ? end : last.end;
      last.duration = (last.end.getTime() - last.start.getTime()) / 1000;
      last.ids.push(s.id);
      last.count += 1;
      if (s.window_title && !last.titles.includes(s.window_title)) last.titles.push(s.window_title);
      continue;
    }
    out.push({
      key: `${s.app_name}-${s.id}`,
      app_name: s.app_name,
      category: meta?.category || 'other',
      color: meta?.color || colorForApp(s.app_name),
      start,
      end,
      duration: (end.getTime() - start.getTime()) / 1000,
      ids: [s.id],
      count: 1,
      titles: s.window_title ? [s.window_title] : [],
    });
  }
  return out;
}

function TimelineView({
  days, viewMode, sessions, heatmap, onDelete, summary, display, onChangeDisplay,
  range, onChangeRange,
}: {
  days: Date[]; viewMode: ViewMode;
  sessions: AppUsageSession[]; heatmap: { days: string[]; matrix: number[][] } | null;
  onDelete: (id: number) => void;
  summary: AppUsageFullSummary | null;
  display: TimelineDisplay;
  onChangeDisplay: (d: TimelineDisplay) => void;
  range: TimelineRange;
  onChangeRange: (r: TimelineRange) => void;
}) {
  // For month/year we show a calendar heatmap style (daily totals) instead of a 24h grid.
  if (viewMode === 'month' || viewMode === 'year') {
    return <CalendarHeatmap days={days} heatmap={heatmap} viewMode={viewMode} />;
  }

  const appMeta = useMemo(() => buildAppMeta(summary), [summary]);
  const categoryColor = useMemo(() => {
    const m = new Map<string, string>();
    summary?.by_category.forEach(c => m.set(c.category, c.color));
    return m;
  }, [summary]);
  const isCategories = display === 'categories';

  // Auto-zoom: trim leading/trailing hours with negligible activity. Density-based
  // so a single isolated session (e.g. Spotify at 3am) doesn't keep the full 24h range.
  const [startHour, endHour] = useMemo<[number, number]>(() => {
    if (range === 'full' || sessions.length === 0) return [0, 24];
    const hourSecs = new Array(24).fill(0);
    for (const s of sessions) {
      const start = parseISO(s.start_time);
      const end = parseISO(s.end_time);
      let cur = start.getTime();
      const endMs = end.getTime();
      while (cur < endMs) {
        const d = new Date(cur);
        const nextHour = new Date(d);
        nextHour.setMinutes(0, 0, 0);
        nextHour.setHours(d.getHours() + 1);
        const segEnd = Math.min(nextHour.getTime(), endMs);
        hourSecs[d.getHours()] += (segEnd - cur) / 1000;
        cur = segEnd;
      }
    }
    const total = hourSecs.reduce((a, b) => a + b, 0);
    if (total <= 0) return [0, 24];
    const threshold = total * 0.02;
    let sh = 0;
    while (sh < 24 && hourSecs[sh] <= threshold) sh++;
    let eh = 24;
    while (eh > sh && hourSecs[eh - 1] <= threshold) eh--;
    if (sh >= eh) return [0, 24];
    sh = Math.max(0, sh - 1);
    eh = Math.min(24, eh + 1);
    if (eh - sh < 4) return [Math.max(0, sh - 1), Math.min(24, eh + 1)];
    return [sh, eh];
  }, [sessions, range]);

  const visibleHours = endHour - startHour;
  const baseOffsetMin = startHour * 60;

  const displayLabels: Record<TimelineDisplay, { label: string; title: string }> = {
    clean: { label: 'Apps', title: 'Funde sessões adjacentes da mesma app e usa cor por categoria' },
    categories: { label: 'Categorias', title: 'Bins de 30 min coloridos pela categoria dominante de cada slot' },
  };
  const rangeLabels: Record<TimelineRange, { label: string; title: string }> = {
    auto: { label: 'Auto', title: 'Mostra apenas as horas com atividade' },
    full: { label: '24h', title: 'Mostra o dia inteiro (00:00–24:00)' },
  };

  return (
    <div className="bg-[#161616] border border-[#222] rounded-xl p-4">
      <div className="flex items-center justify-between mb-3 gap-2">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide">Timeline</h2>
        <div className="flex items-center gap-2">
          <div className="flex bg-black/30 rounded-lg p-0.5 text-[11px]">
            {(['auto', 'full'] as TimelineRange[]).map(r => (
              <button
                key={r}
                onClick={() => onChangeRange(r)}
                className={`px-2.5 py-1 rounded-md font-medium transition-all ${
                  range === r ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'
                }`}
                title={rangeLabels[r].title}
              >
                {rangeLabels[r].label}
              </button>
            ))}
          </div>
          <div className="flex bg-black/30 rounded-lg p-0.5 text-[11px]">
            {(['clean', 'categories'] as TimelineDisplay[]).map(d => (
              <button
                key={d}
                onClick={() => onChangeDisplay(d)}
                className={`px-2.5 py-1 rounded-md font-medium transition-all ${
                  display === d ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'
                }`}
                title={displayLabels[d].title}
              >
                {displayLabels[d].label}
              </button>
            ))}
          </div>
        </div>
      </div>
      {(() => {
        const ROW_HEIGHT = viewMode === 'day' ? 96 : 56;
        const LABEL_W = 72;
        const totalMinutes = visibleHours * 60;
        // Pick a tick step so we get ~6-12 hour labels regardless of zoom.
        const tickStep = visibleHours <= 8 ? 1 : visibleHours <= 16 ? 2 : 3;
        const ticks: number[] = [];
        for (let h = startHour; h <= endHour; h += tickStep) ticks.push(h);
        if (ticks[ticks.length - 1] !== endHour) ticks.push(endHour);

        return (
          <div>
            {/* Hour axis */}
            <div className="flex">
              <div style={{ width: LABEL_W }} />
              <div className="flex-1 relative h-5">
                {ticks.map(h => {
                  const left = ((h - startHour) / visibleHours) * 100;
                  return (
                    <span
                      key={h}
                      className="absolute text-[10px] text-gray-500 -translate-x-1/2"
                      style={{ left: `${left}%` }}
                    >
                      {h.toString().padStart(2, '0')}:00
                    </span>
                  );
                })}
              </div>
            </div>

            {/* Day rows */}
            <div className="space-y-1">
              {days.map(day => {
                const dayStr = format(day, 'yyyy-MM-dd');
                const dayFiltered = sessions.filter(s => s.date === dayStr);

                // Categories mode: use 30-min bins, dominant category fills each cell.
                // Drastically simpler to scan than per-session blocks.
                const BIN_MIN = 30;
                const numBins = Math.ceil((visibleHours * 60) / BIN_MIN);
                type Bin = { totalSec: number; byCat: Map<string, number>; byApp: Map<string, number>; ids: number[] };
                const bins: Bin[] = isCategories
                  ? Array.from({ length: numBins }, () => ({ totalSec: 0, byCat: new Map(), byApp: new Map(), ids: [] }))
                  : [];
                if (isCategories) {
                  for (const s of dayFiltered) {
                    const start = parseISO(s.start_time);
                    const end = parseISO(s.end_time);
                    const startMin = start.getHours() * 60 + start.getMinutes() - baseOffsetMin;
                    const endMin = startMin + s.duration_seconds / 60;
                    const cat = appMeta.get(s.app_name)?.category || 'other';
                    let cur = startMin;
                    while (cur < endMin) {
                      const binIdx = Math.floor(cur / BIN_MIN);
                      if (binIdx < 0 || binIdx >= numBins) { cur += BIN_MIN; continue; }
                      const binEnd = (binIdx + 1) * BIN_MIN;
                      const segSec = (Math.min(endMin, binEnd) - cur) * 60;
                      const bin = bins[binIdx];
                      bin.totalSec += segSec;
                      bin.byCat.set(cat, (bin.byCat.get(cat) || 0) + segSec);
                      bin.byApp.set(s.app_name, (bin.byApp.get(s.app_name) || 0) + segSec);
                      bin.ids.push(s.id);
                      cur = Math.min(endMin, binEnd);
                    }
                  }
                }

                const blocks: TimelineBlock[] = isCategories
                  ? []
                  : mergeSessions(dayFiltered, appMeta);
                const dayTotal = isCategories
                  ? bins.reduce((s, b) => s + b.totalSec, 0)
                  : blocks.reduce((s, b) => s + b.duration, 0);

                return (
                  <div key={dayStr} className="flex items-stretch">
                    <div
                      className={`shrink-0 pr-2 flex flex-col justify-center text-right ${isToday(day) ? 'text-blue-400' : 'text-gray-400'}`}
                      style={{ width: LABEL_W }}
                    >
                      <div className="text-[11px] font-medium leading-tight">
                        {viewMode === 'day' ? (
                          <>
                            <span className="capitalize">{format(day, 'EEEE', { locale: pt })}</span>
                            <span className="ml-1 text-gray-500">{format(day, "d 'de' MMM", { locale: pt })}</span>
                          </>
                        ) : (
                          <>
                            <span className="capitalize">{format(day, 'EEE', { locale: pt })}</span>
                            <span className="ml-1 text-gray-500">{format(day, 'd')}</span>
                          </>
                        )}
                      </div>
                      <div className="text-[10px] text-gray-600 leading-tight">{formatDuration(Math.round(dayTotal))}</div>
                    </div>

                    <div
                      className="relative flex-1 bg-[#0d0d0d] rounded-md overflow-hidden border border-[#1f1f1f]"
                      style={{ height: ROW_HEIGHT }}
                    >
                      {/* Vertical hour gridlines */}
                      {ticks.map(h => (
                        <div
                          key={h}
                          className="absolute top-0 bottom-0 border-l border-[#1a1a1a]"
                          style={{ left: `${((h - startHour) / visibleHours) * 100}%` }}
                        />
                      ))}

                      {isCategories && bins.map((bin, i) => {
                        if (bin.totalSec <= 0) return null;
                        let topCat = 'other';
                        let topSec = 0;
                        bin.byCat.forEach((sec, cat) => { if (sec > topSec) { topSec = sec; topCat = cat; } });
                        const color = categoryColor.get(topCat) || colorForApp(topCat);
                        const intensity = Math.min(1, bin.totalSec / (BIN_MIN * 60));
                        const left = (i * BIN_MIN / totalMinutes) * 100;
                        const width = (BIN_MIN / totalMinutes) * 100;
                        const slotStart = startHour * 60 + i * BIN_MIN;
                        const sh = Math.floor(slotStart / 60);
                        const sm = slotStart % 60;
                        const eh = Math.floor((slotStart + BIN_MIN) / 60);
                        const em = (slotStart + BIN_MIN) % 60;
                        const fmt = (h: number, m: number) => `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
                        const appsList = Array.from(bin.byApp.entries())
                          .sort((a, b) => b[1] - a[1])
                          .slice(0, 4)
                          .map(([n, s]) => `${n} (${formatDuration(Math.round(s))})`)
                          .join(', ');
                        const tooltip = [
                          `${fmt(sh, sm)}–${fmt(eh, em)}`,
                          `Categoria dominante: ${CATEGORY_LABELS[topCat] || topCat}`,
                          `Total: ${formatDuration(Math.round(bin.totalSec))} de ${BIN_MIN} min`,
                          `Apps: ${appsList}`,
                        ].join('\n');
                        return (
                          <div
                            key={`bin-${i}`}
                            className="absolute top-0 bottom-0 cursor-pointer"
                            style={{
                              left: `${left}%`,
                              width: `${width}%`,
                              backgroundColor: color,
                              opacity: 0.25 + intensity * 0.65,
                            }}
                            title={tooltip}
                            onClick={() => bin.ids.forEach(onDelete)}
                          />
                        );
                      })}
                      {!isCategories && blocks.map(b => {
                        const startMinutes = b.start.getHours() * 60 + b.start.getMinutes();
                        const endMinutesRaw = b.end.getHours() * 60 + b.end.getMinutes()
                          + (b.end.getDate() !== b.start.getDate() ? 24 * 60 : 0);
                        const fromMin = Math.max(0, startMinutes - baseOffsetMin);
                        const toMin = Math.min(totalMinutes, endMinutesRaw - baseOffsetMin);
                        if (toMin <= 0 || fromMin >= totalMinutes) return null;
                        const left = (fromMin / totalMinutes) * 100;
                        const width = Math.max(0.2, ((toMin - fromMin) / totalMinutes) * 100);
                        const color = b.color;
                        const titleSummary = b.titles.length === 0
                          ? ''
                          : b.titles.length === 1
                            ? b.titles[0]
                            : `${b.titles[0]} (+${b.titles.length - 1})`;
                        const tooltip = [
                          b.app_name,
                          titleSummary,
                          `${format(b.start, 'HH:mm')} – ${format(b.end, 'HH:mm')} (${formatDuration(Math.round(b.duration))})`,
                          b.count > 1 ? `${b.count} sessões` : '',
                        ].filter(Boolean).join('\n');
                        // Heuristic: show label only if block is wide enough.
                        const showLabel = width > 5;
                        return (
                          <div
                            key={b.key}
                            className="absolute top-0.5 bottom-0.5 rounded-sm overflow-hidden cursor-pointer group flex items-center px-1.5"
                            style={{
                              left: `${left}%`,
                              width: `${width}%`,
                              backgroundColor: color + '40',
                              borderLeft: `2px solid ${color}`,
                            }}
                            title={tooltip}
                            onClick={() => b.ids.forEach(onDelete)}
                          >
                            {showLabel && (
                              <span
                                className="text-[10px] font-medium truncate"
                                style={{ color }}
                              >
                                {b.app_name}
                              </span>
                            )}
                            <Trash2 size={10} className="absolute top-0.5 right-0.5 opacity-0 group-hover:opacity-100 text-red-400" />
                          </div>
                        );
                      })}

                      {/* "Now" indicator on today's row */}
                      {isToday(day) && (() => {
                        const now = new Date();
                        const nowMin = now.getHours() * 60 + now.getMinutes() - baseOffsetMin;
                        if (nowMin < 0 || nowMin > totalMinutes) return null;
                        return (
                          <div
                            className="absolute top-0 bottom-0 w-px bg-blue-400"
                            style={{ left: `${(nowMin / totalMinutes) * 100}%` }}
                          />
                        );
                      })()}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })()}
      {!isCategories && (
        <p className="text-[10px] text-gray-600 mt-2">
          Cor por categoria · sessões da mesma app a menos de {MERGE_GAP_SECONDS / 60} min foram fundidas. Clica num bloco para apagar.
        </p>
      )}
      {isCategories && (
        <p className="text-[10px] text-gray-600 mt-2">
          Cada célula = 30 min, cor = categoria dominante, opacidade = quanto desse slot foi usado. Passa o rato para ver as apps.
        </p>
      )}
    </div>
  );
}

// ── Month/year calendar heatmap ───────────────────────────────────

function CalendarHeatmap({
  days, heatmap, viewMode,
}: { days: Date[]; heatmap: { days: string[]; matrix: number[][] } | null; viewMode: ViewMode }) {
  const totals = new Map<string, number>();
  if (heatmap) {
    heatmap.days.forEach((d, i) => {
      totals.set(d, heatmap.matrix[i].reduce((a, b) => a + b, 0));
    });
  }
  const max = Math.max(1, ...Array.from(totals.values()));

  return (
    <div className="bg-[#161616] border border-[#222] rounded-xl p-4">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
        {viewMode === 'month' ? 'Mês (total por dia)' : 'Ano (total por dia)'}
      </h2>
      <div
        className="grid gap-1"
        style={{ gridTemplateColumns: viewMode === 'year' ? 'repeat(53, minmax(0, 1fr))' : 'repeat(7, minmax(0, 1fr))' }}
      >
        {days.map(d => {
          const key = format(d, 'yyyy-MM-dd');
          const sec = totals.get(key) ?? 0;
          const intensity = sec / max;
          const bg = sec === 0 ? '#1a1a1a' : `rgba(59, 130, 246, ${0.15 + intensity * 0.85})`;
          return (
            <div
              key={key}
              className="aspect-square rounded-sm relative group flex items-center justify-center"
              style={{ backgroundColor: bg }}
              title={`${format(d, 'yyyy-MM-dd')}: ${formatDuration(sec)}`}
            >
              {viewMode === 'month' && (
                <span className="text-[10px] text-white/70">{format(d, 'd')}</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Heatmap (day × hour) ──────────────────────────────────────────

function HeatmapView({ heatmap }: { heatmap: { days: string[]; matrix: number[][] } | null }) {
  if (!heatmap || heatmap.days.length === 0) {
    return <div className="bg-[#161616] border border-[#222] rounded-xl p-6 text-sm text-gray-500">Sem dados.</div>;
  }
  const max = Math.max(1, ...heatmap.matrix.flat());
  return (
    <div className="bg-[#161616] border border-[#222] rounded-xl p-4">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
        Intensidade hora × dia
      </h2>
      <div className="overflow-x-auto">
        <table className="text-[10px] text-gray-500">
          <thead>
            <tr>
              <th className="w-12 text-right pr-2"></th>
              {Array.from({ length: 24 }).map((_, h) => (
                <th key={h} className="w-5 text-center">{h % 3 === 0 ? h : ''}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {heatmap.days.map((d, i) => (
              <tr key={d}>
                <td className="text-right pr-2 text-gray-600 font-medium">
                  {format(parseISO(d), 'EEE d', { locale: pt })}
                </td>
                {heatmap.matrix[i].map((sec, h) => {
                  const intensity = sec / max;
                  const bg = sec === 0 ? '#1a1a1a' : `rgba(59, 130, 246, ${0.15 + intensity * 0.85})`;
                  return (
                    <td
                      key={h}
                      className="w-5 h-5 border border-[#0f0f0f]"
                      style={{ backgroundColor: bg }}
                      title={`${d} ${h}:00 — ${formatDuration(sec)}`}
                    />
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Flow overlap ──────────────────────────────────────────────────

function FlowView({ overlaps }: { overlaps: FlowOverlap[] }) {
  if (overlaps.length === 0) {
    return (
      <div className="bg-[#161616] border border-[#222] rounded-xl p-6 text-sm text-gray-500">
        Nenhuma sessão Flow neste período.
      </div>
    );
  }
  return (
    <div className="bg-[#161616] border border-[#222] rounded-xl p-4">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
        Durante sessões Flow
      </h2>
      <div className="space-y-3">
        {overlaps.map(f => (
          <div key={f.flow_id} className="p-3 rounded-lg border border-[#222] bg-black/20">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: f.flow_color }} />
                <span className="font-medium text-sm">{f.flow_name}</span>
                <span className="text-xs text-gray-500">
                  {format(parseISO(f.date), 'd MMM', { locale: pt })} · {f.start_time}–{f.end_time}
                </span>
              </div>
              <div className="text-xs text-gray-400">
                {formatDuration(f.tracked_seconds)} / {formatDuration(f.flow_duration_seconds)}
              </div>
            </div>
            <div className="flex flex-wrap gap-1 mb-2">
              {f.by_category.map(c => (
                <span
                  key={c.category}
                  className="text-[10px] px-2 py-0.5 rounded-full font-medium"
                  style={{ color: c.color, backgroundColor: c.color + '20' }}
                >
                  {c.label} {formatDuration(c.seconds)}
                </span>
              ))}
            </div>
            <div className="h-1.5 rounded-full bg-black/40 overflow-hidden flex">
              {f.by_category.map(c => (
                <div
                  key={c.category}
                  style={{
                    width: `${(c.seconds / f.flow_duration_seconds) * 100}%`,
                    backgroundColor: c.color,
                  }}
                />
              ))}
            </div>
            <div className="mt-2 text-[11px] text-gray-500 truncate">
              Top apps: {f.by_app.slice(0, 3).map(a => `${a.app_name} (${formatDuration(a.seconds)})`).join(' · ') || '—'}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Weekly trend ──────────────────────────────────────────────────

function TrendView({ trend }: { trend: WeeklyTrend[] }) {
  if (trend.length === 0) {
    return <div className="bg-[#161616] border border-[#222] rounded-xl p-6 text-sm text-gray-500">Sem dados.</div>;
  }
  const max = Math.max(1, ...trend.map(t => t.total_seconds));

  return (
    <div className="bg-[#161616] border border-[#222] rounded-xl p-4">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">
        Últimas {trend.length} semanas
      </h2>
      <div className="space-y-3">
        {trend.map((w, i) => {
          const prev = i > 0 ? trend[i - 1] : null;
          const delta = prev ? w.total_seconds - prev.total_seconds : 0;
          const deltaPct = prev && prev.total_seconds > 0 ? (delta / prev.total_seconds) * 100 : 0;
          return (
            <div key={w.start_date}>
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-gray-400 font-medium">{w.label}</span>
                <div className="flex items-center gap-2">
                  <span className="font-semibold">{formatDuration(w.total_seconds)}</span>
                  {prev && (
                    <span className={delta >= 0 ? 'text-green-400' : 'text-red-400'}>
                      {delta >= 0 ? '↑' : '↓'} {Math.abs(Math.round(deltaPct))}%
                    </span>
                  )}
                </div>
              </div>
              <div className="h-5 rounded bg-black/40 overflow-hidden flex" style={{ width: `${(w.total_seconds / max) * 100}%`, minWidth: '2%' }}>
                {w.by_category.map(c => (
                  <div
                    key={c.category}
                    style={{
                      width: `${(c.seconds / w.total_seconds) * 100}%`,
                      backgroundColor: c.color,
                    }}
                    title={`${c.label}: ${formatDuration(c.seconds)}`}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── App breakdown + title breakdown ───────────────────────────────

function AppBreakdown({
  summary, filterApp, onSelect,
}: {
  summary: AppUsageFullSummary | null;
  filterApp: string | null;
  onSelect: (name: string) => void;
}) {
  return (
    <div className="bg-[#161616] border border-[#222] rounded-xl p-4 h-fit">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Por aplicação</h2>
      {summary && summary.by_app.length === 0 && (
        <p className="text-sm text-gray-500">Sem dados.</p>
      )}
      <div className="space-y-2 max-h-[500px] overflow-y-auto pr-1">
        {summary?.by_app.map(app => {
          const color = colorForApp(app.app_name);
          const selected = filterApp === app.app_name;
          return (
            <button
              key={app.app_name}
              onClick={() => onSelect(app.app_name)}
              className={`w-full text-left rounded-lg p-2.5 transition-colors border ${
                selected ? 'border-white/20 bg-white/5' : 'border-transparent hover:bg-white/5'
              }`}
            >
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: color }} />
                  <span className="text-sm font-medium truncate">{app.app_name}</span>
                </div>
                <span className="text-xs text-gray-400 shrink-0">{formatDuration(app.total_seconds)}</span>
              </div>
              <div className="h-1 rounded-full bg-white/5 overflow-hidden">
                <div className="h-full" style={{ width: `${app.percentage}%`, backgroundColor: color }} />
              </div>
              <div className="text-[10px] text-gray-600 mt-1">
                {app.session_count} sess. · {app.percentage}%
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function TitleBreakdown({ app, rows }: { app: string; rows: { window_title: string; total_seconds: number; session_count: number; percentage: number }[] }) {
  return (
    <div className="bg-[#161616] border border-[#222] rounded-xl p-4 h-fit">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
        Janelas em {app}
      </h2>
      <div className="space-y-1.5 max-h-[400px] overflow-y-auto pr-1">
        {rows.map(r => (
          <div key={r.window_title} className="text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate flex-1" title={r.window_title}>{r.window_title}</span>
              <span className="text-gray-500 shrink-0">{formatDuration(r.total_seconds)}</span>
            </div>
            <div className="h-0.5 rounded-full bg-white/5 mt-1 overflow-hidden">
              <div className="h-full bg-blue-500" style={{ width: `${r.percentage}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Settings modal (blocklist) ────────────────────────────────────

function SettingsModal({ onClose }: { onClose: () => void }) {
  const [entries, setEntries] = useState<{ id: number; app_name: string | null; bundle_id: string | null }[]>([]);
  const [newApp, setNewApp] = useState('');
  const [retentionDays, setRetentionDays] = useState('180');
  const [cleanupBusy, setCleanupBusy] = useState(false);
  const [cleanupResult, setCleanupResult] = useState<{ merged: number; purged: number } | null>(null);

  async function refresh() {
    setEntries(await appUsageApi.blocklist());
  }
  useEffect(() => { refresh(); }, []);

  async function add() {
    const name = newApp.trim();
    if (!name) return;
    await appUsageApi.addBlocklist({ app_name: name });
    setNewApp('');
    refresh();
  }

  async function remove(id: number) {
    await appUsageApi.deleteBlocklist(id);
    refresh();
  }

  async function runCleanup(purge: boolean) {
    setCleanupBusy(true);
    try {
      const days = purge ? parseInt(retentionDays, 10) || 0 : 0;
      const r = await appUsageApi.cleanup(5, days);
      setCleanupResult(r);
    } catch {
      alert('Erro no cleanup');
    } finally {
      setCleanupBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 overflow-y-auto py-8" onClick={onClose}>
      <div className="bg-[#161616] border border-[#333] rounded-2xl p-6 max-w-md w-full mx-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold">Definições</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-white/10"><X size={18} /></button>
        </div>

        <h3 className="text-xs uppercase tracking-wide text-gray-500 mb-2">Aplicações ignoradas</h3>
        <p className="text-xs text-gray-500 mb-3">
          Apps na blocklist não são rastreadas. O tracker recarrega esta lista a cada 30s.
        </p>
        <div className="flex gap-2 mb-3">
          <input
            value={newApp}
            onChange={e => setNewApp(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && add()}
            placeholder="Nome da aplicação (ex: 1Password)"
            className="flex-1 px-3 py-2 bg-black/30 border border-[#333] rounded-lg text-sm"
          />
          <button onClick={add} className="px-3 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm font-medium flex items-center gap-1">
            <Plus size={14} /> Adicionar
          </button>
        </div>
        <div className="space-y-1 mb-6 max-h-40 overflow-y-auto">
          {entries.length === 0 && (
            <p className="text-sm text-gray-500 text-center py-3">Nada na blocklist.</p>
          )}
          {entries.map(e => (
            <div key={e.id} className="flex items-center justify-between px-3 py-2 rounded bg-black/20">
              <span className="text-sm">{e.app_name || e.bundle_id}</span>
              <button onClick={() => remove(e.id)} className="text-red-400 hover:text-red-300">
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>

        <h3 className="text-xs uppercase tracking-wide text-gray-500 mb-2">Manutenção</h3>
        <p className="text-xs text-gray-500 mb-3">
          Faz merge de sessões adjacentes (mesma app + título, gap &lt; 5s) e opcionalmente apaga sessões antigas.
        </p>
        <div className="flex gap-2 mb-2">
          <button
            onClick={() => runCleanup(false)}
            disabled={cleanupBusy}
            className="flex-1 px-3 py-2 bg-white/10 hover:bg-white/15 rounded-lg text-sm font-medium disabled:opacity-50"
          >
            {cleanupBusy ? 'A processar…' : 'Compactar (merge)'}
          </button>
        </div>
        <div className="flex gap-2 items-center">
          <input
            type="number"
            min={1}
            value={retentionDays}
            onChange={e => setRetentionDays(e.target.value)}
            className="w-20 px-3 py-2 bg-black/30 border border-[#333] rounded-lg text-sm"
          />
          <span className="text-xs text-gray-500">dias guardar</span>
          <button
            onClick={() => runCleanup(true)}
            disabled={cleanupBusy}
            className="ml-auto px-3 py-2 bg-red-600/30 hover:bg-red-600/50 text-red-300 rounded-lg text-sm font-medium disabled:opacity-50"
          >
            Compactar + apagar antigos
          </button>
        </div>
        {cleanupResult && (
          <p className="text-xs text-green-400 mt-3">
            ✓ {cleanupResult.merged} merged, {cleanupResult.purged} apagados
          </p>
        )}
      </div>
    </div>
  );
}
