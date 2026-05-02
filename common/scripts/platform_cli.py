"""argparse dispatcher backing common/scripts/platform.sh.

Subcommand:
  spawn-terminal-if-needed <session> [--log-file PATH]
                                     [--log-prefix STR]
                                     [--maximize]
      Mirrors `spawn_terminal_if_needed` in platform.sh. Always exits 0.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from platform_lib import (
    DEFAULT_LOG_FILE,
    DEFAULT_LOG_PREFIX,
    spawnTerminalIfNeeded,
)


def _cmd_spawn_terminal_if_needed(args: argparse.Namespace) -> int:
    spawnTerminalIfNeeded(
        session=args.session,
        log_file=Path(args.log_file),
        log_prefix=args.log_prefix,
        maximize=args.maximize,
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="platform_cli", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("spawn-terminal-if-needed")
    p.add_argument("session")
    p.add_argument("--log-file", default=str(DEFAULT_LOG_FILE))
    p.add_argument("--log-prefix", default=DEFAULT_LOG_PREFIX)
    p.add_argument("--maximize", action="store_true")
    p.set_defaults(func=_cmd_spawn_terminal_if_needed)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
