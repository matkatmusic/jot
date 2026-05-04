#!/bin/bash
# todo-session-start.sh — SessionStart hook for per-invocation claude panes.
# Fires once when claude starts in a fresh tmux pane. Reads the pane id from
# "$TMPDIR_INV/tmux_target" (written by todo-launcher.sh), then sends the
# initial "Read <input.txt> and follow the instructions" prompt.
#
# Args: $1 = absolute path to the input.txt for THIS /todo invocation
#       $2 = absolute path to the per-invocation tmpdir (/tmp/todo.XXXXXX)
set -uo pipefail

INPUT_FILE="${1:-}"
TMPDIR_INV="${2:-}"

if [ -z "$INPUT_FILE" ] || [ -z "$TMPDIR_INV" ]; then
  echo "[todo-session-start] missing args (input_file, tmpdir_inv)" >&2
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
  echo "[todo-session-start] tmux_target sidecar empty after retries" >&2
  exit 0
fi

# shellcheck source=tmux.sh
. "$(dirname "$0")/tmux.sh"
# shellcheck source=tmux-launcher.sh
. "$(dirname "$0")/tmux-launcher.sh"

if ! tmux_wait_for_claude_readiness "$TMUX_TARGET"; then
  echo "[todo-session-start] claude TUI not ready, aborting send" >&2
  exit 1
fi

tmux_send_and_submit "$TMUX_TARGET" \
  "Read $INPUT_FILE and follow the instructions at the top of that file"

exit 0
