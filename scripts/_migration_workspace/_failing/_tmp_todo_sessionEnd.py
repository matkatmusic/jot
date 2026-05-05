"""todo_sessionEnd — SessionEnd hook for per-invocation claude panes.

Wipes the per-invocation /tmp/todo.XXXXXX directory that held this
claude's settings.json and copied-in helper scripts.

Bash source: todo_session_end() @ jot-plugin-orchestrator.sh line 3784
             (todo-session-end.sh cluster).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


# Accepted path prefixes for the per-invocation tmpdir.
# /tmp/todo.* covers Linux; /private/tmp/todo.* covers macOS (symlink target).
_ALLOWED_PREFIXES: tuple[str, ...] = (
    "/tmp/todo.",
    "/private/tmp/todo.",
)


def todo_sessionEnd(tmpdir_inv: str) -> None:
    """Delete the per-invocation tmpdir created by todo_launcher.

    Args:
        tmpdir_inv: Absolute path to the temp directory (e.g. /tmp/todo.abcXYZ).
                    Must match /tmp/todo.* or /private/tmp/todo.* — any other
                    value is silently ignored to prevent accidental rm -rf of
                    arbitrary paths.
    """
    # Safety guard: refuse to delete anything that does not match the expected
    # path pattern.  Without this, a misconfigured hook could wipe an arbitrary
    # directory (mirrors the bash `case` guard in the original).
    if not any(tmpdir_inv.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
        print(
            f"[todo-session-end] refusing to rm unexpected path: {tmpdir_inv}",
            file=sys.stderr,
        )
        return

    # YELLOW: rm -rf the validated tmpdir.
    target = Path(tmpdir_inv)
    if target.exists():
        shutil.rmtree(target)
