import { useEffect, useMemo, useState } from 'react';
import { format, parseISO, subDays } from 'date-fns';
import { pt } from 'date-fns/locale';
import { Plus, Trash2, X, Brain, Sparkles, GitBranch, Sunrise, Target, Award } from 'lucide-react';
import {
  appInsightsApi, appGoalsApi,
  FocusScoreDay, Correlation, TransitionRow, DeepWorkHour,
  AppGoalProgress,
} from '../api';

const PRODUCTIVE_CATEGORIES = ['development', 'productivity', 'communication'];
const ALL_CATEGORIES = [
  { id: 'productivity', label: 'Produtividade', color: '#10B981' },
  { id: 'development', label: 'Desenvolvimento', color: '#3B82F6' },
  { id: 'communication', label: 'Comunicação', color: '#06B6D4' },
  { id: 'social', label: 'Social', color: '#EC4899' },
  { id: 'gaming', label: 'Gaming', color: '#EF4444' },
  { id: 'entertainment', label: 'Entretenimento', color: '#8B5CF6' },
  { id: 'browser', label: 'Browser', color: '#F59E0B' },
  { id: 'system', label: 'Sistema', color: '#6B7280' },
];

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem ? `${h}h ${rem}m` : `${h}h`;
}

function scoreColor(score: number): string {
  if (score >= 75) return '#10B981';
  if (score >= 50) return '#3B82F6';
  if (score >= 25) return '#F59E0B';
  return '#EF4444';
}

// ── Insights tab ──────────────────────────────────────────────────

export function InsightsTab({ startStr, endStr }: { startStr: string; endStr: string }) {
  const [focus, setFocus] = useState<{ average: number | null; series: FocusScoreDay[]; best_day: FocusScoreDay | null; worst_day: FocusScoreDay | null } | null>(null);
  const [correlations, setCorrelations] = useState<Correlation[]>([]);
  const [transitions, setTransitions] = useState<TransitionRow[]>([]);
  const [deepWork, setDeepWork] = useState<DeepWorkHour[] | null>(null);
  const [bestHour, setBestHour] = useState<DeepWorkHour | null>(null);
  const [worstHour, setWorstHour] = useState<DeepWorkHour | null>(null);
  const [firstDistraction, setFirstDistraction] = useState<{ samples: number; median_minutes: number | null; mean_minutes: number | null } | null>(null);
  const [windowDays, setWindowDays] = useState(30);

  useEffect(() => {
    Promise.all([
      appInsightsApi.focusScore(startStr, endStr),
      appInsightsApi.correlations(windowDays),
      appInsightsApi.transitions(windowDays, 12),
      appInsightsApi.deepWork(windowDays),
      appInsightsApi.firstDistraction(windowDays),
    ]).then(([f, c, t, d, fd]) => {
      setFocus(f);
      setCorrelations(c.insights);
      setTransitions(t.transitions);
      setDeepWork(d.hours);
      setBestHour(d.best_hour);
      setWorstHour(d.worst_hour);
      setFirstDistraction(fd);
    });
  }, [startStr, endStr, windowDays]);

  return (
    <div className="space-y-4">
      {/* Window selector */}
      <div className="flex items-center justify-between bg-[#161616] border border-[#222] rounded-xl p-3">
        <div className="text-xs text-gray-500">
          <span className="font-medium text-gray-400">Focus score</span> usa o período selecionado em cima.
          Os outros insights usam uma janela móvel:
        </div>
        <div className="flex bg-black/30 rounded-lg p-1">
          {[7, 30, 90].map(d => (
            <button
              key={d}
              onClick={() => setWindowDays(d)}
              className={`px-3 py-1 text-xs font-medium rounded ${
                windowDays === d ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      <FocusScoreCard focus={focus} />

      <div className="grid grid-cols-2 gap-4">
        <BestHourCard best={bestHour} worst={worstHour} firstDistraction={firstDistraction} />
        <DeepWorkChart hours={deepWork} />
      </div>

      <CorrelationsCard correlations={correlations} windowDays={windowDays} />
      <TransitionsCard transitions={transitions} windowDays={windowDays} />
    </div>
  );
}

function FocusScoreCard({ focus }: { focus: { average: number | null; series: FocusScoreDay[]; best_day: FocusScoreDay | null; worst_day: FocusScoreDay | null } | null }) {
  if (!focus) {
    return <div className="bg-[#161616] border border-[#222] rounded-xl p-6 text-sm text-gray-500">A calcular focus score…</div>;
  }
  const avg = focus.average;
  const color = avg != null ? scoreColor(avg) : '#6B7280';
  const series = focus.series.filter(d => d.score !== null);
  const max = Math.max(100, ...series.map(d => d.score ?? 0));

  return (
    <div className="bg-[#161616] border border-[#222] rounded-xl p-5">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide flex items-center gap-2 mb-1">
            <Brain size={14} /> Focus score
          </h2>
          <p className="text-xs text-gray-500">0–100 baseado em produtividade, deep work, switches e distrações em Flow</p>
        </div>
        <div className="text-right">
          <div className="text-5xl font-bold" style={{ color }}>
            {avg != null ? avg.toFixed(0) : '—'}
          </div>
          <div className="text-[10px] text-gray-500">média do período</div>
        </div>
      </div>

      {/* Daily bars */}
      {focus.series.length > 0 && (
        <div className="flex items-end gap-1 h-20 mt-4">
          {focus.series.map(d => {
            const sc = d.score ?? 0;
            const h = sc / max;
            return (
              <div
                key={d.date}
                className="flex-1 flex flex-col items-center justify-end group relative"
                title={d.score != null ? `${format(parseISO(d.date), 'd MMM', { locale: pt })}: ${d.score} (${d.deep_work_blocks} blocks deep, ${d.context_switches} switches)` : `${format(parseISO(d.date), 'd MMM', { locale: pt })}: sem dados`}
              >
                <div
                  className="w-full rounded-sm transition-opacity"
                  style={{
                    height: d.score != null ? `${Math.max(2, h * 100)}%` : '2px',
                    backgroundColor: d.score != null ? scoreColor(sc) : '#333',
                    opacity: d.score != null ? 1 : 0.3,
                  }}
                />
              </div>
            );
          })}
        </div>
      )}

      {(focus.best_day || focus.worst_day) && (
        <div className="grid grid-cols-2 gap-3 mt-4 text-xs">
          {focus.best_day && (
            <div className="rounded-lg bg-green-500/10 border border-green-500/30 p-2">
              <div className="text-green-400 font-medium">Melhor dia</div>
              <div className="text-gray-400">
                {format(parseISO(focus.best_day.date), "d 'de' MMM", { locale: pt })} · {focus.best_day.score} pts
              </div>
              <div className="text-gray-600 text-[10px]">
                {focus.best_day.deep_work_blocks} deep blocks · {formatDuration(focus.best_day.productive_seconds)} produtivo
              </div>
            </div>
          )}
          {focus.worst_day && focus.best_day?.date !== focus.worst_day.date && (
            <div className="rounded-lg bg-red-500/10 border border-red-500/30 p-2">
              <div className="text-red-400 font-medium">Pior dia</div>
              <div className="text-gray-400">
                {format(parseISO(focus.worst_day.date), "d 'de' MMM", { locale: pt })} · {focus.worst_day.score} pts
              </div>
              <div className="text-gray-600 text-[10px]">
                {focus.worst_day.context_switches} switches · {formatDuration(focus.worst_day.distraction_seconds)} distração
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function BestHourCard({ best, worst, firstDistraction }: { best: DeepWorkHour | null; worst: DeepWorkHour | null; firstDistraction: { samples: number; median_minutes: number | null; mean_minutes: number | null } | null }) {
  return (
    <div className="bg-[#161616] border border-[#222] rounded-xl p-5">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide flex items-center gap-2 mb-3">
        <Sunrise size={14} /> Hora mais produtiva
      </h2>
      {best ? (
        <div className="space-y-3">
          <div>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-bold text-green-400">
                {best.hour.toString().padStart(2, '0')}:00
              </span>
              <span className="text-sm text-gray-500">— {best.score} pts</span>
            </div>
            <div className="text-xs text-gray-500 mt-1">
              {formatDuration(best.productive_seconds)} produtivo nesta hora ao longo do período
            </div>
          </div>
          {worst && worst.hour !== best.hour && (
            <div>
              <div className="text-xs text-gray-500">Pior hora</div>
              <div className="text-lg font-semibold text-red-400">
                {worst.hour.toString().padStart(2, '0')}:00 · {worst.score} pts
              </div>
            </div>
          )}
          {firstDistraction && firstDistraction.samples > 0 && firstDistraction.median_minutes != null && (
            <div className="pt-3 border-t border-[#222]">
              <div className="text-xs text-gray-500">Tempo até primeira distração</div>
              <div className="text-lg font-semibold">
                {Math.round(firstDistraction.median_minutes)}min <span className="text-xs text-gray-500 font-normal">mediano</span>
              </div>
              <div className="text-[10px] text-gray-600">{firstDistraction.samples} dias amostrados</div>
            </div>
          )}
        </div>
      ) : (
        <p className="text-sm text-gray-500">Sem dados suficientes.</p>
      )}
    </div>
  );
}

function DeepWorkChart({ hours }: { hours: DeepWorkHour[] | null }) {
  if (!hours) return <div className="bg-[#161616] border border-[#222] rounded-xl p-5 text-sm text-gray-500">A carregar…</div>;
  const max = Math.max(1, ...hours.map(h => h.total_seconds));

  return (
    <div className="bg-[#161616] border border-[#222] rounded-xl p-5">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
        Produtividade por hora do dia
      </h2>
      <div className="flex items-end gap-px h-24">
        {hours.map(h => {
          const bar = h.total_seconds / max;
          const sc = h.score ?? 0;
          const color = h.score != null ? scoreColor(sc) : '#222';
          return (
            <div
              key={h.hour}
              className="flex-1 group relative cursor-help"
              title={
                h.score != null
                  ? `${h.hour.toString().padStart(2, '0')}:00 — score ${h.score} (${formatDuration(h.productive_seconds)}/${formatDuration(h.total_seconds)})`
                  : `${h.hour.toString().padStart(2, '0')}:00 — sem dados`
              }
            >
              <div
                className="w-full rounded-sm"
                style={{ height: `${Math.max(2, bar * 100)}%`, backgroundColor: color, opacity: h.score != null ? 1 : 0.2 }}
              />
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-[9px] text-gray-600 mt-1">
        <span>00</span><span>06</span><span>12</span><span>18</span><span>23</span>
      </div>
    </div>
  );
}

function CorrelationsCard({ correlations, windowDays }: { correlations: Correlation[]; windowDays: number }) {
  return (
    <div className="bg-[#161616] border border-[#222] rounded-xl p-5">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide flex items-center gap-2 mb-3">
        <Sparkles size={14} /> Correlações com mood, sono, hábitos & LoL
      </h2>
      {correlations.length === 0 ? (
        <p className="text-sm text-gray-500">
          Sem padrões fortes detetados nos últimos {windowDays} dias. Precisa de pelo menos 3 dias de cada lado para fazer comparação.
        </p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {correlations.map((c, i) => (
            <div key={i} className="rounded-lg p-3 border border-[#222] bg-black/20">
              <div className="text-sm">{c.text}</div>
              <div className="text-[10px] text-gray-600 mt-1">
                {c.samples_high} dias com · {c.samples_low} dias sem
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TransitionsCard({ transitions, windowDays }: { transitions: TransitionRow[]; windowDays: number }) {
  if (transitions.length === 0) {
    return (
      <div className="bg-[#161616] border border-[#222] rounded-xl p-5 text-sm text-gray-500">
        Sem transições registadas em {windowDays} dias.
      </div>
    );
  }
  return (
    <div className="bg-[#161616] border border-[#222] rounded-xl p-5">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide flex items-center gap-2 mb-3">
        <GitBranch size={14} /> Padrões de transição
      </h2>
      <p className="text-xs text-gray-500 mb-3">
        "Depois de X, o que vem a seguir?" — top transições nos últimos {windowDays} dias.
      </p>
      <div className="space-y-1.5">
        {transitions.map((t, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className="font-medium truncate flex-1 text-right">{t.from_app}</span>
            <span className="text-gray-600">→</span>
            <span className="font-medium truncate flex-1">{t.to_app}</span>
            <span className="text-gray-500 shrink-0 w-16 text-right">{t.count}× · {t.pct_from}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Goals tab ─────────────────────────────────────────────────────

export function GoalsTab() {
  const [progress, setProgress] = useState<{ date: string; goals: AppGoalProgress[] } | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  async function refresh() {
    setProgress(await appGoalsApi.progress());
  }
  useEffect(() => { refresh(); }, []);

  async function handleDelete(id: number) {
    if (!confirm('Apagar este objetivo?')) return;
    await appGoalsApi.delete(id);
    refresh();
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between bg-[#161616] border border-[#222] rounded-xl p-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide flex items-center gap-2">
            <Target size={14} /> Objetivos diários
          </h2>
          <p className="text-xs text-gray-500 mt-1">Define limites (máx) e mínimos por categoria. Streaks contam dias consecutivos atingidos.</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="px-3 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm font-medium flex items-center gap-1"
        >
          <Plus size={14} /> Novo
        </button>
      </div>

      {progress && progress.goals.length === 0 && (
        <div className="bg-[#161616] border border-[#222] rounded-xl p-8 text-center">
          <Target size={36} className="mx-auto text-gray-600 mb-3" />
          <p className="text-sm text-gray-500">Sem objetivos. Cria o primeiro para começar a fazer streaks.</p>
        </div>
      )}

      {progress && progress.goals.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {progress.goals.map(g => (
            <GoalCard key={g.id} goal={g} onDelete={handleDelete} />
          ))}
        </div>
      )}

      {showCreate && <CreateGoalModal onClose={() => { setShowCreate(false); refresh(); }} />}
    </div>
  );
}

function GoalCard({ goal, onDelete }: { goal: AppGoalProgress; onDelete: (id: number) => void }) {
  const isMax = goal.direction === 'max';
  const pct = Math.min(100, goal.percentage);
  const ok = goal.on_track;
  const barColor = isMax ? (ok ? '#10B981' : '#EF4444') : (ok ? '#10B981' : goal.color);

  return (
    <div className="bg-[#161616] border border-[#222] rounded-xl p-4 group relative">
      <button
        onClick={() => onDelete(goal.id)}
        className="absolute top-2 right-2 p-1 rounded text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100"
      >
        <Trash2 size={14} />
      </button>
      <div className="flex items-center gap-2 mb-2">
        <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: goal.color }} />
        <span className="font-semibold text-sm">{goal.label}</span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
          isMax ? 'bg-red-500/20 text-red-400' : 'bg-green-500/20 text-green-400'
        }`}>
          {isMax ? 'máx' : 'mín'} {formatDuration(goal.target_seconds)}
        </span>
      </div>

      <div className="flex items-baseline gap-2 mb-2">
        <span className="text-2xl font-bold" style={{ color: barColor }}>
          {formatDuration(goal.today_seconds)}
        </span>
        <span className="text-xs text-gray-500">hoje</span>
      </div>

      <div className="h-2 rounded-full bg-black/40 overflow-hidden mb-3">
        <div
          className="h-full transition-all"
          style={{ width: `${pct}%`, backgroundColor: barColor }}
        />
      </div>

      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-1.5 text-gray-400">
          <Award size={12} className="text-amber-400" />
          <span><span className="font-bold text-amber-400">{goal.current_streak}</span>d streak</span>
        </div>
        <div className="text-gray-600">recorde: {goal.best_streak}d</div>
      </div>
    </div>
  );
}

function CreateGoalModal({ onClose }: { onClose: () => void }) {
  const [category, setCategory] = useState('gaming');
  const [direction, setDirection] = useState<'min' | 'max'>('max');
  const [hours, setHours] = useState('2');
  const [minutes, setMinutes] = useState('0');

  async function submit() {
    const total = parseInt(hours, 10) * 3600 + parseInt(minutes, 10) * 60;
    if (total <= 0) {
      alert('Define um tempo válido');
      return;
    }
    try {
      await appGoalsApi.create({ category, direction, target_seconds: total });
      onClose();
    } catch (e: any) {
      alert(e.message || 'Erro');
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-[#161616] border border-[#333] rounded-2xl p-6 max-w-md w-full mx-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold">Novo objetivo</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-white/10"><X size={18} /></button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Categoria</label>
            <select
              value={category}
              onChange={e => setCategory(e.target.value)}
              className="w-full px-3 py-2 bg-black/30 border border-[#333] rounded-lg text-sm"
            >
              {ALL_CATEGORIES.map(c => (
                <option key={c.id} value={c.id}>{c.label}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs text-gray-500 mb-1 block">Direção</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => setDirection('max')}
                className={`px-3 py-2 rounded-lg text-sm font-medium border ${
                  direction === 'max' ? 'border-red-500 bg-red-500/10 text-red-400' : 'border-[#333] text-gray-400'
                }`}
              >
                Máximo
              </button>
              <button
                onClick={() => setDirection('min')}
                className={`px-3 py-2 rounded-lg text-sm font-medium border ${
                  direction === 'min' ? 'border-green-500 bg-green-500/10 text-green-400' : 'border-[#333] text-gray-400'
                }`}
              >
                Mínimo
              </button>
            </div>
          </div>

          <div>
            <label className="text-xs text-gray-500 mb-1 block">Alvo (por dia)</label>
            <div className="flex gap-2">
              <div className="flex-1">
                <input
                  type="number"
                  min={0}
                  value={hours}
                  onChange={e => setHours(e.target.value)}
                  className="w-full px-3 py-2 bg-black/30 border border-[#333] rounded-lg text-sm"
                  placeholder="Horas"
                />
                <div className="text-[10px] text-gray-600 mt-1">horas</div>
              </div>
              <div className="flex-1">
                <input
                  type="number"
                  min={0}
                  max={59}
                  value={minutes}
                  onChange={e => setMinutes(e.target.value)}
                  className="w-full px-3 py-2 bg-black/30 border border-[#333] rounded-lg text-sm"
                  placeholder="Minutos"
                />
                <div className="text-[10px] text-gray-600 mt-1">minutos</div>
              </div>
            </div>
          </div>

          <button
            onClick={submit}
            className="w-full px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm font-medium"
          >
            Criar objetivo
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Distraction toast ─────────────────────────────────────────────

export function DistractionToast() {
  const [visible, setVisible] = useState(false);
  const [app, setApp] = useState<string | null>(null);
  const [flowName, setFlowName] = useState<string | null>(null);
  const [dismissedKey, setDismissedKey] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function tick() {
      try {
        const s = await appInsightsApi.currentState();
        if (cancelled) return;
        const flow = s.active_flow;
        if (s.tracker_running && s.is_distraction && flow) {
          const key = `${flow.id}-${s.current_app}`;
          if (key !== dismissedKey) {
            setApp(s.current_app || null);
            setFlowName(flow.name);
            setVisible(true);
          }
        } else {
          setVisible(false);
        }
      } catch { /* silent */ }
    }
    tick();
    const id = setInterval(tick, 20000);
    return () => { cancelled = true; clearInterval(id); };
  }, [dismissedKey]);

  if (!visible || !app) return null;

  function dismiss() {
    setDismissedKey(`${flowName}-${app}`);
    setVisible(false);
  }

  return (
    <div className="fixed bottom-6 right-6 z-50 max-w-sm bg-red-950/90 border border-red-500/40 backdrop-blur-md rounded-xl p-4 shadow-2xl animate-in slide-in-from-right">
      <div className="flex items-start gap-3">
        <div className="text-2xl">⚠️</div>
        <div className="flex-1">
          <div className="text-sm font-semibold text-red-300">Foco interrompido</div>
          <div className="text-xs text-gray-300 mt-1">
            Estás em <span className="font-medium">{app}</span> durante a sessão Flow{' '}
            <span className="font-medium">"{flowName}"</span>.
          </div>
        </div>
        <button onClick={dismiss} className="p-1 rounded text-red-300 hover:bg-red-500/20">
          <X size={14} />
        </button>
      </div>
    </div>
  );
}
