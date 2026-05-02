"""argparse dispatcher backing common/scripts/invoke_command.sh.

Subcommand:
  run --caller <caller> -- <program> [args...]
      Mirrors `invoke_command` in invoke_command.sh. Use `--` to
      separate the program's argv from this CLI's flags.

Exits with the wrapped command's exit code (or 127 if missing).
"""
from __future__ import annotations

import argparse
import sys

from invoke_command_lib import invokeCommand


def _cmd_run(args: argparse.Namespace) -> int:
    argv = args.argv
    # argparse.REMAINDER preserves the literal `--` separator; strip it so
    # the wrapped program sees only its own argv.
    if argv and argv[0] == "--":
        argv = argv[1:]
    return invokeCommand(caller=args.caller, argv=argv)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="invoke_command_cli", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run")
    p.add_argument("--caller", required=True)
    p.add_argument("argv", nargs=argparse.REMAINDER)
    p.set_defaults(func=_cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "run":
        # Reject empty (or `--`-only) argv lists.
        cleaned = [a for a in args.argv if a != "--"]
        if not cleaned:
            print(
                "invoke_command_cli: run requires a command after --",
                file=sys.stderr,
            )
            return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
