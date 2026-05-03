#!/usr/bin/env bash
# scan-open-todos.sh - delegates to common/scripts/todo/scan_open_todos_cli.py.
# Different spec from the jot-side scan-open-todos.sh: this one lists every
# Todos/*.md file (no status filter), printing "(none)" when empty/missing.
# File kept executable so the existing caller (todo-launcher.sh) works
# unmodified; remove once that caller is itself migrated.
exec python3 \
  "$(dirname "${BASH_SOURCE[0]}")/../../../common/scripts/todo/scan_open_todos_cli.py" \
  "$@"
