import { useState, useEffect, useRef, useLayoutEffect } from 'react';
import type { ClipboardEvent } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Note } from '../types';

export const scrollKey = (id: number) => `noteScroll:${id}`;
export const viewModeKey = (id: number) => `noteViewMode:${id}`;
export const pageKey = (id: number) => `notePage:${id}`;

export function ModeToggle({ mode, onChange }: { mode: 'scroll' | 'pages'; onChange: (m: 'scroll' | 'pages') => void }) {
  return (
    <div className="inline-flex rounded-lg bg-[#1a1a1a] border border-[#222] p-0.5 shrink-0">
      <button onClick={() => onChange('scroll')} title="Uma página com scroll"
        className={`px-2.5 py-1 rounded-md text-xs font-semibold transition-colors ${mode === 'scroll' ? 'bg-blue-500/20 text-blue-300' : 'text-gray-500 hover:text-gray-300'}`}>
        Scroll
      </button>
      <button onClick={() => onChange('pages')} title="Modo caderno (por páginas)"
        className={`px-2.5 py-1 rounded-md text-xs font-semibold transition-colors ${mode === 'pages' ? 'bg-blue-500/20 text-blue-300' : 'text-gray-500 hover:text-gray-300'}`}>
        Caderno
      </button>
    </div>
  );
}

// Conteúdo da nota partilhado pelo editor inline e pela vista de página inteira.
// mode='scroll' → textarea (guarda a posição); mode='pages' → caderno editável com
// páginas que cabem no ecrã (colunas CSS), sem scroll, com salto de página.
export function NoteBody({ note, mode, onContentChange, dense = false }: {
  note: Note;
  mode: 'scroll' | 'pages';
  onContentChange: (v: string) => void;
  dense?: boolean;
}) {
  const GAP = dense ? 40 : 48;
  const [page, setPage] = useState(() => Number(localStorage.getItem(pageKey(note.id)) || '0'));
  const [pageW, setPageW] = useState(0);
  const [pageH, setPageH] = useState(0);
  const [pageCount, setPageCount] = useState(1);
  const [empty, setEmpty] = useState(!note.content);
  const scrollRef = useRef<HTMLTextAreaElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const columnsRef = useRef<HTMLDivElement>(null);
  // O caderno é contentEditable: o DOM é a fonte enquanto se escreve, por isso só se
  // reescreve quando o texto muda por fora (outra nota, gravação vinda do servidor).
  const ownValue = useRef<string | null>(null);

  useEffect(() => { localStorage.setItem(pageKey(note.id), String(page)); }, [page, note.id]);

  // Modo scroll: restaura a posição onde deixei.
  useEffect(() => {
    if (mode !== 'scroll') return;
    const saved = Number(localStorage.getItem(scrollKey(note.id)) || '0');
    requestAnimationFrame(() => { if (scrollRef.current) scrollRef.current.scrollTop = saved; });
  }, [mode, note.id]);
  const saveScroll = () => {
    if (scrollRef.current) localStorage.setItem(scrollKey(note.id), String(scrollRef.current.scrollTop));
  };

  // Modo caderno: mede a página em píxeis (largura e altura da viewport). ResizeObserver
  // apanha a altura assim que o layout assenta, mesmo quando vem de flexbox.
  useLayoutEffect(() => {
    if (mode !== 'pages') return;
    const vp = viewportRef.current;
    if (!vp) return;
    // getBoundingClientRect (não clientWidth, que arredonda ao pixel) — dentro de
    // uma grid de colunas 1fr a largura real é fraccionária, e usar o inteiro
    // desviava o translateX por página, um desvio que se somava a cada avanço.
    const measure = () => {
      const r = vp.getBoundingClientRect();
      setPageW(r.width);
      setPageH(r.height);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(vp);
    return () => ro.disconnect();
  }, [mode]);

  // Semeia o texto no caderno quando ele aparece ou quando se muda de nota.
  useLayoutEffect(() => {
    const el = columnsRef.current;
    if (mode !== 'pages' || !el) return;
    el.innerText = note.content || '';
    ownValue.current = note.content || '';
    setEmpty(!note.content);
  }, [mode, note.id, pageW > 0 && pageH > 0]);

  // Actualizações vindas de fora enquanto o caderno está aberto.
  useLayoutEffect(() => {
    const el = columnsRef.current;
    if (mode !== 'pages' || !el) return;
    if ((note.content || '') === ownValue.current) return;
    el.innerText = note.content || '';
    ownValue.current = note.content || '';
    setEmpty(!note.content);
  }, [note.content]);

  // Conta as páginas a partir da largura total das colunas (altura fixa → paginação).
  const recount = () => {
    const el = columnsRef.current;
    if (!el || pageW <= 0 || pageH <= 0) return;
    const count = Math.max(1, Math.round((el.scrollWidth + GAP) / (pageW + GAP)));
    setPageCount(count);
    setPage(p => Math.min(Math.max(0, p), count - 1));
  };
  useLayoutEffect(() => {
    if (mode !== 'pages') return;
    recount();
  }, [mode, pageW, pageH, note.content, note.id]);

  // Posição horizontal do cursor. Um cursor colapsado costuma dar um rect vazio
  // (sobretudo no fim do texto), por isso mede-se o caractere ao lado.
  const caretX = (): number | null => {
    const el = columnsRef.current;
    const sel = window.getSelection();
    if (!el || !sel || sel.rangeCount === 0) return null;
    const range = sel.getRangeAt(0);
    if (!el.contains(range.startContainer)) return null;
    const r = range.getBoundingClientRect();
    if (r.width > 0 || r.height > 0) return r.left;

    const probe = range.cloneRange();
    const node = probe.startContainer;
    if (node.nodeType === Node.TEXT_NODE) {
      const len = node.textContent?.length ?? 0;
      if (probe.startOffset > 0) {
        probe.setStart(node, probe.startOffset - 1);
        const back = probe.getBoundingClientRect();
        if (back.width > 0 || back.height > 0) return back.right;
      }
      if (len > probe.startOffset) {
        probe.setEnd(node, probe.startOffset + 1);
        const fwd = probe.getBoundingClientRect();
        if (fwd.width > 0 || fwd.height > 0) return fwd.left;
      }
      return null;
    }
    const child = node.childNodes[Math.max(0, probe.startOffset - 1)];
    if (!child) return null;
    const around = document.createRange();
    around.selectNodeContents(child);
    const rc = around.getBoundingClientRect();
    return rc.width > 0 || rc.height > 0 ? rc.right : null;
  };

  // Vira a página sozinha quando o cursor passa para a coluna seguinte.
  const syncCaretPage = () => {
    const el = columnsRef.current;
    if (!el || pageW <= 0) return;
    const left = caretX();
    if (left === null) return;
    // O contentor está deslocado pelo translateX, por isso o rect dele já traz a
    // página actual: a diferença dá a posição do cursor no texto todo.
    const x = left - el.getBoundingClientRect().left;
    const p = Math.max(0, Math.floor(x / (pageW + GAP)));
    setPage(prev => (prev === p ? prev : p));
  };

  const onInput = () => {
    const el = columnsRef.current;
    if (!el) return;
    const value = el.innerText;
    ownValue.current = value;
    setEmpty(!value.trim());
    recount();
    onContentChange(value);
    requestAnimationFrame(syncCaretPage);
  };

  const onPaste = (e: ClipboardEvent) => {
    e.preventDefault();
    const text = e.clipboardData.getData('text/plain');
    document.execCommand('insertText', false, text);
  };

  const clampedPage = Math.min(Math.max(0, page), Math.max(0, pageCount - 1));
  const textCls = dense ? 'text-sm leading-relaxed' : 'text-base leading-relaxed';

  if (mode === 'scroll') {
    return (
      <textarea
        ref={scrollRef}
        value={note.content}
        onChange={e => onContentChange(e.target.value)}
        onScroll={saveScroll}
        placeholder="Começa a escrever..."
        className={`flex-1 min-h-0 w-full bg-transparent focus:outline-none resize-none placeholder-gray-600 ${textCls}`}
      />
    );
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div ref={viewportRef} className="relative flex-1 min-h-0 overflow-hidden">
        {pageW > 0 && pageH > 0 && (
          <>
            <div
              ref={columnsRef}
              contentEditable
              suppressContentEditableWarning
              spellCheck={false}
              onInput={onInput}
              onPaste={onPaste}
              onKeyUp={syncCaretPage}
              onMouseUp={syncCaretPage}
              className={`whitespace-pre-wrap break-words text-gray-200 focus:outline-none ${textCls}`}
              style={{
                height: `${pageH}px`,
                columnWidth: `${pageW}px`,
                columnGap: `${GAP}px`,
                columnFill: 'auto',
                transform: `translateX(${-(clampedPage * (pageW + GAP))}px)`,
                transition: 'transform .2s ease',
              }}
            />
            {empty && (
              <p className={`pointer-events-none absolute top-0 left-0 text-gray-600 ${textCls}`}>
                Começa a escrever...
              </p>
            )}
          </>
        )}
      </div>
      <div className="flex items-center justify-center gap-3 pt-3 shrink-0">
        <button onClick={() => setPage(p => Math.max(p - 1, 0))} disabled={clampedPage === 0}
          className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 disabled:opacity-30">
          <ChevronLeft size={18} />
        </button>
        <div className="flex items-center gap-1.5 text-xs text-gray-400">
          <span>Página</span>
          <input
            type="number" min={1} max={pageCount} value={clampedPage + 1}
            onChange={e => { const v = Number(e.target.value) - 1; if (!isNaN(v)) setPage(Math.max(0, Math.min(v, pageCount - 1))); }}
            className="w-12 bg-[#1a1a1a] border border-[#222] rounded px-1.5 py-0.5 text-center tabular-nums focus:outline-none focus:border-blue-500/50"
          />
          <span>/ {pageCount}</span>
        </div>
        <button onClick={() => setPage(p => Math.min(p + 1, pageCount - 1))} disabled={clampedPage >= pageCount - 1}
          className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 disabled:opacity-30">
          <ChevronRight size={18} />
        </button>
      </div>
    </div>
  );
}
