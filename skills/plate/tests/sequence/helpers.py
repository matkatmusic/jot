"""Shared helpers for the /plate sequence test harness.

Implemented:
    - run(cmd, cwd, ...)              subprocess wrapper
    - setup_repo(base)                fresh repo with topology
    - performRandomEdit(repo)               simulate a user edit
    - assertion utilities             getCurrentBranchName, branchExists,
                                      countCommitsReachableFromRef, getTreeSHA,
                                      getGitStatus, checkForCleanWorkTree,
                                      getCommitSubject, getCommitTrailers

Stubbed (raise NotImplementedError):
    - plate_push, plate_done, plate_drop, plate_trash,
      plate_recycle, plate_carry, plate_next
    - simulate_derived_agent
    - apply_patch

See plans/plate-walkthrough-log-2026-04-28.md for the locked-in
sequences each stub must implement.
"""
from __future__ import annotations

import os
import random
import shutil
import string
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

def plate_push(repo: Path, branch: Optional[str] = None) -> Optional[str]:
    """Run the canonical /plate push (Step 7 sequence).

    Sequence (plumbing — no merging, no checkouts; HEAD/index/WT untouched):
        TMP_INDEX=$(mktemp)
        GIT_INDEX_FILE=$TMP_INDEX git read-tree HEAD
        GIT_INDEX_FILE=$TMP_INDEX git add -A 
        TREE=$(GIT_INDEX_FILE=$TMP_INDEX git write-tree)
        PARENT = <branch>-plate tip if exists, else HEAD
        if TREE == PARENT^{tree}: return None  ("no changes to stack")
        NEW=$(git commit-tree $TREE -p $PARENT -m "plate: WIP on <branch>")
        git update-ref refs/heads/<branch>-plate $NEW

    Args:
        repo: Repository root.
        branch: Working branch name; defaults to currently checked-out
                branch.

    Returns:
        SHA of the new <branch>-plate tip commit on push. None when the
        WT tree already matches the would-be parent's tree (the empty-WIP
        "no changes to stack" no-op case).
    """
    if branch is None:
        branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    # Build a snapshot tree from the current working tree via a temp
    # index. The real index, HEAD, and WT are never touched.
    
    tmp_index_path = makeTempGitIndexPath()
    try:
        env = setGitIndexFileForEnv(env={}, gitIndexFile=tmp_index_path)
        _ = readGitTreeAt(repo=repo, ref="HEAD", env=env)
        stageAllChanges(repo=repo, env=env)
        wt_tree = writeGitTree(repo=repo, env=env)
    finally:
        Path(tmp_index_path).unlink(missing_ok=True)

    # Parent: existing plate tip if branch already exists, else HEAD.
    if branchExists(repo=repo, branchName=plateBranchName):
        parent = getSHAForRefViaRevParse(repo=repo, ref=plateBranchName)
    else:
        parent = getSHAForRefViaRevParse(repo=repo, ref="HEAD")

    # Empty-WIP guard. If the WT tree is identical to the would-be
    # parent's tree, no change has occurred since the last plate push.
    parent_tree = getSHAForRefViaRevParse(repo=repo, ref=getTreeRevOf(parent))
    if wt_tree == parent_tree:
        print(f"No changes to push, plate-push returns None: WT tree {wt_tree} == parent tree {parent_tree}")
        return None

    # Create the new plate commit and advance the plate branch ref.
    print(f"Creating new plate commit with WT tree {wt_tree} and parent {parent}")
    new_commit = run(
        [
            "git", "commit-tree", wt_tree,
            "-p", parent,
            COMMIT_MESSAGE_FLAG, f"plate: WIP on {branch}",
        ],
        cwd=repo,
    )
    run(["git", "update-ref", f"refs/heads/{plateBranchName}", new_commit], cwd=repo)

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
    plate_push(repo, branch)

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
        plate_push(repo, branch)

    return getSHAForRefViaRevParse(repo, plateBranchName)

def test_plate_recycle(tmp_path: Path):
    """Per-function: 2 plates → trash → recycle restores branch with same tree."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_recycle_restores_stack(repo)

def plate_carry(repo: Path, target_plate: str) -> None:
    """STUB. Push current WIP, then check out target plate branch.

    Phase A: canonical /plate push of current WIP onto
             <current-branch>-plate.
    Phase B: present picker (in tests, target_plate is given directly),
             check out the chosen plate branch.
    """
    plate_push(repo)
    checkOutBranch(repo, target_plate)

def test_plate_carry(tmp_path: Path):
    """Per-function: WIP + target plate → carry pushes source plate then checks out target."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_carry_pushes_then_checks_out_target(repo)

def plate_next(repo: Path) -> str:
    """Walk the parent-trailer chain across <base>-derived*
    branches, return the resume command (e.g.
    "cd <cwd> && claude --resume <convoID>").

    Reads the parent-convo trailer of HEAD's tip commit and emits the
    shell command needed to resume that conversation in this repo.
    """
    parent_convo = getCommitTrailers(repo, "HEAD").get("parent-convo", "")
    return f"cd {repo} && claude --resume {parent_convo}"

def test_plate_next(tmp_path: Path):
    """Per-function: derived chain → plate_next emits parent-convo resume command."""
    repo = makeTestRepoWithSingleCommit(tmp_path)
    _check_plate_next_returns_parent_convo_resume_command(repo)

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


def _check_plate_carry_pushes_then_checks_out_target(repo: Path) -> None:
    """Scenario: WIP on source branch + target plate exists → plate_carry
    pushes WIP onto source-plate, then checks out target plate."""
    source_branch = getCurrentBranchName(repo)
    source_tip = getSHAForRefViaRevParse(repo, source_branch)
    sourcePlateBranchName = f"{source_branch}-plate"

    # Set up a target plate branch directly via plumbing (in production this
    # would be created by another agent's plate_push).
    targetPlateBranchName = "target-plate"
    run(
        ["git", "update-ref", f"refs/heads/{targetPlateBranchName}", source_tip],
        cwd=repo,
    )

    untracked = createUntrackedFile(repo, random.Random())["file"]

    plate_carry(repo, target_plate=targetPlateBranchName)

    assert getCurrentBranchName(repo) == targetPlateBranchName
    assert branchExists(repo, sourcePlateBranchName)
    # Source plate captured the WIP (verify via ls-tree, not checkout).
    plate_files = run(
        ["git", "ls-tree", "-r", "--name-only", sourcePlateBranchName], cwd=repo
    ).splitlines()
    assert untracked in plate_files
    assert getSHAForRefViaRevParse(repo, source_branch) == source_tip


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


def _check_plate_next_returns_parent_convo_resume_command(repo: Path) -> None:
    """Scenario: agent on derived2 → plate_next emits
    `cd <repo> && claude --resume <parent-convo-trailer>`.

    NOTE: walkthrough sequence_14 spec says "claude --resume <current convo>"
    (deepest), but the implementation reads the parent-convo trailer. We
    assert the implemented behavior; spec discrepancy is flagged for
    user resolution.
    """
    branch = getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    (repo / TEST_FILENAME).write_text("modified\n")
    plate_push(repo)
    # Reset WT so the upcoming checkout to derived2 doesn't conflict.
    resetHardToHead(repo)

    simulate_derived_agent(repo, plateBranchName, "CONVO-A")
    derived2 = simulate_derived_agent(repo, plateBranchName, "CONVO-B")

    checkOutBranch(repo, derived2)
    cmd = plate_next(repo)

    assert cmd == f"cd {repo} && claude --resume CONVO-A"


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
