import sys
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
from jot_plugin_orchestrator import *

import os
import time
import pytest


# Real-tmux fixture: creates a detached session, yields its name, kills on teardown.
# Marked `live` because it spawns an actual tmux server.
@pytest.fixture
def tmux_session():
    name = f"tmux-py-cancel-and-send-{os.getpid()}"
    tmux_killSession(name)  # Setup: ensure no stale session of the same name
    rc = tmux_newSession(name)
    assert rc == 0, "fixture precondition: new session must succeed"
    yield name
    tmux_killSession(name)


@pytest.mark.live
def test_cancelAndSend_withLabel_logsLabel(tmux_session):
    # Scenario: tmux_cancelAndSend with a label includes that label in its return value.
    # Setup: start a blocking command so Ctrl-C has something to cancel.
    tmux_sendKeys(tmux_session, "sleep 10")
    tmux_sendEnter(tmux_session)
    time.sleep(0.2)
    label = f"work-{os.getpid()}"
    # Test action: cancel and send a replacement command with a label.
    log = tmux_cancelAndSend(tmux_session, f"echo replaced-{os.getpid()}", label)
    # Test verification: log string contains the label we passed.
    assert label in log


@pytest.mark.live
def test_cancelAndSend_withLabel_replacementRunsAfterCancel(tmux_session):
    # Scenario: The replacement command appears in pane output, proving sleep was cancelled.
    # Setup: start sleep 10 and cancel it via tmux_cancelAndSend.
    tag = f"replaced-{os.getpid()}"
    tmux_sendKeys(tmux_session, "sleep 10")
    tmux_sendEnter(tmux_session)
    time.sleep(0.2)
    tmux_cancelAndSend(tmux_session, f"echo {tag}", f"work-{os.getpid()}")
    time.sleep(0.5)
    # Test action: capture pane content.
    content = tmux_capturePane(tmux_session)
    # Test verification: replacement text visible (fast arrival proves sleep was cancelled).
    assert tag in content


@pytest.mark.live
def test_cancelAndSend_withoutLabel_logsNothing(tmux_session):
    # Scenario: tmux_cancelAndSend called without a label does not log a cancellation line.
    # Setup: start sleep 10.
    tmux_sendKeys(tmux_session, "sleep 10")
    tmux_sendEnter(tmux_session)
    time.sleep(0.2)
    # Test action: cancel without passing a label.
    log = tmux_cancelAndSend(tmux_session, f"echo second-{os.getpid()}")
    # Test verification: no "cancelled in-progress" text in returned log.
    assert "cancelled in-progress" not in log


@pytest.mark.live
def test_cancelAndSend_withoutLabel_replacementRunsAfterCancel(tmux_session):
    # Scenario: Replacement command appears in pane output even when no label is given.
    # Setup: start sleep 10, cancel without label.
    tag = f"second-{os.getpid()}"
    tmux_sendKeys(tmux_session, "sleep 10")
    tmux_sendEnter(tmux_session)
    time.sleep(0.2)
    tmux_cancelAndSend(tmux_session, f"echo {tag}")
    time.sleep(0.5)
    # Test action: capture pane content.
    content = tmux_capturePane(tmux_session)
    # Test verification: replacement text visible.
    assert tag in content
