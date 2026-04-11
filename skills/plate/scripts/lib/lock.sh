#!/bin/bash
# lock.sh — mkdir-based lock helpers. Matches jot-state-lib.sh pattern.
# macOS does not ship flock; mkdir is atomic on every POSIX filesystem.

plate_lock_acquire() {
  local lock_dir="$1"
  local timeout="${2:-10}"
  local stale_after="${3:-60}"   # seconds — older locks are assumed stale
  local waited=0
  local max=$(( timeout * 20 ))
  while ! mkdir "$lock_dir" 2>/dev/null; do
    # Stale-lock sweep: if the lock dir is older than stale_after seconds,
    # the holder is almost certainly dead. Remove and retry.
    if [ -d "$lock_dir" ]; then
      local now age
      now=$(date +%s)
      age=$(( now - $(stat -f %m "$lock_dir" 2>/dev/null || stat -c %Y "$lock_dir" 2>/dev/null || echo "$now") ))
      if [ "$age" -ge "$stale_after" ]; then
        rmdir "$lock_dir" 2>/dev/null || true
        continue
      fi
    fi
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
