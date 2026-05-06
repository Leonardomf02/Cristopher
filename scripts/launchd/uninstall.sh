#!/usr/bin/env bash
# Remove os LaunchAgents do Cristopher (backend + frontend) e mata os processos.
set -euo pipefail

LAUNCH_DIR="$HOME/Library/LaunchAgents"
BACKEND_PLIST="$LAUNCH_DIR/com.cristopher.backend.plist"
FRONTEND_PLIST="$LAUNCH_DIR/com.cristopher.frontend.plist"

for p in "$BACKEND_PLIST" "$FRONTEND_PLIST"; do
  if [[ -f "$p" ]]; then
    launchctl unload "$p" 2>/dev/null || true
    rm -f "$p"
    echo "🗑  Removido: $p"
  fi
done

echo "✅ Autostart desligado."
