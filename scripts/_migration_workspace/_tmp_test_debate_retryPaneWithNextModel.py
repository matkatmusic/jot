"""RED tests for debate_retryPaneWithNextModel.

Migrated from bash retry_pane_with_next_model (jot-plugin-orchestrator.sh ~L2896).
No paired bash _tests existed; behavior derived from function body.
RELAXED_COVERAGE: intent + docstring driven.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# Workspace path setup mirrors the plan's import block.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp_debate_retryPaneWithNextModel import debate_retryPaneWithNextModel  # noqa: E402

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# RED test 1 -- no remaining models -> returns None
# ---------------------------------------------------------------------------
def test_no_next_model_returns_none():
    # Scenario: _next_model exhausted; no models left for agent.
    # Setup: debate_nextModel returns None.
    # Test action: call debate_retryPaneWithNextModel.
    # Test verification: returns None; no pane kill or creation attempted.
    with (
        patch(
            "_tmp_debate_retryPaneWithNextModel.debate_nextModel",
            return_value=None,
        ) as mock_next,
        patch(
            "_tmp_debate_retryPaneWithNextModel.debate_newEmptyPane"
        ) as mock_new_pane,
    ):
        result = debate_retryPaneWithNextModel(**_BASE_KWARGS)

    assert result is None
    mock_new_pane.assert_not_called()


# ---------------------------------------------------------------------------
# RED test 2 -- happy path: updates tried_models and current_model dicts
# ---------------------------------------------------------------------------
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
            "_tmp_debate_retryPaneWithNextModel.debate_nextModel",
            return_value="gemini-flash",
        ),
        patch(
            "_tmp_debate_retryPaneWithNextModel.debate_newEmptyPane",
            return_value="%11",
        ),
        patch(
            "_tmp_debate_retryPaneWithNextModel.debate_agentLaunchCmd",
            return_value="gemini --model gemini-flash",
        ),
        patch("_tmp_debate_retryPaneWithNextModel._kill_pane"),
        patch("_tmp_debate_retryPaneWithNextModel._launch_agent", return_value=True),
        patch("_tmp_debate_retryPaneWithNextModel._send_prompt", return_value=True),
    ):
        kwargs = dict(_BASE_KWARGS)
        kwargs["current_model"] = current_model
        kwargs["tried_models"] = tried_models
        debate_retryPaneWithNextModel(**kwargs)

    assert current_model["gemini"] == "gemini-flash"
    assert "gemini-flash" in tried_models["gemini"]


# ---------------------------------------------------------------------------
# RED test 3 -- happy path: kills old pane and returns new pane id
# ---------------------------------------------------------------------------
def test_kills_old_pane_returns_new_pane_id():
    # Scenario: successful rotation; old pane killed, new pane id returned.
    # Setup: debate_nextModel = "gemini-flash"; debate_newEmptyPane = "%99".
    # Test action: call debate_retryPaneWithNextModel.
    # Test verification: _kill_pane called with "%10"; return value == "%99".
    kill_mock = MagicMock()

    with (
        patch(
            "_tmp_debate_retryPaneWithNextModel.debate_nextModel",
            return_value="gemini-flash",
        ),
        patch(
            "_tmp_debate_retryPaneWithNextModel.debate_newEmptyPane",
            return_value="%99",
        ),
        patch(
            "_tmp_debate_retryPaneWithNextModel.debate_agentLaunchCmd",
            return_value="gemini --model gemini-flash",
        ),
        patch(
            "_tmp_debate_retryPaneWithNextModel._kill_pane", kill_mock
        ),
        patch("_tmp_debate_retryPaneWithNextModel._launch_agent", return_value=True),
        patch("_tmp_debate_retryPaneWithNextModel._send_prompt", return_value=True),
    ):
        result = debate_retryPaneWithNextModel(**_BASE_KWARGS)

    kill_mock.assert_called_once_with("%10")
    assert result == "%99"


# ---------------------------------------------------------------------------
# RED test 4 -- launch_agent failure propagates as None
# ---------------------------------------------------------------------------
def test_launch_agent_failure_returns_none():
    # Scenario: new pane created but agent fails to become ready.
    # Setup: _launch_agent returns False.
    # Test action: call debate_retryPaneWithNextModel.
    # Test verification: returns None (mirrors bash `return 1`).
    with (
        patch(
            "_tmp_debate_retryPaneWithNextModel.debate_nextModel",
            return_value="gemini-flash",
        ),
        patch(
            "_tmp_debate_retryPaneWithNextModel.debate_newEmptyPane",
            return_value="%11",
        ),
        patch(
            "_tmp_debate_retryPaneWithNextModel.debate_agentLaunchCmd",
            return_value="gemini --model gemini-flash",
        ),
        patch("_tmp_debate_retryPaneWithNextModel._kill_pane"),
        patch(
            "_tmp_debate_retryPaneWithNextModel._launch_agent", return_value=False
        ),
        patch("_tmp_debate_retryPaneWithNextModel._send_prompt", return_value=True),
    ):
        result = debate_retryPaneWithNextModel(**_BASE_KWARGS)

    assert result is None


# ---------------------------------------------------------------------------
# RED test 5 -- send_prompt failure propagates as None
# ---------------------------------------------------------------------------
def test_send_prompt_failure_returns_none():
    # Scenario: agent launched fine but prompt delivery timed out.
    # Setup: _launch_agent True; _send_prompt returns False.
    # Test action: call debate_retryPaneWithNextModel.
    # Test verification: returns None.
    with (
        patch(
            "_tmp_debate_retryPaneWithNextModel.debate_nextModel",
            return_value="gemini-flash",
        ),
        patch(
            "_tmp_debate_retryPaneWithNextModel.debate_newEmptyPane",
            return_value="%11",
        ),
        patch(
            "_tmp_debate_retryPaneWithNextModel.debate_agentLaunchCmd",
            return_value="gemini --model gemini-flash",
        ),
        patch("_tmp_debate_retryPaneWithNextModel._kill_pane"),
        patch("_tmp_debate_retryPaneWithNextModel._launch_agent", return_value=True),
        patch(
            "_tmp_debate_retryPaneWithNextModel._send_prompt", return_value=False
        ),
    ):
        result = debate_retryPaneWithNextModel(**_BASE_KWARGS)

    assert result is None


# ---------------------------------------------------------------------------
# RED test 6 -- tried_models entry created from scratch when agent not present
# ---------------------------------------------------------------------------
def test_tried_models_created_when_agent_missing():
    # Scenario: agent key absent from tried_models (first rotation ever).
    # Setup: tried_models = {} (empty); next model = "codex-mini".
    # Test action: call with agent="codex", tried_models={}.
    # Test verification: tried_models["codex"] contains "codex-mini".
    current_model: dict[str, str] = {}
    tried_models: dict[str, str] = {}

    with (
        patch(
            "_tmp_debate_retryPaneWithNextModel.debate_nextModel",
            return_value="codex-mini",
        ),
        patch(
            "_tmp_debate_retryPaneWithNextModel.debate_newEmptyPane",
            return_value="%20",
        ),
        patch(
            "_tmp_debate_retryPaneWithNextModel.debate_agentLaunchCmd",
            return_value="codex -a never",
        ),
        patch("_tmp_debate_retryPaneWithNextModel._kill_pane"),
        patch("_tmp_debate_retryPaneWithNextModel._launch_agent", return_value=True),
        patch("_tmp_debate_retryPaneWithNextModel._send_prompt", return_value=True),
    ):
        kwargs = dict(_BASE_KWARGS)
        kwargs["agent"] = "codex"
        kwargs["current_pane_id"] = "%5"
        kwargs["current_model"] = current_model
        kwargs["tried_models"] = tried_models
        debate_retryPaneWithNextModel(**kwargs)

    assert "codex-mini" in tried_models.get("codex", "")
    assert current_model.get("codex") == "codex-mini"
