"""Reconhecer a mesma despesa vinda do extracto e da API do banco.

Exigir o mesmo dia deixou 113 despesas a contar a dobrar (2.619€ em três meses):
o extracto do Revolut data pelo lançamento e a API pelo processamento, com um a
três dias de diferença. Estes testes fixam a janela e — mais importante — as
recusas: juntar duas compras diferentes apaga dinheiro a sério.

Corre sozinho:  python tests/test_gemeos_banco.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta

from routers.banking import _parecidas, _primeira_palavra, JANELA_GEMEO_DIAS


class DespesaFalsa:
    """O suficiente para o emparelhamento: valor, data, nome e id."""
    def __init__(self, id, date_, amount, description):
        self.id, self.date, self.amount, self.description = id, date_, amount, description


def gemeo(candidatos, quando, valor, descricao):
    """A mesma regra do `_gemeo_do_extracto`, sem base de dados pelo meio."""
    perto = [
        e for e in candidatos
        if e.amount == valor and abs((e.date - quando).days) <= JANELA_GEMEO_DIAS
        and (e.date == quando or _parecidas(e.description or "", descricao))
    ]
    if not perto:
        return None
    return min(perto, key=lambda e: (abs((e.date - quando).days), e.id))


# ── Nomes ────────────────────────────────────────────────────────

def test_primeira_palavra_ignora_lixo():
    assert _primeira_palavra("Lidl 2043") == "lidl"
    assert _primeira_palavra("Airbnb * Hmt9e8bfrd") == "airbnb"
    assert _primeira_palavra("  ") == ""


def test_nomes_do_banco_e_do_extracto_batem():
    # casos reais que estavam a duplicar
    assert _parecidas("Vinted", "vinted")
    assert _parecidas("Lidl 2043", "Lidl")
    assert _parecidas("Rimi/rimi Kaubahall Is", "Rimi")
    assert _parecidas("Mcdonalds 262 Krakow 1", "McDonald's")
    assert _parecidas("apple.com/bill", "Apple")


def test_nomes_diferentes_nao_batem():
    assert not _parecidas("Lidl", "Auchan")
    assert not _parecidas("Uber", "Bolt")
    assert not _parecidas("", "Lidl")


def test_acentos_nao_impedem_o_emparelhamento():
    """O extracto escreve `Żabka`, a API escreve `Zabka Zd705 K.1`. Com o acento
    a contar, 17 compras ficaram a somar duas vezes."""
    assert _primeira_palavra("Żabka") == "zabka"
    assert _parecidas("Zabka Zd705 K.1", "Żabka")
    assert _parecidas("Cafe Central", "Café Central")


# ── Emparelhamento ───────────────────────────────────────────────

DIA = date(2026, 7, 22)


def test_apanha_a_gemea_do_dia_seguinte():
    extracto = [DespesaFalsa(1, DIA + timedelta(days=1), 702.57, "Vinted")]
    assert gemeo(extracto, DIA, 702.57, "vinted").id == 1


def test_apanha_ate_tres_dias():
    extracto = [DespesaFalsa(1, DIA + timedelta(days=3), 1.50, "Atac")]
    assert gemeo(extracto, DIA, 1.50, "Atac Tap&Go").id == 1


def test_nao_apanha_ao_quarto_dia():
    extracto = [DespesaFalsa(1, DIA + timedelta(days=4), 1.50, "Atac")]
    assert gemeo(extracto, DIA, 1.50, "Atac Tap&Go") is None


def test_noutro_dia_o_nome_tem_de_bater():
    # dois cafés de 3,50€ em sítios diferentes não são a mesma compra
    extracto = [DespesaFalsa(1, DIA + timedelta(days=1), 3.50, "Starbucks")]
    assert gemeo(extracto, DIA, 3.50, "Delta Cafés") is None


def test_no_mesmo_dia_o_valor_chega():
    # é a regra que já existia e que funcionava; não se perde
    extracto = [DespesaFalsa(1, DIA, 3.50, "Qualquer coisa")]
    assert gemeo(extracto, DIA, 3.50, "Outro nome").id == 1


def test_valor_diferente_nunca_junta():
    extracto = [DespesaFalsa(1, DIA, 702.58, "Vinted")]
    assert gemeo(extracto, DIA, 702.57, "vinted") is None


def test_ganha_a_mais_proxima_na_data():
    extracto = [
        DespesaFalsa(1, DIA + timedelta(days=3), 20.0, "Lidl"),
        DespesaFalsa(2, DIA + timedelta(days=1), 20.0, "Lidl"),
    ]
    assert gemeo(extracto, DIA, 20.0, "Lidl 2043").id == 2


def test_reembolsos_tambem_emparelham():
    # valores negativos (devoluções) duplicavam da mesma maneira
    extracto = [DespesaFalsa(1, DIA + timedelta(days=2), -240.85, "Vinted")]
    assert gemeo(extracto, DIA, -240.85, "vinted").id == 1


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
