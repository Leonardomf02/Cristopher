"""O que o Mac vê do cliente do LoL, empurrado para a app.

O cliente do LoL fala por uma porta local: só o Mac o vê. Com a app na NAS, o
champ select deixava de existir. O agente (`agent/push_local.py`) lê-o no Mac e
manda-o para aqui de poucos em poucos segundos; a app serve-o como se fosse
local — e passa a funcionar também no telemóvel, que nunca viu o cliente.

Vive em memória e caduca depressa: um champ select de há dez minutos é mentira,
e mais vale dizer que não há nada do que mostrar picks de um draft já acabado.
"""
from __future__ import annotations

import time
from typing import Optional

# Um draft dura ~60s por ronda e o agente empurra de 3 em 3 segundos: 25s é
# folga que chega para uma falha de rede sem servir estado velho.
VALIDADE_S = 25.0

_ultimo: dict = {"quando": 0.0, "dados": None}


# As posições da equipa dele, tal como o draft as atribuiu. Sobrevivem ao fim do
# champ select de propósito: é no jogo ao vivo que fazem falta, e aí a Riot já
# não diz quem joga onde — a app adivinhava pelo histórico de cada um e trocava
# o mid com o adc de quem joga as duas.
DRAFT_VALIDADE_S = 3 * 3600
_LCU_PARA_PAPEL = {"top": "top", "jungle": "jungle", "middle": "mid",
                   "bottom": "adc", "utility": "support"}
_draft: dict = {"quando": 0.0, "por_campeao": {}}


def guarda(dados: dict) -> None:
    _ultimo["quando"] = time.time()
    _ultimo["dados"] = dados
    lembra_draft((dados or {}).get("session"))


def lembra_draft(sessao: Optional[dict]) -> None:
    """Guarda campeão → posição da equipa dele. Chamado a cada estado do champ
    select; o último com campeões escolhidos é o que fica."""
    por_campeao = {}
    for p in (sessao or {}).get("myTeam") or []:
        papel = _LCU_PARA_PAPEL.get((p.get("assignedPosition") or "").lower())
        cid = p.get("championId") or 0
        if papel and cid:
            por_campeao[int(cid)] = papel
    if por_campeao:
        _draft["quando"] = time.time()
        _draft["por_campeao"] = por_campeao


def posicoes_do_draft() -> dict[int, str]:
    """Campeão → papel (top/jungle/mid/adc/support) do último draft, se recente."""
    if time.time() - _draft["quando"] > DRAFT_VALIDADE_S:
        return {}
    return dict(_draft["por_campeao"])


def estado() -> Optional[dict]:
    """O último estado empurrado, ou None quando já passou da validade."""
    dados = _ultimo.get("dados")
    if not dados or (time.time() - _ultimo["quando"]) > VALIDADE_S:
        return None
    return dados


def idade_s() -> Optional[float]:
    """Há quanto tempo chegou o último estado. None se nunca chegou nada."""
    if not _ultimo.get("dados"):
        return None
    return round(time.time() - _ultimo["quando"], 1)
