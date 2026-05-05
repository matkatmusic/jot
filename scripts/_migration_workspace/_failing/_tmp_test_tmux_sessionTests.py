import sys
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
from jot_plugin_orchestrator import *

import os
import pytest


@pytest.fixture
def session_name():
    # Setup: unique session name keyed to pid; ensure it does not exist before/after.
    name = f"tmux-sh-test-{os.getpid()}"
    try:
        tmux_killSession(name)
    except Exception:
        pass
    yield name
    try:
        tmux_killSession(name)
    except Exception:
        pass


@pytest.mark.live
def test_hasSession_false_when_session_absent(session_name):
    # Scenario: tmux_hasSession returns falsy for a session that has never been created.
    # Setup: fixture guarantees session_name is not present.
    # Test action: query has-session.
    rc = tmux_hasSession(session_name)
    # Test verification: nonzero/falsy return code indicates absence.
    assert not rc


@pytest.mark.live
def test_newSession_creates_session(session_name):
    # Scenario: tmux_newSession successfully creates a fresh detached session.
    # Setup: fixture guarantees session_name is absent.
    # Test action: create the session.
    rc = tmux_newSession(session_name)
    # Test verification: success return code (0/truthy-success per invoke_command contract).
    assert rc == 0


@pytest.mark.live
def test_hasSession_true_after_creation(session_name):
    # Scenario: tmux_hasSession reports presence after newSession.
    # Setup: create the session.
    assert tmux_newSession(session_name) == 0
    # Test action: query has-session.
    rc = tmux_hasSession(session_name)
    # Test verification: zero return code indicates presence.
    assert rc == 0


@pytest.mark.live
def test_newSession_rejects_duplicate(session_name):
    # Scenario: creating a session that already exists must fail.
    # Setup: create session once.
    assert tmux_newSession(session_name) == 0
    # Test action: attempt to create again with the same name.
    rc = tmux_newSession(session_name)
    # Test verification: nonzero return code signals duplicate rejection.
    assert rc != 0


@pytest.mark.live
def test_killSession_removes_existing_session(session_name):
    # Scenario: tmux_killSession succeeds against a live session.
    # Setup: create the session.
    assert tmux_newSession(session_name) == 0
    # Test action: kill it.
    rc = tmux_killSession(session_name)
    # Test verification: success return code.
    assert rc == 0


@pytest.mark.live
def test_hasSession_false_after_kill(session_name):
    # Scenario: tmux_hasSession reports absence once the session is killed.
    # Setup: create then kill the session.
    assert tmux_newSession(session_name) == 0
    assert tmux_killSession(session_name) == 0
    # Test action: query has-session post-kill.
    rc = tmux_hasSession(session_name)
    # Test verification: nonzero/falsy result.
    assert not rc


@pytest.mark.live
def test_killSession_fails_on_nonexistent(session_name):
    # Scenario: killing a session that does not exist must fail.
    # Setup: fixture guarantees absence.
    # Test action: attempt to kill the missing session.
    rc = tmux_killSession(session_name)
    # Test verification: nonzero return code.
    assert rc != 0
