#!/bin/bash
# plate-e2e-live.sh — end-to-end test for the plate skill.
#
# Creates a temp git repo, fires /plate via the hook orchestrator,
# stacks multiple plates, then tests --show, --next, --done.
#
# Usage:
#   bash skills/plate/tests/plate-e2e-live.sh           # run tests immediately
#   bash skills/plate/tests/plate-e2e-live.sh --attach  # pause before tests so you can
#                                                       # tmux attach -t plate-e2e
set -uo pipefail

THIS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$THIS_DIR/../../.." && pwd)"
: "${CLAUDE_PLUGIN_ROOT:=$REPO_ROOT}"
: "${CLAUDE_PLUGIN_DATA:=$REPO_ROOT/.plate-e2e-data}"
export CLAUDE_PLUGIN_ROOT CLAUDE_PLUGIN_DATA
mkdir -p "$CLAUDE_PLUGIN_DATA"

source "$REPO_ROOT/common/scripts/silencers.sh"
source "$REPO_ROOT/common/scripts/tmux.sh"
source "$REPO_ROOT/common/scripts/tmux-launcher.sh"
source "$REPO_ROOT/common/scripts/git.sh"

PLATE_SH="$REPO_ROOT/skills/plate/scripts/plate-orchestrator.sh"
DONE_SH="$REPO_ROOT/skills/plate/scripts/done.sh"
PYTHON_DIR="$REPO_ROOT/common/scripts/plate"

ATTACH_MODE=false
if [ "${1:-}" = "--attach" ]; then
  ATTACH_MODE=true
fi

PASS=0
FAIL=0
TEST_REPO=""
TEST_SESSION="plate-e2e"

pass() { printf "PASS: %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "FAIL: %s\n" "$1"; FAIL=$((FAIL + 1)); }

cleanup() {
  tmux_kill_session "$TEST_SESSION"
  [ -n "$TEST_REPO" ] && rm -rf "$TEST_REPO"
  rm -rf "$CLAUDE_PLUGIN_DATA"
}
trap cleanup EXIT

# ── Helpers ───────────────────────────────────────────────────────────────

create_test_repo() {
  TEST_REPO=$(mktemp -d /tmp/plate-e2e.XXXXXX)
  cd "$TEST_REPO"
  git init -q
  git checkout -b main -q 2>/dev/null
  echo "initial" > file.txt
  git add file.txt
  git commit -q -m "initial commit"
  echo "$TEST_REPO"
}

# usage: fire_plate <cwd> <prompt> [session_id]
# Pipes hook JSON to plate-orchestrator.sh, captures output.
# usage: fire_plate <cwd> <prompt> [session_id]
# Pipes hook JSON to plate-orchestrator.sh, prints stdout only.
# Stderr flows to the caller (test ignores it).
fire_plate() {
  local cwd="$1" prompt="$2" sid="${3:-$(uuidgen | tr 'A-Z' 'a-z')}"
  local payload
  payload=$(jq -nc \
    --arg sid "$sid" \
    --arg cwd "$cwd" \
    --arg prompt "$prompt" \
    '{session_id:$sid,transcript_path:"",cwd:$cwd,prompt:$prompt,hook_event_name:"UserPromptSubmit"}')
  printf '%s' "$payload" | hide_errors bash "$PLATE_SH"
}

# ════════════════════════════════════════════════════════════════════════
echo "═══ Setting up test repo ═══"
create_test_repo
echo "  repo: $TEST_REPO"

# Create a tmux session for observing the test
tmux_kill_session "$TEST_SESSION"
tmux_new_session "$TEST_SESSION"

if [ "$ATTACH_MODE" = true ]; then
  echo ""
  echo "  Tmux session '$TEST_SESSION' is ready."
  echo "  Attach in another terminal:  tmux attach -t $TEST_SESSION"
  echo ""
  echo "  Press ENTER to start tests..."
  read -r
fi

# Use a stable session ID so instance JSON accumulates
SESSION_ID="plate-e2e-test-$$"

# ════════════════════════════════════════════════════════════════════════
echo "═══ Test 1: first /plate push (virgin repo — path 2) ═══"

echo "change 1" > "$TEST_REPO/feature.txt"
git -C "$TEST_REPO" add feature.txt
git -C "$TEST_REPO" commit -q -m "add feature.txt"

# Push creates a tmux session that fails in test env (no terminal).
# The instance JSON + stack get written before the tmux step.
# Verify instance creation rather than emit_block output.
fire_plate "$TEST_REPO" "/plate" "$SESSION_ID"

# Verify instance file was created
PLATE_ROOT="$TEST_REPO/.plate"
INSTANCE_FILE="$PLATE_ROOT/instances/${SESSION_ID}.json"
if [ -f "$INSTANCE_FILE" ]; then
  pass "1b: instance JSON created"
else
  fail "1b: instance JSON missing at $INSTANCE_FILE"
fi

# Verify stack has 1 plate
STACK_COUNT=$(python3 -c "import json; d=json.load(open('$INSTANCE_FILE')); print(len(d.get('stack',[])))")
if [ "$STACK_COUNT" -eq 1 ]; then
  pass "1c: stack has 1 plate"
else
  fail "1c: expected 1 plate, got $STACK_COUNT"
fi

# ════════════════════════════════════════════════════════════════════════
echo "═══ Test 2: second /plate push (path 1 — existing session) ═══"

# Clean stale tmux-launch lock from test 1 (tmux session creation fails in test env)
hide_errors rmdir "$CLAUDE_PLUGIN_DATA/tmux-launch.lock"

echo "change 2" >> "$TEST_REPO/feature.txt"
git -C "$TEST_REPO" add feature.txt
git -C "$TEST_REPO" commit -q -m "update feature.txt"

OUTPUT=$(fire_plate "$TEST_REPO" "/plate" "$SESSION_ID")
if echo "$OUTPUT" | grep -qF "pushed"; then
  pass "2a: second push succeeded"
else
  fail "2a: expected 'pushed', got: $OUTPUT"
fi

STACK_COUNT=$(python3 -c "import json; d=json.load(open('$INSTANCE_FILE')); print(len(d.get('stack',[])))")
if [ "$STACK_COUNT" -eq 2 ]; then
  pass "2b: stack has 2 plates"
else
  fail "2b: expected 2 plates, got $STACK_COUNT"
fi

# ════════════════════════════════════════════════════════════════════════
echo "═══ Test 3: /plate --show ═══"

OUTPUT=$(fire_plate "$TEST_REPO" "/plate --show" "$SESSION_ID")
if echo "$OUTPUT" | grep -qF "[plate] tree:"; then
  pass "3a: --show emits tree"
else
  fail "3a: expected tree output, got: $OUTPUT"
fi

if [ -f "$PLATE_ROOT/tree.md" ]; then
  pass "3b: tree.md file exists"
else
  fail "3b: tree.md not created"
fi

# ════════════════════════════════════════════════════════════════════════
echo "═══ Test 4: /plate --next ═══"

OUTPUT=$(fire_plate "$TEST_REPO" "/plate --next" "$SESSION_ID")
if echo "$OUTPUT" | grep -qF "[plate]"; then
  pass "4a: --next emits output"
else
  fail "4a: expected output, got: $OUTPUT"
fi

# ════════════════════════════════════════════════════════════════════════
echo "═══ Test 5: /plate --done (direct, no skill body) ═══"

# Count commits before done
COMMITS_BEFORE=$(git -C "$TEST_REPO" rev-list --count HEAD)

# Run done.sh directly (bypasses skill body — no AskUserQuestion needed
# since there are no delegated children)
cd "$TEST_REPO"
# done.sh may exit nonzero if git apply hits conflicts during replay —
# the conflicts are resolved via --3way and commits still succeed.
# Check output for "Committed" rather than exit code.
DONE_OUTPUT=$(CLAUDE_PLUGIN_ROOT="$CLAUDE_PLUGIN_ROOT" \
  CLAUDE_PLUGIN_DATA="$CLAUDE_PLUGIN_DATA" \
  hide_errors bash "$DONE_SH" "$SESSION_ID")

if echo "$DONE_OUTPUT" | grep -qF "Committed"; then
  pass "5a: done output mentions commits"
else
  fail "5a: expected 'Committed' in output, got: $DONE_OUTPUT"
fi

# Verify new commits were created
COMMITS_AFTER=$(git -C "$TEST_REPO" rev-list --count HEAD)
NEW_COMMITS=$((COMMITS_AFTER - COMMITS_BEFORE))
if [ "$NEW_COMMITS" -ge 2 ]; then
  pass "5b: $NEW_COMMITS new commits created (expected >= 2)"
else
  fail "5b: expected >= 2 new commits, got $NEW_COMMITS"
fi

# Verify commit messages have [plate] prefix
PLATE_COMMITS=$(git -C "$TEST_REPO" log --oneline -"$NEW_COMMITS" --format="%s" | grep -c '\[plate\]')
if [ "$PLATE_COMMITS" -ge 1 ]; then
  pass "5c: commits have [plate] prefix"
else
  fail "5c: no [plate] prefix in recent commits"
fi

# ════════════════════════════════════════════════════════════════════════
echo "═══ Test 6: /plate --drop ═══"

# Clean stale tmux-launch lock from previous tests
hide_errors rmdir "$CLAUDE_PLUGIN_DATA/tmux-launch.lock"

# Push a new plate to test drop
echo "drop me" > "$TEST_REPO/dropfile.txt"
git -C "$TEST_REPO" add dropfile.txt
git -C "$TEST_REPO" commit -q -m "add dropfile"

DROP_SID="plate-e2e-drop-$$"
# Clean stale locks + old instances so this push goes through path 2
hide_errors rmdir "$CLAUDE_PLUGIN_DATA/tmux-launch.lock"
hide_errors rmdir "$PLATE_ROOT/.push.lock"
rm -f "$PLATE_ROOT/instances/"*.json

fire_plate "$TEST_REPO" "/plate" "$DROP_SID"

# Clean locks left by push
hide_errors rmdir "$CLAUDE_PLUGIN_DATA/tmux-launch.lock"
hide_errors rmdir "$PLATE_ROOT/.push.lock"

DROP_INSTANCE="$PLATE_ROOT/instances/${DROP_SID}.json"
if [ -f "$DROP_INSTANCE" ]; then
  DROP_STACK=$(python3 -c "import json; d=json.load(open('$DROP_INSTANCE')); print(len(d.get('stack',[])))")
  if [ "$DROP_STACK" -ge 1 ]; then
    OUTPUT=$(fire_plate "$TEST_REPO" "/plate --drop" "$DROP_SID")
    if echo "$OUTPUT" | grep -qF "dropped"; then
      pass "6a: --drop succeeded"
    else
      fail "6a: expected 'dropped', got: $OUTPUT"
    fi
  else
    fail "6a: push created instance but stack is empty ($DROP_STACK plates)"
  fi
else
  fail "6a: drop instance not created at $DROP_INSTANCE"
fi

# ════════════════════════════════════════════════════════════════════════
echo ""
echo "════════════════════════════════════════"
printf "TOTAL:  PASS=%d  FAIL=%d\n" "$PASS" "$FAIL"
echo "════════════════════════════════════════"
[ "$FAIL" -eq 0 ] || exit 1
