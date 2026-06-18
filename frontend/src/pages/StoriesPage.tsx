import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { BookOpen, Sparkles, ArrowLeft, Trash2, AlertCircle, ExternalLink, Search, Loader2 } from 'lucide-react';
import { format } from 'date-fns';
import { storiesApi, Story, StoryListItem, StoryLevel, StoryVersion } from '../api';

const LEVELS: { key: StoryLevel; label: string; hint: string }[] = [
  { key: 'simple', label: 'Simples', hint: 'Resumo rápido, linguagem simples' },
  { key: 'medium', label: 'Médio', hint: 'Contexto, causas e consequências' },
  { key: 'long', label: 'Grande', hint: 'Aprofundado, com cronologia' },
];

const MD_COMPONENTS = {
  h1: (p: any) => <h1 className="text-xl font-bold mt-5 mb-2 text-white" {...p} />,
  h2: (p: any) => <h2 className="text-lg font-bold mt-5 mb-2 text-white" {...p} />,
  h3: (p: any) => <h3 className="text-base font-semibold mt-4 mb-1.5 text-gray-100" {...p} />,
  p: (p: any) => <p className="text-[15px] leading-relaxed text-gray-300 mb-3" {...p} />,
  ul: (p: any) => <ul className="list-disc pl-5 mb-3 space-y-1 text-[15px] text-gray-300" {...p} />,
  ol: (p: any) => <ol className="list-decimal pl-5 mb-3 space-y-1 text-[15px] text-gray-300" {...p} />,
  li: (p: any) => <li className="leading-relaxed" {...p} />,
  strong: (p: any) => <strong className="font-semibold text-white" {...p} />,
  em: (p: any) => <em className="italic" {...p} />,
  a: (p: any) => <a className="text-blue-400 hover:underline" target="_blank" rel="noreferrer" {...p} />,
  blockquote: (p: any) => <blockquote className="border-l-2 border-[#333] pl-3 italic text-gray-400 mb-3" {...p} />,
  code: (p: any) => <code className="bg-[#222] rounded px-1.5 py-0.5 text-[13px] text-purple-300" {...p} />,
  hr: () => <hr className="border-[#222] my-4" />,
};

export default function StoriesPage() {
  const [items, setItems] = useState<StoryListItem[]>([]);
  const [loadingList, setLoadingList] = useState(true);

  const [query, setQuery] = useState('');
  const [searchLevel, setSearchLevel] = useState<StoryLevel>('medium');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [current, setCurrent] = useState<Story | null>(null);
  const [activeLevel, setActiveLevel] = useState<StoryLevel>('medium');
  const [levelLoading, setLevelLoading] = useState<StoryLevel | null>(null);

  useEffect(() => { loadList(); }, []);

  async function loadList() {
    setLoadingList(true);
    try {
      setItems(await storiesApi.list());
    } catch {
      /* silent */
    } finally {
      setLoadingList(false);
    }
  }

  async function create() {
    const q = query.trim();
    if (!q || creating) return;
    setError(null);
    setCreating(true);
    try {
      const story = await storiesApi.create({ query: q, level: searchLevel });
      setCurrent(story);
      setActiveLevel(story.last_level);
      setQuery('');
    } catch (e: any) {
      setError(e?.message || 'Erro a gerar a história');
    } finally {
      setCreating(false);
    }
  }

  async function openStory(id: number) {
    setError(null);
    try {
      const story = await storiesApi.get(id);
      setCurrent(story);
      setActiveLevel(story.last_level);
    } catch (e: any) {
      setError(e?.message || 'Erro a abrir');
    }
  }

  function backToList() {
    setCurrent(null);
    setError(null);
    loadList();
  }

  async function switchLevel(level: StoryLevel) {
    if (!current || level === activeLevel) return;
    const existing = current.versions.find(v => v.level === level);
    if (existing) {
      setActiveLevel(level);
      storiesApi.setLevel(current.id, level).catch(() => {});  // persiste o último visto
      return;
    }
    setError(null);
    setLevelLoading(level);
    try {
      const version: StoryVersion = await storiesApi.setLevel(current.id, level);
      setCurrent(c => c ? { ...c, versions: [...c.versions, version], last_level: level } : c);
      setActiveLevel(level);
    } catch (e: any) {
      setError(e?.message || 'Erro a gerar este nível');
    } finally {
      setLevelLoading(null);
    }
  }

  async function remove(id: number) {
    if (!confirm('Apagar esta história?')) return;
    try {
      await storiesApi.remove(id);
    } catch { /* silent */ }
    if (current?.id === id) backToList();
    else loadList();
  }

  // ── Detail view ──────────────────────────────────────────────
  if (current) {
    const version = current.versions.find(v => v.level === activeLevel);
    return (
      <div className="max-w-3xl mx-auto">
        <button onClick={backToList}
          className="flex items-center gap-2 text-gray-400 hover:text-white mb-4 text-sm">
          <ArrowLeft size={16} /> Voltar às histórias
        </button>

        <div className="flex items-start justify-between gap-3 mb-1">
          <h2 className="text-2xl sm:text-3xl font-bold">{current.title}</h2>
          <button onClick={() => remove(current.id)}
            className="p-2 text-gray-600 hover:text-red-400 shrink-0" title="Apagar">
            <Trash2 size={18} />
          </button>
        </div>
        <p className="text-xs text-gray-600 mb-5">
          Pesquisado a {format(new Date(current.created_at), 'dd/MM/yyyy')} · "{current.query}"
        </p>

        <div className="inline-flex rounded-xl bg-[#161616] border border-[#222] p-1 mb-6">
          {LEVELS.map(l => {
            const isActive = activeLevel === l.key;
            const isLoading = levelLoading === l.key;
            return (
              <button key={l.key} onClick={() => switchLevel(l.key)} disabled={levelLoading !== null}
                className={`flex items-center gap-1.5 px-3 sm:px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'
                } ${levelLoading !== null && !isLoading ? 'opacity-50' : ''}`}>
                {isLoading && <Loader2 size={13} className="animate-spin" />}
                {l.label}
              </button>
            );
          })}
        </div>

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3 mb-5 flex items-start gap-2">
            <AlertCircle size={16} className="text-red-400 mt-0.5 shrink-0" />
            <span className="text-sm text-red-400">{error}</span>
          </div>
        )}

        {levelLoading ? (
          <div className="flex items-center gap-2 text-gray-500 text-sm py-10">
            <Loader2 size={16} className="animate-spin" /> A escrever a versão {LEVELS.find(l => l.key === levelLoading)?.label.toLowerCase()}…
          </div>
        ) : version ? (
          <div className="bg-[#161616] rounded-2xl border border-[#222] p-5 sm:p-7">
            <ReactMarkdown components={MD_COMPONENTS}>{version.body}</ReactMarkdown>

            {version.sources.length > 0 && (
              <div className="mt-6 pt-5 border-t border-[#222]">
                <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-2">Fontes</h4>
                <ul className="space-y-1.5">
                  {version.sources.map((s, i) => (
                    <li key={i}>
                      <a href={s.url} target="_blank" rel="noreferrer"
                        className="inline-flex items-center gap-1.5 text-sm text-blue-400 hover:underline">
                        <ExternalLink size={13} className="shrink-0" />
                        <span className="truncate">{s.title}</span>
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : null}
      </div>
    );
  }

  // ── List view ────────────────────────────────────────────────
  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center gap-3 mb-2">
        <BookOpen size={28} className="text-blue-400" />
        <h2 className="text-2xl sm:text-3xl font-bold">Histórias</h2>
      </div>
      <p className="text-sm text-gray-500 mb-6">
        Pesquisa qualquer tema (história, ciência, pessoas, eventos) e a IA explica-te ao nível que escolheres.
      </p>

      <div className="bg-[#161616] rounded-2xl border border-[#222] p-5 mb-8">
        <div className="flex items-center gap-2 mb-3">
          <Search size={16} className="text-gray-500 shrink-0" />
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') create(); }}
            placeholder="Ex: o que aconteceu em Chernobyl, quem foi Alexandre o Grande…"
            className="flex-1 bg-transparent text-sm focus:outline-none placeholder:text-gray-600"
          />
        </div>

        <div className="flex items-end justify-between gap-3 flex-wrap">
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] text-gray-500">Profundidade</span>
            <div className="inline-flex rounded-xl bg-[#0f0f0f] border border-[#222] p-1">
              {LEVELS.map(l => (
                <button key={l.key} onClick={() => setSearchLevel(l.key)} title={l.hint}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                    searchLevel === l.key ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'
                  }`}>
                  {l.label}
                </button>
              ))}
            </div>
          </div>
          <button
            onClick={create}
            disabled={!query.trim() || creating}
            className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-[#222] disabled:text-gray-600 disabled:cursor-not-allowed rounded-xl text-sm font-semibold transition-colors">
            {creating ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
            {creating ? 'A escrever…' : 'Explicar'}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3 mb-6 flex items-start gap-2">
          <AlertCircle size={16} className="text-red-400 mt-0.5 shrink-0" />
          <span className="text-sm text-red-400">{error}</span>
        </div>
      )}

      <h3 className="text-sm font-medium text-gray-400 mb-3">As tuas histórias</h3>

      {loadingList ? (
        <div className="flex items-center gap-2 text-gray-600 text-sm py-8">
          <Loader2 size={15} className="animate-spin" /> A carregar…
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-12 text-gray-600">
          <BookOpen size={36} className="mx-auto mb-3 opacity-40" />
          <p className="text-sm">Ainda não pesquisaste nada. Escreve um tema acima para começar.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {items.map(s => (
            <button key={s.id} onClick={() => openStory(s.id)}
              className="text-left bg-[#161616] hover:bg-[#1c1c1c] border border-[#222] rounded-2xl p-4 transition-colors group">
              <div className="flex items-start justify-between gap-2 mb-1">
                <h4 className="font-semibold text-white leading-snug line-clamp-2">{s.title}</h4>
                <span
                  onClick={e => { e.stopPropagation(); remove(s.id); }}
                  className="p-1 text-gray-700 hover:text-red-400 opacity-0 group-hover:opacity-100 shrink-0 cursor-pointer">
                  <Trash2 size={14} />
                </span>
              </div>
              <p className="text-xs text-gray-500 line-clamp-2 mb-3">{s.snippet}</p>
              <div className="flex items-center gap-2 flex-wrap">
                {LEVELS.filter(l => s.levels.includes(l.key)).map(l => (
                  <span key={l.key} className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/15 text-blue-300">{l.label}</span>
                ))}
                <span className="text-[10px] text-gray-600 ml-auto">{format(new Date(s.created_at), 'dd/MM/yyyy')}</span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
