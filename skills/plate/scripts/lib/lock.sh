#!/bin/bash
# lock.sh — mkdir-based lock helpers. Matches jot-state-lib.sh pattern.
# macOS does not ship flock; mkdir is atomic on every POSIX filesystem.

plate_lock_acquire() {
  local lock_dir="$1"
  local timeout="${2:-10}"
  local waited=0
  local max=$(( timeout * 20 ))
  while ! mkdir "$lock_dir" 2>/dev/null; do
    sleep 0.05
    waited=$(( waited + 1 ))
    if [ "$waited" -ge "$max" ]; then
      return 1
    fi
  done
  return 0
}

plate_lock_release() {
  rmdir "$1" 2>/dev/null || true
}
