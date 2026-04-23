#!/bin/bash
# debate-abort-orchestrator.sh — UserPromptSubmit hook entry for /debate-abort.
# Sources debate.sh (shared init + helpers + functions), calls debate_abort_main.
set -euo pipefail
DEBATE_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../debate/scripts" && pwd)"
# shellcheck source=../../debate/scripts/debate.sh
. "$DEBATE_SCRIPTS_DIR/debate.sh"
debate_abort_main
