"""Quanto da IA cada parte da app gasta, e um travão por dia.

O agente é partilhado por 15 sítios diferentes — deals, sinais de investimento,
diário, Perguntar, histórias, Spotify, recibos, planeador — e é o recurso mais
escasso que a app tem (351 respostas de "rate limit" no log). Não havia forma de
saber quem gastava o quê, nem nada que impedisse uma parte de comer a quota toda:
uma pesquisa de deals com 200 anúncios novos deixava o Perguntar sem IA o resto
do dia.

Isto conta as chamadas por parte da app e por dia, e deixa cada parte ter um
tecto. Quem passa do tecto não fica sem funcionar — fica sem IA nessa passagem,
e volta a tê-la no dia seguinte.
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from datetime import date

logger = logging.getLogger(__name__)

# Tectos por dia. Generosos: isto é uma rede de segurança, não um orçamento
# apertado. `None` = sem tecto (o que o utilizador pede à mão nunca é travado).
TECTOS: dict[str, int | None] = {
    "deals": 12,            # 2 pesquisas por dia × poucos lotes
    "sinais": 20,
    "lojas_banco": 6,
    "spotify": 20,
    "stories": 30,
    "code": 20,
    "aquecer": 12,
    "recibos": 30,
    "planeador": 10,
    "relogio": 8,           # a leitura do dia; fica em cache por dia
    "ask": None,            # é ele a perguntar; nunca se trava
    "captura": None,
    "outro": None,
}

_lock = threading.Lock()
_contagem: dict[tuple[date, str], int] = defaultdict(int)


def _hoje() -> date:
    return date.today()


def regista(feature: str) -> int:
    """Conta mais uma chamada. Devolve quantas vão hoje nessa parte."""
    chave = (_hoje(), feature or "outro")
    with _lock:
        _contagem[chave] += 1
        # Ontem já não interessa a ninguém.
        for k in [k for k in _contagem if k[0] != chave[0]]:
            del _contagem[k]
        return _contagem[chave]


def gastas(feature: str) -> int:
    with _lock:
        return _contagem.get((_hoje(), feature), 0)


def permitido(feature: str) -> bool:
    """Ainda há quota hoje para esta parte da app?"""
    tecto = TECTOS.get(feature, TECTOS["outro"])
    if tecto is None:
        return True
    if gastas(feature) < tecto:
        return True
    logger.info("ia: %s chegou ao tecto de hoje (%s chamadas)", feature, tecto)
    return False


def estado() -> dict:
    """Para o painel de saúde: o que a IA gastou hoje, por parte da app."""
    hoje = _hoje()
    with _lock:
        por_feature = {f: n for (d, f), n in sorted(_contagem.items()) if d == hoje}
    return {
        "date": hoje.isoformat(),
        "total": sum(por_feature.values()),
        "by_feature": por_feature,
        "limits": {k: v for k, v in TECTOS.items() if v is not None},
        "capped": [f for f, n in por_feature.items()
                   if TECTOS.get(f) is not None and n >= (TECTOS.get(f) or 0)],
    }
