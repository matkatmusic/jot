"""Migration workspace temp module for debate_paneHasCapacityError.

Mirrors the bash `pane_has_capacity_error` function from
scripts/jot-plugin-orchestrator.sh (lines ~2786-2798).
"""
from __future__ import annotations

import os
import sys

# Allow importing the production module's helpers from the parent scripts dir.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from jot_plugin_orchestrator import tmux_capturePane  # noqa: E402


# Per-agent capacity / quota error markers, mirroring bash agent_error_markers.
# Order is preserved (first match wins) to match bash while-read semantics.
_AGENT_ERROR_MARKERS: dict[str, tuple[str, ...]] = {
    "codex": ("Selected model is at capacity", "model is overloaded"),
    "gemini": ("RESOURCE_EXHAUSTED", "Quota exceeded", "You exceeded your current quota"),
    "claude": ("API Error: 529", "overloaded_error"),
}


# Probes pane scrollback for an agent-specific capacity / overload marker.
# Returns the matched marker string (truthy) on hit, or "" (falsy) when no
# marker matches or the agent is unknown. Strips ANSI ESC bytes before
# matching to mirror `tr -d '\033'` in the bash original.
def debate_paneHasCapacityError(pane_id: str, agent: str) -> str:
    markers = _AGENT_ERROR_MARKERS.get(agent, ())
    if not markers:
        return ""
    capture = tmux_capturePane(pane_id, scrollback_lines=200)
    # Bash strips raw ESC (\033) bytes before grep -F.
    capture = capture.replace("\033", "")
    for marker in markers:
        if not marker:
            continue
        if marker in capture:
            return marker
    return ""
