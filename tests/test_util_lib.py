from __future__ import annotations

import signal
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from common.scripts.debate_lib import (
    debate_launch,
    debate_main,
    debate_writeFailed,
)
from common.scripts.tmux_lib import (
    tmux_capturePane,
    tmux_sendAndSubmit,
)
from common.scripts.util_lib import (
    FileLock,
    LockTimeout,
    shell_runWithTimeout,
    shell_waitForFile,
    terminal_spawnIfNeeded,
)


# --- shell_runWithTimeout ---


@pytest.mark.live
def test_shell_runWithTimeout_returns_zero_for_successful_fast_command():
    # Scenario: command exits 0 within budget; rc=0.
    # Setup: /usr/bin/true with generous timeout.
    # Test action + verification.
    assert shell_runWithTimeout(5, ["true"]) == 0


@pytest.mark.live
def test_shell_runWithTimeout_returns_nonzero_for_failing_fast_command():
    # Scenario: command exits non-zero before timeout.
    # Test action + verification.
    rc = shell_runWithTimeout(5, ["false"])
    assert rc == 1


@pytest.mark.live
def test_shell_runWithTimeout_kills_command_that_exceeds_timeout():
    # Scenario: sleep 10 with 1s budget; expect kill within ~3s wall-clock.
    import time as _t
    start = _t.monotonic()
    # Test action.
    rc = shell_runWithTimeout(1, ["sleep", "10"])
    elapsed = _t.monotonic() - start
    # Test verification: returned well before 10s and rc nonzero.
    assert elapsed < 5.0
    assert rc != 0


@pytest.mark.live
def test_shell_runWithTimeout_returns_promptly_when_command_finishes_early():
    # Scenario: fast command must not block on the timeout.
    import time as _t
    start = _t.monotonic()
    # Test action.
    rc = shell_runWithTimeout(30, ["true"])
    elapsed = _t.monotonic() - start
    # Test verification.
    assert rc == 0
    assert elapsed < 3.0


@pytest.mark.live
def test_shell_runWithTimeout_kills_process_that_ignores_sigterm():
    # Scenario: child traps SIGTERM (mirrors gemini); SIGKILL escalation must occur.
    import time as _t
    import sys as _sys
    argv = [
        _sys.executable,
        "-c",
        "import signal, time;"
        "signal.signal(signal.SIGTERM, lambda *a: None);"
        "time.sleep(30)",
    ]
    start = _t.monotonic()
    # Test action.
    rc = shell_runWithTimeout(1, argv)
    elapsed = _t.monotonic() - start
    # Test verification: returned within a few seconds via SIGKILL.
    assert elapsed < 6.0
    assert rc != 0

# --- terminal_spawnIfNeeded ---

def test_terminal_spawnIfNeeded_empty_session_raises_value_error():
    # Scenario: caller forgets the required session arg.
    # Test action + verification: ValueError surfaces.
    with pytest.raises(ValueError):
        terminal_spawnIfNeeded("")


def test_terminal_spawnIfNeeded_skips_spawn_when_clients_attached():
    # Scenario: tmux session already has an attached client.
    # Setup: stub tmux list to return a non-empty client line.
    with patch.object(jot_plugin_orchestrator, "_terminalListTmuxClients", return_value="/dev/ttys001 ...\n"), \
         patch.object(jot_plugin_orchestrator.subprocess, "Popen") as popen, \
         patch.object(jot_plugin_orchestrator.sys, "platform", "darwin"):
        # Test action: call function on darwin.
        rc = terminal_spawnIfNeeded("sess1")
    # Test verification: osascript is not spawned and success is returned.
    assert rc == 0
    popen.assert_not_called()


def test_terminal_spawnIfNeeded_darwin_spawns_osascript_with_attach_command():
    # Scenario: no clients attached, osascript present, darwin host.
    # Setup: stub list_clients empty, which() finds osascript, mock Popen.
    fake_proc = MagicMock()
    fake_proc.communicate.return_value = (b"", b"")
    with patch.object(jot_plugin_orchestrator, "_terminalListTmuxClients", return_value=""), \
         patch.object(jot_plugin_orchestrator.shutil, "which", return_value="/usr/bin/osascript"), \
         patch.object(jot_plugin_orchestrator.sys, "platform", "darwin"), \
         patch.object(jot_plugin_orchestrator.subprocess, "Popen", return_value=fake_proc) as popen:
        # Test action: call with default maximize="".
        rc = terminal_spawnIfNeeded("mySess")
    # Test verification: Popen called with osascript; script contains attach command and no maximize block.
    assert rc == 0
    args, _kwargs = popen.call_args
    assert args[0] == ["osascript"]
    sent = fake_proc.communicate.call_args.kwargs["input"].decode("utf-8")
    assert "tmux attach -t mySess" in sent
    assert "set bounds of front window" not in sent


def test_terminal_spawnIfNeeded_darwin_maximize_yes_includes_full_desktop_block():
    # Scenario: caller requests maximize="yes" for a large pane layout.
    # Setup: use darwin happy-path stubs.
    fake_proc = MagicMock()
    fake_proc.communicate.return_value = (b"", b"")
    with patch.object(jot_plugin_orchestrator, "_terminalListTmuxClients", return_value=""), \
         patch.object(jot_plugin_orchestrator.shutil, "which", return_value="/x/osascript"), \
         patch.object(jot_plugin_orchestrator.sys, "platform", "darwin"), \
         patch.object(jot_plugin_orchestrator.subprocess, "Popen", return_value=fake_proc):
        # Test action: invoke with maximize="yes".
        terminal_spawnIfNeeded("s", "/dev/null", "tmux", "yes")
    # Test verification: AppleScript stdin contains full-screen bounds assignment.
    sent = fake_proc.communicate.call_args.kwargs["input"].decode("utf-8")
    assert "set bounds of front window to screenBounds" in sent
    assert "winW to 1000" not in sent


def test_terminal_spawnIfNeeded_darwin_maximize_compact_includes_centred_1000x700_block():
    # Scenario: caller requests compact geometry for a single-pane spawner.
    # Setup: use darwin happy-path stubs.
    fake_proc = MagicMock()
    fake_proc.communicate.return_value = (b"", b"")
    with patch.object(jot_plugin_orchestrator, "_terminalListTmuxClients", return_value=""), \
         patch.object(jot_plugin_orchestrator.shutil, "which", return_value="/x/osascript"), \
         patch.object(jot_plugin_orchestrator.sys, "platform", "darwin"), \
         patch.object(jot_plugin_orchestrator.subprocess, "Popen", return_value=fake_proc):
        # Test action: invoke with maximize="compact".
        terminal_spawnIfNeeded("s", "/dev/null", "tmux", "compact")
    # Test verification: stdin includes 1000x700 centering math.
    sent = fake_proc.communicate.call_args.kwargs["input"].decode("utf-8")
    assert "winW to 1000" in sent
    assert "winH to 700" in sent


def test_terminal_spawnIfNeeded_darwin_missing_osascript_writes_advisory_and_returns_zero(tmp_path):
    # Scenario: darwin host but osascript binary is not on PATH.
    # Setup: which() returns None; real tmp log file.
    log = tmp_path / "spawn.log"
    with patch.object(jot_plugin_orchestrator, "_terminalListTmuxClients", return_value=""), \
         patch.object(jot_plugin_orchestrator.shutil, "which", return_value=None), \
         patch.object(jot_plugin_orchestrator.sys, "platform", "darwin"), \
         patch.object(jot_plugin_orchestrator.subprocess, "Popen") as popen:
        # Test action: invoke with log_file pointing at tmp file.
        rc = terminal_spawnIfNeeded("abc", str(log), "myprefix")
    # Test verification: Popen never called, advisory line appended.
    assert rc == 0
    popen.assert_not_called()
    text = log.read_text()
    assert "myprefix: osascript unavailable" in text
    assert "tmux attach -t abc" in text


def test_terminal_spawnIfNeeded_non_darwin_writes_advisory_and_does_not_spawn(tmp_path):
    # Scenario: linux host invokes the spawner.
    # Setup: sys.platform stubbed to linux; real tmp log file.
    log = tmp_path / "spawn.log"
    with patch.object(jot_plugin_orchestrator, "_terminalListTmuxClients", return_value=""), \
         patch.object(jot_plugin_orchestrator.sys, "platform", "linux"), \
         patch.object(jot_plugin_orchestrator.subprocess, "Popen") as popen:
        # Test action: invoke with custom log_prefix.
        rc = terminal_spawnIfNeeded("zzz", str(log), "plate")
    # Test verification: Popen never called, advisory contains non-Darwin.
    assert rc == 0
    popen.assert_not_called()
    text = log.read_text()
    assert "plate: non-Darwin host" in text
    assert "tmux attach -t zzz" in text


def test_terminal_spawnIfNeeded_dev_null_log_does_not_create_file(tmp_path, monkeypatch):
    # Scenario: caller passes default /dev/null log on non-darwin.
    # Setup: cwd switched to tmp_path so any accidental write would land here.
    monkeypatch.chdir(tmp_path)
    with patch.object(jot_plugin_orchestrator, "_terminalListTmuxClients", return_value=""), \
         patch.object(jot_plugin_orchestrator.sys, "platform", "linux"):
        # Test action: invoke with log_file="/dev/null".
        rc = terminal_spawnIfNeeded("s", "/dev/null", "tmux")
    # Test verification: no spurious files created in cwd; rc 0.
    assert rc == 0
    assert list(tmp_path.iterdir()) == []


def test_terminal_spawnIfNeeded_advisory_write_failure_is_swallowed():
    # Scenario: log file path is unwritable.
    # Setup: monkeypatch open() to raise OSError.
    with patch.object(jot_plugin_orchestrator, "_terminalListTmuxClients", return_value=""), \
         patch.object(jot_plugin_orchestrator.sys, "platform", "linux"), \
         patch("builtins.open", side_effect=OSError("EACCES")):
        # Test action + verification: function returns 0, no exception escapes.
        assert terminal_spawnIfNeeded("s", "/some/real/path.log", "tmux") == 0



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



# ===========================================================================
# 2. Darwin + Terminal NOT running -> launches Terminal then calls debate_main
# ===========================================================================

def test_darwin_terminal_not_running_launches_terminal() -> None:
    # Scenario: on Darwin, when Terminal is not running, osascript is invoked.
    # Setup:
    main_mock = _make_main_mock()
    launch_mock = MagicMock()
    terminal_running = lambda: False
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=Path("/fake/plugin"),
        _debate_main_fn=main_mock,
        _is_darwin=True,
        _terminal_running_fn=terminal_running,
        _launch_terminal_fn=launch_mock,
    )
    # Test verification:
    launch_mock.assert_called_once_with()
    main_mock.assert_called_once_with()


# ===========================================================================
# 3. Darwin + Terminal already running -> skips launch
# ===========================================================================

def test_darwin_terminal_already_running_skips_launch() -> None:
    # Scenario: on Darwin, when Terminal is already running, do NOT launch it.
    # Setup:
    main_mock = _make_main_mock()
    launch_mock = MagicMock()
    terminal_running = lambda: True
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=Path("/fake/plugin"),
        _debate_main_fn=main_mock,
        _is_darwin=True,
        _terminal_running_fn=terminal_running,
        _launch_terminal_fn=launch_mock,
    )
    # Test verification:
    launch_mock.assert_not_called()
    main_mock.assert_called_once_with()


# ===========================================================================
# 4. Non-Darwin -> never launches Terminal regardless of pgrep result
# ===========================================================================

def test_non_darwin_never_launches_terminal() -> None:
    # Scenario: on non-Darwin (Linux/CI), Terminal.app guard is skipped entirely.
    # Setup:
    main_mock = _make_main_mock()
    launch_mock = MagicMock()
    terminal_running_mock = MagicMock(return_value=False)
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=Path("/fake/plugin"),
        _debate_main_fn=main_mock,
        _is_darwin=False,
        _terminal_running_fn=terminal_running_mock,
        _launch_terminal_fn=launch_mock,
    )
    # Test verification:
    terminal_running_mock.assert_not_called()
    launch_mock.assert_not_called()
    main_mock.assert_called_once_with()


def _noop() -> None:
    pass


def _make_main_mock() -> MagicMock:
    return MagicMock(return_value=None)

# ===========================================================================
# 6. Terminal launch is fire-and-forget (does NOT block debate_main)
# ===========================================================================

def test_terminal_launch_before_debate_main() -> None:
    # Scenario: Terminal is launched BEFORE debate_main is called (ordering).
    # Setup:
    call_order: list[str] = []
    main_mock = MagicMock(side_effect=lambda: call_order.append("main"))
    launch_mock = MagicMock(side_effect=lambda: call_order.append("launch"))
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=Path("/fake/plugin"),
        _debate_main_fn=main_mock,
        _is_darwin=True,
        _terminal_running_fn=lambda: False,
        _launch_terminal_fn=launch_mock,
    )
    # Test verification:
    assert call_order == ["launch", "main"], (
        f"Expected launch before main, got: {call_order}"
    )


def _patch_all(
    pane_content: str = "",
    *,
    ready_after: int | None = 0,
):
    """Return a context-manager stack that patches all I/O callees.

    ready_after: iteration index (0-based) at which pane shows the ready marker.
                 None => never shows ready (simulate timeout).
    """
    captured_lines: list[str] = []
    call_count = 0

    def fake_capture(pane_id, scrollback_lines=2000):
        nonlocal call_count
        result = _READY if (ready_after is not None and call_count >= ready_after) else ""
        call_count += 1
        return result

    return (
        patch("jot_plugin_orchestrator.tmux_sendAndSubmit"),
        patch("jot_plugin_orchestrator.tmux_capturePane", side_effect=fake_capture),
        patch("jot_plugin_orchestrator.debate_writeFailed"),
        patch("jot_plugin_orchestrator.time_sleep"),
    )


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





def test_returns_true_when_file_already_nonempty(tmp_path):
    # Scenario: target file already has content before polling begins.
    # Setup: create a non-empty file in tmp_path.
    target = tmp_path / "synthesis.md"
    target.write_text("done")
    # Test action: invoke shell_waitForFile with a 5s timeout.
    result = shell_waitForFile(str(target), timeout=5, poll_interval=0.01)
    # Test verification: returns True (success) without sleeping out the timeout.
    assert result is True


def test_returns_false_when_file_never_appears(tmp_path):
    # Scenario: target file never exists; helper must time out.
    # Setup: tmp_path is empty; build a path that will never be created.
    target = tmp_path / "missing.md"
    # Test action: poll for it with a tiny timeout/interval to keep test fast.
    result = shell_waitForFile(str(target), timeout=0.05, poll_interval=0.01)
    # Test verification: returns False indicating timeout.
    assert result is False


def test_returns_false_when_file_exists_but_empty(tmp_path):
    # Scenario: bash uses `[ -s ]` (non-empty) so empty files do NOT satisfy.
    # Setup: create a zero-byte file.
    target = tmp_path / "empty.md"
    target.touch()
    # Test action: poll until short timeout.
    result = shell_waitForFile(str(target), timeout=0.05, poll_interval=0.01)
    # Test verification: empty file is treated as "not yet ready"; returns False.
    assert result is False


def test_returns_true_when_file_appears_during_polling(tmp_path, monkeypatch):
    # Scenario: file is written after several poll iterations.
    # Setup: counter-driven fake sleep that creates the file on the 3rd call.
    target = tmp_path / "late.md"
    calls = {"n": 0}

    def fake_sleep(_seconds):
        calls["n"] += 1
        if calls["n"] == 3:
            target.write_text("ready")

    monkeypatch.setattr("jot_plugin_orchestrator.time.sleep", fake_sleep)
    # Test action: poll with timeout large enough to allow 3 fake sleeps.
    result = shell_waitForFile(str(target), timeout=10, poll_interval=1)
    # Test verification: helper observed the late-arriving file and returned True.
    assert result is True
    assert calls["n"] >= 3

def _read(path: str) -> str:
    return Path(path).read_text()



def _write(p: Path, content: str = "x") -> None:
    p.write_text(content)



