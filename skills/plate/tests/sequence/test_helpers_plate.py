"""Tests for plate-specific helpers (plate_listPlateBranches, plate_findMyLastPlate,
plate_push/done/drop/trash/recycle/next, etc.).

Split from test_helpers.py per MIGRATION_TO_PYTHON.md bucket [plate].
"""
from __future__ import annotations

import random
import time
from pathlib import Path

import pytest

# After the test_* functions migrated out of plate_lib.py, every library
# symbol the tests reference must be importable into this namespace —
# including underscore-prefixed scenario callables (`_check_*`) and
# private helpers (`_plate_writeFakeTranscriptWithToolUse`, etc.) that
# `from plate_lib import *` would skip. Pull them in explicitly via vars().
# (sys.path setup already done by conftest.py.)
import plate_lib as _plate_lib
from common.scripts.git_lib import (
    git_getCurrentBranchName
)

import test_plate_scenarios as _plate_scenarios
from test_plate_scenarios import (
    _check_plate_push_creates_branch_capturing_wip,
)

globals().update({
    name: value
    for name, value in vars(_plate_scenarios).items()
    if name.startswith("_check_") or name.startswith("_build") or name.startswith("_write")
})

globals().update({
    name: value
    for name, value in vars(_plate_lib).items()
    if not name.startswith("__")
})

def test_formatPlateAge():
    assert plate_formatPlateAge(0) == "0m"
    assert plate_formatPlateAge(59) == "0m"
    assert plate_formatPlateAge(60) == "1m"
    assert plate_formatPlateAge(32 * 60) == "32m"
    assert plate_formatPlateAge(14 * 3600 + 7 * 60) == "14h 7m"
    assert plate_formatPlateAge(3 * 86400 + 2 * 3600 + 5 * 60) == "3d 2h 5m"
    # Edge: exactly one hour with no remaining minutes.
    assert plate_formatPlateAge(3600) == "1h 0m"
    # Negative seconds clamp to zero.
    assert plate_formatPlateAge(-5) == "0m"

def test_listPlateBranches(tmp_path: Path):
    """Two plate branches across two working branches → both listed, newest first."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)

    # First plate on `main`.
    (repo / TEST_FILENAME).write_text("edit on main\n")
    plate_push(repo, convo_id="t1.jsonl", convo_name="convo-on-main")

    # Force a measurable timestamp gap so committer_unix sort is deterministic.
    time.sleep(1)

    # Second plate on a new branch `feature-x`.
    git_resetHardToHead(repo)
    git_createAndCheckoutBranch(repo, "feature-x")
    (repo / TEST_FILENAME).write_text("edit on feature\n")
    plate_push(repo, convo_id="t2.jsonl", convo_name="convo-on-feature")

    result = plate_listPlateBranches(repo)
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
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    git_createAndCheckoutBranch(repo, "feature-y")
    # No plate pushed; `feature-y` and `main` are plain branches.
    assert plate_listPlateBranches(repo) == []

def test_findMyLastPlate(tmp_path: Path):
    """plate_findMyLastPlate walks the branch and returns most recent matching trailer."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    branch = git_getCurrentBranchName(repo)
    plate_branch = f"{branch}-plate"

    # No branch yet → (None, None).
    assert plate_findMyLastPlate(repo, plate_branch, "A") == (None, None)

    # Push 3 plates with alternating convo_ids: A, B, A.
    (repo / TEST_FILENAME).write_text("A1\n")
    sha_a1 = plate_push(repo, convo_id="A")
    (repo / TEST_FILENAME).write_text("A1\nB1\n")
    plate_push(repo, convo_id="B")
    (repo / TEST_FILENAME).write_text("A1\nB1\nA2\n")
    sha_a2 = plate_push(repo, convo_id="A")

    # plate_findMyLastPlate("A") returns the most recent A commit (sha_a2) with date.
    sha, date = plate_findMyLastPlate(repo, plate_branch, "A")
    assert sha == sha_a2
    assert sha != sha_a1
    assert date is not None
    # ISO-8601 date with timezone (e.g. "2026-04-30 14:47:14 -0700").
    assert len(date) >= len("2026-04-30 14:47:14 -0700")

    # convo_id not present → (None, None).
    assert plate_findMyLastPlate(repo, plate_branch, "C") == (None, None)

    # Non-existent branch → (None, None).
    assert plate_findMyLastPlate(repo, "nonexistent-plate", "A") == (None, None)

def test_plate_push_1x(tmp_path: Path):
    """Per-function: plate_push contract + fixture-specific stash/checkout flow.

    Shared scenario covers the plate-creation contract; the rest verifies that
    you can stash the conflicting untracked file, check out the plate branch
    to inspect its exact tracked-file list (this fixture: .gitignore + a.txt
    + the new file), then switch back and unstash.
    """
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_push_creates_branch_capturing_wip(repo)

    # Fixture-specific extras: clear the tracked modification (so checkout
    # doesn't conflict on it), stash the untracked, then verify the plate
    # branch's exact tracked-file list via checkout.
    originalBranch = git_getCurrentBranchName(repo)
    plateBranchName = f"{originalBranch}-plate"
    untrackedFileName = next(
        f for f in git_getUntrackedFilesList(repo) if f.startswith("new-")
    )

    git_resetHardToHead(repo)
    git_stashFiles(repo, [untrackedFileName])
    assert git_getUntrackedFilesList(repo) == []

    git_checkOutBranch(repo, plateBranchName)
    assert sorted(git_getTrackedFilesList(repo)) == sorted(
        [".gitignore", TEST_FILENAME, untrackedFileName]
    )

    git_checkOutBranch(repo, originalBranch)
    git_unstashFiles(repo)
    assert git_getCurrentBranchName(repo) == originalBranch
    assert untrackedFileName in git_getUntrackedFilesList(repo)

def test_plate_push_with_convo_id(tmp_path: Path):
    """plate_push writes parent-branch always, and convo-* trailers when set."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    (repo / TEST_FILENAME).write_text("modified\n")

    sha = plate_push(
        repo,
        convo_id="/Users/me/.claude/projects/proj/abc-123.jsonl",
        convo_name="my titled convo",
        convo_summary="line one\nline two\nline three",
    )
    assert sha is not None

    branch = git_getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"
    trailers = git_getCommitTrailers(repo, plateBranchName)

    assert trailers["parent-branch"] == branch
    assert trailers["convo-id"] == "/Users/me/.claude/projects/proj/abc-123.jsonl"
    assert trailers["convo-name"] == "my titled convo"
    # Multi-line summary input collapses to single line of space-joined words.
    assert trailers["convo-summary"] == "line one line two line three"

def test_plate_push_convo_summary_preserves_section_labels_on_own_lines(
    tmp_path: Path,
):
    """Regression for multi-line trailer formatting.

    Earlier code collapsed all whitespace in the convo-summary body to
    single spaces (`" ".join(text.split())`), so when the user ran
    `git log -1 --format='%(trailers)'` everything appeared as one wall
    of text. The agent's section labels (`what:` `why:` `how:` ...) were
    no longer on their own lines.

    Fix: indent every continuation line with a single space (git's
    standard multi-line trailer continuation rule), preserving the line
    breaks. `git_getCommitTrailers` uses `unfold=true`, so the flat-form
    test contract still holds for callers that expect a single-line
    string.

    Failing condition: the raw commit message has the section labels
    smashed onto one line, OR the unfolded read returns something
    other than the flat space-joined string.
    """
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    (repo / TEST_FILENAME).write_text("modified\n")

    summary = (
        "what:\n"
        "extracted git_lib from plate_lib.\n"
        "why:\n"
        "python migration cleanup.\n"
        "how:\n"
        "verbatim move plus a shim."
    )
    sha = plate_push(repo, convo_summary=summary)
    assert sha is not None

    branch = git_getCurrentBranchName(repo)
    plateBranchName = f"{branch}-plate"

    # Raw commit message: each section label is at the start of a line
    # (with the single leading space that marks a trailer continuation).
    raw = run(["git", "log", "-1", "--format=%B", plateBranchName], cwd=repo)
    # The convo-summary trailer line opens with `convo-summary: what:`.
    # The continuation lines are space-prefixed (` why:` etc.).
    assert "convo-summary: what:" in raw
    assert "\n why:" in raw, f"why: not on its own line in raw message:\n{raw}"
    assert "\n how:" in raw, f"how: not on its own line in raw message:\n{raw}"

    # Unfolded read (the form code paths already depend on): collapses
    # continuation lines to single-space joins. Existing flat-form
    # contract preserved.
    trailers = git_getCommitTrailers(repo, plateBranchName)
    flat = trailers["convo-summary"]
    assert "what:" in flat and "why:" in flat and "how:" in flat
    # No literal newline in the unfolded form.
    assert "\n" not in flat


def test_plate_push_extraction_uses_explicit_transcript_path_arg(tmp_path: Path):
    """Regression for the production-vs-test convo_id semantics mismatch.

    cli.py passes a session UUID as ``convo_id`` and the transcript file
    path as a SEPARATE ``transcript_path`` argument. Earlier code in
    ``_plate_buildExtractedTree`` did ``Path(convo_id)`` and treated the UUID
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
    git_createUserConfig(repo)
    git_writeGitignore(repo)
    git_addFile(repo, ".gitignore")
    (repo / "a.txt").write_text("base\n")
    git_addFile(repo, "a.txt")
    git_createCommit(repo, "initial")

    # Agent A: UUID-style convo_id, transcript stored at a separate path.
    uuid_A = "9f2be37f-0620-4877-b2e5-03c4ac2cdf35"
    transcript_A = tmp_path / f"{uuid_A}.jsonl"
    _plate_writeFakeTranscriptWithToolUse(
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
    _plate_writeFakeTranscriptWithToolUse(
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

    trailers = git_getCommitTrailers(repo, "main-plate")
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
    git_createUserConfig(repo)
    git_writeGitignore(repo)
    git_addFile(repo, ".gitignore")
    (repo / "a.txt").write_text("base\n")
    git_addFile(repo, "a.txt")
    git_createCommit(repo, "initial")

    # 1 & 2: Agent A's transcript with one Edit-on-a.txt entry (timestamps far
    # in the future so the cutoff filter never excludes them in this test).
    transcript_A = tmp_path / "transcript_A.jsonl"
    _plate_writeFakeTranscriptWithToolUse(
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
    _plate_writeFakeTranscriptWithToolUse(
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
    _plate_writeFakeTranscriptWithToolUse(
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
    pb1_trailers = git_getCommitTrailers(repo, "main-plate")
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
    pa2_trailers = git_getCommitTrailers(repo, "main-plate")
    assert pa2_trailers["convo-id"] == str(transcript_A)

    # 12: Agent B "deletes" b.txt — append a Bash rm entry to Agent B's
    #     transcript; actually unlink the file from WT to mirror the rm.
    _plate_writeFakeTranscriptWithToolUse(
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
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    (repo / TEST_FILENAME).write_text("modified\n")

    sha = plate_push(repo)
    assert sha is not None

    branch = git_getCurrentBranchName(repo)
    trailers = git_getCommitTrailers(repo, f"{branch}-plate")
    assert trailers["parent-branch"] == branch
    assert "convo-id" not in trailers
    assert "convo-name" not in trailers
    assert "convo-summary" not in trailers

def test_plate_done(tmp_path: Path):
    """Per-function: 2-plate stack → done cherry-picks both, deletes plate, WT clean."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_done_replays_stack(repo)

def test_plate_drop(tmp_path: Path):
    """Per-function: single plate → drop deletes branch + writes patch.
    Shared scenario covers the contract; runs against the 1-commit fixture."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_drop_deletes_last_plate(repo)

def test_plate_trash(tmp_path: Path):
    """Per-function: 2-plate stack → trash saves patches + deletes branch + WT preserved."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_trash_default_preserves_wt(repo)

def test_plate_trash_hard(tmp_path: Path):
    """Per-function: dirty 2-plate stack → trash --hard saves patches + wipes WT."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_trash_clean_resets_wt(repo)

def test_plate_recycle(tmp_path: Path):
    """Per-function: 2 plates → trash → recycle restores branch with same tree."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_recycle_restores_stack(repo)

def test_simulate_derived_agent_first(tmp_path: Path):
    """Per-function: first derived agent records trailers."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_first_derived_agent_records_trailers(repo)

def test_simulate_derived_agent_second(tmp_path: Path):
    """Per-function: second derived agent extends chain (parent-convo points at previous)."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_second_derived_agent_extends_chain(repo)

def test_plate_drop_no_branch(tmp_path: Path, capsys):
    """Per-function: plate_drop with no plate branch warns + returns None."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_drop_no_branch_warns_and_exits(repo, capsys)

def test_plate_trash_no_branch(tmp_path: Path, capsys):
    """Per-function: plate_trash with no plate branch warns + returns None."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_trash_no_branch_warns_and_exits(repo, capsys)

def test_plate_recycle_no_branch(tmp_path: Path, capsys):
    """Per-function: plate_recycle with no trashed session warns + returns None."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_recycle_no_branch_warns_and_exits(repo, capsys)

def test_plate_done_resolves_content_conflict_in_plate_favor(tmp_path: Path, capsys):
    """Per-function: plate_done auto-resolves content conflicts in plate's favor."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_done_resolves_content_conflict_in_plate_favor(repo, capsys)

def test_drop_patch_cross_repo_portability(tmp_path: Path):
    """Per-function: drop patch from repoA applies in a separate repoB."""
    repoA = git_test_makeRepoWithSingleCommit(tmp_path / "a")
    repoB = git_test_makeRepoWithSingleCommit(tmp_path / "b")
    _check_drop_patch_applies_in_fresh_repo(repoA, repoB)

def test_plate_done_leaves_sha_recoverable(tmp_path: Path):
    """Per-function: plate_done's deleted plate SHA is still in the object DB."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_done_leaves_sha_recoverable(repo)

def test_plate_done_aborts_when_no_plate_branch(tmp_path: Path, capsys):
    """Per-function: plate_done with no plate branch warns + returns without
    touching the repo."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_done_aborts_when_no_plate_branch(repo, capsys)

def test_plate_done_aborts_when_wt_differs_from_plate_tip(tmp_path: Path, capsys):
    """Per-function: plate_done with WT diverged from plate tip warns + returns,
    leaving plate branch and WT intact."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_done_aborts_when_wt_differs_from_plate_tip(repo, capsys)

def test_plate_next_list_shows_plates_sorted_with_current_marker(tmp_path: Path):
    """Per-function: list mode against the single-commit fixture."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_next_list_shows_plates_sorted_with_current_marker(repo)

def test_plate_next_jump_restores_plate_tree_without_post_plate_branch_changes(tmp_path: Path):
    """Per-function: cross-branch jump with readable target transcript."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_next_jump_restores_plate_tree_without_post_plate_branch_changes(repo, tmp_path)

def test_plate_next_jump_lost_message_when_transcript_unreadable(tmp_path: Path):
    """Per-function: lost-path jump, parametrized over summary present/absent."""
    _check_plate_next_jump_lost_message_when_transcript_unreadable(tmp_path)

def test_plate_next_jump_self_index_is_noop(tmp_path: Path):
    """Per-function: picking the current plate's index is a no-op."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_next_jump_self_index_is_noop(repo, tmp_path)

def test_plate_next_jump_proceeds_when_head_on_branch_with_no_plate(tmp_path: Path):
    """Per-function: jump from a plate-less branch proceeds normally."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_next_jump_proceeds_when_head_on_branch_with_no_plate(repo, tmp_path)

def test_plate_next_jump_invalid_index_returns_message(tmp_path: Path):
    """Per-function: invalid index returns user-facing message, no side effects."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_next_jump_invalid_index_returns_message(repo, tmp_path)

def test_plate_next_list_empty_when_no_plates(tmp_path: Path):
    """Per-function: list mode on a repo with no plates returns the friendly
    empty-list message."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_next_list_empty_when_no_plates(repo)

def test_plate_next_list_no_marker_when_head_has_no_plate(tmp_path: Path):
    """Per-function: list mode marks no entries when HEAD has no plate."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_plate_next_list_no_marker_when_head_has_no_plate(repo, tmp_path)

def test_rewriteBranchTipSummary_strips_old_tip_and_adds_new_tip_summary(tmp_path: Path) -> None:
    """Per-function: rebase-reword strips old summary, writes new on tip."""
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    _check_rewriteBranchTipSummary_strips_old_tip_and_adds_new_tip_summary(repo)
