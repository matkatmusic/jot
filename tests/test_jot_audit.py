"""Tests for jot_lib audit-log rotation (jot_rotateAudit)."""
from __future__ import annotations

from pathlib import Path

from common.scripts.jot_lib import jot_rotateAudit


# --- jot_rotateAudit ---


def test_jot_rotateAudit_silent_noop_when_file_missing(tmp_path: Path) -> None:
    # Scenario: audit log file does not exist; rotate is a silent no-op.
    # Setup: path that is not created.
    missing = tmp_path / "audit.log"
    # Test action.
    result = jot_rotateAudit(str(missing))
    # Test verification.
    assert result is None
    assert not missing.exists()


def test_jot_rotateAudit_leaves_short_file_untouched(tmp_path: Path) -> None:
    # Scenario: log under threshold must not be modified.
    # Setup: 50 lines, default max=1000.
    audit = tmp_path / "audit.log"
    original = "\n".join(f"line{i}" for i in range(50)) + "\n"
    audit.write_text(original)
    # Test action.
    jot_rotateAudit(str(audit))
    # Test verification.
    assert audit.read_text() == original


def test_jot_rotateAudit_truncates_to_last_max_lines_when_oversized(tmp_path: Path) -> None:
    # Scenario: log exceeds max_lines; only the tail is kept.
    # Setup: 1500 lines, default max=1000.
    audit = tmp_path / "audit.log"
    audit.write_text("\n".join(f"line{i}" for i in range(1500)) + "\n")
    # Test action.
    jot_rotateAudit(str(audit))
    # Test verification.
    kept = audit.read_text().splitlines()
    assert len(kept) == 1000
    assert kept[0] == "line500"
    assert kept[-1] == "line1499"


def test_jot_rotateAudit_respects_custom_max_lines(tmp_path: Path) -> None:
    # Scenario: caller-supplied max_lines overrides default.
    # Setup: 20 lines, max=5.
    audit = tmp_path / "audit.log"
    audit.write_text("\n".join(f"l{i}" for i in range(20)) + "\n")
    # Test action.
    jot_rotateAudit(str(audit), 5)
    # Test verification.
    assert audit.read_text().splitlines() == ["l15", "l16", "l17", "l18", "l19"]


def test_jot_rotateAudit_no_trim_sidecar_left_behind(tmp_path: Path) -> None:
    # Scenario: rotation must not leave .trim sidecar in directory.
    # Setup: oversized log forcing rotation.
    audit = tmp_path / "audit.log"
    audit.write_text("\n".join(f"x{i}" for i in range(2000)) + "\n")
    # Test action.
    jot_rotateAudit(str(audit), 100)
    # Test verification: only audit.log present.
    siblings = sorted(p.name for p in tmp_path.iterdir())
    assert siblings == ["audit.log"]
