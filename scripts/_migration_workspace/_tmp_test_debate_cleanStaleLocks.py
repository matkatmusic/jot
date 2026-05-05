"""RED tests for debate_cleanStaleLocks (RELAXED_COVERAGE: no paired bash _tests).

Authored from intent + bash docstring of clean_stale_locks (lines 3018-3033 of
scripts/jot-plugin-orchestrator.sh). Per-test step comments per RED_GREEN_TDD.md.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

# Ensure workspace dir on sys.path so we import the in-progress module.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp_debate_cleanStaleLocks import debate_cleanStaleLocks  # noqa: E402


# Helper: write a lock file with the given pane id payload.
def _write_lock(debate_dir: Path, stage: str, agent: str, payload: str) -> Path:
    lock = debate_dir / f".{stage}_{agent}.lock"
    lock.write_text(payload)
    return lock


def test_removes_lock_with_missing_pane_id(tmp_path: Path) -> None:
    # Scenario: lock file is malformed and contains no pane id token.
    # Setup: create a .r1_gemini.lock with junk that sed regex will not match.
    lock = _write_lock(tmp_path, "r1", "gemini", "garbage-not-a-pane-id\n")
    # Test action: invoke cleaner with no live panes; tmux probes should not even matter.
    with patch("_tmp_debate_cleanStaleLocks._listLivePaneIds", return_value=set()), \
         patch("_tmp_debate_cleanStaleLocks._paneCurrentCommand", return_value=""):
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: the malformed lock must be gone.
    assert not lock.exists()


def test_removes_lock_when_pane_not_in_window(tmp_path: Path) -> None:
    # Scenario: lock references a pane id that is no longer present in the tmux window.
    # Setup: write a well-formed lock pointing to %42; tmux reports only %99 alive.
    lock = _write_lock(tmp_path, "r1", "codex", "debate:%42\n")
    with patch("_tmp_debate_cleanStaleLocks._listLivePaneIds", return_value={"%99"}), \
         patch("_tmp_debate_cleanStaleLocks._paneCurrentCommand", return_value="codex"):
        # Test action: clean stage r1.
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: stale lock removed.
    assert not lock.exists()


def test_removes_lock_when_pane_current_command_mismatches_agent(tmp_path: Path) -> None:
    # Scenario: pane is alive but running a different binary (agent crashed; shell took over).
    # Setup: lock claims pane %5 for gemini, but tmux reports current_command = "bash".
    lock = _write_lock(tmp_path, "r1", "gemini", "debate:%5\n")
    with patch("_tmp_debate_cleanStaleLocks._listLivePaneIds", return_value={"%5"}), \
         patch("_tmp_debate_cleanStaleLocks._paneCurrentCommand", return_value="bash"):
        # Test action.
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: lock removed because current_command != agent.
    assert not lock.exists()


def test_preserves_lock_when_pane_alive_and_command_matches_agent(tmp_path: Path) -> None:
    # Scenario: pane is live and running the agent binary -- lock is valid and must NOT be removed.
    # Setup: lock for codex on pane %7; tmux confirms %7 alive with current_command "codex".
    lock = _write_lock(tmp_path, "r1", "codex", "debate:%7\n")
    with patch("_tmp_debate_cleanStaleLocks._listLivePaneIds", return_value={"%7"}), \
         patch("_tmp_debate_cleanStaleLocks._paneCurrentCommand", return_value="codex"):
        # Test action.
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: live lock preserved.
    assert lock.exists()
    assert lock.read_text() == "debate:%7\n"


def test_only_touches_locks_for_requested_stage(tmp_path: Path) -> None:
    # Scenario: r2 lock files must be ignored when caller asks to clean r1.
    # Setup: write one stale r1 lock (no pane id) and one stale r2 lock (no pane id).
    r1_lock = _write_lock(tmp_path, "r1", "gemini", "junk\n")
    r2_lock = _write_lock(tmp_path, "r2", "gemini", "junk\n")
    with patch("_tmp_debate_cleanStaleLocks._listLivePaneIds", return_value=set()), \
         patch("_tmp_debate_cleanStaleLocks._paneCurrentCommand", return_value=""):
        # Test action: clean stage r1 only.
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: r1 lock removed, r2 lock untouched.
    assert not r1_lock.exists()
    assert r2_lock.exists()


def test_no_locks_present_is_a_noop(tmp_path: Path) -> None:
    # Scenario: empty debate directory -- glob matches nothing.
    # Setup: tmp_path is empty; no tmux probes should be invoked.
    with patch("_tmp_debate_cleanStaleLocks._listLivePaneIds") as live, \
         patch("_tmp_debate_cleanStaleLocks._paneCurrentCommand") as cur:
        # Test action.
        debate_cleanStaleLocks(tmp_path, "synthesis")
    # Test verification: function returns cleanly without probing tmux.
    assert live.call_count == 0
    assert cur.call_count == 0
