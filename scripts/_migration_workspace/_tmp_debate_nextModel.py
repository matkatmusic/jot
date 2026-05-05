"""Workspace temp module for debate_nextModel migration.

Migrated from bash `_next_model` (jot-plugin-orchestrator.sh ~line 2801).
ABSORBED: bash `_lookup TRIED_MODELS "$agent"` is replaced by a plain dict
parameter (`tried_models`), per plan §ABSORBED.

RELAXED_COVERAGE: no paired bash _tests existed; behavior derived from body.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure scripts/ is on sys.path for any cross-imports if needed later.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# YELLOW intent: read the models JSON, list candidate models for `agent`,
# return the first model whose name does not appear in the agent's tried
# list (comma-separated string mirroring the bash _stash format). If none
# remain, or the file/agent is missing, return None.

def debate_nextModel(
    agent: str,
    tried_models: dict[str, str],
    models_json_path: str,
) -> str | None:
    """Return the next untried model name for `agent`, or None if exhausted.

    Args:
        agent: agent key (e.g. "gemini", "codex", "claude").
        tried_models: dict mapping agent name -> comma-separated tried list
            (e.g. {"gemini": "gem-pro,gem-flash"}). Mirrors the bash
            TRIED_MODELS stash that this migration absorbs.
        models_json_path: path to assets/models.json (agent -> [models]).

    Returns:
        First model in the JSON list for `agent` not present in
        `tried_models[agent]`, or None when no untried model exists,
        the file is missing/unreadable, or the agent has no entry.
    """
    # GREEN: load JSON tolerantly; bash used `hide_errors jq` which yields
    # empty stdin on failure -> the while-read loop produced rc=1.
    try:
        with open(models_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    candidates = data.get(agent) or []
    # bash matched ",$tried," against ",$m," — i.e. exact whole-token match
    # within a comma-delimited string. Splitting and using a set replicates
    # that with O(1) membership and tolerates leading/trailing commas.
    tried_raw = tried_models.get(agent, "") or ""
    tried_set = {t for t in tried_raw.split(",") if t}

    for m in candidates:
        if not m:
            continue
        if m in tried_set:
            continue
        return m
    return None
