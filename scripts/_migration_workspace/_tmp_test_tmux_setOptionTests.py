import sys
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
from jot_plugin_orchestrator import *

import os
import shutil
import subprocess
import pytest


# Skip the whole module if tmux is unavailable on this host.
pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not installed"
)


@pytest.fixture
def tmux_session():
    # Provide a unique, isolated tmux session for one test; tear it down on exit.
    name = f"tmux-py-opt-test-{os.getpid()}"
    subprocess.run(["tmux", "kill-session", "-t", name],
                   capture_output=True, check=False)
    rc = tmux_newSession(name)
    assert rc == 0, "fixture failed to create tmux session"
    yield name
    subprocess.run(["tmux", "kill-session", "-t", name],
                   capture_output=True, check=False)


@pytest.mark.live
def test_setOptionForTarget_accepts_valid_session_option(tmux_session):
    # Scenario: setting a real session-scoped option on a live session returns rc=0.
    # Setup: tmux_session fixture provides a fresh detached session.
    session = tmux_session
    # Test action: set the session-scoped `remain-on-exit` option to `off`.
    rc = tmux_setOptionForTarget(session, "remain-on-exit", "off")
    # Test verification: tmux accepted it; rc must be 0.
    assert rc == 0


@pytest.mark.live
def test_setOptionForTarget_rejects_invalid_option(tmux_session, capfd):
    # Scenario: setting an unknown option name on a live session returns nonzero.
    # Setup: live session from fixture.
    session = tmux_session
    # Test action: attempt to set a fabricated option name.
    rc = tmux_setOptionForTarget(session, "not-a-real-option", "foo")
    # Test verification: tmux rejects unknown option; rc nonzero.
    assert rc != 0
    capfd.readouterr()  # drain caller-attributed stderr from helper


@pytest.mark.live
def test_setOptionForTarget_rejects_nonexistent_target(capfd):
    # Scenario: targeting a session that does not exist returns nonzero.
    # Setup: build a name guaranteed not to exist.
    bogus = f"nonexistent-{os.getpid()}"
    subprocess.run(["tmux", "kill-session", "-t", bogus],
                   capture_output=True, check=False)
    # Test action: try to set `mouse on` against the nonexistent session.
    rc = tmux_setOptionForTarget(bogus, "mouse", "on")
    # Test verification: tmux rejects unknown target; rc nonzero.
    assert rc != 0
    capfd.readouterr()


@pytest.mark.live
def test_setOptionGlobally_accepts_valid_global_option():
    # Scenario: setting a global option to its current value succeeds (no-op).
    # Setup: read the current global `mouse` value so we can rewrite it identically.
    proc = subprocess.run(
        ["tmux", "show-options", "-gv", "mouse"],
        capture_output=True, text=True, check=False,
    )
    current = (proc.stdout or "").strip() or "off"
    # Test action: set the global `mouse` option back to the captured value.
    rc = tmux_setOptionGlobally("mouse", current)
    # Test verification: rc must be 0.
    assert rc == 0


@pytest.mark.live
def test_setOptionGlobally_rejects_invalid_option(capfd):
    # Scenario: setting a fabricated global option fails.
    # Setup: no fixture state needed (global scope).
    # Test action: attempt to set an unknown option name globally.
    rc = tmux_setOptionGlobally("not-a-real-option", "foo")
    # Test verification: rc nonzero.
    assert rc != 0
    capfd.readouterr()


@pytest.mark.live
def test_setOptionForWindow_accepts_valid_window_option(tmux_session):
    # Scenario: setting a window-scoped option on a real window succeeds.
    # Setup: create a named window inside the fixture session.
    session = tmux_session
    win = f"optwin-{os.getpid()}"
    rc_new = tmux_newWindow(session, win)
    assert rc_new == 0, "precondition: tmux_newWindow should succeed"
    # Test action: set `aggressive-resize on` on the new window.
    rc = tmux_setOptionForWindow(f"{session}:{win}", "aggressive-resize", "on")
    # Test verification: tmux accepted it; rc must be 0.
    assert rc == 0


@pytest.mark.live
def test_setOptionForWindow_rejects_nonexistent_window(tmux_session, capfd):
    # Scenario: setting a window option against a missing window fails.
    # Setup: live session exists, but target window does not.
    session = tmux_session
    bogus_win = f"nosuch-{os.getpid()}"
    # Test action: attempt to set the option against the absent window.
    rc = tmux_setOptionForWindow(f"{session}:{bogus_win}", "aggressive-resize", "on")
    # Test verification: rc nonzero.
    assert rc != 0
    capfd.readouterr()
