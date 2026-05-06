from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from datetime import date, timedelta
from collections import defaultdict
import logging

from database import get_db
from models import Trip, TripPlace, Expense, TripRating, TripGaja, DayType
from schemas import (
    TripCreate, TripUpdate, TripOut,
    TripPlaceCreate, TripPlaceUpdate, TripPlaceOut,
    TripRatingCreate, TripRatingUpdate, TripRatingOut,
    TripGajaCreate, TripGajaUpdate, TripGajaOut,
    ExpenseOut,
)

router = APIRouter(prefix="/api/trips", tags=["Trips"])

# Curated suggestions for popular destinations
DESTINATION_SUGGESTIONS: dict[str, list[dict]] = {
    "stockholm": [
        {"name": "Gamla Stan (Old Town)", "description": "Medieval old town with cobblestone streets and colorful buildings", "is_free": True, "estimated_cost": 0},
        {"name": "Vasa Museum", "description": "Home to a nearly intact 17th century ship", "is_free": False, "estimated_cost": 20},
        {"name": "ABBA The Museum", "description": "Interactive exhibition about the legendary pop group", "is_free": False, "estimated_cost": 25},
        {"name": "Djurgården Island", "description": "Beautiful island with parks, museums and gardens", "is_free": True, "estimated_cost": 0},
        {"name": "Fotografiska", "description": "Contemporary photography museum", "is_free": False, "estimated_cost": 19},
        {"name": "Royal Palace", "description": "Official residence of the Swedish monarch", "is_free": False, "estimated_cost": 18},
        {"name": "Södermalm District", "description": "Trendy neighborhood with vintage shops and cafés", "is_free": True, "estimated_cost": 0},
        {"name": "Skansen Open-Air Museum", "description": "World's oldest open-air museum", "is_free": False, "estimated_cost": 22},
    ],
    "paris": [
        {"name": "Eiffel Tower", "description": "Iconic iron tower with panoramic city views", "is_free": False, "estimated_cost": 26},
        {"name": "Louvre Museum", "description": "World's largest art museum", "is_free": False, "estimated_cost": 17},
        {"name": "Notre-Dame Cathedral", "description": "Medieval Catholic cathedral (exterior visit)", "is_free": True, "estimated_cost": 0},
        {"name": "Sacré-Cœur Basilica", "description": "Hilltop church with stunning views of the city", "is_free": True, "estimated_cost": 0},
        {"name": "Champs-Élysées", "description": "Famous tree-lined avenue for walking and shopping", "is_free": True, "estimated_cost": 0},
        {"name": "Musée d'Orsay", "description": "Impressionist and post-impressionist art", "is_free": False, "estimated_cost": 16},
        {"name": "Montmartre", "description": "Artistic hilltop village with bohemian vibes", "is_free": True, "estimated_cost": 0},
    ],
    "london": [
        {"name": "British Museum", "description": "World-class collection of art and antiquities", "is_free": True, "estimated_cost": 0},
        {"name": "Tower of London", "description": "Historic castle and home of the Crown Jewels", "is_free": False, "estimated_cost": 33},
        {"name": "Buckingham Palace", "description": "The official London residence of the sovereign", "is_free": False, "estimated_cost": 30},
        {"name": "Hyde Park", "description": "One of London's largest and most famous parks", "is_free": True, "estimated_cost": 0},
        {"name": "Tate Modern", "description": "National gallery of modern art", "is_free": True, "estimated_cost": 0},
        {"name": "Borough Market", "description": "One of the oldest and largest food markets", "is_free": True, "estimated_cost": 0},
    ],
    "lisbon": [
        {"name": "Belém Tower", "description": "16th-century fortified tower on the Tagus River", "is_free": False, "estimated_cost": 10},
        {"name": "Jerónimos Monastery", "description": "UNESCO World Heritage Gothic monastery", "is_free": False, "estimated_cost": 10},
        {"name": "Alfama District", "description": "Oldest district with narrow streets and Fado music", "is_free": True, "estimated_cost": 0},
        {"name": "Tram 28", "description": "Iconic yellow tram through historic neighborhoods", "is_free": False, "estimated_cost": 3},
        {"name": "Time Out Market", "description": "Food hall with the best of Lisbon gastronomy", "is_free": True, "estimated_cost": 0},
        {"name": "São Jorge Castle", "description": "Medieval castle with panoramic city views", "is_free": False, "estimated_cost": 10},
        {"name": "LX Factory", "description": "Creative hub with shops, restaurants and exhibitions", "is_free": True, "estimated_cost": 0},
        {"name": "Pastéis de Belém", "description": "Famous pastry shop for Portuguese custard tarts", "is_free": False, "estimated_cost": 5},
    ],
    "barcelona": [
        {"name": "Sagrada Família", "description": "Gaudí's iconic unfinished basilica", "is_free": False, "estimated_cost": 26},
        {"name": "Park Güell", "description": "Colorful mosaic park designed by Gaudí", "is_free": False, "estimated_cost": 10},
        {"name": "La Rambla", "description": "Famous street for walking, street performers, and markets", "is_free": True, "estimated_cost": 0},
        {"name": "Gothic Quarter", "description": "Medieval streets in the heart of the city", "is_free": True, "estimated_cost": 0},
        {"name": "Barceloneta Beach", "description": "Popular city beach for swimming and sunbathing", "is_free": True, "estimated_cost": 0},
        {"name": "Casa Batlló", "description": "Gaudí's colorful masterpiece building", "is_free": False, "estimated_cost": 35},
    ],
    "rome": [
        {"name": "Colosseum", "description": "Ancient amphitheatre and icon of Rome", "is_free": False, "estimated_cost": 16},
        {"name": "Vatican Museums", "description": "Vast collection of art including the Sistine Chapel", "is_free": False, "estimated_cost": 17},
        {"name": "Pantheon", "description": "Ancient Roman temple with a remarkable dome", "is_free": True, "estimated_cost": 0},
        {"name": "Trevi Fountain", "description": "Baroque fountain, toss a coin for good luck", "is_free": True, "estimated_cost": 0},
        {"name": "Roman Forum", "description": "Ruins of the ancient government center", "is_free": False, "estimated_cost": 16},
        {"name": "Trastevere", "description": "Charming neighborhood with great restaurants", "is_free": True, "estimated_cost": 0},
    ],
    "tokyo": [
        {"name": "Senso-ji Temple", "description": "Tokyo's oldest Buddhist temple in Asakusa", "is_free": True, "estimated_cost": 0},
        {"name": "Shibuya Crossing", "description": "The world's busiest pedestrian crossing", "is_free": True, "estimated_cost": 0},
        {"name": "Meiji Shrine", "description": "Shinto shrine surrounded by forest", "is_free": True, "estimated_cost": 0},
        {"name": "Tsukiji Outer Market", "description": "Fresh seafood and street food paradise", "is_free": True, "estimated_cost": 0},
        {"name": "teamLab Borderless", "description": "Immersive digital art museum", "is_free": False, "estimated_cost": 30},
        {"name": "Akihabara", "description": "Electronics and anime culture district", "is_free": True, "estimated_cost": 0},
    ],
    "amsterdam": [
        {"name": "Anne Frank House", "description": "Historic house where Anne Frank wrote her diary", "is_free": False, "estimated_cost": 16},
        {"name": "Rijksmuseum", "description": "Dutch art and history masterpieces", "is_free": False, "estimated_cost": 22},
        {"name": "Vondelpark", "description": "Beautiful urban park for relaxing", "is_free": True, "estimated_cost": 0},
        {"name": "Canal Ring", "description": "UNESCO World Heritage canal belt for walking", "is_free": True, "estimated_cost": 0},
        {"name": "Van Gogh Museum", "description": "Largest collection of Van Gogh's works", "is_free": False, "estimated_cost": 20},
        {"name": "Jordaan Neighborhood", "description": "Trendy area with galleries, shops and cafés", "is_free": True, "estimated_cost": 0},
    ],
}


def _get_suggestions(destination: str) -> list[dict]:
    dest_lower = destination.lower()
    for key, suggestions in DESTINATION_SUGGESTIONS.items():
        if key in dest_lower:
            return suggestions
    return []


VACATION_TYPE = "Férias"
VACATION_COLOR = "#8B5CF6"


def _fill_vacation_days(db: Session, start: date, end: date, note: str) -> None:
    """Mark every day in [start, end] as Férias unless the day already has a DayType."""
    if not start or not end or end < start:
        return
    existing_dates = {
        d.date for d in db.query(DayType).filter(
            DayType.date >= start, DayType.date <= end
        ).all()
    }
    cur = start
    while cur <= end:
        if cur not in existing_dates:
            db.add(DayType(date=cur, type_name=VACATION_TYPE, color=VACATION_COLOR, note=note))
        cur += timedelta(days=1)
    db.commit()


def _clear_vacation_days(db: Session, start: date, end: date) -> None:
    """Remove vacation DayType entries inside [start, end]. Leaves manual entries alone."""
    if not start or not end or end < start:
        return
    db.query(DayType).filter(
        DayType.date >= start,
        DayType.date <= end,
        DayType.type_name == VACATION_TYPE,
    ).delete(synchronize_session=False)
    db.commit()


@router.get("/", response_model=list[TripOut])
def list_trips(db: Session = Depends(get_db)):
    trips = db.query(Trip).order_by(Trip.start_date.desc()).all()
    result = []
    for trip in trips:
        out = TripOut.model_validate(trip)
        out.total_cost = trip.flights_cost + trip.accommodation_cost + trip.food_budget + trip.other_costs
        result.append(out)
    return result


@router.get("/{trip_id}", response_model=TripOut)
def get_trip(trip_id: int, db: Session = Depends(get_db)):
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    out = TripOut.model_validate(trip)
    out.total_cost = trip.flights_cost + trip.accommodation_cost + trip.food_budget + trip.other_costs
    out.rating_food = trip.rating_food
    out.rating_places = trip.rating_places
    out.rating_nightlife = trip.rating_nightlife
    out.rating_overall = trip.rating_overall
    return out


@router.post("/", response_model=TripOut)
def create_trip(data: TripCreate, db: Session = Depends(get_db)):
    trip = Trip(**data.model_dump())
    db.add(trip)
    db.commit()
    db.refresh(trip)

    # Auto-suggest places for the destination
    suggestions = _get_suggestions(data.destination)
    for s in suggestions:
        place = TripPlace(trip_id=trip.id, suggested=True, **s)
        db.add(place)
    if suggestions:
        db.commit()

    _fill_vacation_days(db, trip.start_date, trip.end_date, f"Viagem: {trip.destination}")

    out = TripOut.model_validate(trip)
    out.total_cost = trip.flights_cost + trip.accommodation_cost + trip.food_budget + trip.other_costs
    out.rating_food = trip.rating_food
    out.rating_places = trip.rating_places
    out.rating_nightlife = trip.rating_nightlife
    out.rating_overall = trip.rating_overall
    return out


@router.put("/{trip_id}", response_model=TripOut)
def update_trip(trip_id: int, data: TripUpdate, db: Session = Depends(get_db)):
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    old_start, old_end = trip.start_date, trip.end_date
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(trip, key, value)
    db.commit()
    db.refresh(trip)

    if (trip.start_date, trip.end_date) != (old_start, old_end):
        _clear_vacation_days(db, old_start, old_end)
        _fill_vacation_days(db, trip.start_date, trip.end_date, f"Viagem: {trip.destination}")
    out = TripOut.model_validate(trip)
    out.total_cost = trip.flights_cost + trip.accommodation_cost + trip.food_budget + trip.other_costs
    out.rating_food = trip.rating_food
    out.rating_places = trip.rating_places
    out.rating_nightlife = trip.rating_nightlife
    out.rating_overall = trip.rating_overall
    return out


@router.delete("/{trip_id}")
def delete_trip(trip_id: int, db: Session = Depends(get_db)):
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    trip_start, trip_end = trip.start_date, trip.end_date
    # Delete associated places and expenses
    db.query(TripPlace).filter(TripPlace.trip_id == trip_id).delete()
    # Unassign expenses (don't delete them)
    db.query(Expense).filter(Expense.trip_id == trip_id).update({Expense.trip_id: None})
    db.delete(trip)
    db.commit()
    _clear_vacation_days(db, trip_start, trip_end)
    return {"ok": True}


# ── Trip Places ──────────────────────────────────────────────────

@router.get("/{trip_id}/places", response_model=list[TripPlaceOut])
def list_trip_places(trip_id: int, db: Session = Depends(get_db)):
    return db.query(TripPlace).filter(TripPlace.trip_id == trip_id).all()


@router.post("/{trip_id}/places", response_model=TripPlaceOut)
def add_trip_place(trip_id: int, data: TripPlaceCreate, db: Session = Depends(get_db)):
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    place = TripPlace(**data.model_dump(), suggested=False)
    place.trip_id = trip_id
    db.add(place)
    db.commit()
    db.refresh(place)
    return place


@router.put("/places/{place_id}", response_model=TripPlaceOut)
def update_trip_place(place_id: int, data: TripPlaceUpdate, db: Session = Depends(get_db)):
    place = db.query(TripPlace).filter(TripPlace.id == place_id).first()
    if not place:
        raise HTTPException(status_code=404, detail="Place not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(place, key, value)
    db.commit()
    db.refresh(place)
    return place


@router.delete("/places/{place_id}")
def delete_trip_place(place_id: int, db: Session = Depends(get_db)):
    place = db.query(TripPlace).filter(TripPlace.id == place_id).first()
    if not place:
        raise HTTPException(status_code=404, detail="Place not found")
    db.delete(place)
    db.commit()
    return {"ok": True}


# ── Trip Expenses ────────────────────────────────────────────────

@router.get("/{trip_id}/expenses", response_model=list[ExpenseOut])
def list_trip_expenses(trip_id: int, db: Session = Depends(get_db)):
    return db.query(Expense).filter(Expense.trip_id == trip_id).order_by(Expense.date.desc()).all()


# ── Trip Ratings (free-form: comida, sítios, noite, encontros…) ──

@router.get("/{trip_id}/ratings", response_model=list[TripRatingOut])
def list_trip_ratings(trip_id: int, db: Session = Depends(get_db)):
    return (
        db.query(TripRating)
        .filter(TripRating.trip_id == trip_id)
        .order_by(TripRating.created_at.desc())
        .all()
    )


@router.post("/{trip_id}/ratings", response_model=TripRatingOut)
def add_trip_rating(trip_id: int, data: TripRatingCreate, db: Session = Depends(get_db)):
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    rating = TripRating(trip_id=trip_id, **data.model_dump())
    db.add(rating)
    db.commit()
    db.refresh(rating)
    return rating


@router.put("/ratings/{rating_id}", response_model=TripRatingOut)
def update_trip_rating(rating_id: int, data: TripRatingUpdate, db: Session = Depends(get_db)):
    rating = db.query(TripRating).filter(TripRating.id == rating_id).first()
    if not rating:
        raise HTTPException(status_code=404, detail="Rating not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(rating, key, value)
    db.commit()
    db.refresh(rating)
    return rating


@router.delete("/ratings/{rating_id}")
def delete_trip_rating(rating_id: int, db: Session = Depends(get_db)):
    rating = db.query(TripRating).filter(TripRating.id == rating_id).first()
    if not rating:
        raise HTTPException(status_code=404, detail="Rating not found")
    db.delete(rating)
    db.commit()
    return {"ok": True}


# ── Trip Gajas ───────────────────────────────────────────────────

@router.get("/{trip_id}/gajas", response_model=list[TripGajaOut])
def list_trip_gajas(trip_id: int, db: Session = Depends(get_db)):
    return (
        db.query(TripGaja)
        .filter(TripGaja.trip_id == trip_id)
        .order_by(TripGaja.created_at.desc())
        .all()
    )


@router.post("/{trip_id}/gajas", response_model=TripGajaOut)
def add_trip_gaja(trip_id: int, data: TripGajaCreate, db: Session = Depends(get_db)):
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    gaja = TripGaja(trip_id=trip_id, **data.model_dump())
    db.add(gaja)
    db.commit()
    db.refresh(gaja)
    return gaja


@router.put("/gajas/{gaja_id}", response_model=TripGajaOut)
def update_trip_gaja(gaja_id: int, data: TripGajaUpdate, db: Session = Depends(get_db)):
    gaja = db.query(TripGaja).filter(TripGaja.id == gaja_id).first()
    if not gaja:
        raise HTTPException(status_code=404, detail="Gaja not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(gaja, key, value)
    db.commit()
    db.refresh(gaja)
    return gaja


@router.delete("/gajas/{gaja_id}")
def delete_trip_gaja(gaja_id: int, db: Session = Depends(get_db)):
    gaja = db.query(TripGaja).filter(TripGaja.id == gaja_id).first()
    if not gaja:
        raise HTTPException(status_code=404, detail="Gaja not found")
    db.delete(gaja)
    db.commit()
    return {"ok": True}


# ── Auto-detect trips from expenses ─────────────────────────────

logger = logging.getLogger(__name__)

# Map country codes to readable names
COUNTRY_NAMES = {
    "POL": "Polónia", "PL": "Polónia",
    "SWE": "Suécia", "SE": "Suécia",
    "ROM": "Roménia", "RO": "Roménia",
    "LTU": "Lituânia", "LT": "Lituânia",
    "LVA": "Letónia", "LV": "Letónia",
    "EST": "Estónia", "EE": "Estónia",
    "DEU": "Alemanha", "DE": "Alemanha",
    "FRA": "França", "FR": "França",
    "ESP": "Espanha", "ES": "Espanha",
    "ITA": "Itália", "IT": "Itália",
    "GBR": "Reino Unido", "GB": "Reino Unido",
    "NLD": "Países Baixos", "NL": "Países Baixos",
    "BEL": "Bélgica", "BE": "Bélgica",
    "CZE": "Chéquia", "CZ": "Chéquia",
    "AUT": "Áustria", "AT": "Áustria",
    "HUN": "Hungria", "HU": "Hungria",
    "GRC": "Grécia", "GR": "Grécia",
    "HRV": "Croácia", "HR": "Croácia",
    "BGR": "Bulgária", "BG": "Bulgária",
    "B": "Roménia",  # Bucharest abbreviation from Revolut
}

# Map currency to likely country when merchant_country is missing
CURRENCY_COUNTRY = {
    "PLN": "POL", "SEK": "SWE", "RON": "ROM", "CZK": "CZE",
    "HUF": "HUN", "GBP": "GBR", "DKK": "DNK", "NOK": "NOR",
    "CHF": "CHE", "HRK": "HRV", "BGN": "BGR", "TRY": "TUR",
}

# Map country codes to major city (for destination name when city is unknown)
COUNTRY_CITIES = {
    "POL": "Polónia", "SWE": "Estocolmo", "ROM": "Bucareste",
    "LTU": "Lituânia", "LVA": "Letónia", "EST": "Estónia",
    "DEU": "Alemanha", "B": "Bucareste",
}


# Normalize country codes to canonical 3-letter form
COUNTRY_NORMALIZE = {
    "PL": "POL", "SE": "SWE", "RO": "ROM", "LT": "LTU",
    "LV": "LVA", "EE": "EST", "DE": "DEU",
    "FR": "FRA", "ES": "ESP", "IT": "ITA", "GB": "GBR",
    "NL": "NLD", "BE": "BEL", "CZ": "CZE", "AT": "AUT",
    "HU": "HUN", "GR": "GRC", "HR": "HRV", "BG": "BGR",
    "B": "ROM",  # Bucharest abbreviation from Revolut
}


@router.post("/auto-detect")
def auto_detect_trips(db: Session = Depends(get_db)):
    """
    Analyze unassigned expenses with foreign country/currency data
    and automatically create trips — one trip per country visited.
    """
    # Get all expenses not assigned to a trip
    expenses = (
        db.query(Expense)
        .filter(Expense.trip_id.is_(None))
        .order_by(Expense.date)
        .all()
    )

    # Separate foreign expenses and transfer expenses
    foreign_expenses = []
    transfer_expenses = []

    for exp in expenses:
        country = (exp.merchant_country or "").strip().upper()
        currency = (exp.original_currency or "").strip().upper()

        # Ignore single-letter country codes (unreliable Revolut data)
        if len(country) == 1:
            country = ""

        # Infer country from currency if missing
        if not country and currency in CURRENCY_COUNTRY:
            country = CURRENCY_COUNTRY[currency]

        # Normalize to canonical 3-letter code
        country = COUNTRY_NORMALIZE.get(country, country)

        is_foreign = (
            (country and country not in ("", "PRT", "PT", "POR"))
            or (currency and currency not in ("", "EUR"))
        )

        if is_foreign:
            foreign_expenses.append((exp, country))
        elif "transfer" in exp.description.lower() and exp.category == "travel":
            transfer_expenses.append(exp)

    if not foreign_expenses:
        return {"trips_created": 0, "expenses_assigned": 0, "trips": []}

    # Group expenses by country — one trip per country
    # First, group into continuous trip periods (gap ≤ 2 days)
    trip_periods = []
    current_period = {
        "start": foreign_expenses[0][0].date,
        "end": foreign_expenses[0][0].date,
        "expenses": [(foreign_expenses[0][0], foreign_expenses[0][1])],
    }

    for exp, country in foreign_expenses[1:]:
        gap = (exp.date - current_period["end"]).days
        if gap <= 2:
            current_period["end"] = exp.date
            current_period["expenses"].append((exp, country))
        else:
            trip_periods.append(current_period)
            current_period = {
                "start": exp.date,
                "end": exp.date,
                "expenses": [(exp, country)],
            }
    trip_periods.append(current_period)

    # Now split each period into per-country segments
    segments = []
    for period in trip_periods:
        country_groups: dict[str, list] = defaultdict(list)
        for exp, country in period["expenses"]:
            c = country if country else "UNKNOWN"
            country_groups[c].append(exp)

        for country_code, exps in country_groups.items():
            exps_sorted = sorted(exps, key=lambda e: e.date)
            segments.append({
                "start": exps_sorted[0].date,
                "end": exps_sorted[-1].date,
                "countries": {country_code},
                "cities": {e.merchant_city for e in exps_sorted if e.merchant_city},
                "expenses": exps_sorted,
                "period_start": period["start"],
                "period_end": period["end"],
            })

    # Create trips from segments
    created_trips = []
    total_assigned = 0

    for seg in segments:
        # One country per trip
        country_code = list(seg["countries"])[0] if seg["countries"] else ""
        destination = COUNTRY_NAMES.get(country_code, country_code) or "Viagem"
        country_str = destination

        # Check if a trip already exists for this country and overlapping dates
        existing = (
            db.query(Trip)
            .filter(
                Trip.start_date <= seg["end"],
                Trip.end_date >= seg["start"],
                Trip.destination == destination,
            )
            .first()
        )
        if existing:
            # Assign expenses to existing trip
            for exp in seg["expenses"]:
                exp.trip_id = existing.id
                total_assigned += 1
            # Also assign transfer expenses within date range
            for texp in transfer_expenses:
                if seg["start"] <= texp.date <= seg["end"]:
                    texp.trip_id = existing.id
                    total_assigned += 1
            db.commit()
            created_trips.append({
                "id": existing.id,
                "destination": existing.destination,
                "existing": True,
                "expenses_assigned": len(seg["expenses"]),
            })
            continue

        # Create new trip
        trip = Trip(
            destination=destination,
            country=country_str,
            start_date=seg["start"],
            end_date=seg["end"],
            notes=f"Auto-detetada a partir de {len(seg['expenses'])} despesas",
        )
        db.add(trip)
        db.commit()
        db.refresh(trip)

        # Auto-suggest places
        suggestions = _get_suggestions(destination)
        for s in suggestions:
            place = TripPlace(trip_id=trip.id, suggested=True, **s)
            db.add(place)

        # Assign expenses
        for exp in seg["expenses"]:
            exp.trip_id = trip.id
            total_assigned += 1

        # Also grab transfer expenses within trip dates
        for texp in transfer_expenses:
            if seg["start"] <= texp.date <= seg["end"]:
                texp.trip_id = trip.id
                total_assigned += 1

        db.commit()

        # Calculate costs from ALL assigned expenses (including transfers)
        all_trip_expenses = db.query(Expense).filter(Expense.trip_id == trip.id).all()
        flights_cost = sum(e.amount for e in all_trip_expenses if any(
            kw in (e.description + " " + (e.notes or "")).lower()
            for kw in ["ryanair", "wizz", "tap", "easyjet", "vueling", "flight"]
        ))
        accommodation_cost = sum(e.amount for e in all_trip_expenses if any(
            kw in (e.description + " " + (e.notes or "")).lower()
            for kw in ["booking", "hotel", "hostel", "airbnb", "alojamento"]
        ))
        food_cost = sum(e.amount for e in all_trip_expenses if e.category in ("food", "groceries"))
        other_cost = sum(e.amount for e in all_trip_expenses) - flights_cost - accommodation_cost - food_cost

        trip.flights_cost = round(flights_cost, 2)
        trip.accommodation_cost = round(accommodation_cost, 2)
        trip.food_budget = round(food_cost, 2)
        trip.other_costs = round(max(0, other_cost), 2)
        db.commit()

        _fill_vacation_days(db, trip.start_date, trip.end_date, f"Viagem: {destination}")

        created_trips.append({
            "id": trip.id,
            "destination": destination,
            "country": country_str,
            "start_date": str(seg["start"]),
            "end_date": str(seg["end"]),
            "expenses_count": len(seg["expenses"]),
            "total": round(sum(e.amount for e in seg["expenses"]), 2),
        })

    return {
        "trips_created": len([t for t in created_trips if not t.get("existing")]),
        "expenses_assigned": total_assigned,
        "trips": created_trips,
    }
