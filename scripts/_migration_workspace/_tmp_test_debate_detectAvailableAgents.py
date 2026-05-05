"""RED-YELLOW-GREEN tests for debate_detectAvailableAgents.

Authored from intent + bash docstring (no paired _tests in monolith).
RELAXED_COVERAGE: name-map row tagged accordingly.

Bash source:
  detect_available_agents (jot-plugin-orchestrator.sh:2216-2238)
    AVAILABLE_AGENTS=(claude); GEMINI_MODEL=""; CODEX_MODEL=""
    parallel _probe_gemini / _probe_codex via tmpdir files
    if non-empty gemini: append "gemini", set GEMINI_MODEL unless "present"
    if non-empty codex:  append "codex",  set CODEX_MODEL  unless "present"

Python contract:
  Returns dict {
    "available": list[str],   # always starts with "claude"
    "gemini_model": str,      # "" if unavailable or only "present" sentinel
    "codex_model":  str,      # "" if unavailable or only "present" sentinel
  }
  Probes mocked at module boundary in _tmp_debate_detectAvailableAgents.
"""

import os
import sys
from unittest.mock import patch

# Wire workspace path so the SUT module is importable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _tmp_debate_detectAvailableAgents import debate_detectAvailableAgents


def test_only_claude_when_both_probes_unavailable():
    # Scenario: no gemini, no codex installed → only claude is available.
    # Setup: patch both probes at SUT module boundary to return "" (unavailable).
    with patch("_tmp_debate_detectAvailableAgents.debate_probeGemini", return_value=""), \
         patch("_tmp_debate_detectAvailableAgents.debate_probeCodex", return_value=""):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: claude-only list, both model strings empty.
    assert result["available"] == ["claude"]
    assert result["gemini_model"] == ""
    assert result["codex_model"] == ""


def test_gemini_with_real_model_appended_and_model_recorded():
    # Scenario: gemini probe returns a real model name → gemini joins list, model captured.
    # Setup: gemini probe returns concrete model; codex probe returns "" (unavailable).
    with patch("_tmp_debate_detectAvailableAgents.debate_probeGemini", return_value="gemini-2.5-pro"), \
         patch("_tmp_debate_detectAvailableAgents.debate_probeCodex", return_value=""):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: gemini joins after claude; model captured verbatim.
    assert result["available"] == ["claude", "gemini"]
    assert result["gemini_model"] == "gemini-2.5-pro"
    assert result["codex_model"] == ""


def test_gemini_present_sentinel_marks_available_but_leaves_model_blank():
    # Scenario: gemini probe returns "present" sentinel (binary+creds, no model configured).
    # Setup: probe returns literal "present"; codex unavailable.
    with patch("_tmp_debate_detectAvailableAgents.debate_probeGemini", return_value="present"), \
         patch("_tmp_debate_detectAvailableAgents.debate_probeCodex", return_value=""):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: gemini in list, but gemini_model is "" (sentinel suppressed).
    assert result["available"] == ["claude", "gemini"]
    assert result["gemini_model"] == ""


def test_codex_with_real_model_appended_and_model_recorded():
    # Scenario: codex probe returns a real model name → codex joins list, model captured.
    # Setup: gemini unavailable, codex returns concrete model.
    with patch("_tmp_debate_detectAvailableAgents.debate_probeGemini", return_value=""), \
         patch("_tmp_debate_detectAvailableAgents.debate_probeCodex", return_value="gpt-5-codex"):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: codex joins after claude; model captured verbatim.
    assert result["available"] == ["claude", "codex"]
    assert result["codex_model"] == "gpt-5-codex"
    assert result["gemini_model"] == ""


def test_codex_present_sentinel_marks_available_but_leaves_model_blank():
    # Scenario: codex probe returns "present" sentinel.
    # Setup: gemini unavailable, codex returns literal "present".
    with patch("_tmp_debate_detectAvailableAgents.debate_probeGemini", return_value=""), \
         patch("_tmp_debate_detectAvailableAgents.debate_probeCodex", return_value="present"):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: codex available, codex_model blank (sentinel suppressed).
    assert result["available"] == ["claude", "codex"]
    assert result["codex_model"] == ""


def test_both_probes_available_preserves_order_claude_gemini_codex():
    # Scenario: both auxiliary agents usable → list order is claude, gemini, codex.
    # Setup: both probes return real model names.
    with patch("_tmp_debate_detectAvailableAgents.debate_probeGemini", return_value="gemini-2.5-pro"), \
         patch("_tmp_debate_detectAvailableAgents.debate_probeCodex", return_value="gpt-5-codex"):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: ordered list and both models captured.
    assert result["available"] == ["claude", "gemini", "codex"]
    assert result["gemini_model"] == "gemini-2.5-pro"
    assert result["codex_model"] == "gpt-5-codex"
