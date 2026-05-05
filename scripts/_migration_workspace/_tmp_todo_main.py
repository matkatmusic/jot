"""Workspace stub for todo_main migration.

Source bash: scripts/jot-plugin-orchestrator.sh lines 3202-3281.
Target: merge into scripts/jot_plugin_orchestrator.py (do not edit yet).

RELAXED_COVERAGE: bash uses a noclobber retry loop with `mktemp -u` to claim a
unique pending file. Python uses tempfile.mkstemp which is atomic+O_EXCL by
construction, so the retry loop is unnecessary. The on-disk filename pattern
differs (`pending-XXXXXX.json` vs the random suffix mkstemp picks), but the
contract is "unique file under STATE_DIR with prefix=pending- suffix=.json".
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Imported in the real merge from jot_plugin_orchestrator.py:
#   hookjson_emitBlock, hookjson_checkRequirements
# Workspace-fallback shims (replaced at merge time):
try:
    from jot_plugin_orchestrator import (  # type: ignore
        hookjson_emitBlock,
        hookjson_checkRequirements,
    )
except Exception:  # pragma: no cover - fallback for isolated tests
    def hookjson_emitBlock(reason: str) -> str:
        return json.dumps({"decision": "block", "reason": reason})

    def hookjson_checkRequirements(prefix: str, *cmds: str) -> None:
        return None


# Resolves the git repo root for `cwd` via `git -C <cwd> rev-parse --show-toplevel`.
# Returns the path string on success, or "" on any failure (non-git dir, missing git).
def _git_get_repo_root(cwd: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# Bash entrypoint port: /todo PreToolUse-style hook. Reads a Claude Code hook JSON
# payload from stdin, validates the prompt is "/todo" or "/todo <idea>", and on a
# match writes a pending-claim JSON file under <repo_root>/Todos/.todo-state/ for
# the foreground claude to dispatch. Always returns 0; uses emit_block only on the
# "not in a git repo" branch. Errors on missing CLAUDE_PLUGIN_DATA env.
def todo_main() -> int:
    # Required env: data dir for plugin state (also default log dir).
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not plugin_data:
        raise RuntimeError("todo plugin env not set: CLAUDE_PLUGIN_DATA")

    # CLAUDE_PLUGIN_ROOT defaults to the parent of this script's directory
    # (matches bash `cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd`).
    plugin_root = os.environ.setdefault(
        "CLAUDE_PLUGIN_ROOT",
        str(Path(__file__).resolve().parent.parent),
    )
    scripts_dir = f"{plugin_root}/skills/todo/scripts"
    log_file = os.environ.get("TODO_LOG_FILE") or f"{plugin_data}/todo-log.txt"

    # Best-effort log dir create; ignore failures (matches bash hide_errors).
    try:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    # Read raw hook payload from stdin.
    hook_input = sys.stdin.read()

    # Fast-path: if the payload doesn't even mention "/todo as a substring,
    # this is not for us. Silent exit.
    if '"/todo' not in hook_input:
        return 0

    # Append raw input to the rolling log (best-effort).
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().astimezone().isoformat()} HOOK_INPUT {hook_input}\n")
    except OSError:
        pass

    # Verify required CLI tools are on PATH (jq retained for parity with siblings).
    hookjson_checkRequirements("todo", "jq", "python3", "tmux", "claude")

    # Parse JSON payload; on any malformed input, treat as not-for-us.
    try:
        payload = json.loads(hook_input)
    except (ValueError, TypeError):
        return 0
    if not isinstance(payload, dict):
        return 0

    prompt = payload.get("prompt") or ""
    if not isinstance(prompt, str):
        return 0
    # Strip leading whitespace; remove embedded NUL bytes (parity with strip_stdin.py).
    prompt = prompt.lstrip().replace("\x00", "")

    # Strict slash-command match: exactly "/todo" or "/todo " followed by an idea.
    if prompt != "/todo" and not prompt.startswith("/todo "):
        return 0

    # Extract idea: everything after "/todo" with one optional leading space stripped.
    idea = prompt[len("/todo"):]
    if idea.startswith(" "):
        idea = idea[1:]

    # Pull metadata fields with the same defaults the bash uses.
    session_id = payload.get("session_id") or "unknown"
    transcript_path = payload.get("transcript_path") or ""
    cwd = payload.get("cwd") or os.getcwd()

    # Require a git repo; emit a block message (not an error) if missing.
    repo_root = _git_get_repo_root(cwd)
    if not repo_root:
        print(hookjson_emitBlock(
            "todo requires a git repository. Run 'git init' in your project root."
        ))
        return 0

    # State dir lives under the repo for visibility/co-location with Todos/.
    state_dir = Path(repo_root) / "Todos" / ".todo-state"
    state_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

    # Atomic unique pending-file claim via mkstemp (O_EXCL under the hood).
    fd, pending_file = tempfile.mkstemp(
        prefix="pending-", suffix=".json", dir=str(state_dir)
    )
    os.close(fd)

    # Build the claim payload; json.dump handles all string escaping.
    claim = {
        "session_id": session_id,
        "transcript_path": transcript_path,
        "cwd": cwd,
        "repo_root": repo_root,
        "idea": idea,
        "timestamp": timestamp,
        "todo_plugin_root": plugin_root,
        "todo_scripts_dir": scripts_dir,
        "pending_file": pending_file,
        "created_at": datetime.now().astimezone().isoformat(),
    }
    with open(pending_file, "w", encoding="utf-8") as fh:
        json.dump(claim, fh)

    # Silent return: no emit_block. The foreground claude dispatches the skill.
    return 0
