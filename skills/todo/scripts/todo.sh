#!/bin/bash
# todo.sh — function definitions for the /todo hook.
# Sourced by todo-orchestrator.sh. No side effects when sourced.
#
# The /todo hook writes Todos/.todo-state/pending-XXXXXX.json and
# exits 0 silently so the foreground Claude can dispatch the `todo` skill
# body (which may ask clarification questions via AskUserQuestion).

todo_main() {
  : "${CLAUDE_PLUGIN_DATA:?todo plugin env not set}"

  local REPO
  REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
  export CLAUDE_PLUGIN_ROOT="$REPO"

  local SCRIPTS_DIR="$REPO/skills/todo/scripts"
  LOG_FILE="${TODO_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/todo-log.txt}"

  . "$REPO/common/scripts/silencers.sh"
  . "$REPO/common/scripts/hook-json.sh"
  . "$REPO/common/scripts/git.sh"
  hide_errors mkdir -p "$(dirname "$LOG_FILE")"

  INPUT=$(cat)
  case "$INPUT" in
    *'"/todo'*) ;;
    *) exit 0 ;;
  esac

  hide_errors printf '%s HOOK_INPUT %s\n' "$(date -Iseconds)" "$INPUT" >> "$LOG_FILE"
  check_requirements "todo" jq python3 tmux claude

  PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""' | \
           python3 "$REPO/common/scripts/jot/strip_stdin.py")
  if [[ "$PROMPT" != "/todo" && "$PROMPT" != "/todo "* ]]; then
    exit 0
  fi

  IDEA="${PROMPT#/todo}"; IDEA="${IDEA# }"
  SESSION_ID=$(printf '%s' "$INPUT" | hide_errors jq -r '.session_id // "unknown"') || SESSION_ID="unknown"
  TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | hide_errors jq -r '.transcript_path // empty')
  CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
  [ -z "$CWD" ] && CWD="$PWD"

  REPO_ROOT=$(hide_errors git_get_repo_root "$CWD") || REPO_ROOT=""
  if [ -z "$REPO_ROOT" ]; then
    emit_block "todo requires a git repository. Run 'git init' in your project root."
    exit 0
  fi

  STATE_DIR="$REPO_ROOT/Todos/.todo-state"
  mkdir -p "$STATE_DIR"
  TIMESTAMP=$(date +%Y-%m-%dT%H-%M-%S)

  # Atomic, per-invocation-unique pending filename. BSD mktemp requires the
  # X's to be trailing, so we generate a unique base via `mktemp -u`, append
  # `.json`, and atomically claim the path with `set -C` (noclobber). Same
  # convention as scan-existing-todos.sh.
  local PENDING_BASE PENDING_FILE
  while :; do
    PENDING_BASE=$(mktemp -u "$STATE_DIR/pending-XXXXXX")
    PENDING_FILE="${PENDING_BASE}.json"
    if ( set -C; : > "$PENDING_FILE" ) 2>/dev/null; then
      break
    fi
  done

  IDEA_JSON=$(printf '%s' "$IDEA" | \
              python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')

  cat > "$PENDING_FILE" <<JSON
{
  "session_id": "$SESSION_ID",
  "transcript_path": "$TRANSCRIPT_PATH",
  "cwd": "$CWD",
  "repo_root": "$REPO_ROOT",
  "idea": $IDEA_JSON,
  "timestamp": "$TIMESTAMP",
  "todo_plugin_root": "$REPO",
  "todo_scripts_dir": "$SCRIPTS_DIR",
  "pending_file": "$PENDING_FILE",
  "created_at": "$(date -Iseconds)"
}
JSON

  # Silent exit — no emit_block so the fg claude dispatches the `todo` skill.
  exit 0
}
