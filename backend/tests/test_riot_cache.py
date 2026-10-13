"""A análise ao vivo não pode voltar a queimar a quota da Riot.

Por cada refrescamento pedia rank + maestria + lista de jogos + 5 jogos em
detalhe para os 10 jogadores (~80 pedidos), de 90 em 90 segundos, com uma chave
que dá 100 pedidos por 2 minutos: 26.871 linhas de "Rate limited" no log, metade
do ficheiro. Nada disto muda a meio da partida.

Corre sozinho:  python tests/test_riot_cache.py
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import riot_api


class ContaPedidos:
    """Substitui o `_get` e conta quantas vezes foi chamado."""
    def __init__(self, resposta):
        self.resposta = resposta
        self.chamadas = 0

    async def __call__(self, url, api_key, params=None):
        self.chamadas += 1
        return self.resposta


def _com_get(falso, fn):
    original = riot_api._get
    riot_api._get = falso
    try:
        return asyncio.run(fn())
    finally:
        riot_api._get = original


def _limpa():
    riot_api.limpa_cache_jogadores()


RANK = [{"queueType": "RANKED_SOLO_5x5", "tier": "MASTER", "rank": "I",
         "leaguePoints": 130, "wins": 200, "losses": 180, "hotStreak": True}]


def test_rank_do_mesmo_jogador_so_se_pede_uma_vez():
    _limpa()
    falso = ContaPedidos(RANK)
    sem = asyncio.Semaphore(4)

    async def corre():
        a = await riot_api._live_fetch_rank("puuid-1", "k", sem)
        b = await riot_api._live_fetch_rank("puuid-1", "k", sem)
        return a, b

    a, b = _com_get(falso, corre)
    assert falso.chamadas == 1, "a segunda leitura tinha de vir da cache"
    assert a == b and a["tier"] == "MASTER"


def test_jogadores_diferentes_nao_partilham_cache():
    _limpa()
    falso = ContaPedidos(RANK)
    sem = asyncio.Semaphore(4)

    async def corre():
        await riot_api._live_fetch_rank("puuid-1", "k", sem)
        await riot_api._live_fetch_rank("puuid-2", "k", sem)

    _com_get(falso, corre)
    assert falso.chamadas == 2


def test_jogador_sem_puuid_nao_chega_a_pedir():
    """Eram 743 pedidos com o puuid a `None`, todos a devolver 400."""
    _limpa()
    falso = ContaPedidos(RANK)
    sem = asyncio.Semaphore(4)

    async def corre():
        return (
            await riot_api._live_fetch_rank("", "k", sem),
            await riot_api._live_fetch_mastery("", 1, "k", sem),
            await riot_api._live_fetch_matches("", "Lee Sin", "k", sem),
        )

    rank, maestria, jogos = _com_get(falso, corre)
    assert falso.chamadas == 0
    assert rank is None
    assert maestria == {"points": 0, "level": 0}
    assert jogos["total_recent"] == 0


def test_sem_rank_tambem_fica_em_cache():
    """Um jogador sem ranked devolve vazio; sem guardar isso, era pedido outra
    vez a cada refrescamento."""
    _limpa()
    falso = ContaPedidos([])            # nenhuma fila ranked
    sem = asyncio.Semaphore(4)

    async def corre():
        await riot_api._live_fetch_rank("puuid-9", "k", sem)
        await riot_api._live_fetch_rank("puuid-9", "k", sem)

    _com_get(falso, corre)
    assert falso.chamadas == 1


def test_maestria_e_por_campeao():
    _limpa()
    falso = ContaPedidos({"championPoints": 50000, "championLevel": 7})
    sem = asyncio.Semaphore(4)

    async def corre():
        a = await riot_api._live_fetch_mastery("puuid-1", 64, "k", sem)
        b = await riot_api._live_fetch_mastery("puuid-1", 64, "k", sem)
        c = await riot_api._live_fetch_mastery("puuid-1", 121, "k", sem)
        return a, b, c

    a, b, c = _com_get(falso, corre)
    assert falso.chamadas == 2          # dois campeões, não três leituras
    assert a == b == {"points": 50000, "level": 7}


def test_historico_sem_jogos_nao_se_repete():
    _limpa()
    falso = ContaPedidos([])            # sem match ids
    sem = asyncio.Semaphore(4)

    async def corre():
        await riot_api._live_fetch_matches("puuid-1", "Lee Sin", "k", sem)
        await riot_api._live_fetch_matches("puuid-1", "Lee Sin", "k", sem)

    _com_get(falso, corre)
    assert falso.chamadas == 1


def test_uma_partida_inteira_custa_uma_leitura_por_jogador():
    """O caso que interessa: 10 jogadores e 20 refrescamentos."""
    _limpa()
    falso = ContaPedidos(RANK)
    sem = asyncio.Semaphore(4)

    async def corre():
        for _ in range(20):                       # 30 min de jogo, 90s por poll
            for i in range(10):
                await riot_api._live_fetch_rank(f"p{i}", "k", sem)

    _com_get(falso, corre)
    assert falso.chamadas == 10, f"esperava 10 pedidos, foram {falso.chamadas}"


def test_cache_nao_cresce_sem_limite():
    _limpa()
    for i in range(500):
        riot_api._cache_guarda(f"rank:p{i}", {"tier": "GOLD"})
    assert len(riot_api._cache_jogador) <= 400


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {nome}")
            except AssertionError as ex:
                falhas += 1
                print(f"  FALHA {nome}: {ex}")
    print(f"\n{falhas} falhas")
    sys.exit(1 if falhas else 0)
