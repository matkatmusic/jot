#!/usr/bin/env python3
"""Jot plugin orchestrator (Python).

Canonical Python monolith for the jot plugin. Replaces
`scripts/jot-plugin-orchestrator.sh` function-by-function.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys


# Emit a Claude Code hook JSON block decision: {"decision":"block","reason":<reason>}.
def hookjson_emitBlock(reason: str) -> str:
    return json.dumps({"decision": "block", "reason": reason})


_INSTALL_HINTS: dict[str, str] = {
    "jq": "jq (brew install jq)",
    "python3": "python3 (brew install python)",
    "tmux": "tmux (brew install tmux)",
    "claude": "claude (https://claude.com/claude-code)",
}


# Returns a human-readable install hint for a known dependency; falls back to the bare command name.
def hookjson_installHint(cmd: str) -> str:
    return _INSTALL_HINTS.get(cmd, cmd)


# Probes commands; on any missing, emits a block-decision JSON listing them with install hints, then sys.exit(0).
def hookjson_checkRequirements(prefix: str, *cmds: str) -> None:
    missing: list[str] = []
    for cmd in cmds:
        if shutil.which(cmd) is None:
            missing.append(hookjson_installHint(cmd))
    if not missing:
        return None
    joined = ", ".join(missing)
    payload = hookjson_emitBlock(f"{prefix} needs: {joined} - install and retry.")
    print(payload)
    sys.exit(0)


_TMUX_VERSION_RE = re.compile(r"(\d+)\.(\d+)")


# Probe installed tmux binary version; return 0 if it meets/exceeds `minimum` (format "M.m"), else 1 with a stderr diagnostic.
def tmux_requireVersion(minimum: str) -> int:
    try:
        proc = subprocess.run(
            ["tmux", "-V"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print("[tmux] tmux is not installed", file=sys.stderr)
        return 1

    match = _TMUX_VERSION_RE.search(proc.stdout or "")
    if not match:
        print("[tmux] tmux is not installed", file=sys.stderr)
        return 1
    installed = (int(match.group(1)), int(match.group(2)))

    req_match = _TMUX_VERSION_RE.search(minimum)
    if not req_match:
        print(f"[tmux] invalid minimum version: {minimum}", file=sys.stderr)
        return 1
    required = (int(req_match.group(1)), int(req_match.group(2)))

    if installed < required:
        found = f"{installed[0]}.{installed[1]}"
        print(f"[tmux] tmux {minimum}+ required (found {found})", file=sys.stderr)
        return 1
    return 0


# Calls `tmux set-option` with the given args, returning the exit code; logs failure with caller name to stderr.
def tmux_setOption(*args: str) -> int:
    cmd = ["tmux", "set-option", *args]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
    elif result.stdout:
        print(result.stdout, end="")
    return result.returncode
