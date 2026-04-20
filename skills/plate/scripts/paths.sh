#!/bin/bash
# paths.sh — plate-specific path discovery and directory setup.

source "${CLAUDE_PLUGIN_ROOT}/common/scripts/git.sh"

# usage: plate_discover_repo_root
# returns: 0 on success (sets PLATE_ROOT), 1 if not in a git repo
plate_discover_repo_root() {
  local repo_root
  repo_root=$(git_get_repo_root)
  local result=$?
  if [ $result -ne 0 ]; then
    return 1
  fi
  PLATE_ROOT="${repo_root}/.plate"
  export PLATE_ROOT
}

# usage: plate_ensure_dirs
# requires: PLATE_ROOT set by plate_discover_repo_root
plate_ensure_dirs() {
  mkdir -p "$PLATE_ROOT/instances" "$PLATE_ROOT/dropped" "$PLATE_ROOT/inputs"
  git_ensure_gitignore_entry "$(dirname "$PLATE_ROOT")" ".plate/"
}
