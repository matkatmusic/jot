# /plate — Implementation Plan

Prescriptive engineering playbook for building the `/plate` skill from DESIGN.md.
Every code block is runnable as-is. Every phase has an exit criterion.

References use `§N` notation for DESIGN.md sections.

---

## 1. Guarantees

- Scripts in the **plugin** (`$CLAUDE_PLUGIN_ROOT/`), state in the **repo** (`<worktree>/.plate/`).
- `.plate/` is auto-gitignored on first creation. Git refs live in `.git/refs/plates/`.
- Hook suppression uses `{"decision":"block","reason":"..."}` on stdout (jot protocol).
- Hook input is JSON on stdin with fields: `prompt`, `session_id`, `transcript_path`, `cwd`.
- All shell scripts use `set -euo pipefail`. All python uses 3.11+.
- JSON writes are atomic: write to temp file, `fsync`, `os.replace`. No partial writes.
- `mkdir`-based lock prevents duplicate launches on hook double-fire.
- Every instance JSON carries `"schema_version": 1` for future migration.
- Cascade walks have a max depth of 20 hops to prevent infinite loops on corrupt `parent_ref`.

---

## 2. Plugin Directory Tree

```
plate/                                    # CLAUDE_PLUGIN_ROOT
├── .claude-plugin/
│   ├── plugin.json                       # Plugin manifest (name, version, author)
│   └── marketplace.json                  # Marketplace metadata (if published)
├── hooks/
│   └── hooks.json                        # Hook registration (UserPromptSubmit)
├── scripts/
│   ├── plate.sh                          # Main UserPromptSubmit hook entry point
│   ├── plate-session-start.sh            # Global SessionStart hook (resume freshness)
│   ├── plate-worker-start.sh             # Per-window SessionStart (send-keys prompt)
│   ├── plate-worker-stop.sh              # Per-window Stop (verify + kill window)
│   ├── plate-worker-end.sh               # Per-window SessionEnd (wipe tmpdir)
│   ├── snapshot-stash.sh                 # git stash create + update-ref
│   ├── push.sh                           # Orchestrate full push flow
│   ├── done.sh                           # Replay loop + cascade + commit
│   ├── drop.sh                           # Patch file + restore top plate
│   ├── next.sh                           # Walk parent chain + print resume command
│   ├── show.sh                           # Regenerate tree.md + open in $EDITOR
│   ├── render-tree.sh                    # Build tree.md from all instance JSONs
│   ├── list-paused-plates.sh             # Glob instances, emit dropdown rows
│   ├── register-parent.sh               # Write parent_ref + delegated_to[]
│   └── lib/
│       ├── paths.sh                      # PLATE_ROOT discovery, gitignore patch
│       └── lock.sh                       # mkdir-based lock helpers
├── python/
│   ├── instance_rw.py                    # Atomic JSON load / write / mutate
│   ├── transcript_parse.py               # JSONL parse + parentUuid dedup (§12)
│   ├── render_tree.py                    # Tree.md renderer
│   └── commit_message.py                 # Format --done commit messages (§7.3)
├── prompts/
│   ├── bg-agent.md                       # Background agent extraction prompt
│   └── drift-judge.md                    # Drift detection micro-LLM prompt
├── skills/
│   └── plate/
│       └── SKILL.md                      # Skill body for path-3 parent selection
├── assets/
│   ├── permissions.default.json          # Bundled permission allowlist
│   └── permissions.default.json.sha256   # SHA for three-state seeding
└── tests/
    ├── test-push-smoke.sh
    ├── test-done-smoke.sh
    ├── test-drop-smoke.sh
    └── fixtures/
        └── sample-transcript.jsonl
```

---

## 3. Runtime State Directory

Created per-repo at `<main-worktree>/.plate/`. Auto-discovered via `dirname "$(git rev-parse --git-common-dir)"`.

```
<main-worktree>/.plate/
├── project.json                          # Cross-instance delegation graph (future)
├── instances/
│   └── <convoID>.json                    # Source of truth per conversation
├── dropped/
│   └── <convoID>/
│       └── <plate-id>_<ts>.patch         # Recoverable abandoned work
├── inputs/
│   └── <convoID>_<ts>.txt                # Agent job payloads (temporary)
└── tree.md                               # Derived view (regenerated lazily)
```

Git refs (NOT in `.plate/`):
```
.git/refs/plates/<convoID>/<plate-id>     # Named refs keeping stash commits alive
```

---

## 4. Instance JSON Schema

`<worktree>/.plate/instances/<convoID>.json` — full example:

```json
{
  "schema_version": 1,
  "convo_id": "abc-123-def-456",
  "label": "refactor auth middleware",
  "label_source": "auto",
  "branch_at_registration": "feat/auth",
  "cwd": "/Users/matkatmusicllc/Programming/dotfiles",
  "created_at": "2026-04-09T12:34:56Z",
  "last_touched": "2026-04-09T13:45:12Z",

  "parent_ref": {
    "convo_id": null,
    "plate_id": null
  },

  "rolling_intent": {
    "text": "",
    "snapshot_at": null,
    "confidence": "low"
  },

  "drift_alert": {
    "pending": false,
    "message": "",
    "generated_at": null
  },

  "stack": [],
  "completed": []
}
```

Plate entry shape (within `stack[]` or `completed[]`):

```json
{
  "plate_id": "2026-04-09T13-12-34_refactor-auth",
  "pushed_at": "2026-04-09T13:12:34Z",
  "state": "paused",
  "delegated_to": [],
  "push_time_head_sha": "abc123def456",
  "stash_sha": "789abc012def",
  "branch": "feat/auth",
  "summary_action": "",
  "summary_goal": "",
  "summary_goal_hedge": {"confidence": "low", "reason": ""},
  "hypothesis": "",
  "hypothesis_hedge": {"confidence": "low", "reason": ""},
  "files": [],
  "errors": [],
  "completed_at": null,
  "commit_sha": null
}
```

---

## 5. Phased Implementation Plan

### Phase 0: Scaffold

**Goal:** Create the shared library and runtime directory structure.

**Depends on:** nothing.

**Files to create:**

| File | Purpose |
|---|---|
| `scripts/lib/paths.sh` | PLATE_ROOT discovery + .gitignore patch |
| `scripts/lib/lock.sh` | mkdir-based lock helpers |
| `python/instance_rw.py` | Atomic JSON read/write/mutate |

#### `scripts/lib/paths.sh`

```bash
#!/bin/bash
# paths.sh — sourced by every plate script. Sets PLATE_ROOT and ensures
# the runtime directory exists with .gitignore entry.

plate_discover_root() {
  local git_common_dir
  git_common_dir="$(git rev-parse --git-common-dir 2>/dev/null)" || {
    echo "[plate] not inside a git repository" >&2
    return 1
  }
  PLATE_ROOT="$(cd "$(dirname "$git_common_dir")" && pwd)/.plate"
  export PLATE_ROOT
}

plate_ensure_dirs() {
  mkdir -p "$PLATE_ROOT/instances" "$PLATE_ROOT/dropped" "$PLATE_ROOT/inputs"
  local repo_root
  repo_root="$(dirname "$PLATE_ROOT")"
  if ! grep -qxF '.plate/' "$repo_root/.gitignore" 2>/dev/null; then
    printf '\n.plate/\n' >> "$repo_root/.gitignore"
  fi
}
```

#### `scripts/lib/lock.sh`

```bash
#!/bin/bash
# lock.sh — mkdir-based lock helpers. Matches jot-state-lib.sh pattern.
# macOS does not ship flock; mkdir is atomic on every POSIX filesystem.

plate_lock_acquire() {
  local lock_dir="$1"
  local timeout="${2:-10}"
  local waited=0
  local max=$(( timeout * 20 ))
  while ! mkdir "$lock_dir" 2>/dev/null; do
    sleep 0.05
    waited=$(( waited + 1 ))
    if [ "$waited" -ge "$max" ]; then
      return 1
    fi
  done
  return 0
}

plate_lock_release() {
  rmdir "$1" 2>/dev/null || true
}
```

#### `python/instance_rw.py`

```python
#!/usr/bin/env python3
"""Atomic JSON read/write/mutate for .plate/instances/*.json."""
from __future__ import annotations
import json, os, sys, tempfile
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = 1

def load(path: Path) -> dict[str, Any]:
    """Load instance JSON. Returns empty dict if file missing."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically: tmp + fsync + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise

def mutate(path: Path, fn: Callable[[dict[str, Any]], None]) -> None:
    """Load, apply fn in-place, write back atomically."""
    data = load(path)
    fn(data)
    atomic_write(path, data)

def new_instance(convo_id: str, cwd: str, branch: str) -> dict[str, Any]:
    """Create a blank instance dict with schema_version."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "convo_id": convo_id,
        "label": "",
        "label_source": "auto",
        "branch_at_registration": branch,
        "cwd": cwd,
        "created_at": now,
        "last_touched": now,
        "parent_ref": {"convo_id": None, "plate_id": None},
        "rolling_intent": {"text": "", "snapshot_at": None, "confidence": "low"},
        "drift_alert": {"pending": False, "message": "", "generated_at": None},
        "stack": [],
        "completed": [],
    }

def new_plate(plate_id: str, head_sha: str, stash_sha: str, branch: str) -> dict[str, Any]:
    """Create a blank plate entry for stack[]."""
    from datetime import datetime, timezone
    return {
        "plate_id": plate_id,
        "pushed_at": datetime.now(timezone.utc).isoformat(),
        "state": "paused",
        "delegated_to": [],
        "push_time_head_sha": head_sha,
        "stash_sha": stash_sha,
        "branch": branch,
        "summary_action": "",
        "summary_goal": "",
        "summary_goal_hedge": {"confidence": "low", "reason": ""},
        "hypothesis": "",
        "hypothesis_hedge": {"confidence": "low", "reason": ""},
        "files": [],
        "errors": [],
        "completed_at": None,
        "commit_sha": None,
    }

# ── CLI interface for shell scripts ──────────────────────────────────────
if __name__ == "__main__":
    cmd = sys.argv[1]
    path = Path(sys.argv[2])

    if cmd == "stack-oldest":
        # Print stack entries oldest-first (one JSON per line)
        for plate in load(path).get("stack", []):
            print(json.dumps(plate))
    elif cmd == "stack-newest":
        # Print stack entries newest-first
        for plate in reversed(load(path).get("stack", [])):
            print(json.dumps(plate))
    elif cmd == "top":
        # Print top of stack (most recent plate)
        stack = load(path).get("stack", [])
        print(json.dumps(stack[-1] if stack else {}))
    elif cmd == "drop-top":
        mutate(path, lambda d: d["stack"].pop() if d.get("stack") else None)
    elif cmd == "complete":
        # Move plate from stack to completed with commit_sha + completed_at
        plate_id, commit_sha, completed_at = sys.argv[3:6]
        def op(d: dict) -> None:
            stack = d.get("stack", [])
            idx = next(i for i, p in enumerate(stack) if p["plate_id"] == plate_id)
            plate = stack.pop(idx)
            plate["completed_at"] = completed_at
            plate["commit_sha"] = commit_sha
            d.setdefault("completed", []).append(plate)
        mutate(path, op)
    elif cmd == "touch":
        from datetime import datetime, timezone
        mutate(path, lambda d: d.__setitem__("last_touched", datetime.now(timezone.utc).isoformat()))
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
```

**Exit criterion:**

```bash
cd /tmp && git init plate-test && cd plate-test && git commit --allow-empty -m "init"
PLATE_ROOT="$(pwd)/.plate"
source "$CLAUDE_PLUGIN_ROOT/scripts/lib/paths.sh"
plate_discover_root && plate_ensure_dirs
test -d "$PLATE_ROOT/instances" && grep -q '.plate/' .gitignore && echo "PASS: Phase 0"
```

---

### Phase 1: Push (Silent Paths 1 & 2)

**Goal:** Wire the UserPromptSubmit hook. On `/plate`, capture a git snapshot, write instance JSON, and launch the background agent. Paths 1 & 2 suppress the prompt entirely.

**Depends on:** Phase 0.

**Files to create:**

| File | Purpose |
|---|---|
| `scripts/plate.sh` | Main hook entry — parse stdin, gate, dispatch |
| `scripts/snapshot-stash.sh` | `git stash create` + `git update-ref` |
| `scripts/push.sh` | Orchestrate: snapshot + JSON + bg-agent launch |
| `hooks/hooks.json` | Plugin hook registration |
| `.claude-plugin/plugin.json` | Plugin manifest |

#### `hooks/hooks.json`

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/plate.sh"
          }
        ]
      }
    ]
  }
}
```

#### `.claude-plugin/plugin.json`

```json
{
  "name": "plate",
  "version": "0.1.0",
  "description": "Stack-of-plates WIP tracker for Claude Code. Captures uncommitted work context when switching tasks.",
  "author": {
    "name": "Matkat Music LLC"
  },
  "license": "MIT",
  "keywords": ["wip", "context", "stack", "plates", "hook", "tmux"]
}
```

#### `scripts/snapshot-stash.sh`

```bash
#!/usr/bin/env bash
# snapshot-stash.sh — Create named git ref for current working tree state.
# Args: $1=convo_id  $2=plate_id
# Stdout: the stash SHA
# Side effects: creates refs/plates/<convoID>/<plate-id>
set -euo pipefail

CONVO_ID="${1:?usage: snapshot-stash.sh <convo_id> <plate_id>}"
PLATE_ID="${2:?usage: snapshot-stash.sh <convo_id> <plate_id>}"

# git stash create produces a dangling commit. It returns NOTHING on a
# clean tracked tree. Fallback to HEAD in that case.
STASH_SHA=$(git stash create 2>/dev/null || true)
[ -n "$STASH_SHA" ] || STASH_SHA=$(git rev-parse HEAD)

# Named ref keeps the stash commit alive against git gc.
# This MUST run immediately after stash create — no commands in between.
REF="refs/plates/${CONVO_ID}/${PLATE_ID}"
git update-ref "$REF" "$STASH_SHA"

printf '%s\n' "$STASH_SHA"
```

#### `scripts/plate.sh`

```bash
#!/usr/bin/env bash
# plate.sh — UserPromptSubmit hook entry point.
# Reads JSON from stdin. Dispatches /plate variants.
# Matches jot.sh architecture: emit_block for suppression, self-filtering.
set -euo pipefail

: "${CLAUDE_PLUGIN_ROOT:?plate plugin env not set}"
: "${CLAUDE_PLUGIN_DATA:?plate plugin env not set}"

SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/scripts"
PYTHON_DIR="${CLAUDE_PLUGIN_ROOT}/python"
LOG_FILE="${PLATE_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/plate-log.txt}"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# shellcheck source=lib/paths.sh
. "$SCRIPTS_DIR/lib/paths.sh"
# shellcheck source=lib/lock.sh
. "$SCRIPTS_DIR/lib/lock.sh"

# ── emit_block: suppress prompt from reaching the LLM ────────────────────
emit_block() {
  local reason="$1"
  if command -v jq >/dev/null 2>&1; then
    jq -n --arg r "$reason" '{decision:"block", reason:$r}'
  else
    local esc="${reason//\\/\\\\}"
    esc="${esc//\"/\\\"}"
    printf '{"decision":"block","reason":"%s"}\n' "$esc"
  fi
}

# ── check_requirements ────────────────────────────────────────────────────
check_requirements() {
  local -a missing=()
  command -v jq      >/dev/null 2>&1 || missing+=("jq")
  command -v python3 >/dev/null 2>&1 || missing+=("python3")
  command -v tmux    >/dev/null 2>&1 || missing+=("tmux")
  command -v claude  >/dev/null 2>&1 || missing+=("claude")
  if [ ${#missing[@]} -gt 0 ]; then
    local list=""
    for item in "${missing[@]}"; do
      [ -z "$list" ] && list="$item" || list="$list, $item"
    done
    emit_block "plate needs: $list"
    exit 0
  fi
}

# ── Read hook input from stdin ────────────────────────────────────────────
INPUT=$(cat)

# ── Fast-path: bail if not /plate ─────────────────────────────────────────
case "$INPUT" in
  *'"/plate'*) ;;
  *) exit 0 ;;
esac

check_requirements

# ── Parse fields ──────────────────────────────────────────────────────────
PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""' | python3 -c 'import sys; print(sys.stdin.read().strip())')
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || echo "unknown")
TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | jq -r '.transcript_path // ""' 2>/dev/null || echo "")
CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // ""' 2>/dev/null || echo "")
[ -z "$CWD" ] && CWD="$PWD"

# ── Regex gate: only /plate and its variants ──────────────────────────────
if ! printf '%s' "$PROMPT" | grep -qE '^/plate(\s+(--done|--drop|--next|--show))?$'; then
  exit 0
fi

printf '%s plate session=%s prompt="%s"\n' "$(date -Iseconds)" "$SESSION_ID" "$PROMPT" >> "$LOG_FILE" 2>/dev/null || true

# ── ERR trap ──────────────────────────────────────────────────────────────
trap 'rc=$?; emit_block "plate crashed at line $LINENO (rc=$rc)"; printf "%s FAIL line=%s rc=%s\n" "$(date -Iseconds)" "$LINENO" "$rc" >> "$LOG_FILE" 2>/dev/null || true; exit 0' ERR

# ── Extract variant ───────────────────────────────────────────────────────
VARIANT=$(printf '%s' "$PROMPT" | sed 's|^/plate||; s|^ ||')

# ── Dispatch by variant ───────────────────────────────────────────────────
case "$VARIANT" in
  "")
    # /plate (push) — three-way gate (§8.1)
    plate_discover_root
    plate_ensure_dirs
    INSTANCE_FILE="${PLATE_ROOT}/instances/${SESSION_ID}.json"

    if [ -f "$INSTANCE_FILE" ]; then
      # PATH 1: this session has plate state → suppress + background push
      bash "$SCRIPTS_DIR/push.sh" "$SESSION_ID" "$TRANSCRIPT_PATH" "$CWD"
      emit_block "[plate] pushed"
    elif [ -d "${PLATE_ROOT}/instances" ] && \
         find "${PLATE_ROOT}/instances" -name "*.json" -maxdepth 1 2>/dev/null | read -r _; then
      # PATH 3: other instances exist → let prompt through for parent selection
      # Do NOT emit_block. Exit 0 lets the prompt reach the SKILL.md body.
      exit 0
    else
      # PATH 2: virgin repo → auto-register as top-level + suppress + push
      python3 "$PYTHON_DIR/instance_rw.py" create-instance \
        "$INSTANCE_FILE" "$SESSION_ID" "$CWD" \
        "$(git symbolic-ref --short HEAD 2>/dev/null || echo 'detached')"
      bash "$SCRIPTS_DIR/push.sh" "$SESSION_ID" "$TRANSCRIPT_PATH" "$CWD"
      emit_block "[plate] registered + pushed"
    fi
    ;;
  "--done")
    # /plate --done — pass through to skill body which runs done.sh
    # Foreground because user needs to see the commit output + resume command
    exit 0
    ;;
  "--drop")
    # /plate --drop — suppress + run drop.sh in background
    plate_discover_root
    INSTANCE_FILE="${PLATE_ROOT}/instances/${SESSION_ID}.json"
    bash "$SCRIPTS_DIR/drop.sh" "$SESSION_ID" "$INSTANCE_FILE"
    emit_block "[plate] dropped"
    ;;
  "--next")
    # /plate --next — pass through to skill body
    exit 0
    ;;
  "--show")
    # /plate --show — pass through to skill body
    exit 0
    ;;
esac

exit 0
```

#### `scripts/push.sh`

```bash
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
python3 -c "
import json, sys
sys.path.insert(0, '$PYTHON_DIR')
from instance_rw import load, atomic_write, new_instance, new_plate
from pathlib import Path
from datetime import datetime, timezone

path = Path('$INSTANCE_FILE')
data = load(path)
if not data:
    from instance_rw import new_instance
    data = new_instance('$CONVO_ID', '$CWD', '$BRANCH')

plate = new_plate('$PLATE_ID', '$HEAD_SHA', '$STASH_SHA', '$BRANCH')
plate['files'] = [f for f in '''$ALL_FILES'''.strip().split('\n') if f]
data['stack'].append(plate)
data['last_touched'] = datetime.now(timezone.utc).isoformat()
data['cwd'] = '$CWD'
if not data.get('label') and plate.get('summary_action'):
    data['label'] = plate['summary_action']
    data['label_source'] = 'auto'

atomic_write(path, data)
"

# ── 4. Launch background agent for field extraction ───────────────────────
# Durable-first: write INPUT_FILE before spawning tmux window.
INPUT_FILE="${PLATE_ROOT}/inputs/${CONVO_ID}_${TIMESTAMP}.txt"
cat > "$INPUT_FILE" <<PAYLOAD
{
  "convo_id": "$CONVO_ID",
  "plate_id": "$PLATE_ID",
  "instance_file": "$INSTANCE_FILE",
  "transcript_path": "$TRANSCRIPT_PATH",
  "plate_root": "$PLATE_ROOT",
  "cwd": "$CWD",
  "stash_sha": "$STASH_SHA",
  "head_sha": "$HEAD_SHA"
}
PAYLOAD

# ── Build per-invocation settings.json (jot pattern) ─────────────────────
TMPDIR_INV=$(mktemp -d /tmp/plate.XXXXXX)
SETTINGS_FILE="$TMPDIR_INV/settings.json"
WINDOW_NAME="$(basename "$CWD")-${TIMESTAMP}"
TMUX_TARGET="plate:$WINDOW_NAME"

# Copy lifecycle scripts to tmpdir (survives plugin update during run)
cp "$SCRIPTS_DIR/plate-worker-start.sh" "$TMPDIR_INV/"
cp "$SCRIPTS_DIR/plate-worker-stop.sh"  "$TMPDIR_INV/"
cp "$SCRIPTS_DIR/plate-worker-end.sh"   "$TMPDIR_INV/"

cat > "$SETTINGS_FILE" <<JSON
{
  "permissions": {
    "allow": [
      "Read($PLATE_ROOT/*)",
      "Write($PLATE_ROOT/*)",
      "Edit($PLATE_ROOT/*)",
      "Read($TRANSCRIPT_PATH)"
    ]
  },
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "bash $TMPDIR_INV/plate-worker-start.sh '$INPUT_FILE' '$TMUX_TARGET'"}]}],
    "Stop":         [{"hooks": [{"type": "command", "command": "bash $TMPDIR_INV/plate-worker-stop.sh '$INPUT_FILE' '$TMUX_TARGET'"}]}],
    "SessionEnd":   [{"hooks": [{"type": "command", "command": "bash $TMPDIR_INV/plate-worker-end.sh '$TMPDIR_INV'"}]}]
  }
}
JSON

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
```

**Exit criterion:**

```bash
# In a test repo with uncommitted changes:
echo "test change" >> test.txt && git add test.txt
echo '{"prompt":"/plate","session_id":"test-001","transcript_path":"","cwd":"'$(pwd)'"}' \
  | bash "$CLAUDE_PLUGIN_ROOT/scripts/plate.sh"
# Verify:
git cat-file -t "$(git for-each-ref --format='%(objectname)' refs/plates/test-001/)" | grep -q commit \
  && test -f .plate/instances/test-001.json \
  && python3 -c "import json; d=json.load(open('.plate/instances/test-001.json')); assert len(d['stack'])==1" \
  && echo "PASS: Phase 1"
```

---

### Phase 2: Background Agent

**Goal:** The tmux-hosted background claude reads the INPUT_FILE, parses the transcript, extracts `summary_action`, `summary_goal`, `hypothesis`, and populates the instance JSON with real field values.

**Depends on:** Phase 1.

**Files to create:**

| File | Purpose |
|---|---|
| `scripts/plate-worker-start.sh` | Per-window SessionStart — send-keys to claude |
| `scripts/plate-worker-stop.sh` | Per-window Stop — verify + kill window |
| `scripts/plate-worker-end.sh` | Per-window SessionEnd — wipe tmpdir |
| `python/transcript_parse.py` | JSONL parentUuid dedup + turn extraction |
| `prompts/bg-agent.md` | Extraction prompt with self-verification |

#### `scripts/plate-worker-start.sh`

```bash
#!/bin/bash
# plate-worker-start.sh — SessionStart hook for per-invocation claude windows.
# Fires once when claude starts in a tmux window. Sends the initial prompt.
# Args: $1=INPUT_FILE path  $2=tmux target (e.g. "plate:dotfiles-2026-04-09T13-12-34Z")
set -uo pipefail

INPUT_FILE="${1:-}"
TMUX_TARGET="${2:-}"

if [ -z "$INPUT_FILE" ] || [ -z "$TMUX_TARGET" ]; then
  echo "[plate-worker-start] missing args" >&2
  exit 0
fi

# Brief delay so claude's prompt loop accepts input.
sleep 2

tmux send-keys -t "$TMUX_TARGET" \
  "Read $INPUT_FILE and follow the instructions at the top of that file" Enter

exit 0
```

#### `scripts/plate-worker-stop.sh`

```bash
#!/bin/bash
# plate-worker-stop.sh — Stop hook. Verifies agent wrote fields, kills window.
# Args: $1=INPUT_FILE  $2=tmux target
set -uo pipefail

INPUT_FILE="${1:-}"
TMUX_TARGET="${2:-}"

if [ -z "$INPUT_FILE" ] || [ -z "$TMUX_TARGET" ]; then
  exit 0
fi

# Check that the agent marked the input as processed
ts=$(date -Iseconds)
if [ -f "$INPUT_FILE" ]; then
  first_line=$(head -1 "$INPUT_FILE" 2>/dev/null || true)
  if [[ "$first_line" == PROCESSED:* ]]; then
    echo "[$ts] plate-worker SUCCESS: $INPUT_FILE" >&2
  else
    echo "[$ts] plate-worker FAIL: no PROCESSED marker in $INPUT_FILE" >&2
  fi
fi

# Kill this window asynchronously (let hook return first)
( sleep 0.5 && tmux kill-window -t "$TMUX_TARGET" 2>/dev/null ) >/dev/null 2>&1 &
disown 2>/dev/null || true

exit 0
```

#### `scripts/plate-worker-end.sh`

```bash
#!/bin/bash
# plate-worker-end.sh — SessionEnd hook. Wipes the per-invocation tmpdir.
# Args: $1=tmpdir path
set -uo pipefail
TMPDIR_INV="${1:-}"
[ -n "$TMPDIR_INV" ] && [ -d "$TMPDIR_INV" ] && rm -rf "$TMPDIR_INV"
exit 0
```

#### `python/transcript_parse.py`

```python
#!/usr/bin/env python3
"""JSONL transcript parser with parentUuid-based dedup (§12).

"Consecutive user messages" means consecutive AFTER filtering to user-type
records only — not adjacent raw .jsonl lines. Tool calls, system messages,
and assistant responses between two user messages do not break the
"consecutive" relationship.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from typing import Iterator

def is_user_message(rec: dict) -> bool:
    """Check if a transcript record is a user message."""
    return (
        rec.get("type") == "user"
        or rec.get("role") == "user"
        or rec.get("message", {}).get("role") == "user"
    )

def deduped_user_turns(path: Path) -> Iterator[dict]:
    """Yield deduplicated user turns from a .jsonl transcript.

    For each parentUuid, only the LAST user message is kept.
    Earlier messages with the same parentUuid were cancelled/superseded.
    """
    pending: dict | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not is_user_message(rec):
            continue
        if pending and rec.get("parentUuid") == pending.get("parentUuid"):
            # Same parent → this supersedes the pending message
            pending = rec
            continue
        if pending:
            yield pending
        pending = rec
    if pending:
        yield pending

def extract_recent_turns(path: Path, n: int = 50) -> list[dict]:
    """Return the last N deduplicated user turns."""
    turns = list(deduped_user_turns(path))
    return turns[-n:]

def extract_errors(path: Path, since_ts: str | None = None, max_count: int = 10) -> list[str]:
    """Extract error messages from transcript since a given timestamp.

    Scans both user messages (pasted errors) and tool results (runtime errors).
    Returns up to max_count most recent errors.
    """
    errors: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Skip if before the cutoff timestamp
        if since_ts and rec.get("timestamp", "") < since_ts:
            continue
        # Check for error patterns in content
        content = ""
        if isinstance(rec.get("message"), dict):
            content = rec["message"].get("content", "")
        elif isinstance(rec.get("content"), str):
            content = rec["content"]
        # Heuristic: lines containing "error", "Error", "ERROR", "failed", "FAIL"
        if any(kw in content for kw in ("Error:", "error:", "ERROR", "FAIL", "failed", "panic:", "Traceback")):
            # Truncate to first 200 chars
            errors.append(content[:200])
    return errors[-max_count:]

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: transcript_parse.py <dedup|errors|recent> <path> [args...]", file=sys.stderr)
        sys.exit(1)
    cmd, path = sys.argv[1], Path(sys.argv[2])
    if cmd == "dedup":
        for rec in deduped_user_turns(path):
            print(json.dumps(rec))
    elif cmd == "recent":
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 50
        for rec in extract_recent_turns(path, n):
            print(json.dumps(rec))
    elif cmd == "errors":
        since = sys.argv[3] if len(sys.argv) > 3 else None
        for err in extract_errors(path, since):
            print(err)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
```

#### `prompts/bg-agent.md`

This is the content written into `INPUT_FILE` as instructions the background claude follows. The `push.sh` script prepends this to the job payload.

```markdown
## Instructions

You are a background agent extracting metadata from a Claude Code conversation.
Read the job payload JSON below, then:

1. Read the transcript at `transcript_path` (use the Read tool directly — no Bash).
2. Filter to deduplicated user turns using the parentUuid rule:
   if two consecutive user messages share the same parentUuid, only the later one counts.
3. From the recent conversation context, extract:
   - `summary_action`: 1 sentence — what was being tried (concrete action).
   - `summary_goal`: 1 sentence — broader goal the action served.
   - `hypothesis`: reasoning / why-this-approach.
   - `rolling_intent.text`: 1 sentence — what the user is currently trying to accomplish.
4. For each extracted field, self-verify against the source transcript.
   You must be **at least 90% certain** of each value.
   If below 90%, set the companion `_hedge.confidence` to `low` or `medium` and write
   a concrete `_hedge.reason` (e.g., "inferred from single phrase in turn N; user never
   explicitly stated the goal").
5. Extract up to 10 error messages from the time window since the previous plate push.
6. Read the instance JSON at `instance_file`.
7. Update the LAST entry in `stack[]` with your extracted fields.
8. Update `rolling_intent` on the instance root.
9. Write the updated instance JSON back using the Edit tool.
10. Overwrite this INPUT_FILE with the single line: `PROCESSED: <plate_id>`

Rules:
- NEVER ask questions. Zero interaction.
- NEVER run Bash commands. Use only Read, Write, Edit tools.
- Store error messages verbatim (truncated to 200 chars each).
- Every `_hedge` field MUST include a `reason` string. Never leave `reason` empty.
```

**Exit criterion:**

```bash
# After a /plate push with a real transcript, wait ~30s for the bg agent, then:
python3 -c "
import json
d = json.load(open('.plate/instances/test-001.json'))
plate = d['stack'][-1]
assert plate['summary_action'] != '', 'summary_action not populated'
print('PASS: Phase 2 — bg agent populated fields')
"
```

---

### Phase 3: Registration (Path 3 — Parent Selection)

**Goal:** When a new conversation enters a repo that already has plate state, present a parent-selection dropdown and register the relationship.

**Depends on:** Phase 1.

**Files to create:**

| File | Purpose |
|---|---|
| `skills/plate/SKILL.md` | Skill body (foreground claude sees this on path 3) |
| `scripts/list-paused-plates.sh` | Glob instances, emit dropdown rows |
| `scripts/register-parent.sh` | Write parent_ref + flip delegated_to[] |

#### `scripts/list-paused-plates.sh`

```bash
#!/usr/bin/env bash
# list-paused-plates.sh — Emit one row per paused plate across all instances.
# Output format: <convoID>|<plate_id>|<label>|<summary_action>|<pushed_at>
# Used by SKILL.md to build the AskUserQuestion dropdown.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/paths.sh
. "$SCRIPTS_DIR/lib/paths.sh"
plate_discover_root

shopt -s nullglob
for f in "$PLATE_ROOT"/instances/*.json; do
  python3 -c "
import json, sys
from datetime import datetime, timezone
d = json.load(open('$f'))
convo = d.get('convo_id', '')
label = d.get('label', convo[:12])
for p in d.get('stack', []):
    if p.get('state') == 'paused':
        pushed = p.get('pushed_at', '')
        action = p.get('summary_action', '(no synopsis)')
        print(f'{convo}|{p[\"plate_id\"]}|{label}|{action}|{pushed}')
" 2>/dev/null || true
done
shopt -u nullglob
```

#### `scripts/register-parent.sh`

```bash
#!/usr/bin/env bash
# register-parent.sh — Register parent-child relationship.
# Args: $1=child_convo_id  $2=parent_convo_id  $3=parent_plate_id
#   If $2 is "none", register as top-level.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_DIR="${CLAUDE_PLUGIN_ROOT}/python"
# shellcheck source=lib/paths.sh
. "$SCRIPTS_DIR/lib/paths.sh"
plate_discover_root

CHILD_CONVO="${1:?}"
PARENT_CONVO="${2:?}"
PARENT_PLATE="${3:-}"

CHILD_FILE="${PLATE_ROOT}/instances/${CHILD_CONVO}.json"

if [ "$PARENT_CONVO" = "none" ]; then
  # Top-level: parent_ref stays null (already default)
  exit 0
fi

PARENT_FILE="${PLATE_ROOT}/instances/${PARENT_CONVO}.json"

python3 -c "
import sys
sys.path.insert(0, '$PYTHON_DIR')
from instance_rw import load, atomic_write
from pathlib import Path

# Set child's parent_ref
child_path = Path('$CHILD_FILE')
child = load(child_path)
child['parent_ref'] = {'convo_id': '$PARENT_CONVO', 'plate_id': '$PARENT_PLATE'}
atomic_write(child_path, child)

# Add child to parent's delegated_to[] and flip state
parent_path = Path('$PARENT_FILE')
parent = load(parent_path)
for plate in parent.get('stack', []):
    if plate['plate_id'] == '$PARENT_PLATE':
        if '$CHILD_CONVO' not in plate.get('delegated_to', []):
            plate.setdefault('delegated_to', []).append('$CHILD_CONVO')
        plate['state'] = 'delegated'
        break
atomic_write(parent_path, parent)
"
```

#### `skills/plate/SKILL.md`

```markdown
---
name: plate
description: Stack-of-plates WIP tracker. Push uncommitted work context when switching tasks.
---

# Task:

Run `bash ${CLAUDE_PLUGIN_ROOT}/scripts/list-paused-plates.sh` to get candidate parents.

If the output is EMPTY (no paused plates anywhere):
- Register this session as top-level silently.
- Run `bash ${CLAUDE_PLUGIN_ROOT}/scripts/register-parent.sh "${SESSION_ID}" "none"`.
- Then run the push: `bash ${CLAUDE_PLUGIN_ROOT}/scripts/push.sh "${SESSION_ID}" "${TRANSCRIPT_PATH}" "${CWD}"`.
- Reply: "plate registered + pushed (top-level)".

If the output has 1+ rows:
- Build options for AskUserQuestion. Each row is `convoID|plateID|label|synopsis|pushed_at`.
  Format each as: `<label> -> "<synopsis>" (paused <relative time>)`.
  Add "Top-level (no parent)" as the first option.
- Call AskUserQuestion with header "Parent" and question "Pick a parent plate (or top-level)".
- Parse the user's selection. Run register-parent.sh with the chosen convoID and plateID.
- Then run the push.
- Reply with one line: "plate registered + pushed: <synopsis>".
```

**Exit criterion:**

```bash
# With at least one existing instance JSON containing a paused plate:
bash "$CLAUDE_PLUGIN_ROOT/scripts/list-paused-plates.sh" | grep -q '|paused' \
  || bash "$CLAUDE_PLUGIN_ROOT/scripts/list-paused-plates.sh" | wc -l | grep -q '[1-9]'
echo "PASS: Phase 3 — list-paused-plates emits rows"
```

---

### Phase 4: Done

**Goal:** Replay plates as sequential commits, cascade through delegation chain, clean up refs.

**Depends on:** Phase 1, Phase 2 (for populated fields).

**Files to create:**

| File | Purpose |
|---|---|
| `scripts/done.sh` | Replay loop + cascade + commit |
| `python/commit_message.py` | Format structured commit messages (§7.3) |

#### `python/commit_message.py`

```python
#!/usr/bin/env python3
"""Format a plate's commit message per §7.3."""
import json, sys

def format_commit_message(plate: dict) -> str:
    lines = [f"[plate] {plate.get('summary_action', 'untitled plate')}"]
    goal = plate.get("summary_goal", "")
    if goal:
        lines.append(f"\nGoal: {goal}")
    hyp = plate.get("hypothesis", "")
    if hyp:
        hedge = plate.get("hypothesis_hedge", {})
        conf = hedge.get("confidence", "")
        reason = hedge.get("reason", "")
        lines.append(f"\nHypothesis: {hyp}")
        if conf:
            lines.append(f"  (confidence: {conf}; reason: {reason})")
    errors = plate.get("errors", [])
    if errors:
        lines.append("\nErrors encountered during this plate:")
        for e in errors:
            lines.append(f"  - {e}")
    lines.append(f"\nplate-id: {plate.get('plate_id', '')}")
    lines.append(f"pushed-at: {plate.get('pushed_at', '')}")
    return "\n".join(lines)

if __name__ == "__main__":
    plate = json.loads(sys.stdin.read())
    print(format_commit_message(plate))
```

#### `scripts/done.sh`

```bash
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

STACK_COUNT=$(python3 -c "import json; d=json.load(open('$INSTANCE_FILE')); print(len(d.get('stack',[])))")
if [ "$STACK_COUNT" -eq 0 ]; then
  echo "Error: no plates on the stack to commit." >&2
  exit 1
fi

# ── Check for open delegated children (§9.3) ─────────────────────────────
HAS_LIVE_CHILDREN=$(python3 -c "
import json
d = json.load(open('$INSTANCE_FILE'))
live = any(p.get('delegated_to') for p in d.get('stack', []) if p.get('state') == 'delegated')
print('yes' if live else 'no')
")
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
python3 -c "
import json, sys
sys.path.insert(0, '$PYTHON_DIR')
from instance_rw import load, atomic_write
from pathlib import Path

instance_file = Path('$INSTANCE_FILE')
data = load(instance_file)
parent_ref = data.get('parent_ref', {})
depth = 0

while parent_ref and parent_ref.get('convo_id') and depth < $MAX_DEPTH:
    parent_convo = parent_ref['convo_id']
    parent_plate_id = parent_ref.get('plate_id', '')
    parent_path = Path('$PLATE_ROOT') / 'instances' / f'{parent_convo}.json'
    if not parent_path.exists():
        break
    parent_data = load(parent_path)
    for plate in parent_data.get('stack', []):
        if plate['plate_id'] == parent_plate_id:
            # Remove this child from delegated_to
            dt = plate.get('delegated_to', [])
            if '${CONVO_ID}' in dt:
                dt.remove('${CONVO_ID}')
            # If no more children, flip back to paused
            if not dt:
                plate['state'] = 'paused'
            break
    atomic_write(parent_path, parent_data)
    # Stop at first ancestor (§9.2 step 3)
    break
"

# ── Print result ──────────────────────────────────────────────────────────
BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "detached")
echo "Committed ${#COMMIT_SHAS[@]} plates in ${CONVO_ID} -> ${BRANCH} (${COMMIT_SHAS[*]})"

# Print resume pointer if parent exists
python3 -c "
import json
from pathlib import Path
d = json.load(open('$INSTANCE_FILE'))
pr = d.get('parent_ref', {})
if pr.get('convo_id'):
    parent_path = Path('$PLATE_ROOT') / 'instances' / f'{pr[\"convo_id\"]}.json'
    if parent_path.exists():
        pd = json.load(open(parent_path))
        cwd = pd.get('cwd', '.')
        print(f'\\nTo resume parent, run:\\n  cd {cwd} && claude --resume {pr[\"convo_id\"]}')
" 2>/dev/null || true
```

**Exit criterion:**

```bash
# After pushing 2 plates and running done:
CONVO_ID=test-done-001
bash "$CLAUDE_PLUGIN_ROOT/scripts/done.sh" "$CONVO_ID"
# Verify:
git log --oneline -3 | grep -c '\[plate\]' | grep -q '[1-9]' \
  && python3 -c "import json; d=json.load(open('.plate/instances/test-done-001.json')); assert len(d['completed'])>=1" \
  && ! git for-each-ref "refs/plates/test-done-001/" | grep -q . \
  && echo "PASS: Phase 4"
```

---

### Phase 5: Drop

**Goal:** Abandon top plate's uncommitted work as a recoverable patch file. Restore previous plate state.

**Depends on:** Phase 1.

#### `scripts/drop.sh`

```bash
#!/usr/bin/env bash
# drop.sh — /plate --drop: save abandoned work as patch, restore top plate (§7.4).
# Args: $1=convo_id  $2=instance_file
set -euo pipefail

: "${CLAUDE_PLUGIN_ROOT:?}"
PYTHON_DIR="${CLAUDE_PLUGIN_ROOT}/python"
SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/scripts"

# shellcheck source=lib/paths.sh
. "$SCRIPTS_DIR/lib/paths.sh"
plate_discover_root

CONVO_ID="${1:?usage: drop.sh <convo_id> <instance_file>}"
INSTANCE_FILE="${2:?usage: drop.sh <convo_id> <instance_file>}"

# ── Get top plate ─────────────────────────────────────────────────────────
TOP=$(python3 "$PYTHON_DIR/instance_rw.py" top "$INSTANCE_FILE")
PLATE_ID=$(printf '%s' "$TOP" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("plate_id",""))')

if [ -z "$PLATE_ID" ]; then
  cat >&2 <<'ERR'
Error: no plates on the stack to drop.

If you want to discard all uncommitted changes and reset to HEAD instead, run one of:
  git stash push -u                            (recoverable via `git stash pop`)
  git reset --hard HEAD && git clean -fd       (destructive — no recovery)
ERR
  exit 1
fi

REF="refs/plates/${CONVO_ID}/${PLATE_ID}"

# ── Verify ref exists ─────────────────────────────────────────────────────
if ! git cat-file -t "$REF" >/dev/null 2>&1; then
  echo "Error: ref $REF does not exist (may have been GC'd)" >&2
  exit 1
fi

# ── Build full snapshot including untracked files ─────────────────────────
TEMP_SNAPSHOT=$(git stash create -u 2>/dev/null || true)

# ── Write patch file ──────────────────────────────────────────────────────
TS=$(date +%s)
PATCH_DIR="${PLATE_ROOT}/dropped/${CONVO_ID}"
mkdir -p "$PATCH_DIR"
PATCH_FILE="${PATCH_DIR}/${PLATE_ID}_${TS}.patch"

if [ -n "$TEMP_SNAPSHOT" ]; then
  git diff --binary "$REF" "$TEMP_SNAPSHOT" > "$PATCH_FILE"
else
  : > "$PATCH_FILE"
fi

# ── Restore top plate state ───────────────────────────────────────────────
git checkout "$REF" -- .

# ── Remove plate from stack and delete ref ────────────────────────────────
git update-ref -d "$REF"
python3 "$PYTHON_DIR/instance_rw.py" drop-top "$INSTANCE_FILE"

echo "Dropped plate $PLATE_ID"
echo "Patch saved to: $PATCH_FILE"
echo "Recover via: git apply '$PATCH_FILE'"
```

**Exit criterion:**

```bash
# After pushing a plate and making additional changes:
echo "extra work" >> extra.txt
CONVO_ID=test-drop-001
bash "$CLAUDE_PLUGIN_ROOT/scripts/drop.sh" "$CONVO_ID" ".plate/instances/test-drop-001.json"
test -f .plate/dropped/test-drop-001/*.patch \
  && ! git for-each-ref "refs/plates/test-drop-001/" | grep -q . \
  && echo "PASS: Phase 5"
```

---

### Phase 6: Navigation (Show, Next)

**Goal:** Regenerate the tree view and walk the delegation chain to find the next resume point.

**Depends on:** Phase 0, Phase 3 (for parent_ref).

**Files to create:**

| File | Purpose |
|---|---|
| `scripts/show.sh` | Regenerate tree.md + open in $EDITOR |
| `scripts/next.sh` | Walk parent chain, print resume command |
| `scripts/render-tree.sh` | Build tree.md from all instance JSONs |

#### `scripts/render-tree.sh`

```bash
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
```

#### `scripts/show.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
bash "$SCRIPTS_DIR/render-tree.sh"
# shellcheck source=lib/paths.sh
. "$SCRIPTS_DIR/lib/paths.sh"
plate_discover_root
"${EDITOR:-less}" "$PLATE_ROOT/tree.md"
```

#### `scripts/next.sh`

```bash
#!/usr/bin/env bash
# next.sh — Walk parent delegation chain upward to find next resume point (§4).
# Args: $1=convo_id
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_DIR="${CLAUDE_PLUGIN_ROOT}/python"
# shellcheck source=lib/paths.sh
. "$SCRIPTS_DIR/lib/paths.sh"
plate_discover_root

CONVO_ID="${1:?usage: next.sh <convo_id>}"
INSTANCE_FILE="${PLATE_ROOT}/instances/${CONVO_ID}.json"

python3 -c "
import json
from pathlib import Path

plate_root = Path('$PLATE_ROOT')
convo = '$CONVO_ID'
depth = 0
MAX_DEPTH = 20

while depth < MAX_DEPTH:
    inst_path = plate_root / 'instances' / f'{convo}.json'
    if not inst_path.exists():
        break
    data = json.load(open(inst_path))
    parent = data.get('parent_ref', {})
    if not parent or not parent.get('convo_id'):
        print(f'Reached top-level instance: {convo}')
        print(f'No ancestor with paused work.')
        break
    parent_convo = parent['convo_id']
    parent_plate_id = parent.get('plate_id', '')
    parent_path = plate_root / 'instances' / f'{parent_convo}.json'
    if not parent_path.exists():
        print(f'Parent {parent_convo} not found (dangling ref)')
        break
    parent_data = json.load(open(parent_path))
    # Check if parent has paused work
    paused = [p for p in parent_data.get('stack', []) if p.get('state') == 'paused']
    if paused:
        cwd = parent_data.get('cwd', '.')
        label = parent_data.get('label', parent_convo[:12])
        action = paused[-1].get('summary_action', '(no synopsis)')
        print(f'Resume here: {label} -> \"{action}\"')
        print(f'  cd {cwd} && claude --resume {parent_convo}')
        break
    convo = parent_convo
    depth += 1
else:
    print('Max depth reached (possible cycle in parent_ref chain)')
"
```

**Exit criterion:**

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/render-tree.sh" && test -f .plate/tree.md && echo "PASS: Phase 6"
```

---

### Phase 7: Drift Detection

**Goal:** Detect when the user's conversation has drifted from their stated rolling intent (§11).

**Depends on:** Phase 2 (bg-agent infrastructure).

This phase adds logic to the background agent prompt and the UserPromptSubmit hook.

#### Changes to `push.sh`

In step 4 (INPUT_FILE creation), add a drift-check trigger when `now - rolling_intent.snapshot_at > 5min`:

```bash
# Check if rolling intent needs refresh
NEEDS_REFRESH=$(python3 -c "
import json
from datetime import datetime, timezone, timedelta
d = json.load(open('$INSTANCE_FILE'))
ri = d.get('rolling_intent', {})
snap = ri.get('snapshot_at')
if not snap:
    print('yes')
else:
    snap_dt = datetime.fromisoformat(snap)
    if datetime.now(timezone.utc) - snap_dt > timedelta(minutes=5):
        print('yes')
    else:
        print('no')
" 2>/dev/null || echo "yes")
```

If `NEEDS_REFRESH=yes`, include `"refresh_rolling_intent": true` in the INPUT_FILE payload. The bg-agent prompt handles the rest.

#### `prompts/drift-judge.md`

```markdown
You are a STRICT drift judge. Given:
- rolling_intent: the user's stated current goal
- recent_turns: the last 3 conversation turns

Answer ONLY with valid JSON:
{"drifted": true|false, "confidence": "low"|"medium"|"high", "reason": "..."}

Rules:
- Only return drifted=true when you are HIGHLY CONFIDENT the user has changed topics.
- False positives erode trust. When in doubt, return drifted=false.
- A debugging side-quest related to the intent is NOT drift.
- A long pause followed by new work IS drift if the topic changed.
```

#### Changes to `plate.sh` (hook)

Before the gate logic, check for pending drift alerts:

```bash
# Drift alert injection (§11.3)
if [ -f "$INSTANCE_FILE" ]; then
  DRIFT_PENDING=$(python3 -c "
import json
d = json.load(open('$INSTANCE_FILE'))
da = d.get('drift_alert', {})
if da.get('pending'):
    print(da.get('message', ''))
" 2>/dev/null || true)
  if [ -n "$DRIFT_PENDING" ]; then
    # Clear the flag (ack-once)
    python3 -c "
import sys
sys.path.insert(0, '$PYTHON_DIR')
from instance_rw import mutate
from pathlib import Path
mutate(Path('$INSTANCE_FILE'), lambda d: d.get('drift_alert', {}).__setitem__('pending', False))
"
    # Inject system note (the hook can prepend to the response)
    # This works via the hook's stdout as supplemental context
  fi
fi
```

**Exit criterion:**

```bash
# Manually set drift_alert.pending=true in an instance JSON, then trigger /plate:
python3 -c "
import json; f='.plate/instances/test-001.json'
d=json.load(open(f))
d['drift_alert']={'pending':True,'message':'test drift','generated_at':'2026-04-09T00:00:00Z'}
json.dump(d, open(f,'w'), indent=2)
"
# Verify the hook clears it:
echo '{"prompt":"/plate","session_id":"test-001","cwd":"'$(pwd)'"}' | bash "$CLAUDE_PLUGIN_ROOT/scripts/plate.sh" >/dev/null 2>&1
python3 -c "import json; assert not json.load(open('.plate/instances/test-001.json'))['drift_alert']['pending']" \
  && echo "PASS: Phase 7"
```

---

### Phase 8: SessionStart Freshness Check

**Goal:** On `claude --resume`, verify stash refs still exist and warn about stale state (§14 Implementation Notes).

**Depends on:** Phase 1.

#### `scripts/plate-session-start.sh`

```bash
#!/usr/bin/env bash
# plate-session-start.sh — Global SessionStart hook for resume freshness.
# Runs on every `claude --resume <convoID>`. NOT the per-worker SessionStart.
set -uo pipefail

: "${CLAUDE_PLUGIN_ROOT:?}"
SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/scripts"
PYTHON_DIR="${CLAUDE_PLUGIN_ROOT}/python"

# shellcheck source=lib/paths.sh
. "$SCRIPTS_DIR/lib/paths.sh"
plate_discover_root 2>/dev/null || exit 0

# Determine session ID from hook input
INPUT=$(cat)
SESSION_ID=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("session_id",""))' 2>/dev/null || echo "")
[ -z "$SESSION_ID" ] && exit 0

INSTANCE_FILE="${PLATE_ROOT}/instances/${SESSION_ID}.json"
[ -f "$INSTANCE_FILE" ] || exit 0

# ── Verify stash refs are alive ───────────────────────────────────────────
python3 -c "
import json, subprocess, sys
d = json.load(open('$INSTANCE_FILE'))
warnings = []
for plate in d.get('stack', []):
    ref = f'refs/plates/${SESSION_ID}/{plate[\"plate_id\"]}'
    result = subprocess.run(['git', 'cat-file', '-t', ref], capture_output=True, text=True)
    if result.returncode != 0:
        warnings.append(f'  stash ref {ref} missing (may have been GC\\'d)')
    head = plate.get('push_time_head_sha', '')
    if head:
        result2 = subprocess.run(['git', 'merge-base', '--is-ancestor', head, 'HEAD'], capture_output=True)
        if result2.returncode != 0:
            warnings.append(f'  push_time_head_sha {head[:8]} not reachable from HEAD (branch rewritten?)')
if warnings:
    print('plate freshness warnings:', file=sys.stderr)
    for w in warnings:
        print(w, file=sys.stderr)
" 2>&1 || true

# ── Update last_touched ──────────────────────────────────────────────────
python3 "$PYTHON_DIR/instance_rw.py" touch "$INSTANCE_FILE"

# ── Clear stale drift alerts ─────────────────────────────────────────────
python3 -c "
import sys
sys.path.insert(0, '$PYTHON_DIR')
from instance_rw import mutate
from pathlib import Path
mutate(Path('$INSTANCE_FILE'), lambda d: d.get('drift_alert', {}).__setitem__('pending', False))
" 2>/dev/null || true

# ── Re-render tree.md ─────────────────────────────────────────────────────
bash "$SCRIPTS_DIR/render-tree.sh" 2>/dev/null || true

exit 0
```

To register this as a global hook, add to `hooks/hooks.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [{"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/scripts/plate.sh"}]
      }
    ],
    "SessionStart": [
      {
        "hooks": [{"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/scripts/plate-session-start.sh"}]
      }
    ]
  }
}
```

**Exit criterion:**

```bash
# Delete a stash ref, then simulate resume:
git update-ref -d refs/plates/test-001/some-plate 2>/dev/null
echo '{"session_id":"test-001"}' | bash "$CLAUDE_PLUGIN_ROOT/scripts/plate-session-start.sh" 2>&1 | grep -q "missing" \
  && echo "PASS: Phase 8"
```

---

## 6. Script Contracts Table

| Script | Invoked By | Inputs | Side Effects | Exit Codes |
|---|---|---|---|---|
| `plate.sh` | UserPromptSubmit hook | stdin JSON (`prompt`, `session_id`, `transcript_path`, `cwd`) | Gate logic, may spawn bg-agent, may emit_block | 0 always |
| `snapshot-stash.sh` | `push.sh` | `$1`=convo_id, `$2`=plate_id | Creates `refs/plates/<convo>/<plate>` | 0=ok, 1=git error |
| `push.sh` | `plate.sh` (paths 1,2) | `$1`=convo_id, `$2`=transcript_path, `$3`=cwd | Snapshot + JSON write + tmux launch | 0=ok, 1=lock fail |
| `done.sh` | Skill body (foreground) | `$1`=convo_id | Sequential commits, ref cleanup, cascade | 0=ok, 1=empty stack |
| `drop.sh` | `plate.sh` (--drop) | `$1`=convo_id, `$2`=instance_file | Patch file + ref delete + stack pop | 0=ok, 1=empty stack |
| `next.sh` | Skill body (foreground) | `$1`=convo_id | Prints resume command | 0 always |
| `show.sh` | Skill body (foreground) | none | Renders tree.md, opens $EDITOR | 0 always |
| `render-tree.sh` | Multiple callers | none | Writes `tree.md` | 0 always |
| `list-paused-plates.sh` | Skill body (path 3) | none | Stdout: rows of paused plates | 0 always |
| `register-parent.sh` | Skill body (path 3) | `$1`=child, `$2`=parent_convo, `$3`=parent_plate | Writes parent_ref + delegated_to | 0=ok |
| `plate-session-start.sh` | Global SessionStart hook | stdin JSON (`session_id`) | Freshness warnings, touch, re-render | 0 always |
| `plate-worker-start.sh` | Per-window SessionStart | `$1`=input_file, `$2`=tmux_target | tmux send-keys | 0 always |
| `plate-worker-stop.sh` | Per-window Stop | `$1`=input_file, `$2`=tmux_target | Verify PROCESSED, kill window | 0 always |
| `plate-worker-end.sh` | Per-window SessionEnd | `$1`=tmpdir | rm -rf tmpdir | 0 always |

---

## 7. Under-Specified Decisions (Pinned)

These areas were fuzzy in DESIGN.md. This plan pins them:

1. **§8.1 "suppress" semantics.** Hook suppresses by printing `{"decision":"block","reason":"..."}` to stdout and exiting 0. This matches the jot hook protocol. If Claude Code changes the hook suppression API, update `emit_block()` in one place.

2. **§7.3 first-plate replay base.** The first plate's diff uses `push_time_head_sha` (from that plate's JSON), NOT the current `HEAD`. Subsequent plates diff from the previous plate's `stash_sha`. Codified in `done.sh`'s `LAST_REF` variable.

3. **§6 schema versioning.** Every instance JSON carries `"schema_version": 1`. `instance_rw.py`'s `load()` function checks this on read. Future migrations increment the version and add a converter.

4. **§9.2 cascade cycle guard.** `done.sh` and `next.sh` walk at most 20 hops up the `parent_ref` chain. On hit: `"Max depth reached (possible cycle in parent_ref chain)"`.

5. **git stash create empty-tree.** `snapshot-stash.sh` falls back to `HEAD` when `git stash create` returns empty (clean tracked tree). The ref is still created so the plate has a valid `stash_sha`.

6. **§12 "consecutive" meaning.** "Consecutive user messages" means consecutive after filtering to user-type records only. Tool calls, system messages, and assistant responses between two user messages do not break the "consecutive" relationship. Codified in `transcript_parse.py`.

7. **§7.3 replay commit timestamps.** Replay commits use the current execution time for `GIT_AUTHOR_DATE` and `GIT_COMMITTER_DATE` (git default). The original `pushed_at` timestamp is preserved in the commit message trailer. Overriding git dates would confuse `git log` chronology.

8. **§8.2 path-3 skill body location.** The SKILL.md body lives at `skills/plate/SKILL.md` in the plugin. It is only reached when path-3 fires (other instances exist, this session is new). Paths 1 and 2 suppress before the skill body executes.

9. **done.sh replay worktree.** Replay happens in the current worktree using `git diff | git apply --index --3way`. The `--3way` flag handles conflicts. If the working tree is dirty after the last plate, step 4 captures it as a final commit. No separate scratch worktree is needed.

10. **tmux window initialization race.** `plate-worker-start.sh` uses a 2-second `sleep` before `tmux send-keys` (same as jot). This is a pragmatic delay, not a guarantee. If claude's TUI is slow to initialize, increase to 3s. A future improvement: poll for the claude prompt character before sending.

---

## 8. Open Punch-List

- [ ] **`python/render_tree.py`**: Full implementation needed. Contract: read all `instances/*.json`, sort by `last_touched` desc, produce box-drawing tree per §13 example. No LLM needed.
- [ ] **`prompts/bg-agent.md` integration**: The `push.sh` script writes a raw JSON payload to INPUT_FILE. It must prepend the bg-agent prompt instructions. Wire the heredoc into `push.sh` step 4.
  *Next step:* Copy the prompt from Phase 2 section into push.sh as a heredoc, prepended to INPUT_FILE before the JSON payload.
- [ ] **Permissions model**: Implement three-state seeding (`jot_seed_permissions` equivalent) for `assets/permissions.default.json`. Currently stubbed.
  *Next step:* Port `jot_seed_permissions()` from jot.sh, changing variable names.
- [ ] **`spawn_terminal_if_needed`**: Optional macOS convenience. Port from jot.sh if desired.
  *Next step:* Copy function, change session name from `jot` to `plate`.
- [ ] **§14 Q10: Auto-branch on delegation**: Parked. Observe real usage first. Revisit after 10 manual `/plate --done` cascades.
- [ ] **§14 Q11: Committable plate state**: Investigate which parts of `.plate/` should be committable for cross-machine resume.
  *Next step:* Experiment with committing `instances/*.json` and `dropped/*.patch`. Named refs require explicit `git push origin 'refs/plates/*:refs/plates/*'`.
- [ ] **§14 Q12: Terminal color tinting**: Investigate VS Code API for per-pane terminal coloring on delegation.
  *Next step:* Check `vscode.window.terminals` API and OSC escape sequences.
- [ ] **Drift detection micro-LLM call**: The drift-judge prompt exists but the actual LLM invocation (how the bg-agent calls a second LLM) is not wired. Options: (a) the bg-agent itself evaluates drift as part of its single-prompt structured output, (b) a separate tmux window for drift only.
  *Next step:* Option (a) — add a `drift_verdict` field to the bg-agent's structured JSON output.
- [ ] **Test fixtures**: Create `tests/fixtures/sample-transcript.jsonl` with realistic parentUuid dedup cases (cancel-resend, fat-finger, intentional re-type).
- [ ] **Error surface for hook crashes**: `plate.sh` has an ERR trap but the user sees only `{"decision":"block","reason":"plate crashed..."}`. Consider logging the full stack trace to `$LOG_FILE` and surfacing a shorter message.

---

*Generated by four-way AI debate (Codex + Gemini + Sonnet + Opus) — 2026-04-09.*
*Source: DESIGN.md §1–§15.*
