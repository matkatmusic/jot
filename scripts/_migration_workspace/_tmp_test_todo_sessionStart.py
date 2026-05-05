"""RED/GREEN tests for todo_sessionStart.

Bash source: jot-plugin-orchestrator.sh lines 3732-3779 (todo_session_start).
No paired bash tests — authored from intent + docstring. RELAXED_COVERAGE.

Function contract:
  todo_sessionStart(input_file, tmpdir_inv) -> int
  1. Missing either arg -> stderr log, return 0.
  2. tmux_target sidecar absent/empty after 5 poll attempts -> stderr log, return 0.
  3. tmux_waitForClaudeReadiness fails -> stderr log, return 1.
  4. Happy path -> calls jot_sendPrompt(pane_id, input_file), returns its rc.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import call, patch

import pytest

# Workspace sys.path setup so import resolves without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _tmp_todo_sessionStart import todo_sessionStart


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
    with patch("_tmp_todo_sessionStart.time.sleep"):
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
    with patch("_tmp_todo_sessionStart.time.sleep"):
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
    with patch("_tmp_todo_sessionStart.tmux_waitForClaudeReadiness", return_value=1):
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
    with patch("_tmp_todo_sessionStart.tmux_waitForClaudeReadiness", return_value=0), \
         patch("_tmp_todo_sessionStart.jot_sendPrompt", return_value=0) as mock_send:
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
    with patch("_tmp_todo_sessionStart.tmux_waitForClaudeReadiness", return_value=0), \
         patch("_tmp_todo_sessionStart.jot_sendPrompt", return_value=3):
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
    with patch("_tmp_todo_sessionStart.tmux_waitForClaudeReadiness", return_value=0) as mock_wait, \
         patch("_tmp_todo_sessionStart.jot_sendPrompt", return_value=0):
        todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification: pane id passed to readiness check must be stripped
    mock_wait.assert_called_once_with("%7")
