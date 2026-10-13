import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { format, parseISO } from 'date-fns';
import { pt } from 'date-fns/locale';
import { Code2, ChevronRight, ChevronDown, FileCode, FolderOpen, ListChecks, ListPlus, Sparkles, Plus, Star, Trash2, Loader2, Clock, RefreshCw, FolderKanban, StickyNote, Pencil, FileDown, AlertTriangle, FilePlus2, Link2, Unlink, Search, X } from 'lucide-react';
import {
  codeActivityApi,
  CodeActivityDay,
  CodeActivityProject,
  CodeProjectTodo,
  CodeProjectNote,
  CodeKnownProject,
  notesApi,
  wakatimeApi,
  WakaSummary,
  WakaHours,
  WakaBreakdownItem,
  WakaProjectDetail,
  WakaAiTrend,
  WAKA_RANGES,
  WAKA_PROJECT_RANGES,
} from '../api';
import { Note } from '../types';
import { ModeToggle, NoteBody, viewModeKey } from '../components/NoteBody';

// Rascunhos por escrever ficam guardados para sobreviverem a mudar de secção.
const draftKey = (kind: 'nota' | 'todo', projectPath: string) => `codeDraft:${kind}:${projectPath}`;

function readDraft(kind: 'nota' | 'todo', projectPath: string): string {
  try { return localStorage.getItem(draftKey(kind, projectPath)) || ''; } catch { return ''; }
}

function writeDraft(kind: 'nota' | 'todo', projectPath: string, value: string) {
  try {
    if (value) localStorage.setItem(draftKey(kind, projectPath), value);
    else localStorage.removeItem(draftKey(kind, projectPath));
  } catch { /* ignora */ }
}

// O backend grava os timestamps em UTC sem sufixo; sem isto a hora aparecia atrasada.
function localDate(ts: string): Date {
  return new Date(/([zZ]|[+-]\d{2}:?\d{2})$/.test(ts) ? ts : `${ts}Z`);
}

// Último projecto seleccionado na aba Atividade.
const SELECTED_KEY = 'codeActivitySelected';

function readSelected(): string | null {
  try { return localStorage.getItem(SELECTED_KEY); } catch { return null; }
}

function writeSelected(path: string) {
  try { localStorage.setItem(SELECTED_KEY, path); } catch { /* ignora */ }
}

// Vista activa do projecto: a nota da secção Notas sozinha, os painéis
// completos (notas/TODOs + notas IA), ou a nota com os TODOs e sem a IA.
const VIEW_KEY = 'codeActivityView';
type ProjectView = 'nota' | 'paineis' | 'nota_todos';

function readView(): ProjectView {
  try {
    const v = localStorage.getItem(VIEW_KEY);
    return v === 'nota' || v === 'nota_todos' ? v : 'paineis';
  } catch { return 'paineis'; }
}

function writeView(v: ProjectView) {
  try { localStorage.setItem(VIEW_KEY, v); } catch { /* ignora */ }
}

// Altura disponível até ao fundo da janela, para o board não fazer scroll de página.
// Selector de período do WakaTime: "m:2026-07" → mês, "y:2026" → ano, resto → range nomeado.
function periodToArg(v: string): string | { range?: string; month?: string; year?: number } {
  if (v.startsWith('m:')) return { month: v.slice(2) };
  if (v.startsWith('y:')) return { year: Number(v.slice(2)) };
  return v;
}

function monthLabel(m: string): string {
  const s = format(parseISO(`${m}-01`), 'MMMM yyyy', { locale: pt });
  return s.charAt(0).toUpperCase() + s.slice(1);
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
  const [date] = useState(today);
  const [data, setData] = useState<CodeActivityDay | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [todoProjects, setTodoProjects] = useState<{ path: string; name: string }[]>([]);
  const [known, setKnown] = useState<CodeKnownProject[]>([]);
  const [knownLoaded, setKnownLoaded] = useState(false);
  const [tab, setTab] = useState<'atividade' | 'tempo' | 'projectos'>('atividade');

  const refreshKnown = () => {
    codeActivityApi.allProjects()
      .then(setKnown)
      .catch(() => {})
      .finally(() => setKnownLoaded(true));
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

  const refreshTotals = () => {
    codeActivityApi.projectsWithTodos().then(setTodoProjects).catch(() => {});
  };
  useEffect(() => { refreshTotals(); }, []);

  const dateLabel = format(parseISO(date), "d 'de' MMMM yyyy", { locale: pt });
  const weekday = format(parseISO(date), 'EEEE', { locale: pt });

  return (
    <div className={`flex flex-col ${tab === 'atividade'
      ? 'max-w-7xl mx-auto lg:h-[calc(100dvh-4rem)] lg:overflow-hidden'
      : 'max-w-6xl mx-auto'}`}>
      {/* A data vai por baixo do título: entalada a meio, entre o título e as
          abas, ficava por cima dos dois em qualquer largura de iPad. */}
      <div className="flex items-center justify-between gap-x-3 gap-y-2 mb-4 flex-wrap shrink-0">
        <div className="flex items-center gap-3 shrink-0">
          <Code2 size={28} className="text-blue-400 shrink-0" />
          <div>
            <h2 className="text-2xl sm:text-3xl font-bold whitespace-nowrap">Atividade VS Code</h2>
            {tab === 'atividade' && (
              <p className="text-xs text-gray-500 whitespace-nowrap first-letter:uppercase">{weekday}, {dateLabel}</p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3 flex-wrap min-w-0 max-w-full">
          {/* No telemóvel as três abas não cabem: rolam em vez de esticarem a página */}
          <div className="flex items-center gap-2 border-b border-[#222] max-w-full overflow-x-auto">
            <button
              onClick={() => setTab('atividade')}
              className={`shrink-0 whitespace-nowrap px-3 sm:px-4 py-2 text-sm font-semibold border-b-2 -mb-px transition-colors ${
                tab === 'atividade' ? 'border-blue-400 text-blue-300' : 'border-transparent text-gray-500 hover:text-gray-300'
              }`}
            >
              Atividade
            </button>
            <button
              onClick={() => setTab('tempo')}
              className={`shrink-0 whitespace-nowrap flex items-center gap-1.5 px-3 sm:px-4 py-2 text-sm font-semibold border-b-2 -mb-px transition-colors ${
                tab === 'tempo' ? 'border-cyan-400 text-cyan-300' : 'border-transparent text-gray-500 hover:text-gray-300'
              }`}
            >
              <Clock size={14} /> Tempo de código
            </button>
            <button
              onClick={() => setTab('projectos')}
              className={`shrink-0 whitespace-nowrap flex items-center gap-1.5 px-3 sm:px-4 py-2 text-sm font-semibold border-b-2 -mb-px transition-colors ${
                tab === 'projectos' ? 'border-cyan-400 text-cyan-300' : 'border-transparent text-gray-500 hover:text-gray-300'
              }`}
            >
              <FolderKanban size={14} /> Projectos
            </button>
          </div>
        </div>
      </div>

      {tab === 'tempo' && <WakaTimePanel />}
      {tab === 'projectos' && <WakaProjectsPanel />}

      {tab === 'atividade' && (
        <div className="flex-1 min-h-0 flex flex-col">
          <ActivityBoard
            date={date}
            data={data}
            loading={loading}
            error={error}
            known={known}
            knownLoaded={knownLoaded}
            favPaths={favPaths}
            todoProjects={todoProjects}
            onToggleFavorite={toggleFavorite}
            onChanged={refreshTotals}
          />
        </div>
      )}
    </div>
  );
}

function ActivityBoard({
  date,
  data, loading, error, known, knownLoaded, favPaths, todoProjects, onToggleFavorite, onChanged,
}: {
  date: string;
  data: CodeActivityDay | null;
  loading: boolean;
  error: string | null;
  known: CodeKnownProject[];
  knownLoaded: boolean;
  favPaths: Set<string>;
  todoProjects: { path: string; name: string }[];
  onToggleFavorite: (path: string, name: string) => void;
  onChanged: () => void;
}) {
  const [selected, setSelected] = useState<string | null>(() => readSelected());
  const [showAll, setShowAll] = useState(false);
  const [view, setView] = useState<ProjectView>(() => readView());
  const [showFiles, setShowFiles] = useState(false);

  const activePaths = new Set((data?.projects || []).map(p => p.path));
  const todoOnly: CodeActivityProject[] = todoProjects
    .filter(t => !activePaths.has(t.path))
    .map(t => ({ name: t.name, path: t.path, saves: 0, files_count: 0, files: [], last_ts: 0 }));
  const dayAll = [...(data?.projects || []), ...todoOnly];

  // Favoritos ficam sempre no topo, mesmo sem actividade no dia.
  const favCards: CodeActivityProject[] = known
    .filter(k => k.favorite)
    .map(k => dayAll.find(p => p.path === k.path) ?? {
      name: k.name, path: k.path, saves: 0, files_count: 0, files: [], last_ts: 0,
    });
  const dayCards = dayAll.filter(p => !favPaths.has(p.path));
  const mainList = [...favCards, ...dayCards];

  const mainPaths = new Set(mainList.map(p => p.path));
  const others: CodeActivityProject[] = known
    .filter(k => !mainPaths.has(k.path))
    .sort((a, b) => (b.last_activity || '').localeCompare(a.last_activity || ''))
    .map(k => ({ name: k.name, path: k.path, saves: 0, files_count: 0, files: [], last_ts: 0 }));

  // O projecto guardado manda, mesmo que hoje não tenha actividade — só se cai
  // para o primeiro da lista quando já se sabe que ele não existe.
  const resolved = selected
    ? mainList.find(p => p.path === selected) ?? others.find(p => p.path === selected)
    : undefined;
  const settled = knownLoaded && !loading;
  const current = resolved ?? (!selected || settled ? mainList[0] : undefined);

  const pinned = resolved && !mainList.some(p => p.path === resolved.path) && !showAll ? [resolved] : [];
  const visible = showAll ? [...mainList, ...others] : [...pinned, ...mainList];

  const pick = (path: string) => {
    setSelected(path);
    writeSelected(path);
  };

  const pickView = (v: ProjectView) => { setView(v); writeView(v); };

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-2.5 mb-3 text-sm text-red-400 shrink-0">
          {error}
        </div>
      )}

      <div className="shrink-0 mb-3 bg-[#161616] rounded-2xl border border-[#222]">
        <div className="flex items-center gap-2 p-1.5 flex-wrap sm:flex-nowrap">
          <div className="w-full sm:w-auto sm:flex-1 min-w-0 flex items-center gap-1.5 overflow-x-auto">
            {loading && !data && <span className="text-xs text-gray-600 px-2">A carregar...</span>}
            {!loading && visible.length === 0 && (
              <span className="text-xs text-gray-600 px-2">Nenhuma atividade neste dia.</span>
            )}
            {visible.map(p => (
              <ProjectChip
                key={p.path || p.name}
                project={p}
                active={current?.path === p.path}
                favorite={favPaths.has(p.path)}
                onSelect={() => pick(p.path)}
                onToggleFavorite={() => onToggleFavorite(p.path, p.name)}
              />
            ))}
          </div>
          <div className="w-full sm:w-auto shrink-0 flex items-center gap-1.5 flex-nowrap overflow-x-auto
                          sm:pl-1.5 sm:border-l border-[#222]">
            {others.length > 0 && (
              <button
                onClick={() => setShowAll(s => !s)}
                title={showAll ? 'Mostrar só os do dia' : 'Mostrar todos os projectos'}
                className={`shrink-0 whitespace-nowrap flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-[11px] font-semibold border transition-colors ${
                  showAll ? 'bg-blue-500/15 border-blue-500/30 text-blue-300' : 'bg-[#1a1a1a] border-[#222] text-gray-500 hover:text-gray-300'
                }`}
              >
                <FolderOpen size={13} />
                {showAll ? 'Todos' : `+${others.length}`}
              </button>
            )}
            {current && current.files_count > 0 && (
              <button
                onClick={() => setShowFiles(s => !s)}
                title="Ficheiros gravados neste dia"
                className={`shrink-0 whitespace-nowrap flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-[11px] font-semibold border transition-colors ${
                  showFiles ? 'bg-blue-500/15 border-blue-500/30 text-blue-300' : 'bg-[#1a1a1a] border-[#222] text-gray-500 hover:text-gray-300'
                }`}
              >
                <FileCode size={13} /> {current.files_count}
                <ChevronDown size={12} className={showFiles ? 'rotate-180' : ''} />
              </button>
            )}
            <div className="inline-flex rounded-xl bg-[#1a1a1a] border border-[#222] p-0.5">
              <button
                onClick={() => pickView('nota')}
                title="Nota deste projecto (secção Notas)"
                className={`shrink-0 whitespace-nowrap flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-semibold transition-colors ${
                  view === 'nota' ? 'bg-blue-500/20 text-blue-300' : 'text-gray-500 hover:text-gray-300'
                }`}
              >
                <StickyNote size={13} /> Nota
              </button>
              <button
                onClick={() => pickView('nota_todos')}
                title="Nota deste projecto e TODOs, sem notas IA"
                className={`shrink-0 whitespace-nowrap flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-semibold transition-colors ${
                  view === 'nota_todos' ? 'bg-blue-500/20 text-blue-300' : 'text-gray-500 hover:text-gray-300'
                }`}
              >
                <ListChecks size={13} /> Nota / TODOs
              </button>
              <button
                onClick={() => pickView('paineis')}
                title="Notas do projecto, notas IA e TODOs"
                className={`shrink-0 whitespace-nowrap flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-semibold transition-colors ${
                  view === 'paineis' ? 'bg-blue-500/20 text-blue-300' : 'text-gray-500 hover:text-gray-300'
                }`}
              >
                <ListChecks size={13} /> Notas / TODOs
              </button>
            </div>
          </div>
        </div>
        {showFiles && current && current.files.length > 0 && (
          <div className="border-t border-[#222] max-h-44 overflow-y-auto divide-y divide-[#1a1a1a]">
            {current.files.map(f => (
              <div key={f.abs_path} className="flex items-center gap-3 px-3 py-1.5 hover:bg-white/5">
                <span className="text-sm shrink-0">{fileIcon(f.filename)}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs truncate">{f.filename}</p>
                  <p className="text-[10px] text-gray-600 truncate">{f.rel_path}</p>
                </div>
                <span className="text-[11px] text-gray-500 shrink-0">{f.saves}×</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {current ? (
        view === 'nota' ? (
          <LinkedNotePanel
            key={`nota-${current.path}`}
            projectPath={current.path}
            projectName={current.name}
          />
        ) : view === 'nota_todos' ? (
          <NoteAndTodosPanels
            key={`nota-todos-${current.path}`}
            project={current}
            onChanged={onChanged}
          />
        ) : (
          <ProjectPanels
            key={`paineis-${current.path}`}
            project={current}
            date={date}
            onChanged={onChanged}
          />
        )
      ) : (
        <div className="flex-1 min-h-0 bg-[#161616] rounded-2xl border border-[#222] flex items-center justify-center">
          <div className="text-center">
            <FileCode size={28} className="text-gray-700 mx-auto mb-2" />
            <p className="text-sm text-gray-600">
              {settled && data?.history_dir === null
                ? 'VS Code Local History não encontrado.'
                : settled ? 'Sem projectos.' : 'A carregar...'}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}


function ProjectChip({
  project, active, favorite, onSelect, onToggleFavorite,
}: {
  project: CodeActivityProject;
  active: boolean;
  favorite: boolean;
  onSelect: () => void;
  onToggleFavorite: () => void;
}) {
  return (
    <div
      onClick={onSelect}
      title={project.path ? `~/${project.path}` : project.name}
      className={`shrink-0 flex items-center gap-1.5 pl-2 pr-3 py-1.5 rounded-xl border cursor-pointer transition-colors ${
        active ? 'bg-blue-500/15 border-blue-500/40' : 'bg-[#1a1a1a] border-transparent hover:bg-white/5'
      }`}
    >
      <button
        onClick={e => { e.stopPropagation(); onToggleFavorite(); }}
        title={favorite ? 'Remover dos favoritos' : 'Marcar como favorito'}
        className={`shrink-0 transition-colors ${favorite ? 'text-blue-400' : 'text-gray-700 hover:text-blue-400'}`}
      >
        <Star size={12} fill={favorite ? 'currentColor' : 'none'} />
      </button>
      <span className={`text-sm whitespace-nowrap ${active ? 'font-semibold text-blue-200' : 'font-medium text-gray-300'}`}>
        {project.name}
      </span>
    </div>
  );
}

function ProjectPanels({
  project, date, onChanged,
}: {
  project: CodeActivityProject;
  date: string;
  onChanged: () => void;
}) {
  const [notesTab, setNotesTab] = useState<'notas' | 'ia'>('notas');
  const [todoReload, setTodoReload] = useState(0);
  const hasActivity = project.saves > 0;

  const handleConverted = () => {
    setTodoReload(k => k + 1);
    onChanged();
  };

  return (
    <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-2 gap-px bg-[#222] rounded-2xl border border-[#222] overflow-hidden">
      <div className="bg-[#161616] flex flex-col min-h-0">
        <div className="px-4 pt-3 shrink-0">
          <div className="inline-flex rounded-xl bg-[#1a1a1a] border border-[#222] p-0.5">
            <button
              onClick={() => setNotesTab('notas')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                notesTab === 'notas' ? 'bg-blue-500/20 text-blue-300' : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              <FileCode size={13} /> Notas
            </button>
            <button
              onClick={() => setNotesTab('ia')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                notesTab === 'ia' ? 'bg-purple-500/20 text-purple-400' : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              <Sparkles size={13} /> Notas IA
            </button>
          </div>
        </div>
        {/* Os dois ficam montados: a nota IA do dia é gerada mesmo sem abrir o separador. */}
        <div className={`flex-1 min-h-0 flex flex-col ${notesTab === 'notas' ? '' : 'hidden'}`}>
          <NotesPanel
            projectPath={project.path}
            mode="manual"
            date={date}
            hasActivity={hasActivity}
            onChanged={onChanged}
            onConverted={handleConverted}
          />
        </div>
        <div className={`flex-1 min-h-0 flex flex-col ${notesTab === 'ia' ? '' : 'hidden'}`}>
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
      <div className="bg-[#161616] flex flex-col min-h-0">
        <TodosPanel projectPath={project.path} reloadKey={todoReload} onChanged={onChanged} />
      </div>
    </div>
  );
}

// A nota (da secção Notas) lado a lado com os TODOs, sem o separador de notas
// IA — para quem só quer estas duas coisas, sem ter de trocar de aba.
function NoteAndTodosPanels({
  project, onChanged,
}: {
  project: CodeActivityProject;
  onChanged: () => void;
}) {
  return (
    <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-2 gap-px bg-[#222] rounded-2xl border border-[#222] overflow-hidden">
      {/* No telemóvel ficam um por cima do outro e sem altura própria a Nota
          encolhia até duas linhas. No computador dividem a altura como antes. */}
      <div className="bg-[#161616] flex flex-col min-h-[320px] lg:min-h-0">
        <LinkedNotePanel projectPath={project.path} projectName={project.name} embedded />
      </div>
      <div className="bg-[#161616] flex flex-col min-h-[320px] lg:min-h-0">
        <TodosPanel projectPath={project.path} reloadKey={0} onChanged={onChanged} />
      </div>
    </div>
  );
}

function WakaTimePanel() {
  const [period, setPeriod] = useState('last_7_days');
  const [periods, setPeriods] = useState<{ months: string[]; years: number[] }>({ months: [], years: [] });
  const [data, setData] = useState<WakaSummary | null>(null);
  const [hours, setHours] = useState<WakaHours | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);

  const load = (p: string) => {
    setLoading(true);
    wakatimeApi.summary(periodToArg(p))
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
    wakatimeApi.hours(periodToArg(p)).then(setHours).catch(() => setHours(null));
  };
  useEffect(() => { load(period); }, [period]);
  useEffect(() => { wakatimeApi.periods().then(setPeriods).catch(() => {}); }, []);

  const sync = async () => {
    if (syncing) return;
    setSyncing(true);
    try {
      await wakatimeApi.sync(14);
      load(period);
      wakatimeApi.periods().then(setPeriods).catch(() => {});
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
          value={period}
          onChange={e => setPeriod(e.target.value)}
          className="bg-[#1a1a1a] border border-[#222] rounded-lg px-3 py-1.5 text-xs font-semibold text-cyan-300 focus:outline-none focus:border-cyan-500/50"
        >
          <optgroup label="Rápido">
            {WAKA_RANGES.map(r => (
              <option key={r.key} value={r.key} className="bg-[#161616] text-gray-200">{r.label}</option>
            ))}
          </optgroup>
          {periods.months.length > 0 && (
            <optgroup label="Por mês">
              {periods.months.map(m => (
                <option key={m} value={`m:${m}`} className="bg-[#161616] text-gray-200">{monthLabel(m)}</option>
              ))}
            </optgroup>
          )}
          {periods.years.length > 0 && (
            <optgroup label="Por ano">
              {periods.years.map(y => (
                <option key={y} value={`y:${y}`} className="bg-[#161616] text-gray-200">{y}</option>
              ))}
            </optgroup>
          )}
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

      <WakaHoursChart hours={hours} />

      <AiTrendPanel />

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

// Custo e peso da IA mês a mês — os dados já vinham do WakaTime, faltava vê-los.
function AiTrendPanel() {
  const [data, setData] = useState<WakaAiTrend | null>(null);
  const [meses, setMeses] = useState(6);

  useEffect(() => { wakatimeApi.aiTrend(meses).then(setData).catch(() => setData(null)); }, [meses]);
  if (!data || data.months.length === 0) return null;

  const maxCost = Math.max(1, ...data.months.map(m => m.cost));
  const fmtLinhas = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
  const fmtH = (s: number) => `${Math.floor(s / 3600)}h`;

  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
      <div className="flex items-baseline justify-between gap-2 mb-4">
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider">Custo e peso da IA</h3>
        <select
          value={meses}
          onChange={e => setMeses(Number(e.target.value))}
          className="bg-[#1a1a1a] border border-[#222] rounded-lg px-2 py-1 text-[11px] text-cyan-300 focus:outline-none"
        >
          {[3, 6, 12, 24].map(n => <option key={n} value={n} className="bg-[#161616] text-gray-200">{n} meses</option>)}
        </select>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        <WakaMini label="Custo total" value={`${data.total_cost.toFixed(2)}`} accent />
        <WakaMini label="Linhas IA" value={fmtLinhas(data.total_ai_lines)} />
        <WakaMini label="Linhas minhas" value={fmtLinhas(data.total_human_lines)} />
        <WakaMini label="Peso da IA" value={`${data.ai_pct}%`} sub="das linhas escritas" />
      </div>

      <div className="flex items-end gap-2 mb-4">
        {data.months.map(m => (
          <div key={m.month} className="flex-1 flex flex-col items-center gap-1 group min-w-0">
            <span className="text-[9px] text-cyan-300/80">{m.cost.toFixed(0)}</span>
            <div className="w-full h-24 flex items-end">
              <div
                className="w-full rounded-t-md bg-cyan-400/40 group-hover:bg-cyan-400/70 transition-all"
                style={{ height: `${Math.max(3, (m.cost / maxCost) * 100)}%` }}
                title={`${m.month}: custo ${m.cost.toFixed(2)} · ${fmtLinhas(m.ai_lines)} linhas IA (${m.ai_pct}%) · ${m.prompts} prompts`}
              />
            </div>
            <span className="text-[9px] text-gray-600">{m.month.slice(5)}/{m.month.slice(2, 4)}</span>
          </div>
        ))}
      </div>

      <div className="space-y-2">
        <p className="text-[10px] text-gray-600 uppercase tracking-wider">Por projecto</p>
        {data.projects.filter(p => p.cost > 0 || p.ai_lines > 0).slice(0, 6).map(p => (
          <div key={p.name} className="flex items-center gap-3 text-xs">
            <span className="w-28 truncate text-gray-300" title={p.name}>{p.name}</span>
            <div className="flex-1 h-2 bg-[#1a1a1a] rounded-full overflow-hidden flex">
              <div className="h-full bg-cyan-400/70" style={{ width: `${p.ai_pct}%` }} />
              <div className="h-full bg-gray-600/50" style={{ width: `${100 - p.ai_pct}%` }} />
            </div>
            <span className="w-10 text-right text-gray-500">{p.ai_pct}%</span>
            <span className="w-16 text-right text-cyan-300">{p.cost.toFixed(2)}</span>
            <span className="w-20 text-right text-gray-600">
              {p.cost_per_hour !== null ? `${p.cost_per_hour}/h` : fmtH(p.seconds)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function WakaHoursChart({ hours }: { hours: WakaHours | null }) {
  if (!hours || hours.total_seconds <= 0) return null;
  const maxSec = Math.max(1, ...hours.hours.map(h => h.seconds));
  const fmtH = (n: number) => `${String(n).padStart(2, '0')}h`;
  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
      <div className="flex items-baseline justify-between mb-4">
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider">A que horas programo</h3>
        {hours.peak_hour !== null && (
          <span className="text-[11px] text-gray-500">
            pico às <span className="text-cyan-300 font-semibold">{fmtH(hours.peak_hour)}</span>
          </span>
        )}
      </div>
      <div className="flex items-end gap-[3px]">
        {hours.hours.map(h => {
          const pct = (h.seconds / maxSec) * 100;
          const isPeak = h.hour === hours.peak_hour;
          return (
            <div key={h.hour} className="flex-1 flex flex-col items-center gap-1 group min-w-0">
              <div className="relative w-full h-28 flex items-end">
                <div className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block z-20 whitespace-nowrap rounded-md bg-[#222] border border-[#333] px-2 py-1 text-[10px] text-gray-100 shadow-lg">
                  {fmtH(h.hour)} · {h.text}
                </div>
                <div
                  className={`w-full rounded-t-sm transition-all ${isPeak ? 'bg-cyan-400' : 'bg-cyan-400/35 group-hover:bg-cyan-400/60'}`}
                  style={{ height: `${Math.max(h.seconds > 0 ? 3 : 0, pct)}%` }}
                />
              </div>
              <span className={`text-[8px] tabular-nums ${isPeak ? 'text-cyan-300 font-bold' : 'text-gray-600'}`}>{String(h.hour).padStart(2, '0')}</span>
            </div>
          );
        })}
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

// Nota da secção Notas associada ao projecto, editável aqui mesmo (autosave).
function LinkedNotePanel({ projectPath, projectName, embedded }: { projectPath: string; projectName: string; embedded?: boolean }) {
  const navigate = useNavigate();
  const [linked, setLinked] = useState<Note[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [draft, setDraft] = useState('');
  const [mode, setMode] = useState<'scroll' | 'pages'>('scroll');
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  const [modal, setModal] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Guarda o que ainda não foi gravado, para não se perder ao trocar de nota/projecto.
  const pending = useRef<{ id: number; value: string } | null>(null);
  const seededId = useRef<number | null>(null);

  const flush = () => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    const p = pending.current;
    pending.current = null;
    if (p) notesApi.update(p.id, { content: p.value }).catch(() => {});
  };

  const load = () => {
    notesApi.list({ project_path: projectPath })
      .then((ns: Note[]) => {
        setLinked(ns);
        setActiveId(prev => (prev && ns.some(n => n.id === prev) ? prev : ns[0]?.id ?? null));
      })
      .catch(() => {});
  };
  useEffect(() => {
    flush();
    seededId.current = null;
    setActiveId(null);
    setDraft('');
    load();
  }, [projectPath]);

  useEffect(() => () => flush(), []);

  const active = linked.find(n => n.id === activeId) || null;

  // O texto só é semeado quando muda a nota — nunca a partir da resposta do servidor,
  // senão o que se escrevesse durante o pedido de gravação era descartado.
  useEffect(() => {
    if (!active) { seededId.current = null; setDraft(''); return; }
    if (seededId.current === active.id) return;
    seededId.current = active.id;
    setDraft(active.content || '');
    setMode(localStorage.getItem(viewModeKey(active.id)) === 'pages' ? 'pages' : 'scroll');
  }, [active?.id, active?.content]);

  const changeMode = (m: 'scroll' | 'pages') => {
    setMode(m);
    if (active) localStorage.setItem(viewModeKey(active.id), m);
  };

  const switchNote = (id: number) => {
    flush();
    seededId.current = null;
    setActiveId(id);
  };

  const edit = (value: string) => {
    setDraft(value);
    if (!active) return;
    pending.current = { id: active.id, value };
    if (timer.current) clearTimeout(timer.current);
    setStatus('saving');
    timer.current = setTimeout(async () => {
      timer.current = null;
      try {
        await notesApi.update(active.id, { content: value });
        setLinked(prev => prev.map(n => (n.id === active.id ? { ...n, content: value } : n)));
        if (pending.current?.value === value) pending.current = null;
        setStatus('saved');
        setTimeout(() => setStatus(s => (s === 'saved' ? 'idle' : s)), 1500);
      } catch {
        setStatus('idle');
      }
    }, 700);
  };

  return (
    <div className={`flex-1 min-h-0 flex flex-col ${embedded ? '' : 'bg-[#161616] rounded-2xl border border-[#222]'}`}>
      <div className="flex items-center gap-2 px-3 py-2 shrink-0">
        <StickyNote size={14} className="text-blue-300 shrink-0" />
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs font-bold text-blue-300 uppercase tracking-wider shrink-0">Nota</span>
          <span className="text-xs text-gray-500 truncate">
            {active ? (active.title || 'Sem título') : 'nenhuma nota associada'}
          </span>
        </div>
        {status !== 'idle' && (
          <span className="text-[10px] text-gray-600 shrink-0">{status === 'saving' ? 'a guardar…' : 'guardado'}</span>
        )}
        <div className="ml-auto flex items-center gap-1.5 shrink-0">
          {active && <ModeToggle mode={mode} onChange={changeMode} />}
          {active && (
            <button
              onClick={() => navigate(`/notes?note=${active.id}`)}
              title="Abrir na secção Notas"
              className="p-1.5 rounded-lg text-gray-500 hover:text-blue-300 hover:bg-white/5"
            >
              <ChevronRight size={15} />
            </button>
          )}
          <button
            onClick={() => setModal(true)}
            title={active ? 'Gerir notas do projecto' : 'Criar/associar nota'}
            className="p-1.5 rounded-lg text-gray-500 hover:text-gray-200 hover:bg-white/5"
          >
            {active ? <Link2 size={15} /> : <FilePlus2 size={15} />}
          </button>
        </div>
      </div>
      <div className="flex-1 min-h-0 flex flex-col gap-2 border-t border-[#222] p-3">
        {linked.length > 1 && (
          <div className="flex flex-wrap gap-1 shrink-0">
            {linked.map(n => (
              <button
                key={n.id}
                onClick={() => switchNote(n.id)}
                className={`px-2 py-1 rounded-lg text-[11px] max-w-[160px] truncate ${
                  n.id === activeId ? 'bg-blue-500/20 text-blue-300' : 'bg-[#1a1a1a] text-gray-500 hover:text-gray-300'
                }`}
              >
                {n.title || 'Sem título'}
              </button>
            ))}
          </div>
        )}
        {active ? (
          <div className="flex-1 min-h-0 flex flex-col bg-[#1a1a1a] border border-[#222] rounded-lg px-3 py-2">
            <NoteBody
              key={active.id}
              note={{ ...active, content: draft }}
              mode={mode}
              onContentChange={edit}
              dense
            />
          </div>
        ) : (
          <button
            onClick={() => setModal(true)}
            className="flex-1 min-h-0 w-full flex items-center justify-center gap-2 px-3 rounded-lg bg-[#1a1a1a] hover:bg-white/5 text-xs text-gray-400"
          >
            <FilePlus2 size={14} /> Criar ou associar uma nota a {projectName}
          </button>
        )}
      </div>
      {modal && (
        <ProjectNotesModal
          projectPath={projectPath}
          projectName={projectName}
          linked={linked}
          onClose={() => setModal(false)}
          onChanged={load}
        />
      )}
    </div>
  );
}

function ProjectNotesModal({
  projectPath, projectName, linked, onClose, onChanged,
}: {
  projectPath: string;
  projectName: string;
  linked: Note[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const navigate = useNavigate();
  const [all, setAll] = useState<Note[]>([]);
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => { notesApi.list().then(setAll).catch(() => {}); }, []);

  const goToNote = (id: number) => { onClose(); navigate(`/notes?note=${id}`); };

  // Depois de criar/associar fica-se na Atividade — a nota já é editável ali.
  const createNew = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await notesApi.create({ title: projectName, content: '', project_path: projectPath });
      onChanged();
      onClose();
    } finally { setBusy(false); }
  };

  const associate = async (note: Note) => {
    if (busy) return;
    setBusy(true);
    try {
      await notesApi.update(note.id, { project_path: projectPath });
      onChanged();
      onClose();
    } finally { setBusy(false); }
  };

  const unlink = async (note: Note) => {
    if (busy) return;
    setBusy(true);
    try {
      await notesApi.update(note.id, { project_path: null });
      onChanged();
    } finally { setBusy(false); }
  };

  const linkedIds = new Set(linked.map(n => n.id));
  const term = q.trim().toLowerCase();
  const candidates = all
    .filter(n => !linkedIds.has(n.id))
    .filter(n => !term || (n.title || '').toLowerCase().includes(term) || (n.content || '').toLowerCase().includes(term))
    .slice(0, 50);

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className="bg-[#161616] rounded-2xl border border-[#2a2a2a] w-[420px] max-w-[90vw] max-h-[80vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#222]">
          <div className="flex items-center gap-2 min-w-0">
            <StickyNote size={16} className="text-blue-300 shrink-0" />
            <h3 className="text-sm font-bold truncate">Notas · {projectName}</h3>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-white shrink-0"><X size={18} /></button>
        </div>

        <div className="p-4 overflow-y-auto space-y-4">
          {linked.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Notas associadas</p>
              {linked.map(n => (
                <div key={n.id} className="flex items-center gap-1 px-1 rounded-lg bg-[#1a1a1a]">
                  <button
                    onClick={() => unlink(n)}
                    disabled={busy}
                    title="Desassociar do projecto"
                    className="p-2 text-gray-600 hover:text-red-400 shrink-0 disabled:opacity-50"
                  >
                    <Unlink size={13} />
                  </button>
                  <button
                    onClick={() => goToNote(n.id)}
                    className="flex items-center gap-2 flex-1 min-w-0 px-1 py-2 text-left hover:bg-white/5 rounded-lg"
                  >
                    <StickyNote size={13} className="text-blue-300 shrink-0" />
                    <span className="text-sm truncate flex-1">{n.title || 'Sem título'}</span>
                    <ChevronRight size={14} className="text-gray-600 shrink-0" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <button
            onClick={createNew}
            disabled={busy}
            className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 text-sm font-semibold disabled:opacity-50"
          >
            {busy ? <Loader2 size={15} className="animate-spin" /> : <FilePlus2 size={15} />}
            Criar nova nota para este projecto
          </button>

          <div className="space-y-2">
            <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Associar nota existente</p>
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input
                value={q}
                onChange={e => setQ(e.target.value)}
                placeholder="Pesquisar notas..."
                className="w-full bg-[#1a1a1a] border border-[#222] rounded-lg pl-9 pr-3 py-2 text-sm focus:outline-none focus:border-blue-500/50"
              />
            </div>
            <div className="space-y-1 max-h-[240px] overflow-y-auto">
              {candidates.length === 0 ? (
                <p className="text-xs text-gray-600 text-center py-3">Sem notas para associar.</p>
              ) : candidates.map(n => (
                <button
                  key={n.id}
                  onClick={() => associate(n)}
                  disabled={busy}
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-white/5 text-left disabled:opacity-50"
                >
                  <Link2 size={13} className="text-purple-400 shrink-0" />
                  <span className="text-sm truncate flex-1">{n.title || 'Sem título'}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function TodosPanel({ projectPath, reloadKey = 0, onChanged }: { projectPath: string; reloadKey?: number; onChanged: () => void }) {
  const [todos, setTodos] = useState<CodeProjectTodo[]>([]);
  const [input, setInput] = useState(() => readDraft('todo', projectPath));
  const [busy, setBusy] = useState(false);

  const load = () => {
    codeActivityApi.listTodos(projectPath).then(setTodos).catch(() => {});
  };
  useEffect(() => { setInput(readDraft('todo', projectPath)); load(); }, [projectPath, reloadKey]);

  const editInput = (v: string) => { setInput(v); writeDraft('todo', projectPath, v); };

  const add = async () => {
    const c = input.trim();
    if (!c || busy) return;
    setBusy(true);
    try {
      const t = await codeActivityApi.createTodo(projectPath, c);
      setTodos(prev => [t, ...prev]);
      editInput('');
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

  const rename = async (t: CodeProjectTodo, content: string) => {
    const c = content.trim();
    if (!c || c === t.content) return;
    const updated = await codeActivityApi.updateTodo(t.id, { content: c });
    setTodos(prev => prev.map(x => x.id === t.id ? updated : x));
    onChanged();
  };

  const open = todos.filter(t => !t.done);
  const done = todos.filter(t => t.done);

  return (
    <div className="flex-1 min-h-0 flex flex-col gap-2.5 p-4">
      <div className="flex items-center gap-2 shrink-0">
        <ListChecks size={14} className="text-emerald-400" />
        <h4 className="text-xs font-bold text-emerald-400 uppercase tracking-wider">TODOs</h4>
        <span className="text-[10px] text-gray-600 ml-auto">{todos.filter(t => !t.done).length} abertos</span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <input
          type="text"
          value={input}
          onChange={e => editInput(e.target.value)}
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
        <div className="flex-1 min-h-0 overflow-y-auto space-y-1 pr-1">
          {open.map(t => <TodoRow key={t.id} todo={t} onToggle={() => toggle(t)} onDelete={() => remove(t.id)} onRename={c => rename(t, c)} />)}
          {done.length > 0 && (
            <p className="text-[10px] text-gray-600 uppercase tracking-wider mt-3 mb-1">Feitas</p>
          )}
          {done.map(t => <TodoRow key={t.id} todo={t} onToggle={() => toggle(t)} onDelete={() => remove(t.id)} onRename={c => rename(t, c)} />)}
        </div>
      )}
    </div>
  );
}

// Carregar no texto (ou no lápis) edita-o ali mesmo: Enter ou sair do campo
// grava, Esc desiste.
function TodoRow({ todo, onToggle, onDelete, onRename }: {
  todo: CodeProjectTodo; onToggle: () => void; onDelete: () => void; onRename: (content: string) => void;
}) {
  const ts = todo.done && todo.done_at ? todo.done_at : todo.created_at;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(todo.content);

  const start = () => { setDraft(todo.content); setEditing(true); };
  const save = () => { setEditing(false); onRename(draft); };

  return (
    <div className="flex items-start gap-2 group py-1">
      <input
        type="checkbox"
        checked={todo.done}
        onChange={onToggle}
        className="accent-emerald-500 mt-1"
      />
      {editing ? (
        <textarea
          autoFocus
          rows={1}
          value={draft}
          ref={el => { if (el) { el.style.height = 'auto'; el.style.height = `${el.scrollHeight}px`; } }}
          onChange={e => setDraft(e.target.value)}
          onBlur={save}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); save(); }
            else if (e.key === 'Escape') { setEditing(false); setDraft(todo.content); }
          }}
          className="flex-1 min-w-0 bg-[#1a1a1a] border border-emerald-500/40 rounded px-1.5 py-0.5 text-sm resize-none overflow-hidden focus:outline-none"
        />
      ) : (
        <span onClick={start} title="carregar para editar"
          className={`flex-1 min-w-0 text-sm cursor-text ${todo.done ? 'line-through text-gray-600' : ''}`}>{todo.content}</span>
      )}
      <span className="text-[10px] text-gray-700 shrink-0 mt-1">
        {format(localDate(ts), "d MMM HH:mm", { locale: pt })}
      </span>
      {!editing && (
        <button
          onClick={start}
          title="editar"
          className="lg:opacity-0 lg:group-hover:opacity-100 text-gray-600 hover:text-emerald-400 transition-opacity mt-0.5"
        >
          <Pencil size={13} />
        </button>
      )}
      <button
        onClick={onDelete}
        title="apagar"
        className="lg:opacity-0 lg:group-hover:opacity-100 text-gray-600 hover:text-red-400 transition-opacity mt-0.5"
      >
        <Trash2 size={13} />
      </button>
    </div>
  );
}

// Relatório PDF: a IA organiza as notas do projecto no período escolhido.
function ReportButton({ projectPath }: { projectPath: string }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const gerar = async (days: number) => {
    if (busy !== null) return;
    setBusy(days);
    setError(null);
    try {
      const { blob, filename } = await codeActivityApi.notesReport(projectPath, days);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      setOpen(false);
    } catch (e: any) {
      setError(e?.message || 'Erro a gerar o PDF');
    } finally { setBusy(null); }
  };

  return (
    <div className="relative shrink-0">
      <button
        onClick={() => setOpen(o => !o)}
        title="Relatório PDF das notas deste projecto, organizado pela IA"
        className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-semibold text-gray-500 hover:text-blue-300 hover:bg-white/5"
      >
        {busy !== null ? <Loader2 size={12} className="animate-spin" /> : <FileDown size={12} />}
        PDF
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => !busy && setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-40 w-52 bg-[#1a1a1a] border border-[#2a2a2a] rounded-xl p-1.5 shadow-xl">
            <p className="px-2 py-1 text-[10px] text-gray-500 uppercase tracking-wider">Período do relatório</p>
            {[
              { days: 7, label: 'Última semana' },
              { days: 30, label: 'Último mês' },
              { days: 90, label: 'Últimos 3 meses' },
              { days: 365, label: 'Último ano' },
            ].map(opt => (
              <button
                key={opt.days}
                onClick={() => gerar(opt.days)}
                disabled={busy !== null}
                className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-gray-300 hover:bg-white/5 disabled:opacity-50"
              >
                {busy === opt.days ? <Loader2 size={12} className="animate-spin" /> : <FileDown size={12} className="text-gray-600" />}
                {opt.label}
              </button>
            ))}
            {busy !== null && (
              <p className="px-2 py-1 text-[10px] text-gray-500">A IA está a organizar as notas — pode demorar ~1 min.</p>
            )}
            {error && <p className="px-2 py-1 text-[10px] text-red-400">{error}</p>}
          </div>
        </>
      )}
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
  const [input, setInput] = useState(() => readDraft('nota', projectPath));
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [convertingId, setConvertingId] = useState<number | null>(null);
  const [convertError, setConvertError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState('');
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
  useEffect(() => {
    setLoaded(false);
    setEditingId(null);
    setInput(readDraft('nota', projectPath));
    load();
  }, [projectPath]);

  const editInput = (v: string) => { setInput(v); writeDraft('nota', projectPath, v); };

  const startEdit = (n: CodeProjectNote) => { setEditingId(n.id); setEditDraft(n.content); };

  const saveEdit = async () => {
    const c = editDraft.trim();
    if (editingId === null || !c || busy) return;
    setBusy(true);
    try {
      const updated = await codeActivityApi.updateNote(editingId, c);
      setAllNotes(prev => prev.map(n => (n.id === updated.id ? updated : n)));
      setEditingId(null);
    } finally { setBusy(false); }
  };

  const add = async () => {
    const c = input.trim();
    if (!c || busy) return;
    setBusy(true);
    try {
      const n = await codeActivityApi.createNote(projectPath, c, date);
      setAllNotes(prev => [n, ...prev]);
      editInput('');
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
    <div className="flex-1 min-h-0 flex flex-col gap-2.5 p-4">
      <div className="flex items-center gap-2 shrink-0">
        {isAi ? <Sparkles size={14} className={accentText} /> : <FileCode size={14} className={accentText} />}
        <h4 className={`text-xs font-bold ${accentText} uppercase tracking-wider`}>{isAi ? 'Notas IA' : 'Notas'}</h4>
        {generating && <Loader2 size={12} className="text-purple-400 animate-spin" />}
        <span className="text-[10px] text-gray-600 ml-auto">{notes.length} notas</span>
        {!isAi && <ReportButton projectPath={projectPath} />}
      </div>
      {isAi ? (
        <div className="flex justify-end shrink-0">
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
        <div className="flex items-start gap-2 shrink-0">
          <textarea
            value={input}
            onChange={e => editInput(e.target.value)}
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
        <div className="flex-1 min-h-0 space-y-2 overflow-y-auto pr-1">
          {notes.map(n => (
            <div key={n.id} className="group relative bg-[#1a1a1a] rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-[9px] px-1.5 py-0.5 rounded uppercase tracking-wider ${
                  n.source === 'ai' ? 'bg-purple-500/20 text-purple-400' : 'bg-gray-700/40 text-gray-400'
                }`}>{n.source === 'ai' ? '✨ IA' : 'Manual'}</span>
                {n.note_date && <span className="text-[10px] text-gray-600">{n.note_date}</span>}
                <span className="text-[10px] text-gray-700 ml-auto">
                  {format(localDate(n.created_at), "d MMM HH:mm", { locale: pt })}
                </span>
                {n.source !== 'ai' && (
                  <button
                    onClick={() => (editingId === n.id ? setEditingId(null) : startEdit(n))}
                    title="Editar nota"
                    className={`text-gray-600 hover:text-blue-300 transition-opacity ${
                      editingId === n.id ? '' : 'opacity-0 group-hover:opacity-100'
                    }`}
                  >
                    <Pencil size={12} />
                  </button>
                )}
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
              {editingId === n.id ? (
                <div className="space-y-2">
                  <textarea
                    value={editDraft}
                    onChange={e => setEditDraft(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Escape') setEditingId(null);
                      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) saveEdit();
                    }}
                    autoFocus
                    rows={Math.min(10, Math.max(3, editDraft.split('\n').length))}
                    className="w-full bg-[#161616] border border-[#222] rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500/50 resize-none"
                  />
                  <div className="flex items-center gap-2">
                    <button
                      onClick={saveEdit}
                      disabled={!editDraft.trim() || busy}
                      className="px-3 py-1 rounded-lg bg-blue-500/20 hover:bg-blue-500/30 disabled:opacity-40 text-blue-300 text-xs font-semibold"
                    >
                      Guardar
                    </button>
                    <button
                      onClick={() => setEditingId(null)}
                      className="px-3 py-1 rounded-lg bg-[#222] hover:bg-[#2a2a2a] text-gray-400 text-xs"
                    >
                      Cancelar
                    </button>
                    <span className="text-[10px] text-gray-600">⌘↵ guarda · Esc cancela</span>
                  </div>
                </div>
              ) : (
                <p
                  onDoubleClick={() => n.source !== 'ai' && startEdit(n)}
                  className="text-sm text-gray-300 whitespace-pre-wrap"
                >
                  {n.content}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
