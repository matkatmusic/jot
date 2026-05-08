"""Smoke tests for git_test_funcs_lib helpers (makeEmptyRepo, makeTestRepo,
performRandomEdit, setup_repo, etc.).

Split from test_helpers.py per MIGRATION_TO_PYTHON.md bucket [git_test_funcs].
"""
from __future__ import annotations

import random
import subprocess
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

def test_makeEmptyRepo(tmp_path: Path):
    # no repo should exist yet at tmp_path
    assert not isGitRepo(tmp_path)

    repo = makeEmptyRepo(path=tmp_path)
    # Returns the path it created
    assert repo == tmp_path / "repo"
    assert repo.is_dir()
    # It's a git repo
    assert isGitRepo(repo)
    # Default branch is main (HEAD points at refs/heads/main even pre-commit)
    head = (repo / ".git" / "HEAD").read_text().strip()
    assert head == "ref: refs/heads/main"
    # Empty: no commits yet
    result = subprocess.run(
        ["git", "rev-list", "--all", "--count"],
        cwd=repo, capture_output=True, text=True,
check=True,
    )
    assert int(result.stdout.strip()) == 0

def test_makeTestRepoWithSingleCommit(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    assert isGitRepo(repo)
    assert countGitCommitsReachableFromRef(repo, "main") == 1
    assert getCurrentGitBranchName(repo) == "main"
    assert getGitUntrackedFilesList(repo) == []
    assert getGitStagedFilesList(repo) == []
    assert getGitUnstagedFilesList(repo) == []

def test_makeTestFile(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    fileName = TEST_FILENAME
    file = makeTestFile(repo, fileName)
    assert file == repo / fileName
    assert file.exists()
    assert file.read_text() == TEST_FILE_CONTENTS

def test_modifyTrackedFile(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    # make a test file
    fileName = TEST_FILENAME
    file = makeTestFile(repo, fileName)
    # add it to git
    addFileToGit(repo, file)
    createGitCommit(repo, "commit message")
    # now modify the tracked file
    before = (repo / fileName).read_text()
    action = modifyTrackedFile(repo, fileName, rng=random.Random())
    assert action == {"action": "modify_tracked", "file": fileName}
    # assert file was modified
    assert (repo / fileName).read_text() != before
    # assert file is not untracked
    assert getGitUntrackedFilesList(repo) == []
    # assert change isn't staged
    assert getGitStagedFilesList(repo) == []
    # assert file is tracked
    assert getGitTrackedFilesList(repo) == [fileName]
    # assert file is unstaged
    assert getGitUnstagedFilesList(repo) == [fileName]

def test_modifyRandomlyChosenTrackedFile(tmp_path: Path):
    # make a test repo
    repo = makeTestRepo(base=tmp_path)
    # add 3 files to it
    fileNames = [TEST_FILENAME, "b.txt", "c.txt"]
    files = []
    for fileName in fileNames:
        files.append(makeTestFile(repo, fileName))
    addMultipleFilesToGit(repo, files)
    # commit the 3 files
    createGitCommit(repo=repo, message="commit message")
    # modify one of them
    action = modifyRandomlyChosenTrackedFile(repo, files)
    # assert that the file is the only one showing up as unstaged
    assert getGitUnstagedFilesList(repo) == [action["file"]]

def test_createUntrackedFile(tmp_path: Path):
    # create a test repo
    repo = makeTestRepo(base=tmp_path)
    # add a file to it
    file = createUntrackedFile(repo, rng=random.Random())
    # assert it is untracked
    assert getGitUntrackedFilesList(repo) == [file["file"]]

def test_setup_repo(tmp_path: Path):
    repo = setup_repo(tmp_path)
    assert checkGitForCleanWorkTree(repo)
    assert getCurrentGitBranchName(repo) != "main"
    assert countGitCommitsReachableFromRef(repo, "main") == 1
    assert countGitCommitsReachableFromRef(repo, "HEAD") == 3
    assert (repo / TEST_FILENAME).read_text() == TEST_FILE_CONTENTS
    assert (repo / B_FILENAME).read_text() == B_FILE_CONTENTS
    assert (repo / F1_FILENAME).read_text() == F1_FILE_CONTENTS

def test_performRandomEdit_modify_tracked(tmp_path: Path,
monkeypatch):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    # Force rng.choice(seq) to return seq[0]:
    #   actions[0] = "modify_tracked"  → takes that branch
    #   tracked[0] = first tracked file → modifies it
    monkeypatch.setattr(random.Random, "choice", lambda self, seq: seq[0])

    # seed=0 forces rng = random.Random(0), whose .choice honors the patch
    # (the module-level `random.choice` is a pre-bound method and would not).
    result = performRandomEdit(repo, seed=0)

    assert result["action"] == "modify_tracked"
    assert result["file"] in getGitTrackedFilesList(repo)
    # Behavior: file shows as modified in WT
    assert result["file"] in getGitUnstagedFilesList(repo)


def test_performRandomEdit_create_untracked_when_tracked_exists(tmp_path: Path, monkeypatch):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    # Force rng.choice(seq) to return seq[-1]:
    #   actions[-1] = "create_untracked" → takes that branch
    monkeypatch.setattr(random.Random, "choice", lambda self, seq: seq[-1])

    # seed=0 forces rng = random.Random(0); see test_..._modify_tracked for why.
    result = performRandomEdit(repo, seed=0)

    assert result["action"] == "create_untracked"
    assert result["file"] in getGitUntrackedFilesList(repo)
    # Behavior: tracked files unchanged
    assert getGitUnstagedFilesList(repo) == []

def test_performRandomEdit_no_tracked_forces_create_untracked(tmp_path: Path):
    # No commits → empty `git ls-files` → "modify_tracked" removed from actions.
    # Only one branch reachable; no monkeypatch needed.
    repo = makeTestRepo(base=tmp_path)

    result = performRandomEdit(repo)

    assert result["action"] == "create_untracked"
    assert result["file"] in getGitUntrackedFilesList(repo)

def test_performRandomEdit_seeded_is_deterministic_simple(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    a = performRandomEdit(repo, seed=42)
    # reset and replay
    run(["git", "reset", "--hard"], cwd=repo)
    run(["git", "clean", "-fd"], cwd=repo)
    b = performRandomEdit(repo, seed=42)
    # expect the same results from two deterministic (same seed) calls
    assert a == b


# ── setup_repo ────────────────────────────────────────────────────────

def test_setup_repo_checks_out_non_main_branch(repo: Path) -> None:
    """Working branch is randomized but is never 'main'."""
    branch = getCurrentGitBranchName(repo)
    assert branch
    assert branch != "main"


def test_setup_repo_branch_name_is_varied(tmp_path: Path) -> None:
    """Two fresh repos in succession should pick different branch names."""
    from git_test_funcs_lib import setup_git_plate_test_repo as setup_repo

    seen = set()
    for i in range(10):
        r = setup_repo(tmp_path / f"r{i}")
        seen.add(getCurrentGitBranchName(r))
    # Variance means we shouldn't always get the same name 10 times.
    assert len(seen) > 1


def test_setup_repo_creates_three_commits(repo: Path) -> None:
    assert countGitCommitsReachableFromRef(repo, "HEAD") == 3


def test_setup_repo_main_has_one_commit(repo: Path) -> None:
    assert countGitCommitsReachableFromRef(repo, "main") == 1


def test_setup_repo_starts_clean(repo: Path) -> None:
    assert checkGitForCleanWorkTree(repo)


def test_setup_repo_creates_expected_files(repo: Path) -> None:
    assert (repo / "a.txt").read_text() == "A\n"
    assert (repo / "b.txt").read_text() == "B\n"
    assert (repo / "fix.txt").read_text() == "F1\n"


def test_setup_repo_has_expected_subjects(repo: Path) -> None:
    assert getGitCommitSubject(repo, "HEAD") == "F1"
    assert getGitCommitSubject(repo, "HEAD~1") == "B"
    assert getGitCommitSubject(repo, "main") == "A"


def test_setup_repo_diverges_from_main(repo: Path) -> None:
    """The working branch and main share an ancestor (A) but diverge:
    main has neither b.txt nor fix.txt."""
    assert getGitTreeSHA(repo, "main") != getGitTreeSHA(repo, "HEAD")


def test_setup_repo_no_plate_branch_initially(repo: Path) -> None:
    plate = f"{getCurrentGitBranchName(repo)}-plate"
    assert not checkIfGitBranchExists(repo, plate)


# ── performRandomEdit ───────────────────────────────────────────────────────

def test_performRandomEdit_dirties_wt(repo: Path) -> None:
    assert checkGitForCleanWorkTree(repo)
    performRandomEdit(repo, seed=0)
    assert not checkGitForCleanWorkTree(repo)


def test_performRandomEdit_returns_action_record(repo: Path) -> None:
    result = performRandomEdit(repo, seed=0)
    assert result["action"] in ("modify_tracked", "create_untracked")
    assert "file" in result


def test_performRandomEdit_modify_tracked_appends_line(repo: Path) -> None:
    """With a seed that picks modify_tracked, the file gains a line."""
    # Drive enough seeds to hit modify_tracked at least once.
    for s in range(50):
        before = (repo / "fix.txt").read_text()
        result = performRandomEdit(repo, seed=s)
        if result["action"] == "modify_tracked" and result["file"] == "fix.txt":
            after = (repo / "fix.txt").read_text()
            assert after.startswith(before)
            assert len(after) > len(before)
            return
    pytest.skip("seed range did not produce a modify_tracked of fix.txt")


def test_performRandomEdit_create_untracked_makes_new_file(repo: Path) -> None:
    """With a seed that picks create_untracked, a new file appears in WT."""
    for s in range(50):
        files_before = set(p.name for p in repo.iterdir() if p.is_file())
        result = performRandomEdit(repo, seed=s)
        if result["action"] == "create_untracked":
            files_after = set(p.name for p in repo.iterdir() if p.is_file())
            new_files = files_after - files_before
            assert result["file"] in new_files
            assert (repo / result["file"]).read_text().startswith("content-")
            return
    pytest.skip("seed range did not produce a create_untracked")


def test_performRandomEdit_seeded_is_deterministic(repo: Path, tmp_path: Path) -> None:
    """Same seed → same action."""
    a = performRandomEdit(repo, seed=12345)
    # Reset by setting up a parallel repo from the same fixture base
    from git_test_funcs_lib import setup_git_plate_test_repo as setup_repo

    other = setup_repo(tmp_path / "other")
    b = performRandomEdit(other, seed=12345)
    assert a == b


def test_performRandomEdit_unseeded_works(repo: Path) -> None:
    """No seed → still produces a valid edit (non-deterministic)."""
    result = performRandomEdit(repo)
    assert result["action"] in ("modify_tracked", "create_untracked")
    assert not checkGitForCleanWorkTree(repo)
