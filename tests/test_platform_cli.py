"""Parity tests for common/scripts/platform_cli.py and platform.sh shim.

Avoids invoking real osascript: tests run only on the non-Darwin
advisory path (or the missing-osascript advisory path), since that
exercises the full CLI/shim plumbing without needing Terminal.app.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_CLI = REPO_ROOT / "common" / "scripts" / "platform_cli.py"
PLATFORM_SH = REPO_ROOT / "common" / "scripts" / "platform.sh"


@pytest.fixture
def cli_env_no_osascript(tmp_path: Path) -> dict[str, str]:
    """Env where osascript is missing - drives the advisory branch.

    Used for the CLI-only tests where Python launches platform_cli.py
    directly via sys.executable (no pyenv shim path resolution needed).
    """
    bin_dir = tmp_path / "no_osascript_bin"
    bin_dir.mkdir()
    return {"PATH": str(bin_dir)}


@pytest.fixture
def shim_env_stub_osascript(tmp_path: Path) -> dict[str, str]:
    """Env for bash-shim tests: bash + python3 reachable; osascript is a stub.

    The shim invokes `python3 platform_cli.py ...`, which resolves
    python3 via PATH (pyenv shims need tr/sed/etc.), so /usr/bin must
    be on PATH. To keep osascript from actually launching Terminal.app,
    we shadow /usr/bin/osascript with a no-op stub placed earlier on PATH.
    """
    bin_dir = tmp_path / "shim_bin"
    bin_dir.mkdir()
    stub = bin_dir / "osascript"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    # Earlier-on-PATH: stub takes precedence over /usr/bin/osascript.
    return {"PATH": f"{bin_dir}:/usr/bin:/bin"}


def py(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PLATFORM_CLI), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def sh(snippet: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f'source "{PLATFORM_SH}"; {snippet}'],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


# ── CLI smoke ─────────────────────────────────────────────────────────


def test_cli_writes_advisory_when_osascript_unreachable(
    tmp_path: Path, cli_env_no_osascript: dict[str, str]
):
    log = tmp_path / "p.log"
    out = py(
        "spawn-terminal-if-needed",
        "fake-session",
        "--log-file", str(log),
        "--log-prefix", "testlog",
        env=cli_env_no_osascript,
    )
    assert out.returncode == 0
    assert log.exists()
    contents = log.read_text()
    assert "fake-session" in contents
    assert "testlog" in contents
    assert "tmux attach -t fake-session" in contents


def test_cli_exits_zero_with_no_extra_output(
    tmp_path: Path, cli_env_no_osascript: dict[str, str]
):
    out = py(
        "spawn-terminal-if-needed",
        "x",
        "--log-file", str(tmp_path / "p.log"),
        env=cli_env_no_osascript,
    )
    assert out.returncode == 0
    assert out.stdout == ""
    assert out.stderr == ""


def test_cli_maximize_flag_accepted(
    tmp_path: Path, cli_env_no_osascript: dict[str, str]
):
    out = py(
        "spawn-terminal-if-needed",
        "x",
        "--log-file", str(tmp_path / "p.log"),
        "--maximize",
        env=cli_env_no_osascript,
    )
    assert out.returncode == 0


def test_cli_requires_session_arg(cli_env_no_osascript: dict[str, str]):
    out = py("spawn-terminal-if-needed", env=cli_env_no_osascript)
    assert out.returncode != 0
    assert "session" in out.stderr.lower()


# ── bash-shim parity ──────────────────────────────────────────────────


def test_shim_invokes_cli_successfully(
    tmp_path: Path, shim_env_stub_osascript: dict[str, str]
):
    """End-to-end: shim → CLI → lib → osascript stub. All wires intact."""
    out = sh(
        f'spawn_terminal_if_needed "shim-fake" "{tmp_path / "p.log"}" "shimlog"',
        env=shim_env_stub_osascript,
    )
    assert out.returncode == 0


def test_shim_with_maximize_yes_succeeds(
    tmp_path: Path, shim_env_stub_osascript: dict[str, str]
):
    """Verifies the shim translates positional 'yes' → --maximize without error."""
    out = sh(
        f'spawn_terminal_if_needed "shim-fake" "{tmp_path / "p.log"}" "shimlog" "yes"',
        env=shim_env_stub_osascript,
    )
    assert out.returncode == 0


def test_shim_defaults_log_file_to_devnull(
    shim_env_stub_osascript: dict[str, str]
):
    """No log file passed: shim defaults to /dev/null; call still succeeds."""
    out = sh(
        'spawn_terminal_if_needed "shim-default-test"',
        env=shim_env_stub_osascript,
    )
    assert out.returncode == 0
