#!/bin/bash
# git.sh — bash shim. Each function delegates to common/scripts/git_cli.py.
# Caller-visible contracts (stdout/stderr/exit codes) match the historic
# bash implementation; see git_cli.py for the contract spec per subcommand.
# Kept as a sourceable file so existing `source git.sh` callers keep working
# until they are themselves migrated to Python (see MIGRATION_TO_PYTHON.md).

_git_cli="$(dirname "${BASH_SOURCE[0]}")/git_cli.py"

git_is_repo()                 { python3 "$_git_cli" is-repo "$@"; }
git_get_repo_root()           { python3 "$_git_cli" repo-root "$@"; }
git_get_branch_name()         { python3 "$_git_cli" branch-name "$@"; }
git_get_recent_commits()      { python3 "$_git_cli" recent-commits "$@"; }
git_get_uncommitted()         { python3 "$_git_cli" uncommitted "$@"; }
git_ensure_gitignore_entry()  { python3 "$_git_cli" ensure-gitignore-entry "$@"; }
