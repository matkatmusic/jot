#!/bin/bash
# namespace-roundtrip-test.sh — full orchestrator → todo-orchestrator path
# on a "/jot:todo <idea>" prompt. Verifies the dispatcher's namespace
# normalisation lets the sub-orchestrator produce a pending-*.json.
#
# Failing condition: no pending file written, or .prompt in the forwarded
# JSON still carries the /jot: prefix.
set -euo pipefail

THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$THIS_DIR/../../.." && pwd)"
ORCH="$REPO/scripts/orchestrator.sh"

TMP=$(mktemp -d /tmp/todo-ns-test.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

cd "$TMP"
git init -q
git config user.email test@test.test
git config user.name test
git commit --allow-empty -qm init

export CLAUDE_PLUGIN_ROOT="$REPO"
export CLAUDE_PLUGIN_DATA="$TMP/.plugin-data"
export TODO_LOG_FILE="$TMP/todo-log.txt"
mkdir -p "$CLAUDE_PLUGIN_DATA"

hook_input=$(python3 -c '
import json,sys
print(json.dumps({
  "prompt": "/jot:todo a namespaced idea",
  "session_id": "sess-ns1",
  "transcript_path": "",
  "cwd": sys.argv[1],
}))
' "$TMP")

stdout=$(printf '%s' "$hook_input" | bash "$ORCH")
if [ -n "$stdout" ]; then
  echo "FAIL: orchestrator printed on stdout: $stdout" >&2; exit 1
fi

pending=$(ls "$TMP/Todos/.todo-state/"pending-*.json 2>/dev/null | head -1)
if [ -z "$pending" ]; then
  echo "FAIL: no pending-*.json after /jot:todo prompt" >&2
  ls -la "$TMP/Todos/.todo-state/" >&2 || true
  exit 1
fi

got_idea=$(jq -r '.idea' "$pending")
if [ "$got_idea" != "a namespaced idea" ]; then
  echo "FAIL: idea mismatch. expected='a namespaced idea' got='$got_idea'" >&2
  exit 1
fi

echo "PASS: /jot:todo <idea> round-trips through orchestrator and writes pending JSON"
