import glob, json, hashlib, errno, fcntl, os, re, shutil, signal, subprocess, sys, tempfile, threading, time, io
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Optional, Sequence, Type, TypedDict

from common.scripts.claude_lib import claude_buildCmd, claude_seedPermissions
from common.scripts.hookjson_lib import hookjson_checkRequirements, hookjson_emitBlock
from common.scripts.git_lib import (
    git_getBranchNameOrFail,
    git_getRecentCommitHashes,
    git_getUncommittedFilenames,
    _git_repoRoot,
    _git_get_repo_root,
)
from common.scripts.util_lib import (
    _util_hide_errors,
    _util_resolvePluginRoot,
    FileLock,
    LockTimeout,
    terminal_spawnIfNeeded,
)
from common.scripts.tmux_lib import (
    tmux_ensureSession,
    tmux_killPane,
    tmux_splitWorkerPane,
    tmux_setPaneTitle,
    tmux_retile,
    tmux_waitForClaudeReadiness,
)


_POLL_ATTEMPTS = 5
_POLL_SLEEP = 0.2


# Module-level wrapper for jot_sendPrompt to break circular import with jot_lib
# (jot_lib imports todo_scanOpen from this module). Tests patch this attribute.
def jot_sendPrompt(tmux_target: str, input_file: str) -> int:
    from common.scripts.jot_lib import jot_sendPrompt as _impl
    return _impl(tmux_target, input_file)
# Max retries polling the tmux_target sidecar file.
_SIDECAR_RETRIES = 5
_SIDECAR_SLEEP = 0.2
_AUDIT_MAX_LINES = 1000


# Hook entrypoint for /todo-list: reads the Claude Code UserPromptSubmit JSON
# from stdin, validates the prompt, locates the repo's Todos/ folder, runs the
# format_open_todos.py helper, and emits a block-decision JSON wrapping the
# formatted output (or a friendly fallback message). Always returns 0.
def todo_listMain() -> int:
    plugin_root = _util_resolvePluginRoot()
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

    repo_root = _git_repoRoot(cwd)
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

# Prefixes that are considered safe to remove.
_VALID_PREFIXES: tuple[str, ...] = ("/tmp/todo.", "/private/tmp/todo.")

def todo_sessionEnd(tmpdir_inv: str) -> None:
    """Remove a todo session tmpdir after validating its prefix.

    Args:
        tmpdir_inv: Absolute path to the temporary directory to remove.

    Behaviour:
        - If *tmpdir_inv* starts with a recognised prefix, delegate removal
          to ``shutil.rmtree`` with ``ignore_errors=True`` and return.
        - If the prefix is not recognised, print a warning to stderr and
          return without touching the filesystem.
        - An empty string is treated as an unrecognised prefix.
    """
    if not any(tmpdir_inv.startswith(prefix) for prefix in _VALID_PREFIXES):
        print(
            f"[todo-session-end] refusing to rm unexpected path: {tmpdir_inv}",
            file=sys.stderr,
        )
        return

    shutil.rmtree(tmpdir_inv, ignore_errors=True)


def todo_launcher(session_id: str, idea: str, pending_file_path: str) -> int:
    if not session_id:
        print("todo_launcher: session_id required", file=sys.stderr)
        return 1
    if not idea:
        print("todo_launcher: refined idea required", file=sys.stderr)
        return 1
    if not pending_file_path:
        print("todo_launcher: pending_file path required", file=sys.stderr)
        return 1

    pending_file = Path(pending_file_path)
    if not pending_file.is_file():
        print(f"todo-launcher: pending file not found at {pending_file}", file=sys.stderr)
        return 1

    plugin_root = Path(__file__).resolve().parent.parent
    scripts_dir = plugin_root / "skills" / "todo" / "scripts"

    os.environ["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    claude_plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA", str(Path.home() / ".claude" / "plugins" / "data" / "jot-matkatmusic-jot"))
    os.environ["CLAUDE_PLUGIN_DATA"] = claude_plugin_data
    
    Path(claude_plugin_data).mkdir(parents=True, exist_ok=True)
    
    log_file = os.environ.get("TODO_LOG_FILE", str(Path(claude_plugin_data) / "todo-log.txt"))
    try:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
        
    try:
        with open(pending_file, "r") as f:
            pending_data = json.load(f)
    except Exception as e:
        print(f"todo-launcher: failed to read pending file: {e}", file=sys.stderr)
        return 1
        
    repo_root = pending_data.get("repo_root", "")
    cwd = pending_data.get("cwd", "")
    transcript_path = pending_data.get("transcript_path", "")
    timestamp = pending_data.get("timestamp", "")
    
    state_dir = Path(repo_root) / "Todos" / ".todo-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "audit.log").touch(exist_ok=True)
    
    # Phase 1
    target_dir = Path(repo_root) / "Todos"
    target_dir.mkdir(parents=True, exist_ok=True)
    input_file = target_dir / f"{timestamp}_input.txt"
    input_abs = str(input_file)
    
    branch = _util_hide_errors(git_getBranchNameOrFail, Path(cwd))
    commits_list = _util_hide_errors(git_getRecentCommitHashes, Path(cwd))
    commits = "\n".join(commits_list) if isinstance(commits_list, list) else commits_list
    uncommitted_list = _util_hide_errors(git_getUncommittedFilenames, Path(cwd))
    uncommitted = "\n".join(uncommitted_list) if isinstance(uncommitted_list, list) else uncommitted_list
    
    open_todos_list = _util_hide_errors(todo_scanOpen, repo_root)
    open_todos = "\n".join(open_todos_list) if isinstance(open_todos_list, list) else open_todos_list
    
    if transcript_path and Path(transcript_path).is_file():
        try:
            result = subprocess.run(
                ["python3", str(plugin_root / "skills" / "jot" / "scripts" / "capture-conversation.py"), transcript_path],
                capture_output=True, text=True, check=True
            )
            conversation = result.stdout.strip()
        except subprocess.CalledProcessError:
            conversation = "(unavailable)"
    else:
        conversation = "No conversation history available."
        
    try:
        env = os.environ.copy()
        env.update({
            "REPO_ROOT": repo_root,
            "TIMESTAMP": timestamp,
            "BRANCH": branch,
            "INPUT_ABS": input_abs
        })
        result = subprocess.run(
            ["python3", str(plugin_root / "common" / "scripts" / "jot" / "render_template.py"),
             str(scripts_dir / "assets" / "todo-instructions.md"),
             "REPO_ROOT", "TIMESTAMP", "BRANCH", "INPUT_ABS"],
            capture_output=True, text=True, check=True, env=env
        )
        instructions = result.stdout.strip()
    except Exception:
        instructions = "(unavailable)"
        
    input_content = f"""# Todo Task

## Instructions
{instructions}

## Idea
{idea}

## Working Directory
{cwd}

## Git State
- Branch: {branch}
- Commits: {commits}
- Uncommitted: {uncommitted}

## Open TODO Files
{open_todos}

## Transcript Path
{transcript_path or '(none)'}

## Recent Conversation
{conversation}
"""
    input_file.write_text(input_content)
    
    # Phase 2
    tmpdir_inv = Path(tempfile.mkdtemp(prefix="todo."))
    settings_file = tmpdir_inv / "settings.json"

    permissions_file = Path(claude_plugin_data) / "todo-permissions.local.json"
    default_file = scripts_dir / "assets" / "permissions.default.json"
    default_sha_file = scripts_dir / "assets" / "permissions.default.json.sha256"
    prior_sha_file = Path(claude_plugin_data) / "todo-permissions.default.sha256"
    
    claude_seedPermissions(
        str(permissions_file), str(default_file), str(default_sha_file), str(prior_sha_file), log_file, "todo"
    )
    
    try:
        env = os.environ.copy()
        env.update({"CWD": cwd, "HOME": str(Path.home()), "REPO_ROOT": repo_root})
        result = subprocess.run(
            ["python3", str(plugin_root / "common" / "scripts" / "jot" / "expand_permissions.py"), str(permissions_file)],
            capture_output=True, text=True, check=True, env=env
        )
        allow_json = result.stdout.strip()
    except Exception:
        allow_json = "{}"
        
    hooks_json_file = tmpdir_inv / "hooks.json"
    hooks_data = {
        "SessionStart": [{"hooks": [{"type": "command", "command": f"python3 {tmpdir_inv}/jot_plugin_orchestrator.py todo-session-start '{input_file}' '{tmpdir_inv}'"}]}],
        "Stop":         [{"hooks": [{"type": "command", "command": f"python3 {tmpdir_inv}/jot_plugin_orchestrator.py todo-stop '{input_file}' '{tmpdir_inv}' '{state_dir}'"}]}],
        "SessionEnd":   [{"hooks": [{"type": "command", "command": f"python3 {tmpdir_inv}/jot_plugin_orchestrator.py todo-session-end '{tmpdir_inv}'"}]}]
    }
    hooks_json_file.write_text(json.dumps(hooks_data))
    
    claude_cmd = claude_buildCmd(str(settings_file), allow_json, str(hooks_json_file), cwd, repo_root)
    
    # Phase 3
    tmux_lock_file = Path(claude_plugin_data) / "todo-tmux-launch.lock"
    try:
        with FileLock(str(tmux_lock_file), timeout=10):
            counter_file = Path(claude_plugin_data) / "todo-pane-counter.txt"
            try:
                n = int(counter_file.read_text().strip())
            except Exception:
                n = 0
            n = (n % 20) + 1
            counter_file.write_text(f"{n}\n")
            pane_label = f"todo{n}"
            
            keepalive_cmd = 'exec sh -c \'trap "" INT HUP TERM; printf "[todo keepalive — do not kill]\\n"; exec tail -f /dev/null\''
            tmux_ensureSession("todo", "todos", cwd, keepalive_cmd, 'todo: keepalive')
            
            pane_id = tmux_splitWorkerPane("todo:todos", cwd, claude_cmd)
            if not pane_id:
                print("todo-launcher: tmux split-window returned empty pane id", file=sys.stderr)
                return 1
                
            (tmpdir_inv / "tmux_target.tmp").write_text(f"{pane_id}\n")
            (tmpdir_inv / "tmux_target.tmp").rename(tmpdir_inv / "tmux_target")
            
            tmux_setPaneTitle(pane_id, pane_label)
            tmux_retile("todo:todos")
            
    except Exception as e:
        # Fallback to catching all exceptions if LockTimeout not exported correctly
        print("todo-launcher: failed to acquire tmux-launch lock", file=sys.stderr)
        return 1
        
    terminal_spawnIfNeeded("todo", log_file, "todo")
    return 0


def todo_stop(
    input_file: str,
    tmpdir_inv: str,
    state_dir: str,
) -> int:
    """Stop hook for the /todo skill's per-invocation claude pane.

    Fires when claude finishes responding to its one job.

    Ordering contract (mirrors jot_stop):
      1. Read tmux_target sidecar SYNCHRONOUSLY before anything else.
      2. Write audit entry.
      3. Rotate audit log.
      4. Kill pane + retile in a background thread (so this hook returns
         before tmux signals the claude process).

    Args:
        input_file:  Absolute path to the input.txt claude was told to process.
        tmpdir_inv:  Absolute path to the per-invocation tmpdir (/tmp/todo.XXXX).
        state_dir:   Path to todo state dir (for audit.log).

    Returns:
        0 always (matches bash exit 0 semantics; errors logged to stderr).
    """
    # --- arg guard -----------------------------------------------------------
    if not input_file or not tmpdir_inv or not state_dir:
        print("[todo-stop] missing args (input_file, tmpdir_inv, state_dir)", file=sys.stderr)
        return 0

    # --- read tmux_target sidecar SYNCHRONOUSLY (ordering contract) ----------
    target_file = Path(tmpdir_inv) / "tmux_target"
    tmux_target = ""
    for _ in range(_SIDECAR_RETRIES):
        if target_file.is_file() and target_file.stat().st_size > 0:
            first = target_file.read_text().splitlines()
            if first and first[0].strip():
                tmux_target = first[0].strip()
                break
        time.sleep(_SIDECAR_SLEEP)

    if not tmux_target:
        print("[todo-stop] tmux_target sidecar empty after retries", file=sys.stderr)
        return 0

    # --- ensure state dir and audit.log exist --------------------------------
    state_path = Path(state_dir)
    state_path.mkdir(parents=True, exist_ok=True)
    audit_path = state_path / "audit.log"
    audit_path.touch(exist_ok=True)

    # --- audit entry ---------------------------------------------------------
    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    inp = Path(input_file)
    if inp.is_file():
        content = inp.read_text()
        first_line = content.splitlines()[0] if content else ""
        if first_line.startswith("PROCESSED:"):
            with audit_path.open("a") as fh:
                fh.write(f"{ts} SUCCESS {input_file}\n")
            # SUCCESS: remove input file (matches bash rm -f)
            try:
                inp.unlink()
            except FileNotFoundError:
                pass
        else:
            with audit_path.open("a") as fh:
                fh.write(f"{ts} FAIL {input_file} (no PROCESSED marker)\n")
    else:
        with audit_path.open("a") as fh:
            fh.write(f"{ts} FAIL {input_file} (input.txt missing)\n")

    # --- rotate audit --------------------------------------------------------
    # Lazy import to avoid circular: jot_lib imports todo_scanOpen from todo_lib.
    from common.scripts.jot_lib import jot_rotateAudit
    jot_rotateAudit(audit_path, _AUDIT_MAX_LINES)

    # --- kill pane + retile in background (hook must return first) -----------
    _pane = tmux_target  # captured in closure before thread starts

    def _cleanup() -> None:
        time.sleep(0.5)
        try:
            tmux_killPane(_pane)
        except Exception:
            pass
        try:
            tmux_retile("todo:todos")
        except Exception:
            pass

    t = threading.Thread(target=_cleanup, daemon=True)
    t.start()

    return 0


def todo_sessionStart(input_file: str, tmpdir_inv: str) -> int:
    """SessionStart hook: poll sidecar, wait for Claude TUI, send prompt.

    Args:
        input_file: Absolute path to input.txt for this /todo invocation.
        tmpdir_inv: Absolute path to per-invocation tmpdir (/tmp/todo.XXXXXX).

    Returns:
        0 on success or soft failure; 1 if Claude TUI not ready.
    """
    # Validate required args (bash: exit 0 on missing).
    if not input_file or not tmpdir_inv:
        print(f"{_TAG} missing args (input_file, tmpdir_inv)", file=sys.stderr)
        return 0

    # Poll <tmpdir_inv>/tmux_target up to 5 times (bash: for _ in 1..5 with sleep 0.2).
    target_file = Path(tmpdir_inv) / "tmux_target"
    tmux_target = ""
    for _ in range(_POLL_ATTEMPTS):
        if target_file.is_file() and target_file.stat().st_size > 0:
            first_line = target_file.read_text().splitlines()[0].strip()
            if first_line:
                tmux_target = first_line
                break
        time.sleep(_POLL_SLEEP)

    if not tmux_target:
        print(f"{_TAG} tmux_target sidecar empty after retries", file=sys.stderr)
        return 0

    # Wait for Claude TUI ready glyph (bash: tmux_wait_for_claude_readiness).
    if tmux_waitForClaudeReadiness(tmux_target) != 0:
        print(f"{_TAG} claude TUI not ready, aborting send", file=sys.stderr)
        return 1

    # Send "Read <input.txt> and follow the instructions ..." prompt.
    return jot_sendPrompt(tmux_target, input_file)


# Mirrors `head -10 "$f" | grep -q '^status: open'`: a line within the first
# 10 lines whose start is the literal token "status: open". grep's anchor (^)
# pins the match to column 0; the trailing portion of the line is unconstrained.
def _todo_has_open_status(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= 10:
                    break
                if line.startswith("status: open"):
                    return True
    except OSError:
        return False
    return False


_TAG = "[todo-session-start]"


# Scan <target_dir>/Todos/*.md and return absolute paths whose first 10 lines
# contain a line beginning exactly with "status: open".
def todo_scanOpen(target_dir: str | Path = ".") -> list[str]:
    todos_dir = Path(target_dir) / "Todos"
    if not todos_dir.is_dir():
        return []

    open_paths: list[str] = []
    # sorted() mirrors bash glob's lexicographic order — callers depend on
    # stable ordering when this list is rendered into the jot input file.
    for md_path in sorted(todos_dir.glob("*.md")):
        if not md_path.is_file():
            continue
        if _todo_has_open_status(md_path):
            open_paths.append(str(md_path.resolve()))
    return open_paths


