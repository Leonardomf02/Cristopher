import { useState, useEffect, useRef } from 'react';
import { format } from 'date-fns';
import { pt } from 'date-fns/locale';
import {
  Plus, X, Trash2, Search, FolderPlus, Pin, PinOff, ChevronLeft,
  Folder, FileText, MoreHorizontal, Edit3,
} from 'lucide-react';
import { notesApi } from '../api';
import { NoteFolder, Note } from '../types';

const FOLDER_COLORS = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#06B6D4', '#F97316'];
const NOTE_COLORS = ['', '#1e3a5f', '#1a3d2e', '#3d3520', '#3d1f1f', '#2d1f3d', '#3d1f35'];

export default function NotesPage() {
  const [folders, setFolders] = useState<NoteFolder[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [selectedFolder, setSelectedFolder] = useState<number | null>(null); // null = all notes
  const [selectedNote, setSelectedNote] = useState<Note | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderForm, setNewFolderForm] = useState({ name: '', color: '#3B82F6' });
  const [editingTitle, setEditingTitle] = useState(false);
  const contentRef = useRef<HTMLTextAreaElement>(null);
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => { loadFolders(); loadNotes(); }, []);
  useEffect(() => { loadNotes(); }, [selectedFolder, searchQuery]);

  async function loadFolders() {
    const data = await notesApi.listFolders();
    setFolders(data);
  }

  async function loadNotes() {
    const data = await notesApi.list({
      folder_id: selectedFolder ?? undefined,
      search: searchQuery || undefined,
    });
    setNotes(data);
  }

  async function createFolder() {
    if (!newFolderForm.name.trim()) return;
    await notesApi.createFolder(newFolderForm);
    setShowNewFolder(false);
    setNewFolderForm({ name: '', color: '#3B82F6' });
    loadFolders();
  }

  async function deleteFolder(id: number) {
    await notesApi.deleteFolder(id);
    if (selectedFolder === id) setSelectedFolder(null);
    loadFolders();
    loadNotes();
  }

  async function createNote() {
    const note = await notesApi.create({
      title: 'Nova nota',
      content: '',
      folder_id: selectedFolder,
    });
    await loadNotes();
    setSelectedNote(note);
    setEditingTitle(true);
  }

  async function deleteNote(id: number) {
    await notesApi.delete(id);
    if (selectedNote?.id === id) setSelectedNote(null);
    loadNotes();
    loadFolders();
  }

  async function togglePin(note: Note) {
    const updated = await notesApi.update(note.id, { pinned: !note.pinned });
    setNotes(prev => prev.map(n => n.id === note.id ? updated : n));
    if (selectedNote?.id === note.id) setSelectedNote(updated);
    loadNotes();
  }

  function handleNoteFieldChange(field: 'title' | 'content' | 'color', value: string) {
    if (!selectedNote) return;
    setSelectedNote(prev => prev ? { ...prev, [field]: value } : null);
    setNotes(prev => prev.map(n => n.id === selectedNote.id ? { ...n, [field]: value } : n));

    // Auto-save with debounce
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    saveTimeoutRef.current = setTimeout(async () => {
      await notesApi.update(selectedNote.id, { [field]: value });
      if (field === 'title') loadNotes();
    }, 500);
  }

  function selectNote(note: Note) {
    setSelectedNote(note);
    setEditingTitle(false);
  }

  const pinnedNotes = notes.filter(n => n.pinned);
  const unpinnedNotes = notes.filter(n => !n.pinned);

  const allNotesCount = folders.reduce((sum, f) => sum + f.note_count, 0);

  return (
    <div className="flex gap-0 h-[calc(100vh-100px)]">
      {/* Folders sidebar */}
      <div className="w-56 shrink-0 border-r border-[#222] pr-4 flex flex-col">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold">Notas</h2>
          <button onClick={() => setShowNewFolder(true)}
            className="text-gray-400 hover:text-white p-1">
            <FolderPlus size={18} />
          </button>
        </div>

        {/* Search */}
        <div className="relative mb-4">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            placeholder="Pesquisar notas..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="w-full bg-[#222] border border-[#333] rounded-xl pl-9 pr-3 py-2 text-xs focus:outline-none focus:border-blue-500"
          />
        </div>

        {/* All notes */}
        <button
          onClick={() => setSelectedFolder(null)}
          className={`flex items-center gap-2 px-3 py-2 rounded-xl mb-1 text-sm transition-all ${
            selectedFolder === null ? 'bg-white/10 text-white' : 'text-gray-400 hover:bg-white/5'
          }`}
        >
          <FileText size={16} />
          <span className="flex-1 text-left">Todas as notas</span>
          <span className="text-xs text-gray-500">{allNotesCount}</span>
        </button>

        {/* Folder list */}
        <div className="flex-1 overflow-y-auto space-y-1">
          {folders.map(folder => (
            <div key={folder.id}
              onClick={() => setSelectedFolder(folder.id)}
              className={`flex items-center gap-2 px-3 py-2 rounded-xl cursor-pointer group transition-all ${
                selectedFolder === folder.id ? 'bg-white/10 text-white' : 'text-gray-400 hover:bg-white/5'
              }`}
            >
              <Folder size={16} style={{ color: folder.color }} />
              <span className="flex-1 text-sm truncate">{folder.name}</span>
              <span className="text-xs text-gray-500">{folder.note_count}</span>
              <button onClick={e => { e.stopPropagation(); deleteFolder(folder.id); }}
                className="opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-400">
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Notes list */}
      <div className="w-72 shrink-0 border-r border-[#222] flex flex-col">
        <div className="px-4 py-3 border-b border-[#222] flex items-center justify-between">
          <h3 className="text-sm font-bold text-gray-400">
            {selectedFolder === null
              ? 'Todas as notas'
              : folders.find(f => f.id === selectedFolder)?.name || 'Notas'}
          </h3>
          <button onClick={createNote}
            className="text-blue-400 hover:text-blue-300 p-1">
            <Plus size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {/* Pinned */}
          {pinnedNotes.length > 0 && (
            <>
              <div className="px-4 py-2 text-[10px] font-bold text-gray-600 uppercase tracking-wider">
                Fixadas
              </div>
              {pinnedNotes.map(note => (
                <NoteListItem key={note.id} note={note} isSelected={selectedNote?.id === note.id}
                  onSelect={() => selectNote(note)} onDelete={() => deleteNote(note.id)}
                  onTogglePin={() => togglePin(note)} />
              ))}
            </>
          )}

          {/* Regular */}
          {unpinnedNotes.length > 0 && pinnedNotes.length > 0 && (
            <div className="px-4 py-2 text-[10px] font-bold text-gray-600 uppercase tracking-wider">
              Notas
            </div>
          )}
          {unpinnedNotes.map(note => (
            <NoteListItem key={note.id} note={note} isSelected={selectedNote?.id === note.id}
              onSelect={() => selectNote(note)} onDelete={() => deleteNote(note.id)}
              onTogglePin={() => togglePin(note)} />
          ))}

          {notes.length === 0 && (
            <div className="p-8 text-center text-gray-600 text-sm">
              {searchQuery ? 'Nenhuma nota encontrada' : 'Sem notas — cria uma!'}
            </div>
          )}
        </div>
      </div>

      {/* Note editor */}
      <div className="flex-1 flex flex-col min-w-0">
        {selectedNote ? (
          <>
            {/* Editor toolbar */}
            <div className="px-6 py-3 border-b border-[#222] flex items-center gap-3">
              <button onClick={() => togglePin(selectedNote)}
                className={`p-1.5 rounded-lg transition-colors ${
                  selectedNote.pinned ? 'text-yellow-400 bg-yellow-400/10' : 'text-gray-500 hover:text-gray-300'
                }`}
              >
                {selectedNote.pinned ? <Pin size={16} /> : <PinOff size={16} />}
              </button>

              {/* Note color */}
              <div className="flex gap-1.5 ml-2">
                {NOTE_COLORS.map((color, i) => (
                  <button key={i}
                    onClick={() => handleNoteFieldChange('color', color)}
                    className={`w-5 h-5 rounded-full border transition-all ${
                      (selectedNote.color || '') === color
                        ? 'ring-2 ring-blue-400 ring-offset-1 ring-offset-[#0f0f0f]'
                        : 'border-[#444]'
                    }`}
                    style={{ backgroundColor: color || '#222' }}
                  />
                ))}
              </div>

              {/* Folder selector */}
              <select
                value={selectedNote.folder_id || ''}
                onChange={async e => {
                  const folderId = e.target.value ? Number(e.target.value) : null;
                  const updated = await notesApi.update(selectedNote.id, { folder_id: folderId });
                  setSelectedNote(updated);
                  loadNotes();
                  loadFolders();
                }}
                className="ml-auto bg-[#222] border border-[#333] rounded-lg px-2 py-1 text-xs text-gray-400 focus:outline-none"
              >
                <option value="">Sem pasta</option>
                {folders.map(f => (
                  <option key={f.id} value={f.id}>{f.name}</option>
                ))}
              </select>

              <span className="text-xs text-gray-600">
                {format(new Date(selectedNote.updated_at), "d MMM yyyy 'às' HH:mm", { locale: pt })}
              </span>

              <button onClick={() => deleteNote(selectedNote.id)}
                className="text-gray-500 hover:text-red-400 p-1">
                <Trash2 size={16} />
              </button>
            </div>

            {/* Title + Content */}
            <div className="flex-1 overflow-y-auto px-6 py-4"
              style={{ backgroundColor: selectedNote.color || 'transparent' }}
            >
              <input
                type="text"
                value={selectedNote.title}
                onChange={e => handleNoteFieldChange('title', e.target.value)}
                onFocus={() => setEditingTitle(true)}
                onBlur={() => setEditingTitle(false)}
                placeholder="Título da nota..."
                className="w-full bg-transparent text-2xl font-bold mb-4 focus:outline-none placeholder-gray-600"
                autoFocus={editingTitle}
              />
              <textarea
                ref={contentRef}
                value={selectedNote.content}
                onChange={e => handleNoteFieldChange('content', e.target.value)}
                placeholder="Começa a escrever..."
                className="w-full bg-transparent text-sm leading-relaxed focus:outline-none resize-none min-h-[400px] placeholder-gray-600"
              />
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-600">
            <div className="text-center">
              <p className="text-5xl mb-3">📝</p>
              <p className="text-sm">Seleciona ou cria uma nota</p>
            </div>
          </div>
        )}
      </div>

      {/* New Folder Modal */}
      {showNewFolder && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
          onClick={() => setShowNewFolder(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 w-[360px] border border-[#333]"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold">Nova Pasta</h3>
              <button onClick={() => setShowNewFolder(false)} className="text-gray-500 hover:text-white">
                <X size={20} />
              </button>
            </div>

            <input type="text" placeholder="Nome da pasta..."
              value={newFolderForm.name}
              onChange={e => setNewFolderForm(f => ({ ...f, name: e.target.value }))}
              className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-500 mb-4"
              autoFocus
              onKeyDown={e => { if (e.key === 'Enter') createFolder(); }}
            />

            <div className="mb-4">
              <label className="text-xs text-gray-500 block mb-2">Cor</label>
              <div className="flex gap-2">
                {FOLDER_COLORS.map(color => (
                  <button key={color}
                    onClick={() => setNewFolderForm(f => ({ ...f, color }))}
                    className={`w-8 h-8 rounded-full transition-all ${
                      newFolderForm.color === color ? 'ring-2 ring-offset-2 ring-offset-[#1a1a1a]' : ''
                    }`}
                    style={{ backgroundColor: color }}
                  />
                ))}
              </div>
            </div>

            <div className="flex gap-3 justify-end">
              <button onClick={() => setShowNewFolder(false)}
                className="px-4 py-2.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm">
                Cancelar
              </button>
              <button onClick={createFolder}
                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 rounded-xl text-sm font-medium">
                Criar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function NoteListItem({ note, isSelected, onSelect, onDelete, onTogglePin }: {
  note: Note;
  isSelected: boolean;
  onSelect: () => void;
  onDelete: () => void;
  onTogglePin: () => void;
}) {
  const preview = note.content?.slice(0, 80) || 'Sem conteúdo';

  return (
    <div
      onClick={onSelect}
      className={`px-4 py-3 cursor-pointer group transition-colors border-b border-[#1a1a1a] ${
        isSelected ? 'bg-blue-600/10 border-l-2 !border-l-blue-500' : 'hover:bg-white/5'
      }`}
    >
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            {note.pinned && <Pin size={10} className="text-yellow-400 shrink-0" />}
            <p className="text-sm font-medium truncate">{note.title || 'Sem título'}</p>
          </div>
          <p className="text-xs text-gray-500 truncate mt-0.5">{preview}</p>
          <p className="text-[10px] text-gray-600 mt-1">
            {format(new Date(note.updated_at), "d MMM HH:mm", { locale: pt })}
          </p>
        </div>
        {note.color && (
          <div className="w-2 h-2 rounded-full shrink-0 mt-1.5"
            style={{ backgroundColor: note.color }} />
        )}
      </div>
    </div>
  );
}
