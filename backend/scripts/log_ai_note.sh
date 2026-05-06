#!/bin/bash
# Posts an AI Note to the Cristopher backend, tagged with the current project.
# Usage:
#   echo -e "bullet 1\nbullet 2" | log_ai_note.sh
#   log_ai_note.sh "bullet 1" "bullet 2" "bullet 3"
# Designed to be called by Claude at task end from any project directory.
# Silently no-ops if the backend is down — never blocks the assistant's flow.

set -e

BACKEND="${CRISTOPHER_BACKEND:-http://localhost:8000}"
HOME_PREFIX="$HOME/"

cwd=$(pwd)
case "$cwd" in
  "$HOME_PREFIX"*) project_path="${cwd#$HOME_PREFIX}" ;;
  *) project_path="$(basename "$cwd")" ;;
esac

if [ "$#" -gt 0 ]; then
  bullets_input=$(printf '%s\n' "$@")
else
  bullets_input=$(cat)
fi

[ -z "$bullets_input" ] && exit 0

payload=$(printf '%s' "$bullets_input" | python3 -c '
import json, sys
lines = [l.strip().lstrip("- ").strip() for l in sys.stdin.read().splitlines() if l.strip()]
print(json.dumps({"bullets": lines}))
' 2>/dev/null || true)

[ -z "$payload" ] && exit 0

encoded=$(python3 -c "import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=''))" "$project_path" 2>/dev/null || true)
[ -z "$encoded" ] && exit 0

curl -sf --max-time 3 \
  -H "Content-Type: application/json" \
  -X POST "$BACKEND/api/code-activity/projects/$encoded/notes/from-bullets" \
  -d "$payload" >/dev/null 2>&1 || true

exit 0
