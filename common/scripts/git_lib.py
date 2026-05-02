"""Shared git utilities used by /plate and other jot scripts.

Self-contained: defines the `run()` subprocess wrapper, git CLI flag
constants, test-config constants (USER_EMAIL_*, USER_NAME_*), and the
default GITIGNORE_CONTENTS string used by the test harness.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

# ── git CLI flag constants ────────────────────────────────────────────
QUIET_OUTPUT = "-q"
COMMIT_MESSAGE_FLAG = "-m"
CREATE_BRANCH_AND_CHECKOUT_FLAG = "-b"

# ── test-config constants ─────────────────────────────────────────────
USER_EMAIL_KEY = "user.email"
USER_EMAIL_VALUE = "test@example.com"
USER_NAME_KEY = "user.name"
USER_NAME_VALUE = "Test User"
GITIGNORE_CONTENTS = ".plate/\n"


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


def currentTimestampMs() -> str:
    """Millisecond-resolution timestamp for patch-file naming."""
    return str(int(time.time() * 1000))


# ── Git helpers ───────────────────────────────────────────────────────
def isGitRepo(path: Path) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0

def setGitUserConfigValue(repo: Path, config_key: str, config_value: str) -> None:
    run(["git", "config", config_key, config_value], cwd=repo)

def getGitUserConfigValue(repo: Path, config_key: str) -> str:
    return run(["git", "config", config_key], cwd=repo)

def writeGitIgnore(repo: Path, contents: str = GITIGNORE_CONTENTS) -> Path:
    """Write a .gitignore file at repo root and return its path.

    Default contents ignore the /plate skill's local stash directory
    (.plate/) so it is treated as ignored rather than untracked, which
    means `git clean -fd` won't blow it away (that requires `-x`).
    """
    path = repo / ".gitignore"
    path.write_text(contents)
    return path


def createGitUserConfig(repo: Path) -> None:
    setGitUserConfigValue(repo, USER_EMAIL_KEY, USER_EMAIL_VALUE)
    setGitUserConfigValue(repo, USER_NAME_KEY, USER_NAME_VALUE)

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

def createGitBranch(repo: Path, branch_name: str) -> None:
    # git branch -q <branch-name>
    run(["git", "branch", QUIET_OUTPUT, branch_name], cwd=repo)

def checkOutGitBranch(repo: Path, branch_name: str) -> None:
    # git checkout -q <branch-name>
    run(["git", "checkout", QUIET_OUTPUT, branch_name], cwd=repo)

def createAndCheckoutGitBranch(repo: Path, branch_name: str) -> None:
    run(["git", "checkout", QUIET_OUTPUT, CREATE_BRANCH_AND_CHECKOUT_FLAG, branch_name], cwd=repo)

def getCurrentGitBranchName(repo: Path) -> str:
    """Return the current branch name (e.g. 'fix')."""
    # git branch --show-current
    return run(["git", "branch", "--show-current"], cwd=repo)

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


def stageAllGitChanges(repo: Path, env: dict[str, str] | None = None) -> None:
    run(["git", "add", "-A"], cwd=repo, env=env)

def gitStashFiles(repo: Path, files: list[str]) -> None:
    """Stash the named files (tracked or untracked) and remove them from WT.

    Uses `git stash push -u --` so that untracked files in <files> are
    included in the stash. After the call, the named files are gone from
    the WT and saved on the top of the stash stack (stash@{0}). Use
    unstashFiles() to restore them.
    """
    run(["git", "stash", "push", "-u", QUIET_OUTPUT, "--"] + files, cwd=repo)

def gitUnstashFiles(repo: Path) -> None:
    """Pop the top of the stash stack back into the WT (stash@{0})."""
    run(["git", "stash", "pop", QUIET_OUTPUT], cwd=repo)

def addMultipleFilesToGit(repo: Path, files: list[str]) -> None:
    run(["git", "add"] + files, cwd=repo)

def createGitCommit(repo: Path, message: str) -> None:
    run(["git", "commit", QUIET_OUTPUT, COMMIT_MESSAGE_FLAG, message], cwd=repo)

def checkIfGitBranchExists(repo: Path, branchName: str) -> bool:
    """True iff refs/heads/<branchName> exists."""
    # git branch --list <branchName>
    list_output = run(["git", "branch", "--list"], cwd=repo)
    # strip out any * in the branch names
    list_output = list_output.replace("*", "")
    # the branch exists if its name appears in the list of branches
    return branchName in list_output

def countGitCommitsReachableFromRef(repo: Path, ref: str) -> int:
    """Number of commits reachable from <ref>."""
    return int(run(["git", "rev-list", "--count", ref], cwd=repo))

def setGitIndexFileForEnv(env: dict[str, str], gitIndexFile: str) -> dict[str, str]:
    env["GIT_INDEX_FILE"] = gitIndexFile
    return env


def getSHAForGitRefViaRevParse(repo: Path, ref: str) -> str:
    return run(["git", "rev-parse", ref], cwd=repo)

def readGitTreeAt(repo: Path, ref: str, env: dict[str, str]) -> str:
    return run(["git", "read-tree", ref], cwd=repo, env=env)

def writeGitTree(repo: Path, env: dict[str, str]) -> str:
    return run(["git", "write-tree"], cwd=repo, env=env)

def getGitTreeRevOf(commit: str) -> str:
    """Return the git rev-spec that peels <commit> to its tree.
    The returned string is a rev-spec (e.g. 'abc1234^{tree}'), NOT a SHA.
    Pass it to git rev-parse — or any command taking a <rev> — to resolve it to the SHA of the commit's tree.
    """
    return f"{commit}^{{tree}}"

def getGitTreeSHA(repo: Path, ref: str) -> str:
    """SHA of the tree pointed to by <ref>."""
    return getSHAForGitRefViaRevParse(repo, getGitTreeRevOf(ref))

def getGitStatus(repo: Path) -> str:
    """Output of `git status --porcelain` (empty string when clean)."""
    return run(["git", "status", "--porcelain"], cwd=repo)

def checkGitForCleanWorkTree(repo: Path) -> bool:
    """True iff WT and index match HEAD with no untracked files."""
    return getGitStatus(repo) == ""

def getGitCommitSubject(repo: Path, ref: str) -> str:
    """Subject line of the commit at <ref>."""
    return run(["git", "log", "-1", "--format=%s", ref], cwd=repo)

def getGitCommitTrailers(repo: Path, ref: str) -> dict[str, str]:
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


def gitResetHardToHead(repo: Path) -> None:
    """git reset --hard — restore tracked files to HEAD's state."""
    run(["git", "reset", QUIET_OUTPUT, "--hard"], cwd=repo)

def gitCleanWorkTree(repo: Path) -> None:
    """git clean -fd — delete untracked files and untracked directories.

    Ignored paths (e.g. anything matching .gitignore) are preserved
    because `git clean -fd` does NOT touch them without the `-x` flag.
    """
    run(["git", "clean", "-fd", QUIET_OUTPUT], cwd=repo)

def deleteGitBranchByForce(repo: Path, branchName: str) -> None:
    """git branch -D <name> — delete branch even if not merged."""
    run(["git", "branch", "-D", QUIET_OUTPUT, branchName], cwd=repo)

def saveChangesToGitPatch(
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

def makeTempGitIndexPath() -> str:
    fd, tmp_index_path = tempfile.mkstemp(prefix="plate-index-")
    os.close(fd)
    return tmp_index_path

def applyGitPatch(repo: Path, patch: Path) -> None:
    """Apply a saved .patch file via `git apply --3way <patch>`."""
    run(["git", "apply", "--3way", str(patch)], cwd=repo)


# ── git.sh parity helpers ─────────────────────────────────────────────
# These match the contracts of the legacy common/scripts/git.sh
# functions so the bash shim can delegate to them via git_cli.py.
class GitError(Exception):
    """Raised by git.sh-parity helpers to signal a contract failure.

    The bash shim maps GitError to exit-1 with the message on stderr,
    matching the behavior of the original bash functions.
    """


def getGitRepoRoot(path: Path) -> Path:
    """Absolute repo root containing <path>.

    Mirrors `git_get_repo_root` in git.sh: resolves --git-common-dir to
    the work tree's root. Raises GitError if <path> is not in a repo.
    """
    completed = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise GitError("[git] not inside a git repository")
    git_common_dir = completed.stdout.strip()
    # git_common_dir may be relative to <path>; resolve it the same way
    # the bash version does: cd <path> && cd $(dirname <git_common_dir>) && pwd.
    common = Path(git_common_dir)
    if not common.is_absolute():
        common = (path / common).resolve()
    return common.parent


def getGitBranchNameOrFail(path: Path) -> str:
    """Current branch name, or raise on detached HEAD / non-repo.

    Mirrors `git_get_branch_name` in git.sh exactly, including the
    detached-HEAD message format.
    """
    if not isGitRepo(path):
        raise GitError(f"[git] not a git repository: {path}")
    branch = run(["git", "-C", str(path), "branch", "--show-current"], cwd=path)
    if not branch:
        short_sha = run(
            ["git", "-C", str(path), "rev-parse", "--short", "HEAD"], cwd=path
        )
        raise GitError(f"HEAD detached at {short_sha}")
    return branch


def getGitRecentCommitHashes(path: Path, n: int = 5) -> list[str]:
    """Up to <n> most-recent commit short hashes, newest first.

    Mirrors `git_get_recent_commits` in git.sh. Raises GitError if
    <path> is not a repo or has no commits.
    """
    if not isGitRepo(path):
        raise GitError(f"[git] not a git repository: {path}")
    # `git log` on a repo with no commits exits 128 — handle without raising.
    completed = subprocess.run(
        ["git", "-C", str(path), "log", "--oneline", f"-{n}", "--format=%h"],
        capture_output=True,
        text=True,
        check=False,
    )
    out = (completed.stdout or "").strip()
    if completed.returncode != 0 or not out:
        raise GitError("No commits yet")
    return out.split()


def getGitUncommittedFilenames(path: Path) -> list[str]:
    """Filenames with uncommitted changes (modified, staged, untracked).

    Mirrors `git_get_uncommitted` in git.sh, which parses the second
    whitespace-delimited field of `git status --short`. Returns [] when
    the work tree is clean (the bash CLI shim translates that to 'None').
    Raises GitError if <path> is not a repo.
    """
    if not isGitRepo(path):
        raise GitError(f"[git] not a git repository: {path}")
    porcelain = run(["git", "-C", str(path), "status", "--short"], cwd=path)
    if not porcelain:
        return []
    files: list[str] = []
    for line in porcelain.splitlines():
        # git status --short lines: "XY filename" (X=index, Y=worktree).
        # The bash uses awk '{print $2}', which takes the 2nd whitespace
        # field — i.e. the filename, ignoring the XY status code.
        parts = line.split()
        if len(parts) >= 2:
            files.append(parts[1])
    return files


def ensureGitignoreEntry(repo_root: Path, pattern: str) -> None:
    """Idempotently append <pattern> as a line in <repo_root>/.gitignore.

    Mirrors `git_ensure_gitignore_entry` in git.sh: if <pattern> already
    appears as a complete line, no-op; otherwise append "\\n<pattern>\\n".
    Creates the file if missing.
    """
    gitignore = repo_root / ".gitignore"
    existing = gitignore.read_text() if gitignore.exists() else ""
    # Match the bash `grep -qxF` semantics: full-line, fixed-string match.
    if pattern in existing.splitlines():
        return
    with gitignore.open("a") as fh:
        fh.write(f"\n{pattern}\n")
