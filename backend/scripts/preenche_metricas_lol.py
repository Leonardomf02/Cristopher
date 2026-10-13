"""Preenche CS, ouro, dano e visão nos jogos de LoL que já estão na base.

A Riot manda estes números em cada partida e a app deitava-os fora — ficaram
488 jogos só com vitória/derrota e K/D/A. O histórico ainda está lá do lado
deles, por isso dá para ir buscar tudo de uma vez.

Corre à mão (é uma vez na vida):

    cd backend && source venv/bin/activate
    python scripts/preenche_metricas_lol.py            # experimenta 10 jogos
    python scripts/preenche_metricas_lol.py --todos    # a sério

A chave da Riot é a mesma que a app usa. Como as chaves de developer duram 24h
e o limite é de 100 pedidos por 2 minutos, o script vai devagar de propósito e
pode ser interrompido e retomado: só pede os jogos que ainda não têm métricas.
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

from database import SessionLocal              # noqa: E402
from models import LolGame                     # noqa: E402
from riot_api import (                         # noqa: E402
    RiotAPIError, get_match_detail, get_puuid, parse_match,
)

# 100 pedidos por 2 minutos na chave de developer. 1,3s entre pedidos deixa
# folga para o resto da app (o trabalho `jogos_lol` corre de 20 em 20 min).
PAUSA = 1.3
CAMPOS = ("cs", "cs_jungle", "gold", "damage", "damage_taken", "vision", "team_kills")


def por_preencher(db, limite: int | None):
    q = (
        db.query(LolGame)
        .filter(LolGame.match_id.isnot(None), LolGame.cs.is_(None))
        .order_by(LolGame.date.desc())
    )
    return q.limit(limite).all() if limite else q.all()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--todos", action="store_true", help="sem isto só faz 10 jogos")
    ap.add_argument("--chave", default="", help="chave da Riot (senão vem do .env/app)")
    args = ap.parse_args()

    api_key = args.chave or os.getenv("RIOT_API_KEY", "")
    if not api_key:
        try:                                    # a app guarda-a em memória
            from routers.lol import _riot_config
            api_key = _riot_config.get("api_key", "")
        except Exception:
            pass
    if not api_key:
        print("Sem chave da Riot. Põe RIOT_API_KEY no .env ou usa --chave.")
        return 1

    db = SessionLocal()
    try:
        jogos = por_preencher(db, None if args.todos else 10)
        total_falta = db.query(LolGame).filter(
            LolGame.match_id.isnot(None), LolGame.cs.is_(None)).count()
        if not jogos:
            print("Nada por preencher — todos os jogos já têm métricas.")
            return 0
        print(f"{total_falta} jogos sem métricas; vou tratar de {len(jogos)}.")
        if not args.todos:
            print("(ensaio: usa --todos para fazer o resto)")

        nome = os.getenv("RIOT_GAME_NAME", "")
        tag = os.getenv("RIOT_TAG_LINE", "")
        if not nome:
            from routers.lol import _riot_config
            nome = _riot_config.get("game_name", "Cristóvão")
            tag = _riot_config.get("tag_line", "2002")
        puuid = await get_puuid(nome, tag, api_key)

        feitos = falhados = 0
        for i, jogo in enumerate(jogos, 1):
            try:
                dados = parse_match(await get_match_detail(jogo.match_id, api_key), puuid)
            except RiotAPIError as e:
                # 404 = partida já fora do histórico da Riot; não vale a pena
                # tentar outra vez, mas também não é um erro nosso.
                print(f"  [{i}/{len(jogos)}] {jogo.match_id}: {e.message[:60]}")
                falhados += 1
                if e.status_code == 429:
                    print("  rate limit — espero 130s")
                    await asyncio.sleep(130)
                await asyncio.sleep(PAUSA)
                continue
            if not dados:
                falhados += 1
                await asyncio.sleep(PAUSA)
                continue
            for campo in CAMPOS:
                setattr(jogo, campo, dados.get(campo))
            feitos += 1
            if feitos % 25 == 0:
                db.commit()
                print(f"  [{i}/{len(jogos)}] {feitos} preenchidos…")
            await asyncio.sleep(PAUSA)

        db.commit()
        print(f"\n{feitos} jogos preenchidos, {falhados} sem dados.")
        restam = db.query(LolGame).filter(
            LolGame.match_id.isnot(None), LolGame.cs.is_(None)).count()
        print(f"Ficam {restam} por preencher.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
