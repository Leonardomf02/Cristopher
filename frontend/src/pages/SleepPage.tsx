import { useState, useEffect } from 'react';
import { format, subDays } from 'date-fns';
import { pt } from 'date-fns/locale';
import { Plus, X, Trash2, Moon, Sun, Star, ChevronLeft, ChevronRight } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { sleepApi } from '../api';
import { SleepEntry, SleepStats } from '../types';

const QUALITY_LABELS = ['', 'Péssima', 'Má', 'Normal', 'Boa', 'Excelente'];
const QUALITY_COLORS = ['', '#EF4444', '#F97316', '#F59E0B', '#10B981', '#8B5CF6'];

export default function SleepPage() {
  const [entries, setEntries] = useState<SleepEntry[]>([]);
  const [stats, setStats] = useState<SleepStats | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [editingEntry, setEditingEntry] = useState<SleepEntry | null>(null);
  const [statsDays, setStatsDays] = useState(30);

  const [form, setForm] = useState({
    date: format(new Date(), 'yyyy-MM-dd'),
    bedtime: '23:00',
    wake_time: '07:00',
    hours: 8,
    quality: 3,
    notes: '',
  });

  useEffect(() => { loadData(); }, [statsDays]);

  async function loadData() {
    const start = format(subDays(new Date(), statsDays), 'yyyy-MM-dd');
    const end = format(new Date(), 'yyyy-MM-dd');
    const [entriesData, statsData] = await Promise.all([
      sleepApi.list({ start_date: start, end_date: end }),
      sleepApi.stats(statsDays),
    ]);
    setEntries(entriesData);
    setStats(statsData);
  }

  function openNew() {
    setEditingEntry(null);
    setForm({ date: format(new Date(), 'yyyy-MM-dd'), bedtime: '23:00', wake_time: '07:00', hours: 8, quality: 3, notes: '' });
    setShowModal(true);
  }

  function openEdit(entry: SleepEntry) {
    setEditingEntry(entry);
    setForm({
      date: entry.date,
      bedtime: entry.bedtime || '23:00',
      wake_time: entry.wake_time || '07:00',
      hours: entry.hours,
      quality: entry.quality || 3,
      notes: entry.notes || '',
    });
    setShowModal(true);
  }

  function calcHours(bedtime: string, wakeTime: string): number {
    const [bh, bm] = bedtime.split(':').map(Number);
    const [wh, wm] = wakeTime.split(':').map(Number);
    let diff = (wh * 60 + wm) - (bh * 60 + bm);
    if (diff < 0) diff += 24 * 60;
    return Math.round((diff / 60) * 10) / 10;
  }

  function updateBedtime(val: string) {
    const hours = calcHours(val, form.wake_time);
    setForm(f => ({ ...f, bedtime: val, hours }));
  }

  function updateWakeTime(val: string) {
    const hours = calcHours(form.bedtime, val);
    setForm(f => ({ ...f, wake_time: val, hours }));
  }

  async function handleSave() {
    if (editingEntry) {
      await sleepApi.update(editingEntry.id, form);
    } else {
      await sleepApi.create(form);
    }
    setShowModal(false);
    loadData();
  }

  async function handleDelete() {
    if (editingEntry) {
      await sleepApi.delete(editingEntry.id);
      setShowModal(false);
      loadData();
    }
  }

  const chartData = [...entries].reverse().map(e => ({
    date: format(new Date(e.date), 'd MMM', { locale: pt }),
    hours: e.hours,
    quality: e.quality || 0,
  }));

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h2 className="text-2xl font-bold">Sono</h2>
          <p className="text-gray-500 text-sm mt-1">Tracking do teu sono</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1 bg-[#161616] rounded-xl border border-[#222] p-1">
            {[7, 14, 30, 90].map(d => (
              <button key={d} onClick={() => setStatsDays(d)}
                className={`px-3 py-1.5 text-xs rounded-lg transition-all ${
                  statsDays === d ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-white'
                }`}>
                {d}d
              </button>
            ))}
          </div>
          <button onClick={openNew}
            className="flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-xl text-sm font-medium">
            <Plus size={16} /> Registar Sono
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-5 gap-4 mb-8">
          <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
            <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
              <Moon size={14} className="text-purple-400" /> Média
            </div>
            <p className="text-2xl font-bold">{stats.avg_hours.toFixed(1)}<span className="text-sm text-gray-500">h</span></p>
          </div>

          <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
            <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
              <Star size={14} className="text-yellow-400" /> Qualidade
            </div>
            <p className="text-2xl font-bold" style={{ color: QUALITY_COLORS[Math.round(stats.avg_quality)] || '#fff' }}>
              {stats.avg_quality.toFixed(1)}<span className="text-sm text-gray-500">/5</span>
            </p>
          </div>

          <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
            <p className="text-xs text-gray-500 mb-2">Entradas</p>
            <p className="text-2xl font-bold">{stats.total_entries}</p>
          </div>

          <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
            <p className="text-xs text-gray-500 mb-2">Melhor Noite</p>
            {stats.best_day ? (
              <>
                <p className="text-2xl font-bold text-green-400">{stats.best_day.hours}h</p>
                <p className="text-xs text-gray-500 mt-1">
                  {format(new Date(stats.best_day.date), 'd MMM', { locale: pt })}
                </p>
              </>
            ) : <p className="text-2xl font-bold text-gray-600">—</p>}
          </div>

          <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
            <p className="text-xs text-gray-500 mb-2">Pior Noite</p>
            {stats.worst_day ? (
              <>
                <p className="text-2xl font-bold text-red-400">{stats.worst_day.hours}h</p>
                <p className="text-xs text-gray-500 mt-1">
                  {format(new Date(stats.worst_day.date), 'd MMM', { locale: pt })}
                </p>
              </>
            ) : <p className="text-2xl font-bold text-gray-600">—</p>}
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-6">
        {/* Chart */}
        <div className="col-span-2">
          <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
            <h3 className="text-sm font-medium text-gray-300 mb-4">Horas de Sono</h3>
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#222" />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#666' }} />
                  <YAxis tick={{ fontSize: 11, fill: '#666' }} domain={[0, 12]} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#222', border: 'none', borderRadius: '12px', fontSize: '12px' }}
                    formatter={(value: number, name: string) => [
                      name === 'hours' ? `${value}h` : QUALITY_LABELS[value] || value,
                      name === 'hours' ? 'Horas' : 'Qualidade',
                    ]}
                  />
                  <Bar dataKey="hours" fill="#8B5CF6" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[280px] flex items-center justify-center text-gray-600 text-sm">
                Sem dados de sono
              </div>
            )}
          </div>
        </div>

        {/* Recent entries */}
        <div>
          <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
            <div className="p-4 border-b border-[#222]">
              <h3 className="text-sm font-medium text-gray-300">Entradas Recentes</h3>
            </div>
            <div className="divide-y divide-[#1a1a1a]">
              {entries.length === 0 ? (
                <div className="p-6 text-center text-gray-600 text-sm">Sem entradas</div>
              ) : (
                entries.slice(0, 10).map(entry => (
                  <div key={entry.id} onClick={() => openEdit(entry)}
                    className="flex items-center gap-3 p-3 hover:bg-white/5 cursor-pointer">
                    <div className="w-10 h-10 rounded-xl flex items-center justify-center text-lg"
                      style={{ backgroundColor: (QUALITY_COLORS[entry.quality || 0] || '#333') + '22' }}>
                      {entry.hours >= 7 ? '😴' : entry.hours >= 5 ? '😐' : '😵'}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium">{entry.hours}h</p>
                      <p className="text-xs text-gray-500">
                        {format(new Date(entry.date), "d 'de' MMM", { locale: pt })}
                        {entry.bedtime && entry.wake_time && (
                          <> · {entry.bedtime} → {entry.wake_time}</>
                        )}
                      </p>
                    </div>
                    {entry.quality && (
                      <div className="flex gap-0.5">
                        {Array.from({ length: 5 }).map((_, i) => (
                          <Star key={i} size={10}
                            className={i < entry.quality! ? 'text-yellow-400 fill-yellow-400' : 'text-gray-700'} />
                        ))}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowModal(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 w-[420px] border border-[#333]" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-bold">{editingEntry ? 'Editar Sono' : 'Registar Sono'}</h3>
              <button onClick={() => setShowModal(false)} className="text-gray-500 hover:text-white"><X size={20} /></button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="text-xs text-gray-500 block mb-1">Data</label>
                <input type="date" value={form.date} onChange={e => setForm(f => ({ ...f, date: e.target.value }))}
                  className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-purple-500" />
              </div>

              <div className="flex gap-3">
                <div className="flex-1">
                  <label className="text-xs text-gray-500 block mb-1 flex items-center gap-1">
                    <Moon size={12} className="text-purple-400" /> Deitei-me
                  </label>
                  <input type="time" value={form.bedtime} onChange={e => updateBedtime(e.target.value)}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-purple-500" />
                </div>
                <div className="flex-1">
                  <label className="text-xs text-gray-500 block mb-1 flex items-center gap-1">
                    <Sun size={12} className="text-yellow-400" /> Acordei
                  </label>
                  <input type="time" value={form.wake_time} onChange={e => updateWakeTime(e.target.value)}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-purple-500" />
                </div>
              </div>

              <div className="bg-[#222] rounded-xl p-3 text-center">
                <p className="text-3xl font-bold text-purple-400">{form.hours}h</p>
                <p className="text-xs text-gray-500">de sono</p>
              </div>

              <div>
                <label className="text-xs text-gray-500 block mb-2">Qualidade</label>
                <div className="flex gap-2">
                  {[1, 2, 3, 4, 5].map(q => (
                    <button key={q} onClick={() => setForm(f => ({ ...f, quality: q }))}
                      className={`flex-1 py-2.5 rounded-xl text-xs font-medium transition-all border ${
                        form.quality === q
                          ? 'text-white border-transparent'
                          : 'bg-[#222] border-[#333] text-gray-400 hover:text-white hover:border-[#444]'
                      }`}
                      style={form.quality === q ? { backgroundColor: QUALITY_COLORS[q] } : undefined}>
                      {QUALITY_LABELS[q]}
                    </button>
                  ))}
                </div>
              </div>

              <textarea placeholder="Notas (opcional)"
                value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-purple-500 resize-none"
                rows={2} />
            </div>

            <div className="flex gap-3 mt-6">
              {editingEntry && (
                <button onClick={handleDelete}
                  className="px-4 py-2.5 bg-red-600/20 text-red-400 hover:bg-red-600/30 rounded-xl text-sm font-medium">
                  Apagar
                </button>
              )}
              <div className="flex-1" />
              <button onClick={() => setShowModal(false)}
                className="px-4 py-2.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm">Cancelar</button>
              <button onClick={handleSave}
                className="px-6 py-2.5 bg-purple-600 hover:bg-purple-700 rounded-xl text-sm font-medium">
                {editingEntry ? 'Guardar' : 'Registar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
