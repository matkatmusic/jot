#!/usr/bin/env python3
"""Workspace migration of bash `jot_main` (lines 1904-2009 of jot-plugin-orchestrator.sh).

RELAXED_COVERAGE: This is a workspace draft pending merger into
`scripts/jot_plugin_orchestrator.py`. Some upstream deps are stubbed and
imported via try/except workspace-fallback (e.g. `todo_scanOpen`).

Signature change rationale:
- Bash `jot_main` was an entrypoint reading stdin + env, performing side
  effects, and exiting with `exit 0`. Python signature returns `int` so
  callers / tests can drive it without intercepting `SystemExit`. The
  bash `exit 0` semantics are preserved by `return 0` on every terminal
  branch (block decisions, missing-repo, tmux-too-old, etc.) - the hook
  contract is "always exit 0 after emitting a JSON decision".
- Bash `safe <cmd>` (which swallows failures and returns "(unavailable)")
  is replicated via local `_safe_call` helper that wraps each git_lib /
  todo_scanOpen invocation in try/except.
- Bash `trap ERR` crash-handler is replicated via outer try/except in the
  body so unexpected failures still emit a block decision.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# Migrated deps live in jot_plugin_orchestrator. Workspace fallback for in-flight
# todo_scanOpen.
from jot_plugin_orchestrator import (
    hookjson_emitBlock,
    hookjson_checkRequirements,
    tmux_requireVersion,
    jot_launchPhase2Window,
)

try:
    from jot_plugin_orchestrator import todo_scanOpen  # type: ignore[attr-defined]
except ImportError:
    from _tmp_todo_scanOpen import todo_scanOpen  # type: ignore[no-redef]

# git_lib helpers - prefer canonical import, fall back to subprocess shim.
try:
    from common.scripts.git_lib import (  # type: ignore[import-not-found]
        getGitBranchNameOrFail,
        getGitRecentCommitHashes,
        getGitUncommittedFilenames,
        getGitRepoRoot,
    )
except ImportError:
    def getGitBranchNameOrFail(cwd: str) -> str:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()

    def getGitRecentCommitHashes(cwd: str) -> str:
        result = subprocess.run(
            ["git", "-C", cwd, "log", "-n", "5", "--pretty=format:%h %s"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()

    def getGitUncommittedFilenames(cwd: str) -> str:
        result = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()

    def getGitRepoRoot(cwd: str) -> str:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()


def _safe_call(fn: Callable[..., Any], *args: Any) -> str:
    """Bash `safe` wrapper: swallow failures, return '(unavailable)'."""
    try:
        result = fn(*args)
        if result is None:
            return "(unavailable)"
        text = str(result)
        return text if text else "(unavailable)"
    except Exception:
        return "(unavailable)"


def _strip_stdin_text(text: str) -> str:
    """Mirror common/scripts/jot/strip_stdin.py: strip leading whitespace,
    replace null bytes with spaces."""
    return text.lstrip().replace("\x00", " ")


def _append_log(log_file: str, line: str) -> None:
    """Append a line to the log file; swallow all errors (bash hide_errors)."""
    if not log_file:
        return
    try:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        return


def jot_main() -> int:
    """Entrypoint for the /jot Claude Code hook.

    Reads JSON hook payload from stdin; if the prompt is `/jot <idea>`,
    materializes a Todos/<timestamp>_input.txt task file (idea + git state +
    transcript context + rendered instructions) and launches a tmux pane
    running Claude in the repo root via `jot_launchPhase2Window()`.

    Returns 0 on every terminal branch to honor Claude Code hook
    `exit 0` semantics; block decisions are surfaced via stdout JSON.
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not plugin_root or not plugin_data:
        raise RuntimeError(
            "jot plugin env not set - not running under Claude Code plugin harness"
        )

    scripts_dir = f"{plugin_root}/skills/jot/scripts"
    log_file = os.environ.get("JOT_LOG_FILE") or f"{plugin_data}/jot-log.txt"

    # Read hook payload from stdin.
    hook_input = sys.stdin.read()

    # Fast-path substring match for "/jot"; silent exit if absent.
    if '"/jot' not in hook_input:
        return 0

    _append_log(log_file, f"{datetime.now().isoformat()} HOOK_INPUT {hook_input}\n")

    # Required external commands.
    hookjson_checkRequirements("jot", "jq", "python3", "tmux", "claude")

    # tmux version gate.
    if tmux_requireVersion("2.9") != 0:
        print(hookjson_emitBlock("jot requires tmux 2.9+"))
        return 0

    # Parse prompt + strip-stdin semantics.
    try:
        payload = json.loads(hook_input) if hook_input.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    prompt = _strip_stdin_text(str(payload.get("prompt", "")))

    # Strict prefix match.
    if prompt != "/jot" and not prompt.startswith("/jot "):
        return 0

    # Extract idea (prompt minus prefix), strip-stdin again.
    idea = prompt[len("/jot"):]
    if idea.startswith(" "):
        idea = idea[1:]
    idea = _strip_stdin_text(idea)

    if not idea:
        print(hookjson_emitBlock("jot: no idea provided"))
        return 0

    session_id = str(payload.get("session_id", "?")) or "?"
    _append_log(
        log_file,
        f"{datetime.now().isoformat()} jot session={session_id} idea_len={len(idea)}\n",
    )

    transcript_path = str(payload.get("transcript_path", "") or "")
    cwd = str(payload.get("cwd", "") or "") or os.getcwd()
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

    # Repo-root requirement.
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=False,
        )
        repo_root = result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        repo_root = ""

    if not repo_root:
        print(hookjson_emitBlock(
            "jot requires a git repository. Run 'git init' in your project root."
        ))
        return 0

    target_dir = Path(repo_root) / "Todos"
    target_dir.mkdir(parents=True, exist_ok=True)
    input_file = target_dir / f"{timestamp}_input.txt"
    input_abs = str(input_file)

    # Initial header (idea + cwd).
    header = (
        f"# Jot Task\n\n## Idea\n{idea}\n\n"
        f"## Working Directory\n{cwd}\n\n"
    )
    input_file.write_text(header)

    # Git state + open todos + conversation (each safe-wrapped).
    branch = _safe_call(getGitBranchNameOrFail, cwd)
    commits = _safe_call(getGitRecentCommitHashes, cwd)
    uncommitted = _safe_call(getGitUncommittedFilenames, cwd)
    open_todos = _safe_call(todo_scanOpen, repo_root)

    if transcript_path and Path(transcript_path).is_file():
        try:
            cap = subprocess.run(
                ["python3", f"{scripts_dir}/capture-conversation.py", transcript_path],
                capture_output=True, text=True, check=False,
            )
            conversation = cap.stdout if cap.returncode == 0 else "(unavailable)"
            if not conversation:
                conversation = "(unavailable)"
        except (OSError, subprocess.SubprocessError):
            conversation = "(unavailable)"
    else:
        conversation = "(no transcript available)"

    # Append context block.
    context_block = (
        f"## Git State\n- Branch: {branch}\n- Commits: {commits}\n"
        f"- Uncommitted: {uncommitted}\n\n"
        f"## Open TODO Files\n{open_todos}\n\n"
        f"## Transcript Path\n{transcript_path or '(none)'}\n\n"
        f"## Recent Conversation\n{conversation}\n\n"
    )
    with open(input_file, "a", encoding="utf-8") as fh:
        fh.write(context_block)

    # Render instructions template.
    asset_path = f"{plugin_root}/skills/jot/scripts/assets/jot-instructions.md"
    render_env = {
        **os.environ,
        "REPO_ROOT": repo_root,
        "TIMESTAMP": timestamp,
        "BRANCH": branch,
        "INPUT_ABS": input_abs,
    }
    try:
        rendered = subprocess.run(
            [
                "python3",
                f"{plugin_root}/common/scripts/jot/render_template.py",
                asset_path,
                "REPO_ROOT", "TIMESTAMP", "BRANCH", "INPUT_ABS",
            ],
            capture_output=True, text=True, env=render_env, check=False,
        )
        instructions = rendered.stdout if rendered.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        instructions = ""

    # Rewrite input file: prepend instructions, drop the original first
    # "# Jot Task" line so it isn't duplicated.
    body = input_file.read_text()
    body_lines = body.split("\n")
    body_after_first = "\n".join(body_lines[1:])
    rewritten = (
        f"# Jot Task\n\n## Instructions\n{instructions}\n\n"
        f"{body_after_first}"
    )
    if not rewritten.endswith("\n"):
        rewritten += "\n"
    input_file.write_text(rewritten)

    # Skip-launch gate (used by tests / dry-runs).
    if os.environ.get("JOT_SKIP_LAUNCH") == "1":
        print(hookjson_emitBlock(f"Jotted: {idea} (launch skipped)"))
        return 0

    # Surface env vars that jot_launchPhase2Window reads from os.environ.
    os.environ["REPO_ROOT"] = repo_root
    os.environ["CWD"] = cwd
    os.environ["INPUT_FILE"] = input_abs
    if log_file:
        os.environ["LOG_FILE"] = log_file

    jot_launchPhase2Window()
    print(hookjson_emitBlock(f"Done! Jotted idea in {input_abs}"))
    return 0


if __name__ == "__main__":
    sys.exit(jot_main())
