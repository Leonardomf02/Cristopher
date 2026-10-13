import { useState, useEffect, useLayoutEffect, useRef, Fragment } from 'react';
import {
  format,
  startOfMonth, endOfMonth, startOfWeek, endOfWeek,
  eachDayOfInterval, isSameMonth, isSameDay, isToday,
  addMonths, subMonths, addWeeks, subWeeks, addDays, subDays,
  addYears, subYears, startOfYear, endOfYear, eachMonthOfInterval,
  getDay, parseISO,
} from 'date-fns';
import { pt } from 'date-fns/locale';
import { ChevronLeft, ChevronRight, Plus, X, Clock, Check, Tag, Repeat, CalendarDays, CheckSquare, Download, Upload, Loader, Target, Trash2, Edit3, LayoutTemplate, Monitor, Undo2, Play } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import { eventsApi, dayTypesApi, listsApi, habitsApi, templatesApi, screenTimeApi } from '../api';
import { Event, EventCreate, EVENT_CATEGORIES, DayTypeEntry, DAY_TYPE_PRESETS, DEFAULT_DAY_TYPE, RECURRENCE_OPTIONS } from '../types';
import { CATEGORY_STACK_ORDER, categoryFill, fmtHm } from '../screenTime';
import { ComecarTarefa } from '../ComecarTarefa';
import { inkColor } from '../theme';
import { useFlow, linhasDaDescricao } from '../FlowContext';
import { NotaDoBloco } from '../NotaDaSessao';

type ViewMode = 'day' | 'week' | 'month' | 'year';
type Layer = 'normal' | 'categorias';

const CALENDAR_VIEW_KEY = 'calendarViewMode';
const CALENDAR_LAYER_KEY = 'calendarLayer';

// Screen Time por bucket → { chave do bucket: { categoria: segundos } }
type StackedBuckets = Record<string, Record<string, number>>;

function bucketTotal(cats: Record<string, number> | undefined): number {
  if (!cats) return 0;
  return Object.values(cats).reduce((s, v) => s + v, 0);
}

function sortedCategories(cats: Record<string, number>): [string, number][] {
  return Object.entries(cats)
    .filter(([, v]) => v > 0)
    .sort((a, b) => CATEGORY_STACK_ORDER.indexOf(a[0]) - CATEGORY_STACK_ORDER.indexOf(b[0]));
}

type TimelineItem = { key: string; ev: Event; kind: 'fixed' | 'done'; start: number; end: number };

// Atribui colunas a blocos que se sobrepõem no tempo, para ficarem lado a lado.
// Blocos que não colidem ocupam a largura toda (cols=1).
function layoutTimeline(items: TimelineItem[]): (TimelineItem & { col: number; cols: number })[] {
  const sorted = [...items].sort((a, b) => a.start - b.start || a.end - b.end);
  const out: (TimelineItem & { col: number; cols: number })[] = [];
  let cluster: (TimelineItem & { col: number; cols: number })[] = [];
  let clusterEnd = -Infinity;
  const flush = () => {
    const colEnds: number[] = [];
    for (const it of cluster) {
      let c = colEnds.findIndex(end => end <= it.start);
      if (c === -1) { c = colEnds.length; colEnds.push(it.end); } else colEnds[c] = it.end;
      it.col = c;
    }
    for (const it of cluster) { it.cols = colEnds.length; out.push(it); }
    cluster = [];
  };
  for (const it of sorted) {
    if (cluster.length && it.start >= clusterEnd) flush();
    cluster.push({ ...it, col: 0, cols: 1 });
    clusterEnd = Math.max(clusterEnd, it.end);
  }
  flush();
  return out;
}

type CatTip = { x: number; y: number; label: string; parts: [string, number][]; total: number };

// Cartão que segue o rato com a repartição por categoria (o title nativo era tapado
// pelo title do próprio dia e não dizia a categoria).
function CategoryTooltip({ tip }: { tip: CatTip }) {
  const left = Math.min(tip.x + 14, window.innerWidth - 240);
  const top = Math.min(tip.y + 14, window.innerHeight - 40 - tip.parts.length * 20);
  return (
    <div
      className="fixed z-[70] pointer-events-none w-[220px] rounded-xl border border-[#2a2a2a] bg-[#161616] px-3 py-2 shadow-xl"
      style={{ left, top }}
    >
      <div className="flex items-baseline justify-between gap-2 mb-1.5">
        <span className="text-[11px] font-semibold text-gray-200 capitalize truncate">{tip.label}</span>
        <span className="text-[11px] font-bold text-blue-300 shrink-0">{fmtHm(tip.total)}</span>
      </div>
      <div className="space-y-1">
        {(tip.parts.filter(([, s]) => s >= 30).length ? tip.parts.filter(([, s]) => s >= 30) : tip.parts).map(([cat, secs]) => (
          <div key={cat} className="flex items-center gap-1.5 text-[11px]">
            <span className="w-2 h-2 rounded-sm shrink-0" style={{ backgroundColor: categoryFill(cat) }} />
            <span className="flex-1 truncate text-gray-300">{cat}</span>
            <span className="text-gray-500 shrink-0">{fmtHm(secs)}</span>
            <span className="w-8 text-right text-gray-600 shrink-0">{Math.round((secs / tip.total) * 100)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Barra empilhada com o Screen Time do dia, para a camada "Categorias" do mês.
function DayCategories({ cats, label, onHover, onLeave }: {
  cats?: Record<string, number>;
  label: string;
  onHover: (tip: CatTip) => void;
  onLeave: () => void;
}) {
  const total = bucketTotal(cats);
  if (!cats || total <= 0) {
    return <div className="mt-2 text-[10px] text-gray-700">sem registo</div>;
  }
  const parts = sortedCategories(cats);
  const show = (e: React.MouseEvent) =>
    onHover({ x: e.clientX, y: e.clientY, label, parts, total });
  return (
    <div className="mt-1.5 sm:mt-2" onMouseEnter={show} onMouseMove={show} onMouseLeave={onLeave}>
      <div className="text-xs sm:text-sm font-bold text-gray-200">{fmtHm(total)}</div>
      <div className="mt-1 flex h-1.5 sm:h-2 w-full overflow-hidden rounded-full bg-[#0f0f0f]">
        {parts.map(([cat, secs]) => (
          <div key={cat} style={{ width: `${(secs / total) * 100}%`, backgroundColor: categoryFill(cat) }} />
        ))}
      </div>
      <div className="hidden sm:block mt-1 text-[10px] text-gray-500 truncate">
        {(() => {
          const [cat, secs] = parts.reduce((a, b) => (b[1] > a[1] ? b : a));
          return `${cat} ${Math.round((secs / total) * 100)}%`;
        })()}
      </div>
    </div>
  );
}

// Legenda com o peso de cada categoria no período visível.
function CategoryLegend({ buckets, error }: { buckets: StackedBuckets; error: string | null }) {
  const totals: Record<string, number> = {};
  for (const [key, cats] of Object.entries(buckets)) {
    if (key.includes('#')) continue; // buckets horários — evita contar duas vezes
    for (const [cat, secs] of Object.entries(cats)) totals[cat] = (totals[cat] || 0) + secs;
  }
  const parts = sortedCategories(totals);
  const total = parts.reduce((s, [, v]) => s + v, 0);

  if (error) {
    return (
      <p className="mt-3 text-xs text-gray-500">
        Screen Time indisponível: {error}
      </p>
    );
  }
  if (!parts.length) {
    return <p className="mt-3 text-xs text-gray-600">Sem dados de Screen Time neste período.</p>;
  }
  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
      {parts.map(([cat, secs]) => (
        <div key={cat} className="flex items-center gap-1.5 text-[11px] text-gray-400">
          <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: categoryFill(cat) }} />
          {cat}
          <span className="text-gray-600">{fmtHm(secs)} · {Math.round((secs / total) * 100)}%</span>
        </div>
      ))}
    </div>
  );
}

// Célula de uma hora na camada "Categorias": barra a subir com o tempo usado.
function HourCategories({ cats, hour, label, onHover, onLeave, dense }: {
  cats?: Record<string, number>;
  hour: number;
  label: string;
  onHover: (tip: CatTip) => void;
  onLeave: () => void;
  dense?: boolean;
}) {
  const total = bucketTotal(cats);
  const parts = cats ? sortedCategories(cats) : [];
  const fill = Math.min(100, (total / 3600) * 100);
  const hourLabel = `${label} · ${String(hour).padStart(2, '0')}:00`;
  const show = (e: React.MouseEvent) => {
    if (total <= 0) return;
    onHover({ x: e.clientX, y: e.clientY, label: hourLabel, parts, total });
  };
  return (
    <div
      className={`border-t border-[#1a1a1a] p-0.5 ${dense ? '' : 'min-h-[48px]'}`}
      onMouseEnter={show}
      onMouseMove={show}
      onMouseLeave={onLeave}
    >
      <div className={`relative h-full rounded bg-[#111] overflow-hidden flex flex-col justify-end ${dense ? '' : 'min-h-[44px]'}`}>
        {parts.map(([cat, secs]) => (
          <div
            key={cat}
            style={{ height: `${(secs / total) * fill}%`, backgroundColor: categoryFill(cat) }}
          />
        ))}
      </div>
    </div>
  );
}

export default function CalendarPage() {
  const { startTimer, phase } = useFlow();
  const [calParams, setCalParams] = useSearchParams();
  const [currentDate, setCurrentDate] = useState(new Date());
  const [viewMode, setViewMode] = useState<ViewMode>(() => {
    const v = localStorage.getItem(CALENDAR_VIEW_KEY);
    return v === 'day' || v === 'week' || v === 'month' || v === 'year' ? v : 'month';
  });
  const [layer, setLayer] = useState<Layer>(() =>
    localStorage.getItem(CALENDAR_LAYER_KEY) === 'categorias' ? 'categorias' : 'normal'
  );
  const [screenTime, setScreenTime] = useState<StackedBuckets>({});
  const [catTip, setCatTip] = useState<CatTip | null>(null);
  const [screenTimeError, setScreenTimeError] = useState<string | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [pendingItems, setPendingItems] = useState<any[]>([]);
  const [filtroLista, setFiltroLista] = useState('');
  const [novaTarefa, setNovaTarefa] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [selectedDate, setSelectedDate] = useState<Date | null>(null);
  const [editingEvent, setEditingEvent] = useState<Event | null>(null);
  const [notaAberta, setNotaAberta] = useState<Event | null>(null);
  const [dayTypes, setDayTypes] = useState<DayTypeEntry[]>([]);
  const [dayTypeMenu, setDayTypeMenu] = useState<{ date: string; x: number; y: number } | null>(null);

  // Apple Calendar import
  const [showImportModal, setShowImportModal] = useState(false);
  const [appleCalendars, setAppleCalendars] = useState<string[]>([]);
  const [selectedCalendars, setSelectedCalendars] = useState<Set<string>>(new Set());
  const [importLoading, setImportLoading] = useState(false);
  const [importResult, setImportResult] = useState<{ imported: number; skipped: number; errors: number } | null>(null);
  const [exportLoading, setExportLoading] = useState(false);

  // Habits
  const [habits, setHabits] = useState<any[]>([]);
  const [habitCompletions, setHabitCompletions] = useState<any[]>([]);
  const [showHabitPanel, setShowHabitPanel] = useState(false);
  const [showHabitModal, setShowHabitModal] = useState(false);
  const [editingHabit, setEditingHabit] = useState<any>(null);
  const [habitForm, setHabitForm] = useState({ name: '', icon: '✅', color: '#10B981', days: 'daily', fixed_time: '' });
  const [showCheckModal, setShowCheckModal] = useState<{ habitId: number; habitName: string; date: string } | null>(null);
  const [checkTime, setCheckTime] = useState(format(new Date(), 'HH:mm'));

  // Day Templates
  const [dayTemplates, setDayTemplates] = useState<any[]>([]);
  const [showTemplatePanel, setShowTemplatePanel] = useState(false);
  const [showTemplateCreateModal, setShowTemplateCreateModal] = useState(false);
  const [templateForm, setTemplateForm] = useState({ name: '', icon: '📋', color: '#3B82F6', events: [] as { title: string; start_time: string; end_time: string; category: string }[] });
  const [templateEventForm, setTemplateEventForm] = useState({ title: '', start_time: '09:00', end_time: '10:00', category: 'general' });

  // Habit streaks
  const [habitStreaks, setHabitStreaks] = useState<Record<number, { current_streak: number; best_streak: number }>>({});

  const [form, setForm] = useState<EventCreate>({
    title: '',
    description: '',
    date: format(new Date(), 'yyyy-MM-dd'),
    start_time: null,
    end_time: null,
    event_type: 'fixed',
    category: 'general',
    color: '#3B82F6',
    recurrence: 'none',
    recurrence_end: null,
  });

  // "Várias vezes ao dia" (ex: comprimido ao pequeno-almoço/almoço/jantar).
  // Só disponível ao criar. Gera N eventos fixed, um por hora, herdando a repetição.
  const [multiMode, setMultiMode] = useState(false);
  const [multiTimes, setMultiTimes] = useState<string[]>(['09:00', '14:00', '21:00']);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    loadEvents();
  }, [currentDate, viewMode]);

  useEffect(() => {
    localStorage.setItem(CALENDAR_VIEW_KEY, viewMode);
  }, [viewMode]);

  useEffect(() => {
    localStorage.setItem(CALENDAR_LAYER_KEY, layer);
  }, [layer]);

  // Screen Time da vista actual. Pede-se por hora e agrega-se em dias locais — os
  // buckets diários do backend são alinhados a UTC e ficariam desencontrados.
  useEffect(() => {
    if (layer !== 'categorias' || (viewMode !== 'month' && viewMode !== 'week')) return;
    const first = viewMode === 'month'
      ? startOfWeek(startOfMonth(currentDate), { weekStartsOn: 1 })
      : startOfWeek(currentDate, { weekStartsOn: 1 });
    const last = viewMode === 'month'
      ? endOfWeek(endOfMonth(currentDate), { weekStartsOn: 1 })
      : endOfWeek(currentDate, { weekStartsOn: 1 });

    let cancelled = false;
    screenTimeApi.timeseriesStacked({
      start_date: format(subDays(first, 1), 'yyyy-MM-dd'),
      end_date: format(addDays(last, 1), 'yyyy-MM-dd'),
      bucket: 'hour',
    })
      .then(rows => {
        if (cancelled) return;
        const map: StackedBuckets = {};
        for (const row of rows) {
          const d = new Date(row.bucket_start * 1000);
          const dayKey = format(d, 'yyyy-MM-dd');
          const hourKey = `${dayKey}#${d.getHours()}`;
          for (const [cat, secs] of Object.entries(row.categories || {})) {
            if (!secs) continue;
            (map[dayKey] ||= {})[cat] = (map[dayKey][cat] || 0) + secs;
            (map[hourKey] ||= {})[cat] = (map[hourKey][cat] || 0) + secs;
          }
        }
        setScreenTime(map);
        setScreenTimeError(null);
      })
      .catch(e => {
        if (cancelled) return;
        setScreenTime({});
        setScreenTimeError(e?.message || 'Sem dados de Screen Time');
      });
    return () => { cancelled = true; };
  }, [layer, viewMode, currentDate]);

  const showCategories = layer === 'categorias' && (viewMode === 'month' || viewMode === 'week');

  // Dia e semana ocupam o resto do ecrã: mede-se onde a grelha começa e dá-se-lhe
  // a altura que sobra, para a página não crescer nem ganhar scroll vertical.
  const gridRef = useRef<HTMLDivElement>(null);
  const [gridHeight, setGridHeight] = useState<number | null>(null);
  const fitsPage = viewMode === 'day' || viewMode === 'week';

  useLayoutEffect(() => {
    if (!fitsPage) { setGridHeight(null); return; }
    const medir = () => {
      const el = gridRef.current;
      if (!el) return;
      if (window.innerWidth < 1024) { setGridHeight(null); return; }
      // Medido contra o contentor que faz scroll (não a janela), senão a altura
      // dependia de onde a página estava quando se muda de vista.
      const scroller = el.closest('main');
      const espaco = scroller ? scroller.clientHeight : window.innerHeight;
      const topo = scroller
        ? el.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop
        : el.getBoundingClientRect().top;
      // O padding de baixo do contentor da página também conta para o scroll.
      let node: HTMLElement | null = el;
      while (node?.parentElement && node.parentElement !== scroller) node = node.parentElement;
      const folga = node ? parseFloat(getComputedStyle(node).paddingBottom) || 0 : 0;
      setGridHeight(Math.max(360, espaco - topo - folga - 4));
    };
    medir();
    const t = setTimeout(medir, 0);
    window.addEventListener('resize', medir);
    // O cabeçalho muda de altura quando os botões passam para outra linha.
    const ro = new ResizeObserver(medir);
    const header = gridRef.current?.previousElementSibling;
    if (header) ro.observe(header);
    return () => { clearTimeout(t); window.removeEventListener('resize', medir); ro.disconnect(); };
  }, [fitsPage, viewMode, showCategories]);

  // Vista de dia: a altura de cada hora sai da altura da timeline, para as 16 horas
  // caberem exactamente no espaço disponível.
  const timelineRef = useRef<HTMLDivElement>(null);
  const [timelineHeight, setTimelineHeight] = useState<number | null>(null);

  useLayoutEffect(() => {
    if (viewMode !== 'day' || gridHeight === null) { setTimelineHeight(null); return; }
    const el = timelineRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setTimelineHeight(el.clientHeight));
    ro.observe(el);
    setTimelineHeight(el.clientHeight);
    return () => ro.disconnect();
  }, [viewMode, gridHeight]);

  async function loadEvents() {
    let start: string, end: string;
    if (viewMode === 'day') {
      start = end = format(currentDate, 'yyyy-MM-dd');
    } else if (viewMode === 'week') {
      start = format(startOfWeek(currentDate, { weekStartsOn: 1 }), 'yyyy-MM-dd');
      end = format(endOfWeek(currentDate, { weekStartsOn: 1 }), 'yyyy-MM-dd');
    } else if (viewMode === 'year') {
      start = format(startOfYear(currentDate), 'yyyy-MM-dd');
      end = format(endOfYear(currentDate), 'yyyy-MM-dd');
    } else {
      start = format(startOfMonth(currentDate), 'yyyy-MM-dd');
      end = format(endOfMonth(currentDate), 'yyyy-MM-dd');
    }
    const [data, dtData, reminders, habitsData, completionsData, tplData, analyticsData, pendingData] = await Promise.all([
      eventsApi.list({ start_date: start, end_date: end }),
      dayTypesApi.list({ start_date: start, end_date: end }),
      listsApi.getReminders({ start_date: start, end_date: end }),
      habitsApi.list().catch(() => []),
      habitsApi.completionsRange(start, end).catch(() => []),
      templatesApi.list().catch(() => []),
      habitsApi.analytics(30).catch(() => null),
      listsApi.pendingItems().catch(() => []),
    ]);
    const reminderEvents: Event[] = reminders.map((r: any) => ({
      id: r.id,
      title: r.title,
      description: r.notes || '',
      date: r.date,
      start_time: r.start_time || null,
      end_time: null,
      event_type: 'flexible' as const,
      category: 'general',
      color: r.color || '#8B5CF6',
      completed: r.checked,
      recurrence: 'none',
      recurrence_end: null,
      is_reminder: true,
    }));
    setEvents([...data, ...reminderEvents]);
    setPendingItems(pendingData);
    setDayTypes(dtData);
    setHabits(habitsData);
    setHabitCompletions(completionsData);
    setDayTemplates(tplData);
    if (analyticsData?.habits) {
      const streakMap: Record<number, { current_streak: number; best_streak: number }> = {};
      analyticsData.habits.forEach((h: any) => {
        streakMap[h.habit_id] = { current_streak: h.current_streak, best_streak: h.best_streak };
      });
      setHabitStreaks(streakMap);
    }
  }

  function navigate(dir: number) {
    if (viewMode === 'day') setCurrentDate(dir > 0 ? addDays(currentDate, 1) : subDays(currentDate, 1));
    else if (viewMode === 'week') setCurrentDate(dir > 0 ? addWeeks(currentDate, 1) : subWeeks(currentDate, 1));
    else if (viewMode === 'year') setCurrentDate(dir > 0 ? addYears(currentDate, 1) : subYears(currentDate, 1));
    else setCurrentDate(dir > 0 ? addMonths(currentDate, 1) : subMonths(currentDate, 1));
  }

  // ?new=1 (paleta ⌘K) abre já o formulário de novo evento.
  useEffect(() => {
    if (calParams.get('new') !== '1') return;
    setCalParams({}, { replace: true });
    openNewEvent();
  }, [calParams]);

  function openNewEvent(date?: Date) {
    const d = date || currentDate;
    setEditingEvent(null);
    setForm({
      title: '',
      description: '',
      date: format(d, 'yyyy-MM-dd'),
      start_time: null,
      end_time: null,
      event_type: 'fixed',
      category: 'general',
      color: '#3B82F6',
      recurrence: 'none',
      recurrence_end: null,
    });
    setMultiMode(false);
    setMultiTimes(['09:00', '14:00', '21:00']);
    setSelectedDate(d);
    setShowModal(true);
  }

  // Um bloco de flow com nota abre a nota; é para isso que se carrega nele.
  // Editar o bloco continua a um clique, a partir dela.
  function openEvent(event: Event) {
    if (!event.is_reminder && linhasDaDescricao(event.description).length > 0) setNotaAberta(event);
    else openEditEvent(event);
  }

  function openEditEvent(event: Event) {
    if (event.is_reminder) return;
    setEditingEvent(event);
    setForm({
      title: event.title,
      description: event.description,
      date: event.date,
      start_time: event.start_time,
      end_time: event.end_time,
      event_type: event.event_type,
      category: event.category,
      color: event.color,
      recurrence: event.recurrence || 'none',
      recurrence_end: event.recurrence_end || null,
    });
    setMultiMode(false);
    setShowModal(true);
  }

  async function handleSave() {
    if (saving) return;
    if (!form.title.trim()) return;
    setSaving(true);
    try {
      if (!editingEvent && multiMode) {
        const times = [...new Set(multiTimes.filter(Boolean))].sort();
        if (times.length === 0) return;
        await Promise.all(
          times.map(t => eventsApi.create({ ...form, event_type: 'fixed', start_time: t, end_time: null }))
        );
      } else if (editingEvent) {
        await eventsApi.update(editingEvent.id, form);
      } else {
        await eventsApi.create(form);
      }
      setShowModal(false);
      loadEvents();
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (editingEvent) {
      if (editingEvent.is_recurring_instance) {
        // Delete just this instance — add to exceptions
        await eventsApi.excludeDate(editingEvent.parent_id!, editingEvent.date);
      } else {
        await eventsApi.delete(editingEvent.id);
      }
      setShowModal(false);
      loadEvents();
    }
  }

  async function handleDeleteAll() {
    if (editingEvent) {
      const id = editingEvent.parent_id || editingEvent.id;
      await eventsApi.delete(id);
      setShowModal(false);
      loadEvents();
    }
  }

  async function toggleComplete(event: Event) {
    const nowTime = format(new Date(), 'HH:mm');
    if (event.is_reminder) {
      const itemId = Number(String(event.id).replace('reminder-', ''));
      const patch: { checked: boolean; due_time?: string } = { checked: !event.completed };
      // Ao concluir um reminder sem hora, regista a hora do check para aparecer na timeline.
      if (!event.completed && !event.start_time) patch.due_time = nowTime;
      await listsApi.updateItem(itemId, patch);
    } else {
      // Ao concluir, regista a hora do check para a tarefa aparecer na timeline a essa hora.
      await eventsApi.setOccurrenceCompleted(event.id as number, event.date, !event.completed, nowTime);
    }
    loadEvents();
  }

  function getEventsForDate(date: Date) {
    const dateStr = format(date, 'yyyy-MM-dd');
    return events.filter(e => e.date === dateStr);
  }

  // Agenda um reminder sem dia para a data escolhida (aparece depois como tarefa flexível).
  async function addPendingToDay(item: any, date: Date) {
    await listsApi.updateItem(item.id, { due_date: format(date, 'yyyy-MM-dd') });
    loadEvents();
    listsApi.pendingItems().then(setPendingItems).catch(() => {});
  }

  // Uma coisa que ainda não existe em lado nenhum: arranca já, e o bloco entra
  // na timeline quando ele parar.
  function comecaAgora(minutos: number) {
    const nome = novaTarefa.trim();
    if (!nome) return;
    startTimer({ id: 0, name: nome, work_minutes: minutos,
      break_minutes: minutos >= 90 ? 10 : 5, color: '#3B82F6', icon: '⏱️' });
    setNovaTarefa('');
  }

  // Arranca o timer do Flow a partir de um bloco do calendário.
  function arrancarTimer(event: Event, minutos: number) {
    const dur = Math.max(5, Math.round(minutos) || 60);
    startTimer({ id: 0, name: event.title, work_minutes: dur, break_minutes: dur >= 90 ? 10 : 5, color: event.color, icon: '📅' });
  }

  // Desfaz o "+ hoje": o reminder volta para as sugestões sem dia.
  // (o estado do selector de duração vive junto do resto do ecrã do dia)
  async function removeFromDay(event: Event) {
    if (!event.is_reminder) return;
    const itemId = Number(String(event.id).replace('reminder-', ''));
    await listsApi.updateItem(itemId, { due_date: null });
    loadEvents();
    listsApi.pendingItems().then(setPendingItems).catch(() => {});
  }

  function getDayType(date: Date): DayTypeEntry | undefined {
    const dateStr = format(date, 'yyyy-MM-dd');
    return dayTypes.find(d => d.date === dateStr);
  }

  // Dia sem tipo definido conta como Livre (só se mostra, não se grava) — apenas hoje/passado.
  function getEffectiveDayType(date: Date): { type_name: string; color: string; icon: string; isDefault: boolean } | undefined {
    const real = getDayType(date);
    if (real) {
      const preset = DAY_TYPE_PRESETS.find(p => p.name === real.type_name);
      return { type_name: real.type_name, color: real.color, icon: preset?.icon || '📌', isDefault: false };
    }
    if (!isToday(date) && date.getTime() > Date.now()) return undefined;
    return { type_name: DEFAULT_DAY_TYPE.name, color: DEFAULT_DAY_TYPE.color, icon: DEFAULT_DAY_TYPE.icon, isDefault: true };
  }

  async function setDayType(dateStr: string, preset: typeof DAY_TYPE_PRESETS[number]) {
    await dayTypesApi.set({ date: dateStr, type_name: preset.name, color: preset.color });
    setDayTypeMenu(null);
    loadEvents();
  }

  async function clearDayType(dateStr: string) {
    const dt = dayTypes.find(d => d.date === dateStr);
    if (dt) {
      await dayTypesApi.delete(dt.id);
      setDayTypeMenu(null);
      loadEvents();
    }
  }

  function getCompletionsForDate(date: Date) {
    const dateStr = format(date, 'yyyy-MM-dd');
    return habitCompletions.filter(c => c.date === dateStr);
  }

  // ── Habit CRUD ────────────────────────────────────────────────
  async function saveHabit() {
    if (!habitForm.name.trim()) return;
    const payload = {
      ...habitForm,
      fixed_time: habitForm.fixed_time || null,
    };
    if (editingHabit) {
      await habitsApi.update(editingHabit.id, payload);
    } else {
      await habitsApi.create(payload);
    }
    setShowHabitModal(false);
    setEditingHabit(null);
    loadEvents();
  }

  async function deleteHabit(id: number) {
    await habitsApi.delete(id);
    loadEvents();
  }

  async function checkHabit(habitId: number, dateStr: string, time: string) {
    try {
      await habitsApi.complete(habitId, { date: dateStr, completed_at: time });
      loadEvents();
    } catch { /* already completed */ }
  }

  async function uncheckHabit(habitId: number, completionId: number) {
    await habitsApi.deleteCompletion(habitId, completionId);
    loadEvents();
  }

  // ── Day Templates ─────────────────────────────────────────────
  async function applyTemplate(tpl: any, date: Date) {
    const dateStr = format(date, 'yyyy-MM-dd');
    const events = JSON.parse(tpl.events_json || '[]');
    for (const ev of events) {
      const cat = EVENT_CATEGORIES.find(c => c.value === ev.category);
      await eventsApi.create({
        title: ev.title,
        date: dateStr,
        start_time: ev.start_time,
        end_time: ev.end_time,
        event_type: 'fixed',
        category: ev.category || 'general',
        color: cat?.color || '#6B7280',
      });
    }
    setShowTemplatePanel(false);
    loadEvents();
  }

  async function saveTemplate() {
    if (!templateForm.name.trim() || templateForm.events.length === 0) return;
    await templatesApi.create({
      name: templateForm.name,
      icon: templateForm.icon,
      color: templateForm.color,
      events_json: JSON.stringify(templateForm.events),
    });
    setShowTemplateCreateModal(false);
    setTemplateForm({ name: '', icon: '📋', color: '#3B82F6', events: [] });
    loadEvents();
  }

  async function deleteTemplate(id: number) {
    await templatesApi.delete(id);
    loadEvents();
  }

  function isHabitScheduled(habit: any, date: Date): boolean {
    const weekday = date.getDay() === 0 ? 6 : date.getDay() - 1; // Convert JS Sunday=0 to Mon=0..Sun=6
    if (habit.days === 'daily') return true;
    if (habit.days === 'weekdays') return weekday < 5;
    try {
      const allowed = new Set(habit.days.split(',').map((d: string) => parseInt(d.trim())));
      return allowed.has(weekday);
    } catch { return true; }
  }

  const DAYS_OPTIONS = [
    { value: 'daily', label: 'Todos os dias' },
    { value: 'weekdays', label: 'Dias úteis (Seg-Sex)' },
    { value: '0,1,2,3,4,5', label: 'Seg a Sáb' },
    { value: '0,3', label: 'Seg e Qui' },
    { value: '1,4', label: 'Ter e Sex' },
    { value: '0,2,4', label: 'Seg, Qua, Sex' },
  ];

  const HABIT_ICONS = ['🏋️', '🧘', '📚', '💊', '🏃', '🧹', '💧', '🎹', '🖥️', '✍️', '🧑‍🍳', '🎯', '✅'];

  const headerLabel = () => {
    if (viewMode === 'day') return format(currentDate, "EEEE, d 'de' MMMM yyyy", { locale: pt });
    if (viewMode === 'week') {
      const ws = startOfWeek(currentDate, { weekStartsOn: 1 });
      const we = endOfWeek(currentDate, { weekStartsOn: 1 });
      return `${format(ws, 'd MMM', { locale: pt })} — ${format(we, 'd MMM yyyy', { locale: pt })}`;
    }
    if (viewMode === 'year') return format(currentDate, 'yyyy');
    return format(currentDate, "MMMM 'de' yyyy", { locale: pt });
  };

  // ── Month View ──────────────────────────────────────────────
  function renderMonthView() {
    const monthStart = startOfMonth(currentDate);
    const monthEnd = endOfMonth(currentDate);
    const calStart = startOfWeek(monthStart, { weekStartsOn: 1 });
    const calEnd = endOfWeek(monthEnd, { weekStartsOn: 1 });
    const days = eachDayOfInterval({ start: calStart, end: calEnd });

    return (
      <div>
        <div className="grid grid-cols-7 gap-px mb-2">
          {['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'].map(d => (
            <div key={d} className="text-center text-[10px] sm:text-xs text-gray-500 py-1 sm:py-2 font-medium">
              <span className="sm:hidden">{d.charAt(0)}</span>
              <span className="hidden sm:inline">{d}</span>
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-px">
          {days.map(day => {
            const dayEvents = getEventsForDate(day);
            const dayCompletions = getCompletionsForDate(day);
            const eff = getEffectiveDayType(day);
            const isCurrentMonth = isSameMonth(day, currentDate);
            return (
              <div
                key={day.toISOString()}
                onClick={() => { setCurrentDate(day); setViewMode('day'); }}
                title={showCategories ? undefined : 'Abrir este dia'}
                onContextMenu={e => { e.preventDefault(); setDayTypeMenu({ date: format(day, 'yyyy-MM-dd'), x: e.clientX, y: e.clientY }); }}
                className={`group h-[68px] sm:h-auto sm:min-h-[100px] overflow-hidden p-1 sm:p-2 rounded-lg cursor-pointer transition-all border ${
                  isToday(day)
                    ? 'border-blue-500/50 bg-blue-500/5'
                    : isCurrentMonth
                    ? 'border-[#222] bg-[#161616] hover:bg-[#1a1a1a]'
                    : 'border-transparent bg-[#111] opacity-40'
                }`}
                style={eff ? { borderTopColor: eff.color + (eff.isDefault ? '55' : ''), borderTopWidth: eff.isDefault ? '2px' : '3px' } : undefined}
              >
                <div className="flex items-center justify-between gap-1">
                  <span className={`text-xs sm:text-sm font-medium ${
                    isToday(day) ? 'text-blue-400' : isCurrentMonth ? 'text-gray-300' : 'text-gray-600'
                  }`}>
                    {format(day, 'd')}
                  </span>
                  {eff && (
                    <span
                      className="hidden sm:inline text-[10px] px-1.5 py-0.5 rounded-full truncate"
                      style={{ backgroundColor: eff.color + (eff.isDefault ? '11' : '22'), color: inkColor(eff.color) + (eff.isDefault ? 'cc' : '') }}
                      title={eff.isDefault ? 'Livre (por omissão — não definido)' : eff.type_name}
                    >
                      {eff.icon} {eff.type_name}
                    </span>
                  )}
                  <button
                    onClick={e => { e.stopPropagation(); openNewEvent(day); }}
                    title="Novo evento neste dia"
                    className="hidden sm:flex items-center justify-center w-5 h-5 rounded-md shrink-0 ml-auto text-gray-500 hover:text-white hover:bg-white/10 opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <Plus size={12} />
                  </button>
                </div>
                {showCategories ? (
                  <DayCategories
                    cats={screenTime[format(day, 'yyyy-MM-dd')]}
                    label={format(day, "EEE, d 'de' MMM", { locale: pt })}
                    onHover={setCatTip}
                    onLeave={() => setCatTip(null)}
                  />
                ) : (
                <div className="mt-1 space-y-0.5">
                  {dayCompletions.map(comp => (
                    <div
                      key={`hc-${comp.id}`}
                      onClick={(e) => e.stopPropagation()}
                      className="text-[10px] sm:text-xs px-1 sm:px-1.5 py-0.5 rounded truncate flex items-center gap-0.5"
                      style={{ backgroundColor: comp.habit_color + '22', color: inkColor(comp.habit_color) }}
                    >
                      <span className="text-[10px]">{comp.habit_icon}</span>
                      <span className="hidden sm:inline">{comp.completed_at} {comp.habit_name}</span>
                    </div>
                  ))}
                  {dayEvents.slice(0, Math.max(1, 3 - dayCompletions.length)).map(ev => (
                    <div
                      key={`${ev.id}-${day.toISOString()}`}
                      onClick={(e) => { e.stopPropagation(); openEvent(ev); }}
                      className={`text-[10px] sm:text-xs px-1 sm:px-1.5 py-0.5 rounded truncate cursor-pointer flex items-center gap-0.5 ${
                        ev.completed ? 'line-through opacity-50' : ''
                      }`}
                      style={{ backgroundColor: ev.color + '22', color: inkColor(ev.color) }}
                    >
                      {ev.is_reminder && <CheckSquare size={8} className="shrink-0" />}
                      {ev.recurrence && ev.recurrence !== 'none' && <Repeat size={8} className="shrink-0" />}
                      <span className="truncate">
                        <span className="hidden sm:inline">{ev.start_time ? `${ev.start_time} ` : ev.completed && ev.completed_at ? `✓${ev.completed_at} ` : ''}</span>
                        {ev.title}
                      </span>
                    </div>
                  ))}
                  {(dayEvents.length + dayCompletions.length) > 3 && (
                    <div className="text-[10px] sm:text-xs text-gray-500 px-1">+{dayEvents.length + dayCompletions.length - 3}</div>
                  )}
                </div>
                )}
              </div>
            );
          })}
        </div>
        {showCategories && <CategoryLegend buckets={screenTime} error={screenTimeError} />}
      </div>
    );
  }

  // ── Week View ───────────────────────────────────────────────
  function renderWeekView() {
    const ws = startOfWeek(currentDate, { weekStartsOn: 1 });
    const we = endOfWeek(currentDate, { weekStartsOn: 1 });
    const days = eachDayOfInterval({ start: ws, end: we });
    // Na camada de categorias mostram-se as 24h — o Screen Time também acontece de madrugada.
    const hours = showCategories
      ? Array.from({ length: 24 }, (_, i) => i)
      : Array.from({ length: 16 }, (_, i) => i + 7); // 7am to 10pm

    const fill = gridHeight !== null;
    // A ocupar a página: as linhas das horas dividem a altura disponível (com um
    // mínimo, para as 24h da camada de categorias não ficarem ilegíveis).
    const rowMin = showCategories ? 26 : 34;

    return (
      <div className={fill
        ? 'bg-[#161616] border border-[#222] rounded-2xl p-3 h-full flex flex-col overflow-hidden'
        : 'bg-[#161616] border border-[#222] rounded-2xl p-3 overflow-x-auto'}>
        <div className={fill ? 'flex-1 min-h-0 overflow-auto' : 'contents'}>
        <div
          className={`grid gap-px min-w-[720px] ${fill ? 'h-full' : ''}`}
          style={{
            gridTemplateColumns: '3.5rem repeat(7, minmax(0, 1fr))',
            ...(fill ? { gridTemplateRows: `auto repeat(${hours.length}, minmax(${rowMin}px, 1fr))` } : {}),
          }}
        >
          <div className="text-xs text-gray-500 p-2" />
          {days.map(day => (
            <div key={day.toISOString()} className={`text-center p-2 rounded-t-lg ${
              isToday(day) ? 'bg-blue-500/10' : 'bg-[#1a1a1a]'
            }`}>
              <div className="text-xs text-gray-500">{format(day, 'EEE', { locale: pt })}</div>
              <div className={`text-lg font-bold ${isToday(day) ? 'text-blue-400' : 'text-white'}`}>
                {format(day, 'd')}
              </div>
            </div>
          ))}

          {hours.map(hour => (
            <Fragment key={hour}>
              <div className="text-xs text-gray-600 p-2 text-right pr-3">
                {String(hour).padStart(2, '0')}:00
              </div>
              {days.map(day => {
                const dayEvents = getEventsForDate(day);
                const hourStr = String(hour).padStart(2, '0');
                const hourEvents = dayEvents.filter(e => e.start_time?.startsWith(hourStr));
                const flexEvents = hour === 7 ? dayEvents.filter(e => e.event_type === 'flexible') : [];

                if (showCategories) {
                  return (
                    <HourCategories
                      key={`${day.toISOString()}-${hour}`}
                      cats={screenTime[`${format(day, 'yyyy-MM-dd')}#${hour}`]}
                      hour={hour}
                      label={format(day, "EEE, d 'de' MMM", { locale: pt })}
                      onHover={setCatTip}
                      onLeave={() => setCatTip(null)}
                      dense={fill}
                    />
                  );
                }

                return (
                  <div
                    key={`${day.toISOString()}-${hour}`}
                    onClick={() => {
                      const d = new Date(day);
                      setForm(f => ({ ...f, start_time: `${hourStr}:00`, end_time: `${String(hour + 1).padStart(2, '0')}:00` }));
                      openNewEvent(d);
                    }}
                    className={`border-t border-[#1a1a1a] p-0.5 cursor-pointer hover:bg-white/5 ${fill ? 'min-h-0 overflow-y-auto' : 'min-h-[48px]'}`}
                  >
                    {flexEvents.map(ev => (
                      <div
                        key={ev.id}
                        onClick={(e) => { e.stopPropagation(); openEvent(ev); }}
                        className="text-xs px-1 py-0.5 rounded mb-0.5 cursor-pointer"
                        style={{ backgroundColor: ev.color + '22', color: inkColor(ev.color), borderLeft: `2px dashed ${ev.color}` }}
                      >
                        ⏰ {ev.title}
                      </div>
                    ))}
                    {hourEvents.map(ev => (
                      <div
                        key={ev.id}
                        onClick={(e) => { e.stopPropagation(); openEvent(ev); }}
                        className={`text-xs px-1 py-0.5 rounded cursor-pointer ${ev.completed ? 'line-through opacity-50' : ''}`}
                        style={{ backgroundColor: ev.color + '33', color: inkColor(ev.color) }}
                      >
                        {ev.title}
                      </div>
                    ))}
                  </div>
                );
              })}
            </Fragment>
          ))}
        </div>
        </div>
        {showCategories && (
          // A legenda fica fixa por baixo da grelha; sem shrink-0 era esmagada por cima dela.
          <div className={fill ? 'shrink-0' : ''}>
            <CategoryLegend buckets={screenTime} error={screenTimeError} />
          </div>
        )}
      </div>
    );
  }

  // ── Day View (Time Blocking) ─────────────────────────────────
  function renderDayView() {
    const dayEvents = getEventsForDate(currentDate);
    const fixedEvents = dayEvents.filter(e => e.event_type === 'fixed' && e.start_time).sort((a, b) => (a.start_time || '').localeCompare(b.start_time || ''));
    const flexEvents = dayEvents.filter(e => e.event_type === 'flexible');
    // Hora de conclusão: eventos usam completed_at; reminders usam a hora (due_time).
    const doneTime = (e: Event) => (e.is_reminder ? e.start_time : e.completed_at) || null;
    // Tarefas flexíveis concluídas com hora → aparecem também na timeline a essa hora,
    // mas continuam na lista (em "Concluídas") para se poder desfazer o check.
    const flexTimeline = flexEvents.filter(e => e.completed && doneTime(e));
    const flexPending = flexEvents.filter(e => !e.completed);
    const flexDone = flexEvents.filter(e => e.completed);
    const semDia = pendingItems.filter(i => !i.due_date);
    const listasDasSugestoes = Array.from(new Set(semDia.map(i => i.list_name))).sort();
    const undatedPending = filtroLista ? semDia.filter(i => i.list_name === filtroLista) : semDia;
    // A timeline vai das 7h às 22h, mas **estica-se ao que existe**: uma sessão
    // de flow à 01:00 caía fora e simplesmente não aparecia — parecia que não
    // tinha ficado registada.
    const horaDe = (t?: string | null) => (t ? Number(t.split(':')[0]) : null);
    const horasComCoisas = [
      ...fixedEvents.flatMap(e => [horaDe(e.start_time), horaDe(e.end_time)]),
      ...flexTimeline.map(e => horaDe(doneTime(e))),
    ].filter((h): h is number => h !== null);
    const primeiraHora = Math.min(7, ...horasComCoisas);
    const ultimaHora = Math.max(22, ...horasComCoisas);
    const hours = Array.from({ length: ultimaHora - primeiraHora + 1 }, (_, i) => i + primeiraHora);
    const fill = gridHeight !== null;
    const HOUR_HEIGHT = fill && timelineHeight
      ? Math.max(34, timelineHeight / hours.length)
      : 60; // px per hour
    const DAY_START = primeiraHora * 60;
    const toMin = (t: string) => { const [h, m] = t.split(':').map(Number); return h * 60 + m; };

    // Items da timeline: eventos fixos (com duração) + tarefas concluídas (à hora do check,
    // com 30min de altura). Blocos que se sobrepõem no tempo ficam lado a lado em colunas.
    const items: TimelineItem[] = [
      ...fixedEvents.map(ev => {
        const s = toMin(ev.start_time!);
        const e = ev.end_time ? Math.max(toMin(ev.end_time), s + 20) : s + 60;
        return { key: `f-${ev.id}`, ev, kind: 'fixed' as const, start: s, end: e };
      }),
      ...flexTimeline.map(ev => {
        const s = toMin(doneTime(ev)!);
        return { key: `d-${ev.id}`, ev, kind: 'done' as const, start: s, end: s + 30 };
      }),
    ];
    const laidOut = layoutTimeline(items);

    // Linha de tarefa flexível: check reversível e, nos reminders, "tirar do dia".
    const FlexRow = ({ ev }: { ev: Event }) => (
      <div
        onClick={() => openEvent(ev)}
        className={`group flex items-center gap-3 p-3 rounded-xl cursor-pointer ${ev.completed ? 'opacity-60' : ''}`}
        style={{ backgroundColor: ev.color + '11', borderLeft: `3px dashed ${ev.color}` }}
      >
        <button
          onClick={(e) => { e.stopPropagation(); toggleComplete(ev); }}
          title={ev.completed ? 'Desmarcar' : 'Marcar como feita'}
        >
          <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${
            ev.completed ? 'border-green-400 bg-green-400' : 'border-gray-500'
          }`}>
            {ev.completed && <Check size={12} className="text-black" />}
          </div>
        </button>
        <span className={`flex-1 min-w-0 truncate text-sm ${ev.completed ? 'line-through' : ''}`} style={{ color: inkColor(ev.color) }}>
          {ev.title}
        </span>
        {ev.completed && doneTime(ev) && (
          <span className="text-[10px] text-gray-500 shrink-0">✓ {doneTime(ev)}</span>
        )}
        {!ev.completed && (
          <span onClick={e => e.stopPropagation()}>
            <ComecarTarefa nome={ev.title} cor={ev.color} icone="📅" />
          </span>
        )}
        {ev.is_reminder && (
          <button
            onClick={(e) => { e.stopPropagation(); removeFromDay(ev); }}
            title="Tirar deste dia (volta para as sugestões)"
            className="shrink-0 p-1 rounded-lg text-gray-500 hover:text-red-400 hover:bg-white/10 opacity-0 group-hover:opacity-100 transition-opacity"
          >
            <Undo2 size={14} />
          </button>
        )}
      </div>
    );

    return (
      <div className={`grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 ${fill ? 'h-full min-h-0' : ''}`}>
        {/* Timeline with time blocks */}
        <div className={`col-span-2 bg-[#161616] border border-[#222] rounded-2xl p-4 ${fill ? 'flex flex-col min-h-0' : ''}`}>
          <h3 className="text-sm font-medium text-gray-400 mb-4 shrink-0">Timeline — Time Blocking</h3>
          <div ref={timelineRef} className={fill ? 'flex-1 min-h-0 overflow-y-auto' : ''}>
          <div className="relative" style={{ height: `${hours.length * HOUR_HEIGHT}px` }}>
            {/* Hour grid lines */}
            {hours.map((hour, i) => {
              const hourStr = String(hour).padStart(2, '0');
              return (
                <div
                  key={hour}
                  className="absolute left-0 right-0 flex gap-4 cursor-pointer hover:bg-white/5 rounded"
                  style={{ top: `${i * HOUR_HEIGHT}px`, height: `${HOUR_HEIGHT}px` }}
                  onClick={() => {
                    setForm(f => ({ ...f, start_time: `${hourStr}:00`, end_time: `${String(hour + 1).padStart(2, '0')}:00`, event_type: 'fixed' }));
                    openNewEvent(currentDate);
                  }}
                >
                  <span className="text-xs text-gray-600 w-12 pt-1 text-right shrink-0">{hourStr}:00</span>
                  <div className="flex-1 border-t border-[#1a1a1a]" />
                </div>
              );
            })}

            {/* Event blocks — posicionados por tempo, lado a lado quando se sobrepõem */}
            <div className="absolute left-16 right-2 top-0 bottom-0">
              {laidOut.map(it => {
                const ev = it.ev;
                const isDone = it.kind === 'done';
                const top = ((it.start - DAY_START) / 60) * HOUR_HEIGHT;
                const height = Math.max(((it.end - it.start) / 60) * HOUR_HEIGHT - 2, 20);
                const widthPct = 100 / it.cols;
                const leftPct = it.col * widthPct;
                return (
                  <div
                    key={it.key}
                    onClick={(e) => { e.stopPropagation(); if (!ev.is_reminder) openEvent(ev); }}
                    className="absolute rounded-lg px-2 py-1 cursor-pointer transition-all hover:ring-2 hover:ring-white/20 hover:z-20 overflow-hidden"
                    style={{
                      top: `${top}px`, height: `${height}px`,
                      left: `${leftPct}%`, width: `calc(${widthPct}% - 3px)`,
                      backgroundColor: ev.color + (isDone ? '22' : '33'),
                      borderLeft: `3px ${isDone ? 'dashed' : 'solid'} ${ev.color}`,
                      opacity: (isDone || ev.completed) ? 0.7 : 1,
                      zIndex: 10,
                    }}
                  >
                    <div className="flex items-center gap-1.5">
                      {!ev.completed && !isDone && (
                        <button
                          onClick={(e) => { e.stopPropagation(); arrancarTimer(ev, it.end - it.start); }}
                          disabled={phase !== 'idle'}
                          title={phase !== 'idle' ? 'Já tens um timer a correr' : 'Arrancar timer com este bloco'}
                          className="shrink-0 order-last text-gray-500 hover:text-blue-400 disabled:opacity-30"
                        >
                          <Play size={11} />
                        </button>
                      )}
                      <button onClick={(e) => { e.stopPropagation(); toggleComplete(ev); }} className="shrink-0">
                        <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                          ev.completed ? 'border-green-400 bg-green-400' : 'border-gray-500'
                        }`}>
                          {ev.completed && <Check size={10} className="text-black" />}
                        </div>
                      </button>
                      <span className={`text-xs font-medium truncate ${ev.completed ? 'line-through' : ''}`} style={{ color: inkColor(ev.color) }}>
                        {ev.title}
                      </span>
                      {it.cols === 1 && (
                        <span className="text-[10px] text-gray-500 shrink-0 ml-auto">
                          {isDone ? `✓ ${doneTime(ev)}` : `${ev.start_time}${ev.end_time ? `-${ev.end_time}` : ''}`}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
          </div>
        </div>

        {/* Flexible tasks + suggestions. A coluna tem a altura da timeline ao
            lado — não é ela que manda no tamanho da página. Os dois primeiros
            cartões ficam pelo conteúdo e as sugestões esticam e rolam lá dentro,
            que é o único sítio que pode crescer sem fim. */}
        <div className={`flex flex-col gap-4 ${fill ? 'h-full min-h-0' : 'space-y-4'}`}>
          <div className={`bg-[#161616] border border-[#222] rounded-2xl p-4 shrink-0 ${
            fill ? 'max-h-[45%] flex flex-col min-h-0' : ''}`}>
            <h3 className="text-sm font-medium text-gray-400 mb-4 flex items-center gap-2 shrink-0">
              <Clock size={14} /> Flexíveis (qualquer hora)
            </h3>
            <div className={`space-y-2 ${fill ? 'min-h-0 overflow-y-auto pr-1' : 'max-h-72 overflow-y-auto pr-1'}`}>
              {flexPending.length === 0 && flexDone.length === 0 && (
                <p className="text-xs text-gray-600">Sem tarefas flexíveis</p>
              )}
              {flexPending.map(ev => <FlexRow key={ev.id} ev={ev} />)}
              {flexDone.length > 0 && (
                <>
                  <p className="text-[10px] uppercase tracking-wider text-gray-600 pt-2">
                    Concluídas ({flexDone.length})
                  </p>
                  {flexDone.map(ev => <FlexRow key={ev.id} ev={ev} />)}
                </>
              )}
            </div>
          </div>

          {/* Começar já uma coisa que ainda não está em lado nenhum: escreve-se
              o nome, escolhe-se o tempo (ou "sem fim") e o cronómetro arranca. O
              bloco entra na timeline quando ele parar, com o tempo real. */}
          <div className="bg-[#161616] border border-[#222] rounded-2xl p-4 shrink-0">
            <h3 className="text-sm font-medium text-gray-400 flex items-center gap-2 mb-3">
              <Play size={14} /> Começar agora
            </h3>
            <input
              value={novaTarefa}
              onChange={e => setNovaTarefa(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && novaTarefa.trim()) comecaAgora(25); }}
              placeholder="No que vais trabalhar?"
              className="w-full bg-[#1a1a1a] border border-[#222] rounded-xl px-3 py-2 text-sm
                placeholder-gray-600 focus:outline-none focus:border-blue-500/50"
            />
            <div className="flex flex-wrap items-center gap-1.5 mt-2">
              {[25, 50, 90, 120].map(min => (
                <button key={min} onClick={() => comecaAgora(min)}
                  disabled={!novaTarefa.trim() || phase !== 'idle'}
                  className="text-[11px] px-2.5 py-1 rounded-lg bg-white/[0.06] text-gray-300
                    hover:bg-white/[0.12] disabled:opacity-30">
                  {min >= 60 ? `${min / 60}h`.replace('.5h', 'h30') : `${min}min`}
                </button>
              ))}
              <button onClick={() => comecaAgora(0)}
                disabled={!novaTarefa.trim() || phase !== 'idle'}
                title="Conta para cima até carregares em parar"
                className="text-[11px] px-2.5 py-1 rounded-lg bg-emerald-500/15 text-emerald-300
                  hover:bg-emerald-500/25 disabled:opacity-30">
                sem fim
              </button>
              {phase !== 'idle' && (
                <span className="text-[10px] text-gray-600">já tens um a correr</span>
              )}
            </div>
          </div>

          {/* Sugestões — tarefas por fazer sem dia atribuído */}
          <div className={`bg-[#161616] border border-[#222] rounded-2xl p-4 ${
            fill ? 'flex-1 min-h-0 flex flex-col' : ''}`}>
            <div className="flex items-center justify-between mb-4 shrink-0">
              <h3 className="text-sm font-medium text-gray-400 flex items-center gap-2">
                <CheckSquare size={14} /> Sugestões — por fazer
              </h3>
              {/* Uma lista de cada vez, ou todas. */}
              {listasDasSugestoes.length > 1 && (
                <select value={filtroLista} onChange={e => setFiltroLista(e.target.value)}
                  className="bg-transparent text-[11px] text-gray-500 hover:text-gray-300 focus:outline-none cursor-pointer">
                  <option value="">todas as listas</option>
                  {listasDasSugestoes.map(l => <option key={l} value={l}>{l}</option>)}
                </select>
              )}
            </div>
            <div className={`space-y-2 ${fill ? 'flex-1 min-h-0 overflow-y-auto pr-1' : 'max-h-96 overflow-y-auto pr-1'}`}>
              {undatedPending.length === 0 ? (
                <p className="text-xs text-gray-600">Nada por fazer sem dia 🎉</p>
              ) : (
                undatedPending.map(item => (
                  <div
                    key={item.id}
                    className="group rounded-xl bg-[#1a1a1a] border border-[#222] hover:bg-[#222] transition-colors"
                  >
                    <div className="flex items-center gap-2.5 p-3">
                      <span className="text-sm shrink-0">{item.list_icon || '📝'}</span>
                      <span className="text-sm flex-1 truncate" title={item.text}>{item.text}</span>
                      <span className="text-[10px] text-gray-600 shrink-0 hidden sm:inline">{item.list_name}</span>
                      {/* Começar a trabalhar nisto agora, sem ter de o agendar
                          primeiro. Começar não é fazer: a tarefa fica na lista
                          até ele a carimbar. */}
                      <ComecarTarefa nome={item.text} cor={item.list_color || '#3B82F6'}
                        icone={item.list_icon || '📝'} />
                      <button
                        onClick={() => addPendingToDay(item, currentDate)}
                        title="Agendar para este dia"
                        className="text-[10px] px-2 py-1 rounded-lg bg-blue-500/15 text-blue-300 hover:bg-blue-500/25 shrink-0 whitespace-nowrap"
                      >
                        + hoje
                      </button>
                    </div>

                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Year View ───────────────────────────────────────────────
  function renderYearView() {
    const months = eachMonthOfInterval({ start: startOfYear(currentDate), end: endOfYear(currentDate) });

    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {months.map(month => {
          const mStart = startOfMonth(month);
          const mEnd = endOfMonth(month);
          const calStart = startOfWeek(mStart, { weekStartsOn: 1 });
          const calEnd = endOfWeek(mEnd, { weekStartsOn: 1 });
          const days = eachDayOfInterval({ start: calStart, end: calEnd });
          const monthEvents = events.filter(e => {
            const d = new Date(e.date);
            return d >= mStart && d <= mEnd;
          });

          return (
            <div
              key={month.toISOString()}
              className="bg-[#161616] rounded-xl p-4 cursor-pointer hover:bg-[#1a1a1a] transition-all"
              onClick={() => { setCurrentDate(month); setViewMode('month'); }}
            >
              <h3 className="text-sm font-medium text-gray-300 mb-2 capitalize">
                {format(month, 'MMMM', { locale: pt })}
              </h3>
              <div className="grid grid-cols-3 sm:grid-cols-5 lg:grid-cols-7 gap-0.5 text-center">
                {['S', 'T', 'Q', 'Q', 'S', 'S', 'D'].map((d, i) => (
                  <div key={i} className="text-[9px] text-gray-600">{d}</div>
                ))}
                {days.map(day => {
                  const hasEvents = getEventsForDate(day).length > 0;
                  return (
                    <div key={day.toISOString()} className={`text-[10px] w-5 h-5 flex items-center justify-center rounded-full ${
                      !isSameMonth(day, month) ? 'opacity-20' :
                      isToday(day) ? 'bg-blue-500 text-white' :
                      hasEvents ? 'bg-purple-500/30 text-purple-300' :
                      'text-gray-400'
                    }`}>
                      {format(day, 'd')}
                    </div>
                  );
                })}
              </div>
              {monthEvents.length > 0 && (
                <div className="mt-2 text-xs text-gray-500">{monthEvents.length} evento{monthEvents.length !== 1 ? 's' : ''}</div>
              )}
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6 lg:mb-8">
        <div className="min-w-0">
          <h2 className="text-2xl font-bold capitalize">{headerLabel()}</h2>
        </div>
        <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
          {/* View mode tabs */}
          <div className="flex bg-[#161616] rounded-xl p-1">
            {(['day', 'week', 'month', 'year'] as ViewMode[]).map(mode => (
              <button
                key={mode}
                onClick={() => setViewMode(mode)}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all capitalize ${
                  viewMode === mode ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'
                }`}
              >
                {{ day: 'Dia', week: 'Semana', month: 'Mês', year: 'Ano' }[mode]}
              </button>
            ))}
          </div>

          {/* Camada: eventos normais ou Screen Time por categorias */}
          {(viewMode === 'month' || viewMode === 'week') && (
            <div className="flex bg-[#161616] rounded-xl p-1">
              {(['normal', 'categorias'] as Layer[]).map(l => (
                <button
                  key={l}
                  onClick={() => setLayer(l)}
                  title={l === 'normal' ? 'Eventos e hábitos' : 'Screen Time por categorias'}
                  className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${
                    layer === l ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'
                  }`}
                >
                  {l === 'normal' ? 'Normal' : 'Categorias'}
                </button>
              ))}
            </div>
          )}

          <div className="flex items-center gap-1">
            <button onClick={() => navigate(-1)} className="p-2 hover:bg-white/10 rounded-lg">
              <ChevronLeft size={18} />
            </button>
            <button
              onClick={() => setCurrentDate(new Date())}
              className="px-3 py-1.5 text-xs bg-white/10 rounded-lg hover:bg-white/20"
            >
              Hoje
            </button>
            <button onClick={() => navigate(1)} className="p-2 hover:bg-white/10 rounded-lg">
              <ChevronRight size={18} />
            </button>
          </div>

          {/* Action buttons group */}
          <div className="flex items-center bg-[#161616] rounded-xl p-1 gap-0.5">
            <button
              onClick={async () => {
                setShowImportModal(true);
                setImportResult(null);
                try {
                  const data = await eventsApi.appleCalendars();
                  setAppleCalendars(data.calendars);
                  const defaults = new Set(data.calendars.filter(c =>
                    !['Siri Suggestions', 'Birthdays', 'Feriados em Portugal', 'Feriados', 'Scheduled Reminders', 'Cristopher Reminders'].includes(c)
                  ));
                  setSelectedCalendars(defaults);
                } catch { setAppleCalendars([]); }
              }}
              className="p-2 text-gray-500 hover:text-blue-400 hover:bg-white/10 rounded-lg transition-all"
              title="Importar Apple Calendar"
            >
              <Download size={16} />
            </button>

            <button
              onClick={async () => {
                setExportLoading(true);
                try {
                  const result = await eventsApi.exportAppleCalendar();
                  alert(`Exportados: ${result.exported}, Ignorados: ${result.skipped}, Erros: ${result.errors}`);
                } catch { alert('Erro ao exportar para Apple Calendar'); }
                setExportLoading(false);
              }}
              disabled={exportLoading}
              className="p-2 text-gray-500 hover:text-purple-400 hover:bg-white/10 rounded-lg transition-all disabled:opacity-50"
              title="Exportar → Apple Calendar"
            >
              {exportLoading ? <Loader size={16} className="animate-spin" /> : <Upload size={16} />}
            </button>

            <div className="w-px h-5 bg-[#333] mx-0.5" />

            <button
              onClick={() => setShowHabitPanel(!showHabitPanel)}
              className={`p-2 rounded-lg transition-all ${
                showHabitPanel ? 'text-green-400 bg-green-600/20' : 'text-gray-500 hover:text-green-400 hover:bg-white/10'
              }`}
              title="Hábitos"
            >
              <Target size={16} />
            </button>

            <button
              onClick={() => setShowTemplatePanel(!showTemplatePanel)}
              className={`p-2 rounded-lg transition-all ${
                showTemplatePanel ? 'text-blue-400 bg-blue-600/20' : 'text-gray-500 hover:text-blue-400 hover:bg-white/10'
              }`}
              title="Templates de Dia"
            >
              <LayoutTemplate size={16} />
            </button>

            <Link
              to="/calendar/apps"
              className="p-2 text-gray-500 hover:text-cyan-400 hover:bg-white/10 rounded-lg transition-all"
              title="Uso de aplicações"
            >
              <Monitor size={16} />
            </Link>
          </div>

          <button
            onClick={() => openNewEvent()}
            className="flex items-center gap-2 px-3 sm:px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-xl text-sm font-medium transition-all shadow-lg shadow-blue-600/20"
          >
            <Plus size={16} /> <span className="hidden sm:inline">Novo Evento</span><span className="sm:hidden">Novo</span>
          </button>
        </div>
      </div>

      {/* Calendar Grid */}
      <div
        ref={gridRef}
        className={gridHeight ? 'min-h-0 overflow-hidden' : ''}
        style={gridHeight ? { height: `${gridHeight}px` } : undefined}
      >
        {viewMode === 'month' && renderMonthView()}
        {viewMode === 'week' && renderWeekView()}
        {viewMode === 'day' && renderDayView()}
        {viewMode === 'year' && renderYearView()}
      </div>

      {catTip && showCategories && <CategoryTooltip tip={catTip} />}

      {/* Day Type Context Menu */}
      {dayTypeMenu && (
        <div className="fixed inset-0 z-40" onClick={() => setDayTypeMenu(null)}>
          <div className="absolute bg-[#1a1a1a] border border-[#333] rounded-xl p-2 shadow-xl w-48"
            style={{ left: dayTypeMenu.x, top: dayTypeMenu.y }}
            onClick={e => e.stopPropagation()}>
            <p className="text-xs text-gray-500 px-2 py-1 mb-1">Tipo de Dia</p>
            {DAY_TYPE_PRESETS.map(preset => {
              const isActive = dayTypes.find(d => d.date === dayTypeMenu.date)?.type_name === preset.name;
              return (
                <button key={preset.name}
                  onClick={() => isActive ? clearDayType(dayTypeMenu.date) : setDayType(dayTypeMenu.date, preset)}
                  className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-left transition-all ${
                    isActive ? 'bg-white/10 text-white' : 'text-gray-400 hover:bg-white/5 hover:text-white'
                  }`}>
                  <span>{preset.icon}</span>
                  <span>{preset.name}</span>
                  <div className="ml-auto w-3 h-3 rounded-full" style={{ backgroundColor: preset.color }} />
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Event Modal */}
      {notaAberta && (
        <NotaDoBloco
          titulo={notaAberta.title}
          quando={`${format(parseISO(notaAberta.date), "EEEE, d 'de' MMMM", { locale: pt })}${
            notaAberta.start_time ? ` · ${notaAberta.start_time}${notaAberta.end_time ? `–${notaAberta.end_time}` : ''}` : ''}`}
          linhas={linhasDaDescricao(notaAberta.description)}
          cor={notaAberta.color}
          onEditar={() => { const ev = notaAberta; setNotaAberta(null); openEditEvent(ev); }}
          onFechar={() => setNotaAberta(null)}
        />
      )}

      {showModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowModal(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 max-w-[90vw] w-[480px] border border-[#333] max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-bold">{editingEvent ? 'Editar Evento' : 'Novo Evento'}</h3>
              <button onClick={() => setShowModal(false)} className="text-gray-500 hover:text-white">
                <X size={20} />
              </button>
            </div>

            <div className="space-y-4">
              <input
                type="text"
                placeholder="Título do evento..."
                value={form.title}
                onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-500"
                autoFocus
              />

              <textarea
                placeholder="Descrição (opcional)"
                value={form.description}
                onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-500 resize-none"
                rows={2}
              />

              <input
                type="date"
                value={form.date}
                onChange={e => setForm(f => ({ ...f, date: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-500"
              />

              {/* Event type toggle */}
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => { setMultiMode(false); setForm(f => ({ ...f, event_type: 'fixed' })); }}
                  className={`flex-1 min-w-[100px] py-2 rounded-xl text-xs sm:text-sm font-medium transition-all ${
                    !multiMode && form.event_type === 'fixed' ? 'bg-blue-600 text-white' : 'bg-[#222] text-gray-400'
                  }`}
                >
                  ⏰ Hora Fixa
                </button>
                <button
                  onClick={() => { setMultiMode(false); setForm(f => ({ ...f, event_type: 'flexible', start_time: null, end_time: null })); }}
                  className={`flex-1 min-w-[100px] py-2 rounded-xl text-xs sm:text-sm font-medium transition-all ${
                    !multiMode && form.event_type === 'flexible' ? 'bg-purple-600 text-white' : 'bg-[#222] text-gray-400'
                  }`}
                >
                  🔄 Flexível
                </button>
                {!editingEvent && (
                  <button
                    onClick={() => { setMultiMode(true); setForm(f => ({ ...f, event_type: 'fixed' })); }}
                    className={`flex-1 min-w-[100px] py-2 rounded-xl text-xs sm:text-sm font-medium transition-all ${
                      multiMode ? 'bg-emerald-600 text-white' : 'bg-[#222] text-gray-400'
                    }`}
                  >
                    🕐 Várias/dia
                  </button>
                )}
              </div>

              {!multiMode && form.event_type === 'fixed' && (
                <div className="flex gap-3">
                  <div className="flex-1">
                    <label className="text-xs text-gray-500 block mb-1">Início</label>
                    <input
                      type="time"
                      value={form.start_time || ''}
                      onChange={e => setForm(f => ({ ...f, start_time: e.target.value }))}
                      className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div className="flex-1">
                    <label className="text-xs text-gray-500 block mb-1">Fim</label>
                    <input
                      type="time"
                      value={form.end_time || ''}
                      onChange={e => setForm(f => ({ ...f, end_time: e.target.value }))}
                      className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm focus:outline-none focus:border-blue-500"
                    />
                  </div>
                </div>
              )}

              {multiMode && (
                <div className="space-y-2 bg-[#181818] border border-[#2a2a2a] rounded-xl p-3">
                  <label className="text-xs text-gray-500 block">
                    Horários · {multiTimes.length}x ao dia
                  </label>
                  {multiTimes.map((t, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <span className="text-xs text-gray-500 w-4 text-right">{i + 1}.</span>
                      <input
                        type="time"
                        value={t}
                        onChange={e => setMultiTimes(ts => ts.map((x, j) => j === i ? e.target.value : x))}
                        className="flex-1 bg-[#222] border border-[#333] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                      />
                      {multiTimes.length > 1 && (
                        <button
                          onClick={() => setMultiTimes(ts => ts.filter((_, j) => j !== i))}
                          className="text-gray-500 hover:text-red-400 p-1"
                        >
                          <X size={14} />
                        </button>
                      )}
                    </div>
                  ))}
                  <button
                    onClick={() => setMultiTimes(ts => [...ts, '12:00'])}
                    className="text-xs text-emerald-400 hover:text-emerald-300 flex items-center gap-1 mt-1"
                  >
                    <Plus size={12} /> Adicionar hora
                  </button>
                  <p className="text-[10px] text-gray-600">Cria {multiTimes.length} eventos neste dia, um por hora. A repetição abaixo aplica-se a cada um.</p>
                </div>
              )}

              {/* Category */}
              <div>
                <label className="text-xs text-gray-500 block mb-2">Categoria</label>
                <div className="flex flex-wrap gap-2">
                  {EVENT_CATEGORIES.map(cat => (
                    <button
                      key={cat.value}
                      onClick={() => setForm(f => ({ ...f, category: cat.value, color: cat.color }))}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                        form.category === cat.value ? 'ring-2 ring-offset-2 ring-offset-[#1a1a1a]' : 'opacity-60 hover:opacity-100'
                      }`}
                      style={{ backgroundColor: cat.color + '22', color: cat.color, ['--tw-ring-color' as string]: cat.color }}
                    >
                      {cat.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Recurrence */}
              <div>
                <label className="text-xs text-gray-500 block mb-2 flex items-center gap-1">
                  <Repeat size={12} /> Repetição
                </label>
                <select
                  value={form.recurrence || 'none'}
                  onChange={e => setForm(f => ({ ...f, recurrence: e.target.value }))}
                  className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-blue-500"
                >
                  {RECURRENCE_OPTIONS.map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>

              {form.recurrence && form.recurrence !== 'none' && (
                <div>
                  <label className="text-xs text-gray-500 block mb-1 flex items-center gap-1">
                    <CalendarDays size={12} /> Repetir até (opcional)
                  </label>
                  <input
                    type="date"
                    value={form.recurrence_end || ''}
                    onChange={e => setForm(f => ({ ...f, recurrence_end: e.target.value || null }))}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-blue-500"
                  />
                  <p className="text-[10px] text-gray-600 mt-1">Deixa vazio para repetir para sempre</p>
                </div>
              )}
            </div>

            <div className="flex gap-3 mt-6">
              {editingEvent && (
                <div className="flex gap-2">
                  {editingEvent.is_recurring_instance ? (
                    <>
                      <button
                        onClick={handleDelete}
                        className="px-3 py-2.5 bg-red-600/20 text-red-400 hover:bg-red-600/30 rounded-xl text-xs font-medium"
                      >
                        Apagar este
                      </button>
                      <button
                        onClick={handleDeleteAll}
                        className="px-3 py-2.5 bg-red-600/20 text-red-400 hover:bg-red-600/30 rounded-xl text-xs font-medium"
                      >
                        Apagar todos
                      </button>
                    </>
                  ) : editingEvent.recurrence && editingEvent.recurrence !== 'none' ? (
                    <button
                      onClick={handleDeleteAll}
                      className="px-3 py-2.5 bg-red-600/20 text-red-400 hover:bg-red-600/30 rounded-xl text-xs font-medium"
                    >
                      Apagar série
                    </button>
                  ) : (
                    <button
                      onClick={handleDelete}
                      className="px-4 py-2.5 bg-red-600/20 text-red-400 hover:bg-red-600/30 rounded-xl text-sm font-medium"
                    >
                      Apagar
                    </button>
                  )}
                </div>
              )}
              <div className="flex-1" />
              <button onClick={() => setShowModal(false)}
                className="px-4 py-2.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm">
                Cancelar
              </button>
              <button onClick={handleSave} disabled={saving}
                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-xl text-sm font-medium">
                {saving ? 'A guardar…' : editingEvent ? 'Guardar' : 'Criar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Apple Calendar Import Modal */}
      {showImportModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowImportModal(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 max-w-[90vw] w-[420px] border border-[#333] max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold flex items-center gap-2">
                <Download size={20} className="text-blue-400" />
                Importar Apple Calendar
              </h3>
              <button onClick={() => setShowImportModal(false)} className="text-gray-500 hover:text-white"><X size={20} /></button>
            </div>

            {importResult ? (
              <div className="space-y-3">
                <div className="bg-green-500/10 border border-green-500/20 rounded-xl p-4">
                  <p className="text-sm font-medium text-green-400 mb-2">Importação concluída!</p>
                  <div className="space-y-1 text-xs text-gray-300">
                    <p>✅ <span className="font-mono">{importResult.imported}</span> eventos importados</p>
                    <p>⏭️ <span className="font-mono">{importResult.skipped}</span> duplicados ignorados</p>
                    {importResult.errors > 0 && <p>⚠️ <span className="font-mono">{importResult.errors}</span> erros</p>}
                  </div>
                </div>
                <button
                  onClick={() => { setShowImportModal(false); loadEvents(); }}
                  className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-xl transition-colors"
                >
                  Fechar
                </button>
              </div>
            ) : (
              <div className="space-y-4">
                <div>
                  <p className="text-xs text-gray-500 mb-2">Seleciona os calendários a importar:</p>
                  <div className="space-y-1.5 max-h-[250px] overflow-y-auto">
                    {appleCalendars.length === 0 ? (
                      <p className="text-sm text-gray-500 text-center py-4">A carregar calendários...</p>
                    ) : appleCalendars.map(cal => (
                      <label key={cal} className="flex items-center gap-3 p-2 rounded-lg hover:bg-white/5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={selectedCalendars.has(cal)}
                          onChange={e => {
                            const next = new Set(selectedCalendars);
                            if (e.target.checked) next.add(cal); else next.delete(cal);
                            setSelectedCalendars(next);
                          }}
                          className="rounded border-gray-600 bg-[#222] text-blue-600 focus:ring-blue-500"
                        />
                        <span className="text-sm text-white">{cal}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    disabled={selectedCalendars.size === 0 || importLoading}
                    onClick={async () => {
                      setImportLoading(true);
                      try {
                        const result = await eventsApi.importAppleCalendar({
                          calendars: [...selectedCalendars],
                          days_back: 30,
                          days_forward: 90,
                        });
                        setImportResult(result);
                      } catch (e: any) {
                        setImportResult({ imported: 0, skipped: 0, errors: 1 });
                      } finally {
                        setImportLoading(false);
                      }
                    }}
                    className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-medium transition-colors ${
                      selectedCalendars.size > 0 && !importLoading
                        ? 'bg-blue-600 hover:bg-blue-500 text-white'
                        : 'bg-[#333] text-gray-500 cursor-not-allowed'
                    }`}
                  >
                    {importLoading ? <><Loader size={14} className="animate-spin" /> A importar...</> : <>Importar ({selectedCalendars.size})</>}
                  </button>
                  <button onClick={() => setShowImportModal(false)} className="px-4 py-2.5 bg-[#222] hover:bg-[#333] text-gray-400 text-sm rounded-xl transition-colors">
                    Cancelar
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Habits Panel (slide-over) */}
      {showHabitPanel && (
        <div className="fixed right-0 top-0 bottom-0 w-96 bg-[#161616] border-l border-[#222] shadow-2xl z-40 flex flex-col">
          <div className="flex items-center justify-between p-4 border-b border-[#222]">
            <h3 className="text-sm font-bold flex items-center gap-2">
              <Target size={16} className="text-green-400" /> Hábitos Diários
            </h3>
            <div className="flex items-center gap-2">
              <button
                onClick={() => { setEditingHabit(null); setHabitForm({ name: '', icon: '✅', color: '#10B981', days: 'daily', fixed_time: '' }); setShowHabitModal(true); }}
                className="p-1.5 bg-green-600/20 text-green-400 hover:bg-green-600/30 rounded-lg"
              >
                <Plus size={14} />
              </button>
              <button onClick={() => setShowHabitPanel(false)} className="p-1.5 hover:bg-white/10 rounded-lg">
                <X size={14} />
              </button>
            </div>
          </div>

          {/* Today's habits */}
          <div className="p-4 border-b border-[#222]">
            <p className="text-xs text-gray-500 font-bold uppercase tracking-wider mb-3">Hoje — {format(new Date(), "d 'de' MMMM", { locale: pt })}</p>
            <div className="space-y-2">
              {habits.filter(h => isHabitScheduled(h, new Date())).length === 0 ? (
                <p className="text-xs text-gray-600 text-center py-4">Nenhum hábito para hoje</p>
              ) : (
                habits.filter(h => isHabitScheduled(h, new Date())).map(h => {
                  const todayStr = format(new Date(), 'yyyy-MM-dd');
                  const completion = habitCompletions.find(c => c.habit_id === h.id && c.date === todayStr);
                  return (
                    <div key={h.id} className="flex items-center gap-3 p-3 rounded-xl bg-[#111] border border-[#1a1a1a]">
                      <button
                        onClick={() => {
                          if (completion) {
                            uncheckHabit(h.id, completion.id);
                          } else {
                            setCheckTime(format(new Date(), 'HH:mm'));
                            setShowCheckModal({ habitId: h.id, habitName: h.name, date: todayStr });
                          }
                        }}
                        className={`w-7 h-7 rounded-full border-2 flex items-center justify-center shrink-0 transition-all ${
                          completion ? 'border-green-400 bg-green-400' : 'border-gray-600 hover:border-green-400'
                        }`}
                      >
                        {completion && <Check size={14} className="text-black" />}
                      </button>
                      <span className="text-lg">{h.icon}</span>
                      <div className="flex-1 min-w-0">
                        <p className={`text-sm font-medium truncate ${completion ? 'line-through text-gray-600' : ''}`}>{h.name}</p>
                        <p className="text-[10px] text-gray-600">
                          {h.fixed_time ? `⏰ ${h.fixed_time}` : '🔄 Qualquer hora'}
                          {completion && ` • Feito às ${completion.completed_at}`}
                        </p>
                      </div>
                      {habitStreaks[h.id]?.current_streak > 0 && (
                        <span className="text-xs font-bold text-orange-400 shrink-0" title={`Melhor: ${habitStreaks[h.id]?.best_streak || 0} dias`}>
                          🔥{habitStreaks[h.id].current_streak}
                        </span>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* All habits list */}
          <div className="flex-1 overflow-y-auto p-4">
            <p className="text-xs text-gray-500 font-bold uppercase tracking-wider mb-3">Todos os Hábitos</p>
            <div className="space-y-2">
              {habits.length === 0 ? (
                <div className="text-center py-8">
                  <p className="text-gray-600 text-sm">Nenhum hábito criado</p>
                  <p className="text-xs text-gray-700 mt-1">Clica no + para adicionar</p>
                </div>
              ) : (
                habits.map(h => {
                  const daysLabel = h.days === 'daily' ? 'Todos os dias'
                    : h.days === 'weekdays' ? 'Seg-Sex'
                    : h.days.split(',').map((d: string) => ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'][parseInt(d)] || d).join(', ');
                  return (
                    <div key={h.id} className="flex items-center gap-3 p-3 rounded-xl border border-[#1a1a1a] hover:bg-white/5 group">
                      <span className="text-lg">{h.icon}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium">{h.name}</p>
                        <p className="text-[10px] text-gray-600">
                          {daysLabel} • {h.fixed_time ? `⏰ ${h.fixed_time}` : '🔄 Flexível'}
                          {habitStreaks[h.id]?.current_streak > 0 && ` • 🔥${habitStreaks[h.id].current_streak}d`}
                          {habitStreaks[h.id]?.best_streak > 0 && ` • 🎯${habitStreaks[h.id].best_streak}d`}
                        </p>
                      </div>
                      <div className="w-3 h-3 rounded-full" style={{ backgroundColor: h.color }} />
                      <div className="opacity-0 group-hover:opacity-100 flex gap-1 transition-opacity">
                        <button onClick={() => {
                          setEditingHabit(h);
                          setHabitForm({ name: h.name, icon: h.icon, color: h.color, days: h.days, fixed_time: h.fixed_time || '' });
                          setShowHabitModal(true);
                        }} className="p-1 hover:bg-white/10 rounded"><Edit3 size={12} /></button>
                        <button onClick={() => deleteHabit(h.id)} className="p-1 hover:bg-red-500/20 text-red-400 rounded"><Trash2 size={12} /></button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}

      {/* Habit Create/Edit Modal */}
      {showHabitModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowHabitModal(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 max-w-[90vw] w-[420px] border border-[#333]" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-bold mb-4">{editingHabit ? 'Editar Hábito' : 'Novo Hábito'}</h3>

            <div className="space-y-4">
              <input
                type="text"
                placeholder="Nome do hábito..."
                value={habitForm.name}
                onChange={e => setHabitForm(f => ({ ...f, name: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-green-500"
                autoFocus
              />

              {/* Icon picker */}
              <div>
                <label className="text-xs text-gray-500 block mb-2">Ícone</label>
                <div className="flex flex-wrap gap-2">
                  {HABIT_ICONS.map(icon => (
                    <button key={icon} onClick={() => setHabitForm(f => ({ ...f, icon }))}
                      className={`w-9 h-9 rounded-lg text-lg flex items-center justify-center transition-all ${
                        habitForm.icon === icon ? 'bg-white/15 ring-2 ring-green-500' : 'bg-[#222] hover:bg-[#333]'
                      }`}>{icon}</button>
                  ))}
                </div>
              </div>

              {/* Color */}
              <div>
                <label className="text-xs text-gray-500 block mb-2">Cor</label>
                <div className="flex gap-2">
                  {['#10B981', '#3B82F6', '#EF4444', '#F59E0B', '#8B5CF6', '#EC4899', '#06B6D4', '#F97316'].map(c => (
                    <button key={c} onClick={() => setHabitForm(f => ({ ...f, color: c }))}
                      className={`w-8 h-8 rounded-full transition-all ${habitForm.color === c ? 'ring-2 ring-offset-2 ring-offset-[#1a1a1a]' : ''}`}
                      style={{ backgroundColor: c, ['--tw-ring-color' as string]: c }} />
                  ))}
                </div>
              </div>

              {/* Days */}
              <div>
                <label className="text-xs text-gray-500 block mb-2">Dias</label>
                <select
                  value={DAYS_OPTIONS.find(d => d.value === habitForm.days) ? habitForm.days : 'custom'}
                  onChange={e => {
                    if (e.target.value !== 'custom') setHabitForm(f => ({ ...f, days: e.target.value }));
                  }}
                  className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-green-500"
                >
                  {DAYS_OPTIONS.map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                  <option value="custom">Personalizado</option>
                </select>
                {!DAYS_OPTIONS.find(d => d.value === habitForm.days) && habitForm.days !== 'daily' && habitForm.days !== 'weekdays' && (
                  <div className="flex gap-1 mt-2">
                    {['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'].map((label, idx) => {
                      const selected = habitForm.days.split(',').map(d => parseInt(d.trim())).includes(idx);
                      return (
                        <button key={idx} onClick={() => {
                          const current = new Set(habitForm.days.split(',').filter(Boolean).map(d => parseInt(d.trim())));
                          if (selected) current.delete(idx); else current.add(idx);
                          setHabitForm(f => ({ ...f, days: [...current].sort().join(',') || '0' }));
                        }}
                          className={`flex-1 py-2 rounded-lg text-xs font-medium transition-all ${
                            selected ? 'bg-green-600 text-white' : 'bg-[#222] text-gray-500'
                          }`}>{label}</button>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Fixed time */}
              <div>
                <label className="text-xs text-gray-500 block mb-2">Hora fixa (opcional)</label>
                <input
                  type="time"
                  value={habitForm.fixed_time}
                  onChange={e => setHabitForm(f => ({ ...f, fixed_time: e.target.value }))}
                  className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-green-500"
                />
                <p className="text-[10px] text-gray-600 mt-1">Deixa vazio para "qualquer hora do dia"</p>
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowHabitModal(false)}
                className="px-4 py-2.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm flex-1">
                Cancelar
              </button>
              <button onClick={saveHabit}
                className="px-6 py-2.5 bg-green-600 hover:bg-green-700 rounded-xl text-sm font-medium flex-1">
                {editingHabit ? 'Guardar' : 'Criar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Check Habit Time Modal */}
      {showCheckModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowCheckModal(null)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 max-w-[90vw] w-[340px] border border-[#333]" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-bold mb-2">A que horas fizeste?</h3>
            <p className="text-sm text-gray-500 mb-4">{showCheckModal.habitName}</p>
            <input
              type="time"
              value={checkTime}
              onChange={e => setCheckTime(e.target.value)}
              className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-green-500 mb-4"
              autoFocus
            />
            <div className="flex gap-3">
              <button onClick={() => setShowCheckModal(null)}
                className="px-4 py-2.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm flex-1">Cancelar</button>
              <button onClick={() => {
                checkHabit(showCheckModal.habitId, showCheckModal.date, checkTime);
                setShowCheckModal(null);
              }} className="px-4 py-2.5 bg-green-600 hover:bg-green-700 rounded-xl text-sm font-medium flex-1">
                ✅ Confirmar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Day Template Panel */}
      {showTemplatePanel && (
        <div className="fixed right-0 top-0 bottom-0 w-80 bg-[#161616] border-l border-[#222] shadow-2xl z-40 flex flex-col">
          <div className="flex items-center justify-between p-4 border-b border-[#222]">
            <h3 className="text-sm font-bold flex items-center gap-2">
              <LayoutTemplate size={16} className="text-blue-400" /> Templates de Dia
            </h3>
            <div className="flex items-center gap-2">
              <button onClick={() => setShowTemplateCreateModal(true)} className="p-1.5 bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 rounded-lg">
                <Plus size={14} />
              </button>
              <button onClick={() => setShowTemplatePanel(false)} className="p-1.5 hover:bg-white/10 rounded-lg">
                <X size={14} />
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-4">
            {dayTemplates.length === 0 ? (
              <div className="text-center py-8">
                <p className="text-gray-600 text-sm">Sem templates</p>
                <p className="text-xs text-gray-700 mt-1">Cria um para preencher dias rapidamente</p>
              </div>
            ) : (
              <div className="space-y-3">
                {dayTemplates.map((tpl: any) => {
                  const events = JSON.parse(tpl.events_json || '[]');
                  return (
                    <div key={tpl.id} className="bg-[#111] border border-[#1a1a1a] rounded-xl p-3">
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span>{tpl.icon || '📋'}</span>
                          <span className="text-sm font-medium">{tpl.name}</span>
                        </div>
                        <button onClick={() => deleteTemplate(tpl.id)} className="text-gray-600 hover:text-red-400">
                          <Trash2 size={12} />
                        </button>
                      </div>
                      <div className="space-y-1 mb-3">
                        {events.map((ev: any, i: number) => (
                          <div key={i} className="text-xs text-gray-500 flex items-center gap-1">
                            <Clock size={10} /> {ev.start_time}-{ev.end_time} {ev.title}
                          </div>
                        ))}
                      </div>
                      <button
                        onClick={() => applyTemplate(tpl, currentDate)}
                        className="w-full py-2 bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 rounded-lg text-xs font-medium"
                      >
                        Aplicar a {format(currentDate, "d 'de' MMM", { locale: pt })}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Template Create Modal */}
      {showTemplateCreateModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowTemplateCreateModal(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 max-w-[90vw] w-[480px] border border-[#333] max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-bold mb-4">Novo Template de Dia</h3>
            <div className="space-y-4">
              <div className="flex gap-3">
                <input
                  type="text"
                  placeholder="Nome do template..."
                  value={templateForm.name}
                  onChange={e => setTemplateForm(f => ({ ...f, name: e.target.value }))}
                  className="flex-1 bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-500"
                  autoFocus
                />
              </div>
              <div className="flex gap-2">
                {['📋', '💼', '🏋️', '📚', '🎮', '🏖️', '🧘', '🚀'].map(icon => (
                  <button key={icon} onClick={() => setTemplateForm(f => ({ ...f, icon }))}
                    className={`w-9 h-9 rounded-lg text-lg flex items-center justify-center ${
                      templateForm.icon === icon ? 'bg-white/15 ring-2 ring-blue-500' : 'bg-[#222]'
                    }`}>{icon}</button>
                ))}
              </div>

              {/* Events list */}
              <div>
                <p className="text-xs text-gray-500 mb-2">Eventos no template ({templateForm.events.length})</p>
                <div className="space-y-1 mb-3">
                  {templateForm.events.map((ev, i) => (
                    <div key={i} className="flex items-center gap-2 bg-[#222] rounded-lg px-3 py-2">
                      <span className="text-xs text-gray-400">{ev.start_time}-{ev.end_time}</span>
                      <span className="text-sm flex-1">{ev.title}</span>
                      <button onClick={() => setTemplateForm(f => ({ ...f, events: f.events.filter((_, j) => j !== i) }))}
                        className="text-gray-600 hover:text-red-400"><X size={12} /></button>
                    </div>
                  ))}
                </div>

                {/* Add event form */}
                <div className="bg-[#1e1e1e] rounded-xl p-3 space-y-2">
                  <input type="text" placeholder="Título do evento..."
                    value={templateEventForm.title}
                    onChange={e => setTemplateEventForm(f => ({ ...f, title: e.target.value }))}
                    className="w-full bg-[#222] border border-[#333] rounded-lg px-3 py-2 text-sm focus:outline-none" />
                  <div className="flex gap-2">
                    <input type="time" value={templateEventForm.start_time}
                      onChange={e => setTemplateEventForm(f => ({ ...f, start_time: e.target.value }))}
                      className="bg-[#222] border border-[#333] rounded-lg px-2 py-1.5 text-xs text-white" />
                    <input type="time" value={templateEventForm.end_time}
                      onChange={e => setTemplateEventForm(f => ({ ...f, end_time: e.target.value }))}
                      className="bg-[#222] border border-[#333] rounded-lg px-2 py-1.5 text-xs text-white" />
                    <select value={templateEventForm.category}
                      onChange={e => setTemplateEventForm(f => ({ ...f, category: e.target.value }))}
                      className="bg-[#222] border border-[#333] rounded-lg px-2 py-1.5 text-xs text-white flex-1">
                      {EVENT_CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                    </select>
                    <button onClick={() => {
                      if (!templateEventForm.title.trim()) return;
                      setTemplateForm(f => ({ ...f, events: [...f.events, { ...templateEventForm }].sort((a, b) => a.start_time.localeCompare(b.start_time)) }));
                      setTemplateEventForm(f => ({ ...f, title: '' }));
                    }} className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-xs rounded-lg font-medium">+</button>
                  </div>
                </div>
              </div>
            </div>
            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowTemplateCreateModal(false)}
                className="px-4 py-2.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm flex-1">Cancelar</button>
              <button onClick={saveTemplate}
                disabled={!templateForm.name.trim() || templateForm.events.length === 0}
                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-30 rounded-xl text-sm font-medium flex-1">
                Criar Template
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
