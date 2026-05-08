from __future__ import annotations

from unittest.mock import MagicMock, patch

from common.scripts.plate_dispatcher import plate_summaryStop


def test_missing_repo_arg_is_noop(tmp_path):
    # Scenario: hook invoked without REPO arg returns early without side effects.
    # Setup: empty repo/branch; valid output_file path that exists.
    out = tmp_path / "summary.txt"
    out.write_text("body")
    with patch("common.scripts.plate_dispatcher.subprocess.run") as run:
        # Test action:
        rc = plate_summaryStop("", "main", str(out))
        # Test verification: cli.py never invoked when args missing.
        assert rc == 0
        run.assert_not_called()


def test_missing_branch_arg_is_noop(tmp_path):
    # Scenario: empty branch arg short-circuits.
    # Setup: valid repo, empty branch, existing output file.
    out = tmp_path / "summary.txt"
    out.write_text("body")
    with patch("common.scripts.plate_dispatcher.subprocess.run") as run:
        # Test action:
        rc = plate_summaryStop(str(tmp_path), "", str(out))
        # Test verification:
        assert rc == 0
        run.assert_not_called()


def test_missing_output_file_arg_is_noop(tmp_path):
    # Scenario: empty output_file arg short-circuits.
    # Setup: valid repo, valid branch, empty output_file.
    with patch("common.scripts.plate_dispatcher.subprocess.run") as run:
        # Test action:
        rc = plate_summaryStop(str(tmp_path), "main", "")
        # Test verification:
        assert rc == 0
        run.assert_not_called()


def test_nonexistent_output_file_is_noop(tmp_path):
    # Scenario: output_file does not exist on disk -> early exit, no cli call.
    # Setup: a path that points nowhere.
    missing = tmp_path / "nope.txt"
    with patch("common.scripts.plate_dispatcher.subprocess.run") as run:
        # Test action:
        rc = plate_summaryStop(str(tmp_path), "main", str(missing))
        # Test verification:
        assert rc == 0
        run.assert_not_called()


def test_invokes_cli_set_plate_summary_with_args(tmp_path):
    # Scenario: happy path forwards repo/branch/output_file to cli.py set-plate-summary.
    # Setup: existing repo dir + output file; capture subprocess.run call.
    out = tmp_path / "summary.txt"
    out.write_text("agent summary")
    with patch("common.scripts.plate_dispatcher.subprocess.run") as run:
        run.return_value = MagicMock(stdout="ok\n", returncode=0)
        # Test action:
        rc = plate_summaryStop(str(tmp_path), "feature-x", str(out))
        # Test verification: cli.py invoked with the three positional args.
        assert rc == 0
        assert run.called
        argv = run.call_args[0][0]
        assert "set-plate-summary" in argv
        assert str(tmp_path) in argv
        assert "feature-x" in argv
        assert str(out) in argv


def test_writes_audit_log_line(tmp_path, monkeypatch):
    # Scenario: every invocation appends one line to the plate-log.txt.
    # Setup: PLATE_LOG_FILE env var points at a writable file under tmp_path.
    log = tmp_path / "plate-log.txt"
    monkeypatch.setenv("PLATE_LOG_FILE", str(log))
    out = tmp_path / "summary.txt"
    out.write_text("body")
    with patch("common.scripts.plate_dispatcher.subprocess.run") as run:
        run.return_value = MagicMock(stdout="ok", returncode=0)
        # Test action:
        plate_summaryStop(str(tmp_path), "main", str(out))
    # Test verification: log file exists and contains the marker substring.
    assert log.exists()
    text = log.read_text()
    assert "plate-summary-stop" in text
    assert "main" in text


def test_cli_failure_is_swallowed(tmp_path, monkeypatch):
    # Scenario: cli.py crashes -> hook still returns 0 (never block shutdown).
    # Setup: subprocess.run raises CalledProcessError-like exception.
    log = tmp_path / "plate-log.txt"
    monkeypatch.setenv("PLATE_LOG_FILE", str(log))
    out = tmp_path / "summary.txt"
    out.write_text("body")
    with patch("common.scripts.plate_dispatcher.subprocess.run") as run:
        run.side_effect = RuntimeError("boom")
        # Test action: must not raise.
        rc = plate_summaryStop(str(tmp_path), "main", str(out))
        # Test verification: returns 0 regardless of subprocess failure.
        assert rc == 0
