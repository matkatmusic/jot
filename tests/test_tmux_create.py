"""Tests for tmux_lib Create bucket: newSession, newPane, newWindow,
splitWindow, splitWorkerPane, ensureKeepalivePane, ensureSession + live."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from unittest.mock import call, patch

from common.scripts import tmux_lib as _tmux_lib_mod
from common.scripts.tmux_lib import (
    tmux_ensureKeepalivePane,
    tmux_ensureSession,
    tmux_killSession,
    tmux_listPanes,
    tmux_newPane,
    tmux_newSession,
    tmux_newWindow,
    tmux_splitWindow,
    tmux_splitWorkerPane,
)

# Bind module alias used throughout the test bodies.
mod = _tmux_lib_mod


# === Bucket: Create ===

def _make_fake_run(rc: int, stdout: str = "", stderr: str = "", calls: list | None = None):
    """Builds a fake subprocess.run with controllable rc/stdout/stderr."""
    def _fake(cmd, *args, **kwargs):
        if calls is not None:
            calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=rc, stdout=stdout, stderr=stderr)
    return _fake


# --- tmux_newSession ---

def test_tmux_newSession_invokes_tmux_new_session_with_dash_d_dash_s_and_session_name(monkeypatch):
    # Scenario: caller passes only a session name; underlying tmux invocation uses `-d -s <name>`.
    calls: list = []
    # Setup: capturing fake.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action: invoke with only a session name.
    tmux_newSession("mysess")
    # Test verification: cmd is exactly `tmux new-session -d -s mysess`.
    assert calls == [["tmux", "new-session", "-d", "-s", "mysess"]]


def test_tmux_newSession_returns_zero_on_success(monkeypatch):
    # Scenario: tmux new-session succeeds (rc=0); function returns 0.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0))
    # Test action + verification: rc=0 propagates.
    assert tmux_newSession("ok") == 0


def test_tmux_newSession_returns_nonzero_and_logs_caller_when_creation_fails(monkeypatch, capsys):
    # Scenario: duplicate session causes tmux to fail (rc=1); function returns rc and logs caller-attributed stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="duplicate session: dup"))
    # Test action: invoke from this test (caller frame is the test function).
    rc = tmux_newSession("dup")
    err = capsys.readouterr().err
    # Test verification: rc propagates and stderr contains caller name + cmd + failure text.
    assert rc == 1
    assert "test_tmux_newSession_returns_nonzero_and_logs_caller_when_creation_fails" in err
    assert "tmux new-session -d -s dup" in err
    assert "duplicate session: dup" in err


def test_tmux_newSession_passes_extra_args_through_to_tmux_after_session_name(monkeypatch):
    # Scenario: caller supplies extra args (window name, cwd, command); they must appear in argv after the session name.
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action: invoke with extras.
    tmux_newSession("s1", "-n", "win", "-c", "/tmp", "bash")
    # Test verification: extras follow the session name, in order.
    assert calls == [["tmux", "new-session", "-d", "-s", "s1", "-n", "win", "-c", "/tmp", "bash"]]


# --- tmux_newPane ---

def test_tmux_newPane_invokes_tmux_split_window_with_dash_t_target(monkeypatch):
    # Scenario: calling tmux_newPane with only a target builds the canonical split-window command.
    calls: list = []
    # Setup: stub subprocess.run so we capture the argv without spawning tmux.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action: invoke with a single target argument, no extras.
    tmux_newPane("sess:0.0")
    # Test verification: argv must be exactly tmux split-window -t <target>, proving command shape.
    assert calls == [["tmux", "split-window", "-t", "sess:0.0"]]


def test_tmux_newPane_returns_zero_on_success(monkeypatch):
    # Scenario: a successful split-window propagates rc=0 to the caller.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0))
    # Test action + verification: rc=0 propagates.
    assert tmux_newPane("sess:0.0") == 0


def test_tmux_newPane_returns_nonzero_and_logs_caller_when_split_fails(monkeypatch, capsys):
    # Scenario: when tmux exits nonzero, function returns rc and logs a caller-attributed stderr line.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="can't find pane"))
    # Test action: invoke from this test function so caller-frame name = this test's name.
    rc = tmux_newPane("nope:0.0")
    err = capsys.readouterr().err
    # Test verification: rc bubbles up AND stderr contains caller-name tag, proving error-path logging.
    assert rc == 1
    assert "test_tmux_newPane_returns_nonzero_and_logs_caller_when_split_fails" in err
    assert "can't find pane" in err


def test_tmux_newPane_passes_extra_args_through_after_target(monkeypatch):
    # Scenario: extra positional args are appended verbatim after the target, in order.
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action: invoke with several pass-through tmux flags plus a trailing shell command.
    tmux_newPane("sess:0.0", "-c", "/tmp", "-P", "-F", "#{pane_id}", "bash")
    # Test verification: argv preserves position/order of extras after -t <target>.
    assert calls == [["tmux", "split-window", "-t", "sess:0.0", "-c", "/tmp", "-P", "-F", "#{pane_id}", "bash"]]


def test_tmux_newPane_prints_stdout_to_caller_on_success(monkeypatch, capsys):
    # Scenario: when -P is used, tmux writes the new pane id to stdout; the function must echo it so $()-style callers can capture it.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, stdout="%42\n"))
    # Test action: invoke with -P -F '#{pane_id}' as a real caller would.
    rc = tmux_newPane("sess:0.0", "-P", "-F", "#{pane_id}")
    out = capsys.readouterr().out
    # Test verification: stdout was forwarded verbatim and rc=0, proving the pane-id capture flow.
    assert rc == 0
    assert out == "%42\n"


# --- tmux_newWindow ---

def test_tmux_newWindow_invokes_tmux_new_window_with_dash_t_session_and_dash_n_window(monkeypatch):
    # Scenario: caller passes session and window names; subprocess receives `tmux new-window -t S -n W`.
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action.
    tmux_newWindow("mysess", "mywin")
    # Test verification: exact argv ordering.
    assert calls == [["tmux", "new-window", "-t", "mysess", "-n", "mywin"]]


def test_tmux_newWindow_returns_zero_on_success(monkeypatch):
    # Scenario: subprocess returns 0; function returns 0.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0))
    # Test action + verification.
    assert tmux_newWindow("s", "w") == 0


def test_tmux_newWindow_returns_nonzero_and_logs_caller_when_creation_fails(monkeypatch, capsys):
    # Scenario: subprocess returns nonzero; function returns same rc and logs caller-attributed stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(2, stderr="duplicate window"))

    # Setup: named caller frame.
    def caller_fn():
        return tmux_newWindow("s", "w")

    # Test action.
    rc = caller_fn()
    err = capsys.readouterr().err
    # Test verification.
    assert rc == 2
    assert "[caller_fn]" in err
    assert "duplicate window" in err


def test_tmux_newWindow_passes_extra_args_through_after_window_name(monkeypatch):
    # Scenario: extra args (e.g. -c cwd, shell command) appear after `-n <window>`.
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action.
    tmux_newWindow("s", "w", "-c", "/tmp", "echo hi")
    # Test verification: extras follow `-n w` in order.
    assert calls == [["tmux", "new-window", "-t", "s", "-n", "w", "-c", "/tmp", "echo hi"]]


# --- tmux_splitWindow ---

def test_tmux_splitWindow_invokes_tmux_split_window_with_dash_h_for_horizontal(monkeypatch):
    # Scenario: horizontal direction must produce `tmux split-window -h -t <target>`.
    calls: list = []
    # Setup.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action.
    tmux_splitWindow("s1", "h")
    # Test verification.
    assert calls == [["tmux", "split-window", "-h", "-t", "s1"]]


def test_tmux_splitWindow_invokes_tmux_split_window_with_dash_v_for_vertical(monkeypatch):
    # Scenario: vertical direction produces `tmux split-window -v -t <target>`.
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action.
    tmux_splitWindow("win:0", "v")
    # Test verification.
    assert calls == [["tmux", "split-window", "-v", "-t", "win:0"]]


def test_tmux_splitWindow_returns_zero_on_success(monkeypatch):
    # Scenario: rc=0 from tmux is propagated.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0))
    # Test action + verification.
    assert tmux_splitWindow("s1", "h") == 0


def test_tmux_splitWindow_returns_nonzero_and_logs_caller_when_split_fails(monkeypatch, capsys):
    # Scenario: nonzero rc propagates AND a caller-attributed stderr log is emitted.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="no such target"))
    # Test action: invoke from this test (caller name appears in log).
    rc = tmux_splitWindow("missing", "h")
    err = capsys.readouterr().err
    # Test verification.
    assert rc == 1
    assert "tmux split-window -h -t missing" in err
    assert "test_tmux_splitWindow_returns_nonzero_and_logs_caller_when_split_fails" in err


def test_tmux_splitWindow_raises_ValueError_for_invalid_direction(monkeypatch):
    # Scenario: anything other than "h"/"v" must raise ValueError BEFORE any subprocess call.
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action + verification: raises and never invokes subprocess.run.
    with pytest.raises(ValueError, match="direction must be 'h' or 'v'"):
        tmux_splitWindow("s1", "x")
    assert calls == []


# --- tmux_splitWorkerPane ---


class _FakeCompleted:
    """Stand-in for subprocess.CompletedProcess used by tmux_splitWorkerPane tests."""

    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_tmux_splitWorkerPane_returns_pane_id_on_success(monkeypatch):
    # Scenario: split succeeds; tmux prints a pane id; function returns it stripped.
    captured: dict[str, list[str]] = {}
    # Setup: stub subprocess.run to record argv and return a pane id.
    def fake_run(cmd, capture_output, text, check):
        captured["cmd"] = list(cmd)
        return _FakeCompleted(0, stdout="%42\n")
    monkeypatch.setattr(subprocess, "run", fake_run)
    # Test action.
    result = tmux_splitWorkerPane("sess:win", "/tmp/work", "sleep 1")
    # Test verification: id stripped and split-window args correct.
    assert result == "%42"
    assert captured["cmd"][:2] == ["tmux", "split-window"]
    assert "-t" in captured["cmd"] and "sess:win" in captured["cmd"]
    assert "-c" in captured["cmd"] and "/tmp/work" in captured["cmd"]
    assert "-P" in captured["cmd"]
    assert "-F" in captured["cmd"] and "#{pane_id}" in captured["cmd"]
    assert "sleep 1" in captured["cmd"]


def test_tmux_splitWorkerPane_returns_None_when_tmux_fails(monkeypatch):
    # Scenario: tmux split-window exits nonzero; function signals failure with None.
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: _FakeCompleted(1, stdout="", stderr="boom"))
    # Test action + verification.
    assert tmux_splitWorkerPane("sess:win", "/tmp", "cmd") is None


def test_tmux_splitWorkerPane_returns_None_when_pane_id_blank(monkeypatch):
    # Scenario: tmux exits 0 but emits no pane id; treated as failure -> None.
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: _FakeCompleted(0, stdout="\n"))
    # Test action + verification.
    assert tmux_splitWorkerPane("sess:win", "/tmp", "cmd") is None


def test_tmux_splitWorkerPane_logs_caller_attributed_stderr_on_failure(monkeypatch, capsys):
    # Scenario: failure path emits caller-attributed stderr matching project pattern.
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: _FakeCompleted(1, stderr="boom"))
    # Setup: named caller frame.
    def caller_frame_under_test():
        return tmux_splitWorkerPane("s:w", "/tmp", "cmd")
    # Test action.
    caller_frame_under_test()
    err = capsys.readouterr().err
    # Test verification: caller name + tmux cmd + stderr text appear.
    assert "caller_frame_under_test" in err
    assert "tmux split-window -t s:w" in err
    assert "boom" in err


# --- tmux_ensureKeepalivePane ---

def test_tmux_ensureKeepalivePane_returns_early_when_pane_with_title_exists():
    # Scenario: the target window already hosts a pane with the requested title.
    # Setup: stub tmux_paneHasTitle to return rc 0 and spy on creation helpers.
    with patch.object(_tmux_lib_mod, "tmux_paneHasTitle", return_value=0) as has_title, \
         patch.object(_tmux_lib_mod, "tmux_splitWorkerPane") as split_worker, \
         patch.object(_tmux_lib_mod, "tmux_setPaneTitle") as set_title, \
         patch.object(_tmux_lib_mod, "tmux_retile") as retile:
        # Test action: invoke the ensurer.
        result = tmux_ensureKeepalivePane("sess:win", "/tmp", "sleep 9999", "keepalive")
    # Test verification: no creation calls fired.
    assert result is None
    has_title.assert_called_once_with("sess:win", "keepalive")
    split_worker.assert_not_called()
    set_title.assert_not_called()
    retile.assert_not_called()


def test_tmux_ensureKeepalivePane_creates_pane_sets_title_and_retiles_when_absent():
    # Scenario: no keepalive pane exists; one must be spawned, titled, and retiled.
    # Setup: pane title probe returns rc 1 and split helper returns a pane id.
    with patch.object(_tmux_lib_mod, "tmux_paneHasTitle", return_value=1), \
         patch.object(_tmux_lib_mod, "tmux_splitWorkerPane", return_value="%42") as split_worker, \
         patch.object(_tmux_lib_mod, "tmux_setPaneTitle") as set_title, \
         patch.object(_tmux_lib_mod, "tmux_retile") as retile:
        # Test action: ensure on an empty window.
        tmux_ensureKeepalivePane("sess:win", "/work", "sleep 9999", "keepalive")
    # Test verification: pane created with cwd and command; title/retile invoked.
    split_worker.assert_called_once_with("sess:win", "/work", "sleep 9999")
    set_title.assert_called_once_with("%42", "keepalive")
    retile.assert_called_once_with("sess:win")


def test_tmux_ensureKeepalivePane_skips_set_title_when_split_returns_none():
    # Scenario: split helper fails and yields no pane id.
    # Setup: pane absent; split returns None.
    with patch.object(_tmux_lib_mod, "tmux_paneHasTitle", return_value=1), \
         patch.object(_tmux_lib_mod, "tmux_splitWorkerPane", return_value=None) as split_worker, \
         patch.object(_tmux_lib_mod, "tmux_setPaneTitle") as set_title, \
         patch.object(_tmux_lib_mod, "tmux_retile") as retile:
        # Test action: invoke ensurer where pane creation fails.
        tmux_ensureKeepalivePane("sess:win", "/work", "sleep 9999", "keepalive")
    # Test verification: no title set, but retile still called for parity with bash.
    split_worker.assert_called_once_with("sess:win", "/work", "sleep 9999")
    set_title.assert_not_called()
    retile.assert_called_once_with("sess:win")


# --- tmux_ensureSession ---

def test_tmux_ensureSession_creates_session_when_absent():
    # Scenario: session does not yet exist, so full session creation path runs.
    # Setup: tmux_hasSession returns rc 1 for absent.
    with patch.object(_tmux_lib_mod, "tmux_hasSession", return_value=1) as has_session, \
         patch.object(_tmux_lib_mod, "tmux_newSession") as new_session, \
         patch.object(_tmux_lib_mod, "tmux_setOptionForTarget") as set_option, \
         patch.object(_tmux_lib_mod, "tmux_setPaneTitle") as set_title, \
         patch.object(_tmux_lib_mod, "tmux_windowExists") as window_exists, \
         patch.object(_tmux_lib_mod, "tmux_newWindow") as new_window, \
         patch.object(_tmux_lib_mod, "tmux_ensureKeepalivePane") as ensure_keepalive:
        # Test action: invoke ensure-session with fresh-session inputs.
        rc = tmux_ensureSession("sess", "win", "/tmp", "sleep 9999", "KA")
    # Test verification: new session created; window and keepalive existing-session paths skipped.
    assert rc == 0
    has_session.assert_called_once_with("sess")
    new_session.assert_called_once_with("sess", "-n", "win", "-c", "/tmp", "sleep 9999")
    window_exists.assert_not_called()
    new_window.assert_not_called()
    ensure_keepalive.assert_not_called()
    assert set_option.call_args_list == [
        call("sess", "remain-on-exit", "off"),
        call("sess", "mouse", "on"),
        call("sess", "pane-border-status", "top"),
        call("sess", "pane-border-format", " #{pane_title} "),
    ]
    set_title.assert_called_once_with("sess:win.0", "KA")


def test_tmux_ensureSession_creates_window_when_session_exists_but_window_absent():
    # Scenario: session present, window missing; window-creation branch runs.
    # Setup: hasSession rc 0, windowExists rc 1.
    with patch.object(_tmux_lib_mod, "tmux_hasSession", return_value=0), \
         patch.object(_tmux_lib_mod, "tmux_windowExists", return_value=1), \
         patch.object(_tmux_lib_mod, "tmux_newSession") as new_session, \
         patch.object(_tmux_lib_mod, "tmux_setOptionForTarget") as set_option, \
         patch.object(_tmux_lib_mod, "tmux_newWindow") as new_window, \
         patch.object(_tmux_lib_mod, "tmux_setPaneTitle") as set_title, \
         patch.object(_tmux_lib_mod, "tmux_ensureKeepalivePane") as ensure_keepalive:
        # Test action: invoke ensure-session.
        rc = tmux_ensureSession("sess", "win", "/work", "sleep 1", "KA2")
    # Test verification: window created, title set; session creation skipped.
    assert rc == 0
    new_session.assert_not_called()
    set_option.assert_not_called()
    ensure_keepalive.assert_not_called()
    new_window.assert_called_once_with("sess", "win", "-c", "/work", "sleep 1")
    set_title.assert_called_once_with("sess:win.0", "KA2")


def test_tmux_ensureSession_delegates_to_keepalive_pane_when_both_exist():
    # Scenario: session and window both exist; only keepalive-pane ensure runs.
    # Setup: hasSession and windowExists both return rc 0.
    with patch.object(_tmux_lib_mod, "tmux_hasSession", return_value=0), \
         patch.object(_tmux_lib_mod, "tmux_windowExists", return_value=0), \
         patch.object(_tmux_lib_mod, "tmux_newSession") as new_session, \
         patch.object(_tmux_lib_mod, "tmux_newWindow") as new_window, \
         patch.object(_tmux_lib_mod, "tmux_setOptionForTarget") as set_option, \
         patch.object(_tmux_lib_mod, "tmux_setPaneTitle") as set_title, \
         patch.object(_tmux_lib_mod, "tmux_ensureKeepalivePane") as ensure_keepalive:
        # Test action: invoke ensure-session.
        rc = tmux_ensureSession("sess", "win", "/d", "sleep 2", "KA3")
    # Test verification: only ensureKeepalivePane invoked with target sess:win.
    assert rc == 0
    new_session.assert_not_called()
    new_window.assert_not_called()
    set_option.assert_not_called()
    set_title.assert_not_called()
    ensure_keepalive.assert_called_once_with("sess:win", "/d", "sleep 2", "KA3")


# === Bucket: Create [live] ===

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
def test_newSession_createsSession(session_name):
    # Scenario: newSession returns rc 0 and the session becomes reachable.
    # Setup: no pre-existing session (fixture guarantees this).
    # Test action: create the session.
    rc = tmux_newSession(session_name)
    # Test verification: rc 0 means tmux accepted the create.
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
def test_newPane_addsPaneToSession(tmux_session_panes):
    # Scenario: tmux_newPane on an existing session succeeds (rc=0).
    # Setup: session exists via fixture.
    # Test action: split a new pane.
    rc = tmux_newPane(tmux_session_panes)
    # Test verification: rc 0 means tmux accepted the split.
    assert rc == 0


@pytest.mark.live
def test_newPane_failsOnNonexistentSession():
    # Scenario: new_pane on a session that does not exist returns nonzero rc.
    # Setup: a name that is not a live session.
    bogus = f"nonexistent-{os.getpid()}"
    # Test action: attempt split on bogus target.
    rc = tmux_newPane(bogus)
    # Test verification: nonzero rc indicates failure.
    assert rc != 0


def _tmux_has_session(name: str) -> bool:
    # Setup helper: shell out to real tmux to check session existence.
    r = subprocess.run(
        ["tmux", "has-session", "-t", name],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return r.returncode == 0


def _tmux_window_exists(session: str, window: str) -> bool:
    # Setup helper: list windows and grep for an exact name match.
    r = subprocess.run(
        ["tmux", "list-windows", "-t", session, "-F", "#{window_name}"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return False
    return window in r.stdout.splitlines()


def _tmux_pane_has_title(target: str, title: str) -> bool:
    # Setup helper: query pane_title via display-message.
    r = subprocess.run(
        ["tmux", "display-message", "-p", "-t", target, "#{pane_title}"],
        capture_output=True, text=True,
    )
    return r.returncode == 0 and r.stdout.strip() == title


def _tmux_show_option(target: str, opt: str) -> str:
    # Setup helper: read tmux option value, empty string on miss.
    r = subprocess.run(
        ["tmux", "show-options", "-t", target, "-v", opt],
        capture_output=True, text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def _kill(name: str) -> None:
    # Teardown helper: best-effort session kill.
    subprocess.run(
        ["tmux", "kill-session", "-t", name],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


@pytest.fixture
def tmux_session_clean():
    # Provide a unique session name and clean up after the test.
    name = f"tmux-sh-launcher-test-{os.getpid()}"
    _kill(name)
    yield name
    _kill(name)


# ---------- tests ----------

@pytest.mark.live
def test_ensure_session_creates_new_session(tmux_session_clean):
    # Scenario: ensure_session on a missing session creates it (Path 1).
    # Setup: session name guaranteed absent by fixture.
    # Test action: invoke tmux_ensureSession with main window + keepalive.
    tmux_ensureSession(tmux_session_clean, "main", "/tmp", "sleep 30", "keepalive")
    # Test verification: tmux now reports the session exists.
    assert _tmux_has_session(tmux_session_clean)


@pytest.mark.live
def test_ensure_session_sets_keepalive_pane_title(tmux_session_clean):
    # Scenario: keepalive pane created by ensure_session has the requested title.
    # Setup: create the session via ensure_session.
    tmux_ensureSession(tmux_session_clean, "main", "/tmp", "sleep 30", "keepalive")
    # Test action: read pane_title for main window.
    # Test verification: title equals "keepalive".
    assert _tmux_pane_has_title(f"{tmux_session_clean}:main", "keepalive")


@pytest.mark.live
def test_ensure_session_applies_pane_border_status_top(tmux_session_clean):
    # Scenario: ensure_session sets pane-border-status=top via set_option_t.
    # Setup: create session.
    tmux_ensureSession(tmux_session_clean, "main", "/tmp", "sleep 30", "keepalive")
    # Test action: read tmux option.
    border = _tmux_show_option(tmux_session_clean, "pane-border-status")
    # Test verification: option is "top".
    assert border == "top"


@pytest.mark.live
def test_split_worker_pane_returns_pane_id(tmux_session_clean):
    # Scenario: split_worker_pane creates a pane and returns its %id.
    # Setup: ensure session exists first.
    tmux_ensureSession(tmux_session_clean, "main", "/tmp", "sleep 30", "keepalive")
    # Test action: split a worker pane in main window.
    worker = tmux_splitWorkerPane(f"{tmux_session_clean}:main", "/tmp", "sleep 30")
    # Test verification: returned id is non-empty and starts with '%'.
    assert worker
    assert str(worker).startswith("%")


@pytest.mark.live
def test_ensure_session_idempotent_on_existing_session(tmux_session_clean):
    # Scenario: re-calling ensure_session on existing session+window is a no-op (Path 3).
    # Setup: create session once.
    tmux_ensureSession(tmux_session_clean, "main", "/tmp", "sleep 30", "keepalive")
    # Test action: call ensure_session a second time with same args.
    tmux_ensureSession(tmux_session_clean, "main", "/tmp", "sleep 30", "keepalive")
    # Test verification: session still exists, not destroyed by second call.
    assert _tmux_has_session(tmux_session_clean)


@pytest.mark.live
def test_ensure_session_adds_new_window_to_existing_session(tmux_session_clean):
    # Scenario: ensure_session on existing session with new window name adds the window (Path 2).
    # Setup: create session with main window.
    tmux_ensureSession(tmux_session_clean, "main", "/tmp", "sleep 30", "keepalive")
    second = f"secondwin-{os.getpid()}"
    # Test action: call ensure_session with a different window name.
    tmux_ensureSession(tmux_session_clean, second, "/tmp", "sleep 30", "keepalive-2")
    # Test verification: new window now present in the session.
    assert _tmux_window_exists(tmux_session_clean, second)


# --- Orphan helpers (preserved from monolith; not yet referenced by tests) ---

def _writeSidecar(tmpdir_inv: Path, pane_id: str) -> None:
    (tmpdir_inv / "tmux_target").write_text(pane_id + "\n")


@pytest.fixture
def kill_calls(monkeypatch):
    # Test seam: capture pane-id + retile-target instead of touching tmux.
    calls: list[tuple[str, str]] = []

    def _fake_bg(pane_target: str, retile_target: str) -> None:
        calls.append((pane_target, retile_target))

    return calls, _fake_bg


@pytest.fixture
def fake_tmux(monkeypatch):
    """Patch `_tmux_live_pane_ids` to return a configurable set without tmux."""
    state: dict[str, set[str]] = {"live": set()}

    def _fake() -> set[str]:
        return set(state["live"])


    monkeypatch.setattr("common.scripts.tmux_lib._tmux_live_pane_ids", _fake)
    return state


def _make_tmpdir(tmp_path: Path, tmux_target: str = "%42") -> Path:
    """Write a minimal per-invocation tmpdir with tmux_target sidecar."""
    d = tmp_path / "todo.XXXX"
    d.mkdir()
    (d / "tmux_target").write_text(f"{tmux_target}\n")
    return d
