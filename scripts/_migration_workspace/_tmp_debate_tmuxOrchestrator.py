#!/usr/bin/env python3
"""Workspace migration: debate_tmuxOrchestrator.

Translates debate_tmux_orchestrator() from jot-plugin-orchestrator.sh (lines 3150-3165).

Entry-point function: argv-dispatch routes "debate-tmux-orchestrator" here.
Positional args: DEBATE_DIR SESSION WINDOW_NAME SETTINGS_FILE CWD REPO_ROOT PLUGIN_ROOT
Env (caller-set): DEBATE_AGENTS, GEMINI_MODEL, CODEX_MODEL, COMPOSITION_DRIFTED

STAGE_TIMEOUT is hard-coded to 15*60 = 900 seconds, matching the bash original.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import from the monolith where available; workspace-fallback for pending callees.
try:
    from jot_plugin_orchestrator import (  # type: ignore[import]
        cleanup as _cleanup,
        daemon_main as _daemon_main,
    )
    _workspace_cleanup = _cleanup
    _workspace_daemon_main = _daemon_main
except ImportError:
    # Workspace fallbacks — replace with monolith imports once those functions are migrated.
    def _workspace_cleanup() -> None:  # type: ignore[misc]
        """Workspace fallback: cleanup not yet migrated."""
        raise NotImplementedError("cleanup is not yet migrated to jot_plugin_orchestrator.py")

    def _workspace_daemon_main(ctx: "DebateContext") -> None:  # type: ignore[misc]
        """Workspace fallback: daemon_main not yet migrated."""
        raise NotImplementedError("daemon_main is not yet migrated to jot_plugin_orchestrator.py")


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
    _cleanup_fn = cleanup_fn if cleanup_fn is not None else _workspace_cleanup
    _daemon_fn = daemon_main_fn if daemon_main_fn is not None else _workspace_daemon_main

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
