#!/bin/bash
# Claude Code PreToolUse hook: snapshots a file before Edit/Write/MultiEdit
# so the AI Notes pipeline has a baseline to diff against.
# Reads the tool-call payload from stdin (JSON) and POSTs to the backend.

set -e

payload=$(cat)
path=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)

[ -z "$path" ] && exit 0
[ -f "$path" ] || exit 0

encoded=$(python3 -c "import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=''))" "$path" 2>/dev/null || true)
[ -z "$encoded" ] && exit 0

curl -sf --max-time 2 -X POST "http://localhost:8888/code-activity/snapshot?path=$encoded" >/dev/null 2>&1 || true
exit 0
