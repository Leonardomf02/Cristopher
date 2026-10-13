"""Em que dia entrou o salário de cada mês.

O mês civil não é o mês dele: o dinheiro chega a 24, 26, 27 ou 28 e é a partir
daí que se gasta. O dia lê-se da conta — a maior entrada do mês que chegue a 80%
do Rendimento declarado (a transferência da universidade de 598€ em Agosto não é
o salário) — e ele pode corrigi-lo à mão. Os meses sem movimentos do banco
(importados de PDF, ou anteriores à ligação) levam o dia do costume.
"""
from datetime import date
from statistics import median
from typing import Callable, Iterable, Optional

DIA_POR_OMISSAO = 25
FRACAO_DO_SALARIO = 0.8


def _mes(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _dia_no_mes(ano: int, mes: int, dia: int) -> date:
    import calendar
    return date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1]))


def dias_de_salario(
    entradas: Iterable,
    declarado: Callable[[int, int], float],
    correcoes: dict[str, tuple[date, Optional[float]]],
    primeiro_mes: Optional[date],
    hoje: date,
) -> dict:
    """`entradas` são despesas `income` (valor negativo). Devolve os dias por
    ordem, cada um com a origem: `banco`, `manual` ou `estimado`."""
    detectados: dict[str, dict] = {}
    for e in entradas:
        valor = -e.amount
        if valor < FRACAO_DO_SALARIO * declarado(e.date.month, e.date.year):
            continue
        k = _mes(e.date)
        atual = detectados.get(k)
        if atual is None or valor > atual["amount"]:
            detectados[k] = {"date": e.date, "amount": round(valor, 2),
                             "description": e.description, "source": "banco"}

    tipico = round(median(d["date"].day for d in detectados.values())) if detectados else DIA_POR_OMISSAO

    dias = dict(detectados)
    # O valor só vem quando ele marcou um movimento como o salário; corrigir só
    # o dia mantém o valor que a conta mostrou.
    for k, (d, valor) in correcoes.items():
        base = dias.get(k, {"amount": None, "description": None})
        dias[k] = {**base, "date": d, "source": "manual",
                   "amount": round(valor, 2) if valor else base["amount"]}

    # Só se estimam meses que já acabaram: no mês corrente o salário pode estar
    # simplesmente atrasado, e um dia inventado abria um ciclo antes do tempo.
    if primeiro_mes:
        ano, mes = primeiro_mes.year, primeiro_mes.month
        while (ano, mes) < (hoje.year, hoje.month):
            k = f"{ano:04d}-{mes:02d}"
            if k not in dias:
                dias[k] = {"date": _dia_no_mes(ano, mes, tipico), "amount": None,
                           "description": None, "source": "estimado"}
            ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)

    lista = sorted(({"month": k, **v} for k, v in dias.items()), key=lambda d: d["date"])
    return {"paydays": lista, "typical_day": tipico}
