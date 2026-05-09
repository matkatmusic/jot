"""Shared git utilities used by /plate and other jot scripts.

Defines git CLI flag constants, test-config constants (USER_EMAIL_*,
USER_NAME_*), and the default GITIGNORE_CONTENTS string used by the
test harness. Generic helpers `run` and `currentTimestampMs` live in
`common.scripts.util_lib` — import them from there directly.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from common.scripts.util_lib import (
    run,
    currentTimestampMs,
)

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


# ── Git helpers ───────────────────────────────────────────────────────
def git_makeRepo(path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path.resolve()


def git_isRepo(path: Path) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0

def git_setUserConfigValue(repo: Path, config_key: str, config_value: str) -> None:
    run(["git", "config", config_key, config_value], cwd=repo)

def git_getUserConfigValue(repo: Path, config_key: str) -> str:
    return run(["git", "config", config_key], cwd=repo)

def git_writeGitignore(repo: Path, contents: str = GITIGNORE_CONTENTS) -> Path:
    """Write a .gitignore file at repo root and return its path.

    Default contents ignore the /plate skill's local stash directory
    (.plate/) so it is treated as ignored rather than untracked, which
    means `git clean -fd` won't blow it away (that requires `-x`).
    """
    path = repo / ".gitignore"
    path.write_text(contents)
    return path


def git_createUserConfig(repo: Path) -> None:
    git_setUserConfigValue(repo, USER_EMAIL_KEY, USER_EMAIL_VALUE)
    git_setUserConfigValue(repo, USER_NAME_KEY, USER_NAME_VALUE)

def git_getBranchList(repo: Path) -> list[str]:
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

def git_createBranch(repo: Path, branch_name: str) -> None:
    # git branch -q <branch-name>
    run(["git", "branch", QUIET_OUTPUT, branch_name], cwd=repo)

def git_checkOutBranch(repo: Path, branch_name: str) -> None:
    # git checkout -q <branch-name>
    run(["git", "checkout", QUIET_OUTPUT, branch_name], cwd=repo)

def git_createAndCheckoutBranch(repo: Path, branch_name: str) -> None:
    run(["git", "checkout", QUIET_OUTPUT, CREATE_BRANCH_AND_CHECKOUT_FLAG, branch_name], cwd=repo)

def git_getCurrentBranchName(repo: Path) -> str:
    """Return the current branch name (e.g. 'fix')."""
    # git branch --show-current
    return run(["git", "branch", "--show-current"], cwd=repo)

def git_getUntrackedFilesList(repo: Path) -> list[str]:
    # git ls-files --others --exclude-standard
    return run(["git", "ls-files", "--others", "--exclude-standard"], cwd=repo).splitlines()

def git_getUnstagedFilesList(repo: Path) -> list[str]:
    # git ls-files --modified
    return run(["git", "ls-files", "--modified"], cwd=repo).splitlines()

def git_getStagedFilesList(repo: Path) -> list[str]:
    # git diff --name-only --cached
    return run(["git", "diff", "--name-only", "--cached"], cwd=repo).splitlines()

def git_getTrackedFilesList(repo: Path) -> list[str]:
    return run(["git", "ls-files"], cwd=repo).splitlines()

def git_addFile(repo: Path, file: str) -> None:
    run(["git", "add", file], cwd=repo)


def git_stageAllChanges(repo: Path, env: dict[str, str] | None = None) -> None:
    run(["git", "add", "-A"], cwd=repo, env=env)

def git_stashFiles(repo: Path, files: list[str]) -> None:
    """Stash the named files (tracked or untracked) and remove them from WT.

    Uses `git stash push -u --` so that untracked files in <files> are
    included in the stash. After the call, the named files are gone from
    the WT and saved on the top of the stash stack (stash@{0}). Use
    git_unstashFiles() to restore them.
    """
    run(["git", "stash", "push", "-u", QUIET_OUTPUT, "--"] + files, cwd=repo)

def git_unstashFiles(repo: Path) -> None:
    """Pop the top of the stash stack back into the WT (stash@{0})."""
    run(["git", "stash", "pop", QUIET_OUTPUT], cwd=repo)

def git_addMultipleFiles(repo: Path, files: list[str]) -> None:
    run(["git", "add"] + files, cwd=repo)

def git_createCommit(repo: Path, message: str) -> None:
    run(["git", "commit", QUIET_OUTPUT, COMMIT_MESSAGE_FLAG, message], cwd=repo)

def git_checkIfBranchExists(repo: Path, branchName: str) -> bool:
    """True iff refs/heads/<branchName> exists, exact-match only.

    Uses `git show-ref --verify` against the fully qualified ref so that
    a query like "python-migration-plate" does NOT collide with an
    unrelated branch like "DNU-python-migration-plate". A prior impl
    scanned `git branch --list` output and substring-matched, which sent
    `_resolveTargetPlate` down the wrong code path and crashed
    `git rev-parse` (exit 128).
    """
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branchName}"],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0

def git_countCommitsReachableFromRef(repo: Path, ref: str) -> int:
    """Number of commits reachable from <ref>."""
    return int(run(["git", "rev-list", "--count", ref], cwd=repo))

def git_setIndexFileForEnv(env: dict[str, str], gitIndexFile: str) -> dict[str, str]:
    env["GIT_INDEX_FILE"] = gitIndexFile
    return env


def git_getSHAForRefViaRevParse(repo: Path, ref: str) -> str:
    return run(["git", "rev-parse", ref], cwd=repo)

def git_readTreeAt(repo: Path, ref: str, env: dict[str, str]) -> str:
    return run(["git", "read-tree", ref], cwd=repo, env=env)

def git_writeTree(repo: Path, env: dict[str, str]) -> str:
    return run(["git", "write-tree"], cwd=repo, env=env)

def git_getTreeRevOf(commit: str) -> str:
    """Return the git rev-spec that peels <commit> to its tree.
    The returned string is a rev-spec (e.g. 'abc1234^{tree}'), NOT a SHA.
    Pass it to git rev-parse — or any command taking a <rev> — to resolve it to the SHA of the commit's tree.
    """
    return f"{commit}^{{tree}}"

def git_getTreeSHA(repo: Path, ref: str) -> str:
    """SHA of the tree pointed to by <ref>."""
    return git_getSHAForRefViaRevParse(repo, git_getTreeRevOf(ref))

def git_getStatus(repo: Path) -> str:
    """Output of `git status --porcelain` (empty string when clean)."""
    return run(["git", "status", "--porcelain"], cwd=repo)

def git_checkForCleanWorkTree(repo: Path) -> bool:
    """True iff WT and index match HEAD with no untracked files."""
    return git_getStatus(repo) == ""

def git_getCommitSubject(repo: Path, ref: str) -> str:
    """Subject line of the commit at <ref>."""
    return run(["git", "log", "-1", "--format=%s", ref], cwd=repo)

def git_getCommitTrailers(repo: Path, ref: str) -> dict[str, str]:
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


def git_resetHardToHead(repo: Path) -> None:
    """git reset --hard — restore tracked files to HEAD's state."""
    run(["git", "reset", QUIET_OUTPUT, "--hard"], cwd=repo)

def git_cleanWorkTree(repo: Path) -> None:
    """git clean -fd — delete untracked files and untracked directories.

    Ignored paths (e.g. anything matching .gitignore) are preserved
    because `git clean -fd` does NOT touch them without the `-x` flag.
    """
    run(["git", "clean", "-fd", QUIET_OUTPUT], cwd=repo)

def git_deleteBranchByForce(repo: Path, branchName: str) -> None:
    """git branch -D <name> — delete branch even if not merged."""
    run(["git", "branch", "-D", QUIET_OUTPUT, branchName], cwd=repo)

def git_saveChangesToPatch(
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
    tmp_index_path = git_makeTempIndexPath()
    try:
        env = git_setIndexFileForEnv(env={}, gitIndexFile=tmp_index_path)
        git_readTreeAt(repo=repo, ref="HEAD", env=env)
        run(["git", "add"] + files, cwd=repo, env=env)
        snapshot_tree = git_writeTree(repo=repo, env=env)
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

def git_makeTempIndexPath() -> str:
    fd, tmp_index_path = tempfile.mkstemp(prefix="plate-index-")
    os.close(fd)
    return tmp_index_path

def git_applyPatch(repo: Path, patch: Path) -> None:
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


def git_getRepoRoot(path: Path) -> Path:
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


def git_getBranchNameOrFail(path: Path) -> str:
    """Current branch name, or raise on detached HEAD / non-repo.

    Mirrors `git_get_branch_name` in git.sh exactly, including the
    detached-HEAD message format.
    """
    if not git_isRepo(path):
        raise GitError(f"[git] not a git repository: {path}")
    branch = run(["git", "-C", str(path), "branch", "--show-current"], cwd=path)
    if not branch:
        short_sha = run(
            ["git", "-C", str(path), "rev-parse", "--short", "HEAD"], cwd=path
        )
        raise GitError(f"HEAD detached at {short_sha}")
    return branch


def git_getRecentCommitHashes(path: Path, n: int = 5) -> list[str]:
    """Up to <n> most-recent commit short hashes, newest first.

    Mirrors `git_get_recent_commits` in git.sh. Raises GitError if
    <path> is not a repo or has no commits.
    """
    if not git_isRepo(path):
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


def git_getUncommittedFilenames(path: Path) -> list[str]:
    """Filenames with uncommitted changes (modified, staged, untracked).

    Mirrors `git_get_uncommitted` in git.sh, which parses the second
    whitespace-delimited field of `git status --short`. Returns [] when
    the work tree is clean (the bash CLI shim translates that to 'None').
    Raises GitError if <path> is not a repo.
    """
    if not git_isRepo(path):
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


def git_ensureGitignoreEntry(repo_root: Path, pattern: str) -> None:
    """Idempotently ensure <pattern> appears as a line in <repo_root>/.gitignore.

    Creates the .gitignore file with `<pattern>\\n` when missing. When the
    file exists but lacks the pattern, appends `\\n<pattern>\\n`. When the
    pattern is already present as a full line, no-ops.
    """
    gitignore = repo_root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(f"{pattern}\n")
        return
    existing = gitignore.read_text()
    # Match the bash `grep -qxF` semantics: full-line, fixed-string match.
    if pattern in existing.splitlines():
        return
    with gitignore.open("a") as fh:
        fh.write(f"\n{pattern}\n")

# Resolve the git repo root for a given cwd via `git -C <cwd> rev-parse
# --show-toplevel`. Returns None when not inside a git checkout.
def _git_repoRoot(cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return out or None


# Resolves the git repo root for `cwd` via `git -C <cwd> rev-parse --show-toplevel`.
# Returns the path string on success, or "" on any failure (non-git dir, missing git).
def _git_get_repo_root(cwd: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


