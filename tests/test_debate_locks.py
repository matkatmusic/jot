"""Tests for debate_lib -- locks bucket (cleanStaleLocks, liveSession, anyLiveLock, writes-lock-file)."""
from __future__ import annotations

from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from tests.test_util_filelock import _make_lock

from common.scripts.debate_lib import (
    debate_anyLiveLock,
    debate_cleanStaleLocks,
    debate_launchAgent,
    debate_liveSession,
)


# Constants used by the launchAgent/lock test
_PANE = "%7"
_AGENT = "claude"
_CMD = "claude --settings /tmp/s.json --add-dir '/repo'"
_READY = "Claude Code v"
_STAGE = "r1"


# Helper: write a lock file with the given pane id payload.
def _write_lock(debate_dir: Path, stage: str, agent: str, payload: str) -> Path:
    lock = debate_dir / f".{stage}_{agent}.lock"
    lock.write_text(payload)
    return lock


def _write_lock_at_path(lock_path: Path, pane_id: str) -> None:
    """Write a lock file with the canonical debate:<pane_id> format."""
    lock_path.write_text(f"debate:{pane_id}\n")


def _patch_all(pane_content: str = "", *, ready_after: int | None = 0):
    """Patch I/O callees on common.scripts.debate_lib (where bare names resolve)."""
    call_count = 0

    def fake_capture(pane_id, scrollback_lines=2000):
        nonlocal call_count
        result = _READY if (ready_after is not None and call_count >= ready_after) else ""
        call_count += 1
        return result

    return (
        patch("common.scripts.debate_lib.tmux_sendAndSubmit"),
        patch("common.scripts.debate_lib.tmux_capturePane", side_effect=fake_capture),
        patch("common.scripts.debate_lib.debate_writeFailed"),
        patch("common.scripts.debate_lib.time.sleep"),
    )


@pytest.fixture
def fake_tmux(monkeypatch):
    """Patch `_tmux_live_pane_ids` to return a configurable set without tmux."""
    state: dict[str, set[str]] = {"live": set()}

    def _fake() -> set[str]:
        return set(state["live"])

    monkeypatch.setattr("common.scripts.debate_lib._tmux_live_pane_ids", _fake)
    return state


# =====================================================================
# debate_cleanStaleLocks tests
# =====================================================================


def test_removes_lock_with_missing_pane_id(tmp_path: Path) -> None:
    # Scenario: lock file is malformed and contains no pane id token.
    # Setup: create a .r1_gemini.lock with junk that sed regex will not match.
    lock = _write_lock(tmp_path, "r1", "gemini", "garbage-not-a-pane-id\n")
    # Test action: invoke cleaner with no live panes; tmux probes should not even matter.
    with patch("common.scripts.debate_lib._tmux_listLivePaneIds", return_value=set()), \
         patch("common.scripts.debate_lib._tmux_paneCurrentCommand", return_value=""):
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: the malformed lock must be gone.
    assert not lock.exists()


def test_removes_lock_when_pane_not_in_window(tmp_path: Path) -> None:
    # Scenario: lock references a pane id that is no longer present in the tmux window.
    # Setup: write a well-formed lock pointing to %42; tmux reports only %99 alive.
    lock = _write_lock(tmp_path, "r1", "codex", "debate:%42\n")
    with patch("common.scripts.debate_lib._tmux_listLivePaneIds", return_value={"%99"}), \
         patch("common.scripts.debate_lib._tmux_paneCurrentCommand", return_value="codex"):
        # Test action: clean stage r1.
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: stale lock removed.
    assert not lock.exists()


def test_removes_lock_when_pane_current_command_mismatches_agent(tmp_path: Path) -> None:
    # Scenario: pane is alive but running a different binary (agent crashed; shell took over).
    # Setup: lock claims pane %5 for gemini, but tmux reports current_command = "bash".
    lock = _write_lock(tmp_path, "r1", "gemini", "debate:%5\n")
    with patch("common.scripts.debate_lib._tmux_listLivePaneIds", return_value={"%5"}), \
         patch("common.scripts.debate_lib._tmux_paneCurrentCommand", return_value="bash"):
        # Test action.
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: lock removed because current_command != agent.
    assert not lock.exists()


def test_preserves_lock_when_pane_alive_and_command_matches_agent(tmp_path: Path) -> None:
    # Scenario: pane is live and running the agent binary -- lock is valid and must NOT be removed.
    # Setup: lock for codex on pane %7; tmux confirms %7 alive with current_command "codex".
    lock = _write_lock(tmp_path, "r1", "codex", "debate:%7\n")
    with patch("common.scripts.debate_lib._tmux_listLivePaneIds", return_value={"%7"}), \
         patch("common.scripts.debate_lib._tmux_paneCurrentCommand", return_value="codex"):
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
    with patch("common.scripts.debate_lib._tmux_listLivePaneIds", return_value=set()), \
         patch("common.scripts.debate_lib._tmux_paneCurrentCommand", return_value=""):
        # Test action: clean stage r1 only.
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: r1 lock removed, r2 lock untouched.
    assert not r1_lock.exists()
    assert r2_lock.exists()


def test_no_locks_present_is_a_noop(tmp_path: Path) -> None:
    # Scenario: empty debate directory -- glob matches nothing.
    # Setup: tmp_path is empty; no tmux probes should be invoked.
    with patch("common.scripts.debate_lib._tmux_listLivePaneIds") as live, \
         patch("common.scripts.debate_lib._tmux_paneCurrentCommand") as cur:
        # Test action.
        debate_cleanStaleLocks(tmp_path, "synthesis")
    # Test verification: function returns cleanly without probing tmux.
    assert live.call_count == 0
    assert cur.call_count == 0


# =====================================================================
# debate_launchAgent: lock-file write [locks]
# =====================================================================


def test_writes_lock_file_before_launch(tmp_path):
    # Scenario: launch_agent writes debate:<pane_id> to the lock file before
    #           sending the launch command.
    # Setup: fresh debate_dir, pane ready on first capture
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=0)
    with patches[0], patches[1], patches[2], patches[3]:
        debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
        )
    # Test verification: lock file contains "debate:%pane_id"
    lock = tmp_path / f".{_STAGE}_{_AGENT}.lock"
    assert lock.exists(), "lock file must exist after launch"
    assert lock.read_text().strip() == f"debate:{_PANE}"


# =====================================================================
# debate_liveSession tests
# =====================================================================


def test_returns_session_name_when_lock_resolves(tmp_path: Path) -> None:
    # Scenario: debate dir has one live lock whose pane resolves to a tmux session
    # Setup: write .agent.lock with pane_id %1; mock tmux to return "debate-1"
    lock = tmp_path / ".agent.lock"
    _write_lock_at_path(lock, "%1")

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
    _write_lock_at_path(lock, "%5")

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
    _write_lock_at_path(lock, "%9")

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
    _write_lock_at_path(lock_a, "%2")
    _write_lock_at_path(lock_b, "%3")

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
    _write_lock_at_path(lock_a, "%10")
    _write_lock_at_path(lock_b, "%11")

    call_responses = [
        MagicMock(returncode=1, stdout="", stderr=""),
        MagicMock(returncode=0, stdout="debate-4\n", stderr=""),
    ]

    with patch("subprocess.run", side_effect=call_responses):
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == "debate-4"


# =====================================================================
# debate_anyLiveLock tests
# =====================================================================


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


# =====================================================================
# wait-for-outputs lock removal [locks]
# =====================================================================


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_removes_lock_file_when_output_appears(tmp_path):
    # Scenario: lock file exists alongside output; lock must be deleted on detection
    # Setup: create output AND lock file
    from common.scripts.debate_lib import debate_waitForOutputs
    agents = ["claude"]
    panes = {0: "%1"}
    out = tmp_path / "r2_claude.md"
    lock = tmp_path / ".r2_claude.lock"
    _write(out, "synthesis")
    _write(lock, "debate:%1")
    # Test action: poll once
    ok, completed, _ = debate_waitForOutputs(
        prefix="r2", timeout=5, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=lambda p, a: False,
        retry_pane=MagicMock(), sleep_fn=MagicMock(), poll_interval=5,
    )
    # Test verification: success, lock file removed
    assert ok is True
    assert completed == ["claude"]
    assert not lock.exists()
