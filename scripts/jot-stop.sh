#!/bin/bash
# jot-stop.sh — Stop hook for per-invocation claude panes.
#
# Fires when claude finishes responding to its one job. Reads the tmux
# pane id from "$TMPDIR_INV/tmux_target", verifies the PROCESSED: marker
# was written, appends SUCCESS/FAIL to audit.log, rotates the log, then
# kills THIS pane asynchronously (which terminates this claude process,
# triggers SessionEnd, and wipes $TMPDIR_INV).
#
# IMPORTANT ordering contract: the sidecar MUST be read synchronously
# into $TMUX_TARGET BEFORE the backgrounded kill-pane subshell is
# forked. SessionEnd fires AFTER Stop returns and wipes $TMPDIR_INV
# (sidecar included), but the already-forked subshell holds the pane id
# in memory so the wipe is safe. Do NOT move the sidecar read into the
# subshell.
#
# Key contract: this claude instance processes exactly ONE /jot and exits.
# No /clear, no queue drain, no shared state with other jots.
#
# Args:
#   $1 = absolute path to the input.txt this claude was told to process
#   $2 = absolute path to the per-invocation tmpdir (e.g. /tmp/jot.abcXYZ)
#   $3 = state_dir (for audit.log; e.g. "$REPO_ROOT/Todos/.jot-state")
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=jot-state-lib.sh
. "$SCRIPT_DIR/jot-state-lib.sh"

INPUT_FILE="${1:-}"
TMPDIR_INV="${2:-}"
STATE_DIR="${3:-}"

if [ -z "$INPUT_FILE" ] || [ -z "$TMPDIR_INV" ] || [ -z "$STATE_DIR" ]; then
  echo "[jot-stop] missing args (input_file, tmpdir_inv, state_dir)" >&2
  exit 0
fi

# Read the tmux pane id sidecar SYNCHRONOUSLY into $TMUX_TARGET NOW,
# before anything else. The backgrounded kill-pane subshell below captures
# this variable in memory, so SessionEnd's subsequent wipe of $TMPDIR_INV
# cannot break it. See the "IMPORTANT ordering contract" note in the file
# header for why this order matters.
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
  echo "[jot-stop] tmux_target sidecar empty after retries" >&2
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

# Kill this pane in the background so the hook exits cleanly BEFORE tmux
# signals the claude process. The short sleep lets jot-stop.sh return to
# claude, claude acknowledges the hook completion, THEN tmux kill-pane
# takes effect. The chained `select-layout tiled` re-tiles the surviving
# panes (keepalive + any other in-flight workers) into a fresh NxM grid
# so the dashboard layout stays balanced after each completion.
#
# NOTE: $TMUX_TARGET was read synchronously above from the sidecar file,
# BEFORE this fork. The subshell below holds the pane id in memory; by
# the time SessionEnd wipes $TMPDIR_INV the subshell no longer needs
# the file. Do NOT move the sidecar read into this subshell.
( sleep 0.5 \
  && tmux kill-pane -t "$TMUX_TARGET" 2>/dev/null \
  && tmux select-layout -t jot:jots tiled 2>/dev/null \
) >/dev/null 2>&1 &
disown 2>/dev/null || true

exit 0
