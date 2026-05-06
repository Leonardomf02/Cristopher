import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { format } from 'date-fns';
import { pt } from 'date-fns/locale';
import { ArrowLeft, Check, Plus, X, ExternalLink, Trash2, Star } from 'lucide-react';
import { tripsApi, expensesApi } from '../api';
import { Trip, TripPlace, Expense, TripPlaceCreate, ExpenseCreate, EXPENSE_CATEGORIES,
  TripRating, TripRatingCreate, TripRatingCategory, TRIP_RATING_CATEGORIES } from '../types';

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

export default function TripDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [trip, setTrip] = useState<Trip | null>(null);
  const [places, setPlaces] = useState<TripPlace[]>([]);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [ratings, setRatings] = useState<TripRating[]>([]);
  const [showPlaceModal, setShowPlaceModal] = useState(false);
  const [showExpenseModal, setShowExpenseModal] = useState(false);
  const [showRatingModal, setShowRatingModal] = useState(false);
  const [placeForm, setPlaceForm] = useState<TripPlaceCreate>({ trip_id: 0, name: '' });
  const [expenseForm, setExpenseForm] = useState<ExpenseCreate>({
    description: '', amount: 0, category: 'travel', date: format(new Date(), 'yyyy-MM-dd'),
  });
  const [ratingForm, setRatingForm] = useState<TripRatingCreate>({
    category: 'comida', name: '', rating: 7, notes: '', date: format(new Date(), 'yyyy-MM-dd'),
  });

  useEffect(() => { if (id) loadAll(); }, [id]);

  async function loadAll() {
    const tripId = Number(id);
    const [tripData, placesData, expData, ratingsData] = await Promise.all([
      tripsApi.get(tripId),
      tripsApi.listPlaces(tripId),
      tripsApi.listExpenses(tripId),
      tripsApi.listRatings(tripId),
    ]);
    setTrip(tripData);
    setPlaces(placesData);
    setExpenses(expData);
    setRatings(ratingsData);
  }

  async function setTripRatingField(field: 'rating_food' | 'rating_places' | 'rating_nightlife' | 'rating_gajas' | 'rating_overall', value: number | null) {
    if (!trip) return;
    setTrip({ ...trip, [field]: value });
    await tripsApi.update(trip.id, { [field]: value });
  }

  async function addRating() {
    if (!ratingForm.name.trim()) return;
    await tripsApi.addRating(Number(id), ratingForm);
    setShowRatingModal(false);
    setRatingForm({ category: 'comida', name: '', rating: 7, notes: '', date: format(new Date(), 'yyyy-MM-dd') });
    loadAll();
  }

  async function deleteRating(ratingId: number) {
    await tripsApi.deleteRating(ratingId);
    loadAll();
  }

  async function toggleVisited(place: TripPlace) {
    await tripsApi.updatePlace(place.id, { visited: !place.visited });
    loadAll();
  }

  async function addPlace() {
    if (!placeForm.name.trim()) return;
    await tripsApi.addPlace(Number(id), { ...placeForm, trip_id: Number(id) });
    setShowPlaceModal(false);
    loadAll();
  }

  async function deletePlace(placeId: number) {
    await tripsApi.deletePlace(placeId);
    loadAll();
  }

  async function addExpense() {
    if (!expenseForm.description.trim() || expenseForm.amount <= 0) return;
    await expensesApi.create({ ...expenseForm, trip_id: Number(id) });
    setShowExpenseModal(false);
    loadAll();
  }

  async function deleteTrip() {
    if (id) {
      await tripsApi.delete(Number(id));
      navigate('/trips');
    }
  }

  if (!trip) return <div className="text-gray-500">A carregar...</div>;

  const days = Math.ceil((new Date(trip.end_date).getTime() - new Date(trip.start_date).getTime()) / (1000 * 60 * 60 * 24)) + 1;
  const freePlaces = places.filter(p => p.is_free);
  const paidPlaces = places.filter(p => !p.is_free);
  const suggestedPlaces = places.filter(p => p.suggested);
  const userPlaces = places.filter(p => !p.suggested);
  const tripExpenseTotal = expenses.reduce((sum, e) => sum + e.amount, 0);

  return (
    <div>
      {/* Header */}
      <button onClick={() => navigate('/trips')} className="flex items-center gap-2 text-gray-400 hover:text-white mb-6 text-sm">
        <ArrowLeft size={16} /> Voltar às viagens
      </button>

      <div className="flex items-start justify-between mb-8">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span className="text-3xl sm:text-4xl">{COUNTRY_FLAGS[trip.destination] || '🌍'}</span>
            <h2 className="text-2xl sm:text-3xl font-bold">{trip.destination}</h2>
          </div>
          {trip.country && trip.country !== trip.destination && <p className="text-gray-500 ml-14">{trip.country}</p>}
          <p className="text-sm text-gray-500 mt-2 ml-14">
            {format(new Date(trip.start_date), "d 'de' MMMM", { locale: pt })} → {format(new Date(trip.end_date), "d 'de' MMMM yyyy", { locale: pt })}
            <span className="ml-2 text-cyan-400">({days} dias)</span>
          </p>
        </div>
        <button onClick={deleteTrip} className="px-3 py-2 bg-red-600/20 text-red-400 hover:bg-red-600/30 rounded-xl text-sm">
          <Trash2 size={16} />
        </button>
      </div>

      {/* Cost Overview */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 mb-8">
        <div className="bg-[#161616] rounded-2xl p-4 border border-[#222]">
          <p className="text-xs text-gray-500 mb-1">✈️ Voos</p>
          <p className="text-lg font-bold">€{trip.flights_cost.toFixed(0)}</p>
        </div>
        <div className="bg-[#161616] rounded-2xl p-4 border border-[#222]">
          <p className="text-xs text-gray-500 mb-1">🏠 Alojamento</p>
          <p className="text-lg font-bold">€{trip.accommodation_cost.toFixed(0)}</p>
        </div>
        <div className="bg-[#161616] rounded-2xl p-4 border border-[#222]">
          <p className="text-xs text-gray-500 mb-1">🍔 Comida</p>
          <p className="text-lg font-bold">€{trip.food_budget.toFixed(0)}</p>
        </div>
        <div className="bg-[#161616] rounded-2xl p-4 border border-[#222]">
          <p className="text-xs text-gray-500 mb-1">📦 Outros</p>
          <p className="text-lg font-bold">€{trip.other_costs.toFixed(0)}</p>
        </div>
        <div className="bg-cyan-600/20 rounded-2xl p-4 border border-cyan-500/30">
          <p className="text-xs text-cyan-300 mb-1">💰 Total</p>
          <p className="text-lg font-bold text-cyan-400">€{trip.total_cost.toFixed(0)}</p>
        </div>
      </div>

      {/* Aggregate ratings 0-10 */}
      <div className="bg-[#161616] rounded-2xl p-5 border border-[#222] mb-8">
        <div className="flex items-center gap-2 mb-4">
          <Star size={16} className="text-yellow-400" />
          <h3 className="text-sm font-medium text-gray-300">Avaliação da viagem (0-10)</h3>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
          <RatingSlider label="🍔 Comida"     value={trip.rating_food}      onChange={v => setTripRatingField('rating_food', v)} />
          <RatingSlider label="📍 Sítios"     value={trip.rating_places}    onChange={v => setTripRatingField('rating_places', v)} />
          <RatingSlider label="🍻 Noite"      value={trip.rating_nightlife} onChange={v => setTripRatingField('rating_nightlife', v)} />
          <RatingSlider label="💋 Gajas"      value={trip.rating_gajas}     onChange={v => setTripRatingField('rating_gajas', v)} pink />
          <RatingSlider label="✨ Geral"      value={trip.rating_overall}   onChange={v => setTripRatingField('rating_overall', v)} highlight />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* Places to visit */}
        <div className="col-span-2 space-y-6">
          {/* Suggested places */}
          {suggestedPlaces.length > 0 && (
            <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
              <div className="flex items-center justify-between p-4 border-b border-[#222]">
                <h3 className="text-sm font-medium text-gray-300">✨ Sugestões para {trip.destination}</h3>
              </div>
              <div className="divide-y divide-[#1a1a1a]">
                {suggestedPlaces.map(place => (
                  <PlaceItem key={place.id} place={place} onToggle={() => toggleVisited(place)} onDelete={() => deletePlace(place.id)} />
                ))}
              </div>
            </div>
          )}

          {/* User-added places */}
          <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-[#222]">
              <h3 className="text-sm font-medium text-gray-300">📍 Os teus sítios</h3>
              <button onClick={() => { setPlaceForm({ trip_id: Number(id), name: '' }); setShowPlaceModal(true); }}
                className="flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-300">
                <Plus size={14} /> Adicionar
              </button>
            </div>
            <div className="divide-y divide-[#1a1a1a]">
              {userPlaces.length === 0 ? (
                <div className="p-6 text-center text-gray-600 text-sm">Adiciona sítios para visitar</div>
              ) : (
                userPlaces.map(place => (
                  <PlaceItem key={place.id} place={place} onToggle={() => toggleVisited(place)} onDelete={() => deletePlace(place.id)} />
                ))
              )}
            </div>
          </div>
        </div>

        {/* Trip expenses */}
        <div className="space-y-4">
          <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-[#222]">
              <h3 className="text-sm font-medium text-gray-300">💸 Gastos da viagem</h3>
              <button onClick={() => {
                setExpenseForm({ description: '', amount: 0, category: 'travel', date: format(new Date(), 'yyyy-MM-dd') });
                setShowExpenseModal(true);
              }}
                className="flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-300">
                <Plus size={14} /> Adicionar
              </button>
            </div>

            {tripExpenseTotal > 0 && (
              <div className="px-4 py-3 border-b border-[#222] bg-cyan-600/5">
                <p className="text-xs text-gray-500">Total gastos registados</p>
                <p className="text-lg font-bold text-cyan-400">€{tripExpenseTotal.toFixed(2)}</p>
              </div>
            )}

            <div className="divide-y divide-[#1a1a1a]">
              {expenses.length === 0 ? (
                <div className="p-6 text-center text-gray-600 text-sm">Sem gastos registados</div>
              ) : (
                expenses.map(exp => {
                  const catInfo = EXPENSE_CATEGORIES.find(c => c.value === exp.category);
                  return (
                    <div key={exp.id} className="flex items-center gap-3 p-3 hover:bg-white/5">
                      <span className="text-lg">{catInfo?.emoji || '📦'}</span>
                      <div className="flex-1">
                        <p className="text-sm">{exp.description}</p>
                        <p className="text-xs text-gray-600">{format(new Date(exp.date), 'd MMM', { locale: pt })}</p>
                      </div>
                      <span className="text-sm font-medium text-red-400">-€{exp.amount.toFixed(2)}</span>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Summary by type */}
          <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
            <h4 className="text-xs text-gray-500 mb-3">Resumo grátis vs pago</h4>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-green-400">🆓 Grátis</span>
                <span className="text-sm font-medium">{freePlaces.length} sítios</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-yellow-400">💰 Pagos</span>
                <span className="text-sm font-medium">{paidPlaces.length} sítios</span>
              </div>
              <div className="flex items-center justify-between pt-2 border-t border-[#222]">
                <span className="text-xs text-gray-400">Custo estimado sítios</span>
                <span className="text-sm font-bold text-cyan-400">
                  €{paidPlaces.reduce((sum, p) => sum + p.estimated_cost, 0).toFixed(0)}
                </span>
              </div>
            </div>
          </div>

          {/* Free-form ratings */}
          <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-[#222]">
              <h3 className="text-sm font-medium text-gray-300">⭐ Ratings</h3>
              <button onClick={() => setShowRatingModal(true)}
                className="flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-300">
                <Plus size={14} /> Adicionar
              </button>
            </div>
            <div className="divide-y divide-[#1a1a1a]">
              {ratings.length === 0 ? (
                <div className="p-6 text-center text-gray-600 text-sm">Sem avaliações</div>
              ) : (
                ratings.map(r => {
                  const cat = TRIP_RATING_CATEGORIES.find(c => c.value === r.category);
                  const score = r.rating;
                  const tone = score >= 8 ? 'text-green-400' : score >= 5 ? 'text-yellow-400' : 'text-red-400';
                  return (
                    <div key={r.id} className="flex items-start gap-3 p-3 hover:bg-white/5 group">
                      <span className="text-lg">{cat?.emoji || '📦'}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm truncate">{r.name}</p>
                        {r.notes && <p className="text-xs text-gray-600 mt-0.5">{r.notes}</p>}
                      </div>
                      <span className={`text-sm font-bold ${tone}`}>{score.toFixed(1)}</span>
                      <button onClick={() => deleteRating(r.id)}
                        className="p-1 text-gray-700 hover:text-red-400 opacity-0 group-hover:opacity-100">
                        <X size={12} />
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Add Place Modal */}
      {showPlaceModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowPlaceModal(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 max-w-[90vw] w-[420px] border border-[#333]" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold">Adicionar Sítio</h3>
              <button onClick={() => setShowPlaceModal(false)} className="text-gray-500 hover:text-white"><X size={20} /></button>
            </div>
            <div className="space-y-3">
              <input type="text" placeholder="Nome do sítio" value={placeForm.name}
                onChange={e => setPlaceForm(f => ({ ...f, name: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-cyan-500" autoFocus />
              <textarea placeholder="Descrição" value={placeForm.description || ''}
                onChange={e => setPlaceForm(f => ({ ...f, description: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm resize-none" rows={2} />
              <div className="flex gap-3">
                <button onClick={() => setPlaceForm(f => ({ ...f, is_free: true, estimated_cost: 0 }))}
                  className={`flex-1 py-2 rounded-xl text-sm ${placeForm.is_free !== false ? 'bg-green-600 text-white' : 'bg-[#222] text-gray-400'}`}>
                  🆓 Grátis
                </button>
                <button onClick={() => setPlaceForm(f => ({ ...f, is_free: false }))}
                  className={`flex-1 py-2 rounded-xl text-sm ${placeForm.is_free === false ? 'bg-yellow-600 text-white' : 'bg-[#222] text-gray-400'}`}>
                  💰 Pago
                </button>
              </div>
              {placeForm.is_free === false && (
                <input type="number" placeholder="Custo estimado (€)" step="0.01" min="0"
                  value={placeForm.estimated_cost || ''}
                  onChange={e => setPlaceForm(f => ({ ...f, estimated_cost: parseFloat(e.target.value) || 0 }))}
                  className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm" />
              )}
            </div>
            <div className="flex gap-3 mt-4">
              <div className="flex-1" />
              <button onClick={() => setShowPlaceModal(false)} className="px-4 py-2 bg-[#222] rounded-xl text-sm">Cancelar</button>
              <button onClick={addPlace} className="px-5 py-2 bg-cyan-600 hover:bg-cyan-700 rounded-xl text-sm font-medium">Adicionar</button>
            </div>
          </div>
        </div>
      )}

      {/* Add Expense Modal */}
      {showExpenseModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowExpenseModal(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 max-w-[90vw] w-[420px] border border-[#333]" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold">Adicionar Gasto</h3>
              <button onClick={() => setShowExpenseModal(false)} className="text-gray-500 hover:text-white"><X size={20} /></button>
            </div>
            <div className="space-y-3">
              <input type="text" placeholder="Descrição" value={expenseForm.description}
                onChange={e => setExpenseForm(f => ({ ...f, description: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-cyan-500" autoFocus />
              <div className="flex gap-3">
                <input type="number" placeholder="Valor (€)" step="0.01" min="0"
                  value={expenseForm.amount || ''}
                  onChange={e => setExpenseForm(f => ({ ...f, amount: parseFloat(e.target.value) || 0 }))}
                  className="flex-1 bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm" />
                <input type="date" value={expenseForm.date}
                  onChange={e => setExpenseForm(f => ({ ...f, date: e.target.value }))}
                  className="flex-1 bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm" />
              </div>
              <div className="flex flex-wrap gap-2">
                {EXPENSE_CATEGORIES.map(cat => (
                  <button key={cat.value} onClick={() => setExpenseForm(f => ({ ...f, category: cat.value }))}
                    className={`px-2.5 py-1 rounded-lg text-xs ${
                      expenseForm.category === cat.value ? 'bg-cyan-600 text-white' : 'bg-[#222] text-gray-400'
                    }`}>
                    {cat.emoji} {cat.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex gap-3 mt-4">
              <div className="flex-1" />
              <button onClick={() => setShowExpenseModal(false)} className="px-4 py-2 bg-[#222] rounded-xl text-sm">Cancelar</button>
              <button onClick={addExpense} className="px-5 py-2 bg-cyan-600 hover:bg-cyan-700 rounded-xl text-sm font-medium">Adicionar</button>
            </div>
          </div>
        </div>
      )}

      {/* Add Rating Modal */}
      {showRatingModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowRatingModal(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 max-w-[90vw] w-[440px] border border-[#333]" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold">Adicionar Rating</h3>
              <button onClick={() => setShowRatingModal(false)} className="text-gray-500 hover:text-white"><X size={20} /></button>
            </div>
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                {TRIP_RATING_CATEGORIES.map(c => (
                  <button key={c.value} onClick={() => setRatingForm(f => ({ ...f, category: c.value as TripRatingCategory }))}
                    className={`px-2.5 py-1 rounded-lg text-xs ${
                      ratingForm.category === c.value ? 'bg-cyan-600 text-white' : 'bg-[#222] text-gray-400'
                    }`}>
                    {c.emoji} {c.label}
                  </button>
                ))}
              </div>
              <input type="text" placeholder="Nome (ex: Pierogi do bar X, Maria…)" value={ratingForm.name}
                onChange={e => setRatingForm(f => ({ ...f, name: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-cyan-500" autoFocus />
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs text-gray-400">Nota</span>
                  <span className={`text-base font-bold ${
                    ratingForm.rating >= 8 ? 'text-green-400' :
                    ratingForm.rating >= 5 ? 'text-yellow-400' : 'text-red-400'
                  }`}>{ratingForm.rating.toFixed(1)} / 10</span>
                </div>
                <input type="range" min={0} max={10} step={0.5} value={ratingForm.rating}
                  onChange={e => setRatingForm(f => ({ ...f, rating: parseFloat(e.target.value) }))}
                  className="w-full accent-cyan-500" />
              </div>
              <textarea placeholder="Notas (opcional)" value={ratingForm.notes || ''}
                onChange={e => setRatingForm(f => ({ ...f, notes: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm resize-none" rows={2} />
              <input type="date" value={ratingForm.date || ''}
                onChange={e => setRatingForm(f => ({ ...f, date: e.target.value }))}
                className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-2 text-sm" />
            </div>
            <div className="flex gap-3 mt-4">
              <div className="flex-1" />
              <button onClick={() => setShowRatingModal(false)} className="px-4 py-2 bg-[#222] rounded-xl text-sm">Cancelar</button>
              <button onClick={addRating} className="px-5 py-2 bg-cyan-600 hover:bg-cyan-700 rounded-xl text-sm font-medium">Adicionar</button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

function RatingSlider({ label, value, onChange, highlight, pink }: {
  label: string; value: number | null; onChange: (v: number | null) => void; highlight?: boolean; pink?: boolean;
}) {
  const v = value ?? 0;
  const tone = value === null ? 'text-gray-600' :
               v >= 8 ? 'text-green-400' :
               v >= 5 ? 'text-yellow-400' : 'text-red-400';
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs text-gray-400">{label}</span>
        <div className="flex items-center gap-1">
          <span className={`text-sm font-bold ${tone} ${highlight ? 'text-base' : ''}`}>
            {value === null ? '—' : v.toFixed(1)}
          </span>
          {value !== null && (
            <button onClick={() => onChange(null)} className="p-0.5 text-gray-700 hover:text-red-400">
              <X size={10} />
            </button>
          )}
        </div>
      </div>
      <input type="range" min={0} max={10} step={0.5} value={v}
        onChange={e => onChange(parseFloat(e.target.value))}
        className={`w-full ${pink ? 'accent-pink-500' : 'accent-cyan-500'}`} />
    </div>
  );
}


function PlaceItem({ place, onToggle, onDelete }: { place: TripPlace; onToggle: () => void; onDelete: () => void }) {
  return (
    <div className="flex items-center gap-3 p-4 hover:bg-white/5 group">
      <button onClick={onToggle}
        className={`w-6 h-6 rounded-full border-2 flex items-center justify-center shrink-0 transition-all ${
          place.visited ? 'border-green-400 bg-green-400' : 'border-gray-600 hover:border-green-400'
        }`}>
        {place.visited && <Check size={14} className="text-black" />}
      </button>
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <span className={`text-sm font-medium ${place.visited ? 'text-gray-500 line-through' : ''}`}>{place.name}</span>
          {place.is_free ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-green-500/20 text-green-400">Grátis</span>
          ) : (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-yellow-500/20 text-yellow-400">€{place.estimated_cost}</span>
          )}
          {place.url && (
            <a href={place.url} target="_blank" rel="noopener noreferrer" className="text-gray-600 hover:text-cyan-400">
              <ExternalLink size={12} />
            </a>
          )}
        </div>
        {place.description && <p className="text-xs text-gray-600 mt-0.5">{place.description}</p>}
      </div>
      <button onClick={onDelete} className="p-1 text-gray-700 hover:text-red-400 opacity-0 group-hover:opacity-100">
        <X size={14} />
      </button>
    </div>
  );
}
