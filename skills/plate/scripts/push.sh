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
PLUGIN_ROOT="$(cd "$SCRIPTS_DIR/.." && pwd)"
PYTHON_DIR="$PLUGIN_ROOT/python"
PROMPTS_DIR="$PLUGIN_ROOT/prompts"
# Export CLAUDE_PLUGIN_ROOT so child calls that still read it (legacy, or
# paths.sh logging) see the right value.
export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"
: "${CLAUDE_PLUGIN_DATA:=$HOME/.claude/plugins/data/plate-jot-dev}"
export CLAUDE_PLUGIN_DATA
mkdir -p "$CLAUDE_PLUGIN_DATA"

# shellcheck source=paths.sh
. "$SCRIPTS_DIR/paths.sh"
# shellcheck source=../../../scripts/lib/lock.sh
. "${CLAUDE_PLUGIN_ROOT}/scripts/lib/lock.sh"
# shellcheck source=../../../scripts/lib/permissions-seed.sh
. "${CLAUDE_PLUGIN_ROOT}/scripts/lib/permissions-seed.sh"
# shellcheck source=../../../scripts/lib/platform.sh
. "${CLAUDE_PLUGIN_ROOT}/scripts/lib/platform.sh"

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
python3 <<'PY'
import json, os, sys
sys.path.insert(0, os.environ['PYTHON_DIR'])
from instance_rw import load, atomic_write, new_instance, new_plate
from pathlib import Path
from datetime import datetime, timezone

path = Path(os.environ['INSTANCE_FILE'])
data = load(path)
if not data:
    data = new_instance(os.environ['CONVO_ID'], os.environ['CWD'], os.environ['BRANCH'])

plate = new_plate(
    os.environ['PLATE_ID'],
    os.environ['HEAD_SHA'],
    os.environ['STASH_SHA'],
    os.environ['BRANCH'],
)
plate['files'] = [f for f in os.environ.get('ALL_FILES', '').strip().split('\n') if f]
data.setdefault('stack', []).append(plate)
data['last_touched'] = datetime.now(timezone.utc).isoformat()
data['cwd'] = os.environ['CWD']

atomic_write(path, data)
PY

# ── 4. Launch background agent for field extraction ───────────────────────
# Durable-first: write INPUT_FILE before spawning tmux window.
INPUT_FILE="${PLATE_ROOT}/inputs/${CONVO_ID}_${TIMESTAMP}.txt"

# Check if rolling intent needs refresh (§11)
NEEDS_REFRESH=$(INSTANCE_FILE="$INSTANCE_FILE" hide_errors python3 <<'PY') || NEEDS_REFRESH="yes"
import json, os
from datetime import datetime, timezone, timedelta
try:
    d = json.load(open(os.environ['INSTANCE_FILE']))
except Exception:
    print('yes'); raise SystemExit
ri = d.get('rolling_intent', {}) or {}
snap = ri.get('snapshot_at')
if not snap:
    print('yes')
else:
    try:
        snap_dt = datetime.fromisoformat(snap.replace('Z', '+00:00'))
        if datetime.now(timezone.utc) - snap_dt > timedelta(minutes=5):
            print('yes')
        else:
            print('no')
    except Exception:
        print('yes')
PY
)

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
PERM_DEFAULT="${CLAUDE_PLUGIN_ROOT}/assets/permissions.default.json"
PERM_DEFAULT_SHA="${PERM_DEFAULT}.sha256"
PERM_PRIOR_SHA="${CLAUDE_PLUGIN_DATA}/permissions.default.sha256"
permissions_seed "$PERM_INSTALLED" "$PERM_DEFAULT" "$PERM_DEFAULT_SHA" "$PERM_PRIOR_SHA" "${LOG_FILE:-/dev/null}" "plate"

# Expand ${PLATE_ROOT} / ${HOME} placeholders in the installed template
# into a per-invocation settings.json. Python handles JSON merge + lstrip
# for `//` anchors so double-slashes do not degenerate into ``.
PERM_INSTALLED="$PERM_INSTALLED" SETTINGS_FILE="$SETTINGS_FILE" \
PLATE_ROOT="$PLATE_ROOT" TRANSCRIPT_PATH="$TRANSCRIPT_PATH" \
TMPDIR_INV="$TMPDIR_INV" INPUT_FILE="$INPUT_FILE" TMUX_TARGET="$TMUX_TARGET" \
python3 <<'PY'
import json, os
from pathlib import Path

perm_src = Path(os.environ['PERM_INSTALLED'])
out = Path(os.environ['SETTINGS_FILE'])
plate_root = os.environ['PLATE_ROOT']
transcript = os.environ.get('TRANSCRIPT_PATH', '') or ''
tmpdir = os.environ['TMPDIR_INV']
input_file = os.environ['INPUT_FILE']
tmux_target = os.environ['TMUX_TARGET']

# Load template (user-editable or freshly-seeded default)
template = json.loads(perm_src.read_text(encoding='utf-8')) if perm_src.exists() else {}
perms = template.get('permissions', {}) or {}

def expand(s: str) -> str:
    # Substitute placeholders. lstrip leading '/' on PLATE_ROOT so that
    # '//${PLATE_ROOT}/**' -> '//<absolute-path>/**' without collapsing to '/'.
    return (s
            .replace('${PLATE_ROOT}', plate_root.lstrip('/'))
            .replace('${HOME}', os.environ.get('HOME','')))

def expand_list(xs):
    return [expand(x) for x in xs or []]

allow = expand_list(perms.get('allow'))
deny  = expand_list(perms.get('deny'))

# Always add the transcript read rule so bg-agent can actually read the
# conversation. Transcripts are under ~/.claude/projects/<hash>/...
if transcript:
    allow.append(f'Read({transcript})')

settings = {
    'permissions': {
        'allow': allow,
        **({'deny': deny} if deny else {}),
    },
    'hooks': {
        'SessionStart': [{'hooks': [{'type':'command','command': f"bash {tmpdir}/plate-worker-start.sh '{input_file}' '{tmux_target}'"}]}],
        'Stop':         [{'hooks': [{'type':'command','command': f"bash {tmpdir}/plate-worker-stop.sh '{input_file}' '{tmux_target}'"}]}],
        'SessionEnd':   [{'hooks': [{'type':'command','command': f"bash {tmpdir}/plate-worker-end.sh '{tmpdir}'"}]}],
    },
}
out.write_text(json.dumps(settings, indent=2) + '\n', encoding='utf-8')
PY

CLAUDE_CMD="claude --settings '$SETTINGS_FILE' --add-dir '$CWD'"

# ── Global tmux-launch lock (prevents session-creation race) ──────────────
TMUX_LOCK="${CLAUDE_PLUGIN_DATA}/tmux-launch.lock"
mkdir -p "${CLAUDE_PLUGIN_DATA}"
if ! lock_acquire "$TMUX_LOCK" 10; then
  echo "[plate] failed to acquire tmux-launch lock" >&2
  exit 1
fi

if ! tmux_has_session "plate"; then
  tmux new-session -d -s plate -n "$WINDOW_NAME" -c "$CWD" "$CLAUDE_CMD"
  hide_output hide_errors tmux set-option -t '=plate' remain-on-exit off
else
  tmux new-window -t '=plate:' -n "$WINDOW_NAME" -c "$CWD" "$CLAUDE_CMD"
fi

lock_release "$TMUX_LOCK"

# If no terminal is currently attached to the plate tmux session, spawn
# Terminal.app on macOS so the bg-agent window is actually visible.
spawn_terminal_if_needed "plate" "${PLATE_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/plate-log.txt}" "plate"
