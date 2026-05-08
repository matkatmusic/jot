"""Tests for common/scripts/git_lib.py.

Migrated from skills/plate/tests/sequence/test_helpers.py as part of the
bash-to-python migration; this file isolates git_lib coverage so future
git_lib changes are exercised by a focused, plate-independent suite.

Plate-side test helpers (makeTestRepo*, makeTestFile, createUntrackedFile,
modifyTrackedFile, plate_createRandomBranchName) and their constants are still
re-imported from plate_lib for now. They will move to a neutral location
once the broader migration progresses.
"""
from __future__ import annotations

import random
import subprocess
from pathlib import Path

import pytest

from common.scripts.git_lib import (
    GITIGNORE_CONTENTS,
    USER_EMAIL_KEY,
    USER_EMAIL_VALUE,
    USER_NAME_KEY,
    USER_NAME_VALUE,
    GitError,
    addFileToGit,
    addMultipleFilesToGit,
    applyGitPatch,
    ensureGitignoreEntry,
    getGitBranchNameOrFail,
    getGitRecentCommitHashes,
    getGitRepoRoot,
    getGitUncommittedFilenames,
    checkGitForCleanWorkTree,
    checkIfGitBranchExists,
    checkOutGitBranch,
    countGitCommitsReachableFromRef,
    createAndCheckoutGitBranch,
    createGitBranch,
    createGitCommit,
    deleteGitBranchByForce,
    getCurrentGitBranchName,
    getGitBranchList,
    getGitCommitSubject,
    getGitCommitTrailers,
    getGitStagedFilesList,
    getGitStatus,
    getGitTrackedFilesList,
    getGitTreeRevOf,
    getGitUnstagedFilesList,
    getGitUntrackedFilesList,
    getGitUserConfigValue,
    getSHAForGitRefViaRevParse,
    gitCleanWorkTree,
    gitResetHardToHead,
    gitStashFiles,
    gitUnstashFiles,
    isGitRepo,
    makeTempGitIndexPath,
    readGitTreeAt,
    saveChangesToGitPatch,
    setGitIndexFileForEnv,
    setGitUserConfigValue,
    stageAllGitChanges,
    writeGitIgnore,
    writeGitTree,
)
from common.scripts.util_lib import run
from common.scripts.plate.plate_lib import (
    TEST_COMMIT_MESSAGE,
    TEST_FILE_CONTENTS,
    TEST_FILENAME,
    plate_createRandomBranchName,
)
from common.scripts.git_test_funcs_lib import (
    createUntrackedFile,
    makeEmptyRepo,
    makeTestFile,
    makeTestRepo,
    makeTestRepoWithSingleCommit,
    modifyTrackedFile,
)


def test_run():
    result = run(["ls", "-l"], cwd=Path("."))
    assert result is not None


def test_writeGitIgnore(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    path = writeGitIgnore(repo)
    assert path == repo / ".gitignore"
    assert path.read_text() == GITIGNORE_CONTENTS
    # Before staging, .gitignore is itself untracked.
    assert ".gitignore" in getGitUntrackedFilesList(repo)
    # The .plate/ pattern is now active: .plate/foo.txt is ignored.
    (repo / ".plate").mkdir()
    (repo / ".plate" / "foo.txt").write_text("ignored\n")
    assert ".plate/foo.txt" not in getGitUntrackedFilesList(repo)


def test_setGitUserConfigValue(tmp_path: Path):
    repo = makeEmptyRepo(path=tmp_path)
    setGitUserConfigValue(repo, USER_EMAIL_KEY, USER_EMAIL_VALUE)
    assert getGitUserConfigValue(repo, USER_EMAIL_KEY) == USER_EMAIL_VALUE


def test_createGitUserConfig(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    assert getGitUserConfigValue(repo, USER_EMAIL_KEY) == USER_EMAIL_VALUE
    assert getGitUserConfigValue(repo, USER_NAME_KEY) == USER_NAME_VALUE


def test_createGitBranch(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(base=tmp_path)
    original_head = getCurrentGitBranchName(repo)
    branch_name = plate_createRandomBranchName()
    createGitBranch(repo, branch_name)
    branches = getGitBranchList(repo)
    print(branch_name)
    print(branches)
    assert branch_name in getGitBranchList(repo)
    # make sure HEAD hasn't moved
    assert getCurrentGitBranchName(repo) == original_head


def test_checkOutGitBranch(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(base=tmp_path)
    branch_name = plate_createRandomBranchName()
    createGitBranch(repo, branch_name)
    checkOutGitBranch(repo=repo, branch_name=branch_name)
    assert getCurrentGitBranchName(repo) == branch_name


def test_createAndCheckoutGitBranch(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(base=tmp_path)
    branch_name = plate_createRandomBranchName()
    createAndCheckoutGitBranch(repo, branch_name)
    branches = getGitBranchList(repo)
    print(branch_name)
    print(branches)
    assert branch_name in getGitBranchList(repo)
    assert getCurrentGitBranchName(repo) == branch_name


def test_getCurrentGitBranchName(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    assert getCurrentGitBranchName(repo) == "main"


def test_gitStashFiles(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    untrackedName = createUntrackedFile(repo, random.Random())["file"]
    assert untrackedName in getGitUntrackedFilesList(repo)
    assert (repo / untrackedName).exists()

    gitStashFiles(repo, [untrackedName])

    # File is gone from WT and from the untracked list.
    assert not (repo / untrackedName).exists()
    assert getGitUntrackedFilesList(repo) == []
    # A stash entry was created.
    assert run(["git", "stash", "list"], cwd=repo) != ""


def test_gitUnstashFiles(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    untrackedName = createUntrackedFile(repo, random.Random())["file"]
    originalContent = (repo / untrackedName).read_text()
    gitStashFiles(repo, [untrackedName])
    assert not (repo / untrackedName).exists()

    gitUnstashFiles(repo)

    # File is restored byte-for-byte and stash stack is empty.
    assert (repo / untrackedName).exists()
    assert (repo / untrackedName).read_text() == originalContent
    assert getGitUntrackedFilesList(repo) == [untrackedName]
    assert run(["git", "stash", "list"], cwd=repo) == ""


def test_addFileToGit(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    fileName = TEST_FILENAME
    file = makeTestFile(repo, fileName)
    # assert file is in unstaged changes
    assert getGitUntrackedFilesList(repo) == [fileName]
    addFileToGit(repo=repo, file=file)
    # assert file is not in unstaged changes
    assert getGitUntrackedFilesList(repo) == []
    # assert file is staged now
    assert getGitStagedFilesList(repo) == [fileName]


def test_stageFiles(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    fileNames = [TEST_FILENAME, "b.txt"]
    files = []
    for fileName in fileNames:
        files.append(makeTestFile(repo, fileName))
    addMultipleFilesToGit(repo=repo, files=files)
    assert getGitStagedFilesList(repo) == fileNames
    assert getGitUntrackedFilesList(repo) == []


def test_createGitCommit(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    fileName = TEST_FILENAME
    file = makeTestFile(repo, fileName)
    addFileToGit(repo, file)
    message = "test commit"
    createGitCommit(repo=repo, message=message)
    # assert commit count is == 1
    assert countGitCommitsReachableFromRef(repo, "main") == 1
    # assert file is not staged
    assert getGitStagedFilesList(repo) == []
    # assert file is not untracked
    assert getGitUntrackedFilesList(repo) == []
    # assert file is tracked
    assert getGitTrackedFilesList(repo) == [fileName]


def test_checkIfGitBranchExists(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    # a repo with no commits won't show a branch list when running git branch.
    branch_name = getCurrentGitBranchName(repo)
    # assert that branch_name == "main"
    assert branch_name == "main"
    assert checkIfGitBranchExists(repo, branch_name) == False
    # if we make a commit, then the branch will exist
    fileName = TEST_FILENAME
    file = makeTestFile(repo, fileName)
    addFileToGit(repo, file)
    createGitCommit(repo=repo, message="test commit")
    assert checkIfGitBranchExists(repo, branch_name) == True


def test_countGitCommitsReachableFromRef(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    fileName = TEST_FILENAME
    file = makeTestFile(repo, fileName)
    addFileToGit(repo, file)
    createGitCommit(repo=repo, message="test commit")
    assert countGitCommitsReachableFromRef(repo, "main") == 1


def test_getSHAForGitRefViaRevParse(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    # 1. assert the function Returns 40-char lowercase hex for HEAD
    head_sha = getSHAForGitRefViaRevParse(repo, "HEAD")
    assert len(head_sha) == 40
    assert all(c in "0123456789abcdef" for c in head_sha)

    # 2. assert HEAD SHA == current branch tip SHA when HEAD is on that branch
    branch_name = getCurrentGitBranchName(repo)
    assert head_sha == getSHAForGitRefViaRevParse(repo, branch_name)

    # 3. assert HEAD^{tree} resolves to the tree SHA, which differs from commit SHA
    tree_sha = getSHAForGitRefViaRevParse(repo, "HEAD^{tree}")
    assert len(tree_sha) == 40
    assert tree_sha != head_sha

    # 4. assert same result when we call the function with HEAD again (Idempotent)
    assert getSHAForGitRefViaRevParse(repo, "HEAD") == head_sha


def test_readWriteGitTree(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    head_tree = getSHAForGitRefViaRevParse(repo, "HEAD^{tree}")
    # snapshot the real index by writing it (no env override) — pure read,
    # produces a deterministic SHA without mutating anything.
    real_index_before = run(["git", "write-tree"], cwd=repo)
    wt_clean_before = checkGitForCleanWorkTree(repo)

    # 1. assert a round-trip on clean WT reproduces HEAD's tree SHA
    tmp = makeTempGitIndexPath()
    try:
        env = setGitIndexFileForEnv({}, tmp)
        readGitTreeAt(repo, "HEAD", env)
        roundtrip_tree = writeGitTree(repo, env)
        assert roundtrip_tree == head_tree
    finally:
        Path(tmp).unlink(missing_ok=True)

    # 2. assert the Real index is untouched
    assert run(["git", "write-tree"], cwd=repo) == real_index_before

    # 3. assert the Working tree is untouched
    assert checkGitForCleanWorkTree(repo) == wt_clean_before

    # 4. assert that WT edits get captured via temp-index `git add -A`
    tmp2 = makeTempGitIndexPath()
    try:
        env = setGitIndexFileForEnv({}, tmp2)
        readGitTreeAt(repo=repo, ref="HEAD", env=env)
        # modify a file in the working tree
        fileName = TEST_FILENAME
        (repo / fileName).write_text("A-modified\n")
        # add the file to the index
        stageAllGitChanges(repo=repo, env=env)
        modified_tree = writeGitTree(repo=repo, env=env)
        # assert that the modified tree is different from the original tree
        assert modified_tree != head_tree
        # assert that the Real index is STILL untouched even after temp-index add
        assert run(["git", "write-tree"], cwd=repo) == real_index_before
    finally:
        Path(tmp2).unlink(missing_ok=True)


def test_getGitTreeRevOf():
    assert getGitTreeRevOf("abc123") == "abc123^{tree}"


def test_getGitStatus(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    # assert that the repo status is clean
    assert getGitStatus(repo) == ""
    # Untracked
    newFileName = "new.txt"
    makeTestFile(repo, newFileName)
    status = getGitStatus(repo)
    assert newFileName in status
    # modify a tracked file
    rng = random.Random()
    modifyTrackedFile(repo, TEST_FILENAME, rng)
    status = getGitStatus(repo)
    assert ("M " + TEST_FILENAME) in status


def test_checkGitForCleanWorkTree(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    assert checkGitForCleanWorkTree(repo)


def test_getGitCommitSubject(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    assert getGitCommitSubject(repo, "main") == TEST_COMMIT_MESSAGE


def test_getGitCommitTrailers(tmp_path: Path):
    repo = makeTestRepo(tmp_path)
    addFileToGit(repo, makeTestFile(repo, "a.txt"))
    run(
        [
            "git",
            "commit",
            "-q",
            "-m",
            "subject\n\nbody line\n\nparent-convo: abc\nplate-id: 42",
        ],
        cwd=repo,
    )
    trailers = getGitCommitTrailers(repo, "HEAD")
    assert trailers == {"parent-convo": "abc", "plate-id": "42"}


def test_gitResetHardToHead(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    (repo / TEST_FILENAME).write_text("dirty\n")
    assert (repo / TEST_FILENAME).read_text() == "dirty\n"
    gitResetHardToHead(repo)
    assert (repo / TEST_FILENAME).read_text() == TEST_FILE_CONTENTS


def test_gitCleanWorkTree(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    untrackedName = createUntrackedFile(repo, random.Random())["file"]
    assert (repo / untrackedName).exists()
    gitCleanWorkTree(repo)
    assert not (repo / untrackedName).exists()
    assert getGitUntrackedFilesList(repo) == []


def test_deleteGitBranchByForce(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    name = plate_createRandomBranchName()
    createGitBranch(repo, name)
    assert checkIfGitBranchExists(repo, name)
    deleteGitBranchByForce(repo, name)
    assert not checkIfGitBranchExists(repo, name)


def test_saveChangesToGitPatch(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    modifiedContent = "modified content\n"

    # Modify a tracked file and create an untracked one.
    (repo / TEST_FILENAME).write_text(modifiedContent)
    untrackedName = createUntrackedFile(repo, random.Random())["file"]
    untrackedContent = (repo / untrackedName).read_text()

    patch = saveChangesToGitPatch(repo, [TEST_FILENAME, untrackedName])

    # Patch file lands in .plate/dropped/ and ends with a trailing newline.
    assert patch.exists()
    assert patch.parent.name == "dropped"
    text = patch.read_text()
    assert text.endswith("\n")
    assert TEST_FILENAME in text
    assert untrackedName in text

    # WT untouched.
    assert (repo / TEST_FILENAME).read_text() == modifiedContent
    assert (repo / untrackedName).exists()

    # Round-trip: reset WT to clean, apply patch, original changes return.
    gitResetHardToHead(repo)
    (repo / untrackedName).unlink()
    assert (repo / TEST_FILENAME).read_text() == TEST_FILE_CONTENTS
    applyGitPatch(repo, patch)
    assert (repo / TEST_FILENAME).read_text() == modifiedContent
    assert (repo / untrackedName).read_text() == untrackedContent


def test_applyGitPatch(tmp_path: Path):
    # 1. Make a test repo with a single commit; original tracked content
    #    is TEST_FILE_CONTENTS.
    repo = makeTestRepoWithSingleCommit(tmp_path)

    # 2. Modify the tracked file and capture the diff via `git diff --binary`
    #    into a .patch file. (run() strips trailing newlines; git apply
    #    requires them, so append "\n".)
    modifiedContent = "modified content\n"
    (repo / TEST_FILENAME).write_text(modifiedContent)
    patch_text = run(["git", "diff", "--binary"], cwd=repo)
    patch_path = tmp_path / "test.patch"
    patch_path.write_text(patch_text + "\n")

    # 3. git reset --hard to revert the WT to the original state.
    run(["git", "reset", "--hard"], cwd=repo)
    assert (repo / TEST_FILENAME).read_text() == TEST_FILE_CONTENTS

    # 4. Call applyGitPatch(repo, patchPath); expected behavior:
    #    a. Runs `git apply --3way <patch>` on the saved patch.
    #    b. WT now reflects the patched state again.
    applyGitPatch(repo, patch_path)

    # 5. Assert: tracked file content matches the modified content (post-patch).
    assert (repo / TEST_FILENAME).read_text() == modifiedContent


# ── git.sh parity helpers ─────────────────────────────────────────────


def test_getGitRepoRoot_returns_absolute_repo_root(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    assert getGitRepoRoot(repo) == repo


def test_getGitRepoRoot_works_from_subdirectory(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    sub = repo / "sub"
    sub.mkdir()
    assert getGitRepoRoot(sub) == repo


def test_getGitRepoRoot_raises_outside_repo(tmp_path: Path):
    with pytest.raises(GitError, match=r"\[git\] not inside a git repository"):
        getGitRepoRoot(tmp_path)


def test_getGitBranchNameOrFail_returns_current_branch(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    assert getGitBranchNameOrFail(repo) == "main"


def test_getGitBranchNameOrFail_raises_outside_repo(tmp_path: Path):
    with pytest.raises(GitError, match=r"not a git repository"):
        getGitBranchNameOrFail(tmp_path)


def test_getGitBranchNameOrFail_raises_on_detached_head(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    run(["git", "checkout", "--detach"], cwd=repo)
    with pytest.raises(GitError, match=r"HEAD detached at [0-9a-f]+"):
        getGitBranchNameOrFail(repo)


def test_getGitRecentCommitHashes_returns_one_hash_for_single_commit(
    tmp_path: Path,
):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    hashes = getGitRecentCommitHashes(repo)
    assert len(hashes) == 1
    # Each hash is git's --short form: hex, length >= 7.
    assert all(len(h) >= 7 and all(c in "0123456789abcdef" for c in h)
               for h in hashes)


def test_getGitRecentCommitHashes_caps_at_n(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    for i in range(7):
        run(["git", "commit", "--allow-empty", "-m", f"c{i}"], cwd=repo)
    # Default n=5
    assert len(getGitRecentCommitHashes(repo)) == 5
    # Override n
    assert len(getGitRecentCommitHashes(repo, n=3)) == 3


def test_getGitRecentCommitHashes_raises_outside_repo(tmp_path: Path):
    with pytest.raises(GitError, match=r"not a git repository"):
        getGitRecentCommitHashes(tmp_path)


def test_getGitRecentCommitHashes_raises_on_empty_repo(tmp_path: Path):
    repo = makeEmptyRepo(path=tmp_path)
    setGitUserConfigValue(repo, USER_EMAIL_KEY, USER_EMAIL_VALUE)
    setGitUserConfigValue(repo, USER_NAME_KEY, USER_NAME_VALUE)
    with pytest.raises(GitError, match=r"No commits yet"):
        getGitRecentCommitHashes(repo)


def test_getGitUncommittedFilenames_clean_repo_returns_empty(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    assert getGitUncommittedFilenames(repo) == []


def test_getGitUncommittedFilenames_lists_modified(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    (repo / TEST_FILENAME).write_text("modified\n")
    assert TEST_FILENAME in getGitUncommittedFilenames(repo)


def test_getGitUncommittedFilenames_lists_untracked(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    (repo / "new.txt").write_text("hi\n")
    assert "new.txt" in getGitUncommittedFilenames(repo)


def test_getGitUncommittedFilenames_raises_outside_repo(tmp_path: Path):
    with pytest.raises(GitError, match=r"not a git repository"):
        getGitUncommittedFilenames(tmp_path)


def test_ensureGitignoreEntry_creates_file(tmp_path: Path):
    ensureGitignoreEntry(tmp_path, ".plate/")
    assert ".plate/" in (tmp_path / ".gitignore").read_text().splitlines()


def test_ensureGitignoreEntry_appends_to_existing(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("node_modules\n")
    ensureGitignoreEntry(tmp_path, ".plate/")
    lines = (tmp_path / ".gitignore").read_text().splitlines()
    assert "node_modules" in lines
    assert ".plate/" in lines


def test_ensureGitignoreEntry_is_idempotent(tmp_path: Path):
    ensureGitignoreEntry(tmp_path, ".plate/")
    ensureGitignoreEntry(tmp_path, ".plate/")
    ensureGitignoreEntry(tmp_path, ".plate/")
    lines = (tmp_path / ".gitignore").read_text().splitlines()
    assert lines.count(".plate/") == 1

from common.scripts.git_lib import makeGitRepo as _make_repo
