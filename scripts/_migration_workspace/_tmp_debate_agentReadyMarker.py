"""YELLOW stub for debate_agentReadyMarker.

Intent: Given an agent name (gemini/codex/claude), return the literal
substring that appears in the agent's terminal pane once it has finished
booting and is ready to receive input. Unknown agents return empty string
(matching bash `case` fall-through behavior with no default branch).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jot_plugin_orchestrator import *  # noqa: F401,F403


def debate_agentReadyMarker(agent: str) -> str:
    # GREEN: mirror bash `agent_ready_marker` case statement verbatim.
    if agent == "gemini":
        return "Type your message or @path/to/file"
    if agent == "codex":
        return "/model to change"
    if agent == "claude":
        return "Claude Code v"
    # Bash `case` with no default leaves stdout empty.
    return ""
