"""Um dia inteiro numa linha do tempo.

A app tinha os dados todos espalhados por ecrãs (sono num sítio, plano noutro,
apps noutro, gastos noutro) e não havia forma de ver um dia do princípio ao fim.
Isto junta tudo o que aconteceu num dia, em blocos ordenados pela hora.
"""
from __future__ import annotations

import json
from datetime import date as _date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

import expense_kind as ek
from database import get_db
from models import (
    AppUsageSession, DayPlanRecord, Expense, LolGame, MoodEntry, DailyJournal,
    SleepEntry, WakaProjectDay, CodeProjectNote, Event, ListItem, Trip, SpotifyPlay,
)

router = APIRouter(prefix="/api/day", tags=["Dia"])

# Sessões mais curtas do que isto não viram bloco próprio: seriam centenas de
# linhas de 20 segundos a esconder o que interessa.
MIN_BLOCO_SEG = 180
JUNTA_SE_ATE_SEG = 300      # troca rápida de janela e volta → continua o mesmo bloco


def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _blocos_de_ecra(db: Session, dia: _date) -> list[dict]:
    """Agrupa as sessões de apps em blocos legíveis (por categoria e app)."""
    from routers.app_usage import _resolve_category

    sessoes = (
        db.query(AppUsageSession)
        .filter(AppUsageSession.date == dia)
        .order_by(AppUsageSession.start_time)
        .all()
    )
    sessoes = [s for s in sessoes if s.start_time and s.end_time]
    if not sessoes:
        return []

    blocos: list[dict] = []
    for s in sessoes:
        cat = _resolve_category(db, s)
        anterior = blocos[-1] if blocos else None
        mesma_coisa = (
            anterior
            and anterior["app"] == s.app_name
            and anterior["category"] == cat
            and (s.start_time - anterior["_fim"]).total_seconds() <= JUNTA_SE_ATE_SEG
        )
        if mesma_coisa:
            anterior["_fim"] = max(anterior["_fim"], s.end_time)
            anterior["seconds"] += s.duration_seconds or 0
            titulo = (s.window_title or "").strip()
            if titulo and titulo not in anterior["titles"]:
                anterior["titles"].append(titulo)
        else:
            blocos.append({
                "app": s.app_name,
                "bundle_id": s.bundle_id,
                "category": cat,
                "_ini": s.start_time,
                "_fim": s.end_time,
                "seconds": s.duration_seconds or 0,
                "titles": [(s.window_title or "").strip()] if (s.window_title or "").strip() else [],
            })

    saida = []
    for b in blocos:
        if b["seconds"] < MIN_BLOCO_SEG:
            continue
        saida.append({
            "kind": "screen",
            "start": _hhmm(b["_ini"]),
            "end": _hhmm(b["_fim"]),
            "start_ts": b["_ini"].isoformat(),
            "app": b["app"],
            "category": b["category"],
            "seconds": b["seconds"],
            "titles": b["titles"][:4],
        })
    return saida


@router.get("/{dia}")
def resumo_do_dia(dia: str, db: Session = Depends(get_db)):
    d = _date.fromisoformat(dia)
    ontem = d - timedelta(days=1)

    sono = db.query(SleepEntry).filter(SleepEntry.date == d).order_by(SleepEntry.id.desc()).first()
    humor = db.query(MoodEntry).filter(MoodEntry.date == d).first()
    diario = db.query(DailyJournal).filter(DailyJournal.date == d).first()
    viagem = db.query(Trip).filter(Trip.start_date <= d, Trip.end_date >= d).first()

    codigo = (
        db.query(WakaProjectDay)
        .filter(WakaProjectDay.day == d, WakaProjectDay.kind == "project")
        .order_by(WakaProjectDay.seconds.desc())
        .all()
    )
    jogos = db.query(LolGame).filter(LolGame.date == d).order_by(LolGame.game_hour).all()
    gastos = db.query(Expense).filter(Expense.date == d, Expense.kind == ek.GASTO).all()
    notas = db.query(CodeProjectNote).filter(CodeProjectNote.note_date == d).all()
    eventos = db.query(Event).filter(Event.date == d).order_by(Event.start_time).all()
    tarefas = db.query(ListItem).filter(ListItem.due_date == d).all()
    musica = (
        db.query(SpotifyPlay)
        .filter(SpotifyPlay.date == d, SpotifyPlay.seconds >= 20)
        .order_by(SpotifyPlay.started_at)
        .all()
    )

    plano = db.query(DayPlanRecord).filter(DayPlanRecord.plan_date == d).first()
    blocos_plano = json.loads(plano.blocks_json or "[]") if plano else []

    linha: list[dict] = []

    if sono and sono.bedtime and sono.wake_time:
        linha.append({
            "kind": "sleep", "start": sono.wake_time[:5], "end": sono.wake_time[:5],
            "text": f"Acordou às {sono.wake_time[:5]}",
            "detail": f"{round(sono.hours, 1)}h desde as {sono.bedtime[:5]}" if sono.hours else None,
        })

    for b in blocos_plano:
        if b.get("name") == "Tempo livre":
            continue
        linha.append({
            "kind": "plan", "start": b["start"], "end": b["end"],
            "text": f"{b.get('icon', '')} {b['name']}".strip(),
            "detail": b.get("note") or None,
            "done": bool(b.get("done")),
        })

    linha.extend(_blocos_de_ecra(db, d))

    for g in jogos:
        hora = f"{(g.game_hour or 0):02d}:00"
        linha.append({
            "kind": "game", "start": hora, "end": hora,
            "text": f"{'Vitória' if g.won else 'Derrota'} com {g.champion_played}",
            "detail": f"{g.kills}/{g.deaths}/{g.assists}" + (f" · {round((g.game_duration or 0) / 60)}min" if g.game_duration else ""),
            "won": bool(g.won),
        })

    for e in gastos:
        hora = (e.time_of_day or "")[:5]
        linha.append({
            "kind": "expense", "start": hora or "23:59", "end": hora or "23:59",
            "text": f"{e.description}",
            "detail": f"{e.amount:.2f}€" + (f" · {e.category}" if e.category else ""),
            "no_time": not hora,
        })

    for ev in eventos:
        linha.append({
            "kind": "event", "start": (ev.start_time or "00:00")[:5], "end": (ev.end_time or "")[:5],
            "text": ev.title, "detail": ev.category or None, "done": bool(ev.completed),
        })

    for t in tarefas:
        linha.append({
            "kind": "task", "start": "23:59", "end": "23:59",
            "text": t.text, "detail": None, "done": bool(t.checked),
        })

    # música: agrupada por sessão de escuta (buracos de mais de 10min separam)
    sessao_musica: list[dict] = []
    for p in musica:
        anterior = sessao_musica[-1] if sessao_musica else None
        if anterior and (p.started_at - anterior["_fim"]).total_seconds() <= 600:
            anterior["_fim"] = p.ended_at or p.started_at
            anterior["seconds"] += p.seconds or 0
            anterior["tracks"].append(f"{p.track} · {p.artist}")
        else:
            sessao_musica.append({
                "_ini": p.started_at, "_fim": p.ended_at or p.started_at,
                "seconds": p.seconds or 0, "tracks": [f"{p.track} · {p.artist}"],
            })
    for m in sessao_musica:
        if m["seconds"] < 300:
            continue
        linha.append({
            "kind": "music", "start": _hhmm(m["_ini"]), "end": _hhmm(m["_fim"]),
            "text": f"{len(m['tracks'])} músicas",
            "detail": ", ".join(m["tracks"][:3]) + ("…" if len(m["tracks"]) > 3 else ""),
            "seconds": m["seconds"],
        })

    linha.sort(key=lambda x: (x.get("start") or "00:00", x["kind"]))

    total_ecra = sum(b["seconds"] for b in linha if b["kind"] == "screen")
    return {
        "date": d.isoformat(),
        "prev": ontem.isoformat(),
        "next": (d + timedelta(days=1)).isoformat(),
        "timeline": linha,
        "summary": {
            "sleep_hours": round(sono.hours, 2) if sono and sono.hours else None,
            "bedtime": sono.bedtime[:5] if sono and sono.bedtime else None,
            "wake_time": sono.wake_time[:5] if sono and sono.wake_time else None,
            "code_seconds": sum(c.seconds for c in codigo),
            "top_projects": [{"name": c.project, "seconds": c.seconds} for c in codigo[:3]],
            "screen_seconds": total_ecra,
            "games": len(jogos),
            "wins": sum(1 for g in jogos if g.won),
            "spent": round(sum(e.amount for e in gastos if e.amount > 0), 2),
            "notes": len(notas),
            "music_seconds": sum(p.seconds or 0 for p in musica),
            "mood": humor.mood if humor else None,
            "mood_note": humor.note if humor else None,
            "journal": diario.content if diario else None,
            "trip": viagem.destination if viagem else None,
            "plan_blocks": len([b for b in blocos_plano if b.get("name") != "Tempo livre"]),
        },
    }
