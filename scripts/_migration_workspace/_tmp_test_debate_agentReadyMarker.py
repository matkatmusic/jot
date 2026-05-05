"""RED tests for debate_agentReadyMarker (RELAXED_COVERAGE: no paired bash _tests).

Tests authored from intent + bash source: the function maps a known agent
name to the literal substring that appears in its pane when ready.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp_debate_agentReadyMarker import debate_agentReadyMarker


def test_gemini_marker():
    # Scenario: gemini agent boots and shows its REPL prompt.
    # Setup: agent name is the literal "gemini".
    # Test action: query the ready marker.
    # Test verification: returns gemini's exact prompt substring.
    agent = "gemini"
    result = debate_agentReadyMarker(agent)
    assert result == "Type your message or @path/to/file"


def test_codex_marker():
    # Scenario: codex agent finishes boot and shows model-selector hint.
    # Setup: agent name is the literal "codex".
    # Test action: query the ready marker.
    # Test verification: returns codex's exact ready-line substring.
    agent = "codex"
    result = debate_agentReadyMarker(agent)
    assert result == "/model to change"


def test_claude_marker():
    # Scenario: claude CLI prints its banner once ready.
    # Setup: agent name is the literal "claude".
    # Test action: query the ready marker.
    # Test verification: returns the banner prefix used by orchestrator grep.
    agent = "claude"
    result = debate_agentReadyMarker(agent)
    assert result == "Claude Code v"


def test_unknown_agent_returns_empty_string():
    # Scenario: caller passes an agent name not in the case statement.
    # Setup: arbitrary unknown agent identifier.
    # Test action: query the ready marker.
    # Test verification: empty string (bash case has no default branch).
    agent = "bogus"
    result = debate_agentReadyMarker(agent)
    assert result == ""


def test_empty_string_agent_returns_empty_string():
    # Scenario: defensive call with empty agent name.
    # Setup: empty string as agent identifier.
    # Test action: query the ready marker.
    # Test verification: empty string returned, no exception raised.
    agent = ""
    result = debate_agentReadyMarker(agent)
    assert result == ""
