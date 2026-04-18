#!/usr/bin/env bash
# render-tree.sh — Build tree.md from all instance JSONs + project.json (§13).
# No side effects beyond writing tree.md. Safe to call from anywhere.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_DIR="$(cd "$SCRIPTS_DIR/../../python/plate" && pwd)"
# shellcheck source=paths.sh
. "$SCRIPTS_DIR/paths.sh"
plate_discover_repo_root

python3 "$PYTHON_DIR/render_tree.py" "$PLATE_ROOT"
