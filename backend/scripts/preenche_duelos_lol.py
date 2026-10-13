"""Preenche a tabela dos duelos: o jogo dele contra o jungler adversário.

A Riot manda 128 campos de `challenges` por participante — e manda-os para os
dez jogadores, incluindo o jungler do outro lado. A app guardava sete campos, e
só dele. Sem o adversário não há régua nenhuma: "6,24 CS por minuto" não diz
nada, "6,24 contra os 6,84 do jungler adversário, e perdes em 59% dos jogos" diz
tudo. A Riot não publica referências por elo e as dos sites são de outra amostra
e outro patch; o jungler adversário é do mesmo elo, do mesmo patch e do mesmo
jogo.

Corre à mão (é uma vez na vida):

    cd backend && source venv/bin/activate
    python scripts/preenche_duelos_lol.py            # experimenta 10 jogos
    python scripts/preenche_duelos_lol.py --todos    # a sério (~28 min por 500)

São dois pedidos por jogo (a partida e a timeline), por isso demora o dobro do
`preenche_metricas_lol.py`. Pode ser interrompido e retomado a qualquer momento:
só pede os jogos que ainda não têm duelo. `--sem-timeline` faz metade do trabalho
em metade do tempo, e uma passagem posterior completa o que falta.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from database import SessionLocal, engine      # noqa: E402
from models import LolDuel, LolGame            # noqa: E402
from riot_api import (                         # noqa: E402
    RiotAPIError, get_match_detail, get_match_timeline, get_puuid, parse_duel,
)

# 100 pedidos por 2 minutos na chave de developer, e aqui são dois por jogo.
PAUSA = 1.3


def por_tratar(db, com_timeline: bool, limite: int | None):
    """Jogos de jungle sem duelo, mais os que ficaram sem timeline se ela agora
    for pedida — assim uma passagem `--sem-timeline` completa-se depois."""
    feitos = {d.match_id for d in db.query(LolDuel.match_id).all()}
    if com_timeline:
        feitos -= {d.match_id for d in db.query(LolDuel.match_id)
                   .filter(LolDuel.has_timeline.is_(False)).all()}
    q = (
        db.query(LolGame)
        .filter(LolGame.match_id.isnot(None), LolGame.role == "jungle")
        .order_by(LolGame.date.desc())
    )
    faltam = [g for g in q.all() if g.match_id not in feitos]
    return faltam[:limite] if limite else faltam


def grava(db, linha: dict) -> None:
    """Upsert por match_id — correr duas vezes não duplica."""
    existente = db.query(LolDuel).filter(LolDuel.match_id == linha["match_id"]).first()
    if existente:
        for campo, valor in linha.items():
            setattr(existente, campo, valor)
    else:
        db.add(LolDuel(**linha))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--todos", action="store_true", help="sem isto só faz 10 jogos")
    ap.add_argument("--sem-timeline", action="store_true",
                    help="metade do tempo, sem o ouro e o XP ao minuto")
    ap.add_argument("--chave", default="", help="chave da Riot (senão vem do .env/app)")
    args = ap.parse_args()
    com_timeline = not args.sem_timeline

    api_key = args.chave or os.getenv("RIOT_API_KEY", "")
    if not api_key:
        try:
            from routers.lol import _riot_config
            api_key = _riot_config.get("api_key", "")
        except Exception:
            pass
    if not api_key:
        print("Sem chave da Riot. Põe RIOT_API_KEY no .env ou usa --chave.")
        return 1

    # Quem cria as tabelas é o arranque do backend; o script tem de servir com
    # ele desligado.
    LolDuel.__table__.create(bind=engine, checkfirst=True)

    db = SessionLocal()
    try:
        faltam = por_tratar(db, com_timeline, None)
        jogos = faltam if args.todos else faltam[:10]
        if not jogos:
            print("Nada por tratar — todos os jogos de jungle já têm duelo.")
            return 0
        segundos = len(jogos) * PAUSA * (2 if com_timeline else 1)
        print(f"{len(faltam)} jogos sem duelo; vou tratar de {len(jogos)} "
              f"(~{segundos / 60:.0f} min).")
        if not args.todos:
            print("(ensaio: usa --todos para fazer o resto)")

        nome = os.getenv("RIOT_GAME_NAME", "")
        tag = os.getenv("RIOT_TAG_LINE", "")
        if not nome:
            from routers.lol import _riot_config
            nome = _riot_config.get("game_name", "Cristóvão")
            tag = _riot_config.get("tag_line", "2002")
        puuid = await get_puuid(nome, tag, api_key)

        feitos = falhados = sem_duelo = 0
        for i, jogo in enumerate(jogos, 1):
            try:
                partida = await get_match_detail(jogo.match_id, api_key)
                await asyncio.sleep(PAUSA)
                timeline = None
                if com_timeline:
                    try:
                        timeline = await get_match_timeline(jogo.match_id, api_key)
                    except RiotAPIError:
                        pass                    # sem timeline ainda vale a partida
                    await asyncio.sleep(PAUSA)
            except RiotAPIError as e:
                # 404 = partida já fora do histórico da Riot. Não é erro nosso.
                print(f"  [{i}/{len(jogos)}] {jogo.match_id}: {e.message[:60]}")
                falhados += 1
                if e.status_code == 429:
                    print("  rate limit — espero 130s")
                    await asyncio.sleep(130)
                continue

            linha = parse_duel(partida, puuid, timeline)
            if not linha:
                # autofill, remake, ou partida sem jungler do outro lado
                sem_duelo += 1
                continue
            grava(db, linha)
            feitos += 1
            if feitos % 25 == 0:
                db.commit()
                print(f"  [{i}/{len(jogos)}] {feitos} duelos guardados…", flush=True)

        db.commit()
        print(f"\n{feitos} duelos guardados, {sem_duelo} partidas sem duelo para medir, "
              f"{falhados} sem dados.")
        print(f"Ficam {len(por_tratar(db, com_timeline, None))} por tratar.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
