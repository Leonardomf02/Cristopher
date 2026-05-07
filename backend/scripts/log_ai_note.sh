#!/bin/bash
# Regista uma Nota IA do Cristopher.
#
# Uso:
#   echo -e "bullet 1\nbullet 2" | log_ai_note.sh
#   log_ai_note.sh "bullet 1" "bullet 2" "bullet 3"
#
# Comportamento:
# - No Mac (backend Cristopher acessível): POST directo. Nota fica na DB local.
# - Em GitHub Codespace ($CODESPACES=true) ou se o backend não responde:
#   anexa as notas a `ai-notes-pending.md` no root do repo, faz commit + push.
#   Quando voltares ao Mac, corres `process_pending_ai_notes.sh` para
#   processar e esvaziar o ficheiro.
#
# Silencioso em caso de falha — nunca bloqueia o flow do assistente.
set -e

BACKEND="${CRISTOPHER_BACKEND:-http://localhost:8000}"
REPO_ROOT="$(git -C "$(pwd)" rev-parse --show-toplevel 2>/dev/null || true)"
HOME_PREFIX="$HOME/"

cwd=$(pwd)
case "$cwd" in
  "$HOME_PREFIX"*) project_path="${cwd#$HOME_PREFIX}" ;;
  *) project_path="$(basename "$cwd")" ;;
esac

# ── recolhe os bullets (args ou stdin) ────────────────────────────
if [ "$#" -gt 0 ]; then
  bullets_input=$(printf '%s\n' "$@")
else
  bullets_input=$(cat)
fi
[ -z "$bullets_input" ] && exit 0

# ── Modo 1: Codespace → fila no repo ──────────────────────────────
is_codespace=0
if [ "${CODESPACES:-}" = "true" ] || [ -n "${CODESPACE_NAME:-}" ]; then
  is_codespace=1
fi

# Se não estamos em Codespace, primeiro tentamos o backend local.
if [ "$is_codespace" -eq 0 ]; then
  payload=$(printf '%s' "$bullets_input" | python3 -c '
import json, sys
lines = [l.strip().lstrip("- ").strip() for l in sys.stdin.read().splitlines() if l.strip()]
print(json.dumps({"bullets": lines}))
' 2>/dev/null || true)

  encoded=$(python3 -c "import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=''))" "$project_path" 2>/dev/null || true)

  if [ -n "$payload" ] && [ -n "$encoded" ]; then
    if curl -sf --max-time 3 \
         -H "Content-Type: application/json" \
         -X POST "$BACKEND/api/code-activity/projects/$encoded/notes/from-bullets" \
         -d "$payload" >/dev/null 2>&1; then
      exit 0
    fi
  fi
  # Backend não respondeu — passa ao modo fila (silencioso).
fi

# ── Modo 2: fila em ai-notes-pending.md no repo ───────────────────
[ -z "$REPO_ROOT" ] && exit 0  # não estamos num repo, desistir

PENDING_FILE="$REPO_ROOT/ai-notes-pending.md"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

{
  printf '\n## %s — %s\n\n' "$TIMESTAMP" "$project_path"
  printf '%s\n' "$bullets_input" | sed -E 's/^[[:space:]]*-?[[:space:]]*//; s/^/- /'
  printf '\n---\n'
} >> "$PENDING_FILE"

# Em Codespace tenta também fazer commit + push para o Mac ver mais tarde.
# (Em Mac local não fazemos isso — apenas anexamos. O utilizador faz commit
# explícito quando quiser.)
if [ "$is_codespace" -eq 1 ] && command -v git >/dev/null 2>&1; then
  cd "$REPO_ROOT" || exit 0
  git add ai-notes-pending.md 2>/dev/null || true
  if ! git diff --cached --quiet 2>/dev/null; then
    git -c user.email="${GIT_AUTHOR_EMAIL:-codespace@cristopher.local}" \
        -c user.name="${GIT_AUTHOR_NAME:-Codespace}" \
        commit -q -m "ai-note: $project_path @ $TIMESTAMP" 2>/dev/null || true
    git push -q 2>/dev/null || true
  fi
fi

exit 0
