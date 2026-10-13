import { useEffect, useMemo, useState } from 'react';
import { format, subDays, addDays, startOfWeek, startOfMonth, startOfYear, endOfWeek, endOfMonth, endOfYear, addWeeks, addMonths, addYears } from 'date-fns';
import { pt } from 'date-fns/locale';
import { Activity, Smartphone, Tablet, Monitor, Watch, HelpCircle, RefreshCw, AlertTriangle, ExternalLink, Apple, Database, MessageCircle, Briefcase, Palette, Plane, Gamepad2, Wrench, Music, BookOpen, Layers, ChevronLeft, ChevronRight } from 'lucide-react';
import {
  screenTimeApi, habitsApi, ScreenTimeAppRow, ScreenTimeDeviceRow, ScreenTimeCategoryRow, ScreenTimeInsights,
} from '../api';
import { CATEGORY_FILL, CATEGORY_STACK_ORDER } from '../screenTime';

const CATEGORY_META: Record<string, { Icon: typeof Layers; color: string }> = {
  'All Usage': { Icon: Layers, color: 'text-zinc-300' },
  'Social': { Icon: MessageCircle, color: 'text-blue-400' },
  'Productivity & Finance': { Icon: Briefcase, color: 'text-violet-400' },
  'Creativity': { Icon: Palette, color: 'text-orange-400' },
  'Travel': { Icon: Plane, color: 'text-sky-400' },
  'Games': { Icon: Gamepad2, color: 'text-pink-400' },
  'Utilities': { Icon: Wrench, color: 'text-zinc-400' },
  'Entertainment': { Icon: Music, color: 'text-red-400' },
  'Information & Reading': { Icon: BookOpen, color: 'text-emerald-400' },
  'Other': { Icon: HelpCircle, color: 'text-zinc-500' },
};

const KIND_OPTIONS = [
  { value: 'mac', label: 'Mac', Icon: Monitor },
  { value: 'iphone', label: 'iPhone', Icon: Smartphone },
  { value: 'ipad', label: 'iPad', Icon: Tablet },
  { value: 'watch', label: 'Watch', Icon: Watch },
  { value: 'unknown', label: '?', Icon: HelpCircle },
] as const;

function kindIcon(kind: string | undefined) {
  const found = KIND_OPTIONS.find(k => k.value === kind);
  return (found ?? KIND_OPTIONS[KIND_OPTIONS.length - 1]).Icon;
}

function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem ? `${h}h ${rem}m` : `${h}h`;
}

function fmtBigDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem ? `${h}h ${rem}min` : `${h}h`;
}

function bundleToFriendly(bundle: string): string {
  const last = bundle.split('.').pop() || bundle;
  return last.replace(/^mobile/i, '').replace(/^[a-z]/, c => c.toUpperCase());
}

function AppIcon({ bundleId, category, size = 32 }: { bundleId: string; category?: string; size?: number }) {
  const [failed, setFailed] = useState(false);
  const fallbackColor = (category && CATEGORY_FILL[category]) || '#52525b';
  const letter = (bundleToFriendly(bundleId)[0] || '?').toUpperCase();
  if (failed || !bundleId) {
    return (
      <div
        className="flex items-center justify-center rounded-md text-white font-semibold flex-shrink-0"
        style={{ width: size, height: size, backgroundColor: fallbackColor, fontSize: size * 0.45 }}
      >
        {letter}
      </div>
    );
  }
  return (
    <img
      src={`/api/screen-time/app-icon?bundle_id=${encodeURIComponent(bundleId)}`}
      onError={() => setFailed(true)}
      alt=""
      className="rounded-md flex-shrink-0 object-contain"
      style={{ width: size, height: size }}
    />
  );
}

function deviceTitle(d: { device_id: string; label?: string; kind?: string }) {
  if (d.label) return d.label;
  if (d.device_id === '__local__') return 'Este Mac (local)';
  return d.device_id.slice(0, 8) + '…';
}

type RangeKey = 'today' | 'week' | 'month';

const RANGES: { key: RangeKey; label: string; days: number; bucket: 'hour' | 'day' }[] = [
  { key: 'today', label: 'Hoje', days: 1, bucket: 'hour' },
  { key: 'week', label: '7 dias', days: 7, bucket: 'day' },
  { key: 'month', label: '30 dias', days: 30, bucket: 'day' },
];

const PERIODO_LABEL: Record<'day' | 'week' | 'month', string> = { day: 'dia', week: 'semana', month: 'mês' };
const DIAS_SEMANA = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];

// Meta por categoria — um alvo de horas por dia. Dia/semana/mês não são metas
// diferentes, é só a forma de VER o progresso (o toggle acima da lista muda a
// vista de todas ao mesmo tempo); o criar só pede o alvo diário.
function Metas() {
  const [status, setStatus] = useState<Awaited<ReturnType<typeof screenTimeApi.goalsStatus>> | null>(null);
  const [habits, setHabits] = useState<{ id: number; name: string; icon: string }[]>([]);
  const [vista, setVista] = useState<'day' | 'week' | 'month'>('day');
  // Âncora das três vistas — "hoje" por omissão, mas dá para andar para trás
  // (ver Julho passado, por exemplo) sem trocar de vista.
  const [refDate, setRefDate] = useState(() => new Date());
  const [aberto, setAberto] = useState(false);
  const [busy, setBusy] = useState(false);
  const [novaCategoria, setNovaCategoria] = useState('Productivity & Finance');
  const [novasHoras, setNovasHoras] = useState('5');
  const [novosDias, setNovosDias] = useState('daily');
  const [novoHabito, setNovoHabito] = useState('');

  const carregar = () => {
    screenTimeApi.goalsStatus(format(refDate, 'yyyy-MM-dd')).then(setStatus).catch(() => setStatus(null));
  };
  useEffect(() => { carregar(); }, [refDate]);
  useEffect(() => { habitsApi.list().then(setHabits).catch(() => {}); }, []);
  if (!status) return null;

  const categorias = Object.keys(CATEGORY_META).filter(c => c !== 'All Usage');

  const navegar = (delta: number) => {
    setRefDate(d => vista === 'day' ? addDays(d, delta) : vista === 'week' ? addWeeks(d, delta) : addMonths(d, delta));
  };
  const hojeIso = format(new Date(), 'yyyy-MM-dd');
  const noPresente = status.date === hojeIso;
  const periodoRef = status.goals[0]?.views[vista];
  const podeAvancar = !periodoRef || periodoRef.period_end < hojeIso;
  const rotuloPeriodo = (() => {
    if (!periodoRef) return '';
    const ini = new Date(periodoRef.period_start + 'T00:00:00');
    const fim = new Date(periodoRef.period_end + 'T00:00:00');
    if (vista === 'day') return periodoRef.period_start === hojeIso ? 'hoje' : format(ini, "d 'de' MMMM", { locale: pt });
    if (vista === 'week') return `${format(ini, 'd MMM', { locale: pt })} – ${format(fim, 'd MMM', { locale: pt })}`;
    return format(ini, 'MMMM yyyy', { locale: pt });
  })();

  const diasSelecionados = novosDias === 'daily' ? [0, 1, 2, 3, 4, 5, 6]
    : novosDias === 'weekdays' ? [0, 1, 2, 3, 4]
      : novosDias.split(',').filter(Boolean).map(Number);

  const toggleDia = (i: number) => {
    setNovosDias(d => {
      const actual = d === 'daily' ? [0, 1, 2, 3, 4, 5, 6] : d === 'weekdays' ? [0, 1, 2, 3, 4] : d.split(',').filter(Boolean).map(Number);
      const next = actual.includes(i) ? actual.filter(x => x !== i) : [...actual, i].sort((a, b) => a - b);
      return next.length === 7 ? 'daily' : next.join(',');
    });
  };

  const adicionar = async () => {
    const horas = parseFloat(novasHoras);
    if (!horas || horas <= 0 || !novaCategoria) return;
    setBusy(true);
    try {
      await screenTimeApi.setGoal(novaCategoria, horas, novosDias, novoHabito ? Number(novoHabito) : null);
      setNovasHoras('5');
      setNovosDias('daily');
      setNovoHabito('');
      carregar();
    } finally { setBusy(false); }
  };

  const remover = async (cat: string) => {
    setBusy(true);
    try { await screenTimeApi.setGoal(cat, 0, 'daily'); carregar(); } finally { setBusy(false); }
  };

  const fmt = (s: number) => `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}`;

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 mb-3">
        <h2 className="font-semibold text-sm">Metas</h2>

        <div className="flex items-center gap-1 justify-self-center">
          {status.goals.length > 0 && (
            <>
              <button onClick={() => navegar(-1)}
                className="p-1 rounded-lg text-zinc-500 hover:text-white hover:bg-white/10">
                <ChevronLeft size={14} />
              </button>
              <span className="w-32 text-center text-xs text-zinc-300 capitalize">{rotuloPeriodo}</span>
              <button onClick={() => navegar(1)} disabled={!podeAvancar}
                className="p-1 rounded-lg text-zinc-500 hover:text-white hover:bg-white/10 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-zinc-500">
                <ChevronRight size={14} />
              </button>
              {!noPresente && (
                <button onClick={() => setRefDate(new Date())} className="text-xs text-blue-400 hover:underline ml-1">hoje</button>
              )}
            </>
          )}
        </div>

        <div className="flex items-center gap-2 justify-self-end">
          <div className="inline-flex rounded-lg bg-zinc-800 border border-zinc-700 p-0.5">
            {(['day', 'week', 'month'] as const).map(p => (
              <button key={p} onClick={() => setVista(p)}
                className={`px-2 py-1 rounded text-xs font-medium capitalize ${
                  vista === p ? 'bg-blue-500/20 text-blue-300' : 'text-zinc-500 hover:text-zinc-300'
                }`}>
                {PERIODO_LABEL[p]}
              </button>
            ))}
          </div>
          <button onClick={() => setAberto(a => !a)} className="text-xs text-zinc-400 hover:text-zinc-200">
            {aberto ? 'fechar' : 'adicionar'}
          </button>
        </div>
      </div>

      {status.goals.length > 0 && (
        <div className="space-y-2">
          {status.goals.map(g => {
            const v = g.views[vista];
            return (
              <div key={g.category} className="flex items-center gap-3 text-xs">
                <span className="w-36 truncate text-zinc-300" title={diasLabel(g.days)}>{g.category}</span>
                <div className="flex-1 h-2 bg-zinc-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${v.reached ? 'bg-emerald-500' : 'bg-blue-500'}`}
                    style={{ width: `${Math.min(100, v.pct || 0)}%` }}
                  />
                </div>
                <span className="shrink-0 whitespace-nowrap text-right text-zinc-400">
                  {fmt(v.used_seconds)} / {fmt(v.target_seconds)}{!v.reached ? ` · faltam ${fmt(v.remaining_seconds)}` : ''}
                </span>
                {g.habit_name && (
                  <span
                    title={g.habit_checked_today ? `${g.habit_name} marcado` : `${g.habit_name} por marcar`}
                    className={`shrink-0 ${g.habit_checked_today ? 'text-emerald-400' : 'text-zinc-500'}`}
                  >
                    {g.habit_icon}{g.habit_checked_today ? '✓' : ''}
                  </span>
                )}
                {aberto && (
                  <button onClick={() => remover(g.category)} disabled={busy}
                    className="text-zinc-500 hover:text-red-400 disabled:opacity-40">tirar</button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {status.goals.length === 0 && !aberto && (
        <p className="text-xs text-zinc-500">Sem metas definidas. Carrega em “adicionar” para criar uma.</p>
      )}

      {aberto && (
        <div className={`${status.goals.length > 0 ? 'mt-3 pt-3 border-t border-zinc-800' : ''} space-y-2`}>
          <div className="flex items-center gap-2 flex-wrap">
            <select value={novaCategoria} onChange={e => setNovaCategoria(e.target.value)}
              className="bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1.5 text-xs text-zinc-200">
              {categorias.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <input type="number" min="0.5" step="0.5" value={novasHoras}
              onChange={e => setNovasHoras(e.target.value)}
              className="w-16 bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1.5 text-xs text-zinc-200" />
            <span className="text-xs text-zinc-500">horas/dia</span>
          </div>

          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs text-zinc-500 mr-0.5">dias:</span>
            <button onClick={() => setNovosDias('daily')}
              className={`px-2 py-1 rounded text-[11px] font-medium ${
                novosDias === 'daily' ? 'bg-blue-500/20 text-blue-300' : 'bg-zinc-800 text-zinc-500 hover:text-zinc-300'
              }`}>Todos</button>
            <button onClick={() => setNovosDias('weekdays')}
              className={`px-2 py-1 rounded text-[11px] font-medium ${
                novosDias === 'weekdays' ? 'bg-blue-500/20 text-blue-300' : 'bg-zinc-800 text-zinc-500 hover:text-zinc-300'
              }`}>Dias úteis</button>
            {DIAS_SEMANA.map((d, i) => (
              <button key={d} onClick={() => toggleDia(i)}
                className={`w-7 py-1 rounded text-[11px] font-medium ${
                  diasSelecionados.includes(i) ? 'bg-blue-500/20 text-blue-300' : 'bg-zinc-800 text-zinc-500 hover:text-zinc-300'
                }`}>{d[0]}</button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-zinc-500">hábito:</span>
            <select value={novoHabito} onChange={e => setNovoHabito(e.target.value)}
              className="bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1.5 text-xs text-zinc-200">
              <option value="">sem hábito associado</option>
              {habits.map(h => <option key={h.id} value={h.id}>{h.icon} {h.name}</option>)}
            </select>
          </div>

          <button onClick={adicionar} disabled={busy}
            className="px-3 py-1.5 rounded-lg bg-blue-500/15 text-blue-300 hover:bg-blue-500/25 disabled:opacity-40 text-xs font-medium">
            adicionar
          </button>
        </div>
      )}
    </div>
  );
}

function diasLabel(dias: string): string {
  if (dias === 'daily') return 'todos os dias';
  if (dias === 'weekdays') return 'dias úteis';
  return dias.split(',').map(d => DIAS_SEMANA[Number(d)] || '?').join(', ');
}

function StackedActivityChart({
  series, bucket, totalSeconds,
}: {
  series: { bucket_start: number; categories: Record<string, number> }[];
  bucket: 'hour' | 'day';
  totalSeconds: number;
}) {
  if (series.length === 0) return null;
  const totals = series.map(s => Object.values(s.categories).reduce((a, b) => a + b, 0));
  const max = Math.max(...totals, 1);
  const nonZero = totals.filter(t => t > 0).length;
  const avg = nonZero > 0 ? totalSeconds / (bucket === 'hour' ? Math.max(nonZero, 1) : series.length) : 0;
  const avgPct = max > 0 ? (avg / max) * 100 : 0;

  const labelFor = (ts: number, i: number): string => {
    const d = new Date(ts * 1000);
    if (bucket === 'hour') {
      const h = d.getHours();
      return [0, 6, 12, 18].includes(h) ? String(h).padStart(2, '0') : '';
    }
    if (series.length <= 7) {
      return ['D', 'S', 'T', 'Q', 'Q', 'S', 'S'][d.getDay()];
    }
    return i % 5 === 0 ? String(d.getDate()) : '';
  };

  // legenda — só categorias que têm pelo menos algum tempo no intervalo
  const presentCats = CATEGORY_STACK_ORDER.filter(cat =>
    series.some(s => (s.categories[cat] || 0) > 0)
  );

  return (
    <div className="w-full">
      <div className="relative h-48 w-full px-2">
        <div className="absolute inset-x-2 top-0 bottom-6 flex flex-col justify-between pointer-events-none">
          {[0, 1, 2, 3].map(i => (
            <div key={i} className="border-t border-zinc-800/60 border-dashed h-0" />
          ))}
        </div>

        {avg > 0 && (
          <div
            className="absolute inset-x-2 border-t border-dashed border-emerald-400/70 pointer-events-none flex justify-end z-10"
            style={{ bottom: `${24 + avgPct * 1.68}px` }}
          >
            <span className="text-[10px] text-emerald-400 -translate-y-1/2 bg-zinc-900 px-1 rounded">
              média {fmtDuration(avg)}
            </span>
          </div>
        )}

        <div className="absolute inset-x-2 top-0 bottom-6 flex items-end gap-[2px]">
          {series.map((s, idx) => {
            const total = totals[idx];
            const heightPct = (total / max) * 100;
            const isCurrent = bucket === 'hour'
              ? new Date(s.bucket_start * 1000).getHours() === new Date().getHours()
                && new Date(s.bucket_start * 1000).toDateString() === new Date().toDateString()
              : new Date(s.bucket_start * 1000).toDateString() === new Date().toDateString();
            const tooltip = total > 0
              ? `${new Date(s.bucket_start * 1000).toLocaleString('pt-PT')}\n` +
                CATEGORY_STACK_ORDER
                  .map(c => ({ c, v: s.categories[c] || 0 }))
                  .filter(x => x.v > 0)
                  .map(x => `${x.c}: ${fmtDuration(x.v)}`)
                  .join('\n')
              : new Date(s.bucket_start * 1000).toLocaleString('pt-PT');
            return (
              <div
                key={s.bucket_start}
                className="flex-1 flex flex-col-reverse justify-start group relative"
                title={tooltip}
                style={{ height: `${heightPct}%`, minHeight: total > 0 ? '2px' : '0px' }}
              >
                {CATEGORY_STACK_ORDER.map((cat, ci) => {
                  const v = s.categories[cat] || 0;
                  if (v <= 0 || total <= 0) return null;
                  const segPct = (v / total) * 100;
                  const isFirst = CATEGORY_STACK_ORDER.slice(0, ci).every(c2 => (s.categories[c2] || 0) === 0);
                  return (
                    <div
                      key={cat}
                      className={`w-full ${isFirst ? '' : ''}`}
                      style={{
                        height: `${segPct}%`,
                        backgroundColor: CATEGORY_FILL[cat] || '#52525b',
                        opacity: isCurrent ? 1 : 0.85,
                      }}
                    />
                  );
                })}
              </div>
            );
          })}
        </div>

        <div className="absolute inset-x-2 bottom-0 h-6 flex items-start gap-[2px] text-[10px] text-zinc-500">
          {series.map((s, i) => (
            <div key={s.bucket_start} className="flex-1 text-center">{labelFor(s.bucket_start, i)}</div>
          ))}
        </div>
      </div>

      {/* legenda */}
      {presentCats.length > 0 && (
        <div className="px-2 pt-3 flex flex-wrap gap-x-3 gap-y-1.5 text-[11px] text-zinc-400">
          {presentCats.map(cat => (
            <div key={cat} className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ backgroundColor: CATEGORY_FILL[cat] || '#52525b' }} />
              <span>{cat}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

type StatsPeriodKey = 'week' | 'month' | 'year' | 'all';

const STATS_PERIODS: { key: StatsPeriodKey; label: string; bucket: 'day' | 'month' }[] = [
  { key: 'week', label: 'Semana', bucket: 'day' },
  { key: 'month', label: 'Mês', bucket: 'day' },
  { key: 'year', label: 'Ano', bucket: 'month' },
  { key: 'all', label: 'Desde sempre', bucket: 'month' },
];

const MONTH_LABELS = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];
const WEEKDAY_LABELS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];

// Início/fim do período que contém `anchor`. O fim nunca passa de hoje (não
// mostramos dias futuros). 'all' ignora anchor (todo o histórico guardado).
function periodBounds(key: StatsPeriodKey, anchor: Date): { start: Date; end: Date } {
  const today = new Date();
  if (key === 'week') return { start: startOfWeek(anchor, { weekStartsOn: 1 }), end: minDate(endOfWeek(anchor, { weekStartsOn: 1 }), today) };
  if (key === 'month') return { start: startOfMonth(anchor), end: minDate(endOfMonth(anchor), today) };
  if (key === 'year') return { start: startOfYear(anchor), end: minDate(endOfYear(anchor), today) };
  return { start: today, end: today }; // 'all' não usa bounds
}

function minDate(a: Date, b: Date): Date { return a < b ? a : b; }

function statsRange(key: StatsPeriodKey, anchor: Date): { start_date?: string; end_date: string; bucket: 'day' | 'month' } {
  const cfg = STATS_PERIODS.find(p => p.key === key)!;
  if (key === 'all') return { end_date: format(new Date(), 'yyyy-MM-dd'), bucket: cfg.bucket };
  const { start, end } = periodBounds(key, anchor);
  return { start_date: format(start, 'yyyy-MM-dd'), end_date: format(end, 'yyyy-MM-dd'), bucket: cfg.bucket };
}

function periodLabel(key: StatsPeriodKey, anchor: Date): string {
  if (key === 'week') {
    const { start, end } = periodBounds(key, anchor);
    return `${start.getDate()} ${MONTH_LABELS[start.getMonth()]} – ${end.getDate()} ${MONTH_LABELS[end.getMonth()]}`;
  }
  if (key === 'month') return `${MONTH_LABELS[anchor.getMonth()]} ${anchor.getFullYear()}`;
  if (key === 'year') return String(anchor.getFullYear());
  return 'Desde sempre';
}

// Verdade se o período de `anchor` é o mais recente (não há "próximo").
function isLatestPeriod(key: StatsPeriodKey, anchor: Date): boolean {
  const today = new Date();
  if (key === 'week') return startOfWeek(anchor, { weekStartsOn: 1 }) >= startOfWeek(today, { weekStartsOn: 1 });
  if (key === 'month') return startOfMonth(anchor) >= startOfMonth(today);
  if (key === 'year') return startOfYear(anchor) >= startOfYear(today);
  return true;
}

function shiftAnchor(key: StatsPeriodKey, anchor: Date, dir: -1 | 1): Date {
  if (key === 'week') return addWeeks(anchor, dir);
  if (key === 'month') return addMonths(anchor, dir);
  if (key === 'year') return addYears(anchor, dir);
  return anchor;
}

function MiniBars({ data, color, tipLabel, onPick }: {
  data: { label: string; seconds: number; highlight?: boolean; tip?: string }[];
  color: string;
  tipLabel?: (d: { label: string; seconds: number; tip?: string }) => string;
  onPick?: (i: number) => void;
}) {
  const max = Math.max(...data.map(d => d.seconds), 1);
  return (
    <div className="flex items-end gap-[3px] h-32">
      {data.map((d, i) => (
        <div key={i} onClick={onPick ? () => onPick(i) : undefined}
          className={`flex-1 flex flex-col items-center justify-end h-full group relative ${onPick ? 'cursor-pointer' : ''}`}>
          {/* tooltip instantâneo (o title nativo demora ~1s a aparecer) */}
          <div className="pointer-events-none absolute bottom-full mb-1 hidden group-hover:block z-20 whitespace-nowrap rounded-md bg-zinc-800 border border-zinc-700 px-2 py-1 text-[10px] text-zinc-100 shadow-lg">
            {tipLabel ? tipLabel(d) : `${d.tip || d.label}: ${fmtDuration(d.seconds)}`}
          </div>
          <div
            className="w-full rounded-t transition-opacity group-hover:opacity-100"
            style={{ height: `${(d.seconds / max) * 100}%`, minHeight: d.seconds > 0 ? '2px' : '0', backgroundColor: color, opacity: d.highlight ? 1 : 0.55 }}
          />
          <span className="text-[9px] text-zinc-600 mt-1 truncate w-full text-center">{d.label}</span>
        </div>
      ))}
    </div>
  );
}

/** Média por dia da semana, categoria a categoria.
 *
 *  A pergunta não é "quanto é que usei ontem" — é "às quintas trabalho mais e ao
 *  domingo menos?". Segue o período escolhido em cima; os dias sem leitura
 *  nenhuma não entram na conta, senão o Mac desligado puxava a média para baixo.
 */
function MediaPorDiaDaSemana({ range }: {
  range: { start_date?: string; end_date: string };
}) {
  const [dias, setDias] = useState<{ bucket_start: number; categories: Record<string, number> }[]>([]);
  const [categoria, setCategoria] = useState<string | null>(null);
  const [erro, setErro] = useState('');
  // O dia da semana aberto (0 = segunda) e as apps que fazem aquele número.
  const [diaAberto, setDiaAberto] = useState<number | null>(null);
  const [apps, setApps] = useState<ScreenTimeAppRow[] | null>(null);

  useEffect(() => {
    setErro('');
    screenTimeApi.timeseriesStacked({
      start_date: range.start_date, end_date: range.end_date,
      bucket: 'day', source: 'tracker',
    }).then(setDias).catch(e => { setDias([]); setErro(e?.message || 'não deu para ler'); });
  }, [range.start_date, range.end_date]);

  // As apps do dia aberto. Uma pergunta de cada vez: só se vai buscar quando ele
  // carrega numa barra.
  useEffect(() => {
    if (diaAberto === null) { setApps(null); return; }
    let vivo = true;
    setApps(null);
    screenTimeApi.byApp({
      start_date: range.start_date, end_date: range.end_date, source: 'tracker',
      weekday: diaAberto, category: categoria || undefined,
    }).then(r => vivo && setApps(r)).catch(() => vivo && setApps([]));
    return () => { vivo = false; };
  }, [diaAberto, categoria, range.start_date, range.end_date]);

  // Totais por categoria, para as fichas virem pela ordem do costume.
  const totais: Record<string, number> = {};
  for (const d of dias) for (const [c, v] of Object.entries(d.categories)) totais[c] = (totais[c] || 0) + v;
  const categorias = Object.keys(totais).sort((a, b) => totais[b] - totais[a]);
  const escolhida = categoria && totais[categoria] ? categoria : null;

  const soma = Array(7).fill(0);
  const conta = Array(7).fill(0);
  for (const d of dias) {
    const wd = (new Date(d.bucket_start * 1000).getDay() + 6) % 7;   // 0 = segunda
    const seg = escolhida
      ? (d.categories[escolhida] || 0)
      : Object.values(d.categories).reduce((t, v) => t + v, 0);
    soma[wd] += seg;
    conta[wd] += 1;
  }
  const barras = WEEKDAY_LABELS.map((label, i) => ({
    label,
    seconds: conta[i] ? soma[i] / conta[i] : 0,
    tip: `${label}: média de ${conta[i]} ${conta[i] === 1 ? 'dia' : 'dias'}`,
    highlight: diaAberto === null || diaAberto === i,
  }));
  const cor = escolhida ? (CATEGORY_FILL[escolhida] || '#52525b') : '#60a5fa';
  // A média de todos os dias — a régua contra a qual se lêem as sete barras.
  const diasMedidos = conta.reduce((t, n) => t + n, 0);
  const mediaDiaria = diasMedidos ? soma.reduce((t, v) => t + v, 0) / diasMedidos : 0;

  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
      <div className="flex items-baseline justify-between gap-3 flex-wrap mb-3">
        <h2 className="font-semibold text-sm">Média por dia da semana</h2>
        {diasMedidos > 0 && (
          <span className="text-xs text-zinc-500">
            <span className="font-mono text-zinc-300">{fmtDuration(mediaDiaria)}</span> por dia
            {' '}em {escolhida || 'tudo'} · {diasMedidos} {diasMedidos === 1 ? 'dia medido' : 'dias medidos'}
          </span>
        )}
      </div>

      <div className="flex flex-wrap gap-1.5 mb-3">
        <button onClick={() => setCategoria(null)}
          className={`px-2.5 py-1 rounded-lg text-xs border transition ${
            escolhida === null ? 'border-zinc-600 bg-zinc-700 text-white' : 'border-zinc-800 text-zinc-400 hover:bg-zinc-800'}`}>
          Tudo
        </button>
        {categorias.filter(c => c !== 'All Usage').map(c => (
          <button key={c} onClick={() => setCategoria(c)}
            className={`px-2.5 py-1 rounded-lg text-xs border transition flex items-center gap-1.5 ${
              escolhida === c ? 'border-zinc-600 bg-zinc-700 text-white' : 'border-zinc-800 text-zinc-400 hover:bg-zinc-800'}`}>
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: CATEGORY_FILL[c] || '#52525b' }} />
            {c}
          </button>
        ))}
      </div>

      {erro ? <p className="text-sm text-red-400">Falhou a leitura: {erro}</p>
        : diasMedidos === 0 ? <p className="text-sm text-zinc-500">Sem dias medidos neste período.</p>
        : <>
            {/* a linha da média atravessa as barras: vê-se logo que dia é que
                está acima do costume sem ter de comparar números */}
            <div className="relative">
              <MiniBars data={barras} color={cor}
                tipLabel={d => `${d.tip} · ${fmtDuration(d.seconds)} · carrega para ver as apps`}
                onPick={i => setDiaAberto(diaAberto === i ? null : i)} />
              {mediaDiaria > 0 && (
                <div className="pointer-events-none absolute inset-x-0 border-t border-dashed border-zinc-500/50"
                  style={{ bottom: `${(mediaDiaria / Math.max(...barras.map(b => b.seconds), 1)) * 100 * 0.87 + 13}%` }} />
              )}
            </div>
            <div className="flex justify-between mt-2 text-[10px] text-zinc-600 tabular-nums">
              {barras.map(b => <span key={b.label} className="flex-1 text-center">{fmtDuration(b.seconds)}</span>)}
            </div>

            {/* De onde vem o número da barra. Sem isto, "2h45 de Productivity &
                Finance à quarta" era um número sem forma de o confirmar. */}
            {diaAberto !== null && (
              <div className="mt-3 border-t border-zinc-800 pt-3">
                <div className="flex items-baseline justify-between gap-2 mb-2">
                  <h3 className="text-xs font-semibold">
                    {['Segundas', 'Terças', 'Quartas', 'Quintas', 'Sextas', 'Sábados', 'Domingos'][diaAberto]}
                    {escolhida ? ` · ${escolhida}` : ''}
                  </h3>
                  <span className="text-[11px] text-zinc-500">
                    {conta[diaAberto]} {conta[diaAberto] === 1 ? 'dia' : 'dias'} somados ·{' '}
                    <button onClick={() => setDiaAberto(null)} className="underline hover:text-zinc-300">fechar</button>
                  </span>
                </div>
                {apps === null ? <p className="text-xs text-zinc-500">a ler…</p>
                  : apps.length === 0 ? <p className="text-xs text-zinc-500">Nada nesse dia.</p>
                  : (
                    <ul className="space-y-1.5">
                      {apps.slice(0, 8).map(a => (
                        <li key={`${a.bundle_id}-${a.device_id}`} className="flex items-center gap-2.5">
                          <AppIcon bundleId={a.bundle_id} category={a.category} size={20} />
                          <span className="flex-1 min-w-0 truncate text-xs text-zinc-300">
                            {bundleToFriendly(a.bundle_id)}
                          </span>
                          <span className="text-[11px] text-zinc-500 tabular-nums">
                            {fmtDuration(a.total_seconds / Math.max(1, conta[diaAberto]))}/dia
                          </span>
                          <span className="w-14 text-right font-mono text-xs text-zinc-300 tabular-nums">
                            {fmtDuration(a.total_seconds)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
              </div>
            )}
          </>}
    </section>
  );
}

function StatsTab() {
  // O período escolhido fica guardado, como a fonte e o modo da outra aba.
  const [period, setPeriod] = useState<StatsPeriodKey>(() => {
    const v = localStorage.getItem('screenTimeStatsPeriod');
    return v === 'week' || v === 'month' || v === 'year' || v === 'all' ? v : 'month';
  });
  const [anchor, setAnchor] = useState<Date>(() => new Date());
  const [data, setData] = useState<ScreenTimeInsights | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  async function reload() {
    setLoading(true); setErr('');
    try { setData(await screenTimeApi.insights(statsRange(period, anchor))); }
    catch (e: any) { setErr(e?.message || String(e)); }
    finally { setLoading(false); }
  }
  useEffect(() => { reload(); /* eslint-disable-next-line */ }, [period, anchor]);

  function pickPeriod(key: StatsPeriodKey) {
    setAnchor(new Date());  // ao trocar de tipo de período, volta ao actual
    setPeriod(key);
    localStorage.setItem('screenTimeStatsPeriod', key);
  }
  const atLatest = isLatestPeriod(period, anchor);

  async function snapshotNow() {
    setLoading(true);
    try { await screenTimeApi.snapshot(45); await reload(); }
    catch (e: any) { setErr(e?.message || String(e)); setLoading(false); }
  }

  if (err) return <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">{err}</div>;
  if (!data) return <div className="text-sm text-zinc-500 p-6 text-center">A carregar…</div>;

  if (data.tracked_days === 0) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-6 text-center space-y-3">
        <p className="text-sm text-zinc-300">Ainda não há histórico guardado.</p>
        <p className="text-xs text-zinc-500">Os dados do Screen Time passam a ser guardados diariamente a partir de agora, para teres estatísticas de longo prazo (o macOS só guarda ~4 semanas).</p>
        <button onClick={snapshotNow} disabled={loading}
          className="px-3 py-1.5 rounded-lg bg-blue-500/20 hover:bg-blue-500/30 text-blue-200 text-xs border border-blue-400/40 disabled:opacity-50">
          {loading ? 'A guardar…' : 'Guardar histórico agora'}
        </button>
      </div>
    );
  }

  const maxDayApp = Math.max(...data.top_apps.map(a => a.seconds), 1);
  const totalCat = data.by_category.reduce((s, c) => s + c.seconds, 0) || 1;
  const isMonthly = data.bucket === 'month';
  const tsLen = data.timeseries.length;
  const timeseriesBars = data.timeseries.map((p, i) => {
    let label = '';
    let tip = '';
    if (isMonthly) {
      const [yy, mm] = p.date.split('-');
      const mi = Number(mm) - 1;
      label = (tsLen <= 12 || i % 2 === 0) ? MONTH_LABELS[mi] : '';
      tip = `${MONTH_LABELS[mi]} ${yy}`;
    } else {
      const dt = new Date(p.date + 'T00:00:00');
      const dd = dt.getDate();
      // Mostra todos os dias: letra do dia da semana se poucos, senão o número do dia.
      label = tsLen <= 14 ? WEEKDAY_LABELS[(dt.getDay() + 6) % 7][0] : String(dd);
      tip = `${dd} ${MONTH_LABELS[dt.getMonth()]}`;
    }
    return { label, tip, seconds: p.seconds, highlight: data.busiest_day?.date === p.date };
  });

  return (
    <div className="space-y-6">
      {/* Período */}
      <div className="flex items-center gap-2 flex-wrap">
        {STATS_PERIODS.map(p => (
          <button key={p.key} onClick={() => pickPeriod(p.key)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
              period === p.key ? 'bg-blue-500/20 border-blue-400 text-blue-300' : 'border-zinc-700 text-zinc-400 hover:bg-zinc-800'
            }`}>
            {p.label}
          </button>
        ))}
        {period !== 'all' && (
          <div className="inline-flex items-center gap-1">
            <button onClick={() => setAnchor(a => shiftAnchor(period, a, -1))}
              className="p-1.5 rounded-lg border border-zinc-700 text-zinc-400 hover:bg-zinc-800" title="Período anterior">
              <ChevronLeft size={14} />
            </button>
            <span className="px-2 text-sm font-medium min-w-[120px] text-center">{periodLabel(period, anchor)}</span>
            <button onClick={() => setAnchor(a => shiftAnchor(period, a, 1))} disabled={atLatest}
              className="p-1.5 rounded-lg border border-zinc-700 text-zinc-400 hover:bg-zinc-800 disabled:opacity-30 disabled:cursor-not-allowed" title="Período seguinte">
              <ChevronRight size={14} />
            </button>
            {!atLatest && (
              <button onClick={() => setAnchor(new Date())}
                className="ml-1 px-2 py-1 rounded-lg text-[11px] text-blue-300 hover:bg-zinc-800" title="Voltar ao actual">
                Actual
              </button>
            )}
          </div>
        )}
        <span className="text-xs text-zinc-600 ml-auto">
          {data.tracked_days} {data.tracked_days === 1 ? 'dia' : 'dias'} guardados
          {data.first_date && ` · desde ${new Date(data.first_date + 'T00:00:00').toLocaleDateString('pt-PT', { day: 'numeric', month: 'short' })}`}
        </span>
      </div>

      {/* Cards resumo */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
          <div className="text-xs text-zinc-500">Total no período</div>
          <div className="text-2xl font-bold mt-1">{fmtBigDuration(data.total_period_seconds)}</div>
          {data.delta_pct !== null && (
            <div className={`text-xs mt-1 ${data.delta_pct > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
              {data.delta_pct > 0 ? '↑' : '↓'} {Math.abs(data.delta_pct)}% vs período anterior
            </div>
          )}
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
          <div className="text-xs text-zinc-500">Média / dia</div>
          <div className="text-2xl font-bold mt-1 text-emerald-300">{fmtDuration(data.daily_avg_seconds)}</div>
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
          <div className="text-xs text-zinc-500">Dia mais usado</div>
          {data.busiest_day ? (
            <>
              <div className="text-2xl font-bold mt-1">{fmtDuration(data.busiest_day.seconds)}</div>
              <div className="text-xs text-zinc-500 mt-1">{new Date(data.busiest_day.date + 'T00:00:00').toLocaleDateString('pt-PT', { weekday: 'short', day: 'numeric', month: 'short' })}</div>
            </>
          ) : <div className="text-2xl font-bold mt-1 text-zinc-600">—</div>}
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
          <div className="text-xs text-zinc-500">Total guardado</div>
          <div className="text-2xl font-bold mt-1">{fmtBigDuration(data.total_all_seconds)}</div>
          <div className="text-xs text-zinc-500 mt-1">{data.tracked_days} dias de histórico</div>
        </div>
      </div>

      {/* Evolução */}
      <section className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
        <h2 className="font-semibold text-sm mb-3">{isMonthly ? 'Evolução por mês' : 'Evolução diária'}</h2>
        <MiniBars data={timeseriesBars} color="#60a5fa" />
      </section>

      {/* Média por dia da semana, categoria a categoria. Substituiu a média
          simples que estava aqui: dizia o mesmo, mas só do total. */}
      <MediaPorDiaDaSemana range={statsRange(period, anchor)} />

      {/* Top apps */}
      <section className="rounded-xl border border-zinc-800 bg-zinc-900/50">
        <div className="px-4 py-3 border-b border-zinc-800"><h2 className="font-semibold text-sm">Apps mais usadas</h2></div>
        <ul className="divide-y divide-zinc-800">
          {data.top_apps.map(a => (
            <li key={a.bundle_id} className="px-4 py-2.5 flex items-center gap-3">
              <AppIcon bundleId={a.bundle_id} category={a.category} size={28} />
              <div className="flex-1 min-w-0">
                <div className="text-sm truncate">{bundleToFriendly(a.bundle_id)}</div>
                <div className="h-1.5 rounded-full bg-zinc-800 mt-1.5 overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${(a.seconds / maxDayApp) * 100}%`, backgroundColor: CATEGORY_FILL[a.category] || '#52525b' }} />
                </div>
              </div>
              <div className="text-sm font-mono text-zinc-300 flex-shrink-0">{fmtDuration(a.seconds)}</div>
            </li>
          ))}
        </ul>
      </section>

      {/* Por categoria */}
      <section className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
        <h2 className="font-semibold text-sm mb-3">Por categoria</h2>
        <div className="space-y-2.5">
          {data.by_category.map(c => (
            <div key={c.category} className="flex items-center gap-3">
              <div className="w-36 text-xs text-zinc-400 truncate flex-shrink-0">{c.category}</div>
              <div className="flex-1 h-2 rounded-full bg-zinc-800 overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${(c.seconds / totalCat) * 100}%`, backgroundColor: CATEGORY_FILL[c.category] || '#52525b' }} />
              </div>
              <div className="text-xs font-mono text-zinc-400 w-16 text-right flex-shrink-0">{fmtDuration(c.seconds)}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export default function ScreenTimePage() {
  const [health, setHealth] = useState<{ available: boolean; apple_local?: boolean; reason: string; db_path: string; python_app_path?: string } | null>(null);
  const [byDevice, setByDevice] = useState<ScreenTimeDeviceRow[]>([]);
  const [byApp, setByApp] = useState<ScreenTimeAppRow[]>([]);
  const [byCategory, setByCategory] = useState<ScreenTimeCategoryRow[]>([]);
  const [stackedSeries, setStackedSeries] = useState<{ bucket_start: number; categories: Record<string, number> }[]>([]);
  const [view, setView] = useState<'categories' | 'apps'>(() => {
    const saved = localStorage.getItem('screenTimeView');
    return saved === 'categories' ? 'categories' : 'apps';
  });
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null);
  const [filterDevice, setFilterDevice] = useState<string>('');
  const [range, setRange] = useState<RangeKey>('today');
  const [mode, setMode] = useState<'raw' | 'apple'>(() => {
    const saved = localStorage.getItem('screenTimeMode');
    return saved === 'apple' ? 'apple' : 'raw';
  });
  // De onde vêm as horas: o tracker próprio (bate certo com a duração real dos
  // jogos) ou a leitura aproximada do knowledgeC da Apple, que é a única que vê
  // outros dispositivos.
  const [fonte, setFonte] = useState<'tracker' | 'apple'>(() =>
    (localStorage.getItem('screenTimeSource') === 'apple' ? 'apple' : 'tracker'));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>('');
  const [tab, setTab] = useState<'live' | 'stats'>('live');

  const cfg = RANGES.find(r => r.key === range)!;

  const dateRange = useMemo(() => {
    const today = new Date();
    return {
      start_date: format(subDays(today, cfg.days - 1), 'yyyy-MM-dd'),
      end_date: format(today, 'yyyy-MM-dd'),
    };
  }, [cfg.days]);

  async function load() {
    setLoading(true);
    setError('');
    try {
      const h = await screenTimeApi.health();
      setHealth(h);
      if (!h.available) {
        setLoading(false);
        return;
      }
      // Sem o knowledgeC neste servidor (NAS), só há o medido.
      const origem = h.apple_local === false ? 'tracker' : fonte;
      const [sumDev, sumApp, sumCat, tsStacked] = await Promise.all([
        screenTimeApi.byDevice({ ...dateRange, mode, source: origem }),
        screenTimeApi.byApp({ ...dateRange, device_id: filterDevice || undefined, mode, source: origem }),
        screenTimeApi.byCategory({ ...dateRange, device_id: filterDevice || undefined, mode, source: origem }),
        screenTimeApi.timeseriesStacked({ ...dateRange, bucket: cfg.bucket, device_id: filterDevice || undefined, mode, source: origem }),
      ]);
      setByDevice(sumDev);
      setByApp(sumApp);
      setByCategory(sumCat);
      setStackedSeries(tsStacked);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [range, filterDevice, mode, fonte]);
  useEffect(() => { localStorage.setItem('screenTimeSource', fonte); }, [fonte]);
  useEffect(() => { localStorage.setItem('screenTimeMode', mode); }, [mode]);
  useEffect(() => { localStorage.setItem('screenTimeView', view); }, [view]);

  const totalSelected = filterDevice
    ? (byDevice.find(d => d.device_id === filterDevice)?.total_seconds ?? 0)
    : byDevice.reduce((s, r) => s + r.total_seconds, 0);

  if (health && !health.available) {
    return (
      <div className="max-w-3xl mx-auto p-6">
        <h1 className="text-2xl font-bold mb-4">Screen Time (Apple)</h1>
        <div className="rounded-xl border border-yellow-500/40 bg-yellow-500/10 p-5 text-sm space-y-3">
          <div className="flex items-center gap-2 text-yellow-300 font-medium">
            <AlertTriangle size={18} /> Não consigo aceder à DB do Screen Time
          </div>
          <p className="text-zinc-300">{health.reason}</p>
          <p className="text-zinc-400">DB esperada em <code className="bg-black/30 px-1 rounded">{health.db_path}</code></p>
          <div className="text-zinc-300">
            <strong className="text-white">Como dar acesso (opção A — bundle do projecto):</strong>
            <ol className="list-decimal ml-5 mt-2 space-y-1">
              <li>Carrega em <strong>Conceder acesso</strong> — abre o System Settings na página certa.</li>
              <li><strong>Remove TUDO</strong> que tenha que ver com "python", "Python" ou "CristopherBackend" antigo (selecciona e carrega no <strong>−</strong>). Re-assinar invalida entradas antigas.</li>
              <li>Carrega no <strong>+</strong>, faz <code className="bg-black/30 px-1 rounded">Shift+Cmd+G</code> e cola:
                <code className="block mt-1 bg-black/30 p-2 rounded text-xs break-all">
                  ~/Documents/Projects/Cristopher/scripts/launchd/CristopherBackend.app
                </code>
                Adiciona o bundle e activa o toggle.
              </li>
              <li>Corre no terminal <code className="bg-black/30 px-1 rounded">./scripts/launchd/install.sh</code> para reiniciar o backend.</li>
              <li>Volta aqui e carrega em <strong>Tentar de novo</strong>.</li>
            </ol>
            {health.python_app_path && (
              <div className="mt-4 pt-3 border-t border-yellow-500/20">
                <strong className="text-white">Se a opção A não funcionar (frequente em macOS 14+):</strong>
                <p className="mt-1 text-zinc-400">A Apple atribui o pedido de leitura ao binário do Python real, não ao wrapper. Adiciona <strong>também</strong> este path ao FDA:</p>
                <code className="block mt-2 bg-black/30 p-2 rounded text-xs break-all">{health.python_app_path}</code>
                <p className="mt-2 text-zinc-500 text-[11px]">No System Settings carrega no <strong>+</strong> → <code>Shift+Cmd+G</code> → cola o path acima → activa o toggle. Depois faz <strong>Tentar de novo</strong>.</p>
              </div>
            )}
            <p className="mt-3 text-zinc-500 text-[11px]">Para Screen Time do iPhone/iPad aparecer: confirma "Share Across Devices" no Screen Time da Apple.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={async () => {
                try { await screenTimeApi.openSettings(); }
                catch (e: any) { setError(e?.message || 'Falhou ao abrir System Settings'); }
              }}
              className="px-3 py-1.5 rounded-lg bg-blue-500/20 hover:bg-blue-500/30 text-blue-200 text-xs flex items-center gap-1.5 border border-blue-400/40"
            >
              <ExternalLink size={14} /> Conceder acesso
            </button>
            <button onClick={load} className="px-3 py-1.5 rounded-lg bg-yellow-500/20 hover:bg-yellow-500/30 text-yellow-200 text-xs flex items-center gap-1">
              <RefreshCw size={14} /> Tentar de novo
            </button>
          </div>
          {error && (
            <div className="text-xs text-red-300">{error}</div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto p-4 sm:p-6 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-2xl font-bold">Screen Time</h1>
          <div className="inline-flex rounded-lg border border-zinc-700 overflow-hidden">
            <button
              onClick={() => setTab('live')}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${tab === 'live' ? 'bg-zinc-700 text-white' : 'text-zinc-400 hover:bg-zinc-800'}`}
            >
              Resumo
            </button>
            <button
              onClick={() => setTab('stats')}
              className={`px-3 py-1.5 text-xs font-medium transition-colors border-l border-zinc-700 ${tab === 'stats' ? 'bg-zinc-700 text-white' : 'text-zinc-400 hover:bg-zinc-800'}`}
            >
              Estatísticas
            </button>
          </div>
        </div>
        {tab === 'live' && (
          <div className="flex items-center gap-2 flex-wrap">
            <div className={`inline-flex rounded-lg border border-zinc-700 overflow-hidden ${health?.apple_local === false ? 'hidden' : ''}`}
              title="Tracker: medido pela app, bate certo com a duração real dos jogos. Apple: leitura aproximada do Screen Time, mas vê outros dispositivos.">
              <button
                onClick={() => setFonte('tracker')}
                className={`px-2.5 py-1.5 text-xs font-medium flex items-center gap-1 transition-colors ${
                  fonte === 'tracker' ? 'bg-emerald-600/30 text-emerald-200' : 'text-zinc-400 hover:bg-zinc-800'
                }`}
              >
                <Activity size={12} /> Medido
              </button>
              <button
                onClick={() => setFonte('apple')}
                className={`px-2.5 py-1.5 text-xs font-medium flex items-center gap-1 transition-colors border-l border-zinc-700 ${
                  fonte === 'apple' ? 'bg-zinc-700 text-white' : 'text-zinc-400 hover:bg-zinc-800'
                }`}
              >
                <Apple size={12} /> Apple
              </button>
            </div>
            <div className={`inline-flex rounded-lg border border-zinc-700 overflow-hidden ${fonte === 'tracker' || health?.apple_local === false ? 'hidden' : ''}`} title="Algoritmo de agregação">
              <button
                onClick={() => setMode('raw')}
                className={`px-2.5 py-1.5 text-xs font-medium flex items-center gap-1 transition-colors ${
                  mode === 'raw' ? 'bg-zinc-700 text-white' : 'text-zinc-400 hover:bg-zinc-800'
                }`}
              >
                <Database size={12} /> Raw
              </button>
              <button
                onClick={() => setMode('apple')}
                className={`px-2.5 py-1.5 text-xs font-medium flex items-center gap-1 transition-colors border-l border-zinc-700 ${
                  mode === 'apple' ? 'bg-zinc-700 text-white' : 'text-zinc-400 hover:bg-zinc-800'
                }`}
              >
                <Apple size={12} /> Apple
              </button>
            </div>
            {RANGES.map(r => (
              <button key={r.key} onClick={() => setRange(r.key)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                  range === r.key ? 'bg-blue-500/20 border-blue-400 text-blue-300' : 'border-zinc-700 text-zinc-400 hover:bg-zinc-800'
                }`}>
                {r.label}
              </button>
            ))}
            <button onClick={load} className="p-2 rounded-lg hover:bg-zinc-800 text-zinc-400">
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        )}
      </div>


      {error && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">{error}</div>
      )}

      {tab === 'stats' && <StatsTab />}

      {tab === 'live' && (<>

      {/* ── Activity chart ─────────────────────────── */}
      <section className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
        <div className="flex items-baseline justify-between mb-3">
          <div>
            <div className="text-xs text-zinc-500 uppercase tracking-wide">
              {range === 'today' ? 'Hoje' : range === 'week' ? 'Total últimos 7 dias' : 'Total últimos 30 dias'}
              {filterDevice && <span className="ml-1 normal-case text-blue-400">· {deviceTitle(byDevice.find(d => d.device_id === filterDevice) || { device_id: filterDevice })}</span>}
            </div>
            <div className="text-3xl font-bold mt-0.5">{fmtBigDuration(totalSelected)}</div>
          </div>
          {range !== 'today' && cfg.days > 0 && (
            <div className="text-right">
              {/* Só os dias com leitura, como a linha do gráfico: um dia sem nada
                  é o Mac desligado, não um dia sem ecrã. */}
              <div className="text-xs text-zinc-500">Média / dia</div>
              <div className="text-lg font-mono text-emerald-300">
                {fmtDuration(totalSelected / (stackedSeries.filter(b => Object.values(b.categories).some(v => v > 0)).length || cfg.days))}
              </div>
            </div>
          )}
        </div>
        <StackedActivityChart series={stackedSeries} bucket={cfg.bucket} totalSeconds={totalSelected} />
      </section>

      <Metas />

      {/* ── Categorias / Apps & Websites (toggle) ─────── */}
      <section className="rounded-xl border border-zinc-800 bg-zinc-900/50">
        <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between gap-2">
          <div className="inline-flex rounded-lg border border-zinc-700 overflow-hidden">
            <button
              onClick={() => setView('categories')}
              className={`px-3 py-1.5 text-xs font-medium flex items-center gap-1.5 ${
                view === 'categories' ? 'bg-zinc-700 text-white' : 'text-zinc-400 hover:bg-zinc-800'
              }`}
            >
              <Layers size={13} /> Categorias
            </button>
            <button
              onClick={() => setView('apps')}
              className={`px-3 py-1.5 text-xs font-medium flex items-center gap-1.5 border-l border-zinc-700 ${
                view === 'apps' ? 'bg-zinc-700 text-white' : 'text-zinc-400 hover:bg-zinc-800'
              }`}
            >
              <Briefcase size={13} /> Apps &amp; Websites
            </button>
          </div>
          <span className="text-xs text-zinc-500">
            {view === 'categories'
              ? (byCategory.length > 1 ? `${byCategory.length - 1} ${byCategory.length - 1 === 1 ? 'categoria' : 'categorias'}` : '—')
              : `${byApp.length} apps`}
          </span>
        </div>

        {view === 'categories' ? (
          byCategory.length === 0 ? (
            <div className="p-6 text-center text-sm text-zinc-500">Sem dados no intervalo.</div>
          ) : (
            <ul className="divide-y divide-zinc-800">
              {byCategory.map(c => {
                const meta = CATEGORY_META[c.category] ?? CATEGORY_META['Other'];
                const Icon = meta.Icon;
                const isAll = c.category === 'All Usage';
                const isOpen = expandedCategory === c.category;
                const appsInCat = byApp.filter(a => a.category === c.category);
                return (
                  <li key={c.category}>
                    <div
                      onClick={() => !isAll && setExpandedCategory(isOpen ? null : c.category)}
                      className={`flex items-center gap-3 px-4 py-2.5 ${isAll ? 'bg-zinc-800/40' : 'cursor-pointer hover:bg-zinc-800/40'}`}
                    >
                      <div
                        className={`flex items-center justify-center w-7 h-7 rounded-md ${meta.color}`}
                        style={!isAll ? { backgroundColor: (CATEGORY_FILL[c.category] || '#52525b') + '22' } : { backgroundColor: 'rgb(39 39 42)' }}
                      >
                        <Icon size={15} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className={`text-sm ${isAll ? 'font-semibold text-white' : 'text-zinc-200'}`}>{c.category}</div>
                        {!isAll && (
                          <div className="text-xs text-zinc-500">{c.app_count} {c.app_count === 1 ? 'app' : 'apps'}</div>
                        )}
                      </div>
                      <div className={`font-mono text-sm tabular-nums ${isAll ? 'text-white font-semibold' : 'text-zinc-300'}`}>
                        {fmtDuration(c.total_seconds)}
                      </div>
                      {!isAll && (
                        <span className={`text-zinc-500 transition-transform ${isOpen ? 'rotate-90' : ''}`}>›</span>
                      )}
                    </div>
                    {!isAll && isOpen && (
                      <ul className="bg-zinc-950/50 border-t border-zinc-800">
                        {appsInCat.length === 0 ? (
                          <li className="px-4 py-3 text-xs text-zinc-500 pl-14">Sem apps nesta categoria no intervalo.</li>
                        ) : appsInCat.map((a, i) => {
                          const top = appsInCat[0]?.total_seconds || 1;
                          const pct = (a.total_seconds / top) * 100;
                          return (
                            <li key={`${a.device_id}-${a.bundle_id}-${i}`} className="relative pl-14 pr-4 py-2">
                              <div className="absolute inset-y-0 left-12 right-0 pointer-events-none" style={{ width: `${pct}%`, backgroundColor: (CATEGORY_FILL[c.category] || '#52525b') + '10' }} />
                              <div className="relative flex items-center gap-3">
                                <AppIcon bundleId={a.bundle_id} category={c.category} size={24} />
                                <div className="flex-1 min-w-0">
                                  <div className="text-sm truncate">{bundleToFriendly(a.bundle_id)}</div>
                                  <div className="text-[11px] text-zinc-500 truncate">{a.bundle_id}</div>
                                </div>
                                <div className="text-xs font-mono text-zinc-300">{fmtDuration(a.total_seconds)}</div>
                              </div>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>
          )
        ) : (
          byApp.length === 0 ? (
            <p className="p-4 text-sm text-zinc-500">Sem dados.</p>
          ) : (
            <ul className="divide-y divide-zinc-800 max-h-[600px] overflow-y-auto">
              {byApp.slice(0, 200).map((a, i) => {
                const cat = a.category;
                const top = byApp[0]?.total_seconds || 1;
                const pct = (a.total_seconds / top) * 100;
                return (
                  <li key={`${a.device_id}-${a.bundle_id}-${i}`} className="px-4 py-2.5 relative">
                    <div className="absolute inset-y-0 left-0 pointer-events-none" style={{ width: `${pct}%`, backgroundColor: (CATEGORY_FILL[cat] || '#52525b') + '15' }} />
                    <div className="relative flex items-center gap-3">
                      <AppIcon bundleId={a.bundle_id} category={cat} size={32} />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm truncate">{bundleToFriendly(a.bundle_id)}</div>
                        <div className="text-[11px] text-zinc-500 truncate">{cat} · {a.bundle_id}</div>
                      </div>
                      <div className="text-sm font-mono text-zinc-300">{fmtDuration(a.total_seconds)}</div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )
        )}
      </section>

      {/* ── Devices ─────────────────────────────────── */}
      <section className="rounded-xl border border-zinc-800 bg-zinc-900/50">
        <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
          <h2 className="font-semibold">Devices</h2>
          <span className="text-xs text-zinc-500">{byDevice.length} {byDevice.length === 1 ? 'device' : 'devices'}</span>
        </div>
        {byDevice.length === 0 ? (
          <p className="p-4 text-sm text-zinc-500">Sem dados no intervalo.</p>
        ) : (
          <ul className="divide-y divide-zinc-800">
            {byDevice.map(d => {
              const Icon = kindIcon(d.kind);
              const totalAll = byDevice.reduce((s, r) => s + r.total_seconds, 0);
              const pct = totalAll > 0 ? (d.total_seconds / totalAll) * 100 : 0;
              const isFiltered = filterDevice === d.device_id;
              return (
                <li key={d.device_id}
                  onClick={() => setFilterDevice(isFiltered ? '' : d.device_id)}
                  className={`px-4 py-3 cursor-pointer flex items-center gap-3 hover:bg-zinc-800/50 ${isFiltered ? 'bg-blue-500/10' : ''}`}>
                  <Icon size={18} className="text-zinc-400 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate">{deviceTitle(d)}</div>
                    <div className="text-xs text-zinc-500">{d.app_count} apps · {d.session_count} sessões · {pct.toFixed(0)}%</div>
                  </div>
                  <div className="text-sm font-mono text-zinc-300">{fmtDuration(d.total_seconds)}</div>
                </li>
              );
            })}
          </ul>
        )}
        {filterDevice && (
          <div className="px-4 py-2 border-t border-zinc-800 text-xs text-zinc-400 flex items-center justify-between">
            <span>A filtrar por device.</span>
            <button onClick={() => setFilterDevice('')} className="underline hover:text-white">Limpar</button>
          </div>
        )}
      </section>

      </>)}

    </div>
  );
}
