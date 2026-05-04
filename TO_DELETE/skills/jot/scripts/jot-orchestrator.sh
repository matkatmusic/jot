#!/bin/bash
# jot-orchestrator.sh — UserPromptSubmit hook entry point for /jot.
# Sources jot.sh (function definitions), calls jot_main.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=jot.sh
. "$SCRIPTS_DIR/jot.sh"

jot_main
