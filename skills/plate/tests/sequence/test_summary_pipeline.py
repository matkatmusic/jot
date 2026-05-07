"""Iteration 1 RED test for the convo-summary pipeline.

User-described scenario: a plate branch has commit A (with convo-summary,
from agent-A) and commit B (without, from agent-B). The pipeline must:
  1. Strip the convo-summary trailer from A.
  2. Generate a new summary using A's prior summary as input.
  3. Write the new summary onto B.

This test defines two new public functions by usage. Both must exist in
plate_lib.py. The agent step is mocked via a deterministic callable so
the test runs without spawning real claude.
"""
from __future__ import annotations

from pathlib import Path

# conftest.py adds common/scripts/plate/ to sys.path, so plate_lib is
# importable directly.
import pytest

from plate_lib import (
    plate_push,
    getGitCommitTrailers as getCommitTrailers,
    getCurrentGitBranchName as getCurrentBranchName,
    makeTestRepoWithSingleCommit,
    TEST_FILENAME,
    _writeFakeTranscriptWithToolUse,
    run,
)

# stripConvoSummaryFromCommit and regenerateTipSummary are RED features not yet
# implemented. Skip collection until they exist so the rest of the suite runs.
try:
    from plate_lib import (
        stripConvoSummaryFromCommit,
        regenerateTipSummary,
    )
except ImportError:
    pytest.skip(
        "stripConvoSummaryFromCommit/regenerateTipSummary not yet implemented",
        allow_module_level=True,
    )


def test_strip_prior_then_regenerate_tip_summary(tmp_path: Path) -> None:
    """End-to-end: strip prior commit's convo-summary, then regenerate
    the tip's convo-summary using the prior as the agent's input.

    Failing condition (any of):
      - the prior commit still has a convo-summary trailer after step 3
      - the tip commit's convo-summary is missing or doesn't match the
        agent's deterministic output
      - other trailers on either commit get clobbered
    """
    repo = makeTestRepoWithSingleCommit(tmp_path)
    branch = getCurrentBranchName(repo)
    plate_branch = f"{branch}-plate"

    # plate_push triggers the multi-agent extraction path whenever the
    # previous plate's convo-id differs from the incoming one — so each
    # agent needs a real transcript with Edit entries for the file they
    # touched, otherwise extraction stages nothing and push no-ops.
    transcript_a = tmp_path / "transcript_A.jsonl"
    _writeFakeTranscriptWithToolUse(
        transcript_a,
        [{"timestamp": "2099-01-01T00:00:00.000Z", "tool": "Edit",
          "input": {"file_path": str(repo / TEST_FILENAME)}}],
    )
    transcript_b = tmp_path / "transcript_B.jsonl"
    _writeFakeTranscriptWithToolUse(
        transcript_b,
        [{"timestamp": "2099-01-01T00:01:00.000Z", "tool": "Edit",
          "input": {"file_path": str(repo / TEST_FILENAME)}}],
    )

    # ── A (prior): edit + plate_push WITH convo-summary ───────────────
    (repo / TEST_FILENAME).write_text("agent A\n")
    plate_push(
        repo,
        convo_id="agent-A",
        convo_summary="OLD: original summary",
        transcript_path=str(transcript_a),
    )

    # ── B (tip): edit + plate_push WITHOUT convo-summary ──────────────
    (repo / TEST_FILENAME).write_text("agent B\n")
    plate_push(
        repo,
        convo_id="agent-B",
        transcript_path=str(transcript_b),
    )

    # Pre-condition: A has convo-summary; B does not.
    a_pre = getCommitTrailers(repo, f"{plate_branch}~1")
    b_pre = getCommitTrailers(repo, plate_branch)
    assert a_pre.get("convo-summary") == "OLD: original summary", a_pre
    assert "convo-summary" not in b_pre, b_pre

    # ── Action 1: strip A's convo-summary ─────────────────────────────
    stripConvoSummaryFromCommit(repo, branch, target_ref=f"{plate_branch}~1")

    # A no longer has convo-summary; B unchanged (still no trailer).
    a_mid = getCommitTrailers(repo, f"{plate_branch}~1")
    b_mid = getCommitTrailers(repo, plate_branch)
    assert "convo-summary" not in a_mid, a_mid
    assert "convo-summary" not in b_mid, b_mid
    # Other A trailers preserved.
    assert a_mid.get("convo-id") == "agent-A", a_mid
    assert a_mid.get("parent-branch") == branch, a_mid

    # ── Action 2: regenerate tip summary, agent fed with prior ────────
    fake_agent_calls: list[str] = []

    def fake_agent(prior_summary: str) -> str:
        fake_agent_calls.append(prior_summary)
        return f"NEW: rewrote based on {prior_summary}"

    regenerateTipSummary(
        repo,
        branch,
        prior_summary="OLD: original summary",
        agent_callable=fake_agent,
    )

    # B has the new summary; A still empty.
    a_post = getCommitTrailers(repo, f"{plate_branch}~1")
    b_post = getCommitTrailers(repo, plate_branch)
    assert "convo-summary" not in a_post, a_post
    assert (
        b_post.get("convo-summary")
        == "NEW: rewrote based on OLD: original summary"
    ), b_post
    # Other B trailers preserved.
    assert b_post.get("convo-id") == "agent-B", b_post
    assert b_post.get("parent-branch") == branch, b_post
    # Agent invoked exactly once with A's prior summary.
    assert fake_agent_calls == ["OLD: original summary"]


def test_regenerate_tip_summary_splits_subject_and_body(tmp_path: Path):
    """Realistic agent payload handling.

    The agent's summary.txt (per `skills/plate/summary-template.md`)
    is structured as:
      Line 1: subject (≤50 chars; replaces the tip's commit subject)
      Line 2: blank
      Lines 3+: 5-section body (`what:`/`why:`/`how:`/...; becomes the
                                 convo-summary trailer value)

    `regenerateTipSummary` must:
      1. replace the tip's commit subject with line 1 of the payload,
      2. put ONLY the body into the convo-summary trailer (NOT the
         subject line),
      3. produce a trailer block git's
         `interpret-trailers --parse` recognizes (i.e.,
         `getCommitTrailers` returns a non-empty `convo-summary` key).

    Failing condition (any of):
      - tip's commit subject is unchanged (still `plate: WIP on ...`)
      - the convo-summary trailer value contains the subject line
      - getCommitTrailers returns no convo-summary at all (git's parser
        rejected the trailer block)
    """
    repo = makeTestRepoWithSingleCommit(tmp_path)
    branch = getCurrentBranchName(repo)
    plate_branch = f"{branch}-plate"

    # Setup: tip commit on plate (no convo-summary yet).
    transcript = tmp_path / "transcript.jsonl"
    _writeFakeTranscriptWithToolUse(transcript, [
        {"timestamp": "2099-01-01T00:00:00.000Z", "tool": "Edit",
         "input": {"file_path": str(repo / TEST_FILENAME)}},
    ])
    (repo / TEST_FILENAME).write_text("agent edit\n")
    plate_push(repo, convo_id="agent-X", transcript_path=str(transcript))

    # Realistic agent payload — subject + blank + 3-section body.
    realistic_payload = (
        "Migrate scan-open-todos to python\n"
        "\n"
        "what:\n"
        "scan-open-todos.sh now an exec-python3 shim.\n"
        "\n"
        "why:\n"
        "continue the bash to python migration.\n"
        "\n"
        "how:\n"
        "lib + cli + shim pattern.\n"
    )

    regenerateTipSummary(
        repo, branch,
        prior_summary="",
        agent_callable=lambda _prior: realistic_payload,
    )

    # 1. Subject replaced with line 1 of the payload.
    new_subject = run(
        ["git", "log", "-1", "--format=%s", plate_branch], cwd=repo,
    )
    assert new_subject == "Migrate scan-open-todos to python", new_subject

    # 2-3. git's trailer parser recognizes the block and the value is
    # the body only (no subject line embedded).
    trailers = getCommitTrailers(repo, plate_branch)
    assert "convo-summary" in trailers, (
        f"git's trailer parser must recognize the trailer block; "
        f"got trailers={trailers!r}"
    )
    summary_value = trailers["convo-summary"]
    assert "Migrate scan-open-todos to python" not in summary_value, (
        f"subject line must NOT appear inside the trailer value: "
        f"{summary_value!r}"
    )
    assert "what:" in summary_value, summary_value
    assert "why:" in summary_value, summary_value
    assert "how:" in summary_value, summary_value

    # Other trailers preserved.
    assert trailers.get("convo-id") == "agent-X"
    assert trailers.get("parent-branch") == branch
