"""Mudar a categoria de um movimento do banco só vira regra quando ele pede.

Passava sempre: pôr um pagamento à associação de estudantes em Saúde mandava
para lá todos os outros dessa associação, e os que viessem.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Expense, MerchantRule
from routers.expenses import update_expense
from schemas import ExpenseUpdate


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/t.db")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    for i in (1, 2):
        s.add(Expense(description="Assoc Academica Ubi", amount=10, category="other",
                      date=date(2026, 9, i), bank_tx_id=f"tx{i}", notes=""))
    s.commit()
    yield s
    s.close()


def test_so_aquele_movimento_por_omissao(db):
    update_expense(1, ExpenseUpdate(category="health"), db)
    assert [e.category for e in db.query(Expense).order_by(Expense.id)] == ["health", "other"]
    assert db.query(MerchantRule).count() == 0


def test_com_a_caixa_marcada_os_iguais_vao_atras(db):
    update_expense(1, ExpenseUpdate(category="health", apply_to_similar=True), db)
    assert [e.category for e in db.query(Expense).order_by(Expense.id)] == ["health", "health"]
    assert db.query(MerchantRule).one().category == "health"
