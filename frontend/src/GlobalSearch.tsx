// Paleta ⌘K / Ctrl+K: acções (ir para, criar, correr, apontar uma frase) e
// pesquisa em notas, notas de projecto, TODOs, reminders e eventos.
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, X, CornerDownLeft, Loader2 } from 'lucide-react';
import { searchApi, SearchHit } from './api';
import { COMANDOS, Command, comandoDeCaptura, filtra } from './commands';

export default function GlobalSearch() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [cursor, setCursor] = useState(0);
  const [aCorrer, setACorrer] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen(o => !o);
      }
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 30);
    else { setQ(''); setHits([]); setCursor(0); setAviso(null); }
  }, [open]);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    const term = q.trim();
    if (term.length < 2) { setHits([]); setLoading(false); return; }
    setLoading(true);
    timer.current = setTimeout(() => {
      searchApi.query(term, 6)
        .then(r => setHits(r.results))
        .catch(() => setHits([]))
        .finally(() => setLoading(false));
    }, 220);
  }, [q]);

  const captura = comandoDeCaptura(q);
  const comandos: Command[] = [...(captura ? [captura] : []), ...filtra(COMANDOS, q)];
  const total = comandos.length + hits.length;

  useEffect(() => { setCursor(0); }, [q]);

  const correr = async (cmd: Command) => {
    setACorrer(cmd.id);
    setAviso(null);
    try {
      const msg = await cmd.run({ navigate, fechar: () => setOpen(false) });
      if (msg) setAviso(msg);
    } catch (e: any) {
      setAviso(e?.message || 'não consegui fazer isso');
    } finally {
      setACorrer(null);
    }
  };

  const escolher = (i: number) => {
    if (i < comandos.length) correr(comandos[i]);
    else {
      const hit = hits[i - comandos.length];
      if (hit) { setOpen(false); navigate(hit.url); }
    }
  };

  const onInputKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setCursor(c => Math.min(c + 1, total - 1)); }
    if (e.key === 'ArrowUp') { e.preventDefault(); setCursor(c => Math.max(c - 1, 0)); }
    if (e.key === 'Enter' && total > 0) { e.preventDefault(); escolher(cursor); }
  };

  if (!open) return null;

  const Linha = ({ i, icon, titulo, sub, etiqueta }: {
    i: number; icon: string; titulo: string; sub?: string; etiqueta?: string;
  }) => (
    <button
      onClick={() => escolher(i)}
      onMouseEnter={() => setCursor(i)}
      className={`w-full flex items-start gap-3 px-4 py-2.5 text-left ${i === cursor ? 'bg-white/10' : 'hover:bg-white/5'}`}
    >
      <span className="text-base shrink-0 mt-0.5">{icon}</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm truncate">{titulo}</p>
        {sub && <p className="text-[11px] text-gray-500 truncate">{sub}</p>}
      </div>
      {aCorrer === comandos[i]?.id
        ? <Loader2 size={12} className="animate-spin text-gray-400 shrink-0 mt-1" />
        : etiqueta && <span className="text-[10px] text-gray-600 shrink-0 mt-1">{etiqueta}</span>}
    </button>
  );

  return (
    <div className="fixed inset-0 z-[80] bg-black/60 flex items-start justify-center p-4 pt-[12vh]" onClick={() => setOpen(false)}>
      <div
        className="w-[640px] max-w-[92vw] bg-[#161616] border border-[#2a2a2a] rounded-2xl shadow-xl overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[#222]">
          <Search size={16} className="text-gray-500 shrink-0" />
          <input
            ref={inputRef}
            value={q}
            onChange={e => setQ(e.target.value)}
            onKeyDown={onInputKey}
            placeholder="Procurar ou escrever uma acção (ex: gastei 12 no lidl)..."
            className="flex-1 bg-transparent text-sm focus:outline-none placeholder-gray-600"
          />
          <button onClick={() => setOpen(false)} className="text-gray-500 hover:text-white shrink-0">
            <X size={16} />
          </button>
        </div>

        {aviso && (
          <div className="px-4 py-2 bg-green-500/10 border-b border-green-500/20 text-[11px] text-green-300">
            {aviso}
          </div>
        )}

        <div className="max-h-[50vh] overflow-y-auto">
          {comandos.length > 0 && (
            <>
              <p className="px-4 pt-3 pb-1 text-[10px] font-bold uppercase tracking-wider text-gray-600">Acções</p>
              {comandos.map((c, i) => (
                <Linha key={c.id} i={i} icon={c.icon} titulo={c.label} sub={c.hint} etiqueta="acção" />
              ))}
            </>
          )}

          {q.trim().length >= 2 && (
            <>
              <p className="px-4 pt-3 pb-1 text-[10px] font-bold uppercase tracking-wider text-gray-600">Resultados</p>
              {loading && hits.length === 0 ? (
                <p className="px-4 py-4 text-xs text-gray-600 text-center">A procurar...</p>
              ) : hits.length === 0 ? (
                <p className="px-4 py-4 text-xs text-gray-600 text-center">Nada encontrado.</p>
              ) : (
                hits.map((h, i) => (
                  <Linha
                    key={`${h.type}-${i}`}
                    i={comandos.length + i}
                    icon={h.icon}
                    titulo={h.title}
                    sub={h.subtitle}
                    etiqueta={h.type}
                  />
                ))
              )}
            </>
          )}

          {q.trim().length < 2 && comandos.length === 0 && (
            <p className="px-4 py-6 text-xs text-gray-600 text-center">Escreve para procurar ou para uma acção.</p>
          )}
        </div>

        <div className="flex items-center gap-3 px-4 py-2 border-t border-[#222] text-[10px] text-gray-600">
          <span className="flex items-center gap-1"><CornerDownLeft size={11} /> abrir</span>
          <span>↑↓ navegar</span>
          <span>esc fechar</span>
          <span className="ml-auto">⌘K</span>
        </div>
      </div>
    </div>
  );
}
