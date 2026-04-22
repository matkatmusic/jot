#!/bin/bash
# namespace-roundtrip-test.sh — full orchestrator → todo-list-orchestrator
# path on a "/jot:todo-list" prompt. Verifies namespace normalisation makes
# the sub-orchestrator produce its emit_block output.
#
# Failing condition: no block JSON printed, or the block's reason doesn't
# list the seeded TODO.
set -euo pipefail

THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$THIS_DIR/../../.." && pwd)"
ORCH="$REPO/scripts/orchestrator.sh"

TMP=$(mktemp -d /tmp/todo-list-ns-test.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

cd "$TMP"
git init -q
git config user.email t@t.t
git config user.name t
git commit --allow-empty -qm init

mkdir -p Todos
cat > Todos/042_namespaced.md <<'EOF'
---
id: 042
title: namespace round-trip canary
status: open
created: 2026-04-22T10:00:00-07:00
branch: main
---
body
EOF

export CLAUDE_PLUGIN_ROOT="$REPO"
export CLAUDE_PLUGIN_DATA="$TMP/.plugin-data"
mkdir -p "$CLAUDE_PLUGIN_DATA"

hook_input=$(python3 -c '
import json,sys
print(json.dumps({
  "prompt": "/jot:todo-list",
  "session_id": "sess-ns2",
  "transcript_path": "",
  "cwd": sys.argv[1],
}))
' "$TMP")

out=$(printf '%s' "$hook_input" | bash "$ORCH")

if ! printf '%s' "$out" | grep -q '"decision": "block"'; then
  echo "FAIL: no emit_block output for /jot:todo-list" >&2
  echo "got: $out" >&2
  exit 1
fi
if ! printf '%s' "$out" | grep -q 'ID: 042'; then
  echo "FAIL: seeded ID 042 not present in block" >&2
  echo "got: $out" >&2
  exit 1
fi
if ! printf '%s' "$out" | grep -q '1 open TODO'; then
  echo "FAIL: count line missing" >&2
  echo "got: $out" >&2
  exit 1
fi

echo "PASS: /jot:todo-list round-trips through orchestrator and renders the TODO list"
