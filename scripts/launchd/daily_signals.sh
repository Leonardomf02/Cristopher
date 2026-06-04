#!/usr/bin/env bash
# Job diário dos Sinais IA de investimento. Corre via LaunchAgent
# (com.cristopher.dailysignals) a uma hora fixa, contra o backend local.
#
# 1. Refresca a performance de todos os sinais → a calibração deixa de depender
#    de o utilizador carregar no botão (amostra deixa de ser enviesada).
# 2. Gera o sinal do dia de forma idempotente (skip_if_exists_today): se já houve
#    geração hoje, o backend devolve o existente sem gastar nova chamada IA.
#
# Falhas são silenciosas (|| true): o backend pode estar a arrancar; tenta amanhã.
set -uo pipefail

BASE="http://localhost:8001/api/investments/signals"
LOG_DIR="$(cd "$(dirname "$0")" && pwd)/logs"
mkdir -p "$LOG_DIR"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"

echo "[$STAMP] daily_signals: refresh-all-performance" >> "$LOG_DIR/daily_signals.log"
curl -fsS -X POST "$BASE/refresh-all-performance" -m 120 >> "$LOG_DIR/daily_signals.log" 2>&1 || true

echo "" >> "$LOG_DIR/daily_signals.log"
echo "[$STAMP] daily_signals: generate (idempotente)" >> "$LOG_DIR/daily_signals.log"
curl -fsS -X POST "$BASE/generate" \
  -H 'Content-Type: application/json' \
  -d '{"skip_if_exists_today": true}' \
  -m 300 >> "$LOG_DIR/daily_signals.log" 2>&1 || true

echo "" >> "$LOG_DIR/daily_signals.log"
