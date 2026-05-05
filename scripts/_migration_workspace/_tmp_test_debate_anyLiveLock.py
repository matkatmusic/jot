"""RED tests for debate_anyLiveLock (RELAXED_COVERAGE: no paired bash _tests).

Tests are authored from intent + docstring of bash `any_live_lock`
(jot-plugin-orchestrator.sh:2357-2367). One behavior per test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Allow `from _tmp_debate_anyLiveLock import ...` regardless of pytest CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp_debate_anyLiveLock import debate_anyLiveLock  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lock(dir_path: Path, name: str, pane_id: str | None) -> Path:
    """Create a hidden lock file with optional `debate:<pane_id>` line."""
    lock = dir_path / name
    body = f"debate:{pane_id}\n" if pane_id else ""
    lock.write_text(body, encoding="utf-8")
    return lock


@pytest.fixture
def fake_tmux(monkeypatch):
    """Patch `_live_pane_ids` to return a configurable set without tmux."""
    state: dict[str, set[str]] = {"live": set()}

    def _fake() -> set[str]:
        return set(state["live"])

    import _tmp_debate_anyLiveLock as mod

    monkeypatch.setattr(mod, "_live_pane_ids", _fake)
    return state


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_returns_false_when_no_lock_files(tmp_path, fake_tmux):
    # Scenario: empty debate dir, no .*.lock files exist.
    # Setup: tmp_path is fresh; tmux reports no live panes.
    fake_tmux["live"] = set()
    # Test action: invoke debate_anyLiveLock on the empty directory.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: bash returns rc=1 (no live lock) -> Python returns False.
    assert result is False


def test_returns_true_when_lock_pane_id_is_live(tmp_path, fake_tmux):
    # Scenario: a hidden .lock file references a pane that tmux still reports.
    # Setup: write `.alpha.lock` containing `debate:%42`; tmux lists `%42` live.
    _make_lock(tmp_path, ".alpha.lock", "%42")
    fake_tmux["live"] = {"%42", "%99"}
    # Test action: scan the directory for live debate locks.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: pane id matched a live tmux pane -> True.
    assert result is True


def test_returns_false_when_lock_pane_id_is_dead(tmp_path, fake_tmux):
    # Scenario: lock file's pane id is NOT in the live tmux pane set.
    # Setup: lock points at `%7`; tmux only knows `%1` and `%2`.
    _make_lock(tmp_path, ".beta.lock", "%7")
    fake_tmux["live"] = {"%1", "%2"}
    # Test action: query for any live lock.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: dead pane id must not register as a live lock.
    assert result is False


def test_skips_lock_without_debate_marker(tmp_path, fake_tmux):
    # Scenario: a hidden .lock exists but contains no `debate:%N` line.
    # Setup: garbage payload only; tmux happens to have %1 alive.
    (tmp_path / ".garbage.lock").write_text("not-a-debate-line\n", encoding="utf-8")
    fake_tmux["live"] = {"%1"}
    # Test action: scan the dir.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: sed extracts empty pane_id -> bash skips -> False.
    assert result is False


def test_returns_false_when_directory_missing(tmp_path, fake_tmux):
    # Scenario: caller passes a path that does not exist.
    # Setup: build a non-existent child path.
    missing = tmp_path / "nope"
    fake_tmux["live"] = {"%1"}
    # Test action: invoke against missing dir (bash for-loop yields no matches).
    result = debate_anyLiveLock(missing)
    # Test verification: nothing to iterate -> False.
    assert result is False


def test_returns_true_if_any_one_of_many_locks_is_live(tmp_path, fake_tmux):
    # Scenario: multiple lock files; only one references a live pane.
    # Setup: three locks; only `%30` is live in tmux.
    _make_lock(tmp_path, ".a.lock", "%10")
    _make_lock(tmp_path, ".b.lock", "%20")
    _make_lock(tmp_path, ".c.lock", "%30")
    fake_tmux["live"] = {"%30"}
    # Test action: scan all locks.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: short-circuits to True on first live match.
    assert result is True


def test_ignores_non_hidden_lock_files(tmp_path, fake_tmux):
    # Scenario: a .lock file NOT starting with `.` should be ignored.
    # Setup: bash glob is `.*.lock`; visible `visible.lock` must not match.
    (tmp_path / "visible.lock").write_text("debate:%5\n", encoding="utf-8")
    fake_tmux["live"] = {"%5"}
    # Test action: scan dir for hidden locks only.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: visible file ignored -> no live lock found -> False.
    assert result is False
