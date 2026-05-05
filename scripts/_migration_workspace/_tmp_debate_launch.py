"""
Migration workspace: debate_launch

Bash source: scripts/jot-plugin-orchestrator.sh lines 3171-3190
Section: debate-orchestrator.sh

debate_launch is the entry-point called by argv-dispatch for the
"debate-orchestrator" subcommand. It:
  1. Resolves SCRIPTS_DIR (directory of this file) and PLUGIN_ROOT
     (three levels up from SCRIPTS_DIR).
  2. On Darwin, ensures Terminal.app is running by launching it via
     osascript if `pgrep Terminal` finds nothing. Fire-and-forget
     (background process, non-blocking).
  3. Delegates all real work to debate_main().

YELLOW: No logic of its own beyond environment setup + Terminal
        launch guard + delegate. Tests verify the delegation contract
        and the Darwin guard branching.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Workspace-fallback imports
# Try the merged monolith first; fall back to workspace stubs so pytest can
# run in isolation. The merging Claude should replace these with direct
# monolith imports.
# ---------------------------------------------------------------------------
try:
    from jot_plugin_orchestrator import debate_main  # type: ignore[import]
except ImportError:
    # Workspace stub — callers must mock this in tests.
    def debate_main() -> None:  # type: ignore[misc]
        """Stub: replaced by monolith import after merge."""
        raise NotImplementedError("debate_main not available in workspace")


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
