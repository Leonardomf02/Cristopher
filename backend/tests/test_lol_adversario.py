"""O jogador do outro lado contra o campeão que eu tenho em mãos.

A Riot não responde a "os jogos dele contra X" — dá a lista dos últimos jogos e
cada jogo em detalhe. A conta é feita à mão sobre esses jogos, e há duas
maneiras de a fazer errada: contar jogos em que o meu campeão estava na equipa
*dele*, e misturar o que ele fez com o campeão que tem agora com o que fez com
todos os outros.

Corre sozinho:  python tests/test_lol_adversario.py
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import riot_api

ELE = "puuid-adversario"


def _jogo(mid, campeao_dele, campeoes_inimigos, ganhou, duracao=1800, aliados=()):
    parts = [{
        "puuid": ELE, "championName": campeao_dele, "teamId": 100, "win": ganhou,
        "kills": 5, "deaths": 3, "assists": 7, "teamPosition": "JUNGLE",
    }]
    for i, c in enumerate(aliados):
        parts.append({"puuid": f"amigo-{mid}-{i}", "championName": c, "teamId": 100,
                      "win": ganhou, "kills": 1, "deaths": 1, "assists": 1,
                      "teamPosition": "TOP"})
    for i, c in enumerate(campeoes_inimigos):
        parts.append({"puuid": f"inimigo-{mid}-{i}", "championName": c, "teamId": 200,
                      "win": not ganhou, "kills": 2, "deaths": 2, "assists": 2,
                      "teamPosition": "JUNGLE" if i == 0 else "MIDDLE"})
    return {
        "metadata": {"matchId": mid},
        "info": {"gameStartTimestamp": 1_750_000_000_000, "gameDuration": duracao,
                 "participants": parts},
    }


class Riot:
    """Substitui o `_get`: devolve a lista de jogos e cada jogo, e conta pedidos."""
    def __init__(self, jogos):
        self.jogos = {j["metadata"]["matchId"]: j for j in jogos}
        self.pedidos = []

    async def __call__(self, url, api_key, params=None):
        self.pedidos.append(url)
        if url.endswith("/ids"):
            return list(self.jogos.keys())
        return self.jogos[url.rsplit("/", 1)[-1]]


def _corre(falso, campeao_dele="Warwick", meu="MonkeyKing"):
    riot_api.limpa_cache_jogadores()
    original = riot_api._get
    riot_api._get = falso
    try:
        return asyncio.run(riot_api.historico_do_adversario(
            ELE, meu, campeao_dele, "chave", asyncio.Semaphore(4),
        ))
    finally:
        riot_api._get = original


def test_so_contam_os_jogos_em_que_ele_enfrentou_o_meu_campeao():
    falso = Riot([
        _jogo("EUW_1", "Warwick", ["MonkeyKing", "Ahri"], True),
        _jogo("EUW_2", "Warwick", ["LeeSin", "Ahri"], True),
        # o meu campeão do lado DELE não é um jogo contra mim
        _jogo("EUW_3", "Warwick", ["LeeSin"], False, aliados=["MonkeyKing"]),
    ])
    r = _corre(falso)
    assert r["scanned"] == 3
    assert r["vs_all"]["games"] == 1, "só o EUW_1 é um encontro com o meu campeão"
    assert r["vs_all"]["wins"] == 1 and r["vs_all"]["winrate"] == 100
    assert [g["champion"] for g in r["games"]] == ["Warwick"]


def test_separa_o_campeao_que_ele_tem_agora_dos_outros():
    falso = Riot([
        _jogo("EUW_1", "Warwick", ["MonkeyKing"], True),
        _jogo("EUW_2", "Warwick", ["MonkeyKing"], False),
        _jogo("EUW_3", "Viego", ["MonkeyKing"], False),
    ])
    r = _corre(falso, campeao_dele="Warwick")
    assert r["vs_all"] == {"games": 3, "wins": 1, "losses": 2, "winrate": 33}
    assert r["with_current"] == {"champion": "Warwick", "wins": 1, "losses": 1,
                                 "games": 2, "winrate": 50}
    assert [l["champion"] for l in r["by_champion"]] == ["Warwick", "Viego"]


def test_nunca_apanhou_o_meu_campeao_diz_quantos_jogos_leu():
    falso = Riot([_jogo(f"EUW_{i}", "Warwick", ["LeeSin"], True) for i in range(5)])
    r = _corre(falso)
    assert r["scanned"] == 5
    assert r["vs_all"] is None and r["with_current"] is None and r["games"] == []


def test_remakes_nao_contam():
    falso = Riot([
        _jogo("EUW_1", "Warwick", ["MonkeyKing"], True, duracao=200),
        _jogo("EUW_2", "Warwick", ["MonkeyKing"], True),
    ])
    r = _corre(falso)
    assert r["scanned"] == 1 and r["vs_all"]["games"] == 1


def test_o_mesmo_jogo_nao_se_pede_duas_vezes():
    jogos = [_jogo("EUW_1", "Warwick", ["MonkeyKing"], True)]
    falso = Riot(jogos)
    riot_api.limpa_cache_jogadores()
    original = riot_api._get
    riot_api._get = falso

    async def corre():
        sem = asyncio.Semaphore(4)
        a = await riot_api.historico_do_adversario(ELE, "MonkeyKing", "Warwick", "k", sem)
        # outro campeão meu: a lista e o jogo já foram lidos, só a conta muda
        b = await riot_api.historico_do_adversario(ELE, "LeeSin", "Warwick", "k", sem)
        return a, b

    try:
        a, b = asyncio.run(corre())
    finally:
        riot_api._get = original
    assert falso.pedidos.count("https://europe.api.riotgames.com/lol/match/v5/matches/EUW_1") == 1
    assert a["vs_all"]["games"] == 1 and b["vs_all"] is None


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print(f"ok — {nome}")
    print("tudo passou")
