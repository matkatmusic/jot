"""Tests for tmux_lib Read bucket: requireVersion, hasSession, listClients,
capturePane, listPanes, listWindows, windowExists, paneHasTitle, plus live tests."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from common.scripts import tmux_lib as _tmux_lib_mod
from common.scripts.tmux_lib import (
    tmux_capturePane,
    tmux_hasSession,
    tmux_killPane,
    tmux_killSession,
    tmux_listClients,
    tmux_listPanes,
    tmux_listWindows,
    tmux_newPane,
    tmux_newSession,
    tmux_paneHasTitle,
    tmux_requireVersion,
    tmux_windowExists,
)
from common.scripts.jot_lib import jot_main

# Bind module alias used throughout the test bodies.
mod = _tmux_lib_mod


def _stdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    # Helper: replace sys.stdin with an in-memory buffer carrying the JSON payload.
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))


# === Bucket: Read ===

# --- tmux_requireVersion ---

class _FakeProc:
    """Stand-in for subprocess.CompletedProcess used by version-probe tests."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_tmux_requireVersion_returns_1_and_logs_when_tmux_binary_is_missing(monkeypatch, capsys):
    # Scenario: if `tmux -V` cannot be executed because tmux is not installed
    # (FileNotFoundError), the function returns 1 and writes a "not installed"
    # diagnostic to stderr.
    # Setup: monkeypatch subprocess.run to raise FileNotFoundError, simulating no tmux on PATH.
    def _raise(*a, **k):
        raise FileNotFoundError("tmux")
    monkeypatch.setattr(subprocess, "run", _raise)
    # Test action: probe for any required version.
    rc = tmux_requireVersion("3.0")
    # Test verification: return code is 1 and stderr names the missing-binary condition.
    assert rc == 1
    assert "not installed" in capsys.readouterr().err


def test_tmux_requireVersion_returns_0_when_installed_version_exactly_matches_required(monkeypatch):
    # Scenario: installed tmux version equals the required minimum -> success (0).
    # Setup: stub subprocess.run to return "tmux 3.2".
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc("tmux 3.2\n"))
    # Test action + verification: required="3.2", installed="3.2" -> 0.
    assert tmux_requireVersion("3.2") == 0


def test_tmux_requireVersion_returns_0_when_installed_version_exceeds_required(monkeypatch):
    # Scenario: installed tmux version is higher than required -> success (0).
    # Includes a trailing letter ("3.4a") to prove the regex handles tmux's
    # release-candidate suffixes correctly.
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc("tmux 3.4a\n"))
    assert tmux_requireVersion("3.2") == 0


def test_tmux_requireVersion_returns_1_and_logs_when_installed_version_is_below_required(monkeypatch, capsys):
    # Scenario: installed tmux is older than required -> failure (1) with a
    # stderr message naming the required minimum.
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc("tmux 2.9\n"))
    rc = tmux_requireVersion("3.2")
    # Test verification: rc=1 and stderr text contains "required" (the diagnostic word).
    assert rc == 1
    assert "required" in capsys.readouterr().err


def test_tmux_requireVersion_returns_1_when_tmux_version_output_is_unparseable(monkeypatch, capsys):
    # Scenario: `tmux -V` produced output but no M.m version pattern was found.
    # The function treats this the same as "not installed" -> returns 1.
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc("garbage\n"))
    rc = tmux_requireVersion("3.0")
    assert rc == 1
    assert "not installed" in capsys.readouterr().err


# --- tmux_hasSession ---

def _make_fake_run(rc: int, stdout: str = "", stderr: str = "", calls: list | None = None):
    """Builds a fake subprocess.run with controllable rc/stdout/stderr."""
    def _fake(cmd, *args, **kwargs):
        if calls is not None:
            calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=rc, stdout=stdout, stderr=stderr)
    return _fake


def test_tmux_hasSession_returns_zero_when_session_exists(monkeypatch):
    # Scenario: tmux reports session present (rc=0); function returns 0.
    # Setup: monkeypatch subprocess.run to return rc=0.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0))
    # Test action: probe for any session name.
    rc = tmux_hasSession("mysess")
    # Test verification: rc passes through unchanged.
    assert rc == 0


def test_tmux_hasSession_returns_one_when_session_does_not_exist(monkeypatch):
    # Scenario: tmux reports session absent (rc=1); function returns 1 (NOT an error - it's a valid answer).
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1))
    # Test action: probe for a missing session.
    rc = tmux_hasSession("ghost")
    # Test verification: rc=1 propagates as the answer.
    assert rc == 1


def test_tmux_hasSession_invokes_tmux_has_session_with_dash_t_target(monkeypatch):
    # Scenario: function shells out to `tmux has-session -t <session_name>` (proves argv shape).
    calls: list = []
    # Setup: capturing fake.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action: invoke.
    tmux_hasSession("alpha")
    # Test verification: argv exactly matches `tmux has-session -t alpha`.
    assert calls == [["tmux", "has-session", "-t", "alpha"]]


def test_tmux_hasSession_does_not_log_to_stderr_when_session_is_simply_absent(monkeypatch, capsys):
    # Scenario: rc=1 means "absent", a normal answer; no stderr noise even though tmux wrote a diagnostic.
    # Setup: rc=1 with tmux's typical "can't find session" stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="can't find session: ghost"))
    # Test action: probe absent session.
    tmux_hasSession("ghost")
    # Test verification: our wrapper writes nothing to stderr.
    assert capsys.readouterr().err == ""


def test_tmux_hasSession_logs_caller_name_to_stderr_on_unexpected_nonzero_rc(monkeypatch, capsys):
    # Scenario: rc not in {0,1} (e.g. 2) is unexpected; log caller-attributed line to stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(2, stderr="boom"))
    # Test action: invoke directly so caller-frame name = this test's name.
    rc = tmux_hasSession("weird")
    # Test verification: rc returned as-is, stderr has caller name + cmd + tmux's stderr text.
    captured = capsys.readouterr()
    assert rc == 2
    assert "test_tmux_hasSession_logs_caller_name_to_stderr_on_unexpected_nonzero_rc" in captured.err
    assert "tmux has-session -t weird" in captured.err
    assert "boom" in captured.err


# --- tmux_listClients ---

def test_tmux_listClients_invokes_tmux_list_clients_with_dash_t_session_name(monkeypatch):
    # Scenario: function shells out to `tmux list-clients -t <session_name>` (proves argv shape).
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action: invoke.
    tmux_listClients("mysess")
    # Test verification: exact argv.
    assert calls == [["tmux", "list-clients", "-t", "mysess"]]


def test_tmux_listClients_returns_empty_list_when_no_clients_attached(monkeypatch):
    # Scenario: tmux returns rc=0 with empty stdout (session exists, no clients).
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, stdout=""))
    # Test action + verification: returns empty list.
    assert tmux_listClients("sess") == []


def test_tmux_listClients_returns_one_string_per_client_line_on_stdout(monkeypatch):
    # Scenario: tmux prints multiple client lines; each becomes a list element verbatim (without trailing newline).
    stdout = "/dev/ttys001: 0: [80x24 xterm-256color] (utf8)\n/dev/ttys002: 1: [120x40 xterm-256color] (utf8)\n"
    # Setup: stub subprocess.run with multi-line stdout.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, stdout=stdout))
    # Test action: invoke.
    result = tmux_listClients("sess")
    # Test verification: 2 elements, both stripped of the line terminator, no empty string from trailing newline.
    assert result == [
        "/dev/ttys001: 0: [80x24 xterm-256color] (utf8)",
        "/dev/ttys002: 1: [120x40 xterm-256color] (utf8)",
    ]


def test_tmux_listClients_returns_empty_list_and_logs_caller_when_session_not_found(monkeypatch, capsys):
    # Scenario: tmux exits nonzero (session not found); function returns [] and logs caller-attributed stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="can't find session: ghost\n"))

    # Setup: named caller frame to assert attribution.
    def caller_frame():
        return tmux_listClients("ghost")

    # Test action.
    result = caller_frame()
    err = capsys.readouterr().err
    # Test verification: empty list, stderr has caller + cmd.
    assert result == []
    assert "caller_frame" in err
    assert "tmux list-clients -t ghost" in err


# --- tmux_capturePane ---

def test_tmux_capturePane_invokes_tmux_capture_pane_with_dash_p_dash_t_target_when_no_scrollback_requested(monkeypatch):
    # Scenario: caller passes only a pane target; function uses `tmux capture-pane -p -t <target>` with no -S flag.
    calls: list = []
    # Setup: capturing fake.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action: invoke without scrollback.
    tmux_capturePane("session:0.1")
    # Test verification: -p (print) and -t (target), no -S.
    assert calls == [["tmux", "capture-pane", "-p", "-t", "session:0.1"]]


def test_tmux_capturePane_returns_pane_stdout_text_on_success(monkeypatch):
    # Scenario: tmux exits 0 and prints pane text; function returns that text verbatim (preserves trailing newlines).
    pane_text = "line one\nline two\n"
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, stdout=pane_text))
    # Test action: invoke and capture return value.
    result = tmux_capturePane("foo:1.0")
    # Test verification: stdout returned without modification.
    assert result == pane_text


def test_tmux_capturePane_includes_dash_S_negative_offset_when_scrollback_lines_given(monkeypatch):
    # Scenario: caller requests N scrollback lines; argv must end with -S -N (mirrors bash `${2:+-S -$2}`).
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action: invoke with scrollback_lines=200.
    tmux_capturePane("sess:0.0", 200)
    # Test verification: -S -200 appended.
    assert calls == [["tmux", "capture-pane", "-p", "-t", "sess:0.0", "-S", "-200"]]


def test_tmux_capturePane_returns_empty_string_and_logs_caller_when_target_missing(monkeypatch, capsys):
    # Scenario: tmux exits nonzero (target pane does not exist); function returns "" and logs caller-attributed stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="can't find pane"))
    # Test action: invoke; failure path triggered.
    result = tmux_capturePane("bogus:9.9")
    err = capsys.readouterr().err
    # Test verification: empty string returned; stderr has caller-attributed log with cmd + tmux's stderr.
    assert result == ""
    assert "command 'tmux capture-pane -p -t bogus:9.9' failed" in err
    assert "can't find pane" in err


# --- tmux_listPanes ---

def test_tmux_listPanes_uses_default_pane_id_and_title_format_when_no_extras_given(monkeypatch):
    # Scenario: caller passes only a target; default `-F '#{pane_id} #{pane_title}'` should be injected.
    calls: list = []
    # Setup: stub subprocess.run capturing the argv.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, stdout="%0 alpha\n", calls=calls))
    # Test action: call with target only.
    tmux_listPanes("session:0")
    # Test verification: default -F format string is present.
    assert calls == [["tmux", "list-panes", "-t", "session:0", "-F", "#{pane_id} #{pane_title}"]]


def test_tmux_listPanes_passes_extra_args_through_when_extras_given_and_omits_default_format(monkeypatch):
    # Scenario: extras provided; default -F must NOT be appended (caller controls format).
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, stdout="alpha\n", calls=calls))
    # Test action: pass custom -F as extras.
    tmux_listPanes("session:0", "-F", "#{pane_title}")
    # Test verification: extras passed verbatim, no injected default.
    assert calls == [["tmux", "list-panes", "-t", "session:0", "-F", "#{pane_title}"]]


def test_tmux_listPanes_returns_one_string_per_pane_line(monkeypatch):
    # Scenario: tmux emits multi-line stdout; function splits into a list, one entry per non-empty line.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, stdout="%0 alpha\n%1 beta\n%2 gamma\n"))
    # Test action: invoke listPanes.
    panes = tmux_listPanes("session:0")
    # Test verification: 3 entries, no empties from trailing newline.
    assert panes == ["%0 alpha", "%1 beta", "%2 gamma"]


def test_tmux_listPanes_returns_empty_list_when_no_panes_in_stdout(monkeypatch):
    # Scenario: tmux succeeds but stdout is empty (target with no panes is unusual, but valid).
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, stdout=""))
    # Test action + verification: empty list.
    assert tmux_listPanes("session:0") == []


def test_tmux_listPanes_returns_empty_list_and_logs_caller_when_target_missing(monkeypatch, capsys):
    # Scenario: tmux exits nonzero (target missing); function returns [] and logs caller-attributed stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="can't find session"))
    # Test action: invoke with a missing target.
    panes = tmux_listPanes("nope")
    err = capsys.readouterr().err
    # Test verification: [] returned and stderr text propagates with caller name.
    assert panes == []
    assert "test_tmux_listPanes_returns_empty_list_and_logs_caller_when_target_missing" in err
    assert "can't find session" in err


# --- tmux_listWindows ---

def test_tmux_listWindows_uses_default_window_index_and_name_format_when_no_extras_given(monkeypatch):
    # Scenario: caller provides only session_name; default `-F '#{window_index} #{window_name}'` is injected.
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, stdout="", calls=calls))
    # Test action.
    tmux_listWindows("mysession")
    # Test verification: argv has default -F format.
    assert calls == [["tmux", "list-windows", "-t", "mysession", "-F", "#{window_index} #{window_name}"]]


def test_tmux_listWindows_passes_extra_args_through_when_extras_given_and_omits_default_format(monkeypatch):
    # Scenario: extras provided; default -F NOT appended (caller controls format).
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, stdout="", calls=calls))
    # Test action.
    tmux_listWindows("mysession", "-F", "#{window_name}")
    # Test verification: extras passed verbatim.
    assert calls == [["tmux", "list-windows", "-t", "mysession", "-F", "#{window_name}"]]


def test_tmux_listWindows_returns_one_string_per_window_line(monkeypatch):
    # Scenario: tmux emits multi-line stdout; result is one string per non-empty line.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, stdout="0 main\n1 logs\n2 editor\n"))
    # Test action.
    result = tmux_listWindows("mysession")
    # Test verification.
    assert result == ["0 main", "1 logs", "2 editor"]


def test_tmux_listWindows_returns_empty_list_when_no_windows_in_stdout(monkeypatch):
    # Scenario: tmux succeeds but stdout is blank; no windows in result.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, stdout="\n"))
    # Test action + verification.
    assert tmux_listWindows("mysession") == []


def test_tmux_listWindows_returns_empty_list_and_logs_caller_when_session_missing(monkeypatch, capsys):
    # Scenario: tmux fails (session missing); function returns [] and logs caller-attributed stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="can't find session: ghost"))
    # Test action: invoke from this test.
    result = tmux_listWindows("ghost")
    err = capsys.readouterr().err
    # Test verification.
    assert result == []
    assert "test_tmux_listWindows_returns_empty_list_and_logs_caller_when_session_missing" in err
    assert "ghost" in err


# --- tmux_windowExists ---

def test_tmux_windowExists_returns_zero_when_window_name_appears_in_listed_windows(monkeypatch):
    # Scenario: window name matches an entry in the listed windows -> exists (0).
    # Setup: stub tmux_listWindows to return a list containing the target window name.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_listWindows",
                        lambda session, *args: ["main", "logs", "editor"])
    # Test action + verification: present-title yields shell-success status 0.
    assert tmux_windowExists("sess", "logs") == 0


def test_tmux_windowExists_returns_one_when_window_name_not_in_listed_windows(monkeypatch):
    # Scenario: window name absent from listed windows -> not-exists (1).
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_listWindows",
                        lambda session, *args: ["main", "editor"])
    # Test action + verification: absent yields 1.
    assert tmux_windowExists("sess", "logs") == 1


def test_tmux_windowExists_uses_exact_match_not_substring(monkeypatch):
    # Scenario: "log" must NOT match "logs" - bash grep -qx is exact-line match.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_listWindows",
                        lambda session, *args: ["logs"])
    # Test action + verification: substring-only does not satisfy exact-match.
    assert tmux_windowExists("sess", "log") == 1


def test_tmux_windowExists_invokes_tmux_listWindows_with_F_window_name_format(monkeypatch):
    # Scenario: implementation must call tmux_listWindows with -F '#{window_name}' format.
    captured: dict = {}

    # Setup: spy capturing positional args.
    def spy(session, *args):
        captured["session"] = session
        captured["args"] = args
        return []

    monkeypatch.setattr("common.scripts.tmux_lib.tmux_listWindows", spy)
    # Test action.
    tmux_windowExists("my-session", "anything")
    # Test verification: session forwarded; -F '#{window_name}' supplied verbatim.
    assert captured["session"] == "my-session"
    assert captured["args"] == ("-F", "#{window_name}")


# --- tmux_paneHasTitle ---

def test_tmux_paneHasTitle_returns_zero_when_title_appears_in_listed_panes(monkeypatch):
    # Scenario: a pane title in target exactly matches the query -> 0.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_listPanes",
                        lambda *a, **k: ["editor", "shell", "logs"])
    # Test action + verification.
    assert tmux_paneHasTitle("sess:0", "shell") == 0


def test_tmux_paneHasTitle_returns_one_when_title_not_in_listed_panes(monkeypatch):
    # Scenario: no pane in target carries the requested title -> 1.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_listPanes",
                        lambda *a, **k: ["editor", "logs"])
    # Test action + verification.
    assert tmux_paneHasTitle("sess:0", "shell") == 1


def test_tmux_paneHasTitle_uses_exact_match_not_substring(monkeypatch):
    # Scenario: a pane title is a SUPERSTRING of the query but not equal; substring should NOT count.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_listPanes",
                        lambda *a, **k: ["editor", "shell-extra", "logs"])
    # Test action + verification: substring-only matches do not count.
    assert tmux_paneHasTitle("sess:0", "shell") == 1


def test_tmux_paneHasTitle_invokes_tmux_listPanes_with_F_pane_title_format(monkeypatch):
    # Scenario: implementation must forward -F '#{pane_title}' verbatim.
    captured: dict = {}

    # Setup: spy capturing args.
    def spy(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return []

    monkeypatch.setattr("common.scripts.tmux_lib.tmux_listPanes", spy)
    # Test action.
    tmux_paneHasTitle("my-target", "anything")
    # Test verification: target forwarded first, then -F flag, then pane_title format.
    assert captured["args"] == ("my-target", "-F", "#{pane_title}")
    assert captured["kwargs"] == {}


# --- tmux too-old block (jot integration) ---

def test_tmux_too_old_emits_block(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: tmux_requireVersion("2.9") returns nonzero.
    # Setup: stub checkRequirements OK, tmux_requireVersion fail.
    monkeypatch.setattr("common.scripts.hookjson_lib.hookjson_checkRequirements", lambda *a, **k: None)
    monkeypatch.setattr("common.scripts.jot_lib.tmux_requireVersion", lambda _m: 1)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot something"}))
    # Test action: invoke.
    rc = jot_main()
    out = capsys.readouterr().out
    # Test verification: rc=0 + tmux block.
    assert rc == 0
    assert "tmux 2.9+" in out


# === Bucket: Read [live] ===

# Skip the whole module if tmux is unavailable on this host.
pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not installed"
)


# Real-tmux fixture: does NOT pre-create a session - session tests manage lifecycle themselves.
# Yields a unique session name; kills any stale session with that name before and after.
@pytest.fixture
def session_name():
    name = f"tmux-py-session-test-{os.getpid()}"
    tmux_killSession(name)  # Setup: clear any stale session from a prior run
    yield name
    tmux_killSession(name)  # Teardown: clean up in case the test left one behind


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
def test_hasSession_returnsFalse_forNonexistentSession(session_name):
    # Scenario: hasSession returns nonzero rc when the session does not exist.
    # Setup: fixture guarantees no session by this name exists.
    # Test action: check for a session that was never created.
    rc = tmux_hasSession(session_name)
    # Test verification: nonzero rc means session absent.
    assert rc != 0


@pytest.mark.live
def test_hasSession_returnsTrue_forExistingSession(session_name):
    # Scenario: hasSession returns rc 0 after newSession succeeds.
    # Setup: create the session first.
    assert tmux_newSession(session_name) == 0
    # Test action: check for the session that now exists.
    rc = tmux_hasSession(session_name)
    # Test verification: rc 0 means session present.
    assert rc == 0


# Real-tmux fixture: creates a detached session, yields its name, kills on teardown.
# Marked `live` because it spawns an actual tmux server.
@pytest.fixture
def tmux_session_panes():
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
def test_listPanes_newSession_hasOnePane(tmux_session_panes):
    # Scenario: A freshly created session contains exactly one pane.
    # Setup: fixture created the session.
    # Test action: list panes.
    panes = tmux_listPanes(tmux_session_panes)
    # Test verification: exactly one pane reported.
    assert len(panes) == 1


@pytest.mark.live
def test_listPanes_afterNewPane_hasTwoPanes(tmux_session_panes):
    # Scenario: After splitting once, list_panes reports two panes.
    # Setup: session + one extra pane.
    assert tmux_newPane(tmux_session_panes) == 0
    # Test action: list panes.
    panes = tmux_listPanes(tmux_session_panes)
    # Test verification: two panes present.
    assert len(panes) == 2


@pytest.mark.live
def test_capturePane_returnsContent(tmux_session_panes):
    # Scenario: capture_pane succeeds on a live pane (returns string, possibly empty).
    # Setup: known pane id.
    pid = _first_pane_id(tmux_session_panes)
    # Test action: capture pane content.
    captured = tmux_capturePane(pid)
    # Test verification: returns a str (capture succeeded; bash test only checked rc=0).
    assert isinstance(captured, str)


@pytest.mark.live
def test_listPanes_afterKillPane_hasOnePane(tmux_session_panes):
    # Scenario: After killing the added pane, listPanes reports one pane.
    # Setup: add then kill the second pane.
    assert tmux_newPane(tmux_session_panes) == 0
    ids = tmux_listPanes(tmux_session_panes, "-F", "#{pane_id}")
    assert tmux_killPane(ids[1]) == 0
    # Test action: list panes.
    rows = tmux_listPanes(tmux_session_panes)
    # Test verification: down to one pane.
    assert len(rows) == 1
