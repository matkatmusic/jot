#!/bin/bash
# scan-existing-todos.sh — atomically claim the next zero-padded 3-digit
# TODO ID for this invocation.
#
# Scans existing IDs from three sources:
#   - Todos/NNN_*.md           (open)
#   - Todos/done/NNN_*.md      (resolved)
#   - Todos/.todo-state/id-NNN.claim  (in-flight claims from concurrent workers)
#
# Then loops starting at max+1, attempting atomic creation of
# `id-NNN.claim` via `set -C` (noclobber). First successful create wins
# the ID. Workers delete their `.claim` sentinel after the actual NNN_*.md
# is written; failed runs leave cosmetic gaps (acceptable).
#
# Usage: scan-existing-todos.sh <repo_root>
# Output: claimed NNN on stdout (zero-padded).
set -uo pipefail

REPO_ROOT="${1:?repo_root required}"
TODOS="$REPO_ROOT/Todos"
DONE="$TODOS/done"
STATE_DIR="$TODOS/.todo-state"
mkdir -p "$STATE_DIR"

max=0
shopt -s nullglob
for f in "$TODOS"/[0-9][0-9][0-9]_*.md \
         "$DONE"/[0-9][0-9][0-9]_*.md \
         "$STATE_DIR"/id-[0-9][0-9][0-9].claim; do
  base=$(basename "$f")
  if [[ "$base" =~ ^([0-9]{3})_ ]]; then
    n="${BASH_REMATCH[1]}"
  elif [[ "$base" =~ ^id-([0-9]{3})\.claim$ ]]; then
    n="${BASH_REMATCH[1]}"
  else
    continue
  fi
  n=$((10#$n))
  [ "$n" -gt "$max" ] && max="$n"
done
shopt -u nullglob

next=$((max + 1))
while true; do
  padded=$(printf '%03d' "$next")
  sentinel="$STATE_DIR/id-${padded}.claim"
  if ( set -C; : > "$sentinel" ) 2>/dev/null; then
    printf 'pid=%s ts=%s\n' "$$" "$(date -Iseconds)" > "$sentinel" 2>/dev/null || true
    printf '%s\n' "$padded"
    exit 0
  fi
  next=$((next + 1))
  if [ "$next" -gt 999 ]; then
    echo "scan-existing-todos: exhausted 3-digit ID space" >&2
    exit 1
  fi
done
