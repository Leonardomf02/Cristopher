"""A análise ao vivo tem mesmo de pedir o histórico do adversário directo.

A conta pode estar certa e não ser chamada por ninguém — foi o que aconteceu ao
`fetch_external_counters`, que estava morta há meses sem ninguém dar por isso.
Este teste corre a análise ao vivo inteira com a Riot fingida e verifica que o
jungler do outro lado (e não outro qualquer) chega ao painel.

Corre sozinho:  python tests/test_lol_adversario_ligacao.py
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import riot_api

EU = "puuid-eu"


def _participante(puuid, champ_id, team, smite=False):
    return {"puuid": puuid, "championId": champ_id, "teamId": team,
            "riotId": f"{puuid}#EUW", "spell1Id": 11 if smite else 4, "spell2Id": 14}


JOGO = {
    "gameStartTime": 1_750_000_000_000, "gameLength": 600, "mapId": 11,
    "gameMode": "CLASSIC", "gameType": "MATCHED", "bannedChampions": [],
    "participants": [
        _participante(EU, 59, 100, smite=True),          # eu, Jarvan, jungle
        _participante("puuid-mid", 103, 100),
        _participante("puuid-jg-inimigo", 19, 200, smite=True),   # Warwick, jungle
        _participante("puuid-top-inimigo", 86, 200),
    ],
}

NOMES = {59: "JarvanIV", 103: "Ahri", 19: "Warwick", 86: "Garen"}


def _prepara():
    riot_api.limpa_cache_jogadores()
    riot_api._champion_id_map.update(NOMES)
    riot_api._puuid_cache["Cristóvão#2002"] = EU

    pedidos = {}

    async def sem_rede(*a, **kw):
        return None

    async def active(puuid, api_key):
        return JOGO

    async def rank(puuid, api_key, sem):
        return {"tier": "MASTER", "rank": "I", "lp": 100, "wins": 10, "losses": 10,
                "winrate": 50.0}

    async def mastery(puuid, champ_id, api_key, sem):
        return {"points": 100_000, "level": 7}

    async def matches(puuid, champion_name, api_key, sem, detail_count=5):
        return {"champion_stats": None, "role_distribution": {"jungle": 10},
                "recent_results": [True, False], "total_recent": 2,
                "avg_stats": None, "match_ids": [], "unique_champions": [],
                "games_today": 0, "kda_trend": [], "co_players": {}}

    async def historico(puuid, meu, dele, api_key, sem, jogos=20):
        pedidos["puuid"] = puuid
        pedidos["meu"] = meu
        pedidos["dele"] = dele
        return {"champion": dele, "scanned": 20, "games": [],
                "vs_all": None, "with_current": None, "by_champion": []}

    originais = {n: getattr(riot_api, n) for n in
                 ("get_active_game", "_live_fetch_rank", "_live_fetch_mastery",
                  "_live_fetch_matches", "historico_do_adversario", "_ensure_champion_map")}
    riot_api.get_active_game = active
    riot_api._live_fetch_rank = rank
    riot_api._live_fetch_mastery = mastery
    riot_api._live_fetch_matches = matches
    riot_api.historico_do_adversario = historico
    riot_api._ensure_champion_map = sem_rede
    return pedidos, originais


def _repoe(originais):
    for n, f in originais.items():
        setattr(riot_api, n, f)


def test_pergunta_pelo_jungler_do_outro_lado_e_pelo_meu_campeao():
    pedidos, originais = _prepara()
    try:
        r = asyncio.run(riot_api.get_live_game_detailed("Cristóvão", "2002", "chave"))
    finally:
        _repoe(originais)

    assert pedidos["puuid"] == "puuid-jg-inimigo", "tem de ser o adversário directo"
    assert pedidos["meu"] == "JarvanIV" and pedidos["dele"] == "Warwick"
    assert r["enemy_vs_my_champion"]["scanned"] == 20
    assert r["enemy_vs_my_champion"]["player"] == "puuid-jg-inimigo#EUW"
    assert r["enemy_vs_my_champion"]["my_champion"] == "JarvanIV"
    adversario = next(p for p in r["enemy_team"] if p["puuid"] == "puuid-jg-inimigo")
    assert adversario["vs_my_champion"]["champion"] == "Warwick"


def test_jogador_sem_dados_publicos_nao_se_pergunta():
    """Modo stream/perfil privado: a Riot não devolve nada desse jogador. Pedir
    20 jogos para receber vazio é queimar quota — e o painel não pode inventar
    um histórico que não tem."""
    pedidos, originais = _prepara()

    async def rank_vazio(puuid, api_key, sem):
        return None

    async def mastery_vazia(puuid, champ_id, api_key, sem):
        return {"points": 0, "level": 0}

    async def matches_vazio(puuid, champion_name, api_key, sem, detail_count=5):
        return {"champion_stats": None, "role_distribution": {}, "recent_results": [],
                "total_recent": 0, "avg_stats": None, "match_ids": [],
                "unique_champions": [], "games_today": 0, "kda_trend": [], "co_players": {}}

    riot_api._live_fetch_rank = rank_vazio
    riot_api._live_fetch_mastery = mastery_vazia
    riot_api._live_fetch_matches = matches_vazio
    try:
        r = asyncio.run(riot_api.get_live_game_detailed("Cristóvão", "2002", "chave"))
    finally:
        _repoe(originais)

    assert pedidos == {}, "sem dados públicos não se gasta um pedido sequer"
    assert r["enemy_vs_my_champion"] is None


if __name__ == "__main__":
    test_pergunta_pelo_jungler_do_outro_lado_e_pelo_meu_campeao()
    print("ok — o adversário directo é pedido e chega ao painel")
    test_jogador_sem_dados_publicos_nao_se_pergunta()
    print("ok — modo stream / perfil privado não gasta pedidos")
