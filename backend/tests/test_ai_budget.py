"""Nenhuma parte da app pode comer a quota de IA toda.

O agente é partilhado por quinze sítios e é o recurso mais escasso que a app tem.
Uma pesquisa de deals com 200 anúncios novos deixava o Perguntar sem IA o resto
do dia — e ninguém sabia quem tinha gasto o quê.

Corre sozinho:  python tests/test_ai_budget.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_budget
from routers.deals import _separa_por_preco


def _limpa():
    ai_budget._contagem.clear()


# ── Contagem e tectos ────────────────────────────────────────────

def test_conta_por_parte_da_app():
    _limpa()
    ai_budget.regista("deals")
    ai_budget.regista("deals")
    ai_budget.regista("ask")
    assert ai_budget.gastas("deals") == 2
    assert ai_budget.gastas("ask") == 1
    assert ai_budget.estado()["total"] == 3


def test_o_tecto_trava_a_parte_certa():
    _limpa()
    for _ in range(ai_budget.TECTOS["deals"]):
        ai_budget.regista("deals")
    assert ai_budget.permitido("deals") is False
    assert ai_budget.permitido("sinais") is True     # os outros não são afectados


def test_o_que_ele_pede_a_mao_nunca_e_travado():
    _limpa()
    for _ in range(500):
        ai_budget.regista("ask")
    assert ai_budget.permitido("ask") is True
    assert ai_budget.permitido("captura") is True


def test_parte_desconhecida_nao_rebenta():
    _limpa()
    ai_budget.regista("coisa-nova")
    assert ai_budget.permitido("coisa-nova") is True


def test_estado_aponta_quem_estourou():
    _limpa()
    for _ in range(ai_budget.TECTOS["deals"]):
        ai_budget.regista("deals")
    assert "deals" in ai_budget.estado()["capped"]


# ── Filtro de preço dos deals ────────────────────────────────────

class AnuncioFalso:
    def __init__(self, price):
        self.price = price


class WatchFalso:
    max_price = None


def test_sem_historico_avalia_se_tudo():
    """É assim que o histórico se faz: sem preços conhecidos, tudo vai à IA."""
    anuncios = [AnuncioFalso(p) for p in (100, 5000, 9000)]
    vao, ficam = _separa_por_preco(anuncios, [100.0, 200.0], WatchFalso())
    assert len(vao) == 3 and not ficam


def test_com_historico_o_que_e_caro_fica_de_fora():
    historico = [float(p) for p in range(5000, 8000, 100)]     # 30 preços
    anuncios = [AnuncioFalso(4000), AnuncioFalso(6000), AnuncioFalso(12000)]
    vao, ficam = _separa_por_preco(anuncios, historico, WatchFalso())
    assert [a.price for a in vao] == [4000, 6000]
    assert [a.price for a in ficam] == [12000]


def test_anuncio_sem_preco_vai_sempre():
    historico = [float(p) for p in range(5000, 8000, 100)]
    vao, ficam = _separa_por_preco([AnuncioFalso(None)], historico, WatchFalso())
    assert len(vao) == 1 and not ficam


def test_o_tecto_dele_manda_se_for_mais_apertado():
    historico = [float(p) for p in range(5000, 8000, 100)]

    class Apertado:
        max_price = 5500

    vao, ficam = _separa_por_preco([AnuncioFalso(5200), AnuncioFalso(6000)], historico, Apertado())
    assert [a.price for a in vao] == [5200]


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
