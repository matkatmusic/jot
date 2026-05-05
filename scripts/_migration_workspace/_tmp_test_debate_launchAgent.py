"""RED tests for debate_launchAgent.

Mirrors bash `launch_agent` from jot-plugin-orchestrator.sh ~L2854-2872.
All tmux callees and write_failed are mocked at module boundary.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _tmp_debate_launchAgent import debate_launchAgent  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_PANE = "%7"
_STAGE = "r1"
_AGENT = "claude"
_CMD = "claude --settings /tmp/s.json --add-dir '/repo'"
_READY = "Claude Code v"


def _patch_all(
    pane_content: str = "",
    *,
    ready_after: int | None = 0,
):
    """Return a context-manager stack that patches all I/O callees.

    ready_after: iteration index (0-based) at which pane shows the ready marker.
                 None => never shows ready (simulate timeout).
    """
    captured_lines: list[str] = []
    call_count = 0

    def fake_capture(pane_id, scrollback_lines=2000):
        nonlocal call_count
        result = _READY if (ready_after is not None and call_count >= ready_after) else ""
        call_count += 1
        return result

    return (
        patch("_tmp_debate_launchAgent.tmux_sendAndSubmit"),
        patch("_tmp_debate_launchAgent.tmux_capturePane", side_effect=fake_capture),
        patch("_tmp_debate_launchAgent.write_failed"),
        patch("_tmp_debate_launchAgent.time_sleep"),
    )


# ---------------------------------------------------------------------------
# RED tests
# ---------------------------------------------------------------------------


def test_writes_lock_file_before_launch(tmp_path):
    # Scenario: launch_agent writes debate:<pane_id> to the lock file before
    #           sending the launch command.
    # Setup: fresh debate_dir, pane ready on first capture
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=0)
    with patches[0] as mock_send, patches[1], patches[2], patches[3]:
        debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
        )
    # Test verification: lock file contains "debate:%pane_id"
    lock = tmp_path / f".{_STAGE}_{_AGENT}.lock"
    assert lock.exists(), "lock file must exist after launch"
    assert lock.read_text().strip() == f"debate:{_PANE}"


def test_sends_launch_cmd_via_tmux(tmp_path):
    # Scenario: launch_agent calls tmux_send_and_submit with the correct pane
    #           and launch command string.
    # Setup: pane immediately ready
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=0)
    with patches[0] as mock_send, patches[1], patches[2], patches[3]:
        debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
        )
    # Test verification: sendAndSubmit called once with pane_id and launch_cmd
    mock_send.assert_called_once_with(_PANE, _CMD)


def test_returns_true_when_ready_marker_found(tmp_path):
    # Scenario: pane capture contains ready_marker before timeout.
    # Setup: capture returns ready string on iteration 0
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=0)
    with patches[0], patches[1], patches[2], patches[3]:
        result = debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
        )
    # Test verification: truthy result means success
    assert result is True


def test_returns_false_on_timeout(tmp_path):
    # Scenario: pane never shows ready_marker within timeout.
    # Setup: capture always returns empty string; use timeout=2 for speed
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=None)
    with patches[0], patches[1], patches[2], patches[3]:
        result = debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
            timeout=2,
        )
    # Test verification: False means timeout
    assert result is False


def test_calls_write_failed_on_timeout(tmp_path):
    # Scenario: after timeout, write_failed is called with stage + agent info.
    # Setup: capture never ready, short timeout
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=None)
    with patches[0], patches[1], patches[2] as mock_wf, patches[3]:
        debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
            timeout=2,
        )
    # Test verification: write_failed called once
    mock_wf.assert_called_once()
    args = mock_wf.call_args[0]
    assert args[0] == _STAGE  # first positional arg is stage


def test_sleeps_between_capture_polls(tmp_path):
    # Scenario: each polling iteration sleeps 1 second (mirrors bash `sleep 1`).
    # Setup: ready on iteration 2 (so 2 sleeps happen before success)
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=2)
    with patches[0], patches[1], patches[2], patches[3] as mock_sleep:
        debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
        )
    # Test verification: sleep(1) called at least twice
    assert mock_sleep.call_count >= 2
    mock_sleep.assert_any_call(1)


def test_default_timeout_is_120(tmp_path):
    # Scenario: when timeout is omitted, the function defaults to 120 iterations.
    # Setup: capture never ready; measure how many times sleep was called.
    # RELAXED_COVERAGE: bash default is 120; we verify the parameter default
    # rather than waiting 120 real seconds. We inspect the function signature.
    # Test action: introspect default parameter value
    import inspect
    sig = inspect.signature(debate_launchAgent)
    # Test verification: default value for `timeout` parameter is 120
    assert sig.parameters["timeout"].default == 120


def test_no_write_failed_on_success(tmp_path):
    # Scenario: write_failed must NOT be called when agent becomes ready in time.
    # Setup: pane immediately ready
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=0)
    with patches[0], patches[1], patches[2] as mock_wf, patches[3]:
        debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
        )
    # Test verification: write_failed never invoked on success
    mock_wf.assert_not_called()
