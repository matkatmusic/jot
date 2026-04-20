# permissions-seed.sh — three-state first-run / upgrade seeder for a
# user-editable permissions allowlist file.
#
# Source this file and call:
#
#   permissions_seed <installed> <default> <default_sha_file> <prior_sha_file> \
#                    [log_file] [log_prefix]
#
# Arguments:
#   installed         Path the plugin writes on first run (e.g.
#                     ${CLAUDE_PLUGIN_DATA}/permissions.local.json).
#   default           Bundled default shipped with the plugin.
#   default_sha_file  A file containing the sha256 of the bundled default.
#   prior_sha_file    Where this function records the sha of whatever it
#                     last shipped, so it can distinguish user edits from
#                     an unchanged copy on upgrade.
#   log_file          Optional. If unset or empty, logging is silent.
#   log_prefix        Optional. Prefix used in log lines; defaults to "plugin".
#
# Three states:
#   1) installed MISSING           → copy default; record prior_sha.
#   2) installed sha = prior_sha   → user never touched it; safe to overwrite
#                                    with a newer bundled default.
#   3) installed sha ≠ prior_sha   → user edited it. Leave alone. Log once
#                                    per upgrade so user can diff manually.
#
# Extracted from scripts/jot.sh per plans/jot-generalizing-refactor.md (commit 8).

permissions_seed() {
  local installed="$1" default="$2" default_sha_file="$3" prior_sha_file="$4"
  local log_file="${5:-}" log_prefix="${6:-plugin}"
  local current_default_sha installed_sha prior_sha

  _permseed_log() {
    [ -z "$log_file" ] && return 0
    printf '%s %s: %s\n' "$(date -Iseconds)" "$log_prefix" "$1" \
      >> "$log_file" 2>/dev/null || true
  }

  if [ ! -f "$default" ] || [ ! -f "$default_sha_file" ]; then
    _permseed_log "bundled permissions default missing at $default — cannot seed"
    return 0
  fi
  current_default_sha=$(awk '{print $1}' "$default_sha_file")

  if [ ! -f "$installed" ]; then
    cp "$default" "$installed"
    printf '%s\n' "$current_default_sha" > "$prior_sha_file"
    _permseed_log "seeded $installed from bundled default (sha=$current_default_sha)"
    return 0
  fi

  installed_sha=$(shasum -a 256 "$installed" 2>/dev/null | awk '{print $1}')
  prior_sha=$([ -f "$prior_sha_file" ] && awk '{print $1}' "$prior_sha_file" || echo "")

  if [ "$installed_sha" = "$current_default_sha" ]; then
    return 0
  fi

  if [ -n "$prior_sha" ] && [ "$installed_sha" = "$prior_sha" ]; then
    cp "$default" "$installed"
    printf '%s\n' "$current_default_sha" > "$prior_sha_file"
    _permseed_log "upgraded $installed to new bundled default (was $prior_sha, now $current_default_sha)"
    return 0
  fi

  if [ "$prior_sha" != "$current_default_sha" ]; then
    _permseed_log "$installed is user-edited; bundled default updated — diff manually. installed_sha=$installed_sha prior_sha=$prior_sha current_default_sha=$current_default_sha"
    printf '%s\n' "$current_default_sha" > "$prior_sha_file"
  fi
  return 0
}
