"""GREEN implementation of debate_detectAvailableAgents.

Migrated from bash `detect_available_agents` (jot-plugin-orchestrator.sh:2216-2238).
Debate-scoped helper.

YELLOW intent (plain English):
  Determine which debate agents the current environment can actually run.
  Claude is assumed always usable. Gemini and codex each have a probe that
  returns "" when unavailable, a model name when ready, or the literal
  "present" sentinel when the binary+credentials exist but no model is
  configured. Run both probes in parallel (matches bash backgrounded
  subshells) and aggregate results into a single dict:
    - available: list of agent names, claude first, then any usable
      auxiliaries in fixed order (gemini before codex).
    - gemini_model / codex_model: model name when probe returned a real
      model; empty string when unavailable OR when probe returned the
      "present" sentinel (sentinel marks availability without a model).

  Returning a dict (instead of mutating bash globals AVAILABLE_AGENTS /
  GEMINI_MODEL / CODEX_MODEL) is the Python-side contract; callers
  destructure as needed. Concurrency uses ThreadPoolExecutor since the
  probes are I/O-bound (filesystem stat + PATH lookup).
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import TypedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Resolve probe deps. Prefer merged monolith; fall back to workspace stubs.
# Tests patch these names on THIS module, so the import-time binding here
# is what unittest.mock.patch rewrites.
try:
    from jot_plugin_orchestrator import debate_probeGemini  # type: ignore
except ImportError:
    from _tmp_debate_probeGemini import debate_probeGemini  # type: ignore

try:
    from jot_plugin_orchestrator import debate_probeCodex  # type: ignore
except ImportError:
    from _tmp_debate_probeCodex import debate_probeCodex  # type: ignore


class DetectResult(TypedDict):
    """Aggregate result of agent detection.

    Attributes:
        available: Ordered list of usable agent names (claude always first).
        gemini_model: Model string for gemini, or "" if unavailable / sentinel.
        codex_model: Model string for codex, or "" if unavailable / sentinel.
    """
    available: list[str]
    gemini_model: str
    codex_model: str


# Sentinel returned by probes when binary+credentials exist but no model is
# configured. Marks the agent as available without populating a model name.
_PRESENT_SENTINEL = "present"


def debate_detectAvailableAgents() -> DetectResult:
    """Detect which debate agents are usable; return aggregate dict.

    Probes gemini and codex concurrently (I/O-bound: PATH + filesystem).
    Claude is always treated as available — no probe required.

    Returns:
        DetectResult with `available` list and per-agent model fields.

    Behavior parity with bash `detect_available_agents`:
        AVAILABLE_AGENTS starts with [claude]; gemini/codex appended only
        when their probe returns non-empty. Model fields stay "" if probe
        returned "" OR the "present" sentinel.
    """
    # Run both probes in parallel; ThreadPoolExecutor matches bash's two
    # backgrounded subshells joined by `wait`.
    with ThreadPoolExecutor(max_workers=2) as pool:
        gemini_future = pool.submit(debate_probeGemini)
        codex_future = pool.submit(debate_probeCodex)
        gemini_out = gemini_future.result()
        codex_out = codex_future.result()

    # Claude is always available — no probe.
    available: list[str] = ["claude"]
    gemini_model = ""
    codex_model = ""

    # Non-empty probe output ⇒ agent is usable. Capture model only when
    # the output is a real model name (not the "present" sentinel).
    if gemini_out:
        available.append("gemini")
        if gemini_out != _PRESENT_SENTINEL:
            gemini_model = gemini_out

    if codex_out:
        available.append("codex")
        if codex_out != _PRESENT_SENTINEL:
            codex_model = codex_out

    return {
        "available": available,
        "gemini_model": gemini_model,
        "codex_model": codex_model,
    }
