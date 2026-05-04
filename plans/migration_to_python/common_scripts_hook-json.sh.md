# Migrate `common/scripts/hook-json.sh` to Python

## Source

- File: `common/scripts/hook-json.sh`
- Size: ~40 lines bash, leaf shared library, no `.sh` deps.
- Sourced by every consumer via `. "${CLAUDE_PLUGIN_ROOT}/common/scripts/hook-json.sh"`. No subprocess invocations.
- Functions emit Claude Code hook protocol JSON to stdout. Under the new return-don't-echo rule, the migrated functions RETURN the JSON dict (or string); a thin caller in `scripts/jot-plugin-orchestrator.py` is responsible for writing to stdout.

## Target

- Module: `common/scripts/hook_json_lib.py`
- No `_cli.py`. No bash shim. No transitional `.sh`. The `.sh` file is deleted in step 7 once all callers import the Python module directly.

## Function table (spine of the plan)

| name | Python signature (typed) | return type | one-line behavior note |
|---|---|---|---|
| `emit_block` | `emit_block(reason: str) -> dict[str, str]` | `dict` | Returns `{"decision": "block", "reason": reason}`. Caller serializes via `json.dumps(..., separators=(",", ":"), ensure_ascii=False)` and writes to stdout. Was: bash `emit_block` echoed JSON; now returns the dict so callers control the I/O boundary. |
| `_install_hint` | `_install_hint(cmd: str) -> str` | `str` | Pure mapping: `jq` -> `"jq (brew install jq)"`, `python3` -> `"python3 (brew install python)"`, `tmux` -> `"tmux (brew install tmux)"`, `claude` -> `"claude (https://claude.com/claude-code)"`, else returns `cmd` unchanged. Was: bash `_hookjson_install_hint` (renamed: drop `_hookjson` prefix; module namespace replaces it). |
| `check_requirements` | `check_requirements(prefix: str, commands: Sequence[str]) -> dict[str, str] \| None` | `dict \| None` | Probes each command via `shutil.which`. All present: returns `None`. Any missing: returns the same dict shape as `emit_block` with reason `"<prefix> needs: <comma-joined hints> - install and retry."`. Was: bash version called `emit_block` then `exit 0`; that I/O + termination is now the caller's responsibility. The hyphen replaces the legacy em-dash per repo style; the byte-exact em-dash contract is dropped (see Risk 3). |

## Callers needing import-site updates

Active sourcing consumers (verified by `grep -rn 'hook-json'`):

1. `skills/jot/scripts/jot.sh:122`
2. `skills/plate/scripts/plate.sh:19`
3. `skills/todo/scripts/todo.sh:20`
4. `skills/todo-launcher/scripts/todo-launcher.sh:26`
5. `skills/todo-list/scripts/todo-list.sh:14`
6. `skills/debate/scripts/debate.sh:157`
7. `skills/debate/tests/upfront-instructions-test.sh:48`

Plus the hook entry: `scripts/jot-plugin-orchestrator.py` will import `hook_json_lib` directly and own the stdout write + exit-code path that was previously inside `check_requirements`.

These bash callers cannot import Python directly. Two paths:

- **Preferred:** migrate each caller to Python in its own plan; the import-site update happens there.
- **Mid-migration only:** if a bash caller still exists when this plan reaches step 6, replace its `emit_block` / `check_requirements` call sites with `python3 -c 'from hook_json_lib import ...; ...'` inline, keeping the bash file otherwise intact. Mark the bash caller `[s]` until its own migration completes. The `.sh` file `hook-json.sh` itself is still deleted.

Inactive / discardable (do not block migration):

- `skills/debate/scripts/OLD_DISCARD/debate.sh:91`
- `plans/debate-resume.md:496`, `plans/plate-status-2026-04-14.md:82`, `plans/jot-generalizing-refactor.md:40,120,121`
- `CHANGELOG.md`, `README.md`, `common/scripts/USAGE.md`

## Hook protocol invariants (preserved)

- Output (when serialized by the caller) is a single object on a single line followed by `\n`.
- No leading whitespace; no trailing whitespace before the newline.
- `decision` is always literal `"block"`.
- Only `decision` and `reason` keys.
- Field order: `decision` first, `reason` second. Locked by Python dict insertion order plus `json.dumps`.
- `ensure_ascii=False` to match `jq`'s raw-UTF-8 default.

## RED tests (file: `tests/test_hook_json_lib.py`)

Tests assert on return values and `shutil.which` monkeypatches. No stdout capture. The orchestrator caller's stdout write is tested separately in `tests/test_jot_plugin_orchestrator.py`.

### `emit_block` group

1. `emit_block_returns_block_dict`: `emit_block("hello") == {"decision": "block", "reason": "hello"}`.
2. `emit_block_field_order_decision_first`: iterate keys of returned dict; first key is `"decision"`.
3. `emit_block_preserves_quotes_in_reason`: `emit_block('say "hi"')["reason"] == 'say "hi"'` (no pre-escaping; serialization is the caller's job).
4. `emit_block_preserves_backslash`: `emit_block(r"a\b")["reason"] == r"a\b"`.
5. `emit_block_preserves_unicode`: `emit_block("café naïve")["reason"] == "café naïve"`.
6. `emit_block_preserves_newline`: `emit_block("line1\nline2")["reason"] == "line1\nline2"`.
7. `emit_block_empty_string`: `emit_block("") == {"decision": "block", "reason": ""}`.
8. `emit_block_only_two_keys`: `set(emit_block("x").keys()) == {"decision", "reason"}`.

### `_install_hint` group

9. `install_hint_jq`: `_install_hint("jq") == "jq (brew install jq)"`.
10. `install_hint_python3`: `_install_hint("python3") == "python3 (brew install python)"`.
11. `install_hint_tmux`: `_install_hint("tmux") == "tmux (brew install tmux)"`.
12. `install_hint_claude`: `_install_hint("claude") == "claude (https://claude.com/claude-code)"`.
13. `install_hint_unknown_passthrough`: `_install_hint("foo") == "foo"`.

### `check_requirements` group

14. `check_requirements_all_present_returns_none`: monkeypatch `shutil.which` to return a path for all queried names; `check_requirements("/test", ["jq"]) is None`.
15. `check_requirements_one_missing_returns_block`: monkeypatch `shutil.which("jq")` to None; result equals `{"decision": "block", "reason": "/test needs: jq (brew install jq) - install and retry."}`.
16. `check_requirements_multiple_missing_arg_order`: missing `["jq", "tmux"]`; reason equals `"/test needs: jq (brew install jq), tmux (brew install tmux) - install and retry."`.
17. `check_requirements_unknown_cmd_passthrough`: missing `["foobar"]`; reason equals `"/test needs: foobar - install and retry."`.
18. `check_requirements_prefix_verbatim`: prefix `/jot` interpolated unchanged.
19. `check_requirements_uses_ascii_hyphen`: assert literal `" - install and retry."` (ASCII hyphen, two spaces). No em-dash byte sequence anywhere in returned reason.

### Caller integration (in `tests/test_jot_plugin_orchestrator.py`)

20. `orchestrator_writes_block_dict_as_compact_json`: caller invokes `emit_block`, serializes via `json.dumps(d, separators=(",", ":"), ensure_ascii=False)`, writes to a captured stream. Captured bytes equal `b'{"decision":"block","reason":"hello"}\n'`.
21. `orchestrator_check_requirements_missing_writes_then_exits_zero`: caller invokes `check_requirements`, writes the returned dict to stdout (if not `None`), and exits 0. Verifies the parent-script-exits-0 contract now lives in Python.

## Confirm RED

After scaffold (step 2) every function body is `print("TODO: <name>")` and the declared return is missing, so tests 1-19 fail on assertion (not import). Tests 20-21 fail because the orchestrator caller has not yet been wired.

## GREEN order (callees-first, bottom-up)

1. `_install_hint` (no deps). Tests 9-13 flip green.
2. `emit_block` (no deps). Tests 1-8 flip green.
3. `check_requirements` (depends on `_install_hint` and the dict shape from `emit_block`). Tests 14-19 flip green.
4. Wire the orchestrator caller in `scripts/jot-plugin-orchestrator.py`: import `hook_json_lib`, write returned dict via `json.dumps(..., separators=(",", ":"), ensure_ascii=False)` plus `\n`, exit 0 when `check_requirements` returns a dict. Tests 20-21 flip green.

Commit per function. Run `pytest tests/test_hook_json_lib.py tests/test_jot_plugin_orchestrator.py -v` after each.

## Update callers (step 6)

For each of the seven active sourcing consumers, the corresponding migration plan owns its own import-site update. If a consumer is still bash when this plan finishes, replace its in-line use of `emit_block` / `check_requirements` with a `python3 -c '...'` inline invocation that imports `hook_json_lib`, serializes the returned dict, and exits 0 on a block. Track each via `[s]` in `MIGRATION_TO_PYTHON.md` until its own migration plan completes.

## Delete (step 7)

When no caller sources `hook-json.sh`, `git rm common/scripts/hook-json.sh`. No transitional shim survives at this path. The migration is fully done; no `[s]` for `hook-json.sh` itself.

## Verify end-to-end (step 8)

1. `pytest tests/test_hook_json_lib.py tests/test_jot_plugin_orchestrator.py -v` -> all green.
2. **Baseline capture (pre-migration), saved under `tests/fixtures/hook_json_baseline/`:**
   - `bash -c '. common/scripts/hook-json.sh; emit_block "hi"' > emit_simple.json`
   - Variants: empty reason, reason with `"`, reason with `\\`, reason with newline, multibyte reason.
   - `bash -c '. common/scripts/hook-json.sh; check_requirements /test definitely-missing-cmd' > missing_one.json; echo $? > missing_one.exit`
   - Variant: two missing.
3. **Post-migration diff:** Python caller output matches baseline EXCEPT for the em-dash -> hyphen substitution (Risk 3). Diff must show only that single byte-sequence change in the `check_requirements` outputs; `emit_block` outputs must be byte-equal.
4. Live `/jot` invocation: `echo '{"prompt":"/jot foo"}' | bash skills/jot/scripts/jot.sh`. Behavior matches pre-migration recording.
5. Live `/plate` invocation via `bash skills/plate/scripts/plate.sh`.
6. Live `/debate` invocation via `bash skills/debate/scripts/debate.sh`.
7. Force missing-dep path with PATH narrowed to exclude `jq`. User sees the canonical block JSON with the ASCII-hyphen install hint.
8. `pytest tests/ -v` (full suite) plus `bash skills/debate/tests/upfront-instructions-test.sh`. Both pass.
9. Hook protocol parser smoke: pipe orchestrator output into `python3 -c 'import json,sys; assert json.load(sys.stdin)=={"decision":"block","reason":"x"}'`.

## Risk callouts

1. **Byte-exact JSON shape is load-bearing.** Claude Code parses hook output strictly. Field order, whitespace, escaping must match. Tests 1-8 plus baseline diff (verify step 3) lock this. `json.dumps(separators=(",", ":"), ensure_ascii=False)` matches `jq`'s compact form.
2. **`exit 0` from sourced bash function.** Original bash terminated the parent script from inside `check_requirements`. Python `check_requirements` cannot do that and should not try; it returns the dict. The orchestrator caller owns the exit. Test 21 enforces.
3. **Em-dash -> ASCII hyphen.** Prior plan preserved U+2014 byte-exact. The new repo style rule (`feedback_no_emdash`) forbids em-dash anywhere. The migrated reason uses `" - install and retry."` (ASCII). Test 19 enforces. Verification step 3 expects this single intentional diff against the baseline; reviewers must confirm no downstream consumer parses the em-dash byte sequence.
4. **Unicode escaping divergence.** `jq` emits raw UTF-8 by default; Python `json.dumps` defaults to `ensure_ascii=True`. The orchestrator caller MUST pass `ensure_ascii=False`. Test 20 plus a multibyte baseline lock this.
5. **`_install_hint` is private.** Underscore-prefixed; not part of the public API. Internal use only.
6. **Multiple skill scripts source this concurrently.** Was idempotent in bash. Python module-level imports are also idempotent; `sys.modules` cache handles re-imports.
7. **`upfront-instructions-test.sh` is itself a bash test.** Either migrate it in its own plan, or use the inline `python3 -c '...'` pattern in step 6.

## Numbered TODO list (template steps 0-8)

0. Create this numbered TODO list (this section).
1. Mark `common/scripts/hook-json.sh` as `[i]` in `MIGRATION_TO_PYTHON.md`.
2. Plan written here. Mark entry as `[p]` in `MIGRATION_TO_PYTHON.md`.
3. Capture pre-migration byte baselines per Verification step 2. Commit fixtures under `tests/fixtures/hook_json_baseline/`.
4. Scaffold `common/scripts/hook_json_lib.py` with three functions, each body `print("TODO: <name>")`, all with typed signatures and return types per the function table. Module imports cleanly.
5. Write RED tests in `tests/test_hook_json_lib.py` (tests 1-19) and add tests 20-21 to `tests/test_jot_plugin_orchestrator.py`. Run pytest. Confirm RED for the expected reason (assertion failure, not import error).
6. Mark `common/scripts/hook-json.sh` as `[~]`.
7. GREEN one body at a time, callees-first: `_install_hint` -> `emit_block` -> `check_requirements`. Commit per body; rerun pytest after each.
8. Wire orchestrator caller in `scripts/jot-plugin-orchestrator.py`. Tests 20-21 flip green.
9. Update each of the seven active sourcing consumers per "Update callers" section. Mark each `[s]` if it remains bash; their own migration plans flip them to `[x]`.
10. `git rm common/scripts/hook-json.sh`. Run live verifications (step 8 above). Mark entry `[x]` in `MIGRATION_TO_PYTHON.md`.
