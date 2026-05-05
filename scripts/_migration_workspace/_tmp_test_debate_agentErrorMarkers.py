"""RED tests for debate_agentErrorMarkers (migrated from bash agent_error_markers).

Authored from intent (no paired bash _tests). RELAXED_COVERAGE.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _tmp_debate_agentErrorMarkers import debate_agentErrorMarkers


def test_codex_returns_capacity_and_overload_markers():
    # Scenario: codex agent has two known capacity-class error strings
    # Setup: agent name 'codex'
    # Test action: call debate_agentErrorMarkers('codex')
    # Test verification: returns exact ordered list of two markers
    result = debate_agentErrorMarkers("codex")
    assert result == ["Selected model is at capacity", "model is overloaded"]


def test_gemini_returns_quota_markers_in_order():
    # Scenario: gemini agent has three quota/exhaustion markers
    # Setup: agent name 'gemini'
    # Test action: call debate_agentErrorMarkers('gemini')
    # Test verification: returns the three markers in bash printf order
    result = debate_agentErrorMarkers("gemini")
    assert result == [
        "RESOURCE_EXHAUSTED",
        "Quota exceeded",
        "You exceeded your current quota",
    ]


def test_claude_returns_overload_markers():
    # Scenario: claude agent has 529/overloaded markers
    # Setup: agent name 'claude'
    # Test action: call debate_agentErrorMarkers('claude')
    # Test verification: returns exactly the two claude markers
    result = debate_agentErrorMarkers("claude")
    assert result == ["API Error: 529", "overloaded_error"]


def test_unknown_agent_returns_empty_list():
    # Scenario: bash case has no default branch -> no output
    # Setup: agent name not in {codex, gemini, claude}
    # Test action: call with unknown agent
    # Test verification: empty list (Python equivalent of empty stdout)
    assert debate_agentErrorMarkers("bogus") == []


def test_empty_string_agent_returns_empty_list():
    # Scenario: empty argument falls through case with no match
    # Setup: agent name ''
    # Test action: call with empty string
    # Test verification: empty list
    assert debate_agentErrorMarkers("") == []


def test_result_is_list_type():
    # Scenario: callers iterate markers (see pane_has_capacity_error loop)
    # Setup: any valid agent
    # Test action: check return type
    # Test verification: list (mutable sequence) so callers can iterate safely
    assert isinstance(debate_agentErrorMarkers("codex"), list)
