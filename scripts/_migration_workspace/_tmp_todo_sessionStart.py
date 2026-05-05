"""GREEN implementation of todo_sessionStart.

Python port of bash todo_session_start() (jot-plugin-orchestrator.sh lines 3732-3779).

Contract:
  todo_sessionStart(input_file: str, tmpdir_inv: str) -> int

  SessionStart hook for per-invocation claude panes. Fires once when claude
  starts in a fresh tmux pane. Polls <tmpdir_inv>/tmux_target (written by
  todo_launcher) for the tmux pane id, waits for the Claude TUI ready glyph,
  then sends the initial "Read <input.txt> ..." prompt.

  Returns:
    0 - success or soft failure (missing args, sidecar missing/empty)
    1 - claude TUI not ready (hard failure - bash exit 1 semantics)
    other - rc from jot_sendPrompt
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Standard workspace sys.path: makes jot_plugin_orchestrator importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from jot_plugin_orchestrator import (
    jot_sendPrompt,
    tmux_waitForClaudeReadiness,
)

_TAG = "[todo-session-start]"
_POLL_ATTEMPTS = 5
_POLL_SLEEP = 0.2


def todo_sessionStart(input_file: str, tmpdir_inv: str) -> int:
    """SessionStart hook: poll sidecar, wait for Claude TUI, send prompt.

    Args:
        input_file: Absolute path to input.txt for this /todo invocation.
        tmpdir_inv: Absolute path to per-invocation tmpdir (/tmp/todo.XXXXXX).

    Returns:
        0 on success or soft failure; 1 if Claude TUI not ready.
    """
    # Validate required args (bash: exit 0 on missing).
    if not input_file or not tmpdir_inv:
        print(f"{_TAG} missing args (input_file, tmpdir_inv)", file=sys.stderr)
        return 0

    # Poll <tmpdir_inv>/tmux_target up to 5 times (bash: for _ in 1..5 with sleep 0.2).
    target_file = Path(tmpdir_inv) / "tmux_target"
    tmux_target = ""
    for _ in range(_POLL_ATTEMPTS):
        if target_file.is_file() and target_file.stat().st_size > 0:
            first_line = target_file.read_text().splitlines()[0].strip()
            if first_line:
                tmux_target = first_line
                break
        time.sleep(_POLL_SLEEP)

    if not tmux_target:
        print(f"{_TAG} tmux_target sidecar empty after retries", file=sys.stderr)
        return 0

    # Wait for Claude TUI ready glyph (bash: tmux_wait_for_claude_readiness).
    if tmux_waitForClaudeReadiness(tmux_target) != 0:
        print(f"{_TAG} claude TUI not ready, aborting send", file=sys.stderr)
        return 1

    # Send "Read <input.txt> and follow the instructions ..." prompt.
    return jot_sendPrompt(tmux_target, input_file)
