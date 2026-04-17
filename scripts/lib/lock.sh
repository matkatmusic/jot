#!/bin/bash
# lock.sh — mkdir-based lock helpers.
# macOS does not ship flock; mkdir is atomic on every POSIX filesystem.

source "$(dirname "${BASH_SOURCE[0]}")/invoke_command.sh"

# usage: lock_acquire <lock_dir> [timeout_seconds] [stale_after_seconds]
# returns: 0 on success, 1 on timeout
lock_acquire() {
  local timeout="${2:-10}"
  local stale_after="${3:-60}"
  local max=$(( timeout * 20 ))   # 50ms steps
  local waited=0
  while ! hide_errors mkdir "$1"; do
    # Stale-lock sweep: if the lock dir is older than stale_after seconds,
    # the holder is almost certainly dead. Remove and retry.
    if [ -d "$1" ]; then
      local now age lock_mtime
      now=$(date +%s)
      lock_mtime=$(hide_errors stat -f %m "$1") || lock_mtime=$(hide_errors stat -c %Y "$1") || lock_mtime="$now"
      age=$(( now - lock_mtime ))
      if [ "$age" -ge "$stale_after" ]; then
        hide_errors rmdir "$1"
        continue
      fi
    fi
    sleep 0.05
    waited=$(( waited + 1 ))
    if [ "$waited" -ge "$max" ]; then
      echo "[lock] lock_acquire: timed out after ${timeout}s on '$1'" >&2
      return 1
    fi
  done
  return 0
}

# usage: lock_release <lock_dir>
# returns: 0 on success, 1 if lock dir didn't exist
lock_release() {
  hide_errors rmdir "$1"
  local result=$?
  return $result
}

lock_tests() {
  local test_dir="/tmp/lock-test-$$"
  local pass=0 fail=0

  # acquire succeeds on fresh path
  if lock_acquire "$test_dir" 2 2>/dev/null; then
    echo "PASS: acquire succeeds on fresh path"
    pass=$((pass + 1))
  else
    echo "FAIL: acquire failed on fresh path"
    fail=$((fail + 1))
  fi

  # second acquire times out (lock held)
  if lock_acquire "$test_dir" 1 2>/dev/null; then
    echo "FAIL: second acquire should timeout"
    fail=$((fail + 1))
  else
    echo "PASS: second acquire times out"
    pass=$((pass + 1))
  fi

  # release succeeds
  if lock_release "$test_dir"; then
    echo "PASS: release succeeds"
    pass=$((pass + 1))
  else
    echo "FAIL: release failed"
    fail=$((fail + 1))
  fi

  # re-acquire after release
  if lock_acquire "$test_dir" 2 2>/dev/null; then
    echo "PASS: re-acquire after release"
    pass=$((pass + 1))
  else
    echo "FAIL: re-acquire failed"
    fail=$((fail + 1))
  fi
  lock_release "$test_dir"

  # release on nonexistent returns nonzero
  if lock_release "/tmp/lock-nonexistent-$$"; then
    echo "FAIL: release should fail on nonexistent"
    fail=$((fail + 1))
  else
    echo "PASS: release fails on nonexistent"
    pass=$((pass + 1))
  fi

  # stale lock is auto-swept
  mkdir -p "/tmp/lock-stale-$$"
  touch -t 197001010000 "/tmp/lock-stale-$$"  # epoch = very old
  if lock_acquire "/tmp/lock-stale-$$" 2 1 2>/dev/null; then
    echo "PASS: stale lock swept and acquired"
    pass=$((pass + 1))
  else
    echo "FAIL: stale lock not swept"
    fail=$((fail + 1))
  fi
  lock_release "/tmp/lock-stale-$$"

  printf "lock_tests: PASS=%d FAIL=%d\n" "$pass" "$fail"
  [ "$fail" -eq 0 ]
}
