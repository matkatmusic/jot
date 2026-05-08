"""Tests for tmux_lib Communicate bucket: sendKeys, sendEnter, sendCtrlC,
sendAndSubmit, cancelAndSend + live."""
from __future__ import annotations

import os
import shutil
import subprocess
import time

import pytest

from common.scripts import tmux_lib as _tmux_lib_mod
from common.scripts.tmux_lib import (
    tmux_cancelAndSend,
    tmux_capturePane,
    tmux_killSession,
    tmux_newSession,
    tmux_sendAndSubmit,
    tmux_sendCtrlC,
    tmux_sendEnter,
    tmux_sendKeys,
)

# Bind module alias used throughout the test bodies.
mod = _tmux_lib_mod


# === Bucket: Communicate ===

def _make_fake_run(rc: int, stdout: str = "", stderr: str = "", calls: list | None = None):
    """Builds a fake subprocess.run with controllable rc/stdout/stderr."""
    def _fake(cmd, *args, **kwargs):
        if calls is not None:
            calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=rc, stdout=stdout, stderr=stderr)
    return _fake


# --- tmux_sendKeys ---

def test_tmux_sendKeys_invokes_tmux_send_keys_with_dash_t_target_then_text(monkeypatch):
    # Scenario: argv must be ["tmux","send-keys","-t",<target>,<text>] in order.
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action.
    tmux_sendKeys("session:0.1", "ls")
    # Test verification.
    assert calls == [["tmux", "send-keys", "-t", "session:0.1", "ls"]]


def test_tmux_sendKeys_returns_zero_on_success(monkeypatch):
    # Scenario: tmux exits 0 -> function returns 0.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0))
    # Test action + verification.
    assert tmux_sendKeys("sess:0", "echo hi") == 0


def test_tmux_sendKeys_returns_nonzero_and_logs_caller_when_target_missing(monkeypatch, capsys):
    # Scenario: missing pane target -> tmux exits nonzero, wrapper returns rc and logs caller name.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="can't find pane: nope"))
    # Test action.
    rc = tmux_sendKeys("nope", "ls")
    err = capsys.readouterr().err
    # Test verification.
    assert rc == 1
    assert "test_tmux_sendKeys_returns_nonzero_and_logs_caller_when_target_missing" in err
    assert "can't find pane: nope" in err


def test_tmux_sendKeys_passes_text_with_special_chars_unchanged(monkeypatch):
    # Scenario: shell metacharacters in text must pass verbatim (no shell interpolation).
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    payload = "hello world; echo 'hi'"
    # Test action.
    tmux_sendKeys("s:0.0", payload)
    # Test verification: text arrived unchanged at argv[4].
    assert calls[0][4] == payload
    assert calls == [["tmux", "send-keys", "-t", "s:0.0", payload]]


# --- tmux_sendEnter ---

def test_tmux_sendEnter_invokes_tmux_send_keys_with_dash_t_target_and_literal_Enter_token(monkeypatch):
    # Scenario: subprocess.run must receive `tmux send-keys -t <target> Enter`.
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action.
    tmux_sendEnter("session:0.1")
    # Test verification: argv shape with literal "Enter" token.
    assert calls == [["tmux", "send-keys", "-t", "session:0.1", "Enter"]]


def test_tmux_sendEnter_returns_zero_on_success(monkeypatch):
    # Scenario: rc=0 propagates.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0))
    # Test action + verification.
    assert tmux_sendEnter("session:0.0") == 0


def test_tmux_sendEnter_returns_nonzero_and_logs_caller_when_target_missing(monkeypatch, capsys):
    # Scenario: tmux fails (missing pane); function returns rc and logs caller-attributed stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="can't find pane"))

    # Setup: named caller frame.
    def outer_caller():
        return tmux_sendEnter("nope:9.9")

    # Test action.
    rc = outer_caller()
    err = capsys.readouterr().err
    # Test verification.
    assert rc == 1
    assert "[outer_caller]" in err
    assert "tmux send-keys -t nope:9.9 Enter" in err
    assert "can't find pane" in err


# --- tmux_sendCtrlC ---

def test_tmux_sendCtrlC_invokes_tmux_send_keys_with_dash_t_target_and_literal_C_dash_c_token(monkeypatch):
    # Scenario: subprocess.run must receive `tmux send-keys -t <target> C-c` verbatim (NOT translated to \x03).
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action.
    tmux_sendCtrlC("mySession:0.1")
    # Test verification: literal "C-c" token preserved.
    assert calls == [["tmux", "send-keys", "-t", "mySession:0.1", "C-c"]]


def test_tmux_sendCtrlC_returns_zero_on_success(monkeypatch):
    # Scenario: rc=0 propagates.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0))
    # Test action + verification.
    assert tmux_sendCtrlC("any:0") == 0


def test_tmux_sendCtrlC_returns_nonzero_and_logs_caller_when_target_missing(monkeypatch, capsys):
    # Scenario: target pane absent; tmux exits nonzero. Function returns rc and logs caller-attributed stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="can't find pane: ghost"))

    # Setup: named caller frame.
    def caller_frame_under_test():
        return tmux_sendCtrlC("ghost:0")

    # Test action.
    rc = caller_frame_under_test()
    err = capsys.readouterr().err
    # Test verification.
    assert rc == 1
    assert "caller_frame_under_test" in err
    assert "tmux send-keys -t ghost:0 C-c" in err
    assert "can't find pane: ghost" in err


# --- tmux_sendAndSubmit ---


def test_tmux_sendAndSubmit_calls_sendKeys_then_sendEnter_with_same_target(monkeypatch):
    # Scenario: both callees receive the same pane_target, in order sendKeys -> sendEnter.
    calls = []
    # Setup: stub sendKeys to record invocation and succeed.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendKeys",
                        lambda p, t: calls.append(("sendKeys", p, t)) or 0)
    # Setup: stub sendEnter to record invocation and succeed.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendEnter",
                        lambda p: calls.append(("sendEnter", p)) or 0)
    # Setup: stub sleep to avoid real delay.
    monkeypatch.setattr("time.sleep", lambda s: None)
    # Test action.
    tmux_sendAndSubmit("sess:0.1", "hello")
    # Test verification: order and shared pane_target.
    assert calls == [("sendKeys", "sess:0.1", "hello"), ("sendEnter", "sess:0.1")]


def test_tmux_sendAndSubmit_returns_zero_when_both_sends_succeed(monkeypatch):
    # Scenario: both sub-calls return 0; function returns 0.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendKeys", lambda p, t: 0)
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendEnter", lambda p: 0)
    monkeypatch.setattr("time.sleep", lambda s: None)
    # Test action + verification: rc 0 on full success.
    assert tmux_sendAndSubmit("p", "x") == 0


def test_tmux_sendAndSubmit_short_circuits_when_sendKeys_fails(monkeypatch):
    # Scenario: sendKeys fails -> return its rc, sendEnter never called.
    enter_calls = []
    # Setup: sendKeys returns failure rc 7.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendKeys", lambda p, t: 7)
    # Setup: sendEnter records if called (it must not be).
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendEnter",
                        lambda p: enter_calls.append(p) or 0)
    monkeypatch.setattr("time.sleep", lambda s: None)
    # Test action.
    rc = tmux_sendAndSubmit("p", "x")
    # Test verification: short-circuit rc propagation.
    assert rc == 7
    # Test verification: sendEnter was skipped.
    assert enter_calls == []


def test_tmux_sendAndSubmit_returns_sendEnter_rc_when_only_sendEnter_fails(monkeypatch):
    # Scenario: sendKeys ok, sendEnter fails -> return sendEnter's rc.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendKeys", lambda p, t: 0)
    # Setup: sendEnter returns failure rc 3.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendEnter", lambda p: 3)
    monkeypatch.setattr("time.sleep", lambda s: None)
    # Test action + verification: rc equals sendEnter's rc.
    assert tmux_sendAndSubmit("p", "x") == 3


def test_tmux_sendAndSubmit_sleeps_between_sendKeys_and_sendEnter(monkeypatch):
    # Scenario: time.sleep is invoked after sendKeys and before sendEnter, with duration 0.5.
    events = []
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendKeys",
                        lambda p, t: events.append("sendKeys") or 0)
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendEnter",
                        lambda p: events.append("sendEnter") or 0)
    monkeypatch.setattr("time.sleep",
                        lambda s: events.append(("sleep", s)))
    # Test action.
    tmux_sendAndSubmit("p", "x")
    # Test verification: sleep occurred strictly between the two sends with 0.5s duration.
    assert events == ["sendKeys", ("sleep", 0.5), "sendEnter"]


# --- tmux_cancelAndSend ---


def test_tmux_cancelAndSend_stops_retrying_once_marker_seen(monkeypatch):
    # Scenario: marker visible on second capture; loop stops after 2 Ctrl-Cs and replacement submits.
    captures = ["nothing yet", "interrupted by Ctrl-C now"]
    cap_iter = iter(captures)
    ctrlc_calls = []
    submit_calls = []
    # Setup: stub Ctrl-C, capture, submit, sleep.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendCtrlC",
                        lambda p: ctrlc_calls.append(p) or 0)
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane",
                        lambda p, scrollback_lines=None: next(cap_iter))
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendAndSubmit",
                        lambda p, t: submit_calls.append((p, t)) or 0)
    monkeypatch.setattr("time.sleep", lambda s: None)
    # Test action.
    rc = tmux_cancelAndSend("pane0", "echo replaced", "work-1")
    # Test verification: 2 Ctrl-Cs + 1 submit + rc 0.
    assert rc == 0
    assert ctrlc_calls == ["pane0", "pane0"]
    assert submit_calls == [("pane0", "echo replaced")]


def test_tmux_cancelAndSend_caps_at_five_attempts_and_still_submits(monkeypatch):
    # Scenario: marker never appears; loop caps at 5 Ctrl-Cs, replacement still forwarded.
    ctrlc_calls = []
    submit_calls = []
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendCtrlC",
                        lambda p: ctrlc_calls.append(p) or 0)
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane",
                        lambda p, scrollback_lines=None: "busy")
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendAndSubmit",
                        lambda p, t: submit_calls.append((p, t)) or 0)
    monkeypatch.setattr("time.sleep", lambda s: None)
    # Test action.
    rc = tmux_cancelAndSend("p", "cmd")
    # Test verification: 5 Ctrl-Cs, 1 submit, rc 0.
    assert rc == 0
    assert len(ctrlc_calls) == 5
    assert submit_calls == [("p", "cmd")]


def test_tmux_cancelAndSend_returns_rc_from_final_send(monkeypatch):
    # Scenario: tmux_sendAndSubmit returns 2; cancelAndSend propagates.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendCtrlC", lambda p: 0)
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane",
                        lambda p, scrollback_lines=None: "Ctrl-C")
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendAndSubmit", lambda p, t: 2)
    monkeypatch.setattr("time.sleep", lambda s: None)
    # Test action + verification.
    assert tmux_cancelAndSend("p", "x") == 2


def test_tmux_cancelAndSend_logs_label_when_retry_needed(monkeypatch, capsys):
    # Scenario: first capture lacks marker, second has it; label appears in stdout log.
    cap_iter = iter(["", "Ctrl-C"])
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendCtrlC", lambda p: 0)
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane",
                        lambda p, scrollback_lines=None: next(cap_iter))
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendAndSubmit", lambda p, t: 0)
    monkeypatch.setattr("time.sleep", lambda s: None)
    # Test action.
    tmux_cancelAndSend("p", "x", "work-99")
    # Test verification: label and "Ctrl-C" appear on stdout.
    out = capsys.readouterr().out
    assert "work-99" in out
    assert "Ctrl-C" in out


def test_tmux_cancelAndSend_omits_log_when_first_attempt_succeeds(monkeypatch, capsys):
    # Scenario: marker visible on first capture; no log emitted even with label.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendCtrlC", lambda p: 0)
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane",
                        lambda p, scrollback_lines=None: "Ctrl-C done")
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendAndSubmit", lambda p, t: 0)
    monkeypatch.setattr("time.sleep", lambda s: None)
    # Test action.
    tmux_cancelAndSend("p", "x", "work-42")
    # Test verification: log suppressed.
    out = capsys.readouterr().out
    assert "work-42" not in out


# === Bucket: Communicate [live] ===

# Skip the whole module if tmux is unavailable on this host.
pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not installed"
)


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
