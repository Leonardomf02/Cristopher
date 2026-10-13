import { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, Plus, Settings2, X } from 'lucide-react';
import { mealsApi, MealDay, MealScore, MealSlotRow, SupplementRow, SupplementScore } from '../api';

// Um ponto de cor por estado: chega para ler a linha de relance, sem etiquetas a
// competir com o nome da refeição.
const ESTADOS: Record<string, { texto: string; ponto: string; cor: string }> = {
  feito: { texto: 'a horas', ponto: 'bg-emerald-400', cor: 'text-emerald-400/90' },
  fora: { texto: 'fora de horas', ponto: 'bg-amber-400', cor: 'text-amber-400/90' },
  falhado: { texto: 'falhou', ponto: 'bg-rose-400/80', cor: 'text-rose-400/80' },
  aberto: { texto: 'a decorrer', ponto: 'bg-sky-400', cor: 'text-sky-400/90' },
  por_vir: { texto: 'por vir', ponto: 'bg-white/20', cor: 'text-gray-500' },
};

const hojeISO = () => new Date().toLocaleDateString('sv-SE');   // YYYY-MM-DD local

const horaDe = (iso: string) =>
  new Date(iso).toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' });

/** "2026-09-18" + "13:05" → ISO local que o backend lê como hora local. */
const comHora = (dia: string, hhmm: string) => `${dia}T${hhmm.length === 5 ? hhmm : '12:00'}:00`;

const corDoScore = (score: number | null | undefined) =>
  score == null ? 'text-gray-600'
    : score >= 80 ? 'text-emerald-400'
      : score >= 50 ? 'text-amber-400' : 'text-rose-400';

const traco = (score: number | null | undefined) =>
  score == null ? 'stroke-white/10'
    : score >= 80 ? 'stroke-emerald-400'
      : score >= 50 ? 'stroke-amber-400' : 'stroke-rose-400';

/** O score do dia num anel: um número sozinho não diz onde fica na escala. */
function Anel({ score, tamanho = 92 }: { score: number | null | undefined; tamanho?: number }) {
  const r = (tamanho - 8) / 2;
  const volta = 2 * Math.PI * r;
  return (
    <div className="relative shrink-0" style={{ width: tamanho, height: tamanho }}>
      <svg width={tamanho} height={tamanho} className="-rotate-90">
        <circle cx={tamanho / 2} cy={tamanho / 2} r={r} fill="none" strokeWidth={4} className="stroke-white/[0.07]" />
        <circle
          cx={tamanho / 2} cy={tamanho / 2} r={r} fill="none" strokeWidth={4} strokeLinecap="round"
          className={`${traco(score)} transition-all duration-500`}
          strokeDasharray={`${(volta * (score ?? 0)) / 100} ${volta}`}
        />
      </svg>
      <div className={`absolute inset-0 flex items-center justify-center text-xl font-semibold tabular-nums ${corDoScore(score)}`}>
        {score == null ? '—' : score}
      </div>
    </div>
  );
}

/** Duas semanas em barras finas. Sem altura = dia sem registo nenhum. */
function Barras({ dias, alvo }: { dias: { date: string; score: number | null }[]; alvo: number }) {
  return (
    <div className="flex items-end gap-[3px] h-9 flex-1 min-w-[90px]">
      {dias.slice(-14).map(d => (
        <div key={d.date} title={`${d.date}: ${d.score === null ? 'sem registo' : d.score + '%'}`}
             className="flex-1 h-full rounded-full bg-white/[0.04] relative overflow-hidden">
          <div className={`absolute bottom-0 inset-x-0 rounded-full ${
                d.score === null ? '' : d.score >= alvo ? 'bg-emerald-400/70'
                  : d.score > 0 ? 'bg-amber-400/60' : 'bg-rose-400/50'}`}
               style={{ height: `${d.score ?? 0}%` }} />
        </div>
      ))}
    </div>
  );
}

function Numero({ rotulo, valor }: { rotulo: string; valor: string | number }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.12em] text-gray-600">{rotulo}</div>
      <div className="text-sm font-medium tabular-nums mt-0.5">{valor}</div>
    </div>
  );
}

const CAMPO = "bg-transparent border-0 border-b border-white/[0.07] focus:border-white/25 " +
  "px-0 py-1 text-sm placeholder:text-gray-700 focus:outline-none transition-colors";

export default function MealsPage() {
  const [dia, setDia] = useState(hojeISO());
  const [dados, setDados] = useState<MealDay | null>(null);
  const [historico, setHistorico] = useState<MealScore | null>(null);
  const [histSup, setHistSup] = useState<SupplementScore | null>(null);
  const [sugestoes, setSugestoes] = useState<Record<string, string[]>>({});
  const [rascunho, setRascunho] = useState<Record<string, string>>({});
  const [lanche, setLanche] = useState('');
  const [definicoes, setDefinicoes] = useState(false);
  const [slots, setSlots] = useState<MealSlotRow[] | null>(null);

  const carregar = useCallback(async () => {
    const [d, h, hs] = await Promise.all([
      mealsApi.day(dia), mealsApi.score(30), mealsApi.supplementsScore(30),
    ]);
    setDados(d);
    setHistorico(h);
    setHistSup(hs);
    setRascunho(Object.fromEntries(d.slots.map(s => [s.key, s.log?.description || ''])));
  }, [dia]);

  useEffect(() => { carregar().catch(() => setDados(null)); }, [carregar]);

  // As sugestões são por refeição: o que se come ao pequeno-almoço não é o que se
  // come ao jantar, e uma lista única enchia-se de coisas que nunca servem.
  const pedirSugestoes = async (chave: string | null) => {
    const id = chave ?? '__lanche__';
    if (sugestoes[id]) return;
    try {
      const r = await mealsApi.suggestions(chave);
      setSugestoes(s => ({ ...s, [id]: r.map(x => x.text) }));
    } catch { /* sem sugestões não é erro */ }
  };

  const esquecerSugestoes = (chave: string) => setSugestoes(s => ({ ...s, [chave]: undefined as any }));

  const marcar = async (chave: string) => {
    await mealsApi.log({
      slot_key: chave,
      description: rascunho[chave] || '',
      date: dia,
      eaten_at: dia === hojeISO() ? undefined : comHora(dia, '12:00'),
    });
    esquecerSugestoes(chave);
    await carregar();
  };

  const guardarTexto = async (chave: string, logId?: number) => {
    if (logId) await mealsApi.updateLog(logId, { description: rascunho[chave] || '' });
    else if (rascunho[chave]) await marcar(chave);
    esquecerSugestoes(chave);
    await carregar();
  };

  const nomeDoDia = dia === hojeISO()
    ? 'Hoje'
    : new Date(dia).toLocaleDateString('pt-PT', { weekday: 'long', day: 'numeric', month: 'long' });

  const barras = useMemo(() => historico?.days || [], [historico]);

  return (
    <div className="max-w-3xl mx-auto space-y-10 pb-10">

      <header className="flex items-center gap-1">
        <h2 className="text-xl font-semibold tracking-tight capitalize mr-auto">{nomeDoDia}</h2>
        <button onClick={() => setDia(d => new Date(new Date(d).getTime() - 864e5).toLocaleDateString('sv-SE'))}
                className="p-2 rounded-full text-gray-500 hover:text-gray-200 hover:bg-white/5" aria-label="Dia anterior">
          <ChevronLeft size={17} />
        </button>
        <button onClick={() => setDia(d => new Date(new Date(d).getTime() + 864e5).toLocaleDateString('sv-SE'))}
                disabled={dia >= hojeISO()}
                className="p-2 rounded-full text-gray-500 hover:text-gray-200 hover:bg-white/5 disabled:opacity-25 disabled:hover:bg-transparent"
                aria-label="Dia seguinte">
          <ChevronRight size={17} />
        </button>
        <button onClick={() => setDefinicoes(v => !v)}
                className={`p-2 rounded-full hover:bg-white/5 ${definicoes ? 'text-gray-200' : 'text-gray-500 hover:text-gray-200'}`}
                title="Horas das refeições">
          <Settings2 size={17} />
        </button>
      </header>

      <section className="space-y-5">
        <div className="flex items-center gap-6">
          <Anel score={dados?.score} />
          <div className="flex-1 min-w-0 space-y-3">
            <div className="flex gap-6">
              <Numero rotulo="Média 7 dias" valor={historico?.avg_7 == null ? '—' : `${historico.avg_7}%`} />
              <Numero rotulo="Dias bons seguidos" valor={historico?.streak ?? 0} />
              <Numero rotulo="Decididas" valor={dados ? `${dados.decided}/${dados.total}` : '—'} />
            </div>
            <Barras dias={barras} alvo={historico?.good_day ?? 80} />
          </div>
        </div>

        {definicoes && <Definicoes slots={slots} setSlots={setSlots} aoMudar={carregar} />}

        <div className="rounded-2xl bg-white/[0.02] border border-white/[0.06] divide-y divide-white/[0.06]">
          {(dados?.slots || []).map(s => {
            const estado = ESTADOS[s.state] || ESTADOS.por_vir;
            const listaId = `sug-${s.key}`;
            return (
              <div key={s.key} className="px-4 py-3.5 space-y-2">
                <div className="flex items-center gap-3">
                  <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${estado.ponto}`} />
                  <span className="text-sm font-medium">{s.name}</span>
                  <span className="text-xs text-gray-600 tabular-nums">{s.start_time}–{s.end_time}</span>
                  <span className={`text-xs ml-auto ${estado.cor}`}>
                    {s.log ? horaDe(s.log.eaten_at) : estado.texto}
                  </span>
                </div>

                <div className="flex items-center gap-2 pl-[18px]">
                  <input
                    list={listaId}
                    value={rascunho[s.key] ?? ''}
                    onChange={e => setRascunho(r => ({ ...r, [s.key]: e.target.value }))}
                    onFocus={() => pedirSugestoes(s.key)}
                    onBlur={() => guardarTexto(s.key, s.log?.id)}
                    onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
                    placeholder="o que comeste"
                    className={`${CAMPO} flex-1 min-w-0`}
                  />
                  <datalist id={listaId}>
                    {(sugestoes[s.key] || []).map(t => <option key={t} value={t} />)}
                  </datalist>

                  {s.log ? (
                    <>
                      <input
                        type="time"
                        defaultValue={horaDe(s.log.eaten_at)}
                        onChange={async e => {
                          if (e.target.value) {
                            await mealsApi.updateLog(s.log!.id, { eaten_at: comHora(dia, e.target.value) });
                            carregar();
                          }
                        }}
                        className="bg-transparent text-xs text-gray-500 hover:text-gray-300 focus:outline-none tabular-nums"
                      />
                      <button onClick={async () => { await mealsApi.deleteLog(s.log!.id); carregar(); }}
                              className="p-1 rounded-full text-gray-700 hover:text-gray-300 hover:bg-white/5" title="Desmarcar">
                        <X size={14} />
                      </button>
                    </>
                  ) : (
                    <button onClick={() => marcar(s.key)}
                            className="shrink-0 px-3 py-1 rounded-full text-xs font-medium bg-white/[0.06] hover:bg-white/[0.12] transition-colors">
                      comi
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <Suplementos lista={dados?.supplements || []} dia={dia} aoMudar={carregar}
                   hoje={dados?.supplements_score} historico={histSup} />

      <section className="space-y-3">
        <h3 className="text-[11px] uppercase tracking-[0.14em] text-gray-500">
          Lanches <span className="text-gray-700 normal-case tracking-normal">· fora do score</span>
        </h3>

        <div className="space-y-1.5">
          {(dados?.snacks || []).map(l => (
            <div key={l.id} className="group flex items-center gap-3 text-sm py-1">
              <span className="text-xs text-gray-600 tabular-nums w-10">{horaDe(l.eaten_at)}</span>
              <span className="flex-1 truncate text-gray-300">{l.description || '—'}</span>
              <button onClick={async () => { await mealsApi.deleteLog(l.id); carregar(); }}
                      className="p-1 rounded-full text-gray-700 hover:text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity">
                <X size={14} />
              </button>
            </div>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <input
            list="sug-lanche"
            value={lanche}
            onChange={e => setLanche(e.target.value)}
            onFocus={() => pedirSugestoes(null)}
            onKeyDown={async e => {
              if (e.key !== 'Enter' || !lanche.trim()) return;
              await mealsApi.log({
                description: lanche.trim(), date: dia,
                eaten_at: dia === hojeISO() ? undefined : comHora(dia, '17:00'),
              });
              setLanche('');
              esquecerSugestoes('__lanche__');
              carregar();
            }}
            placeholder="apontar um lanche"
            className={`${CAMPO} flex-1`}
          />
          <datalist id="sug-lanche">
            {(sugestoes['__lanche__'] || []).map(t => <option key={t} value={t} />)}
          </datalist>
          <span className="text-[10px] text-gray-700">enter</span>
        </div>
      </section>
    </div>
  );
}

/** Suplementos: pastilhas que se carregam. A lista é dele — proteína e creatina
 *  são só o que vem proposto à primeira. */
function Suplementos({ lista, dia, aoMudar, hoje, historico }: {
  lista: SupplementRow[];
  dia: string;
  aoMudar: () => Promise<void>;
  hoje?: { score: number | null; taken: number; total: number };
  historico: SupplementScore | null;
}) {
  const [novo, setNovo] = useState({ name: '', dose: '', time_hint: '', notify: false });
  const [aJuntar, setAJuntar] = useState(false);

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-3">
        <h3 className="text-[11px] uppercase tracking-[0.14em] text-gray-500">Suplementos</h3>
        <span className="text-xs text-gray-600 tabular-nums">{hoje ? `${hoje.taken}/${hoje.total}` : ''}</span>
        <span className={`text-xs font-medium tabular-nums ${corDoScore(hoje?.score)}`}>
          {hoje?.score == null ? '' : `${hoje.score}%`}
        </span>
        <button onClick={() => setAJuntar(v => !v)}
                className="ml-auto p-1.5 rounded-full text-gray-600 hover:text-gray-200 hover:bg-white/5"
                title="Juntar suplemento">
          <Plus size={15} />
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {lista.map(s => {
          const tomado = !!s.taken_at;
          return (
            <div key={s.id} className="group relative">
              <button
                onClick={async () => { await mealsApi.takeSupplement(s.id, !tomado, dia); aoMudar(); }}
                title={tomado ? `Tomado às ${horaDe(s.taken_at!)} — carrega para desmarcar` : 'Marcar como tomado'}
                className={`px-3.5 py-1.5 rounded-full text-sm border transition-colors ${
                  tomado
                    ? 'bg-emerald-400/10 border-emerald-400/30 text-emerald-300'
                    : 'bg-white/[0.02] border-white/[0.08] text-gray-400 hover:text-gray-200 hover:border-white/20'
                }`}
              >
                {s.name}
                {s.dose && <span className={`ml-1.5 text-xs ${tomado ? 'text-emerald-400/60' : 'text-gray-600'}`}>{s.dose}</span>}
                {s.time_hint && (
                  <span className="ml-1.5 text-[10px] text-gray-600 tabular-nums">
                    {s.time_hint}{s.notify ? ' ·' : ''}
                  </span>
                )}
              </button>
              <button
                onClick={async () => { await mealsApi.deleteSupplement(s.id); aoMudar(); }}
                title="Apagar da lista"
                className="absolute -top-1.5 -right-1.5 p-0.5 rounded-full bg-[#1a1a1a] border border-white/10 text-gray-500
                           opacity-0 group-hover:opacity-100 transition-opacity hover:text-rose-300"
              >
                <X size={11} />
              </button>
            </div>
          );
        })}
        {!lista.length && <span className="text-xs text-gray-700">nenhum na lista</span>}
      </div>

      {historico && (
        <div className="flex items-center gap-6 pt-1">
          <Numero rotulo="Média 7 dias" valor={historico.avg_7 == null ? '—' : `${historico.avg_7}%`} />
          <Numero rotulo="Dias completos" valor={historico.streak} />
          <Barras dias={historico.days} alvo={historico.good_day} />
        </div>
      )}

      {aJuntar && (
        <div className="flex flex-wrap items-center gap-3 pt-2">
          <input value={novo.name} onChange={e => setNovo(n => ({ ...n, name: e.target.value }))}
                 placeholder="nome" className={`${CAMPO} w-36`} />
          <input value={novo.dose} onChange={e => setNovo(n => ({ ...n, dose: e.target.value }))}
                 placeholder="dose" className={`${CAMPO} w-24`} />
          <input type="time" value={novo.time_hint} onChange={e => setNovo(n => ({ ...n, time_hint: e.target.value }))}
                 title="hora do aviso (opcional)"
                 className="bg-transparent text-sm text-gray-400 tabular-nums focus:outline-none" />
          <label className="flex items-center gap-1.5 text-xs text-gray-500">
            <input type="checkbox" checked={novo.notify}
                   onChange={e => setNovo(n => ({ ...n, notify: e.target.checked }))} />
            avisar
          </label>
          <button
            onClick={async () => {
              if (!novo.name.trim()) return;
              await mealsApi.createSupplement({
                name: novo.name.trim(), dose: novo.dose.trim(),
                time_hint: novo.time_hint || null, notify: novo.notify && !!novo.time_hint,
              });
              setNovo({ name: '', dose: '', time_hint: '', notify: false });
              setAJuntar(false);
              await aoMudar();
            }}
            className="px-3 py-1 rounded-full text-xs font-medium bg-white/[0.06] hover:bg-white/[0.12]">
            juntar
          </button>
        </div>
      )}
    </section>
  );
}

/** As horas de cada refeição e os avisos. */
function Definicoes({ slots, setSlots, aoMudar }: {
  slots: MealSlotRow[] | null;
  setSlots: (s: MealSlotRow[]) => void;
  aoMudar: () => Promise<void>;
}) {
  const [novo, setNovo] = useState({ name: '', start_time: '16:00', end_time: '17:00' });

  useEffect(() => { mealsApi.slots().then(setSlots).catch(() => setSlots([])); }, [setSlots]);

  const guardar = async (s: MealSlotRow, campos: Partial<MealSlotRow>) => {
    const actualizado = { ...s, ...campos };
    setSlots((slots || []).map(x => (x.id === s.id ? actualizado : x)));
    await mealsApi.updateSlot(s.id, {
      name: actualizado.name, start_time: actualizado.start_time, end_time: actualizado.end_time,
      notify: actualizado.notify, active: actualizado.active,
    });
    await aoMudar();
  };

  return (
    <div className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-4 space-y-3">
      <h3 className="text-[11px] uppercase tracking-[0.14em] text-gray-500">Horas e avisos</h3>

      {(slots || []).map(s => (
        <div key={s.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <input value={s.name}
                 onChange={e => setSlots((slots || []).map(x => x.id === s.id ? { ...x, name: e.target.value } : x))}
                 onBlur={() => guardar(s, {})}
                 className={`${CAMPO} w-32`} />
          <input type="time" value={s.start_time} onChange={e => guardar(s, { start_time: e.target.value })}
                 className={`${CAMPO} tabular-nums text-gray-400`} />
          <span className="text-xs text-gray-700">até</span>
          <input type="time" value={s.end_time} onChange={e => guardar(s, { end_time: e.target.value })}
                 className={`${CAMPO} tabular-nums text-gray-400`} />
          <label className="flex items-center gap-1.5 text-xs text-gray-500">
            <input type="checkbox" checked={s.notify} onChange={e => guardar(s, { notify: e.target.checked })} />
            avisos
          </label>
          <label className="flex items-center gap-1.5 text-xs text-gray-500">
            <input type="checkbox" checked={s.active} onChange={e => guardar(s, { active: e.target.checked })} />
            activa
          </label>
          <button onClick={async () => { await mealsApi.deleteSlot(s.id); setSlots(await mealsApi.slots()); aoMudar(); }}
                  className="ml-auto p-1 rounded-full text-gray-700 hover:text-rose-300 hover:bg-white/5"
                  title="Apagar refeição">
            <X size={14} />
          </button>
        </div>
      ))}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-3 border-t border-white/[0.06]">
        <input value={novo.name} onChange={e => setNovo(n => ({ ...n, name: e.target.value }))}
               placeholder="nova refeição" className={`${CAMPO} w-36`} />
        <input type="time" value={novo.start_time} onChange={e => setNovo(n => ({ ...n, start_time: e.target.value }))}
               className={`${CAMPO} tabular-nums text-gray-400`} />
        <span className="text-xs text-gray-700">até</span>
        <input type="time" value={novo.end_time} onChange={e => setNovo(n => ({ ...n, end_time: e.target.value }))}
               className={`${CAMPO} tabular-nums text-gray-400`} />
        <button
          onClick={async () => {
            if (!novo.name.trim()) return;
            await mealsApi.createSlot({ ...novo, name: novo.name.trim() });
            setNovo({ name: '', start_time: '16:00', end_time: '17:00' });
            setSlots(await mealsApi.slots());
            await aoMudar();
          }}
          className="px-3 py-1 rounded-full text-xs font-medium bg-white/[0.06] hover:bg-white/[0.12]">
          juntar
        </button>
      </div>
    </div>
  );
}
