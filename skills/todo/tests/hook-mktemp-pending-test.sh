#!/bin/bash
# hook-mktemp-pending-test.sh — guards against the BSD-mktemp literal-X
# regression. Runs the orchestrator twice with /todo prompts and asserts:
#   1. Two distinct pending-*.json files exist (no collision).
#   2. Neither file is named literally `pending-XXXXXX.json` (proves the
#      template was substituted by mktemp, not used verbatim).
# Failing condition: only 1 pending file appears, or a literal-X filename
# exists — both indicate the BSD mktemp suffix bug has returned.
set -euo pipefail

THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$THIS_DIR/../../.." && pwd)"
ORCH="$REPO/scripts/orchestrator.sh"

TMP=$(mktemp -d /tmp/todo-mktemp-test.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

cd "$TMP"
git init -q
git config user.email t@t.t
git config user.name t
git commit --allow-empty -qm init

export CLAUDE_PLUGIN_ROOT="$REPO"
export CLAUDE_PLUGIN_DATA="$TMP/.plugin-data"
mkdir -p "$CLAUDE_PLUGIN_DATA"

mk_input() {
  python3 -c '
import json,sys
print(json.dumps({
  "prompt": sys.argv[1],
  "session_id": "sess-mktemp",
  "transcript_path": "",
  "cwd": sys.argv[2],
}))
' "$1" "$TMP"
}

printf '%s' "$(mk_input "/todo first idea" "$TMP")" | bash "$ORCH"
printf '%s' "$(mk_input "/todo second idea" "$TMP")" | bash "$ORCH"

count=$(find "$TMP/Todos/.todo-state" -maxdepth 1 -name 'pending-*.json' | wc -l | tr -d ' ')
if [ "$count" != "2" ]; then
  echo "FAIL: expected 2 pending files, got $count" >&2
  ls "$TMP/Todos/.todo-state" >&2 || true
  exit 1
fi

if [ -f "$TMP/Todos/.todo-state/pending-XXXXXX.json" ]; then
  echo "FAIL: literal pending-XXXXXX.json exists — mktemp template still broken" >&2
  exit 1
fi

# Sanity: each file must contain its corresponding idea string.
if ! grep -lq "first idea" "$TMP/Todos/.todo-state"/pending-*.json; then
  echo "FAIL: no pending file contains 'first idea'" >&2; exit 1
fi
if ! grep -lq "second idea" "$TMP/Todos/.todo-state"/pending-*.json; then
  echo "FAIL: no pending file contains 'second idea' — second invocation lost" >&2
  exit 1
fi

echo "PASS: two distinct pending files created with substituted names; both ideas present"
