"""Pytest suite for jot_plugin_orchestrator.py.

Migrated incrementally from scripts/test_monolith.sh per
plans/it-is-time-to-jolly-blossom.md.

Every test follows ~/Programming/dotfiles/claude/RED_GREEN_TDD.md "How to write
the tests": a `# Scenario:` header naming what's being verified, then plain-
English step comments explaining what each step proves.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from jot_plugin_orchestrator import (
    hookjson_checkRequirements,
    hookjson_emitBlock,
    hookjson_installHint,
    tmux_requireVersion,
    tmux_setOption,
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
