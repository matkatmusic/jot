# silencers.sh — canonical stdout/stderr suppression wrappers.
# The rest of the codebase must not use raw `>/dev/null` or `2>/dev/null`;
# use these wrappers so suppression intent is searchable and explicit.

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
