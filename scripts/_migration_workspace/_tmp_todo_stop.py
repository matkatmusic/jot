"""todo_stop — Stop hook for per-invocation claude panes (todo skill).

Migrated from: jot-plugin-orchestrator.sh todo_stop() ~lines 3666-3726.
YELLOW intent: read tmux pane id from sidecar, check PROCESSED: marker,
append SUCCESS/FAIL to audit.log, rotate log, then kill pane + retile
asynchronously so the hook exits cleanly before tmux signals the process.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from jot_plugin_orchestrator import (
    jot_initState,
    jot_rotateAudit,
    tmux_killPane,
    tmux_retile,
)

# Max retries polling the tmux_target sidecar file.
_SIDECAR_RETRIES = 5
_SIDECAR_SLEEP = 0.2

# Audit log max lines before rotation.
_AUDIT_MAX_LINES = 1000


def todo_stop(
    input_file: str,
    tmpdir_inv: str,
    state_dir: str,
) -> int:
    """Stop hook for the /todo skill's per-invocation claude pane.

    Fires when claude finishes responding to its one job.

    Ordering contract (mirrors jot_stop):
      1. Read tmux_target sidecar SYNCHRONOUSLY before anything else.
      2. Write audit entry.
      3. Rotate audit log.
      4. Kill pane + retile in a background thread (so this hook returns
         before tmux signals the claude process).

    Args:
        input_file:  Absolute path to the input.txt claude was told to process.
        tmpdir_inv:  Absolute path to the per-invocation tmpdir (/tmp/todo.XXXX).
        state_dir:   Path to todo state dir (for audit.log).

    Returns:
        0 always (matches bash exit 0 semantics; errors logged to stderr).
    """
    # --- arg guard -----------------------------------------------------------
    if not input_file or not tmpdir_inv or not state_dir:
        print("[todo-stop] missing args (input_file, tmpdir_inv, state_dir)", file=sys.stderr)
        return 0

    # --- read tmux_target sidecar SYNCHRONOUSLY (ordering contract) ----------
    target_file = Path(tmpdir_inv) / "tmux_target"
    tmux_target = ""
    for _ in range(_SIDECAR_RETRIES):
        if target_file.is_file() and target_file.stat().st_size > 0:
            first = target_file.read_text().splitlines()
            if first and first[0].strip():
                tmux_target = first[0].strip()
                break
        time.sleep(_SIDECAR_SLEEP)

    if not tmux_target:
        print("[todo-stop] tmux_target sidecar empty after retries", file=sys.stderr)
        return 0

    # --- ensure state dir and audit.log exist --------------------------------
    state_path = Path(state_dir)
    state_path.mkdir(parents=True, exist_ok=True)
    audit_path = state_path / "audit.log"
    audit_path.touch(exist_ok=True)

    # --- audit entry ---------------------------------------------------------
    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    inp = Path(input_file)
    if inp.is_file():
        content = inp.read_text()
        first_line = content.splitlines()[0] if content else ""
        if first_line.startswith("PROCESSED:"):
            with audit_path.open("a") as fh:
                fh.write(f"{ts} SUCCESS {input_file}\n")
            # SUCCESS: remove input file (matches bash rm -f)
            try:
                inp.unlink()
            except FileNotFoundError:
                pass
        else:
            with audit_path.open("a") as fh:
                fh.write(f"{ts} FAIL {input_file} (no PROCESSED marker)\n")
    else:
        with audit_path.open("a") as fh:
            fh.write(f"{ts} FAIL {input_file} (input.txt missing)\n")

    # --- rotate audit --------------------------------------------------------
    jot_rotateAudit(audit_path, _AUDIT_MAX_LINES)

    # --- kill pane + retile in background (hook must return first) -----------
    _pane = tmux_target  # captured in closure before thread starts

    def _cleanup() -> None:
        time.sleep(0.5)
        try:
            tmux_killPane(_pane)
        except Exception:
            pass
        try:
            tmux_retile("todo:todos")
        except Exception:
            pass

    t = threading.Thread(target=_cleanup, daemon=True)
    t.start()

    return 0
