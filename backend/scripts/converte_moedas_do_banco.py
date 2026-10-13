"""Converte para euros as despesas que entraram em moeda estrangeira.

As contas em zlótis e libras do Revolut foram importadas antes de a conversão
existir: 45 PLN ficaram gravados como 45 €. Isto vai buscar os movimentos dessas
contas, converte à taxa do BCE do próprio dia e marca a nota com o valor
original.

Sem `--apply` só mostra. Com `--apply` grava cópia da base antes.
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv                                   # noqa: E402
load_dotenv()

import openbanking as ob                                         # noqa: E402
from database import SessionLocal                                # noqa: E402
from fx_historico import para_euros                              # noqa: E402
from models import BankAccount, Expense                          # noqa: E402

APLICAR = "--apply" in sys.argv


def main() -> None:
    db = SessionLocal()
    mudancas = []
    for conta in db.query(BankAccount).filter(BankAccount.currency != "EUR").all():
        try:
            txs = ob.transacoes(conta.account_id)
        except ob.BancoIndisponivel as ex:
            print(f"conta {conta.currency}: {ex}")
            continue
        for t in txs:
            moeda = (t.get("currency") or conta.currency).upper()
            if moeda == "EUR":
                continue
            e = db.query(Expense).filter(Expense.bank_tx_id == t["external_id"]).first()
            if not e or (e.notes or "") != "do banco":
                continue                       # já convertida ou não é do banco
            novo = para_euros(e.amount, moeda, e.date or date.today())
            if novo is None or abs(novo - e.amount) < 0.01:
                continue
            mudancas.append((e, novo, moeda))

    print(f"{len(mudancas)} despesas em moeda estrangeira")
    for e, novo, moeda in mudancas[:15]:
        print(f"   {e.date} {e.amount:>8.2f} {moeda} → {novo:>8.2f} €   {e.description[:34]}")
    if len(mudancas) > 15:
        print(f"   … mais {len(mudancas) - 15}")
    total_antes = sum(e.amount for e, _, _ in mudancas)
    total_depois = sum(n for _, n, _ in mudancas)
    print(f"\nsoma: {total_antes:.2f} → {total_depois:.2f} € "
          f"({total_antes - total_depois:+.2f} € a menos de gasto inventado)")

    if not APLICAR:
        print("\n(simulação — correr com --apply para gravar)")
        return

    copia = f"cristopher.db.bak-moedas-{datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2("cristopher.db", copia)
    print(f"\ncópia de segurança: {copia}")
    for e, novo, moeda in mudancas:
        e.notes = f"do banco · {abs(e.amount):.2f} {moeda}"
        e.amount = novo
    db.commit()
    print(f"convertidas {len(mudancas)}")


if __name__ == "__main__":
    main()
