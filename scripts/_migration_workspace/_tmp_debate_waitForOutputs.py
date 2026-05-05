"""debate_waitForOutputs — migrated from bash `wait_for_outputs`.

Polls DEBATE_DIR for per-agent output files (`<prefix>_<agent>.md`) until all
agents have non-empty outputs or the timeout elapses. On each poll iteration,
panes lacking output are checked for capacity errors and retried.

Boundaries (injected for testability):
  - pane_capacity_error(pane_id, agent) -> bool
  - retry_pane(panes, index, agent, prefix) -> any (best-effort; failures swallowed)
  - sleep_fn(seconds) -> None

Returns:
  (success: bool, completed_agents: list[str], timeout_reason: str | None)
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, Sequence


def debate_waitForOutputs(
    *,
    prefix: str,
    timeout: int,
    panes: Mapping[int, str],
    agents: Sequence[str],
    debate_dir: Path,
    pane_capacity_error: Callable[[str, str], bool],
    retry_pane: Callable[..., object],
    sleep_fn: Callable[[float], None],
    poll_interval: int = 5,
) -> tuple[bool, list[str], str | None]:
    # YELLOW intent: loop until timeout. Each cycle, scan agents; if their output
    # file exists and is non-empty, mark complete and remove their lock. Otherwise
    # check the pane for a capacity error and trigger a retry. When all agents
    # complete, return success. On timeout, return failure with the agents that
    # did complete and a timeout reason string.
    debate_dir = Path(debate_dir)
    completed: list[str] = []
    elapsed = 0

    while elapsed < timeout:
        for i, agent in enumerate(agents):
            out = debate_dir / f"{prefix}_{agent}.md"
            # Bash `[ -s "$out" ]` -> exists and non-zero size
            if out.exists() and out.stat().st_size > 0:
                lock = debate_dir / f".{prefix}_{agent}.lock"
                if lock.exists():
                    try:
                        lock.unlink()
                    except OSError:
                        pass
                if agent not in completed:
                    completed.append(agent)
                continue
            # No output yet: probe pane for capacity error, retry if so
            pane_id = panes.get(i)
            if pane_id is None:
                continue
            try:
                if pane_capacity_error(pane_id, agent):
                    try:
                        retry_pane(panes, i, agent, prefix)
                    except Exception:
                        # Bash `|| true` — swallow retry failures, keep polling
                        pass
            except Exception:
                pass

        if len(completed) == len(agents):
            return True, completed, None

        sleep_fn(poll_interval)
        elapsed += poll_interval

    reason = f"wait_for_outputs timeout after {timeout}s"
    return False, completed, reason
