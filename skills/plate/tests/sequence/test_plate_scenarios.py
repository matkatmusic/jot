"""Cross-fixture scenario helpers for the /plate test suite.

Each `_check_*` function asserts a single workflow contract. Both the
per-function tests (against git_test_makeRepoWithSingleCommit) and the
sequence tests in test_helpers.py (against git_test_setup_repo) call these to
verify the same workflow under different topologies. Scenarios MUST
avoid fixture-specific assumptions (no hardcoded branch names, no
exact-equality checks on tracked-file lists).
"""
from __future__ import annotations

import random
import shutil
import time
from pathlib import Path

# conftest.py adds common/scripts to sys.path. plate_lib re-exports git_lib
# via `from git_lib import *`, so importing * here pulls in every helper
# (run, git_addFile, git_getCurrentBranchName, plate_push, …) that the
# scenarios reference below.
from plate.plate_lib import *  # noqa: F401,F403

# Underscore-prefixed helpers are not pulled in by `import *`. Import them
# explicitly so the scenarios that build complex topologies can call them.
from plate.plate_lib import (  # noqa: F401
    _plate_writeTranscriptFile,
    _plate_buildTwoBranchPlateTopology,
)


def _check_plate_push_creates_branch_capturing_wip(repo: Path) -> None:
    """Scenario: tracked edit + untracked file → plate_push creates the plate
    branch parented to HEAD, captures both edits, and leaves WT/HEAD/branch
    untouched."""
    branch = git_getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    head_before = git_getSHAForRefViaRevParse(repo, "HEAD")
    assert not git_checkIfBranchExists(repo, plateBranchName)

    (repo / TEST_FILENAME).write_text("modified\n")
    untracked = git_test_createUntrackedFile(repo, random.Random())["file"]

    sha = plate_push(repo)

    # Plate branch created and parented to HEAD.
    assert sha is not None
    assert git_checkIfBranchExists(repo, plateBranchName)
    assert git_getSHAForRefViaRevParse(repo, plateBranchName) == sha
    assert run(["git", "rev-parse", f"{plateBranchName}~1"], cwd=repo) == head_before
    # Both edits captured in the plate tree.
    plate_files = run(
        ["git", "ls-tree", "-r", "--name-only", plateBranchName], cwd=repo
    ).splitlines()
    assert TEST_FILENAME in plate_files
    assert untracked in plate_files
    # WT, HEAD, and current branch unchanged.
    assert git_getCurrentBranchName(repo) == branch
    assert git_getSHAForRefViaRevParse(repo, "HEAD") == head_before
    assert (repo / TEST_FILENAME).read_text() == "modified\n"
    assert untracked in git_getUntrackedFilesList(repo)

def _check_plate_done_replays_stack(repo: Path) -> None:
    """Scenario: 2-plate stack → plate_done cherry-picks both onto branch
    oldest-first, deletes plate ref, leaves WT clean and tree == former plate tip."""
    branch = git_getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    branch_count_before = git_countCommitsReachableFromRef(repo, branch)

    rng = random.Random()
    u1 = git_test_createUntrackedFile(repo, rng)["file"]
    plate_push(repo)
    u2 = git_test_createUntrackedFile(repo, rng)["file"]
    plate_push(repo)
    plate_tip_tree = git_getTreeSHA(repo, plateBranchName)

    plate_done(repo)

    assert not git_checkIfBranchExists(repo, plateBranchName)
    assert git_countCommitsReachableFromRef(repo, branch) == branch_count_before + 2
    assert git_checkForCleanWorkTree(repo)
    assert git_getTreeSHA(repo, branch) == plate_tip_tree
    tracked = git_getTrackedFilesList(repo)
    assert u1 in tracked
    assert u2 in tracked

def _check_plate_drop_deletes_last_plate(repo: Path) -> None:
    """Scenario: single plate → plate_drop saves a unified trash session under
    .plate/trash/<branch>/, deletes the plate ref, leaves WT untouched."""
    branch = git_getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    untracked = git_test_createUntrackedFile(repo, random.Random())["file"]
    plate_push(repo)
    assert git_checkIfBranchExists(repo, plateBranchName)

    session_dir = plate_drop(repo)

    assert session_dir is not None
    assert session_dir.is_dir()
    assert session_dir.parent.name == branch
    assert session_dir.parent.parent.name == "trash"
    assert "_dropped_" in session_dir.name
    patch_path = session_dir / "plate_001.patch"
    assert patch_path.exists()
    assert untracked in patch_path.read_text()
    assert not git_checkIfBranchExists(repo, plateBranchName)
    assert untracked in git_getUntrackedFilesList(repo)

def _check_plate_drop_then_applyGitPatch_round_trip(repo: Path) -> None:
    """Scenario: single plate → plate_drop + reset WT + git_applyPatch restores
    the dropped work to the WT byte-for-byte."""
    untracked = git_test_createUntrackedFile(repo, random.Random())["file"]
    untracked_content = (repo / untracked).read_text()
    plate_push(repo)

    session_dir = plate_drop(repo)
    patch_path = session_dir / "plate_001.patch"

    # Reset WT to clean state (drop's contract leaves the file in WT;
    # delete it explicitly so git_applyPatch's restoration is visible).
    (repo / untracked).unlink()
    assert not (repo / untracked).exists()

    git_applyPatch(repo, patch_path)

    assert (repo / untracked).exists()
    assert (repo / untracked).read_text() == untracked_content

def _check_plate_trash_default_preserves_wt(repo: Path) -> None:
    """Scenario: 2-plate stack → plate_trash (default clean_wt=False) saves
    per-plate patches under a unified trash session, deletes plate ref,
    leaves WT untouched."""
    branch = git_getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    rng = random.Random()
    u1 = git_test_createUntrackedFile(repo, rng)["file"]
    plate_push(repo)
    u2 = git_test_createUntrackedFile(repo, rng)["file"]
    plate_push(repo)

    session_dir = plate_trash(repo)

    assert session_dir.is_dir()
    assert session_dir.parent.name == branch
    assert session_dir.parent.parent.name == "trash"
    assert "_trashed_" in session_dir.name
    patches = sorted(p for p in session_dir.iterdir() if p.suffix == ".patch")
    assert len(patches) == 2
    assert (session_dir / "info.json").exists()
    assert not git_checkIfBranchExists(repo, plateBranchName)
    untracked = git_getUntrackedFilesList(repo)
    assert u1 in untracked
    assert u2 in untracked

def _check_plate_trash_clean_resets_wt(repo: Path) -> None:
    """Scenario: dirty 2-plate stack → plate_trash(clean_wt=True) saves
    patches, deletes plate ref, AND wipes WT (tracked restored, untracked
    removed)."""
    branch = git_getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    branch_tip_before = git_getSHAForRefViaRevParse(repo, branch)
    tracked_before = (repo / TEST_FILENAME).read_text()

    rng = random.Random()
    (repo / TEST_FILENAME).write_text("modified\n")
    u1 = git_test_createUntrackedFile(repo, rng)["file"]
    plate_push(repo)
    u2 = git_test_createUntrackedFile(repo, rng)["file"]
    plate_push(repo)

    session_dir = plate_trash(repo, clean_wt=True)

    assert session_dir.is_dir()
    patches = sorted(p for p in session_dir.iterdir() if p.suffix == ".patch")
    assert len(patches) == 2
    assert not git_checkIfBranchExists(repo, plateBranchName)
    # WT wiped.
    assert (repo / TEST_FILENAME).read_text() == tracked_before
    assert not (repo / u1).exists()
    assert not (repo / u2).exists()
    # Branch HEAD untouched.
    assert git_getSHAForRefViaRevParse(repo, branch) == branch_tip_before

def _check_plate_recycle_restores_stack(repo: Path) -> None:
    """Scenario: 2-plate stack → trash → recycle restores plate branch with
    same commit count and same tip tree SHA; branch HEAD unchanged."""
    branch = git_getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    branch_tip_before = git_getSHAForRefViaRevParse(repo, branch)

    rng = random.Random()
    u1 = git_test_createUntrackedFile(repo, rng)["file"]
    plate_push(repo)
    u2 = git_test_createUntrackedFile(repo, rng)["file"]
    plate_push(repo)
    plate_count_before = git_countCommitsReachableFromRef(repo, plateBranchName)
    plate_tip_tree_before = git_getTreeSHA(repo, plateBranchName)

    plate_trash(repo)
    # Clean WT before recycle so git_applyPatch doesn't conflict on existing files.
    (repo / u1).unlink()
    (repo / u2).unlink()

    recycled_sha = plate_recycle(repo)

    assert git_checkIfBranchExists(repo, plateBranchName)
    assert git_countCommitsReachableFromRef(repo, plateBranchName) == plate_count_before
    assert git_getTreeSHA(repo, plateBranchName) == plate_tip_tree_before
    assert git_getSHAForRefViaRevParse(repo, plateBranchName) == recycled_sha
    assert git_getSHAForRefViaRevParse(repo, branch) == branch_tip_before

def _check_first_derived_agent_records_trailers(repo: Path) -> None:
    """Scenario: parent plate exists → plate_simulate_derived_agent creates
    `<parent_plate>-derived1` parented to plate tip with trailers
    parent-plate=<plate tip SHA> and convo-id=<convo_id>."""
    branch = git_getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    (repo / TEST_FILENAME).write_text("modified\n")
    plate_push(repo)
    parent_plate_sha = git_getSHAForRefViaRevParse(repo, plateBranchName)

    derived = plate_simulate_derived_agent(repo, plateBranchName, "CONVO-A")

    assert derived == f"{plateBranchName}-derived1"
    assert git_checkIfBranchExists(repo, derived)
    assert run(["git", "rev-parse", f"{derived}~1"], cwd=repo) == parent_plate_sha
    trailers = git_getCommitTrailers(repo, derived)
    assert trailers["parent-plate"] == parent_plate_sha
    assert trailers["convo-id"] == "CONVO-A"

def _check_second_derived_agent_extends_chain(repo: Path) -> None:
    """Scenario: parent plate + derived1 exist → plate_simulate_derived_agent
    creates `<parent_plate>-derived2` parented to derived1's tip, with
    parent-convo trailer = derived1's convo-id."""
    branch = git_getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    (repo / TEST_FILENAME).write_text("modified\n")
    plate_push(repo)

    derived1 = plate_simulate_derived_agent(repo, plateBranchName, "CONVO-A")
    derived1_tip = git_getSHAForRefViaRevParse(repo, derived1)

    derived2 = plate_simulate_derived_agent(repo, plateBranchName, "CONVO-B")

    assert derived2 == f"{plateBranchName}-derived2"
    assert git_checkIfBranchExists(repo, derived2)
    assert run(["git", "rev-parse", f"{derived2}~1"], cwd=repo) == derived1_tip
    trailers = git_getCommitTrailers(repo, derived2)
    assert trailers["parent-convo"] == "CONVO-A"
    assert trailers["convo-id"] == "CONVO-B"
    # derived1 untouched.
    assert git_getSHAForRefViaRevParse(repo, derived1) == derived1_tip

# ── Error-path scenarios ─────────────────────────────────────────────
# Scenarios for the 5 untested error paths from PLATE STATE.md §C:
#   - plate_drop / plate_trash / plate_recycle invoked without a plate
#     branch must warn on stderr and return None (no exception).
#   - plate_done with a content-overlap cherry-pick conflict must auto-
#     resolve in the plate's favor (-X theirs), advance HEAD with the
#     plate commit applied on top, and delete the plate branch — the
#     plate tip is the verified working state, so plate's content wins.
#   - Cross-repo patch portability: a `--drop` patch produced in repoA
#     applies cleanly in a separate repoB with the same base file.
#   - Plate SHA remains recoverable from the object database after
#     plate_done deletes the plate branch (no immediate gc).

def _check_plate_drop_no_branch_warns_and_exits(repo: Path, capsys) -> None:
    """Scenario: no plate branch exists → plate_drop returns None, prints
    warning to stderr, creates no .plate/trash/ directory, leaves WT clean."""
    branch = git_getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    assert not git_checkIfBranchExists(repo, plateBranchName)

    head_before = git_getSHAForRefViaRevParse(repo, "HEAD")
    wt_clean_before = git_checkForCleanWorkTree(repo)

    result = plate_drop(repo)

    captured = capsys.readouterr()
    assert result is None
    assert "no plate branch" in captured.err
    assert plateBranchName in captured.err
    # No trash directory created.
    assert not (repo / ".plate" / "trash").exists()
    # Repo state unchanged.
    assert git_getSHAForRefViaRevParse(repo, "HEAD") == head_before
    assert git_checkForCleanWorkTree(repo) == wt_clean_before

def _check_plate_trash_no_branch_warns_and_exits(repo: Path, capsys) -> None:
    """Scenario: no plate branch exists → plate_trash returns None, prints
    warning to stderr, creates no .plate/trash/ directory, leaves WT clean."""
    branch = git_getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    assert not git_checkIfBranchExists(repo, plateBranchName)

    head_before = git_getSHAForRefViaRevParse(repo, "HEAD")

    result = plate_trash(repo)

    captured = capsys.readouterr()
    assert result is None
    assert "no plate branch" in captured.err
    assert plateBranchName in captured.err
    assert not (repo / ".plate" / "trash").exists()
    assert git_getSHAForRefViaRevParse(repo, "HEAD") == head_before

def _check_plate_recycle_no_branch_warns_and_exits(repo: Path, capsys) -> None:
    """Scenario: no trashed plate session exists → plate_recycle returns None,
    prints warning to stderr, creates no plate branch, leaves repo unchanged."""
    branch = git_getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    assert not git_checkIfBranchExists(repo, plateBranchName)

    head_before = git_getSHAForRefViaRevParse(repo, "HEAD")

    result = plate_recycle(repo)

    captured = capsys.readouterr()
    assert result is None
    assert "nothing to recycle" in captured.err
    assert plateBranchName in captured.err
    assert not git_checkIfBranchExists(repo, plateBranchName)
    assert git_getSHAForRefViaRevParse(repo, "HEAD") == head_before

def _check_plate_done_resolves_content_conflict_in_plate_favor(repo: Path, capsys) -> None:
    """Scenario: the parent branch advanced with a commit that edits the same
    line a plate commit also edits, with different content. The plate tip is
    the verified working state, so plate_done must auto-resolve in the
    plate's favor (-X theirs), apply the plate commit on top of the parent
    advance, delete the plate branch, and emit no conflict warning.

    Setup:
      1. Replace TEST_FILENAME contents with "plate version\\n", plate_push.
      2. Reset WT, replace TEST_FILENAME contents with "branch version\\n"
         on HEAD, commit it.
      3. Restore WT to the plate tip's tree so plate_done's implicit
         pre-push is a no-op (this matches the user's mental model: at
         the moment of /plate --done, the WT IS the plate tip).

    Assertions after plate_done:
      - HEAD SHA has advanced past the parent-advance commit (cherry-pick
        applied at least one commit on top).
      - WT contents == "plate version\\n" (theirs/plate side won the
        conflict resolution; not "branch version\\n").
      - <branch>-plate ref is DELETED (success path completed).
      - No .git/CHERRY_PICK_HEAD marker.
      - No "cherry-pick conflict" warning on stderr.
    """
    branch = git_getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    # Setup: plate edit replaces file contents entirely.
    (repo / TEST_FILENAME).write_text("plate version\n")
    plate_push(repo)

    # Setup: reset, then a parent-branch commit replaces same line with
    # different text. This is the same content-overlap that aborted before.
    git_resetHardToHead(repo)
    (repo / TEST_FILENAME).write_text("branch version\n")
    git_addFile(repo, TEST_FILENAME)
    git_createCommit(repo, "branch advance - same line as plate")

    # Setup: restore WT to plate tip's tree so the implicit pre-push in
    # plate_done sees no diff and skips. The user model is that the WT at
    # /plate --done time IS the plate tip's verified state.
    run(["git", "checkout", plateBranchName, "--", TEST_FILENAME], cwd=repo)
    run(["git", "reset", "HEAD", "--", TEST_FILENAME], cwd=repo)

    head_before_done = git_getSHAForRefViaRevParse(repo, "HEAD")

    # Test action: plate_done.
    plate_done(repo)

    captured = capsys.readouterr()
    # Test verification: cherry-pick advanced HEAD (commit was applied).
    assert git_getSHAForRefViaRevParse(repo, "HEAD") != head_before_done
    # Test verification: plate side won the conflict resolution.
    assert (repo / TEST_FILENAME).read_text() == "plate version\n"
    # Test verification: WT matches HEAD (clean state).
    assert git_checkForCleanWorkTree(repo)
    # Test verification: plate branch deleted (success path).
    assert not git_checkIfBranchExists(repo, plateBranchName)
    # Test verification: no cherry-pick state lingering.
    assert not (repo / ".git" / "CHERRY_PICK_HEAD").exists()
    # Test verification: no conflict warning emitted.
    assert "cherry-pick conflict" not in captured.err

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
    untracked_name = git_test_createUntrackedFile(repoA, random.Random())["file"]
    untracked_content = (repoA / untracked_name).read_text()

    plate_push(repoA)
    session_dir = plate_drop(repoA)
    assert session_dir is not None
    patch_path = session_dir / "plate_001.patch"
    assert patch_path.exists()

    # Copy patch into repoB (mirrors emailing/Slacking the file).
    repoB_patch = repoB / "incoming.patch"
    shutil.copyfile(patch_path, repoB_patch)

    # Apply in repoB.
    git_applyPatch(repoB, repoB_patch)

    # Tracked edit applied byte-for-byte.
    assert (repoB / TEST_FILENAME).read_text() == edited_content
    # Untracked file from repoA's patch lands in repoB with same content.
    assert (repoB / untracked_name).exists()
    assert (repoB / untracked_name).read_text() == untracked_content
    # No conflict markers in the patched file.
    assert "<<<<<<<" not in (repoB / TEST_FILENAME).read_text()

def _check_plate_done_aborts_when_no_plate_branch(repo: Path, capsys) -> None:
    """Scenario: no plate branch exists -> plate_done warns to stderr and
    returns without touching HEAD, WT, or any branch."""
    branch = git_getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    assert not git_checkIfBranchExists(repo, plateBranchName)

    head_before = git_getSHAForRefViaRevParse(repo, "HEAD")
    wt_clean_before = git_checkForCleanWorkTree(repo)

    plate_done(repo)

    captured = capsys.readouterr()
    assert "no plate branch" in captured.err
    assert plateBranchName in captured.err
    # Repo state unchanged.
    assert git_getSHAForRefViaRevParse(repo, "HEAD") == head_before
    assert git_checkForCleanWorkTree(repo) == wt_clean_before
    assert not git_checkIfBranchExists(repo, plateBranchName)


def _check_plate_done_aborts_when_wt_differs_from_plate_tip(
    repo: Path, capsys
) -> None:
    """Scenario: plate exists but WT diverges from the plate tip (untracked
    file added after the plate_push) -> plate_done warns to stderr and
    returns. Plate branch, HEAD, and WT must all be untouched so the user
    can `/plate` the divergence and retry."""
    branch = git_getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    rng = random.Random()
    u1 = git_test_createUntrackedFile(repo, rng)["file"]
    plate_push(repo)
    plate_tip_sha_before = git_getSHAForRefViaRevParse(repo, plateBranchName)
    plate_tip_tree_before = git_getTreeSHA(repo, plateBranchName)
    head_before = git_getSHAForRefViaRevParse(repo, "HEAD")

    # Dirty WT with a NEW file so WT-tree != plate-tip-tree.
    u2 = git_test_createUntrackedFile(repo, rng)["file"]

    plate_done(repo)

    captured = capsys.readouterr()
    assert "working tree differs" in captured.err
    assert plateBranchName in captured.err
    # Plate branch ref unchanged.
    assert git_checkIfBranchExists(repo, plateBranchName)
    assert git_getSHAForRefViaRevParse(repo, plateBranchName) == plate_tip_sha_before
    assert git_getTreeSHA(repo, plateBranchName) == plate_tip_tree_before
    # HEAD unchanged.
    assert git_getSHAForRefViaRevParse(repo, "HEAD") == head_before
    # WT untouched: both untracked files still present.
    untracked = git_getUntrackedFilesList(repo)
    assert u1 in untracked
    assert u2 in untracked


def _check_plate_done_leaves_sha_recoverable(repo: Path) -> None:
    """Scenario: after plate_done deletes the plate branch, the plate's
    tip commit SHA is still resolvable from the object database. Documents
    the recoverability invariant — would catch a future regression that
    introduces an immediate `git gc --prune=now` or equivalent.
    """
    branch = git_getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    rng = random.Random()
    git_test_createUntrackedFile(repo, rng)
    plate_push(repo)
    plate_sha = git_getSHAForRefViaRevParse(repo, plateBranchName)

    plate_done(repo)

    # Plate branch ref is gone.
    assert not git_checkIfBranchExists(repo, plateBranchName)
    # But the commit object is still in the repo (recoverable until gc).
    assert git_getSHAForRefViaRevParse(repo, f"{plate_sha}^{{commit}}") == plate_sha

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
    if git_getCurrentBranchName(repo) != "main":
        git_resetHardToHead(repo)
        git_cleanWorkTree(repo)
        git_checkOutBranch(repo, "main")

    # First plate on main with fake transcript path (so list-mode falls back
    # to the convo-name trailer).
    (repo / TEST_FILENAME).write_text("edit on main\n")
    plate_push(
        repo,
        convo_id="/nonexistent/transcript-A.jsonl",
        convo_name="alpha work",
        convo_summary="summary A",
    )
    git_resetHardToHead(repo)

    # Force a measurable timestamp gap so plate_listPlateBranches sort is deterministic.
    time.sleep(1)

    # Second plate on a new feature-y branch off main.
    git_createAndCheckoutBranch(repo, "feature-y")
    (repo / TEST_FILENAME).write_text("edit on feature-y\n")
    plate_push(
        repo,
        convo_id="/nonexistent/transcript-B.jsonl",
        convo_name="beta work",
        convo_summary="summary B",
    )
    git_resetHardToHead(repo)
    assert git_getCurrentBranchName(repo) == "feature-y"

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
    _plate_writeTranscriptFile(transcript, cwd="/Users/me/jot", custom_title="fix-y bug investigation")

    shas = _plate_buildTwoBranchPlateTopology(repo, transcript_for_fixy=transcript)
    assert git_getCurrentBranchName(repo) == "feature-x"

    # Add dirty WIP on feature-x so jump-mode's implicit pre-push has work to capture.
    (repo / "feature.txt").write_text(
        "C1 work\nC2 polish\nPa1 wip\nPa2 more\nPa3 in-flight WIP\n"
    )
    feature_plate_count_before = git_countCommitsReachableFromRef(repo, "feature-x-plate")

    # Find the index of fix-y-plate via plate_listPlateBranches (same source the
    # listing uses, so indices match deterministically).
    plates_in_order = plate_listPlateBranches(repo)
    fixy_index = next(
        i + 1 for i, p in enumerate(plates_in_order) if p["ref"] == "fix-y-plate"
    )

    # Jump.
    result = plate_next(repo, index=str(fixy_index))

    # 1. WIP captured: feature-x-plate gained a commit.
    feature_plate_count_after = git_countCommitsReachableFromRef(repo, "feature-x-plate")
    assert feature_plate_count_after == feature_plate_count_before + 1

    # 2. HEAD now on fix-y at B3.
    assert git_getCurrentBranchName(repo) == "fix-y"
    assert git_getSHAForRefViaRevParse(repo, "HEAD") == shas["sha_B3"]

    # 3. WT contains fix-y-plate's tree (Pb3's content).
    assert (repo / "investigation.txt").read_text() == "Pb1 notes\nPb2 fix attempt\nPb3 final\n"
    # And fix-y's own files (B3's tree minus what plate's tree overwrites) are
    # consistent with the plate-tree restoration.
    # The plate's tree was built off B1, so it has fix.txt = "B1 fix\n".
    # After restoration, fix.txt should also equal the plate's version.
    assert (repo / "fix.txt").read_text() == "B1 fix\n"

    # 4. Resume command uses cwd + customTitle from the live transcript.
    assert result == "resume with: cd /Users/me/jot && claude --resume fix-y bug investigation"

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
        repo = git_test_makeRepoWithSingleCommit(sub)

        shas = _plate_buildTwoBranchPlateTopology(
            repo,
            transcript_for_fixy=fake_transcript_path,
            include_summary=include_summary,
        )
        assert git_getCurrentBranchName(repo) == "feature-x"

        plates = plate_listPlateBranches(repo)
        fixy_index = next(
            i + 1 for i, p in enumerate(plates) if p["ref"] == "fix-y-plate"
        )

        result = plate_next(repo, index=str(fixy_index))

        # Lost message returned (identical in both cases).
        assert result == PLATE_NEXT_LOST_MESSAGE
        # Branch switch still happens.
        assert git_getCurrentBranchName(repo) == "fix-y"
        assert git_getSHAForRefViaRevParse(repo, "HEAD") == shas["sha_B3"]
        # Tree restoration still happens — fix-y-plate's tree (B1-based) is in WT.
        assert (repo / "fix.txt").read_text() == "B1 fix\n"

        # Summary trailer presence in git matches the parameter — proves the
        # next agent can find the summary when it's there, and that absence
        # of summary doesn't change the return string.
        trailers = git_getCommitTrailers(repo, "fix-y-plate")
        if include_summary:
            assert "convo-summary" in trailers
            assert trailers["convo-summary"]
        else:
            assert "convo-summary" not in trailers

def _check_plate_next_jump_self_index_is_noop(repo: Path, tmp_path: Path) -> None:
    """Scenario: HEAD on feature-x; user picks the index of feature-x-plate
    (the *current* plate). plate_next returns the unchanged-message and
    leaves the repo untouched — no implicit pre-push, no branch switch,
    no WT change.
    """
    transcript = tmp_path / "fixy-transcript.jsonl"
    _plate_writeTranscriptFile(transcript, cwd="/Users/me/jot", custom_title="fix-y bug investigation")

    shas = _plate_buildTwoBranchPlateTopology(repo, transcript_for_fixy=transcript)
    assert git_getCurrentBranchName(repo) == "feature-x"

    # Snapshot pre-call state so we can prove nothing changed.
    head_before = git_getSHAForRefViaRevParse(repo, "HEAD")
    feature_plate_sha_before = git_getSHAForRefViaRevParse(repo, "feature-x-plate")
    feature_plate_count_before = git_countCommitsReachableFromRef(repo, "feature-x-plate")
    fixy_plate_sha_before = git_getSHAForRefViaRevParse(repo, "fix-y-plate")
    feature_txt_before = (repo / "feature.txt").read_text()
    wt_clean_before = git_checkForCleanWorkTree(repo)

    plates = plate_listPlateBranches(repo)
    self_index = next(
        i + 1 for i, p in enumerate(plates) if p["ref"] == "feature-x-plate"
    )

    result = plate_next(repo, index=str(self_index))

    # Return string identifies the plate via the title precedence chain.
    # feature-x-plate has a fake transcript (set by topology helper), so the
    # title falls back to the convo-name trailer ("feature work").
    assert result == "already on plate 'feature work'; worktree unchanged"

    # Nothing about the repo changed.
    assert git_getCurrentBranchName(repo) == "feature-x"
    assert git_getSHAForRefViaRevParse(repo, "HEAD") == head_before
    assert git_getSHAForRefViaRevParse(repo, "feature-x-plate") == feature_plate_sha_before
    assert git_countCommitsReachableFromRef(repo, "feature-x-plate") == feature_plate_count_before
    assert git_getSHAForRefViaRevParse(repo, "fix-y-plate") == fixy_plate_sha_before
    assert (repo / "feature.txt").read_text() == feature_txt_before
    assert git_checkForCleanWorkTree(repo) == wt_clean_before

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
    _plate_writeTranscriptFile(transcript, cwd="/Users/me/jot", custom_title="fix-y bug investigation")
    shas = _plate_buildTwoBranchPlateTopology(repo, transcript_for_fixy=transcript)

    # 2. Move HEAD to a brand-new branch `explore` off `main` that has NO
    #    associated `<branch>-plate` ref. WT is clean after the checkout.
    git_checkOutBranch(repo, "main")
    run(["git", "checkout", QUIET_OUTPUT, CREATE_BRANCH_AND_CHECKOUT_FLAG, "explore"], cwd=repo)
    assert git_getCurrentBranchName(repo) == "explore"
    assert not git_checkIfBranchExists(repo, "explore-plate")
    assert git_checkForCleanWorkTree(repo)

    # 3. Resolve the index of fix-y-plate so we have a deterministic target.
    #    fix-y-plate has the readable transcript, so a successful jump should
    #    return the local-resume form.
    plates = plate_listPlateBranches(repo)
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
    assert git_getCurrentBranchName(repo) == "fix-y"
    assert git_getSHAForRefViaRevParse(repo, "HEAD") == shas["sha_B3"]
    assert (repo / "fix.txt").read_text() == "B1 fix\n"

    # 7. Assert no spurious `explore-plate` ref was created. The implicit
    #    pre-push (step 1 of jump-mode) ran while on `explore` with a clean
    #    WT, so plate_push's empty-WIP guard returned None and no commit
    #    was made.
    assert not git_checkIfBranchExists(repo, "explore-plate")

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
    _plate_writeTranscriptFile(transcript, cwd="/Users/me/jot", custom_title="fix-y bug investigation")
    shas = _plate_buildTwoBranchPlateTopology(repo, transcript_for_fixy=transcript)
    assert git_getCurrentBranchName(repo) == "feature-x"
    assert len(plate_listPlateBranches(repo)) == 2

    # 2. Snapshot pre-call state so we can prove the rejected call had no
    #    side effects.
    head_before = git_getSHAForRefViaRevParse(repo, "HEAD")
    feature_plate_sha_before = git_getSHAForRefViaRevParse(repo, "feature-x-plate")
    fixy_plate_sha_before = git_getSHAForRefViaRevParse(repo, "fix-y-plate")
    feature_txt_before = (repo / "feature.txt").read_text()
    wt_clean_before = git_checkForCleanWorkTree(repo)

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
        assert git_getCurrentBranchName(repo) == "feature-x"
        assert git_getSHAForRefViaRevParse(repo, "HEAD") == head_before
        assert git_getSHAForRefViaRevParse(repo, "feature-x-plate") == feature_plate_sha_before
        assert git_getSHAForRefViaRevParse(repo, "fix-y-plate") == fixy_plate_sha_before
        assert (repo / "feature.txt").read_text() == feature_txt_before
        assert git_checkForCleanWorkTree(repo) == wt_clean_before

def _check_plate_next_list_empty_when_no_plates(repo: Path) -> None:
    """Scenario: a fresh repo has no plate refs. plate_next list-mode
    returns the friendly empty-list message instead of an empty string,
    so the user sees a clear signal that nothing is parked.
    """
    # 1. Confirm precondition: the repo has no plate-related refs at all.
    #    (No `*-plate` and no `*-plate-derived*` branches.)
    assert plate_listPlateBranches(repo) == []

    # 2. Call list mode.
    result = plate_next(repo)

    # 3. Assert the friendly empty-list message is returned (not an empty
    #    string, which would look like a silent failure to the user).
    assert result == PLATE_NEXT_EMPTY_LIST_MESSAGE

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
    _plate_writeTranscriptFile(transcript, cwd="/Users/me/jot", custom_title="fix-y bug investigation")
    _plate_buildTwoBranchPlateTopology(repo, transcript_for_fixy=transcript)

    # 2. Switch HEAD to a fresh `explore` branch off `main` that has no
    #    associated plate ref.
    git_checkOutBranch(repo, "main")
    run(["git", "checkout", QUIET_OUTPUT, CREATE_BRANCH_AND_CHECKOUT_FLAG, "explore"], cwd=repo)
    assert git_getCurrentBranchName(repo) == "explore"

    # 3. Confirm precondition: no `explore-plate` ref exists, but the two
    #    pre-existing plates DO exist.
    assert not git_checkIfBranchExists(repo, "explore-plate")
    assert git_checkIfBranchExists(repo, "feature-x-plate")
    assert git_checkIfBranchExists(repo, "fix-y-plate")

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

def _check_rewriteBranchTipSummary_strips_old_tip_and_adds_new_tip_summary(
    repo: Path,
) -> None:
    """Realistic mainline case for plate_rewriteBranchTipSummary.

    Setup: a plate branch with two commits.
      commit-1 (parent of tip) carries convo-summary: "old summary" plus
        the standard convo-id / convo-name / parent-branch trailers
        (because the previous push fired the agent and wrote a summary).
      commit-2 (tip) has convo-id / convo-name / parent-branch but NO
        convo-summary (the new push just landed; agent hasn't written
        the new summary yet).

    After running plate_rewriteBranchTipSummary(repo, branch, "<new text>"):
      - commit-1 has NO convo-summary trailer.
      - commit-2 (new tip) has convo-summary == "<new text>".
      - All other trailers (convo-id, convo-name, parent-branch) are
        preserved on both commits.
      - The branch ref points at the new tip.
    """
    branch = git_getCurrentBranchName(repo)
    plate_branch = f"{branch}-plate"

    parent_sha = git_getSHAForRefViaRevParse(repo, "HEAD")

    # Build commit-1: tree of HEAD plus a synthetic file path; commit
    # carries convo-summary + the standard trailers.
    git_addFile(repo, git_test_makeTestFile(repo, "plate-1.txt"))
    git_stageAllChanges(repo)
    commit1_msg = (
        "plate-1\n\n"
        "convo-id: convo-aaa\n"
        "convo-name: my conversation\n"
        f"parent-branch: {branch}\n"
        "convo-summary: old summary"
    )
    run(["git", "commit", "-q", "-m", commit1_msg], cwd=repo)
    commit1_sha = git_getSHAForRefViaRevParse(repo, "HEAD")
    # Move the plate ref to commit-1, then reset HEAD so we can build commit-2 on top.
    run(["git", "branch", "-f", plate_branch, commit1_sha], cwd=repo)
    run(["git", "reset", "--hard", parent_sha], cwd=repo)

    # Build commit-2 (the new tip — no convo-summary yet).
    git_addFile(repo, git_test_makeTestFile(repo, "plate-2.txt"))
    git_stageAllChanges(repo)
    commit2_msg = (
        "plate-2\n\n"
        "convo-id: convo-bbb\n"
        "convo-name: my conversation\n"
        f"parent-branch: {branch}"
    )
    # We need commit-2 to have commit-1 as parent to mirror the real
    # plate stack. Easiest: checkout the plate branch, commit there.
    run(["git", "checkout", "-q", plate_branch], cwd=repo)
    git_addFile(repo, git_test_makeTestFile(repo, "plate-2.txt"))
    git_stageAllChanges(repo)
    run(["git", "commit", "-q", "-m", commit2_msg], cwd=repo)
    commit2_sha = git_getSHAForRefViaRevParse(repo, "HEAD")
    # Return HEAD to the original branch so the rewrite happens via worktree.
    run(["git", "checkout", "-q", branch], cwd=repo)

    # Sanity: plate ref points at commit-2, with commit-1 as its parent.
    assert git_getSHAForRefViaRevParse(repo, plate_branch) == commit2_sha
    pre_trailers_1 = git_getCommitTrailers(repo, commit1_sha)
    pre_trailers_2 = git_getCommitTrailers(repo, commit2_sha)
    assert pre_trailers_1.get("convo-summary") == "old summary"
    assert "convo-summary" not in pre_trailers_2

    # Run.
    new_tip_sha = plate_rewriteBranchTipSummary(repo, branch, "the new summary text")

    # The branch ref must have advanced (or at least changed SHA).
    assert git_getSHAForRefViaRevParse(repo, plate_branch) == new_tip_sha
    # The two plate commits got rewritten — SHAs differ from before.
    # Walk only commits above the merge-base with the parent branch.
    new_log_shas = run(
        ["git", "log", "--format=%H", f"{parent_sha}..{plate_branch}"],
        cwd=repo,
    ).splitlines()
    assert len(new_log_shas) == 2, f"expected 2 plate commits; got {new_log_shas}"
    new_tip, new_parent = new_log_shas

    # Tip trailers: new convo-summary present + standard trailers preserved.
    tip_trailers = git_getCommitTrailers(repo, new_tip)
    assert tip_trailers.get("convo-summary") == "the new summary text", tip_trailers
    assert tip_trailers.get("convo-id") == "convo-bbb", (
        f"new_tip={new_tip} trailers={tip_trailers}"
    )
    assert tip_trailers.get("convo-name") == "my conversation"
    assert tip_trailers.get("parent-branch") == branch

    # Parent trailers: convo-summary stripped; other trailers preserved.
    parent_trailers = git_getCommitTrailers(repo, new_parent)
    assert "convo-summary" not in parent_trailers, parent_trailers
    assert parent_trailers.get("convo-id") == "convo-aaa"
    assert parent_trailers.get("convo-name") == "my conversation"
    assert parent_trailers.get("parent-branch") == branch
