"""Dar sentido às descrições que vêm do banco.

O extracto não diz "Vinted": diz `Mgp*vinted`, `Klarna*youget.pt`,
`Crunchyroll *eur`, `Zettle_*souvenier`. Sem limpar isto, quase tudo caía em
"Outro". E há movimentos que nem sequer são despesas — carregar a conta a partir
de outra conta própria é dinheiro que muda de sítio, não dinheiro gasto.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Optional

# Intermediários de pagamento que aparecem colados ao nome real da loja.
_INTERMEDIARIOS = re.compile(
    r"^(mgp|klarna|pep|zettle_?|sumup|sq|square|paypal|pp|izettle|nets|adyen|stripe|"
    r"tpv|google|apple pay|gpay|revolut\*?)\s*\*+\s*", re.I
)
_REFERENCIA = re.compile(r"^[A-Z0-9]{12,}\s+")          # OBADSS62XAYIZLWFB …
# A Caixa prefixa cada linha com o tipo de operação e corta o resultado aos 21
# caracteres: `COMPRAS C.DEB INTER F` é uma compra a débito no "Inter Figueira
# Da Foz", com o nome cortado a meio da palavra. Sem tirar o prefixo, a mesma
# loja tinha duas identidades — o Auchan, o Lidl, o Carrefour e o Intermarché
# tinham todos uma regra por cada forma de aparecer, e uma correcção dele numa
# delas não chegava à outra.
#
# O dinheiro que volta traz outro prefixo: `CR VCHER CRT DB GOPRO` (crédito por
# voucher no cartão de débito) é a GoPro a devolver o que cobrou como `GOPRO.C`.
# Com o prefixo lá dentro a devolução não tinha loja e a compra nunca se anulava.
_OPERACAO_CGD = re.compile(
    r"^compras?\s*c\.?\s*d[eé]b\.?\s+|^compra\s+|^cr\.?\s+vcher\s+crt\.?\s+d[eé]?b\.?\s+", re.I)
_SUFIXO_MOEDA = re.compile(r"\s*\*?\s*(eur|usd|gbp|pln)\s*$", re.I)
_DEVOLUCAO = re.compile(r"^(refund from|reembolso de|estorno de)\s+", re.I)


def limpa(descricao: str) -> str:
    """Nome utilizável da loja, sem o lixo do processador de pagamentos."""
    t = _REFERENCIA.sub("", descricao.strip())
    t = _OPERACAO_CGD.sub("", t)
    t = _DEVOLUCAO.sub("", t)
    anterior = None
    while anterior != t:                                # `Google *gpay Klarna*x`
        anterior = t
        t = _INTERMEDIARIOS.sub("", t).strip()
    t = _SUFIXO_MOEDA.sub("", t)
    return t.strip(" -*,").strip() or descricao.strip()


def _sem_acentos(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower())
                   if unicodedata.category(c) != "Mn")


def e_transferencia_propria(descricao: str, titular: str) -> bool:
    """Dinheiro que só mudou de conta dele: carregamentos e envios para si próprio.

    Contar isto como gasto (ou como receita) inflaciona os dois lados sem que
    tenha havido consumo nenhum."""
    if not titular:
        return False
    texto = _sem_acentos(descricao)
    nomes = [n for n in _sem_acentos(titular).split() if len(n) > 2]
    return bool(nomes) and all(n in texto for n in nomes)


# Loja → categoria. Só o que ele usa mesmo; o resto continua a cair nas regras
# genéricas dos recibos.
LOJAS = {
    "shopping": ["vinted", "klarna", "youget", "shein", "temu", "amazon", "aliexpress",
                 "souvenir", "souvenier", "sztuka", "decathlon", "zara", "h&m", "fnac",
                 "worten", "primark", "action", "flying tiger", "hm pl", "cloudshop"],
    "subscriptions": ["crunchyroll", "netflix", "spotify", "apple.com/bill", "icloud",
                      "youtube", "disney", "hbo", "chatgpt", "openai", "anthropic",
                      "github", "google storage", "dropbox", "claude.ai", "midjourney"],
    "travel": ["airbnb", "booking.com", "ryanair", "easyjet", "wizz", "tap portugal",
               "flixbus", "blablacar", "hostel", "hotel", "trip.com", "omio"],
    "transport": ["uber", "bolt", "free now", "public trans", "jak dojade", "jakdojade",
                  "carris", "metro ", "cp comboios", "renfe", "mpk", "trenitalia", "gvb",
                  "oasa", "atac ", "tap&go", "delijn", "de lijn", "terravision",
                  "autobuska", "train to", "flixbus", "bus "],
    "groceries": ["spar", "dirk", "albert heijn", "jumbo", "conad", "carrefour", "delhaize",
                  "zabka", "biedronka", "lidl", "aldi", "continente", "pingo doce",
                  "mercadona", "auchan", "kaufland", "tesco", "coop"],
    "food": ["coffeeshop", "kebab", "sushi", "pizza", "gyros", "pasta", "trattoria",
             "pub", "automat spec", "bistro", "tavern", "bar ",
             "restauracja", "restaurante", "cafe", "café", "bakery", "piekarnia",
             "mcdonald", "kfc", "burger", "starbucks", "glovo", "bolt food", "uber eats"],
    "nightlife": ["discoteca", "klub", "club "],
    "entertainment": ["cinema", "kino", "museum", "muzeum", "teatr",
                      "steam", "epic games", "riot", "playstation", "xbox"],
    "invest": ["trading 212", "trading212", "finst", "degiro", "xtb", "etoro", "coinbase",
               "binance", "kraken"],
    "health": ["farmacia", "farmácia", "apteka", "pharmacy", "clinica", "clínica",
               "dentist", "massage", "hospital"],
    "bills": ["meo", "vodafone", "edp", "nos comunica", "agua", "água", "renda", "rent "],
}


def categoria(descricao: str) -> str:
    """Categoria a partir do nome da loja; "other" quando não há certeza."""
    t = _sem_acentos(limpa(descricao))
    for cat, lojas in LOJAS.items():
        for loja in lojas:
            if _sem_acentos(loja) in t:
                return cat
    from receipt_ocr import _categoria_local
    return _categoria_local(descricao)


CATEGORIAS = ["food", "groceries", "transport", "travel", "entertainment", "nightlife",
              "subscriptions", "shopping", "health", "bills", "invest", "other"]


def categoria_valida(cat: str, db) -> bool:
    """As de origem mais as que ele criou."""
    from models import ExpenseCategory
    return cat in CATEGORIAS or db.query(ExpenseCategory).filter(ExpenseCategory.value == cat).first() is not None


# No MB Way a "loja" é o número de telefone, e é a única coisa que distingue o
# ginásio de um amigo. A Caixa mostra-o com o meio tapado (`Trf Mbway 963XXX836`).
_MBWAY = re.compile(r"mb ?way(.*)")
_TELEFONE = re.compile(r"(\d{3})(?:xxx|\d{3})(\d{3})(?![\dx])")


def _chave_mbway(t: str) -> Optional[str]:
    m = _MBWAY.search(t)
    if not m:
        return None
    resto = re.sub(r"(?<=[\dx])[\s.-]+(?=[\dx])", "", m.group(1))
    tel = _TELEFONE.search(resto)
    return f"mbway {tel.group(1)}xxx{tel.group(2)}" if tel else None


def chave(descricao: str) -> str:
    """Identidade da loja: sem referências, sem número de terminal, sem acentos.

    `Mgp*vinted` e `vinted` são a mesma loja; `Airbnb * Hmr9zhb52h` e
    `Airbnb * Hmt9e8bfrd` também. No MB Way não: ali o número é a loja, e sem
    ele todas as transferências eram uma só — corrigir a do ginásio mudava as
    dos amigos todos."""
    t = _sem_acentos(limpa(descricao))
    mbway = _chave_mbway(t)
    if mbway:
        return mbway
    t = re.sub(r"\b[a-z0-9]*\d[a-z0-9]*\b", " ", t)     # códigos e números de talão
    t = re.sub(r"[^a-z ]+", " ", t)
    return " ".join(t.split())[:60]


# Abaixo disto um prefixo não identifica loja nenhuma ("cont" apanhava o
# Continente e a Conad).
MINIMO_PREFIXO = 6


def _por_prefixo(k: str, db):
    """A mesma loja com o nome cortado noutro sítio.

    A Caixa corta a 21 caracteres e o corte cai a meio da palavra: a mesma
    bomba de combustível chega como `INTER F` e como `Inter Figueira Da Foz`.
    Uma delas é prefixo da outra — e é por isso que se aceita o corte a meio da
    palavra, que é exactamente o que aqui acontece.

    Ganha a chave mais comprida (a mais específica) e, entre iguais, a que ele
    corrigiu à mão."""
    from models import MerchantRule
    if len(k) < MINIMO_PREFIXO:
        return None
    candidatas = [
        r for r in db.query(MerchantRule).all()
        if r.key and len(r.key) >= MINIMO_PREFIXO and r.key != k
        and (r.key.startswith(k) or k.startswith(r.key))
    ]
    if not candidatas:
        return None
    return max(candidatas, key=lambda r: (r.source == "manual", len(r.key)))


def _regra(descricao: str, db):
    from models import MerchantRule
    k = chave(descricao)
    if not k:
        return None
    regra = db.query(MerchantRule).filter(MerchantRule.key == k).first() or _por_prefixo(k, db)
    if regra:
        regra.hits = (regra.hits or 0) + 1
    return regra


def categoria_aprendida(descricao: str, db) -> Optional[str]:
    """O que já foi decidido antes para esta loja (correcção dele ou da IA)."""
    regra = _regra(descricao, db)
    return regra.category if regra else None


def aprende(descricao: str, categoria_nova: str, db, fonte: str = "manual") -> None:
    """Guarda a decisão. O que ele corrige à mão manda sempre sobre o que a IA disse."""
    from models import MerchantRule
    k = chave(descricao)
    if not k or not categoria_valida(categoria_nova, db):
        return
    regra = db.query(MerchantRule).filter(MerchantRule.key == k).first()
    if regra and regra.source == "manual" and fonte != "manual":
        return
    if regra:
        regra.category, regra.source = categoria_nova, fonte
        regra.updated_at = datetime.utcnow()
    else:
        db.add(MerchantRule(key=k, label=limpa(descricao)[:60], category=categoria_nova,
                            source=fonte, hits=0, updated_at=datetime.utcnow()))


def arruma_iguais(db, k: str, categoria: str, excepto: Optional[int] = None) -> int:
    """Passa à categoria nova as despesas do banco que já lá estavam com a mesma
    chave. Devolve quantas mudaram."""
    from models import Expense
    mudadas = 0
    for e in db.query(Expense).filter(Expense.bank_tx_id.isnot(None)).all():
        if e.id != excepto and e.category != categoria and chave(e.description) == k:
            e.category = categoria
            mudadas += 1
    return mudadas


def categoria_com_memoria(descricao: str, db) -> str:
    """Correcção dele → regra fixa → o que a IA aprendeu → "other".

    O que ele corrigiu à mão vem primeiro de propósito: se decidiu que a Vinted
    conta como outra coisa, não é a lista interna que o vai contrariar."""
    regra = _regra(descricao, db)
    if regra and regra.source == "manual":
        return regra.category
    fixa = categoria(descricao)
    if fixa != "other":
        return fixa
    return regra.category if regra else "other"
