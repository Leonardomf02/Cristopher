import { useEffect, useState } from 'react';
import {
  Tag, Plus, RefreshCw, Trash2, Pencil, ExternalLink, Bookmark, X,
  Search, Loader2, MapPin, Power, AlertTriangle,
} from 'lucide-react';
import { dealsApi, DealWatch, DealResult, DealWatchInput, DealPriceStats, TriageItem } from '../api';

const SOURCE_LABEL: Record<string, string> = { all: 'Todas', vinted: 'Só Vinted', olx: 'Só OLX', facebook: 'Só Facebook', web: 'Só IA (web)' };
const COND_LABEL: Record<string, string> = { any: 'Novo ou usado', new: 'Só novo', used: 'Só usado' };
const CATEGORIES = ['', 'phone', 'motorcycle', 'accessory', 'laptop', 'console', 'other'];

const emptyForm: DealWatchInput = {
  title: '', query: '', category: '', condition: 'any', sources: 'all',
  max_price: null, min_rating: 60, ai_context: '', exclude_keywords: '', kind: 'specific', criteria: {}, notify: true, active: true,
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


// A app encontrou 914 anúncios e classificou 154 como bons — e nenhum chegou a
// ser decidido. Sem decisões nunca aprende o que ele quer nem sabe se acerta.
// Isto põe à frente só os que valem uma escolha, os mais baratos primeiro.
function Triagem({ onDecidido }: { onDecidido: () => void }) {
  const [dados, setDados] = useState<{ pending: number; items: TriageItem[] } | null>(null);
  const [aberto, setAberto] = useState(true);
  const [ocupado, setOcupado] = useState(false);

  const carregar = () => dealsApi.triage(12).then(setDados).catch(() => setDados(null));
  useEffect(() => { carregar(); }, []);

  const decidir = async (id: number, guardar: boolean) => {
    setOcupado(true);
    try {
      await dealsApi.triageApply(guardar ? [id] : [], guardar ? [] : [id]);
      await carregar();
      onDecidido();
    } finally { setOcupado(false); }
  };

  if (!dados || !dados.items.length) return null;

  return (
    <div className="mb-5 rounded-2xl border border-pink-500/25 bg-pink-500/[0.04] p-4">
      <button onClick={() => setAberto(a => !a)} className="flex w-full items-center gap-2 text-left">
        <Bookmark size={15} className="text-pink-400" />
        <span className="text-sm font-semibold">A precisar de decisão</span>
        <span className="text-xs text-gray-500">{dados.pending} anúncio{dados.pending === 1 ? '' : 's'}</span>
        <span className="ml-auto text-xs text-gray-500">{aberto ? 'esconder' : 'mostrar'}</span>
      </button>

      {aberto && (
        <div className="mt-3 space-y-2">
          {dados.items.map(i => (
            <div key={i.id} className="flex items-center gap-3 rounded-xl bg-[#161616] border border-[#222] p-2.5">
              {i.image_url && <img src={i.image_url} alt="" className="h-12 w-12 rounded-lg object-cover shrink-0" />}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <a href={i.url} target="_blank" rel="noreferrer" className="truncate text-sm hover:text-pink-300">
                    {i.title}
                  </a>
                  <ExternalLink size={11} className="shrink-0 text-gray-600" />
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px]">
                  <span className="font-semibold text-gray-200">
                    {i.price != null ? `${i.price.toFixed(0)}${i.currency === 'EUR' ? '€' : ' ' + i.currency}` : 'sem preço'}
                  </span>
                  {i.price_percentile != null && (
                    <span className={i.price_percentile <= 25 ? 'text-emerald-400' : 'text-gray-500'}>
                      {i.price_percentile === 0
                        ? 'o mais barato que já vi'
                        : `mais barato que ${100 - i.price_percentile}% dos que vi`}
                    </span>
                  )}
                  {i.fair_price != null && i.vs_fair != null ? (
                    <span className={i.vs_fair < 0 ? 'text-emerald-400' : 'text-gray-500'}>
                      {i.vs_fair < 0 ? `${Math.abs(i.vs_fair).toFixed(0)}€ abaixo` : `${i.vs_fair.toFixed(0)}€ acima`} do que vale
                      <span className="text-gray-600"> (uma {i.fair_basis}: {i.fair_price.toFixed(0)}€)</span>
                    </span>
                  ) : i.vs_median != null && i.vs_median < 0 && (
                    <span className="text-emerald-400">{Math.abs(i.vs_median).toFixed(0)}€ abaixo do costume</span>
                  )}
                  {i.checks?.filter(c => c.status !== 'ok').map(c => (
                    <span key={c.key} title={c.detail}
                      className={c.status === 'fail' ? 'text-red-400' : 'text-amber-400/80'}>
                      {c.status === 'fail' ? '✗' : '?'} {c.label}
                    </span>
                  ))}
                  <span className={`rounded px-1.5 py-0.5 ${ratingColor(i.ai_rating)}`}>{i.ai_rating ?? '?'}</span>
                  <span className="text-gray-600">{i.watch_title}</span>
                </div>
              </div>
              <div className="flex shrink-0 gap-1">
                <button onClick={() => decidir(i.id, true)} disabled={ocupado} title="Guardar"
                  className="rounded-lg bg-emerald-500/15 p-2 text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-40">
                  <Bookmark size={14} />
                </button>
                <button onClick={() => decidir(i.id, false)} disabled={ocupado} title="Não interessa"
                  className="rounded-lg bg-white/5 p-2 text-gray-400 hover:bg-white/10 disabled:opacity-40">
                  <X size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


// O mercado deste watch: com centenas de anúncios recolhidos, a app já sabe
// quanto a coisa costuma custar — é o que falta para decidir num anúncio novo.
function MercadoDoWatch({ watchId }: { watchId: number }) {
  const [d, setD] = useState<DealPriceStats | null>(null);

  useEffect(() => { setD(null); dealsApi.priceStats(watchId).then(setD).catch(() => setD(null)); }, [watchId]);
  if (!d || !d.enough || d.median === undefined) return null;

  const min = d.min!, max = d.max!, span = Math.max(1, max - min);
  const x = (v: number) => ((v - min) / span) * 100;
  const meses = (d.months || []).filter(m => m.count >= 3);
  const tendencia = meses.length >= 2 ? meses[meses.length - 1].median - meses[0].median : 0;

  return (
    <div className="bg-[#161616] rounded-xl border border-[#222] p-4 mb-4">
      <div className="flex items-baseline justify-between gap-2 mb-3 flex-wrap">
        <h4 className="text-sm font-medium text-gray-300">Quanto isto costuma custar</h4>
        <span className="text-[11px] text-gray-500">{d.count} anúncios válidos</span>
      </div>

      <div className="relative h-14 px-1">
        <div className="absolute top-6 left-0 right-0 h-1.5 bg-[#1a1a1a] rounded-full" />
        <div className="absolute top-6 h-1.5 bg-pink-500/25 rounded-full"
          style={{ left: `${x(d.p25!)}%`, width: `${x(d.p75!) - x(d.p25!)}%` }} />
        <div className="absolute top-[19px] w-[3px] h-[16px] bg-pink-400 rounded"
          style={{ left: `${x(d.median!)}%`, transform: 'translateX(-1px)' }} />
        <span className="absolute top-0 text-[10px] font-medium text-pink-300 whitespace-nowrap"
          style={{ left: `${Math.min(88, Math.max(6, x(d.median!)))}%`, transform: 'translateX(-50%)' }}>
          €{d.median!.toFixed(0)}
        </span>
        <span className="absolute top-9 left-0 text-[10px] text-gray-600">€{min.toFixed(0)}</span>
        <span className="absolute top-9 right-0 text-[10px] text-gray-600">€{max.toFixed(0)}</span>
        {([d.p25!, d.p75!] as const).map(v => (
          <span key={v} className="absolute top-9 text-[10px] text-gray-500 whitespace-nowrap"
            style={{ left: `${Math.min(90, Math.max(10, x(v)))}%`, transform: 'translateX(-50%)' }}>
            €{v.toFixed(0)}
          </span>
        ))}
      </div>

      <div className="flex items-center gap-3 flex-wrap text-[11px] text-gray-500 mt-2">
        <span>metade dos anúncios anda entre <span className="text-gray-300">€{d.p25!.toFixed(0)}</span> e <span className="text-gray-300">€{d.p75!.toFixed(0)}</span></span>
        {meses.length >= 2 && (
          <span className={tendencia > 50 ? 'text-red-400' : tendencia < -50 ? 'text-emerald-400' : ''}>
            · mediana {tendencia > 50 ? 'a subir' : tendencia < -50 ? 'a descer' : 'estável'}
            {Math.abs(tendencia) >= 50 && ` (${tendencia > 0 ? '+' : '−'}€${Math.abs(tendencia).toFixed(0)} desde ${meses[0].month.slice(5)}/${meses[0].month.slice(2, 4)})`}
          </span>
        )}
      </div>
    </div>
  );
}

export default function DealsPage() {
  const [watches, setWatches] = useState<DealWatch[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [results, setResults] = useState<DealResult[]>([]);
  const [filter, setFilter] = useState<'good' | 'all' | 'saved' | 'unmatched' | 'failed' | 'gone'>('good');
  // Vazio = todas. Cada watch tem as suas fontes, por isso a escolha não
  // atravessa watches.
  const [fontes, setFontes] = useState<string[]>([]);
  const [loadingResults, setLoadingResults] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<DealWatch | null>(null);
  const [form, setForm] = useState<DealWatchInput>(emptyForm);
  const setCriterio = (chave: string, valor: unknown) =>
    setForm(f => ({ ...f, criteria: { ...(f.criteria || {}), [chave]: valor } }));
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
      else if (filter === 'gone') setResults(await dealsApi.results(watchId, { status: 'gone' }));
      else if (filter === 'unmatched') setResults(await dealsApi.results(watchId, { include_unmatched: true, include_failed: true }));
      else if (filter === 'failed') setResults(await dealsApi.results(watchId, { include_failed: true }));
      // "Melhores" e "Todos" nunca mostram o que falha uma exigência: ele não
      // quer saber. O que o anúncio não diz **entra** — não é um "não".
      else setResults(await dealsApi.results(watchId));
    } finally {
      setLoadingResults(false);
    }
  }

  useEffect(() => {
    if (selectedId !== null) loadResults(selectedId);
  }, [selectedId, filter]);

  useEffect(() => { setFontes([]); }, [selectedId]);

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

  // Só os "Melhores" escondem o que falha as exigências. "Todos" é todos — foi
  // por isto que a lista apareceu vazia: 38 motas à venda e nenhuma cumpria.
  const naoCumprem = selected ? (selected.total_count - results.filter(r => r.verdict !== 'fail').length) : 0;
  const noSeparador = results.filter(r => {
    if (filter === 'good') {
      return r.ai_match && r.verdict !== 'fail'
        && (r.ai_rating ?? -1) >= (selected?.min_rating ?? 0);
    }
    if (filter === 'gone') return true;
    if (filter === 'unmatched') return !r.ai_match;
    if (filter === 'failed') return r.verdict === 'fail';
    return true;
  });
  // Quantos há de cada fonte **neste separador** — o número é o que dá sentido
  // ao botão: "OLX 42" diz logo se vale a pena carregar.
  const contaPorFonte = new Map<string, number>();
  noSeparador.forEach(r => contaPorFonte.set(r.source, (contaPorFonte.get(r.source) || 0) + 1));
  const fontesPresentes = TODAS_AS_FONTES.filter(f => contaPorFonte.has(f));
  const visibleResults = noSeparador.filter(r => {
    return fontes.length === 0 || fontes.includes(r.source);
  }).sort((a, b) => {
    // As que falham por pouco primeiro: "falha só a potência" é uma decisão a
    // tomar; "falha o ano, os km e a potência" é lixo.
    if (filter !== 'failed') return 0;
    return quantasFalham(a) - quantasFalham(b);
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
      ai_context: w.ai_context, exclude_keywords: w.exclude_keywords, criteria: w.criteria || {},
      kind: w.kind || 'specific', notify: w.notify ?? true, active: w.active,
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
            <p className="text-xs text-gray-500">Caça-deals · Vinted + OLX + Facebook + IA web · scan automático 2x/dia · ou carrega Procurar</p>
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

      <Triagem onDecidido={() => { loadWatches(); if (selectedId) loadResults(selectedId); }} />

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
                {w.kind === 'generic' && <span className="px-1.5 py-0.5 rounded bg-purple-500/15 text-purple-300">tema</span>}
                {w.notify === false && <span className="px-1.5 py-0.5 rounded bg-white/5 text-gray-500">sem avisos</span>}
                {w.gone_count > 0 && <span className="px-1.5 py-0.5 rounded bg-white/5 text-gray-500">{w.gone_count} já não estão</span>}
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
                  {([['good', 'Melhores'], ['all', 'Todos'], ['saved', 'Guardados'], ['unmatched', 'Descartados IA'], ['failed', 'Não cumprem'], ['gone', 'Já não estão']] as const).map(([k, label]) => (
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

              {/* Fontes: só aparecem as que têm anúncios neste separador, e só
                  quando há mais do que uma — com uma só não há nada a filtrar. */}
              {fontesPresentes.length > 1 && (
                <div className="flex items-center gap-1.5 flex-wrap text-[11px] mb-3">
                  <span className="text-gray-600 mr-0.5">Fonte:</span>
                  <button
                    onClick={() => setFontes([])}
                    className={`px-2 py-1 rounded-lg border transition-colors ${
                      fontes.length === 0
                        ? 'bg-pink-600/15 text-pink-300 border-pink-500/40'
                        : 'bg-white/5 text-gray-500 border-transparent hover:text-gray-300'
                    }`}
                  >Todas <span className="text-gray-600">{noSeparador.length}</span></button>
                  {fontesPresentes.map(f => {
                    const activo = fontes.includes(f);
                    return (
                      <button
                        key={f}
                        onClick={() => setFontes(activo ? fontes.filter(x => x !== f) : [...fontes, f])}
                        className={`px-2 py-1 rounded-lg border transition-colors ${
                          activo
                            ? 'bg-pink-600/15 text-pink-300 border-pink-500/40'
                            : 'bg-white/5 text-gray-500 border-transparent hover:text-gray-300'
                        }`}
                      >{FONTE_CURTA[f] || f} <span className="text-gray-600">{contaPorFonte.get(f)}</span></button>
                    );
                  })}
                </div>
              )}

              <MercadoDoWatch watchId={selected.id} />

              {loadingResults ? (
                <div className="flex items-center gap-2 text-gray-500 text-sm py-20 justify-center"><Loader2 className="animate-spin" size={18} /> a carregar…</div>
              ) : visibleResults.length === 0 ? (
                <div className="text-center text-gray-500 text-sm py-16 border border-dashed border-[#333] rounded-xl px-4">
                  <Search size={20} className="mx-auto mb-2 opacity-50" />
                  {fontes.length > 0 ? (
                    // Acontece ao mudar de separador com uma fonte escolhida: os
                    // botões só mostram as fontes deste separador, e a escolhida
                    // pode não estar cá.
                    <>
                      Nenhum anúncio {fontes.length === 1 ? 'do ' : 'de '}
                      <span className="text-gray-300">{fontes.map(f => FONTE_CURTA[f] || f).join(' ou ')}</span> neste separador.<br />
                      <button onClick={() => setFontes([])} className="text-pink-400 hover:underline">Ver todas as fontes</button>
                      {noSeparador.length > 0 && <span className="text-gray-600"> ({noSeparador.length} {noSeparador.length === 1 ? 'anúncio' : 'anúncios'})</span>}
                    </>
                  ) : filter === 'good' && naoCumprem > 0 ? (
                    <>
                      <span className="text-gray-200 font-medium">{naoCumprem}</span>{' '}
                      {naoCumprem === 1 ? 'anúncio existe' : 'anúncios existem'}, mas{' '}
                      {naoCumprem === 1 ? 'não cumpre' : 'nenhum cumpre'} as exigências que puseste.<br />
                      Vê <button onClick={() => setFilter('failed')} className="text-pink-400 hover:underline">Não cumprem</button>{' '}
                      para saber o que falha, ou alarga uma exigência no watch.
                    </>
                  ) : filter === 'good' && selected.pending_count > 0 ? (
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
                        {r.status === 'new' && r.ai_match && !r.reappeared_at && (
                          <span className="absolute bottom-2 left-2 text-[10px] font-bold rounded px-1.5 py-0.5 bg-pink-600 text-white">NOVO</span>
                        )}
                        {r.reappeared_at && r.status !== 'gone' && (
                          <span className="absolute bottom-2 left-2 text-[10px] font-bold rounded px-1.5 py-0.5 bg-amber-500 text-black">VOLTOU</span>
                        )}
                        {r.status === 'gone' && (
                          <span className="absolute inset-0 bg-black/55 flex items-end p-2">
                            <span className="text-[10px] font-bold rounded px-1.5 py-0.5 bg-gray-700 text-gray-200">JÁ NÃO ESTÁ</span>
                          </span>
                        )}
                      </div>
                      <div className="p-3 flex-1 flex flex-col">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="font-semibold text-sm truncate">{r.title}</span>
                          {r.price != null && <span className="shrink-0 font-bold text-emerald-400 text-sm">{r.price}{r.currency === 'EUR' ? '€' : ' ' + r.currency}</span>}
                        </div>
                        {r.fair_price != null && r.vs_fair != null ? (
                          <p className={`text-[11px] mt-0.5 ${
                            r.vs_fair <= -300 ? 'text-emerald-400' : r.vs_fair >= 300 ? 'text-red-400' : 'text-gray-500'
                          }`}>
                            {r.vs_fair <= -300 ? 'abaixo do que vale'
                              : r.vs_fair >= 300 ? 'acima do que vale' : 'no preço'}
                            <span className="text-gray-600">
                              {' '}· uma {r.fair_basis} anda nos {r.fair_price.toFixed(0)}€
                              {Math.abs(r.vs_fair) >= 1 && ` (${r.vs_fair < 0 ? '−' : '+'}${Math.abs(r.vs_fair).toFixed(0)}€)`}
                            </span>
                          </p>
                        ) : r.price_percentile !== null && r.vs_median !== null && (
                          <p className="text-[11px] mt-0.5 text-gray-500">
                            {r.price_percentile <= 25 ? 'barato' : r.price_percentile >= 75 ? 'caro' : 'preço normal'}
                            <span className="text-gray-600"> · mais barato que {100 - r.price_percentile}% do que já vimos</span>
                          </p>
                        )}
                        {quantasFalham(r) === 1 && (
                          <p className="text-[11px] mt-1 text-amber-400">
                            Falha só: {(r.checks || []).find(c => c.status === 'fail')?.label}
                          </p>
                        )}
                        {r.checks?.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-1.5">
                            {r.checks.map(c => (
                              <span key={c.key} title={c.detail}
                                className={`text-[10px] rounded px-1.5 py-0.5 ${
                                  c.status === 'ok' ? 'bg-emerald-500/15 text-emerald-300'
                                    : c.status === 'fail' ? 'bg-red-500/15 text-red-300'
                                      : 'bg-amber-500/10 text-amber-400/80'
                                }`}>
                                {c.status === 'ok' ? '✓' : c.status === 'fail' ? '✗' : '?'} {c.label}
                              </span>
                            ))}
                          </div>
                        )}
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
              <Field label="Tipo">
                <div className="flex gap-2">
                  {([['specific', 'Produto certo', 'só me mostra este produto'],
                     ['generic', 'Tema', 'mostra o que houver de bom no tema']] as const).map(([v, label, hint]) => (
                    <button key={v} onClick={() => setForm({ ...form, kind: v })}
                      className={`flex-1 text-left px-3 py-2 rounded-xl border text-xs transition-colors ${
                        (form.kind || 'specific') === v
                          ? 'border-pink-500/60 bg-pink-500/10 text-pink-200'
                          : 'border-[#333] bg-[#1a1a1a] text-gray-400 hover:text-gray-200'
                      }`}>
                      <span className="block font-medium">{label}</span>
                      <span className="block text-[10px] text-gray-500 mt-0.5">{hint}</span>
                    </button>
                  ))}
                </div>
              </Field>
              <Field label="Título">
                <input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })}
                  placeholder={form.kind === 'generic' ? 'Bicicletas baratas' : 'iPhone 17'} className="inp" />
              </Field>
              <Field label="Termos de pesquisa">
                <input value={form.query} onChange={e => setForm({ ...form, query: e.target.value })}
                  placeholder={form.kind === 'generic' ? 'bicicleta' : 'iphone 17'} className="inp" />
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
                <div className="col-span-2">
                  <Field label="Fontes (escolhe as que quiseres)">
                    <div className="flex flex-wrap gap-1.5">
                      <button type="button" onClick={() => setForm({ ...form, sources: 'all' })}
                        className={`px-2.5 py-1.5 rounded-lg text-xs transition-colors ${
                          (form.sources || 'all') === 'all'
                            ? 'bg-pink-600 text-white' : 'bg-[#1f1f1f] text-gray-400 hover:text-gray-200'
                        }`}>
                        Todas
                      </button>
                      {FONTES.map(([id, label]) => {
                        const activo = fontesEscolhidas(form.sources).includes(id);
                        return (
                          <button key={id} type="button"
                            onClick={() => setForm({ ...form, sources: alternaFonte(form.sources, id) })}
                            className={`px-2.5 py-1.5 rounded-lg text-xs transition-colors ${
                              activo ? 'bg-pink-600 text-white' : 'bg-[#1f1f1f] text-gray-400 hover:text-gray-200'
                            }`}>
                            {label}
                          </button>
                        );
                      })}
                    </div>
                  </Field>
                </div>
                <Field label="Preço máximo (€)">
                  <input type="number" value={form.max_price ?? ''} onChange={e => setForm({ ...form, max_price: e.target.value ? Number(e.target.value) : null })} placeholder="sem limite" className="inp" />
                </Field>
              </div>
              <Field label={`Rating mínimo para notificar: ${form.min_rating}`}>
                <input type="range" min={0} max={100} value={form.min_rating} onChange={e => setForm({ ...form, min_rating: Number(e.target.value) })} className="w-full accent-pink-500" />
              </Field>
              <div className="rounded-xl border border-[#2a2a2a] bg-[#141414] p-3 space-y-3">
                <div>
                  <div className="text-xs text-gray-300 font-medium">Exigências</div>
                  <p className="text-[11px] text-gray-500 mt-0.5">
                    Verificadas no texto do anúncio, não deixadas ao critério da IA. O que o anúncio
                    não disser fica marcado como <span className="text-amber-400">não diz</span> e continua na lista.
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Field label="Ano de">
                    <input type="number" placeholder="2021" className="inp"
                      value={form.criteria?.year_min ?? ''}
                      onChange={e => setCriterio('year_min', e.target.value ? Number(e.target.value) : null)} />
                  </Field>
                  <Field label="Ano até">
                    <input type="number" placeholder="2024" className="inp"
                      value={form.criteria?.year_max ?? ''}
                      onChange={e => setCriterio('year_max', e.target.value ? Number(e.target.value) : null)} />
                  </Field>
                  <Field label="Km no máximo">
                    <input type="number" placeholder="10000" className="inp"
                      value={form.criteria?.km_max ?? ''}
                      onChange={e => setCriterio('km_max', e.target.value ? Number(e.target.value) : null)} />
                  </Field>
                  <Field label="Potência (kW)">
                    <input type="number" placeholder="35" className="inp"
                      value={form.criteria?.power_kw_min ?? ''}
                      onChange={e => {
                        const v = e.target.value ? Number(e.target.value) : null;
                        setForm(f => ({ ...f, criteria: { ...(f.criteria || {}), power_kw_min: v, power_kw_max: v } }));
                      }} />
                  </Field>
                </div>
                <Field label="Cor">
                  <div className="flex flex-wrap gap-1.5">
                    {CORES.map(c => {
                      const activo = (form.criteria?.colors || []).includes(c);
                      return (
                        <button key={c} type="button"
                          onClick={() => {
                            const actuais = form.criteria?.colors || [];
                            setCriterio('colors', activo ? actuais.filter(x => x !== c) : [...actuais, c]);
                          }}
                          className={`px-2.5 py-1 rounded-lg text-xs capitalize transition-colors ${
                            activo ? 'bg-pink-600 text-white' : 'bg-[#1f1f1f] text-gray-400 hover:text-gray-200'
                          }`}>
                          {c}
                        </button>
                      );
                    })}
                  </div>
                </Field>
                <Field label="Tem de dizer na descrição (vírgulas)">
                  <input className="inp" placeholder="akrapovic"
                    value={(form.criteria?.must_include || []).join(', ')}
                    onChange={e => setCriterio('must_include', listaDeTexto(e.target.value))} />
                </Field>
                <Field label="Não serve se disser (vírgulas)">
                  <input className="inp" placeholder="acidentada, para peças"
                    value={(form.criteria?.must_exclude || []).join(', ')}
                    onChange={e => setCriterio('must_exclude', listaDeTexto(e.target.value))} />
                </Field>
              </div>
              <Field label="Contexto para a IA (o que é / o que NÃO é)">
                <textarea value={form.ai_context} onChange={e => setForm({ ...form, ai_context: e.target.value })} rows={3}
                  placeholder={form.kind === 'generic'
                    ? 'Bicicletas de estrada ou gravel em bom estado, tamanho M/L. Nada de crianças nem BTT velho.'
                    : 'É o iPhone 17 normal. NÃO quero o 17e, nem Plus, nem Pro. Nada de capas/peças.'}
                  className="inp resize-none" />
              </Field>
              <Field label="Excluir se o título tiver (separado por vírgulas)">
                <input value={form.exclude_keywords} onChange={e => setForm({ ...form, exclude_keywords: e.target.value })} placeholder="17e, plus, capa, case" className="inp" />
              </Field>
              <button onClick={() => setForm({ ...form, notify: !(form.notify ?? true) })}
                className="flex items-center gap-2 text-xs text-gray-400 hover:text-gray-200">
                <span className={`w-9 h-5 rounded-full relative transition-colors ${form.notify ?? true ? 'bg-pink-600' : 'bg-[#333]'}`}>
                  <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all ${form.notify ?? true ? 'left-[18px]' : 'left-0.5'}`} />
                </span>
                Avisar-me quando aparecer um achado bom
              </button>
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

const FONTES = [
  ['olx', 'OLX'],
  ['facebook', 'Facebook Marketplace'],
  ['standvirtual', 'StandVirtual'],
  ['vinted', 'Vinted'],
  ['web', 'IA (web)'],
] as const;

const TODAS_AS_FONTES = FONTES.map(([id]) => id as string);

// Nos botões de filtro da lista o nome tem de caber: "Facebook Marketplace"
// numa fila de cinco botões parte a linha.
const FONTE_CURTA: Record<string, string> = {
  olx: 'OLX', facebook: 'Facebook', standvirtual: 'StandVirtual',
  vinted: 'Vinted', web: 'IA (web)',
};

function fontesEscolhidas(spec: string | undefined): string[] {
  const s = (spec || 'all').trim().toLowerCase();
  if (!s || s === 'all') return TODAS_AS_FONTES;
  return s.split(',').map(x => x.trim()).filter(Boolean);
}

function alternaFonte(spec: string | undefined, id: string): string {
  const actuais = fontesEscolhidas(spec);
  const proximas = actuais.includes(id) ? actuais.filter(x => x !== id) : [...actuais, id];
  // Sem nenhuma escolhida não se pesquisa nada — nesse caso volta a "todas".
  if (proximas.length === 0) return 'all';
  if (proximas.length === TODAS_AS_FONTES.length) return 'all';
  return proximas.join(',');
}

const CORES = ['preto', 'branco', 'azul', 'vermelho', 'cinzento', 'verde', 'amarelo', 'laranja'];

function quantasFalham(r: DealResult): number {
  return (r.checks || []).filter(c => c.status === 'fail').length;
}

function listaDeTexto(s: string): string[] {
  return s.split(',').map(x => x.trim()).filter(Boolean);
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs text-gray-400 mb-1 block">{label}</span>
      {children}
    </label>
  );
}
