import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { format } from 'date-fns';
import { pt } from 'date-fns/locale';
import {
  Plus, X, Trash2, Check, Flag, Calendar,
  FileText, ChevronDown, Sparkles,
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

export default function ListsPage() {
  const navigate = useNavigate();
  const [lists, setLists] = useState<UserList[]>([]);
  const [selectedList, setSelectedList] = useState<UserList | null>(null);
  const [items, setItems] = useState<ListItem[]>([]);
  const [showNewList, setShowNewList] = useState(false);
  const [newListForm, setNewListForm] = useState({ name: '', icon: '📝', color: '#3B82F6' });
  const [newItemText, setNewItemText] = useState('');
  const [editingList, setEditingList] = useState<UserList | null>(null);
  const [selectedItem, setSelectedItem] = useState<ListItem | null>(null);
  const [showCompletedItems, setShowCompletedItems] = useState(true);

  useEffect(() => { initialLoad(); }, []);

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

  async function createList() {
    if (!newListForm.name.trim()) return;
    const created = await listsApi.create(newListForm);
    setShowNewList(false);
    setNewListForm({ name: '', icon: '📝', color: '#3B82F6' });
    await loadLists();
    selectList(created);
  }

  async function deleteList(id: number) {
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
    await listsApi.addItem(selectedList.id, { text: newItemText.trim() });
    setNewItemText('');
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

  const uncheckedItems = items.filter(i => !i.checked).sort((a, b) => {
    // Sort by priority desc, then position
    if (b.priority !== a.priority) return b.priority - a.priority;
    return a.position - b.position;
  });
  const checkedItems = items.filter(i => i.checked);

  return (
    <div>
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6 lg:mb-8">
        <div>
          <h2 className="text-2xl font-bold">Reminders</h2>
          <p className="text-gray-500 text-sm mt-1">{lists.length} lista{lists.length !== 1 ? 's' : ''}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button onClick={() => navigate('/ideas')}
            className="flex items-center gap-2 px-3 sm:px-4 py-2 bg-yellow-500 hover:bg-yellow-600 text-black rounded-xl text-sm font-semibold">
            <Sparkles size={16} /> <span className="hidden sm:inline">Despejar ideias (IA)</span><span className="sm:hidden">IA</span>
          </button>
          <button onClick={() => setShowNewList(true)}
            className="flex items-center gap-2 px-3 sm:px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-xl text-sm font-medium">
            <Plus size={16} /> <span className="hidden sm:inline">Nova Lista</span><span className="sm:hidden">Lista</span>
          </button>
        </div>
      </div>

      <div className="flex flex-col lg:flex-row gap-3 lg:gap-6 lg:h-[calc(100vh-200px)]">
        {/* Lists sidebar */}
        <div className="w-full lg:w-64 lg:shrink-0 space-y-2 lg:overflow-y-auto max-h-48 lg:max-h-none overflow-y-auto">
          {lists.map(list => (
            <div key={list.id}
              onClick={() => selectList(list)}
              className={`flex items-center gap-3 p-3 rounded-xl cursor-pointer transition-all group ${
                selectedList?.id === list.id
                  ? 'bg-white/10 border border-white/20'
                  : 'hover:bg-white/5 border border-transparent'
              }`}>
              <span className="text-xl">{list.icon}</span>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{list.name}</p>
                <p className="text-xs text-gray-500">{list.checked_count}/{list.item_count}</p>
              </div>
              <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: list.color }} />
              <button onClick={e => { e.stopPropagation(); deleteList(list.id); }}
                className="opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-400 transition-all">
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
              </div>

              {/* Items list */}
              <div className="flex-1 overflow-y-auto">
                {/* Unchecked items */}
                <div className="divide-y divide-[#1a1a1a]">
                  {uncheckedItems.map(item => (
                    <div key={item.id}
                      onClick={() => setSelectedItem(item)}
                      className={`flex items-start gap-3 p-4 hover:bg-white/5 group cursor-pointer transition-colors ${
                        selectedItem?.id === item.id ? 'bg-white/5' : ''
                      }`}>
                      <button onClick={e => { e.stopPropagation(); toggleItem(item); }}
                        className="w-5 h-5 mt-0.5 rounded-full border-2 border-gray-600 hover:border-blue-400 shrink-0 transition-colors" />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm flex-1">{item.text}</span>
                          {item.priority > 0 && (
                            <span className={`text-xs font-bold ${getPriorityInfo(item.priority).color}`}>
                              {getPriorityInfo(item.priority).icon}
                            </span>
                          )}
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
                      <button onClick={e => { e.stopPropagation(); deleteItem(item.id); }}
                        className="opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-400 transition-all mt-0.5">
                        <Trash2 size={14} />
                      </button>
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
                          <div key={item.id}
                            onClick={() => setSelectedItem(item)}
                            className={`flex items-start gap-3 p-4 hover:bg-white/5 group opacity-50 cursor-pointer ${
                              selectedItem?.id === item.id ? 'bg-white/5 !opacity-70' : ''
                            }`}>
                            <button onClick={e => { e.stopPropagation(); toggleItem(item); }}
                              className="w-5 h-5 mt-0.5 rounded-full border-2 border-green-500 bg-green-500 flex items-center justify-center shrink-0">
                              <Check size={12} className="text-black" />
                            </button>
                            <div className="flex-1 min-w-0">
                              <span className="text-sm line-through">{item.text}</span>
                            </div>
                            <button onClick={e => { e.stopPropagation(); deleteItem(item.id); }}
                              className="opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-400 transition-all mt-0.5">
                              <Trash2 size={14} />
                            </button>
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

        {/* Detail Panel — Apple Reminders style. Em mobile aparece como overlay fixo. */}
        {selectedItem && selectedList && (
          <>
            <div onClick={() => setSelectedItem(null)} className="lg:hidden fixed inset-0 bg-black/60 z-30" />
            <div className="lg:w-80 lg:shrink-0 lg:static lg:rounded-2xl bg-[#161616] border border-[#222] p-5 overflow-y-auto fixed inset-x-3 bottom-3 top-20 rounded-2xl z-40 lg:inset-auto lg:top-auto lg:bottom-auto">
            <div className="flex items-center justify-between mb-5">
              <h4 className="text-sm font-bold text-gray-400">Detalhes</h4>
              <button onClick={() => setSelectedItem(null)}
                className="text-gray-500 hover:text-white">
                <X size={16} />
              </button>
            </div>

            {/* Title */}
            <input
              type="text"
              value={selectedItem.text}
              onChange={e => {
                setSelectedItem(prev => prev ? { ...prev, text: e.target.value } : null);
              }}
              onBlur={e => updateItemField(selectedItem.id, 'text', e.target.value)}
              className="w-full bg-transparent text-lg font-medium mb-4 focus:outline-none border-b border-transparent focus:border-gray-600 pb-1"
            />

            {/* Notes */}
            <div className="mb-4">
              <label className="text-xs text-gray-500 mb-1 block flex items-center gap-1">
                <FileText size={12} /> Notas
              </label>
              <textarea
                value={selectedItem.notes || ''}
                onChange={e => setSelectedItem(prev => prev ? { ...prev, notes: e.target.value } : null)}
                onBlur={e => updateItemField(selectedItem.id, 'notes', e.target.value)}
                placeholder="Adicionar nota..."
                className="w-full bg-[#222] border border-[#333] rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-blue-500 resize-none min-h-[100px]"
              />
            </div>

            {/* Due Date & Time */}
            <div className="mb-4">
              <label className="text-xs text-gray-500 mb-1 block flex items-center gap-1">
                <Calendar size={12} /> Data limite
              </label>
              <div className="flex gap-2">
                <input
                  type="date"
                  value={selectedItem.due_date || ''}
                  onChange={e => {
                    const val = e.target.value || null;
                    setSelectedItem(prev => prev ? { ...prev, due_date: val } : null);
                    updateItemField(selectedItem.id, 'due_date', val);
                  }}
                  className="flex-1 bg-[#222] border border-[#333] rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
                />
                {selectedItem.due_date && (
                  <input
                    type="time"
                    value={selectedItem.due_time || ''}
                    onChange={e => {
                      const val = e.target.value || null;
                      setSelectedItem(prev => prev ? { ...prev, due_time: val } : null);
                      updateItemField(selectedItem.id, 'due_time', val);
                    }}
                    className="w-28 bg-[#222] border border-[#333] rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
                  />
                )}
              </div>
              {selectedItem.due_date && (
                <div className="flex gap-2 mt-1">
                  <button
                    onClick={() => {
                      setSelectedItem(prev => prev ? { ...prev, due_date: null, due_time: null } : null);
                      updateItemField(selectedItem.id, 'due_date', null);
                      updateItemField(selectedItem.id, 'due_time', null);
                    }}
                    className="text-xs text-red-400 hover:underline"
                  >
                    Remover data
                  </button>
                  {selectedItem.due_time && (
                    <button
                      onClick={() => {
                        setSelectedItem(prev => prev ? { ...prev, due_time: null } : null);
                        updateItemField(selectedItem.id, 'due_time', null);
                      }}
                      className="text-xs text-gray-500 hover:underline"
                    >
                      Remover hora
                    </button>
                  )}
                </div>
              )}
            </div>

            {/* Priority */}
            <div className="mb-4">
              <label className="text-xs text-gray-500 mb-2 block flex items-center gap-1">
                <Flag size={12} /> Prioridade
              </label>
              <div className="flex gap-2">
                {PRIORITY_LABELS.map(p => (
                  <button
                    key={p.value}
                    onClick={() => {
                      setSelectedItem(prev => prev ? { ...prev, priority: p.value } : null);
                      updateItemField(selectedItem.id, 'priority', p.value);
                    }}
                    className={`flex-1 py-2 rounded-xl text-xs font-medium transition-all ${
                      selectedItem.priority === p.value
                        ? 'bg-white/10 ring-1 ring-white/20'
                        : 'bg-[#222] hover:bg-[#2a2a2a]'
                    } ${p.color}`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Status */}
            <div className="pt-4 border-t border-[#222]">
              <button
                onClick={() => toggleItem(selectedItem)}
                className={`w-full py-2.5 rounded-xl text-sm font-medium transition-all ${
                  selectedItem.checked
                    ? 'bg-yellow-600/20 text-yellow-400 hover:bg-yellow-600/30'
                    : 'bg-green-600/20 text-green-400 hover:bg-green-600/30'
                }`}
              >
                {selectedItem.checked ? 'Marcar como pendente' : 'Marcar como concluído'}
              </button>
              <button
                onClick={() => deleteItem(selectedItem.id)}
                className="w-full mt-2 py-2.5 rounded-xl text-sm font-medium bg-red-600/10 text-red-400 hover:bg-red-600/20 transition-all"
              >
                Apagar item
              </button>
            </div>
            </div>
          </>
        )}
      </div>

      {/* New List Modal */}
      {showNewList && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowNewList(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 max-w-[90vw] w-[420px] border border-[#333]" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-bold">Nova Lista</h3>
              <button onClick={() => setShowNewList(false)} className="text-gray-500 hover:text-white"><X size={20} /></button>
            </div>

            <div className="space-y-4">
              <input type="text" placeholder="Nome da lista..."
                value={newListForm.name} onChange={e => setNewListForm(f => ({ ...f, name: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-500"
                autoFocus />

              <div>
                <label className="text-xs text-gray-500 block mb-2">Ícone</label>
                <div className="flex flex-wrap gap-2">
                  {LIST_ICONS.map(icon => (
                    <button key={icon} onClick={() => setNewListForm(f => ({ ...f, icon }))}
                      className={`w-10 h-10 rounded-xl flex items-center justify-center text-lg transition-all ${
                        newListForm.icon === icon ? 'bg-blue-600 ring-2 ring-blue-400' : 'bg-[#222] hover:bg-[#2a2a2a]'
                      }`}>
                      {icon}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-xs text-gray-500 block mb-2">Cor</label>
                <div className="flex gap-2">
                  {LIST_COLORS.map(color => (
                    <button key={color} onClick={() => setNewListForm(f => ({ ...f, color }))}
                      className={`w-8 h-8 rounded-full transition-all ${
                        newListForm.color === color ? 'ring-2 ring-offset-2 ring-offset-[#1a1a1a]' : ''
                      }`}
                      style={{ backgroundColor: color }} />
                  ))}
                </div>
              </div>
            </div>

            <div className="flex gap-3 mt-6 justify-end">
              <button onClick={() => setShowNewList(false)}
                className="px-4 py-2.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm">Cancelar</button>
              <button onClick={createList}
                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 rounded-xl text-sm font-medium">Criar</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
