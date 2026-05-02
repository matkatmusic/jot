"""Platform-specific UX helpers for Claude Code hooks.

Public API:
    spawnTerminalIfNeeded(session, log_file, log_prefix, maximize)

If no tmux client is attached to <session>, opens a new macOS Terminal
window via osascript and runs `tmux attach -t <session>` in it. Best-
effort UX: never raises; all errors are swallowed and (where possible)
logged to <log_file>. On non-Darwin hosts or when osascript is missing,
writes an advisory line to <log_file> instead.

Migrated from common/scripts/platform.sh per MIGRATION_TO_PYTHON.md.
"""
from __future__ import annotations

import platform as _platform
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

OSASCRIPT = "osascript"
DARWIN = "Darwin"
DEFAULT_LOG_FILE = Path("/dev/null")
DEFAULT_LOG_PREFIX = "tmux"

# Advisory message templates (single-line, appended to the log file).
_ADVISORY_NO_OSASCRIPT = (
    "{ts} {prefix}: osascript unavailable; "
    "attach manually via `tmux attach -t {session}`"
)
_ADVISORY_NON_DARWIN = (
    "{ts} {prefix}: non-Darwin host; "
    "attach manually via `tmux attach -t {session}`"
)


def _isoTimestamp() -> str:
    """ISO-8601 timestamp with timezone, matching `date -Iseconds`."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _clientsAttached(session: str) -> bool:
    """True iff at least one tmux client is attached to <session>.

    A non-existent session (tmux exits non-zero) is treated as "no
    clients attached" so the caller proceeds to spawn a terminal.
    """
    try:
        completed = subprocess.run(
            ["tmux", "list-clients", "-t", session],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        # tmux not installed, or process spawn failed: treat as
        # "no clients" so the caller falls through to the spawn path
        # (mirrors hide_errors behavior in tmux.sh's tmux_list_clients).
        return False
    if completed.returncode != 0:
        return False
    return bool((completed.stdout or "").strip())


def _appendAdvisory(log_file: Path, prefix: str, session: str, template: str) -> None:
    """Append one advisory line to <log_file>; swallow all I/O errors."""
    line = template.format(ts=_isoTimestamp(), prefix=prefix, session=session)
    try:
        with log_file.open("a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _buildOsascript(session: str, maximize: bool) -> str:
    """Return the AppleScript program to attach Terminal to <session>.

    Mirrors the heredoc in platform.sh exactly: opens a new window in a
    running Terminal, or launches Terminal and uses window 1. When
    <maximize> is True, appends a Finder/Terminal block that resizes
    the front Terminal window to the active desktop's bounds.
    """
    body = (
        f'if application "Terminal" is running then\n'
        f'  tell application "Terminal" to do script "tmux attach -t {session}"\n'
        f'else\n'
        f'  tell application "Terminal"\n'
        f'    do script "tmux attach -t {session}" in window 1\n'
        f'  end tell\n'
        f'end if'
    )
    if maximize:
        body += (
            '\n'
            'tell application "Finder"\n'
            '  set screenBounds to bounds of window of desktop\n'
            'end tell\n'
            'tell application "Terminal"\n'
            '  set bounds of front window to screenBounds\n'
            'end tell'
        )
    return body


def _spawnOsascriptDetached(script: str) -> None:
    """Run osascript in the background; do not wait for completion.

    Matches the bash `osascript <<OSA &` pattern: the AppleScript
    blocks for several seconds while Terminal launches, but the
    caller's hook must return within its latency budget.
    """
    try:
        proc = subprocess.Popen(
            [OSASCRIPT, "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return
    try:
        if proc.stdin is not None:
            proc.stdin.write(script.encode())
            proc.stdin.close()
    except OSError:
        pass


def spawnTerminalIfNeeded(
    session: str,
    log_file: Path | str = DEFAULT_LOG_FILE,
    log_prefix: str = DEFAULT_LOG_PREFIX,
    maximize: bool = False,
) -> None:
    """Open a Terminal attached to <session> when no client is connected.

    Args:
        session:    tmux session name to attach to.
        log_file:   file to append advisory lines to (defaults to /dev/null).
        log_prefix: short tag prefixed to advisory lines (defaults to "tmux").
        maximize:   if True, resize the spawned window to desktop bounds.
    """
    if not session:
        # The bash shim enforces this with ${1:?...}; mirror by no-op.
        return
    if _clientsAttached(session):
        return
    log_path = Path(log_file)
    if _platform.system() != DARWIN:
        _appendAdvisory(log_path, log_prefix, session, _ADVISORY_NON_DARWIN)
        return
    if shutil.which(OSASCRIPT) is None:
        _appendAdvisory(log_path, log_prefix, session, _ADVISORY_NO_OSASCRIPT)
        return
    _spawnOsascriptDetached(_buildOsascript(session, maximize))
