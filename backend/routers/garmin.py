"""O que o relógio mediu — sono, recuperação, corpo e treinos.

A página do Sono continua a ser sobre as horas; esta é sobre o resto: o que o
corpo fez com essas horas. Só lê da base — quem fala com a Garmin é o trabalho
`sync_garmin` (ou o botão de sincronizar, que chama o mesmo código).
"""
from __future__ import annotations

import json
import logging
from datetime import date as _date
from datetime import datetime
from datetime import timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import garmin_api
import garmin_sync
from database import get_db
from models import GarminActivity, GarminDay, GarminSeries, GarminSnapshot

router = APIRouter(prefix="/api/garmin", tags=["Garmin"])
logger = logging.getLogger(__name__)


def _dia_para_dict(d: Optional[GarminDay]) -> Optional[dict[str, Any]]:
    if d is None:
        return None
    return {
        "date": d.date.isoformat(),
        "sleep": {
            "start": d.sleep_start.isoformat() if d.sleep_start else None,
            "end": d.sleep_end.isoformat() if d.sleep_end else None,
            "hours": d.sleep_hours,
            "deep_min": d.deep_min, "light_min": d.light_min,
            "rem_min": d.rem_min, "awake_min": d.awake_min,
            "nap_min": d.nap_min, "awake_count": d.awake_count,
            "score": d.sleep_score, "qualifier": d.sleep_qualifier,
            "need_min": d.sleep_need_min, "feedback": d.sleep_feedback,
            "avg_stress": d.avg_sleep_stress,
            "spo2_avg": d.spo2_avg, "spo2_min": d.spo2_min,
            "resp_avg": d.resp_avg, "skin_temp_dev_c": d.skin_temp_dev_c,
        },
        "recovery": {
            "resting_hr": d.resting_hr,
            "hrv": d.hrv_last_night, "hrv_high": d.hrv_5min_high,
            "hrv_weekly": d.hrv_weekly_avg, "hrv_status": d.hrv_status,
            "hrv_low": d.hrv_baseline_low, "hrv_up": d.hrv_baseline_high,
            "hrv_feedback": d.hrv_feedback,
        },
        "body_battery": {"start": d.bb_start, "end": d.bb_end, "min": d.bb_min,
                         "max": d.bb_max, "charged": d.bb_charged, "drained": d.bb_drained},
        "stress": {"avg": d.stress_avg, "max": d.stress_max,
                   "rest_min": d.stress_rest_min, "low_min": d.stress_low_min,
                   "medium_min": d.stress_medium_min, "high_min": d.stress_high_min},
        "activity": {"steps": d.steps, "step_goal": d.step_goal,
                     "distance_m": d.distance_m, "calories": d.calories,
                     "active_calories": d.active_calories,
                     "moderate_min": d.intensity_moderate_min,
                     "vigorous_min": d.intensity_vigorous_min,
                     "hr_min": d.hr_min, "hr_max": d.hr_max},
        "training": {"readiness": d.training_readiness, "level": d.readiness_level,
                     "feedback": d.readiness_feedback, "status": d.training_status,
                     "vo2max": d.vo2max, "acute_load": d.acute_load,
                     "recovery_min": d.recovery_min,
                     "factors": {"sleep": d.readiness_sleep_pct, "hrv": d.readiness_hrv_pct,
                                 "recovery": d.readiness_recovery_pct, "load": d.readiness_load_pct,
                                 "stress": d.readiness_stress_pct}},
        "body": {"fitness_age": d.fitness_age, "achievable_age": d.fitness_age_achievable,
                 "bmi": d.bmi, "weight_kg": d.weight_kg,
                 "vigorous_min": d.vigorous_min_avg, "vigorous_days": d.vigorous_days_avg},
        "synced_at": d.synced_at.isoformat() if d.synced_at else None,
    }


def _treino_para_dict(a: GarminActivity) -> dict[str, Any]:
    return {
        "id": a.activity_id, "date": a.date.isoformat(),
        "start": a.start_time.isoformat() if a.start_time else None,
        "auto": bool(a.auto),
        "type": a.type, "name": a.name,
        "duration_s": a.duration_s, "distance_m": a.distance_m,
        "calories": a.calories, "avg_hr": a.avg_hr, "max_hr": a.max_hr,
        "avg_speed": a.avg_speed, "avg_cadence": a.avg_cadence, "avg_power": a.avg_power,
        "aerobic_te": a.aerobic_te, "anaerobic_te": a.anaerobic_te,
        "location": a.location, "lat": a.lat, "lon": a.lon,
    }


def _snapshot_para_dict(s: GarminSnapshot) -> dict[str, Any]:
    return {
        "uuid": s.uuid, "date": s.date.isoformat(),
        "start": s.start_time.isoformat() if s.start_time else None,
        "duration_s": s.duration_s, "name": s.name, "device": s.device,
        "hr_avg": s.hr_avg, "hr_min": s.hr_min, "hr_max": s.hr_max,
        "hrv_rmssd": s.hrv_rmssd, "hrv_sdrr": s.hrv_sdrr,
        "spo2_avg": s.spo2_avg, "spo2_min": s.spo2_min,
        "resp_avg": s.resp_avg, "resp_max": s.resp_max,
        "stress_avg": s.stress_avg, "stress_max": s.stress_max,
    }


def _com_ultimo_peso(db: Session, dia: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Nos dias em que não se pesou, mostra-se o último peso conhecido e a data.

    Ele pesa-se de vez em quando, não todos os dias — deixar o campo vazio era
    esconder um número que existe."""
    if not dia or dia["body"]["weight_kg"] is not None:
        return dia
    ultimo = (db.query(GarminDay.date, GarminDay.weight_kg)
              .filter(GarminDay.weight_kg.isnot(None), GarminDay.date <= dia["date"])
              .order_by(GarminDay.date.desc()).first())
    if ultimo:
        dia["body"]["weight_kg"] = ultimo[1]
        dia["body"]["weight_date"] = ultimo[0].isoformat()
    return dia


def _snapshots_do_dia(db: Session, quando: _date) -> list[dict[str, Any]]:
    linhas = (db.query(GarminSnapshot).filter(GarminSnapshot.date == quando)
              .order_by(GarminSnapshot.start_time.desc()).all())
    return [_snapshot_para_dict(s) for s in linhas]


VAZIO: dict[str, list] = {"stress": [], "body_battery": [], "hr": [], "steps": [], "events": []}


def _series(db: Session, quando: _date) -> dict[str, list]:
    linha = db.query(GarminSeries).filter(GarminSeries.date == quando).first()
    if linha is None:
        return dict(VAZIO)

    def carrega(txt: Optional[str]) -> list:
        try:
            return json.loads(txt or "[]")
        except (ValueError, TypeError):
            return []

    return {"stress": carrega(linha.stress_json),
            "body_battery": carrega(linha.body_battery_json),
            "hr": carrega(linha.hr_json),
            "steps": carrega(linha.steps_json),
            "events": carrega(linha.events_json)}


def _zonas_fc(series: dict[str, list]) -> Optional[dict[str, Any]]:
    """Os limiares das zonas e quanto tempo do dia esteve em cada uma.

    Sem os limiares, 140 bpm no gráfico é um número solto. Os minutos saem das
    próprias leituras: cada amostra vale o tempo até à seguinte, com tecto de 5
    minutos para um buraco (relógio fora do pulso) não virar meia hora em zona 1.
    """
    import cache
    import garmin_sync
    zonas = cache.cache_get(garmin_sync.CHAVE_ZONAS_FC)
    if not isinstance(zonas, dict) or not zonas.get("floors"):
        return None

    pisos: list[int] = zonas["floors"]
    minutos = [0.0] * (len(pisos) + 1)                 # índice 0 = abaixo da zona 1
    pontos = series.get("hr") or []
    for i, (ts, bpm) in enumerate(pontos):
        seguinte = pontos[i + 1][0] if i + 1 < len(pontos) else ts
        dt = min(max((seguinte - ts) / 60000, 0), 5)
        zona = sum(1 for piso in pisos if bpm >= piso)
        minutos[zona] += dt
    return {**zonas, "minutes": [round(m) for m in minutos]}


def _cobertura(series: dict[str, list]) -> dict[str, Any]:
    """Até que horas é que a Garmin tem mesmo leituras deste dia.

    É o que explica uma noite sem sono, e distingue os dois casos que se parecem:
    leituras paradas há horas com o dia a decorrer significa que o relógio ainda
    não passou pelo telemóvel — os dados existem, estão é no pulso. Leituras que
    param a meio de uma noite já passada é que são relógio fora do pulso."""
    from datetime import datetime as _dt
    pontos = series.get("hr") or series.get("body_battery") or []
    if not pontos:
        return {"from": None, "to": None, "readings": 0, "hours_ago": None}
    ultimo = _dt.fromtimestamp(pontos[-1][0] / 1000)
    return {
        "from": _dt.fromtimestamp(pontos[0][0] / 1000).isoformat(),
        "to": ultimo.isoformat(),
        "readings": len(pontos),
        "hours_ago": round((_dt.now() - ultimo).total_seconds() / 3600, 1),
    }


@router.get("/status")
def estado(db: Session = Depends(get_db)):
    """Se o relógio está ligado, o que falta para as métricas lentas aparecerem.

    O HRV e a prontidão só existem depois de ~19 noites com o relógio no pulso.
    Dizer quantas faltam é mais honesto do que mostrar uma caixa vazia."""
    import cache
    import garmin_sync
    ultimo = db.query(GarminDay).order_by(GarminDay.date.desc()).first()
    noites = db.query(GarminDay).filter(GarminDay.sleep_hours.isnot(None)).count()
    tem_hrv = db.query(GarminDay).filter(GarminDay.hrv_last_night.isnot(None)).count() > 0
    # Quando o relógio falou com o telemóvel pela última vez. É o número que
    # interessa quando os dados parecem parados: se este está velho, o problema
    # está entre o pulso e o telefone, não entre a app e a Garmin.
    carimbo = cache.cache_get(garmin_sync.CHAVE_ULTIMO_UPLOAD)
    return {
        "watch_synced_at": (datetime.fromtimestamp(carimbo / 1000).isoformat()
                            if isinstance(carimbo, (int, float)) else None),
        "connected": garmin_api.tem_token(),
        "enabled": garmin_api.activo(),
        "last_day": ultimo.date.isoformat() if ultimo else None,
        "last_sync": ultimo.synced_at.isoformat() if (ultimo and ultimo.synced_at) else None,
        "nights": noites,
        "nights_for_hrv": max(0, garmin_api.NOITES_PARA_BASELINE_HRV - noites),
        "has_hrv": tem_hrv,
        "days": db.query(GarminDay).count(),
        "activities": db.query(GarminActivity).count(),
    }


@router.get("/today")
def hoje(db: Session = Depends(get_db)):
    """O estado agora. Cai para ontem quando o dia ainda não sincronizou."""
    hoje_ = _date.today()
    dia = db.query(GarminDay).filter(GarminDay.date == hoje_).first()
    if dia is None:
        dia = db.query(GarminDay).order_by(GarminDay.date.desc()).first()
    if dia is None:
        return {"day": None, "series": dict(VAZIO),
                "coverage": {"from": None, "to": None, "readings": 0, "hours_ago": None},
                "hr_zones": None,
                "activities": [], "snapshots": [], "stale": True, "prev": None, "next": None}
    treinos = (db.query(GarminActivity)
               .filter(GarminActivity.date == dia.date)
               .order_by(GarminActivity.start_time.desc()).all())
    series = _series(db, dia.date)
    return {
        "day": _com_ultimo_peso(db, _dia_para_dict(dia)),
        "series": series,
        "coverage": _cobertura(series),
        "hr_zones": _zonas_fc(series),
        "activities": [_treino_para_dict(a) for a in treinos],
        "snapshots": _snapshots_do_dia(db, dia.date),
        "stale": dia.date != hoje_,
        **_vizinhos(db, dia.date),
    }


def _vizinhos(db: Session, quando: _date) -> dict[str, Any]:
    """Os dias com dados imediatamente antes e depois, para as setas da página."""
    anterior = (db.query(GarminDay.date).filter(GarminDay.date < quando)
                .order_by(GarminDay.date.desc()).first())
    seguinte = (db.query(GarminDay.date).filter(GarminDay.date > quando)
                .order_by(GarminDay.date).first())
    return {"prev": anterior[0].isoformat() if anterior else None,
            "next": seguinte[0].isoformat() if seguinte else None}


@router.get("/day/{quando}")
def um_dia(quando: _date, db: Session = Depends(get_db)):
    dia = db.query(GarminDay).filter(GarminDay.date == quando).first()
    if dia is None:
        raise HTTPException(404, "sem dados do relógio nesse dia")
    treinos = (db.query(GarminActivity)
               .filter(GarminActivity.date == quando)
               .order_by(GarminActivity.start_time.desc()).all())
    series = _series(db, quando)
    return {"day": _com_ultimo_peso(db, _dia_para_dict(dia)), "series": series,
            "coverage": _cobertura(series),
            "hr_zones": _zonas_fc(series),
            "activities": [_treino_para_dict(a) for a in treinos],
            "snapshots": _snapshots_do_dia(db, quando),
            "stale": quando != _date.today(),
            **_vizinhos(db, quando)}


def _sestas_por_dia(db: Session, desde: _date) -> dict[_date, list[dict[str, Any]]]:
    """As sestas de cada dia, com hora e duração.

    O `nap_min` do dia só diz o total — quem sabe a que horas ele dormiu são os
    eventos do body battery, que é o único sítio onde a sesta existe."""
    saida: dict[_date, list[dict[str, Any]]] = {}
    linhas = (db.query(GarminSeries)
              .filter(GarminSeries.date >= desde, GarminSeries.events_json.isnot(None)).all())
    for linha in linhas:
        try:
            blocos = json.loads(linha.events_json or "[]")
        except (ValueError, TypeError):
            continue
        sestas = [{"start": b["start"], "end": b["end"],
                   "min": round((b["end"] - b["start"]) / 60000),
                   "impact": b.get("impact")}
                  for b in blocos
                  if isinstance(b, dict) and b.get("kind") == "sesta"
                  and b.get("start") and b.get("end")]
        if sestas:
            saida[linha.date] = sestas
    return saida


# Uma média móvel de 7 dias no primeiro dia da janela precisa dos 6 dias
# anteriores a ela. Lêem-se, usam-se para a conta, e não se devolvem.
JANELA_MOVEL = 7
MINIMO_NA_JANELA = 3


def _media_movel(valores: list[Optional[float]], i: int) -> Optional[float]:
    janela = [v for v in valores[max(0, i - JANELA_MOVEL + 1): i + 1] if v is not None]
    if len(janela) < MINIMO_NA_JANELA:
        return None
    return round(sum(janela) / len(janela), 1)


def _intensidade_da_semana(linhas: list[GarminDay], i: int) -> Optional[int]:
    """Os minutos de intensidade dos últimos 7 dias, como a Garmin os conta:
    um minuto vigoroso vale por dois moderados."""
    janela = [d for d in linhas[max(0, i - JANELA_MOVEL + 1): i + 1]
              if d.intensity_moderate_min is not None or d.intensity_vigorous_min is not None]
    if len(janela) < 4:
        return None
    return sum((d.intensity_moderate_min or 0) + 2 * (d.intensity_vigorous_min or 0)
               for d in janela)


@router.get("/history")
def historico(days: int = Query(30, ge=7, le=365), db: Session = Depends(get_db)):
    desde = _date.today() - timedelta(days=days)
    # Os dias a mais são só para as médias móveis — saem antes de responder.
    linhas = (db.query(GarminDay)
              .filter(GarminDay.date >= desde - timedelta(days=JANELA_MOVEL - 1))
              .order_by(GarminDay.date).all())
    sestas = _sestas_por_dia(db, desde)
    hrvs = [d.hrv_last_night for d in linhas]
    fcs = [d.resting_hr for d in linhas]
    return [{
        "date": d.date.isoformat(),
        "sleep_hours": d.sleep_hours, "sleep_score": d.sleep_score,
        "sleep_need_min": d.sleep_need_min, "awake_count": d.awake_count,
        "avg_sleep_stress": d.avg_sleep_stress, "resp_avg": d.resp_avg,
        "nap_min": d.nap_min, "naps": sestas.get(d.date, []),
        "deep_min": d.deep_min, "light_min": d.light_min, "rem_min": d.rem_min,
        "awake_min": d.awake_min,
        "hrv": d.hrv_last_night, "hrv_status": d.hrv_status,
        "hrv_weekly_avg": d.hrv_weekly_avg, "hrv_avg7": _media_movel(hrvs, i),
        "resting_hr": d.resting_hr, "rhr_avg7": _media_movel(fcs, i),
        "hr_min": d.hr_min, "hr_max": d.hr_max,
        "bb_start": d.bb_start, "bb_end": d.bb_end, "bb_min": d.bb_min, "bb_max": d.bb_max,
        "bb_charged": d.bb_charged, "bb_drained": d.bb_drained,
        "stress_avg": d.stress_avg, "stress_max": d.stress_max,
        "stress_rest_min": d.stress_rest_min, "stress_low_min": d.stress_low_min,
        "stress_medium_min": d.stress_medium_min, "stress_high_min": d.stress_high_min,
        "steps": d.steps, "step_goal": d.step_goal,
        "distance_m": d.distance_m, "calories": d.calories,
        "active_calories": d.active_calories,
        "moderate_min": d.intensity_moderate_min, "vigorous_min": d.intensity_vigorous_min,
        "intensity_7d": _intensidade_da_semana(linhas, i),
        "readiness": d.training_readiness, "recovery_min": d.recovery_min,
        "vo2max": d.vo2max,
        "fitness_age": d.fitness_age, "weight_kg": d.weight_kg,
    } for i, d in enumerate(linhas) if d.date >= desde]


@router.get("/baselines")
def reguas(days: int = Query(30, ge=7, le=365), db: Session = Depends(get_db)):
    """A faixa do costume dele em cada métrica, para os gráficos terem régua.

    Sem ela, sete barras não dizem qual é o dia acima do costume — e abaixo de
    `min_days` noites medidas não se desenha faixa nenhuma, para não inventar
    uma régua a partir de três dias."""
    import garmin_insights
    return garmin_insights.baselines(db, dias=days)


@router.get("/activities")
def treinos(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    desde = _date.today() - timedelta(days=days)
    linhas = (db.query(GarminActivity)
              .filter(GarminActivity.date >= desde)
              .order_by(GarminActivity.start_time.desc()).all())
    return [_treino_para_dict(a) for a in linhas]


@router.get("/reading")
def leitura_do_dia(date: Optional[_date] = Query(None), db: Session = Depends(get_db)):
    """O que se destaca no dia, em frases.

    Os números saem das réguas dele (a mediana das próprias noites, não uma
    tabela de referência); o modelo local só escolhe o tema e escreve a ligação.
    Está à parte do resto da página porque é a única coisa aqui que espera por
    um modelo."""
    import garmin_insights
    quando = date or _date.today()
    if db.query(GarminDay).filter(GarminDay.date == quando).first() is None:
        ultimo = db.query(GarminDay).order_by(GarminDay.date.desc()).first()
        if ultimo is None:
            return {"date": quando.isoformat(), "facts": [], "relations": [], "theme": None,
                    "headline": "", "text": "", "source": "vazio",
                    "days_measured": 0, "days_for_baseline": garmin_insights.MINIMO_BASELINE,
                    "days_for_relations": garmin_insights.MINIMO_PARES}
        quando = ultimo.date
    return garmin_insights.analise(db, quando)


@router.get("/snapshots")
def health_snapshots(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    desde = _date.today() - timedelta(days=days)
    linhas = (db.query(GarminSnapshot).filter(GarminSnapshot.date >= desde)
              .order_by(GarminSnapshot.start_time.desc()).all())
    return [_snapshot_para_dict(s) for s in linhas]


@router.post("/sync")
def sincronizar(days: int = Query(2, ge=1, le=28), db: Session = Depends(get_db)):
    if not garmin_api.tem_token():
        raise HTTPException(
            400,
            "sem ligação à conta Garmin — correr `python scripts/garmin_login.py` no backend",
        )
    try:
        return garmin_sync.sincroniza(dias=days, db=db)
    except garmin_api.GarminIndisponivel as e:
        raise HTTPException(503, str(e)) from e
