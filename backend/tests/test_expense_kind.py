"""Que movimentos são gasto e quais não são.

Enganar-se para um lado inflaciona os gastos (uma transferência para a corretora
aparecia como 300€ gastos); para o outro, esconde consumo a sério. Os casos aqui
são todos tirados da conta dele.

Corre sozinho:  python tests/test_expense_kind.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta

import expense_kind as ek


class DespesaFalsa:
    def __init__(self, id, date_, amount, description, kind=ek.GASTO):
        self.id, self.date, self.amount = id, date_, amount
        self.description, self.kind = description, kind


# ── Transferências ───────────────────────────────────────────────

def test_dinheiro_para_a_corretora_nao_e_gasto():
    assert ek.classifica("Trading 212", "invest", 300.0) == ek.TRANSFERENCIA
    assert ek.classifica("Trading 212", "other", 300.0) == ek.TRANSFERENCIA
    assert ek.classifica("3397922844X355cc DPT_1zyYN64 To Finst B.V.", "invest", 90.0) == ek.TRANSFERENCIA


def test_dinheiro_que_volta_da_corretora_tambem_e_transferencia():
    # o sinal não muda a natureza do movimento
    assert ek.classifica("Trading 212", "invest", -310.0) == ek.TRANSFERENCIA
    assert ek.classifica(
        "Withdrawal from Finst PAYgMDkpoh72 Payment from Stichting Finst Custody",
        "invest", -221.14,
    ) == ek.TRANSFERENCIA


def test_categoria_invest_chega_para_ser_transferencia():
    assert ek.classifica("Qualquer coisa", "invest", 50.0) == ek.TRANSFERENCIA


def test_passar_dinheiro_da_caixa_para_o_revolut_nao_e_gasto():
    """A Caixa corta a descrição: "CAR WAL CRT DEB REVOL" é carregar a carteira
    do Revolut com o cartão de débito dela. Eram 15 movimentos e 2.235€ a contar
    como consumo — e ainda por cima como "viagens"."""
    assert ek.classifica("CAR WAL CRT DEB REVOL", "travel", 100.0) == ek.TRANSFERENCIA
    assert ek.classifica("CAR WAL CRT DEB REVOL", "other", 600.0) == ek.TRANSFERENCIA
    assert ek.classifica("Carregamento carteira Revolut", "other", 50.0) == ek.TRANSFERENCIA


def test_o_revolut_num_gasto_a_serio_continua_gasto():
    """Só o carregamento faz de um movimento uma transferência; o nome não."""
    assert ek.classifica("COMPRAS C.DEB REVOLUT COMISSAO", "other", 3.9) == ek.GASTO
    assert ek.classifica("Cash withdrawal Revolut", "other", 50.0) == ek.GASTO


def test_carregar_a_conta_e_transferencia():
    assert ek.classifica("Top-up by *1234", "other", 100.0) == ek.TRANSFERENCIA
    assert ek.classifica("Carregamento de conta", "other", 100.0) == ek.TRANSFERENCIA


# ── Gastos e entradas a sério ────────────────────────────────────

def test_compra_normal_e_gasto():
    assert ek.classifica("Lidl 2043", "groceries", 26.27) == ek.GASTO
    assert ek.classifica("vinted", "shopping", 702.57) == ek.GASTO


def test_dinheiro_de_um_amigo_e_entrada_nao_transferencia():
    """Rodrigo a devolver a parte dele é dinheiro que entrou — não é a conta
    dele a mudar de sítio."""
    assert ek.classifica("Transfer from RODRIGO DE SOUSA", "travel", -8.62) == ek.ENTRADA


def test_pagar_a_um_amigo_e_gasto():
    assert ek.classifica("Transfer to RODRIGO DE SOUSA", "travel", 22.5) == ek.GASTO


def test_reembolso_e_entrada():
    assert ek.classifica("Ryanair", "travel", -35.0) == ek.ENTRADA


# ── Estornos ─────────────────────────────────────────────────────

def test_compra_que_volta_atras_marca_as_duas_pernas():
    despesas = [
        DespesaFalsa(1, date(2026, 7, 20), 345.85, "vinted"),
        DespesaFalsa(2, date(2026, 7, 27), -345.85, "vinted"),
    ]
    assert ek.marca_estornos(despesas) == 2
    assert all(d.kind == ek.ESTORNO for d in despesas)


def test_nomes_diferentes_nao_sao_estorno():
    despesas = [
        DespesaFalsa(1, date(2026, 7, 20), 50.0, "Lidl"),
        DespesaFalsa(2, date(2026, 7, 21), -50.0, "Ryanair"),
    ]
    assert ek.marca_estornos(despesas) == 0


def test_devolucao_antes_da_compra_nao_conta():
    despesas = [
        DespesaFalsa(1, date(2026, 7, 20), 50.0, "Vinted"),
        DespesaFalsa(2, date(2026, 7, 10), -50.0, "Vinted"),
    ]
    assert ek.marca_estornos(despesas) == 0


def test_fora_da_janela_nao_conta():
    despesas = [
        DespesaFalsa(1, date(2026, 6, 1), 50.0, "Vinted"),
        DespesaFalsa(2, date(2026, 6, 1) + timedelta(days=40), -50.0, "Vinted"),
    ]
    assert ek.marca_estornos(despesas) == 0


def test_cada_devolucao_so_serve_uma_compra():
    """Duas compras iguais e uma só devolução: fica um gasto a sério de pé."""
    despesas = [
        DespesaFalsa(1, date(2026, 7, 1), 20.0, "Vinted"),
        DespesaFalsa(2, date(2026, 7, 2), 20.0, "Vinted"),
        DespesaFalsa(3, date(2026, 7, 3), -20.0, "Vinted"),
    ]
    ek.marca_estornos(despesas)
    assert [d.kind for d in despesas] == [ek.ESTORNO, ek.GASTO, ek.ESTORNO]


def test_valores_diferentes_nunca_emparelham():
    despesas = [
        DespesaFalsa(1, date(2026, 7, 1), 20.0, "Vinted"),
        DespesaFalsa(2, date(2026, 7, 2), -19.99, "Vinted"),
    ]
    assert ek.marca_estornos(despesas) == 0


# ── Resumo ───────────────────────────────────────────────────────

def test_resumo_separa_as_quatro_coisas():
    despesas = [
        DespesaFalsa(1, date(2026, 7, 1), 100.0, "Lidl", ek.GASTO),
        DespesaFalsa(2, date(2026, 7, 2), -30.0, "Reembolso", ek.ENTRADA),
        DespesaFalsa(3, date(2026, 7, 3), 300.0, "Trading 212", ek.TRANSFERENCIA),
        DespesaFalsa(4, date(2026, 7, 4), 50.0, "Vinted", ek.ESTORNO),
        DespesaFalsa(5, date(2026, 7, 5), -50.0, "Vinted", ek.ESTORNO),
    ]
    r = ek.resume(despesas)
    assert r["spent"] == 100.0          # só o Lidl
    assert r["income"] == 30.0          # entrada com sinal positivo
    assert r["transfers"] == 300.0
    assert r["reversed"] == 50.0        # o par conta uma vez
    assert r["net"] == 70.0             # gasto menos entradas


# ── Casos que já enganaram o classificador ───────────────────────

def test_notas_da_app_nao_fazem_de_uma_compra_uma_transferencia():
    """Metade do histórico tem "Importado do Revolut PDF" nas notas. Olhar para
    as notas classificava tudo isso como transferência."""
    assert ek.classifica("GitHub", "subscriptions", 8.39, "Importado do Revolut PDF") == ek.GASTO
    assert ek.classifica("Lidl", "groceries", 12.0, "do banco · 51.00 PLN") == ek.GASTO


def test_o_nome_do_proprio_banco_nao_e_transferencia():
    # comissões e levantamentos ao balcão são gastos a sério
    assert ek.classifica("Revolut Bank UAB Sucursal em Portugal", "other", 3.9) == ek.GASTO


def test_levantar_dinheiro_continua_a_ser_gasto():
    """Ele não regista o que faz com o dinheiro vivo — tratá-lo como
    transferência fazia desaparecer o consumo."""
    assert ek.classifica("Cash at Ziraat Bank", "other", 50.0) == ek.GASTO
    assert ek.classifica("Cash withdrawal at Yuan Massage", "health", 45.95) == ek.GASTO


def test_pessoas_diferentes_nao_se_anulam():
    """10€ para o Nuno e 10€ que vieram do Rodrigo não são um estorno."""
    despesas = [
        DespesaFalsa(1, date(2026, 5, 25), 10.0, "Transfer to NUNO JOSE FREITAS"),
        DespesaFalsa(2, date(2026, 6, 9), -10.0, "Transfer from RODRIGO DE SOUSA"),
    ]
    assert ek.marca_estornos(despesas) == 0


def test_a_mesma_pessoa_a_devolver_e_estorno():
    despesas = [
        DespesaFalsa(1, date(2026, 6, 8), 1.5, "Transfer to RODRIGO DE SOUSA"),
        DespesaFalsa(2, date(2026, 6, 9), -1.5, "Transfer from RODRIGO DE SOUSA"),
    ]
    assert ek.marca_estornos(despesas) == 2


def test_devolucao_da_caixa_com_prefixo_anula_a_compra():
    """A GoPro cobrou `GOPRO.C` e devolveu como `CR VCHER CRT DB GOPRO`."""
    despesas = [
        DespesaFalsa(1, date(2026, 9, 7), 59.99, "GOPRO.C"),
        DespesaFalsa(2, date(2026, 9, 24), -59.99, "CR VCHER CRT DB GOPRO"),
    ]
    assert ek.marca_estornos(despesas) == 2


def test_mbway_para_pessoas_diferentes_nao_se_anula():
    despesas = [
        DespesaFalsa(1, date(2026, 9, 9), 30.0, "TRF MBWAY 963XXX836"),
        DespesaFalsa(2, date(2026, 9, 12), -30.0, "TRF MBWAY 927XXX207"),
    ]
    assert ek.marca_estornos(despesas) == 0


def test_mbway_devolvido_pelo_mesmo_numero_e_estorno():
    despesas = [
        DespesaFalsa(1, date(2026, 9, 9), 30.0, "TRF MBWAY 963XXX836"),
        DespesaFalsa(2, date(2026, 9, 12), -30.0, "TRF MBWAY 963XXX836"),
    ]
    assert ek.marca_estornos(despesas) == 2


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
