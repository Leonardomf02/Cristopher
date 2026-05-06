#!/usr/bin/env bash
# Mostra estado dos LaunchAgents do Cristopher.
set -euo pipefail

echo "── LaunchAgents ──────────────────────────────────────"
launchctl list | grep cristopher || echo "  (nenhum carregado)"
echo ""
echo "── Portas ────────────────────────────────────────────"
lsof -nP -iTCP:8000 -sTCP:LISTEN 2>/dev/null | tail -n +2 | awk '{print "  backend  → PID " $2 " (" $1 ")"}' || true
lsof -nP -iTCP:5173 -sTCP:LISTEN 2>/dev/null | tail -n +2 | awk '{print "  frontend → PID " $2 " (" $1 ")"}' || true
echo ""
echo "── Logs (últimas 5 linhas) ───────────────────────────"
LOG_DIR="$(cd "$(dirname "$0")" && pwd)/logs"
for f in backend frontend; do
  if [[ -f "$LOG_DIR/$f.err.log" ]]; then
    echo "── $f.err.log ──"
    tail -n 5 "$LOG_DIR/$f.err.log"
  fi
done
