#!/usr/bin/env bash
# plate.sh — UserPromptSubmit hook entry point.
# Reads JSON from stdin. Dispatches /plate variants.
# Matches jot.sh architecture: emit_block for suppression, self-filtering.
set -euo pipefail

: "${CLAUDE_PLUGIN_ROOT:?plate plugin env not set}"
: "${CLAUDE_PLUGIN_DATA:?plate plugin env not set}"

SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/scripts"
PYTHON_DIR="${CLAUDE_PLUGIN_ROOT}/python"
LOG_FILE="${PLATE_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/plate-log.txt}"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# shellcheck source=lib/paths.sh
. "$SCRIPTS_DIR/lib/paths.sh"
# shellcheck source=lib/lock.sh
. "$SCRIPTS_DIR/lib/lock.sh"

# ── emit_block: suppress prompt from reaching the LLM ────────────────────
emit_block() {
  local reason="$1"
  if command -v jq >/dev/null 2>&1; then
    jq -n --arg r "$reason" '{decision:"block", reason:$r}'
  else
    local esc="${reason//\\/\\\\}"
    esc="${esc//\"/\\\"}"
    printf '{"decision":"block","reason":"%s"}\n' "$esc"
  fi
}

# ── check_requirements ────────────────────────────────────────────────────
check_requirements() {
  local -a missing=()
  command -v jq      >/dev/null 2>&1 || missing+=("jq")
  command -v python3 >/dev/null 2>&1 || missing+=("python3")
  command -v tmux    >/dev/null 2>&1 || missing+=("tmux")
  command -v claude  >/dev/null 2>&1 || missing+=("claude")
  if [ ${#missing[@]} -gt 0 ]; then
    local list=""
    for item in "${missing[@]}"; do
      [ -z "$list" ] && list="$item" || list="$list, $item"
    done
    emit_block "plate needs: $list"
    exit 0
  fi
}

# ── Read hook input from stdin ────────────────────────────────────────────
INPUT=$(cat)

# ── Fast-path: bail if not /plate ─────────────────────────────────────────
case "$INPUT" in
  *'"/plate'*) ;;
  *) exit 0 ;;
esac

check_requirements

# ── Parse fields ──────────────────────────────────────────────────────────
PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""' | python3 -c 'import sys; print(sys.stdin.read().strip())')
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || echo "unknown")
TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | jq -r '.transcript_path // ""' 2>/dev/null || echo "")
CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // ""' 2>/dev/null || echo "")
[ -z "$CWD" ] && CWD="$PWD"

# ── Regex gate: only /plate and its variants ──────────────────────────────
if ! printf '%s' "$PROMPT" | grep -qE '^/plate(\s+(--done|--drop|--next|--show))?$'; then
  exit 0
fi

printf '%s plate session=%s prompt="%s"\n' "$(date -Iseconds)" "$SESSION_ID" "$PROMPT" >> "$LOG_FILE" 2>/dev/null || true

# ── ERR trap ──────────────────────────────────────────────────────────────
# Full stack trace lands in $LOG_FILE; user-visible emit_block stays short
# and points at the log for diagnosis.
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
  } >> "$LOG_FILE" 2>/dev/null || true
}
trap 'rc=$?; plate_log_stack_trace "$rc" "$LINENO" "$BASH_COMMAND"; emit_block "plate crashed (rc=$rc line=$LINENO cmd=$BASH_COMMAND) — see $LOG_FILE"; exit 0' ERR

# ── Drift alert injection (§11.3) ────────────────────────────────────────
plate_discover_root 2>/dev/null || true
if [ -n "${PLATE_ROOT:-}" ]; then
  DRIFT_INSTANCE_FILE="${PLATE_ROOT}/instances/${SESSION_ID}.json"
  if [ -f "$DRIFT_INSTANCE_FILE" ]; then
    DRIFT_MSG=$(DRIFT_INSTANCE_FILE="$DRIFT_INSTANCE_FILE" PYTHON_DIR="$PYTHON_DIR" python3 <<'PY' 2>/dev/null
import json, os, sys
sys.path.insert(0, os.environ.get('PYTHON_DIR', ''))
try:
    from instance_rw import mutate
    from pathlib import Path
except Exception:
    sys.exit(0)
path = Path(os.environ['DRIFT_INSTANCE_FILE'])
try:
    d = json.load(open(path))
except Exception:
    sys.exit(0)
da = d.get('drift_alert', {}) or {}
if da.get('pending'):
    def _clear(x):
        x.setdefault('drift_alert', {})['pending'] = False
    mutate(path, _clear)
    print(da.get('message', 'drift detected'))
PY
)
    if [ -n "$DRIFT_MSG" ]; then
      printf '[plate drift] %s\n' "$DRIFT_MSG" >&2
    fi
  fi
fi

# ── Extract variant ───────────────────────────────────────────────────────
VARIANT=$(printf '%s' "$PROMPT" | sed 's|^/plate||; s|^ ||')

# ── Dispatch by variant ───────────────────────────────────────────────────
case "$VARIANT" in
  "")
    # /plate (push) — three-way gate (§8.1)
    plate_discover_root
    plate_ensure_dirs
    INSTANCE_FILE="${PLATE_ROOT}/instances/${SESSION_ID}.json"

    if [ -f "$INSTANCE_FILE" ]; then
      # PATH 1: this session has plate state → suppress + background push
      bash "$SCRIPTS_DIR/push.sh" "$SESSION_ID" "$TRANSCRIPT_PATH" "$CWD"
      emit_block "[plate] pushed"
    elif [ -d "${PLATE_ROOT}/instances" ] && \
         find "${PLATE_ROOT}/instances" -name "*.json" -maxdepth 1 2>/dev/null | read -r _; then
      # PATH 3: other instances exist → let prompt through for parent selection.
      # Create a fully-populated instance file NOW so register-parent.sh and
      # push.sh (which run later from the SKILL.md body) mutate a complete
      # dict rather than an empty {}. Without this, top-level fields like
      # convo_id/cwd/created_at end up missing because load() on a missing
      # file returns {} and neither downstream script calls new_instance().
      python3 "$PYTHON_DIR/instance_rw.py" create-instance \
        "$INSTANCE_FILE" "$SESSION_ID" "$CWD" \
        "$(git symbolic-ref --short HEAD 2>/dev/null || echo 'detached')"

      # Drop a registration-context file so the SKILL.md body (running in
      # the foreground claude) can read session_id/transcript_path/cwd
      # without relying on `${SESSION_ID}`-style shell expansion that
      # never happens inside a skill body.
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
      # Do NOT emit_block. Exit 0 lets the prompt reach the SKILL.md body.
      exit 0
    else
      # PATH 2: virgin repo → auto-register as top-level + suppress + push
      python3 "$PYTHON_DIR/instance_rw.py" create-instance \
        "$INSTANCE_FILE" "$SESSION_ID" "$CWD" \
        "$(git symbolic-ref --short HEAD 2>/dev/null || echo 'detached')"
      bash "$SCRIPTS_DIR/push.sh" "$SESSION_ID" "$TRANSCRIPT_PATH" "$CWD"
      emit_block "[plate] registered + pushed"
    fi
    ;;
  "--done")
    # /plate --done — pass through to skill body which runs done.sh
    # Foreground because user needs to see the commit output + resume command
    exit 0
    ;;
  "--drop")
    # /plate --drop — suppress + run drop.sh in background
    plate_discover_root
    INSTANCE_FILE="${PLATE_ROOT}/instances/${SESSION_ID}.json"
    bash "$SCRIPTS_DIR/drop.sh" "$SESSION_ID" "$INSTANCE_FILE"
    emit_block "[plate] dropped"
    ;;
  "--next")
    # /plate --next — pass through to skill body
    exit 0
    ;;
  "--show")
    # /plate --show — pass through to skill body
    exit 0
    ;;
esac

exit 0
