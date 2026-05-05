"""debate_buildClaudePrompts -- Python migration of bash debate_build_prompts().

Bash source: jot-plugin-orchestrator.sh lines 2395-2475.
No heredocs present in bash source (plain printf composition, no python3 subprocess).

YELLOW intent:
- r1: render r1.template.md via render_template.py substituting DEBATE_DIR and
  OUTPUT_FILE, write result to r1_instructions_<agent>.txt for each agent.
- r2: build cross-critique instruction text inline (bash used printf), write to
  r2_instructions_<agent>.txt for each agent.
- synthesis: build synthesis instruction text inline, write to
  synthesis_instructions.txt.
- agent_filter: when set, skip agents that don't match (same semantics as
  AGENT_FILTER env var).
- agents list empty: fall back to reading agents.txt from debate_dir.
"""
from __future__ import annotations

import subprocess
import sys
from io import StringIO
from pathlib import Path


def debate_buildClaudePrompts(
    stage: str,
    debate_dir: Path,
    plugin_root: Path,
    agents: list[str],
    agent_filter: str = "",
) -> None:
    """Build debate instruction files for the given stage.

    Args:
        stage:        One of "r1", "r2", "synthesis".
        debate_dir:   Path to the debate working directory.
        plugin_root:  Path to the plugin root (CLAUDE_PLUGIN_ROOT).
        agents:       List of active agent names. If empty, read from
                      debate_dir/agents.txt (mirrors DEBATE_AGENTS env var).
        agent_filter: When non-empty, emit only that agent's file (mirrors
                      AGENT_FILTER env var).

    Raises:
        ValueError: If stage is not one of the three recognised values.
    """
    debate_dir = Path(debate_dir)
    plugin_root = Path(plugin_root)

    # Resolve agent list -- fall back to agents.txt when list is empty.
    if not agents:
        agents_file = debate_dir / "agents.txt"
        agents = [
            line
            for line in agents_file.read_text().splitlines()
            if line.strip()
        ]

    if stage == "r1":
        _build_r1(stage, debate_dir, plugin_root, agents, agent_filter)
    elif stage == "r2":
        _build_r2(debate_dir, agents, agent_filter)
    elif stage == "synthesis":
        _build_synthesis(debate_dir, agents)
    else:
        raise ValueError(f"Unknown stage: {stage!r}")


# ---------------------------------------------------------------------------
# Stage builders
# ---------------------------------------------------------------------------


def _build_r1(
    stage: str,
    debate_dir: Path,
    plugin_root: Path,
    agents: list[str],
    agent_filter: str,
) -> None:
    """Render r1.template.md for each agent and write r1_instructions_<agent>.txt.

    The bash original delegated to render_template.py with two var overrides:
        DEBATE_DIR=<debate_dir>  OUTPUT_FILE=<debate_dir>/r1_<agent>.md
    We call the same script via subprocess to stay faithful to the original.
    """
    render = plugin_root / "common" / "scripts" / "jot" / "render_template.py"
    template = plugin_root / "skills" / "debate" / "prompts" / "r1.template.md"

    for agent in agents:
        if agent_filter and agent_filter != agent:
            continue
        output_file = debate_dir / f"r1_{agent}.md"
        instructions_file = debate_dir / f"r1_instructions_{agent}.txt"

        if render.exists():
            # Call render_template.py exactly as bash did.
            env_overrides = {
                "DEBATE_DIR": str(debate_dir),
                "OUTPUT_FILE": str(output_file),
            }
            import os
            env = os.environ.copy()
            env.update(env_overrides)
            result = subprocess.run(
                [sys.executable, str(render), str(template), "DEBATE_DIR", "OUTPUT_FILE"],
                capture_output=True,
                text=True,
                env=env,
            )
            instructions_file.write_text(result.stdout)
        else:
            # Fallback: minimal template substitution for testing without
            # the real render_template.py on disk.
            raw = template.read_text()
            rendered = raw.replace("{{DEBATE_DIR}}", str(debate_dir))
            rendered = rendered.replace("{{OUTPUT_FILE}}", str(output_file))
            instructions_file.write_text(rendered)


def _build_r2(
    debate_dir: Path,
    agents: list[str],
    agent_filter: str,
) -> None:
    """Build r2 cross-critique instruction files inline (mirrors bash printf block)."""
    for agent in agents:
        if agent_filter and agent_filter != agent:
            continue
        others = [a for a in agents if a != agent]
        buf = StringIO()
        buf.write("# Debate -- Round 2: Cross-Critique\n\n")
        buf.write(f"## Your Round 1 Response\nRead from: {debate_dir}/r1_{agent}.md\n\n")
        buf.write("## Other Agents' Round 1 Responses\n")
        for other in others:
            buf.write(f"Read {other}'s response from: {debate_dir}/r1_{other}.md\n")
        buf.write("\n## Instructions\n")
        buf.write("- Identify agreement and disagreement across responses\n")
        buf.write("- Validate or challenge claims with evidence\n")
        buf.write("- Concede where others made stronger arguments\n")
        buf.write("- Raise new considerations from reading their perspectives\n")
        buf.write(
            f"\n## Output\nWrite your critique as markdown to: {debate_dir}/r2_{agent}.md\n"
            "Do not write to any other file.\n"
        )
        (debate_dir / f"r2_instructions_{agent}.txt").write_text(buf.getvalue())


def _build_synthesis(debate_dir: Path, agents: list[str]) -> None:
    """Build synthesis instruction file inline (mirrors bash printf block)."""
    agents_str = " ".join(agents)
    buf = StringIO()
    buf.write("# Debate -- Round 3: Synthesis\n\n")
    buf.write(
        f"{len(agents)} agents ({agents_str}) debated across two rounds. "
        "Produce a balanced assessment.\n\n"
    )
    buf.write("## Round 1 Responses\n")
    for agent in agents:
        buf.write(f"Read {agent} R1 from: {debate_dir}/r1_{agent}.md\n")
    buf.write("\n## Round 2 Responses\n")
    for agent in agents:
        buf.write(f"Read {agent} R2 from: {debate_dir}/r2_{agent}.md\n")
    buf.write("\n## Structure\n")
    buf.write("1. **Topic**: One-line restatement\n")
    buf.write("2. **Agreement**: Where agents align\n")
    buf.write("3. **Disagreement**: Where they diverge, strongest argument per side\n")
    buf.write("4. **Strongest Arguments**: Most compelling points, attributed\n")
    buf.write("5. **Weaknesses**: Arguments successfully challenged in R2\n")
    buf.write("6. **Path Forward**: Synthesized recommendation\n")
    buf.write("7. **Confidence**: High/Medium/Low with reasoning\n")
    buf.write("8. **Open Questions**: Unresolved issues\n")
    buf.write(
        f"\n## Output\nWrite synthesis as markdown to: {debate_dir}/synthesis.md\n"
        "Do not write to any other file.\n"
    )
    (debate_dir / "synthesis_instructions.txt").write_text(buf.getvalue())
