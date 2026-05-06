import { Routes, Route, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useEffect } from 'react';
import { LayoutDashboard, Calendar, Wallet, Swords, Plane, ListTodo, Moon, Timer, Play, Pause, Square, StickyNote, TrendingUp, BarChart3, Code2, Smartphone } from 'lucide-react';
import Dashboard from './pages/Dashboard';
import CalendarPage from './pages/CalendarPage';
import ExpensesPage from './pages/ExpensesPage';
import LolPage from './pages/LolPage';
import TripsPage from './pages/TripsPage';
import TripDetail from './pages/TripDetail';
import ListsPage from './pages/ListsPage';
import SleepPage from './pages/SleepPage';
import FlowPage from './pages/FlowPage';
import NotesPage from './pages/NotesPage';
import InvestmentsPage from './pages/InvestmentsPage';
import HabitAnalyticsPage from './pages/HabitAnalyticsPage';
import AppUsagePage from './pages/AppUsagePage';
import IdeasPage from './pages/IdeasPage';
import CodeActivityPage from './pages/CodeActivityPage';
import ScreenTimePage from './pages/ScreenTimePage';
import { FlowProvider, useFlow } from './FlowContext';
import { requestNotificationPermission, notifyEventSoon, notifyHabitReminder, isNotificationsEnabled } from './notifications';
import { eventsApi, habitsApi } from './api';
import { format } from 'date-fns';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/calendar', icon: Calendar, label: 'Calendário' },
  { to: '/expenses', icon: Wallet, label: 'Gastos' },
  { to: '/lists', icon: ListTodo, label: 'Reminders' },
  { to: '/notes', icon: StickyNote, label: 'Notas' },
  { to: '/code', icon: Code2, label: 'VS Code' },
  { to: '/sleep', icon: Moon, label: 'Sono' },
  { to: '/flow', icon: Timer, label: 'Flow' },
  { to: '/habits', icon: BarChart3, label: 'Hábitos' },
  { to: '/screen-time', icon: Smartphone, label: 'Screen Time' },
  { to: '/lol', icon: Swords, label: 'LoL Tracker' },
  { to: '/investments', icon: TrendingUp, label: 'Investimentos' },
  { to: '/trips', icon: Plane, label: 'Viagens' },
];

export default function App() {
  return (
    <FlowProvider>
      <AppShell />
    </FlowProvider>
  );
}

function MiniTimer() {
  const { phase, secondsLeft, isPaused, activePreset, togglePause, stopTimer } = useFlow();
  const navigate = useNavigate();

  if (phase === 'idle' || !activePreset) return null;

  const m = Math.floor(secondsLeft / 60);
  const s = secondsLeft % 60;
  const time = `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;

  return (
    <div
      onClick={() => navigate('/flow')}
      className="mx-3 mb-2 p-3 rounded-xl border cursor-pointer transition-colors hover:bg-white/5"
      style={{ borderColor: activePreset.color + '60', backgroundColor: activePreset.color + '10' }}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-sm">{activePreset.icon}</span>
        <span className="text-xs font-medium truncate flex-1">{activePreset.name}</span>
        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${
          phase === 'work' ? 'bg-blue-500/20 text-blue-400' : 'bg-green-500/20 text-green-400'
        }`}>
          {phase === 'work' ? 'FOCO' : 'PAUSA'}
        </span>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-lg font-mono font-bold" style={{ color: activePreset.color }}>{time}</span>
        <div className="flex gap-1" onClick={e => e.stopPropagation()}>
          <button onClick={togglePause}
            className="p-1 rounded-lg hover:bg-white/10 transition-colors">
            {isPaused ? <Play size={14} /> : <Pause size={14} />}
          </button>
          <button onClick={stopTimer}
            className="p-1 rounded-lg hover:bg-red-500/20 text-red-400 transition-colors">
            <Square size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}

function AppShell() {
  const location = useLocation();

  // Request notification permission on mount + set up event/habit reminders
  useEffect(() => {
    requestNotificationPermission();

    // Check for upcoming events every 60s
    const checkReminders = async () => {
      if (!isNotificationsEnabled()) return;
      try {
        const today = format(new Date(), 'yyyy-MM-dd');
        const events = await eventsApi.list({ start_date: today, end_date: today });
        const now = new Date();
        const nowMinutes = now.getHours() * 60 + now.getMinutes();
        events.forEach((e: any) => {
          if (!e.start_time) return;
          const [h, m] = e.start_time.split(':').map(Number);
          const eventMinutes = h * 60 + m;
          const diff = eventMinutes - nowMinutes;
          if (diff > 0 && diff <= 15) {
            notifyEventSoon(e.title, diff);
          }
        });

        // Habit reminders at fixed times
        const habits = await habitsApi.list();
        const completions = await habitsApi.completionsRange(today, today).catch(() => []);
        const completedIds = new Set(completions.map((c: any) => c.habit_id));
        habits.forEach((h: any) => {
          if (completedIds.has(h.id) || !h.fixed_time) return;
          const [hh, mm] = h.fixed_time.split(':').map(Number);
          const habitMinutes = hh * 60 + mm;
          const diff = nowMinutes - habitMinutes;
          if (diff >= 0 && diff <= 5) {
            notifyHabitReminder(h.name, h.icon);
          }
        });
      } catch { /* silent */ }
    };

    checkReminders();
    const interval = setInterval(checkReminders, 60000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex h-screen bg-[#0f0f0f]">
      {/* Sidebar */}
      <aside className="w-64 bg-[#161616] border-r border-[#222] flex flex-col">
        <div className="p-6">
          <h1 className="text-2xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">
            Cristopher
          </h1>
          <p className="text-xs text-gray-500 mt-1">Personal Life Manager</p>
        </div>

        <nav className="flex-1 px-3">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-xl mb-1 transition-all ${
                  isActive
                    ? 'bg-white/10 text-white'
                    : 'text-gray-400 hover:text-white hover:bg-white/5'
                }`
              }
            >
              <Icon size={20} />
              <span className="text-sm font-medium">{label}</span>
            </NavLink>
          ))}
        </nav>

        <MiniTimer />

        <div className="p-4 border-t border-[#222]">
          <p className="text-xs text-gray-600 text-center">v1.0.0</p>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-y-auto">
        <div className="p-8">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/calendar" element={<CalendarPage />} />
            <Route path="/calendar/apps" element={<AppUsagePage />} />
            <Route path="/expenses" element={<ExpensesPage />} />
            <Route path="/lists" element={<ListsPage />} />
            <Route path="/ideas" element={<IdeasPage />} />
            <Route path="/code" element={<CodeActivityPage />} />
            <Route path="/notes" element={<NotesPage />} />
            <Route path="/sleep" element={<SleepPage />} />
            <Route path="/flow" element={<FlowPage />} />
            <Route path="/habits" element={<HabitAnalyticsPage />} />
            <Route path="/screen-time" element={<ScreenTimePage />} />
            <Route path="/lol" element={<LolPage />} />
            <Route path="/investments" element={<InvestmentsPage />} />
            <Route path="/trips" element={<TripsPage />} />
            <Route path="/trips/:id" element={<TripDetail />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
