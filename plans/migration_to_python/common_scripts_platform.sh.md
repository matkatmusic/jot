# Migrate `common/scripts/platform.sh` to Python

## Source

- File: `common/scripts/platform.sh`
- Class: `(sourced)` — every consumer pulls it in via `. "${CLAUDE_PLUGIN_ROOT}/common/scripts/platform.sh"` and then calls `spawn_terminal_if_needed` as a shell function. No callers `bash`-exec it. One Python consumer (`common/scripts/plate/spawn_summary_agent.py`) references the path string only (likely passed to a child shell), not Python-imported.
- Size: 91 lines bash
- Dependencies (sourced inside `platform.sh`):
  - `common/scripts/silencers.sh` — provides `hide_errors`, `hide_output`
  - `common/scripts/tmux.sh` — provides `tmux_list_clients`
  - External: `tmux`, `osascript` (Darwin only), `date -Iseconds`, AppleScript `Finder` + `Terminal`
- Position in dependency graph: leaf relative to `silencers.sh` and `tmux.sh`. Migration of `platform.sh` is **gated** on those two being callable from Python (or on us reimplementing the two helper calls inline in Python — preferred since `tmux_list_clients` is a one-liner around `tmux list-clients -t`).

### Caller list (grep `platform.sh`, excluding `.git/`, docs, OLD/archive)

Active sourcing callers (must keep `spawn_terminal_if_needed` available as a shell function):

1. `skills/jot/scripts/jot.sh:123`
2. `skills/plate/scripts/archive/push.sh:29` — archived path; verify if dead before counting.
3. `skills/debate/scripts/debate.sh:158`
4. `skills/debate/scripts/OLD_DISCARD/debate.sh:92` — dead.
5. `skills/debate/tests/e2e-test.sh:167`
6. `skills/todo/scripts/todo-launcher.sh:31`
7. `plans/debate-resume.md:497` — plan example, not a runtime caller.

Python-side path reference (no source-import semantics):

- `common/scripts/plate/spawn_summary_agent.py:37` — stores the path; investigate at impl time whether it shells out via `bash -c '. platform.sh; spawn_terminal_if_needed …'`. If yes, it must be updated to call the new Python entry directly.

Doc-only mentions: `README.md:66`, `CHANGELOG.md`, `MIGRATION_TO_PYTHON.md`, `common/scripts/USAGE.md:7`. No code change.

## Behavior spec

`platform.sh` defines exactly one public function:

### `spawn_terminal_if_needed <session_name> [log_file] [log_prefix] [maximize]`

Purpose: UX nicety. If no tmux client is attached to `<session_name>`, open a new macOS Terminal.app window that runs `tmux attach -t <session_name>`. On non-Darwin or when `osascript` is missing, write an advisory line to `<log_file>` and return 0. Never fails (always returns 0 — calling it must not break a hook).

Argument contract:

1. `session_name` — required. If empty, bash's `${1:?…}` aborts with non-zero (the only failure mode).
2. `log_file` — default `/dev/null`. Append target for the advisory line on non-Darwin / missing-osascript paths.
3. `log_prefix` — default `tmux`. Tag prepended to the advisory line (e.g. `jot`, `plate`, `debate`).
4. `maximize` — default empty. Tri-state:
   - `"yes"` — after `do script`, set front Terminal window bounds to `bounds of window of desktop` (full active monitor minus menu bar). Used by `/debate` (4-pane layout).
   - `"compact"` — clamp front window to a 1000x700 rect centred on the active monitor. Used by single-pane spawners like `/plate` so a previously-maximized window doesn't carry over.
   - `""` — no resize. Legacy default.

Algorithm:

1. Probe attached clients: `clients=$(hide_errors tmux_list_clients "$session")`.
2. If `clients` non-empty → `return 0` (already attached; do nothing). The early-return skips the entire osascript block, including bounds adjustment — the `maximize` argument only fires on the very first spawn.
3. Build an AppleScript fragment `maximize_block` based on `maximize` value.
4. Branch on `${OSTYPE:-}`:
   - `darwin*`:
     - If `command -v osascript` fails (silenced) → write `"<ts> <log_prefix>: osascript unavailable; attach manually via tmux attach -t <session>"` to `log_file`, return 0.
     - Else: run `osascript` with a heredoc that:
       - if Terminal.app already running → `do script "tmux attach -t <session>"` (opens a new window or tab — Terminal default is window).
       - else → `tell application "Terminal" / do script "…" in window 1`.
       - appends `maximize_block` (Finder bounds query + bounds setter for "yes" / centred-rect setter for "compact").
     - Backgrounded with `&` so the hook returns immediately.
6. Non-Darwin (`*`): write the advisory line to `log_file`, return 0.

### Platform branch rationale (per-branch)

| Branch | Trigger | Why it exists |
|---|---|---|
| `darwin*` + `osascript` present | macOS with AppleScript runtime | Spawning Terminal.app windows is only meaningfully scriptable through AppleScript. tmux + iTerm2 has its own AppleScript dictionary but we deliberately target stock Terminal.app for zero-install. |
| `darwin*` + `osascript` missing | hardened/stripped macOS, sandbox | Falls back to advisory log line so the hook never blocks. |
| Non-Darwin | Linux dev machines, CI | No analogue to AppleScript Finder bounds. We log instructions and let the user `tmux attach` manually. Terminal-spawning on Linux varies wildly (gnome-terminal, kitty, foot, alacritty, xterm) — out of scope. |
| `maximize="yes"` | `/debate` only | Four-pane layout (Claude + Gemini + Codex + synth) needs a full screen to be readable. |
| `maximize="compact"` | `/plate` summary-agent spawn | Avoids inheriting a giant geometry left behind by a prior `/debate` window — the next paragraph in observation #3257 explains this is a real bug fixed via this exact mode. |
| `maximize=""` | `/jot`, `/todo`, legacy | No layout opinion. |

### Non-portability inventory (commands that don't exist everywhere)

- `osascript` — macOS only. Already guarded.
- `Finder.app` and `Terminal.app` AppleScript dictionaries — macOS only. Already inside the `darwin*` branch.
- `date -Iseconds` — GNU coreutils flag. **macOS BSD `date` supports `-Iseconds` as of macOS 12** (it was added then). Older macOS would fail silently because the line is appended to `log_file` with `|| true`. Risk: silent drop of advisory log on ancient macOS. Migration MUST replicate this with `datetime.datetime.now().isoformat(timespec="seconds")` which is platform-agnostic.
- `tmux` — assumed present by every caller; not our problem here.
- `command -v` — POSIX builtin, fine on every shell. Python equivalent: `shutil.which("osascript")`.
- `>> "$log_file" 2>/dev/null || true` — silent-best-effort append. Python: `try: Path(log_file).open("a").write(...)\nexcept OSError: pass`.

## Target Python module path

Single source-of-truth module:

```
common/scripts/platform_lib.py        # pure functions, importable, fully unit-tested
common/scripts/platform_cli.py        # argparse dispatcher; one subcommand: spawn-terminal
common/scripts/platform.sh            # shim — bash function delegating to platform_cli.py
```

Rationale:

- `platform.sh` is `(sourced)`, so per the migration template step 6 we keep a bash shim that defines `spawn_terminal_if_needed` as a shell function calling `python3 .../platform_cli.py spawn-terminal --session …`. Existing `. platform.sh` callers see no API change.
- Most of the original is `case "${OSTYPE:-}" in darwin*) … ;; *) … ;; esac`. In Python this becomes `platform.system() == "Darwin"`. No `OSTYPE` env probing needed — `platform.system()` is canonical.
- The two heredoc AppleScript bodies become Python triple-quoted strings rendered with `str.format` placeholders. Run via `subprocess.Popen(["osascript", "-"], stdin=PIPE, …)` and write the script to stdin (avoids shell quoting hell of the original `<<OSA` form).
- We do **not** depend on porting `silencers.sh` first: Python's `subprocess` provides `stdout=DEVNULL, stderr=DEVNULL` natively. We do **not** depend on porting `tmux.sh` first either: `tmux_list_clients` collapses to `subprocess.run(["tmux", "list-clients", "-t", session], capture_output=True, text=True, check=False)` and the truthiness check is `result.returncode == 0 and result.stdout.strip() != ""`.

### `_cli.py` shim

`common/scripts/platform_cli.py` exposes:

```
platform_cli.py spawn-terminal --session NAME [--log-file PATH] [--log-prefix STR] [--maximize {yes,compact,}]
```

Exit code: always 0 (matches "never fails" contract). Non-zero only if argparse rejects args (programmer error).

### `platform.sh` final body (shim)

```bash
# platform.sh — Python-shim wrapper.
# Public function preserved for `. platform.sh` consumers.
_PLATFORM_PY="$(dirname "${BASH_SOURCE[0]}")/platform_cli.py"

spawn_terminal_if_needed() {
  local session="${1:?spawn_terminal_if_needed: session name required}"
  local log_file="${2:-/dev/null}"
  local log_prefix="${3:-tmux}"
  local maximize="${4:-}"
  python3 "$_PLATFORM_PY" spawn-terminal \
    --session "$session" \
    --log-file "$log_file" \
    --log-prefix "$log_prefix" \
    --maximize "$maximize" || true
}
```

`|| true` preserves the never-fail contract verbatim.

## RED test scenarios (pytest)

File: `tests/test_platform.py`. Each test starts as a plain-English scenario comment, then a failing assertion. All osascript / tmux / Finder calls are stubbed by monkeypatching `subprocess.run` and `shutil.which`; `platform.system()` is monkeypatched per-test. No real Terminal.app windows ever open during tests.

Helpers:

- Fixture `fake_subproc` — captures every `subprocess.run` call (args, input, env) into a list.
- Fixture `tmp_log` — `tmp_path / "advisory.log"`.
- Parametrize `system` over `["Darwin", "Linux"]` where relevant.

Scenarios (count: 18):

1. `missing_session_raises` — calling `spawn_terminal_if_needed(session="")` raises `ValueError`. (matches bash `${1:?…}` semantics; CLI maps it to argparse error.)
2. `attached_client_returns_without_spawning_darwin` — `tmux list-clients` stub returns non-empty stdout + rc 0; on Darwin → no `osascript` call recorded, return code 0.
3. `attached_client_returns_without_spawning_linux` — same, but `platform.system()=="Linux"` → no advisory log written either (early-return precedes the OS branch).
4. `unattached_darwin_invokes_osascript` — `tmux list-clients` rc != 0 → `osascript` invoked exactly once with stdin containing `tmux attach -t mysession`.
5. `unattached_darwin_missing_osascript_logs_advisory` — `shutil.which("osascript")` returns `None` → log file gains exactly one line matching `r"\S+ jot: osascript unavailable; attach manually via `tmux attach -t mysession`\n"`.
6. `unattached_linux_logs_advisory` — `platform.system()=="Linux"` → log file gains `non-Darwin host; attach manually …` line; no `osascript` call.
7. `linux_advisory_log_path_devnull_does_not_raise` — `log_file="/dev/null"` (the default) → no exception, no file created.
8. `log_file_unwritable_swallows_error` — `log_file=tmp_path / "ro" / "log"` (parent missing) → function still returns 0, no exception. (Mirrors `|| true`.)
9. `maximize_yes_appends_full_bounds_block` — Darwin spawn, `maximize="yes"` → osascript stdin contains `bounds of window of desktop` AND `set bounds of front window to screenBounds`.
10. `maximize_compact_appends_centred_block` — Darwin spawn, `maximize="compact"` → osascript stdin contains `winW to 1000` and `winH to 700` and `(ex - sx - winW) div 2`.
11. `maximize_empty_omits_bounds_block` — Darwin spawn, `maximize=""` → osascript stdin contains the `do script "tmux attach -t …"` line but NO `bounds` keyword.
12. `maximize_unknown_value_omits_bounds_block` — Darwin spawn, `maximize="garbage"` → behaves like empty (matches bash's `if/elif` with no else fallthrough). Document in spec.
13. `terminal_running_branch_uses_do_script_top_level` — when AppleScript renders the "if running" branch the stdin must contain `if application "Terminal" is running then\n  tell application "Terminal" to do script`. (We always emit both branches; the `if/else` is inside AppleScript itself, not Python.)
14. `log_prefix_default_is_tmux` — Linux call with `log_prefix=None` → advisory line begins `<iso> tmux:`.
15. `log_prefix_custom_is_used` — `log_prefix="debate"` → advisory line begins `<iso> debate:`.
16. `iso_timestamp_format_in_advisory` — advisory line first whitespace-delimited token parses as ISO-8601 seconds-precision via `datetime.fromisoformat`.
17. `osascript_invocation_is_backgrounded` — verify the implementation does NOT block on osascript completion (e.g. uses `Popen` + does not call `.wait()` synchronously, OR uses `start_new_session=True`, depending on impl choice). Verified by mocking `Popen` and asserting `.wait` not called before return.
18. `cli_subcommand_parity` — invoking `python3 platform_cli.py spawn-terminal --session s --log-file L --log-prefix p --maximize yes` end-to-end (with mocked `subprocess.run` for tmux/osascript) produces identical observed side effects to a direct `platform_lib.spawn_terminal_if_needed(...)` call.

Platform parameterization: scenarios 2/3, 6 explicitly switch `platform.system()`. Scenario 5 covers Darwin-without-osascript. Scenario 1, 9-12 are platform-agnostic (logic before the OS branch, or AppleScript string assembly).

## Risk callouts

1. **AppleScript shape regressions invisible to unit tests.** All osascript invocations are mocked. We must add a smoke test (Verification §3) that runs against a real macOS host and visually confirms a window opens. Captured-stdin assertions verify the *intent* of the script, not that AppleScript itself accepts it.
2. **`tmux_list_clients` semantics.** The original sources `tmux.sh`. Reimplementing inline as `tmux list-clients -t <session>` must match: `tmux list-clients -t` returns rc 1 with empty stdout when no session exists; rc 0 with one line per client when attached. Confirm by reading `common/scripts/tmux.sh` at impl time and matching.
3. **`osascript` availability detection.** Original uses `command -v osascript`. Python equivalent is `shutil.which("osascript") is not None`. Both honor `PATH`. Verify by setting `PATH=""` in a test.
4. **`OSTYPE` vs `platform.system()`.** The bash version branches on `OSTYPE` (set by bash itself, e.g. `darwin24`). Python `platform.system()` returns `"Darwin"`. Behavior is equivalent for all known hosts (Darwin, Linux, FreeBSD, WSL → `"Linux"`). Documented divergence: if a user explicitly overrides `OSTYPE=linux-gnu` on a real Mac to force the advisory branch, Python will not honor it. Acceptable; nobody does that.
5. **Background osascript `&`.** The original backgrounds `osascript` so the hook returns immediately. Python must replicate via `Popen` without `.wait()`, using `stdout=DEVNULL, stderr=DEVNULL, stdin=PIPE` and writing+closing stdin before returning. If we accidentally block, every UserPromptSubmit hook now waits for AppleScript — measurable regression.
6. **`log_file` race / append semantics.** Bash uses `>> "$log_file"` which is O_APPEND atomic for short writes. Python `Path(...).open("a")` is the same on POSIX. Use a single `write()` of the fully-formed line (with trailing `\n`) to preserve atomicity.
7. **Path of `spawn_summary_agent.py`'s reference.** That module currently stores `_PLATFORM_SH = … / "platform.sh"`. After migration the shim still exists, so the reference stays valid. But if `spawn_summary_agent.py` is shelling out via `bash -c '. platform.sh; spawn_terminal_if_needed ...'`, we must verify the shim's function signature is byte-identical (it is, by construction). If instead it should call Python directly, **do that in a separate commit** to keep this migration's blast radius small.
8. **Archived/dead callers.** `skills/plate/scripts/archive/push.sh` and `skills/debate/scripts/OLD_DISCARD/debate.sh` may be dead but still source the shim; keep the shim alive until they're deleted.

## Verification plan

A failing verification would: (a) invoke a hook that uses `spawn_terminal_if_needed`, (b) observe no Terminal window opens / advisory line missing / log line malformed / hook latency spikes — any of which fails the test. Concrete steps:

1. `pytest tests/test_platform.py -v` → all 18 GREEN.
2. Sourcing-shim parity check: `bash -c '. common/scripts/platform.sh; type -t spawn_terminal_if_needed'` prints `function`. `bash -c '. common/scripts/platform.sh; spawn_terminal_if_needed test-sess /tmp/p.log jot ""'` returns 0 within <500ms (timing asserted via `time` + threshold).
3. macOS smoke (manual): `bash -c '. common/scripts/platform.sh; spawn_terminal_if_needed migration-smoke /tmp/p.log jot yes'` opens a maximized Terminal.app window running `tmux attach -t migration-smoke`. Repeat with `compact` → window is 1000x700 centred. Repeat with `""` → window opens with default geometry.
4. Linux smoke (CI / Linux dev): same invocation → no Terminal opens; `/tmp/p.log` gains exactly one line matching `^\S+ jot: non-Darwin host; attach manually via `tmux attach -t migration-smoke`$`.
5. Existing caller integration: run `skills/debate/tests/e2e-test.sh` end-to-end on macOS. Must still spawn the four-pane debate window with full bounds.
6. `bash -n common/scripts/platform.sh` (syntax-check shim) → exit 0.
7. `python3 -m py_compile common/scripts/platform_lib.py common/scripts/platform_cli.py` → exit 0.
8. Latency regression check: `time (for i in 1 2 3 4 5; do bash -c '. common/scripts/platform.sh; spawn_terminal_if_needed nonexistent /tmp/p.log j ""'; done)` total wall <1s. If above, the `Popen` background is broken.

## Numbered TODO list (per template steps 0-8)

0. Create this numbered TODO list (this section). DONE inline.
1. Mark `common/scripts/platform.sh` as `[i]` in `MIGRATION_TO_PYTHON.md`. (Done before this plan was written.)
2. Commit this plan at `plans/migration_to_python/common_scripts_platform.sh.md` and flip the tracker entry to `[p]`.
3. Write RED tests in `tests/test_platform.py` covering all 18 scenarios above. Each scenario starts as a plain-English comment block before any assertion. Run `pytest tests/test_platform.py -v`; verify every test FAILS for the right reason (NameError on missing module, not stub bug). Flip tracker to `[~]`.
4. Implement `common/scripts/platform_lib.py` with:
   - `spawn_terminal_if_needed(session, log_file="/dev/null", log_prefix="tmux", maximize="") -> int`
   - private `_render_applescript(session, maximize) -> str`
   - private `_tmux_has_attached_clients(session) -> bool`
   - private `_write_advisory(log_file, log_prefix, session, reason) -> None`
5. Implement `common/scripts/platform_cli.py` with `argparse` subcommand `spawn-terminal` whose flags map 1:1 to `spawn_terminal_if_needed` kwargs.
6. Run `pytest tests/test_platform.py -v` until GREEN. Do not proceed past GREEN with any failing scenario. Run full suite `pytest` to catch regressions in callers' tests (especially `skills/debate/tests/`, `skills/plate/tests/`).
7. Replace `common/scripts/platform.sh` body with the bash shim shown above. Keep the file's leading comment block. Verify all seven active sourcing callers still parse and call the function via `bash -n` and a one-shot dry-run per caller path.
8. End-to-end verify per Verification §3-5 above. On full GREEN + manual Darwin smoke + Linux advisory-log smoke, flip the tracker entry to `[x]`.

