from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

import pytest

from common.scripts.util_lib import (
    FileLock,
    LockTimeout,
)


# --- FileLock / absorbed lock helpers ---

def _hold_lock_worker(lock_path: str, hold_seconds: float, ready_path: str) -> None:
    with FileLock(lock_path, timeout=5.0):
        Path(ready_path).write_text("ready", encoding="utf-8")
        time.sleep(hold_seconds)


def _try_acquire_worker(lock_path: str, timeout: float, result_path: str) -> None:
    try:
        with FileLock(lock_path, timeout=timeout):
            Path(result_path).write_text("acquired", encoding="utf-8")
    except LockTimeout:
        Path(result_path).write_text("timeout", encoding="utf-8")


def test_FileLock_acquire_succeeds_on_fresh_path(tmp_path: Path) -> None:
    # Scenario: no holder exists; acquire on fresh path must succeed.
    # Setup: lockfile path that has never been locked.
    lock_path = tmp_path / "fresh.lock"
    # Test action: acquire the lock.
    lock = FileLock(lock_path, timeout=2.0)
    lock.acquire()
    # Test verification: lock reports acquired and lockfile exists on disk.
    try:
        assert lock.acquired is True
        assert lock_path.exists()
    finally:
        lock.release()


def test_FileLock_release_clears_acquired_state(tmp_path: Path) -> None:
    # Scenario: after release, lock object reports not-acquired.
    # Setup: acquire the lock.
    lock_path = tmp_path / "release.lock"
    lock = FileLock(lock_path, timeout=2.0).acquire()
    # Test action: release.
    lock.release()
    # Test verification: acquired flag is False.
    assert lock.acquired is False


def test_FileLock_reacquire_after_release(tmp_path: Path) -> None:
    # Scenario: same process can re-acquire after releasing.
    # Setup: acquire then release.
    lock_path = tmp_path / "reacquire.lock"
    first = FileLock(lock_path, timeout=2.0).acquire()
    first.release()
    # Test action: acquire a second time.
    second = FileLock(lock_path, timeout=2.0).acquire()
    # Test verification: second acquire succeeds.
    try:
        assert second.acquired is True
    finally:
        second.release()


def test_FileLock_release_is_idempotent_when_not_held(tmp_path: Path) -> None:
    # Scenario: releasing a never-acquired FileLock is a no-op.
    # Setup: construct without acquiring.
    lock = FileLock(tmp_path / "never.lock", timeout=1.0)
    # Test action + verification: release does not raise.
    lock.release()
    assert lock.acquired is False


def test_FileLock_competing_process_blocks_until_holder_releases(tmp_path: Path) -> None:
    # Scenario: a second process blocks while the first holds the lock, then succeeds once released.
    # Setup: spawn holder worker that grabs the lock for 0.6s.
    lock_path = str(tmp_path / "competing.lock")
    ready_path = str(tmp_path / "ready.flag")
    result_path = str(tmp_path / "result.txt")
    ctx = multiprocessing.get_context("spawn")
    holder = ctx.Process(target=_hold_lock_worker, args=(lock_path, 0.6, ready_path))
    holder.start()
    try:
        deadline = time.monotonic() + 3.0
        while not Path(ready_path).exists():
            if time.monotonic() >= deadline:
                pytest.fail("holder process never signalled ready")
            time.sleep(0.02)
        # Test action: contender tries to acquire with a timeout longer than the hold.
        contender = ctx.Process(target=_try_acquire_worker, args=(lock_path, 3.0, result_path))
        start = time.monotonic()
        contender.start()
        contender.join(timeout=5.0)
        elapsed = time.monotonic() - start
        # Test verification: contender eventually acquired and had to wait for the holder.
        assert contender.exitcode == 0
        assert Path(result_path).read_text(encoding="utf-8") == "acquired"
        assert elapsed >= 0.4, f"contender acquired too fast: {elapsed:.3f}s"
    finally:
        holder.join(timeout=5.0)
        if holder.is_alive():
            holder.terminate()


def test_FileLock_timeout_elapses_when_lock_is_held(tmp_path: Path) -> None:
    # Scenario: contender with a short timeout raises LockTimeout while holder still owns the lock.
    # Setup: holder grabs the lock for 2s.
    lock_path = str(tmp_path / "timeout.lock")
    ready_path = str(tmp_path / "ready.flag")
    result_path = str(tmp_path / "result.txt")
    ctx = multiprocessing.get_context("spawn")
    holder = ctx.Process(target=_hold_lock_worker, args=(lock_path, 2.0, ready_path))
    holder.start()
    try:
        deadline = time.monotonic() + 3.0
        while not Path(ready_path).exists():
            if time.monotonic() >= deadline:
                pytest.fail("holder process never signalled ready")
            time.sleep(0.02)
        # Test action: contender with timeout far shorter than the hold.
        contender = ctx.Process(target=_try_acquire_worker, args=(lock_path, 0.3, result_path))
        start = time.monotonic()
        contender.start()
        contender.join(timeout=5.0)
        elapsed = time.monotonic() - start
        # Test verification: timeout is reported and the elapsed wall time matches the short timeout.
        assert contender.exitcode == 0
        assert Path(result_path).read_text(encoding="utf-8") == "timeout"
        assert 0.25 <= elapsed < 1.5, f"timeout window wrong: {elapsed:.3f}s"
    finally:
        holder.join(timeout=5.0)
        if holder.is_alive():
            holder.terminate()


def test_FileLock_auto_released_when_holder_process_dies(tmp_path: Path) -> None:
    # Scenario: flock auto-releases if holder exits without an explicit release.
    # Setup: holder acquires briefly, then exits cleanly.
    lock_path = str(tmp_path / "autorelease.lock")
    ready_path = str(tmp_path / "ready.flag")
    ctx = multiprocessing.get_context("spawn")
    holder = ctx.Process(target=_hold_lock_worker, args=(lock_path, 0.1, ready_path))
    holder.start()
    holder.join(timeout=5.0)
    # Test action: after holder is reaped, acquire in this process.
    assert holder.exitcode == 0
    lock = FileLock(lock_path, timeout=2.0).acquire()
    # Test verification: lock acquired without timeout.
    try:
        assert lock.acquired is True
    finally:
        lock.release()


# Helper: write a lock file with the given pane id payload.
def _write_lock(debate_dir: Path, stage: str, agent: str, payload: str) -> Path:
    lock = debate_dir / f".{stage}_{agent}.lock"
    lock.write_text(payload)
    return lock


def _write_lock_at_path(lock_path: Path, pane_id: str) -> None:
    """Write a lock file with the canonical debate:<pane_id> format."""
    lock_path.write_text(f"debate:{pane_id}\n")


def _make_lock(dir_path: Path, name: str, pane_id: str | None) -> Path:
    """Create a hidden lock file with optional `debate:<pane_id>` line."""
    lock = dir_path / name
    body = f"debate:{pane_id}\n" if pane_id else ""
    lock.write_text(body, encoding="utf-8")
    return lock


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
