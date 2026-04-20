#!/usr/bin/env bash
# list-paused-plates.sh — Emit one row per paused plate across all instances.
# Output format: <convoID>|<plate_id>|<label>|<summary_action>|<pushed_at>
# Used by SKILL.md to build the AskUserQuestion dropdown.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../../../common/scripts/silencers.sh
. "${CLAUDE_PLUGIN_ROOT}/common/scripts/silencers.sh"
# shellcheck source=paths.sh
. "$SCRIPTS_DIR/paths.sh"
plate_discover_repo_root

PYTHON_DIR="$(cd "$SCRIPTS_DIR/../../../common/scripts/plate" && pwd)"

shopt -s nullglob
for f in "$PLATE_ROOT"/instances/*.json; do
  hide_errors INSTANCE_FILE="$f" python3 "$PYTHON_DIR/list_paused_plates.py"
done
shopt -u nullglob
