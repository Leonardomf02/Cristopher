"""Adapter StandVirtual (standvirtual.com) — o site de veículos do grupo OLX em Portugal.

É a fonte que interessa para motas e carros: as outras (Vinted, Facebook) são
sobretudo particulares e trazem peças e acessórios pelo meio.

Vale mais do que uma fonte a mais: ao contrário do texto solto do Facebook, aqui
o **ano, os quilómetros e a potência vêm em campos**. O `deal_attrs` só os
adivinha em 73% e 32% dos anúncios; aqui vêm certos em 100%, e é com eles que se
decide se a mota serve.

Não há API pública documentada, mas a página é Next.js e traz os resultados já
no `__NEXT_DATA__` — é lê-los daí em vez de raspar HTML, que muda a cada deploy.
"""

import json
import logging
import re
import unicodedata

import httpx

from .base import Listing

logger = logging.getLogger(__name__)

_BASE = "https://www.standvirtual.com"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# É um site de veículos: procura-se nas duas secções e junta-se.
_SECCOES = ("motos", "carros")
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

CV_PARA_KW = 0.7355


def _slug(query: str) -> str:
    texto = unicodedata.normalize("NFD", (query or "").lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", texto)).strip("-")


def _anuncios(html: str) -> list[dict]:
    m = _NEXT_DATA.search(html)
    if not m:
        return []
    try:
        dados = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    estado = (dados.get("props", {}).get("pageProps", {}) or {}).get("urqlState") or {}
    for valor in estado.values():
        conteudo = valor.get("data")
        if isinstance(conteudo, str):
            try:
                conteudo = json.loads(conteudo)
            except json.JSONDecodeError:
                continue
        if isinstance(conteudo, dict) and "advertSearch" in conteudo:
            busca = conteudo["advertSearch"] or {}
            linhas = busca.get("edges") or busca.get("nodes") or []
            return [linha.get("node", linha) for linha in linhas]
    return []


def _params(anuncio: dict) -> dict:
    return {p.get("key"): p.get("value") for p in (anuncio.get("parameters") or [])}


def _inteiro(valor) -> int | None:
    try:
        return int(float(str(valor).replace(" ", "").replace(",", ".")))
    except (TypeError, ValueError):
        return None


def _potencia_kw(titulo: str, params: dict) -> int | None:
    """A potência que interessa é a **homologada**, não a do motor.

    Uma MT-07 limitada a A2 traz `engine_power = 75 cv` (o motor é o mesmo) e o
    vendedor escreve "35 kW" no título e na versão. Converter os cavalos dava 55
    e mandava fora exactamente a mota que ele procura. Por isso o kW escrito
    ganha sempre; os cavalos só valem quando ninguém escreveu nada."""
    import deal_attrs
    escrito = deal_attrs.extrai_potencia_kw(f"{titulo} {params.get('version') or ''}")
    if escrito is not None:
        return escrito
    cv = _inteiro(params.get("engine_power"))
    # 45 cv dá 33 kW e 73 cv dá 54: sem arredondar à classe legal, uma A2 a
    # sério falhava um pedido de "exactamente 35 kW".
    return deal_attrs.classe_de_potencia(round(cv * CV_PARA_KW)) if cv else None


def _atributos(anuncio: dict, params: dict) -> dict:
    """Ano, km e potência já em números."""
    return {
        "year": _inteiro(params.get("first_registration_year")),
        "km": _inteiro(params.get("mileage")),
        "power_kw": _potencia_kw(anuncio.get("title", "") or "", params),
        "color": None,                      # o site não o dá na lista de resultados
    }


def _descricao(anuncio: dict, params: dict) -> str:
    """O texto que a IA vê. A lista não traz descrição, por isso monta-se com o
    que há — sem isto os filtros de palavras não teriam onde procurar."""
    partes = [anuncio.get("shortDescription") or ""]
    for chave, etiqueta in (("version", "versão"), ("engine_capacity", "cilindrada"),
                            ("mileage", "km"), ("first_registration_year", "ano"),
                            ("engine_power", "cv"), ("origin", "origem")):
        valor = params.get(chave)
        if valor:
            partes.append(f"{etiqueta}: {valor}")
    return " · ".join(p for p in partes if p)


def _localizacao(anuncio: dict) -> str:
    loc = anuncio.get("location") or {}
    cidade = (loc.get("city") or {}).get("name", "")
    regiao = (loc.get("region") or {}).get("name", "")
    return ", ".join(x for x in (cidade, regiao) if x)


def _preco(anuncio: dict) -> tuple[float | None, str]:
    preco = ((anuncio.get("price") or {}).get("amount") or {})
    try:
        return float(preco.get("value")), preco.get("currencyCode") or "EUR"
    except (TypeError, ValueError):
        return None, "EUR"


def search(query: str, *, max_price=None, condition="any", limit=40) -> list[Listing]:
    slug = _slug(query)
    if not slug:
        return []
    params = {}
    if max_price:
        params["search[filter_float_price:to]"] = str(int(max_price))

    vistos: set[str] = set()
    out: list[Listing] = []
    with httpx.Client(timeout=30.0, follow_redirects=True,
                      headers={"User-Agent": _UA, "Accept-Language": "pt-PT,pt;q=0.9"}) as client:
        for seccao in _SECCOES:
            if len(out) >= limit:
                break
            try:
                r = client.get(f"{_BASE}/{seccao}/q-{slug}", params=params)
                r.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning("standvirtual %s: %s", seccao, e)
                continue
            for anuncio in _anuncios(r.text):
                ext = str(anuncio.get("id") or "")
                if not ext or ext in vistos:
                    continue
                vistos.add(ext)
                p = _params(anuncio)
                preco, moeda = _preco(anuncio)
                out.append(Listing(
                    source="standvirtual",
                    external_id=ext,
                    title=anuncio.get("title", "") or "",
                    description=_descricao(anuncio, p),
                    price=preco,
                    currency=moeda,
                    condition="usado",       # o site é de usados; novos são de stand
                    url=anuncio.get("url", "") or "",
                    image_url=(anuncio.get("thumbnail") or {}).get("x1", "") or "",
                    location=_localizacao(anuncio),
                    seller=((anuncio.get("sellerLink") or {}).get("name") or ""),
                    attrs=_atributos(anuncio, p),
                ))
                if len(out) >= limit:
                    break
    return out
