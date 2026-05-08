"""Tests for debate_lib -- capacity bucket (agentReadyMarker, agentErrorMarkers, paneHasCapacityError, nextModel, retryPaneWithNextModel, waitForOutputs+capacity)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from common.scripts.debate_lib import (
    debate_agentErrorMarkers,
    debate_agentReadyMarker,
    debate_nextModel,
    debate_paneHasCapacityError,
    debate_retryPaneWithNextModel,
    debate_waitForOutputs,
)


# =====================================================================
# debate_agentReadyMarker tests
# =====================================================================


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


# =====================================================================
# debate_agentErrorMarkers tests
# =====================================================================


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


# =====================================================================
# debate_nextModel tests
# =====================================================================


@pytest.fixture
def models_file(tmp_path: Path) -> Path:
    # Setup: typical models.json shape per assets/models.json.
    p = tmp_path / "models.json"
    p.write_text(json.dumps({
        "gemini": ["gem-pro", "gem-flash", "gem-lite"],
        "codex":  ["gpt-a", "gpt-b"],
        "claude": ["c-opus", "c-sonnet"],
    }))
    return p


def test_returns_first_model_when_none_tried(models_file: Path) -> None:
    # Scenario: no models tried yet for an agent.
    # Setup: empty TRIED_MODELS entry for "gemini".
    tried = {"gemini": "", "codex": "", "claude": ""}
    # Test action: ask for next model for gemini.
    result = debate_nextModel("gemini", tried, str(models_file))
    # Test verification: first model in list is returned.
    assert result == "gem-pro"


def test_skips_already_tried_models(models_file: Path) -> None:
    # Scenario: first two gemini models already tried.
    # Setup: comma-joined tried list matching bash idiom ",a,b,".
    tried = {"gemini": "gem-pro,gem-flash", "codex": "", "claude": ""}
    # Test action: request next model.
    result = debate_nextModel("gemini", tried, str(models_file))
    # Test verification: third model returned.
    assert result == "gem-lite"


def test_returns_none_when_all_tried(models_file: Path) -> None:
    # Scenario: every model in the list has been tried.
    # Setup: tried list contains all gemini entries.
    tried = {"gemini": "gem-pro,gem-flash,gem-lite", "codex": "", "claude": ""}
    # Test action: request next model.
    result = debate_nextModel("gemini", tried, str(models_file))
    # Test verification: bash returned rc=1; Python returns None.
    assert result is None


def test_unknown_agent_returns_none(models_file: Path) -> None:
    # Scenario: agent key absent from models.json.
    # Setup: tried dict has agent but JSON does not.
    tried = {"mystery": ""}
    # Test action: request next model for unknown agent.
    result = debate_nextModel("mystery", tried, str(models_file))
    # Test verification: no model available -> None.
    assert result is None


def test_partial_tried_with_leading_comma(models_file: Path) -> None:
    # Scenario: tried list has bash-style leading comma artifact (",first").
    # Setup: tried entry mimics how _stash appends (",${next}").
    tried = {"codex": ",gpt-a"}
    # Test action: request next codex model.
    result = debate_nextModel("codex", tried, str(models_file))
    # Test verification: gpt-a is skipped, gpt-b returned.
    assert result == "gpt-b"


def test_missing_models_file_returns_none(tmp_path: Path) -> None:
    # Scenario: models.json path does not exist.
    # Setup: point at nonexistent file (bash hide_errors -> empty stdin -> rc=1).
    tried = {"gemini": ""}
    # Test action: request next model.
    result = debate_nextModel("gemini", tried, str(tmp_path / "missing.json"))
    # Test verification: graceful None.
    assert result is None


# =====================================================================
# debate_paneHasCapacityError tests
# =====================================================================


# ---------- codex agent ----------

def test_codex_capacity_marker_present_returns_truthy():
    # Scenario: codex pane shows the "at capacity" message in scrollback.
    # Setup: mock tmux_capturePane to return a buffer containing the marker.
    fake_capture = "some banner\nSelected model is at capacity\nmore output\n"
    # Test action: call debate_paneHasCapacityError for the codex agent.
    with patch(
        "common.scripts.debate_lib.tmux_capturePane",
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
        "common.scripts.debate_lib.tmux_capturePane",
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
        "common.scripts.debate_lib.tmux_capturePane",
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
        "common.scripts.debate_lib.tmux_capturePane",
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
        "common.scripts.debate_lib.tmux_capturePane",
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
        "common.scripts.debate_lib.tmux_capturePane",
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
        "common.scripts.debate_lib.tmux_capturePane",
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
        "common.scripts.debate_lib.tmux_capturePane",
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
        "common.scripts.debate_lib.tmux_capturePane",
        return_value="",
    ):
        result = debate_paneHasCapacityError("%5", "codex")
    # Test verification: nothing to match -> falsy.
    assert bool(result) is False


# =====================================================================
# debate_retryPaneWithNextModel tests [capacity -- model rotation / pane rotation]
# =====================================================================


_BASE_KWARGS = dict(
    pane_index=0,
    agent="gemini",
    stage="r1",
    current_pane_id="%10",
    current_model={"gemini": "gemini-pro"},
    tried_models={"gemini": "gemini-pro"},
    window_target="debate:0",
    cwd="/tmp/cwd",
    repo_root="/tmp/repo",
    home="/tmp/home",
    settings_file="/tmp/settings.json",
    debate_dir="/tmp/debate",
    models_json_path="/tmp/models.json",
)


def test_no_next_model_returns_none():
    # Scenario: _next_model exhausted; no models left for agent.
    # Setup: debate_nextModel returns None.
    # Test action: call debate_retryPaneWithNextModel.
    # Test verification: returns None; no pane kill or creation attempted.
    with (
        patch(
            "common.scripts.debate_lib.debate_nextModel",
            return_value=None,
        ) as mock_next,
        patch(
            "common.scripts.debate_lib.debate_newEmptyPane"
        ) as mock_new_pane,
    ):
        result = debate_retryPaneWithNextModel(**_BASE_KWARGS)

    assert result is None
    mock_new_pane.assert_not_called()


def test_updates_model_dicts_on_success():
    # Scenario: next model found; dicts should reflect new model after call.
    # Setup: debate_nextModel returns "gemini-flash"; launch + prompt succeed.
    # Test action: call with mutable dicts; check mutations after.
    # Test verification: current_model["gemini"] == "gemini-flash";
    #                    "gemini-flash" appended to tried_models["gemini"].
    current_model = {"gemini": "gemini-pro"}
    tried_models = {"gemini": "gemini-pro"}

    with (
        patch(
            "common.scripts.debate_lib.debate_nextModel",
            return_value="gemini-flash",
        ),
        patch(
            "common.scripts.debate_lib.debate_newEmptyPane",
            return_value="%11",
        ),
        patch(
            "common.scripts.debate_lib.debate_agentLaunchCmd",
            return_value="gemini --model gemini-flash",
        ),
        patch("common.scripts.debate_lib._kill_pane"),
        patch("common.scripts.debate_lib._launch_agent", return_value=True),
        patch("common.scripts.debate_lib._send_prompt", return_value=True),
    ):
        kwargs = dict(_BASE_KWARGS)
        kwargs["current_model"] = current_model
        kwargs["tried_models"] = tried_models
        debate_retryPaneWithNextModel(**kwargs)

    assert current_model["gemini"] == "gemini-flash"
    assert "gemini-flash" in tried_models["gemini"]


def test_kills_old_pane_returns_new_pane_id():
    # Scenario: successful rotation; old pane killed, new pane id returned.
    # Setup: debate_nextModel = "gemini-flash"; debate_newEmptyPane = "%99".
    # Test action: call debate_retryPaneWithNextModel.
    # Test verification: _kill_pane called with "%10"; return value == "%99".
    kill_mock = MagicMock()

    with (
        patch(
            "common.scripts.debate_lib.debate_nextModel",
            return_value="gemini-flash",
        ),
        patch(
            "common.scripts.debate_lib.debate_newEmptyPane",
            return_value="%99",
        ),
        patch(
            "common.scripts.debate_lib.debate_agentLaunchCmd",
            return_value="gemini --model gemini-flash",
        ),
        patch(
            "common.scripts.debate_lib._kill_pane", kill_mock
        ),
        patch("common.scripts.debate_lib._launch_agent", return_value=True),
        patch("common.scripts.debate_lib._send_prompt", return_value=True),
    ):
        result = debate_retryPaneWithNextModel(**_BASE_KWARGS)

    kill_mock.assert_called_once_with("%10")
    assert result == "%99"


def test_launch_agent_failure_returns_none():
    # Scenario: new pane created but agent fails to become ready.
    # Setup: _launch_agent returns False.
    # Test action: call debate_retryPaneWithNextModel.
    # Test verification: returns None (mirrors bash `return 1`).
    with (
        patch(
            "common.scripts.debate_lib.debate_nextModel",
            return_value="gemini-flash",
        ),
        patch(
            "common.scripts.debate_lib.debate_newEmptyPane",
            return_value="%11",
        ),
        patch(
            "common.scripts.debate_lib.debate_agentLaunchCmd",
            return_value="gemini --model gemini-flash",
        ),
        patch("common.scripts.debate_lib._kill_pane"),
        patch(
            "common.scripts.debate_lib._launch_agent", return_value=False
        ),
        patch("common.scripts.debate_lib._send_prompt", return_value=True),
    ):
        result = debate_retryPaneWithNextModel(**_BASE_KWARGS)

    assert result is None


def test_send_prompt_failure_returns_none():
    # Scenario: agent launched fine but prompt delivery timed out.
    # Setup: _launch_agent True; _send_prompt returns False.
    # Test action: call debate_retryPaneWithNextModel.
    # Test verification: returns None.
    with (
        patch(
            "common.scripts.debate_lib.debate_nextModel",
            return_value="gemini-flash",
        ),
        patch(
            "common.scripts.debate_lib.debate_newEmptyPane",
            return_value="%11",
        ),
        patch(
            "common.scripts.debate_lib.debate_agentLaunchCmd",
            return_value="gemini --model gemini-flash",
        ),
        patch("common.scripts.debate_lib._kill_pane"),
        patch("common.scripts.debate_lib._launch_agent", return_value=True),
        patch(
            "common.scripts.debate_lib._send_prompt", return_value=False
        ),
    ):
        result = debate_retryPaneWithNextModel(**_BASE_KWARGS)

    assert result is None


def test_tried_models_created_when_agent_missing():
    # Scenario: agent key absent from tried_models (first rotation ever).
    # Setup: tried_models = {} (empty); next model = "codex-mini".
    # Test action: call with agent="codex", tried_models={}.
    # Test verification: tried_models["codex"] contains "codex-mini".
    current_model: dict[str, str] = {}
    tried_models: dict[str, str] = {}

    with (
        patch(
            "common.scripts.debate_lib.debate_nextModel",
            return_value="codex-mini",
        ),
        patch(
            "common.scripts.debate_lib.debate_newEmptyPane",
            return_value="%20",
        ),
        patch(
            "common.scripts.debate_lib.debate_agentLaunchCmd",
            return_value="codex -a never",
        ),
        patch("common.scripts.debate_lib._kill_pane"),
        patch("common.scripts.debate_lib._launch_agent", return_value=True),
        patch("common.scripts.debate_lib._send_prompt", return_value=True),
    ):
        kwargs = dict(_BASE_KWARGS)
        kwargs["agent"] = "codex"
        kwargs["current_pane_id"] = "%5"
        kwargs["current_model"] = current_model
        kwargs["tried_models"] = tried_models
        debate_retryPaneWithNextModel(**kwargs)

    assert "codex-mini" in tried_models.get("codex", "")
    assert current_model.get("codex") == "codex-mini"


# =====================================================================
# debate_waitForOutputs capacity-error retry [capacity]
# =====================================================================


def test_invokes_retry_when_pane_has_capacity_error_and_no_output(tmp_path):
    # Scenario: agent pane shows capacity error and no output file exists yet
    # Setup: no output files; capacity_check returns True for one agent
    agents = ["gemini"]
    panes = {0: "%5"}
    retry_cb = MagicMock()
    sleep_fn = MagicMock()
    # Test action: single poll iteration before timeout
    ok, _, reason = debate_waitForOutputs(
        prefix="r1", timeout=5, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=lambda p, a: True,
        retry_pane=retry_cb, sleep_fn=sleep_fn, poll_interval=5,
    )
    # Test verification: retry callback invoked with (panes, index, agent, prefix)
    assert ok is False
    assert reason is not None
    retry_cb.assert_called_once()
    args = retry_cb.call_args[0]
    assert args[1] == 0  # index
    assert args[2] == "gemini"
    assert args[3] == "r1"
