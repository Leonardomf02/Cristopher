#!/bin/bash
# Arranca o Cristopher via LaunchAgents e abre o browser.
#
# O backend e o frontend correm SEMPRE como LaunchAgents (KeepAlive). O backend
# arranca através do wrapper assinado CristopherBackend.app, que é o único modo
# de ter Full Disk Access (Screen Time / sono automático).
#
# Este script NÃO arranca um uvicorn próprio de propósito: um 2º backend lançado
# de um Terminal liga-se a 127.0.0.1:8001 (mais específico que o *:8001 do
# LaunchAgent) e, como o Terminal não tem FDA, tapava o localhost e partia o
# Screen Time/sono no browser. Por isso aqui só (re)arrancamos os agentes.

UID_NUM="$(id -u)"
BACKEND_LABEL="com.cristopher.backend"
FRONTEND_LABEL="com.cristopher.frontend"
FRONTEND_URL="http://localhost:3001"
BACKEND_URL="http://localhost:8001"

agent_loaded() { launchctl list 2>/dev/null | grep -q "$1"; }

if ! agent_loaded "$BACKEND_LABEL" || ! agent_loaded "$FRONTEND_LABEL"; then
  echo "❌ LaunchAgents não instalados. Corre primeiro:"
  echo "    ./scripts/launchd/install.sh"
  exit 1
fi

echo "🚀 A (re)arrancar Cristopher via LaunchAgents..."
launchctl kickstart -k "gui/$UID_NUM/$BACKEND_LABEL" 2>/dev/null || true
launchctl kickstart -k "gui/$UID_NUM/$FRONTEND_LABEL" 2>/dev/null || true

echo -n "⏳ backend"
for _ in $(seq 1 30); do
  if curl -sf "$BACKEND_URL/docs" >/dev/null 2>&1; then echo " ✓"; break; fi
  echo -n "."; sleep 1
done

echo -n "⏳ frontend"
for _ in $(seq 1 30); do
  if curl -sf "$FRONTEND_URL" >/dev/null 2>&1; then echo " ✓"; break; fi
  echo -n "."; sleep 1
done

echo ""
echo "✅ Cristopher a correr:"
echo "   Frontend: $FRONTEND_URL"
echo "   Backend:  $BACKEND_URL (docs em /docs)"
echo ""

# Confirma rapidamente que o backend está a ver o knowledgeC (FDA OK).
FDA=$(curl -sf "$BACKEND_URL/api/screen-time/health" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('available'))" 2>/dev/null || echo "?")
if [ "$FDA" = "True" ]; then
  echo "🟢 Full Disk Access OK (Screen Time / sono automático activos)"
elif [ "$FDA" = "False" ]; then
  echo "🟠 Backend sem Full Disk Access — dá FDA ao CristopherBackend.app:"
  echo "   System Settings → Privacy & Security → Full Disk Access"
fi

open "$FRONTEND_URL"
