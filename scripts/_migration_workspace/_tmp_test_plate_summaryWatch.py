"""RED-YELLOW-GREEN TDD tests for plate_summaryWatch.

Migrated from bash plate_summary_watch (RELAXED_COVERAGE: no paired
bash _tests; tests authored from intent + docstring).

The watcher polls an output file. When the file appears AND is non-empty,
it dispatches `/exit` + Enter to the named tmux pane and returns 0.
On timeout (file never becomes non-empty), it returns 1 without
touching the pane.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the workspace importable regardless of pytest invocation cwd.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import pytest

from _tmp_plate_summaryWatch import plate_summaryWatch


# ---------------------------------------------------------------------------
# Test doubles: deterministic sleep + tmux send injection
# ---------------------------------------------------------------------------

class FakeClock:
    """Deterministic sleep replacement that advances a virtual clock and
    optionally mutates the filesystem at scheduled tick counts."""

    def __init__(self, on_tick=None):
        self.elapsed = 0.0
        self.calls = 0
        self._on_tick = on_tick or (lambda n: None)

    def __call__(self, secs: float) -> None:
        self.calls += 1
        self.elapsed += secs
        self._on_tick(self.calls)


class FakeTmux:
    """Records every (pane, keys) tuple sent."""

    def __init__(self, raise_on_call: bool = False):
        self.sent: list[tuple[str, str]] = []
        self.raise_on_call = raise_on_call

    def __call__(self, pane: str, keys: str) -> None:
        if self.raise_on_call:
            raise RuntimeError("pane gone")
        self.sent.append((pane, keys))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_returns_zero_when_output_file_already_non_empty(tmp_path):
    # Scenario: agent has already written its summary before the watcher polls.
    # Setup: pre-create a non-empty output file.
    out = tmp_path / "summary.txt"
    out.write_text("done")
    sleep = FakeClock()
    send = FakeTmux()

    # Test action: run the watcher with a generous timeout.
    rc = plate_summaryWatch(
        pane="plate-summary-7:plate-summary-abc",
        output_file=str(out),
        timeout=600,
        interval=2,
        sleep=sleep,
        tmux_send=send,
    )

    # Test verification: rc==0, no sleep call needed (file ready first poll).
    assert rc == 0
    assert sleep.calls == 0


def test_sends_exit_then_enter_when_file_becomes_non_empty(tmp_path):
    # Scenario: file appears non-empty after a couple of poll intervals.
    # Setup: schedule the file to be written on tick #2.
    out = tmp_path / "summary.txt"

    def writer(tick: int) -> None:
        if tick == 2:
            out.write_text("summary body")

    sleep = FakeClock(on_tick=writer)
    send = FakeTmux()

    # Test action.
    rc = plate_summaryWatch(
        pane="pane:0",
        output_file=str(out),
        timeout=600,
        interval=2,
        sleep=sleep,
        tmux_send=send,
    )

    # Test verification: rc==0 AND exactly the documented two-step send sequence.
    assert rc == 0
    assert send.sent == [("pane:0", "/exit"), ("pane:0", "Enter")]


def test_returns_one_on_timeout_without_sending(tmp_path):
    # Scenario: file never becomes non-empty; watcher must give up.
    # Setup: file does not exist (and stays absent across all ticks).
    out = tmp_path / "never.txt"
    sleep = FakeClock()
    send = FakeTmux()

    # Test action: timeout=4s, interval=2s -> exactly 2 polls then exit.
    rc = plate_summaryWatch(
        pane="pane:0",
        output_file=str(out),
        timeout=4,
        interval=2,
        sleep=sleep,
        tmux_send=send,
    )

    # Test verification: failure rc, NO tmux dispatch, slept exactly timeout/interval times.
    assert rc == 1
    assert send.sent == []
    assert sleep.calls == 2


def test_empty_file_is_treated_as_not_ready(tmp_path):
    # Scenario: file exists but is zero-byte (atomicity invariant: agent
    # uses temp-then-rename, so empty = not yet written).
    # Setup: create the file empty, fill it on tick #1.
    out = tmp_path / "summary.txt"
    out.write_text("")

    def writer(tick: int) -> None:
        if tick == 1:
            out.write_text("payload")

    sleep = FakeClock(on_tick=writer)
    send = FakeTmux()

    # Test action.
    rc = plate_summaryWatch(
        pane="pane:0",
        output_file=str(out),
        timeout=600,
        interval=2,
        sleep=sleep,
        tmux_send=send,
    )

    # Test verification: watcher slept at least once before sending /exit.
    assert rc == 0
    assert sleep.calls >= 1
    assert ("pane:0", "/exit") in send.sent


def test_swallows_tmux_send_errors_and_still_returns_zero(tmp_path):
    # Scenario: pane has already gone away (user closed it). send-keys raises;
    # watcher must still report success per docstring ("just exit successfully").
    # Setup: pre-populated file + tmux double that throws.
    out = tmp_path / "summary.txt"
    out.write_text("done")
    sleep = FakeClock()
    send = FakeTmux(raise_on_call=True)

    # Test action.
    rc = plate_summaryWatch(
        pane="dead:pane",
        output_file=str(out),
        timeout=10,
        interval=1,
        sleep=sleep,
        tmux_send=send,
    )

    # Test verification: graceful success.
    assert rc == 0


def test_env_overrides_supply_default_timeout_and_interval(tmp_path, monkeypatch):
    # Scenario: caller omits timeout/interval -> values come from env knobs
    # PLATE_SUMMARY_WATCH_TIMEOUT / PLATE_SUMMARY_WATCH_INTERVAL.
    # Setup: env says timeout=6s, interval=3s; file never appears.
    monkeypatch.setenv("PLATE_SUMMARY_WATCH_TIMEOUT", "6")
    monkeypatch.setenv("PLATE_SUMMARY_WATCH_INTERVAL", "3")
    out = tmp_path / "never.txt"
    sleep = FakeClock()
    send = FakeTmux()

    # Test action: do NOT pass timeout/interval.
    rc = plate_summaryWatch(
        pane="pane:0",
        output_file=str(out),
        sleep=sleep,
        tmux_send=send,
    )

    # Test verification: 6/3 = 2 polls, then timeout rc==1.
    assert rc == 1
    assert sleep.calls == 2
