"""GREEN implementation of plate_summaryWatch.

Workspace temp module for the bash->Python migration of
`plate_summary_watch` (scripts/jot-plugin-orchestrator.sh, ~L3854-3909).

YELLOW intent (plain English):
  Poll `output_file` every `interval` seconds for up to `timeout` seconds.
  As soon as the file exists AND is non-empty, dispatch the Claude TUI's
  graceful-shutdown sequence to the agent's tmux pane (literal "/exit"
  followed by "Enter") and return 0. If the deadline elapses without the
  file ever becoming non-empty, return 1 and leave the pane alone so the
  operator can investigate. Errors from the tmux send path (e.g. the pane
  has already disappeared) are swallowed -- the watcher still reports
  success, matching the bash `2>/dev/null || true` semantics.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional


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
