"""Pytest suite for jot_plugin_orchestrator.py.

Migrated incrementally from scripts/test_monolith.sh per
plans/it-is-time-to-jolly-blossom.md.

Every test follows ~/Programming/dotfiles/claude/RED_GREEN_TDD.md "How to write
the tests": a `# Scenario:` header naming what's being verified, then plain-
English step comments explaining what each step proves.
"""
from __future__ import annotations

import json
import hashlib
import multiprocessing
import os
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

import jot_plugin_orchestrator
from jot_plugin_orchestrator import (
    claude_buildCmd,
    claude_permseedLog,
    claude_seedPermissions,
    FileLock,
    hookjson_checkRequirements,
    hookjson_emitBlock,
    hookjson_installHint,
    LockTimeout,
    jot_initState,
    jot_buildClaudeCmd,
    jot_diagIndent,
    jot_diagKv,
    jot_diagSection,
    jot_launchPhase2Window,
    jot_popFirstFromQueue,
    jot_rotateAudit,
    jot_sendPrompt,
    shell_runWithTimeout,
    terminal_spawnIfNeeded,
    tmux_capturePane,
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
    tmux_cancelAndSend,
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
    tmux_ensureKeepalivePane,
    tmux_ensureSession,
    tmux_splitWorkerPane,
    tmux_waitForClaudeReadiness,
    tmux_windowExists,
)


# --- hookjson_emitBlock ---

def test_hookjson_emitBlock_simple_reason_roundtrips_through_json():
    # Scenario: emitting a block with a plain ASCII reason returns a JSON string
    # that, when parsed back, yields the canonical {"decision":"block","reason":...} shape.
    # Test action: call the function with a simple reason.
    result_str = hookjson_emitBlock("nope")
    # Test verification: parsing the returned string yields the exact decision/reason dict.
    assert json.loads(result_str) == {"decision": "block", "reason": "nope"}


def test_hookjson_emitBlock_quotes_in_reason_are_preserved_after_roundtrip():
    # Scenario: a reason containing double-quote characters survives JSON encode/decode
    # without corruption (proves we are not hand-rolling fragile string interpolation).
    # Setup: build a reason string containing literal double quotes.
    reason = 'he said "hi"'
    # Test action + verification: encode then decode and confirm the reason matches verbatim.
    assert json.loads(hookjson_emitBlock(reason)) == {"decision": "block", "reason": reason}


def test_hookjson_emitBlock_backslashes_in_reason_are_preserved_after_roundtrip():
    # Scenario: backslashes in the reason survive JSON encoding (the bash version had
    # explicit double-escape logic; the Python version delegates to json.dumps and
    # this test proves that delegation does not lose data).
    reason = r"path\\to\\thing"
    assert json.loads(hookjson_emitBlock(reason)) == {"decision": "block", "reason": reason}


def test_hookjson_emitBlock_unicode_in_reason_is_preserved_after_roundtrip():
    # Scenario: non-ASCII unicode in the reason survives the roundtrip.
    reason = "café - 日本語 - ✓"
    assert json.loads(hookjson_emitBlock(reason)) == {"decision": "block", "reason": reason}


def test_hookjson_emitBlock_returns_a_string_type():
    # Scenario: the function's contract is "returns a string"; this test pins the type
    # so a future refactor cannot silently start returning a dict or bytes.
    assert isinstance(hookjson_emitBlock("x"), str)


def test_hookjson_emitBlock_empty_reason_still_produces_valid_block_json():
    # Scenario: an empty-string reason is valid input and must produce a parseable
    # block-decision JSON with reason == "".
    assert json.loads(hookjson_emitBlock("")) == {"decision": "block", "reason": ""}


# --- hookjson_installHint ---

@pytest.mark.parametrize(
    "cmd,expected",
    [
        ("jq", "jq (brew install jq)"),
        ("python3", "python3 (brew install python)"),
        ("tmux", "tmux (brew install tmux)"),
        ("claude", "claude (https://claude.com/claude-code)"),
    ],
)
def test_hookjson_installHint_returns_canonical_hint_for_each_known_dependency(cmd: str, expected: str) -> None:
    # Scenario: each of the four canonical dependency names maps to its documented
    # human-readable install hint string.
    # Test action + verification: parametrized lookup returns the exact expected string.
    assert hookjson_installHint(cmd) == expected


def test_hookjson_installHint_returns_bare_command_name_for_unknown_dependency() -> None:
    # Scenario: an unknown command falls through to the bare name (mirrors bash
    # `case ... *) echo "$1"`). This is the fallback contract.
    assert hookjson_installHint("ripgrep") == "ripgrep"


def test_hookjson_installHint_handles_empty_string_input_without_crashing() -> None:
    # Scenario: empty-string input must not raise; it returns "" (the bare-name fallback).
    assert hookjson_installHint("") == ""


# --- hookjson_checkRequirements ---

def test_hookjson_checkRequirements_returns_None_silently_when_all_commands_are_present(monkeypatch, capsys):
    # Scenario: when every probed command resolves on PATH, the function returns
    # None and produces no stdout (no block-decision JSON is emitted).
    # Setup: stub shutil.which so every command appears installed.
    monkeypatch.setattr("shutil.which", lambda cmd: f"/usr/bin/{cmd}")
    # Test action: probe two commands, both present.
    result = hookjson_checkRequirements("Hook", "jq", "python3")
    # Test verification: function returned None and emitted nothing.
    assert result is None
    assert capsys.readouterr().out == ""


def test_hookjson_checkRequirements_emits_block_JSON_and_exits_zero_when_one_command_is_missing(monkeypatch, capsys):
    # Scenario: a single missing command causes the function to emit a block-decision
    # JSON to stdout naming the missing command, then sys.exit(0).
    # Setup: stub shutil.which so only "jq" is missing.
    monkeypatch.setattr("shutil.which", lambda cmd: None if cmd == "jq" else f"/bin/{cmd}")
    # Test action: probe two commands; expect SystemExit because one is missing.
    with pytest.raises(SystemExit) as exc:
        hookjson_checkRequirements("Hook", "jq", "python3")
    # Test verification: exit code is 0 (matches bash `exit 0`).
    assert exc.value.code == 0
    # Test verification: stdout contains a parseable block JSON whose reason names the prefix and the missing tool.
    payload = json.loads(capsys.readouterr().out.strip())
    reason = json.dumps(payload)
    assert "Hook" in reason
    assert "jq" in reason


def test_hookjson_checkRequirements_comma_joins_multiple_missing_commands_in_block_reason(monkeypatch, capsys):
    # Scenario: when multiple commands are missing, the block-decision reason lists
    # them all separated by commas (proves the join logic).
    # Setup: stub shutil.which so every command is missing.
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    # Test action: probe three commands; all missing.
    with pytest.raises(SystemExit) as exc:
        hookjson_checkRequirements("Pre", "jq", "tmux", "claude")
    # Test verification: exit code 0; reason contains at least two commas (3 items joined).
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    reason = json.dumps(payload)
    assert reason.count(",") >= 2
    # Test verification: every missing tool name appears in the reason.
    for tool in ("jq", "tmux", "claude"):
        assert tool in reason


def test_hookjson_checkRequirements_prepends_the_supplied_prefix_to_the_block_reason(monkeypatch, capsys):
    # Scenario: the first arg (prefix) is the human-readable label that prepends
    # the missing-deps message in the emitted reason.
    # Setup: stub shutil.which so the probed command is missing.
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    # Test action: pass a uniquely-recognizable prefix.
    with pytest.raises(SystemExit):
        hookjson_checkRequirements("MY_UNIQUE_PREFIX_XYZ", "jq")
    # Test verification: that exact prefix string appears in the emitted reason.
    payload = json.loads(capsys.readouterr().out.strip())
    assert "MY_UNIQUE_PREFIX_XYZ" in json.dumps(payload)


def test_hookjson_checkRequirements_lists_unknown_command_by_its_bare_name(monkeypatch, capsys):
    # Scenario: a missing command that has no canonical install hint still appears
    # in the reason (by its bare name; via the installHint fallback).
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    with pytest.raises(SystemExit):
        hookjson_checkRequirements("X", "totally-fake-bin-zzz")
    # Test verification: the unknown bin name appears verbatim in the reason.
    payload = json.loads(capsys.readouterr().out.strip())
    assert "totally-fake-bin-zzz" in json.dumps(payload)


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
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_setOption", spy)

    # Test action: invoke the wrapper with sample target/name/value.
    tmux_setOptionForTarget("mysession", "status", "on")

    # Test verification: spy received exactly ("-t", target, name, value).
    assert captured_args["args"] == ("-t", "mysession", "status", "on")


def test_tmux_setOptionForTarget_returns_the_exit_code_from_tmux_setOption(monkeypatch):
    # Scenario: wrapper must propagate the underlying exit code unchanged so
    # callers can branch on success/failure.
    # Setup: stub returns a distinctive non-zero code.
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_setOption", lambda *a: 42)

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
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_setOption", spy)

    # Test action: invoke the wrapper.
    tmux_setOptionGlobally("status-interval", "5")

    # Test verification: spy received exactly ("-g", name, value).
    assert captured_args["args"] == ("-g", "status-interval", "5")


def test_tmux_setOptionGlobally_returns_the_exit_code_from_tmux_setOption(monkeypatch):
    # Scenario: wrapper must propagate the underlying exit code unchanged.
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_setOption", lambda *a: 42)

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
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_setOption", spy)

    # Test action: invoke wrapper with representative target/name/value.
    tmux_setOptionForWindow("mywin", "remain-on-exit", "on")

    # Test verification: argv order matches bash exactly.
    assert captured["args"] == ("-w", "-t", "mywin", "remain-on-exit", "on")


def test_tmux_setOptionForWindow_returns_the_exit_code_from_tmux_setOption(monkeypatch):
    # Scenario: wrapper must propagate the callee's exit code unchanged.
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_setOption", lambda *a: 42)

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
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_listWindows",
                        lambda session, *args: ["main", "logs", "editor"])
    # Test action + verification: present-title yields shell-success status 0.
    assert tmux_windowExists("sess", "logs") == 0


def test_tmux_windowExists_returns_one_when_window_name_not_in_listed_windows(monkeypatch):
    # Scenario: window name absent from listed windows -> not-exists (1).
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_listWindows",
                        lambda session, *args: ["main", "editor"])
    # Test action + verification: absent yields 1.
    assert tmux_windowExists("sess", "logs") == 1


def test_tmux_windowExists_uses_exact_match_not_substring(monkeypatch):
    # Scenario: "log" must NOT match "logs" - bash grep -qx is exact-line match.
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_listWindows",
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

    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_listWindows", spy)
    # Test action.
    tmux_windowExists("my-session", "anything")
    # Test verification: session forwarded; -F '#{window_name}' supplied verbatim.
    assert captured["session"] == "my-session"
    assert captured["args"] == ("-F", "#{window_name}")


# --- tmux_paneHasTitle ---

def test_tmux_paneHasTitle_returns_zero_when_title_appears_in_listed_panes(monkeypatch):
    # Scenario: a pane title in target exactly matches the query -> 0.
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_listPanes",
                        lambda *a, **k: ["editor", "shell", "logs"])
    # Test action + verification.
    assert tmux_paneHasTitle("sess:0", "shell") == 0


def test_tmux_paneHasTitle_returns_one_when_title_not_in_listed_panes(monkeypatch):
    # Scenario: no pane in target carries the requested title -> 1.
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_listPanes",
                        lambda *a, **k: ["editor", "logs"])
    # Test action + verification.
    assert tmux_paneHasTitle("sess:0", "shell") == 1


def test_tmux_paneHasTitle_uses_exact_match_not_substring(monkeypatch):
    # Scenario: a pane title is a SUPERSTRING of the query but not equal; substring should NOT count.
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_listPanes",
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

    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_listPanes", spy)
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

    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_selectLayout", spy)
    # Test action.
    tmux_retile("session:1")
    # Test verification: exactly one delegation, target verbatim, layout literal "tiled".
    assert calls == [("session:1", "tiled")]


def test_tmux_retile_returns_the_exit_code_from_tmux_selectLayout(monkeypatch):
    # Scenario: thin wrapper must propagate the callee's return value.
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_selectLayout", lambda *a: 42)
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
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendKeys",
                        lambda p, t: calls.append(("sendKeys", p, t)) or 0)
    # Setup: stub sendEnter to record invocation and succeed.
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendEnter",
                        lambda p: calls.append(("sendEnter", p)) or 0)
    # Setup: stub sleep to avoid real delay.
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
    # Test action.
    tmux_sendAndSubmit("sess:0.1", "hello")
    # Test verification: order and shared pane_target.
    assert calls == [("sendKeys", "sess:0.1", "hello"), ("sendEnter", "sess:0.1")]


def test_tmux_sendAndSubmit_returns_zero_when_both_sends_succeed(monkeypatch):
    # Scenario: both sub-calls return 0; function returns 0.
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendKeys", lambda p, t: 0)
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendEnter", lambda p: 0)
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
    # Test action + verification: rc 0 on full success.
    assert tmux_sendAndSubmit("p", "x") == 0


def test_tmux_sendAndSubmit_short_circuits_when_sendKeys_fails(monkeypatch):
    # Scenario: sendKeys fails -> return its rc, sendEnter never called.
    enter_calls = []
    # Setup: sendKeys returns failure rc 7.
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendKeys", lambda p, t: 7)
    # Setup: sendEnter records if called (it must not be).
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendEnter",
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
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendKeys", lambda p, t: 0)
    # Setup: sendEnter returns failure rc 3.
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendEnter", lambda p: 3)
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
    # Test action + verification: rc equals sendEnter's rc.
    assert tmux_sendAndSubmit("p", "x") == 3


def test_tmux_sendAndSubmit_sleeps_between_sendKeys_and_sendEnter(monkeypatch):
    # Scenario: time.sleep is invoked after sendKeys and before sendEnter, with duration 0.5.
    events = []
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendKeys",
                        lambda p, t: events.append("sendKeys") or 0)
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendEnter",
                        lambda p: events.append("sendEnter") or 0)
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep",
                        lambda s: events.append(("sleep", s)))
    # Test action.
    tmux_sendAndSubmit("p", "x")
    # Test verification: sleep occurred strictly between the two sends with 0.5s duration.
    assert events == ["sendKeys", ("sleep", 0.5), "sendEnter"]


# --- claude_buildCmd ---


@pytest.fixture
def _hooks_file(tmp_path: Path) -> Path:
    # Setup: a hooks JSON file containing a representative hooks block.
    p = tmp_path / "hooks.json"
    p.write_text('{"SessionStart":[{"hooks":[{"type":"command","command":"x"}]}]}')
    return p


def test_claude_buildCmd_returns_command_string_with_trailing_newline(tmp_path: Path, _hooks_file: Path) -> None:
    # Scenario: caller captures the returned command for tmux.
    # Setup: minimal valid inputs.
    settings_out = tmp_path / "settings.json"
    allow_json = '["Bash(ls:*)"]'
    cwd = "/work/repo"
    # Test action: build the command with no extra dirs.
    result = claude_buildCmd(str(settings_out), allow_json, str(_hooks_file), cwd)
    # Test verification: returned string matches printf '%s\n' format.
    assert result == f"claude --settings '{settings_out}' --add-dir '{cwd}'\n"


def test_claude_buildCmd_extra_dirs_appended_in_order(tmp_path: Path, _hooks_file: Path) -> None:
    # Scenario: caller passes additional --add-dir paths positionally.
    # Setup: two extra dirs in a specific order.
    settings_out = tmp_path / "settings.json"
    # Test action: invoke with two trailing extras.
    result = claude_buildCmd(
        str(settings_out), "[]", str(_hooks_file), "/cwd", "/extra/a", "/extra/b"
    )
    # Test verification: extras appear in given order with single quotes.
    assert result.rstrip("\n").endswith(
        "--add-dir '/cwd' --add-dir '/extra/a' --add-dir '/extra/b'"
    )


def test_claude_buildCmd_writes_settings_file_with_allow_and_hooks(tmp_path: Path, _hooks_file: Path) -> None:
    # Scenario: settings file must be valid JSON merging allow_json + hooks_json.
    # Setup: realistic allow list and hooks file content.
    settings_out = tmp_path / "settings.json"
    allow_json = '["Bash(echo:*)","Read"]'
    # Test action: build command (side effect: writes settings_out).
    claude_buildCmd(str(settings_out), allow_json, str(_hooks_file), "/cwd")
    # Test verification: settings file parses and contains expected structure.
    parsed = json.loads(settings_out.read_text())
    assert parsed["permissions"]["allow"] == ["Bash(echo:*)", "Read"]
    assert parsed["hooks"] == json.loads(_hooks_file.read_text())


def test_claude_buildCmd_no_extra_dirs_omits_additional_flags(tmp_path: Path, _hooks_file: Path) -> None:
    # Scenario: zero extra positional args means only one --add-dir.
    # Setup: minimal call.
    settings_out = tmp_path / "settings.json"
    # Test action: call with no extras.
    result = claude_buildCmd(str(settings_out), "[]", str(_hooks_file), "/cwd")
    # Test verification: exactly one --add-dir token.
    assert result.count("--add-dir") == 1


def test_claude_buildCmd_missing_hooks_file_raises(tmp_path: Path) -> None:
    # Scenario: hooks_json_file does not exist; bash `cat` would fail.
    # Setup: path to nonexistent file.
    settings_out = tmp_path / "settings.json"
    missing = tmp_path / "nope.json"
    # Test action + verification: raises FileNotFoundError.
    with pytest.raises(FileNotFoundError):
        claude_buildCmd(str(settings_out), "[]", str(missing), "/cwd")


# --- tmux_cancelAndSend ---


def test_tmux_cancelAndSend_stops_retrying_once_marker_seen(monkeypatch):
    # Scenario: marker visible on second capture; loop stops after 2 Ctrl-Cs and replacement submits.
    captures = ["nothing yet", "interrupted by Ctrl-C now"]
    cap_iter = iter(captures)
    ctrlc_calls = []
    submit_calls = []
    # Setup: stub Ctrl-C, capture, submit, sleep.
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendCtrlC",
                        lambda p: ctrlc_calls.append(p) or 0)
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_capturePane",
                        lambda p, scrollback_lines=None: next(cap_iter))
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendAndSubmit",
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
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendCtrlC",
                        lambda p: ctrlc_calls.append(p) or 0)
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_capturePane",
                        lambda p, scrollback_lines=None: "busy")
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendAndSubmit",
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
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendCtrlC", lambda p: 0)
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_capturePane",
                        lambda p, scrollback_lines=None: "Ctrl-C")
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendAndSubmit", lambda p, t: 2)
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
    # Test action + verification.
    assert tmux_cancelAndSend("p", "x") == 2


def test_tmux_cancelAndSend_logs_label_when_retry_needed(monkeypatch, capsys):
    # Scenario: first capture lacks marker, second has it; label appears in stdout log.
    cap_iter = iter(["", "Ctrl-C"])
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendCtrlC", lambda p: 0)
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_capturePane",
                        lambda p, scrollback_lines=None: next(cap_iter))
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendAndSubmit", lambda p, t: 0)
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
    # Test action.
    tmux_cancelAndSend("p", "x", "work-99")
    # Test verification: label and "Ctrl-C" appear on stdout.
    out = capsys.readouterr().out
    assert "work-99" in out
    assert "Ctrl-C" in out


def test_tmux_cancelAndSend_omits_log_when_first_attempt_succeeds(monkeypatch, capsys):
    # Scenario: marker visible on first capture; no log emitted even with label.
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendCtrlC", lambda p: 0)
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_capturePane",
                        lambda p, scrollback_lines=None: "Ctrl-C done")
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendAndSubmit", lambda p, t: 0)
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
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_capturePane",
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
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_capturePane",
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
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_capturePane",
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
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_capturePane", fake_capture)
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
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_capturePane", fake_capture)
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
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_capturePane", fake_capture)
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda s: None)
    # Test action.
    tmux_waitForClaudeReadiness("%55", timeout=1)
    # Test verification.
    assert seen == [("%55", 5)]


# --- jot_initState ---


def test_jot_initState_creates_state_directory_when_missing(tmp_path: Path) -> None:
    # Scenario: caller points at a state dir that does not yet exist.
    # Setup: choose a path under tmp_path that has not been created.
    state_dir = tmp_path / "jot-state"
    assert not state_dir.exists()
    # Test action.
    jot_initState(state_dir)
    # Test verification: directory exists after the call.
    assert state_dir.is_dir()


def test_jot_initState_creates_three_tracked_files(tmp_path: Path) -> None:
    # Scenario: fresh state dir must contain the three jot tracking files.
    # Setup: empty target path.
    state_dir = tmp_path / "jot-state"
    # Test action.
    jot_initState(state_dir)
    # Test verification: each tracked file is present and empty.
    for name in ("queue.txt", "active_job.txt", "audit.log"):
        f = state_dir / name
        assert f.is_file()
        assert f.stat().st_size == 0


def test_jot_initState_preserves_existing_queue_contents(tmp_path: Path) -> None:
    # Scenario: re-running on a populated state dir must not clobber data.
    # Setup: pre-create state dir with queued work.
    state_dir = tmp_path / "jot-state"
    state_dir.mkdir()
    queue = state_dir / "queue.txt"
    queue.write_text("job-1\njob-2\n")
    # Test action.
    jot_initState(state_dir)
    # Test verification: queue contents intact.
    assert queue.read_text() == "job-1\njob-2\n"


def test_jot_initState_preserves_existing_audit_log(tmp_path: Path) -> None:
    # Scenario: audit log must survive re-init (append-only history).
    # Setup: pre-existing audit log with entries.
    state_dir = tmp_path / "jot-state"
    state_dir.mkdir()
    audit = state_dir / "audit.log"
    audit.write_text("2026-05-04 event\n")
    # Test action.
    jot_initState(state_dir)
    # Test verification: audit log untouched.
    assert audit.read_text() == "2026-05-04 event\n"


def test_jot_initState_idempotent_on_second_call(tmp_path: Path) -> None:
    # Scenario: invoking twice is a no-op beyond touch.
    # Setup: run once to establish the state dir.
    state_dir = tmp_path / "jot-state"
    jot_initState(state_dir)
    # Test action.
    jot_initState(state_dir)
    # Test verification: dir + three files still present.
    assert state_dir.is_dir()
    for name in ("queue.txt", "active_job.txt", "audit.log"):
        assert (state_dir / name).is_file()


def test_jot_initState_creates_parent_directories(tmp_path: Path) -> None:
    # Scenario: state path nested under non-existent parents.
    # Setup: deep path with no intermediate dirs.
    state_dir = tmp_path / "a" / "b" / "c" / "jot-state"
    # Test action.
    jot_initState(state_dir)
    # Test verification: full chain created and files present.
    assert state_dir.is_dir()
    assert (state_dir / "queue.txt").is_file()


def test_jot_initState_accepts_string_path(tmp_path: Path) -> None:
    # Scenario: callers pass a plain str path (parity with bash arg).
    # Setup: build str path.
    state_dir = str(tmp_path / "jot-state")
    # Test action.
    jot_initState(state_dir)
    # Test verification: behaves identically to Path input.
    assert Path(state_dir).is_dir()
    assert (Path(state_dir) / "audit.log").is_file()


def test_jot_initState_touch_refreshes_mtime_on_existing_file(tmp_path: Path) -> None:
    # Scenario: bash `touch` updates mtime; Python parity required.
    # Setup: pre-existing file with an old mtime.
    import os
    state_dir = tmp_path / "jot-state"
    state_dir.mkdir()
    queue = state_dir / "queue.txt"
    queue.write_text("x\n")
    old = 1_000_000.0
    os.utime(queue, (old, old))
    before = queue.stat().st_mtime
    # Test action.
    jot_initState(state_dir)
    # Test verification: mtime advanced.
    assert queue.stat().st_mtime > before


# --- jot_popFirstFromQueue ---


def _seed_jot_state(state_dir: Path, queue_lines: list[str]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "queue.txt").write_text(
        ("\n".join(queue_lines) + "\n") if queue_lines else ""
    )
    (state_dir / "active_job.txt").write_text("")


def test_jot_popFirstFromQueue_returns_first_line(tmp_path: Path) -> None:
    # Scenario: 3-entry queue; pop returns the first one.
    # Setup: queue with three jobs.
    state = tmp_path / "state"
    _seed_jot_state(state, ["job-a", "job-b", "job-c"])
    # Test action.
    popped = jot_popFirstFromQueue(str(state))
    # Test verification.
    assert popped == "job-a"


def test_jot_popFirstFromQueue_removes_first_line_from_queue_file(tmp_path: Path) -> None:
    # Scenario: pop must mutate queue.txt by deleting line 1.
    state = tmp_path / "state"
    _seed_jot_state(state, ["job-a", "job-b", "job-c"])
    # Test action.
    jot_popFirstFromQueue(str(state))
    # Test verification.
    assert (state / "queue.txt").read_text() == "job-b\njob-c\n"


def test_jot_popFirstFromQueue_writes_popped_line_to_active_job_file(tmp_path: Path) -> None:
    # Scenario: pop writes popped entry to active_job.txt (head -1 > active).
    state = tmp_path / "state"
    _seed_jot_state(state, ["alpha", "beta"])
    # Test action.
    jot_popFirstFromQueue(str(state))
    # Test verification.
    assert (state / "active_job.txt").read_text() == "alpha\n"


def test_jot_popFirstFromQueue_returns_none_on_empty_queue(tmp_path: Path) -> None:
    # Scenario: empty queue.txt; bash returned 1 -> Python returns None.
    state = tmp_path / "state"
    _seed_jot_state(state, [])
    # Test action + verification.
    assert jot_popFirstFromQueue(str(state)) is None


def test_jot_popFirstFromQueue_empty_queue_does_not_modify_active_job(tmp_path: Path) -> None:
    # Scenario: empty-queue branch returns early; active_job.txt untouched.
    state = tmp_path / "state"
    _seed_jot_state(state, [])
    (state / "active_job.txt").write_text("prev-job\n")
    # Test action.
    jot_popFirstFromQueue(str(state))
    # Test verification.
    assert (state / "active_job.txt").read_text() == "prev-job\n"


def test_jot_popFirstFromQueue_single_entry_queue_becomes_empty(tmp_path: Path) -> None:
    # Scenario: pop the only entry; queue.txt becomes empty.
    state = tmp_path / "state"
    _seed_jot_state(state, ["only-job"])
    # Test action.
    popped = jot_popFirstFromQueue(str(state))
    # Test verification.
    assert popped == "only-job"
    assert (state / "queue.txt").read_text() == ""


# --- jot_sendPrompt ---


def test_jot_sendPrompt_delegates_to_tmux_sendAndSubmit_with_target_and_prompt(monkeypatch):
    # Scenario: caller has tmux target + input file path; jot_sendPrompt hands control to tmux_sendAndSubmit.
    calls = []
    # Setup: patch boundary helper to observe args.
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendAndSubmit",
                        lambda p, t: calls.append((p, t)) or 0)
    # Test action.
    rc = jot_sendPrompt("jot:jots.0", "/tmp/jot.ABC123/input.txt")
    # Test verification: helper invoked with target + composed prompt.
    assert rc == 0
    assert calls == [(
        "jot:jots.0",
        "Read /tmp/jot.ABC123/input.txt and follow the instructions at the top of that file",
    )]


def test_jot_sendPrompt_returns_nonzero_when_tmux_helper_fails(monkeypatch):
    # Scenario: tmux send/submit fails; jot_sendPrompt propagates rc.
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendAndSubmit", lambda p, t: 1)
    # Test action + verification.
    assert jot_sendPrompt("jot:jots.9", "/tmp/anything.txt") == 1


def test_jot_sendPrompt_input_path_interpolated_verbatim(monkeypatch):
    # Scenario: paths with spaces/unusual chars must appear literally in the prompt.
    weird_path = "/tmp/jot dir/weird name.txt"
    seen = []
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_sendAndSubmit",
                        lambda p, t: seen.append((p, t)) or 0)
    # Test action.
    jot_sendPrompt("pane@7", weird_path)
    # Test verification.
    assert seen == [(
        "pane@7",
        f"Read {weird_path} and follow the instructions at the top of that file",
    )]


# --- jot_rotateAudit ---


def test_jot_rotateAudit_silent_noop_when_file_missing(tmp_path: Path) -> None:
    # Scenario: audit log file does not exist; rotate is a silent no-op.
    # Setup: path that is not created.
    missing = tmp_path / "audit.log"
    # Test action.
    result = jot_rotateAudit(str(missing))
    # Test verification.
    assert result is None
    assert not missing.exists()


def test_jot_rotateAudit_leaves_short_file_untouched(tmp_path: Path) -> None:
    # Scenario: log under threshold must not be modified.
    # Setup: 50 lines, default max=1000.
    audit = tmp_path / "audit.log"
    original = "\n".join(f"line{i}" for i in range(50)) + "\n"
    audit.write_text(original)
    # Test action.
    jot_rotateAudit(str(audit))
    # Test verification.
    assert audit.read_text() == original


def test_jot_rotateAudit_truncates_to_last_max_lines_when_oversized(tmp_path: Path) -> None:
    # Scenario: log exceeds max_lines; only the tail is kept.
    # Setup: 1500 lines, default max=1000.
    audit = tmp_path / "audit.log"
    audit.write_text("\n".join(f"line{i}" for i in range(1500)) + "\n")
    # Test action.
    jot_rotateAudit(str(audit))
    # Test verification.
    kept = audit.read_text().splitlines()
    assert len(kept) == 1000
    assert kept[0] == "line500"
    assert kept[-1] == "line1499"


def test_jot_rotateAudit_respects_custom_max_lines(tmp_path: Path) -> None:
    # Scenario: caller-supplied max_lines overrides default.
    # Setup: 20 lines, max=5.
    audit = tmp_path / "audit.log"
    audit.write_text("\n".join(f"l{i}" for i in range(20)) + "\n")
    # Test action.
    jot_rotateAudit(str(audit), 5)
    # Test verification.
    assert audit.read_text().splitlines() == ["l15", "l16", "l17", "l18", "l19"]


def test_jot_rotateAudit_no_trim_sidecar_left_behind(tmp_path: Path) -> None:
    # Scenario: rotation must not leave .trim sidecar in directory.
    # Setup: oversized log forcing rotation.
    audit = tmp_path / "audit.log"
    audit.write_text("\n".join(f"x{i}" for i in range(2000)) + "\n")
    # Test action.
    jot_rotateAudit(str(audit), 100)
    # Test verification: only audit.log present.
    siblings = sorted(p.name for p in tmp_path.iterdir())
    assert siblings == ["audit.log"]


# --- shell_runWithTimeout ---


@pytest.mark.live
def test_shell_runWithTimeout_returns_zero_for_successful_fast_command():
    # Scenario: command exits 0 within budget; rc=0.
    # Setup: /usr/bin/true with generous timeout.
    # Test action + verification.
    assert shell_runWithTimeout(5, ["true"]) == 0


@pytest.mark.live
def test_shell_runWithTimeout_returns_nonzero_for_failing_fast_command():
    # Scenario: command exits non-zero before timeout.
    # Test action + verification.
    rc = shell_runWithTimeout(5, ["false"])
    assert rc == 1


@pytest.mark.live
def test_shell_runWithTimeout_kills_command_that_exceeds_timeout():
    # Scenario: sleep 10 with 1s budget; expect kill within ~3s wall-clock.
    import time as _t
    start = _t.monotonic()
    # Test action.
    rc = shell_runWithTimeout(1, ["sleep", "10"])
    elapsed = _t.monotonic() - start
    # Test verification: returned well before 10s and rc nonzero.
    assert elapsed < 5.0
    assert rc != 0


@pytest.mark.live
def test_shell_runWithTimeout_returns_promptly_when_command_finishes_early():
    # Scenario: fast command must not block on the timeout.
    import time as _t
    start = _t.monotonic()
    # Test action.
    rc = shell_runWithTimeout(30, ["true"])
    elapsed = _t.monotonic() - start
    # Test verification.
    assert rc == 0
    assert elapsed < 3.0


@pytest.mark.live
def test_shell_runWithTimeout_kills_process_that_ignores_sigterm():
    # Scenario: child traps SIGTERM (mirrors gemini); SIGKILL escalation must occur.
    import time as _t
    import sys as _sys
    argv = [
        _sys.executable,
        "-c",
        "import signal, time;"
        "signal.signal(signal.SIGTERM, lambda *a: None);"
        "time.sleep(30)",
    ]
    start = _t.monotonic()
    # Test action.
    rc = shell_runWithTimeout(1, argv)
    elapsed = _t.monotonic() - start
    # Test verification: returned within a few seconds via SIGKILL.
    assert elapsed < 6.0
    assert rc != 0


# --- claude_permseedLog ---


_PERMSEED_ISO_RE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)")


def test_claude_permseedLog_no_op_when_log_file_is_none(tmp_path: Path) -> None:
    # Scenario: caller passes log_file=None; logging disabled.
    pre = sorted(tmp_path.iterdir())
    # Test action.
    claude_permseedLog("hello", None)
    # Test verification.
    assert sorted(tmp_path.iterdir()) == pre


def test_claude_permseedLog_no_op_when_log_file_is_empty_string(tmp_path: Path) -> None:
    # Scenario: empty string log_file means logging disabled.
    # Test action + verification.
    assert claude_permseedLog("hello", "") is None


def test_claude_permseedLog_writes_line_to_log_file(tmp_path: Path) -> None:
    # Scenario: normal call appends a line.
    log_file = tmp_path / "seed.log"
    # Test action.
    claude_permseedLog("seeded ok", str(log_file), log_prefix="plugin")
    # Test verification.
    contents = log_file.read_text(encoding="utf-8")
    assert contents.endswith("plugin: seeded ok\n")
    assert contents.count("\n") == 1


def test_claude_permseedLog_default_log_prefix_is_plugin(tmp_path: Path) -> None:
    # Scenario: omitting log_prefix uses default "plugin".
    log_file = tmp_path / "seed.log"
    # Test action.
    claude_permseedLog("msg", str(log_file))
    # Test verification.
    assert " plugin: msg\n" in log_file.read_text(encoding="utf-8")


def test_claude_permseedLog_custom_log_prefix_is_used(tmp_path: Path) -> None:
    # Scenario: caller-supplied prefix overrides default.
    log_file = tmp_path / "seed.log"
    # Test action.
    claude_permseedLog("hi", str(log_file), log_prefix="permseed")
    # Test verification.
    contents = log_file.read_text(encoding="utf-8")
    assert " permseed: hi\n" in contents
    assert "plugin:" not in contents


def test_claude_permseedLog_line_starts_with_iso8601_timestamp(tmp_path: Path) -> None:
    # Scenario: log line is timestamped with ISO-8601 (matches bash date -Iseconds).
    log_file = tmp_path / "seed.log"
    # Test action.
    claude_permseedLog("x", str(log_file))
    # Test verification.
    line = log_file.read_text(encoding="utf-8").rstrip("\n")
    assert _PERMSEED_ISO_RE.match(line)


def test_claude_permseedLog_appends_rather_than_overwrites(tmp_path: Path) -> None:
    # Scenario: multiple calls accumulate lines (bash uses >>).
    log_file = tmp_path / "seed.log"
    claude_permseedLog("first", str(log_file))
    # Test action.
    claude_permseedLog("second", str(log_file))
    # Test verification.
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("plugin: first")
    assert lines[1].endswith("plugin: second")


def test_claude_permseedLog_swallows_write_errors_silently(tmp_path: Path) -> None:
    # Scenario: log_file under nonexistent dir; bash swallows via 2>/dev/null || true.
    bad = tmp_path / "missing" / "seed.log"
    # Test action + verification: must NOT raise, returns None.
    assert claude_permseedLog("msg", str(bad)) is None
    assert not bad.exists()


# --- claude_seedPermissions ---

@pytest.fixture
def permissions_workspace(tmp_path: Path):
    default = tmp_path / "default.json"
    installed = tmp_path / "installed.json"
    default_sha_file = tmp_path / "default.sha256"
    prior_sha_file = tmp_path / "prior.sha256"
    log_file = tmp_path / "seed.log"
    return {
        "default": default,
        "installed": installed,
        "default_sha_file": default_sha_file,
        "prior_sha_file": prior_sha_file,
        "log_file": log_file,
    }


def test_claude_seedPermissions_missing_default_file_logs_and_returns(permissions_workspace):
    # Scenario: bundled default file does not exist on disk.
    # Setup: only create the sha-file; leave default missing.
    permissions_workspace["default_sha_file"].write_text("deadbeef\n")
    # Test action: invoke with all required paths plus a log destination.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=str(permissions_workspace["log_file"]),
    )
    # Test verification: nothing copied, no prior sha written, warning logged.
    assert not permissions_workspace["installed"].exists()
    assert not permissions_workspace["prior_sha_file"].exists()
    log_text = permissions_workspace["log_file"].read_text()
    assert "bundled permissions default missing" in log_text


def test_claude_seedPermissions_missing_default_sha_file_logs_and_returns(permissions_workspace):
    # Scenario: bundled default exists but its companion sha-file is missing.
    # Setup: write default contents only.
    permissions_workspace["default"].write_text("{}\n")
    # Test action.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=str(permissions_workspace["log_file"]),
    )
    # Test verification: still no installed file; warning surfaced via log.
    assert not permissions_workspace["installed"].exists()
    assert "cannot seed" in permissions_workspace["log_file"].read_text()


def test_claude_seedPermissions_seeds_installed_when_missing(permissions_workspace):
    # Scenario: first run on a fresh machine - no installed file present.
    # Setup: create default + its sha-file with the real digest.
    payload = b'{"allow":["Read"]}\n'
    permissions_workspace["default"].write_bytes(payload)
    expected_sha = hashlib.sha256(payload).hexdigest()
    permissions_workspace["default_sha_file"].write_text(f"{expected_sha}  default.json\n")
    # Test action.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=str(permissions_workspace["log_file"]),
    )
    # Test verification: installed copied from default; prior sha recorded.
    assert permissions_workspace["installed"].read_bytes() == payload
    assert permissions_workspace["prior_sha_file"].read_text().strip().split()[0] == expected_sha
    assert "seeded" in permissions_workspace["log_file"].read_text()


def test_claude_seedPermissions_no_op_when_installed_matches_default(permissions_workspace):
    # Scenario: installed file already byte-identical to bundled default.
    # Setup: create default; copy it to installed; record sha.
    payload = b"abc\n"
    permissions_workspace["default"].write_bytes(payload)
    permissions_workspace["installed"].write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    permissions_workspace["default_sha_file"].write_text(f"{sha}\n")
    pre_mtime = permissions_workspace["installed"].stat().st_mtime_ns
    # Test action.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=str(permissions_workspace["log_file"]),
    )
    # Test verification: file untouched, no log line emitted, no prior file written.
    assert permissions_workspace["installed"].stat().st_mtime_ns == pre_mtime
    assert not permissions_workspace["log_file"].exists() or permissions_workspace["log_file"].read_text() == ""
    assert not permissions_workspace["prior_sha_file"].exists()


def test_claude_seedPermissions_upgrades_unmodified_installed_to_new_default(permissions_workspace):
    # Scenario: bundled default has been bumped; user has not touched installed.
    # Setup: installed equals prior_sha contents; default differs.
    old = b"v1\n"
    new = b"v2-newer\n"
    permissions_workspace["installed"].write_bytes(old)
    permissions_workspace["default"].write_bytes(new)
    old_sha = hashlib.sha256(old).hexdigest()
    new_sha = hashlib.sha256(new).hexdigest()
    permissions_workspace["default_sha_file"].write_text(f"{new_sha}\n")
    permissions_workspace["prior_sha_file"].write_text(f"{old_sha}\n")
    # Test action.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=str(permissions_workspace["log_file"]),
    )
    # Test verification: installed now matches new default; prior_sha advanced; logged.
    assert permissions_workspace["installed"].read_bytes() == new
    assert permissions_workspace["prior_sha_file"].read_text().strip() == new_sha
    assert "upgraded" in permissions_workspace["log_file"].read_text()


def test_claude_seedPermissions_user_edited_installed_is_preserved_and_logged(permissions_workspace):
    # Scenario: user has hand-edited installed; bundled default also moved on.
    # Setup: three distinct shas: installed, prior, default.
    permissions_workspace["installed"].write_bytes(b"user-tweaks\n")
    permissions_workspace["default"].write_bytes(b"new-default\n")
    new_sha = hashlib.sha256(b"new-default\n").hexdigest()
    prior_sha_value = hashlib.sha256(b"original\n").hexdigest()
    permissions_workspace["default_sha_file"].write_text(f"{new_sha}\n")
    permissions_workspace["prior_sha_file"].write_text(f"{prior_sha_value}\n")
    pre_installed = permissions_workspace["installed"].read_bytes()
    # Test action.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=str(permissions_workspace["log_file"]),
    )
    # Test verification: installed bytes unchanged; prior_sha refreshed to new; log explains user-edited situation.
    assert permissions_workspace["installed"].read_bytes() == pre_installed
    assert permissions_workspace["prior_sha_file"].read_text().strip() == new_sha
    log_text = permissions_workspace["log_file"].read_text()
    assert "user-edited" in log_text
    assert "diff manually" in log_text


def test_claude_seedPermissions_user_edited_no_default_change_does_not_rewrite_prior(permissions_workspace):
    # Scenario: installed is user-edited but the bundled default is unchanged since prior_sha was recorded.
    # Setup: prior_sha == current_default_sha; installed differs from both.
    permissions_workspace["installed"].write_bytes(b"hand-edited\n")
    permissions_workspace["default"].write_bytes(b"def\n")
    def_sha = hashlib.sha256(b"def\n").hexdigest()
    permissions_workspace["default_sha_file"].write_text(f"{def_sha}\n")
    permissions_workspace["prior_sha_file"].write_text(f"{def_sha}\n")
    pre_prior_mtime = permissions_workspace["prior_sha_file"].stat().st_mtime_ns
    # Test action.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=str(permissions_workspace["log_file"]),
    )
    # Test verification: prior_sha_file untouched; installed untouched; no log.
    assert permissions_workspace["prior_sha_file"].stat().st_mtime_ns == pre_prior_mtime
    assert permissions_workspace["installed"].read_bytes() == b"hand-edited\n"
    assert not permissions_workspace["log_file"].exists() or permissions_workspace["log_file"].read_text() == ""


def test_claude_seedPermissions_log_file_none_suppresses_logging(permissions_workspace):
    # Scenario: caller opts out of logging by passing log_file=None.
    # Test action: trigger the missing-default branch which would otherwise log.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=None,
    )
    # Test verification: no log file materialized anywhere in the workspace.
    assert not permissions_workspace["log_file"].exists()


def test_claude_seedPermissions_default_sha_file_with_two_column_format_is_parsed(permissions_workspace):
    # Scenario: default_sha_file uses `shasum`-style "<sha>  <filename>" layout.
    # Setup: write two-column sha line; ensure only the hash is consumed.
    payload = b"x\n"
    sha = hashlib.sha256(payload).hexdigest()
    permissions_workspace["default"].write_bytes(payload)
    permissions_workspace["default_sha_file"].write_text(f"{sha}  default.json\n")
    # Test action: install missing path exercises the parser.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=str(permissions_workspace["log_file"]),
    )
    # Test verification: prior_sha file holds only the hash, no filename token.
    assert permissions_workspace["prior_sha_file"].read_text().strip() == sha


# --- terminal_spawnIfNeeded ---

def test_terminal_spawnIfNeeded_empty_session_raises_value_error():
    # Scenario: caller forgets the required session arg.
    # Test action + verification: ValueError surfaces.
    with pytest.raises(ValueError):
        terminal_spawnIfNeeded("")


def test_terminal_spawnIfNeeded_skips_spawn_when_clients_attached():
    # Scenario: tmux session already has an attached client.
    # Setup: stub tmux list to return a non-empty client line.
    with patch.object(jot_plugin_orchestrator, "_terminalListTmuxClients", return_value="/dev/ttys001 ...\n"), \
         patch.object(jot_plugin_orchestrator.subprocess, "Popen") as popen, \
         patch.object(jot_plugin_orchestrator.sys, "platform", "darwin"):
        # Test action: call function on darwin.
        rc = terminal_spawnIfNeeded("sess1")
    # Test verification: osascript is not spawned and success is returned.
    assert rc == 0
    popen.assert_not_called()


def test_terminal_spawnIfNeeded_darwin_spawns_osascript_with_attach_command():
    # Scenario: no clients attached, osascript present, darwin host.
    # Setup: stub list_clients empty, which() finds osascript, mock Popen.
    fake_proc = MagicMock()
    fake_proc.communicate.return_value = (b"", b"")
    with patch.object(jot_plugin_orchestrator, "_terminalListTmuxClients", return_value=""), \
         patch.object(jot_plugin_orchestrator.shutil, "which", return_value="/usr/bin/osascript"), \
         patch.object(jot_plugin_orchestrator.sys, "platform", "darwin"), \
         patch.object(jot_plugin_orchestrator.subprocess, "Popen", return_value=fake_proc) as popen:
        # Test action: call with default maximize="".
        rc = terminal_spawnIfNeeded("mySess")
    # Test verification: Popen called with osascript; script contains attach command and no maximize block.
    assert rc == 0
    args, _kwargs = popen.call_args
    assert args[0] == ["osascript"]
    sent = fake_proc.communicate.call_args.kwargs["input"].decode("utf-8")
    assert "tmux attach -t mySess" in sent
    assert "set bounds of front window" not in sent


def test_terminal_spawnIfNeeded_darwin_maximize_yes_includes_full_desktop_block():
    # Scenario: caller requests maximize="yes" for a large pane layout.
    # Setup: use darwin happy-path stubs.
    fake_proc = MagicMock()
    fake_proc.communicate.return_value = (b"", b"")
    with patch.object(jot_plugin_orchestrator, "_terminalListTmuxClients", return_value=""), \
         patch.object(jot_plugin_orchestrator.shutil, "which", return_value="/x/osascript"), \
         patch.object(jot_plugin_orchestrator.sys, "platform", "darwin"), \
         patch.object(jot_plugin_orchestrator.subprocess, "Popen", return_value=fake_proc):
        # Test action: invoke with maximize="yes".
        terminal_spawnIfNeeded("s", "/dev/null", "tmux", "yes")
    # Test verification: AppleScript stdin contains full-screen bounds assignment.
    sent = fake_proc.communicate.call_args.kwargs["input"].decode("utf-8")
    assert "set bounds of front window to screenBounds" in sent
    assert "winW to 1000" not in sent


def test_terminal_spawnIfNeeded_darwin_maximize_compact_includes_centred_1000x700_block():
    # Scenario: caller requests compact geometry for a single-pane spawner.
    # Setup: use darwin happy-path stubs.
    fake_proc = MagicMock()
    fake_proc.communicate.return_value = (b"", b"")
    with patch.object(jot_plugin_orchestrator, "_terminalListTmuxClients", return_value=""), \
         patch.object(jot_plugin_orchestrator.shutil, "which", return_value="/x/osascript"), \
         patch.object(jot_plugin_orchestrator.sys, "platform", "darwin"), \
         patch.object(jot_plugin_orchestrator.subprocess, "Popen", return_value=fake_proc):
        # Test action: invoke with maximize="compact".
        terminal_spawnIfNeeded("s", "/dev/null", "tmux", "compact")
    # Test verification: stdin includes 1000x700 centering math.
    sent = fake_proc.communicate.call_args.kwargs["input"].decode("utf-8")
    assert "winW to 1000" in sent
    assert "winH to 700" in sent


def test_terminal_spawnIfNeeded_darwin_missing_osascript_writes_advisory_and_returns_zero(tmp_path):
    # Scenario: darwin host but osascript binary is not on PATH.
    # Setup: which() returns None; real tmp log file.
    log = tmp_path / "spawn.log"
    with patch.object(jot_plugin_orchestrator, "_terminalListTmuxClients", return_value=""), \
         patch.object(jot_plugin_orchestrator.shutil, "which", return_value=None), \
         patch.object(jot_plugin_orchestrator.sys, "platform", "darwin"), \
         patch.object(jot_plugin_orchestrator.subprocess, "Popen") as popen:
        # Test action: invoke with log_file pointing at tmp file.
        rc = terminal_spawnIfNeeded("abc", str(log), "myprefix")
    # Test verification: Popen never called, advisory line appended.
    assert rc == 0
    popen.assert_not_called()
    text = log.read_text()
    assert "myprefix: osascript unavailable" in text
    assert "tmux attach -t abc" in text


def test_terminal_spawnIfNeeded_non_darwin_writes_advisory_and_does_not_spawn(tmp_path):
    # Scenario: linux host invokes the spawner.
    # Setup: sys.platform stubbed to linux; real tmp log file.
    log = tmp_path / "spawn.log"
    with patch.object(jot_plugin_orchestrator, "_terminalListTmuxClients", return_value=""), \
         patch.object(jot_plugin_orchestrator.sys, "platform", "linux"), \
         patch.object(jot_plugin_orchestrator.subprocess, "Popen") as popen:
        # Test action: invoke with custom log_prefix.
        rc = terminal_spawnIfNeeded("zzz", str(log), "plate")
    # Test verification: Popen never called, advisory contains non-Darwin.
    assert rc == 0
    popen.assert_not_called()
    text = log.read_text()
    assert "plate: non-Darwin host" in text
    assert "tmux attach -t zzz" in text


def test_terminal_spawnIfNeeded_dev_null_log_does_not_create_file(tmp_path, monkeypatch):
    # Scenario: caller passes default /dev/null log on non-darwin.
    # Setup: cwd switched to tmp_path so any accidental write would land here.
    monkeypatch.chdir(tmp_path)
    with patch.object(jot_plugin_orchestrator, "_terminalListTmuxClients", return_value=""), \
         patch.object(jot_plugin_orchestrator.sys, "platform", "linux"):
        # Test action: invoke with log_file="/dev/null".
        rc = terminal_spawnIfNeeded("s", "/dev/null", "tmux")
    # Test verification: no spurious files created in cwd; rc 0.
    assert rc == 0
    assert list(tmp_path.iterdir()) == []


def test_terminal_spawnIfNeeded_advisory_write_failure_is_swallowed():
    # Scenario: log file path is unwritable.
    # Setup: monkeypatch open() to raise OSError.
    with patch.object(jot_plugin_orchestrator, "_terminalListTmuxClients", return_value=""), \
         patch.object(jot_plugin_orchestrator.sys, "platform", "linux"), \
         patch("builtins.open", side_effect=OSError("EACCES")):
        # Test action + verification: function returns 0, no exception escapes.
        assert terminal_spawnIfNeeded("s", "/some/real/path.log", "tmux") == 0


# --- FileLock / absorbed lock helpers ---

def _hold_lock_worker(lock_path: str, hold_seconds: float, ready_path: str) -> None:
    with FileLock(lock_path, timeout=5.0):
        Path(ready_path).write_text("ready", encoding="utf-8")
        time.sleep(hold_seconds)


def _try_acquire_worker(lock_path: str, timeout: float, result_path: str) -> None:
    try:
        with FileLock(lock_path, timeout=timeout):
            Path(result_path).write_text("acquired", encoding="utf-8")
    except LockTimeout:
        Path(result_path).write_text("timeout", encoding="utf-8")


def test_FileLock_acquire_succeeds_on_fresh_path(tmp_path: Path) -> None:
    # Scenario: no holder exists; acquire on fresh path must succeed.
    # Setup: lockfile path that has never been locked.
    lock_path = tmp_path / "fresh.lock"
    # Test action: acquire the lock.
    lock = FileLock(lock_path, timeout=2.0)
    lock.acquire()
    # Test verification: lock reports acquired and lockfile exists on disk.
    try:
        assert lock.acquired is True
        assert lock_path.exists()
    finally:
        lock.release()


def test_FileLock_release_clears_acquired_state(tmp_path: Path) -> None:
    # Scenario: after release, lock object reports not-acquired.
    # Setup: acquire the lock.
    lock_path = tmp_path / "release.lock"
    lock = FileLock(lock_path, timeout=2.0).acquire()
    # Test action: release.
    lock.release()
    # Test verification: acquired flag is False.
    assert lock.acquired is False


def test_FileLock_reacquire_after_release(tmp_path: Path) -> None:
    # Scenario: same process can re-acquire after releasing.
    # Setup: acquire then release.
    lock_path = tmp_path / "reacquire.lock"
    first = FileLock(lock_path, timeout=2.0).acquire()
    first.release()
    # Test action: acquire a second time.
    second = FileLock(lock_path, timeout=2.0).acquire()
    # Test verification: second acquire succeeds.
    try:
        assert second.acquired is True
    finally:
        second.release()


def test_FileLock_release_is_idempotent_when_not_held(tmp_path: Path) -> None:
    # Scenario: releasing a never-acquired FileLock is a no-op.
    # Setup: construct without acquiring.
    lock = FileLock(tmp_path / "never.lock", timeout=1.0)
    # Test action + verification: release does not raise.
    lock.release()
    assert lock.acquired is False


def test_FileLock_competing_process_blocks_until_holder_releases(tmp_path: Path) -> None:
    # Scenario: a second process blocks while the first holds the lock, then succeeds once released.
    # Setup: spawn holder worker that grabs the lock for 0.6s.
    lock_path = str(tmp_path / "competing.lock")
    ready_path = str(tmp_path / "ready.flag")
    result_path = str(tmp_path / "result.txt")
    ctx = multiprocessing.get_context("spawn")
    holder = ctx.Process(target=_hold_lock_worker, args=(lock_path, 0.6, ready_path))
    holder.start()
    try:
        deadline = time.monotonic() + 3.0
        while not Path(ready_path).exists():
            if time.monotonic() >= deadline:
                pytest.fail("holder process never signalled ready")
            time.sleep(0.02)
        # Test action: contender tries to acquire with a timeout longer than the hold.
        contender = ctx.Process(target=_try_acquire_worker, args=(lock_path, 3.0, result_path))
        start = time.monotonic()
        contender.start()
        contender.join(timeout=5.0)
        elapsed = time.monotonic() - start
        # Test verification: contender eventually acquired and had to wait for the holder.
        assert contender.exitcode == 0
        assert Path(result_path).read_text(encoding="utf-8") == "acquired"
        assert elapsed >= 0.4, f"contender acquired too fast: {elapsed:.3f}s"
    finally:
        holder.join(timeout=5.0)
        if holder.is_alive():
            holder.terminate()


def test_FileLock_timeout_elapses_when_lock_is_held(tmp_path: Path) -> None:
    # Scenario: contender with a short timeout raises LockTimeout while holder still owns the lock.
    # Setup: holder grabs the lock for 2s.
    lock_path = str(tmp_path / "timeout.lock")
    ready_path = str(tmp_path / "ready.flag")
    result_path = str(tmp_path / "result.txt")
    ctx = multiprocessing.get_context("spawn")
    holder = ctx.Process(target=_hold_lock_worker, args=(lock_path, 2.0, ready_path))
    holder.start()
    try:
        deadline = time.monotonic() + 3.0
        while not Path(ready_path).exists():
            if time.monotonic() >= deadline:
                pytest.fail("holder process never signalled ready")
            time.sleep(0.02)
        # Test action: contender with timeout far shorter than the hold.
        contender = ctx.Process(target=_try_acquire_worker, args=(lock_path, 0.3, result_path))
        start = time.monotonic()
        contender.start()
        contender.join(timeout=5.0)
        elapsed = time.monotonic() - start
        # Test verification: timeout is reported and the elapsed wall time matches the short timeout.
        assert contender.exitcode == 0
        assert Path(result_path).read_text(encoding="utf-8") == "timeout"
        assert 0.25 <= elapsed < 1.5, f"timeout window wrong: {elapsed:.3f}s"
    finally:
        holder.join(timeout=5.0)
        if holder.is_alive():
            holder.terminate()


def test_FileLock_auto_released_when_holder_process_dies(tmp_path: Path) -> None:
    # Scenario: flock auto-releases if holder exits without an explicit release.
    # Setup: holder acquires briefly, then exits cleanly.
    lock_path = str(tmp_path / "autorelease.lock")
    ready_path = str(tmp_path / "ready.flag")
    ctx = multiprocessing.get_context("spawn")
    holder = ctx.Process(target=_hold_lock_worker, args=(lock_path, 0.1, ready_path))
    holder.start()
    holder.join(timeout=5.0)
    # Test action: after holder is reaped, acquire in this process.
    assert holder.exitcode == 0
    lock = FileLock(lock_path, timeout=2.0).acquire()
    # Test verification: lock acquired without timeout.
    try:
        assert lock.acquired is True
    finally:
        lock.release()


# --- jot_buildClaudeCmd ---

@pytest.fixture
def plugin_layout(tmp_path: Path):
    # Setup: synthesize a plugin root with the orchestrator script and bundled permissions defaults.
    plugin_root = tmp_path / "plugin_root"
    plugin_data = tmp_path / "plugin_data"
    (plugin_root / "scripts").mkdir(parents=True)
    (plugin_root / "skills/jot/scripts/assets").mkdir(parents=True)
    (plugin_root / "scripts/jot-plugin-orchestrator.sh").write_text("# fake orchestrator\n")
    (plugin_root / "skills/jot/scripts/assets/permissions.default.json").write_text("{}")
    (plugin_root / "skills/jot/scripts/assets/permissions.default.json.sha256").write_text("deadbeef")

    fixed_tmp = tmp_path / "jot.ABCDEF"
    fixed_tmp.mkdir()

    seed_calls: list[tuple] = []
    expand_calls: list[tuple] = []

    def fake_seed(perm_file, default_file, default_sha, prior_sha, log_file, label):
        seed_calls.append((perm_file, default_file, default_sha, prior_sha, log_file, label))
        Path(perm_file).write_text('{"permissions":{"allow":[]}}')
        return 0

    def fake_expand(perm_file, env):
        expand_calls.append((perm_file, dict(env)))
        return '["Bash(echo:*)", "Read(*)"]'

    return {
        "plugin_root": plugin_root,
        "plugin_data": plugin_data,
        "tmp_inv": fixed_tmp,
        "seed_calls": seed_calls,
        "expand_calls": expand_calls,
        "fake_seed": fake_seed,
        "fake_expand": fake_expand,
    }


def _invoke_jot_build(layout, **overrides):
    kwargs = dict(
        claude_plugin_root=str(layout["plugin_root"]),
        claude_plugin_data=str(layout["plugin_data"]),
        cwd="/work/proj",
        repo_root="/work/proj",
        home="/Users/x",
        input_file="/work/proj/Todos/2026_input.txt",
        state_dir="/work/proj/Todos/.jot-state",
        log_file=str(layout["plugin_data"] / "jot-log.txt"),
        permissions_seed=layout["fake_seed"],
        expand_permissions=layout["fake_expand"],
        tmpdir_factory=lambda: str(layout["tmp_inv"]),
    )
    kwargs.update(overrides)
    return jot_buildClaudeCmd(**kwargs)


def test_jot_buildClaudeCmd_returns_tmpdir_inv_from_factory(plugin_layout):
    # Scenario: bash mktemp -d is replaced by injectable tmpdir_factory.
    # Test action: invoke jot_buildClaudeCmd.
    out = _invoke_jot_build(plugin_layout)
    # Test verification: returned TMPDIR_INV is the factory's directory.
    assert out["TMPDIR_INV"] == str(plugin_layout["tmp_inv"])


def test_jot_buildClaudeCmd_settings_file_lives_under_tmpdir(plugin_layout):
    # Scenario: bash sets SETTINGS_FILE="$TMPDIR_INV/settings.json".
    # Test action: invoke.
    out = _invoke_jot_build(plugin_layout)
    # Test verification: SETTINGS_FILE path equals tmpdir_inv/settings.json.
    assert out["SETTINGS_FILE"] == f"{plugin_layout['tmp_inv']}/settings.json"


def test_jot_buildClaudeCmd_permissions_file_under_plugin_data(plugin_layout):
    # Scenario: bash sets PERMISSIONS_FILE="$CLAUDE_PLUGIN_DATA/permissions.local.json".
    # Test action: invoke.
    out = _invoke_jot_build(plugin_layout)
    # Test verification: PERMISSIONS_FILE path resolves under plugin_data.
    assert out["PERMISSIONS_FILE"] == f"{plugin_layout['plugin_data']}/permissions.local.json"


def test_jot_buildClaudeCmd_orchestrator_script_copied_into_tmpdir(plugin_layout):
    # Scenario: lifecycle-safe copy of orchestrator script into tmpdir.
    # Test action: invoke.
    _invoke_jot_build(plugin_layout)
    # Test verification: tmpdir copy exists and matches source bytes.
    copied = plugin_layout["tmp_inv"] / "jot-plugin-orchestrator.sh"
    assert copied.read_text() == "# fake orchestrator\n"


def test_jot_buildClaudeCmd_plugin_data_dir_is_created(plugin_layout):
    # Scenario: bash `mkdir -p "$CLAUDE_PLUGIN_DATA"` ensures the dir exists.
    # Setup: plugin_data does not exist before invoke.
    assert not plugin_layout["plugin_data"].exists()
    # Test action: invoke.
    _invoke_jot_build(plugin_layout)
    # Test verification: plugin_data exists as a directory afterwards.
    assert plugin_layout["plugin_data"].is_dir()


def test_jot_buildClaudeCmd_permissions_seed_invoked_with_expected_args(plugin_layout):
    # Scenario: function delegates seeding to permissions_seed dependency.
    # Test action: invoke.
    _invoke_jot_build(plugin_layout)
    # Test verification: seed called once with the six bash args in order.
    calls = plugin_layout["seed_calls"]
    assert len(calls) == 1
    perm_file, default_file, default_sha, prior_sha, log_file, label = calls[0]
    assert perm_file == f"{plugin_layout['plugin_data']}/permissions.local.json"
    assert default_file == f"{plugin_layout['plugin_root']}/skills/jot/scripts/assets/permissions.default.json"
    assert default_sha == default_file + ".sha256"
    assert prior_sha == f"{plugin_layout['plugin_data']}/permissions.default.sha256"
    assert label == "jot"


def test_jot_buildClaudeCmd_expand_permissions_receives_cwd_home_repo_root(plugin_layout):
    # Scenario: bash exports CWD/HOME/REPO_ROOT before running the python helper.
    # Test action: invoke with distinct values.
    _invoke_jot_build(plugin_layout, cwd="/A", home="/B", repo_root="/C")
    # Test verification: env contains all three keys with the input values.
    perm_file, env = plugin_layout["expand_calls"][0]
    assert env["CWD"] == "/A"
    assert env["HOME"] == "/B"
    assert env["REPO_ROOT"] == "/C"
    assert perm_file == f"{plugin_layout['plugin_data']}/permissions.local.json"


def test_jot_buildClaudeCmd_hooks_json_file_is_written_and_valid_json(plugin_layout):
    # Scenario: bash writes hooks.json via heredoc into TMPDIR_INV.
    # Test action: invoke.
    out = _invoke_jot_build(plugin_layout)
    # Test verification: hooks.json exists, parses, and has the three hook keys.
    hooks_path = Path(out["HOOKS_JSON_FILE"])
    assert hooks_path == plugin_layout["tmp_inv"] / "hooks.json"
    parsed = json.loads(hooks_path.read_text())
    assert set(parsed.keys()) == {"SessionStart", "Stop", "SessionEnd"}


def test_jot_buildClaudeCmd_hooks_json_session_start_command_includes_input_file_and_tmpdir(plugin_layout):
    # Scenario: SessionStart hook command embeds INPUT_FILE and TMPDIR_INV.
    # Test action: parse generated hooks.json.
    out = _invoke_jot_build(plugin_layout, input_file="/p/Todos/IN.txt")
    # Test verification: SessionStart command string contains both paths.
    parsed = json.loads(Path(out["HOOKS_JSON_FILE"]).read_text())
    cmd = parsed["SessionStart"][0]["hooks"][0]["command"]
    assert "/p/Todos/IN.txt" in cmd
    assert str(plugin_layout["tmp_inv"]) in cmd
    assert "jot-session-start" in cmd


def test_jot_buildClaudeCmd_hooks_json_stop_command_includes_state_dir(plugin_layout):
    # Scenario: Stop hook is the only hook that gets the state_dir argument.
    # Test action: parse hooks.json.
    out = _invoke_jot_build(plugin_layout, state_dir="/p/Todos/.jot-state")
    # Test verification: Stop command contains state_dir; SessionEnd does not.
    parsed = json.loads(Path(out["HOOKS_JSON_FILE"]).read_text())
    stop_cmd = parsed["Stop"][0]["hooks"][0]["command"]
    end_cmd = parsed["SessionEnd"][0]["hooks"][0]["command"]
    assert "/p/Todos/.jot-state" in stop_cmd
    assert "/p/Todos/.jot-state" not in end_cmd


def test_jot_buildClaudeCmd_claude_cmd_contains_settings_and_cwd(plugin_layout):
    # Scenario: final CLAUDE_CMD comes from claude_buildCmd.
    # Test action: invoke.
    out = _invoke_jot_build(plugin_layout, cwd="/work/abc")
    # Test verification: CLAUDE_CMD string contains settings path and cwd.
    assert out["SETTINGS_FILE"] in out["CLAUDE_CMD"]
    assert "/work/abc" in out["CLAUDE_CMD"]
    assert out["CLAUDE_CMD"].startswith("claude ")


def test_jot_buildClaudeCmd_settings_file_written_with_expanded_allow_json(plugin_layout):
    # Scenario: claude_buildCmd writes settings JSON containing expanded allow JSON.
    # Test action: invoke.
    out = _invoke_jot_build(plugin_layout)
    # Test verification: settings.json on disk contains the sentinel allow entries.
    body = Path(out["SETTINGS_FILE"]).read_text()
    assert '"Bash(echo:*)"' in body
    assert '"Read(*)"' in body


# --- tmux_ensureKeepalivePane ---

def test_tmux_ensureKeepalivePane_returns_early_when_pane_with_title_exists():
    # Scenario: the target window already hosts a pane with the requested title.
    # Setup: stub tmux_paneHasTitle to return rc 0 and spy on creation helpers.
    with patch.object(jot_plugin_orchestrator, "tmux_paneHasTitle", return_value=0) as has_title, \
         patch.object(jot_plugin_orchestrator, "tmux_splitWorkerPane") as split_worker, \
         patch.object(jot_plugin_orchestrator, "tmux_setPaneTitle") as set_title, \
         patch.object(jot_plugin_orchestrator, "tmux_retile") as retile:
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
    with patch.object(jot_plugin_orchestrator, "tmux_paneHasTitle", return_value=1), \
         patch.object(jot_plugin_orchestrator, "tmux_splitWorkerPane", return_value="%42") as split_worker, \
         patch.object(jot_plugin_orchestrator, "tmux_setPaneTitle") as set_title, \
         patch.object(jot_plugin_orchestrator, "tmux_retile") as retile:
        # Test action: ensure on an empty window.
        tmux_ensureKeepalivePane("sess:win", "/work", "sleep 9999", "keepalive")
    # Test verification: pane created with cwd and command; title/retile invoked.
    split_worker.assert_called_once_with("sess:win", "/work", "sleep 9999")
    set_title.assert_called_once_with("%42", "keepalive")
    retile.assert_called_once_with("sess:win")


def test_tmux_ensureKeepalivePane_skips_set_title_when_split_returns_none():
    # Scenario: split helper fails and yields no pane id.
    # Setup: pane absent; split returns None.
    with patch.object(jot_plugin_orchestrator, "tmux_paneHasTitle", return_value=1), \
         patch.object(jot_plugin_orchestrator, "tmux_splitWorkerPane", return_value=None) as split_worker, \
         patch.object(jot_plugin_orchestrator, "tmux_setPaneTitle") as set_title, \
         patch.object(jot_plugin_orchestrator, "tmux_retile") as retile:
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
    with patch.object(jot_plugin_orchestrator, "tmux_hasSession", return_value=1) as has_session, \
         patch.object(jot_plugin_orchestrator, "tmux_newSession") as new_session, \
         patch.object(jot_plugin_orchestrator, "tmux_setOptionForTarget") as set_option, \
         patch.object(jot_plugin_orchestrator, "tmux_setPaneTitle") as set_title, \
         patch.object(jot_plugin_orchestrator, "tmux_windowExists") as window_exists, \
         patch.object(jot_plugin_orchestrator, "tmux_newWindow") as new_window, \
         patch.object(jot_plugin_orchestrator, "tmux_ensureKeepalivePane") as ensure_keepalive:
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
    with patch.object(jot_plugin_orchestrator, "tmux_hasSession", return_value=0), \
         patch.object(jot_plugin_orchestrator, "tmux_windowExists", return_value=1), \
         patch.object(jot_plugin_orchestrator, "tmux_newSession") as new_session, \
         patch.object(jot_plugin_orchestrator, "tmux_setOptionForTarget") as set_option, \
         patch.object(jot_plugin_orchestrator, "tmux_newWindow") as new_window, \
         patch.object(jot_plugin_orchestrator, "tmux_setPaneTitle") as set_title, \
         patch.object(jot_plugin_orchestrator, "tmux_ensureKeepalivePane") as ensure_keepalive:
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
    with patch.object(jot_plugin_orchestrator, "tmux_hasSession", return_value=0), \
         patch.object(jot_plugin_orchestrator, "tmux_windowExists", return_value=0), \
         patch.object(jot_plugin_orchestrator, "tmux_newSession") as new_session, \
         patch.object(jot_plugin_orchestrator, "tmux_newWindow") as new_window, \
         patch.object(jot_plugin_orchestrator, "tmux_setOptionForTarget") as set_option, \
         patch.object(jot_plugin_orchestrator, "tmux_setPaneTitle") as set_title, \
         patch.object(jot_plugin_orchestrator, "tmux_ensureKeepalivePane") as ensure_keepalive:
        # Test action: invoke ensure-session.
        rc = tmux_ensureSession("sess", "win", "/d", "sleep 2", "KA3")
    # Test verification: only ensureKeepalivePane invoked with target sess:win.
    assert rc == 0
    new_session.assert_not_called()
    new_window.assert_not_called()
    set_option.assert_not_called()
    set_title.assert_not_called()
    ensure_keepalive.assert_called_once_with("sess:win", "/d", "sleep 2", "KA3")


# --- jot_launchPhase2Window ---

@pytest.fixture
def phase2_env(tmp_path: Path, monkeypatch):
    # Setup: realistic env vars and tmpdirs the function reads.
    repo_root = tmp_path / "repo"
    plugin_data = tmp_path / "plugin_data"
    plugin_root = tmp_path / "plugin_root"
    repo_root.mkdir()
    plugin_data.mkdir()
    plugin_root.mkdir()
    log_file = tmp_path / "jot.log"
    log_file.touch()
    monkeypatch.setenv("REPO_ROOT", str(repo_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CWD", str(repo_root))
    monkeypatch.setenv("LOG_FILE", str(log_file))
    monkeypatch.setenv("INPUT_FILE", str(repo_root / "Todos" / "input.txt"))
    monkeypatch.setenv("HOME", "/Users/tester")
    return {
        "repo_root": repo_root,
        "plugin_data": plugin_data,
        "plugin_root": plugin_root,
        "log_file": log_file,
    }


def _phase2_patches(tmp_path: Path):
    tmpdir_inv = tmp_path / "tmpinv"
    tmpdir_inv.mkdir()
    lock_obj = MagicMock()
    lock_obj.__enter__.return_value = lock_obj
    return {
        "tmpdir_inv": tmpdir_inv,
        "lock_obj": lock_obj,
        "file_lock": patch.object(jot_plugin_orchestrator, "FileLock", return_value=lock_obj),
        "state_init": patch.object(jot_plugin_orchestrator, "jot_initState"),
        "build_cmd": patch.object(
            jot_plugin_orchestrator,
            "jot_buildClaudeCmd",
            return_value={
                "TMPDIR_INV": str(tmpdir_inv),
                "SETTINGS_FILE": "/tmp/x/settings.json",
                "CLAUDE_CMD": "claude --foo",
            },
        ),
        "ensure": patch.object(jot_plugin_orchestrator, "tmux_ensureSession", return_value=0),
        "split": patch.object(jot_plugin_orchestrator, "tmux_splitWorkerPane", return_value="%42"),
        "title": patch.object(jot_plugin_orchestrator, "tmux_setPaneTitle", return_value=0),
        "retile": patch.object(jot_plugin_orchestrator, "tmux_retile", return_value=0),
        "spawn": patch.object(jot_plugin_orchestrator, "terminal_spawnIfNeeded", return_value=0),
    }


def _enter_phase2_patches(patches: dict):
    entered = {}
    for key, value in patches.items():
        if key in {"tmpdir_inv", "lock_obj"}:
            entered[key] = value
        else:
            entered[key] = value.__enter__()
    return entered


def _exit_phase2_patches(patches: dict) -> None:
    for key, value in patches.items():
        if key not in {"tmpdir_inv", "lock_obj"}:
            value.__exit__(None, None, None)


def test_jot_launchPhase2Window_initializes_state_dir_under_repo_root_todos(phase2_env, tmp_path: Path):
    # Scenario: function derives STATE_DIR=$REPO_ROOT/Todos/.jot-state and initializes it.
    # Setup: patch external tmux/build/lock boundaries.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: state init receives the derived state directory.
        expected = str(phase2_env["repo_root"] / "Todos" / ".jot-state")
        m["state_init"].assert_called_once_with(expected)
        assert os.environ["STATE_DIR"] == expected
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_acquires_global_tmux_lock_with_10s_timeout(phase2_env, tmp_path: Path):
    # Scenario: function must hold the global tmux-launch lock during pane spawn.
    # Setup: patch external boundaries.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: FileLock constructed for the global lock path with timeout 10.
        expected_lock = str(phase2_env["plugin_data"] / "tmux-launch.lock")
        m["file_lock"].assert_called_once_with(expected_lock, timeout=10)
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_returns_1_if_lock_acquire_times_out(phase2_env):
    # Scenario: lock contention prevents tmux launch.
    # Setup: FileLock construction raises LockTimeout.
    with patch.object(jot_plugin_orchestrator, "FileLock", side_effect=LockTimeout), \
         patch.object(jot_plugin_orchestrator, "tmux_ensureSession") as ensure, \
         patch.object(jot_plugin_orchestrator, "tmux_splitWorkerPane") as split, \
         patch.object(jot_plugin_orchestrator, "jot_buildClaudeCmd") as build_cmd:
        # Test action: launch phase 2.
        rc = jot_launchPhase2Window()
    # Test verification: returns failure and does not reach tmux/build calls.
    assert rc == 1
    ensure.assert_not_called()
    split.assert_not_called()
    build_cmd.assert_not_called()
    assert "failed to acquire global tmux-launch lock" in phase2_env["log_file"].read_text()


def test_jot_launchPhase2Window_pane_counter_increments_modulo_20(phase2_env, tmp_path: Path):
    # Scenario: counter file holds 7, so next pane label is jot8.
    # Setup: seed pane-counter.txt.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    counter = phase2_env["plugin_data"] / "pane-counter.txt"
    counter.write_text("7\n")
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: counter increments and pane title uses jot8.
        assert counter.read_text().strip() == "8"
        m["title"].assert_called_once_with("%42", "jot8")
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_pane_counter_wraps_from_20_to_1(phase2_env, tmp_path: Path):
    # Scenario: counter at 20 wraps to 1.
    # Setup: seed pane-counter.txt with 20.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    counter = phase2_env["plugin_data"] / "pane-counter.txt"
    counter.write_text("20\n")
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: counter wraps and pane title uses jot1.
        assert counter.read_text().strip() == "1"
        m["title"].assert_called_once_with("%42", "jot1")
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_split_failure_releases_lock_and_returns_1(phase2_env, tmp_path: Path):
    # Scenario: tmux_splitWorkerPane returns None.
    # Setup: patch split failure.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    m["split"].return_value = None
    try:
        # Test action: launch phase 2.
        rc = jot_launchPhase2Window()
        # Test verification: lock context exits, no title/retile/spawn occurs, rc=1.
        assert rc == 1
        m["lock_obj"].__exit__.assert_called_once()
        m["title"].assert_not_called()
        m["retile"].assert_not_called()
        m["spawn"].assert_not_called()
        assert "tmux split-window returned empty pane id" in phase2_env["log_file"].read_text()
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_writes_pane_id_atomically_via_tmp_then_rename(phase2_env, tmp_path: Path):
    # Scenario: PANE_ID must be written through a temp file then renamed to tmux_target.
    # Setup: normal patched launch.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: target file has pane id and temp file is gone.
        target_file = m["tmpdir_inv"] / "tmux_target"
        tmp_file = m["tmpdir_inv"] / "tmux_target.tmp"
        assert target_file.read_text().strip() == "%42"
        assert not tmp_file.exists()
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_calls_tmux_helpers_in_required_order(phase2_env, tmp_path: Path):
    # Scenario: ordering invariant is ensureSession, split, title, retile, lock release, spawn.
    # Setup: attach mocks to a parent recorder.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    parent = MagicMock()
    parent.attach_mock(m["ensure"], "ensure")
    parent.attach_mock(m["split"], "split")
    parent.attach_mock(m["title"], "title")
    parent.attach_mock(m["retile"], "retile")
    parent.attach_mock(m["lock_obj"].__exit__, "lock_exit")
    parent.attach_mock(m["spawn"], "spawn")
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: ordering preserves lock release before terminal spawn.
        seq = [c[0] for c in parent.mock_calls if c[0] in {"ensure", "split", "title", "retile", "lock_exit", "spawn"}]
        assert seq == ["ensure", "split", "title", "retile", "lock_exit", "spawn"]
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_ensure_session_called_with_jot_jots_session_window(phase2_env, tmp_path: Path):
    # Scenario: ensureSession targets session jot and window jots with cwd plus keepalive command.
    # Setup: normal patched launch.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: ensureSession arguments match the shared jot tmux window contract.
        args = m["ensure"].call_args.args
        assert args[0] == "jot"
        assert args[1] == "jots"
        assert args[2] == str(phase2_env["repo_root"])
        assert "keepalive" in args[3].lower()
        assert args[4] == "jot: keepalive"
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_split_worker_called_with_built_claude_cmd(phase2_env, tmp_path: Path):
    # Scenario: split worker pane receives CLAUDE_CMD from jot_buildClaudeCmd.
    # Setup: customize build result command.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    m["build_cmd"].return_value = {
        "TMPDIR_INV": str(m["tmpdir_inv"]),
        "SETTINGS_FILE": "/tmp/x/settings.json",
        "CLAUDE_CMD": "claude --custom-arg",
    }
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: split worker uses the command from build result.
        m["split"].assert_called_once_with("jot:jots", str(phase2_env["repo_root"]), "claude --custom-arg")
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_spawn_terminal_called_after_lock_released(phase2_env, tmp_path: Path):
    # Scenario: terminal spawn is invoked after lock-protected tmux setup.
    # Setup: normal patched launch.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: terminal spawner gets session, log file, and prefix.
        m["spawn"].assert_called_once_with("jot", str(phase2_env["log_file"]), "jot")
    finally:
        _exit_phase2_patches(p)


# --- jot_diagSection ---


def test_jot_diagSection_starts_with_leading_newline() -> None:
    # Scenario: section banner must visually separate from prior output.
    # Setup + Test action.
    out = jot_diagSection("Foo")
    # Test verification: leading newline.
    assert out.startswith("\n")


def test_jot_diagSection_embeds_title_between_rules() -> None:
    # Scenario: title sandwiched between two identical horizontal rules.
    out = jot_diagSection("Section 1")
    # Test verification: exact 4-line layout.
    lines = out.split("\n")
    rule = "═" * 59
    assert lines[1] == rule
    assert lines[2] == "Section 1"
    assert lines[3] == rule


def test_jot_diagSection_rule_is_59_box_chars() -> None:
    # Scenario: rule width is exactly 59 U+2550 chars (bash hardcode).
    out = jot_diagSection("X")
    # Test verification.
    rule_line = out.split("\n")[1]
    assert len(rule_line) == 59
    assert set(rule_line) == {"═"}


def test_jot_diagSection_ends_with_trailing_newline() -> None:
    # Scenario: banner ends with \n so subsequent text starts on its own line.
    # Test action + verification.
    assert jot_diagSection("X").endswith("\n")


def test_jot_diagSection_preserves_empty_title() -> None:
    # Scenario: empty title still produces well-formed banner with 4 newlines.
    # Test action + verification.
    assert jot_diagSection("").count("\n") == 4


# --- jot_diagIndent ---


def test_jot_diagIndent_single_line_no_trailing_newline() -> None:
    # Scenario: single line, no trailing newline.
    # Test action + verification.
    assert jot_diagIndent("hello") == "  hello"


def test_jot_diagIndent_multiline_preserves_trailing_newline() -> None:
    # Scenario: typical command output with trailing newline.
    # Test action + verification.
    assert jot_diagIndent("a\nb\n") == "  a\n  b\n"


def test_jot_diagIndent_multiline_no_trailing_newline() -> None:
    # Scenario: text without trailing newline (e.g. captured via $(...)).
    # Test action + verification.
    assert jot_diagIndent("a\nb") == "  a\n  b"


def test_jot_diagIndent_blank_line_still_prefixed() -> None:
    # Scenario: blank lines also get 2-space prefix (matches sed).
    # Test action + verification.
    assert jot_diagIndent("a\n\nb\n") == "  a\n  \n  b\n"


def test_jot_diagIndent_empty_string_returns_empty() -> None:
    # Scenario: empty input -> empty output.
    # Test action + verification.
    assert jot_diagIndent("") == ""


def test_jot_diagIndent_only_newline() -> None:
    # Scenario: lone newline -> single empty line gets prefix.
    # Test action + verification.
    assert jot_diagIndent("\n") == "  \n"


# --- jot_diagKv ---


def test_jot_diagKv_short_key_left_padded_to_28() -> None:
    # Scenario: short key padded with spaces to width 28 + separator + value.
    # Test action + verification.
    assert jot_diagKv("path", "/tmp/x") == "path" + " " * 24 + " /tmp/x\n"


def test_jot_diagKv_value_starts_at_column_29() -> None:
    # Scenario: '%-28s ' yields key field 28 cols + 1-space separator -> col 29.
    out = jot_diagKv("k", "v")
    # Test verification.
    assert out.index("v") == 29


def test_jot_diagKv_long_key_not_truncated() -> None:
    # Scenario: keys >= 28 chars are NOT truncated (printf min-width).
    long_key = "k" * 40
    # Test action + verification.
    assert jot_diagKv(long_key, "v") == f"{long_key} v\n"


def test_jot_diagKv_ends_with_single_trailing_newline() -> None:
    # Scenario: each line has exactly one trailing newline.
    out = jot_diagKv("a", "b")
    # Test verification.
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


def test_jot_diagKv_empty_value_still_emits_padded_key() -> None:
    # Scenario: empty value still emits padded key + space + newline.
    # Test action + verification.
    assert jot_diagKv("jq", "") == "jq" + " " * 26 + " \n"


def test_jot_diagKv_value_with_spaces_preserved_verbatim() -> None:
    # Scenario: value with internal spaces preserved as-is, not split.
    out = jot_diagKv("mtime", "Mon Jan  1 00:00:00")
    # Test verification.
    assert "Mon Jan  1 00:00:00\n" in out
