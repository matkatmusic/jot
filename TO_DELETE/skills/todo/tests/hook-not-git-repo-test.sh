#!/bin/bash
# hook-not-git-repo-test.sh — outside a git repo, the hook must emit_block
# with a git-required message and NOT write a pending file.
set -euo pipefail

THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$THIS_DIR/../../.." && pwd)"
ORCH="$REPO/skills/todo/scripts/todo-orchestrator.sh"

TMP=$(mktemp -d /tmp/todo-nogit-test.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

export CLAUDE_PLUGIN_ROOT="$REPO"
export CLAUDE_PLUGIN_DATA="$TMP/.plugin-data"
export TODO_LOG_FILE="$TMP/todo-log.txt"
mkdir -p "$CLAUDE_PLUGIN_DATA"

hook_input=$(python3 -c '
import json,sys
print(json.dumps({
  "prompt": "/todo anything",
  "session_id": "sess-x",
  "transcript_path": "",
  "cwd": sys.argv[1],
}))
' "$TMP")

stdout=$(printf '%s' "$hook_input" | bash "$ORCH" || true)

if ! printf '%s' "$stdout" | grep -q 'requires a git repository'; then
  echo "FAIL: expected block about 'git repository', got: $stdout" >&2
  exit 1
fi

if [ -d "$TMP/Todos/.todo-state" ]; then
  echo "FAIL: state dir created even though not in git repo" >&2
  exit 1
fi

echo "PASS: hook emits git-required block outside a repo and writes no pending file"
