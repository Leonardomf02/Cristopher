#!/bin/bash
# Processa notas IA pendentes em ai-notes-pending.md (geradas em viagem
# via Codespace) e regista cada bloco na DB Cristopher do Mac.
#
# Uso (no Mac, depois de chegares de viagem):
#   ./backend/scripts/process_pending_ai_notes.sh
#
# Cada bloco está delimitado por "---" no ficheiro. Cabeçalho do bloco:
#   ## <timestamp> — <project_path>
# Conteúdo: bullets em "- ...".
set -e

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
[ -z "$REPO_ROOT" ] && { echo "❌ não estou num repo"; exit 1; }

PENDING="$REPO_ROOT/ai-notes-pending.md"
[ ! -s "$PENDING" ] && { echo "✅ sem notas pendentes"; exit 0; }

BACKEND="${CRISTOPHER_BACKEND:-http://localhost:8000}"
if ! curl -sf --max-time 3 "$BACKEND/api/health" >/dev/null 2>&1; then
  echo "❌ backend não responde em $BACKEND — confirma que está a correr"
  exit 1
fi

# Parse com Python: separa blocos por "---", extrai project_path do header e bullets.
python3 - "$PENDING" "$BACKEND" <<'PY'
import sys, re, json, urllib.parse, urllib.request

path, backend = sys.argv[1], sys.argv[2]
with open(path) as f:
    content = f.read()

# Split por "---" em linhas isoladas; ignora blocos vazios.
blocks = [b.strip() for b in re.split(r'^---\s*$', content, flags=re.M) if b.strip()]
if not blocks:
    print("✅ ficheiro vazio")
    sys.exit(0)

processed, failed = 0, 0
for blk in blocks:
    lines = [l.rstrip() for l in blk.splitlines()]
    # Header: ## <ts> — <path>  (em-dash é U+2014)
    header_match = next((re.match(r'^##\s+(\S+)\s+[—-]\s+(.+)$', l) for l in lines if l.startswith('##')), None)
    if not header_match:
        failed += 1
        continue
    project_path = header_match.group(2).strip()
    bullets = [re.sub(r'^[-\s]+', '', l).strip() for l in lines if l.lstrip().startswith('-')]
    bullets = [b for b in bullets if b]
    if not bullets:
        continue
    encoded = urllib.parse.quote(project_path, safe='')
    url = f"{backend}/api/code-activity/projects/{encoded}/notes/from-bullets"
    payload = json.dumps({"bullets": bullets}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=5).read()
        processed += 1
        print(f"  ✓ {project_path}: {len(bullets)} bullets")
    except Exception as e:
        failed += 1
        print(f"  ✗ {project_path}: {e}")

print(f"\nProcessadas: {processed} · Falhadas: {failed}")
sys.exit(0 if failed == 0 else 2)
PY

# Esvazia o ficheiro (mantém-no para futuras notas).
: > "$PENDING"

cd "$REPO_ROOT"
git add ai-notes-pending.md 2>/dev/null || true
if ! git diff --cached --quiet 2>/dev/null; then
  git commit -q -m "ai-notes: processadas e esvaziadas no Mac" 2>/dev/null || true
  git push -q 2>/dev/null || true
fi

echo "✅ ai-notes-pending.md esvaziado e sincronizado"
