"""Python migration of bash `launch_agents_parallel` from jot-plugin-orchestrator.sh ~L2962-2997.

RELAXED_COVERAGE:
- Bash used globals AGENTS and DEBATE_DIR; Python signature makes these explicit params
  (stage, panes, agents, debate_dir). This is an intentional API improvement -- callers
  must be updated at integration time.
- Bash used an indirect variable reference (`eval "pane_id=\${${panes_var}[$i]}"`) to
  resolve pane IDs; Python collapses this to a direct list[str] param.
- ThreadPoolExecutor replaces bash `&`+`wait` for parallel subshell launches.

# WORKSPACE-FALLBACK: the try/except import block below is temporary scaffolding.
# When merging into jot_plugin_orchestrator.py, rewrite to a single flat import.
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

# WORKSPACE-FALLBACK: remove this block at integration time -- rewrite as single import.
try:
    from jot_plugin_orchestrator import (
        debate_agentLaunchCmd,
        debate_agentReadyMarker,
        debate_launchAgent,
        debate_sendPromptToAgent,
        tmux_killPane,
    )
except ImportError:
    from _tmp_debate_launchAgent import debate_launchAgent  # type: ignore[no-redef]
    from _tmp_debate_sendPromptToAgent import debate_sendPromptToAgent  # type: ignore[no-redef]
    from _tmp_debate_agentLaunchCmd import debate_agentLaunchCmd  # type: ignore[no-redef]
    from _tmp_debate_agentReadyMarker import debate_agentReadyMarker  # type: ignore[no-redef]
    from jot_plugin_orchestrator import tmux_killPane  # type: ignore[no-redef]


def debate_launchAgentsParallel(
    stage: str,
    panes: list[str],
    agents: list[str],
    debate_dir: str | Path,
) -> int:
    """Launch multiple debate agents in parallel for a given stage.

    Mirrors bash `launch_agents_parallel` (jot-plugin-orchestrator.sh ~L2962-2997).

    For each agent/pane pair:
    - If the output file (<debate_dir>/<stage>_<agent>.md) already exists and is
      non-empty, the agent is considered complete; the pane is killed and skipped.
    - If a lock file (<debate_dir>/.<stage>_<agent>.lock) exists, a live pane is
      already running; the new pane is killed and skipped.
    - Otherwise, launch the agent and send its prompt concurrently via
      ThreadPoolExecutor (replaces bash `&` + `wait`).

    Args:
        stage:      Debate stage label (e.g. "r1", "r2").
        panes:      Ordered list of tmux pane IDs; panes[i] pairs with agents[i].
        agents:     Ordered list of agent names (e.g. ["claude", "gemini"]).
        debate_dir: Directory holding stage output and instruction files.

    Returns:
        0 if all launched workers succeeded, 1 if any worker exited non-zero.

    RELAXED_COVERAGE:
        Bash signature was `launch_agents_parallel <stage> <panes_var>` where
        panes_var was an indirect array reference to a global and AGENTS/DEBATE_DIR
        were implicit globals. Python makes all four params explicit.
    """
    debate_dir = Path(debate_dir)
    t0 = time.monotonic()
    fail = 0

    # Map future -> agent name so we can log failures by name.
    future_to_agent: dict[Future[int], str] = {}

    with ThreadPoolExecutor() as pool:
        for pane_id, agent in zip(panes, agents):
            output_file = debate_dir / f"{stage}_{agent}.md"
            lock_file = debate_dir / f".{stage}_{agent}.lock"

            # Skip: output already exists (non-empty) -- agent previously completed.
            if output_file.exists() and output_file.stat().st_size > 0:
                print(f"[orch] {stage}/{agent} already complete, skipping launch", flush=True)
                tmux_killPane(pane_id)
                continue

            # Skip: lock held by a live pane -- wait_for_outputs will observe it.
            if lock_file.exists():
                print(
                    f"[orch] {stage}/{agent} lock held by live pane, "
                    "skipping launch (wait_for_outputs will observe)",
                    flush=True,
                )
                tmux_killPane(pane_id)
                continue

            # Launch agent and send prompt concurrently.
            def _worker(
                _pane_id: str = pane_id,
                _agent: str = agent,
            ) -> int:
                launch_cmd = debate_agentLaunchCmd(_agent)
                ready_marker = debate_agentReadyMarker(_agent)
                ok = debate_launchAgent(_pane_id, stage, _agent, launch_cmd, ready_marker)
                if not ok:
                    return 1
                instructions = str(debate_dir / f"{stage}_instructions_{_agent}.txt")
                return debate_sendPromptToAgent(_pane_id, stage, _agent, instructions)

            future_to_agent[pool.submit(_worker)] = agent

        # Collect results as workers complete.
        for future in as_completed(future_to_agent):
            agent_name = future_to_agent[future]
            try:
                rc = future.result()
            except Exception as exc:
                print(f"[orch] {stage}/{agent_name} worker raised: {exc}", file=sys.stderr, flush=True)
                rc = 1
            if rc != 0:
                print(f"[orch] {stage}/{agent_name} worker exited non-zero", file=sys.stderr, flush=True)
                fail = 1

    wall = time.monotonic() - t0
    n_workers = len(future_to_agent)
    print(
        f"[orch] launch_agents_parallel {stage}: {n_workers} workers, {wall:.1f}s wall",
        file=sys.stderr,
        flush=True,
    )
    return fail
