"""GREEN implementation of todo_scanOpen — Python port of bash scan_open_todos.

Source bash (jot-plugin-orchestrator.sh lines 1885-1900):
    scan_open_todos() {
        TARGET_DIR="${1:-.}"
        TODOS_DIR="$TARGET_DIR/Todos"
        if [ ! -d "$TODOS_DIR" ]; then
            exit 0
        fi
        for f in "$TODOS_DIR"/*.md; do
            [ -f "$f" ] || continue
            if head -10 "$f" | grep -q '^status: open' 2>/dev/null; then
                echo "$f"
            fi
        done
    }

Behavioral parity:
- Iterates *.md in Todos/ in alphabetical order (bash glob default).
- Matches `^status: open` (anchored, exactly that prefix) within first 10 lines.
- Returns absolute paths.
- Missing Todos/ dir => empty list (the bash `exit 0` was a side-effect bug
  when called via `safe scan_open_todos`; the Python port returns the
  semantically-correct empty result instead of terminating the caller).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Standard temp file header: keep workspace importable when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))


# Scan <target_dir>/Todos/*.md and return absolute paths whose first 10 lines
# contain a line beginning exactly with "status: open".
def todo_scanOpen(target_dir: str | Path = ".") -> list[str]:
    todos_dir = Path(target_dir) / "Todos"
    if not todos_dir.is_dir():
        return []

    open_paths: list[str] = []
    # sorted() mirrors bash glob's lexicographic order — callers depend on
    # stable ordering when this list is rendered into the jot input file.
    for md_path in sorted(todos_dir.glob("*.md")):
        if not md_path.is_file():
            continue
        if _has_open_status(md_path):
            open_paths.append(str(md_path.resolve()))
    return open_paths


# Mirrors `head -10 "$f" | grep -q '^status: open'`: a line within the first
# 10 lines whose start is the literal token "status: open". grep's anchor (^)
# pins the match to column 0; the trailing portion of the line is unconstrained.
def _has_open_status(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= 10:
                    break
                if line.startswith("status: open"):
                    return True
    except OSError:
        return False
    return False
