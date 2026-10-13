import { useState, useEffect } from 'react';
import {
  Loader2, ExternalLink, TrendingUp, TrendingDown, Sparkles, RefreshCw, ChevronDown,
  Swords, Trophy, Zap, Target, Route, Crosshair, Wrench, AlertTriangle,
} from 'lucide-react';
import { lolApi } from '../api';

const TIER_STYLE: Record<string, { bg: string; text: string }> = {
  'S+': { bg: 'bg-fuchsia-500/15', text: 'text-fuchsia-300' },
  S: { bg: 'bg-amber-500/15', text: 'text-amber-300' },
  A: { bg: 'bg-emerald-500/15', text: 'text-emerald-300' },
  B: { bg: 'bg-sky-500/15', text: 'text-sky-300' },
  C: { bg: 'bg-gray-500/15', text: 'text-gray-400' },
  D: { bg: 'bg-red-500/15', text: 'text-red-300' },
};

function tierStyle(tier?: string | null) {
  return TIER_STYLE[tier || ''] || { bg: 'bg-white/5', text: 'text-gray-500' };
}

function champIcon(version: string | undefined, key: string) {
  if (!version) return '';
  return `https://ddragon.leagueoflegends.com/cdn/${version}/img/champion/${key}.png`;
}

function wrColor(wr?: number | null) {
  if (wr == null) return 'text-gray-500';
  if (wr >= 52) return 'text-green-400';
  if (wr >= 50) return 'text-emerald-300';
  if (wr >= 48) return 'text-yellow-400';
  return 'text-red-400';
}

function Section({ icon, title, subtitle, children, right }: {
  icon: React.ReactNode; title: string; subtitle?: string; children: React.ReactNode; right?: React.ReactNode;
}) {
  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden mb-6">
      <div className="flex items-center justify-between gap-3 p-4 border-b border-[#222] flex-wrap">
        <div>
          <h3 className="text-sm font-medium text-gray-200 flex items-center gap-2">{icon} {title}</h3>
          {subtitle && <p className="text-[11px] text-gray-500 mt-0.5">{subtitle}</p>}
        </div>
        {right}
      </div>
      {children}
    </div>
  );
}

function ChangeLines({ groups }: { groups: any[] }) {
  return (
    <div className="space-y-2">
      {groups.map((g, i) => (
        <div key={i}>
          {g.title && <p className="text-[11px] font-medium text-gray-400 mb-1">{g.title}</p>}
          <ul className="space-y-1">
            {g.changes.map((c: any, j: number) => (
              <li key={j} className="text-xs text-gray-400 leading-relaxed">
                {c.label ? (
                  <>
                    <span className="text-gray-500">{c.label}:</span>{' '}
                    <span className="text-gray-600 line-through">{c.before}</span>{' '}
                    <span className="text-gray-600">→</span>{' '}
                    <span className="text-gray-200 font-medium">{c.after}</span>
                  </>
                ) : c.text}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function ItemRow({ items, label }: { items: any[]; label?: string }) {
  if (!items?.length) return null;
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {label && <span className="text-[10px] text-gray-500 w-14 shrink-0">{label}</span>}
      {items.map((it, i) => (
        <div key={i} className="flex items-center gap-1.5" title={it.name}>
          {i > 0 && <span className="text-gray-700 text-xs">›</span>}
          {it.icon
            ? <img src={it.icon} alt={it.name} className="w-7 h-7 rounded-md border border-[#333]" />
            : <span className="w-7 h-7 rounded-md bg-[#222]" />}
        </div>
      ))}
    </div>
  );
}

function BuildCard({ build }: { build: any }) {
  const best = build.label === 'Melhor winrate';
  return (
    <div className="bg-[#111] rounded-xl border border-[#222] p-4">
      <div className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${
          best ? 'bg-emerald-500/15 text-emerald-300' : 'bg-sky-500/15 text-sky-300'
        }`}>
          {build.label}
        </span>
        {build.core_items?.winrate != null && (
          <span className="text-[11px] text-gray-500">
            <span className={`font-bold ${wrColor(build.core_items.winrate)}`}>{build.core_items.winrate}%</span>
            {' '}· {build.core_items.games?.toLocaleString('pt-PT')} jogos
          </span>
        )}
      </div>

      <div className="space-y-2.5">
        <ItemRow label="Início" items={build.starting_items?.resolved || []} />
        <ItemRow label="Core" items={build.core_items?.resolved || []} />

        {['item4', 'item5', 'item6'].some(s => build[s]?.length > 0) && (
          <div className="flex items-start gap-2">
            <span className="text-[10px] text-gray-500 w-14 shrink-0 mt-1.5">Depois</span>
            <div className="flex gap-3 flex-wrap">
              {['item4', 'item5', 'item6'].map(slot => (
                build[slot]?.length > 0 && (
                  <div key={slot} className="flex items-center gap-1">
                    {build[slot].slice(0, 2).map((o: any) => (
                      <div key={o.id} className="relative group" title={`${o.name} · ${o.winrate}% WR`}>
                        {o.icon
                          ? <img src={o.icon} alt={o.name} className="w-7 h-7 rounded-md border border-[#333] opacity-80" />
                          : <span className="w-7 h-7 rounded-md bg-[#222]" />}
                      </div>
                    ))}
                  </div>
                )
              ))}
            </div>
          </div>
        )}

        <div className="pt-2 border-t border-[#1e1e1e] space-y-2">
          <div className="flex items-start gap-2 flex-wrap">
            <span className="text-[10px] text-gray-500 w-14 shrink-0 mt-1">Runas</span>
            <div className="flex-1 min-w-0 space-y-1.5">
              <div className="flex items-center gap-1.5 flex-wrap">
                {(build.runes?.primary_resolved || []).map((r: any, i: number) => (
                  <span key={i} className={`flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded-md ${
                    i === 0 ? 'bg-yellow-500/15 text-yellow-200 font-medium' : 'bg-white/5 text-gray-400'
                  }`} title={r.desc || r.name}>
                    {r.icon && <img src={r.icon} alt="" className="w-4 h-4" />}
                    {r.name}
                  </span>
                ))}
              </div>
              <div className="flex items-center gap-1.5 flex-wrap">
                {(build.runes?.secondary_resolved || []).map((r: any, i: number) => (
                  <span key={i} className="flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded-md bg-white/5 text-gray-400" title={r.desc || r.name}>
                    {r.icon && <img src={r.icon} alt="" className="w-4 h-4" />}
                    {r.name}
                  </span>
                ))}
                {(build.runes?.shards_resolved || []).map((r: any, i: number) => (
                  <span key={`s${i}`} className="text-[10px] px-1.5 py-0.5 rounded-md bg-[#1c1c1c] text-gray-500">{r.name}</span>
                ))}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] text-gray-500 w-14 shrink-0">Skills</span>
            <span className="text-xs font-bold text-gray-200 tracking-wider">
              {(build.skill_priority?.order || '').split('').join(' › ')}
            </span>
            {build.skill_order?.sequence?.length > 0 && (
              <span className="text-[10px] text-gray-600">
                ({build.skill_order.sequence.slice(0, 9).join('')}…)
              </span>
            )}
            <span className="flex items-center gap-1 ml-auto">
              {(build.summoners?.resolved || []).map((s: any, i: number) => (
                s.icon
                  ? <img key={i} src={s.icon} alt={s.name} title={s.name} className="w-6 h-6 rounded-md border border-[#333]" />
                  : <span key={i} className="text-[10px] text-gray-500">{s.name}</span>
              ))}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

const TIP_SECTIONS: { key: string; title: string; icon: React.ReactNode; color: string }[] = [
  { key: 'patch_impact', title: 'O que este patch muda para ti', icon: <Zap size={13} />, color: 'text-yellow-400' },
  { key: 'pathing', title: 'Clear & pathing', icon: <Route size={13} />, color: 'text-emerald-400' },
  { key: 'objectives', title: 'Objectivos', icon: <Target size={13} />, color: 'text-cyan-400' },
  { key: 'matchups', title: 'Matchups', icon: <Crosshair size={13} />, color: 'text-purple-400' },
  { key: 'fix_my_game', title: 'Corrigir no teu jogo', icon: <Wrench size={13} />, color: 'text-orange-400' },
];

export default function JungleMetaTab() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedChamp, setSelectedChamp] = useState<string | null>(null);
  const [build, setBuild] = useState<any>(null);
  const [buildLoading, setBuildLoading] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);

  const [tips, setTips] = useState<any>(null);
  const [tipsLoading, setTipsLoading] = useState(false);
  const [tipsError, setTipsError] = useState<string | null>(null);

  const [showAllTier, setShowAllTier] = useState(false);

  useEffect(() => { load(); }, []);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const d = await lolApi.jungleInsights();
      setData(d);
      const first = d.my_pool?.[0]?.champion;
      if (first) selectChamp(first);
    } catch (e: any) {
      setError(e?.message || 'Não consegui carregar a meta de jungle');
    } finally {
      setLoading(false);
    }
  }

  async function selectChamp(champion: string) {
    setSelectedChamp(champion);
    setBuildLoading(true);
    setBuildError(null);
    setBuild(null);
    try {
      setBuild(await lolApi.jungleBuild(champion));
    } catch (e: any) {
      setBuildError(e?.message || 'Sem build para este campeão');
    } finally {
      setBuildLoading(false);
    }
  }

  async function loadTips(force = false) {
    setTipsLoading(true);
    setTipsError(null);
    try {
      const t = await lolApi.jungleTips(force);
      if (!t.generated) {
        setTipsError(t.message || 'A IA não devolveu dicas.');
        setTips(null);
      } else {
        setTips(t);
      }
    } catch (e: any) {
      setTipsError(e?.message || 'Falhou a gerar dicas');
    } finally {
      setTipsLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-20 text-gray-500 text-sm">
        <Loader2 size={16} className="animate-spin" /> A carregar a meta de jungle…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="bg-[#161616] rounded-2xl border border-[#222] p-8 text-center">
        <p className="text-sm text-gray-400">{error || 'Sem dados'}</p>
        <button onClick={load} className="mt-3 px-4 py-1.5 bg-[#222] hover:bg-[#2a2a2a] rounded-lg text-xs">Tentar outra vez</button>
      </div>
    );
  }

  const patch = data.patch || {};
  const version = patch.version;
  const tierList = showAllTier ? data.tier_list : data.tier_list?.slice(0, 10);
  const poolChanged = (data.my_pool || []).filter((p: any) => p.patch_changes);

  return (
    <div>
      {/* Cabeçalho do patch */}
      <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 mb-6 flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <span className="text-2xl">🌿</span>
          <div>
            <p className="text-sm font-medium text-gray-200">
              Meta de jungle · patch {patch.site || patch.short || '—'}
              {data.patch_is_current === false && (
                <span className="ml-2 text-[10px] text-yellow-400/80">(notas do patch anterior)</span>
              )}
            </p>
            <p className="text-[11px] text-gray-500">
              {data.rank}
              {data.average_winrate && <> · WR médio da jungle {data.average_winrate}%</>}
              {data.recent_form?.games > 0 && (
                <> · a tua forma: <span className={wrColor(data.recent_form.winrate)}>{data.recent_form.winrate}%</span> nos últimos {data.recent_form.games}</>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {data.patch_notes_url && (
            <a href={data.patch_notes_url} target="_blank" rel="noreferrer"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-white/5 text-gray-400 hover:text-white hover:bg-white/10">
              Notas oficiais <ExternalLink size={11} />
            </a>
          )}
          <button onClick={load} className="p-2 rounded-lg bg-white/5 text-gray-400 hover:text-white hover:bg-white/10" title="Actualizar">
            <RefreshCw size={13} />
          </button>
        </div>
      </div>

      {/* Mudanças do patch com impacto na jungle */}
      <Section
        icon={<Zap size={14} className="text-yellow-400" />}
        title="O que mudou para a jungle neste patch"
        subtitle={`${data.jungle_system_changes?.length || 0} alterações de sistema · ${data.jungle_champion_changes?.length || 0} campeões de jungle mexidos`}
      >
        <div className="p-4 space-y-3">
          {(data.jungle_system_changes || []).map((s: any, i: number) => (
            <div key={i} className="bg-yellow-500/5 border border-yellow-500/20 rounded-xl p-3">
              <p className="text-xs font-medium text-yellow-300 mb-1">⚙️ {s.name}</p>
              {s.context && <p className="text-[11px] text-gray-500 mb-2 leading-relaxed">{s.context}</p>}
              <ChangeLines groups={s.groups} />
            </div>
          ))}

          {(data.jungle_champion_changes || []).map((c: any, i: number) => {
            const mine = (data.my_pool || []).find((p: any) => p.champion_slug === c.champion_slug);
            return (
              <div key={i} className={`rounded-xl p-3 border ${mine ? 'bg-purple-500/5 border-purple-500/30' : 'bg-[#111] border-[#222]'}`}>
                <p className="text-xs font-medium text-gray-200 mb-1 flex items-center gap-2 flex-wrap">
                  {version && <img src={champIcon(version, c.ddragon_key || c.name)} alt="" className="w-5 h-5 rounded" />}
                  {c.name || c.champion_slug}
                  {mine && <span className="text-[10px] bg-purple-500/20 text-purple-300 px-1.5 py-0.5 rounded-full">está no teu pool</span>}
                </p>
                {c.context && <p className="text-[11px] text-gray-500 mb-2 leading-relaxed">{c.context}</p>}
                <ul className="space-y-1">
                  {(c.changes || []).map((t: string, j: number) => (
                    <li key={j} className="text-xs text-gray-400">{t}</li>
                  ))}
                </ul>
              </div>
            );
          })}

          {!data.jungle_system_changes?.length && !data.jungle_champion_changes?.length && (
            <p className="text-xs text-gray-600 text-center py-4">Nada relevante para a jungle neste patch.</p>
          )}

          {poolChanged.length > 0 && (
            <div className="flex items-start gap-2 bg-[#111] border border-[#222] rounded-xl p-3">
              <AlertTriangle size={13} className="text-orange-400 shrink-0 mt-0.5" />
              <p className="text-[11px] text-gray-400">
                Levaram mexidas no teu pool: <span className="text-gray-200">{poolChanged.map((p: any) => p.champion).join(', ')}</span>
              </p>
            </div>
          )}
        </div>
      </Section>

      {/* O teu pool vs meta */}
      <Section
        icon={<Swords size={14} className="text-purple-400" />}
        title="O teu pool vs a meta"
        subtitle="winrate pessoal contra o winrate global no Master+ EUW"
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 p-4">
          {(data.my_pool || []).map((p: any) => {
            const ts = tierStyle(p.tier);
            const edge = p.edge;
            const active = selectedChamp === p.champion;
            return (
              <button
                key={p.champion}
                onClick={() => selectChamp(p.champion)}
                className={`text-left bg-[#111] rounded-xl p-3 border transition-all ${
                  active ? 'border-purple-500/60 ring-1 ring-purple-500/30' : 'border-[#222] hover:border-[#333]'
                }`}
              >
                <div className="flex items-center gap-2.5">
                  {version && <img src={champIcon(version, p.champion)} alt="" className="w-9 h-9 rounded-lg" />}
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium truncate">{p.champion}</p>
                    <p className="text-[10px] text-gray-500">{p.games} jogos · {p.wins}V {p.losses}D</p>
                  </div>
                  {p.tier && <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${ts.bg} ${ts.text}`}>{p.tier}</span>}
                </div>
                <div className="flex items-center justify-between mt-2.5 text-[11px]">
                  <span>
                    <span className={`font-bold ${wrColor(p.winrate)}`}>{p.winrate}%</span>
                    <span className="text-gray-600"> tu</span>
                  </span>
                  {p.meta_winrate != null && (
                    <span className="text-gray-500">
                      meta <span className="text-gray-300">{p.meta_winrate}%</span>
                    </span>
                  )}
                  {edge != null && (
                    <span className={`flex items-center gap-0.5 font-medium ${edge >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {edge >= 0 ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                      {edge > 0 ? '+' : ''}{edge}
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      </Section>

      {/* Build do campeão seleccionado */}
      <Section
        icon={<Trophy size={14} className="text-emerald-400" />}
        title={selectedChamp ? `Build de ${selectedChamp}` : 'Build'}
        subtitle="lolalytics · jungle · Master+ · patch actual"
        right={
          <div className="flex gap-1 flex-wrap justify-end">
            {(data.my_pool || []).slice(0, 6).map((p: any) => (
              <button key={p.champion} onClick={() => selectChamp(p.champion)}
                className={`px-2 py-1 rounded-md text-[11px] transition-all ${
                  selectedChamp === p.champion ? 'bg-emerald-600/25 text-emerald-300' : 'bg-white/5 text-gray-500 hover:text-gray-300'
                }`}>
                {p.champion}
              </button>
            ))}
          </div>
        }
      >
        <div className="p-4">
          {buildLoading ? (
            <div className="flex items-center justify-center gap-2 py-10 text-gray-500 text-sm">
              <Loader2 size={15} className="animate-spin" /> A carregar build…
            </div>
          ) : buildError ? (
            <p className="text-xs text-gray-500 text-center py-8">{buildError}</p>
          ) : build ? (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {build.builds.map((b: any, i: number) => <BuildCard key={i} build={b} />)}
            </div>
          ) : (
            <p className="text-xs text-gray-600 text-center py-8">Escolhe um campeão.</p>
          )}
        </div>
      </Section>

      {/* Tier list */}
      <Section
        icon={<TrendingUp size={14} className="text-cyan-400" />}
        title="Tier list de jungle"
        subtitle="Master+ EUW · média ponderada de lolalytics, u.gg e op.gg"
        right={
          data.tier_list?.length > 10 && (
            <button onClick={() => setShowAllTier(s => !s)}
              className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] bg-white/5 text-gray-400 hover:text-white">
              {showAllTier ? 'Mostrar menos' : `Ver todos (${data.tier_list.length})`}
              <ChevronDown size={11} className={showAllTier ? 'rotate-180' : ''} />
            </button>
          )
        }
      >
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] text-gray-600 border-b border-[#222]">
                <th className="text-left font-normal py-2 px-4">Campeão</th>
                <th className="text-center font-normal px-2">Tier</th>
                <th className="text-right font-normal px-2">WR</th>
                <th className="text-right font-normal px-2 hidden sm:table-cell">Pick</th>
                <th className="text-right font-normal px-2 hidden sm:table-cell">Ban</th>
                <th className="text-right font-normal px-4 hidden md:table-cell">Jogos</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1a1a1a]">
              {(tierList || []).map((c: any) => {
                const ts = tierStyle(c.tier);
                const mine = (data.my_pool || []).some((p: any) => p.champion_slug === c.champion);
                return (
                  <tr key={c.champion} className={`hover:bg-white/5 ${mine ? 'bg-purple-500/5' : ''}`}>
                    <td className="py-2 px-4">
                      <div className="flex items-center gap-2">
                        {version && <img src={champIcon(version, c.ddragon_key)} alt="" className="w-6 h-6 rounded" />}
                        <span className="text-gray-200">{c.ddragon_key}</span>
                        {mine && <span className="text-[9px] text-purple-300">teu</span>}
                        {c.patch_changes && <span className="text-[9px] text-yellow-400" title="mexido neste patch">⚡</span>}
                      </div>
                    </td>
                    <td className="text-center px-2">
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${ts.bg} ${ts.text}`}>{c.tier}</span>
                    </td>
                    <td className={`text-right px-2 font-medium ${wrColor(c.winrate)}`}>{c.winrate}%</td>
                    <td className="text-right px-2 text-gray-500 hidden sm:table-cell">{c.pickrate}%</td>
                    <td className="text-right px-2 text-gray-500 hidden sm:table-cell">{c.banrate}%</td>
                    <td className="text-right px-4 text-gray-600 hidden md:table-cell">{c.games?.toLocaleString('pt-PT')}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>

      {/* Dicas IA */}
      <Section
        icon={<Sparkles size={14} className="text-pink-400" />}
        title="Dicas para o teu jogo"
        subtitle="geradas com pesquisa web, ancoradas no patch, no teu rank e nas tuas estatísticas"
        right={
          <button onClick={() => loadTips(!!tips)} disabled={tipsLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-pink-600/20 text-pink-300 hover:bg-pink-600/30 disabled:opacity-50">
            {tipsLoading ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
            {tipsLoading ? 'A pensar…' : tips ? 'Regenerar' : 'Gerar dicas'}
          </button>
        }
      >
        <div className="p-4">
          {tipsLoading && !tips && (
            <p className="text-xs text-gray-500 text-center py-8">
              A pesquisar o patch e a analisar os teus jogos — demora até 2 minutos.
            </p>
          )}
          {tipsError && <p className="text-xs text-red-400 text-center py-6">{tipsError}</p>}
          {!tips && !tipsLoading && !tipsError && (
            <p className="text-xs text-gray-600 text-center py-8">
              Carrega em “Gerar dicas” para receber dicas específicas do patch {patch.site} para o teu pool.
            </p>
          )}

          {tips?.tips && (
            <div className="space-y-4">
              {TIP_SECTIONS.map(s => {
                const list: string[] = tips.tips[s.key] || [];
                if (!list.length) return null;
                return (
                  <div key={s.key}>
                    <p className={`text-xs font-medium mb-2 flex items-center gap-1.5 ${s.color}`}>{s.icon} {s.title}</p>
                    <ul className="space-y-1.5">
                      {list.map((t, i) => (
                        <li key={i} className="text-xs text-gray-300 leading-relaxed flex gap-2">
                          <span className="text-gray-700 shrink-0">•</span>
                          <span>{t}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}

              {tips.tips.champion_tips?.length > 0 && (
                <div>
                  <p className="text-xs font-medium mb-2 flex items-center gap-1.5 text-emerald-400">
                    <Swords size={13} /> Por campeão
                  </p>
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                    {tips.tips.champion_tips.map((ct: any, i: number) => (
                      <div key={i} className="bg-[#111] rounded-xl border border-[#222] p-3">
                        <p className="text-xs font-medium text-gray-200 mb-1">{ct.champion}</p>
                        {ct.verdict && <p className="text-[11px] text-gray-500 mb-2 leading-relaxed">{ct.verdict}</p>}
                        <ul className="space-y-1.5">
                          {(ct.tips || []).map((t: string, j: number) => (
                            <li key={j} className="text-xs text-gray-300 leading-relaxed flex gap-2">
                              <span className="text-gray-700 shrink-0">•</span>
                              <span>{t}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <p className="text-[10px] text-gray-600 pt-2 border-t border-[#1e1e1e]">
                patch {tips.patch} · {tips.cached ? 'em cache' : 'geradas agora'}
                {tips.generated_at && ` · ${tips.generated_at.replace('T', ' ')}`}
              </p>
            </div>
          )}
        </div>
      </Section>
    </div>
  );
}
