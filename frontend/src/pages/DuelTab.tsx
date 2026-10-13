import { useState, useEffect } from 'react';
import {
  Loader2, Swords, Clock, Layers, GraduationCap, TrendingUp, TrendingDown,
  Minus, AlertTriangle, Map, Ban,
} from 'lucide-react';
import { lolApi, type LolDuel, type LolWorthLearning, type LolDuelMetric, type LolBans } from '../api';

const DIAS = [
  { label: '90d', value: 90 },
  { label: '180d', value: 180 },
  { label: '1 ano', value: 365 },
];

function fmt(v: number | null | undefined, casas = 2) {
  if (v == null) return '—';
  return Number.isInteger(v) ? String(v) : v.toFixed(casas);
}

function sinal(v: number, casas = 2) {
  return `${v > 0 ? '+' : ''}${fmt(v, casas)}`;
}

function Painel({ icon, titulo, nota, children }: {
  icon: React.ReactNode; titulo: string; nota?: string; children: React.ReactNode;
}) {
  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] flex flex-col">
      <div className="p-4 border-b border-[#222] shrink-0">
        <div className="flex items-center gap-2 text-white font-semibold">{icon}{titulo}</div>
        {nota && <p className="text-xs text-gray-500 mt-1">{nota}</p>}
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

/* Uma métrica: ele contra o jungler adversário do mesmo jogo. */
function Linha({ m }: { m: LolDuelMetric }) {
  const cor = !m.proven ? 'text-gray-500'
    : m.in_my_favour ? 'text-green-400' : 'text-red-400';
  const Icone = !m.proven ? Minus : m.in_my_favour ? TrendingUp : TrendingDown;
  const soDiferenca = m.theirs == null;
  return (
    <div className="flex items-center gap-3 py-2 border-b border-[#1e1e1e] last:border-0">
      <Icone className={`w-4 h-4 shrink-0 ${cor}`} />
      <div className="min-w-0 flex-1">
        <div className="text-sm text-gray-200 truncate">{m.label}</div>
        <div className="text-[11px] text-gray-500">
          {soDiferenca
            ? `em ${m.games} jogos`
            : `tu ${fmt(m.mine)} · adversário ${fmt(m.theirs)}`}
          {m.win_pct != null && <> · ganhas {m.win_pct}%{m.tie_pct > 5 && ` (empatas ${m.tie_pct}%)`}</>}
        </div>
      </div>
      <div className="text-right shrink-0">
        {/* A mediana da diferença pode ser zero e o teste passar à mesma: nos
            abates em laners cedo há muitos jogos empatados, e dos que se
            decidem ele ganha dois terços. Aí o número que diz alguma coisa é a
            percentagem, não o zero. */}
        <div className={`text-sm font-semibold tabular-nums ${cor}`}>
          {m.diff !== 0 || m.win_pct == null ? sinal(m.diff) : `${m.win_pct}%`}
        </div>
        <div className="text-[10px] text-gray-600 tabular-nums">
          {m.proven ? (m.p < 0.0001 ? 'p<0,0001' : `p=${m.p.toString().replace('.', ',')}`) : 'sem prova'}
        </div>
      </div>
    </div>
  );
}

export default function DuelTab() {
  const [dias, setDias] = useState(365);
  const [duelo, setDuelo] = useState<LolDuel | null>(null);
  const [aprender, setAprender] = useState<LolWorthLearning | null>(null);
  const [bans, setBans] = useState<LolBans | null>(null);
  const [aCarregar, setACarregar] = useState(true);

  useEffect(() => {
    let vivo = true;
    setACarregar(true);
    lolApi.duel(dias)
      .then((d) => { if (vivo) setDuelo(d); })
      .catch(() => { if (vivo) setDuelo(null); })
      .finally(() => { if (vivo) setACarregar(false); });
    return () => { vivo = false; };
  }, [dias]);

  useEffect(() => {
    let vivo = true;
    lolApi.worthLearning(180)
      .then((d) => { if (vivo) setAprender(d); })
      .catch(() => { if (vivo) setAprender(null); });
    lolApi.bans(180)
      .then((d) => { if (vivo) setBans(d); })
      .catch(() => { if (vivo) setBans(null); });
    return () => { vivo = false; };
  }, []);

  if (aCarregar && !duelo) {
    return (
      <div className="flex items-center justify-center py-20 text-gray-500">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> a medir…
      </div>
    );
  }

  if (duelo?.message) {
    return (
      <div className="bg-[#161616] rounded-2xl border border-[#222] p-6 flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-yellow-500 shrink-0 mt-0.5" />
        <div>
          <p className="text-gray-300">{duelo.message}</p>
          <p className="text-xs text-gray-500 mt-2">
            São dois pedidos por jogo à Riot; para os 500 jogos demora cerca de meia hora.
          </p>
        </div>
      </div>
    );
  }
  if (!duelo) return null;

  const cedo = duelo.metrics.filter((m) => m.moment === 'cedo');
  const jogo = duelo.metrics.filter((m) => m.moment === 'jogo');
  const jc = duelo.critical_window;
  const maiorGap = jc ? Math.max(...jc.points.map((p) => p.gap)) : null;

  return (
    <div className="flex flex-col gap-4">
      {/* Barra fina: quem é a régua, e de quantos jogos */}
      <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3 min-w-0">
          <Swords className="w-5 h-5 text-purple-400 shrink-0" />
          <div className="min-w-0">
            <div className="text-white font-semibold">Tu contra o jungler adversário</div>
            <p className="text-xs text-gray-500">
              {duelo.games} jogos, cada um comparado com o jungler do outro lado — mesmo elo,
              mesmo patch, mesma partida. {duelo.proven_count} das {duelo.metrics.length} medidas
              têm prova estatística.
            </p>
          </div>
        </div>
        <div className="flex gap-1 bg-[#111] rounded-xl p-1 shrink-0">
          {DIAS.map((d) => (
            <button key={d.value} onClick={() => setDias(d.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                dias === d.value ? 'bg-purple-600 text-white' : 'text-gray-400 hover:text-white'
              }`}>
              {d.label}
            </button>
          ))}
        </div>
      </div>

      {duelo.map_side && (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
          <div className="flex items-center gap-2 text-white font-semibold mb-1">
            <Map className="w-4 h-4 text-orange-400" />
            De que lado do mapa jogas melhor
          </div>
          <p className="text-xs text-gray-500 mb-3">
            O lado é sorteado, por isso isto é uma experiência às cegas — não há escolha
            nenhuma pelo meio. É o maior efeito que a app consegue medir em ti.
          </p>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="flex items-center gap-4">
              {(['red', 'blue'] as const).map((lado) => (
                <div key={lado} className={`flex-1 rounded-xl p-3 border ${
                  duelo.map_side!.better_side === lado
                    ? 'border-orange-500/40 bg-orange-500/5' : 'border-[#222] bg-[#111]'
                }`}>
                  <div className={`text-[11px] uppercase tracking-wider ${
                    lado === 'red' ? 'text-red-400' : 'text-blue-400'}`}>{lado}</div>
                  <div className="text-2xl font-bold text-white tabular-nums">
                    {duelo.map_side![lado].winrate}%
                  </div>
                  <div className="text-[11px] text-gray-500">{duelo.map_side![lado].games} jogos</div>
                </div>
              ))}
            </div>
            <div className="lg:col-span-2">
              <p className="text-sm text-gray-300 mb-2">
                <span className="text-orange-300 font-semibold">
                  {sinal(duelo.map_side.diff, 1)}pp
                </span>{' '}
                a favor de {duelo.map_side.better_side}
                {duelo.map_side.proven ? ' — passa o teste' : ' — ainda sem prova'}.
                {duelo.map_side.causes.length > 0 && ' O que muda:'}
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4">
                {duelo.map_side.causes.map((c) => (
                  <div key={c.metric} className="flex items-center gap-2 py-1 text-xs border-b border-[#1e1e1e]">
                    <span className="text-gray-400 flex-1 truncate">{c.label}</span>
                    <span className="text-blue-400 tabular-nums w-16 text-right">{sinal(c.blue)}</span>
                    <span className="text-red-400 tabular-nums w-16 text-right">{sinal(c.red)}</span>
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-gray-600 mt-2 leading-tight">
                Valores em diferença para o jungler adversário, de blue e de red.
                Partindo os jogos ao meio no tempo a direcção aguenta-se mas a diferença
                encolhe (+16,5pp na primeira metade, +8,4pp na segunda) — o efeito real
                é provavelmente menor do que o total mostra.
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
        <Painel
          icon={<Clock className="w-4 h-4 text-amber-400" />}
          titulo="Antes de o jogo se decidir"
          nota="Acontece nos primeiros 15 minutos, antes de se saber quem ganha. É o que dá para mudar."
        >
          {cedo.map((m) => <Linha key={m.metric} m={m} />)}
          {jc && maiorGap != null && (
            <div className="mt-4 pt-3 border-t border-[#222]">
              <div className="text-xs text-gray-400 mb-2">
                Ouro contra o jungler adversário, nos jogos que ganhaste e nos que perdeste
              </div>
              {jc.points.map((p) => (
                <div key={p.minute} className="flex items-center gap-2 py-1 text-xs">
                  <span className="text-gray-500 w-14 shrink-0">{p.minute} min</span>
                  <span className="text-green-400 tabular-nums w-16 text-right">{sinal(p.wins, 0)}</span>
                  <span className="text-gray-600">vs</span>
                  <span className="text-red-400 tabular-nums w-16 text-right">{sinal(p.losses, 0)}</span>
                  <div className="flex-1 h-1.5 bg-[#222] rounded-full overflow-hidden ml-1">
                    <div className="h-full bg-purple-500 rounded-full"
                      style={{ width: `${maiorGap > 0 ? Math.min(100, (p.gap / maiorGap) * 100) : 0}%` }} />
                  </div>
                </div>
              ))}
              {jc.splits_at && (
                <p className="text-[11px] text-gray-500 mt-2">
                  É aos <span className="text-purple-300">{jc.splits_at} minutos</span> que os
                  teus jogos ganhos deixam de se parecer com os perdidos.
                </p>
              )}
            </div>
          )}
        </Painel>

        <Painel
          icon={<Layers className="w-4 h-4 text-sky-400" />}
          titulo="Acumulado ao longo do jogo"
          nota="Sobe porque se ganha tanto quanto faz ganhar — fazer mais dragões não é conselho, é a descrição de ter ganho."
        >
          {jogo.map((m) => <Linha key={m.metric} m={m} />)}
        </Painel>

        <div className="flex flex-col gap-4">
          <Painel
            icon={<TrendingUp className="w-4 h-4 text-emerald-400" />}
            titulo="Melhor ou pior do que a média"
            nota="O teu winrate menos o do mesmo campeão no teu elo, encolhido pelo número de jogos. Nenhuma destas diferenças passa um teste — por isso não entram nas sugestões de pick."
          >
            <p className="text-[10px] text-gray-600 leading-tight mb-2 pb-2 border-b border-[#222]">
              A variação entre estes números (5,9pp) é menor do que o ruído que se
              esperaria só por acaso com estes jogos (10,6pp): a distância entre o
              primeiro e o último é indistinguível de uma moeda ao ar. Fica como
              retrato, não como conselho.
            </p>
            {duelo.edge.map((e) => (
              <div key={e.champion} className="flex items-center gap-3 py-1.5 border-b border-[#1e1e1e] last:border-0">
                <div className="min-w-0 flex-1">
                  <div className="text-sm text-gray-200 truncate">{e.champion}</div>
                  <div className="text-[11px] text-gray-500">
                    {e.winrate}% em {e.games} jogos · o elo faz {e.meta_wr}%
                  </div>
                </div>
                <div className="text-sm font-semibold tabular-nums shrink-0 text-gray-300">
                  {sinal(e.edge_shrunk, 1)}
                </div>
              </div>
            ))}
          </Painel>

        </div>
      </div>

      {aprender && aprender.champions.length > 0 && (
        <Painel
          icon={<GraduationCap className="w-4 h-4 text-fuchsia-400" />}
              titulo="Vale a pena aprender"
              nota={`Contra os ${aprender.distinct_enemies ?? '—'} junglers que apanhaste mesmo nos últimos ${aprender.days ?? 180} dias, já com o custo de pegar num campeão novo descontado. "Exposto a counters" é para quando picas primeiro e ainda não sabes quem vais ter do outro lado.`}
            >
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6">
          {aprender.champions.slice(0, 12).map((c) => (
                <div key={c.champion} className="flex items-center gap-3 py-1.5 border-b border-[#1e1e1e] last:border-0">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-gray-200 truncate">
                      {c.champion}
                      {c.already_playing && <span className="text-[10px] text-gray-600 ml-1.5">já jogas</span>}
                    </div>
                    <div className="text-[11px] text-gray-500">
                      {c.familiarity}
                      {c.learning_cost < 0 && ` · custa ${fmt(c.learning_cost, 1)}pp`}
                      {c.counter_exposure != null && (
                        <span title={c.worst_matchups?.map((w) => `${w.enemy} ${w.effect}`).join(' · ')}>
                          {' · '}{c.counter_exposure < 0.5 ? 'sem counters a sério'
                            : `exposto a counters (${c.counter_exposure})`}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="text-sm font-semibold tabular-nums text-gray-300 shrink-0">
                    {c.worth_it.toFixed(1)}%
                  </div>
                </div>
              ))}
            </div>
        </Painel>
      )}

      {bans && bans.bans.length > 0 && (
        <div className="bg-[#161616] rounded-2xl border border-[#222]">
          <div className="p-4 border-b border-[#222]">
            <div className="flex items-center gap-2 text-white font-semibold">
              <Ban className="w-4 h-4 text-red-400" />
              Vale a pena banir alguém?
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Não dá para responder a "contra quem perco" — dos 19 junglers que apanhaste dez
              ou mais vezes, um passa o teste, e com dezanove testes espera-se exactamente um
              falso positivo. O que dá para medir é quanto cada um te baixa o melhor pick que
              te resta, vezes as vezes que aparece. Um ban tira o campeão aos dois lados.
            </p>
          </div>
          <div className="p-4">
            <p className="text-sm text-gray-300 mb-3">
              O melhor ban vale-te{' '}
              <span className="text-white font-semibold">
                {bans.bans[0].gain > 0 ? '+' : ''}{bans.bans[0].gain.toFixed(3)}pp por jogo
              </span>
              {' '}— praticamente nada, e por uma boa razão: contra qualquer um deles tens
              sempre uma resposta acima dos 50%. O teu pool é largo o suficiente para o ban
              não decidir nada.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6">
              {bans.bans.slice(0, 6).map((b) => (
                <div key={b.champion} className="flex items-center gap-3 py-1.5 border-b border-[#1e1e1e]">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-gray-200 truncate">
                      {b.champion}
                      {b.in_my_pool && (
                        <span className="text-[10px] text-yellow-600 ml-1.5">também o perdes</span>
                      )}
                    </div>
                    <div className="text-[11px] text-gray-500">
                      {b.encounters} encontros · respondes com {b.best_answer} ({b.best_answer_wr}%)
                    </div>
                  </div>
                  <div className={`text-xs font-semibold tabular-nums shrink-0 ${
                    b.gain > 0 ? 'text-gray-300' : 'text-gray-600'
                  }`}>
                    {b.gain > 0 ? '+' : ''}{b.gain.toFixed(3)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {duelo.by_champion.length > 0 && (
        <div className="bg-[#161616] rounded-2xl border border-[#222]">
          <div className="p-4 border-b border-[#222]">
            <div className="text-white font-semibold">Campeão a campeão</div>
            <p className="text-xs text-gray-500 mt-1">
              Tudo em diferença para o jungler adversário. Sem teste — com 8 a 40 jogos por
              campeão nada passaria, e a mediana já diz o que interessa.
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[11px] text-gray-500 border-b border-[#222]">
                  <th className="text-left px-4 py-2 font-medium">Campeão</th>
                  <th className="text-right px-3 py-2 font-medium">Jogos</th>
                  <th className="text-right px-3 py-2 font-medium">WR</th>
                  <th className="text-right px-3 py-2 font-medium">CS selva @10</th>
                  <th className="text-right px-3 py-2 font-medium">Ouro @15</th>
                  <th className="text-right px-3 py-2 font-medium">Ouro/min</th>
                  <th className="text-right px-3 py-2 font-medium">Dano/min</th>
                  <th className="text-right px-3 py-2 font-medium">Mortes</th>
                  <th className="text-right px-3 py-2 font-medium">Visão/min</th>
                </tr>
              </thead>
              <tbody>
                {duelo.by_champion.map((c: any) => (
                  <tr key={c.champion} className="border-b border-[#1e1e1e] last:border-0">
                    <td className="px-4 py-2 text-gray-200">{c.champion}</td>
                    <td className="px-3 py-2 text-right text-gray-500 tabular-nums">{c.games}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-gray-300">{c.winrate}%</td>
                    {['jungle_cs10', 'gd15', 'gold_min', 'damage_min', 'deaths', 'vision_min'].map((k) => {
                      const v = c[k];
                      const bom = k === 'deaths' ? (v ?? 0) < 0 : (v ?? 0) > 0;
                      return (
                        <td key={k} className={`px-3 py-2 text-right tabular-nums ${
                          v == null ? 'text-gray-700' : bom ? 'text-green-400' : 'text-red-400'
                        }`}>
                          {v == null ? '—' : sinal(v, k === 'vision_min' ? 2 : k === 'deaths' ? 1 : 0)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
