"""Limpa as sessões fantasma do tracker de apps.

Durante meses o tracker esticou a sessão viva quando o Mac acordava: se a mesma
janela continuasse à frente, a sessão voltava a crescer até ao presente. Ficaram
horas de "uso" durante a noite (ex.: 9h36 de browser das 03:11 às 12:48, com o
sono registado das 03:56 às 12:18).

O que este script faz, por ordem de confiança:
  1. corta o pedaço que cai dentro do sono registado nessa noite;
  2. para o resto, aplica o mesmo tecto que o tracker passa a usar (90min).

Nada é apagado: a duração original fica guardada em `raw_duration_seconds`, por
isso o script pode correr outra vez sem estragar nada.

Uso:
    python scripts/fix_phantom_sessions.py            # só mostra o que faria
    python scripts/fix_phantom_sessions.py --apply    # grava (faz backup antes)
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cristopher.db")
TECTO_MIN = 90          # igual ao MAX_SESSION_SECONDS do tracker
SUSPEITA_MIN = 90       # só se mexe em sessões acima disto


def _migra(con: sqlite3.Connection) -> None:
    cols = {r[1] for r in con.execute("PRAGMA table_info(app_usage_sessions)")}
    if "raw_duration_seconds" not in cols:
        con.execute("ALTER TABLE app_usage_sessions ADD COLUMN raw_duration_seconds INTEGER")
    con.commit()


def _janelas_de_sono(con: sqlite3.Connection) -> list[tuple[datetime, datetime]]:
    """(início, fim) de cada noite registada, em datas reais."""
    out = []
    for d, bed, wake in con.execute(
        "SELECT date, bedtime, wake_time FROM sleep_entries WHERE bedtime IS NOT NULL AND wake_time IS NOT NULL"
    ):
        try:
            dia = datetime.fromisoformat(str(d))
            bh, bm = str(bed)[:5].split(":")
            wh, wm = str(wake)[:5].split(":")
        except (ValueError, AttributeError):
            continue
        acordar = dia.replace(hour=int(wh), minute=int(wm))
        deitar = dia.replace(hour=int(bh), minute=int(bm))
        if deitar >= acordar:                     # deitou-se no dia anterior
            deitar -= timedelta(days=1)
        out.append((deitar, acordar))
    return sorted(out)


def _sobreposicao(a1: datetime, a2: datetime, b1: datetime, b2: datetime) -> float:
    return max(0.0, (min(a2, b2) - max(a1, b1)).total_seconds())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="grava as correcções")
    ap.add_argument("--cap-min", type=int, default=TECTO_MIN)
    args = ap.parse_args()

    if not os.path.exists(DB):
        print(f"base de dados não encontrada: {DB}", file=sys.stderr)
        return 1

    if args.apply:
        destino = f"{DB}.bak-phantom-{datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(DB, destino)
        print(f"backup: {os.path.basename(destino)}")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    _migra(con)

    sono = _janelas_de_sono(con)
    tecto = args.cap_min * 60

    linhas = con.execute(
        """SELECT id, app_name, date, start_time, end_time, duration_seconds,
                  raw_duration_seconds
           FROM app_usage_sessions
           WHERE duration_seconds > ? ORDER BY duration_seconds DESC""",
        (SUSPEITA_MIN * 60,),
    ).fetchall()

    total_antes = con.execute("SELECT SUM(duration_seconds) FROM app_usage_sessions").fetchone()[0] or 0
    cortado_sono = cortado_tecto = 0.0
    alteradas = 0

    for r in linhas:
        try:
            ini = datetime.fromisoformat(r["start_time"])
            fim = datetime.fromisoformat(r["end_time"])
        except (TypeError, ValueError):
            continue
        dur = (fim - ini).total_seconds()
        if dur <= 0:
            continue

        # A assinatura de uma sessão fantasma: só pára quando ele volta a mexer no
        # Mac, ou seja, acaba coladinha à hora a que acordou. Registos de sono são
        # às vezes escritos antes da noite acontecer, por isso não chegam sozinhos
        # para cortar — sem esta condição uma noite de trabalho até às 07h seria
        # apagada por um "deitei-me às 02:30" escrito na véspera.
        dormido = 0.0
        for s1, s2 in sono:
            sobrepoe = _sobreposicao(ini, fim, s1, s2)
            if sobrepoe > 60 and abs((fim - s2).total_seconds()) <= 45 * 60:
                dormido += sobrepoe
        nova = dur - dormido
        motivo = "sono" if dormido > 60 else ""

        if nova > tecto:
            cortado_tecto += nova - tecto
            nova = tecto
            motivo = f"{motivo}+tecto" if motivo else "tecto"
        if dormido > 60:
            cortado_sono += min(dormido, dur)

        nova = max(60.0, nova)
        if abs(nova - r["duration_seconds"]) < 60:
            continue

        alteradas += 1
        if alteradas <= 12:
            print(f"  #{r['id']:6} {r['date']} {r['app_name'][:18]:18} "
                  f"{r['duration_seconds']/60:6.0f}min → {nova/60:5.0f}min  ({motivo})")

        if args.apply:
            con.execute(
                """UPDATE app_usage_sessions
                   SET raw_duration_seconds = COALESCE(raw_duration_seconds, duration_seconds),
                       duration_seconds = ?,
                       end_time = ?
                   WHERE id = ?""",
                (int(nova), (ini + timedelta(seconds=nova)).isoformat(sep=" ", timespec="seconds"), r["id"]),
            )

    if args.apply:
        con.commit()

    total_depois = con.execute("SELECT SUM(duration_seconds) FROM app_usage_sessions").fetchone()[0] or 0
    print(f"\n  sessões acima de {SUSPEITA_MIN}min: {len(linhas)}   corrigidas: {alteradas}")
    print(f"  tempo removido por sobrepor o sono: {cortado_sono/3600:.0f}h")
    print(f"  tempo removido pelo tecto de {args.cap_min}min: {cortado_tecto/3600:.0f}h")
    print(f"  total do tracker: {total_antes/3600:.0f}h → {total_depois/3600:.0f}h"
          + ("" if args.apply else "  (simulação — usa --apply para gravar)"))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
