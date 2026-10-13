"""Categorizar lojas que nenhuma regra conhece.

Cada viagem traz nomes que não estão em lista nenhuma (`Diamanti Evgenia`,
`Fratelli Srl`, `Automat Spec`). Em vez de andar a escrever regras à mão, o que
sobra em "Outro" vai uma vez à IA, e a resposta fica guardada como regra — a
segunda vez que essa loja aparecer já é imediata e não custa nada.

Corre depois da sincronização, nunca dentro do pedido do utilizador.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy.orm import Session

from ai_config import ask_agent, extract_json
import expense_kind as ek
from bank_categories import CATEGORIAS, aprende, categoria_aprendida, chave, limpa
from models import Expense, MerchantRule

logger = logging.getLogger(__name__)

MAX_POR_VEZ = 40


def _desconhecidas(db: Session, limite: int) -> dict[str, list[Expense]]:
    """Lojas em "Outro" que ainda não têm regra, agrupadas por loja.

    O que não é gasto nem sequer se pergunta: não há loja nenhuma do outro lado.
    "CAR WAL CRT DEB REVOL" é a Caixa a mandar 100€ para o Revolut, e a IA — que
    tem de responder com uma categoria de despesa — chamou-lhe "viagens". A
    regra ficou guardada e passou a pintar de viagens cada carregamento."""
    grupos: dict[str, list[Expense]] = defaultdict(list)
    linhas = (
        db.query(Expense)
        .filter(Expense.bank_tx_id.isnot(None), Expense.category == "other",
                Expense.kind.notin_(ek.NAO_E_GASTO))
        .order_by(Expense.date.desc())
        .limit(500)
        .all()
    )
    conhecidas = {r.key for r in db.query(MerchantRule.key).all()}
    for e in linhas:
        k = chave(e.description)
        if k and k not in conhecidas:
            grupos[k].append(e)
    mais_frequentes = sorted(grupos.items(), key=lambda kv: -len(kv[1]))[:limite]
    return dict(mais_frequentes)


def _prompt(grupos: dict[str, list[Expense]]) -> str:
    linhas = []
    for k, despesas in grupos.items():
        exemplo = despesas[0]
        valores = ", ".join(f"{abs(e.amount):.2f}€" for e in despesas[:3])
        linhas.append(f'- "{limpa(exemplo.description)[:50]}" ({len(despesas)}x: {valores})')
    return (
        "Estes são nomes de comerciantes tal como aparecem no extracto bancário de "
        "uma pessoa portuguesa que viajou pela Europa (Polónia, Itália, Grécia, "
        "Holanda, Malta). Classifica cada um numa categoria de despesa.\n\n"
        + "\n".join(linhas)
        + "\n\nCategorias possíveis (usa exactamente estas palavras):\n"
        "food (restaurantes, cafés, take-away), groceries (supermercados), "
        "transport (transportes locais, combustível, táxis), travel (voos, alojamento, "
        "comboios entre cidades), entertainment (cinema, museus, jogos), "
        "nightlife (sair à noite: discotecas, clubes, bares à noite), "
        "subscriptions (serviços mensais), shopping (lojas, roupa, electrónica), "
        "health (farmácia, médico), bills (contas, telecomunicações, renda), "
        "invest (corretoras), other (só quando for mesmo impossível saber).\n\n"
        'Devolve SÓ um JSON: {"nome do comerciante": "categoria", ...}. '
        "Se não souberes, usa \"other\" — não inventes."
    )


def classifica_desconhecidas(db: Session, limite: int = MAX_POR_VEZ) -> dict:
    """Pergunta à IA pelas lojas por classificar e aplica o que ela disser."""
    grupos = _desconhecidas(db, limite)
    if not grupos:
        return {"perguntadas": 0, "aprendidas": 0, "despesas": 0}

    # Aqui o agente vai primeiro, ao contrário do resto: cada resposta vira uma
    # regra permanente (`merchant_rules`), e uma regra errada fica errada para
    # sempre. O modelo local acertou nas lojas óbvias mas mandou a De Lijn
    # (transportes belgas) para "other" — e é uma chamada por dia, portanto não
    # há quota nenhuma a poupar. Fica como rede quando o agente está em baixo.
    import local_ai

    onde = "agente"
    resposta = ask_agent(_prompt(grupos), timeout=120.0, feature="lojas_banco")
    dados = extract_json(resposta) if resposta else None
    if not isinstance(dados, dict):
        onde = "local"
        dados = local_ai.pergunta_json(_prompt(grupos), timeout=180.0)
    if not isinstance(dados, dict):
        logger.warning("classificação de lojas: nem o modelo local nem o agente responderam")
        return {"perguntadas": len(grupos), "aprendidas": 0, "despesas": 0,
                "error": "IA indisponível"}

    # a IA responde com o nome tal como foi mostrado; volta-se à mesma chave
    por_chave = {chave(nome): cat for nome, cat in dados.items() if isinstance(cat, str)}
    aprendidas = tocadas = 0
    for k, despesas in grupos.items():
        cat = (por_chave.get(k) or "").strip().lower()
        if cat not in CATEGORIAS or cat == "other":
            continue
        aprende(despesas[0].description, cat, db, fonte="ia" if onde == "agente" else "ia-local")
        aprendidas += 1
        for e in despesas:
            e.category = cat
            tocadas += 1
    db.commit()
    logger.info("lojas classificadas (%s): %s regras, %s despesas", onde, aprendidas, tocadas)
    return {"perguntadas": len(grupos), "aprendidas": aprendidas, "despesas": tocadas,
            "source": onde}


def aplica_regras(db: Session) -> int:
    """Passa as regras conhecidas às despesas que ainda estão em "Outro"."""
    mudadas = 0
    for e in (db.query(Expense)
              .filter(Expense.bank_tx_id.isnot(None), Expense.category == "other",
                      Expense.kind.notin_(ek.NAO_E_GASTO)).all()):
        cat = categoria_aprendida(e.description, db)
        if cat and cat != "other":
            e.category = cat
            mudadas += 1
    db.commit()
    return mudadas
