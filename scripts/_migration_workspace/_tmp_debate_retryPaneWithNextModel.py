"""GREEN implementation of debate_retryPaneWithNextModel.

Migrated from bash `retry_pane_with_next_model` (jot-plugin-orchestrator.sh L2896-2919).
RELAXED_COVERAGE: no paired bash _tests; behavior derived from function body + docstring.

Bash original:
    retry_pane_with_next_model() {
      local panes_var="$1" i="$2" agent="$3" stage="$4"
      local next
      if ! next=$(_next_model "$agent"); then
        echo "[orch] $stage/$agent: no remaining models; giving up" >&2
        return 1
      fi
      echo "[orch] $stage/$agent: capacity hit -- rotating to model '$next'"
      _stash CURRENT_MODEL "$agent" "$next"
      local tried; tried=$(_lookup TRIED_MODELS "$agent")
      _stash TRIED_MODELS "$agent" "${tried},${next}"
      local current_pane
      eval "current_pane=${panes_var}[$i]"
      hide_errors tmux_kill_pane "$current_pane"
      local new_pane; new_pane=$(new_empty_pane)
      eval "${panes_var}[$i]=\"$new_pane\""
      hide_output tmux_retile "$WINDOW_TARGET"
      sleep 1
      launch_agent "$new_pane" "$stage" "$agent" \
        "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" || return 1
      send_prompt  "$new_pane" "$stage" "$agent" \
        "$DEBATE_DIR/${stage}_instructions_${agent}.txt" || return 1
      return 0
    }

Python changes vs bash:
- No global bash arrays (CURRENT_MODEL / TRIED_MODELS): callers pass dicts and
  this function mutates them in-place (same semantics, no side-channel globals).
- panes_var / eval-based array mutation replaced by return value: callers update
  their pane list with the returned new pane id (None = failure).
- launch_agent / send_prompt are private helpers (_launch_agent / _send_prompt)
  factored as thin callables so tests can mock at module boundary.
- sleep(1) preserved for parity with bash (retile settle time).
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Dependency imports (plan-mandated fallback chain)
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from jot_plugin_orchestrator import *  # noqa: F401, F403

try:
    from jot_plugin_orchestrator import debate_nextModel  # noqa: E402
except ImportError:
    from _tmp_debate_nextModel import debate_nextModel  # type: ignore[no-redef]

try:
    from jot_plugin_orchestrator import debate_newEmptyPane  # noqa: E402
except ImportError:
    from _tmp_debate_newEmptyPane import debate_newEmptyPane  # type: ignore[no-redef]

try:
    from jot_plugin_orchestrator import debate_agentLaunchCmd  # noqa: E402
except ImportError:
    from _tmp_debate_agentLaunchCmd import debate_agentLaunchCmd  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Private helpers (thin wrappers so tests can mock at module boundary)
# ---------------------------------------------------------------------------

def _kill_pane(pane_id: str) -> None:
    """Kill a tmux pane, silencing errors (mirrors bash `hide_errors tmux_kill_pane`)."""
    subprocess.run(
        ["tmux", "kill-pane", "-t", pane_id],
        capture_output=True,
        check=False,
    )


def _launch_agent(
    *,
    pane_id: str,
    stage: str,
    agent: str,
    launch_cmd: str,
    debate_dir: str,
) -> bool:
    """Thin shim; real implementation delegates to the monolith launch_agent.

    Returns True if the agent reached its ready marker within the timeout.
    In production this is replaced by the real launch_agent; here we import
    it from the monolith if available.
    """
    # Attempt to call the real function if available on sys.modules.
    try:
        import jot_plugin_orchestrator as _mono  # type: ignore[import]
        return bool(
            _mono.launch_agent(  # type: ignore[attr-defined]
                pane_id, stage, agent, launch_cmd,
                _mono.agent_ready_marker(agent),  # type: ignore[attr-defined]
            )
        )
    except (AttributeError, ImportError):
        return False


def _send_prompt(
    *,
    pane_id: str,
    stage: str,
    agent: str,
    debate_dir: str,
) -> bool:
    """Thin shim; delegates to monolith send_prompt if available."""
    instructions = f"{debate_dir}/{stage}_instructions_{agent}.txt"
    try:
        import jot_plugin_orchestrator as _mono  # type: ignore[import]
        return bool(
            _mono.send_prompt(pane_id, stage, agent, instructions)  # type: ignore[attr-defined]
        )
    except (AttributeError, ImportError):
        return False


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def debate_retryPaneWithNextModel(
    *,
    pane_index: int,
    agent: str,
    stage: str,
    current_pane_id: str,
    current_model: dict[str, str],
    tried_models: dict[str, str],
    window_target: str,
    cwd: str,
    repo_root: str,
    home: str,
    settings_file: str,
    debate_dir: str,
    models_json_path: str,
) -> str | None:
    """Rotate a capacity-exhausted agent pane to the next available model.

    Mirrors bash retry_pane_with_next_model (L2896-2919).

    Steps:
    1. Ask debate_nextModel for the next untried model for `agent`.
       If none remain, log and return None (bash return 1).
    2. Mutate `current_model` and `tried_models` dicts in-place.
    3. Kill the stale pane; open a fresh empty pane via debate_newEmptyPane.
    4. Launch the agent in the new pane; send it the stage instructions.
    5. Return the new pane id on success; None on any failure.

    Args:
        pane_index: position of this agent in the PANES array (informational).
        agent: "gemini" | "codex" | "claude".
        stage: "r1" | "r2" | "synthesis".
        current_pane_id: tmux pane id being replaced (e.g. "%10").
        current_model: mutable dict agent->current model string (mutated in-place).
        tried_models: mutable dict agent->comma-separated tried model string (mutated).
        window_target: tmux window target for retiling (e.g. "debate:0").
        cwd: working directory for the new pane.
        repo_root: repository root path.
        home: $HOME used for claude --add-dir dedup.
        settings_file: path to claude settings JSON.
        debate_dir: absolute path to the debate working directory.
        models_json_path: path to assets/models.json.

    Returns:
        New pane id string on success; None if no models left or launch failed.
    """
    # YELLOW: ask for next untried model; bail early if list exhausted.
    next_model = debate_nextModel(
        agent=agent,
        tried_models=tried_models,
        models_json_path=models_json_path,
    )
    if next_model is None:
        print(
            f"[orch] {stage}/{agent}: no remaining models; giving up",
            file=sys.stderr,
        )
        return None

    print(f"[orch] {stage}/{agent}: capacity hit -- rotating to model '{next_model}'")

    # YELLOW: update stash dicts in-place (replaces bash _stash calls).
    current_model[agent] = next_model
    existing_tried = tried_models.get(agent, "")
    tried_models[agent] = f"{existing_tried},{next_model}" if existing_tried else next_model

    # YELLOW: kill stale pane; open fresh replacement.
    _kill_pane(current_pane_id)
    new_pane = debate_newEmptyPane(window_target=window_target, cwd=cwd)
    if new_pane is None:
        print(
            f"[orch] {stage}/{agent}: debate_newEmptyPane returned None",
            file=sys.stderr,
        )
        return None

    # YELLOW: settle time after retile (mirrors bash `sleep 1`).
    time.sleep(1)

    # YELLOW: build launch command string for the updated model.
    launch_cmd = debate_agentLaunchCmd(
        agent=agent,
        current_model=current_model,
        debate_dir=debate_dir,
        cwd=cwd,
        repo_root=repo_root,
        home=home,
        settings_file=settings_file,
    )

    # YELLOW: launch agent; propagate failure as None.
    if not _launch_agent(
        pane_id=new_pane,
        stage=stage,
        agent=agent,
        launch_cmd=launch_cmd,
        debate_dir=debate_dir,
    ):
        return None

    # YELLOW: send instructions file; propagate failure as None.
    if not _send_prompt(
        pane_id=new_pane,
        stage=stage,
        agent=agent,
        debate_dir=debate_dir,
    ):
        return None

    return new_pane
