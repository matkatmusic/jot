#!/bin/bash
# plate-worker-start.sh — SessionStart hook for per-invocation claude windows.
# Fires once when claude starts in a tmux window. Sends the initial prompt.
# Args: $1=INPUT_FILE path  $2=tmux target (e.g. "plate:dotfiles-2026-04-09T13-12-34Z")
set -uo pipefail

INPUT_FILE="${1:-}"
TMUX_TARGET="${2:-}"

LOG="${CLAUDE_PLUGIN_DATA:-/tmp}/plate-worker-start.log"
{
  printf '[%s] start input=%s target=%s\n' "$(date -Iseconds)" "$INPUT_FILE" "$TMUX_TARGET"
} >> "$LOG" 2>/dev/null

if [ -z "$INPUT_FILE" ] || [ -z "$TMUX_TARGET" ]; then
  echo "[plate-worker-start] missing args" >&2
  exit 0
fi

# Detach from the parent process group so the hook doesn't block claude's
# startup. claude's SessionStart hook runs synchronously in some versions
# and `sleep 2` + `send-keys` cannot complete until claude's own TUI has
# the tmux pane attached and ready to accept keys.
(
  sleep 2
  tmux send-keys -t "$TMUX_TARGET" \
    "Read $INPUT_FILE and follow the instructions at the top of that file" Enter \
    >> "$LOG" 2>&1
  printf '[%s] send-keys rc=%s\n' "$(date -Iseconds)" "$?" >> "$LOG" 2>/dev/null
) >/dev/null 2>&1 &
disown 2>/dev/null || true

exit 0
