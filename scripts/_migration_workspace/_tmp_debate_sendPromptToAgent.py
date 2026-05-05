"""Temp workspace for migrating bash `send_prompt` -> debate_sendPromptToAgent.

GREEN implementation. Imports already-migrated tmux helpers from the production
monolith. `debate_writeFailed` is a forward dependency (still in bash); a stub
is defined here and tests monkeypatch it.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Ensure we can import the production module and its already-migrated helpers.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jot_plugin_orchestrator import (  # noqa: E402
    tmux_capturePane,
    tmux_sendAndSubmit,
)


# Forward dependency placeholder; real debate_writeFailed is still in bash.
# Tests monkeypatch this symbol; production wiring will replace it when the
# debate-cluster failure-writer is migrated.
def debate_writeFailed(stage: str, reason: str) -> None:  # pragma: no cover
    raise NotImplementedError(
        "debate_writeFailed not yet migrated; tests must monkeypatch this stub."
    )


# Sends a "read <instructions> and perform them" prompt to the agent's pane via
# tmux_sendAndSubmit, then polls the pane (capture-pane with 2000 lines of
# scrollback, ANSI-stripped, fixed-string match against basename(instructions))
# for up to 30s in 1s ticks. Returns 0 when the marker appears, 1 on timeout.
# On timeout, logs "[orch] TIMEOUT: <stage>/<agent> did not echo prompt" to
# stderr and calls debate_writeFailed(stage, "send_prompt timeout for <agent>
# after 30s") (parity with bash write_failed). Marker derivation, scrollback
# size, poll cadence, and timeout are bash-faithful.
def debate_sendPromptToAgent(
    pane_id: str,
    stage: str,
    agent: str,
    instructions: str,
) -> int:
    rc = tmux_sendAndSubmit(pane_id, f"read {instructions} and perform them")
    # Bash sends the prompt unconditionally and ignores send_and_submit rc;
    # we preserve that behavior (no early return on rc != 0).
    _ = rc
    marker = Path(instructions).name
    elapsed = 0
    while elapsed < 30:
        captured = tmux_capturePane(pane_id, 2000)
        # Bash strips ANSI escapes via `tr -d '\033'` before fixed-string grep.
        stripped = (captured or "").replace("\x1b", "")
        if marker in stripped:
            print(f"[orch] {stage}/{agent} prompt received after {elapsed}s")
            return 0
        time.sleep(1)
        elapsed += 1
    print(
        f"[orch] TIMEOUT: {stage}/{agent} did not echo prompt",
        file=sys.stderr,
    )
    debate_writeFailed(stage, f"send_prompt timeout for {agent} after 30s")
    return 1
