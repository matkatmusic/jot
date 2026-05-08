"""Tests for jot_lib state-management functions (jot_initState, jot_popFirstFromQueue)."""
from __future__ import annotations

from pathlib import Path

from common.scripts.jot_lib import (
    jot_initState,
    jot_popFirstFromQueue,
)

# --- jot_initState ---


def test_jot_initState_creates_state_directory_when_missing(tmp_path: Path) -> None:
    # Scenario: caller points at a state dir that does not yet exist.
    # Setup: choose a path under tmp_path that has not been created.
    state_dir = tmp_path / "jot-state"
    assert not state_dir.exists()
    # Test action.
    jot_initState(state_dir)
    # Test verification: directory exists after the call.
    assert state_dir.is_dir()


def test_jot_initState_creates_three_tracked_files(tmp_path: Path) -> None:
    # Scenario: fresh state dir must contain the three jot tracking files.
    # Setup: empty target path.
    state_dir = tmp_path / "jot-state"
    # Test action.
    jot_initState(state_dir)
    # Test verification: each tracked file is present and empty.
    for name in ("queue.txt", "active_job.txt", "audit.log"):
        f = state_dir / name
        assert f.is_file()
        assert f.stat().st_size == 0


def test_jot_initState_preserves_existing_queue_contents(tmp_path: Path) -> None:
    # Scenario: re-running on a populated state dir must not clobber data.
    # Setup: pre-create state dir with queued work.
    state_dir = tmp_path / "jot-state"
    state_dir.mkdir()
    queue = state_dir / "queue.txt"
    queue.write_text("job-1\njob-2\n")
    # Test action.
    jot_initState(state_dir)
    # Test verification: queue contents intact.
    assert queue.read_text() == "job-1\njob-2\n"


def test_jot_initState_preserves_existing_audit_log(tmp_path: Path) -> None:
    # Scenario: audit log must survive re-init (append-only history).
    # Setup: pre-existing audit log with entries.
    state_dir = tmp_path / "jot-state"
    state_dir.mkdir()
    audit = state_dir / "audit.log"
    audit.write_text("2026-05-04 event\n")
    # Test action.
    jot_initState(state_dir)
    # Test verification: audit log untouched.
    assert audit.read_text() == "2026-05-04 event\n"


def test_jot_initState_idempotent_on_second_call(tmp_path: Path) -> None:
    # Scenario: invoking twice is a no-op beyond touch.
    # Setup: run once to establish the state dir.
    state_dir = tmp_path / "jot-state"
    jot_initState(state_dir)
    # Test action.
    jot_initState(state_dir)
    # Test verification: dir + three files still present.
    assert state_dir.is_dir()
    for name in ("queue.txt", "active_job.txt", "audit.log"):
        assert (state_dir / name).is_file()


def test_jot_initState_creates_parent_directories(tmp_path: Path) -> None:
    # Scenario: state path nested under non-existent parents.
    # Setup: deep path with no intermediate dirs.
    state_dir = tmp_path / "a" / "b" / "c" / "jot-state"
    # Test action.
    jot_initState(state_dir)
    # Test verification: full chain created and files present.
    assert state_dir.is_dir()
    assert (state_dir / "queue.txt").is_file()


def test_jot_initState_accepts_string_path(tmp_path: Path) -> None:
    # Scenario: callers pass a plain str path (parity with bash arg).
    # Setup: build str path.
    state_dir = str(tmp_path / "jot-state")
    # Test action.
    jot_initState(state_dir)
    # Test verification: behaves identically to Path input.
    assert Path(state_dir).is_dir()
    assert (Path(state_dir) / "audit.log").is_file()


def test_jot_initState_touch_refreshes_mtime_on_existing_file(tmp_path: Path) -> None:
    # Scenario: bash `touch` updates mtime; Python parity required.
    # Setup: pre-existing file with an old mtime.
    import os
    state_dir = tmp_path / "jot-state"
    state_dir.mkdir()
    queue = state_dir / "queue.txt"
    queue.write_text("x\n")
    old = 1_000_000.0
    os.utime(queue, (old, old))
    before = queue.stat().st_mtime
    # Test action.
    jot_initState(state_dir)
    # Test verification: mtime advanced.
    assert queue.stat().st_mtime > before


# --- jot_popFirstFromQueue ---


def _seed_jot_state(state_dir: Path, queue_lines: list[str]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "queue.txt").write_text(
        ("\n".join(queue_lines) + "\n") if queue_lines else ""
    )
    (state_dir / "active_job.txt").write_text("")


def test_jot_popFirstFromQueue_returns_first_line(tmp_path: Path) -> None:
    # Scenario: 3-entry queue; pop returns the first one.
    # Setup: queue with three jobs.
    state = tmp_path / "state"
    _seed_jot_state(state, ["job-a", "job-b", "job-c"])
    # Test action.
    popped = jot_popFirstFromQueue(str(state))
    # Test verification.
    assert popped == "job-a"


def test_jot_popFirstFromQueue_removes_first_line_from_queue_file(tmp_path: Path) -> None:
    # Scenario: pop must mutate queue.txt by deleting line 1.
    state = tmp_path / "state"
    _seed_jot_state(state, ["job-a", "job-b", "job-c"])
    # Test action.
    jot_popFirstFromQueue(str(state))
    # Test verification.
    assert (state / "queue.txt").read_text() == "job-b\njob-c\n"


def test_jot_popFirstFromQueue_writes_popped_line_to_active_job_file(tmp_path: Path) -> None:
    # Scenario: pop writes popped entry to active_job.txt (head -1 > active).
    state = tmp_path / "state"
    _seed_jot_state(state, ["alpha", "beta"])
    # Test action.
    jot_popFirstFromQueue(str(state))
    # Test verification.
    assert (state / "active_job.txt").read_text() == "alpha\n"


def test_jot_popFirstFromQueue_returns_none_on_empty_queue(tmp_path: Path) -> None:
    # Scenario: empty queue.txt; bash returned 1 -> Python returns None.
    state = tmp_path / "state"
    _seed_jot_state(state, [])
    # Test action + verification.
    assert jot_popFirstFromQueue(str(state)) is None


def test_jot_popFirstFromQueue_empty_queue_does_not_modify_active_job(tmp_path: Path) -> None:
    # Scenario: empty-queue branch returns early; active_job.txt untouched.
    state = tmp_path / "state"
    _seed_jot_state(state, [])
    (state / "active_job.txt").write_text("prev-job\n")
    # Test action.
    jot_popFirstFromQueue(str(state))
    # Test verification.
    assert (state / "active_job.txt").read_text() == "prev-job\n"


def test_jot_popFirstFromQueue_single_entry_queue_becomes_empty(tmp_path: Path) -> None:
    # Scenario: pop the only entry; queue.txt becomes empty.
    state = tmp_path / "state"
    _seed_jot_state(state, ["only-job"])
    # Test action.
    popped = jot_popFirstFromQueue(str(state))
    # Test verification.
    assert popped == "only-job"
    assert (state / "queue.txt").read_text() == ""
