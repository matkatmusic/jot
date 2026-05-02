"""Spec-based tests for common/scripts/claude_launcher_lib.py.

Tests assert against the function's CONTRACT (JSON-parse equality of
the settings file; shell-evaluation equality of the command string),
not against the bash original's exact byte stream. The bash version's
naive single-quote wrapping and raw-text JSON heredoc interpolation
are bugs the Python port intentionally avoids.
"""
from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from claude_launcher_lib import buildClaudeCmd


# ── Helpers ───────────────────────────────────────────────────────────


def _writeHooks(path: Path, obj: dict) -> Path:
    path.write_text(json.dumps(obj))
    return path


# ── Settings-file structural contract ─────────────────────────────────


def test_settings_file_is_valid_json(tmp_path: Path):
    settings = tmp_path / "settings.json"
    hooks = _writeHooks(tmp_path / "hooks.json", {"SessionStart": []})
    buildClaudeCmd(settings, '["Bash"]', hooks, "/c", [])
    # Will raise if not valid JSON.
    json.loads(settings.read_text())


def test_settings_file_top_level_has_permissions_and_hooks(tmp_path: Path):
    settings = tmp_path / "settings.json"
    hooks = _writeHooks(tmp_path / "hooks.json", {})
    buildClaudeCmd(settings, "[]", hooks, "/c", [])
    parsed = json.loads(settings.read_text())
    assert set(parsed.keys()) == {"permissions", "hooks"}


def test_settings_file_embeds_parsed_allow_json(tmp_path: Path):
    settings = tmp_path / "settings.json"
    hooks = _writeHooks(tmp_path / "hooks.json", {})
    buildClaudeCmd(settings, '["Bash(*)", "Read"]', hooks, "/c", [])
    parsed = json.loads(settings.read_text())
    assert parsed["permissions"] == {"allow": ["Bash(*)", "Read"]}


def test_settings_file_embeds_parsed_hooks_json(tmp_path: Path):
    settings = tmp_path / "settings.json"
    expected_hooks = {
        "SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}],
        "Stop": [{"hooks": [{"type": "command", "command": "echo bye"}]}],
    }
    hooks = _writeHooks(tmp_path / "hooks.json", expected_hooks)
    buildClaudeCmd(settings, "[]", hooks, "/c", [])
    parsed = json.loads(settings.read_text())
    assert parsed["hooks"] == expected_hooks


def test_settings_file_overwrites_existing(tmp_path: Path):
    settings = tmp_path / "settings.json"
    settings.write_text("PRIOR GARBAGE")
    hooks = _writeHooks(tmp_path / "hooks.json", {})
    buildClaudeCmd(settings, "[]", hooks, "/c", [])
    parsed = json.loads(settings.read_text())
    assert "permissions" in parsed


# ── Command-string structural contract ────────────────────────────────


def test_returned_argv_starts_with_claude_settings(tmp_path: Path):
    settings = tmp_path / "settings.json"
    hooks = _writeHooks(tmp_path / "hooks.json", {})
    cmd = buildClaudeCmd(settings, "[]", hooks, "/c", [])
    argv = shlex.split(cmd)
    assert argv[0] == "claude"
    assert argv[1] == "--settings"
    assert argv[2] == str(settings)


def test_cwd_is_first_add_dir(tmp_path: Path):
    settings = tmp_path / "settings.json"
    hooks = _writeHooks(tmp_path / "hooks.json", {})
    cmd = buildClaudeCmd(settings, "[]", hooks, "/the/cwd", [])
    argv = shlex.split(cmd)
    assert argv[3] == "--add-dir"
    assert argv[4] == "/the/cwd"


def test_extra_add_dirs_follow_in_source_order(tmp_path: Path):
    settings = tmp_path / "settings.json"
    hooks = _writeHooks(tmp_path / "hooks.json", {})
    cmd = buildClaudeCmd(
        settings, "[]", hooks, "/cwd", ["/extra1", "/extra2", "/extra3"]
    )
    argv = shlex.split(cmd)
    # After the cwd add-dir pair (positions 3,4), extras come in pairs.
    assert argv[5:] == [
        "--add-dir", "/extra1",
        "--add-dir", "/extra2",
        "--add-dir", "/extra3",
    ]


def test_empty_add_dirs_has_no_dangling_flag(tmp_path: Path):
    settings = tmp_path / "settings.json"
    hooks = _writeHooks(tmp_path / "hooks.json", {})
    cmd = buildClaudeCmd(settings, "[]", hooks, "/cwd", [])
    argv = shlex.split(cmd)
    # Exactly: claude --settings <s> --add-dir <cwd>. No trailing --add-dir.
    assert len(argv) == 5
    assert argv[-2:] == ["--add-dir", "/cwd"]


def test_full_argv_for_representative_input(tmp_path: Path):
    settings = tmp_path / "settings.json"
    hooks = _writeHooks(tmp_path / "hooks.json", {})
    cmd = buildClaudeCmd(
        settings,
        '["Bash"]',
        hooks,
        "/Users/me/project",
        ["/Users/me/project/sub"],
    )
    assert shlex.split(cmd) == [
        "claude",
        "--settings", str(settings),
        "--add-dir", "/Users/me/project",
        "--add-dir", "/Users/me/project/sub",
    ]


# ── Quoting edge case (regression-prevent the bash bug) ───────────────


def test_path_with_single_quote_round_trips_through_shell(tmp_path: Path):
    """The bash original would corrupt this path. Python must escape it."""
    settings = tmp_path / "settings.json"
    hooks = _writeHooks(tmp_path / "hooks.json", {})
    weird = "/path/with'quote/inside"
    cmd = buildClaudeCmd(settings, "[]", hooks, weird, [])
    argv = shlex.split(cmd)
    assert weird in argv


def test_path_with_spaces_round_trips_through_shell(tmp_path: Path):
    settings = tmp_path / "settings.json"
    hooks = _writeHooks(tmp_path / "hooks.json", {})
    spaced = "/path with spaces/here"
    cmd = buildClaudeCmd(settings, "[]", hooks, spaced, [])
    argv = shlex.split(cmd)
    assert spaced in argv


# ── Fail-fast contract ────────────────────────────────────────────────


def test_malformed_allow_json_raises_json_decode_error(tmp_path: Path):
    settings = tmp_path / "settings.json"
    hooks = _writeHooks(tmp_path / "hooks.json", {})
    with pytest.raises(json.JSONDecodeError):
        buildClaudeCmd(settings, "this is not json", hooks, "/c", [])


def test_missing_hooks_json_file_raises_file_not_found(tmp_path: Path):
    settings = tmp_path / "settings.json"
    missing = tmp_path / "does_not_exist.json"
    with pytest.raises(FileNotFoundError):
        buildClaudeCmd(settings, "[]", missing, "/c", [])
