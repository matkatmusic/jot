"""E2E argv-subcommand wire-contract tests for the jot orchestrator.

Each test drives `dispatch_main([subcmd, *args])` end-to-end through the
orchestrator's `_ARGV_DISPATCH` adapter table and asserts the matching lib
function is invoked with the documented *positional* contract (not as a
single argv list). One test per subcommand. Mirrors the stub/rebuild
pattern from `tests/test_jot_dispatch.py::test_argv_dispatch_unpacks_args_positionally`
but expanded to one named test per subcommand so per-subcommand regressions
have an independently-named failure.

Note on observables: each lib function has its own unit-test suite asserting
its file/log side effects. At the orchestrator boundary the only behavior
this layer can observe is "did argv[1:] reach the lib fn as positional
args?". The positional-args assertion is therefore the contract assertion;
where a lib fn would also produce a side effect, that side effect is
covered in its own dedicated test module (e.g. test_jot_lib.py,
test_todo_lib.py, test_plate_lib.py, test_debate_lib.py).
"""
from __future__ import annotations

import pytest

import jot_plugin_orchestrator as _orchestrator
from jot_plugin_orchestrator import dispatch_main


# --- helpers (orchestrator-domain, mirror test_jot_dispatch.py shape) ---


def orchestrator_recordLibCalls(monkeypatch, target_attr: str, recorder: list) -> None:
    # Replace the lib-fn attribute on the orchestrator module with a recorder
    # that captures the positional args tuple and returns rc=0.
    def _recorder(*args, **kwargs):
        recorder.append(args)
        return 0

    monkeypatch.setattr(f"jot_plugin_orchestrator.{target_attr}", _recorder)


def orchestrator_rebuildArgvDispatch(monkeypatch) -> None:
    # Rebuild `_ARGV_DISPATCH` so each adapter lambda re-resolves to the
    # freshly-monkeypatched module attrs (the original lambdas closed over
    # the original imports).
    o = _orchestrator
    rebuilt = {
        "jot-session-start": lambda argv: o.jot_sessionStart(*argv),
        "jot-session-end": lambda argv: o.jot_sessionEnd(*argv),
        "jot-stop": lambda argv: o.jot_stop(*argv),
        "scan-open-todos": lambda argv: o.todo_scanOpen(*argv),
        "todo-launcher": lambda argv: o.todo_launcher(*argv),
        "todo-stop": lambda argv: o.todo_stop(*argv),
        "todo-session-start": lambda argv: o.todo_sessionStart(*argv),
        "todo-session-end": lambda argv: o.todo_sessionEnd(*argv),
        "plate-summary-stop": lambda argv: o.plate_summaryStop(*argv),
        "plate-summary-watch": lambda argv: o.plate_summaryWatch(*argv),
        "debate-tmux-orchestrator": lambda argv: o.debate_tmuxOrchestrator(*argv),
        "jot-diag-collect": lambda argv: o.jot_collectDiagnostics(*argv),
    }
    monkeypatch.setattr(o, "_ARGV_DISPATCH", rebuilt)


def orchestrator_driveArgvSubcmd(
    monkeypatch, subcmd: str, target_attr: str, argv_args: list[str]
) -> tuple[int, list]:
    # End-to-end driver: stub target lib fn, rebuild dispatch table, invoke
    # `dispatch_main([subcmd, *argv_args])`. Returns (rc, recorded_calls).
    calls: list = []
    orchestrator_recordLibCalls(monkeypatch, target_attr, calls)
    orchestrator_rebuildArgvDispatch(monkeypatch)
    rc = dispatch_main([subcmd, *argv_args])
    return rc, calls


# --- jot_* subcommand tests ---


def test_jot_session_start_argv_invokes_jot_sessionStart_with_positional_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: argv subcmd "jot-session-start <input_file> <tmpdir_inv>" reaches
    # jot_sessionStart with two positional args (input_file, tmpdir_inv).
    # Setup: stub jot_sessionStart on the orchestrator module; rebuild dispatch.
    args = ["/tmp/in.txt", "/tmp/inv-XXX"]
    # Test action: drive the subcommand end-to-end.
    rc, calls = orchestrator_driveArgvSubcmd(
        monkeypatch, "jot-session-start", "jot_sessionStart", args
    )
    # Test verification: rc=0 and lib fn received argv as positional args.
    assert rc == 0
    assert calls == [tuple(args)]


def test_jot_session_end_argv_invokes_jot_sessionEnd_with_positional_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: "jot-session-end <tmpdir_inv>" reaches jot_sessionEnd with one
    # positional arg (tmpdir_inv).
    # Setup: stub + rebuild.
    args = ["/tmp/inv-YYY"]
    # Test action:
    rc, calls = orchestrator_driveArgvSubcmd(
        monkeypatch, "jot-session-end", "jot_sessionEnd", args
    )
    # Test verification:
    assert rc == 0
    assert calls == [tuple(args)]


def test_jot_stop_argv_invokes_jot_stop_with_positional_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: "jot-stop <input_file> <tmpdir_inv> <state_dir>" reaches
    # jot_stop with three positional args.
    # Setup:
    args = ["/tmp/in.txt", "/tmp/inv-Z", "/tmp/state"]
    # Test action:
    rc, calls = orchestrator_driveArgvSubcmd(monkeypatch, "jot-stop", "jot_stop", args)
    # Test verification:
    assert rc == 0
    assert calls == [tuple(args)]


def test_jot_diag_collect_argv_invokes_jot_collectDiagnostics_with_positional_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: "jot-diag-collect <out_path>" reaches jot_collectDiagnostics with
    # one positional arg (out_path).
    # Setup:
    args = ["/tmp/jot-diag-fixture.log"]
    # Test action:
    rc, calls = orchestrator_driveArgvSubcmd(
        monkeypatch, "jot-diag-collect", "jot_collectDiagnostics", args
    )
    # Test verification:
    assert rc == 0
    assert calls == [tuple(args)]


# --- todo_* subcommand tests ---


def test_scan_open_todos_argv_invokes_todo_scanOpen_with_positional_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: "scan-open-todos <target_dir>" reaches todo_scanOpen with one
    # positional arg (target_dir).
    # Setup:
    args = ["/tmp/scan-root"]
    # Test action:
    rc, calls = orchestrator_driveArgvSubcmd(
        monkeypatch, "scan-open-todos", "todo_scanOpen", args
    )
    # Test verification:
    assert rc == 0
    assert calls == [tuple(args)]


def test_todo_launcher_argv_invokes_todo_launcher_with_positional_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: "todo-launcher <session_id> <idea> <pending_file_path>" reaches
    # todo_launcher with three positional args in that exact order.
    # Setup:
    args = ["sess-42", "fix the parser", "/tmp/pending.json"]
    # Test action:
    rc, calls = orchestrator_driveArgvSubcmd(
        monkeypatch, "todo-launcher", "todo_launcher", args
    )
    # Test verification:
    assert rc == 0
    assert calls == [tuple(args)]


def test_todo_stop_argv_invokes_todo_stop_with_positional_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: "todo-stop <input_file> <tmpdir_inv> <state_dir>" reaches
    # todo_stop with three positional args.
    # Setup:
    args = ["/tmp/in.txt", "/tmp/inv-T", "/tmp/state"]
    # Test action:
    rc, calls = orchestrator_driveArgvSubcmd(monkeypatch, "todo-stop", "todo_stop", args)
    # Test verification:
    assert rc == 0
    assert calls == [tuple(args)]


def test_todo_session_start_argv_invokes_todo_sessionStart_with_positional_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: "todo-session-start <input_file> <tmpdir_inv>" reaches
    # todo_sessionStart with two positional args.
    # Setup:
    args = ["/tmp/in.txt", "/tmp/inv-S"]
    # Test action:
    rc, calls = orchestrator_driveArgvSubcmd(
        monkeypatch, "todo-session-start", "todo_sessionStart", args
    )
    # Test verification:
    assert rc == 0
    assert calls == [tuple(args)]


def test_todo_session_end_argv_invokes_todo_sessionEnd_with_positional_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: "todo-session-end <tmpdir_inv>" reaches todo_sessionEnd with one
    # positional arg.
    # Setup:
    args = ["/tmp/inv-E"]
    # Test action:
    rc, calls = orchestrator_driveArgvSubcmd(
        monkeypatch, "todo-session-end", "todo_sessionEnd", args
    )
    # Test verification:
    assert rc == 0
    assert calls == [tuple(args)]


# --- plate-summary-* subcommand tests ---


def test_plate_summary_stop_argv_invokes_plate_summaryStop_with_positional_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: "plate-summary-stop <repo> <branch> <output_file>" reaches
    # plate_summaryStop with three positional args.
    # Setup:
    args = ["/tmp/repo", "feature/x", "/tmp/plate-out.txt"]
    # Test action:
    rc, calls = orchestrator_driveArgvSubcmd(
        monkeypatch, "plate-summary-stop", "plate_summaryStop", args
    )
    # Test verification:
    assert rc == 0
    assert calls == [tuple(args)]


def test_plate_summary_watch_argv_invokes_plate_summaryWatch_with_positional_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: "plate-summary-watch <pane> <output_file>" reaches
    # plate_summaryWatch with two positional args.
    # Setup:
    args = ["jot:plate.0", "/tmp/plate-out.txt"]
    # Test action:
    rc, calls = orchestrator_driveArgvSubcmd(
        monkeypatch, "plate-summary-watch", "plate_summaryWatch", args
    )
    # Test verification:
    assert rc == 0
    assert calls == [tuple(args)]


# --- debate-* subcommand tests ---


def test_debate_tmux_orchestrator_argv_invokes_debate_tmuxOrchestrator_with_positional_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: "debate-tmux-orchestrator <debate_dir> <session> <window>
    # <state_json> <cwd> <repo> <plugin>" reaches debate_tmuxOrchestrator with
    # seven positional args in that exact order.
    # Setup:
    args = [
        "/tmp/debates/d1",
        "debate-sess",
        "win0",
        "/tmp/debates/d1/state.json",
        "/tmp/cwd",
        "/tmp/repo",
        "/tmp/plugin",
    ]
    # Test action:
    rc, calls = orchestrator_driveArgvSubcmd(
        monkeypatch,
        "debate-tmux-orchestrator",
        "debate_tmuxOrchestrator",
        args,
    )
    # Test verification:
    assert rc == 0
    assert calls == [tuple(args)]
