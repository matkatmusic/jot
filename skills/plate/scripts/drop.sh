#!/usr/bin/env bash
# drop.sh — /plate --drop: save abandoned work as patch, restore top plate (§7.4).
# Args: $1=convo_id  $2=instance_file
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPTS_DIR/.." && pwd)"
PYTHON_DIR="$PLUGIN_ROOT/python"
export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"

# shellcheck source=paths.sh
. "$SCRIPTS_DIR/paths.sh"
plate_discover_repo_root

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
TEMP_SNAPSHOT=$(hide_errors git stash create -u) || TEMP_SNAPSHOT=""

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
