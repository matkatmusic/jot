"""Workspace stub for shell_waitForFile (migration of bash `wait_for_file`).

Generic shell utility: poll a path until it exists AND is non-empty, or
timeout elapses. Mirrors bash `[ -s "$path" ]` semantics (size > 0).

RELAXED_COVERAGE: bash `wait_for_file` additionally removes
.synthesis_claude.lock, prints progress, and calls write_failed on
timeout. Those side effects are debate-specific and stay with the caller
in Python -- the generic helper returns a bool.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# YELLOW intent: poll filesystem until target path is a non-empty file or
# the cumulative wall-clock elapsed time meets/exceeds `timeout`. Use the
# module-level `time.sleep` and `time.monotonic` so tests can monkeypatch.
# Return True on success, False on timeout. Empty (zero-byte) files do not
# count as ready -- this preserves bash `[ -s ]` semantics.
def shell_waitForFile(path: str, timeout: float, poll_interval: float = 5.0) -> bool:
    """Block until `path` is a non-empty file or `timeout` seconds pass.

    Args:
        path: filesystem path to poll.
        timeout: maximum seconds to wait (inclusive upper bound).
        poll_interval: seconds between polls (bash default: 5).

    Returns:
        True if the file became non-empty before timeout, else False.
    """
    target = Path(path)
    deadline = time.monotonic() + float(timeout)
    while True:
        try:
            if target.is_file() and target.stat().st_size > 0:
                return True
        except OSError:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_interval)
