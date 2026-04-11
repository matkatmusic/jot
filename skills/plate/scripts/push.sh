#!/usr/bin/env bash
# push.sh — Orchestrate a full /plate push.
# Args: $1=convo_id  $2=transcript_path  $3=cwd
# Side effects: creates snapshot ref, appends to instance JSON stack[],
#   launches background agent in tmux.
set -euo pipefail

: "${CLAUDE_PLUGIN_ROOT:?}"
: "${CLAUDE_PLUGIN_DATA:?}"

SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/scripts"
PYTHON_DIR="${CLAUDE_PLUGIN_ROOT}/python"
PROMPTS_DIR="${CLAUDE_PLUGIN_ROOT}/prompts"

# shellcheck source=lib/paths.sh
. "$SCRIPTS_DIR/lib/paths.sh"
# shellcheck source=lib/lock.sh
. "$SCRIPTS_DIR/lib/lock.sh"

CONVO_ID="${1:?}"
TRANSCRIPT_PATH="${2:-}"
CWD="${3:-$PWD}"

plate_discover_root
plate_ensure_dirs

INSTANCE_FILE="${PLATE_ROOT}/instances/${CONVO_ID}.json"
TIMESTAMP=$(date -u +%Y-%m-%dT%H-%M-%SZ)
PLATE_ID="${TIMESTAMP}_$(basename "$CWD" | tr ' ' '-')"
HEAD_SHA=$(git rev-parse HEAD)
BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "detached")

# ── Reentrancy lock ──────────────────────────────────────────────────────
LOCK_DIR="${PLATE_ROOT}/.push.lock"
if ! plate_lock_acquire "$LOCK_DIR" 5; then
  echo "[plate] push already in progress, skipping duplicate" >&2
  exit 0
fi
trap 'plate_lock_release "$LOCK_DIR"' EXIT

# ── 1. Git snapshot (synchronous — must complete before agent starts) ─────
STASH_SHA=$(bash "$SCRIPTS_DIR/snapshot-stash.sh" "$CONVO_ID" "$PLATE_ID")

# ── 2. Compute files changed since previous plate (§7.1) ─────────────────
PREV_SHA="$HEAD_SHA"
PREV_PLATE=$(python3 "$PYTHON_DIR/instance_rw.py" top "$INSTANCE_FILE" 2>/dev/null || echo "{}")
if [ "$PREV_PLATE" != "{}" ]; then
  PREV_SHA=$(printf '%s' "$PREV_PLATE" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("push_time_head_sha",""))')
  [ -z "$PREV_SHA" ] && PREV_SHA="$HEAD_SHA"
fi
FILES_CHANGED=$(git diff --name-only "$PREV_SHA" HEAD 2>/dev/null || true)
FILES_UNCOMMITTED=$(git diff --name-only HEAD 2>/dev/null || true)
ALL_FILES=$(printf '%s\n%s' "$FILES_CHANGED" "$FILES_UNCOMMITTED" | sort -u | grep -v '^$' || true)

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
NEEDS_REFRESH=$(INSTANCE_FILE="$INSTANCE_FILE" python3 <<'PY' 2>/dev/null || echo "yes"
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
WINDOW_NAME="$(basename "$CWD")-${TIMESTAMP}"
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
plate_seed_permissions "$PERM_INSTALLED" "$PERM_DEFAULT" "$PERM_DEFAULT_SHA" "$PERM_PRIOR_SHA"

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
if ! plate_lock_acquire "$TMUX_LOCK" 10; then
  echo "[plate] failed to acquire tmux-launch lock" >&2
  exit 1
fi

if ! tmux has-session -t plate 2>/dev/null; then
  tmux new-session -d -s plate -n "$WINDOW_NAME" -c "$CWD" "$CLAUDE_CMD"
  tmux set-option -t plate remain-on-exit off >/dev/null 2>&1 || true
else
  tmux new-window -t plate -n "$WINDOW_NAME" -c "$CWD" "$CLAUDE_CMD"
fi

plate_lock_release "$TMUX_LOCK"
