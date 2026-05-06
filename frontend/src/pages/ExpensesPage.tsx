import { useState, useEffect } from 'react';
import { format, startOfMonth, endOfMonth, subMonths, getDaysInMonth, isSameMonth } from 'date-fns';
import { pt } from 'date-fns/locale';
import { Plus, X, Upload, Trash2, ChevronLeft, ChevronRight, Receipt, FileSpreadsheet, FileText, Globe, Sparkles, Pencil, Shield, CreditCard, AlertTriangle } from 'lucide-react';
import { PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip } from 'recharts';
import { expensesApi, budgetsApi, dashboardApi } from '../api';
import { Expense, ExpenseCreate, ExpenseSummary, EXPENSE_CATEGORIES } from '../types';

export default function ExpensesPage() {
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [summary, setSummary] = useState<ExpenseSummary[]>([]);
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [showModal, setShowModal] = useState(false);
  const [editingExpense, setEditingExpense] = useState<Expense | null>(null);
  const [csvImporting, setCsvImporting] = useState(false);
  const [pdfImporting, setPdfImporting] = useState(false);
  const [recategorizing, setRecategorizing] = useState(false);
  const [importResult, setImportResult] = useState<{ imported: number; skipped: number; errors: string[]; total_parsed?: number } | null>(null);
  const [income, setIncome] = useState(1040.98);
  const [editingIncome, setEditingIncome] = useState(false);
  const [incomeInput, setIncomeInput] = useState('');

  // Budget & Subscriptions
  const [budgetStatus, setBudgetStatus] = useState<any>(null);
  const [subscriptions, setSubscriptions] = useState<any[]>([]);
  const [subsSummary, setSubsSummary] = useState<any>(null);
  const [showSubModal, setShowSubModal] = useState(false);
  const [editingSub, setEditingSub] = useState<any>(null);
  const [showBudgetSetup, setShowBudgetSetup] = useState(false);
  const [budgetForm, setBudgetForm] = useState({ category: '', monthly_limit: 0 });
  const [subForm, setSubForm] = useState({ name: '', amount: 0, currency: 'EUR', billing_cycle: 'monthly', next_renewal: '', category: 'subscriptions', notes: '' });

  // Weekday spending correlation
  const [weekdaySpending, setWeekdaySpending] = useState<any[] | null>(null);

  const [form, setForm] = useState<ExpenseCreate>({
    description: '',
    amount: 0,
    category: 'other',
    date: format(new Date(), 'yyyy-MM-dd'),
    notes: '',
  });

  useEffect(() => { loadData(); }, [currentMonth]);

  async function loadData() {
    const start = format(startOfMonth(currentMonth), 'yyyy-MM-dd');
    const end = format(endOfMonth(currentMonth), 'yyyy-MM-dd');
    const month = currentMonth.getMonth() + 1;
    const year = currentMonth.getFullYear();

    const [expData, sumData, incData, budgetData, subsData, subsSumData] = await Promise.all([
      expensesApi.list({ start_date: start, end_date: end }),
      expensesApi.summary({ month, year }),
      expensesApi.getIncome(month, year),
      budgetsApi.status(month, year).catch(() => null),
      budgetsApi.subscriptions().catch(() => []),
      budgetsApi.subscriptionsSummary().catch(() => null),
    ]);
    setExpenses(expData);
    setSummary(sumData);
    setIncome(incData.amount);
    setBudgetStatus(budgetData);
    setSubscriptions(subsData);
    setSubsSummary(subsSumData);

    // Load weekday spending correlations
    dashboardApi.correlations().then(corr => {
      if (corr?.expenses_by_weekday) setWeekdaySpending(corr.expenses_by_weekday);
    }).catch(() => null);
  }

  function openNew() {
    setEditingExpense(null);
    setForm({ description: '', amount: 0, category: 'other', date: format(new Date(), 'yyyy-MM-dd'), notes: '' });
    setShowModal(true);
  }

  function openEdit(exp: Expense) {
    setEditingExpense(exp);
    setForm({ description: exp.description, amount: exp.amount, category: exp.category, date: exp.date, notes: exp.notes });
    setShowModal(true);
  }

  async function handleSave() {
    if (!form.description.trim() || form.amount <= 0) return;
    if (editingExpense) {
      await expensesApi.update(editingExpense.id, form);
    } else {
      await expensesApi.create(form);
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

  const totalMonth = expenses.reduce((sum, e) => sum + e.amount, 0);
  const remaining = income - totalMonth;
  const COLORS = ['#3B82F6', '#8B5CF6', '#EF4444', '#F59E0B', '#10B981', '#EC4899', '#6366F1', '#14B8A6', '#6B7280'];

  const pieData = summary.map(s => ({
    name: EXPENSE_CATEGORIES.find(c => c.value === s.category)?.label || s.category,
    value: s.total,
  }));

  const getCategoryInfo = (cat: string) => EXPENSE_CATEGORIES.find(c => c.value === cat) || { label: cat, emoji: '📦' };

  async function saveBudgetLimit() {
    if (!budgetForm.category || budgetForm.monthly_limit <= 0) return;
    await budgetsApi.createLimit({ category: budgetForm.category, monthly_limit: budgetForm.monthly_limit });
    setBudgetForm({ category: '', monthly_limit: 0 });
    setShowBudgetSetup(false);
    loadData();
  }

  async function deleteBudgetLimit(id: number) {
    await budgetsApi.deleteLimit(id);
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
    <div>
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6 lg:mb-8">
        <div>
          <h2 className="text-2xl font-bold">Gastos</h2>
          <p className="text-gray-500 text-sm mt-1 capitalize">{format(currentMonth, "MMMM 'de' yyyy", { locale: pt })}</p>
        </div>
        <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
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
          <label className="flex items-center gap-2 px-3 sm:px-4 py-2 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm font-medium cursor-pointer border border-[#333]">
            <FileSpreadsheet size={16} /> <span className="hidden sm:inline">{csvImporting ? 'A importar...' : 'CSV'}</span>
            <input type="file" className="hidden" accept=".csv"
              onChange={e => { const f = e.target.files?.[0]; if (f) handleCSVImport(f); e.target.value = ''; }}
              disabled={csvImporting} />
          </label>
          <label className="flex items-center gap-2 px-3 sm:px-4 py-2 bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 rounded-xl text-sm font-medium cursor-pointer border border-blue-500/30">
            <FileText size={16} /> <span className="hidden sm:inline">{pdfImporting ? 'A importar...' : 'Revolut PDF'}</span><span className="sm:hidden">PDF</span>
            <input type="file" className="hidden" accept=".pdf"
              onChange={e => { const f = e.target.files?.[0]; if (f) handlePDFImport(f); e.target.value = ''; }}
              disabled={pdfImporting} />
          </label>
          <button onClick={handleRecategorize} disabled={recategorizing || expenses.length === 0}
            className="flex items-center gap-2 px-3 sm:px-4 py-2 bg-purple-600/20 hover:bg-purple-600/30 text-purple-400 rounded-xl text-sm font-medium border border-purple-500/30 disabled:opacity-50">
            <Sparkles size={16} /> <span className="hidden sm:inline">{recategorizing ? 'A categorizar...' : 'IA'}</span><span className="sm:hidden">IA</span>
          </button>
          <button onClick={openNew}
            className="flex items-center gap-2 px-3 sm:px-4 py-2 bg-green-600 hover:bg-green-700 rounded-xl text-sm font-medium">
            <Plus size={16} /> <span className="hidden sm:inline">Novo Gasto</span><span className="sm:hidden">Novo</span>
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 sm:gap-4 mb-6 lg:mb-8">
        <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
          <div className="flex items-center justify-between mb-1">
            <p className="text-xs text-gray-500">Rendimento</p>
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
                className="w-full bg-transparent text-2xl font-bold text-green-400 outline-none border-b border-green-400/30"
              />
            </div>
          ) : (
            <p className="text-2xl font-bold text-green-400">€{income.toFixed(2)}</p>
          )}
        </div>
        <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
          <p className="text-xs text-gray-500 mb-1">Total do Mês</p>
          <p className="text-2xl font-bold text-red-400">€{totalMonth.toFixed(2)}</p>
        </div>
        <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
          <p className="text-xs text-gray-500 mb-1">Restante</p>
          <p className={`text-2xl font-bold ${remaining >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            €{remaining.toFixed(2)}
          </p>
        </div>
        <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
          <p className="text-xs text-gray-500 mb-1">Transações</p>
          <p className="text-2xl font-bold">{expenses.length}</p>
        </div>
        <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
          <p className="text-xs text-gray-500 mb-1">Média/dia</p>
          <p className="text-2xl font-bold text-yellow-400">
            €{(totalMonth / (isSameMonth(currentMonth, new Date()) ? (new Date().getDate() || 1) : getDaysInMonth(currentMonth))).toFixed(2)}
          </p>
        </div>
      </div>

      {/* Budget Status Bars */}
      {budgetStatus && budgetStatus.categories && budgetStatus.categories.length > 0 && (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 mb-6">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
              <Shield size={14} className="text-green-400" /> Orçamento Mensal
            </h3>
            <button onClick={() => setShowBudgetSetup(!showBudgetSetup)}
              className="text-xs text-blue-400 hover:text-blue-300">
              {showBudgetSetup ? 'Fechar' : '+ Limite'}
            </button>
          </div>

          {showBudgetSetup && (
            <div className="flex items-center gap-2 mb-3 p-3 bg-[#1a1a1a] rounded-xl">
              <select
                value={budgetForm.category}
                onChange={e => setBudgetForm(f => ({ ...f, category: e.target.value }))}
                className="bg-[#222] border border-[#333] rounded-lg px-3 py-2 text-sm text-white focus:outline-none"
              >
                <option value="">Categoria...</option>
                {EXPENSE_CATEGORIES.map(c => (
                  <option key={c.value} value={c.value}>{c.emoji} {c.label}</option>
                ))}
              </select>
              <input
                type="number"
                placeholder="Limite €"
                value={budgetForm.monthly_limit || ''}
                onChange={e => setBudgetForm(f => ({ ...f, monthly_limit: parseFloat(e.target.value) || 0 }))}
                className="bg-[#222] border border-[#333] rounded-lg px-3 py-2 text-sm text-white focus:outline-none w-28"
              />
              <button onClick={saveBudgetLimit} className="px-3 py-2 bg-green-600 hover:bg-green-700 rounded-lg text-xs font-medium">
                Guardar
              </button>
            </div>
          )}

          <div className="space-y-3">
            {budgetStatus.categories.map((cat: any) => {
              const catInfo = getCategoryInfo(cat.category);
              const pct = Math.min(cat.percentage, 100);
              const barColor = cat.status === 'over' ? '#EF4444' : cat.status === 'warning' ? '#F59E0B' : '#10B981';
              return (
                <div key={cat.category} className="group">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-gray-400">{catInfo.emoji} {catInfo.label}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium" style={{ color: barColor }}>
                        €{cat.spent.toFixed(0)} / €{cat.limit.toFixed(0)}
                      </span>
                      {cat.status === 'over' && <AlertTriangle size={12} className="text-red-400" />}
                      <button onClick={() => deleteBudgetLimit(cat.id)}
                        className="opacity-0 group-hover:opacity-100 text-gray-600 hover:text-red-400 transition-all">
                        <X size={12} />
                      </button>
                    </div>
                  </div>
                  <div className="h-2 bg-[#222] rounded-full overflow-hidden">
                    <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: barColor }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

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

      {/* Gastos por dia da semana */}
      {weekdaySpending && weekdaySpending.length > 0 && (() => {
        const maxAvg = Math.max(...weekdaySpending.map((x: any) => x.avg || 0), 1);
        const totalAvg = weekdaySpending.reduce((s: number, d: any) => s + (d.avg || 0), 0);
        const peakDay = weekdaySpending.reduce((p: any, c: any) => (c.avg || 0) > (p.avg || 0) ? c : p, weekdaySpending[0]);
        // Color scale: low=green, mid=yellow, high=red
        const getBarColor = (pct: number) => {
          if (pct >= 80) return { from: '#EF4444', to: '#F87171', shadow: 'rgba(239,68,68,0.2)' };
          if (pct >= 55) return { from: '#F59E0B', to: '#FBBF24', shadow: 'rgba(245,158,11,0.15)' };
          return { from: '#10B981', to: '#34D399', shadow: 'rgba(16,185,129,0.15)' };
        };
        return (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-5 mb-6">
          <div className="flex items-center justify-between mb-5">
            <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
              💰 Gastos por dia da semana
            </h3>
            <div className="flex gap-4 text-xs">
              <span className="text-gray-500">Total médio/sem <span className="text-white font-bold">€{totalAvg.toFixed(0)}</span></span>
              <span className="text-gray-500">Pico <span className="text-red-400 font-bold">{peakDay?.day}</span></span>
            </div>
          </div>
          <div className="relative h-40">
            {/* Grid lines */}
            {[0.25, 0.5, 0.75, 1].map(frac => (
              <div key={frac} className="absolute w-full border-t border-dashed border-[#222]" style={{ bottom: `${frac * 100}%` }}>
                <span className="absolute -top-2.5 -left-1 text-[9px] text-gray-700">€{Math.round(maxAvg * frac)}</span>
              </div>
            ))}
            <div className="flex items-end gap-3 h-full pl-7">
              {weekdaySpending.map((d: any) => {
                const pct = maxAvg > 0 ? ((d.avg || 0) / maxAvg) * 100 : 0;
                const isPeak = d.day === peakDay?.day;
                const colors = getBarColor(pct);
                return (
                  <div key={d.day} className="flex-1 flex flex-col items-center group cursor-default">
                    {/* Hover tooltip */}
                    <div className="relative">
                      <div className="absolute -top-8 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity bg-[#222] border border-[#333] rounded-lg px-2.5 py-1 whitespace-nowrap z-10 pointer-events-none">
                        <span className="text-[10px] text-white font-medium">{d.day}: €{(d.avg || 0).toFixed(2)} avg · {d.total_count || '—'} transações</span>
                      </div>
                    </div>
                    <div className="w-full flex flex-col items-center" style={{ height: '160px' }}>
                      <div className="flex-1" />
                      <span className={`text-[11px] font-bold mb-1.5 ${isPeak ? 'text-red-400' : 'text-gray-400'}`}>
                        €{(d.avg || 0).toFixed(0)}
                      </span>
                      <div
                        className="w-full rounded-lg transition-all duration-300 group-hover:brightness-125"
                        style={{
                          height: `${Math.max(pct, 5)}%`,
                          minHeight: '6px',
                          background: `linear-gradient(to top, ${colors.from}, ${colors.to})`,
                          boxShadow: isPeak ? `0 0 12px ${colors.shadow}` : 'none',
                        }}
                      />
                    </div>
                    <span className={`text-xs font-medium mt-2 ${isPeak ? 'text-red-400' : 'text-gray-500'}`}>{d.day}</span>
                  </div>
                );
              })}
            </div>
          </div>
          <div className="flex items-center gap-3 mt-4 text-[10px] text-gray-600">
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-green-500" /> Baixo</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-yellow-500" /> Médio</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-red-500" /> Alto</span>
            <span className="text-gray-700 ml-auto">Média diária nos últimos 90 dias</span>
          </div>
        </div>
        );
      })()}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* Expense List */}
        <div className="col-span-2">
          <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
            <div className="p-4 border-b border-[#222]">
              <h3 className="text-sm font-medium text-gray-300">Transações</h3>
            </div>
            <div className="divide-y divide-[#1a1a1a]">
              {expenses.length === 0 ? (
                <div className="p-8 text-center text-gray-600">Sem gastos este mês</div>
              ) : (
                expenses.map(exp => {
                  const catInfo = getCategoryInfo(exp.category);
                  const hasOrigCurrency = exp.original_currency && exp.original_currency !== 'EUR';
                  return (
                    <div key={exp.id} onClick={() => openEdit(exp)}
                      className="flex items-center gap-4 p-4 hover:bg-white/5 cursor-pointer">
                      <div className="text-2xl">{catInfo.emoji}</div>
                      <div className="flex-1">
                        <p className="text-sm font-medium">{exp.description}</p>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-xs text-gray-500">{catInfo.label} · {format(new Date(exp.date), 'd MMM', { locale: pt })}</span>
                          {exp.merchant_country && (
                            <span className="text-xs text-gray-500">· {exp.merchant_city}{exp.merchant_country ? `, ${exp.merchant_country}` : ''}</span>
                          )}
                        </div>
                      </div>
                      <div className="flex flex-col items-end gap-0.5">
                        <div className="flex items-center gap-2">
                          {exp.receipt_image && <Receipt size={14} className="text-gray-500" />}
                          <span className="text-sm font-bold text-red-400">-€{exp.amount.toFixed(2)}</span>
                        </div>
                        {hasOrigCurrency && (
                          <span className="text-[10px] text-gray-500">
                            {exp.original_amount?.toFixed(2)} {exp.original_currency}
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

        {/* Charts */}
        <div className="space-y-6">
          <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
            <h3 className="text-sm font-medium text-gray-300 mb-4">Por Categoria</h3>
            {pieData.length > 0 ? (
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} dataKey="value" paddingAngle={3}>
                    {pieData.map((_, idx) => (
                      <Cell key={idx} fill={COLORS[idx % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ backgroundColor: '#222', border: 'none', borderRadius: '12px', fontSize: '12px' }}
                    formatter={(value: number) => [`€${value.toFixed(2)}`, '']}
                  />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[200px] flex items-center justify-center text-gray-600 text-sm">Sem dados</div>
            )}
            <div className="space-y-2 mt-4">
              {summary.sort((a, b) => b.total - a.total).map((s, i) => {
                const catInfo = getCategoryInfo(s.category);
                return (
                  <div key={s.category} className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                    <span className="text-xs text-gray-400 flex-1">{catInfo.emoji} {catInfo.label}</span>
                    <span className="text-xs font-medium">€{s.total.toFixed(2)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowModal(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 max-w-[90vw] w-[480px] border border-[#333]" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-bold">{editingExpense ? 'Editar Gasto' : 'Novo Gasto'}</h3>
              <button onClick={() => setShowModal(false)} className="text-gray-500 hover:text-white"><X size={20} /></button>
            </div>

            <div className="space-y-4">
              <input type="text" placeholder="Descrição..."
                value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-green-500"
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
              </div>

              <div>
                <label className="text-xs text-gray-500 block mb-2">Categoria</label>
                <div className="flex flex-wrap gap-2">
                  {EXPENSE_CATEGORIES.map(cat => (
                    <button key={cat.value}
                      onClick={() => setForm(f => ({ ...f, category: cat.value }))}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                        form.category === cat.value
                          ? 'bg-green-600 text-white'
                          : 'bg-[#222] text-gray-400 hover:text-gray-200'
                      }`}>
                      {cat.emoji} {cat.label}
                    </button>
                  ))}
                </div>
              </div>

              <textarea placeholder="Notas (opcional)"
                value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-green-500 resize-none"
                rows={2} />

              {/* Receipt upload for existing expenses */}
              {editingExpense && (
                <div>
                  <label className="text-xs text-gray-500 block mb-2">Recibo / Foto</label>
                  {editingExpense.receipt_image ? (
                    <div className="flex items-center gap-2 text-xs text-green-400">
                      <Receipt size={14} /> Recibo enviado
                    </div>
                  ) : (
                    <label className="flex items-center gap-2 px-4 py-2 bg-[#222] border border-dashed border-[#444] rounded-xl cursor-pointer hover:border-green-500 transition-all">
                      <Upload size={16} className="text-gray-400" />
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

            <div className="flex gap-3 mt-6">
              {editingExpense && (
                <button onClick={handleDelete}
                  className="px-4 py-2.5 bg-red-600/20 text-red-400 hover:bg-red-600/30 rounded-xl text-sm font-medium">
                  Apagar
                </button>
              )}
              <div className="flex-1" />
              <button onClick={() => setShowModal(false)}
                className="px-4 py-2.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm">Cancelar</button>
              <button onClick={handleSave}
                className="px-6 py-2.5 bg-green-600 hover:bg-green-700 rounded-xl text-sm font-medium">
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
