#!/bin/bash
# claude-plans-addir-test.sh — asserts agent_launch_cmd claude includes
# --add-dir pointing at $HOME/.claude/plans so claude doesn't block on a
# workspace-boundary Read prompt for plan files referenced in debate topics.
#
# Also round-trips the returned string through `eval set --` to prove the
# pane's shell will parse the --add-dir value as a single argv entry (not
# split on spaces, not mis-quoted).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"

pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
nope() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }

# Source the daemon in sourced-mode so agent_launch_cmd is defined.
SANDBOX=$(mktemp -d /tmp/claude-plans-addir-test.XXXXXX)
export DEBATE_DAEMON_SOURCED=1
export DEBATE_DIR="$SANDBOX/debate"; mkdir -p "$DEBATE_DIR"
export SESSION="placeholder"
export WINDOW_NAME="main"
export WINDOW_TARGET="${SESSION}:${WINDOW_NAME}"
export SETTINGS_FILE="$SANDBOX/settings.json"; echo "{}" > "$SETTINGS_FILE"
export CWD="/tmp/test-cwd"
export REPO_ROOT="/tmp/test-repo"
export DEBATE_AGENTS="claude"
# shellcheck source=../scripts/debate-tmux-orchestrator.sh
. "$PLUGIN_ROOT/skills/debate/scripts/debate-tmux-orchestrator.sh"

CMD=$(agent_launch_cmd claude)
EXPECTED="$HOME/.claude/plans"

# T1: the command string mentions --add-dir '<HOME>/.claude/plans'
if echo "$CMD" | grep -qF -- "--add-dir '${EXPECTED}'"; then
  ok "agent_launch_cmd claude contains --add-dir '${EXPECTED}'"
else
  nope "agent_launch_cmd claude missing --add-dir for plans dir"
  echo "    got: $CMD"
fi

# T2: shell-parse round-trip — the plans path appears as a single argv entry
eval "set -- $CMD"
found=0
for arg in "$@"; do
  if [ "$arg" = "$EXPECTED" ]; then
    found=1; break
  fi
done
if [ "$found" = 1 ]; then
  ok "shell-parsed argv contains exact token [${EXPECTED}] (no splitting)"
else
  nope "plans path did not survive shell parsing as a single token"
  echo "    argv:" "$@"
fi

# T3: the target dir actually exists on this system (non-fatal warning if not,
# since plans may not be present in CI-ish environments, but fail if missing
# on the author's machine where tests are expected to pass).
if [ -d "$EXPECTED" ]; then
  ok "${EXPECTED} exists on disk"
else
  nope "${EXPECTED} does NOT exist — debate topics referencing plan files will still prompt"
fi

rm -rf "$SANDBOX"

printf '\n'
if [ "$fail" -eq 0 ]; then
  printf '\033[32m[claude-plans-addir-test] %d passed, 0 failed\033[0m\n' "$pass"
  exit 0
else
  printf '\033[31m[claude-plans-addir-test] %d passed, %d failed\033[0m\n' "$pass" "$fail"
  exit 1
fi
