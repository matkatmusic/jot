#!/usr/bin/env bash
# render-tree.sh — Build tree.md from all instance JSONs + project.json (§13).
# No side effects beyond writing tree.md. Safe to call from anywhere.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_DIR="${CLAUDE_PLUGIN_ROOT}/python"
# shellcheck source=lib/paths.sh
. "$SCRIPTS_DIR/lib/paths.sh"
plate_discover_root

python3 "$PYTHON_DIR/render_tree.py" "$PLATE_ROOT"
