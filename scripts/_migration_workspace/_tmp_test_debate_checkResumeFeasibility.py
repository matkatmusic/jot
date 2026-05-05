#!/usr/bin/env python3
"""RED-YELLOW-GREEN tests for debate_checkResumeFeasibility.

No paired bash _tests existed for check_resume_feasibility — RELAXED_COVERAGE.
Tests authored from the bash function intent + comment docstring (lines
~2317-2355 of jot-plugin-orchestrator.sh) and follow RED_GREEN_TDD.md
test-shape rules: one behavior per test, scenario/setup/action/verification
comments, assert on returned feasibility verdict / why-not reason.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the workspace temp module importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp_debate_checkResumeFeasibility import (  # noqa: E402
    ResumeFeasibility,
    debate_checkResumeFeasibility,
)


def _seed_original(debate_dir: Path, agents: list[str]) -> None:
    """Helper: write r1_instructions_<agent>.txt for each agent."""
    debate_dir.mkdir(parents=True, exist_ok=True)
    for a in agents:
        (debate_dir / f"r1_instructions_{a}.txt").write_text("instr\n")


def _seed_outputs(debate_dir: Path, agent: str, *, r1: bool, r2: bool) -> None:
    """Helper: optionally seed non-empty r1_<agent>.md / r2_<agent>.md."""
    if r1:
        (debate_dir / f"r1_{agent}.md").write_text("r1 body\n")
    if r2:
        (debate_dir / f"r2_{agent}.md").write_text("r2 body\n")


def test_all_originals_still_available_returns_feasible(tmp_path: Path) -> None:
    # Scenario: original composition (claude, gemini) still all available.
    # Setup: seed two r1_instructions files; available list matches exactly.
    _seed_original(tmp_path, ["claude", "gemini"])
    # Test action: run the feasibility check.
    result = debate_checkResumeFeasibility(tmp_path, ["claude", "gemini"])
    # Test verification: feasible=True, agent list unchanged, no unusable.
    assert result.feasible is True
    assert result.unusable_agents == []
    assert set(result.updated_agents) == {"claude", "gemini"}


def test_appeared_agent_is_kept_in_updated_list(tmp_path: Path) -> None:
    # Scenario: an agent appeared since the original debate (codex new).
    # Setup: original was just claude; available now is [claude, codex].
    _seed_original(tmp_path, ["claude"])
    # Test action: feasibility check with the larger available list.
    result = debate_checkResumeFeasibility(tmp_path, ["claude", "codex"])
    # Test verification: feasible and codex retained for JIT instructions.
    assert result.feasible is True
    assert "codex" in result.updated_agents


def test_disappeared_agent_with_complete_outputs_is_readded(tmp_path: Path) -> None:
    # Scenario: gemini disappeared (creds gone) but its R1+R2 are cached.
    # Setup: original=[claude,gemini]; available=[claude]; gemini outputs exist.
    _seed_original(tmp_path, ["claude", "gemini"])
    _seed_outputs(tmp_path, "gemini", r1=True, r2=True)
    # Test action: run check.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: feasible, gemini re-added so synthesis sees it.
    assert result.feasible is True
    assert "gemini" in result.updated_agents
    assert result.unusable_agents == []


def test_disappeared_agent_missing_r2_is_unusable(tmp_path: Path) -> None:
    # Scenario: gemini disappeared and only R1 cached (no R2).
    # Setup: original=[claude,gemini]; available=[claude]; only gemini r1 exists.
    _seed_original(tmp_path, ["claude", "gemini"])
    _seed_outputs(tmp_path, "gemini", r1=True, r2=False)
    # Test action: run check.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: not feasible; gemini listed in unusable.
    assert result.feasible is False
    assert result.unusable_agents == ["gemini"]


def test_disappeared_agent_with_empty_output_file_is_unusable(tmp_path: Path) -> None:
    # Scenario: r1+r2 exist but r2 is zero bytes — bash uses `-s` (non-empty).
    # Setup: seed gemini originals and an empty r2 file.
    _seed_original(tmp_path, ["claude", "gemini"])
    (tmp_path / "r1_gemini.md").write_text("r1\n")
    (tmp_path / "r2_gemini.md").write_text("")  # zero-byte
    # Test action: run check with gemini missing from availability.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: empty file == unusable, matching bash `[ -s ]` semantics.
    assert result.feasible is False
    assert "gemini" in result.unusable_agents


def test_unusable_reason_contains_block_message_and_agent_name(tmp_path: Path) -> None:
    # Scenario: emit_block reason text needs to surface the unusable agent.
    # Setup: codex disappeared with no outputs at all.
    _seed_original(tmp_path, ["claude", "codex"])
    # Test action: run check with codex unavailable and no cached outputs.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: reason mentions codex and the canonical resume hint.
    assert "codex" in result.reason
    assert "cannot resume" in result.reason
    assert "/debate-abort" in result.reason


def test_no_original_instructions_returns_feasible(tmp_path: Path) -> None:
    # Scenario: brand-new debate dir with no r1_instructions_*.txt yet.
    # Setup: empty debate_dir; available=[claude].
    tmp_path.mkdir(exist_ok=True)
    # Test action: run check.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: trivially feasible — no originals to validate against.
    assert result.feasible is True
    assert result.unusable_agents == []
    assert result.updated_agents == ["claude"]


def test_caller_available_agents_list_is_not_mutated(tmp_path: Path) -> None:
    # Scenario: function must not mutate caller's list (Python idiom vs bash global).
    # Setup: original includes gemini with cached outputs; available list captured.
    _seed_original(tmp_path, ["claude", "gemini"])
    _seed_outputs(tmp_path, "gemini", r1=True, r2=True)
    available = ["claude"]
    snapshot = list(available)
    # Test action: run check.
    debate_checkResumeFeasibility(tmp_path, available)
    # Test verification: caller's list is unchanged after the call.
    assert available == snapshot


def test_returns_resumefeasibility_dataclass_instance(tmp_path: Path) -> None:
    # Scenario: contract — return type is the documented dataclass.
    # Setup: minimal valid debate dir.
    _seed_original(tmp_path, ["claude"])
    # Test action: run the check.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: instance shape is ResumeFeasibility.
    assert isinstance(result, ResumeFeasibility)
    assert isinstance(result.updated_agents, list)
    assert isinstance(result.unusable_agents, list)
