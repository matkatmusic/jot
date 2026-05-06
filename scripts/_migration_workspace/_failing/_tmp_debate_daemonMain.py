"""
debate_daemonMain - Python migration of bash daemon_main (jot-plugin-orchestrator.sh:3054-3144).

Signature change rationale:
    The bash original relied on globals (DEBATE_DIR, SESSION, WINDOW_TARGET, AGENTS,
    STAGE_TIMEOUT, PLUGIN_ROOT, COMPOSITION_DRIFTED).  All are now explicit keyword-only
    args so callers are self-documenting and the function is unit-testable without
    environment surgery.

Dependencies (workspace-fallback -- flag for merger):
    debate_initAgentModels       _tmp_debate_initAgentModels.py
    debate_cleanStaleLocks       _tmp_debate_cleanStaleLocks.py
    debate_newEmptyPane          _tmp_debate_newEmptyPane.py
    debate_launchAgentsParallel  _tmp_debate_launchAgentsParallel.py
    debate_waitForOutputs        _tmp_debate_waitForOutputs.py
    debate_buildClaudePrompts    _tmp_debate_buildClaudePrompts.py
    debate_launchAgent           _tmp_debate_launchAgent.py
    debate_sendPromptToAgent     _tmp_debate_sendPromptToAgent.py
    debate_agentLaunchCmd        _tmp_debate_agentLaunchCmd.py
    debate_agentReadyMarker      _tmp_debate_agentReadyMarker.py
    debate_archive               _tmp_debate_archive.py
    shell_waitForFile            _tmp_shell_waitForFile.py
    tmux_retile                  merged
    tmux_killPane                merged

Exit semantics:
    Returns 0 on full success.
    Returns 1 (or raises SystemExit(1)) when any subordinate step fails.
    The synthesis-already-complete short-circuit returns 0 after archiving.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Workspace-fallback imports -- replace with package imports after merger
# ---------------------------------------------------------------------------

try:
    from skills.debate.debate_initAgentModels import debate_initAgentModels
except ImportError:  # pragma: no cover - workspace fallback
    from _tmp_debate_initAgentModels import debate_initAgentModels  # type: ignore[no-redef]

try:
    from skills.debate.debate_cleanStaleLocks import debate_cleanStaleLocks
except ImportError:  # pragma: no cover - workspace fallback
    from _tmp_debate_cleanStaleLocks import debate_cleanStaleLocks  # type: ignore[no-redef]

try:
    from skills.debate.debate_newEmptyPane import debate_newEmptyPane
except ImportError:  # pragma: no cover - workspace fallback
    from _tmp_debate_newEmptyPane import debate_newEmptyPane  # type: ignore[no-redef]

try:
    from skills.debate.debate_launchAgentsParallel import debate_launchAgentsParallel
except ImportError:  # pragma: no cover - workspace fallback
    from _tmp_debate_launchAgentsParallel import debate_launchAgentsParallel  # type: ignore[no-redef]

try:
    from skills.debate.debate_waitForOutputs import debate_waitForOutputs
except ImportError:  # pragma: no cover - workspace fallback
    from _tmp_debate_waitForOutputs import debate_waitForOutputs  # type: ignore[no-redef]

try:
    from skills.debate.debate_buildClaudePrompts import debate_buildClaudePrompts
except ImportError:  # pragma: no cover - workspace fallback
    from _tmp_debate_buildClaudePrompts import debate_buildClaudePrompts  # type: ignore[no-redef]

try:
    from skills.debate.debate_launchAgent import debate_launchAgent
except ImportError:  # pragma: no cover - workspace fallback
    from _tmp_debate_launchAgent import debate_launchAgent  # type: ignore[no-redef]

try:
    from skills.debate.debate_sendPromptToAgent import debate_sendPromptToAgent
except ImportError:  # pragma: no cover - workspace fallback
    from _tmp_debate_sendPromptToAgent import debate_sendPromptToAgent  # type: ignore[no-redef]

try:
    from skills.debate.debate_agentLaunchCmd import debate_agentLaunchCmd
except ImportError:  # pragma: no cover - workspace fallback
    from _tmp_debate_agentLaunchCmd import debate_agentLaunchCmd  # type: ignore[no-redef]

try:
    from skills.debate.debate_agentReadyMarker import debate_agentReadyMarker
except ImportError:  # pragma: no cover - workspace fallback
    from _tmp_debate_agentReadyMarker import debate_agentReadyMarker  # type: ignore[no-redef]

try:
    from skills.debate.debate_archive import debate_archive
except ImportError:  # pragma: no cover - workspace fallback
    from _tmp_debate_archive import debate_archive  # type: ignore[no-redef]

try:
    from common.shell_waitForFile import shell_waitForFile
except ImportError:  # pragma: no cover - workspace fallback
    from _tmp_shell_waitForFile import shell_waitForFile  # type: ignore[no-redef]

try:
    from common.tmux import tmux_retile, tmux_killPane
except ImportError:  # pragma: no cover - workspace fallback
    from _tmp_tmux import tmux_retile, tmux_killPane  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------

def debate_daemonMain(
    *,
    debate_dir: str | Path,
    session: str,
    window_target: str,
    agents: list[str],
    stage_timeout: int,
    plugin_root: str,
    composition_drifted: bool = False,
) -> int:
    """Drive the full R1 -> R2 -> synthesis pipeline for a debate session.

    Args:
        debate_dir:          Absolute path to the debate working directory.
        session:             tmux session name.
        window_target:       tmux window target string (e.g. "session:0").
        agents:              Ordered list of agent names participating in the debate.
        stage_timeout:       Per-stage wall-clock timeout in seconds.
        plugin_root:         Absolute path to the plugin root (used by prompt builder).
        composition_drifted: When True, stale R2 artifacts are wiped before R1 runs.

    Returns:
        0 on success.  Returns 1 (or raises SystemExit(1)) on any subordinate failure.
    """
    debate_dir = Path(debate_dir)

    # ------------------------------------------------------------------
    # Banner
    # ------------------------------------------------------------------
    print("========================================")
    print("[orch] DEBATE DAEMON")
    print(f"[orch] Dir:     {debate_dir}")
    print(f"[orch] Session: {session}")
    print(f"[orch] Window:  {window_target}")
    print(f"[orch] Agents:  {agents} ({len(agents)})")
    print(f"[orch] Timeout: {stage_timeout}s per stage")
    print(f"[orch] Drift:   {int(composition_drifted)}")
    print("========================================")

    # ------------------------------------------------------------------
    # Init agent models
    # ------------------------------------------------------------------
    debate_initAgentModels()

    # ------------------------------------------------------------------
    # Drift handling: wipe stale R2 artifacts so they are rebuilt fresh
    # ------------------------------------------------------------------
    if composition_drifted:
        print("[orch] composition drifted -- clearing r2_*.md, r2_instructions_*.txt, synthesis_instructions.txt")
        for pattern in ("r2_*.md", "r2_instructions_*.txt", ".r2_*.lock"):
            for f in debate_dir.glob(pattern):
                f.unlink(missing_ok=True)
        (debate_dir / "synthesis_instructions.txt").unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # R1 stage
    # ------------------------------------------------------------------
    debate_cleanStaleLocks("r1")

    r1_panes: list[str] = []
    for _agent in agents:
        r1_panes.append(debate_newEmptyPane())

    tmux_retile(window_target)
    print(f"[orch] R1 panes: agents={agents}={r1_panes}")
    time.sleep(1)

    if debate_launchAgentsParallel("r1", r1_panes) != 0:
        return 1

    if debate_waitForOutputs("r1", stage_timeout, r1_panes) != 0:
        return 1

    for pane in r1_panes:
        tmux_killPane(pane)
    tmux_retile(window_target)
    print("[orch] R1 agent panes closed")

    # ------------------------------------------------------------------
    # Build R2 prompts for any agent missing its instructions file
    # ------------------------------------------------------------------
    debate_cleanStaleLocks("r2")

    agents_str = " ".join(agents)
    for agent in agents:
        r2_instructions = debate_dir / f"r2_instructions_{agent}.txt"
        if r2_instructions.exists():
            continue
        # Mirrors: DEBATE_AGENTS="${AGENTS[*]}" AGENT_FILTER="$_a" debate_build_prompts r2 ...
        debate_buildClaudePrompts(
            stage="r2",
            debate_dir=str(debate_dir),
            plugin_root=plugin_root,
            debate_agents=agents_str,
            agent_filter=agent,
        )

    # ------------------------------------------------------------------
    # R2 stage
    # ------------------------------------------------------------------
    r2_panes: list[str] = []
    for _agent in agents:
        r2_panes.append(debate_newEmptyPane())

    tmux_retile(window_target)
    print(f"[orch] R2 panes: agents={agents}={r2_panes}")
    time.sleep(1)

    if debate_launchAgentsParallel("r2", r2_panes) != 0:
        return 1

    if debate_waitForOutputs("r2", stage_timeout, r2_panes) != 0:
        return 1

    for pane in r2_panes:
        tmux_killPane(pane)
    tmux_retile(window_target)
    print("[orch] R2 agent panes closed")

    # ------------------------------------------------------------------
    # Synthesis short-circuit: if synthesis.md is already non-empty, skip launch
    # ------------------------------------------------------------------
    synthesis_md = debate_dir / "synthesis.md"
    if synthesis_md.exists() and synthesis_md.stat().st_size > 0:
        print("[orch] synthesis already complete, skipping launch; running archive step")
        debate_archive()
        print(f"[orch] DEBATE COMPLETE -- synthesis at {synthesis_md}")
        return 0

    # ------------------------------------------------------------------
    # Synthesis stage
    # ------------------------------------------------------------------
    debate_cleanStaleLocks("synthesis")

    synthesis_instructions = debate_dir / "synthesis_instructions.txt"
    if not synthesis_instructions.exists():
        debate_buildClaudePrompts(
            stage="synthesis",
            debate_dir=str(debate_dir),
            plugin_root=plugin_root,
            debate_agents=agents_str,
            agent_filter=None,
        )

    synth_pane = debate_newEmptyPane()
    tmux_retile(window_target)
    print(f"[orch] synthesis pane: {synth_pane}")
    time.sleep(1)

    launch_cmd = debate_agentLaunchCmd("claude")
    ready_marker = debate_agentReadyMarker("claude")

    if debate_launchAgent(synth_pane, "synthesis", "claude", launch_cmd, ready_marker) != 0:
        return 1

    if debate_sendPromptToAgent(synth_pane, "synthesis", "claude", str(synthesis_instructions)) != 0:
        return 1

    if shell_waitForFile(str(synthesis_md), stage_timeout) != 0:
        return 1

    tmux_killPane(synth_pane)
    tmux_retile(window_target)
    print("[orch] synthesis pane closed")

    debate_archive()
    print(f"[orch] DEBATE COMPLETE -- synthesis at {synthesis_md}")
    return 0
