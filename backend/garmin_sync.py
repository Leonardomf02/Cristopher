"""Traz o que o relógio mediu para dentro da app.

Uma passagem trata sempre hoje e ontem (o dia de ontem só fica completo depois de
o telemóvel sincronizar) mais os dias que faltem na última semana. Tudo é upsert
por data, por isso correr duas vezes seguidas não duplica nada.

O sono é o caso especial: até agora era **adivinhado** pelo buraco de actividade
no Mac. Aqui passa a ser medido, e entra em `sleep_entries` com
`source='garmin'` — mas nunca por cima de uma noite que ele tenha escrito à mão.
"""
from __future__ import annotations

import json
import logging
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import cache
import garmin_api
from database import SessionLocal
from models import (GarminActivity, GarminDay, GarminSeries, GarminSnapshot, Habit,
                    HabitCompletion, SleepEntry)

logger = logging.getLogger(__name__)

# Fontes de sono que o relógio pode substituir. Uma noite `manual` é dele e fica.
FONTES_SUBSTITUIVEIS = {"auto", "power", "garmin", "", None}

# Notas que a app escreveu sozinha — essas podem ir; o que ele escreveu fica.
_NOTAS_GERADAS = ("o Mac esteve parado", "estimativa a confirmar")


# ── leitura defensiva ────────────────────────────────────────────
# A Garmin muda campos sem avisar e este relógio não calcula tudo. Nada aqui
# pode rebentar por um campo em falta: o que não vier fica a NULL.

def _g(obj: Any, *caminho: Any) -> Any:
    for k in caminho:
        if obj is None:
            return None
        try:
            obj = obj[k]
        except (KeyError, IndexError, TypeError):
            return None
    return obj


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return None if n != n else n                      # NaN fora


def _int(v: Any) -> Optional[int]:
    n = _num(v)
    return None if n is None else int(round(n))


def _dt(ms: Any) -> Optional[datetime]:
    """Timestamp da Garmin (epoch em milissegundos) para datetime sem fuso.

    Os campos `...Local` já vêm deslocados para a hora dele, por isso lêem-se
    como se fossem UTC — é assim que dão a hora que aparece no relógio."""
    n = _num(ms)
    if not n:
        return None
    try:
        return datetime.fromtimestamp(n / 1000, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def _minutos(segundos: Any) -> Optional[int]:
    n = _num(segundos)
    return None if n is None else int(round(n / 60))


def _serie(pares: Any, indice_valor: int = 1) -> list[list[int]]:
    """[[ts, valor], …] só com leituras válidas.

    O stress vem a -1 e -2 quando o relógio não estava a medir (fora do pulso, a
    carregar); esses pontos não são zero, são ausência."""
    saida: list[list[int]] = []
    for p in pares or []:
        if not isinstance(p, (list, tuple)) or len(p) <= indice_valor:
            continue
        ts, valor = _num(p[0]), _num(p[indice_valor])
        if ts is None or valor is None or valor < 0:
            continue
        saida.append([int(ts), int(valor)])
    return saida


# ── um dia ───────────────────────────────────────────────────────

# Se nenhuma destas veio, o relógio não estava com ele nesse dia — e uma linha
# de NULLs só serve para pôr buracos nos gráficos e inflar as contagens.
_SINAIS_DE_VIDA = ("sleep_hours", "steps", "resting_hr", "stress_avg",
                   "bb_end", "hr_max", "calories", "hrv_last_night")


def tem_medicao(linha: GarminDay) -> bool:
    return any(getattr(linha, c) is not None for c in _SINAIS_DE_VIDA)


def grava_dia(db, quando: _date, cru: dict[str, Any]) -> Optional[GarminDay]:
    """Devolve a linha do dia, ou None quando não há nada medido nesse dia."""
    linha = db.query(GarminDay).filter(GarminDay.date == quando).first()
    nova = linha is None
    if nova:
        linha = GarminDay(date=quando)
        db.add(linha)

    sono = _g(cru, "sono") or {}
    dto = _g(sono, "dailySleepDTO") or {}
    notas = _g(sono, "sleepScores") or _g(dto, "sleepScores") or {}
    hrv = _g(cru, "hrv", "hrvSummary") or {}
    stress = _g(cru, "stress") or {}
    resumo = _g(cru, "resumo") or {}
    fc = _g(cru, "fc") or {}
    prontidao = _g(cru, "prontidao")
    if isinstance(prontidao, list):
        prontidao = prontidao[0] if prontidao else {}
    prontidao = prontidao or {}
    estado = _g(cru, "estado_treino") or {}

    # Sono
    inicio = _dt(_g(dto, "sleepStartTimestampLocal")) or _dt(_g(dto, "sleepStartTimestampGMT"))
    fim = _dt(_g(dto, "sleepEndTimestampLocal")) or _dt(_g(dto, "sleepEndTimestampGMT"))
    segundos = _num(_g(dto, "sleepTimeSeconds"))
    linha.sleep_start = inicio
    linha.sleep_end = fim
    linha.sleep_hours = round(segundos / 3600, 2) if segundos else None
    linha.deep_min = _minutos(_g(dto, "deepSleepSeconds"))
    linha.light_min = _minutos(_g(dto, "lightSleepSeconds"))
    linha.rem_min = _minutos(_g(dto, "remSleepSeconds"))
    linha.awake_min = _minutos(_g(dto, "awakeSleepSeconds"))
    linha.nap_min = _minutos(_g(dto, "napTimeSeconds"))
    linha.awake_count = _int(_g(dto, "awakeCount"))
    linha.sleep_score = _int(_g(notas, "overall", "value"))
    linha.sleep_qualifier = _g(notas, "overall", "qualifierKey")
    linha.sleep_need_min = _int(_g(sono, "sleepNeed", "baseline")) or _int(_g(dto, "sleepNeed", "baseline"))
    linha.sleep_feedback = _g(dto, "sleepScoreFeedback") or _g(sono, "sleepNeed", "feedback")
    linha.avg_sleep_stress = _num(_g(dto, "avgSleepStress"))
    linha.spo2_avg = _num(_g(dto, "averageSpO2Value")) or _num(_g(resumo, "averageSpo2"))
    linha.spo2_min = _num(_g(dto, "lowestSpO2Value")) or _num(_g(resumo, "lowestSpo2"))
    linha.resp_avg = _num(_g(dto, "averageRespirationValue"))
    linha.skin_temp_dev_c = _num(_g(sono, "avgSkinTempDeviationC"))

    # Recuperação
    linha.resting_hr = (_int(_g(sono, "restingHeartRate"))
                        or _int(_g(fc, "restingHeartRate"))
                        or _int(_g(resumo, "restingHeartRate")))
    linha.hrv_last_night = _int(_g(hrv, "lastNightAvg"))
    linha.hrv_5min_high = _int(_g(hrv, "lastNight5MinHigh"))
    linha.hrv_weekly_avg = _int(_g(hrv, "weeklyAvg"))
    linha.hrv_status = _g(hrv, "status")
    linha.hrv_baseline_low = _int(_g(hrv, "baseline", "balancedLow"))
    linha.hrv_baseline_high = _int(_g(hrv, "baseline", "balancedUpper"))
    linha.hrv_feedback = _g(hrv, "feedbackPhrase")

    # Body Battery
    bb = _serie(_g(stress, "bodyBatteryValuesArray"), indice_valor=2)
    niveis = [v for _, v in bb]
    linha.bb_start = _nivel_ao_acordar(bb, fim) if fim else (niveis[0] if niveis else None)
    linha.bb_end = niveis[-1] if niveis else _int(_g(resumo, "bodyBatteryMostRecentValue"))
    linha.bb_min = min(niveis) if niveis else _int(_g(resumo, "bodyBatteryLowestValue"))
    linha.bb_max = max(niveis) if niveis else _int(_g(resumo, "bodyBatteryHighestValue"))
    linha.bb_charged = _int(_g(resumo, "bodyBatteryChargedValue"))
    linha.bb_drained = _int(_g(resumo, "bodyBatteryDrainedValue"))

    # Stress
    linha.stress_avg = _int(_g(stress, "avgStressLevel")) or _int(_g(resumo, "averageStressLevel"))
    linha.stress_max = _int(_g(stress, "maxStressLevel")) or _int(_g(resumo, "maxStressLevel"))
    linha.stress_rest_min = _minutos(_g(resumo, "restStressDuration"))
    linha.stress_low_min = _minutos(_g(resumo, "lowStressDuration"))
    linha.stress_medium_min = _minutos(_g(resumo, "mediumStressDuration"))
    linha.stress_high_min = _minutos(_g(resumo, "highStressDuration"))

    # Actividade
    linha.steps = _int(_g(resumo, "totalSteps"))
    linha.step_goal = _int(_g(resumo, "dailyStepGoal"))
    linha.distance_m = _num(_g(resumo, "totalDistanceMeters"))
    linha.calories = _int(_g(resumo, "totalKilocalories"))
    linha.active_calories = _int(_g(resumo, "activeKilocalories"))
    linha.intensity_moderate_min = _int(_g(resumo, "moderateIntensityMinutes"))
    linha.intensity_vigorous_min = _int(_g(resumo, "vigorousIntensityMinutes"))
    linha.hr_min = _int(_g(fc, "minHeartRate")) or _int(_g(resumo, "minHeartRate"))
    linha.hr_max = _int(_g(fc, "maxHeartRate")) or _int(_g(resumo, "maxHeartRate"))

    # Treino
    linha.training_readiness = _int(_g(prontidao, "score"))
    linha.readiness_level = _g(prontidao, "level")
    linha.readiness_feedback = _g(prontidao, "feedbackLong") or _g(prontidao, "feedbackShort")
    linha.recovery_min = _int(_g(prontidao, "recoveryTime"))
    linha.acute_load = _num(_g(prontidao, "acuteLoad"))
    linha.vo2max = _num(_g(estado, "mostRecentVO2Max", "generic", "vo2MaxValue"))
    linha.training_status = _estado_de_treino(estado)
    if linha.acute_load is None:
        linha.acute_load = _num(_g(_ultimo_por_aparelho(estado), "acuteTrainingLoadDTO", "dailyTrainingLoadAcute"))

    # Porque é que a prontidão deu aquilo: o peso de cada factor. Vem a zero
    # enquanto não houver linha de base, e nessa altura fica a NULL em vez de 0.
    manha = _g(cru, "prontidao_manha") or {}
    for coluna, chave in (("readiness_sleep_pct", "sleepScoreFactorPercent"),
                          ("readiness_hrv_pct", "hrvFactorPercent"),
                          ("readiness_recovery_pct", "recoveryTimeFactorPercent"),
                          ("readiness_load_pct", "acwrFactorPercent"),
                          ("readiness_stress_pct", "stressHistoryFactorPercent")):
        valor = _int(_g(manha, chave))
        setattr(linha, coluna, valor or None)

    idade = _g(cru, "idade") or {}
    linha.fitness_age = _num(_g(idade, "fitnessAge"))
    linha.fitness_age_achievable = _num(_g(idade, "achievableFitnessAge"))
    linha.vigorous_min_avg = _num(_g(idade, "components", "vigorousMinutesAvg", "value"))
    linha.vigorous_days_avg = _num(_g(idade, "components", "vigorousDaysAvg", "value"))
    linha.bmi = _num(_g(idade, "components", "bmi", "value"))

    linha.weight_kg = _peso_do_dia(_g(cru, "peso"))

    if not tem_medicao(linha):
        if nova:
            db.expunge(linha)
        return None

    linha.synced_at = datetime.now()
    return linha


def _nivel_ao_acordar(bb: list[list[int]], fim_do_sono: datetime) -> Optional[int]:
    """Body battery no instante em que ele acordou.

    Não é a primeira leitura do dia: quem se deita às 2h já gastou bateria depois
    da meia-noite, e o valor da meia-noite não é "com quanto acordou".

    Cuidado com o tempo aqui, que já deu erro: as horas de sono vêm dos campos
    `...Local` da Garmin, que são epoch **deslocado** e por isso se lêem como
    hora de parede; as séries vêm em epoch verdadeiro. Comparar os dois em cru
    dava o valor uma hora ao lado no Verão — 80 em vez dos 93 com que acordou.
    Por isso passa-se tudo para hora de parede antes de comparar.
    """
    if not bb:
        return None
    alvo = fim_do_sono
    melhor = min(bb, key=lambda p: abs(datetime.fromtimestamp(p[0] / 1000) - alvo))
    distancia = abs(datetime.fromtimestamp(melhor[0] / 1000) - alvo)
    return melhor[1] if distancia <= timedelta(minutes=30) else None


def _ultimo_por_aparelho(estado: dict[str, Any]) -> dict[str, Any]:
    """O estado de treino vem numa gaveta por id de aparelho — só há um relógio."""
    por_aparelho = _g(estado, "mostRecentTrainingStatus", "latestTrainingStatusData")
    if isinstance(por_aparelho, dict) and por_aparelho:
        return next(iter(por_aparelho.values())) or {}
    return {}


def _estado_de_treino(estado: dict[str, Any]) -> Optional[str]:
    d = _ultimo_por_aparelho(estado)
    return (_g(d, "trainingStatusFeedbackPhrase")
            or _g(d, "trainingStatus")
            or _g(estado, "mostRecentTrainingStatus", "trainingStatus"))


def _peso_do_dia(bruto: Any) -> Optional[float]:
    """Peso em quilos, ou None nos dias em que não se pesou.

    Vem em gramas, e num dia pode haver mais do que uma pesagem — vale a última,
    que é a que corrige as anteriores (ele registou 74 e 88 kg no mesmo dia)."""
    pesagens = [p for p in (_g(bruto, "dateWeightList") or []) if _num(_g(p, "weight"))]
    if pesagens:
        ultima = max(pesagens, key=lambda p: _num(_g(p, "date")) or 0)
        return round(_num(_g(ultima, "weight")) / 1000, 1)
    media = _num(_g(bruto, "totalAverage", "weight"))
    return round(media / 1000, 1) if media else None


def _passos_por_quarto_de_hora(bruto: Any) -> list[list[int]]:
    """Passos ao longo do dia, de 15 em 15 minutos.

    Vem como lista de blocos com hora de início em texto, não como os pares
    [instante, valor] das outras séries — aqui é convertido para o mesmo
    formato, para o gráfico não ter de saber de dois feitios."""
    saida: list[list[int]] = []
    for bloco in bruto or []:
        inicio = _texto_para_dt(_g(bloco, "startGMT")) or _texto_para_dt(_g(bloco, "startTimeGMT"))
        passos = _int(_g(bloco, "steps"))
        if inicio is None or passos is None:
            continue
        saida.append([int(inicio.replace(tzinfo=timezone.utc).timestamp() * 1000), passos])
    return saida


def _ms(dt_: Optional[datetime]) -> Optional[int]:
    return None if dt_ is None else int(dt_.replace(tzinfo=timezone.utc).timestamp() * 1000)


# O que a Garmin chama a cada bloco da linha do dia, e o nome que a app usa.
_TIPOS_DE_EVENTO = {"SLEEP": "sono", "NAP": "sesta", "ACTIVITY": "movimento"}


def linha_do_dia(cru: dict[str, Any]) -> list[dict[str, Any]]:
    """Os blocos do dia: dormir, sestas e movimento, com início e fim.

    A hora a que ele acordou e a sesta da tarde não estão em campo nenhum do
    sono — vêm dos eventos que explicam as subidas do body battery. E uma
    caminhada que o relógio detectou sozinho não é uma actividade gravada: sai
    do Move IQ, que é outro endereço.
    """
    blocos: list[dict[str, Any]] = []

    for e in _g(cru, "eventos") or []:
        ev = _g(e, "event") or {}
        tipo = _TIPOS_DE_EVENTO.get(str(_g(ev, "eventType") or "").upper())
        inicio = _ms(_texto_para_dt(_g(ev, "eventStartTimeGmt")))
        duracao = _num(_g(ev, "durationInMilliseconds"))
        if not tipo or inicio is None or not duracao:
            continue
        blocos.append({"kind": tipo, "start": inicio, "end": inicio + int(duracao),
                       "impact": _int(_g(ev, "bodyBatteryImpact")),
                       "name": _g(e, "activityName") or "",
                       "type": _g(e, "activityType") or ""})

    for m in _g(cru, "movimentos") or []:
        inicio = _ms(_texto_para_dt(_g(m, "startTimestampGMT")))
        fim = _ms(_texto_para_dt(_g(m, "endTimestampGMT")))
        if inicio is None:
            continue
        if fim is None:
            # `duration` do Move IQ vem em minutos, ao contrário das actividades
            # gravadas, onde é em segundos.
            minutos_ = _num(_g(m, "duration")) or 0
            fim = inicio + int(minutos_ * 60_000)
        blocos.append({"kind": "movimento", "start": inicio, "end": fim, "auto": True,
                       "type": _g(m, "activityType") or "", "name": ""})

    blocos.sort(key=lambda b: b["start"])
    return blocos


def grava_series(db, quando: _date, cru: dict[str, Any]) -> None:
    stress = _g(cru, "stress") or {}
    fc = _g(cru, "fc") or {}
    valores = {
        "stress_json": _serie(_g(stress, "stressValuesArray")),
        "body_battery_json": _serie(_g(stress, "bodyBatteryValuesArray"), indice_valor=2),
        "hr_json": _serie(_g(fc, "heartRateValues")),
        "steps_json": _passos_por_quarto_de_hora(_g(cru, "passos")),
        "events_json": linha_do_dia(cru),
    }
    if not any(valores.values()):
        return                                        # dia sem relógio: nada a guardar
    linha = db.query(GarminSeries).filter(GarminSeries.date == quando).first()
    if linha is None:
        linha = GarminSeries(date=quando)
        db.add(linha)
    for coluna, serie in valores.items():
        setattr(linha, coluna, json.dumps(serie))


# ── treinos ──────────────────────────────────────────────────────

def grava_actividades(db, brutas: Iterable[dict[str, Any]]) -> int:
    novas = 0
    for a in brutas or []:
        aid = str(_g(a, "activityId") or "")
        if not aid:
            continue
        inicio = _texto_para_dt(_g(a, "startTimeLocal")) or _texto_para_dt(_g(a, "startTimeGMT"))
        if inicio is None:
            continue
        linha = db.query(GarminActivity).filter(GarminActivity.activity_id == aid).first()
        if linha is None:
            linha = GarminActivity(activity_id=aid)
            db.add(linha)
            novas += 1
        linha.date = inicio.date()
        linha.start_time = inicio
        linha.type = _g(a, "activityType", "typeKey") or ""
        linha.name = _g(a, "activityName") or ""
        linha.duration_s = _num(_g(a, "duration"))
        linha.distance_m = _num(_g(a, "distance"))
        linha.calories = _int(_g(a, "calories"))
        linha.avg_hr = _int(_g(a, "averageHR"))
        linha.max_hr = _int(_g(a, "maxHR"))
        linha.avg_speed = _num(_g(a, "averageSpeed"))
        linha.avg_cadence = _num(_g(a, "averageRunningCadenceInStepsPerMinute")) or _num(_g(a, "averageBikingCadenceInRevPerMinute"))
        linha.avg_power = _num(_g(a, "avgPower"))
        linha.aerobic_te = _num(_g(a, "aerobicTrainingEffect"))
        linha.anaerobic_te = _num(_g(a, "anaerobicTrainingEffect"))
        linha.location = _g(a, "locationName") or ""
        linha.lat = _num(_g(a, "startLatitude"))
        linha.lon = _num(_g(a, "startLongitude"))
        linha.auto = False
    return novas


def grava_movimentos(db, quando: _date, cru: dict[str, Any]) -> int:
    """Os movimentos que o relógio detectou sozinho (Move IQ).

    Uma caminhada de 25 minutos aparece na app da Garmin e não em
    `get_activities_by_date` — sem isto, a app dizia que o dia não teve nada. O
    identificador é feito da hora de início, porque estes eventos não trazem um."""
    novos = 0
    for m in _g(cru, "movimentos") or []:
        inicio = _texto_para_dt(_g(m, "startTimestampLocal")) or _texto_para_dt(_g(m, "startTimestampGMT"))
        if inicio is None:
            continue
        tipo = _g(m, "activityType") or "movimento"
        aid = f"moveiq-{int(inicio.timestamp())}-{tipo}"
        linha = db.query(GarminActivity).filter(GarminActivity.activity_id == aid).first()
        if linha is None:
            linha = GarminActivity(activity_id=aid)
            db.add(linha)
            novos += 1
        fim = _texto_para_dt(_g(m, "endTimestampLocal"))
        linha.date = inicio.date()
        linha.start_time = inicio
        linha.auto = True
        linha.type = tipo
        linha.name = ""
        # `duration` do Move IQ vem em minutos; as actividades gravadas trazem
        # segundos no mesmo campo.
        linha.duration_s = ((fim - inicio).total_seconds() if fim
                            else (_num(_g(m, "duration")) or 0) * 60)
    return novos


# ── o hábito do gym ──────────────────────────────────────────────
# Um treino de ginásio no relógio é o gym feito: marcá-lo à mão era repetir o que
# o relógio já disse. Cada treino só passa por aqui uma vez (`habit_checked`), por
# isso um gym desmarcado à mão fica desmarcado.

TIPOS_DE_GINASIO = {"strength_training", "indoor_cardio", "hiit", "fitness_equipment",
                    "indoor_cycling", "elliptical", "indoor_rowing", "stair_climbing"}
_NOMES_DE_GYM = ("gym", "ginásio", "ginasio", "muscula")
# Abaixo disto é o aquecimento gravado à parte ou um treino começado sem querer.
MINIMO_GYM_S = 15 * 60
def marca_gym(db) -> int:
    """Marca o hábito do gym nos dias com treino de ginásio. Devolve quantos marcou."""
    habitos = [h for h in db.query(Habit).filter(Habit.active == True).all()
               if any(p in (h.name or "").lower() for p in _NOMES_DE_GYM)]
    if not habitos:
        return 0
    treinos = (db.query(GarminActivity)
               .filter(GarminActivity.habit_checked.isnot(True))
               .order_by(GarminActivity.start_time).all())
    # A musculação primeiro: a bicicleta de aquecimento do mesmo dia não é o treino.
    treinos.sort(key=lambda t: (t.type or "").lower() != "strength_training")
    feitos = {(c.habit_id, c.date) for c in db.query(HabitCompletion).filter(
        HabitCompletion.habit_id.in_([h.id for h in habitos]),
        HabitCompletion.date.in_({t.date for t in treinos}))}
    marcados = 0
    for t in treinos:
        if (t.type or "").lower() not in TIPOS_DE_GINASIO or (t.duration_s or 0) < MINIMO_GYM_S:
            continue
        fim = t.start_time + timedelta(seconds=t.duration_s) if t.start_time else None
        minutos = int(t.duration_s // 60)
        nota = f"pelo relógio: {t.name or t.type}, {minutos // 60}h{minutos % 60:02d}"
        for h in habitos:
            if (h.id, t.date) not in feitos:
                feitos.add((h.id, t.date))
                db.add(HabitCompletion(habit_id=h.id, date=t.date, notes=nota,
                                       completed_at=fim.strftime("%H:%M") if fim else "00:00"))
                marcados += 1
        t.habit_checked = True
    return marcados


# O GraphQL devolve cada medida numa lista de resumos, não em campos próprios.
_MEDIDAS = {
    "HEART_RATE": (("hr_avg", "avgValue"), ("hr_min", "minValue"), ("hr_max", "maxValue")),
    "RESPIRATION": (("resp_avg", "avgValue"), ("resp_max", "maxValue")),
    "STRESS": (("stress_avg", "avgValue"), ("stress_max", "maxValue")),
    "SPO2": (("spo2_avg", "avgValue"), ("spo2_min", "minValue")),
    "RMSSD_HRV": (("hrv_rmssd", "avgValue"),),
    "SDRR_HRV": (("hrv_sdrr", "avgValue"),),
}


def grava_snapshots(db, brutos: Iterable[dict[str, Any]]) -> int:
    novos = 0
    for s in brutos or []:
        uuid = _g(s, "activityUuid", "uuid")
        inicio = _texto_para_dt(_g(s, "startTimestampLocal"))
        if not uuid or inicio is None:
            continue
        linha = db.query(GarminSnapshot).filter(GarminSnapshot.uuid == uuid).first()
        if linha is None:
            linha = GarminSnapshot(uuid=uuid)
            db.add(linha)
            novos += 1
        fim = _texto_para_dt(_g(s, "endTimestampLocal"))
        linha.date = inicio.date()
        linha.start_time = inicio
        linha.duration_s = int((fim - inicio).total_seconds()) if fim else None
        linha.name = _g(s, "activityName") or ""
        linha.device = _g(s, "deviceMetaData", "deviceName") or ""
        for medida in _g(s, "summaryTypeDataList") or []:
            for coluna, chave in _MEDIDAS.get(_g(medida, "summaryType") or "", ()):
                valor = _num(_g(medida, chave))
                if valor is not None:
                    setattr(linha, coluna, round(valor, 1))
    return novos


def _texto_para_dt(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v
    if not isinstance(v, str) or not v.strip():
        return None
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(v.strip().replace("Z", ""), formato)
        except ValueError:
            continue
    return None


# ── o sono real entra onde o palpite estava ──────────────────────

def qualidade_do_score(score: Optional[int]) -> Optional[int]:
    """O 1-5 da app a partir do 0-100 do relógio.

    A coluna `quality` estava quase sempre vazia (é subjectiva e ninguém a
    preenche), e o resumo semanal e mensal já a lêem."""
    if score is None:
        return None
    if score >= 90:
        return 5
    if score >= 80:
        return 4
    if score >= 70:
        return 3
    if score >= 60:
        return 2
    return 1


def aplica_sono(db, gd: GarminDay) -> bool:
    """Escreve a noite medida em `sleep_entries`. Devolve True se mexeu."""
    if not gd.sleep_hours or not gd.sleep_start or not gd.sleep_end:
        return False

    entrada = db.query(SleepEntry).filter(SleepEntry.date == gd.date).first()
    if entrada is not None and entrada.source not in FONTES_SUBSTITUIVEIS:
        return False                                   # noite escrita por ele: não se toca

    nota = (entrada.notes or "") if entrada else ""
    if nota.startswith(_NOTAS_GERADAS):
        nota = ""                                      # nota do palpite antigo, já não serve

    valores = dict(
        bedtime=gd.sleep_start.strftime("%H:%M"),
        wake_time=gd.sleep_end.strftime("%H:%M"),
        hours=round(gd.sleep_hours, 2),
        quality=qualidade_do_score(gd.sleep_score),
        notes=nota,
        source="garmin",
    )

    if entrada is None:
        db.add(SleepEntry(date=gd.date, **valores))
        return True

    mudou = any(getattr(entrada, k) != v for k, v in valores.items())
    for k, v in valores.items():
        setattr(entrada, k, v)
    return mudou


# ── orquestração ─────────────────────────────────────────────────

CHAVE_ULTIMO_UPLOAD = "garmin:ultimo_upload"
CHAVE_ULTIMA_LEITURA = "garmin:ultima_leitura_completa"
CHAVE_ZONAS_FC = "garmin:zonas_fc"
# Os treinos vêm só da última semana. Uma vez, vêm todos desde o primeiro dia do
# relógio: os de antes de a NAS sincronizar não estavam na base, e sem eles o
# gym desses dias nunca se marcava.
CHAVE_TREINOS_TODOS = "garmin:treinos_desde_o_inicio"
DIAS_ZONAS_FC = 30

# Mesmo sem o relógio ter passado pelo telemóvel, há coisas que a Garmin calcula
# do lado dela (prontidão, idade de fitness) — de vez em quando lê-se na mesma.
HORAS_ATE_LER_A_FORCA = 6


def ha_coisa_nova() -> tuple[bool, str]:
    """Vale a pena ir buscar tudo? Um pedido em vez de dez.

    O relógio não tem Wi-Fi: só há dados novos depois de ele passar pelo
    telemóvel. Perguntar quando isso aconteceu pela última vez custa um pedido, e
    poupa os outros nove nas vezes em que não mudou nada."""
    agora = datetime.now().timestamp()
    desde_a_ultima = agora - (cache.cache_get(CHAVE_ULTIMA_LEITURA) or 0)
    if desde_a_ultima > HORAS_ATE_LER_A_FORCA * 3600:
        return True, "leitura de rotina"

    carimbo = garmin_api.ultimo_upload()
    if carimbo is None:
        return True, "sem forma de saber"
    if carimbo != cache.cache_get(CHAVE_ULTIMO_UPLOAD):
        quando = datetime.fromtimestamp(carimbo / 1000).strftime("%H:%M")
        return True, f"o relógio sincronizou às {quando}"
    return False, "o relógio não passou pelo telemóvel desde a última vez"


def guarda_zonas_fc() -> Optional[dict[str, Any]]:
    """As zonas só se pedem quando a cache arrefece — é um pedido por mês.

    O router só lê da base, como o resto da página; quem fala com a Garmin é
    esta passagem."""
    zonas = cache.cache_get(CHAVE_ZONAS_FC)
    if zonas is not None:
        return zonas
    try:
        zonas = garmin_api.zonas_fc()
    except Exception as e:                              # pragma: no cover
        logger.debug("garmin: zonas de FC falharam (%s)", e)
        return None
    if zonas:
        cache.cache_set(CHAVE_ZONAS_FC, zonas, DIAS_ZONAS_FC * 24 * 3600)
    return zonas


def sincroniza(dias: int = 7, db=None) -> dict[str, Any]:
    """Traz os dias em falta e os treinos recentes.

    Devolve o que aconteceu, para o job e o botão de sincronizar poderem dizer
    alguma coisa em vez de "ok"."""
    proprio = db is None
    db = db or SessionLocal()
    try:
        ja_tem = {d for (d,) in db.query(GarminDay.date).filter(
            GarminDay.date >= _date.today() - timedelta(days=dias)).all()}
        # Não vale a pena pedir dias anteriores ao primeiro que tem dados: antes
        # disso o relógio não existia, e eram 6 leituras por passagem a devolver
        # vazio para sempre.
        primeiro = db.query(GarminDay.date).order_by(GarminDay.date).first()
        alvos = garmin_api.dias_em_falta(ja_tem, dias=dias,
                                         nao_antes=primeiro[0] if primeiro else None)

        dias_ok, noites, vazios, movimentos, avisos = 0, 0, 0, 0, []
        for quando in alvos:
            try:
                cru = garmin_api.dia(quando)
            except garmin_api.GarminIndisponivel:
                raise
            except Exception as e:                      # pragma: no cover
                avisos.append(f"{quando}: {type(e).__name__}")
                continue
            linha = grava_dia(db, quando, cru)
            if linha is None:
                vazios += 1
                continue
            grava_series(db, quando, cru)
            movimentos += grava_movimentos(db, quando, cru)
            db.flush()
            if aplica_sono(db, linha):
                noites += 1
            dias_ok += 1

        desde = _date.today() - timedelta(days=dias)
        todos = not cache.cache_get(CHAVE_TREINOS_TODOS) and primeiro is not None
        treinos = grava_actividades(db, garmin_api.actividades(min(desde, primeiro[0]) if todos else desde))
        medicoes = grava_snapshots(db, garmin_api.snapshots(desde))
        db.flush()
        gym = marca_gym(db)
        db.commit()
        if todos:
            cache.cache_set(CHAVE_TREINOS_TODOS, True, 10 * 365 * 24 * 3600)

        guarda_zonas_fc()

        agora = datetime.now().timestamp()
        cache.cache_set(CHAVE_ULTIMA_LEITURA, agora, 30 * 24 * 3600)
        carimbo = garmin_api.ultimo_upload()
        if carimbo:
            cache.cache_set(CHAVE_ULTIMO_UPLOAD, carimbo, 30 * 24 * 3600)

        partes = [f"{dias_ok} dias"]
        if noites:
            partes.append(f"{noites} noites de sono")
        if treinos:
            partes.append(f"{treinos} treinos")
        if medicoes:
            partes.append(f"{medicoes} health snapshots")
        if gym:
            partes.append(f"gym marcado em {gym} dias")
        if movimentos:
            partes.append(f"{movimentos} movimentos detectados")
        if vazios:
            partes.append(f"{vazios} dias sem relógio")
        if avisos:
            partes.append(f"{len(avisos)} falhas")
        return {"dias": dias_ok, "noites": noites, "treinos": treinos,
                "snapshots": medicoes, "movimentos": movimentos, "gym": gym,
                "vazios": vazios, "avisos": avisos,
                "message": " · ".join(partes)}
    finally:
        if proprio:
            db.close()


def noites_medidas(db, dias: int = 30) -> int:
    return db.query(GarminDay).filter(
        GarminDay.date >= _date.today() - timedelta(days=dias),
        GarminDay.sleep_hours.isnot(None),
    ).count()
