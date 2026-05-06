"""Unified argv + stdin dispatcher for the jot plugin orchestrator.

Mirrors lines 4117-4177 of `scripts/jot-plugin-orchestrator.sh`:
  1. If sys.argv[1:] is non-empty and argv[0] matches a known subcommand,
     route to that function with the remaining args and exit.
  2. Otherwise read stdin (a hook JSON blob), extract `.prompt`, lstrip,
     normalise `/jot:<skill>` -> `/<skill>` (rewriting the JSON too), and
     dispatch to the matching prompt entrypoint via stdin piping.
"""

from __future__ import annotations

import io
import json
import sys

# --- Argv-mode entrypoints (all merged into jot_plugin_orchestrator) -------
from jot_plugin_orchestrator import (
    jot_sessionStart,
    jot_sessionEnd,
    jot_stop,
    todo_scanOpen,
    todo_launcher,
    todo_stop,
    todo_sessionStart,
    todo_sessionEnd,
    plate_summaryStop,
    plate_summaryWatch,
    jot_collectDiagnostics,
)

# --- Stdin-mode entrypoints: jot_main, plate_main, todo_main, todoList_main
# are workspace pairs in flight; debate_* live in workspace too.
# Try direct import first, fall back to workspace shim. [PENDING merge]
try:
    from jot_plugin_orchestrator import jot_main  # type: ignore
except ImportError:
    from _tmp_jot_main import jot_main  # type: ignore  # PENDING merge

try:
    from jot_plugin_orchestrator import plate_main  # type: ignore
except ImportError:
    from _tmp_plate_main import plate_main  # type: ignore  # PENDING merge

try:
    from jot_plugin_orchestrator import todo_main  # type: ignore
except ImportError:
    from _tmp_todo_main import todo_main  # type: ignore  # PENDING merge

try:
    from jot_plugin_orchestrator import todoList_main  # type: ignore
except ImportError:
    from _tmp_todoList_main import todoList_main  # type: ignore  # PENDING merge

try:
    from jot_plugin_orchestrator import debate_launch  # type: ignore
except ImportError:
    from _tmp_debate_launch import debate_launch  # type: ignore  # PENDING merge

try:
    from jot_plugin_orchestrator import debateRetry_main  # type: ignore
except ImportError:
    from _tmp_debateRetry_main import debateRetry_main  # type: ignore  # PENDING merge

try:
    from jot_plugin_orchestrator import debateAbort_main  # type: ignore
except ImportError:
    from _tmp_debateAbort_main import debateAbort_main  # type: ignore  # PENDING merge

try:
    from jot_plugin_orchestrator import debate_tmuxOrchestrator  # type: ignore
except ImportError:
    from _tmp_debate_tmuxOrchestrator import debate_tmuxOrchestrator  # type: ignore  # PENDING merge


# Argv subcommand -> function map. Order mirrors the bash case block.
_ARGV_DISPATCH = {
    "jot-session-start": jot_sessionStart,
    "jot-session-end": jot_sessionEnd,
    "jot-stop": jot_stop,
    "scan-open-todos": todo_scanOpen,
    "todo-launcher": todo_launcher,
    "todo-stop": todo_stop,
    "todo-session-start": todo_sessionStart,
    "todo-session-end": todo_sessionEnd,
    "plate-summary-stop": plate_summaryStop,
    "plate-summary-watch": plate_summaryWatch,
    "debate-tmux-orchestrator": debate_tmuxOrchestrator,
    "jot-diag-collect": jot_collectDiagnostics,
}

# Prompt prefix -> stdin-mode entrypoint.
_PROMPT_DISPATCH = (
    ("/jot", lambda: jot_main()),
    ("/plate", lambda: plate_main()),
    ("/debate", lambda: debate_launch()),
    ("/debate-retry", lambda: debateRetry_main()),
    ("/debate-abort", lambda: debateAbort_main()),
    ("/todo", lambda: todo_main()),
    ("/todo-list", lambda: todoList_main()),
)


def _matches_prefix(prompt: str, prefix: str) -> bool:
    """True if prompt is exactly `prefix`, `prefix `, or `prefix\\n` led."""
    # Setup: a prompt matches when it equals the slash-command, or when the
    # command is followed by a space or a newline (mirrors the bash case
    # patterns "/X"|"/X "*|$'/X\n'*).
    if prompt == prefix:
        return True
    if prompt.startswith(prefix + " "):
        return True
    if prompt.startswith(prefix + "\n"):
        return True
    return False


def dispatch_main(argv: list[str] | None = None) -> int:
    """Top-level entrypoint mirroring the bash dispatcher.

    Args:
        argv: Argument list to dispatch on (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code suitable for ``sys.exit``.
    """
    if argv is None:
        argv = sys.argv[1:]

    # Argv mode: route by subcommand name and exit. Falls through to stdin
    # mode if argv is empty OR argv[0] is not a known subcommand.
    if argv:
        head = argv[0]
        fn = _ARGV_DISPATCH.get(head)
        if fn is not None:
            rc = fn(argv[1:])
            return int(rc) if rc is not None else 0

    # Stdin mode: read the hook JSON, extract .prompt, normalise.
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = {}
    prompt = data.get("prompt", "") if isinstance(data, dict) else ""
    prompt = prompt.lstrip()

    # Normalise "/jot:<skill>" -> "/<skill>" and rewrite JSON .prompt.
    if prompt.startswith("/jot:"):
        prompt = "/" + prompt[len("/jot:"):]
        if isinstance(data, dict):
            data["prompt"] = prompt
            raw = json.dumps(data)

    # Match prompt prefix; longer prefixes ("/todo-list", "/debate-retry",
    # "/debate-abort") must beat their shorter siblings. Sort by descending
    # length to guarantee that.
    for prefix, fn in sorted(_PROMPT_DISPATCH, key=lambda p: -len(p[0])):
        if _matches_prefix(prompt, prefix):
            # Pipe the (possibly rewritten) JSON into stdin for the callee.
            saved_stdin = sys.stdin
            try:
                sys.stdin = io.StringIO(raw)
                rc = fn()
            finally:
                sys.stdin = saved_stdin
            return int(rc) if rc is not None else 0

    # Default: no prefix matched, exit 0.
    return 0


if __name__ == "__main__":
    sys.exit(dispatch_main())
