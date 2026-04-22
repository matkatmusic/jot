#!/bin/bash
# orchestrator.sh — UserPromptSubmit dispatcher. Reads hook JSON from stdin,
# inspects .prompt, and delegates to the /jot or /plate sub-orchestrator.
# Unknown prompts pass through silently (exit 0).
set -eEuo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

. "$PLUGIN_ROOT/common/scripts/silencers.sh"

INPUT=$(cat)
PROMPT=$(printf '%s' "$INPUT" | hide_errors jq -r '.prompt // ""')

# Strip leading whitespace so "  /jot foo" still dispatches.
PROMPT="${PROMPT#"${PROMPT%%[![:space:]]*}"}"

# Claude Code namespaces plugin skills as "/<plugin>:<skill>" when
# disambiguation is needed. Normalise "/jot:todo-list" → "/todo-list" so the
# case branches below don't have to enumerate both forms. We rewrite both the
# local $PROMPT (for the case match) and the forwarded JSON's .prompt field
# (so sub-orchestrators see the same normalised form).
case "$PROMPT" in
  /jot:*)
    PROMPT="/${PROMPT#/jot:}"
    INPUT=$(printf '%s' "$INPUT" | hide_errors jq --arg p "$PROMPT" '.prompt = $p')
    ;;
esac

case "$PROMPT" in
  "/jot"|"/jot "*|$'/jot\n'*)
    printf '%s' "$INPUT" | bash "$PLUGIN_ROOT/skills/jot/scripts/jot-orchestrator.sh"
    ;;
  "/plate"|"/plate "*|$'/plate\n'*)
    printf '%s' "$INPUT" | bash "$PLUGIN_ROOT/skills/plate/scripts/plate-orchestrator.sh"
    ;;
  "/debate"|"/debate "*|$'/debate\n'*)
    printf '%s' "$INPUT" | bash "$PLUGIN_ROOT/skills/debate/scripts/debate-orchestrator.sh"
    ;;
  "/todo"|"/todo "*|$'/todo\n'*)
    printf '%s' "$INPUT" | bash "$PLUGIN_ROOT/skills/todo/scripts/todo-orchestrator.sh"
    ;;
  "/todo-list"|"/todo-list "*|$'/todo-list\n'*)
    printf '%s' "$INPUT" | bash "$PLUGIN_ROOT/skills/todo-list/scripts/todo-list-orchestrator.sh"
    ;;
  *)
    exit 0
    ;;
esac
