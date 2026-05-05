#!/bin/bash
# orchestrator.sh — UserPromptSubmit dispatcher. Reads hook JSON from stdin,
# inspects .prompt, and delegates to the /jot or /plate sub-orchestrator.
# Unknown prompts pass through silently (exit 0).
set -eEuo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# . "$PLUGIN_ROOT/common/scripts/silencers.sh"
##### silencers.sh — canonical stdout/stderr suppression wrappers. #####
# The rest of the codebase must not use raw `>/dev/null` or `2>/dev/null`;
# use these wrappers so suppression intent is searchable and explicit.

# usage: hide_output <command> [args...]
# Runs the command with its stdout redirected to /dev/null. Stderr passes
# through unchanged — real failures still surface. Useful for wrapping calls
# whose success-output is noise the caller doesn't want (e.g. `tmux set-option`
# echoing the new value).
# returns: the command's exit code
# [ABSORBED -> subprocess.run(..., stdout=subprocess.DEVNULL) @ 2026-05-04]
hide_output() {
  "$@" >/dev/null
}

# usage: hide_errors <command> [args...]
# Runs the command with its stderr redirected to /dev/null. Stdout passes
# through unchanged — callers can still capture output. Complement of
# hide_output. Use for probes where "failed" is a valid answer state and
# the diagnostic log would be noise.
# returns: the command's exit code
# [ABSORBED -> subprocess.run(..., stderr=subprocess.DEVNULL) or try/except @ 2026-05-04]
hide_errors() {
  "$@" 2>/dev/null
}
#### end silencers.sh ####

#### hook-json.sh ####

# hook-json.sh — shared Claude Code hook JSON helpers.
#
# This file is meant to be `source`d. It exports:
#   emit_block <reason>       Print {"decision":"block","reason":...} to stdout.
#                             Uses jq when available; falls back to hand-rolled
#                             JSON so the requirements check can still report
#                             that jq is missing.
#   check_requirements <prefix> <cmd...>
#                             Probe each command; if any are missing, emit a
#                             block reason listing them with install hints,
#                             then exit 0. Known commands (jq, python3, tmux,
#                             claude) get canonical install hints; unknown
#                             commands are listed by name.
#
# Extracted from scripts/jot.sh per plans/jot-generalizing-refactor.md (commit 3).

# [MIGRATED -> hookjson_emitBlock @ 2026-05-04]
emit_block() {
  local reason="$1"
  if command -v jq >/dev/null 2>&1; then
    jq -n --arg r "$reason" '{decision:"block", reason:$r}'
  else
    local esc="${reason//\\/\\\\}"   # backslashes first
    esc="${esc//\"/\\\"}"            # then quotes
    printf '{"decision":"block","reason":"%s"}\n' "$esc"
  fi
}

# [MIGRATED -> hookjson_installHint @ 2026-05-04]
_hookjson_install_hint() {
  case "$1" in
    jq)       echo "jq (brew install jq)" ;;
    python3)  echo "python3 (brew install python)" ;;
    tmux)     echo "tmux (brew install tmux)" ;;
    claude)   echo "claude (https://claude.com/claude-code)" ;;
    *)        echo "$1" ;;
  esac
}

# [MIGRATED -> hookjson_checkRequirements @ 2026-05-04]
check_requirements() {
  local prefix="$1"; shift
  local -a missing=()
  local cmd
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null 2>&1 || missing+=("$(_hookjson_install_hint "$cmd")")
  done
  if [ ${#missing[@]} -eq 0 ]; then
    return 0
  fi
  local list="" item
  for item in "${missing[@]}"; do
    if [ -z "$list" ]; then list="$item"; else list="$list, $item"; fi
  done
  emit_block "${prefix} needs: $list — install and retry."
  exit 0
}

#### end hook-json.sh ####

#### invoke_command.sh
# invoke_command.sh — canonical command-execution wrapper.
# Source silencers.sh separately if you also need hide_output / hide_errors.

# [ABSORBED -> subprocess.run(..., check=True, capture_output=True, text=True) with try/except logging caller via sys._getframe(1).f_code.co_name @ 2026-05-04]
invoke_command() {
    local output
    output=$("$@" 2>&1) # execute whatever command was passed in
    local result=$? # get the result
    if [ $result -ne 0 ]; then
        echo "[${FUNCNAME[1]}] command '$*' failed: $output" >&2 # print out the failed result
    elif [ -n "$output" ]; then
        # Add a trailing newline only when output is non-empty. Text commands
        # (tmux list-sessions, etc.) need it for line-oriented consumers like
        # `while read` and `wc -l`. Silent commands with no stdout stay truly
        # silent — no stray blank line leaks to callers.
        printf '%s\n' "$output"
    fi
    return $result
}

#### end invoke_command.sh

#### tmux.sh ####

# all the generic commands used when interacting with tmux programmatically:
# send-keys, including the 'enter' key
#
#
#  select_layout
# retile

# each generic function is followed by its testing function to ensure it works as expected.

# source "$(dirname "${BASH_SOURCE[0]}")/invoke_command.sh"
# source "$(dirname "${BASH_SOURCE[0]}")/silencers.sh"

# usage: tmux_require_version <minimum_version>
# [MIGRATED -> tmux_requireVersion @ 2026-05-04]
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
# [MIGRATED -> tmux_setOption @ 2026-05-04]
tmux_set_option() {
  invoke_command tmux set-option "$@"
}

# usage: tmux_set_option_t <target> <option_name> <option_value>
# Sets a tmux option scoped to <target> (session, window, or pane).
# returns: 0 on success, nonzero if target or option is invalid
# [MIGRATED -> tmux_setOptionForTarget @ 2026-05-04]
tmux_set_option_t() {
  tmux_set_option -t "$1" "$2" "$3"
}

# usage: tmux_set_option_g <option_name> <option_value>
# Sets a tmux option in the global scope.
# returns: 0 on success, nonzero if option is invalid
# [MIGRATED -> tmux_setOptionGlobally @ 2026-05-04]
tmux_set_option_g() {
  tmux_set_option -g "$1" "$2"
}

# usage: tmux_set_option_w <window_target> <option_name> <option_value>
# Sets a window-scoped tmux option on the given window target.
# returns: 0 on success, nonzero if target or option is invalid
# [MIGRATED -> tmux_setOptionForWindow @ 2026-05-04]
tmux_set_option_w() {
  tmux_set_option -w -t "$1" "$2" "$3"
}

# [PENDING]
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
# [MIGRATED -> tmux_hasSession @ 2026-05-04]
tmux_has_session() {
    invoke_command tmux has-session -t "$1"
}

# usage: tmux_new_session <session_name> [extra_tmux_args...]
# Creates a detached session. Extra args pass through to `tmux new-session -d -s <name>`
# (e.g. `-n window`, `-c cwd`, trailing shell-command).
# returns: 0 on success, 1 if creation failed (e.g. duplicate session)
# [MIGRATED -> tmux_newSession @ 2026-05-04]
tmux_new_session() {
  invoke_command tmux new-session -d -s "$1" "${@:2}"
}

# usage: tmux_kill_session <session_name>
# returns: 0 on success, 1 if kill failed (e.g. session not found)
# [MIGRATED -> tmux_killSession @ 2026-05-04]
tmux_kill_session() {
  invoke_command tmux kill-session -t "$1"
}

# usage: tmux_list_clients <session_name>
# Prints one line per client attached to the session. Empty output if
# no clients are attached.
# returns: 0 on success, nonzero if session does not exist
# [MIGRATED -> tmux_listClients @ 2026-05-04]
tmux_list_clients() {
  invoke_command tmux list-clients -t "$1"
}

# [PENDING]
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
# [MIGRATED -> tmux_newPane @ 2026-05-04]
tmux_new_pane() {
  invoke_command tmux split-window -t "$1" "${@:2}"
}

# usage: tmux_kill_pane <pane_target>
# returns: 0 on success, nonzero if pane does not exist
# [MIGRATED -> tmux_killPane @ 2026-05-04]
tmux_kill_pane() {
  invoke_command tmux kill-pane -t "$1"
}

# usage: tmux_capture_pane <pane_target> [lines]
# Prints the target pane's visible contents to stdout. If [lines] is given,
# also includes that many lines of scrollback history before the visible area.
# returns: 0 on success, nonzero if target does not exist
# [MIGRATED -> tmux_capturePane @ 2026-05-04]
tmux_capture_pane() {
  invoke_command tmux capture-pane -p -t "$1" ${2:+-S -$2}
}

# usage: tmux_list_panes <target> [extra_tmux_args...]
# Prints one line per pane. With no extra args: "<pane_id> <pane_title>".
# Extra args pass through to `tmux list-panes` (e.g. `-F '#{pane_title}'`).
# returns: 0 on success, nonzero if target does not exist
# [MIGRATED -> tmux_listPanes @ 2026-05-04]
tmux_list_panes() {
  if [ $# -eq 1 ]; then
    invoke_command tmux list-panes -t "$1" -F '#{pane_id} #{pane_title}'
  else
    invoke_command tmux list-panes -t "$1" "${@:2}"
  fi
}

# usage: tmux_select_pane <pane_target>
# returns: 0 on success, nonzero if target does not exist
# [MIGRATED -> tmux_selectPane @ 2026-05-04]
tmux_select_pane() {
  invoke_command tmux select-pane -t "$1"
}

# usage: tmux_set_pane_title <pane_target> <title>
# returns: 0 on success, nonzero if target does not exist
# [MIGRATED -> tmux_setPaneTitle @ 2026-05-04]
tmux_set_pane_title() {
  invoke_command tmux select-pane -t "$1" -T "$2"
}

# [PENDING]
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
# [MIGRATED -> tmux_newWindow @ 2026-05-04]
tmux_new_window() {
  invoke_command tmux new-window -t "$1" -n "$2" "${@:3}"
}

# usage: tmux_kill_window <window_target>
# returns: 0 on success, nonzero if window does not exist
# [MIGRATED -> tmux_killWindow @ 2026-05-04]
tmux_kill_window() {
  invoke_command tmux kill-window -t "$1"
}

# usage: tmux_list_windows <session_name> [extra_tmux_args...]
# Prints one line per window. With no extra args: "<window_index> <window_name>".
# Extra args pass through to `tmux list-windows` (e.g. `-F '#{window_name}'`).
# returns: 0 on success, nonzero if session does not exist
# [MIGRATED -> tmux_listWindows @ 2026-05-04]
tmux_list_windows() {
  if [ $# -eq 1 ]; then
    invoke_command tmux list-windows -t "$1" -F '#{window_index} #{window_name}'
  else
    invoke_command tmux list-windows -t "$1" "${@:2}"
  fi
}

# usage: tmux_window_exists <session> <window_name>
# returns: 0 if a window with exact name exists in session, 1 if not
# [MIGRATED -> tmux_windowExists @ 2026-05-04]
tmux_window_exists() {
  tmux_list_windows "$1" -F '#{window_name}' | grep -qx "$2"
}

# usage: tmux_pane_has_title <target> <title>
# returns: 0 if any pane in target has the exact title, 1 if not
# [MIGRATED -> tmux_paneHasTitle @ 2026-05-04]
tmux_pane_has_title() {
  tmux_list_panes "$1" -F '#{pane_title}' | grep -qx "$2"
}

# usage: tmux_split_window <target> <direction>
# direction: h for horizontal (side-by-side), v for vertical (stacked)
# returns: 0 on success, nonzero on failure
# [MIGRATED -> tmux_splitWindow @ 2026-05-04]
tmux_split_window() {
  invoke_command tmux split-window -"$2" -t "$1"
}

# [PENDING]
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
# [MIGRATED -> tmux_selectLayout @ 2026-05-04]
tmux_select_layout() {
  invoke_command tmux select-layout -t "$1" "$2"
}

# usage: tmux_retile <target>
# Re-applies the `tiled` layout to the target window.
# returns: 0 on success, nonzero on failure
# [MIGRATED -> tmux_retile @ 2026-05-04]
tmux_retile() {
  tmux_select_layout "$1" tiled
}

# [PENDING]
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
# [MIGRATED -> tmux_sendKeys @ 2026-05-04]
tmux_send_keys() {
  invoke_command tmux send-keys -t "$1" "$2"
}

# usage: tmux_send_enter <pane_target>
# returns: 0 on success, nonzero if target does not exist
# [MIGRATED -> tmux_sendEnter @ 2026-05-04]
tmux_send_enter() {
  invoke_command tmux send-keys -t "$1" Enter
}

# usage: tmux_send_Ctrl_c <pane_target>
# returns: 0 on success, nonzero if target does not exist
# [MIGRATED -> tmux_sendCtrlC @ 2026-05-04]
tmux_send_Ctrl_c() {
  invoke_command tmux send-keys -t "$1" C-c
}

# usage: tmux_send_and_submit <pane_target> <text>
# Sends <text> then presses Enter as a separate send-keys call, because
# some TUIs drop Enter when it arrives in the same call as a long string.
# returns: 0 on success, nonzero if either send fails
# [MIGRATED -> tmux_sendAndSubmit @ 2026-05-04]
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
# [MIGRATED -> tmux_cancelAndSend @ 2026-05-04]
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
  if [ $attempt -gt 0 ] && [ -n "${3:-}" ]; then
    echo "[tmux] cancelled in-progress work: ${3} ($((attempt + 1)) Ctrl-C's)"
  fi
  tmux_send_and_submit "$1" "$2"
}

# [PENDING]
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

# [PENDING]
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

#### end tmux.sh #### 

#### tmux-launcher.sh ####
# tmux-launcher.sh — higher-level tmux session composites.
#
# Sources tmux.sh for primitives and provides composites on top:
#
#   tmux_ensure_session <session> <window> <cwd> <keepalive_cmd> <keepalive_title>
#   tmux_ensure_keepalive_pane <target> <cwd> <keepalive_cmd> <title>
#   tmux_split_worker_pane <target> <cwd> <cmd>

# source "$(dirname "${BASH_SOURCE[0]}")/silencers.sh"
# source "$(dirname "${BASH_SOURCE[0]}")/tmux.sh"

# Moved above tmux_ensure_session (Phase 0.1) so callees precede callers.
# [MIGRATED -> tmux_ensureKeepalivePane @ 2026-05-04]
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

# [MIGRATED -> tmux_ensureSession @ 2026-05-04]
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

# [MIGRATED -> tmux_splitWorkerPane @ 2026-05-04]
tmux_split_worker_pane() {
  local target="$1" cwd="$2" cmd="$3"
  local pane_id
  pane_id=$(tmux_new_pane "$target" -c "$cwd" -P -F '#{pane_id}' "$cmd")
  if [ -z "$pane_id" ]; then
    return 1
  fi
  printf '%s\n' "$pane_id"
}

# usage: tmux_wait_for_claude_readiness <pane_id> [timeout_seconds]
# returns: 0 when the Claude Code TUI is ready for input, 1 on timeout
# [MIGRATED -> tmux_waitForClaudeReadiness @ 2026-05-04]
tmux_wait_for_claude_readiness() {
  local pane_id="$1"
  local timeout="${2:-10}"
  local max_attempts=$(( timeout * 2 ))  # 0.5s per attempt
  local attempt=0
  while [ $attempt -lt $max_attempts ]; do
    local pane_content
    pane_content=$(tmux_capture_pane "$pane_id" 5 2>/dev/null) || true
    if echo "$pane_content" | grep -qF '❯'; then
      return 0
    fi
    sleep 0.5
    attempt=$((attempt + 1))
  done
  echo "[tmux-launcher] tmux_wait_for_claude_readiness: timed out after ${timeout}s waiting for pane '$pane_id'" >&2
  return 1
}

# [PENDING]
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

#### end tmux-launcher.sh ####

#### claude-launcher.sh ####

# claude-launcher.sh — generalized per-invocation `claude` launcher.
#
# This file is meant to be `source`d. It exports one function:
#
#   build_claude_cmd <settings_out> <allow_json> <hooks_json_file> <cwd> <add_dir...>
#
#   Arguments:
#     settings_out    Path to write the generated settings.json.
#     allow_json      A JSON array literal (string) of expanded permissions.
#                     Callers typically generate this via
#                     common/scripts/jot/expand_permissions.py.
#     hooks_json_file Path to a file containing the JSON object for the
#                     "hooks" key in settings.json (e.g. {"SessionStart":
#                     [...], "Stop": [...], "SessionEnd": [...]}).
#                     Caller is responsible for constructing this file
#                     with correct absolute paths to any hook scripts.
#     cwd             Launcher cwd (becomes the first --add-dir).
#     add_dir...      Zero or more additional --add-dir paths.
#
#   Prints the resolved `claude ...` command string to stdout. The caller
#   typically captures this into a variable and passes it to tmux.
#
# Extracted from scripts/jot.sh per plans/jot-generalizing-refactor.md (commit 7).
# No longer assumes jot-specific hook scripts, permissions location, or
# SessionStart/Stop/SessionEnd wiring — callers supply those.

# [MIGRATED -> claude_buildCmd @ 2026-05-04]
build_claude_cmd() {
  local settings_out="$1"
  local allow_json="$2"
  local hooks_json_file="$3"
  local cwd="$4"
  shift 4

  local hooks_json
  hooks_json=$(cat "$hooks_json_file")

  cat > "$settings_out" <<JSON
{
  "permissions": {
    "allow": $allow_json
  },
  "hooks": $hooks_json
}
JSON

  local cmd="claude --settings '$settings_out' --add-dir '$cwd'"
  local extra
  for extra in "$@"; do
    cmd="$cmd --add-dir '$extra'"
  done
  printf '%s\n' "$cmd"
}

#### end claude-launcher.sh

#### permissions-seed.sh

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

# De-nested from permissions_seed (Phase 0.0). Relies on bash dynamic scoping:
# callers invoke this only from within permissions_seed, where $log_file and
# $log_prefix are set as locals. The Python port will pass them explicitly.
# [MIGRATED -> claude_permseedLog @ 2026-05-04]
_permseed_log() {
  [ -z "$log_file" ] && return 0
  printf '%s %s: %s\n' "$(date -Iseconds)" "$log_prefix" "$1" \
    >> "$log_file" 2>/dev/null || true
}

# [MIGRATED -> claude_seedPermissions @ 2026-05-04]
permissions_seed() {
  local installed="$1" default="$2" default_sha_file="$3" prior_sha_file="$4"
  local log_file="${5:-}" log_prefix="${6:-plugin}"
  local current_default_sha installed_sha prior_sha

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

#### end permissions-seed.sh

#### git.sh ####

#!/bin/bash
# git.sh — git query functions.

# source "$(dirname "${BASH_SOURCE[0]}")/silencers.sh"

# ========================================================
# usage: git_is_repo <directory>
# returns: 0 if directory is inside a git work tree, 1 if not
# [IMPORT_FROM_GIT_LIB -> git_lib.isGitRepo @ 2026-05-04]
git_is_repo() {
  hide_output hide_errors git -C "$1" rev-parse --is-inside-work-tree
  local result=$?
  return $result
}

# usage: git_get_repo_root [directory]
# returns: 0 on success (prints absolute repo root path), 1 if not in a git repo
# [IMPORT_FROM_GIT_LIB -> git_lib.getGitRepoRoot @ 2026-05-04]
git_get_repo_root() {
  local dir="${1:-.}"
  local git_common_dir
  git_common_dir="$(hide_errors git -C "$dir" rev-parse --git-common-dir)"
  local result=$?
  if [ $result -ne 0 ]; then
    echo "[git] not inside a git repository" >&2
    return 1
  fi
  (cd "$dir" && cd "$(dirname "$git_common_dir")" && pwd)
}

# usage: git_get_branch_name <directory>
# returns: 0 on success (prints branch name), 1 if not a git repo or detached HEAD
# [IMPORT_FROM_GIT_LIB -> git_lib.getGitBranchNameOrFail @ 2026-05-04]
git_get_branch_name() {
  if ! git_is_repo "$1"; then
    echo "[git] not a git repository: $1" >&2
    return 1
  fi
  local branch
  branch=$(hide_errors git -C "$1" branch --show-current)
  if [ -z "$branch" ]; then
    echo "HEAD detached at $(hide_errors git -C "$1" rev-parse --short HEAD)" >&2
    return 1
  fi
  echo "$branch"
}

# usage: git_get_recent_commits <directory>
# returns: 0 on success (prints space-separated hashes), 1 if not a git repo or no commits
# [IMPORT_FROM_GIT_LIB -> git_lib.getGitRecentCommitHashes @ 2026-05-04]
git_get_recent_commits() {
  if ! git_is_repo "$1"; then
    echo "[git] not a git repository: $1" >&2
    return 1
  fi
  local commits
  commits=$(hide_errors git -C "$1" log --oneline -5 --format='%h' | tr '\n' ' ' | sed 's/ $//')
  if [ -z "$commits" ]; then
    echo "No commits yet" >&2
    return 1
  fi
  echo "$commits"
}

# usage: git_get_uncommitted <directory>
# returns: 0 on success (prints space-separated filenames), 1 if not a git repo
# prints "None" and returns 0 if the working tree is clean
# [IMPORT_FROM_GIT_LIB -> git_lib.getGitUncommittedFilenames @ 2026-05-04]
git_get_uncommitted() {
  if ! git_is_repo "$1"; then
    echo "[git] not a git repository: $1" >&2
    return 1
  fi
  local uncommitted
  uncommitted=$(hide_errors git -C "$1" status --short | awk '{print $2}' | tr '\n' ' ' | sed 's/ $//')
  if [ -z "$uncommitted" ]; then
    echo "None"
    return 0
  fi
  echo "$uncommitted"
}

# usage: git_ensure_gitignore_entry <repo_root> <pattern>
# returns: 0 on success, 1 if not a git repo
# Appends <pattern> to .gitignore if not already present.
# [IMPORT_FROM_GIT_LIB -> git_lib.ensureGitignoreEntry @ 2026-05-04]
git_ensure_gitignore_entry() {
  local gitignore="$1/.gitignore"
  if ! hide_errors grep -qxF "$2" "$gitignore"; then
    printf '\n%s\n' "$2" >> "$gitignore"
  fi
}

# ========================================================
# [COVERED_BY_GIT_LIB_TESTS @ 2026-05-04]
git_tests() {
  local test_dir pass=0 fail=0

  # ── git_is_repo ──
  test_dir=$(mktemp -d)
  git -C "$test_dir" init -q
  if git_is_repo "$test_dir"; then
    echo "PASS: git_is_repo true for repo"
    pass=$((pass + 1))
  else
    echo "FAIL: git_is_repo false for repo"
    fail=$((fail + 1))
  fi
  if ! git_is_repo /tmp; then
    echo "PASS: git_is_repo false for non-repo"
    pass=$((pass + 1))
  else
    echo "FAIL: git_is_repo true for non-repo"
    fail=$((fail + 1))
  fi

  # ── git_get_repo_root ──
  local root
  root=$(git_get_repo_root "$test_dir" 2>/dev/null)
  if [ $? -eq 0 ] && [ "$root" = "$test_dir" ]; then
    echo "PASS: git_get_repo_root returns correct path"
    pass=$((pass + 1))
  else
    echo "FAIL: expected '$test_dir', got '$root'"
    fail=$((fail + 1))
  fi
  if ! git_get_repo_root /tmp 2>/dev/null; then
    echo "PASS: git_get_repo_root fails for non-repo"
    pass=$((pass + 1))
  else
    echo "FAIL: git_get_repo_root should fail for non-repo"
    fail=$((fail + 1))
  fi

  # ── git_get_branch_name ──
  git -C "$test_dir" checkout -b test-branch-$$ -q 2>/dev/null
  git -C "$test_dir" commit --allow-empty -m "init" -q
  local branch
  branch=$(git_get_branch_name "$test_dir" 2>/dev/null)
  if [ $? -eq 0 ] && [ "$branch" = "test-branch-$$" ]; then
    echo "PASS: git_get_branch_name returns branch"
    pass=$((pass + 1))
  else
    echo "FAIL: expected 'test-branch-$$', got '$branch'"
    fail=$((fail + 1))
  fi
  git -C "$test_dir" checkout --detach -q 2>/dev/null
  if ! git_get_branch_name "$test_dir" 2>/dev/null; then
    echo "PASS: git_get_branch_name fails on detached HEAD"
    pass=$((pass + 1))
  else
    echo "FAIL: should fail on detached HEAD"
    fail=$((fail + 1))
  fi
  git -C "$test_dir" checkout test-branch-$$ -q 2>/dev/null

  # ── git_get_recent_commits ──
  git -C "$test_dir" commit --allow-empty -m "second" -q
  local commits
  commits=$(git_get_recent_commits "$test_dir" 2>/dev/null)
  local count
  count=$(echo "$commits" | wc -w | tr -d ' ')
  if [ $? -eq 0 ] && [ "$count" -eq 2 ]; then
    echo "PASS: git_get_recent_commits returns 2 hashes"
    pass=$((pass + 1))
  else
    echo "FAIL: expected 2 hashes, got $count"
    fail=$((fail + 1))
  fi

  # ── git_get_uncommitted ──
  local uncommitted
  uncommitted=$(git_get_uncommitted "$test_dir" 2>/dev/null)
  if [ "$uncommitted" = "None" ]; then
    echo "PASS: git_get_uncommitted clean repo returns 'None'"
    pass=$((pass + 1))
  else
    echo "FAIL: expected 'None', got '$uncommitted'"
    fail=$((fail + 1))
  fi
  echo "dirty" > "$test_dir/changed.txt"
  uncommitted=$(git_get_uncommitted "$test_dir" 2>/dev/null)
  if echo "$uncommitted" | grep -qF 'changed.txt'; then
    echo "PASS: git_get_uncommitted lists changed file"
    pass=$((pass + 1))
  else
    echo "FAIL: expected 'changed.txt', got '$uncommitted'"
    fail=$((fail + 1))
  fi

  # ── git_ensure_gitignore_entry ──
  git_ensure_gitignore_entry "$test_dir" ".plate/"
  if grep -qxF '.plate/' "$test_dir/.gitignore"; then
    echo "PASS: git_ensure_gitignore_entry adds entry"
    pass=$((pass + 1))
  else
    echo "FAIL: entry not found in .gitignore"
    fail=$((fail + 1))
  fi
  git_ensure_gitignore_entry "$test_dir" ".plate/"
  local entry_count
  entry_count=$(grep -cxF '.plate/' "$test_dir/.gitignore")
  if [ "$entry_count" -eq 1 ]; then
    echo "PASS: git_ensure_gitignore_entry is idempotent"
    pass=$((pass + 1))
  else
    echo "FAIL: duplicate entries ($entry_count)"
    fail=$((fail + 1))
  fi

  rm -rf "$test_dir"
  printf "git_tests: PASS=%d FAIL=%d\n" "$pass" "$fail"
  [ "$fail" -eq 0 ]
}

#### end git.sh ####

#### platform.sh ####

# platform.sh — platform-specific UX helpers for Claude Code hooks.
#
# Source this file and call:
#   spawn_terminal_if_needed <session_name> [log_file] [log_prefix] [maximize]
#
# Behaviour: if no tmux client is attached to <session_name>, open a new
# macOS Terminal window attached to it via `tmux attach -t <session_name>`.
# When [maximize] = "yes", resize the new window's bounds to fill the
# desktop (only on first spawn — the early-return for already-attached
# clients still skips the entire osascript block).
# On non-Darwin hosts (or if osascript is unavailable) writes an advisory
# line to <log_file> and returns. Never fails — this is a UX nicety.
#
# Extracted from scripts/jot.sh per plans/jot-generalizing-refactor.md (commit 4).

# source "$(dirname "${BASH_SOURCE[0]}")/silencers.sh"
# source "$(dirname "${BASH_SOURCE[0]}")/tmux.sh"

# [MIGRATED -> terminal_spawnIfNeeded @ 2026-05-04]
spawn_terminal_if_needed() {
  local session="${1:?spawn_terminal_if_needed: session name required}"
  local log_file="${2:-/dev/null}"
  local log_prefix="${3:-tmux}"
  local maximize="${4:-}"
  local clients
  # Probe for attached clients; silence invoke_command's failure log because
  # a missing session is the trigger-condition for spawning, not an error.
  clients=$(hide_errors tmux_list_clients "$session")
  if [ -n "$clients" ]; then
    return 0
  fi
  # Optional window-bounds adjustment after `do script` opens the new
  # Terminal window. Three modes:
  #   "yes"     — maximize to desktop bounds. Used by /debate (4-pane
  #               layout needs the room).
  #   "compact" — clamp to a small centred rect (1000×700). Used by
  #               single-pane spawners (e.g. /plate) so they don't
  #               inherit a maximized geometry left behind by /debate
  #               or by the user manually maximizing a previous window.
  #   ""        — no adjustment (legacy default).
  # Finder's "bounds of window of desktop" excludes the menu bar and
  # tracks the active display, so multi-monitor setups work for both
  # "yes" and "compact" modes.
  local maximize_block=""
  if [ "$maximize" = "yes" ]; then
    maximize_block='
tell application "Finder"
  set screenBounds to bounds of window of desktop
end tell
tell application "Terminal"
  set bounds of front window to screenBounds
end tell'
  elif [ "$maximize" = "compact" ]; then
    maximize_block='
tell application "Finder"
  set screenBounds to bounds of window of desktop
end tell
set sx to item 1 of screenBounds
set sy to item 2 of screenBounds
set ex to item 3 of screenBounds
set ey to item 4 of screenBounds
set winW to 1000
set winH to 700
set winX to sx + ((ex - sx - winW) div 2)
set winY to sy + ((ey - sy - winH) div 2)
tell application "Terminal"
  set bounds of front window to {winX, winY, winX + winW, winY + winH}
end tell'
  fi
  case "${OSTYPE:-}" in
    darwin*)
      if ! hide_output hide_errors command -v osascript; then
        printf '%s %s: osascript unavailable; attach manually via `tmux attach -t %s`\n' \
          "$(date -Iseconds)" "$log_prefix" "$session" >> "$log_file" 2>/dev/null || true
        return 0
      fi
      hide_output hide_errors osascript <<OSA &
if application "Terminal" is running then
  tell application "Terminal" to do script "tmux attach -t ${session}"
else
  tell application "Terminal"
    do script "tmux attach -t ${session}" in window 1
  end tell
end if${maximize_block}
OSA
      ;;
    *)
      printf '%s %s: non-Darwin host; attach manually via `tmux attach -t %s`\n' \
        "$(date -Iseconds)" "$log_prefix" "$session" >> "$log_file" 2>/dev/null || true
      ;;
  esac
}

#### end platform.sh ####

#### lock.sh ####
#!/bin/bash
# lock.sh — mkdir-based lock helpers.
# macOS does not ship flock; mkdir is atomic on every POSIX filesystem.

# source "$(dirname "${BASH_SOURCE[0]}")/silencers.sh"

# usage: lock_acquire <lock_dir> [timeout_seconds] [stale_after_seconds]
# returns: 0 on success, 1 on timeout
# [ABSORBED -> with FileLock(path, timeout=...) @ 2026-05-04]
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
# [ABSORBED -> FileLock.release() / context manager exit @ 2026-05-04]
lock_release() {
  hide_errors rmdir "$1"
  local result=$?
  return $result
}

# [TEST -> test_FileLock_* @ 2026-05-04]
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

#### end lock.sh ####

#### jot-state-lib.sh

#!/bin/bash
# jot-state-lib.sh — shared state-dir and lock helpers for the jot Phase 2
# hook scripts. Sourced by jot-session-start.sh, jot-stop.sh, jot.sh, etc.
#
# Lock model: mkdir-based, no flock dependency. macOS doesn't ship `flock`
# and we want zero brew dependencies beyond what check_requirements covers.
# `mkdir` is atomic on every POSIX filesystem, so this works portably.

# source "${CLAUDE_PLUGIN_ROOT}/common/scripts/invoke_command.sh"
# source "${CLAUDE_PLUGIN_ROOT}/common/scripts/tmux.sh"
# source "${CLAUDE_PLUGIN_ROOT}/common/scripts/lock.sh"

# Aliases for backward compat — callers use jot_lock_acquire/release.
# [ABSORBED -> with FileLock(path, timeout=...) @ 2026-05-04]
jot_lock_acquire() { lock_acquire "$@"; }
# [ABSORBED -> FileLock.release() / context manager exit @ 2026-05-04]
jot_lock_release() { lock_release "$@"; }

# usage: jot_state_init <state_dir>
# [MIGRATED -> jot_initState @ 2026-05-04]
jot_state_init() {
  mkdir -p "$1"
  touch "$1/queue.txt" "$1/active_job.txt" "$1/audit.log"
}

# usage: jot_queue_pop_first <state_dir>
# returns: 0 on success (prints popped line), 1 if queue is empty
# MUST be called while holding the queue lock.
# [MIGRATED -> jot_popFirstFromQueue @ 2026-05-04]
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
# [MIGRATED -> jot_sendPrompt @ 2026-05-04]
jot_send_prompt() {
  tmux_send_and_submit "$1" \
    "Read $2 and follow the instructions at the top of that file"
}

# usage: jot_audit_rotate <audit_log> [max_lines]
# [MIGRATED -> jot_rotateAudit @ 2026-05-04]
jot_audit_rotate() {
  [ -f "$1" ] || return 0
  local max="${2:-1000}"
  local lines
  lines=$(wc -l < "$1" | tr -d ' ')
  if [ "${lines:-0}" -gt "$max" ]; then
    tail -"$max" "$1" > "$1.trim" && mv "$1.trim" "$1"
  fi
}

#### end jot-state-lib.sh

#### jot.sh ####
#!/bin/bash
# jot.sh — function definitions for the /jot hook.
# Sourced by jot-orchestrator.sh. No side effects when sourced.
#
# Phase 1 invariant: the user's idea must survive every partial failure.
#   Whatever goes wrong during enrichment or Phase 2 launch, the input.txt
#   is already on disk (durable-first) so the user can retrieve their idea.
#
# Phase 2: one claude per invocation, running in its own tmux pane inside
#   the cross-project `jot:jots` window. Lifecycle hooks (SessionStart,
#   Stop, SessionEnd) live in scripts/jot-session-start.sh, jot-stop.sh,
#   jot-session-end.sh; they are copied into /tmp/jot.XXXXXX/ at launch
#   so `claude plugin update` cannot yank them mid-run.
#
# Testing hook: set JOT_SKIP_LAUNCH=1 in the environment to skip Phase 2
#   entirely (no tmux, no claude). The canary suite uses this to verify
#   Phase 1 output without spawning real tmux sessions.

# usage: safe <command> [args...]
# returns: stdout from command, or "(unavailable)" on failure
# [ABSORBED -> local try/except or subprocess fallback returning "(unavailable)" @ 2026-05-04]
safe() {
  local out
  out=$(hide_errors "$@") || out="(unavailable)"
  printf '%s' "${out:-(unavailable)}"
}

# usage: jot_build_claude_cmd
# Sets globals: TMPDIR_INV, SETTINGS_FILE, CLAUDE_CMD
# [MIGRATED -> jot_buildClaudeCmd @ 2026-05-04]
jot_build_claude_cmd() {
  TMPDIR_INV=$(mktemp -d /tmp/jot.XXXXXX)
  SETTINGS_FILE="$TMPDIR_INV/settings.json"
  PERMISSIONS_FILE="${CLAUDE_PLUGIN_DATA}/permissions.local.json"

  # Lifecycle-safe: copy hook scripts into TMPDIR_INV so plugin updates
  # can't delete them mid-run.
  cp "${CLAUDE_PLUGIN_ROOT}/scripts/jot-plugin-orchestrator.sh" "$TMPDIR_INV/jot-plugin-orchestrator.sh"

  local permissions_file="${CLAUDE_PLUGIN_DATA}/permissions.local.json"
  local default_file="${CLAUDE_PLUGIN_ROOT}/skills/jot/scripts/assets/permissions.default.json"
  local default_sha_file="${CLAUDE_PLUGIN_ROOT}/skills/jot/scripts/assets/permissions.default.json.sha256"
  local prior_sha_file="${CLAUDE_PLUGIN_DATA}/permissions.default.sha256"
  mkdir -p "${CLAUDE_PLUGIN_DATA}"
  permissions_seed "$permissions_file" "$default_file" "$default_sha_file" "$prior_sha_file" "$LOG_FILE" "jot"

  local allow_json
  allow_json=$(CWD="$CWD" HOME="$HOME" REPO_ROOT="$REPO_ROOT" \
    python3 "${CLAUDE_PLUGIN_ROOT}/common/scripts/jot/expand_permissions.py" "$permissions_file")

  local hooks_json_file="$TMPDIR_INV/hooks.json"
  cat > "$hooks_json_file" <<JSON
{
  "SessionStart": [{"hooks": [{"type": "command", "command": "bash $TMPDIR_INV/jot-plugin-orchestrator.sh jot-session-start '$INPUT_FILE' '$TMPDIR_INV'"}]}],
  "Stop":         [{"hooks": [{"type": "command", "command": "bash $TMPDIR_INV/jot-plugin-orchestrator.sh jot-stop '$INPUT_FILE' '$TMPDIR_INV' '$STATE_DIR'"}]}],
  "SessionEnd":   [{"hooks": [{"type": "command", "command": "bash $TMPDIR_INV/jot-plugin-orchestrator.sh jot-session-end '$TMPDIR_INV'"}]}]
}
JSON

  CLAUDE_CMD=$(build_claude_cmd "$SETTINGS_FILE" "$allow_json" "$hooks_json_file" "$CWD" "$REPO_ROOT")
}

# usage: phase2_launch_window
# Spawns a tmux pane running claude for this jot invocation.
# [MIGRATED -> jot_launchPhase2Window @ 2026-05-04]
phase2_launch_window() {
  STATE_DIR="$REPO_ROOT/Todos/.jot-state"
  jot_state_init "$STATE_DIR"

  mkdir -p "${CLAUDE_PLUGIN_DATA}"
  local tmux_lock="${CLAUDE_PLUGIN_DATA}/tmux-launch.lock"
  if ! jot_lock_acquire "$tmux_lock" 10; then
    hide_errors echo "[jot] failed to acquire global tmux-launch lock at $tmux_lock" >> "$LOG_FILE"
    return 1
  fi

  local counter_file="${CLAUDE_PLUGIN_DATA}/pane-counter.txt"
  local n
  n=$(hide_errors cat "$counter_file") || n=0
  n=$(( n % 20 + 1 ))
  printf '%s\n' "$n" > "$counter_file"
  local pane_label="jot${n}"

  jot_build_claude_cmd

  local keepalive_cmd='exec sh -c '\''trap "" INT HUP TERM; printf "[jot keepalive — do not kill]\n"; exec tail -f /dev/null'\'''
  tmux_ensure_session jot jots "$CWD" "$keepalive_cmd" 'jot: keepalive'

  local PANE_ID
  if ! PANE_ID=$(tmux_split_worker_pane jot:jots "$CWD" "$CLAUDE_CMD"); then
    hide_errors echo "[jot] tmux split-window returned empty pane id" >> "$LOG_FILE"
    jot_lock_release "$tmux_lock"
    return 1
  fi

  printf '%s\n' "$PANE_ID" > "$TMPDIR_INV/tmux_target.tmp"
  mv "$TMPDIR_INV/tmux_target.tmp" "$TMPDIR_INV/tmux_target"

  tmux_set_pane_title "$PANE_ID" "$pane_label"
  tmux_retile jot:jots

  jot_lock_release "$tmux_lock"
  spawn_terminal_if_needed "jot" "$LOG_FILE" "jot"
}

#### scan-open-todos.sh ####
# Moved above jot_main (Phase 0.1) so callees precede callers.
# [PENDING]
scan_open_todos() {
    TARGET_DIR="${1:-.}"
    TODOS_DIR="$TARGET_DIR/Todos"

    if [ ! -d "$TODOS_DIR" ]; then
        exit 0
    fi

    for f in "$TODOS_DIR"/*.md; do
        [ -f "$f" ] || continue
        # Check frontmatter for status: open (within first 10 lines)
        if head -10 "$f" | grep -q '^status: open' 2>/dev/null; then
            echo "$f"
        fi
    done
}
#### end scan-open-todos.sh ####

# usage: jot_main
# Entry point. Reads hook JSON from stdin, runs Phase 1 + Phase 2.
# [PENDING]
jot_main() {
  : "${CLAUDE_PLUGIN_ROOT:?jot plugin env not set — not running under Claude Code plugin harness}"
  : "${CLAUDE_PLUGIN_DATA:?jot plugin env not set — not running under Claude Code plugin harness}"

  SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/skills/jot/scripts"

  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/silencers.sh"
  LOG_FILE="${JOT_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/jot-log.txt}"
  hide_errors mkdir -p "$(dirname "$LOG_FILE")"

#   . "${CLAUDE_PLUGIN_ROOT}/common/scripts/hook-json.sh"
#   . "${CLAUDE_PLUGIN_ROOT}/common/scripts/platform.sh"
#   . "${CLAUDE_PLUGIN_ROOT}/common/scripts/tmux-launcher.sh"
#   . "${CLAUDE_PLUGIN_ROOT}/common/scripts/claude-launcher.sh"
#   . "${CLAUDE_PLUGIN_ROOT}/common/scripts/permissions-seed.sh"
#   . "${CLAUDE_PLUGIN_ROOT}/common/scripts/git.sh"

  INPUT=$(cat)
  case "$INPUT" in
    *'"/jot'*) ;;
    *) exit 0 ;;
  esac

  hide_errors printf '%s HOOK_INPUT %s\n' "$(date -Iseconds)" "$INPUT" >> "$LOG_FILE"
  check_requirements "jot" jq python3 tmux claude
  tmux_require_version "2.9" || { emit_block "jot requires tmux 2.9+"; exit 0; }

#   . "$SCRIPTS_DIR/jot-state-lib.sh"

  PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""' | python3 "${CLAUDE_PLUGIN_ROOT}/common/scripts/jot/strip_stdin.py")
  if [[ "$PROMPT" != "/jot" && "$PROMPT" != "/jot "* ]]; then
    exit 0
  fi

  IDEA="${PROMPT#/jot}"
  IDEA="${IDEA# }"
  IDEA=$(printf '%s' "$IDEA" | python3 "${CLAUDE_PLUGIN_ROOT}/common/scripts/jot/strip_stdin.py")
  if [ -z "$IDEA" ]; then
    emit_block "jot: no idea provided"
    exit 0
  fi

  SESSION_ID=$(printf '%s' "$INPUT" | hide_errors jq -r '.session_id // "?"') || SESSION_ID="?"
  hide_errors printf '%s jot session=%s idea_len=%s\n' "$(date -Iseconds)" "$SESSION_ID" "${#IDEA}" >> "$LOG_FILE"

  trap 'rc=$?; emit_block "jot crashed at line $LINENO (rc=$rc)"; hide_errors printf "%s FAIL line=%s rc=%s\n" "$(date -Iseconds)" "$LINENO" "$rc" >> "$LOG_FILE"; exit 0' ERR

  TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | hide_errors jq -r '.transcript_path // empty')
  CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
  [ -z "$CWD" ] && CWD="$PWD"
  TIMESTAMP=$(date +%Y-%m-%dT%H-%M-%S)

  REPO_ROOT=$(hide_errors git -C "$CWD" rev-parse --show-toplevel) || REPO_ROOT=""
  if [ -z "$REPO_ROOT" ]; then
    emit_block "jot requires a git repository. Run 'git init' in your project root."
    exit 0
  fi

  TARGET_DIR="$REPO_ROOT/Todos"
  mkdir -p "$TARGET_DIR"
  INPUT_FILE="$TARGET_DIR/${TIMESTAMP}_input.txt"
  INPUT_ABS="${REPO_ROOT}/Todos/${TIMESTAMP}_input.txt"

  {
    printf '# Jot Task\n\n## Idea\n%s\n\n' "$IDEA"
    printf '## Working Directory\n%s\n\n' "$CWD"
  } > "$INPUT_FILE"

  BRANCH=$(safe git_get_branch_name "$CWD")
  COMMITS=$(safe git_get_recent_commits "$CWD")
  UNCOMMITTED=$(safe git_get_uncommitted "$CWD")
  OPEN_TODOS=$(safe scan_open_todos "$REPO_ROOT")
  if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
    CONVERSATION=$(safe python3 "$SCRIPTS_DIR/capture-conversation.py" "$TRANSCRIPT_PATH")
  else
    CONVERSATION="(no transcript available)"
  fi

  {
    printf '## Git State\n- Branch: %s\n- Commits: %s\n- Uncommitted: %s\n\n' "$BRANCH" "$COMMITS" "$UNCOMMITTED"
    printf '## Open TODO Files\n%s\n\n' "$OPEN_TODOS"
    printf '## Transcript Path\n%s\n\n' "${TRANSCRIPT_PATH:-(none)}"
    printf '## Recent Conversation\n%s\n\n' "$CONVERSATION"
  } >> "$INPUT_FILE"

  INSTRUCTIONS=$(REPO_ROOT="$REPO_ROOT" TIMESTAMP="$TIMESTAMP" BRANCH="$BRANCH" INPUT_ABS="$INPUT_ABS" \
    python3 "${CLAUDE_PLUGIN_ROOT}/common/scripts/jot/render_template.py" \
      "${CLAUDE_PLUGIN_ROOT}/skills/jot/scripts/assets/jot-instructions.md" \
      REPO_ROOT TIMESTAMP BRANCH INPUT_ABS)

  _BODY=$(cat "$INPUT_FILE")
  {
    printf '# Jot Task\n\n## Instructions\n%s\n\n' "$INSTRUCTIONS"
    printf '%s\n' "$_BODY" | tail -n +2
  } > "$INPUT_FILE"

  if [ "${JOT_SKIP_LAUNCH:-0}" = "1" ]; then
    emit_block "Jotted: $IDEA (launch skipped)"
    exit 0
  fi

  phase2_launch_window
  emit_block "Done! Jotted idea in $INPUT_ABS"
  exit 0
}

#### end jot.sh ####

#### plate.sh ####

#!/usr/bin/env bash
# plate.sh — function definitions for the /plate UserPromptSubmit hook.
# Sourced by plate-orchestrator.sh. No side effects when sourced.
#
# Branch-model wiring (2026-05-01): every /plate variant runs inline by
# invoking common/scripts/plate/cli.py. The Python CLI's stdout becomes
# the user-facing message via emit_block. Same shape as /jot — no
# pending-*.json drop files, no AskUserQuestion bridges, no foreground-
# claude detour.

# usage: plate_main
# Entry point. Reads hook JSON from stdin, dispatches /plate variants
# inline, emits a single block back to the foreground claude.
# [PENDING]
plate_main() {
  : "${CLAUDE_PLUGIN_ROOT:?plate plugin env not set — not running under Claude Code plugin harness}"
  : "${CLAUDE_PLUGIN_DATA:?plate plugin env not set — not running under Claude Code plugin harness}"

#   . "${CLAUDE_PLUGIN_ROOT}/common/scripts/silencers.sh"
#   . "${CLAUDE_PLUGIN_ROOT}/common/scripts/hook-json.sh"
#   . "${CLAUDE_PLUGIN_ROOT}/common/scripts/git.sh"

  # Provisional log path (used until we resolve REPO_ROOT). Per-repo
  # path is preferred so multi-worktree work each has its own log.
  LOG_FILE="${PLATE_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/plate-log.txt}"
  hide_errors mkdir -p "$(dirname "$LOG_FILE")"

  # ── Fast-path bail-out (mirrors jot.sh:130-133) ──────────────────────
  # Substring match against raw INPUT JSON before any jq parsing. Any
  # non-/plate prompt exits silently with no Python startup cost.
  INPUT=$(cat)
  case "$INPUT" in
    *'"/plate'*) ;;
    *) exit 0 ;;
  esac

  check_requirements "plate" jq python3

  # ── Strict prompt regex — typos exit silently before spawning Python ─
  PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""')
  PROMPT="${PROMPT#"${PROMPT%%[![:space:]]*}"}"   # lstrip whitespace
  if ! printf '%s' "$PROMPT" \
       | grep -qE '^/plate(\s+(--done|--drop|--trash|--recycle(\s+--list|\s+\S+)?|--show|--next( +[0-9A-Za-z._@#$+-]+)?))?$'; then
    exit 0
  fi

  SESSION_ID=$(printf '%s' "$INPUT" | hide_errors jq -r '.session_id // "?"') || SESSION_ID="?"
  TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | hide_errors jq -r '.transcript_path // empty')
  CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
  [ -z "$CWD" ] && CWD="$PWD"

  # All branch-model variants need a git repo to operate on. If we can't
  # find one, surface a friendly message instead of crashing in Python.
  REPO_ROOT=$(hide_errors git -C "$CWD" rev-parse --show-toplevel) || REPO_ROOT=""
  if [ -z "$REPO_ROOT" ]; then
    emit_block "plate requires a git repository. Run 'git init' in your project root."
    exit 0
  fi

  # Promote LOG_FILE to per-repo path now that REPO_ROOT is known. Honour
  # an explicit PLATE_LOG_FILE env override (e.g. tests pinning a path).
  if [ -z "${PLATE_LOG_FILE:-}" ]; then
    LOG_FILE="$REPO_ROOT/.plate/plate-log.txt"
    hide_errors mkdir -p "$(dirname "$LOG_FILE")"
    # Ensure the log file is gitignored. If it weren't, every /plate
    # write to it would mark the WT dirty, and the next plate_push (e.g.
    # the SessionEnd auto-/plate fired on conversation reload) would see
    # a different WT-tree than the prior plate's tree and create a
    # spurious second plate commit + spawn a second summary agent.
    hide_errors git_ensure_gitignore_entry "$REPO_ROOT" ".plate/plate-log.txt"
  fi
  # Export so the spawned summary agent's per-invocation SessionEnd
  # hook writes to the same file.
  export PLATE_LOG_FILE="$LOG_FILE"

  hide_errors printf '%s plate prompt="%s"\n' "$(date -Iseconds)" "$PROMPT" >> "$LOG_FILE"

  # ── ERR trap: any failure becomes a single user-visible block ────────
  trap 'rc=$?; emit_block "plate crashed at line $LINENO (rc=$rc)"; hide_errors printf "%s FAIL line=%s rc=%s cmd=%s\n" "$(date -Iseconds)" "$LINENO" "$rc" "$BASH_COMMAND" >> "$LOG_FILE"; exit 0' ERR

  # ── Map prompt → cli.py argv ─────────────────────────────────────────
  CLI_PATH="${CLAUDE_PLUGIN_ROOT}/common/scripts/plate/cli.py"
  case "$PROMPT" in
    "/plate")                        ARGS=(push "$SESSION_ID" "$TRANSCRIPT_PATH" "$REPO_ROOT") ;;
    "/plate --done")                 ARGS=(done    "$REPO_ROOT") ;;
    "/plate --drop")                 ARGS=(drop    "$REPO_ROOT") ;;
    "/plate --trash")                ARGS=(trash   "$REPO_ROOT") ;;
    "/plate --recycle")              ARGS=(recycle "$REPO_ROOT") ;;
    "/plate --recycle --list")       ARGS=(recycle "$REPO_ROOT" --list) ;;
    "/plate --recycle "*)            ARGS=(recycle "$REPO_ROOT" "${PROMPT#/plate --recycle }") ;;
    "/plate --show")                 ARGS=(show    "$REPO_ROOT") ;;
    "/plate --next")                 ARGS=(next    "$REPO_ROOT") ;;
    "/plate --next "*)               ARGS=(next    "$REPO_ROOT" "${PROMPT#/plate --next }") ;;
    *) emit_block "plate: unrecognized variant '$PROMPT'"; exit 0 ;;
  esac

  OUT=$(python3 "$CLI_PATH" "${ARGS[@]}" 2>&1) || true
  emit_block "$OUT"
  exit 0
}

#### end plate.sh #### 

#### debate.sh ####
#!/bin/bash
# debate.sh — function definitions for the /debate hook.
# Sourced by debate-orchestrator.sh. No side effects when sourced.
#
# debate_main() parses the hook JSON, sets up Debates/<ts>_<slug>/, seeds
# Claude settings (permissions only — no lifecycle hooks, unlike jot), then
# forks debate-tmux-orchestrator.sh as a background daemon. The hook returns
# immediately; the daemon drives R1 → R2 → synthesis in its own time.

# ── Provider detection (3-stage: binary + credentials + smoke test) ──

# Bash-native timeout (macOS lacks GNU timeout).
# Uses SIGTERM followed by SIGKILL because agent CLIs (notably gemini) trap
# SIGTERM and keep running to completion — causing the bash-level `wait` to
# block for the agent's natural runtime (200s+) rather than the requested
# timeout. SIGKILL cannot be caught, so the process dies within ~1s.
# [MIGRATED -> shell_runWithTimeout @ 2026-05-04]
_run_with_timeout() {
  local secs=$1; shift
  "$@" &
  local pid=$!
  (
    sleep "$secs"
    hide_errors kill -TERM "$pid"
    sleep 1
    hide_errors kill -KILL "$pid"
  ) &
  local watchdog=$!
  hide_errors wait "$pid"
  local rc=$?
  hide_errors kill -KILL "$watchdog"
  hide_errors wait "$watchdog"
  return $rc
}

# Atomically claim the lowest-unused `debate-N` session. `tmux new-session -d`
# is the atomic primitive: it returns non-zero on name collision, so looping
# over N until one call succeeds is race-free across concurrent /debate hooks.
# Avoids the TOCTOU window of a has-session pre-check. First window named
# `main`; $1 (keepalive_cmd) becomes that window's argv. Prints claimed
# session name on stdout. Bound is a safety cap on pathological tmux state.
# [PENDING]
debate_claim_session() {
  local keepalive_cmd="$1"
  local n=1 session
  while [ "$n" -lt 1000 ]; do
    session="debate-$n"
    if hide_errors tmux new-session -d -s "$session" \
         -x 200 -y 60 \
         -n main \
         "$keepalive_cmd"; then
      printf '%s\n' "$session"
      return 0
    fi
    n=$((n + 1))
  done
  return 1
}

# _default_model <agent>
# Reads the launch-time model (index 0) from models.json for <agent>. Empty
# string if no models listed for that agent. Used by detect_available_agents
# to assign a model without running a live smoke test — because at least one
# agent CLI (gemini) can take 200-400s to respond to a trivial `-p "Reply…"`
# probe, making live smoke tests unusable here. launch_agent's 120s readiness
# timeout catches broken agents at R1 spawn time instead.
# [PENDING]
_default_model() {
  local models_json="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/assets/models.json"
  local agent="$1"
  hide_errors jq -r --arg a "$agent" '.[$a][0] // ""' "$models_json"
}

# _probe_gemini / _probe_codex — run inside backgrounded subshells. Presence
# check only (binary + credentials). Empty stdout → unavailable. Non-empty
# stdout → the configured model name (or "" if no models configured).
# [PENDING]
_probe_gemini() {
  hide_output hide_errors command -v gemini || return 0
  [[ -f "$HOME/.gemini/oauth_creds.json" ]] \
    || [[ -n "${GEMINI_API_KEY:-}" ]] \
    || [[ -n "${GOOGLE_API_KEY:-}" ]] \
    || return 0
  # Non-empty model name OR literal "present" sentinel so the outer `-s` check
  # treats gemini as available even when no model is configured.
  local m; m=$(_default_model gemini)
  printf '%s\n' "${m:-present}"
}
# [PENDING]
_probe_codex() {
  hide_output hide_errors command -v codex || return 0
  [[ -f "$HOME/.codex/auth.json" ]] || [[ -n "${OPENAI_API_KEY:-}" ]] || return 0
  local m; m=$(_default_model codex)
  printf '%s\n' "${m:-present}"
}

# [PENDING]
detect_available_agents() {
  AVAILABLE_AGENTS=(claude)
  GEMINI_MODEL=""
  CODEX_MODEL=""

  local tmpdir
  tmpdir=$(mktemp -d /tmp/debate-detect.XXXXXX)
  ( _probe_gemini > "$tmpdir/gemini" ) &
  ( _probe_codex  > "$tmpdir/codex"  ) &
  wait
  local m
  if [ -s "$tmpdir/gemini" ]; then
    AVAILABLE_AGENTS+=(gemini)
    m=$(cat "$tmpdir/gemini")
    [ "$m" = "present" ] || GEMINI_MODEL="$m"
  fi
  if [ -s "$tmpdir/codex" ]; then
    AVAILABLE_AGENTS+=(codex)
    m=$(cat "$tmpdir/codex")
    [ "$m" = "present" ] || CODEX_MODEL="$m"
  fi
  rm -rf "$tmpdir"
}

# ── Claude settings builder ──
# Writes a settings.json granting the debate permissions. No SessionStart /
# Stop / SessionEnd hooks — the daemon drives Claude interactively via
# tmux send-keys, so no lifecycle instrumentation is needed.
# [PENDING]
debate_build_claude_cmd() {
  TMPDIR_INV=$(mktemp -d /tmp/debate.XXXXXX)
  SETTINGS_FILE="$TMPDIR_INV/settings.json"

  local permissions_file="${CLAUDE_PLUGIN_DATA}/debate-permissions.local.json"
  local default_file="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/assets/permissions.default.json"
  local default_sha_file="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/assets/permissions.default.json.sha256"
  local prior_sha_file="${CLAUDE_PLUGIN_DATA}/debate-permissions.default.sha256"
  mkdir -p "${CLAUDE_PLUGIN_DATA}"
  permissions_seed "$permissions_file" "$default_file" "$default_sha_file" "$prior_sha_file" "$LOG_FILE" "debate"

  local allow_json
  allow_json=$(CWD="$CWD" HOME="$HOME" REPO_ROOT="$REPO_ROOT" \
    python3 "${CLAUDE_PLUGIN_ROOT}/common/scripts/jot/expand_permissions.py" "$permissions_file")

  # Empty hooks object — build_claude_cmd requires a file but we have no hooks.
  local hooks_json_file="$TMPDIR_INV/hooks.json"
  printf '{}\n' > "$hooks_json_file"

  build_claude_cmd "$SETTINGS_FILE" "$allow_json" "$hooks_json_file" "$CWD" "$REPO_ROOT" > /dev/null
}

# ── Shared hook setup ──

# init_hook_context
# Reads hook JSON from stdin and sets shared globals (INPUT, CWD,
# TRANSCRIPT_PATH, REPO_ROOT, SCRIPTS_DIR, LOG_FILE). Sources the
# common libs. Called by debate_main, debate_retry_main, debate_abort_main.
# [PENDING]
init_hook_context() {
  : "${CLAUDE_PLUGIN_ROOT:?debate plugin env not set}"
  : "${CLAUDE_PLUGIN_DATA:?debate plugin env not set}"
  SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts"

  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/silencers.sh"
  LOG_FILE="${DEBATE_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/debate-log.txt}"
  hide_errors mkdir -p "$(dirname "$LOG_FILE")"

#   . "${CLAUDE_PLUGIN_ROOT}/common/scripts/hook-json.sh"
#   . "${CLAUDE_PLUGIN_ROOT}/common/scripts/platform.sh"
#   . "${CLAUDE_PLUGIN_ROOT}/common/scripts/tmux-launcher.sh"
#   . "${CLAUDE_PLUGIN_ROOT}/common/scripts/claude-launcher.sh"
#   . "${CLAUDE_PLUGIN_ROOT}/common/scripts/permissions-seed.sh"

  INPUT=${INPUT:-$(cat)}
  CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
  [ -z "$CWD" ] && CWD="$PWD"
  TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | hide_errors jq -r '.transcript_path // empty')
  REPO_ROOT=$(hide_errors git -C "$CWD" rev-parse --show-toplevel) || REPO_ROOT=""
}

# find_matching_debate <repo_root> <topic>
# Prints the matching debate dir path, or empty if none. Uses cmp so
# multi-line topics and trailing-newline edge cases work correctly.
# Most-recent dir (lexicographic timestamp) wins.
# [PENDING]
find_matching_debate() {
  local repo_root="$1" topic="$2"
  local dir match_ts="" best=""
  for dir in "$repo_root"/Debates/*/; do
    [ -f "$dir/topic.md" ] || continue
    if printf '%s\n' "$topic" | hide_errors cmp -s - "$dir/topic.md"; then
      local ts; ts=$(basename "$dir")
      if [[ "$ts" > "$match_ts" ]]; then
        match_ts="$ts"
        best="${dir%/}"
      fi
    fi
  done
  printf '%s' "$best"
}

# check_resume_feasibility
# Expects $DEBATE_DIR and AVAILABLE_AGENTS set. Permissive resume check:
#   - Appeared agents (in AVAILABLE_AGENTS but not in original composition)
#     are accepted — they'll be added to the debate, their instructions get
#     built just-in-time, and they run at each stage.
#   - Disappeared agents (in original composition but not in AVAILABLE_AGENTS)
#     are OK only if their R1 AND R2 outputs already exist; those outputs are
#     reused and the agent is re-added to AVAILABLE_AGENTS so synthesis
#     includes them. Otherwise hard-fail: cannot run a missing agent.
# Original composition is derived from r1_instructions_<agent>.txt filenames.
# [PENDING]
check_resume_feasibility() {
  local -a original=()
  local f agent
  for f in "$DEBATE_DIR"/r1_instructions_*.txt; do
    [ -f "$f" ] || continue
    agent=$(basename "$f" .txt)
    agent="${agent#r1_instructions_}"
    original+=("$agent")
  done

  local orig unusable=""
  for orig in "${original[@]}"; do
    case " ${AVAILABLE_AGENTS[*]} " in
      *" $orig "*) continue ;;
    esac
    # Disappeared — reusable iff outputs are complete.
    if [ -s "$DEBATE_DIR/r1_${orig}.md" ] && [ -s "$DEBATE_DIR/r2_${orig}.md" ]; then
      AVAILABLE_AGENTS+=("$orig")
    else
      unusable="$unusable $orig"
    fi
  done

  if [ -n "$unusable" ]; then
    emit_block "/debate: cannot resume, these original agents are unavailable and their outputs are incomplete:${unusable}. Fix credentials/quota and re-run '/debate <topic>', or '/debate-abort' to delete."
    exit 0
  fi
}

# any_live_lock <debate_dir> → 0 if a live lock exists, 1 otherwise.
# [PENDING]
any_live_lock() {
  local dir="$1" lock pane_id
  for lock in "$dir"/.*.lock; do
    [ -f "$lock" ] || continue
    pane_id=$(sed -n 's|^debate:\(%[0-9]*\)$|\1|p' "$lock")
    [ -n "$pane_id" ] && hide_errors tmux list-panes -a -F '#{pane_id}' | grep -qFx "$pane_id" && return 0
  done
  return 1
}

# live_debate_session <debate_dir> → prints the session currently hosting the
# debate's panes, empty on failure. Since debate-N is chosen at claim time and
# not stored on disk, we recover it by asking tmux which session owns any
# still-live lock-file pane id. Self-healing across session renames; no
# separate session-name artifact to keep in sync.
# [PENDING]
live_debate_session() {
  local dir="$1" lock pane_id session
  for lock in "$dir"/.*.lock; do
    [ -f "$lock" ] || continue
    pane_id=$(sed -n 's|^debate:\(%[0-9]*\)$|\1|p' "$lock")
    [ -n "$pane_id" ] || continue
    session=$(hide_errors tmux display-message -p -t "$pane_id" '#{session_name}') || continue
    [ -n "$session" ] && { printf '%s\n' "$session"; return 0; }
  done
  return 1
}

#### debate-build-prompts.sh ####
# Moved above debate_start_or_resume (Phase 0.1) so callees precede callers.
# Builds per-stage instruction files from templates.
# Usage (function-call form): DEBATE_AGENTS="claude gemini codex" debate_build_prompts <stage> <debate_dir> <plugin_root>
#   stage: r1 | r2 | synthesis
# DEBATE_AGENTS env var: space-separated list of active agents for this debate.
# AGENT_FILTER env var (optional): emit only that agent's instruction file.
# [PENDING]
debate_build_prompts() {
  local STAGE="$1"
  local DEBATE_DIR="$2"
  local PLUGIN_ROOT="$3"
  local RENDER="$PLUGIN_ROOT/common/scripts/jot/render_template.py"
  local -a AGENTS=()
  if [ -n "${DEBATE_AGENTS:-}" ]; then
    read -ra AGENTS <<< "$DEBATE_AGENTS"
  else
    local line
    while IFS= read -r line; do
      [ -n "$line" ] && AGENTS+=("$line")
    done < "$DEBATE_DIR/agents.txt"
  fi
  local FILTER="${AGENT_FILTER:-}"
  local agent other
  local -a others
  case "$STAGE" in
    r1)
      for agent in "${AGENTS[@]}"; do
        [ -n "$FILTER" ] && [ "$FILTER" != "$agent" ] && continue
        DEBATE_DIR="$DEBATE_DIR" \
        OUTPUT_FILE="$DEBATE_DIR/r1_${agent}.md" \
          python3 "$RENDER" \
            "$PLUGIN_ROOT/skills/debate/prompts/r1.template.md" \
            DEBATE_DIR OUTPUT_FILE \
          > "$DEBATE_DIR/r1_instructions_${agent}.txt"
      done
      ;;
    r2)
      for agent in "${AGENTS[@]}"; do
        [ -n "$FILTER" ] && [ "$FILTER" != "$agent" ] && continue
        others=()
        for other in "${AGENTS[@]}"; do
          [ "$other" = "$agent" ] && continue
          others+=("$other")
        done
        {
          printf '# Debate -- Round 2: Cross-Critique\n\n'
          printf '## Your Round 1 Response\nRead from: %s\n\n' "$DEBATE_DIR/r1_${agent}.md"
          printf '## Other Agents'\'' Round 1 Responses\n'
          for other in "${others[@]}"; do
            printf 'Read %s'\''s response from: %s\n' "$other" "$DEBATE_DIR/r1_${other}.md"
          done
          printf '\n## Instructions\n'
          printf '%s\n' '- Identify agreement and disagreement across responses'
          printf '%s\n' '- Validate or challenge claims with evidence'
          printf '%s\n' '- Concede where others made stronger arguments'
          printf '%s\n' '- Raise new considerations from reading their perspectives'
          printf '\n## Output\nWrite your critique as markdown to: %s\nDo not write to any other file.\n' "$DEBATE_DIR/r2_${agent}.md"
        } > "$DEBATE_DIR/r2_instructions_${agent}.txt"
      done
      ;;
    synthesis)
      {
        printf '# Debate -- Round 3: Synthesis\n\n'
        printf '%d agents (%s) debated across two rounds. Produce a balanced assessment.\n\n' \
          "${#AGENTS[@]}" "${AGENTS[*]}"
        printf '## Round 1 Responses\n'
        for agent in "${AGENTS[@]}"; do
          printf 'Read %s R1 from: %s\n' "$agent" "$DEBATE_DIR/r1_${agent}.md"
        done
        printf '\n## Round 2 Responses\n'
        for agent in "${AGENTS[@]}"; do
          printf 'Read %s R2 from: %s\n' "$agent" "$DEBATE_DIR/r2_${agent}.md"
        done
        printf '\n## Structure\n'
        printf '1. **Topic**: One-line restatement\n'
        printf '2. **Agreement**: Where agents align\n'
        printf '3. **Disagreement**: Where they diverge, strongest argument per side\n'
        printf '4. **Strongest Arguments**: Most compelling points, attributed\n'
        printf '5. **Weaknesses**: Arguments successfully challenged in R2\n'
        printf '6. **Path Forward**: Synthesized recommendation\n'
        printf '7. **Confidence**: High/Medium/Low with reasoning\n'
        printf '8. **Open Questions**: Unresolved issues\n'
        printf '\n## Output\nWrite synthesis as markdown to: %s\nDo not write to any other file.\n' "$DEBATE_DIR/synthesis.md"
      } > "$DEBATE_DIR/synthesis_instructions.txt"
      ;;
    *) echo "Unknown stage: $STAGE" >&2; return 1 ;;
  esac
}

# debate_start_or_resume
# Shared body invoked by fresh-start and resume paths. Caller sets:
# TOPIC, DEBATE_DIR, RESUMING (0|1), AVAILABLE_AGENTS, GEMINI_MODEL,
# CODEX_MODEL, SCRIPTS_DIR, CWD, REPO_ROOT, LOG_FILE.
# [PENDING]
debate_start_or_resume() {
  # One tmux session per invocation; always a single window named `main`.
  # Session name `debate-N` is chosen at claim time below.
  local window_name="main"

  # Snapshot composition BEFORE any rebuild modifies r1_instructions_*.txt.
  # The daemon uses this to detect drift (appeared/disappeared agents) and
  # reset R2 artifacts so every agent critiques the correct roster.
  local composition_drifted=0
  if [ "$RESUMING" = 1 ]; then
    local -a _original=()
    local _f _aa
    for _f in "$DEBATE_DIR"/r1_instructions_*.txt; do
      [ -f "$_f" ] || continue
      _aa=$(basename "$_f" .txt); _aa="${_aa#r1_instructions_}"
      _original+=("$_aa")
    done
    local _orig_sorted _new_sorted
    _orig_sorted=$(printf '%s\n' "${_original[@]}" | sort -u | tr '\n' ' ')
    _new_sorted=$(printf '%s\n' "${AVAILABLE_AGENTS[@]}" | sort -u | tr '\n' ' ')
    [ "$_orig_sorted" != "$_new_sorted" ] && composition_drifted=1
  fi

  # Per-stage instruction build. Only missing files get built; full composition
  # provides context. R2 and synthesis templates reference r1_<agent>.md /
  # r2_<agent>.md only as paths (debate-build-prompts.sh never reads their
  # content), so they can be built at /debate-start time — surfacing any
  # template error here via emit_block rather than 15 min later in the daemon.
  # Composition drift (resume path) still rebuilds r2/synth inside daemon_main.
  local _a
  for _a in "${AVAILABLE_AGENTS[@]}"; do
    [ -f "$DEBATE_DIR/r1_instructions_${_a}.txt" ] && continue
    DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" AGENT_FILTER="$_a" \
      debate_build_prompts r1 "$DEBATE_DIR" "${CLAUDE_PLUGIN_ROOT}"
  done
  for _a in "${AVAILABLE_AGENTS[@]}"; do
    [ -f "$DEBATE_DIR/r2_instructions_${_a}.txt" ] && continue
    DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" AGENT_FILTER="$_a" \
      debate_build_prompts r2 "$DEBATE_DIR" "${CLAUDE_PLUGIN_ROOT}"
  done
  if [ ! -f "$DEBATE_DIR/synthesis_instructions.txt" ]; then
    DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" \
      debate_build_prompts synthesis "$DEBATE_DIR" "${CLAUDE_PLUGIN_ROOT}"
  fi

  debate_build_claude_cmd

  local keepalive_cmd='exec sh -c '\''trap "" INT HUP TERM; printf "[debate keepalive]\n"; exec tail -f /dev/null'\'''
  local session
  session=$(debate_claim_session "$keepalive_cmd") || {
    emit_block "/debate: could not claim debate-<N> session (1000 already in use)"; exit 0
  }
  # Session-scoped options that tmux_ensure_session used to set. Kept here
  # so the pane-title border (which `select-pane -T` writes to) actually
  # renders, and so mouse works for the attached Terminal.
  hide_errors tmux set-option -t "$session" remain-on-exit off
  hide_errors tmux set-option -t "$session" mouse on
  hide_errors tmux set-option -t "$session" pane-border-status top
  hide_errors tmux set-option -t "$session" pane-border-format ' #{pane_title} '
  # Title the keepalive pane with the debate's directory basename so
  # live_debate_session (and human observers attaching via `tmux attach`)
  # can tell at a glance which debate the session hosts, even after
  # debate-N numbers get reused once a session dies.
  hide_errors tmux select-pane -t "${session}:main" -T "keepalive:$(basename "$DEBATE_DIR")"

  local orch_log="$DEBATE_DIR/orchestrator.log"
  GEMINI_MODEL="$GEMINI_MODEL" CODEX_MODEL="$CODEX_MODEL" \
  DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" COMPOSITION_DRIFTED="$composition_drifted" \
  SESSION="$session" \
    bash "${CLAUDE_PLUGIN_ROOT}/scripts/jot-plugin-orchestrator.sh" debate-tmux-orchestrator \
      "$DEBATE_DIR" "$session" "$window_name" "$SETTINGS_FILE" "$CWD" "$REPO_ROOT" "${CLAUDE_PLUGIN_ROOT}" \
      >> "$orch_log" 2>&1 </dev/null &
  disown

  spawn_terminal_if_needed "$session" "$LOG_FILE" "debate" "yes"

  local agents_str="${AVAILABLE_AGENTS[*]}"
  local rel="Debates/$(basename "$DEBATE_DIR")"
  local verb="spawned"
  [ "$RESUMING" = 1 ] && verb="resumed"
  emit_block "/debate ${verb} (${agents_str// /, }) → ${rel}/synthesis.md (~10-30 min). View: tmux attach -t ${session}"
}

# ── Main entry point ──

# [PENDING]
debate_main() {
  init_hook_context
  check_requirements "debate" jq python3 tmux claude

  case "$INPUT" in *'"/debate'*) ;; *) exit 0 ;; esac
  hide_errors printf '%s HOOK_INPUT %s\n' "$(date -Iseconds)" "$INPUT" >> "$LOG_FILE"

  PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""')
  PROMPT="${PROMPT#"${PROMPT%%[![:space:]]*}"}"
  [[ "$PROMPT" == "/debate" || "$PROMPT" == "/debate "* ]] || exit 0

  TOPIC="${PROMPT#/debate}"
  TOPIC="${TOPIC# }"
  [ -z "$TOPIC" ] && { emit_block "debate: no topic provided. Usage: /debate <topic>"; exit 0; }
  [ -z "$REPO_ROOT" ] && { emit_block "debate requires a git repository."; exit 0; }

  trap 'rc=$?; emit_block "debate crashed at line $LINENO (rc=$rc)"; exit 0' ERR

  detect_available_agents

  local existing
  existing=$(find_matching_debate "$REPO_ROOT" "$TOPIC")
  RESUMING=0
  if [ -n "$existing" ]; then
    if [ -f "$existing/synthesis.md" ]; then
      emit_block "/debate: already complete, see $existing/synthesis.md — or 'rm -rf $existing' to re-run"; exit 0
    fi
    if any_live_lock "$existing"; then
      local live; live=$(live_debate_session "$existing") || live="<unknown>"
      emit_block "/debate: already running for this topic → tmux attach -t ${live}"; exit 0
    fi
    DEBATE_DIR="$existing"
    RESUMING=1
  else
    if [ "${#AVAILABLE_AGENTS[@]}" -lt 2 ]; then
      emit_block "/debate: needs ≥2 agents, got: ${AVAILABLE_AGENTS[*]}. All configured models for missing agents failed smoke tests. Fix credentials/quota and re-run '/debate <topic>'."
      exit 0
    fi
    local TIMESTAMP slug
    TIMESTAMP=$(date +%Y-%m-%dT%H-%M-%S)
    slug=$(printf '%s' "$TOPIC" | tr '[:upper:]' '[:lower:]' | tr -cs '[:alnum:]' '-' | head -c 40 | sed 's/-$//')
    DEBATE_DIR="$REPO_ROOT/Debates/${TIMESTAMP}_${slug}"
    mkdir -p "$DEBATE_DIR"
    printf '%s\n' "$TOPIC" > "$DEBATE_DIR/topic.md"
    [ -n "$TRANSCRIPT_PATH" ] && printf '%s\n' "$TRANSCRIPT_PATH" > "$DEBATE_DIR/invoking_transcript.txt"

    local capture_script="${CLAUDE_PLUGIN_ROOT}/skills/jot/scripts/capture-conversation.py"
    if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ] && [ -f "$capture_script" ]; then
      if ! hide_errors python3 "$capture_script" "$TRANSCRIPT_PATH" > "$DEBATE_DIR/context.md" \
           || [ ! -s "$DEBATE_DIR/context.md" ]; then
        printf '(conversation capture failed)\n' > "$DEBATE_DIR/context.md"
      fi
    else
      printf '(no conversation context available)\n' > "$DEBATE_DIR/context.md"
    fi
  fi

  if [ "$RESUMING" = 1 ]; then
    check_resume_feasibility
    rm -f "$DEBATE_DIR/FAILED.txt"
  fi

  debate_start_or_resume
  exit 0
}

# ── /debate-retry entry point ──

# [PENDING]
debate_retry_main() {
  init_hook_context
  check_requirements "debate-retry" jq python3 tmux claude

  [ -z "$TRANSCRIPT_PATH" ] && { emit_block "/debate-retry: no transcript_path in hook payload"; exit 0; }
  [ -z "$REPO_ROOT" ] && { emit_block "/debate-retry requires a git repository"; exit 0; }

  trap 'rc=$?; emit_block "debate-retry crashed at line $LINENO (rc=$rc)"; exit 0' ERR

  local dir best_ts="" best=""
  for dir in "$REPO_ROOT"/Debates/*/; do
    [ -f "$dir/invoking_transcript.txt" ] || continue
    [ "$(cat "$dir/invoking_transcript.txt")" = "$TRANSCRIPT_PATH" ] || continue
    local ts; ts=$(basename "$dir")
    if [[ "$ts" > "$best_ts" ]]; then best_ts="$ts"; best="${dir%/}"; fi
  done
  [ -z "$best" ] && { emit_block "/debate-retry: no debate found in this conversation"; exit 0; }

  if [ -f "$best/synthesis.md" ]; then
    emit_block "/debate-retry: already complete, see $best/synthesis.md"; exit 0
  fi
  if any_live_lock "$best"; then
    local live; live=$(live_debate_session "$best") || live="<unknown>"
    emit_block "/debate-retry: still running → tmux attach -t ${live}"; exit 0
  fi

  DEBATE_DIR="$best"
  TOPIC=$(cat "$best/topic.md")
  RESUMING=1

  detect_available_agents
  check_resume_feasibility

  rm -f "$DEBATE_DIR/FAILED.txt"
  debate_start_or_resume
  exit 0
}

# ── /debate-abort entry point ──

# [PENDING]
debate_abort_main() {
  init_hook_context
  check_requirements "debate-abort" jq tmux

  [ -z "$TRANSCRIPT_PATH" ] && { emit_block "/debate-abort: no transcript_path in hook payload"; exit 0; }
  [ -z "$REPO_ROOT" ] && { emit_block "/debate-abort requires a git repository"; exit 0; }

  local dir best_ts="" best=""
  for dir in "$REPO_ROOT"/Debates/*/; do
    [ -f "$dir/invoking_transcript.txt" ] || continue
    [ "$(cat "$dir/invoking_transcript.txt")" = "$TRANSCRIPT_PATH" ] || continue
    local ts; ts=$(basename "$dir")
    if [[ "$ts" > "$best_ts" ]]; then best_ts="$ts"; best="${dir%/}"; fi
  done
  [ -z "$best" ] && { emit_block "/debate-abort: no debate found in this conversation"; exit 0; }

  if any_live_lock "$best"; then
    local live; live=$(live_debate_session "$best") || live="<unknown>"
    emit_block "/debate-abort: debate is running. to force-kill: tmux kill-session -t ${live}"
    exit 0
  fi
  rm -rf "$best"
  emit_block "/debate-abort: deleted $best"
  exit 0
}

#### end debate.sh

#### debate-tmux-orchestrator.sh ####
# Background daemon that drives the full R1 -> R2 -> synthesis flow inside
# the debate's tmux session. Forked from debate.sh as:
#   bash <orchestrator>.sh debate-tmux-orchestrator ... &; disown
# The argv-dispatch case routes to `debate_tmux_orchestrator` below.

# [PENDING]
cleanup() {
  local settings_dir
  settings_dir=$(dirname "$SETTINGS_FILE")
  case "$settings_dir" in
    /tmp/debate.*) rm -rf "$settings_dir" ;;
  esac
}

# [PENDING]
_stash()  { eval "${1}_${2}=\"\$3\""; }
# [PENDING]
_lookup() { local _v="${1}_${2}"; eval "printf '%s' \"\${$_v:-}\""; }

# [PENDING]
init_agent_models() {
  local _a
  for _a in gemini codex claude; do
    _stash CURRENT_MODEL "$_a" ""
    _stash TRIED_MODELS  "$_a" ""
  done
  _stash CURRENT_MODEL gemini "${GEMINI_MODEL:-}"
  _stash CURRENT_MODEL codex  "${CODEX_MODEL:-}"
  _stash TRIED_MODELS  gemini "${GEMINI_MODEL:-}"
  _stash TRIED_MODELS  codex  "${CODEX_MODEL:-}"
}

# [PENDING]
agent_launch_cmd() {
  local a="$1"
  local m; m=$(_lookup CURRENT_MODEL "$a")
  case "$a" in
    gemini)
      if [ -n "$m" ]; then
        echo "gemini --allowed-tools 'read_file,write_file,run_shell_command(ls)' --model '$m'"
      else
        echo "gemini --allowed-tools 'read_file,write_file,run_shell_command(ls)'"
      fi
      ;;
    codex)
      if [ -n "$m" ]; then
        echo "codex -a never --add-dir '$DEBATE_DIR' --model '$m'"
      else
        echo "codex -a never --add-dir '$DEBATE_DIR'"
      fi
      ;;
    claude)
      local dirs="--add-dir '$CWD'"
      [ -n "$REPO_ROOT" ] && [ "$REPO_ROOT" != "$CWD" ] && dirs="$dirs --add-dir '$REPO_ROOT'"
      [ "$HOME/.claude/plans" != "$CWD" ] && [ "$HOME/.claude/plans" != "$REPO_ROOT" ] && dirs="$dirs --add-dir '$HOME/.claude/plans'"
      echo "claude --settings '$SETTINGS_FILE' $dirs"
      ;;
  esac
}

# [PENDING]
agent_ready_marker() {
  case "$1" in
    gemini) echo "Type your message or @path/to/file" ;;
    codex)  echo "/model to change" ;;
    claude) echo "Claude Code v" ;;
  esac
}

# [PENDING]
agent_error_markers() {
  case "$1" in
    codex)  printf '%s\n' 'Selected model is at capacity' 'model is overloaded' ;;
    gemini) printf '%s\n' 'RESOURCE_EXHAUSTED' 'Quota exceeded' 'You exceeded your current quota' ;;
    claude) printf '%s\n' 'API Error: 529' 'overloaded_error' ;;
  esac
}

# [PENDING]
pane_has_capacity_error() {
  local pane_id="$1" agent="$2"
  local cap marker
  cap=$(hide_errors tmux capture-pane -t "$pane_id" -p -S -200 | tr -d '\033')
  while IFS= read -r marker; do
    [ -z "$marker" ] && continue
    if echo "$cap" | grep -qF "$marker"; then
      echo "$marker"
      return 0
    fi
  done < <(agent_error_markers "$agent")
  return 1
}

# [PENDING]
_next_model() {
  local agent="$1"
  local tried; tried=$(_lookup TRIED_MODELS "$agent")
  local models_json="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/assets/models.json"
  local m
  while IFS= read -r m; do
    [ -z "$m" ] && continue
    case ",$tried," in *,"$m",*) continue ;; esac
    echo "$m"
    return 0
  done < <(hide_errors jq -r --arg a "$agent" '.[$a][]?' "$models_json")
  return 1
}

# Moved above the launch/send/wait cluster (Phase 0.1) so callees precede callers.
# [PENDING]
write_failed() {
  local stage="$1" reason="$2"
  local tmpfile
  tmpfile=$(mktemp "$DEBATE_DIR/.FAILED.txt.XXXXXX") || return 1
  {
    printf '# debate FAILED\n\nstage: %s\nreason: %s\ntimestamp: %s\n\n' \
      "$stage" "$reason" "$(date -Iseconds)"
    printf '## missing agents\n'
    local agent lock pane_id
    for agent in ${AGENTS[@]+"${AGENTS[@]}"}; do
      [ -s "$DEBATE_DIR/${stage}_${agent}.md" ] && continue
      printf '\n### %s\n' "$agent"
      lock="$DEBATE_DIR/.${stage}_${agent}.lock"
      pane_id=$(sed -n 's|^debate:\(%[0-9]*\)$|\1|p' "$lock" 2>/dev/null)
      if [ -n "$pane_id" ]; then
        printf '```\n'
        hide_errors tmux capture-pane -t "$pane_id" -p -S -200 || printf '(pane capture unavailable)\n'
        printf '```\n'
      else
        printf '(no pane captured -- lock file missing or malformed)\n'
      fi
    done
  } > "$tmpfile"
  mv -f "$tmpfile" "$DEBATE_DIR/FAILED.txt"
}

# Moved above retry_pane_with_next_model and launch_agents_parallel (Phase 0.1)
# so callees precede callers. Note: wait_for_outputs is intentionally placed
# AFTER retry_pane_with_next_model below because it calls retry_pane_with_next_model;
# placing it above (per the literal plan instruction) would create a forward ref.
# [PENDING]
new_empty_pane() {
  hide_output tmux_retile "$WINDOW_TARGET"
  tmux_new_pane "$WINDOW_TARGET" -c "$CWD" -P -F '#{pane_id}'
}

# [PENDING]
launch_agent() {
  local pane_id="$1" stage="$2" agent="$3" launch_cmd="$4" ready_marker="$5"
  local timeout="${6:-120}"
  printf 'debate:%s\n' "$pane_id" > "$DEBATE_DIR/.${stage}_${agent}.lock"
  tmux_send_and_submit "$pane_id" "$launch_cmd"
  local elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    if hide_errors tmux capture-pane -t "$pane_id" -p -S -2000 \
         | tr -d '\033' | grep -qF "$ready_marker"; then
      echo "[orch] ${stage}/${agent} ready after ${elapsed}s (pane $pane_id)"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  echo "[orch] TIMEOUT: ${stage}/${agent} not ready within ${timeout}s" >&2
  write_failed "$stage" "launch_agent timeout for $agent after ${timeout}s"
  return 1
}

# [PENDING]
send_prompt() {
  local pane_id="$1" stage="$2" agent="$3" instructions="$4"
  tmux_send_and_submit "$pane_id" "read $instructions and perform them"
  local marker
  marker=$(basename "$instructions")
  local elapsed=0
  while [ "$elapsed" -lt 30 ]; do
    if hide_errors tmux capture-pane -t "$pane_id" -p -S -2000 \
         | tr -d '\033' | grep -qF "$marker"; then
      echo "[orch] ${stage}/${agent} prompt received after ${elapsed}s"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  echo "[orch] TIMEOUT: ${stage}/${agent} did not echo prompt" >&2
  write_failed "$stage" "send_prompt timeout for $agent after 30s"
  return 1
}

# [PENDING]
retry_pane_with_next_model() {
  local panes_var="$1" i="$2" agent="$3" stage="$4"
  local next
  if ! next=$(_next_model "$agent"); then
    echo "[orch] $stage/$agent: no remaining models; giving up" >&2
    return 1
  fi
  echo "[orch] $stage/$agent: capacity hit -- rotating to model '$next'"
  _stash CURRENT_MODEL "$agent" "$next"
  local tried; tried=$(_lookup TRIED_MODELS "$agent")
  _stash TRIED_MODELS "$agent" "${tried},${next}"
  local current_pane
  eval "current_pane=\${${panes_var}[$i]}"
  hide_errors tmux_kill_pane "$current_pane"
  local new_pane; new_pane=$(new_empty_pane)
  eval "${panes_var}[$i]=\"\$new_pane\""
  hide_output tmux_retile "$WINDOW_TARGET"
  sleep 1
  launch_agent "$new_pane" "$stage" "$agent" \
    "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" || return 1
  send_prompt  "$new_pane" "$stage" "$agent" \
    "$DEBATE_DIR/${stage}_instructions_${agent}.txt" || return 1
  return 0
}

# [PENDING]
wait_for_outputs() {
  local prefix="$1" timeout="$2" panes_var="$3"
  local reported=""
  local elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    local done_count=0
    local i agent pane_id
    for i in "${!AGENTS[@]}"; do
      agent="${AGENTS[$i]}"
      local out="$DEBATE_DIR/${prefix}_${agent}.md"
      if [ -s "$out" ]; then
        rm -f "$DEBATE_DIR/.${prefix}_${agent}.lock"
        done_count=$((done_count + 1))
        case " $reported " in
          *" $agent "*) ;;
          *) printf '\n[orch] %s: %s wrote %s (%ds)\n' "$prefix" "$agent" "$(basename "$out")" "$elapsed"
             reported="$reported $agent" ;;
        esac
        continue
      fi
      eval "pane_id=\${${panes_var}[$i]}"
      if pane_has_capacity_error "$pane_id" "$agent" >/dev/null; then
        retry_pane_with_next_model "$panes_var" "$i" "$agent" "$prefix" || true
      fi
      continue
    done
    if [ "$done_count" -eq "${#AGENTS[@]}" ]; then
      printf '[orch] %s: all %d outputs present after %ds\n' "$prefix" "${#AGENTS[@]}" "$elapsed"
      return 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
    printf '\r[orch] %s: %d/%d outputs (%ds/%ds)  ' "$prefix" "$done_count" "${#AGENTS[@]}" "$elapsed" "$timeout"
  done
  printf '\n[orch] TIMEOUT: %s outputs incomplete after %ds\n' "$prefix" "$timeout" >&2
  write_failed "$prefix" "wait_for_outputs timeout after ${timeout}s"
  return 1
}

# [PENDING]
launch_agents_parallel() {
  local stage="$1" panes_var="$2"
  local pids=() agents_run=() i agent pane_id fail=0
  local t0=$SECONDS
  for i in "${!AGENTS[@]}"; do
    agent="${AGENTS[$i]}"
    eval "pane_id=\${${panes_var}[$i]}"
    if [ -s "$DEBATE_DIR/${stage}_${agent}.md" ]; then
      echo "[orch] ${stage}/${agent} already complete, skipping launch"
      hide_errors tmux_kill_pane "$pane_id"
      continue
    fi
    if [ -f "$DEBATE_DIR/.${stage}_${agent}.lock" ]; then
      echo "[orch] ${stage}/${agent} lock held by live pane, skipping launch (wait_for_outputs will observe)"
      hide_errors tmux_kill_pane "$pane_id"
      continue
    fi
    (
      launch_agent "$pane_id" "$stage" "$agent" \
        "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" \
        || exit 1
      send_prompt "$pane_id" "$stage" "$agent" \
        "$DEBATE_DIR/${stage}_instructions_${agent}.txt" || exit 1
    ) &
    pids+=("$!")
    agents_run+=("$agent")
  done
  for i in "${!pids[@]}"; do
    if ! wait "${pids[$i]}"; then
      echo "[orch] ${stage}/${agents_run[$i]} worker exited non-zero" >&2
      fail=1
    fi
  done
  echo "[orch] launch_agents_parallel ${stage}: ${#pids[@]} workers, $((SECONDS - t0))s wall"
  return "$fail"
}

# [PENDING]
archive_debate() {
  echo "[orch] archiving intermediate files to $DEBATE_DIR/archive/"
  mkdir -p "$DEBATE_DIR/archive"
  local f
  for f in \
      "$DEBATE_DIR/context.md" \
      "$DEBATE_DIR/synthesis_instructions.txt" \
      "$DEBATE_DIR"/r1_instructions_*.txt \
      "$DEBATE_DIR"/r1_*.md \
      "$DEBATE_DIR"/r2_instructions_*.txt \
      "$DEBATE_DIR"/r2_*.md \
      ; do
    [ -f "$f" ] && mv "$f" "$DEBATE_DIR/archive/"
  done
  [ -f "$DEBATE_DIR/orchestrator.log" ] && mv "$DEBATE_DIR/orchestrator.log" "$DEBATE_DIR/archive/"
}

# [PENDING]
clean_stale_locks() {
  local stage="$1"
  local lock agent pane_id current
  for lock in "$DEBATE_DIR"/.${stage}_*.lock; do
    [ -f "$lock" ] || continue
    agent=$(basename "$lock" .lock)
    agent="${agent#.${stage}_}"
    pane_id=$(sed -n 's|^debate:\(%[0-9]*\)$|\1|p' "$lock")
    if [ -z "$pane_id" ]; then rm -f "$lock"; continue; fi
    if ! hide_errors tmux list-panes -t "$WINDOW_TARGET" -F '#{pane_id}' | grep -qFx "$pane_id"; then
      rm -f "$lock"; continue
    fi
    current=$(hide_errors tmux display-message -p -t "$pane_id" '#{pane_current_command}')
    if [ "$current" != "$agent" ]; then rm -f "$lock"; fi
  done
}

# [PENDING]
wait_for_file() {
  local path="$1" timeout="$2"
  local elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    if [ -s "$path" ]; then
      rm -f "$DEBATE_DIR/.synthesis_claude.lock"
      printf '\n[orch] %s present after %ds\n' "$(basename "$path")" "$elapsed"
      return 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
    printf '\r[orch] waiting for %s (%ds/%ds)  ' "$(basename "$path")" "$elapsed" "$timeout"
  done
  printf '\n[orch] TIMEOUT: %s never written after %ds\n' "$(basename "$path")" "$timeout" >&2
  write_failed synthesis "wait_for_file timeout after ${timeout}s ($(basename "$path") missing)"
  return 1
}

# [PENDING]
daemon_main() {
  echo "========================================"
  echo "[orch] DEBATE DAEMON"
  echo "[orch] Dir:     $DEBATE_DIR"
  echo "[orch] Session: $SESSION"
  echo "[orch] Window:  $WINDOW_TARGET"
  echo "[orch] Agents:  ${AGENTS[*]} (${#AGENTS[@]})"
  echo "[orch] Timeout: ${STAGE_TIMEOUT}s per stage"
  echo "[orch] Drift:   ${COMPOSITION_DRIFTED:-0}"
  echo "========================================"
  init_agent_models

  if [ "${COMPOSITION_DRIFTED:-0}" = 1 ]; then
    echo "[orch] composition drifted -- clearing r2_*.md, r2_instructions_*.txt, synthesis_instructions.txt"
    rm -f "$DEBATE_DIR"/r2_*.md "$DEBATE_DIR"/r2_instructions_*.txt
    rm -f "$DEBATE_DIR"/.r2_*.lock
    rm -f "$DEBATE_DIR/synthesis_instructions.txt"
  fi

  clean_stale_locks r1
  R1_PANES=()
  local agent _a i
  for agent in "${AGENTS[@]}"; do
    R1_PANES+=("$(new_empty_pane)")
  done
  hide_output tmux_retile "$WINDOW_TARGET"
  echo "[orch] R1 panes: agents=[${AGENTS[*]}]=[${R1_PANES[*]}]"
  sleep 1
  launch_agents_parallel r1 R1_PANES || exit 1

  wait_for_outputs r1 "$STAGE_TIMEOUT" R1_PANES || exit 1

  for i in "${!AGENTS[@]}"; do
    hide_errors tmux_kill_pane "${R1_PANES[$i]}"
  done
  hide_output tmux_retile "$WINDOW_TARGET"
  echo "[orch] R1 agent panes closed"

  clean_stale_locks r2
  for _a in "${AGENTS[@]}"; do
    [ -f "$DEBATE_DIR/r2_instructions_${_a}.txt" ] && continue
    DEBATE_AGENTS="${AGENTS[*]}" AGENT_FILTER="$_a" \
      debate_build_prompts r2 "$DEBATE_DIR" "$PLUGIN_ROOT"
  done

  R2_PANES=()
  for agent in "${AGENTS[@]}"; do
    R2_PANES+=("$(new_empty_pane)")
  done
  hide_output tmux_retile "$WINDOW_TARGET"
  echo "[orch] R2 panes: agents=[${AGENTS[*]}]=[${R2_PANES[*]}]"
  sleep 1
  launch_agents_parallel r2 R2_PANES || exit 1

  wait_for_outputs r2 "$STAGE_TIMEOUT" R2_PANES || exit 1

  for i in "${!AGENTS[@]}"; do
    hide_errors tmux_kill_pane "${R2_PANES[$i]}"
  done
  hide_output tmux_retile "$WINDOW_TARGET"
  echo "[orch] R2 agent panes closed"

  if [ -s "$DEBATE_DIR/synthesis.md" ]; then
    echo "[orch] synthesis already complete, skipping launch; running archive step"
    archive_debate
    echo "[orch] DEBATE COMPLETE -- synthesis at $DEBATE_DIR/synthesis.md"
    exit 0
  fi

  clean_stale_locks synthesis
  if [ ! -f "$DEBATE_DIR/synthesis_instructions.txt" ]; then
    DEBATE_AGENTS="${AGENTS[*]}" debate_build_prompts synthesis "$DEBATE_DIR" "$PLUGIN_ROOT"
  fi

  SYNTH_PANE=$(new_empty_pane)
  hide_output tmux_retile "$WINDOW_TARGET"
  echo "[orch] synthesis pane: $SYNTH_PANE"
  sleep 1
  launch_agent "$SYNTH_PANE" synthesis claude "$(agent_launch_cmd claude)" "$(agent_ready_marker claude)" || exit 1
  send_prompt  "$SYNTH_PANE" synthesis claude "$DEBATE_DIR/synthesis_instructions.txt" || exit 1

  wait_for_file "$DEBATE_DIR/synthesis.md" "$STAGE_TIMEOUT" || exit 1

  hide_errors tmux_kill_pane "$SYNTH_PANE"
  hide_output tmux_retile "$WINDOW_TARGET"
  echo "[orch] synthesis pane closed"

  archive_debate
  echo "[orch] DEBATE COMPLETE -- synthesis at $DEBATE_DIR/synthesis.md"
}

# Entry-point function: argv-dispatch routes "debate-tmux-orchestrator" here.
# Positional: DEBATE_DIR SESSION WINDOW_NAME SETTINGS_FILE CWD REPO_ROOT PLUGIN_ROOT
# Env (caller-set): DEBATE_AGENTS, GEMINI_MODEL, CODEX_MODEL, COMPOSITION_DRIFTED
# [PENDING]
debate_tmux_orchestrator() {
  DEBATE_DIR="$1"
  SESSION="$2"
  WINDOW_NAME="$3"
  SETTINGS_FILE="$4"
  CWD="$5"
  REPO_ROOT="$6"
  PLUGIN_ROOT="$7"
  : "${SESSION:?SESSION required}"
  WINDOW_TARGET="${SESSION}:${WINDOW_NAME}"
  STAGE_TIMEOUT=$((15 * 60))
  : "${DEBATE_AGENTS:?DEBATE_AGENTS env var required}"
  IFS=' ' read -r -a AGENTS <<< "$DEBATE_AGENTS"
  trap cleanup EXIT
  daemon_main
}
#### end debate-tmux-orchestrator.sh ####

#### debate-orchestrator.sh ####

# [PENDING]
debate_launch() {
    SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PLUGIN_ROOT="$(cd "$SCRIPTS_DIR/../../.." && pwd)"

    # . "$PLUGIN_ROOT/common/scripts/silencers.sh"

    # Ensure Terminal.app is running as a process so spawn_terminal_if_needed's
    # `do script` can land in a single tmux-attach window. `launch` (not
    # `activate`) starts Terminal without opening a default shell window —
    # avoiding a duplicate empty window beside the real one. Darwin-only; no-op
    # if Terminal is already running.
    if [[ "${OSTYPE:-}" == darwin* ]] && ! hide_errors pgrep -q Terminal; then
        hide_output hide_errors osascript -e 'tell application "Terminal" to launch' &
    fi

    # shellcheck source=debate.sh
    # . "$SCRIPTS_DIR/debate.sh"

    debate_main
}
#### end debate-orchestrator.sh ####

#### todo.sh #### 
#!/bin/bash
# todo.sh — function definitions for the /todo hook.
# Sourced by todo-orchestrator.sh. No side effects when sourced.
#
# The /todo hook writes Todos/.todo-state/pending-XXXXXX.json and
# exits 0 silently so the foreground Claude can dispatch the `todo` skill
# body (which may ask clarification questions via AskUserQuestion).

# [PENDING]
todo_main() {
  : "${CLAUDE_PLUGIN_DATA:?todo plugin env not set}"

  local REPO
  REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  export CLAUDE_PLUGIN_ROOT="$REPO"

  local SCRIPTS_DIR="$REPO/skills/todo/scripts"
  LOG_FILE="${TODO_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/todo-log.txt}"

#   . "$REPO/common/scripts/silencers.sh"
#   . "$REPO/common/scripts/hook-json.sh"
#   . "$REPO/common/scripts/git.sh"
  hide_errors mkdir -p "$(dirname "$LOG_FILE")"

  INPUT=$(cat)
  case "$INPUT" in
    *'"/todo'*) ;;
    *) exit 0 ;;
  esac

  hide_errors printf '%s HOOK_INPUT %s\n' "$(date -Iseconds)" "$INPUT" >> "$LOG_FILE"
  check_requirements "todo" jq python3 tmux claude

  PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""' | \
           python3 "$REPO/common/scripts/jot/strip_stdin.py")
  if [[ "$PROMPT" != "/todo" && "$PROMPT" != "/todo "* ]]; then
    exit 0
  fi

  IDEA="${PROMPT#/todo}"; IDEA="${IDEA# }"
  SESSION_ID=$(printf '%s' "$INPUT" | hide_errors jq -r '.session_id // "unknown"') || SESSION_ID="unknown"
  TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | hide_errors jq -r '.transcript_path // empty')
  CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
  [ -z "$CWD" ] && CWD="$PWD"

  REPO_ROOT=$(hide_errors git_get_repo_root "$CWD") || REPO_ROOT=""
  if [ -z "$REPO_ROOT" ]; then
    emit_block "todo requires a git repository. Run 'git init' in your project root."
    exit 0
  fi

  STATE_DIR="$REPO_ROOT/Todos/.todo-state"
  mkdir -p "$STATE_DIR"
  TIMESTAMP=$(date +%Y-%m-%dT%H-%M-%S)

  # Atomic, per-invocation-unique pending filename. BSD mktemp requires the
  # X's to be trailing, so we generate a unique base via `mktemp -u`, append
  # `.json`, and atomically claim the path with `set -C` (noclobber).
  local PENDING_BASE PENDING_FILE
  while :; do
    PENDING_BASE=$(mktemp -u "$STATE_DIR/pending-XXXXXX")
    PENDING_FILE="${PENDING_BASE}.json"
    if ( set -C; : > "$PENDING_FILE" ) 2>/dev/null; then
      break
    fi
  done

  IDEA_JSON=$(printf '%s' "$IDEA" | \
              python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')

  cat > "$PENDING_FILE" <<JSON
{
  "session_id": "$SESSION_ID",
  "transcript_path": "$TRANSCRIPT_PATH",
  "cwd": "$CWD",
  "repo_root": "$REPO_ROOT",
  "idea": $IDEA_JSON,
  "timestamp": "$TIMESTAMP",
  "todo_plugin_root": "$REPO",
  "todo_scripts_dir": "$SCRIPTS_DIR",
  "pending_file": "$PENDING_FILE",
  "created_at": "$(date -Iseconds)"
}
JSON

  # Silent exit — no emit_block so the fg claude dispatches the `todo` skill.
  exit 0
}

#### end todo.sh ####

#### todo-list.sh ####
#!/bin/bash
# todo-list.sh — function definitions for the /todo-list hook.
# Sourced by todo-list-orchestrator.sh. No side effects when sourced.
#
# Synchronously reads YAML frontmatter from all open TODOs under Todos/
# (excluding Todos/done/) and emits a formatted block via emit_block.

# [PENDING]
todo_list_main() {
  local REPO
  REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  export CLAUDE_PLUGIN_ROOT="$REPO"

#   . "$REPO/common/scripts/silencers.sh"
#   . "$REPO/common/scripts/hook-json.sh"
#   . "$REPO/common/scripts/git.sh"

  local INPUT
  INPUT=$(cat)
  case "$INPUT" in
    *'"/todo-list'*) ;;
    *) exit 0 ;;
  esac

  check_requirements "todo-list" jq python3

  local PROMPT
  PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""' | \
           python3 "$REPO/common/scripts/jot/strip_stdin.py")
  if [[ "$PROMPT" != "/todo-list" && "$PROMPT" != "/todo-list "* ]]; then
    exit 0
  fi

  local CWD
  CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
  [ -z "$CWD" ] && CWD="$PWD"

  local REPO_ROOT
  REPO_ROOT=$(hide_errors git_get_repo_root "$CWD") || REPO_ROOT=""
  if [ -z "$REPO_ROOT" ]; then
    emit_block "todo-list: not a git repository."
    exit 0
  fi

  if [ ! -d "$REPO_ROOT/Todos" ]; then
    emit_block "No Todos/ folder found in this project."
    exit 0
  fi

  local FORMATTED
  FORMATTED=$(TODOS_DIR="$REPO_ROOT/Todos" \
              python3 "$REPO/skills/todo-list/scripts/format_open_todos.py")

  if [ -z "$FORMATTED" ]; then
    emit_block "No open TODOs."
  else
    emit_block "$FORMATTED"
  fi
  exit 0
}

#### end todo-list.sh ####
#### jot-session-start.sh 
# [PENDING]
jot_session_start() {
    INPUT_FILE="${1:-}"
    TMPDIR_INV="${2:-}"

    if [ -z "$INPUT_FILE" ] || [ -z "$TMPDIR_INV" ]; then
        echo "[jot-session-start] missing args (input_file, tmpdir_inv)" >&2
        exit 0
    fi

    # Read the tmux pane id sidecar written atomically by phase2_launch_window
    # immediately after `tmux split-window` returned. The retry loop is a
    # belt-and-suspenders guard: in practice the sidecar is always present by
    # the time claude's SessionStart fires (claude takes ~1-2s to boot, the
    # sidecar is written in microseconds after split-window).
    TARGET_FILE="$TMPDIR_INV/tmux_target"
    TMUX_TARGET=""
    for _ in 1 2 3 4 5; do
    if [ -s "$TARGET_FILE" ]; then
        TMUX_TARGET=$(head -1 "$TARGET_FILE")
        [ -n "$TMUX_TARGET" ] && break
    fi
    sleep 0.2
    done

    if [ -z "$TMUX_TARGET" ]; then
        echo "[jot-session-start] tmux_target sidecar empty after retries" >&2
        exit 0
    fi

    # shellcheck source=tmux.sh
    # . "$(dirname "$0")/tmux.sh"
    # shellcheck source=tmux-launcher.sh
    # . "$(dirname "$0")/tmux-launcher.sh"

    # Wait for claude's TUI to show the input prompt before sending keys.
    if ! tmux_wait_for_claude_readiness "$TMUX_TARGET"; then
        echo "[jot-session-start] claude TUI not ready, aborting send" >&2
        exit 1
    fi

    tmux_send_and_submit "$TMUX_TARGET" \
    "Read $INPUT_FILE and follow the instructions at the top of that file"

    exit 0
}
#### end jot-session-start.sh

#### jot-session-end.sh ####
# [PENDING]
jot_session_end() {

    TMPDIR_INV="${1:-}"

    # Safety guard: refuse to rm anything not matching the expected pattern.
    # Without this a misconfigured hook could wipe an arbitrary path.
    case "$TMPDIR_INV" in
    /tmp/jot.*|/private/tmp/jot.*) ;;
    *)
        echo "[jot-session-end] refusing to rm unexpected path: $TMPDIR_INV" >&2
        exit 0
        ;;
    esac

    rm -rf "$TMPDIR_INV"
    exit 0
}
#### end jot-session-end.sh ####

#### jot-stop.sh ####
# [MIGRATED -> jot_stop @ 2026-05-04]
jot_stop(){
    # jot-stop.sh — Stop hook for per-invocation claude panes.
    #
    # Fires when claude finishes responding to its one job. Reads the tmux
    # pane id from "$TMPDIR_INV/tmux_target", verifies the PROCESSED: marker
    # was written, appends SUCCESS/FAIL to audit.log, rotates the log, then
    # kills THIS pane asynchronously (which terminates this claude process,
    # triggers SessionEnd, and wipes $TMPDIR_INV).
    #
    # IMPORTANT ordering contract: the sidecar MUST be read synchronously
    # into $TMUX_TARGET BEFORE the backgrounded kill-pane subshell is
    # forked. SessionEnd fires AFTER Stop returns and wipes $TMPDIR_INV
    # (sidecar included), but the already-forked subshell holds the pane id
    # in memory so the wipe is safe. Do NOT move the sidecar read into the
    # subshell.
    #
    # Key contract: this claude instance processes exactly ONE /jot and exits.
    # No /clear, no queue drain, no shared state with other jots.
    #
    # Args:
    #   $1 = absolute path to the input.txt this claude was told to process
    #   $2 = absolute path to the per-invocation tmpdir (e.g. /tmp/jot.abcXYZ)
    #   $3 = state_dir (for audit.log; e.g. "$REPO_ROOT/Todos/.jot-state")
    
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    # shellcheck source=jot-state-lib.sh
    # . "$SCRIPT_DIR/jot-state-lib.sh"
    # . "${CLAUDE_PLUGIN_ROOT}/common/scripts/silencers.sh"
    # invoke_command.sh and tmux.sh are already sourced by jot-state-lib.sh

    INPUT_FILE="${1:-}"
    TMPDIR_INV="${2:-}"
    STATE_DIR="${3:-}"

    if [ -z "$INPUT_FILE" ] || [ -z "$TMPDIR_INV" ] || [ -z "$STATE_DIR" ]; then
        echo "[jot-stop] missing args (input_file, tmpdir_inv, state_dir)" >&2
        exit 0
    fi

    # Read the tmux pane id sidecar SYNCHRONOUSLY into $TMUX_TARGET NOW,
    # before anything else. The backgrounded kill-pane subshell below captures
    # this variable in memory, so SessionEnd's subsequent wipe of $TMPDIR_INV
    # cannot break it. See the "IMPORTANT ordering contract" note in the file
    # header for why this order matters.
    TARGET_FILE="$TMPDIR_INV/tmux_target"
    TMUX_TARGET=""
    for _ in 1 2 3 4 5; do
        if [ -s "$TARGET_FILE" ]; then
            TMUX_TARGET=$(head -1 "$TARGET_FILE")
            [ -n "$TMUX_TARGET" ] && break
        fi
        sleep 0.2
    done

    if [ -z "$TMUX_TARGET" ]; then
        echo "[jot-stop] tmux_target sidecar empty after retries" >&2
        exit 0
    fi

    jot_state_init "$STATE_DIR"

    AUDIT="$STATE_DIR/audit.log"

    # Definitive success check: PROCESSED: marker on head -1 of input.txt.
    ts=$(date -Iseconds)
    if [ -f "$INPUT_FILE" ]; then
        first_line=$(head -1 "$INPUT_FILE")
        if [[ "$first_line" == PROCESSED:* ]]; then
            printf '%s SUCCESS %s\n' "$ts" "$INPUT_FILE" >> "$AUDIT"
        else
            printf '%s FAIL %s (no PROCESSED marker)\n' "$ts" "$INPUT_FILE" >> "$AUDIT"
        fi
    else
        printf '%s FAIL %s (input.txt missing)\n' "$ts" "$INPUT_FILE" >> "$AUDIT"
    fi

    jot_audit_rotate "$AUDIT" 1000

    # Kill this pane in the background so the hook exits cleanly BEFORE tmux
    # signals the claude process. The short sleep lets jot-stop.sh return to
    # claude, claude acknowledges the hook completion, THEN tmux kill-pane
    # takes effect. The chained `select-layout tiled` re-tiles the surviving
    # panes (keepalive + any other in-flight workers) into a fresh NxM grid
    # so the dashboard layout stays balanced after each completion.
    #
    # NOTE: $TMUX_TARGET was read synchronously above from the sidecar file,
    # BEFORE this fork. The subshell below holds the pane id in memory; by
    # the time SessionEnd wipes $TMPDIR_INV the subshell no longer needs
    # the file. Do NOT move the sidecar read into this subshell.
    ( sleep 0.5
    hide_output hide_errors tmux_kill_pane "$TMUX_TARGET"
    hide_output hide_errors tmux_retile "jot:jots"
    ) &
    hide_errors disown

    exit 0

}

#### end jot-stop.sh ####

#### todo-launcher.sh ####
# [PENDING]
todo_launcher() {
    SESSION_ID="${1:?session_id required}"
    IDEA="${2:?refined idea required}"
    PENDING_FILE="${3:?pending_file path required}"

    SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PLUGIN_ROOT="$(cd "$SCRIPTS_DIR/../../.." && pwd)"
    export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"
    : "${CLAUDE_PLUGIN_DATA:=$HOME/.claude/plugins/data/jot-matkatmusic-jot}"
    export CLAUDE_PLUGIN_DATA
    mkdir -p "$CLAUDE_PLUGIN_DATA"

    # . "$PLUGIN_ROOT/common/scripts/silencers.sh"
    # . "$PLUGIN_ROOT/common/scripts/hook-json.sh"
    # . "$PLUGIN_ROOT/common/scripts/tmux.sh"
    # . "$PLUGIN_ROOT/common/scripts/tmux-launcher.sh"
    # . "$PLUGIN_ROOT/common/scripts/claude-launcher.sh"
    # . "$PLUGIN_ROOT/common/scripts/permissions-seed.sh"
    # . "$PLUGIN_ROOT/common/scripts/platform.sh"
    # . "$PLUGIN_ROOT/common/scripts/lock.sh"
    # . "$PLUGIN_ROOT/common/scripts/git.sh"
    # . "$SCRIPTS_DIR/todo-state-lib.sh"

    LOG_FILE="${TODO_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/todo-log.txt}"
    hide_errors mkdir -p "$(dirname "$LOG_FILE")"

    if [ ! -f "$PENDING_FILE" ]; then
    echo "todo-launcher: pending file not found at $PENDING_FILE" >&2
    exit 1
    fi

    REPO_ROOT=$(jq -r '.repo_root' "$PENDING_FILE")
    CWD=$(jq -r '.cwd' "$PENDING_FILE")
    TRANSCRIPT_PATH=$(jq -r '.transcript_path // empty' "$PENDING_FILE")
    TIMESTAMP=$(jq -r '.timestamp' "$PENDING_FILE")

    STATE_DIR="$REPO_ROOT/Todos/.todo-state"
    todo_state_init "$STATE_DIR"

    # ── Phase 1: write input.txt (durable-first) ─────────────────────────────
    TARGET_DIR="$REPO_ROOT/Todos"
    mkdir -p "$TARGET_DIR"
    INPUT_FILE="$TARGET_DIR/${TIMESTAMP}_input.txt"
    INPUT_ABS="$INPUT_FILE"

    BRANCH=$(hide_errors git_get_branch_name "$CWD") || BRANCH="(unavailable)"
    COMMITS=$(hide_errors git_get_recent_commits "$CWD") || COMMITS="(unavailable)"
    UNCOMMITTED=$(hide_errors git_get_uncommitted "$CWD") || UNCOMMITTED="(unavailable)"
    OPEN_TODOS=$(hide_errors scan_open_todos "$REPO_ROOT") || OPEN_TODOS="(unavailable)"

    if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
    CONVERSATION=$(hide_errors python3 \
        "$PLUGIN_ROOT/skills/jot/scripts/capture-conversation.py" "$TRANSCRIPT_PATH") \
        || CONVERSATION="(unavailable)"
    else
    CONVERSATION="No conversation history available."
    fi

    INSTRUCTIONS=$(REPO_ROOT="$REPO_ROOT" TIMESTAMP="$TIMESTAMP" BRANCH="$BRANCH" \
    INPUT_ABS="$INPUT_ABS" \
    python3 "$PLUGIN_ROOT/common/scripts/jot/render_template.py" \
        "$SCRIPTS_DIR/assets/todo-instructions.md" \
        REPO_ROOT TIMESTAMP BRANCH INPUT_ABS)

    {
    printf '# Todo Task\n\n## Instructions\n%s\n\n' "$INSTRUCTIONS"
    printf '## Idea\n%s\n\n' "$IDEA"
    printf '## Working Directory\n%s\n\n' "$CWD"
    printf '## Git State\n- Branch: %s\n- Commits: %s\n- Uncommitted: %s\n\n' \
        "$BRANCH" "$COMMITS" "$UNCOMMITTED"
    printf '## Open TODO Files\n%s\n\n' "$OPEN_TODOS"
    printf '## Transcript Path\n%s\n\n' "${TRANSCRIPT_PATH:-(none)}"
    printf '## Recent Conversation\n%s\n\n' "$CONVERSATION"
    } > "$INPUT_FILE"

    # ── Phase 2: build the per-invocation claude command ──────────────────────
    TMPDIR_INV=$(mktemp -d /tmp/todo.XXXXXX)
    SETTINGS_FILE="$TMPDIR_INV/settings.json"

    cp "$PLUGIN_ROOT/scripts/jot-plugin-orchestrator.sh" "$TMPDIR_INV/jot-plugin-orchestrator.sh"

    permissions_file="${CLAUDE_PLUGIN_DATA}/todo-permissions.local.json"
    default_file="$SCRIPTS_DIR/assets/permissions.default.json"
    default_sha_file="$SCRIPTS_DIR/assets/permissions.default.json.sha256"
    prior_sha_file="${CLAUDE_PLUGIN_DATA}/todo-permissions.default.sha256"
    permissions_seed "$permissions_file" "$default_file" "$default_sha_file" \
                    "$prior_sha_file" "$LOG_FILE" "todo"

    allow_json=$(CWD="$CWD" HOME="$HOME" REPO_ROOT="$REPO_ROOT" \
    python3 "$PLUGIN_ROOT/common/scripts/jot/expand_permissions.py" "$permissions_file")

    hooks_json_file="$TMPDIR_INV/hooks.json"
    cat > "$hooks_json_file" <<JSON
{
    "SessionStart": [{"hooks": [{"type": "command", "command": "bash $TMPDIR_INV/jot-plugin-orchestrator.sh todo-session-start '$INPUT_FILE' '$TMPDIR_INV'"}]}],
    "Stop":         [{"hooks": [{"type": "command", "command": "bash $TMPDIR_INV/jot-plugin-orchestrator.sh todo-stop '$INPUT_FILE' '$TMPDIR_INV' '$STATE_DIR'"}]}],
    "SessionEnd":   [{"hooks": [{"type": "command", "command": "bash $TMPDIR_INV/jot-plugin-orchestrator.sh todo-session-end '$TMPDIR_INV'"}]}]
}
JSON

    CLAUDE_CMD=$(build_claude_cmd "$SETTINGS_FILE" "$allow_json" "$hooks_json_file" "$CWD" "$REPO_ROOT")

    # ── Phase 3: launch the tmux pane ─────────────────────────────────────────
    tmux_lock="${CLAUDE_PLUGIN_DATA}/todo-tmux-launch.lock"
    if ! lock_acquire "$tmux_lock" 10; then
        echo "todo-launcher: failed to acquire tmux-launch lock" >&2
        exit 1
    fi
    trap 'lock_release "$tmux_lock"' EXIT

    counter_file="${CLAUDE_PLUGIN_DATA}/todo-pane-counter.txt"
    n=$(hide_errors cat "$counter_file") || n=0
    n=$(( n % 20 + 1 ))
    printf '%s\n' "$n" > "$counter_file"
    pane_label="todo${n}"

    keepalive_cmd='exec sh -c '\''trap "" INT HUP TERM; printf "[todo keepalive — do not kill]\n"; exec tail -f /dev/null'\'''
    tmux_ensure_session todo todos "$CWD" "$keepalive_cmd" 'todo: keepalive'

    if ! PANE_ID=$(tmux_split_worker_pane todo:todos "$CWD" "$CLAUDE_CMD"); then
        echo "todo-launcher: tmux split-window returned empty pane id" >&2
        exit 1
    fi

    printf '%s\n' "$PANE_ID" > "$TMPDIR_INV/tmux_target.tmp"
    mv "$TMPDIR_INV/tmux_target.tmp" "$TMPDIR_INV/tmux_target"

    tmux_set_pane_title "$PANE_ID" "$pane_label"
    tmux_retile todo:todos

    spawn_terminal_if_needed "todo" "$LOG_FILE" "todo"

    # Delete the pending-context sidecar now that the worker has been handed off.
    # Failure here is cosmetic (sidecar accumulates harmlessly), so log and continue.
    hide_errors rm -f "$PENDING_FILE" || \
    hide_errors printf '%s todo-launcher: failed to rm pending_file=%s\n' \
        "$(date -Iseconds)" "$PENDING_FILE" >> "$LOG_FILE"

    printf '%s\n' "$INPUT_ABS"
}

#### end todo-launcher.sh ####

#### todo-stop.sh ####
# [PENDING]
todo_stop() {
    # SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    # . "$SCRIPT_DIR/tmux.sh"
    # . "$SCRIPT_DIR/invoke_command.sh"
    # . "$SCRIPT_DIR/silencers.sh"

    INPUT_FILE="${1:-}"
    TMPDIR_INV="${2:-}"
    STATE_DIR="${3:-}"

    if [ -z "$INPUT_FILE" ] || [ -z "$TMPDIR_INV" ] || [ -z "$STATE_DIR" ]; then
        echo "[todo-stop] missing args (input_file, tmpdir_inv, state_dir)" >&2
        exit 0
    fi

    TARGET_FILE="$TMPDIR_INV/tmux_target"
    TMUX_TARGET=""
    for _ in 1 2 3 4 5; do
        if [ -s "$TARGET_FILE" ]; then
            TMUX_TARGET=$(head -1 "$TARGET_FILE")
            [ -n "$TMUX_TARGET" ] && break
        fi
        sleep 0.2
    done

    if [ -z "$TMUX_TARGET" ]; then
        echo "[todo-stop] tmux_target sidecar empty after retries" >&2
        exit 0
    fi

    mkdir -p "$STATE_DIR"
    AUDIT="$STATE_DIR/audit.log"

    ts=$(date -Iseconds)
    if [ -f "$INPUT_FILE" ]; then
        first_line=$(head -1 "$INPUT_FILE")
        if [[ "$first_line" == PROCESSED:* ]]; then
            printf '%s SUCCESS %s\n' "$ts" "$INPUT_FILE" >> "$AUDIT"
            rm -f "$INPUT_FILE"
        else
            printf '%s FAIL %s (no PROCESSED marker)\n' "$ts" "$INPUT_FILE" >> "$AUDIT"
        fi
    else
        printf '%s FAIL %s (input.txt missing)\n' "$ts" "$INPUT_FILE" >> "$AUDIT"
    fi

    lines=$(wc -l < "$AUDIT" | tr -d ' ')
    if [ "${lines:-0}" -gt 1000 ]; then
        tail -1000 "$AUDIT" > "$AUDIT.trim" && mv "$AUDIT.trim" "$AUDIT"
    fi

    ( sleep 0.5
    hide_output hide_errors tmux_kill_pane "$TMUX_TARGET"
    hide_output hide_errors tmux_retile "todo:todos"
    ) &
    hide_errors disown

    exit 0
}

#### end todo-stop.sh ####

#### todo-session-start.sh ####
# [PENDING]
todo_session_start() {
    # todo-session-start.sh — SessionStart hook for per-invocation claude panes.
    # Fires once when claude starts in a fresh tmux pane. Reads the pane id from
    # "$TMPDIR_INV/tmux_target" (written by todo-launcher.sh), then sends the
    # initial "Read <input.txt> and follow the instructions" prompt.
    #
    # Args: $1 = absolute path to the input.txt for THIS /todo invocation
    #       $2 = absolute path to the per-invocation tmpdir (/tmp/todo.XXXXXX)
    set -uo pipefail

    INPUT_FILE="${1:-}"
    TMPDIR_INV="${2:-}"

    if [ -z "$INPUT_FILE" ] || [ -z "$TMPDIR_INV" ]; then
        echo "[todo-session-start] missing args (input_file, tmpdir_inv)" >&2
        exit 0
    fi

    TARGET_FILE="$TMPDIR_INV/tmux_target"
    TMUX_TARGET=""
    for _ in 1 2 3 4 5; do
        if [ -s "$TARGET_FILE" ]; then
            TMUX_TARGET=$(head -1 "$TARGET_FILE")
            [ -n "$TMUX_TARGET" ] && break
        fi
        sleep 0.2
    done

    if [ -z "$TMUX_TARGET" ]; then
        echo "[todo-session-start] tmux_target sidecar empty after retries" >&2
        exit 0
    fi

    # shellcheck source=tmux.sh
    # . "$(dirname "$0")/tmux.sh"
    # shellcheck source=tmux-launcher.sh
    # . "$(dirname "$0")/tmux-launcher.sh"

    if ! tmux_wait_for_claude_readiness "$TMUX_TARGET"; then
        echo "[todo-session-start] claude TUI not ready, aborting send" >&2
        exit 1
    fi

    tmux_send_and_submit "$TMUX_TARGET" \
    "Read $INPUT_FILE and follow the instructions at the top of that file"

    exit 0
}
#### end todo-session-start.sh ####

#### todo-session-end.sh ####
# [PENDING]
todo_session_end() {
# todo-session-end.sh — SessionEnd hook for per-invocation claude panes.
# Wipes the per-invocation /tmp/todo.XXXXXX directory that held this
# claude's settings.json and copied-in helper scripts.
#
# Args: $1 = absolute path to the temp dir

    TMPDIR_INV="${1:-}"

    case "$TMPDIR_INV" in
    /tmp/todo.*|/private/tmp/todo.*) ;;
    *)
        echo "[todo-session-end] refusing to rm unexpected path: $TMPDIR_INV" >&2
        exit 0
        ;;
    esac

    rm -rf "$TMPDIR_INV"
    exit 0

}

#### end todo-session-end.sh ####

#### plate-summary-stop.sh ####
# [PENDING]
plate_summary_stop() {
    # plate-summary-stop.sh — per-invocation SessionEnd hook for the
    # spawned summary agent. Reads the agent's output file and forwards it
    # to `cli.py set-plate-summary` which runs the trailer-rewrite via
    # rebase-reword.
    #
    # Args:
    #   $1 = repo (absolute path)
    #   $2 = branch (the parent branch; plate branch is <branch>-plate)
    #   $3 = output_file (path the agent wrote its summary to)
    #
    # Always exit 0 so a failure here can never block session shutdown.
    set -uo pipefail

    REPO="${1:-}"
    BRANCH="${2:-}"
    OUTPUT_FILE="${3:-}"

    [ -z "$REPO" ] || [ -z "$BRANCH" ] || [ -z "$OUTPUT_FILE" ] && exit 0
    [ -f "$OUTPUT_FILE" ] || exit 0

    REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
    CLI_PATH="$REPO_ROOT/common/scripts/plate/cli.py"

    if [ -n "${PLATE_LOG_FILE:-}" ]; then
        LOG_FILE="$PLATE_LOG_FILE"
    elif [ -d "$REPO" ]; then
        LOG_FILE="$REPO/.plate/plate-log.txt"
    else
        LOG_FILE="${CLAUDE_PLUGIN_DATA:-$HOME/.claude/plugins/data/plate-jot-dev}/plate-log.txt"
    fi
    mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

    OUT=$(python3 "$CLI_PATH" set-plate-summary "$REPO" "$BRANCH" "$OUTPUT_FILE" 2>&1) || true
    printf '%s plate-summary-stop repo=%s branch=%s out=%s\n' \
    "$(date -Iseconds)" "$REPO" "$BRANCH" "$OUT" >> "$LOG_FILE" 2>/dev/null || true

    exit 0

}
#### end plate-summary-stop.sh ####

#### plate-summary-watch.sh ####
# [PENDING]
plate_summary_watch() {
    # plate-summary-watch.sh — fire-and-forget watchdog for the spawned
    # plate-summary agent. Polls the agent's output file; when it appears
    # and is non-empty, sends `/exit\n` to the agent's tmux pane to trigger
    # a graceful shutdown. The agent's per-invocation SessionEnd hook
    # (plate-summary-stop.sh) fires after that and runs the trailer-rewrite.
    #
    # Why a watcher and not a Stop hook on the agent's settings.json:
    # Claude Code's `decision:"block"` for Stop means "BLOCK the stop, force
    # agent to continue" — opposite of PreToolUse semantics. A Stop hook
    # can't terminate the agent, only prevent termination. Killing the pane
    # from the OUTSIDE (this script) is the working pattern, mirrored on
    # `/debate`'s `wait_for_outputs` → `tmux_kill_pane` flow in
    # skills/debate/scripts/debate-tmux-orchestrator.sh.
    #
    # Atomicity invariant (same as debate's `wait_for_outputs`): assumes the
    # agent writes the output via Claude's Write tool, which is atomic
    # temp-then-rename. Streaming writes would race against `[ -s ... ]`
    # and trigger a mid-write kill.
    #
    # Usage:
    #   plate-summary-watch.sh <pane_target> <output_file>
    #     <pane_target>   tmux session:window form, e.g.
    #                     plate-summary-7:plate-summary-abc12345
    #     <output_file>   absolute path the agent writes its summary to
    # Env knobs (rarely needed):
    #   PLATE_SUMMARY_WATCH_TIMEOUT  seconds before giving up (default 600)
    #   PLATE_SUMMARY_WATCH_INTERVAL seconds between polls   (default 2)
    set -uo pipefail

    PANE="${1:?pane target required}"
    OUTPUT_FILE="${2:?output file required}"
    TIMEOUT="${PLATE_SUMMARY_WATCH_TIMEOUT:-600}"
    INTERVAL="${PLATE_SUMMARY_WATCH_INTERVAL:-2}"

    elapsed=0
    while [ "$elapsed" -lt "$TIMEOUT" ]; do
        if [ -s "$OUTPUT_FILE" ]; then
            # `/exit` is Claude TUI's graceful-shutdown command. Two send-keys
            # calls: the first inserts the literal text into the prompt buffer,
            # the second submits with Enter. Errors from send-keys are silenced
            # — if the pane has already gone away (user attached + closed), we
            # just exit successfully.
            tmux send-keys -t "$PANE" "/exit" 2>/dev/null || true
            tmux send-keys -t "$PANE" Enter 2>/dev/null || true
            exit 0
        fi
        sleep "$INTERVAL"
        elapsed=$((elapsed + INTERVAL))
    done

    # Timeout: leave the pane alive so the user can investigate. SessionEnd
    # won't fire until the user closes it manually, which is the safer
    # default than masking a real failure with a hard pane kill.
    exit 1
}
#### end plate-summary-watch.sh ####

# ─── inlined from skills/jot/tests/jot-diag-collect.sh ───
# Operator-invoked post-mortem collector for a /jot run. Writes a single
# diagnostic report file. Invoke via:
#   bash scripts/jot-plugin-orchestrator.sh jot-diag-collect [output-path]
# De-nested from jot_diag_collect (Phase 0.0). Pure helpers — no captured state.
# [MIGRATED -> jot_diagSection @ 2026-05-05]
section() { printf '\n═══════════════════════════════════════════════════════════\n%s\n═══════════════════════════════════════════════════════════\n' "$1"; }
# [MIGRATED -> jot_diagIndent @ 2026-05-05]
indent()  { sed 's/^/  /'; }
# [MIGRATED -> jot_diagKv @ 2026-05-05]
kv()      { printf '%-28s %s\n' "$1" "$2"; }

# [PENDING]
jot_diag_collect() {
  local OUT CWD REPO_ROOT PROJECT TMUX_TARGET STATE_DIR LATEST FIRST_LINE
  local FOUND_TMP _log _root p CLIENTS d cmd

  OUT="${1:-/tmp/jot-diag-$(date +%Y%m%d-%H%M%S).log}"
  CWD=$(pwd)
  REPO_ROOT=$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null || echo "$CWD")
  PROJECT=$(basename "$REPO_ROOT")
  TMUX_TARGET="jot:jots"
  STATE_DIR="$REPO_ROOT/Todos/.jot-state"


  {
    printf 'jot-diag-collect report\n'
    printf 'generated: %s\n' "$(date -Iseconds)"
    printf 'cwd:       %s\n' "$CWD"
    printf 'project:   %s\n' "$PROJECT"
    printf 'tmux target (expected): %s\n' "$TMUX_TARGET"

    section "1. Latest Todos/*_input.txt"
    LATEST=$(ls -t "$REPO_ROOT"/Todos/*_input.txt 2>/dev/null | head -1 || true)
    if [ -z "$LATEST" ]; then
      echo "(no input.txt found in $REPO_ROOT/Todos/)"
    else
      kv "path" "$LATEST"
      kv "size (bytes)" "$(wc -c < "$LATEST" | tr -d ' ')"
      kv "mtime" "$(stat -f '%Sm' "$LATEST" 2>/dev/null || stat -c '%y' "$LATEST")"
      FIRST_LINE=$(head -1 "$LATEST")
      kv "first line" "$FIRST_LINE"
      if [[ "$FIRST_LINE" == PROCESSED:* ]]; then
        kv "status" "✓ PROCESSED (success)"
      elif [[ "$FIRST_LINE" == "# Jot Task" ]]; then
        kv "status" "⏳ PENDING (claude hasn't finished OR failed)"
      else
        kv "status" "? unknown first-line format"
      fi
      echo
      echo "--- full content ---"
      cat "$LATEST"
    fi

    section "2. State dir ($STATE_DIR)"
    if [ ! -d "$STATE_DIR" ]; then
      echo "(state dir does not exist — Phase 2 may not have run)"
    else
      echo "--- ls -la ---"
      ls -la "$STATE_DIR" 2>&1 | indent
      echo
      echo "--- queue.txt ---"
      if [ -f "$STATE_DIR/queue.txt" ]; then
        if [ -s "$STATE_DIR/queue.txt" ]; then
          cat "$STATE_DIR/queue.txt" | indent
        else
          echo "  (empty — no jobs pending)"
        fi
      else
        echo "  (missing)"
      fi
      echo
      echo "--- active_job.txt ---"
      if [ -f "$STATE_DIR/active_job.txt" ]; then
        if [ -s "$STATE_DIR/active_job.txt" ]; then
          cat "$STATE_DIR/active_job.txt" | indent
          echo "  (claude is currently processing this file)"
        else
          echo "  (empty — claude is idle)"
        fi
      else
        echo "  (missing)"
      fi
      echo
      echo "--- audit.log (last 30 entries) ---"
      if [ -f "$STATE_DIR/audit.log" ]; then
        tail -30 "$STATE_DIR/audit.log" | indent
      else
        echo "  (missing)"
      fi
      echo
      echo "--- queue.lock ---"
      if [ -e "$STATE_DIR/queue.lock" ]; then
        echo "  LOCK IS HELD (type: $(test -d "$STATE_DIR/queue.lock" && echo "dir (mkdir lock)" || echo "file"))"
        echo "  If no /jot is currently running, this is a stale lock and should be removed:"
        echo "    rm -rf '$STATE_DIR/queue.lock'"
      else
        echo "  (free — no lock held)"
      fi
    fi

    section "3. tmux session 'jot'"
    if ! tmux has-session -t jot 2>/dev/null; then
      echo "(no 'jot' tmux session exists)"
    else
      echo "--- tmux list-sessions | grep jot ---"
      tmux list-sessions 2>&1 | grep '^jot' | indent
      echo
      echo "--- tmux list-windows -t jot ---"
      tmux list-windows -t jot 2>&1 | indent
      echo
      echo "--- tmux list-panes -t $TMUX_TARGET ---"
      tmux list-panes -t "$TMUX_TARGET" -F '#{pane_id} pid=#{pane_pid} dead=#{pane_dead} deadstatus=#{pane_dead_status} cmd=#{pane_current_command}' 2>&1 | indent
      echo
      echo "--- pane start command ---"
      tmux display-message -t "$TMUX_TARGET" -p 'start: #{pane_start_command}' 2>&1 | indent
      echo
      echo "--- tmux attached clients ---"
      CLIENTS=$(tmux list-clients -t jot 2>/dev/null)
      if [ -z "$CLIENTS" ]; then
        echo "  (no clients attached)"
      else
        echo "$CLIENTS" | indent
      fi
      echo
      echo "--- pane content (last 80 lines of scrollback) ---"
      tmux_capture_pane "$TMUX_TARGET" 80 2>&1 | indent
    fi

    section "4. /tmp/jot.* per-invocation dirs"
    FOUND_TMP=0
    for d in /tmp/jot.*; do
      [ -d "$d" ] || continue
      FOUND_TMP=1
      echo "--- $d ---"
      ls -la "$d" 2>&1 | indent
      if [ -f "$d/settings.json" ]; then
        echo "  --- settings.json ---"
        cat "$d/settings.json" | indent
      fi
    done
    [ "$FOUND_TMP" = "0" ] && echo "(none — either not started or SessionEnd cleaned up)"

    _log="${JOT_LOG_FILE:-${CLAUDE_PLUGIN_DATA:-$HOME/.claude/plugins/data/jot}/jot-log.txt}"
    section "5. $_log (last 20 entries)"
    if [ -f "$_log" ]; then
      tail -20 "$_log" | indent
    else
      echo "(missing)"
    fi

    section "6. Todos/ directory listing (newest first)"
    if [ -d "$REPO_ROOT/Todos" ]; then
      ls -lat "$REPO_ROOT/Todos/" 2>&1 | head -20 | indent
    else
      echo "(no Todos/ dir in $REPO_ROOT)"
    fi

    _root="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/installed/jot}"
    section "7. Installed plugin orchestrator path"
    for p in \
      "$_root/scripts/jot-plugin-orchestrator.sh" \
      "$_root/scripts" \
      "$_root/hooks/hooks.json"
    do
      if [ -e "$p" ] || [ -L "$p" ]; then
        if [ -L "$p" ]; then
          kv "$p" "→ $(readlink "$p")"
        else
          kv "$p" "present ($(stat -f '%z' "$p" 2>/dev/null || stat -c '%s' "$p") bytes)"
        fi
      else
        kv "$p" "MISSING"
      fi
    done

    section "8. Dependency check"
    for cmd in jq python3 tmux claude osascript; do
      if command -v "$cmd" >/dev/null 2>&1; then
        kv "$cmd" "$(command -v "$cmd")"
      else
        kv "$cmd" "NOT FOUND"
      fi
    done

    section "END OF REPORT"
  } > "$OUT" 2>&1

  echo "jot-diag report: $OUT"
  echo "size: $(wc -c < "$OUT") bytes, $(wc -l < "$OUT") lines"
  echo
  echo "share this with Claude via:"
  echo "  cat $OUT"
  echo "or just paste the path."
}
# ─── end jot-diag-collect.sh ───

# Source-guard: when this file is sourced (e.g., by test_monolith.sh) we want
# the function definitions above to be exported into the caller's scope, but
# we must NOT execute the dispatch logic below (which reads stdin and calls
# `exit`, terminating the caller). Skip the mainline when sourced.
if [ "${BASH_SOURCE[0]}" != "${0}" ]; then
  return 0 2>/dev/null || true
fi

# Argv dispatch: if invoked as `bash jot-plugin-orchestrator.sh <entry-name> <args>`,
# route to the matching function and exit without reading stdin.
case "${1:-}" in
  jot-session-start)        shift; jot_session_start "$@";       exit ;;
  jot-session-end)          shift; jot_session_end "$@";         exit ;;
  jot-stop)                 shift; jot_stop "$@";                exit ;;
  scan-open-todos)          shift; scan_open_todos "$@";         exit ;;
  todo-launcher)            shift; todo_launcher "$@";           exit ;;
  todo-stop)                shift; todo_stop "$@";               exit ;;
  todo-session-start)       shift; todo_session_start "$@";      exit ;;
  todo-session-end)         shift; todo_session_end "$@";        exit ;;
  plate-summary-stop)       shift; plate_summary_stop "$@";      exit ;;
  plate-summary-watch)      shift; plate_summary_watch "$@";     exit ;;
  debate-tmux-orchestrator) shift; debate_tmux_orchestrator "$@"; exit ;;
  jot-diag-collect)         shift; jot_diag_collect "$@";        exit ;;
esac

INPUT=$(cat)
PROMPT=$(printf '%s' "$INPUT" | hide_errors jq -r '.prompt // ""')

# Strip leading whitespace so "  /jot foo" still dispatches.
PROMPT="${PROMPT#"${PROMPT%%[![:space:]]*}"}"

# Claude Code namespaces plugin skills as "/<plugin>:<skill>" when
# disambiguation is needed. Normalise "/jot:todo-list" → "/todo-list" so the
# case branches below don't have to enumerate both forms. We rewrite both the
# local $PROMPT (for the case match) and the forwarded JSON's .prompt field
# (so sub-orchestrators see the same normalised form).
case "$PROMPT" in
  /jot:*)
    PROMPT="/${PROMPT#/jot:}"
    INPUT=$(printf '%s' "$INPUT" | hide_errors jq --arg p "$PROMPT" '.prompt = $p')
    ;;
esac

case "$PROMPT" in
  "/jot"|"/jot "*|$'/jot\n'*)
    printf '%s' "$INPUT" | jot_main
    ;;
  "/plate"|"/plate "*|$'/plate\n'*)
    printf '%s' "$INPUT" | plate_main
    ;;
  "/debate"|"/debate "*|$'/debate\n'*)
    printf '%s' "$INPUT" | debate_launch
    ;;
  "/debate-retry"|"/debate-retry "*|$'/debate-retry\n'*)
    printf '%s' "$INPUT" | debate_retry_main
    ;;
  "/debate-abort"|"/debate-abort "*|$'/debate-abort\n'*)
    printf '%s' "$INPUT" | debate_abort_main
    ;;
  "/todo"|"/todo "*|$'/todo\n'*)
    printf '%s' "$INPUT" | todo_main
    ;;
  "/todo-list"|"/todo-list "*|$'/todo-list\n'*)
    printf '%s' "$INPUT" | todo_list_main
    ;;
  *)
    exit 0
    ;;
esac
