"""Tests for dispatch_main: argv routing + stdin prompt routing.

Mirrors lines 4117-4177 of jot-plugin-orchestrator.sh. One behavior per test;
all 12 argv subcommands and all 7 prompt prefixes covered, plus normalisation,
whitespace tolerance, newline tolerance, and unknown-argv fall-through.
"""

from __future__ import annotations

import io
import json
import sys

import pytest

import _tmp_dispatch_main as dm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub(monkeypatch, name, recorder, key):
    """Replace dm.<name> with a stub that records the call. Returns nothing."""
    def _fn(*args, **kwargs):
        recorder.append((key, args, kwargs))
        return 0
    monkeypatch.setattr(dm, name, _fn)
    # Also patch the lookup tables that captured the original references at
    # import time, so the dispatcher actually invokes our stub.
    if key in dm._ARGV_DISPATCH:
        dm._ARGV_DISPATCH[key] = _fn


def _stub_prompt(monkeypatch, name, recorder, key):
    """Stub a stdin-mode entrypoint and rewire the prompt dispatch table."""
    def _fn(*args, **kwargs):
        # Capture stdin contents at call time so tests can verify rewrite.
        recorder.append((key, sys.stdin.read()))
        return 0
    monkeypatch.setattr(dm, name, _fn)
    # Rebuild the prompt dispatch tuple list with the new lambda.
    rebuilt = []
    for prefix, _ in dm._PROMPT_DISPATCH:
        if prefix == key:
            rebuilt.append((prefix, lambda f=_fn: f()))
        else:
            rebuilt.append((prefix, _))
    monkeypatch.setattr(dm, "_PROMPT_DISPATCH", tuple(rebuilt))


# ---------------------------------------------------------------------------
# Argv-mode tests: 12 subcommands
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "subcmd,fn_name",
    [
        ("jot-session-start", "jot_sessionStart"),
        ("jot-session-end", "jot_sessionEnd"),
        ("jot-stop", "jot_stop"),
        ("scan-open-todos", "todo_scanOpen"),
        ("todo-launcher", "todo_launcher"),
        ("todo-stop", "todo_stop"),
        ("todo-session-start", "todo_sessionStart"),
        ("todo-session-end", "todo_sessionEnd"),
        ("plate-summary-stop", "plate_summaryStop"),
        ("plate-summary-watch", "plate_summaryWatch"),
        ("debate-tmux-orchestrator", "debate_tmuxOrchestrator"),
        ("jot-diag-collect", "jot_collectDiagnostics"),
    ],
)
def test_argv_subcommand_routes_to_function(monkeypatch, subcmd, fn_name):
    # Scenario: argv[0] is a known subcommand; dispatcher must call it once
    # with argv[1:] and not consult stdin.
    # Setup: stub the target function and rewire the argv map; stdin is empty.
    calls: list = []
    _stub(monkeypatch, fn_name, calls, subcmd)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    # Test action: invoke dispatcher with subcmd plus two extra args.
    rc = dm.dispatch_main([subcmd, "alpha", "beta"])
    # Test verification: function called exactly once with the trailing args.
    assert rc == 0
    assert len(calls) == 1
    assert calls[0][0] == subcmd
    assert calls[0][1] == (["alpha", "beta"],)


def test_unknown_argv_falls_through_to_stdin_mode(monkeypatch):
    # Scenario: argv[0] is not a known subcommand -> dispatcher must read
    # stdin and route by prompt instead of erroring.
    # Setup: stub jot_main; provide stdin JSON with /jot prompt.
    calls: list = []
    _stub_prompt(monkeypatch, "jot_main", calls, "/jot")
    payload = json.dumps({"prompt": "/jot hello"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    # Test action: pass an unknown argv head.
    rc = dm.dispatch_main(["not-a-subcommand", "x"])
    # Test verification: jot_main was invoked via stdin fall-through.
    assert rc == 0
    assert len(calls) == 1
    assert calls[0][0] == "/jot"


# ---------------------------------------------------------------------------
# Stdin-mode tests: 7 prompt prefixes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "prefix,fn_name",
    [
        ("/jot", "jot_main"),
        ("/plate", "plate_main"),
        ("/debate", "debate_launch"),
        ("/debate-retry", "debateRetry_main"),
        ("/debate-abort", "debateAbort_main"),
        ("/todo", "todo_main"),
        ("/todo-list", "todoList_main"),
    ],
)
def test_prompt_prefix_routes_to_entrypoint(monkeypatch, prefix, fn_name):
    # Scenario: stdin JSON's .prompt starts with a known slash command;
    # dispatcher must invoke the matching entrypoint exactly once.
    # Setup: stub the target entrypoint; feed JSON with the prefix + a tail.
    calls: list = []
    _stub_prompt(monkeypatch, fn_name, calls, prefix)
    payload = json.dumps({"prompt": f"{prefix} arg-tail"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    # Test action: dispatch with empty argv to force stdin mode.
    rc = dm.dispatch_main([])
    # Test verification: the matching entrypoint was called once.
    assert rc == 0
    assert len(calls) == 1
    assert calls[0][0] == prefix


def test_default_prompt_exits_zero(monkeypatch):
    # Scenario: prompt matches none of the known prefixes; bash exits 0.
    # Setup: provide a non-matching prompt; stub jot_main as a tripwire.
    tripwire: list = []
    _stub_prompt(monkeypatch, "jot_main", tripwire, "/jot")
    payload = json.dumps({"prompt": "hello world no slash"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    # Test action: dispatch with empty argv.
    rc = dm.dispatch_main([])
    # Test verification: returns 0 and no entrypoint was invoked.
    assert rc == 0
    assert tripwire == []


def test_jot_namespace_normalises_to_bare_skill(monkeypatch):
    # Scenario: prompt arrives as "/jot:todo-list ..." -> dispatcher must
    # rewrite to "/todo-list ..." and route to todoList_main.
    # Setup: stub todoList_main; feed namespaced prompt.
    calls: list = []
    _stub_prompt(monkeypatch, "todoList_main", calls, "/todo-list")
    payload = json.dumps({"prompt": "/jot:todo-list show me"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    # Test action: dispatch.
    rc = dm.dispatch_main([])
    # Test verification: todoList_main called once; the stdin seen by the
    # callee contains the rewritten prompt (no "/jot:" prefix).
    assert rc == 0
    assert len(calls) == 1
    forwarded = json.loads(calls[0][1])
    assert forwarded["prompt"] == "/todo-list show me"


def test_leading_whitespace_in_prompt_tolerated(monkeypatch):
    # Scenario: prompt has leading spaces; lstrip must let it match.
    # Setup: stub jot_main; prefix prompt with spaces and tab.
    calls: list = []
    _stub_prompt(monkeypatch, "jot_main", calls, "/jot")
    payload = json.dumps({"prompt": "   \t/jot foo"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    # Test action: dispatch.
    rc = dm.dispatch_main([])
    # Test verification: matched and routed to jot_main.
    assert rc == 0
    assert len(calls) == 1


def test_newline_after_slashcommand_tolerated(monkeypatch):
    # Scenario: prompt is "/plate\n..." -> bash matches $'/plate\n'*.
    # Setup: stub plate_main; payload uses literal newline.
    calls: list = []
    _stub_prompt(monkeypatch, "plate_main", calls, "/plate")
    payload = json.dumps({"prompt": "/plate\nbody line"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    # Test action: dispatch.
    rc = dm.dispatch_main([])
    # Test verification: plate_main routed.
    assert rc == 0
    assert len(calls) == 1
