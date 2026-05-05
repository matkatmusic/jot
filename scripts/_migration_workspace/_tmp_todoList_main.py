"""Workspace migration of bash `todo_list_main` (lines 3294-3345 of
`scripts/jot-plugin-orchestrator.sh`) to Python.

Target signature: `todoList_main() -> int`

RELAXED_COVERAGE: Bash uses `jq` to parse PROMPT and CWD; this Python port
uses `json.loads` directly on stdin (jq is still listed as a runtime
requirement to match the bash check). Bash sourced silencers/hook-json/git
helpers; this port uses `subprocess` for `git rev-parse --show-toplevel`
directly when no `git_lib.git_getRepoRoot` is available in scope. Behavior
preserved: silent exit on non-/todo-list inputs, block-emit on missing repo,
missing Todos/, and on the formatter producing empty output.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# In the merged monolith, these are module-level. Workspace fallback imports
# them lazily so this file is runnable standalone for unit tests.
try:
    from jot_plugin_orchestrator import (  # type: ignore[import-not-found]
        hookjson_emitBlock,
        hookjson_checkRequirements,
    )
except Exception:  # pragma: no cover - fallback for isolated workspace tests
    def hookjson_emitBlock(reason: str) -> str:
        return json.dumps({"decision": "block", "reason": reason})

    def hookjson_checkRequirements(prefix: str, *cmds: str) -> None:
        import shutil
        missing = [c for c in cmds if shutil.which(c) is None]
        if missing:
            print(hookjson_emitBlock(f"{prefix} needs: {', '.join(missing)} - install and retry."))
            sys.exit(0)


# Resolve the plugin root: prefer CLAUDE_PLUGIN_ROOT env, else the parent of
# this file's parent (mirrors bash `dirname/..`).
def _resolvePluginRoot() -> Path:
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parent.parent


# Resolve the git repo root for a given cwd via `git -C <cwd> rev-parse
# --show-toplevel`. Returns None when not inside a git checkout.
def _gitRepoRoot(cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return out or None


# Hook entrypoint for /todo-list: reads the Claude Code UserPromptSubmit JSON
# from stdin, validates the prompt, locates the repo's Todos/ folder, runs the
# format_open_todos.py helper, and emits a block-decision JSON wrapping the
# formatted output (or a friendly fallback message). Always returns 0.
def todoList_main() -> int:
    plugin_root = _resolvePluginRoot()
    os.environ["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)

    raw = sys.stdin.read()

    # Fast-path substring check: if the raw payload does not contain the
    # literal `"/todo-list` token, exit silently. Mirrors bash glob.
    if '"/todo-list' not in raw:
        return 0

    hookjson_checkRequirements("todo-list", "jq", "python3")

    # Parse JSON and pull the prompt; tolerate malformed JSON by treating it
    # as no-prompt (silent exit, matching bash jq's empty fallback).
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0

    prompt_raw = payload.get("prompt") or ""
    if not isinstance(prompt_raw, str):
        return 0
    # Strip leading whitespace only (bash strip_stdin.py trims leading WS).
    prompt = prompt_raw.lstrip()

    # Strict match: exactly `/todo-list` or `/todo-list ` followed by anything.
    if prompt != "/todo-list" and not prompt.startswith("/todo-list "):
        return 0

    cwd_val = payload.get("cwd")
    cwd = cwd_val if isinstance(cwd_val, str) and cwd_val else os.getcwd()

    repo_root = _gitRepoRoot(cwd)
    if not repo_root:
        print(hookjson_emitBlock("todo-list: not a git repository."))
        return 0

    todos_dir = Path(repo_root) / "Todos"
    if not todos_dir.is_dir():
        print(hookjson_emitBlock("No Todos/ folder found in this project."))
        return 0

    formatter = plugin_root / "skills" / "todo-list" / "scripts" / "format_open_todos.py"
    env = os.environ.copy()
    env["TODOS_DIR"] = str(todos_dir)
    proc = subprocess.run(
        ["python3", str(formatter)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    formatted = proc.stdout

    # Bash uses `[ -z "$FORMATTED" ]` which treats whitespace-only as
    # non-empty; preserve that exact semantics by checking len(formatted) == 0.
    if not formatted:
        print(hookjson_emitBlock("No open TODOs."))
    else:
        print(hookjson_emitBlock(formatted))
    return 0
