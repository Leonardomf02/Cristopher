from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, datetime, timedelta
from typing import Optional

from pydantic import BaseModel

from database import get_db
from models import (
    MoodEntry, DailyJournal, DayQuestion, SleepEntry, Expense, ListItem, Event,
    WakaProjectDay, LolGame, Trip, CodeProjectNote,
)
import expense_kind as ek
import screen_source
from schemas import MoodCreate, MoodOut, JournalCreate, JournalOut

router = APIRouter(prefix="/api/mood", tags=["Mood & Journal"])


# ── Mood CRUD ────────────────────────────────────────────────────

@router.get("/", response_model=list[MoodOut])
def list_moods(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(MoodEntry)
    if start_date:
        q = q.filter(MoodEntry.date >= start_date)
    if end_date:
        q = q.filter(MoodEntry.date <= end_date)
    return q.order_by(MoodEntry.date.desc()).all()


@router.post("/", response_model=MoodOut)
def create_or_update_mood(data: MoodCreate, db: Session = Depends(get_db)):
    if data.mood < 0 or data.mood > 10:
        raise HTTPException(400, "Rating must be between 0 and 10")
    existing = db.query(MoodEntry).filter(MoodEntry.date == data.date).first()
    if existing:
        existing.mood = data.mood
        existing.quality = data.quality
        existing.note = data.note
        existing.tags = data.tags
        db.commit()
        db.refresh(existing)
        return existing
    entry = MoodEntry(**data.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}")
def delete_mood(entry_id: int, db: Session = Depends(get_db)):
    entry = db.query(MoodEntry).filter(MoodEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Mood entry not found")
    db.delete(entry)
    db.commit()
    return {"ok": True}


@router.get("/today")
def mood_today(db: Session = Depends(get_db)):
    """Get today's mood and journal in one call."""
    today = date.today()
    mood = db.query(MoodEntry).filter(MoodEntry.date == today).first()
    journal = db.query(DailyJournal).filter(DailyJournal.date == today).first()
    return {
        "mood": MoodOut.model_validate(mood).model_dump() if mood else None,
        "journal": JournalOut.model_validate(journal).model_dump() if journal else None,
    }


# ── Journal CRUD ─────────────────────────────────────────────────

@router.get("/journal", response_model=list[JournalOut])
def list_journals(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(DailyJournal)
    if start_date:
        q = q.filter(DailyJournal.date >= start_date)
    if end_date:
        q = q.filter(DailyJournal.date <= end_date)
    return q.order_by(DailyJournal.date.desc()).all()


@router.post("/journal", response_model=JournalOut)
def create_or_update_journal(data: JournalCreate, db: Session = Depends(get_db)):
    existing = db.query(DailyJournal).filter(DailyJournal.date == data.date).first()
    if existing:
        existing.content = data.content
        db.commit()
        db.refresh(existing)
        return existing
    entry = DailyJournal(**data.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/journal/{entry_id}")
def delete_journal(entry_id: int, db: Session = Depends(get_db)):
    entry = db.query(DailyJournal).filter(DailyJournal.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Journal entry not found")
    db.delete(entry)
    db.commit()
    return {"ok": True}


# ── Factos do dia (para o diário não começar em branco) ──────────

@router.get("/day-facts")
def day_facts(day: Optional[date] = Query(None), db: Session = Depends(get_db)):
    """O que a app já sabe sobre o dia: sono, código, ecrã, gastos, tarefas, jogos.
    Serve para o diário sugerir por onde começar em vez de uma caixa vazia."""
    d = day or date.today()
    facts: list[dict] = []

    sleep = db.query(SleepEntry).filter(SleepEntry.date == d).order_by(SleepEntry.id.desc()).first()
    if sleep and sleep.hours:
        facts.append({"key": "sono", "icon": "🌙", "label": f"{round(sleep.hours, 1)}h de sono"})

    code_seconds = (
        db.query(func.coalesce(func.sum(WakaProjectDay.seconds), 0))
        .filter(WakaProjectDay.day == d, WakaProjectDay.kind == "project")
        .scalar()
    ) or 0
    if code_seconds >= 300:
        facts.append({"key": "codigo", "icon": "💻", "label": f"{_hm(code_seconds)} de código"})

    screen_seconds = (
        screen_source.por_dia(db, d, d).get(d, 0)
    ) or 0
    if screen_seconds >= 600:
        facts.append({"key": "ecra", "icon": "📱", "label": f"{_hm(screen_seconds)} de ecrã"})

    expenses = db.query(Expense).filter(Expense.date == d, Expense.kind == ek.GASTO).all()
    gasto = round(sum(e.amount for e in expenses if e.amount > 0), 2)
    if expenses:
        facts.append({"key": "gastos", "icon": "💸", "label": f"{gasto:.2f}€ em {len(expenses)} transaç{'ões' if len(expenses) != 1 else 'ão'}"})

    feitas = db.query(ListItem).filter(ListItem.due_date == d, ListItem.checked == True).count()
    eventos = db.query(Event).filter(Event.date == d, Event.completed == True).count()
    if feitas + eventos:
        facts.append({"key": "tarefas", "icon": "✅", "label": f"{feitas + eventos} tarefa{'s' if feitas + eventos != 1 else ''} feita{'s' if feitas + eventos != 1 else ''}"})

    games = db.query(LolGame).filter(LolGame.date == d).all()
    if games:
        wins = sum(1 for g in games if g.won)
        facts.append({"key": "lol", "icon": "🎮", "label": f"{len(games)} games ({wins}W-{len(games) - wins}L)"})

    prompt = ""
    if facts:
        prompt = "Hoje: " + ", ".join(f["label"] for f in facts) + ".\n\n"
    return {"date": str(d), "facts": facts, "prompt": prompt}


def _hm(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m // 60}h{m % 60:02d}" if m >= 60 else f"{m}min"


# Perguntas do dia: em vez de uma caixa vazia, a app pergunta sobre o que
# realmente aconteceu naquele dia. Só entram perguntas com base em dados.
def _perguntas_do_dia(db: Session, d: date) -> list[dict]:
    out: list[dict] = []

    sono = db.query(SleepEntry).filter(SleepEntry.date == d).order_by(SleepEntry.id.desc()).first()
    if sono and sono.hours:
        h = round(sono.hours, 1)
        if h < 6:
            out.append({"key": "sono-pouco", "icon": "🌙", "question": f"Dormiste só {h}h — o que te tirou o sono?"})
        elif h >= 9:
            out.append({"key": "sono-muito", "icon": "🌙", "question": f"{h}h de sono — foi recuperação ou preguiça?"})

    codigo = (
        db.query(func.coalesce(func.sum(WakaProjectDay.seconds), 0))
        .filter(WakaProjectDay.day == d, WakaProjectDay.kind == "project")
        .scalar()
    ) or 0
    top = (
        db.query(WakaProjectDay.project)
        .filter(WakaProjectDay.day == d, WakaProjectDay.kind == "project")
        .order_by(WakaProjectDay.seconds.desc()).first()
    )
    if codigo >= 3600 * 3 and top:
        out.append({"key": "codigo-muito", "icon": "💻", "question": f"{_hm(codigo)} no {top[0]} — o que ficou pronto?"})
    elif codigo >= 300 and top:
        out.append({"key": "codigo", "icon": "💻", "question": f"No {top[0]}, onde é que ficaste preso?"})
    elif codigo == 0:
        out.append({"key": "codigo-zero", "icon": "💻", "question": "Dia sem código — foi por escolha ou fugiu o tempo?"})

    gastos = db.query(Expense).filter(Expense.date == d, Expense.kind == ek.GASTO).all()
    if gastos:
        maior = max(gastos, key=lambda e: e.amount)
        if maior.amount >= 30:
            out.append({
                "key": "gasto-grande", "icon": "💸",
                "question": f"{maior.amount:.2f}€ em {maior.description} — valeu?",
            })

    jogos = db.query(LolGame).filter(LolGame.date == d).all()
    if jogos:
        vitorias = sum(1 for g in jogos if g.won)
        derrotas = len(jogos) - vitorias
        if derrotas >= 3 and derrotas > vitorias:
            out.append({"key": "lol-mal", "icon": "🎮", "question": f"{derrotas} derrotas — porque é que continuaste a jogar?"})
        elif len(jogos) >= 4:
            out.append({"key": "lol-muitos", "icon": "🎮", "question": f"{len(jogos)} games — o que ias fazer nesse tempo?"})

    ecra = (
        screen_source.por_dia(db, d, d).get(d, 0)
    ) or 0
    if ecra >= 3600 * 8:
        out.append({"key": "ecra-muito", "icon": "📱", "question": f"{_hm(ecra)} de ecrã — em que é que se foi o dia?"})

    feitas = db.query(ListItem).filter(ListItem.due_date == d, ListItem.checked == True).count()  # noqa: E712
    abertas = db.query(ListItem).filter(ListItem.due_date == d, ListItem.checked == False).count()  # noqa: E712
    if abertas and not feitas:
        out.append({"key": "tarefas-zero", "icon": "✅", "question": f"{abertas} tarefas ficaram por fazer — o que atrapalhou?"})
    elif feitas >= 3:
        out.append({"key": "tarefas-boas", "icon": "✅", "question": f"{feitas} tarefas fechadas — o que ajudou a ir tão bem?"})

    viagem = db.query(Trip).filter(Trip.start_date <= d, Trip.end_date >= d).first()
    if viagem:
        out.append({"key": "viagem", "icon": "✈️", "question": f"Em {viagem.destination}: o melhor momento do dia?"})

    humor = db.query(MoodEntry).filter(MoodEntry.date == d).first()
    if humor and humor.mood is not None:
        if humor.mood <= 5:
            out.append({"key": "humor-baixo", "icon": "🙂", "question": f"Deste {humor.mood}/10 ao dia — o que faria disto um 8?"})
        elif humor.mood >= 9:
            out.append({"key": "humor-alto", "icon": "🙂", "question": f"{humor.mood}/10 — o que é que correu tão bem?"})

    # Fecho universal, para nunca ficar sem nada.
    out.append({"key": "amanha", "icon": "➡️", "question": "Uma coisa que queres fazer diferente amanhã?"})
    return out[:5]


@router.get("/journal-prompts")
def journal_prompts(day: Optional[date] = Query(None), db: Session = Depends(get_db)):
    d = day or date.today()
    return {"date": str(d), "prompts": _perguntas_do_dia(db, d)}


# ── A app pergunta-te (dias fora do padrão) ───────────────────────
# As perguntas acima são sobre HOJE e vivem dentro do diário. Estas são sobre os
# dias que fugiram ao padrão dele nas últimas semanas — que são os dias em que o
# "porquê" vale mesmo a pena e onde se perde primeiro. A resposta é curta e vai
# para o diário desse dia.

DIA_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]

# Como se pergunta por cada tipo de coisa fora do padrão. `{texto}` é a frase que
# o motor de anomalias já escreve (com os números dele lá dentro).
_MOLDES = {
    "gasto-dia": "{quando} foi um dia caro ({texto}) — em quê?",
    "gasto-sitio": "{quando}: {texto} O que é que levaste?",
    "sono": "{quando} dormiste fora do costume ({texto}) — o que aconteceu?",
    "deitar": "{quando} {texto} Porquê?",
    "ecra": "{quando} foram {texto} — em que é que se foi o dia?",
    "jogos": "{quando} jogaste muito mais que o costume ({texto}) — o que estava a acontecer?",
    "codigo": "{quando} foi um dia forte de código ({texto}) — o que é que destravou?",
}


def _quando(d: date, hoje: date) -> str:
    dias = (hoje - d).days
    if dias == 0:
        return "Hoje"
    if dias == 1:
        return "Ontem"
    if dias < 7:
        return DIA_SEMANA[d.weekday()].capitalize()
    return f"{d.day}/{d.month}"


def _pergunta_da_anomalia(a: dict, hoje: date) -> Optional[str]:
    molde = _MOLDES.get(str(a.get("key", "")).split(":")[0])
    if not molde:
        return None
    try:
        d = date.fromisoformat(a["date"])
    except (KeyError, ValueError):
        return None
    return molde.format(quando=_quando(d, hoje), texto=str(a.get("text", "")).strip())


@router.get("/questions")
def perguntas_por_responder(
    days: int = Query(14, ge=1, le=60),
    limit: int = Query(4, ge=1, le=12),
    db: Session = Depends(get_db),
):
    """O que a app quer perguntar sobre os dias estranhos que ainda não explicou."""
    from routers.dashboard import anomalies

    hoje = date.today()
    try:
        fora = anomalies(days=days, baseline_days=120, db=db).get("anomalies", [])
    except Exception:                                       # noqa: BLE001
        fora = []

    # Já respondidas ou postas de lado não voltam a aparecer.
    arrumadas = {
        (q.date, q.key) for q in db.query(DayQuestion)
        .filter(DayQuestion.date >= hoje - timedelta(days=days)).all()
        if q.dismissed or (q.answer or "").strip()
    }

    saida, vistos = [], set()
    for a in fora:
        try:
            d = date.fromisoformat(a["date"])
        except (KeyError, ValueError):
            continue
        chave = str(a.get("key", ""))
        if (d, chave) in arrumadas or (d, chave) in vistos:
            continue
        texto = _pergunta_da_anomalia(a, hoje)
        if not texto:
            continue
        vistos.add((d, chave))
        saida.append({
            "date": d.isoformat(), "key": chave, "icon": a.get("icon", "❓"),
            "question": texto, "score": a.get("score"),
            # Um dia já contado no diário não precisa de mais explicação.
            "has_journal": bool(
                db.query(DailyJournal).filter(DailyJournal.date == d).first()
            ),
        })

    # Os dias mais fora do normal primeiro; a data desempata (mais recente ganha).
    saida.sort(key=lambda q: (q["has_journal"], -(q["score"] or 0), q["date"]))

    # No máximo duas do mesmo tipo: uma semana de compras dava quatro vezes
    # "em quê?" e escondia a noite de 2h de sono, que é a pergunta que interessa.
    escolhidas, quantas = [], {}
    for q in saida:
        tipo = q["key"].split(":")[0]
        if quantas.get(tipo, 0) >= 2:
            continue
        quantas[tipo] = quantas.get(tipo, 0) + 1
        escolhidas.append(q)
        if len(escolhidas) >= limit:
            break
    return {"days": days, "questions": escolhidas, "total": len(saida)}


class RespostaDoDia(BaseModel):
    date: date
    key: str
    question: str
    answer: str = ""


@router.post("/questions/answer")
def responder(body: RespostaDoDia, db: Session = Depends(get_db)):
    """Guarda a resposta e junta-a ao diário desse dia."""
    texto = (body.answer or "").strip()
    if not texto:
        raise HTTPException(status_code=400, detail="Resposta vazia")

    registo = (
        db.query(DayQuestion)
        .filter(DayQuestion.date == body.date, DayQuestion.key == body.key).first()
    )
    if registo is None:
        registo = DayQuestion(date=body.date, key=body.key, question=body.question[:500])
        db.add(registo)
    registo.question = body.question[:500]
    registo.answer = texto[:2000]
    registo.answered_at = datetime.now()
    registo.dismissed = False

    # O diário desse dia fica com a pergunta e a resposta — é lá que ele vai
    # procurar daqui a uns meses, não a uma tabela de perguntas.
    linha = f"{body.question.strip()}\n{texto}"
    diario = db.query(DailyJournal).filter(DailyJournal.date == body.date).first()
    if diario is None:
        db.add(DailyJournal(date=body.date, content=linha))
    elif linha not in (diario.content or ""):
        diario.content = f"{(diario.content or '').rstrip()}\n\n{linha}".strip()
    db.commit()
    return {"ok": True, "date": str(body.date)}


class PorDeLado(BaseModel):
    date: date
    key: str
    question: str = ""


@router.post("/questions/dismiss")
def por_de_lado(body: PorDeLado, db: Session = Depends(get_db)):
    registo = (
        db.query(DayQuestion)
        .filter(DayQuestion.date == body.date, DayQuestion.key == body.key).first()
    )
    if registo is None:
        registo = DayQuestion(date=body.date, key=body.key, question=body.question[:500])
        db.add(registo)
    registo.dismissed = True
    db.commit()
    return {"ok": True}


@router.get("/questions/answered")
def respondidas(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    """O que já foi explicado — o histórico dos porquês."""
    linhas = (
        db.query(DayQuestion)
        .filter(DayQuestion.answer != "")
        .order_by(DayQuestion.date.desc()).limit(limit).all()
    )
    return [
        {"date": q.date.isoformat(), "key": q.key, "question": q.question,
         "answer": q.answer, "answered_at": q.answered_at.isoformat() if q.answered_at else None}
        for q in linhas
    ]


# ── Diário escrito pela app ───────────────────────────────────────
# Uma entrada de diário em 110 dias diz que a folha em branco não funciona. A app
# escreve o dia com o que já sabe e ele só corrige o que interessa — as partes
# que nenhum sensor apanha.

def _periodo(hora: int) -> str:
    return "de madrugada" if hora < 6 else "de manhã" if hora < 12 else "à tarde" if hora < 19 else "à noite"


def _rascunho_do_dia(db: Session, d: date) -> tuple[str, list[str]]:
    frases: list[str] = []
    fontes: list[str] = []

    sono = db.query(SleepEntry).filter(SleepEntry.date == d).order_by(SleepEntry.id.desc()).first()
    if sono and sono.hours:
        pedaco = f"Dormi {round(sono.hours, 1)}h"
        if sono.bedtime and sono.wake_time:
            pedaco += f" ({sono.bedtime}–{sono.wake_time})"
        if sono.hours < 6:
            pedaco += " e acordei a arrastar-me"
        elif sono.hours >= 9:
            pedaco += ", bem dormido"
        frases.append(pedaco + ".")
        fontes.append("sono")

    codigo = (
        db.query(func.coalesce(func.sum(WakaProjectDay.seconds), 0))
        .filter(WakaProjectDay.day == d, WakaProjectDay.kind == "project").scalar()
    ) or 0
    projectos = (
        db.query(WakaProjectDay.project, WakaProjectDay.seconds)
        .filter(WakaProjectDay.day == d, WakaProjectDay.kind == "project")
        .order_by(WakaProjectDay.seconds.desc()).limit(2).all()
    )
    if codigo >= 300:
        nomes = " e ".join(p[0] for p in projectos)
        frases.append(f"Estive {_hm(codigo)} a programar, sobretudo no {nomes}.")
        fontes.append("código")
    elif codigo == 0:
        frases.append("Não toquei em código.")

    notas = db.query(func.count(CodeProjectNote.id)).filter(CodeProjectNote.note_date == d).scalar() or 0
    if notas:
        frases.append(f"Ficaram {notas} nota{'s' if notas != 1 else ''} de trabalho registada{'s' if notas != 1 else ''}.")

    jogos = db.query(LolGame).filter(LolGame.date == d).all()
    if jogos:
        v = sum(1 for g in jogos if g.won)
        quando = _periodo(min((g.game_hour for g in jogos if g.game_hour is not None), default=21))
        resultado = "correu bem" if v > len(jogos) - v else "correu mal" if v < len(jogos) - v else "ficou empatado"
        frases.append(f"Joguei {len(jogos)} game{'s' if len(jogos) != 1 else ''} de LoL {quando} ({v}W-{len(jogos) - v}L) — {resultado}.")
        fontes.append("LoL")

    ecra = (
        screen_source.por_dia(db, d, d).get(d, 0)
    ) or 0
    if ecra >= 3600 * 6:
        frases.append(f"Foram {_hm(ecra)} de ecrã ao todo.")
        fontes.append("ecrã")

    gastos = db.query(Expense).filter(Expense.date == d, Expense.kind == ek.GASTO).all()
    if gastos:
        total = sum(e.amount for e in gastos)
        maior = max(gastos, key=lambda e: e.amount)
        if len(gastos) == 1:
            frases.append(f"Gastei {total:.2f}€ ({maior.description}).")
        else:
            frases.append(f"Gastei {total:.2f}€ em {len(gastos)} coisas, a maior foi {maior.description} ({maior.amount:.2f}€).")
        fontes.append("gastos")

    viagem = db.query(Trip).filter(Trip.start_date <= d, Trip.end_date >= d).first()
    if viagem:
        frases.insert(0, f"Estava em {viagem.destination}.")
        fontes.append("viagem")

    feitos = [
        e.title for e in db.query(Event).filter(Event.date == d, Event.completed == True)  # noqa: E712
        .order_by(Event.start_time).limit(4).all()
    ]
    tarefas = db.query(func.count(ListItem.id)).filter(ListItem.due_date == d, ListItem.checked == True).scalar() or 0  # noqa: E712
    if feitos:
        frases.append("Fiz: " + ", ".join(feitos) + ".")
        fontes.append("agenda")
    elif tarefas:
        frases.append(f"Risquei {tarefas} tarefa{'s' if tarefas != 1 else ''} da lista.")

    humor = db.query(MoodEntry).filter(MoodEntry.date == d).first()
    if humor and humor.mood is not None:
        pedaco = f"Dei {humor.mood}/10 ao dia"
        if humor.note:
            pedaco += f" — {humor.note.strip()}"
        frases.append(pedaco + ".")
        fontes.append("humor")

    return " ".join(frases), fontes


@router.get("/journal-draft")
def journal_draft(day: Optional[date] = Query(None), db: Session = Depends(get_db)):
    """Primeiro rascunho do diário, feito só com dados — sem IA e sem inventar nada."""
    d = day or date.today()
    texto, fontes = _rascunho_do_dia(db, d)
    return {
        "date": str(d),
        "text": texto,
        "sources": fontes,
        "empty": not texto.strip(),
    }
