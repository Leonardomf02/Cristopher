"""Ligação ao banco (Enable Banking).

As despesas chegavam sempre atrasadas porque dependiam de exportar um ficheiro
do Revolut e carregá-lo à mão — a 31 de Julho a última despesa registada era de
23 de Julho. Com isto autoriza-se o banco uma vez e as transacções passam a
entrar sozinhas, todos os dias.

Porquê o Enable Banking e não o GoCardless (ex-Nordigen): desde Julho de 2025 o
GoCardless deixou de aceitar registos novos no produto Bank Account Data. O
Enable Banking tem um modo gratuito ("restricted production") pensado
exactamente para isto — acesso só às contas que a própria pessoa liga.

Configuração em backend/.env:
    ENABLEBANKING_APP_ID=…              (id da aplicação no painel deles)
    ENABLEBANKING_KEY_PATH=backend/enablebanking.pem   (chave privada RSA)

O histórico que o banco mostra à partida é limitado (normalmente 90 dias), mas
cada sincronização grava na base local — daí para a frente o histórico é
permanente deste lado.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE = "https://api.enablebanking.com"
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_JWT: dict[str, object] = {"token": None, "expira": 0.0}
_CACHE_APP: dict[str, object] = {"dados": None, "expira": 0.0}


class BancoIndisponivel(Exception):
    """Sem credenciais ou API a recusar."""


class CodigoJaUsado(BancoIndisponivel):
    """O código que o banco devolve é de uso único: trocá-lo duas vezes dá 422.

    A app tenta concluir sozinha assim que volta do banco; se ele colar a seguir
    o mesmo endereço, o segundo pedido bate neste erro — que não tem nada a ver
    com a autorização estar errada."""


def _caminho_chave() -> str:
    caminho = os.getenv("ENABLEBANKING_KEY_PATH", "enablebanking.pem")
    if not os.path.isabs(caminho):
        caminho = os.path.join(_BASE_DIR, os.path.basename(caminho))
    return caminho


def configurado() -> bool:
    return bool(os.getenv("ENABLEBANKING_APP_ID")) and os.path.exists(_caminho_chave())


def _jwt() -> str:
    """Token assinado com a chave privada da aplicação (válido 24h)."""
    if not configurado():
        raise BancoIndisponivel(
            "Falta ENABLEBANKING_APP_ID no .env ou a chave privada em backend/enablebanking.pem"
        )
    if _CACHE_JWT["token"] and time.time() < float(_CACHE_JWT["expira"]) - 300:
        return str(_CACHE_JWT["token"])

    import jwt as pyjwt

    with open(_caminho_chave()) as f:
        chave = f.read()
    agora = int(time.time())
    token = pyjwt.encode(
        {"iss": "enablebanking.com", "aud": "api.enablebanking.com",
         "iat": agora, "exp": agora + 3600},
        chave,
        algorithm="RS256",
        headers={"typ": "JWT", "alg": "RS256", "kid": os.getenv("ENABLEBANKING_APP_ID")},
    )
    _CACHE_JWT.update({"token": token, "expira": agora + 3600})
    return token


def _pedido(metodo: str, caminho: str, **kwargs) -> dict:
    r = httpx.request(
        metodo, f"{BASE}{caminho}",
        headers={"Authorization": f"Bearer {_jwt()}"},
        timeout=40, **kwargs,
    )
    if r.status_code >= 400:
        raise BancoIndisponivel(f"{caminho} → {r.status_code}: {r.text[:200]}")
    return r.json() if r.content else {}


def _get(caminho: str, **params) -> dict:
    return _pedido("GET", caminho, params=params or None)


def _post(caminho: str, corpo: dict) -> dict:
    return _pedido("POST", caminho, json=corpo)


def aplicacao() -> dict:
    """Quem somos aos olhos deles: ambiente (SANDBOX/PRODUCTION) e se está activa.

    Serve para explicar porque é que só aparecem bancos de teste — uma aplicação
    de sandbox nunca chega aos bancos verdadeiros."""
    if _CACHE_APP["dados"] and time.time() < float(_CACHE_APP["expira"]):
        return dict(_CACHE_APP["dados"])          # o estado muda no painel, não a toda a hora
    a = _get("/application")
    info = {
        "name": a.get("name", ""),
        "environment": (a.get("environment") or "").upper(),
        "active": bool(a.get("active")),
        "redirect_urls": a.get("redirect_urls") or [],
        "countries": len(a.get("countries") or []),
    }
    _CACHE_APP.update({"dados": info, "expira": time.time() + 600})
    return info


def bancos(pais: str = "PT") -> list[dict]:
    """Bancos disponíveis no país, com os de teste identificados.

    Enquanto a aplicação não for activada no painel (ligando uma conta própria),
    esta lista só traz bancos de sandbox — é o sinal de que falta esse passo."""
    dados = _get("/aspsps", country=pais.upper())
    saida = []
    for a in dados.get("aspsps") or []:
        nome = a.get("name", "")
        pessoais = "personal" in (a.get("psu_types") or ["personal"])
        saida.append({
            "id": f"{nome}|{a.get('country', pais.upper())}",
            "name": nome,
            "country": a.get("country", pais.upper()),
            "logo": a.get("logo"),
            "days": str((a.get("maximum_consent_validity") or 7776000) // 86400),
            "sandbox": bool(a.get("sandbox")) or nome.lower().startswith("mock"),
            "personal": pessoais,
        })
    # primeiro os que servem contas pessoais e não são de teste
    saida.sort(key=lambda b: (b["sandbox"], not b["personal"], b["name"].lower()))
    return saida


def _dias_de_consentimento(nome: str, pais: str) -> int:
    """O máximo que este banco dá (o Revolut dá 180 dias, não 90).

    Pedir menos do que o permitido só serve para obrigar a renovar mais vezes —
    e cada renovação é a única altura em que o banco entrega o histórico todo."""
    try:
        for b in bancos(pais or "PT"):
            if b["name"].lower() == nome.lower():
                return max(1, min(int(b["days"]), 180))
    except (BancoIndisponivel, ValueError, TypeError):
        pass
    return 90


def cria_ligacao(institution_id: str, redirect_url: str, dias_historico: int = 90) -> dict:
    """Pede uma autorização ao banco. Devolve o link para onde ele tem de ir."""
    nome, _, pais = institution_id.partition("|")
    validade = datetime.now(timezone.utc) + timedelta(days=_dias_de_consentimento(nome, pais))
    r = _post("/auth", {
        "access": {"valid_until": validade.isoformat().replace("+00:00", "Z")},
        "aspsp": {"name": nome, "country": pais or "PT"},
        "state": f"cristopher-{int(time.time())}",
        "redirect_url": redirect_url,
        "psu_type": "personal",
    })
    return {
        "requisition_id": r.get("state") or f"cristopher-{int(time.time())}",
        "link": r.get("url", ""),
        "agreement_id": "",
        "expires_at": validade.replace(tzinfo=None).isoformat(),
    }


def confirma_ligacao(code: str) -> dict:
    """Troca o código devolvido pelo banco por uma sessão com as contas."""
    try:
        r = _post("/sessions", {"code": code})
    except BancoIndisponivel as ex:
        if "WRONG_AUTHORIZATION_CODE" in str(ex):
            raise CodigoJaUsado(str(ex)) from ex
        raise
    contas = []
    for c in r.get("accounts_data") or r.get("accounts") or []:
        if isinstance(c, str):
            contas.append({"uid": c, "name": "conta", "iban": "", "currency": "EUR"})
            continue
        ident = c.get("account_id") or {}
        contas.append({
            "uid": c.get("uid") or c.get("account_uid") or "",
            "name": c.get("name") or c.get("product") or "conta",
            "iban": ident.get("iban", "") if isinstance(ident, dict) else "",
            "currency": c.get("currency", "EUR"),
        })
    uteis = [c for c in contas if c["uid"]]
    if not uteis:
        # Uma sessão válida sem contas nenhumas é o sinal do modo restrito: o
        # Enable Banking devolve a sessão e retira as contas que não estão
        # ligadas à aplicação. Fica o payload inteiro no log, senão não há como
        # distinguir isto de o banco não ter partilhado nada.
        logger.warning("sessão do banco sem contas: %s", json.dumps(r, default=str)[:1000])
    return {
        "session_id": r.get("session_id", ""),
        "accounts": uteis,
        "aspsp": (r.get("aspsp") or {}).get("name", ""),
        # quanto tempo o banco deu mesmo (pode ser menos do que pedimos)
        "valid_until": (r.get("access") or {}).get("valid_until") or "",
    }


def estado_ligacao(session_id: str) -> dict:
    r = _get(f"/sessions/{session_id}")
    return {"status": r.get("status", "?"), "accounts": r.get("accounts") or []}


def saldo(account_uid: str) -> Optional[float]:
    try:
        b = _get(f"/accounts/{account_uid}/balances").get("balances") or []
    except BancoIndisponivel:
        return None
    for tipo in ("ITAV", "CLBD", "XPCD"):          # disponível, contabilístico, previsto
        for linha in b:
            if (linha.get("balance_type") or "").upper().startswith(tipo):
                try:
                    return float(linha["balance_amount"]["amount"])
                except (KeyError, TypeError, ValueError):
                    continue
    for linha in b:
        try:
            return float(linha["balance_amount"]["amount"])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _texto(t: dict) -> str:
    partes = t.get("remittance_information")
    if isinstance(partes, list) and partes:
        return " ".join(str(p) for p in partes if p).strip()
    if isinstance(partes, str) and partes.strip():
        return partes.strip()
    for lado in ("creditor", "debtor"):
        nome = (t.get(lado) or {}).get("name") if isinstance(t.get(lado), dict) else None
        if nome:
            return str(nome)
    return (t.get("bank_transaction_code") or {}).get("description") or "Movimento"


_ISO_COM_HORA = re.compile(r"\d{4}-\d{2}-\d{2}[T ](\d{2}:\d{2})")

# Por ordem de confiança: a hora a que a compra aconteceu vale mais do que a
# hora a que o banco a processou.
_CAMPOS_DE_HORA = ("transaction_date", "booking_datetime", "transaction_datetime",
                   "value_date", "booking_date")


def _hora_do_movimento(t: dict) -> str:
    """HH:MM do movimento, ou "" se o banco não a der.

    Cada banco põe a hora num campo diferente e o `booking_date` do Revolut vem
    só com a data — era por isso que 635 despesas em 635 ficavam sem hora e
    apareciam todas às 23:59 na linha do tempo do dia. Tenta os campos
    conhecidos e, se nenhum servir, varre o payload à procura de um instante."""
    def hora_de(valor) -> str:
        m = _ISO_COM_HORA.search(str(valor)) if valor else None
        # 00:00 é uma data sem hora disfarçada de instante, não meia-noite.
        return m.group(1) if m and m.group(1) != "00:00" else ""

    for campo in _CAMPOS_DE_HORA:
        h = hora_de(t.get(campo))
        if h:
            return h

    def varre(no, fundo: int = 0) -> str:
        if fundo > 4:
            return ""
        if isinstance(no, str):
            return hora_de(no)
        if isinstance(no, dict):
            for v in no.values():
                h = varre(v, fundo + 1)
                if h:
                    return h
        elif isinstance(no, list):
            for v in no[:20]:
                h = varre(v, fundo + 1)
                if h:
                    return h
        return ""

    return varre(t)


def _le_transacoes(account_uid: str, desde: Optional[str]) -> list[dict]:
    """Transacções normalizadas: valor positivo = dinheiro que saiu."""
    saida: list[dict] = []
    params = {"date_from": desde} if desde else {}
    continuacao: Optional[str] = None
    vistas: set[str] = set()
    repetidos: dict[str, int] = {}
    payloads: set[str] = set()
    for _ in range(100):                             # tecto de páginas, por segurança
        if continuacao:
            params["continuation_key"] = continuacao
        dados = _get(f"/accounts/{account_uid}/transactions", **params)
        for t in dados.get("transactions") or []:
            # páginas sobrepostas devolvem o mesmo movimento outra vez
            impressao = json.dumps(t, sort_keys=True, default=str)
            if impressao in payloads:
                continue
            payloads.add(impressao)
            try:
                valor = float(t["transaction_amount"]["amount"])
            except (KeyError, TypeError, ValueError):
                continue
            saiu = (t.get("credit_debit_indicator") or "DBIT").upper().startswith("D")
            quando = (t.get("booking_date") or t.get("value_date")
                      or t.get("transaction_date") or "")[:10]
            if not quando:
                continue
            hora = _hora_do_movimento(t)
            estado = (t.get("status") or "BOOK").upper()
            # Nem todos os bancos dão referência única. Sem ela monta-se uma a
            # partir do movimento, e se ainda assim houver iguais no mesmo dia
            # (dois cafés de 1,20€) numeram-se — senão o segundo desaparecia.
            chave = str(t.get("entry_reference") or t.get("transaction_id") or "").strip()
            if not chave:
                chave = f"{quando}-{valor}-{_texto(t)[:20]}"
            if chave in vistas:
                repetidos[chave] = repetidos.get(chave, 1) + 1
                chave = f"{chave}#{repetidos[chave]}"
            vistas.add(chave)
            saida.append({
                "external_id": chave,
                "date": quando,
                "time": hora,
                "amount": round(valor if saiu else -valor, 2),
                "currency": t["transaction_amount"].get("currency", "EUR"),
                "description": _texto(t)[:160],
                "merchant_city": "",
                "pending": not estado.startswith("BOOK"),
                "raw": json.dumps(t)[:2000],
            })
        seguinte = dados.get("continuation_key")
        if not seguinte or seguinte == continuacao:      # fim, ou banco preso na mesma página
            break
        continuacao = seguinte
    return saida


# Cada banco expõe uma janela de histórico diferente e não a anuncia em lado
# nenhum: o Revolut aceita dois anos, a Caixa Geral de Depósitos recusa tudo o
# que passe dos 90 dias. E recusa o pedido INTEIRO com 422, em vez de devolver o
# que tem — por isso a primeira sincronização da CGD (que pede 730 dias para
# apanhar o histórico todo) não trouxe movimento nenhum e a ligação ficou a
# dizer "ligado" com zero importados.
_JANELAS = (730, 365, 180, 90, 30, 7)
_JANELA_ACEITE: dict[str, int] = {}      # o que cada conta já aceitou, por uid


def transacoes(account_uid: str, desde: Optional[str] = None) -> list[dict]:
    """Como `_le_transacoes`, mas encolhe o pedido até o banco o aceitar."""
    if not desde:
        return _le_transacoes(account_uid, None)

    hoje = date.today()
    try:
        pedidos = max(1, (hoje - date.fromisoformat(desde)).days)
    except ValueError:
        return _le_transacoes(account_uid, desde)

    # Já se sabe o que esta conta aceita: não vale a pena gastar leituras (o
    # banco só deixa ler cada conta ~4x por dia) a levar 422 outra vez.
    tecto = _JANELA_ACEITE.get(account_uid)
    if tecto:
        pedidos = min(pedidos, tecto)

    ultimo: Optional[BancoIndisponivel] = None
    for dias in [pedidos] + [j for j in _JANELAS if j < pedidos]:
        try:
            movimentos = _le_transacoes(account_uid, (hoje - timedelta(days=dias)).isoformat())
        except BancoIndisponivel as ex:
            if "WRONG_TRANSACTIONS_PERIOD" not in str(ex):
                raise
            logger.info("banco recusou %s dias de histórico nesta conta; a pedir menos", dias)
            ultimo = ex
            continue
        _JANELA_ACEITE[account_uid] = dias
        return movimentos
    raise ultimo if ultimo else BancoIndisponivel("o banco recusou todas as janelas de histórico")
