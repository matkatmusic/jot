#!/bin/bash
# todo-orchestrator.sh — UserPromptSubmit hook entry point for /todo.
# Sources todo.sh (function definitions), calls todo_main.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=todo.sh
. "$SCRIPTS_DIR/todo.sh"

todo_main
