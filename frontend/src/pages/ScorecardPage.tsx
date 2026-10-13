// O que a app acertou. Cada parte que faz previsões é avaliada aqui — incluindo
// as que se estão a portar mal.
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Target, ChevronRight } from 'lucide-react';
import { scorecardApi, Scorecard } from '../api';

export default function ScorecardPage() {
  const navigate = useNavigate();
  const [d, setD] = useState<Scorecard | null>(null);
  const [dias, setDias] = useState(90);

  useEffect(() => { setD(null); scorecardApi.get(dias).then(setD).catch(() => setD(null)); }, [dias]);

  const cor = (v: number | undefined) =>
    v === undefined ? 'text-gray-500'
      : v >= 60 ? 'text-emerald-400'
      : v >= 45 ? 'text-amber-400'
      : 'text-red-400';

  return (
    <div className="max-w-3xl mx-auto pb-10">
      <div className="flex items-center gap-3 mb-2">
        <Target size={26} className="text-emerald-400" />
        <h2 className="text-2xl sm:text-3xl font-bold">O que a app acertou</h2>
      </div>
      <p className="text-sm text-gray-500 mb-5">
        Cada parte desta app que faz previsões avaliada com o que aconteceu depois.
        Onde não há amostra suficiente, não se inventa número.
      </p>

      <div className="flex gap-1 mb-4">
        {[30, 90, 365].map(n => (
          <button key={n} onClick={() => setDias(n)}
            className={`text-[11px] px-2.5 py-1 rounded-lg ${dias === n ? 'bg-white/10 text-gray-200' : 'text-gray-500 hover:text-gray-300'}`}>
            {n === 365 ? '1 ano' : `${n} dias`}
          </button>
        ))}
      </div>

      {!d ? (
        <p className="text-sm text-gray-600">a calcular…</p>
      ) : (
        <>
          <p className="text-[11px] text-gray-600 mb-3">{d.measured} de {d.total} partes com amostra para julgar</p>
          <div className="space-y-3">
            {d.cards.map(c => (
              <div key={c.area} className="bg-[#161616] rounded-2xl border border-[#222] p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium flex items-center gap-2">
                      <span>{c.icon}</span> {c.title}
                    </p>
                    <p className="text-[11px] text-gray-500 mt-0.5">
                      {c.enough ? `${c.detail} · ${c.n} casos` : c.note}
                    </p>
                  </div>
                  <div className="text-right shrink-0">
                    {c.enough ? (
                      <>
                        <p className={`text-2xl font-bold ${cor(c.hit_rate)}`}>{c.hit_rate}%</p>
                        <p className="text-[10px] text-gray-600">{c.verdict}</p>
                      </>
                    ) : (
                      <p className="text-sm text-gray-600">sem dados</p>
                    )}
                  </div>
                </div>

                {c.enough && c.breakdown && c.breakdown.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-[#222] space-y-1">
                    {c.breakdown.map(b => (
                      <div key={b.label} className="flex items-center gap-2 text-[11px]">
                        <span className="flex-1 text-gray-400">{b.label}</span>
                        <span className="text-gray-600">{b.n} casos</span>
                        <span className={`w-12 text-right ${cor(b.hit_rate)}`}>{b.hit_rate}%</span>
                        {b.promised !== undefined && (
                          <span className="w-24 text-right text-gray-600">prometia {b.promised}%</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {c.url && (
                  <button onClick={() => navigate(c.url!)}
                    className="mt-2 text-[11px] text-gray-500 hover:text-gray-300 flex items-center gap-1">
                    ver a secção <ChevronRight size={11} />
                  </button>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
