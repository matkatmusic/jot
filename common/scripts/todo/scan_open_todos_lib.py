"""List every TODO file under a repo's `Todos/` directory.

Public API:
    listOpenTodos(repo_root) -> list[str]
        Return absolute paths of every top-level `*.md` file in
        `<repo_root>/Todos/`, sorted by name. If the directory does
        not exist, contains no `*.md` files, or is unreadable, returns
        the single-element list `["(none)"]`.

Migrated from `skills/todo/scripts/scan-open-todos.sh` per
MIGRATION_TO_PYTHON.md. Sibling of `common/scripts/jot/scan_open_todos_lib.py`,
which has a DIFFERENT spec (jot filters by `status: open` in the file
header; this todo version does not — every `*.md` counts).
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

NONE_SENTINEL = "(none)"


def listOpenTodos(repo_root: Union[Path, str]) -> list[str]:
    """Return absolute paths of `<repo_root>/Todos/*.md` (sorted), or
    `[NONE_SENTINEL]` if the dir is missing/empty/unreadable."""
    todos = Path(repo_root) / "Todos"
    try:
        if not todos.is_dir():
            return [NONE_SENTINEL]
        paths = sorted(p for p in todos.glob("*.md") if p.is_file())
    except OSError:
        return [NONE_SENTINEL]
    if not paths:
        return [NONE_SENTINEL]
    return [str(p.resolve()) for p in paths]
