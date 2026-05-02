# claude-launcher.sh - bash shim. Delegates to common/scripts/claude_launcher_cli.py.
# See claude_launcher_cli.py for the build-claude-cmd contract. Kept
# source-able so existing callers work unmodified; remove once all
# 4 sourcers are themselves migrated to Python (MIGRATION_TO_PYTHON.md).

_claude_launcher_cli="$(dirname "${BASH_SOURCE[0]}")/claude_launcher_cli.py"

build_claude_cmd() {
  python3 "$_claude_launcher_cli" build-claude-cmd "$@"
}
