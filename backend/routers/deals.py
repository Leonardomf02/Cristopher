"""Deals — caça-deals automático.

Crias 'watches' (ex: 'Yamaha MT-07') e de hora a hora as fontes (Vinted, OLX)
são pesquisadas; a IA iaedu.pt avalia cada anúncio 0-100 e marca se é mesmo o
item pedido (desambiguação de descrições). Notificação = painel na app."""

import logging
import re
import threading
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from models import DealWatch, DealResult
import deals_sources as ds
from deals_sources import vinted as vinted_source
import deals_ai

router = APIRouter(prefix="/api/deals", tags=["Deals"])
logger = logging.getLogger(__name__)

_MAX_VINTED_DETAILS = 15   # nº máx de fetches de descrição Vinted por run (controla 403/volume)
_SEARCH_LIMIT = 25         # candidatos por fonte por run (menos = menos chamadas de IA / quota)
_RERATE_CHUNK = 40         # re-avalia o backlog de pendentes em lotes deste tamanho (commit por lote)

# Controlo de concorrência: um watch só corre 1 scan de cada vez (evita o scheduler
# e o "procurar agora" colidirem no mesmo watch → duplicados/IntegrityError).
_run_lock = threading.Lock()
_running: set[int] = set()


def _try_start(watch_id: int) -> bool:
    with _run_lock:
        if watch_id in _running:
            return False
        _running.add(watch_id)
        return True


def _finish(watch_id: int) -> None:
    with _run_lock:
        _running.discard(watch_id)


def is_scanning(watch_id: int) -> bool:
    with _run_lock:
        return watch_id in _running


# ── Schemas ──────────────────────────────────────────────────────

class DealWatchIn(BaseModel):
    title: str
    query: str
    category: str = ""
    condition: str = "any"           # any | new | used
    sources: str = "all"             # all | vinted | csv
    max_price: Optional[float] = None
    min_rating: int = 60
    ai_context: str = ""
    exclude_keywords: str = ""
    active: bool = True


class DealWatchUpdate(BaseModel):
    title: Optional[str] = None
    query: Optional[str] = None
    category: Optional[str] = None
    condition: Optional[str] = None
    sources: Optional[str] = None
    max_price: Optional[float] = None
    min_rating: Optional[int] = None
    ai_context: Optional[str] = None
    exclude_keywords: Optional[str] = None
    active: Optional[bool] = None


class DealWatchOut(BaseModel):
    id: int
    title: str
    query: str
    category: str
    condition: str
    sources: str
    max_price: Optional[float]
    min_rating: int
    ai_context: str
    exclude_keywords: str
    active: bool
    last_checked_at: Optional[datetime]
    new_count: int = 0          # nº de deals bons por ver
    total_count: int = 0        # nº de matches reais (match=true E já avaliados pela IA)
    pending_count: int = 0      # nº de anúncios ainda por avaliar (sem rating)
    scanning: bool = False      # True enquanto um scan está a correr

    class Config:
        from_attributes = True


class DealResultOut(BaseModel):
    id: int
    watch_id: int
    source: str
    title: str
    description: str
    price: Optional[float]
    currency: str
    condition: str
    url: str
    image_url: str
    location: str
    seller: str
    ai_rating: Optional[int]
    ai_match: bool
    ai_reason: str
    status: str
    first_seen_at: Optional[datetime]
    last_seen_at: Optional[datetime]

    class Config:
        from_attributes = True


class ResultPatch(BaseModel):
    status: str   # seen | saved | dismissed | new


# ── Helpers ──────────────────────────────────────────────────────

def _watch_to_out(db: Session, w: DealWatch) -> DealWatchOut:
    out = DealWatchOut.model_validate(w)
    out.new_count = (
        db.query(DealResult)
        .filter(
            DealResult.watch_id == w.id,
            DealResult.status == "new",
            DealResult.ai_match == True,  # noqa: E712
            DealResult.ai_rating >= w.min_rating,
        )
        .count()
    )
    out.total_count = (
        db.query(DealResult)
        .filter(
            DealResult.watch_id == w.id,
            DealResult.ai_match == True,  # noqa: E712
            DealResult.ai_rating.isnot(None),   # pendentes (ainda sem rating) NÃO contam como match
        )
        .count()
    )
    out.pending_count = (
        db.query(DealResult)
        .filter(DealResult.watch_id == w.id, DealResult.ai_rating.is_(None))
        .count()
    )
    out.scanning = is_scanning(w.id)
    return out


def _excluded(title: str, exclude_keywords: str) -> bool:
    words = [w.strip().lower() for w in (exclude_keywords or "").split(",") if w.strip()]
    t = (title or "").lower()
    return any(w in t for w in words)


def _relevant(title: str, description: str, query: str) -> bool:
    """Pré-filtro barato (sem IA): pelo menos um token significativo (≥3 letras) da
    query tem de aparecer no título/descrição. Corta lixo cross-categoria (ex: um
    Samsung que a pesquisa solta da Vinted devolveu para 'iphone 17') antes de
    gastar chamadas de IA e antes de gravar. Se a query não tiver tokens ≥3, deixa passar."""
    toks = [t for t in re.split(r"\W+", (query or "").lower()) if len(t) >= 3]
    if not toks:
        return True
    hay = f"{title} {description}".lower()
    return any(t in hay for t in toks)


def _watch_dict(watch: DealWatch) -> dict:
    return {
        "id": watch.id, "title": watch.title, "query": watch.query,
        "category": watch.category, "condition": watch.condition,
        "max_price": watch.max_price, "ai_context": watch.ai_context,
        "exclude_keywords": watch.exclude_keywords,
    }


def _rerate_backlog(watch: DealWatch, watch_dict: dict, db: Session) -> int:
    """Re-avalia TODO o backlog deste watch sem rating (deste run + de runs antigos
    com rate limit), em lotes, commitando cada um — o backlog esvazia mesmo quando é
    grande e o frontend vê o progresso no poll. Pára se um lote não recuperar nada
    (IA mesmo em rate limit): evita loop infinito e poupa quota. Devolve nº avaliados."""
    total = 0
    while True:
        batch = (
            db.query(DealResult)
            .filter(DealResult.watch_id == watch.id, DealResult.ai_rating.is_(None))
            .limit(_RERATE_CHUNK)
            .all()
        )
        if not batch:
            break
        rated = 0
        for row, rate in zip(batch, deals_ai.rate_listings(watch_dict, batch)):
            if rate["rating"] is not None:
                row.ai_rating = rate["rating"]
                row.ai_match = rate["match"]
                row.ai_reason = rate["reason"]
                rated += 1
        db.commit()
        total += rated
        if rated == 0:   # IA não devolveu nada (rate limit real) → não insistir
            break
    return total


def run_watch(watch: DealWatch, db: Session) -> int:
    """Pesquisa as fontes, dedupe, busca descrições novas, avalia com IA e grava.
    Devolve o nº de deals bons novos (match & rating>=min_rating)."""
    listings = ds.search_all(
        watch.query,
        watch.sources,
        max_price=watch.max_price,
        condition=watch.condition,
        limit=_SEARCH_LIMIT,
    )

    # dedupe vs existentes deste watch
    existing = {
        (r.source, r.external_id): r
        for r in db.query(DealResult).filter(DealResult.watch_id == watch.id).all()
    }

    new_listings = []
    seen_new: set = set()
    for lst in listings:
        if _excluded(lst.title, watch.exclude_keywords):
            continue
        if not _relevant(lst.title, lst.description, watch.query):
            continue
        key = (lst.source, lst.external_id)
        if key in existing:
            row = existing[key]
            row.last_seen_at = datetime.utcnow()
            if lst.price is not None:
                row.price = lst.price
            continue
        if key in seen_new:   # mesma fonte pode devolver o mesmo item 2x no mesmo run
            continue
        seen_new.add(key)
        new_listings.append(lst)

    # descrições Vinted só para os novos (cap p/ limitar 403/volume); acrescenta à
    # hint de modelo (item_box) — o detalhe dá 403 com frequência (Datadome), por
    # isso é best-effort e a hint da pesquisa garante sempre algo para a IA avaliar.
    fetched = 0
    for lst in new_listings:
        if lst.source == "vinted" and fetched < _MAX_VINTED_DETAILS:
            detail = vinted_source.fetch_description(lst.external_id)
            if detail:
                lst.description = (lst.description + "\n" + detail).strip() if lst.description else detail
            fetched += 1

    watch_dict = _watch_dict(watch)

    # avaliação IA dos novos
    ratings = deals_ai.rate_listings(watch_dict, new_listings)

    good_new = 0
    for lst, rate in zip(new_listings, ratings):
        row = DealResult(
            watch_id=watch.id,
            source=lst.source,
            external_id=lst.external_id,
            title=lst.title,
            description=lst.description or "",
            price=lst.price,
            currency=lst.currency,
            condition=lst.condition,
            url=lst.url,
            image_url=lst.image_url,
            location=lst.location,
            seller=lst.seller,
            ai_rating=rate["rating"],
            ai_match=rate["match"],
            ai_reason=rate["reason"],
            status="new",
        )
        db.add(row)
        if rate["match"] and rate["rating"] is not None and rate["rating"] >= watch.min_rating:
            good_new += 1
    db.commit()

    # esvazia o backlog: avalia TUDO o que ficou sem rating (novos que a IA falhou +
    # pendentes de runs anteriores com rate limit). Antes só re-avaliava 40/run e o
    # backlog crescia mais depressa do que esvaziava → ficava tudo "por avaliar".
    _rerate_backlog(watch, watch_dict, db)

    watch.last_checked_at = datetime.utcnow()
    db.commit()
    return good_new


def _scan_now(watch_id: int) -> int:
    """Scan síncrono de 1 watch, em sessão própria. Assume o lock já adquirido."""
    db = SessionLocal()
    try:
        w = db.get(DealWatch, watch_id)
        return run_watch(w, db) if w else 0
    finally:
        db.close()


def start_scan(watch_id: int) -> bool:
    """Arranca um scan em background (thread). Devolve False se já estava a correr."""
    if not _try_start(watch_id):
        return False

    def _job():
        try:
            _scan_now(watch_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("scan %s falhou: %s", watch_id, e)
        finally:
            _finish(watch_id)

    threading.Thread(target=_job, daemon=True).start()
    return True


def run_all_watches() -> int:
    """Corre todos os watches activos (sequencial). Usado pelo scheduler.
    Respeita o lock por watch: se houver um scan manual a correr, salta esse desta vez."""
    db = SessionLocal()
    try:
        ids = [w.id for w in db.query(DealWatch).filter(DealWatch.active == True).all()]  # noqa: E712
    finally:
        db.close()
    total = 0
    for wid in ids:
        if not _try_start(wid):
            continue
        try:
            total += _scan_now(wid)
        except Exception as e:  # noqa: BLE001 — um watch não pode derrubar o scan
            logger.warning("scan %s falhou: %s", wid, e)
        finally:
            _finish(wid)
    return total


# ── Watches CRUD ─────────────────────────────────────────────────

@router.get("/watches", response_model=list[DealWatchOut])
def list_watches(db: Session = Depends(get_db)):
    watches = db.query(DealWatch).order_by(DealWatch.created_at.desc()).all()
    return [_watch_to_out(db, w) for w in watches]


@router.post("/watches", response_model=DealWatchOut)
def create_watch(data: DealWatchIn, db: Session = Depends(get_db)):
    w = DealWatch(**data.model_dump())
    db.add(w)
    db.commit()
    db.refresh(w)
    if w.active:
        start_scan(w.id)   # 1ª pesquisa arranca já em background
    return _watch_to_out(db, w)


@router.patch("/watches/{watch_id}", response_model=DealWatchOut)
def update_watch(watch_id: int, data: DealWatchUpdate, db: Session = Depends(get_db)):
    w = db.query(DealWatch).filter(DealWatch.id == watch_id).first()
    if not w:
        raise HTTPException(status_code=404, detail="Watch não encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(w, k, v)
    db.commit()
    db.refresh(w)
    return _watch_to_out(db, w)


@router.delete("/watches/{watch_id}")
def delete_watch(watch_id: int, db: Session = Depends(get_db)):
    w = db.query(DealWatch).filter(DealWatch.id == watch_id).first()
    if not w:
        raise HTTPException(status_code=404, detail="Watch não encontrado")
    db.query(DealResult).filter(DealResult.watch_id == watch_id).delete()
    db.delete(w)
    db.commit()
    return {"ok": True}


@router.post("/watches/{watch_id}/run", response_model=DealWatchOut)
def run_now(watch_id: int, db: Session = Depends(get_db)):
    """Arranca um scan em background e devolve já (scanning=True). O frontend faz
    poll até `scanning` ficar False. Não bloqueia ~min à espera da IA + fontes."""
    w = db.query(DealWatch).filter(DealWatch.id == watch_id).first()
    if not w:
        raise HTTPException(status_code=404, detail="Watch não encontrado")
    start_scan(watch_id)   # no-op se já estiver a correr
    return _watch_to_out(db, w)


# ── Results ──────────────────────────────────────────────────────

@router.get("/results", response_model=list[DealResultOut])
def list_results(
    watch_id: int = Query(...),
    status: Optional[str] = Query(None),     # new | seen | saved | dismissed
    include_unmatched: bool = Query(False),
    db: Session = Depends(get_db),
):
    q = db.query(DealResult).filter(DealResult.watch_id == watch_id)
    if not include_unmatched:
        q = q.filter(DealResult.ai_match == True)  # noqa: E712
    if status:
        q = q.filter(DealResult.status == status)
    # melhores primeiro: match, depois rating desc, depois mais recentes
    rows = q.all()
    rows.sort(key=lambda r: (
        r.ai_match,
        r.ai_rating if r.ai_rating is not None else -1,
        r.first_seen_at or datetime.min,
    ), reverse=True)
    return rows


@router.patch("/results/{result_id}", response_model=DealResultOut)
def patch_result(result_id: int, data: ResultPatch, db: Session = Depends(get_db)):
    r = db.query(DealResult).filter(DealResult.id == result_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Resultado não encontrado")
    if data.status not in ("new", "seen", "saved", "dismissed"):
        raise HTTPException(status_code=400, detail="status inválido")
    r.status = data.status
    db.commit()
    db.refresh(r)
    return r


@router.post("/results/mark-seen")
def mark_all_seen(watch_id: int = Query(...), db: Session = Depends(get_db)):
    db.query(DealResult).filter(
        DealResult.watch_id == watch_id, DealResult.status == "new"
    ).update({DealResult.status: "seen"})
    db.commit()
    return {"ok": True}


# ── Summary (badge do nav) ───────────────────────────────────────

@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    watches = db.query(DealWatch).filter(DealWatch.active == True).all()  # noqa: E712
    total_new = 0
    for w in watches:
        total_new += (
            db.query(DealResult)
            .filter(
                DealResult.watch_id == w.id,
                DealResult.status == "new",
                DealResult.ai_match == True,  # noqa: E712
                DealResult.ai_rating >= w.min_rating,
            )
            .count()
        )
    from ai_config import ai_status
    return {"new_count": total_new, "watch_count": len(watches), "ai": ai_status()}


@router.post("/ai-check")
def ai_check():
    """Sonda a IA agora (1 chamada) e devolve o estado. Para o botão 'Verificar agora'
    e o auto-probe do frontend saberem quando a IA recuperou do rate limit."""
    from ai_config import ping, ai_status
    ping()
    return ai_status()
