import sys
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
from jot_plugin_orchestrator import *

import os
import pytest


# Real-tmux fixture: does NOT pre-create a session - session tests manage lifecycle themselves.
# Yields a unique session name; kills any stale session with that name before and after.
@pytest.fixture
def session_name():
    name = f"tmux-py-session-test-{os.getpid()}"
    tmux_killSession(name)  # Setup: clear any stale session from a prior run
    yield name
    tmux_killSession(name)  # Teardown: clean up in case the test left one behind


@pytest.mark.live
def test_hasSession_returnsFalse_forNonexistentSession(session_name):
    # Scenario: hasSession returns nonzero rc when the session does not exist.
    # Setup: fixture guarantees no session by this name exists.
    # Test action: check for a session that was never created.
    rc = tmux_hasSession(session_name)
    # Test verification: nonzero rc means session absent.
    assert rc != 0


@pytest.mark.live
def test_newSession_createsSession(session_name):
    # Scenario: newSession returns rc 0 and the session becomes reachable.
    # Setup: no pre-existing session (fixture guarantees this).
    # Test action: create the session.
    rc = tmux_newSession(session_name)
    # Test verification: rc 0 means tmux accepted the create.
    assert rc == 0


@pytest.mark.live
def test_hasSession_returnsTrue_forExistingSession(session_name):
    # Scenario: hasSession returns rc 0 after newSession succeeds.
    # Setup: create the session first.
    assert tmux_newSession(session_name) == 0
    # Test action: check for the session that now exists.
    rc = tmux_hasSession(session_name)
    # Test verification: rc 0 means session present.
    assert rc == 0


@pytest.mark.live
def test_newSession_rejectsDuplicate(session_name):
    # Scenario: newSession on an already-existing session returns nonzero rc.
    # Setup: create the session once.
    assert tmux_newSession(session_name) == 0
    # Test action: attempt to create the same session again.
    rc = tmux_newSession(session_name)
    # Test verification: nonzero rc means tmux rejected the duplicate.
    assert rc != 0


@pytest.mark.live
def test_killSession_succeeds_onExistingSession(session_name):
    # Scenario: killSession returns rc 0 when the session exists.
    # Setup: create the session.
    assert tmux_newSession(session_name) == 0
    # Test action: kill it.
    rc = tmux_killSession(session_name)
    # Test verification: rc 0 means kill accepted.
    assert rc == 0


@pytest.mark.live
def test_hasSession_returnsFalse_afterKill(session_name):
    # Scenario: hasSession returns nonzero rc after the session has been killed.
    # Setup: create then kill the session.
    assert tmux_newSession(session_name) == 0
    assert tmux_killSession(session_name) == 0
    # Test action: check for the session that no longer exists.
    rc = tmux_hasSession(session_name)
    # Test verification: nonzero rc means session is gone.
    assert rc != 0


@pytest.mark.live
def test_killSession_fails_onNonexistentSession(session_name):
    # Scenario: killSession returns nonzero rc when the session does not exist.
    # Setup: fixture guarantees no session by this name exists.
    # Test action: attempt to kill a session that was never created.
    rc = tmux_killSession(session_name)
    # Test verification: nonzero rc means kill rejected.
    assert rc != 0
