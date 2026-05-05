#!/usr/bin/env python3
"""Jot plugin orchestrator (Python).

Canonical Python monolith for the jot plugin. Replaces
`scripts/jot-plugin-orchestrator.sh` function-by-function.
"""
from __future__ import annotations

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
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Callable, Optional, Sequence, Type


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
