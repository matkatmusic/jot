"""GREEN implementation for debate_initAgentModels.

Migrated from bash init_agent_models (jot-plugin-orchestrator.sh ~L2727).
ABSORBED: original used _stash/_lookup global var-name idiom; replaced with
a plain dict returned from this function so the caller owns the state.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Agents in the order the bash loop initializes them.
_AGENTS = ("gemini", "codex", "claude")
# Map agent -> env var name that seeds CURRENT_MODEL/TRIED_MODELS.
# claude has no seed env var (matches bash, which only stashes "" for it).
_AGENT_ENV_VAR = {"gemini": "GEMINI_MODEL", "codex": "CODEX_MODEL"}


def debate_initAgentModels(env: Mapping[str, str] | None = None) -> dict[str, dict[str, str]]:
    """Build initial agent-model state for a debate.

    Returns a fresh mapping of:
        {
            "CURRENT_MODEL": {agent: model_or_empty, ...},
            "TRIED_MODELS":  {agent: model_or_empty, ...},
        }
    seeded from `env` (defaults to os.environ). Mirrors bash ${VAR:-}: an
    unset env var becomes "".
    """
    # Read os.environ lazily so monkeypatch.setenv works for callers omitting env.
    src: Mapping[str, str] = os.environ if env is None else env

    state: dict[str, dict[str, str]] = {
        "CURRENT_MODEL": {a: "" for a in _AGENTS},
        "TRIED_MODELS": {a: "" for a in _AGENTS},
    }

    for agent, var in _AGENT_ENV_VAR.items():
        seed = src.get(var, "") or ""
        state["CURRENT_MODEL"][agent] = seed
        state["TRIED_MODELS"][agent] = seed

    return state
