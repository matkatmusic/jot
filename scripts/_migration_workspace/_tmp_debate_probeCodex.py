"""GREEN implementation of debate_probeCodex.

Migrated from bash `_probe_codex` (jot-plugin-orchestrator.sh:2208-2213).
RELAXED_COVERAGE: no paired bash _tests; coverage authored from docstring intent.

YELLOW intent (plain English):
  Decide whether the `codex` CLI is usable for a debate run. Three gates,
  evaluated in order:
    1. Is the `codex` binary on PATH? If not, return "" (unavailable).
    2. Are credentials present? Either ~/.codex/auth.json on disk OR the
       OPENAI_API_KEY environment variable. If neither, return "".
    3. Look up the launch-time model from models.json via _default_model.
       Return the model name, or the literal "present" sentinel if no
       model is configured (so the caller's `-s` non-empty check still
       treats codex as available).

  Empty string means "do not use codex this run". Any non-empty string
  means "codex is available; use this string as the model identifier".
"""

import os
import shutil
import sys
from typing import Optional

# Workspace fallback: pull _default_model from the monolith if migrated;
# otherwise from the workspace tmp file. Listed in fallback report below.
sys.path.insert(
    0,
    "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts",
)
sys.path.insert(
    0,
    "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts/_migration_workspace",
)

try:
    from jot_plugin_orchestrator import _default_model  # type: ignore
except ImportError:
    try:
        from _tmp_default_model import _default_model  # type: ignore
    except ImportError:
        # Last-resort stub: bash returns "" when models.json missing/empty.
        # Keeps this module importable in isolation; real callers will have
        # one of the above available after the monolith merge.
        def _default_model(agent: str) -> str:  # noqa: D401
            return ""


def debate_probeCodex() -> str:
    """Probe codex CLI availability for the debate engine.

    Returns:
        - "" if codex is unusable (missing binary OR missing credentials).
        - The configured model name from models.json if available.
        - The literal "present" sentinel if codex is available but no model
          is configured for it in models.json.

    Behavior parity with bash `_probe_codex`:
        * `command -v codex`           -> shutil.which("codex")
        * `[[ -f $HOME/.codex/auth.json ]]` -> os.path.isfile(...)
        * `[[ -n $OPENAI_API_KEY ]]`   -> truthy env-var check
        * `_default_model codex`       -> _default_model("codex")
        * `printf '%s\\n' "${m:-present}"` -> return m or "present"
    """
    # Gate 1: binary must be on PATH.
    if shutil.which("codex") is None:
        return ""

    # Gate 2: at least one credential source must be present.
    home = os.environ.get("HOME", "")
    auth_path = os.path.join(home, ".codex", "auth.json")
    has_auth_file = bool(home) and os.path.isfile(auth_path)
    has_api_key = bool(os.environ.get("OPENAI_API_KEY", ""))
    if not (has_auth_file or has_api_key):
        return ""

    # Gate 3: resolve model name; fall back to "present" sentinel if empty.
    model: Optional[str] = _default_model("codex")
    return model if model else "present"
