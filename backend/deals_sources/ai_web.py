"""Fonte 'IA + pesquisa web' via agente iaedu.pt (Claude Opus 4.7 com Tavily).

Pesquisa a web aberta e devolve anúncios/ofertas reais — apanha o que a Vinted e
o OLX não dão: Standvirtual (motos), preço novo em retail (Worten/Fnac/iStore),
KuantoKusta, lojas oficiais, etc. Best-effort: se a IA falhar, devolve []."""

import hashlib
import logging
from urllib.parse import urlparse

from ai_config import ask_agent, extract_json
from .base import Listing

logger = logging.getLogger(__name__)


def _domain(url: str, fallback: str = "web") -> str:
    try:
        host = urlparse(url).netloc.lower().replace("www.", "")
        label = host.split(".")[0] if host else ""
        return label or fallback
    except Exception:
        return fallback


def _to_float(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        digits = "".join(c for c in v.replace(",", ".") if c.isdigit() or c == ".")
        try:
            return float(digits) if digits else None
        except ValueError:
            return None
    return None


def search(query: str, *, max_price=None, condition="any", limit=10) -> list[Listing]:
    limit = min(limit, 12)  # web search rende poucos resultados bons; não pedir 40
    cond_txt = {"new": "Só novos.", "used": "Só usados."}.get(condition, "Novos ou usados.")
    price_txt = f"Preço máximo: {max_price} EUR." if max_price else ""

    prompt = f"""És um motor de busca de deals em Portugal. Pesquisa AGORA na web (usa a tua ferramenta de pesquisa) anúncios/ofertas À VENDA para o produto abaixo e devolve os melhores que encontrares MESMO, com URL real e acessível.

Produto: {query}
{cond_txt} {price_txt}

Procura nos sites de venda PT adequados ao produto (ex.: Standvirtual e OLX para motos/carros; Worten, Fnac, iStore, PCDiga, KuantoKusta e lojas oficiais para eletrónica nova; marketplaces para usado). Dá prioridade a páginas de produto/anúncio concretas, não a listagens genéricas.

Responde APENAS com um array JSON (sem texto à volta), no máximo {limit} itens, cada um exactamente assim:
[{{"title": "...", "price": 699.0, "currency": "EUR", "condition": "novo|usado", "url": "https://...", "site": "dominio.pt", "location": "cidade ou vazio"}}]

Regras: só inclui itens REAIS encontrados na pesquisa, com URL que abra a página do produto/anúncio. NÃO inventes preços nem URLs. Se não encontrares nada fiável, devolve []."""

    reply = ask_agent(prompt, timeout=180.0)
    parsed = extract_json(reply)
    if not isinstance(parsed, list):
        logger.warning("ai_web: sem JSON válido para '%s'", query)
        return []

    out: list[Listing] = []
    seen: set[str] = set()
    for obj in parsed:
        if not isinstance(obj, dict):
            continue
        url = str(obj.get("url", "")).strip()
        if not url.startswith("http") or url in seen:
            continue
        site = _domain(url, str(obj.get("site", "web")) or "web")
        if site in ("olx", "vinted"):  # já cobertos por adapters próprios (melhor data)
            continue
        seen.add(url)
        out.append(Listing(
            source="web",  # constante: nunca colide com os adapters estruturados
            external_id=hashlib.sha1(url.encode()).hexdigest()[:16],
            title=str(obj.get("title", "")).strip()[:200],
            description="",
            price=_to_float(obj.get("price")),
            currency=str(obj.get("currency", "EUR")) or "EUR",
            condition=str(obj.get("condition", "")).strip(),
            url=url,
            image_url="",
            location=str(obj.get("location", "")).strip(),
            seller=site,
        ))
    return out[:limit]
