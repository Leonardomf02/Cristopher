"""O duelo com o jungler adversário, e a recomendação de campeões.

Os números vieram todos dos 500 jogos reais que estão na base — incluindo os que
partiram a primeira versão (o `d1` da lolalytics, que parecia o campo certo e
tem um viés de dez pontos percentuais).
"""
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lol_duel as ld
import lol_picks as lp


# ── Wilcoxon emparelhado ────────────────────────────────────────

def _p_exacto(d):
    """Distribuição exacta por enumeração — referência independente da
    aproximação normal que o módulo usa. Só serve para amostras pequenas."""
    d = [x for x in d if x != 0]
    n = len(d)
    ordem = sorted(range(n), key=lambda i: abs(d[i]))
    rank = [0] * n
    for pos, i in enumerate(ordem):
        rank[i] = pos + 1
    w = sum(rank[i] for i in range(n) if d[i] > 0)
    todos = [sum(s) for k in range(n + 1) for s in itertools.combinations(rank, k)]
    mu = n * (n + 1) / 4
    extremo = abs(w - mu)
    return sum(1 for t in todos if abs(t - mu) >= extremo) / len(todos)


def test_wilcoxon_bate_com_a_distribuicao_exacta():
    """A aproximação normal tem de dar o mesmo que contar todos os casos."""
    casos = [
        [1.5, -2.0, 3.1, 0.4, -0.7, 2.2, 1.1, -3.3, 0.9, 4.0, -1.2, 2.8],
        [0.3, 0.8, -1.4, 2.6, 1.9, -0.2, 3.3, 0.5, -2.1, 1.2, 0.7, 2.4, 1.8, -0.9],
    ]
    for d in casos:
        z, p = ld.wilcoxon(d)
        assert abs(p - _p_exacto(d)) < 0.05


def test_wilcoxon_e_simetrico():
    """Trocar os dois lados do duelo dá o mesmo p e o z ao contrário — senão a
    régua dependia de quem se põe primeiro."""
    d = [2.0, -1.0, 3.5, 0.5, -2.5, 1.5, 4.0, -0.5, 2.5, 1.0, -3.0, 0.8, 1.7]
    z1, p1 = ld.wilcoxon(d)
    z2, p2 = ld.wilcoxon([-x for x in d])
    assert p1 == p2
    assert z1 == -z2


def test_wilcoxon_cala_se_com_poucos_jogos():
    assert ld.wilcoxon([1.0] * (ld.MINIMO - 1)) is None


def test_wilcoxon_ignora_os_empates():
    """As diferenças zero saem do teste, como manda o Wilcoxon — e se sobrarem
    poucas, não se diz nada em vez de se dizer uma coisa qualquer."""
    assert ld.wilcoxon([0.0] * 50 + [1.0, 2.0, 3.0]) is None


def test_empates_apertam_o_teste_em_vez_de_o_alargar():
    """Wards de controlo são 0, 1, 2 — cheio de empates em |d|. Sem a correcção
    da variância o p saía optimista de mais."""
    d = [1.0] * 20 + [-1.0] * 8
    z, p = ld.wilcoxon(d)
    assert 0 < p < 0.05
    assert z > 0


# ── As métricas ─────────────────────────────────────────────────

class _Duelo:
    """Uma linha de `lol_duels` só com o que o módulo lê."""
    def __init__(self, **kw):
        for chave, _, coluna, _, _ in ld.METRICAS:
            setattr(self, coluna, None)
            setattr(self, f"opp_{coluna}", None)
        self.champion = kw.pop("champion", "Khazix")
        self.won = kw.pop("won", True)
        for k, v in kw.items():
            setattr(self, k, v)


def test_separa_o_que_e_conselho_do_que_e_consequencia():
    """A divisão é o ponto todo: perder CS de selva aos 10 é conselho, fazer
    dragões é a descrição de ter ganho."""
    momentos = {chave: momento for chave, _, _, _, momento in ld.METRICAS}
    assert momentos["jungle_cs10"] == "cedo"
    assert momentos["gd15"] == "cedo"
    assert momentos["early_ganks"] == "cedo"
    assert momentos["dragons"] == "jogo"
    assert momentos["gold_min"] == "jogo"


def test_ganha_pct_e_sobre_os_jogos_que_se_decidiram():
    """Ele ganha os abates em laners cedo em 46% de *todos* os jogos e empata em
    30% deles. Contar os empates dava a leitura ao contrário do que o teste diz."""
    duelos = ([_Duelo(control_wards=1, opp_control_wards=0)] * 12 +
              [_Duelo(control_wards=0, opp_control_wards=1)] * 6 +
              [_Duelo(control_wards=0, opp_control_wards=0)] * 20)
    linha = next(m for m in ld.compara(duelos) if m["metric"] == "control_wards")
    assert linha["win_pct"] == 67          # 12 de 18 decididos, não 12 de 38
    assert linha["tie_pct"] == 53


def test_diferencas_da_timeline_nao_inventam_um_adversario():
    """gd15 já é a diferença; não há coluna do adversário para mostrar."""
    duelos = [_Duelo(gd15=300 if i % 3 else -200) for i in range(30)]
    linha = next(m for m in ld.compara(duelos) if m["metric"] == "gd15")
    assert linha["theirs"] is None
    assert linha["mine"] == linha["diff"]


def test_o_que_nao_passa_tambem_aparece():
    """Ao contrário do `/performance`, aqui o que empata é resposta: "no dano
    por minuto estás a par do adversário" é informação."""
    duelos = [_Duelo(damage_min=700 + (i % 5) - 2, opp_damage_min=700) for i in range(40)]
    linha = next(m for m in ld.compara(duelos) if m["metric"] == "damage_min")
    assert linha["proven"] is False


# ── A recomendação ──────────────────────────────────────────────

def test_dominar_o_campeao_nao_custa_nada():
    """A curva da maestria satura cedo (de 75 mil para 175 mil pontos o ganho é
    menos de 1pp), por isso os campeões que ele já sabe jogar não levam castigo —
    mesmo que nunca os tenha jogado nesta posição."""
    assert lp.custo_de_aprender(177_076, 0) == (0.0, "à-vontade")
    assert lp.custo_de_aprender(0, 12) == (0.0, "à-vontade")


def test_pegar_num_campeao_de_raiz_custa_o_que_custa():
    custo, _ = lp.custo_de_aprender(1_200, 0)
    assert custo == -6.0
    assert lp.custo_de_aprender(40_000, 0)[0] > custo


def test_o_winrate_por_campeao_dele_nao_decide_nada():
    """Mediu-se: a variância dos edges dele (5,9pp) é menor do que o ruído que se
    esperaria por acaso (10,6pp). 60% de Wukong em 50 jogos e 44,9% de Lee Sin em
    98 não são distinguíveis de uma moeda ao ar, e dar-lhes peso punha o Wukong
    em primeiro contra onze dos doze junglers que ele mais encontra."""
    assert lp._a_vontade(60.0, 51.7, 50) == 0.0
    assert lp._a_vontade(44.9, 49.1, 98) == 0.0
    assert lp._a_vontade(100.0, 50.0, 2) == 0.0


def test_o_winrate_do_meta_encolhe_nos_campeoes_de_nicho():
    """Gragas jungle: 57,5% em 3.083 jogos. Lee Sin: 49,1% em 54.770. O primeiro
    é o winrate de quem o domina tanto quanto o do campeão."""
    nicho = lp._wr_do_meta({"wr": 57.5, "games": 3083})
    popular = lp._wr_do_meta({"wr": 49.1, "games": 54770})
    assert nicho < 57.5
    assert abs(popular - 49.1) < 0.1


def test_matchup_com_pouca_amostra_quase_nao_conta():
    """"Teemo jungle ganha 8,4pp ao Viego" em 40 jogos não pode valer o mesmo
    que um matchup medido em 3.469."""
    poucos = {"Viego": {"teemo": {"effect": 8.4, "games": 40, "champion_key": "Teemo"}}}
    muitos = {"Viego": {"khazix": {"effect": 2.4, "games": 3469, "champion_key": "Khazix"}}}
    e_poucos, _ = lp._matchup("teemo", poucos)
    e_muitos, _ = lp._matchup("khazix", muitos)
    assert e_poucos < 0.5            # 40 jogos não dizem nada
    assert e_muitos > 1.5            # 3.469 dizem quase tudo
    assert e_muitos > e_poucos * 3


def test_o_encolhimento_dos_matchups_e_o_medido():
    """73% do que a lolalytics mostra como efeito de matchup é ruído amostral
    (variância 8,96pp² contra 6,50 de ruído, em 588 matchups). O encolhimento
    óptimo é n/(n+1015) — estava n/(n+200), que sobrestimava os matchups por um
    factor de dois. Um matchup mediano (610 jogos) tem de reter ~38%, não 75%."""
    assert lp.JOGOS_MATCHUP_PARA_METADE == 1015
    e, _ = lp._matchup("x", {"E": {"x": {"effect": 10.0, "games": 610, "champion_key": "X"}}})
    assert 3.5 < e < 4.0             # 38% de 10pp


def test_combinar_e_em_log_odds_e_nunca_sai_do_intervalo():
    """Somar percentagens é o que se faz à mão e é errado: +2pp não vale o mesmo
    a partir de 50% e de 57%, e somando o suficiente sai-se de [0, 100]. Bradley-
    Terry (que é o Elo e a regressão logística) soma em log-odds."""
    assert lp._combina(50.0, 0.0) == 50.0
    assert lp._combina(50.0, 2.0) == 52.0        # em 50% coincide com somar
    assert lp._combina(57.5, 2.0) < 59.5         # mais acima, o mesmo bónus vale menos
    for base in (30.0, 50.0, 70.0):
        for ajuste in (-50.0, -10.0, 10.0, 50.0):
            assert 0.0 < lp._combina(base, ajuste) < 100.0


def test_exposicao_a_counters_desconta_o_ruido():
    """Um campeão com matchups de amostra pequena parecia volátil só por isso.
    Em Master+ o ruído sozinho vale 2,55pp de desvio."""
    # tudo igual: zero exposição, por muito que a amostra seja pequena
    plano = {f"E{i}": {"x": {"effect": 0.0, "games": 300, "champion_key": "X"}} for i in range(20)}
    exp, _ = lp._exposicao_a_counters("x", plano)
    assert exp == 0.0
    # alternado a ±5pp com muita amostra: sobra exposição a sério
    forte = {f"E{i}": {"x": {"effect": 5.0 if i % 2 else -5.0, "games": 4000, "champion_key": "X"}}
             for i in range(20)}
    exp2, piores = lp._exposicao_a_counters("x", forte)
    assert exp2 > 4.0
    assert piores[0]["effect"] == -5.0           # os piores primeiro


def test_matchup_pesa_os_inimigos_pelo_tamanho_da_amostra():
    """A média ponderada pelos jogos é a forma que Kim et al. mediram ser melhor
    do que somar deltas."""
    efeitos = {
        "Viego": {"x": {"effect": -4.0, "games": 4000, "champion_key": "X"}},
        "Ivern": {"x": {"effect": +4.0, "games": 40, "champion_key": "X"}},
    }
    efeito, detalhes = lp._matchup("x", efeitos)
    assert efeito < 0                # o matchup com 4000 jogos manda
    assert len(detalhes) == 2


def test_composicao_pesa_pouco():
    """O draft explica pouco do resultado — nenhum modelo publicado passa dos
    60% de acerto. Os bónus de composição têm de ser pequenos."""
    pontos, _ = lp._composicao(["Tank"], "AP", {"ap": True, "engage": True, "tank": True})
    assert pontos <= 3.0


# ── O lado do mapa ──────────────────────────────────────────────

class _Jogo:
    def __init__(self, lado, won):
        self.team_side, self.won = lado, won


def test_lado_do_mapa_precisa_de_jogos_dos_dois_lados():
    """Com quarenta jogos de um lado e três do outro não se diz nada."""
    jogos = [_Jogo("red", True)] * 100 + [_Jogo("blue", False)] * 3
    assert ld.lado_do_mapa([], jogos) is None


def test_lado_do_mapa_encontra_a_diferenca_e_testa_a():
    """Os números dele: red 57,6% em 236, blue 45,2% em 263 → +12,4pp, z=2,76."""
    jogos = ([_Jogo("red", True)] * 136 + [_Jogo("red", False)] * 100
             + [_Jogo("blue", True)] * 119 + [_Jogo("blue", False)] * 144)
    r = ld.lado_do_mapa([], jogos)
    assert r["better_side"] == "red"
    assert 12.0 < r["diff"] < 13.0
    assert r["proven"] is True
    assert 2.5 < r["z"] < 3.0


def test_lado_do_mapa_nao_inventa_uma_diferenca_que_nao_ha():
    jogos = ([_Jogo("red", i % 2 == 0) for i in range(200)]
             + [_Jogo("blue", i % 2 == 0) for i in range(200)])
    r = ld.lado_do_mapa([], jogos)
    assert r["proven"] is False
    assert abs(r["diff"]) < 1.0


def test_o_lado_a_favor_vem_do_teste_e_nao_da_mediana():
    """Nos abates em laners cedo a mediana da diferença é zero (23% dos jogos
    empatam) e ele ganha 64% dos que se decidem. A olhar para a mediana, a
    métrica aparecia a vermelho — contra ele — apesar de o teste dizer o
    contrário."""
    duelos = ([_Duelo(early_ganks=1, opp_early_ganks=0)] * 45 +
              [_Duelo(early_ganks=0, opp_early_ganks=1)] * 25 +
              [_Duelo(early_ganks=1, opp_early_ganks=1)] * 21)
    linha = next(m for m in ld.compara(duelos) if m["metric"] == "early_ganks")
    assert linha["diff"] == 0.0          # a mediana não diz nada
    assert linha["win_pct"] == 64
    assert linha["proven"] is True
    assert linha["in_my_favour"] is True


# ── Synergy ─────────────────────────────────────────────────────

def test_synergy_soma_se_em_vez_de_fazer_media():
    """Dois aliados bons são duas vantagens, não a média de duas — ao contrário
    do matchup, em que o inimigo é um só e vários inimigos são a mesma pergunta
    feita várias vezes."""
    mapa = {"jarvaniv": {
        "syndra": {"effect": 2.33, "games": 2452, "partner_role": "mid"},
        "lulu": {"effect": 2.36, "games": 2300, "partner_role": "supp"},
    }}
    um, _ = lp._synergy("jarvaniv", ["Syndra"], mapa)
    dois, detalhe = lp._synergy("jarvaniv", ["Syndra", "Lulu"], mapa)
    assert dois > um * 1.8
    assert len(detalhe) == 2


def test_synergy_encolhe_pela_amostra_medida():
    """Metade do que a u.gg mostra como synergy é ruído (variância 1,72pp²
    contra 0,87 de ruído). Um par mediano (2.794 jogos) retém ~49%."""
    assert lp.JOGOS_SYNERGY_PARA_METADE == 2951
    mapa = {"x": {"y": {"effect": 2.0, "games": 2794, "partner_role": "mid"}}}
    efeito, _ = lp._synergy("x", ["Y"], mapa)
    assert 0.9 < efeito < 1.1


def test_aliado_sem_dados_vale_zero_e_nao_um_palpite():
    """A u.gg cobre os pares mais jogados: o Lee Sin aparece em 52, a Diana em 1.
    O que não está medido não entra."""
    efeito, detalhe = lp._synergy("diana", ["Ashe"], {"diana": {}})
    assert efeito == 0.0
    assert detalhe == []


# ── Bans ────────────────────────────────────────────────────────

def test_banir_um_campeao_do_proprio_pool_custa_o_campeao():
    """Um ban tira o campeão aos **dois** lados: banir o Lee Sin é ficar sem Lee
    Sin. Sem isso, a lista recomendava banir os campeões do próprio pool."""
    import asyncio

    meta = {
        "leesin": {"wr": 52.0, "games": 50000, "pr": 8.9},
        "jarvaniv": {"wr": 50.0, "games": 50000, "pr": 7.4},
    }
    pool = {"LeeSin": {"games": 98, "winrate": 45.0},
            "JarvanIV": {"games": 119, "winrate": 48.0}}

    async def corre():
        return await lp.quem_banir({"LeeSin": 20, "JarvanIV": 20}, meta, pool)

    linhas = {c["champion"]: c for c in asyncio.run(corre())}
    if not linhas:
        return                                    # sem rede: o teste não se aplica
    assert linhas["LeeSin"]["in_my_pool"] is True
    # O Lee Sin é o melhor do pool; bani-lo deixa-o com o Jarvan, que é pior.
    assert linhas["LeeSin"]["gain"] < 0.5
