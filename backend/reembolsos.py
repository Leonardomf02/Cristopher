"""O que os amigos devolvem de uma conta que ele pagou.

O caso é o dele: o gás da casa, 35,60€ a 8 de Setembro (`CHAMATENCAO`), e no
mesmo dia o Rodrigo e o Gabriel mandaram 11,87€ cada — 35,60 a dividir por três.
Sem ligação nenhuma, a app contava 35,60€ de gasto e 23,74€ de "dinheiro
recebido", como se fosse uma entrada a sério.

Ligar um reembolso faz dele um gasto **negativo** da categoria da conta. Não há
uma única soma de `spend` na app que precise de saber disto: o gás passa a valer
11,86€ nos totais, no orçamento, nos envelopes e na média por dia, e os 23,74€
saem das entradas.

As sugestões procuram entradas que sejam uma fracção da conta (metade, um terço,
… um sexto, ao cêntimo) nos dias a seguir a ela. Com a conta marcada como
dividida por N, a parte é conhecida e a janela alarga — os amigos nem sempre
pagam na hora. Nada se liga sem ele confirmar.
"""
from datetime import date, timedelta
from typing import Iterable, Optional

DIVISOES = range(2, 7)
TOLERANCIA = 0.02            # o arredondamento ao cêntimo de quem divide
TOLERANCIA_DIVIDIDA = 0.05
JANELA = 14                  # dias depois da conta
JANELA_DIVIDIDA = 45
CONTA_MINIMA = 8.0           # um café de 3€ a meias não vale uma pergunta
ANTES = 1                    # o amigo que manda na véspera de ele pagar


def _dividida(conta) -> bool:
    return bool(conta.split_people or getattr(conta, "my_share", None) is not None)


def reparte(valor: float, faltas: list[tuple[int, float]]) -> dict[int, float]:
    """Reparte uma entrada por várias contas, na proporção do que falta a cada uma:
    o Rafael manda 75€ pelos levantamentos de 70€ e 30€ → 52,50€ e 22,50€.
    Ao cêntimo, e a última conta leva o que sobra do arredondamento."""
    total = sum(f for _, f in faltas)
    if total <= 0:
        return {}
    saida, posto = {}, 0.0
    for i, (cid, falta) in enumerate(faltas):
        parte = round(valor - posto, 2) if i == len(faltas) - 1 else round(valor * falta / total, 2)
        saida[cid] = parte
        posto += parte
    return saida


def _divisao(valor: float, conta) -> Optional[int]:
    """Em quantas partes a conta se dividiu para dar este valor (None se nenhuma).
    Com a parte dele em valor (`my_share`), qualquer valor que caiba serve: a
    conta já está marcada como dividida, e devolve-se 0 em vez de N."""
    if getattr(conta, "my_share", None) is not None:
        return 0 if valor <= conta.amount - conta.my_share + 0.01 else None
    if conta.split_people:
        parte = conta.amount / conta.split_people
        return conta.split_people if abs(valor - parte) <= TOLERANCIA_DIVIDIDA else None
    for n in DIVISOES:
        if abs(valor - conta.amount / n) <= TOLERANCIA:
            return n
    return None


def _na_janela(entrada, conta) -> bool:
    dias = JANELA_DIVIDIDA if _dividida(conta) else JANELA
    return conta.date - timedelta(days=ANTES) <= entrada.date <= conta.date + timedelta(days=dias)


def candidatas(entrada, contas: Iterable, ja_devolvido: dict[int, float]) -> list[dict]:
    """Contas a que esta entrada pode pertencer, da mais provável para a menos.
    Serve a lista do "descontar em…" no editar: as que batem certo vêm primeiro."""
    valor = -entrada.amount
    saida = []
    for c in contas:
        # uma conta mais pequena que a entrada continua a servir: junta-se a outras
        # (os levantamentos de 70€ e 30€ para os 75€ do Rafael)
        if c.id == entrada.id:
            continue
        falta = c.amount - ja_devolvido.get(c.id, 0.0)
        n = _divisao(valor, c) if valor <= falta + 0.01 else None
        perto = abs((entrada.date - c.date).days)
        saida.append({"conta": c, "partes": n, "dias": perto})
    saida.sort(key=lambda x: (x["partes"] is None, not _dividida(x["conta"]), x["dias"], -x["conta"].amount))
    return saida


def esperado_dos_outros(conta) -> Optional[float]:
    """Quanto os outros deviam devolver, se a conta está marcada como dividida."""
    parte = getattr(conta, "my_share", None)
    if parte is not None:
        return max(0.0, conta.amount - parte)
    if conta.split_people and conta.split_people >= 2:
        return conta.amount * (conta.split_people - 1) / conta.split_people
    return None


def _combinacao(valor: float, faltas: list[tuple[object, float]]) -> Optional[list]:
    """Contas cujo que-falta soma exactamente o valor (2 a 4 delas, das mais
    próximas): o Rafael manda 75€ e aos levantamentos de 70€ e 30€ faltam 70€ e 5€."""
    from itertools import combinations
    for tamanho in range(2, min(4, len(faltas)) + 1):
        for grupo in combinations(faltas, tamanho):
            if abs(sum(f for _, f in grupo) - valor) <= TOLERANCIA_DIVIDIDA:
                return [c for c, _ in grupo]
    return None


def sugestoes(entradas: Iterable, contas: Iterable, ja_devolvido: dict[int, float],
              dispensadas: set[tuple[int, int]]) -> list[dict]:
    """Cada sugestão é um grupo: o gás com os dois MB Ways, de uma vez, ou o MB
    Way do Rafael com os dois levantamentos que ele pagou."""
    contas = [c for c in contas if c.amount >= CONTA_MINIMA]
    atribuido: dict[int, float] = {}
    grupos: dict[int, dict] = {}
    multiplas: list[dict] = []
    for e in sorted(entradas, key=lambda x: (x.date, x.id)):
        valor = -e.amount
        opcoes = []
        for c in contas:
            if (e.id, c.id) in dispensadas or not _na_janela(e, c):
                continue
            falta = c.amount - ja_devolvido.get(c.id, 0.0) - atribuido.get(c.id, 0.0)
            if valor > falta + 0.01:
                continue
            n = _divisao(valor, c)
            if n is None:
                continue
            opcoes.append((not _dividida(c), abs((e.date - c.date).days), n, c))
        if opcoes:
            *_, conta = min(opcoes, key=lambda o: o[:3])
            atribuido[conta.id] = atribuido.get(conta.id, 0.0) + valor
            grupo = grupos.setdefault(conta.id, {"expenses": [conta], "incomes": []})
            grupo["incomes"].append(e)
            continue
        # Uma conta só não chega: procura-se entre as que ele marcou como divididas.
        faltas = []
        for c in sorted(contas, key=lambda c: abs((e.date - c.date).days)):
            esperado = esperado_dos_outros(c)
            if esperado is None or (e.id, c.id) in dispensadas or not _na_janela(e, c):
                continue
            falta = round(esperado - ja_devolvido.get(c.id, 0.0) - atribuido.get(c.id, 0.0), 2)
            if falta > 0.01:
                faltas.append((c, falta))
        juntas = _combinacao(valor, faltas[:10])
        if juntas:
            for c in juntas:
                atribuido[c.id] = atribuido.get(c.id, 0.0) + dict((x.id, f) for x, f in faltas)[c.id]
            multiplas.append({"expenses": juntas, "incomes": [e]})

    saida = []
    for g in list(grupos.values()) + multiplas:
        total = sum(c.amount for c in g["expenses"])
        recebido = sum(ja_devolvido.get(c.id, 0.0) for c in g["expenses"]) + sum(-e.amount for e in g["incomes"])
        saida.append({**g, "share_after": round(total - recebido, 2)})
    saida.sort(key=lambda g: max(e.date for e in g["incomes"]), reverse=True)
    return saida


def por_receber(contas_divididas: Iterable, devolvido: dict[int, tuple[float, int]]) -> list[dict]:
    """Contas divididas a que ainda falta dinheiro: quanto, e quantas pessoas."""
    saida = []
    for c in contas_divididas:
        total, pessoas = devolvido.get(c.id, (0.0, 0))
        parte = getattr(c, "my_share", None)
        esperado = esperado_dos_outros(c)
        if esperado is None:
            continue
        falta = round(esperado - total, 2)
        if falta <= 0.01:
            continue
        saida.append({
            "expense": c,
            "expected": round(esperado, 2),
            "received": round(total, 2),
            "missing": falta,
            # com a parte em valor não se sabe quantos faltam
            "missing_people": max(1, c.split_people - 1 - pessoas) if parte is None else None,
            "share": round(parte if parte is not None else c.amount / c.split_people, 2),
        })
    saida.sort(key=lambda x: x["expense"].date, reverse=True)
    return saida


def janela_de_procura(hoje: date) -> date:
    return hoje - timedelta(days=JANELA_DIVIDIDA + 30)
