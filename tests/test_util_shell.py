from __future__ import annotations

from pathlib import Path

import pytest

from common.scripts.util_lib import (
    shell_runWithTimeout,
    shell_waitForFile,
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


# --- shell_waitForFile ---


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

    monkeypatch.setattr("time.sleep", fake_sleep)
    # Test action: poll with timeout large enough to allow 3 fake sleeps.
    result = shell_waitForFile(str(target), timeout=10, poll_interval=1)
    # Test verification: helper observed the late-arriving file and returned True.
    assert result is True
    assert calls["n"] >= 3


def _read(path: str) -> str:
    return Path(path).read_text()


def _write(p: Path, content: str = "x") -> None:
    p.write_text(content)
