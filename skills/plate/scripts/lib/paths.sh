#!/bin/bash
# paths.sh — sourced by every plate script. Sets PLATE_ROOT and ensures
# the runtime directory exists with .gitignore entry.

plate_discover_root() {
  local git_common_dir
  git_common_dir="$(git rev-parse --git-common-dir 2>/dev/null)" || {
    echo "[plate] not inside a git repository" >&2
    return 1
  }
  PLATE_ROOT="$(cd "$(dirname "$git_common_dir")" && pwd)/.plate"
  export PLATE_ROOT
}

plate_ensure_dirs() {
  mkdir -p "$PLATE_ROOT/instances" "$PLATE_ROOT/dropped" "$PLATE_ROOT/inputs"
  local repo_root
  repo_root="$(dirname "$PLATE_ROOT")"
  if ! grep -qxF '.plate/' "$repo_root/.gitignore" 2>/dev/null; then
    printf '\n.plate/\n' >> "$repo_root/.gitignore"
  fi
}

# plate_spawn_terminal_if_needed: open Terminal.app attached to the plate
# session on first run, if no tmux client is currently attached. macOS only.
# On non-Darwin hosts or when osascript is missing, no-op and log a hint.
# Requires: $LOG_FILE in caller's scope (optional; silent fallback if unset).
plate_spawn_terminal_if_needed() {
  local clients
  clients=$(tmux list-clients -t '=plate' 2>/dev/null || true)
  if [ -n "$clients" ]; then
    return 0
  fi
  case "${OSTYPE:-}" in
    darwin*)
      if ! command -v osascript >/dev/null 2>&1; then
        printf '%s plate: osascript unavailable; attach manually via `tmux attach -t plate`\n' \
          "$(date -Iseconds)" >> "${LOG_FILE:-/dev/null}" 2>/dev/null || true
        return 0
      fi
      osascript >/dev/null 2>&1 <<'OSA' &
tell application "Terminal"
  do script "tmux attach -t plate"
  set frontmost of window 1 to false
end tell
OSA
      ;;
    *)
      printf '%s plate: non-Darwin host; attach manually via `tmux attach -t plate`\n' \
        "$(date -Iseconds)" >> "${LOG_FILE:-/dev/null}" 2>/dev/null || true
      ;;
  esac
}

# plate_seed_permissions: three-state first-run / upgrade seeder for the
# user-editable permissions allowlist. Mirrors jot_seed_permissions.
#
# Args:
#   $1 installed_file    ${CLAUDE_PLUGIN_DATA}/permissions.local.json
#   $2 default_file      ${CLAUDE_PLUGIN_ROOT}/assets/permissions.default.json
#   $3 default_sha_file  ${CLAUDE_PLUGIN_ROOT}/assets/permissions.default.json.sha256
#   $4 prior_sha_file    ${CLAUDE_PLUGIN_DATA}/permissions.default.sha256
#
# Three states:
#   (1) installed MISSING → copy default, record prior_sha.
#   (2) installed sha == prior_sha → user untouched, safe to upgrade.
#   (3) installed sha differs → user-edited, leave alone (log once per upgrade).
plate_seed_permissions() {
  local installed="$1" default="$2" default_sha_file="$3" prior_sha_file="$4"
  local current_default_sha installed_sha prior_sha

  if [ ! -f "$default" ] || [ ! -f "$default_sha_file" ]; then
    printf '%s plate: bundled permissions default missing at %s — cannot seed\n' \
      "$(date -Iseconds)" "$default" >> "${LOG_FILE:-/dev/null}" 2>/dev/null || true
    return 0
  fi
  current_default_sha=$(awk '{print $1}' "$default_sha_file")
  mkdir -p "$(dirname "$installed")" 2>/dev/null || true

  # State 1: nothing installed
  if [ ! -f "$installed" ]; then
    cp "$default" "$installed"
    printf '%s\n' "$current_default_sha" > "$prior_sha_file"
    printf '%s plate: seeded %s from bundled default (sha=%s)\n' \
      "$(date -Iseconds)" "$installed" "$current_default_sha" >> "${LOG_FILE:-/dev/null}" 2>/dev/null || true
    return 0
  fi

  installed_sha=$(shasum -a 256 "$installed" 2>/dev/null | awk '{print $1}')
  prior_sha=$([ -f "$prior_sha_file" ] && awk '{print $1}' "$prior_sha_file" || echo "")

  if [ "$installed_sha" = "$current_default_sha" ]; then
    return 0
  fi

  # State 2: user never touched it
  if [ -n "$prior_sha" ] && [ "$installed_sha" = "$prior_sha" ]; then
    cp "$default" "$installed"
    printf '%s\n' "$current_default_sha" > "$prior_sha_file"
    printf '%s plate: upgraded %s to new bundled default (was %s, now %s)\n' \
      "$(date -Iseconds)" "$installed" "$prior_sha" "$current_default_sha" >> "${LOG_FILE:-/dev/null}" 2>/dev/null || true
    return 0
  fi

  # State 3: user-edited
  if [ "$prior_sha" != "$current_default_sha" ]; then
    printf '%s plate: %s is user-edited; bundled default updated — diff manually. installed_sha=%s prior_sha=%s current_default_sha=%s\n' \
      "$(date -Iseconds)" "$installed" "$installed_sha" "$prior_sha" "$current_default_sha" >> "${LOG_FILE:-/dev/null}" 2>/dev/null || true
    printf '%s\n' "$current_default_sha" > "$prior_sha_file"
  fi
  return 0
}
