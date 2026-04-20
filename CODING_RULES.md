# common/scripts/ coding rules

These rules apply to all functions in any library scripts in this directory.

## Function style

1. **Usage comment above every function.** States what arguments to pass.
   ```bash
   # usage: tmux_kill_session <session_name>
   ```

2. **Returns comment when the return value isn't obvious.** States what 0 and nonzero mean.
   ```bash
   # returns: 0 on success, 1 if kill failed (e.g. session not found)
   ```

3. **No `local variable="$1"`.** Use `$1`, `$2` directly. The usage comment documents what they are.

4. **No `|| true`. Ever.** Let errors propagate. If tmux already reports a clear error for the failure case, don't add a precondition check — just let tmux fail and forward its error.

5. **Wrap every external command with `invoke_command`.** The helper in `invoke_command.sh` captures merged stdout+stderr, emits output on success (trailing newline only when non-empty), logs `[caller] command '...' failed: <output>` to stderr on nonzero, and returns the command's exit code. Most wrappers collapse to one line:
   ```bash
   tmux_has_session() {
     invoke_command tmux has-session -t "$1"
   }
   ```

6. **Don't consume `invoke_command`'s failure log casually.** No raw `2>/dev/null` on its invocations. Even a "missing" return from a query carries diagnostic content (e.g. `can't find session: foo`) — swallowing it loses the trail when something real breaks later. If silencing is actually justified (see rule 7), use `hide_errors` so the intent is explicit and greppable.

7. **Prefer `hide_output` / `hide_errors` over raw redirects.** Bare `>/dev/null` and `2>/dev/null` are easy to miss in review and carry no intent. The named helpers (in `invoke_command.sh`) make silencing searchable and invite an adjacent comment explaining *why*.
   - `hide_output <cmd> [args...]` — discards stdout. Use when a wrapped command's success-output is noise (e.g. `tmux set-option` echoing the new value).
   - `hide_errors <cmd> [args...]` — discards stderr. Use sparingly — this drops diagnostics. Valid cases: probes where "failed" is a valid answer state (`tmux_list_clients` on a session that might not exist), or cleanup of resources that may already be gone.
   - Compose when both streams are noise: `hide_output hide_errors <cmd>`. Bash's nested function calls preserve stdin, so heredocs still reach the innermost command.
   ```bash
   hide_output tmux_set_option_t "$session" mouse on
   clients=$(hide_errors tmux_list_clients "$session")
   if ! hide_output hide_errors command -v osascript; then ...
   ```

8. **Fallback when `invoke_command` can't be used** (rare — e.g. when the command's stdout must be piped live rather than captured). Capture the exit code explicitly and re-emit stderr with a `[function_name]` prefix:
   ```bash
   local result=$?
   return $result
   ```

9. **Declaration order.** Dependencies come first. If `tmux_new_session` calls `tmux_has_session`, `has_session` is defined above it.

## Testing style

10. **Each group has a `_tests()` function.** It exercises every function in the group. Tests use the functions themselves — e.g. `tmux_session_tests` calls `has_session`, `new_session`, `kill_session` in a lifecycle sequence.

11. **Tests check both success and failure paths.** Create succeeds, duplicate fails, kill succeeds, kill-nonexistent fails.

12. **Test cleanup uses `$$` for uniqueness.** Session/window/pane names include `$$` (the PID) so parallel test runs don't collide.

13. **Test output format:**
    ```
    PASS: description
    FAIL: description
    group_tests: PASS=N FAIL=N
    ```

14. **Tests return nonzero on any failure:** `[ "$fail" -eq 0 ]` as the last line.

## TODO

- Extract shared Python functionality from `common/scripts/jot/*.py` and `common/scripts/plate/*.py` into a single `common/scripts/shared.py`. Candidates: git-state helpers, path resolution, JSON I/O, logging. Callers import from `shared` after the move.
