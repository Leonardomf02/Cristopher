import { useState, useEffect, useRef, useLayoutEffect } from 'react';
import { format } from 'date-fns';
import { pt } from 'date-fns/locale';
import { ComecarTarefa } from '../ComecarTarefa';
import {
  Plus, X, Trash2, Check, Flag, Calendar, GripVertical, Pencil,
  FileText, ChevronDown, RefreshCw, ArrowRightLeft,
} from 'lucide-react';
import { listsApi } from '../api';
import { UserList, ListItem } from '../types';

const LIST_COLORS = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#06B6D4', '#F97316'];
const LIST_ICONS = ['🛒', '📝', '🎁', '📦', '🎯', '💡', '📚', '🏋️', '🎮', '✈️', '🍔', '💊'];
const PRIORITY_LABELS = [
  { value: 0, label: 'Nenhuma', color: 'text-gray-500' },
  { value: 1, label: 'Baixa', color: 'text-blue-400', icon: '!' },
  { value: 2, label: 'Média', color: 'text-yellow-400', icon: '!!' },
  { value: 3, label: 'Alta', color: 'text-red-400', icon: '!!!' },
];

/** A data em que o reminder foi apontado. O ano só aparece quando não é este —
 *  "12 mai 2025" diz o que é preciso, "12 mai" chega para o ano corrente. */
/** A data em que o reminder foi apontado (ou feito). O ano só aparece quando não
 *  é este — "12 mai 2025" diz o que é preciso, "12 mai" chega para o ano
 *  corrente. */
type Campos = { notes: string; due_date: string | null; due_time: string | null; priority: number };

function dataCurta(iso: string): string {
  const d = new Date(iso);
  return format(d, d.getFullYear() === new Date().getFullYear() ? 'd MMM' : 'd MMM yyyy', { locale: pt });
}

export default function ListsPage() {
  const [lists, setLists] = useState<UserList[]>([]);
  const [selectedList, setSelectedList] = useState<UserList | null>(null);
  const [items, setItems] = useState<ListItem[]>([]);
  // O mesmo formulário cria e edita: sem `id` é uma lista nova, com `id` é a
  // lista que ele foi mexer.
  const [formLista, setFormLista] = useState<{ id?: number; name: string; icon: string; color: string } | null>(null);
  const [newItemText, setNewItemText] = useState('');
  // O que se escolhe para a nota nova enquanto se escreve (o mesmo painel da
  // edição). Some quando ela é adicionada.
  const RASCUNHO_VAZIO: Campos = { notes: '', due_date: null, due_time: null, priority: 0 };
  const [rascunho, setRascunho] = useState<Campos>(RASCUNHO_VAZIO);
  const [selectedItem, setSelectedItem] = useState<ListItem | null>(null);
  const [showCompletedItems, setShowCompletedItems] = useState(true);
  // Sincronização com o Reminders da Apple: corre sozinha de hora a hora, e o
  // botão é para quem não quer esperar pela hora certa.
  const [apple, setApple] = useState<{ disponivel: boolean; motivo?: string; last_run?: string; last_ok?: boolean; last_detail?: string } | null>(null);
  const [aSincronizar, setASincronizar] = useState(false);
  const [avisoApple, setAvisoApple] = useState('');

  useEffect(() => { initialLoad(); }, []);

  useEffect(() => { listsApi.appleStatus().then(setApple).catch(() => setApple(null)); }, []);

  async function sincronizaApple() {
    setASincronizar(true);
    setAvisoApple('');
    try {
      const r = await listsApi.appleSync();
      setAvisoApple(r.resumo);
      await loadLists();
      if (selectedList) await loadItems(selectedList.id);
      listsApi.appleStatus().then(setApple).catch(() => {});
    } catch (e: any) {
      setAvisoApple(e?.message || 'falhou');
    } finally {
      setASincronizar(false);
      setTimeout(() => setAvisoApple(''), 8000);
    }
  }

  async function initialLoad() {
    const data = await listsApi.list();
    setLists(data);
    if (data.length === 0) return;
    const savedId = Number(localStorage.getItem('reminders_last_list_id') || '');
    const target = data.find((l: UserList) => l.id === savedId) || data[0];
    setSelectedList(target);
    await loadItems(target.id);
  }

  async function loadLists() {
    const data = await listsApi.list();
    setLists(data);
    if (selectedList && !data.find((l: UserList) => l.id === selectedList.id)) {
      const next = data[0] || null;
      setSelectedList(next);
      if (next) {
        localStorage.setItem('reminders_last_list_id', String(next.id));
        loadItems(next.id);
      } else {
        localStorage.removeItem('reminders_last_list_id');
      }
    }
  }

  async function loadItems(listId: number) {
    const data = await listsApi.getItems(listId);
    setItems(data);
  }

  async function selectList(list: UserList) {
    setSelectedList(list);
    setSelectedItem(null);
    localStorage.setItem('reminders_last_list_id', String(list.id));
    await loadItems(list.id);
  }

  async function saveList() {
    if (!formLista?.name.trim()) return;
    const { id, ...dados } = formLista;
    if (id) {
      const atualizada = await listsApi.update(id, dados);
      setFormLista(null);
      await loadLists();
      if (selectedList?.id === id) setSelectedList(atualizada);
    } else {
      const criada = await listsApi.create(dados);
      setFormLista(null);
      await loadLists();
      selectList(criada);
    }
  }

  // ── Arrastar listas (rato: pega no ⠿; dedo/rato: long-press na linha) ──
  const rowRefs = useRef<(HTMLDivElement | null)[]>([]);
  const dragRef = useRef<{ from: number; startY: number; timer?: number; active: boolean; activate: () => void } | null>(null);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragDy, setDragDy] = useState(0);
  const [dropIndex, setDropIndex] = useState<number | null>(null);

  async function moveList(from: number, to: number) {
    if (from === to) return;
    const ordenadas = [...lists];
    const [movida] = ordenadas.splice(from, 1);
    ordenadas.splice(to, 0, movida);
    setLists(ordenadas);                                  // a ordem muda já, sem esperar pelo servidor
    try { await listsApi.reorder(ordenadas.map(l => l.id)); } catch { loadLists(); }
  }

  const onPointerDown = (e: React.PointerEvent, i: number, fromHandle: boolean) => {
    if (e.button !== 0) return;
    // long-press na linha não pode roubar o clique aos botões de editar e apagar
    if (!fromHandle && (e.target as HTMLElement).closest('button')) return;
    const el = e.currentTarget as HTMLElement;
    const pointerId = e.pointerId;
    const activate = () => {
      el.setPointerCapture?.(pointerId);                  // só se captura quando o drag arranca mesmo
      if (dragRef.current) dragRef.current.active = true;
      setDragIndex(i);
      setDropIndex(i);
      navigator.vibrate?.(10);
    };
    dragRef.current = { from: i, startY: e.clientY, active: false, activate };
    if (fromHandle) activate();
    else dragRef.current.timer = window.setTimeout(() => dragRef.current?.activate(), 350);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const st = dragRef.current;
    if (!st) return;
    const dy = e.clientY - st.startY;
    if (!st.active) {                                     // ainda em long-press: se scrollar, cancela
      if (Math.abs(dy) > 8) { clearTimeout(st.timer); dragRef.current = null; }
      return;
    }
    e.preventDefault();
    setDragDy(dy);
    const hit = rowRefs.current.findIndex((r, k) => {
      if (!r || k === st.from) return false;              // a linha arrastada acompanha o cursor
      const b = r.getBoundingClientRect();
      return e.clientY >= b.top && e.clientY <= b.bottom;
    });
    if (hit >= 0) setDropIndex(hit);
  };

  const onPointerUp = () => {
    const st = dragRef.current;
    if (st) clearTimeout(st.timer);
    if (st?.active && dropIndex !== null) moveList(st.from, dropIndex);
    dragRef.current = null;
    setDragIndex(null);
    setDragDy(0);
    setDropIndex(null);
  };

  // ── Arrastar um reminder para outra lista ──
  // Rato: agarra-se e arrasta-se. Dedo: toque longo e arrasta-se (como as
  // listas) — um toque curto continua a abrir a edição e um deslize continua a
  // rolar a página.
  const listasBoxRef = useRef<HTMLDivElement>(null);
  const itemDragRef = useRef<{ item: ListItem; x: number; y: number; timer?: number; active: boolean;
                               pointerId: number; el: HTMLElement; toque: boolean } | null>(null);
  const [itemArrastado, setItemArrastado] = useState<{ item: ListItem; x: number; y: number; toque?: boolean } | null>(null);
  const [listaAlvo, setListaAlvo] = useState<number | null>(null);
  const acabouDeArrastar = useRef(false);

  // Enquanto se arrasta, o dedo não rola a página.
  useEffect(() => {
    const trava = (ev: TouchEvent) => { if (itemDragRef.current?.active) ev.preventDefault(); };
    document.addEventListener('touchmove', trava, { passive: false });
    return () => document.removeEventListener('touchmove', trava);
  }, []);

  // O que ele escreve no iPhone chega à base sozinho, mas a página só lia uma
  // vez ao abrir: com ela aberta, o reminder novo ficava invisível até ao F5.
  const listaAbertaRef = useRef<number | null>(null);
  listaAbertaRef.current = selectedList?.id ?? null;
  useEffect(() => {
    const refresca = () => {
      if (document.hidden || itemDragRef.current?.active) return;
      listsApi.list().then(setLists).catch(() => {});
      const id = listaAbertaRef.current;
      if (id != null) {
        listsApi.getItems(id).then(data => {
          if (listaAbertaRef.current === id) setItems(data);
        }).catch(() => {});
      }
    };
    const t = window.setInterval(refresca, 20000);
    document.addEventListener('visibilitychange', refresca);
    window.addEventListener('focus', refresca);
    return () => {
      clearInterval(t);
      document.removeEventListener('visibilitychange', refresca);
      window.removeEventListener('focus', refresca);
    };
  }, []);

  function listaDebaixo(x: number, y: number): number | null {
    const k = rowRefs.current.findIndex(el => {
      if (!el) return false;
      const b = el.getBoundingClientRect();
      return x >= b.left && x <= b.right && y >= b.top && y <= b.bottom;
    });
    return k >= 0 ? lists[k]?.id ?? null : null;
  }

  function comecaArrastar(x: number, y: number) {
    const st = itemDragRef.current;
    if (!st) return;
    st.active = true;
    st.el.setPointerCapture?.(st.pointerId);
    setItemArrastado({ item: st.item, x, y, toque: st.toque });
    navigator.vibrate?.(10);
  }

  const itemPointerDown = (e: React.PointerEvent, item: ListItem) => {
    if (e.button !== 0) return;
    if ((e.target as HTMLElement).closest('button, textarea, input, select, a')) return;
    const st = { item, x: e.clientX, y: e.clientY, active: false, pointerId: e.pointerId,
                 el: e.currentTarget as HTMLElement, timer: undefined as number | undefined,
                 toque: e.pointerType !== 'mouse' };
    itemDragRef.current = st;
    if (e.pointerType !== 'mouse') {
      const { clientX, clientY } = e;
      st.timer = window.setTimeout(() => comecaArrastar(clientX, clientY), 350);
    }
  };

  const itemPointerMove = (e: React.PointerEvent) => {
    const st = itemDragRef.current;
    if (!st) return;
    const d = Math.hypot(e.clientX - st.x, e.clientY - st.y);
    if (!st.active) {
      if (e.pointerType === 'mouse') { if (d > 6) comecaArrastar(e.clientX, e.clientY); }
      else if (d > 8) { clearTimeout(st.timer); itemDragRef.current = null; }   // estava a rolar
      return;
    }
    e.preventDefault();
    setItemArrastado({ item: st.item, x: e.clientX, y: e.clientY, toque: st.toque });
    setListaAlvo(listaDebaixo(e.clientX, e.clientY));
    // No telemóvel as listas são uma fila que rola para o lado: encostar o dedo
    // à ponta leva-a a mostrar as que estão escondidas.
    const box = listasBoxRef.current;
    if (box && box.scrollWidth > box.clientWidth) {
      const b = box.getBoundingClientRect();
      if (e.clientY >= b.top - 20 && e.clientY <= b.bottom + 20) {
        if (e.clientX < b.left + 40) box.scrollLeft -= 14;
        else if (e.clientX > b.right - 40) box.scrollLeft += 14;
      }
    }
  };

  const itemPointerUp = (e: React.PointerEvent) => {
    const st = itemDragRef.current;
    itemDragRef.current = null;
    if (!st) return;
    clearTimeout(st.timer);
    if (!st.active) return;
    acabouDeArrastar.current = true;                    // o clique que vem a seguir não abre a edição
    setTimeout(() => { acabouDeArrastar.current = false; }, 0);
    const alvo = e.type === 'pointercancel' ? null : listaDebaixo(e.clientX, e.clientY);
    setItemArrastado(null);
    setListaAlvo(null);
    if (alvo && alvo !== st.item.list_id) moveItem(st.item, alvo);
  };

  async function moveItem(item: ListItem, listaId: number) {
    setItems(prev => prev.filter(i => i.id !== item.id));
    if (selectedItem?.id === item.id) setSelectedItem(null);
    try {
      await listsApi.updateItem(item.id, { list_id: listaId });
    } catch {
      if (selectedList) loadItems(selectedList.id);
    }
    loadLists();
  }

  function abreOuFecha(item: ListItem) {
    if (acabouDeArrastar.current) return;
    setSelectedItem(prev => prev?.id === item.id ? null : item);
  }

  async function deleteList(id: number) {
    const alvo = lists.find(l => l.id === id);
    if (!confirm(`Apagar a lista "${alvo?.name}" e os itens dela?`)) return;
    await listsApi.delete(id);
    if (selectedList?.id === id) {
      setSelectedList(null);
      setItems([]);
      setSelectedItem(null);
      localStorage.removeItem('reminders_last_list_id');
    }
    loadLists();
  }

  async function addItem() {
    if (!newItemText.trim() || !selectedList) return;
    await listsApi.addItem(selectedList.id, { text: newItemText.trim(), ...rascunho });
    setNewItemText('');
    setRascunho(RASCUNHO_VAZIO);
    loadItems(selectedList.id);
    loadLists();
  }

  async function toggleItem(item: ListItem) {
    await listsApi.updateItem(item.id, { checked: !item.checked });
    loadItems(selectedList!.id);
    loadLists();
    if (selectedItem?.id === item.id) {
      setSelectedItem({ ...item, checked: !item.checked });
    }
  }

  async function deleteItem(id: number) {
    await listsApi.deleteItem(id);
    if (selectedItem?.id === id) setSelectedItem(null);
    loadItems(selectedList!.id);
    loadLists();
  }

  async function updateItemField(itemId: number, field: string, value: any) {
    await listsApi.updateItem(itemId, { [field]: value });
    loadItems(selectedList!.id);
    if (selectedItem?.id === itemId) {
      setSelectedItem(prev => prev ? { ...prev, [field]: value } : null);
    }
  }

  function getPriorityInfo(priority: number) {
    return PRIORITY_LABELS.find(p => p.value === priority) || PRIORITY_LABELS[0];
  }

  function isOverdue(item: ListItem) {
    if (!item.due_date || item.checked) return false;
    return new Date(item.due_date) < new Date(format(new Date(), 'yyyy-MM-dd'));
  }

  // Notas, data limite e prioridade: o mesmo painel para a nota que se está a
  // escrever e para a que se está a editar. `muda` actualiza o que se vê;
  // `grava` guarda (na nota nova não há nada para gravar até ela ser adicionada).
  function renderCampos(v: Campos, muda: (campo: keyof Campos, valor: any) => void,
                        grava: (campo: keyof Campos, valor: any) => void = () => {}) {
    const altera = (campo: keyof Campos, valor: any) => { muda(campo, valor); grava(campo, valor); };
    return (
      <>
        <div>
          <label className="text-[11px] text-gray-500 mb-1 block flex items-center gap-1">
            <FileText size={11} /> Notas
          </label>
          <textarea
            value={v.notes || ''}
            onChange={e => muda('notes', e.target.value)}
            onBlur={e => grava('notes', e.target.value)}
            placeholder="Adicionar nota..."
            className="w-full bg-[#222] border border-[#333] rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:border-blue-500 resize-none min-h-[52px]"
          />
        </div>

        <div>
          <label className="text-[11px] text-gray-500 mb-1 block flex items-center gap-1">
            <Calendar size={11} /> Data limite
          </label>
          <div className="flex gap-1.5">
            <input
              type="date"
              value={v.due_date || ''}
              onChange={e => altera('due_date', e.target.value || null)}
              className="flex-1 bg-[#222] border border-[#333] rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:border-blue-500"
            />
            {v.due_date && (
              <input
                type="time"
                value={v.due_time || ''}
                onChange={e => altera('due_time', e.target.value || null)}
                className="w-24 bg-[#222] border border-[#333] rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:border-blue-500"
              />
            )}
          </div>
          {v.due_date && (
            <div className="flex gap-2 mt-1">
              <button
                type="button"
                onClick={() => { altera('due_date', null); altera('due_time', null); }}
                className="text-[11px] text-red-400 hover:underline"
              >
                Remover data
              </button>
              {v.due_time && (
                <button
                  type="button"
                  onClick={() => altera('due_time', null)}
                  className="text-[11px] text-gray-500 hover:underline"
                >
                  Remover hora
                </button>
              )}
            </div>
          )}
        </div>

        <div>
          <label className="text-[11px] text-gray-500 mb-1.5 block flex items-center gap-1">
            <Flag size={11} /> Prioridade
          </label>
          <div className="flex gap-1.5">
            {PRIORITY_LABELS.map(p => (
              <button
                key={p.value}
                type="button"
                onClick={() => altera('priority', p.value)}
                className={`flex-1 py-1.5 rounded-lg text-[11px] font-medium transition-all ${
                  v.priority === p.value
                    ? 'bg-white/10 ring-1 ring-white/20'
                    : 'bg-[#222] hover:bg-[#2a2a2a]'
                } ${p.color}`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      </>
    );
  }

  // Edição aberta dentro da própria nota (não é um modal ao lado): o texto
  // edita-se na própria linha do item (vira input enquanto está aberto),
  // aqui só ficam notas, data limite e prioridade. Compacta de propósito.
  function renderItemEditor(item: ListItem) {
    return (
      <div className="px-3 pb-3 pt-1 bg-white/[0.02] border-t border-[#1a1a1a] space-y-2.5">
        {renderCampos(
          item,
          (campo, valor) => setSelectedItem(prev => prev ? { ...prev, [campo]: valor } : null),
          (campo, valor) => updateItemField(item.id, campo, valor),
        )}

        {lists.length > 1 && (
          <div>
            <label className="text-[11px] text-gray-500 mb-1 block flex items-center gap-1">
              <ArrowRightLeft size={11} /> Mover para
            </label>
            <select value={item.list_id} onChange={e => moveItem(item, Number(e.target.value))}
              className="w-full bg-[#222] border border-[#333] rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:border-blue-500">
              {lists.map(l => <option key={l.id} value={l.id}>{l.icon} {l.name}</option>)}
            </select>
          </div>
        )}

        <div className="flex gap-1.5 pt-0.5">
          <button
            onClick={() => toggleItem(item)}
            className={`flex-1 py-1.5 rounded-lg text-[11px] font-medium transition-all ${
              item.checked
                ? 'bg-yellow-600/20 text-yellow-400 hover:bg-yellow-600/30'
                : 'bg-green-600/20 text-green-400 hover:bg-green-600/30'
            }`}
          >
            {item.checked ? 'Marcar como pendente' : 'Marcar como concluído'}
          </button>
          <button
            onClick={() => deleteItem(item.id)}
            className="flex-1 py-1.5 rounded-lg text-[11px] font-medium bg-red-600/10 text-red-400 hover:bg-red-600/20 transition-all"
          >
            Apagar
          </button>
        </div>
      </div>
    );
  }

  const uncheckedItems = items.filter(i => !i.checked).sort((a, b) => {
    // Sort by priority desc, then position
    if (b.priority !== a.priority) return b.priority - a.priority;
    return a.position - b.position;
  });
  const checkedItems = items.filter(i => i.checked);

  // Painéis com a mesma altura vertical que o Calendário usa na vista Dia:
  // mede-se o espaço livre até ao fundo do ecrã, em vez de um valor fixo.
  const gridRef = useRef<HTMLDivElement>(null);
  const [gridHeight, setGridHeight] = useState<number | null>(null);

  useLayoutEffect(() => {
    const medir = () => {
      const el = gridRef.current;
      if (!el) return;
      if (window.innerWidth < 1024) { setGridHeight(null); return; }
      const scroller = el.closest('main');
      const espaco = scroller ? scroller.clientHeight : window.innerHeight;
      const topo = scroller
        ? el.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop
        : el.getBoundingClientRect().top;
      let node: HTMLElement | null = el;
      while (node?.parentElement && node.parentElement !== scroller) node = node.parentElement;
      const folga = node ? parseFloat(getComputedStyle(node).paddingBottom) || 0 : 0;
      setGridHeight(Math.max(360, espaco - topo - folga - 4));
    };
    medir();
    const t = setTimeout(medir, 0);
    window.addEventListener('resize', medir);
    return () => { clearTimeout(t); window.removeEventListener('resize', medir); };
  }, []);

  return (
    <div>
      {/* O reminder que se está a arrastar, colado ao dedo/cursor. */}
      {itemArrastado && (
        // Preso dentro do ecrã, e no dedo vai por cima dele: por baixo, o dedo
        // tapava a lista onde se ia largar.
        <div className="fixed z-50 pointer-events-none w-max max-w-[min(70vw,420px)] truncate px-3 py-2 rounded-xl text-sm
                        bg-[#222] border border-blue-500/60 shadow-2xl shadow-black/50"
          style={{
            left: Math.max(8, Math.min(itemArrastado.x + 14, window.innerWidth - Math.min(window.innerWidth * 0.7, 420) - 8)),
            top: itemArrastado.toque ? Math.max(8, itemArrastado.y - 72) : itemArrastado.y + 14,
          }}>
          {itemArrastado.item.text}
          <span className="block text-[11px] text-gray-400">
            {listaAlvo && listaAlvo !== itemArrastado.item.list_id
              ? `largar em ${lists.find(l => l.id === listaAlvo)?.name}`
              : 'larga numa lista'}
          </span>
        </div>
      )}
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6 lg:mb-8">
        <div>
          <h2 className="text-2xl font-bold">Reminders</h2>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {avisoApple && <span className="text-xs text-gray-400">{avisoApple}</span>}
          {apple?.disponivel !== false && (
            <button onClick={sincronizaApple} disabled={aSincronizar}
              title={apple?.last_run
                ? `Reminders da Apple · última passagem ${new Date(apple.last_run).toLocaleString('pt-PT')}${apple.last_detail ? ` (${apple.last_detail})` : ''}`
                : 'Sincronizar com o Reminders da Apple'}
              className="flex items-center gap-2 px-3 py-2 bg-white/5 hover:bg-white/10 border border-[#222] rounded-xl text-sm font-medium disabled:opacity-50">
              <RefreshCw size={15} className={aSincronizar ? 'animate-spin' : ''} />
              <span className="hidden sm:inline">Apple</span>
            </button>
          )}
          <button onClick={() => setFormLista({ name: '', icon: '📝', color: '#3B82F6' })}
            className="flex items-center gap-2 px-3 sm:px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-xl text-sm font-medium">
            <Plus size={16} /> <span className="hidden sm:inline">Nova Lista</span><span className="sm:hidden">Lista</span>
          </button>
        </div>
      </div>

      <div ref={gridRef} className="flex flex-col lg:flex-row gap-3 lg:gap-6"
        style={gridHeight ? { height: `${gridHeight}px` } : undefined}>
        {/* Lists sidebar */}
        {/* No telemóvel as listas são uma fila que rola: uma por linha comia meio ecrã
            antes de se ver um único item. No computador continua a ser a coluna. */}
        <div ref={listasBoxRef} className="w-full lg:w-64 lg:shrink-0 bg-[#161616] border border-[#222] rounded-2xl p-2
                        flex gap-2 overflow-x-auto lg:block lg:space-y-1.5 lg:overflow-x-visible lg:overflow-y-auto">
          {lists.map((list, i) => (
            <div key={list.id}
              ref={el => { rowRefs.current[i] = el; }}
              onClick={() => { if (dragIndex === null) selectList(list); }}
              onPointerDown={e => onPointerDown(e, i, false)}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
              style={dragIndex === i ? { transform: `translateY(${dragDy}px)`, zIndex: 20 } : undefined}
              className={`relative flex items-center gap-2 shrink-0 px-2.5 py-2 lg:p-3 rounded-xl cursor-pointer transition-colors group lg:touch-none ${
                dragIndex === i ? 'opacity-90 shadow-xl shadow-black/40 bg-white/10'
                  : dropIndex === i && dragIndex !== null ? 'ring-1 ring-blue-500/60'
                  : listaAlvo === list.id && itemArrastado && itemArrastado.item.list_id !== list.id
                    ? 'bg-blue-500/15 ring-2 ring-blue-500 border border-transparent'
                  : selectedList?.id === list.id
                    ? 'bg-white/10 border border-white/20'
                    : 'hover:bg-white/5 border border-transparent'
              }`}>
              <span onPointerDown={e => { e.stopPropagation(); onPointerDown(e, i, true); }}
                onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
                title="arrastar para reordenar"
                className="hidden lg:block -ml-1 text-gray-700 hover:text-gray-400 cursor-grab active:cursor-grabbing touch-none">
                <GripVertical size={14} />
              </span>
              <span className="text-xl">{list.icon}</span>
              <div className="flex-1 min-w-0 flex items-baseline gap-1.5 lg:block">
                <p className="text-sm font-medium truncate">{list.name}</p>
                <p className="text-xs text-gray-500 whitespace-nowrap">{list.checked_count}/{list.item_count}</p>
              </div>
              <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: list.color }} />
              <button onClick={e => { e.stopPropagation(); setFormLista({ id: list.id, name: list.name, icon: list.icon, color: list.color }); }}
                title="editar lista"
                className="hidden lg:block opacity-0 group-hover:opacity-100 text-gray-500 hover:text-white transition-all">
                <Pencil size={13} />
              </button>
              <button onClick={e => { e.stopPropagation(); deleteList(list.id); }}
                className="hidden lg:block opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-400 transition-all">
                <Trash2 size={14} />
              </button>
            </div>
          ))}

          {lists.length === 0 && (
            <div className="text-center py-8 text-gray-600 text-sm">
              Cria a tua primeira lista!
            </div>
          )}
        </div>

        {/* Items */}
        <div className="flex-1 min-w-0">
          {selectedList ? (
            <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden h-full flex flex-col">
              <div className="p-4 border-b border-[#222] flex items-center gap-3">
                <span className="text-2xl">{selectedList.icon}</span>
                <div>
                  <h3 className="text-lg font-bold">{selectedList.name}</h3>
                  <p className="text-xs text-gray-500">
                    {selectedList.checked_count} de {selectedList.item_count} concluído{selectedList.item_count !== 1 ? 's' : ''}
                  </p>
                </div>
                {selectedList.item_count > 0 && (
                  <div className="ml-auto flex items-center gap-2">
                    <div className="w-32 h-2 bg-[#222] rounded-full overflow-hidden">
                      <div className="h-full rounded-full transition-all"
                        style={{
                          width: `${(selectedList.checked_count / selectedList.item_count) * 100}%`,
                          backgroundColor: selectedList.color,
                        }} />
                    </div>
                    <span className="text-xs text-gray-500">
                      {Math.round((selectedList.checked_count / selectedList.item_count) * 100)}%
                    </span>
                  </div>
                )}
              </div>

              {/* Add item */}
              <div className="p-4 border-b border-[#222]">
                <form onSubmit={e => { e.preventDefault(); addItem(); }} className="flex gap-2">
                  <input type="text" placeholder="Adicionar item..."
                    value={newItemText} onChange={e => setNewItemText(e.target.value)}
                    className="flex-1 bg-[#222] border border-[#333] rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-blue-500"
                    autoFocus />
                  <button type="submit"
                    className="px-4 py-2.5 bg-blue-600 hover:bg-blue-700 rounded-xl text-sm font-medium">
                    <Plus size={16} />
                  </button>
                </form>
                {newItemText.trim() && (
                  <div className="mt-3 space-y-2.5">
                    {renderCampos(rascunho, (campo, valor) => setRascunho(prev => ({ ...prev, [campo]: valor })))}
                  </div>
                )}
              </div>

              {/* Items list — carregar num item abre a edição dele próprio, em
                  vez de um modal ao lado. */}
              <div className="flex-1 overflow-y-auto">
                {/* Unchecked items */}
                <div className="divide-y divide-[#1a1a1a]">
                  {uncheckedItems.map(item => (
                    <div key={item.id}>
                      <div
                        onClick={() => abreOuFecha(item)}
                        onPointerDown={e => itemPointerDown(e, item)}
                        onPointerMove={itemPointerMove}
                        onPointerUp={itemPointerUp}
                        onPointerCancel={itemPointerUp}
                        className={`flex items-start gap-3 p-4 hover:bg-white/5 group cursor-pointer transition-colors select-none [-webkit-touch-callout:none] ${
                          selectedItem?.id === item.id ? 'bg-white/5' : ''
                        } ${itemArrastado?.item.id === item.id ? 'opacity-40' : ''}`}>
                        <button onClick={e => { e.stopPropagation(); toggleItem(item); }}
                          className="w-5 h-5 mt-0.5 rounded-full border-2 border-gray-600 hover:border-blue-400 shrink-0 transition-colors" />
                        <div className="flex-1 min-w-0">
                          <div className={`flex gap-2 ${selectedItem?.id === item.id ? 'items-start' : 'items-center'}`}>
                            {selectedItem?.id === item.id ? (
                              <textarea
                                value={selectedItem.text}
                                rows={1}
                                ref={el => { if (el) { el.style.height = 'auto'; el.style.height = `${el.scrollHeight}px`; } }}
                                onClick={e => e.stopPropagation()}
                                onChange={e => {
                                  setSelectedItem(prev => prev ? { ...prev, text: e.target.value } : null);
                                  e.currentTarget.style.height = 'auto';
                                  e.currentTarget.style.height = `${e.currentTarget.scrollHeight}px`;
                                }}
                                onBlur={e => updateItemField(item.id, 'text', e.target.value)}
                                className="flex-1 min-w-0 bg-transparent text-sm focus:outline-none border-b border-gray-600 pb-0.5 resize-none overflow-hidden leading-snug"
                              />
                            ) : (
                              <span className="text-sm flex-1">{item.text}</span>
                            )}
                            {/* A data em que foi apontado, na mesma linha do texto
                                e encostada à direita. */}
                            {item.created_at && (
                              <span className="text-xs text-gray-600 shrink-0 tabular-nums"
                                title={format(new Date(item.created_at), "EEEE, d 'de' MMMM 'de' yyyy, HH:mm", { locale: pt })}>
                                {dataCurta(item.created_at)}
                              </span>
                            )}
                            {item.priority > 0 && (
                              <span className={`text-xs font-bold ${getPriorityInfo(item.priority).color}`}>
                                {getPriorityInfo(item.priority).icon}
                              </span>
                            )}
                            {/* Arranca o cronómetro; o reminder fica por fazer até
                                ele o carimbar. */}
                            <span onClick={e => e.stopPropagation()}>
                              <ComecarTarefa nome={item.text} cor={selectedList?.color || '#3B82F6'}
                                icone={selectedList?.icon || '📝'} />
                            </span>
                          </div>
                          <div className="flex items-center gap-3 mt-1">
                            {item.due_date && (
                              <span className={`text-xs flex items-center gap-1 ${
                                isOverdue(item) ? 'text-red-400' : 'text-gray-500'
                              }`}>
                                <Calendar size={10} />
                                {format(new Date(item.due_date), 'd MMM', { locale: pt })}
                                {item.due_time && ` ${item.due_time}`}
                              </span>
                            )}
                            {item.notes && (
                              <span className="text-xs text-gray-500 flex items-center gap-1">
                                <FileText size={10} />
                                Nota
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                      {selectedItem?.id === item.id && renderItemEditor(selectedItem)}
                    </div>
                  ))}
                </div>

                {/* Checked items */}
                {checkedItems.length > 0 && (
                  <>
                    <button
                      onClick={() => setShowCompletedItems(prev => !prev)}
                      className="w-full px-4 py-2 border-t border-[#222] flex items-center gap-2 text-xs text-gray-500 hover:bg-white/5"
                    >
                      <ChevronDown size={12} className={`transition-transform ${showCompletedItems ? '' : '-rotate-90'}`} />
                      {checkedItems.length} concluído{checkedItems.length !== 1 ? 's' : ''}
                    </button>
                    {showCompletedItems && (
                      <div className="divide-y divide-[#1a1a1a]">
                        {checkedItems.map(item => (
                          <div key={item.id}>
                            <div
                              onClick={() => abreOuFecha(item)}
                              onPointerDown={e => itemPointerDown(e, item)}
                              onPointerMove={itemPointerMove}
                              onPointerUp={itemPointerUp}
                              onPointerCancel={itemPointerUp}
                              className={`flex items-start gap-3 p-4 hover:bg-white/5 group opacity-50 cursor-pointer select-none [-webkit-touch-callout:none] ${
                                selectedItem?.id === item.id ? 'bg-white/5 !opacity-70' : ''
                              }`}>
                              <button onClick={e => { e.stopPropagation(); toggleItem(item); }}
                                className="w-5 h-5 mt-0.5 rounded-full border-2 border-green-500 bg-green-500 flex items-center justify-center shrink-0">
                                <Check size={12} className="text-black" />
                              </button>
                              <div className={`flex-1 min-w-0 flex gap-2 ${selectedItem?.id === item.id ? 'items-start' : 'items-center'}`}>
                                {selectedItem?.id === item.id ? (
                                  <textarea
                                    value={selectedItem.text}
                                    rows={1}
                                    ref={el => { if (el) { el.style.height = 'auto'; el.style.height = `${el.scrollHeight}px`; } }}
                                    onClick={e => e.stopPropagation()}
                                    onChange={e => {
                                      setSelectedItem(prev => prev ? { ...prev, text: e.target.value } : null);
                                      e.currentTarget.style.height = 'auto';
                                      e.currentTarget.style.height = `${e.currentTarget.scrollHeight}px`;
                                    }}
                                    onBlur={e => updateItemField(item.id, 'text', e.target.value)}
                                    className="flex-1 min-w-0 bg-transparent text-sm focus:outline-none border-b border-gray-600 pb-0.5 resize-none overflow-hidden leading-snug"
                                  />
                                ) : (
                                  <span className="text-sm line-through flex-1 min-w-0 truncate">{item.text}</span>
                                )}
                                {/* Nos feitos a data é a de quando foi feito, não a
                                    de quando foi apontado. */}
                                {(item.checked_at || item.created_at) && (
                                  <span className="text-xs text-gray-600 shrink-0 tabular-nums"
                                    title={format(new Date((item.checked_at || item.created_at)!), "EEEE, d 'de' MMMM 'de' yyyy, HH:mm", { locale: pt })}>
                                    {dataCurta((item.checked_at || item.created_at)!)}
                                  </span>
                                )}
                              </div>
                            </div>
                            {selectedItem?.id === item.id && renderItemEditor(selectedItem)}
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}

                {items.length === 0 && (
                  <div className="p-8 text-center text-gray-600 text-sm">
                    Lista vazia — adiciona itens acima!
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-full text-gray-600">
              <div className="text-center">
                <p className="text-3xl sm:text-4xl mb-3">📝</p>
                <p className="text-sm">Seleciona ou cria uma lista</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Criar ou editar lista — o mesmo formulário para as duas coisas */}
      {formLista && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-3" onClick={() => setFormLista(null)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 max-w-[90vw] w-[420px] border border-[#333]" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-bold">{formLista.id ? 'Editar lista' : 'Nova Lista'}</h3>
              <button onClick={() => setFormLista(null)} className="text-gray-500 hover:text-white"><X size={20} /></button>
            </div>

            <div className="space-y-4">
              <input type="text" placeholder="Nome da lista..."
                value={formLista.name} onChange={e => setFormLista(f => f && ({ ...f, name: e.target.value }))}
                onKeyDown={e => { if (e.key === 'Enter') saveList(); }}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-500"
                autoFocus />

              <div>
                <label className="text-xs text-gray-500 block mb-2">Ícone</label>
                <div className="flex flex-wrap gap-2">
                  {/* O ícone que a lista já tem pode não estar na lista fixa — junta-se
                      à frente para não desaparecer ao editar. */}
                  {[...new Set([...(LIST_ICONS.includes(formLista.icon) ? [] : [formLista.icon]), ...LIST_ICONS])].map(icon => (
                    <button key={icon} onClick={() => setFormLista(f => f && ({ ...f, icon }))}
                      className={`w-10 h-10 rounded-xl flex items-center justify-center text-lg transition-all ${
                        formLista.icon === icon ? 'bg-blue-600 ring-2 ring-blue-400' : 'bg-[#222] hover:bg-[#2a2a2a]'
                      }`}>
                      {icon}
                    </button>
                  ))}
                </div>
                <input type="text" value={formLista.icon} maxLength={4}
                  onChange={e => setFormLista(f => f && ({ ...f, icon: e.target.value }))}
                  placeholder="ou escreve outro emoji"
                  className="mt-2 w-full bg-[#222] border border-[#333] rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-blue-500" />
              </div>

              <div>
                <label className="text-xs text-gray-500 block mb-2">Cor</label>
                <div className="flex gap-2">
                  {LIST_COLORS.map(color => (
                    <button key={color} onClick={() => setFormLista(f => f && ({ ...f, color }))}
                      className={`w-8 h-8 rounded-full transition-all ${
                        formLista.color === color ? 'ring-2 ring-offset-2 ring-offset-[#1a1a1a]' : ''
                      }`}
                      style={{ backgroundColor: color }} />
                  ))}
                </div>
              </div>
            </div>

            <div className="flex gap-3 mt-6 justify-end">
              <button onClick={() => setFormLista(null)}
                className="px-4 py-2.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm">Cancelar</button>
              <button onClick={saveList}
                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 rounded-xl text-sm font-medium">
                {formLista.id ? 'Guardar' : 'Criar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
