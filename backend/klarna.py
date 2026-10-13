"""Compras pagas com Klarna: o que ainda falta pagar, mês a mês.

O banco não traz a compra, traz as prestações: 106,63€ no dia, 106,63€ um mês
depois e 106,64€ no seguinte, cada uma como um movimento à parte. O movimento
que ele marca é uma prestação, por isso o valor dele É a prestação — não se
divide por nada.

As outras prestações procuram-se na conta: mesma loja, mesmo valor. A Klarna
cobra quando quer (a terceira da youget.pt veio a 12 e não a 18) e ele pode
pagar adiantado, por isso a data só serve para o que ainda não apareceu: o que
já foi cobrado conta como pago no dia em que o banco o mostra, não no dia em que
devia ter vencido.
"""
import calendar
from datetime import date, timedelta

import expense_kind as ek
from bank_categories import MINIMO_PREFIXO, chave

# Dividir um total por três não dá sempre certo: a última prestação leva os
# cêntimos que sobram.
TOLERANCIA = 0.05
FOLGA = timedelta(days=10)


def mais_meses(d: date, n: int) -> date:
    """O mesmo dia n meses à frente (ou atrás); 31 de Janeiro + 1 mês é o fim de
    Fevereiro."""
    m = d.month - 1 + n
    ano, mes = d.year + m // 12, m % 12 + 1
    return date(ano, mes, min(d.day, calendar.monthrange(ano, mes)[1]))


def mesma_loja(marcada: str, outra: str) -> bool:
    """`youget.pt` na compra e `you Get` nas prestações são a mesma loja. Uma
    cobrança que só diz "Klarna" não tem loja e serve a qualquer plano — mas não
    ao contrário: um plano sem loja não apanha a compra de mesmo valor ao lado."""
    ka, kb = (chave(t or "").replace(" ", "") for t in (marcada, outra))
    if not ka or not kb:
        return False
    if ka == kb or "klarna" in kb:
        return True
    curta, comprida = sorted((ka, kb), key=len)
    return len(curta) >= MINIMO_PREFIXO and comprida.startswith(curta)


def planos(marcadas, movimentos, hoje: date) -> list[dict]:
    """Um plano por movimento marcado: as prestações que o banco já mostra e as
    que faltam.

    `marcadas` são pares (despesa, vezes); `movimentos` é onde se procuram as
    outras prestações. Procura-se para os dois lados: se ele marcar a segunda, a
    primeira é a que veio antes. Cada movimento só serve um plano."""
    donos = {e.id for e, _ in marcadas}
    livres = [m for m in movimentos
              if m.id not in donos and m.kind == ek.GASTO and (m.amount or 0) > 0]
    usados: set = set()
    fora = []
    for e, vezes in sorted(marcadas, key=lambda p: (p[0].date, p[0].id)):
        if (vezes or 0) < 2 or e.kind != ek.GASTO or (e.amount or 0) <= 0:
            continue
        desde = mais_meses(e.date, -(vezes - 1)) - FOLGA
        ate = mais_meses(e.date, vezes - 1) + FOLGA
        irmas = [m for m in livres
                 if m.id not in usados and desde <= m.date <= ate and m.date != e.date
                 and abs(m.amount - e.amount) <= TOLERANCIA
                 and mesma_loja(e.description, m.description)]
        irmas = sorted(irmas, key=lambda m: abs((m.date - e.date).days))[:vezes - 1]
        usados.update(m.id for m in irmas)
        grupo = sorted([e, *irmas], key=lambda m: (m.date, m.id))

        vencem = [mais_meses(grupo[0].date, k) for k in range(1, vezes)]
        # Pago é o que o banco já mostra; o que passou da data sem aparecer (a
        # loja veio com outro nome) também se dá por pago.
        pagas = max(len(grupo) - 1, sum(1 for v in vencem if v < hoje))
        fora.append({
            "expense_id": e.id, "description": e.description,
            "amount": round(e.amount, 2), "of": vezes, "paid": pagas + 1,
            "payments": [{"expense_id": m.id, "date": m.date.isoformat(), "n": i + 1}
                         for i, m in enumerate(grupo)],
            "pending": [{"due": v.isoformat(), "n": i + 2}
                        for i, v in enumerate(vencem) if i >= pagas],
        })
    return fora


def por_pagar(planos_: list[dict]) -> dict:
    """O que falta, agrupado pelo mês em que vence."""
    meses: dict[str, dict] = {}
    for p in planos_:
        for f in p["pending"]:
            mes = meses.setdefault(f["due"][:7], {"month": f["due"][:7], "total": 0.0, "items": []})
            mes["total"] += p["amount"]
            mes["items"].append({
                "expense_id": p["expense_id"], "description": p["description"],
                "amount": p["amount"], "due": f["due"], "n": f["n"], "of": p["of"],
            })
    linhas = [meses[k] for k in sorted(meses)]
    for m in linhas:
        m["total"] = round(m["total"], 2)
        m["items"].sort(key=lambda i: i["due"])
    return {"total": round(sum(m["total"] for m in linhas), 2), "months": linhas, "plans": planos_}
