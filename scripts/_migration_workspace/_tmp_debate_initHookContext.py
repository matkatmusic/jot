"""GREEN implementation of debate_initHookContext.

Port of bash `init_hook_context` (jot-plugin-orchestrator.sh ~L2274-L2294).
Returns a context dict instead of mutating shell globals; callers in the
Python port read keys from the dict.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import IO, Any


def debate_initHookContext(stdin: IO[str] | None = None) -> dict[str, Any]:
    """Initialise the debate hook context.

    Reads hook JSON from `stdin` (or `sys.stdin` if not provided) and returns
    a dict with the following keys (matching the bash globals):

        SCRIPTS_DIR     - $CLAUDE_PLUGIN_ROOT/skills/debate/scripts
        LOG_FILE        - $DEBATE_LOG_FILE or $CLAUDE_PLUGIN_DATA/debate-log.txt
        INPUT           - raw stdin text
        CWD             - JSON .cwd, fallback to os.getcwd()
        TRANSCRIPT_PATH - JSON .transcript_path, "" if absent
        REPO_ROOT       - git toplevel for CWD, "" if not in a repo

    Raises RuntimeError if CLAUDE_PLUGIN_ROOT or CLAUDE_PLUGIN_DATA is unset
    (mirrors bash `: "${VAR:?...}"` guard).
    """
    # Required env vars (bash `:?` semantics).
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not plugin_root:
        raise RuntimeError("debate plugin env not set: CLAUDE_PLUGIN_ROOT")
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not plugin_data:
        raise RuntimeError("debate plugin env not set: CLAUDE_PLUGIN_DATA")

    scripts_dir = str(Path(plugin_root) / "skills" / "debate" / "scripts")

    # LOG_FILE: env override wins; otherwise default under plugin data dir.
    log_file = os.environ.get("DEBATE_LOG_FILE") or str(
        Path(plugin_data) / "debate-log.txt"
    )
    # `mkdir -p "$(dirname "$LOG_FILE")"` (errors hidden in bash; we ignore).
    try:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    # Read raw stdin (preserve exactly, matches bash $(cat) semantics).
    src = stdin if stdin is not None else sys.stdin
    raw_input = src.read()

    # Parse JSON; tolerate empty / malformed input by treating as no fields.
    try:
        payload = json.loads(raw_input) if raw_input.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
    except json.JSONDecodeError:
        payload = {}

    cwd = payload.get("cwd") or os.getcwd()
    transcript_path = payload.get("transcript_path") or ""

    # `git -C "$CWD" rev-parse --show-toplevel`, swallow failure -> "".
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        repo_root = result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, FileNotFoundError):
        repo_root = ""

    return {
        "SCRIPTS_DIR": scripts_dir,
        "LOG_FILE": log_file,
        "INPUT": raw_input,
        "CWD": str(cwd),
        "TRANSCRIPT_PATH": str(transcript_path),
        "REPO_ROOT": repo_root,
    }
