import { createContext, useContext, useState, useEffect, useRef, useCallback, type ReactNode } from 'react';
import { format } from 'date-fns';
import { flowApi, eventsApi } from './api';
import { notifyFlowWorkDone, notifyFlowBreakDone, requestNotificationPermission } from './notifications';

// ── Types ───────────────────────────────────────────────────────

export interface FlowPreset {
  id: number;
  name: string;
  // 0 = sem fim: conta para cima até ele parar. Uma tarefa sem duração definida
  // não é uma sessão de 8h — é uma sessão que ainda não se sabe quanto dura.
  work_minutes: number;
  break_minutes: number;
  color: string;
  icon: string;
}

export type TimerPhase = 'idle' | 'work' | 'break';

/** Uma linha da nota da sessão. A hora é a de quando foi escrita, e não muda
 *  se a linha for corrigida depois — é o registo de quando a ideia surgiu. */
export interface LinhaDaNota { hora: string; texto: string }

// A nota viaja na descrição do bloco do calendário, por baixo da linha "Flow:",
// uma linha por entrada ("15:18 organizar agenda"). Texto simples de propósito:
// lê-se em qualquer sítio que mostre a descrição, e o calendário sabe desenhá-la.
export function textoDaNota(linhas: LinhaDaNota[]): string {
  return linhas.map(l => `${l.hora} ${l.texto}`).join('\n');
}

export function linhasDaDescricao(descricao: string | null | undefined): LinhaDaNota[] {
  if (!descricao?.startsWith('Flow:')) return [];
  return descricao.split('\n').slice(1).flatMap(l => {
    const m = /^(\d{2}:\d{2}) (.+)$/.exec(l.trim());
    return m ? [{ hora: m[1], texto: m[2] }] : [];
  });
}

interface FlowContextValue {
  phase: TimerPhase;
  secondsLeft: number;
  isPaused: boolean;
  activePreset: FlowPreset | null;
  elapsedWorkSeconds: number;
  sessionVersion: number;
  alarmActive: boolean;
  nota: LinhaDaNota[];
  notaAberta: boolean;
  setNotaAberta: (aberta: boolean) => void;
  acrescentaNaNota: (texto: string) => void;
  editaNaNota: (i: number, texto: string) => void;
  apagaDaNota: (i: number) => void;
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

// O timer vivia só em memória: um F5 e a sessão desaparecia como se nunca
// tivesse existido. Fica guardado, e ao voltar avança-se o relógio pelo tempo
// real que passou — o cronómetro conta enquanto a página está fechada, que é o
// que acontece na vida.
const CHAVE_SESSAO = 'flow_sessao';

type SessaoGuardada = {
  preset: FlowPreset; startedAt: string; phase: TimerPhase;
  secondsLeft: number; isPaused: boolean; elapsed: number; savedAt: string;
  nota?: LinhaDaNota[];
};

function leSessaoGuardada(): SessaoGuardada | null {
  try {
    const raw = localStorage.getItem(CHAVE_SESSAO);
    if (!raw) return null;
    const g = JSON.parse(raw) as SessaoGuardada;
    if (!g?.preset || !g.startedAt || g.phase === 'idle') return null;
    const passou = Math.max(0, Math.round((Date.now() - new Date(g.savedAt).getTime()) / 1000));
    if (g.isPaused) return g;
    return {
      ...g,
      secondsLeft: Math.max(0, g.secondsLeft - passou),
      elapsed: g.phase === 'work' ? g.elapsed + passou : g.elapsed,
    };
  } catch {
    return null;
  }
}

export function FlowProvider({ children }: { children: ReactNode }) {
  const guardada = leSessaoGuardada();
  const [phase, setPhase] = useState<TimerPhase>(guardada?.phase ?? 'idle');
  const [secondsLeft, setSecondsLeft] = useState(guardada?.secondsLeft ?? 0);
  const [isPaused, setIsPaused] = useState(guardada?.isPaused ?? false);
  const [activePreset, setActivePreset] = useState<FlowPreset | null>(guardada?.preset ?? null);
  const [sessionStartTime, setSessionStartTime] = useState<Date | null>(
    guardada ? new Date(guardada.startedAt) : null);
  const [elapsedWorkSeconds, setElapsedWorkSeconds] = useState(guardada?.elapsed ?? 0);
  const [sessionVersion, setSessionVersion] = useState(0);
  const [alarmActive, setAlarmActive] = useState(false);
  const [nota, setNota] = useState<LinhaDaNota[]>(guardada?.nota ?? []);
  const [notaAberta, setNotaAberta] = useState(false);

  // Fechar a sessão é uma coisa que só pode acontecer uma vez: sem esta trava,
  // cada carregada no botão de parar (e ele carregou várias, porque demorava)
  // gravava outra sessão e outro evento. Foram cinco cópias da mesma.
  const aFecharRef = useRef(false);
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

  useEffect(() => {
    if (phase === 'idle' || !activePreset || !sessionStartTime) {
      localStorage.removeItem(CHAVE_SESSAO);
      return;
    }
    const estado: SessaoGuardada = {
      preset: activePreset, startedAt: sessionStartTime.toISOString(), phase,
      secondsLeft, isPaused, elapsed: elapsedWorkSeconds, savedAt: new Date().toISOString(), nota,
    };
    try { localStorage.setItem(CHAVE_SESSAO, JSON.stringify(estado)); } catch { /* cheio */ }
  }, [phase, secondsLeft, isPaused, activePreset, sessionStartTime, elapsedWorkSeconds, nota]);

  // ── Tick ────────────────────────────────────────────────
  const tick = useCallback(() => {
    setSecondsLeft(prev => (prev <= 1 ? 0 : prev - 1));

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
    // Um timer sem fim (work_minutes 0) nunca dispara aqui: acaba quando ele
    // carrega em parar, e é aí que a sessão é gravada com o tempo real.
    if (secondsLeft === 0 && phase === 'work' && !isPaused && activePreset
        && activePreset.work_minutes > 0) {
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
    aFecharRef.current = false;
    stopAlarmSound();
    requestNotificationPermission();
    setActivePreset(preset);
    setPhase('work');
    setSecondsLeft(Math.max(0, preset.work_minutes) * 60);
    setIsPaused(false);
    setElapsedWorkSeconds(0);
    setSessionStartTime(new Date());
    setNota([]);
  }

  function acrescentaNaNota(texto: string) {
    const t = texto.trim();
    if (t) setNota(n => [...n, { hora: format(new Date(), 'HH:mm'), texto: t }]);
  }

  function editaNaNota(i: number, texto: string) {
    const t = texto.trim();
    setNota(n => t ? n.map((l, j) => j === i ? { ...l, texto: t } : l) : n.filter((_, j) => j !== i));
  }

  function apagaDaNota(i: number) {
    setNota(n => n.filter((_, j) => j !== i));
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
    if (aFecharRef.current) return;
    const preset = activePreset;
    const inicio = sessionStartTime;
    if (!preset || !inicio) return;
    aFecharRef.current = true;
    stopAlarmSound();

    const now = new Date();
    const actualMinutes = Math.round(elapsedWorkSeconds / 60);
    const startStr = format(inicio, 'HH:mm');
    const endStr = format(now, 'HH:mm');
    const dateStr = format(inicio, 'yyyy-MM-dd');
    const notaStr = textoDaNota(nota);

    // O ecrã pára já — gravar vem depois. Era o contrário, e parar demorava o
    // tempo de dois pedidos à rede com o botão ainda a responder a cliques.
    setPhase('idle');
    setSecondsLeft(0);
    setIsPaused(false);
    setActivePreset(null);
    setSessionStartTime(null);
    setElapsedWorkSeconds(0);
    setNota([]);
    setNotaAberta(false);
    localStorage.removeItem(CHAVE_SESSAO);

    // Dois pedidos independentes: se a sessão falhar a gravar, o bloco no
    // calendário entra na mesma (e ao contrário). Antes partilhavam o try e uma
    // falha comia as duas coisas.
    try {
      await flowApi.createSession({
        preset_id: preset.id > 0 ? preset.id : null,  // 0 = bloco do planeador (sem preset)
        preset_name: preset.name,
        date: dateStr,
        start_time: startStr,
        end_time: endStr,
        planned_minutes: preset.work_minutes,
        actual_minutes: actualMinutes,
        completed,
        color: preset.color,
        notes: notaStr,
      });
    } catch (err) {
      console.error('Falhou a gravar a sessão de flow:', err);
    }

    try {
      // Com nota, o bloco entra mesmo abaixo de um minuto: é no calendário que
      // ela se volta a ler, e sem bloco ficava só na sessão, onde não se vê.
      if (actualMinutes >= 1 || notaStr) {
        const resumo = `Flow: ${actualMinutes}min${completed ? ' (completo)' : preset.work_minutes > 0 ? ` / ${preset.work_minutes}min` : ' (sem fim)'}`;
        await eventsApi.create({
          title: `${preset.icon} ${preset.name}`,
          description: notaStr ? `${resumo}\n${notaStr}` : resumo,
          date: dateStr,
          start_time: startStr,
          end_time: endStr,
          event_type: 'fixed',
          category: 'work',
          color: preset.color,
          completed: true,
        });
      }
    } catch (err) {
      console.error('Falhou a criar o bloco no calendário:', err);
    }

    setSessionVersion(v => v + 1);
    aFecharRef.current = false;
  }

  return (
    <FlowContext.Provider value={{
      phase, secondsLeft, isPaused, activePreset, elapsedWorkSeconds, sessionVersion,
      alarmActive, nota, notaAberta, setNotaAberta, acrescentaNaNota, editaNaNota, apagaDaNota,
      startTimer, togglePause, stopTimer, skipBreak, dismissAlarm,
    }}>
      {children}
    </FlowContext.Provider>
  );
}
