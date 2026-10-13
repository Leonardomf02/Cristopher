"""A régua do desempenho: só passa o que aguenta o teste."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lol_performance as lp


class Jogo:
    """O mínimo que as métricas precisam de um LolGame."""

    def __init__(self, cs=150, dur=1800, gold=12000, dmg=20000, vis=20,
                 kills=5, assists=8, deaths=4, team_kills=25):
        self.cs, self.game_duration = cs, dur
        self.gold, self.damage, self.vision = gold, dmg, vis
        self.kills, self.assists, self.deaths = kills, assists, deaths
        self.team_kills = team_kills


# ── O teste em si ───────────────────────────────────────────────

def test_amostra_pequena_nao_da_resultado():
    assert lp.mann_whitney([1, 2, 3], [8, 9, 10]) is None


def test_diferenca_clara_e_apanhada():
    a = [8.0 + i * 0.1 for i in range(20)]
    b = [5.0 + i * 0.1 for i in range(20)]
    z, p = lp.mann_whitney(a, b)
    assert p < 0.001 and z > 0


def test_amostras_iguais_nao_dao_sinal():
    a = [6.0 + i * 0.1 for i in range(20)]
    z, p = lp.mann_whitney(a, list(a))
    assert p > 0.9 and abs(z) < 0.1


def test_um_valor_extremo_nao_inventa_diferenca():
    """A média cairia nesta; a mediana e os postos não."""
    a = [6.0] * 15 + [200.0]
    b = [6.0] * 16
    _, p = lp.mann_whitney(a, b)
    assert p > lp.P_MAXIMO


def test_empates_nao_dao_p_optimista_de_mais():
    """Mortes são 0,1,2,3… — sem correcção de empates isto passava."""
    a = [2.0] * 10 + [3.0] * 10
    b = [2.0] * 10 + [3.0] * 10
    _, p = lp.mann_whitney(a, b)
    assert p > 0.9


# ── Métricas ────────────────────────────────────────────────────

def test_cs_por_minuto():
    assert lp.valores([Jogo(cs=180, dur=1800)], "cs_min") == [6.0]


def test_jogo_curto_de_mais_nao_conta():
    """Um remake de 4 minutos dava 40 CS/min e estragava tudo."""
    assert lp.valores([Jogo(cs=20, dur=240)], "cs_min") == []


def test_sem_dados_nao_inventa():
    assert lp.valores([Jogo(cs=None)], "cs_min") == []
    assert lp.valores([Jogo(team_kills=0)], "kp") == []


def test_participacao_em_abates():
    assert lp.valores([Jogo(kills=5, assists=15, team_kills=20)], "kp") == [1.0]


# ── Comparação ──────────────────────────────────────────────────

def test_so_devolve_o_que_passa_o_teste():
    iguais_a = [Jogo(cs=150 + i) for i in range(20)]
    iguais_b = [Jogo(cs=150 + i) for i in range(20)]
    assert lp.compara(iguais_a, iguais_b, "a", "b") == []


def test_diz_de_que_lado_e_melhor():
    bons = [Jogo(cs=200 + i, dur=1800) for i in range(20)]
    maus = [Jogo(cs=120 + i, dur=1800) for i in range(20)]
    r = lp.compara(bons, maus, "descansado", "cansado")
    cs = next(x for x in r if x["metric"] == "cs_min")
    assert cs["better_in_a"] is True
    assert cs["median_a"] > cs["median_b"]
    assert cs["p"] <= lp.P_MAXIMO


def test_mortes_sao_ao_contrario():
    """Menos mortes é melhor — não pode dizer-se que piorou."""
    poucas = [Jogo(deaths=2 + (i % 2)) for i in range(20)]
    muitas = [Jogo(deaths=9 + (i % 2)) for i in range(20)]
    r = lp.compara(poucas, muitas, "a", "b")
    mortes = next(x for x in r if x["metric"] == "deaths")
    assert mortes["better_in_a"] is True


def test_resumo_traz_mediana_e_quartis():
    r = lp.resumo([Jogo(cs=120 + i * 6, dur=1800) for i in range(20)])
    assert r["cs_min"]["n"] == 20
    assert r["cs_min"]["p25"] < r["cs_min"]["median"] < r["cs_min"]["p75"]
