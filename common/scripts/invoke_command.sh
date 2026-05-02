# invoke_command.sh - bash shim. Delegates to common/scripts/invoke_command_cli.py.
# See invoke_command_cli.py for the run contract. Kept source-able so existing
# callers work unmodified; remove once all sourcers are themselves migrated to
# Python (MIGRATION_TO_PYTHON.md). The ${FUNCNAME[1]} capture preserves the
# bash original's caller-name behavior in error messages - bash captures the
# name of whoever called invoke_command, which a Python subprocess can't see.

_invoke_command_cli="$(dirname "${BASH_SOURCE[0]}")/invoke_command_cli.py"

invoke_command() {
  python3 "$_invoke_command_cli" run --caller "${FUNCNAME[1]:-unknown}" -- "$@"
}
