"""Shared helpers for the /plate sequence test harness.

Plate operations (all implemented):
    plate_push, plate_done, plate_drop, plate_trash, plate_recycle,
    plate_next, simulate_derived_agent, apply_patch

`plate_push` writes commit trailers — `parent-branch` always; `convo-id`,
`convo-name`, `convo-summary` when the matching kwarg is non-None.

Transcript helpers (read Claude Code JSONL session files):
    extractConvoNameFromTranscript, extractConvoCwdFromTranscript,
    localTranscriptIsReadable

Listing / formatting helpers:
    formatPlateAge, listPlateBranches

Repo / commit utilities:
    setup_repo, makeTestRepoWithSingleCommit, performRandomEdit,
    getCurrentBranchName, branchExists, countCommitsReachableFromRef,
    getTreeSHA, getGitStatus, checkForCleanWorkTree, getCommitSubject,
    getCommitTrailers, saveChangesToPatch, resetHardToHead,
    cleanWorkTree, deleteBranchForce, makeTempGitIndexPath, ...

See `skills/plate/PLATE STATE.md` for the operational gap analysis and
`plans/plate-walkthrough-log-2026-04-28.md` for the canonical sequences.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import string
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

# -- git command flags used by helpers below --

QUIET_OUTPUT = "-q"
COMMIT_MESSAGE_FLAG = "-m"
CREATE_BRANCH_AND_CHECKOUT_FLAG = "-b"

# ── Subprocess wrapper ────────────────────────────────────────────────

def run(
    cmd: list[str],
    cwd: Path,
    env: Optional[dict[str, str]] = None,
    check: bool = True,
    capture: bool = True,
) -> str:
    """Run cmd in cwd. Return stripped stdout when capture=True."""
    full_env: Optional[dict[str, str]] = None
    if env is not None:
        full_env = os.environ.copy()
        full_env.update(env)
    completed = subprocess.run(
        cmd,
        cwd=cwd,
        env=full_env,
        text=True,
        capture_output=capture,
        check=check,
    )
    if not capture:
        return ""
    return (completed.stdout or "").strip()

def test_run():
    result = run(["ls", "-l"], cwd=Path("."))
    assert result is not None
    
# ── Implemented: repo setup ───────────────────────────────────────────

def createRandomBranchName() -> str:
    """Generate a varied branch name to simulate real user environments
    with diverse branch naming conventions. Uses one of several common
    prefixes plus a random alphanumeric suffix."""
    prefixes = [
        "feature-",
        "fix-",
        "hotfix-",
        "refactor-",
        "wip-",
        "experiment-",
        "task-",
    ]
    prefix = random.choice(prefixes)
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return prefix + suffix

COMMIT_MESSAGE_FLAG = "-m"
CREATE_BRANCH_AND_CHECKOUT_FLAG = "-b"

def makeEmptyRepo(path: Path) -> Path:
    """Create a new, empty repo with a single main branch."""
    repo = path / "repo"
    repo.mkdir(parents=True)                               
    run(["git", "init", QUIET_OUTPUT, CREATE_BRANCH_AND_CHECKOUT_FLAG, "main"],
cwd=repo)                                                 
    return repo 

# def getGitStatus(repo: Path) -> dict[str, str]:
#     return run(["git", "status", "--porcelain"], cwd=repo).splitlines()

def isGitRepo(path: Path) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(path), "rev-parse",
"--is-inside-work-tree"],                                  
        capture_output=True,
        check=False,                                       
    )                         
    return completed.returncode == 0   

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

def setUserConfigValue(repo: Path, config_key: str, config_value: str) -> None:
    run(["git", "config", config_key, config_value], cwd=repo)

def getUserConfigValue(repo: Path, config_key: str) -> str:
    return run(["git", "config", config_key], cwd=repo)

def makeTestRepo(base: Path) -> Path:
    repo = makeEmptyRepo(path=base)
    createUserConfig(repo)
    return repo

USER_EMAIL_KEY = "user.email"
USER_EMAIL_VALUE = "test@example.com"
USER_NAME_KEY = "user.name"
USER_NAME_VALUE = "Test User"
TEST_COMMIT_MESSAGE = "test commit"
TEST_FILENAME = "a.txt"
GITIGNORE_CONTENTS = ".plate/\n"

def writeGitIgnore(repo: Path, contents: str = GITIGNORE_CONTENTS) -> Path:
    """Write a .gitignore file at repo root and return its path.

    Default contents ignore the /plate skill's local stash directory
    (.plate/) so it is treated as ignored rather than untracked, which
    means `git clean -fd` won't blow it away (that requires `-x`).
    """
    path = repo / ".gitignore"
    path.write_text(contents)
    return path

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

def makeTestRepoWithSingleCommit(base: Path) -> Path:
    repo = makeTestRepo(base=base)
    # Ignore .plate/ so the skill's stash dir survives `git clean -fd`.
    writeGitIgnore(repo)
    addFileToGit(repo, ".gitignore")
    # add the test file
    addFileToGit(repo, makeTestFile(repo, TEST_FILENAME))
    # commit both files together as the initial commit
    createCommit(repo, TEST_COMMIT_MESSAGE)
    return repo

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

def createUserConfig(repo: Path) -> None:
    setUserConfigValue(repo, USER_EMAIL_KEY, USER_EMAIL_VALUE)
    setUserConfigValue(repo, USER_NAME_KEY, USER_NAME_VALUE)

def test_createUserConfig(tmp_path: Path): 
    repo = makeTestRepo(base=tmp_path)
    assert getUserConfigValue(repo, USER_EMAIL_KEY) == USER_EMAIL_VALUE
    assert getUserConfigValue(repo, USER_NAME_KEY) == USER_NAME_VALUE

def getGitBranchList(repo: Path) -> list[str]:
    # git branch --list
    result = run(["git", "branch", "--list"], cwd=repo).splitlines()
    # remove the leading characters (* , +)
    cleanedBranchNames = []
    for line in result:
        print( "branch: " + line)
        cleaned = line.replace("*", "").replace("+", "").strip()
        print( "cleaned: " + cleaned )
        cleanedBranchNames.append(cleaned)
    return cleanedBranchNames

def createBranch(repo: Path, branch_name: str) -> None:
    # git branch -q <branch-name>
    run(["git", "branch", QUIET_OUTPUT, branch_name], cwd=repo)

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

def checkOutBranch(repo: Path, branch_name: str) -> None:
    # git checkout -q <branch-name>
    run(["git", "checkout", QUIET_OUTPUT, branch_name], cwd=repo)

def test_checkOutBranch(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(base=tmp_path)
    branch_name = createRandomBranchName()
    createBranch(repo, branch_name)
    checkOutBranch(repo=repo, branch_name=branch_name)
    assert getCurrentBranchName(repo) == branch_name

def createAndCheckoutBranch(repo: Path, branch_name: str) -> None:
    run(["git", "checkout", QUIET_OUTPUT, CREATE_BRANCH_AND_CHECKOUT_FLAG, branch_name], cwd=repo)

def test_createAndCheckoutBranch(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(base=tmp_path)
    branch_name = createRandomBranchName()
    createAndCheckoutBranch(repo, branch_name)
    branches = getGitBranchList(repo)
    print(branch_name)
    print(branches)
    assert branch_name in getGitBranchList(repo)
    assert getCurrentBranchName(repo) == branch_name

def getCurrentBranchName(repo: Path) -> str:
    """Return the current branch name (e.g. 'fix')."""
    # git branch --show-current
    return run(["git", "branch", "--show-current"], cwd=repo)

def test_getCurrentBranchName(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    assert getCurrentBranchName(repo) == "main"

TEST_FILE_CONTENTS = "A\n"

def makeTestFile(repo: Path, fileName: str) -> Path:
    file = repo / fileName
    file.write_text(TEST_FILE_CONTENTS)
    return file

def test_makeTestFile(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    fileName = TEST_FILENAME
    file = makeTestFile(repo, fileName)
    assert file == repo / fileName
    assert file.exists()
    assert file.read_text() == TEST_FILE_CONTENTS

def getGitUntrackedFilesList(repo: Path) -> list[str]:
    # git ls-files --others --exclude-standard
    return run(["git", "ls-files", "--others", "--exclude-standard"], cwd=repo).splitlines()

def getGitUnstagedFilesList(repo: Path) -> list[str]:
    # git ls-files --modified
    return run(["git", "ls-files", "--modified"], cwd=repo).splitlines()

def getGitStagedFilesList(repo: Path) -> list[str]:
    # git diff --name-only --cached
    return run(["git", "diff", "--name-only", "--cached"], cwd=repo).splitlines()

def getGitTrackedFilesList(repo: Path) -> list[str]:
    return run(["git", "ls-files"], cwd=repo).splitlines()

def addFileToGit(repo: Path, file: str) -> None:
    run(["git", "add", file], cwd=repo)

def stageAllChanges(repo: Path, env: dict[str, str] | None = None) -> None:
    run(["git", "add", "-A"], cwd=repo, env=env)

def stashFiles(repo: Path, files: list[str]) -> None:
    """Stash the named files (tracked or untracked) and remove them from WT.

    Uses `git stash push -u --` so that untracked files in <files> are
    included in the stash. After the call, the named files are gone from
    the WT and saved on the top of the stash stack (stash@{0}). Use
    unstashFiles() to restore them.
    """
    run(["git", "stash", "push", "-u", QUIET_OUTPUT, "--"] + files, cwd=repo)

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

def unstashFiles(repo: Path) -> None:
    """Pop the top of the stash stack back into the WT (stash@{0})."""
    run(["git", "stash", "pop", QUIET_OUTPUT], cwd=repo)

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

def addMultipleFilesToGit(repo: Path, files: list[str]) -> None:
    run(["git", "add"] + files, cwd=repo)

def test_stageFiles(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    fileNames = [TEST_FILENAME, "b.txt"]  
    files = []
    for fileName in fileNames:
        files.append(makeTestFile(repo, fileName))
    addMultipleFilesToGit(repo=repo, files=files)
    assert getGitStagedFilesList(repo) == fileNames
    assert getGitUntrackedFilesList(repo) == []

def createCommit(repo: Path, message: str) -> None:
    run(["git", "commit", QUIET_OUTPUT, COMMIT_MESSAGE_FLAG, message], cwd=repo)

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

def random_string(length: int = 8, rng: random.Random = random) -> str:
    return "".join(rng.choices(string.ascii_lowercase, k=length))

# ── Implemented: simulate user edits ──────────────────────────────────
def modifyTrackedFile(repo: Path, file: str, rng: random.Random) -> dict:
    path = repo / file
    path.write_text(path.read_text() + f"random-{random_string(rng=rng)}\n")
    return {"action": "modify_tracked", "file": path.name}

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

def modifyRandomlyChosenTrackedFile(
    repo: Path,
    files: list[str],
    rng: random.Random = random,
):
    # randomly choose a file from <files> using the supplied rng so that
    # callers passing a seeded rng get deterministic behavior.
    fileName = rng.choice(files)
    return modifyTrackedFile(repo, fileName, rng=rng)

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

def createUntrackedFile(repo: Path, rng: random.Random) -> dict:
    name = f"new-{random_string(rng=rng)}.txt"
    path = repo / name
    path.write_text(f"content-{random_string(rng=rng)}\n")
    return {"action": "create_untracked", "file": name}

def test_createUntrackedFile(tmp_path: Path):
    # create a test repo
    repo = makeTestRepo(base=tmp_path)
    # add a file to it
    file = createUntrackedFile(repo, rng=random.Random())
    # assert it is untracked
    assert getGitUntrackedFilesList(repo) == [file["file"]]

B_FILENAME = "b.txt"
B_FILE_CONTENTS = "B\n"
F1_FILENAME = "fix.txt"
F1_FILE_CONTENTS = "F1\n"

def setup_repo(base: Path) -> Path:
    """Create a fresh git repo at base/repo and return its path.

    Topology:
        main:      A         (root commit)
                   \\
        <random>:   B - F1   (checked out, clean WT)

    The non-main branch name is randomized per call to mimic real-world
    variance. Tests should query it via getCurrentBranchName(repo) rather
    than hardcoding a value.

    Files:
        a.txt   on main,           content "A"
        b.txt   on <random branch>, content "B"
        fix.txt on <random branch>, content "F1"
    """
    repo = makeEmptyRepo(path=base)
    createUserConfig(repo)

    # main: commit A — also stages .gitignore so .plate/ is ignored
    # and survives `git clean -fd` during plate_trash(clean_wt=True).
    writeGitIgnore(repo)
    addFileToGit(repo, ".gitignore")
    (repo / TEST_FILENAME).write_text(TEST_FILE_CONTENTS)
    addFileToGit(repo, TEST_FILENAME)
    createCommit(repo=repo, message="A")

    # randomly-named branch off main, with B and F1 commits
    branch_name = createRandomBranchName()
    createBranch(repo, branch_name)
    checkOutBranch(repo=repo, branch_name=branch_name)
    
    (repo / B_FILENAME).write_text(B_FILE_CONTENTS)
    addFileToGit(repo, B_FILENAME)
    createCommit(repo=repo, message="B")

    (repo / F1_FILENAME).write_text(F1_FILE_CONTENTS)
    addFileToGit(repo, F1_FILENAME)
    createCommit(repo=repo, message="F1")

    return repo

def test_setup_repo(tmp_path: Path):                     
    repo = setup_repo(tmp_path)                            
    assert checkForCleanWorkTree(repo)
    assert getCurrentBranchName(repo) != "main"            
    assert countCommitsReachableFromRef(repo, "main") == 1 
    assert countCommitsReachableFromRef(repo, "HEAD") == 3
    assert (repo / TEST_FILENAME).read_text() == TEST_FILE_CONTENTS           
    assert (repo / B_FILENAME).read_text() == B_FILE_CONTENTS          
    assert (repo / F1_FILENAME).read_text() == F1_FILE_CONTENTS

def performRandomEdit(repo: Path, seed: Optional[int] = None) -> dict:
    """Make a random edit to the repo to simulate user activity.

    Picks one of:
        modify_tracked    append a random line to an existing tracked file
        create_untracked  create a new untracked file with random content

    Returns a dict describing the action, e.g.:
        {"action": "modify_tracked", "file": "fix.txt"}
        {"action": "create_untracked", "file": "new-abcd.txt"}
    """
    rng = random.Random(seed) if seed is not None else random

    tracked = getGitTrackedFilesList(repo=repo)
    actions = ["modify_tracked", "create_untracked"]
    # if there are no tracked files, remove modify_tracked from actions
    if not tracked:
        actions.remove("modify_tracked")

    action = rng.choice(actions)

    if action == "modify_tracked":
        return modifyRandomlyChosenTrackedFile(repo, tracked, rng=rng)

    return createUntrackedFile(repo, rng)

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

# ── Implemented: assertion utilities ──────────────────────────────────

def branchExists(repo: Path, branchName: str) -> bool:
    """True iff refs/heads/<branchName> exists."""
    # git branch --list <branchName>
    list_output = run(["git", "branch", "--list"], cwd=repo)
    # strip out any * in the branch names
    list_output = list_output.replace("*", "")
    # the branch exists if its name appears in the list of branches
    return branchName in list_output

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

def countCommitsReachableFromRef(repo: Path, ref: str) -> int:
    """Number of commits reachable from <ref>."""
    return int(run(["git", "rev-list", "--count", ref], cwd=repo))

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

def setGitIndexFileForEnv(env: dict[str, str], gitIndexFile: str) -> dict[str, str]:
    env["GIT_INDEX_FILE"] = gitIndexFile
    return env

def getSHAForRefViaRevParse(repo: Path, ref: str) -> str:
    return run(["git", "rev-parse", ref], cwd=repo)

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

def readGitTreeAt(repo: Path, ref: str, env: dict[str, str]) -> str:
    return run(["git", "read-tree", ref], cwd=repo, env=env)

def writeGitTree(repo: Path, env: dict[str, str]) -> str:
    return run(["git", "write-tree"], cwd=repo, env=env)

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

def getTreeRevOf(commit: str) -> str:                      
    """Return the git rev-spec that peels <commit> to its tree.
    The returned string is a rev-spec (e.g. 'abc1234^{tree}'), NOT a SHA. 
    Pass it to git rev-parse — or any command taking a <rev> — to resolve it to the SHA of the commit's tree.
    """
    return f"{commit}^{{tree}}"   

def test_getTreeRevOf():      
    assert getTreeRevOf("abc123") == "abc123^{tree}"   

def getTreeSHA(repo: Path, ref: str) -> str:
    """SHA of the tree pointed to by <ref>."""
    return getSHAForRefViaRevParse(repo, getTreeRevOf(ref))

def getGitStatus(repo: Path) -> str:
    """Output of `git status --porcelain` (empty string when clean)."""
    return run(["git", "status", "--porcelain"], cwd=repo)

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

def checkForCleanWorkTree(repo: Path) -> bool:
    """True iff WT and index match HEAD with no untracked files."""
    return getGitStatus(repo) == ""

def test_checkForCleanWorkTree(tmp_path: Path):
    # make a test repo
    repo = makeTestRepoWithSingleCommit(tmp_path)
    # assert that worktree has no changes 
    assert checkForCleanWorkTree(repo)

def getCommitSubject(repo: Path, ref: str) -> str:
    """Subject line of the commit at <ref>."""
    return run(["git", "log", "-1", "--format=%s", ref], cwd=repo)

def test_getCommitSubject(tmp_path: Path):
    # make a test repo
    repo = makeTestRepoWithSingleCommit(tmp_path)
    # assert that main has 1 commit
    assert getCommitSubject(repo, "main") == TEST_COMMIT_MESSAGE

def getCommitTrailers(repo: Path, ref: str) -> dict[str, str]:
    """Commit message trailers at <ref> as a key→value dict.

    Trailers are git's RFC822-style key/value lines at the end of the
    commit message body, e.g. `parent-convo: 123`. Used by /plate to
    encode parent_ref / plate_id / convo_id without polluting the
    user-visible commit subject.
    """
    raw = run(
        ["git", "log", "-1", "--format=%(trailers:only,unfold=true)", ref],
        cwd=repo,
    )
    trailers: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            trailers[key.strip()] = value.strip()
    return trailers

def test_getCommitTrailers(tmp_path: Path):
    repo = makeTestRepo(tmp_path)
    addFileToGit(repo, makeTestFile(repo, "a.txt"))        
    run(["git", "commit", "-q", "-m", "subject\n\nbody line\n\nparent-convo: abc\nplate-id: 42"], cwd=repo)                             
    trailers = getCommitTrailers(repo, "HEAD")             
    assert trailers == {"parent-convo": "abc", "plate-id": 
"42"}          

# ── Helpers used by the plate operations ─────────────────────────────

def resetHardToHead(repo: Path) -> None:
    """git reset --hard — restore tracked files to HEAD's state."""
    run(["git", "reset", QUIET_OUTPUT, "--hard"], cwd=repo)

def test_resetHardToHead(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    (repo / TEST_FILENAME).write_text("dirty\n")
    assert (repo / TEST_FILENAME).read_text() == "dirty\n"
    resetHardToHead(repo)
    assert (repo / TEST_FILENAME).read_text() == TEST_FILE_CONTENTS

def cleanWorkTree(repo: Path) -> None:
    """git clean -fd — delete untracked files and untracked directories.

    Ignored paths (e.g. anything matching .gitignore) are preserved
    because `git clean -fd` does NOT touch them without the `-x` flag.
    """
    run(["git", "clean", "-fd", QUIET_OUTPUT], cwd=repo)

def test_cleanWorkTree(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    untrackedName = createUntrackedFile(repo, random.Random())["file"]
    assert (repo / untrackedName).exists()
    cleanWorkTree(repo)
    assert not (repo / untrackedName).exists()
    assert getGitUntrackedFilesList(repo) == []

def deleteBranchForce(repo: Path, branchName: str) -> None:
    """git branch -D <name> — delete branch even if not merged."""
    run(["git", "branch", "-D", QUIET_OUTPUT, branchName], cwd=repo)

def test_deleteBranchForce(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    name = createRandomBranchName()
    createBranch(repo, name)
    assert branchExists(repo, name)
    deleteBranchForce(repo, name)
    assert not branchExists(repo, name)

def currentTimestampMs() -> str:
    """Millisecond-resolution timestamp for patch-file naming."""
    return str(int(time.time() * 1000))

def formatPlateAge(seconds: int) -> str:
    """Format an age in seconds as the listing-style age string.

    Drops sub-minute precision. Skips leading zero units. Always shows
    minutes as the smallest unit.

        formatPlateAge(0)       == "0m"
        formatPlateAge(59)      == "0m"
        formatPlateAge(60)      == "1m"
        formatPlateAge(32 * 60) == "32m"
        formatPlateAge(14 * 3600 + 7 * 60) == "14h 7m"
        formatPlateAge(3 * 86400 + 2 * 3600 + 5 * 60) == "3d 2h 5m"
    """
    if seconds < 0:
        seconds = 0
    minutes_total = seconds // 60
    days, rem_minutes = divmod(minutes_total, 24 * 60)
    hours, minutes = divmod(rem_minutes, 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


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


# ── Transcript helpers (Claude Code JSONL session files) ──────────────

def localTranscriptIsReadable(transcript_path: Optional[str]) -> bool:
    """True iff transcript_path points at a readable file on this machine.

    Used by jump-mode to decide between the local-resume and remote-handoff
    paths. Empty string and None both return False.
    """
    if not transcript_path:
        return False
    try:
        path = Path(transcript_path)
        return path.is_file() and os.access(str(path), os.R_OK)
    except OSError:
        return False


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


def extractConvoNameFromTranscript(transcript_path: Path) -> Optional[str]:
    """Return the latest customTitle from a Claude Code JSONL transcript.

    Walks the file line-by-line, JSON-decoding each, and tracks the most
    recent `custom-title` event's `customTitle`. If no `custom-title`
    event exists, falls back to the session id (transcript filename
    without the .jsonl extension). Returns None only if the file itself
    can't be opened.
    """
    path = Path(transcript_path)
    try:
        latest = None
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if record.get("type") == "custom-title":
                    title = record.get("customTitle")
                    if isinstance(title, str):
                        latest = title
        if latest is not None:
            return latest
        # No rename event — session id from filename is the canonical handle.
        return path.stem
    except OSError:
        return None


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


def extractConvoCwdFromTranscript(transcript_path: Path) -> Optional[str]:
    """Return the cwd of the conversation as recorded in the transcript.

    Walks the file line-by-line and returns the first `cwd` field found.
    Returns None if the file is missing/unreadable or no record carries
    a `cwd` field. Jump-mode treats None as 'transcript not available
    locally' and routes to the remote-handoff path.
    """
    path = Path(transcript_path)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                cwd = record.get("cwd")
                if isinstance(cwd, str) and cwd:
                    return cwd
        return None
    except OSError:
        return None


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


_FILE_MODIFYING_TOOL_NAMES = frozenset(
    {"Edit", "Write", "MultiEdit", "NotebookEdit"}
)


def extractFilesEditedSinceTimestamp(
    transcript_path: Path,
    since_iso: Optional[str],
) -> list[str]:
    """Return absolute file paths from the transcript's tool_use entries
    that modified files (`Edit`, `Write`, `MultiEdit`, `NotebookEdit`),
    filtered to records with `timestamp > since_iso` (strict greater-than).

    `since_iso=None` returns all matching entries (no cutoff). Returns
    `[]` when the transcript can't be opened.

    Used by `plate_push`'s author-detection branch to determine which
    files this agent has touched since their last plate commit.
    """
    files: set[str] = set()
    try:
        with Path(transcript_path).open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                ts = record.get("timestamp")
                if since_iso is not None:
                    if not isinstance(ts, str) or ts <= since_iso:
                        continue
                # tool_use blocks live under message.content[].
                content = record.get("message", {}).get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    if block.get("name") not in _FILE_MODIFYING_TOOL_NAMES:
                        continue
                    file_path = block.get("input", {}).get("file_path")
                    if isinstance(file_path, str) and file_path:
                        files.add(file_path)
    except OSError:
        return []
    return sorted(files)


def _writeFakeTranscriptWithToolUse(
    path: Path,
    entries: list[dict],
) -> Path:
    """Helper for tests: write a minimal JSONL transcript where each entry is a
    top-level `assistant` record carrying a tool_use block in
    `message.content`. Each `entries[i]` dict needs keys:
        timestamp: ISO-8601 string
        tool:      tool name (Edit/Write/Read/Bash/...)
        input:     dict for the tool's input
    """
    lines = []
    for e in entries:
        lines.append(json.dumps({
            "type": "assistant",
            "timestamp": e["timestamp"],
            "message": {
                "content": [{
                    "type": "tool_use",
                    "id": f"toolu_{e['timestamp']}",
                    "name": e["tool"],
                    "input": e["input"],
                }],
            },
        }))
    path.write_text("\n".join(lines) + "\n")
    return path


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


_SHELL_EXPANSION_CHARS = frozenset("$`*?[]{}()<>")


def _parseRmTargets(cmd: str, repo_root_resolved: Path) -> set[str]:
    """Find literal file path arguments after `rm` (or `/bin/rm`) tokens in a
    shell command string. Returns repo-relative paths for arguments that
    resolve inside `repo_root_resolved`. Skips shell-expanded args
    ($, backtick, *, ?, [, {), flag tokens (starting with -), and resets
    on shell separators (&&, ||, ;, |).

    `git rm <file>` works because the loop skips "git" (not a trigger),
    then sees "rm" and starts collecting. `git rm --cached <file>` also
    works — the `--cached` flag is skipped by the dash-prefix rule.
    """
    import shlex
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return set()

    targets: set[str] = set()
    in_rm = False
    for tok in tokens:
        if tok in ("&&", "||", ";", "|"):
            in_rm = False
            continue
        if tok in ("rm", "/bin/rm"):
            in_rm = True
            continue
        if not in_rm:
            continue
        if tok.startswith("-"):
            continue
        if any(c in tok for c in _SHELL_EXPANSION_CHARS):
            continue
        try:
            p = (repo_root_resolved / tok).resolve()
            rel = p.relative_to(repo_root_resolved)
        except (OSError, ValueError):
            continue
        targets.add(str(rel))
    return targets


def extractFilesDeletedSinceTimestamp(
    transcript_path: Path,
    since_iso: Optional[str],
    repo_root: Path,
) -> list[str]:
    """Return repo-relative file paths from `Bash` tool_use commands that
    look like `rm` or `git rm` invocations and resolve INSIDE `repo_root`.

    Filtered to records with `timestamp > since_iso` (strict greater-than).
    `since_iso=None` returns all matching entries. Returns `[]` when the
    transcript can't be opened.

    Heuristic — won't catch `rm $(...)` or other shell expansions; won't
    catch `find ... -delete`. Common literal cases work.

    The tracked-at-prev-plate filter (to skip `<repo>/tmp/` scratch files
    that aren't part of the project's tracked tree) is applied by the
    caller, not here — `plate_push` has the prev-plate SHA available and
    can run `git ls-tree` against it.
    """
    files: set[str] = set()
    repo_root_resolved = Path(repo_root).resolve()
    try:
        with Path(transcript_path).open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                ts = record.get("timestamp")
                if since_iso is not None:
                    if not isinstance(ts, str) or ts <= since_iso:
                        continue
                content = record.get("message", {}).get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    if block.get("name") != "Bash":
                        continue
                    cmd = block.get("input", {}).get("command", "")
                    if not isinstance(cmd, str):
                        continue
                    files.update(_parseRmTargets(cmd, repo_root_resolved))
    except OSError:
        return []
    return sorted(files)


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


def listPlateBranches(repo: Path) -> list[dict]:
    """Return all plate-related branch refs in the repo, newest first.

    A ref is considered plate-related if its short name ends in `-plate`
    or contains `-plate-derived`. For each, returns:
        {
          "ref":             e.g. "feature-x-plate"
          "tip_sha":         SHA of the tip commit
          "committer_unix":  int epoch seconds of the tip's committer date
          "trailers":        dict of commit trailers on the tip
        }

    Sorted by committer_unix descending (most recent commit first).
    Used by both `_plate_next_list` (for display) and `_plate_next_jump`
    (for index resolution) so they share a single source of truth.
    """
    raw = run(
        [
            "git", "for-each-ref",
            "--format=%(refname:short)|%(committerdate:unix)",
            "refs/heads/",
        ],
        cwd=repo,
    )
    plates: list[dict] = []
    for line in raw.splitlines():
        if "|" not in line:
            continue
        name, ts = line.split("|", 1)
        if not (name.endswith("-plate") or "-plate-derived" in name):
            continue
        plates.append({
            "ref": name,
            "tip_sha": getSHAForRefViaRevParse(repo, name),
            "committer_unix": int(ts),
            "trailers": getCommitTrailers(repo, name),
        })
    plates.sort(key=lambda p: p["committer_unix"], reverse=True)
    return plates


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

def saveChangesToPatch(
    repo: Path,
    files: list[str],
    name: str = "changes",
) -> Path:
    """Save WT changes to <files> as a binary patch under .plate/dropped/.

    Snapshots the named files (both tracked modifications and untracked
    additions) into a temp index, diffs that snapshot against HEAD with
    `git diff --binary`, and writes the result to
    .plate/dropped/<name>_<ts>.patch. The real index, HEAD, and WT
    are never touched.

    Args:
        repo: repository root.
        files: relative paths of files to include in the patch (pathspecs
               like "." are also accepted).
        name: prefix for the patch filename; defaults to "changes".

    Returns:
        Path to the newly written .patch file (ends with trailing newline,
        as `git apply` requires).
    """
    # Temp-index snapshot lets us stage untracked files without polluting
    # the real index.
    tmp_index_path = makeTempGitIndexPath()
    try:
        env = setGitIndexFileForEnv(env={}, gitIndexFile=tmp_index_path)
        readGitTreeAt(repo=repo, ref="HEAD", env=env)
        run(["git", "add"] + files, cwd=repo, env=env)
        snapshot_tree = writeGitTree(repo=repo, env=env)
    finally:
        Path(tmp_index_path).unlink(missing_ok=True)

    patch_text = run(
        ["git", "diff", "--binary", "HEAD", snapshot_tree], cwd=repo
    )

    patch_dir = repo / ".plate" / "dropped"
    patch_dir.mkdir(parents=True, exist_ok=True)
    patch_path = patch_dir / f"{name}_{currentTimestampMs()}.patch"
    # `git apply` requires a trailing newline; run() stripped it.
    patch_path.write_text(patch_text + "\n")
    return patch_path

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


# ── Stubs: plate operations ───────────────────────────────────────────
# Each stub raises NotImplementedError. Implementations should follow
# the canonical sequences locked in plate-walkthrough-log-2026-04-28.md.
def makeTempGitIndexPath() -> str:
        fd, tmp_index_path = tempfile.mkstemp(prefix="plate-index-")
        os.close(fd)
        return tmp_index_path

def findMyLastPlate(
    repo: Path,
    plate_branch: str,
    convo_id: str,
) -> tuple[Optional[str], Optional[str]]:
    """Find the most recent commit on `plate_branch` whose `convo-id` trailer
    matches `convo_id`.

    Returns (sha, committer_date_iso) — the SHA of the matching commit and
    its committer date as an ISO-8601 string with timezone (e.g.
    `2026-04-30 14:47:14 -0700`). Returns (None, None) when the branch
    doesn't exist or no commit on it carries a matching trailer.

    Used by `plate_push`'s author-detection branch to find this agent's
    cutoff time when scanning the transcript for files this agent has
    edited or deleted since their last plate.
    """
    if not branchExists(repo, plate_branch):
        return (None, None)

    raw = run(
        [
            "git", "log", plate_branch,
            "--format=%H|%ci|%(trailers:key=convo-id,valueonly,unfold=true)",
        ],
        cwd=repo,
    )
    for line in raw.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        sha, date_iso, trailer = parts
        if trailer.strip() == convo_id:
            return (sha, date_iso)
    return (None, None)


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


def _resolveTargetPlate(
    repo: Path,
    base_plate_name: str,
    convo_id: Optional[str],
) -> tuple[str, str]:
    """Determine which plate branch a push lands on, and what its parent SHA is.

    Always returns (base_plate_name, parent_sha) — multiple agents working on
    the same branch all share the same `<branch>-plate` ref. Per-agent
    attribution lives in the `convo-id` commit trailer; per-agent change
    isolation is handled later in `plate_push` via transcript extraction.

    Returns:
        - (base, HEAD)        when no plate exists yet
        - (base, base tip)    when the plate exists (linear history)

    Note: an earlier design routed different convo_ids onto sibling
    `<branch>-plate-derivedN` branches. That auto-derived behavior was
    replaced by the shared-plate-branch + transcript-extraction model.
    The chained-derived workflow (explicit delegation via
    `simulate_derived_agent`) is unrelated and remains in the codebase.
    """
    if not branchExists(repo, base_plate_name):
        return base_plate_name, getSHAForRefViaRevParse(repo, "HEAD")
    return base_plate_name, getSHAForRefViaRevParse(repo, base_plate_name)


def _buildFullWtTree(repo: Path) -> str:
    """Snapshot the working tree via a temp index and return its tree SHA.

    Same-author / first-plate path: the commit tree IS the full WT, so
    `git diff prev..mine` correctly attributes everything since prev to me
    (because I'm the one who made prev too).
    """
    tmp_index_path = makeTempGitIndexPath()
    try:
        env = setGitIndexFileForEnv(env={}, gitIndexFile=tmp_index_path)
        _ = readGitTreeAt(repo=repo, ref="HEAD", env=env)
        stageAllChanges(repo=repo, env=env)
        return writeGitTree(repo=repo, env=env)
    finally:
        Path(tmp_index_path).unlink(missing_ok=True)


def _buildExtractedTree(
    repo: Path,
    plate_branch: str,
    convo_id: str,
    parent_sha: str,
) -> str:
    """Build a commit tree starting from `parent_sha`'s tree, applying ONLY
    the file changes attributable to `convo_id` per the transcript.

    Used when a different agent committed the previous plate. Plain
    snapshot of WT would attribute the other agent's intervening edits to
    me; extraction filters to my edits/deletions only.

    Algorithm:
        1. Find my last plate on this branch → cutoff timestamp
           (None if I've never plated here).
        2. Extract files I edited since cutoff from my transcript (Edit /
           Write / MultiEdit / NotebookEdit tool_use entries).
        3. Extract files I deleted since cutoff (Bash rm / git rm),
           filtered to paths that were tracked in `parent_sha`'s tree
           (skips scratch deletions in `<repo>/tmp/` etc.).
        4. Start temp index = parent_sha's tree.
           For each edited file: stage its current WT content (`git add`).
           For each deleted file: remove from temp index (`git rm --cached`).
        5. Write tree → that's the commit tree.

    Result: prev plate's tree + my edits + my deletions, nothing more.
    The other agent's intervening WT changes stay in WT (unstaged), to
    be captured by their next plate.
    """
    _, cutoff = findMyLastPlate(repo, plate_branch, convo_id)

    transcript_path = Path(convo_id)
    edited_abs = extractFilesEditedSinceTimestamp(transcript_path, since_iso=cutoff)
    deleted_candidates = extractFilesDeletedSinceTimestamp(
        transcript_path, since_iso=cutoff, repo_root=repo
    )

    # Filter deletions to files actually tracked at the parent commit
    # (skips scratch removals in <repo>/tmp/ that aren't in the project tree).
    tracked_at_parent = set(
        run(
            ["git", "ls-tree", "-r", "--name-only", parent_sha],
            cwd=repo,
        ).splitlines()
    )
    deleted = [p for p in deleted_candidates if p in tracked_at_parent]

    # Convert absolute edited paths to repo-relative; skip those outside repo.
    repo_resolved = repo.resolve()
    edited_relative: list[str] = []
    for abs_path in edited_abs:
        try:
            rel = Path(abs_path).resolve().relative_to(repo_resolved)
        except (OSError, ValueError):
            continue
        edited_relative.append(str(rel))

    tmp_index_path = makeTempGitIndexPath()
    try:
        env = setGitIndexFileForEnv(env={}, gitIndexFile=tmp_index_path)
        readGitTreeAt(repo=repo, ref=parent_sha, env=env)
        # Stage edited files from current WT; skip files no longer present
        # (those are deletions, handled below).
        for rel_path in edited_relative:
            if (repo / rel_path).exists():
                run(["git", "add", "--", rel_path], cwd=repo, env=env)
        # Remove deleted files from the temp index.
        for rel_path in deleted:
            run(
                ["git", "rm", "--cached", "--ignore-unmatch", "--", rel_path],
                cwd=repo,
                env=env,
            )
        return writeGitTree(repo=repo, env=env)
    finally:
        Path(tmp_index_path).unlink(missing_ok=True)


def plate_push(
    repo: Path,
    convo_id: Optional[str] = None,
    convo_name: Optional[str] = None,
    convo_summary: Optional[str] = None,
) -> Optional[str]:
    """Run the canonical /plate push and stamp commit trailers.

    Sequence (plumbing — no merging, no checkouts; HEAD/index/WT untouched):
        TMP_INDEX=$(mktemp)
        GIT_INDEX_FILE=$TMP_INDEX git read-tree HEAD
        GIT_INDEX_FILE=$TMP_INDEX git add -A
        TREE=$(GIT_INDEX_FILE=$TMP_INDEX git write-tree)
        PARENT = <branch>-plate tip if exists, else HEAD
        if TREE == PARENT^{tree}: return None  ("no changes to stack")
        NEW=$(git commit-tree $TREE -p $PARENT -m "plate: WIP on <branch>" \
              -- with parent-branch and convo-* trailers)
        git update-ref refs/heads/<branch>-plate $NEW

    Trailers always written:
        parent-branch: <branch>     # auto-derived from getCurrentBranchName

    Trailers written only when the matching kwarg is non-None:
        convo-id:      <transcript_path>
        convo-name:    <customTitle>
        convo-summary: <single-line summary>   # multi-line input is collapsed
                                                  to spaces (git trailers are
                                                  single-line by spec)

    Returns:
        SHA of the new <branch>-plate tip commit on push, or None when the
        WT tree already matches the would-be parent's tree.
    """
    branch = getCurrentBranchName(repo)
    base_plate_name = f"{branch}-plate"

    # Always-shared plate branch; parent is HEAD if no plate exists, else
    # the current plate tip (regardless of who pushed it).
    target_plate, parent = _resolveTargetPlate(repo, base_plate_name, convo_id)

    # Choose between two tree-build strategies:
    #   - Mixed-author path: previous plate exists with a different convo-id
    #     than mine → build the tree from prev's tree + my edits/deletions
    #     extracted from my transcript (keeps the other agent's intervening
    #     WT changes out of my commit).
    #   - Same-author / first-time path: snapshot full WT (existing logic).
    use_extraction = (
        convo_id is not None
        and branchExists(repo, base_plate_name)
        and getCommitTrailers(repo, base_plate_name).get("convo-id") not in (None, convo_id)
    )

    if use_extraction:
        commit_tree = _buildExtractedTree(repo, base_plate_name, convo_id, parent)
    else:
        commit_tree = _buildFullWtTree(repo)

    parent_tree = getSHAForRefViaRevParse(repo=repo, ref=getTreeRevOf(parent))
    if commit_tree == parent_tree:
        return None
    wt_tree = commit_tree

    trailerLines = [f"parent-branch: {branch}"]
    if convo_id is not None:
        trailerLines.append(f"convo-id: {convo_id}")
    if convo_name is not None:
        trailerLines.append(f"convo-name: {convo_name}")
    if convo_summary is not None:
        # Git trailers are single-line; collapse newlines to single spaces.
        flatSummary = " ".join(convo_summary.split())
        trailerLines.append(f"convo-summary: {flatSummary}")

    commitMessage = f"plate: WIP on {branch}\n\n" + "\n".join(trailerLines)

    new_commit = run(
        [
            "git", "commit-tree", wt_tree,
            "-p", parent,
            COMMIT_MESSAGE_FLAG, commitMessage,
        ],
        cwd=repo,
    )
    run(["git", "update-ref", f"refs/heads/{target_plate}", new_commit], cwd=repo)

    return new_commit

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


def plate_done(repo: Path, branch: Optional[str] = None) -> None:
    """Run the canonical /plate --done (Step 9).

    Sequence:
        Step 0  implicit pre-push (only if WT tree differs from plate tip)
        Step 1  git reset --hard
                git clean -fd
        Step 2  git cherry-pick HEAD..<branch>-plate
        Step 3  git branch -D <branch>-plate

    Args:
        branch: working branch name; defaults to current.
    """
    if branch is None:
        branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    # Step 0: implicit pre-push (no-op when WT already matches plate tip).
    # plate_push always derives branch from current repo state; no kwarg needed.
    plate_push(repo)

    # No plate branch means there was nothing to push and nothing to merge.
    if not branchExists(repo, plateBranchName):
        return

    # Snapshot pre-call state so we can roll back on cherry-pick conflict.
    preHeadSha = getSHAForRefViaRevParse(repo, "HEAD")

    # Step 1: clean WT.
    resetHardToHead(repo)
    cleanWorkTree(repo)

    # Step 2: cherry-pick HEAD..<branch>-plate (oldest first).
    completed = subprocess.run(
        ["git", "cherry-pick", f"HEAD..{plateBranchName}"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        # Conflict (or any non-zero exit). Abort the cherry-pick and
        # restore HEAD to its pre-call SHA. Plate branch is preserved
        # so the user can retry after rebasing or resolving manually.
        subprocess.run(
            ["git", "cherry-pick", "--abort"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
        )
        run(["git", "reset", QUIET_OUTPUT, "--hard", preHeadSha], cwd=repo)
        cleanWorkTree(repo)
        print(
            f"warning: cherry-pick conflict during plate_done; "
            f"aborted and restored HEAD to {preHeadSha}. "
            f"Plate branch '{plateBranchName}' preserved.",
            file=sys.stderr,
        )
        return

    # Step 3: delete the plate branch.
    deleteBranchForce(repo, plateBranchName)

def test_plate_done(tmp_path: Path):
    """Per-function: 2-plate stack → done cherry-picks both, deletes plate, WT clean."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_done_replays_stack(repo)

def plate_drop(repo: Path, branch: Optional[str] = None) -> Optional[Path]:
    """Pop the top plate from <branch>-plate, save as patch.

    Sequence:
        - Build WT-tree via temp-index (capture tracked + untracked).
        - Write .plate/dropped/<branch>-plate_<ts>.patch as
          `git diff --binary <branch> <WT-tree>`.
        - Rewind <branch>-plate to <branch>-plate~1 (or `git branch -D`
          if last plate).
        - WT untouched.

    Returns:
        Path to the generated .patch file, or None when no plate branch
        exists (warning printed to stderr).
    """
    if branch is None:
        branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    if not branchExists(repo, plateBranchName):
        print(
            f"warning: no plate branch '{plateBranchName}' — nothing to drop",
            file=sys.stderr,
        )
        return None

    # Capture the entire WT (tracked + untracked) as a binary patch under
    # .plate/dropped/<plateBranchName>_<ts>.patch. The "." pathspec stages
    # everything in the temp index without touching the real index.
    patch_path = saveChangesToPatch(repo, ["."], name=plateBranchName)

    # Rewind the plate branch by one commit, or delete it if it was the last.
    plateCount = int(run(
        ["git", "rev-list", "--count", f"{branch}..{plateBranchName}"],
        cwd=repo,
    ))
    if plateCount == 1:
        deleteBranchForce(repo, plateBranchName)
    else:
        parent_sha = run(["git", "rev-parse", f"{plateBranchName}~1"], cwd=repo)
        run(["git", "update-ref", f"refs/heads/{plateBranchName}", parent_sha], cwd=repo)

    return patch_path

def test_plate_drop(tmp_path: Path):
    """Per-function: single plate → drop deletes branch + writes patch.
    Shared scenario covers the contract; runs against the 1-commit fixture."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_drop_deletes_last_plate(repo)

def plate_trash(
    repo: Path,
    branch: Optional[str] = None,
    clean_wt: bool = False,
) -> Optional[Path]:
    """Delete <branch>-plate entirely, save per-plate patches under .plate/trashed/.

    Args:
        branch: working branch name; defaults to current.
        clean_wt: if True, run git reset --hard + git clean -fd after
                  writing the patches (mode b — destructive of post-plate
                  WT edits not in the patch). If False, leave WT alone
                  (mode a — patch redundant with WT).

    Returns:
        Path to the directory containing per-plate .patch files
        (e.g. .plate/trashed/<branch>-plate_<ts>/), or None when no plate
        branch exists (warning printed to stderr).
    """
    if branch is None:
        branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    if not branchExists(repo, plateBranchName):
        print(
            f"warning: no plate branch '{plateBranchName}' — nothing to trash",
            file=sys.stderr,
        )
        return None

    # Walk plate commits oldest-first.
    plates = run(
        ["git", "rev-list", "--reverse", f"{branch}..{plateBranchName}"],
        cwd=repo,
    ).splitlines()

    # Per-plate patches go into a single dated session directory.
    trash_dir = repo / ".plate" / "trashed" / f"{plateBranchName}_{currentTimestampMs()}"
    trash_dir.mkdir(parents=True)

    for i, plate_sha in enumerate(plates):
        patch_text = run(
            ["git", "diff", "--binary", f"{plate_sha}~1", plate_sha],
            cwd=repo,
        )
        # `git apply` requires a trailing newline; run() stripped it.
        (trash_dir / f"plate_{i:03d}.patch").write_text(patch_text + "\n")

    deleteBranchForce(repo, plateBranchName)

    if clean_wt:
        resetHardToHead(repo)
        cleanWorkTree(repo)

    return trash_dir

def test_plate_trash(tmp_path: Path):
    """Per-function: 2-plate stack → trash saves patches + deletes branch + WT preserved."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_trash_default_preserves_wt(repo)

def test_plate_trash_hard(tmp_path: Path):
    """Per-function: dirty 2-plate stack → trash --hard saves patches + wipes WT."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_trash_clean_resets_wt(repo)


def plate_recycle(
    repo: Path,
    branch: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> Optional[str]:
    """Replay a trashed stack into a fresh <branch>-plate.

    Implementation uses Path 2 — per-plate patches replayed
    sequentially. Path 1 (single-patch single-recovered-plate) was
    rejected because it loses commit boundaries.

    Args:
        branch: working branch name; defaults to current.
        timestamp: pick a specific trash session by timestamp; defaults
                   to most recent.

    Returns:
        SHA of the recycled <branch>-plate tip, or None when no trashed
        session exists for the branch (warning printed to stderr).
    """
    if branch is None:
        branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    trash_root = repo / ".plate" / "trashed"
    if not trash_root.is_dir():
        sessions: list[Path] = []
    else:
        sessions = sorted(
            d for d in trash_root.iterdir() if d.name.startswith(f"{plateBranchName}_")
        )
    if not sessions:
        print(
            f"warning: no trashed plate '{plateBranchName}' — nothing to recycle",
            file=sys.stderr,
        )
        return None

    if timestamp is not None:
        chosen = next(d for d in sessions if d.name.endswith(f"_{timestamp}"))
    else:
        chosen = sessions[-1]

    # Apply each per-plate patch, then push it as its own plate commit.
    for patch in sorted(chosen.iterdir()):
        apply_patch(repo, patch)
        plate_push(repo)

    return getSHAForRefViaRevParse(repo, plateBranchName)

def test_plate_recycle(tmp_path: Path):
    """Per-function: 2 plates → trash → recycle restores branch with same tree."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_recycle_restores_stack(repo)

def plate_next(repo: Path, index: Optional[str] = None) -> str:
    """List or jump to a parked plate.

    Modes:
      - `index is None`: return a numbered list of every plate branch
        in the repo, sorted by tip-commit time descending.
      - `index` provided (1-based, raw argv string): push current WIP
        onto the current plate, switch HEAD to the target plate's parent
        branch, restore the target plate's tree onto WT as unstaged WIP,
        and return a resume command. Validation (numeric-only, range)
        lives in `_plate_next_jump` so the CLI can pass argv through
        without parsing.

    Selecting the current plate as the target is a no-op with a message.
    """
    plates = listPlateBranches(repo)
    if index is None:
        return _plate_next_list(repo, plates)
    return _plate_next_jump(repo, plates, index)


def _resolvePlateTitle(plate: dict) -> str:
    """Title precedence: live customTitle (if transcript readable here) →
    convo-name trailer → parent-branch trailer → ref name."""
    trailers = plate["trailers"]
    transcript_path = trailers.get("convo-id")
    if localTranscriptIsReadable(transcript_path):
        live = extractConvoNameFromTranscript(Path(transcript_path))
        if live:
            return live
    if "convo-name" in trailers:
        return trailers["convo-name"]
    return trailers.get("parent-branch", plate["ref"])


def _plate_next_list(repo: Path, plates: list[dict]) -> str:
    """Format the plate list per the canonical example in the plan."""
    if not plates:
        return PLATE_NEXT_EMPTY_LIST_MESSAGE
    branch = getCurrentBranchName(repo)
    currentPlateRef = f"{branch}-plate"
    now = int(time.time())
    lines = []
    for i, p in enumerate(plates, start=1):
        title = _resolvePlateTitle(p)
        age = formatPlateAge(now - p["committer_unix"])
        if p["ref"] == currentPlateRef:
            lines.append(f"{i}. `{title}` (current)  age: {age}")
        else:
            lines.append(f"{i}. `{title}` age: {age}")
    return "\n".join(lines)


PLATE_NEXT_LOST_MESSAGE = (
    "previous conversation for the desired plate has been lost. "
    "Tell the next agent to attempt to extract context from current git "
    "state and plate branch commits and that summary text is available "
    "in plate branch commits"
)

PLATE_NEXT_INVALID_INDEX_MESSAGE = (
    "please choose a valid index when switching to the next plate"
)

PLATE_NEXT_NON_NUMERIC_MESSAGE = (
    "--next <#>: <#> must be a number and not letters or symbols."
)

PLATE_NEXT_EMPTY_LIST_MESSAGE = (
    "No changes plated.  Make some changes to your repo and then /plate "
    "to capture them"
)


def _plate_next_jump(repo: Path, plates: list[dict], index: str) -> str:
    """Push current WIP, switch to target plate's parent branch, restore tree as WIP, emit resume command.

    `index` is the raw argv string. Validation order:
      1. Numeric-only check (str.isdigit) — rejects letters, symbols,
         whitespace, decimals, signs, and empty strings.
      2. Range check (1..len(plates)).
    """
    if not isinstance(index, str) or not index.isdigit():
        return PLATE_NEXT_NON_NUMERIC_MESSAGE
    idx_int = int(index)
    if idx_int < 1 or idx_int > len(plates):
        return PLATE_NEXT_INVALID_INDEX_MESSAGE
    target = plates[idx_int - 1]
    branch = getCurrentBranchName(repo)
    currentPlateRef = f"{branch}-plate"
    if target["ref"] == currentPlateRef:
        title = _resolvePlateTitle(target)
        return f"already on plate '{title}'; worktree unchanged"

    # 1. Capture current WIP into the current-branch plate (no-op when clean).
    plate_push(repo)
    # 2. Clear WIP so the upcoming checkout doesn't conflict.
    resetHardToHead(repo)
    cleanWorkTree(repo)
    # 3. Check out the target's parent branch.
    parent_branch = target["trailers"].get("parent-branch")
    if not parent_branch or not branchExists(repo, parent_branch):
        return PLATE_NEXT_LOST_MESSAGE
    checkOutBranch(repo, parent_branch)
    # 4. Restore the plate's tree onto WT; leave HEAD on parent_branch with
    #    plate's accumulated work showing as unstaged changes.
    run(["git", "checkout", target["tip_sha"], "--", "."], cwd=repo)
    run(["git", "reset", QUIET_OUTPUT, "HEAD"], cwd=repo)

    # 5. Build the resume command.
    transcript_path = target["trailers"].get("convo-id")
    if localTranscriptIsReadable(transcript_path):
        cwd = extractConvoCwdFromTranscript(Path(transcript_path))
        title = (
            extractConvoNameFromTranscript(Path(transcript_path))
            or target["trailers"].get("convo-name")
            or Path(transcript_path).stem
        )
        if cwd:
            return f"resume with: cd {cwd} && claude --resume {title}"
        return f"resume with: claude --resume {title}"

    # 6. Lost path — transcript not readable here. The next agent will read
    #    the convo-summary trailer (if present) directly from git.
    return PLATE_NEXT_LOST_MESSAGE

def simulate_derived_agent(
    repo: Path,
    parent_plate: str,
    convo_id: str,
) -> str:
    """STUB. Simulate a new agent in the same repo creating its
    derived plate branch.

    Behavior:
        - Determine N (chain depth) from existing <parent>-derived*
          branches.
        - Create <parent>-derived<N+1> off the most recent derived
          branch (or off <parent>-plate if N=0).
        - First commit on the derived branch carries trailers:
            parent-convo: <parent's convo_id>
            parent-plate: <SHA of the parent plate commit at branch time>
            convo-id: <this agent's convo_id>

    Returns:
        Name of the created derived branch
        (e.g. "fix-plate-derived1").
    """
    derivedPattern = f"{parent_plate}-derived"
    existing = [b for b in getGitBranchList(repo) if b.startswith(derivedPattern)]
    N = len(existing)

    if N == 0:
        baseBranch = parent_plate
        parentConvo = "ROOT"
    else:
        existing.sort(key=lambda b: int(b[len(derivedPattern):]))
        baseBranch = existing[-1]
        parentConvo = getCommitTrailers(repo, baseBranch)["convo-id"]

    newBranchName = f"{parent_plate}-derived{N+1}"
    parentSHA = getSHAForRefViaRevParse(repo, baseBranch)
    parentTree = getTreeSHA(repo, baseBranch)

    msg = (
        f"derived agent {N+1}\n\n"
        f"parent-convo: {parentConvo}\n"
        f"parent-plate: {parentSHA}\n"
        f"convo-id: {convo_id}"
    )
    new_commit = run(
        ["git", "commit-tree", parentTree, "-p", parentSHA, COMMIT_MESSAGE_FLAG, msg],
        cwd=repo,
    )
    run(["git", "update-ref", f"refs/heads/{newBranchName}", new_commit], cwd=repo)
    return newBranchName

def test_simulate_derived_agent_first(tmp_path: Path):
    """Per-function: first derived agent records trailers."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_first_derived_agent_records_trailers(repo)


def test_simulate_derived_agent_second(tmp_path: Path):
    """Per-function: second derived agent extends chain (parent-convo points at previous)."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_second_derived_agent_extends_chain(repo)


def apply_patch(repo: Path, patch: Path) -> None:
    """Apply a saved .patch file via `git apply --3way <patch>`."""
    run(["git", "apply", "--3way", str(patch)], cwd=repo)

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


# ── Cross-fixture scenario helpers ────────────────────────────────────
# Each `_check_*` function asserts a single workflow contract. Both the
# per-function tests above (against makeTestRepoWithSingleCommit) and the
# sequence tests in test_helpers.py (against setup_repo) call these to
# verify the same workflow under different topologies. Scenarios MUST
# avoid fixture-specific assumptions (no hardcoded branch names, no
# exact-equality checks on tracked-file lists).


def _check_plate_push_creates_branch_capturing_wip(repo: Path) -> None:
    """Scenario: tracked edit + untracked file → plate_push creates the plate
    branch parented to HEAD, captures both edits, and leaves WT/HEAD/branch
    untouched."""
    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    head_before = getSHAForRefViaRevParse(repo, "HEAD")
    assert not branchExists(repo, plateBranchName)

    (repo / TEST_FILENAME).write_text("modified\n")
    untracked = createUntrackedFile(repo, random.Random())["file"]

    sha = plate_push(repo)

    # Plate branch created and parented to HEAD.
    assert sha is not None
    assert branchExists(repo, plateBranchName)
    assert getSHAForRefViaRevParse(repo, plateBranchName) == sha
    assert run(["git", "rev-parse", f"{plateBranchName}~1"], cwd=repo) == head_before
    # Both edits captured in the plate tree.
    plate_files = run(
        ["git", "ls-tree", "-r", "--name-only", plateBranchName], cwd=repo
    ).splitlines()
    assert TEST_FILENAME in plate_files
    assert untracked in plate_files
    # WT, HEAD, and current branch unchanged.
    assert getCurrentBranchName(repo) == branch
    assert getSHAForRefViaRevParse(repo, "HEAD") == head_before
    assert (repo / TEST_FILENAME).read_text() == "modified\n"
    assert untracked in getGitUntrackedFilesList(repo)


def _check_plate_done_replays_stack(repo: Path) -> None:
    """Scenario: 2-plate stack → plate_done cherry-picks both onto branch
    oldest-first, deletes plate ref, leaves WT clean and tree == former plate tip."""
    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    branch_count_before = countCommitsReachableFromRef(repo, branch)

    rng = random.Random()
    u1 = createUntrackedFile(repo, rng)["file"]
    plate_push(repo)
    u2 = createUntrackedFile(repo, rng)["file"]
    plate_push(repo)
    plate_tip_tree = getTreeSHA(repo, plateBranchName)

    plate_done(repo)

    assert not branchExists(repo, plateBranchName)
    assert countCommitsReachableFromRef(repo, branch) == branch_count_before + 2
    assert checkForCleanWorkTree(repo)
    assert getTreeSHA(repo, branch) == plate_tip_tree
    tracked = getGitTrackedFilesList(repo)
    assert u1 in tracked
    assert u2 in tracked


def _check_plate_drop_deletes_last_plate(repo: Path) -> None:
    """Scenario: single plate → plate_drop saves a patch under .plate/dropped/,
    deletes the plate ref, leaves WT untouched."""
    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    untracked = createUntrackedFile(repo, random.Random())["file"]
    plate_push(repo)
    assert branchExists(repo, plateBranchName)

    patch_path = plate_drop(repo)

    assert patch_path.exists()
    assert patch_path.parent.name == "dropped"
    assert untracked in patch_path.read_text()
    assert not branchExists(repo, plateBranchName)
    assert untracked in getGitUntrackedFilesList(repo)


def _check_plate_drop_then_apply_patch_round_trip(repo: Path) -> None:
    """Scenario: single plate → plate_drop + reset WT + apply_patch restores
    the dropped work to the WT byte-for-byte."""
    untracked = createUntrackedFile(repo, random.Random())["file"]
    untracked_content = (repo / untracked).read_text()
    plate_push(repo)

    patch_path = plate_drop(repo)

    # Reset WT to clean state (drop's contract leaves the file in WT;
    # delete it explicitly so apply_patch's restoration is visible).
    (repo / untracked).unlink()
    assert not (repo / untracked).exists()

    apply_patch(repo, patch_path)

    assert (repo / untracked).exists()
    assert (repo / untracked).read_text() == untracked_content


def _check_plate_trash_default_preserves_wt(repo: Path) -> None:
    """Scenario: 2-plate stack → plate_trash (default clean_wt=False) saves
    per-plate patches, deletes plate ref, leaves WT untouched."""
    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    rng = random.Random()
    u1 = createUntrackedFile(repo, rng)["file"]
    plate_push(repo)
    u2 = createUntrackedFile(repo, rng)["file"]
    plate_push(repo)

    trash_dir = plate_trash(repo)

    assert trash_dir.is_dir()
    assert trash_dir.parent.name == "trashed"
    patches = sorted(trash_dir.iterdir())
    assert len(patches) == 2
    assert all(p.suffix == ".patch" for p in patches)
    assert not branchExists(repo, plateBranchName)
    untracked = getGitUntrackedFilesList(repo)
    assert u1 in untracked
    assert u2 in untracked


def _check_plate_trash_clean_resets_wt(repo: Path) -> None:
    """Scenario: dirty 2-plate stack → plate_trash(clean_wt=True) saves
    patches, deletes plate ref, AND wipes WT (tracked restored, untracked
    removed)."""
    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    branch_tip_before = getSHAForRefViaRevParse(repo, branch)
    tracked_before = (repo / TEST_FILENAME).read_text()

    rng = random.Random()
    (repo / TEST_FILENAME).write_text("modified\n")
    u1 = createUntrackedFile(repo, rng)["file"]
    plate_push(repo)
    u2 = createUntrackedFile(repo, rng)["file"]
    plate_push(repo)

    trash_dir = plate_trash(repo, clean_wt=True)

    assert trash_dir.is_dir()
    patches = sorted(trash_dir.iterdir())
    assert len(patches) == 2
    assert not branchExists(repo, plateBranchName)
    # WT wiped.
    assert (repo / TEST_FILENAME).read_text() == tracked_before
    assert not (repo / u1).exists()
    assert not (repo / u2).exists()
    # Branch HEAD untouched.
    assert getSHAForRefViaRevParse(repo, branch) == branch_tip_before


def _check_plate_recycle_restores_stack(repo: Path) -> None:
    """Scenario: 2-plate stack → trash → recycle restores plate branch with
    same commit count and same tip tree SHA; branch HEAD unchanged."""
    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    branch_tip_before = getSHAForRefViaRevParse(repo, branch)

    rng = random.Random()
    u1 = createUntrackedFile(repo, rng)["file"]
    plate_push(repo)
    u2 = createUntrackedFile(repo, rng)["file"]
    plate_push(repo)
    plate_count_before = countCommitsReachableFromRef(repo, plateBranchName)
    plate_tip_tree_before = getTreeSHA(repo, plateBranchName)

    plate_trash(repo)
    # Clean WT before recycle so apply_patch doesn't conflict on existing files.
    (repo / u1).unlink()
    (repo / u2).unlink()

    recycled_sha = plate_recycle(repo)

    assert branchExists(repo, plateBranchName)
    assert countCommitsReachableFromRef(repo, plateBranchName) == plate_count_before
    assert getTreeSHA(repo, plateBranchName) == plate_tip_tree_before
    assert getSHAForRefViaRevParse(repo, plateBranchName) == recycled_sha
    assert getSHAForRefViaRevParse(repo, branch) == branch_tip_before


def _check_first_derived_agent_records_trailers(repo: Path) -> None:
    """Scenario: parent plate exists → simulate_derived_agent creates
    `<parent_plate>-derived1` parented to plate tip with trailers
    parent-plate=<plate tip SHA> and convo-id=<convo_id>."""
    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    (repo / TEST_FILENAME).write_text("modified\n")
    plate_push(repo)
    parent_plate_sha = getSHAForRefViaRevParse(repo, plateBranchName)

    derived = simulate_derived_agent(repo, plateBranchName, "CONVO-A")

    assert derived == f"{plateBranchName}-derived1"
    assert branchExists(repo, derived)
    assert run(["git", "rev-parse", f"{derived}~1"], cwd=repo) == parent_plate_sha
    trailers = getCommitTrailers(repo, derived)
    assert trailers["parent-plate"] == parent_plate_sha
    assert trailers["convo-id"] == "CONVO-A"


def _check_second_derived_agent_extends_chain(repo: Path) -> None:
    """Scenario: parent plate + derived1 exist → simulate_derived_agent
    creates `<parent_plate>-derived2` parented to derived1's tip, with
    parent-convo trailer = derived1's convo-id."""
    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    (repo / TEST_FILENAME).write_text("modified\n")
    plate_push(repo)

    derived1 = simulate_derived_agent(repo, plateBranchName, "CONVO-A")
    derived1_tip = getSHAForRefViaRevParse(repo, derived1)

    derived2 = simulate_derived_agent(repo, plateBranchName, "CONVO-B")

    assert derived2 == f"{plateBranchName}-derived2"
    assert branchExists(repo, derived2)
    assert run(["git", "rev-parse", f"{derived2}~1"], cwd=repo) == derived1_tip
    trailers = getCommitTrailers(repo, derived2)
    assert trailers["parent-convo"] == "CONVO-A"
    assert trailers["convo-id"] == "CONVO-B"
    # derived1 untouched.
    assert getSHAForRefViaRevParse(repo, derived1) == derived1_tip




# ── Error-path scenarios ─────────────────────────────────────────────
# Scenarios for the 5 untested error paths from PLATE STATE.md §C:
#   - plate_drop / plate_trash / plate_recycle invoked without a plate
#     branch must warn on stderr and return None (no exception).
#   - plate_done with a cherry-pick conflict must abort, restore HEAD/WT,
#     preserve the plate branch, and warn on stderr.
#   - Cross-repo patch portability: a `--drop` patch produced in repoA
#     applies cleanly in a separate repoB with the same base file.
#   - Plate SHA remains recoverable from the object database after
#     plate_done deletes the plate branch (no immediate gc).


def _check_plate_drop_no_branch_warns_and_exits(repo: Path, capsys) -> None:
    """Scenario: no plate branch exists → plate_drop returns None, prints
    warning to stderr, creates no .plate/dropped/ directory, leaves WT clean."""
    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    assert not branchExists(repo, plateBranchName)

    head_before = getSHAForRefViaRevParse(repo, "HEAD")
    wt_clean_before = checkForCleanWorkTree(repo)

    result = plate_drop(repo)

    captured = capsys.readouterr()
    assert result is None
    assert "no plate branch" in captured.err
    assert plateBranchName in captured.err
    # No patch directory created.
    assert not (repo / ".plate" / "dropped").exists()
    # Repo state unchanged.
    assert getSHAForRefViaRevParse(repo, "HEAD") == head_before
    assert checkForCleanWorkTree(repo) == wt_clean_before


def test_plate_drop_no_branch(tmp_path: Path, capsys):
    """Per-function: plate_drop with no plate branch warns + returns None."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_drop_no_branch_warns_and_exits(repo, capsys)


def _check_plate_trash_no_branch_warns_and_exits(repo: Path, capsys) -> None:
    """Scenario: no plate branch exists → plate_trash returns None, prints
    warning to stderr, creates no .plate/trashed/ directory, leaves WT clean."""
    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    assert not branchExists(repo, plateBranchName)

    head_before = getSHAForRefViaRevParse(repo, "HEAD")

    result = plate_trash(repo)

    captured = capsys.readouterr()
    assert result is None
    assert "no plate branch" in captured.err
    assert plateBranchName in captured.err
    assert not (repo / ".plate" / "trashed").exists()
    assert getSHAForRefViaRevParse(repo, "HEAD") == head_before


def test_plate_trash_no_branch(tmp_path: Path, capsys):
    """Per-function: plate_trash with no plate branch warns + returns None."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_trash_no_branch_warns_and_exits(repo, capsys)


def _check_plate_recycle_no_branch_warns_and_exits(repo: Path, capsys) -> None:
    """Scenario: no trashed plate session exists → plate_recycle returns None,
    prints warning to stderr, creates no plate branch, leaves repo unchanged."""
    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    assert not branchExists(repo, plateBranchName)

    head_before = getSHAForRefViaRevParse(repo, "HEAD")

    result = plate_recycle(repo)

    captured = capsys.readouterr()
    assert result is None
    assert "nothing to recycle" in captured.err
    assert plateBranchName in captured.err
    assert not branchExists(repo, plateBranchName)
    assert getSHAForRefViaRevParse(repo, "HEAD") == head_before


def test_plate_recycle_no_branch(tmp_path: Path, capsys):
    """Per-function: plate_recycle with no trashed session warns + returns None."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_recycle_no_branch_warns_and_exits(repo, capsys)


def _check_plate_done_conflict_aborts_and_restores(repo: Path, capsys) -> None:
    """Scenario: plate_done's cherry-pick conflicts because the working
    branch advanced on the same file the plate edits → plate_done aborts
    the cherry-pick, restores HEAD/WT, preserves the plate branch, warns.

    Setup:
      1. Replace TEST_FILENAME contents with "plate version\\n", plate_push.
      2. Reset WT, replace TEST_FILENAME contents with "branch version\\n"
         on HEAD, commit it. Both edits replace the same line that the
         shared base had → guaranteed cherry-pick conflict.

    Assertions after plate_done:
      - HEAD SHA == post-setup HEAD (the "branch version" commit).
      - <branch>-plate ref still exists, and the original plate tip SHA
        is still reachable from it (plate_done's implicit pre-push may
        have advanced the ref, but the recoverable history is preserved).
      - WT contents == HEAD's tree (the "branch version" file content).
      - No .git/CHERRY_PICK_HEAD marker (clean abort).
      - stderr contains a conflict warning naming the plate branch.
    """
    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    # 1. Plate edit replaces file contents entirely.
    (repo / TEST_FILENAME).write_text("plate version\n")
    plate_push(repo)
    plate_tip_before = getSHAForRefViaRevParse(repo, plateBranchName)

    # 2. Reset, then a conflicting commit replaces same line with different text.
    resetHardToHead(repo)
    (repo / TEST_FILENAME).write_text("branch version\n")
    addFileToGit(repo, TEST_FILENAME)
    createCommit(repo, "branch advance — will conflict with plate")

    head_before_done = getSHAForRefViaRevParse(repo, "HEAD")
    wt_before_done = (repo / TEST_FILENAME).read_text()

    # 3. plate_done — cherry-pick should conflict, abort, restore.
    plate_done(repo)

    captured = capsys.readouterr()
    # Restored state.
    assert getSHAForRefViaRevParse(repo, "HEAD") == head_before_done
    assert (repo / TEST_FILENAME).read_text() == wt_before_done
    assert checkForCleanWorkTree(repo)
    # Plate branch preserved; original plate tip still reachable from it.
    assert branchExists(repo, plateBranchName)
    plate_history = run(["git", "rev-list", plateBranchName], cwd=repo).splitlines()
    assert plate_tip_before in plate_history
    # Cherry-pick state cleaned.
    assert not (repo / ".git" / "CHERRY_PICK_HEAD").exists()
    # Warning emitted.
    assert "cherry-pick conflict" in captured.err
    assert plateBranchName in captured.err


def test_plate_done_conflict(tmp_path: Path, capsys):
    """Per-function: plate_done's cherry-pick conflict aborts cleanly."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_done_conflict_aborts_and_restores(repo, capsys)


def _check_drop_patch_applies_in_fresh_repo(repoA: Path, repoB: Path) -> None:
    """Scenario: a `--drop` patch from repoA applies cleanly in a separate
    repoB whose HEAD has the same base file content. Verifies the
    "send the patch to a teammate" portability claim.

    Both repos must share the same TEST_FILENAME content at HEAD.
    """
    # Sanity: same base content.
    assert (repoA / TEST_FILENAME).read_text() == (repoB / TEST_FILENAME).read_text()

    # In repoA: edit, push, drop → patch path.
    edited_content = (repoA / TEST_FILENAME).read_text() + "portable-edit\n"
    (repoA / TEST_FILENAME).write_text(edited_content)
    untracked_name = createUntrackedFile(repoA, random.Random())["file"]
    untracked_content = (repoA / untracked_name).read_text()

    plate_push(repoA)
    patch_path = plate_drop(repoA)
    assert patch_path is not None
    assert patch_path.exists()

    # Copy patch into repoB (mirrors emailing/Slacking the file).
    repoB_patch = repoB / "incoming.patch"
    shutil.copyfile(patch_path, repoB_patch)

    # Apply in repoB.
    apply_patch(repoB, repoB_patch)

    # Tracked edit applied byte-for-byte.
    assert (repoB / TEST_FILENAME).read_text() == edited_content
    # Untracked file from repoA's patch lands in repoB with same content.
    assert (repoB / untracked_name).exists()
    assert (repoB / untracked_name).read_text() == untracked_content
    # No conflict markers in the patched file.
    assert "<<<<<<<" not in (repoB / TEST_FILENAME).read_text()


def test_drop_patch_cross_repo_portability(tmp_path: Path):
    """Per-function: drop patch from repoA applies in a separate repoB."""
    repoA = makeTestRepoWithSingleCommit(tmp_path / "a")
    repoB = makeTestRepoWithSingleCommit(tmp_path / "b")
    _check_drop_patch_applies_in_fresh_repo(repoA, repoB)


def _check_plate_done_leaves_sha_recoverable(repo: Path) -> None:
    """Scenario: after plate_done deletes the plate branch, the plate's
    tip commit SHA is still resolvable from the object database. Documents
    the recoverability invariant — would catch a future regression that
    introduces an immediate `git gc --prune=now` or equivalent.
    """
    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    rng = random.Random()
    createUntrackedFile(repo, rng)
    plate_push(repo)
    plate_sha = getSHAForRefViaRevParse(repo, plateBranchName)

    plate_done(repo)

    # Plate branch ref is gone.
    assert not branchExists(repo, plateBranchName)
    # But the commit object is still in the repo (recoverable until gc).
    assert getSHAForRefViaRevParse(repo, f"{plate_sha}^{{commit}}") == plate_sha


def test_plate_done_leaves_sha_recoverable(tmp_path: Path):
    """Per-function: plate_done's deleted plate SHA is still in the object DB."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_done_leaves_sha_recoverable(repo)


# ── plate_next scenarios ─────────────────────────────────────────────


def _check_plate_next_list_shows_plates_sorted_with_current_marker(repo: Path) -> None:
    """Scenario: two plates across two branches → listing shows both,
    newest first, with `(current)` on the plate corresponding to HEAD's
    branch and trailer-fallback titles when transcripts aren't readable.

    Topology produced by this scenario:
        main:    A
                  \\
                   main-plate
                       │
                       └─ Pa1   (convo-name "alpha work")

         + 1 second sleep so committer_unix differs +

        main:    A
                  \\
                   feature-y
                       │
                       └─ feature-y-plate
                               │
                               └─ Pb1   (convo-name "beta work")

        HEAD: feature-y, clean WT.
    """
    # Start from main, regardless of which branch the fixture left HEAD on.
    if getCurrentBranchName(repo) != "main":
        resetHardToHead(repo)
        cleanWorkTree(repo)
        checkOutBranch(repo, "main")

    # First plate on main with fake transcript path (so list-mode falls back
    # to the convo-name trailer).
    (repo / TEST_FILENAME).write_text("edit on main\n")
    plate_push(
        repo,
        convo_id="/nonexistent/transcript-A.jsonl",
        convo_name="alpha work",
        convo_summary="summary A",
    )
    resetHardToHead(repo)

    # Force a measurable timestamp gap so listPlateBranches sort is deterministic.
    time.sleep(1)

    # Second plate on a new feature-y branch off main.
    createAndCheckoutBranch(repo, "feature-y")
    (repo / TEST_FILENAME).write_text("edit on feature-y\n")
    plate_push(
        repo,
        convo_id="/nonexistent/transcript-B.jsonl",
        convo_name="beta work",
        convo_summary="summary B",
    )
    resetHardToHead(repo)
    assert getCurrentBranchName(repo) == "feature-y"

    # Act: list mode (no index).
    result = plate_next(repo)
    lines = result.split("\n")

    # Two plates listed.
    assert len(lines) == 2, f"expected 2 lines, got {len(lines)}: {result!r}"

    # Newest first: feature-y-plate (current), then main-plate.
    assert lines[0].startswith("1. `beta work` (current) "), lines[0]
    assert "age:" in lines[0]
    assert lines[1].startswith("2. `alpha work` "), lines[1]
    assert "(current)" not in lines[1]
    assert "age:" in lines[1]


def test_plate_next_list_shows_plates_sorted_with_current_marker(tmp_path: Path):
    """Per-function: list mode against the single-commit fixture."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_next_list_shows_plates_sorted_with_current_marker(repo)


def _writeTranscriptFile(
    path: Path,
    cwd: str,
    custom_title: Optional[str] = None,
) -> Path:
    """Write a minimal Claude Code JSONL transcript with cwd + optional title.

    Used by plate_next jump-mode tests to fabricate a "real" local transcript
    that extractConvoCwdFromTranscript and extractConvoNameFromTranscript can
    read successfully.
    """
    lines = [json.dumps({"type": "system", "cwd": cwd, "subtype": "init"})]
    if custom_title is not None:
        lines.append(
            json.dumps({"type": "custom-title", "customTitle": custom_title, "sessionId": path.stem})
        )
    path.write_text("\n".join(lines) + "\n")
    return path


def _buildTwoBranchPlateTopology(
    repo: Path,
    transcript_for_fixy: Path,
    include_summary: bool = True,
) -> dict:
    """Construct the canonical two-branch plate topology used by plate_next jump tests.

        main:    A ── B ── C
                       │    │
                       │    └── feature-x
                       │           │
                       │           └── C1 ── C2
                       │                       │
                       │                       └── feature-x-plate
                       │                               ├── Pa1
                       │                               └── Pa2          (2 plate commits)
                       │
                       └── fix-y
                               │
                               └── B1 ── B2 ── B3
                                           │
                                           (plate parented to B1, NOT B3)
                                           │
                                           fix-y-plate
                                               ├── Pb1
                                               ├── Pb2
                                               └── Pb3                  (3 plate commits)

    fix-y-plate's convo-id points at `transcript_for_fixy` so the local-resume
    path can extract a real cwd + customTitle. feature-x-plate's convo-id is
    a fake path that does not exist on disk.

    Returns a dict of recorded SHAs and ref names for the test to assert against.
    """
    # The fixture leaves us on main with one commit (A). Add B and C.
    sha_A = getSHAForRefViaRevParse(repo, "main")
    (repo / TEST_FILENAME).write_text("A\nB-line\n")
    addFileToGit(repo, TEST_FILENAME)
    createCommit(repo, "B")
    sha_B = getSHAForRefViaRevParse(repo, "main")
    (repo / TEST_FILENAME).write_text("A\nB-line\nC-line\n")
    addFileToGit(repo, TEST_FILENAME)
    createCommit(repo, "C")
    sha_C = getSHAForRefViaRevParse(repo, "main")

    # fix-y branches off main at B with three working commits B1, B2, B3.
    run(["git", "checkout", QUIET_OUTPUT, CREATE_BRANCH_AND_CHECKOUT_FLAG, "fix-y", sha_B], cwd=repo)
    (repo / "fix.txt").write_text("B1 fix\n")
    addFileToGit(repo, "fix.txt")
    createCommit(repo, "B1")
    sha_B1 = getSHAForRefViaRevParse(repo, "fix-y")
    (repo / "fix.txt").write_text("B1 fix\nB2 polish\n")
    addFileToGit(repo, "fix.txt")
    createCommit(repo, "B2")
    (repo / "fix.txt").write_text("B1 fix\nB2 polish\nB3 cleanup\n")
    addFileToGit(repo, "fix.txt")
    createCommit(repo, "B3")
    sha_B3 = getSHAForRefViaRevParse(repo, "fix-y")

    # Rewind fix-y to B1 so plate_push parents off B1, then push 3 plates.
    run(["git", "reset", QUIET_OUTPUT, "--hard", sha_B1], cwd=repo)
    (repo / "investigation.txt").write_text("Pb1 notes\n")
    plate_push(
        repo,
        convo_id=str(transcript_for_fixy),
        convo_name="bug-fix work",
        convo_summary=("Investigating bisect-flagged regression in B1" if include_summary else None),
    )
    (repo / "investigation.txt").write_text("Pb1 notes\nPb2 fix attempt\n")
    plate_push(
        repo,
        convo_id=str(transcript_for_fixy),
        convo_name="bug-fix work",
        convo_summary=("Investigating bisect-flagged regression in B1" if include_summary else None),
    )
    (repo / "investigation.txt").write_text("Pb1 notes\nPb2 fix attempt\nPb3 final\n")
    plate_push(
        repo,
        convo_id=str(transcript_for_fixy),
        convo_name="bug-fix work",
        convo_summary=("Investigating bisect-flagged regression in B1" if include_summary else None),
    )
    sha_Pb3 = getSHAForRefViaRevParse(repo, "fix-y-plate")

    # Restore fix-y's working tip back to B3 (its real, post-investigation state).
    # `git reset --hard` preserves untracked files, so investigation.txt would
    # otherwise leak across branch switches. Clean it out so subsequent
    # plate_push calls don't accidentally capture it.
    run(["git", "reset", QUIET_OUTPUT, "--hard", sha_B3], cwd=repo)
    cleanWorkTree(repo)

    # feature-x branches off main at C with two working commits.
    checkOutBranch(repo, "main")
    run(["git", "checkout", QUIET_OUTPUT, CREATE_BRANCH_AND_CHECKOUT_FLAG, "feature-x", sha_C], cwd=repo)
    (repo / "feature.txt").write_text("C1 work\n")
    addFileToGit(repo, "feature.txt")
    createCommit(repo, "C1")
    (repo / "feature.txt").write_text("C1 work\nC2 polish\n")
    addFileToGit(repo, "feature.txt")
    createCommit(repo, "C2")
    sha_C2 = getSHAForRefViaRevParse(repo, "feature-x")

    # Push 2 plates on feature-x with a fake transcript path.
    (repo / "feature.txt").write_text("C1 work\nC2 polish\nPa1 wip\n")
    plate_push(
        repo,
        convo_id="/nonexistent/feature-transcript.jsonl",
        convo_name="feature work",
        convo_summary="building the new feature on top of C2",
    )
    (repo / "feature.txt").write_text("C1 work\nC2 polish\nPa1 wip\nPa2 more\n")
    plate_push(
        repo,
        convo_id="/nonexistent/feature-transcript.jsonl",
        convo_name="feature work",
        convo_summary="building the new feature on top of C2",
    )
    sha_Pa2 = getSHAForRefViaRevParse(repo, "feature-x-plate")

    # Reset WT clean on feature-x.
    resetHardToHead(repo)

    return {
        "sha_A": sha_A,
        "sha_B": sha_B,
        "sha_B1": sha_B1,
        "sha_B3": sha_B3,
        "sha_Pb3": sha_Pb3,
        "sha_C": sha_C,
        "sha_C2": sha_C2,
        "sha_Pa2": sha_Pa2,
    }


def _check_plate_next_jump_restores_plate_tree_without_post_plate_branch_changes(repo: Path, tmp_path: Path) -> None:
    """Scenario: HEAD on feature-x with dirty WIP. Two unrelated plate branches
    (feature-x-plate parented to C2, fix-y-plate parented to B1). User jumps
    to fix-y-plate via index. Verify:
      1. WIP captured into feature-x-plate as a new commit (Pa3).
      2. HEAD now on fix-y at B3 (parent-branch trailer of target).
      3. WT shows fix-y-plate's accumulated tree (Pb3's tree).
      4. Resume command uses cwd + customTitle from the readable transcript.
    """
    transcript = tmp_path / "fixy-transcript.jsonl"
    _writeTranscriptFile(transcript, cwd="/Users/me/jot", custom_title="fix-y bug investigation")

    shas = _buildTwoBranchPlateTopology(repo, transcript_for_fixy=transcript)
    assert getCurrentBranchName(repo) == "feature-x"

    # Add dirty WIP on feature-x so jump-mode's implicit pre-push has work to capture.
    (repo / "feature.txt").write_text(
        "C1 work\nC2 polish\nPa1 wip\nPa2 more\nPa3 in-flight WIP\n"
    )
    feature_plate_count_before = countCommitsReachableFromRef(repo, "feature-x-plate")

    # Find the index of fix-y-plate via listPlateBranches (same source the
    # listing uses, so indices match deterministically).
    plates_in_order = listPlateBranches(repo)
    fixy_index = next(
        i + 1 for i, p in enumerate(plates_in_order) if p["ref"] == "fix-y-plate"
    )

    # Jump.
    result = plate_next(repo, index=str(fixy_index))

    # 1. WIP captured: feature-x-plate gained a commit.
    feature_plate_count_after = countCommitsReachableFromRef(repo, "feature-x-plate")
    assert feature_plate_count_after == feature_plate_count_before + 1

    # 2. HEAD now on fix-y at B3.
    assert getCurrentBranchName(repo) == "fix-y"
    assert getSHAForRefViaRevParse(repo, "HEAD") == shas["sha_B3"]

    # 3. WT contains fix-y-plate's tree (Pb3's content).
    assert (repo / "investigation.txt").read_text() == "Pb1 notes\nPb2 fix attempt\nPb3 final\n"
    # And fix-y's own files (B3's tree minus what plate's tree overwrites) are
    # consistent with the plate-tree restoration.
    # The plate's tree was built off B1, so it has fix.txt = "B1 fix\n".
    # After restoration, fix.txt should also equal the plate's version.
    assert (repo / "fix.txt").read_text() == "B1 fix\n"

    # 4. Resume command uses cwd + customTitle from the live transcript.
    assert result == "resume with: cd /Users/me/jot && claude --resume fix-y bug investigation"


def test_plate_next_jump_restores_plate_tree_without_post_plate_branch_changes(tmp_path: Path):
    """Per-function: cross-branch jump with readable target transcript."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_next_jump_restores_plate_tree_without_post_plate_branch_changes(repo, tmp_path)


def _check_plate_next_jump_lost_message_when_transcript_unreadable(base: Path) -> None:
    """Scenario: when the target plate's `convo-id` points at a path that
    doesn't exist on this machine, plate_next returns the canned lost
    message — and does so identically whether or not a `convo-summary`
    trailer is present. The branch switch and tree restoration still
    happen unconditionally; only the resume command differs.

    Runs twice in two sub-repos (summary present, summary absent) to lock
    in: the return string is identical either way, but the summary trailer
    is queryable from git in the present-case (so the next agent can find
    it).

    Topology in each sub-repo (same as test 2):
        main:    A ── B ── C
                       │    │
                       │    └── feature-x ── C1 ── C2
                       │                              │
                       │                              └── feature-x-plate ── Pa1 ── Pa2
                       │
                       └── fix-y ── B1 ── B2 ── B3
                                     │
                                     └── fix-y-plate (off B1) ── Pb1 ── Pb2 ── Pb3
                                             convo-id:      <fake/missing path>
                                             convo-summary: present | absent  (case A | B)
    """
    fake_transcript_path = Path("/nonexistent/path/that/should/never/exist.jsonl")
    assert not fake_transcript_path.exists(), "test precondition: fake transcript must not exist"

    for include_summary in (True, False):
        sub = base / f"repo-summary-{'present' if include_summary else 'absent'}"
        sub.mkdir(parents=True, exist_ok=True)
        repo = makeTestRepoWithSingleCommit(sub)

        shas = _buildTwoBranchPlateTopology(
            repo,
            transcript_for_fixy=fake_transcript_path,
            include_summary=include_summary,
        )
        assert getCurrentBranchName(repo) == "feature-x"

        plates = listPlateBranches(repo)
        fixy_index = next(
            i + 1 for i, p in enumerate(plates) if p["ref"] == "fix-y-plate"
        )

        result = plate_next(repo, index=str(fixy_index))

        # Lost message returned (identical in both cases).
        assert result == PLATE_NEXT_LOST_MESSAGE
        # Branch switch still happens.
        assert getCurrentBranchName(repo) == "fix-y"
        assert getSHAForRefViaRevParse(repo, "HEAD") == shas["sha_B3"]
        # Tree restoration still happens — fix-y-plate's tree (B1-based) is in WT.
        assert (repo / "fix.txt").read_text() == "B1 fix\n"

        # Summary trailer presence in git matches the parameter — proves the
        # next agent can find the summary when it's there, and that absence
        # of summary doesn't change the return string.
        trailers = getCommitTrailers(repo, "fix-y-plate")
        if include_summary:
            assert "convo-summary" in trailers
            assert trailers["convo-summary"]
        else:
            assert "convo-summary" not in trailers


def test_plate_next_jump_lost_message_when_transcript_unreadable(tmp_path: Path):
    """Per-function: lost-path jump, parametrized over summary present/absent."""
    _check_plate_next_jump_lost_message_when_transcript_unreadable(tmp_path)


def _check_plate_next_jump_self_index_is_noop(repo: Path, tmp_path: Path) -> None:
    """Scenario: HEAD on feature-x; user picks the index of feature-x-plate
    (the *current* plate). plate_next returns the unchanged-message and
    leaves the repo untouched — no implicit pre-push, no branch switch,
    no WT change.
    """
    transcript = tmp_path / "fixy-transcript.jsonl"
    _writeTranscriptFile(transcript, cwd="/Users/me/jot", custom_title="fix-y bug investigation")

    shas = _buildTwoBranchPlateTopology(repo, transcript_for_fixy=transcript)
    assert getCurrentBranchName(repo) == "feature-x"

    # Snapshot pre-call state so we can prove nothing changed.
    head_before = getSHAForRefViaRevParse(repo, "HEAD")
    feature_plate_sha_before = getSHAForRefViaRevParse(repo, "feature-x-plate")
    feature_plate_count_before = countCommitsReachableFromRef(repo, "feature-x-plate")
    fixy_plate_sha_before = getSHAForRefViaRevParse(repo, "fix-y-plate")
    feature_txt_before = (repo / "feature.txt").read_text()
    wt_clean_before = checkForCleanWorkTree(repo)

    plates = listPlateBranches(repo)
    self_index = next(
        i + 1 for i, p in enumerate(plates) if p["ref"] == "feature-x-plate"
    )

    result = plate_next(repo, index=str(self_index))

    # Return string identifies the plate via the title precedence chain.
    # feature-x-plate has a fake transcript (set by topology helper), so the
    # title falls back to the convo-name trailer ("feature work").
    assert result == "already on plate 'feature work'; worktree unchanged"

    # Nothing about the repo changed.
    assert getCurrentBranchName(repo) == "feature-x"
    assert getSHAForRefViaRevParse(repo, "HEAD") == head_before
    assert getSHAForRefViaRevParse(repo, "feature-x-plate") == feature_plate_sha_before
    assert countCommitsReachableFromRef(repo, "feature-x-plate") == feature_plate_count_before
    assert getSHAForRefViaRevParse(repo, "fix-y-plate") == fixy_plate_sha_before
    assert (repo / "feature.txt").read_text() == feature_txt_before
    assert checkForCleanWorkTree(repo) == wt_clean_before


def test_plate_next_jump_self_index_is_noop(tmp_path: Path):
    """Per-function: picking the current plate's index is a no-op."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_next_jump_self_index_is_noop(repo, tmp_path)


def _check_plate_next_jump_proceeds_when_head_on_branch_with_no_plate(
    repo: Path, tmp_path: Path
) -> None:
    """Scenario: HEAD is on a branch that has no associated plate (no
    `<branch>-plate` ref exists). User picks any index. Because no entry
    is `(current)`, the self-index check never matches; the jump proceeds
    normally — branch switch + tree restoration happen, the no-op message
    is NOT returned, and no spurious `<explore-branch>-plate` ref is
    created since WT is clean and pre-push is a no-op.
    """
    # 1. Build the canonical two-branch topology (feature-x with feature-x-plate
    #    parented to C2; fix-y with fix-y-plate parented to B1). Use a real
    #    transcript file for fix-y-plate so the local-resume path will fire.
    transcript = tmp_path / "fixy-transcript.jsonl"
    _writeTranscriptFile(transcript, cwd="/Users/me/jot", custom_title="fix-y bug investigation")
    shas = _buildTwoBranchPlateTopology(repo, transcript_for_fixy=transcript)

    # 2. Move HEAD to a brand-new branch `explore` off `main` that has NO
    #    associated `<branch>-plate` ref. WT is clean after the checkout.
    checkOutBranch(repo, "main")
    run(["git", "checkout", QUIET_OUTPUT, CREATE_BRANCH_AND_CHECKOUT_FLAG, "explore"], cwd=repo)
    assert getCurrentBranchName(repo) == "explore"
    assert not branchExists(repo, "explore-plate")
    assert checkForCleanWorkTree(repo)

    # 3. Resolve the index of fix-y-plate so we have a deterministic target.
    #    fix-y-plate has the readable transcript, so a successful jump should
    #    return the local-resume form.
    plates = listPlateBranches(repo)
    fixy_index = next(
        i + 1 for i, p in enumerate(plates) if p["ref"] == "fix-y-plate"
    )

    # 4. Run plate_next with that index. Because `explore-plate` doesn't
    #    exist, the listing has no `(current)` entry — the self-index
    #    early-return cannot fire — so the jump must proceed all the way
    #    through to the resume command.
    result = plate_next(repo, index=str(fixy_index))

    # 5. Assert the no-op message did NOT fire (proves the self-check
    #    didn't spuriously match).
    assert "already on plate" not in result

    # 6. Assert the jump completed: local-resume command returned (the
    #    target's transcript was readable), HEAD now on fix-y at B3,
    #    fix-y-plate's tree restored to WT (fix.txt = "B1 fix\n", with
    #    B2/B3 changes absent — same property as test 2).
    assert result == "resume with: cd /Users/me/jot && claude --resume fix-y bug investigation"
    assert getCurrentBranchName(repo) == "fix-y"
    assert getSHAForRefViaRevParse(repo, "HEAD") == shas["sha_B3"]
    assert (repo / "fix.txt").read_text() == "B1 fix\n"

    # 7. Assert no spurious `explore-plate` ref was created. The implicit
    #    pre-push (step 1 of jump-mode) ran while on `explore` with a clean
    #    WT, so plate_push's empty-WIP guard returned None and no commit
    #    was made.
    assert not branchExists(repo, "explore-plate")


def test_plate_next_jump_proceeds_when_head_on_branch_with_no_plate(tmp_path: Path):
    """Per-function: jump from a plate-less branch proceeds normally."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_next_jump_proceeds_when_head_on_branch_with_no_plate(repo, tmp_path)


def _check_plate_next_jump_invalid_index_returns_message(repo: Path, tmp_path: Path) -> None:
    """Scenario: user passes a bad index value. plate_next returns the
    appropriate canned message and the repo is untouched — no implicit
    pre-push, no branch switch, no WT change.

    Two error buckets, each with its own message:
      - Non-numeric ("abc", "1.5", "-1", "3a", "", "  ", "@#$") →
        `PLATE_NEXT_NON_NUMERIC_MESSAGE`. `str.isdigit()` rejects letters,
        decimals, signs, mixed input, empty strings, whitespace, and
        symbols.
      - Out-of-range ("99", "0") → `PLATE_NEXT_INVALID_INDEX_MESSAGE`.
        Note "-1" migrates to the non-numeric bucket: "-1".isdigit() is
        False because "-" is non-digit.
    """
    # 1. Build the two-branch topology so there are exactly 2 plates in the
    #    repo (feature-x-plate, fix-y-plate). HEAD ends on feature-x with a
    #    clean WT.
    transcript = tmp_path / "fixy-transcript.jsonl"
    _writeTranscriptFile(transcript, cwd="/Users/me/jot", custom_title="fix-y bug investigation")
    shas = _buildTwoBranchPlateTopology(repo, transcript_for_fixy=transcript)
    assert getCurrentBranchName(repo) == "feature-x"
    assert len(listPlateBranches(repo)) == 2

    # 2. Snapshot pre-call state so we can prove the rejected call had no
    #    side effects.
    head_before = getSHAForRefViaRevParse(repo, "HEAD")
    feature_plate_sha_before = getSHAForRefViaRevParse(repo, "feature-x-plate")
    fixy_plate_sha_before = getSHAForRefViaRevParse(repo, "fix-y-plate")
    feature_txt_before = (repo / "feature.txt").read_text()
    wt_clean_before = checkForCleanWorkTree(repo)

    # 3. Build (input, expected_message) pairs covering both buckets.
    cases = [
        # Non-numeric bucket — every str.isdigit()==False input.
        ("abc", PLATE_NEXT_NON_NUMERIC_MESSAGE),
        ("1.5", PLATE_NEXT_NON_NUMERIC_MESSAGE),
        ("-1",  PLATE_NEXT_NON_NUMERIC_MESSAGE),
        ("3a",  PLATE_NEXT_NON_NUMERIC_MESSAGE),
        ("",    PLATE_NEXT_NON_NUMERIC_MESSAGE),
        ("  ",  PLATE_NEXT_NON_NUMERIC_MESSAGE),
        ("@#$", PLATE_NEXT_NON_NUMERIC_MESSAGE),
        # Range bucket — numeric strings that are out of [1..len(plates)].
        ("99",  PLATE_NEXT_INVALID_INDEX_MESSAGE),
        ("0",   PLATE_NEXT_INVALID_INDEX_MESSAGE),
    ]

    # 4. For each case, call plate_next and assert (a) correct message and
    #    (b) repo state is unchanged.
    for invalid_index, expected_message in cases:
        result = plate_next(repo, index=invalid_index)
        assert result == expected_message, (
            f"index {invalid_index!r}: expected {expected_message!r}, got {result!r}"
        )
        # No side effects.
        assert getCurrentBranchName(repo) == "feature-x"
        assert getSHAForRefViaRevParse(repo, "HEAD") == head_before
        assert getSHAForRefViaRevParse(repo, "feature-x-plate") == feature_plate_sha_before
        assert getSHAForRefViaRevParse(repo, "fix-y-plate") == fixy_plate_sha_before
        assert (repo / "feature.txt").read_text() == feature_txt_before
        assert checkForCleanWorkTree(repo) == wt_clean_before


def test_plate_next_jump_invalid_index_returns_message(tmp_path: Path):
    """Per-function: invalid index returns user-facing message, no side effects."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_next_jump_invalid_index_returns_message(repo, tmp_path)


def _check_plate_next_list_empty_when_no_plates(repo: Path) -> None:
    """Scenario: a fresh repo has no plate refs. plate_next list-mode
    returns the friendly empty-list message instead of an empty string,
    so the user sees a clear signal that nothing is parked.
    """
    # 1. Confirm precondition: the repo has no plate-related refs at all.
    #    (No `*-plate` and no `*-plate-derived*` branches.)
    assert listPlateBranches(repo) == []

    # 2. Call list mode.
    result = plate_next(repo)

    # 3. Assert the friendly empty-list message is returned (not an empty
    #    string, which would look like a silent failure to the user).
    assert result == PLATE_NEXT_EMPTY_LIST_MESSAGE


def test_plate_next_list_empty_when_no_plates(tmp_path: Path):
    """Per-function: list mode on a repo with no plates returns the friendly
    empty-list message."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_next_list_empty_when_no_plates(repo)


def _check_plate_next_list_no_marker_when_head_has_no_plate(
    repo: Path, tmp_path: Path
) -> None:
    """Scenario: HEAD is on a branch (`explore`) that has no associated
    plate ref. Two unrelated plates exist (`feature-x-plate`, `fix-y-plate`).
    list-mode returns the listing as usual but with NO `(current)` marker
    on any line — the marker rule ("ref equals `<currentBranch>-plate`")
    doesn't match anything, so zero entries get marked.
    """
    # 1. Build the canonical two-branch topology with feature-x-plate and
    #    fix-y-plate. The fix-y-plate transcript is real (so titles resolve
    #    deterministically); feature-x-plate transcript is fake (falls back
    #    to convo-name trailer).
    transcript = tmp_path / "fixy-transcript.jsonl"
    _writeTranscriptFile(transcript, cwd="/Users/me/jot", custom_title="fix-y bug investigation")
    _buildTwoBranchPlateTopology(repo, transcript_for_fixy=transcript)

    # 2. Switch HEAD to a fresh `explore` branch off `main` that has no
    #    associated plate ref.
    checkOutBranch(repo, "main")
    run(["git", "checkout", QUIET_OUTPUT, CREATE_BRANCH_AND_CHECKOUT_FLAG, "explore"], cwd=repo)
    assert getCurrentBranchName(repo) == "explore"

    # 3. Confirm precondition: no `explore-plate` ref exists, but the two
    #    pre-existing plates DO exist.
    assert not branchExists(repo, "explore-plate")
    assert branchExists(repo, "feature-x-plate")
    assert branchExists(repo, "fix-y-plate")

    # 4. Call list mode.
    result = plate_next(repo)
    lines = result.split("\n")

    # 5. Assert exactly 2 entries are listed (the two existing plates).
    assert len(lines) == 2, f"expected 2 lines, got {len(lines)}: {result!r}"

    # 6. Assert NO line contains `(current)` — the marker rule didn't
    #    match anything because `explore-plate` doesn't exist.
    assert "(current)" not in result, (
        f"expected no `(current)` marker, got listing:\n{result}"
    )

    # 7. Assert sort order is unaffected: feature-x-plate (newer, pushed
    #    after fix-y-plate per the topology helper) is line 1, fix-y-plate
    #    is line 2.
    assert lines[0].startswith("1. `feature work` "), lines[0]
    assert lines[1].startswith("2. `fix-y bug investigation` "), lines[1]


def test_plate_next_list_no_marker_when_head_has_no_plate(tmp_path: Path):
    """Per-function: list mode marks no entries when HEAD has no plate."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_next_list_no_marker_when_head_has_no_plate(repo, tmp_path)


# ──────────────────────────────────────────────────────────────────────
# rewriteBranchTipSummary — strip convo-summary trailer from older plate
# commits and add (or replace) it on the new tip. Uses `git rebase -i
# --reword` driven by the dual-role editor at
# common/scripts/plate/_rebase_reword_summary.py.
# ──────────────────────────────────────────────────────────────────────

_REBASE_EDITOR_SCRIPT = (
    Path(__file__).resolve().parents[4]
    / "common" / "scripts" / "plate" / "_rebase_reword_summary.py"
)


def rewriteBranchTipSummary(repo: Path, branch: str, summary_text: str) -> str:
    """Rebase the <branch>-plate ref so only the tip carries a
    convo-summary trailer (set to summary_text). Earlier commits with a
    convo-summary trailer get it stripped. Returns the new tip SHA.

    Implementation: spin up a detached worktree on <branch>-plate, run
    `git rebase -i <merge-base-with-branch>` with custom editors that
    (a) mark every commit `reword` and (b) per-commit, strip any existing
    convo-summary line and append the new one only when the commit is
    the original tip. Then update-ref the original branch and remove
    the worktree.
    """
    plate_branch = f"{branch}-plate"
    if not branchExists(repo, plate_branch):
        raise RuntimeError(f"plate branch does not exist: {plate_branch}")

    parent_sha = run(["git", "merge-base", plate_branch, branch], cwd=repo)
    tip_sha = getSHAForRefViaRevParse(repo, plate_branch)
    if parent_sha == tip_sha:
        # Nothing to rebase; just amend the tip directly via the editor
        # script's logic. But there's no commit between parent and tip
        # to rebase. Skip — caller shouldn't hit this since plate_push
        # always advances the ref.
        return tip_sha

    # Worktree + summary file in a single tempdir for easy cleanup.
    with tempfile.TemporaryDirectory(prefix="plate-summary-") as td:
        td_path = Path(td)
        wt_dir = td_path / "wt"
        summary_file = td_path / "summary.txt"
        summary_file.write_text(summary_text)

        run(["git", "worktree", "add", "--detach", str(wt_dir), plate_branch],
            cwd=repo)
        try:
            wt_git_dir = wt_dir / ".git"
            # Worktrees use a `.git` file pointing at the real gitdir.
            # `git rev-parse --git-dir` resolves it.
            git_dir = Path(run(
                ["git", "rev-parse", "--git-dir"], cwd=wt_dir
            ))
            if not git_dir.is_absolute():
                git_dir = (wt_dir / git_dir).resolve()

            seq_editor = f"python3 {shlex.quote(str(_REBASE_EDITOR_SCRIPT))} sequence"
            msg_editor = (
                f"python3 {shlex.quote(str(_REBASE_EDITOR_SCRIPT))} message "
                f"--tip-sha {tip_sha} "
                f"--new-summary-file {shlex.quote(str(summary_file))} "
                f"--git-dir {shlex.quote(str(git_dir))}"
            )

            run(
                ["git", "rebase", "-i", parent_sha],
                cwd=wt_dir,
                env={
                    "GIT_SEQUENCE_EDITOR": seq_editor,
                    "GIT_EDITOR": msg_editor,
                },
            )

            new_tip_sha = run(["git", "rev-parse", "HEAD"], cwd=wt_dir)
            run(["git", "update-ref", f"refs/heads/{plate_branch}", new_tip_sha],
                cwd=repo)
        finally:
            run(["git", "worktree", "remove", "--force", str(wt_dir)], cwd=repo,
                check=False)

        return new_tip_sha


def _check_rewriteBranchTipSummary_strips_old_tip_and_adds_new_tip_summary(
    repo: Path,
) -> None:
    """Realistic mainline case for rewriteBranchTipSummary.

    Setup: a plate branch with two commits.
      commit-1 (parent of tip) carries convo-summary: "old summary" plus
        the standard convo-id / convo-name / parent-branch trailers
        (because the previous push fired the agent and wrote a summary).
      commit-2 (tip) has convo-id / convo-name / parent-branch but NO
        convo-summary (the new push just landed; agent hasn't written
        the new summary yet).

    After running rewriteBranchTipSummary(repo, branch, "<new text>"):
      - commit-1 has NO convo-summary trailer.
      - commit-2 (new tip) has convo-summary == "<new text>".
      - All other trailers (convo-id, convo-name, parent-branch) are
        preserved on both commits.
      - The branch ref points at the new tip.
    """
    branch = getCurrentBranchName(repo)
    plate_branch = f"{branch}-plate"

    parent_sha = getSHAForRefViaRevParse(repo, "HEAD")

    # Build commit-1: tree of HEAD plus a synthetic file path; commit
    # carries convo-summary + the standard trailers.
    addFileToGit(repo, makeTestFile(repo, "plate-1.txt"))
    stageAllChanges(repo)
    commit1_msg = (
        "plate-1\n\n"
        "convo-id: convo-aaa\n"
        "convo-name: my conversation\n"
        f"parent-branch: {branch}\n"
        "convo-summary: old summary"
    )
    run(["git", "commit", "-q", "-m", commit1_msg], cwd=repo)
    commit1_sha = getSHAForRefViaRevParse(repo, "HEAD")
    # Move the plate ref to commit-1, then reset HEAD so we can build commit-2 on top.
    run(["git", "branch", "-f", plate_branch, commit1_sha], cwd=repo)
    run(["git", "reset", "--hard", parent_sha], cwd=repo)

    # Build commit-2 (the new tip — no convo-summary yet).
    addFileToGit(repo, makeTestFile(repo, "plate-2.txt"))
    stageAllChanges(repo)
    commit2_msg = (
        "plate-2\n\n"
        "convo-id: convo-bbb\n"
        "convo-name: my conversation\n"
        f"parent-branch: {branch}"
    )
    # We need commit-2 to have commit-1 as parent to mirror the real
    # plate stack. Easiest: checkout the plate branch, commit there.
    run(["git", "checkout", "-q", plate_branch], cwd=repo)
    addFileToGit(repo, makeTestFile(repo, "plate-2.txt"))
    stageAllChanges(repo)
    run(["git", "commit", "-q", "-m", commit2_msg], cwd=repo)
    commit2_sha = getSHAForRefViaRevParse(repo, "HEAD")
    # Return HEAD to the original branch so the rewrite happens via worktree.
    run(["git", "checkout", "-q", branch], cwd=repo)

    # Sanity: plate ref points at commit-2, with commit-1 as its parent.
    assert getSHAForRefViaRevParse(repo, plate_branch) == commit2_sha
    pre_trailers_1 = getCommitTrailers(repo, commit1_sha)
    pre_trailers_2 = getCommitTrailers(repo, commit2_sha)
    assert pre_trailers_1.get("convo-summary") == "old summary"
    assert "convo-summary" not in pre_trailers_2

    # Run.
    new_tip_sha = rewriteBranchTipSummary(repo, branch, "the new summary text")

    # The branch ref must have advanced (or at least changed SHA).
    assert getSHAForRefViaRevParse(repo, plate_branch) == new_tip_sha
    # The two plate commits got rewritten — SHAs differ from before.
    # Walk only commits above the merge-base with the parent branch.
    new_log_shas = run(
        ["git", "log", "--format=%H", f"{parent_sha}..{plate_branch}"],
        cwd=repo,
    ).splitlines()
    assert len(new_log_shas) == 2, f"expected 2 plate commits; got {new_log_shas}"
    new_tip, new_parent = new_log_shas

    # Tip trailers: new convo-summary present + standard trailers preserved.
    tip_trailers = getCommitTrailers(repo, new_tip)
    assert tip_trailers.get("convo-summary") == "the new summary text", tip_trailers
    assert tip_trailers.get("convo-id") == "convo-bbb", (
        f"new_tip={new_tip} trailers={tip_trailers}"
    )
    assert tip_trailers.get("convo-name") == "my conversation"
    assert tip_trailers.get("parent-branch") == branch

    # Parent trailers: convo-summary stripped; other trailers preserved.
    parent_trailers = getCommitTrailers(repo, new_parent)
    assert "convo-summary" not in parent_trailers, parent_trailers
    assert parent_trailers.get("convo-id") == "convo-aaa"
    assert parent_trailers.get("convo-name") == "my conversation"
    assert parent_trailers.get("parent-branch") == branch


def test_rewriteBranchTipSummary_strips_old_tip_and_adds_new_tip_summary(tmp_path: Path) -> None:
    """Per-function: rebase-reword strips old summary, writes new on tip."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_rewriteBranchTipSummary_strips_old_tip_and_adds_new_tip_summary(repo)
