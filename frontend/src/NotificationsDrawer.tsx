// Painel de avisos (direita). Junta o que a app tem para dizer — coisas a precisar
// de atenção e o resumo da semana — para isso não andar espalhado pelos ecrãs.
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  X, Bell, AlertTriangle, Moon, Code2, Zap, Tag, TrendingUp, ChevronRight, Trash2, Check, Pencil, Activity, Brain, FileDown, CalendarClock, Flame, Target, HardDriveDownload, Cloud, HelpCircle,
} from 'lucide-react';
import { activarAvisos, desactivarAvisos, avisosActivos, podeReceberAvisos } from './push';
import {
  dashboardApi, codeActivityApi, sleepApi, budgetsApi, dealsApi,
  healthApi, DataHealth, appInsightsApi, OnThisDay, Anomaly, SleepMismatch, pushApi, seguranca,
  moodApi, DayQuestion,
} from './api';

type Insight = { key: string; icon: string; text: string };
type Stalled = { path: string; name: string; open_todos: number; days: number | null };
type Suspect = { id: number; date: string; hours: number; bedtime: string; wake_time: string; reason: string };

export function useAvisosCount() {
  const [count, setCount] = useState(0);

  const carregar = useCallback(async () => {
    const [sono, parados, previsao, saude] = await Promise.all([
      sleepApi.suspect(90).catch(() => []),
      codeActivityApi.stalled(5).catch(() => []),
      budgetsApi.forecast().catch(() => null),
      healthApi.data().catch(() => null),
    ]);
    const acimaDoPlano = previsao && previsao.plan_target > 0 && previsao.projected > previsao.plan_target ? 1 : 0;
    setCount(sono.length + parados.length + acimaDoPlano + (saude?.problems.length || 0));
  }, []);

  useEffect(() => {
    carregar();
    const id = setInterval(carregar, 600000);   // 10 min
    return () => clearInterval(id);
  }, [carregar]);

  return { count, recarregar: carregar };
}

export default function NotificationsDrawer({
  open, onClose, onChanged,
}: {
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const navigate = useNavigate();
  const [insights, setInsights] = useState<Insight[]>([]);
  const [semana, setSemana] = useState<Awaited<ReturnType<typeof codeActivityApi.weeklySummary>> | null>(null);
  const [parados, setParados] = useState<Stalled[]>([]);
  const [sono, setSono] = useState<Suspect[]>([]);
  const [previsao, setPrevisao] = useState<Awaited<ReturnType<typeof budgetsApi.forecast>> | null>(null);
  const [top, setTop] = useState<Awaited<ReturnType<typeof dealsApi.weeklyTop>>>([]);
  const [drops, setDrops] = useState<Awaited<ReturnType<typeof dealsApi.priceDrops>>>([]);
  const [saude, setSaude] = useState<DataHealth | null>(null);
  const [foco, setFoco] = useState<{ average: number | null; days_scored: number; best_day: any; series: any[] } | null>(null);
  const [distracao, setDistracao] = useState<{ median_minutes: number | null } | null>(null);
  const [correndo, setCorrendo] = useState<string | null>(null);
  const [aCopiar, setACopiar] = useState(false);
  const [retro, setRetro] = useState<'atual' | 'anterior' | null>(null);
  const [memorias, setMemorias] = useState<OnThisDay[]>([]);
  const [foraDoPadrao, setForaDoPadrao] = useState<Anomaly[]>([]);
  const [perguntas, setPerguntas] = useState<DayQuestion[]>([]);
  const [sonoErrado, setSonoErrado] = useState<SleepMismatch[]>([]);
  const [aCorrigirSono, setACorrigirSono] = useState(false);
  const [exposicao, setExposicao] = useState<Awaited<ReturnType<typeof seguranca.exposicao>> | null>(null);
  const [avisosNoTelemovel, setAvisosNoTelemovel] = useState(false);
  const [avisosErro, setAvisosErro] = useState<string | null>(null);
  const [aLigarAvisos, setALigarAvisos] = useState(false);
  const [consistencia, setConsistencia] = useState<Awaited<ReturnType<typeof dashboardApi.consistency>> | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [editando, setEditando] = useState<number | null>(null);
  const [form, setForm] = useState({ bedtime: '23:00', wake_time: '07:00' });

  const carregar = useCallback(() => {
    dashboardApi.insight().then(r => setInsights(r.insights)).catch(() => {});
    codeActivityApi.weeklySummary().then(setSemana).catch(() => {});
    codeActivityApi.stalled(5).then(setParados).catch(() => {});
    sleepApi.suspect(90).then(setSono).catch(() => {});
    budgetsApi.forecast().then(setPrevisao).catch(() => {});
    dealsApi.weeklyTop(3, 7).then(setTop).catch(() => {});
    dealsApi.priceDrops(30).then(setDrops).catch(() => {});
    healthApi.data().then(setSaude).catch(() => {});
    const hoje = new Date();
    const inicio = new Date(hoje.getTime() - 6 * 86400000);
    const iso = (d: Date) => d.toISOString().slice(0, 10);
    appInsightsApi.focusScore(iso(inicio), iso(hoje)).then(setFoco).catch(() => {});
    appInsightsApi.firstDistraction(30).then(setDistracao).catch(() => {});
    dashboardApi.onThisDay().then(r => setMemorias(r.entries)).catch(() => {});
    dashboardApi.anomalies(14).then(r => setForaDoPadrao(r.anomalies)).catch(() => {});
    moodApi.perguntas(14, 4).then(r => setPerguntas(r.questions)).catch(() => {});
    sleepApi.reconcile(14, false).then(r => setSonoErrado(r.changes)).catch(() => {});
    avisosActivos().then(setAvisosNoTelemovel).catch(() => {});
    seguranca.exposicao().then(setExposicao).catch(() => {});
    dashboardApi.consistency(30).then(setConsistencia).catch(() => {});
  }, []);

  useEffect(() => { if (open) carregar(); }, [open, carregar]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  if (!open) return null;

  const ir = (url: string) => { onClose(); navigate(url); };

  const confirmarSono = async (id: number) => {
    setBusy(id);
    try { await sleepApi.confirm(id); setSono(s => s.filter(x => x.id !== id)); onChanged(); }
    finally { setBusy(null); }
  };
  // Horas entre deitar e acordar, a contar com noites que passam da meia-noite.
  const horasEntre = (bedtime: string, wake: string) => {
    const [bh, bm] = bedtime.split(':').map(Number);
    const [wh, wm] = wake.split(':').map(Number);
    let mins = wh * 60 + wm - (bh * 60 + bm);
    if (mins <= 0) mins += 24 * 60;
    return Math.round(mins / 60 * 10) / 10;
  };

  const abrirEdicao = (e: Suspect) => {
    setEditando(e.id);
    setForm({ bedtime: e.bedtime || '23:00', wake_time: e.wake_time || '07:00' });
  };

  const guardarSono = async (id: number) => {
    setBusy(id);
    try {
      await sleepApi.update(id, {
        bedtime: form.bedtime,
        wake_time: form.wake_time,
        hours: horasEntre(form.bedtime, form.wake_time),
      });
      setSono(s => s.filter(x => x.id !== id));
      setEditando(null);
      onChanged();
    } finally { setBusy(null); }
  };

  const apagarSono = async (id: number) => {
    setBusy(id);
    try { await sleepApi.delete(id); setSono(s => s.filter(x => x.id !== id)); onChanged(); }
    finally { setBusy(null); }
  };

  const acimaDoPlano = previsao && previsao.plan_target > 0 && previsao.projected > previsao.plan_target;
  const MES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  const diaLongo = (iso: string) => {
    const [a, m, d] = iso.split('-').map(Number);
    return `${d} ${MES[m - 1]} ${a}`;
  };
  const horas = (s: number) => `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}`;
  const problemasSaude = saude?.problems.length || 0;
  const nAvisos = sono.length + parados.length + (acimaDoPlano ? 1 : 0) + problemasSaude;

  const descarregarRetro = async (qual: 'atual' | 'anterior') => {
    setRetro(qual);
    try {
      const d = new Date();
      if (qual === 'anterior') d.setMonth(d.getMonth() - 1);
      const { blob, filename } = await dashboardApi.monthlyReviewPdf(d.getMonth() + 1, d.getFullYear());
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
    } finally { setRetro(null); }
  };

  const correrJob = async (name: string) => {
    setCorrendo(name);
    try { await healthApi.runJob(name); setSaude(await healthApi.data()); onChanged(); }
    finally { setCorrendo(null); }
  };

  return (
    <div className="fixed inset-0 z-[75] flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/50" />
      <aside
        onClick={e => e.stopPropagation()}
        className="relative h-full w-[420px] max-w-[92vw] bg-[#161616] border-l border-[#222] flex flex-col shadow-xl"
      >
        <header className="flex items-center gap-2 px-4 py-3 border-b border-[#222] shrink-0">
          <Bell size={16} className="text-blue-400" />
          <h2 className="text-sm font-semibold">Avisos</h2>
          {nAvisos > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-red-500/20 text-red-300">{nAvisos}</span>
          )}
          <button onClick={onClose} className="ml-auto text-gray-500 hover:text-white">
            <X size={16} />
          </button>
        </header>

        <div className="flex-1 min-h-0 overflow-y-auto divide-y divide-[#1a1a1a]">
          {exposicao?.risk && (
            <section className="p-4 bg-red-500/[0.06]">
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-red-300 flex items-center gap-1.5 mb-1.5">
                <AlertTriangle size={12} /> A app está aberta à rede
              </h3>
              <p className="text-[11px] text-gray-400 leading-relaxed">
                Sem password, quem estiver no mesmo wi-fi abre{' '}
                <span className="text-gray-200">http://{exposicao.local_ip}:3001</span>{' '}
                e vê (e altera) gastos, notas, sono e investimentos.
              </p>
              <p className="text-[10px] text-gray-500 mt-1.5">
                Fecha com <span className="text-gray-300">./scripts/proteger.sh</span> no terminal — a sessão dura 30 dias em cada dispositivo.
              </p>
            </section>
          )}

          {/* ── A precisar de ti ─────────────────────────────── */}
          {nAvisos === 0 && (
            <p className="px-4 py-6 text-xs text-gray-600 text-center">Nada a precisar de ti. 🎉</p>
          )}

          {saude && !saude.ok && (
            <section className="p-4">
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-red-400 flex items-center gap-1.5 mb-2">
                <Activity size={12} /> Dados parados
              </h3>
              <div className="space-y-1.5">
                {saude.sources.filter(f => f.stale).map(f => (
                  <div key={f.key} className="flex items-center gap-2 text-xs bg-[#1a1a1a] rounded-lg px-2.5 py-2">
                    <span className="flex-1 min-w-0 truncate text-gray-300">{f.label}</span>
                    <span className="text-red-400 shrink-0">
                      {f.days_ago === null ? 'sem dados' : `${f.days_ago}d sem actualizar`}
                    </span>
                  </div>
                ))}
                {saude.jobs.filter(j => j.stale).map(j => (
                  <div key={j.name} className="flex items-center gap-2 text-xs bg-[#1a1a1a] rounded-lg px-2.5 py-2">
                    <span className="flex-1 min-w-0 truncate text-gray-300">{j.label}</span>
                    <span className="text-red-400 shrink-0">
                      {j.hours_ago === null ? 'nunca correu' : `há ${Math.round(j.hours_ago)}h`}
                    </span>
                    <button
                      onClick={() => correrJob(j.name)}
                      disabled={correndo === j.name}
                      className="px-2 py-0.5 rounded-lg bg-blue-500/15 text-blue-300 hover:bg-blue-500/25 disabled:opacity-40 shrink-0"
                    >
                      {correndo === j.name ? 'a correr…' : 'correr'}
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}

          {sono.length > 0 && (
            <section className="p-4">
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-amber-400 flex items-center gap-1.5 mb-2">
                <Moon size={12} /> {sono.length} noite{sono.length > 1 ? 's' : ''} estimada{sono.length > 1 ? 's' : ''} a confirmar
              </h3>
              <div className="space-y-1.5">
                {sono.slice(0, 4).map(e => (
                  <div key={e.id} className="text-xs bg-[#1a1a1a] rounded-lg px-2.5 py-2">
                    <div className="flex items-center gap-2">
                      <span className="w-11 shrink-0 text-gray-400">{e.date.slice(8)}/{e.date.slice(5, 7)}</span>
                      <span className="w-11 shrink-0 font-semibold">{e.hours}h</span>
                      <span className="flex-1 min-w-0 truncate text-gray-500">
                        {editando === e.id ? `${e.bedtime} → ${e.wake_time}` : e.reason}
                      </span>
                      <button onClick={() => confirmarSono(e.id)} disabled={busy === e.id}
                        title="Está certo" className="p-1 text-gray-500 hover:text-emerald-400 disabled:opacity-40">
                        <Check size={13} />
                      </button>
                      <button
                        onClick={() => (editando === e.id ? setEditando(null) : abrirEdicao(e))}
                        disabled={busy === e.id}
                        title="Corrigir horas"
                        className={`p-1 disabled:opacity-40 ${editando === e.id ? 'text-blue-400' : 'text-gray-500 hover:text-blue-400'}`}
                      >
                        <Pencil size={13} />
                      </button>
                      <button onClick={() => apagarSono(e.id)} disabled={busy === e.id}
                        title="Apagar" className="p-1 text-gray-500 hover:text-red-400 disabled:opacity-40">
                        <Trash2 size={13} />
                      </button>
                    </div>

                    {editando === e.id && (
                      <div className="mt-2 pt-2 border-t border-[#222] flex flex-wrap items-end gap-2">
                        <label className="flex flex-col gap-0.5">
                          <span className="text-[10px] text-gray-500">Deitei-me</span>
                          <input
                            type="time"
                            value={form.bedtime}
                            onChange={ev => setForm(f => ({ ...f, bedtime: ev.target.value }))}
                            className="bg-[#222] border border-[#333] rounded-lg px-2 py-1 text-xs tabular-nums focus:outline-none focus:border-blue-500/50"
                          />
                        </label>
                        <label className="flex flex-col gap-0.5">
                          <span className="text-[10px] text-gray-500">Acordei</span>
                          <input
                            type="time"
                            value={form.wake_time}
                            onChange={ev => setForm(f => ({ ...f, wake_time: ev.target.value }))}
                            className="bg-[#222] border border-[#333] rounded-lg px-2 py-1 text-xs tabular-nums focus:outline-none focus:border-blue-500/50"
                          />
                        </label>
                        <span className="text-xs font-semibold text-blue-300 pb-1.5">
                          {horasEntre(form.bedtime, form.wake_time)}h
                        </span>
                        <div className="ml-auto flex items-center gap-1.5 pb-0.5">
                          <button onClick={() => setEditando(null)}
                            className="px-2 py-1 rounded-lg bg-[#222] text-gray-400 hover:text-gray-200">
                            cancelar
                          </button>
                          <button onClick={() => guardarSono(e.id)} disabled={busy === e.id}
                            className="px-2 py-1 rounded-lg bg-blue-500/20 text-blue-300 hover:bg-blue-500/30 disabled:opacity-40">
                            guardar
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
              {sono.length > 4 && (
                <button onClick={() => ir('/sleep')} className="mt-2 text-[11px] text-amber-400 hover:text-amber-300">
                  ver as {sono.length} no Sono →
                </button>
              )}
            </section>
          )}

          {parados.length > 0 && (
            <section className="p-4">
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-amber-400 flex items-center gap-1.5 mb-2">
                <AlertTriangle size={12} /> Projectos parados
              </h3>
              <div className="space-y-1.5">
                {parados.map(p => (
                  <button
                    key={p.path}
                    onClick={() => ir('/code')}
                    className="w-full flex items-center gap-2 text-xs bg-[#1a1a1a] rounded-lg px-2.5 py-2 hover:bg-white/5 text-left"
                  >
                    <span className="flex-1 min-w-0 truncate text-gray-300">{p.name}</span>
                    <span className="text-gray-500 shrink-0">{p.days} dias · {p.open_todos} TODO{p.open_todos === 1 ? '' : 's'}</span>
                    <ChevronRight size={13} className="text-gray-600 shrink-0" />
                  </button>
                ))}
              </div>
            </section>
          )}

          {acimaDoPlano && previsao && (
            <section className="p-4">
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-red-400 flex items-center gap-1.5 mb-2">
                <TrendingUp size={12} /> Gastos acima do plano
              </h3>
              <button onClick={() => ir('/expenses')} className="w-full text-left bg-[#1a1a1a] rounded-lg px-3 py-2.5 hover:bg-white/5">
                <p className="text-sm font-semibold">€{previsao.projected.toFixed(0)} previstos este mês</p>
                <p className="text-[11px] text-red-400 mt-0.5">
                  {Math.round(previsao.projected / previsao.plan_target * 100)}% do plano (€{previsao.plan_target.toFixed(0)}) ·
                  a caminho de estourar €{Math.abs(previsao.over_by || 0).toFixed(0)}
                </p>
                <p className="text-[10px] text-gray-600 mt-0.5">
                  ao ritmo de €{previsao.daily_rate.toFixed(0)}/dia · {previsao.days_elapsed} de {previsao.days_in_month} dias
                </p>
              </button>
            </section>
          )}

          {/* ── Esta semana ──────────────────────────────────── */}
          {insights.length > 0 && (
            <section className="p-4">
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-500 flex items-center gap-1.5 mb-2">
                <Zap size={12} className="text-yellow-400" /> Insight da semana
              </h3>
              <div className="space-y-2">
                {insights.map(i => (
                  <div key={i.key} className="flex items-start gap-2">
                    <span className="text-sm shrink-0">{i.icon}</span>
                    <p className="text-xs text-gray-400 leading-relaxed">{i.text}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {foco && foco.average !== null && (
            <section className="p-4">
              <div className="flex items-baseline justify-between gap-2 mb-2">
                <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-500 flex items-center gap-1.5">
                  <Brain size={12} className="text-violet-400" /> Foco desta semana
                </h3>
                <button onClick={() => ir('/calendar/apps')} className="text-[11px] text-violet-400 hover:text-violet-300">ver tudo →</button>
              </div>
              <div className="flex items-end gap-2 mb-2">
                <span className="text-2xl font-bold">{Math.round(foco.average)}</span>
                <span className="text-[11px] text-gray-500 pb-1">
                  /100 em {foco.days_scored} dia{foco.days_scored === 1 ? '' : 's'}
                  {distracao?.median_minutes ? ` · 1ª distracção aos ${Math.round(distracao.median_minutes)}min` : ''}
                </span>
              </div>
              {foco.series.length > 0 && (
                <div className="flex items-end gap-1 h-10">
                  {foco.series.slice(-14).map((d: any) => (
                    <div key={d.date} className="flex-1 bg-violet-400/30 rounded-t" title={`${d.date}: ${Math.round(d.score)}`}
                      style={{ height: `${Math.max(6, Math.min(100, d.score))}%` }} />
                  ))}
                </div>
              )}
              {foco.best_day && (
                <p className="text-[10px] text-gray-600 mt-1">
                  melhor dia: {foco.best_day.date.slice(8)}/{foco.best_day.date.slice(5, 7)} com {Math.round(foco.best_day.score)}
                  {foco.best_day.deep_work_blocks ? ` · ${foco.best_day.deep_work_blocks} blocos de foco` : ''}
                </p>
              )}
            </section>
          )}

          {semana && semana.total_seconds > 0 && (
            <section className="p-4">
              <div className="flex items-baseline justify-between gap-2 mb-2">
                <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-500 flex items-center gap-1.5">
                  <Code2 size={12} className="text-blue-400" /> Semana de código
                </h3>
                <button onClick={() => ir('/code')} className="text-[11px] text-blue-400 hover:text-blue-300">ver tudo →</button>
              </div>
              <p className="text-lg font-bold mb-1">
                {horas(semana.total_seconds)}
                <span className="ml-2 text-[11px] font-normal text-gray-500">
                  {semana.projects.slice(0, 2).map(p => `${p.name} ${horas(p.seconds)}`).join(' · ')}
                </span>
              </p>
              <ul className="space-y-1.5">
                {semana.bullets.map((b, i) => (
                  <li key={i} className="text-xs text-gray-400 flex gap-2">
                    <span className="text-blue-400 shrink-0">•</span><span>{b}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {(top.length > 0 || drops.length > 0) && (
            <section className="p-4">
              <div className="flex items-baseline justify-between gap-2 mb-2">
                <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-500 flex items-center gap-1.5">
                  <Tag size={12} className="text-pink-400" /> Deals da semana
                </h3>
                <button onClick={() => ir('/deals')} className="text-[11px] text-pink-400 hover:text-pink-300">ver tudo →</button>
              </div>
              {drops.slice(0, 2).map(d => (
                <a key={d.id} href={d.url} target="_blank" rel="noreferrer"
                  className="flex items-center gap-2 text-xs text-emerald-300 hover:underline mb-1.5">
                  <TrendingUp size={12} className="rotate-180 shrink-0" />
                  <span className="flex-1 truncate">{d.title}</span>
                  <span className="shrink-0">−{d.drop_pct}% · {d.price}€</span>
                </a>
              ))}
              <div className="space-y-1.5">
                {top.map(d => (
                  <a key={d.id} href={d.url} target="_blank" rel="noreferrer"
                    className="flex items-center gap-2 bg-[#1a1a1a] rounded-lg px-2.5 py-2 hover:bg-white/5">
                    {d.image_url
                      ? <img src={d.image_url} alt="" className="w-8 h-8 rounded object-cover shrink-0" />
                      : <div className="w-8 h-8 rounded bg-[#222] shrink-0" />}
                    <div className="flex-1 min-w-0">
                      <p className="text-xs truncate">{d.title}</p>
                      <p className="text-[10px] text-gray-600">{d.source}{d.location ? ` · ${d.location}` : ''}</p>
                    </div>
                    <span className="text-xs font-semibold text-pink-400 shrink-0">{d.price ?? '—'}€</span>
                  </a>
                ))}
              </div>
            </section>
          )}
          {sonoErrado.length > 0 && (
            <section className="p-4">
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-500 flex items-center gap-1.5 mb-2">
                <Moon size={12} className="text-indigo-400" /> Noites que não batem certo
              </h3>
              <p className="text-[11px] text-gray-500 mb-2">
                O que está registado não coincide com o que o Mac viu.
              </p>
              <div className="space-y-1.5">
                {sonoErrado.slice(0, 5).map(m => (
                  <div key={m.date} className="bg-[#1a1a1a] rounded-xl px-3 py-2">
                    <p className="text-[11px] text-gray-300">
                      {diaLongo(m.date)}:{' '}
                      {m.antigo
                        ? <>a app diz <span className="text-gray-500">{m.antigo.hours}h</span> ({m.antigo.bedtime}–{m.antigo.wake_time})</>
                        : <>sem registo</>}
                      {' → '}
                      <span className="text-indigo-300">{m.novo.hours}h</span> ({m.novo.bedtime}–{m.novo.wake_time})
                    </p>
                    <p className="text-[10px] text-gray-600 mt-0.5">{m.novo.fact}</p>
                  </div>
                ))}
              </div>
              <button
                onClick={async () => {
                  setACorrigirSono(true);
                  try {
                    await sleepApi.reconcile(14, true);
                    setSonoErrado([]);
                    onChanged();
                  } finally { setACorrigirSono(false); }
                }}
                disabled={aCorrigirSono}
                className="mt-2 text-[11px] px-2.5 py-1.5 rounded-lg bg-indigo-500/15 text-indigo-300 hover:bg-indigo-500/25 disabled:opacity-40"
              >
                {aCorrigirSono ? 'a corrigir…' : `corrigir ${sonoErrado.length} noite${sonoErrado.length === 1 ? '' : 's'}`}
              </button>
            </section>
          )}

          {consistencia?.today && (
            <section className="p-4">
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-500 flex items-center gap-1.5 mb-2">
                <Flame size={12} className="text-orange-400" /> Consistência
              </h3>
              <div className="flex items-baseline gap-2 mb-2">
                <span className={`text-2xl font-bold ${
                  consistencia.today.score >= 75 ? 'text-emerald-400'
                    : consistencia.today.score >= 50 ? 'text-amber-400' : 'text-red-400'
                }`}>{consistencia.today.score}%</span>
                <span className="text-[11px] text-gray-500">
                  hoje · {consistencia.today.done}/{consistencia.today.total}
                  {consistencia.streak > 0 && ` · ${consistencia.streak} dia${consistencia.streak === 1 ? '' : 's'} seguidos`}
                </span>
                {consistencia.best_streak > consistencia.streak && (
                  <span className="text-[10px] text-gray-600 ml-auto">recorde {consistencia.best_streak}d</span>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5 mb-2">
                {consistencia.today.parts.map(p => (
                  <span key={p.key} className={`text-[10px] px-2 py-0.5 rounded-lg ${
                    p.ok ? 'bg-emerald-500/15 text-emerald-300' : 'bg-[#1a1a1a] text-gray-600'
                  }`}>
                    {p.ok ? '✓' : '·'} {p.label}
                  </span>
                ))}
              </div>
              <div className="flex items-end gap-[2px] h-7">
                {consistencia.series.slice(-21).map(s => (
                  <div key={s.date} className="flex-1 rounded-t bg-orange-400/40" title={`${s.date}: ${s.score}%`}
                    style={{ height: `${Math.max(6, s.score)}%` }} />
                ))}
              </div>
            </section>
          )}

          {perguntas.length > 0 && (
            <section className="p-4">
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-500 flex items-center gap-1.5 mb-2">
                <HelpCircle size={12} className="text-sky-400" /> A app pergunta-te
              </h3>
              <div className="space-y-1.5">
                {perguntas.map(p => (
                  <PerguntaDoDia
                    key={`${p.date}-${p.key}`}
                    p={p}
                    onFeito={() => setPerguntas(qs => qs.filter(q => !(q.date === p.date && q.key === p.key)))}
                    onAbrirDia={() => ir(`/day/${p.date}`)}
                  />
                ))}
              </div>
              <p className="text-[10px] text-gray-600 mt-2">
                O que respondes fica no diário desse dia — é onde vais procurar daqui a uns meses.
              </p>
            </section>
          )}

          {foraDoPadrao.length > 0 && (
            <section className="p-4">
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-500 flex items-center gap-1.5 mb-2">
                <Activity size={12} className="text-orange-400" /> Fora do padrão
              </h3>
              <div className="space-y-1.5">
                {foraDoPadrao.slice(0, 6).map((a, i) => (
                  <button key={`${a.date}-${a.key}-${i}`} onClick={() => ir(`/day/${a.date}`)}
                    className="w-full text-left flex items-start gap-2.5 bg-[#1a1a1a] rounded-xl px-3 py-2 hover:bg-white/5">
                    <span className="text-sm shrink-0 mt-0.5">{a.icon}</span>
                    <div className="min-w-0 flex-1">
                      <p className="text-[11px] text-gray-300 leading-snug">{a.text}</p>
                      <p className="text-[10px] text-gray-600 mt-0.5">
                        {diaLongo(a.date)}
                        {a.severity === 'alta' && <span className="text-orange-400/80"> · bem fora do normal</span>}
                      </p>
                    </div>
                  </button>
                ))}
              </div>
              <p className="text-[10px] text-gray-600 mt-2">
                Comparado com o teu próprio normal dos últimos meses, não com metas.
              </p>
            </section>
          )}

          {memorias.length > 0 && (
            <section className="p-4">
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-500 flex items-center gap-1.5 mb-2">
                <CalendarClock size={12} className="text-amber-400" /> Neste dia
              </h3>
              <div className="space-y-2">
                {memorias.map(m => {
                  const factos: string[] = [];
                  if (m.trip) factos.push(`estavas em ${m.trip}`);
                  if (m.code_seconds >= 300) factos.push(`${horas(m.code_seconds)} de código${m.top_project ? ` (${m.top_project.name})` : ''}`);
                  if (m.sleep_hours) factos.push(`dormiste ${m.sleep_hours}h`);
                  if (m.spent > 0) factos.push(`gastaste ${m.spent.toFixed(2)}€${m.top_expense ? ` — ${m.top_expense.description}` : ''}`);
                  if (m.lol) factos.push(`${m.lol.games} game${m.lol.games === 1 ? '' : 's'} de LoL (${m.lol.wins}W)`);
                  if (m.mood) factos.push(`humor ${m.mood}/10`);
                  if (m.notes) factos.push(`${m.notes} nota${m.notes === 1 ? '' : 's'}`);
                  if (m.events.length) factos.push(m.events.slice(0, 2).join(', '));
                  return (
                    <button key={m.date} onClick={() => ir(`/day/${m.date}`)}
                      className="w-full text-left bg-[#1a1a1a] rounded-xl px-3 py-2 hover:bg-white/5">
                      <div className="flex items-baseline gap-2">
                        <span className="text-xs font-semibold text-amber-300/90">{m.label}</span>
                        <span className="text-[10px] text-gray-600">{diaLongo(m.date)}</span>
                      </div>
                      <p className="text-[11px] text-gray-400 mt-0.5 leading-relaxed">{factos.join(' · ')}</p>
                      {(m.journal || m.mood_note) && (
                        <p className="text-[11px] text-gray-500 italic mt-1 line-clamp-3">
                          "{(m.journal || m.mood_note)!.replace(/\s+/g, ' ').trim()}"
                        </p>
                      )}
                    </button>
                  );
                })}
              </div>
            </section>
          )}

          <section className="p-4">
            <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-500 flex items-center gap-1.5 mb-2">
              <Bell size={12} className="text-emerald-400" /> Avisos neste dispositivo
            </h3>
            <p className="text-[11px] text-gray-500 mb-2">
              {avisosNoTelemovel
                ? 'Este dispositivo recebe os avisos mesmo com a app fechada.'
                : 'Recebe deals, orçamento e plano do dia sem teres de abrir a app.'}
            </p>
            <div className="flex items-center gap-2 flex-wrap">
              <button
                onClick={async () => {
                  setALigarAvisos(true);
                  setAvisosErro(null);
                  try {
                    if (avisosNoTelemovel) {
                      await desactivarAvisos();
                      setAvisosNoTelemovel(false);
                    } else {
                      const r = await activarAvisos();
                      if (r.ok) setAvisosNoTelemovel(true);
                      else setAvisosErro(r.erro || 'não consegui activar');
                    }
                  } finally { setALigarAvisos(false); }
                }}
                disabled={aLigarAvisos}
                className={`text-[11px] px-2.5 py-1.5 rounded-lg disabled:opacity-40 ${
                  avisosNoTelemovel
                    ? 'bg-[#1a1a1a] text-gray-400 hover:text-gray-200'
                    : 'bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25'
                }`}
              >
                {aLigarAvisos ? 'um momento…' : avisosNoTelemovel ? 'desligar avisos' : 'receber avisos aqui'}
              </button>
              {avisosNoTelemovel && (
                <button onClick={() => pushApi.test().catch(() => {})}
                  className="text-[11px] px-2.5 py-1.5 rounded-lg bg-[#1a1a1a] text-gray-400 hover:text-gray-200">
                  enviar um de teste
                </button>
              )}
            </div>
            {avisosErro && <p className="text-[10px] text-amber-400 mt-1.5">{avisosErro}</p>}
            {!avisosNoTelemovel && !podeReceberAvisos().pode && !avisosErro && (
              <p className="text-[10px] text-gray-600 mt-1.5">{podeReceberAvisos().motivo}</p>
            )}
          </section>

          <section className="p-4">
            <button onClick={() => ir('/acertos')} className="w-full text-left group">
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-500 flex items-center gap-1.5 mb-1 group-hover:text-gray-300">
                <Target size={12} className="text-emerald-400" /> O que a app acertou
              </h3>
              <p className="text-[11px] text-gray-500">
                Cada parte que faz previsões, avaliada com o que aconteceu depois.
              </p>
            </button>
          </section>

          <section className="p-4">
            <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-500 flex items-center gap-1.5 mb-2">
              <FileDown size={12} className="text-purple-400" /> Retrospectiva
            </h3>
            <p className="text-[11px] text-gray-500 mb-2">
              O mês em PDF: sono, gastos, código, jogos, viagens e humor, com leitura da IA.
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={() => descarregarRetro('anterior')}
                disabled={retro !== null}
                className="text-[11px] px-2.5 py-1.5 rounded-lg bg-purple-500/15 text-purple-300 hover:bg-purple-500/25 disabled:opacity-40"
              >
                {retro === 'anterior' ? 'a gerar…' : 'mês passado'}
              </button>
              <button
                onClick={() => descarregarRetro('atual')}
                disabled={retro !== null}
                className="text-[11px] px-2.5 py-1.5 rounded-lg bg-[#1a1a1a] text-gray-400 hover:text-gray-200 disabled:opacity-40"
              >
                {retro === 'atual' ? 'a gerar…' : 'este mês'}
              </button>
            </div>
          </section>
        </div>

        {saude && (
          <footer className="shrink-0 border-t border-[#222] px-4 py-2.5 space-y-1.5">
            <div className="flex items-center gap-2 text-[11px]">
              <Activity size={12} className={saude.ok ? 'text-emerald-400' : 'text-red-400'} />
              <span className={saude.ok ? 'text-emerald-400' : 'text-red-400'}>
                {saude.ok ? 'Todos os dados em dia' : `${saude.problems.length} fonte(s) por actualizar`}
              </span>
              <span className="ml-auto text-gray-600">
                {saude.jobs.filter(j => j.ok).length}/{saude.jobs.length} trabalhos ok
              </span>
            </div>
            {saude.backups && (
              <div className="flex items-center gap-2 text-[11px]">
                <HardDriveDownload size={12} className={saude.backups.stale ? 'text-red-400' : 'text-emerald-400'} />
                <span className={saude.backups.stale ? 'text-red-400' : 'text-gray-500'}>
                  {saude.backups.last
                    ? `cópia de há ${Math.round(saude.backups.hours_ago || 0)}h · ${saude.backups.last.mb}MB`
                    : 'sem cópia de segurança'}
                </span>
                <button
                  onClick={async () => {
                    setACopiar(true);
                    try { await healthApi.runBackup(); setSaude(await healthApi.data()); onChanged(); }
                    finally { setACopiar(false); }
                  }}
                  disabled={aCopiar}
                  className="ml-auto px-2 py-0.5 rounded-lg bg-blue-500/15 text-blue-300 hover:bg-blue-500/25 disabled:opacity-40"
                >
                  {aCopiar ? 'a copiar…' : 'copiar agora'}
                </button>
              </div>
            )}
            {saude.backups?.offsite && (
              <div className="flex items-center gap-2 text-[11px]" title={saude.backups.offsite.dir}>
                <Cloud size={12} className={
                  !saude.backups.offsite.enabled ? 'text-gray-600'
                    : saude.backups.offsite.stale ? 'text-red-400' : 'text-emerald-400'
                } />
                <span className={saude.backups.offsite.stale ? 'text-red-400' : 'text-gray-500'}>
                  {!saude.backups.offsite.enabled
                    ? (saude.backups.offsite.dir && !saude.backups.offsite.has_passphrase
                        ? 'fora do Mac: falta a palavra-passe'
                        : 'sem cópia fora deste Mac')
                    : saude.backups.offsite.last
                      ? `fora do Mac há ${Math.round(saude.backups.offsite.hours_ago || 0)}h · cifrada`
                      : 'fora do Mac: ainda nenhuma'}
                </span>
              </div>
            )}
          </footer>
        )}
      </aside>
    </div>
  );
}

// Uma pergunta sobre um dia estranho. Responder escreve no diário desse dia;
// "não interessa" tira-a de vez (a mesma pergunta não volta a aparecer).
function PerguntaDoDia({ p, onFeito, onAbrirDia }: {
  p: DayQuestion; onFeito: () => void; onAbrirDia: () => void;
}) {
  const [texto, setTexto] = useState('');
  const [aGuardar, setAGuardar] = useState(false);

  const guardar = async () => {
    if (!texto.trim() || aGuardar) return;
    setAGuardar(true);
    try {
      await moodApi.responderPergunta({ date: p.date, key: p.key, question: p.question, answer: texto.trim() });
      onFeito();
    } catch {
      setAGuardar(false);
    }
  };

  const dispensar = async () => {
    try { await moodApi.dispensarPergunta({ date: p.date, key: p.key, question: p.question }); } catch { /* ignora */ }
    onFeito();
  };

  return (
    <div className="bg-[#1a1a1a] rounded-xl px-3 py-2.5">
      <div className="flex items-start gap-2.5">
        <span className="text-sm shrink-0 mt-0.5">{p.icon}</span>
        <p className="text-[11px] text-gray-300 leading-snug flex-1">{p.question}</p>
      </div>
      <div className="flex items-center gap-1.5 mt-2">
        <input
          value={texto}
          onChange={e => setTexto(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && guardar()}
          placeholder="numa frase…"
          className="flex-1 min-w-0 bg-[#0f0f0f] border border-[#2a2a2a] rounded-lg px-2.5 py-1.5 text-[11px] text-gray-200 focus:outline-none focus:border-sky-500/50"
        />
        <button
          onClick={guardar}
          disabled={!texto.trim() || aGuardar}
          className="shrink-0 px-2 py-1.5 rounded-lg bg-sky-500/15 text-sky-300 text-[10px] font-medium hover:bg-sky-500/25 disabled:opacity-30"
        >
          {aGuardar ? '…' : 'guardar'}
        </button>
      </div>
      <div className="flex items-center gap-3 mt-1.5">
        <button onClick={onAbrirDia} className="text-[10px] text-gray-600 hover:text-gray-400">
          ver o dia
        </button>
        <button onClick={dispensar} className="text-[10px] text-gray-600 hover:text-gray-400">
          não interessa
        </button>
        {p.has_journal && <span className="text-[10px] text-gray-700 ml-auto">já tem diário</span>}
      </div>
    </div>
  );
}
