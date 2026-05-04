#!/bin/bash
# hook-ignores-other-prompts-test.sh — hook must be a no-op for prompts
# that are not /todo. In particular: /jot, /todo-list, /todo-clean,
# and arbitrary user text.
#
# Failing condition: any pending-*.json is written for a non-/todo prompt,
# OR anything is printed to stdout.
set -euo pipefail

THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$THIS_DIR/../../.." && pwd)"
ORCH="$REPO/skills/todo/scripts/todo-orchestrator.sh"

TMP=$(mktemp -d /tmp/todo-other-test.XXXXXX)
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

run_hook() {
  local prompt="$1"
  local hook_input
  hook_input=$(python3 -c '
import json,sys
print(json.dumps({
  "prompt": sys.argv[1],
  "session_id": "sess-x",
  "transcript_path": "",
  "cwd": sys.argv[2],
}))
' "$prompt" "$TMP")
  printf '%s' "$hook_input" | bash "$ORCH"
}

# These prompts must NOT produce output or pending files.
for p in "/jot something" "hello world" "/todo-list" "/todo-clean"; do
  out=$(run_hook "$p" || true)
  if [ -n "$out" ]; then
    echo "FAIL: got output for prompt '$p': $out" >&2
    exit 1
  fi
  if ls "$TMP/Todos/.todo-state/"pending-*.json >/dev/null 2>&1; then
    echo "FAIL: pending file created for prompt '$p'" >&2
    exit 1
  fi
done

echo "PASS: hook is no-op for /jot, arbitrary text, /todo-list, /todo-clean"
