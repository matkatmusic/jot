#!/bin/bash
# todo-stop.sh — Stop hook for per-invocation claude panes.
# Verifies the PROCESSED: marker, appends SUCCESS/FAIL to audit.log, then
# kills the pane asynchronously.
#
# IMPORTANT: sidecar read MUST be synchronous before the backgrounded
# kill-pane subshell is forked. SessionEnd fires after Stop returns and
# wipes $TMPDIR_INV; the already-forked subshell holds the pane id in
# memory so the wipe is safe.
#
# Args: $1 = input.txt path   $2 = tmpdir   $3 = state_dir
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/tmux.sh"
. "$SCRIPT_DIR/invoke_command.sh"
. "$SCRIPT_DIR/silencers.sh"

INPUT_FILE="${1:-}"
TMPDIR_INV="${2:-}"
STATE_DIR="${3:-}"

if [ -z "$INPUT_FILE" ] || [ -z "$TMPDIR_INV" ] || [ -z "$STATE_DIR" ]; then
  echo "[todo-stop] missing args (input_file, tmpdir_inv, state_dir)" >&2
  exit 0
fi

TARGET_FILE="$TMPDIR_INV/tmux_target"
TMUX_TARGET=""
for _ in 1 2 3 4 5; do
  if [ -s "$TARGET_FILE" ]; then
    TMUX_TARGET=$(head -1 "$TARGET_FILE")
    [ -n "$TMUX_TARGET" ] && break
  fi
  sleep 0.2
done

if [ -z "$TMUX_TARGET" ]; then
  echo "[todo-stop] tmux_target sidecar empty after retries" >&2
  exit 0
fi

mkdir -p "$STATE_DIR"
AUDIT="$STATE_DIR/audit.log"

ts=$(date -Iseconds)
if [ -f "$INPUT_FILE" ]; then
  first_line=$(head -1 "$INPUT_FILE")
  if [[ "$first_line" == PROCESSED:* ]]; then
    printf '%s SUCCESS %s\n' "$ts" "$INPUT_FILE" >> "$AUDIT"
  else
    printf '%s FAIL %s (no PROCESSED marker)\n' "$ts" "$INPUT_FILE" >> "$AUDIT"
  fi
else
  printf '%s FAIL %s (input.txt missing)\n' "$ts" "$INPUT_FILE" >> "$AUDIT"
fi

lines=$(wc -l < "$AUDIT" | tr -d ' ')
if [ "${lines:-0}" -gt 1000 ]; then
  tail -1000 "$AUDIT" > "$AUDIT.trim" && mv "$AUDIT.trim" "$AUDIT"
fi

( sleep 0.5
  hide_output hide_errors tmux_kill_pane "$TMUX_TARGET"
  hide_output hide_errors tmux_retile "todo:todos"
) &
hide_errors disown

exit 0
