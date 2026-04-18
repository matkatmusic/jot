#!/bin/bash
# jot-state-lib.sh — shared state-dir and lock helpers for the jot Phase 2
# hook scripts. Sourced by jot-session-start.sh, jot-stop.sh, jot.sh, etc.
#
# Lock model: mkdir-based, no flock dependency. macOS doesn't ship `flock`
# and we want zero brew dependencies beyond what check_requirements covers.
# `mkdir` is atomic on every POSIX filesystem, so this works portably.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/invoke_command.sh"
source "$(dirname "${BASH_SOURCE[0]}")/../lib/tmux.sh"
source "$(dirname "${BASH_SOURCE[0]}")/../lib/lock.sh"

# Aliases for backward compat — callers use jot_lock_acquire/release.
jot_lock_acquire() { lock_acquire "$@"; }
jot_lock_release() { lock_release "$@"; }

# usage: jot_state_init <state_dir>
jot_state_init() {
  mkdir -p "$1"
  touch "$1/queue.txt" "$1/active_job.txt" "$1/audit.log"
}

# usage: jot_queue_pop_first <state_dir>
# returns: 0 on success (prints popped line), 1 if queue is empty
# MUST be called while holding the queue lock.
jot_queue_pop_first() {
  local queue="$1/queue.txt"
  local active="$1/active_job.txt"
  if [ ! -s "$queue" ]; then
    return 1
  fi
  head -1 "$queue" > "$active"
  sed -i "" '1d' "$queue"
  cat "$active"
  return 0
}

# usage: jot_send_prompt <tmux_target> <input_file_path>
jot_send_prompt() {
  tmux_send_and_submit "$1" \
    "Read $2 and follow the instructions at the top of that file"
}

# usage: jot_audit_rotate <audit_log> [max_lines]
jot_audit_rotate() {
  [ -f "$1" ] || return 0
  local max="${2:-1000}"
  local lines
  lines=$(wc -l < "$1" | tr -d ' ')
  if [ "${lines:-0}" -gt "$max" ]; then
    tail -"$max" "$1" > "$1.trim" && mv "$1.trim" "$1"
  fi
}
