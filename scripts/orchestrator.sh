#!/bin/bash
# orchestrator.sh — UserPromptSubmit dispatcher. Reads hook JSON from stdin,
# inspects .prompt, and delegates to the /jot or /plate sub-orchestrator.
# Unknown prompts pass through silently (exit 0).
set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

. "$PLUGIN_ROOT/common/scripts/silencers.sh"

INPUT=$(cat)
PROMPT=$(printf '%s' "$INPUT" | hide_errors jq -r '.prompt // ""')

# Strip leading whitespace so "  /jot foo" still dispatches.
PROMPT="${PROMPT#"${PROMPT%%[![:space:]]*}"}"

case "$PROMPT" in
  "/jot"|"/jot "*|$'/jot\n'*)
    printf '%s' "$INPUT" | bash "$PLUGIN_ROOT/skills/jot/scripts/jot-orchestrator.sh"
    ;;
  "/plate"|"/plate "*|$'/plate\n'*)
    printf '%s' "$INPUT" | bash "$PLUGIN_ROOT/skills/plate/scripts/plate-orchestrator.sh"
    ;;
  *)
    exit 0
    ;;
esac
