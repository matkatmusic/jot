import sys
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
from jot_plugin_orchestrator import *

import os
import shutil
import subprocess
import pytest


# Skip the whole module if tmux isn't available on the runner.
if shutil.which("tmux") is None:
    pytest.skip("tmux not installed", allow_module_level=True)


def _kill_session(name: str) -> None:
    # Helper: best-effort cleanup; ignore failure when session doesn't exist.
    subprocess.run(
        ["tmux", "kill-session", "-t", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


@pytest.fixture
def tmux_session():
    # Fixture: create a fresh detached tmux session, yield its name, kill on teardown.
    name = f"tmux-sh-win-test-{os.getpid()}"
    _kill_session(name)
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    yield name
    _kill_session(name)


@pytest.mark.live
def test_listWindows_newSession_hasOneWindow(tmux_session):
    # Scenario: a freshly created tmux session reports exactly one window.
    # Setup: fixture provides an empty session.
    # Test action: list windows in the session.
    result = tmux_listWindows(tmux_session)
    # Test verification: command succeeds and yields a single line of output.
    assert result.returncode == 0
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1


@pytest.mark.live
def test_newWindow_createsSecondWindow(tmux_session):
    # Scenario: tmux_newWindow adds a window to an existing session.
    # Setup: empty session from fixture; window name unique to PID.
    win = f"win-{os.getpid()}"
    # Test action: create a new window.
    rc = tmux_newWindow(tmux_session, win)
    # Test verification: returns success.
    assert rc == 0


@pytest.mark.live
def test_listWindows_afterNewWindow_showsTwo(tmux_session):
    # Scenario: after adding a window, list_windows reports two entries.
    # Setup: create one extra window in the fixture session.
    win = f"win-{os.getpid()}"
    assert tmux_newWindow(tmux_session, win) == 0
    # Test action: list windows.
    result = tmux_listWindows(tmux_session)
    # Test verification: exactly two non-empty output lines.
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 2


@pytest.mark.live
def test_splitWindow_horizontal_succeeds(tmux_session):
    # Scenario: split_window with horizontal flag succeeds on a real window.
    # Setup: create a target window inside the session.
    win = f"win-{os.getpid()}"
    assert tmux_newWindow(tmux_session, win) == 0
    # Test action: split horizontally.
    rc = tmux_splitWindow(f"{tmux_session}:{win}", "h")
    # Test verification: returns success.
    assert rc == 0


@pytest.mark.live
def test_splitWindow_vertical_succeeds(tmux_session):
    # Scenario: split_window with vertical flag succeeds on a real window.
    # Setup: create the target window.
    win = f"win-{os.getpid()}"
    assert tmux_newWindow(tmux_session, win) == 0
    # Test action: split vertically.
    rc = tmux_splitWindow(f"{tmux_session}:{win}", "v")
    # Test verification: returns success.
    assert rc == 0


@pytest.mark.live
def test_killWindow_removesWindow(tmux_session):
    # Scenario: kill_window removes a previously-created window.
    # Setup: create a window to be killed.
    win = f"win-{os.getpid()}"
    assert tmux_newWindow(tmux_session, win) == 0
    # Test action: kill that window.
    rc = tmux_killWindow(f"{tmux_session}:{win}")
    # Test verification: returns success.
    assert rc == 0


@pytest.mark.live
def test_listWindows_afterKill_backToOne(tmux_session):
    # Scenario: after creating then killing a window, the session has 1 window again.
    # Setup: create then kill an extra window.
    win = f"win-{os.getpid()}"
    assert tmux_newWindow(tmux_session, win) == 0
    assert tmux_killWindow(f"{tmux_session}:{win}") == 0
    # Test action: list windows.
    result = tmux_listWindows(tmux_session)
    # Test verification: exactly one non-empty line remains.
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1


@pytest.mark.live
def test_killWindow_nonexistent_fails(tmux_session):
    # Scenario: killing a window that does not exist returns nonzero.
    # Setup: target name that was never created.
    target = f"{tmux_session}:nosuch-{os.getpid()}"
    # Test action: attempt to kill the missing window.
    rc = tmux_killWindow(target)
    # Test verification: nonzero return code indicates failure.
    assert rc != 0


@pytest.mark.live
def test_newWindow_nonexistentSession_fails():
    # Scenario: creating a window in a session that doesn't exist fails.
    # Setup: session name that was never created.
    bogus = f"nonexistent-{os.getpid()}"
    _kill_session(bogus)
    # Test action: attempt to add a window to the missing session.
    rc = tmux_newWindow(bogus, "whatever")
    # Test verification: nonzero return code indicates failure.
    assert rc != 0
