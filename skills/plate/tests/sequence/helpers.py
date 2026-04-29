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
import string
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

# -- git command flags used by helpers below --

QUIET_OUTPUT = "-q"
COMMIT_MESSAGE = "-m"
BRANCH_NAME = "-b"

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

COMMIT_MESSAGE = "-m"
BRANCH_NAME = "-b"

def makeEmptyRepo(path: Path) -> Path:
    """Create a new, empty repo with a single main branch."""
    repo = path / "repo"
    repo.mkdir(parents=True)                               
    run(["git", "init", QUIET_OUTPUT, BRANCH_NAME, "main"],
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

def makeTestRepoWithSingleCommit(base: Path) -> Path:
    repo = makeTestRepo(base=base)
    # add a file to it
    fileName = TEST_FILENAME
    addFileToGit(repo, makeTestFile(repo, fileName))
    # commit the test file
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

def checkOutBranch(repo: Path, branch_name: str) -> None:
    run(["git", "checkout", QUIET_OUTPUT, BRANCH_NAME, branch_name], cwd=repo)

def test_checkOutBranch(tmp_path: Path):
    repo = makeTestRepo(base=tmp_path)
    branch_name = createRandomBranchName()
    checkOutBranch(repo=repo, branch_name=branch_name)
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
    run(["git", "commit", QUIET_OUTPUT, COMMIT_MESSAGE, message], cwd=repo)

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

def modifyRandomlyChosenTrackedFile(repo: Path, files: list[str]):
    # randomly choose a file from files
    fileName = random.choice(files)
    # modify it
    return modifyTrackedFile(repo, fileName, rng=random.Random())

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

    # main: commit A
    (repo / TEST_FILENAME).write_text(TEST_FILE_CONTENTS)
    addFileToGit(repo, TEST_FILENAME)
    createCommit(repo=repo, message="A")

    # randomly-named branch off main, with B and F1 commits
    branch_name = createRandomBranchName()
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
        return modifyRandomlyChosenTrackedFile(repo, tracked)

    return createUntrackedFile(repo, rng)

def test_performRandomEdit_seeded_is_deterministic(tmp_path: Path):  
    repo = makeTestRepoWithSingleCommit(tmp_path)          
    a = performRandomEdit(repo, seed=42)                 
    # reset and replay                                     
    run(["git", "reset", "--hard"], cwd=repo)
    run(["git", "clean", "-fd"], cwd=repo) 
    b = performRandomEdit(repo, seed=42)
    # expect the same results from two deterministic (same seed) calls
    assert a == b

# ── Implemented: assertion utilities ──────────────────────────────────

def branchExists(repo: Path, name: str) -> bool:
    """True iff refs/heads/<name> exists."""
    # git branch --list <branch_name>
    list_output = run(["git", "branch", "--list"], cwd=repo)
    print("branchExists()")
    # strip out any * in the branch names
    list_output = list_output.replace("*", "")
    print(list_output.splitlines()) 
    # the branch exists if it's name appears in the list of branches
    return name in list_output

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

def setGitIndexFileForEnv(env: dict[str, str], tmp_index_path: str) -> dict[str, str]:
    env["GIT_INDEX_FILE"] = tmp_index_path
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

def readGitTreeAt(repo: Path, tree_ish: str, env: dict[str, str]) -> str:
    return run(["git", "read-tree", tree_ish], cwd=repo, env=env)

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
        readGitTreeAt(repo=repo, tree_ish="HEAD", env=env)
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
        env = setGitIndexFileForEnv({}, tmp_index_path)
        _ = readGitTreeAt(repo, "HEAD", env)
        wt_tree = writeGitTree(repo, env)
    finally:
        Path(tmp_index_path).unlink(missing_ok=True)

    # Parent: existing plate tip if branch already exists, else HEAD.
    if branchExists(repo, plateBranchName):
        parent = getSHAForRefViaRevParse(repo, plateBranchName)
    else:
        parent = getSHAForRefViaRevParse(repo, "HEAD")

    # Empty-WIP guard. If the WT tree is identical to the would-be
    # parent's tree, no change has occurred since the last plate push.
    parent_tree = getSHAForRefViaRevParse(repo, getTreeRevOf(parent))
    if wt_tree == parent_tree:
        print(f"No changes to push, plate-push returns None: WT tree {wt_tree} == parent tree {parent_tree}")
        return None

    # Create the new plate commit and advance the plate branch ref.
    print(f"Creating new plate commit with WT tree {wt_tree} and parent {parent}")
    new_commit = run(
        [
            "git", "commit-tree", wt_tree,
            "-p", parent,
            COMMIT_MESSAGE, f"plate: WIP on {branch}",
        ],
        cwd=repo,
    )
    run(["git", "update-ref", f"refs/heads/{plateBranchName}", new_commit], cwd=repo)

    return new_commit


def plate_done(repo: Path, branch: Optional[str] = None) -> list[str]:
    """STUB. Run the canonical /plate --done (Step 9).

    Sequence:
        Step 0  implicit pre-push (only if WT tree differs from plate tip)
        Step 1  git reset --hard
                git clean -fd
        Step 2  git cherry-pick HEAD..<branch>-plate
        Step 3  git branch -D <branch>-plate

    Args:
        branch: working branch name; defaults to current.

    Returns:
        List of new commit SHAs cherry-picked onto <branch>, oldest-first.
    """
    raise NotImplementedError("plate_done: see Step 9 in walkthrough log")


def plate_drop(repo: Path, branch: Optional[str] = None) -> Path:
    """STUB. Pop the top plate from <branch>-plate, save as patch.

    Sequence:
        - Build WT-tree via temp-index (capture tracked + untracked).
        - Write .plate/dropped/<branch>-plate_<ts>.patch as
          `git diff --binary <branch> <WT-tree>`.
        - Rewind <branch>-plate to <branch>-plate~1 (or `git branch -D`
          if last plate).
        - WT untouched.

    Returns:
        Path to the generated .patch file.
    """
    raise NotImplementedError("plate_drop")


def plate_trash(
    repo: Path,
    branch: Optional[str] = None,
    clean_wt: bool = False,
) -> Path:
    """STUB. Delete <branch>-plate entirely, save combined patch.

    Args:
        branch: working branch name; defaults to current.
        clean_wt: if True, run git reset --hard + git clean -fd after
                  writing the patch (mode b — destructive of post-plate
                  WT edits not in the patch). If False, leave WT alone
                  (mode a — patch redundant with WT). Decision pending.

    Returns:
        Path to the generated .patch file.
    """
    raise NotImplementedError("plate_trash")


def plate_recycle(
    repo: Path,
    branch: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> str:
    """STUB. Replay a trashed stack into a fresh <branch>-plate.

    Implementation must use Path 2 — per-plate patches replayed
    sequentially. Path 1 (single-patch single-recovered-plate) was
    rejected because it loses commit boundaries.

    Args:
        branch: working branch name; defaults to current.
        timestamp: pick a specific trash session by timestamp; defaults
                   to most recent.

    Returns:
        SHA of the recycled <branch>-plate tip.
    """
    raise NotImplementedError("plate_recycle")


def plate_carry(repo: Path, target_plate: str) -> None:
    """STUB. Push current WIP, then check out target plate branch.

    Phase A: canonical /plate push of current WIP onto
             <current-branch>-plate.
    Phase B: present picker (in tests, target_plate is given directly),
             check out the chosen plate branch.
    """
    raise NotImplementedError("plate_carry")


def plate_next(repo: Path) -> str:
    """STUB. Walk the parent-trailer chain across <base>-derived*
    branches, return the resume command (e.g.
    "cd <cwd> && claude --resume <convoID>").
    """
    raise NotImplementedError("plate_next")


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
    raise NotImplementedError("simulate_derived_agent")


def apply_patch(repo: Path, patch: Path) -> None:
    """STUB. Apply a saved .patch file via `git apply --3way <patch>`."""
    raise NotImplementedError("apply_patch")
