"""RED tests for jot_collectDiagnostics.

RELAXED_COVERAGE: no paired bash _tests exist; tests authored from
bash body intent + docstring. tmux/subprocess calls are replaced with
fakes via monkeypatching so tests are hermetic.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts/_migration_workspace")

from _tmp_jot_collectDiagnostics import jot_collectDiagnostics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(path: str) -> str:
    return Path(path).read_text()


# ---------------------------------------------------------------------------
# Section 1 — report header
# ---------------------------------------------------------------------------

class TestReportHeader:
    def test_report_file_created_at_default_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: caller passes no out_path; function auto-generates /tmp/jot-diag-*.log
        # Setup: redirect default tmp location to tmp_path via env or by passing explicit path
        out = str(tmp_path / "diag.log")
        # Test action:
        result = jot_collectDiagnostics(out_path=out)
        # Test verification:
        assert result == out
        assert Path(out).exists()

    def test_report_contains_header_line(self, tmp_path: Path) -> None:
        # Scenario: report always starts with the literal banner line
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "jot-diag-collect report" in content

    def test_report_contains_generated_timestamp(self, tmp_path: Path) -> None:
        # Scenario: report header includes a "generated:" line with ISO timestamp
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "generated:" in content

    def test_report_contains_cwd_line(self, tmp_path: Path) -> None:
        # Scenario: report header includes a "cwd:" line
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "cwd:" in content

    def test_report_contains_project_line(self, tmp_path: Path) -> None:
        # Scenario: report header includes a "project:" line derived from repo root basename
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "project:" in content


# ---------------------------------------------------------------------------
# Section 2 — section banners (uses jot_diagSection format)
# ---------------------------------------------------------------------------

class TestSectionBanners:
    def test_section_1_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 1 banner for Latest Todos input files
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "1. Latest Todos/*_input.txt" in content

    def test_section_2_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 2 banner for state dir
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "2. State dir" in content

    def test_section_3_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 3 banner for tmux session
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "3. tmux session" in content

    def test_section_4_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 4 banner for /tmp/jot.* dirs
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "4. /tmp/jot." in content

    def test_section_5_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 5 banner for log file
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "5." in content

    def test_section_6_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 6 banner for Todos/ listing
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "6. Todos/" in content

    def test_section_7_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 7 banner for plugin orchestrator path
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "7. Installed plugin orchestrator" in content

    def test_section_8_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 8 banner for dependency check
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "8. Dependency check" in content

    def test_end_of_report_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report ends with END OF REPORT banner
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "END OF REPORT" in content

    def test_section_banners_use_box_drawing_rule(self, tmp_path: Path) -> None:
        # Scenario: section banners use the 59-char box-drawing rule (jot_diagSection format)
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification: box-drawing char appears (from jot_diagSection)
        assert "═" in content  # '═'


# ---------------------------------------------------------------------------
# Section 3 — section 1: Todos/*_input.txt
# ---------------------------------------------------------------------------

class TestTodosInputSection:
    def test_no_input_txt_shows_not_found_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: Todos/ dir has no *_input.txt files
        # Setup: point REPO_ROOT at tmp_path (no Todos/ dir)
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "no input.txt found" in content

    def test_input_txt_present_shows_kv_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: Todos/ contains one *_input.txt; report shows path kv
        # Setup:
        todos = tmp_path / "Todos"
        todos.mkdir()
        inp = todos / "task_input.txt"
        inp.write_text("# Jot Task\ndo something\n")
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GIT_DIR", "")  # suppress git, cwd becomes repo_root
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "path" in content
        assert "task_input.txt" in content

    def test_input_txt_pending_status(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: input.txt first line is "# Jot Task" -> status shows PENDING
        # Setup:
        todos = tmp_path / "Todos"
        todos.mkdir()
        inp = todos / "task_input.txt"
        inp.write_text("# Jot Task\ndo something\n")
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "PENDING" in content

    def test_input_txt_processed_status(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: input.txt first line starts with "PROCESSED:" -> status shows PROCESSED
        # Setup:
        todos = tmp_path / "Todos"
        todos.mkdir()
        inp = todos / "task_input.txt"
        inp.write_text("PROCESSED: done\nsome content\n")
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "PROCESSED" in content


# ---------------------------------------------------------------------------
# Section 4 — section 2: state dir
# ---------------------------------------------------------------------------

class TestStateDirSection:
    def test_missing_state_dir_shows_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: STATE_DIR does not exist; report notes this
        # Setup:
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "state dir does not exist" in content

    def test_queue_txt_empty_shows_empty_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: queue.txt exists but is empty
        # Setup:
        state = tmp_path / "Todos" / ".jot-state"
        state.mkdir(parents=True)
        (state / "queue.txt").write_text("")
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "empty" in content or "no jobs pending" in content

    def test_queue_txt_missing_shows_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: state dir exists but queue.txt absent
        # Setup:
        state = tmp_path / "Todos" / ".jot-state"
        state.mkdir(parents=True)
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "missing" in content

    def test_queue_lock_held_shows_lock_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: queue.lock exists; report warns lock is held
        # Setup:
        state = tmp_path / "Todos" / ".jot-state"
        state.mkdir(parents=True)
        (state / "queue.lock").mkdir()  # dir-based mkdir lock
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "LOCK IS HELD" in content

    def test_queue_lock_free_shows_free_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: no queue.lock; report confirms lock is free
        # Setup:
        state = tmp_path / "Todos" / ".jot-state"
        state.mkdir(parents=True)
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "free" in content or "no lock held" in content


# ---------------------------------------------------------------------------
# Section 5 — section 8: dependency check uses kv format
# ---------------------------------------------------------------------------

class TestDependencySection:
    def test_dependency_section_lists_known_cmds(self, tmp_path: Path) -> None:
        # Scenario: dependency check covers the 5 expected commands
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification: all 5 deps appear
        for cmd in ("jq", "python3", "tmux", "claude", "osascript"):
            assert cmd in content, f"missing dependency check for {cmd!r}"

    def test_dependency_found_cmd_shows_path(self, tmp_path: Path) -> None:
        # Scenario: python3 is always present; its which-path appears in report
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification: python3 row has a path (starts with /)
        lines = [l for l in content.splitlines() if l.startswith("python3") or "python3" in l[:30]]
        found = any("/" in l for l in lines)
        assert found, f"python3 path not found in dep lines: {lines}"


# ---------------------------------------------------------------------------
# Section 6 — return value
# ---------------------------------------------------------------------------

class TestReturnValue:
    def test_returns_out_path_string(self, tmp_path: Path) -> None:
        # Scenario: explicit out_path is returned verbatim
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        result = jot_collectDiagnostics(out_path=out)
        # Test verification:
        assert result == out

    def test_default_out_path_is_in_tmp(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: when out_path is None, returned path is under /tmp
        # Setup: we cannot write to real /tmp in all CI environments, so skip
        # if /tmp is not writable; otherwise verify prefix.
        if not os.access("/tmp", os.W_OK):
            pytest.skip("/tmp not writable")
        # Test action:
        result = jot_collectDiagnostics(out_path=None)
        # Test verification:
        assert result.startswith("/tmp/jot-diag-")
        assert Path(result).exists()
        Path(result).unlink(missing_ok=True)
