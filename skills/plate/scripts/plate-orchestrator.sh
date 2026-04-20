#!/bin/bash
# plate-orchestrator.sh — UserPromptSubmit hook entry point for /plate.
# Sources plate.sh (function definitions), calls plate_main.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=plate.sh
. "$SCRIPTS_DIR/plate.sh"

plate_main
