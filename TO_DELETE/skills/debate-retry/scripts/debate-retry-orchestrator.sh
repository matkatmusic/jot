#!/bin/bash
# debate-retry-orchestrator.sh — UserPromptSubmit hook entry for /debate-retry.
# Sources debate.sh (shared init + helpers + functions), calls debate_retry_main.
set -euo pipefail
DEBATE_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../debate/scripts" && pwd)"
# shellcheck source=../../debate/scripts/debate.sh
. "$DEBATE_SCRIPTS_DIR/debate.sh"
debate_retry_main
