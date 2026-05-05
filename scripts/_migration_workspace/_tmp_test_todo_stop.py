"""RED tests for todo_stop migration.

Bash source: jot-plugin-orchestrator.sh todo_stop() ~lines 3666-3726.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).parent))

from _tmp_todo_stop import todo_stop


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
    with patch("_tmp_todo_stop.time.sleep"):
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
    with patch("_tmp_todo_stop.time.sleep"):
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
        patch("_tmp_todo_stop.time.sleep"),
        patch("_tmp_todo_stop.tmux_killPane"),
        patch("_tmp_todo_stop.tmux_retile"),
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
        patch("_tmp_todo_stop.time.sleep"),
        patch("_tmp_todo_stop.tmux_killPane"),
        patch("_tmp_todo_stop.tmux_retile"),
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
        patch("_tmp_todo_stop.time.sleep"),
        patch("_tmp_todo_stop.tmux_killPane"),
        patch("_tmp_todo_stop.tmux_retile"),
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
        patch("_tmp_todo_stop.time.sleep"),
        patch("_tmp_todo_stop.tmux_killPane"),
        patch("_tmp_todo_stop.tmux_retile"),
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
        patch("_tmp_todo_stop.time.sleep"),
        patch("_tmp_todo_stop.tmux_killPane"),
        patch("_tmp_todo_stop.tmux_retile"),
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
        patch("_tmp_todo_stop.time.sleep"),
        patch("_tmp_todo_stop.tmux_killPane"),
        patch("_tmp_todo_stop.tmux_retile"),
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
        patch("_tmp_todo_stop.time.sleep"),
        patch("_tmp_todo_stop.tmux_killPane", kill_mock),
        patch("_tmp_todo_stop.tmux_retile", retile_mock),
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
        patch("_tmp_todo_stop.time.sleep"),
        patch("_tmp_todo_stop.tmux_killPane"),
        patch("_tmp_todo_stop.tmux_retile", retile_mock),
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
        patch("_tmp_todo_stop.time.sleep"),
        patch("_tmp_todo_stop.tmux_killPane"),
        patch("_tmp_todo_stop.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    assert state_dir.is_dir()
    assert (state_dir / "audit.log").is_file()
