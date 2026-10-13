#!/bin/bash
# Põe uma password na app.
#
# Sem isto, qualquer pessoa na mesma rede (casa, universidade, café) abre o
# endereço do Mac e vê gastos, notas, sono, investimentos — tudo. O sistema de
# login já existe no backend; só falta definir a password.
set -e
cd "$(dirname "$0")/.."
ENV=backend/.env

read -r -s -p "Password para a app: " PW; echo
read -r -s -p "Outra vez: " PW2; echo
if [ "$PW" != "$PW2" ]; then echo "Não coincidem." >&2; exit 1; fi
if [ ${#PW} -lt 6 ]; then echo "Usa pelo menos 6 caracteres." >&2; exit 1; fi

SEGREDO=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")

python3 - "$ENV" "$PW" "$SEGREDO" <<'PY'
import sys, re
caminho, pw, segredo = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    linhas = open(caminho).read().splitlines()
except FileNotFoundError:
    linhas = []
def poe(chave, valor, linhas):
    for i, l in enumerate(linhas):
        if l.startswith(f"{chave}="):
            linhas[i] = f"{chave}={valor}"
            return linhas
    return linhas + [f"{chave}={valor}"]
linhas = poe("CRISTOPHER_PASSWORD", pw, linhas)
linhas = poe("JWT_SECRET", segredo, linhas)
open(caminho, "w").write("\n".join(linhas) + "\n")
PY
chmod 600 "$ENV"

echo "Password guardada. A reiniciar o backend…"
launchctl kickstart -k "gui/$(id -u)/com.cristopher.backend" >/dev/null 2>&1 || true
sleep 6
ESTADO=$(curl -s http://localhost:8001/api/auth/status || echo "sem resposta")
echo "estado: $ESTADO"
echo
echo "A partir de agora a app pede a password (a sessão dura 30 dias em cada dispositivo)."
