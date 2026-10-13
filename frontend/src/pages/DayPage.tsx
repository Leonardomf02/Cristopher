// Um dia do princípio ao fim: sono, plano, o que esteve à frente do ecrã, jogos,
// gastos, música e notas — tudo na mesma linha do tempo.
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ChevronLeft, ChevronRight, Moon, Monitor, Gamepad2, Wallet, Music, Calendar,
  Check, CalendarDays, StickyNote, Plane,
} from 'lucide-react';
import { dayApi, DaySummary, DayTimelineItem } from '../api';

const MES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const DIA_SEMANA = ['domingo', 'segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado'];

const CATEGORIA_COR: Record<string, string> = {
  development: '#3B82F6', productivity: '#22C55E', communication: '#06B6D4',
  social: '#EC4899', gaming: '#8B5CF6', entertainment: '#F59E0B',
  browser: '#6B7280', system: '#4B5563', finance: '#10B981', shopping: '#F472B6',
  other: '#6B7280',
};

const CATEGORIA_NOME: Record<string, string> = {
  development: 'código', productivity: 'trabalho', communication: 'conversas',
  social: 'redes', gaming: 'jogos', entertainment: 'entretenimento',
  browser: 'browser', system: 'sistema', finance: 'contas', shopping: 'compras',
  other: 'outros',
};

function hm(segundos: number): string {
  const m = Math.round(segundos / 60);
  return m >= 60 ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}` : `${m}min`;
}

function hoje(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

const ICONE: Record<string, JSX.Element> = {
  sleep: <Moon size={13} />,
  plan: <CalendarDays size={13} />,
  screen: <Monitor size={13} />,
  game: <Gamepad2 size={13} />,
  expense: <Wallet size={13} />,
  event: <Calendar size={13} />,
  task: <Check size={13} />,
  music: <Music size={13} />,
};

export default function DayPage() {
  const { date } = useParams();
  const navigate = useNavigate();
  const dia = date || hoje();
  const [d, setD] = useState<DaySummary | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [semRuido, setSemRuido] = useState(true);

  useEffect(() => {
    setD(null);
    setErro(null);
    dayApi.get(dia).then(setD).catch(e => setErro(e?.message || 'Não consegui carregar o dia'));
  }, [dia]);

  const [ano, mes, num] = dia.split('-').map(Number);
  const dataObj = new Date(ano, mes - 1, num);
  const titulo = `${DIA_SEMANA[dataObj.getDay()]}, ${num} de ${MES[mes - 1]}`;

  // Blocos de ecrã curtos são ruído: escondê-los deixa ver a forma do dia.
  const itens = (d?.timeline || []).filter(
    i => !(semRuido && i.kind === 'screen' && (i.seconds || 0) < 600)
  );

  const s = d?.summary;

  return (
    <div className="max-w-4xl mx-auto pb-10">
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <div>
          <h2 className="text-2xl sm:text-3xl font-bold capitalize">{titulo}</h2>
          <p className="text-sm text-gray-500 mt-1">
            {dia === hoje() ? 'hoje' : `${ano}`}
            {s?.trip && <span className="text-blue-400"> · em {s.trip}</span>}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => navigate(`/day/${d?.prev}`)} disabled={!d}
            className="p-2 rounded-lg bg-[#161616] border border-[#222] text-gray-400 hover:text-white disabled:opacity-40">
            <ChevronLeft size={16} />
          </button>
          <button onClick={() => navigate(`/day/${hoje()}`)}
            className="px-3 py-2 rounded-lg bg-[#161616] border border-[#222] text-xs text-gray-400 hover:text-white">
            hoje
          </button>
          <button onClick={() => navigate(`/day/${d?.next}`)} disabled={!d || d.next > hoje()}
            className="p-2 rounded-lg bg-[#161616] border border-[#222] text-gray-400 hover:text-white disabled:opacity-40">
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      {erro && <p className="text-sm text-red-400">{erro}</p>}
      {!d && !erro && <p className="text-sm text-gray-600">a carregar…</p>}

      {d && s && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-5">
            <Cartao titulo="Sono" valor={s.sleep_hours ? `${s.sleep_hours}h` : '—'}
              sub={s.bedtime && s.wake_time ? `${s.bedtime}–${s.wake_time}` : 'sem registo'} />
            <Cartao titulo="Código" valor={s.code_seconds ? hm(s.code_seconds) : '—'}
              sub={s.top_projects[0]?.name || 'nada'} />
            <Cartao titulo="Ecrã" valor={s.screen_seconds ? hm(s.screen_seconds) : '—'}
              sub={`${d.timeline.filter(i => i.kind === 'screen').length} blocos`} />
            <Cartao titulo="Jogos" valor={s.games ? `${s.games}` : '—'}
              sub={s.games ? `${s.wins}W-${s.games - s.wins}L` : 'nenhum'} />
            <Cartao titulo="Gastos" valor={s.spent ? `€${s.spent.toFixed(0)}` : '—'}
              sub={s.notes ? `${s.notes} notas` : ''} />
            <Cartao titulo="Humor" valor={s.mood ? `${s.mood}/10` : '—'}
              sub={s.music_seconds ? `${hm(s.music_seconds)} música` : ''} />
          </div>

          {(s.journal || s.mood_note) && (
            <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 mb-5">
              <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-1">O que escreveste</p>
              <p className="text-sm text-gray-300 whitespace-pre-wrap leading-relaxed">
                {s.journal || s.mood_note}
              </p>
            </div>
          )}

          <div className="flex items-center justify-between gap-2 mb-2">
            <h3 className="text-sm font-medium text-gray-300">Linha do tempo</h3>
            <button onClick={() => setSemRuido(v => !v)} className="text-[11px] text-gray-500 hover:text-gray-300">
              {semRuido ? 'mostrar tudo' : 'esconder blocos curtos'}
            </button>
          </div>

          {itens.length === 0 ? (
            <p className="text-sm text-gray-600 py-8 text-center border border-dashed border-[#222] rounded-2xl">
              Nada registado neste dia.
            </p>
          ) : (
            <div className="bg-[#161616] rounded-2xl border border-[#222] p-2 sm:p-3">
              {itens.map((i, idx) => <Linha key={`${i.kind}-${i.start}-${idx}`} item={i} />)}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Cartao({ titulo, valor, sub }: { titulo: string; valor: string; sub?: string }) {
  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] p-3">
      <p className="text-[10px] uppercase tracking-wider text-gray-600">{titulo}</p>
      <p className="text-xl font-bold mt-0.5">{valor}</p>
      {sub && <p className="text-[10px] text-gray-600 truncate">{sub}</p>}
    </div>
  );
}

function Linha({ item }: { item: DayTimelineItem }) {
  const cor = item.kind === 'screen'
    ? (CATEGORIA_COR[item.category || 'other'] || '#6B7280')
    : item.kind === 'game' ? (item.won ? '#10B981' : '#EF4444')
    : item.kind === 'plan' ? '#3B82F6'
    : item.kind === 'expense' ? '#F59E0B'
    : item.kind === 'music' ? '#1DB954'
    : item.kind === 'sleep' ? '#8B5CF6'
    : '#6B7280';

  const titulo = item.kind === 'screen'
    ? item.app
    : item.text;

  const detalhe = item.kind === 'screen'
    ? (item.titles || []).join(' · ')
    : item.detail;

  return (
    <div className="flex items-start gap-3 px-2 py-1.5 rounded-lg hover:bg-white/[0.03] group">
      <span className="text-[11px] tabular-nums text-gray-600 w-[86px] shrink-0 pt-0.5">
        {item.no_time ? 'sem hora' : `${item.start}${item.end && item.end !== item.start ? `–${item.end}` : ''}`}
      </span>
      <span className="shrink-0 mt-0.5 rounded-md p-1" style={{ backgroundColor: `${cor}22`, color: cor }}>
        {ICONE[item.kind] || <StickyNote size={13} />}
      </span>
      <div className="min-w-0 flex-1">
        <p className={`text-sm truncate ${item.done ? 'text-gray-500 line-through' : ''}`}>
          {titulo}
          {item.kind === 'screen' && item.seconds ? (
            <span className="text-[11px] text-gray-600 ml-2">{hm(item.seconds)} · {CATEGORIA_NOME[item.category || 'other']}</span>
          ) : null}
          {item.kind === 'music' && item.seconds ? (
            <span className="text-[11px] text-gray-600 ml-2">{hm(item.seconds)}</span>
          ) : null}
        </p>
        {detalhe && <p className="text-[11px] text-gray-600 truncate">{detalhe}</p>}
      </div>
      {item.kind === 'plan' && (
        <span className="text-[10px] text-gray-600 shrink-0 pt-1">plano</span>
      )}
    </div>
  );
}
