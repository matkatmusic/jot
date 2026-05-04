#!/bin/bash
# parallel-launch-timing-test.sh — proves the parallel-launch refactor.
# Two discriminating cases:
#   T1. Timing: launch_agents_parallel runs three 2s-sleep stubs concurrently.
#       Wall must be <4s. Serial regression would land near 6s.
#   T2. Atomicity: three workers concurrently invoke write_failed. FAILED.txt
#       must be well-formed (exactly one header, 3 agent sections, no torn
#       lines), and no .FAILED.txt.* tempfiles may linger.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"

pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
nope() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }

mk_env() {
  SANDBOX=$(mktemp -d /tmp/parallel-launch-test.XXXXXX)
  DEBATE_DIR="$SANDBOX/debate"; mkdir -p "$DEBATE_DIR"
  SESSION="parallel-test-$$"
  WINDOW_NAME="main"
  WINDOW_TARGET="${SESSION}:${WINDOW_NAME}"
  SETTINGS_FILE="$SANDBOX/settings.json"; echo "{}" > "$SETTINGS_FILE"
  CWD="$SANDBOX"
  REPO_ROOT="$SANDBOX"
  AGENTS=(claude gemini codex)
  DEBATE_AGENTS="${AGENTS[*]}"
  export DEBATE_DAEMON_SOURCED=1
  export DEBATE_DIR SESSION WINDOW_NAME WINDOW_TARGET SETTINGS_FILE
  export CWD REPO_ROOT DEBATE_AGENTS

  . "$PLUGIN_ROOT/skills/debate/scripts/debate-tmux-orchestrator.sh"
}

teardown_env() {
  rm -rf "$SANDBOX"
  unset DEBATE_DAEMON_SOURCED
}

# ──────────── T1: parallelism timing ────────────
echo "T1: launch_agents_parallel runs workers concurrently (elapsed <4s for 3x2s sleeps)"
mk_env

# Stub launch_agent to a deterministic 2s sleep and send_prompt to no-op.
# Bash function defs in the parent shell are inherited by ( ... ) & subshells,
# so each backgrounded worker calls these stubs.
launch_agent()       { sleep 2; return 0; }
send_prompt()        { return 0; }
tmux_kill_pane()     { :; }
agent_launch_cmd()   { echo "stub-launch-$1"; }
agent_ready_marker() { echo "stub-marker-$1"; }
hide_errors()        { "$@"; }
hide_output()        { "$@"; }

R1_PANES=(%1 %2 %3)
t0=$SECONDS
launch_agents_parallel r1 R1_PANES
elapsed=$((SECONDS - t0))

if [ "$elapsed" -lt 4 ]; then
  ok "elapsed=${elapsed}s (<4s, parallel confirmed)"
else
  nope "elapsed=${elapsed}s (>=4s, suggests serial regression)"
fi

teardown_env

# ──────────── T2: concurrent write_failed atomicity ────────────
echo "T2: concurrent write_failed produces well-formed FAILED.txt with no torn writes"
mk_env

# Stub launch_agent to write the lock file (so write_failed can resolve a
# pane_id from it) then call write_failed and exit 1. Three backgrounded
# subshells racing into write_failed concurrently is exactly the scenario
# the mktemp+mv-f atomicity fix is meant to survive.
launch_agent() {
  local pane_id="$1" stage="$2" agent="$3"
  printf 'debate:%s\n' "$pane_id" > "$DEBATE_DIR/.${stage}_${agent}.lock"
  write_failed "$stage" "test-injected timeout for $agent"
  return 1
}
send_prompt()        { return 0; }
tmux_kill_pane()     { :; }
agent_launch_cmd()   { echo "stub-launch-$1"; }
agent_ready_marker() { echo "stub-marker-$1"; }
hide_errors()        { "$@"; }
hide_output()        { "$@"; }
# write_failed calls `hide_errors tmux capture-pane ...`; with hide_errors
# stubbed to "$@", we need tmux itself to be a no-op so we don't depend on
# a live tmux server during unit-style tests.
tmux()               { :; }

R1_PANES=(%1 %2 %3)
launch_agents_parallel r1 R1_PANES
rc=$?

if [ "$rc" -ne 0 ]; then
  ok "helper returns non-zero when all workers exit 1"
else
  nope "helper returned 0 despite all workers exiting non-zero"
fi

if [ ! -f "$DEBATE_DIR/FAILED.txt" ]; then
  nope "FAILED.txt was not created"
else
  header_count=$(grep -c '^# debate FAILED' "$DEBATE_DIR/FAILED.txt")
  agent_section_count=$(grep -c '^### ' "$DEBATE_DIR/FAILED.txt")

  if [ "$header_count" -eq 1 ]; then
    ok "FAILED.txt has exactly one '# debate FAILED' header"
  else
    nope "FAILED.txt has $header_count headers (expected 1) — torn write"
  fi

  if [ "$agent_section_count" -eq 3 ]; then
    ok "FAILED.txt has exactly 3 agent sections"
  else
    nope "FAILED.txt has $agent_section_count agent sections (expected 3)"
  fi

  # Torn boundary detection: '### gem### codex' style fragments
  if grep -q '###[A-Za-z]*###' "$DEBATE_DIR/FAILED.txt"; then
    nope "FAILED.txt has interleaved agent-name boundaries (torn writes)"
  else
    ok "FAILED.txt has no torn agent-name boundaries"
  fi
fi

stray=$(ls "$DEBATE_DIR"/.FAILED.txt.* 2>/dev/null | wc -l | tr -d ' ')
if [ "$stray" -eq 0 ]; then
  ok "no stray .FAILED.txt.* tempfiles linger"
else
  nope "$stray stray tempfile(s) lingering — mv -f did not run"
fi

teardown_env

# ──────────── Summary ────────────
printf '\n'
if [ "$fail" -eq 0 ]; then
  printf '\033[32m[parallel-launch-timing-test] %d passed, 0 failed\033[0m\n' "$pass"
  exit 0
else
  printf '\033[31m[parallel-launch-timing-test] %d passed, %d failed\033[0m\n' "$pass" "$fail"
  exit 1
fi
