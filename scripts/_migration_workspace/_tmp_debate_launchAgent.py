"""Migration workspace: debate_launchAgent.

Mirrors bash `launch_agent` from jot-plugin-orchestrator.sh ~L2854-2872.

Bash signature:
    launch_agent pane_id stage agent launch_cmd ready_marker [timeout=120]

Behavior:
  1. Write "debate:<pane_id>\\n" to DEBATE_DIR/.<stage>_<agent>.lock
  2. Send launch_cmd to the tmux pane via tmux_send_and_submit
  3. Poll (1 s intervals, up to `timeout` iterations) the pane scrollback
     for ready_marker (ANSI-stripped, -S -2000 lines)
  4. Return True when found; on timeout call write_failed and return False

Dependencies resolved via workspace-fallback import pattern so this module
can be tested standalone before the monolith absorbs it.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Workspace-fallback imports
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_HERE))

# tmux_send_and_submit and tmux_capturePane come from the already-merged
# tmux helpers in jot_plugin_orchestrator.
try:
    from jot_plugin_orchestrator import tmux_sendAndSubmit, tmux_capturePane
except ImportError:
    from _tmp_tmux_sendAndSubmit import tmux_sendAndSubmit  # type: ignore
    from _tmp_tmux_capturePane import tmux_capturePane  # type: ignore

# write_failed: lives in the monolith (PENDING); fall back to stub if absent.
try:
    from jot_plugin_orchestrator import write_failed  # type: ignore
except ImportError:
    def write_failed(stage: str, reason: str, **kwargs) -> None:  # type: ignore
        """Stub: called when launch_agent times out."""
        pass  # Will be replaced when write_failed is migrated

# Allow tests to patch the sleep call cleanly.
time_sleep = time.sleep

# ---------------------------------------------------------------------------
# YELLOW intent
# ---------------------------------------------------------------------------
# Launch one debate agent inside an existing tmux pane:
#   - Claim the lock file so orchestrator can recover the pane on resume.
#   - Send the CLI command and wait until the ready-marker appears.
#   - If the agent never becomes ready within `timeout` seconds, record the
#     failure and signal the caller with False.
# This is a blocking poll (1 s granularity) mirroring the bash while loop.


def debate_launchAgent(
    *,
    pane_id: str,
    stage: str,
    agent: str,
    launch_cmd: str,
    ready_marker: str,
    debate_dir: str,
    timeout: int = 120,
) -> bool:
    """Launch a debate agent inside *pane_id* and wait for it to become ready.

    Mirrors bash ``launch_agent pane_id stage agent launch_cmd ready_marker [timeout]``.

    Args:
        pane_id:      tmux pane id (e.g. ``%7``).
        stage:        Debate stage label (``r1``, ``r2``, ``synthesis``).
        agent:        Agent name (``gemini``, ``codex``, ``claude``).
        launch_cmd:   Shell command string sent to the pane.
        ready_marker: Substring that signals the agent CLI is ready.
        debate_dir:   Path to the debate working directory.
        timeout:      Max iterations (seconds) to wait. Default 120.

    Returns:
        ``True`` on success; ``False`` on timeout (write_failed also called).
    """
    # Step 1: claim the lock file (bash: printf 'debate:%s\\n' "$pane_id" > lock)
    lock_path = Path(debate_dir) / f".{stage}_{agent}.lock"
    lock_path.write_text(f"debate:{pane_id}\n")

    # Step 2: send the launch command (bash: tmux_send_and_submit "$pane_id" "$launch_cmd")
    tmux_sendAndSubmit(pane_id, launch_cmd)

    # Step 3: poll for ready_marker (bash: while [ "$elapsed" -lt "$timeout" ])
    elapsed = 0
    while elapsed < timeout:
        # Bash: tmux capture-pane -t "$pane_id" -p -S -2000 | tr -d '\033'
        capture = tmux_capturePane(pane_id, scrollback_lines=2000)
        capture = capture.replace("\033", "")
        if ready_marker in capture:
            print(f"[orch] {stage}/{agent} ready after {elapsed}s (pane {pane_id})")
            return True
        time_sleep(1)
        elapsed += 1

    # Step 4: timeout path (bash: echo TIMEOUT >&2; write_failed ...)
    print(
        f"[orch] TIMEOUT: {stage}/{agent} not ready within {timeout}s",
        file=sys.stderr,
    )
    write_failed(stage, f"launch_agent timeout for {agent} after {timeout}s")
    return False
