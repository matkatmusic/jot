# Migrate `common/scripts/platform.sh` to Python

## Source

- File: `common/scripts/platform.sh`
- Size: 91 lines bash
- Target: `common/scripts/platform_lib.py` (single module; no `_cli.py`, no shim)
- Sourced dependencies (will be reimplemented inline, NOT ported as prerequisites):
  - `silencers.sh` (`hide_errors`, `hide_output`) replaced by Python `subprocess` `DEVNULL`
  - `tmux.sh` (`tmux_list_clients`) replaced by direct `subprocess.run(["tmux", "list-clients", "-t", session], ...)`
- External runtime deps: `tmux`, `osascript` (Darwin only)

## Function table (spine)

| name | Python signature | return type | one-line behavior |
|---|---|---|---|
| `spawn_terminal_if_needed` | `spawn_terminal_if_needed(session: str, log_file: str = "/dev/null", log_prefix: str = "tmux", maximize: str = "") -> None` | `None` | If no tmux client attached to `session`, spawn macOS Terminal running `tmux attach -t <session>`; on non-Darwin or missing `osascript`, append advisory line to `log_file`. Never raises (except `ValueError` for empty session). |
| `_tmux_has_attached_clients` | `_tmux_has_attached_clients(session: str) -> bool` | `bool` | True iff `tmux list-clients -t <session>` exits 0 with non-empty stdout. |
| `_render_applescript` | `_render_applescript(session: str, maximize: str) -> str` | `str` | Build the AppleScript body (do-script + optional bounds block) for `osascript` stdin. |
| `_maximize_block` | `_maximize_block(maximize: str) -> str` | `str` | Return AppleScript fragment: full-desktop bounds for `"yes"`, centred 1000x700 for `"compact"`, empty for anything else. |
| `_write_advisory` | `_write_advisory(log_file: str, log_prefix: str, session: str, reason: str) -> None` | `None` | Best-effort append of `"<iso-ts> <prefix>: <reason> attach manually via \`tmux attach -t <session>\`\n"` to `log_file`; swallows `OSError`. |
| `_spawn_osascript` | `_spawn_osascript(script: str) -> None` | `None` | `Popen(["osascript", "-"], stdin=PIPE, stdout=DEVNULL, stderr=DEVNULL)`, write `script`, close stdin, do NOT wait. Replicates bash `&` backgrounding. |

No renames. All bash function names map 1:1; helpers are new private functions extracted from the bash body for testability.

## Callers needing import-site updates

Active sourcing callers (all currently use `. platform.sh; spawn_terminal_if_needed ...`). Each must switch to `from common.scripts.platform_lib import spawn_terminal_if_needed` once migrated, OR get a transitional `[s]` shim if they remain bash:

1. `skills/jot/scripts/jot.sh:123`
2. `skills/debate/scripts/debate.sh:158`
3. `skills/debate/tests/e2e-test.sh:167`
4. `skills/todo/scripts/todo-launcher.sh:31`
5. `common/scripts/plate/spawn_summary_agent.py:37` (Python; currently stores path string; verify shell-out form at impl time, then convert to direct import)

Likely-dead (verify before migration day):

- `skills/plate/scripts/archive/push.sh:29`
- `skills/debate/scripts/OLD_DISCARD/debate.sh:92`

Doc-only mentions (no code change): `README.md`, `CHANGELOG.md`, `MIGRATION_TO_PYTHON.md`, `common/scripts/USAGE.md`.

Per-caller migration policy: since callers 1-4 are themselves `[ ]` in the tracker, this migration drops a transitional `[s]` shim of `platform.sh` (2-line `exec python3 -c '...'`) until those callers migrate. The shim is deleted in the same commit as the last bash caller's migration.

## Per-function notes

### `spawn_terminal_if_needed`

Argument contract:

1. `session` required; empty raises `ValueError("session name required")` (mirrors bash `${1:?...}`).
2. `log_file` default `/dev/null`. Append target on non-Darwin / missing-osascript paths.
3. `log_prefix` default `"tmux"`. Tag prepended to advisory line.
4. `maximize` tri-state: `"yes"` (full desktop), `"compact"` (1000x700 centred), anything else (no resize). Unknown values silently behave like `""` (matches bash `if/elif` no-else).

Algorithm:

1. Validate `session`; raise `ValueError` if empty.
2. If `_tmux_has_attached_clients(session)`: return immediately. Early-return precedes OS branch AND bounds logic; `maximize` only fires on first spawn.
3. Branch on `platform.system()`:
   - `"Darwin"`: if `shutil.which("osascript") is None` -> `_write_advisory(..., "osascript unavailable;")`, return. Else call `_spawn_osascript(_render_applescript(session, maximize))`.
   - else: `_write_advisory(..., "non-Darwin host;")`, return.
4. Return `None` always (except the one `ValueError`). Never propagate `subprocess` / `OSError` from osascript or log writes.

Side effects (what tests assert):

- `_tmux_has_attached_clients` invoked exactly once per call.
- `osascript` Popen invoked 0 or 1 times depending on branch.
- `log_file` content (read back from disk) on advisory branches.
- No call to `.wait()` on the osascript Popen before return (latency contract).

### `_tmux_has_attached_clients`

`subprocess.run(["tmux", "list-clients", "-t", session], capture_output=True, text=True, check=False)`. Return `result.returncode == 0 and result.stdout.strip() != ""`. Verify behavior against `tmux.sh` at impl time: `tmux list-clients -t <missing>` returns rc 1 with empty stdout; `-t <attached>` returns rc 0 with one line per client.

### `_render_applescript`

Returns:

```
if application "Terminal" is running then
  tell application "Terminal" to do script "tmux attach -t {session}"
else
  tell application "Terminal"
    do script "tmux attach -t {session}" in window 1
  end tell
end if{maximize_block}
```

`{session}` interpolated via `str.format` or f-string. `{maximize_block}` is `_maximize_block(maximize)`.

### `_maximize_block`

- `"yes"` returns the Finder-bounds + `set bounds of front window to screenBounds` block.
- `"compact"` returns the centred-rect block with `winW=1000`, `winH=700`.
- anything else returns `""`.

Strings copied verbatim from `platform.sh` lines 45-67.

### `_write_advisory`

```
ts = datetime.datetime.now().isoformat(timespec="seconds")
line = f"{ts} {log_prefix}: {reason} attach manually via `tmux attach -t {session}`\n"
try:
    with open(log_file, "a") as f:
        f.write(line)
except OSError:
    pass
```

`isoformat(timespec="seconds")` is platform-agnostic (replaces `date -Iseconds`, which is missing on macOS <12). Single `write()` of fully-formed line preserves O_APPEND atomicity.

### `_spawn_osascript`

```
proc = subprocess.Popen(
    ["osascript", "-"],
    stdin=subprocess.PIPE,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
proc.stdin.write(script.encode())
proc.stdin.close()
```

Do NOT call `.wait()`, `.communicate()`, or check `.returncode`. Replicates the bash `&`. If we accidentally block, every UserPromptSubmit hook waits on AppleScript (measurable regression - see Verification).

## RED tests

File: `tests/test_platform_lib.py`. Per RED_GREEN_TDD:

- Write tests against the scaffold (`platform_lib.py` with `print("TODO: <fn>")` bodies) that import each function by name.
- Each test is a plain-English scenario comment then a failing assertion.
- All assertions on **return values** or **observable side effects** (file content, `subprocess` mock call args), never on stdout.
- `subprocess.run`, `subprocess.Popen`, `shutil.which` monkeypatched. `platform.system` patched per-test.
- Confirm every test fails for the right reason (assertion failure, not import error). If a test errors on import, fix scaffold not test.

Fixtures:

- `fake_run` - records every `subprocess.run` call (cmd, kwargs).
- `fake_popen` - records `Popen` constructor args and stdin bytes; tracks `.wait` calls.
- `tmp_log` - `tmp_path / "advisory.log"`.

Scenarios (count: 18):

1. `empty_session_raises_value_error` - `spawn_terminal_if_needed(session="")` raises `ValueError`.
2. `attached_client_darwin_returns_without_osascript` - `_tmux_has_attached_clients` mocked True; `platform.system()=="Darwin"`; assert no Popen call recorded.
3. `attached_client_linux_returns_without_advisory` - same, but `system()=="Linux"`; assert log file does NOT exist (early-return precedes OS branch).
4. `unattached_darwin_invokes_osascript_once` - mocked unattached; Darwin; assert exactly one Popen with `argv[0]==["osascript","-"]` and stdin contains `tmux attach -t mysession`.
5. `unattached_darwin_missing_osascript_logs_advisory` - `shutil.which("osascript")` returns `None`; log file gains exactly one line matching `r"\S+ jot: osascript unavailable; attach manually via \x60tmux attach -t mysession\x60\n"`.
6. `unattached_linux_logs_advisory` - `system()=="Linux"`; log file gains `non-Darwin host;` line; no Popen.
7. `default_log_devnull_does_not_raise` - `log_file="/dev/null"` default; no exception, no file created.
8. `unwritable_log_file_swallows_oserror` - `log_file=tmp_path/"missing"/"log"`; function returns normally, no exception.
9. `maximize_yes_renders_full_bounds_block` - Darwin spawn, `maximize="yes"`; Popen stdin contains both `bounds of window of desktop` AND `set bounds of front window to screenBounds`.
10. `maximize_compact_renders_centred_block` - Darwin spawn, `maximize="compact"`; stdin contains `winW to 1000`, `winH to 700`, `(ex - sx - winW) div 2`.
11. `maximize_empty_omits_bounds_block` - Darwin spawn, `maximize=""`; stdin contains `do script "tmux attach -t ...` but NO `bounds` keyword.
12. `maximize_unknown_value_omits_bounds_block` - `maximize="garbage"`; behaves like empty (matches bash if/elif fallthrough).
13. `applescript_includes_running_branch_and_else_branch` - rendered script contains `if application "Terminal" is running then` AND `tell application "Terminal"` else-branch.
14. `default_log_prefix_is_tmux` - Linux call without `log_prefix` kwarg; advisory line begins `<iso> tmux:`.
15. `custom_log_prefix_is_used` - `log_prefix="debate"`; advisory line begins `<iso> debate:`.
16. `advisory_timestamp_is_iso8601_seconds` - first whitespace-delimited token of advisory line parses via `datetime.fromisoformat`.
17. `osascript_popen_is_not_waited` - mock `Popen` records that `.wait` was never called, `.communicate` never called; function returns before AppleScript completes.
18. `tmux_list_clients_invoked_with_correct_args` - `_tmux_has_attached_clients("foo")` calls `subprocess.run(["tmux", "list-clients", "-t", "foo"], ...)` with `check=False` and `capture_output=True`.

Platform parameterization: scenarios 2/3/6 patch `platform.system`; scenario 5 covers Darwin-without-osascript. Scenarios 1, 9-13, 18 are platform-agnostic.

## GREEN order (callees-first)

Per philosophy, implement bottom-up so each commit flips a clear set of tests:

1. `_maximize_block` -> flips scenarios 9, 10, 11, 12.
2. `_render_applescript` -> flips 13 (and supports 4, 9, 10, 11 once `spawn_terminal_if_needed` exists).
3. `_write_advisory` -> flips 14, 15, 16 (called via `spawn_terminal_if_needed` once that exists; until then, test directly).
4. `_spawn_osascript` -> flips 17 (test directly until wired up).
5. `_tmux_has_attached_clients` -> flips 18.
6. `spawn_terminal_if_needed` (orchestrator) -> flips 1, 2, 3, 4, 5, 6, 7, 8.

After each commit run `pytest tests/test_platform_lib.py -v`; verify the expected scenarios flip GREEN and none regress. Run full `pytest` after step 6 to catch caller-side regressions.

## Update callers

Once all 18 GREEN:

1. `common/scripts/plate/spawn_summary_agent.py` - if it shells out via `bash -c '. platform.sh; spawn_terminal_if_needed ...'`, replace with `from common.scripts.platform_lib import spawn_terminal_if_needed` direct call. Same commit.
2. Bash callers (`jot.sh`, `debate.sh`, `e2e-test.sh`, `todo-launcher.sh`): cannot drop-in import Python. Install transitional `[s]` shim by replacing `platform.sh` body with:

   ```bash
   # Transitional shim — see MIGRATION_TO_PYTHON.md.
   spawn_terminal_if_needed() {
     python3 -c "from common.scripts.platform_lib import spawn_terminal_if_needed; import sys; spawn_terminal_if_needed(*sys.argv[1:])" "$@"
   }
   ```

   Mark `[s]` in tracker. Shim deleted when last bash caller migrates.

3. Verify dead callers (`archive/push.sh`, `OLD_DISCARD/debate.sh`) - if confirmed dead, delete in a separate commit; otherwise treat as live shim consumers.

## Final delete

When the last bash caller (currently any of jot.sh / debate.sh / e2e-test.sh / todo-launcher.sh) migrates and no `. platform.sh` remains in the codebase:

```
git grep -nE '(\. |source ).*platform\.sh' -- ':!docs' ':!*.md'
```

Must return zero matches. Then `rm common/scripts/platform.sh`. Tracker flips from `[s]` to `[x]`.

## Risk callouts

1. **AppleScript regressions invisible to mocked tests.** Captured-stdin assertions verify intent, not that AppleScript itself parses. Mandatory manual smoke (Verification step 3).
2. **`tmux list-clients` semantics.** Confirm rc/stdout for missing vs attached sessions match the bash assumption. Verify against `common/scripts/tmux.sh` at impl time.
3. **`OSTYPE` vs `platform.system()`.** Bash branches on `OSTYPE` (e.g. `darwin24`); Python uses `platform.system()` returning `"Darwin"`. Equivalent for Darwin/Linux/FreeBSD/WSL. Documented divergence: `OSTYPE=linux-gnu` override on a Mac will not flip Python to non-Darwin branch. Acceptable.
4. **Background osascript.** Must use `Popen` without `.wait()`. If broken, every UserPromptSubmit hook waits on AppleScript - measurable as latency spike in Verification step 8.
5. **`log_file` append atomicity.** Single `write()` of fully-formed line preserves O_APPEND atomicity (matches bash `>> "$log_file"`).
6. **Dead-caller risk.** `archive/push.sh` and `OLD_DISCARD/debate.sh` may still source `platform.sh`. Keep transitional shim alive until they're confirmed deleted.
7. **`spawn_summary_agent.py` reference shape.** Currently stores path string. If it shells out via bash, the `[s]` shim covers it. Migrating to direct import is preferred but may belong in a separate commit to keep blast radius small.

## Verification plan

Failing-verification design: a regression would manifest as (a) hook firing without spawning a Terminal, (b) missing/malformed advisory line, (c) hook latency spike >500ms, (d) Python `ImportError` at hook fire time. All four are concretely measurable below.

1. `pytest tests/test_platform_lib.py -v` -> all 18 GREEN.
2. `pytest` (full suite) -> no regressions in `skills/debate/tests/`, `skills/plate/tests/`.
3. **macOS smoke (manual).** With shim in place: `bash -c '. common/scripts/platform.sh; spawn_terminal_if_needed migration-smoke /tmp/p.log jot yes'` -> maximized Terminal opens running `tmux attach -t migration-smoke`. Repeat with `compact` -> 1000x700 centred. Repeat with `""` -> default geometry.
4. **Linux smoke.** Same invocation -> no Terminal; `/tmp/p.log` gains exactly one line matching `^\S+ jot: non-Darwin host; attach manually via \x60tmux attach -t migration-smoke\x60$`.
5. **Live caller integration.** Run `skills/debate/tests/e2e-test.sh` end-to-end on macOS; four-pane debate window must spawn with full bounds.
6. **Latency regression.** `time (for i in 1 2 3 4 5; do bash -c '. common/scripts/platform.sh; spawn_terminal_if_needed nonexistent /tmp/p.log j ""'; done)` -> total wall <1s. Above threshold means Popen is blocking.
7. `python3 -m py_compile common/scripts/platform_lib.py` -> exit 0.
8. **Direct-import smoke.** `python3 -c "from common.scripts.platform_lib import spawn_terminal_if_needed; spawn_terminal_if_needed('migration-smoke-direct', '/tmp/p2.log', 'jot', 'compact')"` -> identical observed behavior to step 3 compact case.

Mark `[x]` in tracker only after steps 1-8 pass and no `. platform.sh` references remain in non-doc code.

## Numbered TODO list (per template steps 0-8)

0. Create this numbered TODO list (this section). DONE inline.
1. **Inventory.** Function table above. Source confirmed: 1 public function, decomposed into 6 typed Python functions for testability.
2. **Scaffold.** Write `common/scripts/platform_lib.py` with all 6 functions from the table. Each body is `print(f"TODO: {__name__}")` and a typed-correct dummy return (`None`, `False`, `""` as needed for type signature). Module imports cleanly; calling any function does no real work.
3. **RED tests.** Write `tests/test_platform_lib.py` with all 18 scenarios. Each scenario starts as a plain-English comment block before its assertion(s).
4. **Confirm RED.** `pytest tests/test_platform_lib.py -v`; every test fails on assertion (not import / signature). Fix scaffold if any test errors instead of fails. Flip tracker `[i]` -> `[~]`.
5. **GREEN, callees-first.** Implement in order: `_maximize_block` -> `_render_applescript` -> `_write_advisory` -> `_spawn_osascript` -> `_tmux_has_attached_clients` -> `spawn_terminal_if_needed`. Run pytest after each; commit per body or per small cluster. Stop only when all 18 GREEN.
6. **Update callers.** `spawn_summary_agent.py` -> direct import (same commit if shell-out path confirmed; separate commit otherwise). Bash callers -> install transitional `[s]` shim in `platform.sh`.
7. **Delete `.sh`.** When last bash caller migrates, `git grep` for residual sources, then `rm common/scripts/platform.sh`. Until then keep `[s]`.
8. **Verify end-to-end.** Run Verification steps 1-8. Flip tracker to `[x]` only after all pass plus manual Darwin smoke.
