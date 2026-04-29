"""Smoke tests and sequence specs for the /plate test helpers.

The setup_repo() and random_edit() tests verify implemented helpers.
The test_sequence_* functions are failing workflow stubs for the plate
operation helpers; each one describes the user sequence it must cover.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from helpers import (
    branchExists,
    commit_count,
    getCommitSubject,
    getCurrentBranchName,
    is_clean_wt,
    random_edit,
    status_porcelain,
    getTreeSHA,
)


# ── setup_repo ────────────────────────────────────────────────────────

def test_setup_repo_checks_out_non_main_branch(repo: Path) -> None:
    """Working branch is randomized but is never 'main'."""
    branch = getCurrentBranchName(repo)
    assert branch
    assert branch != "main"


def test_setup_repo_branch_name_is_varied(tmp_path: Path) -> None:
    """Two fresh repos in succession should pick different branch names."""
    from helpers import setup_repo

    seen = set()
    for i in range(10):
        r = setup_repo(tmp_path / f"r{i}")
        seen.add(getCurrentBranchName(r))
    # Variance means we shouldn't always get the same name 10 times.
    assert len(seen) > 1


def test_setup_repo_creates_three_commits(repo: Path) -> None:
    assert commit_count(repo, "HEAD") == 3


def test_setup_repo_main_has_one_commit(repo: Path) -> None:
    assert commit_count(repo, "main") == 1


def test_setup_repo_starts_clean(repo: Path) -> None:
    assert is_clean_wt(repo)


def test_setup_repo_creates_expected_files(repo: Path) -> None:
    assert (repo / "a.txt").read_text() == "A\n"
    assert (repo / "b.txt").read_text() == "B\n"
    assert (repo / "fix.txt").read_text() == "F1\n"


def test_setup_repo_has_expected_subjects(repo: Path) -> None:
    assert getCommitSubject(repo, "HEAD") == "F1"
    assert getCommitSubject(repo, "HEAD~1") == "B"
    assert getCommitSubject(repo, "main") == "A"


def test_setup_repo_diverges_from_main(repo: Path) -> None:
    """The working branch and main share an ancestor (A) but diverge:
    main has neither b.txt nor fix.txt."""
    assert getTreeSHA(repo, "main") != getTreeSHA(repo, "HEAD")


def test_setup_repo_no_plate_branch_initially(repo: Path) -> None:
    plate = f"{getCurrentBranchName(repo)}-plate"
    assert not branchExists(repo, plate)


# ── random_edit ───────────────────────────────────────────────────────

def test_random_edit_dirties_wt(repo: Path) -> None:
    assert is_clean_wt(repo)
    random_edit(repo, seed=0)
    assert not is_clean_wt(repo)


def test_random_edit_returns_action_record(repo: Path) -> None:
    result = random_edit(repo, seed=0)
    assert result["action"] in ("modify_tracked", "create_untracked")
    assert "file" in result


def test_random_edit_modify_tracked_appends_line(repo: Path) -> None:
    """With a seed that picks modify_tracked, the file gains a line."""
    # Drive enough seeds to hit modify_tracked at least once.
    for s in range(50):
        before = (repo / "fix.txt").read_text()
        result = random_edit(repo, seed=s)
        if result["action"] == "modify_tracked" and result["file"] == "fix.txt":
            after = (repo / "fix.txt").read_text()
            assert after.startswith(before)
            assert len(after) > len(before)
            return
    pytest.skip("seed range did not produce a modify_tracked of fix.txt")


def test_random_edit_create_untracked_makes_new_file(repo: Path) -> None:
    """With a seed that picks create_untracked, a new file appears in WT."""
    for s in range(50):
        files_before = set(p.name for p in repo.iterdir() if p.is_file())
        result = random_edit(repo, seed=s)
        if result["action"] == "create_untracked":
            files_after = set(p.name for p in repo.iterdir() if p.is_file())
            new_files = files_after - files_before
            assert result["file"] in new_files
            assert (repo / result["file"]).read_text().startswith("content-")
            return
    pytest.skip("seed range did not produce a create_untracked")


def test_random_edit_seeded_is_deterministic(repo: Path, tmp_path: Path) -> None:
    """Same seed → same action."""
    a = random_edit(repo, seed=12345)
    # Reset by setting up a parallel repo from the same fixture base
    from helpers import setup_repo

    other = setup_repo(tmp_path / "other")
    b = random_edit(other, seed=12345)
    assert a == b


def test_random_edit_unseeded_works(repo: Path) -> None:
    """No seed → still produces a valid edit (non-deterministic)."""
    result = random_edit(repo)
    assert result["action"] in ("modify_tracked", "create_untracked")
    assert not is_clean_wt(repo)


# ── plate operation sequence specs ───────────────────────────────────

def test_sequence_01_plate_push_first_time_preserves_user_workspace(repo: Path) -> None:
    # Sequence:
    # 1. User starts in a fresh repo on a non-main branch with no plate branch.
    # 2. User edits a tracked file and creates an untracked file.
    # 3. User runs plate_push(repo).
    # 4. Test verifies <branch>-plate is created from the original HEAD,
    #    captures both edits, returns its tip SHA, and leaves the current
    #    branch, real index, and visible WT unchanged.
    pytest.fail("TODO: implement sequence 01")


def test_sequence_02_plate_push_second_time_extends_plate_stack(repo: Path) -> None:
    # Sequence:
    # 1. User makes edit A and runs plate_push(repo), creating P1.
    # 2. User keeps working and makes edit B on top of the visible WT.
    # 3. User runs plate_push(repo) again, creating P2.
    # 4. Test verifies P2 parents to P1, <branch>-plate advances, the latest
    #    plate tree matches the current WT, and branch/WT remain unchanged.
    pytest.fail("TODO: implement sequence 02")


def test_sequence_03_plate_done_replays_stack_and_cleans_workspace(repo: Path) -> None:
    # Sequence:
    # 1. User creates P1 with edit A.
    # 2. User creates P2 with edit B.
    # 3. User runs plate_done(repo).
    # 4. Test verifies the user branch receives the two plate commits
    #    oldest-first, <branch>-plate is deleted, WT is clean, and the final
    #    branch tree equals the former P2 tree.
    pytest.fail("TODO: implement sequence 03")


def test_sequence_04_plate_done_captures_unpushed_work_before_cleanup(repo: Path) -> None:
    # Sequence:
    # 1. User creates P1 with edit A.
    # 2. User makes edit B but does not run plate_push(repo).
    # 3. User runs plate_done(repo).
    # 4. Test verifies the implicit pre-done capture preserves edit B before
    #    reset/clean, the branch receives both commits, <branch>-plate is
    #    deleted, and WT is clean.
    pytest.fail("TODO: implement sequence 04")


def test_sequence_05_plate_drop_removes_top_plate_only(repo: Path) -> None:
    # Sequence:
    # 1. User creates P1 with edit A.
    # 2. User creates P2 with edit B.
    # 3. User runs plate_drop(repo).
    # 4. Test verifies a patch file is written, <branch>-plate rewinds to P1,
    #    WT is unchanged, and the dropped top plate remains recoverable from
    #    the patch.
    pytest.fail("TODO: implement sequence 05")


def test_sequence_06_plate_drop_single_plate_deletes_stack(repo: Path) -> None:
    # Sequence:
    # 1. User creates a single plate P1.
    # 2. User runs plate_drop(repo).
    # 3. Test verifies a patch file is written, <branch>-plate is deleted,
    #    and WT is unchanged.
    pytest.fail("TODO: implement sequence 06")


def test_sequence_07_apply_patch_recovers_dropped_plate_work(repo: Path) -> None:
    # Sequence:
    # 1. User creates a single plate P1.
    # 2. User runs plate_drop(repo) and keeps the generated patch path.
    # 3. User resets/cleans the repo back to branch HEAD.
    # 4. User runs apply_patch(repo, patch).
    # 5. Test verifies the WT contains the dropped plate work again.
    pytest.fail("TODO: implement sequence 07")


def test_sequence_08_plate_trash_deletes_stack_but_leaves_workspace_by_default(
    repo: Path,
) -> None:
    # Sequence:
    # 1. User creates P1 with edit A.
    # 2. User creates P2 with edit B.
    # 3. User runs plate_trash(repo) with default clean_wt=False.
    # 4. Test verifies a combined patch is written, recycle data is available
    #    for preserving plate boundaries, <branch>-plate is deleted, and WT is
    #    unchanged.
    pytest.fail("TODO: implement sequence 08")


def test_sequence_09_plate_trash_clean_mode_resets_workspace(repo: Path) -> None:
    # Sequence:
    # 1. User creates a dirty plate stack.
    # 2. User runs plate_trash(repo, clean_wt=True).
    # 3. Test verifies the patch is written before cleanup, <branch>-plate is
    #    deleted, WT is clean, and the user branch HEAD has not received plate
    #    commits.
    pytest.fail("TODO: implement sequence 09")


def test_sequence_10_plate_recycle_restores_latest_trashed_stack(repo: Path) -> None:
    # Sequence:
    # 1. User creates P1 and P2.
    # 2. User runs plate_trash(repo), deleting <branch>-plate.
    # 3. User runs plate_recycle(repo).
    # 4. Test verifies <branch>-plate exists again, has the same number of
    #    plate commits, its tip tree equals the original trashed tip tree, and
    #    user branch HEAD is unchanged.
    pytest.fail("TODO: implement sequence 10")


def test_sequence_11_plate_carry_sets_down_wip_before_checkout(repo: Path) -> None:
    # Sequence:
    # 1. User creates a target plate branch.
    # 2. User returns to the source branch and makes dirty WIP.
    # 3. User runs plate_carry(repo, target_plate).
    # 4. Test verifies source <branch>-plate captures the WIP before checkout,
    #    current branch becomes target_plate, and no WIP is silently lost.
    pytest.fail("TODO: implement sequence 11")


def test_sequence_12_derived_agent_first_child_records_parent_trailers(
    repo: Path,
) -> None:
    # Sequence:
    # 1. User creates parent <branch>-plate.
    # 2. A new agent starts from that parent via simulate_derived_agent().
    # 3. Test verifies the new branch is <parent_plate>-derived1, its first
    #    commit parents to the parent plate tip, and trailers record
    #    parent-plate and convo-id.
    pytest.fail("TODO: implement sequence 12")


def test_sequence_13_derived_agent_second_child_extends_linear_chain(
    repo: Path,
) -> None:
    # Sequence:
    # 1. User creates parent <branch>-plate.
    # 2. User creates derived1 with convo ID A.
    # 3. User creates derived2 with convo ID B.
    # 4. Test verifies derived2 is named <parent_plate>-derived2, parents to
    #    derived1 tip, records the immediate parent state, and leaves derived1
    #    intact.
    pytest.fail("TODO: implement sequence 13")


def test_sequence_14_plate_next_returns_deepest_derived_resume_command(
    repo: Path,
) -> None:
    # Sequence:
    # 1. User creates parent <branch>-plate.
    # 2. User creates derived1 with convo ID A.
    # 3. User creates derived2 with convo ID B.
    # 4. User runs plate_next(repo).
    # 5. Test verifies the returned command is:
    #    cd <repo> && claude --resume B
    pytest.fail("TODO: implement sequence 14")
