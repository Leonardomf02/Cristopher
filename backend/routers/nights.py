"""Saídas à noite: se saiu, e se bebeu.

Não há nada no Mac nem no relógio que diga isto, por isso marca-se à mão — mas
a app ajuda: um gasto na categoria Noite entre as 18h e as 6h da manhã seguinte
é quase sempre uma saída, e aparece como pista para confirmar (nunca se marca
sozinho: pagar a entrada de um amigo não é ter saído).

O que vale a pena tirar daqui é o efeito no sono: a noite depois de beber
contra as noites em casa, nas medidas do relógio.
"""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from database import get_db
from garmin_insights import POR_CHAVE, _mediana, valor_da_metrica
from lol_performance import mann_whitney
from models import Expense, GarminDay, NightOut

router = APIRouter(prefix="/api/nights", tags=["Noites"])

# Abaixo disto a mediana de um grupo é uma noite ou duas, e não diz nada.
MINIMO_POR_GRUPO = 3
# As medidas da manhã seguinte que o álcool costuma mexer.
MEDIDAS = ("sleep_score", "sleep_hours", "hrv_last_night", "resting_hr",
           "pct_deep", "pct_rem", "bb_start", "bedtime")


class Marca(BaseModel):
    drank: bool = False
    # 1 pouco, 2 médio, 3 muito. Dar um nível já é dizer que bebeu.
    level: Optional[int] = Field(None, ge=1, le=3)


def _json(n: Optional[NightOut], d: date) -> dict:
    bebeu = bool(n and n.drank)
    return {"date": d.isoformat(), "went_out": n is not None, "drank": bebeu,
            "drink_level": n.drink_level if bebeu else None}


def _pistas(db: Session, d: date) -> list[dict]:
    """Gastos na Noite entre as 18h desse dia e as 6h do seguinte. Sem hora (a
    Caixa não a manda) conta o próprio dia."""
    seguinte = d + timedelta(days=1)
    gastos = (db.query(Expense)
              .filter(Expense.category == "nightlife",
                      Expense.kind == "spend",
                      or_(and_(Expense.date == d,
                               or_(Expense.time_of_day.is_(None), Expense.time_of_day >= "18:00")),
                          and_(Expense.date == seguinte, Expense.time_of_day < "06:00")))
              .order_by(Expense.date, Expense.time_of_day).all())
    return [{"description": g.description, "amount": round(g.amount, 2),
             "date": g.date.isoformat(), "time": g.time_of_day} for g in gastos]


@router.get("")
def lista(days: int = Query(90, ge=1, le=3650), db: Session = Depends(get_db)):
    desde = date.today() - timedelta(days=days)
    noites = db.query(NightOut).filter(NightOut.date >= desde).order_by(NightOut.date).all()
    return [_json(n, n.date) for n in noites]


@router.get("/effect")
def efeito(days: int = Query(365, ge=30, le=3650), db: Session = Depends(get_db)):
    """O sono depois de beber contra o sono depois de ficar em casa.

    Medianas lado a lado e, havendo noites que cheguem, Mann-Whitney por medida
    (o mesmo teste do LoL). As saídas sem beber ficam de fora dos dois grupos:
    deitar às 4h sóbrio é outra pergunta."""
    desde = date.today() - timedelta(days=days)
    saidas = {n.date: n.drank for n in db.query(NightOut).filter(NightOut.date >= desde)}
    noites = (db.query(GarminDay)
              .filter(GarminDay.date > desde, GarminDay.sleep_hours.isnot(None)).all())
    bebeu, casa = [], []
    for n in noites:
        vespera = n.date - timedelta(days=1)
        if vespera not in saidas:
            casa.append(n)
        elif saidas[vespera]:
            bebeu.append(n)

    linhas = []
    if len(bebeu) >= MINIMO_POR_GRUPO and len(casa) >= MINIMO_POR_GRUPO:
        for chave in MEDIDAS:
            m = POR_CHAVE[chave]
            a = [v for v in (valor_da_metrica(n, m) for n in bebeu) if v is not None]
            b = [v for v in (valor_da_metrica(n, m) for n in casa) if v is not None]
            if len(a) < MINIMO_POR_GRUPO or len(b) < MINIMO_POR_GRUPO:
                continue
            teste = mann_whitney(a, b)
            linhas.append({
                "key": chave, "name": m.nome, "unit": m.unidade,
                "drank": m.formato(_mediana(a)), "home": m.formato(_mediana(b)),
                "worse": (_mediana(a) - _mediana(b)) * m.sentido < 0,
                "p": round(teste[1], 4) if teste else None,
            })
    return {"days": days, "drank": len(bebeu), "home": len(casa),
            "sober_out": sum(1 for d, b in saidas.items() if not b),
            "min": MINIMO_POR_GRUPO, "rows": linhas}


@router.get("/{dia}")
def ler(dia: date, db: Session = Depends(get_db)):
    n = db.query(NightOut).filter(NightOut.date == dia).first()
    return {**_json(n, dia), "evidence": _pistas(db, dia)}


@router.put("/{dia}")
def marcar(dia: date, body: Marca, db: Session = Depends(get_db)):
    n = db.query(NightOut).filter(NightOut.date == dia).first()
    if not n:
        n = NightOut(date=dia)
        db.add(n)
    n.drank = body.drank or body.level is not None
    n.drink_level = body.level if n.drank else None
    db.commit()
    return {**_json(n, dia), "evidence": _pistas(db, dia)}


@router.delete("/{dia}")
def desmarcar(dia: date, db: Session = Depends(get_db)):
    db.query(NightOut).filter(NightOut.date == dia).delete()
    db.commit()
    return {**_json(None, dia), "evidence": _pistas(db, dia)}
