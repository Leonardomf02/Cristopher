#!/bin/bash
# Arranca Cristopher (backend + frontend). Mata o que estiver nas portas.
set -e

PROJECT="Cristopher"
BACKEND_PORT=8001
FRONTEND_PORT=3001
ROOT="$(cd "$(dirname "$0")" && pwd)"

kill_port() {
  local port=$1
  local pids
  pids=$(lsof -nP -iTCP:$port -sTCP:LISTEN -t 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "⚠  Porta $port ocupada — a matar PIDs: $pids"
    kill -9 $pids 2>/dev/null || true
    sleep 0.5
  fi
}

kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"

echo "🚀 A arrancar $PROJECT..."

(
  cd "$ROOT/backend"
  source venv/bin/activate
  exec uvicorn main:app --reload --port "$BACKEND_PORT"
) &
BACKEND_PID=$!

sleep 2

(
  cd "$ROOT/frontend"
  exec npm run dev
) &
FRONTEND_PID=$!

cleanup() {
  echo ""
  echo "🛑 A parar $PROJECT..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

echo ""
echo "✅ $PROJECT a correr:"
echo "   Frontend: http://localhost:$FRONTEND_PORT"
echo "   Backend:  http://localhost:$BACKEND_PORT (docs em /docs)"
echo ""

(sleep 3 && open "http://localhost:$FRONTEND_PORT") &

wait
