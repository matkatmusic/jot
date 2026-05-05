"""GREEN implementation for debate_defaultModel.

Bash source: jot-plugin-orchestrator.sh `_default_model()` lines 2186-2190.
  local models_json="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/assets/models.json"
  local agent="$1"
  hide_errors jq -r --arg a "$agent" '.[$a][0] // ""' "$models_json"

Behavioural contract:
  * Read launch-time (index 0) model name for `agent` from models.json.
  * Unknown agent OR empty list -> "" (matches jq `// ""` fallback).
  * Missing/unreadable models.json under bash `hide_errors` returns "";
    here we mirror that by treating IO/parse errors as "" (parity with
    callers _probe_gemini/_probe_codex which check for emptiness only).
  * Missing CLAUDE_PLUGIN_ROOT raises — bash uses `:?` guard at hook entry,
    so absence is a programmer error, not a runtime "" fallback.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Standard temp file header: ensure workspace dir is importable.
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


# Reads launch-time (index 0) model name for `agent` from
# ${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/assets/models.json.
# Returns "" when the agent key is absent or its model list is empty.
# Raises KeyError if CLAUDE_PLUGIN_ROOT is unset (mirrors bash `:?` guard).
def debate_defaultModel(agent: str) -> str:
    plugin_root = os.environ["CLAUDE_PLUGIN_ROOT"]
    models_json = Path(plugin_root) / "skills" / "debate" / "scripts" / "assets" / "models.json"
    try:
        data = json.loads(models_json.read_text())
    except (OSError, json.JSONDecodeError):
        # Bash wraps jq with `hide_errors`; an unreadable/invalid file
        # surfaces as empty stdout, which probes treat as "unavailable".
        return ""
    entry = data.get(agent)
    if not isinstance(entry, list) or not entry:
        return ""
    first = entry[0]
    return first if isinstance(first, str) else ""
