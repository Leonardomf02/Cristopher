import { useEffect, useRef, useState } from 'react';
import {
  Music, Sparkles, ArrowLeft, Trash2, AlertCircle, ExternalLink, Loader2,
  Plus, Upload, Heart, Check, Pencil, Link2, Layers, Copy, ArrowRight,
  X, ChevronDown, ChevronUp, Search,
} from 'lucide-react';
import { format } from 'date-fns';
import {
  spotifyApi, SpotifyPlaylist, SpotifyTrack, SpotifyAnalysis, SpotifyOverview,
  SpotifySuggestion, SpotifySearchResult, SpotifyPlacement, SpotifyListening,
} from '../api';

const SPOTIFY = '#1DB954';

const VIBE_PRESETS = [
  'triste / melancólica', 'chill', 'rock + hype', 'vibe de verão',
  'portuguesas conhecidas', 'treino / gym', 'foco / estudo',
];


// O que tocou mesmo. As playlists são o que ele guardou; isto vem do tracker, que
// pergunta ao Spotify de 15 em 15 segundos mesmo com ele em segundo plano.
function OQueOuves() {
  const [dias, setDias] = useState(30);
  const [d, setD] = useState<SpotifyListening | null>(null);
  const [recentes, setRecentes] = useState<Awaited<ReturnType<typeof spotifyApi.history>>>([]);

  useEffect(() => {
    spotifyApi.listeningStats(dias).then(setD).catch(() => setD(null));
    spotifyApi.history(dias, 12).then(setRecentes).catch(() => setRecentes([]));
  }, [dias]);

  if (!d) return null;
  const hm = (s: number) => (s >= 3600 ? `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}` : `${Math.round(s / 60)}min`);
  const CAT: Record<string, string> = {
    development: 'a programar', productivity: 'a trabalhar', gaming: 'a jogar',
    social: 'em redes sociais', entertainment: 'a ver coisas', communication: 'a falar com gente',
    browser: 'no browser', system: 'no sistema', other: 'noutras coisas',
    finance: 'em contas', shopping: 'em compras',
  };
  const maxHora = Math.max(1, ...d.by_hour.map(h => h.seconds));

  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 sm:p-5 mb-4">
      <div className="flex items-center justify-between gap-3 mb-1 flex-wrap">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Music size={16} style={{ color: SPOTIFY }} /> O que ouves mesmo
        </div>
        <div className="flex gap-1">
          {[7, 30, 90].map(n => (
            <button key={n} onClick={() => setDias(n)}
              className={`text-[11px] px-2 py-0.5 rounded-lg ${dias === n ? 'bg-white/10 text-gray-200' : 'text-gray-500 hover:text-gray-300'}`}>
              {n}d
            </button>
          ))}
        </div>
      </div>

      {d.plays === 0 ? (
        <p className="text-xs text-gray-500">
          Ainda sem histórico. A app começa a registar assim que puseres música — não é preciso ter o Spotify à frente.
        </p>
      ) : (
        <>
          <p className="text-xs text-gray-500 mb-3">
            {hm(d.total_seconds)} de música em {d.plays} passagens desde {new Date(d.since).toLocaleDateString('pt-PT', { day: 'numeric', month: 'short' })}
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-1.5">Artistas</p>
              <div className="space-y-1">
                {d.artists.slice(0, 6).map(a => (
                  <div key={a.artist} className="flex items-center gap-2 text-xs">
                    <span className="flex-1 truncate">{a.artist}</span>
                    <span className="text-gray-600">{a.plays}x</span>
                    <span className="text-gray-400 w-12 text-right">{hm(a.seconds)}</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-1.5">Músicas</p>
              <div className="space-y-1">
                {d.tracks.slice(0, 6).map(t => (
                  <div key={`${t.track}-${t.artist}`} className="flex items-center gap-2 text-xs">
                    <span className="flex-1 truncate">{t.track} <span className="text-gray-600">· {t.artist}</span></span>
                    <span className="text-gray-400 w-12 text-right">{hm(t.seconds)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {d.by_activity.length > 0 && (
            <div className="mt-4">
              <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-1.5">Música enquanto estavas…</p>
              <div className="flex flex-wrap gap-1.5">
                {d.by_activity.map(a => (
                  <span key={a.category} className="text-[11px] px-2 py-1 rounded-lg bg-[#1a1a1a] text-gray-400">
                    {CAT[a.category] || a.category} · {hm(a.seconds)}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="mt-4">
            <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-1.5">A que horas ouves</p>
            <div className="flex items-end gap-[3px] h-10">
              {d.by_hour.map(h => (
                <div key={h.hour} className="flex-1 rounded-t" title={`${String(h.hour).padStart(2, '0')}h · ${hm(h.seconds)}`}
                  style={{ height: `${Math.max(4, (h.seconds / maxHora) * 100)}%`, backgroundColor: h.seconds ? SPOTIFY : '#222' }} />
              ))}
            </div>
            <div className="flex justify-between text-[9px] text-gray-600 mt-0.5">
              <span>00h</span><span>06h</span><span>12h</span><span>18h</span><span>23h</span>
            </div>
          </div>

          {recentes.length > 0 && (
            <details className="mt-3">
              <summary className="text-[11px] text-gray-500 cursor-pointer hover:text-gray-300">últimas passagens</summary>
              <div className="mt-2 space-y-1">
                {recentes.map(r => (
                  <div key={r.id} className="flex items-center gap-2 text-[11px] text-gray-500">
                    <span className="w-24 shrink-0">{new Date(r.started_at).toLocaleString('pt-PT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                    <span className="flex-1 truncate text-gray-400">{r.track} · {r.artist}</span>
                    <span>{hm(r.seconds)}</span>
                  </div>
                ))}
              </div>
            </details>
          )}
        </>
      )}
    </div>
  );
}

export default function SpotifyPage() {
  const [items, setItems] = useState<SpotifyPlaylist[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // criar
  const [showNew, setShowNew] = useState(false);
  const [newName, setNewName] = useState('');
  const [newVibe, setNewVibe] = useState('');
  const [newFav, setNewFav] = useState(false);
  const [creating, setCreating] = useState(false);

  // importar pelo link
  const [linkUrl, setLinkUrl] = useState('');
  const [linkLoading, setLinkLoading] = useState(false);

  // visão geral (transversal a todas as playlists)
  const [overview, setOverview] = useState<SpotifyOverview | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [overviewErr, setOverviewErr] = useState<string | null>(null);
  const [copiedGroup, setCopiedGroup] = useState<string | null>(null);
  const [groupSugs, setGroupSugs] = useState<Record<string, SpotifySuggestion[]>>({});
  const [groupModal, setGroupModal] = useState<SpotifyOverview['groups'][number] | null>(null);
  const [showRecs, setShowRecs] = useState(false);
  const [deduping, setDeduping] = useState(false);

  // adicionar música (pesquisa → IA escolhe a(s) playlist(s) → aprovo)
  type PlacementRow = SpotifyPlacement & { status: 'pending' | 'added' | 'already' | 'rejected' };
  const [songQuery, setSongQuery] = useState('');
  const [songResults, setSongResults] = useState<SpotifySearchResult[]>([]);
  const [songSearching, setSongSearching] = useState(false);
  const [songSel, setSongSel] = useState<SpotifySearchResult | null>(null);
  const [placing, setPlacing] = useState(false);
  const [placements, setPlacements] = useState<PlacementRow[]>([]);
  const [placeMsg, setPlaceMsg] = useState<string | null>(null);

  // detalhe
  const [current, setCurrent] = useState<SpotifyPlaylist | null>(null);
  const [tracks, setTracks] = useState<SpotifyTrack[]>([]);
  const [analysis, setAnalysis] = useState<SpotifyAnalysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [importText, setImportText] = useState('');
  const [importMode, setImportMode] = useState<'replace' | 'append'>('replace');
  const [importing, setImporting] = useState(false);
  const [editingVibe, setEditingVibe] = useState(false);
  const [vibeDraft, setVibeDraft] = useState('');
  const [suggestions, setSuggestions] = useState<SpotifySuggestion[]>([]);
  const [copiedPlaylist, setCopiedPlaylist] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => { loadList(); loadOverview(); loadGroupSugs(); }, []);

  // autocomplete com debounce
  useEffect(() => {
    if (songSel) return;
    const q = songQuery.trim();
    if (q.length < 2) { setSongResults([]); setSongSearching(false); return; }
    setSongSearching(true);
    const t = setTimeout(async () => {
      try { setSongResults(await spotifyApi.search(q)); }
      catch { setSongResults([]); }
      finally { setSongSearching(false); }
    }, 350);
    return () => clearTimeout(t);
  }, [songQuery, songSel]);

  async function pickSong(r: SpotifySearchResult) {
    setSongSel(r);
    setSongQuery(r.artist ? `${r.title} — ${r.artist}` : r.title);
    setSongResults([]);
    setPlacements([]);
    setPlaceMsg(null);
    setPlacing(true);
    try {
      const ps = await spotifyApi.place(r.title, r.artist);
      setPlacements(ps.map(p => ({ ...p, status: 'pending' as const })));
      if (ps.length === 0) setPlaceMsg('A IA não encontrou nenhuma playlist onde esta música encaixe.');
    } catch (e: any) {
      setPlaceMsg(e?.message || 'Erro a pedir sugestões à IA (pode estar em espera).');
    } finally { setPlacing(false); }
  }

  function resetSong() {
    setSongSel(null); setSongQuery(''); setSongResults([]);
    setPlacements([]); setPlaceMsg(null);
  }

  async function approvePlacement(p: PlacementRow) {
    if (!songSel) return;
    try {
      const res = await spotifyApi.addTrack(p.playlist_id, {
        title: songSel.title, artist: songSel.artist, album: songSel.album, spotify_url: songSel.search_url,
      });
      setPlacements(ps => ps.map(x => (x.playlist_id === p.playlist_id ? { ...x, status: res.already ? 'already' : 'added' } : x)));
      if (!res.already) setItems(it => it.map(x => (x.id === p.playlist_id ? { ...x, track_count: res.total } : x)));
    } catch (e: any) {
      setPlaceMsg(e?.message || 'Erro a adicionar à playlist.');
    }
  }

  function rejectPlacement(p: PlacementRow) {
    setPlacements(ps => ps.map(x => (x.playlist_id === p.playlist_id ? { ...x, status: 'rejected' } : x)));
  }

  async function removeDuplicates() {
    if (deduping) return;
    setDeduping(true);
    try {
      await spotifyApi.dedupe();
      setOverview(ov => (ov ? { ...ov, duplicates: [] } : ov));
      loadList();
    } catch { /* silent */ }
    finally { setDeduping(false); }
  }

  async function loadGroupSugs() {
    try { setGroupSugs(await spotifyApi.groupSuggestions()); }
    catch { /* silent */ }
  }

  async function loadList() {
    setLoadingList(true);
    try { setItems(await spotifyApi.list()); }
    catch { /* silent */ }
    finally { setLoadingList(false); }
  }

  async function loadOverview() {
    try {
      const ov = await spotifyApi.overview();
      if (ov.analyzed_at) setOverview(ov);
    } catch { /* silent */ }
  }

  async function runOverview() {
    if (overviewLoading) return;
    setOverviewErr(null);
    setOverviewLoading(true);
    try { setOverview(await spotifyApi.analyzeOverview()); }
    catch (e: any) { setOverviewErr(e?.message || 'Erro a analisar (a IA pode estar em espera)'); }
    finally { setOverviewLoading(false); }
  }

  async function copyToClipboard(text: string) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); } catch { /* ignore */ }
      document.body.removeChild(ta);
    }
  }

  function asLines(items: { title: string; artist: string }[]) {
    return items.map(t => (t.artist ? `${t.title} - ${t.artist}` : t.title)).join('\n');
  }

  async function copyGroup(groupName: string, tracks: { title: string; artist: string }[]) {
    const accepted = (groupSugs[groupName] || []).filter(s => s.accepted);
    await copyToClipboard(asLines([...tracks, ...accepted]));
    setCopiedGroup(groupName);
    setTimeout(() => setCopiedGroup(c => (c === groupName ? null : c)), 2000);
  }

  function openGroup(g: SpotifyOverview['groups'][number]) {
    setGroupModal(g);
    setShowRecs(false);
  }

  async function toggleGroupSuggestion(groupName: string, sid: number) {
    try {
      const updated = await spotifyApi.toggleSuggestion(sid);
      setGroupSugs(gs => ({ ...gs, [groupName]: (gs[groupName] || []).map(x => (x.id === sid ? updated : x)) }));
    } catch { /* silent */ }
  }

  async function toggleSuggestion(sid: number) {
    try {
      const updated = await spotifyApi.toggleSuggestion(sid);
      setSuggestions(s => s.map(x => (x.id === sid ? updated : x)));
    } catch { /* silent */ }
  }

  async function copyPlaylist() {
    const accepted = suggestions.filter(s => s.accepted);
    await copyToClipboard(asLines([...tracks, ...accepted]));
    setCopiedPlaylist(true);
    setTimeout(() => setCopiedPlaylist(false), 2000);
  }

  async function toggleFavorites() {
    if (!current) return;
    const next = !current.is_favorites;
    try {
      await spotifyApi.update(current.id, { is_favorites: next });
      setCurrent({ ...current, is_favorites: next });
    } catch (e: any) { setError(e?.message || 'Erro a marcar a playlist de gostadas'); }
  }

  async function create() {
    const name = newName.trim();
    if (!name || creating) return;
    setError(null);
    setCreating(true);
    try {
      const p = await spotifyApi.create({ name, vibe: newVibe.trim(), is_favorites: newFav });
      setShowNew(false);
      setNewName(''); setNewVibe(''); setNewFav(false);
      openPlaylist(p);
    } catch (e: any) {
      setError(e?.message || 'Erro a criar playlist');
    } finally { setCreating(false); }
  }

  async function importLink() {
    const url = linkUrl.trim();
    if (!url || linkLoading) return;
    setError(null);
    setLinkLoading(true);
    try {
      const res = await spotifyApi.importLink(url);
      setLinkUrl('');
      openPlaylist(res.playlist);
    } catch (e: any) {
      setError(e?.message || 'Erro a importar pelo link (a playlist é pública?)');
    } finally { setLinkLoading(false); }
  }

  async function openPlaylist(p: SpotifyPlaylist) {
    setError(null);
    setCurrent(p);
    setVibeDraft(p.vibe);
    setEditingVibe(false);
    setImportText('');
    setAnalysis(null);
    setSuggestions([]);
    setCopiedPlaylist(false);
    try {
      const [tk, an, sg] = await Promise.all([
        spotifyApi.tracks(p.id), spotifyApi.analysis(p.id), spotifyApi.suggestions(p.id),
      ]);
      setTracks(tk);
      if (an.analyzed_at) setAnalysis(an);
      setSuggestions(sg);
    } catch { /* silent */ }
  }

  function backToList() {
    setCurrent(null);
    setError(null);
    loadList();
  }

  async function doImport(text: string) {
    if (!current || !text.trim() || importing) return;
    setError(null);
    setImporting(true);
    try {
      await spotifyApi.import(current.id, text, importMode);
      const tk = await spotifyApi.tracks(current.id);
      setTracks(tk);
      setImportText('');
      setAnalysis(null);  // import invalida a análise antiga
      setCurrent({ ...current, track_count: tk.length, analyzed_at: null });
    } catch (e: any) {
      setError(e?.message || 'Erro a importar');
    } finally { setImporting(false); }
  }

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    const text = await f.text();
    setImportText(text);
  }

  async function analyze() {
    if (!current || analyzing) return;
    setError(null);
    setAnalyzing(true);
    try {
      const an = await spotifyApi.analyze(current.id);
      setAnalysis(an);
      setCurrent({ ...current, analyzed_at: an.analyzed_at });
    } catch (e: any) {
      setError(e?.message || 'Erro na análise (IA pode estar em espera)');
    } finally { setAnalyzing(false); }
  }

  async function removeTrack(id: number) {
    if (!current) return;
    try { await spotifyApi.removeTrack(id); } catch { return; }
    setTracks(t => t.filter(x => x.id !== id));
    setAnalysis(a => a ? { ...a, intruders: a.intruders.filter(i => i.track_id !== id) } : a);
    setCurrent(c => c ? { ...c, track_count: c.track_count - 1 } : c);
  }

  async function saveVibe() {
    if (!current) return;
    try {
      const p = await spotifyApi.update(current.id, { vibe: vibeDraft.trim() });
      setCurrent({ ...current, vibe: p.vibe });
      setEditingVibe(false);
    } catch (e: any) { setError(e?.message || 'Erro a guardar vibe'); }
  }

  async function removePlaylist(id: number) {
    if (!confirm('Apagar esta playlist?')) return;
    try { await spotifyApi.remove(id); } catch { /* silent */ }
    if (current?.id === id) backToList();
    else loadList();
  }

  // ── Detail view ──────────────────────────────────────────────
  if (current) {
    const intruderIds = new Set((analysis?.intruders || []).map(i => i.track_id));
    const acceptedCount = suggestions.filter(s => s.accepted).length;
    return (
      <div className="max-w-3xl mx-auto">
        <button onClick={backToList}
          className="flex items-center gap-2 text-gray-400 hover:text-white mb-4 text-sm">
          <ArrowLeft size={16} /> Voltar às playlists
        </button>

        <div className="flex items-start justify-between gap-3 mb-1">
          <h2 className="text-2xl sm:text-3xl font-bold flex items-center gap-2">
            {current.is_favorites && <Heart size={22} className="text-pink-400 fill-pink-400 shrink-0" />}
            {current.name}
          </h2>
          <div className="flex items-center gap-1 shrink-0">
            <button onClick={toggleFavorites}
              className={`p-2 transition ${current.is_favorites ? 'text-pink-400' : 'text-gray-600 hover:text-pink-400'}`}
              title={current.is_favorites ? 'É a tua playlist de gostadas (clica para desmarcar)' : 'Marcar como a playlist de gostadas'}>
              <Heart size={18} className={current.is_favorites ? 'fill-pink-400' : ''} />
            </button>
            <button onClick={() => removePlaylist(current.id)}
              className="p-2 text-gray-600 hover:text-red-400" title="Apagar">
              <Trash2 size={18} />
            </button>
          </div>
        </div>

        {/* vibe */}
        <div className="flex items-center gap-2 mb-5 text-sm">
          <span className="text-gray-500 shrink-0">Vibe:</span>
          {editingVibe ? (
            <>
              <input value={vibeDraft} onChange={e => setVibeDraft(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') saveVibe(); }}
                autoFocus
                className="flex-1 bg-[#0f0f0f] border border-[#222] rounded-lg px-2 py-1 text-sm focus:outline-none focus:border-[#1DB954]" />
              <button onClick={saveVibe} className="p-1.5 text-[#1DB954] hover:bg-[#1DB954]/10 rounded-lg"><Check size={16} /></button>
            </>
          ) : (
            <>
              <span className="text-gray-300">{current.vibe || <span className="text-gray-600 italic">por definir</span>}</span>
              <button onClick={() => { setVibeDraft(current.vibe); setEditingVibe(true); }}
                className="p-1 text-gray-600 hover:text-white"><Pencil size={13} /></button>
            </>
          )}
        </div>

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3 mb-5 flex items-start gap-2">
            <AlertCircle size={16} className="text-red-400 mt-0.5 shrink-0" />
            <span className="text-sm text-red-400">{error}</span>
          </div>
        )}

        {/* importar */}
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 sm:p-5 mb-5">
          <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
            <h3 className="text-sm font-semibold">Importar faixas</h3>
            <div className="inline-flex rounded-lg bg-[#0f0f0f] border border-[#222] p-0.5 text-xs">
              {(['replace', 'append'] as const).map(m => (
                <button key={m} onClick={() => setImportMode(m)}
                  className={`px-2.5 py-1 rounded-md font-medium transition-colors ${importMode === m ? 'bg-[#1DB954] text-black' : 'text-gray-400 hover:text-white'}`}>
                  {m === 'replace' ? 'Substituir' : 'Acrescentar'}
                </button>
              ))}
            </div>
          </div>
          <textarea value={importText} onChange={e => setImportText(e.target.value)}
            placeholder={'Cola o link de uma playlist pública, OU uma lista (uma por linha):\nNumb - Linkin Park\nChop Suey! - System of a Down\n\n…ou carrega um CSV.'}
            rows={4}
            className="w-full bg-[#0f0f0f] border border-[#222] rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-[#1DB954] placeholder:text-gray-600 resize-y" />
          <div className="flex items-center gap-2 mt-2 flex-wrap">
            <button onClick={() => doImport(importText)} disabled={!importText.trim() || importing}
              className="flex items-center gap-1.5 px-4 py-2 bg-[#1DB954] hover:brightness-110 disabled:bg-[#222] disabled:text-gray-600 text-black font-semibold rounded-xl text-sm transition">
              {importing ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              Importar
            </button>
            <button onClick={() => fileRef.current?.click()}
              className="flex items-center gap-1.5 px-3 py-2 border border-[#222] hover:bg-[#1c1c1c] rounded-xl text-sm text-gray-300 transition">
              <Upload size={14} /> Carregar CSV
            </button>
            <input ref={fileRef} type="file" accept=".csv,text/csv,text/plain" onChange={onFile} className="hidden" />
          </div>
        </div>

        {/* faixas + ações */}
        <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
          <h3 className="text-sm font-medium text-gray-400">
            {tracks.length} faixas{acceptedCount > 0 && <span className="text-[#1DB954]"> + {acceptedCount} a adicionar</span>}
          </h3>
          <div className="flex items-center gap-2 flex-wrap">
            <button onClick={copyPlaylist} disabled={tracks.length + acceptedCount === 0}
              className={`flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-sm font-semibold transition disabled:bg-[#222] disabled:text-gray-600 ${copiedPlaylist ? 'bg-[#1DB954] text-black' : 'border border-[#2a2a2a] text-gray-200 hover:bg-[#1c1c1c]'}`}>
              {copiedPlaylist ? <Check size={14} /> : <Copy size={14} />}
              {copiedPlaylist ? 'Copiado!' : `Copiar playlist (${tracks.length + acceptedCount})`}
            </button>
            <button onClick={analyze} disabled={analyzing || tracks.length === 0}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition disabled:bg-[#222] disabled:text-gray-600"
              style={analyzing || tracks.length === 0 ? {} : { background: SPOTIFY, color: '#000' }}>
              {analyzing ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
              {analyzing ? 'A analisar…' : analysis ? 'Analisar de novo' : 'Analisar com IA'}
            </button>
          </div>
        </div>

        {/* análise */}
        {analysis && (
          <div className="space-y-4 mb-6">
            {analysis.summary && (
              <div className="bg-[#1DB954]/10 border border-[#1DB954]/30 rounded-2xl p-4">
                <p className="text-sm text-gray-200 leading-relaxed">{analysis.summary}</p>
                {current.analyzed_at && (
                  <p className="text-[11px] text-gray-500 mt-2">Analisado a {format(new Date(current.analyzed_at), 'dd/MM HH:mm')}</p>
                )}
              </div>
            )}

            {analysis.intruders.length > 0 && (
              <div>
                <h4 className="text-xs uppercase tracking-wide text-red-400 mb-2">Não encaixam ({analysis.intruders.length})</h4>
                <div className="space-y-2">
                  {analysis.intruders.map(i => (
                    <div key={i.track_id} className="bg-red-500/5 border border-red-500/20 rounded-xl p-3 flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-white truncate">{i.title}{i.artist && <span className="text-gray-400 font-normal"> — {i.artist}</span>}</p>
                        <p className="text-xs text-red-300/80 mt-0.5">{i.reason}</p>
                      </div>
                      <button onClick={() => removeTrack(i.track_id)}
                        className="p-1.5 text-gray-500 hover:text-red-400 shrink-0" title="Tirar da playlist (aqui)">
                        <Trash2 size={15} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {analysis.additions.length > 0 && (
              <div>
                <h4 className="text-xs uppercase tracking-wide text-[#1DB954] mb-2">Sugestões para adicionar ({analysis.additions.length})</h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {analysis.additions.map((a, idx) => (
                    <a key={idx} href={a.search_url} target="_blank" rel="noreferrer"
                      className="bg-[#161616] hover:bg-[#1c1c1c] border border-[#222] rounded-xl p-3 flex items-start justify-between gap-2 transition group">
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-white truncate">{a.title}{a.artist && <span className="text-gray-400 font-normal"> — {a.artist}</span>}</p>
                        <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{a.reason}</p>
                      </div>
                      <ExternalLink size={14} className="text-gray-600 group-hover:text-[#1DB954] shrink-0 mt-0.5" />
                    </a>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* recomendações para esta playlist */}
        {suggestions.length > 0 && (
          <div className="mb-6">
            <h3 className="text-sm font-semibold text-[#1DB954] mb-1 flex items-center gap-1.5">
              <Sparkles size={15} /> Recomendações para adicionar ({acceptedCount}/{suggestions.length})
            </h3>
            <p className="text-[11px] text-gray-500 mb-3">
              Músicas novas que encaixam nesta playlist. Carrega <Plus size={11} className="inline -mt-0.5" /> para marcares — as marcadas entram quando carregas em <strong className="text-gray-400">Copiar playlist</strong>.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {suggestions.map(s => (
                <div key={s.id}
                  className={`rounded-xl p-3 flex items-start justify-between gap-2 border transition ${s.accepted ? 'bg-[#1DB954]/10 border-[#1DB954]/40' : 'bg-[#161616] border-[#222]'}`}>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-white truncate">{s.title}{s.artist && <span className="text-gray-400 font-normal"> — {s.artist}</span>}</p>
                    <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{s.reason}</p>
                    <a href={s.search_url} target="_blank" rel="noreferrer"
                      className="text-[11px] text-gray-500 hover:text-[#1DB954] inline-flex items-center gap-1 mt-1">
                      <ExternalLink size={11} /> ouvir no Spotify
                    </a>
                  </div>
                  <button onClick={() => toggleSuggestion(s.id)}
                    title={s.accepted ? 'Tirar dos a adicionar' : 'Adicionar à playlist'}
                    className={`shrink-0 flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg font-medium transition ${s.accepted ? 'bg-[#1DB954] text-black' : 'border border-[#2a2a2a] text-gray-300 hover:text-white'}`}>
                    {s.accepted ? <><Check size={13} /> Adicionada</> : <><Plus size={13} /> Adicionar</>}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* lista de faixas */}
        {tracks.length > 0 ? (
          <div className="bg-[#161616] rounded-2xl border border-[#222] divide-y divide-[#1c1c1c]">
            {tracks.map((t, i) => (
              <div key={t.id} className={`flex items-center gap-3 px-4 py-2.5 group ${intruderIds.has(t.id) ? 'bg-red-500/5' : ''}`}>
                <span className="text-xs text-gray-600 w-5 text-right shrink-0">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-white truncate">{t.title}</p>
                  {t.artist && <p className="text-xs text-gray-500 truncate">{t.artist}</p>}
                </div>
                {t.spotify_url && (
                  <a href={t.spotify_url} target="_blank" rel="noreferrer" className="p-1 text-gray-600 hover:text-[#1DB954]" title="Abrir no Spotify">
                    <ExternalLink size={13} />
                  </a>
                )}
                <button onClick={() => removeTrack(t.id)} className="p-1 text-gray-700 hover:text-red-400 opacity-0 group-hover:opacity-100" title="Remover">
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-10 text-gray-600 text-sm">Sem faixas. Importa acima para começar.</div>
        )}
      </div>
    );
  }

  // ── List view ────────────────────────────────────────────────
  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center gap-3 mb-2">
        <Music size={28} style={{ color: SPOTIFY }} />
        <h2 className="text-2xl sm:text-3xl font-bold">Spotify</h2>
      </div>
      <p className="text-sm text-gray-500 mb-6">
        Cola o link de uma playlist <strong className="text-gray-400">pública</strong> e a app puxa as faixas. Depois dizes a vibe e a IA marca o que não encaixa e sugere músicas novas.
      </p>

      <OQueOuves />

      {/* visão geral (transversal a todas as playlists) */}
      {items.length > 0 && (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 sm:p-5 mb-4">
          <div className="flex items-center justify-between gap-3 mb-2 flex-wrap">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Layers size={16} style={{ color: SPOTIFY }} /> Visão geral
            </div>
            <button onClick={runOverview} disabled={overviewLoading}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-sm font-semibold transition disabled:bg-[#222] disabled:text-gray-600"
              style={overviewLoading ? {} : { background: SPOTIFY, color: '#000' }}>
              {overviewLoading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              {overviewLoading ? 'A analisar tudo…' : overview ? 'Analisar de novo' : 'Analisar tudo'}
            </button>
          </div>
          <p className="text-xs text-gray-500 mb-3">
            A IA olha para <strong className="text-gray-400">todas</strong> as playlists de uma vez: agrupa por género/mood e diz que músicas estavam melhor noutra playlist. Duplicados = a mesma faixa repetida <strong className="text-gray-400">dentro</strong> da mesma playlist (estar em várias playlists é normal).
          </p>

          {overviewErr && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3 mb-3 flex items-start gap-2">
              <AlertCircle size={16} className="text-red-400 mt-0.5 shrink-0" />
              <span className="text-sm text-red-400">{overviewErr}</span>
            </div>
          )}

          {overview && overview.analyzed_at && (
            <div className="space-y-4">
              <p className="text-[11px] text-gray-500">
                {overview.playlist_count} playlists · {overview.track_count} faixas · analisado a {format(new Date(overview.analyzed_at), 'dd/MM HH:mm')}
                {overview.truncated && ' · lista grande, analisada em parte'}
              </p>

              {overview.summary && (
                <div className="bg-[#1DB954]/10 border border-[#1DB954]/30 rounded-2xl p-4">
                  <p className="text-sm text-gray-200 leading-relaxed">{overview.summary}</p>
                </div>
              )}

              {overview.duplicates.length > 0 && (
                <div>
                  <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
                    <h4 className="text-xs uppercase tracking-wide text-amber-400 flex items-center gap-1.5">
                      <Copy size={13} /> Repetidas na mesma playlist ({overview.duplicates.length})
                    </h4>
                    <button onClick={removeDuplicates} disabled={deduping}
                      className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-amber-500/30 text-amber-300 hover:bg-amber-500/10 disabled:opacity-50 transition">
                      {deduping ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                      Remover duplicados (fica 1 de cada)
                    </button>
                  </div>
                  <div className="space-y-2">
                    {overview.duplicates.map((d, i) => (
                      <div key={i} className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-2.5 flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="text-sm text-white truncate">{d.title}{d.artist && <span className="text-gray-400 font-normal"> — {d.artist}</span>}</p>
                          <p className="text-xs text-gray-500 mt-0.5 truncate">em <span className="text-gray-400">{d.playlist}</span></p>
                        </div>
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-300 shrink-0">×{d.count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {overview.groups.length > 0 && (
                <div>
                  <h4 className="text-xs uppercase tracking-wide text-[#1DB954] mb-2 flex items-center gap-1.5">
                    <Layers size={13} /> Playlists sugeridas ({overview.groups.length})
                  </h4>
                  <p className="text-[11px] text-gray-500 mb-2">
                    As {overview.groups.length} playlists que te sugiro criar a partir das tuas músicas — pensadas para um dia substituírem as tuas {items.length} atuais. <strong className="text-gray-400">Abre uma</strong> para ver as músicas que lhe metia e as novas que recomendo juntar.
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {overview.groups.map((g, i) => {
                      const sugs = groupSugs[g.name] || [];
                      const acc = sugs.filter(s => s.accepted).length;
                      return (
                        <button key={i} onClick={() => openGroup(g)}
                          className="text-left bg-[#0f0f0f] hover:bg-[#161616] border border-[#222] rounded-xl p-3 transition group">
                          <div className="flex items-center justify-between gap-2 mb-1">
                            <div className="min-w-0">
                              <h5 className="text-sm font-semibold text-white truncate">{g.playlist_name || g.name}</h5>
                              <p className="text-[10px] text-gray-500 truncate">{g.name}</p>
                            </div>
                            <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#1DB954]/15 text-[#1DB954] shrink-0">{g.tracks.length}{acc > 0 && <span className="text-white"> +{acc}</span>}</span>
                          </div>
                          {g.mood && <p className="text-xs text-gray-500 line-clamp-1 mb-2">{g.mood}</p>}
                          <div className="flex items-center justify-between text-[11px]">
                            <span className="text-gray-600">{sugs.length > 0 ? `${sugs.length} recomendadas` : `${g.tracks.length} músicas`}</span>
                            <span className="text-[#1DB954] group-hover:underline">abrir →</span>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {overview.relocations.length > 0 && (
                <div>
                  <h4 className="text-xs uppercase tracking-wide text-blue-300 mb-2 flex items-center gap-1.5">
                    <ArrowRight size={13} /> Estavam melhor noutra playlist ({overview.relocations.length})
                  </h4>
                  <div className="space-y-2">
                    {overview.relocations.map((r, i) => (
                      <div key={i} className="bg-[#0f0f0f] border border-[#222] rounded-xl p-3">
                        <p className="text-sm text-white truncate">{r.title}{r.artist && <span className="text-gray-400 font-normal"> — {r.artist}</span>}</p>
                        <div className="flex items-center gap-1.5 text-xs mt-1 flex-wrap">
                          <span className="text-gray-500">{r.from || '—'}</span>
                          <ArrowRight size={12} className="text-[#1DB954] shrink-0" />
                          <span className="text-[#1DB954]">{r.to || '—'}</span>
                        </div>
                        {r.reason && <p className="text-xs text-gray-500 mt-1">{r.reason}</p>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* adicionar música: pesquisa → IA escolhe a(s) playlist(s) → aprovas */}
      {items.length > 0 && (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 sm:p-5 mb-4">
          <div className="flex items-center gap-2 mb-1.5 text-sm font-semibold">
            <Search size={16} style={{ color: SPOTIFY }} /> Adicionar música
          </div>
          <p className="text-xs text-gray-500 mb-3">
            Escreve o título, escolhe a música nas sugestões, e a IA diz em que playlists tuas ela encaixa — aprovas uma a uma.
          </p>

          <div className="relative">
            <div className="flex items-center gap-2">
              <input value={songQuery}
                onChange={e => { setSongQuery(e.target.value); if (songSel) { setSongSel(null); setPlacements([]); setPlaceMsg(null); } }}
                placeholder="ex: teenage…"
                className="flex-1 bg-[#0f0f0f] border border-[#222] rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-[#1DB954] placeholder:text-gray-600" />
              {(songQuery || songSel) && (
                <button onClick={resetSong} className="p-2 text-gray-500 hover:text-white" title="Limpar">
                  <X size={16} />
                </button>
              )}
            </div>

            {!songSel && (songSearching || songResults.length > 0) && (
              <div className="absolute left-0 right-0 top-full mt-1 z-20 bg-[#0f0f0f] border border-[#222] rounded-xl overflow-hidden shadow-xl">
                {songSearching && songResults.length === 0 ? (
                  <div className="flex items-center gap-2 px-3 py-2.5 text-xs text-gray-500">
                    <Loader2 size={13} className="animate-spin" /> A procurar…
                  </div>
                ) : songResults.map((r, i) => (
                  <button key={i} onClick={() => pickSong(r)}
                    className="w-full text-left px-3 py-2.5 hover:bg-[#1c1c1c] transition border-b border-[#1a1a1a] last:border-0">
                    <p className="text-sm text-white truncate">{r.title}{r.artist && <span className="text-gray-400"> — {r.artist}</span>}</p>
                    {r.album && <p className="text-[11px] text-gray-600 truncate">{r.album}</p>}
                  </button>
                ))}
              </div>
            )}
          </div>

          {placing && (
            <div className="flex items-center gap-2 mt-3 text-sm text-gray-400">
              <Loader2 size={15} className="animate-spin" /> A IA está a ver em que playlists encaixa…
            </div>
          )}

          {placeMsg && !placing && (
            <p className="text-xs text-amber-300/90 mt-3">{placeMsg}</p>
          )}

          {placements.length > 0 && !placing && (
            <div className="mt-3 space-y-2">
              {placements.map(p => (
                <div key={p.playlist_id}
                  className={`rounded-xl border p-3 flex items-start justify-between gap-3 transition ${
                    p.status === 'added' ? 'bg-[#1DB954]/10 border-[#1DB954]/40'
                    : p.status === 'rejected' ? 'bg-[#0f0f0f] border-[#222] opacity-45'
                    : 'bg-[#0f0f0f] border-[#222]'}`}>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-white truncate">{p.playlist_name}</p>
                    {p.reason && <p className="text-xs text-gray-500 mt-0.5">{p.reason}</p>}
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {p.status === 'pending' ? (
                      <>
                        <button onClick={() => approvePlacement(p)}
                          className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg bg-[#1DB954] text-black font-semibold hover:brightness-110 transition">
                          <Check size={13} /> Sim
                        </button>
                        <button onClick={() => rejectPlacement(p)}
                          className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg border border-[#2a2a2a] text-gray-400 hover:text-white transition">
                          <X size={13} /> Não
                        </button>
                      </>
                    ) : (
                      <span className={`text-[11px] px-2 py-1 rounded-full ${
                        p.status === 'added' ? 'bg-[#1DB954]/15 text-[#1DB954]'
                        : p.status === 'already' ? 'bg-blue-500/15 text-blue-300'
                        : 'bg-[#1c1c1c] text-gray-500'}`}>
                        {p.status === 'added' ? 'Adicionada ✓' : p.status === 'already' ? 'Já lá estava' : 'Rejeitada'}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* importar pelo link */}
      <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 mb-4">
        <div className="flex items-center gap-2 mb-1.5 text-sm font-semibold">
          <Link2 size={16} style={{ color: SPOTIFY }} /> Importar pelo link
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <input value={linkUrl} onChange={e => setLinkUrl(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') importLink(); }}
            placeholder="https://open.spotify.com/playlist/…"
            className="flex-1 min-w-[200px] bg-[#0f0f0f] border border-[#222] rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-[#1DB954] placeholder:text-gray-600" />
          <button onClick={importLink} disabled={!linkUrl.trim() || linkLoading}
            className="flex items-center gap-1.5 px-4 py-2.5 bg-[#1DB954] hover:brightness-110 disabled:bg-[#222] disabled:text-gray-600 text-black font-semibold rounded-xl text-sm transition">
            {linkLoading ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />} Importar
          </button>
        </div>
        <p className="text-[11px] text-gray-600 mt-2">
          A playlist tem de estar pública. Em playlists muito grandes pode vir incompleta — depois é só colar o resto dentro da playlist.
          As <strong>gostadas</strong> são privadas: para essas, cria uma playlist manual e cola a lista.
        </p>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3 mb-5 flex items-start gap-2">
          <AlertCircle size={16} className="text-red-400 mt-0.5 shrink-0" />
          <span className="text-sm text-red-400">{error}</span>
        </div>
      )}

      {/* criar */}
      {showNew ? (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-5 mb-8">
          <input value={newName} onChange={e => setNewName(e.target.value)} autoFocus
            placeholder="Nome da playlist (ex: Itachi, Shower, Home…)"
            className="w-full bg-[#0f0f0f] border border-[#222] rounded-xl px-3 py-2.5 text-sm mb-3 focus:outline-none focus:border-[#1DB954] placeholder:text-gray-600" />
          <input value={newVibe} onChange={e => setNewVibe(e.target.value)}
            placeholder="Vibe / espírito (ex: músicas tristes, rock + hype…)"
            className="w-full bg-[#0f0f0f] border border-[#222] rounded-xl px-3 py-2.5 text-sm mb-3 focus:outline-none focus:border-[#1DB954] placeholder:text-gray-600" />
          <div className="flex flex-wrap gap-1.5 mb-4">
            {VIBE_PRESETS.map(v => (
              <button key={v} onClick={() => setNewVibe(v)}
                className={`text-xs px-2.5 py-1 rounded-full border transition ${newVibe === v ? 'bg-[#1DB954] text-black border-[#1DB954]' : 'border-[#2a2a2a] text-gray-400 hover:text-white'}`}>
                {v}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-300 mb-4 cursor-pointer select-none">
            <input type="checkbox" checked={newFav} onChange={e => setNewFav(e.target.checked)} className="accent-pink-500" />
            <Heart size={14} className="text-pink-400" /> É a lista de músicas gostadas (favoritas)
          </label>
          <div className="flex items-center gap-2">
            <button onClick={create} disabled={!newName.trim() || creating}
              className="flex items-center gap-2 px-5 py-2.5 bg-[#1DB954] hover:brightness-110 disabled:bg-[#222] disabled:text-gray-600 text-black font-semibold rounded-xl text-sm transition">
              {creating ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />} Criar
            </button>
            <button onClick={() => setShowNew(false)} className="px-4 py-2.5 text-sm text-gray-400 hover:text-white">Cancelar</button>
          </div>
        </div>
      ) : (
        <button onClick={() => setShowNew(true)}
          className="flex items-center gap-2 px-5 py-2.5 mb-8 bg-[#1DB954] hover:brightness-110 text-black font-semibold rounded-xl text-sm transition">
          <Plus size={16} /> Nova playlist
        </button>
      )}

      {loadingList ? (
        <div className="flex items-center gap-2 text-gray-600 text-sm py-8">
          <Loader2 size={15} className="animate-spin" /> A carregar…
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-12 text-gray-600">
          <Music size={36} className="mx-auto mb-3 opacity-40" />
          <p className="text-sm">Ainda não tens playlists. Cria uma acima para começar.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {items.map(p => (
            <button key={p.id} onClick={() => openPlaylist(p)}
              className="text-left bg-[#161616] hover:bg-[#1c1c1c] border border-[#222] rounded-2xl p-4 transition-colors group">
              <div className="flex items-start justify-between gap-2 mb-1">
                <h4 className="font-semibold text-white leading-snug flex items-center gap-1.5 min-w-0">
                  {p.is_favorites && <Heart size={14} className="text-pink-400 fill-pink-400 shrink-0" />}
                  <span className="truncate">{p.name}</span>
                </h4>
                <span onClick={e => { e.stopPropagation(); removePlaylist(p.id); }}
                  className="p-1 text-gray-700 hover:text-red-400 opacity-0 group-hover:opacity-100 shrink-0 cursor-pointer">
                  <Trash2 size={14} />
                </span>
              </div>
              {p.vibe && <p className="text-xs text-gray-500 line-clamp-1 mb-3">{p.vibe}</p>}
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#1DB954]/15 text-[#1DB954]">{p.track_count} faixas</span>
                {p.analyzed_at && <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/15 text-blue-300">analisada</span>}
              </div>
            </button>
          ))}
        </div>
      )}

      {/* modal de playlist sugerida (grupo de género) */}
      {groupModal && (() => {
        const sugs = groupSugs[groupModal.name] || [];
        const acc = sugs.filter(s => s.accepted).length;
        return (
          <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={() => setGroupModal(null)}>
            <div className="bg-[#161616] border border-[#222] rounded-2xl w-full max-w-lg max-h-[85vh] flex flex-col" onClick={e => e.stopPropagation()}>
              <div className="flex items-start justify-between gap-3 p-4 border-b border-[#222]">
                <div className="min-w-0">
                  <h3 className="text-lg font-bold text-white truncate flex items-center gap-2">
                    <Music size={18} style={{ color: SPOTIFY }} /> {groupModal.playlist_name || groupModal.name}
                  </h3>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {groupModal.name} · {groupModal.tracks.length} músicas{acc > 0 && <span className="text-[#1DB954]"> + {acc} a juntar</span>}
                  </p>
                  {groupModal.mood && <p className="text-xs text-gray-500 mt-0.5">{groupModal.mood}</p>}
                </div>
                <button onClick={() => setGroupModal(null)} className="p-1.5 text-gray-500 hover:text-white shrink-0"><X size={18} /></button>
              </div>

              <div className="flex-1 overflow-y-auto p-4 space-y-4">
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1.5">As tuas músicas ({groupModal.tracks.length})</p>
                  <ul className="space-y-1">
                    {groupModal.tracks.map((t, j) => (
                      <li key={j} className="text-xs text-gray-300 flex items-center justify-between gap-2">
                        <span className="truncate">{t.title}{t.artist && <span className="text-gray-500"> — {t.artist}</span>}</span>
                        {t.from && <span className="text-[10px] text-gray-600 shrink-0 truncate max-w-[45%]" title={t.from}>{t.from}</span>}
                      </li>
                    ))}
                  </ul>
                </div>

                {sugs.length > 0 && (
                  <div className="border-t border-[#222] pt-3">
                    <button onClick={() => setShowRecs(v => !v)}
                      className="flex items-center gap-1.5 text-xs font-semibold text-[#1DB954] mb-2">
                      <Sparkles size={13} /> Músicas novas que recomendo ({acc}/{sugs.length})
                      {showRecs ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </button>
                    {showRecs && (
                      <ul className="space-y-1.5">
                        {sugs.map(s => (
                          <li key={s.id} className="flex items-center justify-between gap-2 bg-[#0f0f0f] border border-[#222] rounded-lg px-2.5 py-1.5">
                            <div className="min-w-0">
                              <p className="text-xs text-gray-200 truncate">{s.title}{s.artist && <span className="text-gray-500"> — {s.artist}</span>}</p>
                              {s.reason && <p className="text-[10px] text-gray-600 truncate">{s.reason}</p>}
                            </div>
                            <button onClick={() => toggleGroupSuggestion(groupModal.name, s.id)}
                              className={`shrink-0 flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border font-medium transition ${s.accepted ? 'bg-[#1DB954] border-[#1DB954] text-black' : 'border-[#2a2a2a] text-gray-300 hover:text-white'}`}>
                              {s.accepted ? <><Check size={11} /> Junta</> : <><Plus size={11} /> Juntar</>}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>

              <div className="p-4 border-t border-[#222]">
                <button onClick={() => copyGroup(groupModal.name, groupModal.tracks)}
                  className={`w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition ${copiedGroup === groupModal.name ? 'bg-[#1DB954] text-black' : 'bg-[#1DB954] text-black hover:brightness-110'}`}>
                  {copiedGroup === groupModal.name ? <Check size={15} /> : <Copy size={15} />}
                  {copiedGroup === groupModal.name ? 'Copiado!' : `Copiar playlist (${groupModal.tracks.length + acc})`}
                </button>
                <p className="text-[10px] text-gray-600 text-center mt-2">
                  Cola no <a href="https://www.tunemymusic.com/transfer" target="_blank" rel="noreferrer" className="text-gray-500 hover:text-[#1DB954]">TuneMyMusic</a> ou <a href="https://spotlistr.com/search/textbox" target="_blank" rel="noreferrer" className="text-gray-500 hover:text-[#1DB954]">Spotlistr</a> (login grátis) para criar no Spotify
                </p>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
