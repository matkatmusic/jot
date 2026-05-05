"""RED-YELLOW-GREEN tests for jot_sessionStart.

RELAXED_COVERAGE: no bash _tests pair; behaviors derived from docstring + intent.
Test-shape rules: one behavior per test, Scenario/Setup/Test action/Test verification
comments per RED_GREEN_TDD.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts")
sys.path.insert(0, "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts/_migration_workspace")

from _tmp_jot_sessionStart import jot_sessionStart
import _tmp_jot_sessionStart as mod


def test_missing_input_file_returns_0_and_warns(capsys):
    # Scenario: caller forgot to pass input_file; bash spec returns silent exit 0.
    # Setup: input_file=None, tmpdir_inv non-empty.
    # Test action: invoke jot_sessionStart with missing input_file.
    rc = jot_sessionStart(None, "/some/tmpdir")
    err = capsys.readouterr().err
    # Test verification: rc is 0 and stderr names the missing-args contract.
    assert rc == 0
    assert "missing args" in err


def test_missing_tmpdir_inv_returns_0_and_warns(capsys):
    # Scenario: caller forgot tmpdir_inv argument.
    # Setup: input_file present, tmpdir_inv empty string.
    # Test action: invoke with empty tmpdir_inv.
    rc = jot_sessionStart("/x/in.md", "")
    err = capsys.readouterr().err
    # Test verification: rc is 0 and missing-args message emitted.
    assert rc == 0
    assert "missing args" in err


def test_sidecar_empty_after_retries_returns_0(tmp_path, monkeypatch, capsys):
    # Scenario: tmux_target sidecar never appears within 5 retries.
    # Setup: empty tmpdir, monkeypatch sleep to no-op so test runs fast.
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    # Test action: call with valid args but no sidecar file present.
    rc = jot_sessionStart("/x/in.md", str(tmp_path))
    err = capsys.readouterr().err
    # Test verification: rc 0 and stderr explains sidecar emptiness.
    assert rc == 0
    assert "tmux_target sidecar empty" in err


def test_sidecar_zero_byte_file_treated_as_empty(tmp_path, monkeypatch, capsys):
    # Scenario: sidecar exists but is zero-byte (race window).
    # Setup: create empty tmux_target file; bypass real sleeps.
    (tmp_path / "tmux_target").write_text("")
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    # Test action: invoke jot_sessionStart.
    rc = jot_sessionStart("/x/in.md", str(tmp_path))
    err = capsys.readouterr().err
    # Test verification: empty sidecar is rejected as if missing.
    assert rc == 0
    assert "tmux_target sidecar empty" in err


def test_readiness_timeout_returns_1(tmp_path, monkeypatch, capsys):
    # Scenario: pane id resolved but Claude TUI never shows the ready glyph.
    # Setup: write valid sidecar; stub readiness probe to return 1 (timeout).
    (tmp_path / "tmux_target").write_text("%42\n")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(mod, "tmux_waitForClaudeReadiness", lambda pane: 1)
    monkeypatch.setattr(
        mod, "tmux_sendAndSubmit",
        lambda pane, text: sent.append((pane, text)) or 0,
    )
    # Test action: invoke jot_sessionStart.
    rc = jot_sessionStart("/x/in.md", str(tmp_path))
    err = capsys.readouterr().err
    # Test verification: rc 1, no keys sent, diagnostic emitted.
    assert rc == 1
    assert "claude TUI not ready" in err
    assert sent == []


def test_happy_path_sends_read_prompt_to_resolved_pane(tmp_path, monkeypatch):
    # Scenario: sidecar present, TUI ready -> prompt is submitted to that pane.
    # Setup: write pane id "%99" into sidecar; stub readiness to 0; capture sends.
    (tmp_path / "tmux_target").write_text("%99\nignored-extra\n")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(mod, "tmux_waitForClaudeReadiness", lambda pane: 0)
    monkeypatch.setattr(
        mod, "tmux_sendAndSubmit",
        lambda pane, text: sent.append((pane, text)) or 0,
    )
    # Test action: invoke with realistic args.
    rc = jot_sessionStart("/path/to/input.md", str(tmp_path))
    # Test verification: rc 0, exactly one send to first-line pane id, exact prompt text.
    assert rc == 0
    assert sent == [
        ("%99", "Read /path/to/input.md and follow the instructions at the top of that file"),
    ]


def test_sidecar_first_line_only_used(tmp_path, monkeypatch):
    # Scenario: sidecar accidentally contains multiple lines; bash uses head -1.
    # Setup: multi-line sidecar; stub readiness OK; capture send target.
    (tmp_path / "tmux_target").write_text("%first\n%second\n")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(mod, "tmux_waitForClaudeReadiness", lambda pane: 0)
    monkeypatch.setattr(
        mod, "tmux_sendAndSubmit",
        lambda pane, text: sent.append((pane, text)) or 0,
    )
    # Test action: invoke jot_sessionStart.
    jot_sessionStart("/x/in.md", str(tmp_path))
    # Test verification: only the first line is used as the pane target.
    assert sent[0][0] == "%first"


def test_readiness_called_with_resolved_pane_id(tmp_path, monkeypatch):
    # Scenario: readiness probe must receive the same pane id parsed from sidecar.
    # Setup: sidecar with "%77"; record arg passed into readiness probe.
    (tmp_path / "tmux_target").write_text("%77\n")
    seen: list[str] = []
    def fake_ready(pane: str) -> int:
        seen.append(pane)
        return 0
    monkeypatch.setattr(mod, "tmux_waitForClaudeReadiness", fake_ready)
    monkeypatch.setattr(mod, "tmux_sendAndSubmit", lambda p, t: 0)
    # Test action: invoke jot_sessionStart.
    jot_sessionStart("/x/in.md", str(tmp_path))
    # Test verification: readiness probe got the parsed pane id verbatim.
    assert seen == ["%77"]
