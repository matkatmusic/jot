from __future__ import annotations

import json

import pytest

from common.scripts.hookjson_lib import (
    hookjson_checkRequirements,
    hookjson_emitBlock,
    hookjson_installHint,
)


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
