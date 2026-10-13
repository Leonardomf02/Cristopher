"""Alimentação: comer as principais a horas, e saber quando não aconteceu.

O score é só das refeições com janela (pequeno-almoço, almoço, jantar): dentro da
janela conta inteira, fora conta metade, falhada conta zero. Os lanches ficam
registados mas não entram na conta — senão bastava petiscar para o dia parecer bom.

Uma refeição cuja janela ainda não fechou não conta como falhada: fica pendente,
e o score do dia é só sobre o que já se decidiu.
"""
from datetime import date as date_cls, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import MealLog, MealNotice, MealSlot, Supplement, SupplementLog

router = APIRouter(prefix="/api/meals", tags=["Alimentação"])

# Dentro da janela vale tudo, fora vale metade: comer o almoço às 17h não é o
# mesmo que falhá-lo, mas também não é o que ele quer medir.
PESO_DENTRO = 1.0
PESO_FORA = 0.5
# A partir daqui o dia conta como bom (para a sequência de dias).
DIA_BOM = 80
# Nos suplementos não há meio termo: ou tomou o que tinha para tomar, ou não.
DIA_BOM_SUP = 100

# Os dois que ele quis à partida. São uma sugestão, não uma regra: apagam-se e
# acrescentam-se na própria página.
_SUPLEMENTOS_POR_OMISSAO = [("Proteína", "30 g"), ("Creatina", "5 g")]

_POR_OMISSAO = [
    ("breakfast", "Pequeno-almoço", "08:00", "10:00", 0),
    ("lunch", "Almoço", "12:30", "14:30", 1),
    ("dinner", "Jantar", "19:30", "21:30", 2),
]


def _hora(texto: str) -> tuple[int, int]:
    h, m = (texto or "00:00").split(":")[:2]
    return int(h), int(m)


def _janela(slot: MealSlot, dia: date_cls) -> tuple[datetime, datetime]:
    """Início e fim da janela nesse dia. Uma janela que acabe antes de começar
    (ceia das 23:00 à 01:00) fecha no dia seguinte."""
    hi, mi = _hora(slot.start_time)
    hf, mf = _hora(slot.end_time)
    inicio = datetime(dia.year, dia.month, dia.day, hi, mi)
    fim = datetime(dia.year, dia.month, dia.day, hf, mf)
    if fim <= inicio:
        fim += timedelta(days=1)
    return inicio, fim


def slots_activos(db: Session) -> list[MealSlot]:
    """As refeições configuradas. Na primeira vez, cria as três principais."""
    existe = db.query(MealSlot).count()
    if not existe:
        for key, nome, inicio, fim, pos in _POR_OMISSAO:
            db.add(MealSlot(key=key, name=nome, start_time=inicio, end_time=fim, position=pos))
        db.commit()
    return (
        db.query(MealSlot)
        .filter(MealSlot.active.is_(True))
        .order_by(MealSlot.position, MealSlot.start_time)
        .all()
    )


def _estado(slot: MealSlot, dia: date_cls, log: Optional[MealLog], agora: datetime) -> str:
    inicio, fim = _janela(slot, dia)
    if log:
        return "feito" if inicio <= log.eaten_at <= fim else "fora"
    if agora >= fim:
        return "falhado"
    if agora >= inicio:
        return "aberto"
    return "por_vir"


def _pontos(estado: str) -> Optional[float]:
    """None = ainda não se decidiu, e por isso não entra no score."""
    return {"feito": PESO_DENTRO, "fora": PESO_FORA, "falhado": 0.0}.get(estado)


def _primeiro_registo(db: Session) -> Optional[date_cls]:
    """O dia do primeiro registo. Antes disso não há nada para julgar."""
    valor = db.query(func.min(MealLog.date)).scalar()
    if not valor:
        return None
    return valor if isinstance(valor, date_cls) else date_cls.fromisoformat(str(valor)[:10])


def _score_do_dia(db: Session, dia: date_cls, agora: Optional[datetime] = None,
                  inicio: Optional[date_cls] = None, tem_inicio: bool = False) -> dict:
    agora = agora or datetime.now()
    if not tem_inicio:
        inicio = _primeiro_registo(db)
    slots = slots_activos(db)
    logs = {
        l.slot_key: l
        for l in db.query(MealLog).filter(MealLog.date == dia, MealLog.slot_key.isnot(None)).all()
    }
    linhas, pontos = [], []
    for s in slots:
        log = logs.get(s.key)
        estado = _estado(s, dia, log, agora)
        p = _pontos(estado)
        if p is not None:
            pontos.append(p)
        linhas.append({
            "key": s.key, "name": s.name, "start_time": s.start_time, "end_time": s.end_time,
            "notify": bool(s.notify), "state": estado,
            "log": None if not log else {
                "id": log.id, "eaten_at": log.eaten_at.isoformat(), "description": log.description or "",
            },
        })
    score = round(100 * sum(pontos) / len(pontos)) if pontos else None
    # Dias anteriores ao primeiro registo não são dias falhados — é a app que
    # ainda não existia. Contá-los como zero punha a média da semana a mentir.
    antes_de_comecar = inicio is None or dia < inicio
    if antes_de_comecar:
        score = None
    return {"slots": linhas, "score": score, "decided": 0 if antes_de_comecar else len(pontos),
            "total": len(slots), "tracked": not antes_de_comecar}


# ── Refeições configuradas ───────────────────────────────────────

class SlotIn(BaseModel):
    name: str
    start_time: str
    end_time: str
    notify: bool = True
    active: bool = True
    key: Optional[str] = None


@router.get("/slots")
def listar_slots(db: Session = Depends(get_db)):
    slots_activos(db)          # garante as três por omissão à primeira vez
    return [
        {"id": s.id, "key": s.key, "name": s.name, "start_time": s.start_time,
         "end_time": s.end_time, "notify": bool(s.notify), "active": bool(s.active),
         "position": s.position}
        for s in db.query(MealSlot).order_by(MealSlot.position, MealSlot.start_time).all()
    ]


@router.post("/slots")
def criar_slot(body: SlotIn, db: Session = Depends(get_db)):
    chave = (body.key or body.name.lower().replace(" ", "-"))[:40]
    if db.query(MealSlot).filter(MealSlot.key == chave).first():
        raise HTTPException(400, "Já existe uma refeição com esse nome")
    ultimo = db.query(MealSlot).count()
    slot = MealSlot(key=chave, name=body.name, start_time=body.start_time,
                    end_time=body.end_time, notify=body.notify, active=body.active,
                    position=ultimo)
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return {"id": slot.id, "key": slot.key}


@router.put("/slots/{slot_id}")
def editar_slot(slot_id: int, body: SlotIn, db: Session = Depends(get_db)):
    slot = db.query(MealSlot).filter(MealSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(404, "Refeição não encontrada")
    slot.name = body.name
    slot.start_time = body.start_time
    slot.end_time = body.end_time
    slot.notify = body.notify
    slot.active = body.active
    db.commit()
    return {"ok": True}


@router.delete("/slots/{slot_id}")
def apagar_slot(slot_id: int, db: Session = Depends(get_db)):
    slot = db.query(MealSlot).filter(MealSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(404, "Refeição não encontrada")
    db.delete(slot)
    db.commit()
    return {"ok": True}


# ── O dia ────────────────────────────────────────────────────────

@router.get("/day")
def dia(data: Optional[date_cls] = Query(None), db: Session = Depends(get_db)):
    alvo = data or date_cls.today()
    resposta = _score_do_dia(db, alvo)
    lanches = (
        db.query(MealLog)
        .filter(MealLog.date == alvo, MealLog.slot_key.is_(None))
        .order_by(MealLog.eaten_at)
        .all()
    )
    resposta["date"] = alvo.isoformat()
    resposta["supplements"] = _suplementos_do_dia(db, alvo)
    resposta["supplements_score"] = _score_suplementos(db, alvo)
    resposta["snacks"] = [
        {"id": l.id, "eaten_at": l.eaten_at.isoformat(), "description": l.description or ""}
        for l in lanches
    ]
    return resposta


class LogIn(BaseModel):
    slot_key: Optional[str] = None       # nulo = lanche
    description: str = ""
    eaten_at: Optional[datetime] = None  # por omissão, agora
    date: Optional[date_cls] = None


@router.post("/log")
def marcar(body: LogIn, db: Session = Depends(get_db)):
    quando = body.eaten_at or datetime.now()
    dia_alvo = body.date or quando.date()
    if body.slot_key:
        # uma refeição por janela e por dia: marcar outra vez corrige a anterior
        existente = (
            db.query(MealLog)
            .filter(MealLog.date == dia_alvo, MealLog.slot_key == body.slot_key)
            .first()
        )
        if existente:
            existente.eaten_at = quando
            if body.description:
                existente.description = body.description
            db.commit()
            return {"id": existente.id, "updated": True}
    log = MealLog(date=dia_alvo, slot_key=body.slot_key, eaten_at=quando,
                  description=body.description)
    db.add(log)
    db.commit()
    db.refresh(log)
    return {"id": log.id, "updated": False}


class LogPatch(BaseModel):
    description: Optional[str] = None
    eaten_at: Optional[datetime] = None


@router.put("/log/{log_id}")
def editar_log(log_id: int, body: LogPatch, db: Session = Depends(get_db)):
    log = db.query(MealLog).filter(MealLog.id == log_id).first()
    if not log:
        raise HTTPException(404, "Registo não encontrado")
    if body.description is not None:
        log.description = body.description
    if body.eaten_at is not None:
        log.eaten_at = body.eaten_at
        log.date = body.eaten_at.date()
    db.commit()
    return {"ok": True}


@router.delete("/log/{log_id}")
def apagar_log(log_id: int, db: Session = Depends(get_db)):
    log = db.query(MealLog).filter(MealLog.id == log_id).first()
    if not log:
        raise HTTPException(404, "Registo não encontrado")
    db.delete(log)
    db.commit()
    return {"ok": True}


@router.get("/suggestions")
def sugestoes(slot_key: Optional[str] = Query(None), q: str = Query(""),
              limit: int = Query(12), db: Session = Depends(get_db)):
    """O que ele já escreveu para aquela refeição, do mais repetido para o menos.

    É por refeição de propósito: o que se come ao pequeno-almoço não é o que se
    come ao jantar, e uma lista única enchia-se de coisas que nunca servem."""
    consulta = db.query(MealLog).filter(MealLog.description != "")
    consulta = (
        consulta.filter(MealLog.slot_key == slot_key) if slot_key
        else consulta.filter(MealLog.slot_key.is_(None))
    )
    procura = q.strip().lower()
    contagem: dict[str, int] = {}
    for log in consulta.order_by(MealLog.eaten_at.desc()).limit(500).all():
        texto = (log.description or "").strip()
        if not texto or (procura and procura not in texto.lower()):
            continue
        contagem[texto] = contagem.get(texto, 0) + 1
    ordenadas = sorted(contagem.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    return [{"text": t, "times": n} for t, n in ordenadas[:limit]]


@router.get("/score")
def historico(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    """Score de cada dia, média dos últimos 7 e sequência de dias bons."""
    hoje = date_cls.today()
    agora = datetime.now()
    inicio = _primeiro_registo(db)
    dias = []
    for i in range(days - 1, -1, -1):
        d = hoje - timedelta(days=i)
        resultado = _score_do_dia(db, d, agora, inicio, tem_inicio=True)
        dias.append({"date": d.isoformat(), "score": resultado["score"],
                     "decided": resultado["decided"], "total": resultado["total"]})

    fechados = [d for d in dias if d["score"] is not None]
    ultimos7 = [d["score"] for d in fechados[-7:]]
    media7 = round(sum(ultimos7) / len(ultimos7)) if ultimos7 else None

    # A sequência não se parte por o dia de hoje ainda estar a meio: conta-se de
    # trás para a frente e o dia incompleto só entra se já estiver acima da fasquia.
    sequencia = 0
    for d in reversed(dias):
        if d["score"] is None:
            continue
        if d["date"] == hoje.isoformat() and d["decided"] < d["total"] and d["score"] < DIA_BOM:
            continue
        if d["score"] >= DIA_BOM:
            sequencia += 1
        else:
            break

    return {"days": dias, "avg_7": media7, "streak": sequencia, "good_day": DIA_BOM}


# ── Suplementos ─────────────────────────────────────────────────

def suplementos_activos(db: Session) -> list[Supplement]:
    """Os suplementos configurados. Na primeira vez, propõe proteína e creatina."""
    if not db.query(Supplement).count():
        for i, (nome, dose) in enumerate(_SUPLEMENTOS_POR_OMISSAO):
            db.add(Supplement(name=nome, dose=dose, position=i))
        db.commit()
    return (
        db.query(Supplement)
        .filter(Supplement.active.is_(True))
        .order_by(Supplement.position, Supplement.id)
        .all()
    )


def _suplementos_do_dia(db: Session, dia: date_cls) -> list[dict]:
    tomados = {
        l.supplement_id: l
        for l in db.query(SupplementLog).filter(SupplementLog.date == dia).all()
    }
    saida = []
    for s in suplementos_activos(db):
        log = tomados.get(s.id)
        saida.append({
            "id": s.id, "name": s.name, "dose": s.dose or "",
            "time_hint": s.time_hint, "notify": bool(s.notify),
            "taken_at": log.taken_at.isoformat() if log else None,
        })
    return saida


def _primeiro_suplemento(db: Session) -> Optional[date_cls]:
    valor = db.query(func.min(SupplementLog.date)).scalar()
    if not valor:
        return None
    return valor if isinstance(valor, date_cls) else date_cls.fromisoformat(str(valor)[:10])


def _score_suplementos(db: Session, dia: date_cls, inicio: Optional[date_cls] = None,
                       tem_inicio: bool = False) -> dict:
    """Quantos dos suplementos activos foram tomados nesse dia, em percentagem.

    Anda ao lado do score das refeições e não dentro dele: ali mede-se comer a
    horas, e um dia sem creatina não é um almoço falhado."""
    if not tem_inicio:
        inicio = _primeiro_suplemento(db)
    activos = suplementos_activos(db)
    if not activos or inicio is None or dia < inicio:
        return {"score": None, "taken": 0, "total": len(activos)}
    ids = {s.id for s in activos}
    tomados = sum(
        1 for l in db.query(SupplementLog).filter(SupplementLog.date == dia).all()
        if l.supplement_id in ids
    )
    return {"score": round(100 * tomados / len(activos)), "taken": tomados, "total": len(activos)}


class SuplementoIn(BaseModel):
    name: str
    dose: str = ""
    time_hint: Optional[str] = None
    notify: bool = False
    active: bool = True


@router.get("/supplements")
def listar_suplementos(db: Session = Depends(get_db)):
    suplementos_activos(db)
    return [
        {"id": s.id, "name": s.name, "dose": s.dose or "", "time_hint": s.time_hint,
         "notify": bool(s.notify), "active": bool(s.active), "position": s.position}
        for s in db.query(Supplement).order_by(Supplement.position, Supplement.id).all()
    ]


@router.post("/supplements")
def criar_suplemento(body: SuplementoIn, db: Session = Depends(get_db)):
    s = Supplement(name=body.name.strip(), dose=body.dose.strip(),
                   time_hint=body.time_hint or None, notify=body.notify,
                   active=body.active, position=db.query(Supplement).count())
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id}


@router.put("/supplements/{sup_id}")
def editar_suplemento(sup_id: int, body: SuplementoIn, db: Session = Depends(get_db)):
    s = db.query(Supplement).filter(Supplement.id == sup_id).first()
    if not s:
        raise HTTPException(404, "Suplemento não encontrado")
    s.name = body.name.strip()
    s.dose = body.dose.strip()
    s.time_hint = body.time_hint or None
    s.notify = body.notify
    s.active = body.active
    db.commit()
    return {"ok": True}


@router.delete("/supplements/{sup_id}")
def apagar_suplemento(sup_id: int, db: Session = Depends(get_db)):
    s = db.query(Supplement).filter(Supplement.id == sup_id).first()
    if not s:
        raise HTTPException(404, "Suplemento não encontrado")
    db.query(SupplementLog).filter(SupplementLog.supplement_id == sup_id).delete()
    db.delete(s)
    db.commit()
    return {"ok": True}


class TomaIn(BaseModel):
    date: Optional[date_cls] = None
    taken: bool = True


@router.post("/supplements/{sup_id}/take")
def marcar_suplemento(sup_id: int, body: TomaIn, db: Session = Depends(get_db)):
    """Carregar outra vez desmarca: é um check, não um registo que se acumula."""
    if not db.query(Supplement).filter(Supplement.id == sup_id).first():
        raise HTTPException(404, "Suplemento não encontrado")
    dia = body.date or date_cls.today()
    log = (
        db.query(SupplementLog)
        .filter(SupplementLog.date == dia, SupplementLog.supplement_id == sup_id)
        .first()
    )
    if body.taken and not log:
        db.add(SupplementLog(date=dia, supplement_id=sup_id, taken_at=datetime.now()))
    elif not body.taken and log:
        db.delete(log)
    db.commit()
    return {"ok": True, "taken": body.taken}


@router.get("/supplements/score")
def historico_suplementos(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    """Score de cada dia, média de 7 e sequência — separado do das refeições."""
    hoje = date_cls.today()
    inicio = _primeiro_suplemento(db)
    dias = []
    for i in range(days - 1, -1, -1):
        d = hoje - timedelta(days=i)
        r = _score_suplementos(db, d, inicio, tem_inicio=True)
        dias.append({"date": d.isoformat(), "score": r["score"],
                     "taken": r["taken"], "total": r["total"]})

    fechados = [d["score"] for d in dias if d["score"] is not None]
    media7 = round(sum(fechados[-7:]) / len(fechados[-7:])) if fechados else None

    # O dia de hoje ainda vai a meio: só corta a sequência quando já não dá para
    # o salvar, ou seja, nunca antes do fim do dia.
    sequencia = 0
    for d in reversed(dias):
        if d["score"] is None:
            continue
        if d["date"] == hoje.isoformat() and d["score"] < DIA_BOM_SUP:
            continue
        if d["score"] >= DIA_BOM_SUP:
            sequencia += 1
        else:
            break

    return {"days": dias, "avg_7": media7, "streak": sequencia, "good_day": DIA_BOM_SUP}


# ── Avisos (trabalho do agendador, de 5 em 5 minutos) ────────────

def _ja_avisado(db: Session, dia: date_cls, slot_key: str, kind: str) -> bool:
    return db.query(MealNotice).filter(
        MealNotice.date == dia, MealNotice.slot_key == slot_key, MealNotice.kind == kind
    ).first() is not None


def avisa_refeicoes(db: Session, agora: Optional[datetime] = None) -> str:
    """Avisa quando a janela abre e outra vez perto do fim, se ainda não comeu.

    Cada aviso sai uma vez por dia: a marca fica na base, para um reinício do
    backend não os repetir de cinco em cinco minutos."""
    agora = agora or datetime.now()
    hoje = agora.date()
    enviados = []
    for slot in slots_activos(db):
        if not slot.notify:
            continue
        inicio, fim = _janela(slot, hoje)
        log = (
            db.query(MealLog)
            .filter(MealLog.date == hoje, MealLog.slot_key == slot.key)
            .first()
        )
        if log:
            continue

        if inicio <= agora < inicio + timedelta(minutes=15) and not _ja_avisado(db, hoje, slot.key, "abriu"):
            _envia(db, hoje, slot, "abriu",
                   f"{slot.name} — está na hora",
                   f"Janela das {slot.start_time} às {slot.end_time}. Marca na app quando comeres.")
            enviados.append(f"{slot.key}:abriu")
        elif fim - timedelta(minutes=20) <= agora < fim and not _ja_avisado(db, hoje, slot.key, "a_fechar"):
            faltam = int((fim - agora).total_seconds() // 60)
            _envia(db, hoje, slot, "a_fechar",
                   f"{slot.name} por marcar",
                   f"A janela fecha às {slot.end_time}, daqui a {faltam} min.")
            enviados.append(f"{slot.key}:a_fechar")

    # Suplementos: só os que têm hora e aviso ligado. Sem hora não há quando avisar.
    for sup in suplementos_activos(db):
        if not (sup.notify and sup.time_hint):
            continue
        hi, mi = _hora(sup.time_hint)
        marca = datetime(hoje.year, hoje.month, hoje.day, hi, mi)
        chave = f"sup:{sup.id}"
        if not (marca <= agora < marca + timedelta(minutes=15)):
            continue
        tomado = (
            db.query(SupplementLog)
            .filter(SupplementLog.date == hoje, SupplementLog.supplement_id == sup.id)
            .first()
        )
        if tomado or _ja_avisado(db, hoje, chave, "abriu"):
            continue
        from notifier import notify
        try:
            notify(f"{sup.name} — está na hora", (sup.dose or "").strip() or "Marca na app quando tomares.")
        except Exception:
            pass
        db.add(MealNotice(date=hoje, slot_key=chave, kind="abriu"))
        db.commit()
        enviados.append(f"{chave}:abriu")

    return ", ".join(enviados) if enviados else "nada a avisar"


def _envia(db: Session, dia: date_cls, slot: MealSlot, kind: str, titulo: str, texto: str) -> None:
    from notifier import notify
    try:
        notify(titulo, texto)
    except Exception:                       # um aviso que falha não trava o resto
        pass
    db.add(MealNotice(date=dia, slot_key=slot.key, kind=kind))
    db.commit()
