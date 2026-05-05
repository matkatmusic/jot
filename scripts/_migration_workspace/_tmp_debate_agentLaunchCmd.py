#!/usr/bin/env python3
"""Migration temp module: debate_agentLaunchCmd.

Mirrors bash agent_launch_cmd from jot-plugin-orchestrator.sh (~L2740-2765).
Returns the CLI launch command string for one debate agent (gemini/codex/claude).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Standard sys.path insert (parent contains jot_plugin_orchestrator.py if needed).
HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))


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
