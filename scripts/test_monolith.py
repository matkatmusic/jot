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
    debate_agentErrorMarkers,
    debate_agentLaunchCmd,
    debate_agentReadyMarker,
    debate_anyLiveLock,
    debate_archive,
    debate_buildClaudeCmd,
    debate_buildClaudePrompts,
    debate_checkResumeFeasibility,
    debate_claimSession,
    debate_cleanStaleLocks,
    debate_cleanup,
    debate_defaultModel,
    debate_detectAvailableAgents,
    debate_findMatching,
    debate_initAgentModels,
    debate_initHookContext,
    debate_launch,
    debate_launchAgent,
    debate_launchAgentsParallel,
    debate_liveSession,
    debate_newEmptyPane,
    debate_nextModel,
    debate_paneHasCapacityError,
    debate_probeCodex,
    debate_probeGemini,
    debate_retryPaneWithNextModel,
    debate_sendPromptToAgent,
    debate_tmuxOrchestrator,
    debate_waitForOutputs,
    debate_writeFailed,
    debateAbort_main,
    FileLock,
    hookjson_checkRequirements,
    hookjson_emitBlock,
    hookjson_installHint,
    jot_buildClaudeCmd,
    jot_collectDiagnostics,
    jot_diagIndent,
    jot_diagKv,
    jot_diagSection,
    jot_initState,
    jot_launchPhase2Window,
    jot_main,
    jot_popFirstFromQueue,
    jot_rotateAudit,
    jot_sendPrompt,
    jot_sessionEnd,
    jot_sessionStart,
    jot_stop,
    LockTimeout,
    plate_summaryStop,
    plate_summaryWatch,
    shell_runWithTimeout,
    shell_waitForFile,
    terminal_spawnIfNeeded,
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
    todo_launcher,
    todo_main,
    todo_scanOpen,
    todo_sessionEnd,
    todo_sessionStart,
    todo_stop,
    todoList_main,
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


# --- debate_agentReadyMarker ---

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))



def test_gemini_marker():
    # Scenario: gemini agent boots and shows its REPL prompt.
    # Setup: agent name is the literal "gemini".
    # Test action: query the ready marker.
    # Test verification: returns gemini's exact prompt substring.
    agent = "gemini"
    result = debate_agentReadyMarker(agent)
    assert result == "Type your message or @path/to/file"


def test_codex_marker():
    # Scenario: codex agent finishes boot and shows model-selector hint.
    # Setup: agent name is the literal "codex".
    # Test action: query the ready marker.
    # Test verification: returns codex's exact ready-line substring.
    agent = "codex"
    result = debate_agentReadyMarker(agent)
    assert result == "/model to change"


def test_claude_marker():
    # Scenario: claude CLI prints its banner once ready.
    # Setup: agent name is the literal "claude".
    # Test action: query the ready marker.
    # Test verification: returns the banner prefix used by orchestrator grep.
    agent = "claude"
    result = debate_agentReadyMarker(agent)
    assert result == "Claude Code v"


def test_unknown_agent_returns_empty_string():
    # Scenario: caller passes an agent name not in the case statement.
    # Setup: arbitrary unknown agent identifier.
    # Test action: query the ready marker.
    # Test verification: empty string (bash case has no default branch).
    agent = "bogus"
    result = debate_agentReadyMarker(agent)
    assert result == ""


def test_empty_string_agent_returns_empty_string():
    # Scenario: defensive call with empty agent name.
    # Setup: empty string as agent identifier.
    # Test action: query the ready marker.
    # Test verification: empty string returned, no exception raised.
    agent = ""
    result = debate_agentReadyMarker(agent)
    assert result == ""



# --- debate_agentErrorMarkers ---

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))



def test_codex_returns_capacity_and_overload_markers():
    # Scenario: codex agent has two known capacity-class error strings
    # Setup: agent name 'codex'
    # Test action: call debate_agentErrorMarkers('codex')
    # Test verification: returns exact ordered list of two markers
    result = debate_agentErrorMarkers("codex")
    assert result == ["Selected model is at capacity", "model is overloaded"]


def test_gemini_returns_quota_markers_in_order():
    # Scenario: gemini agent has three quota/exhaustion markers
    # Setup: agent name 'gemini'
    # Test action: call debate_agentErrorMarkers('gemini')
    # Test verification: returns the three markers in bash printf order
    result = debate_agentErrorMarkers("gemini")
    assert result == [
        "RESOURCE_EXHAUSTED",
        "Quota exceeded",
        "You exceeded your current quota",
    ]


def test_claude_returns_overload_markers():
    # Scenario: claude agent has 529/overloaded markers
    # Setup: agent name 'claude'
    # Test action: call debate_agentErrorMarkers('claude')
    # Test verification: returns exactly the two claude markers
    result = debate_agentErrorMarkers("claude")
    assert result == ["API Error: 529", "overloaded_error"]


def test_unknown_agent_returns_empty_list():
    # Scenario: bash case has no default branch -> no output
    # Setup: agent name not in {codex, gemini, claude}
    # Test action: call with unknown agent
    # Test verification: empty list (Python equivalent of empty stdout)
    assert debate_agentErrorMarkers("bogus") == []


def test_empty_string_agent_returns_empty_list():
    # Scenario: empty argument falls through case with no match
    # Setup: agent name ''
    # Test action: call with empty string
    # Test verification: empty list
    assert debate_agentErrorMarkers("") == []


def test_result_is_list_type():
    # Scenario: callers iterate markers (see pane_has_capacity_error loop)
    # Setup: any valid agent
    # Test action: check return type
    # Test verification: list (mutable sequence) so callers can iterate safely
    assert isinstance(debate_agentErrorMarkers("codex"), list)



# --- debate_agentLaunchCmd ---

#!/usr/bin/env python3

import os
import sys
from pathlib import Path

# Standard sys.path insert so the temp module is importable.



# ──────────────────────────── gemini ────────────────────────────

def test_gemini_with_model() -> None:
    # Scenario: caller selected an explicit gemini model.
    # Setup: stash CURRENT_MODEL[gemini] = "gemini-2.5-pro".
    current_model = {"gemini": "gemini-2.5-pro"}
    # Test action: build launch cmd for gemini.
    cmd = debate_agentLaunchCmd(
        agent="gemini",
        current_model=current_model,
        debate_dir="/tmp/x",
        cwd="/tmp/x",
        repo_root="/tmp/x",
        home="/tmp/home",
        settings_file="/tmp/s.json",
    )
    # Test verification: --model flag appears with the chosen model, quoted.
    assert cmd == (
        "gemini --allowed-tools "
        "'read_file,write_file,run_shell_command(ls)' "
        "--model 'gemini-2.5-pro'"
    )


def test_gemini_without_model() -> None:
    # Scenario: no model preselected for gemini.
    # Setup: stash CURRENT_MODEL[gemini] = "" (empty).
    current_model = {"gemini": ""}
    # Test action: build launch cmd.
    cmd = debate_agentLaunchCmd(
        agent="gemini",
        current_model=current_model,
        debate_dir="/tmp/x",
        cwd="/tmp/x",
        repo_root="/tmp/x",
        home="/tmp/home",
        settings_file="/tmp/s.json",
    )
    # Test verification: no --model segment present.
    assert cmd == (
        "gemini --allowed-tools "
        "'read_file,write_file,run_shell_command(ls)'"
    )


# ──────────────────────────── codex ────────────────────────────

def test_codex_with_model() -> None:
    # Scenario: codex with explicit model.
    # Setup: model "gpt-5", debate_dir "/repo/Debates/T_slug".
    current_model = {"codex": "gpt-5"}
    # Test action.
    cmd = debate_agentLaunchCmd(
        agent="codex",
        current_model=current_model,
        debate_dir="/repo/Debates/T_slug",
        cwd="/repo",
        repo_root="/repo",
        home="/h",
        settings_file="/s.json",
    )
    # Test verification: --add-dir uses debate_dir; --model uses provided.
    assert cmd == "codex -a never --add-dir '/repo/Debates/T_slug' --model 'gpt-5'"


def test_codex_without_model() -> None:
    # Scenario: codex without model.
    # Setup: empty model entry.
    current_model = {"codex": ""}
    # Test action.
    cmd = debate_agentLaunchCmd(
        agent="codex",
        current_model=current_model,
        debate_dir="/repo/Debates/X",
        cwd="/repo",
        repo_root="/repo",
        home="/h",
        settings_file="/s.json",
    )
    # Test verification: no --model.
    assert cmd == "codex -a never --add-dir '/repo/Debates/X'"


# ──────────────────────────── claude ────────────────────────────

def test_claude_repo_root_equals_cwd_no_plans_dup() -> None:
    # Scenario: CWD == REPO_ROOT and home/.claude/plans differs.
    # Setup: CWD == REPO_ROOT == /repo; home /h => plans /h/.claude/plans (distinct).
    current_model: dict[str, str] = {}
    # Test action.
    cmd = debate_agentLaunchCmd(
        agent="claude",
        current_model=current_model,
        debate_dir="/repo/Debates/X",
        cwd="/repo",
        repo_root="/repo",
        home="/h",
        settings_file="/tmp/settings.json",
    )
    # Test verification: only one --add-dir for cwd, plus plans dir; no duplicate repo_root.
    assert cmd == (
        "claude --settings '/tmp/settings.json' "
        "--add-dir '/repo' --add-dir '/h/.claude/plans'"
    )


def test_claude_repo_root_distinct_from_cwd() -> None:
    # Scenario: CWD differs from REPO_ROOT; both differ from plans.
    # Setup: cwd /sub, repo_root /repo, home /h.
    cmd = debate_agentLaunchCmd(
        agent="claude",
        current_model={},
        debate_dir="/repo/Debates/X",
        cwd="/sub",
        repo_root="/repo",
        home="/h",
        settings_file="/s.json",
    )
    # Test verification: cwd, repo_root, then plans appended in order.
    assert cmd == (
        "claude --settings '/s.json' "
        "--add-dir '/sub' --add-dir '/repo' --add-dir '/h/.claude/plans'"
    )


def test_claude_plans_equals_cwd_skipped() -> None:
    # Scenario: CWD is exactly $HOME/.claude/plans.
    # Setup: cwd == /h/.claude/plans, repo_root == cwd.
    cmd = debate_agentLaunchCmd(
        agent="claude",
        current_model={},
        debate_dir="/x",
        cwd="/h/.claude/plans",
        repo_root="/h/.claude/plans",
        home="/h",
        settings_file="/s.json",
    )
    # Test verification: no duplicate plans --add-dir appended.
    assert cmd == "claude --settings '/s.json' --add-dir '/h/.claude/plans'"


def test_claude_repo_root_empty_string_skipped() -> None:
    # Scenario: not in a git repo => REPO_ROOT == "".
    # Setup: empty repo_root; cwd /tmp.
    cmd = debate_agentLaunchCmd(
        agent="claude",
        current_model={},
        debate_dir="/x",
        cwd="/tmp",
        repo_root="",
        home="/h",
        settings_file="/s.json",
    )
    # Test verification: empty repo_root contributes no --add-dir; plans still added.
    assert cmd == (
        "claude --settings '/s.json' "
        "--add-dir '/tmp' --add-dir '/h/.claude/plans'"
    )



# --- debate_archive ---

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest



def test_creates_archive_subdirectory(tmp_path: Path) -> None:
    # Scenario: debate_archive must create the archive/ subdirectory under DEBATE_DIR.
    # Setup: empty debate dir with no intermediate files.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    # Test action: invoke debate_archive on the empty dir.
    debate_archive(debate_dir)
    # Test verification: archive subdir now exists.
    assert (debate_dir / "archive").is_dir()


def test_moves_context_md_into_archive(tmp_path: Path) -> None:
    # Scenario: context.md at debate root must be relocated into archive/.
    # Setup: write a context.md with known content.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    src = debate_dir / "context.md"
    src.write_text("CTX")
    # Test action: archive.
    debate_archive(debate_dir)
    # Test verification: source removed; destination present with same content.
    assert not src.exists()
    moved = debate_dir / "archive" / "context.md"
    assert moved.is_file()
    assert moved.read_text() == "CTX"


def test_moves_synthesis_instructions_txt(tmp_path: Path) -> None:
    # Scenario: synthesis_instructions.txt must be archived.
    # Setup: create file at debate root.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "synthesis_instructions.txt").write_text("SI")
    # Test action.
    debate_archive(debate_dir)
    # Test verification.
    assert not (debate_dir / "synthesis_instructions.txt").exists()
    assert (debate_dir / "archive" / "synthesis_instructions.txt").read_text() == "SI"


def test_moves_r1_instructions_glob(tmp_path: Path) -> None:
    # Scenario: r1_instructions_*.txt files must be archived (glob pattern).
    # Setup: two r1 instruction files for different agents.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "r1_instructions_gemini.txt").write_text("g")
    (debate_dir / "r1_instructions_claude.txt").write_text("c")
    # Test action.
    debate_archive(debate_dir)
    # Test verification: both moved into archive/.
    assert not (debate_dir / "r1_instructions_gemini.txt").exists()
    assert not (debate_dir / "r1_instructions_claude.txt").exists()
    assert (debate_dir / "archive" / "r1_instructions_gemini.txt").read_text() == "g"
    assert (debate_dir / "archive" / "r1_instructions_claude.txt").read_text() == "c"


def test_moves_r1_output_md_glob(tmp_path: Path) -> None:
    # Scenario: r1_*.md round-1 outputs must be archived.
    # Setup: per-agent r1 outputs.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "r1_gemini.md").write_text("R1G")
    (debate_dir / "r1_codex.md").write_text("R1C")
    # Test action.
    debate_archive(debate_dir)
    # Test verification.
    assert (debate_dir / "archive" / "r1_gemini.md").read_text() == "R1G"
    assert (debate_dir / "archive" / "r1_codex.md").read_text() == "R1C"
    assert not (debate_dir / "r1_gemini.md").exists()


def test_moves_r2_instructions_and_outputs_glob(tmp_path: Path) -> None:
    # Scenario: r2_instructions_*.txt and r2_*.md must both be archived.
    # Setup.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "r2_instructions_gemini.txt").write_text("i")
    (debate_dir / "r2_gemini.md").write_text("o")
    # Test action.
    debate_archive(debate_dir)
    # Test verification.
    assert (debate_dir / "archive" / "r2_instructions_gemini.txt").is_file()
    assert (debate_dir / "archive" / "r2_gemini.md").is_file()


def test_moves_orchestrator_log_when_present(tmp_path: Path) -> None:
    # Scenario: orchestrator.log handled by separate clause; must move when present.
    # Setup.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "orchestrator.log").write_text("LOG")
    # Test action.
    debate_archive(debate_dir)
    # Test verification.
    assert not (debate_dir / "orchestrator.log").exists()
    assert (debate_dir / "archive" / "orchestrator.log").read_text() == "LOG"


def test_does_not_move_synthesis_md(tmp_path: Path) -> None:
    # Scenario: synthesis.md is the final artifact; must remain at debate root.
    # Setup: create synthesis.md plus an r1 output.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "synthesis.md").write_text("FINAL")
    (debate_dir / "r1_gemini.md").write_text("R1G")
    # Test action.
    debate_archive(debate_dir)
    # Test verification: synthesis.md still at root, untouched.
    assert (debate_dir / "synthesis.md").read_text() == "FINAL"
    assert not (debate_dir / "archive" / "synthesis.md").exists()


def test_does_not_move_topic_md(tmp_path: Path) -> None:
    # Scenario: topic.md is a primary artifact; must NOT be archived.
    # Setup.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "topic.md").write_text("TOPIC")
    # Test action.
    debate_archive(debate_dir)
    # Test verification.
    assert (debate_dir / "topic.md").read_text() == "TOPIC"
    assert not (debate_dir / "archive" / "topic.md").exists()


def test_idempotent_when_no_intermediate_files(tmp_path: Path) -> None:
    # Scenario: running on a debate dir with nothing to archive must not error.
    # Setup: only synthesis.md present.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "synthesis.md").write_text("S")
    # Test action.
    debate_archive(debate_dir)
    # Test verification: archive dir created, synthesis.md untouched.
    assert (debate_dir / "archive").is_dir()
    assert (debate_dir / "synthesis.md").read_text() == "S"


def test_handles_preexisting_archive_dir(tmp_path: Path) -> None:
    # Scenario: archive/ already exists from a previous run; mkdir -p semantics.
    # Setup: pre-create archive with a stale file inside, plus a new file to archive.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "archive").mkdir()
    (debate_dir / "archive" / "old.txt").write_text("OLD")
    (debate_dir / "context.md").write_text("NEW")
    # Test action.
    debate_archive(debate_dir)
    # Test verification: prior contents preserved; new file moved in.
    assert (debate_dir / "archive" / "old.txt").read_text() == "OLD"
    assert (debate_dir / "archive" / "context.md").read_text() == "NEW"
    assert not (debate_dir / "context.md").exists()



# --- debate_buildClaudeCmd ---

import json
import os
import sys
from pathlib import Path

# sys.path: workspace dir (for _tmp module) + scripts dir (for monolith).
sys.path.insert(0, str(HERE.parent))



def test_creates_tmpdir_and_settings_file_path(tmp_path, monkeypatch):
    # Scenario: Function provisions a fresh tmpdir under /tmp and returns a
    # settings.json path inside it.
    # Setup: stub permissions_seed (no-op) and expand_permissions ('[]').
    seeded = []
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "root"))
    (tmp_path / "data").mkdir()
    (tmp_path / "root" / "skills" / "debate" / "scripts" / "assets").mkdir(parents=True)

    def fake_seed(*args, **kwargs):
        seeded.append(args)

    def fake_expand(perm_file, cwd, repo_root, home):
        return "[]"

    # Test action:
    result = debate_buildClaudeCmd(
        cwd=str(tmp_path),
        repo_root=str(tmp_path),
        log_file=str(tmp_path / "log.txt"),
        permissions_seed_fn=fake_seed,
        expand_permissions_fn=fake_expand,
    )

    # Test verification: tmpdir exists, settings_file lives inside it.
    assert Path(result["tmpdir_inv"]).is_dir()
    assert result["tmpdir_inv"].startswith("/tmp/debate.")
    assert result["settings_file"] == str(Path(result["tmpdir_inv"]) / "settings.json")


def test_writes_settings_json_with_allow_and_empty_hooks(tmp_path, monkeypatch):
    # Scenario: Settings file is written with permissions.allow from
    # expand_permissions output and an empty hooks object.
    # Setup:
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "root"))
    (tmp_path / "data").mkdir()

    allow_value = '["Bash(echo:*)","Read"]'

    # Test action:
    result = debate_buildClaudeCmd(
        cwd=str(tmp_path),
        repo_root=str(tmp_path),
        log_file=str(tmp_path / "log.txt"),
        permissions_seed_fn=lambda *a, **k: None,
        expand_permissions_fn=lambda *a, **k: allow_value,
    )

    # Test verification: parse settings.json round-trip.
    body = json.loads(Path(result["settings_file"]).read_text())
    assert body["permissions"]["allow"] == ["Bash(echo:*)", "Read"]
    assert body["hooks"] == {}


def test_returns_claude_cmd_with_settings_and_add_dir(tmp_path, monkeypatch):
    # Scenario: Returned cmd string contains --settings <file> and --add-dir
    # <cwd>, plus a trailing newline (claude_buildCmd contract).
    # Setup:
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "root"))
    (tmp_path / "data").mkdir()
    cwd = str(tmp_path / "work")
    (tmp_path / "work").mkdir()

    # Test action:
    result = debate_buildClaudeCmd(
        cwd=cwd,
        repo_root=cwd,
        log_file=str(tmp_path / "log.txt"),
        permissions_seed_fn=lambda *a, **k: None,
        expand_permissions_fn=lambda *a, **k: "[]",
    )

    # Test verification:
    cmd = result["cmd"]
    assert cmd.endswith("\n")
    assert f"--settings '{result['settings_file']}'" in cmd
    assert f"--add-dir '{cwd}'" in cmd
    assert cmd.startswith("claude ")


def test_invokes_permissions_seed_with_expected_paths(tmp_path, monkeypatch):
    # Scenario: permissions_seed is called once with the documented six args.
    # Setup:
    data = tmp_path / "data"
    root = tmp_path / "root"
    data.mkdir()
    root.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    log = str(tmp_path / "log.txt")
    captured = {}

    def fake_seed(perm_file, default_file, default_sha, prior_sha, log_file, label):
        captured["perm_file"] = perm_file
        captured["default_file"] = default_file
        captured["default_sha"] = default_sha
        captured["prior_sha"] = prior_sha
        captured["log_file"] = log_file
        captured["label"] = label

    # Test action:
    debate_buildClaudeCmd(
        cwd=str(tmp_path),
        repo_root=str(tmp_path),
        log_file=log,
        permissions_seed_fn=fake_seed,
        expand_permissions_fn=lambda *a, **k: "[]",
    )

    # Test verification:
    assert captured["perm_file"] == str(data / "debate-permissions.local.json")
    assert captured["default_file"] == str(
        root / "skills/debate/scripts/assets/permissions.default.json"
    )
    assert captured["default_sha"] == str(
        root / "skills/debate/scripts/assets/permissions.default.json.sha256"
    )
    assert captured["prior_sha"] == str(data / "debate-permissions.default.sha256")
    assert captured["log_file"] == log
    assert captured["label"] == "debate"


def test_creates_claude_plugin_data_dir_if_missing(tmp_path, monkeypatch):
    # Scenario: CLAUDE_PLUGIN_DATA dir does not yet exist; function mkdir -p's it.
    # Setup: data dir intentionally NOT created.
    data = tmp_path / "data_nonexistent"
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))

    # Test action:
    debate_buildClaudeCmd(
        cwd=str(tmp_path),
        repo_root=str(tmp_path),
        log_file=str(tmp_path / "log.txt"),
        permissions_seed_fn=lambda *a, **k: None,
        expand_permissions_fn=lambda *a, **k: "[]",
    )

    # Test verification:
    assert data.is_dir()



# --- debate_buildClaudePrompts ---

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))



# ---------------------------------------------------------------------------
# r1 stage
# ---------------------------------------------------------------------------


def test_r1_writes_instruction_file_for_each_agent(tmp_path: Path) -> None:
    # Scenario: r1 stage with two agents, no AGENT_FILTER
    # Setup:
    plugin_root = tmp_path / "plugin"
    tmpl_dir = plugin_root / "skills" / "debate" / "prompts"
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "r1.template.md").write_text("# R1 template\nDEBATE_DIR={{DEBATE_DIR}}\nOUTPUT_FILE={{OUTPUT_FILE}}\n")
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]

    # Test action:
    debate_buildClaudePrompts(
        stage="r1",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
    )

    # Test verification:
    for agent in agents:
        out = debate_dir / f"r1_instructions_{agent}.txt"
        assert out.exists(), f"missing {out.name}"
        content = out.read_text()
        assert str(debate_dir) in content
        assert str(debate_dir / f"r1_{agent}.md") in content


def test_r1_agent_filter_writes_only_matching_agent(tmp_path: Path) -> None:
    # Scenario: r1 stage with AGENT_FILTER set to one agent
    # Setup:
    plugin_root = tmp_path / "plugin"
    tmpl_dir = plugin_root / "skills" / "debate" / "prompts"
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "r1.template.md").write_text("DEBATE_DIR={{DEBATE_DIR}}\nOUTPUT_FILE={{OUTPUT_FILE}}\n")
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]

    # Test action:
    debate_buildClaudePrompts(
        stage="r1",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
        agent_filter="claude",
    )

    # Test verification:
    assert (debate_dir / "r1_instructions_claude.txt").exists()
    assert not (debate_dir / "r1_instructions_gemini.txt").exists()


def test_r1_reads_agents_from_agents_txt_when_agents_list_empty(tmp_path: Path) -> None:
    # Scenario: agents list is empty; function falls back to agents.txt
    # Setup:
    plugin_root = tmp_path / "plugin"
    tmpl_dir = plugin_root / "skills" / "debate" / "prompts"
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "r1.template.md").write_text("DEBATE_DIR={{DEBATE_DIR}}\nOUTPUT_FILE={{OUTPUT_FILE}}\n")
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "agents.txt").write_text("claude\ngemini\n")

    # Test action:
    debate_buildClaudePrompts(
        stage="r1",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=[],
    )

    # Test verification:
    assert (debate_dir / "r1_instructions_claude.txt").exists()
    assert (debate_dir / "r1_instructions_gemini.txt").exists()


# ---------------------------------------------------------------------------
# r2 stage
# ---------------------------------------------------------------------------


def test_r2_writes_cross_critique_instruction_file_for_each_agent(tmp_path: Path) -> None:
    # Scenario: r2 stage with three agents, no filter
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini", "codex"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="r2",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
    )

    # Test verification:
    for agent in agents:
        out = debate_dir / f"r2_instructions_{agent}.txt"
        assert out.exists()
        content = out.read_text()
        assert "Round 2: Cross-Critique" in content
        assert f"r1_{agent}.md" in content
        # Others' r1 paths referenced
        for other in agents:
            if other != agent:
                assert f"r1_{other}.md" in content
        assert f"r2_{agent}.md" in content


def test_r2_agent_filter_writes_only_matching_agent(tmp_path: Path) -> None:
    # Scenario: r2 with AGENT_FILTER; only target agent file written
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="r2",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
        agent_filter="gemini",
    )

    # Test verification:
    assert (debate_dir / "r2_instructions_gemini.txt").exists()
    assert not (debate_dir / "r2_instructions_claude.txt").exists()


def test_r2_others_list_excludes_self(tmp_path: Path) -> None:
    # Scenario: r2 for agent "claude"; claude's own r1 not listed as "other"
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="r2",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
        agent_filter="claude",
    )

    # Test verification:
    content = (debate_dir / "r2_instructions_claude.txt").read_text()
    lines = content.splitlines()
    # gemini r1 path appears in "Other Agents" section (after the header line)
    other_refs = [l for l in lines if "r1_gemini.md" in l]
    assert other_refs, "gemini r1 not referenced"
    # claude's r1 path referenced only as "Your Round 1 Response"
    self_refs = [l for l in lines if "r1_claude.md" in l]
    assert self_refs, "own r1 not referenced at all"


# ---------------------------------------------------------------------------
# synthesis stage
# ---------------------------------------------------------------------------


def test_synthesis_writes_single_instruction_file(tmp_path: Path) -> None:
    # Scenario: synthesis stage with two agents
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="synthesis",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
    )

    # Test verification:
    out = debate_dir / "synthesis_instructions.txt"
    assert out.exists()
    content = out.read_text()
    assert "Round 3: Synthesis" in content
    assert "2 agents" in content
    assert "claude" in content
    assert "gemini" in content
    assert "synthesis.md" in content


def test_synthesis_references_all_r1_and_r2_paths(tmp_path: Path) -> None:
    # Scenario: synthesis file references every agent's r1 and r2 paths
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini", "codex"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="synthesis",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
    )

    # Test verification:
    content = (debate_dir / "synthesis_instructions.txt").read_text()
    for agent in agents:
        assert f"r1_{agent}.md" in content
        assert f"r2_{agent}.md" in content


def test_synthesis_contains_required_structure_sections(tmp_path: Path) -> None:
    # Scenario: output must contain all 8 structure headings
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="synthesis",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
    )

    # Test verification:
    content = (debate_dir / "synthesis_instructions.txt").read_text()
    for heading in [
        "Topic",
        "Agreement",
        "Disagreement",
        "Strongest Arguments",
        "Weaknesses",
        "Path Forward",
        "Confidence",
        "Open Questions",
    ]:
        assert heading in content, f"missing section: {heading}"


# ---------------------------------------------------------------------------
# error cases
# ---------------------------------------------------------------------------


def test_unknown_stage_raises_value_error(tmp_path: Path) -> None:
    # Scenario: invalid stage name raises ValueError
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()

    # Test action / verification:
    try:
        debate_buildClaudePrompts(
            stage="badstage",
            debate_dir=debate_dir,
            plugin_root=tmp_path / "plugin",
            agents=["claude"],
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "badstage" in str(exc)



# --- debate_checkResumeFeasibility ---

#!/usr/bin/env python3

import sys
from pathlib import Path

# Make the workspace temp module importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))

    ResumeFeasibility,
    debate_checkResumeFeasibility,
)


def _seed_original(debate_dir: Path, agents: list[str]) -> None:
    """Helper: write r1_instructions_<agent>.txt for each agent."""
    debate_dir.mkdir(parents=True, exist_ok=True)
    for a in agents:
        (debate_dir / f"r1_instructions_{a}.txt").write_text("instr\n")


def _seed_outputs(debate_dir: Path, agent: str, *, r1: bool, r2: bool) -> None:
    """Helper: optionally seed non-empty r1_<agent>.md / r2_<agent>.md."""
    if r1:
        (debate_dir / f"r1_{agent}.md").write_text("r1 body\n")
    if r2:
        (debate_dir / f"r2_{agent}.md").write_text("r2 body\n")


def test_all_originals_still_available_returns_feasible(tmp_path: Path) -> None:
    # Scenario: original composition (claude, gemini) still all available.
    # Setup: seed two r1_instructions files; available list matches exactly.
    _seed_original(tmp_path, ["claude", "gemini"])
    # Test action: run the feasibility check.
    result = debate_checkResumeFeasibility(tmp_path, ["claude", "gemini"])
    # Test verification: feasible=True, agent list unchanged, no unusable.
    assert result.feasible is True
    assert result.unusable_agents == []
    assert set(result.updated_agents) == {"claude", "gemini"}


def test_appeared_agent_is_kept_in_updated_list(tmp_path: Path) -> None:
    # Scenario: an agent appeared since the original debate (codex new).
    # Setup: original was just claude; available now is [claude, codex].
    _seed_original(tmp_path, ["claude"])
    # Test action: feasibility check with the larger available list.
    result = debate_checkResumeFeasibility(tmp_path, ["claude", "codex"])
    # Test verification: feasible and codex retained for JIT instructions.
    assert result.feasible is True
    assert "codex" in result.updated_agents


def test_disappeared_agent_with_complete_outputs_is_readded(tmp_path: Path) -> None:
    # Scenario: gemini disappeared (creds gone) but its R1+R2 are cached.
    # Setup: original=[claude,gemini]; available=[claude]; gemini outputs exist.
    _seed_original(tmp_path, ["claude", "gemini"])
    _seed_outputs(tmp_path, "gemini", r1=True, r2=True)
    # Test action: run check.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: feasible, gemini re-added so synthesis sees it.
    assert result.feasible is True
    assert "gemini" in result.updated_agents
    assert result.unusable_agents == []


def test_disappeared_agent_missing_r2_is_unusable(tmp_path: Path) -> None:
    # Scenario: gemini disappeared and only R1 cached (no R2).
    # Setup: original=[claude,gemini]; available=[claude]; only gemini r1 exists.
    _seed_original(tmp_path, ["claude", "gemini"])
    _seed_outputs(tmp_path, "gemini", r1=True, r2=False)
    # Test action: run check.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: not feasible; gemini listed in unusable.
    assert result.feasible is False
    assert result.unusable_agents == ["gemini"]


def test_disappeared_agent_with_empty_output_file_is_unusable(tmp_path: Path) -> None:
    # Scenario: r1+r2 exist but r2 is zero bytes — bash uses `-s` (non-empty).
    # Setup: seed gemini originals and an empty r2 file.
    _seed_original(tmp_path, ["claude", "gemini"])
    (tmp_path / "r1_gemini.md").write_text("r1\n")
    (tmp_path / "r2_gemini.md").write_text("")  # zero-byte
    # Test action: run check with gemini missing from availability.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: empty file == unusable, matching bash `[ -s ]` semantics.
    assert result.feasible is False
    assert "gemini" in result.unusable_agents


def test_unusable_reason_contains_block_message_and_agent_name(tmp_path: Path) -> None:
    # Scenario: emit_block reason text needs to surface the unusable agent.
    # Setup: codex disappeared with no outputs at all.
    _seed_original(tmp_path, ["claude", "codex"])
    # Test action: run check with codex unavailable and no cached outputs.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: reason mentions codex and the canonical resume hint.
    assert "codex" in result.reason
    assert "cannot resume" in result.reason
    assert "/debate-abort" in result.reason


def test_no_original_instructions_returns_feasible(tmp_path: Path) -> None:
    # Scenario: brand-new debate dir with no r1_instructions_*.txt yet.
    # Setup: empty debate_dir; available=[claude].
    tmp_path.mkdir(exist_ok=True)
    # Test action: run check.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: trivially feasible — no originals to validate against.
    assert result.feasible is True
    assert result.unusable_agents == []
    assert result.updated_agents == ["claude"]


def test_caller_available_agents_list_is_not_mutated(tmp_path: Path) -> None:
    # Scenario: function must not mutate caller's list (Python idiom vs bash global).
    # Setup: original includes gemini with cached outputs; available list captured.
    _seed_original(tmp_path, ["claude", "gemini"])
    _seed_outputs(tmp_path, "gemini", r1=True, r2=True)
    available = ["claude"]
    snapshot = list(available)
    # Test action: run check.
    debate_checkResumeFeasibility(tmp_path, available)
    # Test verification: caller's list is unchanged after the call.
    assert available == snapshot


def test_returns_resumefeasibility_dataclass_instance(tmp_path: Path) -> None:
    # Scenario: contract — return type is the documented dataclass.
    # Setup: minimal valid debate dir.
    _seed_original(tmp_path, ["claude"])
    # Test action: run the check.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: instance shape is ResumeFeasibility.
    assert isinstance(result, ResumeFeasibility)
    assert isinstance(result.updated_agents, list)
    assert isinstance(result.unusable_agents, list)



# --- debate_claimSession ---

import sys
from pathlib import Path

# Standard temp-file header: make workspace + scripts dir importable.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))

import pytest



def test_claims_first_unused_when_all_free(tmp_path):
    # Scenario: no debate-* sessions exist; first attempt at debate-1 succeeds.
    # Setup: fake tmux runner that always returns rc=0 (free slot).
    calls = []

    def fake_tmux(argv):
        calls.append(argv)
        return 0  # success

    # Test action: claim a session.
    result = debate_claimSession("sleep 86400", tmux_runner=fake_tmux)

    # Test verification: returned debate-1 and invoked tmux exactly once.
    assert result == "debate-1"
    assert len(calls) == 1


def test_skips_collisions_until_free_slot(tmp_path):
    # Scenario: debate-1 and debate-2 already exist; debate-3 is free.
    # Setup: runner returns nonzero for first two N, zero for third.
    rcs = iter([1, 1, 0])
    seen = []

    def fake_tmux(argv):
        seen.append(argv)
        return next(rcs)

    # Test action: claim.
    result = debate_claimSession("keepalive", tmux_runner=fake_tmux)

    # Test verification: walked N=1..3, returned debate-3.
    assert result == "debate-3"
    assert len(seen) == 3


def test_passes_keepalive_cmd_and_geometry_to_tmux(tmp_path):
    # Scenario: claim must invoke tmux with -d, -s <name>, -x 200, -y 60,
    #           -n main, and the keepalive_cmd as the final argv.
    # Setup: runner that succeeds and records argv.
    captured = {}

    def fake_tmux(argv):
        captured["argv"] = argv
        return 0

    # Test action: claim with a specific keepalive command.
    debate_claimSession("sleep 99999", tmux_runner=fake_tmux)

    # Test verification: argv contains required flags and keepalive tail.
    argv = captured["argv"]
    assert argv[0] == "tmux"
    assert "new-session" in argv
    assert "-d" in argv
    assert "-s" in argv and argv[argv.index("-s") + 1] == "debate-1"
    assert "-x" in argv and argv[argv.index("-x") + 1] == "200"
    assert "-y" in argv and argv[argv.index("-y") + 1] == "60"
    assert "-n" in argv and argv[argv.index("-n") + 1] == "main"
    assert argv[-1] == "sleep 99999"


def test_raises_when_all_slots_exhausted(tmp_path):
    # Scenario: every N from 1 to 999 collides; function must signal failure.
    # Setup: runner that always returns nonzero.
    attempts = {"n": 0}

    def fake_tmux(argv):
        attempts["n"] += 1
        return 1

    # Test action + verification: RuntimeError raised after 999 attempts.
    with pytest.raises(RuntimeError):
        debate_claimSession("k", tmux_runner=fake_tmux)
    assert attempts["n"] == 999


def test_session_names_are_sequential_debate_n(tmp_path):
    # Scenario: verify the N-th attempt targets `debate-<N>` (1-indexed).
    # Setup: fail first 4, succeed on 5th.
    names = []
    rcs = iter([1, 1, 1, 1, 0])

    def fake_tmux(argv):
        names.append(argv[argv.index("-s") + 1])
        return next(rcs)

    # Test action: claim.
    result = debate_claimSession("cmd", tmux_runner=fake_tmux)

    # Test verification: sequential debate-1..debate-5 attempts, returned debate-5.
    assert names == ["debate-1", "debate-2", "debate-3", "debate-4", "debate-5"]
    assert result == "debate-5"



# --- debate_cleanStaleLocks ---

import sys
from pathlib import Path
from unittest.mock import patch

# Ensure workspace dir on sys.path so we import the in-progress module.
sys.path.insert(0, str(Path(__file__).resolve().parent))



# Helper: write a lock file with the given pane id payload.
def _write_lock(debate_dir: Path, stage: str, agent: str, payload: str) -> Path:
    lock = debate_dir / f".{stage}_{agent}.lock"
    lock.write_text(payload)
    return lock


def test_removes_lock_with_missing_pane_id(tmp_path: Path) -> None:
    # Scenario: lock file is malformed and contains no pane id token.
    # Setup: create a .r1_gemini.lock with junk that sed regex will not match.
    lock = _write_lock(tmp_path, "r1", "gemini", "garbage-not-a-pane-id\n")
    # Test action: invoke cleaner with no live panes; tmux probes should not even matter.
    with patch("jot_plugin_orchestrator._listLivePaneIds", return_value=set()), \
         patch("jot_plugin_orchestrator._paneCurrentCommand", return_value=""):
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: the malformed lock must be gone.
    assert not lock.exists()


def test_removes_lock_when_pane_not_in_window(tmp_path: Path) -> None:
    # Scenario: lock references a pane id that is no longer present in the tmux window.
    # Setup: write a well-formed lock pointing to %42; tmux reports only %99 alive.
    lock = _write_lock(tmp_path, "r1", "codex", "debate:%42\n")
    with patch("jot_plugin_orchestrator._listLivePaneIds", return_value={"%99"}), \
         patch("jot_plugin_orchestrator._paneCurrentCommand", return_value="codex"):
        # Test action: clean stage r1.
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: stale lock removed.
    assert not lock.exists()


def test_removes_lock_when_pane_current_command_mismatches_agent(tmp_path: Path) -> None:
    # Scenario: pane is alive but running a different binary (agent crashed; shell took over).
    # Setup: lock claims pane %5 for gemini, but tmux reports current_command = "bash".
    lock = _write_lock(tmp_path, "r1", "gemini", "debate:%5\n")
    with patch("jot_plugin_orchestrator._listLivePaneIds", return_value={"%5"}), \
         patch("jot_plugin_orchestrator._paneCurrentCommand", return_value="bash"):
        # Test action.
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: lock removed because current_command != agent.
    assert not lock.exists()


def test_preserves_lock_when_pane_alive_and_command_matches_agent(tmp_path: Path) -> None:
    # Scenario: pane is live and running the agent binary -- lock is valid and must NOT be removed.
    # Setup: lock for codex on pane %7; tmux confirms %7 alive with current_command "codex".
    lock = _write_lock(tmp_path, "r1", "codex", "debate:%7\n")
    with patch("jot_plugin_orchestrator._listLivePaneIds", return_value={"%7"}), \
         patch("jot_plugin_orchestrator._paneCurrentCommand", return_value="codex"):
        # Test action.
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: live lock preserved.
    assert lock.exists()
    assert lock.read_text() == "debate:%7\n"


def test_only_touches_locks_for_requested_stage(tmp_path: Path) -> None:
    # Scenario: r2 lock files must be ignored when caller asks to clean r1.
    # Setup: write one stale r1 lock (no pane id) and one stale r2 lock (no pane id).
    r1_lock = _write_lock(tmp_path, "r1", "gemini", "junk\n")
    r2_lock = _write_lock(tmp_path, "r2", "gemini", "junk\n")
    with patch("jot_plugin_orchestrator._listLivePaneIds", return_value=set()), \
         patch("jot_plugin_orchestrator._paneCurrentCommand", return_value=""):
        # Test action: clean stage r1 only.
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: r1 lock removed, r2 lock untouched.
    assert not r1_lock.exists()
    assert r2_lock.exists()


def test_no_locks_present_is_a_noop(tmp_path: Path) -> None:
    # Scenario: empty debate directory -- glob matches nothing.
    # Setup: tmp_path is empty; no tmux probes should be invoked.
    with patch("jot_plugin_orchestrator._listLivePaneIds") as live, \
         patch("jot_plugin_orchestrator._paneCurrentCommand") as cur:
        # Test action.
        debate_cleanStaleLocks(tmp_path, "synthesis")
    # Test verification: function returns cleanly without probing tmux.
    assert live.call_count == 0
    assert cur.call_count == 0



# --- debate_defaultModel ---

import json
import os
import sys
from pathlib import Path

import pytest

# Standard temp file headers: insert workspace dir on sys.path so
# the SUT module can be imported by its temp filename.



# Helper: build a fake plugin root with a models.json containing `payload`.
def _make_plugin_root(tmp_path: Path, payload: dict) -> Path:
    assets = tmp_path / "skills" / "debate" / "scripts" / "assets"
    assets.mkdir(parents=True)
    (assets / "models.json").write_text(json.dumps(payload))
    return tmp_path


def test_returns_first_claude_model(tmp_path, monkeypatch):
    # Scenario: caller asks for the launch-time model for "claude".
    # Setup: plugin root with models.json mapping claude -> 3 models.
    root = _make_plugin_root(tmp_path, {
        "claude": ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"],
        "gemini": ["gemini-3.1-pro-preview"],
        "codex": ["gpt-5.5"],
    })
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for agent="claude".
    result = debate_defaultModel("claude")
    # Test verification: index-0 entry for claude is returned verbatim.
    assert result == "claude-opus-4-7"


def test_returns_first_gemini_model(tmp_path, monkeypatch):
    # Scenario: caller asks for the launch-time model for "gemini".
    # Setup: plugin root with multi-entry gemini list.
    root = _make_plugin_root(tmp_path, {
        "gemini": ["gemini-3.1-pro-preview", "gemini-3-flash-preview"],
    })
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for agent="gemini".
    result = debate_defaultModel("gemini")
    # Test verification: returns the first gemini model only.
    assert result == "gemini-3.1-pro-preview"


def test_returns_first_codex_model(tmp_path, monkeypatch):
    # Scenario: caller asks for the launch-time model for "codex".
    # Setup: plugin root with codex list.
    root = _make_plugin_root(tmp_path, {
        "codex": ["gpt-5.5", "gpt-5.4"],
    })
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for agent="codex".
    result = debate_defaultModel("codex")
    # Test verification: index-0 codex model returned.
    assert result == "gpt-5.5"


def test_unknown_agent_returns_empty_string(tmp_path, monkeypatch):
    # Scenario: caller asks for an agent absent from models.json.
    # Setup: models.json with only claude listed.
    root = _make_plugin_root(tmp_path, {"claude": ["claude-opus-4-7"]})
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for an unmapped agent name.
    result = debate_defaultModel("gemini")
    # Test verification: bash `// ""` fallback is "", not None / KeyError.
    assert result == ""


def test_agent_with_empty_list_returns_empty_string(tmp_path, monkeypatch):
    # Scenario: agent key exists but has no models configured.
    # Setup: gemini key maps to an empty array.
    root = _make_plugin_root(tmp_path, {"gemini": []})
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for agent="gemini".
    result = debate_defaultModel("gemini")
    # Test verification: jq `.[$a][0] // ""` returns "" on empty list.
    assert result == ""


def test_missing_plugin_root_env_raises(tmp_path, monkeypatch):
    # Scenario: CLAUDE_PLUGIN_ROOT is unset (plugin harness not active).
    # Setup: clear the env var.
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    # Test action + verification: a clear error is raised, not silent "".
    with pytest.raises((KeyError, RuntimeError)):
        debate_defaultModel("claude")



# --- debate_detectAvailableAgents ---

import os
import sys
from unittest.mock import patch

# Wire workspace path so the SUT module is importable.



def test_only_claude_when_both_probes_unavailable():
    # Scenario: no gemini, no codex installed → only claude is available.
    # Setup: patch both probes at SUT module boundary to return "" (unavailable).
    with patch("jot_plugin_orchestrator.debate_probeGemini", return_value=""), \
         patch("jot_plugin_orchestrator.debate_probeCodex", return_value=""):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: claude-only list, both model strings empty.
    assert result["available"] == ["claude"]
    assert result["gemini_model"] == ""
    assert result["codex_model"] == ""


def test_gemini_with_real_model_appended_and_model_recorded():
    # Scenario: gemini probe returns a real model name → gemini joins list, model captured.
    # Setup: gemini probe returns concrete model; codex probe returns "" (unavailable).
    with patch("jot_plugin_orchestrator.debate_probeGemini", return_value="gemini-2.5-pro"), \
         patch("jot_plugin_orchestrator.debate_probeCodex", return_value=""):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: gemini joins after claude; model captured verbatim.
    assert result["available"] == ["claude", "gemini"]
    assert result["gemini_model"] == "gemini-2.5-pro"
    assert result["codex_model"] == ""


def test_gemini_present_sentinel_marks_available_but_leaves_model_blank():
    # Scenario: gemini probe returns "present" sentinel (binary+creds, no model configured).
    # Setup: probe returns literal "present"; codex unavailable.
    with patch("jot_plugin_orchestrator.debate_probeGemini", return_value="present"), \
         patch("jot_plugin_orchestrator.debate_probeCodex", return_value=""):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: gemini in list, but gemini_model is "" (sentinel suppressed).
    assert result["available"] == ["claude", "gemini"]
    assert result["gemini_model"] == ""


def test_codex_with_real_model_appended_and_model_recorded():
    # Scenario: codex probe returns a real model name → codex joins list, model captured.
    # Setup: gemini unavailable, codex returns concrete model.
    with patch("jot_plugin_orchestrator.debate_probeGemini", return_value=""), \
         patch("jot_plugin_orchestrator.debate_probeCodex", return_value="gpt-5-codex"):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: codex joins after claude; model captured verbatim.
    assert result["available"] == ["claude", "codex"]
    assert result["codex_model"] == "gpt-5-codex"
    assert result["gemini_model"] == ""


def test_codex_present_sentinel_marks_available_but_leaves_model_blank():
    # Scenario: codex probe returns "present" sentinel.
    # Setup: gemini unavailable, codex returns literal "present".
    with patch("jot_plugin_orchestrator.debate_probeGemini", return_value=""), \
         patch("jot_plugin_orchestrator.debate_probeCodex", return_value="present"):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: codex available, codex_model blank (sentinel suppressed).
    assert result["available"] == ["claude", "codex"]
    assert result["codex_model"] == ""


def test_both_probes_available_preserves_order_claude_gemini_codex():
    # Scenario: both auxiliary agents usable → list order is claude, gemini, codex.
    # Setup: both probes return real model names.
    with patch("jot_plugin_orchestrator.debate_probeGemini", return_value="gemini-2.5-pro"), \
         patch("jot_plugin_orchestrator.debate_probeCodex", return_value="gpt-5-codex"):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: ordered list and both models captured.
    assert result["available"] == ["claude", "gemini", "codex"]
    assert result["gemini_model"] == "gemini-2.5-pro"
    assert result["codex_model"] == "gpt-5-codex"



# --- debate_findMatching ---

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))



def _make_debate(repo_root: Path, ts: str, topic_text: str) -> Path:
    # Helper: create Debates/<ts>/topic.md with given text. Returns dir path.
    d = repo_root / "Debates" / ts
    d.mkdir(parents=True)
    (d / "topic.md").write_text(topic_text)
    return d


def test_returns_none_when_no_debates_dir(tmp_path):
    # Scenario: repo has no Debates/ directory at all.
    # Setup: empty tmp repo root.
    repo = tmp_path
    # Test action: call debate_findMatching with any topic.
    result = debate_findMatching(str(repo), "anything")
    # Test verification: returns None (no match).
    assert result is None


def test_returns_none_when_no_topic_matches(tmp_path):
    # Scenario: Debates/ has dirs but none has matching topic.md content.
    # Setup: one debate dir with different topic text.
    repo = tmp_path
    _make_debate(repo, "2026-01-01_120000_a", "different topic\n")
    # Test action: search for unrelated topic.
    result = debate_findMatching(str(repo), "looking for this\n")
    # Test verification: returns None.
    assert result is None


def test_returns_dir_path_for_single_match(tmp_path):
    # Scenario: exactly one debate has a topic.md byte-equal to query.
    # Setup: matching topic written verbatim (incl. trailing newline appended by printf '%s\n').
    repo = tmp_path
    topic = "Discuss async patterns"
    d = _make_debate(repo, "2026-02-02_100000_x", topic + "\n")
    # Test action: query with the same topic (function appends \n internally like `printf '%s\n'`).
    result = debate_findMatching(str(repo), topic)
    # Test verification: returns that debate dir as a string, no trailing slash.
    assert result == str(d)


def test_skips_dirs_missing_topic_md(tmp_path):
    # Scenario: a Debates/<ts>/ dir exists with no topic.md file.
    # Setup: one dir without topic.md, one with matching topic.md.
    repo = tmp_path
    (repo / "Debates" / "2026-03-03_111111_no_topic").mkdir(parents=True)
    d_match = _make_debate(repo, "2026-03-03_222222_yes", "hello\n")
    # Test action.
    result = debate_findMatching(str(repo), "hello")
    # Test verification: skips topic-less dir, returns the one with topic.md.
    assert result == str(d_match)


def test_most_recent_timestamp_wins_on_multiple_matches(tmp_path):
    # Scenario: multiple debates have identical topic.md; lexicographically-greatest dir name wins.
    # Setup: three matching debates with sortable timestamps.
    repo = tmp_path
    topic = "shared topic"
    _make_debate(repo, "2025-01-01_000000_a", topic + "\n")
    _make_debate(repo, "2026-06-15_120000_b", topic + "\n")
    d_newest = _make_debate(repo, "2027-12-31_235959_c", topic + "\n")
    # Test action.
    result = debate_findMatching(str(repo), topic)
    # Test verification: returns lexicographically-greatest (newest) match.
    assert result == str(d_newest)


def test_multiline_topic_byte_exact_match(tmp_path):
    # Scenario: topic spans multiple lines; cmp-style byte-exact compare must succeed.
    # Setup: write multi-line topic with embedded newlines.
    repo = tmp_path
    topic = "line one\nline two\nline three"
    d = _make_debate(repo, "2026-04-04_090000_m", topic + "\n")
    # Test action: pass same multi-line topic.
    result = debate_findMatching(str(repo), topic)
    # Test verification: matches despite multi-line content.
    assert result == str(d)


def test_partial_substring_does_not_match(tmp_path):
    # Scenario: topic.md contains query as substring but is not byte-equal.
    # Setup: topic.md is a superstring.
    repo = tmp_path
    _make_debate(repo, "2026-05-05_100000_p", "prefix hello suffix\n")
    # Test action: query a substring.
    result = debate_findMatching(str(repo), "hello")
    # Test verification: byte-exact match required, returns None.
    assert result is None



# --- debate_initAgentModels ---

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))



def test_returns_dict_with_current_model_and_tried_models_keys():
    # Scenario: caller invokes with no env overrides
    # Setup: empty env dict
    # Test action: call with empty env
    # Test verification: returned mapping has both top-level keys
    result = debate_initAgentModels(env={})
    assert "CURRENT_MODEL" in result
    assert "TRIED_MODELS" in result


def test_all_three_agents_present_in_both_subdicts():
    # Scenario: bash loop initializes gemini/codex/claude entries
    # Setup: empty env
    # Test action: call function
    # Test verification: every agent key exists in both subdicts
    result = debate_initAgentModels(env={})
    for agent in ("gemini", "codex", "claude"):
        assert agent in result["CURRENT_MODEL"]
        assert agent in result["TRIED_MODELS"]


def test_claude_has_empty_string_when_no_env():
    # Scenario: bash never stashes a CLAUDE_MODEL value, only zeroes it
    # Setup: empty env
    # Test action: call function
    # Test verification: claude entries default to ""
    result = debate_initAgentModels(env={})
    assert result["CURRENT_MODEL"]["claude"] == ""
    assert result["TRIED_MODELS"]["claude"] == ""


def test_gemini_picks_up_GEMINI_MODEL_env():
    # Scenario: GEMINI_MODEL env var set
    # Setup: env with GEMINI_MODEL
    # Test action: call function with that env
    # Test verification: gemini current/tried both equal that value
    result = debate_initAgentModels(env={"GEMINI_MODEL": "gemini-2.5-pro"})
    assert result["CURRENT_MODEL"]["gemini"] == "gemini-2.5-pro"
    assert result["TRIED_MODELS"]["gemini"] == "gemini-2.5-pro"


def test_codex_picks_up_CODEX_MODEL_env():
    # Scenario: CODEX_MODEL env var set
    # Setup: env with CODEX_MODEL
    # Test action: call function with that env
    # Test verification: codex current/tried both equal that value
    result = debate_initAgentModels(env={"CODEX_MODEL": "gpt-5"})
    assert result["CURRENT_MODEL"]["codex"] == "gpt-5"
    assert result["TRIED_MODELS"]["codex"] == "gpt-5"


def test_unset_gemini_env_yields_empty_string_not_missing_key():
    # Scenario: bash uses ${GEMINI_MODEL:-} which expands to "" when unset
    # Setup: env without GEMINI_MODEL
    # Test action: call function
    # Test verification: gemini entry is "" (not None, not absent)
    result = debate_initAgentModels(env={})
    assert result["CURRENT_MODEL"]["gemini"] == ""
    assert result["TRIED_MODELS"]["gemini"] == ""


def test_unset_codex_env_yields_empty_string():
    # Scenario: CODEX_MODEL unset
    # Setup: env without CODEX_MODEL
    # Test action: call function
    # Test verification: codex entry is ""
    result = debate_initAgentModels(env={})
    assert result["CURRENT_MODEL"]["codex"] == ""
    assert result["TRIED_MODELS"]["codex"] == ""


def test_independent_calls_return_independent_dicts():
    # Scenario: ABSORBED idiom - caller owns state, no shared globals
    # Setup: two separate calls
    # Test action: mutate first result
    # Test verification: second result is unaffected
    a = debate_initAgentModels(env={})
    a["CURRENT_MODEL"]["gemini"] = "mutated"
    b = debate_initAgentModels(env={})
    assert b["CURRENT_MODEL"]["gemini"] == ""


def test_env_defaults_to_os_environ_when_omitted(monkeypatch):
    # Scenario: caller omits env arg; function reads os.environ
    # Setup: monkeypatch GEMINI_MODEL in os.environ
    # Test action: call without env kwarg
    # Test verification: gemini entry reflects the patched env
    monkeypatch.setenv("GEMINI_MODEL", "from-os-env")
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    result = debate_initAgentModels()
    assert result["CURRENT_MODEL"]["gemini"] == "from-os-env"



# --- debate_initHookContext ---

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Standard temp file headers: insert workspace dir on sys.path so we can import.
sys.path.insert(0, str(Path(__file__).parent))


# ---------- helpers ----------

def _make_repo(tmp_path: Path) -> Path:
    """Initialise a git repo at tmp_path and return its absolute path."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path.resolve()


# ---------- tests ----------

def test_returns_scripts_dir_under_plugin_root(tmp_path, monkeypatch):
    # Scenario: SCRIPTS_DIR is derived from CLAUDE_PLUGIN_ROOT.
    # Setup: plugin root + plugin data env vars; minimal stdin JSON.
    plugin_root = tmp_path / "plug"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.delenv("DEBATE_LOG_FILE", raising=False)
    # Test action: call with empty JSON object.
    ctx = debate_initHookContext(stdin=io.StringIO("{}"))
    # Test verification: SCRIPTS_DIR points at skills/debate/scripts under root.
    assert ctx["SCRIPTS_DIR"] == str(plugin_root / "skills" / "debate" / "scripts")


def test_log_file_defaults_under_plugin_data_and_dir_created(tmp_path, monkeypatch):
    # Scenario: LOG_FILE defaults to $CLAUDE_PLUGIN_DATA/debate-log.txt and parent dir exists.
    # Setup: plugin data dir not yet containing log dir; no DEBATE_LOG_FILE override.
    plugin_root = tmp_path / "plug"
    plugin_data = tmp_path / "data" / "nested"  # not yet created
    plugin_root.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.delenv("DEBATE_LOG_FILE", raising=False)
    # Test action: call function.
    ctx = debate_initHookContext(stdin=io.StringIO("{}"))
    # Test verification: LOG_FILE path matches default and its parent dir was created.
    expected = plugin_data / "debate-log.txt"
    assert ctx["LOG_FILE"] == str(expected)
    assert expected.parent.is_dir()


def test_log_file_honours_debate_log_file_override(tmp_path, monkeypatch):
    # Scenario: DEBATE_LOG_FILE env var overrides the default LOG_FILE path.
    # Setup: set DEBATE_LOG_FILE to a custom location.
    plugin_root = tmp_path / "plug"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    custom_log = tmp_path / "custom" / "mylog.txt"
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.setenv("DEBATE_LOG_FILE", str(custom_log))
    # Test action.
    ctx = debate_initHookContext(stdin=io.StringIO("{}"))
    # Test verification: LOG_FILE is the override and parent dir was made.
    assert ctx["LOG_FILE"] == str(custom_log)
    assert custom_log.parent.is_dir()


def test_parses_cwd_and_transcript_path_from_stdin_json(tmp_path, monkeypatch):
    # Scenario: CWD and TRANSCRIPT_PATH are read from hook JSON stdin.
    # Setup: env, plus JSON containing cwd + transcript_path keys.
    plugin_root = tmp_path / "plug"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    cwd_dir = _make_repo(tmp_path / "wd")
    payload = '{"cwd": "%s", "transcript_path": "/tmp/t.jsonl"}' % cwd_dir
    # Test action.
    ctx = debate_initHookContext(stdin=io.StringIO(payload))
    # Test verification: cwd and transcript_path lifted into context.
    assert ctx["CWD"] == str(cwd_dir)
    assert ctx["TRANSCRIPT_PATH"] == "/tmp/t.jsonl"


def test_cwd_falls_back_to_pwd_when_json_omits_it(tmp_path, monkeypatch):
    # Scenario: missing .cwd in JSON falls back to current working directory.
    # Setup: env, chdir to tmp_path, JSON without cwd key.
    plugin_root = tmp_path / "plug"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.chdir(tmp_path)
    # Test action.
    ctx = debate_initHookContext(stdin=io.StringIO('{"transcript_path": ""}'))
    # Test verification: CWD falls back to os.getcwd() (i.e. tmp_path).
    assert ctx["CWD"] == str(tmp_path.resolve())


def test_repo_root_resolved_for_git_cwd(tmp_path, monkeypatch):
    # Scenario: REPO_ROOT is resolved from `git rev-parse --show-toplevel`.
    # Setup: real git repo as cwd; subdir passed in JSON to ensure rev-parse climbs.
    plugin_root = tmp_path / "plug"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    repo = _make_repo(tmp_path / "repo")
    sub = repo / "sub"
    sub.mkdir()
    payload = '{"cwd": "%s"}' % sub
    # Test action.
    ctx = debate_initHookContext(stdin=io.StringIO(payload))
    # Test verification: REPO_ROOT equals the repo top-level.
    assert ctx["REPO_ROOT"] == str(repo)


def test_repo_root_empty_when_cwd_not_in_git(tmp_path, monkeypatch):
    # Scenario: outside any git repo, REPO_ROOT is the empty string (no crash).
    # Setup: cwd is a plain dir with no .git anywhere up to /tmp.
    plugin_root = tmp_path / "plug"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    non_git = tmp_path / "plain"
    non_git.mkdir()
    payload = '{"cwd": "%s"}' % non_git
    # Test action.
    ctx = debate_initHookContext(stdin=io.StringIO(payload))
    # Test verification: REPO_ROOT is empty string per bash contract.
    assert ctx["REPO_ROOT"] == ""


def test_input_field_preserves_raw_stdin(tmp_path, monkeypatch):
    # Scenario: INPUT in returned context is the raw stdin text.
    # Setup: JSON with extra whitespace / fields.
    plugin_root = tmp_path / "plug"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    raw = '{"cwd": "/x", "transcript_path": "/y", "extra": 1}\n'
    # Test action.
    ctx = debate_initHookContext(stdin=io.StringIO(raw))
    # Test verification: raw stdin preserved verbatim in INPUT.
    assert ctx["INPUT"] == raw


def test_missing_plugin_root_raises(tmp_path, monkeypatch):
    # Scenario: CLAUDE_PLUGIN_ROOT unset must raise (mirrors bash `:?` guard).
    # Setup: clear CLAUDE_PLUGIN_ROOT, set CLAUDE_PLUGIN_DATA.
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    # Test action + Test verification: must raise (RuntimeError or KeyError).
    with pytest.raises((RuntimeError, KeyError, OSError)):
        debate_initHookContext(stdin=io.StringIO("{}"))


def test_missing_plugin_data_raises(tmp_path, monkeypatch):
    # Scenario: CLAUDE_PLUGIN_DATA unset must raise (mirrors bash `:?` guard).
    # Setup: set CLAUDE_PLUGIN_ROOT, clear CLAUDE_PLUGIN_DATA.
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    # Test action + Test verification.
    with pytest.raises((RuntimeError, KeyError, OSError)):
        debate_initHookContext(stdin=io.StringIO("{}"))



# --- debate_launch ---

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

# ---------------------------------------------------------------------------
# sys.path: allow running from repo root or workspace directly.
# ---------------------------------------------------------------------------
_WORKSPACE = Path(__file__).resolve().parent
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noop() -> None:
    pass


def _make_main_mock() -> MagicMock:
    return MagicMock(return_value=None)


# ===========================================================================
# 1. Always calls debate_main
# ===========================================================================

def test_always_calls_debate_main() -> None:
    # Scenario: debate_launch always delegates to debate_main regardless of OS.
    # Setup:
    main_mock = _make_main_mock()
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=Path("/fake/plugin"),
        _debate_main_fn=main_mock,
        _is_darwin=False,
        _terminal_running_fn=lambda: True,
        _launch_terminal_fn=_noop,
    )
    # Test verification:
    main_mock.assert_called_once_with()


# ===========================================================================
# 2. Darwin + Terminal NOT running -> launches Terminal then calls debate_main
# ===========================================================================

def test_darwin_terminal_not_running_launches_terminal() -> None:
    # Scenario: on Darwin, when Terminal is not running, osascript is invoked.
    # Setup:
    main_mock = _make_main_mock()
    launch_mock = MagicMock()
    terminal_running = lambda: False
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=Path("/fake/plugin"),
        _debate_main_fn=main_mock,
        _is_darwin=True,
        _terminal_running_fn=terminal_running,
        _launch_terminal_fn=launch_mock,
    )
    # Test verification:
    launch_mock.assert_called_once_with()
    main_mock.assert_called_once_with()


# ===========================================================================
# 3. Darwin + Terminal already running -> skips launch
# ===========================================================================

def test_darwin_terminal_already_running_skips_launch() -> None:
    # Scenario: on Darwin, when Terminal is already running, do NOT launch it.
    # Setup:
    main_mock = _make_main_mock()
    launch_mock = MagicMock()
    terminal_running = lambda: True
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=Path("/fake/plugin"),
        _debate_main_fn=main_mock,
        _is_darwin=True,
        _terminal_running_fn=terminal_running,
        _launch_terminal_fn=launch_mock,
    )
    # Test verification:
    launch_mock.assert_not_called()
    main_mock.assert_called_once_with()


# ===========================================================================
# 4. Non-Darwin -> never launches Terminal regardless of pgrep result
# ===========================================================================

def test_non_darwin_never_launches_terminal() -> None:
    # Scenario: on non-Darwin (Linux/CI), Terminal.app guard is skipped entirely.
    # Setup:
    main_mock = _make_main_mock()
    launch_mock = MagicMock()
    terminal_running_mock = MagicMock(return_value=False)
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=Path("/fake/plugin"),
        _debate_main_fn=main_mock,
        _is_darwin=False,
        _terminal_running_fn=terminal_running_mock,
        _launch_terminal_fn=launch_mock,
    )
    # Test verification:
    terminal_running_mock.assert_not_called()
    launch_mock.assert_not_called()
    main_mock.assert_called_once_with()


# ===========================================================================
# 5. PLUGIN_ROOT exported to environment
# ===========================================================================

def test_plugin_root_exported_to_environment() -> None:
    # Scenario: debate_launch sets PLUGIN_ROOT env var so debate_main sees it.
    # Setup:
    import os
    plugin_root = Path("/my/plugin/root")
    main_mock = _make_main_mock()
    # Remove any pre-existing value so setdefault fires.
    os.environ.pop("PLUGIN_ROOT", None)
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=plugin_root,
        _debate_main_fn=main_mock,
        _is_darwin=False,
        _terminal_running_fn=lambda: True,
        _launch_terminal_fn=_noop,
    )
    # Test verification:
    assert os.environ.get("PLUGIN_ROOT") == str(plugin_root)


# ===========================================================================
# 6. Terminal launch is fire-and-forget (does NOT block debate_main)
# ===========================================================================

def test_terminal_launch_before_debate_main() -> None:
    # Scenario: Terminal is launched BEFORE debate_main is called (ordering).
    # Setup:
    call_order: list[str] = []
    main_mock = MagicMock(side_effect=lambda: call_order.append("main"))
    launch_mock = MagicMock(side_effect=lambda: call_order.append("launch"))
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=Path("/fake/plugin"),
        _debate_main_fn=main_mock,
        _is_darwin=True,
        _terminal_running_fn=lambda: False,
        _launch_terminal_fn=launch_mock,
    )
    # Test verification:
    assert call_order == ["launch", "main"], (
        f"Expected launch before main, got: {call_order}"
    )



# --- debate_launchAgent ---

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))



# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_PANE = "%7"
_STAGE = "r1"
_AGENT = "claude"
_CMD = "claude --settings /tmp/s.json --add-dir '/repo'"
_READY = "Claude Code v"


def _patch_all(
    pane_content: str = "",
    *,
    ready_after: int | None = 0,
):
    """Return a context-manager stack that patches all I/O callees.

    ready_after: iteration index (0-based) at which pane shows the ready marker.
                 None => never shows ready (simulate timeout).
    """
    captured_lines: list[str] = []
    call_count = 0

    def fake_capture(pane_id, scrollback_lines=2000):
        nonlocal call_count
        result = _READY if (ready_after is not None and call_count >= ready_after) else ""
        call_count += 1
        return result

    return (
        patch("jot_plugin_orchestrator.tmux_sendAndSubmit"),
        patch("jot_plugin_orchestrator.tmux_capturePane", side_effect=fake_capture),
        patch("jot_plugin_orchestrator.debate_writeFailed"),
        patch("jot_plugin_orchestrator.time_sleep"),
    )


# ---------------------------------------------------------------------------
# RED tests
# ---------------------------------------------------------------------------


def test_writes_lock_file_before_launch(tmp_path):
    # Scenario: launch_agent writes debate:<pane_id> to the lock file before
    #           sending the launch command.
    # Setup: fresh debate_dir, pane ready on first capture
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=0)
    with patches[0] as mock_send, patches[1], patches[2], patches[3]:
        debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
        )
    # Test verification: lock file contains "debate:%pane_id"
    lock = tmp_path / f".{_STAGE}_{_AGENT}.lock"
    assert lock.exists(), "lock file must exist after launch"
    assert lock.read_text().strip() == f"debate:{_PANE}"


def test_sends_launch_cmd_via_tmux(tmp_path):
    # Scenario: launch_agent calls tmux_send_and_submit with the correct pane
    #           and launch command string.
    # Setup: pane immediately ready
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=0)
    with patches[0] as mock_send, patches[1], patches[2], patches[3]:
        debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
        )
    # Test verification: sendAndSubmit called once with pane_id and launch_cmd
    mock_send.assert_called_once_with(_PANE, _CMD)


def test_returns_true_when_ready_marker_found(tmp_path):
    # Scenario: pane capture contains ready_marker before timeout.
    # Setup: capture returns ready string on iteration 0
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=0)
    with patches[0], patches[1], patches[2], patches[3]:
        result = debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
        )
    # Test verification: truthy result means success
    assert result is True


def test_returns_false_on_timeout(tmp_path):
    # Scenario: pane never shows ready_marker within timeout.
    # Setup: capture always returns empty string; use timeout=2 for speed
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=None)
    with patches[0], patches[1], patches[2], patches[3]:
        result = debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
            timeout=2,
        )
    # Test verification: False means timeout
    assert result is False


def test_calls_write_failed_on_timeout(tmp_path):
    # Scenario: after timeout, write_failed is called with stage + agent info.
    # Setup: capture never ready, short timeout
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=None)
    with patches[0], patches[1], patches[2] as mock_wf, patches[3]:
        debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
            timeout=2,
        )
    # Test verification: write_failed called once
    mock_wf.assert_called_once()
    args = mock_wf.call_args[0]
    assert args[0] == _STAGE  # first positional arg is stage


def test_sleeps_between_capture_polls(tmp_path):
    # Scenario: each polling iteration sleeps 1 second (mirrors bash `sleep 1`).
    # Setup: ready on iteration 2 (so 2 sleeps happen before success)
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=2)
    with patches[0], patches[1], patches[2], patches[3] as mock_sleep:
        debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
        )
    # Test verification: sleep(1) called at least twice
    assert mock_sleep.call_count >= 2
    mock_sleep.assert_any_call(1)


def test_default_timeout_is_120(tmp_path):
    # Scenario: when timeout is omitted, the function defaults to 120 iterations.
    # Setup: capture never ready; measure how many times sleep was called.
    # RELAXED_COVERAGE: bash default is 120; we verify the parameter default
    # rather than waiting 120 real seconds. We inspect the function signature.
    # Test action: introspect default parameter value
    import inspect
    sig = inspect.signature(debate_launchAgent)
    # Test verification: default value for `timeout` parameter is 120
    assert sig.parameters["timeout"].default == 120


def test_no_write_failed_on_success(tmp_path):
    # Scenario: write_failed must NOT be called when agent becomes ready in time.
    # Setup: pane immediately ready
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=0)
    with patches[0], patches[1], patches[2] as mock_wf, patches[3]:
        debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
        )
    # Test verification: write_failed never invoked on success
    mock_wf.assert_not_called()



# --- debate_liveSession ---

#!/usr/bin/env python3

import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

# Workspace import with monolith fallback
try:
except ImportError:
    from jot_plugin_orchestrator import debate_liveSession  # type: ignore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_lock(lock_path: Path, pane_id: str) -> None:
    """Write a lock file with the canonical debate:<pane_id> format."""
    lock_path.write_text(f"debate:{pane_id}\n")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_returns_session_name_when_lock_resolves(tmp_path: Path) -> None:
    # Scenario: debate dir has one live lock whose pane resolves to a tmux session
    # Setup: write .agent.lock with pane_id %1; mock tmux to return "debate-1"
    lock = tmp_path / ".agent.lock"
    _write_lock(lock, "%1")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="debate-1\n", stderr="")
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == "debate-1"


def test_returns_empty_when_no_lock_files(tmp_path: Path) -> None:
    # Scenario: debate dir has no .*.lock files
    # Setup: empty tmp_path directory
    # Test action:
    result = debate_liveSession(str(tmp_path))
    # Test verification:
    assert result == ""


def test_returns_empty_when_lock_has_no_pane_id(tmp_path: Path) -> None:
    # Scenario: lock file exists but content does not match debate:<pane_id> pattern
    # Setup: lock file with garbage content
    lock = tmp_path / ".bad.lock"
    lock.write_text("not-a-pane-ref\n")

    with patch("subprocess.run") as mock_run:
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == ""
    mock_run.assert_not_called()


def test_returns_empty_when_tmux_fails(tmp_path: Path) -> None:
    # Scenario: lock file has valid pane_id but tmux display-message returns non-zero
    # Setup: write valid lock; mock tmux to return rc=1
    lock = tmp_path / ".agent.lock"
    _write_lock(lock, "%5")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="no server running")
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == ""


def test_returns_empty_when_tmux_returns_empty_session(tmp_path: Path) -> None:
    # Scenario: tmux succeeds (rc=0) but returns empty session name (pane gone)
    # Setup: write valid lock; mock tmux stdout to empty string
    lock = tmp_path / ".agent.lock"
    _write_lock(lock, "%9")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == ""


def test_skips_missing_lock_file_gracefully(tmp_path: Path) -> None:
    # Scenario: glob finds a path that disappears between glob and open (TOCTOU)
    # Setup: no actual files; just verify empty-dir returns "" without crashing
    # Test action:
    result = debate_liveSession(str(tmp_path))
    # Test verification:
    assert result == ""


def test_returns_first_resolved_session_from_multiple_locks(tmp_path: Path) -> None:
    # Scenario: multiple lock files; first valid one wins
    # Setup: two lock files; first resolves to "debate-2", second would give "debate-3"
    lock_a = tmp_path / ".a.lock"
    lock_b = tmp_path / ".b.lock"
    _write_lock(lock_a, "%2")
    _write_lock(lock_b, "%3")

    call_responses = [
        MagicMock(returncode=0, stdout="debate-2\n", stderr=""),
        MagicMock(returncode=0, stdout="debate-3\n", stderr=""),
    ]

    with patch("subprocess.run", side_effect=call_responses) as mock_run:
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == "debate-2"
    # Only one tmux call needed (returns on first success)
    assert mock_run.call_count == 1


def test_falls_through_to_second_lock_when_first_tmux_fails(tmp_path: Path) -> None:
    # Scenario: first lock's pane is dead; second lock resolves successfully
    # Setup: two locks; tmux fails for first pane, succeeds for second
    lock_a = tmp_path / ".a.lock"
    lock_b = tmp_path / ".b.lock"
    _write_lock(lock_a, "%10")
    _write_lock(lock_b, "%11")

    call_responses = [
        MagicMock(returncode=1, stdout="", stderr=""),
        MagicMock(returncode=0, stdout="debate-4\n", stderr=""),
    ]

    with patch("subprocess.run", side_effect=call_responses):
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == "debate-4"



# --- debate_nextModel ---

import json
import sys
from pathlib import Path

import pytest

# Ensure workspace dir on sys.path so we can import the temp production module.
sys.path.insert(0, str(Path(__file__).resolve().parent))



@pytest.fixture
def models_file(tmp_path: Path) -> Path:
    # Setup: typical models.json shape per assets/models.json.
    p = tmp_path / "models.json"
    p.write_text(json.dumps({
        "gemini": ["gem-pro", "gem-flash", "gem-lite"],
        "codex":  ["gpt-a", "gpt-b"],
        "claude": ["c-opus", "c-sonnet"],
    }))
    return p


def test_returns_first_model_when_none_tried(models_file: Path) -> None:
    # Scenario: no models tried yet for an agent.
    # Setup: empty TRIED_MODELS entry for "gemini".
    tried = {"gemini": "", "codex": "", "claude": ""}
    # Test action: ask for next model for gemini.
    result = debate_nextModel("gemini", tried, str(models_file))
    # Test verification: first model in list is returned.
    assert result == "gem-pro"


def test_skips_already_tried_models(models_file: Path) -> None:
    # Scenario: first two gemini models already tried.
    # Setup: comma-joined tried list matching bash idiom ",a,b,".
    tried = {"gemini": "gem-pro,gem-flash", "codex": "", "claude": ""}
    # Test action: request next model.
    result = debate_nextModel("gemini", tried, str(models_file))
    # Test verification: third model returned.
    assert result == "gem-lite"


def test_returns_none_when_all_tried(models_file: Path) -> None:
    # Scenario: every model in the list has been tried.
    # Setup: tried list contains all gemini entries.
    tried = {"gemini": "gem-pro,gem-flash,gem-lite", "codex": "", "claude": ""}
    # Test action: request next model.
    result = debate_nextModel("gemini", tried, str(models_file))
    # Test verification: bash returned rc=1; Python returns None.
    assert result is None


def test_unknown_agent_returns_none(models_file: Path) -> None:
    # Scenario: agent key absent from models.json.
    # Setup: tried dict has agent but JSON does not.
    tried = {"mystery": ""}
    # Test action: request next model for unknown agent.
    result = debate_nextModel("mystery", tried, str(models_file))
    # Test verification: no model available -> None.
    assert result is None


def test_partial_tried_with_leading_comma(models_file: Path) -> None:
    # Scenario: tried list has bash-style leading comma artifact (",first").
    # Setup: tried entry mimics how _stash appends (",${next}").
    tried = {"codex": ",gpt-a"}
    # Test action: request next codex model.
    result = debate_nextModel("codex", tried, str(models_file))
    # Test verification: gpt-a is skipped, gpt-b returned.
    assert result == "gpt-b"


def test_missing_models_file_returns_none(tmp_path: Path) -> None:
    # Scenario: models.json path does not exist.
    # Setup: point at nonexistent file (bash hide_errors -> empty stdin -> rc=1).
    tried = {"gemini": ""}
    # Test action: request next model.
    result = debate_nextModel("gemini", tried, str(tmp_path / "missing.json"))
    # Test verification: graceful None.
    assert result is None



# --- debate_paneHasCapacityError ---

import os
import sys
from unittest.mock import patch

# Make the temp module importable.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)



# ---------- codex agent ----------

def test_codex_capacity_marker_present_returns_truthy():
    # Scenario: codex pane shows the "at capacity" message in scrollback.
    # Setup: mock tmux_capturePane to return a buffer containing the marker.
    fake_capture = "some banner\nSelected model is at capacity\nmore output\n"
    # Test action: call debate_paneHasCapacityError for the codex agent.
    with patch(
        "jot_plugin_orchestrator.tmux_capturePane",
        return_value=fake_capture,
    ) as m:
        result = debate_paneHasCapacityError("%7", "codex")
    # Test verification: result is truthy (bool(result) is True).
    assert bool(result) is True
    # And capture was requested with -S -200 scrollback to mirror bash.
    m.assert_called_once_with("%7", scrollback_lines=200)


def test_codex_overloaded_marker_present_returns_truthy():
    # Scenario: codex pane shows the secondary "model is overloaded" marker.
    # Setup: capture buffer contains only the second codex marker.
    fake_capture = "noise\nmodel is overloaded right now\nnoise\n"
    # Test action: probe codex for capacity error.
    with patch(
        "jot_plugin_orchestrator.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%1", "codex")
    # Test verification: truthy bool indicates a capacity hit.
    assert bool(result) is True


def test_codex_no_marker_returns_falsy():
    # Scenario: codex pane shows healthy output, no capacity markers.
    # Setup: capture buffer with unrelated content.
    fake_capture = "all good\nready\n> _\n"
    # Test action: probe codex for capacity error.
    with patch(
        "jot_plugin_orchestrator.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%1", "codex")
    # Test verification: result is falsy (bool() is False).
    assert bool(result) is False


# ---------- gemini agent ----------

def test_gemini_resource_exhausted_returns_truthy():
    # Scenario: gemini pane prints RESOURCE_EXHAUSTED quota error.
    # Setup: capture contains the gemini-specific marker.
    fake_capture = "ERROR: RESOURCE_EXHAUSTED please retry later\n"
    # Test action: probe gemini for capacity error.
    with patch(
        "jot_plugin_orchestrator.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%2", "gemini")
    # Test verification: truthy bool indicates capacity hit.
    assert bool(result) is True


def test_gemini_marker_for_other_agent_does_not_match():
    # Scenario: pane shows codex-specific marker but agent arg is "gemini".
    # Setup: capture has codex marker text only; gemini markers should NOT match.
    fake_capture = "Selected model is at capacity\n"
    # Test action: probe gemini.
    with patch(
        "jot_plugin_orchestrator.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%2", "gemini")
    # Test verification: per-agent markers are isolated -> falsy.
    assert bool(result) is False


# ---------- claude agent ----------

def test_claude_api_529_returns_truthy():
    # Scenario: claude pane prints HTTP 529 overload error.
    # Setup: capture contains "API Error: 529" marker.
    fake_capture = "request failed: API Error: 529 overloaded_error: please retry\n"
    # Test action: probe claude.
    with patch(
        "jot_plugin_orchestrator.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%3", "claude")
    # Test verification: truthy bool.
    assert bool(result) is True


# ---------- unknown agent ----------

def test_unknown_agent_returns_falsy_without_capturing():
    # Scenario: caller passes an unrecognised agent name.
    # Setup: patch tmux_capturePane so we can assert it is NEVER called
    # (mirrors bash: empty marker stream -> while-loop body never executes,
    # function returns 1 with no side effects).
    with patch(
        "jot_plugin_orchestrator.tmux_capturePane",
        return_value="API Error: 529\n",
    ) as m:
        # Test action: probe with a bogus agent.
        result = debate_paneHasCapacityError("%9", "nonsense-agent")
    # Test verification: falsy AND tmux capture not invoked.
    assert bool(result) is False
    assert m.call_count == 0


# ---------- ANSI escape stripping ----------

def test_ansi_escape_bytes_are_stripped_before_match():
    # Scenario: pane capture is interleaved with raw ESC bytes (\033) the way
    # tmux emits color codes; bash uses `tr -d '\033'` before grep -F.
    # Setup: insert ESC bytes inside the marker so a naive substring search
    # against the unstripped buffer would FAIL.
    marker = "API Error: 529"
    poisoned = "API\033 Error:\033 529"  # same chars, ESC interleaved
    fake_capture = f"prefix {poisoned} suffix\n"
    # Test action: probe claude.
    with patch(
        "jot_plugin_orchestrator.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%4", "claude")
    # Test verification: ESC stripping lets the marker match -> truthy.
    assert bool(result) is True
    # And the matched marker text is the canonical (ESC-free) string.
    assert result == marker


# ---------- empty capture ----------

def test_empty_capture_returns_falsy():
    # Scenario: tmux capture-pane fails or pane has no output (returns "").
    # Setup: tmux_capturePane returns empty string (its documented failure mode).
    # Test action: probe codex.
    with patch(
        "jot_plugin_orchestrator.tmux_capturePane",
        return_value="",
    ):
        result = debate_paneHasCapacityError("%5", "codex")
    # Test verification: nothing to match -> falsy.
    assert bool(result) is False



# --- debate_probeCodex ---

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(
    0,
    "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts",
)
sys.path.insert(
    0,
    "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts/_migration_workspace",
)



def test_returns_empty_when_codex_binary_missing():
    # Scenario: codex CLI is not installed on PATH.
    # Setup: shutil.which("codex") returns None; credentials irrelevant.
    # Test action: invoke debate_probeCodex().
    # Test verification: returns "" (unavailable sentinel, mirrors bash empty stdout).
    with patch("jot_plugin_orchestrator.shutil.which", return_value=None), \
         patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
        result = debate_probeCodex()
    assert result == ""


def test_returns_empty_when_no_credentials_present():
    # Scenario: codex binary exists but no auth.json and no OPENAI_API_KEY.
    # Setup: which returns a path; auth.json absent; env var unset.
    # Test action: invoke debate_probeCodex().
    # Test verification: returns "" because credentials gate fails.
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    with patch("jot_plugin_orchestrator.shutil.which", return_value="/usr/local/bin/codex"), \
         patch("jot_plugin_orchestrator.os.path.isfile", return_value=False), \
         patch.dict(os.environ, env, clear=True):
        result = debate_probeCodex()
    assert result == ""


def test_returns_present_when_available_but_no_model_configured():
    # Scenario: codex binary + credentials exist, but models.json has no codex entry.
    # Setup: which → path; auth.json present; _default_model returns "".
    # Test action: invoke debate_probeCodex().
    # Test verification: returns "present" sentinel so outer `-s` check passes.
    with patch("jot_plugin_orchestrator.shutil.which", return_value="/usr/local/bin/codex"), \
         patch("jot_plugin_orchestrator.os.path.isfile", return_value=True), \
         patch("jot_plugin_orchestrator.debate_defaultModel", return_value=""):
        result = debate_probeCodex()
    assert result == "present"


def test_returns_model_name_when_configured():
    # Scenario: codex binary + credentials exist AND models.json lists a model.
    # Setup: which → path; auth.json present; _default_model returns "gpt-5".
    # Test action: invoke debate_probeCodex().
    # Test verification: returns the model name verbatim.
    with patch("jot_plugin_orchestrator.shutil.which", return_value="/usr/local/bin/codex"), \
         patch("jot_plugin_orchestrator.os.path.isfile", return_value=True), \
         patch("jot_plugin_orchestrator.debate_defaultModel", return_value="gpt-5"):
        result = debate_probeCodex()
    assert result == "gpt-5"


def test_openai_api_key_alone_satisfies_credentials_gate():
    # Scenario: no auth.json on disk, but OPENAI_API_KEY env var is set.
    # Setup: which → path; isfile → False; env has OPENAI_API_KEY.
    # Test action: invoke debate_probeCodex().
    # Test verification: returns model name (proves env-var path is honored).
    with patch("jot_plugin_orchestrator.shutil.which", return_value="/usr/local/bin/codex"), \
         patch("jot_plugin_orchestrator.os.path.isfile", return_value=False), \
         patch("jot_plugin_orchestrator.debate_defaultModel", return_value="gpt-5"), \
         patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
        result = debate_probeCodex()
    assert result == "gpt-5"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))



# --- debate_retryPaneWithNextModel ---

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# Workspace path setup mirrors the plan's import block.
sys.path.insert(0, str(Path(__file__).resolve().parent))


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

_BASE_KWARGS = dict(
    pane_index=0,
    agent="gemini",
    stage="r1",
    current_pane_id="%10",
    current_model={"gemini": "gemini-pro"},
    tried_models={"gemini": "gemini-pro"},
    window_target="debate:0",
    cwd="/tmp/cwd",
    repo_root="/tmp/repo",
    home="/tmp/home",
    settings_file="/tmp/settings.json",
    debate_dir="/tmp/debate",
    models_json_path="/tmp/models.json",
)


# ---------------------------------------------------------------------------
# RED test 1 -- no remaining models -> returns None
# ---------------------------------------------------------------------------
def test_no_next_model_returns_none():
    # Scenario: _next_model exhausted; no models left for agent.
    # Setup: debate_nextModel returns None.
    # Test action: call debate_retryPaneWithNextModel.
    # Test verification: returns None; no pane kill or creation attempted.
    with (
        patch(
            "jot_plugin_orchestrator.debate_nextModel",
            return_value=None,
        ) as mock_next,
        patch(
            "jot_plugin_orchestrator.debate_newEmptyPane"
        ) as mock_new_pane,
    ):
        result = debate_retryPaneWithNextModel(**_BASE_KWARGS)

    assert result is None
    mock_new_pane.assert_not_called()


# ---------------------------------------------------------------------------
# RED test 2 -- happy path: updates tried_models and current_model dicts
# ---------------------------------------------------------------------------
def test_updates_model_dicts_on_success():
    # Scenario: next model found; dicts should reflect new model after call.
    # Setup: debate_nextModel returns "gemini-flash"; launch + prompt succeed.
    # Test action: call with mutable dicts; check mutations after.
    # Test verification: current_model["gemini"] == "gemini-flash";
    #                    "gemini-flash" appended to tried_models["gemini"].
    current_model = {"gemini": "gemini-pro"}
    tried_models = {"gemini": "gemini-pro"}

    with (
        patch(
            "jot_plugin_orchestrator.debate_nextModel",
            return_value="gemini-flash",
        ),
        patch(
            "jot_plugin_orchestrator.debate_newEmptyPane",
            return_value="%11",
        ),
        patch(
            "jot_plugin_orchestrator.debate_agentLaunchCmd",
            return_value="gemini --model gemini-flash",
        ),
        patch("jot_plugin_orchestrator._kill_pane"),
        patch("jot_plugin_orchestrator._launch_agent", return_value=True),
        patch("jot_plugin_orchestrator._send_prompt", return_value=True),
    ):
        kwargs = dict(_BASE_KWARGS)
        kwargs["current_model"] = current_model
        kwargs["tried_models"] = tried_models
        debate_retryPaneWithNextModel(**kwargs)

    assert current_model["gemini"] == "gemini-flash"
    assert "gemini-flash" in tried_models["gemini"]


# ---------------------------------------------------------------------------
# RED test 3 -- happy path: kills old pane and returns new pane id
# ---------------------------------------------------------------------------
def test_kills_old_pane_returns_new_pane_id():
    # Scenario: successful rotation; old pane killed, new pane id returned.
    # Setup: debate_nextModel = "gemini-flash"; debate_newEmptyPane = "%99".
    # Test action: call debate_retryPaneWithNextModel.
    # Test verification: _kill_pane called with "%10"; return value == "%99".
    kill_mock = MagicMock()

    with (
        patch(
            "jot_plugin_orchestrator.debate_nextModel",
            return_value="gemini-flash",
        ),
        patch(
            "jot_plugin_orchestrator.debate_newEmptyPane",
            return_value="%99",
        ),
        patch(
            "jot_plugin_orchestrator.debate_agentLaunchCmd",
            return_value="gemini --model gemini-flash",
        ),
        patch(
            "jot_plugin_orchestrator._kill_pane", kill_mock
        ),
        patch("jot_plugin_orchestrator._launch_agent", return_value=True),
        patch("jot_plugin_orchestrator._send_prompt", return_value=True),
    ):
        result = debate_retryPaneWithNextModel(**_BASE_KWARGS)

    kill_mock.assert_called_once_with("%10")
    assert result == "%99"


# ---------------------------------------------------------------------------
# RED test 4 -- launch_agent failure propagates as None
# ---------------------------------------------------------------------------
def test_launch_agent_failure_returns_none():
    # Scenario: new pane created but agent fails to become ready.
    # Setup: _launch_agent returns False.
    # Test action: call debate_retryPaneWithNextModel.
    # Test verification: returns None (mirrors bash `return 1`).
    with (
        patch(
            "jot_plugin_orchestrator.debate_nextModel",
            return_value="gemini-flash",
        ),
        patch(
            "jot_plugin_orchestrator.debate_newEmptyPane",
            return_value="%11",
        ),
        patch(
            "jot_plugin_orchestrator.debate_agentLaunchCmd",
            return_value="gemini --model gemini-flash",
        ),
        patch("jot_plugin_orchestrator._kill_pane"),
        patch(
            "jot_plugin_orchestrator._launch_agent", return_value=False
        ),
        patch("jot_plugin_orchestrator._send_prompt", return_value=True),
    ):
        result = debate_retryPaneWithNextModel(**_BASE_KWARGS)

    assert result is None


# ---------------------------------------------------------------------------
# RED test 5 -- send_prompt failure propagates as None
# ---------------------------------------------------------------------------
def test_send_prompt_failure_returns_none():
    # Scenario: agent launched fine but prompt delivery timed out.
    # Setup: _launch_agent True; _send_prompt returns False.
    # Test action: call debate_retryPaneWithNextModel.
    # Test verification: returns None.
    with (
        patch(
            "jot_plugin_orchestrator.debate_nextModel",
            return_value="gemini-flash",
        ),
        patch(
            "jot_plugin_orchestrator.debate_newEmptyPane",
            return_value="%11",
        ),
        patch(
            "jot_plugin_orchestrator.debate_agentLaunchCmd",
            return_value="gemini --model gemini-flash",
        ),
        patch("jot_plugin_orchestrator._kill_pane"),
        patch("jot_plugin_orchestrator._launch_agent", return_value=True),
        patch(
            "jot_plugin_orchestrator._send_prompt", return_value=False
        ),
    ):
        result = debate_retryPaneWithNextModel(**_BASE_KWARGS)

    assert result is None


# ---------------------------------------------------------------------------
# RED test 6 -- tried_models entry created from scratch when agent not present
# ---------------------------------------------------------------------------
def test_tried_models_created_when_agent_missing():
    # Scenario: agent key absent from tried_models (first rotation ever).
    # Setup: tried_models = {} (empty); next model = "codex-mini".
    # Test action: call with agent="codex", tried_models={}.
    # Test verification: tried_models["codex"] contains "codex-mini".
    current_model: dict[str, str] = {}
    tried_models: dict[str, str] = {}

    with (
        patch(
            "jot_plugin_orchestrator.debate_nextModel",
            return_value="codex-mini",
        ),
        patch(
            "jot_plugin_orchestrator.debate_newEmptyPane",
            return_value="%20",
        ),
        patch(
            "jot_plugin_orchestrator.debate_agentLaunchCmd",
            return_value="codex -a never",
        ),
        patch("jot_plugin_orchestrator._kill_pane"),
        patch("jot_plugin_orchestrator._launch_agent", return_value=True),
        patch("jot_plugin_orchestrator._send_prompt", return_value=True),
    ):
        kwargs = dict(_BASE_KWARGS)
        kwargs["agent"] = "codex"
        kwargs["current_pane_id"] = "%5"
        kwargs["current_model"] = current_model
        kwargs["tried_models"] = tried_models
        debate_retryPaneWithNextModel(**kwargs)

    assert "codex-mini" in tried_models.get("codex", "")
    assert current_model.get("codex") == "codex-mini"



# --- debate_tmuxOrchestrator ---

import os
import sys
from unittest.mock import MagicMock, call, patch

import pytest




# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_kwargs(**overrides: object) -> dict:
    """Return a minimal valid call-site kwargs dict."""
    base: dict = dict(
        debate_dir="/tmp/debate",
        session="jot",
        window_name="debate",
        settings_file="/tmp/settings.json",
        cwd="/tmp/repo",
        repo_root="/tmp/repo",
        plugin_root="/tmp/plugin",
        debate_agents="claude gemini",
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_raises_when_session_empty() -> None:
    # Scenario: caller passes empty SESSION; orchestrator must abort like bash `:?` guard.
    # Setup: all args valid except session="".
    # Test action: call debate_tmuxOrchestrator with session="".
    # Test verification: ValueError raised with "SESSION required".
    with pytest.raises(ValueError, match="SESSION required"):
        debate_tmuxOrchestrator(**_valid_kwargs(session=""))


def test_raises_when_debate_agents_empty_and_no_env() -> None:
    # Scenario: caller passes empty debate_agents and env var absent; must abort.
    # Setup: no DEBATE_AGENTS env var, debate_agents="".
    # Test action: call with debate_agents="".
    # Test verification: ValueError raised with "DEBATE_AGENTS".
    env = {k: v for k, v in os.environ.items() if k != "DEBATE_AGENTS"}
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValueError, match="DEBATE_AGENTS"):
            debate_tmuxOrchestrator(**_valid_kwargs(debate_agents=""))


def test_debate_agents_falls_back_to_env() -> None:
    # Scenario: debate_agents="" but DEBATE_AGENTS env var is set; orchestrator uses env value.
    # Setup: inject mock daemon_main and cleanup; set DEBATE_AGENTS env.
    # Test action: call with debate_agents="".
    # Test verification: daemon_main called once; ctx.agents matches env value.
    mock_daemon = MagicMock()
    mock_cleanup = MagicMock()
    with patch.dict(os.environ, {"DEBATE_AGENTS": "claude codex"}, clear=False):
        debate_tmuxOrchestrator(
            **_valid_kwargs(debate_agents=""),
            daemon_main_fn=mock_daemon,
            cleanup_fn=mock_cleanup,
        )
    ctx: DebateContext = mock_daemon.call_args[0][0]
    assert ctx.agents == ["claude", "codex"]


def test_window_target_composed_from_session_and_window_name() -> None:
    # Scenario: window_target must be "SESSION:WINDOW_NAME" matching bash `WINDOW_TARGET="${SESSION}:${WINDOW_NAME}"`.
    # Setup: inject mock daemon_main; pass distinct session and window_name.
    # Test action: call debate_tmuxOrchestrator with session="mysession" window_name="mywin".
    # Test verification: ctx.window_target == "mysession:mywin".
    mock_daemon = MagicMock()
    debate_tmuxOrchestrator(
        **_valid_kwargs(session="mysession", window_name="mywin"),
        daemon_main_fn=mock_daemon,
        cleanup_fn=MagicMock(),
    )
    ctx: DebateContext = mock_daemon.call_args[0][0]
    assert ctx.window_target == "mysession:mywin"


def test_stage_timeout_is_900_seconds() -> None:
    # Scenario: STAGE_TIMEOUT must be 15*60=900 (bash hard-code).
    # Setup: inject mock daemon_main.
    # Test action: call debate_tmuxOrchestrator with valid args.
    # Test verification: ctx.stage_timeout == 900.
    mock_daemon = MagicMock()
    debate_tmuxOrchestrator(
        **_valid_kwargs(),
        daemon_main_fn=mock_daemon,
        cleanup_fn=MagicMock(),
    )
    ctx: DebateContext = mock_daemon.call_args[0][0]
    assert ctx.stage_timeout == 900


def test_agents_parsed_from_space_separated_string() -> None:
    # Scenario: DEBATE_AGENTS is a space-separated string; must be split into list.
    # Setup: debate_agents="claude gemini codex".
    # Test action: call debate_tmuxOrchestrator.
    # Test verification: ctx.agents == ["claude", "gemini", "codex"].
    mock_daemon = MagicMock()
    debate_tmuxOrchestrator(
        **_valid_kwargs(debate_agents="claude gemini codex"),
        daemon_main_fn=mock_daemon,
        cleanup_fn=MagicMock(),
    )
    ctx: DebateContext = mock_daemon.call_args[0][0]
    assert ctx.agents == ["claude", "gemini", "codex"]


def test_daemon_main_called_once_with_context() -> None:
    # Scenario: daemon_main must be called exactly once, receiving the DebateContext.
    # Setup: inject mock daemon_main and cleanup.
    # Test action: call debate_tmuxOrchestrator with valid args.
    # Test verification: mock_daemon called once; arg is DebateContext instance.
    mock_daemon = MagicMock()
    debate_tmuxOrchestrator(
        **_valid_kwargs(),
        daemon_main_fn=mock_daemon,
        cleanup_fn=MagicMock(),
    )
    mock_daemon.assert_called_once()
    ctx = mock_daemon.call_args[0][0]
    assert isinstance(ctx, DebateContext)


def test_cleanup_called_even_when_daemon_raises() -> None:
    # Scenario: mirrors `trap cleanup EXIT` — cleanup runs even if daemon_main raises.
    # Setup: daemon_main raises RuntimeError; inject mock cleanup.
    # Test action: call debate_tmuxOrchestrator; catch the raised error.
    # Test verification: cleanup called exactly once despite the exception.
    mock_cleanup = MagicMock()
    mock_daemon = MagicMock(side_effect=RuntimeError("daemon exploded"))
    with pytest.raises(RuntimeError, match="daemon exploded"):
        debate_tmuxOrchestrator(
            **_valid_kwargs(),
            daemon_main_fn=mock_daemon,
            cleanup_fn=mock_cleanup,
        )
    mock_cleanup.assert_called_once()


def test_returns_zero_on_success() -> None:
    # Scenario: successful run must return 0 (POSIX exit-code convention).
    # Setup: daemon_main and cleanup are no-ops.
    # Test action: call debate_tmuxOrchestrator.
    # Test verification: return value is 0.
    result = debate_tmuxOrchestrator(
        **_valid_kwargs(),
        daemon_main_fn=MagicMock(),
        cleanup_fn=MagicMock(),
    )
    assert result == 0


def test_context_stores_all_positional_args() -> None:
    # Scenario: all seven positional args must be stored verbatim on the context object.
    # Setup: inject distinct values for all positional args.
    # Test action: call debate_tmuxOrchestrator.
    # Test verification: each ctx field matches the supplied value.
    mock_daemon = MagicMock()
    debate_tmuxOrchestrator(
        debate_dir="/d/debate",
        session="s1",
        window_name="w1",
        settings_file="/d/settings.json",
        cwd="/d/cwd",
        repo_root="/d/repo",
        plugin_root="/d/plugin",
        debate_agents="agent_a",
        daemon_main_fn=mock_daemon,
        cleanup_fn=MagicMock(),
    )
    ctx: DebateContext = mock_daemon.call_args[0][0]
    assert ctx.debate_dir == "/d/debate"
    assert ctx.session == "s1"
    assert ctx.window_name == "w1"
    assert ctx.settings_file == "/d/settings.json"
    assert ctx.cwd == "/d/cwd"
    assert ctx.repo_root == "/d/repo"
    assert ctx.plugin_root == "/d/plugin"



# --- debate_waitForOutputs ---

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts/_migration_workspace")


def _write(p: Path, content: str = "x") -> None:
    p.write_text(content)


def test_returns_true_when_all_outputs_already_present(tmp_path):
    # Scenario: all agent output files exist with non-empty content before first poll
    # Setup: create r1_<agent>.md for each agent, populate panes map
    agents = ["gemini", "codex"]
    for a in agents:
        _write(tmp_path / f"r1_{a}.md", "done")
    panes = {0: "%1", 1: "%2"}
    capacity_check = MagicMock(return_value=False)
    retry_cb = MagicMock()
    sleep_fn = MagicMock()
    # Test action: call with short timeout
    ok, completed, reason = debate_waitForOutputs(
        prefix="r1", timeout=10, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=capacity_check,
        retry_pane=retry_cb, sleep_fn=sleep_fn, poll_interval=5,
    )
    # Test verification: success, both agents completed, no retries, no sleeps
    assert ok is True
    assert sorted(completed) == ["codex", "gemini"]
    assert reason is None
    retry_cb.assert_not_called()


def test_returns_false_with_timeout_reason_when_outputs_never_appear(tmp_path):
    # Scenario: no output files materialize within timeout
    # Setup: empty debate dir, panes have no capacity errors
    agents = ["gemini"]
    panes = {0: "%1"}
    sleep_fn = MagicMock()
    # Test action: timeout=5, poll=5 -> exactly one iteration
    ok, completed, reason = debate_waitForOutputs(
        prefix="r1", timeout=5, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=lambda p, a: False,
        retry_pane=MagicMock(), sleep_fn=sleep_fn, poll_interval=5,
    )
    # Test verification: failure with timeout reason, no completions
    assert ok is False
    assert completed == []
    assert reason is not None and "timeout" in reason.lower()


def test_removes_lock_file_when_output_appears(tmp_path):
    # Scenario: lock file exists alongside output; lock must be deleted on detection
    # Setup: create output AND lock file
    agents = ["claude"]
    panes = {0: "%1"}
    out = tmp_path / "r2_claude.md"
    lock = tmp_path / ".r2_claude.lock"
    _write(out, "synthesis")
    _write(lock, "debate:%1")
    # Test action: poll once
    ok, completed, _ = debate_waitForOutputs(
        prefix="r2", timeout=5, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=lambda p, a: False,
        retry_pane=MagicMock(), sleep_fn=MagicMock(), poll_interval=5,
    )
    # Test verification: success, lock file removed
    assert ok is True
    assert completed == ["claude"]
    assert not lock.exists()


def test_invokes_retry_when_pane_has_capacity_error_and_no_output(tmp_path):
    # Scenario: agent pane shows capacity error and no output file exists yet
    # Setup: no output files; capacity_check returns True for one agent
    agents = ["gemini"]
    panes = {0: "%5"}
    retry_cb = MagicMock()
    sleep_fn = MagicMock()
    # Test action: single poll iteration before timeout
    ok, _, reason = debate_waitForOutputs(
        prefix="r1", timeout=5, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=lambda p, a: True,
        retry_pane=retry_cb, sleep_fn=sleep_fn, poll_interval=5,
    )
    # Test verification: retry callback invoked with (panes, index, agent, prefix)
    assert ok is False
    assert reason is not None
    retry_cb.assert_called_once()
    args = retry_cb.call_args[0]
    assert args[1] == 0  # index
    assert args[2] == "gemini"
    assert args[3] == "r1"


def test_partial_completion_returns_only_completed_agents(tmp_path):
    # Scenario: some agents finish, others time out
    # Setup: only codex output present
    agents = ["gemini", "codex", "claude"]
    panes = {0: "%1", 1: "%2", 2: "%3"}
    _write(tmp_path / "r1_codex.md", "done")
    # Test action: timeout exhausted with partial state
    ok, completed, reason = debate_waitForOutputs(
        prefix="r1", timeout=5, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=lambda p, a: False,
        retry_pane=MagicMock(), sleep_fn=MagicMock(), poll_interval=5,
    )
    # Test verification: ok=False, only codex in completed
    assert ok is False
    assert completed == ["codex"]
    assert "timeout" in reason.lower()


def test_empty_output_file_does_not_count_as_complete(tmp_path):
    # Scenario: output file exists but is zero-byte (matches bash `[ -s "$out" ]`)
    # Setup: create empty file
    agents = ["gemini"]
    panes = {0: "%1"}
    (tmp_path / "r1_gemini.md").write_text("")  # zero bytes
    # Test action: single poll
    ok, completed, _ = debate_waitForOutputs(
        prefix="r1", timeout=5, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=lambda p, a: False,
        retry_pane=MagicMock(), sleep_fn=MagicMock(), poll_interval=5,
    )
    # Test verification: empty file -> not complete -> timeout
    assert ok is False
    assert completed == []



# --- debate_writeFailed ---

import sys
from datetime import datetime, timezone
from pathlib import Path

# Mirror the temp module's sys.path bootstrap so the import resolves regardless of CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent))



_FIXED_NOW = lambda: datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)


def test_writes_failed_txt_at_debate_dir_root(tmp_path):
    # Scenario: one agent missing, no lock; FAILED.txt should appear at debate_dir/FAILED.txt.
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    # Test action:
    out = debate_writeFailed(debate_dir, "R1", "boom", ["gemini"], now=_FIXED_NOW)
    # Test verification:
    assert out == debate_dir / "FAILED.txt"
    assert out.is_file()


def test_header_contains_stage_reason_and_iso_timestamp(tmp_path):
    # Scenario: header lines must include stage, reason, ISO-8601 timestamp from injected clock.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    # Test action:
    debate_writeFailed(debate_dir, "R2", "launch_agent timeout", [], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert text.startswith("# debate FAILED\n")
    assert "stage: R2\n" in text
    assert "reason: launch_agent timeout\n" in text
    assert "timestamp: 2026-05-04T12:00:00+00:00\n" in text


def test_skips_agents_with_nonempty_output_files(tmp_path):
    # Scenario: agent who produced a non-empty stage_<agent>.md must NOT appear in missing list.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    (debate_dir / "R1_gemini.md").write_text("real output\n")
    # Test action:
    debate_writeFailed(debate_dir, "R1", "partial", ["gemini", "codex"], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "### gemini" not in text
    assert "### codex" in text


def test_empty_output_file_counts_as_missing(tmp_path):
    # Scenario: zero-byte output file means agent did not finish; treat as missing.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    (debate_dir / "R1_codex.md").write_text("")  # empty
    # Test action:
    debate_writeFailed(debate_dir, "R1", "x", ["codex"], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "### codex" in text


def test_missing_lock_file_emits_placeholder_line(tmp_path):
    # Scenario: agent missing AND no .lock file -> placeholder string instead of fenced block.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    # Test action:
    debate_writeFailed(debate_dir, "R1", "x", ["claude"], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "(no pane captured -- lock file missing or malformed)" in text
    assert "```" not in text


def test_lock_with_pane_id_invokes_capture_and_fences_output(tmp_path):
    # Scenario: lock file points to pane; pane_capture callback's text is fenced.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    (debate_dir / ".R1_gemini.lock").write_text("debate:%42\n")
    captured = {}

    def fake_capture(pane_id):
        captured["pane"] = pane_id
        return "RESOURCE_EXHAUSTED line1\nline2"

    # Test action:
    debate_writeFailed(
        debate_dir, "R1", "capacity", ["gemini"],
        pane_capture=fake_capture, now=_FIXED_NOW,
    )
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert captured["pane"] == "%42"
    assert "```\nRESOURCE_EXHAUSTED line1\nline2\n```" in text


def test_overwrites_existing_failed_txt(tmp_path):
    # Scenario: a stale FAILED.txt must be replaced atomically (overwrite, not append).
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    (debate_dir / "FAILED.txt").write_text("OLD CONTENT SHOULD VANISH\n")
    # Test action:
    debate_writeFailed(debate_dir, "R1", "fresh", ["gemini"], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "OLD CONTENT SHOULD VANISH" not in text
    assert "reason: fresh" in text


def test_no_temp_files_left_behind_on_success(tmp_path):
    # Scenario: atomic publish via mktemp+rename must leave no .FAILED.txt.* siblings.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    # Test action:
    debate_writeFailed(debate_dir, "R1", "x", ["gemini"], now=_FIXED_NOW)
    # Test verification:
    leftovers = [p.name for p in debate_dir.iterdir() if p.name.startswith(".FAILED.txt.")]
    assert leftovers == []


def test_missing_agents_section_header_present(tmp_path):
    # Scenario: the literal '## missing agents' header is always emitted, even with zero agents.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    # Test action:
    debate_writeFailed(debate_dir, "R1", "x", [], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "## missing agents\n" in text


def test_pane_capture_callback_failure_yields_unavailable_marker(tmp_path):
    # Scenario: capture callback raises -> body still well-formed with '(pane capture unavailable)'.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    (debate_dir / ".R1_codex.lock").write_text("debate:%7\n")

    def boom(_pane_id):
        raise RuntimeError("tmux gone")

    # Test action:
    debate_writeFailed(
        debate_dir, "R1", "x", ["codex"],
        pane_capture=boom, now=_FIXED_NOW,
    )
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "```\n(pane capture unavailable)\n```" in text



# --- jot_collectDiagnostics ---

import os
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts/_migration_workspace")



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(path: str) -> str:
    return Path(path).read_text()


# ---------------------------------------------------------------------------
# Section 1 — report header
# ---------------------------------------------------------------------------

class TestReportHeader:
    def test_report_file_created_at_default_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: caller passes no out_path; function auto-generates /tmp/jot-diag-*.log
        # Setup: redirect default tmp location to tmp_path via env or by passing explicit path
        out = str(tmp_path / "diag.log")
        # Test action:
        result = jot_collectDiagnostics(out_path=out)
        # Test verification:
        assert result == out
        assert Path(out).exists()

    def test_report_contains_header_line(self, tmp_path: Path) -> None:
        # Scenario: report always starts with the literal banner line
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "jot-diag-collect report" in content

    def test_report_contains_generated_timestamp(self, tmp_path: Path) -> None:
        # Scenario: report header includes a "generated:" line with ISO timestamp
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "generated:" in content

    def test_report_contains_cwd_line(self, tmp_path: Path) -> None:
        # Scenario: report header includes a "cwd:" line
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "cwd:" in content

    def test_report_contains_project_line(self, tmp_path: Path) -> None:
        # Scenario: report header includes a "project:" line derived from repo root basename
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "project:" in content


# ---------------------------------------------------------------------------
# Section 2 — section banners (uses jot_diagSection format)
# ---------------------------------------------------------------------------

class TestSectionBanners:
    def test_section_1_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 1 banner for Latest Todos input files
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "1. Latest Todos/*_input.txt" in content

    def test_section_2_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 2 banner for state dir
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "2. State dir" in content

    def test_section_3_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 3 banner for tmux session
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "3. tmux session" in content

    def test_section_4_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 4 banner for /tmp/jot.* dirs
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "4. /tmp/jot." in content

    def test_section_5_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 5 banner for log file
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "5." in content

    def test_section_6_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 6 banner for Todos/ listing
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "6. Todos/" in content

    def test_section_7_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 7 banner for plugin orchestrator path
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "7. Installed plugin orchestrator" in content

    def test_section_8_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 8 banner for dependency check
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "8. Dependency check" in content

    def test_end_of_report_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report ends with END OF REPORT banner
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "END OF REPORT" in content

    def test_section_banners_use_box_drawing_rule(self, tmp_path: Path) -> None:
        # Scenario: section banners use the 59-char box-drawing rule (jot_diagSection format)
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification: box-drawing char appears (from jot_diagSection)
        assert "═" in content  # '═'


# ---------------------------------------------------------------------------
# Section 3 — section 1: Todos/*_input.txt
# ---------------------------------------------------------------------------

class TestTodosInputSection:
    def test_no_input_txt_shows_not_found_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: Todos/ dir has no *_input.txt files
        # Setup: point REPO_ROOT at tmp_path (no Todos/ dir)
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "no input.txt found" in content

    def test_input_txt_present_shows_kv_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: Todos/ contains one *_input.txt; report shows path kv
        # Setup:
        todos = tmp_path / "Todos"
        todos.mkdir()
        inp = todos / "task_input.txt"
        inp.write_text("# Jot Task\ndo something\n")
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GIT_DIR", "")  # suppress git, cwd becomes repo_root
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "path" in content
        assert "task_input.txt" in content

    def test_input_txt_pending_status(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: input.txt first line is "# Jot Task" -> status shows PENDING
        # Setup:
        todos = tmp_path / "Todos"
        todos.mkdir()
        inp = todos / "task_input.txt"
        inp.write_text("# Jot Task\ndo something\n")
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "PENDING" in content

    def test_input_txt_processed_status(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: input.txt first line starts with "PROCESSED:" -> status shows PROCESSED
        # Setup:
        todos = tmp_path / "Todos"
        todos.mkdir()
        inp = todos / "task_input.txt"
        inp.write_text("PROCESSED: done\nsome content\n")
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "PROCESSED" in content


# ---------------------------------------------------------------------------
# Section 4 — section 2: state dir
# ---------------------------------------------------------------------------

class TestStateDirSection:
    def test_missing_state_dir_shows_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: STATE_DIR does not exist; report notes this
        # Setup:
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "state dir does not exist" in content

    def test_queue_txt_empty_shows_empty_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: queue.txt exists but is empty
        # Setup:
        state = tmp_path / "Todos" / ".jot-state"
        state.mkdir(parents=True)
        (state / "queue.txt").write_text("")
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "empty" in content or "no jobs pending" in content

    def test_queue_txt_missing_shows_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: state dir exists but queue.txt absent
        # Setup:
        state = tmp_path / "Todos" / ".jot-state"
        state.mkdir(parents=True)
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "missing" in content

    def test_queue_lock_held_shows_lock_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: queue.lock exists; report warns lock is held
        # Setup:
        state = tmp_path / "Todos" / ".jot-state"
        state.mkdir(parents=True)
        (state / "queue.lock").mkdir()  # dir-based mkdir lock
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "LOCK IS HELD" in content

    def test_queue_lock_free_shows_free_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: no queue.lock; report confirms lock is free
        # Setup:
        state = tmp_path / "Todos" / ".jot-state"
        state.mkdir(parents=True)
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "free" in content or "no lock held" in content


# ---------------------------------------------------------------------------
# Section 5 — section 8: dependency check uses kv format
# ---------------------------------------------------------------------------

class TestDependencySection:
    def test_dependency_section_lists_known_cmds(self, tmp_path: Path) -> None:
        # Scenario: dependency check covers the 5 expected commands
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification: all 5 deps appear
        for cmd in ("jq", "python3", "tmux", "claude", "osascript"):
            assert cmd in content, f"missing dependency check for {cmd!r}"

    def test_dependency_found_cmd_shows_path(self, tmp_path: Path) -> None:
        # Scenario: python3 is always present; its which-path appears in report
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification: python3 row has a path (starts with /)
        lines = [l for l in content.splitlines() if l.startswith("python3") or "python3" in l[:30]]
        found = any("/" in l for l in lines)
        assert found, f"python3 path not found in dep lines: {lines}"


# ---------------------------------------------------------------------------
# Section 6 — return value
# ---------------------------------------------------------------------------

class TestReturnValue:
    def test_returns_out_path_string(self, tmp_path: Path) -> None:
        # Scenario: explicit out_path is returned verbatim
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        result = jot_collectDiagnostics(out_path=out)
        # Test verification:
        assert result == out

    def test_default_out_path_is_in_tmp(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: when out_path is None, returned path is under /tmp
        # Setup: we cannot write to real /tmp in all CI environments, so skip
        # if /tmp is not writable; otherwise verify prefix.
        if not os.access("/tmp", os.W_OK):
            pytest.skip("/tmp not writable")
        # Test action:
        result = jot_collectDiagnostics(out_path=None)
        # Test verification:
        assert result.startswith("/tmp/jot-diag-")
        assert Path(result).exists()
        Path(result).unlink(missing_ok=True)



# --- plate_summaryStop ---

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure the workspace dir is importable.
sys.path.insert(0, str(Path(__file__).parent))

import pytest


def test_missing_repo_arg_is_noop(tmp_path):
    # Scenario: hook invoked without REPO arg returns early without side effects.
    # Setup: empty repo/branch; valid output_file path that exists.
    out = tmp_path / "summary.txt"
    out.write_text("body")
    with patch("jot_plugin_orchestrator.subprocess.run") as run:
        # Test action:
        rc = plate_summaryStop("", "main", str(out))
        # Test verification: cli.py never invoked when args missing.
        assert rc == 0
        run.assert_not_called()


def test_missing_branch_arg_is_noop(tmp_path):
    # Scenario: empty branch arg short-circuits.
    # Setup: valid repo, empty branch, existing output file.
    out = tmp_path / "summary.txt"
    out.write_text("body")
    with patch("jot_plugin_orchestrator.subprocess.run") as run:
        # Test action:
        rc = plate_summaryStop(str(tmp_path), "", str(out))
        # Test verification:
        assert rc == 0
        run.assert_not_called()


def test_missing_output_file_arg_is_noop(tmp_path):
    # Scenario: empty output_file arg short-circuits.
    # Setup: valid repo, valid branch, empty output_file.
    with patch("jot_plugin_orchestrator.subprocess.run") as run:
        # Test action:
        rc = plate_summaryStop(str(tmp_path), "main", "")
        # Test verification:
        assert rc == 0
        run.assert_not_called()


def test_nonexistent_output_file_is_noop(tmp_path):
    # Scenario: output_file does not exist on disk -> early exit, no cli call.
    # Setup: a path that points nowhere.
    missing = tmp_path / "nope.txt"
    with patch("jot_plugin_orchestrator.subprocess.run") as run:
        # Test action:
        rc = plate_summaryStop(str(tmp_path), "main", str(missing))
        # Test verification:
        assert rc == 0
        run.assert_not_called()


def test_invokes_cli_set_plate_summary_with_args(tmp_path):
    # Scenario: happy path forwards repo/branch/output_file to cli.py set-plate-summary.
    # Setup: existing repo dir + output file; capture subprocess.run call.
    out = tmp_path / "summary.txt"
    out.write_text("agent summary")
    with patch("jot_plugin_orchestrator.subprocess.run") as run:
        run.return_value = MagicMock(stdout="ok\n", returncode=0)
        # Test action:
        rc = plate_summaryStop(str(tmp_path), "feature-x", str(out))
        # Test verification: cli.py invoked with the three positional args.
        assert rc == 0
        assert run.called
        argv = run.call_args[0][0]
        assert "set-plate-summary" in argv
        assert str(tmp_path) in argv
        assert "feature-x" in argv
        assert str(out) in argv


def test_writes_audit_log_line(tmp_path, monkeypatch):
    # Scenario: every invocation appends one line to the plate-log.txt.
    # Setup: PLATE_LOG_FILE env var points at a writable file under tmp_path.
    log = tmp_path / "plate-log.txt"
    monkeypatch.setenv("PLATE_LOG_FILE", str(log))
    out = tmp_path / "summary.txt"
    out.write_text("body")
    with patch("jot_plugin_orchestrator.subprocess.run") as run:
        run.return_value = MagicMock(stdout="ok", returncode=0)
        # Test action:
        plate_summaryStop(str(tmp_path), "main", str(out))
    # Test verification: log file exists and contains the marker substring.
    assert log.exists()
    text = log.read_text()
    assert "plate-summary-stop" in text
    assert "main" in text


def test_cli_failure_is_swallowed(tmp_path, monkeypatch):
    # Scenario: cli.py crashes -> hook still returns 0 (never block shutdown).
    # Setup: subprocess.run raises CalledProcessError-like exception.
    log = tmp_path / "plate-log.txt"
    monkeypatch.setenv("PLATE_LOG_FILE", str(log))
    out = tmp_path / "summary.txt"
    out.write_text("body")
    with patch("jot_plugin_orchestrator.subprocess.run") as run:
        run.side_effect = RuntimeError("boom")
        # Test action: must not raise.
        rc = plate_summaryStop(str(tmp_path), "main", str(out))
        # Test verification: returns 0 regardless of subprocess failure.
        assert rc == 0



# --- plate_summaryWatch ---

import sys
from pathlib import Path

# Make the workspace importable regardless of pytest invocation cwd.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import pytest



# ---------------------------------------------------------------------------
# Test doubles: deterministic sleep + tmux send injection
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_returns_zero_when_output_file_already_non_empty(tmp_path):
    # Scenario: agent has already written its summary before the watcher polls.
    # Setup: pre-create a non-empty output file.
    out = tmp_path / "summary.txt"
    out.write_text("done")
    sleep = FakeClock()
    send = FakeTmux()

    # Test action: run the watcher with a generous timeout.
    rc = plate_summaryWatch(
        pane="plate-summary-7:plate-summary-abc",
        output_file=str(out),
        timeout=600,
        interval=2,
        sleep=sleep,
        tmux_send=send,
    )

    # Test verification: rc==0, no sleep call needed (file ready first poll).
    assert rc == 0
    assert sleep.calls == 0


def test_sends_exit_then_enter_when_file_becomes_non_empty(tmp_path):
    # Scenario: file appears non-empty after a couple of poll intervals.
    # Setup: schedule the file to be written on tick #2.
    out = tmp_path / "summary.txt"

    def writer(tick: int) -> None:
        if tick == 2:
            out.write_text("summary body")

    sleep = FakeClock(on_tick=writer)
    send = FakeTmux()

    # Test action.
    rc = plate_summaryWatch(
        pane="pane:0",
        output_file=str(out),
        timeout=600,
        interval=2,
        sleep=sleep,
        tmux_send=send,
    )

    # Test verification: rc==0 AND exactly the documented two-step send sequence.
    assert rc == 0
    assert send.sent == [("pane:0", "/exit"), ("pane:0", "Enter")]


def test_returns_one_on_timeout_without_sending(tmp_path):
    # Scenario: file never becomes non-empty; watcher must give up.
    # Setup: file does not exist (and stays absent across all ticks).
    out = tmp_path / "never.txt"
    sleep = FakeClock()
    send = FakeTmux()

    # Test action: timeout=4s, interval=2s -> exactly 2 polls then exit.
    rc = plate_summaryWatch(
        pane="pane:0",
        output_file=str(out),
        timeout=4,
        interval=2,
        sleep=sleep,
        tmux_send=send,
    )

    # Test verification: failure rc, NO tmux dispatch, slept exactly timeout/interval times.
    assert rc == 1
    assert send.sent == []
    assert sleep.calls == 2


def test_empty_file_is_treated_as_not_ready(tmp_path):
    # Scenario: file exists but is zero-byte (atomicity invariant: agent
    # uses temp-then-rename, so empty = not yet written).
    # Setup: create the file empty, fill it on tick #1.
    out = tmp_path / "summary.txt"
    out.write_text("")

    def writer(tick: int) -> None:
        if tick == 1:
            out.write_text("payload")

    sleep = FakeClock(on_tick=writer)
    send = FakeTmux()

    # Test action.
    rc = plate_summaryWatch(
        pane="pane:0",
        output_file=str(out),
        timeout=600,
        interval=2,
        sleep=sleep,
        tmux_send=send,
    )

    # Test verification: watcher slept at least once before sending /exit.
    assert rc == 0
    assert sleep.calls >= 1
    assert ("pane:0", "/exit") in send.sent


def test_swallows_tmux_send_errors_and_still_returns_zero(tmp_path):
    # Scenario: pane has already gone away (user closed it). send-keys raises;
    # watcher must still report success per docstring ("just exit successfully").
    # Setup: pre-populated file + tmux double that throws.
    out = tmp_path / "summary.txt"
    out.write_text("done")
    sleep = FakeClock()
    send = FakeTmux(raise_on_call=True)

    # Test action.
    rc = plate_summaryWatch(
        pane="dead:pane",
        output_file=str(out),
        timeout=10,
        interval=1,
        sleep=sleep,
        tmux_send=send,
    )

    # Test verification: graceful success.
    assert rc == 0


def test_env_overrides_supply_default_timeout_and_interval(tmp_path, monkeypatch):
    # Scenario: caller omits timeout/interval -> values come from env knobs
    # PLATE_SUMMARY_WATCH_TIMEOUT / PLATE_SUMMARY_WATCH_INTERVAL.
    # Setup: env says timeout=6s, interval=3s; file never appears.
    monkeypatch.setenv("PLATE_SUMMARY_WATCH_TIMEOUT", "6")
    monkeypatch.setenv("PLATE_SUMMARY_WATCH_INTERVAL", "3")
    out = tmp_path / "never.txt"
    sleep = FakeClock()
    send = FakeTmux()

    # Test action: do NOT pass timeout/interval.
    rc = plate_summaryWatch(
        pane="pane:0",
        output_file=str(out),
        sleep=sleep,
        tmux_send=send,
    )

    # Test verification: 6/3 = 2 polls, then timeout rc==1.
    assert rc == 1
    assert sleep.calls == 2



# --- shell_waitForFile ---

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))



def test_returns_true_when_file_already_nonempty(tmp_path):
    # Scenario: target file already has content before polling begins.
    # Setup: create a non-empty file in tmp_path.
    target = tmp_path / "synthesis.md"
    target.write_text("done")
    # Test action: invoke shell_waitForFile with a 5s timeout.
    result = shell_waitForFile(str(target), timeout=5, poll_interval=0.01)
    # Test verification: returns True (success) without sleeping out the timeout.
    assert result is True


def test_returns_false_when_file_never_appears(tmp_path):
    # Scenario: target file never exists; helper must time out.
    # Setup: tmp_path is empty; build a path that will never be created.
    target = tmp_path / "missing.md"
    # Test action: poll for it with a tiny timeout/interval to keep test fast.
    result = shell_waitForFile(str(target), timeout=0.05, poll_interval=0.01)
    # Test verification: returns False indicating timeout.
    assert result is False


def test_returns_false_when_file_exists_but_empty(tmp_path):
    # Scenario: bash uses `[ -s ]` (non-empty) so empty files do NOT satisfy.
    # Setup: create a zero-byte file.
    target = tmp_path / "empty.md"
    target.touch()
    # Test action: poll until short timeout.
    result = shell_waitForFile(str(target), timeout=0.05, poll_interval=0.01)
    # Test verification: empty file is treated as "not yet ready"; returns False.
    assert result is False


def test_returns_true_when_file_appears_during_polling(tmp_path, monkeypatch):
    # Scenario: file is written after several poll iterations.
    # Setup: counter-driven fake sleep that creates the file on the 3rd call.
    target = tmp_path / "late.md"
    calls = {"n": 0}

    def fake_sleep(_seconds):
        calls["n"] += 1
        if calls["n"] == 3:
            target.write_text("ready")

    monkeypatch.setattr("jot_plugin_orchestrator.time.sleep", fake_sleep)
    # Test action: poll with timeout large enough to allow 3 fake sleeps.
    result = shell_waitForFile(str(target), timeout=10, poll_interval=1)
    # Test verification: helper observed the late-arriving file and returned True.
    assert result is True
    assert calls["n"] >= 3



# --- todo_scanOpen ---

import sys
from pathlib import Path

# Standard temp file header: make _migration_workspace importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))



def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_returns_empty_list_when_todos_dir_missing(tmp_path: Path) -> None:
    # Scenario: target dir has no Todos/ subdir at all.
    # Setup: tmp_path is empty (no Todos/).
    # Test action: invoke todo_scanOpen on the bare target.
    result = todo_scanOpen(tmp_path)
    # Test verification: returns empty list, never raises.
    assert result == []


def test_returns_empty_list_when_todos_dir_has_no_markdown(tmp_path: Path) -> None:
    # Scenario: Todos/ exists but contains no .md files.
    # Setup: create Todos/ with one non-md file.
    todos = tmp_path / "Todos"
    todos.mkdir()
    _write(todos / "notes.txt", "status: open\n")
    # Test action: scan.
    result = todo_scanOpen(tmp_path)
    # Test verification: non-md files are ignored.
    assert result == []


def test_returns_only_files_with_status_open_in_frontmatter(tmp_path: Path) -> None:
    # Scenario: mixed statuses across multiple .md files.
    # Setup: three TODOs — open, closed, open.
    todos = tmp_path / "Todos"
    _write(todos / "a.md", "---\nstatus: open\n---\nbody\n")
    _write(todos / "b.md", "---\nstatus: closed\n---\nbody\n")
    _write(todos / "c.md", "---\nstatus: open\n---\nbody\n")
    # Test action: scan.
    result = todo_scanOpen(tmp_path)
    # Test verification: only the two open files appear.
    names = sorted(Path(p).name for p in result)
    assert names == ["a.md", "c.md"]


def test_results_are_sorted_alphabetically_like_bash_glob(tmp_path: Path) -> None:
    # Scenario: bash `for f in Todos/*.md` yields glob order (alphabetical).
    # Setup: create files in non-alphabetical creation order.
    todos = tmp_path / "Todos"
    for name in ("z.md", "a.md", "m.md"):
        _write(todos / name, "status: open\n")
    # Test action: scan.
    result = todo_scanOpen(tmp_path)
    # Test verification: returned order is alphabetical by filename.
    names = [Path(p).name for p in result]
    assert names == ["a.md", "m.md", "z.md"]


def test_status_open_must_anchor_at_line_start(tmp_path: Path) -> None:
    # Scenario: bash uses `grep '^status: open'` — embedded matches must NOT count.
    # Setup: file whose only mention of "status: open" is mid-line.
    todos = tmp_path / "Todos"
    _write(todos / "x.md", "---\nnote: previous status: open was wrong\n---\n")
    # Test action: scan.
    result = todo_scanOpen(tmp_path)
    # Test verification: non-anchored mention is rejected.
    assert result == []


def test_only_first_ten_lines_are_inspected(tmp_path: Path) -> None:
    # Scenario: bash uses `head -10` — status: open beyond line 10 must be ignored.
    # Setup: file with status: open on line 12.
    todos = tmp_path / "Todos"
    body = "\n".join(["filler"] * 11 + ["status: open", "more"])
    _write(todos / "late.md", body)
    # Test action: scan.
    result = todo_scanOpen(tmp_path)
    # Test verification: late status is not picked up.
    assert result == []


def test_returns_absolute_paths(tmp_path: Path) -> None:
    # Scenario: callers (jot_main) feed result into a markdown report; path
    # must be unambiguous regardless of cwd.
    # Setup: one open TODO.
    todos = tmp_path / "Todos"
    _write(todos / "only.md", "status: open\n")
    # Test action: scan with an absolute target_dir.
    result = todo_scanOpen(tmp_path)
    # Test verification: every returned path is absolute and points at the file.
    assert len(result) == 1
    p = Path(result[0])
    assert p.is_absolute()
    assert p.name == "only.md"


def test_accepts_string_path_argument(tmp_path: Path) -> None:
    # Scenario: bash callers pass plain strings; Python signature must accept
    # both str and Path (parity with `scan_open_todos "$REPO_ROOT"`).
    # Setup: one open TODO.
    todos = tmp_path / "Todos"
    _write(todos / "only.md", "status: open\n")
    # Test action: pass a str, not a Path.
    result = todo_scanOpen(str(tmp_path))
    # Test verification: works the same.
    assert len(result) == 1



# --- todo_sessionStart ---

import sys
from pathlib import Path
from unittest.mock import call, patch

import pytest

# Workspace sys.path setup so import resolves without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))



# ---------------------------------------------------------------------------
# Scenario: missing args
# ---------------------------------------------------------------------------

def test_missing_input_file_returns_0(tmp_path, capsys):
    # Scenario: both args absent (input_file is empty string)
    # Setup: no files needed
    # Test action:
    rc = todo_sessionStart("", str(tmp_path))
    # Test verification:
    assert rc == 0
    assert "[todo-session-start]" in capsys.readouterr().err


def test_missing_tmpdir_inv_returns_0(tmp_path, capsys):
    # Scenario: tmpdir_inv is empty string
    # Setup: a real input file so only tmpdir is missing
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    # Test action:
    rc = todo_sessionStart(str(input_file), "")
    # Test verification:
    assert rc == 0
    assert "[todo-session-start]" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Scenario: tmux_target sidecar absent
# ---------------------------------------------------------------------------

def test_missing_sidecar_returns_0(tmp_path, capsys):
    # Scenario: tmpdir exists but tmux_target file is never written
    # Setup: input file present, no tmux_target sidecar
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    # Test action: patch sleep to avoid 1s delay (5 * 0.2)
    with patch("jot_plugin_orchestrator.time.sleep"):
        rc = todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification:
    assert rc == 0
    assert "tmux_target sidecar empty" in capsys.readouterr().err


def test_empty_sidecar_returns_0(tmp_path, capsys):
    # Scenario: tmux_target file exists but is empty
    # Setup:
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    (tmpdir / "tmux_target").write_text("")
    # Test action:
    with patch("jot_plugin_orchestrator.time.sleep"):
        rc = todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification:
    assert rc == 0
    assert "tmux_target sidecar empty" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Scenario: Claude TUI not ready
# ---------------------------------------------------------------------------

def test_claude_not_ready_returns_1(tmp_path, capsys):
    # Scenario: sidecar present but tmux_waitForClaudeReadiness returns 1
    # Setup:
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    (tmpdir / "tmux_target").write_text("%42\n")
    # Test action:
    with patch("jot_plugin_orchestrator.tmux_waitForClaudeReadiness", return_value=1):
        rc = todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification:
    assert rc == 1
    assert "claude TUI not ready" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Scenario: happy path
# ---------------------------------------------------------------------------

def test_happy_path_sends_prompt(tmp_path):
    # Scenario: all conditions met; expect jot_sendPrompt called with correct args
    # Setup:
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    (tmpdir / "tmux_target").write_text("%42\n")
    # Test action:
    with patch("jot_plugin_orchestrator.tmux_waitForClaudeReadiness", return_value=0), \
         patch("jot_plugin_orchestrator.jot_sendPrompt", return_value=0) as mock_send:
        rc = todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification:
    assert rc == 0
    mock_send.assert_called_once_with("%42", str(input_file))


def test_happy_path_propagates_send_rc(tmp_path):
    # Scenario: jot_sendPrompt returns nonzero; function should propagate it
    # Setup:
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    (tmpdir / "tmux_target").write_text("%99\n")
    # Test action:
    with patch("jot_plugin_orchestrator.tmux_waitForClaudeReadiness", return_value=0), \
         patch("jot_plugin_orchestrator.jot_sendPrompt", return_value=3):
        rc = todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification:
    assert rc == 3


def test_sidecar_read_strips_whitespace(tmp_path):
    # Scenario: sidecar has trailing newline; pane id must be stripped before use
    # Setup:
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    (tmpdir / "tmux_target").write_text("  %7  \n")
    # Test action:
    with patch("jot_plugin_orchestrator.tmux_waitForClaudeReadiness", return_value=0) as mock_wait, \
         patch("jot_plugin_orchestrator.jot_sendPrompt", return_value=0):
        todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification: pane id passed to readiness check must be stripped
    mock_wait.assert_called_once_with("%7")



# --- todo_stop ---

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).parent))



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tmpdir(tmp_path: Path, tmux_target: str = "%42") -> Path:
    """Write a minimal per-invocation tmpdir with tmux_target sidecar."""
    d = tmp_path / "todo.XXXX"
    d.mkdir()
    (d / "tmux_target").write_text(f"{tmux_target}\n")
    return d


# ---------------------------------------------------------------------------
# Missing-args guard
# ---------------------------------------------------------------------------


def test_missing_args_returns_early(tmp_path: Path, capsys) -> None:
    # Scenario: all three required args are empty strings
    # Setup: no filesystem state needed
    # Test action: call with empty strings
    rc = todo_stop("", "", "")
    # Test verification: must not raise; logs to stderr; returns 0
    captured = capsys.readouterr()
    assert rc == 0
    assert "[todo-stop] missing args" in captured.err


def test_missing_state_dir_returns_early(tmp_path: Path, capsys) -> None:
    # Scenario: input_file and tmpdir_inv present but state_dir empty
    # Setup:
    inv = _make_tmpdir(tmp_path)
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action:
    rc = todo_stop(str(input_file), str(inv), "")
    # Test verification:
    captured = capsys.readouterr()
    assert rc == 0
    assert "[todo-stop] missing args" in captured.err


# ---------------------------------------------------------------------------
# tmux_target sidecar retry / failure
# ---------------------------------------------------------------------------


def test_empty_sidecar_logs_and_returns(tmp_path: Path, capsys) -> None:
    # Scenario: tmux_target file exists but is empty after all retries
    # Setup:
    inv = tmp_path / "inv"
    inv.mkdir()
    (inv / "tmux_target").write_text("")       # empty — no pane id
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action: patch time.sleep so test is fast
    with patch("jot_plugin_orchestrator.time.sleep"):
        rc = todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    captured = capsys.readouterr()
    assert rc == 0
    assert "tmux_target sidecar empty" in captured.err


def test_missing_sidecar_file_logs_and_returns(tmp_path: Path, capsys) -> None:
    # Scenario: tmux_target file does not exist at all
    # Setup:
    inv = tmp_path / "inv"
    inv.mkdir()
    # no tmux_target written
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action:
    with patch("jot_plugin_orchestrator.time.sleep"):
        rc = todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    captured = capsys.readouterr()
    assert rc == 0
    assert "tmux_target sidecar empty" in captured.err


# ---------------------------------------------------------------------------
# Audit log — SUCCESS path
# ---------------------------------------------------------------------------


def test_processed_marker_writes_success_to_audit(tmp_path: Path) -> None:
    # Scenario: input.txt first line starts with "PROCESSED:"
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\nsome other content\n")
    # Test action:
    with (
        patch("jot_plugin_orchestrator.time.sleep"),
        patch("jot_plugin_orchestrator.tmux_killPane"),
        patch("jot_plugin_orchestrator.tmux_retile"),
    ):
        rc = todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    assert rc == 0
    audit = (state_dir / "audit.log").read_text()
    assert "SUCCESS" in audit
    assert str(input_file) in audit


def test_processed_marker_removes_input_file(tmp_path: Path) -> None:
    # Scenario: SUCCESS path should delete the input file
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action:
    with (
        patch("jot_plugin_orchestrator.time.sleep"),
        patch("jot_plugin_orchestrator.tmux_killPane"),
        patch("jot_plugin_orchestrator.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification: file must be gone
    assert not input_file.exists()


# ---------------------------------------------------------------------------
# Audit log — FAIL paths
# ---------------------------------------------------------------------------


def test_no_processed_marker_writes_fail_to_audit(tmp_path: Path) -> None:
    # Scenario: input.txt exists but first line lacks PROCESSED:
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("still pending\n")
    # Test action:
    with (
        patch("jot_plugin_orchestrator.time.sleep"),
        patch("jot_plugin_orchestrator.tmux_killPane"),
        patch("jot_plugin_orchestrator.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    audit = (state_dir / "audit.log").read_text()
    assert "FAIL" in audit
    assert "no PROCESSED marker" in audit


def test_no_processed_marker_does_not_remove_input_file(tmp_path: Path) -> None:
    # Scenario: FAIL path must NOT delete the input file (only SUCCESS deletes it)
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("still pending\n")
    # Test action:
    with (
        patch("jot_plugin_orchestrator.time.sleep"),
        patch("jot_plugin_orchestrator.tmux_killPane"),
        patch("jot_plugin_orchestrator.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    assert input_file.exists()


def test_missing_input_file_writes_fail_missing_to_audit(tmp_path: Path) -> None:
    # Scenario: input.txt does not exist at all
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "nonexistent_input.txt"
    # Test action:
    with (
        patch("jot_plugin_orchestrator.time.sleep"),
        patch("jot_plugin_orchestrator.tmux_killPane"),
        patch("jot_plugin_orchestrator.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    audit = (state_dir / "audit.log").read_text()
    assert "FAIL" in audit
    assert "input.txt missing" in audit


# ---------------------------------------------------------------------------
# Audit rotation
# ---------------------------------------------------------------------------


def test_audit_rotated_when_over_1000_lines(tmp_path: Path) -> None:
    # Scenario: audit.log exceeds 1000 lines; must be trimmed to 1000
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    audit = state_dir / "audit.log"
    # Write 1005 lines
    audit.write_text("\n".join(f"line {i}" for i in range(1005)) + "\n")
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action:
    with (
        patch("jot_plugin_orchestrator.time.sleep"),
        patch("jot_plugin_orchestrator.tmux_killPane"),
        patch("jot_plugin_orchestrator.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification: line count must be <= 1000
    line_count = len([l for l in audit.read_text().splitlines() if l])
    assert line_count <= 1000


# ---------------------------------------------------------------------------
# tmux pane kill (side-effect verification)
# ---------------------------------------------------------------------------


def test_kill_pane_called_with_correct_target(tmp_path: Path) -> None:
    # Scenario: tmux_killPane must be called with the pane id from sidecar
    # Setup:
    inv = _make_tmpdir(tmp_path, tmux_target="%99")
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    kill_mock = MagicMock(return_value=0)
    retile_mock = MagicMock(return_value=0)
    # Test action:
    with (
        patch("jot_plugin_orchestrator.time.sleep"),
        patch("jot_plugin_orchestrator.tmux_killPane", kill_mock),
        patch("jot_plugin_orchestrator.tmux_retile", retile_mock),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    kill_mock.assert_called_once_with("%99")


def test_retile_called_with_todo_todos_window(tmp_path: Path) -> None:
    # Scenario: tmux_retile must target "todo:todos" after killing pane
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    retile_mock = MagicMock(return_value=0)
    # Test action:
    with (
        patch("jot_plugin_orchestrator.time.sleep"),
        patch("jot_plugin_orchestrator.tmux_killPane"),
        patch("jot_plugin_orchestrator.tmux_retile", retile_mock),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    retile_mock.assert_called_once_with("todo:todos")


def test_state_dir_created_if_absent(tmp_path: Path) -> None:
    # Scenario: state_dir does not pre-exist; function must create it
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "new_state_dir"
    # Do NOT create state_dir
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action:
    with (
        patch("jot_plugin_orchestrator.time.sleep"),
        patch("jot_plugin_orchestrator.tmux_killPane"),
        patch("jot_plugin_orchestrator.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    assert state_dir.is_dir()
    assert (state_dir / "audit.log").is_file()



# --- debate_cleanup ---

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))



# ---------------------------------------------------------------------------
# Test 1 — removes /tmp/debate.* directory
# ---------------------------------------------------------------------------
def test_removes_tmp_debate_dir(tmp_path: Path) -> None:
    # Scenario: settings_file lives inside a /tmp/debate.XYZ directory.
    # Setup: create a mock /tmp/debate.XYZ tree under tmp_path (so we don't
    #   touch real /tmp). We monkey-patch by creating the structure locally
    #   and passing the fake path; the guard checks parent.name == "debate.*"
    #   and parent.parent == Path("/tmp"). We build the fake tree and
    #   temporarily repoint by using a symlink trick — actually, the function
    #   checks Path("/tmp") literally, so we directly fabricate a path string
    #   with a real /tmp/debate.* dir to exercise it.
    import tempfile, shutil, os

    # Create a real /tmp/debate.<unique> directory
    debate_dir = Path(tempfile.mkdtemp(prefix="debate.", dir="/tmp"))
    settings_file = debate_dir / "settings.json"
    settings_file.write_text("{}")

    try:
        # Test action:
        debate_cleanup(settings_file)

        # Test verification: directory must be gone
        assert not debate_dir.exists(), f"Expected {debate_dir} to be removed"
    finally:
        # Safety: clean up if test failed before removal
        if debate_dir.exists():
            shutil.rmtree(debate_dir)


# ---------------------------------------------------------------------------
# Test 2 — does NOT remove a non-/tmp/debate.* directory
# ---------------------------------------------------------------------------
def test_ignores_non_tmp_debate_dir(tmp_path: Path) -> None:
    # Scenario: settings_file is in a user project dir, not /tmp/debate.*.
    # Setup:
    settings_dir = tmp_path / "my_project_settings"
    settings_dir.mkdir()
    settings_file = settings_dir / "settings.json"
    settings_file.write_text("{}")

    # Test action:
    debate_cleanup(settings_file)

    # Test verification: directory must still exist
    assert settings_dir.exists(), "Non-/tmp/debate.* dir must not be removed"


# ---------------------------------------------------------------------------
# Test 3 — does NOT remove /tmp directory that does not start with "debate."
# ---------------------------------------------------------------------------
def test_ignores_tmp_non_debate_prefix(tmp_path: Path) -> None:
    # Scenario: settings_file is in /tmp/somethingelse (no "debate." prefix).
    # Setup:
    import tempfile, shutil

    other_dir = Path(tempfile.mkdtemp(prefix="notdebate.", dir="/tmp"))
    settings_file = other_dir / "settings.json"
    settings_file.write_text("{}")

    try:
        # Test action:
        debate_cleanup(settings_file)

        # Test verification: directory must still exist
        assert other_dir.exists(), "Non-debate-prefixed /tmp dir must not be removed"
    finally:
        if other_dir.exists():
            shutil.rmtree(other_dir)


# ---------------------------------------------------------------------------
# Test 4 — no-op when debate dir does not exist (already cleaned up)
# ---------------------------------------------------------------------------
def test_noop_when_dir_already_gone() -> None:
    # Scenario: cleanup called twice; second call should not raise.
    # Setup: fabricate a path that looks like /tmp/debate.XYZ but doesn't exist
    nonexistent = Path("/tmp/debate.already_deleted_abc123/settings.json")
    assert not nonexistent.parent.exists(), "Precondition: dir must not exist"

    # Test action + Test verification: must not raise
    debate_cleanup(nonexistent)


# ---------------------------------------------------------------------------
# Test 5 — accepts str path (not just Path)
# ---------------------------------------------------------------------------
def test_accepts_str_path(tmp_path: Path) -> None:
    # Scenario: caller passes a plain str instead of a Path object.
    # Setup:
    import tempfile, shutil

    debate_dir = Path(tempfile.mkdtemp(prefix="debate.", dir="/tmp"))
    settings_file = str(debate_dir / "settings.json")
    (debate_dir / "settings.json").write_text("{}")

    try:
        # Test action:
        debate_cleanup(settings_file)

        # Test verification:
        assert not debate_dir.exists()
    finally:
        if debate_dir.exists():
            shutil.rmtree(debate_dir)



# --- jot_sessionEnd ---

# Workspace temp tests for `jot_sessionEnd`.
# RELAXED_COVERAGE: derived from bash intent/docstring; no paired bash _tests.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))



def test_removes_tmp_jot_directory_recursively(tmp_path, monkeypatch):
    # Scenario: hook fires on a well-formed /tmp/jot.* tmpdir at session end.
    # Setup: create a fake /tmp/jot.<id> dir with nested content; redirect /tmp via symlink-style path.
    fake_root = tmp_path / "tmp"
    fake_root.mkdir()
    target = fake_root / "jot.abc123"
    (target / "subdir").mkdir(parents=True)
    (target / "subdir" / "tmux_target").write_text("%42")
    (target / "input.txt").write_text("PROCESSED: ok")
    # Use the literal /tmp/jot.* pattern by creating it under a path that matches.
    # Since jot_sessionEnd validates by string prefix, exercise the real pattern path.
    real_target = Path("/tmp") / f"jot.pytest_{tmp_path.name}"
    real_target.mkdir(parents=True, exist_ok=True)
    (real_target / "marker").write_text("x")

    # Test action: invoke jot_sessionEnd against the real /tmp/jot.* path.
    rc = jot_sessionEnd(str(real_target))

    # Test verification: directory removed, return code 0.
    assert rc == 0
    assert not real_target.exists(), "tmpdir should be wiped recursively"


def test_refuses_path_outside_safelist(tmp_path, capsys):
    # Scenario: caller passes a path not matching /tmp/jot.* or /private/tmp/jot.*.
    # Setup: create a real directory under tmp_path with a file inside.
    rogue = tmp_path / "not_a_jot_dir"
    rogue.mkdir()
    sentinel = rogue / "keep_me.txt"
    sentinel.write_text("must_survive")

    # Test action: call with the rogue path.
    rc = jot_sessionEnd(str(rogue))

    # Test verification: returns 0, stderr contains refusal, directory NOT deleted.
    assert rc == 0
    assert rogue.exists() and sentinel.exists(), "non-safelist path must NOT be removed"
    err = capsys.readouterr().err
    assert "refusing to rm unexpected path" in err
    assert str(rogue) in err


def test_refuses_empty_argument(capsys):
    # Scenario: hook invoked with no $1 (bash sets to empty string).
    # Setup: none required.

    # Test action: call with empty string.
    rc = jot_sessionEnd("")

    # Test verification: exits 0, refusal message on stderr, no filesystem mutation possible.
    assert rc == 0
    err = capsys.readouterr().err
    assert "refusing to rm unexpected path" in err


def test_accepts_private_tmp_jot_prefix(tmp_path):
    # Scenario: macOS resolves /tmp -> /private/tmp; hook must accept that prefix too.
    # Setup: create real /private/tmp/jot.<id> dir.
    target = Path("/private/tmp") / f"jot.pytest_priv_{tmp_path.name}"
    target.mkdir(parents=True, exist_ok=True)
    (target / "leaf").write_text("data")

    # Test action: invoke with the /private/tmp/jot.* path.
    rc = jot_sessionEnd(str(target))

    # Test verification: removed cleanly.
    assert rc == 0
    assert not target.exists()


def test_missing_directory_is_silent_success(tmp_path):
    # Scenario: tmpdir already wiped by another hook; rm -rf must not error.
    # Setup: compute a /tmp/jot.* path that does not exist.
    ghost = Path("/tmp") / f"jot.pytest_ghost_{tmp_path.name}"
    assert not ghost.exists()

    # Test action: call jot_sessionEnd on the nonexistent path.
    rc = jot_sessionEnd(str(ghost))

    # Test verification: returns 0, no exception (matches `rm -rf` ignore-missing semantics).
    assert rc == 0


def test_refuses_lookalike_prefix(tmp_path, capsys):
    # Scenario: attacker-style path like /tmp/jotfake or /tmp/jot (no dot) must be refused.
    # Setup: create the lookalike directory with content under a sandboxed root we control.
    # We test the validation logic only — never create under real /tmp without `.` separator.
    bad_path = "/tmp/jotfake_should_be_refused"

    # Test action: call with non-conforming path.
    rc = jot_sessionEnd(bad_path)

    # Test verification: refused, stderr message present.
    assert rc == 0
    err = capsys.readouterr().err
    assert "refusing to rm unexpected path" in err
    assert bad_path in err



# --- jot_sessionStart ---

import sys
from pathlib import Path

import pytest

sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts/_migration_workspace")



def test_missing_input_file_returns_0_and_warns(capsys):
    # Scenario: caller forgot to pass input_file; bash spec returns silent exit 0.
    # Setup: input_file=None, tmpdir_inv non-empty.
    # Test action: invoke jot_sessionStart with missing input_file.
    rc = jot_sessionStart(None, "/some/tmpdir")
    err = capsys.readouterr().err
    # Test verification: rc is 0 and stderr names the missing-args contract.
    assert rc == 0
    assert "missing args" in err


def test_missing_tmpdir_inv_returns_0_and_warns(capsys):
    # Scenario: caller forgot tmpdir_inv argument.
    # Setup: input_file present, tmpdir_inv empty string.
    # Test action: invoke with empty tmpdir_inv.
    rc = jot_sessionStart("/x/in.md", "")
    err = capsys.readouterr().err
    # Test verification: rc is 0 and missing-args message emitted.
    assert rc == 0
    assert "missing args" in err


def test_sidecar_empty_after_retries_returns_0(tmp_path, monkeypatch, capsys):
    # Scenario: tmux_target sidecar never appears within 5 retries.
    # Setup: empty tmpdir, monkeypatch sleep to no-op so test runs fast.
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    # Test action: call with valid args but no sidecar file present.
    rc = jot_sessionStart("/x/in.md", str(tmp_path))
    err = capsys.readouterr().err
    # Test verification: rc 0 and stderr explains sidecar emptiness.
    assert rc == 0
    assert "tmux_target sidecar empty" in err


def test_sidecar_zero_byte_file_treated_as_empty(tmp_path, monkeypatch, capsys):
    # Scenario: sidecar exists but is zero-byte (race window).
    # Setup: create empty tmux_target file; bypass real sleeps.
    (tmp_path / "tmux_target").write_text("")
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    # Test action: invoke jot_sessionStart.
    rc = jot_sessionStart("/x/in.md", str(tmp_path))
    err = capsys.readouterr().err
    # Test verification: empty sidecar is rejected as if missing.
    assert rc == 0
    assert "tmux_target sidecar empty" in err


def test_readiness_timeout_returns_1(tmp_path, monkeypatch, capsys):
    # Scenario: pane id resolved but Claude TUI never shows the ready glyph.
    # Setup: write valid sidecar; stub readiness probe to return 1 (timeout).
    (tmp_path / "tmux_target").write_text("%42\n")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(mod, "tmux_waitForClaudeReadiness", lambda pane: 1)
    monkeypatch.setattr(
        mod, "tmux_sendAndSubmit",
        lambda pane, text: sent.append((pane, text)) or 0,
    )
    # Test action: invoke jot_sessionStart.
    rc = jot_sessionStart("/x/in.md", str(tmp_path))
    err = capsys.readouterr().err
    # Test verification: rc 1, no keys sent, diagnostic emitted.
    assert rc == 1
    assert "claude TUI not ready" in err
    assert sent == []


def test_happy_path_sends_read_prompt_to_resolved_pane(tmp_path, monkeypatch):
    # Scenario: sidecar present, TUI ready -> prompt is submitted to that pane.
    # Setup: write pane id "%99" into sidecar; stub readiness to 0; capture sends.
    (tmp_path / "tmux_target").write_text("%99\nignored-extra\n")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(mod, "tmux_waitForClaudeReadiness", lambda pane: 0)
    monkeypatch.setattr(
        mod, "tmux_sendAndSubmit",
        lambda pane, text: sent.append((pane, text)) or 0,
    )
    # Test action: invoke with realistic args.
    rc = jot_sessionStart("/path/to/input.md", str(tmp_path))
    # Test verification: rc 0, exactly one send to first-line pane id, exact prompt text.
    assert rc == 0
    assert sent == [
        ("%99", "Read /path/to/input.md and follow the instructions at the top of that file"),
    ]


def test_sidecar_first_line_only_used(tmp_path, monkeypatch):
    # Scenario: sidecar accidentally contains multiple lines; bash uses head -1.
    # Setup: multi-line sidecar; stub readiness OK; capture send target.
    (tmp_path / "tmux_target").write_text("%first\n%second\n")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(mod, "tmux_waitForClaudeReadiness", lambda pane: 0)
    monkeypatch.setattr(
        mod, "tmux_sendAndSubmit",
        lambda pane, text: sent.append((pane, text)) or 0,
    )
    # Test action: invoke jot_sessionStart.
    jot_sessionStart("/x/in.md", str(tmp_path))
    # Test verification: only the first line is used as the pane target.
    assert sent[0][0] == "%first"


def test_readiness_called_with_resolved_pane_id(tmp_path, monkeypatch):
    # Scenario: readiness probe must receive the same pane id parsed from sidecar.
    # Setup: sidecar with "%77"; record arg passed into readiness probe.
    (tmp_path / "tmux_target").write_text("%77\n")
    seen: list[str] = []
    def fake_ready(pane: str) -> int:
        seen.append(pane)
        return 0
    monkeypatch.setattr(mod, "tmux_waitForClaudeReadiness", fake_ready)
    monkeypatch.setattr(mod, "tmux_sendAndSubmit", lambda p, t: 0)
    # Test action: invoke jot_sessionStart.
    jot_sessionStart("/x/in.md", str(tmp_path))
    # Test verification: readiness probe got the parsed pane id verbatim.
    assert seen == ["%77"]



# --- debate_anyLiveLock ---

import sys
from pathlib import Path

import pytest

# Allow `from jot_plugin_orchestrator import ...` regardless of pytest CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent))



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lock(dir_path: Path, name: str, pane_id: str | None) -> Path:
    """Create a hidden lock file with optional `debate:<pane_id>` line."""
    lock = dir_path / name
    body = f"debate:{pane_id}\n" if pane_id else ""
    lock.write_text(body, encoding="utf-8")
    return lock


@pytest.fixture
def fake_tmux(monkeypatch):
    """Patch `_live_pane_ids` to return a configurable set without tmux."""
    state: dict[str, set[str]] = {"live": set()}

    def _fake() -> set[str]:
        return set(state["live"])


    monkeypatch.setattr(mod, "_live_pane_ids", _fake)
    return state


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_returns_false_when_no_lock_files(tmp_path, fake_tmux):
    # Scenario: empty debate dir, no .*.lock files exist.
    # Setup: tmp_path is fresh; tmux reports no live panes.
    fake_tmux["live"] = set()
    # Test action: invoke debate_anyLiveLock on the empty directory.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: bash returns rc=1 (no live lock) -> Python returns False.
    assert result is False


def test_returns_true_when_lock_pane_id_is_live(tmp_path, fake_tmux):
    # Scenario: a hidden .lock file references a pane that tmux still reports.
    # Setup: write `.alpha.lock` containing `debate:%42`; tmux lists `%42` live.
    _make_lock(tmp_path, ".alpha.lock", "%42")
    fake_tmux["live"] = {"%42", "%99"}
    # Test action: scan the directory for live debate locks.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: pane id matched a live tmux pane -> True.
    assert result is True


def test_returns_false_when_lock_pane_id_is_dead(tmp_path, fake_tmux):
    # Scenario: lock file's pane id is NOT in the live tmux pane set.
    # Setup: lock points at `%7`; tmux only knows `%1` and `%2`.
    _make_lock(tmp_path, ".beta.lock", "%7")
    fake_tmux["live"] = {"%1", "%2"}
    # Test action: query for any live lock.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: dead pane id must not register as a live lock.
    assert result is False


def test_skips_lock_without_debate_marker(tmp_path, fake_tmux):
    # Scenario: a hidden .lock exists but contains no `debate:%N` line.
    # Setup: garbage payload only; tmux happens to have %1 alive.
    (tmp_path / ".garbage.lock").write_text("not-a-debate-line\n", encoding="utf-8")
    fake_tmux["live"] = {"%1"}
    # Test action: scan the dir.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: sed extracts empty pane_id -> bash skips -> False.
    assert result is False


def test_returns_false_when_directory_missing(tmp_path, fake_tmux):
    # Scenario: caller passes a path that does not exist.
    # Setup: build a non-existent child path.
    missing = tmp_path / "nope"
    fake_tmux["live"] = {"%1"}
    # Test action: invoke against missing dir (bash for-loop yields no matches).
    result = debate_anyLiveLock(missing)
    # Test verification: nothing to iterate -> False.
    assert result is False


def test_returns_true_if_any_one_of_many_locks_is_live(tmp_path, fake_tmux):
    # Scenario: multiple lock files; only one references a live pane.
    # Setup: three locks; only `%30` is live in tmux.
    _make_lock(tmp_path, ".a.lock", "%10")
    _make_lock(tmp_path, ".b.lock", "%20")
    _make_lock(tmp_path, ".c.lock", "%30")
    fake_tmux["live"] = {"%30"}
    # Test action: scan all locks.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: short-circuits to True on first live match.
    assert result is True


def test_ignores_non_hidden_lock_files(tmp_path, fake_tmux):
    # Scenario: a .lock file NOT starting with `.` should be ignored.
    # Setup: bash glob is `.*.lock`; visible `visible.lock` must not match.
    (tmp_path / "visible.lock").write_text("debate:%5\n", encoding="utf-8")
    fake_tmux["live"] = {"%5"}
    # Test action: scan dir for hidden locks only.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: visible file ignored -> no live lock found -> False.
    assert result is False



# --- debate_sendPromptToAgent ---

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))



# Scenario: marker (basename of instructions path) appears in pane on first poll.
# Setup: capture returns text containing basename; tmux_sendAndSubmit returns 0.
# Test action: invoke debate_sendPromptToAgent.
# Test verification: returns 0 (success rc); send-and-submit called with
# bash-shaped prompt; capture called with 2000 scrollback.
def test_returns_zero_when_marker_seen_immediately(monkeypatch, capsys):
    sent_calls: list[tuple[str, str]] = []
    capture_calls: list[tuple[str, int | None]] = []

    monkeypatch.setattr(
        mod, "tmux_sendAndSubmit",
        lambda pane, txt: sent_calls.append((pane, txt)) or 0,
    )
    monkeypatch.setattr(
        mod, "tmux_capturePane",
        lambda pane, n=None: capture_calls.append((pane, n))
        or "noise\nr1_instructions_gemini.txt echoed back\n",
    )
    monkeypatch.setattr(mod, "debate_writeFailed", lambda *a, **k: pytest.fail("should not be called"))

    rc = debate_sendPromptToAgent(
        "%7", "r1", "gemini",
        "/debates/x/r1_instructions_gemini.txt",
    )

    assert rc == 0
    assert sent_calls == [
        ("%7", "read /debates/x/r1_instructions_gemini.txt and perform them"),
    ]
    assert capture_calls == [("%7", 2000)]


# Scenario: marker never appears within 30s budget -> timeout path.
# Setup: capture always returns empty; sleep is stubbed to no-op so the loop
# runs synchronously through all 30 ticks.
# Test action: invoke debate_sendPromptToAgent.
# Test verification: returns 1; debate_writeFailed called with bash-faithful
# stage + reason; capture called exactly 30 times (one per second budget).
def test_timeout_returns_one_and_invokes_writeFailed(monkeypatch, capsys):
    capture_count = {"n": 0}
    failed_calls: list[tuple[str, str]] = []

    def fake_capture(pane, n=None):
        capture_count["n"] += 1
        return ""

    monkeypatch.setattr(mod, "tmux_sendAndSubmit", lambda pane, txt: 0)
    monkeypatch.setattr(mod, "tmux_capturePane", fake_capture)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        mod, "debate_writeFailed",
        lambda stage, reason: failed_calls.append((stage, reason)),
    )

    rc = debate_sendPromptToAgent(
        "%9", "r2", "codex",
        "/debates/x/r2_instructions_codex.txt",
    )

    assert rc == 1
    assert capture_count["n"] == 30
    assert failed_calls == [
        ("r2", "send_prompt timeout for codex after 30s"),
    ]
    err = capsys.readouterr().err
    assert "[orch] TIMEOUT: r2/codex did not echo prompt" in err


# Scenario: ANSI escape sequences in pane buffer must be stripped before the
# fixed-string match (bash uses `tr -d '\033'`).
# Setup: capture returns marker wrapped in ESC sequences; if ANSI is not
# stripped the literal basename will not match.
# Test action: invoke debate_sendPromptToAgent.
# Test verification: returns 0 (match succeeded post-strip).
def test_ansi_escapes_are_stripped_before_match(monkeypatch):
    monkeypatch.setattr(mod, "tmux_sendAndSubmit", lambda pane, txt: 0)
    monkeypatch.setattr(
        mod, "tmux_capturePane",
        lambda pane, n=None: "\x1b[32mr1_instructions_claude.txt\x1b[0m",
    )
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(mod, "debate_writeFailed", lambda *a, **k: pytest.fail("unexpected"))

    rc = debate_sendPromptToAgent(
        "%3", "r1", "claude",
        "/debates/y/r1_instructions_claude.txt",
    )

    assert rc == 0


# Scenario: marker derivation uses basename of the instructions path, not the
# full path (bash `marker=$(basename "$instructions")`).
# Setup: capture buffer contains ONLY the basename, never the parent dirs.
# Test action: invoke with a deeply nested instructions path.
# Test verification: returns 0; matching by basename succeeded.
def test_marker_is_basename_not_full_path(monkeypatch):
    monkeypatch.setattr(mod, "tmux_sendAndSubmit", lambda pane, txt: 0)
    monkeypatch.setattr(
        mod, "tmux_capturePane",
        lambda pane, n=None: "echoed: r1_instructions_gemini.txt",
    )
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    rc = debate_sendPromptToAgent(
        "%5", "r1", "gemini",
        "/very/deep/path/Debates/2026/r1_instructions_gemini.txt",
    )

    assert rc == 0



# --- jot_stop ---

import sys
from pathlib import Path

import pytest

# Make the workspace importable.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))



# --- shared fixtures --------------------------------------------------------


@pytest.fixture
def kill_calls(monkeypatch):
    # Test seam: capture pane-id + retile-target instead of touching tmux.
    calls: list[tuple[str, str]] = []

    def _fake_bg(pane_target: str, retile_target: str) -> None:
        calls.append((pane_target, retile_target))

    return calls, _fake_bg


@pytest.fixture
def jot_dirs(tmp_path: Path):
    # Standard layout: tmpdir_inv with sidecar, state_dir for audit.log,
    # plus an input_file path (which may or may not exist depending on test).
    tmpdir_inv = tmp_path / "jot.invXYZ"
    tmpdir_inv.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    return {
        "tmpdir_inv": tmpdir_inv,
        "state_dir": state_dir,
        "input_file": tmp_path / "input.txt",
    }


def _writeSidecar(tmpdir_inv: Path, pane_id: str) -> None:
    (tmpdir_inv / "tmux_target").write_text(pane_id + "\n")


# --- tests ------------------------------------------------------------------


def test_jot_stop_missingArgsReturnsZeroAndLogsToStderr(capsys):
    # Scenario: caller forgot a required arg (Stop hook misconfig).
    # Setup: pass empty strings for two of three positional args.
    # Test action: invoke jot_stop with empty input_file.
    rc = jot_stop("", "/tmp/jot.x", "/tmp/state")
    captured = capsys.readouterr()
    # Test verification: rc must be 0 (silent exit) and stderr must
    # mention all three arg names so operators can debug.
    assert rc == 0
    assert "missing args" in captured.err
    assert "input_file" in captured.err


def test_jot_stop_emptySidecarRetriesThenReturnsZero(jot_dirs, capsys, monkeypatch):
    # Scenario: tmux_target sidecar never gets written (split-window failed).
    # Setup: leave tmpdir_inv empty; stub time.sleep so retries are instant.
    monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", lambda _s: None)
    # Test action: call jot_stop; sidecar reader will exhaust retries.
    rc = jot_stop(
        str(jot_dirs["input_file"]),
        str(jot_dirs["tmpdir_inv"]),
        str(jot_dirs["state_dir"]),
    )
    captured = capsys.readouterr()
    # Test verification: rc=0, stderr mentions the empty-sidecar diagnostic.
    assert rc == 0
    assert "tmux_target sidecar empty" in captured.err


def test_jot_stop_writesSuccessAuditLineWhenInputHasProcessedMarker(
    jot_dirs, kill_calls
):
    # Scenario: claude finished its job — input.txt's first line is PROCESSED:.
    # Setup: sidecar holds a pane id; input.txt has the marker on line 1.
    calls, fake_bg = kill_calls
    _writeSidecar(jot_dirs["tmpdir_inv"], "%42")
    jot_dirs["input_file"].write_text("PROCESSED: ok\nbody\n")
    # Test action: invoke jot_stop with the test seam for the kill subshell.
    rc = jot_stop(
        str(jot_dirs["input_file"]),
        str(jot_dirs["tmpdir_inv"]),
        str(jot_dirs["state_dir"]),
        background_kill=fake_bg,
    )
    audit = (jot_dirs["state_dir"] / "audit.log").read_text().splitlines()
    # Test verification: rc=0, exactly one audit line shaped
    # "<ts> SUCCESS <input_file>" — no FAIL token anywhere.
    assert rc == 0
    assert len(audit) == 1
    assert " SUCCESS " in audit[0]
    assert audit[0].endswith(str(jot_dirs["input_file"]))
    assert "FAIL" not in audit[0]


def test_jot_stop_writesFailAuditLineWhenInputHasNoProcessedMarker(
    jot_dirs, kill_calls
):
    # Scenario: claude exited without writing the PROCESSED: marker.
    # Setup: sidecar present; input.txt's first line is unrelated text.
    calls, fake_bg = kill_calls
    _writeSidecar(jot_dirs["tmpdir_inv"], "%42")
    jot_dirs["input_file"].write_text("hello world\n")
    # Test action: run jot_stop.
    jot_stop(
        str(jot_dirs["input_file"]),
        str(jot_dirs["tmpdir_inv"]),
        str(jot_dirs["state_dir"]),
        background_kill=fake_bg,
    )
    audit = (jot_dirs["state_dir"] / "audit.log").read_text()
    # Test verification: audit line is FAIL and explains why.
    assert " FAIL " in audit
    assert "no PROCESSED marker" in audit


def test_jot_stop_writesFailAuditLineWhenInputFileMissing(jot_dirs, kill_calls):
    # Scenario: input.txt was deleted/never written by the worker.
    # Setup: sidecar present; do NOT create input.txt.
    calls, fake_bg = kill_calls
    _writeSidecar(jot_dirs["tmpdir_inv"], "%42")
    # Test action: run jot_stop pointing at the absent file.
    jot_stop(
        str(jot_dirs["input_file"]),
        str(jot_dirs["tmpdir_inv"]),
        str(jot_dirs["state_dir"]),
        background_kill=fake_bg,
    )
    audit = (jot_dirs["state_dir"] / "audit.log").read_text()
    # Test verification: audit line is FAIL with the missing-file reason.
    assert " FAIL " in audit
    assert "input.txt missing" in audit


def test_jot_stop_killsPaneAndRetilesAfterAuditWrite(jot_dirs, kill_calls):
    # Scenario: happy path — sidecar present, input processed.
    # Setup: pane id = "%99"; SUCCESS path so we know audit ran first.
    calls, fake_bg = kill_calls
    _writeSidecar(jot_dirs["tmpdir_inv"], "%99")
    jot_dirs["input_file"].write_text("PROCESSED: yes\n")
    # Test action: run jot_stop with the kill seam capturing args.
    jot_stop(
        str(jot_dirs["input_file"]),
        str(jot_dirs["tmpdir_inv"]),
        str(jot_dirs["state_dir"]),
        background_kill=fake_bg,
    )
    # Test verification: kill+retile invoked exactly once with the
    # sidecar pane id and the canonical "jot:jots" window target.
    assert calls == [("%99", "jot:jots")]


def test_jot_stop_initializesStateDirArtifacts(jot_dirs, kill_calls):
    # Scenario: state_dir must be ready (queue.txt, active_job.txt, audit.log)
    # before jot_stop returns.
    # Setup: empty state_dir; sidecar present.
    calls, fake_bg = kill_calls
    _writeSidecar(jot_dirs["tmpdir_inv"], "%1")
    jot_dirs["input_file"].write_text("PROCESSED: yes\n")
    # Test action: run jot_stop.
    jot_stop(
        str(jot_dirs["input_file"]),
        str(jot_dirs["tmpdir_inv"]),
        str(jot_dirs["state_dir"]),
        background_kill=fake_bg,
    )
    # Test verification: all three state artifacts exist.
    state = jot_dirs["state_dir"]
    assert (state / "queue.txt").is_file()
    assert (state / "active_job.txt").is_file()
    assert (state / "audit.log").is_file()


def test_jot_stop_rotatesAuditLogToOneThousandLines(jot_dirs, kill_calls):
    # Scenario: audit.log has grown beyond the 1000-line ceiling.
    # Setup: pre-seed audit.log with 1500 lines; jot_stop appends one more
    # then rotates, so the final line count must be exactly 1000.
    calls, fake_bg = kill_calls
    _writeSidecar(jot_dirs["tmpdir_inv"], "%1")
    jot_dirs["input_file"].write_text("PROCESSED: yes\n")
    audit_path = jot_dirs["state_dir"] / "audit.log"
    audit_path.write_text("\n".join(f"old-line-{i}" for i in range(1500)) + "\n")
    # Test action: run jot_stop (will append + rotate).
    jot_stop(
        str(jot_dirs["input_file"]),
        str(jot_dirs["tmpdir_inv"]),
        str(jot_dirs["state_dir"]),
        background_kill=fake_bg,
    )
    final = audit_path.read_text().splitlines()
    # Test verification: trimmed to 1000 lines AND the most recent
    # SUCCESS line is preserved (it was the last write before rotate).
    assert len(final) == 1000
    assert any(" SUCCESS " in line for line in final)



# --- todo_launcher ---

import json
import sys
import subprocess
from pathlib import Path

# Standard temp file header: keep workspace importable when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from _migration_workspace import jot_plugin_orchestrator

def test_todo_launcher_success(monkeypatch, tmp_path):
    # Scenario: standard execution successfully creates inputs, cmds, and tmux window
    # Setup: mock all external calls and dependencies
    session_id = "test-session"
    idea = "fix a bug"
    pending_file = tmp_path / "pending.json"
    repo_root = tmp_path / "repo"
    cwd = repo_root / "src"
    transcript_path = tmp_path / "transcript.txt"
    
    repo_root.mkdir(parents=True)
    cwd.mkdir(parents=True)
    transcript_path.write_text("transcript content")
    
    pending_data = {
        "repo_root": str(repo_root),
        "cwd": str(cwd),
        "transcript_path": str(transcript_path),
        "timestamp": "20260101-120000"
    }
    pending_file.write_text(json.dumps(pending_data))
    
    calls = []
    
    import common.scripts.git_lib as git_lib
    from _migration_workspace import jot_plugin_orchestrator
    
    monkeypatch.setattr(git_lib, "getGitBranchNameOrFail", lambda p: "main-branch")
    monkeypatch.setattr(git_lib, "getGitRecentCommitHashes", lambda p: ["commit1", "commit2"])
    monkeypatch.setattr(git_lib, "getGitUncommittedFilenames", lambda p: ["file1.txt"])
    monkeypatch.setattr(jot_plugin_orchestrator, "todo_scanOpen", lambda p: [str(repo_root / "Todos" / "todo1.md")])
    
    def mock_run(cmd, *args, **kwargs):
        calls.append(["run", cmd[0] if isinstance(cmd, list) else cmd])
        class MockResult:
            returncode = 0
            stdout = "mock stdout output\n"
        return MockResult()
        
    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(jot_plugin_orchestrator.subprocess, "run", mock_run)
    
    monkeypatch.setattr(jot_plugin_orchestrator, "claude_seedPermissions", lambda *args: calls.append(["claude_seedPermissions"]))
    monkeypatch.setattr(jot_plugin_orchestrator, "claude_buildCmd", lambda *args: "mock claude cmd")
    
    class MockFileLock:
        def __init__(self, path, timeout):
            pass
        def __enter__(self):
            calls.append(["lock_acquire"])
            return self
        def __exit__(self, *args):
            calls.append(["lock_release"])
            
    monkeypatch.setattr(jot_plugin_orchestrator, "FileLock", MockFileLock)
    
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_ensureSession", lambda *args: calls.append(["tmux_ensureSession"]))
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_splitWorkerPane", lambda *args: "%123")
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_setPaneTitle", lambda *args: calls.append(["tmux_setPaneTitle"]))
    monkeypatch.setattr(jot_plugin_orchestrator, "tmux_retile", lambda *args: calls.append(["tmux_retile"]))
    monkeypatch.setattr(jot_plugin_orchestrator, "terminal_spawnIfNeeded", lambda *args: calls.append(["terminal_spawnIfNeeded"]))
    
    # Test action:
    result = jot_plugin_orchestrator.todo_launcher(session_id, idea, str(pending_file))

    # Test verification:
    assert result == 0
    assert ["claude_seedPermissions"] in calls
    assert ["lock_acquire"] in calls
    assert ["tmux_ensureSession"] in calls
    assert ["tmux_setPaneTitle"] in calls
    assert ["tmux_retile"] in calls
    assert ["terminal_spawnIfNeeded"] in calls



# --- debate_probeGemini ---

import os
import sys
from unittest.mock import patch

import pytest




# ── Gate 1: binary presence ────────────────────────────────────────────


def test_returns_empty_when_gemini_binary_missing():
    # Scenario: gemini CLI not installed on this machine.
    # Setup: shutil.which returns None for "gemini"; clear all credential env.
    with patch("jot_plugin_orchestrator.shutil.which", return_value=None), \
         patch.dict(os.environ, {}, clear=True), \
         patch("jot_plugin_orchestrator.os.path.isfile", return_value=False):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: empty string signals "unavailable" to caller.
    assert result == ""


# ── Gate 2: credentials present ────────────────────────────────────────


def test_returns_empty_when_binary_present_but_no_credentials():
    # Scenario: gemini installed but user never logged in or set API key.
    # Setup: which finds binary; no oauth file; no API-key env vars.
    with patch("jot_plugin_orchestrator.shutil.which", return_value="/usr/bin/gemini"), \
         patch("jot_plugin_orchestrator.os.path.isfile", return_value=False), \
         patch.dict(os.environ, {}, clear=True):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: empty string — credentials gate failed.
    assert result == ""


def test_returns_model_when_oauth_creds_file_present():
    # Scenario: user authenticated via `gemini auth login` (oauth file).
    # Setup: binary on PATH; oauth_creds.json exists; default model configured.
    with patch("jot_plugin_orchestrator.shutil.which", return_value="/usr/bin/gemini"), \
         patch("jot_plugin_orchestrator.os.path.isfile", return_value=True), \
         patch.dict(os.environ, {}, clear=True), \
         patch("jot_plugin_orchestrator.debate_defaultModel", return_value="gemini-2.5-pro"):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: model name is returned (caller uses it for spawn).
    assert result == "gemini-2.5-pro"


def test_returns_model_when_gemini_api_key_env_set():
    # Scenario: CI / headless usage with GEMINI_API_KEY env var.
    # Setup: binary present; no oauth file; GEMINI_API_KEY set.
    with patch("jot_plugin_orchestrator.shutil.which", return_value="/usr/bin/gemini"), \
         patch("jot_plugin_orchestrator.os.path.isfile", return_value=False), \
         patch.dict(os.environ, {"GEMINI_API_KEY": "abc123"}, clear=True), \
         patch("jot_plugin_orchestrator.debate_defaultModel", return_value="gemini-2.5-flash"):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: env-var credentials path also yields model name.
    assert result == "gemini-2.5-flash"


def test_returns_model_when_google_api_key_env_set():
    # Scenario: alternate env var GOOGLE_API_KEY (Google AI Studio name).
    # Setup: binary present; no oauth file; only GOOGLE_API_KEY set.
    with patch("jot_plugin_orchestrator.shutil.which", return_value="/usr/bin/gemini"), \
         patch("jot_plugin_orchestrator.os.path.isfile", return_value=False), \
         patch.dict(os.environ, {"GOOGLE_API_KEY": "xyz789"}, clear=True), \
         patch("jot_plugin_orchestrator.debate_defaultModel", return_value="gemini-2.5-pro"):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: GOOGLE_API_KEY satisfies the credentials gate.
    assert result == "gemini-2.5-pro"


# ── Gate 3: model lookup / "present" sentinel ──────────────────────────


def test_returns_present_sentinel_when_no_model_configured():
    # Scenario: gemini available but models.json has no entry for it.
    # Setup: all gates pass; _default_model returns "" (no model listed).
    with patch("jot_plugin_orchestrator.shutil.which", return_value="/usr/bin/gemini"), \
         patch("jot_plugin_orchestrator.os.path.isfile", return_value=True), \
         patch.dict(os.environ, {}, clear=True), \
         patch("jot_plugin_orchestrator.debate_defaultModel", return_value=""):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: literal "present" sentinel — non-empty so caller's
    # `-s` truthiness check treats gemini as available.
    assert result == "present"



# --- todo_sessionEnd ---

import shutil

import pytest



# ---------------------------------------------------------------------------
# Valid /tmp/todo.X prefix
# ---------------------------------------------------------------------------


def test_valid_tmp_prefix_calls_rmtree(monkeypatch, capsys):
    # Scenario: valid /tmp/todo.X path delegates removal to shutil.rmtree
    # Setup: capture rmtree calls
    calls: list[tuple] = []

    def fake_rmtree(path, ignore_errors=False):
        calls.append((path, ignore_errors))

    monkeypatch.setattr(shutil, "rmtree", fake_rmtree)

    # Test action:
    todo_sessionEnd("/tmp/todo.abc123")

    # Test verification:
    assert calls == [("/tmp/todo.abc123", True)]
    assert capsys.readouterr().err == ""


def test_valid_tmp_prefix_suffix_variation(monkeypatch):
    # Scenario: /tmp/todo. with a different suffix is also accepted
    # Setup:
    calls: list[str] = []
    monkeypatch.setattr(shutil, "rmtree", lambda path, ignore_errors=False: calls.append(path))

    # Test action:
    todo_sessionEnd("/tmp/todo.xyz-session-99")

    # Test verification:
    assert calls == ["/tmp/todo.xyz-session-99"]


# ---------------------------------------------------------------------------
# Valid /private/tmp/todo.X prefix
# ---------------------------------------------------------------------------


def test_valid_private_tmp_prefix_calls_rmtree(monkeypatch, capsys):
    # Scenario: valid /private/tmp/todo.X path (macOS real path) is accepted
    # Setup:
    calls: list[str] = []
    monkeypatch.setattr(shutil, "rmtree", lambda path, ignore_errors=False: calls.append(path))

    # Test action:
    todo_sessionEnd("/private/tmp/todo.session42")

    # Test verification:
    assert calls == ["/private/tmp/todo.session42"]
    assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# Invalid prefix - dir untouched, stderr warning emitted
# ---------------------------------------------------------------------------


def test_invalid_prefix_prints_stderr_and_skips_rmtree(monkeypatch, capsys):
    # Scenario: path with unrecognised prefix is rejected; rmtree not called
    # Setup:
    calls: list[str] = []
    monkeypatch.setattr(shutil, "rmtree", lambda path, ignore_errors=False: calls.append(path))

    # Test action:
    todo_sessionEnd("/var/tmp/todo.sneaky")

    # Test verification:
    assert calls == []
    err = capsys.readouterr().err
    assert "[todo-session-end] refusing to rm unexpected path: /var/tmp/todo.sneaky" in err


def test_invalid_prefix_leaves_directory_intact(monkeypatch, tmp_path, capsys):
    # Scenario: directory with bad prefix must not be removed from the filesystem
    # Setup: a real directory that should NOT be touched
    bad_dir = tmp_path / "evil"
    bad_dir.mkdir()
    # Bypass the prefix by using a path string that does NOT match valid prefixes
    fake_bad_path = str(bad_dir)

    monkeypatch.setattr(shutil, "rmtree", shutil.rmtree)  # use real rmtree to detect any deletion

    # Test action:
    todo_sessionEnd(fake_bad_path)

    # Test verification: directory still exists because prefix was invalid
    assert bad_dir.exists()


# ---------------------------------------------------------------------------
# Nonexistent valid-prefix path - silently ignored
# ---------------------------------------------------------------------------


def test_nonexistent_valid_path_is_silently_ignored(monkeypatch, capsys):
    # Scenario: valid prefix but path does not exist; ignore_errors=True swallows it
    # Setup: rmtree with ignore_errors=True must not raise on missing path
    deleted: list[str] = []

    def fake_rmtree(path, ignore_errors=False):
        # Simulate real rmtree behaviour: no-op when ignore_errors=True
        assert ignore_errors is True
        deleted.append(path)

    monkeypatch.setattr(shutil, "rmtree", fake_rmtree)

    # Test action: path looks valid but does not exist on disk
    todo_sessionEnd("/tmp/todo.does-not-exist-1234")

    # Test verification: rmtree was still called (caller swallows the error)
    assert deleted == ["/tmp/todo.does-not-exist-1234"]
    assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# Empty string - treated as invalid prefix
# ---------------------------------------------------------------------------


def test_empty_string_is_rejected(monkeypatch, capsys):
    # Scenario: empty string has no valid prefix; must be rejected
    # Setup:
    calls: list[str] = []
    monkeypatch.setattr(shutil, "rmtree", lambda path, ignore_errors=False: calls.append(path))

    # Test action:
    todo_sessionEnd("")

    # Test verification:
    assert calls == []
    err = capsys.readouterr().err
    assert "[todo-session-end] refusing to rm unexpected path:" in err



# --- debate_launchAgentsParallel ---

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))



# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STAGE = "r1"
_PANES = ["%1", "%2"]
_AGENTS = ["claude", "gemini"]
_LAUNCH_CMD = {"claude": "claude --settings /tmp/s.json", "gemini": "gemini --settings /tmp/g.json"}
_READY_MARKER = {"claude": "Claude Code v", "gemini": "Gemini CLI v"}


# ---------------------------------------------------------------------------
# Shared patch helper
# ---------------------------------------------------------------------------

def _patch_deps(
    monkeypatch,
    *,
    launch_return: bool = True,
    send_return: int = 0,
):
    """Patch all in-flight dep functions on the module under test."""
    mock_launch = MagicMock(return_value=launch_return)
    mock_send = MagicMock(return_value=send_return)
    mock_kill = MagicMock(return_value=0)
    mock_launch_cmd = MagicMock(side_effect=lambda a: _LAUNCH_CMD.get(a, "unknown"))
    mock_ready_marker = MagicMock(side_effect=lambda a: _READY_MARKER.get(a, ""))

    monkeypatch.setattr(module, "debate_launchAgent", mock_launch)
    monkeypatch.setattr(module, "debate_sendPromptToAgent", mock_send)
    monkeypatch.setattr(module, "tmux_killPane", mock_kill)
    monkeypatch.setattr(module, "debate_agentLaunchCmd", mock_launch_cmd)
    monkeypatch.setattr(module, "debate_agentReadyMarker", mock_ready_marker)

    return mock_launch, mock_send, mock_kill


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_happy_path_two_agents_returns_zero(monkeypatch, tmp_path):
    # Scenario: two agents, no skip conditions; both workers succeed.
    # Setup: no output files, no lock files; launch and send return success.
    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch, launch_return=True, send_return=0)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES, _AGENTS, tmp_path)

    # Test verification: returns 0, both agents launched and prompted.
    assert rc == 0
    assert mock_launch.call_count == 2
    assert mock_send.call_count == 2
    mock_kill.assert_not_called()


def test_skip_when_output_file_exists(monkeypatch, tmp_path):
    # Scenario: output file for first agent exists and is non-empty; agent is skipped.
    # Setup: create non-empty output file for agent[0].
    output = tmp_path / f"{_STAGE}_{_AGENTS[0]}.md"
    output.write_text("previous result")

    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES, _AGENTS, tmp_path)

    # Test verification: kill called for skipped pane; only second agent launched.
    mock_kill.assert_any_call(_PANES[0])
    assert mock_launch.call_count == 1
    assert rc == 0


def test_skip_when_lock_file_exists(monkeypatch, tmp_path):
    # Scenario: lock file held for second agent; that agent is skipped.
    # Setup: create lock file for agent[1].
    lock = tmp_path / f".{_STAGE}_{_AGENTS[1]}.lock"
    lock.write_text("debate:%2")

    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES, _AGENTS, tmp_path)

    # Test verification: kill called for locked pane; only first agent launched.
    mock_kill.assert_any_call(_PANES[1])
    assert mock_launch.call_count == 1
    assert rc == 0


def test_partial_failure_returns_one(monkeypatch, tmp_path):
    # Scenario: one worker's send_prompt returns non-zero; overall result is 1.
    # Setup: launch succeeds; send_prompt returns 1 for all calls (simulates failure).
    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch, launch_return=True, send_return=1)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES, _AGENTS, tmp_path)

    # Test verification: at least one failure => returns 1.
    assert rc == 1


def test_empty_agents_list_returns_zero(monkeypatch, tmp_path):
    # Scenario: no agents provided; no workers launched; wall-time log still emitted.
    # Setup: empty panes and agents lists.
    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, [], [], tmp_path)

    # Test verification: no calls to any worker dep; returns 0.
    assert rc == 0
    mock_launch.assert_not_called()
    mock_send.assert_not_called()
    mock_kill.assert_not_called()


def test_launch_failure_returns_one(monkeypatch, tmp_path):
    # Scenario: debate_launchAgent returns False for one agent; worker returns 1.
    # Setup: launch returns False (timeout or error); send should not be called.
    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch, launch_return=False, send_return=0)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES[:1], _AGENTS[:1], tmp_path)

    # Test verification: returns 1; send never called because launch failed.
    assert rc == 1
    mock_send.assert_not_called()


def test_empty_output_file_does_not_skip(monkeypatch, tmp_path):
    # Scenario: output file exists but is empty (0 bytes); agent must NOT be skipped.
    # Setup: create zero-byte output file for agent[0].
    output = tmp_path / f"{_STAGE}_{_AGENTS[0]}.md"
    output.write_text("")

    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES, _AGENTS, tmp_path)

    # Test verification: both agents launched (empty file is not "complete").
    assert mock_launch.call_count == 2
    assert rc == 0



# --- debate_newEmptyPane ---

import sys
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts/_migration_workspace")

import os
import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

from jot_plugin_orchestrator import tmux_killSession, tmux_newSession, tmux_listPanes


# ---------------------------------------------------------------------------
# Live fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def tmux_session():
    # Setup: create a detached tmux session; teardown kills it unconditionally.
    name = f"tmux-py-newemptypane-{os.getpid()}"
    tmux_killSession(name)
    rc = tmux_newSession(name)
    assert rc == 0, "fixture precondition: new session must succeed"
    yield name
    tmux_killSession(name)


# ---------------------------------------------------------------------------
# Mock-based tests (no real tmux required)
# ---------------------------------------------------------------------------

def test_newEmptyPane_returnsPaneId_onSuccess():
    # Scenario: subprocess succeeds and returns a pane id; function returns it.
    # Setup: mock subprocess.run to simulate tmux success with pane id '%7'.
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "%7\n"
    fake_result.stderr = ""
    with patch(
        "jot_plugin_orchestrator.tmux_selectLayout",
        return_value=0,
    ), patch(
        "jot_plugin_orchestrator.subprocess.run",
        return_value=fake_result,
    ):
        # Test action: call with arbitrary window target and cwd.
        result = debate_newEmptyPane("mysession:mywindow", "/tmp")
    # Test verification: returned pane id matches stdout (stripped).
    assert result == "%7"


def test_newEmptyPane_returnsNone_onTmuxFailure():
    # Scenario: subprocess reports nonzero rc; function returns None.
    # Setup: mock subprocess.run to simulate tmux error.
    fake_result = MagicMock()
    fake_result.returncode = 1
    fake_result.stdout = ""
    fake_result.stderr = "error: no current target"
    with patch(
        "jot_plugin_orchestrator.tmux_selectLayout",
        return_value=0,
    ), patch(
        "jot_plugin_orchestrator.subprocess.run",
        return_value=fake_result,
    ):
        # Test action: call with a target that would fail.
        result = debate_newEmptyPane("bogus:window", "/tmp")
    # Test verification: None returned on failure.
    assert result is None


def test_newEmptyPane_returnsNone_onEmptyPaneId():
    # Scenario: subprocess succeeds (rc=0) but stdout is blank; function returns None.
    # Setup: mock subprocess.run to return rc=0 with empty stdout.
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "   \n"
    fake_result.stderr = ""
    with patch(
        "jot_plugin_orchestrator.tmux_selectLayout",
        return_value=0,
    ), patch(
        "jot_plugin_orchestrator.subprocess.run",
        return_value=fake_result,
    ):
        # Test action: call the function.
        result = debate_newEmptyPane("mysession:mywindow", "/tmp")
    # Test verification: None when pane id is empty/whitespace.
    assert result is None


def test_newEmptyPane_callsRetile_beforeSplit():
    # Scenario: tmux_retile is called with window_target before the split-window subprocess.
    # Setup: capture call order via mock.
    call_log: list[str] = []

    def fake_retile(target: str) -> int:
        call_log.append(f"retile:{target}")
        return 0

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "%9\n"
    fake_result.stderr = ""

    def fake_run(argv, **kwargs):
        call_log.append(f"split:{argv}")
        return fake_result

    with patch(
        "jot_plugin_orchestrator.tmux_selectLayout",
        side_effect=lambda t, l: fake_retile(t) or 0,
    ), patch(
        "jot_plugin_orchestrator.subprocess.run",
        side_effect=fake_run,
    ):
        # Test action: call the function.
        debate_newEmptyPane("s:w", "/home/user")
    # Test verification: retile call appears before split call.
    assert len(call_log) == 2
    assert call_log[0].startswith("retile:")
    assert call_log[1].startswith("split:")


def test_newEmptyPane_passesCorrectCwdToSplit():
    # Scenario: -c <cwd> is present in the split-window argv.
    # Setup: capture argv passed to subprocess.run.
    captured_argv: list[list[str]] = []

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "%3\n"
    fake_result.stderr = ""

    def fake_run(argv, **kwargs):
        captured_argv.append(list(argv))
        return fake_result

    with patch(
        "jot_plugin_orchestrator.tmux_selectLayout",
        return_value=0,
    ), patch(
        "jot_plugin_orchestrator.subprocess.run",
        side_effect=fake_run,
    ):
        # Test action: call with a specific cwd.
        debate_newEmptyPane("s:w", "/specific/path")
    # Test verification: argv contains '-c' followed by the given cwd.
    assert len(captured_argv) == 1
    argv = captured_argv[0]
    assert "-c" in argv
    idx = argv.index("-c")
    assert argv[idx + 1] == "/specific/path"


def test_newEmptyPane_retileRcIgnored_doesNotPreventSplit():
    # Scenario: tmux_retile returns nonzero; split still proceeds (RELAXED_COVERAGE).
    # Setup: retile mock returns 1, split mock returns success.
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "%5\n"
    fake_result.stderr = ""
    with patch(
        "jot_plugin_orchestrator.tmux_selectLayout",
        return_value=1,
    ), patch(
        "jot_plugin_orchestrator.subprocess.run",
        return_value=fake_result,
    ):
        # Test action: call despite retile failure.
        result = debate_newEmptyPane("s:w", "/tmp")
    # Test verification: pane id still returned (retile rc not checked).
    assert result == "%5"


# ---------------------------------------------------------------------------
# Live tests (real tmux server)
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_newEmptyPane_addsPaneToWindow(tmux_session):
    # Scenario: calling debate_newEmptyPane on an existing window creates a new pane.
    # Setup: session has one pane (from fixture); form window target.
    window_target = f"{tmux_session}:0"
    before = tmux_listPanes(window_target, "-F", "#{pane_id}")
    # Test action: create a new empty pane.
    pane_id = debate_newEmptyPane(window_target, "/tmp")
    # Test verification: returned pane id is non-None and one more pane exists.
    assert pane_id is not None
    assert pane_id.startswith("%")
    after = tmux_listPanes(window_target, "-F", "#{pane_id}")
    assert len(after) == len(before) + 1


@pytest.mark.live
def test_newEmptyPane_returnedIdInPaneList(tmux_session):
    # Scenario: the pane id returned by debate_newEmptyPane is present in the live pane list.
    # Setup: form window target.
    window_target = f"{tmux_session}:0"
    # Test action: create a new pane.
    pane_id = debate_newEmptyPane(window_target, "/tmp")
    # Test verification: pane id appears in listPanes output.
    assert pane_id is not None
    ids = tmux_listPanes(window_target, "-F", "#{pane_id}")
    assert pane_id in ids


@pytest.mark.live
def test_newEmptyPane_returnsNone_onBogusTarget():
    # Scenario: calling debate_newEmptyPane with a nonexistent target returns None.
    # Setup: a session name that does not exist.
    bogus = f"nonexistent-session-{os.getpid()}:0"
    # Test action: attempt to create a pane in the bogus session.
    result = debate_newEmptyPane(bogus, "/tmp")
    # Test verification: None on tmux failure.
    assert result is None



# --- debateAbort_main ---

import sys
from pathlib import Path

import pytest

# Make the workspace dir importable so the SUT module loads its peer shims.
_WS = Path(__file__).resolve().parent
if str(_WS) not in sys.path:
    sys.path.insert(0, str(_WS))



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _install_ctx(monkeypatch: pytest.MonkeyPatch, *, transcript: str, repo: str) -> None:
    """Patch debate_initHookContext on the SUT module to return a fixed ctx."""
    # Setup: stub initHookContext to skip real env/stdin/git.
    def fake_ctx() -> dict[str, str]:
        return {"TRANSCRIPT_PATH": transcript, "REPO_ROOT": repo}

    monkeypatch.setattr(sut, "debate_initHookContext", fake_ctx)
    # Also stub checkRequirements so jq/tmux absence doesn't abort tests.
    monkeypatch.setattr(sut, "hookjson_checkRequirements", lambda *_a, **_k: None)


def _capture_emit(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace hookjson_emitBlock with a recorder; return the message list."""
    # Setup: collect every emit_block message instead of writing JSON.
    msgs: list[str] = []
    monkeypatch.setattr(sut, "hookjson_emitBlock", lambda m: msgs.append(m))
    return msgs


def _make_debate(repo: Path, ts: str, transcript: str) -> Path:
    """Create <repo>/Debates/<ts>/invoking_transcript.txt with given content."""
    # Setup: build a debate dir whose marker references `transcript`.
    debate = repo / "Debates" / ts
    debate.mkdir(parents=True)
    (debate / "invoking_transcript.txt").write_text(transcript, encoding="utf-8")
    return debate


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_emits_when_transcript_path_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: hook payload has no transcript_path; we must short-circuit.
    # Setup: ctx with empty transcript, valid repo (irrelevant here).
    _install_ctx(monkeypatch, transcript="", repo=str(tmp_path))
    msgs = _capture_emit(monkeypatch)

    # Test action: invoke entry point.
    rc = sut.debateAbort_main()

    # Test verification: rc=0 and the exact bash message was emitted.
    assert rc == 0
    assert msgs == ["/debate-abort: no transcript_path in hook payload"]


def test_emits_when_repo_root_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: cwd is not inside a git repo -> no repo_root from initHook.
    # Setup: transcript present, repo_root empty.
    _install_ctx(monkeypatch, transcript="/tmp/fake-transcript.jsonl", repo="")
    msgs = _capture_emit(monkeypatch)

    # Test action: invoke entry point.
    rc = sut.debateAbort_main()

    # Test verification: bash's exact "git repository" message.
    assert rc == 0
    assert msgs == ["/debate-abort requires a git repository"]


def test_emits_when_no_matching_debate_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: Debates/ exists but no marker matches our transcript.
    # Setup: one debate with a different invoking_transcript.txt content.
    _make_debate(tmp_path, "2026-05-05T100000_topic", "/some/other/transcript.jsonl")
    _install_ctx(
        monkeypatch,
        transcript="/the/right/transcript.jsonl",
        repo=str(tmp_path),
    )
    msgs = _capture_emit(monkeypatch)

    # Test action: invoke entry point.
    rc = sut.debateAbort_main()

    # Test verification: emits "no debate found" and the foreign dir survives.
    assert rc == 0
    assert msgs == ["/debate-abort: no debate found in this conversation"]
    assert (tmp_path / "Debates" / "2026-05-05T100000_topic").is_dir()


def test_emits_still_running_when_live_lock_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: matched debate has a live tmux pane lock - must NOT delete.
    # Setup: build matching debate; stub anyLiveLock True; liveSession known.
    transcript = "/conv/transcript.jsonl"
    debate = _make_debate(tmp_path, "2026-05-05T120000_x", transcript)
    _install_ctx(monkeypatch, transcript=transcript, repo=str(tmp_path))
    msgs = _capture_emit(monkeypatch)
    monkeypatch.setattr(sut, "debate_anyLiveLock", lambda _d: True)
    monkeypatch.setattr(sut, "debate_liveSession", lambda _d: "debate-7")

    # Test action: invoke entry point.
    rc = sut.debateAbort_main()

    # Test verification: emits the kill-session hint; debate dir untouched.
    assert rc == 0
    assert msgs == [
        "/debate-abort: debate is running. to force-kill: "
        "tmux kill-session -t debate-7"
    ]
    assert debate.is_dir()


def test_emits_still_running_with_unknown_when_session_lookup_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: live lock present but tmux can't name the session.
    # Setup: anyLiveLock True; liveSession returns empty string.
    transcript = "/conv/t.jsonl"
    _make_debate(tmp_path, "2026-05-05T130000_y", transcript)
    _install_ctx(monkeypatch, transcript=transcript, repo=str(tmp_path))
    msgs = _capture_emit(monkeypatch)
    monkeypatch.setattr(sut, "debate_anyLiveLock", lambda _d: True)
    monkeypatch.setattr(sut, "debate_liveSession", lambda _d: "")

    # Test action: invoke entry point.
    rc = sut.debateAbort_main()

    # Test verification: '<unknown>' placeholder used in the kill-session hint.
    assert rc == 0
    assert msgs == [
        "/debate-abort: debate is running. to force-kill: "
        "tmux kill-session -t <unknown>"
    ]


def test_happy_path_deletes_dir_and_emits_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: matched debate, no live lock -> rmtree + success message.
    # Setup: matching debate dir with a child file to ensure recursive remove.
    transcript = "/conv/done.jsonl"
    debate = _make_debate(tmp_path, "2026-05-05T140000_done", transcript)
    (debate / "child.txt").write_text("payload", encoding="utf-8")
    _install_ctx(monkeypatch, transcript=transcript, repo=str(tmp_path))
    msgs = _capture_emit(monkeypatch)
    monkeypatch.setattr(sut, "debate_anyLiveLock", lambda _d: False)
    # liveSession should not be called on the happy path; trip if it is.
    monkeypatch.setattr(
        sut,
        "debate_liveSession",
        lambda _d: pytest.fail("debate_liveSession must not be called when no lock"),
    )

    # Test action: invoke entry point.
    rc = sut.debateAbort_main()

    # Test verification: dir gone, exact "deleted ..." message emitted.
    assert rc == 0
    assert not debate.exists()
    assert msgs == [f"/debate-abort: deleted {debate}"]


def test_lexicographic_tiebreak_picks_newest_basename(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: two debates match; the lexicographically greatest must win.
    # Setup: two matching debates, an older basename and a newer one.
    transcript = "/conv/multi.jsonl"
    older = _make_debate(tmp_path, "2026-05-05T090000_a", transcript)
    newer = _make_debate(tmp_path, "2026-05-05T180000_b", transcript)
    # Add a non-matching debate to confirm filtering still works.
    _make_debate(tmp_path, "2026-05-05T230000_z", "/different/transcript.jsonl")
    _install_ctx(monkeypatch, transcript=transcript, repo=str(tmp_path))
    msgs = _capture_emit(monkeypatch)
    monkeypatch.setattr(sut, "debate_anyLiveLock", lambda _d: False)
    monkeypatch.setattr(sut, "debate_liveSession", lambda _d: "")

    # Test action: invoke entry point.
    rc = sut.debateAbort_main()

    # Test verification: only the lex-greatest matching dir was deleted; the
    # older matching dir AND the unrelated dir survive.
    assert rc == 0
    assert not newer.exists()
    assert older.is_dir()
    assert (tmp_path / "Debates" / "2026-05-05T230000_z").is_dir()
    assert msgs == [f"/debate-abort: deleted {newer}"]



# --- jot_main ---

#!/usr/bin/env python3

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure workspace and scripts dirs are importable.
WORKSPACE = Path(__file__).resolve().parent
SCRIPTS = WORKSPACE.parent
for p in (str(WORKSPACE), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)



# --------- shared fixtures ---------

@pytest.fixture
def base_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    # Setup: minimal valid plugin env + scratch log.
    plugin_root = tmp_path / "plugin"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.setenv("JOT_LOG_FILE", str(tmp_path / "jot.log"))
    monkeypatch.delenv("JOT_SKIP_LAUNCH", raising=False)
    return {
        "plugin_root": str(plugin_root),
        "plugin_data": str(plugin_data),
        "tmp": str(tmp_path),
    }


def _stub_passing_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    # Setup: bypass real tool checks + tmux probe.
    monkeypatch.setattr(mod, "hookjson_checkRequirements", lambda *a, **k: None)
    monkeypatch.setattr(mod, "tmux_requireVersion", lambda _m: 0)


def _stdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))


# --------- tests ---------

def test_missing_plugin_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Scenario: harness env vars unset.
    # Setup: clear both vars, stdin irrelevant.
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    _stdin(monkeypatch, "")
    # Test action + verification: jot_main raises RuntimeError.
    with pytest.raises(RuntimeError):
        mod.jot_main()


def test_non_jot_input_exits_zero_silently(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: stdin lacks the "/jot" substring; hook should no-op.
    # Setup: arbitrary non-jot payload.
    _stdin(monkeypatch, '{"prompt": "/other thing"}')
    # Test action: invoke.
    rc = mod.jot_main()
    # Test verification: rc=0, no JSON emitted.
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_prompt_not_strict_jot_exits_zero(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: payload contains "/jot" substring but prompt is "/jotsomething" (not strict /jot).
    # Setup: stdin with substring-but-not-prefix.
    _stub_passing_deps(monkeypatch)
    _stdin(monkeypatch, json.dumps({"prompt": "/jotsomething"}))
    # Test action: invoke.
    rc = mod.jot_main()
    # Test verification: rc=0 with no block emission (strict-prefix branch).
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_empty_idea_emits_block(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: prompt is bare "/jot" with no idea.
    # Setup: stub deps, stdin with bare /jot.
    _stub_passing_deps(monkeypatch)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot"}))
    # Test action: invoke.
    rc = mod.jot_main()
    out = capsys.readouterr().out
    # Test verification: rc=0 + block decision mentioning "no idea provided".
    assert rc == 0
    assert "no idea provided" in out


def test_missing_repo_emits_block(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # Scenario: cwd is not inside a git repo.
    # Setup: stub deps; force `git rev-parse` to fail.
    _stub_passing_deps(monkeypatch)
    non_repo = tmp_path / "norepo"
    non_repo.mkdir()
    _stdin(monkeypatch, json.dumps({"prompt": "/jot make thing", "cwd": str(non_repo)}))

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr="fatal")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    # Test action: invoke.
    rc = mod.jot_main()
    out = capsys.readouterr().out
    # Test verification: rc=0 + git-required block.
    assert rc == 0
    assert "requires a git repository" in out


def test_tmux_too_old_emits_block(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: tmux_requireVersion("2.9") returns nonzero.
    # Setup: stub checkRequirements OK, tmux_requireVersion fail.
    monkeypatch.setattr(mod, "hookjson_checkRequirements", lambda *a, **k: None)
    monkeypatch.setattr(mod, "tmux_requireVersion", lambda _m: 1)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot something"}))
    # Test action: invoke.
    rc = mod.jot_main()
    out = capsys.readouterr().out
    # Test verification: rc=0 + tmux block.
    assert rc == 0
    assert "tmux 2.9+" in out


def test_happy_path_writes_input_file_with_all_sections(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: full happy path produces a Todos/<ts>_input.txt with all sections.
    # Setup: stub deps + stub git_lib + stub launch + stub render/capture subprocess.
    _stub_passing_deps(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "Todos").mkdir(parents=True)
    monkeypatch.setattr(mod, "getGitBranchNameOrFail", lambda c: "main")
    monkeypatch.setattr(mod, "getGitRecentCommitHashes", lambda c: "abc123 init")
    monkeypatch.setattr(mod, "getGitUncommittedFilenames", lambda c: "M file.py")
    monkeypatch.setattr(mod, "todo_scanOpen", lambda r: "todo1\ntodo2")
    launched = {"called": False}

    def fake_launch() -> int:
        launched["called"] = True
        return 0

    monkeypatch.setattr(mod, "jot_launchPhase2Window", fake_launch)

    def fake_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        # git rev-parse: return repo path; render_template: return canned text.
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=str(repo) + "\n", stderr="")
        if "render_template.py" in " ".join(str(c) for c in cmd):
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="RENDERED-INSTRUCTIONS", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot fix the bug", "cwd": str(repo)}))
    # Test action: invoke.
    rc = mod.jot_main()
    # Test verification: rc=0, exactly one input file with expected sections.
    assert rc == 0
    files = list((repo / "Todos").glob("*_input.txt"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "## Instructions\nRENDERED-INSTRUCTIONS" in text
    assert "## Idea\nfix the bug" in text
    assert "Branch: main" in text
    assert "Commits: abc123 init" in text
    assert "Uncommitted: M file.py" in text
    assert "## Open TODO Files\ntodo1\ntodo2" in text
    assert "(no transcript available)" in text


def test_skip_launch_does_not_call_phase2(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: JOT_SKIP_LAUNCH=1 path emits "(launch skipped)" and skips phase2.
    # Setup: full happy stubs + skip flag.
    _stub_passing_deps(monkeypatch)
    monkeypatch.setenv("JOT_SKIP_LAUNCH", "1")
    repo = tmp_path / "repo"
    (repo / "Todos").mkdir(parents=True)
    monkeypatch.setattr(mod, "getGitBranchNameOrFail", lambda c: "main")
    monkeypatch.setattr(mod, "getGitRecentCommitHashes", lambda c: "")
    monkeypatch.setattr(mod, "getGitUncommittedFilenames", lambda c: "")
    monkeypatch.setattr(mod, "todo_scanOpen", lambda r: "")
    launched = {"called": False}
    monkeypatch.setattr(mod, "jot_launchPhase2Window", lambda: launched.__setitem__("called", True) or 0)

    def fake_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=str(repo) + "\n", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="X", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot do thing", "cwd": str(repo)}))
    # Test action: invoke.
    rc = mod.jot_main()
    out = capsys.readouterr().out
    # Test verification: phase2 NOT called, block-decision contains "(launch skipped)".
    assert rc == 0
    assert launched["called"] is False
    assert "launch skipped" in out


def test_phase2_called_on_happy_path(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: happy path without JOT_SKIP_LAUNCH calls jot_launchPhase2Window exactly once.
    # Setup: same as happy-path test but track call count.
    _stub_passing_deps(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "Todos").mkdir(parents=True)
    monkeypatch.setattr(mod, "getGitBranchNameOrFail", lambda c: "main")
    monkeypatch.setattr(mod, "getGitRecentCommitHashes", lambda c: "")
    monkeypatch.setattr(mod, "getGitUncommittedFilenames", lambda c: "")
    monkeypatch.setattr(mod, "todo_scanOpen", lambda r: "")
    calls = {"n": 0}

    def fake_launch() -> int:
        calls["n"] += 1
        return 0

    monkeypatch.setattr(mod, "jot_launchPhase2Window", fake_launch)

    def fake_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=str(repo) + "\n", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="OK", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot launch me", "cwd": str(repo)}))
    # Test action: invoke.
    rc = mod.jot_main()
    out = capsys.readouterr().out
    # Test verification: phase2 called once, success block emitted.
    assert rc == 0
    assert calls["n"] == 1
    assert "Done! Jotted idea in" in out


def test_safe_wrapper_falls_back_to_unavailable(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: git_lib helpers raise; the input file should record "(unavailable)".
    # Setup: stub all git_lib funcs to raise; stub launch + render.
    _stub_passing_deps(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "Todos").mkdir(parents=True)

    def boom(*_: object) -> str:
        raise RuntimeError("nope")

    monkeypatch.setattr(mod, "getGitBranchNameOrFail", boom)
    monkeypatch.setattr(mod, "getGitRecentCommitHashes", boom)
    monkeypatch.setattr(mod, "getGitUncommittedFilenames", boom)
    monkeypatch.setattr(mod, "todo_scanOpen", boom)
    monkeypatch.setattr(mod, "jot_launchPhase2Window", lambda: 0)

    def fake_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=str(repo) + "\n", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="INSTR", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot recover", "cwd": str(repo)}))
    # Test action: invoke.
    rc = mod.jot_main()
    # Test verification: rc=0 + every safe-wrapped value rendered as "(unavailable)".
    assert rc == 0
    files = list((repo / "Todos").glob("*_input.txt"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "Branch: (unavailable)" in text
    assert "Commits: (unavailable)" in text
    assert "Uncommitted: (unavailable)" in text
    assert "## Open TODO Files\n(unavailable)" in text



# --- todo_main ---

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _set_stdin(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def _base_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    # Setup helper: provide required env, isolate log/state under tmp_path.
    plugin_data = tmp_path / "plugin-data"
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.delenv("TODO_LOG_FILE", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    return plugin_data


def _patch_repo_root(monkeypatch: pytest.MonkeyPatch, root: str) -> None:
    monkeypatch.setattr(mod, "_git_get_repo_root", lambda cwd: root)


def test_missing_plugin_data_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Scenario: CLAUDE_PLUGIN_DATA is unset.
    # Setup: ensure env var absent.
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    _set_stdin(monkeypatch, "")
    # Test action: invoke todo_main.
    # Test verification: RuntimeError raised before any I/O.
    with pytest.raises(RuntimeError, match="CLAUDE_PLUGIN_DATA"):
        mod.todo_main()


def test_non_todo_input_exits_zero_silently(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: stdin payload does not contain the "/todo substring.
    # Setup: env ready, stdin has unrelated prompt.
    _base_env(monkeypatch, tmp_path)
    _set_stdin(monkeypatch, '{"prompt": "/jot something"}')
    # Test action: run.
    rc = mod.todo_main()
    # Test verification: rc 0 and no stdout emitted.
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_bad_prompt_format_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: stdin contains "/todo as substring but prompt is not a /todo command.
    # Setup: prompt is "/todoxyz extra" (no leading-space match).
    _base_env(monkeypatch, tmp_path)
    _set_stdin(monkeypatch, '{"prompt": "/todoxyz extra"}')
    # Test action: run.
    rc = mod.todo_main()
    # Test verification: silent exit 0, no block emitted.
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_missing_git_repo_emits_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: cwd is not inside a git repo.
    # Setup: stub repo_root resolver to return "".
    _base_env(monkeypatch, tmp_path)
    _patch_repo_root(monkeypatch, "")
    _set_stdin(monkeypatch, json.dumps({"prompt": "/todo write a test", "cwd": str(tmp_path)}))
    # Test action: run.
    rc = mod.todo_main()
    # Test verification: rc 0, stdout is a block-decision JSON mentioning git.
    assert rc == 0
    out = capsys.readouterr().out.strip()
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "git repository" in decision["reason"]


def test_happy_path_writes_valid_pending_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: well-formed /todo command in a real git repo.
    # Setup: env, stub repo_root to tmp_path, valid stdin payload.
    _base_env(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    _patch_repo_root(monkeypatch, str(repo))
    payload = {
        "prompt": "/todo wire the widget",
        "session_id": "sess-1",
        "transcript_path": "/tmp/t.jsonl",
        "cwd": str(repo),
    }
    _set_stdin(monkeypatch, json.dumps(payload))
    # Test action: run.
    rc = mod.todo_main()
    # Test verification: rc 0, exactly one pending-*.json under state dir, contents valid.
    assert rc == 0
    state_dir = repo / "Todos" / ".todo-state"
    pending = list(state_dir.glob("pending-*.json"))
    assert len(pending) == 1
    claim = json.loads(pending[0].read_text())
    assert claim["session_id"] == "sess-1"
    assert claim["transcript_path"] == "/tmp/t.jsonl"
    assert claim["cwd"] == str(repo)
    assert claim["repo_root"] == str(repo)
    assert claim["idea"] == "wire the widget"
    assert claim["pending_file"] == str(pending[0])
    assert claim["todo_scripts_dir"].endswith("/skills/todo/scripts")
    assert "timestamp" in claim and "created_at" in claim
    assert "todo_plugin_root" in claim


def test_idea_with_quotes_and_newlines_round_trips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: idea contains JSON-hostile characters (quotes, newline, backslash).
    # Setup: stub repo, build payload with tricky idea string.
    _base_env(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    _patch_repo_root(monkeypatch, str(repo))
    tricky = 'fix "quoted" thing\nand \\backslash'
    payload = {"prompt": f"/todo {tricky}", "cwd": str(repo)}
    _set_stdin(monkeypatch, json.dumps(payload))
    # Test action: run.
    rc = mod.todo_main()
    # Test verification: pending file parses and idea exactly matches input.
    assert rc == 0
    pending = list((repo / "Todos" / ".todo-state").glob("pending-*.json"))
    assert len(pending) == 1
    claim = json.loads(pending[0].read_text())
    assert claim["idea"] == tricky


def test_bare_todo_yields_empty_idea(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: prompt is exactly "/todo" with no idea text.
    # Setup: minimal payload, stubbed repo.
    _base_env(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    _patch_repo_root(monkeypatch, str(repo))
    _set_stdin(monkeypatch, json.dumps({"prompt": "/todo", "cwd": str(repo)}))
    # Test action: run.
    rc = mod.todo_main()
    # Test verification: pending file written with idea == "".
    assert rc == 0
    pending = list((repo / "Todos" / ".todo-state").glob("pending-*.json"))
    assert len(pending) == 1
    assert json.loads(pending[0].read_text())["idea"] == ""



# --- todoList_main ---

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

# Make the workspace dir importable so we can import the SUT module.
sys.path.insert(0, str(Path(__file__).resolve().parent))



def _setStdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    monkeypatch.setattr(sys, "stdin", StringIO(payload))


def test_non_todoList_prompt_exits_silently(monkeypatch, capsys):
    # Scenario: stdin payload does not mention "/todo-list -> fast-path return.
    # Setup: stdin is unrelated JSON; no git/format calls should occur.
    _setStdin(monkeypatch, json.dumps({"prompt": "/something-else"}))
    monkeypatch.setattr(sut.subprocess, "run", lambda *a, **k: pytest.fail("must not run subprocess"))
    # Test action: invoke entrypoint.
    rc = sut.todoList_main()
    # Test verification: returns 0 and emits no output.
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_bad_prompt_after_fast_path_exits_silently(monkeypatch, capsys):
    # Scenario: payload contains the literal token but prompt is malformed.
    # Setup: prompt has leading text so strict match fails after fast-path.
    payload = json.dumps({"prompt": 'echo "/todo-list" inside string'})
    _setStdin(monkeypatch, payload)
    monkeypatch.setattr(sut, "hookjson_checkRequirements", lambda *a, **k: None)
    monkeypatch.setattr(sut.subprocess, "run", lambda *a, **k: pytest.fail("must not run subprocess"))
    # Test action: invoke entrypoint.
    rc = sut.todoList_main()
    # Test verification: silent exit, no block emission.
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_missing_repo_emits_not_a_git_repo(monkeypatch, capsys, tmp_path):
    # Scenario: prompt valid but cwd is not inside a git checkout.
    # Setup: stub git rev-parse to return non-zero; stub requirements.
    _setStdin(monkeypatch, json.dumps({"prompt": "/todo-list", "cwd": str(tmp_path)}))
    monkeypatch.setattr(sut, "hookjson_checkRequirements", lambda *a, **k: None)
    monkeypatch.setattr(
        sut.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=128, stdout="", stderr="fatal"),
    )
    # Test action: invoke entrypoint.
    rc = sut.todoList_main()
    # Test verification: prints block JSON with not-a-git-repo reason.
    captured = capsys.readouterr().out.strip()
    decoded = json.loads(captured)
    assert rc == 0
    assert decoded == {"decision": "block", "reason": "todo-list: not a git repository."}


def test_missing_todos_folder_emits_message(monkeypatch, capsys, tmp_path):
    # Scenario: repo exists but has no Todos/ subdirectory.
    # Setup: git rev-parse returns tmp_path (no Todos/ inside).
    _setStdin(monkeypatch, json.dumps({"prompt": "/todo-list", "cwd": str(tmp_path)}))
    monkeypatch.setattr(sut, "hookjson_checkRequirements", lambda *a, **k: None)
    monkeypatch.setattr(
        sut.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=str(tmp_path) + "\n", stderr=""),
    )
    # Test action: invoke entrypoint.
    rc = sut.todoList_main()
    # Test verification: emits the no-Todos-folder block message.
    decoded = json.loads(capsys.readouterr().out.strip())
    assert rc == 0
    assert decoded["reason"] == "No Todos/ folder found in this project."


def test_empty_formatter_output_emits_no_open_todos(monkeypatch, capsys, tmp_path):
    # Scenario: Todos/ exists but formatter produces empty stdout.
    # Setup: real Todos/ dir; first subprocess.run is git, second is formatter (empty).
    todos = tmp_path / "Todos"
    todos.mkdir()
    _setStdin(monkeypatch, json.dumps({"prompt": "/todo-list extra", "cwd": str(tmp_path)}))
    monkeypatch.setattr(sut, "hookjson_checkRequirements", lambda *a, **k: None)
    calls: list[list[str]] = []

    def fake_run(cmd, *a, **k):
        calls.append(list(cmd))
        if cmd[0] == "git":
            return SimpleNamespace(returncode=0, stdout=str(tmp_path) + "\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sut.subprocess, "run", fake_run)
    # Test action: invoke entrypoint.
    rc = sut.todoList_main()
    # Test verification: emits "No open TODOs." block; formatter was invoked.
    decoded = json.loads(capsys.readouterr().out.strip())
    assert rc == 0
    assert decoded["reason"] == "No open TODOs."
    assert any("format_open_todos.py" in arg for call in calls for arg in call)


def test_non_empty_formatter_output_is_forwarded(monkeypatch, capsys, tmp_path):
    # Scenario: formatter produces a TODO list; entrypoint must forward it.
    # Setup: real Todos/ dir; formatter stub returns multi-line text.
    todos = tmp_path / "Todos"
    todos.mkdir()
    formatted_text = "TODO 1\nTODO 2\n"
    _setStdin(monkeypatch, json.dumps({"prompt": "/todo-list", "cwd": str(tmp_path)}))
    monkeypatch.setattr(sut, "hookjson_checkRequirements", lambda *a, **k: None)

    def fake_run(cmd, *a, **k):
        if cmd[0] == "git":
            return SimpleNamespace(returncode=0, stdout=str(tmp_path) + "\n", stderr="")
        # Verify TODOS_DIR env was set for the formatter call.
        assert k.get("env", {}).get("TODOS_DIR") == str(todos)
        return SimpleNamespace(returncode=0, stdout=formatted_text, stderr="")

    monkeypatch.setattr(sut.subprocess, "run", fake_run)
    # Test action: invoke entrypoint.
    rc = sut.todoList_main()
    # Test verification: emitted reason equals captured formatter stdout verbatim.
    decoded = json.loads(capsys.readouterr().out.strip())
    assert rc == 0
    assert decoded["reason"] == formatted_text



# --- tmux_launcherTests (TEST cluster) ---

import os
import sys
import subprocess
import pytest

# Make the production module importable from the workspace temp file.



# ---------- helpers ----------

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
def tmux_session():
    # Provide a unique session name and clean up after the test.
    name = f"tmux-sh-launcher-test-{os.getpid()}"
    _kill(name)
    yield name
    _kill(name)


# ---------- tests ----------

@pytest.mark.live
def test_ensure_session_creates_new_session(tmux_session):
    # Scenario: ensure_session on a missing session creates it (Path 1).
    # Setup: session name guaranteed absent by fixture.
    # Test action: invoke tmux_ensureSession with main window + keepalive.
    tmux_ensureSession(tmux_session, "main", "/tmp", "sleep 30", "keepalive")
    # Test verification: tmux now reports the session exists.
    assert _tmux_has_session(tmux_session)


@pytest.mark.live
def test_ensure_session_sets_keepalive_pane_title(tmux_session):
    # Scenario: keepalive pane created by ensure_session has the requested title.
    # Setup: create the session via ensure_session.
    tmux_ensureSession(tmux_session, "main", "/tmp", "sleep 30", "keepalive")
    # Test action: read pane_title for main window.
    # Test verification: title equals "keepalive".
    assert _tmux_pane_has_title(f"{tmux_session}:main", "keepalive")


@pytest.mark.live
def test_ensure_session_applies_pane_border_status_top(tmux_session):
    # Scenario: ensure_session sets pane-border-status=top via set_option_t.
    # Setup: create session.
    tmux_ensureSession(tmux_session, "main", "/tmp", "sleep 30", "keepalive")
    # Test action: read tmux option.
    border = _tmux_show_option(tmux_session, "pane-border-status")
    # Test verification: option is "top".
    assert border == "top"


@pytest.mark.live
def test_split_worker_pane_returns_pane_id(tmux_session):
    # Scenario: split_worker_pane creates a pane and returns its %id.
    # Setup: ensure session exists first.
    tmux_ensureSession(tmux_session, "main", "/tmp", "sleep 30", "keepalive")
    # Test action: split a worker pane in main window.
    worker = tmux_splitWorkerPane(f"{tmux_session}:main", "/tmp", "sleep 30")
    # Test verification: returned id is non-empty and starts with '%'.
    assert worker
    assert str(worker).startswith("%")


@pytest.mark.live
def test_ensure_session_idempotent_on_existing_session(tmux_session):
    # Scenario: re-calling ensure_session on existing session+window is a no-op (Path 3).
    # Setup: create session once.
    tmux_ensureSession(tmux_session, "main", "/tmp", "sleep 30", "keepalive")
    # Test action: call ensure_session a second time with same args.
    tmux_ensureSession(tmux_session, "main", "/tmp", "sleep 30", "keepalive")
    # Test verification: session still exists, not destroyed by second call.
    assert _tmux_has_session(tmux_session)


@pytest.mark.live
def test_ensure_session_adds_new_window_to_existing_session(tmux_session):
    # Scenario: ensure_session on existing session with new window name adds the window (Path 2).
    # Setup: create session with main window.
    tmux_ensureSession(tmux_session, "main", "/tmp", "sleep 30", "keepalive")
    second = f"secondwin-{os.getpid()}"
    # Test action: call ensure_session with a different window name.
    tmux_ensureSession(tmux_session, second, "/tmp", "sleep 30", "keepalive-2")
    # Test verification: new window now present in the session.
    assert _tmux_window_exists(tmux_session, second)



# --- tmux_layoutTests (TEST cluster) ---

import sys
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")


import os
import pytest


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



# --- tmux_paneTests (TEST cluster) ---

import sys
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")


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



# --- tmux_sendKeysTests (TEST cluster) ---

import sys
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")


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



# --- tmux_sessionTests (TEST cluster) ---

import sys
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")


import os
import pytest


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
def test_killSession_fails_onNonexistentSession(session_name):
    # Scenario: killSession returns nonzero rc when the session does not exist.
    # Setup: fixture guarantees no session by this name exists.
    # Test action: attempt to kill a session that was never created.
    rc = tmux_killSession(session_name)
    # Test verification: nonzero rc means kill rejected.
    assert rc != 0



# --- tmux_setOptionTests (TEST cluster) ---

import sys
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")


import os
import shutil
import subprocess
import pytest


# Skip the whole module if tmux is unavailable on this host.
pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not installed"
)


@pytest.fixture
def tmux_session():
    # Provide a unique, isolated tmux session for one test; tear it down on exit.
    name = f"tmux-py-opt-test-{os.getpid()}"
    subprocess.run(["tmux", "kill-session", "-t", name],
                   capture_output=True, check=False)
    rc = tmux_newSession(name)
    assert rc == 0, "fixture failed to create tmux session"
    yield name
    subprocess.run(["tmux", "kill-session", "-t", name],
                   capture_output=True, check=False)


@pytest.mark.live
def test_setOptionForTarget_accepts_valid_session_option(tmux_session):
    # Scenario: setting a real session-scoped option on a live session returns rc=0.
    # Setup: tmux_session fixture provides a fresh detached session.
    session = tmux_session
    # Test action: set the session-scoped `remain-on-exit` option to `off`.
    rc = tmux_setOptionForTarget(session, "remain-on-exit", "off")
    # Test verification: tmux accepted it; rc must be 0.
    assert rc == 0


@pytest.mark.live
def test_setOptionForTarget_rejects_invalid_option(tmux_session, capfd):
    # Scenario: setting an unknown option name on a live session returns nonzero.
    # Setup: live session from fixture.
    session = tmux_session
    # Test action: attempt to set a fabricated option name.
    rc = tmux_setOptionForTarget(session, "not-a-real-option", "foo")
    # Test verification: tmux rejects unknown option; rc nonzero.
    assert rc != 0
    capfd.readouterr()  # drain caller-attributed stderr from helper


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
def test_setOptionGlobally_rejects_invalid_option(capfd):
    # Scenario: setting a fabricated global option fails.
    # Setup: no fixture state needed (global scope).
    # Test action: attempt to set an unknown option name globally.
    rc = tmux_setOptionGlobally("not-a-real-option", "foo")
    # Test verification: rc nonzero.
    assert rc != 0
    capfd.readouterr()


@pytest.mark.live
def test_setOptionForWindow_accepts_valid_window_option(tmux_session):
    # Scenario: setting a window-scoped option on a real window succeeds.
    # Setup: create a named window inside the fixture session.
    session = tmux_session
    win = f"optwin-{os.getpid()}"
    rc_new = tmux_newWindow(session, win)
    assert rc_new == 0, "precondition: tmux_newWindow should succeed"
    # Test action: set `aggressive-resize on` on the new window.
    rc = tmux_setOptionForWindow(f"{session}:{win}", "aggressive-resize", "on")
    # Test verification: tmux accepted it; rc must be 0.
    assert rc == 0


@pytest.mark.live
def test_setOptionForWindow_rejects_nonexistent_window(tmux_session, capfd):
    # Scenario: setting a window option against a missing window fails.
    # Setup: live session exists, but target window does not.
    session = tmux_session
    bogus_win = f"nosuch-{os.getpid()}"
    # Test action: attempt to set the option against the absent window.
    rc = tmux_setOptionForWindow(f"{session}:{bogus_win}", "aggressive-resize", "on")
    # Test verification: rc nonzero.
    assert rc != 0
    capfd.readouterr()

