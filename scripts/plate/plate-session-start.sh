#!/usr/bin/env bash
# plate-session-start.sh — Global SessionStart hook for resume freshness.
# Runs on every `claude --resume <convoID>`. NOT the per-worker SessionStart.
set -uo pipefail

: "${CLAUDE_PLUGIN_ROOT:?}"
SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/scripts/plate"
PYTHON_DIR="${CLAUDE_PLUGIN_ROOT}/python/plate"

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
INSTANCE_FILE="$INSTANCE_FILE" SESSION_ID="$SESSION_ID" hide_errors python3 "$PYTHON_DIR/verify_stash_refs.py"

# ── Update last_touched ──────────────────────────────────────────────────
hide_errors python3 "$PYTHON_DIR/instance_rw.py" touch "$INSTANCE_FILE"

# ── Clear stale drift alerts ─────────────────────────────────────────────
hide_errors INSTANCE_FILE="$INSTANCE_FILE" PYTHON_DIR="$PYTHON_DIR" python3 "$PYTHON_DIR/clear_drift_alert.py"

# ── Re-render tree.md ─────────────────────────────────────────────────────
hide_errors bash "$SCRIPTS_DIR/render-tree.sh"

exit 0
