#!/usr/bin/env bash
# Mostra estado dos LaunchAgents do Cristopher.
set -euo pipefail

echo "── LaunchAgents ──────────────────────────────────────"
launchctl list | grep cristopher || echo "  (nenhum carregado)"
echo ""
echo "── Portas ────────────────────────────────────────────"
lsof -nP -iTCP:8001 -sTCP:LISTEN 2>/dev/null | tail -n +2 | awk '{print "  backend  → PID " $2 " (" $1 ")"}' || true
lsof -nP -iTCP:3001 -sTCP:LISTEN 2>/dev/null | tail -n +2 | awk '{print "  frontend → PID " $2 " (" $1 ")"}' || true
echo ""
echo "── Logs (últimas 5 linhas) ───────────────────────────"
LOG_DIR="$(cd "$(dirname "$0")" && pwd)/logs"
for f in backend frontend; do
  if [[ -f "$LOG_DIR/$f.err.log" ]]; then
    echo "── $f.err.log ──"
    tail -n 5 "$LOG_DIR/$f.err.log"
  fi
done
if [[ -f "$LOG_DIR/daily_signals.log" ]]; then
  echo "── daily_signals.log ──"
  tail -n 8 "$LOG_DIR/daily_signals.log"
fi
