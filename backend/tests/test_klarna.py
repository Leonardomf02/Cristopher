"""Prestações da Klarna: o que já saiu da conta e o que falta.

O caso é o dele: youget.pt, 106,63€ a 18 de Julho em três vezes. A segunda veio
a 19 de Agosto como "you Get" e a terceira a 12 de Setembro — seis dias antes do
dia 18 — com um cêntimo a mais.

Corre sozinho:  python tests/test_klarna.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

import expense_kind as ek
import klarna


class DespesaFalsa:
    def __init__(self, id, date_, amount, description="youget.pt", kind=ek.GASTO):
        self.id, self.date, self.amount = id, date_, amount
        self.description, self.kind = description, kind


COMPRA = DespesaFalsa(470, date(2026, 7, 18), 106.63)
SEGUNDA = DespesaFalsa(762, date(2026, 8, 19), 106.63, "you Get")
TERCEIRA = DespesaFalsa(836, date(2026, 9, 12), 106.64, "you Get")


def _plano(marcada, vezes, movimentos, hoje):
    return klarna.planos([(marcada, vezes)], movimentos, hoje)[0]


def _meses(planos):
    return [(m["month"], m["total"]) for m in klarna.por_pagar(planos)["months"]]


# ── Sem nada na conta ainda: valem as datas ──────────────────────

def test_tres_vezes_deixa_duas_por_pagar():
    p = _plano(COMPRA, 3, [], date(2026, 7, 20))
    assert p["paid"] == 1
    assert p["pending"] == [{"due": "2026-08-18", "n": 2}, {"due": "2026-09-18", "n": 3}]
    assert _meses([p]) == [("2026-08", 106.63), ("2026-09", 106.63)]


def test_a_que_vence_hoje_ainda_conta():
    assert len(_plano(COMPRA, 3, [], date(2026, 8, 18))["pending"]) == 2


def test_passou_da_data_sem_aparecer_da_se_por_paga():
    """A loja pode vir com um nome que não se reconhece; não fica a dever para sempre."""
    p = _plano(COMPRA, 3, [], date(2026, 8, 19))
    assert p["paid"] == 2 and [f["due"] for f in p["pending"]] == ["2026-09-18"]


# ── O que o banco já mostra ──────────────────────────────────────

def test_cobrada_antes_do_dia_ja_nao_se_guarda():
    """A terceira saiu a 12; a 13 já não há nada para pôr de lado, apesar de o
    dia 18 ainda não ter chegado."""
    p = _plano(COMPRA, 3, [SEGUNDA, TERCEIRA], date(2026, 9, 13))
    assert p["paid"] == 3 and p["pending"] == []
    assert [x["expense_id"] for x in p["payments"]] == [470, 762, 836]
    assert klarna.por_pagar([p])["total"] == 0


def test_paga_adiantado_logo_a_seguir_a_compra():
    cedo = DespesaFalsa(2, date(2026, 7, 25), 106.63, "you Get")
    p = _plano(COMPRA, 3, [cedo], date(2026, 7, 26))
    assert p["paid"] == 2 and [f["due"] for f in p["pending"]] == ["2026-09-18"]


def test_marcar_a_segunda_encontra_a_primeira_para_tras():
    p = _plano(SEGUNDA, 3, [COMPRA], date(2026, 8, 20))
    assert [x["n"] for x in p["payments"] if x["expense_id"] == 762] == [2]
    assert [f["due"] for f in p["pending"]] == ["2026-09-18"]


def test_outra_loja_com_o_mesmo_valor_nao_e_prestacao():
    outra = DespesaFalsa(2, date(2026, 8, 10), 106.63, "Worten")
    assert _plano(COMPRA, 3, [outra], date(2026, 8, 11))["paid"] == 1


def test_mesma_loja_com_outro_valor_nao_e_prestacao():
    outra = DespesaFalsa(2, date(2026, 8, 10), 59.90, "you Get")
    assert _plano(COMPRA, 3, [outra], date(2026, 8, 11))["paid"] == 1


def test_cobranca_que_so_diz_klarna_serve():
    generica = DespesaFalsa(2, date(2026, 8, 15), 106.63, "Klarna")
    assert _plano(COMPRA, 3, [generica], date(2026, 8, 16))["paid"] == 2


def test_o_que_nao_e_gasto_nao_e_prestacao():
    volta = DespesaFalsa(2, date(2026, 8, 10), 106.63, "you Get", kind=ek.ESTORNO)
    assert _plano(COMPRA, 3, [volta], date(2026, 8, 11))["paid"] == 1


def test_cada_movimento_so_serve_um_plano():
    a = DespesaFalsa(1, date(2026, 9, 1), 50.0, "Worten")
    b = DespesaFalsa(2, date(2026, 9, 3), 50.0, "Worten")
    paga = DespesaFalsa(3, date(2026, 9, 28), 50.0, "Worten")
    pa, pb = klarna.planos([(a, 3), (b, 3)], [paga], date(2026, 9, 29))
    assert (pa["paid"], pb["paid"]) == (2, 1)


# ── A soma por mês ───────────────────────────────────────────────

def test_duas_compras_somam_no_mesmo_mes():
    a = DespesaFalsa(1, date(2026, 9, 10), 100.0, "Worten")
    b = DespesaFalsa(2, date(2026, 9, 25), 50.0, "Fnac")
    planos = klarna.planos([(a, 3), (b, 4)], [], date(2026, 10, 1))
    assert _meses(planos) == [("2026-10", 150.0), ("2026-11", 150.0), ("2026-12", 50.0)]


def test_dia_31_cai_no_fim_do_mes_curto():
    assert klarna.mais_meses(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert klarna.mais_meses(date(2026, 11, 30), 2) == date(2027, 1, 30)
    assert klarna.mais_meses(date(2026, 1, 15), -2) == date(2025, 11, 15)


def test_sem_ser_gasto_nao_ha_plano():
    volta = DespesaFalsa(1, date(2026, 9, 10), 100.0, kind=ek.ESTORNO)
    entrada = DespesaFalsa(2, date(2026, 9, 10), -100.0)
    assert klarna.planos([(volta, 3), (entrada, 3)], [], date(2026, 9, 11)) == []


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("test_"):
            f()
            print("ok", nome)
