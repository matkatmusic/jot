#!/bin/bash
# scan-open-todos.sh — print absolute paths of all open TODO .md files in
# the given repo's Todos/ directory (excluding Todos/done/).
# Usage: scan-open-todos.sh <repo_root>
set -uo pipefail

REPO_ROOT="${1:?repo_root required}"
TODOS="$REPO_ROOT/Todos"

[ -d "$TODOS" ] || { echo "(none)"; exit 0; }

shopt -s nullglob
found=0
for f in "$TODOS"/*.md; do
  printf '%s\n' "$f"
  found=1
done
shopt -u nullglob

[ "$found" -eq 0 ] && echo "(none)"
exit 0
