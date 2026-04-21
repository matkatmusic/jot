#!/bin/bash
# debate-session-start.sh — SessionStart hook for debate claude agents.
# Reads transcript_path from hook JSON, writes to sidecar file.
# The sidecar path comes from DEBATE_TRANSCRIPT_SIDECAR env var
# (set by spawn_agent_panes in debate-tmux-orchestrator.sh).
set -uo pipefail
INPUT=$(cat)
SIDECAR="${DEBATE_TRANSCRIPT_SIDECAR:-}"
[ -z "$SIDECAR" ] && exit 0
TRANSCRIPT=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
[ -n "$TRANSCRIPT" ] && printf '%s\n' "$TRANSCRIPT" > "$SIDECAR"
exit 0
