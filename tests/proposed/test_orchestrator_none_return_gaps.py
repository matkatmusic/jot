from __future__ import annotations

import io
import json
import sys

import pytest

import jot_plugin_orchestrator as orchestrator


def test_handleArgvDispatch_returns_zero_when_matched_subcommand_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: an argv subcommand matches, and its handler returns None.
    # Setup: install one argv handler that records the positional arguments and
    # returns None instead of an explicit status code.
    observed_args: list[list[str]] = []

    def matchedSubcommand(argv: list[str]):
        observed_args.append(argv)
        return None

    monkeypatch.setattr(orchestrator, "_ARGV_DISPATCH", {"example": matchedSubcommand})

    # Test action: dispatch the argv subcommand.
    matched, return_code = orchestrator.handleArgvDispatch(["example", "one", "two"])

    # Test verification: the handler matched and None was normalized to rc 0.
    assert matched is True
    assert return_code == 0
    assert observed_args == [["one", "two"]]


@pytest.mark.parametrize(
    ("prompt_prefix", "prompt_text"),
    [
        ("/jot", "/jot idea"),
        ("/plate", "/plate"),
        ("/debate", "/debate topic"),
        ("/debate-retry", "/debate-retry"),
        ("/debate-abort", "/debate-abort"),
        ("/todo", "/todo idea"),
        ("/todo-list", "/todo-list"),
    ],
)
def test_handleStdinDispatch_returns_zero_when_matched_prompt_handler_returns_none(
    monkeypatch: pytest.MonkeyPatch,
    prompt_prefix: str,
    prompt_text: str,
) -> None:
    # Scenario: a prompt prefix matches, and its prompt handler returns None.
    # Setup: install one prompt handler for the prefix under test.
    observed_calls: list[str] = []

    def matchedPromptHandler():
        observed_calls.append(prompt_prefix)
        return None

    monkeypatch.setattr(orchestrator, "_PROMPT_DISPATCH", ((prompt_prefix, matchedPromptHandler),))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": prompt_text})))

    # Test action: dispatch the stdin prompt payload.
    matched, return_code = orchestrator.handleStdinDispatch()

    # Test verification: the prompt matched and None was normalized to rc 0.
    assert matched is True
    assert return_code == 0
    assert observed_calls == [prompt_prefix]
