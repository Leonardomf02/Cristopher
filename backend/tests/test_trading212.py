"""Tradução da API do Trading 212 para o formato da app.

O que estes testes fixam é o que a carteira passa a valer: um câmbio mal derivado
ou um ticker mal encurtado dá uma posição duplicada e um valor de carteira errado
em todos os painéis que dependem dela.

Corre sozinho:  python tests/test_trading212.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime

import trading212 as t212


# ── Tickers ──────────────────────────────────────────────────────

def test_ticker_tira_mercado_e_tipo():
    assert t212.ticker_curto("AAPL_US_EQ") == "AAPL"
    assert t212.ticker_curto("VUAAl_EQ") == "VUAA"       # l = Londres
    assert t212.ticker_curto("CNDXl_EQ") == "CNDX"
    assert t212.ticker_curto("SGLDd_EQ") == "SGLD"


def test_ticker_aguenta_lixo():
    assert t212.ticker_curto("") == ""
    assert t212.ticker_curto("NVDA") == "NVDA"
    # só minúsculas: não se pode devolver vazio, senão a posição desaparecia
    assert t212.ticker_curto("abc") == "abc"


# ── Câmbio ───────────────────────────────────────────────────────

def test_fx_derivado_bate_com_o_extracto():
    # NVDA no extracto de Maio: 0.64290532 × 200.75 USD = 129.06 USD → 110.64€
    fx = t212.fx_derivado(0.64290532, 200.75, 110.64)
    assert abs(fx - 1.16647) < 0.001


def test_fx_derivado_em_pence():
    # SSLN cota em GBX; o extracto trazia ~86.73 pence por euro
    fx = t212.fx_derivado(0.69915553, 4048.0, 32.63)
    assert abs(fx - 86.73) < 0.5


def test_fx_derivado_nunca_rebenta():
    assert t212.fx_derivado(0, 0, 0) == 1.0
    assert t212.fx_derivado(1, 10, 0) == 1.0


# ── Posições ─────────────────────────────────────────────────────

POSICAO = {
    "averagePricePaid": 189.12582649,
    "createdAt": "2026-03-17T08:00:10Z",
    "currentPrice": 200.75,
    "quantity": 0.64290532,
    "instrument": {"currency": "USD", "isin": "US67066G1040",
                   "name": "NVIDIA", "ticker": "NVDA_US_EQ"},
    "walletImpact": {"currency": "EUR", "currentValue": 110.64,
                     "totalCost": 104.24, "unrealizedProfitLoss": 6.4},
}


def test_posicao_traduzida():
    p = t212.posicao_da_api(POSICAO, "2026-08")
    assert p["instrument"] == "NVDA"
    assert p["isin"] == "US67066G1040"
    assert p["currency"] == "USD"
    assert p["quantity"] == 0.64290532
    assert p["current_value_eur"] == 110.64
    assert p["return_eur"] == 6.4
    assert p["statement_date"] == "2026-08"
    assert p["source"] == "trading212"
    assert abs(p["fx_rate"] - 1.16647) < 0.001


def test_posicao_em_euros_nao_inventa_cambio():
    em_euros = dict(POSICAO, instrument=dict(POSICAO["instrument"], currency="EUR"))
    assert t212.posicao_da_api(em_euros, "2026-08")["fx_rate"] == 1.0


def test_posicao_sem_quantidade_e_ignorada():
    assert t212.posicao_da_api(dict(POSICAO, quantity=0), "2026-08") is None
    sem_ticker = dict(POSICAO, instrument={"currency": "EUR"})
    assert t212.posicao_da_api(sem_ticker, "2026-08") is None


def test_valor_investido_reconstroi_se_pelo_cambio():
    """O resto da app calcula o investido como quantidade × preço médio ÷ câmbio.
    Se o câmbio derivado estiver errado, o retorno aparece errado em todo o lado."""
    p = t212.posicao_da_api(POSICAO, "2026-08")
    investido = p["quantity"] * p["avg_price"] / p["fx_rate"]
    assert abs(investido - (p["current_value_eur"] - p["return_eur"])) < 0.05


# ── Movimentos de dinheiro ───────────────────────────────────────

def test_deposito_e_levantamento():
    d = t212.movimento_da_api({"amount": 300.0, "currency": "EUR", "type": "DEPOSIT",
                               "dateTime": "2026-07-01T09:12:00Z", "reference": "abc-1"})
    assert d["type"] == "Depósito" and d["amount"] == 300.0 and d["external_id"] == "abc-1"

    l = t212.movimento_da_api({"amount": -50.0, "currency": "EUR", "type": "WITHDRAW",
                               "dateTime": "2026-07-02T09:12:00Z", "reference": "abc-2"})
    assert l["type"] == "Levantamento"


def test_tipo_desconhecido_entra_pelo_sinal():
    # A API pode ganhar tipos novos; o dinheiro não pode desaparecer por isso.
    m = t212.movimento_da_api({"amount": 12.0, "currency": "EUR", "type": "COISA_NOVA",
                               "dateTime": "2026-07-03T09:12:00Z"})
    assert m["type"] == "Depósito"


def test_movimento_sem_data_e_ignorado():
    assert t212.movimento_da_api({"amount": 10, "type": "DEPOSIT"}) is None


def test_dividendo_em_euros():
    d = t212.dividendo_da_api({
        "amount": 1.35, "amountInEuro": 1.21, "currency": "USD",
        "paidOn": "2026-06-20T00:00:00Z", "reference": "div-9",
        "instrument": {"ticker": "AAPL_US_EQ"},
    })
    assert d["type"] == "Dividendo" and d["amount"] == 1.21 and d["currency"] == "EUR"


def test_dividendo_de_zero_nao_conta():
    assert t212.dividendo_da_api({"amount": 0, "amountInEuro": 0,
                                  "paidOn": "2026-06-20T00:00:00Z"}) is None


# ── Ordens executadas ────────────────────────────────────────────

ORDEM = {
    "order": {
        "createdAt": "2026-02-12T08:00:11Z", "currency": "USD", "id": 48113288169,
        "instrument": {"currency": "USD", "isin": "IE00B53SZB19",
                       "name": "iShares Nasdaq 100", "ticker": "CNDXl_EQ"},
        "side": "BUY", "status": "FILLED", "ticker": "CNDXl_EQ",
    },
    "fill": {
        "filledAt": "2026-02-12T08:00:11Z", "id": 991, "price": 1450.6,
        "quantity": 0.04904062,
        "walletImpact": {
            "currency": "EUR", "fxRate": 1.18741985, "netValue": -60.0,
            "taxes": [{"name": "CURRENCY_CONVERSION_FEE", "quantity": 0.09,
                       "currency": "EUR", "chargedAt": "2026-02-12T08:00:11Z"}],
        },
    },
}


def test_ordem_traduzida():
    t = t212.ordem_da_api(ORDEM)
    assert t["instrument"] == "CNDX"
    assert t["direction"] == "Buy"
    assert t["quantity"] == 0.04904062
    assert t["execution_price"] == 1450.6
    assert t["value_eur"] == 60.0            # netValue vem negativo numa compra
    assert t["fx_fee"] == 0.09
    assert t["external_id"] == "991"
    assert t["execution_time"].year == 2026


def test_ordem_de_venda():
    venda = {"order": dict(ORDEM["order"], side="SELL"), "fill": ORDEM["fill"]}
    assert t212.ordem_da_api(venda)["direction"] == "Sell"


def test_ordem_por_executar_nao_entra():
    assert t212.ordem_da_api({"order": ORDEM["order"], "fill": {}}) is None
    assert t212.ordem_da_api({"order": ORDEM["order"],
                              "fill": dict(ORDEM["fill"], quantity=0)}) is None


def test_ordem_sem_cambio_usa_o_valor_bruto():
    sem_impacto = {"order": ORDEM["order"],
                   "fill": {"filledAt": "2026-02-12T08:00:11Z", "id": 1,
                            "price": 100.0, "quantity": 2.0}}
    t = t212.ordem_da_api(sem_impacto)
    assert t["value_eur"] == 200.0 and t["fx_fee"] == 0.0


# ── Datas ────────────────────────────────────────────────────────

def test_data_perde_o_fuso():
    d = t212._data_hora("2026-02-12T08:00:11Z")
    assert isinstance(d, datetime) and d.tzinfo is None


def test_data_invalida_devolve_none():
    assert t212._data_hora("") is None
    assert t212._data_hora("ontem") is None


# ── Autenticação ─────────────────────────────────────────────────

def test_cabecalho_basic_com_par_de_chaves():
    antigo = os.environ.get("T212_API_KEY")
    os.environ["T212_API_KEY"] = "chave:segredo"
    try:
        h = t212._cabecalhos()["Authorization"]
        assert h.startswith("Basic ")
        import base64
        assert base64.b64decode(h[6:]).decode() == "chave:segredo"
    finally:
        if antigo is None:
            os.environ.pop("T212_API_KEY", None)
        else:
            os.environ["T212_API_KEY"] = antigo


def test_cabecalho_legado_vai_em_claro():
    antigo = os.environ.get("T212_API_KEY")
    os.environ["T212_API_KEY"] = "chaveantiga123"
    try:
        assert t212._cabecalhos()["Authorization"] == "chaveantiga123"
    finally:
        if antigo is None:
            os.environ.pop("T212_API_KEY", None)
        else:
            os.environ["T212_API_KEY"] = antigo


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
