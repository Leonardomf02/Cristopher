"""Avisos no telemóvel, sem Telegram.

O balão do macOS só aparece se estiveres à frente do Mac desbloqueado. Com a app
instalada no telemóvel (PWA) dá para receber os avisos onde quer que estejas —
o iOS suporta Web Push desde a 16.4, desde que a app seja aberta a partir do
ecrã principal e servida por HTTPS (ver `scripts/tailscale-https.sh`).

As chaves VAPID são geradas à primeira utilização e ficam em `push_keys.json`.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Na NAS as chaves vivem no volume de dados (PUSH_KEYS_DIR): ao lado do código,
# cada versão nova da imagem gerava chaves novas e o telemóvel deixava de receber.
_PASTA_CHAVES = os.getenv("PUSH_KEYS_DIR") or os.path.dirname(os.path.abspath(__file__))
FICHEIRO_CHAVES = os.path.join(_PASTA_CHAVES, "push_keys.json")
# A biblioteca de envio lê a chave privada de um ficheiro PEM (a versão em texto
# só é aceite no formato cru), por isso guarda-se também assim.
FICHEIRO_PEM = os.path.join(_PASTA_CHAVES, "push_key.pem")
CONTACTO = os.getenv("PUSH_CONTACT", "mailto:cristopher@localhost")


def _gera_chaves() -> dict:
    from py_vapid import Vapid01
    from cryptography.hazmat.primitives import serialization
    import base64

    v = Vapid01()
    v.generate_keys()
    privada = v.private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    numeros = v.public_key.public_numbers()
    bruto = b"\x04" + numeros.x.to_bytes(32, "big") + numeros.y.to_bytes(32, "big")
    publica = base64.urlsafe_b64encode(bruto).decode().rstrip("=")
    return {"private_pem": privada, "public_key": publica}


def chaves() -> dict:
    """Chaves VAPID desta instalação (criadas na primeira vez)."""
    if os.path.exists(FICHEIRO_CHAVES):
        try:
            with open(FICHEIRO_CHAVES) as f:
                guardadas = json.load(f)
            if not os.path.exists(FICHEIRO_PEM):
                _escreve_pem(guardadas["private_pem"])
            return guardadas
        except (OSError, json.JSONDecodeError, KeyError):
            pass
    novas = _gera_chaves()
    with open(FICHEIRO_CHAVES, "w") as f:
        json.dump(novas, f)
    os.chmod(FICHEIRO_CHAVES, 0o600)
    _escreve_pem(novas["private_pem"])
    logger.info("chaves de push criadas")
    return novas


def _escreve_pem(pem: str) -> str:
    with open(FICHEIRO_PEM, "w") as f:
        f.write(pem)
    os.chmod(FICHEIRO_PEM, 0o600)
    return FICHEIRO_PEM


def chave_publica() -> str:
    return chaves()["public_key"]


def _caminho_pem() -> str:
    chaves()
    return FICHEIRO_PEM


def envia(subscricao: dict, titulo: str, corpo: str, url: str = "/") -> tuple[bool, str]:
    """Envia um aviso para um dispositivo. Devolve (ok, motivo)."""
    from pywebpush import webpush, WebPushException

    dados = json.dumps({"title": titulo, "body": corpo[:300], "url": url})
    try:
        webpush(
            subscription_info=subscricao,
            data=dados,
            vapid_private_key=_caminho_pem(),
            vapid_claims={"sub": CONTACTO},
            timeout=10,
        )
        return True, ""
    except WebPushException as ex:
        codigo = getattr(ex.response, "status_code", None)
        # 404/410 = o telemóvel desinstalou a app ou revogou a subscrição
        return False, f"{codigo or 'erro'}: {str(ex)[:120]}"
    except Exception as ex:  # noqa: BLE001
        return False, str(ex)[:120]
