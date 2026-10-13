"""O que dizer durante o jogo, e só o que está medido.

A app descobriu coisas sobre ele — que põe zero control wards, que perde o dragão
do lado azul, que aos dez minutos troca XP por ouro — e nada disso lhe chegava a
não ser que abrisse a aba das estatísticas depois do jogo acabar. Um facto sobre
o passado só vale alguma coisa se aparecer no momento em que ainda dá para fazer
diferente.

Isto lê o estado do jogo no cliente local (o mesmo `allgamedata` do
`live_winprob`) e cruza-o com o que o duelo mediu. Duas regras:

* **só entra o que passou um teste** nos jogos dele. Nada de conselhos gerais de
  guia da internet — se a app não o mediu nele, não o diz;
* **cada aviso traz o número que o sustenta**. "Compra uma control ward" é uma
  ordem; "0 control wards aos 12 minutos, e perdes esse duelo em 78% dos jogos" é
  uma razão.

Os avisos aparecem uma vez cada um por partida: repetir de trinta em trinta
segundos transforma-os em ruído, e ruído não se lê.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

CONTROL_WARD_ID = 2055
# Os avisos ligam-se a partir daqui (segundos de jogo). Antes disto o jogo ainda
# não deu para nada acontecer.
_MIN_CONTROL_WARD = 8 * 60
_MIN_CS10 = 10 * 60


def _nome(p: dict) -> str:
    """O nome de um jogador, seja qual for o campo em que o cliente o mandou.

    São três hipóteses e não uma por escolha do `live_winprob`, que já corre
    contra o cliente a sério: conforme a versão, o `activePlayer` traz `riotId`,
    `summonerName` ou `riotIdGameName`. Ler só um deles é não encontrar o
    jogador — e não encontrar o jogador aqui é a app calar-se sem dizer porquê."""
    bruto = p.get("riotId") or p.get("summonerName") or p.get("riotIdGameName") or ""
    return bruto.split("#")[0].strip().lower()


def _eu(data: dict) -> Optional[dict]:
    meu = _nome(data.get("activePlayer") or {})
    if not meu:
        return None
    for p in data.get("allPlayers") or []:
        if _nome(p) == meu:
            return p
    return None


def _lado(data: dict) -> Optional[str]:
    """"blue" ou "red" — no cliente, ORDER é o lado azul e CHAOS o vermelho."""
    eu = _eu(data)
    equipa = (eu or {}).get("team") or ""
    return "blue" if equipa == "ORDER" else "red" if equipa == "CHAOS" else None


def _tem_control_ward(jogador: dict) -> bool:
    return any(int(i.get("itemID", 0)) == CONTROL_WARD_ID for i in jogador.get("items") or [])


def _dragoes(data: dict, lado: str) -> tuple[int, int]:
    """(meus, do inimigo). O cliente diz quem matou; o lado sai da lista."""
    equipas = {
        _nome(p): ("blue" if p.get("team") == "ORDER" else "red")
        for p in data.get("allPlayers") or []
    }
    meus = deles = 0
    for ev in (data.get("events") or {}).get("Events") or []:
        if ev.get("EventName") != "DragonKill":
            continue
        quem = (ev.get("KillerName") or "").split("#")[0].strip().lower()
        if equipas.get(quem) == lado:
            meus += 1
        elif quem in equipas:
            deles += 1
    return meus, deles


def avisos(data: Optional[dict], medidas: dict) -> dict:
    """Os avisos para o estado de jogo actual.

    `medidas` é o que o duelo mediu nele, já filtrado pelo que passou o teste —
    ver `routers.lol._medidas_para_o_coach`. Sem medidas não há avisos: a app não
    inventa conselhos."""
    if not data:
        return {"in_game": False, "alerts": []}

    jogo = data.get("gameData") or {}
    segundos = float(jogo.get("gameTime", 0) or 0)
    lado = _lado(data)
    eu = _eu(data)
    if eu is None:
        return {"in_game": False, "alerts": []}

    pontos = eu.get("scores") or {}
    alertas: list[dict] = []

    # ── o lado do mapa ────────────────────────────────────────────
    # É o maior efeito medido nele e sabe-se no segundo zero. Aparece cedo
    # porque o que ele tem de mudar (ir ao dragão, jogar fora de casa) decide-se
    # no primeiro percurso.
    m_lado = medidas.get("map_side")
    if lado and m_lado and m_lado.get("proven") and segundos < 6 * 60:
        pior = m_lado["better_side"] != lado
        causa = (m_lado.get("causes") or [None])[0]
        alertas.append({
            "key": "lado",
            "level": "aviso" if pior else "bom",
            "title": f"Lado {lado}",
            "text": (
                f"Ganhas {m_lado[lado]['winrate']}% deste lado contra "
                f"{m_lado['red' if lado == 'blue' else 'blue']['winrate']}% do outro"
                + (f". A maior diferença está em {causa['label'].lower()}" if causa else "")
                + ("." if not pior else " — e é este o teu lado fraco.")
            ),
            "since": 0,
        })

    # ── control wards ─────────────────────────────────────────────
    # O achado mais forte de todos (z = −10,4) e o mais barato de corrigir: 75
    # de ouro.
    m_cw = medidas.get("control_wards")
    if m_cw and segundos >= _MIN_CONTROL_WARD and not _tem_control_ward(eu):
        alertas.append({
            "key": "control_ward",
            "level": "aviso",
            "title": "Sem control ward",
            "text": (
                f"Vais em {int(segundos // 60)} minutos sem nenhuma. Contra o jungler "
                f"adversário perdes este duelo em {100 - int(m_cw['win_pct'])}% dos jogos "
                f"em que se decide — é a coisa mais barata de corrigir que tens."
            ),
            "since": _MIN_CONTROL_WARD,
        })

    # ── o farm dos primeiros dez minutos ──────────────────────────
    m_cs = medidas.get("jungle_cs10")
    cs = pontos.get("creepScore")
    if m_cs and cs is not None and _MIN_CS10 <= segundos < 12 * 60:
        esperado = m_cs["mine"]
        if cs < esperado - 6:
            alertas.append({
                "key": "cs10",
                "level": "aviso",
                "title": f"{int(cs)} de farm aos 10",
                "text": (
                    f"O teu costume aos dez minutos é {esperado:.0f}, e mesmo esse fica "
                    f"{abs(m_cs['diff']):.0f} abaixo do jungler adversário. Aos 10 os teus "
                    "jogos ganhos e perdidos ainda são parecidos; aos 15 já não."
                ),
                "since": _MIN_CS10,
            })

    # ── o dragão, do lado em que ele o perde ──────────────────────
    if lado and m_lado and m_lado.get("proven") and m_lado["better_side"] != lado:
        meus, deles = _dragoes(data, lado)
        if segundos >= 8 * 60 and deles > meus:
            alertas.append({
                "key": "dragao",
                "level": "aviso",
                "title": f"Dragões {meus}-{deles}",
                "text": (
                    f"Deste lado ficas atrás no dragão em relação ao jungler adversário, e "
                    "é a maior diferença entre os teus dois lados — apesar de o lado azul "
                    "ser o que tem a pit do lado de dentro."
                ),
                "since": 8 * 60,
            })

    return {
        "in_game": True,
        "side": lado,
        "game_time": int(segundos),
        "champion": eu.get("championName"),
        "cs": cs,
        "alerts": alertas,
    }
