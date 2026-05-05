"""Tests for todo_main workspace stub."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _tmp_todo_main as mod  # noqa: E402


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
    monkeypatch.setattr(mod, "_git_get_repo_root", lambda cwd: root)


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
