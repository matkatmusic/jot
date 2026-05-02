"""argparse dispatcher backing common/scripts/claude-launcher.sh.

Subcommand:
  build-claude-cmd <settings_out> <allow_json> <hooks_json_file> <cwd> [add_dir ...]
      Mirrors `build_claude_cmd` in claude-launcher.sh. Writes the
      settings JSON to <settings_out>, prints the resolved `claude ...`
      command to stdout, and exits 0.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from claude_launcher_lib import buildClaudeCmd


def _cmd_build_claude_cmd(args: argparse.Namespace) -> int:
    cmd = buildClaudeCmd(
        settings_out=Path(args.settings_out),
        allow_json=args.allow_json,
        hooks_json_file=Path(args.hooks_json_file),
        cwd=args.cwd,
        add_dirs=args.add_dirs,
    )
    print(cmd)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claude_launcher_cli", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build-claude-cmd")
    p.add_argument("settings_out")
    p.add_argument("allow_json")
    p.add_argument("hooks_json_file")
    p.add_argument("cwd")
    p.add_argument("add_dirs", nargs="*")
    p.set_defaults(func=_cmd_build_claude_cmd)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
