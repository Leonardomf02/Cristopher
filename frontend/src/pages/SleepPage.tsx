import { useState, useEffect } from 'react';
import { format, parseISO, subDays } from 'date-fns';
import { pt } from 'date-fns/locale';
import { Moon, Sun, Watch } from 'lucide-react';
import { garminApi, nightsApi, sleepApi, type NightOut, type NightOutDay, type NightOutEffect, type GarminDayView, type GarminNap, type GarminHistoryPoint, type SleepAnalysis, type SleepRhythm } from '../api';
import { SleepEntry } from '../types';
import NoiteFora, { NIVEIS_DE_BEBIDA } from '../components/NoiteFora';

// O relógio do ritmo vai das 18h às 18h: uma noite que começa às 02:00 não pode
// aparecer no princípio do dia, senão parece que ele se deitou de manhã.
const RITMO_INICIO = 18 * 60;
const RITMO_FIM = RITMO_INICIO + 24 * 60;

function hhmm(minutos: number | null | undefined) {
  if (minutos == null) return '—';
  const m = ((Math.round(minutos) % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
}

/** A que horas ele se deita, noite a noite. A hora de deitar varia muito mais do
 *  que as horas dormidas, e é isso que este gráfico mostra: cada linha é uma
 *  noite, do deitar ao acordar, num relógio de 18h a 18h. Só entram as noites que
 *  o relógio mediu — o palpite pelo uso do Mac trazia sestas e noites impossíveis
 *  que era preciso marcar e pôr de lado. */
function RitmoDoSono() {
  const [dados, setDados] = useState<SleepRhythm | null>(null);
  const [erro, setErro] = useState('');
  const [dias, setDias] = useState(90);

  useEffect(() => {
    setErro('');
    sleepApi.rhythm(dias).then(setDados)
      .catch(e => { setDados(null); setErro(e?.message || 'não deu para ler as noites'); });
  }, [dias]);

  // "a ler…" para sempre era a forma de a página mentir quando o pedido falhava.
  if (erro) return <p className="text-sm text-red-400">Falhou a leitura: {erro}</p>;
  if (!dados) return <p className="text-sm text-gray-600">a ler as noites…</p>;

  const pos = (min: number) => ((min - RITMO_INICIO) / (RITMO_FIM - RITMO_INICIO)) * 100;
  const noites = dados.points.filter(p => p.bed_min != null && p.wake_min != null);
  const medianaDeitar = dados.points.length && dados.median_bedtime
    ? dados.points.find(p => p.bedtime === dados.median_bedtime)?.bed_min ?? null : null;
  const scores = dados.points.map(p => p.score).filter((s): s is number => s != null).sort((a, b) => a - b);
  const pontuacaoTipica = scores.length
    ? Math.round(scores.length % 2 ? scores[(scores.length - 1) / 2]
        : (scores[scores.length / 2 - 1] + scores[scores.length / 2]) / 2)
    : null;

  return (
    <div className="flex flex-col gap-4 lg:gap-6 lg:flex-1 lg:min-h-0">
      <div className="flex items-center justify-between gap-3 flex-wrap shrink-0">
        <p className="text-sm text-gray-500">
          {dados.nights} {dados.nights === 1 ? 'noite medida' : 'noites medidas'} pelo relógio
          {dados.nights < 14 && (
            <span className="text-gray-600"> · com tão poucas, as medianas ainda vão mudar</span>
          )}
        </p>
        <div className="flex items-center gap-1 bg-[#161616] rounded-xl border border-[#222] p-1">
          {[30, 90, 180, 365].map(d => (
            <button key={d} onClick={() => setDias(d)}
              className={`px-3 py-1.5 text-xs rounded-lg transition-all ${
                dias === d ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-white'}`}>
              {d}d
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 shrink-0">
        <Cartao titulo="Deita-se por volta das" valor={dados.median_bedtime || '—'}
          sub={`varia ${hm(dados.bed_variation_h * 60)} em média`} />
        <Cartao titulo="Acorda por volta das" valor={dados.median_wake || '—'}
          sub={`varia ${hm(dados.wake_variation_h * 60)} em média`} />
        <Cartao titulo="Dorme" valor={dados.median_hours != null ? hm(dados.median_hours * 60) : '—'}
          sub="mediana das noites" />
        <Cartao titulo="Fim-de-semana"
          valor={dados.weekend_shift_h != null
            ? `${dados.weekend_shift_h > 0 ? '+' : ''}${dados.weekend_shift_h}h` : '—'}
          sub="face aos dias de semana" />
        <Cartao titulo="Pontuação típica" valor={pontuacaoTipica != null ? `${pontuacaoTipica}/100` : '—'}
          sub="mediana do que o relógio deu" />
      </div>

      <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 flex flex-col lg:flex-1 lg:min-h-0">
        <div className="flex items-center justify-between mb-3 shrink-0">
          <h3 className="text-sm font-medium text-gray-300">Cada noite, do deitar ao acordar</h3>
          <span className="text-[10px] text-gray-600">18:00 → 18:00</span>
        </div>

        <div className="relative flex-1 min-h-0 overflow-y-auto">
          {/* As marcas das horas ficam por trás das noites, não numa régua à parte. */}
          <div className="absolute inset-0 pointer-events-none">
            {[0, 6, 12, 18, 24].map(h => (
              <div key={h} className="absolute top-0 bottom-0 w-px bg-[#222]"
                style={{ left: `${(h / 24) * 100}%` }} />
            ))}
          </div>
          <div className="space-y-[3px] relative">
            {noites.map(p => {
              const inicio = pos(p.bed_min!);
              const fim = pos(p.wake_min! < RITMO_INICIO ? p.wake_min! + 1440 : p.wake_min!);
              return (
                <div key={p.date} className="relative h-2.5"
                  title={`${format(parseISO(p.date), 'd/M')} · ${p.bedtime} → ${p.wake_time}`
                    + (p.hours ? ` · ${p.hours}h` : '') + (p.score != null ? ` · ${p.score}/100` : '')}>
                  <div className="absolute rounded-full h-full"
                    style={{
                      left: `${Math.max(0, inicio)}%`,
                      width: `${Math.max(0.6, Math.min(100, fim) - Math.max(0, inicio))}%`,
                      backgroundColor: p.weekday >= 5 ? '#f59e0b' : '#8B5CF6',
                      opacity: 0.85,
                    }} />
                </div>
              );
            })}
          </div>
        </div>

        <div className="flex items-center gap-4 mt-3 text-[10px] text-gray-600 shrink-0 flex-wrap">
          <span className="flex justify-between w-full text-gray-600">
            {['18:00', '00:00', '06:00', '12:00', '18:00'].map((h, i) => <span key={i}>{h}</span>)}
          </span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-[#8B5CF6]" /> semana</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-amber-500" /> sexta e sábado</span>
          {medianaDeitar != null && <span>mediana às {hhmm(medianaDeitar)}</span>}
        </div>
      </div>

      {/* O que acontece no dia seguinte, conforme se deitou cedo ou tarde. Não é
          uma conclusão: é a média dos dois grupos, lado a lado. */}
      <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 shrink-0">
        <h3 className="text-sm font-medium text-gray-300 mb-3">
          O dia seguinte, conforme a hora a que se deitou
        </h3>
        {/* Com quatro noites de cada lado isto não compara nada — mais vale dizer
            que faltam noites do que mostrar uma diferença de um dia contra um. */}
        {dados.early.days < 5 || dados.late.days < 5 ? (
          <p className="text-sm text-gray-600">
            Faltam noites medidas para comparar ({dados.early.days} cedo, {dados.late.days} tarde).
          </p>
        ) : (
        <div className="space-y-2">
          <div className="flex text-[11px] text-gray-600">
            <span className="flex-1" />
            <span className="w-24 text-right">cedo ({dados.early.days})</span>
            <span className="w-24 text-right">tarde ({dados.late.days})</span>
          </div>
          <Linha etiqueta="Winrate no LoL"
            cedo={dados.early.winrate != null ? `${dados.early.winrate}%` : '—'}
            tarde={dados.late.winrate != null ? `${dados.late.winrate}%` : '—'}
            destaque={dados.early.winrate != null && dados.late.winrate != null
              && Math.abs(dados.early.winrate - dados.late.winrate) >= 10} />
          <Linha etiqueta="Horas de código por dia"
            cedo={`${dados.early.code_hours}h`} tarde={`${dados.late.code_hours}h`}
            destaque={Math.abs(dados.early.code_hours - dados.late.code_hours) >= 1} />
          <Linha etiqueta="Gasto por dia"
            cedo={`${dados.early.spend}€`} tarde={`${dados.late.spend}€`}
            destaque={Math.abs(dados.early.spend - dados.late.spend) >= 10} />
        </div>
        )}
      </div>
    </div>
  );
}

/** As noites em conjunto, com os números que o relógio mede por dentro: de que é
 *  feita uma noite dele, o que anda junto com a pontuação, e as noites boas
 *  contra as más. A conta é a mesma do relógio — a régua da app é uma só. */
function AnaliseDasNoites() {
  const [dados, setDados] = useState<SleepAnalysis | null>(null);
  const [efeito, setEfeito] = useState<NightOutEffect | null>(null);
  const [erro, setErro] = useState('');
  const [dias, setDias] = useState(90);

  useEffect(() => {
    setErro('');
    sleepApi.analysis(dias).then(setDados)
      .catch(e => { setDados(null); setErro(e?.message || 'não deu para ler as noites'); });
    nightsApi.effect(Math.max(30, dias)).then(setEfeito).catch(() => setEfeito(null));
  }, [dias]);

  if (erro) return <p className="text-sm text-red-400">Falhou a leitura: {erro}</p>;
  if (!dados) return <p className="text-sm text-gray-600">a ler as noites…</p>;

  const cor = (v: string | null) => v === 'baixo' ? 'text-amber-400'
    : v === 'alto' ? 'text-sky-400' : 'text-gray-500';

  return (
    <div className="flex flex-col gap-4 lg:gap-6 lg:flex-1 lg:min-h-0 lg:overflow-y-auto">
      <div className="flex items-center justify-between gap-3 flex-wrap shrink-0">
        <p className="text-sm text-gray-500">
          {dados.nights} {dados.nights === 1 ? 'noite medida' : 'noites medidas'} pelo relógio
        </p>
        <div className="flex items-center gap-1 bg-[#161616] rounded-xl border border-[#222] p-1">
          {[30, 90, 180, 365].map(d => (
            <button key={d} onClick={() => setDias(d)}
              className={`px-3 py-1.5 text-xs rounded-lg transition-all ${
                dias === d ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-white'}`}>
              {d}d
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 lg:gap-6">
        {/* De que é feita uma noite dele */}
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-gray-300">De que é feita uma noite tua</h3>
            <span className="text-[10px] text-gray-600">mediana · faixa típica de adulto</span>
          </div>
          {dados.composition.length === 0 ? (
            <p className="text-sm text-gray-600">Ainda não há noites com fases medidas.</p>
          ) : (
            <div className="space-y-3">
              {dados.composition.map(f => {
                const fase = FASES_DO_SONO.find(x => x.chave === f.key);
                return (
                  <div key={f.key}>
                    <div className="flex items-baseline gap-2 text-sm">
                      <span className="w-2 h-2 rounded-full shrink-0 self-center"
                        style={{ backgroundColor: fase?.cor || '#495057' }} />
                      <span className="text-gray-400">{fase?.nome || f.name}</span>
                      <span className="ml-auto tabular-nums text-gray-200">{f.pct}%</span>
                      <span className="text-[11px] text-gray-600 w-14 text-right tabular-nums">{hm(f.minutes)}</span>
                    </div>
                    {f.reference && (
                      // A barra mostra onde a fatia dele cai dentro da faixa típica;
                      // a faixa é a zona clara, o traço é ele.
                      <div className="relative h-1.5 mt-1.5 ml-4 rounded-full bg-[#0f0f0f] overflow-hidden">
                        <div className="absolute top-0 bottom-0 bg-white/10"
                          style={{ left: `${f.reference[0] * 1.4}%`, width: `${(f.reference[1] - f.reference[0]) * 1.4}%` }} />
                        <div className="absolute top-0 bottom-0 w-1 rounded-full"
                          style={{ left: `${Math.min(98, f.pct * 1.4)}%`, backgroundColor: fase?.cor || '#888' }} />
                      </div>
                    )}
                    {f.verdict && f.verdict !== 'típico' && (
                      <p className={`text-[11px] mt-1 ml-4 ${cor(f.verdict)}`}>
                        {f.verdict} face aos {f.reference![0]}–{f.reference![1]}% típicos
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <div className="mt-4 pt-4 border-t border-[#222] grid grid-cols-1 gap-y-2">
            {dados.summary.map(s => (
              <Medida key={s.key} etiqueta={s.name.replace(/^(a|o|os|as) /, '')} valor={s.median} />
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-4 lg:gap-6">
          {/* O que explica uma noite boa */}
          <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-gray-300">O que anda junto com a pontuação</h3>
              <span className="text-[10px] text-gray-600">correlação de Spearman</span>
            </div>
            {dados.drivers.length > 0 ? (
              <ul className="space-y-3">
                {dados.drivers.map(d => (
                  <li key={d.key} className="text-sm">
                    <p className="text-gray-300">{d.text}</p>
                    <p className="text-[11px] text-gray-600 mt-0.5 tabular-nums">
                      ρ {d.rho > 0 ? '+' : ''}{d.rho} · p {d.p < 0.001 ? '<0,001' : String(d.p).replace('.', ',')} · {d.n} noites
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-gray-600">
                {dados.nights < dados.min_nights
                  ? `Faltam ${dados.min_nights - dados.nights} noites medidas. Com menos do que isso,
                     qualquer relação entre as fases e a pontuação é coincidência.`
                  : 'Nada passou no teste de significância — o que também é uma resposta.'}
              </p>
            )}
            {dados.tested.length > 0 && (
              <p className="text-[11px] text-gray-600 mt-3 pt-3 border-t border-[#222]">
                testado e sem resultado: {dados.tested.map(t => t.name.replace(/^(a|o|os|as) /, '')).join(', ')}.
              </p>
            )}
          </div>

          {/* Noites boas contra noites más */}
          <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
            <h3 className="text-sm font-medium text-gray-300 mb-3">
              As noites boas contra as más
            </h3>
            {dados.good_vs_bad.rows.length === 0 ? (
              <p className="text-sm text-gray-600">
                Faltam noites de cada lado para comparar ({dados.good_vs_bad.good} acima de 80,
                {' '}{dados.good_vs_bad.bad} abaixo de 60).
              </p>
            ) : (
              <div className="space-y-2">
                <div className="flex text-[11px] text-gray-600">
                  <span className="flex-1" />
                  <span className="w-24 text-right">boas ({dados.good_vs_bad.good})</span>
                  <span className="w-24 text-right">más ({dados.good_vs_bad.bad})</span>
                </div>
                {dados.good_vs_bad.rows.map(r => (
                  <div key={r.key} className={`flex text-sm ${r.notable ? 'text-gray-200' : 'text-gray-500'}`}>
                    <span className="flex-1">{r.name.replace(/^(a|o|os|as) /, '')}</span>
                    <span className="w-24 text-right tabular-nums">{r.good}</span>
                    <span className="w-24 text-right tabular-nums">{r.bad}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* A noite depois de sair e beber contra as noites em casa. As saídas
              sem beber ficam de fora: deitar às 4h sóbrio é outra pergunta. */}
          {efeito && <DepoisDeBeber efeito={efeito} />}
        </div>
      </div>
    </div>
  );
}

function DepoisDeBeber({ efeito }: { efeito: NightOutEffect }) {
  const provado = efeito.rows.some(r => r.p != null && r.p <= 0.05);
  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-gray-300">Depois de beber</h3>
        <span className="text-[10px] text-gray-600">mediana · a noite a seguir</span>
      </div>
      {efeito.rows.length === 0 ? (
        <p className="text-sm text-gray-600">
          {efeito.drank} {efeito.drank === 1 ? 'noite medida' : 'noites medidas'} depois de beber — faltam
          {' '}{Math.max(0, efeito.min - efeito.drank)} para comparar com as noites em casa. Marca as saídas
          com o 🌙 por cima de cada noite, nos registos, ou no cartão do sono do Dashboard.
        </p>
      ) : (
        <div className="space-y-2">
          <div className="flex text-[11px] text-gray-600">
            <span className="flex-1" />
            <span className="w-28 text-right">bebeste ({efeito.drank})</span>
            <span className="w-24 text-right">em casa ({efeito.home})</span>
          </div>
          {efeito.rows.map(r => (
            <div key={r.key} className="flex text-sm text-gray-400">
              <span className="flex-1 min-w-0 truncate">
                {r.name.replace(/^(a|o|os|as) /, '')}
                {r.p != null && r.p <= 0.05 && <span className="ml-1.5 text-[10px] text-sky-400">provado</span>}
              </span>
              <span className={`w-28 text-right tabular-nums ${r.worse ? 'text-amber-400' : 'text-gray-200'}`}>
                {r.drank}{r.unit && ` ${r.unit}`}
              </span>
              <span className="w-24 text-right tabular-nums text-gray-200">{r.home}{r.unit && ` ${r.unit}`}</span>
            </div>
          ))}
          <p className="text-[11px] text-gray-600 pt-2 border-t border-[#222]">
            {provado
              ? 'Provado = Mann-Whitney com p ≤ 0,05. O resto pode ser acaso.'
              : 'Ainda nada passa um teste (são precisas 8 noites de cada lado): por agora é só o que as medianas mostram.'}
            {efeito.sober_out > 0 && (efeito.sober_out === 1 ? ' 1 saída sem beber fica de fora.' : ` ${efeito.sober_out} saídas sem beber ficam de fora.`)}
          </p>
        </div>
      )}
    </div>
  );
}

function Cartao({ titulo, valor, sub }: { titulo: string; valor: string; sub: string }) {
  return (
    <div className="bg-[#161616] rounded-2xl p-4 border border-[#222]">
      <p className="text-[11px] text-gray-500 mb-1.5">{titulo}</p>
      <p className="text-xl font-bold tabular-nums">{valor}</p>
      <p className="text-[10px] text-gray-600 mt-1">{sub}</p>
    </div>
  );
}

function Linha({ etiqueta, cedo, tarde, destaque }: {
  etiqueta: string; cedo: string; tarde: string; destaque: boolean;
}) {
  return (
    <div className={`flex text-sm ${destaque ? 'text-gray-200' : 'text-gray-500'}`}>
      <span className="flex-1">{etiqueta}</span>
      <span className="w-24 text-right tabular-nums">{cedo}</span>
      <span className="w-24 text-right tabular-nums">{tarde}</span>
    </div>
  );
}

// A pontuação do relógio é 0-100 e substituiu a qualidade 1-5 que ele punha à
// mão. As cores são as da Garmin: abaixo de 60 é mau, acima de 80 é bom.
const QUALIFICADOR: Record<string, string> = {
  EXCELLENT: 'excelente', GOOD: 'bom', FAIR: 'razoável', POOR: 'fraco',
};

// O que a Garmin escreve no fim da noite, em português. O resto passa como veio,
// só limpo dos underscores.
const FEEDBACK_DO_SONO: Record<string, string> = {
  POSITIVE_REFRESHING: 'noite reparadora',
  POSITIVE_HIGHLY_RECOVERING: 'noite muito reparadora',
  POSITIVE_DEEP: 'boa dose de sono profundo',
  POSITIVE_CONTINUOUS: 'noite sem interrupções',
  POSITIVE_LONG: 'noite longa',
  NEGATIVE_SHORT: 'noite curta',
  NEGATIVE_LIGHT: 'sono leve a mais',
  NEGATIVE_FRAGMENTED: 'noite aos bocados',
  POSITIVE_LONG_BUT_LOW_QUALITY: 'longa, mas de pouca qualidade',
  NEGATIVE_NOT_ENOUGH_SLEEP: 'dormiste menos do que o corpo pedia',
  NEGATIVE_LOW_QUALITY: 'noite de pouca qualidade',
  NEGATIVE_RESTLESS: 'noite agitada',
};

/** A Garmin manda "none" e "unknown" no que ainda não calculou — mostrar isso é
 *  pior do que não mostrar nada. */
function limpo(v: string | null | undefined) {
  if (!v) return null;
  const t = v.replace(/_/g, ' ').trim().toLowerCase();
  return t && t !== 'none' && t !== 'unknown' ? t : null;
}

function corDaPontuacao(s: number | null | undefined) {
  if (s == null) return '#4b5563';
  if (s >= 80) return '#4ade80';
  if (s >= 70) return '#a3e635';
  if (s >= 60) return '#f59e0b';
  return '#f43f5e';
}

// A mesma cor que a sesta tem na linha do dia do relógio.
const COR_DA_SESTA = '#a855f7';

const FASES_DO_SONO = [
  { chave: 'deep_min', nome: 'Profundo', cor: '#4c6ef5' },
  { chave: 'light_min', nome: 'Leve', cor: '#748ffc' },
  { chave: 'rem_min', nome: 'REM', cor: '#9775fa' },
  { chave: 'awake_min', nome: 'Acordado', cor: '#495057' },
] as const;

function hm(minutos: number | null | undefined) {
  if (minutos == null) return '—';
  const m = Math.round(minutos);
  return m >= 60 ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}` : `${m}min`;
}

function horaDe(ms: number) {
  return format(new Date(ms), 'HH:mm');
}

/** Quanto é que esta noite fugiu ao costume dele. Abaixo de dez minutos não é
 *  diferença nenhuma — é a mesma noite com outros minutos. */
function diferencaDoCostume(horas: number, mediana: number | null) {
  if (mediana == null) return '';
  const delta = Math.round((horas - mediana) * 60);
  if (Math.abs(delta) < 10) return 'em cima do teu costume';
  return `${hm(Math.abs(delta))} ${delta > 0 ? 'acima' : 'abaixo'} do teu costume`;
}

/** As sestas de cada dia, tiradas do histórico do relógio. A chave é a mesma que
 *  a da noite (o dia em que ele acordou), que é como a Garmin conta o dia. */
function sestasPorDia(relogio: Record<string, GarminHistoryPoint>) {
  const mapa: Record<string, GarminNap[]> = {};
  for (const p of Object.values(relogio)) {
    if (p.naps?.length) mapa[p.date] = [...p.naps].sort((a, b) => a.start - b.start);
  }
  return mapa;
}

/** Etiqueta à esquerda, valor à direita, na mesma linha — o estilo das faixas de
 *  stress, que é o que se lê de relance.
 *
 *  Uma medida por linha, com o valor encostado à direita — é assim que todos os
 *  números ficam alinhados uns por baixo dos outros. */
function Medida({ etiqueta, valor, nota, cor }: {
  etiqueta: string; valor: string; nota?: string; cor?: string;
}) {
  return (
    <div className="flex items-baseline gap-2 text-sm min-w-0">
      {cor && <span className="w-2 h-2 rounded-full shrink-0 self-center" style={{ backgroundColor: cor }} />}
      <span className="text-gray-500 truncate">{etiqueta}</span>
      <span className="ml-auto text-gray-200 tabular-nums whitespace-nowrap">
        {valor}
        {/* O ponto é obrigatório: dois números colados ("8h00" e "faltaram
            45min") liam-se como um só, e um espaço sozinho não os separava. */}
        {nota && <span className="text-[11px] text-gray-500"> · {nota}</span>}
      </span>
    </div>
  );
}

/** Tudo o que o relógio mediu naquela noite, à mostra na própria página: fases,
 *  pontuação, o que o corpo pedia, HRV, oxigénio, bateria ao acordar. Já foi um
 *  modal que era preciso abrir — isto é o que ele quer ver primeiro, não o que
 *  vai procurar. */
function ANoite({ entrada, sestas, mediana, aoMudarSaida }: {
  entrada: SleepEntry; sestas: GarminNap[]; mediana: number | null;
  aoMudarSaida: (n: NightOutDay) => void;
}) {
  const [vista, setVista] = useState<GarminDayView | null | undefined>(undefined);

  useEffect(() => {
    let vivo = true;
    setVista(undefined);
    garminApi.day(entrada.date).then(v => vivo && setVista(v)).catch(() => vivo && setVista(null));
    return () => { vivo = false; };
  }, [entrada.date]);

  const dia = vista?.day ?? (vista === null ? null : undefined);
  const s = dia?.sleep;
  const totalFases = FASES_DO_SONO.reduce((t, f) => t + (s?.[f.chave] || 0), 0);
  const minutosDeSesta = sestas.reduce((t, n) => t + n.min, 0);
  const resumo = [
    minutosDeSesta > 0 ? `${hm(entrada.hours * 60 + minutosDeSesta)} de sono ao todo` : '',
    diferencaDoCostume(entrada.hours, mediana),
  ].filter(Boolean).join(' · ');

  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] flex flex-col lg:h-full min-h-0">
      <div className="px-4 py-3 border-b border-[#222] shrink-0">
        {/* A noite que acabou nesta manhã começou na véspera: é essa que se
            marca como saída. */}
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-medium text-gray-300 min-w-0 truncate">
            {format(parseISO(entrada.date), "EEEE, d 'de' MMMM", { locale: pt })}
          </h3>
          <NoiteFora data={format(subDays(parseISO(entrada.date), 1), 'yyyy-MM-dd')} aoMudar={aoMudarSaida} />
        </div>
        <p className="text-xs text-gray-600 mt-0.5">
          {entrada.bedtime && entrada.wake_time ? `${entrada.bedtime} → ${entrada.wake_time}` : 'sem horas registadas'}
          {entrada.source === 'garmin' ? ' · medido pelo relógio' : ' · estimado pelo uso do Mac'}
        </p>
      </div>

      {/* As três partes — os números grandes, as fases e as medidas — repartem a
          altura do painel (`justify-between`), como os painéis do relógio. Com
          espaçamento fixo, um portátil alto deixava meio painel vazio por baixo
          e num baixo era preciso rolar. */}
      <div className="px-4 py-3.5 flex flex-col gap-3.5 lg:justify-between flex-1 min-h-0 overflow-y-auto">
        <div className="shrink-0">
          <div className="flex items-end">
            <div className="flex-1 min-w-0">
              <p className="text-2xl font-bold leading-none tabular-nums">{hm(entrada.hours * 60)}</p>
              <p className="text-[11px] text-gray-600 mt-1.5">a dormir</p>
            </div>
            {s?.score != null && (
              <div className="flex-1 min-w-0 pl-3 border-l border-[#222]">
                <p className="text-2xl font-bold leading-none tabular-nums" style={{ color: corDaPontuacao(s.score) }}>
                  {s.score}<span className="text-sm text-gray-600">/100</span>
                </p>
                <p className="text-[11px] text-gray-600 mt-1.5">
                  {s.qualifier ? QUALIFICADOR[s.qualifier] || s.qualifier.toLowerCase() : 'pontuação'}
                </p>
              </div>
            )}
            {/* A sesta é sono que a noite não conta: em 14 de Agosto foram 7h15
                na cama e mais 2h24 ao fim da tarde, e a página dizia só 7h15. */}
            {minutosDeSesta > 0 && (
              <div className="flex-1 min-w-0 pl-3 border-l border-[#222]">
                <p className="text-2xl font-bold leading-none tabular-nums" style={{ color: COR_DA_SESTA }}>
                  {hm(minutosDeSesta)}
                </p>
                <p className="text-[11px] text-gray-600 mt-1.5">
                  {sestas.length > 1 ? `${sestas.length} sestas` : 'de sesta'}
                </p>
              </div>
            )}
          </div>

          {/* A noite dele contra as noites dele. Um número sozinho não diz se
              7h15 foi muito ou pouco. */}
          {resumo && <p className="text-[11px] text-gray-500 mt-2.5">{resumo}</p>}
        </div>

        {dia === undefined && <p className="text-sm text-gray-600">a ler o relógio…</p>}

        {totalFases > 0 && (
          <div className="space-y-2.5 shrink-0">
            <div className="flex h-3 rounded-full overflow-hidden bg-[#0f0f0f] gap-px">
              {FASES_DO_SONO.map(f => {
                const m = s?.[f.chave] || 0;
                return m ? <div key={f.chave} style={{ width: `${(m / totalFases) * 100}%`, backgroundColor: f.cor }} /> : null;
              })}
            </div>
            {/* A percentagem vai no valor: em nota ficava numa linha só dela e
                as fases passavam a ocupar o dobro da altura. */}
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
              {FASES_DO_SONO.map(f => (
                <Medida key={f.chave} etiqueta={f.nome} cor={f.cor}
                  valor={`${hm(s?.[f.chave])} · ${Math.round(((s?.[f.chave] || 0) / totalFases) * 100)}%`} />
              ))}
            </div>
          </div>
        )}

        {/* As medidas repartem a altura que sobra: num painel alto as linhas
            afastam-se, num baixo encostam-se. É o mesmo que os painéis do
            relógio fazem. */}
        {dia && (
          <div className="grid grid-cols-1 gap-y-1.5 pt-3 border-t border-[#222]
            lg:flex-1 lg:content-between">
            {s?.need_min != null && (
              <Medida etiqueta="O corpo pedia" valor={hm(s.need_min)}
                nota={s.hours != null && s.need_min - s.hours * 60 > 10
                  ? `faltaram ${hm(s.need_min - s.hours * 60)}` : undefined} />
            )}
            {s?.awake_count != null && <Medida etiqueta="Despertares" valor={String(s.awake_count)} />}
            {sestas.map(n => (
              <Medida key={n.start} etiqueta={`Sesta às ${horaDe(n.start)}`} valor={hm(n.min)}
                nota={n.impact ? `+${n.impact} de bateria` : undefined} cor={COR_DA_SESTA} />
            ))}
            {/* O relógio conta minutos de sesta sem dizer quando — mostra-se o
                total em vez de deixar a linha de fora. */}
            {sestas.length === 0 && s?.nap_min ? <Medida etiqueta="Sestas" valor={hm(s.nap_min)} cor={COR_DA_SESTA} /> : null}
            {s?.avg_stress != null && <Medida etiqueta="Stress a dormir" valor={s.avg_stress.toFixed(0)} />}
            {s?.resp_avg != null && <Medida etiqueta="Respiração" valor={`${s.resp_avg.toFixed(0)}/min`} />}
            {s?.spo2_avg != null && (
              <Medida etiqueta="Oxigénio" valor={`${s.spo2_avg.toFixed(0)}%`}
                nota={s.spo2_min != null ? `mín ${s.spo2_min.toFixed(0)}%` : undefined} />
            )}
            {s?.skin_temp_dev_c != null && (
              <Medida etiqueta="Temperatura da pele"
                valor={`${s.skin_temp_dev_c > 0 ? '+' : ''}${s.skin_temp_dev_c.toFixed(1)} °C`}
                nota="face ao costume" />
            )}
            {dia.recovery.hrv != null && (
              <Medida etiqueta="HRV da noite" valor={`${dia.recovery.hrv} ms`}
                nota={limpo(dia.recovery.hrv_status) || undefined} />
            )}
            {dia.recovery.resting_hr != null && (
              <Medida etiqueta="FC em repouso" valor={`${dia.recovery.resting_hr} bpm`} />
            )}
            {dia.body_battery.start != null && (
              <Medida etiqueta="Body Battery ao acordar" valor={String(dia.body_battery.start)}
                nota={dia.body_battery.charged != null ? `+${dia.body_battery.charged} na noite` : undefined} />
            )}
            {dia.training.readiness != null && (
              <Medida etiqueta="Prontidão de manhã" valor={String(dia.training.readiness)}
                nota={limpo(dia.training.level) || undefined} />
            )}
          </div>
        )}

        {limpo(s?.feedback) && (
          <p className="text-xs text-gray-400 bg-white/[0.04] border border-[#222] rounded-xl
            px-3 py-2 shrink-0">
            {FEEDBACK_DO_SONO[s!.feedback!] || limpo(s?.feedback)}
          </p>
        )}

        {dia === null && (
          <p className="text-sm text-gray-600 pt-3 border-t border-[#222]">
            Esta noite não tem medições do relógio — o número vem da estimativa pelo uso
            do Mac. Com o relógio no pulso a dormir, aparecem aqui as fases, a pontuação,
            o HRV e o resto.
          </p>
        )}

        {entrada.notes && (
          <p className="text-sm text-gray-400 pt-3 border-t border-[#222]">{entrada.notes}</p>
        )}
      </div>
    </div>
  );
}

// A linha de cada noite vai das 18h da véspera à meia-noite seguinte: 30 horas,
// e não as 24 do costume. Num mostrador de 18h a 18h, a sesta das 18:17
// transbordava e dava a volta — aparecia no princípio da linha, antes da noite
// que tinha acontecido horas antes dela.
const LINHA_MINUTOS = 30 * 60;
const ATE_MEIA_NOITE = 1440 - RITMO_INICIO;   // das 18h da véspera à meia-noite

/** Uma hora escrita "hh:mm" não diz em que dia caiu. Quem se deita das 18h para
 *  cima deitou-se na véspera; tudo o resto é do próprio dia. */
function offsetDaHora(hhmmTexto: string | null) {
  if (!hhmmTexto) return null;
  const [h, m] = hhmmTexto.split(':').map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) return null;
  const min = h * 60 + m;
  return min >= RITMO_INICIO ? min - RITMO_INICIO : min + ATE_MEIA_NOITE;
}

/** As noites, uma por linha: vê-se logo a que horas se deitou, quanto dormiu,
 *  onde caíram as sestas do dia e — quando o relógio esteve no pulso — como a
 *  noite foi por dentro, com as fases a colorir a própria barra. */
function Noites({ entries, relogio, sestas, saidas, escolhida, aoEscolher }: {
  entries: SleepEntry[];
  relogio: Record<string, GarminHistoryPoint>;
  sestas: Record<string, GarminNap[]>;
  saidas: Record<string, NightOut>;
  escolhida: string | null;
  aoEscolher: (data: string) => void;
}) {
  const pos = (offset: number) => (offset / LINHA_MINUTOS) * 100;

  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] flex flex-col lg:h-full min-h-0">
      <div className="flex items-center justify-between gap-x-3 gap-y-1.5 flex-wrap p-4 border-b border-[#222] shrink-0">
        <h3 className="text-sm font-medium text-gray-300">As noites</h3>
        <div className="flex items-center gap-x-3 gap-y-1 flex-wrap text-[10px] text-gray-600">
          {FASES_DO_SONO.map(f => (
            <span key={f.chave} className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: f.cor }} />
              {f.nome}
            </span>
          ))}
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: COR_DA_SESTA }} /> sesta
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-gray-600" /> estimado
          </span>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {entries.length === 0 ? (
          <p className="p-6 text-center text-gray-600 text-sm">Sem noites neste período</p>
        ) : entries.map(e => {
          const g = relogio[e.date];
          const inicio = offsetDaHora(e.bedtime);
          // Acordar antes da hora a que se deitou é acordar no dia seguinte.
          let fim = offsetDaHora(e.wake_time);
          if (fim != null && inicio != null && fim <= inicio) fim += 1440;
          const fases = FASES_DO_SONO.map(f => ({ ...f, min: (g?.[f.chave] ?? null) as number | null }));
          const totalFases = fases.reduce((t, f) => t + (f.min || 0), 0);
          const esquerda = inicio != null ? Math.max(0, pos(inicio)) : null;
          // Uma noite que acabe depois da meia-noite seguinte sairia da faixa —
          // corta-se no fim em vez de transbordar por cima do que está ao lado.
          const largura = inicio != null && fim != null && esquerda != null
            ? Math.min(100 - esquerda, Math.max(1, pos(fim) - pos(inicio)))
            : null;
          // O minuto zero da linha são as 18h da véspera.
          const inicioDaLinha = +new Date(`${e.date}T00:00:00`) - ATE_MEIA_NOITE * 60_000;
          const saida = saidas[format(subDays(parseISO(e.date), 1), 'yyyy-MM-dd')];

          return (
            <button key={e.id} onClick={() => aoEscolher(e.date)}
              className={`w-full text-left flex items-center gap-3 px-4 py-2 hover:bg-white/5 ${
                escolhida === e.date ? 'bg-white/5' : ''}`}>
              <span className="w-16 shrink-0 text-[11px] text-gray-500 tabular-nums whitespace-nowrap">
                {format(parseISO(e.date), 'd MMM', { locale: pt })}
                {saida && (
                  <span className="ml-1" title={saida.drank
                    ? `saíste na véspera e bebeste${saida.drink_level ? ` ${NIVEIS_DE_BEBIDA[saida.drink_level]}` : ''}`
                    : 'saíste na véspera, sem beber'}>
                    {saida.drank ? '🍺' : '🌙'}
                  </span>
                )}
              </span>

              <span className="flex-1 min-w-0 relative h-4">
                {/* as marcas da meia-noite e do meio-dia, por trás da noite */}
                {[360, 720, 1080, 1440].map(o => (
                  <span key={o} className="absolute top-0 bottom-0 w-px bg-[#202020]"
                    style={{ left: `${pos(o)}%` }} />
                ))}
                {inicio != null && largura != null && (
                  <span className="absolute top-0.5 bottom-0.5 rounded-md overflow-hidden flex"
                    style={{ left: `${esquerda}%`, width: `${largura}%` }}>
                    {totalFases > 0
                      ? fases.map(f => f.min ? (
                          <span key={f.chave} style={{ width: `${(f.min / totalFases) * 100}%`, backgroundColor: f.cor }} />
                        ) : null)
                      : <span className="w-full bg-gray-600/70" />}
                  </span>
                )}

                {/* As sestas do dia, na mesma linha da noite e sempre depois
                    dela — são as horas que se seguiram a essa noite. */}
                {(sestas[e.date] || []).map(n => {
                  const esq = Math.max(0, pos((n.start - inicioDaLinha) / 60_000));
                  const largura = Math.min(100 - esq, Math.max(0.8, pos(n.min)));
                  return (
                    <span key={n.start} className="absolute top-1 bottom-1 rounded-sm"
                      title={`sesta às ${horaDe(n.start)} · ${hm(n.min)}`}
                      style={{ left: `${esq}%`, width: `${largura}%`, backgroundColor: COR_DA_SESTA }} />
                  );
                })}
              </span>

              <span className="w-12 shrink-0 text-right text-sm tabular-nums text-gray-200">
                {hm(e.hours * 60)}
              </span>
              <span className="w-11 shrink-0 text-right text-sm font-bold tabular-nums"
                style={{ color: corDaPontuacao(g?.sleep_score) }}>
                {g?.sleep_score ?? '—'}
              </span>
            </button>
          );
        })}
      </div>

      <div className="flex justify-between px-4 py-2 border-t border-[#222] text-[10px] text-gray-600 shrink-0">
        <span className="w-16" />
        <span className="flex-1 flex justify-between">
          {['18:00', '00:00', '06:00', '12:00', '18:00', '00:00'].map((h, i) => <span key={i}>{h}</span>)}
        </span>
        <span className="w-24 text-right">horas · pontuação</span>
      </div>
    </div>
  );
}

export default function SleepPage() {
  const [vista, setVista] = useState<'registos' | 'ritmo' | 'análise'>('registos');
  const [entries, setEntries] = useState<SleepEntry[]>([]);
  const [relogio, setRelogio] = useState<Record<string, GarminHistoryPoint>>({});
  // A noite que está aberta no painel. Por omissão a mais recente — é essa que
  // ele quer ver ao abrir a página.
  const [escolhida, setEscolhida] = useState<string | null>(null);
  const [period, setPeriod] = useState<number | 'all'>(30);
  // Saídas à noite, pela data em que a noite começou.
  const [saidas, setSaidas] = useState<Record<string, NightOut>>({});

  useEffect(() => { loadData(); }, [period]);

  const mudaSaida = (n: NightOutDay) => setSaidas(prev => {
    const resto = { ...prev };
    if (n.went_out) resto[n.date] = n; else delete resto[n.date];
    return resto;
  });

  async function loadData() {
    const isAll = period === 'all';
    const listParams = isAll
      ? undefined
      : { start_date: format(subDays(new Date(), period), 'yyyy-MM-dd'), end_date: format(new Date(), 'yyyy-MM-dd') };
    setEntries(await sleepApi.list(listParams));
    // A pontuação de cada noite vem do relógio, não de estrelas postas à mão.
    garminApi.history(isAll ? 365 : Math.max(7, period as number))
      .then(h => setRelogio(Object.fromEntries(h.map(p => [p.date, p]))))
      .catch(() => setRelogio({}));
    nightsApi.list(isAll ? 3650 : (period as number) + 1)
      .then(l => setSaidas(Object.fromEntries(l.map(n => [n.date, n]))))
      .catch(() => setSaidas({}));
  }

  const noite = entries.find(e => e.date === escolhida) || entries[0] || null;

  // Os cartões contam só as noites que o relógio mediu: uma estimativa pelo uso
  // do Mac não tem pontuação nenhuma, e misturá-la com as medidas dava uma média
  // que não é de coisa nenhuma.
  const medidas = entries
    .map(e => relogio[e.date])
    .filter((g): g is GarminHistoryPoint => !!g && g.sleep_hours != null);
  const media = (vals: number[]) => vals.length
    ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  const horasMedias = media(medidas.map(g => g.sleep_hours!));
  // O costume dele, para a noite aberta se comparar com alguma coisa. Com menos
  // de três noites medidas não há costume nenhum — mediana de duas é ruído.
  const ordenadas = medidas.map(g => g.sleep_hours!).sort((a, b) => a - b);
  const medianaHoras = ordenadas.length >= 3
    ? (ordenadas.length % 2 ? ordenadas[(ordenadas.length - 1) / 2]
        : (ordenadas[ordenadas.length / 2 - 1] + ordenadas[ordenadas.length / 2]) / 2)
    : null;
  const pontuacoes = medidas.map(g => g.sleep_score).filter((s): s is number => s != null);
  const pontuacaoMedia = pontuacoes.length ? Math.round(media(pontuacoes)!) : null;

  // As sestas são sono que nenhuma noite conta. Só aparecem quando existem: num
  // período sem nenhuma, um cartão a dizer "—" era ruído.
  const sestas = sestasPorDia(relogio);
  const diasComSesta = medidas.filter(g => (g.nap_min || 0) > 0);
  const minutosDeSesta = diasComSesta.reduce((t, g) => t + (g.nap_min || 0), 0);
  const sestaMedia = diasComSesta.length ? minutosDeSesta / diasComSesta.length : null;


  return (
    <div className="lg:h-[calc(100dvh-4rem)] lg:flex lg:flex-col lg:overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap mb-4 lg:mb-6 lg:shrink-0">
        <div>
          <h2 className="text-2xl font-bold">Sono</h2>
        </div>
        {/* No telemóvel os dois grupos passam para a linha de baixo e rolam */}
        <div className="flex items-center gap-2 sm:gap-3 flex-wrap min-w-0 max-w-full">
          <div className="flex items-center gap-1 bg-[#161616] rounded-xl border border-[#222] p-1 shrink-0">
            {(['registos', 'ritmo', 'análise'] as const).map(v => (
              <button key={v} onClick={() => setVista(v)}
                className={`shrink-0 px-2.5 sm:px-3 py-1.5 text-xs rounded-lg capitalize transition-all ${
                  vista === v ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-white'
                }`}>
                {v}
              </button>
            ))}
          </div>
          <div className={`items-center gap-1 bg-[#161616] rounded-xl border border-[#222] p-1 shrink-0 ${vista === 'registos' ? 'flex' : 'hidden'}`}>
            {([7, 14, 30, 90, 'all'] as const).map(d => (
              <button key={d} onClick={() => setPeriod(d)}
                className={`shrink-0 px-2.5 sm:px-3 py-1.5 text-xs rounded-lg transition-all ${
                  period === d ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-white'
                }`}>
                {d === 'all' ? 'Tudo' : `${d}d`}
              </button>
            ))}
          </div>
        </div>
      </div>

      {vista === 'ritmo' && <RitmoDoSono />}
      {vista === 'análise' && <AnaliseDasNoites />}

      {/* Os cartões são só do relógio: uma noite estimada pelo Mac não tem
          pontuação, e entrar para as médias dava um número de coisa nenhuma. */}
      {vista === 'registos' && (
        <div className={`grid grid-cols-2 sm:grid-cols-3 gap-4 mb-4 lg:mb-6 lg:shrink-0 ${
          sestaMedia != null ? 'lg:grid-cols-4' : 'lg:grid-cols-3'}`}>
          <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
            <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
              <Moon size={14} className="text-purple-400" /> Média
            </div>
            <p className="text-2xl font-bold tabular-nums">
              {horasMedias != null ? hm(horasMedias * 60) : '—'}
            </p>
            {sestaMedia != null && (
              <p className="text-xs text-gray-500 mt-1">
                {hm(horasMedias! * 60 + minutosDeSesta / medidas.length)} com as sestas
              </p>
            )}
          </div>

          {sestaMedia != null && (
            <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
              <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
                <Sun size={14} style={{ color: COR_DA_SESTA }} /> Sestas
              </div>
              <p className="text-2xl font-bold tabular-nums">{hm(sestaMedia)}</p>
              <p className="text-xs text-gray-500 mt-1">
                em {diasComSesta.length} de {medidas.length} dias
              </p>
            </div>
          )}

          <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
            <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
              <Watch size={14} className="text-sky-400" /> Pontuação
            </div>
            <p className="text-2xl font-bold tabular-nums" style={{ color: corDaPontuacao(pontuacaoMedia) }}>
              {pontuacaoMedia ?? '—'}<span className="text-sm text-gray-500">/100</span>
            </p>
          </div>

          <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
            <p className="text-xs text-gray-500 mb-2">Noites medidas</p>
            <p className="text-2xl font-bold tabular-nums">{medidas.length}</p>
          </div>
        </div>
      )}

      {vista === 'registos' && (
      <div className="flex flex-col lg:flex-row gap-4 lg:gap-6 lg:flex-1 lg:min-h-0">
        {/* A noite escolhida, com tudo o que o relógio mediu */}
        {noite && (
          <div className="lg:w-[330px] xl:w-[380px] shrink-0 lg:min-h-0">
            <ANoite entrada={noite} sestas={sestas[noite.date] || []} mediana={medianaHoras} aoMudarSaida={mudaSaida} />
          </div>
        )}

        {/* Uma linha por noite: onde ela caiu no relógio, como foi por dentro,
            quanto durou e quanto valeu. O gráfico de barras e a lista mostravam
            as mesmas horas duas vezes e nenhum deles dizia isto. */}
        <div className="lg:flex-1 lg:min-h-0">
          <Noites entries={entries} relogio={relogio} sestas={sestas} saidas={saidas}
            escolhida={noite?.date || null} aoEscolher={setEscolhida} />
        </div>
      </div>
      )}

    </div>
  );
}
