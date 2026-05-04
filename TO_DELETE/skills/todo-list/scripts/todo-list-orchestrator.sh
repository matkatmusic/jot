#!/bin/bash
# todo-list-orchestrator.sh — UserPromptSubmit hook entry point for /todo-list.
# Sources todo-list.sh (function definitions), calls todo_list_main.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=todo-list.sh
. "$SCRIPTS_DIR/todo-list.sh"

todo_list_main
