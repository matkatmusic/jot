#!/bin/bash
# jot.sh — function definitions for the /jot hook.
# Sourced by jot-orchestrator.sh. No side effects when sourced.
#
# Phase 1 invariant: the user's idea must survive every partial failure.
#   Whatever goes wrong during enrichment or Phase 2 launch, the input.txt
#   is already on disk (durable-first) so the user can retrieve their idea.
#
# Phase 2: one claude per invocation, running in its own tmux pane inside
#   the cross-project `jot:jots` window. Lifecycle hooks (SessionStart,
#   Stop, SessionEnd) live in scripts/jot-session-start.sh, jot-stop.sh,
#   jot-session-end.sh; they are copied into /tmp/jot.XXXXXX/ at launch
#   so `claude plugin update` cannot yank them mid-run.
#
# Testing hook: set JOT_SKIP_LAUNCH=1 in the environment to skip Phase 2
#   entirely (no tmux, no claude). The canary suite uses this to verify
#   Phase 1 output without spawning real tmux sessions.

# usage: safe <command> [args...]
# returns: stdout from command, or "(unavailable)" on failure
safe() {
  local out
  out=$(hide_errors "$@") || out="(unavailable)"
  printf '%s' "${out:-(unavailable)}"
}

# usage: jot_build_claude_cmd
# Sets globals: TMPDIR_INV, SETTINGS_FILE, CLAUDE_CMD
jot_build_claude_cmd() {
  TMPDIR_INV=$(mktemp -d /tmp/jot.XXXXXX)
  SETTINGS_FILE="$TMPDIR_INV/settings.json"
  PERMISSIONS_FILE="${CLAUDE_PLUGIN_DATA}/permissions.local.json"

  # Lifecycle-safe: copy hook scripts into TMPDIR_INV so plugin updates
  # can't delete them mid-run.
  cp "${CLAUDE_PLUGIN_ROOT}/skills/jot/scripts/jot-session-start.sh" "$TMPDIR_INV/jot-session-start.sh"
  cp "${CLAUDE_PLUGIN_ROOT}/skills/jot/scripts/jot-stop.sh"          "$TMPDIR_INV/jot-stop.sh"
  cp "${CLAUDE_PLUGIN_ROOT}/skills/jot/scripts/jot-session-end.sh"   "$TMPDIR_INV/jot-session-end.sh"
  cp "${CLAUDE_PLUGIN_ROOT}/common/scripts/tmux.sh"               "$TMPDIR_INV/tmux.sh"
  cp "${CLAUDE_PLUGIN_ROOT}/common/scripts/tmux-launcher.sh"      "$TMPDIR_INV/tmux-launcher.sh"
  cp "${CLAUDE_PLUGIN_ROOT}/common/scripts/invoke_command.sh"     "$TMPDIR_INV/invoke_command.sh"
  cp "${CLAUDE_PLUGIN_ROOT}/common/scripts/silencers.sh"          "$TMPDIR_INV/silencers.sh"
  local hooks_scripts="$TMPDIR_INV"

  local permissions_file="${CLAUDE_PLUGIN_DATA}/permissions.local.json"
  local default_file="${CLAUDE_PLUGIN_ROOT}/skills/jot/scripts/assets/permissions.default.json"
  local default_sha_file="${CLAUDE_PLUGIN_ROOT}/skills/jot/scripts/assets/permissions.default.json.sha256"
  local prior_sha_file="${CLAUDE_PLUGIN_DATA}/permissions.default.sha256"
  mkdir -p "${CLAUDE_PLUGIN_DATA}"
  permissions_seed "$permissions_file" "$default_file" "$default_sha_file" "$prior_sha_file" "$LOG_FILE" "jot"

  local allow_json
  allow_json=$(CWD="$CWD" HOME="$HOME" REPO_ROOT="$REPO_ROOT" \
    python3 "${CLAUDE_PLUGIN_ROOT}/common/scripts/jot/expand_permissions.py" "$permissions_file")

  local hooks_json_file="$TMPDIR_INV/hooks.json"
  cat > "$hooks_json_file" <<JSON
{
  "SessionStart": [{"hooks": [{"type": "command", "command": "bash $hooks_scripts/jot-session-start.sh '$INPUT_FILE' '$TMPDIR_INV'"}]}],
  "Stop":         [{"hooks": [{"type": "command", "command": "bash $hooks_scripts/jot-stop.sh '$INPUT_FILE' '$TMPDIR_INV' '$STATE_DIR'"}]}],
  "SessionEnd":   [{"hooks": [{"type": "command", "command": "bash $hooks_scripts/jot-session-end.sh '$TMPDIR_INV'"}]}]
}
JSON

  CLAUDE_CMD=$(build_claude_cmd "$SETTINGS_FILE" "$allow_json" "$hooks_json_file" "$CWD" "$REPO_ROOT")
}

# usage: phase2_launch_window
# Spawns a tmux pane running claude for this jot invocation.
phase2_launch_window() {
  STATE_DIR="$REPO_ROOT/Todos/.jot-state"
  jot_state_init "$STATE_DIR"

  mkdir -p "${CLAUDE_PLUGIN_DATA}"
  local tmux_lock="${CLAUDE_PLUGIN_DATA}/tmux-launch.lock"
  if ! jot_lock_acquire "$tmux_lock" 10; then
    hide_errors echo "[jot] failed to acquire global tmux-launch lock at $tmux_lock" >> "$LOG_FILE"
    return 1
  fi

  local counter_file="${CLAUDE_PLUGIN_DATA}/pane-counter.txt"
  local n
  n=$(hide_errors cat "$counter_file") || n=0
  n=$(( n % 20 + 1 ))
  printf '%s\n' "$n" > "$counter_file"
  local pane_label="jot${n}"

  jot_build_claude_cmd

  local keepalive_cmd='exec sh -c '\''trap "" INT HUP TERM; printf "[jot keepalive — do not kill]\n"; exec tail -f /dev/null'\'''
  tmux_ensure_session jot jots "$CWD" "$keepalive_cmd" 'jot: keepalive'

  local PANE_ID
  if ! PANE_ID=$(tmux_split_worker_pane jot:jots "$CWD" "$CLAUDE_CMD"); then
    hide_errors echo "[jot] tmux split-window returned empty pane id" >> "$LOG_FILE"
    jot_lock_release "$tmux_lock"
    return 1
  fi

  printf '%s\n' "$PANE_ID" > "$TMPDIR_INV/tmux_target.tmp"
  mv "$TMPDIR_INV/tmux_target.tmp" "$TMPDIR_INV/tmux_target"

  tmux_set_pane_title "$PANE_ID" "$pane_label"
  tmux_retile jot:jots

  jot_lock_release "$tmux_lock"
  spawn_terminal_if_needed "jot" "$LOG_FILE" "jot"
}

# usage: jot_main
# Entry point. Reads hook JSON from stdin, runs Phase 1 + Phase 2.
jot_main() {
  : "${CLAUDE_PLUGIN_ROOT:?jot plugin env not set — not running under Claude Code plugin harness}"
  : "${CLAUDE_PLUGIN_DATA:?jot plugin env not set — not running under Claude Code plugin harness}"

  SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/skills/jot/scripts"

  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/silencers.sh"
  LOG_FILE="${JOT_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/jot-log.txt}"
  hide_errors mkdir -p "$(dirname "$LOG_FILE")"

  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/hook-json.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/platform.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/tmux-launcher.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/claude-launcher.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/permissions-seed.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/git.sh"

  INPUT=$(cat)
  case "$INPUT" in
    *'"/jot'*) ;;
    *) exit 0 ;;
  esac

  hide_errors printf '%s HOOK_INPUT %s\n' "$(date -Iseconds)" "$INPUT" >> "$LOG_FILE"
  check_requirements "jot" jq python3 tmux claude
  tmux_require_version "2.9" || { emit_block "jot requires tmux 2.9+"; exit 0; }

  . "$SCRIPTS_DIR/jot-state-lib.sh"

  PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""' | python3 "${CLAUDE_PLUGIN_ROOT}/common/scripts/jot/strip_stdin.py")
  if [[ "$PROMPT" != "/jot" && "$PROMPT" != "/jot "* ]]; then
    exit 0
  fi

  IDEA="${PROMPT#/jot}"
  IDEA="${IDEA# }"
  IDEA=$(printf '%s' "$IDEA" | python3 "${CLAUDE_PLUGIN_ROOT}/common/scripts/jot/strip_stdin.py")
  if [ -z "$IDEA" ]; then
    emit_block "jot: no idea provided"
    exit 0
  fi

  SESSION_ID=$(printf '%s' "$INPUT" | hide_errors jq -r '.session_id // "?"') || SESSION_ID="?"
  hide_errors printf '%s jot session=%s idea_len=%s\n' "$(date -Iseconds)" "$SESSION_ID" "${#IDEA}" >> "$LOG_FILE"

  trap 'rc=$?; emit_block "jot crashed at line $LINENO (rc=$rc)"; hide_errors printf "%s FAIL line=%s rc=%s\n" "$(date -Iseconds)" "$LINENO" "$rc" >> "$LOG_FILE"; exit 0' ERR

  TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | hide_errors jq -r '.transcript_path // empty')
  CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
  [ -z "$CWD" ] && CWD="$PWD"
  TIMESTAMP=$(date +%Y-%m-%dT%H-%M-%S)

  REPO_ROOT=$(hide_errors git -C "$CWD" rev-parse --show-toplevel) || REPO_ROOT=""
  if [ -z "$REPO_ROOT" ]; then
    emit_block "jot requires a git repository. Run 'git init' in your project root."
    exit 0
  fi

  TARGET_DIR="$REPO_ROOT/Todos"
  mkdir -p "$TARGET_DIR"
  INPUT_FILE="$TARGET_DIR/${TIMESTAMP}_input.txt"
  INPUT_ABS="${REPO_ROOT}/Todos/${TIMESTAMP}_input.txt"

  {
    printf '# Jot Task\n\n## Idea\n%s\n\n' "$IDEA"
    printf '## Working Directory\n%s\n\n' "$CWD"
  } > "$INPUT_FILE"

  BRANCH=$(safe git_get_branch_name "$CWD")
  COMMITS=$(safe git_get_recent_commits "$CWD")
  UNCOMMITTED=$(safe git_get_uncommitted "$CWD")
  OPEN_TODOS=$(safe "$SCRIPTS_DIR/scan-open-todos.sh" "$REPO_ROOT")
  if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
    CONVERSATION=$(safe python3 "$SCRIPTS_DIR/capture-conversation.py" "$TRANSCRIPT_PATH")
  else
    CONVERSATION="(no transcript available)"
  fi

  {
    printf '## Git State\n- Branch: %s\n- Commits: %s\n- Uncommitted: %s\n\n' "$BRANCH" "$COMMITS" "$UNCOMMITTED"
    printf '## Open TODO Files\n%s\n\n' "$OPEN_TODOS"
    printf '## Transcript Path\n%s\n\n' "${TRANSCRIPT_PATH:-(none)}"
    printf '## Recent Conversation\n%s\n\n' "$CONVERSATION"
  } >> "$INPUT_FILE"

  INSTRUCTIONS=$(REPO_ROOT="$REPO_ROOT" TIMESTAMP="$TIMESTAMP" BRANCH="$BRANCH" INPUT_ABS="$INPUT_ABS" \
    python3 "${CLAUDE_PLUGIN_ROOT}/common/scripts/jot/render_template.py" \
      "${CLAUDE_PLUGIN_ROOT}/skills/jot/scripts/assets/jot-instructions.md" \
      REPO_ROOT TIMESTAMP BRANCH INPUT_ABS)

  _BODY=$(cat "$INPUT_FILE")
  {
    printf '# Jot Task\n\n## Instructions\n%s\n\n' "$INSTRUCTIONS"
    printf '%s\n' "$_BODY" | tail -n +2
  } > "$INPUT_FILE"

  if [ "${JOT_SKIP_LAUNCH:-0}" = "1" ]; then
    emit_block "Jotted: $IDEA (launch skipped)"
    exit 0
  fi

  phase2_launch_window
  emit_block "Done! Jotted idea in $INPUT_ABS"
  exit 0
}
