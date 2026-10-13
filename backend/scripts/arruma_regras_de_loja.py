"""Recalcula a identidade das lojas nas regras aprendidas.

A Caixa prefixa cada linha com o tipo de operação (`COMPRAS C.DEB …`) e corta o
resultado aos 21 caracteres. Enquanto o prefixo contou para a identidade da
loja, a mesma loja tinha duas regras — `compras c deb inter f` e
`inter figueira da foz` — e uma correcção à mão numa delas não chegava à outra.

Isto passa as regras que já existem à régua nova, junta as que ficaram iguais e
volta a aplicar o resultado às despesas do banco.

    python scripts/arruma_regras_de_loja.py             # só mostra
    python scripts/arruma_regras_de_loja.py --aplicar   # grava
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bank_categories import _regra, categoria_com_memoria, chave         # noqa: E402
from database import SessionLocal                                        # noqa: E402
from models import Expense, MerchantRule                                 # noqa: E402

import expense_kind as ek                                                # noqa: E402


def _quando(r: MerchantRule) -> datetime:
    return r.updated_at or r.created_at or datetime.min


def main() -> int:
    aplicar = "--aplicar" in sys.argv
    db = SessionLocal()
    try:
        regras = db.query(MerchantRule).all()
        por_chave: dict[str, MerchantRule] = {}
        fora: list[MerchantRule] = []

        for r in sorted(regras, key=lambda r: (r.source != "manual", -_quando(r).timestamp())):
            nova = chave(r.label or r.key)
            if not nova:
                fora.append(r)                       # `COMPRAS C.DEB NLOVX75`: só o prefixo e um código
                continue
            anterior = por_chave.get(nova)
            if anterior is None:
                r.key = nova
                por_chave[nova] = r
                continue
            # Já há regra para esta loja. Ganha a correcção dele, e entre duas
            # correcções ganha a mais recente — a ordenação já as pôs à frente.
            fora.append(r)
            if anterior.source != "manual" and r.source == "manual":
                anterior.category, anterior.source = r.category, "manual"

        print(f"── {len(fora)} regras a sair (repetidas ou sem loja)")
        for r in fora:
            print(f"   {r.key:26s} {r.category:14s} {r.source}")
        for r in fora:
            db.delete(r)
        db.flush()

        # Duas correcções à mão da mesma loja, uma prefixo da outra: fica a mais
        # recente. Era o caso do Intermarché — `inter f` dizia contas e
        # `inter figueira da foz` dizia transportes.
        manuais = sorted([r for r in por_chave.values() if r.source == "manual"],
                         key=lambda r: -_quando(r).timestamp())
        mortas = []
        for i, r in enumerate(manuais):
            if any(r.key.startswith(m.key) or m.key.startswith(r.key)
                   for m in manuais[:i] if m not in mortas and m.category != r.category):
                mortas.append(r)
        for r in mortas:
            print(f"── correcção antiga substituída: {r.key} ({r.category})")
            db.delete(r)
        db.flush()

        # Só se mexe no que está por classificar e no que uma correcção **dele**
        # manda mudar. As despesas de viagem que ele arrumou à mão ficam quietas:
        # a lista fixa de lojas acha que "Transfer to RAFAEL GASPAR" é o Spar.
        mudadas = []
        for e in db.query(Expense).filter(Expense.bank_tx_id.isnot(None)).all():
            if e.kind in ek.NAO_E_GASTO:
                continue
            regra = _regra(e.description, db)
            manual = regra.category if regra and regra.source == "manual" else None
            nova = manual or (categoria_com_memoria(e.description, db)
                              if e.category == "other" else e.category)
            if nova != "other" and nova != e.category:
                mudadas.append((e, e.category, nova))
                e.category = nova

        print(f"\n── {len(mudadas)} despesas mudam de categoria")
        for e, antes, depois in mudadas[:30]:
            print(f"   {e.date}  {(e.description or '')[:30]:30s} {e.amount:8.2f}€  {antes} → {depois}")
        if len(mudadas) > 30:
            print(f"   … mais {len(mudadas) - 30}")

        if not aplicar:
            db.rollback()
            print("\nNada foi gravado — usa --aplicar.")
            return 0
        db.commit()
        print("\ngravado.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
