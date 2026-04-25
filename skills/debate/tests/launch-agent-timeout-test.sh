#!/bin/bash
# launch-agent-timeout-test.sh — verifies the hardened launch_agent() covers:
#   A. 120s default timeout absorbs slow agent banners (>30s).
#      Control: 30s timeout on same slow banner → FAILED.txt reason matches.
#   B. -S -2000 scrollback + tr -d '\033' ANSI strip finds a marker that's
#      scrolled off the visible pane area.
#      Control: a "broken" variant without -S flag misses the same marker.
#
# Markers are read from files so the typed command string itself does NOT
# contain the marker — otherwise capture-pane would match the command-line
# echo before the program runs, defeating the timeout / scrollback checks.
#
# Sources debate-tmux-orchestrator.sh via DEBATE_DAEMON_SOURCED=1 so no daemon
# loop runs — we call launch_agent() directly against a real tmux pane.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"

COUNTER_FILE=$(mktemp /tmp/debate-launch-test-counter.XXXXXX)
echo "0 0" > "$COUNTER_FILE"
pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; read -r p f < "$COUNTER_FILE"; echo "$((p+1)) $f" > "$COUNTER_FILE"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; read -r p f < "$COUNTER_FILE"; echo "$p $((f+1))" > "$COUNTER_FILE"; }

mk_sandbox() {
  SANDBOX=$(mktemp -d /tmp/launch-agent-test.XXXXXX)
  DEBATE_DIR="$SANDBOX/debate"; mkdir -p "$DEBATE_DIR"
  SESSION="launch-agent-test-$$-$RANDOM"
  WINDOW_NAME="main"
  WINDOW_TARGET="${SESSION}:${WINDOW_NAME}"
  SETTINGS_FILE="$SANDBOX/settings.json"; echo "{}" > "$SETTINGS_FILE"
  DEBATE_AGENTS="claude"
  export DEBATE_DAEMON_SOURCED=1
  export DEBATE_DIR SESSION WINDOW_NAME WINDOW_TARGET SETTINGS_FILE DEBATE_AGENTS

  # shellcheck source=../scripts/debate-tmux-orchestrator.sh
  . "$PLUGIN_ROOT/skills/debate/scripts/debate-tmux-orchestrator.sh"

  tmux new-session -d -s "$SESSION" -n "$WINDOW_NAME" -x 200 -y 60 "sleep 600"
}

teardown_sandbox() {
  tmux kill-session -t "$SESSION" 2>/dev/null || true
  rm -rf "$SANDBOX"
  unset DEBATE_DAEMON_SOURCED
}

fresh_pane() {
  tmux split-window -t "$WINDOW_TARGET" -c /tmp -P -F '#{pane_id}'
}

# marker_file() writes a unique token to a tmp file, returns (path, token).
# Using file-backed markers keeps the launch_cmd string clean so the command
# line echoed by the shell doesn't trivially match the capture-pane grep.
mk_marker_file() {
  local token="READY-$$-$RANDOM-$(date +%s%N)"
  local f
  f=$(mktemp /tmp/launch-agent-marker.XXXXXX)
  printf '%s\n' "$token" > "$f"
  # echo path + token separated by a space
  echo "$f $token"
}

# ══════════════════════ TEST A: timeout bump ══════════════════════
echo "T1: launch_agent timeout=120 absorbs 45s slow banner"
mk_sandbox
PANE=$(fresh_pane)
read -r MF TOKEN < <(mk_marker_file)
START=$(date +%s)
launch_agent "$PANE" r1 claude "sleep 45 && cat $MF" "$TOKEN" 120
RC=$?
END=$(date +%s)
ELAPSED=$((END - START))
if [ "$RC" -eq 0 ] && [ "$ELAPSED" -ge 44 ] && [ "$ELAPSED" -lt 110 ]; then
  pass "returned 0 after ${ELAPSED}s (expected ≥44, <110)"
else
  fail "rc=$RC elapsed=${ELAPSED}s (expected rc=0, 44≤elapsed<110)"
fi
rm -f "$MF"
teardown_sandbox

echo "T2: launch_agent timeout=30 FAILS on same 45s slow banner (control)"
mk_sandbox
PANE=$(fresh_pane)
read -r MF TOKEN < <(mk_marker_file)
launch_agent "$PANE" r1 claude "sleep 45 && cat $MF" "$TOKEN" 30
RC=$?
if [ "$RC" -ne 0 ]; then
  pass "returned non-zero as expected (rc=$RC)"
else
  fail "unexpectedly returned 0 — the 30s timeout was supposed to miss"
fi
if [ -f "$DEBATE_DIR/FAILED.txt" ]; then
  REASON=$(grep '^reason:' "$DEBATE_DIR/FAILED.txt" | head -1)
  EXPECTED="reason: launch_agent timeout for claude after 30s"
  if [ "$REASON" = "$EXPECTED" ]; then
    pass "FAILED.txt reason line exact-matches expected string"
  else
    fail "FAILED.txt reason mismatch: got [$REASON] expected [$EXPECTED]"
  fi
else
  fail "FAILED.txt not written"
fi
rm -f "$MF"
teardown_sandbox

# ══════════════════════ TEST B: scrollback hardening ══════════════════════
echo "T3: launch_agent finds marker after 500 lines of noise scroll (uses -S -2000)"
mk_sandbox
PANE=$(fresh_pane)
read -r MF TOKEN < <(mk_marker_file)
# Emit marker first (via cat), then 500 lines of noise, then sleep to keep
# process alive. Pane height is 60, so marker is pushed ≥440 lines above
# the visible area by the time the first poll fires.
CMD="cat $MF; for i in \$(seq 1 500); do echo noise-\$i; done; sleep 30"
launch_agent "$PANE" r1 claude "$CMD" "$TOKEN" 15
RC=$?
if [ "$RC" -eq 0 ]; then
  pass "found marker in scrollback"
else
  fail "rc=$RC — marker missed even with -S -2000 scrollback"
fi
rm -f "$MF"
teardown_sandbox

echo "T4: control — same scrollback test with broken capture (no -S) must FAIL"
mk_sandbox
PANE=$(fresh_pane)
read -r MF TOKEN < <(mk_marker_file)
# Override launch_agent with a deliberately broken variant (no -S, no tr).
# This proves the scrollback-hardening is load-bearing, not incidental.
launch_agent_broken() {
  local pane_id="$1" stage="$2" agent="$3" launch_cmd="$4" ready_marker="$5"
  local timeout="${6:-15}"
  printf 'debate:%s\n' "$pane_id" > "$DEBATE_DIR/.${stage}_${agent}.lock"
  tmux_send_and_submit "$pane_id" "$launch_cmd"
  # Wait 2s so all 500 lines definitely fill the pane + push marker up,
  # before we start polling (otherwise first poll catches marker in visible
  # area before noise scrolls in).
  sleep 2
  local elapsed=2
  while [ "$elapsed" -lt "$timeout" ]; do
    if hide_errors tmux capture-pane -t "$pane_id" -p | grep -qF "$ready_marker"; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}
CMD="cat $MF; for i in \$(seq 1 500); do echo noise-\$i; done; sleep 30"
launch_agent_broken "$PANE" r1 claude "$CMD" "$TOKEN" 15
RC=$?
if [ "$RC" -ne 0 ]; then
  pass "broken variant correctly missed the scrolled-off marker (rc=$RC)"
else
  fail "broken variant unexpectedly found the marker — test is not discriminating"
fi
rm -f "$MF"
teardown_sandbox

# ══════════════════════ SUMMARY ══════════════════════
read -r P F < "$COUNTER_FILE"
rm -f "$COUNTER_FILE"
printf '\n'
if [ "$F" -eq 0 ]; then
  printf '\033[32m[launch-agent-timeout-test] %d passed, 0 failed\033[0m\n' "$P"
  exit 0
else
  printf '\033[31m[launch-agent-timeout-test] %d passed, %d failed\033[0m\n' "$P" "$F"
  exit 1
fi
