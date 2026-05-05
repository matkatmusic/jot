"""Implementation of jot_collectDiagnostics.

Migrated from bash jot_diag_collect() in jot-plugin-orchestrator.sh lines 3925-4106.

Collects a post-mortem diagnostic report for a /jot run and writes it to a
file. Returns the output path on success.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts/_migration_workspace")

from jot_plugin_orchestrator import jot_diagSection, jot_diagIndent, jot_diagKv


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ls_latest_input_txt(todos_dir: Path) -> Path | None:
    """Return the most-recently-modified *_input.txt under todos_dir, or None."""
    candidates = sorted(todos_dir.glob("*_input.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _run_tmux(*args: str) -> str:
    """Run a tmux subcommand; return stdout or error message on failure."""
    try:
        result = subprocess.run(
            ["tmux", *args],
            capture_output=True,
            text=True,
        )
        return (result.stdout + result.stderr).rstrip("\n")
    except FileNotFoundError:
        return "(tmux not found)"


def _tmux_session_exists(session: str) -> bool:
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", session],
            capture_output=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _tail_lines(path: Path, n: int) -> str:
    """Return last n lines of path as a string, or empty string if unreadable."""
    try:
        text = path.read_text(errors="replace")
        lines = text.splitlines(keepends=True)
        return "".join(lines[-n:])
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

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
    latest = _ls_latest_input_txt(todos_dir) if todos_dir.is_dir() else None
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
            lines.append(jot_diagIndent(_tail_lines(audit_file, 30)))
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
        sessions = _run_tmux("list-sessions")
        jot_sessions = "\n".join(l for l in sessions.splitlines() if l.startswith("jot"))
        lines.append(jot_diagIndent(jot_sessions + "\n") if jot_sessions else "  (none)\n")
        lines.append("\n")

        lines.append("--- tmux list-windows -t jot ---\n")
        lines.append(jot_diagIndent(_run_tmux("list-windows", "-t", "jot") + "\n"))
        lines.append("\n")

        lines.append(f"--- tmux list-panes -t {tmux_target} ---\n")
        lines.append(jot_diagIndent(
            _run_tmux(
                "list-panes", "-t", tmux_target,
                "-F", "#{pane_id} pid=#{pane_pid} dead=#{pane_dead} deadstatus=#{pane_dead_status} cmd=#{pane_current_command}",
            ) + "\n"
        ))
        lines.append("\n")

        lines.append("--- pane start command ---\n")
        lines.append(jot_diagIndent(
            _run_tmux("display-message", "-t", tmux_target, "-p", "start: #{pane_start_command}") + "\n"
        ))
        lines.append("\n")

        lines.append("--- tmux attached clients ---\n")
        clients = _run_tmux("list-clients", "-t", "jot")
        if not clients.strip():
            lines.append("  (no clients attached)\n")
        else:
            lines.append(jot_diagIndent(clients + "\n"))
        lines.append("\n")

        lines.append("--- pane content (last 80 lines of scrollback) ---\n")
        pane_content = _run_tmux("capture-pane", "-p", "-t", tmux_target, "-S", "-80")
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
        lines.append(jot_diagIndent(_tail_lines(log_path, 20)))
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
        os.path.join(plugin_root, "scripts/jot-plugin-orchestrator.sh"),
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
