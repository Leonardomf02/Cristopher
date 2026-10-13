"""O treinador ao vivo — o que a app diz enquanto o jogo ainda dá para mudar.

Os estados de jogo são o formato real do Live Client Data API (porta 2999), e os
números medidos são os dos 495 duelos dele.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lol_coach as lc


def _jogo(*, lado="ORDER", minutos=12.0, itens=(), cs=60, campeao="JarvanIV"):
    eu = {
        "riotId": "Cristóvão#2002", "summonerName": "Cristóvão#2002",
        "championName": campeao, "team": lado,
        "items": [{"itemID": i} for i in itens],
        "scores": {"creepScore": cs, "kills": 2, "deaths": 1, "assists": 4, "wardScore": 8},
    }
    inimigo = {"riotId": "Outro#EUW", "summonerName": "Outro#EUW", "championName": "Viego",
               "team": "CHAOS" if lado == "ORDER" else "ORDER", "items": [],
               "scores": {"creepScore": 70}}
    return {
        "activePlayer": {"summonerName": "Cristóvão#2002"},
        "allPlayers": [eu, inimigo],
        "gameData": {"gameTime": minutos * 60},
        "events": {"Events": []},
    }


MEDIDAS = {
    "map_side": {
        "blue": {"games": 263, "winrate": 45.2}, "red": {"games": 236, "winrate": 57.6},
        "diff": 12.4, "z": 2.76, "proven": True, "better_side": "red",
        "causes": [{"metric": "dragons", "label": "Dragões", "blue": -0.36,
                    "red": 0.50, "diff": 0.86, "z": 4.03, "better_on_red": True}],
    },
    "control_wards": {"metric": "control_wards", "label": "Wards de controlo",
                      "win_pct": 22, "proven": True, "diff": 0.0},
    "jungle_cs10": {"metric": "jungle_cs10", "label": "CS de selva aos 10min",
                    "mine": 58.0, "theirs": 64.0, "diff": -6.0, "proven": True},
}


def _chaves(r):
    return {a["key"] for a in r["alerts"]}


# ── O lado do mapa ──────────────────────────────────────────────

def test_avisa_do_lado_fraco_no_inicio_do_jogo():
    """O maior efeito medido nele sabe-se ao segundo zero, e o que ele tem de
    mudar decide-se no primeiro percurso."""
    r = lc.avisos(_jogo(lado="ORDER", minutos=2), MEDIDAS)
    assert r["side"] == "blue"
    aviso = next(a for a in r["alerts"] if a["key"] == "lado")
    assert aviso["level"] == "aviso"
    assert "45.2" in aviso["text"] and "57.6" in aviso["text"]
    assert "dragões" in aviso["text"].lower()


def test_do_lado_bom_o_aviso_muda_de_tom():
    r = lc.avisos(_jogo(lado="CHAOS", minutos=2), MEDIDAS)
    assert r["side"] == "red"
    assert next(a for a in r["alerts"] if a["key"] == "lado")["level"] == "bom"


def test_o_aviso_do_lado_nao_persegue_o_jogo_todo():
    """Aos vinte minutos já não há nada a fazer com essa informação."""
    assert "lado" not in _chaves(lc.avisos(_jogo(minutos=20), MEDIDAS))


# ── Control wards ───────────────────────────────────────────────

def test_avisa_da_control_ward_em_falta():
    r = lc.avisos(_jogo(minutos=12, itens=(3047, 6692)), MEDIDAS)
    aviso = next(a for a in r["alerts"] if a["key"] == "control_ward")
    assert "78%" in aviso["text"]           # 100 − 22
    assert "12 minutos" in aviso["text"]


def test_nao_avisa_quem_ja_tem_control_ward():
    r = lc.avisos(_jogo(minutos=12, itens=(3047, 2055)), MEDIDAS)
    assert "control_ward" not in _chaves(r)


def test_nao_avisa_antes_de_haver_ouro_para_ela():
    assert "control_ward" not in _chaves(lc.avisos(_jogo(minutos=4), MEDIDAS))


# ── Farm ────────────────────────────────────────────────────────

def test_avisa_do_farm_atrasado_aos_dez():
    r = lc.avisos(_jogo(minutos=10.5, cs=45, itens=(2055,)), MEDIDAS)
    aviso = next(a for a in r["alerts"] if a["key"] == "cs10")
    assert "45" in aviso["title"]
    assert "58" in aviso["text"]


def test_nao_avisa_quem_esta_no_seu_costume():
    r = lc.avisos(_jogo(minutos=10.5, cs=58, itens=(2055,)), MEDIDAS)
    assert "cs10" not in _chaves(r)


# ── Dragões ─────────────────────────────────────────────────────

def test_avisa_do_dragao_so_do_lado_em_que_o_perde():
    jogo = _jogo(lado="ORDER", minutos=14, itens=(2055,))
    jogo["events"]["Events"] = [
        {"EventName": "DragonKill", "KillerName": "Outro#EUW"},
        {"EventName": "DragonKill", "KillerName": "Outro#EUW"},
    ]
    assert "dragao" in _chaves(lc.avisos(jogo, MEDIDAS))
    # do lado bom, o mesmo estado não gera aviso
    jogo["allPlayers"][0]["team"] = "CHAOS"
    jogo["allPlayers"][1]["team"] = "ORDER"
    assert "dragao" not in _chaves(lc.avisos(jogo, MEDIDAS))


# ── A regra que manda em tudo ───────────────────────────────────

def test_sem_medidas_a_app_cala_se():
    """Nada de conselhos de guia da internet: o que não foi medido nele não é
    dito. Um jogo mau em todos os eixos, sem medidas, não produz um único aviso."""
    r = lc.avisos(_jogo(minutos=15, cs=20), {})
    assert r["alerts"] == []


def test_medida_sem_prova_nao_fala():
    """O router só passa o que tem `proven`; se algo escapar, não vale."""
    r = lc.avisos(_jogo(lado="ORDER", minutos=2),
                  {"map_side": {**MEDIDAS["map_side"], "proven": False}})
    assert "lado" not in _chaves(r)


def test_fora_de_jogo_nao_ha_nada_a_dizer():
    assert lc.avisos(None, MEDIDAS) == {"in_game": False, "alerts": []}


# ── O que o cliente manda, e nem sempre da mesma maneira ─────────

def test_encontra_o_jogador_seja_qual_for_o_campo_do_nome():
    """Conforme a versão, o cliente põe o nome em `riotId`, `summonerName` ou
    `riotIdGameName`. Ler só um deles é não encontrar o jogador — e não o
    encontrar aqui é a app calar-se sem dizer porquê."""
    for campo in ("riotId", "summonerName", "riotIdGameName"):
        d = _jogo(lado="ORDER", minutos=2)
        d["activePlayer"] = {campo: "Cristóvão#2002"}
        r = lc.avisos(d, MEDIDAS)
        assert r["in_game"] is True, campo
        assert r["side"] == "blue", campo


def test_jogador_que_nao_esta_na_lista_nao_rebenta_nada():
    d = _jogo(minutos=12)
    d["activePlayer"] = {"summonerName": "OutraPessoa#XX"}
    assert lc.avisos(d, MEDIDAS) == {"in_game": False, "alerts": []}


def test_um_dragao_roubado_conta_para_quem_o_matou():
    """Os eventos dizem o nome de quem matou; o lado sai da lista de jogadores."""
    d = _jogo(lado="ORDER", minutos=14, itens=(2055,))
    d["events"]["Events"] = [
        {"EventName": "DragonKill", "KillerName": "Cristóvão#2002"},
        {"EventName": "DragonKill", "KillerName": "Outro#EUW"},
        {"EventName": "BaronKill", "KillerName": "Outro#EUW"},
    ]
    # 1-1 não é ficar atrás
    assert "dragao" not in _chaves(lc.avisos(d, MEDIDAS))
