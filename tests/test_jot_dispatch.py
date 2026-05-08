"""Tests for jot orchestrator dispatch + jot_main entry-point branches."""
from __future__ import annotations

import io
import io as _io_dispatch
import json
import subprocess
import sys
from pathlib import Path

import pytest

import jot_plugin_orchestrator as _orchestrator
from jot_plugin_orchestrator import dispatch_main
from common.scripts import jot_lib as _jot_mod


# --- dispatch_main ---


def _stub_prompt_disp(monkeypatch, name, recorder, key):
    # Stub a stdin-mode entrypoint and rebuild the prompt dispatch tuple.
    # Operates on the real orchestrator module (where _PROMPT_DISPATCH lives).
    _dm = _orchestrator

    def _fn(*args, **kwargs):
        recorder.append((key, sys.stdin.read()))
        return 0

    monkeypatch.setattr(_dm, name, _fn)
    rebuilt = []
    for prefix, original_fn in _dm._PROMPT_DISPATCH:
        if prefix == key:
            rebuilt.append((prefix, lambda f=_fn: f()))
        else:
            rebuilt.append((prefix, original_fn))
    monkeypatch.setattr(_dm, "_PROMPT_DISPATCH", tuple(rebuilt))


def test_dispatchMain_leading_whitespace_in_prompt_tolerated(monkeypatch):
    # Scenario: prompt has leading whitespace; lstrip lets it match.
    # Setup: stub jot_main; prompt with spaces and tab.
    calls: list = []
    _stub_prompt_disp(monkeypatch, "jot_main", calls, "/jot")
    payload = json.dumps({"prompt": "   \t/jot foo"})
    monkeypatch.setattr(sys, "stdin", _io_dispatch.StringIO(payload))
    # Test action:
    rc = dispatch_main([])
    # Test verification:
    assert rc == 0
    assert len(calls) == 1


def test_dispatchMain_jot_namespace_normalises_to_bare_skill(monkeypatch):
    # Scenario: prompt "/jot:todo-list ..." -> rewritten to "/todo-list ...".
    # Setup: stub todoList_main; namespaced prompt.
    calls: list = []
    _stub_prompt_disp(monkeypatch, "todoList_main", calls, "/todo-list")
    payload = json.dumps({"prompt": "/jot:todo-list show me"})
    monkeypatch.setattr(sys, "stdin", _io_dispatch.StringIO(payload))
    # Test action:
    rc = dispatch_main([])
    # Test verification:
    assert rc == 0
    assert len(calls) == 1
    forwarded = json.loads(calls[0][1])
    assert forwarded["prompt"] == "/todo-list show me"


def test_dispatchMain_default_prompt_exits_zero(monkeypatch):
    # Scenario: prompt matches none of the known prefixes -> exit 0.
    # Setup: non-matching prompt; stub jot_main as a tripwire.
    tripwire: list = []
    _stub_prompt_disp(monkeypatch, "jot_main", tripwire, "/jot")
    payload = json.dumps({"prompt": "hello world no slash"})
    monkeypatch.setattr(sys, "stdin", _io_dispatch.StringIO(payload))
    # Test action:
    rc = dispatch_main([])
    # Test verification:
    assert rc == 0
    assert tripwire == []


def test_dispatchMain_unknown_argv_falls_through_to_stdin_mode(monkeypatch):
    # Scenario: argv[0] is not known -> read stdin, route by prompt.
    # Setup: stub jot_main; provide stdin JSON with /jot prompt.
    calls: list = []
    _stub_prompt_disp(monkeypatch, "jot_main", calls, "/jot")
    payload = json.dumps({"prompt": "/jot hello"})
    monkeypatch.setattr(sys, "stdin", _io_dispatch.StringIO(payload))
    # Test action:
    rc = dispatch_main(["not-a-subcommand", "x"])
    # Test verification:
    assert rc == 0
    assert len(calls) == 1
    assert calls[0][0] == "/jot"


# --- jot_main entry-point dispatch (W3-A moved tests) ---


@pytest.fixture
def base_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    # Setup: minimal valid plugin env + scratch log.
    plugin_root = tmp_path / "plugin"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.setenv("JOT_LOG_FILE", str(tmp_path / "jot.log"))
    monkeypatch.delenv("JOT_SKIP_LAUNCH", raising=False)
    return {
        "plugin_root": str(plugin_root),
        "plugin_data": str(plugin_data),
        "tmp": str(tmp_path),
    }


def _stub_passing_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    # Setup: bypass real tool checks + tmux probe.
    monkeypatch.setattr("common.scripts.hookjson_lib.hookjson_checkRequirements", lambda *a, **k: None)
    monkeypatch.setattr("common.scripts.jot_lib.tmux_requireVersion", lambda _m: 0)


def _stdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))


def test_missing_plugin_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Scenario: harness env vars unset.
    # Setup: clear both vars, stdin irrelevant.
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    _stdin(monkeypatch, "")
    # Test action + verification: jot_main raises RuntimeError.
    with pytest.raises(RuntimeError):
        _jot_mod.jot_main()


def test_non_jot_input_exits_zero_silently(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: stdin lacks the "/jot" substring; hook should no-op.
    # Setup: arbitrary non-jot payload.
    _stdin(monkeypatch, '{"prompt": "/other thing"}')
    # Test action: invoke.
    rc = _jot_mod.jot_main()
    # Test verification: rc=0, no JSON emitted.
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_prompt_not_strict_jot_exits_zero(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: payload contains "/jot" substring but prompt is "/jotsomething" (not strict /jot).
    # Setup: stdin with substring-but-not-prefix.
    _stub_passing_deps(monkeypatch)
    _stdin(monkeypatch, json.dumps({"prompt": "/jotsomething"}))
    # Test action: invoke.
    rc = _jot_mod.jot_main()
    # Test verification: rc=0 with no block emission (strict-prefix branch).
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_empty_idea_emits_block(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: prompt is bare "/jot" with no idea.
    # Setup: stub deps, stdin with bare /jot.
    _stub_passing_deps(monkeypatch)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot"}))
    # Test action: invoke.
    rc = _jot_mod.jot_main()
    out = capsys.readouterr().out
    # Test verification: rc=0 + block decision mentioning "no idea provided".
    assert rc == 0
    assert "no idea provided" in out


def test_missing_repo_emits_block(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # Scenario: cwd is not inside a git repo.
    # Setup: stub deps; force `git rev-parse` to fail.
    _stub_passing_deps(monkeypatch)
    non_repo = tmp_path / "norepo"
    non_repo.mkdir()
    _stdin(monkeypatch, json.dumps({"prompt": "/jot make thing", "cwd": str(non_repo)}))

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr="fatal")

    monkeypatch.setattr(_jot_mod.subprocess, "run", fake_run)
    # Test action: invoke.
    rc = _jot_mod.jot_main()
    out = capsys.readouterr().out
    # Test verification: rc=0 + git-required block.
    assert rc == 0
    assert "requires a git repository" in out


def test_happy_path_writes_input_file_with_all_sections(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: full happy path produces a Todos/<ts>_input.txt with all sections.
    # Setup: stub deps + stub git_lib + stub launch + stub render/capture subprocess.
    _stub_passing_deps(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "Todos").mkdir(parents=True)
    monkeypatch.setattr("common.scripts.jot_lib.getGitBranchNameOrFail", lambda c: "main")
    monkeypatch.setattr("common.scripts.jot_lib.getGitRecentCommitHashes", lambda c: "abc123 init")
    monkeypatch.setattr("common.scripts.jot_lib.getGitUncommittedFilenames", lambda c: "M file.py")
    monkeypatch.setattr("common.scripts.jot_lib.todo_scanOpen", lambda r: "todo1\ntodo2")
    launched = {"called": False}

    def fake_launch() -> int:
        launched["called"] = True
        return 0

    monkeypatch.setattr("common.scripts.jot_lib.jot_launchPhase2Window", fake_launch)

    def fake_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        # git rev-parse: return repo path; render_template: return canned text.
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=str(repo) + "\n", stderr="")
        if "render_template.py" in " ".join(str(c) for c in cmd):
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="RENDERED-INSTRUCTIONS", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(_jot_mod.subprocess, "run", fake_run)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot fix the bug", "cwd": str(repo)}))
    # Test action: invoke.
    rc = _jot_mod.jot_main()
    # Test verification: rc=0, exactly one input file with expected sections.
    assert rc == 0
    files = list((repo / "Todos").glob("*_input.txt"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "## Instructions\nRENDERED-INSTRUCTIONS" in text
    assert "## Idea\nfix the bug" in text
    assert "Branch: main" in text
    assert "Commits: abc123 init" in text
    assert "Uncommitted: M file.py" in text
    assert "## Open TODO Files\ntodo1\ntodo2" in text
    assert "(no transcript available)" in text


# --- _ARGV_DISPATCH adapter regression tests ---
#
# Each test confirms dispatch_main routes argv[1:] as positional args to the
# underlying lib function. Guards against the dispatch contract regressing
# back to passing argv as a single list.


def _record_calls(monkeypatch, target_attr, recorder):
    # Replace the lib function the lambda captures, then rebuild
    # _ARGV_DISPATCH so the lambda re-resolves to the stub.
    monkeypatch.setattr(f"jot_plugin_orchestrator.{target_attr}", lambda *a, **k: (recorder.append(a), 0)[1])


def _rebuild_argv_dispatch(monkeypatch):
    # Rebuild _ARGV_DISPATCH from the freshly-patched module attrs.
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


@pytest.mark.parametrize(
    "subcmd,target,argv_args",
    [
        # Scenario: each argv subcommand routes through dispatch_main with
        # argv[1:] unpacked into positional args of the target lib function.
        ("jot-session-start", "jot_sessionStart", ["/tmp/in", "/tmp/inv"]),
        ("jot-session-end", "jot_sessionEnd", ["/tmp/inv"]),
        ("jot-stop", "jot_stop", ["/tmp/in", "/tmp/inv", "/tmp/state"]),
        ("scan-open-todos", "todo_scanOpen", ["/tmp/dir"]),
        ("todo-launcher", "todo_launcher", ["sess", "idea", "/tmp/p"]),
        ("todo-stop", "todo_stop", ["/tmp/in", "/tmp/inv", "/tmp/state"]),
        ("todo-session-start", "todo_sessionStart", ["/tmp/in", "/tmp/inv"]),
        ("todo-session-end", "todo_sessionEnd", ["/tmp/inv"]),
        ("plate-summary-stop", "plate_summaryStop", ["repo", "branch", "/tmp/out"]),
        ("plate-summary-watch", "plate_summaryWatch", ["pane", "/tmp/out"]),
        (
            "debate-tmux-orchestrator",
            "debate_tmuxOrchestrator",
            ["/tmp/d", "sess", "win", "/tmp/s.json", "/cwd", "/repo", "/plug"],
        ),
        ("jot-diag-collect", "jot_collectDiagnostics", ["/tmp/out"]),
    ],
)
def test_argv_dispatch_unpacks_args_positionally(monkeypatch, subcmd, target, argv_args):
    # Setup: replace the target lib fn with a recorder, rebuild dispatch.
    calls: list = []
    _record_calls(monkeypatch, target, calls)
    _rebuild_argv_dispatch(monkeypatch)
    # Test action: dispatch the subcommand with the argv args.
    rc = dispatch_main([subcmd, *argv_args])
    # Test verification: rc=0 and the lib fn received argv args as positional.
    assert rc == 0
    assert calls == [tuple(argv_args)]
