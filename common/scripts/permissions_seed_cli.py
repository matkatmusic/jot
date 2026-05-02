"""argparse dispatcher backing common/scripts/permissions-seed.sh.

Subcommand:
  seed <installed> <default> <default_sha_file> <prior_sha_file>
       [--log-file PATH] [--log-prefix STR]
      Mirrors `permissions_seed` in permissions-seed.sh. Always
      exits 0 (logging is best-effort by contract).
"""
from __future__ import annotations

import argparse
import sys

from permissions_seed_lib import DEFAULT_LOG_PREFIX, permissionsSeed


def _cmd_seed(args: argparse.Namespace) -> int:
    permissionsSeed(
        installed=args.installed,
        default=args.default,
        default_sha_file=args.default_sha_file,
        prior_sha_file=args.prior_sha_file,
        log_file=args.log_file,
        log_prefix=args.log_prefix,
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="permissions_seed_cli", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("seed")
    p.add_argument("installed")
    p.add_argument("default")
    p.add_argument("default_sha_file")
    p.add_argument("prior_sha_file")
    p.add_argument("--log-file", default=None)
    p.add_argument("--log-prefix", default=DEFAULT_LOG_PREFIX)
    p.set_defaults(func=_cmd_seed)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
