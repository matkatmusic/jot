#!/bin/bash
# jot-state-lib.sh — shared state-dir and lock helpers for the jot Phase 2
# hook scripts. Sourced by jot-session-start.sh, jot-stop.sh, jot.sh, etc.
#
# Lock model: mkdir-based, no flock dependency. macOS doesn't ship `flock`
# and we want zero brew dependencies beyond what check_requirements covers.
# `mkdir` is atomic on every POSIX filesystem, so this works portably.

# jot_lock_acquire <lock_dir> [timeout_seconds=10]
#   Spin until we own the lock or timeout. Returns 0 on success, 1 on timeout.
jot_lock_acquire() {
  local lock_dir="$1"
  local timeout="${2:-10}"
  local waited=0
  local max=$(( timeout * 20 ))   # 50ms steps
  while ! mkdir "$lock_dir" 2>/dev/null; do
    sleep 0.05
    waited=$(( waited + 1 ))
    if [ "$waited" -ge "$max" ]; then
      return 1
    fi
  done
  return 0
}

# jot_lock_release <lock_dir>
#   Remove the lock dir. Idempotent — safe to call even if we don't own it
#   (e.g. from a trap on a script that errored before acquiring).
jot_lock_release() {
  rmdir "$1" 2>/dev/null || true
}

# jot_state_init <state_dir>
#   Idempotently create the state dir and its tracked files.
jot_state_init() {
  local state_dir="$1"
  mkdir -p "$state_dir"
  touch "$state_dir/queue.txt" "$state_dir/active_job.txt" "$state_dir/audit.log"
}

# jot_queue_pop_first <state_dir>
#   Atomically remove the first line of queue.txt and write it to active_job.txt.
#   MUST be called WHILE HOLDING the queue lock. Prints the popped line to stdout.
#   No-op if queue is empty (active_job stays whatever it was).
jot_queue_pop_first() {
  local state_dir="$1"
  local queue="$state_dir/queue.txt"
  local active="$state_dir/active_job.txt"
  if [ ! -s "$queue" ]; then
    return 1
  fi
  head -1 "$queue" > "$active"
  # macOS BSD sed -i requires the empty backup arg
  sed -i "" '1d' "$queue"
  cat "$active"
  return 0
}

# jot_send_prompt <tmux_target> <input_file_path>
#   Send the canonical "Read <path> and follow the instructions" prompt to the
#   target tmux pane via send-keys. Caller is responsible for ensuring the
#   target exists and the running claude is ready.
jot_send_prompt() {
  local tmux_target="$1"
  local job_path="$2"
  tmux send-keys -t "$tmux_target" \
    "Read $job_path and follow the instructions at the top of that file"
  sleep 0.5
  tmux send-keys -t "$tmux_target" Enter
}

# jot_audit_rotate <audit_log> [max_lines=1000]
#   Trim audit.log to the last N lines (atomic via temp file + rename).
jot_audit_rotate() {
  local audit="$1"
  local max="${2:-1000}"
  [ -f "$audit" ] || return 0
  local lines
  lines=$(wc -l < "$audit" | tr -d ' ')
  if [ "${lines:-0}" -gt "$max" ]; then
    tail -"$max" "$audit" > "$audit.trim" && mv "$audit.trim" "$audit"
  fi
}
