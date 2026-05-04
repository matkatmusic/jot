#!/bin/bash
# session-survives-daemon-exit-test.sh — asserts the daemon's cleanup()
# does NOT kill the tmux session. test.sh (the design baseline) lets the
# session survive so agent panes remain inspectable when outputs don't
# arrive; f1e6fa7a introduced a `tmux_kill_session` in cleanup that broke
# that property. This test pins the fix: running cleanup leaves the session
# alive. Control: re-inserts the kill line and asserts it DOES kill the
# session, proving the removal is load-bearing.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"

pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
nope() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }

mk_env() {
  SANDBOX=$(mktemp -d /tmp/session-survives-test.XXXXXX)
  DEBATE_DIR="$SANDBOX/debate"; mkdir -p "$DEBATE_DIR"
  SESSION="sess-survives-$$-$RANDOM"
  WINDOW_NAME="main"
  WINDOW_TARGET="${SESSION}:${WINDOW_NAME}"
  # Must match /tmp/debate.* for cleanup's case branch to rm it.
  SETTINGS_DIR=$(mktemp -d /tmp/debate.XXXXXX)
  SETTINGS_FILE="$SETTINGS_DIR/settings.json"
  echo "{}" > "$SETTINGS_FILE"
  DEBATE_AGENTS="claude"
  export DEBATE_DAEMON_SOURCED=1
  export DEBATE_DIR SESSION WINDOW_NAME WINDOW_TARGET SETTINGS_FILE DEBATE_AGENTS
  . "$PLUGIN_ROOT/skills/debate/scripts/debate-tmux-orchestrator.sh"
  tmux new-session -d -s "$SESSION" -n "$WINDOW_NAME" "sleep 120"
}
teardown() {
  tmux kill-session -t "$SESSION" 2>/dev/null || true
  rm -rf "$SANDBOX"
  unset DEBATE_DAEMON_SOURCED
}

# ── T1: production cleanup must NOT kill the session ──
mk_env
cleanup   # invoke directly; simulates trap firing on daemon EXIT
if tmux has-session -t "$SESSION" 2>/dev/null; then
  ok "tmux session [$SESSION] survives cleanup()"
else
  nope "tmux session killed by cleanup — regression!"
fi
# Also verify the settings tmpdir part of cleanup still works.
if [ ! -d "$SETTINGS_DIR" ]; then
  ok "/tmp/debate.* settings tmpdir still removed by cleanup"
else
  nope "cleanup no longer removes settings tmpdir"
fi
teardown

# ── T2: CONTROL — with the kill line re-inserted, session IS killed ──
mk_env
cleanup_broken() {
  local settings_dir
  settings_dir=$(dirname "$SETTINGS_FILE")
  case "$settings_dir" in
    /tmp/debate.*) rm -rf "$settings_dir" ;;
  esac
  hide_errors tmux_kill_session "$SESSION"
}
cleanup_broken
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  ok "control proves kill line is load-bearing (re-inserting it DOES kill the session)"
else
  nope "control variant failed to kill session — test is not discriminating"
fi
teardown

printf '\n'
if [ "$fail" -eq 0 ]; then
  printf '\033[32m[session-survives-daemon-exit-test] %d passed, 0 failed\033[0m\n' "$pass"
  exit 0
else
  printf '\033[31m[session-survives-daemon-exit-test] %d passed, %d failed\033[0m\n' "$pass" "$fail"
  exit 1
fi
