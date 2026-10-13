import { useState, useEffect } from 'react';
import { format } from 'date-fns';
import { pt } from 'date-fns/locale';
import { Plus, X, MapPin, Plane, Calendar, Sparkles } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { tripsApi } from '../api';
import { Trip, TripCreate } from '../types';

// Despesas que caem nas datas de uma viagem mas ainda não estão ligadas a ela.
function DespesasPorLigar({ onLinked }: { onLinked: () => void }) {
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof tripsApi.linkExpenses>> | null>(null);
  const [busy, setBusy] = useState(false);

  const carregar = () => { tripsApi.linkExpenses(false).then(setPreview).catch(() => setPreview(null)); };
  useEffect(() => { carregar(); }, []);
  if (!preview || preview.linked === 0) return null;

  const ligar = async () => {
    setBusy(true);
    try { await tripsApi.linkExpenses(true); setPreview(null); onLinked(); }
    finally { setBusy(false); }
  };

  return (
    <div className="mb-6 rounded-2xl border border-cyan-500/25 bg-cyan-500/[0.07] p-4">
      <div className="flex flex-wrap items-center gap-3">
        <Plane size={15} className="text-cyan-400 shrink-0" />
        <span className="text-sm text-gray-300">
          {preview.linked} despesa{preview.linked > 1 ? 's' : ''} nas datas das tuas viagens ainda por ligar
        </span>
        <button
          onClick={ligar}
          disabled={busy}
          className="ml-auto text-xs px-3 py-1.5 rounded-lg bg-cyan-500/20 text-cyan-300 hover:bg-cyan-500/30 disabled:opacity-40"
        >
          {busy ? 'a ligar...' : 'ligar às viagens'}
        </button>
      </div>
      <div className="mt-2 space-y-1">
        {preview.by_trip.map(t => (
          <p key={t.trip_id} className="text-[11px] text-gray-500">
            {t.destination}: {t.count} despesa{t.count > 1 ? 's' : ''} · €{t.amount.toFixed(2)}
            {t.sample.length > 0 && ` — ${t.sample.slice(0, 2).join(', ')}`}
          </p>
        ))}
      </div>
    </div>
  );
}

export default function TripsPage() {
  const [trips, setTrips] = useState<Trip[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [detecting, setDetecting] = useState(false);
  const [detectResult, setDetectResult] = useState<string | null>(null);
  const navigate = useNavigate();

  const [form, setForm] = useState<TripCreate>({
    destination: '',
    country: '',
    start_date: format(new Date(), 'yyyy-MM-dd'),
    end_date: format(new Date(), 'yyyy-MM-dd'),
    notes: '',
    flights_cost: 0,
    accommodation_cost: 0,
    food_budget: 0,
    other_costs: 0,
  });

  useEffect(() => { loadTrips(); }, []);

  async function loadTrips() {
    const data = await tripsApi.list();
    setTrips(data);
  }

  function openNew() {
    setForm({
      destination: '',
      country: '',
      start_date: format(new Date(), 'yyyy-MM-dd'),
      end_date: format(new Date(), 'yyyy-MM-dd'),
      notes: '',
      flights_cost: 0,
      accommodation_cost: 0,
      food_budget: 0,
      other_costs: 0,
    });
    setShowModal(true);
  }

  async function handleSave() {
    if (!form.destination.trim()) return;
    await tripsApi.create(form);
    setShowModal(false);
    loadTrips();
  }

  // As idas fora de casa saem das despesas. A app sabe onde ele viveu em cada
  // mês, por isso viver na Polónia deixou de contar como uma viagem à Polónia.
  async function handleAutoDetect() {
    setDetecting(true);
    setDetectResult(null);
    try {
      const r = await tripsApi.detect(true);
      if (!r.trips_created && !r.expenses_linked) {
        setDetectResult('Nada de novo — as viagens já estão todas.');
      } else {
        const novas = r.trips.filter(t => !t.existing).map(t => t.destination);
        setDetectResult(
          `${r.trips_created} viagem(ns) nova(s)${novas.length ? ': ' + novas.join(', ') : ''}`
          + ` · ${r.expenses_linked} despesas ligadas`
        );
      }
      loadTrips();
    } catch {
      setDetectResult('Erro ao detetar viagens');
    } finally {
      setDetecting(false);
      setTimeout(() => setDetectResult(null), 8000);
    }
  }

  const upcoming = trips.filter(t => new Date(t.start_date) >= new Date());
  const past = trips.filter(t => new Date(t.start_date) < new Date());

  return (
    <div>
      <DespesasPorLigar onLinked={loadTrips} />

      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h2 className="text-2xl font-bold">Viagens</h2>
          <p className="text-gray-500 text-sm mt-1">Planeia as tuas aventuras</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleAutoDetect} disabled={detecting}
            className="flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 rounded-xl text-sm font-medium">
            <Sparkles size={16} className={detecting ? 'animate-spin' : ''} />
            {detecting ? 'A detetar...' : 'Auto-detetar'}
          </button>
          <button onClick={openNew}
            className="flex items-center gap-2 px-4 py-2 bg-cyan-600 hover:bg-cyan-700 rounded-xl text-sm font-medium">
            <Plus size={16} /> Nova Viagem
          </button>
        </div>
      </div>

      {/* Detection result toast */}
      {detectResult && (
        <div className="mb-4 p-3 bg-purple-600/10 border border-purple-500/20 rounded-xl text-sm text-purple-300 flex items-center gap-2">
          <Sparkles size={14} /> {detectResult}
        </div>
      )}

      {/* Upcoming Trips */}
      {upcoming.length > 0 && (
        <div className="mb-8">
          <h3 className="text-sm font-medium text-gray-400 mb-4 flex items-center gap-2">
            <Plane size={14} /> Próximas Viagens
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {upcoming.map(trip => (
              <TripCard key={trip.id} trip={trip} onClick={() => navigate(`/trips/${trip.id}`)} />
            ))}
          </div>
        </div>
      )}

      {/* Past Trips */}
      {past.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-gray-400 mb-4 flex items-center gap-2">
            <Calendar size={14} /> Viagens Anteriores
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {past.map(trip => (
              <TripCard key={trip.id} trip={trip} onClick={() => navigate(`/trips/${trip.id}`)} isPast />
            ))}
          </div>
        </div>
      )}

      {trips.length === 0 && (
        <div className="bg-[#161616] rounded-2xl border border-[#222] p-12 text-center">
          <Plane className="mx-auto mb-3 text-gray-600" size={40} />
          <p className="text-gray-500">Sem viagens planeadas</p>
          <p className="text-gray-600 text-sm mt-1">Adiciona a tua primeira viagem!</p>
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowModal(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 max-w-[90vw] w-[520px] border border-[#333] max-h-[90vh] overflow-y-auto"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-bold">Nova Viagem</h3>
              <button onClick={() => setShowModal(false)} className="text-gray-500 hover:text-white"><X size={20} /></button>
            </div>

            <div className="space-y-4">
              <div className="flex gap-3">
                <div className="flex-1">
                  <label className="text-xs text-gray-500 block mb-1">Destino</label>
                  <input type="text" placeholder="ex: Estocolmo"
                    value={form.destination} onChange={e => setForm(f => ({ ...f, destination: e.target.value }))}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-cyan-500"
                    autoFocus />
                </div>
                <div className="w-40">
                  <label className="text-xs text-gray-500 block mb-1">País</label>
                  <input type="text" placeholder="ex: Suécia"
                    value={form.country || ''} onChange={e => setForm(f => ({ ...f, country: e.target.value }))}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-cyan-500" />
                </div>
              </div>

              <div className="flex gap-3">
                <div className="flex-1">
                  <label className="text-xs text-gray-500 block mb-1">Data Início</label>
                  <input type="date" value={form.start_date}
                    onChange={e => setForm(f => ({ ...f, start_date: e.target.value }))}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm focus:outline-none focus:border-cyan-500" />
                </div>
                <div className="flex-1">
                  <label className="text-xs text-gray-500 block mb-1">Data Fim</label>
                  <input type="date" value={form.end_date}
                    onChange={e => setForm(f => ({ ...f, end_date: e.target.value }))}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm focus:outline-none focus:border-cyan-500" />
                </div>
              </div>

              <div className="border border-[#222] rounded-xl p-4">
                <p className="text-xs text-gray-500 mb-3">Custos Estimados</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-gray-600 block mb-1">✈️ Voos (€)</label>
                    <input type="number" step="0.01" min="0"
                      value={form.flights_cost || ''}
                      onChange={e => setForm(f => ({ ...f, flights_cost: parseFloat(e.target.value) || 0 }))}
                      className="w-full bg-[#1a1a1a] border border-[#333] rounded-lg px-3 py-2 text-sm" />
                  </div>
                  <div>
                    <label className="text-xs text-gray-600 block mb-1">🏠 Alojamento (€)</label>
                    <input type="number" step="0.01" min="0"
                      value={form.accommodation_cost || ''}
                      onChange={e => setForm(f => ({ ...f, accommodation_cost: parseFloat(e.target.value) || 0 }))}
                      className="w-full bg-[#1a1a1a] border border-[#333] rounded-lg px-3 py-2 text-sm" />
                  </div>
                  <div>
                    <label className="text-xs text-gray-600 block mb-1">🍔 Comida (€)</label>
                    <input type="number" step="0.01" min="0"
                      value={form.food_budget || ''}
                      onChange={e => setForm(f => ({ ...f, food_budget: parseFloat(e.target.value) || 0 }))}
                      className="w-full bg-[#1a1a1a] border border-[#333] rounded-lg px-3 py-2 text-sm" />
                  </div>
                  <div>
                    <label className="text-xs text-gray-600 block mb-1">📦 Outros (€)</label>
                    <input type="number" step="0.01" min="0"
                      value={form.other_costs || ''}
                      onChange={e => setForm(f => ({ ...f, other_costs: parseFloat(e.target.value) || 0 }))}
                      className="w-full bg-[#1a1a1a] border border-[#333] rounded-lg px-3 py-2 text-sm" />
                  </div>
                </div>
              </div>

              <textarea placeholder="Notas (opcional)"
                value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-cyan-500 resize-none"
                rows={2} />
            </div>

            <div className="flex gap-3 mt-6">
              <div className="flex-1" />
              <button onClick={() => setShowModal(false)}
                className="px-4 py-2.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm">Cancelar</button>
              <button onClick={handleSave}
                className="px-6 py-2.5 bg-cyan-600 hover:bg-cyan-700 rounded-xl text-sm font-medium">
                Criar Viagem
              </button>
            </div>

            <p className="text-xs text-gray-600 mt-4 text-center">
              💡 Ao criar a viagem, vamos sugerir automaticamente sítios para visitar!
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function TripCard({ trip, onClick, isPast }: { trip: Trip; onClick: () => void; isPast?: boolean }) {
  const days = Math.ceil((new Date(trip.end_date).getTime() - new Date(trip.start_date).getTime()) / (1000 * 60 * 60 * 24)) + 1;

  const COUNTRY_FLAGS: Record<string, string> = {
    'Polónia': '🇵🇱', 'Roménia': '🇷🇴', 'Suécia': '🇸🇪', 'Lituânia': '🇱🇹',
    'Letónia': '🇱🇻', 'Estónia': '🇪🇪', 'Alemanha': '🇩🇪', 'França': '🇫🇷',
    'Espanha': '🇪🇸', 'Itália': '🇮🇹', 'Reino Unido': '🇬🇧', 'Países Baixos': '🇳🇱',
    'Bélgica': '🇧🇪', 'Chéquia': '🇨🇿', 'Áustria': '🇦🇹', 'Hungria': '🇭🇺',
    'Grécia': '🇬🇷', 'Croácia': '🇭🇷', 'Bulgária': '🇧🇬', 'Portugal': '🇵🇹',
    'Irlanda': '🇮🇪', 'Dinamarca': '🇩🇰', 'Noruega': '🇳🇴', 'Finlândia': '🇫🇮',
    'Suíça': '🇨🇭', 'Turquia': '🇹🇷', 'Japão': '🇯🇵', 'Estados Unidos': '🇺🇸',
    'Brasil': '🇧🇷', 'Marrocos': '🇲🇦', 'Tailândia': '🇹🇭',
  };
  const flag = COUNTRY_FLAGS[trip.destination] || '🌍';

  return (
    <div onClick={onClick}
      className={`bg-[#161616] rounded-2xl border border-[#222] p-5 cursor-pointer hover:border-cyan-500/50 transition-all ${isPast ? 'opacity-70' : ''}`}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-2xl sm:text-3xl">{flag}</span>
          <div>
            <h4 className="font-bold text-lg">{trip.destination}</h4>
            {trip.country && trip.country !== trip.destination && <p className="text-sm text-gray-500">{trip.country}</p>}
          </div>
        </div>
        <span className="text-xs px-2 py-1 bg-cyan-500/20 text-cyan-400 rounded-full">{days} dias</span>
      </div>
      <div className="flex items-center gap-4 text-xs text-gray-500">
        <span>{format(new Date(trip.start_date), 'd MMM', { locale: pt })} → {format(new Date(trip.end_date), 'd MMM yyyy', { locale: pt })}</span>
      </div>
      {trip.total_cost > 0 && (
        <div className="mt-3 pt-3 border-t border-[#222]">
          <span className="text-sm font-medium text-cyan-400">€{trip.total_cost.toFixed(2)}</span>
          <span className="text-xs text-gray-600 ml-1">custo total</span>
        </div>
      )}
    </div>
  );
}
