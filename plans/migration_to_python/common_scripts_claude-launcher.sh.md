# Migrate `common/scripts/claude-launcher.sh` to Python

## Source

- File: `common/scripts/claude-launcher.sh`
- Size: 52 lines bash
- Position in dependency graph: leaf shared library; pure file-IO + string formatting; sources no other `common/scripts/*.sh`.
- Target module: `common/scripts/claude_launcher_lib.py`

## Function table

| name | Python signature (typed) | return type | one-line behavior note |
| --- | --- | --- | --- |
| `build_claude_cmd` | `build_claude_cmd(settings_out: Path, allow_json: str, hooks_json_file: Path, cwd: str, *add_dirs: str) -> str` | `str` | Writes `settings_out` JSON file by splicing `allow_json` and contents of `hooks_json_file`; returns the resolved `claude --settings ... --add-dir ...` command string (no trailing newline). |

### `build_claude_cmd` - per-function behavior notes

Inputs:
- `settings_out`: absolute path; the function overwrites the file at this path.
- `allow_json`: string already containing a JSON-array literal of permissions (caller produces it via `expand_permissions.py`).
- `hooks_json_file`: absolute path to a file whose contents are a JSON object literal suitable as the `"hooks"` value in `settings.json`.
- `cwd`: string, the launcher cwd; becomes the FIRST `--add-dir` argument.
- `*add_dirs`: zero or more extra `--add-dir` paths, appended in order.

Side effects:
1. Reads the entire contents of `hooks_json_file` into a buffer.
2. Writes a new file at `settings_out` with body:
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
   - `allow_json` and the contents of `hooks_json_file` are spliced verbatim. The function does NOT validate or re-serialize them (no `json.dumps`).

Return:
- A single string: `claude --settings '<settings_out>' --add-dir '<cwd>' --add-dir '<add_dir1>' ...`
- Each path wrapped in single quotes literally (no escaping of embedded quotes; matches bash).
- No trailing newline (caller `print()`s if newline desired).

Error behavior:
- Bash version is silent on missing `hooks_json_file` (latent bug; produces malformed `settings.json`). Python port intentionally diverges: raises `FileNotFoundError`. Callers run under `set -euo pipefail`, so non-zero propagation is correct.

External commands invoked: none (replaces bash `cat` and `printf` with native Python). No env vars consumed. No subprocess forks. No tmux, locks, signals.

## Callers needing import-site updates

| Caller | Line | Current invocation | Action |
| --- | --- | --- | --- |
| `skills/jot/scripts/jot.sh` | 125 | `. claude-launcher.sh; build_claude_cmd ...` | Migrate-together: this caller is itself slated for migration; update its Python form to `from common.scripts.claude_launcher_lib import build_claude_cmd`. If `jot.sh` remains bash when this script's GREEN lands, install transitional shim instead. |
| `skills/debate/scripts/debate.sh` | 160 | `. claude-launcher.sh; build_claude_cmd ...` | Migrate-together or transitional shim, same logic as `jot.sh`. |
| `skills/todo/scripts/todo-launcher.sh` | 29 | `. claude-launcher.sh; build_claude_cmd ...` | Migrate-together or transitional shim, same logic. |
| `skills/debate/scripts/OLD_DISCARD/debate.sh` | 94 | dead code | Ignore. |
| `common/scripts/plate/spawn_summary_agent.py` | 102 | doc comment only; not a runtime caller | No action. |

If any of the three live bash callers has not migrated when this `.sh` is being deleted, replace `claude-launcher.sh` body with a 2-line transitional shim (mark `[s]`):
```bash
build_claude_cmd() {
  python3 -c 'from common.scripts.claude_launcher_lib import build_claude_cmd; import sys; print(build_claude_cmd(*sys.argv[1:]))' "$@"
}
```
Delete the shim once the last bash caller migrates.

## RED tests (`tests/test_claude_launcher.py`)

Every test asserts on return value or file-system mutation. No test captures stdout.

1. `test_settings_file_is_written_with_permissions_allow_field` - given `allow_json='["A","B"]'` and an empty hooks file `{}`, the written `settings.json` parses as JSON whose `.permissions.allow == ["A","B"]`.
2. `test_settings_file_is_written_with_hooks_field_spliced_verbatim` - given a hooks file containing `{"SessionStart":[{"hooks":[{"type":"command","command":"foo"}]}]}`, the written settings file's `.hooks.SessionStart[0].hooks[0].command == "foo"`.
3. `test_settings_file_overwrites_existing_target` - pre-create `settings_out` with sentinel bytes; call function; assert sentinel bytes are gone and new JSON parses cleanly.
4. `test_returned_string_starts_with_claude_settings_flag` - return value begins `claude --settings '<abs_settings_out>'`.
5. `test_returned_string_includes_cwd_as_first_add_dir` - first `--add-dir` argument in the return value equals the `cwd` positional, in single quotes.
6. `test_returned_string_appends_each_extra_add_dir_in_order` - `cwd='/a'` plus `extras=('/b','/c')` produces a return value ending `--add-dir '/a' --add-dir '/b' --add-dir '/c'`.
7. `test_returned_string_with_zero_extra_add_dirs` - passing only `cwd` yields exactly one `--add-dir` flag in the return string.
8. `test_paths_with_spaces_are_wrapped_in_single_quotes_literally` - `cwd='/tmp/path with space'` round-trips inside single quotes (matching bash; no embedded-quote escaping).
9. `test_allow_json_string_is_spliced_verbatim_not_re_encoded` - `allow_json='[ "X" , "Y" ]'` (deliberately weird whitespace) appears byte-for-byte inside the written settings file's `"allow":` slot. Proves no `json.dumps` re-serialization.
10. `test_hooks_json_file_contents_are_spliced_verbatim` - write a hooks file with deliberate whitespace padding; assert the same bytes appear inside `settings_out` after the `"hooks":` key.
11. `test_missing_hooks_json_file_raises_file_not_found` - non-existent `hooks_json_file` raises `FileNotFoundError`. Documented intentional divergence from bash silent-malformed behavior.
12. `test_returned_string_has_no_trailing_newline` - return value does not end in `\n`; caller is responsible for printing if newline output is desired.
13. `test_settings_file_has_trailing_newline` - bytes written to `settings_out` end with exactly one `\n`, matching the bash heredoc.
14. `test_golden_file_parse_equivalent_to_bash_original` - fixture: capture pre-migration bash output for one canonical input; assert post-migration `json.load(settings_out) == json.load(golden_file)`.

## GREEN fill order (callees before callers)

`build_claude_cmd` has no internal helpers; it is a single leaf function. Implementation order:

1. Stub written in step 2 of the template (`print("TODO: build_claude_cmd")`); module imports clean.
2. Implement in one body change. Iterate per-test until all 14 RED tests flip GREEN.

If during implementation a private helper emerges (e.g. `_format_settings_json` or `_quote_path`), implement that helper FIRST with its own RED test, then `build_claude_cmd` last.

## Numbered TODO list (mirrors migration template steps 0-8)

0. Mark `common/scripts/claude-launcher.sh` as `[~]` in `MIGRATION_TO_PYTHON.md` when implementation begins.
1. Inventory: function table above is the spine. One function: `build_claude_cmd`.
2. Scaffold `common/scripts/claude_launcher_lib.py` containing `build_claude_cmd` with typed signature and body `print("TODO: build_claude_cmd")`. Confirm `python3 -c 'from common.scripts.claude_launcher_lib import build_claude_cmd'` succeeds.
3. Write the 14 RED tests in `tests/test_claude_launcher.py`. Each asserts on return value or file mutation; none captures stdout.
4. Run `pytest tests/test_claude_launcher.py -v`. Confirm all 14 fail on assertion (not on import).
5. GREEN: implement `build_claude_cmd` body. Use raw f-string interpolation for `allow_json` and `hooks_contents` (no `json.dumps`). Quote each path with literal single quotes. Run pytest after each substantive edit; commit per cluster.
6. Update callers per "Callers needing import-site updates" table. Python callers: direct `import`. Bash callers still in flight: install the 2-line transitional shim and mark the file `[s]`.
7. Delete `common/scripts/claude-launcher.sh` once the last bash caller migrates. If a transitional shim is in place, delete it then. Mark `[x]`.
8. End-to-end verify: run each live caller (`jot.sh`, `debate.sh`, `todo-launcher.sh`) on a sandbox repo. Capture pre-migration `settings.json` from `main` and post-migration from this branch. `jq -S . pre.json > pre.norm && jq -S . post.json > post.norm && diff pre.norm post.norm` must be empty. Confirm `claude --settings <generated> --print 'noop'` exits 0. Only then mark `[x]` and update `MIGRATION_TO_PYTHON.md`.

## Risk callouts

1. **Quoting fidelity**: bash wraps every path in single quotes without escaping. If a caller passes a path containing a single quote (controlled inputs make this unlikely), both bash and the Python port emit broken shell. Match bash exactly to avoid drift; document in module docstring.
2. **Verbatim splicing**: the bash heredoc does not parse `allow_json` or hooks contents. Python port must NOT call `json.dumps` on them or formatting diverges from existing golden inputs.
3. **Trailing newline divergence**: bash uses `printf '%s\n'`. Library returns no trailing newline; tests #12 and #13 enforce this. Callers wanting bash-identical bytes call `print()`.
4. **`set -e` interaction**: all three callers run under `set -euo pipefail`. The bash function silently produces malformed JSON on missing hooks file; Python raises `FileNotFoundError`, newly triggering `set -e` aborts. Verify desired and document the behavior change in the migration commit.
5. **Race conditions**: none. Idempotent; fresh `settings_out` per invocation under per-invocation tmpdir.
6. **Platform quirks**: none. Pure file IO + string formatting.
