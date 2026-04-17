#!/usr/bin/env bash
# branch-snapshot.v2.sh — FIX for branch-snapshot.sh.
#
# BUG in v1: used `git stash create -u "$MSG"`. `git stash create` does NOT
# accept `-u` / `--include-untracked`; that subcommand's only positional
# argument is the message. So `git stash create -u "$MSG"` treated `-u` as
# the message and `"$MSG"` as a pathspec, silently producing a tracked-only
# snapshot (or erroring on the pathspec). Untracked files were NEVER captured.
#
# FIX: skip `git stash create` entirely. Build the snapshot tree by:
#   1. Using a temporary index file (via GIT_INDEX_FILE env var)
#   2. Seeding it with HEAD's tree
#   3. `git add -A` to layer ALL working-tree state on top (tracked edits +
#      previously-staged changes + untracked files, while still respecting
#      .gitignore)
#   4. `git write-tree` to emit the tree SHA
#
# The real .git/index is never touched. The real working tree is never
# touched. Result is functionally equivalent to what `git stash create -u`
# would do IF it accepted `-u` — a snapshot of the full on-disk state.
#
# Args:
#   $1  commit message                  (required)
#   $2  plate branch name               (optional, default: <current>-plate)
#
# Stdout: the new commit SHA
# Exit codes: 0 ok | 1 not a git repo | 2 detached HEAD | 3 tree unchanged
set -euo pipefail

# shellcheck source=../../../scripts/lib/invoke_command.sh
. "${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/../../.." && pwd)}/scripts/lib/invoke_command.sh"

MSG="${1:?usage: branch-snapshot.v2.sh <commit-message> [plate-branch-name]}"

# ── Require a git repo ───────────────────────────────────────────────────
git rev-parse --git-dir >/dev/null 2>&1 || {
  echo "[plate] not inside a git repository" >&2
  exit 1
}

# ── Refuse detached HEAD ────────────────────────────────────────────────
CURRENT_BRANCH=$(hide_errors git symbolic-ref --short HEAD) || CURRENT_BRANCH=""
if [ -z "$CURRENT_BRANCH" ]; then
  echo "[plate] HEAD is detached — cannot derive plate-branch name" >&2
  exit 2
fi

PLATE_BRANCH="${2:-${CURRENT_BRANCH}-plate}"

# ── 1. Build the snapshot tree via a temporary index ─────────────────────
# Env-scope the temp index so git's read-tree / add / write-tree operate
# on it instead of the real .git/index. The real index and working tree
# are untouched throughout.
TMP_INDEX=$(mktemp -t plate-index.XXXXXX)
trap 'rm -f "$TMP_INDEX"' EXIT

# Seed the temp index with HEAD's tree so previously-committed state is
# recorded and `git add -A` can compute a correct delta.
GIT_INDEX_FILE="$TMP_INDEX" git read-tree HEAD

# Stage everything: tracked edits, previously-staged changes, and any
# currently-untracked files (still honoring .gitignore). --force is safe
# here — it only affects the temp index, not the real one.
GIT_INDEX_FILE="$TMP_INDEX" git add -A --force

# Emit the tree SHA for that in-memory index.
TREE=$(GIT_INDEX_FILE="$TMP_INDEX" git write-tree)

# ── 2. Determine parent ─────────────────────────────────────────────────
if git rev-parse --verify --quiet "refs/heads/${PLATE_BRANCH}" >/dev/null; then
  PARENT=$(git rev-parse "refs/heads/${PLATE_BRANCH}")
  EXPECTED_OLD="$PARENT"
else
  PARENT=$(git rev-parse HEAD)
  EXPECTED_OLD=""
fi

# If the snapshot tree exactly matches the parent's tree, there's nothing
# new to record. Skip rather than chain an empty commit.
PARENT_TREE=$(git rev-parse "${PARENT}^{tree}")
if [ "$TREE" = "$PARENT_TREE" ]; then
  echo "[plate] no changes since parent commit — nothing to snapshot" >&2
  exit 3
fi

# ── 3. Build the plate commit ───────────────────────────────────────────
NEW=$(printf '%s\n' "$MSG" | git commit-tree "$TREE" -p "$PARENT")

# ── 4. Advance the plate branch (CAS when advancing an existing branch) ─
if [ -n "$EXPECTED_OLD" ]; then
  git update-ref "refs/heads/${PLATE_BRANCH}" "$NEW" "$EXPECTED_OLD"
else
  git update-ref "refs/heads/${PLATE_BRANCH}" "$NEW"
fi

printf '%s\n' "$NEW"
