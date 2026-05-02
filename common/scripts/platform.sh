# platform.sh - bash shim. Delegates to common/scripts/platform_cli.py.
# See platform_cli.py for the spawn-terminal-if-needed contract. Kept
# source-able so existing callers work unmodified; remove once all
# 5 sourcers are themselves migrated to Python (MIGRATION_TO_PYTHON.md).

_platform_cli="$(dirname "${BASH_SOURCE[0]}")/platform_cli.py"

spawn_terminal_if_needed() {
  local session="${1:?spawn_terminal_if_needed: session name required}"
  local log_file="${2:-/dev/null}"
  local log_prefix="${3:-tmux}"
  local maximize="${4:-}"
  local args=(spawn-terminal-if-needed "$session" --log-file "$log_file" --log-prefix "$log_prefix")
  if [ "$maximize" = "yes" ]; then
    args+=(--maximize)
  fi
  python3 "$_platform_cli" "${args[@]}"
}
