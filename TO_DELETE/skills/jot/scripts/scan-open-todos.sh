#!/bin/bash
# scan-open-todos.sh — List open TODO files.
# Usage: bash scan-open-todos.sh [working-directory]
# Outputs one file path per line. Empty output if none found.

set -euo pipefail

TARGET_DIR="${1:-.}"
TODOS_DIR="$TARGET_DIR/Todos"

if [ ! -d "$TODOS_DIR" ]; then
    exit 0
fi

for f in "$TODOS_DIR"/*.md; do
    [ -f "$f" ] || continue
    # Check frontmatter for status: open (within first 10 lines)
    if head -10 "$f" | grep -q '^status: open' 2>/dev/null; then
        echo "$f"
    fi
done
