"""A cor da mota sai da foto, porque no texto não está.

Ele pediu uma MT-07 preta. De 780 anúncios guardados, **nenhum diz a cor** — nem
no título nem na descrição. A cor ficava eternamente em "o anúncio não diz", que
é honesto mas não ajuda nada: é a única exigência dele que o texto nunca
responde.

A foto responde sempre. O modelo local (`qwen3.5:9b`) vê imagens, corre no Mac,
não gasta quota nenhuma e demora ~5 segundos. Medido nos anúncios reais dele:
azul → azul, preta → preta, prateada → cinzento, e uma foto de uma piscina que o
Facebook mete no meio → "nenhuma", em vez de inventar uma cor.

Só se olha para a foto quando **o watch pede uma cor** e **o texto não a deu** —
não vale a pena gastar 5 segundos por anúncio para responder a uma pergunta que
ninguém fez.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Optional

import httpx

import deal_attrs

logger = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

CORES_VALIDAS = set(deal_attrs.CORES)
CERTEZA_MINIMA = 70
TAMANHO_MINIMO = 8000        # abaixo disto é um ícone ou um erro, não uma foto

_PROMPT = (
    "Nesta foto está um artigo à venda. De que cor é o artigo em si "
    "(ignora o fundo, o chão, as sombras e os acessórios)? Escolhe exactamente uma: "
    + ", ".join(sorted(CORES_VALIDAS)) + ". "
    "Se não houver artigo visível ou não der para dizer, usa \"nenhuma\". "
    'Responde só JSON: {"cor":"...","certeza":0-100}'
)


def descarrega(url: str) -> Optional[bytes]:
    if not url:
        return None
    try:
        r = httpx.get(url, timeout=20.0, follow_redirects=True,
                      headers={"User-Agent": UA})
    except httpx.HTTPError as e:
        logger.debug("foto %s: %s", url[:60], e)
        return None
    # O Facebook assina os URLs das imagens e eles caducam: passado um tempo
    # devolvem 21 bytes de "URL signature expired" em vez da foto.
    if r.status_code != 200 or len(r.content) < TAMANHO_MINIMO:
        return None
    return r.content


def cor_da_foto(imagem: bytes, *, timeout: float = 90.0) -> Optional[str]:
    """A cor do artigo na foto. None quando não se consegue dizer."""
    import local_ai
    if not imagem or not local_ai.disponivel():
        return None
    corpo = {
        "model": local_ai.MODELO,
        "prompt": _PROMPT,
        "images": [base64.b64encode(imagem).decode()],
        "stream": False,
        "format": "json",
        "think": False,
        "options": {"temperature": 0, "num_predict": 60, "num_ctx": 8192},
    }
    try:
        r = httpx.post(f"{local_ai.URL}/api/generate", json=corpo, timeout=timeout)
        if r.status_code != 200:
            return None
        dados = json.loads(r.json().get("response") or "{}")
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as e:
        logger.debug("cor pela foto: %s", e)
        return None

    cor = deal_attrs.normaliza(str(dados.get("cor") or ""))
    try:
        certeza = int(dados.get("certeza") or 0)
    except (TypeError, ValueError):
        certeza = 0
    if cor not in CORES_VALIDAS or certeza < CERTEZA_MINIMA:
        return None
    return cor


def cor_do_anuncio(image_url: str, *, source: str = "",
                   external_id: str = "") -> tuple[Optional[str], bool]:
    """(cor, vi_mesmo_a_foto).

    O segundo valor importa: sem ele, um anúncio cuja foto não se conseguiu
    descarregar ficava marcado como "já tentei" e nunca mais era olhado. Os URLs
    de imagem do OLX e do Facebook caducam, por isso isso acontece muito."""
    imagem = descarrega(image_url)
    if imagem is None and source == "facebook" and external_id:
        # O URL guardado caducou — a foto boa está na página do item. Atenção:
        # a página traz dezenas de imagens de outros anúncios (chegou a vir uma
        # piscina); a do próprio anúncio é a do `og:image`.
        from deals_sources import facebook as fb
        imagem = descarrega(fb.foto_principal(external_id) or "")
    if imagem is None:
        return None, False
    return cor_da_foto(imagem), True
