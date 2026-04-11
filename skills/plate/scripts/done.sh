#!/usr/bin/env bash
# done.sh — /plate --done: replay stack[] as sequential commits (§7.3).
# Args: $1=convo_id
# Stdout: ancestor chain + resume command for user
set -euo pipefail

: "${CLAUDE_PLUGIN_ROOT:?}"
SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/scripts"
PYTHON_DIR="${CLAUDE_PLUGIN_ROOT}/python"

# shellcheck source=lib/paths.sh
. "$SCRIPTS_DIR/lib/paths.sh"
plate_discover_root

CONVO_ID="${1:?usage: done.sh <convo_id>}"
INSTANCE_FILE="${PLATE_ROOT}/instances/${CONVO_ID}.json"

# ── Preflight checks ─────────────────────────────────────────────────────
if [ ! -f "$INSTANCE_FILE" ]; then
  echo "Error: no plate state for session $CONVO_ID" >&2
  exit 1
fi

STACK_COUNT=$(INSTANCE_FILE="$INSTANCE_FILE" python3 -c 'import json,os; d=json.load(open(os.environ["INSTANCE_FILE"])); print(len(d.get("stack",[])))')
if [ "$STACK_COUNT" -eq 0 ]; then
  echo "Error: no plates on the stack to commit." >&2
  exit 1
fi

# ── Check for open delegated children (§9.3) ─────────────────────────────
HAS_LIVE_CHILDREN=$(INSTANCE_FILE="$INSTANCE_FILE" python3 <<'PY'
import json, os
d = json.load(open(os.environ['INSTANCE_FILE']))
live = any(p.get('delegated_to') for p in d.get('stack', []) if p.get('state') == 'delegated')
print('yes' if live else 'no')
PY
)
if [ "$HAS_LIVE_CHILDREN" = "yes" ]; then
  # The skill body (foreground claude) handles AskUserQuestion for this.
  # done.sh only runs after the user has chosen to proceed.
  echo "WARNING: delegated children still open. Proceeding per user choice." >&2
fi

# ── Replay loop: oldest first ─────────────────────────────────────────────
COMMIT_SHAS=()
LAST_REF=""

while IFS= read -r plate_json; do
  [ -z "$plate_json" ] && continue

  PLATE_ID=$(printf '%s' "$plate_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["plate_id"])')
  STASH_SHA=$(printf '%s' "$plate_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["stash_sha"])')
  HEAD_SHA=$(printf '%s' "$plate_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["push_time_head_sha"])')

  # Base for diff: previous plate's stash, or first plate's HEAD at push time
  if [ -z "$LAST_REF" ]; then
    BASE="$HEAD_SHA"
  else
    BASE="$LAST_REF"
  fi

  # Apply the diff for this plate
  DIFF=$(git diff --binary "$BASE" "$STASH_SHA" 2>/dev/null || true)
  if [ -n "$DIFF" ]; then
    printf '%s' "$DIFF" | git apply --index --3way - 2>/dev/null || {
      echo "Warning: conflict applying plate $PLATE_ID, attempting manual resolve" >&2
      printf '%s' "$DIFF" | git apply --index --3way - || true
    }
  fi

  # Commit with structured message
  COMMIT_MSG=$(printf '%s' "$plate_json" | python3 "$PYTHON_DIR/commit_message.py")
  git commit --allow-empty -m "$COMMIT_MSG"
  COMMIT_SHA=$(git rev-parse HEAD)
  COMMIT_SHAS+=("$COMMIT_SHA")

  # Mark plate completed in instance JSON
  COMPLETED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  python3 "$PYTHON_DIR/instance_rw.py" complete "$INSTANCE_FILE" "$PLATE_ID" "$COMMIT_SHA" "$COMPLETED_AT"

  # Delete the named ref
  git update-ref -d "refs/plates/${CONVO_ID}/${PLATE_ID}" 2>/dev/null || true

  LAST_REF="$STASH_SHA"

done < <(python3 "$PYTHON_DIR/instance_rw.py" stack-oldest "$INSTANCE_FILE")

# ── Final commit: capture any work done after the last plate (§7.3 step 4)
if ! git diff --quiet HEAD 2>/dev/null || ! git diff --cached --quiet HEAD 2>/dev/null; then
  git add -A
  git commit -m "[plate] final: work after last plate push"
  COMMIT_SHAS+=("$(git rev-parse HEAD)")
fi

# ── Cascade up through parent chain (§9.2) ────────────────────────────────
MAX_DEPTH=20
INSTANCE_FILE="$INSTANCE_FILE" PLATE_ROOT="$PLATE_ROOT" \
CONVO_ID="$CONVO_ID" PYTHON_DIR="$PYTHON_DIR" MAX_DEPTH="$MAX_DEPTH" \
python3 <<'PY'
import os, sys
sys.path.insert(0, os.environ['PYTHON_DIR'])
from instance_rw import load, atomic_write
from pathlib import Path

instance_file = Path(os.environ['INSTANCE_FILE'])
data = load(instance_file)
parent_ref = data.get('parent_ref', {})
max_depth = int(os.environ['MAX_DEPTH'])
convo_id = os.environ['CONVO_ID']
plate_root = Path(os.environ['PLATE_ROOT'])
depth = 0

while parent_ref and parent_ref.get('convo_id') and depth < max_depth:
    parent_convo = parent_ref['convo_id']
    parent_plate_id = parent_ref.get('plate_id', '')
    parent_path = plate_root / 'instances' / f'{parent_convo}.json'
    if not parent_path.exists():
        break
    parent_data = load(parent_path)
    for plate in parent_data.get('stack', []):
        if plate['plate_id'] == parent_plate_id:
            dt = plate.get('delegated_to', [])
            if convo_id in dt:
                dt.remove(convo_id)
            if not dt:
                plate['state'] = 'paused'
            break
    atomic_write(parent_path, parent_data)
    # Stop at first ancestor (§9.2 step 3)
    break
PY

# ── Print result ──────────────────────────────────────────────────────────
BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "detached")
echo "Committed ${#COMMIT_SHAS[@]} plates in ${CONVO_ID} -> ${BRANCH} (${COMMIT_SHAS[*]})"

# Print resume pointer if parent exists
INSTANCE_FILE="$INSTANCE_FILE" PLATE_ROOT="$PLATE_ROOT" python3 <<'PY' 2>/dev/null || true
import json, os
from pathlib import Path
d = json.load(open(os.environ['INSTANCE_FILE']))
pr = d.get('parent_ref', {})
if pr.get('convo_id'):
    parent_path = Path(os.environ['PLATE_ROOT']) / 'instances' / f'{pr["convo_id"]}.json'
    if parent_path.exists():
        pd = json.load(open(parent_path))
        cwd = pd.get('cwd', '.')
        print(f'\nTo resume parent, run:\n  cd {cwd} && claude --resume {pr["convo_id"]}')
PY
