

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

# usage: hide_output <command> [args...]
# Runs the command with its stdout redirected to /dev/null. Stderr passes
# through unchanged — real failures still surface. Useful for wrapping calls
# whose success-output is noise the caller doesn't want (e.g. `tmux set-option`
# echoing the new value).
# returns: the command's exit code
hide_output() {
  "$@" >/dev/null
}

# usage: hide_errors <command> [args...]
# Runs the command with its stderr redirected to /dev/null. Stdout passes
# through unchanged — callers can still capture output. Complement of
# hide_output. Use for probes where "failed" is a valid answer state and
# the diagnostic log would be noise.
# returns: the command's exit code
hide_errors() {
  "$@" 2>/dev/null
}