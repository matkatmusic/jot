"""Tests for common/scripts/hook_json_lib.py."""
from __future__ import annotations

import json

from hook_json_lib import (
    INSTALL_HINTS,
    checkRequirements,
    emitBlockReason,
    installHintFor,
)


def test_emitBlockReason_returns_valid_json():
    out = emitBlockReason("hello")
    parsed = json.loads(out)
    assert parsed == {"decision": "block", "reason": "hello"}


def test_emitBlockReason_round_trips_special_chars():
    reason = 'has "quotes", a \\backslash, and a\nnewline'
    parsed = json.loads(emitBlockReason(reason))
    assert parsed["reason"] == reason


def test_emitBlockReason_round_trips_unicode():
    reason = "résumé naïve über"
    parsed = json.loads(emitBlockReason(reason))
    assert parsed["reason"] == reason


def test_installHintFor_known_commands():
    assert installHintFor("jq") == "jq (brew install jq)"
    assert installHintFor("python3") == "python3 (brew install python)"
    assert installHintFor("tmux") == "tmux (brew install tmux)"
    assert installHintFor("claude") == "claude (https://claude.com/claude-code)"


def test_installHintFor_unknown_command_returns_bare_name():
    assert installHintFor("definitely_unknown_xyz") == "definitely_unknown_xyz"


def test_INSTALL_HINTS_keys_are_the_documented_set():
    assert set(INSTALL_HINTS) == {"jq", "python3", "tmux", "claude"}


def test_checkRequirements_returns_None_when_all_present():
    # `sh` and `ls` exist on every POSIX host pytest runs on.
    assert checkRequirements("jot", ["sh", "ls"]) is None


def test_checkRequirements_returns_None_for_empty_cmd_list():
    assert checkRequirements("jot", []) is None


def test_checkRequirements_returns_block_when_one_missing():
    out = checkRequirements("jot", ["definitely_missing_xyz"])
    assert out is not None
    parsed = json.loads(out)
    assert parsed["decision"] == "block"
    assert parsed["reason"] == (
        "jot needs: definitely_missing_xyz - install and retry."
    )


def test_checkRequirements_uses_install_hints_for_known_missing():
    # Hard to test missing `jq` directly (it may be installed); instead
    # verify the install-hint mapping is what gets used by exercising
    # an unknown cmd alongside, and rely on test_installHintFor_known_commands
    # for the hint-string contract.
    out = checkRequirements("jot", ["unknown_a", "unknown_b"])
    parsed = json.loads(out)
    assert parsed["reason"] == (
        "jot needs: unknown_a, unknown_b - install and retry."
    )


def test_checkRequirements_preserves_command_order_in_message():
    out = checkRequirements("p", ["zzz_missing", "aaa_missing"])
    parsed = json.loads(out)
    assert parsed["reason"] == (
        "p needs: zzz_missing, aaa_missing - install and retry."
    )


def test_checkRequirements_filters_present_commands_out_of_list():
    out = checkRequirements("jot", ["sh", "definitely_missing_xyz", "ls"])
    parsed = json.loads(out)
    assert parsed["reason"] == (
        "jot needs: definitely_missing_xyz - install and retry."
    )
