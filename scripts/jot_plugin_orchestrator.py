#!/usr/bin/env python3
"""Jot plugin orchestrator (Python).

Canonical Python monolith for the jot plugin. Replaces
`scripts/jot-plugin-orchestrator.sh` function-by-function.
"""
from __future__ import annotations

import glob
import json
import hashlib
import errno
import fcntl
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Optional, Sequence, Type, TypedDict
import io


from common.scripts.hookjson_lib import (
    hookjson_checkRequirements,
    hookjson_emitBlock,
    hookjson_installHint
)

from common.scripts.tmux_lib import (
    tmux_cancelAndSend,
    tmux_capturePane,
    tmux_ensureKeepalivePane,
    tmux_ensureSession,
    tmux_hasSession,
    tmux_killPane,
    tmux_killSession,
    tmux_killWindow,
    tmux_listClients,
    tmux_listPanes,
    tmux_listWindows,
    tmux_newPane,
    tmux_newSession,
    tmux_newWindow,
    tmux_paneHasTitle,
    tmux_requireVersion,
    tmux_retile,
    tmux_selectLayout,
    tmux_selectPane,
    tmux_sendAndSubmit,
    tmux_sendCtrlC,
    tmux_sendEnter,
    tmux_sendKeys,
    tmux_setOption,
    tmux_setOptionForTarget,
    tmux_setOptionForWindow,
    tmux_setOptionGlobally,
    tmux_setPaneTitle,
    tmux_splitWindow,
    tmux_splitWorkerPane,
    tmux_waitForClaudeReadiness,
    tmux_windowExists
)

from common.scripts.claude_lib import (
    claude_buildCmd
)

from common.scripts.jot_lib import (
    jot_initState,
    jot_popFirstFromQueue,
    jot_rotateAudit,
    jot_sendPrompt
)



from common.scripts.claude_lib import (
    claude_permseedLog,
    claude_seedPermissions
)

_DIAG_SECTION_RULE = "═" * 59

from common.scripts.jot_lib import(
    jot_buildClaudeCmd,
    jot_diagIndent,
    jot_diagKv,
    jot_diagSection,
    jot_initState,
    jot_launchPhase2Window,
    jot_popFirstFromQueue,
    jot_rotateAudit,
    jot_sendPrompt,
)

from common.scripts.debate_lib import (
    debate_agentErrorMarkers,
    debate_agentLaunchCmd,
    debate_agentReadyMarker,
    debate_archive,
    debate_buildClaudeCmd,
    debate_buildClaudePrompts,
    debate_checkResumeFeasibility,
    debate_launch,
    debate_tmuxOrchestrator,
)

from common.scripts.plate_lib import (
    plate_main,
    plate_summaryStop,
    plate_summaryWatch,
)

from common.scripts.todo_lib import (
    todo_launcher,
    todo_main,
    todo_scanOpen,
    todo_sessionEnd,
    todo_sessionStart,
    todo_stop,
)


# Standard temp-file header: ensure scripts dir importable for any future
# cross-stub references (FileLock not currently required by this function).
_HERE = Path(__file__).resolve().parent


_MAX_SESSIONS = 999







# ---------------------------------------------------------------------------
# Workspace-fallback imports
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent


_SCRIPTS = _HERE.parent


# Allow tests to patch the sleep call cleanly.
time_sleep = time.sleep



# Pattern matching the lock-file body written by the bash debate daemon:
#   debate:%NNN
_LOCK_PANE_RE = re.compile(r"^debate:(%\d+)$", re.MULTILINE)



# Allow importing the production module's helpers from the parent scripts dir.
_HERE = os.path.dirname(os.path.abspath(__file__))


_SCRIPTS = os.path.dirname(_HERE)


# Per-agent capacity / quota error markers, mirroring bash agent_error_markers.
# Order is preserved (first match wins) to match bash while-read semantics.
_AGENT_ERROR_MARKERS: dict[str, tuple[str, ...]] = {
    "codex": ("Selected model is at capacity", "model is overloaded"),
    "gemini": ("RESOURCE_EXHAUSTED", "Quota exceeded", "You exceeded your current quota"),
    "claude": ("API Error: 529", "overloaded_error"),
}

# ---------------------------------------------------------------------------
# Private helpers (thin wrappers so tests can mock at module boundary)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

from common.scripts.jot_lib import (
    jot_collectDiagnostics
)


# CLI entrypoint mirrors the bash script's positional-arg contract.
def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: plate_summaryWatch <pane_target> <output_file>", file=sys.stderr)
        return 2
    return plate_summaryWatch(pane=argv[0], output_file=argv[1])


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))




_POLL_ATTEMPTS = 5


_POLL_SLEEP = 0.2



# Max retries polling the tmux_target sidecar file.
_SIDECAR_RETRIES = 5


_SIDECAR_SLEEP = 0.2


# Audit log max lines before rotation.
_AUDIT_MAX_LINES = 1000



from common.scripts.jot_lib import (
    jot_sessionEnd,
    jot_sessionStart
)

_LOCK_LINE_RE = re.compile(r"^debate:(%[0-9]+)$", re.MULTILINE)




# Allow imports from the production module living one dir up.
_THIS_DIR = Path(__file__).resolve().parent


_SCRIPTS_DIR = _THIS_DIR.parent



from common.scripts.jot_lib import (
    jot_stop,
)

from common.scripts.git_lib import ( 
    getGitBranchNameOrFail,
    getGitRecentCommitHashes,
    getGitUncommittedFilenames,
    getGitRepoRoot,
)
    
from common.scripts.jot_lib import (
    jot_main
)

if __name__ == "__main__":
    sys.exit(jot_main())


# Strict /plate prompt regex - mirrors bash grep -qE pattern exactly.
_PROMPT_RE_PLATE = re.compile(
    r"^/plate"
    r"(\s+(--done|--drop|--trash"
    r"|--recycle(\s+--list|\s+\S+)?"
    r"|--show"
    r"|--next( +[0-9A-Za-z._@#$+-]+)?"
    r"))?$"
)



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
    """Top-level entrypoint mirroring the bash dispatcher.

    1. If argv[0] matches a known subcommand, route to it and exit.
    2. Otherwise read stdin (a hook JSON blob), extract `.prompt`, lstrip,
       normalise `/jot:<skill>` -> `/<skill>` (rewriting JSON too), and
       dispatch to the matching prompt entrypoint via stdin piping.
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
