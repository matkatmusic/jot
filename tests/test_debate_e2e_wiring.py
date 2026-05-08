"""End-to-end wiring tests for the /debate, /debate-retry, /debate-abort
prompt routes.

Each test pipes a UserPromptSubmit hook JSON into
`scripts/jot_plugin_orchestrator.py` and asserts the routed
`debate_lib.*_main` entrypoint emitted the documented block-decision
JSON on stdout, mirroring the contract used by the /jot and /todo-list
e2e tests.
"""
from __future__ import annotations

from pathlib import Path

from tests._e2e_lib import (
    e2e_buildDebateAbortPromptFixture,
    e2e_buildDebatePromptFixture,
    e2e_buildDebateRetryPromptFixture,
    e2e_parseHookDecision,
    e2e_runOrchestratorWithStdin,
)


def test_debatePrompt_emitsBlockDecisionWhenTopicMissing(tmp_path: Path) -> None:
    # Scenario: a "/debate" UserPromptSubmit with no topic must reach
    # debate_main via _PROMPT_DISPATCH, which then emits the documented
    # "no topic provided" block-decision JSON on stdout so Claude Code's
    # hook reader can block the prompt.
    # Setup: hermetic env with DEBATE_SKIP_TERMINAL_CHECK=1 to bypass the
    # macOS Terminal.app probe inside debate_launch.
    env, payload = e2e_buildDebatePromptFixture(tmp_path)

    # Test action: pipe payload through the orchestrator subprocess.
    result = e2e_runOrchestratorWithStdin(env=env, stdin=payload)

    # Test verification: stdout carries a block decision whose reason
    # names the missing topic.
    assert result.returncode == 0, f"orchestrator crashed: stderr={result.stderr!r}"
    decision = e2e_parseHookDecision(result.stdout)
    assert decision["decision"] == "block"
    assert "no topic provided" in decision["reason"]


def test_debateRetryPrompt_emitsBlockDecisionWhenTranscriptPathMissing(
    tmp_path: Path,
) -> None:
    # Scenario: a "/debate-retry" UserPromptSubmit with empty transcript_path
    # must reach debate_retryMain via _PROMPT_DISPATCH, which emits the
    # documented "no transcript_path" block-decision JSON on stdout.
    # Setup: hermetic env with empty transcript_path in payload.
    env, payload = e2e_buildDebateRetryPromptFixture(tmp_path)

    # Test action: pipe payload through the orchestrator subprocess.
    result = e2e_runOrchestratorWithStdin(env=env, stdin=payload)

    # Test verification: stdout carries a block decision naming the
    # missing transcript_path.
    assert result.returncode == 0, f"orchestrator crashed: stderr={result.stderr!r}"
    decision = e2e_parseHookDecision(result.stdout)
    assert decision["decision"] == "block"
    assert "transcript_path" in decision["reason"]


def test_debateAbortPrompt_emitsBlockDecisionWhenTranscriptPathMissing(
    tmp_path: Path,
) -> None:
    # Scenario: a "/debate-abort" UserPromptSubmit with empty transcript_path
    # must reach debate_abortMain via _PROMPT_DISPATCH, which emits the
    # documented "no transcript_path" block-decision JSON on stdout.
    # Setup: hermetic env with empty transcript_path in payload.
    env, payload = e2e_buildDebateAbortPromptFixture(tmp_path)

    # Test action: pipe payload through the orchestrator subprocess.
    result = e2e_runOrchestratorWithStdin(env=env, stdin=payload)

    # Test verification: stdout carries a block decision naming the
    # missing transcript_path.
    assert result.returncode == 0, f"orchestrator crashed: stderr={result.stderr!r}"
    decision = e2e_parseHookDecision(result.stdout)
    assert decision["decision"] == "block"
    assert "transcript_path" in decision["reason"]
