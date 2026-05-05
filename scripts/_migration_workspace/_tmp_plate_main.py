"""
Migration workspace: plate_main

Bash source: scripts/jot-plugin-orchestrator.sh lines 2028-2114

plate_main is the Claude Code plugin hook entrypoint for /plate commands.
It reads a JSON hook payload from stdin, dispatches the correct cli.py
subcommand, and emits the output as a single hookjson block.

RELAXED_COVERAGE: The ERR-trap equivalent (crash -> emit_block) is
implemented via a bare except in the outer try/except. Line-number info
is not preserved because Python tracebacks serve the same purpose.

Signature change vs bash:
- Bash entrypoint inherits stdin/env from the shell.
- Python reads os.environ and sys.stdin explicitly; all injectable
  dependencies are accepted as keyword-only args for testability.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Workspace-fallback imports
# ---------------------------------------------------------------------------
try:
    from jot_plugin_orchestrator import (  # type: ignore[import]
        hookjson_emitBlock,
        hookjson_checkRequirements,
    )
except ImportError:
    def hookjson_emitBlock(text: str) -> str:  # type: ignore[misc]
        """Stub: replaced by monolith import after merge."""
        raise NotImplementedError("hookjson_emitBlock not available in workspace")

    def hookjson_checkRequirements(prefix: str, *cmds: str) -> None:  # type: ignore[misc]
        """Stub: replaced by monolith import after merge."""
        raise NotImplementedError("hookjson_checkRequirements not available in workspace")

try:
    from git_lib import getGitRepoRoot, ensureGitignoreEntry  # type: ignore[import]
except ImportError:
    def getGitRepoRoot(directory: str) -> str | None:  # type: ignore[misc]
        """Stub: replaced by monolith import after merge."""
        raise NotImplementedError("getGitRepoRoot not available in workspace")

    def ensureGitignoreEntry(repo_root: str, pattern: str) -> None:  # type: ignore[misc]
        """Stub: replaced by monolith import after merge."""
        raise NotImplementedError("ensureGitignoreEntry not available in workspace")


# Strict prompt regex — mirrors bash grep -qE pattern exactly.
_PROMPT_RE = re.compile(
    r"^/plate"
    r"(\s+(--done|--drop|--trash"
    r"|--recycle(\s+--list|\s+\S+)?"
    r"|--show"
    r"|--next( +[0-9A-Za-z._@#$+-]+)?"
    r"))?$"
)


def plate_main(
    *,
    _stdin: str | None = None,
    _environ: dict[str, str] | None = None,
    _hookjson_emitBlock: object = None,
    _hookjson_checkRequirements: object = None,
    _getGitRepoRoot: object = None,
    _ensureGitignoreEntry: object = None,
    _subprocess_run: object = None,
) -> int:
    """Claude Code plugin hook entrypoint for /plate commands.

    Reads JSON from sys.stdin (or _stdin for tests), dispatches to cli.py,
    emits output as a hookjson block.

    Returns 0 in all handled cases (errors are surfaced via emit_block).
    Raises RuntimeError for missing required env vars.
    """
    # Resolve injectable dependencies.
    emit_block = _hookjson_emitBlock or hookjson_emitBlock
    check_reqs = _hookjson_checkRequirements or hookjson_checkRequirements
    get_repo_root = _getGitRepoRoot or getGitRepoRoot
    ensure_gitignore = _ensureGitignoreEntry or ensureGitignoreEntry
    run = _subprocess_run or subprocess.run
    env = _environ if _environ is not None else dict(os.environ)

    # ── Validate required env vars ────────────────────────────────────────
    plugin_root = env.get("CLAUDE_PLUGIN_ROOT")
    if not plugin_root:
        raise RuntimeError(
            "plate plugin env not set -- not running under Claude Code plugin harness"
            " (CLAUDE_PLUGIN_ROOT missing)"
        )
    plugin_data = env.get("CLAUDE_PLUGIN_DATA")
    if not plugin_data:
        raise RuntimeError(
            "plate plugin env not set -- not running under Claude Code plugin harness"
            " (CLAUDE_PLUGIN_DATA missing)"
        )

    # Provisional log path (used until REPO_ROOT is resolved).
    plate_log_override = env.get("PLATE_LOG_FILE", "")
    log_file = plate_log_override if plate_log_override else os.path.join(plugin_data, "plate-log.txt")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    # ── Fast-path bail-out ────────────────────────────────────────────────
    # Substring match on raw JSON before any parsing.
    raw_input = _stdin if _stdin is not None else sys.stdin.read()
    if '"/plate' not in raw_input:
        return 0

    check_reqs("plate", "python3")

    # ── Strict prompt regex ───────────────────────────────────────────────
    try:
        payload: dict = json.loads(raw_input)
    except json.JSONDecodeError:
        return 0

    prompt: str = payload.get("prompt") or ""
    prompt = prompt.lstrip()

    if not _PROMPT_RE.match(prompt):
        return 0

    # ── Extract payload fields ────────────────────────────────────────────
    session_id: str = payload.get("session_id") or "?"
    transcript_path: str = payload.get("transcript_path") or ""
    cwd: str = payload.get("cwd") or os.getcwd()

    # ── Repo-root detection ───────────────────────────────────────────────
    repo_root: str = get_repo_root(cwd) or ""
    if not repo_root:
        print(emit_block("plate requires a git repository. Run 'git init' in your project root."))
        return 0

    # ── Promote LOG_FILE to per-repo path ────────────────────────────────
    if not plate_log_override:
        log_file = os.path.join(repo_root, ".plate", "plate-log.txt")
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        # Keep the log gitignored so plate_push does not see a dirty worktree.
        ensure_gitignore(repo_root, ".plate/plate-log.txt")

    # Export so spawned summary agents write to the same file.
    os.environ["PLATE_LOG_FILE"] = log_file

    # Log this invocation.
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    try:
        with open(log_file, "a") as fh:
            fh.write(f"{ts} plate prompt=\"{prompt}\"\n")
    except OSError:
        pass

    # ── Map prompt -> cli.py argv ─────────────────────────────────────────
    cli_path = os.path.join(plugin_root, "common", "scripts", "plate", "cli.py")

    if prompt == "/plate":
        args = ["push", session_id, transcript_path, repo_root]
    elif prompt == "/plate --done":
        args = ["done", repo_root]
    elif prompt == "/plate --drop":
        args = ["drop", repo_root]
    elif prompt == "/plate --trash":
        args = ["trash", repo_root]
    elif prompt == "/plate --recycle":
        args = ["recycle", repo_root]
    elif prompt == "/plate --recycle --list":
        args = ["recycle", repo_root, "--list"]
    elif prompt.startswith("/plate --recycle "):
        name = prompt[len("/plate --recycle "):]
        args = ["recycle", repo_root, name]
    elif prompt == "/plate --show":
        args = ["show", repo_root]
    elif prompt == "/plate --next":
        args = ["next", repo_root]
    elif prompt.startswith("/plate --next "):
        name = prompt[len("/plate --next "):]
        args = ["next", repo_root, name]
    else:
        print(emit_block(f"plate: unrecognized variant '{prompt}'"))
        return 0

    # ── Dispatch to cli.py ────────────────────────────────────────────────
    try:
        result = run(
            ["python3", cli_path] + args,
            capture_output=True,
            text=True,
        )
        out = (result.stdout or "") + (result.stderr or "")
    except Exception as exc:  # noqa: BLE001
        ts2 = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        try:
            with open(log_file, "a") as fh:
                fh.write(f"{ts2} FAIL plate crashed: {exc}\n")
        except OSError:
            pass
        out = f"plate crashed: {exc}"

    print(emit_block(out))
    return 0
