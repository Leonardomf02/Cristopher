import { useEffect, useState } from 'react';
import { format, parseISO } from 'date-fns';
import { pt } from 'date-fns/locale';
import {
  Activity, BatteryCharging, ChevronLeft, ChevronRight, CloudOff, Footprints, Heart,
  HeartPulse, Moon, RefreshCw, Watch, Zap,
} from 'lucide-react';
import {
  Area, Bar, CartesianGrid, Cell, ComposedChart, Line,
  ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { garminApi, type GarminActivity, type GarminBaseline, type GarminBaselines, type GarminDay, type GarminDayView, type GarminHistoryPoint, type GarminHrZones, type GarminSeries, type GarminReading, type GarminRelation, type GarminSnapshot as GarminSnapshotT, type GarminStatus } from '../api';

const CINZA = '#222';
const FASES = [
  { chave: 'deep_min', nome: 'Profundo', cor: '#4c6ef5' },
  { chave: 'light_min', nome: 'Leve', cor: '#748ffc' },
  { chave: 'rem_min', nome: 'REM', cor: '#9775fa' },
  { chave: 'awake_min', nome: 'Acordado', cor: '#495057' },
] as const;

const ESTADO_HRV: Record<string, { texto: string; cor: string }> = {
  BALANCED: { texto: 'equilibrado', cor: 'text-green-400' },
  UNBALANCED: { texto: 'desequilibrado', cor: 'text-amber-400' },
  LOW: { texto: 'baixo', cor: 'text-orange-400' },
  POOR: { texto: 'mau', cor: 'text-red-400' },
};

function horas(h: number | null | undefined) {
  if (h == null) return '—';
  const m = Math.round(h * 60);
  return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}`;
}

function minutos(m: number | null | undefined) {
  if (m == null) return '—';
  return m >= 60 ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}` : `${m}min`;
}

function emHoras(m: number | null | undefined) {
  return m == null ? null : +(m / 60).toFixed(2);
}

/** O alvo semanal de minutos de intensidade da Garmin (vigoroso conta a dobrar). */
const ALVO_INTENSIDADE = 150;

/** As cores com que a Garmin lê a prontidão. Um número de 0 a 100 sozinho não
 *  diz se 68 é bom — a cor diz. */
function corDaProntidao(v: number | null | undefined) {
  if (v == null) return '#495057';
  if (v >= 75) return '#4ade80';
  if (v >= 50) return '#f59e0b';
  if (v >= 25) return '#fb923c';
  return '#f43f5e';
}

function hora(iso: string | null | undefined) {
  if (!iso) return '—';
  try { return format(parseISO(iso), 'HH:mm'); } catch { return '—'; }
}

/** A Garmin manda "none", "unknown" e "UNKNOWN" nos campos que ainda não
 *  calculou — mostrá-los é pior do que não mostrar nada. */
function texto(v: string | null | undefined) {
  if (!v) return null;
  const limpo = v.replace(/_\d+$/, '').replace(/_/g, ' ').trim().toLowerCase();
  return limpo && limpo !== 'none' && limpo !== 'unknown' ? limpo : null;
}

function ritmo(a: GarminActivity) {
  if (!a.distance_m || !a.duration_s || a.distance_m < 100) return null;
  const segPorKm = a.duration_s / (a.distance_m / 1000);
  return `${Math.floor(segPorKm / 60)}:${String(Math.round(segPorKm % 60)).padStart(2, '0')}/km`;
}

function Cartao({ icone, titulo, valor, sub, cor = 'text-white' }: {
  icone: React.ReactNode; titulo: string; valor: string; sub?: string; cor?: string;
}) {
  return (
    <div className="bg-[#161616] rounded-2xl p-3.5 lg:p-4 border border-[#222]">
      <div className="flex items-center gap-2 text-[11px] text-gray-500 mb-1.5">{icone} {titulo}</div>
      <p className={`text-xl lg:text-2xl font-bold leading-none ${cor}`}>{valor}</p>
      {sub && <p className="text-[10px] text-gray-600 mt-1.5 truncate">{sub}</p>}
    </div>
  );
}

/** Nas Medições os painéis vivem dentro da altura do ecrã: o cabeçalho fica fixo
 *  e o corpo estica ou rola dentro de si, para a página não crescer. Na Leitura,
 *  onde a grelha não fixa alturas, isto não faz diferença nenhuma. */
function Painel({ titulo, extra, children }: { titulo: string; extra?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 flex flex-col h-full min-h-0">
      <div className="flex items-center justify-between gap-3 mb-3 shrink-0">
        <h3 className="text-sm font-medium text-gray-300 truncate">{titulo}</h3>
        {extra}
      </div>
      <div className="flex flex-col flex-1 min-h-0 lg:overflow-y-auto">{children}</div>
    </div>
  );
}

/** As métricas lentas do relógio não existem no primeiro dia — dizer quanto falta
 *  é melhor do que mostrar uma caixa vazia sem explicação. */
function Aquecimento({ estado }: { estado: GarminStatus }) {
  if (estado.has_hrv || estado.nights_for_hrv <= 0) return null;
  return (
    <div className="bg-sky-500/10 border border-sky-500/20 rounded-2xl p-4 text-sm text-sky-200/90">
      <span className="font-medium">Faltam {estado.nights_for_hrv} noites</span> para o relógio ter
      linha de base de HRV. Até lá não há estado de HRV nem prontidão para treinar —
      já leva {estado.nights} {estado.nights === 1 ? 'noite medida' : 'noites medidas'}.
    </div>
  );
}

/** O relógio não tem Wi-Fi: os dados só chegam aqui depois de passarem pelo
 *  telemóvel. Uma noite sem sono é quase sempre isso — dados ainda no pulso — e
 *  não vale a pena afirmar que ele não o usou a dormir sem saber. As leituras
 *  paradas há horas com o dia a decorrer distinguem os dois casos. */
function SemSono({ cobertura }: { cobertura: GarminDayView['coverage'] }) {
  const porSincronizar = cobertura.hours_ago != null && cobertura.hours_ago >= 2;
  return (
    <div className="text-sm text-gray-500 space-y-2 shrink-0">
      {porSincronizar ? (
        <>
          <p>Ainda não chegou aqui o sono desta noite.</p>
          <p className="text-xs text-gray-600">
            A última leitura que a Garmin tem é das {hora(cobertura.to)}, há {Math.round(cobertura.hours_ago!)}h.
            O relógio não tem Wi-Fi — abre o Garmin Connect no telemóvel com ele por perto
            e volta a carregar em Sincronizar.
          </p>
        </>
      ) : (
        <>
          <p>Esta noite não tem sono medido.</p>
          {cobertura.from && (
            <p className="text-xs text-gray-600">
              Houve leituras entre as {hora(cobertura.from)} e as {hora(cobertura.to)} — se dormiste
              com ele fora dessa janela, os dados podem ainda não ter sincronizado.
            </p>
          )}
        </>
      )}
      <p className="text-xs text-gray-600">
        Até lá, o sono deste dia na página do Sono é a estimativa pelo uso do Mac.
      </p>
    </div>
  );
}

const QUALIFICADOR: Record<string, string> = {
  EXCELLENT: 'excelente', GOOD: 'bom', FAIR: 'razoável', POOR: 'fraco',
};

function corDoScore(s: number | null) {
  if (s == null) return 'text-gray-400';
  if (s >= 80) return 'text-green-400';
  if (s >= 70) return 'text-lime-400';
  if (s >= 60) return 'text-amber-400';
  return 'text-red-400';
}

function Fases({ dia }: { dia: GarminDay }) {
  const total = FASES.reduce((s, f) => s + (dia.sleep[f.chave] || 0), 0);
  if (!total) return null;
  return (
    <div className="space-y-2.5">
      <div className="flex h-2.5 rounded-full overflow-hidden bg-[#0f0f0f] gap-px">
        {FASES.map(f => {
          const m = dia.sleep[f.chave] || 0;
          return m ? <div key={f.chave} style={{ width: `${(m / total) * 100}%`, backgroundColor: f.cor }} /> : null;
        })}
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-1.5 text-xs">
        {FASES.map(f => {
          const m = dia.sleep[f.chave] || 0;
          return (
            <span key={f.chave} className="flex items-baseline gap-1.5">
              <span className="w-2 h-2 rounded-full shrink-0 self-center" style={{ backgroundColor: f.cor }} />
              <span className="text-gray-500">{f.nome}</span>
              <span className="text-gray-200 tabular-nums">{minutos(m)}</span>
              <span className="text-gray-600 tabular-nums">{Math.round((m / total) * 100)}%</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

/** Os dois minutos parado que ele grava à mão. Vale um painel próprio porque é a
 *  única leitura de HRV que não espera pelas 19 noites de linha de base, e
 *  porque é ele que escolhe o momento — dá para medir o antes e o depois de
 *  alguma coisa concreta. */
function Snapshots({ medicoes }: { medicoes: GarminSnapshotT[] }) {
  return (
    <div className="space-y-3 shrink-0">
      {medicoes.map(m => (
        <div key={m.uuid} className="space-y-3">
          <div className="flex items-baseline justify-between gap-3 flex-wrap">
            <p className="text-sm text-gray-300">
              {m.name?.replace(/^Health Snapshot\s*-\s*/i, '') || 'Medição'}
              <span className="text-gray-600 text-xs ml-2">
                {format(parseISO(m.date), 'd/M', { locale: pt })} · {hora(m.start)}
              </span>
            </p>
            <span className="text-[11px] text-gray-600">
              {m.duration_s ? `${Math.round(m.duration_s / 60)} min parado` : ''}
            </span>
          </div>
          <div className="grid grid-cols-1 gap-y-2">
            {m.hrv_rmssd != null && (
              <Detalhe etiqueta="HRV (RMSSD)" valor={`${m.hrv_rmssd} ms`}
                nota={m.hrv_sdrr != null ? `SDRR ${m.hrv_sdrr}` : undefined} />
            )}
            {m.hr_avg != null && (
              <Detalhe etiqueta="Frequência cardíaca" valor={`${Math.round(m.hr_avg)} bpm`}
                nota={m.hr_max != null ? `máx ${Math.round(m.hr_max)}` : undefined} />
            )}
            {m.spo2_avg != null && (
              <Detalhe etiqueta="Oxigénio" valor={`${Math.round(m.spo2_avg)}%`}
                nota={m.spo2_min != null ? `mín ${Math.round(m.spo2_min)}%` : undefined} />
            )}
            {m.resp_avg != null && (
              <Detalhe etiqueta="Respiração" valor={`${Math.round(m.resp_avg)}/min`}
                nota={m.resp_max != null ? `máx ${Math.round(m.resp_max)}` : undefined} />
            )}
            {m.stress_avg != null && (
              <Detalhe etiqueta="Stress" valor={String(Math.round(m.stress_avg))}
                nota={m.stress_max != null ? `máx ${Math.round(m.stress_max)}` : undefined} />
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

const CORES_TEMA: Record<string, string> = {
  doenca: 'text-red-400', 'sono-curto': 'text-amber-400', recuperacao: 'text-orange-400',
  stress: 'text-amber-400', parado: 'text-sky-400', bom: 'text-green-400', misto: 'text-gray-300',
};

/** A régua é a mediana das próprias semanas dele — por isso um facto forte quer
 *  dizer "fora do teu costume", não "fora de uma tabela". */
function Factos({ leitura }: { leitura: GarminReading }) {
  const destaques = leitura.facts.filter(f => f.kind !== 'dia');
  const contados = leitura.facts.filter(f => f.kind === 'dia');

  const linha = (f: GarminReading['facts'][number]) => (
    <li key={f.key} className="text-sm flex gap-3">
      <span className={`mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 ${
        f.kind === 'padrao' ? 'bg-red-400'
          : f.good === false ? 'bg-amber-400' : f.good ? 'bg-green-400' : 'bg-gray-600'}`} />
      <span className={f.kind === 'dia' ? 'text-gray-400' : 'text-gray-300'}>
        {f.text}
        {f.z != null && <span className="text-gray-600 text-xs ml-1.5">{Math.abs(f.z).toFixed(1)}σ</span>}
      </span>
    </li>
  );

  // As duas listas são coisas diferentes e sem rótulo nas duas a divisão não se
  // percebia: em cima o que foi comparado com alguma coisa (o costume dele ou um
  // alvo do relógio), em baixo o dia como foi, que não se compara com nada.
  const rotulo = (texto: string, dica: string, extra = '') => (
    <p title={dica} className={`text-[11px] text-gray-600 mb-2.5 shrink-0 ${extra}`}>{texto}</p>
  );

  return (
    <>
      {destaques.length > 0 && (
        <>
          {contados.length > 0 && rotulo('o que saiu do costume',
            'medidas que fugiram ao teu histórico ou ficaram longe de um alvo do relógio')}
          <ul className="space-y-2.5 shrink-0">{destaques.map(linha)}</ul>
        </>
      )}
      {contados.length > 0 && (
        <>
          {rotulo('o dia, como foi', 'o que o relógio mediu nesse dia, sem comparação com nada',
            destaques.length ? 'mt-4' : '')}
          <ul className="space-y-2.5 shrink-0">{contados.map(linha)}</ul>
        </>
      )}
    </>
  );
}

/** Correlação de Spearman com teste de significância: só sai o que sobrevive ao
 *  teste, para não confundir coincidência com descoberta. */
function Relacoes({ relacoes }: { relacoes: GarminRelation[] }) {
  return (
    <ul className="space-y-3 shrink-0">
      {relacoes.map(r => (
        <li key={r.key} className="text-sm">
          <p className="text-gray-300">{r.text}</p>
          <p className="text-[11px] text-gray-600 mt-0.5 tabular-nums">
            ρ {r.rho > 0 ? '+' : ''}{r.rho} · p {r.p < 0.001 ? '<0,001' : r.p.toString().replace('.', ',')} · {r.n} dias
          </p>
        </li>
      ))}
    </ul>
  );
}

/** Etiqueta à esquerda, valor à direita, na mesma linha — o estilo das faixas de
 *  stress, que é o que se lê de relance e ocupa metade da altura de ter a
 *  etiqueta por cima do valor. */
function Detalhe({ etiqueta, valor, nota, cor = 'text-gray-200' }: {
  etiqueta: string; valor: string; nota?: string; cor?: string;
}) {
  return (
    <div className="flex items-baseline gap-2 text-sm min-w-0">
      <span className="text-gray-500 truncate">{etiqueta}</span>
      <span className={`ml-auto tabular-nums whitespace-nowrap ${cor}`}>
        {valor}
        {/* O ponto é obrigatório: dois números colados ("+68" e "6h26") liam-se
            como um só ("+686h26"), e um espaço sozinho não os separava. */}
        {nota && <span className="text-[11px] text-gray-500"> · {nota}</span>}
      </span>
    </div>
  );
}

/** Quanto ele dormiu de sesta nesse dia. A sesta não vem no sono: são os eventos
 *  do body battery que sabem a que horas foi. O `nap_min` só dá o total, e fica
 *  como rede para os dias em que os eventos não vieram. */
function minutosDeSestas(dia: GarminDay, series: GarminSeries) {
  const sestas = series.events.filter(e => e.kind === 'sesta');
  return sestas.length
    ? Math.round(sestas.reduce((t, e) => t + (e.end - e.start) / 60000, 0))
    : (dia.sleep.nap_min || 0);
}

function NoitePassada({ dia, series }: { dia: GarminDay; series: GarminSeries }) {
  const s = dia.sleep;
  const emFalta = s.need_min != null && s.hours != null ? Math.round(s.need_min - s.hours * 60) : null;
  const sestas = series.events.filter(e => e.kind === 'sesta');
  const minutosDeSesta = minutosDeSestas(dia, series);
  const detalhes = [
    s.need_min != null && (
      <Detalhe key="need" etiqueta="Precisavas de" valor={minutos(s.need_min)}
        nota={emFalta && emFalta > 10 ? `faltaram ${minutos(emFalta)}` : emFalta && emFalta < -10 ? 'de sobra' : undefined} />
    ),
    s.awake_count != null && <Detalhe key="awake" etiqueta="Despertares" valor={String(s.awake_count)} />,
    s.resp_avg != null && <Detalhe key="resp" etiqueta="Respiração" valor={`${s.resp_avg.toFixed(0)}/min`} />,
    s.avg_stress != null && <Detalhe key="stress" etiqueta="Stress a dormir" valor={s.avg_stress.toFixed(0)} />,
    s.spo2_avg != null && <Detalhe key="spo2" etiqueta="Oxigénio" valor={`${s.spo2_avg.toFixed(0)}%`}
      nota={s.spo2_min != null ? `mín ${s.spo2_min.toFixed(0)}%` : undefined} />,
    dia.recovery.resting_hr != null && <Detalhe key="rhr" etiqueta="FC em repouso" valor={`${dia.recovery.resting_hr} bpm`} />,
    ...sestas.map((e, i) => (
      <Detalhe key={`nap${i}`} etiqueta={`Sesta às ${format(new Date(e.start), 'HH:mm')}`}
        valor={minutos(Math.round((e.end - e.start) / 60000))}
        nota={e.impact ? `+${e.impact} de bateria` : undefined} />
    )),
    sestas.length === 0 && s.nap_min
      ? <Detalhe key="nap" etiqueta="Sestas" valor={minutos(s.nap_min)} /> : null,
  ].filter(Boolean);

  return (
    // shrink-0: dentro de um painel de altura fixa, um filho de flex encolhe
    // abaixo do conteúdo e corta-o em silêncio, sem sequer dar scroll.
    <div className="space-y-4 shrink-0">
      {/* Os três números na mesma linha, e por isso as etiquetas são curtas: com
          "pontuação · excelente" e "de sesta · 9h39 ao todo" por baixo dos
          números, a sesta não cabia e caía para uma linha só dela. O sono ao
          todo vai no cabeçalho do painel: aqui, uma linha de texto a mais é a
          diferença entre a coluna caber e o painel de baixo passar a rolar. */}
      <div>
        <div className="flex items-end">
          <div className="flex-1 min-w-0">
            <p className="text-2xl font-bold leading-none tabular-nums">{horas(s.hours)}</p>
            <p className="text-[11px] text-gray-600 mt-1.5">a dormir</p>
          </div>
          {s.score != null && (
            <div className="flex-1 min-w-0 pl-3 border-l border-[#222]">
              <p className={`text-2xl font-bold leading-none tabular-nums ${corDoScore(s.score)}`}>{s.score}</p>
              <p className="text-[11px] text-gray-600 mt-1.5 truncate">
                {s.qualifier ? QUALIFICADOR[s.qualifier] || s.qualifier.toLowerCase() : 'pontuação'}
              </p>
            </div>
          )}
          {/* A sesta é sono que a noite não conta: 7h15 na cama mais 2h24 à tarde
              são 9h39 de sono, e o painel dizia só as 7h15. */}
          {minutosDeSesta > 0 && (
            <div className="flex-1 min-w-0 pl-3 border-l border-[#222]">
              <p className="text-2xl font-bold leading-none tabular-nums"
                style={{ color: BLOCOS_DO_DIA.sesta.cor }}>{minutos(minutosDeSesta)}</p>
              <p className="text-[11px] text-gray-600 mt-1.5">de sesta</p>
            </div>
          )}
        </div>
      </div>

      <Fases dia={dia} />

      {detalhes.length > 0 && (
        <div className="grid grid-cols-1 gap-y-1.5 pt-2.5 border-t border-[#222]">
          {detalhes}
        </div>
      )}
    </div>
  );
}

/** A curva do Body Battery e do stress. Só a curva: os números que a explicam
 *  vivem no painel ao lado, para este gráfico ter o mesmo tamanho do da
 *  frequência cardíaca. */
function CurvaDoDia({ series }: { series: GarminSeries }) {
  const stressPorInstante = new Map(series.stress);
  const pontos = series.body_battery.map(([ts, v]) => ({
    hora: format(new Date(ts), 'HH:mm'),
    bateria: v,
    stress: stressPorInstante.get(ts) ?? null,
  }));
  if (pontos.length < 2) return <p className="text-sm text-gray-600">ainda sem leituras suficientes hoje</p>;
  return (
    <div className="flex flex-col min-h-0 lg:flex-1">
      <div className="h-[200px] lg:h-0 lg:flex-1">
      <ResponsiveContainer width="100%" height="100%">
        {/* ComposedChart, não AreaChart: dentro de um AreaChart o Recharts ignora
            a Line, e o stress não aparecia nem no gráfico nem ao passar por cima. */}
        <ComposedChart data={pontos}>
          <defs>
            <linearGradient id="gBateria" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.35} />
              <stop offset="95%" stopColor="#38bdf8" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={CINZA} />
          <XAxis dataKey="hora" stroke="#555" fontSize={11} interval="preserveStartEnd" minTickGap={40} />
          <YAxis stroke="#555" fontSize={11} domain={[0, 100]} width={30} />
          <Tooltip
            contentStyle={{ background: '#0f0f0f', border: `1px solid ${CINZA}`, borderRadius: 12, fontSize: 12 }}
            labelStyle={{ color: '#9ca3af', marginBottom: 4 }}
            formatter={(v: any, nome: string) => [v == null ? '—' : v, nome]} />
          <Area type="monotone" dataKey="bateria" name="Body Battery" stroke="#38bdf8"
            fill="url(#gBateria)" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="stress" name="Stress" stroke="#f59e0b"
            strokeWidth={1.5} dot={false} connectNulls />
        </ComposedChart>
      </ResponsiveContainer>
      </div>
      <div className="flex items-center gap-4 mt-2 text-xs text-gray-500 shrink-0">
        <span className="flex items-center gap-1.5"><span className="w-2.5 h-0.5 rounded bg-sky-400" /> Body Battery</span>
        <span className="flex items-center gap-1.5"><span className="w-2.5 h-0.5 rounded bg-amber-500" /> Stress</span>
      </div>
    </div>
  );
}

/** Os números que explicam a curva ao lado: onde a bateria começou e acabou, o
 *  que carregou e gastou, quanto devolveu cada sono e cada sesta, e o dia
 *  repartido pelas quatro faixas de stress. */
function NumerosDoDia({ dia, series }: { dia: GarminDay; series: GarminSeries }) {
  const ganhos = series.events.filter(e => (e.impact ?? 0) > 0);
  // Uma medida por linha. Em duas colunas lia-se "Body Battery 93 → 40  Stress
  // médio 24 · máx 94" atravessado, com quatro números na mesma linha e nenhuma
  // etiqueta encostada ao seu valor.
  //
  // content-between: cinco linhas de texto num painel alto deixavam meio painel
  // vazio por baixo. Assim as linhas repartem a altura toda, e num ecrã curto
  // encostam-se umas às outras e é o corpo do Painel que rola.
  return (
    <div className="grid grid-cols-1 gap-y-1.5 lg:h-full lg:content-between shrink-0">
      {dia.body_battery.start != null && dia.body_battery.end != null && (
        <Detalhe etiqueta="Body Battery" valor={`${dia.body_battery.start} → ${dia.body_battery.end}`}
          cor="text-sky-400" />
      )}
      {dia.stress.avg != null && (
        <Detalhe etiqueta="Stress médio" valor={String(dia.stress.avg)}
          nota={dia.stress.max != null ? `máx ${dia.stress.max}` : undefined} cor="text-amber-400" />
      )}
      {dia.body_battery.charged != null && (
        <Detalhe etiqueta="Carregou" valor={`+${dia.body_battery.charged}`} cor="text-green-400/90" />
      )}
      {dia.body_battery.drained != null && (
        <Detalhe etiqueta="Gastou" valor={`−${dia.body_battery.drained}`} cor="text-red-400/90" />
      )}
      {ganhos.map((e, i) => (
        <Detalhe key={i} etiqueta={e.kind === 'sesta' ? 'Na sesta' : 'A dormir'}
          valor={`+${e.impact}`}
          nota={minutos(Math.round((e.end - e.start) / 60000))} />
      ))}
      <div className="pt-1"><FaixasDeStress dia={dia} /></div>

      {/* O que o dia teve de movimento. Só aparece em ecrãs com altura para isso:
          num portátil de 800px este painel já está cheio com a bateria e o
          stress, e acrescentar isto obrigaria a rolar — que é o que se quer
          evitar aqui. */}
      {/* Duas colunas e etiquetas curtas: a coluna é estreita e um "Minutos
          intensos" a toda a largura empurrava o resto para fora do painel. */}
      <div className="hidden [@media(min-height:860px)]:grid grid-cols-2 gap-x-5
        gap-y-2 pt-2.5 border-t border-[#222]">
        {dia.activity.steps != null && (
          <Detalhe etiqueta="Passos" valor={dia.activity.steps.toLocaleString('pt-PT')} />
        )}
        {dia.activity.distance_m != null && (
          <Detalhe etiqueta="Distância" valor={`${(dia.activity.distance_m / 1000).toFixed(1)} km`} />
        )}
        {dia.activity.calories != null && (
          <Detalhe etiqueta="Calorias" valor={dia.activity.calories.toLocaleString('pt-PT')} />
        )}
        {(dia.activity.moderate_min != null || dia.activity.vigorous_min != null) && (
          <Detalhe etiqueta="Intensos"
            valor={minutos((dia.activity.moderate_min || 0) + (dia.activity.vigorous_min || 0) * 2)} />
        )}
        {dia.training.readiness != null && (
          <Detalhe etiqueta="Prontidão" valor={String(dia.training.readiness)} />
        )}
        {dia.training.vo2max != null && (
          <Detalhe etiqueta="VO2 máx" valor={dia.training.vo2max.toFixed(0)} />
        )}
        {dia.training.recovery_min != null && (
          <Detalhe etiqueta="Recuperação" valor={minutos(dia.training.recovery_min)} />
        )}
      </div>
    </div>
  );
}

// ── as peças dos gráficos do histórico ───────────────────────────

const TOOLTIP = { background: '#0f0f0f', border: `1px solid ${CINZA}`, borderRadius: 12, fontSize: 12 };

/** Altura fixa em vez de `flex-1`: no Histórico a grelha é `auto-rows-min` e
 *  são dez painéis — a esticar, cada linha ficava com a altura do painel mais
 *  alto dela. */
function GraficoBox({ children }: { children: React.ReactElement }) {
  return (
    <div className="h-[200px] lg:h-[220px] shrink-0">
      <ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer>
    </div>
  );
}

function SemDados({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-gray-600 shrink-0">{children}</p>;
}

/** A régua por baixo do gráfico, em texto. Diz de onde veio a faixa — um palpite
 *  feito de doze noites dele não é o mesmo que a linha de base do relógio. */
function NotaDaFaixa({ regua, minimo, unidade = '', o = 'a faixa' }:
  { regua?: GarminBaseline; minimo: number; unidade?: string; o?: string }) {
  if (!regua) return null;
  if (regua.median == null) {
    return (
      <p className="text-[10px] text-gray-600 mt-2 shrink-0">
        faltam {minimo - regua.n} {minimo - regua.n === 1 ? 'dia medido' : 'dias medidos'} para haver {o}
      </p>
    );
  }
  return (
    <p className="text-[10px] text-gray-600 mt-2 shrink-0">
      {regua.source === 'garmin'
        ? `faixa do relógio · ${regua.low}–${regua.high}${unidade}`
        : `o teu costume em ${regua.n} dias · ${regua.low}–${regua.high}${unidade}`}
    </p>
  );
}

/** A faixa e a mediana desenhadas dentro do gráfico. São dois elementos soltos
 *  porque o Recharts só aceita filhos que ele próprio conheça. */
function faixaDe(regua: GarminBaseline | undefined, cor: string, eixo?: string) {
  if (!regua || regua.median == null) return null;
  const y = eixo ? { yAxisId: eixo } : {};
  return [
    <ReferenceArea key="faixa" {...y} y1={regua.low!} y2={regua.high!}
      fill={cor} fillOpacity={0.07} stroke="none" ifOverflow="extendDomain" />,
    <ReferenceLine key="mediana" {...y} y={regua.median} stroke={cor} strokeOpacity={0.45}
      strokeDasharray="4 4" ifOverflow="extendDomain" />,
  ];
}

const NIVEIS_DE_STRESS = [
  { chave: 'rest_min', nome: 'Repouso', cor: '#38bdf8' },
  { chave: 'low_min', nome: 'Baixo', cor: '#4ade80' },
  { chave: 'medium_min', nome: 'Médio', cor: '#f59e0b' },
  { chave: 'high_min', nome: 'Alto', cor: '#f43f5e' },
] as const;

/** As quatro faixas de stress do dia, como a Garmin as conta: repouso, baixo,
 *  médio e alto. Vive por baixo da curva do stress em vez de num painel próprio —
 *  é a mesma coisa contada de outra maneira, e assim sobra altura para o gráfico. */
function FaixasDeStress({ dia }: { dia: GarminDay }) {
  const partes = NIVEIS_DE_STRESS.map(n => ({ ...n, min: dia.stress[n.chave] || 0 }));
  const total = partes.reduce((s, p) => s + p.min, 0);
  if (!total) return null;

  return (
    <div className="space-y-1.5">
      <div className="flex h-1.5 rounded-full overflow-hidden bg-[#0f0f0f] gap-px">
        {partes.map(p => p.min ? (
          <div key={p.chave} style={{ width: `${(p.min / total) * 100}%`, backgroundColor: p.cor }} />
        ) : null)}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs">
        {partes.map(p => (
          <span key={p.chave} className="flex items-baseline gap-1.5">
            <span className="w-2 h-2 rounded-full shrink-0 self-center" style={{ backgroundColor: p.cor }} />
            <span className="text-gray-500">{p.nome}</span>
            <span className="text-gray-200 tabular-nums ml-auto">{minutos(p.min)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

/** Os totais da semana como o Garmin Connect os mostra: passos e distância
 *  somados, e a média por dia — que é a linha que ele lê primeiro. */
function ASemana({ historico, ate }: { historico: GarminHistoryPoint[]; ate: string }) {
  const fim = +parseISO(ate);
  const dias = historico.filter(p => {
    const t = +parseISO(p.date);
    return t <= fim && t > fim - 7 * 24 * 3600_000;
  });
  const medidos = dias.filter(p => p.steps != null);
  if (medidos.length === 0) return <p className="text-sm text-gray-600">ainda sem dias medidos nesta semana</p>;

  const passos = medidos.reduce((s, p) => s + (p.steps || 0), 0);
  const metros = dias.reduce((s, p) => s + (p.distance_m || 0), 0);
  const intensos = dias.reduce((s, p) => s + (p.moderate_min || 0) + (p.vigorous_min || 0) * 2, 0);
  const inicio = dias[0]?.date;

  return (
    <div className="space-y-3 shrink-0">
      <p className="text-[11px] text-gray-600">
        {inicio && `${format(parseISO(inicio), 'd/M')} – ${format(parseISO(ate), 'd/M')}`}
        {' · '}{medidos.length} {medidos.length === 1 ? 'dia medido' : 'dias medidos'}
      </p>
      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        <Detalhe etiqueta="Passos" valor={passos.toLocaleString('pt-PT')} />
        <Detalhe etiqueta="Média por dia"
          valor={Math.round(passos / medidos.length).toLocaleString('pt-PT')} />
        {metros > 0 && <Detalhe etiqueta="Distância" valor={`${(metros / 1000).toFixed(1)} km`} />}
        {intensos > 0 && <Detalhe etiqueta="Minutos intensos" valor={minutos(intensos)} />}
      </div>
    </div>
  );
}

const TIPOS_DE_MOVIMENTO: Record<string, string> = {
  walking: 'caminhada', running: 'corrida', cycling: 'bicicleta',
  strength_training: 'musculação', swimming: 'natação', elliptical: 'elíptica',
};

const BLOCOS_DO_DIA = {
  sono: { nome: 'a dormir', cor: '#6366f1' },
  sesta: { nome: 'sesta', cor: '#a855f7' },
  movimento: { nome: 'em movimento', cor: '#22c55e' },
  treino: { nome: 'treino', cor: '#f59e0b' },
} as const;

type BlocoDoDia = {
  kind: keyof typeof BLOCOS_DO_DIA; start: number; end: number; nome: string;
  impacto?: number | null;      // o que o bloco fez ao Body Battery
};

/** Os blocos do dia, juntando o que o relógio detectou sozinho (sono, sestas,
 *  Move IQ) com os treinos que ele próprio gravou. Serve a linha do dia e as
 *  sombras do gráfico de frequência cardíaca — é o mesmo dia contado duas vezes,
 *  por isso é a mesma lista. */
function blocosDoDia(dia: GarminDay, series: GarminSeries, treinos: GarminActivity[]): BlocoDoDia[] {
  const inicioDoDia = +new Date(`${dia.date}T00:00:00`);
  const fimDoDia = inicioDoDia + 24 * 3600_000;
  return [
    ...series.events.map(e => ({
      kind: e.kind,
      start: e.start, end: e.end,
      impacto: e.impact ?? null,
      nome: e.kind === 'movimento'
        ? (TIPOS_DE_MOVIMENTO[e.type || ''] || e.type || 'movimento')
        : BLOCOS_DO_DIA[e.kind].nome,
    })),
    // Um treino gravado por ele vale por si; o Move IQ já veio nos eventos.
    ...treinos.filter(t => !t.auto && t.start && t.duration_s).map(t => ({
      kind: 'treino' as const,
      start: +parseISO(t.start!), end: +parseISO(t.start!) + t.duration_s! * 1000,
      nome: t.name || TIPOS_DE_MOVIMENTO[t.type] || t.type.replace(/_/g, ' '),
    })),
  ].filter(b => b.end > inicioDoDia && b.start < fimDoDia)
   .sort((a, b) => a.start - b.start);
}

/** A linha do dia da app da Garmin: onde é que o dia foi dormido, onde houve
 *  sesta e onde houve movimento. A hora a que ele acordou e a sesta da tarde não
 *  estão em campo nenhum do sono — só aqui. */
function LinhaDoDia({ dia, series, treinos }: {
  dia: GarminDay; series: GarminSeries; treinos: GarminActivity[];
}) {
  const inicioDoDia = +new Date(`${dia.date}T00:00:00`);
  const fimDoDia = inicioDoDia + 24 * 3600_000;
  const blocos = blocosDoDia(dia, series, treinos);

  if (blocos.length === 0) {
    return <p className="text-sm text-gray-600">
      Este dia não tem sono nem movimento registados pelo relógio.
    </p>;
  }

  const pos = (ts: number) => ((Math.min(Math.max(ts, inicioDoDia), fimDoDia) - inicioDoDia) / (24 * 3600_000)) * 100;
  const agora = Date.now();
  const eHoje = agora > inicioDoDia && agora < fimDoDia;

  return (
    <div className="flex flex-col min-h-0 gap-2">
      <div className="relative h-8 rounded-lg bg-[#0f0f0f] border border-[#222] overflow-hidden shrink-0">
        {[6, 12, 18].map(h => (
          <div key={h} className="absolute top-0 bottom-0 w-px bg-[#222]" style={{ left: `${(h / 24) * 100}%` }} />
        ))}
        {blocos.map((b, i) => (
          <div key={i} title={`${b.nome} · ${format(new Date(b.start), 'HH:mm')} → ${format(new Date(b.end), 'HH:mm')}`}
            className="absolute top-0 bottom-0 rounded-[3px]"
            style={{
              left: `${pos(b.start)}%`,
              width: `${Math.max(pos(b.end) - pos(b.start), 0.4)}%`,
              backgroundColor: BLOCOS_DO_DIA[b.kind].cor,
              opacity: 0.85,
            }} />
        ))}
        {eHoje && (
          <div className="absolute top-0 bottom-0 w-px bg-white/70" style={{ left: `${pos(agora)}%` }} />
        )}
      </div>

      {/* As horas ficam por baixo da marca a que dizem respeito, não espalhadas
          pela largura — senão o 06:00 não cai em cima do sítio das 6 da manhã. */}
      <div className="relative h-3 text-[10px] text-gray-600 tabular-nums shrink-0">
        {[0, 6, 12, 18, 24].map(h => (
          <span key={h} className="absolute top-0"
            style={{ left: `${(h / 24) * 100}%`, transform: h === 0 ? 'none' : h === 24 ? 'translateX(-100%)' : 'translateX(-50%)' }}>
            {String(h).padStart(2, '0')}:00
          </span>
        ))}
      </div>

      <div className="flex flex-wrap gap-x-5 gap-y-1.5 text-xs min-h-0 overflow-y-auto">
        {blocos.map((b, i) => (
          <span key={i} className="flex items-baseline gap-1.5">
            <span className="w-2 h-2 rounded-full shrink-0 self-center"
              style={{ backgroundColor: BLOCOS_DO_DIA[b.kind].cor }} />
            <span className="text-gray-400">{b.nome}</span>
            <span className="text-gray-200 tabular-nums">
              {format(new Date(b.start), 'HH:mm')}–{format(new Date(b.end), 'HH:mm')}
            </span>
            <span className="text-gray-600 tabular-nums">
              {minutos(Math.round((b.end - b.start) / 60000))}
            </span>
            {!!b.impacto && (
              <span className="text-sky-400/80 tabular-nums">+{b.impacto}</span>
            )}
          </span>
        ))}
      </div>
    </div>
  );
}

const ZONAS_FC = [
  { nome: 'Z1', etiqueta: 'aquecimento', cor: '#64748b' },
  { nome: 'Z2', etiqueta: 'fácil', cor: '#38bdf8' },
  { nome: 'Z3', etiqueta: 'aeróbio', cor: '#4ade80' },
  { nome: 'Z4', etiqueta: 'limiar', cor: '#fb923c' },
  { nome: 'Z5', etiqueta: 'máximo', cor: '#f43f5e' },
] as const;

/** Todas as leituras de FC do dia — uma de 2 em 2 minutos, o que a Garmin dá.
 *
 *  Eixo do tempo a sério (não a hora em texto): é o que faz um intervalo sem
 *  relógio no pulso ocupar o espaço que ocupou mesmo, e o que permite marcar os
 *  treinos por cima da curva. Buracos com mais de 15 minutos partem a linha em
 *  vez de a ligar por cima do vazio. */
function CurvaDeFC({ series, dia, treinos, zonas }: {
  series: GarminSeries; dia: GarminDay; treinos: GarminActivity[]; zonas: GarminHrZones | null;
}) {
  const leituras = series.hr;
  if (leituras.length < 2) {
    return <p className="text-sm text-gray-600">
      Ainda sem leituras suficientes neste dia — a frequência cardíaca só é
      registada com o relógio no pulso.
    </p>;
  }

  const CORTE_MS = 15 * 60 * 1000;
  const pontos: { ts: number; bpm: number | null }[] = [];
  leituras.forEach(([ts, bpm], i) => {
    const anterior = leituras[i - 1];
    if (anterior && ts - anterior[0] > CORTE_MS) pontos.push({ ts: anterior[0] + 1, bpm: null });
    pontos.push({ ts, bpm });
  });

  const valores = leituras.map(([, bpm]) => bpm);
  const mini = Math.min(...valores);
  const maxi = Math.max(...valores);
  const dominio: [number, number] = [Math.max(30, Math.floor((mini - 8) / 10) * 10),
                                     Math.ceil((maxi + 8) / 10) * 10];
  const repouso = dia.recovery.resting_hr;
  // Cada zona com o intervalo de batimentos a que corresponde — "Z1" sozinho não
  // diz nada a quem não anda a treinar por zonas.
  const emZona = zonas?.minutes.slice(1)
    .map((min, i) => ({ ...ZONAS_FC[i], min,
                        de: zonas.floors[i], ate: zonas.floors[i + 1] ?? zonas.max }))
    .filter(z => z.min > 0) ?? [];
  const blocos = blocosDoDia(dia, series, treinos);

  return (
    <div className="flex flex-col min-h-0 lg:flex-1">
      <div className="h-[240px] lg:h-0 lg:flex-1">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={pontos} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="gFC" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#f43f5e" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={CINZA} />
          {/* As zonas por trás da curva: fora do domínio do dia são cortadas
              sozinhas, por isso um dia sedentário não mostra cinco faixas vazias. */}
          {zonas?.floors.map((piso, i) => (
            <ReferenceArea key={piso} y1={piso} y2={zonas.floors[i + 1] ?? zonas.max}
              fill={ZONAS_FC[i].cor} fillOpacity={0.07} stroke="none" ifOverflow="hidden" />
          ))}
          {/* O que o corpo estava a fazer, por cima da curva: dormir, sesta,
              movimento ou treino. É a mesma lista da linha do dia. */}
          {blocos.map((b, i) => (
            <ReferenceArea key={i} x1={b.start} x2={b.end}
              fill={BLOCOS_DO_DIA[b.kind].cor} fillOpacity={0.14} stroke="none" ifOverflow="hidden" />
          ))}
          <XAxis dataKey="ts" type="number" scale="time" domain={['dataMin', 'dataMax']}
            stroke="#555" fontSize={11} minTickGap={40}
            tickFormatter={(ts: number) => format(new Date(ts), 'HH:mm')} />
          <YAxis stroke="#555" fontSize={11} width={34} domain={dominio} />
          {repouso != null && (
            <ReferenceLine y={repouso} stroke="#38bdf8" strokeDasharray="4 4" strokeOpacity={0.7}
              label={{ value: `repouso ${repouso}`, position: 'insideBottomLeft', fill: '#38bdf8', fontSize: 10 }} />
          )}
          <Tooltip
            contentStyle={{ background: '#0f0f0f', border: `1px solid ${CINZA}`, borderRadius: 12, fontSize: 12 }}
            labelStyle={{ color: '#9ca3af', marginBottom: 4 }}
            labelFormatter={(ts: any) => format(new Date(ts), 'HH:mm')}
            formatter={(v: any) => [v == null ? '—' : `${v} bpm`, 'FC']} />
          <Area type="monotone" dataKey="bpm" name="FC" stroke="#f43f5e" fill="url(#gFC)"
            strokeWidth={1.5} dot={false} connectNulls={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
      </div>

      <div className="flex items-center gap-x-4 gap-y-2 mt-2 text-xs text-gray-500 flex-wrap shrink-0">
        <span>mín <span className="text-gray-300 tabular-nums">{mini}</span></span>
        <span>máx <span className="text-gray-300 tabular-nums">{maxi}</span></span>
        <span className="text-gray-600">{leituras.length} leituras</span>
        {[...new Set(blocos.map(b => b.kind))].map(k => (
          <span key={k} className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: BLOCOS_DO_DIA[k].cor, opacity: 0.35 }} />
            {BLOCOS_DO_DIA[k].nome}
          </span>
        ))}
      </div>

      {emZona.length > 0 && (
        <div className="flex items-center gap-x-4 gap-y-1 mt-2 pt-2 border-t border-[#222] text-xs flex-wrap shrink-0">
          <span className="text-gray-600">tempo por zona de esforço</span>
          {emZona.map(z => (
            <span key={z.nome} className="flex items-center gap-1.5 text-gray-500"
              title={`${z.nome} (${z.etiqueta}): entre ${z.de} e ${z.ate} bpm`}>
              <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: z.cor, opacity: 0.6 }} />
              {z.nome} <span className="text-gray-600">{z.etiqueta} {z.de}–{z.ate}</span>
              <span className="text-gray-300 tabular-nums">{minutos(z.min)}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// Tailwind precisa das classes escritas por extenso — daí o mapa em vez de
// `lg:grid-cols-${n}`.
const COLUNAS: Record<number, string> = {
  2: 'lg:grid-cols-2', 3: 'lg:grid-cols-3', 4: 'lg:grid-cols-4',
};
const COLUNAS_SPAN: Record<number, string> = {
  2: 'lg:col-span-2', 3: 'lg:col-span-3', 4: 'lg:col-span-4',
};

type Seccao = 'leitura' | 'medicoes' | 'historico';

// A leitura é o que se abre: é a que responde a "como é que o dia correu". Os
// números todos ficam ao lado, para quem os quiser ver.
const SECCOES: { chave: Seccao; nome: string }[] = [
  { chave: 'leitura', nome: 'Leitura' },
  { chave: 'medicoes', nome: 'Medições' },
  { chave: 'historico', nome: 'Histórico' },
];

export default function GarminPage() {
  const [seccao, setSeccao] = useState<Seccao>('leitura');
  const [estado, setEstado] = useState<GarminStatus | null>(null);
  const [vista, setVista] = useState<GarminDayView | null>(null);
  const [quando, setQuando] = useState<string | null>(null);   // null = o mais recente
  const [historico, setHistorico] = useState<GarminHistoryPoint[]>([]);
  const [reguas, setReguas] = useState<GarminBaselines | null>(null);
  const [treinos, setTreinos] = useState<GarminActivity[]>([]);
  const [leitura, setLeitura] = useState<GarminReading | null>(null);
  const [dias, setDias] = useState(30);
  const [aSincronizar, setASincronizar] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [aCarregar, setACarregar] = useState(true);

  useEffect(() => { carrega(); }, [dias, quando]);

  async function carrega() {
    try {
      const [e, v, hist, t, r] = await Promise.all([
        garminApi.status(),
        quando ? garminApi.day(quando) : garminApi.today(),
        garminApi.history(dias),
        garminApi.activities(dias),
        garminApi.baselines(dias),
      ]);
      setEstado(e); setVista(v); setHistorico(hist); setTreinos(t); setReguas(r); setErro(null);
      // A leitura espera pelo modelo local — carrega à parte para não segurar a página.
      garminApi.reading(quando || undefined).then(setLeitura).catch(() => setLeitura(null));
    } catch (e: any) {
      setErro(e?.message || 'não deu para ler os dados do relógio');
    } finally {
      setACarregar(false);
    }
  }

  async function sincroniza() {
    setASincronizar(true);
    setErro(null);
    try {
      await garminApi.sync(3);
      await carrega();
    } catch (e: any) {
      setErro(e?.message || 'a sincronização falhou');
    } finally {
      setASincronizar(false);
    }
  }

  if (aCarregar) return <p className="text-gray-500 text-sm">a carregar…</p>;

  const dia = vista?.day;
  const hrv = dia?.recovery.hrv_status ? ESTADO_HRV[dia.recovery.hrv_status] : null;
  const semLigacao = estado && !estado.connected;
  const temSono = dia?.sleep.hours != null;
  const noitesMedidas = historico.filter(p => p.sleep_hours != null).length;
  // Só faz sentido avisar sobre o dia que está a decorrer: num dia antigo, as
  // leituras estarem paradas há 20h é o normal.
  const porSincronizar = !vista?.stale && (vista?.coverage.hours_ago ?? 0) >= 2;
  const temTreino = !!dia && (dia.training.readiness != null || !!texto(dia.training.status)
    || dia.training.vo2max != null || dia.training.recovery_min != null
    || dia.activity.active_calories != null);
  const temSnapshots = (vista?.snapshots.length ?? 0) > 0;
  // Três linhas de painéis: a primeira é o gráfico da frequência cardíaca, e as
  // outras duas levam o resto. Com Health Snapshot são seis painéis a dividir
  // por duas linhas, e aí é preciso uma coluna a mais.
  const colunasDoDia = temSnapshots ? 4 : 3;
  const temCorpo = !!dia && (dia.body.fitness_age != null || dia.body.weight_kg != null);
  const eixoX = { stroke: '#555', fontSize: 11, interval: 'preserveStartEnd' as const, minTickGap: 20 };
  const dadosHistorico = historico.map(p => ({
    ...p,
    dia: format(parseISO(p.date), 'd/M'),
    faixa: p.hr_min != null && p.hr_max != null ? [p.hr_min, p.hr_max] : null,
    // As fases e as faixas de stress vêm em minutos; em horas as barras
    // empilhadas lêem-se com o mesmo eixo do resto da página.
    ...Object.fromEntries(FASES.map(f => [`${f.chave}_h`, emHoras(p[f.chave])])),
    ...Object.fromEntries(NIVEIS_DE_STRESS.map(
      n => [`${n.chave}_h`, emHoras(p[`stress_${n.chave}` as keyof GarminHistoryPoint] as number | null)])),
    // O gasto do dia vai para baixo do zero: a pergunta é se a noite devolveu
    // o que o dia levou, e isso vê-se com as duas barras a partir da mesma linha.
    bb_gasto: p.bb_drained != null ? -p.bb_drained : null,
  }));
  const regua = (chave: string) => reguas?.metrics[chave];
  const minimoDaFaixa = reguas?.min_days ?? 8;
  const alertas = (reguas?.alerts ?? [])
    .map(d => format(parseISO(d), 'd/M'))
    .filter(d => dadosHistorico.some(p => p.dia === d));
  const diasComMeta = historico.filter(
    p => p.steps != null && p.step_goal != null && p.steps >= p.step_goal).length;
  const temProntidao = historico.some(p => p.readiness != null);

  return (
    // Em desktop a página ocupa exactamente a altura da janela e é cada painel
    // que estica ou faz scroll dentro de si — o que não cabe fica onde está, em
    // vez de empurrar o resto para fora do ecrã. No telemóvel não há altura que
    // chegue e volta tudo ao empilhado normal.
    // A altura é a da janela menos o padding do shell (lg:p-8 → 4rem), porque
    // um `h-full` aqui dentro resolveria contra um pai que cresce com o conteúdo.
    <div className="flex flex-col gap-3 lg:gap-4 lg:h-[calc(100dvh-4rem)] lg:min-h-0 lg:overflow-hidden">
      {/* Cabeçalho: que dia, que secção, e o botão de ir buscar dados novos */}
      <div className="flex items-start justify-between gap-3 flex-wrap shrink-0">
        <div>
          <h2 className="text-xl lg:text-2xl font-bold">Relógio</h2>
          {seccao !== 'historico' && (
            <div className="flex items-center gap-1 mt-1">
              <button onClick={() => vista?.prev && setQuando(vista.prev)} disabled={!vista?.prev}
                className="p-1 -ml-1 rounded-lg hover:bg-white/10 disabled:opacity-20 disabled:hover:bg-transparent"
                title="dia anterior">
                <ChevronLeft size={16} />
              </button>
              <p className="text-gray-500 text-sm">
                {dia
                  ? `${format(parseISO(dia.date), "EEEE, d 'de' MMMM", { locale: pt })}${vista?.stale ? ' · último dia com dados' : ''}`
                  : 'sem dados ainda'}
              </p>
              <button onClick={() => vista?.next && setQuando(vista.next)} disabled={!vista?.next}
                className="p-1 rounded-lg hover:bg-white/10 disabled:opacity-20 disabled:hover:bg-transparent"
                title="dia seguinte">
                <ChevronRight size={16} />
              </button>
              {quando && (
                <button onClick={() => setQuando(null)}
                  className="text-xs text-gray-500 hover:text-white underline underline-offset-2 ml-1">
                  hoje
                </button>
              )}
            </div>
          )}
          {seccao === 'historico' && (
            <p className="text-gray-500 text-sm mt-1">últimos {dias} dias</p>
          )}
        </div>

        <div className="flex items-center gap-3">
          {/* Dados parados é um aviso de duas palavras ao lado das secções, não
              um banner de quatro linhas a explicar como funciona o relógio. */}
          {porSincronizar && (
            <span title={`A Garmin não recebe nada do relógio desde as ${hora(vista!.coverage.to)}. `
              + 'O relógio não tem Wi-Fi: abre o Garmin Connect no telemóvel com ele por perto '
              + 'e carrega em Sincronizar.'}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-300/90 whitespace-nowrap">
              <CloudOff size={13} />
              sem dados há {Math.round(vista!.coverage.hours_ago!)}h
            </span>
          )}
          <div className="flex items-center gap-1 bg-[#161616] rounded-xl border border-[#222] p-1">
            {SECCOES.map(s => (
              <button key={s.chave} onClick={() => setSeccao(s.chave)}
                className={`px-3 py-1.5 text-xs rounded-lg transition-all ${
                  seccao === s.chave ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-white'}`}>
                {s.nome}
              </button>
            ))}
          </div>
          {seccao === 'historico' && (
            <div className="flex items-center gap-1 bg-[#161616] rounded-xl border border-[#222] p-1">
              {[7, 30, 90].map(d => (
                <button key={d} onClick={() => setDias(d)}
                  className={`px-3 py-1.5 text-xs rounded-lg transition-all ${
                    dias === d ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-white'}`}>
                  {d}d
                </button>
              ))}
            </div>
          )}
          {/* O estado da sincronização era uma linha no fim da página a roubar
              altura ao gráfico; passa a viver aqui, onde só se lê quando se
              procura. */}
          <button onClick={sincroniza} disabled={aSincronizar}
            title={estado?.last_sync
              ? [estado.watch_synced_at
                  ? `o relógio falou com o telemóvel ${format(parseISO(estado.watch_synced_at), "'a' d/M 'às' HH:mm")}`
                  : 'ainda sem sinal de quando o relógio sincronizou',
                 `a app leu ${format(parseISO(estado.last_sync), "'às' HH:mm")}`,
                 `${estado.days} dias e ${estado.activities} treinos guardados`].join(' · ')
              : undefined}
            className="flex items-center gap-2 px-4 py-2 bg-sky-600 hover:bg-sky-700 disabled:opacity-50 rounded-xl text-sm font-medium">
            <RefreshCw size={16} className={aSincronizar ? 'animate-spin' : ''} />
            <span className="hidden sm:inline">{aSincronizar ? 'a sincronizar…' : 'Sincronizar'}</span>
          </button>
        </div>
      </div>

      {semLigacao && (
        <div className="bg-amber-500/10 border border-amber-500/20 rounded-2xl p-4 text-sm text-amber-200/90">
          O relógio ainda não está ligado à app. No backend, correr uma vez{' '}
          <code className="bg-black/30 px-1.5 py-0.5 rounded">python scripts/garmin_login.py</code>{' '}
          — a password é pedida na altura e não fica guardada em lado nenhum.
        </div>
      )}
      {erro && <div className="bg-red-500/10 border border-red-500/20 rounded-2xl p-4 text-sm text-red-300">{erro}</div>}

      {/* ── O estado do dia: é o cabeçalho da Leitura ─────────────────── */}
      {seccao === 'leitura' && dia && (
        <div className="flex flex-col gap-3 lg:gap-4 shrink-0">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 lg:gap-4">
            <Cartao icone={<Moon size={14} className="text-purple-400" />} titulo="Sono"
              valor={horas(dia.sleep.hours)}
              sub={temSono
                ? (dia.sleep.score != null ? `${dia.sleep.score}/100` : 'sem pontuação')
                : 'não medido'} />
            <Cartao icone={<BatteryCharging size={14} className="text-sky-400" />} titulo="Body Battery"
              valor={dia.body_battery.end != null ? String(dia.body_battery.end) : '—'}
              sub={dia.body_battery.start != null
                ? (temSono ? `ao acordar ${dia.body_battery.start}` : `1.ª leitura ${dia.body_battery.start}`)
                : undefined}
              cor={(dia.body_battery.end ?? 100) < 25 ? 'text-red-400' : 'text-white'} />
            <Cartao icone={<HeartPulse size={14} className="text-rose-400" />} titulo="HRV"
              valor={dia.recovery.hrv != null ? `${dia.recovery.hrv}ms` : '—'}
              sub={hrv?.texto} cor={hrv?.cor || 'text-white'} />
            <Cartao icone={<Heart size={14} className="text-red-400" />} titulo="FC em repouso"
              valor={dia.recovery.resting_hr != null ? `${dia.recovery.resting_hr}` : '—'} sub="bpm" />
            <Cartao icone={<Footprints size={14} className="text-green-400" />} titulo="Passos"
              valor={dia.activity.steps != null ? dia.activity.steps.toLocaleString('pt-PT') : '—'}
              sub={dia.activity.step_goal ? `meta ${dia.activity.step_goal.toLocaleString('pt-PT')}` : undefined} />
          </div>

          <Painel titulo="A linha do dia"
            extra={<span className="text-[10px] text-gray-600">sono, sestas e movimento</span>}>
            <LinhaDoDia dia={dia} series={vista!.series} treinos={vista!.activities} />
          </Painel>
        </div>
      )}

      {/* ── Medições ────────────────────────────────────────── */}
      {seccao === 'medicoes' && dia && (
        <>
          {/* Duas linhas iguais para os dois gráficos ficarem do mesmo tamanho, e
              a coluna da direita com o que se lê em números: a noite em cima, o
              resto em baixo. */}
          <div className={`grid grid-cols-1 gap-3 lg:gap-4 lg:flex-1 lg:min-h-0 ${COLUNAS[colunasDoDia]}
            lg:grid-rows-2`}>
            <div className="lg:col-span-2 lg:col-start-1 lg:row-start-1 min-h-0">
              <Painel titulo="Frequência cardíaca ao longo do dia"
                extra={dia.activity.hr_min != null && dia.activity.hr_max != null ? (
                  <span className="text-xs text-gray-600">
                    {dia.activity.hr_min}–{dia.activity.hr_max} bpm
                  </span>
                ) : undefined}>
                <CurvaDeFC series={vista!.series} dia={dia} treinos={vista!.activities}
                  zonas={vista!.hr_zones} />
              </Painel>
            </div>

            <div className="lg:col-span-2 lg:col-start-1 lg:row-start-2 min-h-0">
              <Painel titulo="Body Battery e stress"
                extra={vista!.coverage.from && (
                  <span className="text-xs text-gray-600">
                    {hora(vista!.coverage.from)} → {hora(vista!.coverage.to)}
                  </span>
                )}>
                <CurvaDoDia series={vista!.series} />
              </Painel>
            </div>

            {/* A noite leva a coluna inteira e a altura que o conteúdo pedir —
                são oito medidas e uma barra de fases, e espremidas em meia coluna
                obrigavam a rolar lá dentro. O que sobra da coluna fica para a
                semana, que encolhe sem problema. */}
            <div className="lg:col-start-3 lg:row-start-1 lg:row-span-2 min-h-0 flex flex-col gap-3 lg:gap-4">
              <div className="lg:shrink-0">
                <Painel titulo="A noite passada"
                  extra={temSono ? <span className="text-xs text-gray-600 whitespace-nowrap shrink-0">
                    {hora(dia.sleep.start)} → {hora(dia.sleep.end)}
                    {minutosDeSestas(dia, vista!.series) > 0 && dia.sleep.hours != null
                      && ` · ${horas(dia.sleep.hours + minutosDeSestas(dia, vista!.series) / 60)} com sesta`}
                  </span> : undefined}>
                  {temSono ? <NoitePassada dia={dia} series={vista!.series} />
                    : <SemSono cobertura={vista!.coverage} />}
                </Painel>
              </div>
              <div className="lg:flex-1 lg:min-h-0">
                <Painel titulo="Os números do dia"
                  extra={<span className="text-[10px] text-gray-600">bateria e stress</span>}>
                  <NumerosDoDia dia={dia} series={vista!.series} />
                </Painel>
              </div>
            </div>

            {temSnapshots && (
              <div className="lg:col-start-4 lg:row-start-1 lg:row-span-2 min-h-0">
                <Painel titulo={vista!.snapshots.length > 1 ? 'Health Snapshots' : 'Health Snapshot'}
                  extra={<span className="text-xs text-gray-600 truncate">{vista!.snapshots[0].device}</span>}>
                  <Snapshots medicoes={vista!.snapshots} />
                </Painel>
              </div>
            )}
          </div>
        </>
      )}
      {seccao !== 'historico' && !dia && (
        <p className="text-sm text-gray-600">Ainda não há nenhum dia com dados do relógio.</p>
      )}

      {/* ── Leitura ─────────────────────────────────────────── */}
      {seccao === 'leitura' && (
        // A leitura leva duas colunas de três: é o texto e os factos que se vêm
        // aqui ler, e as correlações são uma nota de rodapé a maior parte dos dias.
        // Os dois painéis esticam até ao fundo da janela e é dentro deles que se
        // rola — a página em si nunca cresce (`overflow-hidden`, e não `auto`).
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 lg:gap-4 lg:flex-1 lg:min-h-0 lg:overflow-hidden">
          <div className="lg:col-span-2 lg:min-h-0">
          <Painel titulo={leitura?.headline || 'O dia'}
            extra={leitura && (
              <span className="text-[10px] text-gray-600">
                {leitura.source === 'agente' ? 'lido pela IA, números da app'
                  : leitura.source === 'local' ? 'texto pelo modelo local'
                  : 'números da app'}
              </span>
            )}>
            {!leitura ? <p className="text-sm text-gray-600">a ler…</p>
              : !leitura.facts.length ? (
                <p className="text-sm text-gray-600">
                  Nada a assinalar neste dia — nenhuma medida saiu do teu costume.
                </p>
              ) : (
                <>
                  {leitura.text && leitura.linked && (
                    <ul className={`space-y-2 mb-4 shrink-0 ${leitura.source === 'agente'
                      ? 'text-gray-300' : 'text-gray-400 italic'}`}>
                      {leitura.text.split('\n').filter(Boolean).map((ponto, i) => (
                        <li key={i} className="text-sm flex gap-3">
                          <span className="mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 bg-blue-400" />
                          <span>{ponto}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                  {leitura.source === 'agente' && (
                    <p className="text-[11px] text-gray-600 mb-4 pb-4 border-b border-[#222] shrink-0">
                      Pontos escritos pela IA a partir destes números — nenhum algarismo
                      que ela escreva pode faltar aqui em baixo.
                    </p>
                  )}
                  <Factos leitura={leitura} />
                  {leitura.days_for_baseline > 0 && (
                    <p className="text-[11px] text-gray-600 mt-4 pt-4 border-t border-[#222] shrink-0">
                      Faltam {leitura.days_for_baseline} dias medidos para haver régua com que
                      comparar. Até lá só aparecem distâncias a alvos, não desvios ao teu costume.
                    </p>
                  )}
                </>
              )}
          </Painel>
          </div>

          <div className="flex flex-col gap-3 lg:gap-4 lg:min-h-0">
            <Painel titulo="O que anda junto com o quê"
              extra={<span className="text-[10px] text-gray-600">correlação de Spearman</span>}>
              {!leitura ? <p className="text-sm text-gray-600">a ler…</p>
                : leitura.relations.length ? <Relacoes relacoes={leitura.relations} />
                : (
                  <p className="text-sm text-gray-600">
                    {leitura.days_for_relations > 0
                      ? `Faltam ${leitura.days_for_relations} dias medidos. Com menos do que isso,
                         qualquer correlação entre o relógio e o resto da app é coincidência.`
                      : 'Nenhuma relação passou no teste de significância — o que é uma resposta.'}
                  </p>
                )}
            </Painel>
          </div>
        </div>
      )}

      {/* ── Histórico ───────────────────────────────────────── */}
      {seccao === 'historico' && (
        <div className={`grid grid-cols-1 gap-3 lg:gap-4 lg:flex-1 lg:min-h-0 lg:overflow-y-auto lg:auto-rows-min ${COLUNAS[3]}`}>
            {/* O sono aqui é de que é feita cada noite — as horas por si já as
                diz a página do Sono. A pontuação vai no eixo direito porque é
                ela que responde a "9h e mesmo assim uma noite fraca". */}
            <Painel titulo="Sono, noite a noite"
              extra={<span className="text-xs text-gray-600">{noitesMedidas} {noitesMedidas === 1 ? 'noite' : 'noites'}</span>}>
              {noitesMedidas === 0 ? (
                <SemDados>
                  Ainda não há nenhuma noite medida. O relógio tem de estar no pulso a dormir —
                  com ele a carregar durante a noite, a Garmin não regista sono nenhum.
                </SemDados>
              ) : (
                <>
                <GraficoBox>
                  <ComposedChart data={dadosHistorico}>
                    <CartesianGrid strokeDasharray="3 3" stroke={CINZA} />
                    <XAxis dataKey="dia" {...eixoX} />
                    <YAxis yAxisId="h" stroke="#555" fontSize={11} width={30}
                      tickFormatter={(v: number) => `${v}h`} />
                    <YAxis yAxisId="p" orientation="right" domain={[0, 100]} stroke="#555" fontSize={11} width={28} />
                    <Tooltip contentStyle={TOOLTIP}
                      formatter={(v: any, nome: string) => [
                        nome === 'pontuação' ? v : horas(v as number), nome]} />
                    {FASES.map(f => (
                      <Bar key={f.chave} yAxisId="h" dataKey={`${f.chave}_h`} name={f.nome}
                        stackId="sono" fill={f.cor} isAnimationActive={false}
                        radius={f.chave === 'awake_min' ? [4, 4, 0, 0] : undefined} />
                    ))}
                    {faixaDe(regua('sleep_hours'), '#9775fa', 'h')}
                    <Line yAxisId="p" type="monotone" dataKey="sleep_score" name="pontuação"
                      stroke="#e9ecef" strokeWidth={1.5} dot={false} connectNulls />
                  </ComposedChart>
                </GraficoBox>
                <NotaDaFaixa regua={regua('sleep_hours')} minimo={minimoDaFaixa} unidade="h" />
                </>
              )}
            </Painel>

            {/* Uma noite de HRV varia 15-30% por ruído. O que se lê é a média de
                7 dias contra a faixa — é assim que o relógio decide o estado. */}
            <Painel titulo="HRV"
              extra={<span className="text-[10px] text-gray-600">noite · média de 7 dias</span>}>
              {historico.every(p => p.hrv == null) ? (
                <SemDados>
                  Sem leituras ainda — o HRV só é medido com o relógio no pulso a dormir.
                </SemDados>
              ) : (
                <>
                <GraficoBox>
                  <ComposedChart data={dadosHistorico}>
                    <CartesianGrid strokeDasharray="3 3" stroke={CINZA} />
                    <XAxis dataKey="dia" {...eixoX} />
                    <YAxis stroke="#555" fontSize={11} width={30} domain={['dataMin - 4', 'dataMax + 4']} />
                    <Tooltip contentStyle={TOOLTIP} formatter={(v: any, nome: string) => [`${v} ms`, nome]} />
                    {faixaDe(regua('hrv'), '#f43f5e')}
                    <Line type="monotone" dataKey="hrv" name="a noite" stroke="none"
                      dot={{ r: 2.5, fill: '#fda4af' }} isAnimationActive={false} />
                    <Line type="monotone" dataKey="hrv_avg7" name="média de 7 dias" stroke="#f43f5e"
                      strokeWidth={2.5} dot={false} connectNulls />
                  </ComposedChart>
                </GraficoBox>
                <NotaDaFaixa regua={regua('hrv')} minimo={minimoDaFaixa} unidade=" ms" />
                </>
              )}
            </Painel>

            <Painel titulo="Frequência cardíaca, dia a dia"
              extra={<span className="text-[10px] text-gray-600">faixa do dia · repouso</span>}>
              {historico.every(p => p.hr_max == null) ? (
                <SemDados>Sem leituras ainda — é preciso um dia com o relógio no pulso.</SemDados>
              ) : (
                <>
                <GraficoBox>
                  <ComposedChart data={dadosHistorico}>
                    <CartesianGrid strokeDasharray="3 3" stroke={CINZA} />
                    <XAxis dataKey="dia" {...eixoX} />
                    <YAxis stroke="#555" fontSize={11} width={34}
                      domain={['dataMin - 8', 'dataMax + 8']} />
                    <Tooltip contentStyle={TOOLTIP}
                      formatter={(v: any, nome: string) => [
                        Array.isArray(v) ? `${v[0]}–${v[1]} bpm` : `${v} bpm`, nome]} />
                    {/* Área de intervalo: o dataKey devolve o par [mín, máx] do dia,
                        que é o que mostra um dia de treino sem esconder o resto. */}
                    <Area dataKey="faixa" name="mín–máx" stroke="#f43f5e" strokeOpacity={0.25}
                      fill="#f43f5e" fillOpacity={0.07} connectNulls={false} isAnimationActive={false} />
                    {faixaDe(regua('resting_hr'), '#38bdf8')}
                    <Line type="monotone" dataKey="resting_hr" name="repouso" stroke="#7dd3fc"
                      strokeWidth={1.5} strokeOpacity={0.6} dot={false} connectNulls />
                    <Line type="monotone" dataKey="rhr_avg7" name="repouso, 7 dias" stroke="#38bdf8"
                      strokeWidth={2.5} dot={false} connectNulls />
                    {/* O sinal de infecção a incubar: dois dias seguidos com a
                        frequência acima e o HRV abaixo. É a mesma regra da
                        Leitura, marcada onde ela aconteceu. */}
                    {alertas.map(d => (
                      <ReferenceLine key={d} x={d} stroke="#f59e0b" strokeOpacity={0.6} strokeDasharray="3 3" />
                    ))}
                  </ComposedChart>
                </GraficoBox>
                {alertas.length > 0 ? (
                  <p className="text-[10px] text-amber-300/80 mt-2 shrink-0">
                    a amarelo, os dias com a frequência acima e o HRV abaixo dois dias seguidos —
                    o sinal do costume de o corpo estar a lutar contra alguma coisa
                  </p>
                ) : (
                  <NotaDaFaixa regua={regua('resting_hr')} minimo={minimoDaFaixa} unidade=" bpm" />
                )}
                </>
              )}
            </Painel>

            {/* As quatro faixas existiam só para o dia que se estivesse a ver. É
                aqui que se percebe se as horas de stress alto andam a crescer. */}
            <Painel titulo="Stress, dia a dia"
              extra={<span className="text-[10px] text-gray-600">as quatro faixas · média</span>}>
              {historico.every(p => p.stress_avg == null) ? (
                <SemDados>Sem leituras ainda — o stress é medido com o relógio no pulso durante o dia.</SemDados>
              ) : (
                <>
                <GraficoBox>
                  <ComposedChart data={dadosHistorico}>
                    <CartesianGrid strokeDasharray="3 3" stroke={CINZA} />
                    <XAxis dataKey="dia" {...eixoX} />
                    <YAxis yAxisId="h" stroke="#555" fontSize={11} width={30}
                      tickFormatter={(v: number) => `${v}h`} />
                    <YAxis yAxisId="m" orientation="right" domain={[0, 100]} stroke="#555" fontSize={11} width={28} />
                    <Tooltip contentStyle={TOOLTIP}
                      formatter={(v: any, nome: string) => [
                        nome === 'média' ? v : horas(v as number), nome]} />
                    {NIVEIS_DE_STRESS.map((n, i) => (
                      <Bar key={n.chave} yAxisId="h" dataKey={`${n.chave}_h`} name={n.nome}
                        stackId="stress" fill={n.cor} isAnimationActive={false}
                        radius={i === NIVEIS_DE_STRESS.length - 1 ? [4, 4, 0, 0] : undefined} />
                    ))}
                    <Line yAxisId="m" type="monotone" dataKey="stress_avg" name="média"
                      stroke="#e9ecef" strokeWidth={1.5} dot={false} connectNulls />
                  </ComposedChart>
                </GraficoBox>
                <NotaDaFaixa regua={regua('stress_avg')} minimo={minimoDaFaixa} o="régua da média" />
                </>
              )}
            </Painel>

            {/* A pergunta é se as noites estão a devolver o que os dias gastam:
                a carga para cima, a descarga para baixo, no mesmo eixo. */}
            <Painel titulo="Body Battery"
              extra={<span className="text-[10px] text-gray-600">carregou · gastou · ao acordar</span>}>
              {historico.every(p => p.bb_charged == null) ? (
                <SemDados>Sem leituras ainda — é preciso um dia com o relógio no pulso.</SemDados>
              ) : (
                <>
                <GraficoBox>
                  <ComposedChart data={dadosHistorico} stackOffset="sign">
                    <CartesianGrid strokeDasharray="3 3" stroke={CINZA} />
                    <XAxis dataKey="dia" {...eixoX} />
                    <YAxis stroke="#555" fontSize={11} width={34} />
                    <Tooltip contentStyle={TOOLTIP}
                      formatter={(v: any, nome: string) => [Math.abs(v as number), nome]} />
                    <ReferenceLine y={0} stroke="#333" />
                    <Bar dataKey="bb_charged" name="carregou" stackId="bb" fill="#4ade80"
                      isAnimationActive={false} radius={[4, 4, 0, 0]} />
                    <Bar dataKey="bb_gasto" name="gastou" stackId="bb" fill="#f43f5e"
                      isAnimationActive={false} radius={[0, 0, 4, 4]} />
                    <Line type="monotone" dataKey="bb_start" name="ao acordar" stroke="#e9ecef"
                      strokeWidth={1.5} dot={false} connectNulls />
                  </ComposedChart>
                </GraficoBox>
                <NotaDaFaixa regua={regua('bb_start')} minimo={minimoDaFaixa} o="régua do acordar" />
                </>
              )}
            </Painel>

            <Painel titulo="Passos"
              extra={<span className="text-[10px] text-gray-600">a meta da Garmin move-se todos os dias</span>}>
              {historico.every(p => p.steps == null) ? (
                <SemDados>Sem leituras ainda — é preciso um dia com o relógio no pulso.</SemDados>
              ) : (
                <>
                <GraficoBox>
                  <ComposedChart data={dadosHistorico}>
                    <CartesianGrid strokeDasharray="3 3" stroke={CINZA} />
                    <XAxis dataKey="dia" {...eixoX} />
                    <YAxis stroke="#555" fontSize={11} width={42}
                      tickFormatter={(v: number) => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : `${v}`} />
                    <Tooltip contentStyle={TOOLTIP}
                      formatter={(v: any, nome: string) => [(v as number).toLocaleString('pt-PT'), nome]} />
                    {faixaDe(regua('steps'), '#f59e0b')}
                    <Bar dataKey="steps" name="passos" fill="#f59e0b" radius={[4, 4, 0, 0]}
                      isAnimationActive={false} />
                    <Line type="monotone" dataKey="step_goal" name="meta" stroke="#e9ecef"
                      strokeWidth={1.5} strokeDasharray="4 3" dot={false} connectNulls />
                  </ComposedChart>
                </GraficoBox>
                <p className="text-[10px] text-gray-600 mt-2 shrink-0">
                  {diasComMeta > 0
                    ? `cumpriste a meta em ${diasComMeta} ${diasComMeta === 1 ? 'dia' : 'dias'}`
                    : 'nenhum dia chegou à meta neste período'}
                </p>
                </>
              )}
            </Painel>

            {/* Os minutos de intensidade são um alvo semanal, não diário — um dia
                sozinho não diz nada. Vigoroso conta a dobrar, como na Garmin. */}
            <Painel titulo="Minutos de intensidade"
              extra={<span className="text-[10px] text-gray-600">soma dos 7 dias até cada dia</span>}>
              {historico.every(p => p.intensity_7d == null) ? (
                <SemDados>
                  Ainda não há dias que cheguem para uma semana — a soma precisa de pelo menos
                  quatro dias medidos.
                </SemDados>
              ) : (
                <>
                <GraficoBox>
                  <ComposedChart data={dadosHistorico}>
                    <CartesianGrid strokeDasharray="3 3" stroke={CINZA} />
                    <XAxis dataKey="dia" {...eixoX} />
                    <YAxis stroke="#555" fontSize={11} width={34} />
                    <Tooltip contentStyle={TOOLTIP} formatter={(v: any) => [`${v} min`, 'na semana']} />
                    <ReferenceLine y={ALVO_INTENSIDADE} stroke="#4ade80" strokeOpacity={0.5}
                      strokeDasharray="4 4" ifOverflow="extendDomain"
                      label={{ value: 'alvo 150', position: 'insideTopRight', fill: '#4ade80', fontSize: 10 }} />
                    <Area type="monotone" dataKey="intensity_7d" name="na semana" stroke="#4ade80"
                      strokeWidth={2} fill="#4ade80" fillOpacity={0.12} connectNulls />
                  </ComposedChart>
                </GraficoBox>
                <p className="text-[10px] text-gray-600 mt-2 shrink-0">
                  um minuto vigoroso vale por dois moderados, como a Garmin os conta
                </p>
                </>
              )}
            </Painel>

            {temProntidao && (
              <Painel titulo="Prontidão para treinar"
                extra={<span className="text-[10px] text-gray-600">de manhã, 0-100</span>}>
                <>
                <GraficoBox>
                  <ComposedChart data={dadosHistorico}>
                    <CartesianGrid strokeDasharray="3 3" stroke={CINZA} />
                    <XAxis dataKey="dia" {...eixoX} />
                    <YAxis domain={[0, 100]} stroke="#555" fontSize={11} width={30} />
                    <Tooltip contentStyle={TOOLTIP} formatter={(v: any) => [v, 'prontidão']} />
                    {faixaDe(regua('readiness'), '#22d3ee')}
                    <Bar dataKey="readiness" name="prontidão" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                      {dadosHistorico.map(p => (
                        <Cell key={p.date} fill={corDaProntidao(p.readiness)} />
                      ))}
                    </Bar>
                  </ComposedChart>
                </GraficoBox>
                <NotaDaFaixa regua={regua('readiness')} minimo={minimoDaFaixa} />
                </>
              </Painel>
            )}

            {dia && (
              <div className="lg:self-start">
                <Painel titulo="Os sete dias até aqui"
                  extra={<span className="text-[10px] text-gray-600">como no Garmin Connect</span>}>
                  <ASemana historico={historico} ate={dia.date} />
                </Painel>
              </div>
            )}

          {dia && (dia.body.fitness_age != null || dia.body.weight_kg != null) && (
            <Painel titulo="Corpo"
              extra={dia.body.weight_kg != null ? (
                <span className="text-xs text-gray-600">
                  {dia.body.weight_kg} kg
                  {dia.body.weight_date && ` · pesado a ${format(parseISO(dia.body.weight_date), 'd/M')}`}
                </span>
              ) : undefined}>
              <div className="flex items-end gap-5 flex-wrap">
                {dia.body.fitness_age != null && (
                  <div>
                    <p className="text-3xl font-bold leading-none tabular-nums text-emerald-400">
                      {dia.body.fitness_age.toFixed(0)}
                    </p>
                    <p className="text-[11px] text-gray-600 mt-1.5">
                      idade de fitness{dia.body.achievable_age != null ? ` · podes chegar a ${dia.body.achievable_age.toFixed(0)}` : ''}
                    </p>
                  </div>
                )}
                {dia.body.bmi != null && (
                  <div className="pl-5 border-l border-[#222]">
                    <p className="text-3xl font-bold leading-none tabular-nums">{dia.body.bmi.toFixed(1)}</p>
                    <p className="text-[11px] text-gray-600 mt-1.5">índice de massa corporal</p>
                  </div>
                )}
              </div>
              {dia.body.vigorous_min != null && dia.body.vigorous_min < 75 && (
                <p className="text-xs text-gray-500 mt-4">
                  Fazes <span className="text-gray-300">{Math.round(dia.body.vigorous_min)} min</span> de
                  exercício intenso por semana. A Garmin conta <span className="text-gray-300">75 min em 3 dias</span> para
                  baixar a idade de fitness.
                </p>
              )}
            </Painel>
          )}

          <div className={temCorpo ? COLUNAS_SPAN[2] : COLUNAS_SPAN[3]}>
          <Painel titulo="Treinos" extra={<span className="text-xs text-gray-600">{treinos.length} em {dias} dias</span>}>
            {treinos.length === 0 ? (
              <p className="text-sm text-gray-600">nenhum treino registado no relógio neste período</p>
            ) : (
              <div className="overflow-x-auto -mx-5 px-5">
                <table className="w-full text-sm min-w-[520px]">
                  <thead>
                    <tr className="text-xs text-gray-600 text-left">
                      <th className="pb-2 font-normal">Quando</th>
                      <th className="pb-2 font-normal">Tipo</th>
                      <th className="pb-2 font-normal text-right">Tempo</th>
                      <th className="pb-2 font-normal text-right">Distância</th>
                      <th className="pb-2 font-normal text-right">Ritmo</th>
                      <th className="pb-2 font-normal text-right">FC média</th>
                    </tr>
                  </thead>
                  <tbody>
                    {treinos.map(t => (
                      <tr key={t.id} className="border-t border-[#222]">
                        <td className="py-2.5 text-gray-400">
                          {format(parseISO(t.date), 'd/M', { locale: pt })}
                          <span className="text-gray-600"> {hora(t.start)}</span>
                        </td>
                        <td className="py-2.5 text-gray-300">
                          {t.name || TIPOS_DE_MOVIMENTO[t.type] || t.type.replace(/_/g, ' ')}
                          {t.auto && <span className="text-[10px] text-gray-600 ml-2">detectado</span>}
                        </td>
                        <td className="py-2.5 text-right text-gray-400">{t.duration_s ? minutos(Math.round(t.duration_s / 60)) : '—'}</td>
                        <td className="py-2.5 text-right text-gray-400">{t.distance_m ? `${(t.distance_m / 1000).toFixed(2)} km` : '—'}</td>
                        <td className="py-2.5 text-right text-gray-400">{ritmo(t) || '—'}</td>
                        <td className="py-2.5 text-right text-gray-400">{t.avg_hr ? `${t.avg_hr}` : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Painel>
          </div>
        </div>
      )}

      {estado && !semLigacao && <div className="shrink-0"><Aquecimento estado={estado} /></div>}
    </div>
  );
}
