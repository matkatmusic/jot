#!/usr/bin/env bash
# branch-snapshot.sh — Commit the current working tree as a new plate commit
# on the "<current-branch>-plate" branch, without switching branches or
# modifying the working tree in any way.
#
# Replaces the old `git stash create` + `git update-ref refs/plates/...`
# primitive with a real branch the user can inspect via normal git tooling
# (gitk, git log, GitHub's branch view, etc.).
#
# Three git commands do the work:
#   1. `git stash create`      — snapshot working tree as a dangling commit.
#                                Does not modify HEAD, index, or working tree.
#   2. `git commit-tree`       — create a new commit whose tree is the
#                                snapshot's tree and whose parent is the
#                                previous plate-branch tip (or current
#                                branch HEAD on first invocation).
#   3. `git update-ref`        — advance refs/heads/<plate-branch> to the
#                                new commit.
#
# Args:
#   $1  commit message                  (required)
#   $2  plate branch name               (optional, default: <current>-plate)
#
# Stdout: the new commit SHA (for callers that want to record it)
#
# Exit codes:
#   0  ok
#   1  not in a git repo
#   2  detached HEAD (no current-branch name to derive plate-branch from)
#   3  working tree clean — nothing to snapshot
set -euo pipefail

# shellcheck source=../../../common/scripts/silencers.sh
. "${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/../../.." && pwd)}/common/scripts/silencers.sh"

MSG="${1:?usage: branch-snapshot.sh <commit-message> [plate-branch-name]}"

# ── Require a git repo ───────────────────────────────────────────────────
git rev-parse --git-dir >/dev/null 2>&1 || {
  echo "[plate] not inside a git repository" >&2
  exit 1
}

# ── Discover current branch (refuse detached HEAD) ──────────────────────
CURRENT_BRANCH=$(hide_errors git symbolic-ref --short HEAD) || CURRENT_BRANCH=""
if [ -z "$CURRENT_BRANCH" ]; then
  echo "[plate] HEAD is detached — cannot derive plate-branch name" >&2
  exit 2
fi

PLATE_BRANCH="${2:-${CURRENT_BRANCH}-plate}"

# ── 1. Snapshot working tree as a commit (tree untouched) ────────────────
# `-u` includes untracked (but not gitignored) files so new files created
# during a plate session get captured alongside edits to tracked files.
SNAP=$(hide_errors git stash create -u) || SNAP=""

if [ -z "$SNAP" ]; then
  echo "[plate] working tree clean — nothing to snapshot" >&2
  exit 3
fi

# ── 2. Build the plate commit ────────────────────────────────────────────
TREE=$(git rev-parse "${SNAP}^{tree}")

# Parent: previous plate-branch tip if it exists, else current branch HEAD.
# This chains plate commits linearly so `--done` can cherry-pick them in
# order, and so `git log <plate-branch>` shows the full plate history.
if git rev-parse --verify --quiet "refs/heads/${PLATE_BRANCH}" >/dev/null; then
  PARENT=$(git rev-parse "refs/heads/${PLATE_BRANCH}")
  EXPECTED_OLD="$PARENT"
else
  PARENT=$(git rev-parse HEAD)
  EXPECTED_OLD=""   # branch does not exist yet
fi

# `git commit-tree` reads the commit message from stdin.
NEW=$(printf '%s\n' "$MSG" | git commit-tree "$TREE" -p "$PARENT")

# ── 3. Advance the plate branch ──────────────────────────────────────────
# When the branch already exists, pass EXPECTED_OLD so update-ref fails if
# someone else advanced it concurrently (mkdir-lock caller-side still
# prevents this, but belt-and-suspenders is cheap).
if [ -n "$EXPECTED_OLD" ]; then
  git update-ref "refs/heads/${PLATE_BRANCH}" "$NEW" "$EXPECTED_OLD"
else
  git update-ref "refs/heads/${PLATE_BRANCH}" "$NEW"
fi

# ── Emit the new SHA so callers can record it in the instance JSON ──────
printf '%s\n' "$NEW"
