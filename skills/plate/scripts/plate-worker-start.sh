#!/bin/bash
# plate-worker-start.sh — SessionStart hook for per-invocation claude windows.
# Fires once when claude starts in a tmux window. Sends the initial prompt.
# Args: $1=INPUT_FILE path  $2=tmux target (e.g. "plate:dotfiles-2026-04-09T13-12-34Z")
set -uo pipefail

INPUT_FILE="${1:-}"
TMUX_TARGET="${2:-}"

if [ -z "$INPUT_FILE" ] || [ -z "$TMUX_TARGET" ]; then
  echo "[plate-worker-start] missing args" >&2
  exit 0
fi

# Brief delay so claude's prompt loop accepts input.
sleep 2

tmux send-keys -t "$TMUX_TARGET" \
  "Read $INPUT_FILE and follow the instructions at the top of that file" Enter

exit 0
