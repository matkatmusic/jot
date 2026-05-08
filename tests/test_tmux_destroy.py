"""Tests for tmux_lib Destroy bucket: killSession, killPane, killWindow + live."""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from common.scripts import tmux_lib as _tmux_lib_mod
from common.scripts.tmux_lib import (
    tmux_killPane,
    tmux_killSession,
    tmux_killWindow,
    tmux_listPanes,
    tmux_newPane,
    tmux_newSession,
)

# Bind module alias used throughout the test bodies.
mod = _tmux_lib_mod


# === Bucket: Destroy ===

def _make_fake_run(rc: int, stdout: str = "", stderr: str = "", calls: list | None = None):
    """Builds a fake subprocess.run with controllable rc/stdout/stderr."""
    def _fake(cmd, *args, **kwargs):
        if calls is not None:
            calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=rc, stdout=stdout, stderr=stderr)
    return _fake


# --- tmux_killSession ---

def test_tmux_killSession_invokes_tmux_kill_session_with_dash_t_target(monkeypatch):
    # Scenario: caller passes a session name; function shells out to `tmux kill-session -t <name>`.
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action: invoke with a session name.
    tmux_killSession("my-sess")
    # Test verification: argv exactly matches.
    assert calls == [["tmux", "kill-session", "-t", "my-sess"]]


def test_tmux_killSession_returns_zero_on_success(monkeypatch):
    # Scenario: tmux exits 0; function returns 0.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0))
    # Test action + verification.
    assert tmux_killSession("any") == 0


def test_tmux_killSession_returns_nonzero_and_logs_caller_when_kill_fails(monkeypatch, capsys):
    # Scenario: tmux exits nonzero (e.g. session not found); function returns rc and logs caller-attributed stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="can't find session: ghost"))

    # Setup: invoke from a uniquely-named caller frame to assert sys._getframe(1) attribution.
    def caller_frame():
        return tmux_killSession("ghost")

    # Test action: invoke via the named frame.
    rc = caller_frame()
    err = capsys.readouterr().err
    # Test verification: rc propagated and stderr names caller + cmd + tmux text.
    assert rc == 1
    assert "caller_frame" in err
    assert "tmux kill-session -t ghost" in err
    assert "can't find session: ghost" in err


# --- tmux_killPane ---

def test_tmux_killPane_invokes_tmux_kill_pane_with_dash_t_target(monkeypatch):
    # Scenario: caller passes a pane target; function must shell out to `tmux kill-pane -t <target>`.
    calls: list = []
    # Setup: stub subprocess.run to capture argv.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action: invoke with a representative pane target.
    tmux_killPane("session:0.1")
    # Test verification: exact argv contract (program, subcommand, -t flag, target).
    assert calls == [["tmux", "kill-pane", "-t", "session:0.1"]]


def test_tmux_killPane_returns_zero_on_success(monkeypatch):
    # Scenario: tmux exits 0 -> function propagates 0.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0))
    # Test action + verification.
    assert tmux_killPane("any:0.0") == 0


def test_tmux_killPane_returns_nonzero_and_logs_caller_when_kill_fails(monkeypatch, capsys):
    # Scenario: tmux fails (no such pane); function returns rc and logs caller-attributed stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="can't find pane"))

    # Setup: invoke from a uniquely-named caller frame to assert sys._getframe(1) attribution.
    def caller_frame_marker():
        return tmux_killPane("missing:9.9")

    # Test action.
    rc = caller_frame_marker()
    err = capsys.readouterr().err
    # Test verification: rc propagated; stderr names caller + cmd + tmux's stderr text.
    assert rc == 1
    assert "[caller_frame_marker]" in err
    assert "tmux kill-pane -t missing:9.9" in err
    assert "can't find pane" in err


# --- tmux_killWindow ---

def test_tmux_killWindow_invokes_tmux_kill_window_with_dash_t_target(monkeypatch):
    # Scenario: caller passes a window target; tmux receives kill-window with -t target.
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action.
    tmux_killWindow("session:1")
    # Test verification: exact argv shape.
    assert calls == [["tmux", "kill-window", "-t", "session:1"]]


def test_tmux_killWindow_returns_zero_on_success(monkeypatch):
    # Scenario: tmux exits 0; helper returns 0.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0))
    # Test action + verification.
    assert tmux_killWindow("session:1") == 0


def test_tmux_killWindow_returns_nonzero_and_logs_caller_when_window_missing(monkeypatch, capsys):
    # Scenario: tmux fails (window absent); helper returns rc and logs caller-attributed stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="can't find window: ghost\n"))
    # Test action: invoke directly from this test so caller name = test's name.
    rc = tmux_killWindow("ghost")
    err = capsys.readouterr().err
    # Test verification: rc propagates; stderr has caller name + cmd + tmux message.
    assert rc == 1
    assert "test_tmux_killWindow_returns_nonzero_and_logs_caller_when_window_missing" in err
    assert "tmux kill-window -t ghost" in err
    assert "can't find window: ghost" in err


# === Bucket: Destroy [live] ===

# Skip the whole module if tmux is unavailable on this host.
pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not installed"
)


# Real-tmux fixture: does NOT pre-create a session - session tests manage lifecycle themselves.
@pytest.fixture
def session_name():
    name = f"tmux-py-session-test-{os.getpid()}"
    tmux_killSession(name)  # Setup: clear any stale session from a prior run
    yield name
    tmux_killSession(name)  # Teardown: clean up in case the test left one behind


@pytest.mark.live
def test_killSession_fails_onNonexistentSession(session_name):
    # Scenario: killSession returns nonzero rc when the session does not exist.
    # Setup: fixture guarantees no session by this name exists.
    # Test action: attempt to kill a session that was never created.
    rc = tmux_killSession(session_name)
    # Test verification: nonzero rc means kill rejected.
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


# Real-tmux fixture: creates a detached session, yields its name, kills on teardown.
@pytest.fixture
def tmux_session_panes():
    name = f"tmux-py-pane-test-{os.getpid()}"
    tmux_killSession(name)  # Setup: ensure no stale session of the same name
    rc = tmux_newSession(name)
    assert rc == 0, "fixture precondition: new session must succeed"
    yield name
    tmux_killSession(name)


@pytest.mark.live
def test_killPane_removesLivePane(tmux_session_panes):
    # Scenario: kill_pane on the second live pane returns rc 0.
    # Setup: ensure two panes exist; capture id of the second pane.
    assert tmux_newPane(tmux_session_panes) == 0
    ids = tmux_listPanes(tmux_session_panes, "-F", "#{pane_id}")
    assert len(ids) >= 2, "precondition: need at least 2 panes"
    second_id = ids[1]
    # Test action: kill the second pane.
    rc = tmux_killPane(second_id)
    # Test verification: rc 0.
    assert rc == 0


@pytest.mark.live
def test_killPane_failsOnNonexistentTarget():
    # Scenario: kill_pane on a nonexistent target returns nonzero rc.
    # Setup: bogus target name.
    bogus = f"nonexistent-{os.getpid()}"
    # Test action: attempt kill.
    rc = tmux_killPane(bogus)
    # Test verification: nonzero rc.
    assert rc != 0
