"""Adapter OLX Portugal (olx.pt) via API pública `/api/v1/offers/`.

Devolve já a descrição completa, estado (novo/usado), modelo normalizado e
localização — ótimo para a desambiguação. Cobre telemóveis, acessórios e motos.

E, nos veículos, devolve o **ano, os quilómetros e a cor em campos** (`params`),
tal como o StandVirtual. Isso estava a ser deitado fora: uma MT-07 com "Ano:
2018 · Quilómetros: 22.000 km · Cor: azul" no próprio anúncio aparecia na app
com quatro pontos de interrogação, porque só se olhava para o texto livre — e o
texto livre daquele anúncio não diz nada disso."""

import logging
import re

from curl_cffi import requests as curl

from .base import Listing

logger = logging.getLogger(__name__)

_API = "https://www.olx.pt/api/v1/offers/"


def _params(offer) -> dict:
    return {p.get("key"): (p.get("value") or {}) for p in (offer.get("params") or [])}


def _price_param(offer):
    v = _params(offer).get("price") or {}
    return v.get("value"), v.get("currency") or "EUR"


def _state(offer):
    # A API chama-lhe `condicao` nos veículos e `state` no resto (telemóveis,
    # roupa). Só se olhava para o segundo, por isso as motos vinham todas sem
    # condição e o filtro novo/usado deixava passar tudo.
    p = _params(offer)
    for chave in ("condicao", "state"):
        rotulo = (p.get(chave) or {}).get("label")
        if rotulo:
            return rotulo
    return ""


def _inteiro(valor) -> int | None:
    """O número do campo. Vem "22000" na chave e "22.000 km" na etiqueta."""
    achado = re.search(r"\d[\d.\s]*", str(valor or ""))
    if not achado:
        return None
    try:
        return int(re.sub(r"[.\s]", "", achado.group()))
    except ValueError:
        return None


def _valor(p: dict, *chaves) -> str:
    """O primeiro dos campos pedidos que tenha alguma coisa (`key` ou `label`)."""
    for chave in chaves:
        v = p.get(chave) or {}
        for lado in ("key", "label"):
            texto = str(v.get(lado) or "").strip()
            if texto:
                return texto
    return ""


def _potencia_kw(p: dict) -> int | None:
    """A potência, quando o anúncio a traz em campo. Pode vir em kW ou em cv."""
    import deal_attrs
    texto = _valor(p, "potencia", "motorpower", "engine_power", "power")
    if not texto:
        return None
    if texto.replace(".", "").isdigit():
        # Campo só com o número: o OLX pede-o em cv nos veículos.
        cv = _inteiro(texto)
        return deal_attrs.classe_de_potencia(round(cv * 0.7355)) if cv else None
    return deal_attrs.extrai_potencia_kw(texto)


def _atributos(offer) -> dict:
    """Ano, km, potência e cor tirados dos campos do anúncio, não do texto."""
    import deal_attrs
    p = _params(offer)
    km = _inteiro(_valor(p, "quilometros", "mileage"))
    cor = _valor(p, "cor", "color")
    return {
        "year": _inteiro(_valor(p, "year", "ano")),
        "km": km if km and 0 <= km <= 2_000_000 else None,
        "power_kw": _potencia_kw(p),
        # "prateado" e "cinza" são o mesmo cinzento da app; "outra" não é cor
        # nenhuma e fica em "o anúncio não diz".
        "color": deal_attrs.extrai_cor(cor) if cor else None,
    }


def _image(offer):
    photos = offer.get("photos") or []
    if not photos:
        return ""
    link = photos[0].get("link") or ""
    return link.replace("{width}", "600").replace("{height}", "600")


def _location(offer):
    loc = offer.get("location") or {}
    city = (loc.get("city") or {}).get("name", "")
    region = (loc.get("region") or {}).get("name", "")
    return ", ".join(x for x in (city, region) if x)


# A API do OLX devolve no máximo ~50 por pedido, mas há 738 anúncios para
# "Yamaha MT 07". Sem paginar, a app via 25 e concluía que não havia nada.
_POR_PAGINA = 50


def search(query: str, *, max_price=None, condition="any", limit=40) -> list[Listing]:
    params = {
        "offset": "0",
        "limit": str(min(limit, _POR_PAGINA)),
        "query": query,
        "sort_by": "created_at:desc",
    }
    if max_price:
        params["filter_float_price:to"] = str(int(max_price))
    if condition == "new":
        params["filter_enum_state[0]"] = "new"
    elif condition == "used":
        params["filter_enum_state[0]"] = "used"

    data = []
    # A imitar o Chrome e não com o httpx: dentro da imagem da NAS o OLX responde
    # 403 ao httpx (a impressão digital do TLS é outra) e o mesmo pedido do Mac
    # passava. Foram oito dias sem um anúncio novo sem ninguém dar por isso.
    with curl.Session(impersonate="chrome", timeout=30,
                      headers={"Accept": "application/json"}) as client:
        while len(data) < limit:
            params["offset"] = str(len(data))
            params["limit"] = str(min(limit - len(data), _POR_PAGINA))
            r = client.get(_API, params=params)
            r.raise_for_status()
            pagina = r.json().get("data", [])
            if not pagina:
                break
            data.extend(pagina)
            if len(pagina) < _POR_PAGINA:
                break

    out: list[Listing] = []
    for offer in data:
        ext = offer.get("id")
        if ext is None:
            continue
        price, currency = _price_param(offer)
        cond = _state(offer)
        out.append(Listing(
            source="olx",
            external_id=str(ext),
            title=offer.get("title", "") or "",
            description=offer.get("description", "") or "",
            price=price,
            currency=currency,
            condition=cond,
            url=offer.get("url", "") or "",
            image_url=_image(offer),
            location=_location(offer),
            seller=((offer.get("user") or {}).get("name", "") or ""),
            attrs=_atributos(offer),
        ))
    return out
