"""Que campeão escolher — e porquê, em pontos percentuais.

A recomendação antiga só sabia olhar para os campeões que ele já tinha jogado:
percorria a tabela dos jogos dele, por isso um campeão que nunca jogou de jungle
não podia ser sugerido. Daí a sensação de "são sempre os mesmos". Ele tem Talon
com 177 mil pontos de maestria e tier 2 no patch, e a app nunca lho ia dizer.

E os pesos estavam ao contrário: um matchup pessoal com 1-4 jogos mexia até ±30
no resultado, o meta global com milhares de jogos mexia ±8. Nos 500 jogos dele há
234 pares de matchup e **um** com dez jogos ou mais.

Aqui o resultado é um winrate esperado em pontos percentuais, somado de parcelas
que se podem ler uma a uma:

    E[WR] = meta + matchup + à-vontade + composição

Nenhuma delas é inventada:

* **meta** — o winrate do campeão no elo dele, das três fontes que funcionam.
* **matchup** — o `d2` da lolalytics, o único dos três números deles que é
  antissimétrico (ver `meta_stats.efeitos_de_matchup`), combinado por média
  ponderada pelo número de jogos de cada matchup, que é a forma que o
  recomendador de Kim et al. (UW) mediu ser a melhor — e não uma soma de deltas.
* **à-vontade** — **zero dentro do pool**, e isso mediu-se: as diferenças de
  winrate entre os campeões dele têm menos variância (5,9pp) do que o ruído que
  se esperaria por acaso (10,6pp). Fora do pool é o custo de aprender, e esse
  vem de uma medição a sério (iTero, 1M+ jogos): 41,5% de winrate abaixo de 5 mil
  pontos de maestria contra 54,5% acima de 500 mil, **mas com a curva a saturar
  cedo** — de 75 mil para 175 mil o ganho é menos de 1pp. Por isso os campeões
  que ele já sabe jogar não levam castigo nenhum.
* **composição** — o rácio de dano da equipa entre 20% e 80%, que é o intervalo
  onde o mesmo estudo mede o winrate mais alto.

**As diferenças são pequenas de propósito.** Nenhum modelo publicado passa dos
60% de acerto a prever o resultado só pelo draft. Um pick 1,5pp melhor do que
outro é o que a evidência aguenta, e é isso que a app diz — em vez de um "score
87" que finge uma precisão que não existe.
"""
from __future__ import annotations

import asyncio
import logging
import math
from typing import Optional

from meta_stats import (_to_ddragon_key, canon_slug, efeitos_de_matchup,
                        normalize_name, synergias)

logger = logging.getLogger(__name__)

# Dentro do pool dele, o winrate por campeão não separa nada — e isso mediu-se.
# A variância dos "edges" (winrate dele menos o do elo) nos nove campeões com
# amostra é de 5,9pp de desvio; o ruído que se esperaria só por acaso, dado o
# número de jogos de cada um, é de 10,6pp. O ruído é maior do que o sinal: a
# diferença entre os 61,9% de Diana e os 44,9% de Lee Sin é indistinguível de
# uma moeda ao ar. O encolhimento óptimo (τ² / (τ² + ruído)) dá praticamente
# zero, por isso é zero — e não um número escolhido a olho.
#
# O que ficaria mal ao ignorar isto: o Wukong levava +5,2pp e aparecia em
# primeiro lugar contra onze dos doze junglers que ele mais encontra, com os
# matchups (±2pp, medidos em milhares de jogos) a nunca conseguirem compensar
# uma vantagem que não existe.
#
# As medidas contínuas do duelo (`lol_duels`) separam mesmo os campeões — mas
# separam **o campeão**, não ele: o Kha'Zix faz mais dano por minuto do que o
# Wukong porque é um assassino, e sem uma referência por campeão e por elo (que
# a Riot não publica) não há como isolar as duas coisas.
#
# O edge continua a aparecer na aba Duelo, onde é informação sobre ele — só não
# manda em decisões.
EDGE_DENTRO_DO_POOL = 0.0

# Encolhimento do winrate do meta. Os campeões que quase ninguém joga na role
# têm caudas muito maiores: o Gragas jungle tem 57,5% em 3.083 jogos e o Lee Sin
# 49,1% em 54.770. E não é só amostra — quem escolhe um campeão de nicho costuma
# ser quem o domina, por isso aquele winrate é o dos especialistas, não o que ele
# teria. Nos campeões populares a correcção é de décimas.
JOGOS_META_PARA_METADE = 500


def _wr_do_meta(m: dict) -> float:
    n = m.get("games") or 0
    return 50.0 + (m["wr"] - 50.0) * n / (n + JOGOS_META_PARA_METADE) if n else m["wr"]


def _combina(base_pct: float, ajuste_pp: float) -> float:
    """Junta a força do campeão com os ajustes, em log-odds e não em percentagem.

    Somar percentagens é o que se faz à mão e é errado: um bónus de +2pp não vale
    o mesmo a partir de 50% e a partir de 57%, e somando o suficiente sai-se do
    intervalo [0, 100] — foi por isso que aqui esteve um corte artificial em
    [40, 60]. A forma certa é a do modelo de Bradley-Terry (que é a mesma coisa
    que o Elo e que uma regressão logística): as forças somam-se em log-odds.

    Perto de 50% a diferença é de décimas, o que é a confirmação de que o corte
    não estava a esconder um erro grande — estava a esconder um erro de forma."""
    p = max(0.02, min(0.98, base_pct / 100.0))
    z = math.log(p / (1 - p)) + ajuste_pp * 0.04   # 0,04 = d(logit)/dp em p=0,5
    return round(100.0 / (1.0 + math.exp(-max(-6.0, min(6.0, z)))), 1)

# Quanto custa pegar num campeão que não se domina, em pontos percentuais. A
# curva do iTero satura acima de ~75 mil pontos, por isso acima disso é zero.
def custo_de_aprender(maestria: int, jogos_na_role: int) -> tuple[float, str]:
    if jogos_na_role >= 10 or maestria >= 100_000:
        return 0.0, "à-vontade"
    if maestria >= 25_000 or jogos_na_role >= 4:
        return -2.0, "alguma prática"
    if maestria >= 5_000:
        return -4.0, "pouca prática"
    return -6.0, "de raiz"


def _a_vontade(wr_dele: float, wr_meta: float, jogos: int) -> float:
    """Zero, e é medido — ver `EDGE_DENTRO_DO_POOL`. Fica como função porque é
    aqui que entraria um dia, se houver referência por campeão e por elo."""
    return EDGE_DENTRO_DO_POOL


def _composicao(tags: list[str], dano: str, precisa: dict) -> tuple[float, list[str]]:
    """O que a equipa ainda não tem. Pesos pequenos: é o que a evidência aguenta.

    O rácio de dano só é castigado quando fica fora de 20-80% — dentro disso o
    winrate medido é praticamente plano, e empurrar para 50/50 é inventar."""
    pontos, razoes = 0.0, []
    if precisa.get("ap") and dano == "AP":
        pontos += 1.5
        razoes.append("a equipa está toda em dano físico")
    elif precisa.get("ad") and dano == "AD":
        pontos += 1.5
        razoes.append("a equipa está toda em dano mágico")
    if precisa.get("engage") and "Tank" in tags:
        pontos += 1.0
        razoes.append("a equipa não tem quem inicie")
    if precisa.get("tank") and "Tank" in tags:
        pontos += 0.5
    return pontos, razoes


async def _efeitos_dos_inimigos(inimigos: list[str], role: str) -> dict[str, dict]:
    """Um pedido por inimigo, em paralelo. Cada resposta traz os 66 candidatos
    contra ele, por isso são cinco pedidos e não sessenta e oito — é o que faz
    isto caber no tempo de um champ select."""
    if not inimigos:
        return {}
    resultados = await asyncio.gather(
        *[efeitos_de_matchup(e, role) for e in inimigos], return_exceptions=True
    )
    return {
        inimigo: r
        for inimigo, r in zip(inimigos, resultados)
        if isinstance(r, dict) and r
    }


# Encolhimento de cada matchup pela sua própria amostra — e o número vem de uma
# medição, não de um palpite. Em 588 matchups de dez junglers em Master+:
#
#   variância observada dos d2 : 8,96 pp²  (desvio 2,99pp)
#   ruído esperado pela amostra: 6,50 pp²  (desvio 2,55pp)
#   → efeito genuíno           : 2,46 pp²  (desvio 1,57pp)
#
# **73% do que a lolalytics mostra como efeito de matchup é ruído amostral.** O
# encolhimento óptimo (τ²/(τ²+ruído)) dá n/(n+1015); estava n/(n+200), o que
# sobrestimava os matchups por um factor de dois — um matchup mediano (610 jogos)
# retinha 75% do valor quando devia reter 38%.
#
# O modelo de ruído confirma-se de fora: os mesmos matchups em Master+ e em
# Diamond+ discordam 2,07pp, e 2500/n prevê essa ordem de grandeza. E o desacordo
# entre elos é todo ruído — os matchups não mudam materialmente de Diamond para
# Master, ao contrário do que se poderia supor.
JOGOS_MATCHUP_PARA_METADE = 1015


# Encolhimento da synergy, medido como tudo o resto: em 186 pares da u.gg a
# variância é 1,72pp² e o ruído da amostra 0,87 — **metade do que se vê é ruído**,
# e o efeito genuíno tem desvio de 0,92pp. Dá n/(n+2951); um par mediano (2.794
# jogos) retém 49%.
#
# Que é sinal a sério, prova-se de fora: os mesmos pares medidos em Diamond+ e em
# Esmeralda+ correlacionam **+0,865** com desacordo de 0,65pp. Os matchups, para
# comparação, ficam-se pelos 0,60-0,76.
JOGOS_SYNERGY_PARA_METADE = 2951


def _synergy(slug: str, aliados: list[str], mapa: dict[str, dict]) -> tuple[float, list[dict]]:
    """Quanto este campeão ganha por jogar com os aliados que já estão escolhidos.

    Ao contrário do matchup, a synergy **soma-se** em vez de se fazer média: dois
    aliados bons são duas vantagens, não a média de duas. Só entram os pares que
    a u.gg mede — a cobertura é dos mais jogados (o Lee Sin aparece em 52 pares,
    a Diana em 1), e o que não existe vale zero em vez de valer um palpite."""
    pares = mapa.get(slug) or {}
    total = 0.0
    detalhes = []
    for aliado in aliados:
        chave = canon_slug(aliado) or normalize_name(aliado)
        linha = pares.get(chave)
        if not linha:
            continue
        n = max(linha["games"], 1)
        efeito = linha["effect"] * n / (n + JOGOS_SYNERGY_PARA_METADE)
        total += efeito
        detalhes.append({
            "ally": aliado, "effect": round(efeito, 2),
            "raw_effect": linha["effect"], "games": linha["games"],
            "role": linha.get("partner_role"),
        })
    detalhes.sort(key=lambda d: -d["effect"])
    return total, detalhes


def _matchup(slug: str, efeitos: dict[str, dict]) -> tuple[float, list[dict]]:
    """Média dos efeitos contra os inimigos visíveis, ponderada pelos jogos de
    cada matchup — a forma que o paper de Kim et al. mediu ser melhor do que a
    média simples, porque um matchup com 200 jogos e outro com 4000 não valem o
    mesmo."""
    soma = peso = 0.0
    detalhes = []
    for inimigo, mapa in efeitos.items():
        linha = mapa.get(slug)
        if not linha:
            continue
        n = max(linha["games"], 1)
        efeito = linha["effect"] * n / (n + JOGOS_MATCHUP_PARA_METADE)
        soma += efeito * n
        peso += n
        detalhes.append({
            "enemy": inimigo,
            "effect": round(efeito, 2),
            "raw_effect": linha["effect"],
            "games": linha["games"],
        })
    if not peso:
        return 0.0, []
    detalhes.sort(key=lambda d: d["effect"])
    return soma / peso, detalhes


async def recomenda(
    inimigos: list[str],
    meta: dict[str, dict],
    pool: dict[str, dict],
    maestria: dict[str, int],
    precisa: dict,
    info_campeao,
    role: str = "jungle",
    pick_rate_minimo: float = 0.5,
    indisponiveis: list[str] | None = None,
    aliados: list[str] | None = None,
) -> dict:
    """As duas listas: o pool dele e o que o meta diz.

    `pool` é {campeão: {"games": n, "winrate": wr}}; `maestria` é {campeão: pontos}
    da Riot; `info_campeao(nome)` devolve (tags, tipo de dano) do Data Dragon.
    `pick_rate_minimo` corta os campeões que quase ninguém joga na role — sem
    isso a lista enche-se de Darius jungle com quarenta jogos no mundo inteiro.
    `indisponiveis` são campeões que já não dá para escolher (banidos, ou já
    escolhidos por alguém).
    """
    efeitos = await _efeitos_dos_inimigos(inimigos, role)
    sem_matchup = [e for e in inimigos if e not in efeitos]
    aliados = [a for a in (aliados or []) if a]
    try:
        mapa_synergy = await synergias(role) if aliados else {}
    except Exception as e:                       # a fonte é de fora; não pode travar as picks
        logger.warning(f"synergy indisponível ({e})")
        mapa_synergy = {}
    # O que ele já joga entra sempre, mesmo que quase ninguém o jogue na role:
    # ninguém quer abrir a página e não encontrar lá os seus próprios campeões.
    dele = {normalize_name(c) for c in pool}
    # Um campeão só entra numa partida uma vez: recomendar o Wukong contra o
    # Wukong é sugerir um pick que o cliente não deixa fazer — e apareceu logo
    # em primeiro lugar, porque um campeão contra si próprio tem matchup zero e
    # fica só com o à-vontade dele.
    fora = {canon_slug(c) or normalize_name(c)
            for c in list(inimigos) + list(indisponiveis or []) if c}

    linhas = []
    for chave, m in meta.items():
        if m.get("pr", 0) < pick_rate_minimo and chave not in dele:
            continue
        nome = _to_ddragon_key(chave)
        slug = canon_slug(nome) or chave
        if slug in fora or chave in fora:
            continue
        efeito, detalhes = _matchup(slug, efeitos)

        meu = pool.get(nome, {})
        jogos = meu.get("games", 0)
        pontos_maestria = maestria.get(nome, 0)
        wr_meta = _wr_do_meta(m)
        if jogos >= 5:
            conforto = _a_vontade(meu["winrate"], wr_meta, jogos)
            etiqueta = "à-vontade"
        else:
            conforto, etiqueta = custo_de_aprender(pontos_maestria, jogos)

        tags, dano = info_campeao(nome)
        comp, razoes_comp = _composicao(tags, dano, precisa)
        sinergia, com_quem = _synergy(slug, aliados, mapa_synergy)

        esperado = _combina(wr_meta, efeito + sinergia + conforto + comp)
        linhas.append({
            "champion": nome,
            "expected_wr": esperado,
            "meta_wr": m["wr"],
            "meta_wr_used": round(wr_meta, 1),
            "meta_games": m.get("games"),
            "meta_tier": m.get("tier"),
            "pick_rate": m.get("pr"),
            "matchup": round(efeito, 1),
            "synergy": round(sinergia, 1),
            "with": com_quem[:3],
            "comfort": round(conforto, 1),
            "comfort_label": etiqueta,
            "comp": round(comp, 1),
            "games": jogos,
            "my_wr": meu.get("winrate"),
            "mastery": pontos_maestria,
            "damage": dano,
            "vs": detalhes[:5],
            "comp_reasons": razoes_comp,
        })

    linhas.sort(key=lambda c: -c["expected_wr"])
    do_pool = [c for c in linhas if c["games"] >= 10]
    de_fora = [c for c in linhas if c["games"] < 10]

    return {
        "pool": do_pool,
        "meta": de_fora,
        "enemies": inimigos,
        "allies": aliados,
        "enemies_without_matchup": sem_matchup,
        "synergy_available": bool(mapa_synergy),
        # A app diz sempre o tamanho do efeito de que está a falar. Entre o
        # primeiro e o quinto do pool costumam ir 1 a 2 pontos percentuais —
        # menos do que a diferença entre dormir bem e dormir mal.
        "spread": round(
            (do_pool[0]["expected_wr"] - do_pool[min(4, len(do_pool) - 1)]["expected_wr"])
            if len(do_pool) >= 2 else 0.0, 1),
    }


# ── Que campeão vale a pena aprender ─────────────────────────────

def _exposicao_a_counters(slug: str, efeitos: dict[str, dict]) -> tuple[float | None, list[dict]]:
    """Quão exposto está um campeão a ser contra-escolhido.

    De blue escolhe-se primeiro, e nessa altura o jungler adversário ainda não
    existe — a pergunta deixa de ser "quem é bom contra ele" e passa a ser "quem
    tem menos maneiras de correr mal". É a mesma ideia do blind pick: o melhor
    não é o mais forte, é o que tem a banda mais larga de matchups pares.

    Devolve o desvio dos efeitos **já limpo do ruído amostral** — sem isso um
    campeão com matchups de amostra pequena parecia volátil só por isso. Em
    Master+ o ruído sozinho vale 2,55pp de desvio, por isso quem fica abaixo
    disso não tem hard counters detectáveis (Graves, Talon, Jarvan, Lee Sin), e
    quem fica muito acima tem (Kayn, Sylas)."""
    valores = []
    detalhe = []
    for inimigo, mapa in efeitos.items():
        linha = mapa.get(slug)
        if not linha or linha["games"] < 200:
            continue
        valores.append(linha["effect"])
        detalhe.append({"enemy": inimigo, "effect": linha["effect"], "games": linha["games"]})
    if len(valores) < 15:
        return None, []
    media = sum(valores) / len(valores)
    var = sum((v - media) ** 2 for v in valores) / len(valores)
    ruido = sum(2500 / max(d["games"], 1) for d in detalhe) / len(detalhe)
    genuino = max(var - ruido, 0.0) ** 0.5
    detalhe.sort(key=lambda d: d["effect"])
    return round(genuino, 2), detalhe[:3]


async def vale_a_pena_aprender(
    frequencia: dict[str, int],
    meta: dict[str, dict],
    pool: dict[str, dict],
    maestria: dict[str, int],
    role: str = "jungle",
    pick_rate_minimo: float = 1.0,
    cobertura_minima: float = 0.5,
) -> list[dict]:
    """Contra os junglers que ele encontra mesmo, quais é que rendiam mais.

    Não é a mesma pergunta que a do champ select. Ali o inimigo já se sabe; aqui
    a pergunta é sobre os próximos cem jogos, e a resposta tem de ser pesada pela
    frequência real com que cada inimigo aparece — vale mais um campeão que se dá
    bem com o Hecarim (20 encontros em seis meses) do que um que arrasa o Ivern
    (nenhum)."""
    total = sum(frequencia.values())
    if not total:
        return []

    efeitos = await _efeitos_dos_inimigos(list(frequencia), role)
    if not efeitos:
        return []

    linhas = []
    for chave, m in meta.items():
        if m.get("pr", 0) < pick_rate_minimo:
            continue
        nome = _to_ddragon_key(chave)
        slug = canon_slug(nome) or chave
        soma = peso = 0.0
        for inimigo, n in frequencia.items():
            linha = efeitos.get(inimigo, {}).get(slug)
            if linha:
                g = max(linha["games"], 1)
                soma += linha["effect"] * g / (g + JOGOS_MATCHUP_PARA_METADE) * n
                peso += n
        # Sem metade dos encontros cobertos o número seria de outra amostra.
        if peso < cobertura_minima * total:
            continue

        jogos = pool.get(nome, {}).get("games", 0)
        pontos = maestria.get(nome, 0)
        custo, etiqueta = custo_de_aprender(pontos, jogos)
        efeito = soma / peso
        wr_meta = _wr_do_meta(m)
        exposicao, pior = _exposicao_a_counters(slug, efeitos)
        linhas.append({
            "counter_exposure": exposicao,
            "worst_matchups": pior,
            "champion": nome,
            "meta_wr": m["wr"],
            "meta_wr_used": round(wr_meta, 1),
            "meta_games": m.get("games"),
            "matchup": round(efeito, 2),
            "vs_my_enemies": _combina(wr_meta, efeito),
            "learning_cost": custo,
            "worth_it": _combina(wr_meta, efeito + custo),
            "familiarity": etiqueta,
            "mastery": pontos,
            "games": jogos,
            "coverage": round(100 * peso / total),
            "already_playing": jogos >= 10,
        })
    linhas.sort(key=lambda c: -c["worth_it"])
    return linhas


# ── Quem banir ───────────────────────────────────────────────────

async def quem_banir(
    frequencia: dict[str, int],
    meta: dict[str, dict],
    pool: dict[str, dict],
    role: str = "jungle",
    quantos_avaliar: int = 14,
) -> list[dict]:
    """Que jungler adversário mais estraga as opções dele.

    A pergunta que parecia óbvia — "contra quem é que perco mais?" — não tem
    resposta nos dados dele: dos 19 junglers que enfrentou dez ou mais vezes,
    um passa o teste, e com dezanove testes espera-se exactamente um falso
    positivo por acaso. O que se pode medir é outra coisa, e é melhor: **quanto
    é que cada inimigo baixa o melhor pick que lhe resta**.

    Para cada candidato calcula-se o melhor E[WR] do pool dele com esse inimigo
    do outro lado, e compara-se com o melhor que teria sem ninguém. Um jungler
    que só é mau contra um campeão do pool custa pouco — ele troca. Um que é mau
    contra o pool todo custa a sério. Isso multiplica-se pela frequência com que
    aparece de facto, porque banir o que nunca se encontra é banir nada.

    A fase de bans acontece antes dos picks, por isso isto não depende do draft e
    calcula-se uma vez por dia.
    """
    do_pool = [c for c, d in pool.items() if d.get("games", 0) >= 10]
    if not do_pool or not frequencia:
        return []
    total = sum(frequencia.values())
    candidatos = sorted(frequencia, key=lambda c: -frequencia[c])[:quantos_avaliar]
    efeitos = await _efeitos_dos_inimigos(candidatos, role)
    if not efeitos:
        return []

    def melhor_do_pool(inimigo: Optional[str], sem: Optional[str] = None) -> tuple[float, str]:
        """O melhor winrate esperado que o pool dele dá contra `inimigo`, podendo
        faltar-lhe um campeão (`sem`) — um ban tira o campeão aos **dois** lados."""
        melhor, quem = -99.0, ""
        for campeao in do_pool:
            if sem and (canon_slug(campeao) or normalize_name(campeao)) == (canon_slug(sem) or normalize_name(sem)):
                continue
            m = meta.get(normalize_name(campeao))
            if not m:
                continue
            slug = canon_slug(campeao) or normalize_name(campeao)
            efeito = 0.0
            if inimigo:
                efeito, _ = _matchup(slug, {inimigo: efeitos.get(inimigo, {})})
            valor = _combina(_wr_do_meta(m), efeito)
            if valor > melhor:
                melhor, quem = valor, campeao
        return melhor, quem

    linhas = []
    for inimigo in candidatos:
        if inimigo not in efeitos:
            continue
        vezes = frequencia.get(inimigo, 0)
        prob = vezes / total
        # Sem banir: com probabilidade `prob` ele aparece do outro lado.
        contra, resposta = melhor_do_pool(inimigo)
        livre, _ = melhor_do_pool(None)
        sem_banir = prob * contra + (1 - prob) * livre
        # A banir: ele nunca aparece, mas o campeão sai do pool dele também.
        banido, _ = melhor_do_pool(None, sem=inimigo)
        ganho = banido - sem_banir
        linhas.append({
            "champion": inimigo,
            "gain": round(ganho, 3),
            "cost_if_faced": round(livre - contra, 2),
            "best_answer": resposta,
            "best_answer_wr": round(contra, 1),
            "in_my_pool": any(
                (canon_slug(c) or normalize_name(c)) == (canon_slug(inimigo) or normalize_name(inimigo))
                for c in do_pool
            ),
            "encounters": vezes,
            "encounter_pct": round(100 * prob, 1),
            "meta_wr": (meta.get(normalize_name(inimigo)) or {}).get("wr"),
            "ban_rate": (meta.get(normalize_name(inimigo)) or {}).get("br"),
        })
    linhas.sort(key=lambda c: -c["gain"])
    return linhas
