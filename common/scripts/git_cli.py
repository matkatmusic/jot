"""argparse dispatcher that backs common/scripts/git.sh.

Each subcommand mirrors the contract of one git.sh function, so the
bash shim can call `python3 git_cli.py <subcmd> "$@"` without changing
caller-visible stdout, stderr, or exit codes.

Subcommand contracts:
  is-repo <dir>                          → exit 0 if repo, 1 otherwise. No output.
  repo-root [dir]                        → print abs path; exit 1 + stderr msg if not in a repo.
  branch-name <dir>                      → print branch; exit 1 + stderr if non-repo or detached HEAD.
  recent-commits <dir>                   → print space-joined hashes; exit 1 + stderr on non-repo / empty repo.
  uncommitted <dir>                      → print space-joined filenames; "None" when clean. Exit 1 if not a repo.
  ensure-gitignore-entry <root> <pat>    → idempotent .gitignore append; no output.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from git_lib import (
    GitError,
    ensureGitignoreEntry,
    getGitBranchNameOrFail,
    getGitRecentCommitHashes,
    getGitRepoRoot,
    getGitUncommittedFilenames,
    isGitRepo,
)


def _cmd_is_repo(args: argparse.Namespace) -> int:
    return 0 if isGitRepo(Path(args.dir)) else 1


def _cmd_repo_root(args: argparse.Namespace) -> int:
    target = Path(args.dir) if args.dir else Path.cwd()
    try:
        print(getGitRepoRoot(target))
    except GitError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def _cmd_branch_name(args: argparse.Namespace) -> int:
    try:
        print(getGitBranchNameOrFail(Path(args.dir)))
    except GitError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def _cmd_recent_commits(args: argparse.Namespace) -> int:
    try:
        hashes = getGitRecentCommitHashes(Path(args.dir))
    except GitError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(" ".join(hashes))
    return 0


def _cmd_uncommitted(args: argparse.Namespace) -> int:
    try:
        files = getGitUncommittedFilenames(Path(args.dir))
    except GitError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("None" if not files else " ".join(files))
    return 0


def _cmd_ensure_gitignore_entry(args: argparse.Namespace) -> int:
    ensureGitignoreEntry(Path(args.repo_root), args.pattern)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="git_cli", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("is-repo")
    p.add_argument("dir")
    p.set_defaults(func=_cmd_is_repo)

    p = sub.add_parser("repo-root")
    p.add_argument("dir", nargs="?", default=None)
    p.set_defaults(func=_cmd_repo_root)

    p = sub.add_parser("branch-name")
    p.add_argument("dir")
    p.set_defaults(func=_cmd_branch_name)

    p = sub.add_parser("recent-commits")
    p.add_argument("dir")
    p.set_defaults(func=_cmd_recent_commits)

    p = sub.add_parser("uncommitted")
    p.add_argument("dir")
    p.set_defaults(func=_cmd_uncommitted)

    p = sub.add_parser("ensure-gitignore-entry")
    p.add_argument("repo_root")
    p.add_argument("pattern")
    p.set_defaults(func=_cmd_ensure_gitignore_entry)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
