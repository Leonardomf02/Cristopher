"""Acções rápidas da app (paleta ⌘K).

A captura por frase já existia para o Atalho do iOS, mas essa é protegida por um
token partilhado. Aqui a mesma coisa fica atrás da autenticação normal da app,
para a paleta poder criar despesas/reminders/humor sem token nenhum.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from routers.ingest import CapturePayload, executa_captura

router = APIRouter(prefix="/api/quick", tags=["Quick"])


@router.post("/capture")
async def capture(payload: CapturePayload, db: Session = Depends(get_db)):
    return await executa_captura(payload, db)


@router.get("/exposure")
def exposicao():
    """Quem consegue chegar a esta app. Sem password definida e com os serviços
    à escuta em todas as interfaces, qualquer pessoa na mesma rede entra."""
    import platform
    import socket
    import subprocess

    from auth import auth_required

    portas: dict[int, list[str]] = {8001: [], 3001: []}
    if platform.system() == "Darwin":
        for porta in list(portas):
            # o PATH do LaunchAgent não traz /usr/sbin, onde o lsof vive
            import shutil
            binario = shutil.which("lsof") or "/usr/sbin/lsof"
            try:
                out = subprocess.run(
                    [binario, "-nP", f"-iTCP:{porta}", "-sTCP:LISTEN"],
                    capture_output=True, text=True, timeout=5,
                ).stdout
                for linha in out.splitlines()[1:]:
                    partes = linha.split()
                    if len(partes) >= 2:
                        portas[porta].append(partes[-2] if partes[-1] == "(LISTEN)" else partes[-1])
            except Exception:
                pass

    aberto_a_rede = any(
        any(e.startswith("*:") or e.startswith("0.0.0.0") or e.startswith("[::]") for e in enderecos)
        for enderecos in portas.values()
    )

    ip_local = ""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_local = s.getsockname()[0]
        s.close()
    except OSError:
        pass

    return {
        "auth_required": auth_required(),
        "listening": {str(p): e for p, e in portas.items()},
        "open_to_network": aberto_a_rede,
        "local_ip": ip_local,
        "risk": bool(aberto_a_rede and not auth_required()),
        "hint": (
            "Sem password e à escuta em todas as interfaces: quem estiver na mesma rede "
            f"abre http://{ip_local}:3001 e vê tudo. Corre ./scripts/proteger.sh para fechar."
            if aberto_a_rede and not auth_required() else ""
        ),
    }
