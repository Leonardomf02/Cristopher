import { useState, useEffect } from 'react';
import { format, isToday, isTomorrow, startOfWeek, endOfWeek } from 'date-fns';
import { pt } from 'date-fns/locale';
import { Calendar, Wallet, Swords, Plane, Check, TrendingUp, Clock, ArrowRight, Moon, Target, Plus, X, ChevronLeft, ChevronRight, BarChart3, Smile, Frown, Meh, Heart, BookOpen, Flame, Zap, Edit2, Pencil, LineChart, ListPlus } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { eventsApi, expensesApi, lolApi, tripsApi, sleepApi, habitsApi, dashboardApi, moodApi, dayTypesApi, investmentsApi, listsApi } from '../api';
import { Event, Expense, LolStats, Trip, EVENT_CATEGORIES, EXPENSE_CATEGORIES, SleepStats, EventCreate, DAY_TYPE_PRESETS, STREAK_PROTECTED_DAY_TYPES } from '../types';

const MOOD_EMOJIS = [
  { value: 1, emoji: '😢', label: 'Péssimo', color: '#EF4444' },
  { value: 2, emoji: '😔', label: 'Mau', color: '#F97316' },
  { value: 3, emoji: '😐', label: 'Normal', color: '#F59E0B' },
  { value: 4, emoji: '😊', label: 'Bom', color: '#10B981' },
  { value: 5, emoji: '😁', label: 'Ótimo', color: '#3B82F6' },
];

const MOOD_TAGS = [
  { value: 'sono', label: 'Com sono', emoji: '😴' },
  { value: 'cansado', label: 'Cansado', emoji: '🥱' },
  { value: 'stress', label: 'Stress', emoji: '😣' },
  { value: 'ansioso', label: 'Ansioso', emoji: '😰' },
  { value: 'feliz', label: 'Feliz', emoji: '😄' },
  { value: 'motivado', label: 'Motivado', emoji: '💪' },
  { value: 'focado', label: 'Focado', emoji: '🎯' },
  { value: 'calmo', label: 'Calmo', emoji: '😌' },
  { value: 'triste', label: 'Triste', emoji: '😢' },
  { value: 'irritado', label: 'Irritado', emoji: '😤' },
];

export default function Dashboard() {
  const navigate = useNavigate();
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
  const [pendingFilter, setPendingFilter] = useState('');
  const [pickingId, setPickingId] = useState<number | null>(null);

  // Weekly Review
  const [weeklyReview, setWeeklyReview] = useState<any>(null);
  const [weekOffset, setWeekOffset] = useState(0);
  const [showWeeklyReview, setShowWeeklyReview] = useState(false);

  // Mood & Journal
  const [todayMood, setTodayMood] = useState<any>(null);
  const [todayJournal, setTodayJournal] = useState<any>(null);
  const [moodNote, setMoodNote] = useState('');
  const [moodTags, setMoodTags] = useState<string[]>([]);
  const [editingMood, setEditingMood] = useState(false);
  const [journalContent, setJournalContent] = useState('');
  const [showJournal, setShowJournal] = useState(false);

  // Day Type
  const [todayDayType, setTodayDayType] = useState<any>(null);
  const [showDayTypePicker, setShowDayTypePicker] = useState(false);

  // Investments
  const [investmentSummary, setInvestmentSummary] = useState<any>(null);

  const today = new Date();
  const todayStr = format(today, 'yyyy-MM-dd');

  useEffect(() => {
    loadDashboard();
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
      setMoodTags(moodData.mood.tags ? moodData.mood.tags.split(',').filter((t: string) => t.trim()) : []);
    }
    setTodayDayType(dayTypeData && dayTypeData.length > 0 ? dayTypeData[0] : null);
    setInvestmentSummary(investData);
  }

  async function toggleEvent(event: Event) {
    await eventsApi.update(event.id, { completed: !event.completed });
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

  async function loadPendingItems() {
    try {
      const data = await listsApi.pendingItems();
      setAllPending(data);
    } catch {
      setAllPending([]);
    }
  }

  async function togglePicker() {
    if (!showPickPending) await loadPendingItems();
    setShowPickPending(s => !s);
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

  async function saveMood(value: number) {
    await moodApi.create({
      date: todayStr,
      mood: value,
      note: moodNote,
      tags: moodTags.join(','),
    });
    const moodData = await moodApi.today();
    setTodayMood(moodData?.mood || null);
    setEditingMood(false);
  }

  function toggleMoodTag(tag: string) {
    setMoodTags(prev => prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag]);
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
    <div>
      {/* Header */}
      <div className="mb-8">
        <h2 className="text-2xl sm:text-3xl font-bold">{greeting}! 👋</h2>
        <p className="text-gray-500 mt-1">{format(today, "EEEE, d 'de' MMMM 'de' yyyy", { locale: pt })}</p>
      </div>

      {/* Today's Schedule (Agenda) + Habits + Trips */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
        {/* Today's Schedule */}
        <div className="col-span-2">
          <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
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
                  <div className="max-h-64 overflow-y-auto divide-y divide-[#222] rounded-lg border border-[#222] bg-[#0f0f0f]">
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
              return (
                <div className="divide-y divide-[#1a1a1a]">
                  {/* Pending tasks first (most actionable) */}
                  {pendingTasks.map(task => (
                    <div key={task.id} className="flex items-center gap-4 p-4 hover:bg-white/5">
                      <button onClick={() => toggleTask(task)}
                        className="w-6 h-6 rounded-full border-2 border-gray-600 hover:border-green-400 flex items-center justify-center shrink-0">
                      </button>
                      <div className="w-1 h-8 rounded-full" style={{ backgroundColor: task.color }} />
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
                    </div>
                  ))}
                  {/* Events */}
                  {sortedEvents.map(event => {
                    const catInfo = EVENT_CATEGORIES.find(c => c.value === event.category);
                    return (
                      <div key={event.id} className="flex items-center gap-4 p-4 hover:bg-white/5">
                        <button onClick={() => toggleEvent(event)}
                          className={`w-6 h-6 rounded-full border-2 flex items-center justify-center shrink-0 ${
                            event.completed ? 'border-green-400 bg-green-400' : 'border-gray-600 hover:border-green-400'
                          }`}>
                          {event.completed && <Check size={14} className="text-black" />}
                        </button>
                        <div className="w-1 h-8 rounded-full" style={{ backgroundColor: event.color }} />
                        <div className="flex-1">
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
                        <span className="text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: event.color + '22', color: event.color }}>
                          {catInfo?.label || event.category}
                        </span>
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
                        <div key={task.id} className="flex items-center gap-4 p-4 pl-6 hover:bg-white/5">
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
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })()}
          </div>
        </div>

        {/* Right column - habits + upcoming trips */}
        <div className="space-y-6">
          {todayHabits.length > 0 && (
            <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
              <div className="flex items-center justify-between p-4 border-b border-[#222]">
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
                    }}
                    className="flex items-center gap-3 p-3 cursor-pointer hover:bg-white/5 transition"
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
                        <p className="text-[10px] text-gray-600">Feito às {h.completion.completed_at}</p>
                      )}
                    </div>
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

          {upcomingTrips.length > 0 && (
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
          )}
        </div>
      </div>

      {/* Day Type Selector */}
      <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 mb-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl">
              {todayDayType
                ? (DAY_TYPE_PRESETS.find(p => p.name === todayDayType.type_name)?.icon || '📅')
                : '📅'}
            </span>
            <div>
              <p className="text-xs text-gray-500">Tipo de Dia</p>
              <div className="flex items-center gap-2">
                <p className="text-sm font-medium" style={{ color: todayDayType?.color || '#9CA3AF' }}>
                  {todayDayType?.type_name || 'Não definido'}
                </p>
                {todayDayType && STREAK_PROTECTED_DAY_TYPES.includes(todayDayType.type_name) && (
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

      {/* Mood Prompt — full selector when not set or editing */}
      {(!todayMood || editingMood) && (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-5 mb-6">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
              <Heart size={14} className="text-pink-400" /> {editingMood ? 'Editar humor' : 'Como te sentes hoje?'}
            </h3>
            {editingMood && (
              <button onClick={() => setEditingMood(false)} className="p-1 text-gray-500 hover:text-white">
                <X size={14} />
              </button>
            )}
          </div>
          <div className="flex items-center gap-3 mb-3">
            {MOOD_EMOJIS.map(m => {
              const isSelected = todayMood?.mood === m.value;
              return (
                <button
                  key={m.value}
                  onClick={() => saveMood(m.value)}
                  className={`flex flex-col items-center gap-1 p-3 rounded-xl transition-all group ${
                    isSelected ? 'bg-white/10 ring-2 ring-pink-400/50' : 'hover:bg-white/10'
                  }`}
                >
                  <span className="text-2xl sm:text-3xl group-hover:scale-125 transition-transform">{m.emoji}</span>
                  <span className="text-[10px] text-gray-600 group-hover:text-gray-400">{m.label}</span>
                </button>
              );
            })}
          </div>
          {/* Mood tags */}
          <div className="mb-3">
            <p className="text-[10px] text-gray-500 mb-2">Como te sentes? (escolhe todas que se aplicam)</p>
            <div className="flex gap-1.5 flex-wrap">
              {MOOD_TAGS.map(tag => {
                const isActive = moodTags.includes(tag.value);
                return (
                  <button
                    key={tag.value}
                    onClick={() => toggleMoodTag(tag.value)}
                    className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] transition-all ${
                      isActive
                        ? 'bg-pink-500/20 text-pink-300 ring-1 ring-pink-400/50'
                        : 'bg-white/5 text-gray-400 hover:bg-white/10'
                    }`}
                  >
                    <span>{tag.emoji}</span> {tag.label}
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
          {editingMood && todayMood && (
            <div className="mt-2 flex justify-end">
              <button
                onClick={() => saveMood(todayMood.mood)}
                className="px-4 py-1.5 bg-pink-600 hover:bg-pink-500 text-white text-xs font-medium rounded-lg"
              >
                Guardar alterações
              </button>
            </div>
          )}
        </div>
      )}

      {/* Today's mood display + journal toggle */}
      {todayMood && !editingMood && (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 mb-6 flex items-center justify-between">
          <div className="flex items-center gap-3 flex-1 min-w-0">
            <span className="text-2xl">{MOOD_EMOJIS.find(m => m.value === todayMood.mood)?.emoji || '😐'}</span>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">Humor: {MOOD_EMOJIS.find(m => m.value === todayMood.mood)?.label}</p>
              {todayMood.tags && (
                <div className="flex gap-1 flex-wrap mt-1">
                  {todayMood.tags.split(',').filter((t: string) => t.trim()).map((tagValue: string) => {
                    const tag = MOOD_TAGS.find(t => t.value === tagValue.trim());
                    if (!tag) return null;
                    return (
                      <span key={tagValue} className="text-[10px] bg-pink-500/10 text-pink-300 px-1.5 py-0.5 rounded-full">
                        {tag.emoji} {tag.label}
                      </span>
                    );
                  })}
                </div>
              )}
              {todayMood.note && <p className="text-xs text-gray-500 mt-1 truncate">{todayMood.note}</p>}
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={() => setEditingMood(true)}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs bg-white/5 text-gray-400 hover:text-white hover:bg-white/10"
            >
              <Edit2 size={12} /> Editar
            </button>
            <button
              onClick={() => setShowJournal(!showJournal)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-all ${showJournal ? 'bg-purple-600/20 text-purple-400' : 'bg-white/5 text-gray-400 hover:text-white'}`}
            >
              <BookOpen size={14} /> Diário
            </button>
          </div>
        </div>
      )}

      {/* Quick Journal */}
      {showJournal && (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-5 mb-6">
          <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
            <BookOpen size={14} className="text-purple-400" /> Diário Rápido
          </h3>
          <textarea
            value={journalContent}
            onChange={e => setJournalContent(e.target.value)}
            placeholder="O que aconteceu hoje? O que tens em mente?..."
            rows={4}
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

      {/* Quick Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
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
              <p className={`text-2xl font-bold ${sleepStats.avg_hours >= 7 ? 'text-green-400' : sleepStats.avg_hours >= 5 ? 'text-yellow-400' : 'text-red-400'}`}>
                {sleepStats.avg_hours.toFixed(1)}h
              </p>
              <p className="text-xs text-gray-500 mt-1">média/noite</p>
            </>
          ) : (
            <>
              <p className="text-2xl font-bold text-gray-600">—</p>
              <p className="text-xs text-gray-500 mt-1">sem registos</p>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
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

      {/* Weekly Review Card */}
      <div className="bg-[#161616] rounded-2xl border border-[#222] mb-6 overflow-hidden">
        <button
          onClick={() => setShowWeeklyReview(!showWeeklyReview)}
          className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-all"
        >
          <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
            <BarChart3 size={14} className="text-blue-400" /> Weekly Review
          </h3>
          <div className="flex items-center gap-2">
            <button onClick={e => { e.stopPropagation(); setWeekOffset(o => o - 1); }} className="p-1 hover:bg-white/10 rounded">
              <ChevronLeft size={14} className="text-gray-500" />
            </button>
            <span className="text-xs text-gray-500 min-max-w-[90vw] w-[100px] text-center">
              {weekOffset === 0 ? 'Esta semana' : weekOffset === -1 ? 'Semana passada' : `${Math.abs(weekOffset)} sem. atrás`}
            </span>
            <button onClick={e => { e.stopPropagation(); setWeekOffset(o => Math.min(0, o + 1)); }} className="p-1 hover:bg-white/10 rounded" disabled={weekOffset >= 0}>
              <ChevronRight size={14} className={weekOffset >= 0 ? 'text-gray-700' : 'text-gray-500'} />
            </button>
          </div>
        </button>

        {showWeeklyReview && wr && (
          <div className="p-4 pt-0 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
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

            {/* Mood */}
            {wr.mood && wr.mood.entries > 0 && (
              <div className="bg-[#1a1a1a] rounded-xl p-3">
                <p className="text-[10px] text-gray-500 mb-1 flex items-center gap-1"><Heart size={10} /> Humor</p>
                <p className="text-lg font-bold">{MOOD_EMOJIS.find(m => m.value === Math.round(wr.mood.average))?.emoji || '😐'} {wr.mood.average.toFixed(1)}</p>
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
                      const catInfo = EXPENSE_CATEGORIES.find(c => c.value === cat);
                      return (
                        <span key={cat} className="text-xs bg-[#222] px-2 py-1 rounded-lg">
                          {catInfo?.emoji || '📦'} {catInfo?.label || cat}: €{Number(amount).toFixed(0)}
                        </span>
                      );
                    })}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
