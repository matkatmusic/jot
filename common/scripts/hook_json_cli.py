"""argparse dispatcher backing common/scripts/hook-json.sh.

Subcommand contracts:
  emit-block <reason>
      Print the Claude Code block-decision JSON. Always exit 0.

  check-requirements <prefix> <cmd...>
      Probe each <cmd> with shutil.which. If any missing, print the
      block JSON to stdout and exit 0. If all present, print nothing
      and exit 0. The bash shim detects non-empty stdout and `exit 0`s
      itself to halt the sourcing hook (matching the bash original's
      `exit 0` semantics).
"""
from __future__ import annotations

import argparse
import sys

from hook_json_lib import checkRequirements, emitBlockReason


def _cmd_emit_block(args: argparse.Namespace) -> int:
    print(emitBlockReason(args.reason))
    return 0


def _cmd_check_requirements(args: argparse.Namespace) -> int:
    block = checkRequirements(args.prefix, args.cmds)
    if block is not None:
        print(block)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hook_json_cli", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("emit-block")
    p.add_argument("reason")
    p.set_defaults(func=_cmd_emit_block)

    p = sub.add_parser("check-requirements")
    p.add_argument("prefix")
    p.add_argument("cmds", nargs="*")
    p.set_defaults(func=_cmd_check_requirements)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
