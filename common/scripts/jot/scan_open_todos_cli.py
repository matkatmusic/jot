"""CLI dispatcher backing skills/jot/scripts/scan-open-todos.sh.

Usage: scan_open_todos_cli.py [target_dir]
   target_dir defaults to "."

Prints one path per line, exits 0. Mirrors the behavior of the
original bash entry point.
"""
from __future__ import annotations

import argparse
import sys

from scan_open_todos_lib import iterOpenTodos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scan_open_todos_cli", description=__doc__)
    parser.add_argument("target_dir", nargs="?", default=".")
    args = parser.parse_args(argv)
    for path in iterOpenTodos(args.target_dir):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
