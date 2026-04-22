# invoke_command.sh — canonical command-execution wrapper.
# Source silencers.sh separately if you also need hide_output / hide_errors.

invoke_command() {
    # The `if output=$(...); then` form is load-bearing with `set -eE`: it
    # places the command substitution in an `if` test context, which suppresses
    # both errexit and ERR-trap inheritance inside the subshell. Without it,
    # a caller's ERR trap would fire *inside* the subshell, emit its block
    # diagnostic to the captured stdout (ending up in `$output`), and then get
    # reprinted by our success branch below — producing duplicate block JSON
    # and leaking raw command stderr into hook output.
    local output result
    if output=$("$@" 2>&1); then
        result=0
    else
        result=$?
    fi
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
