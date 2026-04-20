#!/usr/bin/env bash
# register-parent.sh — Register parent-child relationship.
# Args: $1=child_convo_id  $2=parent_convo_id  $3=parent_plate_id
#   If $2 is "none", register as top-level.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
# Derive python dir from SCRIPTS_DIR so we don't depend on CLAUDE_PLUGIN_ROOT
# being set correctly (it may point at a sibling plugin in multi-plugin sessions).
PYTHON_DIR="$(cd "$SCRIPTS_DIR/../../../common/scripts/plate" && pwd)"
# shellcheck source=paths.sh
. "$SCRIPTS_DIR/paths.sh"
plate_discover_repo_root

CHILD_CONVO="${1:?}"
PARENT_CONVO="${2:?}"
PARENT_PLATE="${3:-}"

CHILD_FILE="${PLATE_ROOT}/instances/${CHILD_CONVO}.json"

if [ "$PARENT_CONVO" = "none" ]; then
  # Top-level: parent_ref stays null (already default)
  exit 0
fi

PARENT_FILE="${PLATE_ROOT}/instances/${PARENT_CONVO}.json"

CHILD_FILE="$CHILD_FILE" PARENT_FILE="$PARENT_FILE" \
CHILD_CONVO="$CHILD_CONVO" PARENT_CONVO="$PARENT_CONVO" \
PARENT_PLATE="$PARENT_PLATE" PYTHON_DIR="$PYTHON_DIR" \
python3 "$PYTHON_DIR/register_parent.py"
