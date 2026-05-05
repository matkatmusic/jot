import sys
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
from jot_plugin_orchestrator import *

import os
import pytest


@pytest.fixture
def layout_session():
    # Setup: create real detached tmux session with 3 panes for layout exercises.
    name = f"tmux-py-lay-test-{os.getpid()}"
    tmux_newSession(name)
    tmux_newPane(name)
    tmux_newPane(name)
    yield name
    # Teardown: best-effort kill regardless of test outcome.
    tmux_killSession(name)


@pytest.mark.live
def test_selectLayout_tiled_succeeds(layout_session):
    # Scenario: tmux_selectLayout returns 0 when applying the tiled layout to a real session.
    # Setup: live session created by fixture.
    # Test action: invoke selectLayout with "tiled".
    rc = tmux_selectLayout(layout_session, "tiled")
    # Test verification: rc must be 0 (success).
    assert rc == 0


@pytest.mark.live
def test_selectLayout_evenHorizontal_succeeds(layout_session):
    # Scenario: tmux_selectLayout returns 0 for the even-horizontal preset.
    # Setup: live session from fixture.
    # Test action: invoke selectLayout with "even-horizontal".
    rc = tmux_selectLayout(layout_session, "even-horizontal")
    # Test verification: rc must be 0.
    assert rc == 0


@pytest.mark.live
def test_selectLayout_invalidName_fails(layout_session):
    # Scenario: tmux_selectLayout returns nonzero when given an unknown layout name.
    # Setup: live session from fixture.
    # Test action: invoke selectLayout with bogus layout id.
    rc = tmux_selectLayout(layout_session, "not-a-layout")
    # Test verification: rc must be nonzero (failure).
    assert rc != 0


@pytest.mark.live
def test_retile_succeeds(layout_session):
    # Scenario: tmux_retile returns 0 on a valid live session target.
    # Setup: live session from fixture.
    # Test action: invoke retile.
    rc = tmux_retile(layout_session)
    # Test verification: rc must be 0.
    assert rc == 0


@pytest.mark.live
def test_retile_nonexistentTarget_fails():
    # Scenario: tmux_retile returns nonzero when target session does not exist.
    # Setup: synthesize a name guaranteed not to exist.
    bogus = f"nonexistent-{os.getpid()}-xyz"
    # Test action: invoke retile against bogus target.
    rc = tmux_retile(bogus)
    # Test verification: rc must be nonzero.
    assert rc != 0
