"""Parity tests for claude_launcher_cli.py and the claude-launcher.sh shim.

CLI tests assert the spec contract (settings file parses to expected
dict; stdout shlex-splits to expected argv). Shim tests assert that the
bash shim, the CLI, and the lib all agree byte-for-byte.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_LAUNCHER_CLI = REPO_ROOT / "common" / "scripts" / "claude_launcher_cli.py"
CLAUDE_LAUNCHER_SH = REPO_ROOT / "common" / "scripts" / "claude-launcher.sh"


def py(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLAUDE_LAUNCHER_CLI), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def sh(snippet: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f'source "{CLAUDE_LAUNCHER_SH}"; {snippet}'],
        capture_output=True,
        text=True,
        check=False,
    )


def _writeHooks(path: Path, obj: dict) -> Path:
    path.write_text(json.dumps(obj))
    return path


# ── CLI direct ────────────────────────────────────────────────────────


def test_cli_writes_settings_file_with_expected_structure(tmp_path: Path):
    settings = tmp_path / "settings.json"
    hooks = _writeHooks(tmp_path / "hooks.json", {"SessionStart": []})
    out = py("build-claude-cmd", str(settings), '["Bash"]', str(hooks), "/c")
    assert out.returncode == 0
    parsed = json.loads(settings.read_text())
    assert parsed == {
        "permissions": {"allow": ["Bash"]},
        "hooks": {"SessionStart": []},
    }


def test_cli_stdout_shlex_splits_to_expected_argv(tmp_path: Path):
    settings = tmp_path / "settings.json"
    hooks = _writeHooks(tmp_path / "hooks.json", {})
    out = py(
        "build-claude-cmd",
        str(settings), "[]", str(hooks), "/cwd", "/extra1", "/extra2",
    )
    assert out.returncode == 0
    assert shlex.split(out.stdout.strip()) == [
        "claude",
        "--settings", str(settings),
        "--add-dir", "/cwd",
        "--add-dir", "/extra1",
        "--add-dir", "/extra2",
    ]


def test_cli_missing_required_arg_exits_nonzero(tmp_path: Path):
    out = py("build-claude-cmd", str(tmp_path / "settings.json"))
    assert out.returncode != 0


def test_cli_handles_no_extra_add_dirs(tmp_path: Path):
    settings = tmp_path / "settings.json"
    hooks = _writeHooks(tmp_path / "hooks.json", {})
    out = py("build-claude-cmd", str(settings), "[]", str(hooks), "/cwd")
    assert out.returncode == 0
    argv = shlex.split(out.stdout.strip())
    # Exactly 5 tokens: claude --settings <s> --add-dir /cwd
    assert len(argv) == 5
    assert argv[-2:] == ["--add-dir", "/cwd"]


# ── Bash-shim parity ──────────────────────────────────────────────────


def test_shim_settings_file_matches_cli(tmp_path: Path):
    """Source the .sh, call build_claude_cmd, compare settings file vs CLI run."""
    hooks_obj = {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]}
    allow_json = '["Bash(*)", "Read"]'
    cwd = "/the/cwd"

    # CLI run.
    settings_cli = tmp_path / "cli.json"
    hooks_file = _writeHooks(tmp_path / "hooks.json", hooks_obj)
    py("build-claude-cmd", str(settings_cli), allow_json, str(hooks_file), cwd)

    # Shim run (separate output file).
    settings_shim = tmp_path / "shim.json"
    out = sh(
        f'build_claude_cmd '
        f'"{settings_shim}" \'{allow_json}\' "{hooks_file}" "{cwd}"'
    )
    assert out.returncode == 0

    assert json.loads(settings_cli.read_text()) == json.loads(
        settings_shim.read_text()
    )


def test_shim_stdout_argv_matches_cli(tmp_path: Path):
    hooks_file = _writeHooks(tmp_path / "hooks.json", {})
    settings = tmp_path / "settings.json"

    py_out = py(
        "build-claude-cmd",
        str(settings), "[]", str(hooks_file), "/cwd", "/x",
    )
    sh_out = sh(
        f'build_claude_cmd "{settings}" \'[]\' "{hooks_file}" "/cwd" "/x"'
    )

    assert py_out.returncode == sh_out.returncode == 0
    # stdout from shim and CLI should resolve to the same argv.
    assert (
        shlex.split(py_out.stdout.strip())
        == shlex.split(sh_out.stdout.strip())
    )


def test_shim_handles_path_with_single_quote(tmp_path: Path):
    """Regression-prevent: bash original would corrupt this path."""
    hooks_file = _writeHooks(tmp_path / "hooks.json", {})
    settings = tmp_path / "settings.json"
    weird = "/path/with'quote"
    out = sh(
        f"""build_claude_cmd "{settings}" '[]' "{hooks_file}" "{weird}" """
    )
    assert out.returncode == 0
    argv = shlex.split(out.stdout.strip())
    assert weird in argv
