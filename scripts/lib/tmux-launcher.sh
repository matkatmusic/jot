# tmux-launcher.sh — higher-level tmux session composites.
#
# Sources tmux.sh for primitives and provides composites on top:
#
#   tmux_ensure_session <session> <window> <cwd> <keepalive_cmd> <keepalive_title>
#   tmux_ensure_keepalive_pane <target> <cwd> <keepalive_cmd> <title>
#   tmux_split_worker_pane <target> <cwd> <cmd>

source "$(dirname "${BASH_SOURCE[0]}")/tmux.sh"

tmux_ensure_session() {
  local session="$1" window="$2" cwd="$3" keepalive_cmd="$4" keepalive_title="$5"
  if ! tmux_has_session "$session"; then
    tmux_new_session "$session" -n "$window" -c "$cwd" "$keepalive_cmd"
    hide_output tmux_set_option_t "$session" remain-on-exit off
    hide_output tmux_set_option_t "$session" mouse on
    hide_output tmux_set_option_t "$session" pane-border-status top
    hide_output tmux_set_option_t "$session" pane-border-format ' #{pane_title} '
    hide_output tmux_set_pane_title "${session}:${window}.0" "$keepalive_title"
    return 0
  fi
  if ! tmux_window_exists "$session" "$window"; then
    tmux_new_window "$session" "$window" -c "$cwd" "$keepalive_cmd"
    hide_output tmux_set_pane_title "${session}:${window}.0" "$keepalive_title"
    return 0
  fi
  tmux_ensure_keepalive_pane "${session}:${window}" "$cwd" "$keepalive_cmd" "$keepalive_title"
}

tmux_ensure_keepalive_pane() {
  local target="$1" cwd="$2" keepalive_cmd="$3" title="$4"
  if tmux_pane_has_title "$target" "$title"; then
    return 0
  fi
  local ka_id
  ka_id=$(tmux_new_pane "$target" -c "$cwd" -P -F '#{pane_id}' "$keepalive_cmd")
  if [ -n "$ka_id" ]; then
    hide_output tmux_set_pane_title "$ka_id" "$title"
  fi
  hide_output tmux_retile "$target"
}

tmux_split_worker_pane() {
  local target="$1" cwd="$2" cmd="$3"
  local pane_id
  pane_id=$(tmux_new_pane "$target" -c "$cwd" -P -F '#{pane_id}' "$cmd")
  if [ -z "$pane_id" ]; then
    return 1
  fi
  printf '%s\n' "$pane_id"
}

tmux_launcher_tests() {
  local test_session="tmux-sh-launcher-test-$$"
  local pass=0 fail=0

  # Path 1: ensure_session on a missing session creates it.
  tmux_ensure_session "$test_session" "main" "/tmp" "sleep 30" "keepalive" >/dev/null 2>&1
  if tmux_has_session "$test_session"; then
    echo "PASS: ensure_session created new session"
    pass=$((pass + 1))
  else
    echo "FAIL: ensure_session did not create session"
    fail=$((fail + 1))
  fi

  # Keepalive pane got its title set.
  if tmux_pane_has_title "${test_session}:main" "keepalive"; then
    echo "PASS: keepalive pane has correct title"
    pass=$((pass + 1))
  else
    echo "FAIL: keepalive title not found"
    fail=$((fail + 1))
  fi

  # set_option_t applied pane-border-status=top.
  local border_status
  border_status=$(tmux show-options -t "$test_session" -v pane-border-status 2>/dev/null)
  if [ "$border_status" = "top" ]; then
    echo "PASS: set_option_t applied pane-border-status=top"
    pass=$((pass + 1))
  else
    echo "FAIL: pane-border-status is '$border_status', expected 'top'"
    fail=$((fail + 1))
  fi

  # split_worker_pane creates a pane and prints its id.
  local worker
  worker=$(tmux_split_worker_pane "${test_session}:main" "/tmp" "sleep 30")
  if [ -n "$worker" ] && [ "${worker:0:1}" = "%" ]; then
    echo "PASS: split_worker_pane returned pane id $worker"
    pass=$((pass + 1))
  else
    echo "FAIL: split_worker_pane returned '$worker'"
    fail=$((fail + 1))
  fi

  # Path 3: ensure_session on existing session+window is idempotent.
  tmux_ensure_session "$test_session" "main" "/tmp" "sleep 30" "keepalive" >/dev/null 2>&1
  if tmux_has_session "$test_session"; then
    echo "PASS: ensure_session idempotent on existing session+window"
    pass=$((pass + 1))
  else
    echo "FAIL: ensure_session broke existing session"
    fail=$((fail + 1))
  fi

  # Path 2: ensure_session on existing session, new window.
  tmux_ensure_session "$test_session" "secondwin-$$" "/tmp" "sleep 30" "keepalive-2" >/dev/null 2>&1
  if tmux_window_exists "$test_session" "secondwin-$$"; then
    echo "PASS: ensure_session added new window to existing session"
    pass=$((pass + 1))
  else
    echo "FAIL: ensure_session did not add new window"
    fail=$((fail + 1))
  fi

  tmux_kill_session "$test_session" 2>/dev/null

  printf "launcher_tests: PASS=%d FAIL=%d\n" "$pass" "$fail"
  [ "$fail" -eq 0 ]
}
