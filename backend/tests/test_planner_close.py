"""O plano fecha-se com o que aconteceu, não com o que ele carimba.

Em nove planos ele marcou zero blocos. O tracker já sabia o que tinha feito — só
faltava a app usar isso. O que estes testes protegem: não inventar blocos feitos,
e nunca apagar um carimbo dele.

Corre sozinho:  python tests/test_planner_close.py
"""
import os
import sys
import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, AppUsageSession, DayPlanRecord
from routers.day_planner import fecha_plano, blocos_repetidos

DIA = date(2026, 7, 30)


def _sessao():
    tmp = Path(tempfile.mkdtemp()) / "teste.db"
    motor = create_engine(f"sqlite:///{tmp}")
    Base.metadata.create_all(motor)
    return sessionmaker(bind=motor)()


def _plano(db, blocos, dia=DIA):
    db.add(DayPlanRecord(plan_date=dia, wake_time="09:00", day_end="23:00",
                         mode="local", blocks_json=json.dumps(blocos)))
    db.commit()


def _uso(db, dia, inicio_h, minutos, app="Visual Studio Code", bundle="com.microsoft.VSCode"):
    ini = datetime.combine(dia, datetime.min.time()) + timedelta(hours=inicio_h)
    db.add(AppUsageSession(
        app_name=app, bundle_id=bundle, window_title="x", date=dia,
        start_time=ini, end_time=ini + timedelta(minutes=minutos),
        duration_seconds=minutos * 60,
    ))
    db.commit()


BLOCOS = [
    {"name": "Trabalho", "icon": "💼", "start": "10:00", "end": "12:00", "done": False},
    {"name": "Gym", "icon": "🏋️", "start": "17:00", "end": "18:00", "done": False},
]


def test_bloco_cumprido_fica_marcado():
    db = _sessao()
    _plano(db, BLOCOS)
    _uso(db, DIA, 10, 110)                    # quase as duas horas de trabalho
    r = fecha_plano(DIA.isoformat(), db)
    assert r["tracked"] is True and r["closed"] >= 1
    blocos = json.loads(db.query(DayPlanRecord).one().blocks_json)
    assert blocos[0]["done"] is True
    assert blocos[0]["done_by"] == "realidade"


def test_bloco_por_cumprir_nao_se_inventa():
    db = _sessao()
    _plano(db, BLOCOS)
    _uso(db, DIA, 10, 20)                     # 20min de 120 planeados
    fecha_plano(DIA.isoformat(), db)
    blocos = json.loads(db.query(DayPlanRecord).one().blocks_json)
    assert blocos[0]["done"] is False


def test_o_carimbo_dele_nunca_se_apaga():
    """Ele marcou o Gym à mão; o Mac desligado não pode desmarcá-lo."""
    db = _sessao()
    marcados = [dict(b) for b in BLOCOS]
    marcados[1]["done"] = True                # sem done_by = foi ele
    _plano(db, marcados)
    _uso(db, DIA, 10, 110)
    fecha_plano(DIA.isoformat(), db)
    blocos = json.loads(db.query(DayPlanRecord).one().blocks_json)
    assert blocos[1]["done"] is True


def test_dia_sem_tracker_nao_fecha_nada():
    db = _sessao()
    _plano(db, BLOCOS)
    r = fecha_plano(DIA.isoformat(), db)
    assert r["tracked"] is False and r["closed"] == 0


def test_dia_sem_plano_da_404():
    from fastapi import HTTPException
    db = _sessao()
    try:
        fecha_plano("2026-01-01", db)
        assert False, "devia ter dado 404"
    except HTTPException as ex:
        assert ex.status_code == 404


def test_fechar_duas_vezes_nao_conta_a_dobrar():
    db = _sessao()
    _plano(db, BLOCOS)
    _uso(db, DIA, 10, 110)
    primeiro = fecha_plano(DIA.isoformat(), db)["closed"]
    segundo = fecha_plano(DIA.isoformat(), db)["closed"]
    assert primeiro >= 1 and segundo == 0


def test_o_que_se_repete_conta_planeado_e_feito():
    db = _sessao()
    hoje = date.today()
    for atras in (1, 2, 3):
        dia = hoje - timedelta(days=atras)
        _plano(db, [dict(b) for b in BLOCOS], dia=dia)
        _uso(db, dia, 10, 110 if atras == 1 else 10)   # só um dia de trabalho a sério

    r = blocos_repetidos(days=30, db=db)
    trabalho = next(b for b in r["blocks"] if b["name"] == "Trabalho")
    assert trabalho["planned"] == 3
    assert trabalho["done"] == 1
    assert trabalho["rate"] == 33

    # O Gym nunca teve tracker àquela hora: fica por saber, não conta como falhado.
    gym = next(b for b in r["blocks"] if b["name"] == "Gym")
    assert gym["unknown"] == 3 and gym["rate"] is None


def test_tempo_livre_nao_entra_na_conta():
    db = _sessao()
    dia = date.today() - timedelta(days=1)
    _plano(db, BLOCOS + [{"name": "Tempo livre", "start": "12:00", "end": "13:00"}], dia=dia)
    _uso(db, dia, 10, 110)
    r = blocos_repetidos(days=30, db=db)
    assert all(b["name"] != "Tempo livre" for b in r["blocks"])


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {nome}")
            except AssertionError as ex:
                falhas += 1
                print(f"  FALHA {nome}: {ex}")
    print(f"\n{falhas} falhas")
    sys.exit(1 if falhas else 0)
