"""RED-YELLOW-GREEN tests for shell_waitForFile.

Generic shell utility (RELAXED_COVERAGE): bash original `wait_for_file`
also performs debate-specific side effects (remove .synthesis_claude.lock,
call write_failed). Those are out of scope for the generic helper; tests
cover only the polling/timeout/return-bool contract.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp_shell_waitForFile import shell_waitForFile


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

    monkeypatch.setattr("_tmp_shell_waitForFile.time.sleep", fake_sleep)
    # Test action: poll with timeout large enough to allow 3 fake sleeps.
    result = shell_waitForFile(str(target), timeout=10, poll_interval=1)
    # Test verification: helper observed the late-arriving file and returned True.
    assert result is True
    assert calls["n"] >= 3
