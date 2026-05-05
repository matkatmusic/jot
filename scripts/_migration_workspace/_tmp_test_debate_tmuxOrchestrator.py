"""Tests for debate_tmuxOrchestrator workspace migration.

RED-YELLOW-GREEN TDD.
All callees (cleanup, daemon_main) are mocked at module boundary.
No bash _tests paired file exists; tests authored from intent + bash docstring.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from _tmp_debate_tmuxOrchestrator import DebateContext, debate_tmuxOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_kwargs(**overrides: object) -> dict:
    """Return a minimal valid call-site kwargs dict."""
    base: dict = dict(
        debate_dir="/tmp/debate",
        session="jot",
        window_name="debate",
        settings_file="/tmp/settings.json",
        cwd="/tmp/repo",
        repo_root="/tmp/repo",
        plugin_root="/tmp/plugin",
        debate_agents="claude gemini",
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_raises_when_session_empty() -> None:
    # Scenario: caller passes empty SESSION; orchestrator must abort like bash `:?` guard.
    # Setup: all args valid except session="".
    # Test action: call debate_tmuxOrchestrator with session="".
    # Test verification: ValueError raised with "SESSION required".
    with pytest.raises(ValueError, match="SESSION required"):
        debate_tmuxOrchestrator(**_valid_kwargs(session=""))


def test_raises_when_debate_agents_empty_and_no_env() -> None:
    # Scenario: caller passes empty debate_agents and env var absent; must abort.
    # Setup: no DEBATE_AGENTS env var, debate_agents="".
    # Test action: call with debate_agents="".
    # Test verification: ValueError raised with "DEBATE_AGENTS".
    env = {k: v for k, v in os.environ.items() if k != "DEBATE_AGENTS"}
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValueError, match="DEBATE_AGENTS"):
            debate_tmuxOrchestrator(**_valid_kwargs(debate_agents=""))


def test_debate_agents_falls_back_to_env() -> None:
    # Scenario: debate_agents="" but DEBATE_AGENTS env var is set; orchestrator uses env value.
    # Setup: inject mock daemon_main and cleanup; set DEBATE_AGENTS env.
    # Test action: call with debate_agents="".
    # Test verification: daemon_main called once; ctx.agents matches env value.
    mock_daemon = MagicMock()
    mock_cleanup = MagicMock()
    with patch.dict(os.environ, {"DEBATE_AGENTS": "claude codex"}, clear=False):
        debate_tmuxOrchestrator(
            **_valid_kwargs(debate_agents=""),
            daemon_main_fn=mock_daemon,
            cleanup_fn=mock_cleanup,
        )
    ctx: DebateContext = mock_daemon.call_args[0][0]
    assert ctx.agents == ["claude", "codex"]


def test_window_target_composed_from_session_and_window_name() -> None:
    # Scenario: window_target must be "SESSION:WINDOW_NAME" matching bash `WINDOW_TARGET="${SESSION}:${WINDOW_NAME}"`.
    # Setup: inject mock daemon_main; pass distinct session and window_name.
    # Test action: call debate_tmuxOrchestrator with session="mysession" window_name="mywin".
    # Test verification: ctx.window_target == "mysession:mywin".
    mock_daemon = MagicMock()
    debate_tmuxOrchestrator(
        **_valid_kwargs(session="mysession", window_name="mywin"),
        daemon_main_fn=mock_daemon,
        cleanup_fn=MagicMock(),
    )
    ctx: DebateContext = mock_daemon.call_args[0][0]
    assert ctx.window_target == "mysession:mywin"


def test_stage_timeout_is_900_seconds() -> None:
    # Scenario: STAGE_TIMEOUT must be 15*60=900 (bash hard-code).
    # Setup: inject mock daemon_main.
    # Test action: call debate_tmuxOrchestrator with valid args.
    # Test verification: ctx.stage_timeout == 900.
    mock_daemon = MagicMock()
    debate_tmuxOrchestrator(
        **_valid_kwargs(),
        daemon_main_fn=mock_daemon,
        cleanup_fn=MagicMock(),
    )
    ctx: DebateContext = mock_daemon.call_args[0][0]
    assert ctx.stage_timeout == 900


def test_agents_parsed_from_space_separated_string() -> None:
    # Scenario: DEBATE_AGENTS is a space-separated string; must be split into list.
    # Setup: debate_agents="claude gemini codex".
    # Test action: call debate_tmuxOrchestrator.
    # Test verification: ctx.agents == ["claude", "gemini", "codex"].
    mock_daemon = MagicMock()
    debate_tmuxOrchestrator(
        **_valid_kwargs(debate_agents="claude gemini codex"),
        daemon_main_fn=mock_daemon,
        cleanup_fn=MagicMock(),
    )
    ctx: DebateContext = mock_daemon.call_args[0][0]
    assert ctx.agents == ["claude", "gemini", "codex"]


def test_daemon_main_called_once_with_context() -> None:
    # Scenario: daemon_main must be called exactly once, receiving the DebateContext.
    # Setup: inject mock daemon_main and cleanup.
    # Test action: call debate_tmuxOrchestrator with valid args.
    # Test verification: mock_daemon called once; arg is DebateContext instance.
    mock_daemon = MagicMock()
    debate_tmuxOrchestrator(
        **_valid_kwargs(),
        daemon_main_fn=mock_daemon,
        cleanup_fn=MagicMock(),
    )
    mock_daemon.assert_called_once()
    ctx = mock_daemon.call_args[0][0]
    assert isinstance(ctx, DebateContext)


def test_cleanup_called_even_when_daemon_raises() -> None:
    # Scenario: mirrors `trap cleanup EXIT` — cleanup runs even if daemon_main raises.
    # Setup: daemon_main raises RuntimeError; inject mock cleanup.
    # Test action: call debate_tmuxOrchestrator; catch the raised error.
    # Test verification: cleanup called exactly once despite the exception.
    mock_cleanup = MagicMock()
    mock_daemon = MagicMock(side_effect=RuntimeError("daemon exploded"))
    with pytest.raises(RuntimeError, match="daemon exploded"):
        debate_tmuxOrchestrator(
            **_valid_kwargs(),
            daemon_main_fn=mock_daemon,
            cleanup_fn=mock_cleanup,
        )
    mock_cleanup.assert_called_once()


def test_returns_zero_on_success() -> None:
    # Scenario: successful run must return 0 (POSIX exit-code convention).
    # Setup: daemon_main and cleanup are no-ops.
    # Test action: call debate_tmuxOrchestrator.
    # Test verification: return value is 0.
    result = debate_tmuxOrchestrator(
        **_valid_kwargs(),
        daemon_main_fn=MagicMock(),
        cleanup_fn=MagicMock(),
    )
    assert result == 0


def test_context_stores_all_positional_args() -> None:
    # Scenario: all seven positional args must be stored verbatim on the context object.
    # Setup: inject distinct values for all positional args.
    # Test action: call debate_tmuxOrchestrator.
    # Test verification: each ctx field matches the supplied value.
    mock_daemon = MagicMock()
    debate_tmuxOrchestrator(
        debate_dir="/d/debate",
        session="s1",
        window_name="w1",
        settings_file="/d/settings.json",
        cwd="/d/cwd",
        repo_root="/d/repo",
        plugin_root="/d/plugin",
        debate_agents="agent_a",
        daemon_main_fn=mock_daemon,
        cleanup_fn=MagicMock(),
    )
    ctx: DebateContext = mock_daemon.call_args[0][0]
    assert ctx.debate_dir == "/d/debate"
    assert ctx.session == "s1"
    assert ctx.window_name == "w1"
    assert ctx.settings_file == "/d/settings.json"
    assert ctx.cwd == "/d/cwd"
    assert ctx.repo_root == "/d/repo"
    assert ctx.plugin_root == "/d/plugin"
