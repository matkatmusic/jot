"""GREEN implementation of debate_newEmptyPane (migration of bash `new_empty_pane`).

Bash source: scripts/jot-plugin-orchestrator.sh lines 2848-2851
    new_empty_pane() {
      hide_output tmux_retile "$WINDOW_TARGET"
      tmux_new_pane "$WINDOW_TARGET" -c "$CWD" -P -F '#{pane_id}'
    }

Pythonic upgrades vs bash:
- window_target and cwd are explicit parameters (no globals).
- Returns Optional[str] pane id (e.g. "%42") instead of printing it.
- Calls subprocess directly (not tmux_newPane) because tmux_newPane prints
  to stdout rather than returning the pane id; mirrors tmux_splitWorkerPane.
- tmux_retile rc is intentionally discarded (bash `hide_output` parity).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Make the production monolith importable so we can borrow tmux_retile.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jot_plugin_orchestrator import tmux_retile  # noqa: E402


# Retile the target window, then split off a fresh empty pane in <cwd>;
# returns the new pane id (e.g. "%42") or None if tmux failed / emitted nothing.
def debate_newEmptyPane(window_target: str, cwd: str) -> str | None:
    # YELLOW intent: retile first so the new split lands balanced, then run
    # `tmux split-window -t <window> -c <cwd> -P -F '#{pane_id}'` and return
    # the printed pane id (stripped). rc!=0 or empty id -> None.
    tmux_retile(window_target)  # rc discarded (bash hide_output parity).
    argv = [
        "tmux", "split-window",
        "-t", window_target,
        "-c", cwd,
        "-P", "-F", "#{pane_id}",
    ]
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        cmd_str = " ".join(argv)
        combined = (result.stdout or "") + (result.stderr or "")
        print(
            f"[debate_newEmptyPane] command '{cmd_str}' failed: {combined}",
            file=sys.stderr,
        )
        return None
    pane_id = (result.stdout or "").strip()
    if not pane_id:
        return None
    return pane_id
