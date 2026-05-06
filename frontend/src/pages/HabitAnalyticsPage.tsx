import { useState, useEffect } from 'react';
import { format, subDays, eachDayOfInterval, getDay } from 'date-fns';
import { pt } from 'date-fns/locale';
import { ArrowLeft, Flame, Target, BarChart3, Calendar } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { habitsApi } from '../api';

const WEEKDAYS = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];

export default function HabitAnalyticsPage() {
  const navigate = useNavigate();
  const [analytics, setAnalytics] = useState<any>(null);
  const [days, setDays] = useState(90);

  useEffect(() => {
    habitsApi.analytics(days).then(setAnalytics).catch(console.error);
  }, [days]);

  if (!analytics) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-2 border-green-400 border-t-transparent rounded-full" />
      </div>
    );
  }

  const today = new Date();
  const heatmapDays = eachDayOfInterval({ start: subDays(today, days - 1), end: today });
  const weeks: Date[][] = [];
  let currentWeek: Date[] = [];
  heatmapDays.forEach(d => {
    if (getDay(d) === 0 && currentWeek.length > 0) {
      weeks.push(currentWeek);
      currentWeek = [];
    }
    currentWeek.push(d);
  });
  if (currentWeek.length > 0) weeks.push(currentWeek);

  const heatmapMap: Record<string, number> = {};
  if (Array.isArray(analytics.heatmap)) {
    analytics.heatmap.forEach((entry: any) => {
      heatmapMap[entry.date] = entry.count || 0;
    });
  } else {
    Object.assign(heatmapMap, analytics.heatmap);
  }

  const maxCount = Math.max(...Object.values(heatmapMap).filter(v => typeof v === 'number' && v > 0), 1);

  function getHeatColor(count: number) {
    if (count === 0) return '#1a1a1a';
    const intensity = count / maxCount;
    if (intensity > 0.75) return '#10B981';
    if (intensity > 0.5) return '#34D399';
    if (intensity > 0.25) return '#6EE7B7';
    return '#A7F3D0';
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center gap-4 mb-8">
        <button onClick={() => navigate('/calendar')} className="p-2 hover:bg-white/10 rounded-xl transition-all">
          <ArrowLeft size={20} />
        </button>
        <div>
          <h2 className="text-2xl font-bold">Habit Analytics</h2>
          <p className="text-gray-500 text-sm mt-1">Dados dos últimos {days} dias</p>
        </div>
        <div className="ml-auto flex gap-2">
          {[30, 60, 90, 180, 365].map(d => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1.5 text-xs rounded-lg transition-all ${
                days === d ? 'bg-green-600 text-white font-medium' : 'bg-[#222] text-gray-400 hover:text-white'
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* Heatmap */}
      <div className="bg-[#161616] rounded-2xl border border-[#222] p-5 mb-6">
        <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2 mb-4">
          <Calendar size={14} className="text-green-400" /> Mapa de Atividade
        </h3>
        {/* Month labels */}
        <div className="flex ml-8 mb-1 gap-[2px]">
          {(() => {
            let lastMonth = -1;
            return weeks.map((week, wi) => {
              const monthIdx = week[0].getMonth();
              const showLabel = monthIdx !== lastMonth;
              lastMonth = monthIdx;
              return (
                <div key={wi} style={{ width: '11px' }} className="flex-shrink-0 text-center">
                  {showLabel && <span className="text-[9px] text-gray-600">{format(week[0], 'MMM', { locale: pt })}</span>}
                </div>
              );
            });
          })()}
        </div>
        <div className="flex gap-0">
          {/* Weekday labels */}
          <div className="flex flex-col gap-[2px] mr-1.5 pt-0">
            {['D', 'S', 'T', 'Q', 'Q', 'S', 'S'].map((d, i) => (
              <div key={i} className="h-[11px] flex items-center justify-end">
                {i % 2 === 1 && <span className="text-[9px] text-gray-600 leading-none">{d}</span>}
              </div>
            ))}
          </div>
          {/* Cells */}
          <div className="flex gap-[2px] overflow-x-auto">
            {weeks.map((week, wi) => {
              // Pad first week so days align to correct weekday row
              const firstDayOfWeek = getDay(week[0]);
              const padded = Array(firstDayOfWeek).fill(null);
              return (
                <div key={wi} className="flex flex-col gap-[2px]">
                  {padded.map((_, pi) => (
                    <div key={`pad-${pi}`} className="w-[11px] h-[11px]" />
                  ))}
                  {week.map(day => {
                    const dateStr = format(day, 'yyyy-MM-dd');
                    const count = heatmapMap[dateStr] || 0;
                    return (
                      <div
                        key={dateStr}
                        className="w-[11px] h-[11px] rounded-[2px] transition-colors hover:ring-1 hover:ring-white/20"
                        style={{ backgroundColor: getHeatColor(count) }}
                        title={`${format(day, 'd MMM', { locale: pt })}: ${count} hábito${count !== 1 ? 's' : ''}`}
                      />
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
        <div className="flex items-center gap-1.5 mt-3">
          <span className="text-[9px] text-gray-600">Menos</span>
          {[0, 0.25, 0.5, 0.75, 1].map((v, i) => (
            <div key={i} className="w-[11px] h-[11px] rounded-[2px]" style={{ backgroundColor: getHeatColor(v * maxCount) }} />
          ))}
          <span className="text-[9px] text-gray-600">Mais</span>
          <span className="text-[9px] text-gray-700 ml-auto">{Object.values(heatmapMap).reduce((s, v) => s + (typeof v === 'number' ? v : 0), 0)} completados em {days} dias</span>
        </div>
      </div>

      {/* Per-habit cards */}
      {analytics.habits.length === 0 ? (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-8 text-center">
          <p className="text-gray-500">Sem hábitos registados.</p>
          <button onClick={() => navigate('/calendar')} className="text-sm text-blue-400 hover:text-blue-300 mt-2">
            Criar hábitos no Calendário
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {analytics.habits.map((h: any) => (
            <div key={h.id} className="bg-[#161616] rounded-2xl border border-[#222] p-5">
              {/* Habit header */}
              <div className="flex items-center gap-3 mb-4">
                <span className="text-2xl">{h.icon}</span>
                <div className="flex-1">
                  <p className="text-sm font-bold">{h.name}</p>
                  <p className="text-[10px] text-gray-500">{h.days === 'daily' ? 'Todos os dias' : h.days}</p>
                </div>
                <div className={`text-2xl font-bold ${h.rate >= 80 ? 'text-green-400' : h.rate >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
                  {h.rate}%
                </div>
              </div>

              {/* Streaks */}
              <div className="flex gap-4 mb-4">
                <div className="flex items-center gap-2 bg-[#1a1a1a] rounded-xl px-3 py-2 flex-1">
                  <Flame size={16} className="text-orange-400" />
                  <div>
                    <p className="text-lg font-bold">{h.current_streak}</p>
                    <p className="text-[10px] text-gray-500">Streak atual</p>
                  </div>
                </div>
                <div className="flex items-center gap-2 bg-[#1a1a1a] rounded-xl px-3 py-2 flex-1">
                  <Target size={16} className="text-purple-400" />
                  <div>
                    <p className="text-lg font-bold">{h.best_streak}</p>
                    <p className="text-[10px] text-gray-500">Melhor streak</p>
                  </div>
                </div>
              </div>

              {/* Progress bar */}
              <div className="mb-4">
                <div className="h-2 bg-[#222] rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{
                      width: `${h.rate}%`,
                      backgroundColor: h.rate >= 80 ? '#10B981' : h.rate >= 50 ? '#F59E0B' : '#EF4444',
                    }}
                  />
                </div>
              </div>

              {/* By weekday */}
              <div className="flex gap-1">
                {WEEKDAYS.map((day, i) => {
                  const rate = h.by_weekday?.[i] ?? 0;
                  return (
                    <div key={day} className="flex-1 flex flex-col items-center gap-1">
                      <div
                        className="w-full h-8 rounded-md"
                        style={{
                          backgroundColor: rate > 0 ? `rgba(16, 185, 129, ${rate / 100})` : '#1a1a1a',
                        }}
                        title={`${day}: ${rate}%`}
                      />
                      <span className="text-[9px] text-gray-600">{day}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
