"""GREEN implementation: debate_claimSession.

Migrated from bash `debate_claim_session` (jot-plugin-orchestrator.sh
lines ~2154-2176). Atomically claims the lowest-unused `debate-N` tmux
session by relying on `tmux new-session -d -s <name>` returning nonzero
on name collision (race-free across concurrent /debate hooks).

Production callers should let `tmux_runner` default to the real
subprocess driver. Tests inject a fake.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable, List

# Standard temp-file header: ensure scripts dir importable for any future
# cross-stub references (FileLock not currently required by this function).
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))

# FileLock fallback retained per migration policy in case future cross-stubs
# need it; this function itself does not lock — tmux is the atomic primitive.
try:  # pragma: no cover - import resolution
    from jot_plugin_orchestrator import FileLock  # type: ignore
except ImportError:  # pragma: no cover
    try:
        from _tmp_FileLock import FileLock  # type: ignore  # noqa: F401
    except ImportError:
        FileLock = None  # type: ignore


_MAX_SESSIONS = 999


def _default_tmux_runner(argv: List[str]) -> int:
    """Real tmux invocation: run `argv` and return the exit code.

    stdout/stderr suppressed because collisions are an expected control-flow
    signal, not an error condition the user should see (mirrors the bash
    `hide_errors` wrapper around the original tmux call).
    """
    proc = subprocess.run(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return proc.returncode


def debate_claimSession(
    keepalive_cmd: str,
    *,
    tmux_runner: Callable[[List[str]], int] = _default_tmux_runner,
) -> str:
    """Atomically claim the lowest-unused `debate-N` tmux session.

    Args:
        keepalive_cmd: Shell command that becomes the argv of the new session's
            first window (named `main`). Typically a long-lived no-op like
            `sleep 86400` so the session persists for daemon attachment.
        tmux_runner: Injectable runner that takes argv and returns rc. The
            default invokes real tmux; tests pass a fake.

    Returns:
        The claimed session name, e.g. ``"debate-7"``.

    Raises:
        RuntimeError: If no slot in ``debate-1`` .. ``debate-999`` is free.
    """
    for n in range(1, _MAX_SESSIONS + 1):
        session = f"debate-{n}"
        argv = [
            "tmux", "new-session", "-d",
            "-s", session,
            "-x", "200",
            "-y", "60",
            "-n", "main",
            keepalive_cmd,
        ]
        if tmux_runner(argv) == 0:
            return session
    raise RuntimeError(
        f"debate_claimSession: exhausted {_MAX_SESSIONS} session slots"
    )
