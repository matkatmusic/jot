#!/usr/bin/env bash
# register-parent.sh — Register parent-child relationship.
# Args: $1=child_convo_id  $2=parent_convo_id  $3=parent_plate_id
#   If $2 is "none", register as top-level.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
# Derive python dir from SCRIPTS_DIR so we don't depend on CLAUDE_PLUGIN_ROOT
# being set correctly (it may point at a sibling plugin in multi-plugin sessions).
PYTHON_DIR="$(cd "$SCRIPTS_DIR/../python" && pwd)"
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
python3 <<'PY'
import os, sys
sys.path.insert(0, os.environ['PYTHON_DIR'])
from instance_rw import load, atomic_write
from pathlib import Path

# Set child's parent_ref
child_path = Path(os.environ['CHILD_FILE'])
child = load(child_path)
child['parent_ref'] = {
    'convo_id': os.environ['PARENT_CONVO'],
    'plate_id': os.environ['PARENT_PLATE'],
}
atomic_write(child_path, child)

# Add child to parent's delegated_to[] and flip state
parent_path = Path(os.environ['PARENT_FILE'])
parent = load(parent_path)
child_id = os.environ['CHILD_CONVO']
parent_plate = os.environ['PARENT_PLATE']
for plate in parent.get('stack', []):
    if plate['plate_id'] == parent_plate:
        if child_id not in plate.get('delegated_to', []):
            plate.setdefault('delegated_to', []).append(child_id)
        plate['state'] = 'delegated'
        break
atomic_write(parent_path, parent)
PY
