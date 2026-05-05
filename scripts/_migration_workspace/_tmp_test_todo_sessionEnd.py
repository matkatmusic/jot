"""Tests for todo_sessionEnd workspace implementation."""

import shutil

import pytest

from _tmp_todo_sessionEnd import todo_sessionEnd


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


# ---------------------------------------------------------------------------
# Nonexistent valid-prefix path - silently ignored
# ---------------------------------------------------------------------------


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
# Empty string - treated as invalid prefix
# ---------------------------------------------------------------------------


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
