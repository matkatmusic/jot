"""RED tests for debate_launchAgentsParallel.

Mirrors bash `launch_agents_parallel` from jot-plugin-orchestrator.sh ~L2962-2997.
All in-flight deps (debate_launchAgent, debate_sendPromptToAgent, tmux_killPane) are
mocked at module boundary via monkeypatch -- no real tmux required.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _tmp_debate_launchAgentsParallel as module
from _tmp_debate_launchAgentsParallel import debate_launchAgentsParallel  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STAGE = "r1"
_PANES = ["%1", "%2"]
_AGENTS = ["claude", "gemini"]
_LAUNCH_CMD = {"claude": "claude --settings /tmp/s.json", "gemini": "gemini --settings /tmp/g.json"}
_READY_MARKER = {"claude": "Claude Code v", "gemini": "Gemini CLI v"}


# ---------------------------------------------------------------------------
# Shared patch helper
# ---------------------------------------------------------------------------

def _patch_deps(
    monkeypatch,
    *,
    launch_return: bool = True,
    send_return: int = 0,
):
    """Patch all in-flight dep functions on the module under test."""
    mock_launch = MagicMock(return_value=launch_return)
    mock_send = MagicMock(return_value=send_return)
    mock_kill = MagicMock(return_value=0)
    mock_launch_cmd = MagicMock(side_effect=lambda a: _LAUNCH_CMD.get(a, "unknown"))
    mock_ready_marker = MagicMock(side_effect=lambda a: _READY_MARKER.get(a, ""))

    monkeypatch.setattr(module, "debate_launchAgent", mock_launch)
    monkeypatch.setattr(module, "debate_sendPromptToAgent", mock_send)
    monkeypatch.setattr(module, "tmux_killPane", mock_kill)
    monkeypatch.setattr(module, "debate_agentLaunchCmd", mock_launch_cmd)
    monkeypatch.setattr(module, "debate_agentReadyMarker", mock_ready_marker)

    return mock_launch, mock_send, mock_kill


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_happy_path_two_agents_returns_zero(monkeypatch, tmp_path):
    # Scenario: two agents, no skip conditions; both workers succeed.
    # Setup: no output files, no lock files; launch and send return success.
    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch, launch_return=True, send_return=0)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES, _AGENTS, tmp_path)

    # Test verification: returns 0, both agents launched and prompted.
    assert rc == 0
    assert mock_launch.call_count == 2
    assert mock_send.call_count == 2
    mock_kill.assert_not_called()


def test_skip_when_output_file_exists(monkeypatch, tmp_path):
    # Scenario: output file for first agent exists and is non-empty; agent is skipped.
    # Setup: create non-empty output file for agent[0].
    output = tmp_path / f"{_STAGE}_{_AGENTS[0]}.md"
    output.write_text("previous result")

    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES, _AGENTS, tmp_path)

    # Test verification: kill called for skipped pane; only second agent launched.
    mock_kill.assert_any_call(_PANES[0])
    assert mock_launch.call_count == 1
    assert rc == 0


def test_skip_when_lock_file_exists(monkeypatch, tmp_path):
    # Scenario: lock file held for second agent; that agent is skipped.
    # Setup: create lock file for agent[1].
    lock = tmp_path / f".{_STAGE}_{_AGENTS[1]}.lock"
    lock.write_text("debate:%2")

    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES, _AGENTS, tmp_path)

    # Test verification: kill called for locked pane; only first agent launched.
    mock_kill.assert_any_call(_PANES[1])
    assert mock_launch.call_count == 1
    assert rc == 0


def test_partial_failure_returns_one(monkeypatch, tmp_path):
    # Scenario: one worker's send_prompt returns non-zero; overall result is 1.
    # Setup: launch succeeds; send_prompt returns 1 for all calls (simulates failure).
    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch, launch_return=True, send_return=1)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES, _AGENTS, tmp_path)

    # Test verification: at least one failure => returns 1.
    assert rc == 1


def test_empty_agents_list_returns_zero(monkeypatch, tmp_path):
    # Scenario: no agents provided; no workers launched; wall-time log still emitted.
    # Setup: empty panes and agents lists.
    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, [], [], tmp_path)

    # Test verification: no calls to any worker dep; returns 0.
    assert rc == 0
    mock_launch.assert_not_called()
    mock_send.assert_not_called()
    mock_kill.assert_not_called()


def test_launch_failure_returns_one(monkeypatch, tmp_path):
    # Scenario: debate_launchAgent returns False for one agent; worker returns 1.
    # Setup: launch returns False (timeout or error); send should not be called.
    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch, launch_return=False, send_return=0)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES[:1], _AGENTS[:1], tmp_path)

    # Test verification: returns 1; send never called because launch failed.
    assert rc == 1
    mock_send.assert_not_called()


def test_empty_output_file_does_not_skip(monkeypatch, tmp_path):
    # Scenario: output file exists but is empty (0 bytes); agent must NOT be skipped.
    # Setup: create zero-byte output file for agent[0].
    output = tmp_path / f"{_STAGE}_{_AGENTS[0]}.md"
    output.write_text("")

    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES, _AGENTS, tmp_path)

    # Test verification: both agents launched (empty file is not "complete").
    assert mock_launch.call_count == 2
    assert rc == 0
