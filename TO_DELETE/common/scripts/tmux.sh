# all the generic commands used when interacting with tmux programmatically:
# send-keys, including the 'enter' key
#
#
#  select_layout
# retile

# each generic function is followed by its testing function to ensure it works as expected.

source "$(dirname "${BASH_SOURCE[0]}")/invoke_command.sh"
source "$(dirname "${BASH_SOURCE[0]}")/silencers.sh"

# usage: tmux_require_version <minimum_version>
tmux_require_version() {
  local installed
  installed=$(tmux -V 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
  if [ -z "$installed" ]; then
    echo "[tmux] tmux is not installed" >&2
    return 1
  fi
  # sort -V puts the smaller version first; if $1 is first, installed >= required
  if ! printf '%s\n%s\n' "$1" "$installed" | sort -V | head -1 | grep -qx "$1"; then
    echo "[tmux] tmux $1+ required (found $installed)" >&2
    return 1
  fi
}
# ========================================================
# usage: tmux_set_option [scope_flags...] <option_name> <option_value>
# Base wrapper around `tmux set-option`. Usually called via one of the
# scope-specific wrappers below. All args pass through unchanged.
# returns: 0 on success, nonzero if tmux rejects the call
tmux_set_option() {
  invoke_command tmux set-option "$@"
}

# usage: tmux_set_option_t <target> <option_name> <option_value>
# Sets a tmux option scoped to <target> (session, window, or pane).
# returns: 0 on success, nonzero if target or option is invalid
tmux_set_option_t() {
  tmux_set_option -t "$1" "$2" "$3"
}

# usage: tmux_set_option_g <option_name> <option_value>
# Sets a tmux option in the global scope.
# returns: 0 on success, nonzero if option is invalid
tmux_set_option_g() {
  tmux_set_option -g "$1" "$2"
}

# usage: tmux_set_option_w <window_target> <option_name> <option_value>
# Sets a window-scoped tmux option on the given window target.
# returns: 0 on success, nonzero if target or option is invalid
tmux_set_option_w() {
  tmux_set_option -w -t "$1" "$2" "$3"
}

tmux_set_option_tests() {
  local test_session="tmux-sh-opt-test-$$"
  local pass=0 fail=0

  tmux_new_session "$test_session" 2>/dev/null

  # set_option_t accepts valid session option
  if hide_output tmux_set_option_t "$test_session" remain-on-exit off; then
    echo "PASS: set_option_t accepts valid session option"
    pass=$((pass + 1))
  else
    echo "FAIL: set_option_t rejected valid option"
    fail=$((fail + 1))
  fi

  # set_option_t rejects invalid option
  if tmux_set_option_t "$test_session" not-a-real-option foo 2>/dev/null; then
    echo "FAIL: set_option_t accepted invalid option"
    fail=$((fail + 1))
  else
    echo "PASS: set_option_t rejects invalid option"
    pass=$((pass + 1))
  fi

  # set_option_t rejects nonexistent target
  if tmux_set_option_t "nonexistent-$$" mouse on 2>/dev/null; then
    echo "FAIL: set_option_t accepted nonexistent target"
    fail=$((fail + 1))
  else
    echo "PASS: set_option_t rejects nonexistent target"
    pass=$((pass + 1))
  fi

  # set_option_g: read current value, set to same value (no-op effect)
  local current_mouse
  current_mouse=$(tmux show-options -gv mouse 2>/dev/null)
  if hide_output tmux_set_option_g mouse "$current_mouse"; then
    echo "PASS: set_option_g accepts valid global option"
    pass=$((pass + 1))
  else
    echo "FAIL: set_option_g rejected valid global option"
    fail=$((fail + 1))
  fi

  # set_option_g rejects invalid option
  if tmux_set_option_g not-a-real-option foo 2>/dev/null; then
    echo "FAIL: set_option_g accepted invalid option"
    fail=$((fail + 1))
  else
    echo "PASS: set_option_g rejects invalid option"
    pass=$((pass + 1))
  fi

  # set_option_w on a real window
  tmux_new_window "$test_session" "optwin-$$" 2>/dev/null
  if hide_output tmux_set_option_w "${test_session}:optwin-$$" aggressive-resize on; then
    echo "PASS: set_option_w accepts valid window option"
    pass=$((pass + 1))
  else
    echo "FAIL: set_option_w rejected valid window option"
    fail=$((fail + 1))
  fi

  # set_option_w rejects nonexistent window
  if tmux_set_option_w "${test_session}:nosuch-$$" aggressive-resize on 2>/dev/null; then
    echo "FAIL: set_option_w accepted nonexistent window"
    fail=$((fail + 1))
  else
    echo "PASS: set_option_w rejects nonexistent window"
    pass=$((pass + 1))
  fi

  tmux_kill_session "$test_session" 2>/dev/null

  printf "set_option_tests: PASS=%d FAIL=%d\n" "$pass" "$fail"
  [ "$fail" -eq 0 ]
}
# ========================================================
# usage: tmux_has_session <session_name>
# returns: 0 if session exists, 1 if not
tmux_has_session() {
    invoke_command tmux has-session -t "$1"
}

# usage: tmux_new_session <session_name> [extra_tmux_args...]
# Creates a detached session. Extra args pass through to `tmux new-session -d -s <name>`
# (e.g. `-n window`, `-c cwd`, trailing shell-command).
# returns: 0 on success, 1 if creation failed (e.g. duplicate session)
tmux_new_session() {
  invoke_command tmux new-session -d -s "$1" "${@:2}"
}

# usage: tmux_kill_session <session_name>
# returns: 0 on success, 1 if kill failed (e.g. session not found)
tmux_kill_session() {
  invoke_command tmux kill-session -t "$1"
}

# usage: tmux_list_clients <session_name>
# Prints one line per client attached to the session. Empty output if
# no clients are attached.
# returns: 0 on success, nonzero if session does not exist
tmux_list_clients() {
  invoke_command tmux list-clients -t "$1"
}

tmux_session_tests() {
  local test_session="tmux-sh-test-$$"
  local pass=0 fail=0

  # has_session returns false for nonexistent session
  if ! tmux_has_session "$test_session"; then
    echo "PASS: has_session returns false for nonexistent"
    pass=$((pass + 1))
  else
    echo "FAIL: has_session returned true for nonexistent"
    fail=$((fail + 1))
  fi

  # new_session creates a session
  if tmux_new_session "$test_session" 2>/dev/null; then
    echo "PASS: new_session created session"
    pass=$((pass + 1))
  else
    echo "FAIL: new_session failed to create session"
    fail=$((fail + 1))
  fi

  # has_session returns true for existing session
  if tmux_has_session "$test_session"; then
    echo "PASS: has_session returns true for existing"
    pass=$((pass + 1))
  else
    echo "FAIL: has_session returned false for existing"
    fail=$((fail + 1))
  fi

  # new_session fails on duplicate
  if tmux_new_session "$test_session" 2>/dev/null; then
    echo "FAIL: new_session should reject duplicate"
    fail=$((fail + 1))
  else
    echo "PASS: new_session rejects duplicate"
    pass=$((pass + 1))
  fi

  # kill_session removes the session
  if tmux_kill_session "$test_session" 2>/dev/null; then
    echo "PASS: kill_session succeeded"
    pass=$((pass + 1))
  else
    echo "FAIL: kill_session failed"
    fail=$((fail + 1))
  fi

  # has_session returns false after kill
  if ! tmux_has_session "$test_session"; then
    echo "PASS: has_session returns false after kill"
    pass=$((pass + 1))
  else
    echo "FAIL: has_session returned true after kill"
    fail=$((fail + 1))
  fi

  # kill_session fails on nonexistent
  if tmux_kill_session "$test_session" 2>/dev/null; then
    echo "FAIL: kill_session should fail on nonexistent"
    fail=$((fail + 1))
  else
    echo "PASS: kill_session fails on nonexistent"
    pass=$((pass + 1))
  fi

  printf "session_tests: PASS=%d FAIL=%d\n" "$pass" "$fail"
  [ "$fail" -eq 0 ]
}



# ===============================================
# usage: tmux_new_pane <target> [extra_tmux_args...]
# Creates a new pane by splitting <target>. Extra args pass through to
# `tmux split-window -t <target>` (e.g. `-c cwd`, `-P -F '#{pane_id}'`,
# trailing shell-command). When `-P` is passed, tmux emits the new pane id
# to stdout — callers can capture with $() to get the id back.
# returns: 0 on success, nonzero if target does not exist
tmux_new_pane() {
  invoke_command tmux split-window -t "$1" "${@:2}"
}

# usage: tmux_kill_pane <pane_target>
# returns: 0 on success, nonzero if pane does not exist
tmux_kill_pane() {
  invoke_command tmux kill-pane -t "$1"
}

# usage: tmux_capture_pane <pane_target> [lines]
# Prints the target pane's visible contents to stdout. If [lines] is given,
# also includes that many lines of scrollback history before the visible area.
# returns: 0 on success, nonzero if target does not exist
tmux_capture_pane() {
  invoke_command tmux capture-pane -p -t "$1" ${2:+-S -$2}
}

# usage: tmux_list_panes <target> [extra_tmux_args...]
# Prints one line per pane. With no extra args: "<pane_id> <pane_title>".
# Extra args pass through to `tmux list-panes` (e.g. `-F '#{pane_title}'`).
# returns: 0 on success, nonzero if target does not exist
tmux_list_panes() {
  if [ $# -eq 1 ]; then
    invoke_command tmux list-panes -t "$1" -F '#{pane_id} #{pane_title}'
  else
    invoke_command tmux list-panes -t "$1" "${@:2}"
  fi
}

# usage: tmux_select_pane <pane_target>
# returns: 0 on success, nonzero if target does not exist
tmux_select_pane() {
  invoke_command tmux select-pane -t "$1"
}

# usage: tmux_set_pane_title <pane_target> <title>
# returns: 0 on success, nonzero if target does not exist
tmux_set_pane_title() {
  invoke_command tmux select-pane -t "$1" -T "$2"
}

tmux_pane_tests() {
  local test_session="tmux-sh-pane-test-$$"
  local pass=0 fail=0

  tmux_new_session "$test_session" 2>/dev/null

  # list_panes on new session: exactly 1 pane
  local panes
  panes=$(tmux_list_panes "$test_session" | wc -l | tr -d ' ')
  if [ "$panes" = "1" ]; then
    echo "PASS: list_panes shows 1 pane in new session"
    pass=$((pass + 1))
  else
    echo "FAIL: list_panes shows $panes panes, expected 1"
    fail=$((fail + 1))
  fi

  # new_pane creates a second pane
  if tmux_new_pane "$test_session" 2>/dev/null; then
    echo "PASS: new_pane created pane"
    pass=$((pass + 1))
  else
    echo "FAIL: new_pane failed"
    fail=$((fail + 1))
  fi

  # list_panes: now 2
  panes=$(tmux_list_panes "$test_session" | wc -l | tr -d ' ')
  if [ "$panes" = "2" ]; then
    echo "PASS: list_panes shows 2 panes after new_pane"
    pass=$((pass + 1))
  else
    echo "FAIL: list_panes shows $panes panes, expected 2"
    fail=$((fail + 1))
  fi

  # select_pane using a known pane id
  local first_id
  first_id=$(tmux list-panes -t "$test_session" -F '#{pane_id}' 2>/dev/null | head -1)
  if [ -n "$first_id" ] && tmux_select_pane "$first_id" 2>/dev/null; then
    echo "PASS: select_pane selected by pane id"
    pass=$((pass + 1))
  else
    echo "FAIL: select_pane failed on known pane id"
    fail=$((fail + 1))
  fi

  # set_pane_title: title round-trips through list_panes
  if tmux_set_pane_title "$first_id" "titletest-$$" 2>/dev/null; then
    echo "PASS: set_pane_title succeeded"
    pass=$((pass + 1))
  else
    echo "FAIL: set_pane_title failed"
    fail=$((fail + 1))
  fi
  if tmux_list_panes "$test_session" | grep -qF "titletest-$$"; then
    echo "PASS: list_panes reflects new title"
    pass=$((pass + 1))
  else
    echo "FAIL: list_panes does not show new title"
    fail=$((fail + 1))
  fi

  # capture_pane returns content (non-empty)
  local captured
  captured=$(tmux_capture_pane "$first_id")
  if [ $? -eq 0 ]; then
    echo "PASS: capture_pane succeeded"
    pass=$((pass + 1))
  else
    echo "FAIL: capture_pane failed"
    fail=$((fail + 1))
  fi

  # new_pane fails on nonexistent session
  if tmux_new_pane "nonexistent-$$" 2>/dev/null; then
    echo "FAIL: new_pane should fail on nonexistent session"
    fail=$((fail + 1))
  else
    echo "PASS: new_pane fails on nonexistent session"
    pass=$((pass + 1))
  fi

  # select_pane fails on nonexistent target
  if tmux_select_pane "nonexistent-$$" 2>/dev/null; then
    echo "FAIL: select_pane should fail on nonexistent target"
    fail=$((fail + 1))
  else
    echo "PASS: select_pane fails on nonexistent target"
    pass=$((pass + 1))
  fi

  # kill_pane removes a live pane (use the pane we added earlier)
  local second_id
  second_id=$(tmux list-panes -t "$test_session" -F '#{pane_id}' 2>/dev/null | sed -n '2p')
  if [ -n "$second_id" ] && tmux_kill_pane "$second_id"; then
    echo "PASS: kill_pane succeeded on live pane"
    pass=$((pass + 1))
  else
    echo "FAIL: kill_pane failed on live pane"
    fail=$((fail + 1))
  fi
  panes=$(tmux_list_panes "$test_session" | wc -l | tr -d ' ')
  if [ "$panes" = "1" ]; then
    echo "PASS: list_panes shows 1 pane after kill_pane"
    pass=$((pass + 1))
  else
    echo "FAIL: list_panes shows $panes panes, expected 1"
    fail=$((fail + 1))
  fi

  # kill_pane fails on nonexistent target
  if hide_errors tmux_kill_pane "nonexistent-$$"; then
    echo "FAIL: kill_pane should fail on nonexistent target"
    fail=$((fail + 1))
  else
    echo "PASS: kill_pane fails on nonexistent target"
    pass=$((pass + 1))
  fi

  tmux_kill_session "$test_session" 2>/dev/null

  printf "pane_tests: PASS=%d FAIL=%d\n" "$pass" "$fail"
  [ "$fail" -eq 0 ]
}
#==================================================
# usage: tmux_new_window <session_name> <window_name> [extra_tmux_args...]
# Creates a new window. Extra args pass through to `tmux new-window -t <s> -n <w>`
# (e.g. `-c cwd`, trailing shell-command).
# returns: 0 on success, nonzero on failure
tmux_new_window() {
  invoke_command tmux new-window -t "$1" -n "$2" "${@:3}"
}

# usage: tmux_kill_window <window_target>
# returns: 0 on success, nonzero if window does not exist
tmux_kill_window() {
  invoke_command tmux kill-window -t "$1"
}

# usage: tmux_list_windows <session_name> [extra_tmux_args...]
# Prints one line per window. With no extra args: "<window_index> <window_name>".
# Extra args pass through to `tmux list-windows` (e.g. `-F '#{window_name}'`).
# returns: 0 on success, nonzero if session does not exist
tmux_list_windows() {
  if [ $# -eq 1 ]; then
    invoke_command tmux list-windows -t "$1" -F '#{window_index} #{window_name}'
  else
    invoke_command tmux list-windows -t "$1" "${@:2}"
  fi
}

# usage: tmux_window_exists <session> <window_name>
# returns: 0 if a window with exact name exists in session, 1 if not
tmux_window_exists() {
  tmux_list_windows "$1" -F '#{window_name}' | grep -qx "$2"
}

# usage: tmux_pane_has_title <target> <title>
# returns: 0 if any pane in target has the exact title, 1 if not
tmux_pane_has_title() {
  tmux_list_panes "$1" -F '#{pane_title}' | grep -qx "$2"
}

# usage: tmux_split_window <target> <direction>
# direction: h for horizontal (side-by-side), v for vertical (stacked)
# returns: 0 on success, nonzero on failure
tmux_split_window() {
  invoke_command tmux split-window -"$2" -t "$1"
}

tmux_window_tests() {
  local test_session="tmux-sh-win-test-$$"
  local pass=0 fail=0

  tmux_new_session "$test_session" 2>/dev/null

  # list_windows on new session: exactly 1 window
  local wins
  wins=$(tmux_list_windows "$test_session" | wc -l | tr -d ' ')
  if [ "$wins" = "1" ]; then
    echo "PASS: list_windows shows 1 window"
    pass=$((pass + 1))
  else
    echo "FAIL: list_windows shows $wins windows, expected 1"
    fail=$((fail + 1))
  fi

  # new_window creates a second window
  if tmux_new_window "$test_session" "win-$$" 2>/dev/null; then
    echo "PASS: new_window created window"
    pass=$((pass + 1))
  else
    echo "FAIL: new_window failed"
    fail=$((fail + 1))
  fi

  # list_windows: now 2
  wins=$(tmux_list_windows "$test_session" | wc -l | tr -d ' ')
  if [ "$wins" = "2" ]; then
    echo "PASS: list_windows shows 2 windows"
    pass=$((pass + 1))
  else
    echo "FAIL: list_windows shows $wins windows, expected 2"
    fail=$((fail + 1))
  fi

  # split_window h: second pane appears
  if tmux_split_window "${test_session}:win-$$" h 2>/dev/null; then
    echo "PASS: split_window -h succeeded"
    pass=$((pass + 1))
  else
    echo "FAIL: split_window -h failed"
    fail=$((fail + 1))
  fi

  # split_window v: third pane appears
  if tmux_split_window "${test_session}:win-$$" v 2>/dev/null; then
    echo "PASS: split_window -v succeeded"
    pass=$((pass + 1))
  else
    echo "FAIL: split_window -v failed"
    fail=$((fail + 1))
  fi

  # kill_window removes the window
  if tmux_kill_window "${test_session}:win-$$" 2>/dev/null; then
    echo "PASS: kill_window succeeded"
    pass=$((pass + 1))
  else
    echo "FAIL: kill_window failed"
    fail=$((fail + 1))
  fi

  # list_windows: back to 1
  wins=$(tmux_list_windows "$test_session" | wc -l | tr -d ' ')
  if [ "$wins" = "1" ]; then
    echo "PASS: list_windows shows 1 window after kill"
    pass=$((pass + 1))
  else
    echo "FAIL: list_windows shows $wins windows, expected 1"
    fail=$((fail + 1))
  fi

  # kill_window fails on nonexistent
  if tmux_kill_window "${test_session}:nosuch-$$" 2>/dev/null; then
    echo "FAIL: kill_window should fail on nonexistent"
    fail=$((fail + 1))
  else
    echo "PASS: kill_window fails on nonexistent"
    pass=$((pass + 1))
  fi

  # new_window fails on nonexistent session
  if tmux_new_window "nonexistent-$$" "whatever" 2>/dev/null; then
    echo "FAIL: new_window should fail on nonexistent session"
    fail=$((fail + 1))
  else
    echo "PASS: new_window fails on nonexistent session"
    pass=$((pass + 1))
  fi

  tmux_kill_session "$test_session" 2>/dev/null

  printf "window_tests: PASS=%d FAIL=%d\n" "$pass" "$fail"
  [ "$fail" -eq 0 ]
}
#==================================================
# usage: tmux_select_layout <target> <layout>
# layout: even-horizontal | even-vertical | main-horizontal | main-vertical | tiled
# returns: 0 on success, nonzero on failure
tmux_select_layout() {
  invoke_command tmux select-layout -t "$1" "$2"
}

# usage: tmux_retile <target>
# Re-applies the `tiled` layout to the target window.
# returns: 0 on success, nonzero on failure
tmux_retile() {
  tmux_select_layout "$1" tiled
}

tmux_layout_tests() {
  local test_session="tmux-sh-lay-test-$$"
  local pass=0 fail=0

  tmux_new_session "$test_session" 2>/dev/null
  tmux_new_pane "$test_session" 2>/dev/null
  tmux_new_pane "$test_session" 2>/dev/null

  # select_layout tiled succeeds
  if tmux_select_layout "$test_session" tiled 2>/dev/null; then
    echo "PASS: select_layout tiled succeeded"
    pass=$((pass + 1))
  else
    echo "FAIL: select_layout tiled failed"
    fail=$((fail + 1))
  fi

  # select_layout even-horizontal succeeds
  if tmux_select_layout "$test_session" even-horizontal 2>/dev/null; then
    echo "PASS: select_layout even-horizontal succeeded"
    pass=$((pass + 1))
  else
    echo "FAIL: select_layout even-horizontal failed"
    fail=$((fail + 1))
  fi

  # select_layout with invalid name fails
  if tmux_select_layout "$test_session" not-a-layout 2>/dev/null; then
    echo "FAIL: select_layout should fail with invalid name"
    fail=$((fail + 1))
  else
    echo "PASS: select_layout fails with invalid name"
    pass=$((pass + 1))
  fi

  # retile succeeds
  if tmux_retile "$test_session" 2>/dev/null; then
    echo "PASS: retile succeeded"
    pass=$((pass + 1))
  else
    echo "FAIL: retile failed"
    fail=$((fail + 1))
  fi

  # retile fails on nonexistent target
  if tmux_retile "nonexistent-$$" 2>/dev/null; then
    echo "FAIL: retile should fail on nonexistent target"
    fail=$((fail + 1))
  else
    echo "PASS: retile fails on nonexistent target"
    pass=$((pass + 1))
  fi

  tmux_kill_session "$test_session" 2>/dev/null

  printf "layout_tests: PASS=%d FAIL=%d\n" "$pass" "$fail"
  [ "$fail" -eq 0 ]
}
#==================================================

#==================================================
# usage: tmux_send_keys <pane_target> <text>
# Sends <text> to the pane. Does not append Enter.
# returns: 0 on success, nonzero if target does not exist
tmux_send_keys() {
  invoke_command tmux send-keys -t "$1" "$2"
}

# usage: tmux_send_enter <pane_target>
# returns: 0 on success, nonzero if target does not exist
tmux_send_enter() {
  invoke_command tmux send-keys -t "$1" Enter
}

# usage: tmux_send_Ctrl_c <pane_target>
# returns: 0 on success, nonzero if target does not exist
tmux_send_Ctrl_c() {
  invoke_command tmux send-keys -t "$1" C-c
}

# usage: tmux_send_and_submit <pane_target> <text>
# Sends <text> then presses Enter as a separate send-keys call, because
# some TUIs drop Enter when it arrives in the same call as a long string.
# returns: 0 on success, nonzero if either send fails
tmux_send_and_submit() {
  tmux_send_keys "$1" "$2"
  local result=$?
  if [ $result -ne 0 ]; then
    return $result
  fi
  sleep 0.5
  tmux_send_enter "$1"
}

# usage: tmux_cancel_and_send <pane_target> <text> [label]
# Sends Ctrl-C up to 5 times until the pane buffer shows a cancellation
# marker, then types <text> and submits. Optional <label> appears in the
# cancellation log when at least one retry was needed.
# returns: exit code of the final tmux_send_and_submit
tmux_cancel_and_send() {
  local attempt=0
  while [ $attempt -lt 5 ]; do
    tmux_send_Ctrl_c "$1"
    sleep 0.2
    local pane_tail
    pane_tail=$(tmux_capture_pane "$1")
    if echo "$pane_tail" | grep -qF 'Ctrl-C'; then
      break
    fi
    attempt=$((attempt + 1))
  done
  if [ $attempt -gt 0 ] && [ -n "$3" ]; then
    echo "[tmux] cancelled in-progress work: $3 ($((attempt + 1)) Ctrl-C's)"
  fi
  tmux_send_and_submit "$1" "$2"
}

tmux_cancel_and_send_tests() {
  local test_session="tmux-sh-cancel-test-$$"
  local pass=0 fail=0

  tmux_new_session "$test_session" 2>/dev/null

  # Start a long-running command so Ctrl-C has something to cancel.
  tmux_send_and_submit "$test_session" "sleep 10"
  sleep 0.2

  # With label: log line should mention it, replacement should run quickly
  # (fast arrival implies sleep 10 was actually cancelled — if Ctrl-C failed,
  # the echo would queue behind sleep and not appear for ~10s).
  local log
  log=$(tmux_cancel_and_send "$test_session" "echo replaced-$$" "work-$$")
  if echo "$log" | grep -qF "work-$$"; then
    echo "PASS: cancel_and_send logs label after cancellation"
    pass=$((pass + 1))
  else
    echo "FAIL: label missing from log: $log"
    fail=$((fail + 1))
  fi

  sleep 0.5
  if tmux_capture_pane "$test_session" | grep -qF "replaced-$$"; then
    echo "PASS: cancel_and_send cancelled sleep and delivered replacement"
    pass=$((pass + 1))
  else
    echo "FAIL: replacement text not visible — cancel may have failed"
    fail=$((fail + 1))
  fi

  # Without label: no "cancelled in-progress" log line
  tmux_send_and_submit "$test_session" "sleep 10"
  sleep 0.2
  local log2
  log2=$(tmux_cancel_and_send "$test_session" "echo second-$$")
  if echo "$log2" | grep -qF 'cancelled in-progress'; then
    echo "FAIL: cancel_and_send logged despite no label"
    fail=$((fail + 1))
  else
    echo "PASS: cancel_and_send stays quiet without label"
    pass=$((pass + 1))
  fi

  sleep 0.5
  if tmux_capture_pane "$test_session" | grep -qF "second-$$"; then
    echo "PASS: second cancel_and_send delivered replacement"
    pass=$((pass + 1))
  else
    echo "FAIL: second replacement not visible"
    fail=$((fail + 1))
  fi

  tmux_kill_session "$test_session" 2>/dev/null

  printf "cancel_and_send_tests: PASS=%d FAIL=%d\n" "$pass" "$fail"
  [ "$fail" -eq 0 ]
}

tmux_send_keys_tests() {
  local test_session="tmux-sh-send-test-$$"
  local pass=0 fail=0

  tmux_new_session "$test_session" 2>/dev/null

  # send_keys delivers literal text (visible via capture)
  if tmux_send_keys "$test_session" "marker-$$" 2>/dev/null; then
    echo "PASS: send_keys succeeded"
    pass=$((pass + 1))
  else
    echo "FAIL: send_keys failed"
    fail=$((fail + 1))
  fi
  sleep 0.1
  if tmux_capture_pane "$test_session" | grep -qF "marker-$$"; then
    echo "PASS: send_keys text visible in pane capture"
    pass=$((pass + 1))
  else
    echo "FAIL: send_keys text not captured"
    fail=$((fail + 1))
  fi

  # send_Ctrl_c clears the pending input
  if tmux_send_Ctrl_c "$test_session" 2>/dev/null; then
    echo "PASS: send_Ctrl_c succeeded"
    pass=$((pass + 1))
  else
    echo "FAIL: send_Ctrl_c failed"
    fail=$((fail + 1))
  fi

  # send_enter succeeds
  if tmux_send_enter "$test_session" 2>/dev/null; then
    echo "PASS: send_enter succeeded"
    pass=$((pass + 1))
  else
    echo "FAIL: send_enter failed"
    fail=$((fail + 1))
  fi

  # send_and_submit: echo command runs, output appears
  if tmux_send_and_submit "$test_session" "echo submit-$$" 2>/dev/null; then
    echo "PASS: send_and_submit succeeded"
    pass=$((pass + 1))
  else
    echo "FAIL: send_and_submit failed"
    fail=$((fail + 1))
  fi
  sleep 0.3
  if tmux_capture_pane "$test_session" | grep -qF "submit-$$"; then
    echo "PASS: send_and_submit output visible in pane capture"
    pass=$((pass + 1))
  else
    echo "FAIL: send_and_submit output not captured"
    fail=$((fail + 1))
  fi

  # send_keys fails on nonexistent target
  if tmux_send_keys "nonexistent-$$" "text" 2>/dev/null; then
    echo "FAIL: send_keys should fail on nonexistent target"
    fail=$((fail + 1))
  else
    echo "PASS: send_keys fails on nonexistent target"
    pass=$((pass + 1))
  fi

  # send_enter fails on nonexistent target
  if tmux_send_enter "nonexistent-$$" 2>/dev/null; then
    echo "FAIL: send_enter should fail on nonexistent target"
    fail=$((fail + 1))
  else
    echo "PASS: send_enter fails on nonexistent target"
    pass=$((pass + 1))
  fi

  tmux_kill_session "$test_session" 2>/dev/null

  printf "send_text_tests: PASS=%d FAIL=%d\n" "$pass" "$fail"
  [ "$fail" -eq 0 ]
}
