#!/bin/bash
# jot-session-start.sh — SessionStart hook for per-invocation claude windows.
# Fires once when claude starts up in a fresh tmux window. Sends the initial
# "Read <input.txt> and follow the instructions" prompt via tmux send-keys.
#
# Args:
#   $1 = absolute path to the input.txt for THIS jot invocation
#   $2 = tmux target (e.g. "jot:authv3_vps-2026-04-08T14-00-12")
set -uo pipefail

INPUT_FILE="${1:-}"
TMUX_TARGET="${2:-}"

if [ -z "$INPUT_FILE" ] || [ -z "$TMUX_TARGET" ]; then
  echo "[jot-session-start] missing args (input_file, tmux_target)" >&2
  exit 0
fi

# Brief delay so claude's prompt loop accepts input. Without this, send-keys
# fires before claude's TUI is ready to read keys and the prompt is lost.
sleep 2

tmux send-keys -t "$TMUX_TARGET" \
  "Read $INPUT_FILE and follow the instructions at the top of that file" Enter

exit 0
