import sys
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
from jot_plugin_orchestrator import *

import os
import pytest


# Real-tmux fixture: creates a detached session, yields its name, kills on teardown.
# Marked `live` because it spawns an actual tmux server.
@pytest.fixture
def tmux_session():
    name = f"tmux-py-pane-test-{os.getpid()}"
    tmux_killSession(name)  # Setup: ensure no stale session of the same name
    rc = tmux_newSession(name)
    assert rc == 0, "fixture precondition: new session must succeed"
    yield name
    tmux_killSession(name)


def _first_pane_id(session: str) -> str:
    # Helper: returns the first pane id (e.g. "%0") in the session.
    rows = tmux_listPanes(session, "-F", "#{pane_id}")
    return rows[0] if rows else ""


@pytest.mark.live
def test_listPanes_newSession_hasOnePane(tmux_session):
    # Scenario: A freshly created session contains exactly one pane.
    # Setup: fixture created the session.
    # Test action: list panes.
    panes = tmux_listPanes(tmux_session)
    # Test verification: exactly one pane reported.
    assert len(panes) == 1


@pytest.mark.live
def test_newPane_addsPaneToSession(tmux_session):
    # Scenario: tmux_newPane on an existing session succeeds (rc=0).
    # Setup: session exists via fixture.
    # Test action: split a new pane.
    rc = tmux_newPane(tmux_session)
    # Test verification: rc 0 means tmux accepted the split.
    assert rc == 0


@pytest.mark.live
def test_listPanes_afterNewPane_hasTwoPanes(tmux_session):
    # Scenario: After splitting once, list_panes reports two panes.
    # Setup: session + one extra pane.
    assert tmux_newPane(tmux_session) == 0
    # Test action: list panes.
    panes = tmux_listPanes(tmux_session)
    # Test verification: two panes present.
    assert len(panes) == 2


@pytest.mark.live
def test_selectPane_byKnownPaneId_succeeds(tmux_session):
    # Scenario: select_pane targets an existing pane id and succeeds.
    # Setup: capture id of the only pane.
    pid = _first_pane_id(tmux_session)
    assert pid, "precondition: a pane id must exist"
    # Test action: select that pane.
    rc = tmux_selectPane(pid)
    # Test verification: rc 0.
    assert rc == 0


@pytest.mark.live
def test_setPaneTitle_succeeds(tmux_session):
    # Scenario: set_pane_title returns rc 0 on a known pane.
    # Setup: known pane id.
    pid = _first_pane_id(tmux_session)
    # Test action: set a title.
    rc = tmux_setPaneTitle(pid, f"titletest-{os.getpid()}")
    # Test verification: rc 0.
    assert rc == 0


@pytest.mark.live
def test_setPaneTitle_roundTripsThroughListPanes(tmux_session):
    # Scenario: Title set via setPaneTitle is visible via listPanes default -F.
    # Setup: pid + unique title.
    pid = _first_pane_id(tmux_session)
    title = f"titletest-{os.getpid()}"
    assert tmux_setPaneTitle(pid, title) == 0
    # Test action: list panes (default format includes pane_title).
    rows = tmux_listPanes(tmux_session)
    # Test verification: at least one row contains the new title.
    assert any(title in row for row in rows)


@pytest.mark.live
def test_capturePane_returnsContent(tmux_session):
    # Scenario: capture_pane succeeds on a live pane (returns string, possibly empty).
    # Setup: known pane id.
    pid = _first_pane_id(tmux_session)
    # Test action: capture pane content.
    captured = tmux_capturePane(pid)
    # Test verification: returns a str (capture succeeded; bash test only checked rc=0).
    assert isinstance(captured, str)


@pytest.mark.live
def test_newPane_failsOnNonexistentSession():
    # Scenario: new_pane on a session that does not exist returns nonzero rc.
    # Setup: a name that is not a live session.
    bogus = f"nonexistent-{os.getpid()}"
    # Test action: attempt split on bogus target.
    rc = tmux_newPane(bogus)
    # Test verification: nonzero rc indicates failure.
    assert rc != 0


@pytest.mark.live
def test_selectPane_failsOnNonexistentTarget():
    # Scenario: select_pane on a nonexistent target returns nonzero rc.
    # Setup: bogus target name.
    bogus = f"nonexistent-{os.getpid()}"
    # Test action: attempt select.
    rc = tmux_selectPane(bogus)
    # Test verification: nonzero rc.
    assert rc != 0


@pytest.mark.live
def test_killPane_removesLivePane(tmux_session):
    # Scenario: kill_pane on the second live pane returns rc 0.
    # Setup: ensure two panes exist; capture id of the second pane.
    assert tmux_newPane(tmux_session) == 0
    ids = tmux_listPanes(tmux_session, "-F", "#{pane_id}")
    assert len(ids) >= 2, "precondition: need at least 2 panes"
    second_id = ids[1]
    # Test action: kill the second pane.
    rc = tmux_killPane(second_id)
    # Test verification: rc 0.
    assert rc == 0


@pytest.mark.live
def test_listPanes_afterKillPane_hasOnePane(tmux_session):
    # Scenario: After killing the added pane, listPanes reports one pane.
    # Setup: add then kill the second pane.
    assert tmux_newPane(tmux_session) == 0
    ids = tmux_listPanes(tmux_session, "-F", "#{pane_id}")
    assert tmux_killPane(ids[1]) == 0
    # Test action: list panes.
    rows = tmux_listPanes(tmux_session)
    # Test verification: down to one pane.
    assert len(rows) == 1


@pytest.mark.live
def test_killPane_failsOnNonexistentTarget():
    # Scenario: kill_pane on a nonexistent target returns nonzero rc.
    # Setup: bogus target name.
    bogus = f"nonexistent-{os.getpid()}"
    # Test action: attempt kill.
    rc = tmux_killPane(bogus)
    # Test verification: nonzero rc.
    assert rc != 0
