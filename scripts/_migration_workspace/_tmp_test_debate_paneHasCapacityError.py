"""RED-YELLOW-GREEN tests for debate_paneHasCapacityError.

RELAXED_COVERAGE: no paired bash _tests existed for `pane_has_capacity_error`;
behaviors derived from intent + bash body inspection (lines 2786-2798).
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

# Make the temp module importable.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _tmp_debate_paneHasCapacityError import debate_paneHasCapacityError


# ---------- codex agent ----------

def test_codex_capacity_marker_present_returns_truthy():
    # Scenario: codex pane shows the "at capacity" message in scrollback.
    # Setup: mock tmux_capturePane to return a buffer containing the marker.
    fake_capture = "some banner\nSelected model is at capacity\nmore output\n"
    # Test action: call debate_paneHasCapacityError for the codex agent.
    with patch(
        "_tmp_debate_paneHasCapacityError.tmux_capturePane",
        return_value=fake_capture,
    ) as m:
        result = debate_paneHasCapacityError("%7", "codex")
    # Test verification: result is truthy (bool(result) is True).
    assert bool(result) is True
    # And capture was requested with -S -200 scrollback to mirror bash.
    m.assert_called_once_with("%7", scrollback_lines=200)


def test_codex_overloaded_marker_present_returns_truthy():
    # Scenario: codex pane shows the secondary "model is overloaded" marker.
    # Setup: capture buffer contains only the second codex marker.
    fake_capture = "noise\nmodel is overloaded right now\nnoise\n"
    # Test action: probe codex for capacity error.
    with patch(
        "_tmp_debate_paneHasCapacityError.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%1", "codex")
    # Test verification: truthy bool indicates a capacity hit.
    assert bool(result) is True


def test_codex_no_marker_returns_falsy():
    # Scenario: codex pane shows healthy output, no capacity markers.
    # Setup: capture buffer with unrelated content.
    fake_capture = "all good\nready\n> _\n"
    # Test action: probe codex for capacity error.
    with patch(
        "_tmp_debate_paneHasCapacityError.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%1", "codex")
    # Test verification: result is falsy (bool() is False).
    assert bool(result) is False


# ---------- gemini agent ----------

def test_gemini_resource_exhausted_returns_truthy():
    # Scenario: gemini pane prints RESOURCE_EXHAUSTED quota error.
    # Setup: capture contains the gemini-specific marker.
    fake_capture = "ERROR: RESOURCE_EXHAUSTED please retry later\n"
    # Test action: probe gemini for capacity error.
    with patch(
        "_tmp_debate_paneHasCapacityError.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%2", "gemini")
    # Test verification: truthy bool indicates capacity hit.
    assert bool(result) is True


def test_gemini_marker_for_other_agent_does_not_match():
    # Scenario: pane shows codex-specific marker but agent arg is "gemini".
    # Setup: capture has codex marker text only; gemini markers should NOT match.
    fake_capture = "Selected model is at capacity\n"
    # Test action: probe gemini.
    with patch(
        "_tmp_debate_paneHasCapacityError.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%2", "gemini")
    # Test verification: per-agent markers are isolated -> falsy.
    assert bool(result) is False


# ---------- claude agent ----------

def test_claude_api_529_returns_truthy():
    # Scenario: claude pane prints HTTP 529 overload error.
    # Setup: capture contains "API Error: 529" marker.
    fake_capture = "request failed: API Error: 529 overloaded_error: please retry\n"
    # Test action: probe claude.
    with patch(
        "_tmp_debate_paneHasCapacityError.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%3", "claude")
    # Test verification: truthy bool.
    assert bool(result) is True


# ---------- unknown agent ----------

def test_unknown_agent_returns_falsy_without_capturing():
    # Scenario: caller passes an unrecognised agent name.
    # Setup: patch tmux_capturePane so we can assert it is NEVER called
    # (mirrors bash: empty marker stream -> while-loop body never executes,
    # function returns 1 with no side effects).
    with patch(
        "_tmp_debate_paneHasCapacityError.tmux_capturePane",
        return_value="API Error: 529\n",
    ) as m:
        # Test action: probe with a bogus agent.
        result = debate_paneHasCapacityError("%9", "nonsense-agent")
    # Test verification: falsy AND tmux capture not invoked.
    assert bool(result) is False
    assert m.call_count == 0


# ---------- ANSI escape stripping ----------

def test_ansi_escape_bytes_are_stripped_before_match():
    # Scenario: pane capture is interleaved with raw ESC bytes (\033) the way
    # tmux emits color codes; bash uses `tr -d '\033'` before grep -F.
    # Setup: insert ESC bytes inside the marker so a naive substring search
    # against the unstripped buffer would FAIL.
    marker = "API Error: 529"
    poisoned = "API\033 Error:\033 529"  # same chars, ESC interleaved
    fake_capture = f"prefix {poisoned} suffix\n"
    # Test action: probe claude.
    with patch(
        "_tmp_debate_paneHasCapacityError.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%4", "claude")
    # Test verification: ESC stripping lets the marker match -> truthy.
    assert bool(result) is True
    # And the matched marker text is the canonical (ESC-free) string.
    assert result == marker


# ---------- empty capture ----------

def test_empty_capture_returns_falsy():
    # Scenario: tmux capture-pane fails or pane has no output (returns "").
    # Setup: tmux_capturePane returns empty string (its documented failure mode).
    # Test action: probe codex.
    with patch(
        "_tmp_debate_paneHasCapacityError.tmux_capturePane",
        return_value="",
    ):
        result = debate_paneHasCapacityError("%5", "codex")
    # Test verification: nothing to match -> falsy.
    assert bool(result) is False
