"""O sono do relógio a entrar onde estava o palpite.

Durante meses o sono foi **adivinhado** pelo buraco de actividade no Mac, com
offsets fixos de +45min/-30min. Esse número alimenta as correlações, as
anomalias, o planeador e até a hora a que os trabalhos diários correm. Trocar a
fonte é a parte valiosa — e a parte onde um engano apaga uma noite que ele
escreveu à mão.

Corre sozinho:  python tests/test_garmin_sono.py
"""
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import garmin_sync as gs
from models import Base, GarminDay, GarminSeries, GarminSnapshot, SleepEntry

DIA = date(2026, 8, 12)


def _sessao():
    tmp = Path(tempfile.mkdtemp()) / "teste.db"
    motor = create_engine(f"sqlite:///{tmp}")
    Base.metadata.create_all(motor)
    return sessionmaker(bind=motor)()


DEITAR = datetime(2026, 8, 11, 22, 0)      # hora de parede, como aparece no relógio
ACORDAR = datetime(2026, 8, 12, 5, 12)


def _ms_local(quando: datetime) -> int:
    """Como a Garmin manda as horas de sono: epoch já deslocado para a hora dele
    (por isso se lê como hora de parede)."""
    return int(quando.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _ms_real(quando: datetime) -> int:
    """Como a Garmin manda as séries do dia: epoch verdadeiro.

    A diferença entre os dois é a armadilha que trocou o body battery ao acordar
    por um valor de uma hora depois."""
    return int(quando.timestamp() * 1000)


DEITAR_MS = _ms_local(DEITAR)
ACORDAR_MS = _ms_local(ACORDAR)


def _cru(**muda):
    """Resposta como a Garmin a devolve: aninhada e com campos a faltar."""
    base = {
        "date": DIA.isoformat(),
        "sono": {
            "dailySleepDTO": {
                "calendarDate": DIA.isoformat(),
                "sleepTimeSeconds": 25920,                 # 7h12
                "napTimeSeconds": 0,
                "deepSleepSeconds": 4500,
                "lightSleepSeconds": 16200,
                "remSleepSeconds": 5220,
                "awakeSleepSeconds": 1080,
                "awakeCount": 2,
                "sleepStartTimestampLocal": DEITAR_MS,
                "sleepEndTimestampLocal": ACORDAR_MS,
                "sleepScores": {"overall": {"value": 82, "qualifierKey": "GOOD"}},
                "averageSpO2Value": 95.0,
                "lowestSpO2Value": 89.0,
                "averageRespirationValue": 14.2,
                "avgSleepStress": 21.0,
                "sleepScoreFeedback": "NEGATIVE_LONG_BUT_NOT_ENOUGH_REM",
            },
            "restingHeartRate": 54,
            "sleepNeed": {"baseline": 480, "actual": 432, "feedback": "ON_TARGET"},
        },
        "hrv": {"hrvSummary": {
            "lastNightAvg": 44, "lastNight5MinHigh": 62, "weeklyAvg": 46,
            "status": "BALANCED", "feedbackPhrase": "HRV_BALANCED_1",
            "baseline": {"balancedLow": 38, "balancedUpper": 55},
        }},
        "stress": {
            "avgStressLevel": 31, "maxStressLevel": 88,
            "stressValuesArray": [[_ms_real(DEITAR), -1], [_ms_real(ACORDAR), 25],
                                  [_ms_real(ACORDAR) + 3_600_000, 47]],
            "bodyBatteryValuesArray": [[_ms_real(DEITAR), "MEASURED", 41, 1.0],
                                       [_ms_real(ACORDAR), "MEASURED", 82, 1.0],
                                       [_ms_real(ACORDAR) + 3_600_000, "MEASURED", 75, 1.0]],
        },
        "resumo": {
            "totalSteps": 8421, "dailyStepGoal": 7500, "totalDistanceMeters": 6120.5,
            "totalKilocalories": 2450, "activeKilocalories": 640,
            "moderateIntensityMinutes": 22, "vigorousIntensityMinutes": 8,
            "restStressDuration": 18000, "lowStressDuration": 14400,
            "mediumStressDuration": 7200, "highStressDuration": 1800,
            "bodyBatteryChargedValue": 58, "bodyBatteryDrainedValue": 71,
        },
        "fc": {"minHeartRate": 48, "maxHeartRate": 154, "restingHeartRate": 54,
               "heartRateValues": [[1000, 62], [2000, 71]]},
        "prontidao": [{"score": 74, "level": "HIGH", "feedbackShort": "READY",
                       "recoveryTime": 180, "acuteLoad": 310.0}],
        "estado_treino": {
            "mostRecentVO2Max": {"generic": {"vo2MaxValue": 47.0}},
            "mostRecentTrainingStatus": {"latestTrainingStatusData": {
                "3412345678": {"trainingStatus": 3,
                               "trainingStatusFeedbackPhrase": "PRODUCTIVE_1"},
            }},
        },
        "vo2max": None,
    }
    base.update(muda)
    return base


# ── mapeamento ───────────────────────────────────────────────────

def test_grava_o_que_o_relogio_mediu():
    db = _sessao()
    linha = gs.grava_dia(db, DIA, _cru())
    db.commit()

    assert linha.sleep_hours == 7.2
    assert (linha.deep_min, linha.light_min, linha.rem_min) == (75, 270, 87)
    assert linha.awake_count == 2
    assert linha.sleep_score == 82 and linha.sleep_qualifier == "GOOD"
    assert linha.sleep_need_min == 480
    assert linha.resting_hr == 54
    assert linha.hrv_last_night == 44 and linha.hrv_status == "BALANCED"
    assert (linha.hrv_baseline_low, linha.hrv_baseline_high) == (38, 55)
    assert linha.spo2_avg == 95.0 and linha.resp_avg == 14.2
    assert linha.steps == 8421 and linha.step_goal == 7500
    assert linha.stress_avg == 31 and linha.stress_high_min == 30
    assert linha.training_readiness == 74 and linha.readiness_level == "HIGH"
    assert linha.vo2max == 47.0
    assert linha.training_status == "PRODUCTIVE_1"
    assert linha.acute_load == 310.0


def test_body_battery_conta_a_partir_do_acordar():
    """Quem se deita às 2h já gastou bateria depois da meia-noite: a primeira
    leitura do dia não é "com quanto acordou".

    E tem de ser o valor à hora a que acordou, não uma hora depois: as horas do
    sono e as séries do dia vêm em escalas de tempo diferentes, e ignorar isso
    dava 80 numa manhã em que ele acordou com 93."""
    db = _sessao()
    linha = gs.grava_dia(db, DIA, _cru())
    assert linha.bb_start == 82                         # às 05:12, não os 41 da meia-noite
    assert linha.bb_start != 75                         # nem os 75 de uma hora depois
    assert (linha.bb_max, linha.bb_min, linha.bb_end) == (82, 41, 75)


def test_sem_sono_o_body_battery_cai_para_a_primeira_leitura():
    cru = _cru()
    cru["sono"] = {"dailySleepDTO": {"calendarDate": DIA.isoformat(), "sleepTimeSeconds": None}}
    db = _sessao()
    linha = gs.grava_dia(db, DIA, cru)
    assert linha.sleep_hours is None
    assert linha.bb_start == 41


def test_leituras_invalidas_nao_entram_na_serie():
    """O stress vem a -1 quando o relógio não está no pulso. Isso não é zero."""
    db = _sessao()
    gs.grava_series(db, DIA, _cru())
    db.commit()
    s = db.query(GarminSeries).filter(GarminSeries.date == DIA).first()
    assert f"[{_ms_real(ACORDAR)}, 25]" in s.stress_json and "-1" not in s.stress_json
    assert f"[{_ms_real(DEITAR)}, 41]" in s.body_battery_json   # nível, não o texto "MEASURED"


def _dia_vazio():
    return {"date": DIA.isoformat(), "sono": None, "hrv": None, "stress": None,
            "resumo": None, "fc": None, "prontidao": None, "estado_treino": None}


def test_dia_sem_relogio_nao_fica_gravado():
    """Ele comprou o relógio a 11 de Agosto. Gravar linhas de NULLs para os dias
    antes disso só punha buracos nos gráficos e inflava as contagens."""
    db = _sessao()
    assert gs.grava_dia(db, DIA, _dia_vazio()) is None
    gs.grava_series(db, DIA, _dia_vazio())
    db.commit()
    assert db.query(GarminDay).count() == 0
    assert db.query(GarminSeries).count() == 0


def test_dia_so_com_passos_conta_como_medido():
    """Usar o relógio meia hora à tarde é pouco, mas não é nada."""
    cru = _dia_vazio()
    cru["resumo"] = {"totalSteps": 1055}
    db = _sessao()
    linha = gs.grava_dia(db, DIA, cru)
    assert linha is not None and linha.steps == 1055
    assert gs.aplica_sono(db, linha) is False


def test_correr_duas_vezes_nao_duplica():
    db = _sessao()
    gs.grava_dia(db, DIA, _cru())
    db.commit()
    gs.grava_dia(db, DIA, _cru())
    db.commit()
    assert db.query(GarminDay).count() == 1


# ── o sono real vs o palpite ─────────────────────────────────────

def _dia_com_sono(db):
    linha = gs.grava_dia(db, DIA, _cru())
    db.flush()
    return linha


def test_noite_nova_entra_como_garmin():
    db = _sessao()
    assert gs.aplica_sono(db, _dia_com_sono(db)) is True
    db.commit()
    e = db.query(SleepEntry).filter(SleepEntry.date == DIA).first()
    assert e.source == "garmin" and e.hours == 7.2
    assert e.quality == 4                               # score 82 → 4 de 5
    assert (e.bedtime, e.wake_time) == ("22:00", "05:12")


def test_substitui_o_palpite_do_mac():
    db = _sessao()
    db.add(SleepEntry(date=DIA, bedtime="02:30", wake_time="11:00", hours=8.5,
                      source="power", notes="o Mac esteve parado das 02:30 às 11:00"))
    db.commit()
    assert gs.aplica_sono(db, _dia_com_sono(db)) is True
    db.commit()
    e = db.query(SleepEntry).filter(SleepEntry.date == DIA).first()
    assert e.source == "garmin" and e.hours == 7.2
    assert e.notes == ""                                # a nota do palpite já não diz nada


def test_nao_toca_na_noite_que_ele_escreveu():
    db = _sessao()
    db.add(SleepEntry(date=DIA, bedtime="01:00", wake_time="09:00", hours=8.0,
                      quality=5, source="manual", notes="dormi bem"))
    db.commit()
    assert gs.aplica_sono(db, _dia_com_sono(db)) is False
    db.commit()
    e = db.query(SleepEntry).filter(SleepEntry.date == DIA).first()
    assert e.source == "manual" and e.hours == 8.0 and e.notes == "dormi bem"


def test_nota_dele_sobrevive_a_troca_de_fonte():
    db = _sessao()
    db.add(SleepEntry(date=DIA, hours=8.5, source="auto", notes="acordei com dores"))
    db.commit()
    gs.aplica_sono(db, _dia_com_sono(db))
    db.commit()
    e = db.query(SleepEntry).filter(SleepEntry.date == DIA).first()
    assert e.notes == "acordei com dores" and e.source == "garmin"


def test_segunda_passagem_do_mesmo_dia_nao_conta_como_mudanca():
    db = _sessao()
    linha = _dia_com_sono(db)
    assert gs.aplica_sono(db, linha) is True
    db.commit()
    assert gs.aplica_sono(db, linha) is False


# ── Health Snapshot ──────────────────────────────────────────────

def _snapshot_cru(uuid="cf6cc12d-34f8-4f33-89f5-2667aab6414c"):
    """Como sai do gateway GraphQL: as medidas vêm numa lista, não em campos."""
    return {
        "activityUuid": {"uuid": uuid},
        "calendarDate": "2026-08-11",
        "activityName": "Health Snapshot - Evening",
        "startTimestampLocal": "2026-08-11T18:55:16.0",
        "endTimestampLocal": "2026-08-11T18:57:16.84",
        "summaryTypeDataList": [
            {"summaryType": "HEART_RATE", "minValue": 74.0, "maxValue": 95.0, "avgValue": 82.0},
            {"summaryType": "RESPIRATION", "minValue": 14.0, "maxValue": 19.0, "avgValue": 16.65999984741211},
            {"summaryType": "STRESS", "minValue": 29.0, "maxValue": 70.0, "avgValue": 55.0},
            {"summaryType": "SPO2", "minValue": 95.0, "maxValue": 99.0, "avgValue": 98.0},
            {"summaryType": "RMSSD_HRV", "avgValue": 29.0},
            {"summaryType": "SDRR_HRV", "avgValue": 61.0},
        ],
        "deviceMetaData": {"deviceName": "Forerunner 70"},
    }


def test_health_snapshot_entra_com_as_medidas_todas():
    db = _sessao()
    assert gs.grava_snapshots(db, [_snapshot_cru()]) == 1
    db.commit()
    s = db.query(GarminSnapshot).first()
    assert s.date == date(2026, 8, 11) and s.start_time.strftime("%H:%M") == "18:55"
    assert s.duration_s == 120
    assert (s.hr_avg, s.hr_max) == (82.0, 95.0)
    assert (s.hrv_rmssd, s.hrv_sdrr) == (29.0, 61.0)     # o HRV sem esperar 19 noites
    assert (s.spo2_avg, s.spo2_min) == (98.0, 95.0)
    assert s.resp_avg == 16.7 and s.stress_avg == 55.0
    assert s.device == "Forerunner 70"


def test_snapshot_repetido_nao_duplica():
    db = _sessao()
    gs.grava_snapshots(db, [_snapshot_cru()])
    db.commit()
    assert gs.grava_snapshots(db, [_snapshot_cru()]) == 0
    db.commit()
    assert db.query(GarminSnapshot).count() == 1


def test_snapshot_sem_uuid_e_ignorado():
    db = _sessao()
    mau = _snapshot_cru()
    mau["activityUuid"] = None
    assert gs.grava_snapshots(db, [mau]) == 0


def test_score_vira_qualidade():
    assert [gs.qualidade_do_score(s) for s in (95, 84, 72, 61, 40, None)] == [5, 4, 3, 2, 1, None]


# ── ir buscar só quando vale a pena ──────────────────────────────

def test_sondagem_poupa_a_leitura_pesada_quando_nada_mudou():
    """O relógio não tem Wi-Fi: sem ele passar pelo telemóvel não há dados novos.
    Perguntar isso custa um pedido e poupa os outros nove."""
    import garmin_api
    orig = garmin_api.ultimo_upload
    garmin_api.ultimo_upload = lambda: 1786523965000
    gs.cache.cache_set(gs.CHAVE_ULTIMA_LEITURA, datetime.now().timestamp(), 3600)
    gs.cache.cache_set(gs.CHAVE_ULTIMO_UPLOAD, 1786523965000, 3600)
    try:
        vale, motivo = gs.ha_coisa_nova()
        assert vale is False and "telemóvel" in motivo
    finally:
        garmin_api.ultimo_upload = orig


def test_sincronizacao_nova_quando_o_relogio_passou_pelo_telemovel():
    import garmin_api
    orig = garmin_api.ultimo_upload
    garmin_api.ultimo_upload = lambda: 1786600000000
    gs.cache.cache_set(gs.CHAVE_ULTIMA_LEITURA, datetime.now().timestamp(), 3600)
    gs.cache.cache_set(gs.CHAVE_ULTIMO_UPLOAD, 1786523965000, 3600)
    try:
        vale, _ = gs.ha_coisa_nova()
        assert vale is True
    finally:
        garmin_api.ultimo_upload = orig


def test_de_vez_em_quando_le_na_mesma():
    """A prontidão e a idade de fitness são calculadas do lado da Garmin e podem
    mudar sem o relógio sincronizar."""
    import garmin_api
    orig = garmin_api.ultimo_upload
    garmin_api.ultimo_upload = lambda: 1786523965000
    gs.cache.cache_set(gs.CHAVE_ULTIMO_UPLOAD, 1786523965000, 3600)
    gs.cache.cache_set(gs.CHAVE_ULTIMA_LEITURA,
                       datetime.now().timestamp() - (gs.HORAS_ATE_LER_A_FORCA + 1) * 3600, 3600)
    try:
        vale, motivo = gs.ha_coisa_nova()
        assert vale is True and "rotina" in motivo
    finally:
        garmin_api.ultimo_upload = orig


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok  {nome}")
            except AssertionError as e:
                falhas += 1
                print(f"FALHA  {nome}: {e}")
    print("tudo bem" if not falhas else f"{falhas} falhas")
    raise SystemExit(1 if falhas else 0)
