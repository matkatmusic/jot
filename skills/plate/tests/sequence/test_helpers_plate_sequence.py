"""Plate-operation sequence specs (test_sequence_NN_*).

Split from test_helpers.py per MIGRATION_TO_PYTHON.md bucket [plate sequence].
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

# After the test_* functions migrated out of plate_lib.py, every library
# symbol the tests reference must be importable into this namespace —
# including underscore-prefixed scenario callables (`_check_*`) and
# private helpers (`_writeFakeTranscriptWithToolUse`, etc.) that
# `from plate_lib import *` would skip. Pull them in explicitly via vars().
# (sys.path setup already done by conftest.py.)
import plate_lib as _plate_lib
from common.scripts.git_lib import (
    getCurrentGitBranchName
)

import test_plate_scenarios as _plate_scenarios
from test_plate_scenarios import (
    _check_plate_push_creates_branch_capturing_wip,
)

globals().update({
    name: value
    for name, value in vars(_plate_scenarios).items()
    if name.startswith("_check_") or name.startswith("_build") or name.startswith("_write")
})

globals().update({
    name: value
    for name, value in vars(_plate_lib).items()
    if not name.startswith("__")
})


# ── plate operation sequence specs ───────────────────────────────────

def test_sequence_01_plate_push_first_time_preserves_user_workspace(repo: Path) -> None:
    # 1. User starts on a non-main branch with no plate branch.
    # 2. User edits a tracked file and creates an untracked file.
    # 3. User runs plate_push(repo).
    # 4. Plate branch is created parented to HEAD, captures both edits,
    #    returns its tip SHA, and leaves WT/HEAD/branch unchanged.
    _check_plate_push_creates_branch_capturing_wip(repo)


def test_sequence_02_plate_push_second_time_extends_plate_stack(repo: Path) -> None:
    branch = getCurrentGitBranchName(repo)
    plateBranchName = f"{branch}-plate"
    head_before = getSHAForGitRefViaRevParse(repo, "HEAD")

    # 1. Edit A: modify a tracked file. Run plate_push → P1.
    (repo / TEST_FILENAME).write_text("edit A\n")
    p1_sha = plate_push(repo)
    assert p1_sha is not None
    assert getSHAForGitRefViaRevParse(repo, plateBranchName) == p1_sha

    # 2. Edit B: keep working — append more changes on top of the visible WT.
    (repo / TEST_FILENAME).write_text("edit A\nedit B\n")
    untracked_b = createUntrackedFile(repo, random.Random())["file"]

    # 3. Second plate_push → P2.
    p2_sha = plate_push(repo)

    # 4a. P2 parents to P1 (chain extension, not a fresh root).
    assert p2_sha is not None
    assert p2_sha != p1_sha
    assert run(["git", "rev-parse", f"{plateBranchName}~1"], cwd=repo) == p1_sha
    # 4b. <branch>-plate advances to P2.
    assert getSHAForGitRefViaRevParse(repo, plateBranchName) == p2_sha
    # 4c. Latest plate tree captures the current WT (both edit B and untracked).
    plate_files = run(
        ["git", "ls-tree", "-r", "--name-only", plateBranchName], cwd=repo
    ).splitlines()
    assert untracked_b in plate_files
    plate_tip_a_txt = run(
        ["git", "show", f"{plateBranchName}:{TEST_FILENAME}"], cwd=repo
    )
    assert plate_tip_a_txt == "edit A\nedit B"
    # 4d. Branch HEAD and WT unchanged.
    assert getSHAForGitRefViaRevParse(repo, "HEAD") == head_before
    assert (repo / TEST_FILENAME).read_text() == "edit A\nedit B\n"
    assert untracked_b in getGitUntrackedFilesList(repo)


def test_sequence_03_plate_done_replays_stack_and_cleans_workspace(repo: Path) -> None:
    # 1. User creates P1 with edit A.
    # 2. User creates P2 with edit B.
    # 3. User runs plate_done(repo).
    # 4. Branch receives both plate commits oldest-first, plate ref deleted,
    #    WT clean, branch tree == former P2 tree.
    _check_plate_done_replays_stack(repo)


def test_sequence_04_plate_done_aborts_when_unpushed_work_exists(
    repo: Path, capsys
) -> None:
    # Sequence-fixture variant of the per-function abort-on-WT-divergence
    # contract: plate_done is pure replay and must refuse to run when the
    # WT has uncommitted work that would be destroyed by Step 1's clean.
    # The user is expected to /plate the divergence first, then retry.
    branch = getCurrentGitBranchName(repo)
    plateBranchName = f"{branch}-plate"
    branch_count_before = countGitCommitsReachableFromRef(repo, branch)

    # 1. Edit A: create untracked file U_A, push as P1.
    u_a = createUntrackedFile(repo, random.Random())["file"]
    plate_push(repo)
    assert checkIfGitBranchExists(repo, plateBranchName)
    plate_tip_before = getSHAForGitRefViaRevParse(repo, plateBranchName)

    # 2. Edit B: create untracked file U_B but DO NOT plate_push it.
    u_b = createUntrackedFile(repo, random.Random())["file"]

    # 3. plate_done sees WT-tree (with U_B) != plate-tip-tree and must abort.
    plate_done(repo)

    captured = capsys.readouterr()
    # 4a. Warning emitted naming the plate branch.
    assert "working tree differs" in captured.err
    assert plateBranchName in captured.err
    # 4b. Plate branch preserved at its pre-call SHA.
    assert checkIfGitBranchExists(repo, plateBranchName)
    assert getSHAForGitRefViaRevParse(repo, plateBranchName) == plate_tip_before
    # 4c. Branch HEAD did not advance (no commits applied).
    assert countGitCommitsReachableFromRef(repo, branch) == branch_count_before
    # 4d. Both untracked files preserved in WT for the user to /plate next.
    untracked = getGitUntrackedFilesList(repo)
    assert u_a in untracked
    assert u_b in untracked


def test_sequence_05_plate_drop_removes_top_plate_only(repo: Path) -> None:
    branch = getCurrentGitBranchName(repo)
    plateBranchName = f"{branch}-plate"

    rng = random.Random()
    # 1. P1: edit A — create untracked U_A, push.
    u_a = createUntrackedFile(repo, rng)["file"]
    plate_push(repo)
    p1_sha = getSHAForGitRefViaRevParse(repo, plateBranchName)

    # 2. P2: edit B — create untracked U_B, push.
    u_b = createUntrackedFile(repo, rng)["file"]
    p2_sha = plate_push(repo)
    assert getSHAForGitRefViaRevParse(repo, plateBranchName) == p2_sha

    # 3. plate_drop — should rewind, NOT delete (multi-plate stack).
    session_dir = plate_drop(repo)

    # 4a. Session dir written under .plate/trash/<branch>/<ts>_dropped_<sha>/.
    assert session_dir is not None
    assert session_dir.is_dir()
    assert session_dir.parent.name == branch
    assert session_dir.parent.parent.name == "trash"
    assert "_dropped_" in session_dir.name
    patch_path = session_dir / "plate_001.patch"
    assert patch_path.exists()
    # 4b. <branch>-plate rewinds to P1 (still exists, not deleted).
    assert checkIfGitBranchExists(repo, plateBranchName)
    assert getSHAForGitRefViaRevParse(repo, plateBranchName) == p1_sha
    # 4c. WT unchanged — both untracked files still present.
    assert (repo / u_a).exists()
    assert (repo / u_b).exists()
    untracked = getGitUntrackedFilesList(repo)
    assert u_a in untracked
    assert u_b in untracked
    # 4d. The dropped top plate is recoverable — the patch references the
    #     top plate's distinguishing file (U_B).
    assert u_b in patch_path.read_text()


def test_sequence_06_plate_drop_single_plate_deletes_stack(repo: Path) -> None:
    # 1. User creates a single plate P1.
    # 2. User runs plate_drop(repo).
    # 3. Patch saved under .plate/dropped/, plate branch deleted, WT untouched.
    _check_plate_drop_deletes_last_plate(repo)


def test_sequence_07_applyGitPatch_recovers_dropped_plate_work(repo: Path) -> None:
    # 1. User creates a single plate P1.
    # 2. User runs plate_drop(repo) and keeps the generated patch path.
    # 3. User resets/cleans the repo back to branch HEAD.
    # 4. User runs applyGitPatch(repo, patch).
    # 5. WT contains the dropped plate work again byte-for-byte.
    _check_plate_drop_then_applyGitPatch_round_trip(repo)


def test_sequence_08_plate_trash_deletes_stack_but_leaves_workspace_by_default(
    repo: Path,
) -> None:
    # 1. User creates P1 with edit A.
    # 2. User creates P2 with edit B.
    # 3. User runs plate_trash(repo) with default clean_wt=False.
    # 4. Per-plate patches saved under .plate/trashed/<...>/, plate ref
    #    deleted, WT untouched (recycle data is per-plate to preserve
    #    commit boundaries).
    _check_plate_trash_default_preserves_wt(repo)


def test_sequence_09_plate_trash_clean_mode_resets_workspace(repo: Path) -> None:
    # 1. User creates a dirty 2-plate stack (tracked edit + untracked files).
    # 2. User runs plate_trash(repo, clean_wt=True).
    # 3. Patches saved before cleanup, plate ref deleted, WT wiped (tracked
    #    file restored, untracked files removed), branch HEAD unchanged.
    _check_plate_trash_clean_resets_wt(repo)


def test_sequence_10_plate_recycle_restores_latest_trashed_stack(repo: Path) -> None:
    # 1. User creates P1 and P2.
    # 2. User runs plate_trash(repo), deleting <branch>-plate.
    # 3. User runs plate_recycle(repo).
    # 4. Plate branch exists again with same commit count, tip tree SHA
    #    equals the original trashed tip tree, branch HEAD unchanged.
    _check_plate_recycle_restores_stack(repo)


# test_sequence_11 (plate_carry) removed — plate_carry was deprecated in
# favor of plate_next (list/jump navigator). plate_next subsumes carry's
# job with better UX (index-based selection, automatic resume command,
# WIP-on-parent-branch landing state).


def test_sequence_12_derived_agent_first_child_records_parent_trailers(
    repo: Path,
) -> None:
    # 1. User creates parent <branch>-plate.
    # 2. A new agent starts from that parent via simulate_derived_agent().
    # 3. New branch is <parent_plate>-derived1, parented to plate tip,
    #    with parent-plate and convo-id trailers.
    _check_first_derived_agent_records_trailers(repo)


def test_sequence_13_derived_agent_second_child_extends_linear_chain(
    repo: Path,
) -> None:
    # 1. User creates parent <branch>-plate.
    # 2. User creates derived1 with convo ID A.
    # 3. User creates derived2 with convo ID B.
    # 4. derived2 is named <parent_plate>-derived2, parents to derived1 tip,
    #    parent-convo trailer == A, derived1 untouched.
    _check_second_derived_agent_extends_chain(repo)


# test_sequence_14 (old plate_next derived-chain behavior) removed —
# plate_next semantics changed to sibling-plate navigation. New integration
# test sequences for plate_next added below.


def test_sequence_21_plate_next_list_shows_plates_sorted_with_current_marker(
    repo: Path,
) -> None:
    # 1. User pushes a plate from main (convo "alpha work").
    # 2. After a 1s gap, switches to a new feature-y branch off main and
    #    pushes another plate (convo "beta work").
    # 3. User runs plate_next(repo) with no index → list mode.
    # 4. Returned string has two lines, newest first:
    #      - line 1 = `1. \`beta work\` (current)  age: <age>`
    #      - line 2 = `2. \`alpha work\` age: <age>`
    #    Marker fires only on the entry whose ref equals
    #    `<currentBranch>-plate` (feature-y-plate).
    _check_plate_next_list_shows_plates_sorted_with_current_marker(repo)


# ── error-path sequence specs ────────────────────────────────────────


def test_sequence_15_plate_drop_with_no_plate_branch_warns_and_exits(
    repo: Path, capsys
) -> None:
    # 1. User has a clean working branch with no plate branch yet.
    # 2. User runs plate_drop(repo) by mistake.
    # 3. plate_drop emits "no plate branch — nothing to drop" on stderr,
    #    returns None, creates no .plate/dropped/ directory, leaves WT
    #    and HEAD unchanged.
    _check_plate_drop_no_branch_warns_and_exits(repo, capsys)


def test_sequence_16_plate_trash_with_no_plate_branch_warns_and_exits(
    repo: Path, capsys
) -> None:
    # 1. User has a clean working branch with no plate branch yet.
    # 2. User runs plate_trash(repo) by mistake.
    # 3. plate_trash emits "no plate branch — nothing to trash" on stderr,
    #    returns None, creates no .plate/trashed/ directory, leaves HEAD
    #    unchanged.
    _check_plate_trash_no_branch_warns_and_exits(repo, capsys)


def test_sequence_17_plate_recycle_with_no_trashed_session_warns_and_exits(
    repo: Path, capsys
) -> None:
    # 1. User has a clean working branch with no .plate/trashed/ history.
    # 2. User runs plate_recycle(repo) by mistake.
    # 3. plate_recycle emits "nothing to recycle" on stderr, returns None,
    #    creates no plate branch, leaves HEAD unchanged.
    _check_plate_recycle_no_branch_warns_and_exits(repo, capsys)


def test_sequence_18_plate_done_resolves_content_conflict_in_plate_favor(
    repo: Path, capsys
) -> None:
    # 1. User edits a tracked file and plate_pushes (P1 captures "plate
    #    version").
    # 2. User resets WT and commits a parent-branch edit ("branch version")
    #    on the working branch HEAD that overlaps the same line.
    # 3. User runs plate_done(repo). Cherry-pick uses -X theirs, so the
    #    plate's version wins the content overlap.
    # 4. plate_done advances HEAD with the plate commit applied on top,
    #    deletes <branch>-plate, leaves no CHERRY_PICK_HEAD, emits no
    #    conflict warning. The plate tip's working state is preserved
    #    because it represents the verified, tested code state.
    _check_plate_done_resolves_content_conflict_in_plate_favor(repo, capsys)


def test_sequence_19_drop_patch_is_portable_across_repos(tmp_path: Path) -> None:
    # 1. Two separate clones (repoA and repoB) of the same project, both
    #    sharing the same TEST_FILENAME content at HEAD.
    # 2. In repoA: edit TEST_FILENAME, create an untracked file, plate_push,
    #    plate_drop → produces a portable .patch file.
    # 3. The .patch file is copied into repoB (e.g., emailed to a teammate).
    # 4. In repoB: applyGitPatch(repoB, patch) restores the dropped edits
    #    byte-for-byte — both the tracked modification and the untracked
    #    file land cleanly with no merge markers.
    repoA = setup_repo(tmp_path / "a")
    repoB = setup_repo(tmp_path / "b")
    _check_drop_patch_applies_in_fresh_repo(repoA, repoB)


def test_sequence_20_plate_done_leaves_sha_recoverable_after_branch_delete(
    repo: Path,
) -> None:
    # 1. User creates a single plate (P1) with an untracked file.
    # 2. User runs plate_done(repo) → cherry-pick replays P1, plate branch
    #    is force-deleted.
    # 3. The plate tip SHA is still resolvable from the object database
    #    (recoverable until git gc). Documents the invariant — would catch
    #    a future regression that introduces immediate gc/prune.
    _check_plate_done_leaves_sha_recoverable(repo)
