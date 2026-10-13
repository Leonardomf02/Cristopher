"""Porta https só para o regresso do banco.

O Enable Banking não aceita endereços http nas aplicações de produção, mas a app
corre em http://localhost:3001 e não vale a pena passar tudo para https por
causa de um redirecto que acontece uma vez por trimestre.

Solução: um ouvinte minúsculo em https://localhost:3043 que não serve nada — só
reencaminha o que receber para a app, com o código que o banco anexou. Não lê
nem escreve dados; se o certificado não existir, nem sequer arranca.

Certificado (uma vez):
    brew install mkcert && mkcert -install
    cd frontend && mkcert -cert-file certs/localhost.pem \\
                          -key-file certs/localhost-key.pem localhost 127.0.0.1 ::1
"""
from __future__ import annotations

import logging
import os
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger(__name__)

PORTA = int(os.getenv("BANK_CALLBACK_PORT", "3043"))
APP = os.getenv("BANK_CALLBACK_TARGET", "http://localhost:3001")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERT = os.path.join(_RAIZ, "frontend", "certs", "localhost.pem")
CHAVE = os.path.join(_RAIZ, "frontend", "certs", "localhost-key.pem")


class _Reencaminha(BaseHTTPRequestHandler):
    def do_GET(self):                                   # noqa: N802
        self.send_response(302)
        self.send_header("Location", f"{APP}{self.path}")
        self.end_headers()

    def log_message(self, *args):                       # sem ruído nos logs
        pass


def disponivel() -> bool:
    return os.path.exists(CERT) and os.path.exists(CHAVE)


def arranca() -> bool:
    if not disponivel():
        logger.info("callback https desligado: falta o certificado em frontend/certs")
        return False
    try:
        contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        contexto.load_cert_chain(CERT, CHAVE)
        servidor = HTTPServer(("127.0.0.1", PORTA), _Reencaminha)
        servidor.socket = contexto.wrap_socket(servidor.socket, server_side=True)
    except OSError as ex:
        logger.warning("callback https não arrancou na porta %s: %s", PORTA, ex)
        return False
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    logger.info("callback https em https://localhost:%s → %s", PORTA, APP)
    return True
