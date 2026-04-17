#!/usr/bin/env bash
# plate.sh — function definitions for the /plate hook.
# Sourced by plate-orchestrator.sh. No side effects when sourced.

# usage: plate_log_stack_trace <rc> <line> <command>
plate_log_stack_trace() {
  local rc="$1" line="$2" cmd="$3" ts
  ts="$(date -Iseconds)"
  {
    printf '\n---- plate ERR %s ----\n' "$ts"
    printf 'session=%s rc=%s line=%s\n' "$SESSION_ID" "$rc" "$line"
    printf 'last_command=%s\n' "$cmd"
    printf 'prompt=%q\n' "$PROMPT"
    printf 'cwd=%s\n' "$CWD"
    printf 'plate_root=%s\n' "${PLATE_ROOT:-<unset>}"
    printf 'stack:\n'
    local i=0
    while [ "$i" -lt "${#FUNCNAME[@]}" ]; do
      printf '  #%d %s at %s:%s\n' "$i" "${FUNCNAME[$i]:-MAIN}" "${BASH_SOURCE[$i]:-?}" "${BASH_LINENO[$i]:-?}"
      i=$((i+1))
    done
  } >> "$LOG_FILE" 2>/dev/null
}

# usage: plate_dispatch
# Reads globals: VARIANT, SCRIPTS_DIR, PYTHON_DIR, SESSION_ID, TRANSCRIPT_PATH,
#   CWD, PLATE_ROOT, INSTANCE_FILE, CLAUDE_PLUGIN_ROOT
plate_dispatch() {
  case "$VARIANT" in
    "")
      plate_discover_repo_root
      plate_ensure_dirs
      INSTANCE_FILE="${PLATE_ROOT}/instances/${SESSION_ID}.json"

      if [ -f "$INSTANCE_FILE" ]; then
        bash "$SCRIPTS_DIR/push.sh" "$SESSION_ID" "$TRANSCRIPT_PATH" "$CWD"
        emit_block "[plate] pushed"
      elif [ -d "${PLATE_ROOT}/instances" ] && \
           hide_errors find "${PLATE_ROOT}/instances" -name "*.json" -maxdepth 1 | read -r _; then
        python3 "$PYTHON_DIR/instance_rw.py" create-instance \
          "$INSTANCE_FILE" "$SESSION_ID" "$CWD" \
          "$(hide_errors git symbolic-ref --short HEAD || echo 'detached')"

        REG_FILE="${PLATE_ROOT}/pending-registration.json"
        cat > "$REG_FILE" <<REG
{
  "session_id": "$SESSION_ID",
  "transcript_path": "$TRANSCRIPT_PATH",
  "cwd": "$CWD",
  "plate_plugin_root": "$CLAUDE_PLUGIN_ROOT",
  "plate_scripts_dir": "$SCRIPTS_DIR",
  "created_at": "$(date -Iseconds)"
}
REG
        exit 0
      else
        python3 "$PYTHON_DIR/instance_rw.py" create-instance \
          "$INSTANCE_FILE" "$SESSION_ID" "$CWD" \
          "$(hide_errors git symbolic-ref --short HEAD || echo 'detached')"
        bash "$SCRIPTS_DIR/push.sh" "$SESSION_ID" "$TRANSCRIPT_PATH" "$CWD"
        emit_block "[plate] registered + pushed"
      fi
      ;;
    "--done")
      exit 0
      ;;
    "--drop")
      plate_discover_repo_root
      INSTANCE_FILE="${PLATE_ROOT}/instances/${SESSION_ID}.json"
      bash "$SCRIPTS_DIR/drop.sh" "$SESSION_ID" "$INSTANCE_FILE"
      emit_block "[plate] dropped"
      ;;
    "--next")
      exit 0
      ;;
    "--show")
      exit 0
      ;;
  esac
}

# usage: plate_main
# Entry point. Reads hook JSON from stdin, dispatches /plate variants.
plate_main() {
  : "${CLAUDE_PLUGIN_ROOT:?plate plugin env not set}"
  : "${CLAUDE_PLUGIN_DATA:?plate plugin env not set}"

  SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/scripts"
  PYTHON_DIR="${CLAUDE_PLUGIN_ROOT}/python"
  LOG_FILE="${PLATE_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/plate-log.txt}"

  . "${CLAUDE_PLUGIN_ROOT}/scripts/lib/invoke_command.sh"
  hide_errors mkdir -p "$(dirname "$LOG_FILE")"

  . "$SCRIPTS_DIR/paths.sh"
  . "${CLAUDE_PLUGIN_ROOT}/scripts/lib/lock.sh"
  . "${CLAUDE_PLUGIN_ROOT}/scripts/lib/hook-json.sh"

  INPUT=$(cat)
  case "$INPUT" in
    *'"/plate'*) ;;
    *) exit 0 ;;
  esac

  check_requirements "plate" jq python3 tmux claude

  PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""' | python3 -c 'import sys; print(sys.stdin.read().strip())')
  SESSION_ID=$(printf '%s' "$INPUT" | hide_errors jq -r '.session_id // "unknown"') || SESSION_ID="unknown"
  TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | hide_errors jq -r '.transcript_path // empty')
  CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
  [ -z "$CWD" ] && CWD="$PWD"

  if ! printf '%s' "$PROMPT" | grep -qE '^/plate(\s+(--done|--drop|--next|--show))?$'; then
    exit 0
  fi

  hide_errors printf '%s plate session=%s prompt="%s"\n' "$(date -Iseconds)" "$SESSION_ID" "$PROMPT" >> "$LOG_FILE"

  trap 'rc=$?; plate_log_stack_trace "$rc" "$LINENO" "$BASH_COMMAND"; emit_block "plate crashed (rc=$rc line=$LINENO cmd=$BASH_COMMAND) — see $LOG_FILE"; exit 0' ERR

  hide_errors plate_discover_repo_root || PLATE_ROOT=""
  if [ -n "${PLATE_ROOT:-}" ]; then
    DRIFT_INSTANCE_FILE="${PLATE_ROOT}/instances/${SESSION_ID}.json"
    if [ -f "$DRIFT_INSTANCE_FILE" ]; then
      DRIFT_MSG=$(DRIFT_INSTANCE_FILE="$DRIFT_INSTANCE_FILE" PYTHON_DIR="$PYTHON_DIR" hide_errors python3 "$PYTHON_DIR/check_drift_alert.py")
      if [ -n "$DRIFT_MSG" ]; then
        printf '[plate drift] %s\n' "$DRIFT_MSG" >&2
      fi
    fi
  fi

  VARIANT=$(printf '%s' "$PROMPT" | sed 's|^/plate||; s|^ ||')
  plate_dispatch
  exit 0
}
