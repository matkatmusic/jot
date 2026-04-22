#!/bin/bash
# debate-orchestrator.sh — UserPromptSubmit hook entry point for /debate.
# Sources debate.sh (function definitions), calls debate_main.
set -eEuo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=debate.sh
. "$SCRIPTS_DIR/debate.sh"

debate_main
