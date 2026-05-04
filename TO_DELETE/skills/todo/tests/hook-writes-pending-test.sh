#!/bin/bash
# hook-writes-pending-test.sh — simulate the UserPromptSubmit hook JSON
# stdin, verify todo-orchestrator.sh writes a pending-*.json file with the
# expected fields and exits silently (no emit_block output).
#
# Failing condition: missing pending file, malformed JSON, wrong fields,
# or the hook prints anything on stdout (would replace the user prompt).
set -euo pipefail

THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$THIS_DIR/../../.." && pwd)"
ORCH="$REPO/skills/todo/scripts/todo-orchestrator.sh"

TMP=$(mktemp -d /tmp/todo-hook-test.XXXXXX)
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
  "prompt": "/todo implement colorblind-safe palette",
  "session_id": "sess-abc123",
  "transcript_path": "/tmp/some-transcript.jsonl",
  "cwd": sys.argv[1],
}))
' "$TMP")

stdout=$(printf '%s' "$hook_input" | bash "$ORCH")

if [ -n "$stdout" ]; then
  echo "FAIL: orchestrator printed on stdout (would replace user prompt):" >&2
  echo "$stdout" >&2
  exit 1
fi

pending=$(ls "$TMP/Todos/.todo-state/"pending-*.json 2>/dev/null | head -1)
if [ -z "$pending" ]; then
  echo "FAIL: no pending-*.json written" >&2
  ls -la "$TMP/Todos/.todo-state/" 2>&1 >&2 || true
  exit 1
fi

# jq-verify the fields.
got_idea=$(jq -r '.idea' "$pending")
got_cwd=$(jq -r '.cwd' "$pending")
got_repo=$(jq -r '.repo_root' "$pending")
got_session=$(jq -r '.session_id' "$pending")
got_scripts=$(jq -r '.todo_scripts_dir' "$pending")
got_pending=$(jq -r '.pending_file' "$pending")

[ "$got_idea" = "implement colorblind-safe palette" ] || { echo "FAIL: idea mismatch: $got_idea" >&2; exit 1; }
[ "$got_cwd" = "$TMP" ] || { echo "FAIL: cwd mismatch: $got_cwd vs $TMP" >&2; exit 1; }
[ "$got_repo" = "$TMP" ] || { echo "FAIL: repo_root mismatch: $got_repo" >&2; exit 1; }
[ "$got_session" = "sess-abc123" ] || { echo "FAIL: session_id mismatch: $got_session" >&2; exit 1; }
[ "$got_scripts" = "$REPO/skills/todo/scripts" ] || { echo "FAIL: todo_scripts_dir mismatch: $got_scripts" >&2; exit 1; }
[ "$got_pending" = "$pending" ] || { echo "FAIL: pending_file self-ref wrong: $got_pending vs $pending" >&2; exit 1; }

echo "PASS: hook writes pending JSON with all required fields and exits silently"
