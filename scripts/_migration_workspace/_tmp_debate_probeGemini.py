"""GREEN implementation of debate_probeGemini.

Migrated from bash `_probe_gemini` (jot-plugin-orchestrator.sh:2196-2206).
Debate-scoped helper (per plan inventory).

YELLOW intent (plain English):
  Decide whether the gemini CLI agent is usable in this environment, and
  if so report which model name to drive it with. Three sequential gates:
    1. Is the `gemini` executable on PATH? If not, return "" (unavailable).
    2. Are credentials present? Either the oauth creds file
       ~/.gemini/oauth_creds.json exists, OR GEMINI_API_KEY is set in env,
       OR GOOGLE_API_KEY is set. If none, return "" (unavailable).
    3. Look up the configured launch model via _default_model("gemini").
       If non-empty, return it. If empty (no model configured for gemini),
       return the literal sentinel "present" so callers checking
       truthy/non-empty still see the agent as available.

  Empty string ("") is the universal "unavailable" signal — caller's
  `if [ -s "$tmpdir/gemini" ]` test uses non-empty as the available flag.
"""

import os
import shutil
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Dependency: _default_model. Try migrated module first, then workspace stub.
try:
    from jot_plugin_orchestrator import debate_defaultModel as _default_model  # type: ignore
except ImportError:
    try:
        from _tmp_debate_defaultModel import debate_defaultModel as _default_model  # type: ignore
    except ImportError:
        def _default_model(agent: str) -> str:  # type: ignore[misc]
            """Fallback stub used until debate_defaultModel is migrated.

            Returns empty string so the "present" sentinel path is taken.
            Real implementation reads models.json; tests patch this symbol.
            """
            return ""


def debate_probeGemini() -> str:
    """Probe whether the gemini agent is usable; return model name or "".

    Returns:
        - "" when gemini is unavailable (binary missing OR no credentials).
        - The configured model name (e.g., "gemini-2.5-pro") when ready.
        - "present" sentinel when binary + creds exist but no model is
          configured in models.json — caller still treats agent as usable.

    Behavior parity with bash `_probe_gemini`:
        Gate 1: `command -v gemini` must succeed.
        Gate 2: ~/.gemini/oauth_creds.json OR GEMINI_API_KEY OR GOOGLE_API_KEY.
        Gate 3: model = _default_model("gemini"); return model or "present".
    """
    # Gate 1: binary on PATH. shutil.which mirrors `command -v`.
    if shutil.which("gemini") is None:
        return ""

    # Gate 2: at least one credential source present. Order matches bash:
    # oauth file first (most common), then env vars.
    oauth_path = os.path.join(os.path.expanduser("~"), ".gemini", "oauth_creds.json")
    has_oauth = os.path.isfile(oauth_path)
    has_gemini_key = bool(os.environ.get("GEMINI_API_KEY", ""))
    has_google_key = bool(os.environ.get("GOOGLE_API_KEY", ""))
    if not (has_oauth or has_gemini_key or has_google_key):
        return ""

    # Gate 3: resolve model name; fall back to "present" sentinel so the
    # caller's non-empty check still flags gemini as available.
    model = _default_model("gemini")
    return model if model else "present"
