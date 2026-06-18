#!/bin/bash
# Instala o agente local do Cristopher como LaunchAgent (corre sempre que o Mac
# está ligado e sessão iniciada; reinicia sozinho via KeepAlive).
#
# Uso:
#   CRISTOPHER_CLOUD_URL=https://cristopher-api.duckdns.org \
#   INGEST_TOKEN=o-teu-token \
#   ./install.sh
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_DIR="$ROOT/agent"
LABEL="com.cristopher.agent"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/.cristopher-agent/agent.log"
INTERVAL="${PUSH_INTERVAL:-300}"

if [ -z "$CRISTOPHER_CLOUD_URL" ] || [ -z "$INGEST_TOKEN" ]; then
  echo "❌ Define CRISTOPHER_CLOUD_URL e INGEST_TOKEN antes de correr."
  echo "   Ex: CRISTOPHER_CLOUD_URL=https://cristopher-api.duckdns.org INGEST_TOKEN=xxx ./install.sh"
  exit 1
fi

# Python do venv do backend (tem httpx + sqlalchemy). Fallback: python3 do sistema.
PYTHON="$ROOT/backend/venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"

mkdir -p "$HOME/.cristopher-agent" "$HOME/Library/LaunchAgents"

sed -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__SCRIPT__|$AGENT_DIR/push_local.py|g" \
    -e "s|__CLOUD_URL__|$CRISTOPHER_CLOUD_URL|g" \
    -e "s|__TOKEN__|$INGEST_TOKEN|g" \
    -e "s|__INTERVAL__|$INTERVAL|g" \
    -e "s|__LOG__|$LOG|g" \
    "$AGENT_DIR/com.cristopher.agent.plist.template" > "$PLIST_DEST"

launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

echo "✅ Agente instalado e a correr."
echo "   Python:  $PYTHON"
echo "   Cloud:   $CRISTOPHER_CLOUD_URL"
echo "   Logs:    $LOG"
echo ""
echo "⚠️  O Screen Time precisa de Full Disk Access para o Python acima:"
echo "    System Settings → Privacy & Security → Full Disk Access → adiciona:"
echo "    $PYTHON"
echo ""
echo "Ver logs:   tail -f $LOG"
echo "Parar:      launchctl unload $PLIST_DEST"
