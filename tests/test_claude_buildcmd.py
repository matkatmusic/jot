from __future__ import annotations

import json
from pathlib import Path

import pytest

from common.scripts.claude_lib import claude_buildCmd


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
