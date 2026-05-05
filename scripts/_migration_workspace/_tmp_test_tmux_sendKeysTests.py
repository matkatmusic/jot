import sys
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
from jot_plugin_orchestrator import *

import os
import time
import pytest


@pytest.fixture
def live_tmux_session():
    # Setup: create a unique detached tmux session for the test, yield its name, then tear down.
    session = f"tmux-sh-send-test-{os.getpid()}-{time.time_ns()}"
    rc = tmux_newSession(session)
    if rc != 0:
        pytest.skip("tmux_newSession failed; tmux likely unavailable")
    try:
        yield session
    finally:
        tmux_killSession(session)


@pytest.mark.live
def test_sendKeys_returnsZero_onLiveSession(live_tmux_session):
    # Scenario: tmux_sendKeys delivers literal text to a live pane and returns rc=0.
    # Setup: live session created by fixture; build a unique marker.
    marker = f"marker-{os.getpid()}"
    # Test action: send the marker as keystrokes (no Enter).
    rc = tmux_sendKeys(live_tmux_session, marker)
    # Test verification: send-keys succeeded.
    assert rc == 0


@pytest.mark.live
def test_sendKeys_textVisible_inPaneCapture(live_tmux_session):
    # Scenario: text sent via tmux_sendKeys is observable via tmux_capturePane.
    # Setup: send a unique marker into the pane.
    marker = f"marker-{os.getpid()}-visible"
    assert tmux_sendKeys(live_tmux_session, marker) == 0
    time.sleep(0.1)
    # Test action: capture the pane contents.
    captured = tmux_capturePane(live_tmux_session)
    # Test verification: pane capture contains the literal marker text.
    assert marker in captured


@pytest.mark.live
def test_sendCtrlC_returnsZero_onLiveSession(live_tmux_session):
    # Scenario: tmux_sendCtrlC sends a C-c token to a live pane and returns rc=0.
    # Setup: send pending text into the pane first.
    tmux_sendKeys(live_tmux_session, "junk-text")
    # Test action: send Ctrl-C to clear it.
    rc = tmux_sendCtrlC(live_tmux_session)
    # Test verification: send-keys C-c succeeded.
    assert rc == 0


@pytest.mark.live
def test_sendEnter_returnsZero_onLiveSession(live_tmux_session):
    # Scenario: tmux_sendEnter delivers Enter token and returns rc=0.
    # Setup: live session from fixture.
    # Test action: send Enter.
    rc = tmux_sendEnter(live_tmux_session)
    # Test verification: rc=0.
    assert rc == 0


@pytest.mark.live
def test_sendAndSubmit_returnsZero_onLiveSession(live_tmux_session):
    # Scenario: tmux_sendAndSubmit runs an echo command and returns rc=0.
    # Setup: live session from fixture; build unique echo payload.
    payload = f"submit-{os.getpid()}"
    # Test action: send the echo command and submit it.
    rc = tmux_sendAndSubmit(live_tmux_session, f"echo {payload}")
    # Test verification: composite call succeeded.
    assert rc == 0


@pytest.mark.live
def test_sendAndSubmit_outputVisible_inPaneCapture(live_tmux_session):
    # Scenario: shell output of submitted echo appears in pane capture.
    # Setup: submit an echo with a unique payload.
    payload = f"submit-{os.getpid()}-vis"
    assert tmux_sendAndSubmit(live_tmux_session, f"echo {payload}") == 0
    time.sleep(0.3)
    # Test action: capture the pane.
    captured = tmux_capturePane(live_tmux_session)
    # Test verification: pane shows the echoed payload (shell executed it).
    assert payload in captured


def test_sendKeys_returnsNonzero_onNonexistentTarget():
    # Scenario: tmux_sendKeys against an absent session returns nonzero rc.
    # Setup: build a name guaranteed not to exist.
    bogus = f"nonexistent-{os.getpid()}-{time.time_ns()}"
    # Test action: attempt send-keys.
    rc = tmux_sendKeys(bogus, "text")
    # Test verification: rc is nonzero (failure).
    assert rc != 0


def test_sendEnter_returnsNonzero_onNonexistentTarget():
    # Scenario: tmux_sendEnter against an absent session returns nonzero rc.
    # Setup: build a name guaranteed not to exist.
    bogus = f"nonexistent-{os.getpid()}-{time.time_ns()}"
    # Test action: attempt send-keys Enter.
    rc = tmux_sendEnter(bogus)
    # Test verification: rc is nonzero (failure).
    assert rc != 0
