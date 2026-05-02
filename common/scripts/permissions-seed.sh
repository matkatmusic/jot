# permissions-seed.sh - bash shim. Delegates to permissions_seed_cli.py.
# See permissions_seed_cli.py for the seed contract. Kept source-able
# so existing callers work unmodified; remove once all 4 sourcers are
# themselves migrated to Python (MIGRATION_TO_PYTHON.md).

_perm_seed_cli="$(dirname "${BASH_SOURCE[0]}")/permissions_seed_cli.py"

permissions_seed() {
  local installed="${1:?permissions_seed: installed required}"
  local default="${2:?permissions_seed: default required}"
  local default_sha_file="${3:?permissions_seed: default_sha_file required}"
  local prior_sha_file="${4:?permissions_seed: prior_sha_file required}"
  local log_file="${5:-}"
  local log_prefix="${6:-plugin}"
  local args=(seed "$installed" "$default" "$default_sha_file" "$prior_sha_file" \
              --log-prefix "$log_prefix")
  if [ -n "$log_file" ]; then
    args+=(--log-file "$log_file")
  fi
  python3 "$_perm_seed_cli" "${args[@]}"
}
