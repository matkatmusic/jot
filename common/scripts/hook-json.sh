# hook-json.sh - bash shim. Delegates to common/scripts/hook_json_cli.py.
# See hook_json_cli.py for contracts. Kept source-able so existing
# callers work unmodified; remove once all sourcers are themselves
# migrated to Python (see MIGRATION_TO_PYTHON.md).

_hook_json_cli="$(dirname "${BASH_SOURCE[0]}")/hook_json_cli.py"

emit_block() {
  python3 "$_hook_json_cli" emit-block "$@"
}

# check_requirements must `exit 0` from the *sourcing* shell when any
# required command is missing, to halt the hook before it tries to use
# the missing tool. The Python CLI cannot exit the parent bash, so the
# shim detects non-empty CLI output (i.e. a block JSON was emitted) and
# exits 0 itself. Do not "simplify" this to a one-liner without
# preserving the halt semantics - 9 callers depend on it.
check_requirements() {
  local out
  out=$(python3 "$_hook_json_cli" check-requirements "$@")
  if [ -n "$out" ]; then
    printf '%s\n' "$out"
    exit 0
  fi
}
