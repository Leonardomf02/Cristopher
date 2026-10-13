import { useEffect, useRef, useState } from 'react';
import { Play } from 'lucide-react';
import { useFlow } from './FlowContext';

/** O ▶ que arranca o cronómetro numa tarefa, com as durações à escolha.
 *
 *  Vive num sítio só porque aparece em quatro: as sugestões do calendário, a
 *  agenda de hoje, os reminders e os blocos do dia. "Sem fim" é `work_minutes: 0`
 *  — conta para cima e só fecha quando ele carrega em parar.
 *
 *  Começar **não** carimba nada — chegou a fazê-lo e estava errado: uma tarefa
 *  começada não é uma tarefa feita. `aoComecar` fica para quem precise de
 *  reagir ao arranque (nenhuma página o usa hoje). */
export function ComecarTarefa({ nome, cor = '#3B82F6', icone = '📝', aoComecar, tamanho = 13 }: {
  nome: string;
  cor?: string;
  icone?: string;
  aoComecar?: () => void;
  tamanho?: number;
}) {
  const { startTimer, phase } = useFlow();
  const [aberto, setAberto] = useState(false);
  const caixaRef = useRef<HTMLSpanElement | null>(null);

  // Fechar por clique fora sem tapar o ecrã com um `fixed inset-0`: essa manta
  // apanhava o primeiro clique em tudo o resto (os botões de editar e apagar da
  // agenda deixavam de responder à primeira).
  useEffect(() => {
    if (!aberto) return;
    const fora = (e: MouseEvent) => {
      if (!caixaRef.current?.contains(e.target as Node)) setAberto(false);
    };
    document.addEventListener('mousedown', fora);
    return () => document.removeEventListener('mousedown', fora);
  }, [aberto]);

  function arranca(minutos: number) {
    startTimer({
      id: 0, name: nome, work_minutes: minutos,
      break_minutes: minutos >= 90 ? 10 : 5, color: cor, icon: icone,
    });
    setAberto(false);
    aoComecar?.();
  }

  return (
    <span ref={caixaRef} className="relative shrink-0">
      <button
        onClick={e => { e.stopPropagation(); setAberto(v => !v); }}
        disabled={phase !== 'idle'}
        title={phase !== 'idle' ? 'Já tens um timer a correr' : 'Começar agora'}
        className="block p-1 rounded-lg text-gray-500 hover:text-blue-300 hover:bg-white/10 disabled:opacity-30"
      >
        <Play size={tamanho} />
      </button>

      {aberto && (
        <span className="absolute right-0 top-full z-40 mt-1 flex items-center gap-1 rounded-xl border border-[#222]
          bg-[#161616] px-2 py-1.5 shadow-2xl" onClick={e => e.stopPropagation()}>
            {[25, 50, 90, 120].map(min => (
              <button key={min} onClick={() => arranca(min)}
                className="rounded-lg bg-white/[0.06] px-2 py-1 text-[11px] text-gray-300 hover:bg-white/[0.12]">
                {min >= 60 ? `${min / 60}h`.replace('.5h', 'h30') : `${min}min`}
              </button>
            ))}
          <button onClick={() => arranca(0)} title="Conta para cima até carregares em parar"
            className="rounded-lg bg-emerald-500/15 px-2 py-1 text-[11px] text-emerald-300 hover:bg-emerald-500/25">
            sem fim
          </button>
        </span>
      )}
    </span>
  );
}
