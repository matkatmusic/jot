"""RED-YELLOW-GREEN tests for debate_writeFailed (RELAXED_COVERAGE).

No paired bash _tests existed for `write_failed`; tests are authored from
the bash function body's observable intent. Each test isolates one behavior
and asserts on the on-disk FAILED.txt artifact only.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# Mirror the temp module's sys.path bootstrap so the import resolves regardless of CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp_debate_writeFailed import debate_writeFailed  # noqa: E402


_FIXED_NOW = lambda: datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)


def test_writes_failed_txt_at_debate_dir_root(tmp_path):
    # Scenario: one agent missing, no lock; FAILED.txt should appear at debate_dir/FAILED.txt.
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    # Test action:
    out = debate_writeFailed(debate_dir, "R1", "boom", ["gemini"], now=_FIXED_NOW)
    # Test verification:
    assert out == debate_dir / "FAILED.txt"
    assert out.is_file()


def test_header_contains_stage_reason_and_iso_timestamp(tmp_path):
    # Scenario: header lines must include stage, reason, ISO-8601 timestamp from injected clock.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    # Test action:
    debate_writeFailed(debate_dir, "R2", "launch_agent timeout", [], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert text.startswith("# debate FAILED\n")
    assert "stage: R2\n" in text
    assert "reason: launch_agent timeout\n" in text
    assert "timestamp: 2026-05-04T12:00:00+00:00\n" in text


def test_skips_agents_with_nonempty_output_files(tmp_path):
    # Scenario: agent who produced a non-empty stage_<agent>.md must NOT appear in missing list.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    (debate_dir / "R1_gemini.md").write_text("real output\n")
    # Test action:
    debate_writeFailed(debate_dir, "R1", "partial", ["gemini", "codex"], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "### gemini" not in text
    assert "### codex" in text


def test_empty_output_file_counts_as_missing(tmp_path):
    # Scenario: zero-byte output file means agent did not finish; treat as missing.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    (debate_dir / "R1_codex.md").write_text("")  # empty
    # Test action:
    debate_writeFailed(debate_dir, "R1", "x", ["codex"], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "### codex" in text


def test_missing_lock_file_emits_placeholder_line(tmp_path):
    # Scenario: agent missing AND no .lock file -> placeholder string instead of fenced block.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    # Test action:
    debate_writeFailed(debate_dir, "R1", "x", ["claude"], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "(no pane captured -- lock file missing or malformed)" in text
    assert "```" not in text


def test_lock_with_pane_id_invokes_capture_and_fences_output(tmp_path):
    # Scenario: lock file points to pane; pane_capture callback's text is fenced.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    (debate_dir / ".R1_gemini.lock").write_text("debate:%42\n")
    captured = {}

    def fake_capture(pane_id):
        captured["pane"] = pane_id
        return "RESOURCE_EXHAUSTED line1\nline2"

    # Test action:
    debate_writeFailed(
        debate_dir, "R1", "capacity", ["gemini"],
        pane_capture=fake_capture, now=_FIXED_NOW,
    )
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert captured["pane"] == "%42"
    assert "```\nRESOURCE_EXHAUSTED line1\nline2\n```" in text


def test_overwrites_existing_failed_txt(tmp_path):
    # Scenario: a stale FAILED.txt must be replaced atomically (overwrite, not append).
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    (debate_dir / "FAILED.txt").write_text("OLD CONTENT SHOULD VANISH\n")
    # Test action:
    debate_writeFailed(debate_dir, "R1", "fresh", ["gemini"], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "OLD CONTENT SHOULD VANISH" not in text
    assert "reason: fresh" in text


def test_no_temp_files_left_behind_on_success(tmp_path):
    # Scenario: atomic publish via mktemp+rename must leave no .FAILED.txt.* siblings.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    # Test action:
    debate_writeFailed(debate_dir, "R1", "x", ["gemini"], now=_FIXED_NOW)
    # Test verification:
    leftovers = [p.name for p in debate_dir.iterdir() if p.name.startswith(".FAILED.txt.")]
    assert leftovers == []


def test_missing_agents_section_header_present(tmp_path):
    # Scenario: the literal '## missing agents' header is always emitted, even with zero agents.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    # Test action:
    debate_writeFailed(debate_dir, "R1", "x", [], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "## missing agents\n" in text


def test_pane_capture_callback_failure_yields_unavailable_marker(tmp_path):
    # Scenario: capture callback raises -> body still well-formed with '(pane capture unavailable)'.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    (debate_dir / ".R1_codex.lock").write_text("debate:%7\n")

    def boom(_pane_id):
        raise RuntimeError("tmux gone")

    # Test action:
    debate_writeFailed(
        debate_dir, "R1", "x", ["codex"],
        pane_capture=boom, now=_FIXED_NOW,
    )
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "```\n(pane capture unavailable)\n```" in text
