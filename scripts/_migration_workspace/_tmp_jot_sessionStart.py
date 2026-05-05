"""Migration workspace: GREEN body for jot_sessionStart.

Source: scripts/jot-plugin-orchestrator.sh `jot_session_start()` (lines ~3350-3394).
RELAXED_COVERAGE: no paired bash _tests; tests authored from intent/docstring only.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts/_migration_workspace")

# Already-migrated dependencies live in the canonical module. No workspace fallbacks needed.
from jot_plugin_orchestrator import (
    tmux_sendAndSubmit,
    tmux_waitForClaudeReadiness,
)


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
