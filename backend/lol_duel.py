"""O duelo com o jungler adversário — a única régua que a app pode ter.

Durante 500 jogos a app comparou-o só com ele próprio. "6,24 CS por minuto" não
diz nada: é bom, é mau, é normal para Master? A Riot não publica referências por
elo — nenhuma — e as dos sites são de outra amostra, outro patch e outro elo.

Mas em cada partida dele há um jungler do mesmo elo, no mesmo patch, no mesmo
jogo, a jogar contra ele. São 500 comparações emparelhadas de graça, e a app
deitava-as fora. O emparelhamento é o que dá o poder: não são dois grupos de
jogadores, é o mesmo jogo medido duas vezes, por isso Wilcoxon signed-rank e não
Mann-Whitney (que é o que o `lol_performance` usa, e ali está certo — lá os
grupos são independentes).

A divisão que interessa, e que nenhum tracker faz: **o que acontece antes do jogo
se decidir** contra **o que se acumula ao longo dele**. Nos jogos dele, aos 10
minutos as vitórias e as derrotas são indistinguíveis no ouro (−157 contra −150);
aos 15 já vão +607 contra −812. Fazer mais dragões não é conselho — é a descrição
de ter ganho. Perder 8 de CS de selva aos 10 minutos é conselho.
"""
from __future__ import annotations

import math
from typing import Optional

MINIMO = 12                  # abaixo disto não se testa nada
P_MAXIMO = 0.05

# (chave, etiqueta, coluna dele, o que é melhor, quando acontece)
# "cedo" = está decidido antes de o jogo se decidir, logo é conselho.
# "jogo" = acumula-se até ao fim, logo sobe porque se ganha tanto como faz ganhar.
METRICAS: tuple[tuple[str, str, str, str, str], ...] = (
    ("jungle_cs10",   "CS de selva aos 10min",     "jungle_cs10",   "cima",  "cedo"),
    ("takedowns10",   "Abates+assists aos 10min",  "takedowns10",   "cima",  "cedo"),
    ("early_ganks",   "Abates em laners cedo",     "early_ganks",   "cima",  "cedo"),
    ("gd10",          "Ouro aos 10min",            "gd10",          "cima",  "cedo"),
    ("xd10",          "XP aos 10min",              "xd10",          "cima",  "cedo"),
    ("gd15",          "Ouro aos 15min",            "gd15",          "cima",  "cedo"),
    ("xd15",          "XP aos 15min",              "xd15",          "cima",  "cedo"),
    ("cs_min",        "CS por minuto",             "cs_min",        "cima",  "jogo"),
    ("gold_min",      "Ouro por minuto",           "gold_min",      "cima",  "jogo"),
    ("damage_min",    "Dano por minuto",           "damage_min",    "cima",  "jogo"),
    ("damage_share",  "% do dano da equipa",       "damage_share",  "cima",  "jogo"),
    ("kill_participation", "Participação em abates", "kill_participation", "cima", "jogo"),
    ("vision_min",    "Visão por minuto",          "vision_min",    "cima",  "jogo"),
    ("control_wards", "Wards de controlo",         "control_wards", "cima",  "jogo"),
    ("enemy_jungle_cs", "Selva do adversário comida", "enemy_jungle_cs", "cima", "jogo"),
    ("deaths",        "Mortes",                    "deaths",        "baixo", "jogo"),
    ("time_dead_pct", "% do jogo morto",           "time_dead_pct", "baixo", "jogo"),
    ("dragons",       "Dragões",                   "dragons",       "cima",  "jogo"),
    ("turret_plates", "Placas de torre",           "turret_plates", "cima",  "jogo"),
)

# As diferenças da timeline já vêm calculadas (dele menos o adversário) e não
# têm coluna `opp_`; as outras têm.
_JA_SAO_DIFERENCA = {"gd10", "gd15", "gd20", "xd10", "xd15"}


# ── Teste ───────────────────────────────────────────────────────────────

def wilcoxon(diferencas: list[float]) -> Optional[tuple[float, float]]:
    """(z, p) para "estas diferenças estão centradas em zero?".

    Emparelhado: cada valor é o mesmo jogo medido dos dois lados, por isso tudo o
    que varia de jogo para jogo (o patch, o elo, a duração, o dia mau) cancela-se.
    É a mesma razão pela qual o teste precisa de menos jogos para dizer algo.

    As diferenças exactamente zero saem, como manda o teste. Os empates em |d|
    entram na correcção da variância — sem isso, métricas com muitos valores
    repetidos (wards de controlo: 0, 1, 2…) davam p-values optimistas de mais.
    """
    d = [x for x in diferencas if x != 0]
    n = len(d)
    if n < MINIMO:
        return None

    ordem = sorted(range(n), key=lambda i: abs(d[i]))
    ranks = [0.0] * n
    empates = 0.0
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(d[ordem[j + 1]]) == abs(d[ordem[i]]):
            j += 1
        media = (i + j) / 2 + 1
        t = j - i + 1
        if t > 1:
            empates += t ** 3 - t
        for k in range(i, j + 1):
            ranks[ordem[k]] = media
        i = j + 1

    w_mais = sum(r for r, x in zip(ranks, d) if x > 0)
    media_w = n * (n + 1) / 4
    var = (n * (n + 1) * (2 * n + 1) - empates / 2) / 24
    if var <= 0:
        return None
    z = (w_mais - media_w) / math.sqrt(var)
    return z, math.erfc(abs(z) / math.sqrt(2))


def _mediana(v: list[float]) -> float:
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _pares(duelos, chave: str, coluna: str) -> tuple[list[float], list[float]]:
    """(dele, do adversário) só dos jogos em que os dois lados têm o valor."""
    meus: list[float] = []
    deles: list[float] = []
    for d in duelos:
        if chave in _JA_SAO_DIFERENCA:
            v = getattr(d, coluna, None)
            if v is None:
                continue
            # Uma diferença é o par (v, 0): o zero é o adversário por definição.
            meus.append(float(v))
            deles.append(0.0)
            continue
        a = getattr(d, coluna, None)
        b = getattr(d, f"opp_{coluna}", None)
        if a is None or b is None:
            continue
        meus.append(float(a))
        deles.append(float(b))
    return meus, deles


# ── O duelo ─────────────────────────────────────────────────────────────

def compara(duelos) -> list[dict]:
    """Cada métrica dele contra a do jungler adversário do mesmo jogo.

    Devolve tudo, com `proven` a dizer o que passou o teste — ao contrário do
    `lol_performance.compara`, que só devolve o que passa. Aqui o que não passa
    também é informação: "no dano por minuto empatas com o adversário" é uma
    resposta, e é o que impede a página de parecer que só há defeitos."""
    saida = []
    for chave, etiqueta, coluna, melhor, momento in METRICAS:
        meus, deles = _pares(duelos, chave, coluna)
        difs = [a - b for a, b in zip(meus, deles)]
        r = wilcoxon(difs)
        if not r:
            continue
        z, p = r
        med_dif = _mediana(difs)
        ganha = sum(1 for x in difs if x > 0)
        empata = sum(1 for x in difs if x == 0)
        # A percentagem é sobre os jogos em que houve diferença, que são os
        # mesmos que o teste usa. Contá-la sobre o total dava a leitura errada:
        # nos abates em laners cedo ele ganha 46% de *todos* os jogos, mas
        # empata em 30% deles — dos que se decidem, ganha dois terços, e é isso
        # que o p-value está a dizer.
        decididos = len(difs) - empata
        # De que lado está ele, pelo mesmo sinal que o teste usa — e não pela
        # mediana. Nos abates em laners cedo a mediana da diferença é zero (há
        # 23% de jogos empatados) e ele ganha 64% dos que se decidem: a olhar
        # para a mediana, a métrica aparecia como estando contra ele.
        a_favor = (z > 0) if melhor == "cima" else (z < 0)
        saida.append({
            "metric": chave,
            "label": etiqueta,
            "moment": momento,
            "mine": round(_mediana(meus), 2),
            "theirs": round(_mediana(deles), 2) if chave not in _JA_SAO_DIFERENCA else None,
            "diff": round(med_dif, 2),
            "games": len(difs),
            "win_pct": round(100 * ganha / decididos, 0) if decididos else None,
            "tie_pct": round(100 * empata / len(difs), 0),
            "z": round(z, 2),
            # `round(p, 4)` de 1e-15 dá 0,0, e um p-value de zero não existe.
            "p": round(p, 4) if p >= 0.0001 else float(f"{p:.2g}"),
            "proven": p <= P_MAXIMO,
            "in_my_favour": a_favor,
            "higher_is_better": melhor == "cima",
        })
    # O que está provado primeiro, e dentro disso o mais forte.
    saida.sort(key=lambda m: (not m["proven"], m["p"]))
    return saida


def por_campeao(duelos, minimo: int = 8) -> list[dict]:
    """O mesmo duelo, campeão a campeão. Sem teste — com 8 a 40 jogos por campeão
    nada passa, e a mediana da diferença já diz o que interessa."""
    grupos: dict[str, list] = {}
    for d in duelos:
        if d.champion:
            grupos.setdefault(d.champion, []).append(d)

    linhas = []
    for campeao, gs in grupos.items():
        if len(gs) < minimo:
            continue
        linha = {
            "champion": campeao,
            "games": len(gs),
            "winrate": round(100 * sum(1 for g in gs if g.won) / len(gs), 1),
        }
        for chave, _, coluna, _, _ in METRICAS:
            meus, deles = _pares(gs, chave, coluna)
            difs = [a - b for a, b in zip(meus, deles)]
            linha[chave] = round(_mediana(difs), 2) if difs else None
        linhas.append(linha)
    linhas.sort(key=lambda c: -c["games"])
    return linhas


def lado_do_mapa(duelos, jogos) -> Optional[dict]:
    """De que lado do mapa ele joga melhor, e porquê.

    É de longe o maior efeito que a app consegue medir nele — 12,4pp entre red e
    blue (57,6% contra 45,2%, z=2,76), quatro a seis vezes maior do que qualquer
    matchup. E ao contrário de tudo o resto, **o lado é sorteado**: não há
    selecção nenhuma, é uma experiência aleatorizada de graça.

    Duas honestidades obrigatórias, porque o efeito foi descoberto nestes mesmos
    dados: partindo a amostra ao meio no tempo, os primeiros 249 jogos dão
    +16,5pp e os últimos 250 dão +8,4pp — a direcção aguenta-se, a magnitude
    encolhe, e a previsão fora da amostra (54,0%) já não passa o limiar. O efeito
    verdadeiro é provavelmente ~8pp, não 12.

    O que **se aguenta nas duas metades** é o mecanismo: de red ele passa ~4,5pp
    mais do início do jogo na metade inimiga do mapa (z=2,87 e z=2,75). Não é
    farm — o CS de selva aos 10 é igual dos dois lados. É decisão: de blue joga
    em casa e perde o dragão (−0,36 contra o adversário, contra +0,50 de red),
    apesar de o lado azul ter a vantagem estrutural no dragão. Está a desperdiçar
    a vantagem do lado que a tem.
    """
    lados = {"blue": [], "red": []}
    for g in jogos:
        if g.team_side in lados:
            lados[g.team_side].append(g)
    if min(len(v) for v in lados.values()) < 40:
        return None

    def wr(gs):
        return 100 * sum(1 for g in gs if g.won) / len(gs)

    vb, vr = sum(1 for g in lados["blue"] if g.won), sum(1 for g in lados["red"] if g.won)
    nb, nr = len(lados["blue"]), len(lados["red"])
    p_medio = (vb + vr) / (nb + nr)
    se = (p_medio * (1 - p_medio) * (1 / nb + 1 / nr)) ** 0.5
    z = (vr / nr - vb / nb) / se if se else 0.0

    # `lol_duels` não guarda o lado — quem o sabe é `lol_games`, e é de lá que
    # ele vem anexado (`_lado`) por quem chama.
    por_lado = {"blue": [], "red": []}
    for d in duelos:
        lado = getattr(d, "_lado", None)
        if lado in por_lado:
            por_lado[lado].append(d)

    causas = []
    if min(len(v) for v in por_lado.values()) >= 30:
        for chave, etiqueta, coluna, melhor, _ in METRICAS:
            va = [x - y for x, y in zip(*_pares(por_lado["blue"], chave, coluna))]
            vb2 = [x - y for x, y in zip(*_pares(por_lado["red"], chave, coluna))]
            if len(va) < 25 or len(vb2) < 25:
                continue
            ma, mb = sum(va) / len(va), sum(vb2) / len(vb2)
            var_a = sum((x - ma) ** 2 for x in va) / (len(va) - 1)
            var_b = sum((x - mb) ** 2 for x in vb2) / (len(vb2) - 1)
            erro = (var_a / len(va) + var_b / len(vb2)) ** 0.5
            if not erro:
                continue
            zz = (mb - ma) / erro
            if abs(zz) < 1.96:
                continue
            causas.append({
                "metric": chave, "label": etiqueta,
                "blue": round(ma, 2), "red": round(mb, 2),
                "diff": round(mb - ma, 2), "z": round(zz, 2),
                "better_on_red": (mb > ma) if melhor == "cima" else (mb < ma),
            })
        causas.sort(key=lambda c: -abs(c["z"]))

    return {
        "blue": {"games": nb, "winrate": round(wr(lados["blue"]), 1)},
        "red": {"games": nr, "winrate": round(wr(lados["red"]), 1)},
        "diff": round(wr(lados["red"]) - wr(lados["blue"]), 1),
        "z": round(z, 2),
        "proven": abs(z) >= 1.96,
        "better_side": "red" if wr(lados["red"]) > wr(lados["blue"]) else "blue",
        "causes": causas[:5],
    }


def janela_critica(duelos) -> Optional[dict]:
    """Em que minuto é que as vitórias começam a separar-se das derrotas.

    A resposta dele: aos 10 minutos não há diferença nenhuma (−157 nas vitórias
    contra −150 nas derrotas), aos 15 são +607 contra −812. Saber isto vale mais
    do que qualquer média: diz onde é que vale a pena olhar num replay."""
    momentos = []
    for chave, minuto in (("gd10", 10), ("gd15", 15), ("gd20", 20)):
        v = [getattr(d, chave) for d in duelos if d.won and getattr(d, chave) is not None]
        l = [getattr(d, chave) for d in duelos if not d.won and getattr(d, chave) is not None]
        if len(v) < MINIMO or len(l) < MINIMO:
            continue
        momentos.append({
            "minute": minuto,
            "wins": round(_mediana(v)),
            "losses": round(_mediana(l)),
            "gap": round(_mediana(v) - _mediana(l)),
            "n_wins": len(v),
            "n_losses": len(l),
        })
    if len(momentos) < 2:
        return None
    # O primeiro momento em que a distância passa de metade da maior distância.
    maior = max(m["gap"] for m in momentos)
    parte = next((m["minute"] for m in momentos if m["gap"] >= maior / 2), None)
    return {"points": momentos, "splits_at": parte}
