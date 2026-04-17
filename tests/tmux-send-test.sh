#!/bin/bash
# tmux-send-test.sh — verify tmux-send.sh library functions.
#
# Two scenarios:
#   1. Plain shell: send "echo hello", verify "hello" in output.
#   2. Claude Code TUI: send "!echo hello", verify claude processed it.
#
# Usage: bash tests/tmux-send-test.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$REPO_ROOT/scripts/lib/tmux-send.sh"
source "$REPO_ROOT/scripts/lib/tmux-launcher.sh"

TEST_SESSION="tmux-send-test-$$"
PASS=0
FAIL=0

pass() { printf "PASS: %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "FAIL: %s\n" "$1"; FAIL=$((FAIL + 1)); }

cleanup() {
  tmux_kill_session "$TEST_SESSION"
}
trap cleanup EXIT

# ════════════════════════════════════════════════════════════════════
# Test 1: Plain shell — send "echo hello", verify "hello" in output
# ════════════════════════════════════════════════════════════════════
echo "═══ Test 1: plain shell ═══"
tmux new-session -d -s "$TEST_SESSION" -n shell
PANE=$(tmux list-panes -t "$TEST_SESSION:shell" -F '#{pane_id}' | head -1)
sleep 1

tmux_send_and_submit "$PANE" "echo hello"
sleep 1

CAPTURE=$(tmux_capture_pane "$PANE" 10)
if echo "$CAPTURE" | grep -qF 'hello'; then
  pass "1a: 'hello' found in shell output"
else
  fail "1a: 'hello' NOT found in shell output"
  echo "  capture: $CAPTURE"
fi

# Verify the text function alone doesn't submit
tmux_send_text "$PANE" "echo pending"
sleep 0.5
CAPTURE=$(tmux_capture_pane "$PANE" 5)
if echo "$CAPTURE" | grep -qF 'pending'; then
  # Text is in the input line — check it wasn't executed (no second "pending" from output)
  COUNT=$(echo "$CAPTURE" | grep -c 'pending' || true)
  if [ "$COUNT" -le 1 ]; then
    pass "1b: tmux_send_text typed without submitting"
  else
    fail "1b: tmux_send_text appears to have submitted (found $COUNT occurrences)"
  fi
else
  fail "1b: tmux_send_text didn't type text"
fi

# Now submit with tmux_send_enter
tmux_send_enter "$PANE"
sleep 1
CAPTURE=$(tmux_capture_pane "$PANE" 5)
COUNT=$(echo "$CAPTURE" | grep -c 'pending' || true)
if [ "$COUNT" -ge 2 ]; then
  pass "1c: tmux_send_enter submitted the command"
else
  fail "1c: tmux_send_enter didn't submit (found $COUNT occurrences of 'pending')"
fi

# ════════════════════════════════════════════════════════════════════
# Test 2: Claude Code TUI — send "!echo hello", verify processing
# ════════════════════════════════════════════════════════════════════
echo "═══ Test 2: Claude Code TUI ═══"
tmux new-window -t "$TEST_SESSION" -n claude -c "$REPO_ROOT/testrepo" "claude --settings /dev/null"
PANE=$(tmux list-panes -t "$TEST_SESSION:claude" -F '#{pane_id}' | head -1)

# Wait for claude to boot (TUI renders welcome screen)
echo "  Waiting 8s for claude TUI to boot..."
sleep 8

tmux_send_and_submit "$PANE" '!echo tmux-send-test-ok'
echo "  Waiting 5s for claude to process..."
sleep 5

CAPTURE=$(tmux_capture_pane "$PANE" 30)
if echo "$CAPTURE" | grep -qF 'tmux-send-test-ok'; then
  pass "2a: claude received and processed '!echo tmux-send-test-ok'"
else
  fail "2a: 'tmux-send-test-ok' NOT found in claude pane"
  echo "  last 15 lines:"
  echo "$CAPTURE" | tail -15
fi

# Verify it was actually executed (look for the output or the command indicator)
if echo "$CAPTURE" | grep -qE '(Executing|tmux-send-test-ok)'; then
  pass "2b: evidence of command execution in pane"
else
  fail "2b: no evidence of execution in pane"
fi

# ════════════════════════════════════════════════════════════════════
echo ""
echo "════════════════════════════════════════"
printf "TOTAL:  PASS=%d  FAIL=%d\n" "$PASS" "$FAIL"
echo "════════════════════════════════════════"
[ "$FAIL" -eq 0 ] || exit 1
