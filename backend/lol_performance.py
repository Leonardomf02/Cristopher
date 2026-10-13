"""Desempenho nos jogos de LoL, medido em vez de adivinhado.

Durante 488 jogos a app só sabia quem ganhou. Com winrate nada se prova: o
efeito do tilt (54,5% com zero derrotas contra 41,7% depois de duas) dá z=1,65,
e Wukong contra Lee Sin dá z=1,62 — os dois abaixo do limiar. A 40 jogos por
mês, provar qualquer um levaria mais de um ano.

CS por minuto, ouro, dano e participação em abates são contínuos: cada jogo é
uma medição em vez de uma moeda ao ar, e trinta jogos chegam para a diferença
aparecer. É a mesma régua do `garmin_insights` — Mann-Whitney com aproximação
normal, sem dependências novas — e a mesma regra: ou passa o teste ou não se diz.
"""
from __future__ import annotations

import math
from typing import Callable, Optional

MINIMO_POR_LADO = 8          # abaixo disto nem se tenta
P_MAXIMO = 0.05


# ── Métricas de um jogo ─────────────────────────────────────────────────

def _por_minuto(valor, duracao) -> Optional[float]:
    if valor is None or not duracao or duracao < 300:
        return None
    return valor / (duracao / 60)


METRICAS: dict[str, tuple[str, Callable, str]] = {
    # chave: (etiqueta, como se calcula, o que é melhor)
    "cs_min":      ("CS por minuto",     lambda g: _por_minuto(g.cs, g.game_duration), "cima"),
    "gold_min":    ("Ouro por minuto",   lambda g: _por_minuto(g.gold, g.game_duration), "cima"),
    "damage_min":  ("Dano por minuto",   lambda g: _por_minuto(g.damage, g.game_duration), "cima"),
    "vision_min":  ("Visão por minuto",  lambda g: _por_minuto(g.vision, g.game_duration), "cima"),
    "kp":          ("Participação em abates", lambda g: (
        None if not g.team_kills else ((g.kills or 0) + (g.assists or 0)) / g.team_kills), "cima"),
    "deaths":      ("Mortes",            lambda g: None if g.deaths is None else float(g.deaths), "baixo"),
}


def valores(jogos, chave: str) -> list[float]:
    _, calcula, _ = METRICAS[chave]
    return [v for v in (calcula(g) for g in jogos) if v is not None]


# ── Teste ───────────────────────────────────────────────────────────────

def mann_whitney(a: list[float], b: list[float]) -> Optional[tuple[float, float]]:
    """(z, p) para "estas duas amostras vêm da mesma distribuição?".

    Mann-Whitney e não t-test porque o CS por minuto tem cauda: uma partida de
    12 minutos que acabou em remake-quase puxava a média toda. Ordena em vez de
    somar, por isso um valor extremo vale o que vale — um lugar na fila."""
    n1, n2 = len(a), len(b)
    if n1 < MINIMO_POR_LADO or n2 < MINIMO_POR_LADO:
        return None

    juntos = sorted([(v, 0) for v in a] + [(v, 1) for v in b], key=lambda x: x[0])
    n = n1 + n2
    ranks = [0.0] * n
    empates = 0.0
    i = 0
    while i < n:
        j = i
        while j + 1 < n and juntos[j + 1][0] == juntos[i][0]:
            j += 1
        media = (i + j) / 2 + 1
        t = j - i + 1
        if t > 1:
            empates += t ** 3 - t
        for k in range(i, j + 1):
            ranks[k] = media
        i = j + 1

    soma_a = sum(r for r, (_, grupo) in zip(ranks, juntos) if grupo == 0)
    u = soma_a - n1 * (n1 + 1) / 2
    media_u = n1 * n2 / 2
    # Variância corrigida para empates: sem isto, métricas com muitos valores
    # repetidos (mortes: 0,1,2,3…) davam p-values optimistas de mais.
    var = (n1 * n2 / 12) * ((n + 1) - empates / (n * (n - 1))) if n > 1 else 0
    if var <= 0:
        return None
    z = (u - media_u) / math.sqrt(var)
    p = math.erfc(abs(z) / math.sqrt(2))
    return z, p


def _mediana(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def compara(jogos_a, jogos_b, nome_a: str, nome_b: str) -> list[dict]:
    """Compara dois grupos de jogos em todas as métricas. Só devolve as que
    passam o teste — as outras não são notícia, são ruído."""
    out = []
    for chave, (etiqueta, _, melhor) in METRICAS.items():
        va, vb = valores(jogos_a, chave), valores(jogos_b, chave)
        r = mann_whitney(va, vb)
        if not r:
            continue
        z, p = r
        ma, mb = _mediana(va), _mediana(vb)
        if p > P_MAXIMO:
            continue
        diff = ma - mb
        melhorou = (diff > 0) if melhor == "cima" else (diff < 0)
        out.append({
            "metric": chave,
            "label": etiqueta,
            "group_a": nome_a, "group_b": nome_b,
            "median_a": round(ma, 2), "median_b": round(mb, 2),
            "n_a": len(va), "n_b": len(vb),
            "diff": round(diff, 2),
            "diff_pct": round(100 * diff / mb, 1) if mb else None,
            "z": round(z, 2), "p": round(p, 4),
            "better_in_a": melhorou,
        })
    return sorted(out, key=lambda x: x["p"])


def resumo(jogos) -> dict:
    """Os números dele, para servirem de referência."""
    out = {}
    for chave, (etiqueta, _, _) in METRICAS.items():
        vals = valores(jogos, chave)
        if not vals:
            continue
        s = sorted(vals)
        out[chave] = {
            "label": etiqueta,
            "median": round(_mediana(vals), 2),
            "p25": round(s[len(s) // 4], 2),
            "p75": round(s[3 * len(s) // 4], 2),
            "n": len(vals),
        }
    return out
