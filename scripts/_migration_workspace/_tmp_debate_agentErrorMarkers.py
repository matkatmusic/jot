"""GREEN: debate_agentErrorMarkers - migrated from bash `agent_error_markers`.

Bash source: scripts/jot-plugin-orchestrator.sh lines 2777-2783.
Returns the list of substring markers used by `pane_has_capacity_error`
to detect capacity / quota / overload errors in a tmux pane capture for a
given agent. Bash printed one marker per line via `printf '%s\\n'`; the
Python contract is a list[str] preserving the original order. Unknown
agents map to the empty list (bash case had no default branch, so no
output was produced).

Intent (YELLOW->GREEN): callers iterate the returned markers and grep -F
each one against captured pane text; ordering matches bash so the first
matching marker stays stable across the migration.
"""
from __future__ import annotations


# Frozen tuples used as the source of truth; copied into a fresh list per
# call so callers cannot mutate shared state.
_MARKERS: dict[str, tuple[str, ...]] = {
    "codex": (
        "Selected model is at capacity",
        "model is overloaded",
    ),
    "gemini": (
        "RESOURCE_EXHAUSTED",
        "Quota exceeded",
        "You exceeded your current quota",
    ),
    "claude": (
        "API Error: 529",
        "overloaded_error",
    ),
}


def debate_agentErrorMarkers(agent: str) -> list[str]:
    """Return capacity/quota/overload error markers for ``agent``.

    Mirrors bash `agent_error_markers`: a case statement over
    ``codex|gemini|claude`` printing one marker per line. Unknown agent
    names yield an empty list (bash printed nothing).

    Args:
        agent: Agent identifier (``codex``, ``gemini``, or ``claude``).

    Returns:
        Ordered list of marker substrings. Empty list for unknown agents.
    """
    return list(_MARKERS.get(agent, ()))
