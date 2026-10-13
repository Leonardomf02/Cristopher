"""Deals — caça-deals automático.

Crias 'watches' (ex: 'Yamaha MT-07') e de hora a hora as fontes (Vinted, OLX,
Facebook Marketplace) são pesquisadas; a IA iaedu.pt avalia cada anúncio 0-100 e
marca se é mesmo o item pedido (desambiguação de descrições). Notificação = painel na app."""

import json
import logging
import re
import threading
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
import deal_attrs
import deal_criteria
from models import DealWatch, DealResult
import deals_sources as ds
from deals_sources import vinted as vinted_source
from deals_sources import facebook as facebook_source
import deals_ai
import notifier

router = APIRouter(prefix="/api/deals", tags=["Deals"])
logger = logging.getLogger(__name__)

_MAX_VINTED_DETAILS = 15   # nº máx de fetches de descrição Vinted por run (controla 403/volume)
_MAX_FACEBOOK_DETAILS = 10  # idem p/ Facebook (páginas de item ~1MB; FB corta SSR a bursts)
# Candidatos por fonte por passagem. Era 25 — e o OLX tem 738 anúncios para
# "Yamaha MT 07". Pode ser alto porque quem falha uma exigência nem chega a ir
# à IA (ver `fora_por_criterio` em `run_watch`).
_SEARCH_LIMIT = 150
_RERATE_CHUNK = 40         # re-avalia o backlog de pendentes em lotes deste tamanho (commit por lote)

# Controlo de concorrência: um watch só corre 1 scan de cada vez (evita o scheduler
# e o "procurar agora" colidirem no mesmo watch → duplicados/IntegrityError).
_run_lock = threading.Lock()
_running: set[int] = set()


def _try_start(watch_id: int) -> bool:
    with _run_lock:
        if watch_id in _running:
            return False
        _running.add(watch_id)
        return True


def _finish(watch_id: int) -> None:
    with _run_lock:
        _running.discard(watch_id)


def is_scanning(watch_id: int) -> bool:
    with _run_lock:
        return watch_id in _running


# ── Schemas ──────────────────────────────────────────────────────

class DealWatchIn(BaseModel):
    title: str
    query: str
    category: str = ""
    condition: str = "any"           # any | new | used
    sources: str = "all"             # all | csv de: vinted,olx,facebook,web
    max_price: Optional[float] = None
    min_rating: int = 60
    ai_context: str = ""
    exclude_keywords: str = ""
    kind: str = "specific"           # specific | generic
    notify: bool = True
    active: bool = True
    criteria: dict = {}


class DealWatchUpdate(BaseModel):
    title: Optional[str] = None
    query: Optional[str] = None
    category: Optional[str] = None
    condition: Optional[str] = None
    sources: Optional[str] = None
    max_price: Optional[float] = None
    min_rating: Optional[int] = None
    ai_context: Optional[str] = None
    exclude_keywords: Optional[str] = None
    kind: Optional[str] = None
    notify: Optional[bool] = None
    active: Optional[bool] = None
    criteria: Optional[dict] = None


class DealWatchOut(BaseModel):
    id: int
    title: str
    query: str
    category: str
    condition: str
    sources: str
    max_price: Optional[float]
    min_rating: int
    ai_context: str
    exclude_keywords: str
    criteria: dict = {}
    kind: str = "specific"
    notify: bool = True
    active: bool
    last_checked_at: Optional[datetime]
    new_count: int = 0          # nº de deals bons por ver
    total_count: int = 0        # nº de matches reais (match=true E já avaliados pela IA)
    pending_count: int = 0      # nº de anúncios ainda por avaliar (sem rating)
    gone_count: int = 0         # nº de anúncios que já não estão à venda
    scanning: bool = False      # True enquanto um scan está a correr

    class Config:
        from_attributes = True


class DealResultOut(BaseModel):
    id: int
    watch_id: int
    source: str
    title: str
    description: str
    price: Optional[float]
    currency: str
    condition: str
    url: str
    image_url: str
    location: str
    seller: str
    ai_rating: Optional[int]
    ai_match: bool
    ai_reason: str
    status: str
    first_seen_at: Optional[datetime]
    last_seen_at: Optional[datetime]
    gone_at: Optional[datetime] = None
    reappeared_at: Optional[datetime] = None
    price_percentile: Optional[int] = None    # 0-100 face ao histórico deste watch
    vs_median: Optional[float] = None         # € abaixo (negativo) ou acima da mediana
    attrs: dict = {}                          # ano/km/potência/cor lidos do anúncio
    checks: list = []                         # critério a critério: cumpre/não cumpre/não diz
    verdict: str = ""                         # ok | fail | unknown
    fair_price: Optional[float] = None        # quanto vale uma como esta
    fair_basis: str = ""                      # com que amostra se chegou lá
    vs_fair: Optional[float] = None           # € acima (+) ou abaixo (−) do justo

    class Config:
        from_attributes = True


class ResultPatch(BaseModel):
    status: str   # seen | saved | dismissed | new


# ── Helpers ──────────────────────────────────────────────────────

def _le_criterios(w: DealWatch) -> dict:
    try:
        return json.loads(w.criteria_json) if w.criteria_json else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _watch_to_out(db: Session, w: DealWatch) -> DealWatchOut:
    out = DealWatchOut.model_validate(w)
    out.criteria = _le_criterios(w)
    out.new_count = (
        db.query(DealResult)
        .filter(
            DealResult.watch_id == w.id,
            DealResult.status == "new",
            DealResult.ai_match == True,  # noqa: E712
            DealResult.ai_rating >= w.min_rating,
        )
        .count()
    )
    out.total_count = (
        db.query(DealResult)
        .filter(
            DealResult.watch_id == w.id,
            DealResult.ai_match == True,  # noqa: E712
            DealResult.ai_rating.isnot(None),   # pendentes (ainda sem rating) NÃO contam como match
            DealResult.status != "gone",
        )
        .count()
    )
    out.pending_count = (
        db.query(DealResult)
        .filter(DealResult.watch_id == w.id, DealResult.ai_rating.is_(None),
                DealResult.status != "gone")
        .count()
    )
    out.gone_count = (
        db.query(DealResult)
        .filter(DealResult.watch_id == w.id, DealResult.status == "gone")
        .count()
    )
    out.scanning = is_scanning(w.id)
    return out


def _excluded(title: str, exclude_keywords: str) -> bool:
    words = [w.strip().lower() for w in (exclude_keywords or "").split(",") if w.strip()]
    t = (title or "").lower()
    return any(w in t for w in words)


def _attrs_do_anuncio(lst, descricao: str = "") -> dict:
    """O que a fonte deu em campos manda; o texto só preenche o que faltar.

    Era um `lst.attrs or extrai(...)`, tudo-ou-nada: o OLX dá ano, km e cor mas
    quase nunca a potência, e assim um anúncio que trazia três dos quatro ficava
    sem o quarto — nem sequer se olhava para o texto para o encontrar."""
    lidos = deal_attrs.extrai(lst.title, descricao or lst.description or "")
    for chave, valor in (lst.attrs or {}).items():
        if valor is not None:
            lidos[chave] = valor
    return lidos


def _relevant(title: str, description: str, query: str) -> bool:
    """Pré-filtro barato (sem IA): pelo menos um token significativo (≥3 letras) da
    query tem de aparecer no título/descrição. Corta lixo cross-categoria (ex: um
    Samsung que a pesquisa solta da Vinted devolveu para 'iphone 17') antes de
    gastar chamadas de IA e antes de gravar. Se a query não tiver tokens ≥3, deixa passar."""
    toks = [t for t in re.split(r"\W+", (query or "").lower()) if len(t) >= 3]
    if not toks:
        return True
    hay = f"{title} {description}".lower()
    return any(t in hay for t in toks)


# Ver fotos custa ~5s cada no modelo local. Não é caro, mas também não se fazem
# 780 de uma vez: só as que podem vir a interessar, e um lote por passagem.
_MAX_FOTOS_POR_RUN = 30


def _completa_cor_pela_foto(rows, criterios: dict, db: Session) -> int:
    """A cor é a única exigência dele que o texto nunca responde: de 780 anúncios,
    zero dizem a cor. A foto responde sempre — ver `deal_vision`."""
    if not (criterios or {}).get("colors"):
        return 0
    import deal_vision
    import local_ai
    if not local_ai.disponivel():
        return 0
    feitas = 0
    for r in rows:
        if feitas >= _MAX_FOTOS_POR_RUN:
            break
        if r.attr_color or r.attr_color_src == "foto":
            continue                     # já se sabe, ou já se tentou e não deu
        cor, viu = deal_vision.cor_do_anuncio(r.image_url or "", source=r.source,
                                              external_id=r.external_id)
        if not viu:
            continue          # a foto não veio: fica por tentar, não por respondida
        r.attr_color_src = "foto"
        if cor:
            r.attr_color = cor
        feitas += 1
    if feitas:
        db.commit()
    return feitas


def _watch_dict(watch: DealWatch) -> dict:
    return {
        "id": watch.id, "title": watch.title, "query": watch.query,
        "category": watch.category, "condition": watch.condition,
        "max_price": watch.max_price, "ai_context": watch.ai_context,
        "exclude_keywords": watch.exclude_keywords,
        "kind": watch.kind or "specific",
        "criteria": _le_criterios(watch),
    }


def _rerate_backlog(watch: DealWatch, watch_dict: dict, db: Session) -> int:
    """Re-avalia TODO o backlog deste watch sem rating (deste run + de runs antigos
    com rate limit), em lotes, commitando cada um — o backlog esvazia mesmo quando é
    grande e o frontend vê o progresso no poll. Pára se um lote não recuperar nada
    (IA mesmo em rate limit): evita loop infinito e poupa quota. Devolve nº avaliados."""
    total = 0
    while True:
        batch = (
            db.query(DealResult)
            .filter(DealResult.watch_id == watch.id, DealResult.ai_rating.is_(None))
            .limit(_RERATE_CHUNK)
            .all()
        )
        if not batch:
            break
        rated = 0
        for row, rate in zip(batch, deals_ai.rate_listings(watch_dict, batch)):
            if rate["rating"] is not None:
                row.ai_rating = rate["rating"]
                row.ai_match = rate["match"]
                row.ai_reason = rate["reason"]
                rated += 1
        db.commit()
        total += rated
        if rated == 0:   # IA não devolveu nada (rate limit real) → não insistir
            break
    return total


def run_watch(watch: DealWatch, db: Session) -> int:
    """Pesquisa as fontes, dedupe, busca descrições novas, avalia com IA e grava.
    Devolve o nº de deals bons novos (match & rating>=min_rating)."""
    listings = ds.search_all(
        watch.query,
        watch.sources,
        max_price=watch.max_price,
        condition=watch.condition,
        limit=_SEARCH_LIMIT,
        # O Facebook só dá 24 por pesquisa e não pagina: perguntar de várias
        # maneiras é a única forma de ver mais do que isso.
        extra_queries=deal_criteria.pesquisas_alternativas(
            watch.query, _le_criterios(watch)),
    )

    # dedupe vs existentes deste watch
    existing = {
        (r.source, r.external_id): r
        for r in db.query(DealResult).filter(DealResult.watch_id == watch.id).all()
    }

    new_listings = []
    seen_new: set = set()
    for lst in listings:
        if _excluded(lst.title, watch.exclude_keywords):
            continue
        if (watch.kind or "specific") != "generic" and not _relevant(lst.title, lst.description, watch.query):
            continue
        key = (lst.source, lst.external_id)
        if key in existing:
            row = existing[key]
            row.last_seen_at = datetime.utcnow()
            # Reler ano/km/potência de cada vez: são gravados na criação, e quando
            # a leitura melhora (ou a fonte se corrige) as linhas antigas ficavam
            # com o valor velho. Uma MT-07 limitada a 35 kW ficou marcada 55 kW
            # porque a linha já existia quando isso foi corrigido.
            frescos = _attrs_do_anuncio(lst, lst.description or row.description or "")
            row.attr_year = frescos["year"]
            row.attr_km = frescos["km"]
            row.attr_power_kw = frescos["power_kw"]
            if lst.image_url:
                row.image_url = lst.image_url        # os URLs de imagem caducam
            row.attr_color = frescos["color"] or row.attr_color
            if frescos["color"]:
                row.attr_color_src = "texto"
            if lst.price is not None:
                # Guarda o preço anterior para se poder avisar quando um anúncio baixa.
                if row.price is not None and abs(row.price - lst.price) >= 0.01:
                    row.previous_price = row.price
                    row.price_changed_at = datetime.utcnow()
                row.price = lst.price
            continue
        if key in seen_new:   # mesma fonte pode devolver o mesmo item 2x no mesmo run
            continue
        seen_new.add(key)
        new_listings.append(lst)

    # descrições só para os novos (cap p/ limitar 403/volume). Vinted: acrescenta à
    # hint de modelo (item_box) — o detalhe dá 403 com frequência (Datadome), por
    # isso é best-effort e a hint da pesquisa garante sempre algo para a IA avaliar.
    # Facebook: a pesquisa não traz descrição nenhuma, o detalhe é a única fonte
    # (é aí que se apanham os "iPhone 11 — ler descrição: ecrã partido").
    fetched = 0
    fetched_fb = 0
    for lst in new_listings:
        if lst.source == "vinted" and fetched < _MAX_VINTED_DETAILS:
            detail = vinted_source.fetch_description(lst.external_id)
            if detail:
                lst.description = (lst.description + "\n" + detail).strip() if lst.description else detail
            fetched += 1
        elif lst.source == "facebook" and fetched_fb < _MAX_FACEBOOK_DETAILS:
            detail = facebook_source.fetch_description(lst.external_id)
            if detail:
                lst.description = detail
            fetched_fb += 1

    watch_dict = _watch_dict(watch)

    # Avaliação IA — só do que tem hipótese de valer a pena.
    #
    # Foram 914 anúncios avaliados pela IA em oito semanas (696 com nota abaixo de
    # 40) e nem um foi guardado. É o mesmo agente que serve o Perguntar, o
    # rascunho do diário e os sinais de investimento, e que anda a devolver 429.
    # Quando já se sabe quanto a coisa costuma custar, o que está muito acima
    # disso não precisa de IA nenhuma para se saber que não é um achado.
    import ai_budget

    historico = _precos_do_watch(db, watch.id)

    # Quem já falha uma exigência não vai à IA: pedir-lhe para avaliar uma mota
    # de 2016 quando ele quer 2021-2024 é gastar quota para confirmar o que uma
    # regra já sabe. É isto que deixa a app procurar 150 anúncios em vez de 25.
    criterios_watch = _le_criterios(watch)
    fora_por_criterio: dict[int, str] = {}
    if criterios_watch:
        restantes = []
        for lst in new_listings:
            avaliacao = deal_criteria.avalia(lst.title, lst.description or "",
                                             lst.price, criterios_watch,
                                             attrs=_attrs_do_anuncio(lst))
            # Só se salta a IA quando o que falha é um atributo do próprio
            # veículo (ano, km, potência): isso prova que É um veículo. Um par de
            # piscas LED "falhava a cor" e ia parar à lista como se fosse a mota
            # — quem decide se aquilo é o produto continua a ser a IA.
            prova_que_e_o_produto = {"Ano", "Quilómetros", "Potência"} & set(avaliacao["failed"])
            if avaliacao["verdict"] == deal_criteria.FALHA and prova_que_e_o_produto:
                fora_por_criterio[id(lst)] = "não cumpre: " + ", ".join(avaliacao["failed"])
            else:
                restantes.append(lst)
        if fora_por_criterio:
            logger.info("deals: %s anúncios falham as exigências e não foram à IA",
                        len(fora_por_criterio))
        candidatos_ia = restantes
    else:
        candidatos_ia = new_listings

    para_ia, de_lado = _separa_por_preco(candidatos_ia, historico, watch)
    if para_ia and not ai_budget.permitido("deals"):
        # Sem quota hoje: os anúncios ficam guardados sem nota e são avaliados na
        # próxima passagem. Antes disto, uma pesquisa com 200 anúncios novos
        # deixava o Perguntar e o diário sem IA o resto do dia.
        logger.info("deals: tecto de IA atingido, %s anúncios ficam por avaliar", len(para_ia))
        de_lado = list(new_listings)
        para_ia = []
    ratings_ia = deals_ai.rate_listings(watch_dict, para_ia) if para_ia else []
    por_anuncio = dict(zip((id(x) for x in para_ia), ratings_ia))
    por_avaliar = (
        "sem quota de IA hoje — fica para a próxima passagem" if not para_ia and de_lado
        else f"acima do preço habitual (mediana {_quantil(historico, 0.5):.0f}€) — não foi à IA"
    )
    ratings = []
    for lst in new_listings:
        motivo = fora_por_criterio.get(id(lst))
        if motivo:
            # Guardado e visível em "Não cumprem", mas sem gastar IA: continua a
            # contar para o preço de mercado (é o mesmo produto, só não serve).
            ratings.append({"rating": 0, "match": True, "reason": motivo})
        else:
            ratings.append(por_anuncio.get(
                id(lst), {"rating": None, "match": None, "reason": por_avaliar}))
    if de_lado:
        logger.info("deals: %s anúncios caros não foram à IA (%s foram)", len(de_lado), len(para_ia))

    good_new = 0
    for lst, rate in zip(new_listings, ratings):
        # A fonte manda: o StandVirtual e o OLX dão ano/km/cor em campos, e isso
        # vale mais do que o que se adivinha do texto.
        attrs = _attrs_do_anuncio(lst)
        row = DealResult(
            watch_id=watch.id,
            source=lst.source,
            external_id=lst.external_id,
            title=lst.title,
            description=lst.description or "",
            price=lst.price,
            currency=lst.currency,
            condition=lst.condition,
            url=lst.url,
            image_url=lst.image_url,
            location=lst.location,
            seller=lst.seller,
            ai_rating=rate["rating"],
            ai_match=rate["match"],
            ai_reason=rate["reason"],
            status="new",
            attr_year=attrs["year"],
            attr_km=attrs["km"],
            attr_power_kw=attrs["power_kw"],
            attr_color=attrs["color"],
            attr_color_src="texto" if attrs["color"] else None,
        )
        db.add(row)
        if rate["match"] and rate["rating"] is not None and rate["rating"] >= watch.min_rating:
            good_new += 1
    db.commit()

    # esvazia o backlog: avalia TUDO o que ficou sem rating (novos que a IA falhou +
    # pendentes de runs anteriores com rate limit). Antes só re-avaliava 40/run e o
    # backlog crescia mais depressa do que esvaziava → ficava tudo "por avaliar".
    _rerate_backlog(watch, watch_dict, db)

    _arquiva_desaparecidos(watch, db, {(l.source, l.external_id) for l in listings})

    # A cor só se vai ver na foto depois de tudo o resto: a quem já falha o ano
    # ou os quilómetros não vale a pena olhar para a cor.
    criterios = _le_criterios(watch)
    if criterios.get("colors"):
        candidatos = [
            r for r in db.query(DealResult).filter(
                DealResult.watch_id == watch.id,
                DealResult.status != "gone",
                DealResult.ai_match == True,          # noqa: E712
            ).all()
            if deal_criteria.avalia(r.title, r.description or "", r.price,
                                    {k: v for k, v in criterios.items() if k != "colors"},
                                    attrs=_atributos(r))["verdict"] != deal_criteria.FALHA
        ]
        vistas = _completa_cor_pela_foto(candidatos, criterios, db)
        if vistas:
            logger.info("deals: %s fotos vistas para saber a cor", vistas)

    watch.last_checked_at = datetime.utcnow()
    db.commit()

    if watch.notify:
        _avisa_achados(watch, db)
    return good_new


DIAS_ATE_SUMIR = 10        # sem aparecer nas fontes durante este tempo → foi-se
_MAX_VERIFICACOES_FB = 25  # páginas de item que se abrem por passagem para confirmar


def _arquiva_desaparecidos(watch: DealWatch, db: Session, visto_agora: set) -> int:
    """Marca como desaparecidos os anúncios que já não vêm nas pesquisas.

    Sem isto a lista era um cemitério: 908 anúncios guardados, 856 sem aparecer há
    mais de duas semanas, e o contador de "novos" a contar coisas já vendidas."""
    limite = datetime.utcnow() - timedelta(days=DIAS_ATE_SUMIR)
    sumiram = 0
    verificados = [0]
    for r in db.query(DealResult).filter(DealResult.watch_id == watch.id).all():
        chave = (r.source, r.external_id)
        if chave in visto_agora:
            if r.status == "gone":                      # ressuscitou
                r.status = "new"
                r.reappeared_at = datetime.utcnow()
                r.gone_at = None
            continue
        if r.status in ("gone", "saved"):
            continue
        if (r.last_seen_at or datetime.min) < limite:
            # No Facebook não se pode concluir nada de um anúncio não aparecer:
            # a pesquisa dá 24 resultados e não pagina, por isso quase tudo sai
            # da vista em dias. Antes de o dar como ido, vai-se lá ver.
            if r.source == "facebook" and verificados[0] < _MAX_VERIFICACOES_FB:
                verificados[0] += 1
                vivo = facebook_source.esta_vivo(r.external_id)
                if vivo:
                    r.last_seen_at = datetime.utcnow()
                    continue
                if vivo is None:
                    continue          # não se sabe: fica como está
            r.status = "gone"
            r.gone_at = datetime.utcnow()
            sumiram += 1
    db.commit()
    return sumiram


# Um anúncio bom a preço normal não é um achado — é só um anúncio. Só se avisa
# quando o preço está no fundo do que já se viu para aquela coisa.
PERCENTIL_DE_ACHADO = 25


def _avisa_achados(watch: DealWatch, db: Session) -> None:
    """Avisa (balão do macOS / Telegram) quando aparece um achado bom ou uma baixa
    de preço. Sem isto, os deals só apareciam a quem se lembrasse de abrir o ecrã."""
    novos = (
        db.query(DealResult)
        .filter(
            DealResult.watch_id == watch.id,
            DealResult.status == "new",
            DealResult.ai_match == True,  # noqa: E712
            DealResult.ai_rating >= watch.min_rating,
        )
        .order_by(DealResult.ai_rating.desc())
        .all()
    )

    # Com histórico suficiente, o preço manda: 154 anúncios foram dados como bons
    # e nenhum chegou a ser decidido, porque "bom" sem preço de referência não
    # queria dizer nada. Sem histórico fica tudo, como dantes.
    historico = _precos_do_watch(db, watch.id)
    if len(historico) >= 8:
        baratos = []
        for r in novos:
            p = _percentil(float(r.price), historico) if r.price else None
            if p is not None and p <= PERCENTIL_DE_ACHADO:
                baratos.append(r)
        novos = baratos
    baixas = (
        db.query(DealResult)
        .filter(
            DealResult.watch_id == watch.id,
            DealResult.previous_price.isnot(None),
            DealResult.price_changed_at >= datetime.utcnow() - timedelta(hours=24),
            DealResult.ai_match == True,  # noqa: E712
        )
        .all()
    )
    baixas = [b for b in baixas if b.price is not None and b.previous_price and b.price < b.previous_price]

    if not novos and not baixas:
        return

    mediana = _quantil(historico, 0.5) if len(historico) >= 8 else None
    linhas = []
    for r in novos[:3]:
        preco = f"{r.price:.0f}€" if r.price is not None else "?"
        barato = (f" — {mediana - r.price:.0f}€ abaixo do costume"
                  if mediana and r.price and r.price < mediana else "")
        linhas.append(f"{preco} · {r.title[:60]} ({r.ai_rating}/100){barato}")
    for r in baixas[:2]:
        desconto = r.previous_price - r.price
        linhas.append(f"baixou {desconto:.0f}€ → {r.price:.0f}€ · {r.title[:50]}")

    extra = len(novos) - 3
    if extra > 0:
        linhas.append(f"+{extra} outros")

    try:
        notifier.notify(
            f"Deals · {watch.title}",
            "\n".join(linhas),
            severity="info",
        )
    except Exception as ex:  # noqa: BLE001 — um aviso não pode derrubar o scan
        logger.warning("aviso de deals falhou: %s", ex)


def _scan_now(watch_id: int) -> int:
    """Scan síncrono de 1 watch, em sessão própria. Assume o lock já adquirido."""
    db = SessionLocal()
    try:
        w = db.get(DealWatch, watch_id)
        return run_watch(w, db) if w else 0
    finally:
        db.close()


def start_scan(watch_id: int) -> bool:
    """Arranca um scan em background (thread). Devolve False se já estava a correr."""
    if not _try_start(watch_id):
        return False

    def _job():
        try:
            _scan_now(watch_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("scan %s falhou: %s", watch_id, e)
        finally:
            _finish(watch_id)

    threading.Thread(target=_job, daemon=True).start()
    return True


def run_all_watches() -> int:
    """Corre todos os watches activos (sequencial). Usado pelo scheduler.
    Respeita o lock por watch: se houver um scan manual a correr, salta esse desta vez."""
    db = SessionLocal()
    try:
        ids = [w.id for w in db.query(DealWatch).filter(DealWatch.active == True).all()]  # noqa: E712
    finally:
        db.close()
    total = 0
    for wid in ids:
        if not _try_start(wid):
            continue
        try:
            total += _scan_now(wid)
        except Exception as e:  # noqa: BLE001 — um watch não pode derrubar o scan
            logger.warning("scan %s falhou: %s", wid, e)
        finally:
            _finish(wid)
    return total


# ── Watches CRUD ─────────────────────────────────────────────────

@router.get("/watches", response_model=list[DealWatchOut])
def list_watches(db: Session = Depends(get_db)):
    watches = db.query(DealWatch).order_by(DealWatch.created_at.desc()).all()
    return [_watch_to_out(db, w) for w in watches]


@router.post("/watches", response_model=DealWatchOut)
def create_watch(data: DealWatchIn, db: Session = Depends(get_db)):
    campos = data.model_dump()
    criterios = campos.pop("criteria", {}) or {}
    w = DealWatch(**campos, criteria_json=json.dumps(criterios, ensure_ascii=False))
    db.add(w)
    db.commit()
    db.refresh(w)
    if w.active:
        start_scan(w.id)   # 1ª pesquisa arranca já em background
    return _watch_to_out(db, w)


@router.patch("/watches/{watch_id}", response_model=DealWatchOut)
def update_watch(watch_id: int, data: DealWatchUpdate, db: Session = Depends(get_db)):
    w = db.query(DealWatch).filter(DealWatch.id == watch_id).first()
    if not w:
        raise HTTPException(status_code=404, detail="Watch não encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        if k == "criteria":
            w.criteria_json = json.dumps(v or {}, ensure_ascii=False)
        else:
            setattr(w, k, v)
    db.commit()
    db.refresh(w)
    return _watch_to_out(db, w)


@router.delete("/watches/{watch_id}")
def delete_watch(watch_id: int, db: Session = Depends(get_db)):
    w = db.query(DealWatch).filter(DealWatch.id == watch_id).first()
    if not w:
        raise HTTPException(status_code=404, detail="Watch não encontrado")
    db.query(DealResult).filter(DealResult.watch_id == watch_id).delete()
    db.delete(w)
    db.commit()
    return {"ok": True}


@router.post("/watches/{watch_id}/run", response_model=DealWatchOut)
def run_now(watch_id: int, db: Session = Depends(get_db)):
    """Arranca um scan em background e devolve já (scanning=True). O frontend faz
    poll até `scanning` ficar False. Não bloqueia ~min à espera da IA + fontes."""
    w = db.query(DealWatch).filter(DealWatch.id == watch_id).first()
    if not w:
        raise HTTPException(status_code=404, detail="Watch não encontrado")
    start_scan(watch_id)   # no-op se já estiver a correr
    return _watch_to_out(db, w)


# ── Preço justo ──────────────────────────────────────────────────
# Ao fim de meses a apanhar anúncios, a app já sabe quanto a coisa costuma custar.
# Um preço sozinho não diz nada; comparado com a distribuição do que se viu, diz
# tudo. Só entram anúncios que a IA validou como sendo mesmo o produto.

def _precos_do_watch(db: Session, watch_id: int, dias: Optional[int] = None) -> list[float]:
    q = db.query(DealResult.price).filter(
        DealResult.watch_id == watch_id,
        DealResult.ai_match == True,  # noqa: E712
        DealResult.price.isnot(None),
        DealResult.price > 0,
    )
    if dias:
        q = q.filter(DealResult.first_seen_at >= datetime.utcnow() - timedelta(days=dias))
    return sorted(float(p[0]) for p in q.all())


# Acima deste percentil do que já se viu, o anúncio não vai à IA: nunca seria um
# achado. Fica guardado à mesma, só sem nota.
PERCENTIL_MAXIMO_PARA_IA = 70
# Sem histórico que chegue, avalia-se tudo — é assim que o histórico se faz.
MINIMO_HISTORICO = 12


def _separa_por_preco(listings: list, historico: list[float], watch) -> tuple[list, list]:
    """(vai à IA, fica de lado). Sem preço vai sempre: não se pode julgar."""
    if len(historico) < MINIMO_HISTORICO:
        return list(listings), []
    tecto = _quantil(historico, PERCENTIL_MAXIMO_PARA_IA / 100)
    # O tecto que ele pediu manda sobre o histórico, se for mais apertado.
    if watch is not None and getattr(watch, "max_price", None):
        tecto = min(tecto, float(watch.max_price))
    vao, ficam = [], []
    for lst in listings:
        preco = getattr(lst, "price", None)
        (vao if preco is None or preco <= tecto else ficam).append(lst)
    return vao, ficam


def _percentil(valor: float, ordenados: list[float]) -> Optional[int]:
    if len(ordenados) < 8:
        return None
    abaixo = sum(1 for p in ordenados if p < valor)
    return int(round(abaixo / len(ordenados) * 100))


def _quantil(ordenados: list[float], q: float) -> float:
    if not ordenados:
        return 0.0
    i = max(0, min(len(ordenados) - 1, int(round(q * (len(ordenados) - 1)))))
    return round(ordenados[i], 2)


@router.get("/watches/{watch_id}/price-stats")
def price_stats(watch_id: int, days: Optional[int] = Query(None, ge=7, le=1825), db: Session = Depends(get_db)):
    precos = _precos_do_watch(db, watch_id, days)
    if len(precos) < 8:
        return {"watch_id": watch_id, "count": len(precos), "enough": False}

    # mediana mês a mês: mostra se o mercado está a subir ou a descer
    por_mes: dict[str, list[float]] = {}
    for r in (
        db.query(DealResult.price, DealResult.first_seen_at)
        .filter(DealResult.watch_id == watch_id, DealResult.ai_match == True,  # noqa: E712
                DealResult.price.isnot(None), DealResult.price > 0).all()
    ):
        if not r[1]:
            continue
        por_mes.setdefault(r[1].strftime("%Y-%m"), []).append(float(r[0]))
    meses = [
        {"month": m, "median": _quantil(sorted(v), 0.5), "count": len(v)}
        for m, v in sorted(por_mes.items())
    ]

    return {
        "watch_id": watch_id,
        "count": len(precos),
        "enough": True,
        "min": round(precos[0], 2),
        "p10": _quantil(precos, 0.10),
        "p25": _quantil(precos, 0.25),
        "median": _quantil(precos, 0.50),
        "p75": _quantil(precos, 0.75),
        "p90": _quantil(precos, 0.90),
        "max": round(precos[-1], 2),
        "months": meses,
    }


@router.post("/prune")
def prune(days: int = Query(DIAS_ATE_SUMIR, ge=2, le=90), db: Session = Depends(get_db)):
    """Arruma o que já não está à venda. Corre sozinho todos os dias, e também
    limpa o histórico de uma vez (havia 856 anúncios mortos na lista)."""
    limite = datetime.utcnow() - timedelta(days=days)
    n = 0
    for r in (
        db.query(DealResult)
        .filter(DealResult.status.notin_(["gone", "saved"]), DealResult.last_seen_at < limite)
        .all()
    ):
        r.status = "gone"
        r.gone_at = r.gone_at or datetime.utcnow()
        n += 1
    db.commit()
    return {"archived": n, "days": days}


# ── Results ──────────────────────────────────────────────────────

@router.get("/results", response_model=list[DealResultOut])
def list_results(
    watch_id: int = Query(...),
    status: Optional[str] = Query(None),     # new | seen | saved | dismissed | gone
    include_unmatched: bool = Query(False),
    include_gone: bool = Query(False),
    include_failed: bool = Query(False),      # os que falham uma exigência
    db: Session = Depends(get_db),
):
    q = db.query(DealResult).filter(DealResult.watch_id == watch_id)
    if not include_unmatched:
        q = q.filter(DealResult.ai_match == True)  # noqa: E712
    if status:
        q = q.filter(DealResult.status == status)
    elif not include_gone:
        q = q.filter(DealResult.status != "gone")   # já não está à venda
    # melhores primeiro: match, depois rating desc, depois mais recentes
    rows = q.all()
    rows.sort(key=lambda r: (
        r.ai_match,
        r.ai_rating if r.ai_rating is not None else -1,
        r.first_seen_at or datetime.min,
    ), reverse=True)

    historico = _precos_do_watch(db, watch_id)
    mediana = _quantil(historico, 0.5) if len(historico) >= 8 else None
    watch = db.query(DealWatch).filter(DealWatch.id == watch_id).first()
    criterios = _le_criterios(watch) if watch else {}
    comparaveis = _comparaveis(db, watch_id)
    saida = []
    for r in rows:
        out = DealResultOut.model_validate(r)
        if r.price and mediana:
            out.price_percentile = _percentil(float(r.price), historico)
            out.vs_median = round(float(r.price) - mediana, 2)
        _enriquece(out, r, criterios, comparaveis)
        saida.append(out)
    # O que falha uma exigência sai da lista: pedir 2021-2024 e continuar a ver
    # uma de 2016 no topo é o mesmo que não ter pedido nada. Fica atrás do
    # filtro "não cumprem", porque apagar também não é resposta.
    # O "não diz" **fica**: o vendedor não ter escrito os quilómetros não faz do
    # anúncio um anúncio errado.
    if not include_failed:
        saida = [o for o in saida if o.verdict != deal_criteria.FALHA]
    ordem = {deal_criteria.CUMPRE: 0, deal_criteria.NAO_DIZ: 1, deal_criteria.FALHA: 2}
    saida.sort(key=lambda o: ordem.get(o.verdict, 1))
    return saida


# ── Preço justo e critérios ──────────────────────────────────────
# A "mediana do costume" era a mediana de TUDO o que a pesquisa trouxe: para a
# MT-07 isso incluía MT-09, MT-10 e um suporte de alumínio de 20€, de 1€ a
# 8.990€. Dizia que uma de 2016 a 5.600€ estava "900€ abaixo do costume" quando
# está 400€ ACIMA do que vale uma de 2016.

def _comparaveis(db: Session, watch_id: int) -> list[dict]:
    """As que servem de referência de preço: mesmo produto, com preço e com ano.

    Repara que **não** se filtra pelas exigências dele. O preço de mercado de uma
    MT-07 de 2016 conta para saber quanto vale uma MT-07 de 2016, mesmo que ele
    só queira de 2021 para cima — senão a amostra encolhia até não dizer nada."""
    linhas = (
        db.query(DealResult.price, DealResult.attr_year, DealResult.attr_km)
        .filter(DealResult.watch_id == watch_id,
                DealResult.ai_match == True,  # noqa: E712
                DealResult.price.isnot(None), DealResult.price > 0)
        .all()
    )
    return [{"price": float(p), "year": a, "km": k} for p, a, k in linhas]


def _atributos(r: DealResult) -> dict:
    """Os do anúncio. Lê do texto se ainda não estiverem gravados (linhas antigas)."""
    if r.attr_year or r.attr_km or r.attr_power_kw or r.attr_color:
        return {"year": r.attr_year, "km": r.attr_km,
                "power_kw": r.attr_power_kw, "color": r.attr_color,
                "color_src": r.attr_color_src}
    return deal_attrs.extrai(r.title, r.description or "")


def _enriquece(out, r: DealResult, criterios: dict, comparaveis: list[dict]) -> None:
    avaliacao = deal_criteria.avalia(r.title, r.description or "", r.price, criterios,
                                     attrs=_atributos(r))
    out.attrs = avaliacao["attrs"]
    out.checks = avaliacao["checks"]
    out.verdict = avaliacao["verdict"]
    justo = deal_criteria.preco_justo(comparaveis, avaliacao["attrs"])
    if justo and r.price:
        out.fair_price = justo["fair"]
        out.fair_basis = justo["basis"]
        out.vs_fair = round(float(r.price) - justo["fair"], 2)



@router.patch("/results/{result_id}", response_model=DealResultOut)
def patch_result(result_id: int, data: ResultPatch, db: Session = Depends(get_db)):
    r = db.query(DealResult).filter(DealResult.id == result_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Resultado não encontrado")
    if data.status not in ("new", "seen", "saved", "dismissed"):
        raise HTTPException(status_code=400, detail="status inválido")
    r.status = data.status
    db.commit()
    db.refresh(r)
    return r


# ── Triagem ──────────────────────────────────────────────────────
# 914 anúncios encontrados, 154 dados como bons, zero decididos e 869 já
# desaparecidos: o caça-deals encontrava e ninguém dizia que achava. Sem
# decisões, a app nunca aprende o que ele quer nem consegue medir se acerta.

class TriagemAccao(BaseModel):
    saved: list[int] = []
    dismissed: list[int] = []


@router.get("/triage")
def triage(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    """Os anúncios que valem uma decisão: ainda à venda, mesmo produto, bem
    avaliados e — havendo histórico — baratos face ao que já se viu."""
    saida = []
    for w in db.query(DealWatch).filter(DealWatch.active == True).all():  # noqa: E712
        historico = _precos_do_watch(db, w.id)
        mediana = _quantil(historico, 0.5) if len(historico) >= 8 else None
        criterios = _le_criterios(w)
        comparaveis = _comparaveis(db, w.id)
        candidatos = (
            db.query(DealResult)
            .filter(
                DealResult.watch_id == w.id,
                DealResult.status.in_(("new", "seen")),
                DealResult.ai_match == True,  # noqa: E712
                DealResult.ai_rating >= w.min_rating,
            )
            .all()
        )
        for r in candidatos:
            pct = _percentil(float(r.price), historico) if (r.price and historico) else None
            avaliacao = deal_criteria.avalia(r.title, r.description or "", r.price, criterios)
            if avaliacao["verdict"] == deal_criteria.FALHA:
                continue          # não se pede decisão sobre o que ele já disse que não quer
            justo = deal_criteria.preco_justo(comparaveis, avaliacao["attrs"])
            saida.append({
                "attrs": avaliacao["attrs"],
                "checks": avaliacao["checks"],
                "verdict": avaliacao["verdict"],
                "fair_price": justo["fair"] if justo else None,
                "fair_basis": justo["basis"] if justo else "",
                "vs_fair": round(float(r.price) - justo["fair"], 2) if (justo and r.price) else None,
                "id": r.id, "watch_id": w.id, "watch_title": w.title,
                "title": r.title, "price": r.price, "currency": r.currency,
                "url": r.url, "image_url": r.image_url, "location": r.location,
                "source": r.source, "condition": r.condition,
                "ai_rating": r.ai_rating, "ai_reason": r.ai_reason,
                "status": r.status,
                "price_percentile": pct,
                "vs_median": round(float(r.price) - mediana, 2) if (r.price and mediana) else None,
                "first_seen_at": r.first_seen_at.isoformat() if r.first_seen_at else None,
            })

    # Primeiro os baratos (percentil baixo), depois os bem avaliados. Sem
    # histórico o percentil vem a None e vale como "a meio".
    saida.sort(key=lambda d: (d["price_percentile"] if d["price_percentile"] is not None else 50,
                              -(d["ai_rating"] or 0)))
    return {"pending": len(saida), "items": saida[:limit]}


@router.post("/triage")
def triage_apply(accao: TriagemAccao, db: Session = Depends(get_db)):
    """Guarda/descarta vários de uma vez — a triagem só acontece se for rápida."""
    feitos = 0
    for ids, estado in ((accao.saved, "saved"), (accao.dismissed, "dismissed")):
        if not ids:
            continue
        feitos += (
            db.query(DealResult)
            .filter(DealResult.id.in_(ids))
            .update({DealResult.status: estado}, synchronize_session=False)
        )
    db.commit()
    return {"ok": True, "updated": feitos}


@router.post("/results/mark-seen")
def mark_all_seen(watch_id: int = Query(...), db: Session = Depends(get_db)):
    db.query(DealResult).filter(
        DealResult.watch_id == watch_id, DealResult.status == "new"
    ).update({DealResult.status: "seen"})
    db.commit()
    return {"ok": True}


# ── Summary (badge do nav) ───────────────────────────────────────

@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    watches = db.query(DealWatch).filter(DealWatch.active == True).all()  # noqa: E712
    total_new = 0
    for w in watches:
        total_new += (
            db.query(DealResult)
            .filter(
                DealResult.watch_id == w.id,
                DealResult.status == "new",
                DealResult.ai_match == True,  # noqa: E712
                DealResult.ai_rating >= w.min_rating,
            )
            .count()
        )
    from ai_config import ai_status
    return {"new_count": total_new, "watch_count": len(watches), "ai": ai_status()}


@router.post("/ai-check")
def ai_check():
    """Sonda a IA agora (1 chamada) e devolve o estado. Para o botão 'Verificar agora'
    e o auto-probe do frontend saberem quando a IA recuperou do rate limit."""
    from ai_config import ping, ai_status
    ping()
    return ai_status()


# ── Resumo semanal e descidas de preço ───────────────────────────

@router.get("/weekly-top")
def weekly_top(limit: int = Query(3, ge=1, le=10), days: int = Query(7, ge=1, le=30), db: Session = Depends(get_db)):
    """Os melhores anúncios dos últimos dias — para não ser preciso entrar na secção."""
    desde = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(DealResult)
        .filter(DealResult.first_seen_at >= desde)
        .filter(DealResult.status.notin_(["dismissed", "gone"]))
        .filter(DealResult.ai_match == True)
        .order_by(DealResult.ai_rating.desc().nullslast(), DealResult.first_seen_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id, "title": r.title, "price": r.price, "currency": r.currency,
            "rating": r.ai_rating, "source": r.source, "url": r.url,
            "image_url": r.image_url, "location": r.location,
        }
        for r in rows
    ]


@router.get("/price-drops")
def price_drops(days: int = Query(30, ge=1, le=180), db: Session = Depends(get_db)):
    """Anúncios que baixaram de preço desde a última vez que foram vistos."""
    desde = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(DealResult)
        .filter(DealResult.previous_price.isnot(None))
        .filter(DealResult.price_changed_at >= desde)
        .filter(DealResult.status.notin_(["dismissed", "gone"]))
        .order_by(DealResult.price_changed_at.desc())
        .all()
    )
    out = []
    for r in rows:
        if r.price is None or r.previous_price is None or r.price >= r.previous_price:
            continue
        desconto = r.previous_price - r.price
        out.append({
            "id": r.id, "title": r.title, "price": r.price, "previous_price": r.previous_price,
            "drop": round(desconto, 2), "drop_pct": round(desconto / r.previous_price * 100),
            "currency": r.currency, "url": r.url, "source": r.source, "saved": r.status == "saved",
            "changed_at": r.price_changed_at.isoformat() if r.price_changed_at else None,
        })
    return out
