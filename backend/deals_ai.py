"""Rating IA dos deals via agente iaedu.pt (Opus 4.7).

Recebe o que o utilizador quer (watch) + uma lista de candidatos e devolve, por
candidato: rating 0-100, match (é mesmo o item?), e uma razão curta. É aqui que
se resolve a desambiguação de descrições (ex: pede 'iPhone 17', anúncio é '17e')."""

import time
import logging

from ai_config import ask_agent, extract_json

logger = logging.getLogger(__name__)

_BATCH = 40          # candidatos por chamada (Opus aguenta; menos chamadas = menos rate limit)
_BATCH_PAUSE = 1.0   # pausa entre lotes (gentil com o rate limit do agente)


def _candidate_line(i: int, lst) -> str:
    desc = (lst.description or "").replace("\n", " ").strip()[:220]
    title = (lst.title or "").strip()[:120]
    price = f"{lst.price} {lst.currency}" if lst.price is not None else "?"
    parts = [f"#{i} [{lst.source}]", f"titulo: {title}", f"preco: {price}"]
    if lst.condition:
        parts.append(f"estado: {lst.condition}")
    if desc:
        parts.append(f"descricao: {desc}")
    return " | ".join(parts)


def _build_prompt(watch: dict, listings: list) -> str:
    wanted = []
    wanted.append(f"Procuro: {watch.get('title') or watch.get('query')}")
    if watch.get("query"):
        wanted.append(f"Termos: {watch['query']}")
    if watch.get("category"):
        wanted.append(f"Categoria: {watch['category']}")
    cond = watch.get("condition") or "any"
    wanted.append("Condicao: " + {"new": "novo", "used": "usado"}.get(cond, "indiferente"))
    if watch.get("max_price"):
        wanted.append(f"Preco maximo desejado: {watch['max_price']} EUR")
    if watch.get("ai_context"):
        wanted.append(f"Contexto importante: {watch['ai_context']}")
    if watch.get("exclude_keywords"):
        wanted.append(f"EXCLUIR se for: {watch['exclude_keywords']}")
    wanted_block = "\n".join("- " + w for w in wanted)

    cand_block = "\n".join(_candidate_line(i, lst) for i, lst in enumerate(listings))

    return f"""És um caçador de deals exigente. O utilizador quer um produto específico e tu avalias anúncios de marketplaces (Vinted, OLX) para encontrar os melhores negócios e filtrar o lixo.

O QUE O UTILIZADOR QUER:
{wanted_block}

REGRAS DE AVALIAÇÃO (por anúncio):
1. "match": true só se o anúncio for MESMO o produto pedido. Põe false se:
   - For uma variante/modelo diferente (ex: pede "iPhone 17" e o anúncio é "17e", "Plus", "Pro", "mini" — lê o título E a descrição com atenção, muita gente engana).
   - For um acessório/peça/capa quando se pede o produto em si.
   - For condição claramente errada vs o pedido, ou claramente outra coisa.
   - Bater nas regras de EXCLUIR.
2. "rating" 0-100: SÓ importa quando match=true (se match=false, mete rating 0). Avalia o NEGÓCIO:
   - Preço vs valor de mercado típico do item (mais barato p/ o mesmo = melhor).
   - Estado/condição, completude (caixa, fatura, garantia, acessórios), fiabilidade do vendedor, qualidade do anúncio.
   - 90-100 = negócio excelente (raro). 70-89 = bom. 50-69 = ok. <50 = fraco/caro.
3. "reason": 1 frase curta em português a justificar (porque é bom/mau, ou porque não é o item).

Avalia APENAS com a informação dada abaixo — NÃO precisas de pesquisar na web.

Candidatos:
{cand_block}

Responde APENAS com um array JSON, um objecto por candidato, NESTA forma e nada mais (sem texto, sem ```):
[{{"i": 0, "match": true, "rating": 82, "reason": "..."}}]"""


def rate_listings(watch: dict, listings: list) -> list[dict]:
    """Devolve uma lista alinhada com `listings`: cada item {match, rating, reason}.
    Em falha da IA, devolve match=True/rating=None (não esconde, mas não conta como bom)."""
    out: list[dict] = [{"match": True, "rating": None, "reason": ""} for _ in listings]
    if not listings:
        return out

    for start in range(0, len(listings), _BATCH):
        if start > 0:
            time.sleep(_BATCH_PAUSE)
        chunk = listings[start:start + _BATCH]
        prompt = _build_prompt(watch, chunk)
        parsed = None
        for attempt in range(2):  # 1 retry: o agente às vezes devolve prosa em vez de JSON
            msg = prompt if attempt == 0 else ("RESPONDE SÓ COM O ARRAY JSON, NADA MAIS.\n\n" + prompt)
            parsed = extract_json(ask_agent(msg))
            if isinstance(parsed, list):
                break
        if not isinstance(parsed, list):
            logger.warning("rating IA sem JSON válido para watch %s (lote %s)", watch.get("id"), start)
            continue
        for obj in parsed:
            if not isinstance(obj, dict):
                continue
            try:
                i = int(obj.get("i"))
            except (TypeError, ValueError):
                continue
            if not (0 <= i < len(chunk)):
                continue
            match = bool(obj.get("match", True))
            rating = obj.get("rating")
            try:
                rating = max(0, min(100, int(rating)))
            except (TypeError, ValueError):
                rating = None
            out[start + i] = {
                "match": match,
                "rating": 0 if (not match) else rating,
                "reason": str(obj.get("reason", ""))[:300],
            }
    return out
