import sys
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
from jot_plugin_orchestrator import *

import os
import pytest


# Real-tmux fixture: creates a detached session, yields its name, kills on teardown.
# Marked `live` because it spawns an actual tmux server.
@pytest.fixture
def tmux_win_session():
    name = f"tmux-py-win-test-{os.getpid()}"
    tmux_killSession(name)  # Setup: ensure no stale session of the same name
    rc = tmux_newSession(name)
    assert rc == 0, "fixture precondition: new session must succeed"
    yield name
    tmux_killSession(name)


@pytest.mark.live
def test_listWindows_newSession_hasOneWindow(tmux_win_session):
    # Scenario: A freshly created session contains exactly one window.
    # Setup: fixture created the session.
    # Test action: list windows.
    windows = tmux_listWindows(tmux_win_session)
    # Test verification: exactly one window reported.
    assert len(windows) == 1


@pytest.mark.live
def test_newWindow_succeedsOnExistingSession(tmux_win_session):
    # Scenario: tmux_newWindow on an existing session returns rc 0.
    # Setup: session exists via fixture.
    win_name = f"win-{os.getpid()}"
    # Test action: create a new window.
    rc = tmux_newWindow(tmux_win_session, win_name)
    # Test verification: rc 0 means tmux accepted the new window.
    assert rc == 0


@pytest.mark.live
def test_listWindows_afterNewWindow_hasTwoWindows(tmux_win_session):
    # Scenario: After creating one window, listWindows reports two windows.
    # Setup: session + one extra window.
    win_name = f"win-{os.getpid()}"
    assert tmux_newWindow(tmux_win_session, win_name) == 0
    # Test action: list windows.
    windows = tmux_listWindows(tmux_win_session)
    # Test verification: two windows present.
    assert len(windows) == 2


@pytest.mark.live
def test_killWindow_succeedsOnExistingWindow(tmux_win_session):
    # Scenario: tmux_killWindow on a known window target returns rc 0.
    # Setup: create a named window, then kill it.
    win_name = f"win-{os.getpid()}"
    assert tmux_newWindow(tmux_win_session, win_name) == 0
    target = f"{tmux_win_session}:{win_name}"
    # Test action: kill the named window.
    rc = tmux_killWindow(target)
    # Test verification: rc 0.
    assert rc == 0


@pytest.mark.live
def test_listWindows_afterKillWindow_hasOneWindow(tmux_win_session):
    # Scenario: After killing the added window, listWindows reports one window.
    # Setup: add then kill the second window.
    win_name = f"win-{os.getpid()}"
    assert tmux_newWindow(tmux_win_session, win_name) == 0
    assert tmux_killWindow(f"{tmux_win_session}:{win_name}") == 0
    # Test action: list windows.
    windows = tmux_listWindows(tmux_win_session)
    # Test verification: back down to one window.
    assert len(windows) == 1


@pytest.mark.live
def test_killWindow_failsOnNonexistentWindow(tmux_win_session):
    # Scenario: kill_window on a nonexistent window target returns nonzero rc.
    # Setup: a target name that was never created.
    bogus_target = f"{tmux_win_session}:nosuch-{os.getpid()}"
    # Test action: attempt kill on bogus target.
    rc = tmux_killWindow(bogus_target)
    # Test verification: nonzero rc indicates failure.
    assert rc != 0


@pytest.mark.live
def test_newWindow_failsOnNonexistentSession():
    # Scenario: new_window on a session that does not exist returns nonzero rc.
    # Setup: a session name that was never created.
    bogus_session = f"nonexistent-{os.getpid()}"
    win_name = f"whatever-{os.getpid()}"
    # Test action: attempt new window on bogus session.
    rc = tmux_newWindow(bogus_session, win_name)
    # Test verification: nonzero rc indicates failure.
    assert rc != 0


@pytest.mark.live
def test_windowExists_returnsTrueForExistingWindow(tmux_win_session):
    # Scenario: tmux_windowExists returns True when the window is present.
    # Setup: create a named window.
    win_name = f"win-{os.getpid()}"
    assert tmux_newWindow(tmux_win_session, win_name) == 0
    target = f"{tmux_win_session}:{win_name}"
    # Test action: check existence.
    result = tmux_windowExists(target)
    # Test verification: truthy result.
    assert result


@pytest.mark.live
def test_windowExists_returnsFalseForNonexistentWindow(tmux_win_session):
    # Scenario: tmux_windowExists returns False when the window does not exist.
    # Setup: a target name that was never created.
    target = f"{tmux_win_session}:nosuch-{os.getpid()}"
    # Test action: check existence.
    result = tmux_windowExists(target)
    # Test verification: falsy result.
    assert not result
