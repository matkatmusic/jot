"""Smoke tests and sequence specs for the /plate test helpers.

The setup_repo() and performRandomEdit() tests verify implemented helpers.
The test_sequence_* functions are failing workflow stubs for the plate
operation helpers; each one describes the user sequence it must cover.
"""
from __future__ import annotations

import json
import random
import subprocess
import time
from pathlib import Path

import pytest

# After the test_* functions migrated out of plate_lib.py, every library
# symbol the tests reference must be importable into this namespace —
# including underscore-prefixed scenario callables (`_check_*`) and
# private helpers (`_writeFakeTranscriptWithToolUse`, etc.) that
# `from plate_lib import *` would skip. Pull them in explicitly via vars().
# (sys.path setup already done by conftest.py.)
import plate_lib as _plate_lib
globals().update({
    name: value
    for name, value in vars(_plate_lib).items()
    if not name.startswith("__")
})

def test_run():
    result = run(["ls", "-l"], cwd=Path("."))
    assert result is not None

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

def test_makeTestRepoWithSingleCommit(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    assert isGitRepo(repo)
    assert countCommitsReachableFromRef(repo, "main") == 1
    assert getCurrentBranchName(repo) == "main"
    assert getGitUntrackedFilesList(repo) == []
    assert getGitStagedFilesList(repo) == []
    assert getGitUnstagedFilesList(repo) == []

def test_setUserConfigValue(tmp_path: Path):
    repo = makeEmptyRepo(path=tmp_path)
    setUserConfigValue(repo, USER_EMAIL_KEY, USER_EMAIL_VALUE)
    assert getUserConfigValue(repo, USER_EMAIL_KEY) == USER_EMAIL_VALUE

def test_createUserConfig(tmp_path: Path): 
    repo = makeTestRepo(base=tmp_path)
    assert getUserConfigValue(repo, USER_EMAIL_KEY) == USER_EMAIL_VALUE
    assert getUserConfigValue(repo, USER_NAME_KEY) == USER_NAME_VALUE

def test_createBranch(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(base=tmp_path)
    original_head = getCurrentBranchName(repo)
    branch_name = createRandomBranchName()
    createBranch(repo, branch_name)
    branches = getGitBranchList(repo)
    print(branch_name)
    print(branches)
    assert branch_name in getGitBranchList(repo)
    # make sure HEAD hasn't moved
    assert getCurrentBranchName(repo) == original_head  

def test_checkOutBranch(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(base=tmp_path)
    branch_name = createRandomBranchName()
    createBranch(repo, branch_name)
    checkOutBranch(repo=repo, branch_name=branch_name)
    assert getCurrentBranchName(repo) == branch_name

def test_createAndCheckoutBranch(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(base=tmp_path)
    branch_name = createRandomBranchName()
    createAndCheckoutBranch(repo, branch_name)
    branches = getGitBranchList(repo)
    print(branch_name)
    print(branches)
    assert branch_name in getGitBranchList(repo)
    assert getCurrentBranchName(repo) == branch_name

def test_getCurrentBranchName(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    assert getCurrentBranchName(repo) == "main"

def test_makeTestFile(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    fileName = TEST_FILENAME
    file = makeTestFile(repo, fileName)
    assert file == repo / fileName
    assert file.exists()
    assert file.read_text() == TEST_FILE_CONTENTS

def test_stashFiles(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    untrackedName = createUntrackedFile(repo, random.Random())["file"]
    assert untrackedName in getGitUntrackedFilesList(repo)
    assert (repo / untrackedName).exists()

    stashFiles(repo, [untrackedName])

    # File is gone from WT and from the untracked list.
    assert not (repo / untrackedName).exists()
    assert getGitUntrackedFilesList(repo) == []
    # A stash entry was created.
    assert run(["git", "stash", "list"], cwd=repo) != ""

def test_unstashFiles(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    untrackedName = createUntrackedFile(repo, random.Random())["file"]
    originalContent = (repo / untrackedName).read_text()
    stashFiles(repo, [untrackedName])
    assert not (repo / untrackedName).exists()

    unstashFiles(repo)

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

def test_createCommit(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    fileName = TEST_FILENAME
    file = makeTestFile(repo, fileName)
    addFileToGit(repo, file)
    message = "test commit"
    createCommit(repo=repo, message=message)
    # assert commit count is == 1
    assert countCommitsReachableFromRef(repo, "main") == 1
    # assert file is not staged
    assert getGitStagedFilesList(repo) == []
    # assert file is not untracked
    assert getGitUntrackedFilesList(repo) == []
    # assert file is tracked
    assert getGitTrackedFilesList(repo) == [fileName]

def test_modifyTrackedFile(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    # make a test file
    fileName = TEST_FILENAME
    file = makeTestFile(repo, fileName)
    # add it to git
    addFileToGit(repo, file)
    createCommit(repo, "commit message")
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
    createCommit(repo=repo, message="commit message")
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
    assert checkForCleanWorkTree(repo)
    assert getCurrentBranchName(repo) != "main"            
    assert countCommitsReachableFromRef(repo, "main") == 1 
    assert countCommitsReachableFromRef(repo, "HEAD") == 3
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

def test_performRandomEdit_seeded_is_deterministic(tmp_path:
Path):
    repo_a = makeTestRepoWithSingleCommit(tmp_path / "a")
    repo_b = makeTestRepoWithSingleCommit(tmp_path / "b")

    assert performRandomEdit(repo_a, seed=42) == performRandomEdit(repo_b, seed=42)

def test_performRandomEdit_seeded_is_deterministic_simple(tmp_path: Path):  
    repo = makeTestRepoWithSingleCommit(tmp_path)          
    a = performRandomEdit(repo, seed=42)                 
    # reset and replay                                     
    run(["git", "reset", "--hard"], cwd=repo)
    run(["git", "clean", "-fd"], cwd=repo) 
    b = performRandomEdit(repo, seed=42)
    # expect the same results from two deterministic (same seed) calls
    assert a == b

def test_branchExists(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    # a repo with no commits won't show a branch list when running git branch.
    branch_name = getCurrentBranchName(repo) 
    # assert that branch_name == "main"
    assert branch_name == "main"
    assert branchExists(repo, branch_name) == False
    # if we make a commit, then the branch will exist
    # make a test file
    fileName = TEST_FILENAME
    file = makeTestFile(repo, fileName)
    # commit the test file
    addFileToGit(repo, file)
    createCommit(repo=repo, message="test commit")
    # now check that the branch exists
    assert branchExists(repo, branch_name) == True

def test_countCommitsReachableFromRef(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    # make a test file
    fileName = TEST_FILENAME
    file = makeTestFile(repo, fileName)
    # add the test file
    addFileToGit(repo, file)
    # commit the test file
    createCommit(repo=repo, message="test commit")
    # assert that main has 1 commit
    assert countCommitsReachableFromRef(repo, "main") == 1

def test_getSHAForRefViaRevParse(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    # 1. assert the function Returns 40-char lowercase hex for HEAD
    head_sha = getSHAForRefViaRevParse(repo, "HEAD")
    assert len(head_sha) == 40
    assert all(c in "0123456789abcdef" for c in head_sha)

    # 2. assert HEAD SHA == current branch tip SHA when HEAD is on that branch
    branch_name = getCurrentBranchName(repo)
    assert head_sha == getSHAForRefViaRevParse(repo, branch_name)

    # 3. assert HEAD^{tree} resolves to the tree SHA, which differs from commit SHA
    tree_sha = getSHAForRefViaRevParse(repo, "HEAD^{tree}")
    assert len(tree_sha) == 40
    assert tree_sha != head_sha

    # 4. assert same result when we call the function with HEAD again (Idempotent)
    assert getSHAForRefViaRevParse(repo, "HEAD") == head_sha

def test_readWriteGitTree(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    head_tree = getSHAForRefViaRevParse(repo, "HEAD^{tree}")
    # snapshot the real index by writing it (no env override) — pure read,
    # produces a deterministic SHA without mutating anything.
    real_index_before = run(["git", "write-tree"], cwd=repo)
    wt_clean_before = checkForCleanWorkTree(repo)

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
    assert checkForCleanWorkTree(repo) == wt_clean_before

    # 4. assert that WT edits get captured via temp-index `git add -A`
    tmp2 = makeTempGitIndexPath()
    try:
        env = setGitIndexFileForEnv({}, tmp2)
        readGitTreeAt(repo=repo, ref="HEAD", env=env)
        # modify a file in the working tree
        fileName = TEST_FILENAME
        (repo / fileName).write_text("A-modified\n")
        # add the file to the index
        stageAllChanges(repo=repo, env=env)
        modified_tree = writeGitTree(repo=repo, env=env)
        # assert that the modified tree is different from the original tree
        assert modified_tree != head_tree
        # assert that the Real index is STILL untouched even after temp-index add
        assert run(["git", "write-tree"], cwd=repo) == real_index_before
    finally:
        Path(tmp2).unlink(missing_ok=True)

def test_getTreeRevOf():      
    assert getTreeRevOf("abc123") == "abc123^{tree}"   

def test_getGitStatus(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    # assert that the repo status is clean
    assert getGitStatus(repo) == ""
    # Untracked
    newFileName = "new.txt"
    makeTestFile(repo, newFileName)
    status = getGitStatus(repo)
    # assert that there is a 'new.txt' file in the repo status
    assert newFileName in status
    # modify a tracked file
    rng = random.Random()
    modifyTrackedFile(repo, TEST_FILENAME, rng)
    status = getGitStatus(repo)
    # assert that the modified file shows up in the repo status with ' M' before it
    assert ("M " + TEST_FILENAME) in status

def test_checkForCleanWorkTree(tmp_path: Path):
    # make a test repo
    repo = makeTestRepoWithSingleCommit(tmp_path)
    # assert that worktree has no changes 
    assert checkForCleanWorkTree(repo)

def test_getCommitSubject(tmp_path: Path):
    # make a test repo
    repo = makeTestRepoWithSingleCommit(tmp_path)
    # assert that main has 1 commit
    assert getCommitSubject(repo, "main") == TEST_COMMIT_MESSAGE

def test_getCommitTrailers(tmp_path: Path):
    repo = makeTestRepo(tmp_path)
    addFileToGit(repo, makeTestFile(repo, "a.txt"))        
    run(["git", "commit", "-q", "-m", "subject\n\nbody line\n\nparent-convo: abc\nplate-id: 42"], cwd=repo)                             
    trailers = getCommitTrailers(repo, "HEAD")             
    assert trailers == {"parent-convo": "abc", "plate-id": 
"42"}          

def test_resetHardToHead(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    (repo / TEST_FILENAME).write_text("dirty\n")
    assert (repo / TEST_FILENAME).read_text() == "dirty\n"
    resetHardToHead(repo)
    assert (repo / TEST_FILENAME).read_text() == TEST_FILE_CONTENTS

def test_cleanWorkTree(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    untrackedName = createUntrackedFile(repo, random.Random())["file"]
    assert (repo / untrackedName).exists()
    cleanWorkTree(repo)
    assert not (repo / untrackedName).exists()
    assert getGitUntrackedFilesList(repo) == []

def test_deleteBranchForce(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    name = createRandomBranchName()
    createBranch(repo, name)
    assert branchExists(repo, name)
    deleteBranchForce(repo, name)
    assert not branchExists(repo, name)

def test_formatPlateAge():
    assert formatPlateAge(0) == "0m"
    assert formatPlateAge(59) == "0m"
    assert formatPlateAge(60) == "1m"
    assert formatPlateAge(32 * 60) == "32m"
    assert formatPlateAge(14 * 3600 + 7 * 60) == "14h 7m"
    assert formatPlateAge(3 * 86400 + 2 * 3600 + 5 * 60) == "3d 2h 5m"
    # Edge: exactly one hour with no remaining minutes.
    assert formatPlateAge(3600) == "1h 0m"
    # Negative seconds clamp to zero.
    assert formatPlateAge(-5) == "0m"

def test_localTranscriptIsReadable(tmp_path: Path):
    # None / empty → False
    assert localTranscriptIsReadable(None) is False
    assert localTranscriptIsReadable("") is False
    # Non-existent path → False
    assert localTranscriptIsReadable(str(tmp_path / "missing.jsonl")) is False
    # Real, readable file → True
    real = tmp_path / "real.jsonl"
    real.write_text('{"type":"foo"}\n')
    assert localTranscriptIsReadable(str(real)) is True

def test_extractConvoNameFromTranscript_returns_latest_custom_title(tmp_path: Path):
    transcript = tmp_path / "abc-123.jsonl"
    transcript.write_text(
        '{"type":"system","cwd":"/x"}\n'
        '{"type":"custom-title","customTitle":"first name","sessionId":"abc-123"}\n'
        '{"type":"user","content":"hi"}\n'
        '{"type":"custom-title","customTitle":"renamed","sessionId":"abc-123"}\n'
    )
    assert extractConvoNameFromTranscript(transcript) == "renamed"

def test_extractConvoNameFromTranscript_falls_back_to_session_id_when_no_title(
    tmp_path: Path,
):
    transcript = tmp_path / "session-uuid-xyz.jsonl"
    transcript.write_text('{"type":"system","cwd":"/x"}\n')
    assert extractConvoNameFromTranscript(transcript) == "session-uuid-xyz"

def test_extractConvoNameFromTranscript_returns_none_when_file_missing(tmp_path: Path):
    assert extractConvoNameFromTranscript(tmp_path / "missing.jsonl") is None

def test_extractConvoNameFromTranscript_skips_unparseable_lines(tmp_path: Path):
    transcript = tmp_path / "abc.jsonl"
    transcript.write_text(
        'not-json\n'
        '{"type":"custom-title","customTitle":"valid","sessionId":"abc"}\n'
    )
    assert extractConvoNameFromTranscript(transcript) == "valid"

def test_extractConvoCwdFromTranscript_returns_first_cwd(tmp_path: Path):
    transcript = tmp_path / "x.jsonl"
    transcript.write_text(
        '{"type":"custom-title","customTitle":"name"}\n'
        '{"type":"system","cwd":"/Users/me/project"}\n'
        '{"type":"user","cwd":"/Users/me/elsewhere"}\n'
    )
    assert extractConvoCwdFromTranscript(transcript) == "/Users/me/project"

def test_extractConvoCwdFromTranscript_returns_none_when_no_cwd(tmp_path: Path):
    transcript = tmp_path / "x.jsonl"
    transcript.write_text('{"type":"system","other":"field"}\n')
    assert extractConvoCwdFromTranscript(transcript) is None

def test_extractConvoCwdFromTranscript_returns_none_when_file_missing(tmp_path: Path):
    assert extractConvoCwdFromTranscript(tmp_path / "missing.jsonl") is None

def test_extractFilesEditedSinceTimestamp_filters_by_tool_and_cutoff(tmp_path: Path):
    transcript = _writeFakeTranscriptWithToolUse(
        tmp_path / "t.jsonl",
        [
            {"timestamp": "2026-04-30T10:00:00.000Z", "tool": "Edit",
             "input": {"file_path": "/repo/file_a.txt"}},
            {"timestamp": "2026-04-30T10:01:00.000Z", "tool": "Write",
             "input": {"file_path": "/repo/file_b.txt"}},
            {"timestamp": "2026-04-30T10:02:00.000Z", "tool": "Read",
             "input": {"file_path": "/repo/file_c.txt"}},  # NOT a modifier
            {"timestamp": "2026-04-30T10:03:00.000Z", "tool": "MultiEdit",
             "input": {"file_path": "/repo/file_d.txt"}},
            {"timestamp": "2026-04-30T10:04:00.000Z", "tool": "Edit",
             "input": {"file_path": "/repo/file_a.txt"}},  # dup
        ],
    )

    # Cutoff at T2 (10:01:00) — entries at/before excluded; Read excluded; dedup.
    result = extractFilesEditedSinceTimestamp(
        transcript, since_iso="2026-04-30T10:01:00.000Z"
    )
    assert result == ["/repo/file_a.txt", "/repo/file_d.txt"]

    # No cutoff → all file-modifying entries (still no Read; still deduped).
    result_all = extractFilesEditedSinceTimestamp(transcript, since_iso=None)
    assert result_all == ["/repo/file_a.txt", "/repo/file_b.txt", "/repo/file_d.txt"]

    # Missing file → [].
    assert extractFilesEditedSinceTimestamp(tmp_path / "missing.jsonl", None) == []

def test_extractFilesDeletedSinceTimestamp(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()

    transcript = _writeFakeTranscriptWithToolUse(
        tmp_path / "t.jsonl",
        [
            {"timestamp": "2026-04-30T10:00:00.000Z", "tool": "Bash",
             "input": {"command": f"rm {repo}/inside_a.txt"}},
            {"timestamp": "2026-04-30T10:01:00.000Z", "tool": "Bash",
             "input": {"command": "rm /var/log/outside.txt"}},  # outside repo
            {"timestamp": "2026-04-30T10:02:00.000Z", "tool": "Bash",
             "input": {"command": f"git rm {repo}/inside_b.txt"}},
            {"timestamp": "2026-04-30T10:03:00.000Z", "tool": "Bash",
             "input": {"command": f"rm {repo}/inside_c.txt {repo}/inside_d.txt"}},
            {"timestamp": "2026-04-30T10:04:00.000Z", "tool": "Bash",
             "input": {"command": "rm $(cat list.txt)"}},  # shell expansion
            {"timestamp": "2026-04-30T10:05:00.000Z", "tool": "Bash",
             "input": {"command": f"rm -rf {repo}/inside_e.txt"}},  # flag stripped
            {"timestamp": "2026-04-30T10:06:00.000Z", "tool": "Edit",
             "input": {"file_path": f"{repo}/not_a_deletion.txt"}},  # not Bash
        ],
    )

    # All entries, no cutoff — only inside-repo, no expansions, flags ignored.
    result = extractFilesDeletedSinceTimestamp(transcript, since_iso=None, repo_root=repo)
    assert result == [
        "inside_a.txt", "inside_b.txt", "inside_c.txt", "inside_d.txt", "inside_e.txt",
    ]

    # Cutoff at T2 → entries strictly > 10:02 (inside_c, inside_d, inside_e).
    result_recent = extractFilesDeletedSinceTimestamp(
        transcript, since_iso="2026-04-30T10:02:00.000Z", repo_root=repo
    )
    assert result_recent == ["inside_c.txt", "inside_d.txt", "inside_e.txt"]

    # Missing transcript → [].
    assert extractFilesDeletedSinceTimestamp(
        tmp_path / "missing.jsonl", None, repo
    ) == []

def test_listPlateBranches(tmp_path: Path):
    """Two plate branches across two working branches → both listed, newest first."""
    repo = makeTestRepoWithSingleCommit(tmp_path)

    # First plate on `main`.
    (repo / TEST_FILENAME).write_text("edit on main\n")
    plate_push(repo, convo_id="t1.jsonl", convo_name="convo-on-main")

    # Force a measurable timestamp gap so committer_unix sort is deterministic.
    time.sleep(1)

    # Second plate on a new branch `feature-x`.
    resetHardToHead(repo)
    createAndCheckoutBranch(repo, "feature-x")
    (repo / TEST_FILENAME).write_text("edit on feature\n")
    plate_push(repo, convo_id="t2.jsonl", convo_name="convo-on-feature")

    result = listPlateBranches(repo)
    assert len(result) == 2
    # Newest first.
    assert result[0]["ref"] == "feature-x-plate"
    assert result[1]["ref"] == "main-plate"
    # Trailers preserved.
    assert result[0]["trailers"]["convo-name"] == "convo-on-feature"
    assert result[1]["trailers"]["convo-name"] == "convo-on-main"
    assert result[0]["trailers"]["parent-branch"] == "feature-x"
    assert result[1]["trailers"]["parent-branch"] == "main"
    # Timestamps strictly ordered after the sleep.
    assert result[0]["committer_unix"] > result[1]["committer_unix"]

def test_listPlateBranches_excludes_non_plate_refs(tmp_path: Path):
    """Plain working branches and unrelated refs are not returned."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    createAndCheckoutBranch(repo, "feature-y")
    # No plate pushed; `feature-y` and `main` are plain branches.
    assert listPlateBranches(repo) == []

def test_saveChangesToPatch(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    modifiedContent = "modified content\n"

    # Modify a tracked file and create an untracked one.
    (repo / TEST_FILENAME).write_text(modifiedContent)
    untrackedName = createUntrackedFile(repo, random.Random())["file"]
    untrackedContent = (repo / untrackedName).read_text()

    patch = saveChangesToPatch(repo, [TEST_FILENAME, untrackedName])

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
    resetHardToHead(repo)
    (repo / untrackedName).unlink()
    assert (repo / TEST_FILENAME).read_text() == TEST_FILE_CONTENTS
    apply_patch(repo, patch)
    assert (repo / TEST_FILENAME).read_text() == modifiedContent
    assert (repo / untrackedName).read_text() == untrackedContent

def test_findMyLastPlate(tmp_path: Path):
    """findMyLastPlate walks the branch and returns most recent matching trailer."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    branch = getCurrentBranchName(repo)
    plate_branch = f"{branch}-plate"

    # No branch yet → (None, None).
    assert findMyLastPlate(repo, plate_branch, "A") == (None, None)

    # Push 3 plates with alternating convo_ids: A, B, A.
    (repo / TEST_FILENAME).write_text("A1\n")
    sha_a1 = plate_push(repo, convo_id="A")
    (repo / TEST_FILENAME).write_text("A1\nB1\n")
    plate_push(repo, convo_id="B")
    (repo / TEST_FILENAME).write_text("A1\nB1\nA2\n")
    sha_a2 = plate_push(repo, convo_id="A")

    # findMyLastPlate("A") returns the most recent A commit (sha_a2) with date.
    sha, date = findMyLastPlate(repo, plate_branch, "A")
    assert sha == sha_a2
    assert sha != sha_a1
    assert date is not None
    # ISO-8601 date with timezone (e.g. "2026-04-30 14:47:14 -0700").
    assert len(date) >= len("2026-04-30 14:47:14 -0700")

    # convo_id not present → (None, None).
    assert findMyLastPlate(repo, plate_branch, "C") == (None, None)

    # Non-existent branch → (None, None).
    assert findMyLastPlate(repo, "nonexistent-plate", "A") == (None, None)

def test_plate_push_1x(tmp_path: Path):
    """Per-function: plate_push contract + fixture-specific stash/checkout flow.

    Shared scenario covers the plate-creation contract; the rest verifies that
    you can stash the conflicting untracked file, check out the plate branch
    to inspect its exact tracked-file list (this fixture: .gitignore + a.txt
    + the new file), then switch back and unstash.
    """
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_push_creates_branch_capturing_wip(repo)

    # Fixture-specific extras: clear the tracked modification (so checkout
    # doesn't conflict on it), stash the untracked, then verify the plate
    # branch's exact tracked-file list via checkout.
    originalBranch = getCurrentBranchName(repo)
    plateBranchName = f"{originalBranch}-plate"
    untrackedFileName = next(
        f for f in getGitUntrackedFilesList(repo) if f.startswith("new-")
    )

    resetHardToHead(repo)
    stashFiles(repo, [untrackedFileName])
    assert getGitUntrackedFilesList(repo) == []

    checkOutBranch(repo, plateBranchName)
    assert sorted(getGitTrackedFilesList(repo)) == sorted(
        [".gitignore", TEST_FILENAME, untrackedFileName]
    )

    checkOutBranch(repo, originalBranch)
    unstashFiles(repo)
    assert getCurrentBranchName(repo) == originalBranch
    assert untrackedFileName in getGitUntrackedFilesList(repo)

def test_plate_push_with_convo_id(tmp_path: Path):
    """plate_push writes parent-branch always, and convo-* trailers when set."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    (repo / TEST_FILENAME).write_text("modified\n")

    sha = plate_push(
        repo,
        convo_id="/Users/me/.claude/projects/proj/abc-123.jsonl",
        convo_name="my titled convo",
        convo_summary="line one\nline two\nline three",
    )
    assert sha is not None

    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    trailers = getCommitTrailers(repo, plateBranchName)

    assert trailers["parent-branch"] == branch
    assert trailers["convo-id"] == "/Users/me/.claude/projects/proj/abc-123.jsonl"
    assert trailers["convo-name"] == "my titled convo"
    # Multi-line summary input collapses to single line of space-joined words.
    assert trailers["convo-summary"] == "line one line two line three"

def test_plate_push_extraction_uses_explicit_transcript_path_arg(tmp_path: Path):
    """Regression for the production-vs-test convo_id semantics mismatch.

    cli.py passes a session UUID as ``convo_id`` and the transcript file
    path as a SEPARATE ``transcript_path`` argument. Earlier code in
    ``_buildExtractedTree`` did ``Path(convo_id)`` and treated the UUID
    as a path; that path doesn't exist, so the extracted tree wound up
    empty and equal to parent_tree, making the second agent's push
    silently no-op even though the transcript actually carried real
    Edit/Write entries. This test pins the explicit-transcript_path
    plumbing so the regression can't return.

    Failing condition: with a UUID convo_id (no path) plus a valid
    transcript_path, the second-agent push returns None instead of
    creating a new commit on ``main-plate``.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    run(["git", "init", QUIET_OUTPUT, CREATE_BRANCH_AND_CHECKOUT_FLAG, "main"], cwd=repo)
    createUserConfig(repo)
    writeGitIgnore(repo)
    addFileToGit(repo, ".gitignore")
    (repo / "a.txt").write_text("base\n")
    addFileToGit(repo, "a.txt")
    createCommit(repo, "initial")

    # Agent A: UUID-style convo_id, transcript stored at a separate path.
    uuid_A = "9f2be37f-0620-4877-b2e5-03c4ac2cdf35"
    transcript_A = tmp_path / f"{uuid_A}.jsonl"
    _writeFakeTranscriptWithToolUse(
        transcript_A,
        [{"timestamp": "2099-01-01T00:00:00.000Z", "tool": "Edit",
          "input": {"file_path": str(repo / "a.txt")}}],
    )
    (repo / "a.txt").write_text("base\nA1\n")
    pa_sha = plate_push(repo, convo_id=uuid_A, transcript_path=str(transcript_A))
    assert pa_sha is not None, "first push must create a plate"

    # Agent B: different UUID, different transcript with a Write entry.
    uuid_B = "11111111-2222-3333-4444-555555555555"
    transcript_B = tmp_path / f"{uuid_B}.jsonl"
    _writeFakeTranscriptWithToolUse(
        transcript_B,
        [{"timestamp": "2099-01-01T00:02:00.000Z", "tool": "Write",
          "input": {"file_path": str(repo / "b.txt")}}],
    )
    (repo / "b.txt").write_text("B")

    pb_sha = plate_push(repo, convo_id=uuid_B, transcript_path=str(transcript_B))
    assert pb_sha is not None, (
        "second-agent push must create a plate when transcript_path resolves "
        "to a real file containing tool_use entries — regression marker for "
        "the Path(convo_id) bug"
    )

    pb_b_content = run(["git", "show", "main-plate:b.txt"], cwd=repo)
    assert pb_b_content == "B"

    trailers = getCommitTrailers(repo, "main-plate")
    assert trailers["convo-id"] == uuid_B, (
        "trailer must carry the UUID we passed, not the transcript path"
    )

def test_plate_push_shared_branch_two_agents_isolates_each_authors_changes(
    tmp_path: Path,
):
    """Integration test for the shared-plate-branch + transcript-extraction model.

    Two agents push commits to the same `<branch>-plate` branch in alternation.
    Each agent's commit must contain only their own attributable changes, not
    the other agent's intervening unplated WT edits.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    run(["git", "init", QUIET_OUTPUT, CREATE_BRANCH_AND_CHECKOUT_FLAG, "main"], cwd=repo)
    createUserConfig(repo)
    writeGitIgnore(repo)
    addFileToGit(repo, ".gitignore")
    (repo / "a.txt").write_text("base\n")
    addFileToGit(repo, "a.txt")
    createCommit(repo, "initial")

    # 1 & 2: Agent A's transcript with one Edit-on-a.txt entry (timestamps far
    # in the future so the cutoff filter never excludes them in this test).
    transcript_A = tmp_path / "transcript_A.jsonl"
    _writeFakeTranscriptWithToolUse(
        transcript_A,
        [{"timestamp": "2099-01-01T00:00:00.000Z", "tool": "Edit",
          "input": {"file_path": str(repo / "a.txt")}}],
    )

    # 3 & 4: WT a.txt = "base\nA1\n"; Agent A plates → Pa1.
    (repo / "a.txt").write_text("base\nA1\n")
    pa1_sha = plate_push(repo, convo_id=str(transcript_A))
    assert pa1_sha is not None
    pa1_a_content = run(["git", "show", "main-plate:a.txt"], cwd=repo)
    assert pa1_a_content == "base\nA1"  # git show strips trailing \n

    # 5: Agent A makes an unplated WT edit to a.txt; transcript adds a 2nd entry
    # (still far-future timestamp; multiple entries deduplicate to one file).
    (repo / "a.txt").write_text("base\nA1\nA2-not-yet-plated\n")
    _writeFakeTranscriptWithToolUse(
        transcript_A,
        [
            {"timestamp": "2099-01-01T00:00:00.000Z", "tool": "Edit",
             "input": {"file_path": str(repo / "a.txt")}},
            {"timestamp": "2099-01-01T00:01:00.000Z", "tool": "Edit",
             "input": {"file_path": str(repo / "a.txt")}},
        ],
    )

    # 6 & 7: Agent B's transcript with one Write-on-b.txt entry; create b.txt.
    transcript_B = tmp_path / "transcript_B.jsonl"
    _writeFakeTranscriptWithToolUse(
        transcript_B,
        [{"timestamp": "2099-01-01T00:02:00.000Z", "tool": "Write",
          "input": {"file_path": str(repo / "b.txt")}}],
    )
    (repo / "b.txt").write_text("B")

    # 8: Agent B plates → Pb1.
    pb1_sha = plate_push(repo, convo_id=str(transcript_B))
    assert pb1_sha is not None

    # 9: Pb1's tree contains a.txt = Pa1's plated version (NOT A2),
    #    b.txt = "B", convo-id trailer = Agent B's transcript path.
    pb1_a_content = run(["git", "show", "main-plate:a.txt"], cwd=repo)
    assert pb1_a_content == "base\nA1"
    assert "A2-not-yet-plated" not in pb1_a_content
    pb1_b_content = run(["git", "show", "main-plate:b.txt"], cwd=repo)
    assert pb1_b_content == "B"
    pb1_trailers = getCommitTrailers(repo, "main-plate")
    assert pb1_trailers["convo-id"] == str(transcript_B)
    # Pb1 parents to Pa1 (linear history on the shared branch).
    assert run(["git", "rev-parse", "main-plate~1"], cwd=repo) == pa1_sha

    # 10: Agent A plates → Pa2 (their own unplated A2 edit is now captured).
    pa2_sha = plate_push(repo, convo_id=str(transcript_A))
    assert pa2_sha is not None

    # 11: Pa2's tree includes A2 line; b.txt carries forward from Pb1.
    pa2_a_content = run(["git", "show", "main-plate:a.txt"], cwd=repo)
    assert pa2_a_content == "base\nA1\nA2-not-yet-plated"
    pa2_b_content = run(["git", "show", "main-plate:b.txt"], cwd=repo)
    assert pa2_b_content == "B"
    pa2_trailers = getCommitTrailers(repo, "main-plate")
    assert pa2_trailers["convo-id"] == str(transcript_A)

    # 12: Agent B "deletes" b.txt — append a Bash rm entry to Agent B's
    #     transcript; actually unlink the file from WT to mirror the rm.
    _writeFakeTranscriptWithToolUse(
        transcript_B,
        [
            {"timestamp": "2099-01-01T00:02:00.000Z", "tool": "Write",
             "input": {"file_path": str(repo / "b.txt")}},
            {"timestamp": "2099-01-01T00:03:00.000Z", "tool": "Bash",
             "input": {"command": f"rm {repo}/b.txt"}},
        ],
    )
    (repo / "b.txt").unlink()

    # 13: Agent B plates → Pb2.
    pb2_sha = plate_push(repo, convo_id=str(transcript_B))
    assert pb2_sha is not None

    # 14: Pb2's tree no longer contains b.txt; a.txt unchanged from Pa2.
    pb2_files = run(
        ["git", "ls-tree", "-r", "--name-only", "main-plate"], cwd=repo
    ).splitlines()
    assert "b.txt" not in pb2_files
    assert "a.txt" in pb2_files
    pb2_a_content = run(["git", "show", "main-plate:a.txt"], cwd=repo)
    assert pb2_a_content == "base\nA1\nA2-not-yet-plated"

def test_plate_push_omits_convo_trailers_when_kwargs_unset(tmp_path: Path):
    """Without convo_* kwargs, only parent-branch is written."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    (repo / TEST_FILENAME).write_text("modified\n")

    sha = plate_push(repo)
    assert sha is not None

    branch = getCurrentBranchName(repo)
    trailers = getCommitTrailers(repo, f"{branch}-plate")
    assert trailers["parent-branch"] == branch
    assert "convo-id" not in trailers
    assert "convo-name" not in trailers
    assert "convo-summary" not in trailers

def test_plate_done(tmp_path: Path):
    """Per-function: 2-plate stack → done cherry-picks both, deletes plate, WT clean."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_done_replays_stack(repo)

def test_plate_drop(tmp_path: Path):
    """Per-function: single plate → drop deletes branch + writes patch.
    Shared scenario covers the contract; runs against the 1-commit fixture."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_drop_deletes_last_plate(repo)

def test_plate_trash(tmp_path: Path):
    """Per-function: 2-plate stack → trash saves patches + deletes branch + WT preserved."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_trash_default_preserves_wt(repo)

def test_plate_trash_hard(tmp_path: Path):
    """Per-function: dirty 2-plate stack → trash --hard saves patches + wipes WT."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_trash_clean_resets_wt(repo)

def test_plate_recycle(tmp_path: Path):
    """Per-function: 2 plates → trash → recycle restores branch with same tree."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_recycle_restores_stack(repo)

def test_simulate_derived_agent_first(tmp_path: Path):
    """Per-function: first derived agent records trailers."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_first_derived_agent_records_trailers(repo)

def test_simulate_derived_agent_second(tmp_path: Path):
    """Per-function: second derived agent extends chain (parent-convo points at previous)."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_second_derived_agent_extends_chain(repo)

def test_apply_patch(tmp_path: Path):
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

    # 4. Call apply_patch(repo, patchPath); expected behavior:
    #    a. Runs `git apply --3way <patch>` on the saved patch.
    #    b. WT now reflects the patched state again.
    apply_patch(repo, patch_path)

    # 5. Assert: tracked file content matches the modified content (post-patch).
    assert (repo / TEST_FILENAME).read_text() == modifiedContent

def test_plate_drop_no_branch(tmp_path: Path, capsys):
    """Per-function: plate_drop with no plate branch warns + returns None."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_drop_no_branch_warns_and_exits(repo, capsys)

def test_plate_trash_no_branch(tmp_path: Path, capsys):
    """Per-function: plate_trash with no plate branch warns + returns None."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_trash_no_branch_warns_and_exits(repo, capsys)

def test_plate_recycle_no_branch(tmp_path: Path, capsys):
    """Per-function: plate_recycle with no trashed session warns + returns None."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_recycle_no_branch_warns_and_exits(repo, capsys)

def test_plate_done_conflict(tmp_path: Path, capsys):
    """Per-function: plate_done's cherry-pick conflict aborts cleanly."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_done_conflict_aborts_and_restores(repo, capsys)

def test_drop_patch_cross_repo_portability(tmp_path: Path):
    """Per-function: drop patch from repoA applies in a separate repoB."""
    repoA = makeTestRepoWithSingleCommit(tmp_path / "a")
    repoB = makeTestRepoWithSingleCommit(tmp_path / "b")
    _check_drop_patch_applies_in_fresh_repo(repoA, repoB)

def test_plate_done_leaves_sha_recoverable(tmp_path: Path):
    """Per-function: plate_done's deleted plate SHA is still in the object DB."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_done_leaves_sha_recoverable(repo)

def test_plate_next_list_shows_plates_sorted_with_current_marker(tmp_path: Path):
    """Per-function: list mode against the single-commit fixture."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_next_list_shows_plates_sorted_with_current_marker(repo)

def test_plate_next_jump_restores_plate_tree_without_post_plate_branch_changes(tmp_path: Path):
    """Per-function: cross-branch jump with readable target transcript."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_next_jump_restores_plate_tree_without_post_plate_branch_changes(repo, tmp_path)

def test_plate_next_jump_lost_message_when_transcript_unreadable(tmp_path: Path):
    """Per-function: lost-path jump, parametrized over summary present/absent."""
    _check_plate_next_jump_lost_message_when_transcript_unreadable(tmp_path)

def test_plate_next_jump_self_index_is_noop(tmp_path: Path):
    """Per-function: picking the current plate's index is a no-op."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_next_jump_self_index_is_noop(repo, tmp_path)

def test_plate_next_jump_proceeds_when_head_on_branch_with_no_plate(tmp_path: Path):
    """Per-function: jump from a plate-less branch proceeds normally."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_next_jump_proceeds_when_head_on_branch_with_no_plate(repo, tmp_path)

def test_plate_next_jump_invalid_index_returns_message(tmp_path: Path):
    """Per-function: invalid index returns user-facing message, no side effects."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_next_jump_invalid_index_returns_message(repo, tmp_path)

def test_plate_next_list_empty_when_no_plates(tmp_path: Path):
    """Per-function: list mode on a repo with no plates returns the friendly
    empty-list message."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_next_list_empty_when_no_plates(repo)

def test_plate_next_list_no_marker_when_head_has_no_plate(tmp_path: Path):
    """Per-function: list mode marks no entries when HEAD has no plate."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_next_list_no_marker_when_head_has_no_plate(repo, tmp_path)

def test_rewriteBranchTipSummary_strips_old_tip_and_adds_new_tip_summary(tmp_path: Path) -> None:
    """Per-function: rebase-reword strips old summary, writes new on tip."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_rewriteBranchTipSummary_strips_old_tip_and_adds_new_tip_summary(repo)

# ── setup_repo ────────────────────────────────────────────────────────

def test_setup_repo_checks_out_non_main_branch(repo: Path) -> None:
    """Working branch is randomized but is never 'main'."""
    branch = getCurrentBranchName(repo)
    assert branch
    assert branch != "main"


def test_setup_repo_branch_name_is_varied(tmp_path: Path) -> None:
    """Two fresh repos in succession should pick different branch names."""
    from plate_lib import setup_repo

    seen = set()
    for i in range(10):
        r = setup_repo(tmp_path / f"r{i}")
        seen.add(getCurrentBranchName(r))
    # Variance means we shouldn't always get the same name 10 times.
    assert len(seen) > 1


def test_setup_repo_creates_three_commits(repo: Path) -> None:
    assert countCommitsReachableFromRef(repo, "HEAD") == 3


def test_setup_repo_main_has_one_commit(repo: Path) -> None:
    assert countCommitsReachableFromRef(repo, "main") == 1


def test_setup_repo_starts_clean(repo: Path) -> None:
    assert checkForCleanWorkTree(repo)


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


# ── performRandomEdit ───────────────────────────────────────────────────────

def test_performRandomEdit_dirties_wt(repo: Path) -> None:
    assert checkForCleanWorkTree(repo)
    performRandomEdit(repo, seed=0)
    assert not checkForCleanWorkTree(repo)


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
    from plate_lib import setup_repo

    other = setup_repo(tmp_path / "other")
    b = performRandomEdit(other, seed=12345)
    assert a == b


def test_performRandomEdit_unseeded_works(repo: Path) -> None:
    """No seed → still produces a valid edit (non-deterministic)."""
    result = performRandomEdit(repo)
    assert result["action"] in ("modify_tracked", "create_untracked")
    assert not checkForCleanWorkTree(repo)


# ── plate operation sequence specs ───────────────────────────────────

def test_sequence_01_plate_push_first_time_preserves_user_workspace(repo: Path) -> None:
    # 1. User starts on a non-main branch with no plate branch.
    # 2. User edits a tracked file and creates an untracked file.
    # 3. User runs plate_push(repo).
    # 4. Plate branch is created parented to HEAD, captures both edits,
    #    returns its tip SHA, and leaves WT/HEAD/branch unchanged.
    _check_plate_push_creates_branch_capturing_wip(repo)


def test_sequence_02_plate_push_second_time_extends_plate_stack(repo: Path) -> None:
    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    head_before = getSHAForRefViaRevParse(repo, "HEAD")

    # 1. Edit A: modify a tracked file. Run plate_push → P1.
    (repo / TEST_FILENAME).write_text("edit A\n")
    p1_sha = plate_push(repo)
    assert p1_sha is not None
    assert getSHAForRefViaRevParse(repo, plateBranchName) == p1_sha

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
    assert getSHAForRefViaRevParse(repo, plateBranchName) == p2_sha
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
    assert getSHAForRefViaRevParse(repo, "HEAD") == head_before
    assert (repo / TEST_FILENAME).read_text() == "edit A\nedit B\n"
    assert untracked_b in getGitUntrackedFilesList(repo)


def test_sequence_03_plate_done_replays_stack_and_cleans_workspace(repo: Path) -> None:
    # 1. User creates P1 with edit A.
    # 2. User creates P2 with edit B.
    # 3. User runs plate_done(repo).
    # 4. Branch receives both plate commits oldest-first, plate ref deleted,
    #    WT clean, branch tree == former P2 tree.
    _check_plate_done_replays_stack(repo)


def test_sequence_04_plate_done_captures_unpushed_work_before_cleanup(repo: Path) -> None:
    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    branch_count_before = countCommitsReachableFromRef(repo, branch)

    # 1. Edit A: create untracked file U_A, push as P1.
    u_a = createUntrackedFile(repo, random.Random())["file"]
    plate_push(repo)
    assert branchExists(repo, plateBranchName)

    # 2. Edit B: create untracked file U_B but DO NOT plate_push it.
    u_b = createUntrackedFile(repo, random.Random())["file"]
    # Sanity: P1 captured U_A but not U_B (U_B was created after).
    p1_files = run(
        ["git", "ls-tree", "-r", "--name-only", plateBranchName], cwd=repo
    ).splitlines()
    assert u_a in p1_files
    assert u_b not in p1_files

    # 3. plate_done — Step 0's implicit pre-push must capture U_B before the
    #    Step 1 reset/clean would otherwise destroy it.
    plate_done(repo)

    # 4a. Plate ref deleted.
    assert not branchExists(repo, plateBranchName)
    # 4b. Branch received TWO commits (P1 + the implicit pre-push that
    #     captured U_B). Without the implicit pre-push, only P1 lands and
    #     U_B is lost during clean -fd.
    assert countCommitsReachableFromRef(repo, branch) == branch_count_before + 2
    # 4c. WT clean — both files are now tracked.
    assert checkForCleanWorkTree(repo)
    tracked = getGitTrackedFilesList(repo)
    assert u_a in tracked
    assert u_b in tracked


def test_sequence_05_plate_drop_removes_top_plate_only(repo: Path) -> None:
    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    rng = random.Random()
    # 1. P1: edit A — create untracked U_A, push.
    u_a = createUntrackedFile(repo, rng)["file"]
    plate_push(repo)
    p1_sha = getSHAForRefViaRevParse(repo, plateBranchName)

    # 2. P2: edit B — create untracked U_B, push.
    u_b = createUntrackedFile(repo, rng)["file"]
    p2_sha = plate_push(repo)
    assert getSHAForRefViaRevParse(repo, plateBranchName) == p2_sha

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
    assert branchExists(repo, plateBranchName)
    assert getSHAForRefViaRevParse(repo, plateBranchName) == p1_sha
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


def test_sequence_07_apply_patch_recovers_dropped_plate_work(repo: Path) -> None:
    # 1. User creates a single plate P1.
    # 2. User runs plate_drop(repo) and keeps the generated patch path.
    # 3. User resets/cleans the repo back to branch HEAD.
    # 4. User runs apply_patch(repo, patch).
    # 5. WT contains the dropped plate work again byte-for-byte.
    _check_plate_drop_then_apply_patch_round_trip(repo)


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


def test_sequence_18_plate_done_aborts_cleanly_on_cherry_pick_conflict(
    repo: Path, capsys
) -> None:
    # 1. User edits a tracked file and plate_pushes (P1 captures "plate
    #    version").
    # 2. User resets WT and commits a CONFLICTING edit ("branch version")
    #    on the working branch HEAD — the same line is now divergent.
    # 3. User runs plate_done(repo). Cherry-pick conflicts on the shared
    #    line.
    # 4. plate_done aborts the cherry-pick, restores HEAD/WT to pre-call
    #    state, preserves <branch>-plate so the original plate tip is
    #    still reachable, and warns on stderr. No CHERRY_PICK_HEAD lingers.
    _check_plate_done_conflict_aborts_and_restores(repo, capsys)


def test_sequence_19_drop_patch_is_portable_across_repos(tmp_path: Path) -> None:
    # 1. Two separate clones (repoA and repoB) of the same project, both
    #    sharing the same TEST_FILENAME content at HEAD.
    # 2. In repoA: edit TEST_FILENAME, create an untracked file, plate_push,
    #    plate_drop → produces a portable .patch file.
    # 3. The .patch file is copied into repoB (e.g., emailed to a teammate).
    # 4. In repoB: apply_patch(repoB, patch) restores the dropped edits
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
