#!/usr/bin/env bash
# Instala LaunchAgents para que o backend (FastAPI) e o frontend (Vite)
# do Cristopher arranquem automaticamente no login do utilizador.
# Idempotente: pode ser executado várias vezes.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/scripts/launchd/logs"
BACKEND_LABEL="com.cristopher.backend"
FRONTEND_LABEL="com.cristopher.frontend"
BACKEND_PLIST="$LAUNCH_DIR/$BACKEND_LABEL.plist"
FRONTEND_PLIST="$LAUNCH_DIR/$FRONTEND_LABEL.plist"

UVICORN="$PROJECT_DIR/backend/venv/bin/uvicorn"
NPM_BIN="$(command -v npm || true)"
NODE_BIN="$(command -v node || true)"

if [[ ! -x "$UVICORN" ]]; then
  echo "❌ Não encontrei $UVICORN — corre primeiro:"
  echo "    cd backend && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
if [[ -z "$NPM_BIN" || -z "$NODE_BIN" ]]; then
  echo "❌ npm/node não encontrados no PATH actual. Instala node (brew install node ou nvm)."
  exit 1
fi
NODE_DIR="$(dirname "$NODE_BIN")"

mkdir -p "$LAUNCH_DIR" "$LOG_DIR"

cat > "$BACKEND_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$BACKEND_LABEL</string>
  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR/backend</string>
  <key>ProgramArguments</key>
  <array>
    <string>$UVICORN</string>
    <string>main:app</string>
    <string>--host</string>
    <string>0.0.0.0</string>
    <string>--port</string>
    <string>8000</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$PROJECT_DIR/backend/venv/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/backend.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/backend.err.log</string>
</dict>
</plist>
EOF

cat > "$FRONTEND_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$FRONTEND_LABEL</string>
  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR/frontend</string>
  <key>ProgramArguments</key>
  <array>
    <string>$NPM_BIN</string>
    <string>run</string>
    <string>dev</string>
    <string>--</string>
    <string>--host</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$NODE_DIR:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/frontend.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/frontend.err.log</string>
</dict>
</plist>
EOF

# Recarregar (unload + load) para reflectir mudanças
launchctl unload "$BACKEND_PLIST" 2>/dev/null || true
launchctl unload "$FRONTEND_PLIST" 2>/dev/null || true
launchctl load -w "$BACKEND_PLIST"
launchctl load -w "$FRONTEND_PLIST"

echo "✅ Instalado:"
echo "   $BACKEND_LABEL  →  http://localhost:8000"
echo "   $FRONTEND_LABEL →  http://localhost:5173"
echo ""
echo "Logs em: $LOG_DIR"
echo "Para parar: ./scripts/launchd/uninstall.sh"
