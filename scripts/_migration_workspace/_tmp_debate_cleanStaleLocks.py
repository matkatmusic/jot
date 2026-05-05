"""GREEN implementation of debate_cleanStaleLocks.

Migrates bash `clean_stale_locks` from scripts/jot-plugin-orchestrator.sh
(lines 3018-3033). RELAXED_COVERAGE: tests authored from intent only.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Ensure workspace dir on sys.path (header per migration convention).
sys.path.insert(0, str(Path(__file__).resolve().parent))


# YELLOW intent: scan DEBATE_DIR/.{stage}_*.lock; for each lock parse "debate:%N";
# remove the lock if the pane id is missing/malformed, the pane no longer exists in
# the tmux window, or the pane's current command differs from the agent name.

_PANE_ID_RE = re.compile(r"^debate:(%\d+)$", re.MULTILINE)


# Boundary seam: returns the set of live pane ids (e.g. {"%5","%7"}) in WINDOW_TARGET.
# Tests patch this; production callers pass `window_target` from the orchestrator.
def _listLivePaneIds(window_target: str) -> set[str]:
    try:
        out = subprocess.run(
            ["tmux", "list-panes", "-t", window_target, "-F", "#{pane_id}"],
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if out.returncode != 0:
        return set()
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


# Boundary seam: returns the pane's current foreground command (e.g. "gemini","codex","bash").
# Tests patch this.
def _paneCurrentCommand(pane_id: str) -> str:
    try:
        out = subprocess.run(
            ["tmux", "display-message", "-p", "-t", pane_id, "#{pane_current_command}"],
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if out.returncode != 0:
        return ""
    return out.stdout.strip()


# Remove stale per-agent lock files for `stage` under `debate_dir`. A lock is stale
# when its recorded pane id is unparseable, no longer present in `window_target`,
# or whose pane is running a command other than the lock's agent name.
def debate_cleanStaleLocks(
    debate_dir: Path,
    stage: str,
    window_target: str = "",
) -> None:
    debate_dir = Path(debate_dir)
    prefix = f".{stage}_"
    locks = sorted(debate_dir.glob(f"{prefix}*.lock"))
    if not locks:
        return
    live_panes: set[str] | None = None  # lazily fetched on first lock that needs it
    for lock in locks:
        if not lock.is_file():
            continue
        # Derive agent name from filename: ".<stage>_<agent>.lock"
        agent = lock.name[len(prefix):-len(".lock")]
        # Parse "debate:%N" payload (matches bash sed regex exactly).
        try:
            payload = lock.read_text()
        except OSError:
            payload = ""
        match = _PANE_ID_RE.search(payload)
        if match is None:
            lock.unlink(missing_ok=True)
            continue
        pane_id = match.group(1)
        if live_panes is None:
            live_panes = _listLivePaneIds(window_target)
        if pane_id not in live_panes:
            lock.unlink(missing_ok=True)
            continue
        current = _paneCurrentCommand(pane_id)
        if current != agent:
            lock.unlink(missing_ok=True)
