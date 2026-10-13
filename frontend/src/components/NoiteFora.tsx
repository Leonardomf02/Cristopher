import { useEffect, useRef, useState } from 'react';
import { format, parseISO } from 'date-fns';
import { pt } from 'date-fns/locale';
import { nightsApi, type DrinkLevel, type NightOutDay } from '../api';

export const NIVEIS_DE_BEBIDA: Record<DrinkLevel, string> = { 1: 'pouco', 2: 'médio', 3: 'muito' };

const COR_DO_NIVEL: Record<DrinkLevel, string> = {
  1: 'bg-amber-500/10 border-amber-500/30 text-amber-200',
  2: 'bg-amber-500/20 border-amber-500/50 text-amber-200',
  3: 'bg-orange-500/25 border-orange-500/60 text-orange-200',
};

// Saí / bebi de uma noite. `data` é o dia em que a noite começou. Sem nada
// marcado, a noite foi em casa — que é o costume, por isso não se pergunta.
// Um gasto na Noite dessa noite acende o "Saí" como pista para confirmar.
// "Bebi" abre ali mesmo os três níveis, em vez de um menu por cima: os dois
// cartões onde isto vive cortam o que lhes sai das bordas.
export default function NoiteFora({ data, aoMudar }: { data: string; aoMudar?: (n: NightOutDay) => void }) {
  const [noite, setNoite] = useState<NightOutDay | null>(null);
  const [aGravar, setAGravar] = useState(false);
  const [aEscolher, setAEscolher] = useState(false);
  const caixa = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let vivo = true;
    setNoite(null);
    setAEscolher(false);
    nightsApi.get(data).then(n => vivo && setNoite(n)).catch(() => {});
    return () => { vivo = false; };
  }, [data]);

  useEffect(() => {
    if (!aEscolher) return;
    const fora = (e: MouseEvent) => {
      if (caixa.current && !caixa.current.contains(e.target as Node)) setAEscolher(false);
    };
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setAEscolher(false);
    document.addEventListener('mousedown', fora);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', fora);
      document.removeEventListener('keydown', esc);
    };
  }, [aEscolher]);

  if (!noite) return null;

  const grava = async (pedido: Promise<NightOutDay>) => {
    setAGravar(true);
    try {
      const n = await pedido;
      setNoite(n);
      aoMudar?.(n);
      setAEscolher(false);
    } catch { /* fica como estava */ } finally { setAGravar(false); }
  };

  const pista = !noite.went_out && noite.evidence.length > 0;
  const quando = format(parseISO(data), "EEEE 'à noite'", { locale: pt });
  const gastos = noite.evidence
    .map(g => `${g.description} €${g.amount.toFixed(2)}${g.time ? ` às ${g.time}` : ''}`).join('\n');

  return (
    <div ref={caixa} className="flex items-center gap-1 shrink-0" onClick={e => e.stopPropagation()}>
      <button
        disabled={aGravar}
        onClick={() => grava(noite.went_out ? nightsApi.clear(data) : nightsApi.set(data, false))}
        title={noite.went_out
          ? `Saíste ${quando}. Carregar outra vez desmarca.`
          : pista ? `Parece que saíste ${quando}:\n${gastos}\nCarrega para confirmar.`
          : `Saíste ${quando}?`}
        className={`px-2 py-0.5 rounded-lg text-[11px] font-medium border transition-colors disabled:opacity-50 ${
          noite.went_out ? 'bg-indigo-500/20 border-indigo-500/40 text-indigo-200'
          : pista ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300 animate-pulse'
          : 'bg-white/5 border-transparent text-gray-500 hover:text-gray-300'}`}>
        🌙 Saí
      </button>
      {noite.went_out && aEscolher && (
        <div className="flex items-center gap-0.5 rounded-lg bg-white/5 p-0.5">
          <span className="px-1 text-[11px]">🍺</span>
          {([1, 2, 3] as DrinkLevel[]).map(nivel => (
            <button key={nivel} disabled={aGravar}
              onClick={() => grava(nightsApi.set(data, true, nivel))}
              className={`px-1.5 py-0.5 rounded-md text-[11px] font-medium border transition-colors disabled:opacity-50 ${
                noite.drink_level === nivel ? COR_DO_NIVEL[nivel]
                : 'border-transparent text-gray-400 hover:text-gray-200 hover:bg-white/5'}`}>
              {NIVEIS_DE_BEBIDA[nivel]}
            </button>
          ))}
          <button disabled={aGravar}
            onClick={() => noite.drank ? grava(nightsApi.set(data, false)) : setAEscolher(false)}
            title={noite.drank ? 'Afinal não bebeste' : 'Fechar'}
            className="px-1.5 py-0.5 rounded-md text-[11px] text-gray-500 hover:text-gray-300 disabled:opacity-50">
            {noite.drank ? 'não' : '✕'}
          </button>
        </div>
      )}
      {noite.went_out && !aEscolher && (
        <button
          disabled={aGravar}
          onClick={() => setAEscolher(true)}
          title={noite.drank
            ? `Bebeste${noite.drink_level ? ` ${NIVEIS_DE_BEBIDA[noite.drink_level]}` : ''}. Carregar muda o nível.`
            : 'Bebeste?'}
          className={`px-2 py-0.5 rounded-lg text-[11px] font-medium border transition-colors disabled:opacity-50 ${
            noite.drank ? COR_DO_NIVEL[noite.drink_level ?? 2]
            : 'bg-white/5 border-transparent text-gray-500 hover:text-gray-300'}`}>
          🍺 {noite.drank && noite.drink_level ? NIVEIS_DE_BEBIDA[noite.drink_level] : 'Bebi'}
        </button>
      )}
    </div>
  );
}
