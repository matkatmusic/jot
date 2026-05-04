# Migrate `common/scripts/invoke_command.sh` to Python

## Source

- File: `common/scripts/invoke_command.sh`
- Class: `(sourced)` - every caller pulls it in via `source` / `.` and calls the `invoke_command` shell function. Never executed as a subprocess. Migration must therefore preserve the bash-callable function shape via a thin shim that delegates to a Python `_cli.py`.
- Size: 18 lines bash, one function (`invoke_command`).
- Position in dependency graph: foundational. Sourced (directly or transitively) by nearly every other shell file in the plugin. Its migration unblocks every `(sourced)` and `(blocked)` script that delegates through it (notably `common/scripts/tmux.sh`).

## Callers (full list)

Direct `source` / `.` imports:

1. `common/scripts/tmux.sh` - line 10. ~20 call sites of `invoke_command tmux ...`.
2. `skills/jot/scripts/jot-state-lib.sh` - line 9.
3. `skills/jot/scripts/jot-stop.sh` - transitive through `jot-state-lib.sh`.
4. `skills/jot/scripts/jot.sh` - line 41 copies the file into `$TMPDIR_INV` and sources from there at launch.
5. `skills/debate/tests/archive/test.sh` - line 6 (archived test, but still references the path).
6. `skills/debate/scripts/OLD_DISCARD/debate-tmux-orchestrator.sh` - line 20 (dead; ignore for migration).
7. `skills/debate/scripts/debate-tmux-orchestrator.sh` - line 43.
8. `skills/todo/scripts/todo-stop.sh` - line 17.
9. `skills/todo/scripts/todo-launcher.sh` - line 97 copies the file into `$TMPDIR_INV` (mirrors `jot.sh`).

Transitive consumers (via `tmux.sh`): every script that sources `tmux.sh`, `tmux-launcher.sh`, or any orchestrator that uses tmux primitives.

CHANGELOG / docs (non-code references, not callers): `CHANGELOG.md`, `README.md`, `CODING_RULES.md`, `common/scripts/USAGE.md`, `MIGRATION_TO_PYTHON.md`.

`hide_output` / `hide_errors` are NOT in this file; they live in `silencers.sh` (already split, marked `[!]` won't-migrate). Do not pull them back into scope.

## Per-function behavior spec

Single function: `invoke_command "$@"`.

1. Captures merged stdout+stderr of `"$@"` into a local var `output` via `output=$("$@" 2>&1)`.
2. Captures the underlying exit code into `result` via `$?`.
3. On nonzero exit:
   - Writes `"[<caller>] command '<argv-joined-by-space>' failed: <output>"` to stderr.
   - `<caller>` is `${FUNCNAME[1]}` - the bash caller's function name. When `invoke_command` is called from top-level (no enclosing function), bash leaves `FUNCNAME[1]` empty; the migrated form must reproduce that exact behavior (empty brackets `[]`) or a documented sentinel - choose the bash-faithful empty form for byte-for-byte compatibility, but expose a `_cli.py --caller-fallback unknown` option for non-shell callers per the existing `tests/test_invoke_command_cli.py::test_shim_top_level_call_uses_unknown_fallback` reference in the pytest cache.
   - `<argv-joined-by-space>` is bash `$*` - space-joined, no shell-quoting. Tests in the pytest cache (`test_argv_with_spaces_is_shell_quoted_in_error`, `test_argv_with_single_quote_is_shell_safe_in_error`) imply the Python rewrite SHOULD `shlex.join` argv for safe round-tripping. This is an intentional behavior improvement; document it.
4. On zero exit with non-empty `output`: `printf '%s\n' "$output"` - exactly one trailing newline appended.
5. On zero exit with empty `output`: writes nothing. No stray newline.
6. Returns the underlying exit code (`return $result`).

Implicit/derived behavior worth pinning in tests:

- Combined-stream capture: stderr lines from the wrapped command become part of stdout-on-success and part of the failure message on failure.
- Missing program (`ENOENT`): bash returns 127 and prints `command not found` to stderr (which `2>&1` folds into `output`). Python must reproduce 127, not 1, and must not raise `FileNotFoundError`.
- Signal exit: bash returns `128 + signum`. Python's `subprocess.run().returncode` returns negative numbers; the wrapper must translate `-N` -> `128 + N` to stay byte-compatible with shell semantics (matters for callers that check `$? -eq 130` after a Ctrl-C).

## Quoting / escaping callouts (likely the reason this helper exists)

The existing bash form has known footguns the Python rewrite should fix or preserve verbatim. Document each so the GREEN tests pin the chosen direction:

1. `'$*'` in the failure message is space-joined, NOT shell-quoted. An argv like `["tmux", "send-keys", "-t", "sess:1", "echo hi"]` prints `command 'tmux send-keys -t sess:1 echo hi'` - ambiguous when an argv element contains spaces. The pytest cache shows we're moving to `shlex.join`. PIN this in a RED test.
2. `'$*'` is a single string inside single quotes; if any argv element contains a literal single quote, the resulting log line has unbalanced quotes. `shlex.join` fixes this. Pin via RED test (matches `test_argv_with_single_quote_is_shell_safe_in_error`).
3. `output=$(... 2>&1)` strips trailing newlines (bash command-substitution rule). The Python form must reproduce: `result.stdout.rstrip('\n')` before printing/embedding.
4. The `printf '%s\n'` step re-adds exactly one trailing newline. Python equivalent: `print(output)` only when `output != ""`. Verify no double-newline, no stripped-newline.
5. `${FUNCNAME[1]}` is a bash-only construct. The Python `_cli.py` cannot read the bash call stack - the shim must pass it explicitly via `--caller "${FUNCNAME[1]}"`. The shim function in `invoke_command.sh` is the ONLY place that has access to this value.

## Migration class & target paths

- Migration class: `(sourced)` (Medium per the legend; bash shim with function definitions delegating to `_cli.py`).
- Python library module: `common/scripts/invoke_command_lib.py` (matches existing pytest cache entry `tests/test_invoke_command_lib.py`).
- Python CLI shim: `common/scripts/invoke_command_cli.py` (matches `tests/test_invoke_command_cli.py`).
- Final bash shim: `common/scripts/invoke_command.sh` keeps the file path and the `invoke_command` function name; the function body becomes a one-liner that execs the CLI.

### `_cli.py` shim design (required because file is sourced)

```python
# common/scripts/invoke_command_cli.py
# Usage: invoke_command_cli.py --caller <name> -- <program> [args...]
# stdout: captured-and-re-emitted output from the underlying command
# stderr: failure log line on nonzero exit
# exit code: underlying program's exit code (or 127 if program not found)
```

The bash shim becomes:

```bash
# common/scripts/invoke_command.sh - Python-backed shim. Function shape preserved.
invoke_command() {
    python3 "$(dirname "${BASH_SOURCE[0]}")/invoke_command_cli.py" \
        --caller "${FUNCNAME[1]:-}" -- "$@"
}
```

Note: must remain a function (not `exec`) so existing `source` consumers keep working. `${FUNCNAME[1]}` is captured by the shim before crossing the Python boundary.

## RED test scenarios (pytest, plain English)

Two test files mirror the pytest-cache layout already drafted upstream:

### `tests/test_invoke_command_lib.py` - pure-Python unit tests against `invoke_command_lib.run(argv, caller)`

1. `test_success_with_output_prints_to_stdout` - wrapping `echo hi` returns 0 and the captured-output string equals `"hi"`.
2. `test_success_with_no_output_is_silent` - wrapping `true` returns 0 and emits an empty string (NOT `"\n"`).
3. `test_success_output_has_single_trailing_newline` - when the lib's caller prints the captured output, the line count matches the original command (no double-newline, no missing newline).
4. `test_combined_stdout_and_stderr_capture_on_success` - wrapping a python -c that writes to both streams returns both lines, in interleaved-or-stderr-after order matching `2>&1`.
5. `test_failure_returns_underlying_exit_code` - wrapping `false` returns 1; wrapping a script that exits 7 returns 7.
6. `test_failure_writes_caller_tagged_error_to_stderr` - failure message starts with `[caller_name] command '`.
7. `test_combined_streams_appear_in_failure_message` - stderr from the failing command shows up after `failed: ` in the log line.
8. `test_caller_name_round_trips_into_error_prefix` - `caller="my_func"` -> message starts `[my_func] `.
9. `test_argv_with_spaces_is_shell_quoted_in_error` - argv `["echo", "a b"]` -> log shows `'echo "a b"'` (or `shlex.join` form). Pins the quoting fix.
10. `test_argv_with_single_quote_is_shell_safe_in_error` - argv `["echo", "it's"]` -> log shows balanced shell-safe quoting.
11. `test_missing_program_returns_127` - running `["this-binary-does-not-exist"]` returns exit 127, NOT raising `FileNotFoundError`.
12. `test_missing_program_writes_caller_tagged_error` - same case writes the standard `[caller] command '...' failed: ...` line.
13. `test_signal_exit_translates_to_128_plus_signum` - wrapping a child that gets SIGTERM returns 143 (128+15), not -15. Pins shell-faithful exit-code translation.

### `tests/test_invoke_command_cli.py` - subprocess tests against the `_cli.py` and the bash shim

1. `test_cli_success_with_output` - `python3 invoke_command_cli.py --caller f -- echo hi` exits 0, prints `hi\n`.
2. `test_cli_success_no_output_is_silent` - `--caller f -- true` exits 0, prints nothing.
3. `test_cli_failure_returns_underlying_exit_code` - `--caller f -- false` exits 1.
4. `test_cli_failure_writes_caller_tagged_error` - failure stderr matches `^\[f\] command '.*' failed: `.
5. `test_cli_missing_caller_flag_errors` - invoking without `--caller` exits with usage error.
6. `test_cli_missing_program_returns_127` - `--caller f -- nope-not-real` exits 127.
7. `test_cli_run_without_command_errors` - `--caller f --` (no program) is a usage error, distinct exit code (e.g. 2).
8. `test_shim_propagates_underlying_exit_code` - sourcing `invoke_command.sh` in a bash subprocess and calling `invoke_command false` propagates 1.
9. `test_shim_success_no_output_is_silent` - `invoke_command true` produces empty stdout.
10. `test_shim_success_with_output_passes_through` - `invoke_command echo hi` prints `hi\n`.
11. `test_shim_captures_caller_name_in_error` - defining `my_func() { invoke_command false; }` then calling `my_func` writes `[my_func] command 'false' failed: ` to stderr.
12. `test_shim_argv_with_spaces_quoted_in_error` - `invoke_command echo "a b"` failure message would have shell-safe quoting (use a failing wrapper to force the path).
13. `test_shim_top_level_call_uses_unknown_fallback` - calling `invoke_command false` from bash top level (no enclosing function, so `FUNCNAME[1]` is empty) writes either `[]` (bash-faithful) or `[unknown]` (sentinel) to stderr - pick one in the GREEN phase and pin it.

## Risk callouts

1. **Quoting in error log** - the existing bash form is unsafe. Migrating to `shlex.join` is a behavioral CHANGE. Confirm with code review before committing the GREEN form. Tests above pin the new form; if reviewers want byte-compatibility instead, swap to `" ".join(argv)`.
2. **Signal handling / exit codes** - Python `subprocess.run` returns negative codes for signal-killed children; bash returns `128+signum`. Translate or callers that check `$? == 130` (Ctrl-C) will silently misroute.
3. **`FUNCNAME[1]` boundary** - only the bash shim sees the caller name. Tests must cover both code paths: shim-with-caller and direct-CLI-with-explicit-caller.
4. **Combined-stream ordering** - `2>&1` in bash interleaves at the kernel level; Python `subprocess.run(..., stderr=STDOUT)` matches. Do NOT use `capture_output=True` (separate pipes) - order will diverge.
5. **Trailing-newline semantics** - empty-stdout case must stay byte-empty; non-empty case must end in exactly one `\n`. Pinned by tests #2, #3.
6. **Performance** - every wrapped command now spawns `python3` (an extra ~30ms cold-start). Across 20+ `invoke_command tmux ...` sites in `tmux.sh`, this adds up. Consider whether a single long-lived helper or a fast-path is warranted; document the tradeoff and accept it for this round (matches the orchestrator plan's posture).
7. **`$TMPDIR_INV` copies** (`jot.sh:41`, `todo-launcher.sh:97`) - the launchers `cp` the `.sh` into a temp dir and source from there. Ensure they ALSO copy `invoke_command_cli.py` (and `invoke_command_lib.py`) into the same temp dir, OR change the shim to resolve the Python module by absolute plugin path. Decide in the GREEN phase; if absolute-path is chosen, update both launchers in the same commit.
8. **Stdin pass-through** - current shim does NOT redirect stdin. Verify Python `subprocess.run(...)` with no `stdin=` argument inherits the parent's stdin so wrapped commands like `jq` keep working when piped to.

## Verification plan

A failing-form check is required for each behavior. Run in this order:

1. `pytest tests/test_invoke_command_lib.py -v` -> all GREEN.
2. `pytest tests/test_invoke_command_cli.py -v` -> all GREEN.
3. Whole suite: `pytest -v` -> no regressions in any other test file. `tmux.sh` callers transitively exercise the shim.
4. Bash smoke: `source common/scripts/invoke_command.sh && f() { invoke_command false; }; f; echo $?` -> stderr line `[f] command 'false' failed: `, exit code `1`.
5. Bash smoke: `source common/scripts/invoke_command.sh && invoke_command echo hi | wc -l` -> `1`.
6. Bash smoke: `source common/scripts/invoke_command.sh && invoke_command true | wc -c` -> `0` (proves no stray newline).
7. Integration: run an existing tmux-using test (e.g. a tmux.sh test or `skills/jot/scripts/jot.sh` startup) under the new shim. Confirm no behavior change.
8. Failing-form verification (per `feedback_verify_work.md`): before/after capture - capture stderr from the OLD `.sh` for cases 9, 10 in the lib tests; capture stderr from the NEW shim; diff. The diff SHOULD show the quoting fix, NOT diverge anywhere else.

## Numbered TODO list (template steps 0-8)

0. Pre-work: confirm `silencers.sh` stays out of scope; confirm callers list above is complete (re-grep before starting).
1. Mark `[i]` in `MIGRATION_TO_PYTHON.md` for `common/scripts/invoke_command.sh`.
2. Land this plan; mark the entry `[p]` in `MIGRATION_TO_PYTHON.md`.
3. Write RED tests:
   - `tests/test_invoke_command_lib.py` (13 scenarios above).
   - `tests/test_invoke_command_cli.py` (13 scenarios above).
   Confirm RED: every test fails because no module/CLI exists yet.
4. Mark the entry `[~]` in `MIGRATION_TO_PYTHON.md`.
5. Implement:
   - `common/scripts/invoke_command_lib.py` - pure function `run(argv: list[str], caller: str) -> tuple[int, str]` returning `(exit_code, captured_output)` and a side-effecting `run_and_emit(argv, caller, *, stdout, stderr)` for CLI use.
   - `common/scripts/invoke_command_cli.py` - argparse front end: `--caller NAME -- ARGV...`. Calls `run_and_emit` and `sys.exit(code)`.
   - Replace `common/scripts/invoke_command.sh` body with the shim function above (function NOT `exec`, because file is sourced).
6. Run pytest until both files are GREEN. Run the whole suite to confirm no transitive regression.
7. Update `$TMPDIR_INV` copy sites (`skills/jot/scripts/jot.sh`, `skills/todo/scripts/todo-launcher.sh`) to also copy `invoke_command_cli.py` and `invoke_command_lib.py` next to the `.sh` shim - OR pin shim to absolute plugin path. Pick one; update in the same commit.
8. End-to-end verification per the section above (bash smoke, integration test, before/after stderr diff). Mark the entry `[x]` in `MIGRATION_TO_PYTHON.md` only after step 8 passes.

