"""Tests for common/scripts/jot/scan_open_todos_lib.py.

Each test exercises one branch of the spec from the original
skills/jot/scripts/scan-open-todos.sh and is designed to fail
loudly if that branch's behavior breaks.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scan_open_todos_lib import iterOpenTodos


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# ── branch 1: missing Todos/ ──────────────────────────────────────────


def test_branch1_no_todos_dir_returns_empty(tmp_path: Path):
    assert list(iterOpenTodos(tmp_path)) == []


# ── branch 2: empty Todos/ ────────────────────────────────────────────


def test_branch2_empty_todos_dir_returns_empty(tmp_path: Path):
    (tmp_path / "Todos").mkdir()
    assert list(iterOpenTodos(tmp_path)) == []


# ── branch 3: open-todo detection ─────────────────────────────────────


def test_branch3_finds_open_todo(tmp_path: Path):
    f = _write(tmp_path / "Todos" / "a.md", "---\nstatus: open\n---\n")
    assert list(iterOpenTodos(tmp_path)) == [f]


def test_branch3_finds_multiple_open_todos(tmp_path: Path):
    a = _write(tmp_path / "Todos" / "a.md", "---\nstatus: open\n---\n")
    b = _write(tmp_path / "Todos" / "b.md", "---\nstatus: open\n---\n")
    c = _write(tmp_path / "Todos" / "c.md", "---\nstatus: open\n---\n")
    result = list(iterOpenTodos(tmp_path))
    assert result == [a, b, c]   # sorted, deterministic


# ── branch 4: skip non-open ───────────────────────────────────────────


def test_branch4_skips_closed_todo(tmp_path: Path):
    _write(tmp_path / "Todos" / "closed.md", "---\nstatus: closed\n---\n")
    assert list(iterOpenTodos(tmp_path)) == []


def test_branch4_skips_no_status_field(tmp_path: Path):
    _write(tmp_path / "Todos" / "raw.md", "# Just a heading\n\nno frontmatter\n")
    assert list(iterOpenTodos(tmp_path)) == []


# ── exact-match: ^status: open anchored ───────────────────────────────


def test_status_must_match_open_exactly(tmp_path: Path):
    _write(tmp_path / "Todos" / "opened.md", "---\nstatus: opened\n---\n")
    assert list(iterOpenTodos(tmp_path)) == []


def test_status_indented_does_not_match(tmp_path: Path):
    # bash regex `^status: open` rejects leading whitespace.
    _write(tmp_path / "Todos" / "indented.md", "---\n  status: open\n---\n")
    assert list(iterOpenTodos(tmp_path)) == []


# ── 10-line cutoff (mirrors `head -10`) ───────────────────────────────


def test_status_open_after_line_10_not_matched(tmp_path: Path):
    # 10 lines of padding, then status: open on line 11 → not matched.
    body = "\n".join(["padding"] * 10) + "\nstatus: open\n"
    _write(tmp_path / "Todos" / "late.md", body)
    assert list(iterOpenTodos(tmp_path)) == []


def test_status_open_on_line_10_is_matched(tmp_path: Path):
    # 9 lines of padding, then status: open on line 10 → matched.
    body = "\n".join(["padding"] * 9) + "\nstatus: open\n"
    f = _write(tmp_path / "Todos" / "edge.md", body)
    assert list(iterOpenTodos(tmp_path)) == [f]


# ── filesystem edge cases ─────────────────────────────────────────────


def test_md_directory_skipped(tmp_path: Path):
    (tmp_path / "Todos").mkdir()
    (tmp_path / "Todos" / "fake.md").mkdir()   # directory matching glob
    assert list(iterOpenTodos(tmp_path)) == []


def test_non_md_files_ignored(tmp_path: Path):
    _write(tmp_path / "Todos" / "notes.txt", "status: open\n")
    assert list(iterOpenTodos(tmp_path)) == []


# ── arg defaulting ────────────────────────────────────────────────────


def test_default_target_is_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    f = _write(tmp_path / "Todos" / "a.md", "---\nstatus: open\n---\n")
    monkeypatch.chdir(tmp_path)
    # Mirrors bash: relative input yields relative output paths.
    result = list(iterOpenTodos("."))
    assert [p.resolve() for p in result] == [f.resolve()]
