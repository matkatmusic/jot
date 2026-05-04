#!/usr/bin/env bash
# plate-summary-watch.sh — fire-and-forget watchdog for the spawned
# plate-summary agent. Polls the agent's output file; when it appears
# and is non-empty, sends `/exit\n` to the agent's tmux pane to trigger
# a graceful shutdown. The agent's per-invocation SessionEnd hook
# (plate-summary-stop.sh) fires after that and runs the trailer-rewrite.
#
# Why a watcher and not a Stop hook on the agent's settings.json:
# Claude Code's `decision:"block"` for Stop means "BLOCK the stop, force
# agent to continue" — opposite of PreToolUse semantics. A Stop hook
# can't terminate the agent, only prevent termination. Killing the pane
# from the OUTSIDE (this script) is the working pattern, mirrored on
# `/debate`'s `wait_for_outputs` → `tmux_kill_pane` flow in
# skills/debate/scripts/debate-tmux-orchestrator.sh.
#
# Atomicity invariant (same as debate's `wait_for_outputs`): assumes the
# agent writes the output via Claude's Write tool, which is atomic
# temp-then-rename. Streaming writes would race against `[ -s ... ]`
# and trigger a mid-write kill.
#
# Usage:
#   plate-summary-watch.sh <pane_target> <output_file>
#     <pane_target>   tmux session:window form, e.g.
#                     plate-summary-7:plate-summary-abc12345
#     <output_file>   absolute path the agent writes its summary to
# Env knobs (rarely needed):
#   PLATE_SUMMARY_WATCH_TIMEOUT  seconds before giving up (default 600)
#   PLATE_SUMMARY_WATCH_INTERVAL seconds between polls   (default 2)
set -uo pipefail

PANE="${1:?pane target required}"
OUTPUT_FILE="${2:?output file required}"
TIMEOUT="${PLATE_SUMMARY_WATCH_TIMEOUT:-600}"
INTERVAL="${PLATE_SUMMARY_WATCH_INTERVAL:-2}"

elapsed=0
while [ "$elapsed" -lt "$TIMEOUT" ]; do
  if [ -s "$OUTPUT_FILE" ]; then
    # `/exit` is Claude TUI's graceful-shutdown command. Two send-keys
    # calls: the first inserts the literal text into the prompt buffer,
    # the second submits with Enter. Errors from send-keys are silenced
    # — if the pane has already gone away (user attached + closed), we
    # just exit successfully.
    tmux send-keys -t "$PANE" "/exit" 2>/dev/null || true
    tmux send-keys -t "$PANE" Enter 2>/dev/null || true
    exit 0
  fi
  sleep "$INTERVAL"
  elapsed=$((elapsed + INTERVAL))
done

# Timeout: leave the pane alive so the user can investigate. SessionEnd
# won't fire until the user closes it manually, which is the safer
# default than masking a real failure with a hard pane kill.
exit 1
