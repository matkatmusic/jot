"""
todo_sessionEnd: Remove a temporary todo session directory.

RELAXED_COVERAGE note: The original bash function called `exit 0` in both
the rejection and success paths, terminating the entire shell process.
This Python version returns instead, preserving the caller's control flow.
Callers that previously relied on process exit must handle the return
themselves (the orchestrator loop simply continues to the next iteration).
"""

import shutil
import sys

# Prefixes that are considered safe to remove.
_VALID_PREFIXES: tuple[str, ...] = ("/tmp/todo.", "/private/tmp/todo.")


def todo_sessionEnd(tmpdir_inv: str) -> None:
    """Remove a todo session tmpdir after validating its prefix.

    Args:
        tmpdir_inv: Absolute path to the temporary directory to remove.

    Behaviour:
        - If *tmpdir_inv* starts with a recognised prefix, delegate removal
          to ``shutil.rmtree`` with ``ignore_errors=True`` and return.
        - If the prefix is not recognised, print a warning to stderr and
          return without touching the filesystem.
        - An empty string is treated as an unrecognised prefix.
    """
    if not any(tmpdir_inv.startswith(prefix) for prefix in _VALID_PREFIXES):
        print(
            f"[todo-session-end] refusing to rm unexpected path: {tmpdir_inv}",
            file=sys.stderr,
        )
        return

    shutil.rmtree(tmpdir_inv, ignore_errors=True)
