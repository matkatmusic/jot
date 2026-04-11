#!/bin/bash
# plate-worker-stop.sh — Stop hook. Verifies agent wrote fields, kills window.
# Args: $1=INPUT_FILE  $2=tmux target
set -uo pipefail

INPUT_FILE="${1:-}"
TMUX_TARGET="${2:-}"

if [ -z "$INPUT_FILE" ] || [ -z "$TMUX_TARGET" ]; then
  exit 0
fi

# Check that the agent marked the input as processed
ts=$(date -Iseconds)
if [ -f "$INPUT_FILE" ]; then
  first_line=$(head -1 "$INPUT_FILE" 2>/dev/null || true)
  if [[ "$first_line" == PROCESSED:* ]]; then
    echo "[$ts] plate-worker SUCCESS: $INPUT_FILE" >&2
  else
    echo "[$ts] plate-worker FAIL: no PROCESSED marker in $INPUT_FILE" >&2
  fi
fi

# Kill this window asynchronously (let hook return first)
( sleep 0.5 && tmux kill-window -t "$TMUX_TARGET" 2>/dev/null ) >/dev/null 2>&1 &
disown 2>/dev/null || true

exit 0
