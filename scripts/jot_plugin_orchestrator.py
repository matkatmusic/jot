#!/usr/bin/env python3
"""Jot plugin orchestrator (Python).

Canonical Python monolith for the jot plugin. Replaces
`scripts/jot-plugin-orchestrator.sh` function-by-function.
"""
from __future__ import annotations

import glob
import json
import hashlib
import errno
import fcntl
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Optional, Sequence, Type, TypedDict
import io


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


# Sets a tmux option scoped to a specific target (session, window, or pane) via the -t flag.
def tmux_setOptionForTarget(target: str, name: str, value: str) -> int:
    return tmux_setOption("-t", target, name, value)


# Sets a tmux option in the global scope via the -g flag.
def tmux_setOptionGlobally(name: str, value: str) -> int:
    return tmux_setOption("-g", name, value)


# Sets a window-scoped tmux option on the given window target via the -w -t flags.
def tmux_setOptionForWindow(window_target: str, name: str, value: str) -> int:
    return tmux_setOption("-w", "-t", window_target, name, value)


# Probes whether a tmux session with the given name exists; rc=0 (exists) or 1 (absent) are both valid answers and never log; only unexpected rc values log to stderr.
def tmux_hasSession(session_name: str) -> int:
    cmd = ["tmux", "has-session", "-t", session_name]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode not in (0, 1):
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
    return result.returncode


# Creates a detached tmux session named <session_name>; extra args pass through after `-d -s <name>`.
def tmux_newSession(session_name: str, *extra_args: str) -> int:
    cmd = ["tmux", "new-session", "-d", "-s", session_name, *extra_args]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
    return result.returncode


# Kills the tmux session named `session_name` via `tmux kill-session -t <name>`.
def tmux_killSession(session_name: str) -> int:
    cmd = ["tmux", "kill-session", "-t", session_name]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
    return result.returncode


# Lists tmux clients attached to a session; returns list[str] (one per client) for idiomatic data flow, [] on failure with caller-attributed stderr log.
def tmux_listClients(session_name: str) -> list[str]:
    cmd = ["tmux", "list-clients", "-t", session_name]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
        return []
    return [line for line in (result.stdout or "").split("\n") if line]


# Splits <target> via `tmux split-window -t <target>`; extra args pass through (e.g. -P -F '#{pane_id}', -c cwd, shell-cmd). Prints stdout on success so callers can capture new pane id; logs caller-attributed stderr on failure.
def tmux_newPane(target: str, *extra_args: str) -> int:
    cmd = ["tmux", "split-window", "-t", target, *extra_args]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
    elif result.stdout:
        print(result.stdout, end="")
    return result.returncode


# Kills the tmux pane identified by `pane_target` via `tmux kill-pane -t <target>`.
def tmux_killPane(pane_target: str) -> int:
    cmd = ["tmux", "kill-pane", "-t", pane_target]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
    return result.returncode


# Captures the visible contents of a tmux pane and returns them as text; with scrollback_lines, includes that many lines of history before the visible area via `-S -<lines>`. Returns "" on failure.
def tmux_capturePane(pane_target: str, scrollback_lines: int | None = None) -> str:
    cmd = ["tmux", "capture-pane", "-p", "-t", pane_target]
    if scrollback_lines is not None:
        cmd += ["-S", f"-{scrollback_lines}"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
        return ""
    return result.stdout or ""


# Lists panes for a tmux target; with no extras returns "<pane_id> <pane_title>" per pane (default -F preserved); with extras passes them through verbatim and omits the default -F.
def tmux_listPanes(target: str, *extra_args: str) -> list[str]:
    if not extra_args:
        cmd = ["tmux", "list-panes", "-t", target, "-F", "#{pane_id} #{pane_title}"]
    else:
        cmd = ["tmux", "list-panes", "-t", target, *extra_args]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
        return []
    return [line for line in (result.stdout or "").split("\n") if line]


# Selects a tmux pane via `tmux select-pane -t <target>`; returns the exit code, logging failure with caller name.
def tmux_selectPane(pane_target: str) -> int:
    cmd = ["tmux", "select-pane", "-t", pane_target]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
    elif result.stdout:
        print(result.stdout, end="")
    return result.returncode


# Sets a pane's title via `tmux select-pane -t <target> -T <title>` (bash convention: select-pane carries the -T flag).
def tmux_setPaneTitle(pane_target: str, title: str) -> int:
    cmd = ["tmux", "select-pane", "-t", pane_target, "-T", title]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
    return result.returncode


# Creates a new tmux window in <session_name> named <window_name>; extra args pass through after `-t <s> -n <w>`.
def tmux_newWindow(session_name: str, window_name: str, *extra_args: str) -> int:
    cmd = ["tmux", "new-window", "-t", session_name, "-n", window_name, *extra_args]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
    elif result.stdout:
        print(result.stdout, end="")
    return result.returncode


# Kills the tmux window identified by `window_target` via `tmux kill-window -t <target>`.
def tmux_killWindow(window_target: str) -> int:
    cmd = ["tmux", "kill-window", "-t", window_target]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
    return result.returncode


# Lists windows for a tmux session; with no extras returns "<window_index> <window_name>" per window (default -F preserved); with extras passes them through verbatim and omits the default.
def tmux_listWindows(session_name: str, *extra_args: str) -> list[str]:
    if not extra_args:
        cmd = ["tmux", "list-windows", "-t", session_name, "-F", "#{window_index} #{window_name}"]
    else:
        cmd = ["tmux", "list-windows", "-t", session_name, *extra_args]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
        return []
    return [line for line in (result.stdout or "").split("\n") if line]


# Probes whether session has a window with EXACT given name; returns 0 if exists, 1 if not (bash exit-code semantics).
def tmux_windowExists(session_name: str, window_name: str) -> int:
    windows = tmux_listWindows(session_name, "-F", "#{window_name}")
    return 0 if window_name in windows else 1


# Probes whether ANY pane in target has the EXACT given title; returns 0 if exists, 1 if not. Uses tmux_listPanes + exact-match (replaces grep -qx).
def tmux_paneHasTitle(target: str, title: str) -> int:
    titles = tmux_listPanes(target, "-F", "#{pane_title}")
    return 0 if title in titles else 1


# Splits target horizontally (-h) or vertically (-v); raises ValueError for any other direction (Pythonic upgrade vs bash silent passthrough).
def tmux_splitWindow(target: str, direction: str) -> int:
    if direction not in ("h", "v"):
        raise ValueError(f"direction must be 'h' or 'v', got {direction!r}")
    cmd = ["tmux", "split-window", f"-{direction}", "-t", target]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
    return result.returncode


# Calls `tmux select-layout -t <target> <layout>`; returns the exit code, logging failure with caller name.
def tmux_selectLayout(target: str, layout: str) -> int:
    cmd = ["tmux", "select-layout", "-t", target, layout]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
    elif result.stdout:
        print(result.stdout, end="")
    return result.returncode


# Re-applies the `tiled` layout to the target tmux window via tmux_selectLayout.
def tmux_retile(target: str) -> int:
    return tmux_selectLayout(target, "tiled")


# Sends <text> as keystrokes to a tmux pane via `tmux send-keys -t <target> <text>`; does NOT append Enter.
def tmux_sendKeys(pane_target: str, text: str) -> int:
    cmd = ["tmux", "send-keys", "-t", pane_target, text]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
    return result.returncode


# Sends the literal `Enter` keystroke token to a tmux pane via `tmux send-keys -t <target> Enter`.
def tmux_sendEnter(pane_target: str) -> int:
    cmd = ["tmux", "send-keys", "-t", pane_target, "Enter"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
    return result.returncode


# Sends the literal `C-c` (Ctrl-C) token to a tmux pane via `tmux send-keys -t <target> C-c`; preserves tmux key notation, NOT raw \x03.
def tmux_sendCtrlC(pane_target: str) -> int:
    cmd = ["tmux", "send-keys", "-t", pane_target, "C-c"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(cmd)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
    return result.returncode


# Sends text to pane, sleeps 0.5s, then sends Enter as a separate call; returns first nonzero rc or rc of Enter send.
def tmux_sendAndSubmit(pane_target: str, text: str) -> int:
    rc1 = tmux_sendKeys(pane_target, text)
    if rc1 != 0:
        return rc1
    time.sleep(0.5)
    return tmux_sendEnter(pane_target)


# Writes a Claude settings JSON file (permissions.allow + hooks block) and returns the `claude --settings ... --add-dir ...` command string with trailing newline.
def claude_buildCmd(
    settings_out: str,
    allow_json: str,
    hooks_json_file: str,
    cwd: str,
    *extra_dirs: str,
) -> str:
    hooks_json = Path(hooks_json_file).read_text()
    settings_body = (
        "{\n"
        '  "permissions": {\n'
        f'    "allow": {allow_json}\n'
        "  },\n"
        f'  "hooks": {hooks_json}\n'
        "}\n"
    )
    Path(settings_out).write_text(settings_body)
    cmd = f"claude --settings '{settings_out}' --add-dir '{cwd}'"
    for extra in extra_dirs:
        cmd += f" --add-dir '{extra}'"
    return cmd + "\n"


# Repeatedly sends Ctrl-C (up to 5 times) until the pane buffer contains a 'Ctrl-C' marker, then submits the replacement text; logs label + Ctrl-C count when at least one retry was needed. Returns rc of final tmux_sendAndSubmit.
def tmux_cancelAndSend(pane_target: str, text: str, label: str | None = None) -> int:
    MAX_ATTEMPTS = 5
    attempts = 0
    for attempts in range(1, MAX_ATTEMPTS + 1):
        tmux_sendCtrlC(pane_target)
        time.sleep(0.2)
        if "Ctrl-C" in tmux_capturePane(pane_target):
            break
    if attempts > 1 and label:
        print(f"[tmux] cancelled in-progress work: {label} ({attempts} Ctrl-C's)")
    return tmux_sendAndSubmit(pane_target, text)


# Splits target via tmux split-window with -c <cwd> -P -F '#{pane_id}', launching cmd; returns the resulting pane id (e.g. '%42'). Returns None on tmux failure or empty pane id.
def tmux_splitWorkerPane(target: str, cwd: str, cmd: str) -> str | None:
    argv = [
        "tmux", "split-window",
        "-t", target,
        "-c", cwd,
        "-P", "-F", "#{pane_id}",
        cmd,
    ]
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(1).f_code.co_name
        cmd_str = " ".join(argv)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
        return None
    pane_id = (result.stdout or "").strip()
    if not pane_id:
        return None
    return pane_id


# Polls pane content for the Claude TUI ready glyph (❯, U+276F) every 0.5s up to timeout*2 attempts; returns 0 on detect, 1 on timeout (matches bash rc semantic). Capture errors are swallowed (bash `|| true`).
def tmux_waitForClaudeReadiness(pane_id: str, timeout: int = 10) -> int:
    max_attempts = int(timeout) * 2
    ready_glyph = "❯"
    for _ in range(max_attempts):
        try:
            content = tmux_capturePane(pane_id, 5)
        except Exception:
            content = ""
        if ready_glyph in (content or ""):
            return 0
        time.sleep(0.5)
    print(
        f"[tmux-launcher] tmux_waitForClaudeReadiness: timed out after {timeout}s waiting for pane '{pane_id}'",
        file=sys.stderr,
    )
    return 1


# Idempotently guarantees a keepalive pane with the requested title exists in a tmux window, creating and retiling only when absent.
def tmux_ensureKeepalivePane(target: str, cwd: str, keepalive_cmd: str, title: str) -> None:
    if tmux_paneHasTitle(target, title) == 0:
        return None
    ka_id = tmux_splitWorkerPane(target, cwd, keepalive_cmd)
    if ka_id:
        tmux_setPaneTitle(ka_id, title)
    tmux_retile(target)
    return None


# Ensures the named tmux session and window exist with a titled keepalive pane, applying session options on first creation.
def tmux_ensureSession(
    session: str,
    window: str,
    cwd: str,
    keepalive_cmd: str,
    keepalive_title: str,
) -> int:
    if tmux_hasSession(session) != 0:
        tmux_newSession(session, "-n", window, "-c", cwd, keepalive_cmd)
        tmux_setOptionForTarget(session, "remain-on-exit", "off")
        tmux_setOptionForTarget(session, "mouse", "on")
        tmux_setOptionForTarget(session, "pane-border-status", "top")
        tmux_setOptionForTarget(session, "pane-border-format", " #{pane_title} ")
        tmux_setPaneTitle(f"{session}:{window}.0", keepalive_title)
        return 0

    if tmux_windowExists(session, window) != 0:
        tmux_newWindow(session, window, "-c", cwd, keepalive_cmd)
        tmux_setPaneTitle(f"{session}:{window}.0", keepalive_title)
        return 0

    tmux_ensureKeepalivePane(f"{session}:{window}", cwd, keepalive_cmd, keepalive_title)
    return 0


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
    return tmux_sendAndSubmit(pane_target, prompt)


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


# Runs argv with a hard wall-clock timeout: SIGTERM after `secs`, then SIGKILL after a 1s grace (some agents trap SIGTERM). Returns child rc; signal-killed children return their post-signal rc.
def shell_runWithTimeout(secs: float, argv: Sequence[str]) -> int:
    proc = subprocess.Popen(list(argv), start_new_session=True)
    try:
        return proc.wait(timeout=secs)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            return proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        return proc.wait()


# Appends a single timestamped log line ("<ISO-8601> <prefix>: <message>") to log_file. No-op when log_file is None/empty. Write errors are swallowed (matches bash 2>/dev/null || true). Bash function read $log_file/$log_prefix via dynamic scoping; Python takes them as explicit params (Risk #4).
def claude_permseedLog(message: str, log_file: str | None, log_prefix: str = "plugin") -> None:
    if not log_file:
        return
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    line = f"{timestamp} {log_prefix}: {message}\n"
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        return


def _readFirstToken(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        line = fh.readline()
    parts = line.strip().split()
    return parts[0] if parts else ""


def _sha256File(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# Seeds or upgrades an installed permissions config from the bundled default; preserves user edits and records/logs default SHA transitions.
def claude_seedPermissions(
    installed: str,
    default: str,
    default_sha_file: str,
    prior_sha_file: str,
    log_file: str | None = None,
    log_prefix: str = "plugin",
) -> None:
    if not Path(default).is_file() or not Path(default_sha_file).is_file():
        claude_permseedLog(
            f"bundled permissions default missing at {default} - cannot seed",
            log_file,
            log_prefix,
        )
        return

    current_default_sha = _readFirstToken(default_sha_file)

    if not Path(installed).is_file():
        shutil.copyfile(default, installed)
        with open(prior_sha_file, "w", encoding="utf-8") as fh:
            fh.write(f"{current_default_sha}\n")
        claude_permseedLog(
            f"seeded {installed} from bundled default (sha={current_default_sha})",
            log_file,
            log_prefix,
        )
        return

    try:
        installed_sha = _sha256File(installed)
    except OSError:
        installed_sha = ""

    prior_sha = _readFirstToken(prior_sha_file) if Path(prior_sha_file).is_file() else ""

    if installed_sha == current_default_sha:
        return

    if prior_sha and installed_sha == prior_sha:
        shutil.copyfile(default, installed)
        with open(prior_sha_file, "w", encoding="utf-8") as fh:
            fh.write(f"{current_default_sha}\n")
        claude_permseedLog(
            f"upgraded {installed} to new bundled default "
            f"(was {prior_sha}, now {current_default_sha})",
            log_file,
            log_prefix,
        )
        return

    if prior_sha != current_default_sha:
        claude_permseedLog(
            f"{installed} is user-edited; bundled default updated - diff manually. "
            f"installed_sha={installed_sha} prior_sha={prior_sha} "
            f"current_default_sha={current_default_sha}",
            log_file,
            log_prefix,
        )
        with open(prior_sha_file, "w", encoding="utf-8") as fh:
            fh.write(f"{current_default_sha}\n")


def _terminalIsoNow() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _terminalAppendAdvisory(log_file: str, prefix: str, session: str) -> None:
    if not log_file or log_file == "/dev/null":
        return
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(
                f"{_terminalIsoNow()} {prefix}: osascript unavailable; "
                f"attach manually via `tmux attach -t {session}`\n"
            )
    except OSError:
        return


def _terminalAppendNonDarwinAdvisory(log_file: str, prefix: str, session: str) -> None:
    if not log_file or log_file == "/dev/null":
        return
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(
                f"{_terminalIsoNow()} {prefix}: non-Darwin host; "
                f"attach manually via `tmux attach -t {session}`\n"
            )
    except OSError:
        return


def _terminalMaximizeBlock(maximize: str) -> str:
    if maximize == "yes":
        return (
            '\ntell application "Finder"\n'
            "  set screenBounds to bounds of window of desktop\n"
            "end tell\n"
            'tell application "Terminal"\n'
            "  set bounds of front window to screenBounds\n"
            "end tell"
        )
    if maximize == "compact":
        return (
            '\ntell application "Finder"\n'
            "  set screenBounds to bounds of window of desktop\n"
            "end tell\n"
            "set sx to item 1 of screenBounds\n"
            "set sy to item 2 of screenBounds\n"
            "set ex to item 3 of screenBounds\n"
            "set ey to item 4 of screenBounds\n"
            "set winW to 1000\n"
            "set winH to 700\n"
            "set winX to sx + ((ex - sx - winW) div 2)\n"
            "set winY to sy + ((ey - sy - winH) div 2)\n"
            'tell application "Terminal"\n'
            "  set bounds of front window to {winX, winY, winX + winW, winY + winH}\n"
            "end tell"
        )
    return ""


def _terminalBuildOsascript(session: str, maximize: str) -> str:
    return (
        f'if application "Terminal" is running then\n'
        f'  tell application "Terminal" to do script "tmux attach -t {session}"\n'
        f"else\n"
        f'  tell application "Terminal"\n'
        f'    do script "tmux attach -t {session}" in window 1\n'
        f"  end tell\n"
        f"end if{_terminalMaximizeBlock(maximize)}"
    )


def _terminalListTmuxClients(session: str) -> str:
    try:
        result = subprocess.run(
            ["tmux", "list-clients", "-t", session],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout
    except (OSError, FileNotFoundError):
        return ""


# Spawns a macOS Terminal.app window attached to a tmux session when there are no attached clients; logs manual-attach advice on unsupported hosts.
def terminal_spawnIfNeeded(
    session: str,
    log_file: str = "/dev/null",
    log_prefix: str = "tmux",
    maximize: str = "",
) -> int:
    if not session:
        raise ValueError("terminal_spawnIfNeeded: session name required")

    clients = _terminalListTmuxClients(session)
    if clients.strip():
        return 0

    if sys.platform == "darwin":
        if shutil.which("osascript") is None:
            _terminalAppendAdvisory(log_file, log_prefix, session)
            return 0
        script = _terminalBuildOsascript(session, maximize)
        try:
            subprocess.Popen(
                ["osascript"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).communicate(input=script.encode("utf-8"), timeout=None)
        except (OSError, subprocess.SubprocessError):
            pass
        return 0

    _terminalAppendNonDarwinAdvisory(log_file, log_prefix, session)
    return 0


class LockTimeout(TimeoutError):
    """Raised when FileLock cannot acquire within the timeout window."""


class FileLock:
    """Exclusive file lock using fcntl.flock with a polling timeout."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        timeout: float = 10.0,
        poll_interval: float = 0.05,
    ) -> None:
        self._path = Path(path)
        self._timeout = float(timeout)
        self._poll = float(poll_interval)
        self._fd: Optional[int] = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def acquired(self) -> bool:
        return self._fd is not None

    def acquire(self) -> "FileLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self._path), os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + self._timeout
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._fd = fd
                    return self
                except OSError as exc:
                    if exc.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):
                        raise
                    if time.monotonic() >= deadline:
                        raise LockTimeout(
                            f"FileLock: timed out after {self._timeout}s on {self._path}"
                        ) from exc
                    time.sleep(self._poll)
        except BaseException:
            os.close(fd)
            raise

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "FileLock":
        return self.acquire()

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.release()


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

    shutil.copy(
        f"{claude_plugin_root}/scripts/jot-plugin-orchestrator.sh",
        f"{tmpdir_inv}/jot-plugin-orchestrator.sh",
    )

    default_file = f"{claude_plugin_root}/skills/jot/scripts/assets/permissions.default.json"
    default_sha_file = f"{default_file}.sha256"
    prior_sha_file = f"{claude_plugin_data}/permissions.default.sha256"
    Path(claude_plugin_data).mkdir(parents=True, exist_ok=True)

    seed_fn = permissions_seed or _jotDefaultPermissionsSeed
    seed_fn(
        permissions_file,
        default_file,
        default_sha_file,
        prior_sha_file,
        log_file,
        "jot",
    )

    expand_fn = expand_permissions or _jotDefaultExpandPermissions
    env = {"CWD": cwd, "HOME": home, "REPO_ROOT": repo_root}
    allow_json = expand_fn(permissions_file, env)

    hooks_json_file = f"{tmpdir_inv}/hooks.json"
    hooks_body = (
        "{\n"
        '  "SessionStart": [{"hooks": [{"type": "command", "command": "bash '
        f"{tmpdir_inv}/jot-plugin-orchestrator.sh jot-session-start '{input_file}' '{tmpdir_inv}'"
        '"}]}],\n'
        '  "Stop":         [{"hooks": [{"type": "command", "command": "bash '
        f"{tmpdir_inv}/jot-plugin-orchestrator.sh jot-stop '{input_file}' '{tmpdir_inv}' '{state_dir}'"
        '"}]}],\n'
        '  "SessionEnd":   [{"hooks": [{"type": "command", "command": "bash '
        f"{tmpdir_inv}/jot-plugin-orchestrator.sh jot-session-end '{tmpdir_inv}'"
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


def _jotDefaultPermissionsSeed(
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


def _jotDefaultExpandPermissions(permissions_file: str, env: dict[str, str]) -> str:
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


def _jotAppendLog(log_file: str, message: str) -> None:
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
                _jotAppendLog(log_file, "[jot] tmux split-window returned empty pane id\n")
                return 1

            target_path = Path(tmpdir_inv) / "tmux_target"
            tmp_path = Path(tmpdir_inv) / "tmux_target.tmp"
            tmp_path.write_text(f"{pane_id}\n")
            os.replace(tmp_path, target_path)

            tmux_setPaneTitle(pane_id, pane_label)
            tmux_retile("jot:jots")
    except LockTimeout:
        _jotAppendLog(log_file, f"[jot] failed to acquire global tmux-launch lock at {tmux_lock}\n")
        return 1

    terminal_spawnIfNeeded("jot", log_file, "jot")
    return 0


_DIAG_SECTION_RULE = "═" * 59


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


def debate_agentReadyMarker(agent: str) -> str:
    # GREEN: mirror bash `agent_ready_marker` case statement verbatim.
    if agent == "gemini":
        return "Type your message or @path/to/file"
    if agent == "codex":
        return "/model to change"
    if agent == "claude":
        return "Claude Code v"
    # Bash `case` with no default leaves stdout empty.
    return ""


# Frozen tuples used as the source of truth; copied into a fresh list per
# call so callers cannot mutate shared state.
_MARKERS: dict[str, tuple[str, ...]] = {
    "codex": (
        "Selected model is at capacity",
        "model is overloaded",
    ),
    "gemini": (
        "RESOURCE_EXHAUSTED",
        "Quota exceeded",
        "You exceeded your current quota",
    ),
    "claude": (
        "API Error: 529",
        "overloaded_error",
    ),
}


def debate_agentErrorMarkers(agent: str) -> list[str]:
    """Return capacity/quota/overload error markers for ``agent``.

    Mirrors bash `agent_error_markers`: a case statement over
    ``codex|gemini|claude`` printing one marker per line. Unknown agent
    names yield an empty list (bash printed nothing).

    Args:
        agent: Agent identifier (``codex``, ``gemini``, or ``claude``).

    Returns:
        Ordered list of marker substrings. Empty list for unknown agents.
    """
    return list(_MARKERS.get(agent, ()))


# YELLOW intent: build the per-agent shell command string used by tmux to start
# the debate agent CLI. Looks up the current model from a stash dict (empty
# string => omit --model). For claude, dedupe --add-dir entries so the same
# directory isn't passed twice when CWD/REPO_ROOT/$HOME/.claude/plans collide.
def debate_agentLaunchCmd(
    *,
    agent: str,
    current_model: dict[str, str],
    debate_dir: str,
    cwd: str,
    repo_root: str,
    home: str,
    settings_file: str,
) -> str:
    # Lookup model from stash; bash _lookup CURRENT_MODEL "$a" returns "" when unset.
    m = current_model.get(agent, "")

    if agent == "gemini":
        base = "gemini --allowed-tools 'read_file,write_file,run_shell_command(ls)'"
        if m:
            return f"{base} --model '{m}'"
        return base

    if agent == "codex":
        base = f"codex -a never --add-dir '{debate_dir}'"
        if m:
            return f"{base} --model '{m}'"
        return base

    if agent == "claude":
        # Mirror bash dedupe logic exactly:
        #   dirs="--add-dir '$CWD'"
        #   [ -n "$REPO_ROOT" ] && [ "$REPO_ROOT" != "$CWD" ] && dirs+=" --add-dir '$REPO_ROOT'"
        #   [ "$HOME/.claude/plans" != "$CWD" ] && [ "$HOME/.claude/plans" != "$REPO_ROOT" ] \
        #       && dirs+=" --add-dir '$HOME/.claude/plans'"
        plans = f"{home}/.claude/plans"
        dirs = f"--add-dir '{cwd}'"
        if repo_root and repo_root != cwd:
            dirs += f" --add-dir '{repo_root}'"
        if plans != cwd and plans != repo_root:
            dirs += f" --add-dir '{plans}'"
        return f"claude --settings '{settings_file}' {dirs}"

    # Bash case statement falls through silently for unknown agent.
    return ""


# YELLOW intent (plain English):
#   Move all "intermediate" debate scratch files from DEBATE_DIR into
#   DEBATE_DIR/archive/. The bash glob list pins exactly which files count as
#   intermediate: context.md, synthesis_instructions.txt, r1_instructions_*.txt,
#   r1_*.md, r2_instructions_*.txt, r2_*.md, and orchestrator.log. The final
#   synthesis.md and primary inputs (topic.md, invoking_transcript.txt) are
#   intentionally excluded so they remain at the debate root. mkdir -p
#   semantics: a pre-existing archive/ directory is fine and its prior
#   contents are preserved.

# Move debate intermediate scratch files into DEBATE_DIR/archive/.
# Mirrors bash `archive_debate`: creates archive subdir (idempotent),
# then moves a fixed set of patterns. synthesis.md and topic.md are
# preserved at the debate root by exclusion (not in the pattern list).
def debate_archive(debate_dir: Path | str) -> None:
    debate_dir = Path(debate_dir)
    archive_dir = debate_dir / "archive"
    # mkdir -p "$DEBATE_DIR/archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Bash for-loop expands each literal path and each glob; literal paths
    # that don't exist are kept as-is by the shell, then filtered by `[ -f ]`.
    # We mirror that with explicit literal checks plus glob expansion.
    literals = (
        debate_dir / "context.md",
        debate_dir / "synthesis_instructions.txt",
    )
    glob_patterns = (
        "r1_instructions_*.txt",
        "r1_*.md",
        "r2_instructions_*.txt",
        "r2_*.md",
    )

    candidates: list[Path] = []
    candidates.extend(p for p in literals if p.is_file())
    for pattern in glob_patterns:
        candidates.extend(p for p in debate_dir.glob(pattern) if p.is_file())

    for src in candidates:
        # Move into archive_dir using the original filename. Path.replace
        # gives atomic same-filesystem rename semantics matching `mv`.
        src.replace(archive_dir / src.name)

    # Separate orchestrator.log clause in bash (handled outside the loop).
    log = debate_dir / "orchestrator.log"
    if log.is_file():
        log.replace(archive_dir / log.name)


# Provisions a fresh /tmp/debate.* dir, seeds permissions, expands them via the
# injected expand_permissions_fn, then calls claude_buildCmd to write
# settings.json and produce the launch cmd. Returns dict with tmpdir_inv,
# settings_file, cmd. permissions_seed_fn / expand_permissions_fn are injected
# so tests do not require the bash helpers or expand_permissions.py subprocess.
def debate_buildClaudeCmd(
    cwd: str,
    repo_root: str,
    log_file: str,
    permissions_seed_fn,
    expand_permissions_fn,
) -> dict:
    plugin_data = os.environ["CLAUDE_PLUGIN_DATA"]
    plugin_root = os.environ["CLAUDE_PLUGIN_ROOT"]

    # YELLOW intent: mirror bash mktemp -d /tmp/debate.XXXXXX, then build
    # settings_file path inside it.
    tmpdir_inv = tempfile.mkdtemp(prefix="debate.", dir="/tmp")
    settings_file = str(Path(tmpdir_inv) / "settings.json")

    permissions_file = str(Path(plugin_data) / "debate-permissions.local.json")
    default_file = str(
        Path(plugin_root) / "skills/debate/scripts/assets/permissions.default.json"
    )
    default_sha_file = str(
        Path(plugin_root) / "skills/debate/scripts/assets/permissions.default.json.sha256"
    )
    prior_sha_file = str(Path(plugin_data) / "debate-permissions.default.sha256")

    # mkdir -p "$CLAUDE_PLUGIN_DATA"
    Path(plugin_data).mkdir(parents=True, exist_ok=True)

    permissions_seed_fn(
        permissions_file,
        default_file,
        default_sha_file,
        prior_sha_file,
        log_file,
        "debate",
    )

    allow_json = expand_permissions_fn(
        permissions_file, cwd, repo_root, os.environ.get("HOME", "")
    )

    # Empty hooks JSON file — claude_buildCmd needs a path.
    hooks_json_file = str(Path(tmpdir_inv) / "hooks.json")
    Path(hooks_json_file).write_text("{}\n")

    cmd = claude_buildCmd(  # noqa: F405  (star import from monolith)
        settings_file, allow_json, hooks_json_file, cwd, repo_root
    )

    return {
        "tmpdir_inv": tmpdir_inv,
        "settings_file": settings_file,
        "cmd": cmd,
    }


def debate_buildClaudePrompts(
    stage: str,
    debate_dir: Path,
    plugin_root: Path,
    agents: list[str],
    agent_filter: str = "",
) -> None:
    """Build debate instruction files for the given stage.

    Args:
        stage:        One of "r1", "r2", "synthesis".
        debate_dir:   Path to the debate working directory.
        plugin_root:  Path to the plugin root (CLAUDE_PLUGIN_ROOT).
        agents:       List of active agent names. If empty, read from
                      debate_dir/agents.txt (mirrors DEBATE_AGENTS env var).
        agent_filter: When non-empty, emit only that agent's file (mirrors
                      AGENT_FILTER env var).

    Raises:
        ValueError: If stage is not one of the three recognised values.
    """
    debate_dir = Path(debate_dir)
    plugin_root = Path(plugin_root)

    # Resolve agent list -- fall back to agents.txt when list is empty.
    if not agents:
        agents_file = debate_dir / "agents.txt"
        agents = [
            line
            for line in agents_file.read_text().splitlines()
            if line.strip()
        ]

    if stage == "r1":
        _build_r1(stage, debate_dir, plugin_root, agents, agent_filter)
    elif stage == "r2":
        _build_r2(debate_dir, agents, agent_filter)
    elif stage == "synthesis":
        _build_synthesis(debate_dir, agents)
    else:
        raise ValueError(f"Unknown stage: {stage!r}")


def _build_r1(
    stage: str,
    debate_dir: Path,
    plugin_root: Path,
    agents: list[str],
    agent_filter: str,
) -> None:
    """Render r1.template.md for each agent and write r1_instructions_<agent>.txt.

    The bash original delegated to render_template.py with two var overrides:
        DEBATE_DIR=<debate_dir>  OUTPUT_FILE=<debate_dir>/r1_<agent>.md
    We call the same script via subprocess to stay faithful to the original.
    """
    render = plugin_root / "common" / "scripts" / "jot" / "render_template.py"
    template = plugin_root / "skills" / "debate" / "prompts" / "r1.template.md"

    for agent in agents:
        if agent_filter and agent_filter != agent:
            continue
        output_file = debate_dir / f"r1_{agent}.md"
        instructions_file = debate_dir / f"r1_instructions_{agent}.txt"

        if render.exists():
            # Call render_template.py exactly as bash did.
            env_overrides = {
                "DEBATE_DIR": str(debate_dir),
                "OUTPUT_FILE": str(output_file),
            }
            import os
            env = os.environ.copy()
            env.update(env_overrides)
            result = subprocess.run(
                [sys.executable, str(render), str(template), "DEBATE_DIR", "OUTPUT_FILE"],
                capture_output=True,
                text=True,
                env=env,
            )
            instructions_file.write_text(result.stdout)
        else:
            # Fallback: minimal template substitution for testing without
            # the real render_template.py on disk.
            raw = template.read_text()
            rendered = raw.replace("{{DEBATE_DIR}}", str(debate_dir))
            rendered = rendered.replace("{{OUTPUT_FILE}}", str(output_file))
            instructions_file.write_text(rendered)


def _build_r2(
    debate_dir: Path,
    agents: list[str],
    agent_filter: str,
) -> None:
    """Build r2 cross-critique instruction files inline (mirrors bash printf block)."""
    for agent in agents:
        if agent_filter and agent_filter != agent:
            continue
        others = [a for a in agents if a != agent]
        buf = StringIO()
        buf.write("# Debate -- Round 2: Cross-Critique\n\n")
        buf.write(f"## Your Round 1 Response\nRead from: {debate_dir}/r1_{agent}.md\n\n")
        buf.write("## Other Agents' Round 1 Responses\n")
        for other in others:
            buf.write(f"Read {other}'s response from: {debate_dir}/r1_{other}.md\n")
        buf.write("\n## Instructions\n")
        buf.write("- Identify agreement and disagreement across responses\n")
        buf.write("- Validate or challenge claims with evidence\n")
        buf.write("- Concede where others made stronger arguments\n")
        buf.write("- Raise new considerations from reading their perspectives\n")
        buf.write(
            f"\n## Output\nWrite your critique as markdown to: {debate_dir}/r2_{agent}.md\n"
            "Do not write to any other file.\n"
        )
        (debate_dir / f"r2_instructions_{agent}.txt").write_text(buf.getvalue())


def _build_synthesis(debate_dir: Path, agents: list[str]) -> None:
    """Build synthesis instruction file inline (mirrors bash printf block)."""
    agents_str = " ".join(agents)
    buf = StringIO()
    buf.write("# Debate -- Round 3: Synthesis\n\n")
    buf.write(
        f"{len(agents)} agents ({agents_str}) debated across two rounds. "
        "Produce a balanced assessment.\n\n"
    )
    buf.write("## Round 1 Responses\n")
    for agent in agents:
        buf.write(f"Read {agent} R1 from: {debate_dir}/r1_{agent}.md\n")
    buf.write("\n## Round 2 Responses\n")
    for agent in agents:
        buf.write(f"Read {agent} R2 from: {debate_dir}/r2_{agent}.md\n")
    buf.write("\n## Structure\n")
    buf.write("1. **Topic**: One-line restatement\n")
    buf.write("2. **Agreement**: Where agents align\n")
    buf.write("3. **Disagreement**: Where they diverge, strongest argument per side\n")
    buf.write("4. **Strongest Arguments**: Most compelling points, attributed\n")
    buf.write("5. **Weaknesses**: Arguments successfully challenged in R2\n")
    buf.write("6. **Path Forward**: Synthesized recommendation\n")
    buf.write("7. **Confidence**: High/Medium/Low with reasoning\n")
    buf.write("8. **Open Questions**: Unresolved issues\n")
    buf.write(
        f"\n## Output\nWrite synthesis as markdown to: {debate_dir}/synthesis.md\n"
        "Do not write to any other file.\n"
    )
    (debate_dir / "synthesis_instructions.txt").write_text(buf.getvalue())


@dataclass
class ResumeFeasibility:
    """Result of a resume feasibility check.

    feasible           True iff debate can be resumed.
    updated_agents     Effective agent list. Includes 'disappeared' originals
                       whose r1_*.md AND r2_*.md outputs already exist (their
                       cached outputs will be reused at synthesis).
    unusable_agents    Originals that are unavailable AND lack complete outputs.
                       Empty when feasible is True.
    reason             Human-readable block message when not feasible, else "".
    """
    feasible: bool
    updated_agents: list[str]
    unusable_agents: list[str]
    reason: str


# debate_checkResumeFeasibility — port of bash check_resume_feasibility.
#
# Derives the original debate composition from r1_instructions_<agent>.txt
# filenames in `debate_dir`. For each original agent:
#   - If still in `available_agents`: keep, no change.
#   - If 'disappeared' (missing from `available_agents`) BUT both
#     r1_<agent>.md and r2_<agent>.md exist and are non-empty: re-add to the
#     effective agent list so synthesis includes the cached outputs.
#   - If 'disappeared' AND outputs are missing/empty: mark unusable.
# 'Appeared' agents (present in available_agents but not original) are accepted
# implicitly (they remain in the returned list) — instructions are built JIT.
#
# Returns a ResumeFeasibility. Caller decides whether to emit_block + exit;
# this function performs no I/O beyond filesystem inspection. RELAXED_COVERAGE.
def debate_checkResumeFeasibility(
    debate_dir: Path,
    available_agents: list[str],
) -> ResumeFeasibility:
    debate_dir = Path(debate_dir)

    # Discover original composition from r1_instructions_<agent>.txt files.
    original: list[str] = []
    if debate_dir.is_dir():
        for path in sorted(debate_dir.glob("r1_instructions_*.txt")):
            if not path.is_file():
                continue
            agent = path.stem[len("r1_instructions_"):]
            if agent:
                original.append(agent)

    # Work on a copy so caller's list is not mutated.
    updated = list(available_agents)
    unusable: list[str] = []

    for orig in original:
        if orig in updated:
            # Still available — nothing to do.
            continue
        # Disappeared — reusable iff both R1 and R2 outputs are non-empty.
        r1 = debate_dir / f"r1_{orig}.md"
        r2 = debate_dir / f"r2_{orig}.md"
        r1_ok = r1.is_file() and r1.stat().st_size > 0
        r2_ok = r2.is_file() and r2.stat().st_size > 0
        if r1_ok and r2_ok:
            updated.append(orig)
        else:
            unusable.append(orig)

    if unusable:
        joined = "".join(f" {a}" for a in unusable)
        reason = (
            "/debate: cannot resume, these original agents are unavailable "
            "and their outputs are incomplete:"
            f"{joined}. Fix credentials/quota and re-run '/debate <topic>', "
            "or '/debate-abort' to delete."
        )
        return ResumeFeasibility(
            feasible=False,
            updated_agents=updated,
            unusable_agents=unusable,
            reason=reason,
        )

    return ResumeFeasibility(
        feasible=True,
        updated_agents=updated,
        unusable_agents=[],
        reason="",
    )


# Standard temp-file header: ensure scripts dir importable for any future
# cross-stub references (FileLock not currently required by this function).
_HERE = Path(__file__).resolve().parent


_MAX_SESSIONS = 999


def _default_tmux_runner(argv: List[str]) -> int:
    """Real tmux invocation: run `argv` and return the exit code.

    stdout/stderr suppressed because collisions are an expected control-flow
    signal, not an error condition the user should see (mirrors the bash
    `hide_errors` wrapper around the original tmux call).
    """
    proc = subprocess.run(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return proc.returncode


def debate_claimSession(
    keepalive_cmd: str,
    *,
    tmux_runner: Callable[[List[str]], int] = _default_tmux_runner,
) -> str:
    """Atomically claim the lowest-unused `debate-N` tmux session.

    Args:
        keepalive_cmd: Shell command that becomes the argv of the new session's
            first window (named `main`). Typically a long-lived no-op like
            `sleep 86400` so the session persists for daemon attachment.
        tmux_runner: Injectable runner that takes argv and returns rc. The
            default invokes real tmux; tests pass a fake.

    Returns:
        The claimed session name, e.g. ``"debate-7"``.

    Raises:
        RuntimeError: If no slot in ``debate-1`` .. ``debate-999`` is free.
    """
    for n in range(1, _MAX_SESSIONS + 1):
        session = f"debate-{n}"
        argv = [
            "tmux", "new-session", "-d",
            "-s", session,
            "-x", "200",
            "-y", "60",
            "-n", "main",
            keepalive_cmd,
        ]
        if tmux_runner(argv) == 0:
            return session
    raise RuntimeError(
        f"debate_claimSession: exhausted {_MAX_SESSIONS} session slots"
    )


# YELLOW intent: scan DEBATE_DIR/.{stage}_*.lock; for each lock parse "debate:%N";
# remove the lock if the pane id is missing/malformed, the pane no longer exists in
# the tmux window, or the pane's current command differs from the agent name.

_PANE_ID_RE = re.compile(r"^debate:(%\d+)$", re.MULTILINE)


# Boundary seam: returns the set of live pane ids (e.g. {"%5","%7"}) in WINDOW_TARGET.
# Tests patch this; production callers pass `window_target` from the orchestrator.
def _listLivePaneIds(window_target: str) -> set[str]:
    try:
        out = subprocess.run(
            ["tmux", "list-panes", "-t", window_target, "-F", "#{pane_id}"],
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if out.returncode != 0:
        return set()
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


# Boundary seam: returns the pane's current foreground command (e.g. "gemini","codex","bash").
# Tests patch this.
def _paneCurrentCommand(pane_id: str) -> str:
    try:
        out = subprocess.run(
            ["tmux", "display-message", "-p", "-t", pane_id, "#{pane_current_command}"],
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if out.returncode != 0:
        return ""
    return out.stdout.strip()


# Remove stale per-agent lock files for `stage` under `debate_dir`. A lock is stale
# when its recorded pane id is unparseable, no longer present in `window_target`,
# or whose pane is running a command other than the lock's agent name.
def debate_cleanStaleLocks(
    debate_dir: Path,
    stage: str,
    window_target: str = "",
) -> None:
    debate_dir = Path(debate_dir)
    prefix = f".{stage}_"
    locks = sorted(debate_dir.glob(f"{prefix}*.lock"))
    if not locks:
        return
    live_panes: set[str] | None = None  # lazily fetched on first lock that needs it
    for lock in locks:
        if not lock.is_file():
            continue
        # Derive agent name from filename: ".<stage>_<agent>.lock"
        agent = lock.name[len(prefix):-len(".lock")]
        # Parse "debate:%N" payload (matches bash sed regex exactly).
        try:
            payload = lock.read_text()
        except OSError:
            payload = ""
        match = _PANE_ID_RE.search(payload)
        if match is None:
            lock.unlink(missing_ok=True)
            continue
        pane_id = match.group(1)
        if live_panes is None:
            live_panes = _listLivePaneIds(window_target)
        if pane_id not in live_panes:
            lock.unlink(missing_ok=True)
            continue
        current = _paneCurrentCommand(pane_id)
        if current != agent:
            lock.unlink(missing_ok=True)


# Reads launch-time (index 0) model name for `agent` from
# ${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/assets/models.json.
# Returns "" when the agent key is absent or its model list is empty.
# Raises KeyError if CLAUDE_PLUGIN_ROOT is unset (mirrors bash `:?` guard).
def debate_defaultModel(agent: str) -> str:
    plugin_root = os.environ["CLAUDE_PLUGIN_ROOT"]
    models_json = Path(plugin_root) / "skills" / "debate" / "scripts" / "assets" / "models.json"
    try:
        data = json.loads(models_json.read_text())
    except (OSError, json.JSONDecodeError):
        # Bash wraps jq with `hide_errors`; an unreadable/invalid file
        # surfaces as empty stdout, which probes treat as "unavailable".
        return ""
    entry = data.get(agent)
    if not isinstance(entry, list) or not entry:
        return ""
    first = entry[0]
    return first if isinstance(first, str) else ""


class DetectResult(TypedDict):
    """Aggregate result of agent detection.

    Attributes:
        available: Ordered list of usable agent names (claude always first).
        gemini_model: Model string for gemini, or "" if unavailable / sentinel.
        codex_model: Model string for codex, or "" if unavailable / sentinel.
    """
    available: list[str]
    gemini_model: str
    codex_model: str


# Sentinel returned by probes when binary+credentials exist but no model is
# configured. Marks the agent as available without populating a model name.
_PRESENT_SENTINEL = "present"


def debate_detectAvailableAgents() -> DetectResult:
    """Detect which debate agents are usable; return aggregate dict.

    Probes gemini and codex concurrently (I/O-bound: PATH + filesystem).
    Claude is always treated as available — no probe required.

    Returns:
        DetectResult with `available` list and per-agent model fields.

    Behavior parity with bash `detect_available_agents`:
        AVAILABLE_AGENTS starts with [claude]; gemini/codex appended only
        when their probe returns non-empty. Model fields stay "" if probe
        returned "" OR the "present" sentinel.
    """
    # Run both probes in parallel; ThreadPoolExecutor matches bash's two
    # backgrounded subshells joined by `wait`.
    with ThreadPoolExecutor(max_workers=2) as pool:
        gemini_future = pool.submit(debate_probeGemini)
        codex_future = pool.submit(debate_probeCodex)
        gemini_out = gemini_future.result()
        codex_out = codex_future.result()

    # Claude is always available — no probe.
    available: list[str] = ["claude"]
    gemini_model = ""
    codex_model = ""

    # Non-empty probe output ⇒ agent is usable. Capture model only when
    # the output is a real model name (not the "present" sentinel).
    if gemini_out:
        available.append("gemini")
        if gemini_out != _PRESENT_SENTINEL:
            gemini_model = gemini_out

    if codex_out:
        available.append("codex")
        if codex_out != _PRESENT_SENTINEL:
            codex_model = codex_out

    return {
        "available": available,
        "gemini_model": gemini_model,
        "codex_model": codex_model,
    }


def debate_findMatching(repo_root: str, topic: str) -> Optional[str]:
    """Return path to most-recent Debates/<ts>/ whose topic.md byte-equals `topic` + '\\n'.

    Args:
        repo_root: Path to repository root containing Debates/ subdir.
        topic: Topic text (function appends '\\n' before comparison, mirroring
               bash `printf '%s\\n'`).

    Returns:
        Absolute-style dir path string (no trailing slash), or None if no match.
    """
    debates = Path(repo_root) / "Debates"
    if not debates.is_dir():
        return None

    # Bash compared `printf '%s\n' "$topic"` to the file via cmp -s. Replicate
    # that by appending a single newline to the query before byte-compare.
    needle = (topic + "\n").encode("utf-8", errors="surrogateescape")

    best_ts = ""
    best_dir: Optional[str] = None
    for entry in debates.iterdir():
        if not entry.is_dir():
            continue
        topic_md = entry / "topic.md"
        if not topic_md.is_file():
            continue
        try:
            haystack = topic_md.read_bytes()
        except OSError:
            continue
        if haystack != needle:
            continue
        ts = entry.name
        # Lexicographic comparison matches bash `[[ "$ts" > "$match_ts" ]]`.
        if ts > best_ts:
            best_ts = ts
            best_dir = str(entry)

    return best_dir


# Agents in the order the bash loop initializes them.
_AGENTS = ("gemini", "codex", "claude")


# Map agent -> env var name that seeds CURRENT_MODEL/TRIED_MODELS.
# claude has no seed env var (matches bash, which only stashes "" for it).
_AGENT_ENV_VAR = {"gemini": "GEMINI_MODEL", "codex": "CODEX_MODEL"}


def debate_initAgentModels(env: Mapping[str, str] | None = None) -> dict[str, dict[str, str]]:
    """Build initial agent-model state for a debate.

    Returns a fresh mapping of:
        {
            "CURRENT_MODEL": {agent: model_or_empty, ...},
            "TRIED_MODELS":  {agent: model_or_empty, ...},
        }
    seeded from `env` (defaults to os.environ). Mirrors bash ${VAR:-}: an
    unset env var becomes "".
    """
    # Read os.environ lazily so monkeypatch.setenv works for callers omitting env.
    src: Mapping[str, str] = os.environ if env is None else env

    state: dict[str, dict[str, str]] = {
        "CURRENT_MODEL": {a: "" for a in _AGENTS},
        "TRIED_MODELS": {a: "" for a in _AGENTS},
    }

    for agent, var in _AGENT_ENV_VAR.items():
        seed = src.get(var, "") or ""
        state["CURRENT_MODEL"][agent] = seed
        state["TRIED_MODELS"][agent] = seed

    return state


def debate_initHookContext(stdin: IO[str] | None = None) -> dict[str, Any]:
    """Initialise the debate hook context.

    Reads hook JSON from `stdin` (or `sys.stdin` if not provided) and returns
    a dict with the following keys (matching the bash globals):

        SCRIPTS_DIR     - $CLAUDE_PLUGIN_ROOT/skills/debate/scripts
        LOG_FILE        - $DEBATE_LOG_FILE or $CLAUDE_PLUGIN_DATA/debate-log.txt
        INPUT           - raw stdin text
        CWD             - JSON .cwd, fallback to os.getcwd()
        TRANSCRIPT_PATH - JSON .transcript_path, "" if absent
        REPO_ROOT       - git toplevel for CWD, "" if not in a repo

    Raises RuntimeError if CLAUDE_PLUGIN_ROOT or CLAUDE_PLUGIN_DATA is unset
    (mirrors bash `: "${VAR:?...}"` guard).
    """
    # Required env vars (bash `:?` semantics).
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not plugin_root:
        raise RuntimeError("debate plugin env not set: CLAUDE_PLUGIN_ROOT")
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not plugin_data:
        raise RuntimeError("debate plugin env not set: CLAUDE_PLUGIN_DATA")

    scripts_dir = str(Path(plugin_root) / "skills" / "debate" / "scripts")

    # LOG_FILE: env override wins; otherwise default under plugin data dir.
    log_file = os.environ.get("DEBATE_LOG_FILE") or str(
        Path(plugin_data) / "debate-log.txt"
    )
    # `mkdir -p "$(dirname "$LOG_FILE")"` (errors hidden in bash; we ignore).
    try:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    # Read raw stdin (preserve exactly, matches bash $(cat) semantics).
    src = stdin if stdin is not None else sys.stdin
    raw_input = src.read()

    # Parse JSON; tolerate empty / malformed input by treating as no fields.
    try:
        payload = json.loads(raw_input) if raw_input.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
    except json.JSONDecodeError:
        payload = {}

    cwd = payload.get("cwd") or os.getcwd()
    transcript_path = payload.get("transcript_path") or ""

    # `git -C "$CWD" rev-parse --show-toplevel`, swallow failure -> "".
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        repo_root = result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, FileNotFoundError):
        repo_root = ""

    return {
        "SCRIPTS_DIR": scripts_dir,
        "LOG_FILE": log_file,
        "INPUT": raw_input,
        "CWD": str(cwd),
        "TRANSCRIPT_PATH": str(transcript_path),
        "REPO_ROOT": repo_root,
    }


def _terminal_running() -> bool:
    """Return True if Terminal.app process is found via pgrep."""
    result = subprocess.run(
        ["pgrep", "-q", "Terminal"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _launch_terminal_background() -> None:
    """Fire-and-forget: launch Terminal.app via osascript without activating."""
    subprocess.Popen(
        ["osascript", "-e", "tell application \"Terminal\" to launch"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def debate_launch(
    *,
    scripts_dir: Path | None = None,
    plugin_root: Path | None = None,
    _debate_main_fn: object = None,
    _is_darwin: bool | None = None,
    _terminal_running_fn: object = None,
    _launch_terminal_fn: object = None,
) -> None:
    """Entry point for the debate-orchestrator subcommand.

    Resolves SCRIPTS_DIR and PLUGIN_ROOT, optionally ensures Terminal.app is
    running on Darwin (fire-and-forget), then delegates to debate_main().

    Args:
        scripts_dir: Override for the directory containing this script.
            Defaults to the real __file__ parent.
        plugin_root: Override for the plugin root (three levels up from
            scripts_dir). Defaults to computed value.
        _debate_main_fn: Injectable debate_main for testing.
        _is_darwin: Injectable OS check for testing (None = use platform).
        _terminal_running_fn: Injectable pgrep probe for testing.
        _launch_terminal_fn: Injectable Terminal.app launch for testing.
    """
    # Step 1: resolve paths (mirrors bash SCRIPTS_DIR / PLUGIN_ROOT logic).
    if scripts_dir is None:
        scripts_dir = Path(__file__).resolve().parent
    if plugin_root is None:
        plugin_root = (scripts_dir / ".." / ".." / "..").resolve()

    # Export to environment so debate_main and its callees can read them.
    os.environ.setdefault("PLUGIN_ROOT", str(plugin_root))

    # Step 2: Darwin Terminal.app guard (no-op on non-Darwin or already running).
    is_darwin = (platform.system() == "Darwin") if _is_darwin is None else _is_darwin
    terminal_running_fn = _terminal_running_fn or _terminal_running
    launch_terminal_fn = _launch_terminal_fn or _launch_terminal_background

    if is_darwin and not terminal_running_fn():
        launch_terminal_fn()

    # Step 3: delegate all real work.
    main_fn = _debate_main_fn or debate_main
    main_fn()


# ---------------------------------------------------------------------------
# Workspace-fallback imports
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent


_SCRIPTS = _HERE.parent


# Allow tests to patch the sleep call cleanly.
time_sleep = time.sleep


def debate_launchAgent(
    *,
    pane_id: str,
    stage: str,
    agent: str,
    launch_cmd: str,
    ready_marker: str,
    debate_dir: str,
    timeout: int = 120,
) -> bool:
    """Launch a debate agent inside *pane_id* and wait for it to become ready.

    Mirrors bash ``launch_agent pane_id stage agent launch_cmd ready_marker [timeout]``.

    Args:
        pane_id:      tmux pane id (e.g. ``%7``).
        stage:        Debate stage label (``r1``, ``r2``, ``synthesis``).
        agent:        Agent name (``gemini``, ``codex``, ``claude``).
        launch_cmd:   Shell command string sent to the pane.
        ready_marker: Substring that signals the agent CLI is ready.
        debate_dir:   Path to the debate working directory.
        timeout:      Max iterations (seconds) to wait. Default 120.

    Returns:
        ``True`` on success; ``False`` on timeout (write_failed also called).
    """
    # Step 1: claim the lock file (bash: printf 'debate:%s\\n' "$pane_id" > lock)
    lock_path = Path(debate_dir) / f".{stage}_{agent}.lock"
    lock_path.write_text(f"debate:{pane_id}\n")

    # Step 2: send the launch command (bash: tmux_send_and_submit "$pane_id" "$launch_cmd")
    tmux_sendAndSubmit(pane_id, launch_cmd)

    # Step 3: poll for ready_marker (bash: while [ "$elapsed" -lt "$timeout" ])
    elapsed = 0
    while elapsed < timeout:
        # Bash: tmux capture-pane -t "$pane_id" -p -S -2000 | tr -d '\033'
        capture = tmux_capturePane(pane_id, scrollback_lines=2000)
        capture = capture.replace("\033", "")
        if ready_marker in capture:
            print(f"[orch] {stage}/{agent} ready after {elapsed}s (pane {pane_id})")
            return True
        time_sleep(1)
        elapsed += 1

    # Step 4: timeout path (bash: echo TIMEOUT >&2; write_failed ...)
    print(
        f"[orch] TIMEOUT: {stage}/{agent} not ready within {timeout}s",
        file=sys.stderr,
    )
    debate_writeFailed(stage, f"launch_agent timeout for {agent} after {timeout}s")
    return False


# Pattern matching the lock-file body written by the bash debate daemon:
#   debate:%NNN
_LOCK_PANE_RE = re.compile(r"^debate:(%\d+)$", re.MULTILINE)


def debate_liveSession(debate_dir: str) -> str:
    """Return the tmux session name currently hosting the debate's panes.

    Recovers the session by reading still-live lock-file pane IDs and querying
    tmux. Self-heals across session renames; no separate session-name artifact
    to maintain. Returns empty string when no live session is found.

    Args:
        debate_dir: Path to the debate directory (e.g. Debates/<ts>_<slug>/).

    Returns:
        Session name string (e.g. "debate-1") or "" on failure.
    """
    # Glob for hidden lock files: .*.lock
    pattern = str(Path(debate_dir) / ".*.lock")
    lock_files = sorted(glob.glob(pattern))

    for lock_path in lock_files:
        # Read lock content; skip if file disappeared (TOCTOU)
        try:
            content = Path(lock_path).read_text()
        except OSError:
            continue

        # Extract pane_id from line matching "debate:%NNN"
        match = _LOCK_PANE_RE.search(content)
        if not match:
            continue
        pane_id = match.group(1)

        # Ask tmux for the session name owning this pane
        try:
            proc = subprocess.run(
                ["tmux", "display-message", "-p", "-t", pane_id, "#{session_name}"],
                capture_output=True,
                text=True,
            )
        except OSError:
            continue

        if proc.returncode != 0:
            continue

        session = proc.stdout.strip()
        if session:
            return session

    return ""


# YELLOW intent: read the models JSON, list candidate models for `agent`,
# return the first model whose name does not appear in the agent's tried
# list (comma-separated string mirroring the bash _stash format). If none
# remain, or the file/agent is missing, return None.

def debate_nextModel(
    agent: str,
    tried_models: dict[str, str],
    models_json_path: str,
) -> str | None:
    """Return the next untried model name for `agent`, or None if exhausted.

    Args:
        agent: agent key (e.g. "gemini", "codex", "claude").
        tried_models: dict mapping agent name -> comma-separated tried list
            (e.g. {"gemini": "gem-pro,gem-flash"}). Mirrors the bash
            TRIED_MODELS stash that this migration absorbs.
        models_json_path: path to assets/models.json (agent -> [models]).

    Returns:
        First model in the JSON list for `agent` not present in
        `tried_models[agent]`, or None when no untried model exists,
        the file is missing/unreadable, or the agent has no entry.
    """
    # GREEN: load JSON tolerantly; bash used `hide_errors jq` which yields
    # empty stdin on failure -> the while-read loop produced rc=1.
    try:
        with open(models_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    candidates = data.get(agent) or []
    # bash matched ",$tried," against ",$m," — i.e. exact whole-token match
    # within a comma-delimited string. Splitting and using a set replicates
    # that with O(1) membership and tolerates leading/trailing commas.
    tried_raw = tried_models.get(agent, "") or ""
    tried_set = {t for t in tried_raw.split(",") if t}

    for m in candidates:
        if not m:
            continue
        if m in tried_set:
            continue
        return m
    return None


# Allow importing the production module's helpers from the parent scripts dir.
_HERE = os.path.dirname(os.path.abspath(__file__))


_SCRIPTS = os.path.dirname(_HERE)


# Per-agent capacity / quota error markers, mirroring bash agent_error_markers.
# Order is preserved (first match wins) to match bash while-read semantics.
_AGENT_ERROR_MARKERS: dict[str, tuple[str, ...]] = {
    "codex": ("Selected model is at capacity", "model is overloaded"),
    "gemini": ("RESOURCE_EXHAUSTED", "Quota exceeded", "You exceeded your current quota"),
    "claude": ("API Error: 529", "overloaded_error"),
}


# Probes pane scrollback for an agent-specific capacity / overload marker.
# Returns the matched marker string (truthy) on hit, or "" (falsy) when no
# marker matches or the agent is unknown. Strips ANSI ESC bytes before
# matching to mirror `tr -d '\033'` in the bash original.
def debate_paneHasCapacityError(pane_id: str, agent: str) -> str:
    markers = _AGENT_ERROR_MARKERS.get(agent, ())
    if not markers:
        return ""
    capture = tmux_capturePane(pane_id, scrollback_lines=200)
    # Bash strips raw ESC (\033) bytes before grep -F.
    capture = capture.replace("\033", "")
    for marker in markers:
        if not marker:
            continue
        if marker in capture:
            return marker
    return ""


def debate_probeCodex() -> str:
    """Probe codex CLI availability for the debate engine.

    Returns:
        - "" if codex is unusable (missing binary OR missing credentials).
        - The configured model name from models.json if available.
        - The literal "present" sentinel if codex is available but no model
          is configured for it in models.json.

    Behavior parity with bash `_probe_codex`:
        * `command -v codex`           -> shutil.which("codex")
        * `[[ -f $HOME/.codex/auth.json ]]` -> os.path.isfile(...)
        * `[[ -n $OPENAI_API_KEY ]]`   -> truthy env-var check
        * `_default_model codex`       -> _default_model("codex")
        * `printf '%s\\n' "${m:-present}"` -> return m or "present"
    """
    # Gate 1: binary must be on PATH.
    if shutil.which("codex") is None:
        return ""

    # Gate 2: at least one credential source must be present.
    home = os.environ.get("HOME", "")
    auth_path = os.path.join(home, ".codex", "auth.json")
    has_auth_file = bool(home) and os.path.isfile(auth_path)
    has_api_key = bool(os.environ.get("OPENAI_API_KEY", ""))
    if not (has_auth_file or has_api_key):
        return ""

    # Gate 3: resolve model name; fall back to "present" sentinel if empty.
    model: Optional[str] = debate_defaultModel("codex")
    return model if model else "present"


# ---------------------------------------------------------------------------
# Private helpers (thin wrappers so tests can mock at module boundary)
# ---------------------------------------------------------------------------

def _kill_pane(pane_id: str) -> None:
    """Kill a tmux pane, silencing errors (mirrors bash `hide_errors tmux_kill_pane`)."""
    subprocess.run(
        ["tmux", "kill-pane", "-t", pane_id],
        capture_output=True,
        check=False,
    )


def _launch_agent(
    *,
    pane_id: str,
    stage: str,
    agent: str,
    launch_cmd: str,
    debate_dir: str,
) -> bool:
    """Thin shim; real implementation delegates to the monolith launch_agent.

    Returns True if the agent reached its ready marker within the timeout.
    In production this is replaced by the real launch_agent; here we import
    it from the monolith if available.
    """
    # Attempt to call the real function if available on sys.modules.
    try:
        import jot_plugin_orchestrator as _mono  # type: ignore[import]
        return bool(
            _mono.launch_agent(  # type: ignore[attr-defined]
                pane_id, stage, agent, launch_cmd,
                _mono.agent_ready_marker(agent),  # type: ignore[attr-defined]
            )
        )
    except (AttributeError, ImportError):
        return False


def _send_prompt(
    *,
    pane_id: str,
    stage: str,
    agent: str,
    debate_dir: str,
) -> bool:
    """Thin shim; delegates to monolith send_prompt if available."""
    instructions = f"{debate_dir}/{stage}_instructions_{agent}.txt"
    try:
        import jot_plugin_orchestrator as _mono  # type: ignore[import]
        return bool(
            _mono.send_prompt(pane_id, stage, agent, instructions)  # type: ignore[attr-defined]
        )
    except (AttributeError, ImportError):
        return False


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def debate_retryPaneWithNextModel(
    *,
    pane_index: int,
    agent: str,
    stage: str,
    current_pane_id: str,
    current_model: dict[str, str],
    tried_models: dict[str, str],
    window_target: str,
    cwd: str,
    repo_root: str,
    home: str,
    settings_file: str,
    debate_dir: str,
    models_json_path: str,
) -> str | None:
    """Rotate a capacity-exhausted agent pane to the next available model.

    Mirrors bash retry_pane_with_next_model (L2896-2919).

    Steps:
    1. Ask debate_nextModel for the next untried model for `agent`.
       If none remain, log and return None (bash return 1).
    2. Mutate `current_model` and `tried_models` dicts in-place.
    3. Kill the stale pane; open a fresh empty pane via debate_newEmptyPane.
    4. Launch the agent in the new pane; send it the stage instructions.
    5. Return the new pane id on success; None on any failure.

    Args:
        pane_index: position of this agent in the PANES array (informational).
        agent: "gemini" | "codex" | "claude".
        stage: "r1" | "r2" | "synthesis".
        current_pane_id: tmux pane id being replaced (e.g. "%10").
        current_model: mutable dict agent->current model string (mutated in-place).
        tried_models: mutable dict agent->comma-separated tried model string (mutated).
        window_target: tmux window target for retiling (e.g. "debate:0").
        cwd: working directory for the new pane.
        repo_root: repository root path.
        home: $HOME used for claude --add-dir dedup.
        settings_file: path to claude settings JSON.
        debate_dir: absolute path to the debate working directory.
        models_json_path: path to assets/models.json.

    Returns:
        New pane id string on success; None if no models left or launch failed.
    """
    # YELLOW: ask for next untried model; bail early if list exhausted.
    next_model = debate_nextModel(
        agent=agent,
        tried_models=tried_models,
        models_json_path=models_json_path,
    )
    if next_model is None:
        print(
            f"[orch] {stage}/{agent}: no remaining models; giving up",
            file=sys.stderr,
        )
        return None

    print(f"[orch] {stage}/{agent}: capacity hit -- rotating to model '{next_model}'")

    # YELLOW: update stash dicts in-place (replaces bash _stash calls).
    current_model[agent] = next_model
    existing_tried = tried_models.get(agent, "")
    tried_models[agent] = f"{existing_tried},{next_model}" if existing_tried else next_model

    # YELLOW: kill stale pane; open fresh replacement.
    _kill_pane(current_pane_id)
    new_pane = debate_newEmptyPane(window_target=window_target, cwd=cwd)
    if new_pane is None:
        print(
            f"[orch] {stage}/{agent}: debate_newEmptyPane returned None",
            file=sys.stderr,
        )
        return None

    # YELLOW: settle time after retile (mirrors bash `sleep 1`).
    time.sleep(1)

    # YELLOW: build launch command string for the updated model.
    launch_cmd = debate_agentLaunchCmd(
        agent=agent,
        current_model=current_model,
        debate_dir=debate_dir,
        cwd=cwd,
        repo_root=repo_root,
        home=home,
        settings_file=settings_file,
    )

    # YELLOW: launch agent; propagate failure as None.
    if not _launch_agent(
        pane_id=new_pane,
        stage=stage,
        agent=agent,
        launch_cmd=launch_cmd,
        debate_dir=debate_dir,
    ):
        return None

    # YELLOW: send instructions file; propagate failure as None.
    if not _send_prompt(
        pane_id=new_pane,
        stage=stage,
        agent=agent,
        debate_dir=debate_dir,
    ):
        return None

    return new_pane


def _debate_daemon_main_default(ctx: "DebateContext") -> None:
    """Placeholder daemon entrypoint used when debate_tmuxOrchestrator caller does not inject daemon_main_fn.

    Production callers always inject; tests inject mocks. Raising here keeps
    accidental misuse loud rather than silently no-op'ing the orchestrator.
    """
    raise NotImplementedError(
        "debate_tmuxOrchestrator requires daemon_main_fn or a migrated daemon implementation"
    )


class DebateContext:
    """Holds all mutable orchestrator state, replacing bash globals."""

    __slots__ = (
        "debate_dir",
        "session",
        "window_name",
        "settings_file",
        "cwd",
        "repo_root",
        "plugin_root",
        "window_target",
        "stage_timeout",
        "agents",
    )

    def __init__(
        self,
        debate_dir: str,
        session: str,
        window_name: str,
        settings_file: str,
        cwd: str,
        repo_root: str,
        plugin_root: str,
        debate_agents: str,
    ) -> None:
        self.debate_dir = debate_dir
        self.session = session
        self.window_name = window_name
        self.settings_file = settings_file
        self.cwd = cwd
        self.repo_root = repo_root
        self.plugin_root = plugin_root
        # Derived fields — set unconditionally, matching bash behaviour.
        self.window_target: str = f"{session}:{window_name}"
        self.stage_timeout: int = 15 * 60
        self.agents: list[str] = debate_agents.split()


def debate_tmuxOrchestrator(
    debate_dir: str,
    session: str,
    window_name: str,
    settings_file: str,
    cwd: str,
    repo_root: str,
    plugin_root: str,
    *,
    debate_agents: str = "",
    cleanup_fn: object = None,
    daemon_main_fn: object = None,
) -> int:
    """Run the debate tmux orchestrator daemon.

    Mirrors debate_tmux_orchestrator() from jot-plugin-orchestrator.sh (lines 3150-3165).

    Args:
        debate_dir: Path to the debate working directory.
        session: tmux session name.
        window_name: tmux window name within *session*.
        settings_file: Path to the debate settings JSON file.
        cwd: Working directory for agent sub-processes.
        repo_root: Absolute path to the repository root.
        plugin_root: Absolute path to the plugin root.
        debate_agents: Space-separated list of agent names (replaces $DEBATE_AGENTS env var).
            Falls back to os.environ["DEBATE_AGENTS"] when empty.
        cleanup_fn: Injectable cleanup callable (defaults to monolith/workspace cleanup).
        daemon_main_fn: Injectable daemon_main callable (defaults to monolith/workspace daemon_main).

    Returns:
        0 on success. daemon_main is expected to raise or sys.exit on fatal errors.

    Raises:
        ValueError: If session or debate_agents is empty (mirrors bash `:?` guards).
    """
    # --- Resolve injected callees (test seam) ---
    _cleanup_fn = cleanup_fn if cleanup_fn is not None else debate_cleanup
    _daemon_fn = daemon_main_fn if daemon_main_fn is not None else _debate_daemon_main_default

    # --- Guard: SESSION required (mirrors `: "${SESSION:?SESSION required}"`) ---
    if not session:
        raise ValueError("SESSION required")

    # --- Resolve DEBATE_AGENTS (env fallback mirrors bash caller convention) ---
    resolved_agents = debate_agents or os.environ.get("DEBATE_AGENTS", "")
    if not resolved_agents:
        raise ValueError("DEBATE_AGENTS env var required")

    # --- Build context (replaces bash globals) ---
    ctx = DebateContext(
        debate_dir=debate_dir,
        session=session,
        window_name=window_name,
        settings_file=settings_file,
        cwd=cwd,
        repo_root=repo_root,
        plugin_root=plugin_root,
        debate_agents=resolved_agents,
    )

    # --- Register cleanup and run daemon (mirrors `trap cleanup EXIT; daemon_main`) ---
    try:
        _daemon_fn(ctx)
    finally:
        _cleanup_fn()

    return 0


def debate_waitForOutputs(
    *,
    prefix: str,
    timeout: int,
    panes: Mapping[int, str],
    agents: Sequence[str],
    debate_dir: Path,
    pane_capacity_error: Callable[[str, str], bool],
    retry_pane: Callable[..., object],
    sleep_fn: Callable[[float], None],
    poll_interval: int = 5,
) -> tuple[bool, list[str], str | None]:
    # YELLOW intent: loop until timeout. Each cycle, scan agents; if their output
    # file exists and is non-empty, mark complete and remove their lock. Otherwise
    # check the pane for a capacity error and trigger a retry. When all agents
    # complete, return success. On timeout, return failure with the agents that
    # did complete and a timeout reason string.
    debate_dir = Path(debate_dir)
    completed: list[str] = []
    elapsed = 0

    while elapsed < timeout:
        for i, agent in enumerate(agents):
            out = debate_dir / f"{prefix}_{agent}.md"
            # Bash `[ -s "$out" ]` -> exists and non-zero size
            if out.exists() and out.stat().st_size > 0:
                lock = debate_dir / f".{prefix}_{agent}.lock"
                if lock.exists():
                    try:
                        lock.unlink()
                    except OSError:
                        pass
                if agent not in completed:
                    completed.append(agent)
                continue
            # No output yet: probe pane for capacity error, retry if so
            pane_id = panes.get(i)
            if pane_id is None:
                continue
            try:
                if pane_capacity_error(pane_id, agent):
                    try:
                        retry_pane(panes, i, agent, prefix)
                    except Exception:
                        # Bash `|| true` — swallow retry failures, keep polling
                        pass
            except Exception:
                pass

        if len(completed) == len(agents):
            return True, completed, None

        sleep_fn(poll_interval)
        elapsed += poll_interval

    reason = f"wait_for_outputs timeout after {timeout}s"
    return False, completed, reason


def debate_writeFailed(
    debate_dir: Path,
    stage: str,
    reason: str,
    agents: Iterable[str],
    *,
    pane_capture: Callable[[str], str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> Path:
    """Write a `FAILED.txt` marker into ``debate_dir`` describing a debate failure.

    Bash analogue: ``write_failed`` (jot-plugin-orchestrator.sh ~L2817-2841).

    Behavior (RELAXED_COVERAGE - reconstructed from bash intent):
      * Header lines: '# debate FAILED', blank, 'stage:', 'reason:', 'timestamp:' (ISO-8601), blank.
      * Section '## missing agents' followed by one '### <agent>' subsection per agent
        whose ``<stage>_<agent>.md`` output file is missing or empty in ``debate_dir``.
      * If a lock file ``.<stage>_<agent>.lock`` exists with line ``debate:<pane_id>``,
        ``pane_capture(pane_id)`` is invoked and its result is fenced in triple backticks.
        Else writes ``(no pane captured -- lock file missing or malformed)``.
      * Atomic publish: writes to a temp file in ``debate_dir`` then renames over
        ``FAILED.txt``, so a partial file is never observable. Overwrites prior FAILED.txt.
      * Returns the final FAILED.txt path.
    """
    debate_dir = Path(debate_dir)
    if now is None:
        now = lambda: datetime.now(timezone.utc).astimezone()
    timestamp = now().replace(microsecond=0).isoformat()

    lines: list[str] = [
        "# debate FAILED",
        "",
        f"stage: {stage}",
        f"reason: {reason}",
        f"timestamp: {timestamp}",
        "",
        "## missing agents",
    ]

    for agent in agents:
        out_path = debate_dir / f"{stage}_{agent}.md"
        # Skip agents that produced non-empty output (matches bash `[ -s ... ] && continue`).
        if out_path.exists() and out_path.stat().st_size > 0:
            continue
        lines.append("")
        lines.append(f"### {agent}")
        lock_path = debate_dir / f".{stage}_{agent}.lock"
        pane_id = ""
        if lock_path.exists():
            for raw in lock_path.read_text().splitlines():
                if raw.startswith("debate:"):
                    pane_id = raw[len("debate:"):].strip()
                    break
        if pane_id:
            lines.append("```")
            capture_text = ""
            if pane_capture is not None:
                try:
                    capture_text = pane_capture(pane_id) or ""
                except Exception:
                    capture_text = ""
            if not capture_text:
                capture_text = "(pane capture unavailable)"
            # Strip trailing newline so the closing fence sits on its own line.
            lines.append(capture_text.rstrip("\n"))
            lines.append("```")
        else:
            lines.append("(no pane captured -- lock file missing or malformed)")

    body = "\n".join(lines) + "\n"

    debate_dir.mkdir(parents=True, exist_ok=True)
    # Atomic write: tempfile in same dir, then rename onto FAILED.txt.
    import tempfile
    fd, tmp_name = tempfile.mkstemp(prefix=".FAILED.txt.", dir=str(debate_dir))
    tmp_path = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        final = debate_dir / "FAILED.txt"
        tmp_path.replace(final)
        return final
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


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

    # Resolve cli.py: bash uses `cd "$(dirname "$0")/../../.." && pwd`. In the
    # Python migration the equivalent is the repo root above scripts/. We
    # locate it relative to this module so the function works whether installed
    # in the plugin tree or run from the migration workspace.
    repo_root = Path(__file__).resolve().parents[2]
    cli_path = repo_root / "common" / "scripts" / "plate" / "cli.py"

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


# Default tmux send used when the caller does not inject one.
def _default_tmux_send(pane: str, keys: str) -> None:
    # Mirrors `tmux send-keys -t "$PANE" <keys> 2>/dev/null || true` --
    # callers swallow errors at the dispatch layer, but we also redirect
    # stderr here so a missing pane doesn't pollute the watcher's log.
    subprocess.run(
        ["tmux", "send-keys", "-t", pane, keys],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


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


# CLI entrypoint mirrors the bash script's positional-arg contract.
def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: plate_summaryWatch <pane_target> <output_file>", file=sys.stderr)
        return 2
    return plate_summaryWatch(pane=argv[0], output_file=argv[1])


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))


# YELLOW intent: poll filesystem until target path is a non-empty file or
# the cumulative wall-clock elapsed time meets/exceeds `timeout`. Use the
# module-level `time.sleep` and `time.monotonic` so tests can monkeypatch.
# Return True on success, False on timeout. Empty (zero-byte) files do not
# count as ready -- this preserves bash `[ -s ]` semantics.
def shell_waitForFile(path: str, timeout: float, poll_interval: float = 5.0) -> bool:
    """Block until `path` is a non-empty file or `timeout` seconds pass.

    Args:
        path: filesystem path to poll.
        timeout: maximum seconds to wait (inclusive upper bound).
        poll_interval: seconds between polls (bash default: 5).

    Returns:
        True if the file became non-empty before timeout, else False.
    """
    target = Path(path)
    deadline = time.monotonic() + float(timeout)
    while True:
        try:
            if target.is_file() and target.stat().st_size > 0:
                return True
        except OSError:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_interval)


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
        if _has_open_status(md_path):
            open_paths.append(str(md_path.resolve()))
    return open_paths


# Mirrors `head -10 "$f" | grep -q '^status: open'`: a line within the first
# 10 lines whose start is the literal token "status: open". grep's anchor (^)
# pins the match to column 0; the trailing portion of the line is unconstrained.
def _has_open_status(path: Path) -> bool:
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


_POLL_ATTEMPTS = 5


_POLL_SLEEP = 0.2


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


# Max retries polling the tmux_target sidecar file.
_SIDECAR_RETRIES = 5


_SIDECAR_SLEEP = 0.2


# Audit log max lines before rotation.
_AUDIT_MAX_LINES = 1000


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


def debate_cleanup(settings_file: str | Path) -> None:
    """Remove the debate temp-settings directory when it lives under /tmp.

    Args:
        settings_file: Path to the settings JSON file (e.g.
            /tmp/debate.XYZ/settings.json).  Only the *parent* directory is
            examined; the file itself need not exist.

    Side effects:
        If settings_file.parent matches the pattern /tmp/debate.* the entire
        parent directory is deleted with shutil.rmtree.  All other locations
        are left untouched.
    """
    settings_path = Path(settings_file)
    settings_dir = settings_path.parent

    # Mirror bash case pattern: /tmp/debate.*
    # Condition: parent is /tmp AND directory name starts with "debate."
    if settings_dir.parent == Path("/tmp") and settings_dir.name.startswith("debate."):
        if settings_dir.exists():
            shutil.rmtree(settings_dir)


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


_LOCK_LINE_RE = re.compile(r"^debate:(%[0-9]+)$", re.MULTILINE)


def _live_pane_ids() -> set[str]:
    """Return the set of currently-live tmux pane ids ('%N').

    Failures (no tmux, no server, non-zero rc) are swallowed and yield
    an empty set, matching bash `hide_errors tmux list-panes ...`.
    """
    # Test action: query tmux for every pane across every session.
    try:
        proc = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#{pane_id}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return set()
    if proc.returncode != 0:
        return set()
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def debate_anyLiveLock(debate_dir: str | os.PathLike[str]) -> bool:
    """True iff `<debate_dir>/.*.lock` references a still-live tmux pane.

    Behavior port of bash `any_live_lock`:
      * Iterate hidden `*.lock` files (glob `.*.lock`) in `debate_dir`.
      * Skip non-files (matches `[ -f "$lock" ] || continue`).
      * Extract the first line matching `^debate:(%<digits>)$`.
      * If that pane id appears in `tmux list-panes -a`, return True.
      * Return False if no lock yields a live pane.
    """
    d = Path(debate_dir)
    if not d.is_dir():
        return False

    # Collect candidate lock files: hidden, ending in `.lock`. Bash glob
    # `.*.lock` matches any file beginning with `.` and ending in `.lock`.
    locks = sorted(p for p in d.glob(".*.lock") if p.is_file())
    if not locks:
        return False

    live = _live_pane_ids()
    if not live:
        return False

    for lock in locks:
        try:
            text = lock.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = _LOCK_LINE_RE.search(text)
        if not m:
            continue
        pane_id = m.group(1)
        if pane_id in live:
            return True
    return False


# Sends a "read <instructions> and perform them" prompt to the agent's pane via
# tmux_sendAndSubmit, then polls the pane (capture-pane with 2000 lines of
# scrollback, ANSI-stripped, fixed-string match against basename(instructions))
# for up to 30s in 1s ticks. Returns 0 when the marker appears, 1 on timeout.
# On timeout, logs "[orch] TIMEOUT: <stage>/<agent> did not echo prompt" to
# stderr and calls debate_writeFailed(stage, "send_prompt timeout for <agent>
# after 30s") (parity with bash write_failed). Marker derivation, scrollback
# size, poll cadence, and timeout are bash-faithful.
def debate_sendPromptToAgent(
    pane_id: str,
    stage: str,
    agent: str,
    instructions: str,
) -> int:
    rc = tmux_sendAndSubmit(pane_id, f"read {instructions} and perform them")
    # Bash sends the prompt unconditionally and ignores send_and_submit rc;
    # we preserve that behavior (no early return on rc != 0).
    _ = rc
    marker = Path(instructions).name
    elapsed = 0
    while elapsed < 30:
        captured = tmux_capturePane(pane_id, 2000)
        # Bash strips ANSI escapes via `tr -d '\033'` before fixed-string grep.
        stripped = (captured or "").replace("\x1b", "")
        if marker in stripped:
            print(f"[orch] {stage}/{agent} prompt received after {elapsed}s")
            return 0
        time.sleep(1)
        elapsed += 1
    print(
        f"[orch] TIMEOUT: {stage}/{agent} did not echo prompt",
        file=sys.stderr,
    )
    debate_writeFailed(stage, f"send_prompt timeout for {agent} after 30s")
    return 1


# Allow imports from the production module living one dir up.
_THIS_DIR = Path(__file__).resolve().parent


_SCRIPTS_DIR = _THIS_DIR.parent


def _isoTimestampLocal() -> str:
    # Match bash `date -Iseconds` (local-tz, seconds precision).
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _readSidecar(target_file: Path, attempts: int = 5, sleep_s: float = 0.2) -> str:
    # Mirror bash retry loop: 5 attempts, 0.2s sleep between non-final attempts.
    for i in range(attempts):
        try:
            if target_file.is_file() and target_file.stat().st_size > 0:
                first = target_file.read_text().split("\n", 1)[0]
                if first:
                    return first
        except OSError:
            pass
        if i < attempts - 1:
            time.sleep(sleep_s)
    return ""


def _appendAudit(audit_path: Path, line: str) -> None:
    with audit_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _backgroundKill(pane_target: str, retile_target: str = "jot:jots") -> None:
    # Bash forks a `( sleep 0.5; kill-pane; retile ) &` subshell so the hook
    # can return BEFORE tmux signals claude. In Python we expose this as a
    # function so tests can monkeypatch it; default impl does the work
    # synchronously (no sleep, no fork — the hook semantics are the same
    # because we are not the claude process being killed in test).
    tmux_killPane(pane_target)
    tmux_retile(retile_target)


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
    tmux_target = _readSidecar(target_file)
    if not tmux_target:
        print(
            "[jot-stop] tmux_target sidecar empty after retries",
            file=sys.stderr,
        )
        return 0

    # State dir must exist + standard files must be present.
    jot_initState(state_dir)
    audit_path = Path(state_dir) / "audit.log"

    ts = _isoTimestampLocal()
    input_path = Path(input_file)
    if input_path.is_file():
        try:
            with input_path.open("r", encoding="utf-8") as fh:
                first_line = fh.readline().rstrip("\n")
        except OSError:
            first_line = ""
        if first_line.startswith("PROCESSED:"):
            _appendAudit(audit_path, f"{ts} SUCCESS {input_file}")
        else:
            _appendAudit(
                audit_path, f"{ts} FAIL {input_file} (no PROCESSED marker)"
            )
    else:
        _appendAudit(audit_path, f"{ts} FAIL {input_file} (input.txt missing)")

    jot_rotateAudit(audit_path, 1000)

    bg = background_kill if background_kill is not None else _backgroundKill
    bg(tmux_target, "jot:jots")
    return 0


def _hide_errors(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception:
        return "(unavailable)"


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
    
    branch = _hide_errors(getGitBranchNameOrFail, Path(cwd))
    commits_list = _hide_errors(getGitRecentCommitHashes, Path(cwd))
    commits = "\n".join(commits_list) if isinstance(commits_list, list) else commits_list
    uncommitted_list = _hide_errors(getGitUncommittedFilenames, Path(cwd))
    uncommitted = "\n".join(uncommitted_list) if isinstance(uncommitted_list, list) else uncommitted_list
    
    open_todos_list = _hide_errors(todo_scanOpen, repo_root)
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
    
    import shutil
    shutil.copy2(plugin_root / "scripts" / "jot-plugin-orchestrator.sh", tmpdir_inv / "jot-plugin-orchestrator.sh")
    
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
        "SessionStart": [{"hooks": [{"type": "command", "command": f"bash {tmpdir_inv}/jot-plugin-orchestrator.sh todo-session-start '{input_file}' '{tmpdir_inv}'"}]}],
        "Stop":         [{"hooks": [{"type": "command", "command": f"bash {tmpdir_inv}/jot-plugin-orchestrator.sh todo-stop '{input_file}' '{tmpdir_inv}' '{state_dir}'"}]}],
        "SessionEnd":   [{"hooks": [{"type": "command", "command": f"bash {tmpdir_inv}/jot-plugin-orchestrator.sh todo-session-end '{tmpdir_inv}'"}]}]
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


def debate_probeGemini() -> str:
    """Probe whether the gemini agent is usable; return model name or "".

    Returns:
        - "" when gemini is unavailable (binary missing OR no credentials).
        - The configured model name (e.g., "gemini-2.5-pro") when ready.
        - "present" sentinel when binary + creds exist but no model is
          configured in models.json — caller still treats agent as usable.

    Behavior parity with bash `_probe_gemini`:
        Gate 1: `command -v gemini` must succeed.
        Gate 2: ~/.gemini/oauth_creds.json OR GEMINI_API_KEY OR GOOGLE_API_KEY.
        Gate 3: model = debate_defaultModel("gemini"); return model or "present".
    """
    # Gate 1: binary on PATH. shutil.which mirrors `command -v`.
    if shutil.which("gemini") is None:
        return ""

    # Gate 2: at least one credential source present. Order matches bash:
    # oauth file first (most common), then env vars.
    oauth_path = os.path.join(os.path.expanduser("~"), ".gemini", "oauth_creds.json")
    has_oauth = os.path.isfile(oauth_path)
    has_gemini_key = bool(os.environ.get("GEMINI_API_KEY", ""))
    has_google_key = bool(os.environ.get("GOOGLE_API_KEY", ""))
    if not (has_oauth or has_gemini_key or has_google_key):
        return ""

    # Gate 3: resolve model name; fall back to "present" sentinel so the
    # caller's non-empty check still flags gemini as available.
    model = debate_defaultModel("gemini")
    return model if model else "present"


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


def debate_launchAgentsParallel(
    stage: str,
    panes: list[str],
    agents: list[str],
    debate_dir: str | Path,
) -> int:
    """Launch multiple debate agents in parallel for a given stage.

    Mirrors bash `launch_agents_parallel` (jot-plugin-orchestrator.sh ~L2962-2997).

    For each agent/pane pair:
    - If the output file (<debate_dir>/<stage>_<agent>.md) already exists and is
      non-empty, the agent is considered complete; the pane is killed and skipped.
    - If a lock file (<debate_dir>/.<stage>_<agent>.lock) exists, a live pane is
      already running; the new pane is killed and skipped.
    - Otherwise, launch the agent and send its prompt concurrently via
      ThreadPoolExecutor (replaces bash `&` + `wait`).

    Args:
        stage:      Debate stage label (e.g. "r1", "r2").
        panes:      Ordered list of tmux pane IDs; panes[i] pairs with agents[i].
        agents:     Ordered list of agent names (e.g. ["claude", "gemini"]).
        debate_dir: Directory holding stage output and instruction files.

    Returns:
        0 if all launched workers succeeded, 1 if any worker exited non-zero.

    RELAXED_COVERAGE:
        Bash signature was `launch_agents_parallel <stage> <panes_var>` where
        panes_var was an indirect array reference to a global and AGENTS/DEBATE_DIR
        were implicit globals. Python makes all four params explicit.
    """
    debate_dir = Path(debate_dir)
    t0 = time.monotonic()
    fail = 0

    # Map future -> agent name so we can log failures by name.
    future_to_agent: dict[Future[int], str] = {}

    with ThreadPoolExecutor() as pool:
        for pane_id, agent in zip(panes, agents):
            output_file = debate_dir / f"{stage}_{agent}.md"
            lock_file = debate_dir / f".{stage}_{agent}.lock"

            # Skip: output already exists (non-empty) -- agent previously completed.
            if output_file.exists() and output_file.stat().st_size > 0:
                print(f"[orch] {stage}/{agent} already complete, skipping launch", flush=True)
                tmux_killPane(pane_id)
                continue

            # Skip: lock held by a live pane -- wait_for_outputs will observe it.
            if lock_file.exists():
                print(
                    f"[orch] {stage}/{agent} lock held by live pane, "
                    "skipping launch (wait_for_outputs will observe)",
                    flush=True,
                )
                tmux_killPane(pane_id)
                continue

            # Launch agent and send prompt concurrently.
            def _worker(
                _pane_id: str = pane_id,
                _agent: str = agent,
            ) -> int:
                launch_cmd = debate_agentLaunchCmd(_agent)
                ready_marker = debate_agentReadyMarker(_agent)
                ok = debate_launchAgent(_pane_id, stage, _agent, launch_cmd, ready_marker)
                if not ok:
                    return 1
                instructions = str(debate_dir / f"{stage}_instructions_{_agent}.txt")
                return debate_sendPromptToAgent(_pane_id, stage, _agent, instructions)

            future_to_agent[pool.submit(_worker)] = agent

        # Collect results as workers complete.
        for future in as_completed(future_to_agent):
            agent_name = future_to_agent[future]
            try:
                rc = future.result()
            except Exception as exc:
                print(f"[orch] {stage}/{agent_name} worker raised: {exc}", file=sys.stderr, flush=True)
                rc = 1
            if rc != 0:
                print(f"[orch] {stage}/{agent_name} worker exited non-zero", file=sys.stderr, flush=True)
                fail = 1

    wall = time.monotonic() - t0
    n_workers = len(future_to_agent)
    print(
        f"[orch] launch_agents_parallel {stage}: {n_workers} workers, {wall:.1f}s wall",
        file=sys.stderr,
        flush=True,
    )
    return fail


def debate_newEmptyPane(window_target: str, cwd: str) -> str | None:
    """Create a new empty pane in window_target rooted at cwd.

    Mirrors bash new_empty_pane():
      1. Re-tiles the window (output/rc suppressed, matching hide_output).
      2. Splits a new pane with -c <cwd> -P -F '#{pane_id}' and no command,
         returning the new pane id (e.g. '%42') or None on failure.

    Args:
        window_target: tmux target string for the window (e.g. 'session:window').
        cwd: Working directory for the new pane (-c flag to split-window).

    Returns:
        The new pane id string on success, or None on tmux failure or empty output.
    """
    # Re-tile; rc ignored (bash used hide_output which discards rc).
    tmux_retile(window_target)

    # Split a new pane with no command (-P -F '#{pane_id}' to capture id).
    # Passing cmd="" appends an empty string to argv; tmux split-window treats
    # a trailing empty token as "no command" on macOS tmux >= 3.x.  Use the
    # inline subprocess call (same pattern as tmux_splitWorkerPane in
    # jot_plugin_orchestrator.py) for full control and to avoid passing "".
    argv = [
        "tmux", "split-window",
        "-t", window_target,
        "-c", cwd,
        "-P", "-F", "#{pane_id}",
    ]
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(0).f_code.co_name
        cmd_str = " ".join(argv)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
        return None
    pane_id = (result.stdout or "").strip()
    if not pane_id:
        return None
    return pane_id


def debateAbort_main() -> int:
    """Entry point for the /debate-abort hook. Returns process exit code.

    Mirrors bash `debate_abort_main`. Returns 0 on every code path
    (matches bash `exit 0` after emit_block).
    """
    # Test action: load context (env + stdin JSON + git toplevel).
    ctx = debate_initHookContext()

    # Require jq and tmux on PATH; checkRequirements emits + exits on failure.
    hookjson_checkRequirements("debate-abort", "jq", "tmux")

    transcript_path = ctx.get("TRANSCRIPT_PATH", "") or ""
    repo_root = ctx.get("REPO_ROOT", "") or ""

    # Empty transcript_path - hook payload didn't carry one. Bail politely.
    if not transcript_path:
        hookjson_emitBlock("/debate-abort: no transcript_path in hook payload")
        return 0

    # Empty repo_root - cwd isn't inside a git repo; nowhere to look.
    if not repo_root:
        hookjson_emitBlock("/debate-abort requires a git repository")
        return 0

    # Scan <repo>/Debates/*/ for dirs whose invoking_transcript matches.
    debates_root = Path(repo_root) / "Debates"
    best_ts = ""
    best: Path | None = None
    if debates_root.is_dir():
        for entry in debates_root.iterdir():
            if not entry.is_dir():
                continue
            marker = entry / "invoking_transcript.txt"
            if not marker.is_file():
                continue
            try:
                stored = marker.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # Bash uses `[ "$(cat ...)" = "$TRANSCRIPT_PATH" ]` which does
            # not strip; preserve exact equality.
            if stored != transcript_path:
                continue
            ts = entry.name
            # Bash `[[ "$ts" > "$best_ts" ]]` is locale string comparison;
            # Python str > str is lexicographic by Unicode code point. For
            # ASCII timestamp basenames this matches expected behavior.
            if ts > best_ts:
                best_ts = ts
                best = entry

    if best is None:
        hookjson_emitBlock("/debate-abort: no debate found in this conversation")
        return 0

    # If any lock file references a live tmux pane, refuse to delete.
    if debate_anyLiveLock(str(best)):
        live = debate_liveSession(str(best)) or "<unknown>"
        hookjson_emitBlock(
            f"/debate-abort: debate is running. to force-kill: "
            f"tmux kill-session -t {live}"
        )
        return 0

    # Happy path: tear down the debate dir tree and report.
    shutil.rmtree(best, ignore_errors=False)
    hookjson_emitBlock(f"/debate-abort: deleted {best}")
    return 0


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


def ensureGitignoreEntry(repo_root: str, pattern: str) -> None:
    """Append `pattern` to <repo_root>/.gitignore if not already present."""
    gitignore = Path(repo_root) / ".gitignore"
    try:
        existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
    except OSError:
        existing = ""
    lines = existing.splitlines()
    if pattern in lines:
        return
    try:
        with open(gitignore, "a", encoding="utf-8") as fh:
            fh.write(f"\n{pattern}\n")
    except OSError:
        pass


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


def debate_startOrResume(
    *,
    debate_dir: str | Path,
    available_agents: list[str],
    resuming: bool,
    cwd: str,
    repo_root: str,
    settings_file: str,
    log_file: str,
    plugin_root: str,
    gemini_model: str,
    codex_model: str,
) -> None:
    """Start or resume a debate orchestration session.

    Mirrors debate_start_or_resume() from the bash original:
    1. Detect composition drift when resuming.
    2. Build missing per-stage instruction files (r1 / r2 / synthesis).
    3. Build the Claude command via debate_buildClaudeCmd.
    4. Claim a tmux session (debate-N); exit 0 with an error block on failure.
    5. Apply session-scoped tmux options and name the keepalive pane.
    6. Launch the daemon detached via Popen(start_new_session=True).
    7. Spawn a terminal if needed.
    8. Emit the final /debate <verb> block.
    """
    debate_dir = Path(debate_dir)
    window_name = "main"

    # Detect composition drift (resume path only).
    composition_drifted = False
    if resuming:
        original_agents: set[str] = set()
        for f in debate_dir.glob("r1_instructions_*.txt"):
            stem = f.stem
            agent_name = stem[len("r1_instructions_"):]
            original_agents.add(agent_name)
        if original_agents != set(available_agents):
            composition_drifted = True

    # Build missing per-stage instruction files.
    agents_joined = " ".join(available_agents)

    for agent in available_agents:
        r1_path = debate_dir / f"r1_instructions_{agent}.txt"
        if not r1_path.exists():
            debate_buildClaudePrompts(
                stage="r1",
                debate_dir=str(debate_dir),
                plugin_root=plugin_root,
                debate_agents=agents_joined,
                agent_filter=agent,
            )

    for agent in available_agents:
        r2_path = debate_dir / f"r2_instructions_{agent}.txt"
        if not r2_path.exists():
            debate_buildClaudePrompts(
                stage="r2",
                debate_dir=str(debate_dir),
                plugin_root=plugin_root,
                debate_agents=agents_joined,
                agent_filter=agent,
            )

    synthesis_path = debate_dir / "synthesis_instructions.txt"
    if not synthesis_path.exists():
        debate_buildClaudePrompts(
            stage="synthesis",
            debate_dir=str(debate_dir),
            plugin_root=plugin_root,
            debate_agents=agents_joined,
            agent_filter=None,
        )

    # Build the Claude command.
    debate_buildClaudeCmd(
        debate_dir=str(debate_dir),
        plugin_root=plugin_root,
    )

    # Claim a tmux session.
    keepalive_cmd = (
        "exec sh -c 'trap \"\" INT HUP TERM; "
        "printf \"[debate keepalive]\\n\"; exec tail -f /dev/null'"
    )
    session = debate_claimSession(keepalive_cmd=keepalive_cmd)
    if not session:
        hookjson_emitBlock(
            "/debate: could not claim debate-<N> session (1000 already in use)"
        )
        sys.exit(0)

    # Apply session-scoped tmux options and name the keepalive pane.
    _tmux_set = [
        ["tmux", "set-option", "-t", session, "remain-on-exit", "off"],
        ["tmux", "set-option", "-t", session, "mouse", "on"],
        ["tmux", "set-option", "-t", session, "pane-border-status", "top"],
        ["tmux", "set-option", "-t", session, "pane-border-format", " #{pane_title} "],
    ]
    for cmd in _tmux_set:
        subprocess.run(cmd, stderr=subprocess.DEVNULL)

    pane_title = f"keepalive:{debate_dir.name}"
    subprocess.run(
        ["tmux", "select-pane", "-t", f"{session}:{window_name}", "-T", pane_title],
        stderr=subprocess.DEVNULL,
    )

    # Launch the daemon detached (replaces bash `& disown`).
    orch_log_path = debate_dir / "orchestrator.log"
    orch_log_handle = open(orch_log_path, "a")

    daemon_env_extras = {
        "GEMINI_MODEL": gemini_model,
        "CODEX_MODEL": codex_model,
        "DEBATE_AGENTS": agents_joined,
        "COMPOSITION_DRIFTED": "1" if composition_drifted else "0",
        "SESSION": session,
    }
    daemon_env = {**os.environ, **daemon_env_extras}

    daemon_cmd = [
        "bash",
        str(Path(plugin_root) / "scripts" / "jot-plugin-orchestrator.sh"),
        "debate-tmux-orchestrator",
        str(debate_dir),
        session,
        window_name,
        settings_file,
        cwd,
        repo_root,
        plugin_root,
    ]
    subprocess.Popen(
        daemon_cmd,
        stdout=orch_log_handle,
        stderr=orch_log_handle,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=daemon_env,
    )

    # Spawn a terminal if needed.
    terminal_spawnIfNeeded(
        session=session,
        log_file=log_file,
        skill="debate",
        required="yes",
    )

    # Emit the final status block.
    agents_str = ", ".join(available_agents)
    rel = f"Debates/{debate_dir.name}"
    verb = "resumed" if resuming else "spawned"
    hookjson_emitBlock(
        f"/debate {verb} ({agents_str}) -> {rel}/synthesis.md "
        f"(~10-30 min). View: tmux attach -t {session}"
    )


# Slug helpers: lowercase, replace non-alnum runs with '-', head 40, strip trailing '-'.
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _slugify(topic: str) -> str:
    """Mirror bash: tr lower | tr -cs '[:alnum:]' '-' | head -c 40 | sed 's/-$//'."""
    lowered = topic.lower()
    collapsed = _NON_ALNUM_RE.sub("-", lowered)
    return collapsed[:40].rstrip("-")


def debate_main() -> int:
    """Hook entry-point for the /debate slash command.

    Returns 0 in all paths; failures surface via emit_block side-effects.
    """
    from datetime import datetime as _dt

    ctx = debate_initHookContext()
    log_file = ctx.get("LOG_FILE", "")
    raw_input = ctx.get("INPUT", "")
    transcript_path = ctx.get("TRANSCRIPT_PATH", "")
    repo_root = ctx.get("REPO_ROOT", "")

    hookjson_checkRequirements("debate", "jq", "python3", "tmux", "claude")

    # Fast-path: ignore inputs that don't even mention "/debate.
    if '"/debate' not in raw_input:
        return 0

    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{_dt.now().isoformat()} HOOK_INPUT {raw_input}\n")
        except OSError:
            pass

    try:
        payload = json.loads(raw_input) if raw_input else {}
    except (ValueError, TypeError):
        payload = {}
    prompt = (payload.get("prompt") or "") if isinstance(payload, dict) else ""
    prompt = prompt.lstrip()

    if not (prompt == "/debate" or prompt.startswith("/debate ")):
        return 0

    topic = prompt[len("/debate"):]
    if topic.startswith(" "):
        topic = topic[1:]

    if not topic:
        hookjson_emitBlock("debate: no topic provided. Usage: /debate <topic>")
        return 0
    if not repo_root:
        hookjson_emitBlock("debate requires a git repository.")
        return 0

    detect_result = debate_detectAvailableAgents()
    available_agents: list[str] = list(detect_result.get("available", []))
    gemini_model: str = detect_result.get("gemini_model", "")
    codex_model: str = detect_result.get("codex_model", "")

    existing = debate_findMatching(repo_root, topic)
    resuming = False
    debate_dir: Path

    if existing:
        existing_path = Path(existing)
        if (existing_path / "synthesis.md").exists():
            hookjson_emitBlock(
                f"/debate: already complete, see {existing}/synthesis.md - "
                f"or 'rm -rf {existing}' to re-run"
            )
            return 0
        if debate_anyLiveLock(existing):
            try:
                live = debate_liveSession(existing) or "<unknown>"
            except Exception:
                live = "<unknown>"
            hookjson_emitBlock(
                f"/debate: already running for this topic -> tmux attach -t {live}"
            )
            return 0
        debate_dir = existing_path
        resuming = True
    else:
        if len(available_agents) < 2:
            names = " ".join(available_agents)
            hookjson_emitBlock(
                f"/debate: needs >=2 agents, got: {names}. "
                "All configured models for missing agents failed smoke tests. "
                "Fix credentials/quota and re-run '/debate <topic>'."
            )
            return 0

        timestamp = _dt.now().strftime("%Y-%m-%dT%H-%M-%S")
        slug = _slugify(topic)
        debate_dir = Path(repo_root) / "Debates" / f"{timestamp}_{slug}"
        debate_dir.mkdir(parents=True, exist_ok=True)

        (debate_dir / "topic.md").write_text(f"{topic}\n", encoding="utf-8")
        if transcript_path:
            (debate_dir / "invoking_transcript.txt").write_text(
                f"{transcript_path}\n", encoding="utf-8"
            )

        plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
        capture_script = (
            Path(plugin_root) / "skills" / "jot" / "scripts" / "capture-conversation.py"
            if plugin_root
            else None
        )
        context_path = debate_dir / "context.md"
        if (
            transcript_path
            and Path(transcript_path).is_file()
            and capture_script is not None
            and capture_script.is_file()
        ):
            ok = False
            try:
                with context_path.open("w", encoding="utf-8") as out_fh:
                    proc = subprocess.run(
                        ["python3", str(capture_script), transcript_path],
                        stdout=out_fh,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                ok = proc.returncode == 0 and context_path.stat().st_size > 0
            except (OSError, subprocess.SubprocessError):
                ok = False
            if not ok:
                context_path.write_text("(conversation capture failed)\n", encoding="utf-8")
        else:
            context_path.write_text("(no conversation context available)\n", encoding="utf-8")

    if resuming:
        debate_checkResumeFeasibility(debate_dir, available_agents)
        failed_marker = debate_dir / "FAILED.txt"
        try:
            failed_marker.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    settings_file = os.environ.get("SETTINGS_FILE", "")
    debate_startOrResume(
        debate_dir=debate_dir,
        available_agents=available_agents,
        resuming=resuming,
        cwd=ctx.get("CWD", ""),
        repo_root=repo_root,
        settings_file=settings_file,
        log_file=log_file,
        plugin_root=os.environ.get("CLAUDE_PLUGIN_ROOT", ""),
        gemini_model=gemini_model,
        codex_model=codex_model,
    )

    return 0


def debateRetry_main() -> int:
    """Hook entry-point for the /debate-retry slash command.

    Locates the most recent debate directory in the current repo whose
    invoking_transcript.txt matches the current hook's transcript_path,
    then either reports its terminal state or resumes orchestration.
    """
    ctx = debate_initHookContext()
    transcript_path = ctx.get("TRANSCRIPT_PATH", "")
    repo_root = ctx.get("REPO_ROOT", "")
    cwd = ctx.get("CWD", "")
    log_file = ctx.get("LOG_FILE", "")

    hookjson_checkRequirements("debate-retry", "jq", "python3", "tmux", "claude")

    if not transcript_path:
        hookjson_emitBlock("/debate-retry: no transcript_path in hook payload")
        return 0
    if not repo_root:
        hookjson_emitBlock("/debate-retry requires a git repository")
        return 0

    debates_root = Path(repo_root) / "Debates"
    best: Path | None = None
    best_ts: str = ""

    if debates_root.is_dir():
        for entry in debates_root.iterdir():
            if not entry.is_dir():
                continue
            marker = entry / "invoking_transcript.txt"
            if not marker.is_file():
                continue
            try:
                content = marker.read_text(encoding="utf-8")
            except OSError:
                continue
            if content != transcript_path and content.rstrip("\n") != transcript_path:
                continue
            ts = entry.name
            if ts > best_ts:
                best_ts = ts
                best = entry

    if best is None:
        hookjson_emitBlock("/debate-retry: no debate found in this conversation")
        return 0

    if (best / "synthesis.md").exists():
        hookjson_emitBlock(
            f"/debate-retry: already complete, see {best}/synthesis.md"
        )
        return 0

    if debate_anyLiveLock(str(best)):
        try:
            live = debate_liveSession(str(best)) or "<unknown>"
        except Exception:
            live = "<unknown>"
        hookjson_emitBlock(
            f"/debate-retry: still running -> tmux attach -t {live}"
        )
        return 0

    debate_dir = best
    try:
        topic = (debate_dir / "topic.md").read_text(encoding="utf-8")
    except OSError:
        topic = ""
    _ = topic
    resuming = True

    detect_result = debate_detectAvailableAgents()
    available_agents: list[str] = list(detect_result.get("available", []))
    gemini_model: str = detect_result.get("gemini_model", "")
    codex_model: str = detect_result.get("codex_model", "")

    debate_checkResumeFeasibility(debate_dir, available_agents)

    failed_marker = debate_dir / "FAILED.txt"
    try:
        failed_marker.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass

    settings_file = os.environ.get("SETTINGS_FILE", "")
    debate_startOrResume(
        debate_dir=debate_dir,
        available_agents=available_agents,
        resuming=resuming,
        cwd=cwd,
        repo_root=repo_root,
        settings_file=settings_file,
        log_file=log_file,
        plugin_root=os.environ.get("CLAUDE_PLUGIN_ROOT", ""),
        gemini_model=gemini_model,
        codex_model=codex_model,
    )

    return 0


def debate_daemonMain(
    *,
    debate_dir: str | Path,
    session: str,
    window_target: str,
    agents: list[str],
    stage_timeout: int,
    plugin_root: str,
    composition_drifted: bool = False,
) -> int:
    """Drive the full R1 -> R2 -> synthesis pipeline for a debate session.

    Returns 0 on success; 1 on any subordinate failure.
    """
    debate_dir = Path(debate_dir)

    print("========================================")
    print("[orch] DEBATE DAEMON")
    print(f"[orch] Dir:     {debate_dir}")
    print(f"[orch] Session: {session}")
    print(f"[orch] Window:  {window_target}")
    print(f"[orch] Agents:  {agents} ({len(agents)})")
    print(f"[orch] Timeout: {stage_timeout}s per stage")
    print(f"[orch] Drift:   {int(composition_drifted)}")
    print("========================================")

    debate_initAgentModels()

    if composition_drifted:
        print("[orch] composition drifted -- clearing r2_*.md, r2_instructions_*.txt, synthesis_instructions.txt")
        for pattern in ("r2_*.md", "r2_instructions_*.txt", ".r2_*.lock"):
            for f in debate_dir.glob(pattern):
                f.unlink(missing_ok=True)
        (debate_dir / "synthesis_instructions.txt").unlink(missing_ok=True)

    debate_cleanStaleLocks("r1")

    r1_panes: list[str] = []
    for _agent in agents:
        r1_panes.append(debate_newEmptyPane())

    tmux_retile(window_target)
    print(f"[orch] R1 panes: agents={agents}={r1_panes}")
    time.sleep(1)

    if debate_launchAgentsParallel("r1", r1_panes) != 0:
        return 1

    if debate_waitForOutputs("r1", stage_timeout, r1_panes) != 0:
        return 1

    for pane in r1_panes:
        tmux_killPane(pane)
    tmux_retile(window_target)
    print("[orch] R1 agent panes closed")

    debate_cleanStaleLocks("r2")

    agents_str = " ".join(agents)
    for agent in agents:
        r2_instructions = debate_dir / f"r2_instructions_{agent}.txt"
        if r2_instructions.exists():
            continue
        debate_buildClaudePrompts(
            stage="r2",
            debate_dir=str(debate_dir),
            plugin_root=plugin_root,
            debate_agents=agents_str,
            agent_filter=agent,
        )

    r2_panes: list[str] = []
    for _agent in agents:
        r2_panes.append(debate_newEmptyPane())

    tmux_retile(window_target)
    print(f"[orch] R2 panes: agents={agents}={r2_panes}")
    time.sleep(1)

    if debate_launchAgentsParallel("r2", r2_panes) != 0:
        return 1

    if debate_waitForOutputs("r2", stage_timeout, r2_panes) != 0:
        return 1

    for pane in r2_panes:
        tmux_killPane(pane)
    tmux_retile(window_target)
    print("[orch] R2 agent panes closed")

    synthesis_md = debate_dir / "synthesis.md"
    if synthesis_md.exists() and synthesis_md.stat().st_size > 0:
        print("[orch] synthesis already complete, skipping launch; running archive step")
        debate_archive()
        print(f"[orch] DEBATE COMPLETE -- synthesis at {synthesis_md}")
        return 0

    debate_cleanStaleLocks("synthesis")

    synthesis_instructions = debate_dir / "synthesis_instructions.txt"
    if not synthesis_instructions.exists():
        debate_buildClaudePrompts(
            stage="synthesis",
            debate_dir=str(debate_dir),
            plugin_root=plugin_root,
            debate_agents=agents_str,
            agent_filter=None,
        )

    synth_pane = debate_newEmptyPane()
    tmux_retile(window_target)
    print(f"[orch] synthesis pane: {synth_pane}")
    time.sleep(1)

    launch_cmd = debate_agentLaunchCmd("claude")
    ready_marker = debate_agentReadyMarker("claude")

    if debate_launchAgent(synth_pane, "synthesis", "claude", launch_cmd, ready_marker) != 0:
        return 1

    if debate_sendPromptToAgent(synth_pane, "synthesis", "claude", str(synthesis_instructions)) != 0:
        return 1

    if shell_waitForFile(str(synthesis_md), stage_timeout) != 0:
        return 1

    tmux_killPane(synth_pane)
    tmux_retile(window_target)
    print("[orch] synthesis pane closed")

    debate_archive()
    print(f"[orch] DEBATE COMPLETE -- synthesis at {synthesis_md}")
    return 0


# Strict /plate prompt regex - mirrors bash grep -qE pattern exactly.
_PROMPT_RE_PLATE = re.compile(
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

    repo_root: str = get_repo_root(cwd) or ""
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

    print(emit_block(out))
    return 0


# Argv subcommand -> function map. Order mirrors the bash case block.
_ARGV_DISPATCH: dict = {
    "jot-session-start": jot_sessionStart,
    "jot-session-end": jot_sessionEnd,
    "jot-stop": jot_stop,
    "scan-open-todos": todo_scanOpen,
    "todo-launcher": todo_launcher,
    "todo-stop": todo_stop,
    "todo-session-start": todo_sessionStart,
    "todo-session-end": todo_sessionEnd,
    "plate-summary-stop": plate_summaryStop,
    "plate-summary-watch": plate_summaryWatch,
    "debate-tmux-orchestrator": debate_tmuxOrchestrator,
    "jot-diag-collect": jot_collectDiagnostics,
}

# Prompt prefix -> stdin-mode entrypoint.
_PROMPT_DISPATCH: tuple = (
    ("/jot", lambda: jot_main()),
    ("/plate", lambda: plate_main()),
    ("/debate", lambda: debate_launch()),
    ("/debate-retry", lambda: debateRetry_main()),
    ("/debate-abort", lambda: debateAbort_main()),
    ("/todo", lambda: todo_main()),
    ("/todo-list", lambda: todoList_main()),
)


def _matches_prefix(prompt: str, prefix: str) -> bool:
    """True if prompt is exactly `prefix`, `prefix `, or `prefix\\n` led."""
    if prompt == prefix:
        return True
    if prompt.startswith(prefix + " "):
        return True
    if prompt.startswith(prefix + "\n"):
        return True
    return False


def dispatch_main(argv: list[str] | None = None) -> int:
    """Top-level entrypoint mirroring the bash dispatcher.

    1. If argv[0] matches a known subcommand, route to it and exit.
    2. Otherwise read stdin (a hook JSON blob), extract `.prompt`, lstrip,
       normalise `/jot:<skill>` -> `/<skill>` (rewriting JSON too), and
       dispatch to the matching prompt entrypoint via stdin piping.
    """
    if argv is None:
        argv = sys.argv[1:]

    if argv:
        head = argv[0]
        fn = _ARGV_DISPATCH.get(head)
        if fn is not None:
            rc = fn(argv[1:])
            return int(rc) if rc is not None else 0

    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = {}
    prompt = data.get("prompt", "") if isinstance(data, dict) else ""
    prompt = prompt.lstrip()

    if prompt.startswith("/jot:"):
        prompt = "/" + prompt[len("/jot:"):]
        if isinstance(data, dict):
            data["prompt"] = prompt
            raw = json.dumps(data)

    for prefix, fn in sorted(_PROMPT_DISPATCH, key=lambda p: -len(p[0])):
        if _matches_prefix(prompt, prefix):
            saved_stdin = sys.stdin
            try:
                sys.stdin = io.StringIO(raw)
                rc = fn()
            finally:
                sys.stdin = saved_stdin
            return int(rc) if rc is not None else 0

    return 0
