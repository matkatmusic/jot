#!/bin/bash
# debate-orchestrator.sh — UserPromptSubmit hook entry point for /debate.
# Sources debate.sh (function definitions), calls debate_main.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPTS_DIR/../../.." && pwd)"

. "$PLUGIN_ROOT/common/scripts/silencers.sh"

# Ensure Terminal.app is running as a process so spawn_terminal_if_needed's
# `do script` can land in a single tmux-attach window. `launch` (not
# `activate`) starts Terminal without opening a default shell window —
# avoiding a duplicate empty window beside the real one. Darwin-only; no-op
# if Terminal is already running.
if [[ "${OSTYPE:-}" == darwin* ]] && ! hide_errors pgrep -q Terminal; then
  hide_output hide_errors osascript -e 'tell application "Terminal" to launch' &
fi

# shellcheck source=debate.sh
. "$SCRIPTS_DIR/debate.sh"

debate_main
