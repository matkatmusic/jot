"""Tests for debate_newEmptyPane (migration workspace).

Live tests require a real tmux server; mark with @pytest.mark.live.
Mock tests cover error-path and return-value logic without tmux.
"""
import sys
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts/_migration_workspace")

import os
import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

from _tmp_debate_newEmptyPane import debate_newEmptyPane
from jot_plugin_orchestrator import tmux_killSession, tmux_newSession, tmux_listPanes


# ---------------------------------------------------------------------------
# Live fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def tmux_session():
    # Setup: create a detached tmux session; teardown kills it unconditionally.
    name = f"tmux-py-newemptypane-{os.getpid()}"
    tmux_killSession(name)
    rc = tmux_newSession(name)
    assert rc == 0, "fixture precondition: new session must succeed"
    yield name
    tmux_killSession(name)


# ---------------------------------------------------------------------------
# Mock-based tests (no real tmux required)
# ---------------------------------------------------------------------------

def test_newEmptyPane_returnsPaneId_onSuccess():
    # Scenario: subprocess succeeds and returns a pane id; function returns it.
    # Setup: mock subprocess.run to simulate tmux success with pane id '%7'.
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "%7\n"
    fake_result.stderr = ""
    with patch(
        "jot_plugin_orchestrator.tmux_selectLayout",
        return_value=0,
    ), patch(
        "_tmp_debate_newEmptyPane.subprocess.run",
        return_value=fake_result,
    ):
        # Test action: call with arbitrary window target and cwd.
        result = debate_newEmptyPane("mysession:mywindow", "/tmp")
    # Test verification: returned pane id matches stdout (stripped).
    assert result == "%7"


def test_newEmptyPane_returnsNone_onTmuxFailure():
    # Scenario: subprocess reports nonzero rc; function returns None.
    # Setup: mock subprocess.run to simulate tmux error.
    fake_result = MagicMock()
    fake_result.returncode = 1
    fake_result.stdout = ""
    fake_result.stderr = "error: no current target"
    with patch(
        "jot_plugin_orchestrator.tmux_selectLayout",
        return_value=0,
    ), patch(
        "_tmp_debate_newEmptyPane.subprocess.run",
        return_value=fake_result,
    ):
        # Test action: call with a target that would fail.
        result = debate_newEmptyPane("bogus:window", "/tmp")
    # Test verification: None returned on failure.
    assert result is None


def test_newEmptyPane_returnsNone_onEmptyPaneId():
    # Scenario: subprocess succeeds (rc=0) but stdout is blank; function returns None.
    # Setup: mock subprocess.run to return rc=0 with empty stdout.
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "   \n"
    fake_result.stderr = ""
    with patch(
        "jot_plugin_orchestrator.tmux_selectLayout",
        return_value=0,
    ), patch(
        "_tmp_debate_newEmptyPane.subprocess.run",
        return_value=fake_result,
    ):
        # Test action: call the function.
        result = debate_newEmptyPane("mysession:mywindow", "/tmp")
    # Test verification: None when pane id is empty/whitespace.
    assert result is None


def test_newEmptyPane_callsRetile_beforeSplit():
    # Scenario: tmux_retile is called with window_target before the split-window subprocess.
    # Setup: capture call order via mock.
    call_log: list[str] = []

    def fake_retile(target: str) -> int:
        call_log.append(f"retile:{target}")
        return 0

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "%9\n"
    fake_result.stderr = ""

    def fake_run(argv, **kwargs):
        call_log.append(f"split:{argv}")
        return fake_result

    with patch(
        "jot_plugin_orchestrator.tmux_selectLayout",
        side_effect=lambda t, l: fake_retile(t) or 0,
    ), patch(
        "_tmp_debate_newEmptyPane.subprocess.run",
        side_effect=fake_run,
    ):
        # Test action: call the function.
        debate_newEmptyPane("s:w", "/home/user")
    # Test verification: retile call appears before split call.
    assert len(call_log) == 2
    assert call_log[0].startswith("retile:")
    assert call_log[1].startswith("split:")


def test_newEmptyPane_passesCorrectCwdToSplit():
    # Scenario: -c <cwd> is present in the split-window argv.
    # Setup: capture argv passed to subprocess.run.
    captured_argv: list[list[str]] = []

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "%3\n"
    fake_result.stderr = ""

    def fake_run(argv, **kwargs):
        captured_argv.append(list(argv))
        return fake_result

    with patch(
        "jot_plugin_orchestrator.tmux_selectLayout",
        return_value=0,
    ), patch(
        "_tmp_debate_newEmptyPane.subprocess.run",
        side_effect=fake_run,
    ):
        # Test action: call with a specific cwd.
        debate_newEmptyPane("s:w", "/specific/path")
    # Test verification: argv contains '-c' followed by the given cwd.
    assert len(captured_argv) == 1
    argv = captured_argv[0]
    assert "-c" in argv
    idx = argv.index("-c")
    assert argv[idx + 1] == "/specific/path"


def test_newEmptyPane_retileRcIgnored_doesNotPreventSplit():
    # Scenario: tmux_retile returns nonzero; split still proceeds (RELAXED_COVERAGE).
    # Setup: retile mock returns 1, split mock returns success.
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "%5\n"
    fake_result.stderr = ""
    with patch(
        "jot_plugin_orchestrator.tmux_selectLayout",
        return_value=1,
    ), patch(
        "_tmp_debate_newEmptyPane.subprocess.run",
        return_value=fake_result,
    ):
        # Test action: call despite retile failure.
        result = debate_newEmptyPane("s:w", "/tmp")
    # Test verification: pane id still returned (retile rc not checked).
    assert result == "%5"


# ---------------------------------------------------------------------------
# Live tests (real tmux server)
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_newEmptyPane_addsPaneToWindow(tmux_session):
    # Scenario: calling debate_newEmptyPane on an existing window creates a new pane.
    # Setup: session has one pane (from fixture); form window target.
    window_target = f"{tmux_session}:0"
    before = tmux_listPanes(window_target, "-F", "#{pane_id}")
    # Test action: create a new empty pane.
    pane_id = debate_newEmptyPane(window_target, "/tmp")
    # Test verification: returned pane id is non-None and one more pane exists.
    assert pane_id is not None
    assert pane_id.startswith("%")
    after = tmux_listPanes(window_target, "-F", "#{pane_id}")
    assert len(after) == len(before) + 1


@pytest.mark.live
def test_newEmptyPane_returnedIdInPaneList(tmux_session):
    # Scenario: the pane id returned by debate_newEmptyPane is present in the live pane list.
    # Setup: form window target.
    window_target = f"{tmux_session}:0"
    # Test action: create a new pane.
    pane_id = debate_newEmptyPane(window_target, "/tmp")
    # Test verification: pane id appears in listPanes output.
    assert pane_id is not None
    ids = tmux_listPanes(window_target, "-F", "#{pane_id}")
    assert pane_id in ids


@pytest.mark.live
def test_newEmptyPane_returnsNone_onBogusTarget():
    # Scenario: calling debate_newEmptyPane with a nonexistent target returns None.
    # Setup: a session name that does not exist.
    bogus = f"nonexistent-session-{os.getpid()}:0"
    # Test action: attempt to create a pane in the bogus session.
    result = debate_newEmptyPane(bogus, "/tmp")
    # Test verification: None on tmux failure.
    assert result is None
