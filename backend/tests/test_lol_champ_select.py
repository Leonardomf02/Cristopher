"""Champ select: quem é o jungler adversário, e o que ele já fez contra ele.

O cliente do LoL manda `assignedPosition` só para a equipa dele — os cinco
inimigos vêm sem posição nenhuma. Sem deduzir o jungler, a página ficava sempre
em "sem jungler adversário conhecido": sem matchup, sem histórico, sem counter
pick.
"""
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import meta_stats as ms
import routers.lol as L


# ── Quem é o jungler do outro lado ──────────────────────────────

def _com_fatias(monkeypatch, fatias):
    async def falso(force=False):
        return fatias
    monkeypatch.setattr(ms, "lane_shares", falso)
    monkeypatch.setattr(ms, "lane_shares_cached", lambda: fatias)


def test_o_jungler_e_quem_se_joga_de_jungle(monkeypatch):
    """Kindred joga-se só de jungle; Sylas divide-se entre mid e jungle. Num
    draft com os dois, o smite é dela."""
    _com_fatias(monkeypatch, {
        "kindred": {"jungle": 1.0},
        "sylas": {"jungle": 0.43, "middle": 0.43, "top": 0.06, "support": 0.08},
        "ryze": {"middle": 0.8, "top": 0.2},
        "lucian": {"bottom": 0.9, "middle": 0.1},
        "syndra": {"middle": 1.0},
    })
    escolhido = asyncio.run(ms.lane_provavel(["Ryze", "Sylas", "Kindred", "Lucian", "Syndra"]))
    assert escolhido == "Kindred"


def test_sem_ninguem_de_jungle_nao_se_aponta_ninguem(monkeypatch):
    """Apontar o menos improvável de cinco laners seria inventar um matchup."""
    _com_fatias(monkeypatch, {
        "ryze": {"middle": 1.0},
        "lucian": {"bottom": 1.0},
        "syndra": {"middle": 1.0},
    })
    assert asyncio.run(ms.lane_provavel(["Ryze", "Lucian", "Syndra"])) is None


def test_o_nome_do_ddragon_e_o_do_meta_sao_o_mesmo_campeao(monkeypatch):
    """A app guarda 'MonkeyKing', a lolalytics diz 'wukong'."""
    _com_fatias(monkeypatch, {"wukong": {"jungle": 0.9, "top": 0.1}})
    assert asyncio.run(ms.lane_provavel(["MonkeyKing"])) == "MonkeyKing"


# ── O histórico dele contra esse jungler ────────────────────────

class _Jogo:
    def __init__(self, jogado, contra, ganhou, dia, kda=(1, 2, 3)):
        self.role = "jungle"
        self.champion_played = jogado
        self.champion_against = contra
        self.won = ganhou
        self.date = date(2026, 4, dia)
        self.kills, self.deaths, self.assists = kda


class _Query:
    def __init__(self, jogos):
        self._jogos = jogos

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return self._jogos


class _DB:
    def __init__(self, jogos):
        self._jogos = jogos

    def query(self, *a, **k):
        return _Query(self._jogos)


JOGOS = [
    _Jogo("Khazix", "Kindred", False, 29),
    _Jogo("Khazix", "Kindred", False, 16),
    _Jogo("JarvanIV", "Kindred", True, 12),
    _Jogo("JarvanIV", "Kindred", False, 10),
    _Jogo("LeeSin", "Elise", True, 8),
]


def test_conta_os_jogos_contra_aquele_jungler_e_mais_nenhum():
    h = L._historico_contra(_DB(JOGOS), "Kindred", None)
    assert (h["games"], h["wins"], h["losses"]) == (4, 1, 3)
    assert {c["champion"] for c in h["by_champion"]} == {"Khazix", "JarvanIV"}


def test_o_campeao_em_maos_traz_os_jogos_um_a_um():
    """O display name do cliente ('Kha'Zix') e a chave da base ('Khazix') são o
    mesmo campeão — sem isso o painel ficava sempre em 'primeira vez'."""
    h = L._historico_contra(_DB(JOGOS), "Kindred", "Kha'Zix")
    assert len(h["current_pick_games"]) == 2
    assert [g["won"] for g in h["current_pick_games"]] == [False, False]
    assert h["current_pick_games"][0]["date"] == "2026-04-29"


def test_um_campeao_nunca_jogado_contra_ele_nao_inventa_jogos():
    h = L._historico_contra(_DB(JOGOS), "Kindred", "Warwick")
    assert h["current_pick_games"] == []
    assert h["games"] == 4


def test_sem_jogos_nenhuns_nao_ha_painel():
    assert L._historico_contra(_DB(JOGOS), "Briar", "Khazix") is None


def test_com_a_cache_fria_ninguem_e_apontado(monkeypatch):
    """O champ select não espera por cinco páginas: usa o que já tem e aquece o
    resto em segundo plano. Sem cache, diz que não sabe."""
    monkeypatch.setattr(ms, "lane_shares_cached", dict)
    assert ms.lane_provavel_cached(["Kindred", "Sylas"]) is None


# ── Jogo ao vivo: quem joga em que lane ─────────────────────────

def _jogador(nome, cid, historico, feiticos=(4, 14)):
    return {"champion_name": nome, "champion_id": cid, "role_distribution": historico,
            "spell1": feiticos[0], "spell2": feiticos[1], "puuid": f"{nome}-{cid}"}


def _equipa():
    return [
        _jogador("Garen", 86, {"top": 10}),
        _jogador("LeeSin", 64, {"jungle": 10}, (11, 4)),
        _jogador("Ahri", 103, {"adc": 12, "mid": 6}),   # mid que também joga adc
        _jogador("Ezreal", 81, {"adc": 5, "mid": 8}),
        _jogador("Thresh", 412, {"support": 10}),
    ]


def _papeis(equipa):
    return {p["champion_name"]: p["_assigned_role"] for p in equipa}


def test_a_lane_do_campeao_pesa_mais_que_o_historico(monkeypatch):
    """Só pelo histórico, a Ahri caía em adc e a linha do mid aparecia trocada."""
    import riot_api
    _com_fatias(monkeypatch, {"ahri": {"middle": 0.95}, "ezreal": {"bottom": 0.9},
                              "garen": {"top": 0.9}, "leesin": {"jungle": 0.98},
                              "thresh": {"support": 0.97}})
    minha, deles = _equipa(), [dict(p, puuid=p["puuid"] + "-e") for p in _equipa()]
    riot_api._compute_matchups(minha, deles)
    assert _papeis(minha)["Ahri"] == "mid" and _papeis(minha)["Ezreal"] == "adc"


def test_a_posicao_do_draft_ganha_a_tudo(monkeypatch):
    import riot_api
    _com_fatias(monkeypatch, {"ahri": {"middle": 0.95}, "ezreal": {"bottom": 0.9}})
    minha, deles = _equipa(), [dict(p, puuid=p["puuid"] + "-e") for p in _equipa()]
    draft = {86: "top", 64: "jungle", 103: "adc", 81: "mid", 412: "support"}
    riot_api._compute_matchups(minha, deles, draft)
    assert _papeis(minha)["Ahri"] == "adc" and _papeis(minha)["Ezreal"] == "mid"


def test_um_draft_de_outra_partida_nao_conta(monkeypatch):
    import riot_api
    _com_fatias(monkeypatch, {"ahri": {"middle": 0.95}, "ezreal": {"bottom": 0.9}})
    minha, deles = _equipa(), [dict(p, puuid=p["puuid"] + "-e") for p in _equipa()]
    riot_api._compute_matchups(minha, deles, {103: "adc", 81: "mid", 1: "top"})
    assert _papeis(minha)["Ahri"] == "mid"


def test_o_draft_sobrevive_ao_fim_do_champ_select():
    import lol_live
    lol_live.guarda({"client_running": True, "phase": "ChampSelect", "session": {"myTeam": [
        {"championId": 103, "assignedPosition": "middle"},
        {"championId": 81, "assignedPosition": "bottom"},
        {"championId": 0, "assignedPosition": "top"},
    ]}})
    lol_live.guarda({"client_running": True, "phase": "InProgress", "session": None})
    assert lol_live.posicoes_do_draft() == {103: "mid", 81: "adc"}
