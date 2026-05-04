# Migrate `common/scripts/claude-launcher.sh` to Python

## Source

- File: `common/scripts/claude-launcher.sh`
- Class: **`(sourced)`** — every live caller uses `. claude-launcher.sh` and invokes the exported function `build_claude_cmd`. No caller invokes it as `bash claude-launcher.sh ...`; no hook entry-point binding.
- Size: 52 lines bash
- Position in dependency graph: leaf shared library; pure file-IO + string formatting; does not source any other `common/scripts/*.sh`.

### Caller inventory (grep `claude-launcher` repo-wide)

| Caller | Line | Mode |
| --- | --- | --- |
| `skills/jot/scripts/jot.sh` | 125 | sources, calls `build_claude_cmd` at line 65 inside `jot_build_claude_cmd` |
| `skills/debate/scripts/debate.sh` | 160 | sources, calls `build_claude_cmd` at line 139 inside `debate_build_claude_cmd` |
| `skills/todo/scripts/todo-launcher.sh` | 29 | sources, calls `build_claude_cmd` at line 119 |
| `skills/debate/scripts/OLD_DISCARD/debate.sh` | 94 | dead code; ignore |
| `common/scripts/plate/spawn_summary_agent.py` | 102 | doc comment only — already a Python re-implementation; not a runtime caller |

All live callers source the file. Migration class is **sourced** — the `.sh` must remain on disk as a thin shim that re-exports a `build_claude_cmd` shell function delegating to the Python CLI.

## Behavior spec (per-function, plain English — RED test scenarios)

### `build_claude_cmd <settings_out> <allow_json> <hooks_json_file> <cwd> [add_dir...]`

Inputs:
- `settings_out` — absolute path; the function overwrites the file at this path.
- `allow_json` — string already containing a JSON-array literal of permissions (caller produces it via `expand_permissions.py`).
- `hooks_json_file` — absolute path to a file whose contents are a JSON object literal suitable as the `"hooks"` value in `settings.json`.
- `cwd` — string, the launcher cwd; becomes the FIRST `--add-dir` argument.
- variadic remainder — zero or more extra `--add-dir` paths.

Side-effects + outputs:
1. **Read** the entire contents of `hooks_json_file` into a buffer.
2. **Write** a new file at `settings_out` whose body is exactly:
   ```
   {
     "permissions": {
       "allow": <allow_json>
     },
     "hooks": <hooks_json_contents>
   }
   ```
   - Two-space indentation, trailing newline matching the bash heredoc.
   - File is overwritten if it already exists.
   - `allow_json` and the contents of `hooks_json_file` are spliced verbatim. The function does NOT validate or re-serialize them.
3. **Print to stdout** a single line:
   ```
   claude --settings '<settings_out>' --add-dir '<cwd>' --add-dir '<add_dir1>' --add-dir '<add_dir2>' ...
   ```
   - Each path is wrapped in single quotes literally (no escaping of embedded quotes — bash does not escape either).
   - Trailing newline (from `printf '%s\n'`).
4. Returns 0 on success. Bash version has no explicit error handling; if `hooks_json_file` is unreadable, `cat` exits non-zero and (without `set -e`) the function continues and writes a malformed `settings.json`. The Python port MUST raise instead — caller scripts run under `set -euo pipefail`, so a non-zero exit propagates correctly.

External commands invoked: `cat`, `printf` (both replaced by native Python). No env vars consumed. No subprocess forks beyond `cat`. No tmux, locks, signals.

## Target Python module

- New module: `common/scripts/claude_launcher_lib.py`
  - Public function: `build_claude_cmd(settings_out: Path, allow_json: str, hooks_json_file: Path, cwd: str, *add_dirs: str) -> str`
  - Returns the resolved command string (no trailing newline). The CLI shim is responsible for `print()` adding the newline so stdout matches bash exactly.
- New CLI dispatcher: `common/scripts/claude_launcher_cli.py`
  - `argparse` with positional args mirroring the bash signature: `settings_out allow_json hooks_json_file cwd [add_dir...]`.
  - Calls `build_claude_cmd(...)`, prints result, exits 0; non-zero on any raised exception.
- Existing `common/scripts/claude-launcher.sh` becomes a shim that defines a shell function:
  ```bash
  build_claude_cmd() {
    python3 "$(dirname "${BASH_SOURCE[0]}")/claude_launcher_cli.py" "$@"
  }
  ```
  Preserves the sourced API exactly: callers continue to write `CMD=$(build_claude_cmd ...)`.

## `_cli.py` shim required? — YES

Functions to expose via the shim: just `build_claude_cmd`. No other names are referenced by callers (verified by grep).

## RED test list (`tests/test_claude_launcher.py`)

Each scenario starts as a plain-English comment per `RED_GREEN_TDD.md`, then a failing assertion until the lib lands.

1. **`test_settings_file_is_written_with_permissions_allow_field`** — given `allow_json='["A","B"]'` and an empty hooks file `{}`, the written `settings.json` parses as JSON whose `.permissions.allow == ["A","B"]`.
2. **`test_settings_file_is_written_with_hooks_field_spliced_verbatim`** — given a hooks file containing `{"SessionStart":[{"hooks":[{"type":"command","command":"foo"}]}]}`, the written settings file's `.hooks.SessionStart[0].hooks[0].command == "foo"`.
3. **`test_settings_file_overwrites_existing_target`** — pre-create `settings_out` with sentinel bytes, call function, assert sentinel bytes are gone and new JSON parses cleanly.
4. **`test_stdout_command_starts_with_claude_settings_flag`** — captured stdout begins `claude --settings '<abs_settings_out>'`.
5. **`test_stdout_command_includes_cwd_as_first_add_dir`** — first `--add-dir` argument equals the `cwd` positional, in single quotes.
6. **`test_stdout_command_appends_each_extra_add_dir_in_order`** — `cwd=/a` plus `extras=['/b','/c']` yields trailing `--add-dir '/a' --add-dir '/b' --add-dir '/c'` in that exact order.
7. **`test_stdout_command_with_zero_extra_add_dirs`** — passing only `cwd` produces exactly one `--add-dir` flag.
8. **`test_paths_with_spaces_are_wrapped_in_single_quotes_literally`** — `cwd="/tmp/path with space"` round-trips inside single quotes (matching bash; no embedded-quote escaping required by spec).
9. **`test_allow_json_string_is_spliced_verbatim_not_re_encoded`** — `allow_json='[ "X" , "Y" ]'` (deliberately weird whitespace) appears byte-for-byte inside the written settings file's `"allow":` slot. Proves no `json.dumps` re-serialization.
10. **`test_hooks_json_file_contents_are_spliced_verbatim`** — write a hooks file with deliberate whitespace padding; assert the same bytes appear inside `settings_out` after the `"hooks":` key.
11. **`test_missing_hooks_json_file_raises`** — non-existent `hooks_json_file` raises `FileNotFoundError`. Documented intentional divergence from bash silent-malformed behavior.
12. **`test_returned_string_has_no_trailing_newline_but_cli_prints_one`** — library returns a chomped string; CLI dispatcher's stdout has exactly one trailing `\n`, matching the bash `printf '%s\n'`.
13. **`test_cli_argparse_accepts_zero_extra_add_dirs`** — `python3 claude_launcher_cli.py settings_out allow_json hooks_file cwd` exits 0 and prints a valid command line.
14. **`test_cli_argparse_accepts_many_extra_add_dirs`** — same invocation with 4 trailing positionals.
15. **`test_sourced_shim_function_round_trips_through_python`** — integration: `bash -c '. common/scripts/claude-launcher.sh; build_claude_cmd ...'` produces stdout byte-identical to a direct `python3 claude_launcher_cli.py` invocation with the same args.
16. **`test_sourced_shim_writes_same_settings_file_as_pre_migration`** — golden-file: capture the bash original's `settings.json` for a fixed input pre-migration, then assert the post-migration shim writes a parse-equivalent JSON object (equal after `json.load`; whitespace-equal preferred).

## Risk callouts

1. **Quoting fidelity** — bash wraps every path in single quotes without escaping. If a caller ever passes a path containing a single quote (extremely unlikely; `CLAUDE_PLUGIN_ROOT` and tmpdirs are controlled), both bash and the Python port emit broken shell. Match bash exactly to avoid drift; document the limitation in the module docstring.
2. **Verbatim splicing of `allow_json` and `hooks_json`** — the bash heredoc does not parse or validate these strings. The Python port must NOT call `json.dumps` on them, or formatting diverges from existing golden inputs. Use raw f-string interpolation with `{allow_json}` and `{hooks_contents}`.
3. **Trailing newline on stdout** — bash uses `printf '%s\n'`. Callers do `CMD=$(build_claude_cmd ...)` which strips trailing newlines via command substitution, so the newline is invisible to live callers. The Python CLI must still emit it (use `print()`) so any future caller observes identical bytes.
4. **`set -e` interaction** — all three callers (jot.sh:125, debate.sh:160, todo-launcher.sh:29) run under `set -euo pipefail`. The bash function is silent on a missing hooks file; Python raising and exiting non-zero will newly trigger `set -e` aborts in callers. Verify this is desired — silent malformed JSON is a latent bug — and document the behavior change in the migration commit.
5. **`BASH_SOURCE[0]` resolution in shim** — the shim must use `"$(dirname "${BASH_SOURCE[0]}")"` not `$(dirname "$0")`, because the script is sourced; `$0` would be the parent script's name.
6. **Race conditions** — none. The function is idempotent and produces a fresh `settings_out` per invocation under a per-invocation tmpdir.
7. **Platform quirks** — none. Pure file IO + string formatting; no `realpath`, `readlink`, `mktemp`, `tmux`, or platform-specific tools.
8. **No subprocess, no env vars consumed, no signals** — bash version reads no env vars and forks `cat` once. Python port reads no env vars and forks nothing.

## Verification plan (zero-regression for live callers)

Pytest alone is insufficient — the bash shim's sourcing semantics must be exercised end-to-end.

1. **Unit GREEN**: `pytest tests/test_claude_launcher.py -v` — all 16 scenarios pass.
2. **Shim integration test**: `bash -c '. common/scripts/claude-launcher.sh; build_claude_cmd /tmp/s "[\"X\"]" /tmp/h /cwd /extra'` after pre-creating `/tmp/h` with `{}`. Assert stdout byte-equal to `python3 common/scripts/claude_launcher_cli.py /tmp/s '["X"]' /tmp/h /cwd /extra`.
3. **Live caller smoke — jot**: run `bash skills/jot/scripts/jot.sh` end-to-end on a sandbox repo with a fixture idea; capture the `SETTINGS_FILE` it produces. Compare against a pre-migration capture (commit hash recorded in the migration commit message). Use `jq -S . pre.json > pre.norm && jq -S . post.json > post.norm && diff pre.norm post.norm` — must be empty.
4. **Live caller smoke — debate**: run `bash skills/debate/scripts/debate.sh` with a trivial topic in a sandbox; verify the spawned tmux session starts (`tmux has-session`) and the generated `settings.json` parses.
5. **Live caller smoke — todo**: run `bash skills/todo/scripts/todo-launcher.sh` with a fixture idea; verify the worker session spawns and writes a TODO file.
6. **Pre/post capture diff (rigorous regression evidence)**: BEFORE merging, on `main`, run each of the three live callers with a temporary `cp "$settings_out" /tmp/pre/<caller>.json` inserted into the bash function. Then check out the migration branch, repeat into `/tmp/post/`. `diff -ru /tmp/pre /tmp/post` must show only paths/timestamps differing, never structural JSON content. Remove the debug `cp` before merge.
7. **Permission-prompt audit**: confirm `claude --settings <generated>` actually launches without rejecting the file (smoke: `claude --settings <generated> --print 'noop'` exits 0).

## Numbered TODO list (mirrors migration template steps 0-8)

0. Mark `common/scripts/claude-launcher.sh` as `[i]` in `MIGRATION_TO_PYTHON.md` (already done by the discovery agent); flip to `[p]` once this plan is committed.
1. Write the 16 RED tests in `tests/test_claude_launcher.py` as failing plain-English scenario stubs. Confirm `pytest` shows all 16 failing.
2. Implement `common/scripts/claude_launcher_lib.py::build_claude_cmd` — pure-Python, no subprocess. Use raw f-string interpolation for `allow_json` and `hooks_contents` (no `json.dumps`).
3. Run `pytest tests/test_claude_launcher.py -v` and iterate until GREEN.
4. Mark `[~]` in `MIGRATION_TO_PYTHON.md`.
5. Add `common/scripts/claude_launcher_cli.py` argparse dispatcher; wire to lib. Add CLI scenarios (#13, #14) and re-run pytest.
6. Replace `common/scripts/claude-launcher.sh` body with the shim shell function that delegates to `claude_launcher_cli.py`. Keep the existing header comment block so callers that grep for documentation still find it.
7. (No hook entry-point change needed — this script has no hook binding.)
8. Run the full Verification plan (shim integration + three live-caller smokes + pre/post JSON diff). Only after diff-clean, mark `[x]` and update `MIGRATION_TO_PYTHON.md`.

