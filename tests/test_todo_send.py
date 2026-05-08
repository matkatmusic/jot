"""Tests for todo_launcher and todo_sessionStart (send bucket)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from unittest.mock import patch

from common.scripts import todo_lib as mod
from common.scripts.todo_lib import todo_launcher, todo_sessionStart


def test_todo_launcher_success(monkeypatch, tmp_path):
    # Scenario: standard execution successfully creates inputs, cmds, and tmux window
    # Setup: mock all external calls and dependencies
    session_id = "test-session"
    idea = "fix a bug"
    pending_file = tmp_path / "pending.json"
    repo_root = tmp_path / "repo"
    cwd = repo_root / "src"
    transcript_path = tmp_path / "transcript.txt"

    repo_root.mkdir(parents=True)
    cwd.mkdir(parents=True)
    transcript_path.write_text("transcript content")

    pending_data = {
        "repo_root": str(repo_root),
        "cwd": str(cwd),
        "transcript_path": str(transcript_path),
        "timestamp": "20260101-120000"
    }
    pending_file.write_text(json.dumps(pending_data))

    calls = []

    monkeypatch.setattr("common.scripts.todo_lib.git_getBranchNameOrFail", lambda p: "main-branch")
    monkeypatch.setattr("common.scripts.todo_lib.git_getRecentCommitHashes", lambda p: ["commit1", "commit2"])
    monkeypatch.setattr("common.scripts.todo_lib.git_getUncommittedFilenames", lambda p: ["file1.txt"])
    monkeypatch.setattr("common.scripts.todo_lib.todo_scanOpen", lambda p: [str(repo_root / "Todos" / "todo1.md")])

    def mock_run(cmd, *args, **kwargs):
        calls.append(["run", cmd[0] if isinstance(cmd, list) else cmd])
        class MockResult:
            returncode = 0
            stdout = "mock stdout output\n"
        return MockResult()

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(mod.subprocess, "run", mock_run)

    monkeypatch.setattr("common.scripts.todo_lib.claude_seedPermissions", lambda *args: calls.append(["claude_seedPermissions"]))
    monkeypatch.setattr("common.scripts.todo_lib.claude_buildCmd", lambda *args: "mock claude cmd")

    class MockFileLock:
        def __init__(self, path, timeout):
            pass
        def __enter__(self):
            calls.append(["lock_acquire"])
            return self
        def __exit__(self, *args):
            calls.append(["lock_release"])

    monkeypatch.setattr("common.scripts.todo_lib.FileLock", MockFileLock)

    monkeypatch.setattr("common.scripts.todo_lib.tmux_ensureSession", lambda *args: calls.append(["tmux_ensureSession"]))
    monkeypatch.setattr("common.scripts.todo_lib.tmux_splitWorkerPane", lambda *args: "%123")
    monkeypatch.setattr("common.scripts.todo_lib.tmux_setPaneTitle", lambda *args: calls.append(["tmux_setPaneTitle"]))
    monkeypatch.setattr("common.scripts.todo_lib.tmux_retile", lambda *args: calls.append(["tmux_retile"]))
    monkeypatch.setattr("common.scripts.todo_lib.terminal_spawnIfNeeded", lambda *args: calls.append(["terminal_spawnIfNeeded"]))

    # Test action:
    result = mod.todo_launcher(session_id, idea, str(pending_file))

    # Test verification:
    assert result == 0
    assert ["claude_seedPermissions"] in calls
    assert ["lock_acquire"] in calls
    assert ["tmux_ensureSession"] in calls
    assert ["tmux_setPaneTitle"] in calls
    assert ["tmux_retile"] in calls
    assert ["terminal_spawnIfNeeded"] in calls


# --- todo_sessionStart ---


# ---------------------------------------------------------------------------
# Scenario: missing args
# ---------------------------------------------------------------------------

def test_missing_input_file_returns_0(tmp_path, capsys):
    # Scenario: both args absent (input_file is empty string)
    # Setup: no files needed
    # Test action:
    rc = todo_sessionStart("", str(tmp_path))
    # Test verification:
    assert rc == 0
    assert "[todo-session-start]" in capsys.readouterr().err


def test_missing_tmpdir_inv_returns_0(tmp_path, capsys):
    # Scenario: tmpdir_inv is empty string
    # Setup: a real input file so only tmpdir is missing
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    # Test action:
    rc = todo_sessionStart(str(input_file), "")
    # Test verification:
    assert rc == 0
    assert "[todo-session-start]" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Scenario: tmux_target sidecar absent
# ---------------------------------------------------------------------------

def test_missing_sidecar_returns_0(tmp_path, capsys):
    # Scenario: tmpdir exists but tmux_target file is never written
    # Setup: input file present, no tmux_target sidecar
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    # Test action: patch sleep to avoid 1s delay (5 * 0.2)
    with patch("common.scripts.todo_lib.time.sleep"):
        rc = todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification:
    assert rc == 0
    assert "tmux_target sidecar empty" in capsys.readouterr().err


def test_empty_sidecar_returns_0(tmp_path, capsys):
    # Scenario: tmux_target file exists but is empty
    # Setup:
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    (tmpdir / "tmux_target").write_text("")
    # Test action:
    with patch("common.scripts.todo_lib.time.sleep"):
        rc = todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification:
    assert rc == 0
    assert "tmux_target sidecar empty" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Scenario: Claude TUI not ready
# ---------------------------------------------------------------------------

def test_claude_not_ready_returns_1(tmp_path, capsys):
    # Scenario: sidecar present but tmux_waitForClaudeReadiness returns 1
    # Setup:
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    (tmpdir / "tmux_target").write_text("%42\n")
    # Test action:
    with patch("common.scripts.todo_lib.tmux_waitForClaudeReadiness", return_value=1):
        rc = todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification:
    assert rc == 1
    assert "claude TUI not ready" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Scenario: happy path
# ---------------------------------------------------------------------------

def test_happy_path_sends_prompt(tmp_path):
    # Scenario: all conditions met; expect jot_sendPrompt called with correct args
    # Setup:
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    (tmpdir / "tmux_target").write_text("%42\n")
    # Test action:
    with patch("common.scripts.todo_lib.tmux_waitForClaudeReadiness", return_value=0), \
         patch("common.scripts.todo_lib.jot_sendPrompt", return_value=0) as mock_send:
        rc = todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification:
    assert rc == 0
    mock_send.assert_called_once_with("%42", str(input_file))


def test_happy_path_propagates_send_rc(tmp_path):
    # Scenario: jot_sendPrompt returns nonzero; function should propagate it
    # Setup:
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    (tmpdir / "tmux_target").write_text("%99\n")
    # Test action:
    with patch("common.scripts.todo_lib.tmux_waitForClaudeReadiness", return_value=0), \
         patch("common.scripts.todo_lib.jot_sendPrompt", return_value=3):
        rc = todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification:
    assert rc == 3


def test_sidecar_read_strips_whitespace(tmp_path):
    # Scenario: sidecar has trailing newline; pane id must be stripped before use
    # Setup:
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    (tmpdir / "tmux_target").write_text("  %7  \n")
    # Test action:
    with patch("common.scripts.todo_lib.tmux_waitForClaudeReadiness", return_value=0) as mock_wait, \
         patch("common.scripts.todo_lib.jot_sendPrompt", return_value=0):
        todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification: pane id passed to readiness check must be stripped
    mock_wait.assert_called_once_with("%7")
