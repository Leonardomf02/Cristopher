import { useState, useEffect, useRef, useCallback } from 'react';
import { format, subDays, subMonths, startOfMonth, endOfMonth, startOfWeek, endOfWeek, eachDayOfInterval, eachWeekOfInterval } from 'date-fns';
import { pt } from 'date-fns/locale';
import {
  Play, Pause, Square, Plus, X, Timer, Clock, Trash2, Settings2,
  CheckCircle2, BarChart3, VolumeX, Volume2, BellOff, Music,
} from 'lucide-react';
import { flowApi } from '../api';
import { useFlow, type FlowPreset } from '../FlowContext';

// ── Types ───────────────────────────────────────────────────────

interface FlowSession {
  id: number;
  preset_id: number | null;
  preset_name: string;
  date: string;
  start_time: string;
  end_time: string | null;
  planned_minutes: number;
  actual_minutes: number | null;
  completed: boolean;
  color: string;
  notes: string;
}

interface FlowStats {
  total_sessions: number;
  total_minutes: number;
  total_hours: number;
  completed: number;
  completion_rate: number;
  by_preset: Record<string, { sessions: number; minutes: number; completed: number; color: string }>;
}

const PRESET_ICONS = ['⏱️', '💻', '🏋️', '📚', '🎨', '🎵', '✍️', '🧘', '🔬', '🎯', '🚀', '💡'];
const PRESET_COLORS = [
  '#3B82F6', '#EF4444', '#10B981', '#F59E0B', '#8B5CF6',
  '#EC4899', '#06B6D4', '#F97316', '#14B8A6', '#6366F1',
];

export default function FlowPage() {
  const {
    phase, secondsLeft, isPaused, activePreset, elapsedWorkSeconds, sessionVersion,
    alarmActive, startTimer, togglePause, stopTimer, skipBreak, dismissAlarm,
  } = useFlow();

  // ── Local State ─────────────────────────────────────────
  const [presets, setPresets] = useState<FlowPreset[]>([]);
  const [sessions, setSessions] = useState<FlowSession[]>([]);
  const [stats, setStats] = useState<FlowStats | null>(null);

  // UI state
  const [showPresetModal, setShowPresetModal] = useState(false);
  const [editingPreset, setEditingPreset] = useState<FlowPreset | null>(null);
  const [presetForm, setPresetForm] = useState({
    name: '', work_minutes: 50, break_minutes: 10, color: '#3B82F6', icon: '⏱️',
  });

  // Mute & Ambient sounds
  const [isMuted, setIsMuted] = useState(false);
  const [activeSound, setActiveSound] = useState<string | null>(null);
  const [soundVolume, setSoundVolume] = useState(0.3);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const noiseNodeRef = useRef<AudioBufferSourceNode | null>(null);
  const gainNodeRef = useRef<GainNode | null>(null);

  // Flow analytics
  const [weeklyData, setWeeklyData] = useState<{ date: string; minutes: number }[]>([]);
  const [flowRange, setFlowRange] = useState<'week' | 'month' | '3months'>('week');

  const AMBIENT_SOUNDS = [
    { id: 'brown', label: 'Brown Noise', emoji: '🌊', desc: 'Ruído profundo relaxante' },
    { id: 'pink', label: 'Pink Noise', emoji: '🌸', desc: 'Ruído suave e uniforme' },
    { id: 'white', label: 'White Noise', emoji: '⚡', desc: 'Ruído branco constante' },
  ];

  // ── Load data ─────────────────────────────────────────
  useEffect(() => {
    loadData();
  }, [sessionVersion]);

  async function loadData() {
    try {
      const [p, s, st] = await Promise.all([
        flowApi.listPresets(),
        flowApi.listSessions({ start_date: format(new Date(), 'yyyy-MM-dd'), end_date: format(new Date(), 'yyyy-MM-dd') }),
        flowApi.stats(),
      ]);
      setPresets(p);
      setSessions(s);
      setStats(st);
    } catch (err) {
      console.error('Failed to load flow data:', err);
    }

    // Load flow analytics (last 3 months)
    try {
      const end = new Date();
      const start = subMonths(end, 3);
      const allSessions = await flowApi.listSessions({
        start_date: format(start, 'yyyy-MM-dd'),
        end_date: format(end, 'yyyy-MM-dd'),
      });
      const days = eachDayOfInterval({ start, end });
      const daily = days.map(d => {
        const dateStr = format(d, 'yyyy-MM-dd');
        const dayMins = allSessions
          .filter((s: any) => s.date === dateStr)
          .reduce((sum: number, s: any) => sum + (s.actual_minutes || s.planned_minutes || 0), 0);
        return { date: dateStr, minutes: dayMins };
      });
      setWeeklyData(daily);
    } catch {}
  }

  // ── Ambient Sound Engine (Web Audio API) ─────────────────
  const stopSound = useCallback(() => {
    if (noiseNodeRef.current) {
      try { noiseNodeRef.current.stop(); } catch {}
      noiseNodeRef.current = null;
    }
    setActiveSound(null);
  }, []);

  function generateNoise(type: string) {
    if (activeSound === type) {
      stopSound();
      return;
    }
    stopSound();

    const ctx = audioCtxRef.current || new AudioContext();
    audioCtxRef.current = ctx;

    const bufferSize = ctx.sampleRate * 4; // 4 seconds buffer
    const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
    const data = buffer.getChannelData(0);

    if (type === 'white') {
      for (let i = 0; i < bufferSize; i++) data[i] = Math.random() * 2 - 1;
    } else if (type === 'pink') {
      let b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
      for (let i = 0; i < bufferSize; i++) {
        const white = Math.random() * 2 - 1;
        b0 = 0.99886 * b0 + white * 0.0555179;
        b1 = 0.99332 * b1 + white * 0.0750759;
        b2 = 0.96900 * b2 + white * 0.1538520;
        b3 = 0.86650 * b3 + white * 0.3104856;
        b4 = 0.55000 * b4 + white * 0.5329522;
        b5 = -0.7616 * b5 - white * 0.0168980;
        data[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + white * 0.5362) * 0.11;
        b6 = white * 0.115926;
      }
    } else { // brown
      let lastOut = 0;
      for (let i = 0; i < bufferSize; i++) {
        const white = Math.random() * 2 - 1;
        lastOut = (lastOut + (0.02 * white)) / 1.02;
        data[i] = lastOut * 3.5;
      }
    }

    const gain = ctx.createGain();
    gain.gain.value = soundVolume;
    gain.connect(ctx.destination);
    gainNodeRef.current = gain;

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.loop = true;
    source.connect(gain);
    source.start();
    noiseNodeRef.current = source;
    setActiveSound(type);
  }

  useEffect(() => {
    if (gainNodeRef.current) {
      gainNodeRef.current.gain.value = soundVolume;
    }
  }, [soundVolume]);

  // Stop sound on unmount
  useEffect(() => () => stopSound(), [stopSound]);

  // ── Preset Management ──────────────────────────────────
  function openNewPreset() {
    setEditingPreset(null);
    setPresetForm({ name: '', work_minutes: 50, break_minutes: 10, color: '#3B82F6', icon: '⏱️' });
    setShowPresetModal(true);
  }

  function openEditPreset(p: FlowPreset) {
    setEditingPreset(p);
    setPresetForm({ name: p.name, work_minutes: p.work_minutes, break_minutes: p.break_minutes, color: p.color, icon: p.icon });
    setShowPresetModal(true);
  }

  async function savePreset() {
    if (!presetForm.name.trim()) return;
    try {
      if (editingPreset) {
        await flowApi.updatePreset(editingPreset.id, presetForm);
      } else {
        await flowApi.createPreset(presetForm);
      }
      setShowPresetModal(false);
      loadData();
    } catch (err) {
      console.error('Failed to save preset:', err);
    }
  }

  async function deletePreset(id: number) {
    try {
      await flowApi.deletePreset(id);
      loadData();
    } catch (err) {
      console.error('Failed to delete preset:', err);
    }
  }

  // ── Helpers ────────────────────────────────────────────
  function formatTime(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }

  function formatMinutes(mins: number): string {
    if (mins < 60) return `${mins}min`;
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return m > 0 ? `${h}h ${m}min` : `${h}h`;
  }

  const totalRadius = 140;
  const circumference = 2 * Math.PI * totalRadius;
  const totalSeconds = phase === 'work'
    ? (activePreset?.work_minutes ?? 1) * 60
    : (activePreset?.break_minutes ?? 1) * 60;
  const progress = totalSeconds > 0 ? (totalSeconds - secondsLeft) / totalSeconds : 0;

  // ── Render ─────────────────────────────────────────────
  return (
    <div className="max-w-5xl mx-auto space-y-8">
      {/* Alarm Overlay */}
      {alarmActive && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/80 backdrop-blur-sm">
          <div className="text-center space-y-8 p-12 max-w-lg">
            <div className="text-8xl animate-bounce">⏰</div>
            <h2 className="text-4xl font-bold text-white">
              {phase === 'break' ? 'Tempo de trabalho terminou!' : phase === 'idle' ? 'Pausa terminou!' : 'Flow terminou!'}
            </h2>
            <p className="text-xl text-gray-300">
              {activePreset
                ? `${activePreset.icon} ${activePreset.name} — ${Math.round(elapsedWorkSeconds / 60)} minutos de foco`
                : 'A tua sessão acabou'}
            </p>
            <button
              onClick={dismissAlarm}
              className="px-12 py-5 bg-blue-600 hover:bg-blue-700 text-white text-2xl font-bold rounded-2xl transition-all hover:scale-105 shadow-xl shadow-blue-600/30"
            >
              Dispensar
            </button>
          </div>
        </div>
      )}
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3">
            <Timer className="text-blue-400" /> Flow
          </h1>
          <p className="text-gray-500 text-sm mt-1">Timer de foco com ciclos de trabalho e pausa</p>
        </div>
        <button onClick={openNewPreset}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-xl text-sm font-medium transition-colors">
          <Plus size={16} /> Novo Preset
        </button>
      </div>

      {/* Timer Display - Active */}
      {phase !== 'idle' && activePreset && (
        <div className="bg-[#161616] rounded-3xl border border-[#222] p-8 flex flex-col items-center">
          {/* Phase Label */}
          <div className={`px-4 py-1.5 rounded-full text-sm font-bold mb-6 ${
            phase === 'work' ? 'bg-blue-500/20 text-blue-400' : 'bg-green-500/20 text-green-400'
          }`}>
            {phase === 'work' ? '🔥 FOCO' : '☕ PAUSA'}
          </div>

          {/* Forest tree (work only) + Circular Timer */}
          <div className="flex items-center justify-center gap-10 mb-6 flex-wrap">
            {phase === 'work' && (
              <ForestTree progress={progress} paused={isPaused} dead={false} />
            )}
            <div className="relative w-80 h-80 flex items-center justify-center">
              <svg className="absolute w-full h-full -rotate-90" viewBox="0 0 320 320">
                <circle cx="160" cy="160" r={totalRadius} fill="none" stroke="#222" strokeWidth="8" />
                <circle cx="160" cy="160" r={totalRadius} fill="none"
                  stroke={phase === 'work' ? activePreset.color : '#10B981'}
                  strokeWidth="8" strokeLinecap="round"
                  strokeDasharray={circumference}
                  strokeDashoffset={circumference * (1 - progress)}
                  className="transition-all duration-1000"
                />
              </svg>
              <div className="text-center z-10">
                <p className="text-6xl font-mono font-bold tracking-wider">{formatTime(secondsLeft)}</p>
                <p className="text-sm text-gray-500 mt-2">
                  {activePreset.icon} {activePreset.name}
                </p>
                {phase === 'work' && (
                  <p className="text-xs text-gray-600 mt-1">
                    {formatMinutes(Math.round(elapsedWorkSeconds / 60))} trabalhados
                  </p>
                )}
              </div>
            </div>
          </div>

          {/* Controls */}
          <div className="flex items-center gap-4">
            <button onClick={togglePause}
              className={`p-4 rounded-2xl transition-colors ${
                isPaused ? 'bg-blue-600 hover:bg-blue-700' : 'bg-yellow-600 hover:bg-yellow-700'
              }`}>
              {isPaused ? <Play size={28} /> : <Pause size={28} />}
            </button>
            <button
              onClick={() => {
                if (phase === 'work' && progress < 0.95) {
                  const ok = window.confirm('⚠️ Se parares agora, a tua árvore vai morrer. Continuar?');
                  if (!ok) return;
                }
                stopTimer();
              }}
              title={phase === 'work' ? 'Parar (a árvore vai morrer)' : 'Parar'}
              className="p-4 rounded-2xl bg-red-600 hover:bg-red-700 transition-colors">
              <Square size={28} />
            </button>
            {phase === 'break' && (
              <button onClick={skipBreak}
                className="p-4 rounded-2xl bg-gray-600 hover:bg-gray-700 transition-colors text-sm font-medium">
                Skip pausa →
              </button>
            )}
            <button
              onClick={() => setIsMuted(!isMuted)}
              className={`p-3 rounded-2xl transition-colors ${isMuted ? 'bg-red-600/20 text-red-400' : 'bg-[#222] text-gray-400 hover:text-white'}`}
              title={isMuted ? 'Notificações silenciadas' : 'Silenciar notificações'}
            >
              {isMuted ? <BellOff size={20} /> : <Volume2 size={20} />}
            </button>
          </div>

          {/* Ambient Sounds during active timer */}
          <div className="mt-6 w-full max-w-md">
            <p className="text-xs text-gray-500 text-center mb-3 flex items-center justify-center gap-1">
              <Music size={12} /> Sons Ambiente
            </p>
            <div className="flex gap-2 justify-center">
              {AMBIENT_SOUNDS.map(s => (
                <button
                  key={s.id}
                  onClick={() => generateNoise(s.id)}
                  className={`px-4 py-2 rounded-xl text-sm transition-all ${
                    activeSound === s.id
                      ? 'bg-blue-600/20 text-blue-400 ring-1 ring-blue-500/50'
                      : 'bg-[#222] text-gray-400 hover:text-white hover:bg-[#2a2a2a]'
                  }`}
                >
                  {s.emoji} {s.label}
                </button>
              ))}
            </div>
            {activeSound && (
              <div className="flex items-center gap-3 mt-3 justify-center">
                <VolumeX size={14} className="text-gray-500" />
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={soundVolume}
                  onChange={e => setSoundVolume(parseFloat(e.target.value))}
                  className="w-32 accent-blue-500"
                />
                <Volume2 size={14} className="text-gray-500" />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Presets Grid */}
      {phase === 'idle' && (
        <div>
          <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
            <Settings2 size={18} className="text-gray-400" /> Presets
          </h2>
          {presets.length === 0 ? (
            <div className="bg-[#161616] rounded-2xl border border-[#222] p-12 text-center">
              <Timer className="mx-auto mb-3 text-gray-600" size={40} />
              <p className="text-gray-500">Sem presets criados</p>
              <p className="text-gray-600 text-sm mt-1">Cria o teu primeiro preset de foco!</p>
            </div>
          ) : (
            <div className="grid grid-cols-3 gap-4">
              {presets.map(p => (
                <div key={p.id}
                  className="bg-[#161616] rounded-2xl border border-[#222] p-5 hover:border-[#333] transition-colors group relative">
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <span className="text-2xl">{p.icon}</span>
                      <div>
                        <h3 className="font-bold">{p.name}</h3>
                        <p className="text-xs text-gray-500">{p.work_minutes}min foco · {p.break_minutes}min pausa</p>
                      </div>
                    </div>
                    <div className="opacity-0 group-hover:opacity-100 flex gap-1 transition-opacity">
                      <button onClick={() => openEditPreset(p)}
                        className="p-1.5 rounded-lg hover:bg-white/10 text-gray-500 hover:text-white">
                        <Settings2 size={14} />
                      </button>
                      <button onClick={() => deletePreset(p.id)}
                        className="p-1.5 rounded-lg hover:bg-red-500/20 text-gray-500 hover:text-red-400">
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                  <div className="w-full h-1 rounded-full bg-[#222] mb-4">
                    <div className="h-full rounded-full" style={{ backgroundColor: p.color, width: '100%' }} />
                  </div>
                  <button onClick={() => startTimer(p)}
                    className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-medium transition-colors hover:brightness-110"
                    style={{ backgroundColor: `${p.color}20`, color: p.color }}>
                    <Play size={16} /> Iniciar
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Today's Sessions + Stats */}
      <div className="grid grid-cols-2 gap-6">
        {/* Today's Sessions */}
        <div>
          <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
            <Clock size={18} className="text-gray-400" /> Sessões de Hoje
          </h2>
          {sessions.length === 0 ? (
            <div className="bg-[#161616] rounded-2xl border border-[#222] p-8 text-center">
              <p className="text-gray-600 text-sm">Nenhuma sessão hoje</p>
            </div>
          ) : (
            <div className="space-y-2">
              {sessions.map(s => (
                <div key={s.id}
                  className="bg-[#161616] rounded-xl border border-[#222] p-3 flex items-center gap-3 group">
                  <div className="w-1 h-10 rounded-full" style={{ backgroundColor: s.color }} />
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{s.preset_name}</span>
                      {s.completed ? (
                        <CheckCircle2 size={14} className="text-green-400" />
                      ) : (
                        <span className="text-xs text-yellow-400">parcial</span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500">
                      {s.start_time}–{s.end_time || '?'} · {s.actual_minutes ?? s.planned_minutes}min
                      {!s.completed && s.actual_minutes != null && ` / ${s.planned_minutes}min`}
                    </p>
                  </div>
                  <button onClick={async () => { await flowApi.deleteSession(s.id); loadData(); }}
                    className="p-1.5 rounded-lg hover:bg-red-500/20 text-gray-500 hover:text-red-400 opacity-0 group-hover:opacity-100">
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Stats */}
        <div>
          <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
            <BarChart3 size={18} className="text-gray-400" /> Estatísticas
          </h2>
          {stats && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-[#161616] rounded-xl border border-[#222] p-4">
                  <p className="text-xs text-gray-500 mb-1">Total Sessões</p>
                  <p className="text-2xl font-bold">{stats.total_sessions}</p>
                </div>
                <div className="bg-[#161616] rounded-xl border border-[#222] p-4">
                  <p className="text-xs text-gray-500 mb-1">Horas de Foco</p>
                  <p className="text-2xl font-bold">{stats.total_hours}h</p>
                </div>
                <div className="bg-[#161616] rounded-xl border border-[#222] p-4">
                  <p className="text-xs text-gray-500 mb-1">Completas</p>
                  <p className="text-2xl font-bold text-green-400">{stats.completed}</p>
                </div>
                <div className="bg-[#161616] rounded-xl border border-[#222] p-4">
                  <p className="text-xs text-gray-500 mb-1">Taxa Conclusão</p>
                  <p className="text-2xl font-bold text-blue-400">{stats.completion_rate}%</p>
                </div>
              </div>

              {/* By Preset */}
              {Object.entries(stats.by_preset).length > 0 && (
                <div className="bg-[#161616] rounded-xl border border-[#222] p-4">
                  <p className="text-xs text-gray-500 mb-3">Por Atividade</p>
                  <div className="space-y-2">
                    {Object.entries(stats.by_preset).map(([name, data]) => (
                      <div key={name} className="flex items-center gap-3">
                        <div className="w-2 h-2 rounded-full" style={{ backgroundColor: data.color }} />
                        <span className="text-sm flex-1">{name}</span>
                        <span className="text-xs text-gray-500">{data.sessions} sessões</span>
                        <span className="text-xs font-medium">{formatMinutes(data.minutes)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Flow Analytics — multi-range chart */}
      {weeklyData.length > 0 && (() => {
        const now = new Date();
        const todayStr = format(now, 'yyyy-MM-dd');
        
        // Filter data based on selected range
        let filteredData: { date: string; minutes: number }[];
        let rangeLabel: string;
        
        if (flowRange === 'week') {
          const weekStart = startOfWeek(now, { weekStartsOn: 1 });
          filteredData = weeklyData.filter(d => d.date >= format(weekStart, 'yyyy-MM-dd') && d.date <= todayStr);
          // Pad to full week (Mon-Sun)
          const fullWeek = eachDayOfInterval({ start: weekStart, end: endOfWeek(now, { weekStartsOn: 1 }) });
          filteredData = fullWeek.map(day => {
            const ds = format(day, 'yyyy-MM-dd');
            return filteredData.find(d => d.date === ds) || { date: ds, minutes: 0 };
          });
          rangeLabel = 'Esta semana';
        } else if (flowRange === 'month') {
          const monthStart = startOfMonth(now);
          filteredData = weeklyData.filter(d => d.date >= format(monthStart, 'yyyy-MM-dd') && d.date <= todayStr);
          rangeLabel = format(now, 'MMMM yyyy', { locale: pt });
        } else {
          // 3 months — group by week
          const threeMonthsAgo = subMonths(now, 3);
          filteredData = weeklyData.filter(d => d.date >= format(threeMonthsAgo, 'yyyy-MM-dd'));
          rangeLabel = 'Últimos 3 meses';
        }

        // For 3months view, aggregate by week
        let chartBars: { label: string; sublabel: string; minutes: number; isToday: boolean; key: string }[];
        
        if (flowRange === '3months') {
          const weeks = eachWeekOfInterval(
            { start: subMonths(now, 3), end: now },
            { weekStartsOn: 1 }
          );
          chartBars = weeks.map(weekStart => {
            const weekEnd = endOfWeek(weekStart, { weekStartsOn: 1 });
            const weekDays = filteredData.filter(d => d.date >= format(weekStart, 'yyyy-MM-dd') && d.date <= format(weekEnd, 'yyyy-MM-dd'));
            const totalMins = weekDays.reduce((s, d) => s + d.minutes, 0);
            const isCurrent = todayStr >= format(weekStart, 'yyyy-MM-dd') && todayStr <= format(weekEnd, 'yyyy-MM-dd');
            return {
              label: format(weekStart, 'd', { locale: pt }),
              sublabel: format(weekStart, 'MMM', { locale: pt }),
              minutes: totalMins,
              isToday: isCurrent,
              key: format(weekStart, 'yyyy-MM-dd'),
            };
          });
        } else {
          chartBars = filteredData.map(d => {
            const dateObj = new Date(d.date);
            return {
              label: format(dateObj, 'EEE', { locale: pt }).charAt(0).toUpperCase(),
              sublabel: format(dateObj, 'd'),
              minutes: d.minutes,
              isToday: d.date === todayStr,
              key: d.date,
            };
          });
        }

        const maxMins = Math.max(...chartBars.map(x => x.minutes), 1);
        const totalMins = chartBars.reduce((s, d) => s + d.minutes, 0);
        const daysCount = flowRange === '3months' ? chartBars.length : filteredData.length;
        const avgMins = daysCount > 0 ? Math.round(totalMins / daysCount) : 0;
        const activeDays = chartBars.filter(d => d.minutes > 0).length;

        return (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-5">
          {/* Header with range tabs */}
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-sm font-medium text-gray-300 flex items-center gap-2">
              <BarChart3 size={14} className="text-blue-400" /> Flow Analytics
            </h2>
            <div className="flex gap-1 bg-[#111] rounded-lg p-0.5">
              {([['week', 'Semana'], ['month', 'Mês'], ['3months', '3 Meses']] as const).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setFlowRange(key)}
                  className={`px-3 py-1 text-[11px] rounded-md transition-all ${
                    flowRange === key
                      ? 'bg-blue-600 text-white font-medium shadow-sm'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          {/* Stats row */}
          <div className="flex gap-3 text-xs mb-4">
            <span className="text-gray-500">{rangeLabel}</span>
            <span className="text-gray-600">·</span>
            <span className="text-gray-500">Total <span className="text-white font-bold">{formatMinutes(totalMins)}</span></span>
            <span className="text-gray-500">Média <span className="text-blue-400 font-bold">{formatMinutes(avgMins)}</span>{flowRange === '3months' ? '/sem' : '/dia'}</span>
            <span className="text-gray-500">Ativos <span className="text-green-400 font-bold">{activeDays}</span>/{chartBars.length}</span>
          </div>
          {/* Chart */}
          <div className={`flex ${flowRange === '3months' ? 'gap-[3px]' : 'gap-[5px]'}`}>
            {chartBars.map(d => {
              const pct = (d.minutes / maxMins) * 100;
              return (
                <div
                  key={d.key}
                  className="flex-1 flex flex-col items-center group"
                  title={`${d.label} ${d.sublabel}: ${d.minutes}min`}
                >
                  <div className="w-full h-28 flex flex-col justify-end items-center">
                    {d.minutes > 0 && (
                      <span className={`text-[10px] font-bold mb-1 opacity-0 group-hover:opacity-100 transition-opacity ${d.isToday ? 'text-blue-400' : 'text-blue-300'}`}>
                        {d.minutes >= 60 ? `${Math.round(d.minutes / 60)}h${d.minutes % 60 > 0 ? d.minutes % 60 + 'm' : ''}` : `${d.minutes}m`}
                      </span>
                    )}
                    <div
                      className={`${flowRange === '3months' ? 'w-[80%]' : 'w-[65%] group-hover:w-[80%]'} rounded-md transition-all duration-200 ${
                        d.isToday
                          ? 'bg-gradient-to-t from-blue-600 to-blue-400 shadow-md shadow-blue-500/25'
                          : d.minutes > 0
                            ? 'bg-gradient-to-t from-blue-600/50 to-blue-400/30 group-hover:from-blue-600/70 group-hover:to-blue-400/50'
                            : 'bg-[#1e1e1e]'
                      }`}
                      style={{ height: d.minutes > 0 ? `${Math.max(pct, 8)}%` : '2px' }}
                    />
                  </div>
                  <span className={`text-[10px] mt-1.5 font-medium ${d.isToday ? 'text-blue-400' : 'text-gray-600'}`}>
                    {flowRange === '3months' ? '' : d.label}
                  </span>
                  <span className={`text-[9px] leading-tight ${d.isToday ? 'text-blue-400 font-bold' : 'text-gray-700'}`}>
                    {flowRange === '3months' ? d.sublabel : d.sublabel}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
        );
      })()}

      {/* Ambient Sounds (when idle) */}
      {phase === 'idle' && (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-5">
          <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
            <Music size={18} className="text-purple-400" /> Sons Ambiente
          </h2>
          <p className="text-xs text-gray-500 mb-4">Gerados localmente via Web Audio API — sem downloads</p>
          <div className="grid grid-cols-3 gap-3">
            {AMBIENT_SOUNDS.map(s => (
              <button
                key={s.id}
                onClick={() => generateNoise(s.id)}
                className={`p-4 rounded-xl text-center transition-all ${
                  activeSound === s.id
                    ? 'bg-purple-600/20 border border-purple-500/50 ring-1 ring-purple-500/30'
                    : 'bg-[#1a1a1a] border border-[#222] hover:border-[#333]'
                }`}
              >
                <span className="text-3xl block mb-2">{s.emoji}</span>
                <p className="text-sm font-medium">{s.label}</p>
                <p className="text-[10px] text-gray-500 mt-1">{s.desc}</p>
                {activeSound === s.id && (
                  <span className="text-[10px] text-purple-400 mt-1 block">▶ A reproduzir</span>
                )}
              </button>
            ))}
          </div>
          {activeSound && (
            <div className="flex items-center gap-3 mt-4">
              <VolumeX size={14} className="text-gray-500" />
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={soundVolume}
                onChange={e => setSoundVolume(parseFloat(e.target.value))}
                className="flex-1 accent-purple-500"
              />
              <Volume2 size={14} className="text-gray-500" />
              <button onClick={stopSound} className="px-3 py-1 bg-red-600/20 text-red-400 rounded-lg text-xs hover:bg-red-600/30">
                Parar
              </button>
            </div>
          )}
        </div>
      )}

      {/* Preset Modal */}
      {showPresetModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowPresetModal(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl border border-[#333] p-6 w-[440px] max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-bold">{editingPreset ? 'Editar Preset' : 'Novo Preset'}</h3>
              <button onClick={() => setShowPresetModal(false)} className="text-gray-500 hover:text-white"><X size={20} /></button>
            </div>

            <div className="space-y-4">
              {/* Name */}
              <div>
                <label className="text-xs text-gray-400 mb-1 block">Nome</label>
                <input type="text" value={presetForm.name}
                  onChange={e => setPresetForm(f => ({ ...f, name: e.target.value }))}
                  placeholder="Ex: Programming, Gym, Study..."
                  className="w-full bg-[#111] border border-[#333] rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-blue-500"
                />
              </div>

              {/* Work / Break */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">Foco (minutos)</label>
                  <input type="number" value={presetForm.work_minutes}
                    onChange={e => setPresetForm(f => ({ ...f, work_minutes: parseInt(e.target.value) || 0 }))}
                    min={1} max={180}
                    className="w-full bg-[#111] border border-[#333] rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">Pausa (minutos)</label>
                  <input type="number" value={presetForm.break_minutes}
                    onChange={e => setPresetForm(f => ({ ...f, break_minutes: parseInt(e.target.value) || 0 }))}
                    min={0} max={60}
                    className="w-full bg-[#111] border border-[#333] rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              {/* Icon */}
              <div>
                <label className="text-xs text-gray-400 mb-1 block">Ícone</label>
                <div className="flex flex-wrap gap-2">
                  {PRESET_ICONS.map(icon => (
                    <button key={icon} onClick={() => setPresetForm(f => ({ ...f, icon }))}
                      className={`w-10 h-10 rounded-xl text-xl flex items-center justify-center transition-colors ${
                        presetForm.icon === icon ? 'bg-white/15 ring-2 ring-blue-500' : 'bg-[#111] hover:bg-white/10'
                      }`}>
                      {icon}
                    </button>
                  ))}
                </div>
              </div>

              {/* Color */}
              <div>
                <label className="text-xs text-gray-400 mb-1 block">Cor</label>
                <div className="flex flex-wrap gap-2">
                  {PRESET_COLORS.map(c => (
                    <button key={c} onClick={() => setPresetForm(f => ({ ...f, color: c }))}
                      className={`w-8 h-8 rounded-full transition-transform ${
                        presetForm.color === c ? 'ring-2 ring-white scale-110' : 'hover:scale-105'
                      }`}
                      style={{ backgroundColor: c }}
                    />
                  ))}
                </div>
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowPresetModal(false)}
                className="flex-1 px-4 py-2.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm font-medium">
                Cancelar
              </button>
              <button onClick={savePreset}
                className="flex-1 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 rounded-xl text-sm font-medium">
                {editingPreset ? 'Guardar' : 'Criar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Forest-style Growing Tree ─────────────────────────────────
// Shows a plant that grows based on progress (0..1). Inspired by the Forest app.
// If `paused` is true the tree has a gentle sway animation; if `dead` is true
// (session abandoned early) it shows a wilted state.

function ForestTree({ progress, paused, dead }: { progress: number; paused?: boolean; dead?: boolean }) {
  const p = Math.max(0, Math.min(1, progress));

  // Stage thresholds
  const seedStage = p < 0.10;
  const sproutStage = p >= 0.10 && p < 0.25;
  const saplingStage = p >= 0.25 && p < 0.45;
  const smallTreeStage = p >= 0.45 && p < 0.70;
  const mediumTreeStage = p >= 0.70 && p < 0.95;
  const fullTreeStage = p >= 0.95;

  const stageLabel = dead
    ? '💀 Árvore morreu'
    : seedStage ? '🌱 Semente a germinar'
    : sproutStage ? '🌿 Rebento'
    : saplingStage ? '🌱 Muda'
    : smallTreeStage ? '🌲 Árvore jovem'
    : mediumTreeStage ? '🌳 Árvore'
    : '🎄 Árvore adulta!';

  // Colors
  const leafColor = dead ? '#6B5A3E' : '#22C55E';
  const leafColorDark = dead ? '#4A3E28' : '#15803D';
  const trunkColor = dead ? '#3A2E20' : '#78350F';
  const trunkColorLight = dead ? '#4A3A28' : '#92400E';
  const soilColor = '#3E2A14';

  // Trunk grows with progress
  const trunkHeight = 10 + Math.max(0, p - 0.10) * 90; // 10..100
  const trunkWidth = 4 + Math.max(0, p - 0.10) * 14;   // 4..18
  const canopyRadius = p < 0.25 ? 0 : 10 + (p - 0.25) * 80; // 0..70

  const trunkBottomY = 170;
  const trunkTopY = trunkBottomY - trunkHeight;

  return (
    <div className="flex flex-col items-center select-none">
      <svg viewBox="0 0 200 200" className={`w-64 h-64 ${paused && !dead ? 'opacity-60' : ''} ${dead ? 'opacity-70' : ''}`}>
        {/* Sky gradient background */}
        <defs>
          <radialGradient id="skyGrad" cx="50%" cy="40%" r="60%">
            <stop offset="0%" stopColor="#1e293b" stopOpacity="0.8" />
            <stop offset="100%" stopColor="#0f172a" stopOpacity="0.3" />
          </radialGradient>
          <linearGradient id="leafGrad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor={leafColor} />
            <stop offset="100%" stopColor={leafColorDark} />
          </linearGradient>
          <linearGradient id="trunkGrad" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={trunkColor} />
            <stop offset="50%" stopColor={trunkColorLight} />
            <stop offset="100%" stopColor={trunkColor} />
          </linearGradient>
        </defs>
        <rect x="0" y="0" width="200" height="200" fill="url(#skyGrad)" rx="12" />

        {/* Soil / ground mound */}
        <ellipse cx="100" cy="180" rx="60" ry="8" fill={soilColor} opacity="0.6" />
        <ellipse cx="100" cy="175" rx="45" ry="6" fill="#4B3A1A" opacity="0.5" />

        {/* Seed */}
        {seedStage && (
          <g>
            <ellipse cx="100" cy="170" rx="6" ry="8" fill="#92400E" />
            <ellipse cx="98" cy="167" rx="2" ry="3" fill="#A85C1C" />
          </g>
        )}

        {/* Sprout — little curved stem with 2 leaves */}
        {sproutStage && (
          <g>
            <path d={`M 100 170 Q 98 ${165 - (p - 0.10) * 120} 100 ${155 - (p - 0.10) * 150}`}
              stroke={leafColor} strokeWidth="2" fill="none" />
            <ellipse cx={96} cy={158 - (p - 0.10) * 140} rx="4" ry="3" fill={leafColor} transform={`rotate(-30 96 ${158 - (p - 0.10) * 140})`} />
            <ellipse cx={104} cy={158 - (p - 0.10) * 140} rx="4" ry="3" fill={leafColor} transform={`rotate(30 104 ${158 - (p - 0.10) * 140})`} />
          </g>
        )}

        {/* Trunk (sapling and beyond) */}
        {(saplingStage || smallTreeStage || mediumTreeStage || fullTreeStage) && (
          <>
            <rect
              x={100 - trunkWidth / 2}
              y={trunkTopY}
              width={trunkWidth}
              height={trunkHeight}
              fill="url(#trunkGrad)"
              rx={trunkWidth / 2}
            />
            {/* Trunk bark detail */}
            {smallTreeStage || mediumTreeStage || fullTreeStage ? (
              <path
                d={`M ${100 - trunkWidth / 3} ${trunkBottomY - trunkHeight * 0.5} Q 100 ${trunkBottomY - trunkHeight * 0.45} ${100 + trunkWidth / 3} ${trunkBottomY - trunkHeight * 0.55}`}
                stroke={trunkColor} strokeWidth="1" fill="none" opacity="0.6"
              />
            ) : null}
          </>
        )}

        {/* Canopy */}
        {(saplingStage || smallTreeStage || mediumTreeStage || fullTreeStage) && (
          <g>
            {/* Main canopy circle */}
            <circle cx="100" cy={trunkTopY} r={canopyRadius} fill="url(#leafGrad)" />
            {/* Additional clumps for larger trees */}
            {(smallTreeStage || mediumTreeStage || fullTreeStage) && (
              <>
                <circle cx={100 - canopyRadius * 0.6} cy={trunkTopY + canopyRadius * 0.2} r={canopyRadius * 0.55} fill="url(#leafGrad)" />
                <circle cx={100 + canopyRadius * 0.6} cy={trunkTopY + canopyRadius * 0.2} r={canopyRadius * 0.55} fill="url(#leafGrad)" />
                <circle cx={100} cy={trunkTopY - canopyRadius * 0.5} r={canopyRadius * 0.6} fill="url(#leafGrad)" />
              </>
            )}
            {/* Fruits/flowers when fully grown */}
            {fullTreeStage && !dead && (
              <>
                <circle cx={100 - 20} cy={trunkTopY + 5} r="3" fill="#F472B6" />
                <circle cx={100 + 15} cy={trunkTopY - 10} r="3" fill="#FBBF24" />
                <circle cx={100 - 5} cy={trunkTopY - 25} r="3" fill="#F472B6" />
                <circle cx={100 + 25} cy={trunkTopY + 15} r="3" fill="#FBBF24" />
                {/* Sparkle */}
                <text x="100" y={trunkTopY - canopyRadius - 8} textAnchor="middle" fontSize="16">✨</text>
              </>
            )}
            {/* Sway animation when paused: subtle — but for now static via opacity */}
          </g>
        )}

        {/* Dead overlay — falling leaves */}
        {dead && (
          <g>
            <path d={`M ${100 + canopyRadius * 0.7} ${trunkTopY + canopyRadius * 0.8} L ${100 + canopyRadius * 0.9} 180`}
              stroke="#6B5A3E" strokeWidth="1" strokeDasharray="2 2" opacity="0.6" />
            <text x="100" y="30" textAnchor="middle" fontSize="20">💀</text>
          </g>
        )}

        {/* Grass tufts */}
        <g>
          <path d="M 60 178 L 62 172 L 64 178" stroke="#22C55E" strokeWidth="1.5" fill="none" opacity="0.6" />
          <path d="M 136 178 L 138 170 L 140 178" stroke="#22C55E" strokeWidth="1.5" fill="none" opacity="0.6" />
          <path d="M 75 180 L 77 174 L 79 180" stroke="#22C55E" strokeWidth="1.5" fill="none" opacity="0.5" />
          <path d="M 125 180 L 127 173 L 129 180" stroke="#22C55E" strokeWidth="1.5" fill="none" opacity="0.5" />
        </g>
      </svg>
      <p className={`text-xs mt-2 ${dead ? 'text-red-400' : 'text-green-400'}`}>{stageLabel}</p>
      <p className="text-[10px] text-gray-600 mt-0.5">
        {dead
          ? 'Perdeste esta sessão. Começa de novo e não pares!'
          : fullTreeStage
            ? 'Parabéns — árvore plenamente crescida!'
            : `A tua árvore está a crescer (${Math.round(p * 100)}%)`}
      </p>
    </div>
  );
}
