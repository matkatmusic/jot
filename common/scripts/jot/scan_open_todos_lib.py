"""List open TODO files under a target directory's `Todos/` folder.

Public API:
    iterOpenTodos(target_dir) -> Iterator[Path]
        Yield paths of <target_dir>/Todos/*.md whose first 10 lines
        contain a `^status: open` line. Empty iterator if Todos/ is
        missing or no files match.

Migrated from skills/jot/scripts/scan-open-todos.sh per
MIGRATION_TO_PYTHON.md. The bash version used
    head -10 "$f" | grep -q '^status: open' 2>/dev/null
which silenced grep's SIGPIPE-on-`head` artifact. Direct file reads
in Python eliminate the pipeline entirely, so no error suppression
is needed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator, Union

_OPEN_LINE = "status: open"
_LINE_BUDGET = 10


def iterOpenTodos(target_dir: Union[Path, str]) -> Iterator[Path]:
    """Yield paths of `*.md` files under `<target_dir>/Todos/` that
    declare `status: open` in their first 10 lines.

    Order is sorted-by-name (deterministic). Directories matching
    `*.md` and non-`.md` files are skipped. A missing `Todos/`
    directory yields nothing.
    """
    todos = Path(target_dir) / "Todos"
    if not todos.is_dir():
        return
    for f in sorted(todos.glob("*.md")):
        if f.is_file() and _hasOpenStatus(f):
            yield f


def _hasOpenStatus(path: Path) -> bool:
    """True iff `^status: open` (exact, no leading whitespace, no
    trailing content) appears within the file's first 10 lines."""
    try:
        with path.open() as fh:
            for i, line in enumerate(fh):
                if i >= _LINE_BUDGET:
                    return False
                if line.rstrip("\n") == _OPEN_LINE:
                    return True
    except OSError:
        return False
    return False
