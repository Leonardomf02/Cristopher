"""O que a app acertou.

Várias partes desta app fazem previsões: o motor de investimentos dá convicções,
o LoL diz se é boa altura para jogar, o planeador monta um dia, a estimativa de
sono declara horas. Cada uma media-se por si (quando media), em ecrãs
diferentes. Isto junta tudo num sítio: quantas vezes cada parte acertou, com que
amostra, e quando não há dados para dizer nada.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/scorecard", tags=["Placar"])


def _cartao(area: str, icone: str, titulo: str, **extra) -> dict:
    return {"area": area, "icon": icone, "title": titulo, **extra}


def _investimentos(db: Session) -> dict:
    from routers.investment_signals import calibration_stats
    try:
        c = calibration_stats(db=db)
    except Exception:
        return _cartao("investimentos", "📈", "Sugestões de investimento", enough=False,
                       note="sem sugestões resolvidas ainda")
    geral = (c or {}).get("overall") or {}
    n = geral.get("n") or 0
    if n < 10:
        return _cartao("investimentos", "📈", "Sugestões de investimento", enough=False,
                       note=f"só {n} sugestões resolvidas")
    acerto = geral.get("hit_rate_pct")
    return _cartao(
        "investimentos", "📈", "Sugestões de investimento",
        enough=True, n=n, hit_rate=acerto,
        detail=f"retorno médio {geral.get('avg_return_pct')}%",
        verdict=("acima do acaso" if acerto and acerto >= 55
                 else "abaixo do acaso" if acerto is not None and acerto < 45
                 else "no acaso"),
        breakdown=[
            {"label": {"high": "convicção alta", "medium": "convicção média", "low": "convicção baixa"}.get(k, k),
             "n": v.get("n"), "hit_rate": v.get("actual_hit_rate_pct"), "promised": v.get("expected_hit_rate_pct")}
            for k, v in ((c or {}).get("by_conviction") or {}).items() if v.get("n")
        ],
        url="/investments",
    )


def _lol(db: Session) -> dict:
    from models import LolPrediction
    total = db.query(LolPrediction).filter(LolPrediction.correct.isnot(None)).count()
    if total < 10:
        return _cartao("lol", "🎮", "Previsões de vitória no LoL", enough=False,
                       note=f"só {total} previsões resolvidas")
    certas = db.query(LolPrediction).filter(LolPrediction.correct == True).count()  # noqa: E712
    acerto = round(certas / total * 100, 1)
    return _cartao(
        "lol", "🎮", "Previsões de vitória no LoL",
        enough=True, n=total, hit_rate=acerto,
        detail=f"{certas} certas em {total}",
        verdict="acima do acaso" if acerto >= 55 else "no acaso" if acerto >= 45 else "abaixo do acaso",
        url="/lol",
    )


def _plano(db: Session, dias: int) -> dict:
    """Quanto do plano do dia acontece mesmo (média dos últimos dias com plano)."""
    from models import DayPlanRecord
    from routers.day_planner import plan_reality

    hoje = date.today()
    pcts = []
    for r in (
        db.query(DayPlanRecord)
        .filter(DayPlanRecord.plan_date >= hoje - timedelta(days=dias), DayPlanRecord.plan_date < hoje)
        .order_by(DayPlanRecord.plan_date.desc())
        .limit(20)
        .all()
    ):
        try:
            real = plan_reality(r.plan_date.isoformat(), db=db)
        except Exception:
            continue
        resumo = real.get("summary") or {}
        if real.get("tracked") and resumo.get("total"):
            pcts.append(resumo["pct"])
    if len(pcts) < 3:
        return _cartao("plano", "🗓️", "Plano do dia cumprido", enough=False,
                       note=f"só {len(pcts)} dias com plano e tracker")
    media = round(sum(pcts) / len(pcts))
    return _cartao(
        "plano", "🗓️", "Plano do dia cumprido",
        enough=True, n=len(pcts), hit_rate=media,
        detail=f"média de {len(pcts)} dias planeados",
        verdict="segue-se bem" if media >= 60 else "mais ou menos" if media >= 35 else "quase não se cumpre",
        url="/planner",
    )


def _sono(db: Session, dias: int) -> dict:
    """Quantas noites registadas batem certo com o que a máquina viu."""
    from routers.sleep import estimativa_por_paragem
    from models import SleepEntry

    hoje = date.today()
    batem = falham = 0
    for i in range(dias):
        d = hoje - timedelta(days=i)
        est = estimativa_por_paragem(db, d)
        if not est:
            continue
        entrada = db.query(SleepEntry).filter(SleepEntry.date == d).order_by(SleepEntry.id.desc()).first()
        if not entrada or entrada.hours is None:
            continue
        if abs(entrada.hours - est["hours"]) <= 1.5:
            batem += 1
        else:
            falham += 1
    total = batem + falham
    if total < 3:
        return _cartao("sono", "🌙", "Registos de sono certos", enough=False,
                       note="ainda poucas noites com paragem do Mac registada")
    acerto = round(batem / total * 100, 1)
    return _cartao(
        "sono", "🌙", "Registos de sono certos",
        enough=True, n=total, hit_rate=acerto,
        detail=f"{batem} de {total} noites batem certo com a máquina",
        verdict="de confiança" if acerto >= 70 else "a precisar de revisão",
        url="/sleep",
    )


def _deals(db: Session) -> dict:
    """Dos anúncios que a IA classificou como bons, quantos ele guardou."""
    from models import DealResult
    bons = db.query(DealResult).filter(DealResult.ai_match == True, DealResult.ai_rating >= 70).count()  # noqa: E712
    guardados = db.query(DealResult).filter(
        DealResult.ai_match == True, DealResult.ai_rating >= 70, DealResult.status == "saved"  # noqa: E712
    ).count()
    descartados = db.query(DealResult).filter(
        DealResult.ai_match == True, DealResult.ai_rating >= 70, DealResult.status == "dismissed"  # noqa: E712
    ).count()
    decididos = guardados + descartados
    if decididos < 5:
        return _cartao("deals", "🏷️", "Deals que a IA achou bons", enough=False,
                       note=f"{bons} classificados como bons, mas ainda sem decisões tuas para comparar")
    acerto = round(guardados / decididos * 100, 1)
    return _cartao(
        "deals", "🏷️", "Deals que a IA achou bons",
        enough=True, n=decididos, hit_rate=acerto,
        detail=f"guardaste {guardados} dos {decididos} que avaliaste",
        verdict="alinhada contigo" if acerto >= 50 else "desalinhada contigo",
        url="/deals",
    )


@router.get("/")
def placar(days: int = Query(90, ge=14, le=365), db: Session = Depends(get_db)):
    cartoes = [
        _investimentos(db),
        _lol(db),
        _plano(db, days),
        _sono(db, min(days, 30)),
        _deals(db),
    ]
    com_dados = [c for c in cartoes if c.get("enough")]
    return {
        "days": days,
        "cards": cartoes,
        "measured": len(com_dados),
        "total": len(cartoes),
    }
