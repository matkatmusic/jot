"""Tests for tmux_lib Monitor bucket: waitForClaudeReadiness."""
from __future__ import annotations

from common.scripts import tmux_lib as _tmux_lib_mod
from common.scripts.tmux_lib import tmux_waitForClaudeReadiness

# Bind module alias used throughout the test bodies.
mod = _tmux_lib_mod


# === Bucket: Monitor ===

# --- tmux_waitForClaudeReadiness ---


_READY_GLYPH = "❯"  # ❯


def test_tmux_waitForClaudeReadiness_returns_zero_when_glyph_present_immediately(monkeypatch):
    # Scenario: pane already shows the ready glyph; function returns 0 without sleeping.
    sleep_calls = []
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane",
                        lambda pid, lines=None: f"banner\n{_READY_GLYPH} ready\n")
    monkeypatch.setattr("time.sleep",
                        lambda s: sleep_calls.append(s))
    # Test action.
    rc = tmux_waitForClaudeReadiness("%42", timeout=1)
    # Test verification: rc 0 and no sleep needed.
    assert rc == 0
    assert sleep_calls == []


def test_tmux_waitForClaudeReadiness_returns_one_on_timeout_and_logs_stderr(monkeypatch, capsys):
    # Scenario: glyph never appears; function times out after timeout*2 sleeps and logs to stderr.
    sleep_calls = []
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane",
                        lambda pid, lines=None: "still loading")
    monkeypatch.setattr("time.sleep",
                        lambda s: sleep_calls.append(s))
    # Test action.
    rc = tmux_waitForClaudeReadiness("%7", timeout=2)
    err = capsys.readouterr().err
    # Test verification: rc 1, exactly 4 sleeps of 0.5s each, stderr tagged.
    assert rc == 1
    assert sleep_calls == [0.5, 0.5, 0.5, 0.5]
    assert "tmux_waitForClaudeReadiness" in err
    assert "timed out" in err
    assert "%7" in err


def test_tmux_waitForClaudeReadiness_polls_until_ready(monkeypatch):
    # Scenario: glyph appears on third poll; function returns 0 after exactly 2 sleeps.
    seq = iter(["boot", "starting", f"{_READY_GLYPH}"])
    sleep_count = {"n": 0}
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane",
                        lambda pid, lines=None: next(seq))
    monkeypatch.setattr("time.sleep",
                        lambda s: sleep_count.__setitem__("n", sleep_count["n"] + 1))
    # Test action.
    rc = tmux_waitForClaudeReadiness("%1", timeout=5)
    # Test verification.
    assert rc == 0
    assert sleep_count["n"] == 2


def test_tmux_waitForClaudeReadiness_swallows_capture_errors(monkeypatch):
    # Scenario: capturePane raises on first attempt; loop continues and succeeds on second.
    calls = {"n": 0}
    def fake_capture(pid, lines=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return _READY_GLYPH
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane", fake_capture)
    monkeypatch.setattr("time.sleep", lambda s: None)
    # Test action + verification.
    assert tmux_waitForClaudeReadiness("%9", timeout=2) == 0
    assert calls["n"] == 2


def test_tmux_waitForClaudeReadiness_default_timeout_is_ten_seconds(monkeypatch):
    # Scenario: omitting timeout uses default 10 -> 20 attempts before returning 1.
    attempts = {"n": 0}
    def fake_capture(pid, lines=None):
        attempts["n"] += 1
        return ""
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane", fake_capture)
    monkeypatch.setattr("time.sleep", lambda s: None)
    # Test action.
    rc = tmux_waitForClaudeReadiness("%2")
    # Test verification.
    assert rc == 1
    assert attempts["n"] == 20


def test_tmux_waitForClaudeReadiness_passes_pane_id_and_five_line_window(monkeypatch):
    # Scenario: capturePane is invoked with the pane id and a 5-line window.
    seen = []
    def fake_capture(pid, lines=None):
        seen.append((pid, lines))
        return _READY_GLYPH
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_capturePane", fake_capture)
    monkeypatch.setattr("time.sleep", lambda s: None)
    # Test action.
    tmux_waitForClaudeReadiness("%55", timeout=1)
    # Test verification.
    assert seen == [("%55", 5)]
