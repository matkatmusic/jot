"""CLI + bash-shim parity tests for skills/todo/scripts/scan-open-todos.sh."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CLI = _REPO_ROOT / "common" / "scripts" / "todo" / "scan_open_todos_cli.py"
_SHIM = _REPO_ROOT / "skills" / "todo" / "scripts" / "scan-open-todos.sh"


def _runCli(repo_root: Path | str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_CLI), str(repo_root)],
        capture_output=True,
        text=True,
    )


def _runShim(repo_root: Path | str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_SHIM), str(repo_root)],
        capture_output=True,
        text=True,
    )


# Scenario: CLI run against a repo with no Todos/ dir
# Expectation: stdout is exactly "(none)\n", exit 0, stderr empty.
def test_cli_missing_todos_prints_none(tmp_path: Path) -> None:
    result = _runCli(tmp_path)
    assert result.returncode == 0
    assert result.stdout == "(none)\n"


# Scenario: CLI run against a populated Todos/
# Expectation: each *.md path on its own line, sorted, exit 0.
def test_cli_populated_todos_prints_sorted_paths(tmp_path: Path) -> None:
    todos = tmp_path / "Todos"
    todos.mkdir()
    (todos / "b.md").write_text("b")
    (todos / "a.md").write_text("a")
    result = _runCli(tmp_path)
    assert result.returncode == 0
    expected = f"{(todos / 'a.md').resolve()}\n{(todos / 'b.md').resolve()}\n"
    assert result.stdout == expected


# Scenario: CLI invoked with no arg
# Expectation: argparse exits nonzero (mirrors bash ${1:?}).
def test_cli_missing_arg_exits_nonzero() -> None:
    result = subprocess.run(
        [sys.executable, str(_CLI)], capture_output=True, text=True
    )
    assert result.returncode != 0


# Scenario: bash shim parity — empty repo
# Expectation: shim and CLI produce identical stdout/exit on a missing Todos/.
def test_shim_parity_missing_todos(tmp_path: Path) -> None:
    cli_result = _runCli(tmp_path)
    shim_result = _runShim(tmp_path)
    assert cli_result.stdout == shim_result.stdout
    assert cli_result.returncode == shim_result.returncode


# Scenario: bash shim parity — populated repo
# Expectation: shim and CLI produce identical stdout/exit with a Todos/*.md set.
def test_shim_parity_populated_todos(tmp_path: Path) -> None:
    todos = tmp_path / "Todos"
    todos.mkdir()
    (todos / "x.md").write_text("x")
    (todos / "y.md").write_text("y")
    cli_result = _runCli(tmp_path)
    shim_result = _runShim(tmp_path)
    assert cli_result.stdout == shim_result.stdout
    assert cli_result.returncode == shim_result.returncode


# Scenario: bash shim is executable (caller invokes it via path, not `bash X`)
# Expectation: file mode includes user-execute bit.
def test_shim_is_executable() -> None:
    assert os.access(_SHIM, os.X_OK), f"{_SHIM} must be user-executable"
