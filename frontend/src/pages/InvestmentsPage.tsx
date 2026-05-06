import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { TrendingUp, TrendingDown, RefreshCw, FileText, FileSpreadsheet, ChevronLeft, ChevronRight, ChevronDown, Coins, Pencil, Check, X, Camera, Trophy, BarChart3, Plus, Trash2, AlertTriangle, Lightbulb, Target, Search, Loader, PieChart, Euro, Calendar, Newspaper, Sparkles, ExternalLink } from 'lucide-react';
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, ReferenceLine } from 'recharts';
import { investmentsApi } from '../api';

interface Position {
  id: number;
  instrument: string;
  isin: string;
  currency: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  current_value_eur: number;
  return_eur: number;
  fx_rate: number;
  source: string;
  statement_date: string | null;
}

interface Trade {
  id: number;
  execution_time: string;
  instrument: string;
  isin: string;
  currency: string;
  direction: string;
  quantity: number;
  execution_price: number;
  value: number;
  value_eur: number;
  fx_rate: number;
  fx_fee: number;
  source: string;
}

interface Transaction {
  id: number;
  time: string;
  type: string;
  currency: string;
  amount: number;
  source: string;
}

interface Summary {
  total_value: number;
  total_invested: number;
  total_return: number;
  total_return_pct: number;
  total_deposits: number;
  total_withdrawals: number;
  positions_count: number;
  latest_statement: string | null;
  account_value: number;
}

type Tab = 'overview' | 'trades' | 'transactions' | 'stats' | 'planner' | 'signals';
type SourceFilter = 'all' | 'finst' | 'trading212';

export default function InvestmentsPage() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [tab, setTab] = useState<Tab>('overview');
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<any>(null);
  const t212Ref = useRef<HTMLInputElement>(null);
  const finstRef = useRef<HTMLInputElement>(null);
  const screenshotRef = useRef<HTMLInputElement>(null);
  const [filterMonth, setFilterMonth] = useState<string>('all');
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [refreshingCrypto, setRefreshingCrypto] = useState(false);
  const [cryptoDropdownOpen, setCryptoDropdownOpen] = useState(false);
  const cryptoDropdownRef = useRef<HTMLDivElement>(null);
  const [cryptoImportMonth, setCryptoImportMonth] = useState<string>(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  });

  useEffect(() => { loadData(); }, []);

  // Close crypto dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (cryptoDropdownRef.current && !cryptoDropdownRef.current.contains(e.target as Node)) {
        setCryptoDropdownOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  // ── Source filtering ────────────────────────────────────────────
  const filteredPositionsBySource = useMemo(() => {
    if (sourceFilter === 'all') return positions;
    return positions.filter(p => p.source === sourceFilter);
  }, [positions, sourceFilter]);

  const filteredTradesBySource = useMemo(() => {
    if (sourceFilter === 'all') return trades;
    return trades.filter(t => t.source === sourceFilter);
  }, [trades, sourceFilter]);

  const filteredTransactionsBySource = useMemo(() => {
    if (sourceFilter === 'all') return transactions;
    return transactions.filter(t => t.source === sourceFilter);
  }, [transactions, sourceFilter]);

  // ── Month filtering (applied after source) ─────────────────────
  const availableMonths = useMemo(() => {
    const months = new Set<string>();
    filteredPositionsBySource.forEach(p => {
      if (p.statement_date) months.add(p.statement_date);
    });
    filteredTradesBySource.forEach(t => {
      const d = new Date(t.execution_time);
      months.add(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
    });
    filteredTransactionsBySource.forEach(t => {
      const d = new Date(t.time);
      months.add(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
    });
    return ['all', ...Array.from(months).sort().reverse()];
  }, [filteredPositionsBySource, filteredTradesBySource, filteredTransactionsBySource]);

  // Filter positions by month: show snapshot for selected month, or latest per instrument for "all"
  const filteredPositions = useMemo(() => {
    if (filterMonth === 'all') {
      // Show latest snapshot per instrument (highest statement_date), plus Finst (no date)
      const latest = new Map<string, Position>();
      for (const p of filteredPositionsBySource) {
        if (!p.statement_date) {
          // Finst positions: always show
          latest.set(`finst:${p.instrument}`, p);
        } else {
          const key = `${p.source}:${p.instrument}`;
          const existing = latest.get(key);
          if (!existing || !existing.statement_date || p.statement_date > existing.statement_date) {
            latest.set(key, p);
          }
        }
      }
      return Array.from(latest.values());
    }
    // Show positions from this month's snapshot + Finst (always visible)
    return filteredPositionsBySource.filter(p =>
      !p.statement_date || p.statement_date === filterMonth
    );
  }, [filteredPositionsBySource, filterMonth]);

  const filteredTrades = useMemo(() => {
    if (filterMonth === 'all') return filteredTradesBySource;
    return filteredTradesBySource.filter(t => {
      const d = new Date(t.execution_time);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}` === filterMonth;
    });
  }, [filteredTradesBySource, filterMonth]);

  const filteredTransactions = useMemo(() => {
    if (filterMonth === 'all') return filteredTransactionsBySource;
    return filteredTransactionsBySource.filter(t => {
      const d = new Date(t.time);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}` === filterMonth;
    });
  }, [filteredTransactionsBySource, filterMonth]);

  // Reset month filter when it becomes invalid after source change
  useEffect(() => {
    if (filterMonth !== 'all' && !availableMonths.includes(filterMonth)) {
      setFilterMonth('all');
    }
  }, [availableMonths, filterMonth]);

  // ── Best returns (from latest positions only) ─────────────────
  const bestReturns = useMemo(() => {
    return [...filteredPositions]
      .filter(p => p.avg_price > 0 && p.current_price > 0)
      .map(p => ({
        ...p,
        returnPct: ((p.current_price - p.avg_price) / p.avg_price) * 100,
      }))
      .sort((a, b) => b.returnPct - a.returnPct)
      .slice(0, 5);
  }, [filteredPositions]);

  async function loadData() {
    const [pos, trd, txn, sum] = await Promise.all([
      investmentsApi.positions(),
      investmentsApi.trades(),
      investmentsApi.transactions(),
      investmentsApi.summary(),
    ]);
    setPositions(pos);
    setTrades(trd);
    setTransactions(txn);
    setSummary(sum);
  }

  async function handleImport(file: File, type: 'pdf' | 'finst-csv') {
    setImporting(true);
    setImportResult(null);
    try {
      const result = type === 'pdf'
        ? await investmentsApi.importPDF(file)
        : await investmentsApi.importFinstCSV(file);
      setImportResult(result);
      await loadData();
    } catch (e: any) {
      setImportResult({ error: e.message });
    } finally {
      setImporting(false);
      if (t212Ref.current) t212Ref.current.value = '';
      if (finstRef.current) finstRef.current.value = '';
    }
  }

  async function handleRefreshCrypto() {
    setRefreshingCrypto(true);
    try {
      await investmentsApi.refreshCryptoPrices();
      await loadData();
    } catch (e: any) {
      setImportResult({ error: e.message });
    } finally {
      setRefreshingCrypto(false);
    }
  }

  async function handleScreenshot(file: File) {
    setImporting(true);
    setImportResult(null);
    try {
      const result = await investmentsApi.importFinstScreenshot(file, cryptoImportMonth);
      setImportResult({
        screenshot: true,
        updated: result.updated,
        count: result.ocr_cryptos_found,
        month: result.month,
      });
      await loadData();
    } catch (e: any) {
      setImportResult({ error: e.message });
    } finally {
      setImporting(false);
      if (screenshotRef.current) screenshotRef.current.value = '';
    }
  }

  const pl = (v: number) =>
    v >= 0 ? 'text-green-400' : 'text-red-400';

  const eur = (v: number) =>
    new Intl.NumberFormat('pt-PT', { style: 'currency', currency: 'EUR' }).format(v);

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">Investimentos</h1>
          <p className="text-sm text-gray-500 mt-1">
            {summary?.latest_statement
              ? `Último extrato: ${summary.latest_statement}`
              : 'Importa dados para começar'}
          </p>
        </div>
        <div className="flex gap-2 items-center">
          <button
            onClick={() => loadData()}
            className="flex items-center gap-2 px-3 py-2 bg-[#1a1a1a] border border-[#333] rounded-xl text-gray-300 hover:bg-[#222] transition-colors"
            title="Atualizar dados"
          >
            <RefreshCw size={16} />
          </button>

          {/* Crypto dropdown button */}
          <div className="relative" ref={cryptoDropdownRef}>
            <button
              onClick={() => setCryptoDropdownOpen(o => !o)}
              disabled={importing || refreshingCrypto}
              className="flex items-center gap-2 px-4 py-2 bg-teal-600 hover:bg-teal-700 text-white rounded-xl transition-colors disabled:opacity-50 font-medium"
            >
              <Coins size={16} />
              Crypto
              <ChevronDown size={14} className={`transition-transform ${cryptoDropdownOpen ? 'rotate-180' : ''}`} />
            </button>
            {cryptoDropdownOpen && (
              <div className="absolute right-0 mt-2 w-64 bg-[#1a1a1a] border border-[#333] rounded-xl shadow-xl z-50 overflow-hidden">
                <div className="px-4 pt-3 pb-2 border-b border-[#222]">
                  <label className="text-[11px] text-gray-500 block mb-1">Mês do snapshot</label>
                  <input
                    type="month"
                    value={cryptoImportMonth}
                    onChange={e => setCryptoImportMonth(e.target.value)}
                    className="w-full bg-[#0f0f0f] border border-[#333] rounded-lg px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-teal-500"
                  />
                </div>
                <input type="file" ref={finstRef} accept=".csv" className="hidden" onChange={e => { e.target.files?.[0] && handleImport(e.target.files[0], 'finst-csv'); setCryptoDropdownOpen(false); }} />
                <button
                  onClick={() => { finstRef.current?.click(); }}
                  className="w-full flex items-center gap-3 px-4 py-3 text-sm text-gray-300 hover:bg-white/5 transition-colors"
                >
                  <FileSpreadsheet size={16} className="text-teal-400" />
                  Importar CSV (Finst)
                </button>
                <input type="file" ref={screenshotRef} accept="image/*" className="hidden" onChange={e => { e.target.files?.[0] && handleScreenshot(e.target.files[0]); setCryptoDropdownOpen(false); }} />
                <button
                  onClick={() => { screenshotRef.current?.click(); }}
                  disabled={!/^\d{4}-\d{2}$/.test(cryptoImportMonth)}
                  className="w-full flex items-center gap-3 px-4 py-3 text-sm text-gray-300 hover:bg-white/5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  title={!/^\d{4}-\d{2}$/.test(cryptoImportMonth) ? 'Escolhe um mês primeiro' : 'Screenshot do snapshot mensal'}
                >
                  <Camera size={16} className="text-purple-400" />
                  Screenshot (mês selecionado)
                </button>
                <div className="border-t border-[#333]" />
                <button
                  onClick={() => { handleRefreshCrypto(); setCryptoDropdownOpen(false); }}
                  disabled={refreshingCrypto}
                  className="w-full flex items-center gap-3 px-4 py-3 text-sm text-amber-400 hover:bg-white/5 transition-colors disabled:opacity-50"
                >
                  <RefreshCw size={16} />
                  {refreshingCrypto ? 'A atualizar...' : 'Atualizar Preços'}
                </button>
              </div>
            )}
          </div>

          {/* Trading 212 button */}
          <input type="file" ref={t212Ref} accept=".pdf" className="hidden" onChange={e => e.target.files?.[0] && handleImport(e.target.files[0], 'pdf')} />
          <button
            onClick={() => t212Ref.current?.click()}
            disabled={importing}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl transition-colors disabled:opacity-50 font-medium"
          >
            <FileText size={16} />
            {importing ? 'A importar...' : 'Trading 212'}
          </button>
        </div>
      </div>

      {/* Import result toast */}
      {importResult && (
        <div className={`p-4 rounded-xl border ${importResult.error ? 'bg-red-500/10 border-red-500/30 text-red-400' : 'bg-green-500/10 border-green-500/30 text-green-400'}`}>
          {importResult.error
            ? `Erro: ${importResult.error}`
            : importResult.screenshot
              ? `Screenshot ${importResult.month || ''} — ${importResult.count} crypto${importResult.count > 1 ? 's' : ''}: ${importResult.updated?.map((u: any) => `${u.instrument} @ ${u.current_price.toLocaleString('pt-PT', { minimumFractionDigits: 2 })}€`).join(', ')}`
              : `Importado com sucesso — ${importResult.positions_updated} posições, ${importResult.trades_added} trades, ${importResult.transactions_added} transações`}
          <button onClick={() => setImportResult(null)} className="ml-3 text-xs underline">fechar</button>
        </div>
      )}

      {/* Source Filter Pills */}
      <div className="flex items-center gap-2">
        {([
          ['all', 'Todos', undefined],
          ['finst', 'Crypto', 'teal'],
          ['trading212', 'Trading 212', 'blue'],
        ] as [SourceFilter, string, string | undefined][]).map(([key, label, color]) => {
          const isActive = sourceFilter === key;
          const count = key === 'all' ? positions.length : positions.filter(p => p.source === key).length;
          return (
            <button
              key={key}
              onClick={() => setSourceFilter(key)}
              className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
                isActive
                  ? color === 'teal' ? 'bg-teal-500/20 text-teal-400 border border-teal-500/40'
                    : color === 'blue' ? 'bg-blue-500/20 text-blue-400 border border-blue-500/40'
                    : 'bg-white/10 text-white border border-white/20'
                  : 'bg-[#1a1a1a] text-gray-500 border border-[#333] hover:text-gray-300 hover:border-[#444]'
              }`}
            >
              {label}
              {count > 0 && <span className="ml-1.5 text-xs opacity-70">({count})</span>}
            </button>
          );
        })}
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <SummaryCard label="Valor Total" value={eur(filteredPositions.reduce((s, p) => s + (p.current_value_eur ?? 0), 0))} />
          <SummaryCard
            label="Retorno"
            value={eur(filteredPositions.reduce((s, p) => s + (p.return_eur ?? 0), 0))}
            sub={(() => {
              const totalInv = filteredPositions.reduce((s, p) => s + (p.quantity * p.avg_price / (p.fx_rate || 1)), 0);
              const totalRet = filteredPositions.reduce((s, p) => s + (p.return_eur ?? 0), 0);
              const pct = totalInv > 0 ? (totalRet / totalInv) * 100 : 0;
              return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
            })()}
            color={filteredPositions.reduce((s, p) => s + (p.return_eur ?? 0), 0) >= 0 ? 'green' : 'red'}
          />
          <SummaryCard
            label="Depósitos"
            value={eur(summary.total_deposits)}
            sub={summary.total_withdrawals > 0 ? `Levantamentos: ${eur(summary.total_withdrawals)}` : undefined}
          />
          <SummaryCard label="Posições" value={String(filteredPositions.length)} />
        </div>
      )}

      {/* Best Returns */}
      {bestReturns.length > 0 && (
        <div className="bg-[#161616] border border-[#222] rounded-2xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Trophy size={18} className="text-amber-400" />
            <h2 className="text-sm font-semibold text-white">Melhores Retornos</h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-3">
            {bestReturns.map((p, i) => (
              <div key={p.id} className="bg-[#1a1a1a] border border-[#2a2a2a] rounded-xl p-3 relative">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium text-white text-sm">{p.instrument}</span>
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${
                    p.source === 'finst' ? 'bg-teal-500/20 text-teal-400' : 'bg-blue-500/20 text-blue-400'
                  }`}>
                    {p.source === 'finst' ? 'Crypto' : 'T212'}
                  </span>
                </div>
                <div className={`text-lg font-bold font-mono ${p.returnPct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {p.returnPct >= 0 ? '+' : ''}{p.returnPct.toFixed(1)}%
                </div>
                <div className={`text-xs font-mono mt-0.5 ${p.return_eur >= 0 ? 'text-green-400/60' : 'text-red-400/60'}`}>
                  {p.return_eur >= 0 ? '+' : ''}{eur(p.return_eur)}
                </div>
                {i === 0 && (
                  <div className="absolute -top-2 -right-2 w-6 h-6 bg-amber-500 rounded-full flex items-center justify-center text-[10px] font-bold text-black">
                    1
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tabs + Month Filter */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex gap-1 bg-[#161616] rounded-xl p-1 w-fit">
          {([
            ['overview', 'Posições'],
            ['trades', `Trades${filterMonth !== 'all' ? ` (${filteredTrades.length})` : ''}`],
            ['transactions', `Transações${filterMonth !== 'all' ? ` (${filteredTransactions.length})` : ''}`],
            ['stats', 'Estatísticas'],
            ['planner', 'Planeamento'],
            ['signals', 'Sinais IA'],
          ] as [Tab, string][]).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
                tab === key ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-600 mr-1">Mês:</span>
          <button
            onClick={() => {
              const idx = availableMonths.indexOf(filterMonth);
              if (idx < availableMonths.length - 1) setFilterMonth(availableMonths[idx + 1]);
            }}
            className="p-1.5 rounded-lg bg-[#1a1a1a] border border-[#333] text-gray-400 hover:text-white hover:bg-[#222] transition-colors disabled:opacity-30"
            disabled={availableMonths.indexOf(filterMonth) >= availableMonths.length - 1}
          >
            <ChevronLeft size={14} />
          </button>
          <select
            value={filterMonth}
            onChange={e => setFilterMonth(e.target.value)}
            className="bg-[#1a1a1a] border border-[#333] rounded-xl px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:border-[#555] min-w-[180px]"
          >
            {availableMonths.map(m => (
              <option key={m} value={m}>
                {m === 'all' ? 'Todos os meses' : new Date(m + '-01').toLocaleDateString('pt-PT', { month: 'long', year: 'numeric' })}
              </option>
            ))}
          </select>
          <button
            onClick={() => {
              const idx = availableMonths.indexOf(filterMonth);
              if (idx > 0) setFilterMonth(availableMonths[idx - 1]);
            }}
            className="p-1.5 rounded-lg bg-[#1a1a1a] border border-[#333] text-gray-400 hover:text-white hover:bg-[#222] transition-colors disabled:opacity-30"
            disabled={availableMonths.indexOf(filterMonth) <= 0}
          >
            <ChevronRight size={14} />
          </button>
        </div>
      </div>

      {/* Content */}
      {tab === 'overview' && <PositionsTable positions={filteredPositions} eur={eur} pl={pl} onPriceUpdated={loadData} />}
      {tab === 'trades' && <TradesTable trades={filteredTrades} eur={eur} />}
      {tab === 'transactions' && <TransactionsTable transactions={filteredTransactions} eur={eur} />}
      {tab === 'stats' && <StatsPanel positions={filteredPositions} allPositions={filteredPositionsBySource} trades={filteredTradesBySource} transactions={filteredTransactionsBySource} summary={summary} eur={eur} pl={pl} />}
      {tab === 'planner' && <PlannerPanel positions={filteredPositions} transactions={filteredTransactionsBySource} eur={eur} />}
      {tab === 'signals' && <SignalsPanel />}
    </div>
  );
}

// ── Summary Card ────────────────────────────────────────────────────

function SummaryCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: 'green' | 'red' }) {
  return (
    <div className="bg-[#161616] border border-[#222] rounded-2xl p-5">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className="text-xl font-bold text-white">{value}</p>
      {sub && (
        <p className={`text-sm mt-1 ${color === 'green' ? 'text-green-400' : color === 'red' ? 'text-red-400' : 'text-gray-400'}`}>
          {sub}
        </p>
      )}
    </div>
  );
}

// ── Positions Table ─────────────────────────────────────────────────

function PositionsTable({ positions, eur, pl, onPriceUpdated }: { positions: Position[]; eur: (v: number) => string; pl: (v: number) => string; onPriceUpdated: () => void }) {
  const [sort, setSort] = useState<'value' | 'return' | 'returnPct' | 'name'>('returnPct');
  const [dir, setDir] = useState<'asc' | 'desc'>('desc');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editPrice, setEditPrice] = useState('');

  async function savePrice(id: number) {
    const price = parseFloat(editPrice);
    if (isNaN(price) || price <= 0) return;
    try {
      await investmentsApi.updatePositionPrice(id, price);
      setEditingId(null);
      onPriceUpdated();
    } catch {}
  }

  function returnPctFor(p: Position): number {
    return p.avg_price > 0 ? ((p.current_price - p.avg_price) / p.avg_price * 100) : 0;
  }

  const sorted = [...positions].sort((a, b) => {
    const m = dir === 'asc' ? 1 : -1;
    if (sort === 'value') return (a.current_value_eur - b.current_value_eur) * m;
    if (sort === 'return') return (a.return_eur - b.return_eur) * m;
    if (sort === 'returnPct') return (returnPctFor(a) - returnPctFor(b)) * m;
    return a.instrument.localeCompare(b.instrument) * m;
  });

  function toggleSort(key: typeof sort) {
    if (sort === key) setDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSort(key); setDir('desc'); }
  }

  if (positions.length === 0) {
    return (
      <div className="bg-[#161616] border border-[#222] rounded-2xl p-12 text-center text-gray-500">
        Sem posições. Importa dados para começar.
      </div>
    );
  }

  return (
    <div className="bg-[#161616] border border-[#222] rounded-2xl overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[#222] text-gray-500 text-xs">
            <th className="text-left p-4 cursor-pointer hover:text-gray-300" onClick={() => toggleSort('name')}>
              Instrumento {sort === 'name' && (dir === 'asc' ? '↑' : '↓')}
            </th>
            <th className="text-right p-4">Quantidade</th>
            <th className="text-right p-4">Preço Médio</th>
            <th className="text-right p-4">Preço Atual</th>
            <th className="text-right p-4 cursor-pointer hover:text-gray-300" onClick={() => toggleSort('return')}>
              Retorno {sort === 'return' && (dir === 'asc' ? '↑' : '↓')}
            </th>
            <th className="text-right p-4 cursor-pointer hover:text-gray-300" onClick={() => toggleSort('returnPct')}>
              Retorno % {sort === 'returnPct' && (dir === 'asc' ? '↑' : '↓')}
            </th>
            <th className="text-right p-4 cursor-pointer hover:text-gray-300" onClick={() => toggleSort('value')}>
              Valor {sort === 'value' && (dir === 'asc' ? '↑' : '↓')}
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map(p => {
            const returnPct = p.avg_price > 0
              ? ((p.current_price - p.avg_price) / p.avg_price * 100)
              : 0;
            return (
              <tr key={p.id} className="border-b border-[#222] hover:bg-white/5 transition-colors">
                <td className="p-4">
                  <div className="flex items-center gap-2">
                    {p.return_eur != null && p.return_eur >= 0
                      ? <TrendingUp size={16} className="text-green-400" />
                      : p.return_eur != null
                        ? <TrendingDown size={16} className="text-red-400" />
                        : <span className="w-4" />}
                    <div>
                      <span className="font-medium text-white">{p.instrument}</span>
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ml-2 ${
                        p.source === 'finst' ? 'bg-teal-500/20 text-teal-400' : 'bg-blue-500/20 text-blue-400'
                      }`}>
                        {p.source === 'finst' ? 'Crypto' : 'T212'}
                      </span>
                    </div>
                  </div>
                </td>
                <td className="text-right p-4 text-gray-300 font-mono">
                  {p.quantity.toFixed(p.quantity < 1 ? 6 : 2)}
                </td>
                <td className="text-right p-4 text-gray-300 font-mono">
                  {p.avg_price.toFixed(2)}
                </td>
                <td className="text-right p-4 text-gray-300 font-mono">
                  {editingId === p.id ? (
                    <div className="flex items-center justify-end gap-1">
                      <input
                        type="number"
                        step="any"
                        value={editPrice}
                        onChange={e => setEditPrice(e.target.value)}
                        onKeyDown={e => {
                          if (e.key === 'Enter') savePrice(p.id);
                          if (e.key === 'Escape') setEditingId(null);
                        }}
                        autoFocus
                        className="w-28 bg-[#222] border border-[#444] rounded px-2 py-0.5 text-right text-sm text-white font-mono focus:outline-none focus:border-blue-500"
                      />
                      <button onClick={() => savePrice(p.id)} className="p-0.5 text-green-400 hover:text-green-300"><Check size={14} /></button>
                      <button onClick={() => setEditingId(null)} className="p-0.5 text-gray-500 hover:text-gray-300"><X size={14} /></button>
                    </div>
                  ) : (
                    <span
                      className="cursor-pointer hover:text-white group inline-flex items-center gap-1"
                      onClick={() => { setEditingId(p.id); setEditPrice(p.current_price ? String(p.current_price) : ''); }}
                    >
                      {p.current_price ? p.current_price.toFixed(2) : '—'}
                      <Pencil size={11} className="opacity-0 group-hover:opacity-50" />
                    </span>
                  )}
                </td>
                <td className={`text-right p-4 font-mono font-medium ${p.return_eur != null ? pl(p.return_eur) : 'text-gray-500'}`}>
                  {p.return_eur != null ? (
                    <>{p.return_eur >= 0 ? '+' : ''}{eur(p.return_eur)}</>
                  ) : '—'}
                </td>
                <td className={`text-right p-4 font-mono font-medium ${p.return_eur != null ? pl(p.return_eur) : 'text-gray-500'}`}>
                  {p.return_eur != null ? (
                    <>{returnPct >= 0 ? '+' : ''}{returnPct.toFixed(1)}%</>
                  ) : '—'}
                </td>
                <td className="text-right p-4 text-white font-mono font-medium">
                  {p.current_value_eur != null ? eur(p.current_value_eur) : '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="border-t border-[#333] bg-[#1a1a1a]">
            <td className="p-4 font-medium text-gray-400" colSpan={4}>Total</td>
            <td className={`text-right p-4 font-mono font-bold ${pl(positions.reduce((s, p) => s + (p.return_eur ?? 0), 0))}`}>
              {positions.reduce((s, p) => s + (p.return_eur ?? 0), 0) >= 0 ? '+' : ''}
              {eur(positions.reduce((s, p) => s + (p.return_eur ?? 0), 0))}
            </td>
            <td className={`text-right p-4 font-mono font-bold ${pl(positions.reduce((s, p) => s + (p.return_eur ?? 0), 0))}`}>
              {(() => {
                const totalInvested = positions.reduce((s, p) => s + (p.quantity * p.avg_price) / (p.fx_rate && p.fx_rate !== 0 ? p.fx_rate : 1), 0);
                const totalReturn = positions.reduce((s, p) => s + (p.return_eur ?? 0), 0);
                const pct = totalInvested > 0 ? (totalReturn / totalInvested) * 100 : 0;
                return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
              })()}
            </td>
            <td className="text-right p-4 text-white font-mono font-bold">
              {eur(positions.reduce((s, p) => s + (p.current_value_eur ?? 0), 0))}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

// ── Trades Table ────────────────────────────────────────────────────

function TradesTable({ trades, eur }: { trades: Trade[]; eur: (v: number) => string }) {
  if (trades.length === 0) {
    return (
      <div className="bg-[#161616] border border-[#222] rounded-2xl p-12 text-center text-gray-500">
        Sem trades registados.
      </div>
    );
  }

  return (
    <div className="bg-[#161616] border border-[#222] rounded-2xl overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[#222] text-gray-500 text-xs">
            <th className="text-left p-4">Data</th>
            <th className="text-left p-4">Instrumento</th>
            <th className="text-center p-4">Direção</th>
            <th className="text-right p-4">Quantidade</th>
            <th className="text-right p-4">Preço</th>
            <th className="text-right p-4">Valor EUR</th>
            <th className="text-right p-4">FX Fee</th>
          </tr>
        </thead>
        <tbody>
          {trades.map(t => (
            <tr key={t.id} className="border-b border-[#222] hover:bg-white/5 transition-colors">
              <td className="p-4 text-gray-400 font-mono text-xs">
                {new Date(t.execution_time).toLocaleDateString('pt-PT')}
                <span className="text-gray-600 ml-1">
                  {new Date(t.execution_time).toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' })}
                </span>
              </td>
              <td className="p-4">
                <span className="font-medium text-white">{t.instrument}</span>
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ml-2 ${
                  t.source === 'finst' ? 'bg-teal-500/20 text-teal-400' : 'bg-blue-500/20 text-blue-400'
                }`}>
                  {t.source === 'finst' ? 'Crypto' : 'T212'}
                </span>
              </td>
              <td className="text-center p-4">
                <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${
                  t.direction === 'Buy' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                }`}>
                  {t.direction === 'Buy' ? 'Compra' : 'Venda'}
                </span>
              </td>
              <td className="text-right p-4 text-gray-300 font-mono">
                {t.quantity.toFixed(t.quantity < 1 ? 6 : 2)}
              </td>
              <td className="text-right p-4 text-gray-300 font-mono">
                {t.execution_price.toFixed(2)} {t.currency}
              </td>
              <td className="text-right p-4 text-white font-mono font-medium">
                {eur(t.value_eur)}
              </td>
              <td className="text-right p-4 text-gray-500 font-mono">
                {t.fx_fee > 0 ? eur(t.fx_fee) : '-'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Transactions Table ──────────────────────────────────────────────

function TransactionsTable({ transactions, eur }: { transactions: Transaction[]; eur: (v: number) => string }) {
  if (transactions.length === 0) {
    return (
      <div className="bg-[#161616] border border-[#222] rounded-2xl p-12 text-center text-gray-500">
        Sem transações registadas.
      </div>
    );
  }

  return (
    <div className="bg-[#161616] border border-[#222] rounded-2xl overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[#222] text-gray-500 text-xs">
            <th className="text-left p-4">Data</th>
            <th className="text-left p-4">Tipo</th>
            <th className="text-right p-4">Montante</th>
          </tr>
        </thead>
        <tbody>
          {transactions.map(t => (
            <tr key={t.id} className="border-b border-[#222] hover:bg-white/5 transition-colors">
              <td className="p-4 text-gray-400 font-mono text-xs">
                {new Date(t.time).toLocaleDateString('pt-PT')}
                <span className="text-gray-600 ml-1">
                  {new Date(t.time).toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' })}
                </span>
              </td>
              <td className="p-4">
                <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${
                  t.type === 'Depósito' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                }`}>
                  {t.type}
                </span>
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ml-2 ${
                  t.source === 'finst' ? 'bg-teal-500/20 text-teal-400' : 'bg-blue-500/20 text-blue-400'
                }`}>
                  {t.source === 'finst' ? 'Crypto' : 'T212'}
                </span>
              </td>
              <td className="text-right p-4 text-white font-mono font-medium">
                {eur(t.amount)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Stats Panel ─────────────────────────────────────────────────────

const COLORS = ['#14b8a6', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1'];

interface Plan {
  id: number;
  name: string;
  instrument: string;
  asset_type: string;
  target_amount_eur: number | null;
  status: string;
  created_at: string;
  updated_at: string;
}

interface Allocation {
  id: number;
  name: string;
  ticker: string;
  asset_type: string;
  percentage: number;
  sort_order: number;
  is_rotational: boolean;
}

interface MonthlyPlan {
  id: number;
  month: string;
  budget: number;
  rotational_choices: Record<string, string>;
}

interface Suggestion {
  type: string;
  severity: string;
  title: string;
  description: string;
  action: string;
}

function StatsPanel({ positions, allPositions, trades, transactions, summary, eur, pl }: {
  positions: Position[];
  allPositions: Position[];
  trades: Trade[];
  transactions: Transaction[];
  summary: Summary | null;
  eur: (v: number) => string;
  pl: (v: number) => string;
}) {
  // Mapeamento de tickers para nomes completos
  const INSTRUMENT_NAMES: Record<string, string> = {
    'VUAA': 'Vanguard S&P 500',
    'BTC': 'Bitcoin',
    'CNDX': 'iShares Nasdaq 100',
    'NVDA': 'NVIDIA',
    'ETH': 'Ethereum',
    'SSLN': 'iShares Semiconductors',
    'SGLD': 'Invesco Physical Gold',
    'AAPL': 'Apple',
  };
  const getName = (ticker: string) => INSTRUMENT_NAMES[ticker] || ticker;

  // ── 1. Distribuição por ativo ─────────────────────────────────
  const distribution = useMemo(() => {
    const total = positions.reduce((s, p) => s + (p.current_value_eur ?? 0), 0);
    if (total <= 0) return [];
    return positions
      .filter(p => (p.current_value_eur ?? 0) > 0)
      .map(p => ({
        instrument: p.instrument,
        value: p.current_value_eur ?? 0,
        pct: ((p.current_value_eur ?? 0) / total) * 100,
        source: p.source,
      }))
      .sort((a, b) => b.value - a.value);
  }, [positions]);

  // ── 2. Lucro/Prejuízo por mês ────────────────────────────────
  const monthlyPnL = useMemo(() => {
    const months = new Map<string, number>();
    for (const p of allPositions) {
      if (p.statement_date && p.return_eur != null) {
        months.set(p.statement_date, (months.get(p.statement_date) || 0) + p.return_eur);
      }
    }
    return Array.from(months.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([month, ret]) => ({ month, return_eur: ret }));
  }, [allPositions]);

  // ── 3. Investimento mensal ────────────────────────────────────
  const monthlyDeposits = useMemo(() => {
    const months = new Map<string, number>();
    for (const t of transactions) {
      if (t.type === 'Depósito') {
        const d = new Date(t.time);
        const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
        months.set(key, (months.get(key) || 0) + t.amount);
      }
    }
    return Array.from(months.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([month, amount]) => ({ month, amount }));
  }, [transactions]);

  const avgMonthlyDeposit = useMemo(() => {
    if (monthlyDeposits.length === 0) return 0;
    return monthlyDeposits.reduce((s, m) => s + m.amount, 0) / monthlyDeposits.length;
  }, [monthlyDeposits]);

  // ── 6. Retorno por ativo ────────────────────────────────────
  const returnByAsset = useMemo(() => {
    return positions
      .filter(p => p.return_eur != null)
      .map(p => ({
        instrument: p.instrument,
        return_eur: p.return_eur ?? 0,
        source: p.source,
      }))
      .sort((a, b) => b.return_eur - a.return_eur);
  }, [positions]);

  const maxAbsReturn = useMemo(() => Math.max(...returnByAsset.map(r => Math.abs(r.return_eur)), 1), [returnByAsset]);

  // ── 7. Alocação por tipo ──────────────────────────────────────
  const ASSET_TYPE: Record<string, string> = {
    'VUAA': 'ETF', 'CNDX': 'ETF', 'SSLN': 'ETF', 'SGLD': 'ETF',
    'BTC': 'Crypto', 'ETH': 'Crypto',
    'NVDA': 'Ações', 'AAPL': 'Ações',
  };
  const typeAllocation = useMemo(() => {
    const totals = new Map<string, number>();
    for (const p of positions) {
      const type = ASSET_TYPE[p.instrument] || 'Outro';
      totals.set(type, (totals.get(type) || 0) + (p.current_value_eur ?? 0));
    }
    const total = Array.from(totals.values()).reduce((s, v) => s + v, 0);
    if (total <= 0) return [];
    return Array.from(totals.entries())
      .map(([type, value]) => ({ type, value, pct: (value / total) * 100 }))
      .sort((a, b) => b.value - a.value);
  }, [positions]);

  // ── 8. Evolução do portfolio ──────────────────────────────────
  const portfolioEvolution = useMemo(() => {
    const months = new Map<string, number>();
    for (const p of allPositions) {
      if (p.statement_date && p.current_value_eur != null) {
        months.set(p.statement_date, (months.get(p.statement_date) || 0) + p.current_value_eur);
      }
    }
    return Array.from(months.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([month, value]) => ({ month, value }));
  }, [allPositions]);

  // ── 5. Valor líquido ──────────────────────────────────────────
  const netValue = useMemo(() => {
    const totalDeposits = transactions
      .filter(t => t.type === 'Depósito')
      .reduce((s, t) => s + t.amount, 0);
    const totalWithdrawals = transactions
      .filter(t => t.type === 'Levantamento')
      .reduce((s, t) => s + t.amount, 0);
    const netInvested = totalDeposits - totalWithdrawals;
    const totalReturn = positions.reduce((s, p) => s + (p.return_eur ?? 0), 0);
    const currentValue = positions.reduce((s, p) => s + (p.current_value_eur ?? 0), 0);
    const pct = netInvested > 0 ? (totalReturn / netInvested) * 100 : 0;
    return { netInvested, currentValue, totalReturn, pct, totalDeposits, totalWithdrawals };
  }, [positions, transactions]);

  const maxBarPnL = useMemo(() => Math.max(...monthlyPnL.map(m => Math.abs(m.return_eur)), 1), [monthlyPnL]);
  const maxBarDeposit = useMemo(() => Math.max(...monthlyDeposits.map(m => m.amount), 1), [monthlyDeposits]);

  const fmtMonth = (m: string) => {
    try { return new Date(m + '-01').toLocaleDateString('pt-PT', { month: 'short', year: '2-digit' }); }
    catch { return m; }
  };

  return (
    <div className="space-y-6">
      {/* 1. Distribuição por ativo */}
      <div className="bg-[#161616] border border-[#222] rounded-2xl p-5">
        <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
          <BarChart3 size={16} className="text-blue-400" />
          Distribuição por Ativo
        </h3>
        {distribution.length === 0 ? (
          <p className="text-gray-500 text-sm">Sem dados</p>
        ) : (
          <div className="space-y-2.5">
            {distribution.map((d, i) => (
              <div key={d.instrument} className="flex items-center gap-3">
                <div className="w-40 text-xs font-medium text-gray-300 flex items-center gap-1.5 truncate">
                  {getName(d.instrument)}
                  <span className={`shrink-0 text-[9px] px-1 py-0.5 rounded ${d.source === 'finst' ? 'bg-teal-500/20 text-teal-400' : 'bg-blue-500/20 text-blue-400'}`}>
                    {d.source === 'finst' ? 'Crypto' : 'T212'}
                  </span>
                </div>
                <div className="flex-1 h-6 bg-[#222] rounded-lg overflow-hidden relative">
                  <div
                    className="h-full rounded-lg transition-all duration-500"
                    style={{ width: `${d.pct}%`, backgroundColor: COLORS[i % COLORS.length] }}
                  />
                </div>
                <div className="w-24 text-right">
                  <span className="text-xs font-mono text-white">{d.pct.toFixed(1)}%</span>
                  <span className="text-[10px] text-gray-500 ml-1">{eur(d.value)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 5. Valor líquido */}
      <div className="bg-[#161616] border border-[#222] rounded-2xl p-5">
        <h3 className="text-sm font-semibold text-white mb-4">Valor Líquido</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-4">
          <div>
            <p className="text-xs text-gray-500 mb-1">Investido (líquido)</p>
            <p className="text-lg font-bold text-white font-mono">{eur(netValue.netInvested)}</p>
            <p className="text-[10px] text-gray-600">{eur(netValue.totalDeposits)} dep. − {eur(netValue.totalWithdrawals)} lev.</p>
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-1">Valor Posições</p>
            <p className="text-lg font-bold text-white font-mono">{eur(netValue.currentValue)}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-1">Retorno Total</p>
            <p className={`text-lg font-bold font-mono ${netValue.totalReturn >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {netValue.totalReturn >= 0 ? '+' : ''}{eur(netValue.totalReturn)}
            </p>
            <p className={`text-xs ${netValue.pct >= 0 ? 'text-green-400/70' : 'text-red-400/70'}`}>
              {netValue.pct >= 0 ? '+' : ''}{netValue.pct.toFixed(2)}%
            </p>
          </div>
        </div>
        {/* Visual bar comparing invested vs current */}
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-gray-500 w-16">Investido</span>
            <div className="flex-1 h-4 bg-[#222] rounded overflow-hidden">
              <div className="h-full bg-gray-500 rounded" style={{ width: `${Math.min(100, (netValue.netInvested / Math.max(netValue.netInvested, netValue.currentValue)) * 100)}%` }} />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-gray-500 w-16">Posições</span>
            <div className="flex-1 h-4 bg-[#222] rounded overflow-hidden">
              <div className={`h-full rounded ${netValue.totalReturn >= 0 ? 'bg-green-500' : 'bg-red-500'}`} style={{ width: `${Math.min(100, (netValue.currentValue / Math.max(netValue.netInvested, netValue.currentValue)) * 100)}%` }} />
            </div>
          </div>
        </div>
      </div>

      {/* 2. Lucro/Prejuízo por mês */}
      <div className="bg-[#161616] border border-[#222] rounded-2xl p-5">
        <h3 className="text-sm font-semibold text-white mb-4">Retorno por Mês</h3>
        {monthlyPnL.length === 0 ? (
          <p className="text-gray-500 text-sm">Sem dados mensais</p>
        ) : (
          <div className="space-y-2">
            {monthlyPnL.map(m => (
              <div key={m.month} className="flex items-center gap-3">
                <span className="text-xs text-gray-400 w-20 font-mono">{fmtMonth(m.month)}</span>
                <div className="flex-1 flex items-center">
                  {/* Center-aligned bars: negative left, positive right */}
                  <div className="w-1/2 flex justify-end">
                    {m.return_eur < 0 && (
                      <div className="h-5 bg-red-500/30 rounded-l" style={{ width: `${(Math.abs(m.return_eur) / maxBarPnL) * 100}%` }} />
                    )}
                  </div>
                  <div className="w-px h-5 bg-[#444]" />
                  <div className="w-1/2">
                    {m.return_eur >= 0 && (
                      <div className="h-5 bg-green-500/30 rounded-r" style={{ width: `${(m.return_eur / maxBarPnL) * 100}%` }} />
                    )}
                  </div>
                </div>
                <span className={`text-xs font-mono w-20 text-right ${m.return_eur >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {m.return_eur >= 0 ? '+' : ''}{eur(m.return_eur)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 3. Investimento mensal */}
      <div className="bg-[#161616] border border-[#222] rounded-2xl p-5">
        <h3 className="text-sm font-semibold text-white mb-1">Investimento Mensal</h3>
        <p className="text-xs text-gray-500 mb-4">
          Média: <span className="text-amber-400 font-mono">{eur(avgMonthlyDeposit)}</span> / mês
        </p>
        {monthlyDeposits.length === 0 ? (
          <p className="text-gray-500 text-sm">Sem depósitos</p>
        ) : (
          <div className="flex items-end gap-2 h-28">
            {monthlyDeposits.map(m => (
              <div key={m.month} className="flex-1 flex flex-col items-center gap-1">
                <span className="text-[10px] font-mono text-gray-400">{eur(m.amount)}</span>
                <div className="w-full bg-[#222] rounded-t overflow-hidden" style={{ height: '80px' }}>
                  <div
                    className="w-full bg-amber-500/40 rounded-t mt-auto"
                    style={{ height: `${(m.amount / maxBarDeposit) * 100}%`, marginTop: `${100 - (m.amount / maxBarDeposit) * 100}%` }}
                  />
                </div>
                <span className="text-[9px] text-gray-600">{fmtMonth(m.month)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 6. Retorno por ativo */}
      <div className="bg-[#161616] border border-[#222] rounded-2xl p-5">
        <h3 className="text-sm font-semibold text-white mb-4">Retorno por Ativo</h3>
        {returnByAsset.length === 0 ? (
          <p className="text-gray-500 text-sm">Sem dados</p>
        ) : (
          <div className="space-y-2">
            {returnByAsset.map(r => (
              <div key={r.instrument} className="flex items-center gap-3">
                <div className="w-40 text-xs font-medium text-gray-300 flex items-center gap-1.5 truncate">
                  {getName(r.instrument)}
                  <span className={`shrink-0 text-[9px] px-1 py-0.5 rounded ${r.source === 'finst' ? 'bg-teal-500/20 text-teal-400' : 'bg-blue-500/20 text-blue-400'}`}>
                    {r.source === 'finst' ? 'Crypto' : 'T212'}
                  </span>
                </div>
                <div className="flex-1 flex items-center">
                  <div className="w-1/2 flex justify-end">
                    {r.return_eur < 0 && (
                      <div className="h-5 bg-red-500/40 rounded-l" style={{ width: `${(Math.abs(r.return_eur) / maxAbsReturn) * 100}%` }} />
                    )}
                  </div>
                  <div className="w-px h-5 bg-[#444]" />
                  <div className="w-1/2">
                    {r.return_eur >= 0 && (
                      <div className="h-5 bg-green-500/40 rounded-r" style={{ width: `${(r.return_eur / maxAbsReturn) * 100}%` }} />
                    )}
                  </div>
                </div>
                <span className={`text-xs font-mono w-20 text-right ${r.return_eur >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {r.return_eur >= 0 ? '+' : ''}{eur(r.return_eur)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 7. Alocação por tipo */}
      <div className="bg-[#161616] border border-[#222] rounded-2xl p-5">
        <h3 className="text-sm font-semibold text-white mb-4">Alocação por Tipo</h3>
        {typeAllocation.length === 0 ? (
          <p className="text-gray-500 text-sm">Sem dados</p>
        ) : (
          <div className="flex items-center gap-8">
            {/* Donut chart via SVG */}
            <div className="relative w-36 h-36 shrink-0">
              <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
                {(() => {
                  const TYPE_COLORS: Record<string, string> = { 'ETF': '#3b82f6', 'Crypto': '#14b8a6', 'Ações': '#f59e0b', 'Outro': '#6b7280' };
                  let offset = 0;
                  return typeAllocation.map(t => {
                    const dash = t.pct * 0.75; // 75 is circumference fraction for gap
                    const el = (
                      <circle
                        key={t.type}
                        cx="18" cy="18" r="12"
                        fill="none"
                        stroke={TYPE_COLORS[t.type] || '#6b7280'}
                        strokeWidth="5"
                        strokeDasharray={`${dash} ${75 - dash}`}
                        strokeDashoffset={-offset * 0.75}
                        strokeLinecap="round"
                      />
                    );
                    offset += t.pct;
                    return el;
                  });
                })()}
              </svg>
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-[10px] text-gray-500">{typeAllocation.length} tipos</span>
              </div>
            </div>
            {/* Legend */}
            <div className="space-y-3 flex-1">
              {(() => {
                const TYPE_COLORS: Record<string, string> = { 'ETF': '#3b82f6', 'Crypto': '#14b8a6', 'Ações': '#f59e0b', 'Outro': '#6b7280' };
                return typeAllocation.map(t => (
                  <div key={t.type} className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="w-3 h-3 rounded-full" style={{ backgroundColor: TYPE_COLORS[t.type] || '#6b7280' }} />
                      <span className="text-sm text-gray-300">{t.type}</span>
                    </div>
                    <div className="text-right">
                      <span className="text-sm font-mono text-white">{t.pct.toFixed(1)}%</span>
                      <span className="text-[10px] text-gray-500 ml-2">{eur(t.value)}</span>
                    </div>
                  </div>
                ));
              })()}
            </div>
          </div>
        )}
      </div>

      {/* 8. Evolução do portfolio */}
      <div className="bg-[#161616] border border-[#222] rounded-2xl p-5">
        <h3 className="text-sm font-semibold text-white mb-4">Evolução do Portfolio</h3>
        {portfolioEvolution.length === 0 ? (
          <p className="text-gray-500 text-sm">Sem snapshots mensais</p>
        ) : (
          <div className="relative">
            {/* SVG line chart */}
            {(() => {
              const W = 600, H = 160, PY = 20, PX = 10;
              const vals = portfolioEvolution.map(e => e.value);
              const minV = Math.min(...vals) * 0.95;
              const maxV = Math.max(...vals) * 1.05;
              const range = maxV - minV || 1;
              const points = portfolioEvolution.map((e, i) => {
                const x = PX + (i / Math.max(portfolioEvolution.length - 1, 1)) * (W - 2 * PX);
                const y = PY + (1 - (e.value - minV) / range) * (H - 2 * PY);
                return { x, y, ...e };
              });
              const line = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ');
              const areaPath = `${line} L${points[points.length - 1].x},${H} L${points[0].x},${H} Z`;
              return (
                <svg viewBox={`0 0 ${W} ${H}`} className="w-full" preserveAspectRatio="none" style={{ height: '180px' }}>
                  <defs>
                    <linearGradient id="evoGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.3" />
                      <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
                    </linearGradient>
                  </defs>
                  <path d={areaPath} fill="url(#evoGrad)" />
                  <path d={line} fill="none" stroke="#3b82f6" strokeWidth="2.5" strokeLinejoin="round" />
                  {points.map((p, i) => (
                    <g key={i}>
                      <circle cx={p.x} cy={p.y} r="4" fill="#3b82f6" stroke="#161616" strokeWidth="2" />
                      <text x={p.x} y={p.y - 10} textAnchor="middle" fill="#e5e7eb" fontSize="9" fontFamily="monospace">{eur(p.value)}</text>
                      <text x={p.x} y={H - 2} textAnchor="middle" fill="#6b7280" fontSize="8" fontFamily="monospace">{fmtMonth(p.month)}</text>
                    </g>
                  ))}
                </svg>
              );
            })()}
          </div>
        )}
      </div>
    </div>
  );
}


// ── Tabela de plano sugerido pela IA (editável) ───────────────────

interface SuggestedRow {
  ticker: string;
  name: string;
  asset_type: string;
  percentage: number;
}

function SuggestedPlanTable({
  suggestions,
  defaultBudget,
  currentAllocations,
  onAdopted,
  eur,
}: {
  suggestions: any[];
  defaultBudget: number;
  currentAllocations: Allocation[];
  onAdopted: () => void;
  eur: (v: number) => string;
}) {
  // Constrói linhas a partir das sugestões "buy" — usa amount_eur para inferir % ou cai
  // em distribuição uniforme se nada estiver definido.
  const initialRows = useMemo<SuggestedRow[]>(() => {
    const buys = suggestions.filter(s => (s.action || '').toLowerCase() === 'buy' && s.ticker);
    if (buys.length === 0) return [];
    const totalAmt = buys.reduce((acc, s) => acc + (Number(s.amount_eur) || 0), 0);
    if (totalAmt > 0) {
      return buys.map(s => ({
        ticker: String(s.ticker).toUpperCase(),
        name: s.name || s.ticker,
        asset_type: s.asset_type || 'stock',
        percentage: Math.round(((Number(s.amount_eur) || 0) / totalAmt) * 1000) / 10,
      }));
    }
    const uniform = Math.floor(1000 / buys.length) / 10;
    return buys.map(s => ({
      ticker: String(s.ticker).toUpperCase(),
      name: s.name || s.ticker,
      asset_type: s.asset_type || 'stock',
      percentage: uniform,
    }));
  }, [suggestions]);

  const [rows, setRows] = useState<SuggestedRow[]>(initialRows);
  const [budget, setBudget] = useState<number>(defaultBudget || 200);
  const [adopting, setAdopting] = useState(false);

  // Re-sync quando as sugestões mudam (nova análise)
  useEffect(() => { setRows(initialRows); }, [initialRows]);

  const totalPct = rows.reduce((s, r) => s + (r.percentage || 0), 0);
  const isBalanced = Math.abs(totalPct - 100) < 0.5;

  const updatePct = (i: number, val: string) => {
    const num = parseFloat(val);
    setRows(rs => rs.map((r, idx) => idx === i ? { ...r, percentage: isNaN(num) ? 0 : num } : r));
  };

  const removeRow = (i: number) => setRows(rs => rs.filter((_, idx) => idx !== i));

  const normalize = () => {
    if (totalPct <= 0) return;
    const factor = 100 / totalPct;
    setRows(rs => rs.map(r => ({ ...r, percentage: Math.round(r.percentage * factor * 10) / 10 })));
  };

  const adoptAsPlan = async () => {
    if (!isBalanced) {
      if (!confirm(`O total é ${totalPct.toFixed(1)}%, não 100%. Adotar mesmo assim?`)) return;
    } else if (!confirm('Substitui o plano de alocação atual por este. Continuar?')) {
      return;
    }
    setAdopting(true);
    try {
      // Apaga as allocations actuais
      for (const a of currentAllocations) {
        await investmentsApi.deleteAllocation(a.id);
      }
      // Cria as novas
      let order = 0;
      for (const r of rows) {
        await investmentsApi.createAllocation({
          name: r.name,
          ticker: r.ticker,
          asset_type: r.asset_type,
          percentage: r.percentage,
          sort_order: order++,
        });
      }
      onAdopted();
    } catch (e: any) {
      alert(`Erro a adotar plano: ${e.message}`);
    } finally {
      setAdopting(false);
    }
  };

  if (rows.length === 0) {
    return (
      <div className="text-xs text-gray-500 italic text-center py-3">
        A IA não devolveu nenhuma compra ('buy') — sem plano sugerido.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-400">Budget:</label>
          <input
            type="number"
            min="0"
            step="10"
            value={budget}
            onChange={e => setBudget(Number(e.target.value) || 0)}
            className="w-24 bg-[#222] border border-[#333] rounded px-2 py-1 text-xs text-white text-right focus:border-amber-500 focus:outline-none"
          />
          <span className="text-xs text-gray-400">€/mês</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-xs font-mono ${isBalanced ? 'text-green-400' : 'text-amber-400'}`}>
            Total: {totalPct.toFixed(1)}%
          </span>
          {!isBalanced && (
            <button onClick={normalize} className="text-[10px] px-2 py-0.5 rounded bg-[#222] text-gray-400 hover:text-white border border-[#333]" title="Reescala todas as % para somarem 100">
              normalizar
            </button>
          )}
        </div>
      </div>

      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-500 border-b border-[#222]">
            <th className="text-left py-1.5 pr-2 font-normal">%</th>
            <th className="text-left py-1.5 px-2 font-normal">Ativo</th>
            <th className="text-left py-1.5 px-2 font-normal">Tipo</th>
            <th className="text-right py-1.5 pl-2 font-normal">€/mês</th>
            <th className="w-6" />
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.ticker}-${i}`} className="border-b border-[#1a1a1a]">
              <td className="py-1.5 pr-2">
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="1"
                  value={r.percentage}
                  onChange={e => updatePct(i, e.target.value)}
                  className="w-14 bg-[#222] border border-[#333] rounded px-1.5 py-0.5 text-xs text-white text-right focus:border-amber-500 focus:outline-none"
                />
                <span className="text-gray-500 ml-0.5">%</span>
              </td>
              <td className="py-1.5 px-2">
                <span className="text-white">{r.name}</span>
                <span className="text-[9px] text-gray-500 font-mono ml-1.5">{r.ticker}</span>
              </td>
              <td className="py-1.5 px-2">
                <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-bold ${
                  r.asset_type === 'etf' ? 'bg-blue-500/20 text-blue-400' :
                  r.asset_type === 'crypto' ? 'bg-teal-500/20 text-teal-400' :
                  'bg-amber-500/20 text-amber-400'
                }`}>
                  {r.asset_type === 'etf' ? 'ETF' : r.asset_type === 'crypto' ? 'Crypto' : 'Ação'}
                </span>
              </td>
              <td className="py-1.5 pl-2 text-right">
                <span className="font-mono text-white">{eur(Math.round((r.percentage / 100) * budget * 100) / 100)}</span>
              </td>
              <td className="py-1.5">
                <button onClick={() => removeRow(i)} className="text-gray-600 hover:text-red-400" title="Remover">×</button>
              </td>
            </tr>
          ))}
          <tr className="border-t border-[#333] font-semibold">
            <td className="py-2 pr-2 text-gray-400">{totalPct.toFixed(1)}%</td>
            <td colSpan={2} className="py-2 px-2 text-gray-400">Total</td>
            <td className="py-2 pl-2 text-right font-mono text-white">{eur(Math.round((totalPct / 100) * budget * 100) / 100)}</td>
            <td />
          </tr>
        </tbody>
      </table>

      <div className="flex justify-end">
        <button
          onClick={adoptAsPlan}
          disabled={adopting || rows.length === 0}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white text-xs font-medium rounded-lg disabled:opacity-50"
          title="Substitui o teu Plano de Investimento actual por estes ativos/percentagens"
        >
          {adopting ? <RefreshCw size={12} className="animate-spin" /> : <Check size={12} />}
          {adopting ? 'A adotar...' : 'Adotar como plano principal'}
        </button>
      </div>
    </div>
  );
}


// ── Rotational asset picker (autocomplete) ────────────────────────

function RotationalAssetInput({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const parsed = (() => {
    if (!value) return null;
    if (value.includes(' - ')) {
      const [ticker, ...rest] = value.split(' - ');
      return { ticker: ticker.trim().toUpperCase(), name: rest.join(' - ').trim() };
    }
    return { ticker: value.trim().toUpperCase(), name: value.trim().toUpperCase() };
  })();
  const [editing, setEditing] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const onChange = (v: string) => {
    setQuery(v);
    if (debounce.current) clearTimeout(debounce.current);
    if (v.trim().length < 2) { setResults([]); return; }
    setLoading(true);
    debounce.current = setTimeout(async () => {
      try { setResults(await investmentsApi.searchAsset(v)); }
      catch { setResults([]); }
      finally { setLoading(false); }
    }, 350);
  };

  const select = (asset: any) => {
    onSave(`${asset.ticker} - ${asset.name}`);
    setEditing(false);
    setQuery('');
    setResults([]);
  };

  if (!editing && parsed) {
    return (
      <div className="flex items-center gap-1.5">
        <span className="text-xs text-white">{parsed.name}</span>
        <span className="text-[9px] text-gray-500 font-mono">{parsed.ticker}</span>
        <button onClick={() => { setEditing(true); setQuery(''); }} className="text-[10px] text-amber-400 hover:text-amber-300 ml-1">trocar</button>
        <button onClick={() => onSave('')} className="text-[10px] text-gray-500 hover:text-red-400">×</button>
      </div>
    );
  }

  return (
    <div className="relative">
      <input
        autoFocus={editing}
        value={query}
        onChange={e => onChange(e.target.value)}
        onBlur={() => setTimeout(() => { if (results.length === 0) setEditing(false); }, 200)}
        placeholder="procurar: google, microsoft, nvidia..."
        className="w-full bg-[#222] border border-[#333] rounded px-2 py-0.5 text-xs text-white placeholder-gray-600 focus:border-amber-500 focus:outline-none"
      />
      {loading && <Loader size={10} className="absolute right-2 top-1/2 -translate-y-1/2 text-amber-400 animate-spin" />}
      {results.length > 0 && (
        <div className="absolute z-10 left-0 right-0 mt-1 bg-[#1c1c1c] border border-[#333] rounded-lg overflow-hidden shadow-xl max-h-48 overflow-y-auto">
          {results.map((r, i) => (
            <button key={i} onMouseDown={e => { e.preventDefault(); select(r); }} className="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-[#252525] text-left">
              <div className="flex-1 min-w-0">
                <span className="text-xs text-white truncate">{r.name}</span>
                <span className="text-[9px] text-gray-500 font-mono ml-1.5">{r.ticker}</span>
              </div>
              <span className={`text-[9px] px-1 py-0.5 rounded ${
                r.asset_type === 'etf' ? 'bg-blue-500/20 text-blue-400' : r.asset_type === 'crypto' ? 'bg-teal-500/20 text-teal-400' : 'bg-amber-500/20 text-amber-400'
              }`}>{r.asset_type === 'etf' ? 'ETF' : r.asset_type === 'crypto' ? 'Crypto' : 'Ação'}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}


// ── Planner Panel ──────────────────────────────────────────────────

function PlannerPanel({ positions, transactions, eur }: {
  positions: Position[];
  transactions: Transaction[];
  eur: (v: number) => string;
}) {
  const INSTRUMENT_NAMES: Record<string, string> = {
    'VUAA': 'Vanguard S&P 500', 'BTC': 'Bitcoin', 'CNDX': 'iShares Nasdaq 100',
    'NVDA': 'NVIDIA', 'ETH': 'Ethereum', 'SSLN': 'iShares Semiconductors',
    'SGLD': 'Invesco Physical Gold', 'AAPL': 'Apple',
  };
  const getName = (ticker: string) => INSTRUMENT_NAMES[ticker] || ticker;

  // Plans state
  const [plans, setPlans] = useState<Plan[]>([]);
  const [showAddPlan, setShowAddPlan] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [selectedAsset, setSelectedAsset] = useState<{ name: string; ticker: string; asset_type: string } | null>(null);
  const [planAmount, setPlanAmount] = useState('');

  // Allocation plan state
  const [allocations, setAllocations] = useState<Allocation[]>([]);
  const [editingAlloc, setEditingAlloc] = useState(false);
  const [editAllocData, setEditAllocData] = useState<Record<number, number>>({});
  const [showAddAlloc, setShowAddAlloc] = useState(false);
  const [allocSearchQuery, setAllocSearchQuery] = useState('');
  const [allocSearchResults, setAllocSearchResults] = useState<any[]>([]);
  const [allocSearchLoading, setAllocSearchLoading] = useState(false);
  const [allocSelectedAsset, setAllocSelectedAsset] = useState<{ name: string; ticker: string; asset_type: string } | null>(null);
  const [allocPercentage, setAllocPercentage] = useState('');

  // Monthly plan state
  const now = new Date();
  const [selectedMonth, setSelectedMonth] = useState(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`);
  const [monthlyPlan, setMonthlyPlan] = useState<MonthlyPlan | null>(null);
  const [rotationalChoices, setRotationalChoices] = useState<Record<string, string>>({});

  // Análise IA do plano (chama o mesmo motor dos Sinais IA, mas restrito ao plano)
  const [planAnalysis, setPlanAnalysis] = useState<any>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisQuestion, setAnalysisQuestion] = useState('');
  // Tickers que o utilizador rejeitou — persistido localmente e enviado a cada análise
  const [excludedTickers, setExcludedTickers] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem('plan_excluded_tickers') || '[]'); } catch { return []; }
  });
  const persistExcluded = (next: string[]) => {
    setExcludedTickers(next);
    try { localStorage.setItem('plan_excluded_tickers', JSON.stringify(next)); } catch {}
  };

  const loadPlans = useCallback(async () => {
    try { setPlans(await investmentsApi.plans()); } catch {}
  }, []);

  const loadAllocations = useCallback(async () => {
    try { setAllocations(await investmentsApi.allocations()); } catch {}
  }, []);

  const loadMonthlyPlan = useCallback(async (month: string) => {
    try {
      const mp = await investmentsApi.monthlyPlan(month);
      setMonthlyPlan(mp);
      setRotationalChoices(mp.rotational_choices || {});
    } catch {}
  }, []);

  useEffect(() => { loadPlans(); loadAllocations(); }, [loadPlans, loadAllocations]);
  useEffect(() => { loadMonthlyPlan(selectedMonth); }, [selectedMonth, loadMonthlyPlan]);

  // Carregar análise persistida (utilizador não tem de re-gerar)
  useEffect(() => {
    investmentsApi.signalsPlanAnalysisLatest()
      .then(data => { if (data) setPlanAnalysis(data); })
      .catch(() => {});
  }, []);

  const handleAddPlan = async () => {
    if (!selectedAsset) return;
    try {
      await investmentsApi.createPlan({
        name: selectedAsset.name,
        instrument: selectedAsset.ticker,
        asset_type: selectedAsset.asset_type,
        target_amount_eur: planAmount ? parseFloat(planAmount) : undefined,
      });
      setSelectedAsset(null);
      setSearchQuery('');
      setSearchResults([]);
      setPlanAmount('');
      setShowAddPlan(false);
      loadPlans();
    } catch {}
  };

  // Debounced search
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleSearchChange = (value: string) => {
    setSearchQuery(value);
    setSelectedAsset(null);
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    if (value.trim().length < 2) { setSearchResults([]); return; }
    setSearchLoading(true);
    searchTimeoutRef.current = setTimeout(async () => {
      try {
        const results = await investmentsApi.searchAsset(value);
        setSearchResults(results);
      } catch { setSearchResults([]); }
      finally { setSearchLoading(false); }
    }, 350);
  };

  const selectAsset = (asset: any) => {
    setSelectedAsset({ name: asset.name, ticker: asset.ticker, asset_type: asset.asset_type });
    setSearchQuery(asset.name);
    setSearchResults([]);
  };

  // Allocation handlers
  const totalAllocPct = allocations.reduce((s, a) => s + a.percentage, 0);
  const monthlyBudget = monthlyPlan?.budget ?? 300;

  const navigateMonth = (dir: number) => {
    const [y, m] = selectedMonth.split('-').map(Number);
    const d = new Date(y, m - 1 + dir, 1);
    setSelectedMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
  };

  const monthLabel = (() => {
    const [y, m] = selectedMonth.split('-').map(Number);
    const names = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];
    return `${names[m - 1]} ${y}`;
  })();

  const updateBudget = async (val: number) => {
    try {
      const mp = await investmentsApi.updateMonthlyPlan(selectedMonth, { budget: val });
      setMonthlyPlan(mp);
    } catch {}
  };

  const updateRotationalChoice = async (allocId: number, value: string) => {
    const newChoices = { ...rotationalChoices, [String(allocId)]: value };
    setRotationalChoices(newChoices);
    try {
      await investmentsApi.updateMonthlyPlan(selectedMonth, { rotational_choices: newChoices });
    } catch {}
  };

  const startEditAlloc = () => {
    const data: Record<number, number> = {};
    allocations.forEach(a => { data[a.id] = a.percentage; });
    setEditAllocData(data);
    setEditingAlloc(true);
  };

  const saveEditAlloc = async () => {
    try {
      for (const a of allocations) {
        const newPct = editAllocData[a.id];
        if (newPct !== undefined && newPct !== a.percentage) {
          await investmentsApi.updateAllocation(a.id, { percentage: newPct });
        }
      }
      setEditingAlloc(false);
      loadAllocations();
    } catch {}
  };

  const allocSearchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleAllocSearchChange = (value: string) => {
    setAllocSearchQuery(value);
    setAllocSelectedAsset(null);
    if (allocSearchTimeoutRef.current) clearTimeout(allocSearchTimeoutRef.current);
    if (value.trim().length < 2) { setAllocSearchResults([]); return; }
    setAllocSearchLoading(true);
    allocSearchTimeoutRef.current = setTimeout(async () => {
      try {
        const results = await investmentsApi.searchAsset(value);
        setAllocSearchResults(results);
      } catch { setAllocSearchResults([]); }
      finally { setAllocSearchLoading(false); }
    }, 350);
  };

  const selectAllocAsset = (asset: any) => {
    setAllocSelectedAsset({ name: asset.name, ticker: asset.ticker, asset_type: asset.asset_type });
    setAllocSearchQuery(asset.name);
    setAllocSearchResults([]);
  };

  const handleAddAllocation = async () => {
    if (!allocSelectedAsset || !allocPercentage) return;
    try {
      await investmentsApi.createAllocation({
        name: allocSelectedAsset.name,
        ticker: allocSelectedAsset.ticker,
        asset_type: allocSelectedAsset.asset_type,
        percentage: parseFloat(allocPercentage),
        sort_order: allocations.length,
      });
      setAllocSelectedAsset(null);
      setAllocSearchQuery('');
      setAllocSearchResults([]);
      setAllocPercentage('');
      setShowAddAlloc(false);
      loadAllocations();
    } catch {}
  };

  const handleDeleteAllocation = async (id: number) => {
    try { await investmentsApi.deleteAllocation(id); loadAllocations(); } catch {}
  };

  const handleUpdatePlanStatus = async (id: number, status: string) => {
    try { await investmentsApi.updatePlan(id, { status }); loadPlans(); } catch {}
  };

  const handleDeletePlan = async (id: number) => {
    try { await investmentsApi.deletePlan(id); loadPlans(); } catch {}
  };

  const runPlanAnalysis = async (extraExcluded: string[] = []) => {
    setAnalysisLoading(true);
    setAnalysisError(null);
    try {
      const merged = Array.from(new Set([...excludedTickers, ...extraExcluded].map(t => t.toUpperCase())));
      const data = await investmentsApi.signalsAnalyzePlan(analysisQuestion, merged);
      setPlanAnalysis(data);
    } catch (e: any) {
      setAnalysisError(e.message || 'Erro a contactar a IA');
    } finally {
      setAnalysisLoading(false);
    }
  };

  const excludeAndRegen = async (ticker: string) => {
    const t = ticker.toUpperCase();
    if (!excludedTickers.includes(t)) {
      const next = [...excludedTickers, t];
      persistExcluded(next);
    }
    // Remove imediatamente do UI e pede outras
    setPlanAnalysis((prev: any) => prev && Array.isArray(prev.suggestions)
      ? { ...prev, suggestions: prev.suggestions.filter((s: any) => (s.ticker || '').toUpperCase() !== t) }
      : prev);
    await runPlanAnalysis([t]);
  };

  return (
    <div className="space-y-6">
      {/* Plano de Investimento */}
      <div className="bg-[#161616] border border-[#222] rounded-2xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2">
            <PieChart size={16} className="text-blue-400" />
            Plano de Investimento
          </h3>
          <div className="flex items-center gap-2">
            {!editingAlloc ? (
              <>
                <button onClick={() => setShowAddAlloc(!showAddAlloc)} className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 transition-colors">
                  <Plus size={14} /> Adicionar
                </button>
                <button onClick={startEditAlloc} className="flex items-center gap-1 text-xs text-gray-400 hover:text-white transition-colors">
                  <Pencil size={12} /> Editar
                </button>
              </>
            ) : (
              <div className="flex gap-1.5">
                <button onClick={saveEditAlloc} className="flex items-center gap-1 text-xs text-green-400 hover:text-green-300 transition-colors">
                  <Check size={14} /> Guardar
                </button>
                <button onClick={() => setEditingAlloc(false)} className="text-xs text-gray-400 hover:text-white transition-colors">
                  Cancelar
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Month navigator + budget */}
        <div className="flex items-center gap-3 mb-4 p-3 bg-[#1a1a1a] border border-[#333] rounded-xl">
          <div className="flex items-center gap-2">
            <button onClick={() => navigateMonth(-1)} className="p-1 rounded hover:bg-[#333] text-gray-400 hover:text-white transition-colors"><ChevronLeft size={16} /></button>
            <div className="flex items-center gap-1.5 min-w-[140px] justify-center">
              <Calendar size={14} className="text-blue-400" />
              <span className="text-sm font-medium text-white">{monthLabel}</span>
            </div>
            <button onClick={() => navigateMonth(1)} className="p-1 rounded hover:bg-[#333] text-gray-400 hover:text-white transition-colors"><ChevronRight size={16} /></button>
          </div>
          <div className="flex-1 flex items-center gap-2 justify-end">
            <Euro size={14} className="text-purple-400" />
            <input
              type="number"
              value={monthlyBudget}
              onChange={e => { const v = parseFloat(e.target.value) || 0; updateBudget(v); }}
              className="w-20 bg-[#222] border border-[#333] rounded-lg px-2 py-1 text-sm text-white font-mono focus:border-purple-500 focus:outline-none text-right"
            />
            <span className="text-xs text-gray-500">€</span>
            <span className={`text-[10px] font-bold ml-2 ${Math.abs(totalAllocPct - 100) < 0.01 ? 'text-green-400' : 'text-amber-400'}`}>
              {totalAllocPct.toFixed(0)}%
            </span>
          </div>
        </div>

        {/* Add allocation form */}
        {showAddAlloc && (
          <div className="mb-4 p-3 bg-[#1a1a1a] border border-[#333] rounded-xl space-y-3">
            <div className="relative">
              <label className="text-[10px] text-gray-500 mb-1 block">Pesquisar ativo</label>
              <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                <input
                  value={allocSearchQuery}
                  onChange={e => handleAllocSearchChange(e.target.value)}
                  placeholder="ex: VUAA, Bitcoin, Gold..."
                  className="w-full bg-[#222] border border-[#333] rounded-lg pl-9 pr-3 py-2 text-sm text-white placeholder-gray-600 focus:border-blue-500 focus:outline-none"
                  autoFocus
                />
                {allocSearchLoading && <Loader size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-blue-400 animate-spin" />}
              </div>
              {allocSearchResults.length > 0 && !allocSelectedAsset && (
                <div className="absolute z-10 w-full mt-1 bg-[#1c1c1c] border border-[#333] rounded-xl overflow-hidden shadow-xl max-h-48 overflow-y-auto">
                  {allocSearchResults.map((r, i) => (
                    <button key={i} onClick={() => selectAllocAsset(r)} className="w-full flex items-center gap-3 px-3 py-2 hover:bg-[#252525] transition-colors text-left">
                      <div className="flex-1 min-w-0">
                        <span className="text-sm font-medium text-white truncate">{r.name}</span>
                        <span className="text-[10px] text-gray-500 font-mono ml-2">{r.ticker}</span>
                      </div>
                      <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-bold shrink-0 ${
                        r.asset_type === 'etf' ? 'bg-blue-500/20 text-blue-400' : r.asset_type === 'crypto' ? 'bg-teal-500/20 text-teal-400' : 'bg-amber-500/20 text-amber-400'
                      }`}>{r.asset_type === 'etf' ? 'ETF' : r.asset_type === 'crypto' ? 'Crypto' : 'Ação'}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            {allocSelectedAsset && (
              <div className="flex items-center gap-3 p-2 bg-blue-500/10 border border-blue-500/20 rounded-lg">
                <span className="text-sm font-medium text-white flex-1">{allocSelectedAsset.name} <span className="text-[10px] text-gray-400 font-mono">{allocSelectedAsset.ticker}</span></span>
                <button onClick={() => { setAllocSelectedAsset(null); setAllocSearchQuery(''); }} className="text-gray-500 hover:text-white"><X size={14} /></button>
              </div>
            )}
            {allocSelectedAsset && (
              <div>
                <label className="text-[10px] text-gray-500 mb-1 block">Percentagem (%)</label>
                <input type="number" value={allocPercentage} onChange={e => setAllocPercentage(e.target.value)} placeholder="ex: 10" min="1" max="100"
                  className="w-full bg-[#222] border border-[#333] rounded-lg px-3 py-1.5 text-sm text-white placeholder-gray-600 focus:border-blue-500 focus:outline-none"
                />
              </div>
            )}
            <div className="flex gap-2">
              <button onClick={handleAddAllocation} disabled={!allocSelectedAsset || !allocPercentage}
                className={`flex-1 text-white text-xs font-medium py-2 rounded-lg transition-colors ${allocSelectedAsset && allocPercentage ? 'bg-blue-600 hover:bg-blue-500' : 'bg-[#333] text-gray-500 cursor-not-allowed'}`}
              >Adicionar</button>
              <button onClick={() => { setShowAddAlloc(false); setAllocSelectedAsset(null); setAllocSearchQuery(''); setAllocSearchResults([]); setAllocPercentage(''); }}
                className="px-4 bg-[#222] hover:bg-[#333] text-gray-400 text-xs py-2 rounded-lg transition-colors">Cancelar</button>
            </div>
          </div>
        )}

        {/* Allocation table */}
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="text-[10px] text-gray-500 uppercase border-b border-[#222]">
                <th className="text-left py-2 pr-2 w-12">%</th>
                <th className="text-left py-2 px-2">Ativo</th>
                <th className="text-left py-2 px-2 w-16">Tipo</th>
                <th className="text-right py-2 pl-2 w-20">€/mês</th>
                {editingAlloc && <th className="w-8"></th>}
              </tr>
            </thead>
            <tbody>
              {allocations.map(a => (
                <tr key={a.id} className="border-b border-[#1a1a1a] hover:bg-[#1a1a1a] transition-colors">
                  <td className="py-2.5 pr-2">
                    {editingAlloc ? (
                      <input
                        type="number"
                        value={editAllocData[a.id] ?? a.percentage}
                        onChange={e => setEditAllocData(d => ({ ...d, [a.id]: parseFloat(e.target.value) || 0 }))}
                        className="w-12 bg-[#222] border border-[#333] rounded px-1.5 py-0.5 text-xs text-white font-mono focus:border-blue-500 focus:outline-none text-center"
                        min="0" max="100"
                      />
                    ) : (
                      <span className="text-xs text-gray-400 font-mono">{a.percentage}%</span>
                    )}
                  </td>
                  <td className="py-2.5 px-2">
                    {a.is_rotational ? (
                      <div>
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-sm font-medium text-amber-400">{a.name}</span>
                        </div>
                        <RotationalAssetInput
                          value={rotationalChoices[String(a.id)] || ''}
                          onSave={v => updateRotationalChoice(a.id, v)}
                        />
                      </div>
                    ) : (
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-white">{a.name}</span>
                        <span className="text-[9px] text-gray-500 font-mono">{a.ticker}</span>
                      </div>
                    )}
                  </td>
                  <td className="py-2.5 px-2">
                    <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-bold ${
                      a.asset_type === 'etf' ? 'bg-blue-500/20 text-blue-400' :
                      a.asset_type === 'crypto' ? 'bg-teal-500/20 text-teal-400' :
                      'bg-amber-500/20 text-amber-400'
                    }`}>
                      {a.asset_type === 'etf' ? 'ETF' : a.asset_type === 'crypto' ? 'Crypto' : 'Ação'}
                    </span>
                  </td>
                  <td className="py-2.5 pl-2 text-right">
                    <span className="text-sm font-mono text-white">
                      {eur(Math.round((a.percentage / 100) * monthlyBudget * 100) / 100)}
                    </span>
                  </td>
                  {editingAlloc && (
                    <td className="py-2.5 pl-1">
                      <button onClick={() => handleDeleteAllocation(a.id)} className="p-1 rounded text-gray-600 hover:text-red-400 transition-colors"><Trash2 size={12} /></button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-[#333]">
                <td className="py-2.5 pr-2">
                  <span className={`text-xs font-bold font-mono ${Math.abs(totalAllocPct - 100) < 0.01 ? 'text-green-400' : 'text-amber-400'}`}>
                    {editingAlloc ? Object.values(editAllocData).reduce((s, v) => s + v, 0).toFixed(0) : totalAllocPct.toFixed(0)}%
                  </span>
                </td>
                <td className="py-2.5 px-2 text-sm font-semibold text-white" colSpan={2}>Total</td>
                <td className="py-2.5 pl-2 text-right">
                  <span className="text-sm font-mono font-semibold text-white">{eur(monthlyBudget)}</span>
                </td>
                {editingAlloc && <td></td>}
              </tr>
            </tfoot>
          </table>
        </div>

        {Math.abs(totalAllocPct - 100) > 0.01 && (
          <div className="mt-3 flex items-center gap-2 text-xs text-amber-400">
            <AlertTriangle size={14} />
            <span>A alocação total é {totalAllocPct.toFixed(0)}% — deveria ser 100%</span>
          </div>
        )}
      </div>

      {/* Próximos Investimentos */}
      <div className="bg-[#161616] border border-[#222] rounded-2xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2">
            <Target size={16} className="text-purple-400" />
            Próximos Investimentos
          </h3>
          <button
            onClick={() => setShowAddPlan(!showAddPlan)}
            className="flex items-center gap-1 text-xs text-purple-400 hover:text-purple-300 transition-colors"
          >
            <Plus size={14} />
            Adicionar
          </button>
        </div>

        {showAddPlan && (
          <div className="mb-4 p-3 bg-[#1a1a1a] border border-[#333] rounded-xl space-y-3">
            {/* Search input */}
            <div className="relative">
              <label className="text-[10px] text-gray-500 mb-1 block">Pesquisar ativo</label>
              <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                <input
                  value={searchQuery}
                  onChange={e => handleSearchChange(e.target.value)}
                  placeholder="ex: Anthropic, VUAA, Bitcoin..."
                  className="w-full bg-[#222] border border-[#333] rounded-lg pl-9 pr-3 py-2 text-sm text-white placeholder-gray-600 focus:border-purple-500 focus:outline-none"
                  autoFocus
                />
                {searchLoading && <Loader size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-purple-400 animate-spin" />}
              </div>

              {/* Search results dropdown */}
              {searchResults.length > 0 && !selectedAsset && (
                <div className="absolute z-10 w-full mt-1 bg-[#1c1c1c] border border-[#333] rounded-xl overflow-hidden shadow-xl max-h-60 overflow-y-auto">
                  {searchResults.map((r, i) => (
                    <button
                      key={i}
                      onClick={() => selectAsset(r)}
                      className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-[#252525] transition-colors text-left"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-white truncate">{r.name}</span>
                          <span className="text-[10px] text-gray-500 font-mono shrink-0">{r.ticker}</span>
                        </div>
                        <span className="text-[10px] text-gray-600">{r.exchange}</span>
                      </div>
                      <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-bold shrink-0 ${
                        r.asset_type === 'etf' ? 'bg-blue-500/20 text-blue-400' :
                        r.asset_type === 'crypto' ? 'bg-teal-500/20 text-teal-400' :
                        'bg-amber-500/20 text-amber-400'
                      }`}>
                        {r.asset_type === 'etf' ? 'ETF' : r.asset_type === 'crypto' ? 'Crypto' : 'Ação'}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Selected asset info + amount */}
            {selectedAsset && (
              <div className="flex items-center gap-3 p-2 bg-purple-500/10 border border-purple-500/20 rounded-lg">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-white">{selectedAsset.name}</span>
                    <span className="text-[10px] text-gray-400 font-mono">{selectedAsset.ticker}</span>
                    <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-bold ${
                      selectedAsset.asset_type === 'etf' ? 'bg-blue-500/20 text-blue-400' :
                      selectedAsset.asset_type === 'crypto' ? 'bg-teal-500/20 text-teal-400' :
                      'bg-amber-500/20 text-amber-400'
                    }`}>
                      {selectedAsset.asset_type === 'etf' ? 'ETF' : selectedAsset.asset_type === 'crypto' ? 'Crypto' : 'Ação'}
                    </span>
                  </div>
                </div>
                <button onClick={() => { setSelectedAsset(null); setSearchQuery(''); }} className="text-gray-500 hover:text-white">
                  <X size={14} />
                </button>
              </div>
            )}

            {selectedAsset && (
              <div>
                <label className="text-[10px] text-gray-500 mb-1 block">Montante (€)</label>
                <input
                  type="number"
                  value={planAmount}
                  onChange={e => setPlanAmount(e.target.value)}
                  placeholder="ex: 100"
                  className="w-full bg-[#222] border border-[#333] rounded-lg px-3 py-1.5 text-sm text-white placeholder-gray-600 focus:border-purple-500 focus:outline-none"
                />
              </div>
            )}

            <div className="flex gap-2">
              <button
                onClick={handleAddPlan}
                disabled={!selectedAsset}
                className={`flex-1 text-white text-xs font-medium py-2 rounded-lg transition-colors ${
                  selectedAsset ? 'bg-purple-600 hover:bg-purple-500' : 'bg-[#333] text-gray-500 cursor-not-allowed'
                }`}
              >
                Guardar
              </button>
              <button
                onClick={() => { setShowAddPlan(false); setSelectedAsset(null); setSearchQuery(''); setSearchResults([]); setPlanAmount(''); }}
                className="px-4 bg-[#222] hover:bg-[#333] text-gray-400 text-xs py-2 rounded-lg transition-colors"
              >
                Cancelar
              </button>
            </div>
          </div>
        )}

        {plans.length === 0 && !showAddPlan ? (
          <p className="text-gray-500 text-sm text-center py-4">Sem investimentos planeados. Adiciona o primeiro!</p>
        ) : (
          <div className="space-y-2">
            {plans.map(plan => (
              <div
                key={plan.id}
                className={`flex items-center gap-3 p-3 rounded-xl border transition-all ${
                  plan.status === 'bought' ? 'bg-green-500/5 border-green-500/20 opacity-60' :
                  plan.status === 'cancelled' ? 'bg-red-500/5 border-red-500/20 opacity-40' :
                  'bg-[#1a1a1a] border-[#333]'
                }`}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-white">{plan.name || getName(plan.instrument)}</span>
                    <span className="text-[9px] text-gray-500 font-mono">{plan.instrument}</span>
                    <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-bold ${
                      plan.asset_type === 'etf' ? 'bg-blue-500/20 text-blue-400' :
                      plan.asset_type === 'crypto' ? 'bg-teal-500/20 text-teal-400' :
                      'bg-amber-500/20 text-amber-400'
                    }`}>
                      {plan.asset_type === 'etf' ? 'ETF' : plan.asset_type === 'crypto' ? 'Crypto' : 'Ação'}
                    </span>
                    {plan.status !== 'pending' && (
                      <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-bold ${
                        plan.status === 'bought' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                      }`}>
                        {plan.status === 'bought' ? 'Comprado' : 'Cancelado'}
                      </span>
                    )}
                  </div>
                  {plan.target_amount_eur && (
                    <span className="text-[10px] text-gray-400 font-mono mt-0.5 block">{eur(plan.target_amount_eur)}</span>
                  )}
                </div>
                {plan.status === 'pending' ? (
                  <div className="flex items-center gap-1.5 shrink-0">
                    <button onClick={() => handleUpdatePlanStatus(plan.id, 'bought')} className="p-1.5 rounded-lg bg-green-500/10 text-green-400 hover:bg-green-500/20 transition-colors" title="Marcar como comprado"><Check size={12} /></button>
                    <button onClick={() => handleUpdatePlanStatus(plan.id, 'cancelled')} className="p-1.5 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors" title="Cancelar"><X size={12} /></button>
                    <button onClick={() => handleDeletePlan(plan.id)} className="p-1.5 rounded-lg bg-[#222] text-gray-500 hover:text-red-400 hover:bg-red-500/10 transition-colors" title="Apagar"><Trash2 size={12} /></button>
                  </div>
                ) : (
                  <button onClick={() => handleDeletePlan(plan.id)} className="p-1.5 rounded-lg bg-[#222] text-gray-500 hover:text-red-400 hover:bg-red-500/10 transition-colors shrink-0" title="Apagar"><Trash2 size={12} /></button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Análise IA do Plano */}
      <div className="bg-[#161616] border border-[#222] rounded-2xl p-5">
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2">
            <Lightbulb size={16} className="text-amber-400" />
            Análise IA do Plano
          </h3>
          <button
            onClick={() => runPlanAnalysis()}
            disabled={analysisLoading || allocations.length === 0}
            className="px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white text-xs font-medium rounded-lg transition-colors disabled:opacity-50 flex items-center gap-1.5"
          >
            {analysisLoading ? <RefreshCw size={12} className="animate-spin" /> : <Lightbulb size={12} />}
            {analysisLoading ? 'A analisar...' : (planAnalysis ? 'Analisar de novo' : 'Analisar plano')}
          </button>
        </div>
        <p className="text-[11px] text-gray-500 mb-3">
          Mesma IA dos Sinais IA, mas restrita aos {allocations.length} ativos do teu plano. Guardada automaticamente.
        </p>

        {excludedTickers.length > 0 && (
          <div className="mb-3 p-2 bg-[#1a1a1a] border border-[#333] rounded-lg flex items-start gap-2 flex-wrap">
            <span className="text-[10px] text-gray-500 mr-1">Excluídos:</span>
            {excludedTickers.map(t => (
              <span key={t} className="text-[10px] bg-red-900/20 text-red-300 border border-red-900/40 rounded px-1.5 py-0.5 flex items-center gap-1">
                {t}
                <button
                  onClick={() => persistExcluded(excludedTickers.filter(x => x !== t))}
                  className="text-red-400 hover:text-red-200"
                  title={`Remover ${t} da lista de excluídos`}
                >×</button>
              </span>
            ))}
            <button
              onClick={() => persistExcluded([])}
              className="text-[10px] text-gray-500 hover:text-white ml-auto"
            >limpar todos</button>
          </div>
        )}

        <div className="flex gap-2 mb-3">
          <input
            value={analysisQuestion}
            onChange={e => setAnalysisQuestion(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !analysisLoading) runPlanAnalysis(); }}
            placeholder="(opcional) Pergunta extra para a IA..."
            className="flex-1 bg-[#222] border border-[#333] rounded-lg px-3 py-2 text-xs text-white placeholder-gray-600 focus:border-amber-500 focus:outline-none"
          />
        </div>

        {analysisError && (
          <p className="text-xs text-red-400 mb-3">{analysisError}</p>
        )}

        {analysisLoading && !planAnalysis && (
          <div className="flex items-center justify-center py-8">
            <RefreshCw size={20} className="animate-spin text-amber-400 mr-2" />
            <span className="text-sm text-gray-400">A consultar a IA com o teu plano...</span>
          </div>
        )}

        {planAnalysis && (
          <div className="space-y-3">
            {planAnalysis.persisted_at && (
              <p className="text-[10px] text-gray-600">
                Análise guardada em {new Date(planAnalysis.persisted_at).toLocaleString('pt-PT', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
              </p>
            )}
            {(typeof planAnalysis.total_buy_eur === 'number' && typeof planAnalysis.monthly_budget === 'number' && planAnalysis.monthly_budget > 0) && (() => {
              const total = planAnalysis.total_buy_eur as number;
              const budget = planAnalysis.monthly_budget as number;
              const pct = Math.min(100, Math.round(total / budget * 100));
              const over = total > budget;
              return (
                <div className={`text-[11px] px-3 py-2 rounded border flex items-center gap-3 ${over ? 'bg-red-900/20 border-red-800/40 text-red-200' : 'bg-[#1a1a1a] border-[#2a2a2a] text-gray-300'}`}>
                  <span>Se executares todos os <span className="font-mono">buy</span>:</span>
                  <span className="font-mono font-semibold">{total.toFixed(0)}€</span>
                  <span className="text-gray-500">/ {budget.toFixed(0)}€ budget</span>
                  <div className="flex-1 h-1.5 rounded bg-[#222] overflow-hidden">
                    <div className={`h-full ${over ? 'bg-red-500' : pct > 80 ? 'bg-amber-500' : 'bg-green-500'}`} style={{ width: `${pct}%` }} />
                  </div>
                  <span className="font-mono text-xs">{pct}%</span>
                  {over && <span className="text-red-300">⚠ ultrapassa budget</span>}
                </div>
              );
            })()}
            {planAnalysis.headline && (
              <h4 className="text-sm font-medium text-white">{planAnalysis.headline}</h4>
            )}
            {planAnalysis.market_summary && (
              <p className="text-xs text-gray-400 leading-relaxed">{planAnalysis.market_summary}</p>
            )}
            {(() => {
              const all: any[] = Array.isArray(planAnalysis.suggestions) ? planAnalysis.suggestions : [];
              const planSugs = all.filter(s => s.is_plan_asset !== false);
              const newSugs = all
                .filter(s => s.is_plan_asset === false)
                .sort((a, b) => (b.score ?? 0) - (a.score ?? 0));

              const GATE_LABELS: Record<string, string> = {
                rsi_overbought:        'RSI sobrecomprado',
                vol_target_too_small:  'demasiado volátil',
                earnings_too_close:    'earnings perto',
                single_dimension:      'tese mono-dimensional',
                low_confidence:        'confiança baixa',
                budget_exhausted:      'budget esgotado',
                auto_critique_reject:  'risk officer: reject',
              };
              const renderCard = (sug: any, idx: number, opts?: { canReject?: boolean }) => {
                const action = (sug.action || 'watch').toLowerCase();
                const style = action === 'buy'
                  ? { bg: 'bg-green-500/5 border-green-500/30', text: 'text-green-400', label: 'Comprar este mês', tip: 'Reforça este ativo este mês conforme o plano DCA' }
                  : action === 'reduce' || action === 'sell'
                  ? { bg: 'bg-red-500/5 border-red-500/30', text: 'text-red-400', label: 'Reduzir', tip: 'Vender parte da posição existente' }
                  : action === 'hold'
                  ? { bg: 'bg-blue-500/5 border-blue-500/30', text: 'text-blue-400', label: 'Não comprar agora', tip: 'Mantém o que tens mas SALTA o reforço deste mês — vê a tese' }
                  : { bg: 'bg-gray-500/5 border-gray-500/30', text: 'text-gray-400', label: 'Aguardar', tip: 'Não comprar agora — esperar por melhor setup técnico (vê a tese)' };
                // Confidence_pct é a percentagem real calculada (preferida); score é fallback p/ análises antigas.
                const cpct: number | null = typeof sug.confidence_pct === 'number' ? sug.confidence_pct
                  : typeof sug.score === 'number' ? sug.score : null;
                const cpctColor = cpct == null ? 'bg-gray-700/40 text-gray-400 border-gray-600/40'
                  : cpct >= 70 ? 'bg-green-500/20 text-green-300 border-green-500/40'
                  : cpct >= 50 ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                  : 'bg-red-500/20 text-red-300 border-red-500/40';
                const cpctTip = sug.confidence_breakdown
                  ? Object.entries(sug.confidence_breakdown).map(([k, v]) => `${k}: ${v}%`).join(' · ')
                  : `Convicção: ${sug.conviction || '?'}`;
                const gates: { gate: string; reason: string }[] = sug.gates_triggered || [];
                const hasGates = gates.length > 0;
                return (
                  <div key={idx} className={`rounded-lg border p-3 ${style.bg} ${sug.auto_filled ? 'opacity-70' : ''}`}>
                    <div className="flex items-center justify-between gap-2 mb-1.5 flex-wrap">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono text-sm font-semibold text-white">{sug.ticker}</span>
                        <span className="text-xs text-gray-400">{sug.name}</span>
                        <span className="text-[10px] uppercase tracking-wide text-gray-500 px-1.5 py-0.5 bg-black/30 rounded">{sug.asset_type}</span>
                        {sug.auto_filled && (
                          <span className="text-[10px] uppercase tracking-wide text-gray-500 px-1.5 py-0.5 bg-gray-800/40 rounded" title="Sem leitura clara — fallback automático">auto</span>
                        )}
                        {sug.auto_critique && (
                          <span className="text-[10px] uppercase tracking-wide text-purple-300 px-1.5 py-0.5 bg-purple-900/30 border border-purple-800/40 rounded" title="Risk officer corrida automaticamente — confidence baixa">critique</span>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        {cpct != null && (
                          <span
                            className={`text-[11px] font-mono font-bold px-1.5 py-0.5 rounded border ${cpctColor}`}
                            title={cpctTip}
                          >{Math.round(cpct)}%</span>
                        )}
                        {sug.amount_eur != null && sug.amount_eur > 0 && (
                          <span className="text-xs text-white font-medium">{sug.amount_eur.toFixed(0)}€</span>
                        )}
                        <span className={`text-xs font-medium px-2 py-0.5 rounded ${style.text} cursor-help`} title={style.tip}>{style.label}</span>
                      </div>
                    </div>
                    {/* Gates: razão clara para 'buy' → 'watch' */}
                    {hasGates && (
                      <div className="mb-2 px-2 py-1.5 rounded bg-amber-900/20 border border-amber-800/40 text-[11px] text-amber-200 flex flex-wrap items-start gap-2">
                        <AlertTriangle size={11} className="mt-0.5 shrink-0 text-amber-400" />
                        <div className="flex-1 min-w-0">
                          {sug.original_action && sug.original_action !== sug.action && (
                            <div className="font-medium mb-0.5">
                              IA propôs <span className="font-mono uppercase">{sug.original_action}</span> → convertido para <span className="font-mono uppercase">{sug.action}</span>
                            </div>
                          )}
                          {gates.map((g, gi) => (
                            <div key={gi}>
                              <span className="font-medium">{GATE_LABELS[g.gate] || g.gate}:</span> <span className="opacity-80">{g.reason}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {/* Famílias de sinais cruzadas (1 família = mono-dimensional, alerta) */}
                    {Array.isArray(sug.signal_families) && sug.signal_families.length > 0 && (
                      <div className="mb-2 flex flex-wrap items-center gap-1 text-[10px]">
                        <span className="text-gray-500 uppercase tracking-wide">sinais:</span>
                        {sug.signal_families.map((fam: string) => (
                          <span key={fam} className={`px-1.5 py-0.5 rounded border font-mono ${
                            sug.signal_families!.length >= 2
                              ? 'bg-purple-900/20 text-purple-300 border-purple-800/40'
                              : 'bg-gray-800/40 text-gray-400 border-gray-700/40'
                          }`}>{fam}</span>
                        ))}
                        {sug.signal_families.length < 2 && (
                          <span className="text-amber-400 ml-1">⚠ mono-dimensional</span>
                        )}
                      </div>
                    )}
                    {opts?.canReject && (
                      <div className="flex justify-end mb-1">
                        <button
                          onClick={() => excludeAndRegen(sug.ticker)}
                          disabled={analysisLoading}
                          className="text-[10px] px-2 py-0.5 rounded bg-[#1a1a1a] border border-[#333] text-gray-500 hover:text-red-400 hover:border-red-500/40 disabled:opacity-50"
                          title="Marca este ticker como excluído e pede outras sugestões à IA"
                        >
                          👎 outras opções
                        </button>
                      </div>
                    )}
                    {sug.thesis && <p className="text-xs text-gray-300 leading-relaxed mb-2">{sug.thesis}</p>}
                    {(sug.stop_loss_price != null || sug.suggested_amount_eur != null || sug.days_to_earnings != null) && (
                      <div className="flex flex-wrap items-center gap-2 text-[11px] px-2 py-1 bg-black/30 rounded border border-[#222]">
                        {sug.stop_loss_price != null && (
                          <span className="text-gray-400">🛑 stop: <span className="font-mono text-gray-200">{sug.stop_loss_price.toFixed(2)}</span>{sug.stop_loss_pct != null && <span className="text-gray-500"> (-{sug.stop_loss_pct}%)</span>}</span>
                        )}
                        {sug.suggested_amount_eur != null && (
                          <span className={sug.suggested_amount_eur < 25 ? 'text-amber-400' : 'text-gray-400'} title={sug.suggested_amount_eur < 25 ? 'Vol-target abaixo do mínimo investível — posição muito volátil' : 'Tamanho recomendado por vol-targeting (target 15% portfolio vol)'}>
                            📏 vol-target: <span className="font-mono">{sug.suggested_amount_eur.toFixed(0)}€</span>
                          </span>
                        )}
                        {sug.position_after_buy_pct != null && (
                          <span className={sug.max_position_warning ? 'text-red-400' : 'text-gray-500'}>📊 pos depois: <span className="font-mono">{sug.position_after_buy_pct.toFixed(1)}%</span></span>
                        )}
                        {sug.days_to_earnings != null && (
                          <span className={sug.days_to_earnings <= 14 ? 'text-amber-400' : 'text-gray-500'} title={`Próximas earnings: ${sug.next_earnings_date || '?'}`}>
                            📅 earnings em {sug.days_to_earnings}d
                          </span>
                        )}
                      </div>
                    )}
                    {/* Risk officer critique */}
                    {sug.risk_critique && (
                      <details className="mt-2 text-xs">
                        <summary className="cursor-pointer text-purple-400 hover:text-purple-300 flex items-center gap-1">
                          <AlertTriangle size={11} /> Risk officer: {sug.risk_critique.verdict || 'review'}
                        </summary>
                        <div className="mt-1.5 pl-3 border-l-2 border-purple-800/40 space-y-1 text-gray-300">
                          {sug.risk_critique.weaknesses?.map((w: string, wi: number) => (<div key={wi}>· {w}</div>))}
                          {sug.risk_critique.contradicting_evidence?.map((c: string, ci: number) => (<div key={`c${ci}`} className="text-amber-300">⚠ {c}</div>))}
                        </div>
                      </details>
                    )}
                  </div>
                );
              };

              const SECTOR_ORDER = [
                'Tech Mega-cap', 'Semicondutores', 'Software/Cloud',
                'Financeiro', 'Healthcare', 'Consumo', 'Industrial',
                'Energia', 'Utilities', 'Telecom', 'Imobiliário/REIT',
                'ETF Amplo', 'ETF Sectorial', 'Ouro/Commodities', 'Crypto',
                'Outro',
              ];
              const groupBySector = (sggs: any[]): [string, any[]][] => {
                const grouped: Record<string, any[]> = {};
                sggs.forEach(s => {
                  const sec = (s.sector || 'Outro') as string;
                  if (!grouped[sec]) grouped[sec] = [];
                  grouped[sec].push(s);
                });
                return Object.entries(grouped).sort(([a], [b]) => {
                  const ia = SECTOR_ORDER.indexOf(a); const ib = SECTOR_ORDER.indexOf(b);
                  return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
                });
              };
              // Só vale a pena agrupar se tivermos mais que 1 sector (análises antigas sem sector caem todas em "Outro")
              const hasSectorInfo = all.some(s => s.sector);
              const planGrouped = groupBySector(planSugs);
              const ideasGrouped = groupBySector(newSugs);
              const renderGroupHeader = (sector: string, count: number, key: string) => (
                <div key={key} className="text-[10px] uppercase tracking-wider text-purple-400/70 mb-1.5 flex items-center gap-2">
                  <span className="h-px flex-1 bg-purple-900/30" />
                  <span>{sector}</span>
                  <span className="text-gray-600 font-mono">·</span>
                  <span className="text-gray-500">{count}</span>
                  <span className="h-px flex-1 bg-purple-900/30" />
                </div>
              );
              return (
                <>
                  {planSugs.length > 0 && (
                    <div>
                      <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-3">Ativos do plano</h4>
                      {hasSectorInfo ? (
                        <div className="space-y-3">
                          {planGrouped.map(([sector, sggs]) => (
                            <div key={`plan-${sector}`}>
                              {renderGroupHeader(sector, sggs.length, `h-plan-${sector}`)}
                              <div className="grid gap-2">{sggs.map((s, i) => renderCard(s, i))}</div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="grid gap-2">{planSugs.map((s, i) => renderCard(s, i))}</div>
                      )}
                    </div>
                  )}
                  {newSugs.length > 0 && (
                    <div>
                      <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-3 flex items-center gap-2">
                        Novos investimentos sugeridos
                        <span className="text-[10px] normal-case text-gray-600">(fora do plano · alta + média convicção)</span>
                      </h4>
                      {hasSectorInfo ? (
                        <div className="space-y-3">
                          {ideasGrouped.map(([sector, sggs]) => (
                            <div key={`ideas-${sector}`}>
                              {renderGroupHeader(sector, sggs.length, `h-ideas-${sector}`)}
                              <div className="grid gap-2">{sggs.map((s, i) => renderCard(s, planSugs.length + i, { canReject: true }))}</div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="grid gap-2">{newSugs.map((s, i) => renderCard(s, planSugs.length + i, { canReject: true }))}</div>
                      )}
                    </div>
                  )}
                </>
              );
            })()}

            <div className="border-t border-[#222] pt-4 mt-2">
              <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-1 flex items-center gap-2">
                Plano sugerido pela IA
                <span className="text-[10px] normal-case text-gray-600">(editável · podes adotar como plano principal)</span>
              </h4>
              <p className="text-[10px] text-gray-600 mb-3">
                Construído a partir das sugestões "Comprar este mês". Ajusta as % e o budget — os €/mês recalculam-se sozinhos.
              </p>
              <SuggestedPlanTable
                suggestions={Array.isArray(planAnalysis.suggestions) ? planAnalysis.suggestions : []}
                defaultBudget={planAnalysis.monthly_budget || monthlyBudget}
                currentAllocations={allocations}
                onAdopted={() => { loadAllocations(); }}
                eur={eur}
              />
            </div>
          </div>
        )}

        {!planAnalysis && !analysisLoading && !analysisError && (
          <div className="text-center py-6">
            <Lightbulb size={24} className="mx-auto text-gray-600 mb-2" />
            <p className="text-sm text-gray-500">Clica em "Analisar plano"</p>
            <p className="text-xs text-gray-600 mt-1">A IA dá uma recomendação por cada ativo do plano (comprar / manter / observar) com base no estado atual do mercado.</p>
          </div>
        )}
      </div>
    </div>
  );
}


// ── Signals Panel (daily AI suggestions from market news) ─────────

interface RiskCritique {
  ticker: string;
  weaknesses?: string[];
  contradicting_evidence?: string[];
  adjusted_conviction?: string;
  verdict?: string;
}

interface SignalSuggestion {
  ticker: string;
  name: string;
  asset_type: string;
  action: string;          // buy | hold | reduce | watch
  conviction: string;      // high | medium | low
  amount_eur?: number | null;
  thesis: string;
  sector?: string | null;  // Semicondutores, Tech Mega-cap, Energia, ...
  confidence_pct?: number | null;            // 0-99, percentagem real
  confidence_breakdown?: Record<string, number> | null;
  signal_families?: string[];                // técnico, fundamental, sentimento, macro, on-chain, insider
  gates_triggered?: { gate: string; reason: string }[];
  original_action?: string;
  original_amount_eur?: number | null;       // antes de elevar ao mínimo
  original_amount_eur_gate?: number | null;  // antes da gate
  days_to_earnings?: number | null;
  next_earnings_date?: string | null;
  auto_critique?: boolean;
  is_plan_asset?: boolean;  // true → reforço do plano; false → ideia nova
  auto_filled?: boolean;    // true → entrada gerada como fallback (sem leitura clara)
  price_at_generation?: number | null;
  current_price?: number | null;
  pct_since_generation?: number | null;
  last_price_check?: string | null;
  quality_flags?: string[];
  original_conviction?: string;
  // Phase C — risk overlays
  stop_loss_price?: number | null;
  stop_loss_pct?: number | null;
  suggested_amount_eur?: number | null;
  sizing_warning?: string;
  position_after_buy_pct?: number | null;
  max_position_warning?: boolean;
  risk_warnings?: string[];
  risk_critique?: RiskCritique;
}

interface SignalSource {
  title: string;
  url: string;
  source: string;
}

interface Signal {
  id: number;
  generated_at: string;
  headline: string;
  market_summary: string;
  suggestions: SignalSuggestion[];
  sources: SignalSource[];
  model: string;
  cost_usd: number | null;
  quality_summary?: { total: number; counts: Record<string, number> };
  prompt_hash?: string | null;
  prompt_version?: string | null;
  total_buy_eur?: number;
  monthly_budget?: number;
}

interface Alert {
  type: string;          // drawdown, stop_hit, watch_breakout, earnings_soon
  severity: string;      // high, medium, low
  ticker: string;
  signal_id?: number;
  title: string;
  detail: string;
}

type ActionFilter = 'all' | 'buy' | 'hold' | 'reduce' | 'watch';
type ConvictionFilter = 'all' | 'high' | 'medium' | 'low';
type AssetTypeFilter = 'all' | 'etf' | 'crypto' | 'stock';

function SignalsPanel() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [refreshingAll, setRefreshingAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [extraQuestion, setExtraQuestion] = useState('');

  const [actionFilter, setActionFilter] = useState<ActionFilter>('all');
  const [convictionFilter, setConvictionFilter] = useState<ConvictionFilter>('all');
  const [typeFilter, setTypeFilter] = useState<AssetTypeFilter>('all');
  const [feedHealth, setFeedHealth] = useState<{ name: string; ok: boolean | null; count: number; error: string | null }[]>([]);
  const [calibration, setCalibration] = useState<any>(null);
  const [backtest, setBacktest] = useState<any>(null);
  const [calibByContext, setCalibByContext] = useState<any>(null);
  const [calibDecay, setCalibDecay] = useState<any>(null);
  const [showStats, setShowStats] = useState(false);
  const [dataSources, setDataSources] = useState<Record<string, { enabled: boolean; needs_key: string | null }>>({});
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [showAlerts, setShowAlerts] = useState(false);
  const [regime, setRegime] = useState<any>(null);
  const [earningsMomentum, setEarningsMomentum] = useState<any>(null);
  const [sentimentDelta, setSentimentDelta] = useState<any>(null);
  const [funding, setFunding] = useState<any>(null);
  const [regimeHistory, setRegimeHistory] = useState<any[]>([]);
  const [sentimentHistory, setSentimentHistory] = useState<any[]>([]);
  const [fundingHistory, setFundingHistory] = useState<{ btc: any[]; eth: any[] }>({ btc: [], eth: [] });
  const [showContext, setShowContext] = useState(false);
  const [contextLoading, setContextLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const [data, health, calib, bt, sources, alertsRes, reg, ctx, decay] = await Promise.all([
        investmentsApi.signalsList(30),
        investmentsApi.signalsHealth().catch(() => ({ feeds: [] })),
        investmentsApi.signalsCalibration().catch(() => null),
        investmentsApi.signalsBacktest().catch(() => null),
        investmentsApi.signalsDataSources().catch(() => ({})),
        investmentsApi.signalsAlerts().catch(() => ({ alerts: [] })),
        investmentsApi.signalsPreviewRegime().catch(() => null),
        investmentsApi.signalsCalibrationByContext().catch(() => null),
        investmentsApi.signalsCalibrationDecay().catch(() => null),
      ]);
      setSignals(data || []);
      setFeedHealth((health?.feeds) || []);
      setCalibration(calib);
      setBacktest(bt);
      setDataSources(sources || {});
      setAlerts(alertsRes?.alerts || []);
      setRegime(reg);
      setCalibByContext(ctx);
      setCalibDecay(decay);
      if (data && data.length > 0) setExpandedId(data[0].id);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadContext = useCallback(async () => {
    setContextLoading(true);
    try {
      const [em, sd, fund, regHist, sentHist, fundHist] = await Promise.all([
        investmentsApi.signalsPreviewEarningsMomentum().catch(() => null),
        investmentsApi.signalsPreviewSentimentDelta().catch(() => null),
        investmentsApi.signalsPreviewFunding().catch(() => null),
        investmentsApi.signalsHistoryRegime(60).catch(() => ({ history: [] })),
        investmentsApi.signalsHistorySentiment(60).catch(() => ({ history: [] })),
        investmentsApi.signalsHistoryFunding(60).catch(() => ({ btc: [], eth: [] })),
      ]);
      setEarningsMomentum(em);
      setSentimentDelta(sd);
      setFunding(fund);
      setRegimeHistory(regHist?.history || []);
      setSentimentHistory(sentHist?.history || []);
      setFundingHistory({ btc: fundHist?.btc || [], eth: fundHist?.eth || [] });
    } finally {
      setContextLoading(false);
    }
  }, []);

  const toggleContext = () => {
    const next = !showContext;
    setShowContext(next);
    if (next && earningsMomentum === null && sentimentDelta === null && funding === null) {
      loadContext();
    }
  };

  const runCritique = useCallback(async (signalId: number) => {
    try {
      const updated = await investmentsApi.signalsCritique(signalId);
      setSignals(prev => prev.map(s => (s.id === signalId ? updated : s)));
    } catch (e: any) {
      setError(`Critique: ${e.message}`);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const generate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const newSignal = await investmentsApi.signalsGenerate(extraQuestion);
      setSignals(prev => [newSignal, ...prev]);
      setExpandedId(newSignal.id);
      setExtraQuestion('');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setGenerating(false);
    }
  };

  const refreshAll = async () => {
    setRefreshingAll(true);
    try {
      await investmentsApi.signalsRefreshAll();
      const data = await investmentsApi.signalsList(30);
      setSignals(data || []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRefreshingAll(false);
    }
  };

  const refreshOne = async (id: number) => {
    try {
      const updated = await investmentsApi.signalsRefreshPerformance(id);
      setSignals(prev => prev.map(s => (s.id === id ? updated : s)));
    } catch (e: any) {
      setError(e.message);
    }
  };

  const remove = async (id: number) => {
    if (!confirm('Apagar este sinal?')) return;
    try {
      await investmentsApi.signalsDelete(id);
      setSignals(prev => prev.filter(s => s.id !== id));
    } catch (e: any) {
      setError(e.message);
    }
  };

  // Per-suggestion filters
  const filterSuggestion = useCallback((s: SignalSuggestion) => {
    if (actionFilter !== 'all' && s.action !== actionFilter) return false;
    if (convictionFilter !== 'all' && s.conviction !== convictionFilter) return false;
    if (typeFilter !== 'all' && s.asset_type !== typeFilter) return false;
    return true;
  }, [actionFilter, convictionFilter, typeFilter]);

  // Tickers mentioned across recent signals → consistency
  const tickerStreak = useMemo(() => {
    const map: Record<string, number> = {};
    signals.slice(0, 7).forEach(s => {
      const seen = new Set<string>();
      s.suggestions.forEach(sug => {
        const t = (sug.ticker || '').toUpperCase();
        if (t && !seen.has(t)) {
          map[t] = (map[t] || 0) + 1;
          seen.add(t);
        }
      });
    });
    return map;
  }, [signals]);

  const lastSignal = signals[0];
  const hoursSince = lastSignal ? (Date.now() - new Date(lastSignal.generated_at).getTime()) / 3_600_000 : Infinity;
  const isStale = hoursSince > 24;

  const okFeeds = feedHealth.filter(f => f.ok).length;
  const totalFeeds = feedHealth.length;
  const failedFeeds = feedHealth.filter(f => f.ok === false);

  return (
    <div className="space-y-4">
      {/* Header / generate */}
      <div className="bg-[#161616] rounded-xl p-5 border border-[#333]">
        <div className="flex items-start justify-between mb-3 flex-wrap gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <Sparkles size={18} className="text-purple-400" />
              <h2 className="text-base font-semibold text-white">Sinais IA Diários</h2>
              {totalFeeds > 0 && (
                <span
                  className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded ${
                    okFeeds === totalFeeds ? 'bg-green-900/30 text-green-300' :
                    okFeeds > totalFeeds / 2 ? 'bg-amber-900/30 text-amber-300' :
                    'bg-red-900/30 text-red-300'
                  }`}
                  title={failedFeeds.length ? `Falham: ${failedFeeds.map(f => f.name).join(', ')}` : 'Todas as fontes ok'}
                >
                  {okFeeds}/{totalFeeds} feeds
                </span>
              )}
              {Object.keys(dataSources).length > 0 && (() => {
                const enabled = Object.values(dataSources).filter(d => d.enabled).length;
                const total = Object.keys(dataSources).length;
                const missingKeys = Object.entries(dataSources).filter(([_, d]) => !d.enabled && d.needs_key).map(([k]) => k);
                return (
                  <span
                    className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded ${
                      enabled === total ? 'bg-green-900/30 text-green-300' :
                      enabled >= total - 2 ? 'bg-amber-900/30 text-amber-300' :
                      'bg-red-900/30 text-red-300'
                    }`}
                    title={missingKeys.length ? `Faltam keys: ${missingKeys.join(', ')}` : 'Todas as integrações ativas'}
                  >
                    {enabled}/{total} sources
                  </span>
                );
              })()}
              {alerts.length > 0 && (
                <button
                  onClick={() => setShowAlerts(!showAlerts)}
                  className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded flex items-center gap-1 ${
                    alerts.some(a => a.severity === 'high')
                      ? 'bg-red-900/40 text-red-300 border border-red-800/50'
                      : 'bg-amber-900/30 text-amber-300 border border-amber-800/40'
                  }`}
                >
                  <AlertTriangle size={10} /> {alerts.length} alerta{alerts.length === 1 ? '' : 's'}
                </button>
              )}
              {regime?.snapshot?.available && (() => {
                const cls = regime.snapshot.classification as string;
                const p = regime.snapshot.p_risk_off;
                const tone =
                  cls === 'risk-off' ? 'bg-red-900/30 text-red-300 border-red-800/40' :
                  cls === 'risk-on' ? 'bg-green-900/30 text-green-300 border-green-800/40' :
                  'bg-gray-800/40 text-gray-300 border-gray-700/40';
                return (
                  <span
                    className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded border ${tone}`}
                    title={(regime.snapshot.reasoning || []).join(' • ')}
                  >
                    {cls} · P={p?.toFixed(2)}
                  </span>
                );
              })()}
            </div>
            <p className="text-xs text-gray-500">
              Notícias (mercados + Fed/BCE/Treasury + crypto) + dados quant (RSI, SMA, P/E) + sentimento (CNN + crypto F&G) → agente IA.
            </p>
            {lastSignal && (
              <p className="text-xs text-gray-600 mt-1">
                Última: {new Date(lastSignal.generated_at).toLocaleString('pt-PT')}
                {isStale && <span className="text-amber-400 ml-2">• desatualizada</span>}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {signals.length > 0 && (
              <button
                onClick={refreshAll}
                disabled={refreshingAll}
                className="flex items-center gap-1.5 px-3 py-2 bg-[#1a1a1a] hover:bg-[#222] border border-[#333] text-gray-300 rounded-lg text-sm disabled:opacity-50 transition-colors"
                title="Atualizar preços de todas as sugestões antigas"
              >
                {refreshingAll ? <Loader size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                Preços
              </button>
            )}
            <button
              onClick={generate}
              disabled={generating}
              className="flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-500 text-white rounded-lg text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {generating ? <Loader size={16} className="animate-spin" /> : <Sparkles size={16} />}
              {generating ? 'A analisar…' : 'Gerar análise'}
            </button>
          </div>
        </div>
        <input
          type="text"
          value={extraQuestion}
          onChange={e => setExtraQuestion(e.target.value)}
          placeholder="Pergunta opcional (ex: 'foca-te em crypto este mês')"
          className="w-full bg-[#0e0e0e] border border-[#333] rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-purple-500"
          disabled={generating}
        />
        {error && (
          <div className="mt-3 p-3 bg-red-900/20 border border-red-800/40 rounded-lg text-sm text-red-300 flex items-start justify-between gap-2">
            <span>{error}</span>
            <button onClick={() => setError(null)} className="text-red-400 hover:text-red-200"><X size={14} /></button>
          </div>
        )}
        <p className="mt-3 text-[10px] text-gray-600 italic leading-relaxed">
          ⚠️ Estas sugestões não constituem aconselhamento financeiro. Foram geradas por IA com base em dados públicos e estão sujeitas a erros, vieses e omissões. Decisões de investimento são da tua inteira responsabilidade.
        </p>
      </div>

      {/* Alerts panel */}
      {showAlerts && alerts.length > 0 && (
        <AlertsPanel alerts={alerts} onClose={() => setShowAlerts(false)} />
      )}

      {/* Filters + stats toggle */}
      {signals.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <FilterPill label="Ação" value={actionFilter} options={[
            ['all', 'todas'], ['buy', 'comprar'], ['hold', 'manter'], ['reduce', 'reduzir'], ['watch', 'observar'],
          ]} onChange={v => setActionFilter(v as ActionFilter)} />
          <FilterPill label="Convicção" value={convictionFilter} options={[
            ['all', 'todas'], ['high', 'alta'], ['medium', 'média'], ['low', 'baixa'],
          ]} onChange={v => setConvictionFilter(v as ConvictionFilter)} />
          <FilterPill label="Tipo" value={typeFilter} options={[
            ['all', 'todos'], ['etf', 'ETF'], ['stock', 'ações'], ['crypto', 'crypto'],
          ]} onChange={v => setTypeFilter(v as AssetTypeFilter)} />
          <button
            onClick={() => setShowStats(!showStats)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              showStats ? 'bg-purple-900/30 text-purple-300' : 'bg-[#161616] border border-[#333] text-gray-400 hover:text-gray-200'
            }`}
          >
            <BarChart3 size={12} />
            {showStats ? 'Ocultar stats' : 'Ver stats'}
          </button>
          <button
            onClick={toggleContext}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              showContext ? 'bg-purple-900/30 text-purple-300' : 'bg-[#161616] border border-[#333] text-gray-400 hover:text-gray-200'
            }`}
          >
            <Lightbulb size={12} />
            {showContext ? 'Ocultar contexto' : 'Ver contexto'}
          </button>
        </div>
      )}

      {/* Stats panel: calibration + backtest + decay + context attribution */}
      {showStats && (calibration || backtest) && (
        <StatsCards
          calibration={calibration}
          backtest={backtest}
          decay={calibDecay}
          byContext={calibByContext}
        />
      )}

      {/* Context panel: regime + earnings momentum + sentiment delta + funding */}
      {showContext && (
        <ContextPreview
          regime={regime}
          earningsMomentum={earningsMomentum}
          sentimentDelta={sentimentDelta}
          funding={funding}
          regimeHistory={regimeHistory}
          sentimentHistory={sentimentHistory}
          fundingHistory={fundingHistory}
          loading={contextLoading}
        />
      )}

      {/* Signals history */}
      {loading ? (
        <div className="text-center py-12 text-gray-500">
          <Loader size={20} className="mx-auto animate-spin mb-2" />
          A carregar…
        </div>
      ) : signals.length === 0 ? (
        <div className="bg-[#161616] rounded-xl p-12 border border-[#333] text-center">
          <Newspaper size={32} className="mx-auto text-gray-600 mb-3" />
          <p className="text-sm text-gray-400 mb-1">Ainda não há análises</p>
          <p className="text-xs text-gray-600">Clica em "Gerar análise" para a primeira leitura do mercado</p>
        </div>
      ) : (
        <div className="space-y-3">
          {signals.map(s => (
            <SignalCard
              key={s.id}
              signal={s}
              expanded={expandedId === s.id}
              onToggle={() => setExpandedId(expandedId === s.id ? null : s.id)}
              onDelete={() => remove(s.id)}
              onRefresh={() => refreshOne(s.id)}
              onCritique={() => runCritique(s.id)}
              filterSuggestion={filterSuggestion}
              tickerStreak={tickerStreak}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function FilterPill({ label, value, options, onChange }: {
  label: string;
  value: string;
  options: [string, string][];
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center gap-1.5 bg-[#161616] border border-[#333] rounded-lg px-2 py-1">
      <span className="text-[10px] uppercase tracking-wide text-gray-500">{label}</span>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="bg-transparent text-xs text-gray-200 focus:outline-none cursor-pointer"
      >
        {options.map(([v, l]) => (
          <option key={v} value={v} className="bg-[#161616]">{l}</option>
        ))}
      </select>
    </div>
  );
}

const ACTION_STYLE: Record<string, { bg: string; text: string; label: string }> = {
  buy:    { bg: 'bg-green-900/30 border-green-700/40',  text: 'text-green-300',  label: 'Comprar' },
  hold:   { bg: 'bg-blue-900/30 border-blue-700/40',     text: 'text-blue-300',   label: 'Manter' },
  reduce: { bg: 'bg-amber-900/30 border-amber-700/40',   text: 'text-amber-300',  label: 'Reduzir' },
  watch:  { bg: 'bg-gray-900/30 border-gray-700/40',     text: 'text-gray-300',   label: 'Observar' },
};

const CONVICTION_DOTS: Record<string, number> = { low: 1, medium: 2, high: 3 };

function SignalCard({ signal, expanded, onToggle, onDelete, onRefresh, onCritique, filterSuggestion, tickerStreak }: {
  signal: Signal;
  expanded: boolean;
  onToggle: () => void;
  onDelete: () => void;
  onRefresh: () => void;
  onCritique: () => Promise<void>;
  filterSuggestion: (s: SignalSuggestion) => boolean;
  tickerStreak: Record<string, number>;
}) {
  const [adding, setAdding] = useState<number | null>(null);
  const [addedIdx, setAddedIdx] = useState<Set<number>>(new Set());
  const [refreshing, setRefreshing] = useState(false);
  const [critiquing, setCritiquing] = useState(false);
  const hasCritique = signal.suggestions.some(s => s.risk_critique);

  const date = new Date(signal.generated_at);
  const dateStr = date.toLocaleDateString('pt-PT', { day: '2-digit', month: 'short' });
  const timeStr = date.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' });

  const filteredSuggestions = signal.suggestions.filter(filterSuggestion);
  const hiddenCount = signal.suggestions.length - filteredSuggestions.length;
  // Split into "Plano" and "Novas ideias". Legacy signals (sem is_plan_asset definido em nenhuma) caem em "Plano" — comportamento equivalente ao antigo (uma só lista).
  const hasSplitMarker = signal.suggestions.some(s => typeof s.is_plan_asset === 'boolean');
  const planSuggestions = hasSplitMarker ? filteredSuggestions.filter(s => s.is_plan_asset !== false) : filteredSuggestions;
  const newIdeas = hasSplitMarker ? filteredSuggestions.filter(s => s.is_plan_asset === false) : [];

  const handleAddToPlan = async (idx: number, sug: SignalSuggestion) => {
    setAdding(idx);
    try {
      await investmentsApi.createPlan({
        name: sug.name || sug.ticker,
        instrument: sug.ticker,
        asset_type: sug.asset_type,
        target_amount_eur: sug.amount_eur ?? undefined,
      });
      setAddedIdx(prev => new Set(prev).add(idx));
    } catch (e: any) {
      alert(`Erro a adicionar ao plano: ${e.message}`);
    } finally {
      setAdding(null);
    }
  };

  const handleRefresh = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="bg-[#161616] rounded-xl border border-[#333] overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full p-4 flex items-start justify-between gap-3 hover:bg-[#1a1a1a] transition-colors text-left"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <span className="text-xs text-gray-500 font-mono">{dateStr} • {timeStr}</span>
            <span className="text-xs text-gray-600">·</span>
            <span className="text-xs text-purple-400">{signal.suggestions.length} sugestões</span>
            {signal.quality_summary && Object.keys(signal.quality_summary.counts || {}).length > 0 && (
              <span
                className="text-[10px] uppercase tracking-wide bg-amber-900/30 text-amber-300 border border-amber-800/40 px-1.5 py-0.5 rounded flex items-center gap-1"
                title={Object.entries(signal.quality_summary.counts).map(([k, v]) => `${k}: ${v}`).join(' · ')}
              >
                <AlertTriangle size={9} /> {Object.values(signal.quality_summary.counts).reduce((a, b) => a + b, 0)} flag(s)
              </span>
            )}
            {hiddenCount > 0 && (
              <span className="text-[10px] text-gray-600">({hiddenCount} ocultas pelos filtros)</span>
            )}
          </div>
          <h3 className="text-sm font-medium text-white">{signal.headline}</h3>
          {!expanded && signal.market_summary && (
            <p className="text-xs text-gray-500 mt-1 line-clamp-2">{signal.market_summary}</p>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <span
            onClick={handleRefresh}
            className={`p-1.5 rounded hover:bg-[#222] text-gray-500 hover:text-gray-300 cursor-pointer ${refreshing ? 'animate-spin' : ''}`}
            title="Atualizar preços deste sinal"
          >
            <RefreshCw size={14} />
          </span>
          <ChevronDown size={18} className={`text-gray-500 transition-transform ${expanded ? 'rotate-180' : ''}`} />
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-4 border-t border-[#222]">
          {(typeof signal.total_buy_eur === 'number' && typeof signal.monthly_budget === 'number' && signal.monthly_budget > 0) && (() => {
            const total = signal.total_buy_eur as number;
            const budget = signal.monthly_budget as number;
            const pct = Math.min(100, Math.round(total / budget * 100));
            const over = total > budget;
            return (
              <div className={`mt-4 text-[11px] px-3 py-2 rounded border flex items-center gap-3 ${over ? 'bg-red-900/20 border-red-800/40 text-red-200' : 'bg-[#1a1a1a] border-[#2a2a2a] text-gray-300'}`}>
                <span>Soma dos <span className="font-mono">buy</span>:</span>
                <span className="font-mono font-semibold">{total.toFixed(0)}€</span>
                <span className="text-gray-500">/ {budget.toFixed(0)}€ budget</span>
                <div className="flex-1 h-1.5 rounded bg-[#222] overflow-hidden">
                  <div className={`h-full ${over ? 'bg-red-500' : pct > 80 ? 'bg-amber-500' : 'bg-green-500'}`} style={{ width: `${pct}%` }} />
                </div>
                <span className="font-mono text-xs">{pct}%</span>
                {over && <span className="text-red-300">⚠ ultrapassa</span>}
              </div>
            );
          })()}
          {signal.market_summary && (
            <div className="pt-4">
              <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-2">Leitura do mercado</h4>
              <p className="text-sm text-gray-300 leading-relaxed">{signal.market_summary}</p>
            </div>
          )}

          {(() => {
            const renderSugCard = (sug: SignalSuggestion) => {
                  const realIdx = signal.suggestions.indexOf(sug);
                  const style = ACTION_STYLE[sug.action] || ACTION_STYLE.watch;
                  const dots = CONVICTION_DOTS[sug.conviction] || 1;
                  const streak = tickerStreak[sug.ticker?.toUpperCase()] || 0;
                  const pct = sug.pct_since_generation;
                  const isAdded = addedIdx.has(realIdx);

                  return (
                    <div key={realIdx} className={`rounded-lg border p-3 ${style.bg} ${sug.auto_filled ? 'opacity-70' : ''}`}>
                      <div className="flex items-center justify-between gap-2 mb-1.5 flex-wrap">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-mono text-sm font-semibold text-white">{sug.ticker}</span>
                          <span className="text-xs text-gray-400">{sug.name}</span>
                          <span className="text-[10px] uppercase tracking-wide text-gray-500 px-1.5 py-0.5 bg-black/30 rounded">
                            {sug.asset_type}
                          </span>
                          {sug.auto_filled && (
                            <span className="text-[10px] uppercase tracking-wide text-gray-500 px-1.5 py-0.5 bg-gray-800/40 rounded" title="A IA não tinha leitura clara — fallback automático">
                              auto
                            </span>
                          )}
                          {streak >= 3 && (
                            <span
                              className="text-[10px] uppercase tracking-wide text-orange-300 px-1.5 py-0.5 bg-orange-900/30 rounded flex items-center gap-1"
                              title={`Mencionado em ${streak} dos últimos sinais`}
                            >
                              🔥 {streak}×
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2">
                          {sug.confidence_pct != null && (
                            <span
                              className={`text-[11px] font-mono font-bold px-1.5 py-0.5 rounded border ${
                                sug.confidence_pct >= 70 ? 'bg-green-500/20 text-green-300 border-green-500/40'
                                : sug.confidence_pct >= 50 ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                                : 'bg-red-500/20 text-red-300 border-red-500/40'
                              }`}
                              title={sug.confidence_breakdown
                                ? Object.entries(sug.confidence_breakdown).map(([k, v]) => `${k}: ${v}%`).join(' · ')
                                : `Convicção: ${sug.conviction}`}
                            >
                              {Math.round(sug.confidence_pct)}%
                            </span>
                          )}
                          {sug.amount_eur != null && (
                            <span className="text-xs text-white font-medium">{sug.amount_eur.toFixed(0)}€</span>
                          )}
                          <span className={`text-xs font-medium px-2 py-0.5 rounded ${style.text}`}>
                            {style.label}
                          </span>
                          {sug.confidence_pct == null && (
                            <span className="flex gap-0.5" title={`Convicção: ${sug.conviction}`}>
                              {[1, 2, 3].map(n => (
                                <span key={n} className={`w-1.5 h-1.5 rounded-full ${n <= dots ? style.text.replace('text-', 'bg-') : 'bg-gray-700'}`} />
                              ))}
                            </span>
                          )}
                        </div>
                      </div>

                      {sug.quality_flags && sug.quality_flags.length > 0 && (
                        <div className="flex flex-wrap gap-1 mb-2">
                          {sug.quality_flags.map((flag, fi) => {
                            const key = flag.split(':')[0];
                            const meta = FLAG_LABELS[key] || { label: key, tone: 'gray' as const };
                            const detail = flag.includes(':') ? flag.split(':').slice(1).join(':') : '';
                            const cls = meta.tone === 'red'
                              ? 'bg-red-900/40 text-red-300 border-red-800/50'
                              : meta.tone === 'amber'
                              ? 'bg-amber-900/30 text-amber-300 border-amber-800/40'
                              : 'bg-gray-900/40 text-gray-300 border-gray-700/40';
                            return (
                              <span
                                key={fi}
                                className={`text-[10px] px-1.5 py-0.5 rounded border flex items-center gap-1 ${cls}`}
                                title={detail || meta.label}
                              >
                                <AlertTriangle size={9} /> {meta.label}
                                {detail && <span className="opacity-60 font-mono">{detail}</span>}
                              </span>
                            );
                          })}
                          {sug.original_conviction && sug.original_conviction !== sug.conviction && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded border bg-gray-900/40 text-gray-400 border-gray-700/40" title="Convicção foi auto-rebaixada por falta de dados na thesis">
                              ↓ era {sug.original_conviction}
                            </span>
                          )}
                        </div>
                      )}

                      {/* Gates: explica porque um 'buy' foi convertido para 'watch' */}
                      {sug.gates_triggered && sug.gates_triggered.length > 0 && (() => {
                        const GATE_LABELS_LOCAL: Record<string, string> = {
                          rsi_overbought:'RSI sobrecomprado', vol_target_too_small:'demasiado volátil',
                          earnings_too_close:'earnings perto', single_dimension:'tese mono-dimensional',
                          low_confidence:'confiança baixa', budget_exhausted:'budget esgotado',
                          auto_critique_reject:'risk officer: reject',
                        };
                        return (
                          <div className="mb-2 px-2 py-1.5 rounded bg-amber-900/20 border border-amber-800/40 text-[11px] text-amber-200 flex flex-wrap items-start gap-2">
                            <AlertTriangle size={11} className="mt-0.5 shrink-0 text-amber-400" />
                            <div className="flex-1 min-w-0">
                              {sug.original_action && sug.original_action !== sug.action && (
                                <div className="font-medium mb-0.5">
                                  IA propôs <span className="font-mono uppercase">{sug.original_action}</span> → convertido para <span className="font-mono uppercase">{sug.action}</span>
                                </div>
                              )}
                              {sug.gates_triggered.map((g, gi) => (
                                <div key={gi}>
                                  <span className="font-medium">{GATE_LABELS_LOCAL[g.gate] || g.gate}:</span> <span className="opacity-80">{g.reason}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        );
                      })()}

                      {/* Famílias de sinais (técnico+fundamental+sentimento+...) */}
                      {Array.isArray(sug.signal_families) && sug.signal_families.length > 0 && (
                        <div className="mb-2 flex flex-wrap items-center gap-1 text-[10px]">
                          <span className="text-gray-500 uppercase tracking-wide">sinais:</span>
                          {sug.signal_families.map(fam => (
                            <span key={fam} className={`px-1.5 py-0.5 rounded border font-mono ${
                              sug.signal_families!.length >= 2
                                ? 'bg-purple-900/20 text-purple-300 border-purple-800/40'
                                : 'bg-gray-800/40 text-gray-400 border-gray-700/40'
                            }`}>{fam}</span>
                          ))}
                          {sug.signal_families.length < 2 && (
                            <span className="text-amber-400 ml-1">⚠ mono-dimensional</span>
                          )}
                        </div>
                      )}

                      <p className="text-xs text-gray-300 leading-relaxed mb-2">{sug.thesis}</p>

                      {/* Risk overlays — stop-loss, sizing, earnings proximity */}
                      {(sug.stop_loss_price != null || sug.suggested_amount_eur != null || sug.days_to_earnings != null) && (
                        <div className="flex flex-wrap items-center gap-2 text-[11px] mb-2 px-2 py-1.5 bg-black/30 rounded border border-[#222]">
                          {sug.stop_loss_price != null && (
                            <span className="text-gray-400" title="Stop-loss baseado em ATR(14) × 2">
                              🛑 stop: <span className="font-mono text-gray-200">{sug.stop_loss_price.toFixed(2)}</span>
                              {sug.stop_loss_pct != null && <span className="text-gray-500"> (-{sug.stop_loss_pct}%)</span>}
                            </span>
                          )}
                          {sug.suggested_amount_eur != null && (
                            <span
                              className={
                                sug.suggested_amount_eur < 25 ? 'text-red-400'
                                : sug.amount_eur != null && Math.abs((sug.amount_eur - sug.suggested_amount_eur) / sug.suggested_amount_eur) > 0.5 ? 'text-amber-400'
                                : 'text-gray-400'
                              }
                              title={sug.suggested_amount_eur < 25 ? 'Vol-target abaixo do mínimo investível — posição muito volátil para sizar' : 'Tamanho recomendado por vol-targeting (target 15% portfolio vol)'}
                            >
                              📏 vol-target: <span className="font-mono">{sug.suggested_amount_eur.toFixed(0)}€</span>
                            </span>
                          )}
                          {sug.days_to_earnings != null && (
                            <span
                              className={sug.days_to_earnings <= 14 ? 'text-amber-400' : 'text-gray-500'}
                              title={`Próximas earnings: ${sug.next_earnings_date || '?'}`}
                            >
                              📅 earnings em {sug.days_to_earnings}d
                            </span>
                          )}
                          {sug.position_after_buy_pct != null && (
                            <span
                              className={sug.max_position_warning ? 'text-red-400' : 'text-gray-500'}
                              title="% do portfolio se a compra for executada"
                            >
                              📊 pos depois: <span className="font-mono">{sug.position_after_buy_pct.toFixed(1)}%</span>
                            </span>
                          )}
                        </div>
                      )}

                      {/* Risk warnings */}
                      {(sug.risk_warnings && sug.risk_warnings.length > 0) || sug.sizing_warning ? (
                        <ul className="space-y-1 mb-2">
                          {sug.sizing_warning && (
                            <li className="text-[11px] text-amber-300 flex items-start gap-1.5">
                              <AlertTriangle size={10} className="mt-0.5 shrink-0" />
                              <span>{sug.sizing_warning}</span>
                            </li>
                          )}
                          {sug.risk_warnings?.map((w, wi) => (
                            <li key={wi} className="text-[11px] text-amber-300 flex items-start gap-1.5">
                              <AlertTriangle size={10} className="mt-0.5 shrink-0" />
                              <span>{w}</span>
                            </li>
                          ))}
                        </ul>
                      ) : null}

                      {/* Risk officer critique (if run) */}
                      {sug.risk_critique && (
                        <details className="mb-2 text-xs">
                          <summary className="cursor-pointer text-purple-400 hover:text-purple-300 flex items-center gap-1">
                            <AlertTriangle size={11} /> Risk officer: {sug.risk_critique.verdict || 'review'}
                            {sug.risk_critique.adjusted_conviction && sug.risk_critique.adjusted_conviction !== sug.conviction && (
                              <span className="text-amber-300">→ ajusta para {sug.risk_critique.adjusted_conviction}</span>
                            )}
                          </summary>
                          <div className="mt-2 pl-3 border-l-2 border-purple-800/40 space-y-1.5 text-gray-300">
                            {sug.risk_critique.weaknesses && sug.risk_critique.weaknesses.length > 0 && (
                              <div>
                                <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-0.5">Fraquezas</div>
                                <ul className="space-y-0.5">
                                  {sug.risk_critique.weaknesses.map((w, wi) => (<li key={wi}>· {w}</li>))}
                                </ul>
                              </div>
                            )}
                            {sug.risk_critique.contradicting_evidence && sug.risk_critique.contradicting_evidence.length > 0 && (
                              <div>
                                <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-0.5">Evidência contraditória</div>
                                <ul className="space-y-0.5">
                                  {sug.risk_critique.contradicting_evidence.map((c, ci) => (<li key={ci}>· {c}</li>))}
                                </ul>
                              </div>
                            )}
                          </div>
                        </details>
                      )}

                      <div className="flex items-center justify-between gap-2 flex-wrap text-[11px]">
                        <div className="flex items-center gap-3 text-gray-500">
                          {sug.price_at_generation != null && (
                            <span title="Preço quando o sinal foi gerado">
                              entrada: <span className="text-gray-300 font-mono">{sug.price_at_generation.toFixed(2)}</span>
                            </span>
                          )}
                          {sug.current_price != null && (
                            <span title="Preço atual (última atualização)">
                              agora: <span className="text-gray-300 font-mono">{sug.current_price.toFixed(2)}</span>
                            </span>
                          )}
                          {pct != null && (
                            <span
                              className={`font-medium ${
                                pct > 0.5 ? 'text-green-400' : pct < -0.5 ? 'text-red-400' : 'text-gray-500'
                              }`}
                              title="Variação desde a sugestão"
                            >
                              {pct > 0 ? '+' : ''}{pct.toFixed(2)}%
                            </span>
                          )}
                        </div>
                        <button
                          onClick={() => handleAddToPlan(realIdx, sug)}
                          disabled={adding === realIdx || isAdded}
                          className={`flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium transition-colors ${
                            isAdded
                              ? 'bg-green-900/30 text-green-300 cursor-default'
                              : 'bg-purple-900/30 hover:bg-purple-900/50 text-purple-300 disabled:opacity-50'
                          }`}
                          title="Adicionar como plano de investimento"
                        >
                          {adding === realIdx ? <Loader size={11} className="animate-spin" /> : isAdded ? <Check size={11} /> : <Plus size={11} />}
                          {isAdded ? 'no plano' : 'adicionar ao plano'}
                        </button>
                      </div>
                    </div>
                  );
            };
            return (
              <>
                {planSuggestions.length > 0 && (
                  <div>
                    <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-2">
                      {hasSplitMarker ? 'Plano de Investimento' : 'Sugestões'}
                    </h4>
                    <div className="grid gap-2">
                      {planSuggestions.map(sug => renderSugCard(sug))}
                    </div>
                  </div>
                )}
                {newIdeas.length > 0 && (
                  <div>
                    <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-2 flex items-center gap-2">
                      Novas ideias
                      <span className="text-[10px] normal-case text-gray-600">(alta + média convicção)</span>
                    </h4>
                    <div className="grid gap-2">
                      {newIdeas.map(sug => renderSugCard(sug))}
                    </div>
                  </div>
                )}
              </>
            );
          })()}

          {filteredSuggestions.length === 0 && signal.suggestions.length > 0 && (
            <p className="text-xs text-gray-500 italic text-center py-4">Nenhuma sugestão corresponde aos filtros</p>
          )}

          {signal.sources.length > 0 && (
            <details className="text-xs">
              <summary className="cursor-pointer text-gray-500 hover:text-gray-300">
                Fontes consultadas ({signal.sources.length})
              </summary>
              <div className="mt-2 space-y-1 max-h-60 overflow-y-auto pr-1">
                {signal.sources.map((src, i) => (
                  <a
                    key={i}
                    href={src.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-start gap-2 p-2 rounded hover:bg-[#1a1a1a] text-gray-400 hover:text-gray-200"
                  >
                    <ExternalLink size={11} className="mt-0.5 shrink-0" />
                    <span className="flex-1">
                      <span className="text-purple-400">[{src.source}]</span> {src.title}
                    </span>
                  </a>
                ))}
              </div>
            </details>
          )}

          <div className="flex items-center justify-between text-xs text-gray-600 pt-2 border-t border-[#222]">
            <button
              onClick={async () => { setCritiquing(true); try { await onCritique(); } finally { setCritiquing(false); } }}
              disabled={critiquing || hasCritique}
              className="flex items-center gap-1 text-purple-400 hover:text-purple-300 disabled:opacity-50 disabled:cursor-default"
              title={hasCritique ? "Critique já corrida" : "Correr 2ª passagem do agente como risk officer"}
            >
              {critiquing ? <Loader size={11} className="animate-spin" /> : <AlertTriangle size={12} />}
              {hasCritique ? 'critique feita' : critiquing ? 'a criticar…' : 'correr risk officer'}
            </button>
            <button
              onClick={onDelete}
              className="text-red-400 hover:text-red-300 flex items-center gap-1"
            >
              <Trash2 size={12} /> apagar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}


// ── ContextPreview: regime + earnings momentum + sentiment delta + funding ──

function ContextPreview({ regime, earningsMomentum, sentimentDelta, funding, regimeHistory, sentimentHistory, fundingHistory, loading }: {
  regime: any;
  earningsMomentum: any;
  sentimentDelta: any;
  funding: any;
  regimeHistory: any[];
  sentimentHistory: any[];
  fundingHistory: { btc: any[]; eth: any[] };
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="bg-[#161616] rounded-xl p-6 border border-[#333] text-center text-gray-500 text-sm">
        <Loader size={16} className="inline animate-spin mr-2" /> A carregar contexto…
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      <RegimeCard data={regime} history={regimeHistory} />
      <SentimentDeltaCard data={sentimentDelta} history={sentimentHistory} />
      <FundingCard data={funding} history={fundingHistory} />
      <EarningsMomentumCard data={earningsMomentum} />
    </div>
  );
}

function MiniLineChart({ data, dataKey, stroke, refY }: { data: any[]; dataKey: string; stroke: string; refY?: number }) {
  if (!data || data.length < 2) {
    return <div className="text-[10px] text-gray-600 italic">Histórico insuficiente para gráfico (mín. 2d).</div>;
  }
  return (
    <div className="h-20 -mx-1 mt-2">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
          <XAxis dataKey="date" hide />
          <YAxis hide domain={['auto', 'auto']} />
          <Tooltip
            contentStyle={{ background: '#0e0e0e', border: '1px solid #333', borderRadius: 6, fontSize: 11 }}
            labelStyle={{ color: '#888' }}
            formatter={(v: any) => (typeof v === 'number' ? v.toFixed(3) : v)}
          />
          {refY != null && <ReferenceLine y={refY} stroke="#444" strokeDasharray="3 3" />}
          <Line type="monotone" dataKey={dataKey} stroke={stroke} strokeWidth={1.5} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function RegimeCard({ data, history }: { data: any; history: any[] }) {
  const snap = data?.snapshot;
  const available = snap?.available;
  const cls = available ? snap.classification : null;
  const tone =
    cls === 'risk-off' ? 'text-red-400' :
    cls === 'risk-on' ? 'text-green-400' :
    'text-gray-300';
  const stroke =
    cls === 'risk-off' ? '#f87171' :
    cls === 'risk-on' ? '#4ade80' :
    '#a78bfa';
  return (
    <div className="bg-[#161616] border border-[#333] rounded-xl p-4">
      <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
        <Target size={14} className="text-purple-400" /> Regime de mercado
        {history.length > 0 && <span className="text-[10px] text-gray-500 ml-auto">{history.length}d</span>}
      </h3>
      {!available ? (
        <p className="text-xs text-gray-500">Indisponível.</p>
      ) : (
        <>
          <div className="flex items-baseline gap-2 mb-2">
            <span className={`text-2xl font-mono font-semibold ${tone}`}>
              {snap.p_risk_off?.toFixed(2)}
            </span>
            <span className={`text-xs uppercase ${tone}`}>{cls}</span>
            <span className="text-[10px] text-gray-500 ml-auto">P(risk-off)</span>
          </div>
          {snap.p_risk_off_hmm != null && (
            <div className="text-[10px] text-gray-500 mb-2">
              rule={snap.p_risk_off_rule} · HMM={snap.p_risk_off_hmm}
            </div>
          )}
          <MiniLineChart data={history} dataKey="p_risk_off" stroke={stroke} refY={0.5} />
          {snap.reasoning?.length > 0 && (
            <ul className="text-xs text-gray-400 space-y-0.5 mt-2">
              {snap.reasoning.slice(0, 4).map((r: string, i: number) => (
                <li key={i}>• {r}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function SentimentDeltaCard({ data, history }: { data: any; history: any[] }) {
  const d = data?.data;
  const available = d?.available;
  const z = available ? d.z_score : 0;
  const tone = z >= 1.5 ? 'text-green-400' : z <= -1.5 ? 'text-red-400' : 'text-gray-300';
  const arrow = z >= 1.5 ? <TrendingUp size={14} /> : z <= -1.5 ? <TrendingDown size={14} /> : null;
  const stroke = z >= 1.5 ? '#4ade80' : z <= -1.5 ? '#f87171' : '#a78bfa';
  return (
    <div className="bg-[#161616] border border-[#333] rounded-xl p-4">
      <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
        <Newspaper size={14} className="text-purple-400" /> Sentiment delta
        {history.length > 0 && <span className="text-[10px] text-gray-500 ml-auto">{history.length}d</span>}
      </h3>
      {!available ? (
        <p className="text-xs text-gray-500">
          {d?.n_days != null ? `Apenas ${d.n_days}d de histórico (mín. 7d).` : 'Indisponível.'}
        </p>
      ) : (
        <>
          <div className={`text-2xl font-mono font-semibold flex items-center gap-2 ${tone}`}>
            {arrow}{z >= 0 ? '+' : ''}{z.toFixed(2)}
            <span className="text-[10px] text-gray-500 ml-auto">z-score</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 mt-3 text-xs">
            <Metric label="MA7" value={d.ma7 >= 0 ? `+${d.ma7}` : `${d.ma7}`} />
            <Metric label="MA30" value={d.ma30 >= 0 ? `+${d.ma30}` : `${d.ma30}`} />
            <Metric label="delta" value={d.delta >= 0 ? `+${d.delta}` : `${d.delta}`}
              tone={d.delta > 0 ? 'green' : d.delta < 0 ? 'red' : 'gray'} />
          </div>
          <MiniLineChart data={history} dataKey="avg_score" stroke={stroke} refY={0} />
          <div className="text-[10px] text-gray-500 mt-2">{d.interpretation} · {d.n_days}d</div>
        </>
      )}
    </div>
  );
}

function FundingCard({ data, history }: { data: any; history: { btc: any[]; eth: any[] } }) {
  const btc = data?.btc;
  const eth = data?.eth;
  const rows = [['BTC', btc, history.btc, '#f59e0b'], ['ETH', eth, history.eth, '#60a5fa']] as const;
  return (
    <div className="bg-[#161616] border border-[#333] rounded-xl p-4">
      <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
        <Coins size={14} className="text-purple-400" /> Funding persistence
      </h3>
      <div className="space-y-3">
        {rows.map(([sym, p, hist, color]) => {
          if (!p?.available) {
            return (
              <div key={sym} className="text-xs text-gray-500 flex justify-between">
                <span>{sym}</span>
                <span>{p?.n_days != null ? `${p.n_days}d (mín 3d)` : 'sem dados'}</span>
              </div>
            );
          }
          const sig = p.signal;
          const tone =
            sig === 'contrarian_short' ? 'text-amber-400' :
            sig === 'contrarian_long' ? 'text-amber-400' :
            'text-gray-300';
          return (
            <div key={sym}>
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <span className="text-gray-300 font-medium">{sym}</span>
                  <span className={`font-mono ${tone}`}>{p.current_pct >= 0 ? '+' : ''}{p.current_pct}% anual</span>
                </div>
                <div className="flex items-center gap-2 text-[10px]">
                  <span className="text-gray-500">{p.consecutive_extreme_days}d {p.direction.replace('_', ' ')}</span>
                  {sig !== 'neutral' && (
                    <span className={`px-1.5 py-0.5 rounded bg-amber-900/30 text-amber-300 border border-amber-800/40`}>
                      {sig.replace('contrarian_', 'squeeze ')}
                    </span>
                  )}
                </div>
              </div>
              <MiniLineChart data={hist} dataKey="rate_pct" stroke={color} refY={0} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function EarningsMomentumCard({ data }: { data: any }) {
  const enabled = data?.enabled;
  const map: Record<string, any> = data?.data || {};
  const interesting = Object.entries(map).filter(([_, v]: any) =>
    v?.signal && !['no_data', 'neutral'].includes(v.signal)
  );
  return (
    <div className="bg-[#161616] border border-[#333] rounded-xl p-4">
      <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
        <BarChart3 size={14} className="text-purple-400" /> Earnings momentum (PEAD)
      </h3>
      {!enabled ? (
        <p className="text-xs text-gray-500">Finnhub key não configurada.</p>
      ) : interesting.length === 0 ? (
        <p className="text-xs text-gray-500">Sem padrões fortes nos tickers.</p>
      ) : (
        <ul className="space-y-1.5 text-xs">
          {interesting.map(([t, v]: any) => {
            const sig = v.signal;
            const tone =
              sig === 'strong_momentum' ? 'text-green-400' :
              sig === 'positive_drift' ? 'text-green-300' :
              sig === 'declining' ? 'text-red-400' : 'text-gray-300';
            return (
              <li key={t} className="flex items-center justify-between">
                <span className="text-gray-300 font-medium">{t}</span>
                <span className="text-gray-500">
                  {v.consecutive_beats} beats · {v.avg_surprise_pct_4q != null
                    ? `surprise ${v.avg_surprise_pct_4q >= 0 ? '+' : ''}${v.avg_surprise_pct_4q}%`
                    : '—'}
                </span>
                <span className={`text-[10px] uppercase ${tone}`}>{sig}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}


// ── StatsCards: calibration + backtest dashboards ────────────────

const FLAG_LABELS: Record<string, { label: string; tone: 'red' | 'amber' | 'gray' }> = {
  ticker_invalid:        { label: 'ticker inválido',          tone: 'red' },
  unverified_numbers:    { label: 'números não verificados',  tone: 'amber' },
  contradiction:         { label: 'tese contraditória',       tone: 'red' },
  weak_conviction:       { label: 'convicção sem dados',      tone: 'amber' },
  amount_over_budget:    { label: 'acima do budget mensal',   tone: 'amber' },
};

function StatsCards({ calibration, backtest, decay, byContext }: {
  calibration: any;
  backtest: any;
  decay: any;
  byContext: any;
}) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      <CalibrationCard data={calibration} />
      <BacktestCard data={backtest} />
      <DecayCard data={decay} />
      <ContextAttributionCard data={byContext} />
    </div>
  );
}

function DecayCard({ data }: { data: any }) {
  if (!data || data.sample_size === 0 || !data.by_horizon) {
    return (
      <div className="bg-[#161616] border border-[#333] rounded-xl p-4">
        <h3 className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
          <TrendingDown size={14} className="text-purple-400" /> Decay analysis
        </h3>
        <p className="text-xs text-gray-500">{data?.message || 'Sem dados ainda.'}</p>
      </div>
    );
  }
  const horizons = ['7d', '14d', '30d', '60d'] as const;
  const chartData = horizons
    .map(h => {
      const v = data.by_horizon[h];
      return v && v.n > 0 ? { horizon: h, avg: v.avg_return_pct, hit: v.hit_rate_pct, n: v.n } : null;
    })
    .filter(Boolean) as { horizon: string; avg: number; hit: number; n: number }[];
  return (
    <div className="bg-[#161616] border border-[#333] rounded-xl p-4">
      <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
        <TrendingDown size={14} className="text-purple-400" /> Decay analysis
        <span className="text-xs text-gray-500 font-normal">N={data.sample_size}</span>
      </h3>
      {chartData.length < 2 ? (
        <p className="text-xs text-gray-500">Sinais demasiado recentes — precisa de pelo menos 2 horizons com dados.</p>
      ) : (
        <>
          <div className="h-32 -mx-1">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 4, right: 8, left: 4, bottom: 16 }}>
                <XAxis dataKey="horizon" tick={{ fill: '#666', fontSize: 11 }} axisLine={{ stroke: '#333' }} />
                <YAxis tick={{ fill: '#666', fontSize: 11 }} axisLine={{ stroke: '#333' }} domain={['auto', 'auto']} />
                <Tooltip
                  contentStyle={{ background: '#0e0e0e', border: '1px solid #333', borderRadius: 6, fontSize: 11 }}
                  labelStyle={{ color: '#888' }}
                  formatter={(v: any, n: any) => [n === 'avg' ? `${v}%` : v, n === 'avg' ? 'avg return' : 'n']}
                />
                <ReferenceLine y={0} stroke="#444" strokeDasharray="3 3" />
                <Line type="monotone" dataKey="avg" stroke="#a78bfa" strokeWidth={1.8} dot={{ r: 3, fill: '#a78bfa' }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-1 mt-2 text-[10px]">
            {horizons.map(h => {
              const v = data.by_horizon[h];
              if (!v || v.n === 0) {
                return (
                  <div key={h} className="text-center bg-[#0e0e0e] rounded px-1 py-1.5 border border-[#222]">
                    <div className="text-gray-500 uppercase">{h}</div>
                    <div className="text-gray-600">—</div>
                  </div>
                );
              }
              const tone = v.avg_return_pct > 0 ? 'text-green-400' : 'text-red-400';
              return (
                <div key={h} className="text-center bg-[#0e0e0e] rounded px-1 py-1.5 border border-[#222]">
                  <div className="text-gray-500 uppercase">{h}</div>
                  <div className={`font-mono font-semibold ${tone}`}>
                    {v.avg_return_pct >= 0 ? '+' : ''}{v.avg_return_pct}%
                  </div>
                  <div className="text-gray-500">hit {v.hit_rate_pct}% · n={v.n}</div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function ContextAttributionCard({ data }: { data: any }) {
  if (!data || data.sample_size === 0) {
    return (
      <div className="bg-[#161616] border border-[#333] rounded-xl p-4">
        <h3 className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
          <Target size={14} className="text-purple-400" /> Atribuição por contexto
        </h3>
        <p className="text-xs text-gray-500">{data?.message || 'Sem dados ainda.'}</p>
      </div>
    );
  }
  const sections: [string, string, Record<string, any>][] = [
    ['Regime', 'by_regime', data.by_regime || {}],
    ['Sentiment', 'by_sentiment', data.by_sentiment || {}],
    ['Funding BTC', 'by_funding', data.by_funding || {}],
  ];
  return (
    <div className="bg-[#161616] border border-[#333] rounded-xl p-4">
      <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
        <Target size={14} className="text-purple-400" /> Atribuição por contexto
        <span className="text-xs text-gray-500 font-normal">N={data.sample_size}</span>
      </h3>
      <div className="space-y-3">
        {sections.map(([label, _key, buckets]) => {
          const entries = Object.entries(buckets).filter(([k]) => k !== 'no_data');
          if (entries.length === 0) {
            return (
              <div key={label} className="text-xs">
                <div className="text-gray-500 uppercase tracking-wide text-[10px] mb-1">{label}</div>
                <div className="text-gray-600 italic">sem dados ainda</div>
              </div>
            );
          }
          return (
            <div key={label} className="text-xs">
              <div className="text-gray-500 uppercase tracking-wide text-[10px] mb-1">{label}</div>
              {entries.map(([bucket, v]: any) => {
                const tone =
                  v.avg_return_pct > 0 ? 'text-green-400' :
                  v.avg_return_pct < 0 ? 'text-red-400' : 'text-gray-300';
                return (
                  <div key={bucket} className="flex justify-between gap-2 py-0.5">
                    <span className="text-gray-300 capitalize">{bucket.replace(/_/g, ' ')}</span>
                    <span className="text-gray-500">n={v.n}</span>
                    <span className="text-gray-500">hit {v.hit_rate_pct ?? '?'}%</span>
                    <span className={`font-mono font-semibold ${tone}`}>
                      {v.avg_return_pct != null ? `${v.avg_return_pct >= 0 ? '+' : ''}${v.avg_return_pct}%` : '?'}
                    </span>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CalibrationCard({ data }: { data: any }) {
  if (!data || data.sample_size === 0) {
    return (
      <div className="bg-[#161616] border border-[#333] rounded-xl p-4">
        <h3 className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
          <Target size={14} className="text-purple-400" /> Calibração
        </h3>
        <p className="text-xs text-gray-500">{data?.message || 'Dados insuficientes para calibrar.'}</p>
      </div>
    );
  }
  const o = data.overall;
  const brier = data.brier_score;
  const brierTone = brier == null ? 'gray' : brier < 0.15 ? 'green' : brier < 0.20 ? 'amber' : 'red';
  return (
    <div className="bg-[#161616] border border-[#333] rounded-xl p-4">
      <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
        <Target size={14} className="text-purple-400" /> Calibração
        <span className="text-xs text-gray-500 font-normal">N={data.sample_size}</span>
      </h3>
      <div className="grid grid-cols-2 gap-2 mb-3">
        <Metric label="hit rate" value={`${o.hit_rate_pct ?? '?'}%`} />
        <Metric label="retorno médio" value={o.avg_return_pct != null ? `${o.avg_return_pct > 0 ? '+' : ''}${o.avg_return_pct}%` : '?'}
          tone={(o.avg_return_pct ?? 0) > 0 ? 'green' : 'red'} />
        <Metric label="winner médio" value={o.avg_winner_pct != null ? `+${o.avg_winner_pct}%` : '?'} tone="green" />
        <Metric label="loser médio" value={o.avg_loser_pct != null ? `${o.avg_loser_pct}%` : '?'} tone="red" />
      </div>
      {brier != null && (
        <div className="mb-3 flex items-center justify-between text-xs px-3 py-2 rounded bg-[#0e0e0e] border border-[#222]">
          <span className="text-gray-400">Brier score (mais baixo = mais calibrado)</span>
          <span className={`font-mono font-semibold ${
            brierTone === 'green' ? 'text-green-400' :
            brierTone === 'amber' ? 'text-amber-400' :
            brierTone === 'red' ? 'text-red-400' : 'text-gray-300'
          }`}>{brier.toFixed(3)}</span>
        </div>
      )}
      <div className="space-y-1.5 text-xs">
        <div className="text-gray-500 uppercase tracking-wide text-[10px]">por convicção (esperado vs real)</div>
        {(['high', 'medium', 'low'] as const).map(c => {
          const v = data.by_conviction?.[c];
          if (!v) return null;
          const gap = v.calibration_gap_pct;
          const tone = gap >= -5 ? 'text-green-400' : gap >= -15 ? 'text-amber-400' : 'text-red-400';
          return (
            <div key={c} className="flex items-center justify-between gap-2">
              <span className="text-gray-300 capitalize">{c}</span>
              <span className="text-gray-500">esperado <span className="font-mono">{v.expected_hit_rate_pct}%</span></span>
              <span className={`font-mono font-semibold ${tone}`}>real {v.actual_hit_rate_pct}%</span>
              <span className={`text-[10px] ${tone}`}>({gap > 0 ? '+' : ''}{gap}pp)</span>
            </div>
          );
        })}
      </div>
      {data.flag_impact && data.flag_impact.flagged_n > 0 && (
        <div className="mt-3 pt-3 border-t border-[#222] text-xs">
          <div className="text-gray-500 uppercase tracking-wide text-[10px] mb-1">impacto dos flags</div>
          <div className="flex justify-between text-gray-400">
            <span>com flags ({data.flag_impact.flagged_n}): <span className="text-gray-200">{data.flag_impact.flagged_hit_rate_pct ?? '?'}%</span></span>
            <span>sem flags ({data.flag_impact.unflagged_n}): <span className="text-gray-200">{data.flag_impact.unflagged_hit_rate_pct ?? '?'}%</span></span>
          </div>
        </div>
      )}
    </div>
  );
}

function BacktestCard({ data }: { data: any }) {
  if (!data || data.sample_size === 0) {
    return (
      <div className="bg-[#161616] border border-[#333] rounded-xl p-4">
        <h3 className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
          <BarChart3 size={14} className="text-purple-400" /> Backtest vs SPY
        </h3>
        <p className="text-xs text-gray-500">{data?.message || 'Sem dados suficientes.'}</p>
      </div>
    );
  }
  const hitTone = data.hit_rate_vs_spy_pct >= 55 ? 'green' : data.hit_rate_vs_spy_pct >= 45 ? 'amber' : 'red';
  const alphaTone = data.avg_alpha_pct > 0 ? 'green' : data.avg_alpha_pct < 0 ? 'red' : 'gray';
  return (
    <div className="bg-[#161616] border border-[#333] rounded-xl p-4">
      <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
        <BarChart3 size={14} className="text-purple-400" /> Backtest vs SPY
        <span className="text-xs text-gray-500 font-normal">N={data.sample_size}</span>
      </h3>
      <div className="grid grid-cols-2 gap-2 mb-3">
        <Metric
          label="bate SPY"
          value={`${data.hit_rate_vs_spy_pct}%`}
          tone={hitTone}
          hint=">50% = supera benchmark"
        />
        <Metric
          label="alpha médio"
          value={`${data.avg_alpha_pct > 0 ? '+' : ''}${data.avg_alpha_pct}%`}
          tone={alphaTone}
          hint="vs SPY same period"
        />
      </div>
      <div className="space-y-1.5 text-xs">
        <div className="text-gray-500 uppercase tracking-wide text-[10px]">por convicção</div>
        {(['high', 'medium', 'low'] as const).map(c => {
          const v = data.by_conviction?.[c];
          if (!v) return null;
          return (
            <div key={c} className="flex items-center justify-between text-gray-300">
              <span className="capitalize">{c} <span className="text-gray-600">({v.n})</span></span>
              <span className="font-mono text-gray-300">bate SPY <span className="text-white">{v.beat_spy_pct}%</span></span>
              <span className={`font-mono ${v.avg_alpha_pct > 0 ? 'text-green-400' : 'text-red-400'}`}>
                α {v.avg_alpha_pct > 0 ? '+' : ''}{v.avg_alpha_pct}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const ALERT_TYPE_META: Record<string, { icon: any; label: string }> = {
  drawdown:        { icon: TrendingDown, label: 'Drawdown' },
  stop_hit:        { icon: AlertTriangle, label: 'Stop atingido' },
  watch_breakout:  { icon: TrendingUp, label: 'Watch disparou' },
  earnings_soon:   { icon: Calendar, label: 'Earnings próximo' },
  flag_pending:    { icon: AlertTriangle, label: 'Quality flag' },
};

function AlertsPanel({ alerts, onClose }: { alerts: Alert[]; onClose: () => void }) {
  return (
    <div className="bg-[#161616] border border-amber-800/40 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-amber-300 flex items-center gap-2">
          <AlertTriangle size={14} /> Alertas ({alerts.length})
        </h3>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-300">
          <X size={14} />
        </button>
      </div>
      <div className="space-y-2">
        {alerts.map((a, i) => {
          const meta = ALERT_TYPE_META[a.type] || { icon: AlertTriangle, label: a.type };
          const Icon = meta.icon;
          const sev = a.severity === 'high'
            ? 'border-red-800/50 bg-red-900/20 text-red-300'
            : 'border-amber-800/40 bg-amber-900/20 text-amber-300';
          return (
            <div key={i} className={`flex items-start gap-3 p-3 rounded-lg border ${sev}`}>
              <Icon size={16} className="shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-sm font-semibold text-white">{a.ticker}</span>
                  <span className="text-[10px] uppercase tracking-wide opacity-70">{meta.label}</span>
                </div>
                <p className="text-sm text-gray-200 mt-0.5">{a.title}</p>
                <p className="text-xs text-gray-500 mt-0.5">{a.detail}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Metric({ label, value, tone = 'gray', hint }: { label: string; value: string; tone?: 'green' | 'red' | 'amber' | 'gray'; hint?: string }) {
  const color = tone === 'green' ? 'text-green-400' : tone === 'red' ? 'text-red-400' : tone === 'amber' ? 'text-amber-400' : 'text-gray-200';
  return (
    <div className="bg-[#0e0e0e] border border-[#222] rounded-lg px-3 py-2" title={hint}>
      <div className="text-[10px] uppercase tracking-wide text-gray-500">{label}</div>
      <div className={`text-base font-semibold font-mono ${color}`}>{value}</div>
    </div>
  );
}
