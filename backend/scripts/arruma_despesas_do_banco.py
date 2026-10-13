"""Arruma as despesas que já vieram do banco antes das regras novas.

O que faz (só a linhas com `notes = 'do banco'`, nunca ao que foi metido à mão):
  • apaga o que não é consumo — carregamentos e envios entre contas dele
  • apaga movimentos de valor zero (autorizações que nunca chegaram a passar)
  • limpa o nome da loja (`Mgp*vinted` → `vinted`) e volta a categorizar

Sem `--apply` só mostra o que faria. Com `--apply` grava cópia da base antes.
"""
from __future__ import annotations

import os
import shutil
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bank_categories import categoria, e_transferencia_propria, limpa   # noqa: E402
from database import SessionLocal                                        # noqa: E402
from models import BankAccount, Expense                                  # noqa: E402

APLICAR = "--apply" in sys.argv


def main() -> None:
    db = SessionLocal()
    titulares = {c.name for c in db.query(BankAccount).all() if c.name}
    linhas = db.query(Expense).filter(Expense.bank_tx_id.isnot(None),
                                      Expense.notes == "do banco").all()
    print(f"{len(linhas)} despesas vindas do banco · titulares: {', '.join(titulares) or '—'}")

    apagar, mudar = [], []
    for e in linhas:
        if not e.amount or any(e_transferencia_propria(e.description, t) for t in titulares):
            apagar.append(e)
            continue
        nova_cat = categoria(e.description)
        novo_nome = limpa(e.description)[:120]
        if nova_cat != e.category or novo_nome != e.description:
            mudar.append((e, novo_nome, nova_cat))

    print(f"\na apagar: {len(apagar)}")
    for e in apagar[:8]:
        print(f"   {e.date} {e.amount:>9.2f}€  {e.description[:52]}")
    if len(apagar) > 8:
        print(f"   … mais {len(apagar) - 8}")

    print(f"\na recategorizar: {len(mudar)}")
    for e, nome, cat in mudar[:12]:
        print(f"   {e.description[:34]:<35} → {nome[:22]:<23} {e.category} → {cat}")
    if len(mudar) > 12:
        print(f"   … mais {len(mudar) - 12}")

    print("\ncategorias depois:",
          dict(Counter([c for _, _, c in mudar] +
                       [e.category for e in linhas if e not in apagar
                        and e not in [m[0] for m in mudar]]).most_common()))

    if not APLICAR:
        print("\n(simulação — correr com --apply para gravar)")
        return

    copia = f"cristopher.db.bak-banco-{datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2("cristopher.db", copia)
    print(f"\ncópia de segurança: {copia}")
    for e in apagar:
        db.delete(e)
    for e, nome, cat in mudar:
        e.description, e.category = nome, cat
    db.commit()
    print(f"apagadas {len(apagar)} · arrumadas {len(mudar)}")


if __name__ == "__main__":
    main()
