"""Parity tests for common/scripts/jot/scan_open_todos_cli.py and the
skills/jot/scripts/scan-open-todos.sh bash entry point.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_CLI = REPO_ROOT / "common" / "scripts" / "jot" / "scan_open_todos_cli.py"
SCAN_SH = REPO_ROOT / "skills" / "jot" / "scripts" / "scan-open-todos.sh"


@pytest.fixture
def cli_env_default() -> dict[str, str]:
    """Default env for direct python3 _cli.py invocations."""
    return {"PATH": "/usr/bin:/bin"}


@pytest.fixture
def shim_env() -> dict[str, str]:
    """Env for bash entry-point tests: preserves PATH so `python3`
    resolves even when pyenv shims are in use."""
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}


def py(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCAN_CLI), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def shim(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCAN_SH), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# ── CLI subprocess tests ──────────────────────────────────────────────


def test_cli_no_todos_dir_empty_stdout(tmp_path: Path, cli_env_default: dict[str, str]):
    out = py(str(tmp_path), env=cli_env_default)
    assert out.returncode == 0
    assert out.stdout == ""


def test_cli_all_closed_empty_stdout(tmp_path: Path, cli_env_default: dict[str, str]):
    _write(tmp_path / "Todos" / "x.md", "---\nstatus: closed\n---\n")
    out = py(str(tmp_path), env=cli_env_default)
    assert out.returncode == 0
    assert out.stdout == ""


def test_cli_mixed_only_open_listed(tmp_path: Path, cli_env_default: dict[str, str]):
    o = _write(tmp_path / "Todos" / "open.md", "---\nstatus: open\n---\n")
    _write(tmp_path / "Todos" / "closed.md", "---\nstatus: closed\n---\n")
    _write(tmp_path / "Todos" / "raw.md", "no frontmatter\n")
    out = py(str(tmp_path), env=cli_env_default)
    assert out.returncode == 0
    assert out.stdout.strip().splitlines() == [str(o)]


def test_cli_default_target_is_cwd(tmp_path: Path, cli_env_default: dict[str, str]):
    o = _write(tmp_path / "Todos" / "open.md", "---\nstatus: open\n---\n")
    out = subprocess.run(
        [sys.executable, str(SCAN_CLI)],
        capture_output=True,
        text=True,
        check=False,
        env=cli_env_default,
        cwd=str(tmp_path),
    )
    assert out.returncode == 0
    # Relative path because target defaults to "."
    assert out.stdout.strip().splitlines() == [str(Path("Todos") / "open.md")]


# ── bash entry-point parity ───────────────────────────────────────────


def test_shim_matches_cli_for_mixed_todos(tmp_path: Path, shim_env: dict[str, str]):
    """End-to-end: bash shim → exec python3 → CLI → lib. Output
    must match a direct CLI call exactly."""
    _write(tmp_path / "Todos" / "a.md", "---\nstatus: open\n---\n")
    _write(tmp_path / "Todos" / "b.md", "---\nstatus: closed\n---\n")
    _write(tmp_path / "Todos" / "c.md", "---\nstatus: open\n---\n")

    shim_out = shim(str(tmp_path), env=shim_env)
    assert shim_out.returncode == 0

    cli_out = subprocess.run(
        [sys.executable, str(SCAN_CLI), str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        env=shim_env,
    )
    assert shim_out.stdout == cli_out.stdout
    # And it actually contains both open files in sorted order.
    lines = shim_out.stdout.strip().splitlines()
    assert lines == [
        str(tmp_path / "Todos" / "a.md"),
        str(tmp_path / "Todos" / "c.md"),
    ]


def test_shim_no_todos_dir_empty(tmp_path: Path, shim_env: dict[str, str]):
    out = shim(str(tmp_path), env=shim_env)
    assert out.returncode == 0
    assert out.stdout == ""
