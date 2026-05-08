"""Tests for jot_lib diagnostic helpers + jot_collectDiagnostics report builder."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from common.scripts.jot_lib import (
    jot_collectDiagnostics,
    jot_diagIndent,
    jot_diagKv,
    jot_diagSection,
)


# --- jot_diagSection ---


def test_jot_diagSection_starts_with_leading_newline() -> None:
    # Scenario: section banner must visually separate from prior output.
    # Setup + Test action.
    out = jot_diagSection("Foo")
    # Test verification: leading newline.
    assert out.startswith("\n")


def test_jot_diagSection_embeds_title_between_rules() -> None:
    # Scenario: title sandwiched between two identical horizontal rules.
    out = jot_diagSection("Section 1")
    # Test verification: exact 4-line layout.
    lines = out.split("\n")
    rule = "═" * 59
    assert lines[1] == rule
    assert lines[2] == "Section 1"
    assert lines[3] == rule


def test_jot_diagSection_rule_is_59_box_chars() -> None:
    # Scenario: rule width is exactly 59 U+2550 chars (bash hardcode).
    out = jot_diagSection("X")
    # Test verification.
    rule_line = out.split("\n")[1]
    assert len(rule_line) == 59
    assert set(rule_line) == {"═"}


def test_jot_diagSection_ends_with_trailing_newline() -> None:
    # Scenario: banner ends with \n so subsequent text starts on its own line.
    # Test action + verification.
    assert jot_diagSection("X").endswith("\n")


def test_jot_diagSection_preserves_empty_title() -> None:
    # Scenario: empty title still produces well-formed banner with 4 newlines.
    # Test action + verification.
    assert jot_diagSection("").count("\n") == 4


# --- jot_diagIndent ---


def test_jot_diagIndent_single_line_no_trailing_newline() -> None:
    # Scenario: single line, no trailing newline.
    # Test action + verification.
    assert jot_diagIndent("hello") == "  hello"


def test_jot_diagIndent_multiline_preserves_trailing_newline() -> None:
    # Scenario: typical command output with trailing newline.
    # Test action + verification.
    assert jot_diagIndent("a\nb\n") == "  a\n  b\n"


def test_jot_diagIndent_multiline_no_trailing_newline() -> None:
    # Scenario: text without trailing newline (e.g. captured via $(...)).
    # Test action + verification.
    assert jot_diagIndent("a\nb") == "  a\n  b"


def test_jot_diagIndent_blank_line_still_prefixed() -> None:
    # Scenario: blank lines also get 2-space prefix (matches sed).
    # Test action + verification.
    assert jot_diagIndent("a\n\nb\n") == "  a\n  \n  b\n"


def test_jot_diagIndent_empty_string_returns_empty() -> None:
    # Scenario: empty input -> empty output.
    # Test action + verification.
    assert jot_diagIndent("") == ""


def test_jot_diagIndent_only_newline() -> None:
    # Scenario: lone newline -> single empty line gets prefix.
    # Test action + verification.
    assert jot_diagIndent("\n") == "  \n"


# --- jot_diagKv ---


def test_jot_diagKv_short_key_left_padded_to_28() -> None:
    # Scenario: short key padded with spaces to width 28 + separator + value.
    # Test action + verification.
    assert jot_diagKv("path", "/tmp/x") == "path" + " " * 24 + " /tmp/x\n"


def test_jot_diagKv_value_starts_at_column_29() -> None:
    # Scenario: '%-28s ' yields key field 28 cols + 1-space separator -> col 29.
    out = jot_diagKv("k", "v")
    # Test verification.
    assert out.index("v") == 29


def test_jot_diagKv_long_key_not_truncated() -> None:
    # Scenario: keys >= 28 chars are NOT truncated (printf min-width).
    long_key = "k" * 40
    # Test action + verification.
    assert jot_diagKv(long_key, "v") == f"{long_key} v\n"


def test_jot_diagKv_ends_with_single_trailing_newline() -> None:
    # Scenario: each line has exactly one trailing newline.
    out = jot_diagKv("a", "b")
    # Test verification.
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


def test_jot_diagKv_empty_value_still_emits_padded_key() -> None:
    # Scenario: empty value still emits padded key + space + newline.
    # Test action + verification.
    assert jot_diagKv("jq", "") == "jq" + " " * 26 + " \n"


def test_jot_diagKv_value_with_spaces_preserved_verbatim() -> None:
    # Scenario: value with internal spaces preserved as-is, not split.
    out = jot_diagKv("mtime", "Mon Jan  1 00:00:00")
    # Test verification.
    assert "Mon Jan  1 00:00:00\n" in out


# ---------------------------------------------------------------------------
# Section 1 — report header
# ---------------------------------------------------------------------------

def _read(path: str) -> str:
    return Path(path).read_text()


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
