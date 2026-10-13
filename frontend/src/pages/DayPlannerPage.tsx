import { useEffect, useRef, useState } from 'react';
import {
  Plus, Pencil, Trash2, Sparkles, Clock, X, AlertTriangle,
  Play, GripVertical, Check, CalendarCheck, ChevronLeft, ChevronRight,
} from 'lucide-react';
import { format } from 'date-fns';
import { pt } from 'date-fns/locale';
import { dayApi, dayPlannerApi, DayActivity, DayPlan, DayPlanSummary, DaySummary, DayWindow, PlanBlock, ProductiveHours } from '../api';
import { useFlow } from '../FlowContext';

/** Duração do bloco em minutos (trata blocos que passam da meia-noite). */
function blockMinutes(b: PlanBlock): number {
  const [sh, sm] = b.start.split(':').map(Number);
  const [eh, em] = b.end.split(':').map(Number);
  let mins = eh * 60 + em - (sh * 60 + sm);
  if (mins <= 0) mins += 24 * 60;
  return mins;
}

function fmtMins(m: number): string {
  if (m < 60) return `${m}min`;
  const h = Math.floor(m / 60), r = m % 60;
  return r ? `${h}h${String(r).padStart(2, '0')}` : `${h}h`;
}

const toMin = (hhmm: string) => { const [h, m] = hhmm.split(':').map(Number); return h * 60 + m; };
const toHHMM = (mins: number) => {
  const m = ((mins % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
};

/** Índices dos blocos que se sobrepõem ao anterior (só acontece após edição manual). */
function overlapping(blocks: PlanBlock[], wakeTime: string): Set<number> {
  const wake = toMin(wakeTime);
  const abs = (t: string) => { const m = toMin(t); return m < wake ? m + 24 * 60 : m; };
  const out = new Set<number>();
  for (let i = 1; i < blocks.length; i++) {
    if (abs(blocks[i].start) < abs(blocks[i - 1].start) + blockMinutes(blocks[i - 1])) out.add(i);
  }
  return out;
}

/** O relógio está dentro deste bloco agora? */
function containsNow(b: PlanBlock, now: number): boolean {
  const s = toMin(b.start), e = toMin(b.end);
  return e > s ? now >= s && now < e : now >= s || now < e;   // e < s ⇒ passa da meia-noite
}

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** "14 de agosto de 2026" — o dia por extenso, que é o que se lê no cabeçalho.
 *  O `dateLabel` continua a ser o curto, para as listas e os avisos. */
function dataPorExtenso(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  return format(new Date(y, m - 1, d), "d 'de' MMMM 'de' yyyy", { locale: pt });
}

function dateLabel(iso: string): string {
  const t = todayStr();
  if (iso === t) return 'Hoje';
  const y = new Date(); y.setDate(y.getDate() - 1);
  const yStr = `${y.getFullYear()}-${String(y.getMonth() + 1).padStart(2, '0')}-${String(y.getDate()).padStart(2, '0')}`;
  if (iso === yStr) return 'Ontem';
  const [yy, mm, dd] = iso.split('-');
  return `${dd}/${mm}/${yy}`;
}

const WINDOW_LABELS: Record<DayWindow, string> = {
  any: 'Qualquer hora',
  produtivo: 'Quando rendo mais',
  morning: 'De manhã',
  afternoon: 'À tarde',
  evening: 'À noite',
  before_lunch: 'Antes do almoço',
  after_lunch: 'Depois do almoço',
};

const PRIORITY_LABELS = ['Baixa', 'Normal', 'Alta', 'Essencial'];
const PRIORITY_COLORS = ['#6B7280', '#3B82F6', '#F59E0B', '#EF4444'];
// O amarelo/laranja não se lê em fundo claro; no tema claro usa-se o tom escuro.
const PRIORITY_COLORS_LIGHT = ['#475569', '#1d4ed8', '#b45309', '#b91c1c'];

function fmtDur(min: number, max: number | null): string {
  const h = (n: number) => (n % 60 === 0 ? `${n / 60}h` : n >= 60 ? `${Math.floor(n / 60)}h${n % 60}` : `${n}min`);
  return max ? `${h(min)}–${h(max)}` : h(min);
}

const EMPTY: Partial<DayActivity> = {
  name: '', icon: '⏱️', color: '#3B82F6', duration_min: 60, duration_max: null,
  window: 'any', fixed_time: null, priority: 1, splittable: false, chunk_max: null, enabled: true,
};

const card = 'rounded-3xl border border-white/[0.07] bg-white/[0.025] backdrop-blur-xl';
const field = 'rounded-xl border border-white/10 bg-black/40 px-3 py-2 outline-none transition ' +
  'focus:border-blue-500/50 focus:ring-2 focus:ring-blue-500/20';
const chip = 'rounded-full bg-white/[0.06] px-2 py-0.5 text-[11px] text-gray-400';

function priorityColor(priority: number): string {
  const light = document.documentElement.getAttribute('data-theme') === 'light';
  return (light ? PRIORITY_COLORS_LIGHT : PRIORITY_COLORS)[priority] || PRIORITY_COLORS[1];
}

export default function DayPlannerPage() {
  const [activities, setActivities] = useState<DayActivity[]>([]);
  const [preferences, setPreferences] = useState(() => localStorage.getItem('planner_prefs') || '');
  const [plan, setPlan] = useState<DayPlan | null>(null);
  const [planning, setPlanning] = useState<'' | 'local' | 'ai'>('');
  const [error, setError] = useState('');
  const [editing, setEditing] = useState<Partial<DayActivity> | null>(null);
  const [editingBlock, setEditingBlock] = useState<{ index: number; block: PlanBlock } | null>(null);
  const [addingBlock, setAddingBlock] = useState(false);
  const [history, setHistory] = useState<DayPlanSummary[]>([]);
  const [viewDate, setViewDate] = useState(todayStr());
  const [verDias, setVerDias] = useState(false);
  // Os números do dia (sono, código, ecrã, jogos, gastos, humor) viviam numa
  // página só deles; é aqui, ao lado do plano, que dizem alguma coisa.
  const [dia, setDia] = useState<DaySummary | null>(null);

  // Relógio, para marcar o bloco em curso. Acerta ao minuto.
  const [now, setNow] = useState(() => { const d = new Date(); return d.getHours() * 60 + d.getMinutes(); });
  useEffect(() => {
    const id = setInterval(() => { const d = new Date(); setNow(d.getHours() * 60 + d.getMinutes()); }, 30000);
    return () => clearInterval(id);
  }, []);

  const { startTimer, activePreset, phase } = useFlow();

  const load = () => dayPlannerApi.list().then(setActivities).catch(() => {});
  const loadHistory = () => dayPlannerApi.history().then(setHistory).catch(() => {});

  // Qual o bloco a correr — persistido para sobreviver à navegação (o timer é global)
  const [running, setRunning] = useState<{ date: string; index: number } | null>(
    () => { try { return JSON.parse(localStorage.getItem('planner_running') || 'null'); } catch { return null; } }
  );

  useEffect(() => {
    if (phase === 'idle' && running) { localStorage.removeItem('planner_running'); setRunning(null); }
  }, [phase]);

  const startBlock = (b: PlanBlock, i: number) => {
    const dur = blockMinutes(b);
    if (dur <= 0 || !plan?.plan_date) return;
    startTimer({ id: 0, name: b.name, work_minutes: dur, break_minutes: dur >= 90 ? 10 : 5, color: b.color, icon: b.icon });
    const r = { date: plan.plan_date, index: i };
    localStorage.setItem('planner_running', JSON.stringify(r));
    setRunning(r);
  };

  const isRunning = (i: number) =>
    phase !== 'idle' && !!activePreset && running?.index === i && running?.date === plan?.plan_date;

  const toggleDone = async (i: number) => {
    if (!plan?.plan_date) return;
    setPlan(await dayPlannerApi.toggleBlock(plan.plan_date, i));
  };

  // Editar/eliminar reordena os blocos → o marcador de "a correr" deixa de ser fiável
  const clearRunning = () => { localStorage.removeItem('planner_running'); setRunning(null); };

  const saveBlock = async (i: number, data: { name: string; start: string; end: string; note: string }) => {
    if (!plan?.plan_date) return;
    try {
      setPlan(await dayPlannerApi.updateBlock(plan.plan_date, i, data));
      clearRunning();
      setEditingBlock(null);
    } catch (e: any) { setError(e.message || 'Não deu para guardar'); }
  };

  const addBlock = async (data: { name: string; icon: string; color: string; start: string; end: string; note: string }) => {
    try {
      setPlan(await dayPlannerApi.addBlock(viewDate, data));
      setAddingBlock(false);
      loadHistory();          // pode ter nascido um plano novo neste dia
    } catch (e: any) { setError(e.message || 'Não deu para adicionar'); }
  };

  const delBlock = async (i: number) => {
    if (!plan?.plan_date || !confirm(`Eliminar "${plan.blocks[i].name}" do plano?`)) return;
    setPlan(await dayPlannerApi.deleteBlock(plan.plan_date, i));
    clearRunning();
  };

  const moveBlock = async (from: number, to: number) => {
    if (!plan?.plan_date || from === to) return;
    try {
      setPlan(await dayPlannerApi.reorderBlock(plan.plan_date, from, to));
      clearRunning();
    } catch (e: any) { setError(e.message || 'Não deu para mover'); }
  };

  // ── Arrastar blocos (rato: pega no ⠿; dedo/rato: long-press na linha) ──
  const rowRefs = useRef<(HTMLDivElement | null)[]>([]);
  const dragRef = useRef<{ from: number; startY: number; timer?: number; active: boolean; activate: () => void } | null>(null);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragDy, setDragDy] = useState(0);
  const [dropIndex, setDropIndex] = useState<number | null>(null);

  const onPointerDown = (e: React.PointerEvent, i: number, fromHandle: boolean) => {
    if (e.button !== 0) return;
    // long-press na linha não deve roubar cliques aos botões/checkbox
    if (!fromHandle && (e.target as HTMLElement).closest('button, input')) return;

    const el = e.currentTarget as HTMLElement;
    const pointerId = e.pointerId;
    const activate = () => {
      el.setPointerCapture?.(pointerId);   // só capturamos quando o drag arranca mesmo
      if (dragRef.current) dragRef.current.active = true;
      setDragIndex(i);
      setDropIndex(i);
      navigator.vibrate?.(10);
    };
    dragRef.current = { from: i, startY: e.clientY, active: false, activate };
    if (fromHandle) activate();
    else dragRef.current.timer = window.setTimeout(() => dragRef.current?.activate(), 350);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const st = dragRef.current;
    if (!st) return;
    const dy = e.clientY - st.startY;
    if (!st.active) {                       // ainda em long-press: se scrollar, cancela
      if (Math.abs(dy) > 8) { clearTimeout(st.timer); dragRef.current = null; }
      return;
    }
    e.preventDefault();
    setDragDy(dy);
    // a linha arrastada acompanha o cursor — ignorá-la, senão apanhava sempre o hit
    const hit = rowRefs.current.findIndex((r, k) => {
      if (!r || k === st.from) return false;
      const b = r.getBoundingClientRect();
      return e.clientY >= b.top && e.clientY <= b.bottom;
    });
    if (hit >= 0) setDropIndex(hit);
  };

  const onPointerUp = () => {
    const st = dragRef.current;
    if (st) clearTimeout(st.timer);
    if (st?.active && dropIndex !== null) moveBlock(st.from, dropIndex);
    dragRef.current = null;
    setDragIndex(null);
    setDragDy(0);
    setDropIndex(null);
  };

  useEffect(() => {
    load();
    loadHistory();
    dayApi.get(todayStr()).then(setDia).catch(() => setDia(null));
    dayPlannerApi.getPlan(todayStr()).then(setPlan).catch(() => {});   // o plano de hoje, se já existir
  }, []);

  const viewSaved = async (date: string) => {
    setViewDate(date);
    setError('');
    try {
      setPlan(await dayPlannerApi.getPlan(date));
    } catch { if (date !== todayStr()) setPlan(null); }   // hoje sem plano guardado: mantém o gerado
  };

  const delPlan = async (date: string) => {
    if (!confirm(`Apagar o plano de ${dateLabel(date)}?`)) return;
    await dayPlannerApi.deletePlan(date);
    await loadHistory();
    setViewDate(todayStr());
    dayPlannerApi.getPlan(todayStr()).then(setPlan).catch(() => setPlan(null));
  };

  const doPlan = async (mode: 'local' | 'ai') => {
    setPlanning(mode);
    setError('');
    if (mode === 'ai') localStorage.setItem('planner_prefs', preferences);
    try {
      const res = await dayPlannerApi.plan({
        mode, preferences: mode === 'ai' ? preferences || undefined : undefined,
      });
      setPlan(res);
      setViewDate(todayStr());
      loadHistory();
    } catch (e: any) {
      setError(e.message || 'Falhou');
    } finally {
      setPlanning('');
    }
  };

  const toggleEnabled = async (a: DayActivity) => {
    await dayPlannerApi.update(a.id, { enabled: !a.enabled });
    load();
  };

  const saveEdit = async () => {
    if (!editing || !editing.name?.trim()) return;
    const payload = { ...editing, duration_max: editing.duration_max || null, fixed_time: editing.fixed_time || null };
    if (editing.id) await dayPlannerApi.update(editing.id, payload);
    else await dayPlannerApi.create(payload);
    setEditing(null);
    load();
  };

  const del = async (id: number) => {
    if (!confirm('Apagar atividade?')) return;
    await dayPlannerApi.remove(id);
    load();
  };

  const overlaps = plan ? overlapping(plan.blocks, plan.wake_time) : new Set<number>();
  const isToday = viewDate === todayStr();

  const doneCount = plan?.blocks.filter(b => b.done).length ?? 0;

  return (
    <div className="mx-auto max-w-6xl pb-12 lg:flex lg:h-[calc(100dvh-4rem)] lg:flex-col lg:overflow-hidden lg:pb-0">
      {/* Cabeçalho como o resto da app (Sono, Gastos, Ecrã): título grande à
          esquerda — que aqui é o dia —, botões à direita, e por baixo a linha do
          que a app mediu. Antes era um cartão com cinco coisas na mesma fila, que
          se partia onde calhava e mandava os botões para uma linha só deles. E
          antes disso eram dois cartões altos com um logo grande: 300px que
          faltavam ao horário, que é o que importa ver inteiro. */}
      <div className="mb-4 shrink-0 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">

          {/* O dia que se está a ver, por extenso e à vista. A seta para trás
              abre a lista dos dias guardados — era um `select` de 150px onde não
              se percebia sequer que dia estava aberto. */}
          <div className="relative -ml-1.5 flex items-center gap-0.5">
            <button onClick={() => setVerDias(v => !v)} title="Dias anteriores"
              className="rounded-lg p-1 text-gray-400 transition hover:bg-white/10 hover:text-white">
              <ChevronLeft size={20} />
            </button>
            <button onClick={() => setVerDias(v => !v)}
              className="rounded-lg px-1.5 py-0.5 text-2xl font-bold tracking-tight transition hover:bg-white/5">
              {dataPorExtenso(viewDate)}
              {isToday && (
                <span className="ml-2 rounded-full bg-amber-400/15 px-2 py-0.5 text-[11px] font-medium text-amber-300">
                  hoje
                </span>
              )}
            </button>
            {!isToday && (
              <button onClick={() => { setVerDias(false); viewSaved(todayStr()); }} title="Voltar a hoje"
                className="rounded-lg p-1.5 text-gray-400 transition hover:bg-white/10 hover:text-white">
                <ChevronRight size={18} />
              </button>
            )}

            {verDias && (
              <>
                <div className="fixed inset-0 z-30" onClick={() => setVerDias(false)} />
                <div className="absolute left-0 top-full z-40 mt-2 max-h-[60vh] w-64 overflow-y-auto
                  rounded-2xl border border-[#222] bg-[#161616] py-1.5 shadow-2xl">
                  {!history.some(h => h.plan_date === todayStr()) && (
                    <button onClick={() => { setVerDias(false); viewSaved(todayStr()); }}
                      className="flex w-full items-center justify-between px-3.5 py-2 text-sm hover:bg-white/5">
                      <span>Hoje</span>
                      <span className="text-[11px] text-gray-600">por planear</span>
                    </button>
                  )}
                  {history.map(h => (
                    <button key={h.plan_date} onClick={() => { setVerDias(false); viewSaved(h.plan_date); }}
                      className={`flex w-full items-center justify-between px-3.5 py-2 text-sm transition hover:bg-white/5 ${
                        h.plan_date === viewDate ? 'bg-white/[0.06] text-white' : 'text-gray-300'}`}>
                      <span className="truncate">{dataPorExtenso(h.plan_date)}</span>
                      <span className="ml-2 shrink-0 text-[11px] text-gray-600">
                        {h.block_count} blocos · {h.mode === 'ai' ? 'IA' : 'local'}
                      </span>
                    </button>
                  ))}
                  {history.length === 0 && (
                    <p className="px-3.5 py-3 text-sm text-gray-600">Ainda não há dias guardados.</p>
                  )}
                </div>
              </>
            )}
          </div>

          </div>

          <div className="flex shrink-0 items-center gap-2">
            <button onClick={() => doPlan('local')} disabled={!!planning}
              className={`${field} flex items-center gap-2 border-white/10 bg-white/[0.06] px-4 py-2 text-sm font-medium
                hover:bg-white/[0.1] active:scale-[0.98] disabled:opacity-40`}>
              <Clock size={16} className={planning === 'local' ? 'animate-spin' : ''} />
              {planning === 'local' ? 'A planear…' : 'Planear'}
            </button>
            <button onClick={() => doPlan('ai')} disabled={!!planning}
              className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-600 px-4 py-2
                text-sm font-medium shadow-lg shadow-fuchsia-600/25 transition hover:shadow-fuchsia-600/40 active:scale-[0.98] disabled:opacity-40">
              <Sparkles size={16} className={planning === 'ai' ? 'animate-pulse' : ''} />
              {planning === 'ai' ? 'A pensar…' : 'Planear com IA'}
            </button>
          </div>
        </div>

      {/* Como correu o dia até agora — a mesma fila de números que estava na
          página "O Dia", que deixou de existir. */}
      {dia && (
          <div className={`mb-3 shrink-0 ${card} grid grid-cols-3 gap-x-5 gap-y-3 px-5 py-3 sm:grid-cols-6`}>
            <Numero titulo="Sono" valor={dia.summary.sleep_hours ? `${dia.summary.sleep_hours}h` : '—'}
              sub={dia.summary.bedtime && dia.summary.wake_time
                ? `${dia.summary.bedtime}–${dia.summary.wake_time}` : 'sem registo'} />
            <Numero titulo="Código" valor={dia.summary.code_seconds ? fmtMins(Math.round(dia.summary.code_seconds / 60)) : '—'}
              sub={dia.summary.top_projects[0]?.name || 'nada'} />
            <Numero titulo="Ecrã" valor={dia.summary.screen_seconds ? fmtMins(Math.round(dia.summary.screen_seconds / 60)) : '—'}
              sub={`${dia.timeline.filter(i => i.kind === 'screen').length} blocos`} />
            <Numero titulo="Jogos" valor={dia.summary.games ? String(dia.summary.games) : '—'}
              sub={dia.summary.games ? `${dia.summary.wins}W-${dia.summary.games - dia.summary.wins}L` : 'nenhum'} />
            <Numero titulo="Gastos" valor={dia.summary.spent ? `€${dia.summary.spent.toFixed(0)}` : '—'}
              sub={dia.summary.notes ? `${dia.summary.notes} notas` : '—'} />
            <Numero titulo="Humor" valor={dia.summary.mood ? `${dia.summary.mood}/10` : '—'}
              sub={dia.summary.music_seconds ? `${fmtMins(Math.round(dia.summary.music_seconds / 60))} música` : '—'} />
          </div>
      )}

      {error && (
        <div className="mb-4 rounded-xl border border-red-500/25 bg-red-500/10 px-3.5 py-2.5 text-sm text-red-300">{error}</div>
      )}

      {/* As duas colunas têm a mesma altura — a da janela — e é dentro de cada
          uma que se rola. Com a altura a vir do conteúdo, o lado das atividades
          e o do horário acabavam em sítios diferentes e a página ficava torta. */}
      <div className="grid gap-6 lg:min-h-0 lg:flex-1 lg:gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        {/* Atividades, e por baixo o que ele quer do dia — os dois esticam para
            encher a coluna, em vez de deixarem meia página vazia. */}
        <section className="flex flex-col gap-3 lg:min-h-0">
          <div className="flex flex-col lg:min-h-0 lg:flex-[3]">
          <div className="mb-2 flex items-center justify-between shrink-0">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-500">Atividades</h2>
            <button onClick={() => setEditing({ ...EMPTY })}
              className="flex items-center gap-1.5 rounded-full bg-white/[0.06] px-3 py-1.5 text-sm transition hover:bg-white/[0.12] active:scale-95">
              <Plus size={15} /> Nova
            </button>
          </div>

          {/* Uma atividade é uma linha só: o nome e as etiquetas lado a lado.
              Com as etiquetas por baixo do nome, sete atividades não cabiam na
              coluna e obrigavam a rolar para ver a lista toda. */}
          {/* As linhas repartem a altura do cartão entre si: amontoadas em cima
              deixavam metade do cartão vazia. */}
          <div className={`flex flex-col gap-1.5 p-2 ${card} lg:min-h-0 lg:flex-1 lg:overflow-y-auto`}>
            {activities.map(a => (
              <div key={a.id}
                className={`group relative flex items-center gap-2.5 overflow-hidden rounded-xl border border-white/[0.06]
                  bg-white/[0.02] px-2.5 transition hover:bg-white/[0.04] lg:min-h-[46px] lg:max-h-[70px] lg:flex-1
                  py-2.5 ${a.enabled ? '' : 'opacity-40'}`}>
                <span className="absolute inset-y-0 left-0 w-[3px] rounded-r"
                  style={{ background: a.enabled ? a.color : 'transparent', boxShadow: a.enabled ? `0 0 12px ${a.color}66` : undefined }} />
                <input type="checkbox" checked={a.enabled} onChange={() => toggleEnabled(a)}
                  className="ml-1 h-4 w-4 shrink-0 accent-blue-500" />
                <span className="shrink-0 text-lg leading-none">{a.icon}</span>
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{a.name}</span>
                <div className="flex shrink-0 items-center gap-1.5">
                  <span className={chip}>{fmtDur(a.duration_min, a.duration_max)}</span>
                  <span className={`${chip} hidden sm:inline`}>{WINDOW_LABELS[a.window]}</span>
                  {a.fixed_time && <span className={`${chip} tabular-nums hidden md:inline`}>🕒 {a.fixed_time}</span>}
                  {a.splittable && <span className={`${chip} hidden md:inline`}>✂️</span>}
                  <span className="rounded-full px-2 py-0.5 text-[11px] font-medium"
                    style={{ color: priorityColor(a.priority), background: PRIORITY_COLORS[a.priority] + '1a' }}>
                    {PRIORITY_LABELS[a.priority]}
                  </span>
                </div>
                <div className="flex shrink-0 gap-0.5 sm:opacity-0 sm:transition sm:group-hover:opacity-100">
                  <button onClick={() => setEditing(a)} className="rounded-lg p-1.5 text-gray-400 transition hover:bg-white/10 hover:text-white"><Pencil size={15} /></button>
                  <button onClick={() => del(a.id)} className="rounded-lg p-1.5 text-gray-400 transition hover:bg-red-500/15 hover:text-red-400"><Trash2 size={15} /></button>
                </div>
              </div>
            ))}
            {activities.length === 0 && (
              <p className="py-10 text-center text-sm text-gray-600">Sem atividades. Cria a primeira.</p>
            )}
          </div>
          </div>

          {/* O que ele quer do dia fica sempre à vista: é a nota que manda no
              plano da IA, e escondida atrás de um botão não era relida nem
              corrigida. */}
          <div className="flex flex-col lg:min-h-[130px] lg:flex-[1]">
            <div className="mb-2 flex items-baseline justify-between gap-2 shrink-0">
              <h2 className="flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wider text-gray-500">
                <Sparkles size={13} className="text-violet-400" /> Como queres o dia
              </h2>
              <span className="text-[11px] text-gray-600">vai para a IA</span>
            </div>
            <textarea value={preferences}
              onChange={e => { setPreferences(e.target.value); localStorage.setItem('planner_prefs', e.target.value); }}
              placeholder="Ex: gosto de trabalhar um bocado de manhã antes do gym; nada de LoL antes de jantar…"
              className={`${card} w-full resize-none p-3 text-sm leading-relaxed outline-none transition
                placeholder:text-gray-600 focus:border-violet-500/40 lg:min-h-0 lg:flex-1`} />
          </div>
        </section>

        {/* Horário */}
        <section className="flex flex-col lg:min-h-0">
          <div className="mb-2 flex items-center justify-between gap-2 shrink-0">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-500">
              Horário{isToday ? '' : ` · ${dateLabel(viewDate)}`}
            </h2>
            <div className="flex items-center gap-1.5">
              <button onClick={() => setAddingBlock(true)} title="Adicionar bloco solto ao horário"
                className="flex items-center gap-1.5 rounded-full bg-white/[0.06] px-3 py-1.5 text-sm transition hover:bg-white/[0.12] active:scale-95">
                <Plus size={15} /> Bloco
              </button>
            </div>
          </div>

          {/* A coluna é uma pilha que estica: o cartão do horário fica com o
              espaço que sobrar, em vez de acabar a meio e deixar vazio. */}
          <div className="flex flex-col gap-3 lg:min-h-0 lg:flex-1">
          {!plan && (
            <div className={`${card} flex flex-col items-center justify-center border-dashed px-6 py-14 text-center lg:min-h-0 lg:flex-1`}>
              <Clock size={30} className="mx-auto mb-3 text-gray-700" />
              <p className="text-sm text-gray-600">
                Carrega em <b className="text-gray-400">Planear</b> para ver o teu dia,
                <br />ou junta um <b className="text-gray-400">Bloco</b> à mão.
              </p>
            </div>
          )}

          {plan && (
            <div className="flex flex-col gap-3 lg:min-h-0 lg:flex-1">
              {!isToday && (
                <div className="flex shrink-0 items-center justify-between rounded-2xl bg-white/[0.04] px-3.5 py-2.5 text-xs text-gray-400">
                  <span>Guardado de <b className="text-gray-200">{dateLabel(viewDate)}</b> · acordou às <span className="tabular-nums">{plan.wake_time}</span></span>
                  <button onClick={() => delPlan(viewDate)} className="flex items-center gap-1 text-red-400 transition hover:text-red-300">
                    <Trash2 size={13} /> Apagar
                  </button>
                </div>
              )}

              {plan.advice && (
                <div className="flex shrink-0 gap-2.5 rounded-2xl border border-violet-500/20 bg-gradient-to-br from-violet-500/[0.12] to-fuchsia-500/[0.06] px-3.5 py-2.5 text-sm text-violet-100">
                  <Sparkles size={16} className="mt-0.5 shrink-0 text-violet-400" />
                  <span className="leading-relaxed">{plan.advice}</span>
                </div>
              )}

              <div className={`relative flex flex-col ${card} p-1.5 lg:min-h-0 lg:flex-1 lg:overflow-y-auto`}>
                {plan.blocks.map((b, i) => {
                  const clash = overlaps.has(i);
                  const dragging = dragIndex === i;
                  const isDropTarget = dragIndex !== null && dropIndex === i && !dragging;
                  const live = isToday && containsNow(b, now) && !b.done;
                  const last = i === plan.blocks.length - 1;

                  return (
                    <div key={i}
                      ref={el => { rowRefs.current[i] = el; }}
                      onPointerDown={e => onPointerDown(e, i, false)}
                      onPointerMove={onPointerMove}
                      onPointerUp={onPointerUp}
                      onPointerCancel={onPointerUp}
                      style={{
                        transform: dragging ? `translateY(${dragDy}px)` : undefined,
                        touchAction: dragIndex !== null ? 'none' : undefined,
                      }}
                      className={`group relative flex select-none items-center gap-2 rounded-2xl px-2 py-2.5 sm:gap-3
                        lg:min-h-[46px] lg:max-h-[70px] lg:flex-1 ${
                        dragging
                          ? 'z-20 bg-[#1c1c1c] shadow-2xl ring-1 ring-blue-500/50 cursor-grabbing'
                          : 'transition hover:bg-white/[0.03]'
                      } ${isDropTarget ? 'bg-blue-500/[0.12] ring-1 ring-blue-500/30' : ''} ${
                        isRunning(i) ? 'bg-blue-500/[0.08]' : ''} ${b.done ? 'opacity-45' : ''}`}>

                      <button onPointerDown={e => { e.stopPropagation(); onPointerDown(e, i, true); }}
                        onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
                        title="Arrastar para mover" style={{ touchAction: 'none' }}
                        className="cursor-grab p-0.5 text-gray-700 transition hover:text-gray-300 active:cursor-grabbing sm:opacity-0 sm:group-hover:opacity-100">
                        <GripVertical size={14} />
                      </button>

                      <button onClick={() => toggleDone(i)} title={b.done ? 'Desmarcar' : 'Marcar como feito'}
                        className={`grid h-5 w-5 shrink-0 place-items-center rounded-full border transition active:scale-90 ${
                          b.done
                            ? 'border-emerald-400/60 bg-emerald-500 text-black shadow-[0_0_10px] shadow-emerald-500/40'
                            : 'border-white/20 hover:border-emerald-400/60 hover:bg-emerald-500/10'}`}>
                        {b.done && <Check size={12} strokeWidth={3.5} />}
                      </button>

                      <div className={`flex w-[86px] shrink-0 items-center gap-1 text-[13px] tabular-nums ${b.done ? 'text-gray-600' : 'text-gray-400'}`}>
                        {clash && <AlertTriangle size={11} className="shrink-0 text-amber-400" aria-label="Sobrepõe o bloco anterior" />}
                        <span>{b.start}–{b.end}</span>
                      </div>

                      {/* rail + ponto — com as linhas a esticar, o traço tem de
                          ir de centro a centro, senão fica um buraco entre eles */}
                      <div className="relative flex w-3 shrink-0 justify-center self-stretch">
                        <span className={`absolute w-px bg-white/[0.08] ${i === 0 ? 'top-1/2' : 'top-0'} ${last ? 'bottom-1/2' : 'bottom-0'}`} />
                        <span className="relative z-10 h-2.5 w-2.5 shrink-0 self-center rounded-full ring-4 ring-[#101010]"
                          style={{ background: b.color, boxShadow: live ? `0 0 14px ${b.color}` : undefined }} />
                      </div>

                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-[15px]">{b.icon}</span>
                          <span className={`truncate font-medium ${b.done ? 'text-gray-500 line-through' : ''}`}>{b.name}</span>
                          <span className="shrink-0 text-[11px] text-gray-600">{fmtMins(blockMinutes(b))}</span>
                          {live && (
                            <span className="shrink-0 rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[9px] font-bold tracking-wide text-emerald-400">
                              AGORA
                            </span>
                          )}
                        </div>
                        {b.note && <div className="mt-0.5 truncate text-xs text-gray-600">{b.note}</div>}
                      </div>

                      {isRunning(i) ? (
                        <span className="flex shrink-0 items-center gap-1.5 rounded-full bg-blue-500/15 px-2.5 py-1 text-[10px] font-bold tracking-wide text-blue-400">
                          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400" /> A CORRER
                        </span>
                      ) : (
                        <button onClick={() => startBlock(b, i)} disabled={phase !== 'idle' || b.done}
                          title={phase !== 'idle' ? 'Já tens um flow a correr' : 'Iniciar flow'}
                          className="shrink-0 rounded-lg p-1.5 text-gray-500 transition hover:bg-white/10 hover:text-white
                            disabled:opacity-25 disabled:hover:bg-transparent">
                          <Play size={15} />
                        </button>
                      )}

                      <div className="flex shrink-0 gap-0.5 sm:opacity-0 sm:transition sm:group-hover:opacity-100">
                        <button onClick={() => setEditingBlock({ index: i, block: b })} title="Alterar horas"
                          className="rounded-lg p-1.5 text-gray-500 transition hover:bg-white/10 hover:text-white"><Pencil size={14} /></button>
                        <button onClick={() => delBlock(i)} title="Eliminar do plano"
                          className="rounded-lg p-1.5 text-gray-500 transition hover:bg-red-500/15 hover:text-red-400"><Trash2 size={14} /></button>
                      </div>
                    </div>
                  );
                })}
              </div>

              {doneCount > 0 && (
                <p className="flex shrink-0 items-center gap-1.5 px-1 text-xs text-emerald-500/70">
                  <CalendarCheck size={13} /> Os blocos feitos aparecem no calendário.
                </p>
              )}

              {overlaps.size > 0 && (
                <p className="flex shrink-0 items-center gap-1.5 px-1 text-xs text-amber-400/80">
                  <AlertTriangle size={13} /> Há blocos sobrepostos depois das tuas alterações.
                </p>
              )}

              {plan.unplaced.length > 0 && (
                <div className="shrink-0 rounded-2xl border border-amber-500/20 bg-amber-500/[0.07] px-3.5 py-3 text-sm">
                  <div className="mb-1 flex items-center gap-2 font-medium text-amber-300"><AlertTriangle size={15} /> Não coube</div>
                  <ul className="list-inside list-disc space-y-0.5 text-amber-200/70">
                    {plan.unplaced.map((u, i) => <li key={i}>{u}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}

          </div>
        </section>
      </div>

      {editing && (
        <EditModal value={editing} onChange={setEditing} onSave={saveEdit} onClose={() => setEditing(null)} />
      )}

      {editingBlock && (
        <BlockModal entry={editingBlock} onSave={saveBlock} onClose={() => setEditingBlock(null)} />
      )}

      {addingBlock && (
        <NewBlockModal onSave={addBlock} onClose={() => setAddingBlock(false)}
          defaultStart={plan?.blocks.length ? plan.blocks[plan.blocks.length - 1].end : toHHMM(Math.ceil(now / 15) * 15)}
          wakeTime={plan?.wake_time ?? null} />
      )}
    </div>
  );
}

// "Quando rendo mais" não é uma hora escolhida a olho: sai do histórico de
// código. Sem isto a opção parecia mágica e não se sabia a que horas ia dar.
function NotaHorasProdutivas() {
  const [dados, setDados] = useState<ProductiveHours | null>(null);

  useEffect(() => { dayPlannerApi.productiveHours().then(setDados).catch(() => setDados(null)); }, []);
  if (!dados) return null;

  if (!dados.enough) {
    return (
      <span className="text-[11px] text-amber-400/80">
        Ainda só há {dados.days} dias de código registados (precisa de {dados.needed_days ?? 10}) —
        até lá esta janela vale o dia todo.
      </span>
    );
  }
  return (
    <span className="text-[11px] text-gray-500">
      Pelos teus últimos {dados.days} dias de código: {dados.window
        ? <>das <span className="text-gray-300">{dados.window.start}</span> às <span className="text-gray-300">{dados.window.end}</span></>
        : 'sem janela clara'}
      {dados.top.length > 0 && ` · picos às ${dados.top.map(h => `${String(h).padStart(2, '0')}h`).join(', ')}`}
    </span>
  );
}

function Numero({ titulo, valor, sub }: { titulo: string; valor: string; sub?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[11px] uppercase tracking-wider text-gray-500">{titulo}</p>
      <p className="text-lg font-semibold leading-tight tabular-nums">{valor}</p>
      {sub && <p className="truncate text-[11px] text-gray-600">{sub}</p>}
    </div>
  );
}

function Modal({ title, onClose, children, footer }: {
  title: React.ReactNode; onClose: () => void; children: React.ReactNode; footer: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" onClick={onClose}>
      {/* O modal cabe no ecrã sem rolar por dentro: campos em duas colunas e
          espaçamentos curtos. O `max-h`/`overflow` fica como rede para ecrãs
          muito baixos — cortar o formulário em silêncio era pior. */}
      <div className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-3xl border border-white/10 bg-[#141414] p-5 shadow-2xl"
        onClick={e => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-base font-semibold tracking-tight">{title}</h3>
          <button onClick={onClose} className="rounded-lg p-1.5 text-gray-400 transition hover:bg-white/10 hover:text-white"><X size={18} /></button>
        </div>
        <div className="space-y-3">{children}</div>
        <div className="mt-5 flex gap-2">{footer}</div>
      </div>
    </div>
  );
}

const btnGhost = 'flex-1 rounded-xl bg-white/[0.06] py-2.5 transition hover:bg-white/[0.12] active:scale-[0.98]';
const btnPrimary = 'flex-1 rounded-xl bg-blue-600 py-2.5 font-medium shadow-lg shadow-blue-600/20 transition ' +
  'hover:bg-blue-500 active:scale-[0.98] disabled:opacity-40 disabled:shadow-none';

function EditModal({ value, onChange, onSave, onClose }: {
  value: Partial<DayActivity>;
  onChange: (v: Partial<DayActivity>) => void;
  onSave: () => void;
  onClose: () => void;
}) {
  const set = (patch: Partial<DayActivity>) => onChange({ ...value, ...patch });
  const flex = value.duration_max != null;

  return (
    <Modal title={`${value.id ? 'Editar' : 'Nova'} atividade`} onClose={onClose}
      footer={<>
        <button onClick={onClose} className={btnGhost}>Cancelar</button>
        <button onClick={onSave} disabled={!value.name?.trim()} className={btnPrimary}>Guardar</button>
      </>}>
      <div className="flex gap-3">
        <label className="flex w-20 flex-col gap-1.5">
          <span className="text-xs font-medium text-gray-400">Emoji</span>
          <input value={value.icon || ''} onChange={e => set({ icon: e.target.value })} maxLength={4}
            className={`${field} text-center text-xl`} />
        </label>
        <label className="flex flex-1 flex-col gap-1.5">
          <span className="text-xs font-medium text-gray-400">Nome</span>
          <input value={value.name || ''} onChange={e => set({ name: e.target.value })} autoFocus
            placeholder="Gym, Trabalho…" className={field} />
        </label>
        <label className="flex w-16 flex-col gap-1.5">
          <span className="text-xs font-medium text-gray-400">Cor</span>
          <input type="color" value={value.color || '#3B82F6'} onChange={e => set({ color: e.target.value })}
            className="h-[42px] w-full cursor-pointer rounded-xl border border-white/10 bg-black/40" />
        </label>
      </div>

      <div>
        <label className="mb-1.5 flex items-center gap-2 text-xs font-medium text-gray-400">
          <input type="checkbox" checked={flex} className="accent-blue-500"
            onChange={e => set({ duration_max: e.target.checked ? (value.duration_min || 60) + 60 : null })} />
          Duração flexível (min–máx)
        </label>
        <div className="flex gap-3">
          <label className="flex flex-1 flex-col gap-1.5">
            <span className="text-xs font-medium text-gray-400">{flex ? 'Mínimo' : 'Duração'} (min)</span>
            <input type="number" min={5} step={5} value={value.duration_min ?? 60}
              onChange={e => set({ duration_min: +e.target.value })} className={`${field} tabular-nums`} />
          </label>
          {flex && (
            <label className="flex flex-1 flex-col gap-1.5">
              <span className="text-xs font-medium text-gray-400">Máximo (min)</span>
              <input type="number" min={5} step={5} value={value.duration_max ?? 120}
                onChange={e => set({ duration_max: +e.target.value })} className={`${field} tabular-nums`} />
            </label>
          )}
        </div>
      </div>

      <div>
        <label className="mb-1.5 flex items-center gap-2 text-xs font-medium text-gray-400">
          <input type="checkbox" checked={!!value.splittable} className="accent-blue-500"
            onChange={e => set({ splittable: e.target.checked, chunk_max: e.target.checked ? (value.chunk_max || 120) : null })} />
          Dividir em vários blocos ao longo do dia (ex: trabalho)
        </label>
        {value.splittable && (
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-gray-400">Máx por bloco (min)</span>
            <input type="number" min={15} step={15} value={value.chunk_max ?? 120}
              onChange={e => set({ chunk_max: +e.target.value })} className={`${field} tabular-nums`} />
          </label>
        )}
      </div>

      <div className="flex gap-3">
        <label className="flex flex-1 flex-col gap-1.5">
          <span className="text-xs font-medium text-gray-400">Janela do dia</span>
          <select value={value.window} onChange={e => set({ window: e.target.value as DayWindow })} className={field}>
            {(Object.keys(WINDOW_LABELS) as DayWindow[]).map(w => <option key={w} value={w}>{WINDOW_LABELS[w]}</option>)}
          </select>
        </label>
        <label className="flex w-32 flex-col gap-1.5">
          <span className="text-xs font-medium text-gray-400">Hora fixa</span>
          <input type="time" value={value.fixed_time || ''} onChange={e => set({ fixed_time: e.target.value || null })}
            className={`${field} tabular-nums`} />
        </label>
        <label className="flex w-36 flex-col gap-1.5">
          <span className="text-xs font-medium text-gray-400">Prioridade</span>
          <select value={value.priority ?? 1} onChange={e => set({ priority: +e.target.value })} className={field}>
            {PRIORITY_LABELS.map((l, i) => <option key={i} value={i}>{l}</option>)}
          </select>
        </label>
      </div>
      {value.window === 'produtivo' && <NotaHorasProdutivas />}
    </Modal>
  );
}

const PALETTE = ['#6B7280', '#3B82F6', '#8B5CF6', '#EC4899', '#EF4444', '#F59E0B', '#10B981', '#14B8A6'];

function NewBlockModal({ onSave, onClose, defaultStart, wakeTime }: {
  onSave: (d: { name: string; icon: string; color: string; start: string; end: string; note: string }) => void;
  onClose: () => void;
  defaultStart: string;
  wakeTime: string | null;
}) {
  const [name, setName] = useState('');
  const [icon, setIcon] = useState('📌');
  const [color, setColor] = useState(PALETTE[0]);
  const [start, setStart] = useState(defaultStart);
  const [end, setEnd] = useState(toHHMM(toMin(defaultStart) + 60));
  const [note, setNote] = useState('');

  const valid = !!name.trim() && !!start && !!end && start !== end;
  const dur = valid ? blockMinutes({ start, end } as PlanBlock) : 0;
  // o dia lógico vai da hora de acordar em diante; horas anteriores caem na madrugada seguinte
  const afterMidnight = !!wakeTime && toMin(start) < toMin(wakeTime);

  return (
    <Modal title="Novo bloco" onClose={onClose}
      footer={<>
        <button onClick={onClose} className={btnGhost}>Cancelar</button>
        <button onClick={() => onSave({ name, icon, color, start, end, note })} disabled={!valid} className={btnPrimary}>Adicionar</button>
      </>}>
      <div className="flex gap-3">
        <label className="flex w-20 flex-col gap-1.5">
          <span className="text-xs font-medium text-gray-400">Emoji</span>
          <input value={icon} onChange={e => setIcon(e.target.value)} maxLength={4} className={`${field} text-center text-xl`} />
        </label>
        <label className="flex flex-1 flex-col gap-1.5">
          <span className="text-xs font-medium text-gray-400">Nome</span>
          <input value={name} onChange={e => setName(e.target.value)} autoFocus
            placeholder="Consulta, café com o João…" className={field} />
        </label>
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-gray-400">Cor</span>
        <div className="flex flex-wrap gap-2">
          {PALETTE.map(c => (
            <button key={c} onClick={() => setColor(c)} aria-label={`Cor ${c}`}
              className={`h-7 w-7 rounded-full transition active:scale-90 ${color === c ? 'ring-2 ring-white ring-offset-2 ring-offset-[#141414]' : ''}`}
              style={{ background: c }} />
          ))}
        </div>
      </div>

      <div className="flex items-end gap-3">
        <label className="flex flex-1 flex-col gap-1.5">
          <span className="text-xs font-medium text-gray-400">Início</span>
          <input type="time" value={start} onChange={e => setStart(e.target.value)} className={`${field} tabular-nums`} />
        </label>
        <label className="flex flex-1 flex-col gap-1.5">
          <span className="text-xs font-medium text-gray-400">Fim</span>
          <input type="time" value={end} onChange={e => setEnd(e.target.value)} className={`${field} tabular-nums`} />
        </label>
        <span className="w-14 shrink-0 pb-3 text-xs tabular-nums text-gray-500">{valid ? fmtMins(dur) : '—'}</span>
      </div>

      {afterMidnight && (
        <p className="flex gap-1.5 text-xs text-amber-400/80">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          Começa antes das {wakeTime} (hora a que acordaste), por isso entra no fim do dia, depois da meia-noite.
        </p>
      )}

      <label className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-gray-400">Nota (opcional)</span>
        <input value={note} onChange={e => setNote(e.target.value)} className={`${field} text-sm`} />
      </label>
    </Modal>
  );
}

function BlockModal({ entry, onSave, onClose }: {
  entry: { index: number; block: PlanBlock };
  onSave: (i: number, data: { name: string; start: string; end: string; note: string }) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(entry.block.name);
  const [start, setStart] = useState(entry.block.start);
  const [end, setEnd] = useState(entry.block.end);
  const [note, setNote] = useState(entry.block.note);

  const dur = blockMinutes({ ...entry.block, start, end });
  const valid = !!start && !!end && start !== end;

  return (
    <Modal title={<>{entry.block.icon} Alterar bloco</>} onClose={onClose}
      footer={<>
        <button onClick={onClose} className={btnGhost}>Cancelar</button>
        <button onClick={() => onSave(entry.index, { name, start, end, note })} disabled={!valid || !name.trim()}
          className={btnPrimary}>Guardar</button>
      </>}>
      <label className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-gray-400">Nome</span>
        <input value={name} onChange={e => setName(e.target.value)} className={field} />
      </label>

      <div className="flex items-end gap-3">
        <label className="flex flex-1 flex-col gap-1.5">
          <span className="text-xs font-medium text-gray-400">Início</span>
          <input type="time" value={start} onChange={e => setStart(e.target.value)} className={`${field} tabular-nums`} />
        </label>
        <label className="flex flex-1 flex-col gap-1.5">
          <span className="text-xs font-medium text-gray-400">Fim</span>
          <input type="time" value={end} onChange={e => setEnd(e.target.value)} className={`${field} tabular-nums`} />
        </label>
        <span className="w-14 shrink-0 pb-3 text-xs tabular-nums text-gray-500">{valid ? fmtMins(dur) : '—'}</span>
      </div>

      <label className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-gray-400">Nota (opcional)</span>
        <input value={note} onChange={e => setNote(e.target.value)} className={`${field} text-sm`} />
      </label>
    </Modal>
  );
}
