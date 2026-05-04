# Migrate `common/scripts/tmux-launcher.sh` to Python

## Source

- File: `common/scripts/tmux-launcher.sh` (144 lines bash)
- Class: `(sourced)` — every consumer pulls it in via `. tmux-launcher.sh` so callers can invoke its functions in-process; never run as a subprocess.
- Position in dependency graph: composite layer on top of `common/scripts/tmux.sh` primitives. Sources `silencers.sh` (`hide_output`) and `tmux.sh` (raw tmux primitives).
- Blocked-on dependencies: `common/scripts/tmux.sh` and `common/scripts/silencers.sh`. Both must be migrated first OR carved out as Python equivalents that this module can import. Mark this plan blocked until those land.

### Distinction from `tmux.sh` (companion)

- `tmux.sh` = thin per-call wrappers around individual `tmux` subcommands (`tmux_has_session`, `tmux_new_session`, `tmux_new_pane`, `tmux_set_option_t`, `tmux_capture_pane`, `tmux_send_keys`, etc.). Stateless. One bash function == one `tmux` invocation.
- `tmux-launcher.sh` = composite operations that combine multiple `tmux.sh` primitives into idempotent session-bootstrap workflows used at skill launch time. Each function performs a multi-step state-machine check (does the session exist? does the window exist? does the keepalive pane exist?) and only spawns missing pieces.
- Practical split: `tmux.sh` is used by everyone (running-session ops + readers). `tmux-launcher.sh` is used only at the moment a skill spins up its tmux substrate (jot, todo, debate, plate worker spawn). The launcher does not ship send-keys or capture helpers itself; callers reach into `tmux.sh` for those.

### Callers (all source it; none invoke it as a subprocess)

Production scripts:
- `skills/jot/scripts/jot.sh` (copies into `$TMPDIR_INV/tmux-launcher.sh` and sources it after copy, line 124)
- `skills/jot/scripts/jot-session-start.sh` (sources sibling copy in `$TMPDIR_INV`)
- `skills/plate/scripts/archive/plate-worker-start.sh` (archived, ignore)
- `skills/debate/scripts/debate-tmux-orchestrator.sh` (indirect via `tmux.sh`; debate currently relies only on primitives, so direct dependency may be absent — confirm during impl)

Tests (must stay GREEN through migration):
- `tests/tmux-send-test.sh`
- `skills/jot/tests/jot-test-suite.sh`
- `skills/jot/tests/jot-e2e-live.sh`
- `skills/jot/tests/jot-diag-collect.sh` (best-effort source)
- `skills/plate/tests/plate-e2e-live.sh`
- `skills/plate/tests/plate-claude-e2e.sh`

## Behavior spec

Per-function specification. Inputs are positional bash args; document the Python signature alongside each.

### `tmux_ensure_session <session> <window> <cwd> <keepalive_cmd> <keepalive_title>`
Idempotent session+window+keepalive bootstrap. Three branching paths:
1. Session does NOT exist → `tmux_new_session` with `-n <window> -c <cwd> <keepalive_cmd>`. Then apply session-scoped options: `remain-on-exit=off`, `mouse=on`, `pane-border-status=top`, `pane-border-format=' #{pane_title} '`. Title pane `${session}:${window}.0` with `<keepalive_title>`. Return 0.
2. Session exists but window does NOT → `tmux_new_window <session> <window> -c <cwd> <keepalive_cmd>`, then title `${session}:${window}.0`. Return 0.
3. Session+window both exist → delegate to `tmux_ensure_keepalive_pane`.
All option-set and title-set calls are wrapped in `hide_output` to suppress noise. Python equivalent: redirect subprocess stdout/stderr to `os.devnull`.

Python signature:
```python
def tmux_ensureSessionWithKeepalivePane(
    session: str, window: str, cwd: str,
    keepalive_cmd: str, keepalive_title: str,
) -> None
```

### `tmux_ensure_keepalive_pane <target> <cwd> <keepalive_cmd> <title>`
Add a keepalive pane to `<target>` (a `session:window`) only if no pane in that target already has the given title. On miss: `tmux_new_pane -c <cwd> -P -F '#{pane_id}' <keepalive_cmd>`, capture the new pane id, set its title, then retile.

Python signature:
```python
def tmux_ensureKeepalivePaneInWindow(
    target: str, cwd: str, keepalive_cmd: str, title: str,
) -> None
```

### `tmux_split_worker_pane <target> <cwd> <cmd>` -> stdout pane id
Splits `<target>` to spawn a worker pane running `<cmd>` from `<cwd>`. Captures pane id via `-P -F '#{pane_id}'`. On empty pane id returns 1 (bash) — Python should raise. On success prints pane id to stdout (callers capture via `$()`).

Python signature:
```python
def tmux_splitWorkerPaneAndReturnPaneId(
    target: str, cwd: str, cmd: str,
) -> str  # raises RuntimeError if tmux returns empty pane id
```

### `tmux_wait_for_claude_readiness <pane_id> [timeout=10]` -> 0 ready, 1 timeout
Polls `tmux_capture_pane <pane_id> 5` every 0.5s up to `timeout` seconds, looking for the literal `❯` prompt glyph. On timeout writes `[tmux-launcher] tmux_wait_for_claude_readiness: timed out after <N>s waiting for pane '<id>'` to stderr and returns 1.

Python signature:
```python
def tmux_waitForClaudeTuiReadiness(
    pane_id: str, timeout_seconds: float = 10.0,
) -> bool  # True ready, False timeout
```

### `tmux_launcher_tests`
Self-test routine. Drop in Python — replaced by pytest under `tests/`.

## Migration template steps

0. Numbered TODO list (see below).
1. Mark `[i]` in `MIGRATION_TO_PYTHON.md` for `common/scripts/tmux-launcher.sh`.
2. Plan written here; mark `[p]`.
3. RED tests: `tests/test_tmux_launcher.py`. Each function gets a parametrized test set.
4. Mark `[~]`.
5. Implement single module: `common/scripts/tmux_launcher_lib.py` plus `common/scripts/tmux_launcher_cli.py` argparse dispatcher.
6. Run pytest GREEN.
7. Replace `.sh` body with bash shim that defines the four function names as wrappers calling `python3 -m common.scripts.tmux_launcher_cli <fn> "$@"` so existing `source` callers keep working unchanged. (Sourced class — cannot use `exec python3` shim.)
8. Verify end-to-end against jot/todo/debate/plate live launches. Mark `[x]`.

## Target Python module paths

- `common/scripts/tmux_launcher_lib.py` — pure Python implementation. Imports from `common.scripts.tmux_lib` (the future migrated `tmux.sh`). Until that is migrated, the lib calls `tmux` via `subprocess.run` directly, mirroring the bash primitives’ behavior.
- `common/scripts/tmux_launcher_cli.py` — argparse dispatcher exposing one subcommand per public function: `ensure-session`, `ensure-keepalive-pane`, `split-worker-pane`, `wait-for-claude-readiness`. Each subcommand prints the same stdout/exit-code contract as the bash function.
- `common/scripts/tmux-launcher.sh` — kept as bash shim (function-defining wrapper). Contents:

```bash
# tmux-launcher.sh — Python-backed shim. Sourced by skill launchers.
_tl_py() { python3 -m common.scripts.tmux_launcher_cli "$@"; }
tmux_ensure_session()              { _tl_py ensure-session              "$@"; }
tmux_ensure_keepalive_pane()       { _tl_py ensure-keepalive-pane       "$@"; }
tmux_split_worker_pane()           { _tl_py split-worker-pane           "$@"; }
tmux_wait_for_claude_readiness()   { _tl_py wait-for-claude-readiness   "$@"; }
```

Note on `$TMPDIR_INV` copy semantics: `skills/jot/scripts/jot.sh` copies the launcher into `$TMPDIR_INV` so plugin updates mid-flight do not corrupt a running daemon. The shim must be self-contained — no relative `source` lines into sibling files that aren’t also copied. The Python module path must therefore be reachable via `PYTHONPATH=$CLAUDE_PLUGIN_ROOT` at the time the copied shim runs. Verify the shim works after `cp` into a foreign tmpdir.

## RED test scenarios (pytest)

File: `tests/test_tmux_launcher.py`. Tmux mocking strategy: **live tmux integration** with isolated socket (`tmux -L <unique-socket-name>`) so tests never collide with the user’s tmux server. Each test creates a fresh socket name, kills the server in teardown. Rationale: composite functions interact with five+ tmux subcommands — mocking each is brittle and the bash self-tests already use live tmux. CI must have tmux installed (matches existing `tests/tmux-send-test.sh` precedent).

Helpers (in test fixture):
- `tmux_socket` fixture: yields unique `-L` flag, kills server in teardown.
- `running_session(tmux_socket)`: factory creating a disposable session and yielding its name.

### `tmux_ensureSessionWithKeepalivePane`
- `creates_session_when_missing` — no session exists → call → `tmux has-session` returns 0, exactly one window with given name exists, pane 0 title equals `<keepalive_title>`.
- `applies_session_options_on_create` — after creation, `tmux show-options -t <s> -v pane-border-status` == `top`, `mouse` == `on`, `remain-on-exit` == `off`, `pane-border-format` == ` #{pane_title} `.
- `creates_window_when_session_exists_window_missing` — pre-create session, call with new window name → window exists, pane 0 has title.
- `idempotent_when_session_and_window_exist_with_keepalive` — call twice; second call must not create a second pane (pane count unchanged).
- `adds_keepalive_pane_when_session_window_exist_no_keepalive` — pre-create session+window WITHOUT a titled pane, call → pane count increments by exactly 1, new pane title matches.

### `tmux_ensureKeepalivePaneInWindow`
- `noop_when_pane_with_title_already_exists` — title preexists → pane count unchanged, return success.
- `creates_pane_when_title_missing` — title absent → exactly one new pane appears, has title, layout retiled (verified via `tmux list-panes -F '#{pane_active}'` showing >1 pane).
- `propagates_cwd_to_new_pane` — pane’s `pane_current_path` == requested `cwd`.

### `tmux_splitWorkerPaneAndReturnPaneId`
- `returns_pane_id_starting_with_percent` — pane id format matches `%\d+`.
- `pane_actually_runs_command` — split with `cmd="echo READY > /tmp/marker.$$"`, poll for marker file → exists within timeout.
- `raises_when_target_invalid` — bogus target → `RuntimeError` (bash returned 1).

### `tmux_waitForClaudeTuiReadiness`
- `returns_true_when_glyph_appears_in_pane` — spawn pane that prints `❯` immediately → returns True within < timeout.
- `returns_false_on_timeout_with_no_glyph` — spawn pane running `sleep 30` → with `timeout=1.0` returns False, stderr contains `timed out after 1` and the pane id.
- `respects_custom_timeout_value` — measure wall time; with `timeout=2.0` failing path completes between 1.5s and 3.0s.
- `polls_at_half_second_cadence` — count poll attempts via patched `subprocess.run` recorder during a single test that uses a mock-only path.

### CLI shim parity (`tmux_launcher_cli.py`)
- `cli_ensure_session_smoke` — `python3 -m common.scripts.tmux_launcher_cli ensure-session <args>` exits 0 and produces the same tmux state as the lib call.
- `cli_split_worker_pane_prints_pane_id_to_stdout` — assert stdout matches `^%\d+\n$`.
- `cli_wait_for_claude_readiness_exit_codes` — exit 0 on ready, 1 on timeout (matches bash contract).

### Bash shim parity (`tmux-launcher.sh`)
- `bash_source_then_call_ensure_session_works` — `bash -c '. common/scripts/tmux-launcher.sh; tmux_ensure_session ...'` produces same state as direct CLI call.
- `bash_split_worker_pane_captures_via_dollar_paren` — `pid=$(tmux_split_worker_pane …); [[ "$pid" =~ ^%[0-9]+$ ]]`.
- `tmpdir_inv_copy_still_works` — copy shim + lib into a tmpdir, set `PYTHONPATH`, run a sourced call from that tmpdir; matches non-copied behavior.

## Risk callouts

1. **Detached process / daemon lifetime.** `keepalive_cmd` is typically a long-running process (`sleep infinity`, a Claude Code `--dangerously-…` invocation, etc.). The launcher does not own it after creation — tmux does. The Python migration must NOT add a `subprocess.Popen(...).wait()` accidentally; pass the command into `tmux new-session`/`new-window`/`new-pane` as a positional arg and let tmux fork/detach. Verify pane survives Python interpreter exit.
2. **TMPDIR_INV isolation.** `jot.sh` copies the launcher into a per-invocation tmpdir specifically so plugin updates cannot mutate a running daemon’s code. The Python implementation breaks this guarantee unless the `_lib.py` module is also copied (or the import is statically frozen). Mitigation options to choose during impl: (a) copy `tmux_launcher_lib.py` + `tmux_launcher_cli.py` next to the shim and run with `PYTHONPATH=$TMPDIR_INV`; (b) accept that future plugin updates can affect running daemons, document the regression. Option (a) is the safer behavioral match; pick it.
3. **Signal semantics.** Bash propagates `SIGINT`/`SIGTERM` from the parent into running `tmux` subprocesses synchronously. The Python shim adds an interpreter layer; ensure `subprocess.run` is invoked without `start_new_session=True` so tmux client signals propagate. Document this.
4. **`hide_output` migration.** Bash version uses `hide_output` from `silencers.sh` — wraps stdout/stderr to `/dev/null` only when `JOT_DEBUG` is unset. Python equivalent must read the same env var to preserve diagnostic output behavior. Avoid blanket `DEVNULL` redirect.
5. **`tmux capture-pane` UTF-8.** The readiness probe greps for the `❯` (U+276F) glyph. Python `subprocess.check_output` must decode with `encoding='utf-8'` and `errors='replace'`; never `bytes` compare against a manually-encoded literal — wrong locale will silently produce false negatives.
6. **Race on `tmux_pane_has_title`.** Two concurrent `tmux_ensure_keepalive_pane` calls against the same target will both observe “no titled pane” and both create one. Bash version has the same bug — Python migration should NOT silently fix it (preserves behavior parity). Document as known issue and call out a follow-up ticket.
7. **CI tmux availability.** Live-tmux integration tests require `tmux >= 3.0` on test runners. If CI lacks it, gate tests with `pytest.importorskip` equivalent (`shutil.which('tmux')`) and skip with an explicit message.
8. **`tmux_window_exists` exact-name match.** Bash uses exact name comparison; ensure Python uses `==` not `startswith`/regex when delegating.

## Verification plan

1. `pytest tests/test_tmux_launcher.py -v` → GREEN against live tmux on isolated socket.
2. `bash tests/tmux-send-test.sh` → still passes (sources the new shim).
3. `bash skills/jot/tests/jot-test-suite.sh` → all PASS lines, including the launcher-dependent paths around line 327.
4. **Live skill smoke (each in a clean tmux server with `-L verify-mig`):**
   - **jot:** invoke `/jot some-idea` end-to-end. Verify `jot:keepalive` pane appears in the `jot` session, worker pane spawns and runs to completion, `$TMPDIR_INV/tmux_target` is written, `PROCESSED:` marker reaches the input file.
   - **todo:** invoke `/todo park-this`. Verify `todo-launcher.sh` (which copies the launcher into `$TMPDIR_INV`) still spawns the worker pane and the resulting TODO file lands in `Todos/`.
   - **debate:** invoke `/debate some-topic`. Verify three panes (Claude, Gemini, Codex) plus moderator are created in the debate session and the readiness probe returns True for each before send-keys begin.
   - **plate:** invoke `/plate` then `/plate --done`. Verify the worker daemon spawn path through `plate-e2e-live.sh` reaches GREEN and parked plates replay as commits.
5. **Failing-verification design** (per feedback rule): for the readiness probe, run a control test where the migrated function is pointed at a pane that does NOT contain `❯` and assert it returns False within `timeout+0.5s`; if it returns True, the migration is broken. For idempotency, run `tmux_ensure_session` twice and assert pane count stays at exactly 1 (titled keepalive); if pane count grows to 2, the migration is broken.
6. **TMPDIR_INV regression test:** start `/jot`, capture the lib file paths inside `$TMPDIR_INV`, mutate the source-tree `tmux_launcher_lib.py` (add a syntax error), trigger a follow-up jot operation in the same daemon — it must still succeed because it reads the copied frozen lib, not the mutated source.

## Numbered TODO list

1. Confirm `common/scripts/tmux.sh` and `common/scripts/silencers.sh` migration status; if unmigrated, decide whether this plan is blocked or whether `tmux_launcher_lib.py` calls `tmux` directly via `subprocess.run` for the interim.
2. Mark `common/scripts/tmux-launcher.sh` as `[i]` in `MIGRATION_TO_PYTHON.md`.
3. Mark `[p]` (this plan committed).
4. Write `tests/test_tmux_launcher.py` with all RED scenarios above; run pytest, confirm every test fails (no implementation yet).
5. Mark `[~]` in `MIGRATION_TO_PYTHON.md`.
6. Implement `common/scripts/tmux_launcher_lib.py` with the four public functions.
7. Implement `common/scripts/tmux_launcher_cli.py` argparse dispatcher.
8. Run pytest until GREEN; iterate on lib only, never weaken tests.
9. Replace `common/scripts/tmux-launcher.sh` body with the bash shim that delegates each function to `python3 -m common.scripts.tmux_launcher_cli <subcmd>`.
10. Update `skills/jot/scripts/jot.sh` `cp` block (and any other `$TMPDIR_INV`-copying caller) to also copy `tmux_launcher_lib.py` and `tmux_launcher_cli.py` into `$TMPDIR_INV` and prepend `$TMPDIR_INV` to `PYTHONPATH` for the daemon.
11. Run `bash tests/tmux-send-test.sh` and `bash skills/jot/tests/jot-test-suite.sh` → both GREEN.
12. Run live skill smokes (jot, todo, debate, plate) per Verification step 4. Capture pane IDs and timestamps for evidence.
13. Run TMPDIR_INV regression test (Verification step 6).
14. Mark `[x]` in `MIGRATION_TO_PYTHON.md`.

