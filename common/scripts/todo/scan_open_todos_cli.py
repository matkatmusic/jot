"""CLI dispatcher backing skills/todo/scripts/scan-open-todos.sh.

Usage: scan_open_todos_cli.py <repo_root>

Prints one line per element of listOpenTodos(repo_root), exits 0.
The single-element fallback ["(none)"] is printed verbatim when
the Todos/ directory is missing or has no *.md files. Mirrors the
behavior of the original bash entry point.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scan_open_todos_lib import listOpenTodos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scan_open_todos_cli", description=__doc__)
    parser.add_argument("repo_root", type=Path)
    args = parser.parse_args(argv)
    for line in listOpenTodos(args.repo_root):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
