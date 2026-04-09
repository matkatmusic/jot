#!/bin/bash
# Outputs filenames with uncommitted changes, space-separated. Bash 3.2 compatible.
set -euo pipefail
TARGET_DIR="${1:-.}"
if ! git -C "$TARGET_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Not a git repository"; exit 0
fi
uncommitted=$(git -C "$TARGET_DIR" status --short 2>/dev/null | awk '{print $2}' | tr '\n' ' ' | sed 's/ $//')
if [ -z "$uncommitted" ]; then
    uncommitted="None"
fi
echo "$uncommitted"
