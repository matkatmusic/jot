from __future__ import annotations

import errno
import fcntl
import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Optional, Sequence, Type


# ── Subprocess wrapper ────────────────────────────────────────────────
def run(
    cmd: list[str],
    cwd: Path,
    env: Optional[dict[str, str]] = None,
    check: bool = True,
    capture: bool = True,
) -> str:
    """Run cmd in cwd. Return stripped stdout when capture=True."""
    full_env: Optional[dict[str, str]] = None
    if env is not None:
        full_env = os.environ.copy()
        full_env.update(env)
    completed = subprocess.run(
        cmd,
        cwd=cwd,
        env=full_env,
        text=True,
        capture_output=capture,
        check=check,
    )
    if not capture:
        return ""
    return (completed.stdout or "").strip()


def currentTimestampMs() -> str:
    """Millisecond-resolution timestamp for patch-file naming."""
    return str(int(time.time() * 1000))


def _util_matches_prefix(prompt: str, prefix: str) -> bool:
    """True if prompt is exactly `prefix`, `prefix `, or `prefix\\n` led."""
    if prompt == prefix:
        return True
    if prompt.startswith(prefix + " "):
        return True
    if prompt.startswith(prefix + "\n"):
        return True
    return False



# Slug helpers: lowercase, replace non-alnum runs with '-', head 40, strip trailing '-'.
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

def _util_slugify(topic: str) -> str:
    """Mirror bash: tr lower | tr -cs '[:alnum:]' '-' | head -c 40 | sed 's/-$//'."""
    lowered = topic.lower()
    collapsed = _NON_ALNUM_RE.sub("-", lowered)
    return collapsed[:40].rstrip("-")



# Resolve the plugin root: prefer CLAUDE_PLUGIN_ROOT env, else the parent of
# this file's parent (mirrors bash `dirname/..`).
def _util_resolvePluginRoot() -> Path:
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parent.parent


def _util_safe_call(fn: Callable[..., Any], *args: Any) -> str:
    """Bash `safe` wrapper: swallow failures, return '(unavailable)'."""
    try:
        result = fn(*args)
        if result is None:
            return "(unavailable)"
        text = str(result)
        return text if text else "(unavailable)"
    except Exception:
        return "(unavailable)"


def _util_strip_stdin_text(text: str) -> str:
    """Mirror common/scripts/jot/strip_stdin.py: strip leading whitespace,
    replace null bytes with spaces."""
    return text.lstrip().replace("\x00", " ")


def _util_append_log(log_file: str, line: str) -> None:
    """Append a line to the log file; swallow all errors (bash hide_errors)."""
    if not log_file:
        return
    try:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        return


def _util_hide_errors(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception:
        return "(unavailable)"


def _util_appendAudit(audit_path: Path, line: str) -> None:
    with audit_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


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


def _util_isoTimestampLocal() -> str:
    # Match bash `date -Iseconds` (local-tz, seconds precision).
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


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



# Spawns a macOS Terminal.app window attached to a tmux session when there are no attached clients; logs manual-attach advice on unsupported hosts.
def terminal_spawnIfNeeded(
    session: str,
    log_file: str = "/dev/null",
    log_prefix: str = "tmux",
    maximize: str = "",
) -> int:
    if not session:
        raise ValueError("terminal_spawnIfNeeded: session name required")

    clients = _terminal_listTmuxClients(session)
    if clients.strip():
        return 0

    if sys.platform == "darwin":
        if shutil.which("osascript") is None:
            _terminal_appendAdvisory(log_file, log_prefix, session)
            return 0
        script = _terminal_buildOsascript(session, maximize)
        # start_new_session=True detaches osascript from the caller's
        # process group so it survives parent exit (e.g. when /plate runs
        # as a UserPromptSubmit hook and the orchestrator returns within
        # milliseconds). We do NOT call .communicate() / .wait() — write
        # the script to stdin, close it, and return. osascript runs to
        # completion under launchd after we exit.
        try:
            proc = subprocess.Popen(
                ["osascript"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                proc.stdin.write(script.encode("utf-8"))
            finally:
                proc.stdin.close()
        except (OSError, subprocess.SubprocessError):
            pass
        return 0

    _terminal_appendNonDarwinAdvisory(log_file, log_prefix, session)
    return 0


def _util_ls_latest_input_txt(todos_dir: Path) -> Path | None:
    """Return the most-recently-modified *_input.txt under todos_dir, or None."""
    candidates = sorted(todos_dir.glob("*_input.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None



def _util_tail_lines(path: Path, n: int) -> str:
    """Return last n lines of path as a string, or empty string if unreadable."""
    try:
        text = path.read_text(errors="replace")
        lines = text.splitlines(keepends=True)
        return "".join(lines[-n:])
    except OSError:
        return ""



def _terminal_launchBackground() -> None:
    """Fire-and-forget: launch Terminal.app via osascript without activating."""
    subprocess.Popen(
        ["osascript", "-e", "tell application \"Terminal\" to launch"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _terminal_running() -> bool:
    """Return True if Terminal.app process is found via pgrep."""
    result = subprocess.run(
        ["pgrep", "-q", "Terminal"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _terminal_listTmuxClients(session: str) -> str:
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


def _terminal_buildOsascript(session: str, maximize: str) -> str:
    return (
        f'if application "Terminal" is running then\n'
        f'  tell application "Terminal" to do script "tmux attach -t {session}"\n'
        f"else\n"
        f'  tell application "Terminal"\n'
        f'    do script "tmux attach -t {session}" in window 1\n'
        f"  end tell\n"
        f"end if{_terminal_maximizeBlock(maximize)}"
    )


def _terminal_isoNow() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _terminal_appendAdvisory(log_file: str, prefix: str, session: str) -> None:
    if not log_file or log_file == "/dev/null":
        return
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(
                f"{_terminal_isoNow()} {prefix}: osascript unavailable; "
                f"attach manually via `tmux attach -t {session}`\n"
            )
    except OSError:
        return


def _terminal_appendNonDarwinAdvisory(log_file: str, prefix: str, session: str) -> None:
    if not log_file or log_file == "/dev/null":
        return
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(
                f"{_terminal_isoNow()} {prefix}: non-Darwin host; "
                f"attach manually via `tmux attach -t {session}`\n"
            )
    except OSError:
        return


def _terminal_maximizeBlock(maximize: str) -> str:
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


def _util_readFirstToken(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        line = fh.readline()
    parts = line.strip().split()
    return parts[0] if parts else ""


def _util_sha256File(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


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


def _valid_kwargs(**overrides: object) -> dict:
    """Return a minimal valid call-site kwargs dict."""
    base: dict = dict(
        debate_dir="/tmp/debate",
        session="jot",
        window_name="debate",
        settings_file="/tmp/settings.json",
        cwd="/tmp/repo",
        repo_root="/tmp/repo",
        plugin_root="/tmp/plugin",
        debate_agents="claude gemini",
    )
    base.update(overrides)
    return base

