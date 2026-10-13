import { useState, useEffect } from 'react';
import { lolApi } from '../api';

// Objectivo dos 3 jogos por dia: cumprimento (hábito) e se muda o resultado.
// São perguntas diferentes — cumprir 90% dos dias não quer dizer que jogar 3
// seja melhor do que jogar 5.
export default function TresJogosPorDia() {
  const [d, setD] = useState<Awaited<ReturnType<typeof lolApi.dailyGoal>> | null>(null);

  useEffect(() => { lolApi.dailyGoal(180).then(setD).catch(() => setD(null)); }, []);
  if (!d || !d.enough) return null;

  const maxDias = Math.max(...d.by_count.map(b => b.days), 1);

  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 sm:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 mb-3">
        <h3 className="text-sm font-medium text-gray-300">🎮 {d.target} jogos por dia</h3>
        <span className="text-[11px] text-gray-500">
          {d.days_played} dias com jogos · últimos {d.days} dias
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        <div>
          <p className="text-2xl font-bold text-emerald-400">{d.goal_rate_pct}%</p>
          <p className="text-[11px] text-gray-500">dias com {d.target} ou mais ({d.days_goal_met})</p>
        </div>
        <div>
          <p className="text-2xl font-bold">{d.exact_rate_pct}%</p>
          <p className="text-[11px] text-gray-500">exactamente {d.target} ({d.days_on_target} dias)</p>
        </div>
        <div>
          <p className="text-2xl font-bold text-amber-400">{d.days_under}</p>
          <p className="text-[11px] text-gray-500">dias a menos de {d.target}</p>
        </div>
        <div>
          <p className="text-2xl font-bold text-gray-300">{d.streak}</p>
          <p className="text-[11px] text-gray-500">dias seguidos a cumprir</p>
        </div>
      </div>

      <div className="rounded-xl bg-[#1a1a1a] p-3 mb-3">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className="text-xs text-gray-400">
            com {d.target}: <span className="text-base font-bold text-gray-100">{d.on_target.pct}%</span>
            <span className="text-gray-600"> ({d.on_target.wins}/{d.on_target.games})</span>
          </span>
          <span className="text-xs text-gray-400">
            com outro número: <span className="text-base font-bold text-gray-100">{d.off_target.pct}%</span>
            <span className="text-gray-600"> ({d.off_target.wins}/{d.off_target.games})</span>
          </span>
          {d.diff_pp !== null && (
            <span className={`text-xs ${d.proven ? (d.diff_pp > 0 ? 'text-emerald-400' : 'text-red-400') : 'text-gray-500'}`}>
              {d.diff_pp > 0 ? '+' : ''}{d.diff_pp} pontos
            </span>
          )}
        </div>
        <p className="text-[11px] text-gray-500 mt-1">
          {d.verdict}{d.z !== null && ` · z=${d.z}`}
        </p>
      </div>

      {/* O dia inteiro, não os jogos soltos: acabar 2-1 é um dia bom. */}
      <div className="rounded-xl bg-[#1a1a1a] p-3 mb-3">
        <p className="text-[11px] text-gray-500 mb-1.5">Dias que acabam a ganhar mais do que perdeu</p>
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className="text-xs text-gray-400">
            com {d.target}: <span className="text-base font-bold text-gray-100">{d.on_target.positive_pct}%</span>
            <span className="text-gray-600"> ({d.on_target.positive_days} bons · {d.on_target.negative_days} maus)</span>
          </span>
          <span className="text-xs text-gray-400">
            com outro número: <span className="text-base font-bold text-gray-100">{d.off_target.positive_pct}%</span>
            <span className="text-gray-600">
              {' '}({d.off_target.positive_days} bons · {d.off_target.negative_days} maus
              {d.off_target.tied_days > 0 && ` · ${d.off_target.tied_days} empatados`})
            </span>
          </span>
          {d.days_diff_pp !== null && (
            <span className={`text-xs ${d.days_proven ? (d.days_diff_pp > 0 ? 'text-emerald-400' : 'text-red-400') : 'text-gray-500'}`}>
              {d.days_diff_pp > 0 ? '+' : ''}{d.days_diff_pp} pontos
              {!d.days_proven && ' · sem prova'}
              {d.days_z !== null && ` · z=${d.days_z}`}
            </span>
          )}
        </div>
      </div>

      {/* Cada linha é "nos dias em que joguei N jogos". Sem cabeçalho, as duas
          últimas colunas não se percebiam — e faltavam os dias empatados, o que
          fazia as contas não bater (3 dias, 1 bom e 1 mau: o outro foi 1-1). */}
      <div className="flex items-center gap-2 text-[10px] text-gray-600 mb-1">
        <span className="w-14 shrink-0">num dia de</span>
        <span className="flex-1">quantos dias</span>
        <span className="w-12 shrink-0 text-right">dias</span>
        <span className="w-24 shrink-0 text-right">jogos ganhos</span>
        <span className="w-28 shrink-0 text-right">como acabou o dia</span>
      </div>
      <div className="space-y-1">
        {d.by_count.map(b => (
          <div key={b.games_that_day} className="flex items-center gap-2 text-[11px]">
            <span className={`w-14 shrink-0 ${b.games_that_day === d.target ? 'text-gray-200 font-medium' : 'text-gray-500'}`}>
              {b.games_that_day} {b.games_that_day === 1 ? 'jogo' : 'jogos'}
            </span>
            <div className="flex-1 h-3 bg-[#1a1a1a] rounded overflow-hidden">
              <div className={b.games_that_day === d.target ? 'h-full bg-blue-500/60' : 'h-full bg-gray-600/50'}
                style={{ width: `${(b.days / maxDias) * 100}%` }} />
            </div>
            <span className="w-12 shrink-0 text-right text-gray-500">{b.days}d</span>
            <span className={`w-24 shrink-0 text-right ${b.games >= 20 ? 'text-gray-300' : 'text-gray-600'}`}>
              {b.pct}% <span className="text-gray-600">({b.wins}/{b.games})</span>
            </span>
            <span className="w-28 shrink-0 text-right text-gray-600">
              <span className="text-emerald-500/80">{b.positive_days} {b.positive_days === 1 ? 'bom' : 'bons'}</span>
              {' · '}
              <span className="text-red-500/70">{b.negative_days} {b.negative_days === 1 ? 'mau' : 'maus'}</span>
              {b.tied_days > 0 && (
                <span className="text-gray-600">{' · '}{b.tied_days} {b.tied_days === 1 ? 'igual' : 'iguais'}</span>
              )}
            </span>
          </div>
        ))}
      </div>
      <p className="text-[11px] text-gray-600 mt-2">
        "Dia bom" = acabaste a ganhar mais do que perdeste; "iguais" são os dias que fecham
        empatados (2-2, 3-3), que só acontecem com um número par de jogos. As linhas com
        poucos jogos estão a cinzento: com 6 jogos não se conclui nada.
      </p>
    </div>
  );
}
