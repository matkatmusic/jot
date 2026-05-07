"""Contract tests for scripts/jot_plugin_orchestrator.py dispatch_main.

The orchestrator is a thin entry point: it routes argv subcommands and stdin
hook payloads to the appropriate <x>_main in common/scripts/<x>_lib.py, and
returns 0 with empty stdout when nothing matches (silent passthrough).
"""
from __future__ import annotations

import io
import json
import sys

import pytest

import jot_plugin_orchestrator as orch
from jot_plugin_orchestrator import dispatch_main


def _set_stdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))


def test_dispatch_empty_stdin_returns_zero(monkeypatch, capsys):
    # Scenario: hook fires with no prompt payload; dispatcher must passthrough.
    # Setup: stdin holds an empty string.
    _set_stdin(monkeypatch, "")
    # Test action: invoke the dispatcher with no argv.
    rc = dispatch_main([])
    # Test verification: rc=0 and no stdout written (silent passthrough).
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_dispatch_unmatched_prompt_returns_zero(monkeypatch, capsys):
    # Scenario: prompt does not start with any plugin prefix.
    # Setup: stdin holds JSON with an unrelated prompt.
    _set_stdin(monkeypatch, json.dumps({"prompt": "/something-not-ours"}))
    # Test action: invoke the dispatcher.
    rc = dispatch_main([])
    # Test verification: rc=0 and no stdout (Claude proceeds with prompt).
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_dispatch_routes_jot_prefix_to_jot_main(monkeypatch):
    # Scenario: prompt "/jot ..." must invoke jot_main.
    # Setup: stub jot_main inside the prompt dispatch table.
    called = {"n": 0}

    def fake_jot_main():
        called["n"] += 1
        return 0

    rebuilt = tuple(
        (prefix, fake_jot_main if prefix == "/jot" else fn)
        for prefix, fn in orch._PROMPT_DISPATCH
    )
    monkeypatch.setattr(orch, "_PROMPT_DISPATCH", rebuilt)
    _set_stdin(monkeypatch, json.dumps({"prompt": "/jot test idea"}))
    # Test action.
    rc = dispatch_main([])
    # Test verification: route fired exactly once and returned 0.
    assert called["n"] == 1
    assert rc == 0


def test_dispatch_longest_prefix_wins_for_todo_list(monkeypatch):
    # Scenario: "/todo-list" must route to todoList_main, not todo_main, because
    # the dispatcher sorts prefixes longest-first.
    # Setup: stub both /todo and /todo-list entrypoints; record which fires.
    called = []

    def fake_todo():
        called.append("/todo")
        return 0

    def fake_todo_list():
        called.append("/todo-list")
        return 0

    rebuilt = []
    for prefix, fn in orch._PROMPT_DISPATCH:
        if prefix == "/todo":
            rebuilt.append((prefix, fake_todo))
        elif prefix == "/todo-list":
            rebuilt.append((prefix, fake_todo_list))
        else:
            rebuilt.append((prefix, fn))
    monkeypatch.setattr(orch, "_PROMPT_DISPATCH", tuple(rebuilt))
    _set_stdin(monkeypatch, json.dumps({"prompt": "/todo-list"}))
    # Test action.
    dispatch_main([])
    # Test verification: only /todo-list fired.
    assert called == ["/todo-list"]


def test_dispatch_rewrites_jot_colon_prefix(monkeypatch):
    # Scenario: "/jot:plate" must be rewritten to "/plate" and routed there.
    # Setup: stub /plate entrypoint to capture the JSON it sees on stdin.
    captured = {"raw": None}

    def fake_plate_main():
        captured["raw"] = sys.stdin.read()
        return 0

    rebuilt = tuple(
        (prefix, fake_plate_main if prefix == "/plate" else fn)
        for prefix, fn in orch._PROMPT_DISPATCH
    )
    monkeypatch.setattr(orch, "_PROMPT_DISPATCH", rebuilt)
    _set_stdin(monkeypatch, json.dumps({"prompt": "/jot:plate --done"}))
    # Test action.
    dispatch_main([])
    # Test verification: the rewritten JSON reached the entrypoint with /plate.
    assert captured["raw"] is not None
    payload = json.loads(captured["raw"])
    assert payload["prompt"] == "/plate --done"


def test_dispatch_argv_mode_routes_to_known_subcommand(monkeypatch):
    # Scenario: argv-style invocation (e.g. for tmux-launched workers).
    # Setup: stub jot_sessionStart in the argv dispatch table.
    captured = {"args": None}

    def fake_session_start(args):
        captured["args"] = args
        return 0

    monkeypatch.setitem(orch._ARGV_DISPATCH, "jot-session-start", fake_session_start)
    # Test action: invoke with an argv head matching a registered subcommand.
    rc = dispatch_main(["jot-session-start", "input.txt", "/tmp/inv"])
    # Test verification: the registered fn ran with the remaining argv.
    assert rc == 0
    assert captured["args"] == ["input.txt", "/tmp/inv"]


def test_dispatch_argv_unknown_head_falls_through_to_stdin(monkeypatch, capsys):
    # Scenario: argv head is not a known subcommand; dispatcher must read stdin
    # and continue (matches existing behavior — argv path does not short-circuit).
    # Setup: empty stdin so no route fires; argv with bogus head.
    _set_stdin(monkeypatch, "")
    # Test action.
    rc = dispatch_main(["not-a-subcommand", "x"])
    # Test verification: rc=0 from passthrough, no stdout.
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_dispatch_propagates_route_return_code(monkeypatch):
    # Scenario: matched route returns a non-zero rc; dispatcher must propagate.
    # Setup: stub /jot to return 7.

    def fake_jot_main():
        return 7

    rebuilt = tuple(
        (prefix, fake_jot_main if prefix == "/jot" else fn)
        for prefix, fn in orch._PROMPT_DISPATCH
    )
    monkeypatch.setattr(orch, "_PROMPT_DISPATCH", rebuilt)
    _set_stdin(monkeypatch, json.dumps({"prompt": "/jot foo"}))
    # Test action.
    rc = dispatch_main([])
    # Test verification: caller sees the route's rc, not 0.
    assert rc == 7
