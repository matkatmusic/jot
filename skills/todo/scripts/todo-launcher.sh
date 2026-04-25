#!/bin/bash
# todo-launcher.sh — spawn the /todo background worker in a tmux pane.
# Called from skills/todo/SKILL.md (the foreground skill body) after any
# clarification questions have been answered.
#
# Args:
#   $1 = session_id (from pending JSON)
#   $2 = refined idea (single-line string; will be written verbatim to input.txt)
#   $3 = pending file absolute path (written by the hook; the launcher reads cwd/repo/timestamp from it)
#
# Prints the absolute path of the input.txt on stdout on success.
set -euo pipefail

SESSION_ID="${1:?session_id required}"
IDEA="${2:?refined idea required}"
PENDING_FILE="${3:?pending_file path required}"

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPTS_DIR/../../.." && pwd)"
export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"
: "${CLAUDE_PLUGIN_DATA:=$HOME/.claude/plugins/data/jot-matkatmusic-jot}"
export CLAUDE_PLUGIN_DATA
mkdir -p "$CLAUDE_PLUGIN_DATA"

. "$PLUGIN_ROOT/common/scripts/silencers.sh"
. "$PLUGIN_ROOT/common/scripts/hook-json.sh"
. "$PLUGIN_ROOT/common/scripts/tmux.sh"
. "$PLUGIN_ROOT/common/scripts/tmux-launcher.sh"
. "$PLUGIN_ROOT/common/scripts/claude-launcher.sh"
. "$PLUGIN_ROOT/common/scripts/permissions-seed.sh"
. "$PLUGIN_ROOT/common/scripts/platform.sh"
. "$PLUGIN_ROOT/common/scripts/lock.sh"
. "$PLUGIN_ROOT/common/scripts/git.sh"
. "$SCRIPTS_DIR/todo-state-lib.sh"

LOG_FILE="${TODO_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/todo-log.txt}"
hide_errors mkdir -p "$(dirname "$LOG_FILE")"

if [ ! -f "$PENDING_FILE" ]; then
  echo "todo-launcher: pending file not found at $PENDING_FILE" >&2
  exit 1
fi

REPO_ROOT=$(jq -r '.repo_root' "$PENDING_FILE")
CWD=$(jq -r '.cwd' "$PENDING_FILE")
TRANSCRIPT_PATH=$(jq -r '.transcript_path // empty' "$PENDING_FILE")
TIMESTAMP=$(jq -r '.timestamp' "$PENDING_FILE")

STATE_DIR="$REPO_ROOT/Todos/.todo-state"
todo_state_init "$STATE_DIR"

# ── Phase 1: write input.txt (durable-first) ─────────────────────────────
TARGET_DIR="$REPO_ROOT/Todos"
mkdir -p "$TARGET_DIR"
INPUT_FILE="$TARGET_DIR/${TIMESTAMP}_input.txt"
INPUT_ABS="$INPUT_FILE"

BRANCH=$(hide_errors git_get_branch_name "$CWD") || BRANCH="(unavailable)"
COMMITS=$(hide_errors git_get_recent_commits "$CWD") || COMMITS="(unavailable)"
UNCOMMITTED=$(hide_errors git_get_uncommitted "$CWD") || UNCOMMITTED="(unavailable)"
OPEN_TODOS=$(hide_errors "$SCRIPTS_DIR/scan-open-todos.sh" "$REPO_ROOT") || OPEN_TODOS="(unavailable)"

if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
  CONVERSATION=$(hide_errors python3 \
    "$PLUGIN_ROOT/skills/jot/scripts/capture-conversation.py" "$TRANSCRIPT_PATH") \
    || CONVERSATION="(unavailable)"
else
  CONVERSATION="No conversation history available."
fi

INSTRUCTIONS=$(REPO_ROOT="$REPO_ROOT" TIMESTAMP="$TIMESTAMP" BRANCH="$BRANCH" \
  INPUT_ABS="$INPUT_ABS" SCRIPTS_DIR="$SCRIPTS_DIR" \
  python3 "$PLUGIN_ROOT/common/scripts/jot/render_template.py" \
    "$SCRIPTS_DIR/assets/todo-instructions.md" \
    REPO_ROOT TIMESTAMP BRANCH INPUT_ABS SCRIPTS_DIR)

{
  printf '# Todo Task\n\n## Instructions\n%s\n\n' "$INSTRUCTIONS"
  printf '## Idea\n%s\n\n' "$IDEA"
  printf '## Working Directory\n%s\n\n' "$CWD"
  printf '## Git State\n- Branch: %s\n- Commits: %s\n- Uncommitted: %s\n\n' \
    "$BRANCH" "$COMMITS" "$UNCOMMITTED"
  printf '## Open TODO Files\n%s\n\n' "$OPEN_TODOS"
  printf '## Transcript Path\n%s\n\n' "${TRANSCRIPT_PATH:-(none)}"
  printf '## Recent Conversation\n%s\n\n' "$CONVERSATION"
} > "$INPUT_FILE"

# ── Phase 2: build the per-invocation claude command ──────────────────────
TMPDIR_INV=$(mktemp -d /tmp/todo.XXXXXX)
SETTINGS_FILE="$TMPDIR_INV/settings.json"

cp "$SCRIPTS_DIR/todo-session-start.sh" "$TMPDIR_INV/"
cp "$SCRIPTS_DIR/todo-stop.sh"          "$TMPDIR_INV/"
cp "$SCRIPTS_DIR/todo-session-end.sh"   "$TMPDIR_INV/"
cp "$PLUGIN_ROOT/common/scripts/tmux.sh"           "$TMPDIR_INV/"
cp "$PLUGIN_ROOT/common/scripts/tmux-launcher.sh"  "$TMPDIR_INV/"
cp "$PLUGIN_ROOT/common/scripts/invoke_command.sh" "$TMPDIR_INV/"
cp "$PLUGIN_ROOT/common/scripts/silencers.sh"      "$TMPDIR_INV/"

permissions_file="${CLAUDE_PLUGIN_DATA}/todo-permissions.local.json"
default_file="$SCRIPTS_DIR/assets/permissions.default.json"
default_sha_file="$SCRIPTS_DIR/assets/permissions.default.json.sha256"
prior_sha_file="${CLAUDE_PLUGIN_DATA}/todo-permissions.default.sha256"
permissions_seed "$permissions_file" "$default_file" "$default_sha_file" \
                 "$prior_sha_file" "$LOG_FILE" "todo"

allow_json=$(CWD="$CWD" HOME="$HOME" REPO_ROOT="$REPO_ROOT" \
  python3 "$PLUGIN_ROOT/common/scripts/jot/expand_permissions.py" "$permissions_file")

hooks_json_file="$TMPDIR_INV/hooks.json"
cat > "$hooks_json_file" <<JSON
{
  "SessionStart": [{"hooks": [{"type": "command", "command": "bash $TMPDIR_INV/todo-session-start.sh '$INPUT_FILE' '$TMPDIR_INV'"}]}],
  "Stop":         [{"hooks": [{"type": "command", "command": "bash $TMPDIR_INV/todo-stop.sh '$INPUT_FILE' '$TMPDIR_INV' '$STATE_DIR'"}]}],
  "SessionEnd":   [{"hooks": [{"type": "command", "command": "bash $TMPDIR_INV/todo-session-end.sh '$TMPDIR_INV'"}]}]
}
JSON

CLAUDE_CMD=$(build_claude_cmd "$SETTINGS_FILE" "$allow_json" "$hooks_json_file" "$CWD" "$REPO_ROOT")

# ── Phase 3: launch the tmux pane ─────────────────────────────────────────
tmux_lock="${CLAUDE_PLUGIN_DATA}/todo-tmux-launch.lock"
if ! lock_acquire "$tmux_lock" 10; then
  echo "todo-launcher: failed to acquire tmux-launch lock" >&2
  exit 1
fi
trap 'lock_release "$tmux_lock"' EXIT

counter_file="${CLAUDE_PLUGIN_DATA}/todo-pane-counter.txt"
n=$(hide_errors cat "$counter_file") || n=0
n=$(( n % 20 + 1 ))
printf '%s\n' "$n" > "$counter_file"
pane_label="todo${n}"

keepalive_cmd='exec sh -c '\''trap "" INT HUP TERM; printf "[todo keepalive — do not kill]\n"; exec tail -f /dev/null'\'''
tmux_ensure_session todo todos "$CWD" "$keepalive_cmd" 'todo: keepalive'

if ! PANE_ID=$(tmux_split_worker_pane todo:todos "$CWD" "$CLAUDE_CMD"); then
  echo "todo-launcher: tmux split-window returned empty pane id" >&2
  exit 1
fi

printf '%s\n' "$PANE_ID" > "$TMPDIR_INV/tmux_target.tmp"
mv "$TMPDIR_INV/tmux_target.tmp" "$TMPDIR_INV/tmux_target"

tmux_set_pane_title "$PANE_ID" "$pane_label"
tmux_retile todo:todos

spawn_terminal_if_needed "todo" "$LOG_FILE" "todo"

# Delete the pending-context sidecar now that the worker has been handed off.
# Failure here is cosmetic (sidecar accumulates harmlessly), so log and continue.
hide_errors rm -f "$PENDING_FILE" || \
  hide_errors printf '%s todo-launcher: failed to rm pending_file=%s\n' \
    "$(date -Iseconds)" "$PENDING_FILE" >> "$LOG_FILE"

printf '%s\n' "$INPUT_ABS"
