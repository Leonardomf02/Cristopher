"""Autenticação single-user para expor o Cristopher na internet.

Modelo: uma password (env CRISTOPHER_PASSWORD) → JWT Bearer. Se a password não
estiver definida (dev local / Tailscale), a auth fica DESLIGADA e tudo passa —
assim o uso local continua sem fricção. Em produção, basta definir a password.
"""
import hmac
import os
import time

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

_PASSWORD = os.getenv("CRISTOPHER_PASSWORD", "")
_SECRET = os.getenv("JWT_SECRET", "dev-insecure-change-me")
_ALGO = "HS256"
_EXPIRE_DAYS = 30

# Com password, o segredo por omissão está escrito neste repositório público:
# qualquer pessoa assinava um token válido. Mais vale não arrancar.
if _PASSWORD and _SECRET == "dev-insecure-change-me":
    raise RuntimeError("CRISTOPHER_PASSWORD definida sem JWT_SECRET (gerar com: openssl rand -hex 32)")

# Uma password só e a app na internet: sem travão é tentar até acertar. Atrás do
# reverse proxy da NAS todos os pedidos chegam do mesmo endereço, por isso o
# travão é global — no pior caso é ele próprio que espera 15 minutos.
_JANELA_S = 15 * 60
_MAX_FALHAS = 10
_falhas: list[float] = []


def auth_required() -> bool:
    """Auth só está ativa quando há uma password definida."""
    return bool(_PASSWORD)


def create_token() -> str:
    payload = {"sub": "owner", "exp": int(time.time()) + _EXPIRE_DAYS * 86400}
    return jwt.encode(payload, _SECRET, algorithm=_ALGO)


_bearer = HTTPBearer(auto_error=False)


def require_auth(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    """Dependency aplicada a todos os routers protegidos."""
    if not auth_required():
        return
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")
    try:
        jwt.decode(creds.credentials, _SECRET, algorithms=[_ALGO])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido ou expirado")


# ── Router de login ──────────────────────────────────────────────

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    password: str


@router.get("/status")
def auth_status():
    return {"auth_required": auth_required()}


@router.post("/login")
def login(body: LoginIn):
    if not auth_required():
        return {"access_token": "", "token_type": "bearer", "auth_required": False}
    agora = time.time()
    _falhas[:] = [t for t in _falhas if agora - t < _JANELA_S]
    if len(_falhas) >= _MAX_FALHAS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiadas tentativas — espera 15 minutos")
    # em bytes: com str, um carácter fora do ASCII rebentava o compare_digest
    if not hmac.compare_digest(body.password.encode(), _PASSWORD.encode()):
        _falhas.append(agora)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Password errada")
    return {"access_token": create_token(), "token_type": "bearer"}
