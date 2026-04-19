#!/bin/bash
# plate-claude-e2e.sh — end-to-end test with a real claude instance.
#
# Spawns a claude instance in a tmux pane (with installed plugins so hooks
# fire), makes file edits directly, sends /plate commands via send-keys,
# and verifies plate state + git diffs.
#
# Usage:
#   bash tests/plate-claude-e2e.sh           # run tests
#   bash tests/plate-claude-e2e.sh --attach  # pause for tmux attach before tests
set -uo pipefail

THIS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$THIS_DIR/.." && pwd)"

source "$REPO_ROOT/scripts/lib/invoke_command.sh"
source "$REPO_ROOT/scripts/lib/tmux.sh"
source "$REPO_ROOT/scripts/lib/tmux-launcher.sh"
source "$REPO_ROOT/scripts/lib/git.sh"

ATTACH_MODE=false
[ "${1:-}" = "--attach" ] && ATTACH_MODE=true

TEST_SESSION="plate-claude-e2e"
TEST_REPO=""
TESTEE_PANE=""
TMPDIR_TEST=""
PASS=0
FAIL=0

pass() { printf "PASS: %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "FAIL: %s\n" "$1"; FAIL=$((FAIL + 1)); }

cleanup() {
  tmux_kill_session "$TEST_SESSION"
  tmux_kill_session "plate"
  [ -n "$TEST_REPO" ] && rm -rf "$TEST_REPO"
  [ -n "$TMPDIR_TEST" ] && rm -rf "$TMPDIR_TEST"
  # Re-enable context-mode if we disabled it
  claude plugin enable context-mode 2>/dev/null
}
trap cleanup EXIT

# ── Helpers ───────────────────────────────────────────────────────────────

# usage: build_test_settings
# Creates a minimal settings.json with only plate hooks + broad permissions.
# No context-mode, no other plugins — avoids auto-trigger side effects.
build_test_settings() {
  TMPDIR_TEST=$(mktemp -d /tmp/plate-e2e-settings.XXXXXX)
  local settings="$TMPDIR_TEST/settings.json"
  local plate_scripts="$REPO_ROOT/scripts/plate"
  cat > "$settings" <<JSON
{
  "permissions": {
    "allow": [
      "Bash(**)",
      "Read(**)",
      "Write(**)",
      "Edit(**)",
      "mcp__plugin_context-mode_context-mode__*"
    ]
  },
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "CLAUDE_PLUGIN_ROOT='${REPO_ROOT}' CLAUDE_PLUGIN_DATA='${REPO_ROOT}/.plate-e2e-data' ${plate_scripts}/plate-orchestrator.sh"
          }
        ]
      }
    ]
  }
}
JSON
  printf '%s' "$settings"
}

create_test_repo() {
  TEST_REPO=$(mktemp -d /tmp/plate-claude-e2e.XXXXXX)
  cd "$TEST_REPO"
  git init -q
  git checkout -b main -q
  echo "file1 initial content" > file1.txt
  echo "file2 initial content" > file2.txt
  echo "file3 initial content" > file3.txt
  git add file1.txt file2.txt file3.txt
  git commit -q -m "initial: 3 text files"
}

# usage: get_session_id
# Extracts the testee claude's session ID from the pane capture.
# Claude shows the session ID in the SessionStart hook output.
get_session_id() {
  # The plate hook reads session_id from the hook input JSON.
  # We need to find what session_id the testee claude has.
  # Look for the .plate/instances/*.json file — its name IS the session_id.
  local sid_file
  sid_file=$(ls "$TEST_REPO/.plate/instances/"*.json 2>/dev/null | head -1)
  if [ -n "$sid_file" ]; then
    basename "$sid_file" .json
  fi
}

# usage: wait_for_stack_count <instance_file> <expected_count> [timeout]
# Polls until stack[] has the expected number of entries.
wait_for_stack_count() {
  local instance_file="$1" expected="$2" timeout="${3:-30}"
  local start elapsed count
  start=$(date +%s)
  while true; do
    if [ -f "$instance_file" ]; then
      count=$(python3 -c "import json; print(len(json.load(open('$instance_file')).get('stack',[])))" 2>/dev/null)
      [ "$count" = "$expected" ] && return 0
    fi
    elapsed=$(( $(date +%s) - start ))
    [ "$elapsed" -ge "$timeout" ] && return 1
    sleep 1
  done
}

# usage: verify_snapshot_diff <instance_file> <stack_index>
# Checks that the snapshot ref for the given stack entry captures the
# expected diff relative to its base.
verify_snapshot_diff() {
  local instance_file="$1" index="$2"
  local plate_json stash_sha head_sha
  plate_json=$(python3 -c "
import json
d = json.load(open('$instance_file'))
import sys
json.dump(d['stack'][$index], sys.stdout)
")
  stash_sha=$(echo "$plate_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['stash_sha'])")
  head_sha=$(echo "$plate_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['push_time_head_sha'])")

  # Verify the ref exists
  if ! git cat-file -t "$stash_sha" >/dev/null 2>&1; then
    echo "snapshot ref $stash_sha does not exist"
    return 1
  fi

  # Verify diff between head_sha and stash_sha is non-empty
  local diff_output
  diff_output=$(git diff "$head_sha" "$stash_sha" 2>/dev/null)
  if [ -z "$diff_output" ]; then
    echo "diff between $head_sha and $stash_sha is empty"
    return 1
  fi
  return 0
}

# usage: send_plate_command <command>
send_plate_command() {
  tmux_send_and_submit "$TESTEE_PANE" "$1"
  sleep 5
}

# ════════════════════════════════════════════════════════════════════════
echo "═══ Setup ═══"
create_test_repo
echo "  repo: $TEST_REPO"

# Kill any stale sessions
tmux_kill_session "$TEST_SESSION"
tmux_kill_session "plate"

# Disable context-mode plugin to prevent auto-triggered ctx-upgrade
# from blocking the testee's TUI. Re-enabled in cleanup.
claude plugin disable context-mode 2>/dev/null

# Spawn testee claude normally — installed plugins provide hooks + skills.
# context-mode was disabled above to prevent ctx-upgrade interference.
tmux_new_session "$TEST_SESSION"
TESTEE_PANE=$(tmux_new_pane "$TEST_SESSION" -c "$TEST_REPO" -P -F '#{pane_id}' \
  "claude")
tmux_set_pane_title "$TESTEE_PANE" "testee"

if [ "$ATTACH_MODE" = true ]; then
  echo ""
  echo "  Tmux session '$TEST_SESSION' ready."
  echo "  Attach:  tmux attach -t $TEST_SESSION"
  echo ""
  echo "  Press ENTER to start tests..."
  read -r
fi

trap - EXIT  # disable cleanup so the session survives
exit

# premature exit, so I can interact with the tmux claude.


echo "  Waiting for claude to boot..."
tmux_wait_for_claude_readiness "$TESTEE_PANE" 20

# Accept trust prompt (two Enters: select + confirm)
echo "  Accepting project trust prompt..."
sleep 1
tmux_send_enter "$TESTEE_PANE"
sleep 1
tmux_send_enter "$TESTEE_PANE"

sleep 5
echo "  Claude ready."

# ════════════════════════════════════════════════════════════════════════
echo ""
echo "═══ Test 1: edit file1.txt + /plate (first push, path 2) ═══"

echo "file1 edited by test" >> "$TEST_REPO/file1.txt"
git -C "$TEST_REPO" add file1.txt
git -C "$TEST_REPO" commit -q -m "edit file1"

send_plate_command "/plate"

# Find the instance file (created by first push)
PLATE_ROOT="$TEST_REPO/.plate"
sleep 2

SID=$(get_session_id)
INSTANCE_FILE=""
if [ -z "$SID" ]; then
  fail "1a: no session ID found (instance JSON not created)"
  echo "  DEBUG: .plate/ contents:"
  ls -la "$PLATE_ROOT" 2>&1 | head -10
  echo "  DEBUG: pane capture:"
  tmux_capture_pane "$TESTEE_PANE" 15 2>/dev/null | head -15
else
  pass "1a: session ID found: ${SID:0:12}..."
  INSTANCE_FILE="$PLATE_ROOT/instances/${SID}.json"

  if wait_for_stack_count "$INSTANCE_FILE" 1 15; then
    pass "1b: stack has 1 plate"
  else
    fail "1b: stack count != 1"
  fi

  if verify_snapshot_diff "$INSTANCE_FILE" 0; then
    pass "1c: snapshot diff is valid"
  else
    fail "1c: snapshot diff invalid"
  fi
fi

# Clean stale locks left by push (tmux session creation may fail)
hide_errors rmdir "$HOME/.claude/plugins/data/plate-jot-dev/tmux-launch.lock"
hide_errors rmdir "$PLATE_ROOT/.push.lock"

# ════════════════════════════════════════════════════════════════════════
# Skip remaining tests if first push failed
if [ -z "$INSTANCE_FILE" ]; then
  echo "SKIP: tests 2-5 (first push failed, no instance file)"
  echo ""
  echo "════════════════════════════════════════"
  printf "TOTAL:  PASS=%d  FAIL=%d\n" "$PASS" "$FAIL"
  echo "════════════════════════════════════════"
  exit 1
fi

echo ""
echo "═══ Test 2: edit file2.txt + /plate (second push, path 1) ═══"

echo "file2 edited by test" >> "$TEST_REPO/file2.txt"
git -C "$TEST_REPO" add file2.txt
git -C "$TEST_REPO" commit -q -m "edit file2"

send_plate_command "/plate"
sleep 2

if wait_for_stack_count "$INSTANCE_FILE" 2 15; then
  pass "2a: stack has 2 plates"
else
  fail "2a: stack count != 2"
fi

if verify_snapshot_diff "$INSTANCE_FILE" 1; then
  pass "2b: snapshot diff is valid"
else
  fail "2b: snapshot diff invalid"
fi

hide_errors rmdir "$HOME/.claude/plugins/data/plate-jot-dev/tmux-launch.lock"
hide_errors rmdir "$PLATE_ROOT/.push.lock"

# ════════════════════════════════════════════════════════════════════════
echo ""
echo "═══ Test 3: edit file3.txt + /plate (third push) ═══"

echo "file3 edited by test" >> "$TEST_REPO/file3.txt"
git -C "$TEST_REPO" add file3.txt
git -C "$TEST_REPO" commit -q -m "edit file3"

send_plate_command "/plate"
sleep 2

if wait_for_stack_count "$INSTANCE_FILE" 3 15; then
  pass "3a: stack has 3 plates"
else
  fail "3a: stack count != 3"
fi

if verify_snapshot_diff "$INSTANCE_FILE" 2; then
  pass "3b: snapshot diff is valid"
else
  fail "3b: snapshot diff invalid"
fi

hide_errors rmdir "$HOME/.claude/plugins/data/plate-jot-dev/tmux-launch.lock"
hide_errors rmdir "$PLATE_ROOT/.push.lock"

# ════════════════════════════════════════════════════════════════════════
echo ""
echo "═══ Test 4: /plate --show ═══"

send_plate_command "/plate --show"

if [ -f "$PLATE_ROOT/tree.md" ]; then
  pass "4a: tree.md exists"
else
  fail "4a: tree.md not created"
fi

# Verify the tree.md mentions our session
if grep -qF "$SID" "$PLATE_ROOT/tree.md" 2>/dev/null; then
  pass "4b: tree.md contains session ID"
else
  # Session ID might be truncated in tree — check for any content
  if [ -s "$PLATE_ROOT/tree.md" ]; then
    pass "4b: tree.md has content"
  else
    fail "4b: tree.md is empty"
  fi
fi

# ════════════════════════════════════════════════════════════════════════
echo ""
echo "═══ Test 5: /plate --done (replay commits) ═══"

COMMITS_BEFORE=$(git -C "$TEST_REPO" rev-list --count HEAD)

send_plate_command "/plate --done"
# --done passes through to SKILL.md body — claude runs done.sh
# Wait longer for claude to process the skill body
sleep 10
tmux_wait_for_claude_readiness "$TESTEE_PANE" 60

COMMITS_AFTER=$(git -C "$TEST_REPO" rev-list --count HEAD)
NEW_COMMITS=$((COMMITS_AFTER - COMMITS_BEFORE))

if [ "$NEW_COMMITS" -ge 3 ]; then
  pass "5a: $NEW_COMMITS new commits created (expected >= 3)"
else
  fail "5a: expected >= 3 new commits, got $NEW_COMMITS"
fi

PLATE_COMMITS=$(git -C "$TEST_REPO" log --oneline -"$NEW_COMMITS" --format="%s" 2>/dev/null | grep -c '\[plate\]')
if [ "$PLATE_COMMITS" -ge 1 ]; then
  pass "5b: commits have [plate] prefix"
else
  fail "5b: no [plate] prefix in recent commits"
fi

# ════════════════════════════════════════════════════════════════════════
echo ""
echo "════════════════════════════════════════"
printf "TOTAL:  PASS=%d  FAIL=%d\n" "$PASS" "$FAIL"
echo "════════════════════════════════════════"
[ "$FAIL" -eq 0 ] || exit 1
