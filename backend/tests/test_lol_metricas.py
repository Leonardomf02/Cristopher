"""O parser da Riot tem de trazer o desempenho de cada jogo, não só K/D/A."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from riot_api import parse_match


def _partida(**muda):
    """Uma partida da Match-V5 com o mínimo que o parser precisa."""
    eu = {
        "puuid": "EU", "teamId": 100, "teamPosition": "JUNGLE", "win": True,
        "championName": "Khazix", "kills": 9, "deaths": 3, "assists": 7,
        "totalMinionsKilled": 42, "neutralMinionsKilled": 118,
        "goldEarned": 13450, "totalDamageDealtToChampions": 24310,
        "totalDamageTaken": 19870, "visionScore": 21,
    }
    eu.update(muda)
    return {
        "metadata": {"matchId": "EUW1_123"},
        "info": {
            "mapId": 11,
            "gameDuration": 1800,
            "gameStartTimestamp": 1776073997486,
            "participants": [
                eu,
                {"puuid": "COLEGA", "teamId": 100, "teamPosition": "MIDDLE", "kills": 5},
                {"puuid": "OUTRO", "teamId": 100, "teamPosition": "TOP", "kills": 2},
                {"puuid": "INIMIGO", "teamId": 200, "teamPosition": "JUNGLE",
                 "kills": 4, "championName": "LeeSin"},
            ],
        },
    }


def test_traz_cs_ouro_dano_e_visao():
    r = parse_match(_partida(), "EU")
    assert r["cs"] == 160                 # 42 de linha + 118 de selva
    assert r["cs_jungle"] == 118
    assert r["gold"] == 13450
    assert r["damage"] == 24310
    assert r["damage_taken"] == 19870
    assert r["vision"] == 21


def test_abates_da_equipa_somam_so_a_equipa_dele():
    r = parse_match(_partida(), "EU")
    assert r["team_kills"] == 16           # 9 + 5 + 2, sem os 4 do inimigo


def test_participacao_em_abates_da_para_calcular():
    r = parse_match(_partida(), "EU")
    kp = (r["kills"] + r["assists"]) / r["team_kills"]
    assert round(kp, 2) == 1.0             # 16 em 16: participou em tudo


def test_partida_sem_os_campos_novos_nao_rebenta():
    """Partidas antigas ou modos estranhos podem não trazer tudo."""
    sem = _partida()
    for campo in ("totalMinionsKilled", "neutralMinionsKilled", "goldEarned",
                  "totalDamageDealtToChampions", "totalDamageTaken", "visionScore"):
        del sem["info"]["participants"][0][campo]
    r = parse_match(sem, "EU")
    assert r["cs"] == 0 and r["gold"] == 0 and r["vision"] == 0
    assert r["kills"] == 9                 # o resto continua a vir


def test_o_que_ja_funcionava_continua_igual():
    r = parse_match(_partida(), "EU")
    assert r["won"] is True
    assert r["champion_played"] == "Khazix"
    assert r["champion_against"] == "LeeSin"
    assert r["role"] == "jungle"
    assert r["team_side"] == "blue"
    assert r["game_duration"] == 1800
