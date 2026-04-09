#!/bin/bash
# Outputs last 5 commit short hashes, space-separated. Bash 3.2 compatible.
set -euo pipefail
TARGET_DIR="${1:-.}"
if ! git -C "$TARGET_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Not a git repository"; exit 0
fi
commits=$(git -C "$TARGET_DIR" log --oneline -5 --format='%h' 2>/dev/null | tr '\n' ' ' | sed 's/ $//')
if [ -z "$commits" ]; then
    commits="None (no commits yet)"
fi
echo "$commits"
