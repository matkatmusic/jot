"""
debate_startOrResume -- migrated from debate_start_or_resume() in
scripts/jot-plugin-orchestrator.sh lines 2481-2563.

SIGNATURE CHANGE (RELAXED_COVERAGE):
    Bash used globals DEBATE_DIR, AVAILABLE_AGENTS, RESUMING, CWD, REPO_ROOT,
    SETTINGS_FILE, LOG_FILE, CLAUDE_PLUGIN_ROOT, GEMINI_MODEL, CODEX_MODEL.
    Python receives them as explicit keyword-only arguments.

DAEMON LAUNCH STRATEGY:
    Bash used `bash <script> ... >> orch_log 2>&1 </dev/null & disown`.
    Python uses subprocess.Popen with start_new_session=True and stdout/stderr
    redirected to an open file handle for orchestrator.log.  The parent does
    NOT wait on the child -- Popen.pid is intentionally not joined.

DRIFT DETECTION:
    Compares sorted-unique sets of r1_instructions_<agent>.txt basenames
    already on disk vs the provided available_agents list.  Any mismatch sets
    composition_drifted=True and passes COMPOSITION_DRIFTED=1 to the daemon.

MERGE NOTE -- WORKSPACE FALLBACK:
    The try/except import block below is a temporary workaround.  When merging
    this file into jot_plugin_orchestrator.py, remove the except branch and
    the try/except wrapper entirely.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Workspace-fallback imports -- REMOVE except branch on merge
# ---------------------------------------------------------------------------
try:
    from jot_plugin_orchestrator import (
        debate_buildClaudePrompts,
        debate_buildClaudeCmd,
        debate_claimSession,
        terminal_spawnIfNeeded,
        hookjson_emitBlock,
    )
except ImportError:
    from _tmp_debate_buildClaudePrompts import debate_buildClaudePrompts  # type: ignore[no-redef]
    from _tmp_debate_buildClaudeCmd import debate_buildClaudeCmd  # type: ignore[no-redef]
    from _tmp_debate_claimSession import debate_claimSession  # type: ignore[no-redef]
    from jot_plugin_orchestrator import terminal_spawnIfNeeded, hookjson_emitBlock  # type: ignore[no-redef]


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

    Mirrors debate_start_or_resume() exactly:
    1. Detect composition drift when resuming.
    2. Build missing per-stage instruction files (r1 / r2 / synthesis).
    3. Build the Claude command via debate_buildClaudeCmd.
    4. Claim a tmux session (debate-N); exit 0 with an error block on failure.
    5. Apply session-scoped tmux options and name the keepalive pane.
    6. Launch the daemon (jot-plugin-orchestrator.sh debate-tmux-orchestrator)
       detached via Popen(start_new_session=True).
    7. Spawn a terminal if needed.
    8. Emit the final /debate <verb> block.

    Args:
        debate_dir: Path to the debate working directory.
        available_agents: Ordered list of agent names for this debate.
        resuming: True when continuing an existing debate.
        cwd: Working directory passed to the daemon.
        repo_root: Absolute path to the repository root.
        settings_file: Path to the Claude settings JSON.
        log_file: Path to the log file used by terminal_spawnIfNeeded.
        plugin_root: Absolute path to the plugin root (CLAUDE_PLUGIN_ROOT).
        gemini_model: Model name forwarded to the daemon as GEMINI_MODEL.
        codex_model: Model name forwarded to the daemon as CODEX_MODEL.
    """
    debate_dir = Path(debate_dir)
    window_name = "main"

    # ------------------------------------------------------------------
    # 1. Detect composition drift (resume path only).
    # ------------------------------------------------------------------
    composition_drifted = False
    if resuming:
        # Collect agent names from existing r1 instruction files on disk.
        original_agents: set[str] = set()
        for f in debate_dir.glob("r1_instructions_*.txt"):
            # Strip prefix and suffix: r1_instructions_<agent>.txt -> <agent>
            stem = f.stem  # e.g. r1_instructions_claude
            agent_name = stem[len("r1_instructions_"):]
            original_agents.add(agent_name)

        # Compare sorted-unique sets.
        if original_agents != set(available_agents):
            composition_drifted = True

    # ------------------------------------------------------------------
    # 2. Build missing per-stage instruction files.
    # ------------------------------------------------------------------
    agents_joined = " ".join(available_agents)

    # r1 stage -- one file per agent
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

    # r2 stage -- one file per agent
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

    # synthesis stage -- single shared file
    synthesis_path = debate_dir / "synthesis_instructions.txt"
    if not synthesis_path.exists():
        debate_buildClaudePrompts(
            stage="synthesis",
            debate_dir=str(debate_dir),
            plugin_root=plugin_root,
            debate_agents=agents_joined,
            agent_filter=None,
        )

    # ------------------------------------------------------------------
    # 3. Build the Claude command.
    # ------------------------------------------------------------------
    debate_buildClaudeCmd(
        debate_dir=str(debate_dir),
        plugin_root=plugin_root,
    )

    # ------------------------------------------------------------------
    # 4. Claim a tmux session.
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 5. Apply session-scoped tmux options and name the keepalive pane.
    # ------------------------------------------------------------------
    _tmux_set = [
        ["tmux", "set-option", "-t", session, "remain-on-exit", "off"],
        ["tmux", "set-option", "-t", session, "mouse", "on"],
        ["tmux", "set-option", "-t", session, "pane-border-status", "top"],
        ["tmux", "set-option", "-t", session, "pane-border-format", " #{pane_title} "],
    ]
    for cmd in _tmux_set:
        subprocess.run(cmd, stderr=subprocess.DEVNULL)  # hide_errors equivalent

    pane_title = f"keepalive:{debate_dir.name}"
    subprocess.run(
        ["tmux", "select-pane", "-t", f"{session}:{window_name}", "-T", pane_title],
        stderr=subprocess.DEVNULL,
    )

    # ------------------------------------------------------------------
    # 6. Launch the daemon detached (replaces bash `& disown`).
    # ------------------------------------------------------------------
    orch_log_path = debate_dir / "orchestrator.log"
    orch_log_handle = open(orch_log_path, "a")  # noqa: WPS515 -- kept open intentionally

    daemon_env_extras = {
        "GEMINI_MODEL": gemini_model,
        "CODEX_MODEL": codex_model,
        "DEBATE_AGENTS": agents_joined,
        "COMPOSITION_DRIFTED": "1" if composition_drifted else "0",
        "SESSION": session,
    }

    import os  # import here to keep top-level imports minimal

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
        start_new_session=True,  # equivalent to disown
        env=daemon_env,
    )
    # Parent does NOT wait -- daemon runs independently.

    # ------------------------------------------------------------------
    # 7. Spawn a terminal if needed.
    # ------------------------------------------------------------------
    terminal_spawnIfNeeded(
        session=session,
        log_file=log_file,
        skill="debate",
        required="yes",
    )

    # ------------------------------------------------------------------
    # 8. Emit the final status block.
    # ------------------------------------------------------------------
    agents_str = ", ".join(available_agents)
    rel = f"Debates/{debate_dir.name}"
    verb = "resumed" if resuming else "spawned"
    hookjson_emitBlock(
        f"/debate {verb} ({agents_str}) -> {rel}/synthesis.md "
        f"(~10-30 min). View: tmux attach -t {session}"
    )
