from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from common.scripts.git_lib import GitError, getGitRepoRoot, ensureGitignoreEntry
from common.scripts.hookjson_lib import hookjson_checkRequirements, hookjson_emitBlock
from common.scripts.tmux_lib import _default_tmux_send


# Strict /plate prompt regex - mirrors bash grep -qE pattern exactly.
_PROMPT_RE_PLATE = re.compile(
    r"^/plate"
    r"(\s+(--done|--drop|--trash"
    r"|--recycle(\s+--list|\s+\S+)?"
    r"|--show"
    r"|--next( +[0-9A-Za-z._@#$+-]+)?"
    r"))?$"
)


def plate_summaryStop(repo: str, branch: str, output_file: str) -> int:
    """Forward agent summary to plate cli; append audit line; never raise.

    Args:
        repo: absolute path to the repo whose plate branch is being summarised.
        branch: parent branch name (the plate branch is `<branch>-plate`).
        output_file: absolute path the spawned agent wrote its summary to.

    Returns:
        0 always. A non-zero return would let SessionEnd treat this hook as
        failed and surface noise to the user; the bash original exits 0
        unconditionally and we preserve that contract.
    """
    # Guard: any missing required arg -> silent no-op (mirrors bash early exit).
    if not repo or not branch or not output_file:
        return 0

    # Guard: agent never wrote the file -> nothing to forward.
    if not Path(output_file).is_file():
        return 0

    # Resolve plate_cli.py: bash uses `cd "$(dirname "$0")/../../.." && pwd`. In the
    # Python migration the equivalent is the repo root above scripts/. We
    # locate it relative to this module so the function works whether installed
    # in the plugin tree or run from the migration workspace.
    repo_root = Path(__file__).resolve().parents[2]
    cli_path = repo_root / "common" / "scripts" / "plate" / "plate_cli.py"

    # Resolve the audit log location with the same precedence as bash:
    #   1) $PLATE_LOG_FILE     (test/override hook)
    #   2) <repo>/.plate/plate-log.txt
    #   3) $CLAUDE_PLUGIN_DATA/plate-log.txt or ~/.claude/plugins/data/plate-jot-dev/plate-log.txt
    plate_log_env = os.environ.get("PLATE_LOG_FILE", "")
    if plate_log_env:
        log_file = Path(plate_log_env)
    elif Path(repo).is_dir():
        log_file = Path(repo) / ".plate" / "plate-log.txt"
    else:
        plugin_data = os.environ.get(
            "CLAUDE_PLUGIN_DATA",
            str(Path.home() / ".claude" / "plugins" / "data" / "plate-jot-dev"),
        )
        log_file = Path(plugin_data) / "plate-log.txt"

    # Best-effort mkdir of log dir; bash uses `2>/dev/null || true`.
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    # Run the cli command. Bash captures stdout+stderr together (`2>&1`) and
    # always continues (`|| true`). We mirror that with check=False and a
    # broad except, since this hook must never raise.
    out_text = ""
    try:
        result = subprocess.run(
            ["python3", str(cli_path), "set-plate-summary", repo, branch, output_file],
            capture_output=True,
            text=True,
            check=False,
        )
        out_text = (result.stdout or "") + (result.stderr or "")
    except Exception as exc:  # noqa: BLE001 — hook must never propagate.
        out_text = f"<exception: {exc}>"

    # Append one audit line. Bash format:
    #   "<ts> plate-summary-stop repo=<repo> branch=<branch> out=<OUT>"
    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    line = f"{ts} plate-summary-stop repo={repo} branch={branch} out={out_text.strip()}\n"
    try:
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        # Bash silences log-write failures with `2>/dev/null || true`.
        pass

    return 0


# Fire-and-forget watchdog for the plate-summary agent. Polls output_file;
# once it appears non-empty, sends "/exit" + Enter to the tmux pane to
# trigger graceful shutdown. Returns 0 on success, 1 on timeout.
def plate_summaryWatch(
    pane: str,
    output_file: str,
    timeout: Optional[int] = None,
    interval: Optional[int] = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    tmux_send: Callable[[str, str], None] = _default_tmux_send,
) -> int:
    # Resolve env-knob defaults exactly like the bash `${VAR:-default}` form.
    if timeout is None:
        timeout = int(os.environ.get("PLATE_SUMMARY_WATCH_TIMEOUT", "600"))
    if interval is None:
        interval = int(os.environ.get("PLATE_SUMMARY_WATCH_INTERVAL", "2"))

    out_path = Path(output_file)
    elapsed = 0

    # Bash uses `[ -s FILE ]` (exists AND size>0). Path.stat().st_size==0
    # for an empty file, and FileNotFoundError covers the missing case.
    def _ready() -> bool:
        try:
            return out_path.stat().st_size > 0
        except FileNotFoundError:
            return False

    while elapsed < timeout:
        if _ready():
            # Two-step send: first inserts literal "/exit" into the prompt
            # buffer, second submits with Enter. Errors are swallowed --
            # if the pane has gone away we still exit 0.
            try:
                tmux_send(pane, "/exit")
            except Exception:
                pass
            try:
                tmux_send(pane, "Enter")
            except Exception:
                pass
            return 0
        sleep(interval)
        elapsed += interval

    # Timeout: leave the pane alive for operator inspection.
    return 1


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
    """Claude Code plugin hook entrypoint for /plate commands."""
    emit_block = _hookjson_emitBlock or hookjson_emitBlock
    check_reqs = _hookjson_checkRequirements or hookjson_checkRequirements
    get_repo_root = _getGitRepoRoot or getGitRepoRoot
    ensure_gitignore = _ensureGitignoreEntry or ensureGitignoreEntry
    run = _subprocess_run or subprocess.run
    env = _environ if _environ is not None else dict(os.environ)

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

    plate_log_override = env.get("PLATE_LOG_FILE", "")
    log_file = plate_log_override if plate_log_override else os.path.join(plugin_data, "plate-log.txt")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    raw_input = _stdin if _stdin is not None else sys.stdin.read()
    if '/plate' not in raw_input:
        return 0

    check_reqs("plate", "python3")

    try:
        payload: dict = json.loads(raw_input)
    except json.JSONDecodeError:
        return 0

    prompt: str = payload.get("prompt") or ""
    prompt = prompt.lstrip()

    if not _PROMPT_RE_PLATE.match(prompt):
        return 0

    session_id: str = payload.get("session_id") or "?"
    transcript_path: str = payload.get("transcript_path") or ""
    cwd: str = payload.get("cwd") or os.getcwd()

    try:
        repo_root: str = str(get_repo_root(cwd) or "")
    except GitError:
        repo_root = ""
    if not repo_root:
        print(emit_block("plate requires a git repository. Run 'git init' in your project root."))
        return 0

    if not plate_log_override:
        log_file = os.path.join(repo_root, ".plate", "plate-log.txt")
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        ensure_gitignore(repo_root, ".plate/plate-log.txt")

    os.environ["PLATE_LOG_FILE"] = log_file

    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    try:
        with open(log_file, "a") as fh:
            fh.write(f"{ts} plate prompt=\"{prompt}\"\n")
    except OSError:
        pass

    cli_path = os.path.join(plugin_root, "common", "scripts", "plate", "plate_cli.py")

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

    try:
        result = run(
            ["python3", cli_path] + args,
            capture_output=True,
            text=True,
        )
        out = (result.stdout or "") + (result.stderr or "")
    except Exception as exc:
        ts2 = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        try:
            with open(log_file, "a") as fh:
                fh.write(f"{ts2} FAIL plate crashed: {exc}\n")
        except OSError:
            pass
        out = f"plate crashed: {exc}"

    print(emit_block(out.rstrip("\n")))
    return 0
