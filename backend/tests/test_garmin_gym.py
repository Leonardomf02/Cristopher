"""Um treino de ginásio no relógio marca o hábito do gym.

Corre sozinho:  python tests/test_garmin_gym.py
"""
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import garmin_sync as gs
from models import Base, GarminActivity, GarminDay, Habit, HabitCompletion


def _sessao():
    tmp = Path(tempfile.mkdtemp()) / "teste.db"
    motor = create_engine(f"sqlite:///{tmp}")
    Base.metadata.create_all(motor)
    # Como o `SessionLocal` da app: sem autoflush, o que foi adicionado não se vê nas consultas.
    return sessionmaker(bind=motor, autoflush=False)()


def _treino(db, aid, dia, tipo="strength_training", minutos=60, hora=18):
    db.add(GarminActivity(activity_id=aid, date=dia, type=tipo, name=tipo,
                          start_time=datetime.combine(dia, datetime.min.time()).replace(hour=hora),
                          duration_s=minutos * 60))


def test_marca_o_gym_nos_dias_de_treino_de_ginasio():
    db = _sessao()
    db.add_all([Habit(id=1, name="Gym", active=True), Habit(id=2, name="Pesquisa", active=True)])
    hoje = date.today()
    _treino(db, "a", hoje - timedelta(days=2), hora=18, minutos=59)
    _treino(db, "b", hoje - timedelta(days=4), tipo="walking")          # caminhada não é gym
    _treino(db, "c", hoje - timedelta(days=5), minutos=3)               # começado sem querer
    _treino(db, "d", hoje - timedelta(days=60), hora=10)                # os antigos também
    db.commit()

    assert gs.marca_gym(db) == 2
    db.commit()
    feitos = db.query(HabitCompletion).order_by(HabitCompletion.date).all()
    assert [(c.habit_id, c.date, c.completed_at) for c in feitos] == [
        (1, hoje - timedelta(days=60), "11:00"), (1, hoje - timedelta(days=2), "18:59")]
    assert "relógio" in feitos[0].notes


def test_um_gym_desmarcado_a_mao_nao_volta():
    db = _sessao()
    db.add(Habit(id=1, name="Ginásio", active=True))
    _treino(db, "a", date.today())
    db.commit()
    assert gs.marca_gym(db) == 1
    db.commit()
    db.query(HabitCompletion).delete()
    db.commit()
    assert gs.marca_gym(db) == 0
    assert db.query(HabitCompletion).count() == 0


def test_dois_treinos_no_mesmo_dia_marcam_uma_vez_e_nao_pisam_o_que_ele_marcou():
    db = _sessao()
    db.add(Habit(id=1, name="Gym", active=True))
    hoje = date.today()
    db.add(HabitCompletion(habit_id=1, date=hoje - timedelta(days=1), completed_at="10:00", notes="eu"))
    _treino(db, "a", hoje - timedelta(days=1))
    _treino(db, "b", hoje, tipo="indoor_cycling", minutos=18, hora=10)
    _treino(db, "c", hoje, minutos=50, hora=11)
    db.commit()
    assert gs.marca_gym(db) == 1
    db.commit()
    assert db.query(HabitCompletion).filter_by(date=hoje - timedelta(days=1)).one().notes == "eu"
    hoje_feito = db.query(HabitCompletion).filter_by(date=hoje).one()
    assert hoje_feito.completed_at == "11:50" and "strength_training" in hoje_feito.notes


def test_a_primeira_sincronizacao_traz_os_treinos_todos_e_as_seguintes_so_a_semana(monkeypatch):
    db = _sessao()
    db.add(Habit(id=1, name="Gym", active=True))
    db.add(GarminDay(date=date.today() - timedelta(days=40)))
    db.commit()
    memoria, pedidos = {}, []
    monkeypatch.setattr(gs.cache, "cache_get", memoria.get)
    monkeypatch.setattr(gs.cache, "cache_set", lambda k, v, ttl: memoria.__setitem__(k, v))
    monkeypatch.setattr(gs.garmin_api, "dias_em_falta", lambda *a, **k: [])
    monkeypatch.setattr(gs.garmin_api, "snapshots", lambda desde: [])
    monkeypatch.setattr(gs.garmin_api, "ultimo_upload", lambda: None)
    monkeypatch.setattr(gs, "guarda_zonas_fc", lambda: None)
    antigo = (date.today() - timedelta(days=35)).isoformat()
    monkeypatch.setattr(gs.garmin_api, "actividades", lambda desde: pedidos.append(desde) or [{
        "activityId": 1, "startTimeLocal": f"{antigo} 10:00:00", "duration": 3000,
        "activityType": {"typeKey": "strength_training"}, "activityName": "Strength"}])

    assert gs.sincroniza(db=db)["gym"] == 1
    assert pedidos[-1] == date.today() - timedelta(days=40)
    gs.sincroniza(db=db)
    assert pedidos[-1] == date.today() - timedelta(days=7)
    assert db.query(HabitCompletion).one().date.isoformat() == antigo


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("test_") and f.__code__.co_argcount == 0:
            f()
            print("ok", nome)
