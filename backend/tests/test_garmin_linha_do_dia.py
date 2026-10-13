"""A linha do dia (sono, sestas, Move IQ) e a leitura escrita pela IA.

Duas coisas que custaram a descobrir e que estes testes fixam:

- uma **caminhada de 25 minutos** que aparece na app da Garmin não é uma
  actividade gravada: `get_activities_by_date` devolve vazio nesse dia e ela só
  existe no Move IQ, onde a duração vem em **minutos** (nas actividades gravadas
  o mesmo campo vem em segundos);
- a **sesta** e a hora a que ele acordou não estão em campo nenhum do sono —
  saem dos eventos que explicam as subidas do body battery.

E a leitura da IA: qualquer algarismo que ela escreva tem de existir nos dados.
Se inventar um, o texto é deitado fora inteiro.

Corre sozinho:  python tests/test_garmin_linha_do_dia.py
"""
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import garmin_sync
from models import Base, GarminActivity, GarminDay

DIA = date(2026, 8, 12)

# O que a Garmin devolveu mesmo no dia 12: uma noite, uma sesta de 78 minutos e
# uma caminhada de 25 que o relógio detectou sozinho.
CRU = {
    "eventos": [
        {"event": {"eventType": "SLEEP", "eventStartTimeGmt": "2026-08-12T01:30:26.0",
                   "durationInMilliseconds": 19740000, "bodyBatteryImpact": 60}},
        {"event": {"eventType": "NAP", "eventStartTimeGmt": "2026-08-12T11:28:01.0",
                   "durationInMilliseconds": 4680000, "bodyBatteryImpact": 8}},
    ],
    "movimentos": [
        {"startTimestampGMT": "2026-08-12T17:20:00.0", "endTimestampGMT": "2026-08-12T17:45:00.0",
         "startTimestampLocal": "2026-08-12T18:20:00.0", "endTimestampLocal": "2026-08-12T18:45:00.0",
         "duration": 25, "activityType": "walking"},
    ],
}


def _sessao():
    tmp = Path(tempfile.mkdtemp()) / "teste.db"
    motor = create_engine(f"sqlite:///{tmp}")
    Base.metadata.create_all(motor)
    return sessionmaker(bind=motor)()


def test_a_sesta_e_o_sono_saem_dos_eventos():
    blocos = garmin_sync.linha_do_dia(CRU)
    tipos = [b["kind"] for b in blocos]
    assert tipos == ["sono", "sesta", "movimento"]          # por ordem do dia
    sono, sesta, _ = blocos
    assert (sono["end"] - sono["start"]) / 60000 == 329
    assert (sesta["end"] - sesta["start"]) / 60000 == 78
    assert sesta["impact"] == 8


def test_o_move_iq_conta_minutos_e_nao_segundos():
    """Sem fim explícito, `duration: 25` são 25 minutos — nas actividades
    gravadas o mesmo nome quer dizer segundos."""
    sem_fim = {"movimentos": [{"startTimestampGMT": "2026-08-12T17:20:00.0",
                               "duration": 25, "activityType": "walking"}]}
    bloco = garmin_sync.linha_do_dia(sem_fim)[0]
    assert (bloco["end"] - bloco["start"]) / 60000 == 25


def test_um_dia_sem_nada_nao_inventa_blocos():
    assert garmin_sync.linha_do_dia({}) == []
    assert garmin_sync.linha_do_dia({"eventos": [{"event": {}}], "movimentos": [{}]}) == []


def test_a_caminhada_detectada_fica_guardada_e_marcada():
    db = _sessao()
    assert garmin_sync.grava_movimentos(db, DIA, CRU) == 1
    db.flush()
    a = db.query(GarminActivity).one()
    assert a.auto is True and a.type == "walking"
    assert a.duration_s == 1500                              # 25 minutos em segundos
    # Correr outra vez não duplica: o identificador vem da hora de início.
    assert garmin_sync.grava_movimentos(db, DIA, CRU) == 0
    assert db.query(GarminActivity).count() == 1


def test_horas_de_codigo_nao_contam_o_mesmo_tempo_doze_vezes():
    """A tabela do WakaTime reparte o dia por projecto, linguagem, editor e
    dependência. Somar tudo dava 119h num dia de 8h — e era esse número que ia
    para as correlações e para o texto da leitura."""
    import garmin_insights as gi
    from models import WakaProjectDay

    db = _sessao()
    db.add(GarminDay(date=DIA))
    for kind, nome, horas in [("project", "Cristopher", 6), ("project", "Uni", 2),
                              ("language", "Python", 5), ("machine", "Mac", 8),
                              ("dependency", "json", 2)]:
        db.add(WakaProjectDay(day=DIA, kind=kind, project=nome, seconds=horas * 3600))
    db.commit()
    d = db.query(GarminDay).one()
    assert gi._horas_de_codigo(db, d) == 8


def test_a_leitura_da_ia_recusa_numeros_que_ninguem_mediu():
    import ai
    import garmin_insights as gi

    db = _sessao()
    db.add(GarminDay(date=DIA, sleep_hours=5.47, steps=5326))
    db.commit()

    factos = "- Dormiste 5h28 e o corpo pedia 8h00."
    original = ai.pergunta
    try:
        ai.pergunta = lambda *a, **k: "Dormiste 5h28, menos 3h do que as 8h00 pedidas."
        assert gi._analise_do_agente(db, DIA, [], factos) == ""      # o 3 não está nos dados

        ai.pergunta = lambda *a, **k: "Dormiste 5h28 quando o corpo pedia 8h00."
        assert gi._analise_do_agente(db, DIA, [], factos).startswith("Dormiste")
    finally:
        ai.pergunta = original


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
