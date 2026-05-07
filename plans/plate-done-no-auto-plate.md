# Plan: Remove implicit pre-push from `plate_done`

## Context

`plate_done`'s current implementation has a Step 0 that runs `plate_push(repo)` unconditionally before the cherry-pick. The intent was a convenience: if the user has uncommitted WT tweaks they forgot to `/plate`, capture them as a final plate commit. The reality: `plate_push` writes a commit whenever WT-tree differs from plate-tip-tree, in EITHER direction.

When the user has a stale checkout (WT-tree predates plate-tip-tree — e.g., they're on a different branch or rolled back), Step 0 silently writes a commit whose diff is a mass-revert of all the work the plate stack absorbed. The cherry-pick chain then ends with that revert, undoing everything.

This bit the user on 2026-05-07: running `/plate --done` on `python-migration` (HEAD=`afe138e`, May 5) when `python-migration-plate` was at `1ba6bb2` (May 7, post-monolith-deletion) restored the entire deleted monolith including `scripts/test_monolith.py`.

**Desired contract:** `--done` is purely a replay operation. It never writes plate commits. If anything is out of sync, abort and tell the user to `/plate` manually.

## New `plate_done` algorithm

1. Compute `plate_branch = <current_branch>-plate`.
2. If `plate_branch` does not exist → print warning to stderr (`"no plate branch '<plate_branch>' - nothing to do"`), return.
3. **(NEW)** If WT-tree (full WT including untracked files, via the same temp-index strategy `plate_push` uses) ≠ `plate_branch` tip-tree → print warning to stderr (`"working tree differs from <plate_branch> tip - run /plate to capture changes, then retry --done"`), return.
4. Snapshot HEAD SHA (rollback target).
5. `git reset --hard` + `git clean -fd` (Step 1, unchanged).
6. `git cherry-pick -X theirs --allow-empty HEAD..<plate_branch>` (Step 2, unchanged). On failure: abort cherry-pick, reset HEAD to snapshot, clean WT, print warning, leave `<plate_branch>` intact, return.
7. `git branch -D <plate_branch>` (Step 3, unchanged).

**No Step 0 plate_push.** No auto-plating ever.

## Critical files

- `common/scripts/plate/plate_lib.py:821` — `plate_done()` body. Replace Step 0 with the existence + tree-equality checks.
- `common/scripts/plate/plate_lib.py` — three existing `_check_plate_done_*` helpers (lines 1544, 1810, 1910) need a quick audit but should pass unchanged: today's tests set up WT to match plate tip before `plate_done`, so they were always running with a no-op Step 0. The comment at the conflict-test setup explicitly says: `"Restore WT to the plate tip's tree so plate_done's implicit pre-push is a no-op."`
- `common/scripts/plate/plate_lib.py` — add 2 new `_check_plate_done_*` helpers:
  - `_check_plate_done_aborts_when_no_plate_branch(repo, capsys)` — Step 2 abort path.
  - `_check_plate_done_aborts_when_wt_differs_from_plate_tip(repo, capsys)` — Step 3 abort path. Setup: push a plate, then dirty WT with a different file; assert plate_done warns, leaves plate branch + HEAD + WT unchanged.
- `skills/plate/tests/sequence/test_helpers.py` — add 2 new `test_plate_done_*` wrappers calling those new `_check_*` helpers.

## Reusable helpers

- `getGitTreeSHA(repo, ref)` (git_lib.py:200) — for the plate-tip-tree side of the comparison.
- For the WT-tree side: reuse `_buildFullWtTree(repo)` in plate_lib.py — already implements the temp-index full-WT capture (used by `plate_push`). Returns the tree SHA. This is the right helper because it captures untracked files too, matching what `plate_push` would have committed.
- **Tree-SHA equality is byte-identical-content equality** — git tree objects are content-addressed (SHA = hash of the canonicalized `<mode> <name>\0<sha>` entry list); same SHA ⇒ same files, same content, same modes; different SHA ⇒ different content. Same comparison cherry-pick / rebase / merge use internally for "no changes" detection.
- `checkIfGitBranchExists(repo, ref)` (git_lib.py) — Step 2 existence check.
- `getSHAForGitRefViaRevParse(repo, ref)` — for the rollback snapshot.
- `gitResetHardToHead`, `gitCleanWorkTree`, `deleteGitBranchByForce` — unchanged.

## Implementation sketch

```python
def plate_done(repo: Path, branch: Optional[str] = None) -> None:
    if branch is None:
        branch = getCurrentGitBranchName(repo)
    plateBranchName = f"{branch}-plate"

    # Existence check.
    if not checkIfGitBranchExists(repo, plateBranchName):
        print(f"warning: no plate branch '{plateBranchName}' - nothing to do",
              file=sys.stderr)
        return

    # Tree-equality check: WT must match plate tip exactly (no auto-plating).
    wt_tree = _buildFullWtTree(repo)
    plate_tip_tree = getGitTreeSHA(repo, plateBranchName)
    if wt_tree != plate_tip_tree:
        print(
            f"warning: working tree differs from '{plateBranchName}' tip - "
            f"run /plate to capture changes, then retry --done",
            file=sys.stderr,
        )
        return

    # Rollback snapshot, clean WT, cherry-pick, delete branch (unchanged).
    preHeadSha = getSHAForGitRefViaRevParse(repo, "HEAD")
    gitResetHardToHead(repo)
    gitCleanWorkTree(repo)

    completed = subprocess.run(
        ["git", "cherry-pick", "-X", "theirs", "--allow-empty",
         f"HEAD..{plateBranchName}"],
        cwd=repo, text=True, capture_output=True, check=False,
    )
    if completed.returncode != 0:
        subprocess.run(["git", "cherry-pick", "--abort"], cwd=repo,
                       text=True, capture_output=True, check=False)
        run(["git", "reset", QUIET_OUTPUT, "--hard", preHeadSha], cwd=repo)
        gitCleanWorkTree(repo)
        print(
            f"warning: cherry-pick conflict during plate_done; aborted and "
            f"restored HEAD to {preHeadSha}. Plate branch '{plateBranchName}' "
            f"preserved.",
            file=sys.stderr,
        )
        return

    deleteGitBranchByForce(repo, plateBranchName)
```

## Verification

1. `python3 -m pytest skills/plate/tests/sequence/test_helpers.py -k plate_done` — existing 3 tests still pass; 2 new tests pass.
2. `python3 -m pytest` — full suite (currently 901 passing) ends at 903 passing (901 + 2 new).

## Future test (separate change, not in this plan's scope)

End-to-end regression test for the 2026-05-07 bug, to be written later:

1. Make a repo, make 2 commits on a branch.
2. Make a change that deletes a file. Run `/plate` → `<branch>-plate` exists with the deletion captured.
3. Check out the plate commit (HEAD now on `<branch>-plate`).
4. Make a change. Run `/plate` → `<branch>-plate-plate` exists with the new change captured.
5. Run `--done`: `<branch>-plate` should now equal `<branch>-plate-plate` (plate-plate's commits cherry-picked onto plate).
6. Run `--done` again: `<branch>` should now equal `<branch>-plate` (plate's commits cherry-picked onto branch).
7. **Assert:** after the two `--done` runs, `<branch>` == `<branch>-plate-plate`'s tree. If not, the bug regressed.

## Out of scope

- Changing `plate_push` semantics (still captures WT when WT differs from parent-tree; that's its job).
- Updating any `/plate` skill scripts outside `common/scripts/plate/plate_lib.py`.
- Re-running the user's actual restored worktree state through `--done` — that's a separate manual operation (the runtime `/plate` is loaded from the main worktree, not this one).
- Documentation in `skills/plate/SKILL.md` or PLATE STATE.md (separate change).

## Risks

- **Three existing `_check_plate_done_*` tests** were written assuming Step 0 was present (or no-op). Audit: all set up WT to match plate tip before `plate_done`, so Step 0 was already a no-op in those tests. Removing it shouldn't break them. If it does, the failing assertion will pinpoint exactly which one needs adjusting.
- **Production callers expecting auto-plate behavior** — if any production code (skill scripts, hooks) relies on `plate_done` capturing uncommitted WT, those callers must add an explicit `plate_push` before the `--done` call. The `cli.py` route is the only known caller and it just dispatches the user's `/plate --done` invocation, so this is the right boundary to enforce.
