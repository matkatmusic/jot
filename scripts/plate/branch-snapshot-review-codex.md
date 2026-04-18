# `branch-snapshot.sh` Review

Finding: `branch-snapshot.sh` does not fully snapshot current code changes.

Reason: the script uses `git stash create -u` and expects `-u` to include
untracked files. For `git stash create`, `-u` is not honored like it is for
`git stash push -u`; it is treated as part of the stash message. As a result,
tracked edits are captured, but untracked non-ignored files are omitted from the
snapshot commit placed on `<current>-plate`.

This violates the stated goal of taking a snapshot of the current code changes
without modifying the working tree or switching branches, because newly created
files are part of the working tree state but are not included in the snapshot.

Suggested fix: replace the `git stash create -u` snapshot step with a temporary
index. Seed the temporary index from `HEAD`, add the working tree into that
temporary index, write a tree from it, and commit that tree with `git
commit-tree`. This captures tracked edits, deletions, and untracked non-ignored
files without touching the user's real index, working tree, or branch.

```bash
TOP=$(git rev-parse --show-toplevel)
TMP_INDEX=$(mktemp "${TMPDIR:-/tmp}/plate-index.XXXXXX")

cleanup_tmp_index() {
  rm -f "$TMP_INDEX" "$TMP_INDEX.lock"
}
trap cleanup_tmp_index EXIT

HEAD_TREE=$(git rev-parse HEAD^{tree})

GIT_INDEX_FILE="$TMP_INDEX" git -C "$TOP" read-tree HEAD
GIT_INDEX_FILE="$TMP_INDEX" git -C "$TOP" add -A -- .
TREE=$(GIT_INDEX_FILE="$TMP_INDEX" git -C "$TOP" write-tree)

if [ "$TREE" = "$HEAD_TREE" ]; then
  echo "[plate] working tree clean -- nothing to snapshot" >&2
  exit 3
fi
```

Then remove the existing `SNAP=$(git stash create -u ...)` block and the later
`TREE=$(git rev-parse "${SNAP}^{tree}")` line.

Caveat: this approach snapshots the working tree contents. If the real index has
staged content that differs from the file currently on disk, the snapshot will
capture the file on disk, not the separately staged version. That matches the
current script's use of the stash commit tree, but the intended semantics should
be made explicit if staged-only content needs different treatment.
