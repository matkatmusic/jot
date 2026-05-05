"""RED tests for debate_sendPromptToAgent (bash send_prompt parity).

Test-shape: one behavior per test; Scenario / Setup / Test action / Test
verification comments per RED_GREEN_TDD.md. Mocks tmux helpers at the module
boundary. No paired bash _tests existed -> RELAXED_COVERAGE.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp_debate_sendPromptToAgent import debate_sendPromptToAgent  # noqa: E402
import _tmp_debate_sendPromptToAgent as mod  # noqa: E402


# Scenario: marker (basename of instructions path) appears in pane on first poll.
# Setup: capture returns text containing basename; tmux_sendAndSubmit returns 0.
# Test action: invoke debate_sendPromptToAgent.
# Test verification: returns 0 (success rc); send-and-submit called with
# bash-shaped prompt; capture called with 2000 scrollback.
def test_returns_zero_when_marker_seen_immediately(monkeypatch, capsys):
    sent_calls: list[tuple[str, str]] = []
    capture_calls: list[tuple[str, int | None]] = []

    monkeypatch.setattr(
        mod, "tmux_sendAndSubmit",
        lambda pane, txt: sent_calls.append((pane, txt)) or 0,
    )
    monkeypatch.setattr(
        mod, "tmux_capturePane",
        lambda pane, n=None: capture_calls.append((pane, n))
        or "noise\nr1_instructions_gemini.txt echoed back\n",
    )
    monkeypatch.setattr(mod, "debate_writeFailed", lambda *a, **k: pytest.fail("should not be called"))

    rc = debate_sendPromptToAgent(
        "%7", "r1", "gemini",
        "/debates/x/r1_instructions_gemini.txt",
    )

    assert rc == 0
    assert sent_calls == [
        ("%7", "read /debates/x/r1_instructions_gemini.txt and perform them"),
    ]
    assert capture_calls == [("%7", 2000)]


# Scenario: marker never appears within 30s budget -> timeout path.
# Setup: capture always returns empty; sleep is stubbed to no-op so the loop
# runs synchronously through all 30 ticks.
# Test action: invoke debate_sendPromptToAgent.
# Test verification: returns 1; debate_writeFailed called with bash-faithful
# stage + reason; capture called exactly 30 times (one per second budget).
def test_timeout_returns_one_and_invokes_writeFailed(monkeypatch, capsys):
    capture_count = {"n": 0}
    failed_calls: list[tuple[str, str]] = []

    def fake_capture(pane, n=None):
        capture_count["n"] += 1
        return ""

    monkeypatch.setattr(mod, "tmux_sendAndSubmit", lambda pane, txt: 0)
    monkeypatch.setattr(mod, "tmux_capturePane", fake_capture)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        mod, "debate_writeFailed",
        lambda stage, reason: failed_calls.append((stage, reason)),
    )

    rc = debate_sendPromptToAgent(
        "%9", "r2", "codex",
        "/debates/x/r2_instructions_codex.txt",
    )

    assert rc == 1
    assert capture_count["n"] == 30
    assert failed_calls == [
        ("r2", "send_prompt timeout for codex after 30s"),
    ]
    err = capsys.readouterr().err
    assert "[orch] TIMEOUT: r2/codex did not echo prompt" in err


# Scenario: ANSI escape sequences in pane buffer must be stripped before the
# fixed-string match (bash uses `tr -d '\033'`).
# Setup: capture returns marker wrapped in ESC sequences; if ANSI is not
# stripped the literal basename will not match.
# Test action: invoke debate_sendPromptToAgent.
# Test verification: returns 0 (match succeeded post-strip).
def test_ansi_escapes_are_stripped_before_match(monkeypatch):
    monkeypatch.setattr(mod, "tmux_sendAndSubmit", lambda pane, txt: 0)
    monkeypatch.setattr(
        mod, "tmux_capturePane",
        lambda pane, n=None: "\x1b[32mr1_instructions_claude.txt\x1b[0m",
    )
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(mod, "debate_writeFailed", lambda *a, **k: pytest.fail("unexpected"))

    rc = debate_sendPromptToAgent(
        "%3", "r1", "claude",
        "/debates/y/r1_instructions_claude.txt",
    )

    assert rc == 0


# Scenario: marker derivation uses basename of the instructions path, not the
# full path (bash `marker=$(basename "$instructions")`).
# Setup: capture buffer contains ONLY the basename, never the parent dirs.
# Test action: invoke with a deeply nested instructions path.
# Test verification: returns 0; matching by basename succeeded.
def test_marker_is_basename_not_full_path(monkeypatch):
    monkeypatch.setattr(mod, "tmux_sendAndSubmit", lambda pane, txt: 0)
    monkeypatch.setattr(
        mod, "tmux_capturePane",
        lambda pane, n=None: "echoed: r1_instructions_gemini.txt",
    )
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    rc = debate_sendPromptToAgent(
        "%5", "r1", "gemini",
        "/very/deep/path/Debates/2026/r1_instructions_gemini.txt",
    )

    assert rc == 0
