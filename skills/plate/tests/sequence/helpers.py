"""Shared helpers for the /plate sequence test harness.

Implemented:
    - run(cmd, cwd, ...)              subprocess wrapper
    - setup_repo(base)                fresh repo with topology
    - random_edit(repo)               simulate a user edit
    - assertion utilities             getCurrentBranchName, branchExists,
                                      commit_count, getTreeSHA,
                                      status_porcelain, is_clean_wt,
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

def createUserConfig(repo: Path) -> None:
    run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    run(["git", "config", "user.name", "Test User"], cwd=repo)

def checkOutBranch(repo: Path, branch_name: str) -> None:
    run(["git", "checkout", QUIET_OUTPUT, BRANCH_NAME, branch_name], cwd=repo)


def createCommit(repo: Path, message: str) -> None:
    run(["git", "commit", QUIET_OUTPUT, COMMIT_MESSAGE, message], cwd=repo)

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
    repo = base / "repo"
    repo.mkdir(parents=True)

    run(["git", "init", QUIET_OUTPUT, BRANCH_NAME, "main"], cwd=repo)
    createUserConfig(repo)

    # main: commit A
    (repo / "a.txt").write_text("A\n")
    run(["git", "add", "a.txt"], cwd=repo)
    run(["git", "commit", QUIET_OUTPUT, COMMIT_MESSAGE, "A"], cwd=repo)

    # randomly-named branch off main, with B and F1 commits
    branch_name = createRandomBranchName()
    checkOutBranch(repo=repo, branch_name=branch_name)

    (repo / "b.txt").write_text("B\n")
    run(["git", "add", "b.txt"], cwd=repo)
    createCommit(repo=repo, message="B")

    (repo / "fix.txt").write_text("F1\n")
    run(["git", "add", "fix.txt"], cwd=repo)
    createCommit(repo=repo, message="F1")

    return repo

def random_string(length: int = 8, rng: random.Random = random) -> str:
    return "".join(rng.choices(string.ascii_lowercase, k=length))

# ── Implemented: simulate user edits ──────────────────────────────────
def getGitFilesList(repo: Path) -> list[str]:
    return run(["git", "ls-files"], cwd=repo).splitlines()

def modifyTrackedFile(repo: Path, tracked: list[str], rng: random.Random) -> dict:
    target = rng.choice(tracked)
    path = repo / target
    path.write_text(path.read_text() + f"random-{random_string(rng=rng)}\n")
    return {"action": "modify_tracked", "file": target}

def createUntrackedFile(repo: Path, rng: random.Random) -> dict:
    name = f"new-{random_string(rng=rng)}.txt"
    path = repo / name
    path.write_text(f"content-{random_string(rng=rng)}\n")
    return {"action": "create_untracked", "file": name}



def random_edit(repo: Path, *, seed: Optional[int] = None) -> dict:
    """Make a random edit to the repo to simulate user activity.

    Picks one of:
        modify_tracked    append a random line to an existing tracked file
        create_untracked  create a new untracked file with random content

    Returns a dict describing the action, e.g.:
        {"action": "modify_tracked", "file": "fix.txt"}
        {"action": "create_untracked", "file": "new-abcd.txt"}
    """
    rng = random.Random(seed) if seed is not None else random

    tracked = getGitFilesList(repo=repo)
    actions = ["modify_tracked", "create_untracked"]
    if not tracked:
        actions.remove("modify_tracked")

    action = rng.choice(actions)

    if action == "modify_tracked":
        return modifyTrackedFile(repo, tracked, rng)

    return createUntrackedFile(repo, rng)


# ── Implemented: assertion utilities ──────────────────────────────────

def getCurrentBranchName(repo: Path) -> str:
    """Return the current branch name (e.g. 'fix')."""
    return run(["git", "symbolic-ref", "--short", "HEAD"], cwd=repo)


def branchExists(repo: Path, name: str) -> bool:
    """True iff refs/heads/<name> exists."""
    completed = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{name}"],
        cwd=repo,
        check=False,
    )
    return completed.returncode == 0


def commit_count(repo: Path, ref: str) -> int:
    """Number of commits reachable from <ref>."""
    return int(run(["git", "rev-list", "--count", ref], cwd=repo))


def getTreeSHA(repo: Path, ref: str) -> str:
    """SHA of the tree pointed to by <ref>."""
    return run(["git", "rev-parse", f"{ref}^{{tree}}"], cwd=repo)


def status_porcelain(repo: Path) -> str:
    """Output of `git status --porcelain` (empty string when clean)."""
    return run(["git", "status", "--porcelain"], cwd=repo)


def is_clean_wt(repo: Path) -> bool:
    """True iff WT and index match HEAD with no untracked files."""
    return status_porcelain(repo) == ""


def getCommitSubject(repo: Path, ref: str) -> str:
    """Subject line of the commit at <ref>."""
    return run(["git", "log", "-1", "--format=%s", ref], cwd=repo)


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


# ── Stubs: plate operations ───────────────────────────────────────────
# Each stub raises NotImplementedError. Implementations should follow
# the canonical sequences locked in plate-walkthrough-log-2026-04-28.md.


def plate_push(repo: Path, branch: Optional[str] = None) -> str:
    """STUB. Run the canonical /plate push (Step 7).

    Sequence (plumbing, no merging, no checkouts):
        TMP_INDEX=$(mktemp -t plate-index)
        GIT_INDEX_FILE=$TMP_INDEX git read-tree HEAD
        GIT_INDEX_FILE=$TMP_INDEX git add -A --force
        TREE=$(GIT_INDEX_FILE=$TMP_INDEX git write-tree)
        if <branch>-plate exists:
            PARENT=$(git rev-parse <branch>-plate)
        else:
            PARENT=$(git rev-parse HEAD)
        NEW=$(git commit-tree $TREE -p $PARENT -m "plate: WIP on <branch>")
        git update-ref refs/heads/<branch>-plate $NEW
        rm -f $TMP_INDEX

    Args:
        branch: working branch name; defaults to current.

    Returns:
        SHA of the new <branch>-plate tip commit.
    """
    raise NotImplementedError("plate_push: see Step 7 in walkthrough log")


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
