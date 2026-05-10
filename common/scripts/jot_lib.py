import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from common.scripts.claude_lib import (
    claude_buildCmd,
    claude_seedPermissions,
)
from common.scripts.git_lib import (
    git_getBranchNameOrFail,
    git_getRecentCommitHashes,
    git_getUncommittedFilenames,
)
from common.scripts.hookjson_lib import (
    hookjson_checkRequirements,
    hookjson_emitBlock,
)
from common.scripts import tmux_lib
from common.scripts.tmux_lib import (
    _tmux_backgroundKill,
    _tmux_run,
    _tmux_session_exists,
    tmux_ensureSession,
    tmux_requireVersion,
    tmux_retile,
    tmux_sendAndSubmit,
    tmux_setPaneTitle,
    tmux_splitWorkerPane,
    tmux_waitForClaudeReadiness,
)
from common.scripts.todo_lib import todo_scanOpen
from common.scripts.util_lib import (
    FileLock,
    LockTimeout,
    _util_append_log,
    _util_appendAudit,
    _util_isoTimestampLocal,
    _util_ls_latest_input_txt,
    _util_safe_call,
    _util_strip_stdin_text,
    _util_tail_lines,
    terminal_spawnIfNeeded,
)


# Initializes the jot state directory: creates it (idempotent) and ensures queue.txt, active_job.txt, audit.log exist; refreshes mtime on existing files (bash `touch` parity).
def jot_initState(state_dir: str | Path) -> None:
    state_path = Path(state_dir)
    state_path.mkdir(parents=True, exist_ok=True)
    for name in ("queue.txt", "active_job.txt", "audit.log"):
        (state_path / name).touch(exist_ok=True)


# Pops first line from <state_dir>/queue.txt: writes it to active_job.txt, drops it from queue.txt, returns the line (no trailing newline). Returns None on empty queue. Caller must hold the queue lock.
def jot_popFirstFromQueue(state_dir: str | Path) -> str | None:
    state = Path(state_dir)
    queue_path = state / "queue.txt"
    active_path = state / "active_job.txt"
    if not queue_path.exists() or queue_path.stat().st_size == 0:
        return None
    content = queue_path.read_text()
    lines = content.split("\n")
    first = lines[0]
    rest = lines[1:]
    active_path.write_text(first + "\n")
    queue_path.write_text("\n".join(rest))
    return first


# Sends a "Read <input_file> and follow the instructions at the top of that file" prompt to the Claude pane via tmux_sendAndSubmit; returns its rc.
def jot_sendPrompt(pane_target: str, input_file_path: str) -> int:
    prompt = f"Read {input_file_path} and follow the instructions at the top of that file"
    return tmux_lib.tmux_sendAndSubmit(pane_target, prompt)


# Trims audit_log to its last max_lines lines (default 1000) when oversized; missing-file is a silent no-op; in-place via atomic temp+rename so no .trim sidecar survives.
def jot_rotateAudit(audit_log: str | Path, max_lines: int = 1000) -> None:
    path = Path(audit_log)
    if not path.is_file():
        return None
    line_count = 0
    with path.open("rb") as fh:
        for _ in fh:
            line_count += 1
    if line_count <= max_lines:
        return None
    tail: deque[bytes] = deque(maxlen=max_lines)
    with path.open("rb") as fh:
        for raw in fh:
            tail.append(raw)
    fd, tmp_name = tempfile.mkstemp(prefix=".audit.", suffix=".trim", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as out:
            for raw in tail:
                out.write(raw)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    return None


# Builds the Claude launch command for a /jot invocation by staging lifecycle hooks, seeding permissions, expanding allow rules, and returning explicit launch paths.
def jot_buildClaudeCmd(
    *,
    claude_plugin_root: str,
    claude_plugin_data: str,
    cwd: str,
    repo_root: str,
    home: str,
    input_file: str,
    state_dir: str,
    log_file: str,
    permissions_seed: Callable[..., object] | None = None,
    expand_permissions: Callable[[str, dict[str, str]], str] | None = None,
    tmpdir_factory: Callable[[], str] | None = None,
) -> dict[str, str]:
    tmpdir_inv = (tmpdir_factory or (lambda: tempfile.mkdtemp(prefix="jot.", dir="/tmp")))()
    settings_file = f"{tmpdir_inv}/settings.json"
    permissions_file = f"{claude_plugin_data}/permissions.local.json"

    orchestrator_path = f"{claude_plugin_root}/scripts/jot_plugin_orchestrator.py"

    default_file = f"{claude_plugin_root}/skills/jot/scripts/assets/permissions.default.json"
    default_sha_file = f"{default_file}.sha256"
    prior_sha_file = f"{claude_plugin_data}/permissions.default.sha256"
    Path(claude_plugin_data).mkdir(parents=True, exist_ok=True)

    seed_fn = permissions_seed or _jot_defaultPermissionsSeed
    seed_fn(
        permissions_file,
        default_file,
        default_sha_file,
        prior_sha_file,
        log_file,
        "jot",
    )

    expand_fn = expand_permissions or _jot_defaultExpandPermissions
    env = {"CWD": cwd, "HOME": home, "REPO_ROOT": repo_root}
    allow_json = expand_fn(permissions_file, env)

    hooks_json_file = f"{tmpdir_inv}/hooks.json"
    hooks_body = (
        "{\n"
        '  "SessionStart": [{"hooks": [{"type": "command", "command": "python3 '
        f"{orchestrator_path} jot-session-start '{input_file}' '{tmpdir_inv}'"
        '"}]}],\n'
        '  "Stop":         [{"hooks": [{"type": "command", "command": "python3 '
        f"{orchestrator_path} jot-stop '{input_file}' '{tmpdir_inv}' '{state_dir}'"
        '"}]}],\n'
        '  "SessionEnd":   [{"hooks": [{"type": "command", "command": "python3 '
        f"{orchestrator_path} jot-session-end '{tmpdir_inv}'"
        '"}]}]\n'
        "}\n"
    )
    Path(hooks_json_file).write_text(hooks_body)

    claude_cmd = claude_buildCmd(
        settings_file,
        allow_json,
        hooks_json_file,
        cwd,
        repo_root,
    )

    return {
        "TMPDIR_INV": tmpdir_inv,
        "SETTINGS_FILE": settings_file,
        "PERMISSIONS_FILE": permissions_file,
        "HOOKS_JSON_FILE": hooks_json_file,
        "CLAUDE_CMD": claude_cmd,
    }


def _jot_defaultPermissionsSeed(
    permissions_file: str,
    default_file: str,
    default_sha_file: str,
    prior_sha_file: str,
    log_file: str,
    label: str,
) -> int:
    claude_seedPermissions(
        permissions_file,
        default_file,
        default_sha_file,
        prior_sha_file,
        log_file,
        label,
    )
    return 0


def _jot_defaultExpandPermissions(permissions_file: str, env: dict[str, str]) -> str:
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    script_path = f"{plugin_root}/common/scripts/jot/expand_permissions.py"
    merged = {**os.environ, **env}
    result = subprocess.run(
        ["python3", script_path, permissions_file],
        capture_output=True,
        text=True,
        env=merged,
        check=False,
    )
    return result.stdout


def _jot_appendLog(log_file: str, message: str) -> None:
    if not log_file:
        return
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(message)
    except OSError:
        return


# Spawns a tmux pane running Claude for one /jot invocation, publishing the pane id for lifecycle hooks and surfacing the session after launch.
def jot_launchPhase2Window() -> int:
    repo_root = os.environ["REPO_ROOT"]
    plugin_data = os.environ["CLAUDE_PLUGIN_DATA"]
    cwd = os.environ.get("CWD", repo_root)
    log_file = os.environ.get("LOG_FILE", "")

    state_dir = str(Path(repo_root) / "Todos" / ".jot-state")
    os.environ["STATE_DIR"] = state_dir
    jot_initState(state_dir)

    Path(plugin_data).mkdir(parents=True, exist_ok=True)
    tmux_lock = str(Path(plugin_data) / "tmux-launch.lock")

    try:
        with FileLock(tmux_lock, timeout=10):
            counter_file = Path(plugin_data) / "pane-counter.txt"
            try:
                n = int((counter_file.read_text() or "0").strip() or "0")
            except (OSError, ValueError):
                n = 0
            n = (n % 20) + 1
            counter_file.write_text(f"{n}\n")
            pane_label = f"jot{n}"

            built = jot_buildClaudeCmd(
                claude_plugin_root=os.environ.get("CLAUDE_PLUGIN_ROOT", ""),
                claude_plugin_data=plugin_data,
                cwd=cwd,
                repo_root=repo_root,
                home=os.environ.get("HOME", ""),
                input_file=os.environ.get("INPUT_FILE", ""),
                state_dir=state_dir,
                log_file=log_file,
            )
            tmpdir_inv = built["TMPDIR_INV"]
            claude_cmd = built["CLAUDE_CMD"]

            keepalive_cmd = (
                "exec sh -c 'trap \"\" INT HUP TERM; "
                "printf \"[jot keepalive - do not kill]\\n\"; "
                "exec tail -f /dev/null'"
            )
            tmux_ensureSession("jot", "jots", cwd, keepalive_cmd, "jot: keepalive")

            pane_id = tmux_splitWorkerPane("jot:jots", cwd, claude_cmd)
            if not pane_id:
                _jot_appendLog(log_file, "[jot] tmux split-window returned empty pane id\n")
                return 1

            target_path = Path(tmpdir_inv) / "tmux_target"
            tmp_path = Path(tmpdir_inv) / "tmux_target.tmp"
            tmp_path.write_text(f"{pane_id}\n")
            os.replace(tmp_path, target_path)

            tmux_setPaneTitle(pane_id, pane_label)
            tmux_retile("jot:jots")
    except LockTimeout:
        _jot_appendLog(log_file, f"[jot] failed to acquire global tmux-launch lock at {tmux_lock}\n")
        return 1

    terminal_spawnIfNeeded("jot", log_file, "jot")
    return 0


_DIAG_SECTION_RULE = "═" * 59


# Polls the tmux_target sidecar file up to 5 times at 0.2s intervals; returns first non-empty first line, or "" if it stays empty.
def _jot_readSidecar(target_file: Path) -> str:
    for _ in range(5):
        try:
            if target_file.is_file() and target_file.stat().st_size > 0:
                first_line = target_file.read_text().split("\n", 1)[0]
                if first_line:
                    return first_line
        except OSError:
            pass
        time.sleep(0.2)
    return ""


# Format a section banner: leading newline, 59-char box-drawing rule, title, trailing rule, trailing newline. Mirrors bash printf for byte-identical jot-diag report layout.
def jot_diagSection(title: str) -> str:
    return f"\n{_DIAG_SECTION_RULE}\n{title}\n{_DIAG_SECTION_RULE}\n"


# Prepend two spaces to every line in `text`. Trailing newline preserved as-is, matching `sed 's/^/  /'` semantics; bash's stdin-filter form is converted to argument-taking since callers always have the captured text in hand.
def jot_diagIndent(text: str) -> str:
    if not text:
        return text
    had_trailing_nl = text.endswith("\n")
    body = text[:-1] if had_trailing_nl else text
    indented = "\n".join("  " + line for line in body.split("\n"))
    return indented + ("\n" if had_trailing_nl else "")


# Format a key/value diagnostic line: key left-padded to width 28, single-space separator, value, trailing newline. Keys >=28 chars are not truncated (printf '%-28s' minimum-width semantics).
def jot_diagKv(key: str, value: object) -> str:
    return f"{key:<28} {value}\n"

def jot_collectDiagnostics(out_path: str | None = None) -> str:
    """Collect a /jot post-mortem diagnostic report and write it to out_path.

    Gathers:
      1. Latest Todos/*_input.txt metadata and content
      2. State dir (queue, active_job, audit log, lock)
      3. tmux session 'jot' info
      4. /tmp/jot.* per-invocation dirs
      5. jot log file (last 20 entries)
      6. Todos/ directory listing (newest first)
      7. Installed plugin orchestrator paths
      8. Dependency check (jq, python3, tmux, claude, osascript)

    Args:
        out_path: Destination file path. Defaults to
            /tmp/jot-diag-<YYYYMMDD-HHMMSS>.log.

    Returns:
        Absolute path to the written report file.
    """
    if out_path is None:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = f"/tmp/jot-diag-{timestamp}.log"

    cwd = Path(os.getcwd())

    # Determine repo root via git; fall back to cwd.
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
        repo_root = Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else cwd
    except FileNotFoundError:
        repo_root = cwd

    project = repo_root.name
    tmux_target = "jot:jots"
    state_dir = repo_root / "Todos" / ".jot-state"

    lines: list[str] = []

    # --- header ---
    lines.append("jot-diag-collect report\n")
    lines.append(f"generated: {datetime.now().astimezone().isoformat()}\n")
    lines.append(f"cwd:       {cwd}\n")
    lines.append(f"project:   {project}\n")
    lines.append(f"tmux target (expected): {tmux_target}\n")

    # --- section 1 ---
    lines.append(jot_diagSection("1. Latest Todos/*_input.txt"))
    todos_dir = repo_root / "Todos"
    latest = _util_ls_latest_input_txt(todos_dir) if todos_dir.is_dir() else None
    if latest is None:
        lines.append(f"(no input.txt found in {todos_dir})\n")
    else:
        lines.append(jot_diagKv("path", str(latest)))
        try:
            size = latest.stat().st_size
        except OSError:
            size = "?"
        lines.append(jot_diagKv("size (bytes)", str(size)))
        try:
            import time as _time
            mtime = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(latest.stat().st_mtime))
        except OSError:
            mtime = "?"
        lines.append(jot_diagKv("mtime", mtime))
        try:
            content_text = latest.read_text(errors="replace")
            first_line = content_text.splitlines()[0] if content_text.strip() else ""
        except OSError:
            content_text = ""
            first_line = ""
        lines.append(jot_diagKv("first line", first_line))
        if first_line.startswith("PROCESSED:"):
            lines.append(jot_diagKv("status", "PROCESSED (success)"))
        elif first_line == "# Jot Task":
            lines.append(jot_diagKv("status", "PENDING (claude hasn't finished OR failed)"))
        else:
            lines.append(jot_diagKv("status", "? unknown first-line format"))
        lines.append("\n")
        lines.append("--- full content ---\n")
        lines.append(content_text)

    # --- section 2 ---
    lines.append(jot_diagSection(f"2. State dir ({state_dir})"))
    if not state_dir.is_dir():
        lines.append("(state dir does not exist — Phase 2 may not have run)\n")
    else:
        lines.append("--- ls -la ---\n")
        try:
            ls_out = subprocess.run(
                ["ls", "-la", str(state_dir)], capture_output=True, text=True
            ).stdout
        except FileNotFoundError:
            ls_out = "(ls not available)\n"
        lines.append(jot_diagIndent(ls_out))
        lines.append("\n")

        lines.append("--- queue.txt ---\n")
        queue_file = state_dir / "queue.txt"
        if queue_file.exists():
            if queue_file.stat().st_size > 0:
                lines.append(jot_diagIndent(queue_file.read_text(errors="replace")))
            else:
                lines.append("  (empty — no jobs pending)\n")
        else:
            lines.append("  (missing)\n")
        lines.append("\n")

        lines.append("--- active_job.txt ---\n")
        active_file = state_dir / "active_job.txt"
        if active_file.exists():
            if active_file.stat().st_size > 0:
                lines.append(jot_diagIndent(active_file.read_text(errors="replace")))
                lines.append("  (claude is currently processing this file)\n")
            else:
                lines.append("  (empty — claude is idle)\n")
        else:
            lines.append("  (missing)\n")
        lines.append("\n")

        lines.append("--- audit.log (last 30 entries) ---\n")
        audit_file = state_dir / "audit.log"
        if audit_file.exists():
            lines.append(jot_diagIndent(_util_tail_lines(audit_file, 30)))
        else:
            lines.append("  (missing)\n")
        lines.append("\n")

        lines.append("--- queue.lock ---\n")
        lock_path = state_dir / "queue.lock"
        if lock_path.exists() or lock_path.is_symlink():
            lock_type = "dir (mkdir lock)" if lock_path.is_dir() else "file"
            lines.append(f"  LOCK IS HELD (type: {lock_type})\n")
            lines.append("  If no /jot is currently running, this is a stale lock and should be removed:\n")
            lines.append(f"    rm -rf '{lock_path}'\n")
        else:
            lines.append("  (free — no lock held)\n")

    # --- section 3 ---
    lines.append(jot_diagSection("3. tmux session 'jot'"))
    if not _tmux_session_exists("jot"):
        lines.append("(no 'jot' tmux session exists)\n")
    else:
        lines.append("--- tmux list-sessions | grep jot ---\n")
        sessions = _tmux_run("list-sessions")
        jot_sessions = "\n".join(l for l in sessions.splitlines() if l.startswith("jot"))
        lines.append(jot_diagIndent(jot_sessions + "\n") if jot_sessions else "  (none)\n")
        lines.append("\n")

        lines.append("--- tmux list-windows -t jot ---\n")
        lines.append(jot_diagIndent(_tmux_run("list-windows", "-t", "jot") + "\n"))
        lines.append("\n")

        lines.append(f"--- tmux list-panes -t {tmux_target} ---\n")
        lines.append(jot_diagIndent(
            _tmux_run(
                "list-panes", "-t", tmux_target,
                "-F", "#{pane_id} pid=#{pane_pid} dead=#{pane_dead} deadstatus=#{pane_dead_status} cmd=#{pane_current_command}",
            ) + "\n"
        ))
        lines.append("\n")

        lines.append("--- pane start command ---\n")
        lines.append(jot_diagIndent(
            _tmux_run("display-message", "-t", tmux_target, "-p", "start: #{pane_start_command}") + "\n"
        ))
        lines.append("\n")

        lines.append("--- tmux attached clients ---\n")
        clients = _tmux_run("list-clients", "-t", "jot")
        if not clients.strip():
            lines.append("  (no clients attached)\n")
        else:
            lines.append(jot_diagIndent(clients + "\n"))
        lines.append("\n")

        lines.append("--- pane content (last 80 lines of scrollback) ---\n")
        pane_content = _tmux_run("capture-pane", "-p", "-t", tmux_target, "-S", "-80")
        lines.append(jot_diagIndent(pane_content + "\n") if pane_content.strip() else "  (empty)\n")

    # --- section 4 ---
    lines.append(jot_diagSection("4. /tmp/jot.* per-invocation dirs"))
    found_tmp = False
    for d in sorted(Path("/tmp").glob("jot.*")):
        if not d.is_dir():
            continue
        found_tmp = True
        lines.append(f"--- {d} ---\n")
        try:
            ls_out = subprocess.run(["ls", "-la", str(d)], capture_output=True, text=True).stdout
        except FileNotFoundError:
            ls_out = "(ls not available)\n"
        lines.append(jot_diagIndent(ls_out))
        settings = d / "settings.json"
        if settings.exists():
            lines.append("  --- settings.json ---\n")
            lines.append(jot_diagIndent(settings.read_text(errors="replace")))
    if not found_tmp:
        lines.append("(none — either not started or SessionEnd cleaned up)\n")

    # --- section 5 ---
    log_file_path = os.environ.get(
        "JOT_LOG_FILE",
        os.path.join(
            os.environ.get("CLAUDE_PLUGIN_DATA", os.path.join(os.environ.get("HOME", ""), ".claude/plugins/data/jot")),
            "jot-log.txt",
        ),
    )
    lines.append(jot_diagSection(f"5. {log_file_path} (last 20 entries)"))
    log_path = Path(log_file_path)
    if log_path.exists():
        lines.append(jot_diagIndent(_util_tail_lines(log_path, 20)))
    else:
        lines.append("(missing)\n")

    # --- section 6 ---
    lines.append(jot_diagSection("6. Todos/ directory listing (newest first)"))
    if todos_dir.is_dir():
        try:
            ls_out = subprocess.run(
                ["ls", "-lat", str(todos_dir)], capture_output=True, text=True
            ).stdout
            head_20 = "\n".join(ls_out.splitlines()[:20]) + "\n"
        except FileNotFoundError:
            head_20 = "(ls not available)\n"
        lines.append(jot_diagIndent(head_20))
    else:
        lines.append(f"(no Todos/ dir in {repo_root})\n")

    # --- section 7 ---
    lines.append(jot_diagSection("7. Installed plugin orchestrator path"))
    plugin_root = os.environ.get(
        "CLAUDE_PLUGIN_ROOT",
        os.path.join(os.environ.get("HOME", ""), ".claude/plugins/installed/jot"),
    )
    for p_str in [
        os.path.join(plugin_root, "scripts/jot_plugin_orchestrator.py"),
        os.path.join(plugin_root, "scripts"),
        os.path.join(plugin_root, "hooks/hooks.json"),
    ]:
        p = Path(p_str)
        if p.is_symlink():
            lines.append(jot_diagKv(p_str, f"-> {os.readlink(p_str)}"))
        elif p.exists():
            try:
                size = p.stat().st_size
            except OSError:
                size = "?"
            lines.append(jot_diagKv(p_str, f"present ({size} bytes)"))
        else:
            lines.append(jot_diagKv(p_str, "MISSING"))

    # --- section 8 ---
    lines.append(jot_diagSection("8. Dependency check"))
    for cmd in ("jq", "python3", "tmux", "claude", "osascript"):
        which = shutil.which(cmd)
        lines.append(jot_diagKv(cmd, which if which else "NOT FOUND"))

    lines.append(jot_diagSection("END OF REPORT"))

    report = "".join(lines)
    Path(out_path).write_text(report, encoding="utf-8")
    return out_path

def jot_sessionEnd(tmpdir_inv: str | None) -> int:
    """SessionEnd hook: wipe the per-invocation tmpdir at end of a jot claude session.

    Mirrors bash `jot_session_end` (jot-plugin-orchestrator.sh ~3399-3415).

    Safety guard: refuses to remove any path not matching the expected
    `/tmp/jot.*` or `/private/tmp/jot.*` patterns. Without this guard a
    misconfigured hook could wipe an arbitrary directory.

    Args:
        tmpdir_inv: absolute path to per-invocation tmpdir (e.g. /tmp/jot.abcXYZ).

    Returns:
        Exit code (always 0 — bash version `exit 0`s on both refusal and success).

    Side effects:
        Recursively deletes `tmpdir_inv` when it matches the safelist pattern.
        Writes a refusal message to stderr when the path does not match.
    """
    import re
    import shutil

    # Refuse missing/empty arg (bash treats unset $1 as empty string, falls through case).
    if not tmpdir_inv:
        print(
            f"[jot-session-end] refusing to rm unexpected path: {tmpdir_inv or ''}",
            file=sys.stderr,
        )
        return 0

    # Safety pattern: only /tmp/jot.* or /private/tmp/jot.* allowed.
    # Bash glob `/tmp/jot.*` matches paths starting with that literal prefix.
    if not re.match(r"^(/tmp/jot\.|/private/tmp/jot\.)", tmpdir_inv):
        print(
            f"[jot-session-end] refusing to rm unexpected path: {tmpdir_inv}",
            file=sys.stderr,
        )
        return 0

    # rm -rf semantics: ignore missing path, recursive, no error on nonexistent.
    shutil.rmtree(tmpdir_inv, ignore_errors=True)
    return 0


# SessionStart hook entry: reads the tmux pane id sidecar (TMPDIR_INV/tmux_target)
# written by phase2_launch_window, waits for the Claude TUI to be ready, then
# submits a one-shot "Read <INPUT_FILE> and follow the instructions" prompt.
# Returns a process exit code (0 = success/no-op, 1 = readiness timeout).
# Side effects: stderr diagnostics; tmux send-keys to the resolved pane.
# Polling: up to 5 attempts at 0.2s intervals for the sidecar (~1s ceiling).
def jot_sessionStart(input_file: str | None, tmpdir_inv: str | None) -> int:
    # Missing args: bash prints diagnostic and exits 0 (silent no-op).
    if not input_file or not tmpdir_inv:
        print("[jot-session-start] missing args (input_file, tmpdir_inv)", file=sys.stderr)
        return 0

    target_file = Path(tmpdir_inv) / "tmux_target"
    tmux_target = ""
    # Belt-and-suspenders: 5 retries at 0.2s for the pane id sidecar.
    for _ in range(5):
        try:
            if target_file.is_file() and target_file.stat().st_size > 0:
                first_line = target_file.read_text().split("\n", 1)[0]
                if first_line:
                    tmux_target = first_line
                    break
        except OSError:
            pass
        time.sleep(0.2)

    if not tmux_target:
        print("[jot-session-start] tmux_target sidecar empty after retries", file=sys.stderr)
        return 0

    # Wait for the Claude TUI ready glyph before sending keys.
    if tmux_waitForClaudeReadiness(tmux_target) != 0:
        print("[jot-session-start] claude TUI not ready, aborting send", file=sys.stderr)
        return 1

    tmux_sendAndSubmit(
        tmux_target,
        f"Read {input_file} and follow the instructions at the top of that file",
    )
    return 0

def jot_stop(
    input_file: str,
    tmpdir_inv: str,
    state_dir: str,
    *,
    background_kill: Callable[[str, str], None] | None = None,
) -> int:
    """Stop hook for a per-invocation claude pane.

    Reads the tmux pane id sidecar, appends one SUCCESS/FAIL audit line,
    rotates the log, then kills the pane and retiles the jots window.

    Returns 0 on every documented exit (matches bash `exit 0` parity).
    """
    # Argument guard — bash echoes to stderr and exits 0. We do the same.
    if not input_file or not tmpdir_inv or not state_dir:
        print(
            "[jot-stop] missing args (input_file, tmpdir_inv, state_dir)",
            file=sys.stderr,
        )
        return 0

    tmpdir_path = Path(tmpdir_inv)
    target_file = tmpdir_path / "tmux_target"
    tmux_target = _jot_readSidecar(target_file)
    if not tmux_target:
        print(
            "[jot-stop] tmux_target sidecar empty after retries",
            file=sys.stderr,
        )
        return 0

    # State dir must exist + standard files must be present.
    jot_initState(state_dir)
    audit_path = Path(state_dir) / "audit.log"

    ts = _util_isoTimestampLocal()
    input_path = Path(input_file)
    if input_path.is_file():
        try:
            with input_path.open("r", encoding="utf-8") as fh:
                first_line = fh.readline().rstrip("\n")
        except OSError:
            first_line = ""
        if first_line.startswith("PROCESSED:"):
            _util_appendAudit(audit_path, f"{ts} SUCCESS {input_file}")
        else:
            _util_appendAudit(
                audit_path, f"{ts} FAIL {input_file} (no PROCESSED marker)"
            )
    else:
        _util_appendAudit(audit_path, f"{ts} FAIL {input_file} (input.txt missing)")

    jot_rotateAudit(audit_path, 1000)

    bg = background_kill if background_kill is not None else _tmux_backgroundKill
    bg(tmux_target, "jot:jots")
    return 0

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

    _util_append_log(log_file, f"{datetime.now().isoformat()} HOOK_INPUT {hook_input}\n")

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
    prompt = _util_strip_stdin_text(str(payload.get("prompt", "")))

    # Strict prefix match.
    if prompt != "/jot" and not prompt.startswith("/jot "):
        return 0

    # Extract idea (prompt minus prefix), strip-stdin again.
    idea = prompt[len("/jot"):]
    if idea.startswith(" "):
        idea = idea[1:]
    idea = _util_strip_stdin_text(idea)

    if not idea:
        print(hookjson_emitBlock("jot: no idea provided"))
        return 0

    session_id = str(payload.get("session_id", "?")) or "?"
    _util_append_log(
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
    branch = _util_safe_call(git_getBranchNameOrFail, cwd)
    commits = _util_safe_call(git_getRecentCommitHashes, cwd)
    uncommitted = _util_safe_call(git_getUncommittedFilenames, cwd)
    open_todos = _util_safe_call(todo_scanOpen, repo_root)

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

