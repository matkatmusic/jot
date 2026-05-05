"""RED tests for todo_scanOpen migration of bash scan_open_todos.

Tests authored from intent + bash source (no paired bash _tests existed —
RELAXED_COVERAGE per migration plan). Each test isolates one behavior using
tmp_path; shape per RED_GREEN_TDD.md (Scenario / Setup / Test action /
Test verification).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Standard temp file header: make _migration_workspace importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp_todo_scanOpen import todo_scanOpen  # noqa: E402


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_returns_empty_list_when_todos_dir_missing(tmp_path: Path) -> None:
    # Scenario: target dir has no Todos/ subdir at all.
    # Setup: tmp_path is empty (no Todos/).
    # Test action: invoke todo_scanOpen on the bare target.
    result = todo_scanOpen(tmp_path)
    # Test verification: returns empty list, never raises.
    assert result == []


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
