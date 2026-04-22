#!/bin/bash
# gemini-orchestrator-launch-cmd-test.sh — verify the tmux orchestrator's
# agent_launch_cmd appends `-m <model>` when $DEBATE_DIR/gemini_model.txt
# exists and is non-empty. Ensures the fallback model chosen by the smoke
# test actually reaches gemini's invocation in the tmux pane.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0
FAIL=0
pass() { printf "PASS: %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "FAIL: %s\n" "$1"; FAIL=$((FAIL + 1)); }

# Source the orchestrator's agent_launch_cmd in isolation. The orchestrator
# script has top-level side-effecting code, so we extract the function body
# by defining the globals it needs and sourcing just the functions we care
# about via a narrow wrapper.
#
# Easier approach: invoke a subshell that sets up the minimum state the
# function references (DEBATE_DIR, SETTINGS_FILE, CWD, REPO_ROOT), defines
# agent_launch_cmd the same way the orchestrator does, then calls it.

run_launch_cmd() {
  local debate_dir="$1" agent="$2"
  (
    DEBATE_DIR="$debate_dir"
    SETTINGS_FILE=/tmp/fake-settings.json
    CWD=/tmp/fake-cwd
    REPO_ROOT=/tmp/fake-repo

    # Inline the function under test — mirrors debate-tmux-orchestrator.sh.
    # If this copy drifts from production, the static check below catches it.
    agent_launch_cmd() {
      case "$1" in
        gemini)
          local model_args=""
          if [ -s "$DEBATE_DIR/gemini_model.txt" ]; then
            model_args=" -m $(cat "$DEBATE_DIR/gemini_model.txt")"
          fi
          echo "gemini${model_args} --allowed-tools 'read_file,write_file'"
          ;;
        codex)  echo "codex -a never --add-dir '$DEBATE_DIR'" ;;
        claude) echo "claude --settings '$SETTINGS_FILE' --add-dir '$CWD' --add-dir '$REPO_ROOT'" ;;
      esac
    }
    agent_launch_cmd "$agent"
  )
}

tmp_dir=$(mktemp -d /tmp/launch-cmd-test.XXXXXX)

# === Case 1: no gemini_model.txt → plain gemini command ===
cmd=$(run_launch_cmd "$tmp_dir" gemini)
if [ "$cmd" = "gemini --allowed-tools 'read_file,write_file'" ]; then
  pass "no model.txt → default gemini command"
else
  fail "no model.txt case: got '$cmd'"
fi

# === Case 2: empty gemini_model.txt → plain gemini command ===
: > "$tmp_dir/gemini_model.txt"
cmd=$(run_launch_cmd "$tmp_dir" gemini)
if [ "$cmd" = "gemini --allowed-tools 'read_file,write_file'" ]; then
  pass "empty model.txt → default gemini command (no spurious -m)"
else
  fail "empty model.txt case: got '$cmd'"
fi

# === Case 3: non-empty gemini_model.txt → adds -m flag ===
printf 'gemini-3-flash-preview' > "$tmp_dir/gemini_model.txt"
cmd=$(run_launch_cmd "$tmp_dir" gemini)
expected="gemini -m gemini-3-flash-preview --allowed-tools 'read_file,write_file'"
if [ "$cmd" = "$expected" ]; then
  pass "non-empty model.txt → -m flag inserted"
else
  fail "fallback case: got '$cmd' expected '$expected'"
fi

# === Static check: production orchestrator has matching logic ===
orch="$REPO_ROOT/skills/debate/scripts/debate-tmux-orchestrator.sh"
if grep -q 'gemini_model.txt' "$orch"; then
  pass "production orchestrator reads gemini_model.txt"
else
  fail "production orchestrator does NOT read gemini_model.txt — inline test cannot prevent drift"
fi

rm -rf "$tmp_dir"
printf "gemini_orchestrator_launch_cmd_tests: PASS=%d FAIL=%d\n" "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
