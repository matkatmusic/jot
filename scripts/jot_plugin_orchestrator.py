#!/usr/bin/env python3
"""Entry point for the jot plugin.

Routes UserPromptSubmit hook payloads and argv-mode subcommands to the
appropriate `<x>_main` in `common/scripts/<x>_lib.py`. Returns 0 with empty
stdout when the prompt is not consumed by this plugin, signalling silent
passthrough so Claude Code processes the prompt normally.
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

# Bootstrap: when invoked as a standalone script (Claude Code hook, manual run),
# the repo root is not on sys.path. Pytest already arranges this via rootdir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.scripts.util_lib import _matches_prefix
from common.scripts.jot_lib import (
    jot_collectDiagnostics,
    jot_main,
    jot_sessionEnd,
    jot_sessionStart,
    jot_stop,
)
from common.scripts.todo_lib import (
    todoList_main,
    todo_launcher,
    todo_main,
    todo_scanOpen,
    todo_sessionEnd,
    todo_sessionStart,
    todo_stop,
)
from common.scripts.plate_lib import (
    plate_main,
    plate_summaryStop,
    plate_summaryWatch,
)
from common.scripts.debate_lib import (
    debateAbort_main,
    debateRetry_main,
    debate_launch,
    debate_tmuxOrchestrator,
)

# Test seam: legacy patch target preserved until Phase 4 sweep retargets it.
time_sleep = time.sleep


# Argv subcommand -> function map. Order mirrors the bash case block.
_ARGV_DISPATCH: dict = {
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
_PROMPT_DISPATCH: tuple = (
    ("/jot", lambda: jot_main()),
    ("/plate", lambda: plate_main()),
    ("/debate", lambda: debate_launch()),
    ("/debate-retry", lambda: debateRetry_main()),
    ("/debate-abort", lambda: debateAbort_main()),
    ("/todo", lambda: todo_main()),
    ("/todo-list", lambda: todoList_main()),
)


def dispatch_main(argv: list[str] | None = None) -> int:
    """Route argv subcommands and stdin hook payloads to lib entrypoints.

    1. If argv[0] matches a known subcommand, route to it and return its rc.
    2. Otherwise read stdin (a hook JSON blob), extract `.prompt`, lstrip,
       normalise `/jot:<skill>` -> `/<skill>` (rewriting the JSON too), and
       dispatch to the matching prompt entrypoint via stdin piping.
    3. Unmatched prompts return 0 with no stdout (silent passthrough).
    """
    if argv is None:
        argv = sys.argv[1:]

    if argv:
        head = argv[0]
        fn = _ARGV_DISPATCH.get(head)
        if fn is not None:
            rc = fn(argv[1:])
            return int(rc) if rc is not None else 0

    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = {}
    prompt = data.get("prompt", "") if isinstance(data, dict) else ""
    prompt = prompt.lstrip()

    if prompt.startswith("/jot:"):
        prompt = "/" + prompt[len("/jot:"):]
        if isinstance(data, dict):
            data["prompt"] = prompt
            raw = json.dumps(data)

    for prefix, fn in sorted(_PROMPT_DISPATCH, key=lambda p: -len(p[0])):
        if _matches_prefix(prompt, prefix):
            saved_stdin = sys.stdin
            try:
                sys.stdin = io.StringIO(raw)
                rc = fn()
            finally:
                sys.stdin = saved_stdin
            return int(rc) if rc is not None else 0

    return 0


if __name__ == "__main__":
    sys.exit(dispatch_main())
