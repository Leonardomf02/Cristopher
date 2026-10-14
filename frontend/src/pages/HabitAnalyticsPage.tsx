import { useState, useEffect } from 'react';
import TresJogosPorDia from '../components/TresJogosPorDia';
import { format, getDay, startOfMonth, endOfMonth, startOfYear, endOfYear, addMonths, addYears, differenceInCalendarDays, isAfter } from 'date-fns';
import { pt } from 'date-fns/locale';
import { Flame, Target, Calendar, Plus, X, Clock, Pencil, ChevronDown, ChevronLeft, ChevronRight, PauseCircle, PlayCircle, Check } from 'lucide-react';
import { habitsApi, screenTimeApi } from '../api';

// O backend numera os dias 0=Seg … 6=Dom (ao contrário do getDay do date-fns).
const HABIT_DAYS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];
const HABIT_COLORS = ['#10B981', '#3B82F6', '#8B5CF6', '#EC4899', '#F59E0B', '#EF4444', '#06B6D4', '#84CC16'];
const HABIT_ICONS = ['✅', '🏋️', '🏃', '📚', '🧘', '💧', '🥗', '💊', '😴', '🎸', '🧹', '💻', '🦷', '☀️'];

// Categorias de ecrã com que um hábito se pode associar (as mesmas do tracker).
const SCREEN_GOAL_CATEGORIES = ['Social', 'Productivity & Finance', 'Games', 'Entertainment', 'Other'];

const EMPTY_HABIT = { name: '', icon: '✅', color: '#10B981', days: 'daily', fixed_time: '', screen_category: '', screen_hours: '5' };

function daysLabel(days: string) {
  if (days === 'daily') return 'Todos os dias';
  if (days === 'weekdays') return 'Dias úteis';
  return days.split(',').map(d => HABIT_DAYS[Number(d.trim())] || '?').join(', ');
}

/** Mapa de actividade de UM hábito: verde = feito, cinza = falhou, vazio = não estava marcado. */
function HabitHeatmap({ heatmap, color }: { heatmap: any[]; color: string }) {
  if (!heatmap?.length) return null;

  const weeks: any[][] = [];
  let week: any[] = [];
  heatmap.forEach(cell => {
    if (getDay(new Date(cell.date + 'T00:00:00')) === 0 && week.length > 0) {
      weeks.push(week);
      week = [];
    }
    week.push(cell);
  });
  if (week.length) weeks.push(week);

  return (
    <div>
      <div className="flex gap-0">
        <div className="flex flex-col gap-[2px] mr-1.5">
          {['D', 'S', 'T', 'Q', 'Q', 'S', 'S'].map((d, i) => (
            <div key={i} className="h-[11px] flex items-center justify-end">
              {i % 2 === 1 && <span className="text-[9px] text-gray-600 leading-none">{d}</span>}
            </div>
          ))}
        </div>
        <div className="flex gap-[2px] overflow-x-auto">
          {weeks.map((w, wi) => {
            const pad = getDay(new Date(w[0].date + 'T00:00:00'));
            return (
              <div key={wi} className="flex flex-col gap-[2px]">
                {Array.from({ length: pad }).map((_, pi) => <div key={`p${pi}`} className="w-[11px] h-[11px]" />)}
                {w.map(cell => {
                  const d = new Date(cell.date + 'T00:00:00');
                  const label = format(d, 'd MMM', { locale: pt });
                  const state = cell.done
                    ? `feito${cell.time ? ` às ${cell.time}` : ''}`
                    : cell.protected ? 'dia protegido'
                      : cell.scheduled ? 'falhado' : 'não estava marcado';
                  return (
                    <div
                      key={cell.date}
                      className="w-[11px] h-[11px] rounded-[2px] hover:ring-1 hover:ring-white/30"
                      style={{
                        backgroundColor: cell.done ? color : cell.scheduled && !cell.protected ? '#2a1a1a' : '#161616',
                        border: cell.done ? 'none' : '1px solid #1f1f1f',
                      }}
                      title={`${label}: ${state}`}
                    />
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
      <div className="flex items-center gap-3 mt-2 text-[9px] text-gray-600 flex-wrap">
        <span className="flex items-center gap-1">
          <span className="w-[9px] h-[9px] rounded-[2px]" style={{ backgroundColor: color }} /> feito
        </span>
        <span className="flex items-center gap-1">
          <span className="w-[9px] h-[9px] rounded-[2px] border border-[#1f1f1f]" style={{ backgroundColor: '#2a1a1a' }} /> falhado
        </span>
        <span className="flex items-center gap-1">
          <span className="w-[9px] h-[9px] rounded-[2px] border border-[#1f1f1f]" style={{ backgroundColor: '#161616' }} /> sem hábito
        </span>
      </div>
    </div>
  );
}

/** Distribuição por hora do dia (0-23). `formatValue` diz o que cada valor
 *  significa no tooltip — por omissão são ocorrências ("3×"), mas serve
 *  também para segundos de ecrã por hora. */
function HourHistogram({ byHour, color, formatValue }: { byHour: number[]; color: string; formatValue?: (n: number) => string }) {
  const max = Math.max(...byHour, 1);
  const fmt = formatValue || ((n: number) => `${n}×`);
  return (
    <div className="flex items-end gap-[2px] h-12">
      {byHour.map((n, h) => (
        <div key={h} className="flex-1 flex flex-col justify-end h-full" title={`${String(h).padStart(2, '0')}h: ${fmt(n)}`}>
          <div className="w-full rounded-t-[2px]"
            style={{ height: n ? `${Math.max(12, (n / max) * 100)}%` : '2px', backgroundColor: n ? color : '#222' }} />
        </div>
      ))}
    </div>
  );
}

function fmtHoursMin(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h ? `${h}h${String(m).padStart(2, '0')}` : `${m}min`;
}

export default function HabitAnalyticsPage() {
  const [analytics, setAnalytics] = useState<any>(null);
  // O período vê-se por mês ou por ano, e anda-se para trás para ver os outros.
  const [vista, setVista] = useState<'mes' | 'ano'>(() => {
    try { return localStorage.getItem('habitos_vista') === 'ano' ? 'ano' : 'mes'; } catch { return 'mes'; }
  });
  useEffect(() => { try { localStorage.setItem('habitos_vista', vista); } catch { /* ignora */ } }, [vista]);
  const [ref, setRef] = useState(() => new Date());
  const inicio = vista === 'mes' ? startOfMonth(ref) : startOfYear(ref);
  const fimPeriodo = vista === 'mes' ? endOfMonth(ref) : endOfYear(ref);
  const hoje = new Date();
  const fimVisto = isAfter(fimPeriodo, hoje) ? hoje : fimPeriodo;
  const days = differenceInCalendarDays(fimVisto, inicio) + 1;
  const deI = format(inicio, 'yyyy-MM-dd');
  const ateI = format(fimPeriodo, 'yyyy-MM-dd');
  const noPresente = !isAfter(hoje, fimPeriodo);
  const anda = (n: number) => setRef(r => vista === 'mes' ? addMonths(r, n) : addYears(r, n));
  const rotulo = vista === 'mes' ? format(inicio, 'MMMM yyyy', { locale: pt }) : format(inicio, 'yyyy');
  const carregaAnalytics = () => habitsApi.analyticsPeriodo(deI, ateI);

  const [habits, setHabits] = useState<any[]>([]);
  const [showHabitModal, setShowHabitModal] = useState(false);
  const [editingHabit, setEditingHabit] = useState<any>(null);
  const [habitForm, setHabitForm] = useState<typeof EMPTY_HABIT>(EMPTY_HABIT);
  const [savingHabit, setSavingHabit] = useState(false);
  const [expandedHabit, setExpandedHabit] = useState<number | null>(null);
  const [todayHabits, setTodayHabits] = useState<any[]>([]);
  const [togglingId, setTogglingId] = useState<number | null>(null);
  // Metas de ecrã associadas a hábitos (5h/dia de Productivity & Finance, etc.):
  // screenGoals dá a definição (para o formulário), goalsStatus dá o
  // progresso de hoje (a vista "day" de cada meta).
  const [screenGoals, setScreenGoals] = useState<Awaited<ReturnType<typeof screenTimeApi.goals>>>([]);
  const [goalsStatus, setGoalsStatus] = useState<Awaited<ReturnType<typeof screenTimeApi.goalsStatus>>['goals']>([]);
  // "A que horas usas X": só se pede quando um hábito com meta de ecrã é
  // aberto, e fica em cache por categoria+janela.
  const [categoryHours, setCategoryHours] = useState<Record<string, number[]>>({});

  useEffect(() => {
    // Falha da analytics não pode bloquear a gestão dos hábitos.
    carregaAnalytics().then(setAnalytics).catch(() => setAnalytics({ habits: [], heatmap: [] }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deI, ateI]);

  useEffect(() => { loadHabits(); loadScreenGoals(); }, []);

  function loadScreenGoals() {
    screenTimeApi.goals().then(setScreenGoals).catch(() => setScreenGoals([]));
    screenTimeApi.goalsStatus().then(r => setGoalsStatus(r.goals)).catch(() => setGoalsStatus([]));
  }

  useEffect(() => {
    if (expandedHabit == null) return;
    const meta = screenGoals.find(g => g.habit_id === expandedHabit);
    if (!meta) return;
    const janela = Math.min(Math.max(days, 7), 90);
    const key = `${meta.category}:${janela}`;
    if (categoryHours[key]) return;
    screenTimeApi.byHour(meta.category, janela).then(r => setCategoryHours(prev => ({ ...prev, [key]: r.hours }))).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expandedHabit, screenGoals, days]);

  async function loadHabits() {
    const [all, today] = await Promise.all([
      habitsApi.list(false).catch(() => []),
      habitsApi.today().catch(() => []),
    ]);
    setHabits(all);
    setTodayHabits(today);
  }

  async function toggleToday(h: any) {
    const entry = todayHabits.find(t => t.id === h.id);
    if (!entry) return;
    setTogglingId(h.id);
    try {
      if (entry.completed && entry.completion) {
        await habitsApi.deleteCompletion(h.id, entry.completion.id);
      } else {
        await habitsApi.complete(h.id, {
          date: format(new Date(), 'yyyy-MM-dd'),
          completed_at: format(new Date(), 'HH:mm'),
        });
      }
      await loadHabits();
      carregaAnalytics().then(setAnalytics).catch(() => {});
    } finally {
      setTogglingId(null);
    }
  }

  function openNewHabit() {
    setEditingHabit(null);
    setHabitForm(EMPTY_HABIT);
    setShowHabitModal(true);
  }

  function openEditHabit(h: any) {
    setEditingHabit(h);
    const meta = screenGoals.find(g => g.habit_id === h.id);
    setHabitForm({
      name: h.name, icon: h.icon, color: h.color, days: h.days, fixed_time: h.fixed_time || '',
      screen_category: meta?.category || '', screen_hours: meta ? String(meta.target_hours) : '5',
    });
    setShowHabitModal(true);
  }

  function toggleHabitDay(d: number) {
    setHabitForm(f => {
      const current = f.days === 'daily' || f.days === 'weekdays'
        ? (f.days === 'weekdays' ? [0, 1, 2, 3, 4] : [0, 1, 2, 3, 4, 5, 6])
        : f.days.split(',').filter(Boolean).map(Number);
      const next = current.includes(d) ? current.filter(x => x !== d) : [...current, d].sort((a, b) => a - b);
      return { ...f, days: next.length === 7 ? 'daily' : next.join(',') };
    });
  }

  async function saveHabit() {
    if (!habitForm.name.trim()) return;
    setSavingHabit(true);
    try {
      const { screen_category, screen_hours, ...habitFields } = habitForm;
      const payload = { ...habitFields, name: habitFields.name.trim(), fixed_time: habitFields.fixed_time || null };
      let habitId: number;
      if (editingHabit) {
        await habitsApi.update(editingHabit.id, payload);
        habitId = editingHabit.id;
      } else {
        const criado = await habitsApi.create(payload);
        habitId = criado.id;
      }

      // Meta de ecrã: no máximo uma por hábito — apaga a anterior se mudou de
      // categoria (ou se deixou de haver meta), grava a nova (sempre diária,
      // que é o único ritmo em que faz sentido marcar um hábito sozinho).
      const anterior = screenGoals.find(g => g.habit_id === habitId);
      if (anterior && anterior.category !== screen_category) {
        await screenTimeApi.setGoal(anterior.category, 0, 'daily');
      }
      if (screen_category) {
        await screenTimeApi.setGoal(screen_category, parseFloat(screen_hours) || 5, 'daily', habitId);
      }

      setShowHabitModal(false);
      await loadHabits();
      loadScreenGoals();
      carregaAnalytics().then(setAnalytics).catch(() => {});
    } finally {
      setSavingHabit(false);
    }
  }

  async function toggleHabitActive(h: any) {
    await habitsApi.update(h.id, { active: !h.active });
    loadHabits();
  }

  async function deleteHabit(h: any) {
    if (!confirm(`Apagar o hábito "${h.name}"? Perdes o histórico de conclusões.`)) return;
    await habitsApi.delete(h.id);
    setShowHabitModal(false);
    await loadHabits();
    carregaAnalytics().then(setAnalytics).catch(() => {});
  }

  const selectedDays = habitForm.days === 'daily'
    ? [0, 1, 2, 3, 4, 5, 6]
    : habitForm.days === 'weekdays'
      ? [0, 1, 2, 3, 4]
      : habitForm.days.split(',').filter(Boolean).map(Number);

  if (!analytics) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-2 border-green-400 border-t-transparent rounded-full" />
      </div>
    );
  }

  // A lista mostra TODOS os hábitos (incl. pausados); a analytics só cobre os activos.
  const statsById: Record<number, any> = {};
  (analytics.habits || []).forEach((h: any) => { statsById[h.id] = h; });
  return (
    <div>
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3 sm:gap-4 mb-6 lg:mb-8">
        <div className="min-w-0">
          <h2 className="text-2xl font-bold">Hábitos</h2>
        </div>
        {/* Uma linha só, também no telemóvel: no ecrã pequeno o botão fica só com o + */}
        <div className="w-full sm:w-auto sm:ml-auto flex flex-nowrap gap-1.5 sm:gap-2 items-center overflow-x-auto">
          <div className="shrink-0 flex bg-[#222] rounded-lg p-0.5">
            {([['mes', 'Mês'], ['ano', 'Ano']] as const).map(([k, label]) => (
              <button key={k} onClick={() => { setVista(k); setRef(new Date()); }}
                className={`px-2.5 sm:px-3 py-1 text-xs rounded-md transition-all ${
                  vista === k ? 'bg-green-600 text-white font-medium' : 'text-gray-400 hover:text-white'
                }`}>
                {label}
              </button>
            ))}
          </div>
          <div className="shrink-0 flex items-center gap-0.5">
            <button onClick={() => anda(-1)} title={vista === 'mes' ? 'Mês anterior' : 'Ano anterior'}
              className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/10">
              <ChevronLeft size={14} />
            </button>
            <button onClick={() => setRef(new Date())} disabled={noPresente}
              title={noPresente ? undefined : 'Voltar ao actual'}
              className="text-xs text-gray-300 capitalize w-28 text-center disabled:cursor-default enabled:hover:text-white">
              {rotulo}
            </button>
            <button onClick={() => anda(1)} disabled={noPresente}
              title={vista === 'mes' ? 'Mês seguinte' : 'Ano seguinte'}
              className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 disabled:opacity-30 disabled:hover:bg-transparent">
              <ChevronRight size={14} />
            </button>
          </div>
          <button onClick={openNewHabit} title="Novo hábito"
            className="shrink-0 flex items-center gap-2 px-2.5 sm:px-4 py-1.5 bg-green-600 hover:bg-green-500 rounded-lg text-xs font-medium">
            <Plus size={14} /> <span className="hidden sm:inline">Novo Hábito</span>
          </button>
        </div>
      </div>

      {/* Lista compacta — uma linha por hábito, expande uma de cada vez */}
      <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden mb-6">
        <div className="flex items-center justify-between p-4 border-b border-[#222]">
          <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
            <Target size={14} className="text-green-400" /> Os meus hábitos
          </h3>
          <span className="text-xs text-gray-600">{habits.filter(h => h.active).length} activos</span>
        </div>

        {habits.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-sm text-gray-500">Ainda não tens hábitos.</p>
            <button onClick={openNewHabit} className="mt-3 px-4 py-1.5 bg-green-600 hover:bg-green-500 rounded-lg text-xs font-medium">
              Criar o primeiro
            </button>
          </div>
        ) : (
          <div className="divide-y divide-[#1a1a1a]">
            {habits.map(h => {
              const a = statsById[h.id];
              const ts = a?.time_stats;
              const open = expandedHabit === h.id;
              const todayEntry = todayHabits.find(t => t.id === h.id);
              return (
                <div key={h.id} className={h.active ? '' : 'opacity-50'}>
                  {/* Linha compacta */}
                  <div
                    onClick={() => a && setExpandedHabit(open ? null : h.id)}
                    className={`group flex items-center gap-3 p-3 hover:bg-white/5 ${a ? 'cursor-pointer' : ''}`}
                  >
                    {/* Check de hoje — só para hábitos marcados para hoje */}
                    {todayEntry ? (
                      <button
                        onClick={e => { e.stopPropagation(); toggleToday(h); }}
                        disabled={togglingId === h.id}
                        title={todayEntry.completed
                          ? `Feito hoje às ${todayEntry.completion?.completed_at} — carrega para desmarcar`
                          : 'Marcar como feito hoje'}
                        className={`w-6 h-6 rounded-full border-2 flex items-center justify-center shrink-0 transition-all disabled:opacity-50 ${
                          todayEntry.completed ? 'border-green-400 bg-green-400' : 'border-gray-600 hover:border-green-400'
                        }`}
                      >
                        {todayEntry.completed && <Check size={13} className="text-black" />}
                      </button>
                    ) : (
                      <span className="w-6 h-6 shrink-0 flex items-center justify-center" title="Não está marcado para hoje">
                        <span className="w-1.5 h-1.5 rounded-full bg-[#2a2a2a]" />
                      </span>
                    )}

                    <span className="w-9 h-9 rounded-xl flex items-center justify-center text-lg shrink-0"
                      style={{ backgroundColor: h.color + '22' }}>{h.icon}</span>

                    <div className="min-w-0 flex-1">
                      <p className={`text-sm font-medium truncate ${todayEntry?.completed ? 'text-gray-400' : ''}`}>{h.name}</p>
                      <p className="text-[11px] text-gray-500 flex items-center gap-2 flex-wrap">
                        {todayEntry?.completed
                          ? <span className="text-green-400">✓ feito hoje às {todayEntry.completion?.completed_at}</span>
                          : todayEntry
                            ? <span className="text-gray-400">por fazer hoje</span>
                            : <span className="text-gray-600">hoje não</span>}
                        <span className="text-gray-600">·</span>
                        {daysLabel(h.days)}
                        {h.fixed_time && <span className="flex items-center gap-1"><Clock size={10} /> {h.fixed_time}</span>}
                        {!h.active && <span className="text-gray-600">· pausado</span>}
                      </p>
                    </div>

                    {/* Últimos 30 dias em miniatura */}
                    {a && (
                      <div className="hidden md:flex gap-[2px] items-center shrink-0">
                        {a.heatmap.slice(-30).map((c: any) => (
                          <span key={c.date} className="w-[5px] h-4 rounded-[1px]"
                            style={{ backgroundColor: c.done ? h.color : c.scheduled && !c.protected ? '#2a1a1a' : '#1c1c1c' }}
                            title={`${format(new Date(c.date + 'T00:00:00'), 'd MMM', { locale: pt })}: ${c.done ? `feito${c.time ? ' às ' + c.time : ''}` : c.scheduled ? 'falhado' : '—'}`} />
                        ))}
                      </div>
                    )}

                    {a && (
                      <div className="hidden sm:flex items-center gap-4 shrink-0 text-right">
                        <div className="w-14">
                          <p className={`text-sm font-bold leading-none ${a.rate >= 80 ? 'text-green-400' : a.rate >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>{a.rate}%</p>
                          <p className="text-[9px] text-gray-600">{a.completed}/{a.scheduled}</p>
                        </div>
                        <div className="w-10">
                          <p className="text-sm font-bold leading-none flex items-center justify-end gap-0.5">
                            <Flame size={11} className="text-orange-400" />{a.current_streak}
                          </p>
                          <p className="text-[9px] text-gray-600">streak</p>
                        </div>
                        <div className="w-12">
                          <p className="text-sm font-bold leading-none tabular-nums">{ts ? ts.avg : '—'}</p>
                          <p className="text-[9px] text-gray-600">média</p>
                        </div>
                      </div>
                    )}

                    <div className="flex items-center gap-0.5 shrink-0">
                      <button onClick={e => { e.stopPropagation(); toggleHabitActive(h); }}
                        title={h.active ? 'Pausar' : 'Reactivar'}
                        className="p-1.5 rounded-lg text-gray-600 hover:text-white hover:bg-white/10 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
                        {h.active ? <PauseCircle size={14} /> : <PlayCircle size={14} />}
                      </button>
                      <button onClick={e => { e.stopPropagation(); openEditHabit(h); }} title="Editar"
                        className="p-1.5 rounded-lg text-gray-600 hover:text-white hover:bg-white/10 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
                        <Pencil size={13} />
                      </button>
                      {a && <ChevronDown size={14} className={`text-gray-600 transition-transform ${open ? 'rotate-180' : ''}`} />}
                    </div>
                  </div>

                  {/* Detalhe */}
                  {open && a && (
                    <div className="px-3 pb-4 pt-1 bg-[#121212] border-t border-[#1a1a1a] space-y-4">
                      {/* Este hábito sai dos jogos, por isso traz consigo o que
                          os jogos dizem: cumprimento e resultado. */}
                      {h.name === '3 jogos de LoL' && <div className="pt-3"><TresJogosPorDia /></div>}
                      {(() => {
                        const meta = goalsStatus.find(g => g.habit_id === h.id);
                        if (!meta) return null;
                        const v = meta.views.day;
                        return (
                          <div className="space-y-1.5 pt-3">
                            <div className="flex items-center gap-3 bg-[#1a1a1a] rounded-xl px-3 py-2.5">
                              <span className="text-xs text-gray-400 shrink-0">🎯 {meta.category}</span>
                              <div className="flex-1 h-1.5 bg-[#222] rounded-full overflow-hidden">
                                <div className={`h-full rounded-full ${v.reached ? 'bg-emerald-500' : 'bg-blue-500'}`}
                                  style={{ width: `${Math.min(100, v.pct || 0)}%` }} />
                              </div>
                              <span className="text-xs text-gray-500 tabular-nums shrink-0">
                                {fmtHoursMin(v.used_seconds)} / {meta.target_hours}h hoje
                              </span>
                            </div>
                            <button onClick={() => openEditHabit(h)}
                              className="flex items-center gap-1 text-[11px] text-gray-500 hover:text-white">
                              <Pencil size={10} /> editar meta
                            </button>
                          </div>
                        );
                      })()}
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-3">
                        {[
                          { label: 'Taxa', value: `${a.rate}%`, sub: `${a.completed}/${a.scheduled} dias` },
                          { label: 'Melhor streak', value: a.best_streak, sub: `atual ${a.current_streak}` },
                          { label: 'Hora média', value: ts ? ts.avg : '—', sub: ts ? `${ts.earliest}–${ts.latest}` : 'sem registos' },
                          { label: 'Consistência', value: ts ? `${ts.consistency}%` : '—', sub: ts ? `mediana ${ts.median}` : '' },
                        ].map(s => (
                          <div key={s.label} className="bg-[#1a1a1a] rounded-xl px-3 py-2">
                            <p className="text-base font-bold leading-none">{s.value}</p>
                            <p className="text-[10px] text-gray-500 mt-1">{s.label}</p>
                            {s.sub && <p className="text-[9px] text-gray-600">{s.sub}</p>}
                          </div>
                        ))}
                      </div>

                      <div>
                        <p className="text-[11px] text-gray-500 mb-2 flex items-center gap-1.5">
                          <Calendar size={11} /> Mapa de atividade — <span className="capitalize">{rotulo}</span>
                        </p>
                        <HabitHeatmap heatmap={a.heatmap} color={h.color} />
                      </div>

                      {(() => {
                        const metaCat = screenGoals.find(g => g.habit_id === h.id)?.category;
                        const janela = Math.min(Math.max(days, 7), 90);
                        // Um hábito ligado a uma categoria de ecrã: mais informativo saber
                        // a que horas essa categoria é usada do que a que horas o auto-check
                        // aconteceu. Sem meta associada, fica o histórico de quando marcaste.
                        if (metaCat) {
                          const hours = categoryHours[`${metaCat}:${janela}`];
                          if (!hours) return null;
                          return (
                            <div>
                              <p className="text-[11px] text-gray-500 mb-2 flex items-center gap-1.5">
                                <Clock size={11} /> A que horas usas {metaCat}
                              </p>
                              <HourHistogram byHour={hours} color={h.color} formatValue={fmtHoursMin} />
                              <div className="flex justify-between text-[9px] text-gray-700 mt-0.5">
                                {[0, 6, 12, 18, 23].map(hh => <span key={hh}>{String(hh).padStart(2, '0')}h</span>)}
                              </div>
                            </div>
                          );
                        }
                        if (!ts) return null;
                        return (
                          <div>
                            <p className="text-[11px] text-gray-500 mb-2 flex items-center gap-1.5">
                              <Clock size={11} /> A que horas fazes
                            </p>
                            <HourHistogram byHour={ts.by_hour} color={h.color} />
                            <div className="flex justify-between text-[9px] text-gray-700 mt-0.5">
                              {[0, 6, 12, 18, 23].map(hh => <span key={hh}>{String(hh).padStart(2, '0')}h</span>)}
                            </div>
                          </div>
                        );
                      })()}

                      <div>
                        <p className="text-[11px] text-gray-500 mb-2">Taxa por dia da semana</p>
                        <div className="flex gap-1">
                          {HABIT_DAYS.map((day, i) => {
                            const wd = a.by_weekday?.find((w: any) => w.weekday === i);
                            const rate = wd?.rate ?? null;
                            return (
                              <div key={day} className="flex-1 flex flex-col items-center gap-1">
                                <div className="w-full h-7 rounded-md"
                                  style={{ backgroundColor: rate != null ? `${h.color}${Math.round(Math.max(rate, 6) / 100 * 255).toString(16).padStart(2, '0')}` : '#1a1a1a' }}
                                  title={wd ? `${day}: ${rate}% (${wd.completed}/${wd.scheduled})` : `${day}: sem hábito marcado`} />
                                <span className="text-[9px] text-gray-600">{day}</span>
                              </div>
                            );
                          })}
                        </div>
                      </div>

                      {a.times.length > 0 && (
                        <div>
                          <p className="text-[11px] text-gray-500 mb-2">Todas as vezes ({a.times.length})</p>
                          <div className="max-h-48 overflow-y-auto rounded-xl border border-[#222] divide-y divide-[#1a1a1a]">
                            {a.times.map((t: any) => (
                              <div key={t.date} className="flex items-center gap-3 px-3 py-1.5 text-xs">
                                <span className="text-gray-500 w-24 shrink-0">
                                  {format(new Date(t.date + 'T00:00:00'), 'd MMM yyyy', { locale: pt })}
                                </span>
                                <span className="text-gray-600 w-8 shrink-0 text-[10px]">
                                  {HABIT_DAYS[(new Date(t.date + 'T00:00:00').getDay() + 6) % 7]}
                                </span>
                                <span className="font-medium tabular-nums" style={{ color: h.color }}>{t.time}</span>
                                {t.notes && <span className="text-gray-600 truncate flex-1">{t.notes}</span>}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Modal de hábito */}
      {showHabitModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={() => setShowHabitModal(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 max-w-[90vw] w-[420px] border border-[#333] max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-bold">{editingHabit ? 'Editar Hábito' : 'Novo Hábito'}</h3>
              <button onClick={() => setShowHabitModal(false)} className="text-gray-500 hover:text-white"><X size={20} /></button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="text-xs text-gray-500 block mb-1">Nome</label>
                <input type="text" value={habitForm.name} autoFocus
                  onChange={e => setHabitForm(f => ({ ...f, name: e.target.value }))}
                  onKeyDown={e => e.key === 'Enter' && saveHabit()}
                  placeholder="Ex: Ginásio, Ler, Beber água…"
                  className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-green-500" />
              </div>

              <div>
                <label className="text-xs text-gray-500 block mb-2">Ícone</label>
                <div className="flex gap-1.5 flex-wrap">
                  {HABIT_ICONS.map(ic => (
                    <button key={ic} onClick={() => setHabitForm(f => ({ ...f, icon: ic }))}
                      className={`w-9 h-9 rounded-xl text-lg flex items-center justify-center transition-all ${
                        habitForm.icon === ic ? 'ring-2 ring-green-500 bg-white/10' : 'bg-[#222] hover:bg-[#2a2a2a]'
                      }`}>
                      {ic}
                    </button>
                  ))}
                  <input type="text" value={habitForm.icon} maxLength={2}
                    onChange={e => setHabitForm(f => ({ ...f, icon: e.target.value }))}
                    title="Ou escreve outro emoji"
                    className="w-9 h-9 bg-[#222] border border-[#333] rounded-xl text-center text-lg focus:outline-none focus:border-green-500" />
                </div>
              </div>

              <div>
                <label className="text-xs text-gray-500 block mb-2">Cor</label>
                <div className="flex gap-2 flex-wrap">
                  {HABIT_COLORS.map(c => (
                    <button key={c} onClick={() => setHabitForm(f => ({ ...f, color: c }))}
                      className={`w-8 h-8 rounded-lg transition-all ${habitForm.color === c ? 'ring-2 ring-white/60 scale-110' : ''}`}
                      style={{ backgroundColor: c }} />
                  ))}
                </div>
              </div>

              <div>
                <label className="text-xs text-gray-500 block mb-2">Dias</label>
                <div className="flex gap-1.5 mb-2">
                  {[['daily', 'Todos'], ['weekdays', 'Dias úteis']].map(([v, label]) => (
                    <button key={v} onClick={() => setHabitForm(f => ({ ...f, days: v }))}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                        habitForm.days === v ? 'bg-green-600 text-white' : 'bg-[#222] text-gray-400 hover:text-white'
                      }`}>
                      {label}
                    </button>
                  ))}
                </div>
                <div className="grid grid-cols-7 gap-1">
                  {HABIT_DAYS.map((d, i) => (
                    <button key={d} onClick={() => toggleHabitDay(i)}
                      className={`py-2 rounded-lg text-[11px] font-medium transition-all ${
                        selectedDays.includes(i) ? 'bg-green-600/25 text-green-300' : 'bg-[#222] text-gray-500 hover:text-white'
                      }`}>
                      {d}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-xs text-gray-500 block mb-1">Hora fixa (opcional)</label>
                <div className="flex gap-2">
                  <input type="time" value={habitForm.fixed_time}
                    onChange={e => setHabitForm(f => ({ ...f, fixed_time: e.target.value }))}
                    className="flex-1 bg-[#222] border border-[#333] rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-green-500" />
                  {habitForm.fixed_time && (
                    <button onClick={() => setHabitForm(f => ({ ...f, fixed_time: '' }))}
                      className="px-3 py-2.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-xs text-gray-400">Sem hora</button>
                  )}
                </div>
                <p className="text-[10px] text-gray-600 mt-1">Com hora fixa recebes notificação; sem hora fica flexível.</p>
              </div>

              <div>
                <label className="text-xs text-gray-500 block mb-1">Meta de ecrã (opcional)</label>
                <div className="flex gap-2">
                  <select value={habitForm.screen_category}
                    onChange={e => setHabitForm(f => ({ ...f, screen_category: e.target.value }))}
                    className="flex-1 bg-[#222] border border-[#333] rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-green-500">
                    <option value="">Nenhuma</option>
                    {SCREEN_GOAL_CATEGORIES.map(cat => {
                      const outro = screenGoals.find(g => g.category === cat && g.habit_id && g.habit_id !== editingHabit?.id);
                      return <option key={cat} value={cat}>{cat}{outro ? ` (já é de ${outro.habit_name})` : ''}</option>;
                    })}
                  </select>
                  {habitForm.screen_category && (
                    <input type="number" min="0.5" step="0.5" value={habitForm.screen_hours}
                      onChange={e => setHabitForm(f => ({ ...f, screen_hours: e.target.value }))}
                      className="w-16 bg-[#222] border border-[#333] rounded-xl px-2 py-2.5 text-sm text-center focus:outline-none focus:border-green-500" />
                  )}
                </div>
                {habitForm.screen_category && (
                  <p className="text-[10px] text-gray-600 mt-1">
                    Ao chegares a {habitForm.screen_hours || 5}h de {habitForm.screen_category} hoje, o hábito marca-se sozinho.
                  </p>
                )}
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              {editingHabit && (
                <button onClick={() => deleteHabit(editingHabit)}
                  className="px-4 py-2.5 bg-red-600/20 text-red-400 hover:bg-red-600/30 rounded-xl text-sm font-medium">
                  Apagar
                </button>
              )}
              <div className="flex-1" />
              <button onClick={() => setShowHabitModal(false)}
                className="px-4 py-2.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm">Cancelar</button>
              <button onClick={saveHabit} disabled={savingHabit || !habitForm.name.trim()}
                className="px-6 py-2.5 bg-green-600 hover:bg-green-500 disabled:opacity-30 rounded-xl text-sm font-medium">
                {editingHabit ? 'Guardar' : 'Criar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
