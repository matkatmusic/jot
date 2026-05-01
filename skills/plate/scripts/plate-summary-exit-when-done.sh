#!/usr/bin/env bash
# plate-summary-exit-when-done.sh — per-invocation Stop hook for the
# spawned summary agent. Fires after every assistant turn. When the
# agent's output_file exists and is non-empty, emits a JSON decision
# block telling claude to stop so the SessionEnd hook can fire and the
# trailer-rewrite pipeline can run. Otherwise exits 0 silently and lets
# the agent keep working.
#
# Usage: plate-summary-exit-when-done.sh <output_file>
set -euo pipefail

output_file="${1:?output_file required}"

if [ -s "$output_file" ]; then
  # decision:"block" with a stop reason halts the agent immediately;
  # the outer claude session then proceeds to SessionEnd, which fires
  # plate-summary-stop.sh -> cli.py set-plate-summary.
  printf '%s\n' '{"decision":"block","reason":"summary written; exiting"}'
  exit 0
fi

exit 0
