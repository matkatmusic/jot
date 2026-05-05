"""Migration workspace: debate_newEmptyPane.

Bash source: new_empty_pane() at line 2847 of jot-plugin-orchestrator.sh
  hide_output tmux_retile "$WINDOW_TARGET"
  tmux_new_pane "$WINDOW_TARGET" -c "$CWD" -P -F '#{pane_id}'

Signature change (documented in migration map):
  Bash globals $WINDOW_TARGET and $CWD replaced with explicit parameters
  window_target and cwd.  Callers must pass both explicitly.

RELAXED_COVERAGE: tmux_retile return code is intentionally discarded; bash
  used hide_output (suppress stdout/stderr, ignore rc).  Python matches that
  behaviour by calling tmux_retile and ignoring the rc.
"""
from __future__ import annotations

import subprocess
import sys

from jot_plugin_orchestrator import tmux_retile, tmux_splitWorkerPane


def debate_newEmptyPane(window_target: str, cwd: str) -> str | None:
    """Create a new empty pane in window_target rooted at cwd.

    Mirrors bash new_empty_pane():
      1. Re-tiles the window (output/rc suppressed, matching hide_output).
      2. Splits a new pane with -c <cwd> -P -F '#{pane_id}' and no command,
         returning the new pane id (e.g. '%42') or None on failure.

    Args:
        window_target: tmux target string for the window (e.g. 'session:window').
        cwd: Working directory for the new pane (-c flag to split-window).

    Returns:
        The new pane id string on success, or None on tmux failure or empty output.
    """
    # Re-tile; rc ignored (bash used hide_output which discards rc).
    tmux_retile(window_target)

    # Split a new pane with no command (-P -F '#{pane_id}' to capture id).
    # Passing cmd="" appends an empty string to argv; tmux split-window treats
    # a trailing empty token as "no command" on macOS tmux >= 3.x.  Use the
    # inline subprocess call (same pattern as tmux_splitWorkerPane in
    # jot_plugin_orchestrator.py) for full control and to avoid passing "".
    argv = [
        "tmux", "split-window",
        "-t", window_target,
        "-c", cwd,
        "-P", "-F", "#{pane_id}",
    ]
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(0).f_code.co_name
        cmd_str = " ".join(argv)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
        return None
    pane_id = (result.stdout or "").strip()
    if not pane_id:
        return None
    return pane_id
