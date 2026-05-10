

import re
import subprocess
import time
import sys

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


def _tmux_default_runner(argv: list[str]) -> int:
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


def _tmux_run(*args: str) -> str:
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


# Default tmux send used when the caller does not inject one.
def _tmux_default_send(pane: str, keys: str) -> None:
    # Mirrors `tmux send-keys -t "$PANE" <keys> 2>/dev/null || true` --
    # callers swallow errors at the dispatch layer, but we also redirect
    # stderr here so a missing pane doesn't pollute the watcher's log.
    subprocess.run(
        ["tmux", "send-keys", "-t", pane, keys],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _tmux_backgroundKill(pane_target: str, retile_target: str = "jot:jots") -> None:
    # Bash forks a `( sleep 0.5; kill-pane; retile ) &` subshell so the hook
    # can return BEFORE tmux signals claude. In Python we expose this as a
    # function so tests can monkeypatch it; default impl does the work
    # synchronously (no sleep, no fork — the hook semantics are the same
    # because we are not the claude process being killed in test).
    tmux_killPane(pane_target)
    tmux_retile(retile_target)


def _tmux_live_pane_ids() -> set[str]:
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

def _tmux_kill_pane(pane_id: str) -> None:
    """Kill a tmux pane, silencing errors (mirrors bash `hide_errors tmux_kill_pane`)."""
    subprocess.run(
        ["tmux", "kill-pane", "-t", pane_id],
        capture_output=True,
        check=False,
    )


# Boundary seam: returns the pane's current foreground command (e.g. "gemini","codex","bash").
# Tests patch this.
def _tmux_paneCurrentCommand(pane_id: str) -> str:
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


# Boundary seam: returns the set of live pane ids (e.g. {"%5","%7"}) in WINDOW_TARGET.
# Tests patch this; production callers pass `window_target` from the orchestrator.
def _tmux_listLivePaneIds(window_target: str) -> set[str]:
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

