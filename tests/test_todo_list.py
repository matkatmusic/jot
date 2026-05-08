"""Tests for todo_listMain and todo_scanOpen (list bucket)."""
from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from common.scripts import todo_lib as mod
from common.scripts.todo_lib import todo_listMain, todo_scanOpen

# Bind module alias used throughout the test bodies.
sut = mod


# --- todo_listMain ---


def _setStdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    monkeypatch.setattr(sys, "stdin", StringIO(payload))


def test_non_todoList_prompt_exits_silently(monkeypatch, capsys):
    # Scenario: stdin payload does not mention "/todo-list -> fast-path return.
    # Setup: stdin is unrelated JSON; no git/format calls should occur.
    _setStdin(monkeypatch, json.dumps({"prompt": "/something-else"}))
    monkeypatch.setattr(sut.subprocess, "run", lambda *a, **k: pytest.fail("must not run subprocess"))
    # Test action: invoke entrypoint.
    rc = sut.todo_listMain()
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
    rc = sut.todo_listMain()
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
    rc = sut.todo_listMain()
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
    rc = sut.todo_listMain()
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
    rc = sut.todo_listMain()
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
    rc = sut.todo_listMain()
    # Test verification: emitted reason equals captured formatter stdout verbatim.
    decoded = json.loads(capsys.readouterr().out.strip())
    assert rc == 0
    assert decoded["reason"] == formatted_text


# --- todo_scanOpen ---


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
