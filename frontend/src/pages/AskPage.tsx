// Perguntar em português sobre os próprios dados. A IA escreve o SQL, a app
// executa-o só de leitura e mostra a resposta + a tabela.
//
// A conversa continua: cada pergunta leva as anteriores (com o SQL delas), o que
// permite "e no mês passado?" sem repetir o assunto. "Nova conversa" corta o fio.
import { useEffect, useRef, useState } from 'react';
import { Sparkles, Loader2, Send, Code2, ChevronDown, History, Pin, MessageSquarePlus } from 'lucide-react';
import { askApi, AskResult } from '../api';

const HISTORICO_KEY = 'askHistorico';

export default function AskPage() {
  const [pergunta, setPergunta] = useState('');
  const [conversa, setConversa] = useState<AskResult[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  const [aPensar, setAPensar] = useState(false);
  const [exemplos, setExemplos] = useState<string[]>([]);
  const [historico, setHistorico] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem(HISTORICO_KEY) || '[]'); } catch { return []; }
  });
  const input = useRef<HTMLInputElement>(null);
  const fim = useRef<HTMLDivElement>(null);

  useEffect(() => { askApi.examples().then(r => setExemplos(r.examples)).catch(() => {}); }, []);
  // No telemóvel não se rouba o foco: abrir o teclado à entrada ampliava a
  // página inteira, e o zoom ficava depois nas outras secções.
  useEffect(() => {
    if (window.matchMedia('(min-width: 640px)').matches) input.current?.focus();
  }, []);
  useEffect(() => {
    if (conversa.length > 1) fim.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [conversa.length]);

  const perguntar = async (texto?: string) => {
    const q = (texto ?? pergunta).trim();
    if (q.length < 4 || aPensar) return;
    setAPensar(true);
    setErro(null);
    try {
      const r = await askApi.ask(q, conversa.map(c => ({ question: c.question, sql: c.sql })));
      setConversa(c => [...c, r]);
      setPergunta('');
      const novo = [q, ...historico.filter(h => h !== q)].slice(0, 8);
      setHistorico(novo);
      try { localStorage.setItem(HISTORICO_KEY, JSON.stringify(novo)); } catch { /* ignora */ }
    } catch (e: any) {
      setErro(e?.message || 'Não consegui responder a isso');
    } finally {
      setAPensar(false);
      input.current?.focus();
    }
  };

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center gap-3 mb-2">
        <Sparkles size={26} className="text-purple-400" />
        <h2 className="text-2xl sm:text-3xl font-bold">Perguntar</h2>
        {conversa.length > 0 && (
          <button
            onClick={() => { setConversa([]); setErro(null); input.current?.focus(); }}
            title="Esquecer o assunto e começar do zero"
            className="ml-auto flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium bg-white/5 text-gray-400 hover:text-white hover:bg-white/10"
          >
            <MessageSquarePlus size={12} /> nova conversa
          </button>
        )}
      </div>
      <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 mb-6">
        <div className="flex items-center gap-2">
          <input
            ref={input}
            value={pergunta}
            onChange={e => setPergunta(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && perguntar()}
            placeholder={conversa.length > 0 ? 'e no mês passado?' : 'quanto gastei em comida em maio?'}
            className="flex-1 bg-[#1a1a1a] border border-[#222] rounded-xl px-4 py-2.5 text-base sm:text-sm focus:outline-none focus:border-purple-500/50"
          />
          <button
            onClick={() => perguntar()}
            disabled={aPensar || pergunta.trim().length < 4}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-purple-600 hover:bg-purple-500 disabled:opacity-40 text-white text-sm font-medium"
          >
            {aPensar ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
            {aPensar ? 'a pensar…' : 'perguntar'}
          </button>
        </div>

        {conversa.length === 0 && !aPensar && exemplos.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {exemplos.map(ex => (
              <button key={ex} onClick={() => perguntar(ex)}
                className="text-[11px] px-2.5 py-1 rounded-lg bg-[#1a1a1a] text-gray-400 hover:text-gray-200 hover:bg-white/5">
                {ex}
              </button>
            ))}
          </div>
        )}

        {historico.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <History size={12} className="text-gray-600" />
            {historico.map(h => (
              <button key={h} onClick={() => perguntar(h)}
                className="text-[11px] px-2 py-1 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-white/5 max-w-[220px] truncate">
                {h}
              </button>
            ))}
          </div>
        )}
      </div>

      {erro && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3 mb-6 text-sm text-red-400">{erro}</div>
      )}

      <div className="space-y-4">
        {conversa.map((r, i) => (
          <Resposta key={i} r={r} primeira={i === 0} onErro={setErro} />
        ))}
        {aPensar && (
          <div className="flex items-center gap-2 text-sm text-gray-500 px-1">
            <Loader2 size={14} className="animate-spin" /> a pensar…
          </div>
        )}
        <div ref={fim} />
      </div>
    </div>
  );
}

function Resposta({ r, primeira, onErro }: {
  r: AskResult; primeira: boolean; onErro: (e: string) => void;
}) {
  const [verSql, setVerSql] = useState(false);
  const [aFixar, setAFixar] = useState(false);
  const [fixado, setFixado] = useState(false);

  const fixar = async () => {
    setAFixar(true);
    try {
      await askApi.pin({ question: r.question, title: r.title, sql: r.sql, chart: r.chart });
      setFixado(true);
    } catch (e: any) {
      onErro(e?.message || 'Não consegui fixar');
    } finally { setAFixar(false); }
  };

  const numerico = (v: any) => typeof v === 'number';
  const maxValor = r.rows.length ? Math.max(...r.rows.map(l => Number(l[l.length - 1]) || 0)) : 0;

  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
      {!primeira && (
        <p className="px-4 pt-3 text-[11px] text-gray-600 italic truncate">{r.question}</p>
      )}
      <div className="p-4 border-b border-[#222] flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-gray-500 mb-1">{r.title}</p>
          {r.answer
            ? <p className="text-base font-medium leading-relaxed">{r.answer}</p>
            : <p className="text-sm text-gray-400">{r.row_count} resultado{r.row_count === 1 ? '' : 's'}</p>}
        </div>
        <button
          onClick={fixar}
          disabled={aFixar || fixado}
          title="Fixar no Dashboard — o número passa a actualizar-se sozinho"
          className={`shrink-0 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium ${
            fixado ? 'bg-purple-500/15 text-purple-300' : 'bg-white/5 text-gray-400 hover:text-white hover:bg-white/10'
          } disabled:opacity-60`}
        >
          <Pin size={12} />
          {fixado ? 'no Dashboard' : aFixar ? 'a fixar…' : 'fixar'}
        </button>
      </div>

      {r.rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#222] text-left">
                {r.columns.map(c => (
                  <th key={c} className="px-4 py-2 text-[11px] font-semibold uppercase tracking-wider text-gray-500">{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {r.rows.slice(0, 60).map((linha, i) => (
                <tr key={i} className="border-b border-[#1a1a1a] last:border-0 hover:bg-white/5">
                  {linha.map((v, j) => (
                    <td key={j} className={`px-4 py-2 ${numerico(v) ? 'tabular-nums text-right' : ''}`}>
                      {r.chart === 'bar' && j === linha.length - 1 && numerico(v) && maxValor > 0 ? (
                        <span className="flex items-center gap-2 justify-end">
                          <span className="h-1.5 rounded-full bg-purple-400/60"
                            style={{ width: `${Math.max(4, (Number(v) / maxValor) * 90)}px` }} />
                          {v}
                        </span>
                      ) : v === null ? <span className="text-gray-600">—</span> : String(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {r.rows.length > 60 && (
            <p className="px-4 py-2 text-[11px] text-gray-600">
              a mostrar 60 de {r.rows.length} linhas
            </p>
          )}
        </div>
      )}

      <div className="border-t border-[#222]">
        <button onClick={() => setVerSql(v => !v)}
          className="w-full flex items-center gap-2 px-4 py-2 text-[11px] text-gray-500 hover:text-gray-300">
          <Code2 size={12} /> ver a consulta
          <ChevronDown size={12} className={verSql ? 'rotate-180' : ''} />
        </button>
        {verSql && (
          <pre className="px-4 pb-3 text-[11px] text-gray-500 whitespace-pre-wrap break-words">{r.sql}</pre>
        )}
      </div>
    </div>
  );
}
