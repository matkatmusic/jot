#!/usr/bin/env bash
# plate-session-start.sh — Global SessionStart hook for resume freshness.
# Runs on every `claude --resume <convoID>`. NOT the per-worker SessionStart.
set -uo pipefail

: "${CLAUDE_PLUGIN_ROOT:?}"
SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/scripts"
PYTHON_DIR="${CLAUDE_PLUGIN_ROOT}/python"

# shellcheck source=../../../scripts/lib/invoke_command.sh
. "${CLAUDE_PLUGIN_ROOT}/scripts/lib/invoke_command.sh"
# shellcheck source=paths.sh
. "$SCRIPTS_DIR/paths.sh"
hide_errors plate_discover_repo_root || exit 0

# Determine session ID from hook input
INPUT=$(cat)
SESSION_ID=$(printf '%s' "$INPUT" | hide_errors python3 -c 'import json,sys; print(json.load(sys.stdin).get("session_id",""))') || SESSION_ID=""
[ -z "$SESSION_ID" ] && exit 0

INSTANCE_FILE="${PLATE_ROOT}/instances/${SESSION_ID}.json"
[ -f "$INSTANCE_FILE" ] || exit 0

# ── Verify stash refs are alive ───────────────────────────────────────────
INSTANCE_FILE="$INSTANCE_FILE" SESSION_ID="$SESSION_ID" hide_errors python3 <<'PY'
import json, os, subprocess, sys
d = json.load(open(os.environ['INSTANCE_FILE']))
session_id = os.environ['SESSION_ID']
warnings = []
for plate in d.get('stack', []):
    ref = f"refs/plates/{session_id}/{plate['plate_id']}"
    result = subprocess.run(['git', 'cat-file', '-t', ref], capture_output=True, text=True)
    if result.returncode != 0:
        warnings.append(f"  stash ref {ref} missing (may have been GC'd)")
    head = plate.get('push_time_head_sha', '')
    if head:
        result2 = subprocess.run(['git', 'merge-base', '--is-ancestor', head, 'HEAD'], capture_output=True)
        if result2.returncode != 0:
            warnings.append(f"  push_time_head_sha {head[:8]} not reachable from HEAD (branch rewritten?)")
if warnings:
    print('plate freshness warnings:', file=sys.stderr)
    for w in warnings:
        print(w, file=sys.stderr)
PY

# ── Update last_touched ──────────────────────────────────────────────────
hide_errors python3 "$PYTHON_DIR/instance_rw.py" touch "$INSTANCE_FILE"

# ── Clear stale drift alerts ─────────────────────────────────────────────
hide_errors INSTANCE_FILE="$INSTANCE_FILE" PYTHON_DIR="$PYTHON_DIR" python3 <<'PY'
import os, sys
sys.path.insert(0, os.environ['PYTHON_DIR'])
from instance_rw import mutate
from pathlib import Path
def _clear(d):
    d.setdefault('drift_alert', {})['pending'] = False
mutate(Path(os.environ['INSTANCE_FILE']), _clear)
PY

# ── Re-render tree.md ─────────────────────────────────────────────────────
hide_errors bash "$SCRIPTS_DIR/render-tree.sh"

exit 0
