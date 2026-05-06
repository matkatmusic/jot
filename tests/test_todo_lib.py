"""Tests for todo_lib (and todo-related orchestrator functions)."""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import time
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from common.scripts import todo_lib as jot_plugin_orchestrator
from common.scripts.todo_lib import (
    todoList_main,
    todo_launcher,
    todo_main,
    todo_scanOpen,
    todo_sessionEnd,
    todo_sessionStart,
    todo_stop,
)
from common.scripts.claude_lib import claude_buildCmd, claude_seedPermissions
from common.scripts.hookjson_lib import hookjson_checkRequirements
from common.scripts.jot_lib import (
    jot_main,
    jot_sendPrompt,
)
from common.scripts.tmux_lib import (
    tmux_ensureSession,
    tmux_killPane,
    tmux_requireVersion,
    tmux_retile,
    tmux_setPaneTitle,
    tmux_splitWorkerPane,
    tmux_waitForClaudeReadiness,
)
from common.scripts.git_lib import (
    getGitBranchNameOrFail,
    getGitRecentCommitHashes,
    getGitUncommittedFilenames,
)
from common.scripts.util_lib import FileLock, terminal_spawnIfNeeded

# Bind module aliases used throughout the test bodies.
mod = jot_plugin_orchestrator
sut = jot_plugin_orchestrator


def test_todo_launcher_success(monkeypatch, tmp_path):
    # Scenario: standard execution successfully creates inputs, cmds, and tmux window
    # Setup: mock all external calls and dependencies
    session_id = "test-session"
    idea = "fix a bug"
    pending_file = tmp_path / "pending.json"
    repo_root = tmp_path / "repo"
    cwd = repo_root / "src"
    transcript_path = tmp_path / "transcript.txt"
    
    repo_root.mkdir(parents=True)
    cwd.mkdir(parents=True)
    transcript_path.write_text("transcript content")
    
    pending_data = {
        "repo_root": str(repo_root),
        "cwd": str(cwd),
        "transcript_path": str(transcript_path),
        "timestamp": "20260101-120000"
    }
    pending_file.write_text(json.dumps(pending_data))
    
    calls = []
    
    monkeypatch.setattr("common.scripts.todo_lib.getGitBranchNameOrFail", lambda p: "main-branch")
    monkeypatch.setattr("common.scripts.todo_lib.getGitRecentCommitHashes", lambda p: ["commit1", "commit2"])
    monkeypatch.setattr("common.scripts.todo_lib.getGitUncommittedFilenames", lambda p: ["file1.txt"])
    monkeypatch.setattr("common.scripts.todo_lib.todo_scanOpen", lambda p: [str(repo_root / "Todos" / "todo1.md")])
    
    def mock_run(cmd, *args, **kwargs):
        calls.append(["run", cmd[0] if isinstance(cmd, list) else cmd])
        class MockResult:
            returncode = 0
            stdout = "mock stdout output\n"
        return MockResult()
        
    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(jot_plugin_orchestrator.subprocess, "run", mock_run)
    
    monkeypatch.setattr("common.scripts.todo_lib.claude_seedPermissions", lambda *args: calls.append(["claude_seedPermissions"]))
    monkeypatch.setattr("common.scripts.todo_lib.claude_buildCmd", lambda *args: "mock claude cmd")
    
    class MockFileLock:
        def __init__(self, path, timeout):
            pass
        def __enter__(self):
            calls.append(["lock_acquire"])
            return self
        def __exit__(self, *args):
            calls.append(["lock_release"])
            
    monkeypatch.setattr("common.scripts.todo_lib.FileLock", MockFileLock)
    
    monkeypatch.setattr("common.scripts.todo_lib.tmux_ensureSession", lambda *args: calls.append(["tmux_ensureSession"]))
    monkeypatch.setattr("common.scripts.todo_lib.tmux_splitWorkerPane", lambda *args: "%123")
    monkeypatch.setattr("common.scripts.todo_lib.tmux_setPaneTitle", lambda *args: calls.append(["tmux_setPaneTitle"]))
    monkeypatch.setattr("common.scripts.todo_lib.tmux_retile", lambda *args: calls.append(["tmux_retile"]))
    monkeypatch.setattr("common.scripts.todo_lib.terminal_spawnIfNeeded", lambda *args: calls.append(["terminal_spawnIfNeeded"]))
    
    # Test action:
    result = jot_plugin_orchestrator.todo_launcher(session_id, idea, str(pending_file))

    # Test verification:
    assert result == 0
    assert ["claude_seedPermissions"] in calls
    assert ["lock_acquire"] in calls
    assert ["tmux_ensureSession"] in calls
    assert ["tmux_setPaneTitle"] in calls
    assert ["tmux_retile"] in calls
    assert ["terminal_spawnIfNeeded"] in calls


# --- todoList_main ---

import json
import subprocess
from io import StringIO
from types import SimpleNamespace

import pytest




def _setStdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    monkeypatch.setattr(sys, "stdin", StringIO(payload))


def test_non_todoList_prompt_exits_silently(monkeypatch, capsys):
    # Scenario: stdin payload does not mention "/todo-list -> fast-path return.
    # Setup: stdin is unrelated JSON; no git/format calls should occur.
    _setStdin(monkeypatch, json.dumps({"prompt": "/something-else"}))
    monkeypatch.setattr(sut.subprocess, "run", lambda *a, **k: pytest.fail("must not run subprocess"))
    # Test action: invoke entrypoint.
    rc = sut.todoList_main()
    # Test verification: returns 0 and emits no output.
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_bad_prompt_after_fast_path_exits_silently(monkeypatch, capsys):
    # Scenario: payload contains the literal token but prompt is malformed.
    # Setup: prompt has leading text so strict match fails after fast-path.
    payload = json.dumps({"prompt": 'echo "/todo-list" inside string'})
    _setStdin(monkeypatch, payload)
    monkeypatch.setattr("common.scripts.hookjson_lib.hookjson_checkRequirements", lambda *a, **k: None)
    monkeypatch.setattr(sut.subprocess, "run", lambda *a, **k: pytest.fail("must not run subprocess"))
    # Test action: invoke entrypoint.
    rc = sut.todoList_main()
    # Test verification: silent exit, no block emission.
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_missing_repo_emits_not_a_git_repo(monkeypatch, capsys, tmp_path):
    # Scenario: prompt valid but cwd is not inside a git checkout.
    # Setup: stub git rev-parse to return non-zero; stub requirements.
    _setStdin(monkeypatch, json.dumps({"prompt": "/todo-list", "cwd": str(tmp_path)}))
    monkeypatch.setattr("common.scripts.hookjson_lib.hookjson_checkRequirements", lambda *a, **k: None)
    monkeypatch.setattr(
        sut.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=128, stdout="", stderr="fatal"),
    )
    # Test action: invoke entrypoint.
    rc = sut.todoList_main()
    # Test verification: prints block JSON with not-a-git-repo reason.
    captured = capsys.readouterr().out.strip()
    decoded = json.loads(captured)
    assert rc == 0
    assert decoded == {"decision": "block", "reason": "todo-list: not a git repository."}


def test_missing_todos_folder_emits_message(monkeypatch, capsys, tmp_path):
    # Scenario: repo exists but has no Todos/ subdirectory.
    # Setup: git rev-parse returns tmp_path (no Todos/ inside).
    _setStdin(monkeypatch, json.dumps({"prompt": "/todo-list", "cwd": str(tmp_path)}))
    monkeypatch.setattr("common.scripts.hookjson_lib.hookjson_checkRequirements", lambda *a, **k: None)
    monkeypatch.setattr(
        sut.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=str(tmp_path) + "\n", stderr=""),
    )
    # Test action: invoke entrypoint.
    rc = sut.todoList_main()
    # Test verification: emits the no-Todos-folder block message.
    decoded = json.loads(capsys.readouterr().out.strip())
    assert rc == 0
    assert decoded["reason"] == "No Todos/ folder found in this project."


def test_empty_formatter_output_emits_no_open_todos(monkeypatch, capsys, tmp_path):
    # Scenario: Todos/ exists but formatter produces empty stdout.
    # Setup: real Todos/ dir; first subprocess.run is git, second is formatter (empty).
    todos = tmp_path / "Todos"
    todos.mkdir()
    _setStdin(monkeypatch, json.dumps({"prompt": "/todo-list extra", "cwd": str(tmp_path)}))
    monkeypatch.setattr("common.scripts.hookjson_lib.hookjson_checkRequirements", lambda *a, **k: None)
    calls: list[list[str]] = []

    def fake_run(cmd, *a, **k):
        calls.append(list(cmd))
        if cmd[0] == "git":
            return SimpleNamespace(returncode=0, stdout=str(tmp_path) + "\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sut.subprocess, "run", fake_run)
    # Test action: invoke entrypoint.
    rc = sut.todoList_main()
    # Test verification: emits "No open TODOs." block; formatter was invoked.
    decoded = json.loads(capsys.readouterr().out.strip())
    assert rc == 0
    assert decoded["reason"] == "No open TODOs."
    assert any("format_open_todos.py" in arg for call in calls for arg in call)


def test_non_empty_formatter_output_is_forwarded(monkeypatch, capsys, tmp_path):
    # Scenario: formatter produces a TODO list; entrypoint must forward it.
    # Setup: real Todos/ dir; formatter stub returns multi-line text.
    todos = tmp_path / "Todos"
    todos.mkdir()
    formatted_text = "TODO 1\nTODO 2\n"
    _setStdin(monkeypatch, json.dumps({"prompt": "/todo-list", "cwd": str(tmp_path)}))
    monkeypatch.setattr("common.scripts.hookjson_lib.hookjson_checkRequirements", lambda *a, **k: None)

    def fake_run(cmd, *a, **k):
        if cmd[0] == "git":
            return SimpleNamespace(returncode=0, stdout=str(tmp_path) + "\n", stderr="")
        # Verify TODOS_DIR env was set for the formatter call.
        assert k.get("env", {}).get("TODOS_DIR") == str(todos)
        return SimpleNamespace(returncode=0, stdout=formatted_text, stderr="")

    monkeypatch.setattr(sut.subprocess, "run", fake_run)
    # Test action: invoke entrypoint.
    rc = sut.todoList_main()
    # Test verification: emitted reason equals captured formatter stdout verbatim.
    decoded = json.loads(capsys.readouterr().out.strip())
    assert rc == 0
    assert decoded["reason"] == formatted_text


def _set_stdin(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def _base_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    # Setup helper: provide required env, isolate log/state under tmp_path.
    plugin_data = tmp_path / "plugin-data"
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.delenv("TODO_LOG_FILE", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    return plugin_data


def _patch_repo_root(monkeypatch: pytest.MonkeyPatch, root: str) -> None:
    monkeypatch.setattr("common.scripts.todo_lib._git_get_repo_root", lambda cwd: root)


def test_missing_plugin_data_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Scenario: CLAUDE_PLUGIN_DATA is unset.
    # Setup: ensure env var absent.
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    _set_stdin(monkeypatch, "")
    # Test action: invoke todo_main.
    # Test verification: RuntimeError raised before any I/O.
    with pytest.raises(RuntimeError, match="CLAUDE_PLUGIN_DATA"):
        mod.todo_main()


def test_non_todo_input_exits_zero_silently(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: stdin payload does not contain the "/todo substring.
    # Setup: env ready, stdin has unrelated prompt.
    _base_env(monkeypatch, tmp_path)
    _set_stdin(monkeypatch, '{"prompt": "/jot something"}')
    # Test action: run.
    rc = mod.todo_main()
    # Test verification: rc 0 and no stdout emitted.
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_bad_prompt_format_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: stdin contains "/todo as substring but prompt is not a /todo command.
    # Setup: prompt is "/todoxyz extra" (no leading-space match).
    _base_env(monkeypatch, tmp_path)
    _set_stdin(monkeypatch, '{"prompt": "/todoxyz extra"}')
    # Test action: run.
    rc = mod.todo_main()
    # Test verification: silent exit 0, no block emitted.
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_missing_git_repo_emits_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: cwd is not inside a git repo.
    # Setup: stub repo_root resolver to return "".
    _base_env(monkeypatch, tmp_path)
    _patch_repo_root(monkeypatch, "")
    _set_stdin(monkeypatch, json.dumps({"prompt": "/todo write a test", "cwd": str(tmp_path)}))
    # Test action: run.
    rc = mod.todo_main()
    # Test verification: rc 0, stdout is a block-decision JSON mentioning git.
    assert rc == 0
    out = capsys.readouterr().out.strip()
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "git repository" in decision["reason"]


def test_happy_path_writes_valid_pending_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: well-formed /todo command in a real git repo.
    # Setup: env, stub repo_root to tmp_path, valid stdin payload.
    _base_env(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    _patch_repo_root(monkeypatch, str(repo))
    payload = {
        "prompt": "/todo wire the widget",
        "session_id": "sess-1",
        "transcript_path": "/tmp/t.jsonl",
        "cwd": str(repo),
    }
    _set_stdin(monkeypatch, json.dumps(payload))
    # Test action: run.
    rc = mod.todo_main()
    # Test verification: rc 0, exactly one pending-*.json under state dir, contents valid.
    assert rc == 0
    state_dir = repo / "Todos" / ".todo-state"
    pending = list(state_dir.glob("pending-*.json"))
    assert len(pending) == 1
    claim = json.loads(pending[0].read_text())
    assert claim["session_id"] == "sess-1"
    assert claim["transcript_path"] == "/tmp/t.jsonl"
    assert claim["cwd"] == str(repo)
    assert claim["repo_root"] == str(repo)
    assert claim["idea"] == "wire the widget"
    assert claim["pending_file"] == str(pending[0])
    assert claim["todo_scripts_dir"].endswith("/skills/todo/scripts")
    assert "timestamp" in claim and "created_at" in claim
    assert "todo_plugin_root" in claim


def test_idea_with_quotes_and_newlines_round_trips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: idea contains JSON-hostile characters (quotes, newline, backslash).
    # Setup: stub repo, build payload with tricky idea string.
    _base_env(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    _patch_repo_root(monkeypatch, str(repo))
    tricky = 'fix "quoted" thing\nand \\backslash'
    payload = {"prompt": f"/todo {tricky}", "cwd": str(repo)}
    _set_stdin(monkeypatch, json.dumps(payload))
    # Test action: run.
    rc = mod.todo_main()
    # Test verification: pending file parses and idea exactly matches input.
    assert rc == 0
    pending = list((repo / "Todos" / ".todo-state").glob("pending-*.json"))
    assert len(pending) == 1
    claim = json.loads(pending[0].read_text())
    assert claim["idea"] == tricky


def test_bare_todo_yields_empty_idea(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: prompt is exactly "/todo" with no idea text.
    # Setup: minimal payload, stubbed repo.
    _base_env(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    _patch_repo_root(monkeypatch, str(repo))
    _set_stdin(monkeypatch, json.dumps({"prompt": "/todo", "cwd": str(repo)}))
    # Test action: run.
    rc = mod.todo_main()
    # Test verification: pending file written with idea == "".
    assert rc == 0
    pending = list((repo / "Todos" / ".todo-state").glob("pending-*.json"))
    assert len(pending) == 1
    assert json.loads(pending[0].read_text())["idea"] == ""

# --------- shared fixtures ---------

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


# --------- tests ---------

# Bind a local alias for the jot_main section (these tests target jot_lib).
from common.scripts import jot_lib as _jot_mod  # noqa: E402


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


def test_skip_launch_does_not_call_phase2(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: JOT_SKIP_LAUNCH=1 path emits "(launch skipped)" and skips phase2.
    # Setup: full happy stubs + skip flag.
    _stub_passing_deps(monkeypatch)
    monkeypatch.setenv("JOT_SKIP_LAUNCH", "1")
    repo = tmp_path / "repo"
    (repo / "Todos").mkdir(parents=True)
    monkeypatch.setattr("common.scripts.jot_lib.getGitBranchNameOrFail", lambda c: "main")
    monkeypatch.setattr("common.scripts.jot_lib.getGitRecentCommitHashes", lambda c: "")
    monkeypatch.setattr("common.scripts.jot_lib.getGitUncommittedFilenames", lambda c: "")
    monkeypatch.setattr("common.scripts.jot_lib.todo_scanOpen", lambda r: "")
    launched = {"called": False}
    monkeypatch.setattr("common.scripts.jot_lib.jot_launchPhase2Window", lambda: launched.__setitem__("called", True) or 0)

    def fake_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=str(repo) + "\n", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="X", stderr="")

    monkeypatch.setattr(_jot_mod.subprocess, "run", fake_run)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot do thing", "cwd": str(repo)}))
    # Test action: invoke.
    rc = _jot_mod.jot_main()
    out = capsys.readouterr().out
    # Test verification: phase2 NOT called, block-decision contains "(launch skipped)".
    assert rc == 0
    assert launched["called"] is False
    assert "launch skipped" in out


def test_phase2_called_on_happy_path(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: happy path without JOT_SKIP_LAUNCH calls jot_launchPhase2Window exactly once.
    # Setup: same as happy-path test but track call count.
    _stub_passing_deps(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "Todos").mkdir(parents=True)
    monkeypatch.setattr("common.scripts.jot_lib.getGitBranchNameOrFail", lambda c: "main")
    monkeypatch.setattr("common.scripts.jot_lib.getGitRecentCommitHashes", lambda c: "")
    monkeypatch.setattr("common.scripts.jot_lib.getGitUncommittedFilenames", lambda c: "")
    monkeypatch.setattr("common.scripts.jot_lib.todo_scanOpen", lambda r: "")
    calls = {"n": 0}

    def fake_launch() -> int:
        calls["n"] += 1
        return 0

    monkeypatch.setattr("common.scripts.jot_lib.jot_launchPhase2Window", fake_launch)

    def fake_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=str(repo) + "\n", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="OK", stderr="")

    monkeypatch.setattr(_jot_mod.subprocess, "run", fake_run)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot launch me", "cwd": str(repo)}))
    # Test action: invoke.
    rc = _jot_mod.jot_main()
    out = capsys.readouterr().out
    # Test verification: phase2 called once, success block emitted.
    assert rc == 0
    assert calls["n"] == 1
    assert "Done! Jotted idea in" in out


def test_safe_wrapper_falls_back_to_unavailable(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: git_lib helpers raise; the input file should record "(unavailable)".
    # Setup: stub all git_lib funcs to raise; stub launch + render.
    _stub_passing_deps(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "Todos").mkdir(parents=True)

    def boom(*_: object) -> str:
        raise RuntimeError("nope")

    monkeypatch.setattr("common.scripts.jot_lib.getGitBranchNameOrFail", boom)
    monkeypatch.setattr("common.scripts.jot_lib.getGitRecentCommitHashes", boom)
    monkeypatch.setattr("common.scripts.jot_lib.getGitUncommittedFilenames", boom)
    monkeypatch.setattr("common.scripts.jot_lib.todo_scanOpen", boom)
    monkeypatch.setattr("common.scripts.jot_lib.jot_launchPhase2Window", lambda: 0)

    def fake_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=str(repo) + "\n", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="INSTR", stderr="")

    monkeypatch.setattr(_jot_mod.subprocess, "run", fake_run)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot recover", "cwd": str(repo)}))
    # Test action: invoke.
    rc = _jot_mod.jot_main()
    # Test verification: rc=0 + every safe-wrapped value rendered as "(unavailable)".
    assert rc == 0
    files = list((repo / "Todos").glob("*_input.txt"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "Branch: (unavailable)" in text
    assert "Commits: (unavailable)" in text
    assert "Uncommitted: (unavailable)" in text
    assert "## Open TODO Files\n(unavailable)" in text

def test_empty_string_is_rejected(monkeypatch, capsys):
    # Scenario: empty string has no valid prefix; must be rejected
    # Setup:
    calls: list[str] = []
    monkeypatch.setattr(shutil, "rmtree", lambda path, ignore_errors=False: calls.append(path))

    # Test action:
    todo_sessionEnd("")

    # Test verification:
    assert calls == []
    err = capsys.readouterr().err
    assert "[todo-session-end] refusing to rm unexpected path:" in err


def test_nonexistent_valid_path_is_silently_ignored(monkeypatch, capsys):
    # Scenario: valid prefix but path does not exist; ignore_errors=True swallows it
    # Setup: rmtree with ignore_errors=True must not raise on missing path
    deleted: list[str] = []

    def fake_rmtree(path, ignore_errors=False):
        # Simulate real rmtree behaviour: no-op when ignore_errors=True
        assert ignore_errors is True
        deleted.append(path)

    monkeypatch.setattr(shutil, "rmtree", fake_rmtree)

    # Test action: path looks valid but does not exist on disk
    todo_sessionEnd("/tmp/todo.does-not-exist-1234")

    # Test verification: rmtree was still called (caller swallows the error)
    assert deleted == ["/tmp/todo.does-not-exist-1234"]
    assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# Valid /tmp/todo.X prefix
# ---------------------------------------------------------------------------


def test_valid_tmp_prefix_calls_rmtree(monkeypatch, capsys):
    # Scenario: valid /tmp/todo.X path delegates removal to shutil.rmtree
    # Setup: capture rmtree calls
    calls: list[tuple] = []

    def fake_rmtree(path, ignore_errors=False):
        calls.append((path, ignore_errors))

    monkeypatch.setattr(shutil, "rmtree", fake_rmtree)

    # Test action:
    todo_sessionEnd("/tmp/todo.abc123")

    # Test verification:
    assert calls == [("/tmp/todo.abc123", True)]
    assert capsys.readouterr().err == ""


def test_valid_tmp_prefix_suffix_variation(monkeypatch):
    # Scenario: /tmp/todo. with a different suffix is also accepted
    # Setup:
    calls: list[str] = []
    monkeypatch.setattr(shutil, "rmtree", lambda path, ignore_errors=False: calls.append(path))

    # Test action:
    todo_sessionEnd("/tmp/todo.xyz-session-99")

    # Test verification:
    assert calls == ["/tmp/todo.xyz-session-99"]


# ---------------------------------------------------------------------------
# Valid /private/tmp/todo.X prefix
# ---------------------------------------------------------------------------


def test_valid_private_tmp_prefix_calls_rmtree(monkeypatch, capsys):
    # Scenario: valid /private/tmp/todo.X path (macOS real path) is accepted
    # Setup:
    calls: list[str] = []
    monkeypatch.setattr(shutil, "rmtree", lambda path, ignore_errors=False: calls.append(path))

    # Test action:
    todo_sessionEnd("/private/tmp/todo.session42")

    # Test verification:
    assert calls == ["/private/tmp/todo.session42"]
    assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# Invalid prefix - dir untouched, stderr warning emitted
# ---------------------------------------------------------------------------


def test_invalid_prefix_prints_stderr_and_skips_rmtree(monkeypatch, capsys):
    # Scenario: path with unrecognised prefix is rejected; rmtree not called
    # Setup:
    calls: list[str] = []
    monkeypatch.setattr(shutil, "rmtree", lambda path, ignore_errors=False: calls.append(path))

    # Test action:
    todo_sessionEnd("/var/tmp/todo.sneaky")

    # Test verification:
    assert calls == []
    err = capsys.readouterr().err
    assert "[todo-session-end] refusing to rm unexpected path: /var/tmp/todo.sneaky" in err


def test_invalid_prefix_leaves_directory_intact(monkeypatch, tmp_path, capsys):
    # Scenario: directory with bad prefix must not be removed from the filesystem
    # Setup: a real directory that should NOT be touched
    bad_dir = tmp_path / "evil"
    bad_dir.mkdir()
    # Bypass the prefix by using a path string that does NOT match valid prefixes
    fake_bad_path = str(bad_dir)

    monkeypatch.setattr(shutil, "rmtree", shutil.rmtree)  # use real rmtree to detect any deletion

    # Test action:
    todo_sessionEnd(fake_bad_path)

    # Test verification: directory still exists because prefix was invalid
    assert bad_dir.exists()



def test_missing_args_returns_early(tmp_path: Path, capsys) -> None:
    # Scenario: all three required args are empty strings
    # Setup: no filesystem state needed
    # Test action: call with empty strings
    rc = todo_stop("", "", "")
    # Test verification: must not raise; logs to stderr; returns 0
    captured = capsys.readouterr()
    assert rc == 0
    assert "[todo-stop] missing args" in captured.err


def _make_tmpdir(tmp_path: Path, tmux_target: str = "%42") -> Path:
    """Write a minimal per-invocation tmpdir with tmux_target sidecar."""
    d = tmp_path / "todo.XXXX"
    d.mkdir()
    (d / "tmux_target").write_text(f"{tmux_target}\n")
    return d


def test_missing_state_dir_returns_early(tmp_path: Path, capsys) -> None:
    # Scenario: input_file and tmpdir_inv present but state_dir empty
    # Setup:
    inv = _make_tmpdir(tmp_path)
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action:
    rc = todo_stop(str(input_file), str(inv), "")
    # Test verification:
    captured = capsys.readouterr()
    assert rc == 0
    assert "[todo-stop] missing args" in captured.err


# ---------------------------------------------------------------------------
# tmux_target sidecar retry / failure
# ---------------------------------------------------------------------------


def test_empty_sidecar_logs_and_returns(tmp_path: Path, capsys) -> None:
    # Scenario: tmux_target file exists but is empty after all retries
    # Setup:
    inv = tmp_path / "inv"
    inv.mkdir()
    (inv / "tmux_target").write_text("")       # empty — no pane id
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action: patch time.sleep so test is fast
    with patch("common.scripts.todo_lib.time.sleep"):
        rc = todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    captured = capsys.readouterr()
    assert rc == 0
    assert "tmux_target sidecar empty" in captured.err


def test_missing_sidecar_file_logs_and_returns(tmp_path: Path, capsys) -> None:
    # Scenario: tmux_target file does not exist at all
    # Setup:
    inv = tmp_path / "inv"
    inv.mkdir()
    # no tmux_target written
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action:
    with patch("common.scripts.todo_lib.time.sleep"):
        rc = todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    captured = capsys.readouterr()
    assert rc == 0
    assert "tmux_target sidecar empty" in captured.err


# ---------------------------------------------------------------------------
# Audit log — SUCCESS path
# ---------------------------------------------------------------------------


def test_processed_marker_writes_success_to_audit(tmp_path: Path) -> None:
    # Scenario: input.txt first line starts with "PROCESSED:"
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\nsome other content\n")
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane"),
        patch("common.scripts.todo_lib.tmux_retile"),
    ):
        rc = todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    assert rc == 0
    audit = (state_dir / "audit.log").read_text()
    assert "SUCCESS" in audit
    assert str(input_file) in audit


def test_processed_marker_removes_input_file(tmp_path: Path) -> None:
    # Scenario: SUCCESS path should delete the input file
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane"),
        patch("common.scripts.todo_lib.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification: file must be gone
    assert not input_file.exists()


# ---------------------------------------------------------------------------
# Audit log — FAIL paths
# ---------------------------------------------------------------------------


def test_no_processed_marker_writes_fail_to_audit(tmp_path: Path) -> None:
    # Scenario: input.txt exists but first line lacks PROCESSED:
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("still pending\n")
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane"),
        patch("common.scripts.todo_lib.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    audit = (state_dir / "audit.log").read_text()
    assert "FAIL" in audit
    assert "no PROCESSED marker" in audit


def test_no_processed_marker_does_not_remove_input_file(tmp_path: Path) -> None:
    # Scenario: FAIL path must NOT delete the input file (only SUCCESS deletes it)
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("still pending\n")
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane"),
        patch("common.scripts.todo_lib.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    assert input_file.exists()


def test_missing_input_file_writes_fail_missing_to_audit(tmp_path: Path) -> None:
    # Scenario: input.txt does not exist at all
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "nonexistent_input.txt"
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane"),
        patch("common.scripts.todo_lib.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    audit = (state_dir / "audit.log").read_text()
    assert "FAIL" in audit
    assert "input.txt missing" in audit


# ---------------------------------------------------------------------------
# Audit rotation
# ---------------------------------------------------------------------------


def test_audit_rotated_when_over_1000_lines(tmp_path: Path) -> None:
    # Scenario: audit.log exceeds 1000 lines; must be trimmed to 1000
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    audit = state_dir / "audit.log"
    # Write 1005 lines
    audit.write_text("\n".join(f"line {i}" for i in range(1005)) + "\n")
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane"),
        patch("common.scripts.todo_lib.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification: line count must be <= 1000
    line_count = len([l for l in audit.read_text().splitlines() if l])
    assert line_count <= 1000


# ---------------------------------------------------------------------------
# tmux pane kill (side-effect verification)
# ---------------------------------------------------------------------------


def test_kill_pane_called_with_correct_target(tmp_path: Path) -> None:
    # Scenario: tmux_killPane must be called with the pane id from sidecar
    # Setup:
    inv = _make_tmpdir(tmp_path, tmux_target="%99")
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    kill_mock = MagicMock(return_value=0)
    retile_mock = MagicMock(return_value=0)
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane", kill_mock),
        patch("common.scripts.todo_lib.tmux_retile", retile_mock),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    kill_mock.assert_called_once_with("%99")


def test_retile_called_with_todo_todos_window(tmp_path: Path) -> None:
    # Scenario: tmux_retile must target "todo:todos" after killing pane
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    retile_mock = MagicMock(return_value=0)
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane"),
        patch("common.scripts.todo_lib.tmux_retile", retile_mock),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    retile_mock.assert_called_once_with("todo:todos")


def test_state_dir_created_if_absent(tmp_path: Path) -> None:
    # Scenario: state_dir does not pre-exist; function must create it
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "new_state_dir"
    # Do NOT create state_dir
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane"),
        patch("common.scripts.todo_lib.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    assert state_dir.is_dir()
    assert (state_dir / "audit.log").is_file()


def test_returns_empty_list_when_todos_dir_missing(tmp_path: Path) -> None:
    # Scenario: target dir has no Todos/ subdir at all.
    # Setup: tmp_path is empty (no Todos/).
    # Test action: invoke todo_scanOpen on the bare target.
    result = todo_scanOpen(tmp_path)
    # Test verification: returns empty list, never raises.
    assert result == []


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_returns_empty_list_when_todos_dir_has_no_markdown(tmp_path: Path) -> None:
    # Scenario: Todos/ exists but contains no .md files.
    # Setup: create Todos/ with one non-md file.
    todos = tmp_path / "Todos"
    todos.mkdir()
    _write(todos / "notes.txt", "status: open\n")
    # Test action: scan.
    result = todo_scanOpen(tmp_path)
    # Test verification: non-md files are ignored.
    assert result == []


def test_returns_only_files_with_status_open_in_frontmatter(tmp_path: Path) -> None:
    # Scenario: mixed statuses across multiple .md files.
    # Setup: three TODOs — open, closed, open.
    todos = tmp_path / "Todos"
    _write(todos / "a.md", "---\nstatus: open\n---\nbody\n")
    _write(todos / "b.md", "---\nstatus: closed\n---\nbody\n")
    _write(todos / "c.md", "---\nstatus: open\n---\nbody\n")
    # Test action: scan.
    result = todo_scanOpen(tmp_path)
    # Test verification: only the two open files appear.
    names = sorted(Path(p).name for p in result)
    assert names == ["a.md", "c.md"]


def test_results_are_sorted_alphabetically_like_bash_glob(tmp_path: Path) -> None:
    # Scenario: bash `for f in Todos/*.md` yields glob order (alphabetical).
    # Setup: create files in non-alphabetical creation order.
    todos = tmp_path / "Todos"
    for name in ("z.md", "a.md", "m.md"):
        _write(todos / name, "status: open\n")
    # Test action: scan.
    result = todo_scanOpen(tmp_path)
    # Test verification: returned order is alphabetical by filename.
    names = [Path(p).name for p in result]
    assert names == ["a.md", "m.md", "z.md"]


def test_status_open_must_anchor_at_line_start(tmp_path: Path) -> None:
    # Scenario: bash uses `grep '^status: open'` — embedded matches must NOT count.
    # Setup: file whose only mention of "status: open" is mid-line.
    todos = tmp_path / "Todos"
    _write(todos / "x.md", "---\nnote: previous status: open was wrong\n---\n")
    # Test action: scan.
    result = todo_scanOpen(tmp_path)
    # Test verification: non-anchored mention is rejected.
    assert result == []


def test_only_first_ten_lines_are_inspected(tmp_path: Path) -> None:
    # Scenario: bash uses `head -10` — status: open beyond line 10 must be ignored.
    # Setup: file with status: open on line 12.
    todos = tmp_path / "Todos"
    body = "\n".join(["filler"] * 11 + ["status: open", "more"])
    _write(todos / "late.md", body)
    # Test action: scan.
    result = todo_scanOpen(tmp_path)
    # Test verification: late status is not picked up.
    assert result == []


def test_returns_absolute_paths(tmp_path: Path) -> None:
    # Scenario: callers (jot_main) feed result into a markdown report; path
    # must be unambiguous regardless of cwd.
    # Setup: one open TODO.
    todos = tmp_path / "Todos"
    _write(todos / "only.md", "status: open\n")
    # Test action: scan with an absolute target_dir.
    result = todo_scanOpen(tmp_path)
    # Test verification: every returned path is absolute and points at the file.
    assert len(result) == 1
    p = Path(result[0])
    assert p.is_absolute()
    assert p.name == "only.md"


def test_accepts_string_path_argument(tmp_path: Path) -> None:
    # Scenario: bash callers pass plain strings; Python signature must accept
    # both str and Path (parity with `scan_open_todos "$REPO_ROOT"`).
    # Setup: one open TODO.
    todos = tmp_path / "Todos"
    _write(todos / "only.md", "status: open\n")
    # Test action: pass a str, not a Path.
    result = todo_scanOpen(str(tmp_path))
    # Test verification: works the same.
    assert len(result) == 1



# --- todo_sessionStart ---

from unittest.mock import call, patch

import pytest

# Workspace sys.path setup so import resolves without installing.



# ---------------------------------------------------------------------------
# Scenario: missing args
# ---------------------------------------------------------------------------

def test_missing_input_file_returns_0(tmp_path, capsys):
    # Scenario: both args absent (input_file is empty string)
    # Setup: no files needed
    # Test action:
    rc = todo_sessionStart("", str(tmp_path))
    # Test verification:
    assert rc == 0
    assert "[todo-session-start]" in capsys.readouterr().err


def test_missing_tmpdir_inv_returns_0(tmp_path, capsys):
    # Scenario: tmpdir_inv is empty string
    # Setup: a real input file so only tmpdir is missing
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    # Test action:
    rc = todo_sessionStart(str(input_file), "")
    # Test verification:
    assert rc == 0
    assert "[todo-session-start]" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Scenario: tmux_target sidecar absent
# ---------------------------------------------------------------------------

def test_missing_sidecar_returns_0(tmp_path, capsys):
    # Scenario: tmpdir exists but tmux_target file is never written
    # Setup: input file present, no tmux_target sidecar
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    # Test action: patch sleep to avoid 1s delay (5 * 0.2)
    with patch("common.scripts.todo_lib.time.sleep"):
        rc = todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification:
    assert rc == 0
    assert "tmux_target sidecar empty" in capsys.readouterr().err


def test_empty_sidecar_returns_0(tmp_path, capsys):
    # Scenario: tmux_target file exists but is empty
    # Setup:
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    (tmpdir / "tmux_target").write_text("")
    # Test action:
    with patch("common.scripts.todo_lib.time.sleep"):
        rc = todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification:
    assert rc == 0
    assert "tmux_target sidecar empty" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Scenario: Claude TUI not ready
# ---------------------------------------------------------------------------

def test_claude_not_ready_returns_1(tmp_path, capsys):
    # Scenario: sidecar present but tmux_waitForClaudeReadiness returns 1
    # Setup:
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    (tmpdir / "tmux_target").write_text("%42\n")
    # Test action:
    with patch("common.scripts.todo_lib.tmux_waitForClaudeReadiness", return_value=1):
        rc = todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification:
    assert rc == 1
    assert "claude TUI not ready" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Scenario: happy path
# ---------------------------------------------------------------------------

def test_happy_path_sends_prompt(tmp_path):
    # Scenario: all conditions met; expect jot_sendPrompt called with correct args
    # Setup:
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    (tmpdir / "tmux_target").write_text("%42\n")
    # Test action:
    with patch("common.scripts.todo_lib.tmux_waitForClaudeReadiness", return_value=0), \
         patch("common.scripts.todo_lib.jot_sendPrompt", return_value=0) as mock_send:
        rc = todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification:
    assert rc == 0
    mock_send.assert_called_once_with("%42", str(input_file))


def test_happy_path_propagates_send_rc(tmp_path):
    # Scenario: jot_sendPrompt returns nonzero; function should propagate it
    # Setup:
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    (tmpdir / "tmux_target").write_text("%99\n")
    # Test action:
    with patch("common.scripts.todo_lib.tmux_waitForClaudeReadiness", return_value=0), \
         patch("common.scripts.todo_lib.jot_sendPrompt", return_value=3):
        rc = todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification:
    assert rc == 3


def test_sidecar_read_strips_whitespace(tmp_path):
    # Scenario: sidecar has trailing newline; pane id must be stripped before use
    # Setup:
    input_file = tmp_path / "input.txt"
    input_file.write_text("content")
    tmpdir = tmp_path / "inv"
    tmpdir.mkdir()
    (tmpdir / "tmux_target").write_text("  %7  \n")
    # Test action:
    with patch("common.scripts.todo_lib.tmux_waitForClaudeReadiness", return_value=0) as mock_wait, \
         patch("common.scripts.todo_lib.jot_sendPrompt", return_value=0):
        todo_sessionStart(str(input_file), str(tmpdir))
    # Test verification: pane id passed to readiness check must be stripped
    mock_wait.assert_called_once_with("%7")
