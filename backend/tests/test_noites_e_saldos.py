"""Saídas à noite (pistas e efeito no sono) e o saldo dos bancos nos Gastos.

Corre sozinho:  python tests/test_noites_e_saldos.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import BankAccount, BankConnection, Expense, GarminDay, NightOut
from routers import banking, nights


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_gasto_na_noite_depois_da_meia_noite_e_pista_da_vespera():
    db = _db()
    sabado = date(2026, 10, 10)
    db.add_all([
        Expense(description="Bar Galeria", amount=12.5, category="nightlife", kind="spend",
                date=sabado + timedelta(days=1), time_of_day="01:20"),
        # às 14h do dia seguinte já não é dessa noite
        Expense(description="Bar ao almoço", amount=4, category="nightlife", kind="spend",
                date=sabado + timedelta(days=1), time_of_day="14:00"),
        # de manhã no próprio dia também não
        Expense(description="Café", amount=2, category="nightlife", kind="spend",
                date=sabado, time_of_day="10:00"),
        # sem hora (a Caixa não a manda) conta o próprio dia
        Expense(description="Discoteca", amount=10, category="nightlife", kind="spend", date=sabado),
        # um estorno não é ter saído
        Expense(description="Bar devolvido", amount=-8, category="nightlife", kind="reversal",
                date=sabado, time_of_day="23:00"),
    ])
    db.commit()
    pistas = nights._pistas(db, sabado)
    assert [p["description"] for p in pistas] == ["Discoteca", "Bar Galeria"]


def test_marcar_e_desmarcar():
    db = _db()
    d = date(2026, 10, 10)
    assert nights.ler(d, db)["went_out"] is False
    assert nights.marcar(d, nights.Marca(drank=True), db)["drank"] is True
    r = nights.marcar(d, nights.Marca(level=2), db)
    assert (r["drank"], r["drink_level"]) == (True, 2)
    assert nights.marcar(d, nights.Marca(drank=False), db) == {
        "date": "2026-10-10", "went_out": True, "drank": False, "drink_level": None, "evidence": []}
    assert db.query(NightOut).count() == 1
    assert nights.desmarcar(d, db)["went_out"] is False
    assert db.query(NightOut).count() == 0


def test_efeito_compara_a_noite_seguinte_e_deixa_de_fora_as_saidas_sobrias():
    db = _db()
    hoje = date.today()
    # 10 noites medidas: as que vêm depois de beber têm HRV 30, as outras 50
    bebidas = {hoje - timedelta(days=d) for d in (2, 4, 6)}
    sobria = hoje - timedelta(days=8)
    for d in range(1, 11):
        acordou = hoje - timedelta(days=d)
        vespera = acordou - timedelta(days=1)
        db.add(GarminDay(date=acordou, sleep_hours=7, sleep_score=70 if vespera in bebidas else 85,
                         hrv_last_night=30 if vespera in bebidas else 50))
    for v in bebidas:
        db.add(NightOut(date=v, drank=True))
    db.add(NightOut(date=sobria, drank=False))
    db.commit()

    r = nights.efeito(days=365, db=db)
    assert (r["drank"], r["home"], r["sober_out"]) == (3, 6, 1)
    hrv = next(x for x in r["rows"] if x["key"] == "hrv_last_night")
    assert (hrv["drank"], hrv["home"], hrv["worse"]) == ("30", "50", True)
    assert hrv["p"] is None            # 3 contra 6 não chega para o teste


def test_efeito_sem_noites_que_cheguem_nao_inventa_medianas():
    db = _db()
    db.add(GarminDay(date=date.today() - timedelta(days=1), sleep_hours=7, sleep_score=80))
    db.add(NightOut(date=date.today() - timedelta(days=2), drank=True))
    db.commit()
    assert nights.efeito(days=365, db=db)["rows"] == []


def test_saldos_somam_as_contas_de_cada_banco():
    db = _db()
    db.add_all([
        BankConnection(id=1, institution_id="Revolut|PT", institution_name="Revolut",
                       requisition_id="a", status="ligado", last_sync_at=datetime(2026, 10, 11, 8, 30)),
        BankConnection(id=2, institution_id="Caixa Geral de Depósitos|PT",
                       institution_name="Caixa Geral de Depósitos", requisition_id="b", status="ligado"),
        BankConnection(id=3, institution_id="X|PT", requisition_id="c", status="pendente"),
        BankAccount(connection_id=1, account_id="r-eur", iban="LT55000013", currency="EUR", balance=63.51),
        # bolsos noutra moeda a zero não pedem câmbio nenhum
        BankAccount(connection_id=1, account_id="r-pln", iban="LT55000013", currency="PLN", balance=0.0),
        BankAccount(connection_id=2, account_id="c1", iban="PT50000001", currency="EUR", balance=915.64),
        # sem IBAN é o cartão (o plafond que sobra), não dinheiro na conta
        BankAccount(connection_id=2, account_id="c2", currency="EUR", balance=131.6),
        BankAccount(connection_id=2, account_id="c3", currency="EUR", balance=999.0, active=False),
    ])
    db.commit()
    r = banking.saldos(db)
    assert [(b["name"], b["balance"]) for b in r["banks"]] == [("Revolut", 63.51), ("Caixa", 915.64)]
    assert r["total"] == 979.15
    assert r["banks"][0]["as_of"] == "2026-10-11T08:30:00Z"
    assert r["banks"][1]["cards"] == [{"currency": "EUR", "balance": 131.6}]


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("test_"):
            f()
            print("ok", nome)
