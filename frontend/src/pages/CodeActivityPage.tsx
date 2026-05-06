import { useEffect, useRef, useState } from 'react';
import { format, parseISO } from 'date-fns';
import { pt } from 'date-fns/locale';
import { Code2, ChevronLeft, ChevronRight, FileCode, FolderGit2, ListChecks, Sparkles, Plus, Trash2, Loader2 } from 'lucide-react';
import {
  codeActivityApi,
  CodeActivityDay,
  CodeActivityProject,
  CodeProjectTodo,
  CodeProjectNote,
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
      <p className="text-sm text-gray-500 mb-8">
        Resumo do que mexeste no editor — vem do Local History do VS Code, sem precisar de git.
      </p>

      {weekTotals.length > 0 && (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 mb-6">
          <div className="flex items-end gap-2 h-24">
            {weekTotals.map(d => {
              const h = (d.total_saves / maxWeekSaves) * 100;
              const selected = d.date === date;
              return (
                <button
                  key={d.date}
                  onClick={() => setDate(d.date)}
                  className="flex-1 flex flex-col items-center gap-1 group"
                >
                  <div className="flex-1 w-full flex items-end">
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
                name: t.name,
                path: t.path,
                saves: 0,
                files_count: 0,
                files: [],
                last_ts: 0,
              }));
            const merged = [...data.projects, ...todoOnly];
            if (merged.length === 0) {
              return (
                <div className="bg-[#161616] rounded-2xl border border-[#222] p-12 text-center">
                  <FileCode size={32} className="text-gray-700 mx-auto mb-2" />
                  <p className="text-sm text-gray-500">Nenhuma atividade registada neste dia.</p>
                  {data.history_dir === null && (
                    <p className="text-xs text-gray-600 mt-2">
                      VS Code Local History não encontrado em <code>~/Library/Application Support/Code/User/History/</code>
                    </p>
                  )}
                </div>
              );
            }
            return (
              <div className="space-y-4">
                {merged.map(p => (
                  <ProjectCard
                    key={p.path || p.name}
                    project={p}
                    date={date}
                    hasActivity={p.saves > 0}
                    onChanged={refreshTotals}
                  />
                ))}
              </div>
            );
          })()}
        </>
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
  project, date, hasActivity, onChanged,
}: {
  project: CodeActivityProject;
  date: string;
  hasActivity: boolean;
  onChanged: () => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const [showFiles, setShowFiles] = useState(false);
  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5"
      >
        <div className="flex items-center gap-3 min-w-0">
          <FolderGit2 size={18} className="text-blue-400 shrink-0" />
          <div className="text-left min-w-0">
            <p className="text-sm font-semibold truncate">{project.name}</p>
            {project.path && project.path !== project.name && (
              <p className="text-[10px] text-gray-600 truncate">~/{project.path}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className="text-xs text-gray-500">{project.files_count} ficheiros</span>
          <span className="text-sm font-bold text-blue-400">{project.saves} saves</span>
        </div>
      </button>
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
              <TodosPanel projectPath={project.path} onChanged={onChanged} />
            </div>
            <div className="bg-[#161616]">
              <NotesPanel
                projectPath={project.path}
                date={date}
                hasActivity={hasActivity}
                onChanged={onChanged}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function TodosPanel({ projectPath, onChanged }: { projectPath: string; onChanged: () => void }) {
  const [todos, setTodos] = useState<CodeProjectTodo[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);

  const load = () => {
    codeActivityApi.listTodos(projectPath).then(setTodos).catch(() => {});
  };
  useEffect(() => { load(); }, [projectPath]);

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
  projectPath, date, hasActivity, onChanged,
}: {
  projectPath: string;
  date: string;
  hasActivity: boolean;
  onChanged: () => void;
}) {
  const [notes, setNotes] = useState<CodeProjectNote[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const autoTried = useRef<string>('');

  const load = () => {
    codeActivityApi.listNotes(projectPath)
      .then(ns => { setNotes(ns); setLoaded(true); })
      .catch(() => setLoaded(true));
  };
  useEffect(() => { setLoaded(false); load(); }, [projectPath]);

  const add = async () => {
    const c = input.trim();
    if (!c || busy) return;
    setBusy(true);
    try {
      const n = await codeActivityApi.createNote(projectPath, c, date);
      setNotes(prev => [n, ...prev]);
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
      setNotes(prev => [n, ...prev]);
      onChanged();
    } catch (e: any) {
      setGenError(e?.message || 'Erro a gerar');
    } finally { setGenerating(false); }
  };

  // Auto-generate AI note for the day if there's activity and no AI note yet for this date
  useEffect(() => {
    if (!loaded || !hasActivity) return;
    const key = `${projectPath}|${date}`;
    if (autoTried.current === key) return;
    const hasAiNoteForDate = notes.some(n => n.source === 'ai' && n.note_date === date);
    if (hasAiNoteForDate) { autoTried.current = key; return; }
    autoTried.current = key;
    generate();
  }, [loaded, hasActivity, projectPath, date, notes]);

  const remove = async (id: number) => {
    await codeActivityApi.deleteNote(id);
    setNotes(prev => prev.filter(x => x.id !== id));
    onChanged();
  };

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <Sparkles size={14} className="text-purple-400" />
        <h4 className="text-xs font-bold text-purple-400 uppercase tracking-wider">Notas IA</h4>
        {generating && <Loader2 size={12} className="text-purple-400 animate-spin" />}
        <span className="text-[10px] text-gray-600 ml-auto">{notes.length} notas</span>
      </div>
      <div className="flex items-start gap-2">
        <textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Nota manual sobre alterações..."
          rows={2}
          className="flex-1 bg-[#1a1a1a] border border-[#222] rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-purple-500/50 resize-none"
        />
        <div className="flex flex-col gap-1">
          <button
            onClick={add}
            disabled={!input.trim() || busy}
            title="Adicionar nota manual"
            className="p-1.5 bg-purple-500/20 hover:bg-purple-500/30 disabled:opacity-30 text-purple-400 rounded-lg"
          >
            <Plus size={16} />
          </button>
          <button
            onClick={generate}
            disabled={generating}
            title="Gerar nota com IA a partir da actividade do dia"
            className="p-1.5 bg-purple-500/20 hover:bg-purple-500/30 disabled:opacity-30 text-purple-400 rounded-lg"
          >
            {generating ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
          </button>
        </div>
      </div>
      {genError && <p className="text-xs text-red-400">{genError}</p>}
      {notes.length === 0 ? (
        <p className="text-xs text-gray-600 text-center py-4">Sem notas neste projecto.</p>
      ) : (
        <div className="space-y-2">
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
