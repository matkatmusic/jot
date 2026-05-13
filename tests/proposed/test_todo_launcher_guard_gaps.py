from __future__ import annotations

from pathlib import Path

import pytest

from common.scripts import todo_lib


def test_todo_launcher_rejects_missing_session_id(tmp_path: Path, capsys) -> None:
    # Scenario: todo_launcher is called without the required session id.
    # Setup: create a placeholder pending file path that should not be read.
    pending_file = tmp_path / "pending.json"

    # Test action: call todo_launcher with an empty session id.
    result = todo_lib.todo_launcher("", "refined idea", str(pending_file))

    # Test verification: the function rejects the call and explains why.
    assert result == 1
    assert "session_id required" in capsys.readouterr().err


def test_todo_launcher_rejects_missing_refined_idea(tmp_path: Path, capsys) -> None:
    # Scenario: todo_launcher is called without the refined todo idea.
    # Setup: create a placeholder pending file path that should not be read.
    pending_file = tmp_path / "pending.json"

    # Test action: call todo_launcher with an empty idea.
    result = todo_lib.todo_launcher("session-1", "", str(pending_file))

    # Test verification: the function rejects the call and explains why.
    assert result == 1
    assert "refined idea required" in capsys.readouterr().err


def test_todo_launcher_rejects_missing_pending_file_path(capsys) -> None:
    # Scenario: todo_launcher is called without the pending-file path.
    # Setup: provide the other required arguments.

    # Test action: call todo_launcher with an empty pending-file path.
    result = todo_lib.todo_launcher("session-1", "refined idea", "")

    # Test verification: the function rejects the call and explains why.
    assert result == 1
    assert "pending_file path required" in capsys.readouterr().err


def test_todo_launcher_rejects_nonexistent_pending_file(tmp_path: Path, capsys) -> None:
    # Scenario: todo_launcher receives a path to a pending file that does not
    # exist on disk.
    # Setup: choose a missing path under tmp_path.
    pending_file = tmp_path / "missing.json"

    # Test action: call todo_launcher with the missing pending file.
    result = todo_lib.todo_launcher("session-1", "refined idea", str(pending_file))

    # Test verification: the function returns failure and prints the path.
    assert result == 1
    assert str(pending_file) in capsys.readouterr().err


def test_todo_launcher_rejects_invalid_pending_json(tmp_path: Path, capsys) -> None:
    # Scenario: the pending file exists, but it is not valid JSON.
    # Setup: write invalid JSON to the pending file.
    pending_file = tmp_path / "pending.json"
    pending_file.write_text("{not json", encoding="utf-8")

    # Test action: call todo_launcher with the unreadable payload.
    result = todo_lib.todo_launcher("session-1", "refined idea", str(pending_file))

    # Test verification: the function returns failure and reports the read error.
    assert result == 1
    assert "failed to read pending file" in capsys.readouterr().err
