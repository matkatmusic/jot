#!/bin/bash
# jot-session-start.sh — SessionStart hook for per-invocation claude panes.
# Fires once when claude starts up in a fresh tmux pane. Reads the pane id
# from "$TMPDIR_INV/tmux_target" (written by phase2_launch_window after
# split-window), then sends the initial "Read <input.txt> and follow the
# instructions" prompt via tmux send-keys.
#
# Args:
#   $1 = absolute path to the input.txt for THIS jot invocation
#   $2 = absolute path to the per-invocation tmpdir (e.g. /tmp/jot.abcXYZ)
set -uo pipefail

INPUT_FILE="${1:-}"
TMPDIR_INV="${2:-}"

if [ -z "$INPUT_FILE" ] || [ -z "$TMPDIR_INV" ]; then
  echo "[jot-session-start] missing args (input_file, tmpdir_inv)" >&2
  exit 0
fi

# Read the tmux pane id sidecar written atomically by phase2_launch_window
# immediately after `tmux split-window` returned. The retry loop is a
# belt-and-suspenders guard: in practice the sidecar is always present by
# the time claude's SessionStart fires (claude takes ~1-2s to boot, the
# sidecar is written in microseconds after split-window).
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
  echo "[jot-session-start] tmux_target sidecar empty after retries" >&2
  exit 0
fi

# shellcheck source=tmux.sh
. "$(dirname "$0")/tmux.sh"
# shellcheck source=tmux-launcher.sh
. "$(dirname "$0")/tmux-launcher.sh"

# Wait for claude's TUI to show the input prompt before sending keys.
if ! tmux_wait_for_claude_readiness "$TMUX_TARGET"; then
  echo "[jot-session-start] claude TUI not ready, aborting send" >&2
  exit 1
fi

tmux_send_and_submit "$TMUX_TARGET" \
  "Read $INPUT_FILE and follow the instructions at the top of that file"

exit 0
