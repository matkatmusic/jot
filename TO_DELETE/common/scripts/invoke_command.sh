# invoke_command.sh — canonical command-execution wrapper.
# Source silencers.sh separately if you also need hide_output / hide_errors.

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
