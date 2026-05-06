import { createContext, useContext, useState, useEffect, useRef, useCallback, type ReactNode } from 'react';
import { format } from 'date-fns';
import { flowApi, eventsApi } from './api';
import { notifyFlowWorkDone, notifyFlowBreakDone, requestNotificationPermission } from './notifications';

// ── Types ───────────────────────────────────────────────────────

export interface FlowPreset {
  id: number;
  name: string;
  work_minutes: number;
  break_minutes: number;
  color: string;
  icon: string;
}

export type TimerPhase = 'idle' | 'work' | 'break';

interface FlowContextValue {
  phase: TimerPhase;
  secondsLeft: number;
  isPaused: boolean;
  activePreset: FlowPreset | null;
  elapsedWorkSeconds: number;
  sessionVersion: number;
  alarmActive: boolean;
  startTimer: (preset: FlowPreset) => void;
  togglePause: () => void;
  stopTimer: () => Promise<void>;
  skipBreak: () => void;
  dismissAlarm: () => void;
}

const FlowContext = createContext<FlowContextValue | null>(null);

export function useFlow() {
  const ctx = useContext(FlowContext);
  if (!ctx) throw new Error('useFlow must be inside FlowProvider');
  return ctx;
}

// ── Provider ────────────────────────────────────────────────────

export function FlowProvider({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<TimerPhase>('idle');
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [isPaused, setIsPaused] = useState(false);
  const [activePreset, setActivePreset] = useState<FlowPreset | null>(null);
  const [sessionStartTime, setSessionStartTime] = useState<Date | null>(null);
  const [elapsedWorkSeconds, setElapsedWorkSeconds] = useState(0);
  const [sessionVersion, setSessionVersion] = useState(0);
  const [alarmActive, setAlarmActive] = useState(false);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const alarmCtxRef = useRef<AudioContext | null>(null);
  const alarmIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const titleIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const originalTitle = useRef(document.title);

  // ── Alarm Sound (Web Audio API) ─────────────────────────
  const playAlarmSound = useCallback(() => {
    try {
      const ctx = new AudioContext();
      alarmCtxRef.current = ctx;

      const playBeep = (time: number, freq: number, dur: number) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.frequency.setValueAtTime(freq, time);
        osc.type = 'sine';
        gain.gain.setValueAtTime(0, time);
        gain.gain.linearRampToValueAtTime(0.4, time + 0.02);
        gain.gain.linearRampToValueAtTime(0, time + dur);
        osc.start(time);
        osc.stop(time + dur);
      };

      // Play 3 ascending beeps
      const now = ctx.currentTime;
      playBeep(now, 587, 0.2);       // D5
      playBeep(now + 0.25, 740, 0.2); // F#5
      playBeep(now + 0.5, 880, 0.4);  // A5

      // Repeat every 3 seconds until dismissed
      alarmIntervalRef.current = setInterval(() => {
        try {
          const t = ctx.currentTime;
          playBeep(t, 587, 0.2);
          playBeep(t + 0.25, 740, 0.2);
          playBeep(t + 0.5, 880, 0.4);
        } catch {}
      }, 3000);
    } catch {}
  }, []);

  const stopAlarmSound = useCallback(() => {
    if (alarmIntervalRef.current) {
      clearInterval(alarmIntervalRef.current);
      alarmIntervalRef.current = null;
    }
    if (alarmCtxRef.current) {
      alarmCtxRef.current.close().catch(() => {});
      alarmCtxRef.current = null;
    }
    if (titleIntervalRef.current) {
      clearInterval(titleIntervalRef.current);
      titleIntervalRef.current = null;
    }
    document.title = originalTitle.current;
    setAlarmActive(false);
  }, []);

  const triggerAlarm = useCallback((message: string) => {
    setAlarmActive(true);
    playAlarmSound();

    // Flash tab title
    let toggle = false;
    originalTitle.current = document.title;
    titleIntervalRef.current = setInterval(() => {
      document.title = toggle ? message : '⏰ ' + message;
      toggle = !toggle;
    }, 1000);
  }, [playAlarmSound]);

  const dismissAlarm = useCallback(() => {
    stopAlarmSound();
  }, [stopAlarmSound]);

  // ── Tick ────────────────────────────────────────────────
  const tick = useCallback(() => {
    setSecondsLeft(prev => {
      if (prev <= 1) {
        return 0;
      }
      return prev - 1;
    });

    if (phase === 'work') {
      setElapsedWorkSeconds(prev => prev + 1);
    }
  }, [phase]);

  useEffect(() => {
    if ((phase === 'work' || phase === 'break') && !isPaused) {
      timerRef.current = setInterval(tick, 1000);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [phase, isPaused, tick]);

  // Phase transitions
  useEffect(() => {
    if (secondsLeft === 0 && phase === 'work' && !isPaused && activePreset) {
      if (elapsedWorkSeconds > 0) {
        notifyFlowWorkDone(activePreset.name);
        triggerAlarm(`${activePreset.name} — Sessão terminada!`);
        setPhase('break');
        setSecondsLeft(activePreset.break_minutes * 60);
      }
    } else if (secondsLeft === 0 && phase === 'break' && !isPaused) {
      notifyFlowBreakDone();
      triggerAlarm('Pausa terminada!');
      handleSessionComplete(true);
    }
  }, [secondsLeft, phase, isPaused]);

  // ── Actions ─────────────────────────────────────────────
  function startTimer(preset: FlowPreset) {
    stopAlarmSound();
    requestNotificationPermission();
    setActivePreset(preset);
    setPhase('work');
    setSecondsLeft(preset.work_minutes * 60);
    setIsPaused(false);
    setElapsedWorkSeconds(0);
    setSessionStartTime(new Date());
  }

  function togglePause() {
    setIsPaused(prev => !prev);
  }

  async function stopTimer() {
    if (!activePreset || !sessionStartTime) return;
    await handleSessionComplete(false);
  }

  function skipBreak() {
    stopAlarmSound();
    handleSessionComplete(true);
  }

  async function handleSessionComplete(completed: boolean) {
    stopAlarmSound();
    if (!activePreset || !sessionStartTime) return;

    const now = new Date();
    const actualMinutes = Math.round(elapsedWorkSeconds / 60);
    const startStr = format(sessionStartTime, 'HH:mm');
    const endStr = format(now, 'HH:mm');
    const dateStr = format(sessionStartTime, 'yyyy-MM-dd');

    try {
      await flowApi.createSession({
        preset_id: activePreset.id,
        preset_name: activePreset.name,
        date: dateStr,
        start_time: startStr,
        end_time: endStr,
        planned_minutes: activePreset.work_minutes,
        actual_minutes: actualMinutes,
        completed,
        color: activePreset.color,
      });

      if (actualMinutes >= 1) {
        await eventsApi.create({
          title: `${activePreset.icon} ${activePreset.name}`,
          description: `Flow: ${actualMinutes}min${completed ? ' (completo)' : ` / ${activePreset.work_minutes}min`}`,
          date: dateStr,
          start_time: startStr,
          end_time: endStr,
          event_type: 'fixed',
          category: 'work',
          color: activePreset.color,
          completed: true,
        });
      }
    } catch (err) {
      console.error('Failed to save flow session:', err);
    }

    // Reset
    setPhase('idle');
    setSecondsLeft(0);
    setIsPaused(false);
    setActivePreset(null);
    setSessionStartTime(null);
    setElapsedWorkSeconds(0);
    setSessionVersion(v => v + 1);
  }

  return (
    <FlowContext.Provider value={{
      phase, secondsLeft, isPaused, activePreset, elapsedWorkSeconds, sessionVersion,
      alarmActive, startTimer, togglePause, stopTimer, skipBreak, dismissAlarm,
    }}>
      {children}
    </FlowContext.Provider>
  );
}
