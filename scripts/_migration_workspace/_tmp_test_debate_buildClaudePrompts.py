"""RED tests for debate_buildClaudePrompts migration.

Bash source: jot-plugin-orchestrator.sh lines 2395-2475 (debate_build_prompts).
No heredocs present in bash source.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _tmp_debate_buildClaudePrompts import debate_buildClaudePrompts


# ---------------------------------------------------------------------------
# r1 stage
# ---------------------------------------------------------------------------


def test_r1_writes_instruction_file_for_each_agent(tmp_path: Path) -> None:
    # Scenario: r1 stage with two agents, no AGENT_FILTER
    # Setup:
    plugin_root = tmp_path / "plugin"
    tmpl_dir = plugin_root / "skills" / "debate" / "prompts"
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "r1.template.md").write_text("# R1 template\nDEBATE_DIR={{DEBATE_DIR}}\nOUTPUT_FILE={{OUTPUT_FILE}}\n")
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]

    # Test action:
    debate_buildClaudePrompts(
        stage="r1",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
    )

    # Test verification:
    for agent in agents:
        out = debate_dir / f"r1_instructions_{agent}.txt"
        assert out.exists(), f"missing {out.name}"
        content = out.read_text()
        assert str(debate_dir) in content
        assert str(debate_dir / f"r1_{agent}.md") in content


def test_r1_agent_filter_writes_only_matching_agent(tmp_path: Path) -> None:
    # Scenario: r1 stage with AGENT_FILTER set to one agent
    # Setup:
    plugin_root = tmp_path / "plugin"
    tmpl_dir = plugin_root / "skills" / "debate" / "prompts"
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "r1.template.md").write_text("DEBATE_DIR={{DEBATE_DIR}}\nOUTPUT_FILE={{OUTPUT_FILE}}\n")
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]

    # Test action:
    debate_buildClaudePrompts(
        stage="r1",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
        agent_filter="claude",
    )

    # Test verification:
    assert (debate_dir / "r1_instructions_claude.txt").exists()
    assert not (debate_dir / "r1_instructions_gemini.txt").exists()


def test_r1_reads_agents_from_agents_txt_when_agents_list_empty(tmp_path: Path) -> None:
    # Scenario: agents list is empty; function falls back to agents.txt
    # Setup:
    plugin_root = tmp_path / "plugin"
    tmpl_dir = plugin_root / "skills" / "debate" / "prompts"
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "r1.template.md").write_text("DEBATE_DIR={{DEBATE_DIR}}\nOUTPUT_FILE={{OUTPUT_FILE}}\n")
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "agents.txt").write_text("claude\ngemini\n")

    # Test action:
    debate_buildClaudePrompts(
        stage="r1",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=[],
    )

    # Test verification:
    assert (debate_dir / "r1_instructions_claude.txt").exists()
    assert (debate_dir / "r1_instructions_gemini.txt").exists()


# ---------------------------------------------------------------------------
# r2 stage
# ---------------------------------------------------------------------------


def test_r2_writes_cross_critique_instruction_file_for_each_agent(tmp_path: Path) -> None:
    # Scenario: r2 stage with three agents, no filter
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini", "codex"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="r2",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
    )

    # Test verification:
    for agent in agents:
        out = debate_dir / f"r2_instructions_{agent}.txt"
        assert out.exists()
        content = out.read_text()
        assert "Round 2: Cross-Critique" in content
        assert f"r1_{agent}.md" in content
        # Others' r1 paths referenced
        for other in agents:
            if other != agent:
                assert f"r1_{other}.md" in content
        assert f"r2_{agent}.md" in content


def test_r2_agent_filter_writes_only_matching_agent(tmp_path: Path) -> None:
    # Scenario: r2 with AGENT_FILTER; only target agent file written
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="r2",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
        agent_filter="gemini",
    )

    # Test verification:
    assert (debate_dir / "r2_instructions_gemini.txt").exists()
    assert not (debate_dir / "r2_instructions_claude.txt").exists()


def test_r2_others_list_excludes_self(tmp_path: Path) -> None:
    # Scenario: r2 for agent "claude"; claude's own r1 not listed as "other"
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="r2",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
        agent_filter="claude",
    )

    # Test verification:
    content = (debate_dir / "r2_instructions_claude.txt").read_text()
    lines = content.splitlines()
    # gemini r1 path appears in "Other Agents" section (after the header line)
    other_refs = [l for l in lines if "r1_gemini.md" in l]
    assert other_refs, "gemini r1 not referenced"
    # claude's r1 path referenced only as "Your Round 1 Response"
    self_refs = [l for l in lines if "r1_claude.md" in l]
    assert self_refs, "own r1 not referenced at all"


# ---------------------------------------------------------------------------
# synthesis stage
# ---------------------------------------------------------------------------


def test_synthesis_writes_single_instruction_file(tmp_path: Path) -> None:
    # Scenario: synthesis stage with two agents
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="synthesis",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
    )

    # Test verification:
    out = debate_dir / "synthesis_instructions.txt"
    assert out.exists()
    content = out.read_text()
    assert "Round 3: Synthesis" in content
    assert "2 agents" in content
    assert "claude" in content
    assert "gemini" in content
    assert "synthesis.md" in content


def test_synthesis_references_all_r1_and_r2_paths(tmp_path: Path) -> None:
    # Scenario: synthesis file references every agent's r1 and r2 paths
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini", "codex"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="synthesis",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
    )

    # Test verification:
    content = (debate_dir / "synthesis_instructions.txt").read_text()
    for agent in agents:
        assert f"r1_{agent}.md" in content
        assert f"r2_{agent}.md" in content


def test_synthesis_contains_required_structure_sections(tmp_path: Path) -> None:
    # Scenario: output must contain all 8 structure headings
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="synthesis",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
    )

    # Test verification:
    content = (debate_dir / "synthesis_instructions.txt").read_text()
    for heading in [
        "Topic",
        "Agreement",
        "Disagreement",
        "Strongest Arguments",
        "Weaknesses",
        "Path Forward",
        "Confidence",
        "Open Questions",
    ]:
        assert heading in content, f"missing section: {heading}"


# ---------------------------------------------------------------------------
# error cases
# ---------------------------------------------------------------------------


def test_unknown_stage_raises_value_error(tmp_path: Path) -> None:
    # Scenario: invalid stage name raises ValueError
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()

    # Test action / verification:
    try:
        debate_buildClaudePrompts(
            stage="badstage",
            debate_dir=debate_dir,
            plugin_root=tmp_path / "plugin",
            agents=["claude"],
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "badstage" in str(exc)
