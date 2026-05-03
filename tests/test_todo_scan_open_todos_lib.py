"""RED tests for common/scripts/todo/scan_open_todos_lib.listOpenTodos.

Spec (from plans/migration_to_python/skills_todo_scripts_scan-open-todos.sh.md):

The function `listOpenTodos(repo_root)` mirrors the bash original
skills/todo/scripts/scan-open-todos.sh:

  - Computes <repo_root>/Todos.
  - If that directory does not exist: returns ["(none)"].
  - If it exists but contains no *.md files at the top level: returns ["(none)"].
  - Otherwise: returns sorted-by-name absolute paths of every top-level
    *.md file (one entry per file).
  - Subdirectories of Todos/ (e.g. Todos/done/) are NOT descended into.
  - Non-.md files in Todos/ are ignored.
  - Returned paths are always absolute, even when repo_root is relative.
  - Never raises for environmental reasons (returns ["(none)"] on OSError).

Important: this lib is the SIBLING of the already-migrated jot-side
scan_open_todos_lib (which filters by `status: open`). The todo version
has NO status filter — every *.md counts as "open".
"""
from __future__ import annotations

import os
from pathlib import Path

from todo.scan_open_todos_lib import listOpenTodos


def _writeTodo(dir_: Path, name: str, body: str = "x") -> Path:
    """Write a small markdown file with `body` and return its absolute path."""
    p = dir_ / name
    p.write_text(body)
    return p.resolve()


# Scenario: missing Todos/ directory
# Steps: tmp_path is a fresh empty repo with NO Todos/ subdir.
# Expectation: listOpenTodos returns the single sentinel ["(none)"].
def test_missing_todos_dir_returns_none_sentinel(tmp_path: Path) -> None:
    assert listOpenTodos(tmp_path) == ["(none)"]


# Scenario: Todos/ exists but is empty
# Steps: create Todos/ with no entries inside.
# Expectation: listOpenTodos returns ["(none)"].
def test_empty_todos_dir_returns_none_sentinel(tmp_path: Path) -> None:
    (tmp_path / "Todos").mkdir()
    assert listOpenTodos(tmp_path) == ["(none)"]


# Scenario: Todos/ has one *.md file
# Steps: create Todos/foo.md.
# Expectation: returns [abs_path_of_foo.md].
def test_single_md_file_returns_its_absolute_path(tmp_path: Path) -> None:
    todos = tmp_path / "Todos"
    todos.mkdir()
    foo = _writeTodo(todos, "foo.md")
    result = listOpenTodos(tmp_path)
    assert result == [str(foo)]


# Scenario: Todos/ has multiple *.md files
# Steps: create Todos/zebra.md, Todos/alpha.md, Todos/middle.md.
# Expectation: returns the three absolute paths in sorted-by-name order.
def test_multiple_md_files_returned_sorted(tmp_path: Path) -> None:
    todos = tmp_path / "Todos"
    todos.mkdir()
    zebra = _writeTodo(todos, "zebra.md")
    alpha = _writeTodo(todos, "alpha.md")
    middle = _writeTodo(todos, "middle.md")
    result = listOpenTodos(tmp_path)
    assert result == [str(alpha), str(middle), str(zebra)]


# Scenario: Todos/done/*.md files must NOT be included
# Steps: create Todos/active.md and Todos/done/finished.md.
# Expectation: only Todos/active.md is returned (the glob is non-recursive).
def test_done_subdirectory_files_are_excluded(tmp_path: Path) -> None:
    todos = tmp_path / "Todos"
    todos.mkdir()
    active = _writeTodo(todos, "active.md")
    done = todos / "done"
    done.mkdir()
    _writeTodo(done, "finished.md")
    result = listOpenTodos(tmp_path)
    assert result == [str(active)]


# Scenario: non-.md files in Todos/ are ignored
# Steps: create Todos/keep.md and Todos/ignore.txt.
# Expectation: only keep.md is returned.
def test_non_md_files_are_ignored(tmp_path: Path) -> None:
    todos = tmp_path / "Todos"
    todos.mkdir()
    keep = _writeTodo(todos, "keep.md")
    (todos / "ignore.txt").write_text("not a todo")
    (todos / "README").write_text("not a todo either")
    result = listOpenTodos(tmp_path)
    assert result == [str(keep)]


# Scenario: subdirectory whose name ends in .md is not listed as a file
# Steps: create Todos/realfile.md and Todos/dir.md/ (a directory named dir.md).
# Expectation: only realfile.md appears in the result.
def test_directory_with_md_suffix_is_not_listed(tmp_path: Path) -> None:
    todos = tmp_path / "Todos"
    todos.mkdir()
    real = _writeTodo(todos, "realfile.md")
    (todos / "dir.md").mkdir()
    result = listOpenTodos(tmp_path)
    assert result == [str(real)]


# Scenario: sentinel value is exactly "(none)" with parentheses
# Steps: invoke against a repo with no Todos/.
# Expectation: result[0] is the literal string "(none)" — not "None", not "".
def test_none_sentinel_is_exact_string(tmp_path: Path) -> None:
    result = listOpenTodos(tmp_path)
    assert len(result) == 1
    assert result[0] == "(none)"


# Scenario: returned paths are absolute even for a relative repo_root
# Steps: chdir into tmp_path; create Todos/file.md; call listOpenTodos(Path(".")).
# Expectation: returned path is absolute (starts with /).
def test_returned_paths_are_absolute_for_relative_repo_root(tmp_path: Path, monkeypatch) -> None:
    todos = tmp_path / "Todos"
    todos.mkdir()
    _writeTodo(todos, "x.md")
    monkeypatch.chdir(tmp_path)
    result = listOpenTodos(Path("."))
    assert len(result) == 1
    assert os.path.isabs(result[0])
    assert result[0].endswith("/Todos/x.md")


# Scenario: repo_root accepts a string as well as a Path
# Steps: pass tmp_path as a str rather than a Path object.
# Expectation: behaves identically (absolute path returned).
def test_repo_root_accepts_string(tmp_path: Path) -> None:
    todos = tmp_path / "Todos"
    todos.mkdir()
    f = _writeTodo(todos, "s.md")
    result = listOpenTodos(str(tmp_path))
    assert result == [str(f)]


# Scenario: status filter is NOT applied (sibling jot version filters; this one doesn't)
# Steps: create one Todos/closed.md whose body declares "status: closed".
# Expectation: closed.md is still included (todo's spec ignores status).
def test_status_field_is_not_filtered(tmp_path: Path) -> None:
    todos = tmp_path / "Todos"
    todos.mkdir()
    closed = _writeTodo(todos, "closed.md", body="---\nstatus: closed\n---\n")
    result = listOpenTodos(tmp_path)
    assert result == [str(closed)]
