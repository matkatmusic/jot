"""Shared helpers for the /plate sequence test harness.

Plate operations (all implemented):
    plate_push, plate_done, plate_drop, plate_trash, plate_recycle,
    plate_next, simulate_derived_agent, applyGitPatch

`plate_push` writes commit trailers — `parent-branch` always; `convo-id`,
`convo-name`, `convo-summary` when the matching kwarg is non-None.

Transcript helpers (read Claude Code JSONL session files):
    extractConvoNameFromTranscript, extractConvoCwdFromTranscript,
    localTranscriptIsReadable

Listing / formatting helpers:
    formatPlateAge, listPlateBranches

Repo / commit utilities:
    setup_repo, makeTestRepoWithSingleCommit, performRandomEdit,
    getCurrentGitBranchName, checkIfGitBranchExists, countGitCommitsReachableFromRef,
    getGitTreeSHA, getGitStatus, checkGitForCleanWorkTree, getGitCommitSubject,
    getGitCommitTrailers, saveChangesToGitPatch, gitResetHardToHead,
    gitCleanWorkTree, deleteGitBranchByForce, makeTempGitIndexPath, ...

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

# git_lib lives one level up at common/scripts/git_lib.py. Inject that
# directory on sys.path so `from git_lib import *` resolves whether
# plate_lib is imported via its package path or via direct sys.path
# injection by conftest.py / cli.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from git_lib import *  # noqa: E402,F401,F403  (re-export for tests + callers)
from git_lib import (  # noqa: E402  (explicit pulls so static checkers see them)
    QUIET_OUTPUT,
    COMMIT_MESSAGE_FLAG,
    CREATE_BRANCH_AND_CHECKOUT_FLAG,
    USER_EMAIL_KEY,
    USER_EMAIL_VALUE,
    USER_NAME_KEY,
    USER_NAME_VALUE,
    GITIGNORE_CONTENTS,
    run,
    currentTimestampMs,
    addFileToGit,
    checkGitForCleanWorkTree,
    checkIfGitBranchExists,
    createGitCommit,
    getCurrentGitBranchName,
    getGitCommitTrailers,
    getSHAForGitRefViaRevParse,
    gitResetHardToHead,
    countGitCommitsReachableFromRef,
)

# Test-compat aliases: pre-rename names still used by sequence tests.
# Map old git_lib names to current ones so test files do not need to be
# swept every time git_lib renames a helper.
from git_lib import (  # noqa: E402
    setGitUserConfigValue,
    getGitUserConfigValue,
    createGitUserConfig,
    createGitBranch,
    createAndCheckoutGitBranch,
    checkOutGitBranch,
    getGitTreeRevOf,
    getGitTreeSHA,
    getGitCommitSubject,
    gitCleanWorkTree,
    deleteGitBranchByForce,
    saveChangesToGitPatch,
    checkGitForCleanWorkTree,
    gitStashFiles,
    gitUnstashFiles,
    stageAllGitChanges,
    createGitCommit,
    getGitBranchList,
)

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

TEST_COMMIT_MESSAGE = "test commit"
TEST_FILENAME = "a.txt"



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


TEST_FILE_CONTENTS = "A\n"

def makeTestFile(repo: Path, fileName: str) -> Path:
    file = repo / fileName
    file.write_text(TEST_FILE_CONTENTS)
    return file

def random_string(length: int = 8, rng: random.Random = random) -> str:
    return "".join(rng.choices(string.ascii_lowercase, k=length))

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

B_FILENAME = "b.txt"
B_FILE_CONTENTS = "B\n"
F1_FILENAME = "fix.txt"
F1_FILE_CONTENTS = "F1\n"

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

# ── Implemented: assertion utilities ──────────────────────────────────

# ── Helpers used by the plate operations ─────────────────────────────

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
            "tip_sha": getSHAForGitRefViaRevParse(repo, name),
            "committer_unix": int(ts),
            "trailers": getGitCommitTrailers(repo, name),
        })
    plates.sort(key=lambda p: p["committer_unix"], reverse=True)
    return plates

# ── Stubs: plate operations ───────────────────────────────────────────
# Each stub raises NotImplementedError. Implementations should follow
# the canonical sequences locked in plate-walkthrough-log-2026-04-28.md.
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
    if not checkIfGitBranchExists(repo, plate_branch):
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
    if not checkIfGitBranchExists(repo, base_plate_name):
        return base_plate_name, getSHAForGitRefViaRevParse(repo, "HEAD")
    return base_plate_name, getSHAForGitRefViaRevParse(repo, base_plate_name)

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
        stageAllGitChanges(repo=repo, env=env)
        return writeGitTree(repo=repo, env=env)
    finally:
        Path(tmp_index_path).unlink(missing_ok=True)

def _buildExtractedTree(
    repo: Path,
    plate_branch: str,
    convo_id: str,
    parent_sha: str,
    transcript_path: Optional[str] = None,
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

    # In production cli.py passes a session UUID as `convo_id` and the
    # transcript path separately. Fall back to treating `convo_id` as a
    # path only when no `transcript_path` was supplied (legacy test
    # callers pass `convo_id=str(transcript_file)` directly).
    transcript_arg = Path(transcript_path) if transcript_path else Path(convo_id)
    edited_abs = extractFilesEditedSinceTimestamp(transcript_arg, since_iso=cutoff)
    deleted_candidates = extractFilesDeletedSinceTimestamp(
        transcript_arg, since_iso=cutoff, repo_root=repo
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

def _formatTrailerBody(text: str) -> str:
    """Format a long body for a multi-line git trailer value.

    Git trailers can span multiple lines if every line after the first
    starts with whitespace (RFC 822 / `git interpret-trailers`
    continuation rule). Indenting each continuation line with a single
    space preserves the original line breaks so multi-section bodies
    (e.g. the convo-summary's `what:` `why:` `how:` ... blocks) render
    each label on its own line when the user runs
    `git log -1 --format='%(trailers)'`.
    """
    raw = [line.rstrip() for line in text.splitlines()]
    raw = [line for line in raw if line.strip()]
    if not raw:
        return ""
    first = raw[0].lstrip()
    rest = [" " + line.lstrip() for line in raw[1:]]
    return "\n".join([first] + rest)

def plate_push(
    repo: Path,
    convo_id: Optional[str] = None,
    convo_name: Optional[str] = None,
    convo_summary: Optional[str] = None,
    transcript_path: Optional[str] = None,
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
        parent-branch: <branch>     # auto-derived from getCurrentGitBranchName

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
    branch = getCurrentGitBranchName(repo)
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
        and checkIfGitBranchExists(repo, base_plate_name)
        and getGitCommitTrailers(repo, base_plate_name).get("convo-id") not in (None, convo_id)
    )

    if use_extraction:
        commit_tree = _buildExtractedTree(
            repo, base_plate_name, convo_id, parent,
            transcript_path=transcript_path,
        )
    else:
        commit_tree = _buildFullWtTree(repo)

    parent_tree = getSHAForGitRefViaRevParse(repo=repo, ref=getGitTreeRevOf(parent))
    if commit_tree == parent_tree:
        return None
    wt_tree = commit_tree

    trailerLines = [f"parent-branch: {branch}"]
    if convo_id is not None:
        trailerLines.append(f"convo-id: {convo_id}")
    if convo_name is not None:
        trailerLines.append(f"convo-name: {convo_name}")
    if convo_summary is not None:
        trailerLines.append(f"convo-summary: {_formatTrailerBody(convo_summary)}")

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

def plate_done(repo: Path, branch: Optional[str] = None) -> None:
    """Run the canonical /plate --done.

    Pure replay: never writes plate commits. The caller must `/plate` any
    uncommitted WT work first; otherwise plate_done aborts with a warning.

    Sequence:
        Step 1  abort if `<branch>-plate` does not exist
        Step 2  abort if WT-tree (incl. untracked) != plate-tip-tree
        Step 3  snapshot HEAD, git reset --hard, git clean -fd
        Step 4  git cherry-pick HEAD..<branch>-plate -X theirs --allow-empty
        Step 5  git branch -D <branch>-plate

    Args:
        branch: working branch name; defaults to current.
    """
    if branch is None:
        branch = getCurrentGitBranchName(repo)
    plateBranchName = f"{branch}-plate"

    # Step 1: existence check. No plate branch -> nothing to replay.
    if not checkIfGitBranchExists(repo, plateBranchName):
        print(
            f"warning: no plate branch '{plateBranchName}' - nothing to do",
            file=sys.stderr,
        )
        return

    # Step 2: WT must match plate tip exactly. plate_done does not auto-plate;
    # any WT divergence (uncommitted edits OR a stale checkout) is the user's
    # signal to run /plate first. Tree-SHA equality is byte-identical content
    # equality (git tree objects are content-addressed).
    wt_tree = _buildFullWtTree(repo)
    plate_tip_tree = getGitTreeSHA(repo, plateBranchName)
    if wt_tree != plate_tip_tree:
        print(
            f"warning: working tree differs from '{plateBranchName}' tip - "
            f"run /plate to capture changes, then retry --done",
            file=sys.stderr,
        )
        return

    # Snapshot pre-call state so we can roll back on cherry-pick conflict.
    preHeadSha = getSHAForGitRefViaRevParse(repo, "HEAD")

    # Step 1: clean WT.
    gitResetHardToHead(repo)
    gitCleanWorkTree(repo)

    # Step 2: cherry-pick HEAD..<branch>-plate (oldest first).
    # -X theirs: plate tip is the verified working state; on any content
    # conflict with the parent branch, plate's content is the answer.
    # --allow-empty: permit deliberately-empty plate marker commits.
    completed = subprocess.run(
        [
            "git", "cherry-pick",
            "-X", "theirs",
            "--allow-empty",
            f"HEAD..{plateBranchName}",
        ],
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
        gitCleanWorkTree(repo)
        print(
            f"warning: cherry-pick conflict during plate_done; "
            f"aborted and restored HEAD to {preHeadSha}. "
            f"Plate branch '{plateBranchName}' preserved.",
            file=sys.stderr,
        )
        return

    # Step 3: delete the plate branch.
    deleteGitBranchByForce(repo, plateBranchName)

def currentTimestampUtcCompact() -> str:
    """UTC ISO8601-compact timestamp for trash session-dir naming.

    Format: YYYYMMDDTHHMMSSZ (lex-sortable → chronological).
    """
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _trashBranchDir(repo: Path, branch: str) -> Path:
    """Per-branch container under .plate/trash/ that holds session dirs."""
    return repo / ".plate" / "trash" / branch


def _writeTrashSession(
    repo: Path,
    branch: str,
    action: str,
    tip_sha: str,
    parent_sha: str,
    patches: list[tuple[str, str]],
    extra_trailers: Optional[list[dict]] = None,
) -> Path:
    """Materialise a unified-layout trash session directory.

    Layout:
        <repo>/.plate/trash/<branch>/<ts>_<action>_<short-sha>/
            info.json
            plate_001.patch
            plate_002.patch
            ...
    """
    ts = currentTimestampUtcCompact()
    short_sha = tip_sha[:7] if tip_sha else "0000000"
    session_dir = _trashBranchDir(repo, branch) / f"{ts}_{action}_{short_sha}"
    session_dir.mkdir(parents=True, exist_ok=False)

    for filename, patch_text in patches:
        (session_dir / filename).write_text(patch_text + "\n")

    info = {
        "branch": branch,
        "action": action,
        "saved_at": ts,
        "tip_sha_at_save": tip_sha,
        "parent_sha_at_save": parent_sha,
        "trailers": extra_trailers or [],
    }
    (session_dir / "info.json").write_text(json.dumps(info, indent=2))
    return session_dir


def _listTrashSessions(repo: Path, branch: str) -> list[Path]:
    """Lex-sorted list of session dirs under .plate/trash/<branch>/."""
    branch_dir = _trashBranchDir(repo, branch)
    if not branch_dir.is_dir():
        return []
    return sorted(d for d in branch_dir.iterdir() if d.is_dir())


def plate_drop(repo: Path, branch: Optional[str] = None) -> Optional[Path]:
    """Pop the top plate from ``<branch>-plate``, save as a unified trash session.

    Sequence:
        - Capture the popped tip's per-commit diff
          (``git diff --binary <tip>~1 <tip>``) as ``plate_001.patch``
          inside ``<repo>/.plate/trash/<branch>/<ts>_dropped_<sha>/``.
        - Write an ``info.json`` recording the tip and parent SHAs plus
          the tip's commit trailers.
        - Rewind ``<branch>-plate`` to ``<branch>-plate~1`` (or
          ``git branch -D`` if the last plate).
        - WT untouched.

    Returns:
        Path to the new session directory, or ``None`` when no plate
        branch exists (warning printed to stderr).
    """
    if branch is None:
        branch = getCurrentGitBranchName(repo)
    plateBranchName = f"{branch}-plate"

    if not checkIfGitBranchExists(repo, plateBranchName):
        print(
            f"warning: no plate branch '{plateBranchName}' - nothing to drop",
            file=sys.stderr,
        )
        return None

    tip_sha = getSHAForGitRefViaRevParse(repo, plateBranchName)
    parent_sha = run(["git", "rev-parse", f"{plateBranchName}~1"], cwd=repo)

    patch_text = run(
        ["git", "diff", "--binary", parent_sha, tip_sha],
        cwd=repo,
    )

    session_dir = _writeTrashSession(
        repo=repo,
        branch=branch,
        action="dropped",
        tip_sha=tip_sha,
        parent_sha=parent_sha,
        patches=[("plate_001.patch", patch_text)],
        extra_trailers=[getGitCommitTrailers(repo, tip_sha)],
    )

    plateCount = int(run(
        ["git", "rev-list", "--count", f"{branch}..{plateBranchName}"],
        cwd=repo,
    ))
    if plateCount == 1:
        deleteGitBranchByForce(repo, plateBranchName)
    else:
        run(["git", "update-ref", f"refs/heads/{plateBranchName}", parent_sha], cwd=repo)

    return session_dir


def plate_trash(
    repo: Path,
    branch: Optional[str] = None,
    clean_wt: bool = False,
) -> Optional[Path]:
    """Delete <branch>-plate entirely, save the whole stack as a unified trash session.

    Args:
        branch: working branch name; defaults to current.
        clean_wt: if True, run git reset --hard + git clean -fd after
                  writing the patches.

    Returns:
        Path to the unified trash session directory
        (.plate/trash/<branch>/<ts>_trashed_<sha>/), or None when no plate
        branch exists (warning printed to stderr).
    """
    if branch is None:
        branch = getCurrentGitBranchName(repo)
    plateBranchName = f"{branch}-plate"

    if not checkIfGitBranchExists(repo, plateBranchName):
        print(
            f"warning: no plate branch '{plateBranchName}' - nothing to trash",
            file=sys.stderr,
        )
        return None

    plates = run(
        ["git", "rev-list", "--reverse", f"{branch}..{plateBranchName}"],
        cwd=repo,
    ).splitlines()

    tip_sha = plates[-1]
    bottom_parent = run(["git", "rev-parse", f"{plates[0]}~1"], cwd=repo)

    patches: list[tuple[str, str]] = []
    trailer_records: list[dict] = []
    for i, plate_sha in enumerate(plates, start=1):
        patch_text = run(
            ["git", "diff", "--binary", f"{plate_sha}~1", plate_sha],
            cwd=repo,
        )
        patches.append((f"plate_{i:03d}.patch", patch_text))
        trailer_records.append(getGitCommitTrailers(repo, plate_sha))

    session_dir = _writeTrashSession(
        repo=repo,
        branch=branch,
        action="trashed",
        tip_sha=tip_sha,
        parent_sha=bottom_parent,
        patches=patches,
        extra_trailers=trailer_records,
    )

    deleteGitBranchByForce(repo, plateBranchName)

    if clean_wt:
        gitResetHardToHead(repo)
        gitCleanWorkTree(repo)

    return session_dir


def plate_recycle_list(repo: Path, branch: Optional[str] = None) -> str:
    """Human-readable enumeration of recyclable trash sessions.

    Read-only - no mutation. Empty result yields a friendly empty-list
    message rather than an error.
    """
    if branch is None:
        branch = getCurrentGitBranchName(repo)
    sessions = _listTrashSessions(repo, branch)
    if not sessions:
        return f"plate: no trash sessions for '{branch}'"
    lines = [f"trash sessions for '{branch}' (newest last):"]
    for d in sessions:
        info_path = d / "info.json"
        try:
            info = json.loads(info_path.read_text())
            action = info.get("action", "?")
            saved_at = info.get("saved_at", "?")
            tip = (info.get("tip_sha_at_save") or "")[:8]
            lines.append(f"  {d.name}  ({action}, saved {saved_at}, tip {tip})")
        except (OSError, ValueError):
            lines.append(f"  {d.name}  (info.json unreadable)")
    return "\n".join(lines)


def stripConvoSummaryFromCommit(
    repo: Path, branch: str, target_ref: str,
) -> str:
    """Remove the convo-summary trailer from a commit on <branch>-plate.

    Rewrites the targeted commit (preserving every other trailer + the
    tree + the parent) and any descendants on <branch>-plate so the
    branch chain stays linear. Updates refs/heads/<branch>-plate to the
    new tip SHA and returns it.

    Implementation: pure `git commit-tree` — no worktree, no rebase, no
    interactive editor.
    """
    plate_branch = f"{branch}-plate"
    target_sha = run(["git", "rev-parse", target_ref], cwd=repo)
    tip_sha = run(["git", "rev-parse", plate_branch], cwd=repo)

    target_msg = run(
        ["git", "log", "-1", "--format=%B", target_sha], cwd=repo,
    )
    target_tree = run(
        ["git", "rev-parse", f"{target_sha}^{{tree}}"], cwd=repo,
    )
    target_parent = run(
        ["git", "rev-parse", f"{target_sha}~1"], cwd=repo,
    )

    new_target_msg = _stripSummaryTrailerFromMessage(target_msg)
    new_target_sha = run(
        [
            "git", "commit-tree", target_tree,
            "-p", target_parent,
            COMMIT_MESSAGE_FLAG, new_target_msg,
        ],
        cwd=repo,
    )

    # Re-emit each descendant chained off the rewritten target.
    descendants = run(
        ["git", "rev-list", "--reverse", f"{target_sha}..{tip_sha}"],
        cwd=repo,
    ).splitlines()
    prev_sha = new_target_sha
    for desc_sha in descendants:
        if not desc_sha:
            continue
        desc_msg = run(
            ["git", "log", "-1", "--format=%B", desc_sha], cwd=repo,
        )
        desc_tree = run(
            ["git", "rev-parse", f"{desc_sha}^{{tree}}"], cwd=repo,
        )
        prev_sha = run(
            [
                "git", "commit-tree", desc_tree,
                "-p", prev_sha,
                COMMIT_MESSAGE_FLAG, desc_msg,
            ],
            cwd=repo,
        )

    run(
        ["git", "update-ref", f"refs/heads/{plate_branch}", prev_sha],
        cwd=repo,
    )
    return prev_sha


def regenerateTipSummary(
    repo: Path,
    branch: str,
    prior_summary: str,
    agent_callable,
) -> str:
    """Regenerate the tip's convo-summary trailer.

    Calls `agent_callable(prior_summary)` to produce the new summary
    payload (in production the callable spawns a real claude; in tests
    it's a deterministic mock). Payload format:
        Line 1: subject (≤50 chars; replaces the tip's commit subject)
        Line 2: blank
        Lines 3+: 5-section body (becomes the convo-summary trailer)

    Single-line payloads (no blank-line separator) are treated as
    pure trailer body — the commit subject is left untouched.

    Updates `refs/heads/<branch>-plate` to a new tip whose message has
    the new subject (when present) AND the convo-summary trailer.
    Returns the new tip SHA.
    """
    new_payload = agent_callable(prior_summary)
    subject, body = _parseAgentPayload(new_payload)
    # When the payload has no body (no blank-line separator), treat the
    # whole text as body so simple `prior -> "..."` callables in tests
    # still land a trailer. Production payloads always have a body.
    trailer_body = body if body else subject
    if not body:
        subject = ""  # nothing to replace the commit subject with

    plate_branch = f"{branch}-plate"
    tip_sha = run(["git", "rev-parse", plate_branch], cwd=repo)
    tip_msg = run(["git", "log", "-1", "--format=%B", tip_sha], cwd=repo)
    tip_tree = run(["git", "rev-parse", f"{tip_sha}^{{tree}}"], cwd=repo)
    tip_parent = run(["git", "rev-parse", f"{tip_sha}~1"], cwd=repo)

    # Strip any pre-existing convo-summary first so we never duplicate.
    cleaned = _stripSummaryTrailerFromMessage(tip_msg)
    if subject:
        cleaned = _replaceCommitSubject(cleaned, subject)
    new_msg = _appendSummaryTrailerToMessage(cleaned, trailer_body)

    new_tip_sha = run(
        [
            "git", "commit-tree", tip_tree,
            "-p", tip_parent,
            COMMIT_MESSAGE_FLAG, new_msg,
        ],
        cwd=repo,
    )
    run(
        ["git", "update-ref", f"refs/heads/{plate_branch}", new_tip_sha],
        cwd=repo,
    )
    return new_tip_sha


def plate_recycle(
    repo: Path,
    branch: Optional[str] = None,
    session: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> Optional[str]:
    """Replay a unified trash session into a fresh <branch>-plate.

    Re-parents the restored plate at info.json's parent_sha_at_save (NOT
    HEAD at recycle time). Errors out without mutating when the saved
    parent SHA is no longer in the object DB.

    Args:
        branch:    working branch name; defaults to current.
        session:   exact session-dir name; defaults to newest session.
        timestamp: legacy alias accepted for back-compat; treated as a
                   session-dir suffix match.

    Returns:
        SHA of the recycled <branch>-plate tip, or None when no trashed
        session exists for the branch (warning printed to stderr).
    """
    if branch is None:
        branch = getCurrentGitBranchName(repo)
    plateBranchName = f"{branch}-plate"

    sessions = _listTrashSessions(repo, branch)
    if not sessions:
        print(
            f"warning: no trashed plate '{plateBranchName}' - nothing to recycle",
            file=sys.stderr,
        )
        return None

    if session is not None:
        chosen = next((d for d in sessions if d.name == session), None)
        if chosen is None:
            print(
                f"warning: session '{session}' not found under '{branch}'",
                file=sys.stderr,
            )
            return None
    elif timestamp is not None:
        chosen = next(
            (d for d in sessions if d.name.endswith(f"_{timestamp}")),
            None,
        )
        if chosen is None:
            print(
                f"warning: no session with timestamp '{timestamp}' for '{branch}'",
                file=sys.stderr,
            )
            return None
    else:
        chosen = sessions[-1]

    info_path = chosen / "info.json"
    try:
        info = json.loads(info_path.read_text())
    except (OSError, ValueError) as exc:
        print(
            f"warning: cannot read {info_path} ({exc}); refusing to recycle",
            file=sys.stderr,
        )
        return None

    parent_sha = info.get("parent_sha_at_save")
    if not parent_sha:
        print(
            f"warning: {info_path} missing parent_sha_at_save; refusing to recycle",
            file=sys.stderr,
        )
        return None

    # Verify the saved parent SHA still exists BEFORE mutating anything.
    try:
        run(["git", "cat-file", "-e", parent_sha], cwd=repo)
    except Exception:
        print(
            f"warning: parent SHA {parent_sha[:8]} no longer in repo; "
            f"cannot recycle '{chosen.name}'",
            file=sys.stderr,
        )
        return None

    # Re-parent the plate ref at the saved parent SHA.
    if checkIfGitBranchExists(repo, plateBranchName):
        deleteGitBranchByForce(repo, plateBranchName)
    run(["git", "update-ref", f"refs/heads/{plateBranchName}", parent_sha], cwd=repo)

    # Apply each saved patch in order; plate_push commits the result.
    patches = sorted(p for p in chosen.iterdir() if p.suffix == ".patch")
    for patch in patches:
        applyGitPatch(repo, patch)
        plate_push(repo)

    return getSHAForGitRefViaRevParse(repo, plateBranchName)

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

def _plate_next_list(repo: Path, plates: list[dict]) -> str:
    """Format the plate list per the canonical example in the plan."""
    if not plates:
        return PLATE_NEXT_EMPTY_LIST_MESSAGE
    branch = getCurrentGitBranchName(repo)
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
    branch = getCurrentGitBranchName(repo)
    currentPlateRef = f"{branch}-plate"
    if target["ref"] == currentPlateRef:
        title = _resolvePlateTitle(target)
        return f"already on plate '{title}'; worktree unchanged"

    # 1. Capture current WIP into the current-branch plate (no-op when clean).
    plate_push(repo)
    # 2. Clear WIP so the upcoming checkout doesn't conflict.
    gitResetHardToHead(repo)
    gitCleanWorkTree(repo)
    # 3. Check out the target's parent branch.
    parent_branch = target["trailers"].get("parent-branch")
    if not parent_branch or not checkIfGitBranchExists(repo, parent_branch):
        return PLATE_NEXT_LOST_MESSAGE
    checkOutGitBranch(repo, parent_branch)
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
        parentConvo = getGitCommitTrailers(repo, baseBranch)["convo-id"]

    newBranchName = f"{parent_plate}-derived{N+1}"
    parentSHA = getSHAForGitRefViaRevParse(repo, baseBranch)
    parentTree = getGitTreeSHA(repo, baseBranch)

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

# ── plate_next scenarios ─────────────────────────────────────────────

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
    sha_A = getSHAForGitRefViaRevParse(repo, "main")
    (repo / TEST_FILENAME).write_text("A\nB-line\n")
    addFileToGit(repo, TEST_FILENAME)
    createGitCommit(repo, "B")
    sha_B = getSHAForGitRefViaRevParse(repo, "main")
    (repo / TEST_FILENAME).write_text("A\nB-line\nC-line\n")
    addFileToGit(repo, TEST_FILENAME)
    createGitCommit(repo, "C")
    sha_C = getSHAForGitRefViaRevParse(repo, "main")

    # fix-y branches off main at B with three working commits B1, B2, B3.
    run(["git", "checkout", QUIET_OUTPUT, CREATE_BRANCH_AND_CHECKOUT_FLAG, "fix-y", sha_B], cwd=repo)
    (repo / "fix.txt").write_text("B1 fix\n")
    addFileToGit(repo, "fix.txt")
    createGitCommit(repo, "B1")
    sha_B1 = getSHAForGitRefViaRevParse(repo, "fix-y")
    (repo / "fix.txt").write_text("B1 fix\nB2 polish\n")
    addFileToGit(repo, "fix.txt")
    createGitCommit(repo, "B2")
    (repo / "fix.txt").write_text("B1 fix\nB2 polish\nB3 cleanup\n")
    addFileToGit(repo, "fix.txt")
    createGitCommit(repo, "B3")
    sha_B3 = getSHAForGitRefViaRevParse(repo, "fix-y")

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
    sha_Pb3 = getSHAForGitRefViaRevParse(repo, "fix-y-plate")

    # Restore fix-y's working tip back to B3 (its real, post-investigation state).
    # `git reset --hard` preserves untracked files, so investigation.txt would
    # otherwise leak across branch switches. Clean it out so subsequent
    # plate_push calls don't accidentally capture it.
    run(["git", "reset", QUIET_OUTPUT, "--hard", sha_B3], cwd=repo)
    gitCleanWorkTree(repo)

    # feature-x branches off main at C with two working commits.
    checkOutGitBranch(repo, "main")
    run(["git", "checkout", QUIET_OUTPUT, CREATE_BRANCH_AND_CHECKOUT_FLAG, "feature-x", sha_C], cwd=repo)
    (repo / "feature.txt").write_text("C1 work\n")
    addFileToGit(repo, "feature.txt")
    createGitCommit(repo, "C1")
    (repo / "feature.txt").write_text("C1 work\nC2 polish\n")
    addFileToGit(repo, "feature.txt")
    createGitCommit(repo, "C2")
    sha_C2 = getSHAForGitRefViaRevParse(repo, "feature-x")

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
    sha_Pa2 = getSHAForGitRefViaRevParse(repo, "feature-x-plate")

    # Reset WT clean on feature-x.
    gitResetHardToHead(repo)

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

# ──────────────────────────────────────────────────────────────────────
# rewriteBranchTipSummary — strip convo-summary trailer from older plate
# commits and add (or replace) it on the new tip. Uses `git rebase -i
# --reword` driven by the dual-role editor at
# common/scripts/plate/_rebase_reword_summary.py.
# ──────────────────────────────────────────────────────────────────────

_REBASE_EDITOR_SCRIPT = (
    Path(__file__).resolve().parent / "_rebase_reword_summary.py"
)

# Reuse the trailer-manipulation helpers from the dual-role editor
# script. Importing as a sibling module is safe — that script's
# top-level only defines functions and is `if __name__ == "__main__"`
# guarded.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rebase_reword_summary import (  # noqa: E402
    _strip_summary_trailer as _stripSummaryTrailerFromMessage,
    _append_summary_trailer as _appendSummaryTrailerToMessage,
    _parse_payload as _parseAgentPayload,
    _replace_subject as _replaceCommitSubject,
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
    if not checkIfGitBranchExists(repo, plate_branch):
        raise RuntimeError(f"plate branch does not exist: {plate_branch}")

    parent_sha = run(["git", "merge-base", plate_branch, branch], cwd=repo)
    tip_sha = getSHAForGitRefViaRevParse(repo, plate_branch)
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


