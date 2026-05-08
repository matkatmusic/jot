"""Git-test scaffolding helpers extracted from plate_lib.py.

These functions build small disposable git repos, simulate user edits,
and produce timestamps for trash-session directories. They are used by
the /plate sequence test harness and by tests/test_git_lib.py.

Extracted per MIGRATION_TO_PYTHON.md (NEEDS_MIGRATION_TO: git_test_funcs_lib.py).

Note on import ordering: this module pulls a handful of names
(`createRandomBranchName`, `TEST_FILENAME`, `TEST_FILE_CONTENTS`,
`B_FILENAME`, `B_FILE_CONTENTS`, `F1_FILENAME`, `F1_FILE_CONTENTS`)
from `plate_lib`. plate_lib defines those names *before* it executes
its `from common.scripts.git_test_funcs_lib import *` re-export, so
the cycle resolves cleanly.
"""
from __future__ import annotations

import random
import time
from pathlib import Path

from common.scripts.git_lib import (
    QUIET_OUTPUT,
    CREATE_BRANCH_AND_CHECKOUT_FLAG,
    addFileToGit,
    checkOutGitBranch,
    createGitBranch,
    createGitCommit,
    createGitUserConfig,
    run,
    writeGitIgnore,
)


def makeEmptyRepo(path: Path) -> Path:
    """Create a new, empty repo with a single main branch."""
    repo = path / "repo"
    repo.mkdir(parents=True)
    run(["git", "init", QUIET_OUTPUT, CREATE_BRANCH_AND_CHECKOUT_FLAG, "main"],
cwd=repo)
    return repo

# def getGitStatus(repo: Path) -> dict[str, str]:
#     return run(["git", "status", "--porcelain"], cwd=repo).splitlines()

def makeTestRepo(base: Path) -> Path:
    repo = makeEmptyRepo(path=base)
    createGitUserConfig(repo)
    return repo


def makeTestRepoWithSingleCommit(base: Path) -> Path:
    repo = makeTestRepo(base=base)
    # Ignore .plate/ so the skill's stash dir survives `git clean -fd`.
    writeGitIgnore(repo)
    addFileToGit(repo, ".gitignore")
    # add the test file
    addFileToGit(repo, makeTestFile(repo, TEST_FILENAME))
    # commit both files together as the initial commit
    createGitCommit(repo, TEST_COMMIT_MESSAGE)
    return repo


def makeTestFile(repo: Path, fileName: str) -> Path:
    file = repo / fileName
    file.write_text(TEST_FILE_CONTENTS)
    return file


# ── Implemented: simulate user edits ──────────────────────────────────
def modifyTrackedFile(repo: Path, file: str, rng: random.Random) -> dict:
    path = repo / file
    path.write_text(path.read_text() + f"random-{random_string(rng=rng)}\n")
    return {"action": "modify_tracked", "file": path.name}

def modifyRandomlyChosenTrackedFile(
    repo: Path,
    files: list[str],
    rng: random.Random = random,
):
    # randomly choose a file from <files> using the supplied rng so that
    # callers passing a seeded rng get deterministic behavior.
    fileName = rng.choice(files)
    return modifyTrackedFile(repo, fileName, rng=rng)

def createUntrackedFile(repo: Path, rng: random.Random) -> dict:
    name = f"new-{random_string(rng=rng)}.txt"
    path = repo / name
    path.write_text(f"content-{random_string(rng=rng)}\n")
    return {"action": "create_untracked", "file": name}


def setup_git_plate_test_repo(base: Path) -> Path:
    """Create a fresh git repo at base/repo and return its path.

    Topology:
        main:      A         (root commit)
                   \\
        <random>:   B - F1   (checked out, clean WT)

    The non-main branch name is randomized per call to mimic real-world
    variance. Tests should query it via getCurrentGitBranchName(repo) rather
    than hardcoding a value.

    Files:
        a.txt   on main,           content "A"
        b.txt   on <random branch>, content "B"
        fix.txt on <random branch>, content "F1"
    """
    repo = makeEmptyRepo(path=base)
    createGitUserConfig(repo)

    # main: commit A — also stages .gitignore so .plate/ is ignored
    # and survives `git clean -fd` during plate_trash(clean_wt=True).
    writeGitIgnore(repo)
    addFileToGit(repo, ".gitignore")
    (repo / TEST_FILENAME).write_text(TEST_FILE_CONTENTS)
    addFileToGit(repo, TEST_FILENAME)
    createGitCommit(repo=repo, message="A")

    # randomly-named branch off main, with B and F1 commits
    branch_name = createRandomBranchName()
    createGitBranch(repo, branch_name)
    checkOutGitBranch(repo=repo, branch_name=branch_name)

    (repo / B_FILENAME).write_text(B_FILE_CONTENTS)
    addFileToGit(repo, B_FILENAME)
    createGitCommit(repo=repo, message="B")

    (repo / F1_FILENAME).write_text(F1_FILE_CONTENTS)
    addFileToGit(repo, F1_FILENAME)
    createGitCommit(repo=repo, message="F1")

    return repo


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
    createGitUserConfig(repo)

    # main: commit A — also stages .gitignore so .plate/ is ignored
    # and survives `git clean -fd` during plate_trash(clean_wt=True).
    writeGitIgnore(repo)
    addFileToGit(repo, ".gitignore")
    (repo / TEST_FILENAME).write_text(TEST_FILE_CONTENTS)
    addFileToGit(repo, TEST_FILENAME)
    createGitCommit(repo=repo, message="A")

    # randomly-named branch off main, with B and F1 commits
    branch_name = createRandomBranchName()
    createGitBranch(repo, branch_name)
    checkOutGitBranch(repo=repo, branch_name=branch_name)

    (repo / B_FILENAME).write_text(B_FILE_CONTENTS)
    addFileToGit(repo, B_FILENAME)
    createGitCommit(repo=repo, message="B")

    (repo / F1_FILENAME).write_text(F1_FILE_CONTENTS)
    addFileToGit(repo, F1_FILENAME)
    createGitCommit(repo=repo, message="F1")

    return repo


def currentTimestampUtcCompact() -> str:
    """UTC ISO8601-compact timestamp for trash session-dir naming.

    Format: YYYYMMDDTHHMMSSZ (lex-sortable → chronological).
    """
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


# Late import: pulls constants + createRandomBranchName + random_string from
# plate_lib AFTER they are bound there. plate_lib's `from ...git_test_funcs_lib
# import *` runs after those definitions, so this resolves without a cycle.
from common.scripts.plate.plate_lib import (  # noqa: E402
    B_FILENAME,
    B_FILE_CONTENTS,
    F1_FILENAME,
    F1_FILE_CONTENTS,
    TEST_COMMIT_MESSAGE,
    TEST_FILENAME,
    TEST_FILE_CONTENTS,
    createRandomBranchName,
    random_string,
)
