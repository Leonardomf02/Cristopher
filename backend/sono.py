"""O sono, só quando é medido.

Durante meses o sono da app foi um palpite: a maior paragem do Mac, ou uma noite
escrita à mão antes de ela ter acontecido. Essas linhas continuam em
`sleep_entries`, mas não são a mesma coisa que uma noite medida — o portátil
desligado das 15:24 às 20:41 entrava como 5h de sono, e nenhuma delas tem
pontuação, fases ou HRV. Misturá-las com o relógio dava médias de coisa nenhuma.

Quem faz contas com sono pergunta aqui, e aqui só existe o que o relógio mediu.
"""

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from models import GarminDay, SleepEntry

FONTE = "garmin"


def noites(db: Session, inicio: Optional[date] = None, fim: Optional[date] = None) -> list[SleepEntry]:
    q = db.query(SleepEntry).filter(SleepEntry.source == FONTE)
    if inicio is not None:
        q = q.filter(SleepEntry.date >= inicio)
    if fim is not None:
        q = q.filter(SleepEntry.date <= fim)
    return q.order_by(SleepEntry.date).all()


def noite(db: Session, dia: date) -> Optional[SleepEntry]:
    return (
        db.query(SleepEntry)
        .filter(SleepEntry.date == dia, SleepEntry.source == FONTE)
        .first()
    )


def horas_por_dia(db: Session, inicio: Optional[date] = None,
                  fim: Optional[date] = None) -> dict[date, float]:
    return {n.date: n.hours for n in noites(db, inicio, fim) if n.hours}


def pontuacoes(db: Session, inicio: Optional[date] = None,
               fim: Optional[date] = None) -> dict[date, int]:
    """A pontuação 0-100 de cada noite — substituiu as estrelas de 1 a 5."""
    q = db.query(GarminDay.date, GarminDay.sleep_score).filter(GarminDay.sleep_score.isnot(None))
    if inicio is not None:
        q = q.filter(GarminDay.date >= inicio)
    if fim is not None:
        q = q.filter(GarminDay.date <= fim)
    return {d: s for d, s in q.all()}
