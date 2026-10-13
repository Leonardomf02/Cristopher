"""Onde ele estava, a partir de onde gastou o dinheiro.

O detector antigo comparava com Portugal — e ele vive na Polónia, por isso o
Erasmus inteiro era uma viagem. Estes testes fixam a noção de casa e as armadilhas
que se descobriram nos dados reais: a Vinted é lituana, a Apple factura de Cork e
a Ryanair de Dublin.

Corre sozinho:  python tests/test_home_base.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta

import home_base as hb


class DespesaFalsa:
    def __init__(self, id, date_, amount=10.0, description="Loja",
                 merchant_city=None, merchant_country=None, original_currency=None):
        self.id, self.date, self.amount = id, date_, amount
        self.description = description
        self.merchant_city = merchant_city
        self.merchant_country = merchant_country
        self.original_currency = original_currency


def dias(inicio: date, quantos: int):
    return [inicio + timedelta(days=i) for i in range(quantos)]


# ── Onde foi a despesa ───────────────────────────────────────────

def test_a_cidade_manda():
    e = DespesaFalsa(1, date(2026, 5, 15), merchant_city="Roma", merchant_country="RM")
    assert hb.pais_da_despesa(e) == "ITA"       # "RM" é a província, não um país


def test_codigo_do_pais_quando_nao_ha_cidade():
    assert hb.pais_da_despesa(DespesaFalsa(1, date(2026, 6, 1), merchant_country="MNE")) == "MNE"
    assert hb.pais_da_despesa(DespesaFalsa(1, date(2026, 6, 1), merchant_country="BE")) == "BEL"


def test_moeda_como_ultimo_recurso():
    e = DespesaFalsa(1, date(2026, 6, 1), original_currency="PLN")
    assert hb.pais_da_despesa(e) == "POL"


def test_codigos_invalidos_nao_viram_pais():
    """"0TL" e "BAR" chegavam a aparecer como destino de viagem."""
    assert hb.pais_da_despesa(DespesaFalsa(1, date(2026, 6, 1), merchant_country="0TL")) is None
    assert hb.pais_da_despesa(DespesaFalsa(1, date(2026, 6, 1), merchant_country="BAR")) is None
    assert hb.pais_da_despesa(DespesaFalsa(1, date(2026, 6, 1), merchant_country="I")) is None


def test_compras_online_nao_provam_presenca():
    """A morada destes é a da empresa: 702€ na Vinted viravam uma ida a Vilnius
    e o iCloud virava uma ida a Cork."""
    for desc, cidade in [("vinted", "Vilnius"), ("apple.com/bill", "Cork"),
                         ("Ryanair", "Dublin"), ("Booking.com Hotel", "Amsterdam"),
                         ("Transfer to RODRIGO", "Lisboa")]:
        e = DespesaFalsa(1, date(2026, 7, 20), description=desc, merchant_city=cidade)
        assert hb.pais_da_despesa(e) is None, desc


# ── Casa ─────────────────────────────────────────────────────────

def test_casa_e_onde_passa_mais_dias():
    despesas = [DespesaFalsa(i, d, merchant_city="Krakow") for i, d in enumerate(dias(date(2026, 5, 1), 20))]
    despesas += [DespesaFalsa(100 + i, d, merchant_city="Roma") for i, d in enumerate(dias(date(2026, 5, 22), 4))]
    casas = hb.base_por_mes(despesas)
    assert casas["2026-05"] == "POL"


def test_mes_de_chegada_olha_para_as_semanas_seguintes():
    """Em Fevereiro passou por Londres a caminho de Cracóvia; contado só dentro
    do mês, Londres ganhava e a Polónia aparecia como viagem."""
    despesas = [DespesaFalsa(i, d, merchant_city="London") for i, d in enumerate(dias(date(2026, 2, 19), 4))]
    despesas += [DespesaFalsa(50 + i, d, merchant_city="Krakow") for i, d in enumerate(dias(date(2026, 2, 24), 3))]
    despesas += [DespesaFalsa(100 + i, d, merchant_city="Krakow") for i, d in enumerate(dias(date(2026, 3, 1), 20))]
    assert hb.base_por_mes(despesas)["2026-02"] == "POL"


def test_sem_dados_nao_rebenta():
    assert hb.base_por_mes([]) == {}
    assert hb.viagens([]) == []


# ── Viagens ──────────────────────────────────────────────────────

def _cenario():
    """Um mês em casa (Cracóvia) com uma ida a Roma pelo meio."""
    despesas = [DespesaFalsa(i, d, merchant_city="Krakow") for i, d in enumerate(dias(date(2026, 5, 1), 25))]
    despesas += [
        DespesaFalsa(200, date(2026, 5, 15), 40.0, "Trattoria", merchant_city="Roma"),
        DespesaFalsa(201, date(2026, 5, 16), 12.0, "Atac", merchant_city="Roma"),
        DespesaFalsa(202, date(2026, 5, 17), 8.0, "Bar", merchant_city="Venezia"),
    ]
    return despesas


def test_uma_ida_fora_de_casa_e_uma_viagem():
    vs = hb.viagens(_cenario())
    assert len(vs) == 1
    v = vs[0]
    assert v["country"] == "ITA"
    assert v["start"] == date(2026, 5, 15) and v["end"] == date(2026, 5, 17)
    assert v["total"] == 60.0
    assert v["cities"] == ["Roma", "Veneza"]


def test_os_dias_em_casa_nunca_sao_viagem():
    assert all(v["country"] != "POL" for v in hb.viagens(_cenario()))


def test_uma_despesa_solta_nao_chega_para_viagem():
    despesas = [DespesaFalsa(i, d, merchant_city="Krakow") for i, d in enumerate(dias(date(2026, 5, 1), 25))]
    despesas.append(DespesaFalsa(300, date(2026, 5, 10), 20.0, "Loja", merchant_city="Berlin"))
    assert hb.viagens(despesas) == []


def test_dias_seguidos_ficam_na_mesma_viagem():
    despesas = [DespesaFalsa(i, d, merchant_city="Krakow") for i, d in enumerate(dias(date(2026, 5, 1), 25))]
    # 15 e 18 de Maio: três dias de intervalo → duas idas distintas
    despesas += [
        DespesaFalsa(400, date(2026, 5, 5), 10.0, "A", merchant_city="Roma"),
        DespesaFalsa(401, date(2026, 5, 6), 10.0, "B", merchant_city="Roma"),
        DespesaFalsa(402, date(2026, 5, 20), 10.0, "C", merchant_city="Roma"),
        DespesaFalsa(403, date(2026, 5, 21), 10.0, "D", merchant_city="Roma"),
    ]
    vs = [v for v in hb.viagens(despesas) if v["country"] == "ITA"]
    assert len(vs) == 2


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
