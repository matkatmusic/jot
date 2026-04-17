# Issue with `branch-snapshot.sh`

## The Problem
The script fails to capture a complete snapshot of all current code changes because it incorrectly attempts to use `git stash create -u` to include untracked files. The `git stash create` plumbing command does not support the `-u` (or `--include-untracked`) flag; instead, it interprets the `-u` string as the stash commit's message. 

Consequently, any newly created (untracked) files are completely excluded from the snapshot tree. If the working tree contains *only* untracked files, the script will incorrectly abort with the error `working tree clean — nothing to snapshot`.

## The Solution
A clean and robust way to snapshot the exact state of the working tree (including all untracked files) without mutating the actual git index or the working tree is to use a temporary git index file.

By copying the current index, overriding the `GIT_INDEX_FILE` environment variable, adding all files (`git add -A`), and writing the tree (`git write-tree`), you can get a complete snapshot tree exactly as it is on disk. 

### Implementation Fix
Replace the `git stash create` step (lines 40-47):
```bash
# ── 1. Snapshot working tree as a commit (tree untouched) ────────────────
# `-u` includes untracked (but not gitignored) files so new files created
# during a plate session get captured alongside edits to tracked files.
SNAP=$(git stash create -u 2>/dev/null || true)

if [ -z "$SNAP" ]; then
  echo "[plate] working tree clean — nothing to snapshot" >&2
  exit 3
fi

# ── 2. Build the plate commit ────────────────────────────────────────────
TREE=$(git rev-parse "${SNAP}^{tree}")
```

With this temporary index approach:

```bash
# ── 1. Snapshot working tree as a tree object (untouched) ────────────────
# Use a temporary index to stage all changes (including untracked files) 
# and write a tree. This ensures we don't modify the user's actual git 
# index or working tree.
export GIT_INDEX_FILE="$(git rev-parse --git-dir)/index.plate-tmp-$$"
cp "$(git rev-parse --git-dir)/index" "$GIT_INDEX_FILE" 2>/dev/null || true

# Add all files (tracked modifications and untracked files)
git add -A

# Write the temporary index to a tree object
TREE=$(git write-tree)

# Clean up the temporary index
rm -f "$GIT_INDEX_FILE"
unset GIT_INDEX_FILE

# Check if the tree is identical to HEAD's tree (meaning nothing changed)
HEAD_TREE=$(git rev-parse HEAD^{tree})
if [ "$TREE" = "$HEAD_TREE" ]; then
  echo "[plate] working tree clean — nothing to snapshot" >&2
  exit 3
fi
```
