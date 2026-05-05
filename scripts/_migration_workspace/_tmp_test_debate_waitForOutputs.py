"""RED tests for debate_waitForOutputs (migrated from bash wait_for_outputs).

Mocks the boundary: filesystem polling and capacity-error/retry callbacks.
Tag: RELAXED_COVERAGE — no paired bash _tests; tests authored from intent.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts/_migration_workspace")
from _tmp_debate_waitForOutputs import debate_waitForOutputs


def _write(p: Path, content: str = "x") -> None:
    p.write_text(content)


def test_returns_true_when_all_outputs_already_present(tmp_path):
    # Scenario: all agent output files exist with non-empty content before first poll
    # Setup: create r1_<agent>.md for each agent, populate panes map
    agents = ["gemini", "codex"]
    for a in agents:
        _write(tmp_path / f"r1_{a}.md", "done")
    panes = {0: "%1", 1: "%2"}
    capacity_check = MagicMock(return_value=False)
    retry_cb = MagicMock()
    sleep_fn = MagicMock()
    # Test action: call with short timeout
    ok, completed, reason = debate_waitForOutputs(
        prefix="r1", timeout=10, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=capacity_check,
        retry_pane=retry_cb, sleep_fn=sleep_fn, poll_interval=5,
    )
    # Test verification: success, both agents completed, no retries, no sleeps
    assert ok is True
    assert sorted(completed) == ["codex", "gemini"]
    assert reason is None
    retry_cb.assert_not_called()


def test_returns_false_with_timeout_reason_when_outputs_never_appear(tmp_path):
    # Scenario: no output files materialize within timeout
    # Setup: empty debate dir, panes have no capacity errors
    agents = ["gemini"]
    panes = {0: "%1"}
    sleep_fn = MagicMock()
    # Test action: timeout=5, poll=5 -> exactly one iteration
    ok, completed, reason = debate_waitForOutputs(
        prefix="r1", timeout=5, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=lambda p, a: False,
        retry_pane=MagicMock(), sleep_fn=sleep_fn, poll_interval=5,
    )
    # Test verification: failure with timeout reason, no completions
    assert ok is False
    assert completed == []
    assert reason is not None and "timeout" in reason.lower()


def test_removes_lock_file_when_output_appears(tmp_path):
    # Scenario: lock file exists alongside output; lock must be deleted on detection
    # Setup: create output AND lock file
    agents = ["claude"]
    panes = {0: "%1"}
    out = tmp_path / "r2_claude.md"
    lock = tmp_path / ".r2_claude.lock"
    _write(out, "synthesis")
    _write(lock, "debate:%1")
    # Test action: poll once
    ok, completed, _ = debate_waitForOutputs(
        prefix="r2", timeout=5, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=lambda p, a: False,
        retry_pane=MagicMock(), sleep_fn=MagicMock(), poll_interval=5,
    )
    # Test verification: success, lock file removed
    assert ok is True
    assert completed == ["claude"]
    assert not lock.exists()


def test_invokes_retry_when_pane_has_capacity_error_and_no_output(tmp_path):
    # Scenario: agent pane shows capacity error and no output file exists yet
    # Setup: no output files; capacity_check returns True for one agent
    agents = ["gemini"]
    panes = {0: "%5"}
    retry_cb = MagicMock()
    sleep_fn = MagicMock()
    # Test action: single poll iteration before timeout
    ok, _, reason = debate_waitForOutputs(
        prefix="r1", timeout=5, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=lambda p, a: True,
        retry_pane=retry_cb, sleep_fn=sleep_fn, poll_interval=5,
    )
    # Test verification: retry callback invoked with (panes, index, agent, prefix)
    assert ok is False
    assert reason is not None
    retry_cb.assert_called_once()
    args = retry_cb.call_args[0]
    assert args[1] == 0  # index
    assert args[2] == "gemini"
    assert args[3] == "r1"


def test_partial_completion_returns_only_completed_agents(tmp_path):
    # Scenario: some agents finish, others time out
    # Setup: only codex output present
    agents = ["gemini", "codex", "claude"]
    panes = {0: "%1", 1: "%2", 2: "%3"}
    _write(tmp_path / "r1_codex.md", "done")
    # Test action: timeout exhausted with partial state
    ok, completed, reason = debate_waitForOutputs(
        prefix="r1", timeout=5, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=lambda p, a: False,
        retry_pane=MagicMock(), sleep_fn=MagicMock(), poll_interval=5,
    )
    # Test verification: ok=False, only codex in completed
    assert ok is False
    assert completed == ["codex"]
    assert "timeout" in reason.lower()


def test_empty_output_file_does_not_count_as_complete(tmp_path):
    # Scenario: output file exists but is zero-byte (matches bash `[ -s "$out" ]`)
    # Setup: create empty file
    agents = ["gemini"]
    panes = {0: "%1"}
    (tmp_path / "r1_gemini.md").write_text("")  # zero bytes
    # Test action: single poll
    ok, completed, _ = debate_waitForOutputs(
        prefix="r1", timeout=5, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=lambda p, a: False,
        retry_pane=MagicMock(), sleep_fn=MagicMock(), poll_interval=5,
    )
    # Test verification: empty file -> not complete -> timeout
    assert ok is False
    assert completed == []
