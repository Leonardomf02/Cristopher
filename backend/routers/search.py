"""Pesquisa global: uma caixa que procura em tudo o que é texto na app.

Notas, notas de projecto, TODOs de código, reminders e eventos — cada resultado
já traz o sítio para onde a app deve navegar.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from database import get_db
from models import (
    Note, CodeProjectNote, CodeProjectTodo, ListItem, UserList, Event,
    DailyJournal, MoodEntry, Expense, Trip, DealResult, DealWatch,
)

router = APIRouter(prefix="/api/search", tags=["Search"])


def _snippet(text: str, term: str, size: int = 90) -> str:
    if not text:
        return ""
    low = text.lower()
    i = low.find(term.lower())
    if i < 0:
        return text[:size].strip()
    start = max(0, i - size // 3)
    out = text[start:start + size].strip().replace("\n", " ")
    return ("…" if start > 0 else "") + out + ("…" if start + size < len(text) else "")


@router.get("/")
def search(q: str = Query(..., min_length=2), limit: int = Query(8, ge=1, le=25), db: Session = Depends(get_db)):
    term = q.strip()
    like = f"%{term}%"
    results: list[dict] = []

    for n in (
        db.query(Note)
        .filter(or_(Note.title.ilike(like), Note.content.ilike(like)))
        .order_by(Note.updated_at.desc())
        .limit(limit)
        .all()
    ):
        results.append({
            "type": "nota",
            "icon": "📝",
            "title": n.title or "Sem título",
            "subtitle": _snippet(n.content or "", term),
            "url": f"/notes?note={n.id}",
        })

    for n in (
        db.query(CodeProjectNote)
        .filter(CodeProjectNote.content.ilike(like))
        .order_by(CodeProjectNote.created_at.desc())
        .limit(limit)
        .all()
    ):
        proj = (n.project_path or "").rstrip("/").split("/")[-1]
        results.append({
            "type": "nota de projecto",
            "icon": "✨" if n.source == "ai" else "💻",
            "title": _snippet(n.content or "", term, 70),
            "subtitle": f"{proj} · {(n.note_date or (n.created_at.date() if n.created_at else ''))}",
            "url": "/code",
        })

    for t in (
        db.query(CodeProjectTodo)
        .filter(CodeProjectTodo.content.ilike(like))
        .order_by(CodeProjectTodo.done.asc(), CodeProjectTodo.created_at.desc())
        .limit(limit)
        .all()
    ):
        proj = (t.project_path or "").rstrip("/").split("/")[-1]
        results.append({
            "type": "TODO de código",
            "icon": "✅" if t.done else "⬜",
            "title": t.content,
            "subtitle": f"{proj}{' · feita' if t.done else ''}",
            "url": "/code",
        })

    for item, lst in (
        db.query(ListItem, UserList)
        .join(UserList, ListItem.list_id == UserList.id)
        .filter(or_(ListItem.text.ilike(like), ListItem.notes.ilike(like)))
        .order_by(ListItem.checked.asc(), ListItem.id.desc())
        .limit(limit)
        .all()
    ):
        results.append({
            "type": "reminder",
            "icon": lst.icon or "🗒️",
            "title": item.text,
            "subtitle": f"{lst.name}{' · feito' if item.checked else ''}{(' · ' + str(item.due_date)) if item.due_date else ''}",
            "url": "/lists",
        })

    for e in (
        db.query(Event)
        .filter(or_(Event.title.ilike(like), Event.description.ilike(like)))
        .order_by(Event.date.desc())
        .limit(limit)
        .all()
    ):
        results.append({
            "type": "evento",
            "icon": "📅",
            "title": e.title,
            "subtitle": f"{e.date}{(' · ' + e.start_time) if e.start_time else ''}",
            "url": "/calendar",
        })

    # ── O que ele escreve e gasta ────────────────────────────────
    # O diário, as notas de humor e os gastos ficavam de fora: a app insistia
    # para escrever o diário e depois não havia maneira de o encontrar.

    for j in (
        db.query(DailyJournal)
        .filter(DailyJournal.content.ilike(like))
        .order_by(DailyJournal.date.desc())
        .limit(limit)
        .all()
    ):
        results.append({
            "type": "diário",
            "icon": "📔",
            "title": _snippet(j.content or "", term, 70),
            "subtitle": str(j.date),
            "url": f"/day/{j.date}",
        })

    for m in (
        db.query(MoodEntry)
        .filter(or_(MoodEntry.note.ilike(like), MoodEntry.tags.ilike(like)))
        .order_by(MoodEntry.date.desc())
        .limit(limit)
        .all()
    ):
        results.append({
            "type": "humor",
            "icon": "🙂",
            "title": _snippet(m.note or "", term, 70) or f"{m.mood}/10",
            "subtitle": f"{m.date} · {m.mood}/10",
            "url": f"/day/{m.date}",
        })

    for e in (
        db.query(Expense)
        .filter(or_(Expense.description.ilike(like), Expense.notes.ilike(like),
                    Expense.merchant_city.ilike(like)))
        .order_by(Expense.date.desc())
        .limit(limit)
        .all()
    ):
        results.append({
            "type": "gasto",
            "icon": "💸",
            "title": f"{e.description} · {e.amount:.2f}€",
            "subtitle": f"{e.date}{(' · ' + e.merchant_city) if e.merchant_city else ''}{(' · ' + e.category) if e.category else ''}",
            "url": f"/day/{e.date}",
        })

    for t in (
        db.query(Trip)
        .filter(or_(Trip.destination.ilike(like), Trip.country.ilike(like), Trip.notes.ilike(like)))
        .order_by(Trip.start_date.desc())
        .limit(limit)
        .all()
    ):
        results.append({
            "type": "viagem",
            "icon": "✈️",
            "title": t.destination,
            "subtitle": f"{t.start_date} → {t.end_date}",
            "url": f"/trips/{t.id}",
        })

    for r, w in (
        db.query(DealResult, DealWatch)
        .join(DealWatch, DealWatch.id == DealResult.watch_id)
        .filter(DealResult.title.ilike(like), DealResult.status != "gone")
        .order_by(DealResult.ai_rating.desc().nullslast())
        .limit(limit)
        .all()
    ):
        preco = f"{r.price:.0f}€" if r.price else "?"
        results.append({
            "type": "deal",
            "icon": "🏷️",
            "title": f"{r.title[:60]} · {preco}",
            "subtitle": f"{w.title}{(' · ' + str(r.ai_rating) + '/100') if r.ai_rating else ''}",
            "url": "/deals",
        })

    return {"query": term, "count": len(results), "results": results}
