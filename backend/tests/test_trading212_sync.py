"""A sincronização do Trading 212 contra uma base a sério (temporária).

O que se está a testar é o que corre todos os dias: não duplicar o que já veio
dos extractos em PDF, não duplicar o que já veio da própria API, e tirar da
carteira o que ele vendeu. Enganar-se aqui não dá erro nenhum — dá um valor de
carteira errado em todos os painéis.

Corre sozinho:  python tests/test_trading212_sync.py
"""
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import trading212 as t212
from models import Base, InvestmentPosition, InvestmentTrade, InvestmentTransaction

MES = "2026-08"
HOJE = date(2026, 8, 2)


def _sessao():
    tmp = Path(tempfile.mkdtemp()) / "teste.db"
    motor = create_engine(f"sqlite:///{tmp}")
    Base.metadata.create_all(motor)
    return sessionmaker(bind=motor)()


def _posicao(ticker="NVDA_US_EQ", isin="US67066G1040", qtd=0.64290532):
    return {
        "averagePricePaid": 189.12582649, "currentPrice": 200.75, "quantity": qtd,
        "instrument": {"currency": "USD", "isin": isin, "name": "NVIDIA", "ticker": ticker},
        "walletImpact": {"currency": "EUR", "currentValue": 110.64,
                         "totalCost": 104.24, "unrealizedProfitLoss": 6.4},
    }


def _ordem(id_=991, quando="2026-02-12T08:00:11Z", qtd=0.04904062):
    return {
        "order": {"createdAt": quando, "currency": "USD", "id": 48113288169,
                  "instrument": {"currency": "USD", "isin": "IE00B53SZB19",
                                 "name": "iShares", "ticker": "CNDXl_EQ"},
                  "side": "BUY", "status": "FILLED", "ticker": "CNDXl_EQ"},
        "fill": {"filledAt": quando, "id": id_, "price": 1450.6, "quantity": qtd,
                 "walletImpact": {"currency": "EUR", "fxRate": 1.18741985, "netValue": -60.0,
                                  "taxes": []}},
    }


def _movimento(ref="dep-1", quando="2026-07-01T09:12:00Z", montante=300.0):
    return {"amount": montante, "currency": "EUR", "type": "DEPOSIT",
            "dateTime": quando, "reference": ref}


def _liga_api(monkeypatch_alvo, posicoes=(), ordens=(), movs=(), divs=(), resumo=None):
    """Substitui as chamadas de rede por listas fixas."""
    guardadas = {
        "posicoes": t212.posicoes, "ordens_historicas": t212.ordens_historicas,
        "movimentos": t212.movimentos, "dividendos": t212.dividendos,
        "resumo_da_conta": t212.resumo_da_conta,
    }
    t212.posicoes = lambda: list(posicoes)
    t212.ordens_historicas = lambda **kw: iter(list(ordens))
    t212.movimentos = lambda **kw: iter(list(movs))
    t212.dividendos = lambda **kw: iter(list(divs))
    t212.resumo_da_conta = lambda: (resumo or {})
    monkeypatch_alvo.append(guardadas)


def _repoe(guardadas):
    for nome, fn in guardadas[0].items():
        setattr(t212, nome, fn)


def _corre(db, **kw):
    repor = []
    _liga_api(repor, **kw)
    try:
        return t212.sincroniza(db, hoje=HOJE)
    finally:
        _repoe(repor)


# ── Posições ─────────────────────────────────────────────────────

def test_primeira_leitura_cria_a_posicao():
    db = _sessao()
    r = _corre(db, posicoes=[_posicao()])
    assert r["positions"] == 1
    p = db.query(InvestmentPosition).one()
    assert p.instrument == "NVDA" and p.statement_date == MES and p.source == "trading212"
    assert p.current_value_eur == 110.64


def test_segunda_leitura_actualiza_em_vez_de_duplicar():
    db = _sessao()
    _corre(db, posicoes=[_posicao()])
    _corre(db, posicoes=[_posicao(qtd=1.5)])
    linhas = db.query(InvestmentPosition).all()
    assert len(linhas) == 1
    assert linhas[0].quantity == 1.5


def test_o_nome_antigo_ganha_pelo_isin():
    """As posições já gravadas usam o símbolo do extracto. Se a API trouxer outro
    nome para o mesmo ISIN, trocá-lo partia o histórico do instrumento."""
    db = _sessao()
    db.add(InvestmentPosition(instrument="NVDA", isin="US67066G1040", currency="USD",
                              quantity=0.5, avg_price=180.0, source="trading212",
                              statement_date="2026-05"))
    db.commit()
    _corre(db, posicoes=[_posicao(ticker="NVDAX_US_EQ")])
    nomes = {p.instrument for p in db.query(InvestmentPosition).all()}
    assert nomes == {"NVDA"}


def test_posicao_vendida_sai_do_mes():
    db = _sessao()
    _corre(db, posicoes=[_posicao(), _posicao(ticker="AAPL_US_EQ", isin="US0378331005")])
    assert db.query(InvestmentPosition).count() == 2
    _corre(db, posicoes=[_posicao()])            # vendeu a Apple
    restantes = [p.instrument for p in db.query(InvestmentPosition).all()]
    assert restantes == ["NVDA"]


def test_meses_anteriores_ficam_intactos():
    db = _sessao()
    db.add(InvestmentPosition(instrument="VUAA", isin="IE00BFMXXD54", currency="EUR",
                              quantity=1.0, avg_price=100.0, source="trading212",
                              statement_date="2026-05"))
    db.commit()
    _corre(db, posicoes=[_posicao()])
    meses = sorted({p.statement_date for p in db.query(InvestmentPosition).all()})
    assert meses == ["2026-05", MES]


# ── Ordens ───────────────────────────────────────────────────────

def test_ordem_nova_entra_uma_vez_so():
    db = _sessao()
    r1 = _corre(db, ordens=[_ordem()])
    r2 = _corre(db, ordens=[_ordem()])
    assert r1["trades"] == 1 and r2["trades"] == 0
    assert db.query(InvestmentTrade).count() == 1


def test_ordem_ja_importada_do_pdf_nao_duplica():
    db = _sessao()
    # Hora local no extracto, UTC na API: o mesmo negócio, uma hora de diferença.
    db.add(InvestmentTrade(
        execution_time=datetime(2026, 2, 12, 9, 0, 11), instrument="CNDX",
        isin="IE00B53SZB19", currency="USD", direction="Buy", quantity=0.04904062,
        execution_price=1450.6, value=71.14, value_eur=60.0, fx_rate=1.187,
        source="trading212",
    ))
    db.commit()
    r = _corre(db, ordens=[_ordem()])
    assert r["trades"] == 0
    assert db.query(InvestmentTrade).count() == 1


def test_duas_execucoes_da_mesma_ordem_contam_as_duas():
    """Execuções parciais partilham instante e quantidade — só a referência as
    distingue. Se se perdesse uma, faltava dinheiro na carteira."""
    db = _sessao()
    r = _corre(db, ordens=[_ordem(id_=1), _ordem(id_=2)])
    assert r["trades"] == 2


# ── Movimentos de dinheiro ───────────────────────────────────────

def test_deposito_entra_uma_vez():
    db = _sessao()
    r1 = _corre(db, movs=[_movimento()])
    r2 = _corre(db, movs=[_movimento()])
    assert r1["transactions"] == 1 and r2["transactions"] == 0
    assert db.query(InvestmentTransaction).one().type == "Depósito"


def test_deposito_ja_vindo_do_pdf_nao_duplica():
    db = _sessao()
    # O extracto marca 09:12 locais para o que a API dá como 08:12 UTC: é o mesmo
    # depósito, e emparelhar ao segundo deixava-o entrar duas vezes.
    db.add(InvestmentTransaction(time=datetime(2026, 7, 1, 9, 12), type="Depósito",
                                 currency="EUR", amount=300.0, source="trading212"))
    db.commit()
    r = _corre(db, movs=[_movimento(quando="2026-07-01T08:12:00Z")])
    assert r["transactions"] == 0
    assert db.query(InvestmentTransaction).count() == 1


def test_dois_depositos_iguais_no_mesmo_dia_contam_os_dois():
    db = _sessao()
    r = _corre(db, movs=[_movimento(ref="a"), _movimento(ref="b")])
    assert r["transactions"] == 2


def test_dividendos_entram_como_transaccao():
    db = _sessao()
    r = _corre(db, divs=[{
        "amount": 1.35, "amountInEuro": 1.21, "currency": "USD",
        "paidOn": "2026-06-20T00:00:00Z", "reference": "div-9",
        "instrument": {"ticker": "AAPL_US_EQ"},
    }])
    assert r["dividends"] == 1
    assert db.query(InvestmentTransaction).one().type == "Dividendo"


# ── Resumo da conta ──────────────────────────────────────────────

def test_resumo_grava_o_valor_da_conta():
    db = _sessao()
    # O depósito tem de ser do mês corrente: o resumo é por mês, como os extractos.
    r = _corre(db, posicoes=[_posicao()],
               movs=[_movimento(quando="2026-08-01T09:12:00Z")], resumo={
        "totalValue": 1234.56, "currency": "EUR",
        "investments": {"unrealizedProfitLoss": 6.4, "totalCost": 104.24},
    })
    from models import InvestmentSummary
    linha = db.query(InvestmentSummary).one()
    assert r["account_value"] == 1234.56
    assert linha.statement_date == date(2026, 8, 1)
    assert linha.deposits == 300.0


def test_api_em_baixo_nao_estraga_o_resto():
    """Se as listas históricas falharem, as posições já lidas ficam e o erro
    aparece no relatório em vez de rebentar o trabalho todo."""
    db = _sessao()
    repor = []
    _liga_api(repor, posicoes=[_posicao()])

    def rebenta(**kw):
        raise t212.T212Indisponivel("limite de pedidos")

    t212.ordens_historicas = rebenta
    try:
        r = t212.sincroniza(db, hoje=HOJE)
    finally:
        _repoe(repor)
    assert r["positions"] == 1
    assert any("ordens" in e for e in r["errors"])
    assert db.query(InvestmentPosition).count() == 1


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
