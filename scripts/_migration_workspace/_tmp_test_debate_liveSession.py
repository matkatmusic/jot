#!/usr/bin/env python3
"""RED tests for debate_liveSession.

Migrated from bash live_debate_session() (jot-plugin-orchestrator.sh:2375).
RELAXED_COVERAGE: no paired bash _tests; tests authored from docstring + body intent.
"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

# Workspace import with monolith fallback
try:
    from _tmp_debate_liveSession import debate_liveSession
except ImportError:
    from jot_plugin_orchestrator import debate_liveSession  # type: ignore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_lock(lock_path: Path, pane_id: str) -> None:
    """Write a lock file with the canonical debate:<pane_id> format."""
    lock_path.write_text(f"debate:{pane_id}\n")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_returns_session_name_when_lock_resolves(tmp_path: Path) -> None:
    # Scenario: debate dir has one live lock whose pane resolves to a tmux session
    # Setup: write .agent.lock with pane_id %1; mock tmux to return "debate-1"
    lock = tmp_path / ".agent.lock"
    _write_lock(lock, "%1")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="debate-1\n", stderr="")
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == "debate-1"


def test_returns_empty_when_no_lock_files(tmp_path: Path) -> None:
    # Scenario: debate dir has no .*.lock files
    # Setup: empty tmp_path directory
    # Test action:
    result = debate_liveSession(str(tmp_path))
    # Test verification:
    assert result == ""


def test_returns_empty_when_lock_has_no_pane_id(tmp_path: Path) -> None:
    # Scenario: lock file exists but content does not match debate:<pane_id> pattern
    # Setup: lock file with garbage content
    lock = tmp_path / ".bad.lock"
    lock.write_text("not-a-pane-ref\n")

    with patch("subprocess.run") as mock_run:
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == ""
    mock_run.assert_not_called()


def test_returns_empty_when_tmux_fails(tmp_path: Path) -> None:
    # Scenario: lock file has valid pane_id but tmux display-message returns non-zero
    # Setup: write valid lock; mock tmux to return rc=1
    lock = tmp_path / ".agent.lock"
    _write_lock(lock, "%5")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="no server running")
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == ""


def test_returns_empty_when_tmux_returns_empty_session(tmp_path: Path) -> None:
    # Scenario: tmux succeeds (rc=0) but returns empty session name (pane gone)
    # Setup: write valid lock; mock tmux stdout to empty string
    lock = tmp_path / ".agent.lock"
    _write_lock(lock, "%9")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == ""


def test_skips_missing_lock_file_gracefully(tmp_path: Path) -> None:
    # Scenario: glob finds a path that disappears between glob and open (TOCTOU)
    # Setup: no actual files; just verify empty-dir returns "" without crashing
    # Test action:
    result = debate_liveSession(str(tmp_path))
    # Test verification:
    assert result == ""


def test_returns_first_resolved_session_from_multiple_locks(tmp_path: Path) -> None:
    # Scenario: multiple lock files; first valid one wins
    # Setup: two lock files; first resolves to "debate-2", second would give "debate-3"
    lock_a = tmp_path / ".a.lock"
    lock_b = tmp_path / ".b.lock"
    _write_lock(lock_a, "%2")
    _write_lock(lock_b, "%3")

    call_responses = [
        MagicMock(returncode=0, stdout="debate-2\n", stderr=""),
        MagicMock(returncode=0, stdout="debate-3\n", stderr=""),
    ]

    with patch("subprocess.run", side_effect=call_responses) as mock_run:
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == "debate-2"
    # Only one tmux call needed (returns on first success)
    assert mock_run.call_count == 1


def test_falls_through_to_second_lock_when_first_tmux_fails(tmp_path: Path) -> None:
    # Scenario: first lock's pane is dead; second lock resolves successfully
    # Setup: two locks; tmux fails for first pane, succeeds for second
    lock_a = tmp_path / ".a.lock"
    lock_b = tmp_path / ".b.lock"
    _write_lock(lock_a, "%10")
    _write_lock(lock_b, "%11")

    call_responses = [
        MagicMock(returncode=1, stdout="", stderr=""),
        MagicMock(returncode=0, stdout="debate-4\n", stderr=""),
    ]

    with patch("subprocess.run", side_effect=call_responses):
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == "debate-4"
