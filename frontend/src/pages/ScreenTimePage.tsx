import { useEffect, useMemo, useState } from 'react';
import { format, subDays } from 'date-fns';
import { Smartphone, Tablet, Monitor, Watch, HelpCircle, RefreshCw, AlertTriangle } from 'lucide-react';
import {
  screenTimeApi, ScreenTimeDevice, ScreenTimeAppRow, ScreenTimeDeviceRow,
} from '../api';

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

function bundleToFriendly(bundle: string): string {
  // com.apple.mobilesafari → Safari ; com.burbn.instagram → Instagram
  const last = bundle.split('.').pop() || bundle;
  return last.replace(/^mobile/i, '').replace(/^[a-z]/, c => c.toUpperCase());
}

function deviceTitle(d: { device_id: string; label?: string; kind?: string }) {
  if (d.label) return d.label;
  if (d.device_id === '__local__') return 'Este Mac (local)';
  return d.device_id.slice(0, 8) + '…';
}

export default function ScreenTimePage() {
  const [health, setHealth] = useState<{ available: boolean; reason: string; db_path: string } | null>(null);
  const [devices, setDevices] = useState<ScreenTimeDevice[]>([]);
  const [byDevice, setByDevice] = useState<ScreenTimeDeviceRow[]>([]);
  const [byApp, setByApp] = useState<ScreenTimeAppRow[]>([]);
  const [filterDevice, setFilterDevice] = useState<string>('');
  const [days, setDays] = useState<number>(7);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>('');
  const [editing, setEditing] = useState<string | null>(null);
  const [editLabel, setEditLabel] = useState('');
  const [editKind, setEditKind] = useState<string>('unknown');

  const dateRange = useMemo(() => {
    const today = new Date();
    return {
      start_date: format(subDays(today, days - 1), 'yyyy-MM-dd'),
      end_date: format(today, 'yyyy-MM-dd'),
    };
  }, [days]);

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
      const [devs, sumDev, sumApp] = await Promise.all([
        screenTimeApi.devices(),
        screenTimeApi.byDevice(dateRange),
        screenTimeApi.byApp({ ...dateRange, device_id: filterDevice || undefined }),
      ]);
      setDevices(devs);
      setByDevice(sumDev);
      setByApp(sumApp);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [days, filterDevice]);

  const totalAllDevices = byDevice.reduce((s, r) => s + r.total_seconds, 0);

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
            <strong className="text-white">O que fazer:</strong>
            <ol className="list-decimal ml-5 mt-2 space-y-1">
              <li>Abre <em>System Settings → Privacy &amp; Security → Full Disk Access</em></li>
              <li>Carrega no <strong>+</strong> e adiciona o <code className="bg-black/30 px-1 rounded">python3</code> do venv:
                <code className="block mt-1 bg-black/30 p-2 rounded text-xs break-all">
                  ~/Documents/Projects/Cristopher/backend/venv/bin/python3
                </code>
              </li>
              <li>Reinicia o backend (<code className="bg-black/30 px-1 rounded">./scripts/launchd/install.sh</code>)</li>
              <li>Confirma que tens "Share Across Devices" activo no Screen Time do iPhone/iPad</li>
            </ol>
          </div>
          <button onClick={load} className="px-3 py-1.5 rounded-lg bg-yellow-500/20 hover:bg-yellow-500/30 text-yellow-200 text-xs flex items-center gap-1">
            <RefreshCw size={14} /> Tentar de novo
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Screen Time</h1>
        <div className="flex items-center gap-2">
          {[1, 7, 30].map(n => (
            <button key={n} onClick={() => setDays(n)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                days === n ? 'bg-blue-500/20 border-blue-400 text-blue-300' : 'border-zinc-700 text-zinc-400 hover:bg-zinc-800'
              }`}>
              {n === 1 ? 'Hoje' : `${n} dias`}
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

      {/* ── Devices ─────────────────────────────────── */}
      <section className="rounded-xl border border-zinc-800 bg-zinc-900/50">
        <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
          <h2 className="font-semibold">Devices</h2>
          <span className="text-xs text-zinc-500">Total: {fmtDuration(totalAllDevices)}</span>
        </div>
        {byDevice.length === 0 ? (
          <p className="p-4 text-sm text-zinc-500">Sem dados no intervalo.</p>
        ) : (
          <ul className="divide-y divide-zinc-800">
            {byDevice.map(d => {
              const Icon = kindIcon(d.kind);
              const pct = totalAllDevices > 0 ? (d.total_seconds / totalAllDevices) * 100 : 0;
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
                      className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-sm flex-1 min-max-w-[90vw] w-[160px]" />
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

      {/* ── Apps ───────────────────────────────────── */}
      <section className="rounded-xl border border-zinc-800 bg-zinc-900/50">
        <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
          <h2 className="font-semibold">Apps {filterDevice && <span className="text-xs text-zinc-500 ml-1">(filtrado)</span>}</h2>
          <span className="text-xs text-zinc-500">{byApp.length} apps</span>
        </div>
        {byApp.length === 0 ? (
          <p className="p-4 text-sm text-zinc-500">Sem dados.</p>
        ) : (
          <ul className="divide-y divide-zinc-800 max-h-[600px] overflow-y-auto">
            {byApp.slice(0, 200).map((a, i) => {
              const Icon = kindIcon(a.kind);
              const top = byApp[0]?.total_seconds || 1;
              const pct = (a.total_seconds / top) * 100;
              return (
                <li key={`${a.device_id}-${a.bundle_id}-${i}`} className="px-4 py-2.5 relative">
                  <div className="absolute inset-y-0 left-0 bg-blue-500/5" style={{ width: `${pct}%` }} />
                  <div className="relative flex items-center gap-3">
                    <Icon size={14} className="text-zinc-500 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm truncate">{bundleToFriendly(a.bundle_id)}</div>
                      <div className="text-[11px] text-zinc-500 truncate">
                        {a.bundle_id} · {a.label || a.device_id.slice(0, 8)}
                      </div>
                    </div>
                    <div className="text-sm font-mono text-zinc-300">{fmtDuration(a.total_seconds)}</div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
