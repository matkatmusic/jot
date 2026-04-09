#!/bin/bash
# Outputs current git branch name. Bash 3.2 compatible.
set -euo pipefail
TARGET_DIR="${1:-.}"
if ! git -C "$TARGET_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Not a git repository"; exit 0
fi
branch=$(git -C "$TARGET_DIR" branch --show-current 2>/dev/null)
if [ -z "$branch" ]; then
    branch="HEAD detached at $(git -C "$TARGET_DIR" rev-parse --short HEAD 2>/dev/null)"
fi
echo "$branch"
