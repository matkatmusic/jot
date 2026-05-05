"""Unit tests for workspace migration of `todoList_main`.

Each test exercises one branch of the entrypoint per RED_GREEN_TDD.md.
"""
from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

# Make the workspace dir importable so we can import the SUT module.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _tmp_todoList_main as sut  # noqa: E402


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
    monkeypatch.setattr(sut, "hookjson_checkRequirements", lambda *a, **k: None)
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
    monkeypatch.setattr(sut, "hookjson_checkRequirements", lambda *a, **k: None)
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
    monkeypatch.setattr(sut, "hookjson_checkRequirements", lambda *a, **k: None)
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
    monkeypatch.setattr(sut, "hookjson_checkRequirements", lambda *a, **k: None)
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
    monkeypatch.setattr(sut, "hookjson_checkRequirements", lambda *a, **k: None)

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
