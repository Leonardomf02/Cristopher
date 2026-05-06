import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Lightbulb, Mic, MicOff, Sparkles, Trash2, Plus, Check, X, AlertCircle, ArrowLeft } from 'lucide-react';
import { ideasApi, listsApi, ExtractedTodo } from '../api';
import { UserList } from '../types';

interface DraftTodo extends ExtractedTodo {
  selected: boolean;
}

const PRIORITY_LABELS: Record<number, { label: string; color: string }> = {
  0: { label: 'Normal', color: 'text-gray-400' },
  1: { label: 'Baixa', color: 'text-blue-400' },
  2: { label: 'Média', color: 'text-yellow-400' },
  3: { label: 'Alta', color: 'text-red-400' },
};

export default function IdeasPage() {
  const navigate = useNavigate();
  const [text, setText] = useState('');
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<DraftTodo[]>([]);
  const [lists, setLists] = useState<UserList[]>([]);
  const [targetListId, setTargetListId] = useState<number | 'new' | null>(null);
  const [newListName, setNewListName] = useState('Ideias');
  const [saving, setSaving] = useState(false);
  const [savedCount, setSavedCount] = useState<number | null>(null);

  const [recording, setRecording] = useState(false);
  const [speechSupported, setSpeechSupported] = useState(true);
  const recognitionRef = useRef<any>(null);
  const transcriptStartRef = useRef('');

  useEffect(() => { loadLists(); }, []);

  useEffect(() => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) {
      setSpeechSupported(false);
      return;
    }
    const r = new SR();
    r.lang = 'pt-PT';
    r.continuous = true;
    r.interimResults = true;
    r.onresult = (e: any) => {
      let finalText = '';
      let interimText = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += t;
        else interimText += t;
      }
      const base = transcriptStartRef.current;
      const combined = (base + (base && (finalText || interimText) ? ' ' : '') + finalText + interimText).trimStart();
      setText(combined);
      if (finalText) transcriptStartRef.current = (base + (base ? ' ' : '') + finalText).trim();
    };
    r.onend = () => setRecording(false);
    r.onerror = () => setRecording(false);
    recognitionRef.current = r;
    return () => { try { r.stop(); } catch { /* ignore */ } };
  }, []);

  async function loadLists() {
    const data = await listsApi.list();
    setLists(data);
    if (data.length > 0) setTargetListId(data[0].id);
    else setTargetListId('new');
  }

  function toggleRecording() {
    const r = recognitionRef.current;
    if (!r) return;
    if (recording) {
      r.stop();
      setRecording(false);
    } else {
      transcriptStartRef.current = text.trim();
      try {
        r.start();
        setRecording(true);
      } catch {
        // already started — ignore
      }
    }
  }

  async function processText() {
    const trimmed = text.trim();
    if (!trimmed) return;
    setError(null);
    setSavedCount(null);
    setProcessing(true);
    try {
      const { todos } = await ideasApi.process(trimmed);
      if (todos.length === 0) {
        setError('A IA não encontrou nada accionável no texto.');
        setDrafts([]);
      } else {
        setDrafts(todos.map(t => ({ ...t, selected: true })));
      }
    } catch (e: any) {
      setError(e?.message || 'Erro a processar');
    } finally {
      setProcessing(false);
    }
  }

  function updateDraft(idx: number, patch: Partial<DraftTodo>) {
    setDrafts(d => d.map((t, i) => i === idx ? { ...t, ...patch } : t));
  }

  function removeDraft(idx: number) {
    setDrafts(d => d.filter((_, i) => i !== idx));
  }

  function addEmptyDraft() {
    setDrafts(d => [...d, { text: '', priority: 0, due_date: null, notes: '', selected: true }]);
  }

  async function saveAll() {
    const selected = drafts.filter(d => d.selected && d.text.trim());
    if (selected.length === 0) return;
    setSaving(true);
    setError(null);
    try {
      let listId: number;
      if (targetListId === 'new' || targetListId === null) {
        const created = await listsApi.create({
          name: newListName.trim() || 'Ideias',
          icon: '💡',
          color: '#F59E0B',
        });
        listId = created.id;
      } else {
        listId = targetListId;
      }
      for (const t of selected) {
        await listsApi.addItem(listId, {
          text: t.text.trim(),
          notes: t.notes,
          due_date: t.due_date,
          priority: t.priority,
        });
      }
      setSavedCount(selected.length);
      setDrafts([]);
      setText('');
      transcriptStartRef.current = '';
      await loadLists();
      setTargetListId(listId);
    } catch (e: any) {
      setError(e?.message || 'Erro a guardar');
    } finally {
      setSaving(false);
    }
  }

  const selectedCount = drafts.filter(d => d.selected && d.text.trim()).length;

  return (
    <div className="max-w-4xl mx-auto">
      <button onClick={() => navigate('/lists')}
        className="flex items-center gap-2 text-gray-400 hover:text-white mb-4 text-sm">
        <ArrowLeft size={16} /> Voltar a Reminders
      </button>
      <div className="flex items-center gap-3 mb-2">
        <Lightbulb size={28} className="text-yellow-400" />
        <h2 className="text-2xl sm:text-3xl font-bold">Ideias → To-dos</h2>
      </div>
      <p className="text-sm text-gray-500 mb-8">
        Despeja tudo o que tens na cabeça (texto ou áudio). A IA transforma em tarefas accionáveis.
      </p>

      <div className="bg-[#161616] rounded-2xl border border-[#222] p-5 mb-6">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-gray-400">O que tens na cabeça</span>
          <div className="flex items-center gap-2">
            {speechSupported ? (
              <button
                onClick={toggleRecording}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium transition-colors ${
                  recording
                    ? 'bg-red-600/20 text-red-400 hover:bg-red-600/30'
                    : 'bg-[#222] text-gray-300 hover:bg-[#2a2a2a]'
                }`}
              >
                {recording ? <MicOff size={14} /> : <Mic size={14} />}
                {recording ? 'A gravar...' : 'Falar'}
              </button>
            ) : (
              <span className="text-[10px] text-gray-600">áudio só em Chrome</span>
            )}
          </div>
        </div>
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          placeholder="Ex: tenho de ligar ao banco para tratar do cartão, comprar um carregador novo, marcar dentista para a próxima semana..."
          rows={8}
          className="w-full bg-[#0f0f0f] border border-[#222] rounded-xl px-4 py-3 text-sm resize-none focus:outline-none focus:border-yellow-500/50"
        />
        <div className="flex items-center justify-between mt-3">
          <span className="text-[11px] text-gray-600">{text.length} caracteres</span>
          <button
            onClick={processText}
            disabled={!text.trim() || processing}
            className="flex items-center gap-2 px-4 py-2 bg-yellow-500 hover:bg-yellow-600 disabled:bg-[#222] disabled:text-gray-600 text-black disabled:cursor-not-allowed rounded-xl text-sm font-semibold transition-colors"
          >
            <Sparkles size={14} />
            {processing ? 'A processar...' : 'Processar com IA'}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3 mb-6 flex items-start gap-2">
          <AlertCircle size={16} className="text-red-400 mt-0.5 shrink-0" />
          <span className="text-sm text-red-400">{error}</span>
        </div>
      )}

      {savedCount !== null && (
        <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-3 mb-6 flex items-center gap-2">
          <Check size={16} className="text-green-400" />
          <span className="text-sm text-green-400">{savedCount} {savedCount === 1 ? 'tarefa guardada' : 'tarefas guardadas'}.</span>
        </div>
      )}

      {drafts.length > 0 && (
        <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden mb-6">
          <div className="flex items-center justify-between p-4 border-b border-[#222]">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-medium text-gray-300">Tarefas extraídas</h3>
              <span className="text-xs text-gray-600">({selectedCount} de {drafts.length} selecionadas)</span>
            </div>
            <button onClick={addEmptyDraft} className="flex items-center gap-1 text-xs text-yellow-400 hover:text-yellow-300">
              <Plus size={12} /> Adicionar manual
            </button>
          </div>
          <div className="divide-y divide-[#1a1a1a]">
            {drafts.map((d, idx) => (
              <div key={idx} className="p-3 flex items-start gap-3 group">
                <input
                  type="checkbox"
                  checked={d.selected}
                  onChange={e => updateDraft(idx, { selected: e.target.checked })}
                  className="mt-1.5 accent-yellow-500 w-4 h-4 cursor-pointer"
                />
                <div className="flex-1 min-w-0 space-y-1.5">
                  <input
                    type="text"
                    value={d.text}
                    onChange={e => updateDraft(idx, { text: e.target.value })}
                    placeholder="Tarefa..."
                    className="w-full bg-transparent text-sm focus:outline-none focus:bg-white/5 rounded px-1 -mx-1"
                  />
                  <div className="flex items-center gap-2 flex-wrap">
                    <select
                      value={d.priority}
                      onChange={e => updateDraft(idx, { priority: Number(e.target.value) })}
                      className={`bg-[#222] border border-[#333] rounded-lg px-2 py-1 text-[11px] ${PRIORITY_LABELS[d.priority]?.color}`}
                    >
                      {[0, 1, 2, 3].map(p => (
                        <option key={p} value={p}>Prioridade: {PRIORITY_LABELS[p].label}</option>
                      ))}
                    </select>
                    <input
                      type="date"
                      value={d.due_date || ''}
                      onChange={e => updateDraft(idx, { due_date: e.target.value || null })}
                      className="bg-[#222] border border-[#333] rounded-lg px-2 py-1 text-[11px] text-gray-300"
                    />
                    {d.notes && (
                      <span className="text-[10px] text-gray-600 truncate max-w-xs">{d.notes}</span>
                    )}
                  </div>
                </div>
                <button
                  onClick={() => removeDraft(idx)}
                  className="p-1 text-gray-700 hover:text-red-400 opacity-0 group-hover:opacity-100"
                >
                  <X size={14} />
                </button>
              </div>
            ))}
          </div>

          <div className="p-4 border-t border-[#222] bg-black/20">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-gray-400">Guardar em:</span>
                <select
                  value={targetListId === null ? '' : String(targetListId)}
                  onChange={e => {
                    const v = e.target.value;
                    setTargetListId(v === 'new' ? 'new' : Number(v));
                  }}
                  className="bg-[#222] border border-[#333] rounded-lg px-3 py-1.5 text-xs"
                >
                  {lists.map(l => (
                    <option key={l.id} value={l.id}>{l.icon} {l.name}</option>
                  ))}
                  <option value="new">➕ Nova lista...</option>
                </select>
                {targetListId === 'new' && (
                  <input
                    type="text"
                    value={newListName}
                    onChange={e => setNewListName(e.target.value)}
                    placeholder="Nome"
                    className="bg-[#222] border border-[#333] rounded-lg px-3 py-1.5 text-xs"
                  />
                )}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => { setDrafts([]); setError(null); }}
                  className="flex items-center gap-1 px-3 py-1.5 bg-[#222] hover:bg-[#2a2a2a] rounded-lg text-xs text-gray-300"
                >
                  <Trash2 size={12} /> Descartar
                </button>
                <button
                  onClick={saveAll}
                  disabled={selectedCount === 0 || saving}
                  className="flex items-center gap-1.5 px-4 py-1.5 bg-yellow-500 hover:bg-yellow-600 disabled:bg-[#222] disabled:text-gray-600 text-black disabled:cursor-not-allowed rounded-lg text-xs font-semibold"
                >
                  <Check size={12} />
                  {saving ? 'A guardar...' : `Guardar ${selectedCount}`}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
