"""Carteira do Trading 212 pela API oficial.

As posições vinham dos extractos mensais em PDF: a última importada era de Maio e
as quantidades ficavam paradas aí — o valor da carteira, o imposto por posição, a
calibração dos sinais e o placar de acertos corriam todos em cima de uma fotografia
com três meses. A API dá as posições abertas de agora, as ordens executadas, os
dividendos pagos e o dinheiro que entrou e saiu.

Autenticação: `API_KEY:API_SECRET` em Basic (o par gera-se em Definições → API).
As chaves antigas eram uma só e iam em claro no `Authorization` — se a chave não
tiver `:`, é dessas e vai como está.

Limites: as listas históricas são 6 pedidos/minuto e as posições 1/segundo, por
isso as páginas vêm pausadas e um 429 espera pelo `x-ratelimit-reset` antes de
tentar outra vez.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from datetime import date, datetime
from typing import Any, Iterator, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("T212_API_URL", "https://live.trading212.com").rstrip("/")
FONTE = "trading212"

# Uma página de 50 é o máximo que a API deixa; a paginação segue o `nextPagePath`.
PAGINA = 50
# 6 pedidos/minuto nas listas históricas → 10s entre páginas.
PAUSA_HISTORICO = 10.0
MAX_PAGINAS = 40                 # ~2000 movimentos; chega para uma conta pessoal


class T212Indisponivel(Exception):
    """A API recusou ou não respondeu. Nunca deve parar o resto da sincronização."""


def chave() -> str:
    return os.getenv("T212_API_KEY", "").strip()


def configurado() -> bool:
    return bool(chave())


def _cabecalhos() -> dict[str, str]:
    k = chave()
    if ":" in k:
        codificado = base64.b64encode(k.encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {codificado}"}
    return {"Authorization": k}


# ── Cliente ──────────────────────────────────────────────────────

def _espera_do_limite(r: httpx.Response) -> float:
    """Segundos até o limite reabrir, segundo os cabeçalhos da própria resposta."""
    try:
        reset = float(r.headers.get("x-ratelimit-reset", "0"))
    except ValueError:
        return 5.0
    if reset <= 0:
        return 5.0
    # O cabeçalho é um instante unix; se vier em milissegundos, encolhe-se.
    if reset > 1e11:
        reset /= 1000.0
    return max(1.0, min(60.0, reset - time.time()))


def _pede(caminho: str, params: Optional[dict] = None, *, tentativas: int = 2) -> Any:
    if not configurado():
        raise T212Indisponivel("sem T212_API_KEY no .env")
    url = caminho if caminho.startswith("http") else f"{BASE_URL}{caminho}"
    for tentativa in range(tentativas + 1):
        try:
            with httpx.Client(timeout=30.0) as cliente:
                r = cliente.get(url, headers=_cabecalhos(), params=params or None)
        except httpx.HTTPError as ex:
            if tentativa >= tentativas:
                raise T212Indisponivel(f"sem resposta: {ex}")
            time.sleep(3.0)
            continue
        if r.status_code == 429:
            if tentativa >= tentativas:
                raise T212Indisponivel("limite de pedidos do Trading 212")
            time.sleep(_espera_do_limite(r))
            continue
        if r.status_code in (401, 403):
            raise T212Indisponivel("chave recusada (401/403) — confirma a chave e as permissões")
        if r.status_code != 200:
            raise T212Indisponivel(f"HTTP {r.status_code}: {r.text[:120]}")
        try:
            return r.json()
        except ValueError:
            raise T212Indisponivel("resposta não era JSON")
    raise T212Indisponivel("sem resposta")


def posicoes() -> list[dict]:
    dados = _pede("/api/v0/equity/positions")
    return dados if isinstance(dados, list) else dados.get("items", [])


def resumo_da_conta() -> dict:
    dados = _pede("/api/v0/equity/account/summary")
    return dados if isinstance(dados, dict) else {}


def _paginado(caminho: str, *, max_paginas: int = MAX_PAGINAS,
              params: Optional[dict] = None) -> Iterator[dict]:
    """Percorre uma lista histórica seguindo o `nextPagePath` até ao fim.

    A API devolve do mais recente para o mais antigo, o que deixa quem chama
    parar a meio assim que reconhece um movimento que já tinha."""
    proximo: Optional[str] = caminho
    primeiros = dict(params or {})
    primeiros["limit"] = PAGINA
    pagina = 0
    while proximo and pagina < max_paginas:
        dados = _pede(proximo, primeiros if pagina == 0 else None)
        itens = dados.get("items") if isinstance(dados, dict) else None
        for item in itens or []:
            yield item
        proximo = (dados or {}).get("nextPagePath") if isinstance(dados, dict) else None
        pagina += 1
        if proximo:
            time.sleep(PAUSA_HISTORICO)


def ordens_historicas(**kw) -> Iterator[dict]:
    return _paginado("/api/v0/equity/history/orders", **kw)


def dividendos(**kw) -> Iterator[dict]:
    return _paginado("/api/v0/equity/history/dividends", **kw)


def movimentos(**kw) -> Iterator[dict]:
    return _paginado("/api/v0/equity/history/transactions", **kw)


# ── Tradução para o formato da app (puro, sem rede nem base) ─────

def ticker_curto(ticker: str) -> str:
    """`AAPL_US_EQ` → `AAPL`, `VUAAl_EQ` → `VUAA`.

    O Trading 212 junta ao símbolo o mercado (uma letra minúscula) e o tipo de
    instrumento. Os extractos em PDF — e portanto o que já está na base — usam só
    a primeira parte."""
    base = (ticker or "").split("_")[0]
    while base and base[-1].islower():
        base = base[:-1]
    return base or (ticker or "")


def _numero(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _data_hora(v: Any) -> Optional[datetime]:
    """ISO 8601 do Trading 212 (com Z ou fuso) → datetime local sem fuso.

    A base guarda tudo sem fuso; misturar datas com e sem fuso rebenta nas
    comparações que o resto da app faz."""
    if not v:
        return None
    texto = str(v).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(texto)
    except ValueError:
        try:
            d = datetime.fromisoformat(texto[:19])
        except ValueError:
            return None
    if d.tzinfo is not None:
        d = d.astimezone().replace(tzinfo=None)
    return d


def fx_derivado(quantidade: float, preco: float, valor_eur: float) -> float:
    """Quantas unidades da moeda do instrumento valem 1€.

    A app guarda o câmbio como o PDF o dava (valor_eur = valor_na_moeda / fx) e o
    resto do código conta com isso. A API não o devolve nas posições, mas dá o
    valor nas duas moedas — o câmbio é a divisão. Em GBX isto dá ~87, que é
    exactamente o que os extractos traziam."""
    bruto = quantidade * preco
    if valor_eur <= 0 or bruto <= 0:
        return 1.0
    return round(bruto / valor_eur, 8)


def posicao_da_api(item: dict, mes: str) -> Optional[dict]:
    """Uma posição aberta, no formato de `investment_positions`."""
    instrumento = item.get("instrument") or {}
    ticker = ticker_curto(instrumento.get("ticker") or item.get("ticker") or "")
    if not ticker:
        return None
    quantidade = _numero(item.get("quantity"))
    if quantidade <= 0:
        return None
    carteira = item.get("walletImpact") or {}
    preco = _numero(item.get("currentPrice"))
    valor_eur = _numero(carteira.get("currentValue"))
    ganho_eur = _numero(carteira.get("unrealizedProfitLoss"))
    moeda = (instrumento.get("currency") or "EUR").upper()
    fx = 1.0 if moeda == "EUR" else fx_derivado(quantidade, preco, valor_eur)
    return {
        "instrument": ticker,
        "isin": instrumento.get("isin") or None,
        "currency": moeda,
        "quantity": quantidade,
        "avg_price": _numero(item.get("averagePricePaid")),
        "current_price": preco,
        "current_value_eur": round(valor_eur, 2),
        "return_eur": round(ganho_eur, 2),
        "fx_rate": fx,
        "statement_date": mes,
        "source": FONTE,
    }


# Nomes que a app usa nos movimentos de dinheiro (o resto do código procura
# "Depósito" e "Levantamento" para contar as entradas).
TIPOS_MOVIMENTO = {
    "DEPOSIT": "Depósito",
    "WITHDRAW": "Levantamento",
    "FEE": "Taxa",
    "TRANSFER": "Transferência",
    "INTEREST_ON_FREE_CASH": "Juros",
    "LENDING_INTEREST": "Juros",
}


def movimento_da_api(item: dict) -> Optional[dict]:
    quando = _data_hora(item.get("dateTime"))
    if quando is None:
        return None
    tipo_cru = str(item.get("type") or "").upper()
    montante = _numero(item.get("amount"))
    tipo = TIPOS_MOVIMENTO.get(tipo_cru)
    if tipo is None:
        # Um tipo novo não pode desaparecer em silêncio: entra pelo sinal.
        tipo = "Depósito" if montante > 0 else "Levantamento"
    return {
        "time": quando,
        "type": tipo,
        "currency": (item.get("currency") or "EUR").upper(),
        "amount": round(montante, 2),
        "external_id": str(item.get("reference") or "") or None,
        "source": FONTE,
    }


def dividendo_da_api(item: dict) -> Optional[dict]:
    quando = _data_hora(item.get("paidOn"))
    if quando is None:
        return None
    montante = _numero(item.get("amountInEuro")) or _numero(item.get("amount"))
    if montante == 0:
        return None
    return {
        "time": quando,
        "type": "Dividendo",
        "currency": "EUR",
        "amount": round(montante, 2),
        "external_id": str(item.get("reference") or "") or None,
        "source": FONTE,
    }


TAXAS_DE_CAMBIO = {"CURRENCY_CONVERSION_FEE"}


def ordem_da_api(item: dict) -> Optional[dict]:
    """Uma ordem executada, no formato de `investment_trades`.

    Só interessam as que chegaram a ser preenchidas: uma ordem cancelada não
    mexeu na carteira."""
    ordem = item.get("order") or {}
    execucao = item.get("fill") or {}
    quando = _data_hora(execucao.get("filledAt")) or _data_hora(ordem.get("createdAt"))
    if quando is None:
        return None
    quantidade = abs(_numero(execucao.get("quantity")) or _numero(ordem.get("filledQuantity")))
    preco = _numero(execucao.get("price"))
    if quantidade <= 0 or preco <= 0:
        return None
    instrumento = ordem.get("instrument") or {}
    ticker = ticker_curto(instrumento.get("ticker") or ordem.get("ticker") or "")
    if not ticker:
        return None

    carteira = execucao.get("walletImpact") or {}
    fx = _numero(carteira.get("fxRate")) or 1.0
    valor = round(quantidade * preco, 8)
    valor_eur = abs(_numero(carteira.get("netValue"))) or (valor / fx if fx else valor)
    taxa_cambio = sum(
        abs(_numero(t.get("quantity")))
        for t in (carteira.get("taxes") or [])
        if str(t.get("name") or "").upper() in TAXAS_DE_CAMBIO
    )
    lado = str(ordem.get("side") or "").upper()
    if not lado:
        lado = "SELL" if _numero(execucao.get("quantity")) < 0 else "BUY"
    return {
        "execution_time": quando,
        "instrument": ticker,
        "isin": instrumento.get("isin") or None,
        "currency": (instrumento.get("currency") or ordem.get("currency") or "EUR").upper(),
        "direction": "Sell" if lado == "SELL" else "Buy",
        "quantity": quantidade,
        "execution_price": preco,
        "value": valor,
        "value_eur": round(valor_eur, 2),
        "fx_rate": fx,
        "fx_fee": round(taxa_cambio, 2),
        "external_id": str(execucao.get("id") or ordem.get("id") or "") or None,
        "source": FONTE,
    }


# ── Sincronização ────────────────────────────────────────────────

def _mes_actual(hoje: Optional[date] = None) -> str:
    d = hoje or date.today()
    return f"{d.year}-{d.month:02d}"


def _mesmo_movimento(a, b_time: datetime, b_amount: float) -> bool:
    """Reconhece o que já tinha entrado pelos extractos em PDF, que não trazem
    referência nenhuma: mesmo dia e mesmo valor.

    O dia inteiro e não o instante porque o extracto marca a hora local e a API
    marca-a em UTC — no Verão isso dá uma hora de diferença e nada emparelhava.

    Só se aplica a linhas SEM referência: entre linhas da API manda a referência,
    senão dois depósitos iguais no mesmo dia passavam por um só."""
    if a.time is None or (a.external_id or "").strip():
        return False
    return a.time.date() == b_time.date() and abs((a.amount or 0) - b_amount) < 0.01


def sincroniza(db, *, historico: bool = False, hoje: Optional[date] = None) -> dict:
    """Traz posições, ordens, dividendos e movimentos de dinheiro.

    `historico=False` (o normal) pára cada lista assim que reconhece algo que já
    está guardado — uma sincronização diária são duas ou três páginas. Com
    `historico=True` varre tudo, para a primeira vez."""
    from models import (
        InvestmentPosition, InvestmentSummary, InvestmentTrade, InvestmentTransaction,
    )

    mes = _mes_actual(hoje)
    relatorio = {
        "positions": 0, "trades": 0, "transactions": 0, "dividends": 0,
        "account_value": None, "errors": [],
    }

    # ── Posições abertas ──
    linhas = [p for p in (posicao_da_api(i, mes) for i in posicoes()) if p]
    # Um ISIN que já existe na base manda no nome: as posições antigas foram
    # gravadas com o símbolo do extracto e trocar-lhe o nome partiria o histórico.
    por_isin = {
        p.isin: p.instrument
        for p in db.query(InvestmentPosition).filter(InvestmentPosition.source == FONTE).all()
        if p.isin
    }
    for dados in linhas:
        if dados["isin"] and dados["isin"] in por_isin:
            dados["instrument"] = por_isin[dados["isin"]]
        existente = (
            db.query(InvestmentPosition)
            .filter(
                InvestmentPosition.instrument == dados["instrument"],
                InvestmentPosition.source == FONTE,
                InvestmentPosition.statement_date == mes,
            )
            .first()
        )
        if existente:
            for k, v in dados.items():
                setattr(existente, k, v)
            existente.price_updated_at = datetime.now()
        else:
            db.add(InvestmentPosition(**dados, price_updated_at=datetime.now()))
        relatorio["positions"] += 1

    # Uma posição fechada desde a última leitura tem de sair do mês actual, senão
    # continuava a somar para o valor da carteira.
    vivos = {d["instrument"] for d in linhas}
    for antiga in (
        db.query(InvestmentPosition)
        .filter(
            InvestmentPosition.source == FONTE,
            InvestmentPosition.statement_date == mes,
        ).all()
    ):
        if antiga.instrument not in vivos:
            db.delete(antiga)

    db.commit()

    # ── Ordens executadas ──
    try:
        conhecidas = {
            t.external_id for t in db.query(InvestmentTrade)
            .filter(InvestmentTrade.source == FONTE).all() if t.external_id
        }
        # Só as que vieram dos extractos (sem id do broker) entram na comparação
        # por hora+quantidade: duas execuções parciais da mesma ordem partilham
        # instante e quantidade, e só a referência as distingue.
        antigas = [
            t for t in db.query(InvestmentTrade).filter(InvestmentTrade.source == FONTE).all()
            if not (t.external_id or "").strip()
        ]
        seguidas = 0
        for item in ordens_historicas():
            dados = ordem_da_api(item)
            if not dados:
                continue
            # O dia e não o instante: o extracto marca a hora local e a API marca
            # em UTC. Com o mesmo instrumento e a mesma quantidade ao cêntimo, o
            # dia chega para identificar a ordem.
            ja_ta = (dados["external_id"] and dados["external_id"] in conhecidas) or any(
                t.instrument == dados["instrument"]
                and abs((t.quantity or 0) - dados["quantity"]) < 1e-8
                and t.execution_time
                and t.execution_time.date() == dados["execution_time"].date()
                for t in antigas
            )
            if ja_ta:
                seguidas += 1
                if not historico and seguidas >= 3:
                    break        # já se chegou ao que estava guardado
                continue
            seguidas = 0
            db.add(InvestmentTrade(**dados))
            if dados["external_id"]:
                conhecidas.add(dados["external_id"])
            relatorio["trades"] += 1
        db.commit()
    except T212Indisponivel as ex:
        relatorio["errors"].append(f"ordens: {ex}")

    # ── Dinheiro que entrou e saiu + dividendos ──
    for nome, fonte_itens, tradutor in (
        ("movimentos", movimentos, movimento_da_api),
        ("dividendos", dividendos, dividendo_da_api),
    ):
        try:
            guardados = (
                db.query(InvestmentTransaction)
                .filter(InvestmentTransaction.source == FONTE).all()
            )
            referencias = {t.external_id for t in guardados if t.external_id}
            seguidas = 0
            for item in fonte_itens():
                dados = tradutor(item)
                if not dados:
                    continue
                ja_ta = (dados["external_id"] and dados["external_id"] in referencias) or any(
                    _mesmo_movimento(t, dados["time"], dados["amount"]) for t in guardados
                )
                if ja_ta:
                    seguidas += 1
                    if not historico and seguidas >= 3:
                        break
                    continue
                seguidas = 0
                novo = InvestmentTransaction(**dados)
                db.add(novo)
                guardados.append(novo)
                if dados["external_id"]:
                    referencias.add(dados["external_id"])
                relatorio["dividends" if nome == "dividendos" else "transactions"] += 1
            db.commit()
        except T212Indisponivel as ex:
            relatorio["errors"].append(f"{nome}: {ex}")

    # ── Resumo da conta (uma linha por mês, como os extractos) ──
    try:
        resumo = resumo_da_conta()
        if resumo:
            investimentos = resumo.get("investments") or {}
            valor = _numero(resumo.get("totalValue"))
            relatorio["account_value"] = round(valor, 2)
            primeiro = date(int(mes[:4]), int(mes[5:7]), 1)
            do_mes = (
                db.query(InvestmentTransaction)
                .filter(InvestmentTransaction.source == FONTE,
                        InvestmentTransaction.time >= datetime(primeiro.year, primeiro.month, 1))
                .all()
            )
            linha = (
                db.query(InvestmentSummary)
                .filter(InvestmentSummary.statement_date == primeiro).first()
            )
            if linha is None:
                linha = InvestmentSummary(statement_date=primeiro)
                db.add(linha)
            linha.account_value = round(valor, 2)
            linha.open_return = round(_numero(investimentos.get("unrealizedProfitLoss")), 2)
            linha.deposits = round(sum(t.amount for t in do_mes if t.type == "Depósito"), 2)
            linha.withdrawals = round(sum(abs(t.amount) for t in do_mes if t.type == "Levantamento"), 2)
            linha.dividends = round(sum(t.amount for t in do_mes if t.type == "Dividendo"), 2)
            db.commit()
    except T212Indisponivel as ex:
        relatorio["errors"].append(f"resumo: {ex}")

    # O gráfico do valor da carteira vive de snapshots diários; agora que as
    # quantidades estão certas, vale a pena gravar um.
    try:
        from routers.investments import _grava_snapshot
        _grava_snapshot(db)
    except Exception as ex:                                   # noqa: BLE001
        logger.warning("t212: snapshot falhou: %s", ex)

    relatorio["at"] = datetime.now().isoformat(timespec="seconds")
    return relatorio


def estado(db) -> dict:
    """Para o painel: se está ligado, quando foi a última leitura e o que trouxe."""
    from models import InvestmentPosition, InvestmentTrade, InvestmentTransaction, JobRun

    if not configurado():
        return {"configured": False, "positions": 0, "last_sync": None, "ok": None,
                "detail": "", "instruments": []}
    ultima = (
        db.query(JobRun).filter(JobRun.name == "sync_t212")
        .order_by(JobRun.started_at.desc()).first()
    )
    mes = _mes_actual()
    linhas = (
        db.query(InvestmentPosition)
        .filter(InvestmentPosition.source == FONTE, InvestmentPosition.statement_date == mes)
        .order_by(InvestmentPosition.current_value_eur.desc())
        .all()
    )
    return {
        "configured": True,
        "month": mes,
        "positions": len(linhas),
        "value_eur": round(sum(p.current_value_eur or 0 for p in linhas), 2),
        "instruments": [p.instrument for p in linhas],
        "trades": db.query(InvestmentTrade).filter(InvestmentTrade.source == FONTE).count(),
        "transactions": db.query(InvestmentTransaction).filter(InvestmentTransaction.source == FONTE).count(),
        "last_sync": ultima.started_at.isoformat(timespec="seconds") if ultima and ultima.started_at else None,
        "ok": ultima.ok if ultima else None,
        "detail": (ultima.detail or "") if ultima else "",
    }
