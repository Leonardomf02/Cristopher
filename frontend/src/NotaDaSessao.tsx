import { useEffect } from 'react';
import { Pencil, X } from 'lucide-react';
import type { LinhaDaNota } from './FlowContext';

/** A nota de uma sessão já fechada, como fica guardada no bloco do calendário. */
export function NotaDoBloco({ titulo, quando, linhas, cor, onEditar, onFechar }: {
  titulo: string;
  quando: string;
  linhas: LinhaDaNota[];
  cor: string;
  onEditar: () => void;
  onFechar: () => void;
}) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onFechar(); };
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, [onFechar]);

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onFechar}>
      <div className="w-[28rem] max-w-[90vw] max-h-[80dvh] flex flex-col rounded-2xl border bg-[#161616] shadow-2xl"
        style={{ borderColor: cor + '60' }} onClick={e => e.stopPropagation()}>
        <div className="flex items-start gap-2 px-5 py-4 border-b border-[#222] shrink-0">
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold truncate">{titulo}</h3>
            <p className="text-xs text-gray-500 mt-0.5">{quando}</p>
          </div>
          <button onClick={onFechar} className="p-1 rounded-lg text-gray-500 hover:text-white hover:bg-white/10">
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto px-5 py-3 space-y-2">
          {linhas.map((l, i) => (
            <div key={i} className="flex items-start gap-3">
              <span className="text-xs font-mono text-gray-500 pt-0.5 shrink-0">{l.hora}</span>
              <span className="text-sm break-words">{l.texto}</span>
            </div>
          ))}
        </div>
        <div className="px-5 py-3 border-t border-[#222] flex justify-end shrink-0">
          <button onClick={onEditar}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-white hover:bg-white/10">
            <Pencil size={12} /> Editar bloco
          </button>
        </div>
      </div>
    </div>
  );
}
