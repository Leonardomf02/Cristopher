import { Routes, Route, NavLink, useLocation } from 'react-router-dom';
import { Fragment, lazy, Suspense, useEffect, useState } from 'react';
import { pendentes, enviarPendentes } from './outbox';
import { CloudOff, CalendarDays, LayoutDashboard, Calendar, Wallet, Swords, Plane, ListTodo, Moon, Play, Pause, Square, StickyNote, TrendingUp, BarChart3, Code2, Smartphone, Menu, X, Tag, BookOpen, Music, Sun, Bell, Sparkles, Watch, Utensils } from 'lucide-react';
import Dashboard from './pages/Dashboard';

// Cada página só é descarregada quando é aberta. Antes vinha tudo num ficheiro
// de 1.6MB — quem abria a app no telemóvel para apontar um gasto carregava
// também os investimentos, o LoL e a biblioteca de gráficos inteira.
const AskPage = lazy(() => import('./pages/AskPage'));
const CalendarPage = lazy(() => import('./pages/CalendarPage'));
const ExpensesPage = lazy(() => import('./pages/ExpensesPage'));
const LolPage = lazy(() => import('./pages/LolPage'));
const TripsPage = lazy(() => import('./pages/TripsPage'));
const TripDetail = lazy(() => import('./pages/TripDetail'));
const ListsPage = lazy(() => import('./pages/ListsPage'));
const SleepPage = lazy(() => import('./pages/SleepPage'));
const GarminPage = lazy(() => import('./pages/GarminPage'));
const NotesPage = lazy(() => import('./pages/NotesPage'));
const InvestmentsPage = lazy(() => import('./pages/InvestmentsPage'));
const HabitAnalyticsPage = lazy(() => import('./pages/HabitAnalyticsPage'));
const AppUsagePage = lazy(() => import('./pages/AppUsagePage'));
const IdeasPage = lazy(() => import('./pages/IdeasPage'));
const CodeActivityPage = lazy(() => import('./pages/CodeActivityPage'));
const ScreenTimePage = lazy(() => import('./pages/ScreenTimePage'));
const DealsPage = lazy(() => import('./pages/DealsPage'));
const StoriesPage = lazy(() => import('./pages/StoriesPage'));
const SpotifyPage = lazy(() => import('./pages/SpotifyPage'));
const DayPlannerPage = lazy(() => import('./pages/DayPlannerPage'));
const DayPage = lazy(() => import('./pages/DayPage'));
const ScorecardPage = lazy(() => import('./pages/ScorecardPage'));
const MealsPage = lazy(() => import('./pages/MealsPage'));
import { FlowProvider, useFlow } from './FlowContext';
import Login from './Login';
import { getToken } from './auth';
import { requestNotificationPermission, notifyEventSoon, notifyHabitReminder, isNotificationsEnabled } from './notifications';
import { eventsApi, habitsApi, dealsApi, dayPlannerApi } from './api';
import { format } from 'date-fns';
import { applyTheme, getTheme, Theme } from './theme';
import GlobalSearch from './GlobalSearch';
import NotificationsDrawer, { useAvisosCount } from './NotificationsDrawer';

// Ordem por prioridade: o dia primeiro, trabalho a seguir, lazer no fundo.
const navGroups = [
  {
    title: 'Hoje',
    items: [
      { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
      { to: '/calendar', icon: Calendar, label: 'Calendário' },
      { to: '/lists', icon: ListTodo, label: 'Reminders' },
      { to: '/ask', icon: Sparkles, label: 'Perguntar' },
    ],
  },
  {
    title: 'Trabalho',
    items: [
      { to: '/code', icon: Code2, label: 'VS Code' },
      { to: '/notes', icon: StickyNote, label: 'Notas' },
    ],
  },
  {
    title: 'Rotina',
    items: [
      { to: '/habits', icon: BarChart3, label: 'Hábitos' },
      { to: '/meals', icon: Utensils, label: 'Alimentação' },
      { to: '/sleep', icon: Moon, label: 'Sono' },
      { to: '/garmin', icon: Watch, label: 'Relógio' },
      { to: '/screen-time', icon: Smartphone, label: 'Screen Time' },
    ],
  },
  {
    title: 'Dinheiro',
    items: [
      { to: '/expenses', icon: Wallet, label: 'Gastos' },
      { to: '/investments', icon: TrendingUp, label: 'Investimentos' },
      { to: '/deals', icon: Tag, label: 'Deals' },
    ],
  },
  {
    title: 'Lazer',
    items: [
      { to: '/lol', icon: Swords, label: 'LoL Tracker' },
      { to: '/spotify', icon: Music, label: 'Spotify' },
      { to: '/stories', icon: BookOpen, label: 'Histórias' },
      { to: '/trips', icon: Plane, label: 'Viagens' },
    ],
  },
];


// Uma linha para o título de cada grupo e uma por cada par de secções.
const LINHAS_DA_NAV = navGroups
  .flatMap(g => ['auto', ...Array(Math.ceil(g.items.length / 2)).fill('minmax(2rem, 1fr)')])
  .join(' ');

// O que ficou por enviar quando não havia rede (apontar um gasto na rua, marcar
// um bloco do plano). Sai sozinho quando a ligação volta; isto é só para se ver
// que não se perdeu nada.
function PorEnviar() {
  const [n, setN] = useState(() => pendentes().length);
  const [aEnviar, setAEnviar] = useState(false);

  useEffect(() => {
    const ouvir = (e: Event) => setN((e as CustomEvent).detail ?? pendentes().length);
    window.addEventListener('cristopher:outbox', ouvir);
    const t = setInterval(() => setN(pendentes().length), 15000);
    return () => { window.removeEventListener('cristopher:outbox', ouvir); clearInterval(t); };
  }, []);

  if (!n) return <p className="text-xs text-gray-600">v1.0.0</p>;

  return (
    <button
      onClick={async () => { setAEnviar(true); try { await enviarPendentes(); } finally { setAEnviar(false); setN(pendentes().length); } }}
      title={pendentes().map(a => a.descricao).join('\n')}
      className="flex items-center gap-1.5 text-xs text-amber-400 hover:text-amber-300"
    >
      <CloudOff size={13} />
      {aEnviar ? 'a enviar…' : `${n} por enviar`}
    </button>
  );
}


// O título da janela passa a dizer em que secção ele está. O tracker de apps já
// grava o título do separador activo — com isto, e sem infraestrutura nova, a
// app passa a saber onde é que ele gasta as horas dentro dela própria (eram 31h
// registadas apenas como "Cristopher").
const TITULOS: [RegExp, string][] = [
  [/^\/$/, 'Dashboard'],
  [/^\/day/, 'O Dia'],
  [/^\/ask/, 'Perguntar'],
  [/^\/planner/, 'Planear Dia'],
  [/^\/calendar\/apps/, 'Uso de Apps'],
  [/^\/calendar/, 'Calendário'],
  [/^\/lists/, 'Reminders'],
  [/^\/code/, 'VS Code'],
  [/^\/notes/, 'Notas'],
  [/^\/habits/, 'Hábitos'],
  [/^\/sleep/, 'Sono'],
  [/^\/screen-time/, 'Screen Time'],
  [/^\/expenses/, 'Gastos'],
  [/^\/investments/, 'Investimentos'],
  [/^\/deals/, 'Deals'],
  [/^\/lol/, 'LoL'],
  [/^\/spotify/, 'Spotify'],
  [/^\/stories/, 'Histórias'],
  [/^\/trips/, 'Viagens'],
  [/^\/ideas/, 'Ideias'],
  [/^\/acertos/, 'Acertos'],
];

function TituloDaPagina() {
  const { pathname } = useLocation();
  useEffect(() => {
    const encontrado = TITULOS.find(([r]) => r.test(pathname));
    document.title = encontrado ? `${encontrado[1]} · Cristopher` : 'Cristopher';
  }, [pathname]);
  return null;
}

export default function App() {
  // null = a verificar; true = entra; false = mostra login
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    fetch('/api/auth/status')
      .then((r) => r.json())
      .then((d) => { if (alive) setAuthed(!d.auth_required || !!getToken()); })
      .catch(() => { if (alive) setAuthed(true); }); // backend offline → não bloquear dev
    const onUnauth = () => setAuthed(false);
    window.addEventListener('cristopher:unauthorized', onUnauth);
    return () => { alive = false; window.removeEventListener('cristopher:unauthorized', onUnauth); };
  }, []);

  if (authed === null) return null;
  if (!authed) return <Login onSuccess={() => setAuthed(true)} />;

  return (
    <FlowProvider>
      <AppShell />
    </FlowProvider>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => getTheme());

  const toggle = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    applyTheme(next);
  };

  return (
    <button
      onClick={toggle}
      title={theme === 'dark' ? 'Mudar para tema claro' : 'Mudar para tema escuro'}
      className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-gray-400 hover:text-white hover:bg-white/10"
    >
      {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
      {theme === 'dark' ? 'Claro' : 'Escuro'}
    </button>
  );
}

function MiniTimer() {
  const { phase, secondsLeft, isPaused, activePreset, elapsedWorkSeconds, togglePause, stopTimer,
    nota, notaAberta, setNotaAberta, acrescentaNaNota } = useFlow();
  const [texto, setTexto] = useState('');

  // Carregar no bloco transforma-o na nota; Enter guarda a linha e devolve o
  // temporizador. Um painel à parte tirava-o do que estava a fazer.
  const aEscrever = notaAberta && phase !== 'idle' && !!activePreset;
  useEffect(() => { if (!aEscrever) setTexto(''); }, [aEscrever]);

  if (phase === 'idle' || !activePreset) return null;

  // Sem fim: conta para cima, porque um "00:00" parado não diz há quanto tempo
  // ele está nisto.
  const semFim = activePreset.work_minutes <= 0 && phase === 'work';
  const segundos = semFim ? elapsedWorkSeconds : secondsLeft;
  const m = Math.floor(segundos / 60);
  const s = segundos % 60;
  const time = `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;

  return (
    <div
      id="mini-timer"
      onClick={() => setNotaAberta(!notaAberta)}
      title={aEscrever ? 'Voltar ao temporizador' : 'Escrever na nota desta sessão'}
      className="mx-3 mb-2 p-3 rounded-xl border cursor-pointer transition-colors hover:bg-white/5 shrink-0"
      style={{ borderColor: activePreset.color + (aEscrever ? 'aa' : '60'), backgroundColor: activePreset.color + '10' }}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-sm">{activePreset.icon}</span>
        <span className="text-xs font-medium truncate flex-1">{activePreset.name}</span>
        {nota.length > 0 && (
          <span className="flex items-center gap-0.5 text-[10px] text-gray-400" title={`${nota.length} na nota`}>
            <StickyNote size={11} />{nota.length}
          </span>
        )}
        {aEscrever ? (
          <span className="text-[11px] font-mono text-gray-400">{time}</span>
        ) : (
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${
            phase === 'work' ? 'bg-blue-500/20 text-blue-400' : 'bg-green-500/20 text-green-400'
          }`}>
            {phase === 'work' ? (semFim ? 'A CORRER' : 'FOCO') : 'PAUSA'}
          </span>
        )}
      </div>
      {aEscrever ? (
        <input autoFocus value={texto}
          onClick={e => e.stopPropagation()}
          onChange={e => setTexto(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') {
              if (texto.trim()) acrescentaNaNota(texto);
              setNotaAberta(false);
            }
            if (e.key === 'Escape') setNotaAberta(false);
          }}
          placeholder="No que estás agora?"
          className="w-full h-7 bg-[#0f0f0f] border border-[#222] rounded-lg px-2 text-sm outline-none focus:border-[#444]" />
      ) : (
        <div className="flex items-center justify-between h-7">
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
      )}
    </div>
  );
}

function AppShell() {
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [dealsNew, setDealsNew] = useState(0);

  // Fechar drawer ao navegar para outra página (mobile)
  const [avisosOpen, setAvisosOpen] = useState(false);
  const { count: avisos, recarregar: recarregarAvisos } = useAvisosCount();

  // A paleta ⌘K pede a abertura dos avisos por evento (não tem acesso ao estado).
  useEffect(() => {
    const abrir = () => setAvisosOpen(true);
    window.addEventListener('cristopher:avisos', abrir);
    return () => window.removeEventListener('cristopher:avisos', abrir);
  }, []);

  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  // Plano do dia: se hoje ainda não tem plano, gera-o sozinho (uma vez por dia).
  useEffect(() => {
    const hoje = new Date().toISOString().slice(0, 10);
    if (localStorage.getItem('plannerAutoDate') === hoje) return;
    dayPlannerApi.ensureToday()
      .then(() => localStorage.setItem('plannerAutoDate', hoje))
      .catch(() => {});
  }, []);

  // Badge de deals novos (refresca ao navegar e a cada 5 min)
  useEffect(() => {
    const load = () => dealsApi.summary().then(s => setDealsNew(s.new_count)).catch(() => {});
    load();
    const id = setInterval(load, 300000);
    return () => clearInterval(id);
  }, [location.pathname]);

  const currentLabel = navGroups.flatMap(g => g.items).find(n => n.to === location.pathname)?.label
    ?? (location.pathname.startsWith('/trips/') ? 'Viagens' : 'Cristopher');

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
    <div className="flex h-[100dvh] bg-[#0f0f0f] overflow-hidden">
      <GlobalSearch />
      <NotificationsDrawer open={avisosOpen} onClose={() => setAvisosOpen(false)} onChanged={recarregarAvisos} />
      {/* Backdrop em mobile quando o drawer está aberto */}
      {sidebarOpen && (
        <div
          onClick={() => setSidebarOpen(false)}
          className="lg:hidden fixed inset-0 bg-black/60 z-30"
          aria-hidden
        />
      )}

      {/* Sidebar — fixed em mobile (drawer), static em desktop */}
      <aside
        className={`
          bg-[#161616] border-r border-[#222] flex flex-col z-40
          fixed inset-y-0 left-0 w-72 transform transition-transform duration-200
          pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]
          lg:static lg:translate-x-0 lg:pt-0 lg:pb-0
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
        `}
      >
        <div className="p-5 [@media(max-height:820px)]:py-3 flex items-center justify-between shrink-0">
          <div>
            <h1 className="text-2xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">
              Cristopher
            </h1>
            <p className="text-xs text-gray-500 mt-1 [@media(max-height:820px)]:hidden">Personal Life Manager</p>
          </div>
          <button
            onClick={() => setSidebarOpen(false)}
            className="lg:hidden p-2 rounded-lg hover:bg-white/10 text-gray-400"
            aria-label="Fechar menu"
          >
            <X size={20} />
          </button>
        </div>

        {/* Duas colunas, sem scroll, e a encher a barra: cada linha de botões
            leva a mesma fatia da altura que houver (no mínimo 32px). Numa
            coluna só as 18 secções não cabiam sem encolher até ficarem difíceis
            de acertar; com altura fixa sobrava um buraco por baixo nos ecrãs
            altos. Acima de 1000px de altura o ícone vai para cima do nome. */}
        <nav className="flex-1 min-h-0 px-3 pb-2 grid grid-cols-2 gap-x-1 gap-y-1 overflow-hidden"
          style={{ gridTemplateRows: LINHAS_DA_NAV }}>
          {navGroups.map((group, gi) => (
            <Fragment key={group.title}>
              <p className={`col-span-2 px-2.5 pb-0.5 text-[10px] font-bold uppercase tracking-wider text-gray-600 ${
                gi > 0 ? 'mt-1.5 pt-2 border-t border-[#1c1c1c]' : ''
              }`}>{group.title}</p>
              {group.items.map(({ to, icon: Icon, label }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
                  title={label}
                  className={({ isActive }) =>
                    `relative min-h-0 min-w-0 flex items-center gap-1.5 px-2.5 rounded-xl transition-all
                     [@media(min-height:1000px)]:flex-col [@media(min-height:1000px)]:justify-center [@media(min-height:1000px)]:gap-1.5 ${
                      isActive
                        ? 'bg-white/10 text-white'
                        : 'text-gray-400 hover:text-white hover:bg-white/5'
                    }`
                  }
                >
                  <Icon size={16} className="shrink-0 [@media(min-height:1000px)]:w-6 [@media(min-height:1000px)]:h-6" />
                  <span className="text-[13px] font-medium truncate max-w-full">{label}</span>
                  {to === '/deals' && dealsNew > 0 && (
                    <span className="ml-auto shrink-0 text-[10px] font-bold bg-pink-600 text-white rounded-full px-1.5 py-0.5
                      [@media(min-height:1000px)]:absolute [@media(min-height:1000px)]:top-2 [@media(min-height:1000px)]:right-2">{dealsNew}</span>
                  )}
                </NavLink>
              ))}
            </Fragment>
          ))}
        </nav>

        <MiniTimer />

        <div className="p-4 [@media(max-height:820px)]:py-2.5 border-t border-[#222] flex items-center justify-between gap-2 shrink-0">
          <PorEnviar />
          <div className="flex items-center gap-1">
            <button
              onClick={() => setAvisosOpen(true)}
              title="Avisos e resumo da semana"
              className="relative flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-gray-400 hover:text-white hover:bg-white/10"
            >
              <Bell size={14} />
              Avisos
              {avisos > 0 && (
                <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center">
                  {avisos}
                </span>
              )}
            </button>
            <ThemeToggle />
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-y-auto overflow-x-hidden flex flex-col min-w-0">
        {/* Top bar (apenas mobile) */}
        {/* O padding de cima conta com a zona do relógio/ilha do iPhone: instalada
            no ecrã principal, a app ocupa o ecrã todo e o botão do menu ficava
            por baixo das horas, sem forma de sair da página. */}
        <header className="lg:hidden sticky top-0 z-20 bg-[#0f0f0f]/95 backdrop-blur border-b border-[#222] flex items-center gap-3 px-3 pb-3 pt-[calc(env(safe-area-inset-top)_+_1rem)]">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-2 rounded-lg hover:bg-white/10 text-gray-300"
            aria-label="Abrir menu"
          >
            <Menu size={22} />
          </button>
          <h2 className="text-base font-semibold truncate">{currentLabel}</h2>
          <button
            onClick={() => setAvisosOpen(true)}
            title="Avisos"
            className="relative ml-auto p-2 rounded-lg hover:bg-white/10 text-gray-300"
          >
            <Bell size={18} />
            {avisos > 0 && (
              <span className="absolute top-1 right-1 min-w-[15px] h-[15px] px-1 rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center">
                {avisos}
              </span>
            )}
          </button>
        </header>

        <div className="p-3 sm:p-5 lg:p-8 flex-1 min-w-0">
          <TituloDaPagina />
          <Suspense fallback={<div className="text-sm text-gray-600 py-10 text-center">a carregar…</div>}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/ask" element={<AskPage />} />
            <Route path="/planner" element={<DayPlannerPage />} />
            {/* Fora do menu: os números do dia passaram para o Planear Dia. A
                rota fica porque o painel de avisos manda para a linha do tempo
                de um dia concreto ("ontem dormiste 2.6h — o que aconteceu?"). */}
            <Route path="/day" element={<DayPage />} />
            <Route path="/day/:date" element={<DayPage />} />
            <Route path="/acertos" element={<ScorecardPage />} />
            <Route path="/calendar" element={<CalendarPage />} />
            <Route path="/calendar/apps" element={<AppUsagePage />} />
            <Route path="/expenses" element={<ExpensesPage />} />
            <Route path="/lists" element={<ListsPage />} />
            <Route path="/ideas" element={<IdeasPage />} />
            <Route path="/code" element={<CodeActivityPage />} />
            <Route path="/notes" element={<NotesPage />} />
            <Route path="/stories" element={<StoriesPage />} />
            <Route path="/spotify" element={<SpotifyPage />} />
            <Route path="/sleep" element={<SleepPage />} />
            <Route path="/garmin" element={<GarminPage />} />
            <Route path="/habits" element={<HabitAnalyticsPage />} />
            <Route path="/meals" element={<MealsPage />} />
            <Route path="/screen-time" element={<ScreenTimePage />} />
            <Route path="/lol" element={<LolPage />} />
            <Route path="/investments" element={<InvestmentsPage />} />
            <Route path="/trips" element={<TripsPage />} />
            <Route path="/trips/:id" element={<TripDetail />} />
            <Route path="/deals" element={<DealsPage />} />
          </Routes>
          </Suspense>
        </div>
      </main>
    </div>
  );
}
