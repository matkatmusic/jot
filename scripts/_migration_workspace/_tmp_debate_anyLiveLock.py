"""Migration workspace stub for debate_anyLiveLock.

Mirrors bash `any_live_lock` (jot-plugin-orchestrator.sh:2357-2367).
Scans `<dir>/.*.lock` files for `debate:%<n>` pane-id markers and
returns True iff any such pane is still alive in tmux.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# Allow imports from the production scripts/ tree if needed by the test runner.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_LOCK_LINE_RE = re.compile(r"^debate:(%[0-9]+)$", re.MULTILINE)


def _live_pane_ids() -> set[str]:
    """Return the set of currently-live tmux pane ids ('%N').

    Failures (no tmux, no server, non-zero rc) are swallowed and yield
    an empty set, matching bash `hide_errors tmux list-panes ...`.
    """
    # Test action: query tmux for every pane across every session.
    try:
        proc = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#{pane_id}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return set()
    if proc.returncode != 0:
        return set()
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def debate_anyLiveLock(debate_dir: str | os.PathLike[str]) -> bool:
    """True iff `<debate_dir>/.*.lock` references a still-live tmux pane.

    Behavior port of bash `any_live_lock`:
      * Iterate hidden `*.lock` files (glob `.*.lock`) in `debate_dir`.
      * Skip non-files (matches `[ -f "$lock" ] || continue`).
      * Extract the first line matching `^debate:(%<digits>)$`.
      * If that pane id appears in `tmux list-panes -a`, return True.
      * Return False if no lock yields a live pane.
    """
    d = Path(debate_dir)
    if not d.is_dir():
        return False

    # Collect candidate lock files: hidden, ending in `.lock`. Bash glob
    # `.*.lock` matches any file beginning with `.` and ending in `.lock`.
    locks = sorted(p for p in d.glob(".*.lock") if p.is_file())
    if not locks:
        return False

    live = _live_pane_ids()
    if not live:
        return False

    for lock in locks:
        try:
            text = lock.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = _LOCK_LINE_RE.search(text)
        if not m:
            continue
        pane_id = m.group(1)
        if pane_id in live:
            return True
    return False
