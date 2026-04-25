#!/bin/bash
# agent-ls-permission-test.sh — pins the requirement that all 3 debate agents
# can run `ls` without prompting (no human is watching the panes).
#   - claude: permissions.default.json grants Bash(ls:*)
#   - gemini: agent_launch_cmd appends run_shell_command(ls) to --allowed-tools
#   - codex:  agent_launch_cmd uses `-a never`, which auto-accepts all
#             approvals including shell commands like ls
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"

pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
nope() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }

# ── claude: Bash(ls:*) in permissions.default.json ──
PERMS="$PLUGIN_ROOT/skills/debate/scripts/assets/permissions.default.json"
if jq -e '.permissions.allow | index("Bash(ls:*)")' "$PERMS" >/dev/null; then
  ok "claude permissions.default.json contains Bash(ls:*)"
else
  nope "claude permissions.default.json missing Bash(ls:*)"
fi

# ── gemini: run_shell_command(ls) in --allowed-tools ──
SANDBOX=$(mktemp -d /tmp/agent-ls-perm.XXXXXX)
DEBATE_DIR="$SANDBOX/d"; mkdir -p "$DEBATE_DIR"
SESSION="placeholder"
WINDOW_NAME="main"
WINDOW_TARGET="${SESSION}:${WINDOW_NAME}"
SETTINGS_FILE="$SANDBOX/settings.json"; echo "{}" > "$SETTINGS_FILE"
CWD="/tmp/cwd"; REPO_ROOT="/tmp/repo"; DEBATE_AGENTS="claude"
export DEBATE_DAEMON_SOURCED=1
export DEBATE_DIR SESSION WINDOW_NAME WINDOW_TARGET SETTINGS_FILE CWD REPO_ROOT DEBATE_AGENTS
. "$PLUGIN_ROOT/skills/debate/scripts/debate-tmux-orchestrator.sh"

GEMINI_CMD=$(agent_launch_cmd gemini)
if echo "$GEMINI_CMD" | grep -qF -e 'run_shell_command(ls)'; then
  ok "gemini agent_launch_cmd includes run_shell_command(ls)"
else
  nope "gemini cmd missing run_shell_command(ls): [$GEMINI_CMD]"
fi
# Ensure original tools are still present.
if echo "$GEMINI_CMD" | grep -qF -e 'read_file' && echo "$GEMINI_CMD" | grep -qF -e 'write_file'; then
  ok "gemini still permits read_file + write_file (no regression)"
else
  nope "gemini lost read_file or write_file: [$GEMINI_CMD]"
fi

# ── codex: -a never auto-approves, including ls ──
CODEX_CMD=$(agent_launch_cmd codex)
if echo "$CODEX_CMD" | grep -qF -e '-a never'; then
  ok "codex agent_launch_cmd uses -a never (auto-accepts ls without prompting)"
else
  nope "codex cmd missing '-a never': [$CODEX_CMD]"
fi

rm -rf "$SANDBOX"

printf '\n'
if [ "$fail" -eq 0 ]; then
  printf '\033[32m[agent-ls-permission-test] %d passed, 0 failed\033[0m\n' "$pass"
  exit 0
else
  printf '\033[31m[agent-ls-permission-test] %d passed, %d failed\033[0m\n' "$pass" "$fail"
  exit 1
fi
