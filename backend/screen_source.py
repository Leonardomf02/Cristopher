"""De onde vêm as horas de ecrã do Mac.

Havia duas fontes: o tracker próprio (janela activa, segundo a segundo) e uma
leitura aproximada do `knowledgeC.db` da Apple. Comparando as duas com uma
terceira que é verdade absoluta — a duração real das partidas de LoL — o tracker
acerta quase ao minuto (3.69h reais → 3.76h) e a leitura da Apple erra para os
dois lados (mesmo dia: 2.95h; noutro dia 4.30h contra 3.39h reais).

Por isso o ecrã do Mac passa a vir do tracker. A leitura da Apple fica como
comparação (e como única fonte possível para outros dispositivos).

As categorias são traduzidas para o vocabulário da Apple porque é o que já está
guardado nos tectos semanais e no ecrã de Screen Time.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from models import AppUsageSession

# tracker → vocabulário da Apple (o que os tectos já usam)
PARA_APPLE = {
    "development": "Productivity & Finance",
    "productivity": "Productivity & Finance",
    "finance": "Productivity & Finance",
    "communication": "Social",
    "social": "Social",
    "gaming": "Games",
    "entertainment": "Entertainment",
    "media": "Entertainment",
    "system": "Utilities",
    "shopping": "Other",
    "browser": "Other",
    "other": "Other",
}


def para_apple(categoria: Optional[str]) -> str:
    return PARA_APPLE.get((categoria or "").lower(), "Other")


def _sessoes(db: Session, inicio: date, fim: date) -> list[AppUsageSession]:
    return (
        db.query(AppUsageSession)
        .filter(AppUsageSession.date >= inicio, AppUsageSession.date <= fim)
        .all()
    )


def _categoria(db: Session, s: AppUsageSession) -> str:
    from routers.app_usage import _resolve_category
    return _resolve_category(db, s)


def por_dia(db: Session, inicio: date, fim: date) -> dict[date, int]:
    """Segundos de ecrã por dia."""
    out: dict[date, int] = {}
    for s in _sessoes(db, inicio, fim):
        out[s.date] = out.get(s.date, 0) + (s.duration_seconds or 0)
    return out


def por_categoria(db: Session, inicio: date, fim: date, *, apple: bool = True) -> dict[str, int]:
    """Segundos por categoria no período (vocabulário da Apple por omissão)."""
    out: dict[str, int] = {}
    for s in _sessoes(db, inicio, fim):
        c = _categoria(db, s)
        chave = para_apple(c) if apple else c
        out[chave] = out.get(chave, 0) + (s.duration_seconds or 0)
    return out


def por_dia_e_categoria(db: Session, inicio: date, fim: date, *, apple: bool = True) -> dict[date, dict[str, int]]:
    out: dict[date, dict[str, int]] = {}
    for s in _sessoes(db, inicio, fim):
        c = para_apple(_categoria(db, s)) if apple else _categoria(db, s)
        dia = out.setdefault(s.date, {})
        dia[c] = dia.get(c, 0) + (s.duration_seconds or 0)
    return out


def por_app(
    db: Session,
    inicio: date,
    fim: date,
    *,
    dia_da_semana: Optional[int] = None,
    categoria: Optional[str] = None,
) -> list[dict]:
    """Segundos por aplicação, do mais usado para o menos. A categoria é a que
    pesa mais dentro da app: no browser cada separador tem a sua.

    `dia_da_semana` (0 = segunda) e `categoria` respondem à pergunta "que apps é
    que fazem as 2h45 de Productivity & Finance às quartas": sem isto, a página
    mostrava a média da barra e não havia forma de saber de onde vinha. Com uma
    categoria escolhida contam-se só os segundos dessa categoria — o browser tem
    separadores em várias, e somá-lo inteiro mentia."""
    acc: dict[tuple, dict] = {}
    for s in _sessoes(db, inicio, fim):
        if dia_da_semana is not None and s.date.weekday() != dia_da_semana:
            continue
        if categoria is not None and para_apple(_categoria(db, s)) != categoria:
            continue
        chave = (s.bundle_id or "", s.app_name or "")
        linha = acc.setdefault(chave, {
            "bundle_id": s.bundle_id, "app_name": s.app_name,
            "category": "Other", "seconds": 0, "sessions": 0, "_cats": {},
        })
        segundos = s.duration_seconds or 0
        cat = para_apple(_categoria(db, s))
        linha["seconds"] += segundos
        linha["sessions"] += 1
        linha["_cats"][cat] = linha["_cats"].get(cat, 0) + segundos
    saida = []
    for linha in acc.values():
        cats = linha.pop("_cats")
        if cats:
            linha["category"] = max(cats.items(), key=lambda kv: kv[1])[0]
        saida.append(linha)
    return sorted(saida, key=lambda r: -r["seconds"])


def total(db: Session, inicio: date, fim: date) -> int:
    return sum(por_dia(db, inicio, fim).values())


def por_hora_e_categoria(db: Session, inicio: date, fim: date, *, apple: bool = True) -> list[dict[str, int]]:
    """Segundos por hora do dia (0-23) e por categoria, somados no período.
    Uma sessão que atravesse a fronteira da hora reparte-se pelas duas — mesma
    lógica do mapa hora-a-hora de produtividade em app_insights.deep_work."""
    out: list[dict[str, int]] = [{} for _ in range(24)]
    for s in _sessoes(db, inicio, fim):
        c = para_apple(_categoria(db, s)) if apple else _categoria(db, s)
        remaining = s.duration_seconds or 0
        cursor = s.start_time
        while remaining > 0:
            h = cursor.hour
            hour_end = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            chunk = min(remaining, int((hour_end - cursor).total_seconds()))
            out[h][c] = out[h].get(c, 0) + chunk
            remaining -= chunk
            cursor = hour_end
    return out
