import { useEffect, useMemo, useState } from 'react';
import { format, subDays } from 'date-fns';
import { Smartphone, Tablet, Monitor, Watch, HelpCircle, RefreshCw, AlertTriangle, ExternalLink, Apple, Database, MessageCircle, Briefcase, Palette, Plane, Gamepad2, Wrench, Music, BookOpen, Layers } from 'lucide-react';
import {
  screenTimeApi, ScreenTimeDevice, ScreenTimeAppRow, ScreenTimeDeviceRow, ScreenTimeCategoryRow,
} from '../api';

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

// Ordem de stack das categorias (de baixo para cima). Coincide com CATEGORY_META
// definida mais abaixo — mantém-se duplicada aqui para evitar dependency cycle.
const CATEGORY_STACK_ORDER = [
  'Social',
  'Productivity & Finance',
  'Creativity',
  'Travel',
  'Games',
  'Utilities',
  'Entertainment',
  'Information & Reading',
  'Other',
];

const CATEGORY_FILL: Record<string, string> = {
  'Social': '#60a5fa',
  'Productivity & Finance': '#a78bfa',
  'Creativity': '#fb923c',
  'Travel': '#38bdf8',
  'Games': '#f472b6',
  'Utilities': '#a1a1aa',
  'Entertainment': '#f87171',
  'Information & Reading': '#34d399',
  'Other': '#52525b',
};

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

export default function ScreenTimePage() {
  const [health, setHealth] = useState<{ available: boolean; reason: string; db_path: string; python_app_path?: string } | null>(null);
  const [devices, setDevices] = useState<ScreenTimeDevice[]>([]);
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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>('');
  const [editing, setEditing] = useState<string | null>(null);
  const [editLabel, setEditLabel] = useState('');
  const [editKind, setEditKind] = useState<string>('unknown');

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
      const [devs, sumDev, sumApp, sumCat, tsStacked] = await Promise.all([
        screenTimeApi.devices(),
        screenTimeApi.byDevice({ ...dateRange, mode }),
        screenTimeApi.byApp({ ...dateRange, device_id: filterDevice || undefined, mode }),
        screenTimeApi.byCategory({ ...dateRange, device_id: filterDevice || undefined, mode }),
        screenTimeApi.timeseriesStacked({ ...dateRange, bucket: cfg.bucket, device_id: filterDevice || undefined, mode }),
      ]);
      setDevices(devs);
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

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [range, filterDevice, mode]);
  useEffect(() => { localStorage.setItem('screenTimeMode', mode); }, [mode]);
  useEffect(() => { localStorage.setItem('screenTimeView', view); }, [view]);

  const totalSelected = filterDevice
    ? (byDevice.find(d => d.device_id === filterDevice)?.total_seconds ?? 0)
    : byDevice.reduce((s, r) => s + r.total_seconds, 0);

  function startEdit(d: ScreenTimeDevice) {
    setEditing(d.device_id);
    setEditLabel(d.label || '');
    setEditKind(d.kind || 'unknown');
  }
  async function saveEdit() {
    if (!editing) return;
    try {
      await screenTimeApi.labelDevice(editing, { label: editLabel.trim(), kind: editKind });
      setEditing(null);
      load();
    } catch (e: any) {
      setError(e?.message || String(e));
    }
  }

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
        <h1 className="text-2xl font-bold">Screen Time</h1>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="inline-flex rounded-lg border border-zinc-700 overflow-hidden" title="Algoritmo de agregação">
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
      </div>


      {error && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">{error}</div>
      )}

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
              <div className="text-xs text-zinc-500">Média / dia</div>
              <div className="text-lg font-mono text-emerald-300">{fmtDuration(totalSelected / cfg.days)}</div>
            </div>
          )}
        </div>
        <StackedActivityChart series={stackedSeries} bucket={cfg.bucket} totalSeconds={totalSelected} />
      </section>

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

      {/* ── Etiquetas dos devices ──────────────────── */}
      <section className="rounded-xl border border-zinc-800 bg-zinc-900/50">
        <div className="px-4 py-3 border-b border-zinc-800">
          <h2 className="font-semibold">Identificar devices</h2>
          <p className="text-xs text-zinc-500 mt-0.5">Dá um nome a cada device para distinguires Mac, iPhone e iPad nas listas.</p>
        </div>
        <ul className="divide-y divide-zinc-800">
          {devices.map(d => {
            const Icon = kindIcon(d.kind);
            const isEditing = editing === d.device_id;
            return (
              <li key={d.device_id} className="px-4 py-3">
                {isEditing ? (
                  <div className="flex items-center gap-2 flex-wrap">
                    <input value={editLabel} onChange={e => setEditLabel(e.target.value)}
                      placeholder="ex: iPhone do Cris"
                      className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-sm flex-1 min-w-[160px]" />
                    <select value={editKind} onChange={e => setEditKind(e.target.value)}
                      className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-sm">
                      {KIND_OPTIONS.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
                    </select>
                    <button onClick={saveEdit} className="px-3 py-1 rounded bg-blue-500/20 text-blue-300 text-xs">Guardar</button>
                    <button onClick={() => setEditing(null)} className="px-3 py-1 rounded bg-zinc-800 text-zinc-400 text-xs">Cancelar</button>
                  </div>
                ) : (
                  <div onClick={() => startEdit(d)} className="flex items-center gap-3 cursor-pointer hover:bg-zinc-800/30 -mx-2 px-2 py-1 rounded">
                    <Icon size={16} className="text-zinc-400" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm">{d.label || <span className="text-zinc-500 italic">sem nome</span>}</div>
                      <div className="text-[11px] text-zinc-600 font-mono truncate">{d.device_id}</div>
                    </div>
                    <span className="text-xs text-zinc-500">{d.event_count} eventos</span>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </section>

    </div>
  );
}
