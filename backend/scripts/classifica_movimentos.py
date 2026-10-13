"""Marca cada despesa como gasto, entrada, transferência ou estorno.

Corre uma vez sobre o histórico. Daí para a frente é a sincronização do banco e a
criação manual que põem o tipo.

    python scripts/classifica_movimentos.py             # só mostra
    python scripts/classifica_movimentos.py --aplicar    # grava
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import expense_kind as ek
from database import SessionLocal
from models import Expense


def main() -> int:
    aplicar = "--aplicar" in sys.argv
    db = SessionLocal()
    try:
        despesas = db.query(Expense).order_by(Expense.date, Expense.id).all()
        antes = {e.id: e.kind for e in despesas}

        for e in despesas:
            if e.reimburses_id:
                continue          # é a parte de um amigo numa conta: fica gasto negativo
            e.kind = ek.classifica(e.description or "", e.category or "", e.amount or 0, e.notes or "")
        # Os estornos só se vêem aos pares, por isso vêm depois.
        ek.marca_estornos(despesas)

        mudadas = [e for e in despesas if antes.get(e.id) != e.kind]
        por_tipo = defaultdict(list)
        for e in mudadas:
            por_tipo[e.kind].append(e)

        for tipo in (ek.TRANSFERENCIA, ek.ESTORNO, ek.ENTRADA, ek.GASTO):
            linhas = por_tipo.get(tipo, [])
            if not linhas:
                continue
            print(f"\n── {ek.NOMES[tipo]} ({len(linhas)})")
            for e in linhas[:14]:
                print(f"   {e.date}  {(e.description or '')[:34]:34s} {e.amount:9.2f}€  {e.category}")
            if len(linhas) > 14:
                print(f"   … mais {len(linhas) - 14}")

        print("\n── efeito nos totais por mês")
        meses = defaultdict(list)
        for e in despesas:
            meses[e.date.strftime("%Y-%m")].append(e)
        print(f"{'mês':9s} {'antes':>10s} {'gastos':>10s} {'entradas':>10s} {'transfer.':>10s} {'estornos':>9s}")
        for m in sorted(meses):
            r = ek.resume(meses[m])
            bruto = sum(e.amount or 0 for e in meses[m])
            print(f"{m:9s} {bruto:10.2f} {r['spent']:10.2f} {r['income']:10.2f} "
                  f"{r['transfers']:10.2f} {r['reversed']:9.2f}")

        if not aplicar:
            db.rollback()
            print(f"\n{len(mudadas)} linhas mudariam de tipo. Nada foi gravado — usa --aplicar.")
            return 0

        db.commit()
        print(f"\n{len(mudadas)} linhas classificadas.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
