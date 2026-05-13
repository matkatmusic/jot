"""Reproducer for the "/plate: no changes to stack" false-negative bug.

When the user runs /plate twice in a single Claude session:
  1. modify a tracked file -> /plate push -> commits to <branch>-plate (OK)
  2. create a NEW untracked file -> /plate push -> returns
     "plate: no changes to stack" even though the WT has new content
     not yet on <branch>-plate.

This file drives the real plate_cli._cmd_push() against an on-disk git
repo built with the project's own git_lib / git_test_funcs_lib helpers.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "common" / "scripts" / "plate"))

from common.scripts.git_lib import (  # noqa: E402
    git_checkIfBranchExists,
    git_getCurrentBranchName,
    git_getSHAForRefViaRevParse,
    git_getStatus,
)
from common.scripts.git_test_funcs_lib import (  # noqa: E402
    git_test_makeRepoWithSingleCommit,
)
from common.scripts.plate import plate_cli  # noqa: E402
from common.scripts.plate import plate_lib  # noqa: E402


# Production cli.py always passes a session UUID as convo_id. We keep the
# same id across both pushes to mirror a single Claude session.
_SESSION_UUID = "11111111-2222-3333-4444-555555555555"


def test_secondPushAfterUntrackedFileCreated_returnsNoChangesToStack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: with a -plate branch already created from a prior modify+push,
    # a follow-up push that introduces a NEW untracked file in the same
    # Claude session must commit that file to the -plate tip. The bug:
    # plate_cli._cmd_push returns "plate: no changes to stack" instead.
    #
    # Setup: real on-disk repo with one tracked file (created via the
    # project's own git_test_funcs helper); PLATE_SKIP_LAUNCH=1 disables
    # the background summary agent so the push runs purely foreground.
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    branch = git_getCurrentBranchName(repo)
    plate_branch = f"{branch}-plate"
    tracked_file = plate_lib.TEST_FILENAME

    monkeypatch.setenv("PLATE_SKIP_LAUNCH", "1")

    # Test action 1: modify the one tracked file, then push.
    (repo / tracked_file).write_text("initial\nmodified\n")
    first_out = plate_cli._cmd_push([_SESSION_UUID, "", str(repo)])

    # Test verification 1: first push must produce a -plate ref. This is
    # the precondition for the bug under test; if this fails the rest of
    # the assertions are meaningless.
    assert first_out.startswith("plate: pushed "), (
        f"first push should have stacked the tracked-file edit, got: {first_out!r}"
    )
    assert git_checkIfBranchExists(repo, plate_branch), (
        f"{plate_branch} should exist after the first push"
    )
    first_plate_sha = git_getSHAForRefViaRevParse(repo, plate_branch)

    # Test action 2: create a NEW untracked file, then push again with
    # the SAME convo_id (single-session use).
    new_file = repo / "b.txt"
    new_file.write_text("brand new file\n")
    porcelain = git_getStatus(repo)
    assert "b.txt" in porcelain, (
        f"precondition: git status must show b.txt as untracked; got: {porcelain!r}"
    )

    second_out = plate_cli._cmd_push([_SESSION_UUID, "", str(repo)])

    # Test verification 2: second push MUST advance the -plate tip with a
    # commit that contains b.txt. The bug surfaces as:
    #   (a) literal "plate: no changes to stack" return value, AND/OR
    #   (b) the -plate tip SHA unchanged from after the first push.
    # Either signals a real WT change was silently dropped.
    second_plate_sha = git_getSHAForRefViaRevParse(repo, plate_branch)

    assert second_out != "plate: no changes to stack", (
        f"BUG: second push reported no changes despite untracked b.txt in WT.\n"
        f"  first  output: {first_out!r}\n"
        f"  second output: {second_out!r}\n"
        f"  WT status:     {porcelain!r}\n"
        f"  first  plate sha: {first_plate_sha}\n"
        f"  second plate sha: {second_plate_sha}"
    )
    assert second_plate_sha != first_plate_sha, (
        f"BUG: -plate tip SHA did not advance after second push.\n"
        f"  sha before/after: {first_plate_sha} == {second_plate_sha}\n"
        f"  second output: {second_out!r}"
    )


# ---------------------------------------------------------------------------
# Cross-session variant: extraction path
# ---------------------------------------------------------------------------
#
# This is the production failure mode the user hit: hookjson_lib.py was edited
# on disk, but /plate said "no changes to stack". The setup that matches
# real life:
#   - The -plate branch tip carries a `convo-id: <A>` trailer from a PRIOR
#     Claude session.
#   - The current session has a DIFFERENT convo_id (<B>) plus its own
#     transcript file.
#   - The edit on disk was made outside this session's transcript (the user
#     edited the file directly, or a different agent did).
#
# plate_push.use_extraction triggers (prev convo-id != mine), and
# _plate_buildExtractedTree reads ONLY my transcript's Edit/Write/MultiEdit
# entries. No entry for the edited file -> nothing gets staged onto the
# parent tree -> resulting tree == parent tree -> "no changes to stack".
# ---------------------------------------------------------------------------


_PRIOR_SESSION_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_CURRENT_SESSION_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _write_empty_transcript(path: Path) -> None:
    # Empty JSONL transcript: zero tool_use entries. Mirrors the state of
    # a fresh Claude session that has not yet recorded any Edit/Write
    # operations -- the exact condition under which the extraction path
    # has nothing to stage.
    path.write_text("")


def test_extractionPathDropsManuallyEditedFile_returnsNoChangesToStack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: a -plate branch already exists from a PRIOR Claude session
    # (convo-id trailer = A). The current session has a different convo_id
    # (B) plus its own transcript. The user edits a tracked file on disk
    # WITHOUT it being recorded in B's transcript (e.g., direct editor edit
    # or out-of-band tool). /plate push must still stack that change.
    # The bug: use_extraction triggers, B's empty transcript produces an
    # empty edited-files set, the extracted tree equals the parent tree,
    # and plate_push returns None -> "plate: no changes to stack".
    #
    # Setup: real on-disk repo, two transcript files (A's and B's), no
    # background summary agent.
    repo = git_test_makeRepoWithSingleCommit(tmp_path)
    branch = git_getCurrentBranchName(repo)
    plate_branch = f"{branch}-plate"
    tracked_file = plate_lib.TEST_FILENAME

    monkeypatch.setenv("PLATE_SKIP_LAUNCH", "1")

    transcript_a = tmp_path / "session_a.jsonl"
    transcript_b = tmp_path / "session_b.jsonl"
    _write_empty_transcript(transcript_a)
    _write_empty_transcript(transcript_b)

    # Test action 1: session A modifies the tracked file and pushes.
    # An empty transcript on the FIRST push is fine because no -plate
    # exists yet -> use_extraction is False (the branch-exists clause
    # short-circuits) -> _plate_buildFullWtTree captures the WT verbatim.
    (repo / tracked_file).write_text("initial\nsession-A edit\n")
    first_out = plate_cli._cmd_push(
        [_PRIOR_SESSION_UUID, str(transcript_a), str(repo)]
    )

    # Test verification 1 (precondition): -plate exists with convo-id=A.
    assert first_out.startswith("plate: pushed "), (
        f"session A push should have stacked, got: {first_out!r}"
    )
    assert git_checkIfBranchExists(repo, plate_branch), (
        f"{plate_branch} should exist after session A's push"
    )
    first_plate_sha = git_getSHAForRefViaRevParse(repo, plate_branch)
    from common.scripts.git_lib import git_getCommitTrailers
    trailers_after_first = git_getCommitTrailers(repo, plate_branch)
    assert trailers_after_first.get("convo-id") == _PRIOR_SESSION_UUID, (
        f"precondition: -plate tip must carry convo-id={_PRIOR_SESSION_UUID}; "
        f"got trailers {trailers_after_first!r}"
    )

    # Test action 2: session B makes a NEW on-disk edit to a DIFFERENT
    # tracked file (mirrors the production case where hookjson_lib.py:1
    # was edited but the change was not in B's transcript).
    edited_outside_transcript = repo / tracked_file
    edited_outside_transcript.write_text(
        edited_outside_transcript.read_text() + "session-B edit (manual)\n"
    )
    porcelain = git_getStatus(repo)
    assert tracked_file in porcelain, (
        f"precondition: git status must show {tracked_file} as modified; "
        f"got: {porcelain!r}"
    )

    second_out = plate_cli._cmd_push(
        [_CURRENT_SESSION_UUID, str(transcript_b), str(repo)]
    )

    # Test verification 2: B's push MUST advance the -plate tip with a
    # commit that includes the session-B edit. The bug surfaces as:
    #   (a) literal "plate: no changes to stack" return value, AND/OR
    #   (b) the -plate tip SHA unchanged after the second push.
    second_plate_sha = git_getSHAForRefViaRevParse(repo, plate_branch)

    assert second_out != "plate: no changes to stack", (
        f"BUG: extraction path dropped a real WT edit.\n"
        f"  first  (session A) output: {first_out!r}\n"
        f"  second (session B) output: {second_out!r}\n"
        f"  WT status:                 {porcelain!r}\n"
        f"  first  plate sha: {first_plate_sha}\n"
        f"  second plate sha: {second_plate_sha}\n"
        f"  trailers after first push: {trailers_after_first!r}"
    )
    assert second_plate_sha != first_plate_sha, (
        f"BUG: extraction path produced parent_tree-equal extracted tree.\n"
        f"  sha before/after: {first_plate_sha} == {second_plate_sha}\n"
        f"  second output: {second_out!r}"
    )
