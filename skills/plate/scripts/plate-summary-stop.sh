#!/usr/bin/env bash
# plate-summary-stop.sh — per-invocation SessionEnd hook for the
# spawned summary agent. Reads the agent's output file and forwards it
# to `cli.py set-plate-summary` which runs the trailer-rewrite via
# rebase-reword.
#
# Args:
#   $1 = repo (absolute path)
#   $2 = branch (the parent branch; plate branch is <branch>-plate)
#   $3 = output_file (path the agent wrote its summary to)
#
# Always exit 0 so a failure here can never block session shutdown.
set -uo pipefail

REPO="${1:-}"
BRANCH="${2:-}"
OUTPUT_FILE="${3:-}"

[ -z "$REPO" ] || [ -z "$BRANCH" ] || [ -z "$OUTPUT_FILE" ] && exit 0
[ -f "$OUTPUT_FILE" ] || exit 0

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
CLI_PATH="$REPO_ROOT/common/scripts/plate/cli.py"

LOG_FILE="${PLATE_LOG_FILE:-${CLAUDE_PLUGIN_DATA:-$HOME/.claude/plugins/data/plate-jot-dev}/plate-log.txt}"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

OUT=$(python3 "$CLI_PATH" set-plate-summary "$REPO" "$BRANCH" "$OUTPUT_FILE" 2>&1) || true
printf '%s plate-summary-stop repo=%s branch=%s out=%s\n' \
  "$(date -Iseconds)" "$REPO" "$BRANCH" "$OUT" >> "$LOG_FILE" 2>/dev/null || true

exit 0
