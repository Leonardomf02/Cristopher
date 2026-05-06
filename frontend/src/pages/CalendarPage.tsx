import { useState, useEffect } from 'react';
import {
  format,
  startOfMonth, endOfMonth, startOfWeek, endOfWeek,
  eachDayOfInterval, isSameMonth, isSameDay, isToday,
  addMonths, subMonths, addWeeks, subWeeks, addDays, subDays,
  addYears, subYears, startOfYear, endOfYear, eachMonthOfInterval,
  getDay,
} from 'date-fns';
import { pt } from 'date-fns/locale';
import { ChevronLeft, ChevronRight, Plus, X, Clock, Check, Tag, Repeat, CalendarDays, CheckSquare, Download, Upload, Loader, Target, Trash2, Edit3, LayoutTemplate, Monitor } from 'lucide-react';
import { Link } from 'react-router-dom';
import { eventsApi, dayTypesApi, listsApi, habitsApi, templatesApi } from '../api';
import { Event, EventCreate, EVENT_CATEGORIES, DayTypeEntry, DAY_TYPE_PRESETS, RECURRENCE_OPTIONS } from '../types';

type ViewMode = 'day' | 'week' | 'month' | 'year';

export default function CalendarPage() {
  const [currentDate, setCurrentDate] = useState(new Date());
  const [viewMode, setViewMode] = useState<ViewMode>('month');
  const [events, setEvents] = useState<Event[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [selectedDate, setSelectedDate] = useState<Date | null>(null);
  const [editingEvent, setEditingEvent] = useState<Event | null>(null);
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

  useEffect(() => {
    loadEvents();
  }, [currentDate, viewMode]);

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
    const [data, dtData, reminders, habitsData, completionsData, tplData, analyticsData] = await Promise.all([
      eventsApi.list({ start_date: start, end_date: end }),
      dayTypesApi.list({ start_date: start, end_date: end }),
      listsApi.getReminders({ start_date: start, end_date: end }),
      habitsApi.list().catch(() => []),
      habitsApi.completionsRange(start, end).catch(() => []),
      templatesApi.list().catch(() => []),
      habitsApi.analytics(30).catch(() => null),
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
    setSelectedDate(d);
    setShowModal(true);
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
    setShowModal(true);
  }

  async function handleSave() {
    if (!form.title.trim()) return;
    if (editingEvent) {
      await eventsApi.update(editingEvent.id, form);
    } else {
      await eventsApi.create(form);
    }
    setShowModal(false);
    loadEvents();
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
    if (event.is_reminder) {
      const itemId = Number(String(event.id).replace('reminder-', ''));
      await listsApi.updateItem(itemId, { checked: !event.completed });
    } else {
      await eventsApi.update(event.id as number, { completed: !event.completed });
    }
    loadEvents();
  }

  function getEventsForDate(date: Date) {
    const dateStr = format(date, 'yyyy-MM-dd');
    return events.filter(e => e.date === dateStr);
  }

  function getDayType(date: Date): DayTypeEntry | undefined {
    const dateStr = format(date, 'yyyy-MM-dd');
    return dayTypes.find(d => d.date === dateStr);
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
        <div className="grid grid-cols-3 sm:grid-cols-5 lg:grid-cols-7 gap-px mb-2">
          {['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'].map(d => (
            <div key={d} className="text-center text-xs text-gray-500 py-2 font-medium">{d}</div>
          ))}
        </div>
        <div className="grid grid-cols-3 sm:grid-cols-5 lg:grid-cols-7 gap-px">
          {days.map(day => {
            const dayEvents = getEventsForDate(day);
            const dayCompletions = getCompletionsForDate(day);
            const dt = getDayType(day);
            const isCurrentMonth = isSameMonth(day, currentDate);
            return (
              <div
                key={day.toISOString()}
                onClick={() => openNewEvent(day)}
                onContextMenu={e => { e.preventDefault(); setDayTypeMenu({ date: format(day, 'yyyy-MM-dd'), x: e.clientX, y: e.clientY }); }}
                className={`min-h-[100px] p-2 rounded-lg cursor-pointer transition-all border ${
                  isToday(day)
                    ? 'border-blue-500/50 bg-blue-500/5'
                    : isCurrentMonth
                    ? 'border-[#222] bg-[#161616] hover:bg-[#1a1a1a]'
                    : 'border-transparent bg-[#111] opacity-40'
                }`}
                style={dt ? { borderTopColor: dt.color, borderTopWidth: '3px' } : undefined}
              >
                <div className="flex items-center justify-between">
                  <span className={`text-sm font-medium ${
                    isToday(day) ? 'text-blue-400' : isCurrentMonth ? 'text-gray-300' : 'text-gray-600'
                  }`}>
                    {format(day, 'd')}
                  </span>
                  {dt && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ backgroundColor: dt.color + '22', color: dt.color }}>
                      {DAY_TYPE_PRESETS.find(p => p.name === dt.type_name)?.icon || '📌'} {dt.type_name}
                    </span>
                  )}
                </div>
                <div className="mt-1 space-y-0.5">
                  {dayCompletions.map(comp => (
                    <div
                      key={`hc-${comp.id}`}
                      onClick={(e) => e.stopPropagation()}
                      className="text-xs px-1.5 py-0.5 rounded truncate flex items-center gap-0.5"
                      style={{ backgroundColor: comp.habit_color + '22', color: comp.habit_color }}
                    >
                      <span className="text-[10px]">{comp.habit_icon}</span>
                      {comp.completed_at} {comp.habit_name}
                    </div>
                  ))}
                  {dayEvents.slice(0, Math.max(1, 3 - dayCompletions.length)).map(ev => (
                    <div
                      key={`${ev.id}-${day.toISOString()}`}
                      onClick={(e) => { e.stopPropagation(); openEditEvent(ev); }}
                      className={`text-xs px-1.5 py-0.5 rounded truncate cursor-pointer flex items-center gap-0.5 ${
                        ev.completed ? 'line-through opacity-50' : ''
                      }`}
                      style={{ backgroundColor: ev.color + '22', color: ev.color }}
                    >
                      {ev.is_reminder && <CheckSquare size={8} className="shrink-0" />}
                      {ev.recurrence && ev.recurrence !== 'none' && <Repeat size={8} className="shrink-0" />}
                      {ev.start_time ? `${ev.start_time} ` : ''}
                      {ev.title}
                    </div>
                  ))}
                  {(dayEvents.length + dayCompletions.length) > 3 && (
                    <div className="text-xs text-gray-500 px-1">+{dayEvents.length + dayCompletions.length - 3} mais</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // ── Week View ───────────────────────────────────────────────
  function renderWeekView() {
    const ws = startOfWeek(currentDate, { weekStartsOn: 1 });
    const we = endOfWeek(currentDate, { weekStartsOn: 1 });
    const days = eachDayOfInterval({ start: ws, end: we });
    const hours = Array.from({ length: 16 }, (_, i) => i + 7); // 7am to 10pm

    return (
      <div className="overflow-x-auto">
        <div className="grid grid-cols-8 gap-px min-w-[800px]">
          <div className="text-xs text-gray-500 p-2" />
          {days.map(day => (
            <div key={day.toISOString()} className={`text-center p-2 rounded-t-lg ${
              isToday(day) ? 'bg-blue-500/10' : 'bg-[#161616]'
            }`}>
              <div className="text-xs text-gray-500">{format(day, 'EEE', { locale: pt })}</div>
              <div className={`text-lg font-bold ${isToday(day) ? 'text-blue-400' : 'text-white'}`}>
                {format(day, 'd')}
              </div>
            </div>
          ))}

          {hours.map(hour => (
            <>
              <div key={`h-${hour}`} className="text-xs text-gray-600 p-2 text-right pr-3">
                {String(hour).padStart(2, '0')}:00
              </div>
              {days.map(day => {
                const dayEvents = getEventsForDate(day);
                const hourStr = String(hour).padStart(2, '0');
                const hourEvents = dayEvents.filter(e => e.start_time?.startsWith(hourStr));
                const flexEvents = hour === 7 ? dayEvents.filter(e => e.event_type === 'flexible') : [];

                return (
                  <div
                    key={`${day.toISOString()}-${hour}`}
                    onClick={() => {
                      const d = new Date(day);
                      setForm(f => ({ ...f, start_time: `${hourStr}:00`, end_time: `${String(hour + 1).padStart(2, '0')}:00` }));
                      openNewEvent(d);
                    }}
                    className="border-t border-[#1a1a1a] min-h-[48px] p-0.5 cursor-pointer hover:bg-white/5"
                  >
                    {flexEvents.map(ev => (
                      <div
                        key={ev.id}
                        onClick={(e) => { e.stopPropagation(); openEditEvent(ev); }}
                        className="text-xs px-1 py-0.5 rounded mb-0.5 cursor-pointer"
                        style={{ backgroundColor: ev.color + '22', color: ev.color, borderLeft: `2px dashed ${ev.color}` }}
                      >
                        ⏰ {ev.title}
                      </div>
                    ))}
                    {hourEvents.map(ev => (
                      <div
                        key={ev.id}
                        onClick={(e) => { e.stopPropagation(); openEditEvent(ev); }}
                        className={`text-xs px-1 py-0.5 rounded cursor-pointer ${ev.completed ? 'line-through opacity-50' : ''}`}
                        style={{ backgroundColor: ev.color + '33', color: ev.color }}
                      >
                        {ev.title}
                      </div>
                    ))}
                  </div>
                );
              })}
            </>
          ))}
        </div>
      </div>
    );
  }

  // ── Day View (Time Blocking) ─────────────────────────────────
  function renderDayView() {
    const dayEvents = getEventsForDate(currentDate);
    const fixedEvents = dayEvents.filter(e => e.event_type === 'fixed' && e.start_time).sort((a, b) => (a.start_time || '').localeCompare(b.start_time || ''));
    const flexEvents = dayEvents.filter(e => e.event_type === 'flexible');
    const hours = Array.from({ length: 16 }, (_, i) => i + 7);
    const HOUR_HEIGHT = 60; // px per hour

    // Calculate block positions for time-blocking visualization
    function getBlockStyle(ev: Event) {
      if (!ev.start_time) return {};
      const [sh, sm] = ev.start_time.split(':').map(Number);
      const startMin = (sh - 7) * 60 + sm;
      let durationMin = 60; // default 1h
      if (ev.end_time) {
        const [eh, em] = ev.end_time.split(':').map(Number);
        durationMin = Math.max((eh - sh) * 60 + (em - sm), 15);
      }
      return {
        top: `${(startMin / 60) * HOUR_HEIGHT}px`,
        height: `${Math.max((durationMin / 60) * HOUR_HEIGHT - 2, 20)}px`,
      };
    }

    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* Timeline with time blocks */}
        <div className="col-span-2">
          <h3 className="text-sm font-medium text-gray-400 mb-4">Timeline — Time Blocking</h3>
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

            {/* Event blocks - absolute positioned */}
            <div className="absolute left-16 right-0">
              {fixedEvents.map(ev => {
                const style = getBlockStyle(ev);
                return (
                  <div
                    key={ev.id}
                    onClick={(e) => { e.stopPropagation(); openEditEvent(ev); }}
                    className={`absolute left-0 right-2 rounded-lg px-3 py-1.5 cursor-pointer transition-all hover:ring-2 hover:ring-white/20 ${ev.completed ? 'opacity-50' : ''}`}
                    style={{
                      ...style,
                      backgroundColor: ev.color + '33',
                      borderLeft: `3px solid ${ev.color}`,
                      zIndex: 10,
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <button onClick={(e) => { e.stopPropagation(); toggleComplete(ev); }} className="shrink-0">
                        <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                          ev.completed ? 'border-green-400 bg-green-400' : 'border-gray-500'
                        }`}>
                          {ev.completed && <Check size={10} className="text-black" />}
                        </div>
                      </button>
                      <span className={`text-sm font-medium truncate ${ev.completed ? 'line-through' : ''}`} style={{ color: ev.color }}>
                        {ev.title}
                      </span>
                      <span className="text-[10px] text-gray-500 shrink-0">
                        {ev.start_time}{ev.end_time ? `-${ev.end_time}` : ''}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Flexible tasks */}
        <div>
          <h3 className="text-sm font-medium text-gray-400 mb-4 flex items-center gap-2">
            <Clock size={14} /> Flexíveis (qualquer hora)
          </h3>
          <div className="space-y-2">
            {flexEvents.length === 0 ? (
              <p className="text-xs text-gray-600">Sem tarefas flexíveis</p>
            ) : (
              flexEvents.map(ev => (
                <div
                  key={ev.id}
                  onClick={() => openEditEvent(ev)}
                  className={`flex items-center gap-3 p-3 rounded-xl cursor-pointer ${ev.completed ? 'opacity-50' : ''}`}
                  style={{ backgroundColor: ev.color + '11', borderLeft: `3px dashed ${ev.color}` }}
                >
                  <button onClick={(e) => { e.stopPropagation(); toggleComplete(ev); }}>
                    <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${
                      ev.completed ? 'border-green-400 bg-green-400' : 'border-gray-500'
                    }`}>
                      {ev.completed && <Check size={12} className="text-black" />}
                    </div>
                  </button>
                  <span className={`text-sm ${ev.completed ? 'line-through' : ''}`} style={{ color: ev.color }}>
                    {ev.title}
                  </span>
                </div>
              ))
            )}
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
      <div className="flex items-center justify-between mb-8">
        <div>
          <h2 className="text-2xl font-bold capitalize">{headerLabel()}</h2>
        </div>
        <div className="flex items-center gap-3">
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
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-xl text-sm font-medium transition-all shadow-lg shadow-blue-600/20"
          >
            <Plus size={16} /> Novo Evento
          </button>
        </div>
      </div>

      {/* Calendar Grid */}
      {viewMode === 'month' && renderMonthView()}
      {viewMode === 'week' && renderWeekView()}
      {viewMode === 'day' && renderDayView()}
      {viewMode === 'year' && renderYearView()}

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
      {showModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowModal(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 w-[480px] border border-[#333]" onClick={e => e.stopPropagation()}>
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
              <div className="flex gap-2">
                <button
                  onClick={() => setForm(f => ({ ...f, event_type: 'fixed' }))}
                  className={`flex-1 py-2 rounded-xl text-sm font-medium transition-all ${
                    form.event_type === 'fixed' ? 'bg-blue-600 text-white' : 'bg-[#222] text-gray-400'
                  }`}
                >
                  ⏰ Hora Fixa
                </button>
                <button
                  onClick={() => setForm(f => ({ ...f, event_type: 'flexible', start_time: null, end_time: null }))}
                  className={`flex-1 py-2 rounded-xl text-sm font-medium transition-all ${
                    form.event_type === 'flexible' ? 'bg-purple-600 text-white' : 'bg-[#222] text-gray-400'
                  }`}
                >
                  🔄 Flexível
                </button>
              </div>

              {form.event_type === 'fixed' && (
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
              <button onClick={handleSave}
                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 rounded-xl text-sm font-medium">
                {editingEvent ? 'Guardar' : 'Criar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Apple Calendar Import Modal */}
      {showImportModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowImportModal(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 w-[420px] border border-[#333] max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
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
          <div className="bg-[#1a1a1a] rounded-2xl p-6 w-[420px] border border-[#333]" onClick={e => e.stopPropagation()}>
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
          <div className="bg-[#1a1a1a] rounded-2xl p-6 w-[340px] border border-[#333]" onClick={e => e.stopPropagation()}>
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
          <div className="bg-[#1a1a1a] rounded-2xl p-6 w-[480px] border border-[#333] max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
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
