"""Banco ligado: as despesas entram sozinhas.

Fluxo: escolhe-se o banco → a app cria uma autorização → ele aprova no site do
banco → a app guarda as contas e passa a sincronizar todos os dias.

O banco só mostra ~90 dias para trás, mas cada sincronização grava na base
local, por isso o histórico fica permanente deste lado — os meses anteriores
continuam a ser os que já foram importados dos extractos.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from bank_categories import e_transferencia_propria, limpa
import expense_kind as ek
from fx_historico import para_euros
from database import get_db
from models import BankAccount, BankConnection, BankIgnoredTx, Expense, MerchantRule
import openbanking as ob

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/banking", tags=["Banco"])

# Movimentos que não são consumo (transferências para a própria conta, câmbios).
IGNORAR = ("exchanged to", "exchanged from", "to eur", "vault", "savings",
           "top-up by", "transfer from revolut", "to revolut")


# O Enable Banking só aceita https nas aplicações de produção. A app corre em
# http://localhost:3001, por isso o regresso do banco entra por uma porta https
# mínima que só reencaminha para cá (backend/callback_https.py).
REDIRECT_PADRAO = os.getenv("BANK_REDIRECT_URL", "https://localhost:3043/expenses")


class LigarBanco(BaseModel):
    institution_id: str
    redirect_url: str = ""
    history_days: int = 90


@router.get("/status")
def estado(db: Session = Depends(get_db)):
    ligacoes = db.query(BankConnection).order_by(BankConnection.created_at.desc()).all()
    contas = db.query(BankAccount).all()
    por_ligacao: dict[int, list] = {}
    for c in contas:
        por_ligacao.setdefault(c.connection_id, []).append({
            "id": c.id, "name": c.name, "iban": c.iban[-4:] if c.iban else "",
            "balance": c.balance, "currency": c.currency,
            "last_transaction": c.last_transaction_date.isoformat() if c.last_transaction_date else None,
        })
    app_info, aviso = None, ""
    if ob.configurado():
        try:
            app_info = ob.aplicacao()
            if app_info["environment"] == "SANDBOX":
                aviso = ("a aplicação registada é de sandbox: só dá acesso a bancos de teste. "
                         "Para ligar o banco a sério é preciso registar uma aplicação em Production "
                         "e activá-la com \"Activate by linking accounts\".")
            elif not app_info["active"]:
                aviso = ("aplicação de produção ainda por activar — carrega em "
                         "\"Activate by linking accounts\" no painel do Enable Banking.")
        except ob.BancoIndisponivel as ex:
            aviso = str(ex)[:200]
    return {
        "configured": ob.configurado(),
        "app": app_info,
        "warning": aviso,
        "connections": [
            {
                "id": l.id, "institution": l.institution_name or l.institution_id,
                "institution_id": l.institution_id,
                "status": l.status, "link": l.link if l.status == "pendente" else "",
                "expires_at": l.expires_at.isoformat() if l.expires_at else None,
                "expires_in_days": (l.expires_at.date() - date.today()).days if l.expires_at else None,
                "last_sync": l.last_sync_at.isoformat() if l.last_sync_at else None,
                "last_error": l.last_error,
                "accounts": por_ligacao.get(l.id, []),
            }
            for l in ligacoes
        ],
        "synced_expenses": db.query(Expense).filter(Expense.bank_tx_id.isnot(None)).count(),
        "learned_merchants": db.query(MerchantRule).count(),
        "unknown_merchants": db.query(Expense).filter(
            Expense.bank_tx_id.isnot(None), Expense.category == "other").count(),
    }


@router.get("/balances")
def saldos(db: Session = Depends(get_db)):
    """Quanto há em cada banco e no total, da última sincronização.

    O Revolut traz uma conta por moeda, e somam-se todas. O que não é euro
    converte-se à taxa de hoje; sem taxa fica de fora e diz-se.

    Uma conta sem IBAN não é a conta à ordem: na Caixa é o cartão, que vinha a
    150€ e vai descendo com as compras. Ele conta só o que está na conta (em 11
    de Outubro, 384,29€ — com o cartão dava 515,89€). Fica à parte, no `title`."""
    bancos = []
    for lig in (db.query(BankConnection)
                .filter(BankConnection.status.in_(("ligado", "expirado")))
                .order_by(BankConnection.id).all()):
        contas = (db.query(BankAccount)
                  .filter(BankAccount.connection_id == lig.id, BankAccount.active == True)  # noqa: E712
                  .all())
        soma, sem_taxa, linhas, cartoes = 0.0, [], [], []
        for c in contas:
            if c.balance is None:
                continue
            if not c.iban:
                cartoes.append({"currency": c.currency, "balance": c.balance})
                continue
            em_euros = c.balance if c.currency == "EUR" or not c.balance \
                else para_euros(c.balance, c.currency, date.today())
            if em_euros is None:
                sem_taxa.append(f"{c.balance:.2f} {c.currency}")
                continue
            soma += em_euros
            if c.balance:
                linhas.append({"iban": c.iban[-4:] if c.iban else "", "currency": c.currency,
                               "balance": c.balance, "balance_eur": round(em_euros, 2)})
        if not contas:
            continue
        nome = lig.institution_name or lig.institution_id.split("|")[0]
        bancos.append({
            "id": lig.id,
            "name": nome.split()[0],
            "institution": nome,
            "balance": round(soma, 2),
            "accounts": linhas,
            "missing_fx": sem_taxa,
            "cards": cartoes,
            "status": lig.status,
            "as_of": lig.last_sync_at.isoformat() + "Z" if lig.last_sync_at else None,
        })
    return {"banks": bancos, "total": round(sum(b["balance"] for b in bancos), 2)}


@router.get("/institutions")
def instituicoes(country: str = Query("PT", min_length=2, max_length=2)):
    try:
        return ob.bancos(country.upper())
    except ob.BancoIndisponivel as ex:
        raise HTTPException(status_code=503, detail=str(ex))


@router.post("/connect")
def ligar(body: LigarBanco, db: Session = Depends(get_db)):
    destino = body.redirect_url if body.redirect_url.startswith("https://") else REDIRECT_PADRAO
    try:
        r = ob.cria_ligacao(body.institution_id, destino, body.history_days)
    except ob.BancoIndisponivel as ex:
        raise HTTPException(status_code=503, detail=str(ex))
    lig = BankConnection(
        institution_id=body.institution_id,
        institution_name=body.institution_id.split("|")[0],
        requisition_id=r["requisition_id"],
        agreement_id=r.get("agreement_id", ""),
        status="pendente",
        link=r["link"],
        expires_at=datetime.fromisoformat(r["expires_at"]) if r.get("expires_at") else None,
    )
    db.add(lig)
    db.commit()
    db.refresh(lig)
    return {"id": lig.id, "link": lig.link, "status": lig.status, "redirect_url": destino}


class Conclusao(BaseModel):
    code: str


@router.post("/connections/{connection_id}/finish")
def concluir(connection_id: int, body: Conclusao, db: Session = Depends(get_db)):
    """Depois de aprovar no banco: troca o código por uma sessão e guarda as contas."""
    lig = db.query(BankConnection).filter(BankConnection.id == connection_id).first()
    if not lig:
        raise HTTPException(status_code=404, detail="ligação não encontrada")
    if not body.code:
        raise HTTPException(status_code=400, detail="falta o código devolvido pelo banco")
    try:
        sessao = ob.confirma_ligacao(body.code)
    except ob.CodigoJaUsado:
        # A app conclui sozinha assim que volta do banco. Colar o mesmo endereço
        # a seguir dá sempre este erro, e a mensagem crua ("Wrong authorization
        # code") faz parecer que a autorização correu mal quando já foi gasta.
        raise HTTPException(
            status_code=400,
            detail="esse código já foi usado (é de uso único). Carrega em "
                   "\"concluir no banco\" para autorizares de novo.")
    except ob.BancoIndisponivel as ex:
        lig.last_error = str(ex)[:200]
        db.commit()
        raise HTTPException(status_code=503, detail=str(ex))

    if not sessao["accounts"]:
        # Autorização válida e zero contas é o modo restrito a filtrar: a API só
        # devolve as contas que estão ligadas à própria aplicação no painel.
        # Repetir a autorização aqui nunca resolve nada.
        lig.status = "pendente"
        lig.last_error = (
            f"o banco autorizou mas não devolveu contas. No modo gratuito, cada banco tem de "
            f"ser ligado primeiro no painel do Enable Banking (Applications → a tua aplicação → "
            f"\"Activate by linking accounts\") com a conta {lig.institution_name}."
        )[:400]
        db.commit()
        return {"status": "pendente", "accounts": 0, "hint": lig.last_error}

    novas = 0
    for c in sessao["accounts"]:
        if db.query(BankAccount).filter(BankAccount.account_id == c["uid"]).first():
            continue
        db.add(BankAccount(
            connection_id=lig.id, account_id=c["uid"],
            name=c["name"], iban=c.get("iban", ""), currency=c.get("currency", "EUR"),
            balance=ob.saldo(c["uid"]),
        ))
        novas += 1
    lig.status = "ligado"
    lig.agreement_id = sessao.get("session_id", "")
    lig.last_error = ""
    if sessao.get("valid_until"):
        try:
            lig.expires_at = datetime.fromisoformat(sessao["valid_until"].replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    db.commit()

    # Logo a seguir a autorizar, e só aí, o Revolut dá o histórico todo: passados
    # 5 minutos passa a dar apenas 90 dias. Por isso pede-se tudo já.
    importadas = 0
    try:
        primeira = sincronizar(days=730, force=True, connection_id=lig.id, db=db)
        importadas = sum(x.get("created", 0) for x in primeira["results"])
    except Exception as ex:                       # a ligação em si já está feita
        logger.warning("primeira sincronização falhou: %s", ex)
        lig.last_error = f"ligado, mas não consegui trazer o histórico: {ex}"[:400]
        db.commit()

    return {"status": "ligado", "accounts": len(sessao["accounts"]),
            "new": novas, "imported": importadas}


def _categoriza(descricao: str, db: Session) -> str:
    from bank_categories import categoria_com_memoria
    return categoria_com_memoria(descricao, db)


# O extracto em PDF e a API do banco não datam o mesmo movimento no mesmo dia (um
# usa a data do lançamento, o outro a do processamento). Exigir o MESMO dia deixou
# passar as duas versões da mesma compra: 7 despesas ficaram a contar a dobrar,
# ~1.300€ só em Julho.
JANELA_GEMEO_DIAS = 3


def _primeira_palavra(texto: str) -> str:
    """O nome da loja sem acentos: o extracto escreve `Żabka` e a API `Zabka
    Zd705 K.1`. Com o acento pelo meio, 16 compras ficaram a contar a dobrar."""
    import unicodedata
    simples = "".join(
        c for c in unicodedata.normalize("NFD", (texto or "").lower())
        if unicodedata.category(c) != "Mn"
    )
    for parte in simples.replace("*", " ").split():
        limpo = "".join(c for c in parte if c.isalnum())
        if len(limpo) >= 3:
            return limpo
    return ""


def _parecidas(a: str, b: str) -> bool:
    pa, pb = _primeira_palavra(a), _primeira_palavra(b)
    if not pa or not pb:
        return False
    return pa == pb or pa.startswith(pb) or pb.startswith(pa)


def _gemeo_do_extracto(db: Session, quando: date, valor: float, descricao: str):
    """A mesma despesa já importada à mão, se existir: mesmo valor, poucos dias de
    diferença e o mesmo comerciante. O candidato mais próximo na data ganha."""
    candidatos = (
        db.query(Expense)
        .filter(
            Expense.bank_tx_id.is_(None),
            Expense.amount == valor,
            Expense.date >= quando - timedelta(days=JANELA_GEMEO_DIAS),
            Expense.date <= quando + timedelta(days=JANELA_GEMEO_DIAS),
        )
        .all()
    )
    if not candidatos:
        return None

    # Noutro dia, o valor sozinho não chega — um café de 3,50€ repete-se todas as
    # semanas. Enganar-se aqui apaga uma despesa a sério, enquanto falhar deixa
    # só um duplicado à vista: na dúvida, não junta.
    def serve(e: Expense) -> bool:
        return e.date == quando or _parecidas(e.description or "", descricao)

    bons = [e for e in candidatos if serve(e)]
    if not bons:
        return None
    return min(bons, key=lambda e: (abs((e.date - quando).days), e.id))


def _sincroniza_conta(db: Session, conta: BankAccount, desde: Optional[str]) -> dict:
    criadas = repetidas = ignoradas = horas_preenchidas = 0
    ultima: Optional[date] = None
    for t in ob.transacoes(conta.account_id, desde):
        if t["pending"]:
            continue                     # ainda pode mudar de valor ou desaparecer
        quando = date.fromisoformat(t["date"])
        if ultima is None or quando > ultima:
            ultima = quando              # data do último movimento, entre ou não
        if not t["amount"]:
            ignoradas += 1                   # autorizações a zero não são gastos
            continue
        texto = t["description"].lower()
        if any(p in texto for p in IGNORAR) or e_transferencia_propria(t["description"], conta.name):
            ignoradas += 1                   # dinheiro dele a mudar de conta, não gasto
            continue
        ja_existe = db.query(Expense).filter(Expense.bank_tx_id == t["external_id"]).first()
        if ja_existe:
            # As despesas antigas entraram sem hora (o banco põe-na num campo que
            # não era lido). Cada sincronização vai preenchendo o que falta.
            if not ja_existe.time_of_day and t["time"]:
                ja_existe.time_of_day = t["time"]
                horas_preenchidas += 1
            repetidas += 1
            continue
        if db.query(BankIgnoredTx).filter(BankIgnoredTx.tx_id == t["external_id"]).first():
            ignoradas += 1                   # ele apagou-a; não volta a entrar
            continue
        # As contas não são todas em euros: 45 zlótis não são 45 €.
        valor, nota = t["amount"], "do banco"
        if (t.get("currency") or "EUR").upper() != "EUR":
            convertido = para_euros(valor, t["currency"], quando)
            if convertido is None:
                ignoradas += 1               # sem taxa fiável, melhor não inventar
                continue
            nota = f"do banco · {abs(valor):.2f} {t['currency'].upper()}"
            valor = convertido

        # não duplicar o que já veio dos extractos importados à mão
        gemeo = _gemeo_do_extracto(db, quando, valor, t["description"])
        if gemeo:
            gemeo.bank_tx_id = t["external_id"]      # passa a ser a mesma coisa
            if not gemeo.time_of_day and t["time"]:
                gemeo.time_of_day = t["time"]
            db.flush()          # senão o movimento seguinte agarrava o mesmo gémeo
            repetidas += 1
            continue
        limpo = limpa(t["description"])[:120]
        categoria = _categoriza(t["description"], db)
        db.add(Expense(
            description=limpo,
            amount=valor,
            category=categoria,
            date=quando,
            time_of_day=t["time"] or None,
            bank_tx_id=t["external_id"],
            merchant_city=t.get("merchant_city") or None,
            notes=nota,
            # Mandar 300€ para a corretora não é gastar 300€.
            kind=ek.classifica(t["description"], categoria, valor),
        ))
        db.flush()              # para o próximo movimento já a encontrar
        criadas += 1
    saldo = ob.saldo(conta.account_id)
    if saldo is not None:            # uma conta a zero também é um saldo
        conta.balance = saldo
    if ultima and (not conta.last_transaction_date or ultima > conta.last_transaction_date):
        conta.last_transaction_date = ultima
    db.commit()

    # Uma compra revertida só se reconhece quando a devolução chega — o que pode
    # ser dias depois da compra ter entrado. Revê-se sempre a janela recente.
    recentes = (
        db.query(Expense)
        .filter(Expense.date >= date.today() - timedelta(days=45))
        .all()
    )
    estornos = ek.marca_estornos(recentes)
    if estornos:
        db.commit()

    return {"account": conta.name, "created": criadas, "existing": repetidas,
            "skipped": ignoradas, "times_filled": horas_preenchidas,
            "reversals": estornos}


# O banco só permite ler uma conta ~4x por dia quando o utilizador não está
# presente (PSD2). Uma leitura a cada 5h chega e nunca chateia o limite.
INTERVALO_MINIMO_H = 5


@router.post("/sync")
def sincronizar(days: int = Query(30, ge=1, le=730), force: bool = False,
                connection_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Traz o que há de novo. Corre sozinho todos os dias; também dá para forçar."""
    if not ob.configurado():
        raise HTTPException(status_code=503, detail="banco não configurado (ver .env)")
    desde = (date.today() - timedelta(days=days)).isoformat()
    agora = datetime.utcnow()
    resultados = []
    contas = db.query(BankAccount).filter(BankAccount.active == True)  # noqa: E712
    if connection_id:                    # ao ligar um banco novo não se mexe nos outros
        contas = contas.filter(BankAccount.connection_id == connection_id)
    for conta in contas.all():
        if (not force and conta.last_sync_at
                and (agora - conta.last_sync_at).total_seconds() < INTERVALO_MINIMO_H * 3600):
            resultados.append({"account": conta.name, "skipped_recent": True})
            continue
        lig = db.query(BankConnection).filter(BankConnection.id == conta.connection_id).first()
        try:
            resultados.append(_sincroniza_conta(db, conta, desde))
            conta.last_sync_at = agora
            if lig:
                lig.last_sync_at = datetime.utcnow()
                lig.last_error = ""
                lig.status = "ligado"
        except ob.BancoIndisponivel as ex:
            texto = str(ex)
            if lig:
                lig.last_error = texto[:200]
                # 401/403 costumam significar autorização caducada
                if "401" in texto or "403" in texto or "expired" in texto.lower():
                    lig.status = "expirado"
            resultados.append({"account": conta.name, "error": texto[:160]})
        db.commit()
    return {"accounts": len(resultados), "results": resultados}


@router.post("/learn")
def aprender(db: Session = Depends(get_db)):
    """Manda à IA as lojas que nenhuma regra conhece e guarda o que ela disser."""
    from bank_ai import aplica_regras, classifica_desconhecidas
    ja = aplica_regras(db)
    r = classifica_desconhecidas(db)
    return {**r, "por_regras_conhecidas": ja}


# ── Regras dele ──────────────────────────────────────────────────
# Nascem quando ele corrige a categoria de um movimento do banco (ver
# `update_expense`). Aqui vêem-se, mudam-se e apagam-se — sem isto eram
# invisíveis, e uma correcção enganada ficava para sempre.

class RegraIn(BaseModel):
    category: str


def _regra_out(r: MerchantRule, contagem: dict[str, int]) -> dict:
    return {"id": r.id, "key": r.key, "label": r.label or r.key, "category": r.category,
            "expenses": contagem.get(r.key, 0),
            "updated_at": r.updated_at.isoformat() if r.updated_at else None}


def _contagem_por_chave(db: Session) -> dict[str, int]:
    from bank_categories import chave
    contagem: dict[str, int] = {}
    for (descricao,) in db.query(Expense.description).filter(Expense.bank_tx_id.isnot(None)):
        k = chave(descricao or "")
        contagem[k] = contagem.get(k, 0) + 1
    return contagem


@router.get("/rules")
def regras(db: Session = Depends(get_db)):
    contagem = _contagem_por_chave(db)
    linhas = (db.query(MerchantRule).filter(MerchantRule.source == "manual")
              .order_by(MerchantRule.updated_at.desc(), MerchantRule.created_at.desc()).all())
    return [_regra_out(r, contagem) for r in linhas]


@router.put("/rules/{rule_id}")
def muda_regra(rule_id: int, data: RegraIn, db: Session = Depends(get_db)):
    from bank_categories import arruma_iguais, categoria_valida
    r = db.query(MerchantRule).filter(MerchantRule.id == rule_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="regra não encontrada")
    if not categoria_valida(data.category, db):
        raise HTTPException(status_code=400, detail="categoria desconhecida")
    r.category, r.source, r.updated_at = data.category, "manual", datetime.utcnow()
    mudadas = arruma_iguais(db, r.key, data.category)
    db.commit()
    return {**_regra_out(r, _contagem_por_chave(db)), "changed": mudadas}


@router.delete("/rules/{rule_id}")
def apaga_regra(rule_id: int, db: Session = Depends(get_db)):
    """Tira a regra. As despesas ficam com a categoria que têm."""
    r = db.query(MerchantRule).filter(MerchantRule.id == rule_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="regra não encontrada")
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.delete("/connections/{connection_id}")
def apagar(connection_id: int, db: Session = Depends(get_db)):
    lig = db.query(BankConnection).filter(BankConnection.id == connection_id).first()
    if not lig:
        raise HTTPException(status_code=404, detail="ligação não encontrada")
    db.query(BankAccount).filter(BankAccount.connection_id == connection_id).delete()
    db.delete(lig)
    db.commit()
    return {"ok": True}
