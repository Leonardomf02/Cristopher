#!/usr/bin/env bash
# Setup do Cristopher num GitHub Codespace.
# Instala dependências do backend e frontend e regista os comandos de arranque
# como tasks do VS Code para tu não teres de te lembrar.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "── Backend (Python) ──"
cd "$REPO_ROOT/backend"
python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements.txt

# Cria .env mínimo se não existir (utilizador pode preencher se quiser)
if [[ ! -f .env ]]; then
  cat > .env <<'EOF'
# Preenche se quiseres usar features que dependem de APIs externas.
# Para programar/editar código sem tocar nestas features, podes deixar vazio.
FMP_API_KEY=
FINNHUB_API_KEY=
AI_API_KEY=
ALLOWED_ORIGINS=
DATABASE_URL=sqlite:///./cristopher.db
UPLOADS_DIR=uploads
TRACKER_AUTOSTART=0
EOF
fi

echo ""
echo "── Frontend (Node) ──"
cd "$REPO_ROOT/frontend"
npm install --silent

echo ""
echo "── Claude Code (CLI) ──"
npm install -g @anthropic-ai/claude-code 2>/dev/null || echo "(falhou — instala manualmente: npm install -g @anthropic-ai/claude-code)"

echo ""
echo "✅ Setup terminado."
echo ""
echo "Para arrancar:"
echo "  Terminal 1: cd backend && source venv/bin/activate && uvicorn main:app --reload --host 0.0.0.0 --port 8000"
echo "  Terminal 2: cd frontend && npm run dev"
echo ""
echo "Para correr o Claude Code: 'claude' em qualquer terminal."
