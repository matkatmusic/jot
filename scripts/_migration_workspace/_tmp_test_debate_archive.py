"""RED-YELLOW-GREEN tests for debate_archive (migrated from bash archive_debate).

Bash source: scripts/jot-plugin-orchestrator.sh lines 2999-3015.
NOTE: no paired bash _tests existed; tests authored from intent + docstring.
RELAXED_COVERAGE: behavior derived from inspection of bash body.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from _tmp_debate_archive import debate_archive


def test_creates_archive_subdirectory(tmp_path: Path) -> None:
    # Scenario: debate_archive must create the archive/ subdirectory under DEBATE_DIR.
    # Setup: empty debate dir with no intermediate files.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    # Test action: invoke debate_archive on the empty dir.
    debate_archive(debate_dir)
    # Test verification: archive subdir now exists.
    assert (debate_dir / "archive").is_dir()


def test_moves_context_md_into_archive(tmp_path: Path) -> None:
    # Scenario: context.md at debate root must be relocated into archive/.
    # Setup: write a context.md with known content.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    src = debate_dir / "context.md"
    src.write_text("CTX")
    # Test action: archive.
    debate_archive(debate_dir)
    # Test verification: source removed; destination present with same content.
    assert not src.exists()
    moved = debate_dir / "archive" / "context.md"
    assert moved.is_file()
    assert moved.read_text() == "CTX"


def test_moves_synthesis_instructions_txt(tmp_path: Path) -> None:
    # Scenario: synthesis_instructions.txt must be archived.
    # Setup: create file at debate root.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "synthesis_instructions.txt").write_text("SI")
    # Test action.
    debate_archive(debate_dir)
    # Test verification.
    assert not (debate_dir / "synthesis_instructions.txt").exists()
    assert (debate_dir / "archive" / "synthesis_instructions.txt").read_text() == "SI"


def test_moves_r1_instructions_glob(tmp_path: Path) -> None:
    # Scenario: r1_instructions_*.txt files must be archived (glob pattern).
    # Setup: two r1 instruction files for different agents.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "r1_instructions_gemini.txt").write_text("g")
    (debate_dir / "r1_instructions_claude.txt").write_text("c")
    # Test action.
    debate_archive(debate_dir)
    # Test verification: both moved into archive/.
    assert not (debate_dir / "r1_instructions_gemini.txt").exists()
    assert not (debate_dir / "r1_instructions_claude.txt").exists()
    assert (debate_dir / "archive" / "r1_instructions_gemini.txt").read_text() == "g"
    assert (debate_dir / "archive" / "r1_instructions_claude.txt").read_text() == "c"


def test_moves_r1_output_md_glob(tmp_path: Path) -> None:
    # Scenario: r1_*.md round-1 outputs must be archived.
    # Setup: per-agent r1 outputs.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "r1_gemini.md").write_text("R1G")
    (debate_dir / "r1_codex.md").write_text("R1C")
    # Test action.
    debate_archive(debate_dir)
    # Test verification.
    assert (debate_dir / "archive" / "r1_gemini.md").read_text() == "R1G"
    assert (debate_dir / "archive" / "r1_codex.md").read_text() == "R1C"
    assert not (debate_dir / "r1_gemini.md").exists()


def test_moves_r2_instructions_and_outputs_glob(tmp_path: Path) -> None:
    # Scenario: r2_instructions_*.txt and r2_*.md must both be archived.
    # Setup.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "r2_instructions_gemini.txt").write_text("i")
    (debate_dir / "r2_gemini.md").write_text("o")
    # Test action.
    debate_archive(debate_dir)
    # Test verification.
    assert (debate_dir / "archive" / "r2_instructions_gemini.txt").is_file()
    assert (debate_dir / "archive" / "r2_gemini.md").is_file()


def test_moves_orchestrator_log_when_present(tmp_path: Path) -> None:
    # Scenario: orchestrator.log handled by separate clause; must move when present.
    # Setup.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "orchestrator.log").write_text("LOG")
    # Test action.
    debate_archive(debate_dir)
    # Test verification.
    assert not (debate_dir / "orchestrator.log").exists()
    assert (debate_dir / "archive" / "orchestrator.log").read_text() == "LOG"


def test_does_not_move_synthesis_md(tmp_path: Path) -> None:
    # Scenario: synthesis.md is the final artifact; must remain at debate root.
    # Setup: create synthesis.md plus an r1 output.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "synthesis.md").write_text("FINAL")
    (debate_dir / "r1_gemini.md").write_text("R1G")
    # Test action.
    debate_archive(debate_dir)
    # Test verification: synthesis.md still at root, untouched.
    assert (debate_dir / "synthesis.md").read_text() == "FINAL"
    assert not (debate_dir / "archive" / "synthesis.md").exists()


def test_does_not_move_topic_md(tmp_path: Path) -> None:
    # Scenario: topic.md is a primary artifact; must NOT be archived.
    # Setup.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "topic.md").write_text("TOPIC")
    # Test action.
    debate_archive(debate_dir)
    # Test verification.
    assert (debate_dir / "topic.md").read_text() == "TOPIC"
    assert not (debate_dir / "archive" / "topic.md").exists()


def test_idempotent_when_no_intermediate_files(tmp_path: Path) -> None:
    # Scenario: running on a debate dir with nothing to archive must not error.
    # Setup: only synthesis.md present.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "synthesis.md").write_text("S")
    # Test action.
    debate_archive(debate_dir)
    # Test verification: archive dir created, synthesis.md untouched.
    assert (debate_dir / "archive").is_dir()
    assert (debate_dir / "synthesis.md").read_text() == "S"


def test_handles_preexisting_archive_dir(tmp_path: Path) -> None:
    # Scenario: archive/ already exists from a previous run; mkdir -p semantics.
    # Setup: pre-create archive with a stale file inside, plus a new file to archive.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "archive").mkdir()
    (debate_dir / "archive" / "old.txt").write_text("OLD")
    (debate_dir / "context.md").write_text("NEW")
    # Test action.
    debate_archive(debate_dir)
    # Test verification: prior contents preserved; new file moved in.
    assert (debate_dir / "archive" / "old.txt").read_text() == "OLD"
    assert (debate_dir / "archive" / "context.md").read_text() == "NEW"
    assert not (debate_dir / "context.md").exists()
