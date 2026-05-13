from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from common.scripts import todo_lib


class SuccessfulFileLock:
    def __init__(self, _path: str, timeout: int) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


class FailingFileLock:
    def __init__(self, _path: str, timeout: int) -> None:
        pass

    def __enter__(self):
        raise RuntimeError("lock unavailable")

    def __exit__(self, *_args) -> None:
        return None


def makePendingTodoLaunchFile(tmp_path: Path, *, transcript: bool = False) -> Path:
    repo_root = tmp_path / "repo"
    cwd = repo_root / "src"
    cwd.mkdir(parents=True)
    transcript_path = tmp_path / "transcript.txt"
    if transcript:
        transcript_path.write_text("conversation", encoding="utf-8")
    pending_file = tmp_path / "pending.json"
    pending_file.write_text(
        json.dumps(
            {
                "repo_root": str(repo_root),
                "cwd": str(cwd),
                "transcript_path": str(transcript_path if transcript else ""),
                "timestamp": "20260101-120000",
            }
        ),
        encoding="utf-8",
    )
    return pending_file


def installSuccessfulTodoLauncherDoubles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    pane_id: str = "%123",
) -> list[tuple[str, tuple]]:
    calls: list[tuple[str, tuple]] = []
    invocation_dir = tmp_path / "todo.inv"
    invocation_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "plugin-data"))
    monkeypatch.setattr(todo_lib.tempfile, "mkdtemp", lambda prefix: str(invocation_dir))
    monkeypatch.setattr(todo_lib, "FileLock", SuccessfulFileLock)
    monkeypatch.setattr(todo_lib, "git_getBranchNameOrFail", lambda _cwd: "main")
    monkeypatch.setattr(todo_lib, "git_getRecentCommitHashes", lambda _cwd: ["a1", "b2"])
    monkeypatch.setattr(todo_lib, "git_getUncommittedFilenames", lambda _cwd: ["dirty.py"])
    monkeypatch.setattr(todo_lib, "todo_scanOpen", lambda _repo: ["todo.md"])
    monkeypatch.setattr(todo_lib, "bgPermissions_loadClaude", lambda *_a, **_k: '["Read(**)"]')
    monkeypatch.setattr(todo_lib, "claude_buildCmd", lambda *_args: "claude --fake")
    monkeypatch.setattr(todo_lib, "tmux_ensureSession", lambda *args: calls.append(("ensure", args)))
    monkeypatch.setattr(todo_lib, "tmux_splitWorkerPane", lambda *args: pane_id)
    monkeypatch.setattr(todo_lib, "tmux_setPaneTitle", lambda *args: calls.append(("title", args)))
    monkeypatch.setattr(todo_lib, "tmux_retile", lambda *args: calls.append(("retile", args)))
    monkeypatch.setattr(todo_lib, "terminal_spawnIfNeeded", lambda *args: calls.append(("terminal", args)))

    def fakeRun(argv, *args, **kwargs):
        calls.append(("run", tuple(argv)))
        return SimpleNamespace(returncode=0, stdout="rendered instructions\n")

    monkeypatch.setattr(todo_lib.subprocess, "run", fakeRun)
    return calls


# Replaces tests/test_todo_stop.py::test_safe_wrapper_falls_back_to_unavailable
def test_todo_launcher_renders_unavailable_values_when_state_collectors_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scenario: git and open-todo collectors fail while todo_launcher builds
    # the worker input file.
    # Setup: successful outer launch doubles, but failing state collectors.
    pending_file = makePendingTodoLaunchFile(tmp_path)
    installSuccessfulTodoLauncherDoubles(monkeypatch, tmp_path)
    monkeypatch.setattr(todo_lib, "git_getBranchNameOrFail", lambda _cwd: (_ for _ in ()).throw(RuntimeError("branch")))
    monkeypatch.setattr(todo_lib, "git_getRecentCommitHashes", lambda _cwd: (_ for _ in ()).throw(RuntimeError("commits")))
    monkeypatch.setattr(todo_lib, "git_getUncommittedFilenames", lambda _cwd: (_ for _ in ()).throw(RuntimeError("dirty")))
    monkeypatch.setattr(todo_lib, "todo_scanOpen", lambda _repo: (_ for _ in ()).throw(RuntimeError("todos")))

    # Test action: launch the todo worker.
    result = todo_lib.todo_launcher("session-1", "fix bug", str(pending_file))

    # Test verification: the input file records unavailable placeholders.
    assert result == 0
    input_text = (tmp_path / "repo" / "Todos" / "20260101-120000_input.txt").read_text()
    assert input_text.count("(unavailable)") >= 4


def test_todo_launcher_returns_failure_when_worker_pane_id_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    # Scenario: tmux split-window succeeds badly and returns no pane id.
    # Setup: use normal launch doubles except for an empty pane id.
    pending_file = makePendingTodoLaunchFile(tmp_path)
    installSuccessfulTodoLauncherDoubles(monkeypatch, tmp_path, pane_id="")

    # Test action: launch the todo worker.
    result = todo_lib.todo_launcher("session-1", "fix bug", str(pending_file))

    # Test verification: the empty pane id is treated as a launch failure.
    assert result == 1
    assert "empty pane id" in capsys.readouterr().err


def test_todo_launcher_returns_failure_when_tmux_lock_cannot_be_acquired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    # Scenario: the tmux launch lock raises before any pane can be created.
    # Setup: install successful doubles, then replace FileLock with a failing one.
    pending_file = makePendingTodoLaunchFile(tmp_path)
    installSuccessfulTodoLauncherDoubles(monkeypatch, tmp_path)
    monkeypatch.setattr(todo_lib, "FileLock", FailingFileLock)

    # Test action: launch the todo worker.
    result = todo_lib.todo_launcher("session-1", "fix bug", str(pending_file))

    # Test verification: lock failure is converted into return code 1.
    assert result == 1
    assert "failed to acquire tmux-launch lock" in capsys.readouterr().err


# Replaces tests/test_todo_send.py::test_todo_launcher_success
def test_todo_launcher_writes_hooks_sidecar_and_expected_input_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scenario: the happy path should create inspectable launch artifacts,
    # not just call tmux.
    # Setup: install successful doubles and a normal pending file.
    pending_file = makePendingTodoLaunchFile(tmp_path)
    calls = installSuccessfulTodoLauncherDoubles(monkeypatch, tmp_path)

    # Test action: launch the todo worker.
    result = todo_lib.todo_launcher("session-1", "fix bug", str(pending_file))

    # Test verification: generated input content contains the collected state.
    assert result == 0
    input_file = tmp_path / "repo" / "Todos" / "20260101-120000_input.txt"
    input_text = input_file.read_text()
    assert "fix bug" in input_text
    assert "main" in input_text
    assert "dirty.py" in input_text
    assert "todo.md" in input_text

    # Test verification: the tmux target sidecar and hook file were written.
    invocation_dir = tmp_path / "todo.inv"
    hooks_text = (invocation_dir / "hooks.json").read_text()
    tmux_target = (invocation_dir / "tmux_target").read_text().strip()
    assert calls
    hook_run_calls = [call for name, call in calls if name == "run"]
    assert hook_run_calls
    assert input_file.exists()
    assert "todo-session-start" in hooks_text
    assert "todo-stop" in hooks_text
    assert "todo-session-end" in hooks_text
    assert tmux_target == "%123"
