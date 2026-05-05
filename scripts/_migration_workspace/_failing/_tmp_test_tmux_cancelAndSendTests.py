import sys
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
from jot_plugin_orchestrator import *

import os
import time
import subprocess
import pytest


def _tmux(*args: str) -> subprocess.CompletedProcess:
    # Helper: invoke real tmux binary; used only by fixture lifecycle.
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


@pytest.fixture
def live_tmux_session():
    # Real tmux session fixture; yields session name, kills on teardown.
    name = f"tmux-py-cancel-test-{os.getpid()}-{int(time.time()*1000)}"
    _tmux("new-session", "-d", "-s", name, "-x", "200", "-y", "50")
    try:
        yield name
    finally:
        _tmux("kill-session", "-t", name)


@pytest.mark.live
def test_tmux_cancelAndSend_logs_label_after_cancellation(live_tmux_session):
    # Scenario: when a label is supplied, cancelAndSend emits a log line containing the label.
    # Setup: start a long-running sleep so Ctrl-C has something to cancel.
    session = live_tmux_session
    label = f"work-{os.getpid()}"
    tmux_sendAndSubmit(session, "sleep 10")
    time.sleep(0.2)

    # Test action: invoke cancelAndSend with label, capture returned log string.
    log = tmux_cancelAndSend(session, f"echo replaced-{os.getpid()}", label)

    # Test verification: log contains the label.
    assert label in log, f"label missing from log: {log!r}"


@pytest.mark.live
def test_tmux_cancelAndSend_actually_cancels_and_delivers_replacement(live_tmux_session):
    # Scenario: cancelAndSend interrupts the running sleep and the replacement command runs promptly.
    # Setup: start sleep 10; without working Ctrl-C the replacement echo would queue ~10s.
    session = live_tmux_session
    marker = f"replaced-{os.getpid()}"
    tmux_sendAndSubmit(session, "sleep 10")
    time.sleep(0.2)

    # Test action: cancel-and-send a replacement echo, then wait briefly for output.
    tmux_cancelAndSend(session, f"echo {marker}", f"work-{os.getpid()}")
    time.sleep(0.5)

    # Test verification: replacement marker visible in pane (proves sleep was killed).
    pane = tmux_capturePane(session)
    assert marker in pane, f"replacement text not visible; cancel may have failed: {pane!r}"


@pytest.mark.live
def test_tmux_cancelAndSend_stays_quiet_without_label(live_tmux_session):
    # Scenario: when no label is provided, cancelAndSend must not emit the 'cancelled in-progress' log line.
    # Setup: start a sleep so a real cancellation path is exercised.
    session = live_tmux_session
    tmux_sendAndSubmit(session, "sleep 10")
    time.sleep(0.2)

    # Test action: invoke cancelAndSend with no label argument.
    log = tmux_cancelAndSend(session, f"echo second-{os.getpid()}")

    # Test verification: log does not contain the 'cancelled in-progress' phrase.
    assert "cancelled in-progress" not in (log or ""), f"unexpected log emitted: {log!r}"


@pytest.mark.live
def test_tmux_cancelAndSend_delivers_replacement_without_label(live_tmux_session):
    # Scenario: replacement command is delivered to the pane even when label is omitted.
    # Setup: start sleep 10 to require cancellation before the echo can run.
    session = live_tmux_session
    marker = f"second-{os.getpid()}"
    tmux_sendAndSubmit(session, "sleep 10")
    time.sleep(0.2)

    # Test action: cancel-and-send with no label, wait for pane to settle.
    tmux_cancelAndSend(session, f"echo {marker}")
    time.sleep(0.5)

    # Test verification: marker text appears in pane capture.
    pane = tmux_capturePane(session)
    assert marker in pane, f"second replacement not visible: {pane!r}"
