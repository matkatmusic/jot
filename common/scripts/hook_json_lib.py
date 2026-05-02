"""Hook JSON helpers for Claude Code hooks.

Pure library: every function returns strings. The CLI (hook_json_cli.py)
handles printing and exit codes; the bash shim (hook-json.sh) wires those
back to the original `emit_block` / `check_requirements` interface so
existing `.sh` callers work unmodified.

Migrated from common/scripts/hook-json.sh per MIGRATION_TO_PYTHON.md.
"""
from __future__ import annotations

import json
import shutil

# Canonical install hints for commonly-required tools. Unknown commands
# fall through to their bare name (matching the bash _hookjson_install_hint
# default branch).
INSTALL_HINTS: dict[str, str] = {
    "jq":      "jq (brew install jq)",
    "python3": "python3 (brew install python)",
    "tmux":    "tmux (brew install tmux)",
    "claude":  "claude (https://claude.com/claude-code)",
}


def emitBlockReason(reason: str) -> str:
    """Return the Claude Code 'block' decision JSON for <reason>.

    Caller is responsible for printing. Output is a single line of JSON
    (no trailing newline) - matches `jq -n --arg r "$reason"` semantics.
    """
    return json.dumps({"decision": "block", "reason": reason})


def installHintFor(cmd: str) -> str:
    """Return the install-hint string for <cmd>, or <cmd> itself if unknown."""
    return INSTALL_HINTS.get(cmd, cmd)


def checkRequirements(prefix: str, cmds: list[str]) -> str | None:
    """Probe each command in <cmds>; return None if all present.

    If any are missing, returns the JSON block string the caller should
    print before halting the hook. The reason string format matches the
    bash original exactly:
        "<prefix> needs: <hint1>, <hint2>, ... - install and retry."
    """
    missing = [installHintFor(c) for c in cmds if shutil.which(c) is None]
    if not missing:
        return None
    return emitBlockReason(
        f"{prefix} needs: {', '.join(missing)} - install and retry."
    )
