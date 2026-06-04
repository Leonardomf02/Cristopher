import { useEffect, useRef, useState } from 'react';
import { format, parseISO } from 'date-fns';
import { pt } from 'date-fns/locale';
import { Code2, ChevronLeft, ChevronRight, ChevronDown, FileCode, FolderGit2, FolderOpen, ListChecks, ListPlus, Sparkles, Plus, Star, Trash2, Loader2, Clock, RefreshCw, FolderKanban } from 'lucide-react';
import {
  codeActivityApi,
  CodeActivityDay,
  CodeActivityProject,
  CodeProjectTodo,
  CodeProjectNote,
  CodeKnownProject,
  wakatimeApi,
  WakaSummary,
  WakaBreakdownItem,
  WakaProjectDetail,
  WAKA_RANGES,
  WAKA_PROJECT_RANGES,
} from '../api';

function shiftDate(iso: string, days: number): string {
  const d = parseISO(iso);
  d.setDate(d.getDate() + days);
  return format(d, 'yyyy-MM-dd');
}

function fileIcon(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  if (['ts', 'tsx'].includes(ext)) return '🟦';
  if (['js', 'jsx', 'mjs'].includes(ext)) return '🟨';
  if (ext === 'py') return '🐍';
  if (['java', 'kt'].includes(ext)) return '☕';
  if (['rs'].includes(ext)) return '🦀';
  if (['go'].includes(ext)) return '🐹';
  if (['html', 'htm'].includes(ext)) return '🌐';
  if (['css', 'scss', 'sass'].includes(ext)) return '🎨';
  if (['json', 'yaml', 'yml', 'toml'].includes(ext)) return '⚙️';
  if (['md', 'mdx'].includes(ext)) return '📝';
  if (['sh', 'bash', 'zsh'].includes(ext)) return '🐚';
  if (['sql'].includes(ext)) return '🗄️';
  return '📄';
}

export default function CodeActivityPage() {
  const today = format(new Date(), 'yyyy-MM-dd');
  const [date, setDate] = useState(today);
  const [data, setData] = useState<CodeActivityDay | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [weekTotals, setWeekTotals] = useState<{ date: string; total_saves: number; total_files: number; project_count: number }[]>([]);
  const [totals, setTotals] = useState<{ open_todos: number; total_notes: number }>({ open_todos: 0, total_notes: 0 });
  const [todoProjects, setTodoProjects] = useState<{ path: string; name: string }[]>([]);
  const [known, setKnown] = useState<CodeKnownProject[]>([]);
  const [tab, setTab] = useState<'atividade' | 'tempo' | 'projectos'>('atividade');

  const refreshKnown = () => {
    codeActivityApi.allProjects().then(setKnown).catch(() => {});
  };
  useEffect(() => { refreshKnown(); }, []);

  const favPaths = new Set(known.filter(k => k.favorite).map(k => k.path));

  const toggleFavorite = async (path: string, name: string) => {
    const next = !favPaths.has(path);
    setKnown(prev => {
      const exists = prev.some(k => k.path === path);
      const updated = exists
        ? prev.map(k => k.path === path ? { ...k, favorite: next } : k)
        : [...prev, { path, name, open_todos: 0, total_todos: 0, notes_count: 0, last_activity: null, favorite: next }];
      return updated;
    });
    try {
      await codeActivityApi.setFavorite(path, next);
    } catch {
      setKnown(prev => prev.map(k => k.path === path ? { ...k, favorite: !next } : k));
    }
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    codeActivityApi.forDate(date)
      .then(d => { if (!cancelled) setData(d); })
      .catch(e => { if (!cancelled) setError(e?.message || 'Erro'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [date]);

  useEffect(() => {
    codeActivityApi.range(7).then(r => setWeekTotals(r.days)).catch(() => {});
  }, []);

  const refreshTotals = () => {
    codeActivityApi.totals().then(setTotals).catch(() => {});
    codeActivityApi.projectsWithTodos().then(setTodoProjects).catch(() => {});
  };
  useEffect(() => { refreshTotals(); }, []);

  const dateLabel = format(parseISO(date), "d 'de' MMMM yyyy", { locale: pt });
  const weekday = format(parseISO(date), 'EEEE', { locale: pt });
  const isToday = date === today;
  const maxWeekSaves = Math.max(1, ...weekTotals.map(d => d.total_saves));

  return (
    <div className="max-w-6xl mx-auto">
      <div className="flex items-center gap-3 mb-2">
        <Code2 size={28} className="text-blue-400" />
        <h2 className="text-2xl sm:text-3xl font-bold">Atividade VS Code</h2>
      </div>
      <div className="flex items-center gap-2 mt-4 mb-6 border-b border-[#222]">
        <button
          onClick={() => setTab('atividade')}
          className={`px-4 py-2 text-sm font-semibold border-b-2 -mb-px transition-colors ${
            tab === 'atividade' ? 'border-blue-400 text-blue-300' : 'border-transparent text-gray-500 hover:text-gray-300'
          }`}
        >
          Atividade
        </button>
        <button
          onClick={() => setTab('tempo')}
          className={`flex items-center gap-1.5 px-4 py-2 text-sm font-semibold border-b-2 -mb-px transition-colors ${
            tab === 'tempo' ? 'border-cyan-400 text-cyan-300' : 'border-transparent text-gray-500 hover:text-gray-300'
          }`}
        >
          <Clock size={14} /> Tempo de código
        </button>
        <button
          onClick={() => setTab('projectos')}
          className={`flex items-center gap-1.5 px-4 py-2 text-sm font-semibold border-b-2 -mb-px transition-colors ${
            tab === 'projectos' ? 'border-cyan-400 text-cyan-300' : 'border-transparent text-gray-500 hover:text-gray-300'
          }`}
        >
          <FolderKanban size={14} /> Projectos
        </button>
      </div>

      {tab === 'tempo' && <WakaTimePanel />}
      {tab === 'projectos' && <WakaProjectsPanel />}

      {tab === 'atividade' && weekTotals.length > 0 && (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 mb-6">
          <div className="flex items-end gap-2">
            {weekTotals.map(d => {
              const h = (d.total_saves / maxWeekSaves) * 100;
              const selected = d.date === date;
              return (
                <button
                  key={d.date}
                  onClick={() => setDate(d.date)}
                  className="flex-1 flex flex-col items-center gap-1 group"
                >
                  <div className="w-full h-24 flex items-end">
                    <div
                      className={`w-full rounded-t-md transition-all ${
                        selected ? 'bg-blue-400' : 'bg-blue-400/30 group-hover:bg-blue-400/60'
                      }`}
                      style={{ height: `${Math.max(4, h)}%` }}
                      title={`${d.total_saves} saves`}
                    />
                  </div>
                  <span className={`text-[10px] ${selected ? 'text-blue-400 font-bold' : 'text-gray-500'}`}>
                    {format(parseISO(d.date), 'EEE', { locale: pt })}
                  </span>
                  <span className="text-[10px] text-gray-600">{d.total_saves}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {tab === 'atividade' && (<>
      <div className="flex items-center justify-between mb-6">
        <button
          onClick={() => setDate(shiftDate(date, -1))}
          className="p-2 bg-[#161616] hover:bg-[#1a1a1a] border border-[#222] rounded-xl text-gray-400 hover:text-white"
        >
          <ChevronLeft size={18} />
        </button>
        <div className="text-center">
          <p className="text-xs text-gray-500 uppercase">{weekday}</p>
          <p className="text-xl font-bold">{dateLabel}</p>
          {isToday && <p className="text-[10px] text-blue-400 mt-0.5">hoje</p>}
        </div>
        <button
          onClick={() => setDate(shiftDate(date, 1))}
          disabled={date >= today}
          className="p-2 bg-[#161616] hover:bg-[#1a1a1a] disabled:opacity-30 border border-[#222] rounded-xl text-gray-400 hover:text-white disabled:hover:text-gray-400"
        >
          <ChevronRight size={18} />
        </button>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3 mb-6 text-sm text-red-400">
          {error}
        </div>
      )}

      {loading && !data && (
        <div className="text-center text-gray-600 text-sm py-12">A carregar...</div>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 mb-6">
            <SummaryTile label="💾 Saves" value={data.total_saves} />
            <SummaryTile label="📄 Ficheiros" value={data.total_files} />
            <SummaryTile label="📁 Projetos" value={data.projects.length} />
            <SummaryTile label="✅ TODOs" value={totals.open_todos} accent="emerald" />
            <SummaryTile label="✨ Notas IA" value={totals.total_notes} accent="purple" />
          </div>

          {(() => {
            const activePaths = new Set(data.projects.map(p => p.path));
            const todoOnly: CodeActivityProject[] = todoProjects
              .filter(t => !activePaths.has(t.path))
              .map(t => ({
                name: t.name, path: t.path, saves: 0, files_count: 0, files: [], last_ts: 0,
              }));
            const dayAll = [...data.projects, ...todoOnly];

            // Favorites pinned at top, regardless of activity. Use today's activity data
            // if the favorite was touched today, otherwise a synthetic empty card.
            const favCards: CodeActivityProject[] = known
              .filter(k => k.favorite)
              .map(k => dayAll.find(p => p.path === k.path) ?? {
                name: k.name, path: k.path, saves: 0, files_count: 0, files: [], last_ts: 0,
              });

            const dayCards = dayAll.filter(p => !favPaths.has(p.path));
            const excludeFromAll = new Set([...favPaths, ...dayCards.map(p => p.path)]);

            const allCards = [...favCards, ...dayCards];
            return (
              <>
                {allCards.length === 0 ? (
                  <div className="bg-[#161616] rounded-2xl border border-[#222] p-12 text-center">
                    <FileCode size={32} className="text-gray-700 mx-auto mb-2" />
                    <p className="text-sm text-gray-500">Nenhuma atividade registada neste dia.</p>
                    {data.history_dir === null && (
                      <p className="text-xs text-gray-600 mt-2">
                        VS Code Local History não encontrado em <code>~/Library/Application Support/Code/User/History/</code>
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="space-y-4">
                    {allCards.map(p => (
                      <ProjectCard
                        key={p.path || p.name}
                        project={p}
                        date={date}
                        hasActivity={p.saves > 0}
                        onChanged={refreshTotals}
                        favorite={favPaths.has(p.path)}
                        onToggleFavorite={() => toggleFavorite(p.path, p.name)}
                      />
                    ))}
                  </div>
                )}
                <AllProjectsSection
                  date={date}
                  projects={known}
                  excludePaths={excludeFromAll}
                  onChanged={refreshTotals}
                  onToggleFavorite={toggleFavorite}
                />
              </>
            );
          })()}
        </>
      )}
      </>)}
    </div>
  );
}

function AllProjectsSection({
  date, projects, excludePaths, onChanged, onToggleFavorite,
}: {
  date: string;
  projects: CodeKnownProject[];
  excludePaths: Set<string>;
  onChanged: () => void;
  onToggleFavorite: (path: string, name: string) => void;
}) {
  const [open, setOpen] = useState(false);

  const others = projects
    .filter(p => !excludePaths.has(p.path))
    .sort((a, b) => (b.last_activity || '').localeCompare(a.last_activity || ''));

  return (
    <div className="mt-6 bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 p-4 hover:bg-white/5"
      >
        <FolderOpen size={18} className="text-gray-400 shrink-0" />
        <span className="text-sm font-semibold">Todos os projectos</span>
        <span className="text-[11px] text-gray-600">abrir notas/TODOs de projectos antigos</span>
        <ChevronDown
          size={18}
          className={`ml-auto text-gray-500 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && (
        <div className="border-t border-[#222] p-3 space-y-3">
          {others.length === 0 && (
            <p className="text-xs text-gray-600 text-center py-4">Sem outros projectos guardados.</p>
          )}
          {others.map(p => (
            <KnownProjectRow
              key={p.path}
              project={p}
              date={date}
              onChanged={onChanged}
              onToggleFavorite={() => onToggleFavorite(p.path, p.name)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function KnownProjectRow({
  project, date, onChanged, onToggleFavorite,
}: {
  project: CodeKnownProject;
  date: string;
  onChanged: () => void;
  onToggleFavorite: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const asActivity: CodeActivityProject = {
    name: project.name,
    path: project.path,
    saves: 0,
    files_count: 0,
    files: [],
    last_ts: 0,
  };
  const starBtn = (
    <button
      onClick={(e) => { e.stopPropagation(); onToggleFavorite(); }}
      title={project.favorite ? 'Remover dos favoritos' : 'Marcar como favorito'}
      className={`shrink-0 transition-colors ${
        project.favorite ? 'text-blue-400' : 'text-gray-600 hover:text-blue-400'
      }`}
    >
      <Star size={15} fill={project.favorite ? 'currentColor' : 'none'} />
    </button>
  );
  if (!expanded) {
    return (
      <div className="flex items-center gap-3 p-3 rounded-xl bg-[#1a1a1a] hover:bg-white/5">
        {starBtn}
        <button onClick={() => setExpanded(true)} className="flex items-center gap-3 flex-1 min-w-0 text-left">
          <FolderGit2 size={16} className="text-blue-400 shrink-0" />
          <div className="min-w-0">
            <p className="text-sm font-semibold truncate">{project.name}</p>
            {project.path && project.path !== project.name && (
              <p className="text-[10px] text-gray-600 truncate">~/{project.path}</p>
            )}
          </div>
          <div className="ml-auto flex items-center gap-3 shrink-0 text-[11px]">
            {project.open_todos > 0 && <span className="text-emerald-400">{project.open_todos} TODOs</span>}
            {project.notes_count > 0 && <span className="text-purple-400">{project.notes_count} notas</span>}
          </div>
        </button>
      </div>
    );
  }
  return (
    <div className="flex items-start gap-3">
      <div className="pt-4">{starBtn}</div>
      <div className="flex-1 min-w-0">
        <ProjectCard project={asActivity} date={date} hasActivity={false} onChanged={onChanged} defaultExpanded />
      </div>
    </div>
  );
}

function WakaTimePanel() {
  const [range, setRange] = useState('last_7_days');
  const [data, setData] = useState<WakaSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);

  const load = (key: string) => {
    setLoading(true);
    wakatimeApi.summary(key)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(range); }, [range]);

  const sync = async () => {
    if (syncing) return;
    setSyncing(true);
    try {
      await wakatimeApi.sync(14);
      load(range);
    } catch { /* ignora */ } finally { setSyncing(false); }
  };

  if (loading && !data) {
    return <div className="text-center text-gray-600 text-sm py-12">A carregar tempo de código...</div>;
  }

  if (data && !data.configured) {
    return (
      <div className="bg-[#161616] rounded-2xl border border-[#222] p-8 text-center">
        <Clock size={28} className="text-cyan-400/60 mx-auto mb-3" />
        <p className="text-sm text-gray-400 mb-1">WakaTime ainda não está configurado.</p>
        <p className="text-xs text-gray-600">
          Adiciona <code>WAKATIME_API_KEY</code> ao <code>backend/.env</code> (wakatime.com → Settings → API Key) e reinicia o backend.
        </p>
      </div>
    );
  }

  if (!data) return null;

  const maxDay = Math.max(1, ...data.days.map(d => d.total_seconds));
  const isToday = data.range_key === 'today';
  const pct = data.today_vs_avg_pct;
  const cmpText = pct === 0
    ? 'igual à média'
    : `${Math.abs(pct)}% ${pct < 0 ? 'abaixo' : 'acima'} da média`;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-end gap-2">
        <select
          value={range}
          onChange={e => setRange(e.target.value)}
          className="bg-[#1a1a1a] border border-[#222] rounded-lg px-3 py-1.5 text-xs font-semibold text-cyan-300 focus:outline-none focus:border-cyan-500/50"
        >
          {WAKA_RANGES.map(r => (
            <option key={r.key} value={r.key} className="bg-[#161616] text-gray-200">{r.label}</option>
          ))}
        </select>
        <button
          onClick={sync}
          disabled={syncing}
          title="Sincronizar com WakaTime"
          className="p-2 bg-[#161616] border border-[#222] rounded-lg text-gray-500 hover:text-cyan-300 disabled:opacity-40"
        >
          <RefreshCw size={15} className={syncing ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <WakaTile
          label="⏱️ Hoje"
          value={data.today_text || '0m'}
          sub={cmpText}
          subColor={pct < 0 ? 'text-orange-400' : pct > 0 ? 'text-emerald-400' : undefined}
          accent
        />
        <WakaTile label="📊 Total" value={data.total_text || '0m'} sub={data.range_label} />
        <WakaTile label="📈 Média / dia" value={data.daily_average_text || '0m'} sub={`${data.active_days} dias activos`} />
        <WakaTile
          label="🏆 Melhor dia"
          value={data.best_day ? data.best_day.text : '—'}
          sub={data.best_day ? format(parseISO(data.best_day.date), "EEE, d 'de' MMM", { locale: pt }) : undefined}
        />
      </div>

      {!isToday && data.days.length > 1 && (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
          <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4">Tempo de código por dia</h3>
          <div className="flex items-end gap-1.5">
            {data.days.map(d => {
              const h = (d.total_seconds / maxDay) * 100;
              const hours = d.total_seconds / 3600;
              const showValue = data.days.length <= 14;
              return (
                <div key={d.date} className="flex-1 flex flex-col items-center gap-1 group min-w-0">
                  <span className={`text-[9px] text-cyan-300/80 whitespace-nowrap ${showValue ? '' : 'opacity-0 group-hover:opacity-100'}`}>
                    {d.total_seconds > 0 ? (showValue ? `${hours.toFixed(1)}h` : d.text) : ''}
                  </span>
                  <div className="w-full h-28 flex items-end">
                    <div
                      className="w-full rounded-t-md bg-cyan-400/40 group-hover:bg-cyan-400/70 transition-all"
                      style={{ height: `${Math.max(3, h)}%` }}
                      title={`${format(parseISO(d.date), "EEEE, d 'de' MMM", { locale: pt })}: ${d.text}`}
                    />
                  </div>
                  {data.days.length <= 31 && (
                    <span className="text-[9px] text-gray-600">
                      {data.days.length <= 7 ? format(parseISO(d.date), 'EEE', { locale: pt }) : format(parseISO(d.date), 'd')}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4">Código com IA</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
          <WakaMini label="AI Coding" value={`${data.ai.coding_pct}%`} accent />
          <WakaMini label="Linhas IA" value={data.ai.ai_lines_text} />
          <WakaMini label="Linhas humanas" value={data.ai.human_lines_text} />
          <WakaMini label="Tokens" value={data.ai.tokens_text} sub={`${data.ai.input_tokens_text}↓ ${data.ai.output_tokens_text}↑`} />
          <WakaMini label="Custo estimado" value={data.ai.cost_text} />
          <WakaMini label="Sessões IA" value={String(data.ai.sessions)} sub={`${data.ai.prompts} prompts`} />
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[11px] text-cyan-300 w-24 shrink-0">IA {data.ai.ai_line_pct}%</span>
          <div className="flex-1 h-2.5 bg-[#1a1a1a] rounded-full overflow-hidden flex">
            <div className="h-full bg-cyan-400/70" style={{ width: `${data.ai.ai_line_pct}%` }} />
            <div className="h-full bg-gray-600/60" style={{ width: `${100 - data.ai.ai_line_pct}%` }} />
          </div>
          <span className="text-[11px] text-gray-500 w-24 text-right shrink-0">{100 - data.ai.ai_line_pct}% humano</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <WakaBreakdown title={`Projectos · ${data.range_label}`} items={data.projects} max={8} />
        <WakaBreakdown title="Projectos hoje" items={data.today_projects} max={8} />
        <WakaBreakdown title="Linguagens" items={data.languages} max={8} />
        <WakaBreakdown title="Categorias" items={data.categories} max={6} />
      </div>
    </div>
  );
}

function WakaProjectsPanel() {
  const [range, setRange] = useState('all_time');
  const [data, setData] = useState<WakaSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);

  const load = (key: string) => {
    setLoading(true);
    wakatimeApi.summary(key)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(range); }, [range]);

  const sync = async () => {
    if (syncing) return;
    setSyncing(true);
    try {
      await wakatimeApi.sync(14);
      load(range);
    } catch { /* ignora */ } finally { setSyncing(false); }
  };

  if (loading && !data) {
    return <div className="text-center text-gray-600 text-sm py-12">A carregar projectos...</div>;
  }

  if (data && !data.configured) {
    return (
      <div className="bg-[#161616] rounded-2xl border border-[#222] p-8 text-center">
        <FolderKanban size={28} className="text-cyan-400/60 mx-auto mb-3" />
        <p className="text-sm text-gray-400 mb-1">WakaTime ainda não está configurado.</p>
        <p className="text-xs text-gray-600">
          Adiciona <code>WAKATIME_API_KEY</code> ao <code>backend/.env</code> e reinicia o backend.
        </p>
      </div>
    );
  }

  if (!data) return null;

  const details = data.project_details;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-gray-500">
          <span className="text-gray-300 font-semibold">{details.length}</span> projecto{details.length === 1 ? '' : 's'}
          {' · '}<span className="text-cyan-300 font-semibold">{data.total_text || '0m'}</span> no total
        </p>
        <div className="flex items-center gap-2">
          <select
            value={range}
            onChange={e => setRange(e.target.value)}
            className="bg-[#1a1a1a] border border-[#222] rounded-lg px-3 py-1.5 text-xs font-semibold text-cyan-300 focus:outline-none focus:border-cyan-500/50"
          >
            {WAKA_PROJECT_RANGES.map(r => (
              <option key={r.key} value={r.key} className="bg-[#161616] text-gray-200">{r.label}</option>
            ))}
          </select>
          <button
            onClick={sync}
            disabled={syncing}
            title="Sincronizar com WakaTime"
            className="p-2 bg-[#161616] border border-[#222] rounded-lg text-gray-500 hover:text-cyan-300 disabled:opacity-40"
          >
            <RefreshCw size={15} className={syncing ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {details.length === 0 ? (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-12 text-center">
          <FolderKanban size={32} className="text-gray-700 mx-auto mb-2" />
          <p className="text-sm text-gray-500">Sem projectos neste período.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {details.map(p => <WakaProjectDetailCard key={p.name} p={p} />)}
        </div>
      )}
    </div>
  );
}

function WakaProjectDetailCard({ p }: { p: WakaProjectDetail }) {
  const hasAi = p.ai_changes > 0 || p.human_changes > 0 || p.ai_prompts > 0;
  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
      <div className="flex items-baseline justify-between gap-2 mb-3">
        <p className="text-sm font-semibold truncate" title={p.name}>{p.name}</p>
        <span className="text-sm font-bold text-cyan-300 shrink-0">{p.text}</span>
      </div>
      {!hasAi ? (
        <p className="text-[11px] text-gray-600">Sem métricas de IA neste período.</p>
      ) : (
        <div className="grid grid-cols-3 gap-3">
          <WakaStat label="AI changes" value={p.ai_changes_text} sub={`${p.ai_changes_pct}%`} accent />
          <WakaStat label="Humanas" value={p.human_changes_text} sub={`${p.human_changes_pct}%`} />
          <WakaStat label="Custo IA" value={p.ai_cost_text} />
          <WakaStat label="AI prompts" value={String(p.ai_prompts)} sub={`${p.ai_prompt_avg_chars} chars/méd`} />
          <WakaStat label="Sessões IA" value={String(p.ai_sessions)} sub={`${p.ai_avg_prompts_per_session} prompts/méd`} />
          <WakaStat label="Tokens" value={p.tokens_text} sub={`${p.input_tokens_text}↓ ${p.output_tokens_text}↑`} />
        </div>
      )}
    </div>
  );
}

function WakaStat({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div>
      <p className="text-[10px] text-gray-500 truncate" title={label}>{label}</p>
      <p className={`text-sm font-bold ${accent ? 'text-cyan-300' : ''}`}>{value}</p>
      {sub && <p className="text-[9px] text-gray-600 truncate" title={sub}>{sub}</p>}
    </div>
  );
}

function WakaMini({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div className="bg-[#1a1a1a] rounded-xl p-3">
      <p className="text-[10px] text-gray-500 mb-1 truncate" title={label}>{label}</p>
      <p className={`text-lg font-bold ${accent ? 'text-cyan-300' : ''}`}>{value}</p>
      {sub && <p className="text-[9px] text-gray-600 mt-0.5 truncate" title={sub}>{sub}</p>}
    </div>
  );
}

function WakaTile({ label, value, sub, subColor, accent }: { label: string; value: string; sub?: string; subColor?: string; accent?: boolean }) {
  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${accent ? 'text-cyan-300' : ''}`}>{value}</p>
      {sub && <p className={`text-[10px] mt-0.5 ${subColor || 'text-gray-600'}`}>{sub}</p>}
    </div>
  );
}

function WakaBreakdown({ title, items, max }: { title: string; items: WakaBreakdownItem[]; max: number }) {
  const top = items.slice(0, max);
  const maxVal = Math.max(1, ...items.map(i => i.total_seconds));
  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
      <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4">{title}</h3>
      {top.length === 0 ? (
        <p className="text-xs text-gray-600 text-center py-2">Sem dados neste período.</p>
      ) : (
        <div className="space-y-2.5">
          {top.map(i => (
            <div key={i.name} className="flex items-center gap-3">
              <span className="text-xs text-gray-300 w-32 truncate shrink-0" title={i.name}>{i.name}</span>
              <div className="flex-1 h-2 bg-[#1a1a1a] rounded-full overflow-hidden">
                <div className="h-full bg-cyan-400/60 rounded-full" style={{ width: `${(i.total_seconds / maxVal) * 100}%` }} />
              </div>
              <span className="text-xs text-gray-500 w-16 text-right shrink-0">{i.text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SummaryTile({ label, value, accent }: { label: string; value: number; accent?: 'emerald' | 'purple' }) {
  const ring = accent === 'emerald'
    ? 'border-emerald-500/30'
    : accent === 'purple'
    ? 'border-purple-500/30'
    : 'border-[#222]';
  return (
    <div className={`bg-[#161616] rounded-2xl border ${ring} p-4`}>
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className="text-2xl font-bold">{value}</p>
    </div>
  );
}

function ProjectCard({
  project, date, hasActivity, onChanged, defaultExpanded = true, favorite, onToggleFavorite,
}: {
  project: CodeActivityProject;
  date: string;
  hasActivity: boolean;
  onChanged: () => void;
  defaultExpanded?: boolean;
  favorite?: boolean;
  onToggleFavorite?: () => void;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [showFiles, setShowFiles] = useState(false);
  const [leftTab, setLeftTab] = useState<'notas' | 'todos'>('notas');
  const [todoReload, setTodoReload] = useState(0);

  const handleConverted = () => {
    setTodoReload(k => k + 1);
    setLeftTab('todos');
    onChanged();
  };
  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
      <div className="w-full flex items-center justify-between p-4 hover:bg-white/5">
        {onToggleFavorite && (
          <button
            onClick={onToggleFavorite}
            title={favorite ? 'Remover dos favoritos' : 'Marcar como favorito'}
            className={`mr-3 shrink-0 transition-colors ${
              favorite ? 'text-blue-400' : 'text-gray-600 hover:text-blue-400'
            }`}
          >
            <Star size={16} fill={favorite ? 'currentColor' : 'none'} />
          </button>
        )}
        <button
          onClick={() => setExpanded(e => !e)}
          className="flex items-center gap-3 min-w-0 flex-1 text-left"
        >
          <FolderGit2 size={18} className="text-blue-400 shrink-0" />
          <div className="min-w-0">
            <p className="text-sm font-semibold truncate">{project.name}</p>
            {project.path && project.path !== project.name && (
              <p className="text-[10px] text-gray-600 truncate">~/{project.path}</p>
            )}
          </div>
        </button>
        <button
          onClick={() => setExpanded(e => !e)}
          className="flex items-center gap-3 shrink-0 pl-3"
        >
          <span className="text-xs text-gray-500">{project.files_count} ficheiros</span>
          <span className="text-sm font-bold text-blue-400">{project.saves} saves</span>
        </button>
      </div>
      {expanded && (
        <div className="border-t border-[#222]">
          <div className="px-4 pt-3 flex items-center justify-between">
            <button
              onClick={() => setShowFiles(s => !s)}
              className="text-[11px] text-gray-500 hover:text-gray-300 flex items-center gap-1"
            >
              <FileCode size={12} />
              {showFiles ? 'Esconder' : 'Mostrar'} {project.files_count} ficheiros
            </button>
          </div>
          {showFiles && (
            <div className="divide-y divide-[#1a1a1a] mx-4 my-2 rounded-lg border border-[#222] overflow-hidden">
              {project.files.map(f => (
                <div key={f.abs_path} className="flex items-center gap-3 p-2 hover:bg-white/5">
                  <span className="text-base shrink-0">{fileIcon(f.filename)}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm truncate">{f.filename}</p>
                    <p className="text-[10px] text-gray-600 truncate">{f.rel_path}</p>
                  </div>
                  <span className="text-xs text-gray-500 shrink-0">{f.saves}×</span>
                </div>
              ))}
            </div>
          )}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-px bg-[#222] mt-2">
            <div className="bg-[#161616]">
              <div className="px-4 pt-4">
                <div className="inline-flex rounded-xl bg-[#1a1a1a] border border-[#222] p-0.5">
                  <button
                    onClick={() => setLeftTab('notas')}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                      leftTab === 'notas' ? 'bg-blue-500/20 text-blue-300' : 'text-gray-500 hover:text-gray-300'
                    }`}
                  >
                    <FileCode size={13} /> Notas
                  </button>
                  <button
                    onClick={() => setLeftTab('todos')}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                      leftTab === 'todos' ? 'bg-emerald-500/20 text-emerald-400' : 'text-gray-500 hover:text-gray-300'
                    }`}
                  >
                    <ListChecks size={13} /> TODOs
                  </button>
                </div>
              </div>
              {leftTab === 'todos' ? (
                <TodosPanel projectPath={project.path} reloadKey={todoReload} onChanged={onChanged} />
              ) : (
                <NotesPanel
                  projectPath={project.path}
                  mode="manual"
                  date={date}
                  hasActivity={hasActivity}
                  onChanged={onChanged}
                  onConverted={handleConverted}
                />
              )}
            </div>
            <div className="bg-[#161616]">
              <NotesPanel
                projectPath={project.path}
                mode="ai"
                date={date}
                hasActivity={hasActivity}
                onChanged={onChanged}
                onConverted={handleConverted}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function TodosPanel({ projectPath, reloadKey = 0, onChanged }: { projectPath: string; reloadKey?: number; onChanged: () => void }) {
  const [todos, setTodos] = useState<CodeProjectTodo[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);

  const load = () => {
    codeActivityApi.listTodos(projectPath).then(setTodos).catch(() => {});
  };
  useEffect(() => { load(); }, [projectPath, reloadKey]);

  const add = async () => {
    const c = input.trim();
    if (!c || busy) return;
    setBusy(true);
    try {
      const t = await codeActivityApi.createTodo(projectPath, c);
      setTodos(prev => [t, ...prev]);
      setInput('');
      onChanged();
    } finally { setBusy(false); }
  };

  const toggle = async (t: CodeProjectTodo) => {
    const updated = await codeActivityApi.updateTodo(t.id, { done: !t.done });
    setTodos(prev => prev.map(x => x.id === t.id ? updated : x));
    onChanged();
  };

  const remove = async (id: number) => {
    await codeActivityApi.deleteTodo(id);
    setTodos(prev => prev.filter(x => x.id !== id));
    onChanged();
  };

  const open = todos.filter(t => !t.done);
  const done = todos.filter(t => t.done);

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <ListChecks size={14} className="text-emerald-400" />
        <h4 className="text-xs font-bold text-emerald-400 uppercase tracking-wider">TODOs</h4>
        <span className="text-[10px] text-gray-600 ml-auto">{todos.filter(t => !t.done).length} abertos</span>
      </div>
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && add()}
          placeholder="Nova TODO..."
          className="flex-1 bg-[#1a1a1a] border border-[#222] rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-emerald-500/50"
        />
        <button
          onClick={add}
          disabled={!input.trim() || busy}
          className="p-1.5 bg-emerald-500/20 hover:bg-emerald-500/30 disabled:opacity-30 text-emerald-400 rounded-lg"
        >
          <Plus size={16} />
        </button>
      </div>
      {todos.length === 0 ? (
        <p className="text-xs text-gray-600 text-center py-4">Sem TODOs neste projecto.</p>
      ) : (
        <div className="space-y-1">
          {open.map(t => <TodoRow key={t.id} todo={t} onToggle={() => toggle(t)} onDelete={() => remove(t.id)} />)}
          {done.length > 0 && (
            <p className="text-[10px] text-gray-600 uppercase tracking-wider mt-3 mb-1">Feitas</p>
          )}
          {done.map(t => <TodoRow key={t.id} todo={t} onToggle={() => toggle(t)} onDelete={() => remove(t.id)} />)}
        </div>
      )}
    </div>
  );
}

function TodoRow({ todo, onToggle, onDelete }: { todo: CodeProjectTodo; onToggle: () => void; onDelete: () => void }) {
  return (
    <div className="flex items-center gap-2 group py-1">
      <input
        type="checkbox"
        checked={todo.done}
        onChange={onToggle}
        className="accent-emerald-500"
      />
      <span className={`flex-1 text-sm ${todo.done ? 'line-through text-gray-600' : ''}`}>{todo.content}</span>
      <button
        onClick={onDelete}
        className="opacity-0 group-hover:opacity-100 text-gray-600 hover:text-red-400 transition-opacity"
      >
        <Trash2 size={13} />
      </button>
    </div>
  );
}

function NotesPanel({
  projectPath, mode, date, hasActivity, onChanged, onConverted,
}: {
  projectPath: string;
  mode: 'manual' | 'ai';
  date: string;
  hasActivity: boolean;
  onChanged: () => void;
  onConverted: () => void;
}) {
  const isAi = mode === 'ai';
  const [allNotes, setAllNotes] = useState<CodeProjectNote[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [convertingId, setConvertingId] = useState<number | null>(null);
  const [convertError, setConvertError] = useState<string | null>(null);
  const autoTried = useRef<string>('');

  const notes = allNotes.filter(n => (isAi ? n.source === 'ai' : n.source !== 'ai'));

  const convert = async (id: number) => {
    if (convertingId !== null) return;
    setConvertingId(id);
    setConvertError(null);
    try {
      await codeActivityApi.noteToTodos(id);
      onConverted();
    } catch (e: any) {
      setConvertError(e?.message || 'Erro a converter');
    } finally { setConvertingId(null); }
  };

  const load = () => {
    codeActivityApi.listNotes(projectPath)
      .then(ns => { setAllNotes(ns); setLoaded(true); })
      .catch(() => setLoaded(true));
  };
  useEffect(() => { setLoaded(false); load(); }, [projectPath]);

  const add = async () => {
    const c = input.trim();
    if (!c || busy) return;
    setBusy(true);
    try {
      const n = await codeActivityApi.createNote(projectPath, c, date);
      setAllNotes(prev => [n, ...prev]);
      setInput('');
      onChanged();
    } finally { setBusy(false); }
  };

  const generate = async () => {
    if (generating) return;
    setGenerating(true);
    setGenError(null);
    try {
      const n = await codeActivityApi.generateNote(projectPath, date);
      setAllNotes(prev => [n, ...prev]);
      onChanged();
    } catch (e: any) {
      setGenError(e?.message || 'Erro a gerar');
    } finally { setGenerating(false); }
  };

  // Auto-generate AI note for the day if there's activity and no AI note yet for this date
  useEffect(() => {
    if (!isAi || !loaded || !hasActivity) return;
    const key = `${projectPath}|${date}`;
    if (autoTried.current === key) return;
    const hasAiNoteForDate = allNotes.some(n => n.source === 'ai' && n.note_date === date);
    if (hasAiNoteForDate) { autoTried.current = key; return; }
    autoTried.current = key;
    generate();
  }, [isAi, loaded, hasActivity, projectPath, date, allNotes]);

  const remove = async (id: number) => {
    await codeActivityApi.deleteNote(id);
    setAllNotes(prev => prev.filter(x => x.id !== id));
    onChanged();
  };

  const accentText = isAi ? 'text-purple-400' : 'text-blue-300';

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center gap-2 mb-1">
        {isAi ? <Sparkles size={14} className={accentText} /> : <FileCode size={14} className={accentText} />}
        <h4 className={`text-xs font-bold ${accentText} uppercase tracking-wider`}>{isAi ? 'Notas IA' : 'Notas'}</h4>
        {generating && <Loader2 size={12} className="text-purple-400 animate-spin" />}
        <span className="text-[10px] text-gray-600 ml-auto">{notes.length} notas</span>
      </div>
      {isAi ? (
        <div className="flex justify-end">
          <button
            onClick={generate}
            disabled={generating}
            title="Gerar nota com IA a partir da actividade do dia"
            className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-500/20 hover:bg-purple-500/30 disabled:opacity-30 text-purple-400 rounded-lg text-xs font-semibold"
          >
            {generating ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            Gerar
          </button>
        </div>
      ) : (
        <div className="flex items-start gap-2">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Nota sobre o projecto..."
            rows={2}
            className="flex-1 bg-[#1a1a1a] border border-[#222] rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500/50 resize-none"
          />
          <button
            onClick={add}
            disabled={!input.trim() || busy}
            title="Adicionar nota"
            className="p-1.5 bg-blue-500/20 hover:bg-blue-500/30 disabled:opacity-30 text-blue-300 rounded-lg self-stretch"
          >
            <Plus size={16} />
          </button>
        </div>
      )}
      {genError && <p className="text-xs text-red-400">{genError}</p>}
      {convertError && <p className="text-xs text-red-400">{convertError}</p>}
      {notes.length === 0 ? (
        <p className="text-xs text-gray-600 text-center py-4">
          {isAi ? 'Sem notas IA neste projecto.' : 'Sem notas neste projecto.'}
        </p>
      ) : (
        <div className="space-y-2 max-h-[420px] overflow-y-auto pr-1">
          {notes.map(n => (
            <div key={n.id} className="group relative bg-[#1a1a1a] rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-[9px] px-1.5 py-0.5 rounded uppercase tracking-wider ${
                  n.source === 'ai' ? 'bg-purple-500/20 text-purple-400' : 'bg-gray-700/40 text-gray-400'
                }`}>{n.source === 'ai' ? '✨ IA' : 'Manual'}</span>
                {n.note_date && <span className="text-[10px] text-gray-600">{n.note_date}</span>}
                <span className="text-[10px] text-gray-700 ml-auto">
                  {format(parseISO(n.created_at), "d MMM HH:mm", { locale: pt })}
                </span>
                <button
                  onClick={() => convert(n.id)}
                  disabled={convertingId !== null}
                  title="Transformar em TODOs (um por linha)"
                  className="opacity-0 group-hover:opacity-100 text-gray-600 hover:text-emerald-400 transition-opacity disabled:opacity-50"
                >
                  {convertingId === n.id ? <Loader2 size={12} className="animate-spin" /> : <ListPlus size={12} />}
                </button>
                <button
                  onClick={() => remove(n.id)}
                  className="opacity-0 group-hover:opacity-100 text-gray-600 hover:text-red-400 transition-opacity"
                >
                  <Trash2 size={12} />
                </button>
              </div>
              <p className="text-sm text-gray-300 whitespace-pre-wrap">{n.content}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
