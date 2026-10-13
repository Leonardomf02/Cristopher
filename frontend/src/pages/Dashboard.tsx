import { inkColor } from '../theme';
import { useFlow } from '../FlowContext';
import { ComecarTarefa } from '../ComecarTarefa';
import { useState, useEffect, useRef } from 'react';
import { format, isToday, isTomorrow, startOfWeek, endOfWeek, startOfMonth, endOfMonth, eachDayOfInterval, isSameMonth, isSameDay, addMonths, subMonths, subDays } from 'date-fns';
import { pt } from 'date-fns/locale';
import { Calendar, Wallet, Swords, Plane, Check, TrendingUp, Clock, ArrowRight, Moon, Target, Plus, X, ChevronLeft, ChevronRight, BarChart3, Smile, Frown, Meh, Heart, BookOpen, Flame, Zap, Edit2, Pencil, LineChart, ListPlus, History, Wand2, Loader2, Trash2, CalendarX, Sun, Play, Code2, Tag } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useCategorias, infoCategoria } from '../expenseCategories';
import { askApi, codeActivityApi, dealsApi, eventsApi, expensesApi, lolApi, tripsApi, sleepApi, habitsApi, dashboardApi, moodApi, dayTypesApi, investmentsApi, listsApi, dayPlannerApi, DayPlan, PlanBlock, PinnedQuestion } from '../api';
import NoiteFora from '../components/NoiteFora';
import { Event, Expense, LolStats, Trip, EVENT_CATEGORIES, SleepStats, EventCreate, DAY_TYPE_PRESETS, DEFAULT_DAY_TYPE, STREAK_PROTECTED_DAY_TYPES } from '../types';

const DAY_QUALITIES = [
  { value: 'bad', emoji: '😞', label: 'Mau', color: '#EF4444' },
  { value: 'meh', emoji: '😐', label: 'Normal', color: '#F59E0B' },
  { value: 'good', emoji: '🙂', label: 'Bom', color: '#10B981' },
  { value: 'great', emoji: '🤩', label: 'Ótimo', color: '#3B82F6' },
];

// A pontuação do sono é a do relógio, 0-100, com as cores da Garmin.
function corDaPontuacao(s: number | null | undefined) {
  if (s == null) return '#4b5563';
  if (s >= 80) return '#4ade80';
  if (s >= 70) return '#a3e635';
  if (s >= 60) return '#f59e0b';
  return '#f43f5e';
}

function horasEMinutos(h: number) {
  const m = Math.round(h * 60);
  return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}`;
}

// 0-10 rating → colour (red → amber → green)
function ratingColor(r: number) {
  if (r <= 3) return '#EF4444';
  if (r <= 5) return '#F97316';
  if (r <= 6) return '#F59E0B';
  if (r <= 8) return '#10B981';
  return '#3B82F6';
}


// Perguntas fixadas no Perguntar. Guarda-se o SQL que a IA escreveu, por isso o
// número volta a ser calculado de graça sempre que se abre a app — sem isto, a
// pergunta era feita uma vez e esquecida.
function PerguntasFixadas() {
  const navigate = useNavigate();
  const [cartoes, setCartoes] = useState<PinnedQuestion[] | null>(null);

  const carregar = () => askApi.pinned().then(setCartoes).catch(() => setCartoes(null));
  useEffect(() => { carregar(); }, []);

  if (!cartoes || !cartoes.length) return null;

  const remover = async (id: number) => {
    await askApi.unpin(id).catch(() => {});
    carregar();
  };

  return (
    <div className="mb-8 grid grid-cols-2 lg:grid-cols-4 gap-3">
      {cartoes.map(c => {
        const mudou = c.previous != null && c.value != null && c.previous !== c.value;
        const delta = mudou ? Number(c.value) - Number(c.previous) : null;
        return (
          <div key={c.id} className="group relative bg-[#161616] rounded-2xl border border-[#222] p-3.5">
            <button
              onClick={() => remover(c.id)}
              title="Tirar do Dashboard"
              className="absolute top-2 right-2 hidden group-hover:block p-1 rounded-lg text-gray-600 hover:text-red-400 hover:bg-white/5"
            >
              <X size={12} />
            </button>
            <p className="text-[10px] text-gray-500 mb-1 pr-4 line-clamp-2" title={c.question}>{c.title}</p>
            {c.error ? (
              <p className="text-xs text-amber-500/80" title={c.error}>já não dá para calcular</p>
            ) : (
              <>
                <p className="text-xl font-bold tabular-nums">{c.value ?? '—'}</p>
                {delta != null && Number.isFinite(delta) && delta !== 0 && (
                  <p className={`text-[10px] ${delta > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {delta > 0 ? '+' : ''}{Number(delta.toFixed(2))} desde a última vez
                  </p>
                )}
                {c.row_count > 1 && (
                  <button onClick={() => navigate('/ask')} className="mt-0.5 text-[10px] text-gray-600 hover:text-gray-400">
                    {c.row_count} linhas ›
                  </button>
                )}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}








// A vista escolhida fica guardada: quem abre o dashboard no Resumo quer o Resumo
// da próxima vez também.
const VISTA_KEY = 'dashboard_vista';

export default function Dashboard() {
  const navigate = useNavigate();
  useCategorias();
  const [vista, setVista] = useState<'hoje' | 'resumo'>(() =>
    localStorage.getItem(VISTA_KEY) === 'resumo' ? 'resumo' : 'hoje');
  const [todayEvents, setTodayEvents] = useState<Event[]>([]);
  const [todayTasks, setTodayTasks] = useState<any[]>([]);
  const [showCompletedTasks, setShowCompletedTasks] = useState(false);
  const [weekExpenses, setWeekExpenses] = useState<Expense[]>([]);
  const [lolStats, setLolStats] = useState<LolStats | null>(null);
  const [trips, setTrips] = useState<Trip[]>([]);
  const [sleepStats, setSleepStats] = useState<SleepStats | null>(null);
  const [todayHabits, setTodayHabits] = useState<any[]>([]);
  const [showQuickAdd, setShowQuickAdd] = useState(false);
  const [quickMode, setQuickMode] = useState<'event' | 'task'>('task');
  const [quickTitle, setQuickTitle] = useState('');
  const [quickTime, setQuickTime] = useState('');
  const [quickCategory, setQuickCategory] = useState('general');

  // Pick-from-all-todos picker
  const [showPickPending, setShowPickPending] = useState(false);
  const [allPending, setAllPending] = useState<any[]>([]);
  const [codeTodos, setCodeTodos] = useState<{ id: number; content: string; project: string }[]>([]);
  // Filtros das duas listas de baixo: '' = todos.
  const [filtroProjecto, setFiltroProjecto] = useState('');
  // Recolher os TODOs de código. A escolha fica guardada: quem os fecha não os
  // quer ver outra vez amanhã.
  const [todosAbertos, setTodosAbertos] = useState(
    () => localStorage.getItem('dash_todos_codigo') !== 'fechado');
  const alternarTodos = () => setTodosAbertos(v => {
    localStorage.setItem('dash_todos_codigo', v ? 'fechado' : 'aberto');
    return !v;
  });
  const [filtroLista, setFiltroLista] = useState('');
  const [habitHints, setHabitHints] = useState<{ habit_id: number; reason: string }[]>([]);
  const [pendingFilter, setPendingFilter] = useState('');
  const [pickingId, setPickingId] = useState<number | null>(null);

  // Weekly Review
  const [weeklyReview, setWeeklyReview] = useState<any>(null);
  const [weekOffset, setWeekOffset] = useState(0);
  // Aberta por omissão: na vista Resumo ela é o conteúdo, não um extra.
  const [showWeeklyReview, setShowWeeklyReview] = useState(true);

  // Day rating & Journal
  const [todayMood, setTodayMood] = useState<any>(null);
  const [todayJournal, setTodayJournal] = useState<any>(null);
  const [moodNote, setMoodNote] = useState('');
  const [dayQuality, setDayQuality] = useState<string>('');
  const [savingQuickMood, setSavingQuickMood] = useState<string | null>(null);
  const [dayRating, setDayRating] = useState<number | null>(null);
  const [editingMood, setEditingMood] = useState(false);
  const [journalContent, setJournalContent] = useState('');
  const [showJournal, setShowJournal] = useState(false);
  const [dayFacts, setDayFacts] = useState<{ key: string; icon: string; label: string }[]>([]);
  const [dayPrompt, setDayPrompt] = useState('');
  const [perguntasDia, setPerguntasDia] = useState<{ key: string; icon: string; question: string }[]>([]);
  const journalRef = useRef<HTMLTextAreaElement>(null);
  const [aRascunhar, setARascunhar] = useState(false);

  // Monthly history
  const [showMoodHistory, setShowMoodHistory] = useState(false);
  const [historyMonth, setHistoryMonth] = useState<Date>(new Date());
  const [historyMoods, setHistoryMoods] = useState<any[]>([]);

  // Day Type
  const [todayDayType, setTodayDayType] = useState<any>(null);
  const [showDayTypePicker, setShowDayTypePicker] = useState(false);

  // Investments
  const [investmentSummary, setInvestmentSummary] = useState<any>(null);

  // Edição inline de uma linha da agenda (tarefa ou evento)
  const [editingRow, setEditingRow] = useState<{ kind: 'task' | 'event'; id: any } | null>(null);
  const [rowTitle, setRowTitle] = useState('');
  const [rowTime, setRowTime] = useState('');
  const [savingRow, setSavingRow] = useState(false);

  const today = new Date();
  const todayStr = format(today, 'yyyy-MM-dd');

  useEffect(() => {
    loadDashboard();
    loadPendingItems();
    loadCodeTodos();
    habitsApi.suggestions().then(setHabitHints).catch(() => {});
  }, []);

  useEffect(() => {
    dashboardApi.weeklyReview(weekOffset).then(setWeeklyReview).catch(() => null);
  }, [weekOffset]);

  async function loadDashboard() {
    const weekStart = format(startOfWeek(today, { weekStartsOn: 1 }), 'yyyy-MM-dd');
    const weekEnd = format(endOfWeek(today, { weekStartsOn: 1 }), 'yyyy-MM-dd');

    const [eventsData, tasksData, expData, statsData, tripsData, sleepData, habitsData, moodData, dayTypeData, investData] = await Promise.all([
      eventsApi.list({ start_date: todayStr, end_date: todayStr }),
      listsApi.getReminders({ start_date: todayStr, end_date: todayStr }).catch(() => []),
      expensesApi.list({ start_date: weekStart, end_date: weekEnd }),
      lolApi.stats().catch(() => null),
      tripsApi.list(),
      sleepApi.stats(7).catch(() => null),
      habitsApi.today().catch(() => []),
      moodApi.today().catch(() => ({ mood: null, journal: null })),
      dayTypesApi.list({ start_date: todayStr, end_date: todayStr }).catch(() => []),
      investmentsApi.summary().catch(() => null),
    ]);

    setTodayEvents(eventsData);
    setTodayTasks(tasksData || []);
    setWeekExpenses(expData);
    setLolStats(statsData);
    setTrips(tripsData);
    setSleepStats(sleepData);
    setTodayHabits(habitsData);
    setTodayMood(moodData?.mood || null);
    setTodayJournal(moodData?.journal || null);
    if (moodData?.journal) setJournalContent(moodData.journal.content || '');
    if (moodData?.mood) {
      setMoodNote(moodData.mood.note || '');
      setDayQuality(moodData.mood.quality || '');
      setDayRating(typeof moodData.mood.mood === 'number' ? moodData.mood.mood : null);
    }
    setTodayDayType(dayTypeData && dayTypeData.length > 0 ? dayTypeData[0] : null);
    setInvestmentSummary(investData);
  }

  async function toggleEvent(event: Event) {
    // Instâncias recorrentes são virtuais e partilham o id do pai — marcar via update
    // marcaria o evento original em vez desta ocorrência.
    await eventsApi.setOccurrenceCompleted(event.id as number, event.date, !event.completed);
    loadDashboard();
  }

  async function quickAddEvent() {
    if (!quickTitle.trim()) return;
    if (quickMode === 'task') {
      // Add as a task (list item) to the first available list or create one
      let targetListId: number | null = null;
      try {
        const lists = await listsApi.list();
        if (lists && lists.length > 0) {
          targetListId = lists[0].id;
        } else {
          const created = await listsApi.create({ name: 'Tarefas', icon: '✅', color: '#10B981' });
          targetListId = created.id;
        }
      } catch {}
      if (targetListId) {
        await listsApi.addItem(targetListId, {
          text: quickTitle.trim(),
          due_date: todayStr,
          due_time: quickTime || null,
        });
      }
    } else {
      const cat = EVENT_CATEGORIES.find(c => c.value === quickCategory);
      const payload: EventCreate = {
        title: quickTitle.trim(),
        date: todayStr,
        event_type: quickTime ? 'fixed' : 'flexible',
        start_time: quickTime || null,
        category: quickCategory,
        color: cat?.color || '#6B7280',
      };
      await eventsApi.create(payload);
    }
    setQuickTitle('');
    setQuickTime('');
    setQuickCategory('general');
    setShowQuickAdd(false);
    loadDashboard();
  }

  async function toggleTask(task: any) {
    await listsApi.updateItem(task.item_id, { checked: !task.checked });
    loadDashboard();
  }

  // Tirar de hoje ≠ apagar: a tarefa continua na lista dela, só perde a data.
  async function unscheduleTask(task: any) {
    await listsApi.updateItem(task.item_id, { due_date: null, due_time: null });
    loadDashboard();
  }

  // Um clique apaga. Sem `confirm()` do browser — o Chrome deixa de mostrar
  // esses diálogos assim que se marca "não voltar a mostrar", e a partir daí o
  // apagar não fazia nada nenhuma vez.
  async function deleteTask(task: any) {
    await listsApi.deleteItem(task.item_id);
    loadDashboard();
  }

  function startEditTask(task: any) {
    setEditingRow({ kind: 'task', id: task.item_id });
    // O título vem prefixado com o ícone da lista — edita-se só o texto.
    setRowTitle(String(task.title).replace(/^\S+\s/, ''));
    setRowTime(task.start_time || '');
  }

  function startEditEvent(event: Event) {
    setEditingRow({ kind: 'event', id: event.id });
    setRowTitle(event.title);
    setRowTime(event.start_time || '');
  }

  function cancelEditRow() {
    setEditingRow(null);
    setRowTitle('');
    setRowTime('');
  }

  async function saveRow() {
    if (!editingRow || !rowTitle.trim()) return;
    setSavingRow(true);
    try {
      if (editingRow.kind === 'task') {
        await listsApi.updateItem(editingRow.id, { text: rowTitle.trim(), due_time: rowTime || null });
      } else {
        await eventsApi.update(editingRow.id, {
          title: rowTitle.trim(),
          start_time: rowTime || null,
          event_type: rowTime ? 'fixed' : 'flexible',
        });
      }
      cancelEditRow();
      loadDashboard();
    } finally {
      setSavingRow(false);
    }
  }

  async function deleteEvent(event: Event) {
    const recurring = event.is_recurring_instance || (event.recurrence && event.recurrence !== 'none');
    if (recurring) {
      await eventsApi.excludeDate((event.parent_id ?? event.id) as number, event.date);
    } else {
      await eventsApi.delete(event.id as number);
    }
    loadDashboard();
  }

  async function loadCodeTodos() {
    try { setCodeTodos(await codeActivityApi.openTodos(30)); } catch { setCodeTodos([]); }
  }

  async function fecharCodeTodo(id: number) {
    await codeActivityApi.updateTodo(id, { done: true });
    loadCodeTodos();
  }

  async function loadPendingItems() {
    try {
      const data = await listsApi.pendingItems();
      setAllPending(data);
    } catch {
      setAllPending([]);
    }
  }

  useEffect(() => {
    if (!showJournal || dayFacts.length) return;
    moodApi.dayFacts(todayStr)
      .then(r => { setDayFacts(r.facts); setDayPrompt(r.prompt); })
      .catch(() => {});
    moodApi.journalPrompts(todayStr).then(r => setPerguntasDia(r.prompts)).catch(() => {});
  }, [showJournal]);

  // A app escreve o dia com o que já sabe; ele só corrige. Nunca por cima do que
  // já está escrito — entra antes do texto dele.
  async function escreverPorMim() {
    setARascunhar(true);
    try {
      const r = await moodApi.journalDraft(todayStr);
      if (r.empty) return;
      setJournalContent(c => (c.includes(r.text) ? c : (r.text + (c.trim() ? '\n\n' + c.trimStart() : '\n'))));
      journalRef.current?.focus();
    } finally {
      setARascunhar(false);
    }
  }

  // Cada pergunta entra como cabeçalho de um parágrafo para ele responder abaixo.
  function juntarPergunta(pergunta: string) {
    setJournalContent(c => {
      if (c.includes(pergunta)) return c;
      const base = c.trimEnd();
      return `${base ? base + '\n\n' : ''}${pergunta}\n`;
    });
    journalRef.current?.focus();
  }

  async function togglePicker() {
    if (!showPickPending) await loadPendingItems();
    setShowPickPending(s => !s);
  }

  // Empurra um item atrasado para hoje/amanhã sem sair do dashboard.
  async function reagendar(item: any, quando: 'hoje' | 'amanha') {
    setPickingId(item.id);
    try {
      const d = new Date();
      if (quando === 'amanha') d.setDate(d.getDate() + 1);
      await listsApi.updateItem(item.id, { due_date: format(d, 'yyyy-MM-dd') });
      await loadPendingItems();
      await loadDashboard();
    } finally {
      setPickingId(null);
    }
  }

  async function concluirPendente(item: any) {
    setPickingId(item.id);
    try {
      await listsApi.updateItem(item.id, { checked: true });
      await loadPendingItems();
      await loadDashboard();
    } finally {
      setPickingId(null);
    }
  }

  async function scheduleForToday(item: any) {
    setPickingId(item.id);
    try {
      await listsApi.updateItem(item.id, { due_date: todayStr });
      await loadPendingItems();
      await loadDashboard();
    } finally {
      setPickingId(null);
    }
  }

  // Um clique no emoji chega para registar o dia; o resto (nota, 0-10) é opcional.
  const QUALITY_RATING: Record<string, number> = { bad: 3, meh: 5, good: 7, great: 9 };

  async function guardarHumorRapido(quality: string) {
    setSavingQuickMood(quality);
    try {
      await moodApi.create({
        date: todayStr,
        mood: dayRating ?? QUALITY_RATING[quality] ?? 5,
        quality,
        note: moodNote || '',
      });
      const moodData = await moodApi.today();
      setTodayMood(moodData?.mood || null);
      setDayQuality(quality);
      setDayRating(prev => prev ?? QUALITY_RATING[quality] ?? 5);
    } finally {
      setSavingQuickMood(null);
    }
  }

  async function saveMood() {
    if (!dayQuality || dayRating === null) return;
    await moodApi.create({
      date: todayStr,
      mood: dayRating,
      quality: dayQuality,
      note: moodNote,
    });
    const moodData = await moodApi.today();
    setTodayMood(moodData?.mood || null);
    setEditingMood(false);
  }

  async function loadHistory(month: Date) {
    const start = format(startOfMonth(month), 'yyyy-MM-dd');
    const end = format(endOfMonth(month), 'yyyy-MM-dd');
    const data = await moodApi.list({ start_date: start, end_date: end }).catch(() => []);
    setHistoryMoods(data || []);
  }

  function openHistory() {
    const m = new Date();
    setHistoryMonth(m);
    setShowMoodHistory(true);
    loadHistory(m);
  }

  function changeHistoryMonth(delta: number) {
    const m = delta < 0 ? subMonths(historyMonth, 1) : addMonths(historyMonth, 1);
    setHistoryMonth(m);
    loadHistory(m);
  }

  async function setDayType(preset: typeof DAY_TYPE_PRESETS[number] | null) {
    if (preset === null) {
      // Clear day type
      if (todayDayType) {
        await dayTypesApi.delete(todayDayType.id);
      }
    } else {
      await dayTypesApi.set({
        date: todayStr,
        type_name: preset.name,
        color: preset.color,
      });
    }
    const list = await dayTypesApi.list({ start_date: todayStr, end_date: todayStr });
    setTodayDayType(list && list.length > 0 ? list[0] : null);
    setShowDayTypePicker(false);
    // Refresh habits so streak protection takes effect immediately
    const habitsData = await habitsApi.today().catch(() => []);
    setTodayHabits(habitsData);
  }

  async function saveJournal() {
    if (!journalContent.trim()) return;
    await moodApi.saveJournal({ date: todayStr, content: journalContent });
    const moodData = await moodApi.today();
    setTodayJournal(moodData?.journal || null);
  }

  const completedToday = todayEvents.filter(e => e.completed).length;
  const totalToday = todayEvents.length;
  const weekTotal = weekExpenses.reduce((s, e) => s + e.amount, 0);
  const upcomingTrips = trips.filter(t => new Date(t.start_date) >= today).slice(0, 3);
  const nextTrip = upcomingTrips[0];

  const greeting = (() => {
    const h = today.getHours();
    if (h < 12) return 'Bom dia';
    if (h < 18) return 'Boa tarde';
    return 'Boa noite';
  })();

  const wr = weeklyReview;

  return (
    // Cada vista cabe na janela: o que rola são as colunas lá dentro, não a
    // página. Com tudo empilhado eram dois ecrãs e meio de scroll.
    <div className="lg:h-[calc(100dvh-4rem)] lg:flex lg:flex-col lg:overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-6 lg:shrink-0">
        <div>
          <h2 className="text-2xl sm:text-3xl font-bold">{greeting}! 👋</h2>
          <p className="text-gray-500 mt-1 text-sm sm:text-base whitespace-nowrap">{format(today, "EEEE, d 'de' MMMM 'de' yyyy", { locale: pt })}</p>
        </div>
        <div className="flex items-center gap-1 bg-[#161616] rounded-xl border border-[#222] p-1 shrink-0">
          {(['hoje', 'resumo'] as const).map(v => (
            <button key={v} onClick={() => { setVista(v); localStorage.setItem(VISTA_KEY, v); }}
              className={`px-3 py-1.5 text-xs rounded-lg capitalize transition-all ${
                vista === v ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-white'}`}>
              {v}
            </button>
          ))}
        </div>
      </div>

      {vista === 'hoje' && (<>
      <div className="lg:shrink-0"><PerguntasFixadas /></div>

      <div className="flex flex-col lg:flex-row gap-6 lg:items-stretch lg:flex-1 lg:min-h-0">
        {/* Esquerda — agenda (mesma altura da coluna direita) */}
        <div className="flex-1 min-w-0 w-full lg:relative">
      {/* Agenda de Hoje — tarefas numa só coluna */}
      <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden lg:absolute lg:inset-0 lg:flex lg:flex-col">
            <div className="flex items-center justify-between p-4 border-b border-[#222]">
              <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
                <Calendar size={14} className="text-blue-400" /> Agenda de Hoje
              </h3>
              <div className="flex items-center gap-2">
                <button
                  onClick={togglePicker}
                  title="Escolher tarefas existentes para hoje"
                  className={`p-1.5 rounded-lg transition-all ${showPickPending ? 'bg-yellow-500/20 text-yellow-400' : 'hover:bg-white/10 text-gray-500 hover:text-gray-300'}`}
                >
                  <ListPlus size={14} />
                </button>
                <button
                  onClick={() => setShowQuickAdd(!showQuickAdd)}
                  className={`p-1.5 rounded-lg transition-all ${showQuickAdd ? 'bg-blue-600/20 text-blue-400' : 'hover:bg-white/10 text-gray-500 hover:text-gray-300'}`}
                >
                  {showQuickAdd ? <X size={14} /> : <Plus size={14} />}
                </button>
                <button onClick={() => navigate('/calendar')} className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1">
                  Ver tudo <ArrowRight size={12} />
                </button>
              </div>
            </div>

            {/* Pick from all pending todos */}
            {showPickPending && (() => {
              const todayDateStr = todayStr;
              const eligible = allPending.filter(p => p.due_date !== todayDateStr);
              const filtered = pendingFilter.trim()
                ? eligible.filter(p => p.text.toLowerCase().includes(pendingFilter.toLowerCase()))
                : eligible;
              return (
                <div className="p-4 border-b border-[#222] bg-[#1a1a1a]">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs text-gray-400">Escolher de todos os to-dos pendentes</span>
                    <span className="text-[10px] text-gray-600">{filtered.length} disponíve{filtered.length === 1 ? 'l' : 'is'}</span>
                  </div>
                  <input
                    type="text"
                    value={pendingFilter}
                    onChange={e => setPendingFilter(e.target.value)}
                    placeholder="Filtrar..."
                    className="w-full bg-[#222] border border-[#333] rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-yellow-500/50 mb-2"
                  />
                  <div className="divide-y divide-[#222] rounded-lg border border-[#222] bg-[#0f0f0f]">
                    {filtered.length === 0 ? (
                      <div className="p-4 text-center text-xs text-gray-600">
                        {eligible.length === 0 ? 'Sem to-dos pendentes — tudo limpo!' : 'Nada bate certo com o filtro.'}
                      </div>
                    ) : filtered.map(item => (
                      <div key={item.id} className="flex items-start gap-3 p-2.5 hover:bg-white/5">
                        <span className="text-base mt-0.5">{item.list_icon}</span>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm truncate">{item.text}</p>
                          <div className="flex items-center gap-2 mt-0.5">
                            <span className="text-[10px] text-gray-500">{item.list_name}</span>
                            {item.priority > 0 && (
                              <span className="text-[10px] text-orange-400">{'!'.repeat(item.priority)}</span>
                            )}
                            {item.due_date && (
                              <span className="text-[10px] text-gray-600">marcado p/ {item.due_date}</span>
                            )}
                          </div>
                        </div>
                        <button
                          onClick={() => scheduleForToday(item)}
                          disabled={pickingId === item.id}
                          className="px-2 py-1 text-[11px] font-medium rounded-md bg-yellow-500/20 text-yellow-300 hover:bg-yellow-500/30 disabled:opacity-50"
                        >
                          {pickingId === item.id ? '…' : 'Hoje'}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}


            {/* Quick Add Form */}
            {showQuickAdd && (
              <div className="p-4 border-b border-[#222] bg-[#1a1a1a]">
                {/* Mode toggle */}
                <div className="flex gap-1 mb-3 bg-[#0f0f0f] p-1 rounded-lg w-fit">
                  <button
                    onClick={() => setQuickMode('task')}
                    className={`px-3 py-1 rounded-md text-xs font-medium transition-all ${
                      quickMode === 'task' ? 'bg-green-600/20 text-green-400' : 'text-gray-500 hover:text-gray-300'
                    }`}
                  >
                    ✅ Tarefa
                  </button>
                  <button
                    onClick={() => setQuickMode('event')}
                    className={`px-3 py-1 rounded-md text-xs font-medium transition-all ${
                      quickMode === 'event' ? 'bg-blue-600/20 text-blue-400' : 'text-gray-500 hover:text-gray-300'
                    }`}
                  >
                    📅 Evento
                  </button>
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={quickTitle}
                    onChange={e => setQuickTitle(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && quickAddEvent()}
                    placeholder={quickMode === 'task' ? 'Nova tarefa...' : 'Nome do evento...'}
                    className="flex-1 bg-[#222] border border-[#333] rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500"
                    autoFocus
                  />
                  <input
                    type="time"
                    value={quickTime}
                    onChange={e => setQuickTime(e.target.value)}
                    className="bg-[#222] border border-[#333] rounded-lg px-2 py-2 text-sm text-white focus:outline-none focus:border-blue-500 w-24"
                  />
                </div>
                {quickMode === 'event' && (
                  <div className="flex gap-1 mt-2 flex-1 flex-wrap">
                    {EVENT_CATEGORIES.map(cat => (
                      <button
                        key={cat.value}
                        onClick={() => setQuickCategory(cat.value)}
                        className={`px-2 py-1 text-[10px] rounded-md transition-all ${
                          quickCategory === cat.value
                            ? 'ring-1 ring-white/30 font-medium'
                            : 'opacity-50 hover:opacity-80'
                        }`}
                        style={{ backgroundColor: cat.color + '22', color: cat.color }}
                      >
                        {cat.label}
                      </button>
                    ))}
                  </div>
                )}
                <div className="flex justify-end mt-2">
                  <button
                    onClick={quickAddEvent}
                    disabled={!quickTitle.trim()}
                    className={`px-3 py-1.5 disabled:opacity-30 disabled:cursor-not-allowed text-white text-xs font-medium rounded-lg transition-colors ${
                      quickMode === 'task' ? 'bg-green-600 hover:bg-green-500' : 'bg-blue-600 hover:bg-blue-500'
                    }`}
                  >
                    Adicionar {quickMode === 'task' ? 'Tarefa' : 'Evento'}
                  </button>
                </div>
              </div>
            )}

            <div className="lg:flex-1 lg:flex lg:flex-col lg:min-h-0">
            <div className="lg:overflow-y-auto">
            {(() => {
              const pendingTasks = todayTasks.filter(t => !t.checked);
              const completedTasks = todayTasks.filter(t => t.checked);
              const hasAnything = todayEvents.length > 0 || todayTasks.length > 0;
              if (!hasAnything) {
                return (
                  <div className="p-8 text-center">
                    <p className="text-gray-600">Dia livre! 🎉</p>
                    <p className="text-xs text-gray-700 mt-1">Nenhum evento ou tarefa para hoje</p>
                  </div>
                );
              }
              const sortedEvents = [...todayEvents].sort((a, b) => {
                if (a.event_type === 'flexible' && b.event_type !== 'flexible') return 1;
                if (a.event_type !== 'flexible' && b.event_type === 'flexible') return -1;
                return (a.start_time || '').localeCompare(b.start_time || '');
              });
              const rowEditor = (note?: string) => (
                <div className="flex-1 min-w-0 flex flex-col sm:flex-row gap-2 sm:items-center">
                  <input
                    type="text" value={rowTitle} autoFocus
                    onChange={e => setRowTitle(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') saveRow(); if (e.key === 'Escape') cancelEditRow(); }}
                    className="flex-1 min-w-0 bg-[#222] border border-[#333] rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500"
                  />
                  <div className="flex gap-2 items-center">
                    <input
                      type="time" value={rowTime}
                      onChange={e => setRowTime(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') saveRow(); if (e.key === 'Escape') cancelEditRow(); }}
                      className="bg-[#222] border border-[#333] rounded-lg px-2 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500 w-24"
                    />
                    <button onClick={saveRow} disabled={savingRow || !rowTitle.trim()}
                      className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-30 text-white text-xs font-medium rounded-lg">
                      Guardar
                    </button>
                    <button onClick={cancelEditRow} className="p-1.5 text-gray-500 hover:text-white rounded-lg hover:bg-white/10">
                      <X size={14} />
                    </button>
                  </div>
                  {note && <p className="text-[10px] text-yellow-500/80 sm:w-full sm:order-last">{note}</p>}
                </div>
              );
              return (
                <div className="divide-y divide-[#1a1a1a]">
                  {/* Pending tasks first (most actionable) */}
                  {pendingTasks.map(task => (
                    <div key={task.id} className="group flex items-center gap-4 p-4 hover:bg-white/5">
                      <button onClick={() => toggleTask(task)}
                        className="w-6 h-6 rounded-full border-2 border-gray-600 hover:border-green-400 flex items-center justify-center shrink-0">
                      </button>
                      <div className="w-1 h-8 rounded-full" style={{ backgroundColor: task.color }} />
                      {editingRow?.kind === 'task' && editingRow.id === task.item_id ? rowEditor() : (<>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium">{task.title}</p>
                          <div className="flex items-center gap-2 mt-0.5">
                            {task.start_time && <span className="text-xs text-gray-500">{task.start_time}</span>}
                            <span className="text-[10px] text-green-400 flex items-center gap-1">
                              ✅ {task.list_name}
                            </span>
                          </div>
                        </div>
                        {task.priority > 0 && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-orange-500/20 text-orange-400">
                            {'!'.repeat(task.priority)}
                          </span>
                        )}
                        {/* Arranca o cronómetro. Não risca nada: começar não é
                            ter feito. */}
                        <ComecarTarefa nome={task.title} cor={task.color} icone="✅" tamanho={14} />
                        <div className="flex items-center gap-1 shrink-0">
                          <button onClick={() => startEditTask(task)} title="Editar"
                            className="p-1.5 rounded-lg text-gray-500 hover:text-blue-400 hover:bg-white/10">
                            <Pencil size={14} />
                          </button>
                          <button onClick={() => unscheduleTask(task)} title="Tirar de hoje (mantém na lista)"
                            className="p-1.5 rounded-lg text-gray-600 hover:text-yellow-400 hover:bg-white/10">
                            <CalendarX size={14} />
                          </button>
                          <button onClick={() => deleteTask(task)} title="Apagar tarefa"
                            className="p-1.5 rounded-lg text-gray-500 hover:text-red-400 hover:bg-white/10">
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </>)}
                    </div>
                  ))}
                  {/* Events */}
                  {sortedEvents.map(event => {
                    const catInfo = EVENT_CATEGORIES.find(c => c.value === event.category);
                    return (
                      <div key={event.id} className="group flex items-center gap-4 p-4 hover:bg-white/5">
                        <button onClick={() => toggleEvent(event)}
                          className={`w-6 h-6 rounded-full border-2 flex items-center justify-center shrink-0 ${
                            event.completed ? 'border-green-400 bg-green-400' : 'border-gray-600 hover:border-green-400'
                          }`}>
                          {event.completed && <Check size={14} className="text-black" />}
                        </button>
                        <div className="w-1 h-8 rounded-full" style={{ backgroundColor: event.color }} />
                        {editingRow?.kind === 'event' && editingRow.id === event.id ? (
                          rowEditor(event.recurrence && event.recurrence !== 'none'
                            ? 'Este evento repete-se — a alteração aplica-se a todas as repetições.'
                            : undefined)
                        ) : (<>
                          <div className="flex-1 min-w-0">
                            <p className={`text-sm font-medium ${event.completed ? 'line-through text-gray-600' : ''}`}>
                              {event.title}
                            </p>
                            <div className="flex items-center gap-2 mt-0.5">
                              {event.event_type === 'fixed' && event.start_time && (
                                <span className="text-xs text-gray-500">{event.start_time}{event.end_time ? ` - ${event.end_time}` : ''}</span>
                              )}
                              {event.event_type === 'flexible' && (
                                <span className="text-xs text-purple-400 flex items-center gap-1">
                                  <Clock size={10} /> Flexível
                                </span>
                              )}
                            </div>
                          </div>
                          <span className="text-xs px-2 py-0.5 rounded-full shrink-0" style={{ backgroundColor: event.color + '22', color: event.color }}>
                            {catInfo?.label || event.category}
                          </span>
                          {!event.completed && (
                            <ComecarTarefa nome={event.title} cor={event.color} icone="📅" tamanho={14} />
                          )}
                          <div className="flex items-center gap-1 shrink-0">
                            <button onClick={() => startEditEvent(event)} title="Editar"
                              className="p-1.5 rounded-lg text-gray-500 hover:text-blue-400 hover:bg-white/10">
                              <Pencil size={14} />
                            </button>
                            <button onClick={() => deleteEvent(event)}
                              title={event.is_recurring_instance ? 'Remover só de hoje' : 'Apagar evento'}
                              className="p-1.5 rounded-lg text-gray-500 hover:text-red-400 hover:bg-white/10">
                              <Trash2 size={14} />
                            </button>
                          </div>
                        </>)}
                      </div>
                    );
                  })}
                  {/* Completed tasks — collapsible */}
                  {completedTasks.length > 0 && (
                    <div className="bg-[#0f0f0f]/50">
                      <button
                        onClick={() => setShowCompletedTasks(!showCompletedTasks)}
                        className="w-full flex items-center gap-2 p-3 hover:bg-white/5 text-xs text-gray-500"
                      >
                        {showCompletedTasks ? <ChevronLeft size={12} className="rotate-90" /> : <ChevronRight size={12} />}
                        <Check size={12} className="text-green-400" />
                        <span>{completedTasks.length} tarefa{completedTasks.length > 1 ? 's' : ''} concluída{completedTasks.length > 1 ? 's' : ''}</span>
                      </button>
                      {showCompletedTasks && completedTasks.map(task => (
                        <div key={task.id} className="group flex items-center gap-4 p-4 pl-6 hover:bg-white/5">
                          <button onClick={() => toggleTask(task)}
                            className="w-6 h-6 rounded-full border-2 border-green-400 bg-green-400 flex items-center justify-center shrink-0">
                            <Check size={14} className="text-black" />
                          </button>
                          <div className="w-1 h-8 rounded-full opacity-50" style={{ backgroundColor: task.color }} />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium line-through text-gray-600">{task.title}</p>
                            <span className="text-[10px] text-gray-600">
                              ✅ {task.list_name}
                            </span>
                          </div>
                          <button onClick={() => deleteTask(task)} title="Apagar tarefa"
                            className="p-1.5 rounded-lg text-gray-600 hover:text-red-400 hover:bg-white/10 shrink-0 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
                            <Trash2 size={14} />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })()}
            </div>
            {(() => {
              const atrasados = allPending.filter(p => p.due_date && p.due_date < todayStr);
              if (atrasados.length === 0) return null;
              return (
                <div className="shrink-0 border-t border-[#1a1a1a] bg-red-500/[0.04]">
                  <div className="px-4 pt-3 pb-1 flex items-center gap-2">
                    <CalendarX size={13} className="text-red-400" />
                    <span className="text-[11px] font-medium uppercase tracking-wider text-red-400">
                      {atrasados.length} atrasado{atrasados.length > 1 ? 's' : ''}
                    </span>
                  </div>
                  <div className="divide-y divide-[#1a1a1a]">
                    {atrasados.map(item => {
                      const dias = Math.round((new Date(todayStr).getTime() - new Date(item.due_date).getTime()) / 86400000);
                      const busy = pickingId === item.id;
                      return (
                        <div key={item.id} className="group flex items-center gap-3 px-4 py-2.5">
                          <button
                            onClick={() => concluirPendente(item)}
                            disabled={busy}
                            title="Marcar como feita"
                            className="w-5 h-5 rounded-full border-2 border-gray-500 hover:border-green-400 shrink-0 disabled:opacity-40"
                          />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm truncate">{item.text}</p>
                            <p className="text-[10px] text-red-400/80">
                              {item.list_name} · há {dias} dia{dias === 1 ? '' : 's'}
                            </p>
                          </div>
                          <div className="flex items-center gap-1 shrink-0">
                            <button
                              onClick={() => reagendar(item, 'hoje')}
                              disabled={busy}
                              className="text-[10px] px-2 py-1 rounded-lg bg-blue-500/15 text-blue-300 hover:bg-blue-500/25 disabled:opacity-40"
                            >
                              hoje
                            </button>
                            <button
                              onClick={() => reagendar(item, 'amanha')}
                              disabled={busy}
                              className="text-[10px] px-2 py-1 rounded-lg bg-[#222] text-gray-400 hover:text-gray-200 disabled:opacity-40"
                            >
                              amanhã
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })()}
            {(() => {
              const todos = allPending.filter(p => p.due_date !== todayStr && !(p.due_date && p.due_date < todayStr));
              if (todos.length === 0) return null;
              const listas = Array.from(new Set(todos.map(p => p.list_name))).sort();
              const sugg = filtroLista ? todos.filter(p => p.list_name === filtroLista) : todos;
              return (
                <div className="hidden lg:flex lg:flex-1 lg:min-h-[120px] flex-col border-t border-[#1a1a1a]">
                  <div className="shrink-0 flex items-center gap-2 px-4 pt-3.5 pb-1">
                    <span className="text-[11px] font-medium uppercase tracking-wider text-gray-600">Sugestões</span>
                    <span className="text-[11px] text-gray-700"> · reminders por fazer</span>
                    {listas.length > 1 && (
                      <select value={filtroLista} onChange={e => setFiltroLista(e.target.value)}
                        className="ml-auto bg-transparent text-[10px] text-gray-500 hover:text-gray-300 focus:outline-none cursor-pointer">
                        <option value="">todas as listas</option>
                        {listas.map(l => <option key={l} value={l}>{l}</option>)}
                      </select>
                    )}
                  </div>
                  {/* Rola aqui dentro, como os TODOs de código: cortar na
                      quarta escondia as outras sem forma de lá chegar. */}
                  <div className="divide-y divide-[#1a1a1a] lg:flex-1 lg:min-h-0 lg:overflow-y-auto">
                    {sugg.map(item => (
                      <div key={item.id} className="group flex items-center gap-4 px-4 py-3 hover:bg-white/5">
                        <span className="w-6 text-center text-base shrink-0 opacity-70">{item.list_icon}</span>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-gray-400 group-hover:text-gray-200 truncate transition-colors">{item.text}</p>
                          <div className="flex items-center gap-2 mt-0.5">
                            <span className="text-[10px] text-gray-600">{item.list_name}</span>
                            {item.priority > 0 && <span className="text-[10px] text-orange-400/80">{'!'.repeat(item.priority)}</span>}
                          </div>
                        </div>
                        <button
                          onClick={() => scheduleForToday(item)}
                          disabled={pickingId === item.id}
                          className="shrink-0 flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-lg text-blue-400 hover:bg-blue-500/10 disabled:opacity-50 transition-colors"
                        >
                          {pickingId === item.id ? '…' : <><Plus size={12} /> Hoje</>}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}
            {codeTodos.length > 0 && (() => {
              const projectos = Array.from(new Set(codeTodos.map(t => t.project))).sort();
              const visiveis = filtroProjecto ? codeTodos.filter(t => t.project === filtroProjecto) : codeTodos;
              return (
              <div className={`flex flex-col border-t border-[#1a1a1a] ${todosAbertos ? 'lg:flex-1 lg:min-h-[120px]' : 'shrink-0'}`}>
                <div className="shrink-0 px-4 pt-3 pb-1 flex items-center gap-2">
                  <button onClick={alternarTodos}
                          title={todosAbertos ? 'Esconder os TODOs de código' : 'Mostrar os TODOs de código'}
                          className="flex items-center gap-2 text-gray-600 hover:text-gray-300 transition-colors">
                    <ChevronRight size={12} className={`transition-transform ${todosAbertos ? 'rotate-90' : ''}`} />
                    <Code2 size={12} className="text-blue-400" />
                    <span className="text-[11px] font-medium uppercase tracking-wider">TODOs de código</span>
                    {!todosAbertos && <span className="text-[11px] text-gray-600">{visiveis.length}</span>}
                  </button>
                  {/* Um projecto de cada vez, ou todos: com cinco projectos
                      abertos, a lista era um monte sem dono. */}
                  {todosAbertos && projectos.length > 1 && (
                    <select value={filtroProjecto} onChange={e => setFiltroProjecto(e.target.value)}
                      className="ml-auto bg-transparent text-[10px] text-gray-500 hover:text-gray-300 focus:outline-none cursor-pointer">
                      <option value="">todos os projectos</option>
                      {projectos.map(p => <option key={p} value={p}>{p}</option>)}
                    </select>
                  )}
                </div>
                {/* Só isto rola: o resto da agenda fica quieto. */}
                <div className={`divide-y divide-[#1a1a1a] lg:flex-1 lg:min-h-0 lg:overflow-y-auto ${todosAbertos ? '' : 'hidden'}`}>
                  {visiveis.map(t => (
                    <div key={t.id} className="group flex items-center gap-3 px-4 py-2.5">
                      <button
                        onClick={() => fecharCodeTodo(t.id)}
                        title="Marcar como feita"
                        className="w-5 h-5 rounded-full border-2 border-gray-500 hover:border-emerald-400 shrink-0"
                      />
                      <div className="flex-1 min-w-0 cursor-pointer" onClick={() => navigate('/code')}>
                        <p className="text-sm truncate text-gray-400 group-hover:text-gray-200 transition-colors">{t.content}</p>
                        <p className="text-[10px] text-gray-600">{t.project}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              );
            })()}
            </div>
          </div>
        </div>
        {/* Direita — plano, sono, tipo de dia, hábitos, como foi o dia. São
            mais cartões do que cabem numa janela: rolam aqui dentro. */}
        {/* A folga da coluna vai para os cartões que são listas (o plano e os
            hábitos), que crescem; repartida pelos espaços entre eles ficavam
            buracos de ar entre cartões. */}
        <div className="w-full lg:w-[380px] shrink-0 flex flex-col gap-2
          lg:overflow-y-auto lg:min-h-0 lg:pr-1">

      {/* Tipo de Dia */}
      <div className="bg-[#161616] rounded-2xl border border-[#222] p-3 lg:shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className={`text-3xl ${todayDayType ? '' : 'opacity-60'}`}>
              {(todayDayType
                ? DAY_TYPE_PRESETS.find(p => p.name === todayDayType.type_name)?.icon
                : DEFAULT_DAY_TYPE.icon) || '📅'}
            </span>
            <div>
              <p className="text-xs text-gray-500">Tipo de Dia</p>
              <div className="flex items-center gap-2 flex-wrap">
                <p className="text-base font-medium" style={{ color: inkColor(todayDayType?.color || DEFAULT_DAY_TYPE.color) }}>
                  {todayDayType?.type_name || DEFAULT_DAY_TYPE.name}
                </p>
                {!todayDayType && <span className="text-[10px] text-gray-600">por omissão</span>}
                {STREAK_PROTECTED_DAY_TYPES.includes(todayDayType?.type_name || '') && (
                  <span className="text-[10px] bg-green-500/20 text-green-400 px-2 py-0.5 rounded-full">
                    Streak protegida
                  </span>
                )}
              </div>
            </div>
          </div>
          <button
            onClick={() => setShowDayTypePicker(!showDayTypePicker)}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-all ${showDayTypePicker ? 'bg-blue-600/20 text-blue-400' : 'bg-white/5 text-gray-400 hover:text-white'}`}
          >
            {todayDayType ? <Pencil size={12} /> : <Plus size={12} />} {todayDayType ? 'Mudar' : 'Definir'}
          </button>
        </div>
        {showDayTypePicker && (
          <div className="mt-3 pt-3 border-t border-[#222]">
            <div className="flex gap-2 flex-wrap">
              {DAY_TYPE_PRESETS.map(p => {
                const isSelected = todayDayType?.type_name === p.name;
                const isProtected = STREAK_PROTECTED_DAY_TYPES.includes(p.name);
                return (
                  <button
                    key={p.name}
                    onClick={() => setDayType(p)}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                      isSelected ? 'ring-2 ring-white/50' : 'hover:scale-105'
                    }`}
                    style={{ backgroundColor: p.color + '22', color: p.color }}
                    title={isProtected ? 'Protege streaks de hábitos' : ''}
                  >
                    <span>{p.icon}</span> {p.name}
                    {isProtected && <span className="text-[9px] opacity-60">🛡️</span>}
                  </button>
                );
              })}
              {todayDayType && (
                <button
                  onClick={() => setDayType(null)}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-500/10 text-red-400 hover:bg-red-500/20"
                >
                  <X size={12} /> Remover
                </button>
              )}
            </div>
          </div>
        )}
      </div>
          {todayHabits.length > 0 && (
            <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden lg:grow lg:shrink-0">
              <div className="flex items-center justify-between px-4 py-2.5 border-b border-[#222]">
                <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
                  <Target size={14} className="text-green-400" /> Hábitos de Hoje
                </h3>
                <span className="text-xs text-gray-500">
                  {todayHabits.filter(h => h.completed).length}/{todayHabits.length}
                </span>
              </div>
              <div className="divide-y divide-[#1a1a1a]">
                {todayHabits.map(h => (
                  <div
                    key={h.id}
                    onClick={async () => {
                      if (h.completed && h.completion) {
                        await habitsApi.deleteCompletion(h.id, h.completion.id).catch(() => {});
                      } else {
                        const now = new Date();
                        await habitsApi.complete(h.id, {
                          date: todayStr,
                          completed_at: format(now, 'HH:mm'),
                        }).catch(() => {});
                      }
                      const fresh = await habitsApi.today().catch(() => []);
                      setTodayHabits(fresh);
                      habitsApi.suggestions().then(setHabitHints).catch(() => {});
                    }}
                    className="flex items-center gap-3 px-3 py-1.5 cursor-pointer hover:bg-white/5 transition"
                  >
                    <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center shrink-0 ${
                      h.completed ? 'border-green-400 bg-green-400' : 'border-gray-600'
                    }`}>
                      {h.completed && <Check size={12} className="text-black" />}
                    </div>
                    <span className="text-sm">{h.icon}</span>
                    <div className="flex-1 min-w-0">
                      <p className={`text-sm font-medium truncate ${h.completed ? 'line-through text-gray-600' : ''}`}>{h.name}</p>
                      {h.completion && (
                        <p className="text-[10px] text-gray-600" title={h.completion.notes || undefined}>
                          Feito às {h.completion.completed_at}
                          {h.completion.notes?.startsWith('pelo relógio') && ' · ⌚ pelo relógio'}
                        </p>
                      )}
                      {!h.completed && habitHints.find(x => x.habit_id === h.id) && (
                        <p className="text-[10px] text-emerald-400/90">
                          detectado: {habitHints.find(x => x.habit_id === h.id)!.reason}
                        </p>
                      )}
                    </div>
                    {!h.completed && habitHints.find(x => x.habit_id === h.id) && (
                      <span className="text-[10px] px-2 py-1 rounded-lg bg-emerald-500/15 text-emerald-300 shrink-0">
                        confirmar
                      </span>
                    )}
                    {!h.completed && (
                      <span className="text-[10px] text-gray-600">
                        {h.fixed_time ? `⏰ ${h.fixed_time}` : '🔄'}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
      {/* Registo rápido: um toque no emoji e está feito. */}
      {!todayMood && !editingMood && (
        <div className="bg-[#161616] rounded-2xl border border-[#222] px-4 py-3 lg:shrink-0">
          <div className="flex items-center justify-between mb-2.5">
            <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
              <Heart size={14} className="text-pink-400" /> Como foi o dia?
            </h3>
            <button onClick={() => setEditingMood(true)} className="text-[11px] text-gray-500 hover:text-gray-300">
              detalhe
            </button>
          </div>
          <div className="grid grid-cols-4 gap-2">
            {DAY_QUALITIES.map(q => (
              <button
                key={q.value}
                onClick={() => guardarHumorRapido(q.value)}
                disabled={savingQuickMood !== null}
                title={`${q.label} — guarda já`}
                className="flex flex-col items-center gap-1 py-3 rounded-xl bg-white/5 hover:bg-white/10 disabled:opacity-50 transition-all"
              >
                {savingQuickMood === q.value
                  ? <Loader2 size={22} className="animate-spin text-gray-400" />
                  : <span className="text-2xl">{q.emoji}</span>}
                <span className="text-[11px] text-gray-400">{q.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}


      {/* Day rating — full selector when not set or editing */}
      {editingMood && (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-5 lg:shrink-0">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
              <Heart size={14} className="text-pink-400" /> {editingMood ? 'Editar dia' : 'Como foi o dia?'}
            </h3>
            <div className="flex items-center gap-1">
              <button onClick={openHistory} className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] bg-white/5 text-gray-400 hover:text-white hover:bg-white/10">
                <History size={12} /> Histórico
              </button>
              {editingMood && (
                <button
                  onClick={() => {
                    setEditingMood(false);
                    if (todayMood) {
                      setDayQuality(todayMood.quality || '');
                      setDayRating(typeof todayMood.mood === 'number' ? todayMood.mood : null);
                      setMoodNote(todayMood.note || '');
                    }
                  }}
                  className="p-1 text-gray-500 hover:text-white"
                >
                  <X size={14} />
                </button>
              )}
            </div>
          </div>

          {/* Quality */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
            {DAY_QUALITIES.map(q => {
              const active = dayQuality === q.value;
              return (
                <button
                  key={q.value}
                  onClick={() => setDayQuality(q.value)}
                  className={`flex flex-col items-center gap-1 py-3 rounded-xl transition-all ${active ? 'bg-white/10' : 'bg-white/5 hover:bg-white/10'}`}
                  style={active ? { boxShadow: `inset 0 0 0 2px ${q.color}` } : undefined}
                >
                  <span className="text-2xl">{q.emoji}</span>
                  <span className="text-[11px]" style={{ color: active ? inkColor(q.color) : '#9ca3af' }}>{q.label}</span>
                </button>
              );
            })}
          </div>

          {/* Rating 0-10 */}
          <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-[10px] text-gray-500">Avaliação (0-10)</p>
              {dayRating !== null && (
                <span className="text-sm font-bold" style={{ color: inkColor(ratingColor(dayRating)) }}>{dayRating}/10</span>
              )}
            </div>
            <div className="flex gap-1 flex-wrap">
              {Array.from({ length: 11 }, (_, n) => {
                const active = dayRating === n;
                return (
                  <button
                    key={n}
                    onClick={() => setDayRating(n)}
                    className={`flex-1 min-w-[26px] py-2 rounded-lg text-xs font-medium transition-all ${active ? 'text-white' : 'bg-white/5 text-gray-400 hover:bg-white/10'}`}
                    style={active ? { backgroundColor: ratingColor(n) } : undefined}
                  >
                    {n}
                  </button>
                );
              })}
            </div>
          </div>

          <input
            type="text"
            value={moodNote}
            onChange={e => setMoodNote(e.target.value)}
            placeholder="Nota rápida (opcional)..."
            className="w-full bg-[#222] border border-[#333] rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-pink-500/50"
          />
          <div className="mt-3 flex justify-end">
            <button
              onClick={saveMood}
              disabled={!dayQuality || dayRating === null}
              className="px-4 py-1.5 bg-pink-600 hover:bg-pink-500 disabled:opacity-30 disabled:cursor-not-allowed text-white text-xs font-medium rounded-lg"
            >
              {editingMood ? 'Guardar alterações' : 'Guardar'}
            </button>
          </div>
        </div>
      )}
      {/* Today's rating display + journal toggle */}
      {todayMood && !editingMood && (() => {
        const q = DAY_QUALITIES.find(x => x.value === todayMood.quality);
        return (
          <div className="bg-[#161616] rounded-2xl border border-[#222] p-3 flex items-center justify-between gap-3 lg:shrink-0">
            <div className="flex items-center gap-3 flex-1 min-w-0">
              <span className="text-3xl">{q?.emoji || '😐'}</span>
              <div className="flex-1 min-w-0">
                {/* tudo numa linha, sem truncar: os três botões ao lado eram
                    texto e ícone e não sobrava largura nenhuma para "Mais ou
                    menos" — agora são só ícones. */}
                <p className="text-base font-medium flex items-center gap-2 whitespace-nowrap">
                  <span style={{ color: inkColor(q?.color || '#9ca3af') }}>{q?.label || 'Dia'}</span>
                  <span className="text-xs font-bold px-1.5 py-0.5 rounded shrink-0"
                    style={{ backgroundColor: `${ratingColor(todayMood.mood)}22`, color: ratingColor(todayMood.mood) }}>
                    {todayMood.mood}/10
                  </span>
                </p>
                {todayMood.note && <p className="text-xs text-gray-500 mt-1 truncate">{todayMood.note}</p>}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button onClick={openHistory} title="Histórico de dias"
                className="p-2 rounded-lg bg-white/5 text-gray-400 hover:text-white hover:bg-white/10">
                <History size={14} />
              </button>
              <button onClick={() => setEditingMood(true)} title="Editar o dia"
                className="p-2 rounded-lg bg-white/5 text-gray-400 hover:text-white hover:bg-white/10">
                <Edit2 size={14} />
              </button>
              <button onClick={() => setShowJournal(!showJournal)} title="Diário de hoje"
                className={`p-2 rounded-lg transition-all ${showJournal ? 'bg-purple-600/20 text-purple-400' : 'bg-white/5 text-gray-400 hover:text-white'}`}>
                <BookOpen size={14} />
              </button>
            </div>
          </div>
        );
      })()}
      {/* Quick Journal */}
      {showJournal && (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-5 lg:shrink-0">
          <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
            <BookOpen size={14} className="text-purple-400" /> Diário Rápido
          </h3>
          {dayFacts.length > 0 && (
            <div className="mb-3">
              <div className="flex flex-wrap gap-1.5 mb-2">
                {dayFacts.map(f => (
                  <span key={f.key} className="text-[11px] px-2 py-1 rounded-lg bg-[#1a1a1a] text-gray-400">
                    {f.icon} {f.label}
                  </span>
                ))}
              </div>
              <button
                onClick={escreverPorMim}
                disabled={aRascunhar}
                className="text-[11px] px-2.5 py-1 rounded-lg bg-purple-500/15 text-purple-300 hover:bg-purple-500/25 disabled:opacity-40 flex items-center gap-1.5"
              >
                {aRascunhar ? <Loader2 size={11} className="animate-spin" /> : <Wand2 size={11} />}
                {aRascunhar ? 'a escrever…' : 'Escrever o dia por mim'}
              </button>
            </div>
          )}
          {perguntasDia.length > 0 && (
            <div className="mb-3">
              <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-1.5">Perguntas de hoje</p>
              <div className="flex flex-col gap-1">
                {perguntasDia.map(p => {
                  const usada = journalContent.includes(p.question);
                  return (
                    <button
                      key={p.key}
                      onClick={() => juntarPergunta(p.question)}
                      className={`flex items-center gap-2 text-left text-[11px] px-2.5 py-1.5 rounded-lg transition-colors ${
                        usada ? 'bg-purple-500/10 text-purple-300/70' : 'bg-[#1a1a1a] text-gray-400 hover:text-gray-200 hover:bg-white/5'
                      }`}
                    >
                      <span>{p.icon}</span>
                      <span className="flex-1">{p.question}</span>
                      {usada && <Check size={11} className="text-purple-400/70 shrink-0" />}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          <textarea
            ref={journalRef}
            value={journalContent}
            onChange={e => setJournalContent(e.target.value)}
            placeholder="O que aconteceu hoje? O que tens em mente?..."
            rows={6}
            className="w-full bg-[#222] border border-[#333] rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-purple-500/50 resize-none"
          />
          <div className="flex justify-between items-center mt-2">
            <p className="text-[10px] text-gray-600">{journalContent.length} chars</p>
            <button
              onClick={saveJournal}
              disabled={!journalContent.trim()}
              className="px-4 py-1.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-30 text-white text-xs font-medium rounded-lg transition-colors"
            >
              {todayJournal ? 'Atualizar' : 'Guardar'}
            </button>
          </div>
        </div>
      )}

          {/* Sono desta noite — o que o relógio mediu, e mais nada. Escrever
              horas à mão e pôr estrelas de 1 a 5 acabou: a noite chega sozinha
              com a pontuação da Garmin. */}
          {(() => {
            const noite = sleepStats?.entries?.find(e => e.date === todayStr) || null;
            return (
              <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden lg:shrink-0">
                <div className="flex items-center justify-between gap-2 px-4 py-2.5 border-b border-[#222]">
                  <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2 min-w-0">
                    <Moon size={14} className="text-purple-400 shrink-0" /> <span className="truncate">Sono desta noite</span>
                  </h3>
                  {/* Saí / bebi vive aqui, no cabeçalho: é sobre a noite que este
                      cartão mostra, e uma linha a mais punha a coluna a rolar. */}
                  <div className="flex items-center gap-2 shrink-0">
                    <NoiteFora data={format(subDays(today, 1), 'yyyy-MM-dd')} />
                    <button onClick={() => navigate('/sleep')} className="text-xs text-purple-400 hover:text-purple-300 flex items-center gap-1 shrink-0">
                      Ver tudo <ArrowRight size={12} />
                    </button>
                  </div>
                </div>

                {noite ? (
                  <div className="flex items-center gap-3 px-4 py-2.5">
                    <span className="text-3xl shrink-0">{noite.hours >= 7 ? '😴' : noite.hours >= 5 ? '😐' : '😵'}</span>
                    <div className="flex-1 min-w-0">
                      <p className={`text-2xl font-bold leading-none tabular-nums ${noite.hours >= 7 ? 'text-green-400' : noite.hours >= 5 ? 'text-yellow-400' : 'text-red-400'}`}>
                        {horasEMinutos(noite.hours)}
                      </p>
                      <p className="text-xs text-gray-500 mt-1.5">
                        {noite.bedtime && noite.wake_time ? `${noite.bedtime} → ${noite.wake_time}` : 'sem horas'}
                      </p>
                    </div>
                    {noite.score != null && (
                      <div className="text-right shrink-0 pl-3 border-l border-[#222]">
                        <p className="text-2xl font-bold leading-none tabular-nums" style={{ color: corDaPontuacao(noite.score) }}>
                          {noite.score}<span className="text-xs text-gray-600">/100</span>
                        </p>
                        <p className="text-[10px] text-gray-600 mt-1.5">pontuação</p>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="p-4">
                    <p className="text-sm text-gray-500">Esta noite ainda não foi medida.</p>
                    <p className="text-[11px] text-gray-600 mt-1">
                      Aparece aqui pouco depois de o relógio passar pelo telemóvel.
                    </p>
                  </div>
                )}
              </div>
            );
          })()}
        </div>
      </div>
      </>)}

      {vista === 'resumo' && (<>
      {/* Resumo rápido */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4 mb-6 lg:shrink-0">
        <div onClick={() => navigate('/calendar')}
          className="bg-[#161616] rounded-2xl p-5 border border-[#222] cursor-pointer hover:border-blue-500/50 transition-all">
          <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
            <Calendar size={14} className="text-blue-400" /> Hoje
          </div>
          <p className="text-2xl font-bold">{completedToday}<span className="text-gray-600">/{totalToday}</span></p>
          <p className="text-xs text-gray-500 mt-1">tarefas concluídas</p>
        </div>
        <div onClick={() => navigate('/expenses')}
          className="bg-[#161616] rounded-2xl p-5 border border-[#222] cursor-pointer hover:border-green-500/50 transition-all">
          <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
            <Wallet size={14} className="text-green-400" /> Esta semana
          </div>
          <p className="text-2xl font-bold text-red-400">€{weekTotal.toFixed(2)}</p>
          <p className="text-xs text-gray-500 mt-1">{weekExpenses.length} transações</p>
        </div>
        <div onClick={() => navigate('/sleep')}
          className="bg-[#161616] rounded-2xl p-5 border border-[#222] cursor-pointer hover:border-purple-500/50 transition-all">
          <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
            <Moon size={14} className="text-purple-400" /> Sono (7 dias)
          </div>
          {sleepStats && sleepStats.total_entries > 0 ? (
            <>
              <p className={`text-2xl font-bold tabular-nums ${sleepStats.avg_hours >= 7 ? 'text-green-400' : sleepStats.avg_hours >= 5 ? 'text-yellow-400' : 'text-red-400'}`}>
                {horasEMinutos(sleepStats.avg_hours)}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                média de {sleepStats.total_entries} {sleepStats.total_entries === 1 ? 'noite' : 'noites'}
                {sleepStats.avg_score != null && (
                  <span style={{ color: corDaPontuacao(sleepStats.avg_score) }}> · {sleepStats.avg_score}/100</span>
                )}
              </p>
            </>
          ) : (
            <>
              <p className="text-2xl font-bold text-gray-600">—</p>
              <p className="text-xs text-gray-500 mt-1">sem noites medidas</p>
            </>
          )}
        </div>
        <div onClick={() => navigate('/lol')}
          className="bg-[#161616] rounded-2xl p-5 border border-[#222] cursor-pointer hover:border-yellow-500/50 transition-all">
          <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
            <Swords size={14} className="text-yellow-400" /> LoL Stats
          </div>
          {lolStats ? (
            <>
              <p className={`text-2xl font-bold ${lolStats.winrate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                {lolStats.winrate}%
              </p>
              <p className="text-xs text-gray-500 mt-1">{lolStats.wins}W {lolStats.losses}L</p>
            </>
          ) : (
            <>
              <p className="text-2xl font-bold text-gray-600">—</p>
              <p className="text-xs text-gray-500 mt-1">sem games</p>
            </>
          )}
        </div>
        <div onClick={() => navigate('/trips')}
          className="bg-[#161616] rounded-2xl p-5 border border-[#222] cursor-pointer hover:border-cyan-500/50 transition-all">
          <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
            <Plane size={14} className="text-cyan-400" /> Próxima viagem
          </div>
          {nextTrip ? (
            <>
              <p className="text-lg font-bold truncate">{nextTrip.destination}</p>
              <p className="text-xs text-gray-500 mt-1">{format(new Date(nextTrip.start_date), 'd MMM', { locale: pt })}</p>
            </>
          ) : (
            <>
              <p className="text-lg font-bold text-gray-600">—</p>
              <p className="text-xs text-gray-500 mt-1">sem viagens</p>
            </>
          )}
        </div>
        <div onClick={() => navigate('/investments')}
          className="bg-[#161616] rounded-2xl p-5 border border-[#222] cursor-pointer hover:border-emerald-500/50 transition-all">
          <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
            <LineChart size={14} className="text-emerald-400" /> Investimentos
          </div>
          {investmentSummary && investmentSummary.total_value > 0 ? (
            <>
              <p className="text-2xl font-bold">€{Number(investmentSummary.total_value).toLocaleString('pt-PT', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}</p>
              <p className={`text-xs mt-1 ${investmentSummary.total_return >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {investmentSummary.total_return >= 0 ? '↑' : '↓'} €{Math.abs(investmentSummary.total_return).toFixed(0)} ({investmentSummary.total_return_pct > 0 ? '+' : ''}{investmentSummary.total_return_pct.toFixed(1)}%)
              </p>
            </>
          ) : (
            <>
              <p className="text-2xl font-bold text-gray-600">—</p>
              <p className="text-xs text-gray-500 mt-1">sem posições</p>
            </>
          )}
        </div>
      </div>
      </>)}

      {/* Monthly history modal — fica sempre montado: quem o abre é o "como foi
          o dia", que vive na outra vista. */}
      {showMoodHistory && (() => {
        const monthStart = startOfMonth(historyMonth);
        const monthEnd = endOfMonth(historyMonth);
        const gridStart = startOfWeek(monthStart, { weekStartsOn: 1 });
        const gridEnd = endOfWeek(monthEnd, { weekStartsOn: 1 });
        const days = eachDayOfInterval({ start: gridStart, end: gridEnd });
        const byDate: Record<string, any> = {};
        historyMoods.forEach(m => { byDate[m.date] = m; });
        const monthEntries = historyMoods.filter(m => isSameMonth(new Date(m.date + 'T00:00:00'), historyMonth));
        const avg = monthEntries.length ? monthEntries.reduce((s, m) => s + m.mood, 0) / monthEntries.length : null;
        const isFutureMonth = startOfMonth(historyMonth) >= startOfMonth(new Date());
        return (
          <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4" onClick={() => setShowMoodHistory(false)}>
            <div className="bg-[#161616] rounded-2xl border border-[#222] p-5 w-full max-w-md" onClick={e => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-medium text-gray-200 flex items-center gap-2"><History size={15} className="text-pink-400" /> Histórico de dias</h3>
                <button onClick={() => setShowMoodHistory(false)} className="p-1 text-gray-500 hover:text-white"><X size={16} /></button>
              </div>
              <div className="flex items-center justify-between mb-4">
                <button onClick={() => changeHistoryMonth(-1)} className="p-1.5 rounded-lg hover:bg-white/10 text-gray-400"><ChevronLeft size={16} /></button>
                <div className="text-center">
                  <p className="text-sm font-medium capitalize">{format(historyMonth, 'MMMM yyyy', { locale: pt })}</p>
                  {avg !== null
                    ? <p className="text-[11px] text-gray-500">média <span className="font-bold" style={{ color: inkColor(ratingColor(Math.round(avg))) }}>{avg.toFixed(1)}/10</span> · {monthEntries.length} dias</p>
                    : <p className="text-[11px] text-gray-600">sem registos</p>}
                </div>
                <button onClick={() => changeHistoryMonth(1)} disabled={isFutureMonth} className="p-1.5 rounded-lg hover:bg-white/10 text-gray-400 disabled:opacity-30"><ChevronRight size={16} /></button>
              </div>
              <div className="grid grid-cols-7 gap-1 mb-1">
                {['S', 'T', 'Q', 'Q', 'S', 'S', 'D'].map((d, i) => <div key={i} className="text-center text-[10px] text-gray-600">{d}</div>)}
              </div>
              <div className="grid grid-cols-7 gap-1">
                {days.map(day => {
                  const key = format(day, 'yyyy-MM-dd');
                  const entry = byDate[key];
                  const inMonth = isSameMonth(day, historyMonth);
                  const isCurrentDay = isSameDay(day, new Date());
                  const q = entry ? DAY_QUALITIES.find(x => x.value === entry.quality) : null;
                  const color = entry ? (q?.color || ratingColor(entry.mood)) : null;
                  return (
                    <div
                      key={key}
                      title={entry ? `${q?.label || ''} · ${entry.mood}/10${entry.note ? ' · ' + entry.note : ''}` : undefined}
                      className={`aspect-square rounded-lg flex flex-col items-center justify-center leading-none ${inMonth ? '' : 'opacity-25'} ${isCurrentDay ? 'ring-1 ring-white/40' : ''}`}
                      style={{ backgroundColor: color ? `${color}33` : 'rgba(255,255,255,0.03)' }}
                    >
                      <span className="text-[9px] text-gray-500">{format(day, 'd')}</span>
                      {entry && <span className="text-[11px] font-bold" style={{ color: inkColor(color!) }}>{entry.mood}</span>}
                    </div>
                  );
                })}
              </div>
              {monthEntries.length > 0 ? (
                <div className="mt-4 pt-3 border-t border-[#222] space-y-1.5">
                  <p className="text-[10px] text-gray-500 mb-1">Resumo do mês · {monthEntries.length} {monthEntries.length === 1 ? 'dia' : 'dias'}</p>
                  {DAY_QUALITIES.map(q => {
                    const count = monthEntries.filter(m => m.quality === q.value).length;
                    const pct = Math.round((count / monthEntries.length) * 100);
                    return (
                      <div key={q.value} className="flex items-center gap-2 text-[11px]">
                        <span className="w-4 text-center">{q.emoji}</span>
                        <span className="w-24 shrink-0" style={{ color: inkColor(q.color) }}>{q.label}</span>
                        <div className="flex-1 h-1.5 rounded-full bg-white/5 overflow-hidden">
                          <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: q.color }} />
                        </div>
                        <span className="w-16 text-right text-gray-400 shrink-0">{count} · {pct}%</span>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="flex items-center justify-center gap-3 mt-4 flex-wrap">
                  {DAY_QUALITIES.map(q => (
                    <span key={q.value} className="flex items-center gap-1 text-[10px] text-gray-500">
                      <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: q.color }} /> {q.label}
                    </span>
                  ))}
                </div>
              )}
              {monthEntries.some(m => m.note && m.note.trim()) && (
                <div className="mt-4 pt-3 border-t border-[#222]">
                  <p className="text-[10px] text-gray-500 mb-2">Notas do mês</p>
                  <div className="max-h-40 overflow-y-auto space-y-2 pr-1">
                    {[...monthEntries]
                      .filter(m => m.note && m.note.trim())
                      .sort((a, b) => (a.date < b.date ? 1 : -1))
                      .map(m => {
                        const mq = DAY_QUALITIES.find(x => x.value === m.quality);
                        return (
                          <div key={m.id} className="flex items-start gap-2 text-xs">
                            <span className="shrink-0 text-gray-500 w-12">{format(new Date(m.date + 'T00:00:00'), 'd MMM', { locale: pt })}</span>
                            <span className="shrink-0">{mq?.emoji || '•'}</span>
                            <span className="shrink-0 font-bold" style={{ color: inkColor(mq?.color || ratingColor(m.mood)) }}>{m.mood}</span>
                            <span className="text-gray-400 break-words flex-1 min-w-0">{m.note}</span>
                          </div>
                        );
                      })}
                  </div>
                </div>
              )}
            </div>
          </div>
        );
      })()}
      {/* Weekly Review Card */}
      {vista === 'resumo' && (
      <div className="flex flex-col lg:flex-row gap-4 lg:flex-1 lg:min-h-0">
      <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden
        lg:flex-1 lg:min-h-0 lg:flex lg:flex-col">
        {/* div em vez de button: tem botões lá dentro (setas de semana) e
            <button> dentro de <button> é HTML inválido. */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => setShowWeeklyReview(!showWeeklyReview)}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setShowWeeklyReview(!showWeeklyReview); } }}
          className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-all cursor-pointer shrink-0"
        >
          <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
            <BarChart3 size={14} className="text-blue-400" /> Weekly Review
          </h3>
          <div className="flex items-center gap-2">
            <button onClick={e => { e.stopPropagation(); setWeekOffset(o => o - 1); }} className="p-1 hover:bg-white/10 rounded">
              <ChevronLeft size={14} className="text-gray-500" />
            </button>
            <span className="text-xs text-gray-500 min-w-[100px] text-center">
              {weekOffset === 0 ? 'Esta semana' : weekOffset === -1 ? 'Semana passada' : `${Math.abs(weekOffset)} sem. atrás`}
            </span>
            <button onClick={e => { e.stopPropagation(); setWeekOffset(o => Math.min(0, o + 1)); }} className="p-1 hover:bg-white/10 rounded" disabled={weekOffset >= 0}>
              <ChevronRight size={14} className={weekOffset >= 0 ? 'text-gray-700' : 'text-gray-500'} />
            </button>
          </div>
        </div>

        {showWeeklyReview && wr && (
          <div className="p-4 pt-0 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4
            [@media(min-width:1500px)]:grid-cols-5 gap-3 lg:flex-1 lg:content-start">
            {/* Events */}
            <div className="bg-[#1a1a1a] rounded-xl p-3">
              <p className="text-[10px] text-gray-500 mb-1 flex items-center gap-1"><Calendar size={10} /> Eventos</p>
              <p className="text-lg font-bold">{wr.events.completed}<span className="text-gray-600 text-sm">/{wr.events.total}</span></p>
              <p className="text-[10px] text-gray-500">{wr.events.completion_rate}% concluídos</p>
            </div>

            {/* Expenses */}
            <div className="bg-[#1a1a1a] rounded-xl p-3">
              <p className="text-[10px] text-gray-500 mb-1 flex items-center gap-1"><Wallet size={10} /> Gastos</p>
              <p className="text-lg font-bold text-red-400">€{wr.expenses.total.toFixed(0)}</p>
              {wr.expenses.prev_week_total != null && (
                <p className={`text-[10px] ${wr.expenses.total > wr.expenses.prev_week_total ? 'text-red-400' : 'text-green-400'}`}>
                  {wr.expenses.total > wr.expenses.prev_week_total ? '↑' : '↓'} vs sem. ant. (€{wr.expenses.prev_week_total.toFixed(0)})
                </p>
              )}
            </div>

            {/* LoL */}
            <div className="bg-[#1a1a1a] rounded-xl p-3">
              <p className="text-[10px] text-gray-500 mb-1 flex items-center gap-1"><Swords size={10} /> LoL</p>
              {wr.lol.games > 0 ? (
                <>
                  <p className={`text-lg font-bold ${wr.lol.winrate >= 50 ? 'text-green-400' : 'text-red-400'}`}>{wr.lol.winrate}%</p>
                  <p className="text-[10px] text-gray-500">{wr.lol.games} games ({wr.lol.wins}W)</p>
                </>
              ) : (
                <p className="text-lg font-bold text-gray-600">—</p>
              )}
            </div>

            {/* Sleep */}
            <div className="bg-[#1a1a1a] rounded-xl p-3">
              <p className="text-[10px] text-gray-500 mb-1 flex items-center gap-1"><Moon size={10} /> Sono</p>
              {wr.sleep.avg_hours > 0 ? (
                <>
                  <p className={`text-lg font-bold ${wr.sleep.avg_hours >= 7 ? 'text-green-400' : wr.sleep.avg_hours >= 6 ? 'text-yellow-400' : 'text-red-400'}`}>
                    {wr.sleep.avg_hours.toFixed(1)}h
                  </p>
                  {wr.sleep.prev_avg_hours > 0 && (
                    <p className={`text-[10px] ${wr.sleep.avg_hours >= wr.sleep.prev_avg_hours ? 'text-green-400' : 'text-red-400'}`}>
                      {wr.sleep.avg_hours >= wr.sleep.prev_avg_hours ? '↑' : '↓'} vs {wr.sleep.prev_avg_hours.toFixed(1)}h
                    </p>
                  )}
                </>
              ) : (
                <p className="text-lg font-bold text-gray-600">—</p>
              )}
            </div>

            {/* Flow */}
            <div className="bg-[#1a1a1a] rounded-xl p-3">
              <p className="text-[10px] text-gray-500 mb-1 flex items-center gap-1"><Zap size={10} /> Flow</p>
              {wr.flow.total_hours > 0 ? (
                <>
                  <p className="text-lg font-bold text-blue-400">{wr.flow.total_hours.toFixed(1)}h</p>
                  <p className="text-[10px] text-gray-500">{wr.flow.sessions} sessões</p>
                </>
              ) : (
                <p className="text-lg font-bold text-gray-600">—</p>
              )}
            </div>

            {/* Habits */}
            <div className="bg-[#1a1a1a] rounded-xl p-3">
              <p className="text-[10px] text-gray-500 mb-1 flex items-center gap-1"><Target size={10} /> Hábitos</p>
              {wr.habits.total_scheduled > 0 ? (
                <>
                  <p className={`text-lg font-bold ${wr.habits.completion_rate >= 80 ? 'text-green-400' : wr.habits.completion_rate >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
                    {wr.habits.completion_rate}%
                  </p>
                  <p className="text-[10px] text-gray-500">{wr.habits.total_completed}/{wr.habits.total_scheduled}</p>
                </>
              ) : (
                <p className="text-lg font-bold text-gray-600">—</p>
              )}
            </div>

            {/* Day rating */}
            {wr.mood && wr.mood.entries > 0 && (
              <div className="bg-[#1a1a1a] rounded-xl p-3">
                <p className="text-[10px] text-gray-500 mb-1 flex items-center gap-1"><Heart size={10} /> Dias</p>
                <p className="text-lg font-bold" style={{ color: inkColor(ratingColor(Math.round(wr.mood.average))) }}>{wr.mood.average.toFixed(1)}<span className="text-xs text-gray-500">/10</span></p>
                <p className="text-[10px] text-gray-500">{wr.mood.entries} registos</p>
              </div>
            )}

            {/* Expense categories breakdown */}
            {wr.expenses.by_category && Object.keys(wr.expenses.by_category).length > 0 && (
              <div className="col-span-full bg-[#1a1a1a] rounded-xl p-3">
                <p className="text-[10px] text-gray-500 mb-2">Gastos por categoria</p>
                <div className="flex gap-2 flex-wrap">
                  {Object.entries(wr.expenses.by_category)
                    .sort(([, a]: any, [, b]: any) => b - a)
                    .map(([cat, amount]: [string, any]) => {
                      const catInfo = infoCategoria(cat);
                      return (
                        <span key={cat} className="text-xs bg-[#222] px-2 py-1 rounded-lg">
                          {catInfo.emoji} {catInfo.label}: €{Number(amount).toFixed(0)}
                        </span>
                      );
                    })}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* As viagens estavam na coluna do dia, onde empurravam o "como foi o dia"
          para fora da janela — e o Resumo já tem o cartão "Próxima viagem". Sem
          viagens não há coluna: uma coluna vazia de 320px roubava-os à Weekly
          Review, que é quem tem números para encher a largura. */}
      {upcomingTrips.length > 0 && (
        <div className="lg:w-[320px] lg:shrink-0">
            <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
              <div className="flex items-center justify-between p-4 border-b border-[#222]">
                <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
                  <Plane size={14} className="text-cyan-400" /> Próximas Viagens
                </h3>
              </div>
              <div className="divide-y divide-[#1a1a1a]">
              {upcomingTrips.map(trip => (
                  <div key={trip.id} onClick={() => navigate(`/trips/${trip.id}`)}
                    className="flex items-center gap-3 p-3 hover:bg-white/5 cursor-pointer">
                    <span className="text-lg">✈️</span>
                    <div className="flex-1">
                      <p className="text-sm font-medium">{trip.destination}</p>
                      <p className="text-xs text-gray-600">
                        {format(new Date(trip.start_date), "d 'de' MMM", { locale: pt })}
                      </p>
                    </div>
                    <ArrowRight size={14} className="text-gray-600" />
                  </div>
                ))}
              </div>
            </div>
        </div>
      )}
      </div>
      )}
    </div>
  );
}
