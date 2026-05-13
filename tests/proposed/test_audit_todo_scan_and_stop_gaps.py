from __future__ import annotations

from pathlib import Path

import pytest

from common.scripts import jot_lib
from common.scripts import todo_lib


def test_jot_rotateAudit_removes_temp_trim_file_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scenario: audit rotation creates a temporary trim file, then the final
    # replace step fails.
    # Setup: create an oversized audit log so rotation enters the trim path.
    audit_log = tmp_path / "audit.log"
    audit_log.write_text("one\ntwo\nthree\n", encoding="utf-8")

    def failReplace(_tmp_name: str, _audit_log: Path) -> None:
        raise RuntimeError("replace failed after temp file was written")

    monkeypatch.setattr(jot_lib.os, "replace", failReplace)

    # Test action: rotate the audit log and let the replace failure escape.
    with pytest.raises(RuntimeError, match="replace failed"):
        jot_lib.jot_rotateAudit(audit_log, max_lines=1)

    # Test verification: the temporary trim sidecar was removed during cleanup.
    assert list(tmp_path.glob(".audit.*.trim")) == []


def test_todo_has_open_status_returns_false_when_markdown_read_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scenario: a markdown TODO exists, but reading it fails with OSError.
    # Setup: patch Path.open so the helper sees the same failure as an
    # unreadable or disappearing file.
    todo_file = tmp_path / "Todos" / "broken.md"
    todo_file.parent.mkdir()
    todo_file.write_text("status: open\n", encoding="utf-8")

    def failOpen(_path: Path, *args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "open", failOpen)

    # Test action: ask whether the file has open status.
    result = todo_lib._todo_has_open_status(todo_file)

    # Test verification: read failures are treated as not-open, not raised.
    assert result is False


def test_todo_stop_returns_before_background_pane_cleanup_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scenario: todo_stop should return before the daemon cleanup thread kills
    # the tmux pane and retiles the window.
    # Setup: provide a processed input file and a tmux_target sidecar.
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n", encoding="utf-8")
    tmpdir_inv = tmp_path / "todo.inv"
    tmpdir_inv.mkdir()
    (tmpdir_inv / "tmux_target").write_text("%7\n", encoding="utf-8")
    state_dir = tmp_path / ".todo-state"

    cleanup_calls: list[str] = []
    started_threads: list[str] = []

    class FakeThread:
        def __init__(self, target, daemon: bool) -> None:
            self.target = target
            self.daemon = daemon

        def start(self) -> None:
            started_threads.append("started")

    monkeypatch.setattr(jot_lib, "jot_rotateAudit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(todo_lib.threading, "Thread", FakeThread)
    monkeypatch.setattr(todo_lib, "tmux_killPane", lambda _pane: cleanup_calls.append("kill"))
    monkeypatch.setattr(todo_lib, "tmux_retile", lambda _target: cleanup_calls.append("retile"))

    # Test action: run the stop hook.
    result = todo_lib.todo_stop(str(input_file), str(tmpdir_inv), str(state_dir))

    # Test verification: the hook returned successfully before cleanup ran.
    assert result == 0
    assert started_threads == ["started"]
    assert cleanup_calls == []
