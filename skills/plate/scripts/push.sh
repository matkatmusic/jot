#!/usr/bin/env bash
# push.sh — Orchestrate a full /plate push.
# Args: $1=convo_id  $2=transcript_path  $3=cwd
# Side effects: creates snapshot ref, appends to instance JSON stack[],
#   launches background agent in tmux.
set -euo pipefail

# Derive paths from this script's own location so we don't trust
# CLAUDE_PLUGIN_ROOT — in multi-plugin sessions the foreground claude may
# have that env var set to a different (jot, superpowers, etc.) plugin.
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPTS_DIR/../../.." && pwd)"
PYTHON_DIR="$PLUGIN_ROOT/common/scripts/plate"
PROMPTS_DIR="$SCRIPTS_DIR/prompts"
# Export CLAUDE_PLUGIN_ROOT so child calls that still read it (legacy, or
# paths.sh logging) see the right value.
export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"
: "${CLAUDE_PLUGIN_DATA:=$HOME/.claude/plugins/data/plate-jot-dev}"
export CLAUDE_PLUGIN_DATA
mkdir -p "$CLAUDE_PLUGIN_DATA"

# shellcheck source=paths.sh
. "$SCRIPTS_DIR/paths.sh"
# shellcheck source=../../../common/scripts/lock.sh
. "${CLAUDE_PLUGIN_ROOT}/common/scripts/lock.sh"
# shellcheck source=../../../common/scripts/permissions-seed.sh
. "${CLAUDE_PLUGIN_ROOT}/common/scripts/permissions-seed.sh"
# shellcheck source=../../../common/scripts/platform.sh
. "${CLAUDE_PLUGIN_ROOT}/common/scripts/platform.sh"

CONVO_ID="${1:?}"
TRANSCRIPT_PATH="${2:-}"
CWD="${3:-$PWD}"

plate_discover_repo_root
plate_ensure_dirs

INSTANCE_FILE="${PLATE_ROOT}/instances/${CONVO_ID}.json"
TIMESTAMP=$(date -u +%Y-%m-%dT%H-%M-%SZ)
PLATE_ID="${TIMESTAMP}_$(basename "$CWD" | tr ' ' '-')"
HEAD_SHA=$(git rev-parse HEAD)
BRANCH=$(hide_errors git symbolic-ref --short HEAD) || BRANCH="detached"

# ── Reentrancy lock ──────────────────────────────────────────────────────
LOCK_DIR="${PLATE_ROOT}/.push.lock"
if ! lock_acquire "$LOCK_DIR" 5; then
  echo "[plate] push already in progress, skipping duplicate" >&2
  exit 0
fi
trap 'lock_release "$LOCK_DIR"' EXIT

# ── 1. Git snapshot (synchronous — must complete before agent starts) ─────
STASH_SHA=$(bash "$SCRIPTS_DIR/snapshot-stash.sh" "$CONVO_ID" "$PLATE_ID")

# ── 2. Compute files changed since previous plate (§7.1) ─────────────────
PREV_SHA="$HEAD_SHA"
PREV_PLATE=$(hide_errors python3 "$PYTHON_DIR/instance_rw.py" top "$INSTANCE_FILE") || PREV_PLATE="{}"
if [ "$PREV_PLATE" != "{}" ]; then
  PREV_SHA=$(printf '%s' "$PREV_PLATE" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("push_time_head_sha",""))')
  [ -z "$PREV_SHA" ] && PREV_SHA="$HEAD_SHA"
fi
FILES_CHANGED=$(hide_errors git diff --name-only "$PREV_SHA" HEAD) || FILES_CHANGED=""
FILES_UNCOMMITTED=$(hide_errors git diff --name-only HEAD) || FILES_UNCOMMITTED=""
ALL_FILES=$(printf '%s\n%s' "$FILES_CHANGED" "$FILES_UNCOMMITTED" | sort -u | grep -v '^$') || ALL_FILES=""

# ── 3. Append plate to instance JSON stack[] ──────────────────────────────
CONVO_ID="$CONVO_ID" CWD="$CWD" BRANCH="$BRANCH" PLATE_ID="$PLATE_ID" \
HEAD_SHA="$HEAD_SHA" STASH_SHA="$STASH_SHA" ALL_FILES="$ALL_FILES" \
INSTANCE_FILE="$INSTANCE_FILE" PYTHON_DIR="$PYTHON_DIR" \
python3 "$PYTHON_DIR/append_plate_to_stack.py"

# ── 4. Launch background agent for field extraction ───────────────────────
# Durable-first: write INPUT_FILE before spawning tmux window.
INPUT_FILE="${PLATE_ROOT}/inputs/${CONVO_ID}_${TIMESTAMP}.txt"

# Check if rolling intent needs refresh (§11)
NEEDS_REFRESH=$(INSTANCE_FILE="$INSTANCE_FILE" hide_errors python3 "$PYTHON_DIR/check_rolling_intent_refresh.py") || NEEDS_REFRESH="yes"

# Prepend bg-agent prompt before the JSON payload
if [ -f "$PROMPTS_DIR/bg-agent.md" ]; then
  cat "$PROMPTS_DIR/bg-agent.md" > "$INPUT_FILE"
  printf '\n\n## Job Payload\n\n```json\n' >> "$INPUT_FILE"
else
  : > "$INPUT_FILE"
fi

cat >> "$INPUT_FILE" <<PAYLOAD
{
  "convo_id": "$CONVO_ID",
  "plate_id": "$PLATE_ID",
  "instance_file": "$INSTANCE_FILE",
  "transcript_path": "$TRANSCRIPT_PATH",
  "plate_root": "$PLATE_ROOT",
  "cwd": "$CWD",
  "stash_sha": "$STASH_SHA",
  "head_sha": "$HEAD_SHA",
  "refresh_rolling_intent": $([ "$NEEDS_REFRESH" = "yes" ] && echo "true" || echo "false")
}
PAYLOAD

if [ -f "$PROMPTS_DIR/bg-agent.md" ]; then
  printf '```\n' >> "$INPUT_FILE"
fi

# ── Build per-invocation settings.json (jot pattern) ─────────────────────
TMPDIR_INV=$(mktemp -d /tmp/plate.XXXXXX)
SETTINGS_FILE="$TMPDIR_INV/settings.json"
# Sanitize for tmux target syntax: tmux parses '.' as window.pane separator
# and ':' as session:window, so strip both from the window name.
RAW_WINDOW="$(basename "$CWD")-${TIMESTAMP}"
WINDOW_NAME="${RAW_WINDOW//./-}"
WINDOW_NAME="${WINDOW_NAME//:/-}"
TMUX_TARGET="plate:$WINDOW_NAME"

# Record the tmux target so plate-worker-end.sh can find it if needed
printf '%s\n' "$TMUX_TARGET" > "$TMPDIR_INV/tmux_target"

# Copy lifecycle scripts to tmpdir (survives plugin update during run)
cp "$SCRIPTS_DIR/plate-worker-start.sh" "$TMPDIR_INV/"
cp "$SCRIPTS_DIR/plate-worker-stop.sh"  "$TMPDIR_INV/"
cp "$SCRIPTS_DIR/plate-worker-end.sh"   "$TMPDIR_INV/"

# ── Seed installed permissions file (three-state) ────────────────────────
PERM_INSTALLED="${CLAUDE_PLUGIN_DATA}/permissions.local.json"
PERM_DEFAULT="${CLAUDE_PLUGIN_ROOT}/skills/plate/scripts/assets/permissions.default.json"
PERM_DEFAULT_SHA="${PERM_DEFAULT}.sha256"
PERM_PRIOR_SHA="${CLAUDE_PLUGIN_DATA}/permissions.default.sha256"
permissions_seed "$PERM_INSTALLED" "$PERM_DEFAULT" "$PERM_DEFAULT_SHA" "$PERM_PRIOR_SHA" "${LOG_FILE:-/dev/null}" "plate"

# Expand ${PLATE_ROOT} / ${HOME} placeholders in the installed template
# into a per-invocation settings.json. Python handles JSON merge + lstrip
# for `//` anchors so double-slashes do not degenerate into ``.
PERM_INSTALLED="$PERM_INSTALLED" SETTINGS_FILE="$SETTINGS_FILE" \
PLATE_ROOT="$PLATE_ROOT" TRANSCRIPT_PATH="$TRANSCRIPT_PATH" \
TMPDIR_INV="$TMPDIR_INV" INPUT_FILE="$INPUT_FILE" TMUX_TARGET="$TMUX_TARGET" \
python3 "$PYTHON_DIR/build_settings_json.py"

CLAUDE_CMD="claude --settings '$SETTINGS_FILE' --add-dir '$CWD'"

# ── Global tmux-launch lock (prevents session-creation race) ──────────────
# Boundary: everything ABOVE this line must stay fatal — it writes durable
# state (stash ref, stack JSON, INPUT_FILE, settings.json, permissions seed).
# Everything BELOW is cosmetic (tmux session + optional Terminal.app). In
# headless envs (CI, tests with no terminal) the tmux step can fail with no
# way to attach; we don't want that to silently corrupt the user-visible
# "[plate] pushed" contract when the durable work succeeded.

TMUX_LOCK="${CLAUDE_PLUGIN_DATA}/tmux-launch.lock"
mkdir -p "${CLAUDE_PLUGIN_DATA}"
if ! lock_acquire "$TMUX_LOCK" 10; then
  echo "[plate] failed to acquire tmux-launch lock" >&2
  exit 1
fi
# Guarantee both lock releases even if tmux calls abort mid-launch. Replaces
# (and subsumes) the earlier LOCK_DIR-only trap at line ~50 — bash traps for
# the same signal overwrite, not stack, so this single trap must cover both
# the reentrancy lock ($LOCK_DIR) and the tmux-launch lock ($TMUX_LOCK).
# Prevents the stale-lock class of bugs that plate-e2e-live.sh previously
# scrubbed manually via rmdir at test-fixture setup.
trap 'hide_errors lock_release "$TMUX_LOCK"; lock_release "$LOCK_DIR"' EXIT

launch_rc=0
if ! tmux_has_session "plate"; then
  tmux new-session -d -s plate -n "$WINDOW_NAME" -c "$CWD" "$CLAUDE_CMD" || launch_rc=$?
  if [ "$launch_rc" -eq 0 ]; then
    hide_output hide_errors tmux set-option -t '=plate' remain-on-exit off || launch_rc=$?
  fi
else
  tmux new-window -t '=plate:' -n "$WINDOW_NAME" -c "$CWD" "$CLAUDE_CMD" || launch_rc=$?
fi

if [ "$launch_rc" -ne 0 ]; then
  echo "[plate] warning: durable state saved, tmux launch failed rc=$launch_rc" >&2
  # Durable writes above completed; plate.sh's "[plate] pushed" emit is
  # legitimate. Exit 0 so the orchestrator's ERR trap doesn't fire.
  exit 0
fi

# Terminal attach is pure cosmetic on macOS — never fatal.
if ! spawn_terminal_if_needed "plate" "${PLATE_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/plate-log.txt}" "plate"; then
  echo "[plate] warning: terminal attach failed rc=$?" >&2
fi
