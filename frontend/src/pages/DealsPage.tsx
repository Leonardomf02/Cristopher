import { useEffect, useState } from 'react';
import {
  Tag, Plus, RefreshCw, Trash2, Pencil, ExternalLink, Bookmark, X,
  Search, Loader2, MapPin, Power, AlertTriangle,
} from 'lucide-react';
import { dealsApi, DealWatch, DealResult, DealWatchInput } from '../api';

const SOURCE_LABEL: Record<string, string> = { all: 'Todas', vinted: 'Só Vinted', olx: 'Só OLX', web: 'Só IA (web)' };
const COND_LABEL: Record<string, string> = { any: 'Novo ou usado', new: 'Só novo', used: 'Só usado' };
const CATEGORIES = ['', 'phone', 'motorcycle', 'accessory', 'laptop', 'console', 'other'];

const emptyForm: DealWatchInput = {
  title: '', query: '', category: '', condition: 'any', sources: 'all',
  max_price: null, min_rating: 60, ai_context: '', exclude_keywords: '', active: true,
};

function fmtAgo(secs: number): string {
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)} min`;
  return `${Math.floor(secs / 3600)}h`;
}

function ratingColor(r: number | null): string {
  if (r === null) return 'bg-gray-700 text-gray-300';
  if (r >= 85) return 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40';
  if (r >= 70) return 'bg-lime-500/20 text-lime-300 border border-lime-500/40';
  if (r >= 50) return 'bg-amber-500/20 text-amber-300 border border-amber-500/40';
  return 'bg-gray-700/40 text-gray-400 border border-gray-600/40';
}

export default function DealsPage() {
  const [watches, setWatches] = useState<DealWatch[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [results, setResults] = useState<DealResult[]>([]);
  const [filter, setFilter] = useState<'good' | 'all' | 'saved' | 'unmatched'>('good');
  const [loadingResults, setLoadingResults] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<DealWatch | null>(null);
  const [form, setForm] = useState<DealWatchInput>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [ai, setAi] = useState<{ rate_limited: boolean; seconds_ago: number | null }>({ rate_limited: false, seconds_ago: null });
  const [checkingAi, setCheckingAi] = useState(false);

  const selected = watches.find(w => w.id === selectedId) || null;

  async function checkAi() {
    setCheckingAi(true);
    try {
      const s = await dealsApi.aiCheck();
      setAi(s);
      if (!s.rate_limited) loadWatches();   // recuperou: refresca contagens
    } catch { /* ignora */ } finally {
      setCheckingAi(false);
    }
  }

  async function loadWatches(selectFirst = false) {
    const ws = await dealsApi.listWatches();
    setWatches(ws);
    if (selectFirst && ws.length && selectedId === null) setSelectedId(ws[0].id);
    dealsApi.summary().then(s => setAi(s.ai)).catch(() => {});
  }

  useEffect(() => { loadWatches(true); }, []);

  async function loadResults(watchId: number) {
    setLoadingResults(true);
    try {
      if (filter === 'saved') setResults(await dealsApi.results(watchId, { status: 'saved' }));
      else if (filter === 'unmatched') setResults(await dealsApi.results(watchId, { include_unmatched: true }));
      else setResults(await dealsApi.results(watchId));
    } finally {
      setLoadingResults(false);
    }
  }

  useEffect(() => {
    if (selectedId !== null) loadResults(selectedId);
  }, [selectedId, filter]);

  // Enquanto algum watch está a procurar, refresca de 4 em 4s (+ resultados do selecionado)
  useEffect(() => {
    if (!watches.some(w => w.scanning)) return;
    const t = setTimeout(() => {
      loadWatches();
      if (selectedId !== null) loadResults(selectedId);
    }, 4000);
    return () => clearTimeout(t);
  }, [watches, selectedId]);

  // Enquanto a IA está em rate limit, sonda de 5 em 5 min (espaçado de propósito:
  // sondar a mais pode manter o limite "entupido" se for por janela deslizante)
  useEffect(() => {
    if (!ai.rate_limited) return;
    const t = setTimeout(checkAi, 300000);
    return () => clearTimeout(t);
  }, [ai]);

  const visibleResults = results.filter(r => {
    if (filter === 'good') return r.ai_match && (r.ai_rating ?? -1) >= (selected?.min_rating ?? 0);
    if (filter === 'unmatched') return !r.ai_match;
    return true;
  });

  async function runNow(id: number) {
    try {
      await dealsApi.runWatch(id);   // arranca em background; o poll trata do resto
      await loadWatches();
    } catch (e: any) {
      alert(e.message || 'Falha ao pesquisar');
    }
  }

  async function toggleActive(w: DealWatch) {
    await dealsApi.updateWatch(w.id, { active: !w.active });
    loadWatches();
  }

  function openCreate() {
    setEditing(null);
    setForm(emptyForm);
    setModalOpen(true);
  }

  function openEdit(w: DealWatch) {
    setEditing(w);
    setForm({
      title: w.title, query: w.query, category: w.category, condition: w.condition,
      sources: w.sources, max_price: w.max_price, min_rating: w.min_rating,
      ai_context: w.ai_context, exclude_keywords: w.exclude_keywords, active: w.active,
    });
    setModalOpen(true);
  }

  async function saveWatch() {
    if (!form.title.trim() || !form.query.trim()) { alert('Título e termos de pesquisa são obrigatórios'); return; }
    setSaving(true);
    try {
      if (editing) {
        await dealsApi.updateWatch(editing.id, form);
      } else {
        const w = await dealsApi.createWatch(form);
        setSelectedId(w.id);
      }
      setModalOpen(false);
      await loadWatches();
    } catch (e: any) {
      alert(e.message || 'Falha ao guardar');
    } finally {
      setSaving(false);
    }
  }

  async function deleteWatch(w: DealWatch) {
    if (!confirm(`Apagar o watch "${w.title}" e todos os deals encontrados?`)) return;
    await dealsApi.deleteWatch(w.id);
    if (selectedId === w.id) setSelectedId(null);
    loadWatches();
  }

  async function patchResult(r: DealResult, status: string) {
    await dealsApi.patchResult(r.id, status);
    if (selectedId !== null) { loadResults(selectedId); loadWatches(); }
  }

  return (
    <div className="max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-5 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-gradient-to-br from-pink-500/20 to-purple-500/20">
            <Tag className="text-pink-400" size={22} />
          </div>
          <div>
            <h1 className="text-2xl font-bold">Deals</h1>
            <p className="text-xs text-gray-500">Caça-deals · Vinted + OLX + IA web · scan automático 2x/dia · ou carrega Procurar</p>
          </div>
        </div>
        <button onClick={openCreate} className="flex items-center gap-2 px-4 py-2 rounded-xl bg-pink-600 hover:bg-pink-500 text-white text-sm font-medium">
          <Plus size={18} /> Novo watch
        </button>
      </div>

      {ai.rate_limited && (
        <div className="flex items-start gap-2 mb-4 p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-sm">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <div className="flex-1">
            IA em espera (rate limit{ai.seconds_ago != null ? `, há ${fmtAgo(ai.seconds_ago)}` : ''}). Os anúncios continuam a aparecer mas <span className="font-medium">por avaliar</span>. A app verifica sozinha de 5 em 5 min; quando a IA voltar, este aviso desaparece e podes carregar <span className="text-amber-100">Procurar</span>.
            <div className="text-[11px] text-amber-300/70 mt-1">O servidor da IA não diz quanto falta para reabrir (não há countdown). Se isto durar horas, é quota esgotada — convém deixar a IA descansar (sem procurar) um bom bocado.</div>
          </div>
          <button onClick={checkAi} disabled={checkingAi} className="shrink-0 flex items-center gap-1 text-xs px-2 py-1 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-100 disabled:opacity-50">
            {checkingAi ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} Verificar agora
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-5">
        {/* Watches */}
        <div className="space-y-2">
          {watches.length === 0 && (
            <div className="text-center text-gray-500 text-sm border border-dashed border-[#333] rounded-xl p-8">
              Sem watches. Cria um (ex: <span className="text-gray-300">"Yamaha MT-07"</span>, <span className="text-gray-300">"iPhone 17"</span>).
            </div>
          )}
          {watches.map(w => (
            <button
              key={w.id}
              onClick={() => setSelectedId(w.id)}
              className={`w-full text-left p-3 rounded-xl border transition-all ${
                selectedId === w.id ? 'bg-white/10 border-pink-500/50' : 'bg-[#161616] border-[#222] hover:border-[#333]'
              } ${!w.active ? 'opacity-50' : ''}`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold truncate">{w.title}</span>
                {w.new_count > 0 && (
                  <span className="shrink-0 text-xs font-bold bg-pink-600 text-white rounded-full px-2 py-0.5">{w.new_count} novos</span>
                )}
              </div>
              <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                <Tag size={11} className="text-gray-500" />
                <span className="text-xs text-gray-500 truncate">{w.query}</span>
              </div>
              <div className="flex items-center gap-1.5 mt-2 flex-wrap text-[10px]">
                <span className="px-1.5 py-0.5 rounded bg-white/5 text-gray-400">{SOURCE_LABEL[w.sources] || w.sources}</span>
                <span className="px-1.5 py-0.5 rounded bg-white/5 text-gray-400">{COND_LABEL[w.condition] || w.condition}</span>
                {w.max_price != null && <span className="px-1.5 py-0.5 rounded bg-white/5 text-gray-400">≤ {w.max_price}€</span>}
                <span className="px-1.5 py-0.5 rounded bg-white/5 text-gray-400">★ {w.min_rating}+</span>
              </div>
              <div className="flex items-center gap-1 mt-2.5" onClick={e => e.stopPropagation()}>
                <span
                  onClick={() => !w.scanning && runNow(w.id)}
                  className={`flex items-center gap-1 text-xs px-2 py-1 rounded-lg bg-white/5 text-gray-300 ${w.scanning ? 'opacity-60' : 'hover:bg-white/10 cursor-pointer'}`}
                >
                  {w.scanning ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} {w.scanning ? 'A procurar…' : 'Procurar'}
                </span>
                <span onClick={() => openEdit(w)} className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-gray-400 cursor-pointer"><Pencil size={12} /></span>
                <span onClick={() => toggleActive(w)} className={`p-1.5 rounded-lg bg-white/5 hover:bg-white/10 cursor-pointer ${w.active ? 'text-emerald-400' : 'text-gray-500'}`}><Power size={12} /></span>
                <span onClick={() => deleteWatch(w)} className="p-1.5 rounded-lg bg-white/5 hover:bg-red-500/20 text-gray-400 hover:text-red-400 cursor-pointer"><Trash2 size={12} /></span>
              </div>
            </button>
          ))}
        </div>

        {/* Results */}
        <div>
          {!selected ? (
            <div className="text-center text-gray-500 text-sm py-20">Seleciona um watch para ver os deals.</div>
          ) : (
            <>
              <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
                <div className="flex gap-1 text-xs">
                  {([['good', 'Melhores'], ['all', 'Todos'], ['saved', 'Guardados'], ['unmatched', 'Descartados IA']] as const).map(([k, label]) => (
                    <button
                      key={k}
                      onClick={() => setFilter(k)}
                      className={`px-3 py-1.5 rounded-lg ${filter === k ? 'bg-pink-600 text-white' : 'bg-white/5 text-gray-400 hover:bg-white/10'}`}
                    >{label}</button>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  {selected.last_checked_at && (
                    <span className="text-[11px] text-gray-600">verificado {new Date(selected.last_checked_at).toLocaleString('pt-PT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                  )}
                  {selected.new_count > 0 && (
                    <button onClick={() => dealsApi.markSeen(selected.id).then(() => { loadResults(selected.id); loadWatches(); })} className="text-[11px] text-gray-400 hover:text-white">marcar vistos</button>
                  )}
                </div>
              </div>

              {loadingResults ? (
                <div className="flex items-center gap-2 text-gray-500 text-sm py-20 justify-center"><Loader2 className="animate-spin" size={18} /> a carregar…</div>
              ) : visibleResults.length === 0 ? (
                <div className="text-center text-gray-500 text-sm py-16 border border-dashed border-[#333] rounded-xl px-4">
                  <Search size={20} className="mx-auto mb-2 opacity-50" />
                  {filter === 'good' && selected.pending_count > 0 ? (
                    <>
                      <span className="text-gray-200 font-medium">{selected.pending_count}</span> anúncios por avaliar pela IA
                      {selected.scanning ? ' — a avaliar agora…' : ai.rate_limited ? ' — IA em espera (rate limit).' : '.'}<br />
                      {!selected.scanning && !ai.rate_limited && <>Carrega <span className="text-gray-300">Procurar</span> para avaliar. </>}
                      Vê-os já em <button onClick={() => setFilter('all')} className="text-pink-400 hover:underline">Todos</button>.
                    </>
                  ) : filter === 'good' && selected.total_count > 0 ? (
                    <>
                      A IA avaliou tudo: <span className="text-gray-200 font-medium">{selected.total_count}</span> {selected.total_count === 1 ? 'anúncio é mesmo o produto, mas não chega' : 'anúncios são mesmo o produto, mas nenhum chega'} ao rating mínimo (<span className="text-gray-300">{selected.min_rating}+</span>).<br />
                      Baixa o rating mínimo no watch, ou vê <button onClick={() => setFilter('all')} className="text-pink-400 hover:underline">Todos</button>.
                    </>
                  ) : filter === 'good' ? (
                    <>A IA avaliou tudo, mas nenhum anúncio é mesmo o que procuras. Vê <button onClick={() => setFilter('unmatched')} className="text-pink-400 hover:underline">Descartados IA</button> para perceber porquê (ou afina os termos/exclusões do watch).</>
                  ) : (
                    <>Ainda sem deals neste filtro. Carrega em <span className="text-gray-300">Procurar</span> ou espera pelo scan automático.</>
                  )}
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
                  {visibleResults.map(r => (
                    <div key={r.id} className={`rounded-xl border bg-[#161616] overflow-hidden flex flex-col ${r.status === 'new' && r.ai_match ? 'border-pink-500/40' : 'border-[#222]'}`}>
                      <div className="relative aspect-[4/3] bg-[#0d0d0d]">
                        {r.image_url ? (
                          <img src={r.image_url} alt="" className="w-full h-full object-cover" loading="lazy" />
                        ) : (
                          <div className="w-full h-full flex items-center justify-center text-gray-700"><Tag size={28} /></div>
                        )}
                        <span className={`absolute top-2 left-2 text-xs font-bold rounded-lg px-2 py-1 ${ratingColor(r.ai_rating)}`}>
                          {r.ai_rating === null ? '—' : r.ai_rating}
                        </span>
                        <span className="absolute top-2 right-2 text-[10px] font-medium rounded px-1.5 py-0.5 bg-black/60 text-gray-200 capitalize">{r.source === 'web' && r.seller ? r.seller : r.source}</span>
                        {r.status === 'new' && r.ai_match && (
                          <span className="absolute bottom-2 left-2 text-[10px] font-bold rounded px-1.5 py-0.5 bg-pink-600 text-white">NOVO</span>
                        )}
                      </div>
                      <div className="p-3 flex-1 flex flex-col">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="font-semibold text-sm truncate">{r.title}</span>
                          {r.price != null && <span className="shrink-0 font-bold text-emerald-400 text-sm">{r.price}{r.currency === 'EUR' ? '€' : ' ' + r.currency}</span>}
                        </div>
                        <div className="flex items-center gap-2 mt-1 text-[11px] text-gray-500 flex-wrap">
                          {r.condition && <span>{r.condition}</span>}
                          {r.location && <span className="flex items-center gap-0.5"><MapPin size={10} /> {r.location}</span>}
                        </div>
                        {r.ai_reason && <p className="text-xs text-gray-400 mt-2 line-clamp-3">{r.ai_reason}</p>}
                        <div className="flex items-center gap-1.5 mt-auto pt-3">
                          <a href={r.url} target="_blank" rel="noreferrer" className="flex-1 flex items-center justify-center gap-1 text-xs px-2 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-white">
                            Ver <ExternalLink size={12} />
                          </a>
                          <button onClick={() => patchResult(r, r.status === 'saved' ? 'seen' : 'saved')} className={`p-1.5 rounded-lg ${r.status === 'saved' ? 'bg-amber-500/20 text-amber-300' : 'bg-white/5 text-gray-400 hover:bg-white/10'}`} title="Guardar">
                            <Bookmark size={14} />
                          </button>
                          <button onClick={() => patchResult(r, 'dismissed')} className="p-1.5 rounded-lg bg-white/5 text-gray-400 hover:bg-red-500/20 hover:text-red-400" title="Descartar">
                            <X size={14} />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={() => setModalOpen(false)}>
          <div className="bg-[#161616] border border-[#222] rounded-2xl p-5 w-full max-w-[90vw] sm:max-w-lg max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold">{editing ? 'Editar watch' : 'Novo watch'}</h2>
              <button onClick={() => setModalOpen(false)} className="text-gray-500 hover:text-white"><X size={20} /></button>
            </div>
            <div className="space-y-3">
              <Field label="Título">
                <input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} placeholder="iPhone 17" className="inp" />
              </Field>
              <Field label="Termos de pesquisa">
                <input value={form.query} onChange={e => setForm({ ...form, query: e.target.value })} placeholder="iphone 17" className="inp" />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Categoria">
                  <select value={form.category} onChange={e => setForm({ ...form, category: e.target.value })} className="inp">
                    {CATEGORIES.map(c => <option key={c} value={c}>{c || '—'}</option>)}
                  </select>
                </Field>
                <Field label="Condição">
                  <select value={form.condition} onChange={e => setForm({ ...form, condition: e.target.value })} className="inp">
                    <option value="any">Novo ou usado</option>
                    <option value="new">Só novo</option>
                    <option value="used">Só usado</option>
                  </select>
                </Field>
                <Field label="Fontes">
                  <select value={form.sources} onChange={e => setForm({ ...form, sources: e.target.value })} className="inp">
                    <option value="all">Todas (Vinted + OLX + IA web)</option>
                    <option value="vinted">Só Vinted</option>
                    <option value="olx">Só OLX</option>
                    <option value="web">Só IA (web)</option>
                  </select>
                </Field>
                <Field label="Preço máximo (€)">
                  <input type="number" value={form.max_price ?? ''} onChange={e => setForm({ ...form, max_price: e.target.value ? Number(e.target.value) : null })} placeholder="sem limite" className="inp" />
                </Field>
              </div>
              <Field label={`Rating mínimo para notificar: ${form.min_rating}`}>
                <input type="range" min={0} max={100} value={form.min_rating} onChange={e => setForm({ ...form, min_rating: Number(e.target.value) })} className="w-full accent-pink-500" />
              </Field>
              <Field label="Contexto para a IA (o que é / o que NÃO é)">
                <textarea value={form.ai_context} onChange={e => setForm({ ...form, ai_context: e.target.value })} rows={3} placeholder="É o iPhone 17 normal. NÃO quero o 17e, nem Plus, nem Pro. Nada de capas/peças." className="inp resize-none" />
              </Field>
              <Field label="Excluir se o título tiver (separado por vírgulas)">
                <input value={form.exclude_keywords} onChange={e => setForm({ ...form, exclude_keywords: e.target.value })} placeholder="17e, plus, capa, case" className="inp" />
              </Field>
            </div>
            <div className="flex gap-2 mt-5">
              <button onClick={() => setModalOpen(false)} className="flex-1 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-gray-300 text-sm">Cancelar</button>
              <button onClick={saveWatch} disabled={saving} className="flex-1 py-2.5 rounded-xl bg-pink-600 hover:bg-pink-500 text-white text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-50">
                {saving && <Loader2 size={16} className="animate-spin" />} {editing ? 'Guardar' : 'Criar e procurar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs text-gray-400 mb-1 block">{label}</span>
      {children}
    </label>
  );
}
