"""Workspace migration of bash `jot_stop` -> Python `jot_stop`.

Strict RED-YELLOW-GREEN TDD workspace stub. Production module is
`scripts/jot_plugin_orchestrator.py`; this file is throwaway scaffolding
used only to drive RED tests, then GREEN'd in place.

Bash source:
  scripts/jot-plugin-orchestrator.sh, jot_stop() at lines 3420-3517.

Behavioral contract (extracted from bash docstring + body):
  * Args: input_file, tmpdir_inv, state_dir (all required, all absolute).
  * Missing-arg case: log "[jot-stop] missing args ..." to stderr, return 0
    (silent exit-style — caller is a Stop hook).
  * Read TMUX_TARGET sidecar at "$TMPDIR_INV/tmux_target" SYNCHRONOUSLY,
    retrying up to 5 times with 0.2s sleep when the file is empty/missing.
    Empty after retries: log to stderr, return 0.
  * Initialize state dir, then append a single audit line to
    "$STATE_DIR/audit.log":
       "<ISO ts> SUCCESS <input_file>"   if head -1 starts with PROCESSED:
       "<ISO ts> FAIL <input_file> (no PROCESSED marker)"   otherwise
       "<ISO ts> FAIL <input_file> (input.txt missing)"     if file absent
  * Rotate audit log to <=1000 lines.
  * Background subshell: sleep 0.5; tmux kill-pane $TMUX_TARGET;
    tmux retile jot:jots. Forking detail is collapsed in Python — we call
    the helpers directly. Test seam: `_background_kill` callable, so tests
    can synchronously assert kill+retile happened.

Side effects asserted by tests:
  * audit.log contents (SUCCESS/FAIL line shape).
  * tmux_killPane called with the sidecar pane id.
  * tmux_retile called with "jot:jots".
  * state files created via jot_initState (queue.txt etc.).
  * Return code int (0 on every documented exit).
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# Allow imports from the production module living one dir up.
_THIS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _THIS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Re-import the production helpers; tests monkeypatch THESE module-level names
# on `_tmp_jot_stop`, so we keep the rebinding here intentional.
from jot_plugin_orchestrator import (  # noqa: E402
    jot_initState,
    jot_rotateAudit,
    tmux_killPane,
    tmux_retile,
)


def _isoTimestampLocal() -> str:
    # Match bash `date -Iseconds` (local-tz, seconds precision).
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _readSidecar(target_file: Path, attempts: int = 5, sleep_s: float = 0.2) -> str:
    # Mirror bash retry loop: 5 attempts, 0.2s sleep between non-final attempts.
    for i in range(attempts):
        try:
            if target_file.is_file() and target_file.stat().st_size > 0:
                first = target_file.read_text().split("\n", 1)[0]
                if first:
                    return first
        except OSError:
            pass
        if i < attempts - 1:
            time.sleep(sleep_s)
    return ""


def _appendAudit(audit_path: Path, line: str) -> None:
    with audit_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _backgroundKill(pane_target: str, retile_target: str = "jot:jots") -> None:
    # Bash forks a `( sleep 0.5; kill-pane; retile ) &` subshell so the hook
    # can return BEFORE tmux signals claude. In Python we expose this as a
    # function so tests can monkeypatch it; default impl does the work
    # synchronously (no sleep, no fork — the hook semantics are the same
    # because we are not the claude process being killed in test).
    tmux_killPane(pane_target)
    tmux_retile(retile_target)


def jot_stop(
    input_file: str,
    tmpdir_inv: str,
    state_dir: str,
    *,
    background_kill: Callable[[str, str], None] | None = None,
) -> int:
    """Stop hook for a per-invocation claude pane.

    Reads the tmux pane id sidecar, appends one SUCCESS/FAIL audit line,
    rotates the log, then kills the pane and retiles the jots window.

    Returns 0 on every documented exit (matches bash `exit 0` parity).
    """
    # Argument guard — bash echoes to stderr and exits 0. We do the same.
    if not input_file or not tmpdir_inv or not state_dir:
        print(
            "[jot-stop] missing args (input_file, tmpdir_inv, state_dir)",
            file=sys.stderr,
        )
        return 0

    tmpdir_path = Path(tmpdir_inv)
    target_file = tmpdir_path / "tmux_target"
    tmux_target = _readSidecar(target_file)
    if not tmux_target:
        print(
            "[jot-stop] tmux_target sidecar empty after retries",
            file=sys.stderr,
        )
        return 0

    # State dir must exist + standard files must be present.
    jot_initState(state_dir)
    audit_path = Path(state_dir) / "audit.log"

    ts = _isoTimestampLocal()
    input_path = Path(input_file)
    if input_path.is_file():
        try:
            with input_path.open("r", encoding="utf-8") as fh:
                first_line = fh.readline().rstrip("\n")
        except OSError:
            first_line = ""
        if first_line.startswith("PROCESSED:"):
            _appendAudit(audit_path, f"{ts} SUCCESS {input_file}")
        else:
            _appendAudit(
                audit_path, f"{ts} FAIL {input_file} (no PROCESSED marker)"
            )
    else:
        _appendAudit(audit_path, f"{ts} FAIL {input_file} (input.txt missing)")

    jot_rotateAudit(audit_path, 1000)

    bg = background_kill if background_kill is not None else _backgroundKill
    bg(tmux_target, "jot:jots")
    return 0
