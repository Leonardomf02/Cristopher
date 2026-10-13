"""O dia do salário de cada mês.

O caso é o dele: a universidade transfere 1.090,98€ a 25, 28, 27, 26 e 24, e em
Agosto mandou também 598€ que não são o salário.

Corre sozinho:  python tests/test_salario.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

import salario


class Entrada:
    def __init__(self, d, valor, descricao="TRF UNIVERSIDADE DA B"):
        self.date, self.amount, self.description = d, -valor, descricao


ENTRADAS = [
    Entrada(date(2026, 6, 25), 1090.98),
    Entrada(date(2026, 7, 27), 1090.98),
    Entrada(date(2026, 7, 30), 446.92, "TFI Leonardo Santos"),
    Entrada(date(2026, 8, 3), 598.0),
    Entrada(date(2026, 8, 26), 1090.98),
    Entrada(date(2026, 9, 24), 1090.98),
]
HOJE = date(2026, 10, 5)


def _dias(correcoes=None, primeiro=date(2026, 6, 1), entradas=ENTRADAS):
    return salario.dias_de_salario(entradas, lambda m, a: 1090.98, correcoes or {}, primeiro, HOJE)


def test_le_o_salario_da_conta_e_ignora_as_outras_entradas():
    r = _dias()
    assert [(d["date"], d["source"]) for d in r["paydays"]] == [
        (date(2026, 6, 25), "banco"), (date(2026, 7, 27), "banco"),
        (date(2026, 8, 26), "banco"), (date(2026, 9, 24), "banco"),
    ]
    assert r["typical_day"] == 26


def test_a_correcao_dele_ganha_a_conta():
    r = _dias({"2026-09": (date(2026, 9, 26), None)})
    setembro = [d for d in r["paydays"] if d["month"] == "2026-09"]
    assert len(setembro) == 1
    assert setembro[0]["date"] == date(2026, 9, 26) and setembro[0]["source"] == "manual"
    assert setembro[0]["amount"] == 1090.98


def test_uma_correcao_num_mes_sem_salario_abre_um_ciclo():
    # o banco ainda não sincronizou, mas ele sabe que o de Outubro entrou a 2
    r = salario.dias_de_salario(ENTRADAS, lambda m, a: 1090.98, {"2026-10": (date(2026, 10, 2), None)},
                                date(2026, 6, 1), HOJE)
    assert [d["date"] for d in r["paydays"]][-2:] == [date(2026, 9, 24), date(2026, 10, 2)]


def test_meses_sem_banco_levam_o_dia_do_costume_mas_o_mes_corrente_nao():
    r = _dias(primeiro=date(2026, 4, 10))
    estimados = [(d["month"], d["date"]) for d in r["paydays"] if d["source"] == "estimado"]
    assert estimados == [("2026-04", date(2026, 4, 26)), ("2026-05", date(2026, 5, 26))]
    assert not any(d["month"] == "2026-10" for d in r["paydays"])


def test_sem_banco_nenhum_vale_o_dia_por_omissao():
    r = _dias(primeiro=date(2026, 8, 1), entradas=[])
    assert [d["date"] for d in r["paydays"]] == [date(2026, 8, 25), date(2026, 9, 25)]


def test_marcar_um_movimento_como_salario_traz_o_valor():
    # a bolsa veio com outro valor e a regra dos 80% não a apanhou
    r = _dias({"2026-10": (date(2026, 10, 3), 980.0)})
    outubro = [d for d in r["paydays"] if d["month"] == "2026-10"][0]
    assert outubro["date"] == date(2026, 10, 3) and outubro["amount"] == 980.0


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("test_"):
            f()
            print("ok", nome)
