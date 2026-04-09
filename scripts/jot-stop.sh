#!/bin/bash
# jot-stop.sh — Stop hook for per-invocation claude windows.
#
# Fires when claude finishes responding to its one job. Verifies the
# PROCESSED: marker was written, appends SUCCESS/FAIL to audit.log, rotates
# the log, then kills this window asynchronously (which terminates this
# claude process, triggers SessionEnd, and wipes $TMPDIR_INV).
#
# Key contract: this claude instance processes exactly ONE /jot and exits.
# No /clear, no queue drain, no shared state with other jots.
#
# Args:
#   $1 = absolute path to the input.txt this claude was told to process
#   $2 = tmux target (e.g. "jot:authv3_vps-2026-04-08T14-00-12")
#   $3 = state_dir (for audit.log; e.g. "$CWD/Todos/.jot-state")
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=jot-state-lib.sh
. "$SCRIPT_DIR/jot-state-lib.sh"

INPUT_FILE="${1:-}"
TMUX_TARGET="${2:-}"
STATE_DIR="${3:-}"

if [ -z "$INPUT_FILE" ] || [ -z "$TMUX_TARGET" ] || [ -z "$STATE_DIR" ]; then
  echo "[jot-stop] missing args (input_file, tmux_target, state_dir)" >&2
  exit 0
fi

jot_state_init "$STATE_DIR"

AUDIT="$STATE_DIR/audit.log"

# Definitive success check: PROCESSED: marker on head -1 of input.txt.
ts=$(date -Iseconds)
if [ -f "$INPUT_FILE" ]; then
  first_line=$(head -1 "$INPUT_FILE" 2>/dev/null || true)
  if [[ "$first_line" == PROCESSED:* ]]; then
    printf '%s SUCCESS %s\n' "$ts" "$INPUT_FILE" >> "$AUDIT"
  else
    printf '%s FAIL %s (no PROCESSED marker)\n' "$ts" "$INPUT_FILE" >> "$AUDIT"
  fi
else
  printf '%s FAIL %s (input.txt missing)\n' "$ts" "$INPUT_FILE" >> "$AUDIT"
fi

jot_audit_rotate "$AUDIT" 1000

# Kill this window in the background so the hook exits cleanly BEFORE tmux
# signals the claude process. The short sleep lets jot-stop.sh return to
# claude, claude acknowledges the hook completion, THEN tmux kill-window
# takes effect.
( sleep 0.5 && tmux kill-window -t "$TMUX_TARGET" 2>/dev/null ) >/dev/null 2>&1 &
disown 2>/dev/null || true

exit 0
