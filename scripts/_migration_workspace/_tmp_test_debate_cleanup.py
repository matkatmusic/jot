"""Tests for debate_cleanup (port of cleanup() from jot-plugin-orchestrator.sh).

RED-YELLOW-GREEN TDD. Each test covers one behavior.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _tmp_debate_cleanup import debate_cleanup


# ---------------------------------------------------------------------------
# Test 1 — removes /tmp/debate.* directory
# ---------------------------------------------------------------------------
def test_removes_tmp_debate_dir(tmp_path: Path) -> None:
    # Scenario: settings_file lives inside a /tmp/debate.XYZ directory.
    # Setup: create a mock /tmp/debate.XYZ tree under tmp_path (so we don't
    #   touch real /tmp). We monkey-patch by creating the structure locally
    #   and passing the fake path; the guard checks parent.name == "debate.*"
    #   and parent.parent == Path("/tmp"). We build the fake tree and
    #   temporarily repoint by using a symlink trick — actually, the function
    #   checks Path("/tmp") literally, so we directly fabricate a path string
    #   with a real /tmp/debate.* dir to exercise it.
    import tempfile, shutil, os

    # Create a real /tmp/debate.<unique> directory
    debate_dir = Path(tempfile.mkdtemp(prefix="debate.", dir="/tmp"))
    settings_file = debate_dir / "settings.json"
    settings_file.write_text("{}")

    try:
        # Test action:
        debate_cleanup(settings_file)

        # Test verification: directory must be gone
        assert not debate_dir.exists(), f"Expected {debate_dir} to be removed"
    finally:
        # Safety: clean up if test failed before removal
        if debate_dir.exists():
            shutil.rmtree(debate_dir)


# ---------------------------------------------------------------------------
# Test 2 — does NOT remove a non-/tmp/debate.* directory
# ---------------------------------------------------------------------------
def test_ignores_non_tmp_debate_dir(tmp_path: Path) -> None:
    # Scenario: settings_file is in a user project dir, not /tmp/debate.*.
    # Setup:
    settings_dir = tmp_path / "my_project_settings"
    settings_dir.mkdir()
    settings_file = settings_dir / "settings.json"
    settings_file.write_text("{}")

    # Test action:
    debate_cleanup(settings_file)

    # Test verification: directory must still exist
    assert settings_dir.exists(), "Non-/tmp/debate.* dir must not be removed"


# ---------------------------------------------------------------------------
# Test 3 — does NOT remove /tmp directory that does not start with "debate."
# ---------------------------------------------------------------------------
def test_ignores_tmp_non_debate_prefix(tmp_path: Path) -> None:
    # Scenario: settings_file is in /tmp/somethingelse (no "debate." prefix).
    # Setup:
    import tempfile, shutil

    other_dir = Path(tempfile.mkdtemp(prefix="notdebate.", dir="/tmp"))
    settings_file = other_dir / "settings.json"
    settings_file.write_text("{}")

    try:
        # Test action:
        debate_cleanup(settings_file)

        # Test verification: directory must still exist
        assert other_dir.exists(), "Non-debate-prefixed /tmp dir must not be removed"
    finally:
        if other_dir.exists():
            shutil.rmtree(other_dir)


# ---------------------------------------------------------------------------
# Test 4 — no-op when debate dir does not exist (already cleaned up)
# ---------------------------------------------------------------------------
def test_noop_when_dir_already_gone() -> None:
    # Scenario: cleanup called twice; second call should not raise.
    # Setup: fabricate a path that looks like /tmp/debate.XYZ but doesn't exist
    nonexistent = Path("/tmp/debate.already_deleted_abc123/settings.json")
    assert not nonexistent.parent.exists(), "Precondition: dir must not exist"

    # Test action + Test verification: must not raise
    debate_cleanup(nonexistent)


# ---------------------------------------------------------------------------
# Test 5 — accepts str path (not just Path)
# ---------------------------------------------------------------------------
def test_accepts_str_path(tmp_path: Path) -> None:
    # Scenario: caller passes a plain str instead of a Path object.
    # Setup:
    import tempfile, shutil

    debate_dir = Path(tempfile.mkdtemp(prefix="debate.", dir="/tmp"))
    settings_file = str(debate_dir / "settings.json")
    (debate_dir / "settings.json").write_text("{}")

    try:
        # Test action:
        debate_cleanup(settings_file)

        # Test verification:
        assert not debate_dir.exists()
    finally:
        if debate_dir.exists():
            shutil.rmtree(debate_dir)
