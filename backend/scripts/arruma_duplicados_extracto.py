"""Apaga despesas repetidas entre o extracto em PDF e o banco ligado.

A mesma compra entrou duas vezes: uma pelo Revolut em PDF e outra pela API do
banco, com um ou dois dias de diferença (o extracto usa a data do lançamento, a
API a do processamento). A sincronização só reconhecia gémeas no MESMO dia, por
isso deixou passar as outras — e o total do mês passou a contar a dobrar.

Fica a linha do banco (tem id do movimento, hora e cidade) e sai a do PDF.

    python scripts/arruma_duplicados_extracto.py            # só mostra
    python scripts/arruma_duplicados_extracto.py --aplicar   # apaga
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal
from models import Expense
from routers.banking import JANELA_GEMEO_DIAS, _parecidas


def pares(db):
    """(linha do banco, linha do extracto) para cada duplicado encontrado."""
    do_banco = (
        db.query(Expense).filter(Expense.bank_tx_id.isnot(None))
        .order_by(Expense.date, Expense.id).all()
    )
    do_extracto = [
        e for e in db.query(Expense).filter(Expense.bank_tx_id.is_(None)).all()
    ]
    usados: set[int] = set()
    encontrados = []
    for b in do_banco:
        candidatos = [
            e for e in do_extracto
            if e.id not in usados
            and e.amount == b.amount
            and abs((e.date - b.date).days) <= JANELA_GEMEO_DIAS
            and (e.date == b.date or _parecidas(e.description or "", b.description or ""))
        ]
        if not candidatos:
            continue
        gemeo = min(candidatos, key=lambda e: (abs((e.date - b.date).days), e.id))
        usados.add(gemeo.id)
        encontrados.append((b, gemeo))
    return encontrados


def main() -> int:
    aplicar = "--aplicar" in sys.argv
    db = SessionLocal()
    try:
        encontrados = pares(db)
        if not encontrados:
            print("Sem duplicados.")
            return 0

        total = 0.0
        print(f"{len(encontrados)} duplicados:\n")
        for b, e in encontrados:
            dias = (e.date - b.date).days
            total += e.amount
            print(f"  {b.date} {b.description[:24]:24s} {b.amount:9.2f}€  (banco, fica)")
            print(f"  {e.date} {e.description[:24]:24s} {e.amount:9.2f}€  "
                  f"({(e.notes or 'à mão')[:22]}, sai · {dias:+d}d)\n")

        print(f"Total a corrigir: {total:.2f}€")
        if not aplicar:
            print("\nNada foi apagado. Corre outra vez com --aplicar.")
            return 0

        # A linha do banco fica, mas não pode perder o que só a do extracto tinha:
        # o valor na moeda original, a cidade, o recibo, a viagem.
        salvos = 0
        for b, e in encontrados:
            for campo in ("original_amount", "original_currency", "merchant_city",
                          "merchant_country", "receipt_image", "trip_id"):
                if getattr(b, campo, None) in (None, "") and getattr(e, campo, None) not in (None, ""):
                    setattr(b, campo, getattr(e, campo))
                    salvos += 1
            db.delete(e)
        db.commit()
        print(f"\n{len(encontrados)} linhas apagadas · {salvos} campos recuperados para a linha do banco.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
