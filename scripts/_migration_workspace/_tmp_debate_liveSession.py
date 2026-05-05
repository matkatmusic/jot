#!/usr/bin/env python3
"""debate_liveSession — workspace migration module.

Migrated from bash live_debate_session() (jot-plugin-orchestrator.sh:2375-2385).

YELLOW intent:
  Iterate .*.lock files in debate_dir. For each, read the pane_id from a line
  matching 'debate:%NNN'. Ask tmux display-message for the session name owning
  that pane. Return the first non-empty session name found; return "" on total
  failure. Self-healing: no stored session-name artifact needed.
"""
from __future__ import annotations

import glob
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from jot_plugin_orchestrator import *  # noqa: F401,F403
except ImportError:
    pass

# Pattern matching the lock-file body written by the bash debate daemon:
#   debate:%NNN
_LOCK_PANE_RE = re.compile(r"^debate:(%\d+)$", re.MULTILINE)


def debate_liveSession(debate_dir: str) -> str:
    """Return the tmux session name currently hosting the debate's panes.

    Recovers the session by reading still-live lock-file pane IDs and querying
    tmux. Self-heals across session renames; no separate session-name artifact
    to maintain. Returns empty string when no live session is found.

    Args:
        debate_dir: Path to the debate directory (e.g. Debates/<ts>_<slug>/).

    Returns:
        Session name string (e.g. "debate-1") or "" on failure.
    """
    # Glob for hidden lock files: .*.lock
    pattern = str(Path(debate_dir) / ".*.lock")
    lock_files = sorted(glob.glob(pattern))

    for lock_path in lock_files:
        # Read lock content; skip if file disappeared (TOCTOU)
        try:
            content = Path(lock_path).read_text()
        except OSError:
            continue

        # Extract pane_id from line matching "debate:%NNN"
        match = _LOCK_PANE_RE.search(content)
        if not match:
            continue
        pane_id = match.group(1)

        # Ask tmux for the session name owning this pane
        try:
            proc = subprocess.run(
                ["tmux", "display-message", "-p", "-t", pane_id, "#{session_name}"],
                capture_output=True,
                text=True,
            )
        except OSError:
            continue

        if proc.returncode != 0:
            continue

        session = proc.stdout.strip()
        if session:
            return session

    return ""
