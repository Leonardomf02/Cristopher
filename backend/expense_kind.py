"""Que tipo de movimento é cada linha de `expenses`.

Nem tudo o que passa na conta é dinheiro gasto. A tabela misturava três coisas
muito diferentes e somava-as todas como "gastos":

- **gasto** — consumo a sério.
- **transferência** — dinheiro dele a mudar de sítio (para a corretora e de
  volta, e da conta da Caixa para o Revolut).
  132 movimentos, e em Julho **−1.025€**, porque tirou ~1.040€ dos brokers: era
  por isso que Julho aparecia com 332€ gastos. A categoria `invest` somava −341€,
  ou seja, a app achava que investir lhe dava dinheiro.
- **entrada** — reembolsos, vendas na Vinted, dinheiro de amigos.
- **estorno** — a compra que voltou atrás. Aparece duas vezes na conta (a débito e
  a crédito) e o par anula-se: contar as duas pernas inflacionava a categoria e
  fazia disparar o aviso de "dia caro".

Só o `gasto` conta para os totais, para os tectos do orçamento e para a régua das
anomalias. O resto continua guardado — apenas não se chama gasto.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Iterable, Optional

GASTO = "spend"
ENTRADA = "income"
TRANSFERENCIA = "transfer"
ESTORNO = "reversal"

TIPOS = (GASTO, ENTRADA, TRANSFERENCIA, ESTORNO)
# O que não é consumo: fica de fora dos totais de gastos.
NAO_E_GASTO = (TRANSFERENCIA, ESTORNO)

NOMES = {
    GASTO: "gasto",
    ENTRADA: "entrada",
    TRANSFERENCIA: "transferência",
    ESTORNO: "reembolsado",
}

# Contas dele noutras casas: corretoras e carteiras. Mandar 300€ para a Trading
# 212 não é gastar 300€ — é o mesmo dinheiro noutro sítio.
#
# O Revolut NÃO entra aqui de propósito: é o banco dele, e o nome aparece em
# comissões e em levantamentos ao balcão, que são gastos a sério. As passagens de
# dinheiro entre contas próprias do Revolut já nem chegam à base — a
# sincronização deita-as fora com `e_transferencia_propria`.
CONTAS_PROPRIAS = re.compile(
    r"trading\s*212|trading212|\bt212\b|finst|stichting|degiro|xtb|interactive\s*brokers|"
    r"coinbase|binance|kraken|etoro|scalable|traderepublic|trade\s*republic",
    re.I,
)

# Carregar a conta a partir de outra conta dele. Levantar dinheiro NÃO entra
# aqui: ele não regista o que faz com o dinheiro vivo, por isso tratar o
# levantamento como transferência fazia o consumo desaparecer da app.
MOVIMENTO_PROPRIO = re.compile(
    r"^(top-?up|carregamento)\b|\b(to|from)\s+(my|minha|a minha)\b",
    re.I,
)

# A Caixa Geral escreve as descrições cortadas a vinte e um caracteres: passar
# 100€ da conta da Caixa para o Revolut aparece como "CAR WAL CRT DEB REVOL" —
# carregamento de wallet por cartão de débito, com o destino cortado às cinco
# primeiras letras. São 100€ a mudar de conta, não 100€ gastos, e eram 15
# movimentos (2.235€) a contar como consumo, categorizados como "viagens".
#
# É por isto que o Revolut continua fora de `CONTAS_PROPRIAS` e entra aqui: o
# nome sozinho não prova nada (aparece em comissões e levantamentos ao balcão,
# que são gastos a sério) — quem prova é o carregamento.
CARREGAR_CARTEIRA = re.compile(
    r"^(car|carr|carreg\w*)\s+(wal\w*|carteira)\b.*\b"
    r"(revol\w*|wise|paypal|trading|t212|finst|degiro|xtb|etoro)",
    re.I,
)


def classifica(descricao: str, categoria: str = "", valor: float = 0.0,
               notas: str = "") -> str:
    """O tipo de um movimento, olhando só para ele próprio.

    Só a descrição conta. As notas são escritas pela app ("Importado do Revolut
    PDF", "do banco") e olhar para elas classificava metade do histórico como
    transferência por causa do nome do banco lá dentro.

    Os estornos não se detectam assim (é preciso ver o par) — saem de
    `marca_estornos`."""
    texto = (descricao or "").strip()
    if (CONTAS_PROPRIAS.search(texto) or MOVIMENTO_PROPRIO.search(texto)
            or CARREGAR_CARTEIRA.search(texto)):
        return TRANSFERENCIA
    # A categoria `invest` só existe para este tipo de movimento.
    if (categoria or "").lower() == "invest":
        return TRANSFERENCIA
    return ENTRADA if valor < 0 else GASTO


# ── Estornos ─────────────────────────────────────────────────────
# Uma compra revertida aparece a débito e a crédito, com dias de intervalo. Sem
# isto, 345,85€ na Vinted contavam como gasto e o crédito contava como entrada,
# e o dia entrava nos avisos de "dia caro" por uma compra que nunca existiu.

JANELA_ESTORNO_DIAS = 21


# Palavras que não identificam ninguém: "Transfer to X" e "Transfer from Y"
# começavam ambas por "transfer" e emparelhavam pessoas diferentes — 10€ para o
# Nuno anulavam 10€ que vieram do Rodrigo.
_GENERICAS = {
    "transfer", "transferencia", "transferência", "payment", "pagamento", "para",
    "from", "para", "the", "cash", "refund", "reembolso", "estorno", "devolucao",
    "devolução", "withdrawal", "levantamento", "top", "topup", "trf", "mbway",
}


def _raiz(descricao: str) -> str:
    """Quem está do outro lado: 'Vinted' ≡ 'Mgp*vinted', 'Transfer to RODRIGO' → 'rodrigo'.

    Pela mesma identidade de loja das regras de categoria (`bank_categories.chave`):
    a Caixa escreve a compra como `GOPRO.C` e a devolução como `CR VCHER CRT DB
    GOPRO`, e olhando só para a primeira palavra eram "goproc" e "vcher". No MB
    Way a loja é o telefone — sem ele, 30€ para o ginásio anulavam 30€ de um amigo."""
    from bank_categories import chave
    k = chave(descricao or "")
    if k.startswith("mbway "):
        return k
    for parte in k.split():
        if len(parte) >= 3 and parte not in _GENERICAS:
            return parte
    return ""


def pares_de_estorno(despesas: Iterable) -> list[tuple]:
    """(compra, devolução) para cada par que se anula ao cêntimo.

    Exige o mesmo sítio, valores simétricos e a devolução depois da compra — dois
    movimentos iguais em sentidos opostos noutro sítio qualquer não são um par."""
    saidas = sorted([e for e in despesas if (e.amount or 0) > 0], key=lambda e: (e.date, e.id))
    # um reembolso já ligado a uma conta (o MB Way do amigo pelo gás) não é estorno
    entradas = sorted([e for e in despesas if (e.amount or 0) < 0 and not getattr(e, "reimburses_id", None)],
                      key=lambda e: (e.date, e.id))
    usadas: set[int] = set()
    pares = []
    for compra in saidas:
        raiz = _raiz(compra.description)
        if not raiz:
            continue
        candidatas = [
            d for d in entradas
            if d.id not in usadas
            and abs((d.amount or 0) + compra.amount) < 0.01
            and compra.date <= d.date <= compra.date + timedelta(days=JANELA_ESTORNO_DIAS)
            and _raiz(d.description) == raiz
        ]
        if not candidatas:
            continue
        devolucao = min(candidatas, key=lambda d: (d.date, d.id))
        usadas.add(devolucao.id)
        pares.append((compra, devolucao))
    return pares


def marca_estornos(despesas: Iterable) -> int:
    """Põe as duas pernas de cada par a `reversal`. Devolve quantas linhas mexeu."""
    mexidas = 0
    for compra, devolucao in pares_de_estorno(despesas):
        for linha in (compra, devolucao):
            if linha.kind != ESTORNO:
                linha.kind = ESTORNO
                mexidas += 1
    return mexidas


def resume(despesas: Iterable) -> dict:
    """Totais por tipo — o que a app deve mostrar em vez de um número só."""
    fora = {t: 0.0 for t in TIPOS}
    quantos = {t: 0 for t in TIPOS}
    estornado = 0.0
    for e in despesas:
        tipo = e.kind if e.kind in TIPOS else GASTO
        fora[tipo] += e.amount or 0
        quantos[tipo] += 1
        if tipo == ESTORNO and (e.amount or 0) > 0:
            estornado += e.amount          # só a perna da compra, senão contava a dobrar
    return {
        "spent": round(fora[GASTO], 2),
        "income": round(-fora[ENTRADA], 2),          # entradas com sinal positivo
        "transfers": round(fora[TRANSFERENCIA], 2),
        "reversed": round(estornado, 2),
        "counts": {NOMES[t]: quantos[t] for t in TIPOS},
        "net": round(fora[GASTO] + fora[ENTRADA], 2),
    }
