"""Os gráficos do histórico: a régua, as médias móveis e os dias marcados.

Três coisas que se partem em silêncio e sem dar erro nenhum:

- uma **faixa feita de três dias** parece uma régua e não é nenhuma. Abaixo de
  `MINIMO_BASELINE` não pode sair faixa, saia o que sair;
- a **média de 7 dias do primeiro dia da janela** precisa dos 6 dias anteriores
  a ela. Sem os ler, o gráfico começa sempre com um buraco — e ninguém repara,
  porque o resto da linha está lá;
- os **dias marcados** nos gráficos e o sinal de doença da Leitura têm de ser a
  mesma regra. Foi a lição da cópia do `ai_config` dentro dos sinais.

Corre sozinho:  python tests/test_garmin_historico.py
"""
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import garmin_insights as gi
from models import Base, GarminDay
from routers.garmin import historico


def _sessao():
    tmp = Path(tempfile.mkdtemp()) / "teste.db"
    motor = create_engine(f"sqlite:///{tmp}")
    Base.metadata.create_all(motor)
    return sessionmaker(bind=motor)()


def _dias(db, quantos, **campos):
    """`quantos` dias a acabar hoje. Cada campo é uma lista do mais antigo para
    o mais recente, ou um valor só para repetir."""
    hoje = date.today()
    for i in range(quantos):
        d = GarminDay(date=hoje - timedelta(days=quantos - 1 - i))
        for nome, valores in campos.items():
            setattr(d, nome, valores[i] if isinstance(valores, list) else valores)
        db.add(d)
    db.commit()


# ── a régua ──────────────────────────────────────────────────────

def test_a_faixa_nao_se_faz_com_tres_dias():
    r = gi.regua([50, 52, 51])
    assert r["median"] is None, "três dias não são régua nenhuma"
    assert r["n"] == 3, "mas diz-se quantos há, para a página poder dizer quantos faltam"


def test_a_faixa_e_a_mesma_fronteira_do_desvio():
    """Estar fora da faixa tem de ser exactamente ter |z| > 1 — senão o gráfico
    e os factos da Leitura discordam sobre o mesmo dia."""
    vals = [48, 50, 51, 52, 53, 53, 54, 55, 57, 60]
    r = gi.regua(vals)
    for v in (r["high"] + 0.5, r["low"] - 0.5):
        z = gi._desvio(v, vals)["z"]
        assert abs(z) > 1, f"{v} está fora da faixa mas dá z={z:.2f}"
    z = gi._desvio(r["median"], vals)["z"]
    assert abs(z) < 0.01, "a mediana tem de dar z=0"


def test_quem_nao_varia_nao_fica_com_a_regua_apertada():
    """MAD zero sem piso é uma faixa de largura zero: qualquer dia cai fora."""
    iguais = [54] * 10
    assert gi.regua(iguais)["high"] > 54, "sem piso, a faixa fecha-se sobre a mediana"
    assert gi.regua(iguais, mad_min=1.0)["high"] >= 55


# ── as médias móveis ─────────────────────────────────────────────

def test_o_primeiro_dia_da_janela_ja_tem_media_movel():
    """É isto que prova que se lêem os 6 dias anteriores à janela pedida."""
    db = _sessao()
    _dias(db, 20, hrv_last_night=list(range(40, 60)), resting_hr=54)
    saida = historico(days=7, db=db)
    assert saida[0]["hrv_avg7"] is not None, "o gráfico começaria com um buraco"
    assert saida[0]["rhr_avg7"] == 54


def test_a_media_movel_nao_se_faz_com_uma_leitura_so():
    db = _sessao()
    _dias(db, 10, hrv_last_night=[None] * 8 + [50, 60])
    saida = historico(days=10, db=db)
    assert saida[-1]["hrv_avg7"] is None, "duas noites não são uma média de sete dias"


def test_os_minutos_vigorosos_contam_a_dobrar():
    db = _sessao()
    _dias(db, 7, intensity_moderate_min=10, intensity_vigorous_min=5)
    saida = historico(days=7, db=db)
    assert saida[-1]["intensity_7d"] == 7 * (10 + 2 * 5), "é assim que a Garmin os conta"


def test_os_dias_a_mais_nao_saem_na_resposta():
    db = _sessao()
    _dias(db, 30, steps=5000)
    saida = historico(days=7, db=db)
    assert all(p["date"] >= (date.today() - timedelta(days=7)).isoformat() for p in saida)


# ── os dias marcados ─────────────────────────────────────────────

# Dias normais com a variação que dias normais têm. Com doze leituras iguais o
# MAD dá zero, o `_desvio` cai no seu recurso dos 15% da mediana e deixa de ver
# o que quer que seja — a régua precisa de ruído para ter largura.
FC_NORMAL = [52, 54, 53, 55, 52, 56, 54, 53, 55, 52, 54, 53]
HRV_NORMAL = [50, 54, 52, 56, 51, 55, 53, 49, 57, 52, 54, 50]


def test_os_dias_marcados_sao_a_regra_da_leitura():
    """Dois dias seguidos com a frequência acima e o HRV abaixo. A lista dos
    gráficos e o facto da Leitura têm de apontar para o mesmo dia."""
    db = _sessao()
    _dias(db, len(FC_NORMAL) + 2,
          resting_hr=FC_NORMAL + [72, 73],
          hrv_last_night=HRV_NORMAL + [20, 19])
    hoje = date.today()
    marcados = gi.alertas_de_doenca(db, hoje - timedelta(days=14), hoje)
    assert marcados == [hoje.isoformat()], f"esperava só hoje, deu {marcados}"
    assert gi._sinal_de_doenca(db, hoje), "a Leitura tem de dizer o mesmo"


def test_um_dia_mau_sozinho_nao_e_alerta():
    db = _sessao()
    _dias(db, len(FC_NORMAL) + 1,
          resting_hr=FC_NORMAL + [72],
          hrv_last_night=HRV_NORMAL + [20])
    hoje = date.today()
    assert gi.alertas_de_doenca(db, hoje - timedelta(days=14), hoje) == []
    assert not gi._sinal_de_doenca(db, hoje)


def test_as_reguas_dizem_de_onde_vem_a_faixa():
    """A do relógio ganha à da app assim que existir — mas só existe ao fim de
    ~19 noites, e até lá a app tem de assumir que a faixa é dela."""
    db = _sessao()
    _dias(db, 12, hrv_last_night=[48, 50, 51, 52, 53, 53, 54, 55, 57, 60, 52, 51],
          resting_hr=54)
    assert gi.baselines(db, dias=30)["metrics"]["hrv"]["source"] == "app"

    for d in db.query(GarminDay).all():
        d.hrv_baseline_low, d.hrv_baseline_high = 45, 62
    db.commit()
    hrv = gi.baselines(db, dias=30)["metrics"]["hrv"]
    assert (hrv["source"], hrv["low"], hrv["high"]) == ("garmin", 45, 62)


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok  {nome}")
            except AssertionError as e:
                falhas += 1
                print(f"FALHA  {nome}: {e}")
    print("tudo bem" if not falhas else f"{falhas} falhas")
    raise SystemExit(1 if falhas else 0)
