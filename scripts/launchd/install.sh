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
DAILY_LABEL="com.cristopher.dailysignals"
BACKEND_PLIST="$LAUNCH_DIR/$BACKEND_LABEL.plist"
FRONTEND_PLIST="$LAUNCH_DIR/$FRONTEND_LABEL.plist"
DAILY_PLIST="$LAUNCH_DIR/$DAILY_LABEL.plist"
DAILY_SCRIPT="$PROJECT_DIR/scripts/launchd/daily_signals.sh"

VENV_PY="$PROJECT_DIR/backend/venv/bin/python3"
NPM_BIN="$(command -v npm || true)"
NODE_BIN="$(command -v node || true)"

if [[ ! -x "$VENV_PY" ]]; then
  echo "❌ Não encontrei $VENV_PY — corre primeiro:"
  echo "    cd backend && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
if [[ -z "$NPM_BIN" || -z "$NODE_BIN" ]]; then
  echo "❌ npm/node não encontrados no PATH actual. Instala node (brew install node ou nvm)."
  exit 1
fi
NODE_DIR="$(dirname "$NODE_BIN")"

UVICORN="$PROJECT_DIR/backend/venv/bin/uvicorn"
if [[ ! -x "$UVICORN" ]]; then
  echo "❌ Não encontrei $UVICORN — reinstala o venv."
  exit 1
fi

# macOS 26+ não aceita FDA aplicado a Python.app/framework directamente.
# Criamos um wrapper .app bundle (CFBundleIdentifier=com.cristopher.backend),
# ad-hoc signed. O utilizador concede FDA UMA vez a esse bundle e o launchd
# invoca-o. Os processos filhos (uvicorn, python) herdam a identidade do bundle
# para efeitos de TCC.
WRAPPER_APP="$PROJECT_DIR/scripts/launchd/CristopherBackend.app"
WRAPPER_EXEC_DIR="$WRAPPER_APP/Contents/MacOS"
WRAPPER_EXEC="$WRAPPER_EXEC_DIR/CristopherBackend"
WRAPPER_INFO="$WRAPPER_APP/Contents/Info.plist"

mkdir -p "$WRAPPER_EXEC_DIR"

# Conteúdos desejados — escritos em variáveis para podermos comparar com o que
# já está em disco. Re-assinar o .app invalida a entrada FDA do utilizador, por
# isso só recriamos o bundle (e re-signing) se o conteúdo for diferente.
NEW_INFO=$(cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>CFBundleExecutable</key><string>CristopherBackend</string>
  <key>CFBundleIdentifier</key><string>com.cristopher.backend</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>CristopherBackend</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
EOF
)

# Wrapper sem 'exec': o bash mantém-se vivo como parent, o que ajuda o TCC a
# atribuir as syscalls do filho (uvicorn/Python) ao .app responsável.
NEW_EXEC=$(cat <<EOF
#!/bin/bash
cd "$PROJECT_DIR/backend"
"$UVICORN" main:app --host 0.0.0.0 --port 8001 &
CHILD=\$!
trap "kill \$CHILD 2>/dev/null" EXIT INT TERM
wait \$CHILD
EOF
)

CHANGED=0
if [[ ! -f "$WRAPPER_INFO" ]] || [[ "$(cat "$WRAPPER_INFO")" != "$NEW_INFO" ]]; then
  printf '%s\n' "$NEW_INFO" > "$WRAPPER_INFO"
  CHANGED=1
fi
if [[ ! -f "$WRAPPER_EXEC" ]] || [[ "$(cat "$WRAPPER_EXEC")" != "$NEW_EXEC" ]]; then
  printf '%s\n' "$NEW_EXEC" > "$WRAPPER_EXEC"
  chmod +x "$WRAPPER_EXEC"
  CHANGED=1
fi

# Só re-assina se houve mudança real — re-signing muda o hash da assinatura, o
# que invalida a entrada de Full Disk Access no TCC e força o utilizador a
# re-adicionar o .app à lista. Pular o re-signing aqui mantém o FDA estável.
if [[ "$CHANGED" -eq 1 ]] || ! codesign --verify "$WRAPPER_APP" >/dev/null 2>&1; then
  codesign --force --deep --sign - "$WRAPPER_APP" >/dev/null 2>&1 || {
    echo "⚠️  Não consegui ad-hoc sign o $WRAPPER_APP — TCC pode não funcionar."
  }
  if [[ "$CHANGED" -eq 1 ]]; then
    echo "ℹ️  Wrapper do backend re-assinado — se já tinhas dado Full Disk Access, REMOVE e VOLTA A ADICIONAR o .app em Privacy & Security."
  fi
fi

BACKEND_PROGRAM_XML="    <string>$WRAPPER_EXEC</string>"

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
$BACKEND_PROGRAM_XML
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$PROJECT_DIR/backend/venv/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
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

# Job diário dos Sinais IA: refresca outcomes + gera o sinal do dia às 08:30.
chmod +x "$DAILY_SCRIPT" 2>/dev/null || true
cat > "$DAILY_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$DAILY_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$DAILY_SCRIPT</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>8</integer>
    <key>Minute</key><integer>30</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/daily_signals.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/daily_signals.err.log</string>
</dict>
</plist>
EOF

# Recarregar (unload + load) para reflectir mudanças
launchctl unload "$BACKEND_PLIST" 2>/dev/null || true
launchctl unload "$FRONTEND_PLIST" 2>/dev/null || true
launchctl unload "$DAILY_PLIST" 2>/dev/null || true
launchctl load -w "$BACKEND_PLIST"
launchctl load -w "$FRONTEND_PLIST"
launchctl load -w "$DAILY_PLIST"

echo "✅ Instalado:"
echo "   $BACKEND_LABEL  →  http://localhost:8001"
echo "   $FRONTEND_LABEL →  http://localhost:3001"
echo "   $DAILY_LABEL → sinais IA diários às 08:30"
echo ""
echo "Logs em: $LOG_DIR"
echo "Para parar: ./scripts/launchd/uninstall.sh"
echo ""
echo "📌 Para Screen Time (Apple) funcionar:"
echo "   1. System Settings → Privacy & Security → Full Disk Access"
echo "   2. REMOVE quaisquer entradas antigas tipo 'python3' ou 'Python'"
echo "   3. Carrega no '+' e adiciona este bundle:"
echo "        $WRAPPER_APP"
echo "   4. Activa o toggle"
echo "   5. Volta a correr este script para reiniciar o backend com FDA"
