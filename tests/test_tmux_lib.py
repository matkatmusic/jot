"""Tests for tmux_lib (and tmux-related orchestrator functions)."""
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
from unittest.mock import call, patch

import jot_plugin_orchestrator
from common.scripts import tmux_lib as _tmux_lib_mod
from common.scripts.tmux_lib import (
    tmux_cancelAndSend,
    tmux_capturePane,
    tmux_ensureKeepalivePane,
    tmux_ensureSession,
    tmux_hasSession,
    tmux_killPane,
    tmux_killSession,
    tmux_killWindow,
    tmux_listClients,
    tmux_listPanes,
    tmux_listWindows,
    tmux_newPane,
    tmux_newSession,
    tmux_newWindow,
    tmux_paneHasTitle,
    tmux_requireVersion,
    tmux_retile,
    tmux_selectLayout,
    tmux_selectPane,
    tmux_sendAndSubmit,
    tmux_sendCtrlC,
    tmux_sendEnter,
    tmux_sendKeys,
    tmux_setOption,
    tmux_setOptionForTarget,
    tmux_setOptionForWindow,
    tmux_setOptionGlobally,
    tmux_setPaneTitle,
    tmux_splitWindow,
    tmux_splitWorkerPane,
    tmux_waitForClaudeReadiness,
    tmux_windowExists,
)
from common.scripts.hookjson_lib import hookjson_checkRequirements
from common.scripts.jot_lib import jot_main

# Bind module alias used throughout the test bodies.
mod = jot_plugin_orchestrator


def _stdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    # Helper: replace sys.stdin with an in-memory buffer carrying the JSON payload.
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))


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


# --- tmux_setOption ---

class _FakeCompleted:
    """Stand-in for subprocess.CompletedProcess used by tmux_setOption tests."""

    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_tmux_setOption_invokes_tmux_set_option_with_passed_args_and_returns_zero_on_success(monkeypatch, capfd):
    # Scenario: calling tmux_setOption with scope+name+value invokes
    # `tmux set-option -g status on`, returns 0, and echoes any non-empty
    # stdout from tmux.
    # Setup: capture the cmd argv handed to subprocess.run; return a successful CompletedProcess.
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeCompleted(0, stdout="ok-out\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    # Test action: call with three positional args.
    rc = tmux_setOption("-g", "status", "on")
    out, err = capfd.readouterr()
    # Test verification: rc is 0, argv was [tmux, set-option, ...passed-args], capture flags set, stdout echoed, no stderr noise.
    assert rc == 0
    assert captured["cmd"] == ["tmux", "set-option", "-g", "status", "on"]
    assert captured["kwargs"].get("capture_output") is True
    assert captured["kwargs"].get("text") is True
    assert "ok-out" in out
    assert err == ""


def test_tmux_setOption_emits_no_output_when_tmux_succeeds_with_empty_stdout(monkeypatch, capfd):
    # Scenario: a successful tmux call that produced no stdout must produce
    # no spurious blank line on the orchestrator's stdout (mirrors bash invoke_command).
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(0, "", ""))
    rc = tmux_setOption("-g", "status", "on")
    out, err = capfd.readouterr()
    # Test verification: rc=0 and BOTH output streams are completely empty.
    assert rc == 0
    assert out == ""
    assert err == ""


def test_tmux_setOption_logs_caller_name_and_combined_output_to_stderr_when_tmux_fails(monkeypatch, capfd):
    # Scenario: when tmux returns nonzero, the function attributes the failure
    # to the immediate caller's frame name (sys._getframe(1)) and logs the
    # combined stdout+stderr to its own stderr.
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompleted(1, "", "unknown option\n")
    )

    # Setup: define a uniquely-named caller function so we can assert the
    # caller-name resolution mechanism actually works.
    def caller_frame():
        return tmux_setOption("-g", "bogus", "value")

    # Test action: invoke from caller_frame().
    rc = caller_frame()
    out, err = capfd.readouterr()
    # Test verification: rc is propagated from tmux; stderr line begins with [caller_frame]; the failed cmd and tmux's error both appear.
    assert rc == 1
    assert err.startswith("[caller_frame]")
    assert "tmux set-option -g bogus value" in err
    assert "unknown option" in err


def test_tmux_setOption_passes_variadic_args_through_to_tmux_in_order(monkeypatch):
    # Scenario: the function must NOT reorder, drop, or dedupe its variadic args -
    # they must appear in tmux's argv in the exact order supplied (proves no
    # accidental flag-collapsing or arg-massaging).
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return _FakeCompleted(0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    # Test action: pass a deliberately-jumbled set of flags+target+name+value.
    tmux_setOption("-gqu", "-t", "session:0", "mouse", "off")
    # Test verification: argv preserved verbatim after the [tmux, set-option] prefix.
    assert seen["cmd"] == ["tmux", "set-option", "-gqu", "-t", "session:0", "mouse", "off"]


# --- tmux_setOptionForTarget ---

def test_tmux_setOptionForTarget_passes_target_flag_then_target_then_name_then_value_to_tmux_setOption(monkeypatch):
    # Scenario: caller asks to set a tmux option scoped to a specific target;
    # wrapper must forward (-t, target, name, value) in that order to tmux_setOption.
    captured_args = {}

    # Setup: install a spy in place of tmux_setOption to capture forwarded args.
    def spy(*args):
        captured_args["args"] = args
        return 0
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_setOption", spy)

    # Test action: invoke the wrapper with sample target/name/value.
    tmux_setOptionForTarget("mysession", "status", "on")

    # Test verification: spy received exactly ("-t", target, name, value).
    assert captured_args["args"] == ("-t", "mysession", "status", "on")


def test_tmux_setOptionForTarget_returns_the_exit_code_from_tmux_setOption(monkeypatch):
    # Scenario: wrapper must propagate the underlying exit code unchanged so
    # callers can branch on success/failure.
    # Setup: stub returns a distinctive non-zero code.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_setOption", lambda *a: 42)

    # Test action: invoke wrapper.
    result = tmux_setOptionForTarget("win0", "remain-on-exit", "off")

    # Test verification: returned value matches the stub's return value.
    assert result == 42


# --- tmux_setOptionGlobally ---

def test_tmux_setOptionGlobally_passes_dash_g_flag_then_name_then_value_to_tmux_setOption(monkeypatch):
    # Scenario: caller asks to set a tmux option globally; wrapper must forward
    # ("-g", name, value) in that order to the underlying tmux_setOption.
    captured_args = {}

    # Setup: install a spy in place of tmux_setOption.
    def spy(*args):
        captured_args["args"] = args
        return 0
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_setOption", spy)

    # Test action: invoke the wrapper.
    tmux_setOptionGlobally("status-interval", "5")

    # Test verification: spy received exactly ("-g", name, value).
    assert captured_args["args"] == ("-g", "status-interval", "5")


def test_tmux_setOptionGlobally_returns_the_exit_code_from_tmux_setOption(monkeypatch):
    # Scenario: wrapper must propagate the underlying exit code unchanged.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_setOption", lambda *a: 42)

    # Test action: invoke wrapper.
    result = tmux_setOptionGlobally("foo", "bar")

    # Test verification: returned value equals the stub's return value.
    assert result == 42


# --- tmux_setOptionForWindow ---

def test_tmux_setOptionForWindow_passes_dash_w_then_dash_t_then_target_then_name_then_value_to_tmux_setOption(monkeypatch):
    # Scenario: wrapper must forward args as (-w, -t, target, name, value),
    # preserving bash flag order from `tmux_set_option -w -t <target> <name> <value>`.
    captured = {}

    # Setup: spy capturing all positional args passed to tmux_setOption.
    def spy(*args):
        captured["args"] = args
        return 0
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_setOption", spy)

    # Test action: invoke wrapper with representative target/name/value.
    tmux_setOptionForWindow("mywin", "remain-on-exit", "on")

    # Test verification: argv order matches bash exactly.
    assert captured["args"] == ("-w", "-t", "mywin", "remain-on-exit", "on")


def test_tmux_setOptionForWindow_returns_the_exit_code_from_tmux_setOption(monkeypatch):
    # Scenario: wrapper must propagate the callee's exit code unchanged.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_setOption", lambda *a: 42)

    # Test action: invoke wrapper.
    result = tmux_setOptionForWindow("win", "opt", "val")

    # Test verification: wrapper returns exactly what tmux_setOption returned.
    assert result == 42


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


# --- tmux_selectPane ---

def test_tmux_selectPane_invokes_tmux_select_pane_with_dash_t_target(monkeypatch):
    # Scenario: caller passes a pane target; function shells out to `tmux select-pane -t <target>` exactly.
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action: invoke under test.
    tmux_selectPane("sess:0.1")
    # Test verification: exact argv (-t flag + target placement).
    assert calls == [["tmux", "select-pane", "-t", "sess:0.1"]]


def test_tmux_selectPane_returns_zero_on_success(monkeypatch):
    # Scenario: tmux exits 0; function returns 0.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0))
    # Test action + verification.
    assert tmux_selectPane("good-target") == 0


def test_tmux_selectPane_returns_nonzero_and_logs_caller_when_select_fails(monkeypatch, capsys):
    # Scenario: tmux fails (e.g. missing pane); function returns rc and logs caller-attributed stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="can't find pane"))

    # Setup: named caller frame to assert sys._getframe(1) attribution.
    def caller_frame():
        return tmux_selectPane("missing")

    # Test action.
    rc = caller_frame()
    err = capsys.readouterr().err
    # Test verification: rc propagated; stderr names caller and tmux's stderr.
    assert rc == 1
    assert "caller_frame" in err
    assert "can't find pane" in err


# --- tmux_setPaneTitle ---

def test_tmux_setPaneTitle_invokes_tmux_select_pane_with_dash_t_target_and_dash_T_title(monkeypatch):
    # Scenario: caller sets a pane title; the underlying tmux command must use select-pane with -t <target> and -T <title>.
    calls: list = []
    # Setup: capturing fake.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action: invoke with a known pane target and title.
    tmux_setPaneTitle("%42", "my-title")
    # Test verification: argv is exactly the bash equivalent `tmux select-pane -t %42 -T my-title`.
    assert calls == [["tmux", "select-pane", "-t", "%42", "-T", "my-title"]]


def test_tmux_setPaneTitle_returns_zero_on_success(monkeypatch):
    # Scenario: tmux exits 0; wrapper propagates 0 to the caller.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0))
    # Test action + verification.
    assert tmux_setPaneTitle("%0", "title") == 0


def test_tmux_setPaneTitle_returns_nonzero_and_logs_caller_when_target_missing(monkeypatch, capsys):
    # Scenario: tmux exits nonzero (e.g. target gone); wrapper returns rc and logs caller-attributed diagnostic to stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="can't find pane"))
    # Test action: invoke from this test (caller name = test's name).
    rc = tmux_setPaneTitle("%999", "x")
    err = capsys.readouterr().err
    # Test verification: nonzero rc propagated AND stderr message tagged with calling test's name.
    assert rc == 1
    assert "[test_tmux_setPaneTitle_returns_nonzero_and_logs_caller_when_target_missing]" in err
    assert "can't find pane" in err


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


# --- tmux_selectLayout ---

def test_tmux_selectLayout_invokes_tmux_select_layout_with_dash_t_target_then_layout_name(monkeypatch):
    # Scenario: caller passes target and layout; argv is `tmux select-layout -t <target> <layout>`.
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action.
    tmux_selectLayout("session:0.0", "tiled")
    # Test verification.
    assert calls == [["tmux", "select-layout", "-t", "session:0.0", "tiled"]]


def test_tmux_selectLayout_returns_zero_on_success(monkeypatch):
    # Scenario: subprocess returns rc=0; function propagates.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0))
    # Test action + verification.
    assert tmux_selectLayout("sess:0", "even-horizontal") == 0


def test_tmux_selectLayout_returns_nonzero_and_logs_caller_when_layout_invalid(monkeypatch, capsys):
    # Scenario: tmux rejects an invalid layout (rc=1); function returns rc and logs caller-attributed stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="invalid layout: bogus"))
    # Test action.
    rc = tmux_selectLayout("sess:0", "bogus")
    err = capsys.readouterr().err
    # Test verification.
    assert rc == 1
    assert "test_tmux_selectLayout_returns_nonzero_and_logs_caller_when_layout_invalid" in err
    assert "tmux select-layout -t sess:0 bogus" in err
    assert "invalid layout: bogus" in err


# --- tmux_retile ---

def test_tmux_retile_invokes_tmux_selectLayout_with_tiled_for_the_given_target(monkeypatch):
    # Scenario: tmux_retile must delegate to tmux_selectLayout passing the literal "tiled" layout.
    calls: list = []

    # Setup: spy.
    def spy(target, layout):
        calls.append((target, layout))
        return 0

    monkeypatch.setattr("common.scripts.tmux_lib.tmux_selectLayout", spy)
    # Test action.
    tmux_retile("session:1")
    # Test verification: exactly one delegation, target verbatim, layout literal "tiled".
    assert calls == [("session:1", "tiled")]


def test_tmux_retile_returns_the_exit_code_from_tmux_selectLayout(monkeypatch):
    # Scenario: thin wrapper must propagate the callee's return value.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_selectLayout", lambda *a: 42)
    # Test action + verification.
    assert tmux_retile("any-target") == 42


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
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
    # Test action.
    tmux_sendAndSubmit("sess:0.1", "hello")
    # Test verification: order and shared pane_target.
    assert calls == [("sendKeys", "sess:0.1", "hello"), ("sendEnter", "sess:0.1")]


def test_tmux_sendAndSubmit_returns_zero_when_both_sends_succeed(monkeypatch):
    # Scenario: both sub-calls return 0; function returns 0.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendKeys", lambda p, t: 0)
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendEnter", lambda p: 0)
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
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
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
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
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
    # Test action + verification: rc equals sendEnter's rc.
    assert tmux_sendAndSubmit("p", "x") == 3


def test_tmux_sendAndSubmit_sleeps_between_sendKeys_and_sendEnter(monkeypatch):
    # Scenario: time.sleep is invoked after sendKeys and before sendEnter, with duration 0.5.
    events = []
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendKeys",
                        lambda p, t: events.append("sendKeys") or 0)
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendEnter",
                        lambda p: events.append("sendEnter") or 0)
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep",
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
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
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
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
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
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
    # Test action + verification.
    assert tmux_cancelAndSend("p", "x") == 2


def test_tmux_cancelAndSend_logs_label_when_retry_needed(monkeypatch, capsys):
    # Scenario: first capture lacks marker, second has it; label appears in stdout log.
    cap_iter = iter(["", "Ctrl-C"])
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendCtrlC", lambda p: 0)
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane",
                        lambda p, scrollback_lines=None: next(cap_iter))
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendAndSubmit", lambda p, t: 0)
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
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
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
    # Test action.
    tmux_cancelAndSend("p", "x", "work-42")
    # Test verification: log suppressed.
    out = capsys.readouterr().out
    assert "work-42" not in out


# --- tmux_splitWorkerPane ---


class _FakeCompleted:
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


# --- tmux_waitForClaudeReadiness ---


_READY_GLYPH = "❯"  # ❯


def test_tmux_waitForClaudeReadiness_returns_zero_when_glyph_present_immediately(monkeypatch):
    # Scenario: pane already shows the ready glyph; function returns 0 without sleeping.
    sleep_calls = []
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane",
                        lambda pid, lines=None: f"banner\n{_READY_GLYPH} ready\n")
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep",
                        lambda s: sleep_calls.append(s))
    # Test action.
    rc = tmux_waitForClaudeReadiness("%42", timeout=1)
    # Test verification: rc 0 and no sleep needed.
    assert rc == 0
    assert sleep_calls == []


def test_tmux_waitForClaudeReadiness_returns_one_on_timeout_and_logs_stderr(monkeypatch, capsys):
    # Scenario: glyph never appears; function times out after timeout*2 sleeps and logs to stderr.
    sleep_calls = []
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane",
                        lambda pid, lines=None: "still loading")
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep",
                        lambda s: sleep_calls.append(s))
    # Test action.
    rc = tmux_waitForClaudeReadiness("%7", timeout=2)
    err = capsys.readouterr().err
    # Test verification: rc 1, exactly 4 sleeps of 0.5s each, stderr tagged.
    assert rc == 1
    assert sleep_calls == [0.5, 0.5, 0.5, 0.5]
    assert "tmux_waitForClaudeReadiness" in err
    assert "timed out" in err
    assert "%7" in err


def test_tmux_waitForClaudeReadiness_polls_until_ready(monkeypatch):
    # Scenario: glyph appears on third poll; function returns 0 after exactly 2 sleeps.
    seq = iter(["boot", "starting", f"{_READY_GLYPH}"])
    sleep_count = {"n": 0}
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane",
                        lambda pid, lines=None: next(seq))
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep",
                        lambda s: sleep_count.__setitem__("n", sleep_count["n"] + 1))
    # Test action.
    rc = tmux_waitForClaudeReadiness("%1", timeout=5)
    # Test verification.
    assert rc == 0
    assert sleep_count["n"] == 2


def test_tmux_waitForClaudeReadiness_swallows_capture_errors(monkeypatch):
    # Scenario: capturePane raises on first attempt; loop continues and succeeds on second.
    calls = {"n": 0}
    def fake_capture(pid, lines=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return _READY_GLYPH
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane", fake_capture)
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
    # Test action + verification.
    assert tmux_waitForClaudeReadiness("%9", timeout=2) == 0
    assert calls["n"] == 2


def test_tmux_waitForClaudeReadiness_default_timeout_is_ten_seconds(monkeypatch):
    # Scenario: omitting timeout uses default 10 -> 20 attempts before returning 1.
    attempts = {"n": 0}
    def fake_capture(pid, lines=None):
        attempts["n"] += 1
        return ""
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane", fake_capture)
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
    # Test action.
    rc = tmux_waitForClaudeReadiness("%2")
    # Test verification.
    assert rc == 1
    assert attempts["n"] == 20


def test_tmux_waitForClaudeReadiness_passes_pane_id_and_five_line_window(monkeypatch):
    # Scenario: capturePane is invoked with the pane id and a 5-line window.
    seen = []
    def fake_capture(pid, lines=None):
        seen.append((pid, lines))
        return _READY_GLYPH
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane", fake_capture)
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
    # Test action.
    tmux_waitForClaudeReadiness("%55", timeout=1)
    # Test verification.
    assert seen == [("%55", 5)]


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


def test_tmux_too_old_emits_block(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: tmux_requireVersion("2.9") returns nonzero.
    # Setup: stub checkRequirements OK, tmux_requireVersion fail.
    monkeypatch.setattr("common.scripts.hookjson_lib.hookjson_checkRequirements", lambda *a, **k: None)
    monkeypatch.setattr("common.scripts.jot_lib.tmux_requireVersion", lambda _m: 1)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot something"}))
    # Test action: invoke.
    rc = mod.jot_main()
    out = capsys.readouterr().out
    # Test verification: rc=0 + tmux block.
    assert rc == 0
    assert "tmux 2.9+" in out


@pytest.mark.live
def test_setOptionForWindow_rejects_nonexistent_window(tmux_session_opts, capfd):
    # Scenario: setting a window option against a missing window fails.
    # Setup: live session exists, but target window does not.
    session = tmux_session_opts
    bogus_win = f"nosuch-{os.getpid()}"
    # Test action: attempt to set the option against the absent window.
    rc = tmux_setOptionForWindow(f"{session}:{bogus_win}", "aggressive-resize", "on")
    # Test verification: rc nonzero.
    assert rc != 0
    capfd.readouterr()



@pytest.mark.live
def test_setOptionForWindow_accepts_valid_window_option(tmux_session_opts):
    # Scenario: setting a window-scoped option on a real window succeeds.
    # Setup: create a named window inside the fixture session.
    session = tmux_session_opts
    win = f"optwin-{os.getpid()}"
    rc_new = tmux_newWindow(session, win)
    assert rc_new == 0, "precondition: tmux_newWindow should succeed"
    # Test action: set `aggressive-resize on` on the new window.
    rc = tmux_setOptionForWindow(f"{session}:{win}", "aggressive-resize", "on")
    # Test verification: tmux accepted it; rc must be 0.
    assert rc == 0

@pytest.mark.live
def test_setOptionGlobally_rejects_invalid_option(capfd):
    # Scenario: setting a fabricated global option fails.
    # Setup: no fixture state needed (global scope).
    # Test action: attempt to set an unknown option name globally.
    rc = tmux_setOptionGlobally("not-a-real-option", "foo")
    # Test verification: rc nonzero.
    assert rc != 0
    capfd.readouterr()

@pytest.mark.live
def test_setOptionGlobally_accepts_valid_global_option():
    # Scenario: setting a global option to its current value succeeds (no-op).
    # Setup: read the current global `mouse` value so we can rewrite it identically.
    proc = subprocess.run(
        ["tmux", "show-options", "-gv", "mouse"],
        capture_output=True, text=True, check=False,
    )
    current = (proc.stdout or "").strip() or "off"
    # Test action: set the global `mouse` option back to the captured value.
    rc = tmux_setOptionGlobally("mouse", current)
    # Test verification: rc must be 0.
    assert rc == 0



@pytest.mark.live
def test_setOptionForTarget_rejects_nonexistent_target(capfd):
    # Scenario: targeting a session that does not exist returns nonzero.
    # Setup: build a name guaranteed not to exist.
    bogus = f"nonexistent-{os.getpid()}"
    subprocess.run(["tmux", "kill-session", "-t", bogus],
                   capture_output=True, check=False)
    # Test action: try to set `mouse on` against the nonexistent session.
    rc = tmux_setOptionForTarget(bogus, "mouse", "on")
    # Test verification: tmux rejects unknown target; rc nonzero.
    assert rc != 0
    capfd.readouterr()



@pytest.mark.live
def test_setOptionForTarget_rejects_invalid_option(tmux_session_opts, capfd):
    # Scenario: setting an unknown option name on a live session returns nonzero.
    # Setup: live session from fixture.
    session = tmux_session_opts
    # Test action: attempt to set a fabricated option name.
    rc = tmux_setOptionForTarget(session, "not-a-real-option", "foo")
    # Test verification: tmux rejects unknown option; rc nonzero.
    assert rc != 0
    capfd.readouterr()  # drain caller-attributed stderr from helper


@pytest.mark.live
def test_setOptionForTarget_accepts_valid_session_option(tmux_session_opts):
    # Scenario: setting a real session-scoped option on a live session returns rc=0.
    # Setup: tmux_session_opts fixture provides a fresh detached session.
    session = tmux_session_opts
    # Test action: set the session-scoped `remain-on-exit` option to `off`.
    rc = tmux_setOptionForTarget(session, "remain-on-exit", "off")
    # Test verification: tmux accepted it; rc must be 0.
    assert rc == 0


@pytest.fixture
def tmux_session_opts():
    # Provide a unique, isolated tmux session for one test; tear it down on exit.
    name = f"tmux-py-opt-test-{os.getpid()}"
    subprocess.run(["tmux", "kill-session", "-t", name],
                   capture_output=True, check=False)
    rc = tmux_newSession(name)
    assert rc == 0, "fixture failed to create tmux session"
    yield name
    subprocess.run(["tmux", "kill-session", "-t", name],
                   capture_output=True, check=False)

# Skip the whole module if tmux is unavailable on this host.
pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not installed"
)


@pytest.mark.live
def test_killSession_fails_onNonexistentSession(session_name):
    # Scenario: killSession returns nonzero rc when the session does not exist.
    # Setup: fixture guarantees no session by this name exists.
    # Test action: attempt to kill a session that was never created.
    rc = tmux_killSession(session_name)
    # Test verification: nonzero rc means kill rejected.
    assert rc != 0


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
def test_newPane_addsPaneToSession(tmux_session_panes):
    # Scenario: tmux_newPane on an existing session succeeds (rc=0).
    # Setup: session exists via fixture.
    # Test action: split a new pane.
    rc = tmux_newPane(tmux_session_panes)
    # Test verification: rc 0 means tmux accepted the split.
    assert rc == 0


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
def test_selectPane_byKnownPaneId_succeeds(tmux_session_panes):
    # Scenario: select_pane targets an existing pane id and succeeds.
    # Setup: capture id of the only pane.
    pid = _first_pane_id(tmux_session_panes)
    assert pid, "precondition: a pane id must exist"
    # Test action: select that pane.
    rc = tmux_selectPane(pid)
    # Test verification: rc 0.
    assert rc == 0


@pytest.mark.live
def test_setPaneTitle_succeeds(tmux_session_panes):
    # Scenario: set_pane_title returns rc 0 on a known pane.
    # Setup: known pane id.
    pid = _first_pane_id(tmux_session_panes)
    # Test action: set a title.
    rc = tmux_setPaneTitle(pid, f"titletest-{os.getpid()}")
    # Test verification: rc 0.
    assert rc == 0


@pytest.mark.live
def test_setPaneTitle_roundTripsThroughListPanes(tmux_session_panes):
    # Scenario: Title set via setPaneTitle is visible via listPanes default -F.
    # Setup: pid + unique title.
    pid = _first_pane_id(tmux_session_panes)
    title = f"titletest-{os.getpid()}"
    assert tmux_setPaneTitle(pid, title) == 0
    # Test action: list panes (default format includes pane_title).
    rows = tmux_listPanes(tmux_session_panes)
    # Test verification: at least one row contains the new title.
    assert any(title in row for row in rows)


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


@pytest.mark.live
def test_killPane_failsOnNonexistentTarget():
    # Scenario: kill_pane on a nonexistent target returns nonzero rc.
    # Setup: bogus target name.
    bogus = f"nonexistent-{os.getpid()}"
    # Test action: attempt kill.
    rc = tmux_killPane(bogus)
    # Test verification: nonzero rc.
    assert rc != 0



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
    """Patch `_live_pane_ids` to return a configurable set without tmux."""
    state: dict[str, set[str]] = {"live": set()}

    def _fake() -> set[str]:
        return set(state["live"])


    monkeypatch.setattr("common.scripts.tmux_lib._live_pane_ids", _fake)
    return state


def _make_tmpdir(tmp_path: Path, tmux_target: str = "%42") -> Path:
    """Write a minimal per-invocation tmpdir with tmux_target sidecar."""
    d = tmp_path / "todo.XXXX"
    d.mkdir()
    (d / "tmux_target").write_text(f"{tmux_target}\n")
    return d


class FakeClock:
    """Deterministic sleep replacement that advances a virtual clock and
    optionally mutates the filesystem at scheduled tick counts."""

    def __init__(self, on_tick=None):
        self.elapsed = 0.0
        self.calls = 0
        self._on_tick = on_tick or (lambda n: None)

    def __call__(self, secs: float) -> None:
        self.calls += 1
        self.elapsed += secs
        self._on_tick(self.calls)


class FakeTmux:
    """Records every (pane, keys) tuple sent."""

    def __init__(self, raise_on_call: bool = False):
        self.sent: list[tuple[str, str]] = []
        self.raise_on_call = raise_on_call

    def __call__(self, pane: str, keys: str) -> None:
        if self.raise_on_call:
            raise RuntimeError("pane gone")
        self.sent.append((pane, keys))


