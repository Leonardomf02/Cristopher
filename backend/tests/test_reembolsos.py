"""A parte dos amigos numa conta que ele pagou.

O caso é o dele: o gás (CHAMATENCAO) a 35,60€ a 8 de Setembro, e no mesmo dia o
Rodrigo e o Gabriel mandaram 11,87€ cada.

Corre sozinho:  python tests/test_reembolsos.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

import reembolsos as rb


class Mov:
    def __init__(self, id, d, valor, descricao, split=None):
        self.id, self.date, self.amount, self.description = id, d, valor, descricao
        self.split_people = split


GAS = Mov(1, date(2026, 9, 8), 35.60, "CHAMATENCAO")
NOTARIO = Mov(2, date(2026, 9, 8), 34.00, "CARTORIO NOTARIA SAN")
RODRIGO = Mov(10, date(2026, 9, 8), -11.87, "TFI RODRIGO DIAS DA S")
GABRIEL = Mov(11, date(2026, 9, 8), -11.87, "TFI GABRIEL MENDES MI")
CAFE = Mov(12, date(2026, 9, 9), -1.50, "TFI LIDIA")


def test_os_dois_mbways_vao_para_o_gas_de_uma_vez():
    s = rb.sugestoes([RODRIGO, GABRIEL, CAFE], [GAS, NOTARIO], {}, set())
    assert len(s) == 1
    assert s[0]["expenses"] == [GAS]
    assert s[0]["incomes"] == [RODRIGO, GABRIEL]
    assert s[0]["share_after"] == 11.86


def test_nao_sugere_o_que_ja_foi_pago_nem_o_que_ele_dispensou():
    assert rb.sugestoes([RODRIGO], [GAS], {1: 30.0}, set()) == []
    assert rb.sugestoes([RODRIGO], [GAS], {}, {(10, 1)}) == []


def test_conta_dividida_aceita_o_amigo_que_paga_semanas_depois():
    gas = Mov(1, date(2026, 9, 8), 35.60, "CHAMATENCAO", split=3)
    tarde = Mov(13, date(2026, 10, 1), -11.87, "TFI RODRIGO DIAS DA S")
    assert rb.sugestoes([tarde], [GAS], {}, set()) == []
    assert rb.sugestoes([tarde], [gas], {}, set())[0]["expenses"] == [gas]


def test_quem_falta_pagar():
    gas = Mov(1, date(2026, 9, 8), 35.60, "CHAMATENCAO", split=3)
    falta = rb.por_receber([gas], {1: (11.87, 1)})
    assert falta[0]["missing"] == 11.86 and falta[0]["missing_people"] == 1
    assert rb.por_receber([gas], {1: (23.74, 2)}) == []


def test_candidatas_poem_a_que_bate_certo_a_frente():
    lista = rb.candidatas(RODRIGO, [NOTARIO, GAS], {})
    assert lista[0]["conta"] is GAS and lista[0]["partes"] == 3
    assert lista[1]["partes"] is None


def test_uma_entrada_repartida_por_duas_contas():
    # os dois levantamentos do chá, 70€ e 30€, e o Rafael mandou 75€
    assert rb.reparte(75.0, [(1, 70.0), (2, 30.0)]) == {1: 52.5, 2: 22.5}
    partes = rb.reparte(10.0, [(1, 1.0), (2, 1.0), (3, 1.0)])
    assert round(sum(partes.values()), 2) == 10.0


def test_a_parte_dele_em_valor():
    cha = Mov(5, date(2026, 10, 4), 100.0, "ATM Ctr Ass Cultura T")
    cha.my_share = 25.0
    falta = rb.por_receber([cha], {})
    assert falta[0]["missing"] == 75.0 and falta[0]["missing_people"] is None
    assert rb.por_receber([cha], {5: (75.0, 1)}) == []
    rafael = Mov(20, date(2026, 10, 4), -75.0, "From Rafael N")
    assert rb.sugestoes([rafael], [cha], {}, set())[0]["share_after"] == 25.0


def test_o_rafael_pagou_dois_levantamentos_de_uma_vez():
    # 70€ + 30€ no chá, a parte dele é 0€ no primeiro e 25€ no segundo,
    # e o Rafael mandou 75€: nenhuma conta sozinha leva 75€
    a = Mov(6, date(2026, 10, 4), 70.0, "ATM Ctr Ass Cultura T"); a.my_share = 0.0
    b = Mov(7, date(2026, 10, 4), 30.0, "ATM Ctr Ass Cultura T"); b.my_share = 25.0
    rafael = Mov(21, date(2026, 10, 4), -75.0, "From Rafael N")
    s = rb.sugestoes([rafael], [a, b], {}, set())
    assert len(s) == 1 and set(c.id for c in s[0]["expenses"]) == {6, 7}
    assert s[0]["share_after"] == 25.0
    assert rb.reparte(75.0, [(6, 70.0), (7, 5.0)]) == {6: 70.0, 7: 5.0}


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("test_"):
            f()
            print("ok", nome)
