import { useState, useEffect, useRef } from 'react';
import { format, startOfMonth, endOfMonth, subMonths, addMonths, addDays, differenceInCalendarDays, getDaysInMonth, isSameMonth } from 'date-fns';
import { pt } from 'date-fns/locale';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { inkColor } from '../theme';
import { Plus, X, Upload, Loader2, Clock, MapPin, Tag, Landmark, Trash2, ChevronLeft, ChevronRight, Receipt, FileSpreadsheet, FileText, Sparkles, Pencil, CreditCard, AlertTriangle, PiggyBank, Gift, Check, ExternalLink, Search, TrendingUp, Users, HandCoins } from 'lucide-react';
import { PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip } from 'recharts';
import { expensesApi, budgetsApi, wishlistApi, bankingApi, BankBalances, BankStatus, BankRule, CitySpending, WishPlan , ExpenseKind, KlarnaPorPagar, KlarnaPlano, DiaDeSalario, Reembolsos, ContaParaDescontar, WishCandidate } from '../api';
import { Expense, ExpenseCreate, ExpenseSummary } from '../types';
import { useCategorias, infoCategoria, criaCategoria, apagaCategoria } from '../expenseCategories';


// Pagamentos repetidos com o mesmo valor que ainda não estão registados como subscrição.
function SubscricoesDetectadas({ onAdded }: { onAdded: () => void }) {
  const [lista, setLista] = useState<Awaited<ReturnType<typeof budgetsApi.detectSubscriptions>>>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [ignoradas, setIgnoradas] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem('subsIgnoradas') || '[]'); } catch { return []; }
  });

  const carregar = () => { budgetsApi.detectSubscriptions().then(setLista).catch(() => setLista([])); };
  useEffect(() => { carregar(); }, []);

  const visiveis = lista.filter(c => !ignoradas.includes(c.key));
  if (visiveis.length === 0) return null;

  const adicionar = async (c: typeof visiveis[number]) => {
    setBusy(c.key);
    try {
      await budgetsApi.createSubscription({
        name: c.name, amount: c.amount, currency: 'EUR', billing_cycle: 'monthly',
        next_renewal: c.last_date, category: c.category || 'subscriptions', notes: 'detectada nos gastos',
      });
      carregar();
      onAdded();
    } finally { setBusy(null); }
  };

  const ignorar = (key: string) => {
    const novo = [...ignoradas, key];
    setIgnoradas(novo);
    try { localStorage.setItem('subsIgnoradas', JSON.stringify(novo)); } catch { /* ignora */ }
  };

  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 mb-6">
      <h3 className="text-sm font-medium text-gray-300 mb-1">Parecem subscrições</h3>
      <p className="text-xs text-gray-500 mb-3">Mesmo valor a repetir-se em 3 ou mais meses, e ainda não estão na lista.</p>
      <div className="space-y-1.5">
        {visiveis.map(c => (
          <div key={c.key} className="flex items-center gap-3 text-xs">
            <span className="flex-1 min-w-0 truncate text-gray-300">{c.name}</span>
            <span className="text-gray-500 shrink-0">€{c.amount.toFixed(2)}/mês · {c.months} meses</span>
            <button onClick={() => adicionar(c)} disabled={busy === c.key}
              className="px-2 py-1 rounded-lg bg-green-500/15 text-green-300 hover:bg-green-500/25 disabled:opacity-40 shrink-0">
              adicionar
            </button>
            <button onClick={() => ignorar(c.key)} className="text-gray-600 hover:text-gray-400 shrink-0">ignorar</button>
          </div>
        ))}
      </div>
    </div>
  );
}

// As regras que ele criou ao corrigir a categoria de um movimento do banco. No
// MB Way a regra é do número de telefone: a transferência para o ginásio passa a
// Subscrições, e as dos amigos ficam como estão.
function RegrasDoBanco() {
  const [regras, setRegras] = useState<BankRule[] | null>(null);
  const [aberto, setAberto] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);
  const categorias = useCategorias();

  const carregar = () => bankingApi.rules().then(setRegras).catch(() => setRegras([]));
  useEffect(() => { if (aberto && regras === null) carregar(); }, [aberto]);

  const mudar = async (r: BankRule, category: string) => {
    const nova = await bankingApi.updateRule(r.id, category);
    setAviso(nova.changed ? `${nova.changed} movimentos de ${r.label} passaram a ${catLabel(category)}` : null);
    carregar();
  };
  const apagar = async (r: BankRule) => {
    await bankingApi.removeRule(r.id);
    setAviso(null);
    carregar();
  };

  return (
    <div className="mt-2">
      <button onClick={() => setAberto(a => !a)} className="text-[11px] text-gray-400 hover:text-gray-200">
        {aberto ? '▾' : '▸'} as tuas regras{regras ? ` (${regras.length})` : ''}
      </button>
      {aberto && (
        <div className="mt-1.5 space-y-1">
          <p className="text-[10px] text-gray-600">
            Para criar uma, muda a categoria de um movimento do banco e marca «pôr também os outros movimentos…»: os iguais vão atrás, agora e nos que vierem.
            No MB Way conta o número — mudar a do ginásio não mexe nas dos amigos.
          </p>
          {regras?.length === 0 && <p className="text-[11px] text-gray-500">ainda não há nenhuma</p>}
          {regras?.map(r => (
            <div key={r.id} className="flex items-center gap-2 text-[11px]">
              <span className="flex-1 min-w-0 truncate text-gray-300" title={r.key}>{r.label}</span>
              <span className="text-gray-600 shrink-0">{r.expenses} mov.</span>
              <select value={r.category} onChange={e => mudar(r, e.target.value)}
                className="bg-white/5 rounded px-1.5 py-1 text-gray-200 shrink-0">
                {categorias.map(c => <option key={c.value} value={c.value}>{c.emoji} {c.label}</option>)}
              </select>
              <button onClick={() => apagar(r)} title="apagar a regra (os movimentos ficam como estão)"
                className="text-gray-500 hover:text-red-400 shrink-0"><Trash2 size={12} /></button>
            </div>
          ))}
          {aviso && <p className="text-[11px] text-emerald-300">{aviso}</p>}
        </div>
      )}
    </div>
  );
}

const catLabel = (v: string) => infoCategoria(v).label;

// Ligar o banco: as despesas passam a entrar sozinhas todos os dias. O banco só
// mostra ~90 dias para trás, mas cada sincronização grava aqui — o histórico
// fica permanente deste lado.
function BancoLigado() {
  const [st, setSt] = useState<BankStatus | null>(null);
  const [bancos, setBancos] = useState<{ id: string; name: string; days: string; sandbox?: boolean }[]>([]);
  const [aEscolher, setAEscolher] = useState(false);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [colado, setColado] = useState('');
  const [busca, setBusca] = useState('');
  const usados = useRef<Set<string>>(new Set());

  const carregar = () => bankingApi.status().then(setSt).catch(() => setSt(null));
  useEffect(() => { carregar(); }, []);

  // Ao voltar do banco, o endereço traz o código da autorização: a app conclui
  // a ligação sozinha e limpa o endereço.
  useEffect(() => {
    if (!st) return;
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    if (!code) return;
    const pendente = st.connections.find(c => c.status === 'pendente');
    if (!pendente) return;
    window.history.replaceState({}, '', '/expenses');
    concluir(pendente.id, code);
  }, [st]);

  if (!st) return null;

  const abrirEscolha = async () => {
    setAEscolher(true);
    setErro(null);
    try {
      setBancos(await bankingApi.institutions('PT'));
    } catch (e: any) {
      setErro(e?.message || 'não consegui ir buscar os bancos');
    }
  };

  const ligar = async (id: string) => {
    setOcupado(id);
    try {
      // em produção o banco só devolve para https: se estivermos em localhost o
      // backend usa o endereço da tailnet (mesmo Mac, mesma app)
      const meu = window.location.protocol === 'https:' ? `${window.location.origin}/expenses` : '';
      const r = await bankingApi.connect(id, meu);
      window.location.href = r.link;      // aprovar no site do banco
    } catch (e: any) {
      setErro(e?.message || 'não consegui criar a ligação');
    } finally { setOcupado(null); }
  };

  const concluir = (id: number, code: string) => {
    usados.current.add(code);
    return bankingApi.finish(id, code)
      .then(r => {
        setColado('');
        if (r.imported) setAviso(`ligado — entraram ${r.imported} movimentos do banco`);
        else if (r.hint) setErro(r.hint);
        carregar();
      })
      .catch((e: any) => setErro(e?.message || 'não consegui concluir a ligação'));
  };

  const concluirComTexto = (id: number) => {
    const texto = colado.trim();
    const code = texto.includes('code=')
      ? new URLSearchParams(texto.split('?')[1] || '').get('code') || ''
      : texto;
    if (!code) { setErro('não encontrei o código nesse endereço'); return; }
    // A app já tentou concluir sozinha ao voltar do banco. O código é de uso
    // único: mandá-lo outra vez só devolve "Wrong authorization code".
    if (usados.current.has(code)) {
      setErro('esse código já foi usado — autoriza outra vez em "concluir no banco"');
      return;
    }
    concluir(id, code);
  };

  const esquecer = (id: number) =>
    bankingApi.remove(id).then(() => { setErro(null); setAviso(null); carregar(); });

  const aprender = async () => {
    setOcupado('learn');
    try {
      const r = await bankingApi.learn();
      setAviso(r.aprendidas ? `aprendi ${r.aprendidas} lojas novas (${r.despesas} despesas arrumadas)`
                            : 'não consegui perceber as que faltam');
      await carregar();
    } catch (e: any) { setErro(e?.message || 'falhou'); }
    finally { setOcupado(null); }
  };

  const sincronizar = async () => {
    setOcupado('sync');
    try { await bankingApi.sync(30); await carregar(); }
    catch (e: any) { setErro(e?.message || 'falhou'); }
    finally { setOcupado(null); }
  };

  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 sm:p-5 mb-6">
      <div className="flex items-baseline justify-between gap-2 mb-1 flex-wrap">
        <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
          <Landmark size={15} className="text-emerald-400" /> Banco
        </h3>
        {st.synced_expenses > 0 && (
          <span className="text-[11px] text-gray-500">{st.synced_expenses} despesas vindas do banco</span>
        )}
      </div>

      {!st.configured ? (
        <p className="text-[11px] text-gray-500">
          Falta ligar a aplicação do <span className="text-gray-300">Enable Banking</span> (grátis para as tuas
          próprias contas): <span className="text-gray-300">ENABLEBANKING_APP_ID</span> no{' '}
          <span className="text-gray-300">backend/.env</span> e a chave privada em{' '}
          <span className="text-gray-300">backend/enablebanking.pem</span>. Os passos estão no CLAUDE.md.
        </p>
      ) : st.connections.length === 0 || aEscolher ? (
        <>
          {st.warning && <p className="text-[11px] text-amber-400 mb-2">{st.warning}</p>}
          {st.connections.length === 0 && (
            <p className="text-[11px] text-gray-500 mb-2">
              Autorizas uma vez e as transacções passam a entrar sozinhas. Hoje dependes de exportar
              ficheiros do Revolut à mão.
            </p>
          )}
          {!aEscolher ? (
            <button onClick={abrirEscolha}
              className="text-[11px] px-2.5 py-1.5 rounded-lg bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25">
              escolher banco
            </button>
          ) : (
            <>
              <input value={busca} onChange={e => setBusca(e.target.value)} placeholder="procurar banco…"
                className="w-full bg-[#1a1a1a] border border-[#333] rounded-lg px-3 py-1.5 text-xs mb-2" />
              <div className="max-h-56 overflow-y-auto space-y-1">
                {bancos.filter(b => b.name.toLowerCase().includes(busca.toLowerCase())).slice(0, 30).map(b => (
                  <button key={b.id} onClick={() => ligar(b.id)} disabled={ocupado === b.id}
                    className="w-full flex items-center justify-between gap-2 text-left text-xs px-2.5 py-1.5 rounded-lg bg-[#1a1a1a] hover:bg-white/5 disabled:opacity-40">
                    <span className="truncate">{b.name}{b.sandbox && <span className="text-gray-600"> · teste</span>}</span>
                    <span className="text-[10px] text-gray-600 shrink-0">{b.days} dias</span>
                  </button>
                ))}
              </div>
              <button onClick={() => { setAEscolher(false); setBusca(''); }}
                className="mt-2 text-[11px] text-gray-500 hover:text-gray-300">cancelar</button>
            </>
          )}
        </>
      ) : (
        <div className="space-y-2">
          {st.connections.map(c => (
            <div key={c.id} className="bg-[#1a1a1a] rounded-xl px-3 py-2">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <span className="text-xs font-medium">{c.institution}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                  c.status === 'ligado' ? 'bg-emerald-500/15 text-emerald-300'
                    : c.status === 'expirado' ? 'bg-red-500/15 text-red-300'
                    : 'bg-amber-500/15 text-amber-300'
                }`}>{c.status}</span>
              </div>
              {(() => {
                // o Revolut devolve uma conta por moeda; as vazias não merecem
                // uma linha cada, senão o cartão fica com sete linhas iguais
                const usadas = c.accounts.filter(a => (a.balance ?? 0) !== 0 || a.last_transaction);
                const vazias = c.accounts.length - usadas.length;
                return (
                  <>
                    {usadas.map(a => (
                      <p key={a.id} className="text-[11px] text-gray-500 mt-0.5">
                        {a.currency} ••{a.iban}
                        {a.balance !== null && ` · ${a.balance.toFixed(2)}${a.currency === 'EUR' ? '€' : ' ' + a.currency}`}
                        {a.last_transaction && ` · último movimento ${a.last_transaction}`}
                      </p>
                    ))}
                    {vazias > 0 && (
                      <p className="text-[11px] text-gray-600 mt-0.5">
                        +{vazias} {vazias === 1 ? 'conta vazia' : 'contas vazias'} noutras moedas
                      </p>
                    )}
                  </>
                );
              })()}
              {c.status === 'pendente' && (
                <div className="mt-1 space-y-1">
                  {c.link && (
                    <a href={c.link} className="inline-block text-[11px] text-emerald-300 hover:underline">
                      concluir no banco →
                    </a>
                  )}
                  {/* se o regresso do banco falhar (endereço https fora do ar), o
                      código continua no endereço — basta colá-lo aqui */}
                  <div className="flex gap-1">
                    <input value={colado} onChange={e => setColado(e.target.value)}
                      placeholder="ou cola aqui o endereço a que o banco te devolveu"
                      className="flex-1 bg-[#111] border border-[#333] rounded-lg px-2 py-1 text-[11px]" />
                    <button onClick={() => concluirComTexto(c.id)} disabled={!colado.trim()}
                      className="text-[11px] px-2 py-1 rounded-lg bg-emerald-500/15 text-emerald-300 disabled:opacity-30">
                      concluir
                    </button>
                    {/* cada tentativa deixa uma linha pendente; sem isto acumulam-se */}
                    <button onClick={() => esquecer(c.id)} title="apagar esta tentativa"
                      className="text-[11px] px-2 py-1 rounded-lg text-gray-600 hover:text-gray-300">
                      esquecer
                    </button>
                  </div>
                </div>
              )}
              {(c.status === 'expirado' || (c.expires_in_days !== null && c.expires_in_days < 21)) && (
                <div className="mt-1">
                  <p className="text-[11px] text-amber-400">
                    {c.status === 'expirado'
                      ? 'a autorização caducou — o banco deixou de dar movimentos'
                      : `a autorização caduca em ${c.expires_in_days} dias — o banco obriga a renovar`}
                  </p>
                  <button onClick={() => ligar(c.institution_id)} disabled={ocupado === c.institution_id}
                    className="mt-1 text-[11px] px-2.5 py-1.5 rounded-lg bg-amber-500/15 text-amber-300 hover:bg-amber-500/25 disabled:opacity-40">
                    renovar autorização
                  </button>
                  <p className="text-[10px] text-gray-600 mt-1">
                    ao renovar, o banco volta a dar o histórico todo — vale a pena não deixar caducar
                  </p>
                </div>
              )}
              {c.last_error && <p className="text-[10px] text-red-400 mt-1">{c.last_error}</p>}
            </div>
          ))}
          <div className="flex items-center gap-2">
            <button onClick={sincronizar} disabled={ocupado === 'sync'}
              className="text-[11px] px-2.5 py-1.5 rounded-lg bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-40">
              {ocupado === 'sync' ? 'a sincronizar…' : 'sincronizar agora'}
            </button>
            {st.unknown_merchants > 0 && (
              <button onClick={aprender} disabled={ocupado === 'learn'}
                className="text-[11px] px-2.5 py-1.5 rounded-lg bg-white/5 text-gray-300 hover:bg-white/10 disabled:opacity-40">
                {ocupado === 'learn' ? 'a classificar…' : `classificar ${st.unknown_merchants} por perceber`}
              </button>
            )}
            <button onClick={abrirEscolha}
              className="text-[11px] px-2.5 py-1.5 rounded-lg bg-white/5 text-gray-300 hover:bg-white/10">
              ligar outro banco
            </button>
            <span className="text-[10px] text-gray-600">
              corre sozinho todos os dias · {st.learned_merchants} lojas aprendidas
            </span>
          </div>
          <RegrasDoBanco />
        </div>
      )}
      {aviso && <p className="text-[11px] text-emerald-300 mt-2">{aviso}</p>}
      {erro && <p className="text-[11px] text-amber-400 mt-2">{erro}</p>}
    </div>
  );
}

// Quanto custa a vida dele: o que é inevitável, o que é escolha, e quanto tempo
// aguenta sem entrar nada. A app tinha orçamento e previsão, mas não o retrato.
function CustoDeVida() {
  const [d, setD] = useState<Awaited<ReturnType<typeof budgetsApi.costOfLiving>> | null>(null);

  useEffect(() => { budgetsApi.costOfLiving(6).then(setD).catch(() => setD(null)); }, []);
  if (!d || !d.enough) return null;

  const pctFixo = d.monthly_cost > 0 ? (d.fixed_monthly / d.monthly_cost) * 100 : 0;
  const sobra = d.income_monthly - d.monthly_cost;

  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 sm:p-5 mb-6">
      <div className="flex items-baseline justify-between gap-2 mb-1 flex-wrap">
        <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
          <PiggyBank size={15} className="text-emerald-400" /> Quanto custa a tua vida
        </h3>
        <span className="text-[11px] text-gray-500">mediana de {d.months} meses</span>
      </div>

      <div className="flex items-end gap-3 mt-2 mb-3 flex-wrap">
        <span className="text-3xl font-bold">€{d.monthly_cost.toFixed(0)}<span className="text-sm text-gray-500">/mês</span></span>
        {d.income_monthly > 0 && (
          <span className={`text-xs pb-1.5 ${sobra >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {sobra >= 0 ? `sobram €${sobra.toFixed(0)}` : `faltam €${Math.abs(sobra).toFixed(0)}`} do rendimento de €{d.income_monthly.toFixed(0)}
            {d.saving_rate_pct !== null && ` · poupas ${d.saving_rate_pct}%`}
          </span>
        )}
      </div>

      <div className="h-2 rounded-full bg-[#1a1a1a] overflow-hidden flex mb-1.5">
        <div className="h-full bg-blue-500/70" style={{ width: `${pctFixo}%` }} title="fixos" />
        <div className="h-full bg-amber-500/70" style={{ width: `${100 - pctFixo}%` }} title="dia-a-dia" />
      </div>
      <div className="flex items-center justify-between text-[11px] text-gray-500 mb-3">
        <span><span className="text-blue-400">■</span> inevitável €{d.fixed_monthly.toFixed(0)} (contas e subscrições)</span>
        <span><span className="text-amber-400">■</span> dia-a-dia €{d.variable_monthly.toFixed(0)}</span>
      </div>

      {d.occasional_monthly > 0 && (
        <p className="text-[11px] text-gray-500 mb-2">
          Fora desta conta: <span className="text-gray-300">viagens e compras grandes</span> — €{d.occasional_total.toFixed(0)} nos
          últimos {d.months} meses (mediana €{d.occasional_monthly.toFixed(0)}/mês). Entram por fases, por isso
          não contam para o que a vida custa todos os meses.
        </p>
      )}

      {d.months_covered !== null && (
        <p className="text-[11px] text-gray-500">
          Com os €{d.buffer_eur.toFixed(0)} que tens investidos aguentavas{' '}
          <span className={d.months_covered < 3 ? 'text-amber-400' : 'text-gray-300'}>
            {d.months_covered} {d.months_covered === 1 ? 'mês' : 'meses'}
          </span>{' '}sem entrar nada.
        </p>
      )}

      {d.biggest_variable.length > 0 && (
        <p className="text-[11px] text-gray-600 mt-1.5">
          O que mais pesa no dia-a-dia: {d.biggest_variable.slice(0, 3).map(c => `${infoCategoria(c.category).label} ${c.share}%`).join(' · ')}
        </p>
      )}
    </div>
  );
}

// Mapa de gastos por cidade: as coordenadas entram directamente numa projecção
// simples, sem depender de nenhum mapa de fora. O tamanho da bola é o dinheiro.
function MapaDeGastos({ ano }: { ano: number }) {
  const navigate = useNavigate();
  const [dados, setDados] = useState<CitySpending | null>(null);
  const [ativa, setAtiva] = useState<string | null>(null);

  useEffect(() => { setAtiva(null); expensesApi.byCity(ano).then(setDados).catch(() => setDados(null)); }, [ano]);
  if (!dados || dados.cities.length === 0) return null;

  // Uma cidade fora da Europa (São Francisco) esmagava tudo num canto: os limites
  // saem dos percentis e o que fica fora encosta à margem.
  const lats = dados.cities.map(c => c.lat), lons = dados.cities.map(c => c.lon);
  const percentil = (arr: number[], p: number) => {
    const o = [...arr].sort((a, b) => a - b);
    return o[Math.min(o.length - 1, Math.max(0, Math.round((o.length - 1) * p)))];
  };
  const limita = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
  const minLat = percentil(lats, 0.05) - 2, maxLat = percentil(lats, 0.95) + 2;
  const minLon = percentil(lons, 0.05) - 2, maxLon = percentil(lons, 0.95) + 2;
  const W = 640, H = 320;
  const kx = Math.cos(((minLat + maxLat) / 2) * Math.PI / 180);
  const larguraGeo = Math.max(0.1, (maxLon - minLon) * kx), alturaGeo = Math.max(0.1, maxLat - minLat);
  const escala = Math.min(W / larguraGeo, H / alturaGeo);
  const offX = (W - larguraGeo * escala) / 2, offY = (H - alturaGeo * escala) / 2;
  const x = (lon: number) => offX + (limita(lon, minLon, maxLon) - minLon) * kx * escala;
  const y = (lat: number) => H - offY - (limita(lat, minLat, maxLat) - minLat) * escala;
  const maxTotal = Math.max(...dados.cities.map(c => c.total));
  const raio = (t: number) => 4 + Math.sqrt(t / maxTotal) * 15;
  const comNome = new Set(dados.cities.slice(0, 5).map(c => c.city));
  const bandeira = (iso2: string) =>
    iso2 ? iso2.toUpperCase().replace(/./g, ch => String.fromCodePoint(127397 + ch.charCodeAt(0))) : '📍';
  const sel = dados.cities.find(c => c.city === ativa) || null;

  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 sm:p-5
      flex flex-col lg:flex-1 lg:min-h-0">
      <div className="flex items-center justify-between gap-2 mb-1 flex-wrap shrink-0">
        <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
          <MapPin size={15} className="text-blue-400" /> Onde gastaste em {ano}
        </h3>
        <span className="text-[11px] text-gray-500">
          {dados.cities.length} cidades · €{dados.total.toFixed(0)}
        </span>
      </div>
      <p className="text-[11px] text-gray-500 mb-3 shrink-0">
        {dados.unknown.count > 0 && <>{dados.unknown.count} transacções sem cidade (€{dados.unknown.total.toFixed(0)})</>}
      </p>

      {/* O mapa e a lista lado a lado: numa coluna só, as cidades ficavam a
          seguir a um mapa de 320px de altura e nunca se viam ao mesmo tempo. */}
      <div className="flex flex-col lg:flex-row gap-4 lg:flex-1 lg:min-h-0">
      {/* O mapa desenha-se pela altura que sobra, não pela largura: com
          `height: auto` um mapa numa coluna de 1000px ficava com 500px de altura
          e empurrava a página inteira para o scroll. */}
      <div className="overflow-x-auto lg:flex-1 lg:min-w-0 lg:min-h-0">
        {/* a altura tem de vir da classe: um `style={{height:'auto'}}` ganha ao
            `lg:h-full` e o mapa voltava a crescer com a largura */}
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
          className="w-full min-w-[420px] h-auto lg:h-full">
          <rect x={0} y={0} width={W} height={H} rx={12} fill="var(--app-surface, #111)" />
          {[0.25, 0.5, 0.75].map(f => (
            <g key={f} stroke="var(--app-chart-grid, #222)" strokeWidth={1}>
              <line x1={W * f} y1={0} x2={W * f} y2={H} />
              <line x1={0} y1={H * f} x2={W} y2={H * f} />
            </g>
          ))}
          {dados.cities.map(c => {
            const activa = ativa === c.city;
            return (
              <g key={c.city} onClick={() => setAtiva(activa ? null : c.city)} style={{ cursor: 'pointer' }}>
                <circle
                  cx={x(c.lon)} cy={y(c.lat)} r={raio(c.total)}
                  fill={activa ? '#3B82F6' : '#3B82F655'}
                  stroke={activa ? '#93C5FD' : '#3B82F6'} strokeWidth={activa ? 2 : 1}
                />
                {(comNome.has(c.city) || activa) && (
                  <text x={x(c.lon)} y={y(c.lat) - raio(c.total) - 4} textAnchor="middle"
                    className="fill-gray-400" style={{ fontSize: 11 }}>
                    {c.city}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>

      {/* Todas as cidades, não só as oito primeiras: numa aba só para isto há
          espaço, e a lista rola dentro do cartão. */}
      <div className="space-y-1 max-h-[340px] overflow-y-auto lg:w-[280px] lg:shrink-0 lg:max-h-none lg:min-h-0 lg:pr-1">
        {dados.cities.map(c => (
          <button key={c.city} onClick={() => setAtiva(ativa === c.city ? null : c.city)}
            className={`w-full flex items-center gap-2 text-left px-2 py-1 rounded-lg ${ativa === c.city ? 'bg-white/5' : 'hover:bg-white/5'}`}>
            <span className="text-xs w-5 shrink-0">{bandeira(c.flag)}</span>
            <span className="text-xs flex-1 truncate">{c.city}</span>
            <span className="text-[11px] text-gray-500 shrink-0">{c.count}x</span>
            <span className="text-xs font-medium shrink-0 w-20 text-right">€{c.total.toFixed(0)}</span>
          </button>
        ))}
      </div>
      </div>

      {sel && (
        <div className="mt-3 bg-[#1a1a1a] rounded-xl p-3 flex items-start justify-between gap-3 shrink-0">
          <div className="min-w-0">
            <p className="text-sm font-medium">{bandeira(sel.flag)} {sel.city}, {sel.country_name}</p>
            <p className="text-[11px] text-gray-500 mt-0.5">
              €{sel.total.toFixed(2)} em {sel.count} transacç{sel.count === 1 ? 'ão' : 'ões'} · média €{sel.avg.toFixed(2)}
              {sel.per_day !== null && sel.days > 1 && <> · €{sel.per_day.toFixed(2)}/dia em {sel.days} dias</>}
            </p>
          </div>
          {sel.trip && (
            <button onClick={() => navigate(`/trips/${sel.trip!.id}`)}
              className="text-[11px] px-2.5 py-1 rounded-lg bg-blue-500/15 text-blue-300 hover:bg-blue-500/25 shrink-0">
              ver viagem
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// A que horas sai o dinheiro. Só aparece quando há despesas com hora guardada
// (vêm dos extractos importados e dos recibos lidos).
function GastosPorHora() {
  const [dados, setDados] = useState<Awaited<ReturnType<typeof expensesApi.byHour>> | null>(null);

  useEffect(() => { expensesApi.byHour(365).then(setDados).catch(() => setDados(null)); }, []);
  if (!dados || dados.with_time < 5) return null;

  const max = Math.max(...dados.hours.map(h => h.total), 1);
  const faixa = (h: number) => (h < 6 ? 'madrugada' : h < 12 ? 'manhã' : h < 19 ? 'tarde' : 'noite');
  const porFaixa = ['madrugada', 'manhã', 'tarde', 'noite'].map(f => ({
    nome: f,
    total: dados.hours.filter(h => faixa(h.hour) === f).reduce((a, h) => a + h.total, 0),
  })).filter(f => f.total > 0).sort((a, b) => b.total - a.total);

  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 sm:p-5 mb-6">
      <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2 mb-1">
        <Clock size={15} className="text-amber-400" /> A que horas gastas
      </h3>
      <p className="text-[11px] text-gray-500 mb-3">
        {dados.with_time} despesas com hora no último ano
        {dados.peak && <> · pico às {String(dados.peak.hour).padStart(2, '0')}h (€{dados.peak.total.toFixed(0)})</>}
        {porFaixa[0] && <> · mais gasto de {porFaixa[0].nome}</>}
      </p>
      <div className="flex items-end gap-[3px] h-24">
        {dados.hours.map(h => (
          <div key={h.hour} className="flex-1 flex flex-col items-center justify-end h-full group relative">
            <div
              className="w-full rounded-t transition-all"
              style={{ height: `${Math.max(2, (h.total / max) * 100)}%`, backgroundColor: h.total > 0 ? '#F59E0B' : '#2a2a2a' }}
            />
            {h.count > 0 && (
              <div className="absolute bottom-full mb-1 hidden group-hover:block whitespace-nowrap bg-[#222] border border-[#333] rounded px-1.5 py-0.5 text-[10px] z-10">
                {String(h.hour).padStart(2, '0')}h · €{h.total.toFixed(2)} · {h.count}x
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="flex justify-between text-[9px] text-gray-600 mt-1">
        <span>00h</span><span>06h</span><span>12h</span><span>18h</span><span>23h</span>
      </div>
      {dados.without_time > 0 && (
        <p className="text-[10px] text-gray-600 mt-2">
          {dados.without_time} despesas sem hora — o Revolut só dá o dia, sem hora nenhuma.
          Estas vêm dos recibos fotografados e dos extractos que a trazem.
        </p>
      )}
    </div>
  );
}

// Nem tudo o que passa na conta é gasto. Só o que não é gasto ganha etiqueta —
// as linhas normais ficam limpas.
const ETIQUETA_TIPO: Record<ExpenseKind, { rot: string; cls: string; dica: string }> = {
  spend: { rot: 'gasto', cls: '', dica: '' },
  income: { rot: 'entrada', cls: 'bg-green-500/10 text-green-400', dica: 'Dinheiro que entrou: reembolso, venda ou de um amigo.' },
  transfer: { rot: 'transferência', cls: 'bg-blue-500/10 text-blue-400', dica: 'Dinheiro teu a mudar de conta — não conta como gasto.' },
  reversal: { rot: 'reembolsado', cls: 'bg-amber-500/10 text-amber-400', dica: 'Compra reembolsada: o dinheiro saiu e voltou. Não conta como gasto nem como entrada.' },
};

// "Revolut: €63.51 (às 10:29 de 27 set)" — de quando é cada saldo, e as contas
// que o compõem quando é mais do que uma.
function saldoDetalhe(s: BankBalances): string {
  return s.banks.map(b => {
    const quando = b.as_of ? format(new Date(b.as_of), "HH:mm 'de' d MMM", { locale: pt }) : 'nunca';
    const contas = b.accounts.length > 1
      ? '\n' + b.accounts.map(a => `  ${a.iban ? '…' + a.iban : 'outra conta'}: ${a.currency === 'EUR' ? '€' + a.balance.toFixed(2) : `${a.balance.toFixed(2)} ${a.currency} (€${a.balance_eur.toFixed(2)})`}`).join('\n')
      : '';
    const falta = b.missing_fx.length ? `\n  sem câmbio, fora da soma: ${b.missing_fx.join(', ')}` : '';
    const cartao = b.cards.map(c => `\n  cartão (fora da soma): €${c.balance.toFixed(2)}`).join('');
    const caducou = b.status === 'expirado' ? ' — ligação caducada, saldo antigo' : '';
    return `${b.institution}: €${b.balance.toFixed(2)} (às ${quando}${caducou})${contas}${cartao}${falta}`;
  }).join('\n') + '\nSaldo disponível na última sincronização com o banco.';
}

export default function ExpensesPage() {
  const categorias = useCategorias();
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [summary, setSummary] = useState<ExpenseSummary[]>([]);
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [params, setParams] = useSearchParams();
  const [showModal, setShowModal] = useState(false);
  const [aLerRecibo, setALerRecibo] = useState(false);
  const [erroRecibo, setErroRecibo] = useState<string | null>(null);
  const [recibo, setRecibo] = useState<{ path: string; merchant: string; confidence?: string; source?: string } | null>(null);
  const [editingExpense, setEditingExpense] = useState<Expense | null>(null);
  // Mudar a categoria de um movimento do banco só vale para os outros iguais
  // quando ele marca a caixa. Volta a desligada em cada gasto que se abre.
  const [aplicarAosIguais, setAplicarAosIguais] = useState(false);
  useEffect(() => { setAplicarAosIguais(false); }, [editingExpense]);
  const [novaCat, setNovaCat] = useState<{ label: string; emoji: string } | null>(null);
  const [erroCat, setErroCat] = useState<string | null>(null);
  useEffect(() => { setNovaCat(null); setErroCat(null); }, [editingExpense, showModal]);

  async function criarCategoria() {
    if (!novaCat?.label.trim()) return;
    try {
      const c = await criaCategoria(novaCat.label.trim(), novaCat.emoji.trim() || '🏷️');
      setForm(f => ({ ...f, category: c.value }));
      setNovaCat(null);
    } catch (e: any) {
      setErroCat(e?.message || 'Não consegui criar a categoria');
    }
  }

  async function apagarCategoria(value: string) {
    try {
      await apagaCategoria(value);
      setErroCat(null);
      setForm(f => (f.category === value ? { ...f, category: 'other' } : f));
    } catch (e: any) {
      setErroCat(e?.message || 'Não consegui apagar a categoria');
    }
  }
  const [csvImporting, setCsvImporting] = useState(false);
  const [pdfImporting, setPdfImporting] = useState(false);
  const [recategorizing, setRecategorizing] = useState(false);
  const [importResult, setImportResult] = useState<{ imported: number; skipped: number; errors: string[]; total_parsed?: number } | null>(null);
  const [income, setIncome] = useState(1040.98);
  const [editingIncome, setEditingIncome] = useState(false);
  const [incomeInput, setIncomeInput] = useState('');

  // Budget & Subscriptions
  const [subscriptions, setSubscriptions] = useState<any[]>([]);
  const [subsSummary, setSubsSummary] = useState<any>(null);
  const [showSubModal, setShowSubModal] = useState(false);
  const [editingSub, setEditingSub] = useState<any>(null);
  const [subForm, setSubForm] = useState({ name: '', amount: 0, currency: 'EUR', billing_cycle: 'monthly', next_renewal: '', category: 'subscriptions', notes: '' });

  // Plano do salário (grupos por %)
  const [salaryPlan, setSalaryPlan] = useState<any>(null);
  const [showBucketModal, setShowBucketModal] = useState(false);
  const [editingBucket, setEditingBucket] = useState<any>(null);
  const [bucketForm, setBucketForm] = useState<{ name: string; percentage: number; kind: string; color: string; categories: string[] }>({ name: '', percentage: 0, kind: 'spend', color: '#3B82F6', categories: [] });
  const [newBucketCat, setNewBucketCat] = useState('');

  // Weekday spending correlation

  // Filtrar transações por categoria (clicar na legenda / gráfico)
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);
  // Filtrar por tipo: tudo / só gastos / só dinheiro recebido
  const [typeFilter, setTypeFilter] = useState<'all' | ExpenseKind>('all');
  // Gasto bruto do mês anterior (para comparação no Resumo)
  const [prevSpent, setPrevSpent] = useState(0);
  const [prevByCat, setPrevByCat] = useState<Record<string, number>>({});
  // Prestações da Klarna que ainda faltam, por mês
  const [klarna, setKlarna] = useState<KlarnaPorPagar | null>(null);
  const [saldos, setSaldos] = useState<BankBalances | null>(null);
  // O plano do gasto aberto, tal como a conta o mostra — antes de gravar
  const [klarnaPlano, setKlarnaPlano] = useState<KlarnaPlano | null>(null);
  // A parte dos amigos nas contas que ele pagou (o gás da casa): o que parece
  // reembolso e ainda não está ligado, e as contas divididas a que falta dinheiro.
  const [reemb, setReemb] = useState<Reembolsos | null>(null);
  const [aDescontar, setADescontar] = useState<number | null>(null);
  const carregaReembolsos = () => expensesApi.reimbursements().then(setReemb).catch(() => setReemb(null));
  const [contasParaDescontar, setContasParaDescontar] = useState<ContaParaDescontar[] | null>(null);
  const [contasEscolhidas, setContasEscolhidas] = useState<number[]>([]);
  const [erroReemb, setErroReemb] = useState<string | null>(null);
  // Pesquisa e ordenação na lista de transações
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState<'date' | 'amount'>('date');

  // Aba activa dentro da página de Gastos
  const [tab, setTab] = useState<'resumo' | 'ano' | 'viagens' | 'transacoes' | 'orcamento' | 'wishlist'>('resumo');
  const [planos, setPlanos] = useState<Record<number, WishPlan>>({});
  const [aVigiar, setAVigiar] = useState<number | null>(null);

  // Desde o salário: o mês dele começa no dia em que o dinheiro entra (24, 26,
  // 27…), não no dia 1. Só nas Transações — as outras abas são do mês civil.
  const [periodo, setPeriodo] = useState<'mes' | 'salario'>(() => {
    try { return localStorage.getItem('gastos_periodo') === 'salario' ? 'salario' : 'mes'; } catch { return 'mes'; }
  });
  useEffect(() => { try { localStorage.setItem('gastos_periodo', periodo); } catch { /* ignora */ } }, [periodo]);
  const [salarios, setSalarios] = useState<DiaDeSalario[]>([]);
  const [diaTipico, setDiaTipico] = useState(25);
  const [cicloIdx, setCicloIdx] = useState<number | null>(null);   // null = o que está a decorrer
  const carregaSalarios = () => expensesApi.paydays()
    .then(r => { setSalarios(r.paydays); setDiaTipico(r.typical_day); })
    .catch(() => setSalarios([]));
  useEffect(() => { carregaSalarios(); }, []);

  // Um dia corrigido para o futuro ainda não abre ciclo nenhum.
  const salariosPassados = salarios.filter(s => s.date <= format(new Date(), 'yyyy-MM-dd'));
  // Escolhido nas Transações, manda na página toda (cartões, cabeçalho, Resumo,
  // e o plano do salário no Orçamento).
  const modoSalario = periodo === 'salario' && salariosPassados.length > 0;
  const iCiclo = cicloIdx == null ? salariosPassados.length - 1 : Math.min(cicloIdx, salariosPassados.length - 1);
  const ciclo = (() => {
    if (!modoSalario) return null;
    const s = salariosPassados[iCiclo];
    const seguinte = salariosPassados[iCiclo + 1];
    const inicio = new Date(`${s.date}T00:00:00`);
    const mesSeguinte = addMonths(startOfMonth(inicio), 1);
    const proximo = seguinte
      ? new Date(`${seguinte.date}T00:00:00`)
      : new Date(mesSeguinte.getFullYear(), mesSeguinte.getMonth(), Math.min(diaTipico, getDaysInMonth(mesSeguinte)));
    const fim = seguinte ? addDays(proximo, -1) : null;   // sem fim: ainda a decorrer
    const ate = fim ?? new Date();
    return { ...s, inicio, fim, proximo, dias: differenceInCalendarDays(ate, inicio) + 1 };
  })();
  const chaveCiclo = ciclo ? `${ciclo.date}|${ciclo.fim ? format(ciclo.fim, 'yyyy-MM-dd') : ''}` : '';
  const ultimoPedido = useRef(0);

  // O dia escreve-se num campo e só se grava no ✓: gravar a cada mudança do
  // campo de data apanhava o dia a meio de ser escrito (o "2" de "26").
  const [diaNovo, setDiaNovo] = useState<string | null>(null);

  async function corrigeSalario(dia: string, valor?: number) {
    if (!dia) return;
    await expensesApi.setPayday(dia, valor);
    setDiaNovo(null);
    setCicloIdx(null);
    await carregaSalarios();
  }

  // O movimento do salário não é a parte de ninguém numa conta: no editar dele
  // não se oferece o "descontar em…".
  const eSalarioDe = (e: Expense) =>
    salarios.some(sl => sl.date === e.date && sl.amount != null && Math.abs(sl.amount + e.amount) < 0.01);


  async function repoeSalario(month: string) {
    await expensesApi.resetPayday(month);
    await carregaSalarios();
  }

  // Vista anual (comparar meses)
  const [yearData, setYearData] = useState<any>(null);
  const [yearNum, setYearNum] = useState(new Date().getFullYear());
  const [yearCat, setYearCat] = useState<string>('');

  // Wishlist / Desejos
  const [wishItems, setWishItems] = useState<any[]>([]);
  const [wishSummary, setWishSummary] = useState<any>(null);
  const [showWishModal, setShowWishModal] = useState(false);
  const [editingWish, setEditingWish] = useState<any>(null);
  const [wishForm, setWishForm] = useState({ name: '', price: 0, priority: 'medium', category: 'shopping', url: '', notes: '', saved_amount: 0 });

  const [form, setForm] = useState<ExpenseCreate>({
    description: '',
    amount: 0,
    category: 'other',
    date: format(new Date(), 'yyyy-MM-dd'),
    notes: '',
  });

  // ?new=1 (paleta ⌘K) abre já o formulário de novo gasto.
  useEffect(() => {
    if (params.get('new') !== '1') return;
    setParams({}, { replace: true });
    openNew();
  }, [params]);

  useEffect(() => { loadData(); setSearchQuery(''); }, [currentMonth, chaveCiclo]);
  useEffect(() => { expensesApi.yearly(yearNum).then(setYearData).catch(() => null); }, [yearNum]);

  async function loadData() {
    const pedido = ++ultimoPedido.current;
    const start = format(ciclo ? ciclo.inicio : startOfMonth(currentMonth), 'yyyy-MM-dd');
    const end = format(ciclo ? (ciclo.fim ?? new Date()) : endOfMonth(currentMonth), 'yyyy-MM-dd');
    const month = currentMonth.getMonth() + 1;
    const year = currentMonth.getFullYear();

    const [expData, sumData, incData, subsData, subsSumData, planData] = await Promise.all([
      expensesApi.list({ start_date: start, end_date: end }),
      expensesApi.summary({ month, year }),
      expensesApi.getIncome(month, year),
      budgetsApi.subscriptions().catch(() => []),
      budgetsApi.subscriptionsSummary().catch(() => null),
      // Desde o salário, o plano é do período e mede-se contra esse salário.
      (ciclo ? budgetsApi.salaryPlan({ start, end, salary: ciclo.amount ?? undefined })
             : budgetsApi.salaryPlan({ month, year })).catch(() => null),
    ]);
    // Mudar de ciclo depressa: a resposta de um pedido antigo não pisa a do novo.
    if (pedido !== ultimoPedido.current) return;
    setExpenses(expData);
    setSummary(sumData);
    setIncome(incData.amount);
    setSubscriptions(subsData);
    setSubsSummary(subsSumData);
    setSalaryPlan(planData);

    loadWishlist();
    expensesApi.klarna().then(setKlarna).catch(() => setKlarna(null));
    bankingApi.balances().then(setSaldos).catch(() => setSaldos(null));
    carregaReembolsos();

    // Mês anterior — ou o salário anterior — para a comparação no Resumo
    if (ciclo && iCiclo === 0) { setPrevSpent(0); setPrevByCat({}); return; }
    const prevStart = ciclo ? salariosPassados[iCiclo - 1].date : format(startOfMonth(subMonths(currentMonth, 1)), 'yyyy-MM-dd');
    const prevEnd = format(ciclo ? addDays(ciclo.inicio, -1) : endOfMonth(subMonths(currentMonth, 1)), 'yyyy-MM-dd');
    expensesApi.list({ start_date: prevStart, end_date: prevEnd }).then((prev: any[]) => {
      const byCat: Record<string, number> = {};
      let bruto = 0;
      prev.forEach(e => {
        // os reembolsos dos amigos são gasto negativo: descontam na conta
        if ((e.kind || 'spend') === 'spend' && !e.extraordinary) {
          bruto += e.amount;
          byCat[e.category] = (byCat[e.category] || 0) + e.amount;
        }
      });
      setPrevSpent(bruto);
      setPrevByCat(byCat);
    }).catch(() => { setPrevSpent(0); setPrevByCat({}); });
  }

  async function loadWishlist() {
    const [items, sum] = await Promise.all([
      wishlistApi.list().catch(() => []),
      wishlistApi.summary().catch(() => null),
    ]);
    setWishItems(items);
    carregarPlanos(items);
    setWishSummary(sum);
  }

  function openWishNew() {
    setEditingWish(null);
    setWishForm({ name: '', price: 0, priority: 'medium', category: 'shopping', url: '', notes: '', saved_amount: 0 });
    setShowWishModal(true);
  }

  function openWishEdit(item: any) {
    setEditingWish(item);
    setWishForm({ name: item.name, price: item.price, priority: item.priority, category: item.category, url: item.url || '', notes: item.notes || '', saved_amount: item.saved_amount });
    setShowWishModal(true);
  }

  async function saveWish() {
    if (!wishForm.name.trim() || wishForm.price <= 0) return;
    if (editingWish) await wishlistApi.update(editingWish.id, wishForm);
    else await wishlistApi.create(wishForm);
    setShowWishModal(false);
    loadWishlist();
  }

  async function deleteWish(id: number) {
    await wishlistApi.delete(id);
    setShowWishModal(false);
    loadWishlist();
  }

  // Quando é que isto está pago, e onde é que já apareceu à venda.
  async function carregarPlanos(itens: any[]) {
    const abertos = itens.filter(w => !w.purchased).slice(0, 8);
    const pares = await Promise.all(
      abertos.map(w => wishlistApi.plan(w.id).then(p => [w.id, p] as const).catch(() => null))
    );
    setPlanos(Object.fromEntries(pares.filter(Boolean) as any));
  }

  async function vigiarNosDeals(item: any) {
    setAVigiar(item.id);
    try {
      await wishlistApi.createWatch(item.id);
      await loadData();
    } finally {
      setAVigiar(null);
    }
  }

  async function addSavingToWish(item: any) {
    const input = window.prompt(`Quanto juntaste para "${item.name}"? (€)`, '');
    if (input == null) return;
    const amount = parseFloat(input.replace(',', '.'));
    if (isNaN(amount) || amount === 0) return;
    await wishlistApi.addSaving(item.id, amount);
    loadWishlist();
  }

  // "Comprei" não cria gasto nenhum: a compra já está na conta (o banco trouxe-a),
  // e o que falta é dizer qual das transacções é. Criar outra contava-a duas vezes.
  const [aLigar, setALigar] = useState<any | null>(null);
  const [candidatos, setCandidatos] = useState<WishCandidate[] | null>(null);
  const [procuraCand, setProcuraCand] = useState('');
  useEffect(() => {
    if (!aLigar) return;
    let vivo = true;
    setCandidatos(null);
    const t = setTimeout(() => {
      wishlistApi.candidates(aLigar.id, procuraCand)
        .then(r => { if (vivo) setCandidatos(r); }).catch(() => { if (vivo) setCandidatos([]); });
    }, procuraCand ? 250 : 0);
    return () => { vivo = false; clearTimeout(t); };
  }, [aLigar, procuraCand]);

  function purchaseWish(item: any) {
    setProcuraCand('');
    setALigar(item);
  }

  async function ligaCompra(expenseId: number) {
    if (!aLigar) return;
    // Um item ligado a um gasto que a wishlist inventou: desfaz-se (o gasto
    // inventado vai embora) e liga-se à transacção verdadeira.
    if (aLigar.purchased) await wishlistApi.unpurchase(aLigar.id);
    await wishlistApi.purchase(aLigar.id, expenseId);
    setALigar(null);
    setShowWishModal(false);
    loadData();
  }

  async function unpurchaseWish(item: any) {
    await wishlistApi.unpurchase(item.id);
    loadData();
  }

  // As sugestões vivem no editar de cada transação; na lista só há um ícone.
  type Sugestao = Reembolsos['suggestions'][number];
  const sugPorConta: Record<number, Sugestao> = {};
  const sugPorEntrada: Record<number, Sugestao> = {};
  reemb?.suggestions.forEach(sg => {
    sg.expenses.forEach(c => { sugPorConta[c.id] = sg; });
    sg.incomes.forEach(i => { sugPorEntrada[i.id] = sg; });
  });
  const dicaReembolso = (id: number) => {
    const sg = sugPorConta[id];
    if (sg) return `Parece que já te devolveram a parte deles (${sg.incomes.map(i => `${i.description} €${i.amount.toFixed(2)}`).join(' + ')}) — abre para descontar`;
    const se = sugPorEntrada[id];
    if (se) return `Parece a parte de alguém em ${se.expenses.map(c => `${c.description} (€${c.amount.toFixed(2)})`).join(' + ')} — abre para descontar`;
    return null;
  };

  async function descontarSugestao(sug: Reembolsos['suggestions'][number]) {
    setADescontar(sug.expenses[0].id);
    try {
      for (const i of sug.incomes) await expensesApi.linkReimbursement(i.id, sug.expenses.map(c => c.id));
    } finally {
      setADescontar(null);
    }
    setShowModal(false);
    loadData();
  }

  async function naoEReembolso(sug: Reembolsos['suggestions'][number]) {
    await Promise.all(sug.incomes.flatMap(i => sug.expenses.map(c => expensesApi.dismissReimbursement(i.id, c.id))));
    carregaReembolsos();
  }

  // No editar de uma entrada: em que conta é que ela desconta.
  useEffect(() => {
    setContasParaDescontar(null);
    setContasEscolhidas([]);
    setErroReemb(null);
    if (!showModal || !editingExpense || editingExpense.amount >= 0 || editingExpense.reimburses_id) return;
    let vivo = true;
    expensesApi.reimburseCandidates(editingExpense.id).then(l => {
      if (!vivo) return;
      setContasParaDescontar(l);
      // vem escolhida a conta que a app sugere; o resto fica na lista
      const sugeridas = (sugPorEntrada[editingExpense.id]?.expenses || []).map(c => c.id).filter(id => l.some(c => c.id === id));
      if (sugeridas.length) setContasEscolhidas(sugeridas);
    }).catch(() => {});
    return () => { vivo = false; };
  }, [showModal, editingExpense]);

  async function ligarReembolso() {
    if (!editingExpense || contasEscolhidas.length === 0) return;
    try {
      await expensesApi.linkReimbursement(editingExpense.id, contasEscolhidas);
      setShowModal(false);
      loadData();
    } catch (e: any) {
      setErroReemb(e?.message || 'Não consegui descontar');
    }
  }

  async function desligarReembolso() {
    if (!editingExpense) return;
    await expensesApi.unlinkReimbursement(editingExpense.id);
    setShowModal(false);
    loadData();
  }

  // "a tua parte" de uma conta: dividida, é o valor a dividir por N; sem divisão
  // marcada, é o que sobra depois do que os amigos já devolveram.
  type Partilha = { amount: number; split_people?: number | null; my_share?: number | null; reimbursed_total?: number };
  const parteDele = (e: Partilha) =>
    e.my_share != null ? e.my_share : e.split_people ? e.amount / e.split_people : e.amount - (e.reimbursed_total || 0);
  const faltaReceber = (e: Partilha) =>
    e.my_share != null || e.split_people ? Math.max(0, e.amount - parteDele(e) - (e.reimbursed_total || 0)) : 0;

  function openNew() {
    setEditingExpense(null);
    setForm({ description: '', amount: 0, category: 'other', date: format(new Date(), 'yyyy-MM-dd'), notes: '', time_of_day: null, extraordinary: false, klarna_installments: null, split_people: null, my_share: null });
    setRecibo(null);
    setErroRecibo(null);
    setShowModal(true);
  }

  // Foto do recibo → OCR + IA → formulário preenchido. O ficheiro fica anexado à
  // despesa quando for gravada.
  async function lerRecibo(file: File) {
    setALerRecibo(true);
    setErroRecibo(null);
    try {
      const r = await expensesApi.scanReceipt(file);
      setForm(f => ({
        ...f,
        description: r.suggestion.description || f.description,
        amount: r.suggestion.amount ?? f.amount,
        category: r.suggestion.category || f.category,
        date: r.suggestion.date || f.date,
        notes: r.suggestion.notes || f.notes,
        time_of_day: r.suggestion.time_of_day || f.time_of_day || null,
      }));
      setRecibo({ path: r.receipt_path, merchant: r.merchant, confidence: r.confidence, source: r.source });
    } catch (e: any) {
      setErroRecibo(e?.message || 'Não consegui ler o recibo');
    } finally {
      setALerRecibo(false);
    }
  }

  function openEdit(exp: Expense) {
    setEditingExpense(exp);
    setRecibo(null);
    setErroRecibo(null);
    setForm({ description: exp.description, amount: exp.amount, category: exp.category, date: exp.date, notes: exp.notes, time_of_day: exp.time_of_day || null, extraordinary: !!exp.extraordinary, klarna_installments: exp.klarna_installments ?? null, split_people: exp.split_people ?? null, my_share: exp.my_share ?? null });
    setShowModal(true);
  }

  async function handleSave() {
    if (!form.description.trim() || form.amount === 0) return;
    if (editingExpense) {
      await expensesApi.update(editingExpense.id, { ...form, apply_to_similar: aplicarAosIguais });
      if (recibo) await expensesApi.attachReceipt(editingExpense.id, recibo.path).catch(() => {});
    } else {
      const criada = await expensesApi.create(form);
      if (recibo) await expensesApi.attachReceipt(criada.id, recibo.path).catch(() => {});
    }
    setShowModal(false);
    loadData();
  }

  async function handleDelete() {
    if (editingExpense) {
      await expensesApi.delete(editingExpense.id);
      setShowModal(false);
      loadData();
    }
  }

  async function handleUploadReceipt(expId: number, file: File) {
    await expensesApi.uploadReceipt(expId, file);
    loadData();
  }

  async function handleCSVImport(file: File) {
    setCsvImporting(true);
    try {
      const result = await expensesApi.importCSV(file);
      setImportResult(result);
      loadData();
    } catch {
      setImportResult({ imported: 0, skipped: 0, errors: ['Erro ao importar ficheiro'] });
    }
    setCsvImporting(false);
  }

  async function handlePDFImport(file: File) {
    setPdfImporting(true);
    try {
      const result = await expensesApi.importPDF(file);
      setImportResult(result);
      loadData();
    } catch {
      setImportResult({ imported: 0, skipped: 0, errors: ['Erro ao importar PDF'] });
    }
    setPdfImporting(false);
  }

  async function handleRecategorize() {
    setRecategorizing(true);
    try {
      const month = currentMonth.getMonth() + 1;
      const year = currentMonth.getFullYear();
      const result = await expensesApi.recategorize(month, year);
      setImportResult({ imported: result.updated, skipped: result.total - result.updated, errors: [], total_parsed: result.total });
      loadData();
    } catch {
      setImportResult({ imported: 0, skipped: 0, errors: ['Erro ao recategorizar'] });
    }
    setRecategorizing(false);
  }

  async function handleRecategorizeYear() {
    const year = currentMonth.getFullYear();
    if (!window.confirm(`Recategorizar com IA todas as transações de ${year}? Pode demorar um pouco.`)) return;
    setRecategorizing(true);
    try {
      const result = await expensesApi.recategorizeYear(year);
      setImportResult({ imported: result.updated, skipped: result.total - result.updated, errors: [], total_parsed: result.total });
      loadData();
    } catch {
      setImportResult({ imported: 0, skipped: 0, errors: ['Erro ao recategorizar'] });
    }
    setRecategorizing(false);
  }

  // O tipo de cada movimento manda: uma transferência para a corretora ou para o
  // Revolut aparece na lista mas não é gasto, e as duas pernas de uma compra
  // revertida anulam-se. Somar tudo o que era positivo dizia 851,68€ em Agosto
  // quando saíram 651,68€ — os outros 200€ mudaram de conta.
  const eGasto = (e: any) => (e.kind || 'spend') === 'spend';
  const eEntrada = (e: any) => e.kind === 'income';
  // A parte dos amigos numa conta (o MB Way pelo gás) é gasto negativo: entra
  // aqui a descontar, e é por isso que já não se filtra pelo sinal.
  const spentMonth = expenses.reduce((s, e) => s + (eGasto(e) ? e.amount : 0), 0);
  // A compra grande e pontual (a mota) fica no total do mês, mas fora de tudo o
  // que serve para comparar: a média por dia e o mês passado são sobre o resto.
  const extraMonth = expenses.reduce((s, e) => s + (eGasto(e) && e.extraordinary ? e.amount : 0), 0);
  const correnteMonth = spentMonth - extraMonth;
  const receivedMonth = expenses.reduce((s, e) => s + (eEntrada(e) ? -e.amount : 0), 0);
  // O que sobra é o que entrou mesmo menos o que saiu mesmo. O "Rendimento" é um
  // número escrito à mão e fica desactualizado (em Agosto herdava os 1.090,98€
  // de Julho quando tinham entrado 1.705,09€); as entradas são medidas na conta.
  // Somar os dois contava a bolsa duas vezes — dava 2.144,39€ de Restante.
  // Sem entradas medidas (meses antigos, importados de PDF) vale o declarado.
  const baseMes = receivedMonth > 0 ? receivedMonth : income;
  // Desde o salário, o salário tem cartão próprio: o Recebido é o resto que
  // entrou (somá-lo outra vez dava 1.206,23€ com 1.090,98€ de bolsa lá dentro),
  // e o Restante é salário + resto − gasto.
  const linhaDoSalario = ciclo?.amount != null
    ? expenses.filter(e => eEntrada(e) && Math.abs(-e.amount - ciclo.amount!) < 0.01)
        .sort((a, b) => Math.abs(differenceInCalendarDays(new Date(`${a.date}T00:00:00`), ciclo.inicio))
                      - Math.abs(differenceInCalendarDays(new Date(`${b.date}T00:00:00`), ciclo.inicio)))[0]
    : undefined;
  const recebido = ciclo ? receivedMonth - (linhaDoSalario ? -linhaDoSalario.amount : 0) : receivedMonth;
  // Uma devolução cujo par ficou noutro período é dinheiro que entrou (ou saiu)
  // neste: a GoPro foi comprada a 7 de Setembro e os 59,99€ voltaram a 24, no
  // dia do salário. Fora do Gasto e do Recebido (é um estorno), mas o Restante é
  // o que há na conta, e sem isto ficava 59,99€ abaixo do banco.
  const estornosSoltos = -expenses.reduce((t, e) => t + (e.kind === 'reversal' ? e.amount : 0), 0);
  const remaining = (ciclo ? (ciclo.amount ?? income) + recebido - spentMonth : baseMes - spentMonth) + estornosSoltos;
  const COLORS = ['#3B82F6', '#8B5CF6', '#EF4444', '#F59E0B', '#10B981', '#EC4899', '#6366F1', '#14B8A6', '#6B7280'];
  const MESES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];

  // Gráfico "Por Categoria": só categorias com gasto líquido positivo (negativas partiriam o pie),
  // ordenadas por total para as cores baterem com a legenda.
  // Desde o salário, as categorias somam-se da própria lista: o resumo do
  // servidor é por mês civil.
  const porCategoria = ciclo
    ? Object.values(expenses.reduce((acc, e) => {
        if (!eGasto(e)) return acc;
        const c = acc[e.category] || (acc[e.category] = { category: e.category, total: 0, count: 0 });
        c.total += e.amount;
        if (e.amount > 0) c.count += 1;
        return acc;
      }, {} as Record<string, { category: string; total: number; count: number }>))
    : summary;
  const pieData = porCategoria
    .filter(s => s.total > 0)
    .sort((a, b) => b.total - a.total)
    .map(s => ({
      name: infoCategoria(s.category).label,
      value: s.total,
      category: s.category,
      count: s.count,
    }));

  // Que prestação é cada movimento: a marcada e as que a app encontrou na conta.
  const klarnaDe: Record<number, string> = {};
  klarna?.plans.forEach(p => p.payments.forEach(x => { klarnaDe[x.expense_id] = `${x.n}/${p.of}`; }));

  // Um gasto que já existe pergunta à conta o que já saiu. Um gasto novo ainda
  // não tem nada do outro lado: faltam todas menos a primeira.
  const vezesKlarna = form.klarna_installments ?? null;
  useEffect(() => {
    setKlarnaPlano(null);
    if (!showModal || !editingExpense || !vezesKlarna) return;
    let vivo = true;
    expensesApi.klarnaPlano(editingExpense.id, vezesKlarna).then(p => { if (vivo) setKlarnaPlano(p); }).catch(() => {});
    return () => { vivo = false; };
  }, [showModal, editingExpense, vezesKlarna]);
  const diaMes = (d: Date) => format(d, 'd MMM', { locale: pt });
  const klarnaDetalhe = (m: KlarnaPorPagar['months'][number]) =>
    m.items.map(i => `${i.description} · ${i.n}/${i.of} · €${i.amount.toFixed(2)} · dia ${+i.due.slice(8)}`).join('\n');
  // O que vence no mês que se está a ver: é dinheiro do Restante que já tem dono.
  const klarnaDoMes = (() => {
    if (!ciclo) return klarna?.months.find(m => m.month === format(currentMonth, 'yyyy-MM'));
    const de = ciclo.date, ate = format(addDays(ciclo.proximo, -1), 'yyyy-MM-dd');
    const items = (klarna?.months ?? []).flatMap(m => m.items).filter(i => i.due >= de && i.due <= ate);
    return items.length ? { month: '', total: items.reduce((t, i) => t + i.amount, 0), items } : undefined;
  })();
  const klarnaLinha = () => {
    if (!vezesKlarna) return null;
    if (editingExpense && !klarnaPlano) return '…';
    const faltam = klarnaPlano
      ? klarnaPlano.pending.map(f => new Date(`${f.due}T00:00:00`))
      : Array.from({ length: vezesKlarna - 1 }, (_, k) => addMonths(new Date(`${form.date}T00:00:00`), k + 1));
    const pagas = `pagas ${vezesKlarna - faltam.length} de ${vezesKlarna}`;
    if (faltam.length === 0) return pagas;
    return `${pagas} · faltam ${faltam.length <= 3
      ? faltam.map(diaMes).join(', ')
      : `${faltam.length}, até ${format(faltam[faltam.length - 1], 'd MMM yyyy', { locale: pt })}`}`;
  };

  const getCategoryInfo = infoCategoria;

  // Clicar numa categoria (no Resumo) salta para a aba Transações já filtrada
  const pickCategory = (cat: string) => { setCategoryFilter(cat); setTab('transacoes'); };
  // Clicar num número da tabela anual → Transações desse mês, com a categoria filtrada
  const goToMonthCategory = (monthNum: number, cat: string | null) => {
    setCurrentMonth(new Date(yearNum, monthNum - 1, 1));
    setCategoryFilter(cat);
    setTypeFilter('all');
    setPeriodo('mes');   // vem de um número de um mês civil, na tabela do Ano
    setTab('transacoes');
  };
  const searchLower = searchQuery.trim().toLowerCase();
  const visibleExpenses = expenses
    .filter(e =>
      (!categoryFilter || e.category === categoryFilter) &&
      (typeFilter === 'all' || (e.kind || 'spend') === typeFilter) &&
      (!searchLower || e.description.toLowerCase().includes(searchLower) || (e.notes || '').toLowerCase().includes(searchLower))
    )
    .sort((a, b) => sortBy === 'amount' ? Math.abs(b.amount) - Math.abs(a.amount) : 0);
  const filteredTotal = visibleExpenses.reduce((sum, e) => sum + e.amount, 0);
  // Categorias presentes no mês (para os chips do filtro)
  const monthCategories = Array.from(new Set(expenses.map(e => e.category)));
  // Inclui sempre a categoria filtrada (mesmo que sem gastos no mês atual) para o seletor não encravar
  const categoryOptions = Array.from(new Set([...monthCategories, ...(categoryFilter ? [categoryFilter] : [])]));
  const hasActiveFilters = !!categoryFilter || typeFilter !== 'all' || searchQuery.trim() !== '';

  function openBucketNew() {
    setEditingBucket(null);
    setBucketForm({ name: '', percentage: 10, kind: 'spend', color: '#3B82F6', categories: [] });
    setNewBucketCat('');
    setShowBucketModal(true);
  }

  function openBucketEdit(g: any) {
    setEditingBucket(g);
    setBucketForm({ name: g.name, percentage: g.percentage, kind: g.kind || 'spend', color: g.color, categories: g.categories || [] });
    setNewBucketCat('');
    setShowBucketModal(true);
  }

  async function saveBucket() {
    if (!bucketForm.name.trim() || bucketForm.percentage < 0) return;
    if (editingBucket) {
      await budgetsApi.updateBucket(editingBucket.id, bucketForm);
    } else {
      await budgetsApi.createBucket({ ...bucketForm, sort_order: (salaryPlan?.groups?.length || 0) });
    }
    setShowBucketModal(false);
    setEditingBucket(null);
    loadData();
  }

  async function deleteSalaryBucket(id: number) {
    await budgetsApi.deleteBucket(id);
    setShowBucketModal(false);
    setEditingBucket(null);
    loadData();
  }

  async function saveSubscription() {
    if (!subForm.name.trim() || subForm.amount <= 0) return;
    if (editingSub) {
      await budgetsApi.updateSubscription(editingSub.id, subForm);
    } else {
      await budgetsApi.createSubscription(subForm);
    }
    setShowSubModal(false);
    setEditingSub(null);
    loadData();
  }

  async function deleteSubscription(id: number) {
    await budgetsApi.deleteSubscription(id);
    setShowSubModal(false);
    setEditingSub(null);
    loadData();
  }

  return (
    // O Resumo e as Viagens é que se prendem à janela: são as abas que cabem
    // inteiras. As outras (transacções, ano, orçamento) têm listas e tabelas que
    // têm mesmo de rolar.
    <div className={tab === 'resumo' || tab === 'viagens'
      ? 'lg:h-[calc(100dvh-4rem)] lg:flex lg:flex-col lg:overflow-hidden' : ''}>
      {/* Header */}
      <div className="relative flex flex-wrap items-center justify-between gap-3 mb-6 lg:mb-8 lg:shrink-0">
        <div>
          <h2 className="text-2xl font-bold">Gastos</h2>
          {/* O que há agora nas contas não é do mês que se está a ver, por isso
              não vai para os cartões: fica com o título, igual em todas as abas. */}
          {saldos && saldos.banks.length > 0 && (
            <p className="text-xs text-gray-500 tabular-nums whitespace-nowrap" title={saldoDetalhe(saldos)}>
              {saldos.banks.map(b => (
                <span key={b.id} className={b.status === 'expirado' ? 'opacity-60' : ''}>
                  {b.name} <span className="text-gray-300">€{b.balance.toFixed(2)}</span>{' · '}
                </span>
              ))}
              total <span className="text-gray-100 font-semibold">€{saldos.total.toFixed(2)}</span>
            </p>
          )}
        </div>
        {/* O mês é tirado do fluxo e preso a meio da linha: repartir o espaço
            entre um título curto e uma fila de botões larga põe-no a meio do que
            sobra, que não é o meio da página. Abaixo de xl fica no fluxo (no
            telemóvel numa linha só para ele): preso a meio, num iPad, ia parar
            por cima dos saldos ou dos botões. */}
        <p className="order-last w-full text-center text-base text-gray-400 first-letter:uppercase
          sm:order-none sm:w-auto sm:flex-1 xl:absolute xl:left-1/2 xl:-translate-x-1/2">
          {ciclo
            ? `${format(ciclo.inicio, 'd MMM', { locale: pt })} → ${ciclo.fim ? format(ciclo.fim, 'd MMM', { locale: pt }) : 'hoje'}`
            : format(currentMonth, "MMMM 'de' yyyy", { locale: pt })}
        </p>
        <div className="flex items-center gap-2 sm:gap-3 flex-wrap sm:ml-auto">
          {ciclo ? (
            <div className="flex items-center gap-1">
              <button onClick={() => setCicloIdx(Math.max(0, iCiclo - 1))} disabled={iCiclo === 0}
                className="p-2 hover:bg-white/10 rounded-lg disabled:opacity-30" title="salário anterior">
                <ChevronLeft size={18} />
              </button>
              <button onClick={() => setCicloIdx(null)} className="px-3 py-1.5 text-xs bg-white/10 rounded-lg hover:bg-white/20">
                Este salário
              </button>
              <button onClick={() => setCicloIdx(iCiclo + 1 >= salariosPassados.length - 1 ? null : iCiclo + 1)}
                disabled={!ciclo.fim} className="p-2 hover:bg-white/10 rounded-lg disabled:opacity-30" title="salário seguinte">
                <ChevronRight size={18} />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-1">
              <button onClick={() => setCurrentMonth(subMonths(currentMonth, 1))} className="p-2 hover:bg-white/10 rounded-lg">
                <ChevronLeft size={18} />
              </button>
              <button onClick={() => setCurrentMonth(new Date())} className="px-3 py-1.5 text-xs bg-white/10 rounded-lg hover:bg-white/20">
                Este mês
              </button>
              <button onClick={() => setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1))}
                className="p-2 hover:bg-white/10 rounded-lg">
                <ChevronRight size={18} />
              </button>
            </div>
          )}
          <button onClick={openNew}
            className="flex items-center gap-2 px-3 sm:px-4 py-2 bg-green-600 hover:bg-green-700 rounded-xl text-sm font-medium">
            <Plus size={16} /> <span className="hidden sm:inline">Novo Gasto</span><span className="sm:hidden">Novo</span>
          </button>
        </div>
      </div>

      {/* Stats — seis colunas só em ecrã largo: no iPad, com a barra lateral, cada
          cartão ficava com ~100px e "€1705.09" saía do cartão. */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3 sm:gap-4 mb-6 lg:mb-8 lg:shrink-0">
        {ciclo ? (
        <div className="bg-[#161616] rounded-2xl p-4 sm:p-5 border border-[#222] min-w-0"
          title={`O salário que abriu este período${ciclo.source === 'banco' ? ', lido da conta' : ciclo.source === 'manual' ? ', dia corrigido à mão' : `; sem movimento do banco, vale o dia ${diaTipico}`}. O lápis muda o dia.`}>
          <div className="flex items-center justify-between mb-1">
            <p className="text-xs text-gray-500">Salário</p>
            <button onClick={() => setDiaNovo(d => d === null ? ciclo.date : null)} className="text-gray-600 hover:text-gray-400"
              title="mudar o dia em que o salário entrou">
              <Pencil size={12} />
            </button>
          </div>
          <p className="text-xl sm:text-2xl xl:text-xl 2xl:text-2xl font-bold tabular-nums whitespace-nowrap text-green-400">
            €{(ciclo.amount ?? income).toFixed(2)}
          </p>
          {diaNovo !== null ? (
            <div className="mt-1 flex flex-wrap items-center justify-end gap-1">
              <input type="date" autoFocus value={diaNovo} max={format(new Date(), 'yyyy-MM-dd')}
                onChange={e => setDiaNovo(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') corrigeSalario(diaNovo); if (e.key === 'Escape') setDiaNovo(null); }}
                className="w-full bg-[#222] border border-[#333] rounded-md px-1 py-0.5 text-[11px] text-gray-200 focus:outline-none focus:border-green-500" />
              <button onClick={() => corrigeSalario(diaNovo)} disabled={!diaNovo || diaNovo === ciclo.date}
                className="p-1 rounded-md bg-green-600 hover:bg-green-700 disabled:opacity-30" title="guardar"><Check size={12} /></button>
              <button onClick={() => setDiaNovo(null)} className="p-1 text-gray-500 hover:text-gray-300" title="cancelar"><X size={12} /></button>
            </div>
          ) : (
            <p className="text-[11px] text-gray-500 mt-1">
              a {format(ciclo.inicio, "d 'de' MMMM", { locale: pt })}
              {ciclo.source === 'manual' && <> · <button onClick={() => repoeSalario(ciclo.month)} className="underline hover:text-gray-300">repor</button></>}
            </p>
          )}
        </div>
        ) : (
        <div className="bg-[#161616] rounded-2xl p-4 sm:p-5 border border-[#222] min-w-0">
          <div className="flex items-center justify-between mb-1">
            <p className="text-xs text-gray-500" title="Salário declarado por ti. É a base do Orçamento (os envelopes são percentagens dele) — o que entrou mesmo na conta está no cartão Recebido.">Rendimento</p>
            <button onClick={() => { setEditingIncome(true); setIncomeInput(String(income)); }}
              className="text-gray-600 hover:text-gray-400">
              <Pencil size={12} />
            </button>
          </div>
          {editingIncome ? (
            <div className="flex items-center gap-1">
              <span className="text-lg font-bold text-green-400">€</span>
              <input type="number" step="0.01" value={incomeInput}
                onChange={e => setIncomeInput(e.target.value)}
                onKeyDown={async e => {
                  if (e.key === 'Enter') {
                    const val = parseFloat(incomeInput);
                    if (!isNaN(val) && val >= 0) {
                      await expensesApi.setIncome(currentMonth.getMonth() + 1, currentMonth.getFullYear(), val);
                      setIncome(val);
                    }
                    setEditingIncome(false);
                  } else if (e.key === 'Escape') {
                    setEditingIncome(false);
                  }
                }}
                onBlur={async () => {
                  const val = parseFloat(incomeInput);
                  if (!isNaN(val) && val >= 0) {
                    await expensesApi.setIncome(currentMonth.getMonth() + 1, currentMonth.getFullYear(), val);
                    setIncome(val);
                  }
                  setEditingIncome(false);
                }}
                autoFocus
                className="w-full bg-transparent text-xl sm:text-2xl xl:text-xl 2xl:text-2xl font-bold tabular-nums whitespace-nowrap text-green-400 outline-none border-b border-green-400/30"
              />
            </div>
          ) : (
            <p className="text-xl sm:text-2xl xl:text-xl 2xl:text-2xl font-bold tabular-nums whitespace-nowrap text-green-400">€{income.toFixed(2)}</p>
          )}
        </div>
        )}
        <div className="bg-[#161616] rounded-2xl p-4 sm:p-5 border border-[#222] min-w-0">
          <p className="text-xs text-gray-500 mb-1">Gasto</p>
          {/* Um número só, e é o que conta: o que voltou atrás já não está aqui
              dentro (as duas pernas anulam-se), e a bolsa da faculdade não é um
              reembolso — subtrair as entradas dava "−853,41€ gastos". */}
          <p className="text-xl sm:text-2xl xl:text-xl 2xl:text-2xl font-bold tabular-nums whitespace-nowrap text-red-400">€{spentMonth.toFixed(2)}</p>
          {extraMonth > 0 && (
            <p className="text-[11px] text-gray-500 mt-1"
               title="Compras grandes e pontuais. Contam aqui, mas não na média por dia, na comparação com o mês passado, no orçamento nem nos avisos.">
              dos quais €{extraMonth.toFixed(0)} extraordinários
            </p>
          )}
        </div>
        <div className="bg-[#161616] rounded-2xl p-4 sm:p-5 border border-[#222] min-w-0"
          title={ciclo
            ? 'O que entrou além do salário (que tem cartão próprio): vendas, dinheiro de amigos que não descontou numa conta.'
            : 'Dinheiro que entrou na conta: bolsa, reembolsos, vendas e dinheiro de amigos. Não conta o que só mudou de conta.'}>
          <p className="text-xs text-gray-500 mb-1">Recebido</p>
          <p className="text-xl sm:text-2xl xl:text-xl 2xl:text-2xl font-bold tabular-nums whitespace-nowrap text-green-400">€{recebido.toFixed(2)}</p>
        </div>
        <div className="bg-[#161616] rounded-2xl p-4 sm:p-5 border border-[#222] min-w-0"
          title="O que entrou na conta menos o que gastaste, mais as devoluções de compras de outros períodos. Não desconta a Klarna. Sem entradas medidas (meses antigos) usa o Rendimento, que é escrito à mão e fica desactualizado.">
          <p className="text-xs text-gray-500 mb-1">Restante</p>
          <p className={`text-xl sm:text-2xl xl:text-xl 2xl:text-2xl font-bold tabular-nums whitespace-nowrap ${remaining >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            €{remaining.toFixed(2)}
          </p>
          {klarnaDoMes && (
            <p className="text-[11px] text-pink-300/80 mt-1 tabular-nums whitespace-nowrap" title={klarnaDetalhe(klarnaDoMes)}>
              €{klarnaDoMes.total.toFixed(2)} para a Klarna
            </p>
          )}
          {Math.abs(estornosSoltos) >= 0.01 && (
            <p className="text-[11px] text-gray-500 mt-0.5 tabular-nums whitespace-nowrap"
              title={expenses.filter(e => e.kind === 'reversal').map(e => `${e.description} · ${e.date} · €${(-e.amount).toFixed(2)}`).join('\n')}>
              {estornosSoltos > 0 ? 'inclui' : 'desconta'} €{Math.abs(estornosSoltos).toFixed(2)} de devoluções
            </p>
          )}
        </div>
        <div className="bg-[#161616] rounded-2xl p-4 sm:p-5 border border-[#222] min-w-0">
          <p className="text-xs text-gray-500 mb-1">Transações</p>
          <p className="text-xl sm:text-2xl xl:text-xl 2xl:text-2xl font-bold tabular-nums whitespace-nowrap">{expenses.length}</p>
        </div>
        <div className="bg-[#161616] rounded-2xl p-4 sm:p-5 border border-[#222] min-w-0">
          <p className="text-xs text-gray-500 mb-1">Média/dia</p>
          <p className="text-xl sm:text-2xl xl:text-xl 2xl:text-2xl font-bold tabular-nums whitespace-nowrap text-yellow-400">
            €{(correnteMonth / (ciclo ? ciclo.dias : isSameMonth(currentMonth, new Date()) ? (new Date().getDate() || 1) : getDaysInMonth(currentMonth))).toFixed(2)}
          </p>
        </div>
      </div>

      {/* Abas */}
      <div className="flex gap-1 mb-6 bg-[#161616] border border-[#222] rounded-xl p-1 overflow-x-auto lg:shrink-0">
        {([['resumo', 'Resumo'], ['transacoes', 'Transações'], ['ano', 'Ano'], ['viagens', 'Viagens'], ['orcamento', 'Orçamento'], ['wishlist', 'Wishlist']] as const).map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${tab === k ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'orcamento' && (<>
      <BancoLigado />
      <CustoDeVida />
      <GastosPorHora />
      {/* Plano do Salário */}
      {salaryPlan && (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 sm:p-5 mb-6">
          <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
            <div>
              <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
                <PiggyBank size={15} className="text-green-400" /> Plano do Salário
              </h3>
              <p className="text-[11px] text-gray-500 mt-0.5">
                {ciclo
                  ? <>Desde o salário de {format(ciclo.inicio, 'd MMM', { locale: pt })}{ciclo.fim ? ` até ${format(ciclo.fim, 'd MMM', { locale: pt })}` : ''}</>
                  : <span className="capitalize">{format(currentMonth, 'MMMM yyyy', { locale: pt })}</span>}
                {' · '}Salário €{salaryPlan.salary.toFixed(0)} · {salaryPlan.allocated_pct}% alocado · {salaryPlan.savings_pct}% poupança
              </p>
            </div>
            <button onClick={openBucketNew} className="text-xs text-green-400 hover:text-green-300">+ Grupo</button>
          </div>

          {salaryPlan.over_allocated && (
            <div className="flex items-center gap-2 text-[11px] text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2 mb-3">
              <AlertTriangle size={12} /> Os grupos somam {salaryPlan.allocated_pct}% do salário — passaste dos 100%.
            </div>
          )}

          <div className="space-y-3.5">
            {salaryPlan.groups.map((g: any) => {
              const pct = Math.min(g.pct_used, 100);
              const isSave = g.kind === 'save';
              const barColor = isSave
                ? (g.status === 'met' ? '#10B981' : '#3B82F6')
                : (g.status === 'over' ? '#EF4444' : g.status === 'warning' ? '#F59E0B' : '#10B981');
              return (
                <div key={g.id} className="group cursor-pointer" onClick={() => openBucketEdit(g)}>
                  <div className="flex items-center justify-between mb-1 gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: g.color }} />
                      <span className="text-sm font-medium truncate">{g.name}</span>
                      <span className="text-[10px] text-gray-500 shrink-0">{g.percentage}%</span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-xs font-medium" style={{ color: barColor }}>
                        €{g.spent.toFixed(0)} / €{g.target.toFixed(0)}
                      </span>
                      <span className="text-[10px] text-gray-500 w-9 text-right">{g.pct_used}%</span>
                    </div>
                  </div>
                  <div className="h-2 bg-[#222] rounded-full overflow-hidden">
                    <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: barColor }} />
                  </div>
                  <div className="flex items-center justify-between mt-1 gap-2">
                    <span className="text-[10px] text-gray-600 truncate">
                      {g.categories.map((c: string) => getCategoryInfo(c).emoji).join(' ') || '—'}
                    </span>
                    <span className="text-[10px] shrink-0" style={{ color: isSave ? '#10B981' : (g.remaining < 0 ? '#EF4444' : '#6B7280') }}>
                      {isSave
                        ? (g.remaining <= 0 ? 'Meta atingida ✓' : `Faltam €${g.remaining.toFixed(0)}`)
                        : (g.remaining < 0 ? `Passou €${Math.abs(g.remaining).toFixed(0)}` : `Restam €${g.remaining.toFixed(0)}`)}
                    </span>
                  </div>
                </div>
              );
            })}

            {salaryPlan.savings_pct > 0 && (() => {
              const target = salaryPlan.savings_target;
              const saved = salaryPlan.actual_saved;
              const pct = target > 0 ? Math.min(Math.max(saved / target * 100, 0), 100) : 0;
              const met = saved >= target && target > 0;
              return (
                <div className="pt-3 border-t border-[#1e1e1e]">
                  <div className="flex items-center justify-between mb-1 gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="w-2.5 h-2.5 rounded-full shrink-0 bg-emerald-400" />
                      <span className="text-sm font-medium truncate">Poupança <span className="text-gray-500 font-normal text-xs">(sobra)</span></span>
                      <span className="text-[10px] text-gray-500 shrink-0">{salaryPlan.savings_pct}%</span>
                    </div>
                    <span className="text-xs font-medium" style={{ color: met ? '#10B981' : (saved < 0 ? '#EF4444' : '#9CA3AF') }}>
                      €{saved.toFixed(0)} / €{target.toFixed(0)}
                    </span>
                  </div>
                  <div className="h-2 bg-[#222] rounded-full overflow-hidden">
                    <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: saved < 0 ? '#EF4444' : '#10B981' }} />
                  </div>
                  <p className="text-[10px] text-gray-600 mt-1">
                    {saved < 0 ? `Gastaste €${Math.abs(saved).toFixed(0)} acima do salário` : met ? 'Objetivo de poupança atingido ✓' : `Sobrou €${saved.toFixed(0)} ${ciclo ? 'deste salário' : 'este mês'}`}
                  </p>
                </div>
              );
            })()}
          </div>

          {salaryPlan.unbudgeted_spent > 0 && (
            <p className="text-[10px] text-gray-600 mt-3">
              €{salaryPlan.unbudgeted_spent.toFixed(0)} em categorias fora dos grupos ({salaryPlan.unbudgeted.map((u: any) => getCategoryInfo(u.category).label).join(', ')})
            </p>
          )}
        </div>
      )}

      {tab === 'orcamento' && <SubscricoesDetectadas onAdded={loadData} />}

      {/* Subscriptions Tracker — always visible */}
      <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 mb-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
            <CreditCard size={14} className="text-purple-400" /> Subscrições Mensais
            {subsSummary && (
              <span className="text-xs text-gray-500 font-normal">
                · €{subsSummary.monthly_total?.toFixed(2)}/mês
              </span>
            )}
          </h3>
          <button onClick={() => { setEditingSub(null); setSubForm({ name: '', amount: 0, currency: 'EUR', billing_cycle: 'monthly', next_renewal: format(new Date(), 'yyyy-MM-dd'), category: 'subscriptions', notes: '' }); setShowSubModal(true); }}
            className="text-xs text-purple-400 hover:text-purple-300">
            + Subscrição
          </button>
        </div>
        {subscriptions.length === 0 ? (
          <div className="py-6 text-center text-gray-600">
            <p className="text-xs">Sem subscrições registadas. Adiciona as tuas despesas recorrentes (renda, Netflix, Claude Pro, etc.)</p>
          </div>
        ) : (
          <div className="divide-y divide-[#1a1a1a]">
            {subscriptions.map((sub: any) => (
              <div key={sub.id}
                onClick={() => { setEditingSub(sub); setSubForm({ name: sub.name, amount: sub.amount, currency: sub.currency, billing_cycle: sub.billing_cycle, next_renewal: sub.next_renewal || '', category: sub.category, notes: sub.notes || '' }); setShowSubModal(true); }}
                className="flex items-center gap-3 py-3 hover:bg-white/5 cursor-pointer rounded-lg px-2 -mx-2">
                <div className="w-8 h-8 bg-purple-500/20 rounded-lg flex items-center justify-center text-sm">
                  {sub.category === 'subscriptions' ? '📱' : getCategoryInfo(sub.category).emoji}
                </div>
                <div className="flex-1">
                  <p className="text-sm font-medium">{sub.name}</p>
                  <p className="text-[10px] text-gray-500">
                    {sub.billing_cycle === 'monthly' ? 'Mensal' : sub.billing_cycle === 'yearly' ? 'Anual' : sub.billing_cycle}
                    {sub.next_renewal && ` · Renova ${format(new Date(sub.next_renewal), 'd MMM', { locale: pt })}`}
                  </p>
                </div>
                <span className={`text-sm font-bold ${sub.active ? 'text-purple-400' : 'text-gray-600 line-through'}`}>
                  €{sub.amount.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      </>)}

      {tab === 'wishlist' && (
      /* Wishlist / Desejos */
      <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 mb-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
            <Gift size={14} className="text-pink-400" /> Wishlist
            {wishSummary && wishSummary.count > 0 && (
              <span className="text-xs text-gray-500 font-normal">
                · faltam €{wishSummary.total_remaining.toFixed(0)} de €{wishSummary.total_wanted.toFixed(0)}
              </span>
            )}
          </h3>
          <button onClick={openWishNew} className="text-xs text-pink-400 hover:text-pink-300">+ Desejo</button>
        </div>

        {wishItems.length === 0 ? (
          <div className="py-6 text-center text-gray-600">
            <p className="text-xs">Sem desejos ainda. Adiciona coisas que queres comprar (ex: pulseira Garmin, cadeira de secretária) e vai juntando para elas.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {wishItems.filter(w => !w.purchased).map(w => {
              const pct = w.price > 0 ? Math.min(100, (w.saved_amount / w.price) * 100) : 0;
              const remaining = Math.max(0, w.price - w.saved_amount);
              const prio = w.priority === 'high'
                ? { label: 'Alta', cls: 'bg-red-500/20 text-red-400' }
                : w.priority === 'low'
                ? { label: 'Baixa', cls: 'bg-gray-500/20 text-gray-400' }
                : { label: 'Média', cls: 'bg-amber-500/20 text-amber-400' };
              const done = pct >= 100;
              return (
                <div key={w.id} className="bg-[#111] rounded-xl border border-[#222] p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="w-7 h-7 bg-pink-500/15 rounded-lg flex items-center justify-center text-sm shrink-0">
                      {getCategoryInfo(w.category).emoji}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium truncate">{w.name}</p>
                        <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-medium ${prio.cls}`}>{prio.label}</span>
                        {w.url && (
                          <a href={w.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} className="text-gray-500 hover:text-pink-400">
                            <ExternalLink size={12} />
                          </a>
                        )}
                      </div>
                      {w.notes && <p className="text-[10px] text-gray-500 truncate">{w.notes}</p>}
                    </div>
                    <span className="text-sm font-bold text-pink-400 shrink-0">€{w.price.toFixed(0)}</span>
                  </div>

                  <div className="h-1.5 bg-[#0a0a0a] rounded-full overflow-hidden mb-1">
                    <div className={`h-full rounded-full ${done ? 'bg-green-500' : 'bg-pink-500'}`} style={{ width: `${pct}%` }} />
                  </div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] text-gray-500">
                      €{w.saved_amount.toFixed(0)} juntos{done ? ' · pronto!' : ` · faltam €${remaining.toFixed(0)}`}
                    </span>
                    <span className="text-[10px] text-gray-600">{pct.toFixed(0)}%</span>
                  </div>

                  {planos[w.id] && (
                    <div className="mb-2 text-[10px] text-gray-500 space-y-1">
                      {planos[w.id].weeks_needed !== null && planos[w.id].missing > 0 && (
                        <p>
                          Ao ritmo do que te sobra (€{planos[w.id].weekly_leftover.toFixed(0)}/semana),
                          chegas lá em {planos[w.id].weeks_needed} semana{planos[w.id].weeks_needed === 1 ? '' : 's'}
                          {planos[w.id].target_date && ` · ${new Date(planos[w.id].target_date!).toLocaleDateString('pt-PT', { day: 'numeric', month: 'short' })}`}
                        </p>
                      )}
                      {planos[w.id].best_deal && (
                        <a href={planos[w.id].best_deal!.url} target="_blank" rel="noreferrer"
                          className="flex items-center gap-1 text-emerald-400 hover:text-emerald-300">
                          <Tag size={10} /> já apareceu por €{planos[w.id].best_deal!.price.toFixed(0)}
                          <span className="text-gray-600 truncate">· {planos[w.id].best_deal!.title.slice(0, 34)}</span>
                        </a>
                      )}
                    </div>
                  )}

                  <div className="flex items-center gap-2">
                    {!w.watch_id && (
                      <button onClick={() => vigiarNosDeals(w)} disabled={aVigiar === w.id}
                        className="flex-1 text-[11px] py-1.5 rounded-lg bg-pink-500/10 hover:bg-pink-500/20 text-pink-300 flex items-center justify-center gap-1 disabled:opacity-40">
                        <Tag size={12} /> {aVigiar === w.id ? 'a criar…' : 'Vigiar nos deals'}
                      </button>
                    )}
                    <button onClick={() => addSavingToWish(w)} className="flex-1 text-[11px] py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-gray-300 flex items-center justify-center gap-1">
                      <PiggyBank size={12} /> Juntar
                    </button>
                    <button onClick={() => purchaseWish(w)} className={`flex-1 text-[11px] py-1.5 rounded-lg flex items-center justify-center gap-1 ${done ? 'bg-green-600 hover:bg-green-700 text-white' : 'bg-pink-600/80 hover:bg-pink-600 text-white'}`}>
                      <Check size={12} /> Comprei
                    </button>
                    <button onClick={() => openWishEdit(w)} className="px-2.5 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-gray-400">
                      <Pencil size={12} />
                    </button>
                  </div>
                </div>
              );
            })}

            {wishItems.some(w => w.purchased) && (
              <div className="pt-2 mt-1 border-t border-[#1a1a1a] space-y-1">
                <p className="text-[10px] text-gray-600 uppercase tracking-wide mb-1">Comprados</p>
                {wishItems.filter(w => w.purchased).map(w => {
                  const pg = w.paid;
                  const k = pg?.klarna;
                  return (
                  <div key={w.id} className="py-1.5 px-1 text-gray-500">
                    <div className="flex items-center gap-2">
                      <Check size={13} className="text-green-500 shrink-0" />
                      <span className="text-xs line-through flex-1 truncate">{w.name}</span>
                      <span className="text-[10px] text-gray-600 text-right"
                        title={pg ? `${pg.description} · ${pg.date}` : undefined}>
                        {w.purchased_date && format(new Date(`${w.purchased_date}T00:00:00`), 'd MMM', { locale: pt })}
                        {' · '}
                        {k
                          ? <>€{k.installment.toFixed(2)} × {k.of} <span className="text-pink-400">Klarna</span> ({k.paid}/{k.of} pagas · €{k.total.toFixed(0)})</>
                          : `€${(pg?.amount ?? w.price).toFixed(2)}`}
                      </span>
                      <button onClick={() => unpurchaseWish(w)} className="text-[10px] text-gray-600 hover:text-gray-300">desfazer</button>
                      <button onClick={() => deleteWish(w.id)} className="text-gray-700 hover:text-red-400"><Trash2 size={12} /></button>
                    </div>
                    {(pg?.made_here || (!pg && w.expense_id == null)) && (
                      <button onClick={() => purchaseWish(w)}
                        className="ml-5 mt-0.5 text-[10px] text-amber-400 hover:text-amber-300">
                        {pg?.made_here ? 'este gasto foi criado pela wishlist e é uma cópia — escolher a transação verdadeira' : 'escolher a transação desta compra'}
                      </button>
                    )}
                  </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
      )}

      {tab === 'transacoes' && (
        <div className="space-y-4">
          {/* O que falta guardar para a Klarna, na mesma linha dos botões de
              importar / categorizar */}
          {/* Uma linha só, a ocupar a largura toda: cada peça estica. */}
          <div className="flex flex-wrap xl:flex-nowrap items-stretch gap-1.5 text-sm [&>*]:flex-1 [&>*]:justify-center [&>*]:whitespace-nowrap">
            {/* Escolhe-se aqui mas vale na página toda: a escolha fica guardada e
                não volta ao mês ao mudar de aba. */}
            <div className="flex bg-[#161616] border border-[#222] rounded-xl p-0.5"
              title="Desde o salário: o período começa no dia em que o salário entrou e acaba na véspera do seguinte. Vale na página toda, menos no Orçamento.">
              {([['mes', 'Mês'], ['salario', 'Desde o salário']] as const).map(([k, rot]) => (
                <button key={k} onClick={() => { setPeriodo(k); setCicloIdx(null); }}
                  className={`flex-1 px-2.5 py-1 rounded-lg font-medium whitespace-nowrap transition-colors ${periodo === k ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}>
                  {rot}
                </button>
              ))}
            </div>
            {klarna && klarna.months.length > 0 && (
              <div className="!flex-[2] flex items-center gap-x-2.5 px-3 py-1.5 bg-pink-600/15 rounded-xl border border-pink-500/30"
                title={`a guardar para a Klarna · ao todo €${klarna.total.toFixed(2)}`}>
                <span className="flex items-center gap-2 font-medium text-pink-300">
                  <CreditCard size={15} /> <span className="hidden 2xl:inline">Klarna</span>
                </span>
                {klarna.months.map(m => (
                  <span key={m.month} className="tabular-nums border-l border-pink-500/25 pl-2.5" title={klarnaDetalhe(m)}>
                    <span className="text-pink-300/60">
                      {MESES[+m.month.slice(5) - 1]}{+m.month.slice(0, 4) !== new Date().getFullYear() && ` ${m.month.slice(2, 4)}`}
                    </span>{' '}
                    <span className="font-semibold text-gray-100">€{m.total.toFixed(2)}</span>
                  </span>
                ))}
              </div>
            )}
            {reemb && reemb.pending.length > 0 && (
              <div className="flex items-center gap-2 px-3 py-1.5 bg-teal-600/15 rounded-xl border border-teal-500/30"
                title={reemb.pending.map(p => `${p.expense.description} · ${format(new Date(`${p.expense.date}T00:00:00`), 'd MMM', { locale: pt })} · €${p.expense.amount.toFixed(2)} · ${p.missing_people ? `faltam ${p.missing_people} · ` : ''}€${p.missing.toFixed(2)} por receber`).join('\n')}>
                <Users size={15} className="text-teal-300" />
                <span className="text-teal-300/80">A receber</span>
                <span className="font-semibold text-gray-100 tabular-nums">€{reemb.total_pending.toFixed(2)}</span>
              </div>
            )}
            <label className="flex items-center gap-2 px-3 py-1.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl font-medium cursor-pointer border border-[#333]">
              <FileSpreadsheet size={15} /> {csvImporting ? 'A importar...' : 'CSV'}
              <input type="file" className="hidden" accept=".csv"
                onChange={e => { const f = e.target.files?.[0]; if (f) handleCSVImport(f); e.target.value = ''; }}
                disabled={csvImporting} />
            </label>
            <label className="flex items-center gap-2 px-3 py-1.5 bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 rounded-xl font-medium cursor-pointer border border-blue-500/30">
              <FileText size={15} /> {pdfImporting ? 'A importar...' : <span><span className="hidden 2xl:inline">Revolut </span>PDF</span>}
              <input type="file" className="hidden" accept=".pdf"
                onChange={e => { const f = e.target.files?.[0]; if (f) handlePDFImport(f); e.target.value = ''; }}
                disabled={pdfImporting} />
            </label>
            <button onClick={handleRecategorize} disabled={recategorizing || expenses.length === 0}
              className="flex items-center gap-2 px-3 py-1.5 bg-purple-600/20 hover:bg-purple-600/30 text-purple-400 rounded-xl font-medium border border-purple-500/30 disabled:opacity-50">
              <Sparkles size={15} /> {recategorizing ? 'A categorizar...' : <span><span className="hidden 2xl:inline">Categorizar com </span>IA (mês)</span>}
            </button>
            <button onClick={handleRecategorizeYear} disabled={recategorizing}
              className="flex items-center gap-2 px-3 py-1.5 bg-purple-600/20 hover:bg-purple-600/30 text-purple-400 rounded-xl font-medium border border-purple-500/30 disabled:opacity-50">
              <Sparkles size={15} /> Ano
            </button>
          </div>

          {/* Expense List */}
          <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
            <div className="p-3 border-b border-[#222] flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-medium text-gray-300">Transações</h3>
              <div className="relative flex-1 min-w-[140px]">
                <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-600" />
                <input type="text" value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
                  placeholder="Procurar…"
                  className="w-full bg-[#222] border border-[#333] rounded-lg pl-7 pr-6 py-1 text-xs text-gray-300 focus:outline-none focus:border-gray-500" />
                {searchQuery && (
                  <button onClick={() => setSearchQuery('')} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-gray-600 hover:text-white"><X size={12} /></button>
                )}
              </div>
              <select value={typeFilter} onChange={e => setTypeFilter(e.target.value as any)}
                className="bg-[#222] border border-[#333] rounded-lg px-2 py-1 text-xs text-gray-300 focus:outline-none">
                <option value="all">Tudo</option>
                <option value="spend">Gastos</option>
                <option value="income">Entradas</option>
                <option value="transfer">Transferências</option>
                <option value="reversal">Reembolsados</option>
              </select>
              <select value={categoryFilter ?? ''} onChange={e => setCategoryFilter(e.target.value || null)}
                className="bg-[#222] border border-[#333] rounded-lg px-2 py-1 text-xs text-gray-300 focus:outline-none">
                <option value="">Todas as categorias</option>
                {categoryOptions.map(cat => (
                  <option key={cat} value={cat}>{getCategoryInfo(cat).emoji} {getCategoryInfo(cat).label}</option>
                ))}
              </select>
              <select value={sortBy} onChange={e => setSortBy(e.target.value as any)}
                className="bg-[#222] border border-[#333] rounded-lg px-2 py-1 text-xs text-gray-300 focus:outline-none">
                <option value="date">Por data</option>
                <option value="amount">Por valor</option>
              </select>
              {hasActiveFilters && (
                <button onClick={() => { setCategoryFilter(null); setTypeFilter('all'); setSearchQuery(''); }}
                  className="text-[11px] text-gray-500 hover:text-white flex items-center gap-1">
                  <X size={12} /> limpar
                </button>
              )}
              <span className="text-xs text-gray-500 whitespace-nowrap">
                {visibleExpenses.length} · <span className={filteredTotal < 0 ? 'text-green-400' : ''}>{filteredTotal < 0 ? '+' : ''}€{Math.abs(filteredTotal).toFixed(2)}</span>
              </span>
            </div>
            <div className="divide-y divide-[#1a1a1a]">
              {visibleExpenses.length === 0 ? (
                <div className="p-8 text-center text-gray-600">{categoryFilter ? 'Sem transações nesta categoria' : ciclo ? 'Sem gastos desde o salário' : 'Sem gastos este mês'}</div>
              ) : (
                visibleExpenses.map(exp => {
                  const catInfo = getCategoryInfo(exp.category);
                  const hasOrigCurrency = exp.original_currency && exp.original_currency !== 'EUR';
                  return (
                    <div key={exp.id} onClick={() => openEdit(exp)}
                      className="flex items-center gap-4 p-4 hover:bg-white/5 cursor-pointer">
                      <div className="text-2xl">{catInfo.emoji}</div>
                      <div className="flex-1">
                        <p className="text-sm font-medium flex items-center gap-1.5">
                          {exp.description}
                          {dicaReembolso(exp.id) && (
                            <span title={dicaReembolso(exp.id)!} className="text-teal-300"><HandCoins size={14} /></span>
                          )}
                        </p>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-xs text-gray-500">
                            {catInfo.label} · {format(new Date(exp.date), 'd MMM', { locale: pt })}
                            {exp.time_of_day && ` · ${exp.time_of_day}`}
                          </span>
                          {exp.merchant_country && (
                            <span className="text-xs text-gray-500">· {exp.merchant_city}{exp.merchant_country ? `, ${exp.merchant_country}` : ''}</span>
                          )}
                          {exp.kind && exp.kind !== 'spend' && (
                            <span className={`text-[10px] px-1.5 py-0.5 rounded-md ${ETIQUETA_TIPO[exp.kind as ExpenseKind]?.cls || ''}`}
                              title={ETIQUETA_TIPO[exp.kind as ExpenseKind]?.dica}>
                              {ETIQUETA_TIPO[exp.kind as ExpenseKind]?.rot}
                            </span>
                          )}
                          {exp.extraordinary && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded-md bg-purple-500/15 text-purple-300"
                              title="Compra grande e pontual: conta no total do mês, mas fica fora das comparações, do orçamento e dos avisos.">
                              extraordinário
                            </span>
                          )}
                          {exp.reimburses_id && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded-md bg-teal-500/15 text-teal-300"
                              title="A parte de alguém numa conta que pagaste: desconta nela em vez de contar como entrada.">
                              desconta em {exp.reimburses_description || 'uma conta'}
                            </span>
                          )}
                          {(klarnaDe[exp.id] || exp.klarna_installments) && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded-md bg-pink-500/15 text-pink-300">
                              Klarna {klarnaDe[exp.id] || `${exp.klarna_installments}×`}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="flex flex-col items-end gap-0.5">
                        <div className="flex items-center gap-2">
                          {exp.receipt_image && <Receipt size={14} className="text-gray-500" />}
                          {exp.amount < 0 ? (
                            <span className="text-sm font-bold text-green-400">+€{Math.abs(exp.amount).toFixed(2)}</span>
                          ) : (
                            <span className="text-sm font-bold text-red-400">-€{exp.amount.toFixed(2)}</span>
                          )}
                        </div>
                        {hasOrigCurrency && (
                          <span className="text-[10px] text-gray-500">
                            {exp.original_amount?.toFixed(2)} {exp.original_currency}
                          </span>
                        )}
                        {exp.amount > 0 && (exp.split_people || exp.my_share != null || (exp.reimbursed_total || 0) > 0) && (
                          <span className="text-[10px] text-teal-300/90 tabular-nums whitespace-nowrap"
                            title={`${exp.reimbursed_count || 0} reembolso(s): €${(exp.reimbursed_total || 0).toFixed(2)}`}>
                            a tua parte €{parteDele(exp).toFixed(2)}
                            {faltaReceber(exp) > 0.01 && <span className="text-amber-300/90"> · faltam €{faltaReceber(exp).toFixed(2)}</span>}
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}

      {tab === 'resumo' && (
        // Duas colunas: a comparação com o mês passado à esquerda, as categorias
        // à direita a esticar até ao fundo. A lista das categorias rola dentro
        // do cartão — empilhadas, o mês passado empurrava o gráfico para fora.
        <div className="flex flex-col lg:flex-row gap-4 lg:gap-6 lg:flex-1 lg:min-h-0">
          {prevSpent > 0 && (() => {
            // Dos dois lados sem compras extraordinárias: um mês com a mota
            // contra um mês de supermercado não diz nada sobre o mês.
            const delta = correnteMonth - prevSpent;
            const pct = prevSpent > 0 ? (delta / prevSpent) * 100 : 0;
            const up = delta > 0;
            const prevName = ciclo ? 'o salário anterior' : format(subMonths(currentMonth, 1), 'MMMM', { locale: pt });
            const curByCat: Record<string, number> = {};
            expenses.forEach(e => { if (eGasto(e) && !e.extraordinary) curByCat[e.category] = (curByCat[e.category] || 0) + e.amount; });
            const cats = Array.from(new Set([...Object.keys(curByCat), ...Object.keys(prevByCat)]));
            const changes = cats
              .map(c => ({ c, now: curByCat[c] || 0, before: prevByCat[c] || 0, diff: (curByCat[c] || 0) - (prevByCat[c] || 0) }))
              .filter(x => Math.abs(x.diff) >= 1)
              .sort((a, b) => Math.abs(b.diff) - Math.abs(a.diff))
              .slice(0, 4);
            return (
              <div className="bg-[#161616] rounded-2xl border border-[#222] p-5
                lg:w-[320px] xl:w-[360px] lg:shrink-0 lg:overflow-y-auto">
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">vs {prevName}</p>
                <div className="flex items-baseline gap-3">
                  <span className="text-3xl font-semibold text-white"
                        title={extraMonth > 0 ? `Sem os €${extraMonth.toFixed(0)} de compras extraordinárias` : undefined}>
                    €{correnteMonth.toFixed(0)}
                  </span>
                  <span className={`flex items-center gap-1 text-sm font-semibold ${up ? 'text-red-400' : 'text-green-400'}`}>
                    {up ? '▲' : '▼'} {Math.abs(pct).toFixed(0)}%
                  </span>
                </div>
                <p className="text-xs text-gray-500 mt-1 mb-4">
                  {up ? '+' : '−'}€{Math.abs(delta).toFixed(0)} vs €{prevSpent.toFixed(0)} {ciclo ? 'no' : 'em'} <span className={ciclo ? '' : 'capitalize'}>{prevName}</span>
                  {extraMonth > 0 && <span className="block mt-0.5">sem os €{extraMonth.toFixed(0)} extraordinários {ciclo ? 'deste salário' : 'deste mês'}</span>}
                </p>
                {changes.length > 0 && (
                  <div className="space-y-3 pt-4 border-t border-[#222]">
                    {changes.map(x => (
                      <div key={x.c} className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2.5 min-w-0">
                          <span className="text-base shrink-0">{getCategoryInfo(x.c).emoji}</span>
                          <div className="min-w-0">
                            <p className="text-xs text-gray-300 truncate">{getCategoryInfo(x.c).label}</p>
                            <p className="text-[11px] text-gray-600 tabular-nums">€{x.before.toFixed(0)} → €{x.now.toFixed(0)}</p>
                          </div>
                        </div>
                        <span className={`shrink-0 text-xs font-semibold tabular-nums px-2 py-0.5 rounded-full ${
                          x.diff > 0 ? 'bg-red-500/10 text-red-400' : 'bg-green-500/10 text-green-400'}`}>
                          {x.diff > 0 ? '+' : '−'}€{Math.abs(x.diff).toFixed(0)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })()}
          <div className="bg-[#161616] rounded-2xl border border-[#222] p-4
            lg:flex-1 lg:min-h-0 lg:flex lg:flex-col">
            <h3 className="text-sm font-medium text-gray-300 mb-4 shrink-0">Por Categoria</h3>
            {pieData.length > 0 ? (
              // O gráfico leva a altura que sobrar depois da lista, com tecto: um
              // donut de 400px de raio não diz mais nada do que um de 200.
              <div className="h-[200px] lg:h-auto lg:flex-1 lg:min-h-[160px] lg:max-h-[280px] shrink-0">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} dataKey="value" paddingAngle={3}
                    onClick={(d: any) => d?.category && pickCategory(d.category)} className="cursor-pointer">
                    {pieData.map((_, idx) => (
                      <Cell key={idx} fill={COLORS[idx % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ backgroundColor: 'var(--app-surface-3)', color: 'var(--app-text)', border: 'none', borderRadius: '12px', fontSize: '12px' }}
                    formatter={(value: number) => [`€${value.toFixed(2)}`, '']}
                  />
                </PieChart>
              </ResponsiveContainer>
              </div>
            ) : (
              <div className="h-[200px] flex items-center justify-center text-gray-600 text-sm">Sem dados</div>
            )}
            {/* A lista rola dentro do cartão: com quinze categorias era ela que
                fazia a página inteira rolar. */}
            <div className="space-y-2 mt-4 lg:flex-1 lg:min-h-0 lg:overflow-y-auto">
              {pieData.map((s, i) => {
                const catInfo = getCategoryInfo(s.category);
                return (
                  <button key={s.category} onClick={() => pickCategory(s.category)}
                    className="w-full flex items-center gap-2 rounded-lg px-2 py-1 -mx-2 transition-colors hover:bg-white/5">
                    <div className="w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                    <span className="text-xs text-gray-400 flex-1 text-left">{catInfo.emoji} {catInfo.label} <span className="text-gray-600">· {s.count}</span></span>
                    <span className="text-xs font-medium">€{s.value.toFixed(2)}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Onde o dinheiro foi gasto, no mapa. Estava no fundo da aba do Ano, por
          baixo das tabelas todas — é sobre viagens, não sobre o ano. */}
      {tab === 'viagens' && (
        <div className="flex flex-col gap-4 lg:flex-1 lg:min-h-0">
          <div className="flex items-center gap-1 bg-[#161616] border border-[#222] rounded-xl p-1 w-fit shrink-0">
            <button onClick={() => setYearNum(y => y - 1)} className="p-1.5 hover:bg-white/10 rounded-lg"><ChevronLeft size={18} /></button>
            <span className="text-sm font-bold w-14 text-center">{yearNum}</span>
            <button onClick={() => setYearNum(y => y + 1)} className="p-1.5 hover:bg-white/10 rounded-lg"><ChevronRight size={18} /></button>
          </div>
          <MapaDeGastos ano={yearNum} />
        </div>
      )}

      {tab === 'ano' && (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1 bg-[#161616] border border-[#222] rounded-xl p-1">
              <button onClick={() => setYearNum(y => y - 1)} className="p-1.5 hover:bg-white/10 rounded-lg"><ChevronLeft size={18} /></button>
              <span className="text-sm font-bold w-14 text-center">{yearNum}</span>
              <button onClick={() => setYearNum(y => y + 1)} className="p-1.5 hover:bg-white/10 rounded-lg"><ChevronRight size={18} /></button>
            </div>
            <select value={yearCat} onChange={e => setYearCat(e.target.value)}
              className="bg-[#222] border border-[#333] rounded-lg px-3 py-2 text-sm text-gray-300 focus:outline-none">
              <option value="">Todas as categorias</option>
              {(yearData?.categories || []).map((c: string) => (
                <option key={c} value={c}>{getCategoryInfo(c).emoji} {getCategoryInfo(c).label}</option>
              ))}
            </select>
          </div>

          {yearData && (() => {
            const filled = yearData.months.filter((m: any) => Object.keys(m.by_category).length > 0);
            const vals = filled.map((m: any) => yearCat ? (m.by_category[yearCat] || 0) : m.total);
            const totalSel = yearCat ? (yearData.category_totals[yearCat] || 0) : yearData.total;
            const activeN = vals.length || 1;
            const maxV = Math.max(...vals, 0);
            const peakIdx = vals.indexOf(maxV);
            const barColor = yearCat ? COLORS[Math.max(0, yearData.categories.indexOf(yearCat)) % COLORS.length] : '#3B82F6';
            const barData = filled.map((m: any, i: number) => ({ name: MESES[m.month - 1], valor: Math.max(0, vals[i]) }));
            return (
              <>
                <div className={`grid gap-3 ${yearCat ? 'grid-cols-2 sm:grid-cols-3' : 'grid-cols-2 sm:grid-cols-4'}`}>
                  {yearCat ? (
                    <div className="bg-[#161616] rounded-2xl p-4 border border-[#222] min-w-0">
                      <p className="text-xs text-gray-500 mb-1 truncate">Total {getCategoryInfo(yearCat).label}</p>
                      <p className="text-lg sm:text-xl font-bold tabular-nums whitespace-nowrap text-red-400">€{totalSel.toFixed(2)}</p>
                    </div>
                  ) : (
                    <>
                      <div className="bg-[#161616] rounded-2xl p-4 border border-[#222] min-w-0">
                        <p className="text-xs text-gray-500 mb-1">Recebido no ano</p>
                        <p className="text-lg sm:text-xl font-bold tabular-nums whitespace-nowrap text-green-400">€{yearData.total_received.toFixed(2)}</p>
                        <p className="text-[10px] text-gray-600 mt-0.5">salário €{yearData.total_salary.toFixed(0)} + entradas €{yearData.total_refunds.toFixed(0)}</p>
                      </div>
                      <div className="bg-[#161616] rounded-2xl p-4 border border-[#222] min-w-0">
                        <p className="text-xs text-gray-500 mb-1">Gasto no ano</p>
                        <p className="text-lg sm:text-xl font-bold tabular-nums whitespace-nowrap text-red-400">€{yearData.total_spent.toFixed(2)}</p>
                      </div>
                    </>
                  )}
                  <div className="bg-[#161616] rounded-2xl p-4 border border-[#222] min-w-0">
                    <p className="text-xs text-gray-500 mb-1">Média/mês</p>
                    <p className="text-lg sm:text-xl font-bold tabular-nums whitespace-nowrap text-yellow-400">€{(totalSel / activeN).toFixed(2)}</p>
                  </div>
                  <div className="bg-[#161616] rounded-2xl p-4 border border-[#222] min-w-0">
                    <p className="text-xs text-gray-500 mb-1">Mês pico</p>
                    <p className="text-lg sm:text-xl font-bold tabular-nums whitespace-nowrap">{maxV > 0 ? MESES[filled[peakIdx].month - 1] : '—'}</p>
                  </div>
                </div>

                <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
                  <h3 className="text-sm font-medium text-gray-300 mb-4">
                    {yearCat ? `${getCategoryInfo(yearCat).emoji} ${getCategoryInfo(yearCat).label} por mês` : 'Gastos por mês'} · {yearNum}
                  </h3>
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={barData}>
                      <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#9CA3AF' }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 11, fill: '#6B7280' }} axisLine={false} tickLine={false} width={40} />
                      <Tooltip contentStyle={{ backgroundColor: 'var(--app-surface-3)', color: 'var(--app-text)', border: 'none', borderRadius: '12px', fontSize: '12px' }}
                        formatter={(v: number) => [`€${v.toFixed(2)}`, '']} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                      <Bar dataKey="valor" fill={barColor} radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>

                <div className="bg-[#161616] rounded-2xl border border-[#222] p-5 overflow-x-auto">
                  <h3 className="text-sm font-medium text-gray-300 mb-4">Todas as categorias · {yearNum}</h3>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-gray-500">
                        <th className="text-left font-medium py-2 pr-4">Categoria</th>
                        {filled.map((m: any) => <th key={m.month} className="text-right font-medium py-2 px-2">{MESES[m.month - 1]}</th>)}
                        <th className="text-right font-medium py-2 pl-3">Total</th>
                        <th className="text-right font-medium py-2 pl-3">Média</th>
                      </tr>
                    </thead>
                    <tbody>
                      {yearData.categories.map((cat: string) => {
                        const catMonths = filled.filter((m: any) => m.by_category[cat] !== undefined);
                        const catAvg = catMonths.length ? (yearData.category_totals[cat] || 0) / catMonths.length : 0;
                        return (
                          <tr key={cat} onClick={() => setYearCat((c: string) => c === cat ? '' : cat)}
                            className={`cursor-pointer border-t border-[#1a1a1a] ${yearCat === cat ? 'bg-white/10' : 'hover:bg-white/5'}`}>
                            <td className="py-2.5 pr-4 whitespace-nowrap">{getCategoryInfo(cat).emoji} {getCategoryInfo(cat).label}</td>
                            {filled.map((m: any) => {
                              const has = m.by_category[cat] !== undefined;
                              const v = m.by_category[cat] || 0;
                              const cls = !has ? 'text-gray-700'
                                : catAvg > 0 && v > catAvg * 1.15 ? 'text-orange-300'
                                : catAvg > 0 && v < catAvg * 0.85 ? 'text-emerald-300'
                                : 'text-gray-300';
                              return (
                                <td key={m.month}
                                  onClick={e => { e.stopPropagation(); if (has) goToMonthCategory(m.month, cat); }}
                                  title={has ? `${MESES[m.month - 1]}: €${v.toFixed(2)} · média €${catAvg.toFixed(2)}` : ''}
                                  className={`text-right px-2 tabular-nums ${cls} ${has ? 'hover:text-white hover:bg-white/10 rounded cursor-pointer' : ''}`}>
                                  {has ? v.toFixed(0) : '·'}
                                </td>
                              );
                            })}
                            <td className="text-right pl-3 font-bold tabular-nums">{(yearData.category_totals[cat] || 0).toFixed(0)}</td>
                            <td className="text-right pl-3 text-gray-500 tabular-nums">{catAvg.toFixed(0)}</td>
                          </tr>
                        );
                      })}
                      <tr className="border-t border-[#333] text-gray-400 font-medium">
                        <td className="py-2.5 pr-4">Total</td>
                        {filled.map((m: any) => (
                          <td key={m.month}
                            onClick={() => goToMonthCategory(m.month, null)}
                            className="text-right px-2 tabular-nums hover:text-white hover:bg-white/10 rounded cursor-pointer">
                            {m.total ? m.total.toFixed(0) : '·'}
                          </td>
                        ))}
                        <td className="text-right pl-3 font-bold tabular-nums">{yearData.total.toFixed(0)}</td>
                        <td className="text-right pl-3 tabular-nums">{filled.length ? (yearData.total / filled.length).toFixed(0) : '·'}</td>
                      </tr>
                    </tbody>
                  </table>
                  <div className="flex items-center gap-3 mt-3 text-[10px] text-gray-600">
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-400" /> abaixo da média</span>
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-gray-400" /> na média</span>
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-orange-400" /> acima da média</span>
                  </div>
                </div>
              </>
            );
          })()}
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowModal(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-5 max-w-[92vw] w-[520px] max-h-[94dvh] overflow-y-auto border border-[#333]" onClick={e => e.stopPropagation()}>
            {/* Vertical como sempre, mas apertado para caber sem rolar: espaços
                de 10px, campos de 36px e as categorias mais baixas. */}
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-lg font-bold">{editingExpense ? 'Editar Gasto' : 'Novo Gasto'}</h3>
              <button onClick={() => setShowModal(false)} className="text-gray-500 hover:text-white"><X size={20} /></button>
            </div>

            <div className="space-y-2">
              {!editingExpense && <div>
                <label className={`flex items-center justify-center gap-2 px-4 py-2 rounded-xl border border-dashed cursor-pointer transition-all ${
                  aLerRecibo ? 'border-[#444] opacity-60' : 'border-[#444] hover:border-green-500'
                }`}>
                  {aLerRecibo ? <Loader2 size={15} className="text-green-400 animate-spin" /> : <Sparkles size={15} className="text-green-400" />}
                  <span className="text-sm text-gray-300">
                    {aLerRecibo ? 'a ler o recibo…' : 'Ler recibo (foto ou PDF)'}
                  </span>
                  <input type="file" className="hidden" accept="image/*,.pdf" disabled={aLerRecibo}
                    onChange={e => { const f = e.target.files?.[0]; if (f) lerRecibo(f); e.target.value = ''; }} />
                </label>
                {recibo && (
                  <p className="text-[11px] text-green-400/80 mt-1.5 flex items-center gap-1.5">
                    <Check size={11} /> {recibo.merchant} · fica anexado ao gravar
                    {recibo.confidence === 'baixa' && <span className="text-amber-400">· confere os valores</span>}
                    {recibo.source === 'regras' && <span className="text-amber-400">· lido sem IA</span>}
                  </p>
                )}
                {erroRecibo && <p className="text-[11px] text-red-400 mt-1.5">{erroRecibo}</p>}
              </div>}

              <input type="text" placeholder="Descrição..."
                value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-green-500"
                autoFocus />

              <div className="flex gap-3">
                <div className="flex-1">
                  <label className="text-xs text-gray-500 block mb-1">Valor (€)</label>
                  <input type="number" step="0.01" min="0"
                    value={form.amount || ''} onChange={e => setForm(f => ({ ...f, amount: parseFloat(e.target.value) || 0 }))}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm focus:outline-none focus:border-green-500" />
                </div>
                <div className="flex-1">
                  <label className="text-xs text-gray-500 block mb-1">Data</label>
                  <input type="date" value={form.date} onChange={e => setForm(f => ({ ...f, date: e.target.value }))}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm focus:outline-none focus:border-green-500" />
                </div>
                <div className="w-24">
                  <label className="text-xs text-gray-500 block mb-1">Hora</label>
                  <input type="time" value={form.time_of_day || ''}
                    onChange={e => setForm(f => ({ ...f, time_of_day: e.target.value || null }))}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-green-500" />
                </div>
              </div>

              <div>
                <label className="text-xs text-gray-500 block mb-1.5">Categoria</label>
                {/* cada botão estica: as linhas enchem a largura toda em vez de
                    deixarem um buraco à direita */}
                <div className="flex flex-wrap gap-1.5">
                  {categorias.map(cat => (
                    <button key={cat.value}
                      onClick={() => setForm(f => ({ ...f, category: cat.value }))}
                      className={`flex-auto px-2.5 py-1 rounded-lg text-xs font-medium whitespace-nowrap transition-all ${
                        form.category === cat.value
                          ? 'bg-green-600 text-white'
                          : 'bg-[#222] text-gray-400 hover:text-gray-200'
                      }`}>
                      {cat.emoji} {cat.label}
                    </button>
                  ))}
                  <button onClick={() => { setNovaCat(n => n ? null : { label: '', emoji: '🏷️' }); setErroCat(null); }}
                    className={`flex-auto px-2.5 py-1 rounded-lg text-xs font-medium whitespace-nowrap border border-dashed transition-all ${
                      novaCat ? 'border-green-500/60 text-green-300' : 'border-[#3a3a3a] text-gray-500 hover:text-gray-200'
                    }`}>
                    <Plus size={12} className="inline -mt-0.5" /> Nova
                  </button>
                </div>
                {novaCat && (
                  <div className="mt-2 bg-[#1b1b1b] border border-[#2a2a2a] rounded-xl p-2.5 space-y-2">
                    <div className="flex gap-2">
                      <input value={novaCat.emoji} onChange={e => setNovaCat(n => n && { ...n, emoji: e.target.value })}
                        maxLength={4} aria-label="emoji"
                        className="w-12 text-center bg-[#222] border border-[#333] rounded-lg px-1 py-1.5 text-sm focus:outline-none focus:border-green-500" />
                      <input value={novaCat.label} autoFocus placeholder="Nome da categoria"
                        onChange={e => setNovaCat(n => n && { ...n, label: e.target.value })}
                        onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); criarCategoria(); } if (e.key === 'Escape') setNovaCat(null); }}
                        className="flex-1 min-w-0 bg-[#222] border border-[#333] rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-green-500" />
                      <button onClick={criarCategoria} disabled={!novaCat.label.trim()}
                        className="px-3 py-1.5 bg-green-600 hover:bg-green-700 rounded-lg text-xs font-medium disabled:opacity-40">
                        Criar
                      </button>
                    </div>
                    {categorias.some(c => c.custom) && (
                      <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-gray-500">
                        as tuas:
                        {categorias.filter(c => c.custom).map(c => (
                          <span key={c.value} className="flex items-center gap-1 bg-[#222] rounded-md pl-2 pr-1 py-0.5 text-gray-300">
                            {c.emoji} {c.label}
                            <button onClick={() => apagarCategoria(c.value)} title="apagar (só se não tiver gastos)"
                              className="text-gray-500 hover:text-red-400"><X size={11} /></button>
                          </span>
                        ))}
                      </div>
                    )}
                    {erroCat && <p className="text-[11px] text-amber-300">{erroCat}</p>}
                  </div>
                )}
                {editingExpense?.bank_tx_id && form.category !== editingExpense.category && (
                  <label className="flex items-start gap-2 mt-2 text-[11px] text-gray-400 cursor-pointer">
                    <input type="checkbox" className="mt-0.5 accent-emerald-500"
                      checked={aplicarAosIguais} onChange={e => setAplicarAosIguais(e.target.checked)} />
                    <span>
                      Pôr também os outros movimentos de «{editingExpense.description}» em {catLabel(form.category || 'other')}, e os que vierem
                    </span>
                  </label>
                )}
              </div>

              {form.amount >= 0 && <>
              <label className="flex items-center gap-2.5 bg-[#1b1b1b] border border-[#2a2a2a] rounded-xl px-3 py-2 text-xs cursor-pointer"
                title="Conta no total do mês, mas fica fora da média por dia, da comparação com o mês passado, do orçamento e dos avisos de dia caro.">
                <input type="checkbox"
                  checked={!!form.extraordinary}
                  onChange={e => setForm(f => ({ ...f, extraordinary: e.target.checked }))} />
                <span>
                  <span className="text-gray-200">Compra extraordinária</span>
                  <span className="text-gray-500"> · não conta para a média</span>
                </span>
              </label>

              <div className="bg-[#1b1b1b] border border-[#2a2a2a] rounded-xl px-3 py-2 text-xs">
                <div className="flex items-center gap-2.5">
                  <label className="flex items-center gap-2.5 flex-1 cursor-pointer text-gray-200">
                    <input type="checkbox" checked={!!form.klarna_installments}
                      onChange={e => setForm(f => ({ ...f, klarna_installments: e.target.checked ? 3 : null }))} />
                    Pago com Klarna
                  </label>
                  {form.klarna_installments && (
                    <label className="flex items-center gap-1.5 text-gray-400">
                      em
                      <select value={form.klarna_installments}
                        onChange={e => setForm(f => ({ ...f, klarna_installments: +e.target.value }))}
                        className="bg-[#222] border border-[#333] rounded-lg px-2 py-0.5 text-gray-200 focus:outline-none">
                        {Array.from({ length: 11 }, (_, i) => i + 2).map(n => <option key={n} value={n}>{n}</option>)}
                      </select>
                      vezes
                    </label>
                  )}
                </div>
                {form.klarna_installments && form.amount > 0 && (
                  <p className="text-gray-500 mt-1 tabular-nums">
                    €{form.amount.toFixed(2)} por mês · {klarnaLinha()}
                  </p>
                )}
              </div>
              </>}

              {editingExpense && sugPorConta[editingExpense.id] && (() => {
                const sg = sugPorConta[editingExpense.id];
                return (
                  <div className="flex items-center gap-2 bg-teal-600/10 border border-teal-500/25 rounded-xl px-3 py-1.5 text-xs"
                    title={[...sg.incomes.map(i => `${i.description} · €${i.amount.toFixed(2)} · ${format(new Date(`${i.date}T00:00:00`), 'd MMM', { locale: pt })}`),
                      ...(sg.expenses.length > 1 ? ['contas: ' + sg.expenses.map(c => `${c.description} €${c.amount.toFixed(2)}`).join(' + ')] : [])].join('\n')}>
                    <HandCoins size={14} className="text-teal-300 shrink-0" />
                    <span className="flex-1 min-w-0 text-gray-200 tabular-nums">
                      {sg.incomes.length === 1 ? `${sg.incomes[0].description} devolveu` : `${sg.incomes.length} pessoas devolveram`}
                      {' '}€{sg.incomes.reduce((t, i) => t + i.amount, 0).toFixed(2)}{sg.expenses.length > 1 && ` por esta e mais ${sg.expenses.length - 1}`} → a tua parte <span className="text-teal-300 font-medium">€{sg.share_after.toFixed(2)}</span>
                    </span>
                    <button onClick={() => naoEReembolso(sg)} className="text-gray-500 hover:text-gray-300 shrink-0">não é</button>
                    <button onClick={() => descontarSugestao(sg)} disabled={aDescontar === sg.expenses[0].id}
                      className="px-2.5 py-1 bg-teal-600 hover:bg-teal-700 rounded-lg font-medium disabled:opacity-40 shrink-0">
                      Descontar
                    </button>
                  </div>
                );
              })()}

              {form.amount > 0 && !editingExpense?.reimburses_id && (
                <div className="bg-[#1b1b1b] border border-[#2a2a2a] rounded-xl px-3 py-2 text-xs">
                  <div className="flex flex-wrap items-center gap-2.5">
                    <label className="flex items-center gap-2.5 flex-1 cursor-pointer text-gray-200 whitespace-nowrap">
                      <input type="checkbox" checked={!!form.split_people || form.my_share != null}
                        onChange={e => setForm(f => ({ ...f, split_people: e.target.checked ? 3 : null, my_share: null }))} />
                      Paguei por mais pessoas
                    </label>
                    {(!!form.split_people || form.my_share != null) && (
                      <div className="flex items-center gap-1.5 text-gray-400">
                        <select value={form.my_share != null ? 'valor' : 'n'}
                          onChange={e => setForm(f => e.target.value === 'valor'
                            ? { ...f, split_people: null, my_share: +(f.amount / (f.split_people || 2)).toFixed(2) }
                            : { ...f, split_people: 2, my_share: null })}
                          className="bg-[#222] border border-[#333] rounded-lg px-2 py-0.5 text-gray-200 focus:outline-none">
                          <option value="n">por igual, por</option>
                          <option value="valor">a minha parte é</option>
                        </select>
                        {form.my_share != null ? (
                          <span className="flex items-center gap-1">€
                            <input type="number" step="0.01" min="0" value={form.my_share}
                              onChange={e => setForm(f => ({ ...f, my_share: e.target.value === '' ? 0 : +e.target.value }))}
                              className="w-20 bg-[#222] border border-[#333] rounded-lg px-2 py-0.5 text-gray-200 focus:outline-none" />
                          </span>
                        ) : (
                          <>
                            <select value={form.split_people || 2}
                              onChange={e => setForm(f => ({ ...f, split_people: +e.target.value }))}
                              className="bg-[#222] border border-[#333] rounded-lg px-2 py-0.5 text-gray-200 focus:outline-none">
                              {Array.from({ length: 9 }, (_, i) => i + 2).map(n => <option key={n} value={n}>{n}</option>)}
                            </select>
                            contigo
                          </>
                        )}
                      </div>
                    )}
                  </div>
                  {(form.split_people || form.my_share != null || (editingExpense?.reimbursed_total || 0) > 0) && (() => {
                    const conta = { amount: form.amount, split_people: form.split_people, my_share: form.my_share, reimbursed_total: editingExpense?.reimbursed_total || 0 };
                    const falta = faltaReceber(conta);
                    return (
                      <p className="text-gray-500 mt-1 tabular-nums">
                        a tua parte €{parteDele(conta).toFixed(2)}
                        {conta.reimbursed_total > 0 && ` · já devolveram €${conta.reimbursed_total.toFixed(2)} (${editingExpense?.reimbursed_count} ${editingExpense?.reimbursed_count === 1 ? 'pessoa' : 'pessoas'})`}
                        {falta > 0.01 && <span className="text-amber-300/90"> · faltam €{falta.toFixed(2)}</span>}
                      </p>
                    );
                  })()}
                </div>
              )}

              {editingExpense && editingExpense.amount < 0 && !eSalarioDe(editingExpense) && (
                <div className="bg-[#1b1b1b] border border-[#2a2a2a] rounded-xl px-3 py-2 text-xs">
                  {editingExpense.reimburses_id ? (
                    <div className="flex items-center gap-2">
                      <span className="flex-1 text-gray-200">
                        Desconta em <span className="font-medium text-teal-300">{editingExpense.reimburses_description}</span> — conta como a parte de alguém, não como entrada.
                      </span>
                      <button onClick={desligarReembolso} className="text-gray-400 hover:text-red-300 underline shrink-0">desligar</button>
                    </div>
                  ) : (
                    <>
                      <p className="text-gray-200 mb-1.5">
                        {sugPorEntrada[editingExpense.id] ? (<>
                          <HandCoins size={13} className="inline -mt-0.5 mr-1 text-teal-300" />
                          Parece a parte de alguém em <span className="font-medium text-teal-300">{sugPorEntrada[editingExpense.id].expenses.map(c => c.description).join(' + ')}</span>
                          {' '}<button onClick={() => naoEReembolso({ ...sugPorEntrada[editingExpense.id], incomes: sugPorEntrada[editingExpense.id].incomes.filter(i => i.id === editingExpense.id) }).then(() => setContasEscolhidas([]))}
                            className="text-gray-500 hover:text-gray-300">· não é</button>
                        </>) : 'Foi a parte de alguém numa conta que pagaste?'}
                      </p>
                      {/* Uma ou várias contas: os 75€ do Rafael pelos levantamentos de
                          70€ e 30€ repartem-se pelas duas. */}
                      {contasParaDescontar === null ? (
                        <p className="text-gray-500">a procurar contas…</p>
                      ) : (
                        <div className="max-h-32 overflow-y-auto rounded-lg border border-[#2a2a2a] divide-y divide-[#222]">
                          {contasParaDescontar.map(c => {
                            const on = contasEscolhidas.includes(c.id);
                            return (
                              <label key={c.id} className={`flex items-center gap-2 px-2 py-1.5 cursor-pointer ${on ? 'bg-teal-500/10' : 'hover:bg-white/5'}`}>
                                <input type="checkbox" checked={on} className="accent-teal-500"
                                  onChange={() => setContasEscolhidas(l => on ? l.filter(x => x !== c.id) : [...l, c.id])} />
                                <span className="flex-1 min-w-0 truncate text-gray-200">{c.description}</span>
                                {c.parts ? <span className="text-teal-300/80 shrink-0">÷{c.parts}</span> : null}
                                <span className="text-gray-500 tabular-nums shrink-0">{format(new Date(`${c.date}T00:00:00`), 'd MMM', { locale: pt })}</span>
                                <span className="text-gray-300 tabular-nums shrink-0 w-16 text-right">€{c.amount.toFixed(2)}</span>
                              </label>
                            );
                          })}
                        </div>
                      )}
                      {(() => {
                        const valor = -editingExpense.amount;
                        const escolhidas = (contasParaDescontar || []).filter(c => contasEscolhidas.includes(c.id));
                        const total = escolhidas.reduce((t, c) => t + c.amount, 0);
                        const porPagar = escolhidas.reduce((t, c) => t + c.amount - c.reimbursed, 0);
                        const naoCabe = escolhidas.length > 0 && valor > porPagar + 0.01;
                        return (
                          <div className="flex items-center gap-2 mt-1.5">
                            <span className={`flex-1 tabular-nums ${naoCabe ? 'text-amber-300' : 'text-gray-500'}`}>
                              {escolhidas.length === 0 ? 'escolhe uma ou mais contas'
                                : naoCabe ? `€${valor.toFixed(2)} não cabem: só há €${porPagar.toFixed(2)} por pagar`
                                : `a tua parte fica €${(porPagar - valor).toFixed(2)}${escolhidas.length > 1 ? ` de €${total.toFixed(2)}` : ''}`}
                            </span>
                            <button onClick={ligarReembolso} disabled={escolhidas.length === 0 || naoCabe}
                              className="px-3 py-1.5 bg-teal-600 hover:bg-teal-700 rounded-lg font-medium disabled:opacity-40 shrink-0">
                              Descontar
                            </button>
                          </div>
                        );
                      })()}
                    </>
                  )}
                  {erroReemb && <p className="text-amber-300 mt-1.5">{erroReemb}</p>}
                </div>
              )}

              <textarea placeholder="Notas (opcional)"
                value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm focus:outline-none focus:border-green-500 resize-none"
                rows={2} />

              {editingExpense && editingExpense.amount > 0 && (
                <div>
                  <label className="text-xs text-gray-500 block mb-1">Recibo / Foto</label>
                  {editingExpense.receipt_image ? (
                    <div className="flex items-center gap-2 text-xs text-green-400">
                      <Receipt size={14} /> Recibo enviado
                    </div>
                  ) : (
                    <label className="flex items-center gap-2 px-4 py-1.5 bg-[#222] border border-dashed border-[#444] rounded-xl cursor-pointer hover:border-green-500 transition-all">
                      <Upload size={15} className="text-gray-400" />
                      <span className="text-sm text-gray-400">Carregar recibo</span>
                      <input type="file" className="hidden" accept="image/*,.pdf"
                        onChange={e => {
                          const file = e.target.files?.[0];
                          if (file) handleUploadReceipt(editingExpense.id, file);
                        }} />
                    </label>
                  )}
                </div>
              )}
            </div>

            <div className="flex gap-3 mt-3">
              {editingExpense && (
                <button onClick={handleDelete}
                  className="px-4 py-2 bg-red-600/20 text-red-400 hover:bg-red-600/30 rounded-xl text-sm font-medium">
                  Apagar
                </button>
              )}
              <div className="flex-1" />
              <button onClick={() => setShowModal(false)}
                className="px-4 py-2 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm">Cancelar</button>
              <button onClick={handleSave}
                className="px-6 py-2 bg-green-600 hover:bg-green-700 rounded-xl text-sm font-medium">
                {editingExpense ? 'Guardar' : 'Adicionar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Subscription Modal */}
      {showSubModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => { setShowSubModal(false); setEditingSub(null); }}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 max-w-[90vw] w-[420px] border border-[#333]" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-bold">{editingSub ? 'Editar Subscrição' : 'Nova Subscrição'}</h3>
              <button onClick={() => { setShowSubModal(false); setEditingSub(null); }} className="text-gray-500 hover:text-white"><X size={20} /></button>
            </div>
            <div className="space-y-4">
              <input type="text" placeholder="Nome (ex: Netflix, Spotify...)"
                value={subForm.name} onChange={e => setSubForm(f => ({ ...f, name: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-purple-500" autoFocus />
              <div className="flex gap-3">
                <div className="flex-1">
                  <label className="text-xs text-gray-500 block mb-1">Valor (€)</label>
                  <input type="number" step="0.01"
                    value={subForm.amount || ''} onChange={e => setSubForm(f => ({ ...f, amount: parseFloat(e.target.value) || 0 }))}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm focus:outline-none focus:border-purple-500" />
                </div>
                <div className="flex-1">
                  <label className="text-xs text-gray-500 block mb-1">Ciclo</label>
                  <select value={subForm.billing_cycle} onChange={e => setSubForm(f => ({ ...f, billing_cycle: e.target.value }))}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm focus:outline-none text-white">
                    <option value="monthly">Mensal</option>
                    <option value="yearly">Anual</option>
                    <option value="weekly">Semanal</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">Próxima renovação</label>
                <input type="date" value={subForm.next_renewal} onChange={e => setSubForm(f => ({ ...f, next_renewal: e.target.value }))}
                  className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm focus:outline-none focus:border-purple-500" />
              </div>
              <textarea placeholder="Notas (opcional)"
                value={subForm.notes} onChange={e => setSubForm(f => ({ ...f, notes: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-purple-500 resize-none" rows={2} />
            </div>
            <div className="flex gap-3 mt-6">
              {editingSub && (
                <button onClick={() => deleteSubscription(editingSub.id)}
                  className="px-4 py-2.5 bg-red-600/20 text-red-400 hover:bg-red-600/30 rounded-xl text-sm font-medium">
                  Apagar
                </button>
              )}
              <div className="flex-1" />
              <button onClick={() => { setShowSubModal(false); setEditingSub(null); }}
                className="px-4 py-2.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm">Cancelar</button>
              <button onClick={saveSubscription}
                className="px-6 py-2.5 bg-purple-600 hover:bg-purple-700 rounded-xl text-sm font-medium">
                {editingSub ? 'Guardar' : 'Adicionar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Wishlist Modal */}
      {showWishModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => { setShowWishModal(false); setEditingWish(null); }}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 max-w-[90vw] w-[420px] border border-[#333]" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-bold flex items-center gap-2"><Gift size={18} className="text-pink-400" /> {editingWish ? 'Editar desejo' : 'Novo desejo'}</h3>
              <button onClick={() => { setShowWishModal(false); setEditingWish(null); }} className="text-gray-500 hover:text-white"><X size={20} /></button>
            </div>
            <div className="space-y-4">
              <input type="text" placeholder="O que queres? (ex: Pulseira Garmin)"
                value={wishForm.name} onChange={e => setWishForm(f => ({ ...f, name: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-pink-500" autoFocus />
              <div className="flex gap-3">
                <div className="flex-1">
                  <label className="text-xs text-gray-500 block mb-1">Preço (€)</label>
                  <input type="number" step="0.01"
                    value={wishForm.price || ''} onChange={e => setWishForm(f => ({ ...f, price: parseFloat(e.target.value) || 0 }))}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm focus:outline-none focus:border-pink-500" />
                </div>
                <div className="flex-1">
                  <label className="text-xs text-gray-500 block mb-1">Já juntei (€)</label>
                  <input type="number" step="0.01"
                    value={wishForm.saved_amount || ''} onChange={e => setWishForm(f => ({ ...f, saved_amount: parseFloat(e.target.value) || 0 }))}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm focus:outline-none focus:border-pink-500" />
                </div>
              </div>
              <div className="flex gap-3">
                <div className="flex-1">
                  <label className="text-xs text-gray-500 block mb-1">Prioridade</label>
                  <select value={wishForm.priority} onChange={e => setWishForm(f => ({ ...f, priority: e.target.value }))}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm focus:outline-none text-white">
                    <option value="high">Alta</option>
                    <option value="medium">Média</option>
                    <option value="low">Baixa</option>
                  </select>
                </div>
                <div className="flex-1">
                  <label className="text-xs text-gray-500 block mb-1">Categoria</label>
                  <select value={wishForm.category} onChange={e => setWishForm(f => ({ ...f, category: e.target.value }))}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm focus:outline-none text-white">
                    {categorias.map(c => (
                      <option key={c.value} value={c.value}>{c.emoji} {c.label}</option>
                    ))}
                  </select>
                </div>
              </div>
              <input type="url" placeholder="Link do produto (opcional)"
                value={wishForm.url} onChange={e => setWishForm(f => ({ ...f, url: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm focus:outline-none focus:border-pink-500" />
              <textarea placeholder="Notas (opcional)"
                value={wishForm.notes} onChange={e => setWishForm(f => ({ ...f, notes: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-pink-500 resize-none" rows={2} />
            </div>
            <div className="flex gap-3 mt-6">
              {editingWish && (
                <button onClick={() => deleteWish(editingWish.id)}
                  className="px-4 py-2.5 bg-red-600/20 text-red-400 hover:bg-red-600/30 rounded-xl text-sm font-medium">Apagar</button>
              )}
              <div className="flex-1" />
              <button onClick={() => { setShowWishModal(false); setEditingWish(null); }}
                className="px-4 py-2.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm">Cancelar</button>
              <button onClick={saveWish}
                className="px-6 py-2.5 bg-pink-600 hover:bg-pink-700 rounded-xl text-sm font-medium">
                {editingWish ? 'Guardar' : 'Adicionar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Salary Bucket Modal */}
      {showBucketModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={() => { setShowBucketModal(false); setEditingBucket(null); }}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 max-w-[90vw] w-[460px] border border-[#333] max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-bold">{editingBucket ? 'Editar Grupo' : 'Novo Grupo'}</h3>
              <button onClick={() => { setShowBucketModal(false); setEditingBucket(null); }} className="text-gray-500 hover:text-white"><X size={20} /></button>
            </div>
            <div className="space-y-4">
              <input type="text" placeholder="Nome (ex: Despesas, Pessoal...)" value={bucketForm.name}
                onChange={e => setBucketForm(f => ({ ...f, name: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-green-500" autoFocus />
              <div className="flex flex-wrap gap-3">
                <div className="flex-1">
                  <label className="text-xs text-gray-500 block mb-1">% do salário</label>
                  <input type="number" step="0.1" min="0" max="100" value={bucketForm.percentage || ''}
                    onChange={e => setBucketForm(f => ({ ...f, percentage: parseFloat(e.target.value) || 0 }))}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm focus:outline-none focus:border-green-500" />
                </div>
                {salaryPlan?.salary > 0 && (
                  <div className="flex-1">
                    <label className="text-xs text-gray-500 block mb-1">€ por mês</label>
                    <input type="number" step="1" min="0"
                      value={bucketForm.percentage ? Math.round(salaryPlan.salary * bucketForm.percentage / 100) : ''}
                      onChange={e => {
                        const euros = parseFloat(e.target.value) || 0;
                        setBucketForm(f => ({ ...f, percentage: Math.round(euros / salaryPlan.salary * 10000) / 100 }));
                      }}
                      className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm focus:outline-none focus:border-green-500" />
                  </div>
                )}
                <div className="flex-1">
                  <label className="text-xs text-gray-500 block mb-1">Tipo</label>
                  <div className="flex gap-1 bg-[#222] border border-[#333] rounded-xl p-1">
                    <button onClick={() => setBucketForm(f => ({ ...f, kind: 'spend' }))}
                      className={`flex-1 px-2 py-1.5 rounded-lg text-xs font-medium ${bucketForm.kind === 'spend' ? 'bg-red-600/30 text-red-300' : 'text-gray-500'}`}>Gasto</button>
                    <button onClick={() => setBucketForm(f => ({ ...f, kind: 'save' }))}
                      className={`flex-1 px-2 py-1.5 rounded-lg text-xs font-medium ${bucketForm.kind === 'save' ? 'bg-green-600/30 text-green-300' : 'text-gray-500'}`}>Poupar</button>
                  </div>
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">Cor</label>
                <div className="flex flex-wrap gap-2">
                  {['#EF4444', '#F59E0B', '#10B981', '#3B82F6', '#8B5CF6', '#EC4899', '#14B8A6', '#6B7280'].map(c => (
                    <button key={c} onClick={() => setBucketForm(f => ({ ...f, color: c }))}
                      className={`w-7 h-7 rounded-full transition-all ${bucketForm.color === c ? 'ring-2 ring-white ring-offset-2 ring-offset-[#1a1a1a]' : ''}`}
                      style={{ backgroundColor: c }} />
                  ))}
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-2">Categorias que este grupo agrega</label>
                <div className="flex flex-wrap gap-2">
                  {Array.from(new Set([...categorias.map(c => c.value), ...bucketForm.categories])).map(catVal => {
                    const info = getCategoryInfo(catVal);
                    const on = bucketForm.categories.includes(catVal);
                    return (
                      <button key={catVal}
                        onClick={() => setBucketForm(f => ({ ...f, categories: on ? f.categories.filter(x => x !== catVal) : [...f.categories, catVal] }))}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${on ? 'bg-green-600 text-white' : 'bg-[#222] text-gray-400 hover:text-gray-200'}`}>
                        {info.emoji} {info.label}
                      </button>
                    );
                  })}
                </div>
                <div className="flex gap-2 mt-2">
                  <input type="text" value={newBucketCat} onChange={e => setNewBucketCat(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') {
                        const v = newBucketCat.trim().toLowerCase();
                        if (v) setBucketForm(f => ({ ...f, categories: Array.from(new Set([...f.categories, v])) }));
                        setNewBucketCat('');
                      }
                    }}
                    placeholder="Adicionar outra categoria…"
                    className="flex-1 bg-[#222] border border-[#333] rounded-lg px-3 py-1.5 text-xs text-gray-300 focus:outline-none focus:border-green-500" />
                  <button onClick={() => {
                    const v = newBucketCat.trim().toLowerCase();
                    if (v) setBucketForm(f => ({ ...f, categories: Array.from(new Set([...f.categories, v])) }));
                    setNewBucketCat('');
                  }} className="px-3 py-1.5 bg-[#222] hover:bg-[#2a2a2a] rounded-lg text-xs text-gray-300">+ Adicionar</button>
                </div>
              </div>
            </div>
            <div className="flex gap-3 mt-6">
              {editingBucket && (
                <button onClick={() => deleteSalaryBucket(editingBucket.id)}
                  className="px-4 py-2.5 bg-red-600/20 text-red-400 hover:bg-red-600/30 rounded-xl text-sm font-medium">Apagar</button>
              )}
              <div className="flex-1" />
              <button onClick={() => { setShowBucketModal(false); setEditingBucket(null); }}
                className="px-4 py-2.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm">Cancelar</button>
              <button onClick={saveBucket}
                className="px-6 py-2.5 bg-green-600 hover:bg-green-700 rounded-xl text-sm font-medium">{editingBucket ? 'Guardar' : 'Adicionar'}</button>
            </div>
          </div>
        </div>
      )}

      {aLigar && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={() => setALigar(null)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-5 max-w-[90vw] w-[520px] border border-[#333] max-h-[85vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-base font-bold truncate">Qual foi a compra de “{aLigar.name}”?</h3>
              <button onClick={() => setALigar(null)} className="text-gray-500 hover:text-white"><X size={18} /></button>
            </div>
            <p className="text-[11px] text-gray-500 mb-3">
              Escolhe a transação que já está na conta. Com a Klarna, escolhe uma das prestações.
            </p>
            <div className="relative mb-3">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input value={procuraCand} onChange={e => setProcuraCand(e.target.value)} autoFocus
                placeholder="Procurar pela descrição (ex: klarna, amazon)…"
                className="w-full bg-[#222] border border-[#333] rounded-xl pl-8 pr-3 py-2 text-sm focus:outline-none focus:border-pink-500" />
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto divide-y divide-[#222]">
              {candidatos === null ? (
                <p className="py-6 text-center text-xs text-gray-500">a procurar…</p>
              ) : candidatos.length === 0 ? (
                <p className="py-6 text-center text-xs text-gray-500">Nenhuma transação encontrada.</p>
              ) : candidatos.map(c => (
                <button key={c.id} onClick={() => ligaCompra(c.id)}
                  className="w-full flex items-center gap-3 py-2.5 px-2 text-left hover:bg-white/5 rounded-lg">
                  <span className="text-base shrink-0">{getCategoryInfo(c.category).emoji}</span>
                  <span className="flex-1 min-w-0">
                    <span className="block text-sm truncate">{c.description}</span>
                    <span className="block text-[10px] text-gray-500">
                      {format(new Date(`${c.date}T00:00:00`), 'd MMM yyyy', { locale: pt })}
                      {c.likely && <span className="text-green-400"> · parece esta</span>}
                    </span>
                  </span>
                  <span className="text-right shrink-0">
                    <span className="block text-sm font-medium">€{c.amount.toFixed(2)}</span>
                    {c.klarna_installments && (
                      <span className="block text-[10px] text-pink-400">Klarna × {c.klarna_installments} · €{(c.amount * c.klarna_installments).toFixed(0)}</span>
                    )}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Import Result Toast */}
      {importResult && (
        <div className="fixed bottom-6 right-6 bg-[#1a1a1a] border border-[#333] rounded-2xl p-4 shadow-xl z-50 max-w-sm">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-bold flex items-center gap-2">
              <Sparkles size={16} className="text-purple-400" /> Resultado
            </h4>
            <button onClick={() => setImportResult(null)} className="text-gray-500 hover:text-white"><X size={16} /></button>
          </div>
          <p className="text-xs text-gray-400">
            {importResult.total_parsed != null && <span className="text-gray-500">{importResult.total_parsed} transações encontradas · </span>}
            {importResult.imported > 0 && <span className="text-green-400">{importResult.imported} importado{importResult.imported !== 1 ? 's' : ''}</span>}
            {importResult.imported > 0 && importResult.skipped > 0 && ' · '}
            {importResult.skipped > 0 && <span className="text-yellow-400">{importResult.skipped} ignorado{importResult.skipped !== 1 ? 's' : ''}</span>}
          </p>
          {importResult.errors?.length > 0 && (
            <p className="text-xs text-red-400 mt-1">{importResult.errors[0]}</p>
          )}
        </div>
      )}
    </div>
  );
}
