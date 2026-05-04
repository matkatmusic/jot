# Migrate `common/scripts/hook-json.sh` to Python

## Source

- File: `common/scripts/hook-json.sh`
- Class: `(sourced)`. Every consumer pulls it via `. "${CLAUDE_PLUGIN_ROOT}/common/scripts/hook-json.sh"` and then calls bash functions `emit_block` and `check_requirements`. No subprocess invocations exist.
- Size: ~40 lines bash.
- Position in dependency graph: leaf shared library; no `.sh` deps. The `(.py helpers) - inline python3 for emit_block JSON encoding` annotation in `MIGRATION_TO_PYTHON.md` line 99 refers to the planned helper, not existing code. Current source uses `jq` first with a hand-rolled `printf` fallback (no inline `python3 -c`).

### Callers (verified by `grep -rn 'hook-json'`)

Active sourcing consumers (must keep `emit_block` / `check_requirements` callable as bash functions):

1. `skills/jot/scripts/jot.sh:122`
2. `skills/plate/scripts/plate.sh:19`
3. `skills/todo/scripts/todo.sh:20`
4. `skills/todo/scripts/todo-launcher.sh:26`
5. `skills/todo-list/scripts/todo-list.sh:14`
6. `skills/debate/scripts/debate.sh:157`
7. `skills/debate/tests/upfront-instructions-test.sh:48`

Inactive / discardable (do NOT block migration):

- `skills/debate/scripts/OLD_DISCARD/debate.sh:91` (already discarded path)
- `plans/debate-resume.md:496`, `plans/plate-status-2026-04-14.md:82`, `plans/jot-generalizing-refactor.md:40,120,121` (documentation only)
- `CHANGELOG.md`, `README.md`, `common/scripts/USAGE.md` (documentation only)

Python-side: `scripts/jot-plugin-orchestrator.py` does its own `json.loads` / `json.dumps` for hook protocol forwarding and never sources `hook-json.sh`. It is the closest reference for shape semantics but has no functional dependency on this file.

## Behavior spec (exact contracts)

### Function: `emit_block <reason>`

- Writes a single JSON object plus trailing newline to **stdout**.
- Schema (Claude Code hook protocol, `decision: "block"` form):
  ```json
  {"decision":"block","reason":"<reason text>"}
  ```
- Field order in current bash output: `decision` first, `reason` second (matches `jq -n --arg r "$reason" '{decision:"block", reason:$r}'`).
- Fallback path (no `jq`) uses `printf` with manual escaping: backslashes first, then double-quotes. No other characters are escaped (newlines, control chars, unicode pass through raw - this is a known limitation but is the current contract).
- Exit code: 0. Function does not exit; caller controls flow.
- Side effects: stdout only. No stderr writes.

### Function: `_hookjson_install_hint <cmd>` (private)

Pure mapping. Returns one-line install hint via `echo`:

- `jq` -> `jq (brew install jq)`
- `python3` -> `python3 (brew install python)`
- `tmux` -> `tmux (brew install tmux)`
- `claude` -> `claude (https://claude.com/claude-code)`
- any other name -> the name unchanged.

### Function: `check_requirements <prefix> <cmd...>`

- Probes each `<cmd>` via `command -v`.
- If all present: `return 0`. Does NOT exit; caller continues.
- If any missing:
  1. Builds a comma-space joined list of `_hookjson_install_hint` results in argument order.
  2. Calls `emit_block "<prefix> needs: <list> EM-DASH install and retry."` where `EM-DASH` is the literal U+2014 byte sequence in the existing source (UTF-8: `0xE2 0x80 0x94`). Byte-exact preservation required for hook output stability.
  3. `exit 0` (NOT non-zero; the hook protocol expects exit 0 + decision JSON to surface a block to the user).
- Stderr: silent. Stdout: exactly the `emit_block` JSON line.

### Hook protocol invariants

- Output is a single object on a single line followed by `\n`.
- No leading whitespace; no trailing whitespace before the newline.
- `decision` is always literal `"block"` (not `"approve"` / `"ask"`).
- Only `decision` and `reason` keys. No `permissionDecision`, `continue`, `stopReason`, etc. Those exist in the broader Claude Code hook protocol but this helper does not emit them.

## Target Python module path

Library: `common/scripts/hook_json_lib.py`

- Pure functions:
  - `emit_block(reason: str, *, stream=sys.stdout) -> None`
  - `check_requirements(prefix: str, commands: Sequence[str], *, stream=sys.stdout, exit_fn=sys.exit) -> None`
  - `_install_hint(cmd: str) -> str`
- All JSON via `json.dumps({...}, separators=(",", ":"), ensure_ascii=False)` to match `jq` compact form (no internal spaces, raw UTF-8). Verify against captured bash baseline.
- `check_requirements` accepts `exit_fn` injection so tests can assert exit-0 without terminating pytest.

CLI shim: `common/scripts/hook_json_cli.py` (argparse dispatcher) with subcommands:

- `emit-block --reason TEXT` -> prints JSON, exit 0.
- `check-requirements --prefix TEXT -- CMD [CMD ...]` -> if missing: prints block JSON, exits with sentinel `42`. If all present: exits `0` with no output.
- `install-hint CMD` -> prints hint string, exit 0.

## `_cli.py` shim spec (bash to python bridge)

The bash file `common/scripts/hook-json.sh` MUST keep the function names sourceable. The original `check_requirements` calls `exit 0` from inside the function (terminates the whole sourced parent script). A python subprocess cannot terminate the bash parent, so we use a sentinel exit code.

Final `.sh` body:

```bash
# hook-json.sh - shim. Real logic lives in hook_json_lib.py via hook_json_cli.py.
_HOOKJSON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

emit_block() {
  python3 "$_HOOKJSON_DIR/hook_json_cli.py" emit-block --reason "$1"
}

check_requirements() {
  local prefix="$1"; shift
  python3 "$_HOOKJSON_DIR/hook_json_cli.py" check-requirements --prefix "$prefix" -- "$@"
  local rc=$?
  case $rc in
    0)  return 0 ;;       # all deps present
    42) exit 0 ;;         # missing deps; JSON already emitted; terminate parent script
    *)  return $rc ;;     # unexpected python failure; propagate
  esac
}
```

This preserves byte-exact stdout AND the parent-script-exits-0 contract.

## RED test scenarios (pytest)

File: `tests/test_hook_json.py`. Each test starts as a plain-English scenario comment, then a failing assertion.

### `emit_block` group

1. `emit_block_simple_reason_exact_bytes`: `emit_block("hello")` writes exactly `b'{"decision":"block","reason":"hello"}\n'` to the captured stream. Byte-equality assertion (no JSON re-parse) to lock field order and absence of internal spaces.
2. `emit_block_field_order_decision_first`: re-parse output and assert ordered keys via `json.JSONDecoder(object_pairs_hook=list)`; first key must be `"decision"`.
3. `emit_block_escapes_double_quote`: `emit_block('say "hi"')` round-trips: parsed `reason` equals `'say "hi"'` and raw bytes contain `\"`.
4. `emit_block_escapes_backslash`: `emit_block(r'a\b')` round-trips; raw bytes contain `\\`.
5. `emit_block_preserves_unicode`: `emit_block("cafe naive")` plus a multibyte character; parsed reason equals input. Verifies `ensure_ascii=False` matches `jq` default.
6. `emit_block_newline_in_reason_round_trips`: `emit_block("line1\nline2")` parsed reason equals input; raw contains `\n` (escaped).
7. `emit_block_empty_string`: `emit_block("")` -> `{"decision":"block","reason":""}\n`.
8. `emit_block_no_stderr`: captures stderr and asserts empty.
9. `emit_block_writes_single_line`: exactly one `\n` in output, at the end.

### `_install_hint` group

10. `install_hint_jq_canonical`: returns `"jq (brew install jq)"`.
11. `install_hint_python3_canonical`: returns `"python3 (brew install python)"`.
12. `install_hint_tmux_canonical`: returns `"tmux (brew install tmux)"`.
13. `install_hint_claude_canonical`: returns `"claude (https://claude.com/claude-code)"`.
14. `install_hint_unknown_passthrough`: `_install_hint("foo")` returns `"foo"`.

### `check_requirements` group

15. `check_requirements_all_present_returns_zero_silent`: given commands that all exist (use `["python3"]` plus monkeypatched probe), produces no stdout; exit_fn called with `0` OR not called at all (function returns).
16. `check_requirements_one_missing_emits_block_with_hint`: monkeypatch `shutil.which` so `jq` returns None. Output is exactly `{"decision":"block","reason":"<prefix> needs: jq (brew install jq) <EMDASH> install and retry."}\n` where `<EMDASH>` is U+2014 in UTF-8. Exit_fn called with sentinel (CLI: `42`; library: caller-supplied default).
17. `check_requirements_multiple_missing_joined_in_arg_order`: missing `[jq, tmux]` produces `"... needs: jq (brew install jq), tmux (brew install tmux) <EMDASH> install and retry."`. Order matches argument order.
18. `check_requirements_unknown_cmd_listed_by_name`: missing `[foobar]` produces `"... needs: foobar <EMDASH> install and retry."`.
19. `check_requirements_prefix_used_verbatim`: prefix `/jot` is interpolated as-is. Only the surrounding JSON encoding handles escapes.
20. `check_requirements_em_dash_byte_sequence_preserved`: assert raw output contains the byte sequence `b'\xe2\x80\x94'`. Hook-protocol byte-exactness test.

### CLI shim group (`hook_json_cli.py`)

21. `cli_emit_block_subcommand_exit0`: `python3 hook_json_cli.py emit-block --reason hi` -> stdout exact JSON, exit 0.
22. `cli_check_requirements_all_present_exit0`: exit 0; no stdout.
23. `cli_check_requirements_missing_exit42`: missing deps -> exit code `42`; JSON on stdout. Locks the sentinel contract used by the bash wrapper.
24. `cli_install_hint_subcommand`: `install-hint jq` -> `jq (brew install jq)\n`; exit 0.

### Bash-shim integration group (subprocess tests)

25. `bash_emit_block_via_shim_byte_exact`: source `hook-json.sh` in a fresh bash subshell, call `emit_block "hi"`, capture stdout, assert exact bytes (validates the python bridge is invisible to consumers).
26. `bash_check_requirements_present_no_exit`: bash script that sources, calls `check_requirements /test python3`, then echoes `OK`. Output ends with `OK` (function returned, did not exit).
27. `bash_check_requirements_missing_exits_zero_with_json`: bash script sources, calls `check_requirements /test definitely-not-a-command`, then echoes `SHOULD_NOT_PRINT`. Asserts: exit code 0, stdout contains the block JSON, stdout does NOT contain `SHOULD_NOT_PRINT`.
28. `bash_real_consumer_jot_sh_still_works`: minimal smoke. Invoke `bash skills/jot/scripts/jot.sh --help` (or its lightest path) with the new shim in place; assert no syntax errors and exit code matches pre-migration baseline.

## Risk callouts

1. **Byte-exact JSON shape is load-bearing.** Claude Code parses hook output strictly. Any change to key order, whitespace, or escaping could silently change UI behavior. Tests 1-9 plus 25 lock this.
2. **`exit` from sourced function.** Original bash exits the parent script from inside `check_requirements`. Python subprocess cannot. The sentinel-42 bridge is a behavior-preserving workaround; if a future caller depends on parent-exit semantics across pipes, integration test 27 must catch divergence.
3. **Em-dash preservation.** Repo style rules forbid em-dash in new code, but the existing user-visible string contains one. Migration MUST preserve the byte sequence to avoid changing the displayed message hash. Test 20 enforces. Source it from a constant `_EMDASH = "—"` so reviewers can spot it.
4. **Unicode escaping divergence.** `jq` emits raw UTF-8 by default; Python `json.dumps` defaults to `ensure_ascii=True`. Pin `ensure_ascii=False` and verify against a captured baseline from the current bash for at least one non-ASCII reason.
5. **`python3` startup cost on every call.** `emit_block` is invoked at most once per hook invocation, so ~50ms overhead is acceptable. `check_requirements` is also one-shot. No concern.
6. **`_hookjson_install_hint` is private.** Prefixed with `_` and not documented as public. Safe to drop from the bash shim entirely (only used internally by `check_requirements`). Library `_install_hint` should remain underscore-prefixed.
7. **Multiple skill scripts source this concurrently.** Idempotent. No shared state beyond function definitions. Re-sourcing is safe.
8. **`upfront-instructions-test.sh` is a test file.** Sourcing the shim from a bash test must still work. Integration test 28 verifies a representative consumer.

## Verification plan (live hook invocations)

1. `pytest tests/test_hook_json.py -v` -> all 28 scenarios GREEN.
2. **Baseline capture (pre-migration)**: before changing the `.sh`, run from the original bash:
   - `bash -c '. common/scripts/hook-json.sh; emit_block "hi"' > tests/fixtures/hook_json_baseline/emit_simple.json`
   - Repeat for: empty reason, reason with `"`, reason with `\\`, reason with newline, multibyte reason.
   - `bash -c '. common/scripts/hook-json.sh; check_requirements /test definitely-missing-cmd' > tests/fixtures/hook_json_baseline/missing_one.json; echo $? > tests/fixtures/hook_json_baseline/missing_one.exit`
   - Repeat for: two missing, unknown cmd.
3. **Post-migration diff**: re-run identical commands. `diff` against fixtures must be empty (stdout AND exit code).
4. **Real hook invocation `/jot`**: `echo '{"prompt":"/jot foo"}' | bash skills/jot/scripts/jot.sh`. Confirm orchestrator behavior matches pre-migration recording.
5. **Real hook invocation `/plate`**: same pattern via `bash skills/plate/scripts/plate.sh`.
6. **Real hook invocation `/debate`**: `bash skills/debate/scripts/debate.sh`.
7. **Force missing-dep path**: invoke with PATH narrowed to exclude `jq`. Assert the user sees the canonical block JSON with the em-dash hint (byte-exact match against fixture).
8. **Existing test suite regression**: `pytest tests/ -v` (full suite) plus `bash skills/debate/tests/upfront-instructions-test.sh`. Both must pass unchanged.
9. **Hook protocol parser smoke**: pipe `emit_block` output into `python3 -c 'import json,sys; assert json.load(sys.stdin)=={"decision":"block","reason":"x"}'` to confirm parser compatibility.

## Numbered TODO list (template steps 0-8)

0. Create this numbered TODO list (this section).
1. Mark `common/scripts/hook-json.sh` as `[i]` in `MIGRATION_TO_PYTHON.md` line 97.
2. Plan written here. Mark entry as `[p]` in `MIGRATION_TO_PYTHON.md`.
3. Capture pre-migration byte baselines per Verification step 2. Commit fixtures under `tests/fixtures/hook_json_baseline/` for permanent regression coverage.
4. Write RED tests in `tests/test_hook_json.py` covering all 28 scenarios above. Run pytest. All RED (fail with `ModuleNotFoundError: hook_json_lib` or similar).
5. Mark `common/scripts/hook-json.sh` as `[~]` in `MIGRATION_TO_PYTHON.md`.
6. Implement `common/scripts/hook_json_lib.py` (pure functions). Run pytest. Library-only tests GREEN; CLI plus bash-shim tests still RED.
7. Implement `common/scripts/hook_json_cli.py` argparse dispatcher with `emit-block`, `check-requirements` (sentinel-42 on missing), `install-hint` subcommands. Run pytest. CLI tests GREEN.
8. Replace the `common/scripts/hook-json.sh` body with the bash shim (function definitions delegating to `hook_json_cli.py` with the 42-sentinel mapping). Run full pytest plus integration tests plus the seven sourcing consumers' smoke tests plus post-migration baseline diff. All must be byte-equal to baseline. Mark entry `[x]` in `MIGRATION_TO_PYTHON.md`.

