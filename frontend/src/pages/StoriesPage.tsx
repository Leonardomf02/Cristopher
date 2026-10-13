import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import {
  BookOpen, Sparkles, ArrowLeft, ArrowRight, Trash2, AlertCircle, ExternalLink,
  Search, Loader2, RefreshCw, X, Compass,
} from 'lucide-react';
import { format } from 'date-fns';
import { storiesApi, Story, StoryListItem, StoryLevel, StorySuggestion, StoryVersion } from '../api';

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

function SuggestionCard({ s, busy, disabled, onOpen, onDismiss }: {
  s: StorySuggestion;
  busy: boolean;
  disabled: boolean;
  onOpen: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="relative group bg-[#161616] border border-[#222] hover:border-purple-500/40 rounded-2xl p-4 transition-colors">
      <button onClick={onOpen} disabled={disabled} className="text-left w-full disabled:cursor-wait">
        <div className="flex items-center gap-2 mb-1.5">
          {s.category && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/15 text-purple-300">
              {s.category}
            </span>
          )}
        </div>
        <h4 className="font-semibold text-white leading-snug pr-5 mb-1">{s.title}</h4>
        <p className="text-xs text-gray-500 leading-relaxed line-clamp-2 mb-3">{s.reason}</p>
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-purple-300">
          {busy ? <Loader2 size={13} className="animate-spin" /> : <ArrowRight size={13} />}
          {busy ? 'A escrever…' : 'Explicar isto'}
        </span>
      </button>
      <button onClick={onDismiss} disabled={disabled} title="Não me interessa"
        className="absolute top-3 right-3 p-1 text-gray-700 hover:text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity">
        <X size={13} />
      </button>
    </div>
  );
}

export default function StoriesPage() {
  const [items, setItems] = useState<StoryListItem[]>([]);
  const [loadingList, setLoadingList] = useState(true);

  const [query, setQuery] = useState('');
  const [searchLevel, setSearchLevel] = useState<StoryLevel>('medium');
  const [creating, setCreating] = useState(false);
  const [fromSuggestion, setFromSuggestion] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [current, setCurrent] = useState<Story | null>(null);
  const [activeLevel, setActiveLevel] = useState<StoryLevel>('medium');
  const [levelLoading, setLevelLoading] = useState<StoryLevel | null>(null);

  const [suggestions, setSuggestions] = useState<StorySuggestion[]>([]);
  const [sugLoading, setSugLoading] = useState(false);
  const [related, setRelated] = useState<StorySuggestion[]>([]);
  const [relLoading, setRelLoading] = useState(false);

  const relToken = useRef(0);  // invalida polls de histórias que já não estão abertas

  useEffect(() => { loadList(); loadSuggestions(); }, []);

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

  /** Sugestões gerais: usa as guardadas; se não houver nenhuma, pede à IA. */
  async function loadSuggestions() {
    try {
      const saved = await storiesApi.suggestions();
      if (saved.length) { setSuggestions(saved); return; }
    } catch { return; }
    refreshSuggestions();
  }

  async function refreshSuggestions() {
    if (sugLoading) return;
    setSugLoading(true);
    try {
      setSuggestions(await storiesApi.refreshSuggestions());
    } catch {
      /* silent — a secção fica simplesmente vazia */
    } finally {
      setSugLoading(false);
    }
  }

  async function dismissSuggestion(id: number, scope: 'general' | 'related') {
    const setter = scope === 'general' ? setSuggestions : setRelated;
    setter(list => list.filter(s => s.id !== id));
    storiesApi.dismissSuggestion(id).catch(() => {});
  }

  /**
   * Temas relacionados com a história aberta. Depois de criar uma história o backend já
   * está a prepará-los em segundo plano (`justCreated`) — aí basta esperar; numa história
   * antiga do histórico, pede-os na hora.
   */
  async function loadRelated(id: number, justCreated = false) {
    const token = ++relToken.current;
    setRelated([]);
    setRelLoading(true);
    try {
      for (let attempt = 0; attempt < (justCreated ? 12 : 1); attempt++) {
        if (attempt) await new Promise(r => setTimeout(r, 5000));
        if (token !== relToken.current) return;
        const saved = await storiesApi.suggestions(id);
        if (token !== relToken.current) return;
        if (saved.length) { setRelated(saved); return; }
      }
      const fresh = await storiesApi.refreshSuggestions(id);
      if (token === relToken.current) setRelated(fresh);
    } catch {
      /* silent */
    } finally {
      if (token === relToken.current) setRelLoading(false);
    }
  }

  async function create(rawQuery?: string, suggestionId?: number) {
    const q = (rawQuery ?? query).trim();
    if (!q || creating) return;
    setError(null);
    setCreating(true);
    setFromSuggestion(suggestionId ?? null);
    try {
      const story = await storiesApi.create({ query: q, level: searchLevel, suggestion_id: suggestionId });
      if (suggestionId) {
        setSuggestions(list => list.filter(s => s.id !== suggestionId));
        setRelated(list => list.filter(s => s.id !== suggestionId));
      }
      setCurrent(story);
      setActiveLevel(story.last_level);
      setQuery('');
      loadRelated(story.id, true);
    } catch (e: any) {
      setError(e?.message || 'Erro a gerar a história');
    } finally {
      setCreating(false);
      setFromSuggestion(null);
    }
  }

  async function openStory(id: number) {
    setError(null);
    try {
      const story = await storiesApi.get(id);
      setCurrent(story);
      setActiveLevel(story.last_level);
      loadRelated(id);
    } catch (e: any) {
      setError(e?.message || 'Erro a abrir');
    }
  }

  function backToList() {
    relToken.current++;
    setCurrent(null);
    setRelated([]);
    setRelLoading(false);
    setError(null);
    loadList();
    loadSuggestions();
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

        {/* Continuar a explorar — temas vizinhos deste */}
        {(relLoading || related.length > 0) && (
          <div className="mt-8">
            <div className="flex items-center justify-between gap-3 mb-3">
              <div className="flex items-center gap-2">
                <Compass size={16} className="text-purple-400" />
                <h3 className="text-sm font-medium text-gray-300">Continuar a explorar</h3>
              </div>
              <button onClick={() => loadRelated(current.id)} disabled={relLoading || creating}
                className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-white disabled:opacity-40">
                <RefreshCw size={12} className={relLoading ? 'animate-spin' : ''} /> Outros
              </button>
            </div>

            {relLoading && related.length === 0 ? (
              <div className="flex items-center gap-2 text-gray-600 text-sm py-4">
                <Loader2 size={14} className="animate-spin" /> A procurar temas ligados a "{current.title}"…
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {related.map(s => (
                  <SuggestionCard key={s.id} s={s}
                    busy={creating && fromSuggestion === s.id}
                    disabled={creating}
                    onOpen={() => create(s.query, s.id)}
                    onDismiss={() => dismissSuggestion(s.id, 'related')} />
                ))}
              </div>
            )}
          </div>
        )}
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
            onClick={() => create()}
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

      {/* Recomendações — o que ler a seguir, com base no que já pesquisaste */}
      <div className="mb-8">
        <div className="flex items-center justify-between gap-3 mb-1">
          <div className="flex items-center gap-2">
            <Compass size={16} className="text-purple-400" />
            <h3 className="text-sm font-medium text-gray-300">Para ti</h3>
          </div>
          <button onClick={refreshSuggestions} disabled={sugLoading || creating}
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-white disabled:opacity-40">
            <RefreshCw size={12} className={sugLoading ? 'animate-spin' : ''} /> Outros temas
          </button>
        </div>
        <p className="text-xs text-gray-600 mb-3">
          {items.length ? 'A partir do que já leste.' : 'Temas para começar.'}
        </p>

        {sugLoading && suggestions.length === 0 ? (
          <div className="flex items-center gap-2 text-gray-600 text-sm py-4">
            <Loader2 size={14} className="animate-spin" /> A escolher temas para ti…
          </div>
        ) : suggestions.length === 0 ? (
          <p className="text-sm text-gray-600 py-2">Sem recomendações de momento.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {suggestions.map(s => (
              <SuggestionCard key={s.id} s={s}
                busy={creating && fromSuggestion === s.id}
                disabled={creating}
                onOpen={() => create(s.query, s.id)}
                onDismiss={() => dismissSuggestion(s.id, 'general')} />
            ))}
          </div>
        )}
      </div>

      <h3 className="text-sm font-medium text-gray-400 mb-3">As tuas histórias</h3>

      {loadingList ? (
        <div className="flex items-center gap-2 text-gray-600 text-sm py-8">
          <Loader2 size={15} className="animate-spin" /> A carregar…
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-12 text-gray-600">
          <BookOpen size={36} className="mx-auto mb-3 opacity-40" />
          <p className="text-sm">Ainda não pesquisaste nada. Escreve um tema acima ou escolhe uma recomendação.</p>
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
