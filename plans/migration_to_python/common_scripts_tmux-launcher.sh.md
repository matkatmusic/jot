# Migrate `common/scripts/tmux-launcher.sh` to Python

## Source

- File: `common/scripts/tmux-launcher.sh` (144 lines bash)
- Target: `common/scripts/tmux_launcher_lib.py`
- Position in dependency graph: composite layer on top of `common/scripts/tmux.sh` primitives. Sources `silencers.sh` (`hide_output`) and `tmux.sh` (raw tmux primitives).
- Blocked-on dependencies: `tmux.sh` and `silencers.sh`. If unmigrated when this lands, `tmux_launcher_lib.py` calls `tmux` directly via `subprocess.run` for the interim, mirroring bash primitive semantics.

### Distinction from `tmux.sh` (companion)

- `tmux.sh` = thin per-call wrappers around individual `tmux` subcommands. Stateless. One bash function == one `tmux` invocation.
- `tmux-launcher.sh` = composite operations that combine multiple `tmux.sh` primitives into idempotent session-bootstrap workflows used at skill launch time. Each function performs a multi-step state-machine check (does the session exist? does the window exist? does the keepalive pane exist?) and only spawns missing pieces.
- Practical split: `tmux.sh` is used by everyone (running-session ops + readers). `tmux-launcher.sh` is used only at the moment a skill spins up its tmux substrate. The launcher does not ship send-keys or capture helpers itself; callers reach into `tmux.sh` for those.

## Function table (spine of plan)

| name | Python signature (typed) | return type | one-line behavior note |
|------|--------------------------|-------------|-------------------------|
| `tmux_ensure_session` | `tmux_ensure_session(session: str, window: str, cwd: str, keepalive_cmd: str, keepalive_title: str) -> None` | `None` | Idempotent session+window+keepalive bootstrap; three-branch state machine. |
| `tmux_ensure_keepalive_pane` | `tmux_ensure_keepalive_pane(target: str, cwd: str, keepalive_cmd: str, title: str) -> None` | `None` | If no pane in target has `title`, spawn one running `keepalive_cmd`, title it, retile. |
| `tmux_split_worker_pane` | `tmux_split_worker_pane(target: str, cwd: str, cmd: str) -> str` | `str` (pane id, e.g. `%17`) | Split target to spawn worker; returns pane id. Raises `RuntimeError` on empty id. **was: bash echoed pane id; Python returns it.** |
| `tmux_wait_for_claude_readiness` | `tmux_wait_for_claude_readiness(pane_id: str, timeout_seconds: float = 10.0) -> bool` | `bool` | Polls `tmux capture-pane` every 0.5s until `❯` appears or timeout; True ready, False timeout. |

`tmux_launcher_tests` (bash self-test) has no Python equivalent — replaced by `tests/test_tmux_launcher.py`.

### Per-function notes

**`tmux_ensure_session`** — Three branches:
1. Session missing → `tmux new-session -n <window> -c <cwd> <keepalive_cmd>`. Set session-scoped options: `remain-on-exit=off`, `mouse=on`, `pane-border-status=top`, `pane-border-format=' #{pane_title} '`. Title pane `${session}:${window}.0` with `<keepalive_title>`.
2. Session exists, window missing → `tmux new-window -c <cwd> <keepalive_cmd>`, then title pane.
3. Both exist → delegate to `tmux_ensure_keepalive_pane`.

All option-set/title-set calls wrapped in `hide_output` in bash. Python: route stdout/stderr to `subprocess.DEVNULL` only when `JOT_DEBUG` is unset (preserve diagnostic env behavior).

**`tmux_ensure_keepalive_pane`** — If `tmux_pane_has_title(target, title)` is true, no-op. Else: `tmux split-window -t <target> -c <cwd> -P -F '#{pane_id}' <keepalive_cmd>`, capture pane id, set title on that id, then retile target. Known race: two concurrent calls both observe "no titled pane" and both create one. Bash has same bug; **do not silently fix** (preserve parity); document as follow-up ticket.

**`tmux_split_worker_pane`** — `tmux split-window -t <target> -c <cwd> -P -F '#{pane_id}' <cmd>`. Empty pane id → bash returned 1; Python raises `RuntimeError`. Bash printed pane id to stdout for `$()` capture; Python returns the string directly. Detached process lifetime: do NOT `Popen(...).wait()` — pass the command into `tmux split-window` as a positional arg so tmux owns the lifetime. Verify worker pane survives Python interpreter exit.

**`tmux_wait_for_claude_readiness`** — Loop `max_attempts = int(timeout_seconds * 2)`; each iter runs `tmux capture-pane -p -t <pane_id> -S -5`, decoded `utf-8` with `errors='replace'`, searches for literal `'❯'` (U+276F). Sleep 0.5s between attempts. On timeout: write `[tmux-launcher] tmux_wait_for_claude_readiness: timed out after <N>s waiting for pane '<id>'` to stderr, return False. Never compare bytes to manually-encoded literal — wrong locale silently breaks.

## Callers needing import-site updates

This script has 18 callers across the repo. Action per caller:

**Production scripts (all currently `source` the launcher):**

| Caller | Action |
|--------|--------|
| `skills/jot/scripts/jot.sh` | **transitional shim** — bash, copies launcher into `$TMPDIR_INV` at line 124. Until `jot.sh` migrates, keep `tmux-launcher.sh` as a 2-line `exec python3 -c '...'` shim. Update jot.sh `cp` block to also copy `tmux_launcher_lib.py` into `$TMPDIR_INV` and prepend `$TMPDIR_INV` to `PYTHONPATH`. |
| `skills/jot/scripts/jot-session-start.sh` | **transitional shim** — sources sibling copy in `$TMPDIR_INV`. Inherits jot.sh's PYTHONPATH; same shim works. |
| `skills/jot/scripts/jot-state-lib.sh` | **transitional shim** — bash. |
| `skills/jot/scripts/jot-stop.sh` | **transitional shim** — bash, indirect via jot-state-lib. |
| `skills/jot/scripts/jot-session-end.sh` | **transitional shim** — bash. |
| `skills/plate/scripts/plate.sh` | **transitional shim** — bash. |
| `skills/plate/scripts/plate-summary-stop.sh` | **transitional shim** — bash. |
| `skills/plate/scripts/plate-summary-watch.sh` | **transitional shim** — bash. |
| `skills/debate/scripts/debate-orchestrator.sh` | **transitional shim** — bash. Confirm direct dep at impl time (may be indirect via tmux.sh only; if so, drop). |
| `skills/todo/scripts/todo-orchestrator.sh` | **transitional shim** — bash. |
| `skills/todo-list/scripts/todo-list-orchestrator.sh` | **transitional shim** — bash. |
| `skills/plate/scripts/archive/plate-worker-start.sh` | **ignore** — archived. |

**Tests (all `source` the launcher):**

| Caller | Action |
|--------|--------|
| `tests/tmux-send-test.sh` | **transitional shim** — bash test. |
| `skills/jot/tests/jot-test-suite.sh` | **transitional shim** — bash test. |
| `skills/jot/tests/jot-e2e-live.sh` | **transitional shim** — bash test. |
| `skills/jot/tests/jot-diag-collect.sh` | **transitional shim** — bash test (best-effort source). |
| `skills/plate/tests/plate-e2e-live.sh` | **transitional shim** — bash test. |
| `skills/plate/tests/plate-claude-e2e.sh` | **transitional shim** — bash test. |

**Net plan:** zero `import` rewrites possible today (every caller is bash). The `.sh` becomes a `[s]` shim defining the four bash function names as wrappers that `exec python3 -c 'from common.scripts.tmux_launcher_lib import <fn>; ...' "$@"`. Delete the `.sh` only when every caller above has migrated to Python or been retired. **Migrate-together candidates:** none — all callers depend on multiple other unmigrated `.sh` files; standalone migration here is not worth the churn.

Shim form (bash function definitions, sourced by callers):

```bash
# tmux-launcher.sh — Python-backed shim. Sourced by callers.
_tl_py() {
  PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$(dirname "${BASH_SOURCE[0]}")/../.." \
    python3 -c "import sys; from common.scripts.tmux_launcher_lib import $1 as f; sys.exit(0 if (f(*sys.argv[1:]) is None or f(*sys.argv[1:])) else 1)" "${@:2}"
}
tmux_ensure_session()            { _tl_py tmux_ensure_session            "$@"; }
tmux_ensure_keepalive_pane()     { _tl_py tmux_ensure_keepalive_pane     "$@"; }
tmux_wait_for_claude_readiness() { _tl_py tmux_wait_for_claude_readiness "$@"; }
tmux_split_worker_pane()         { _tl_py tmux_split_worker_pane         "$@"; }  # echoes returned pane id
```

Refine pane-id capture and exit-code semantics during impl; the above is sketch, not final.

## Migration steps (scaffold-first per template)

0. Numbered TODO list (below).
1. Mark `[i]` in `MIGRATION_TO_PYTHON.md`.
2. **Inventory** — function table above is the inventory.
3. **Scaffold** — write `common/scripts/tmux_launcher_lib.py` with all four functions: identical names, typed signatures, declared return types, body of `print("TODO: <function_name>")` and nothing else. Module must import cleanly; does no real work.
4. **RED tests** — write `tests/test_tmux_launcher.py` importing the scaffold and calling each stub by name. Tests assert on **return values** and **tmux state side effects** (pane count, titles, options), never on captured stdout. With `print("TODO: ...")` bodies every test fails on assertion.
5. **Confirm RED** — `pytest tests/test_tmux_launcher.py -v`. Every test fails for expected reason. If any errors on import or signature, fix the scaffold first.
6. **Mark `[~]`**.
7. **GREEN, callees-first**. Implementation order:
   1. `tmux_wait_for_claude_readiness` (no callees inside the module; pure subprocess loop).
   2. `tmux_split_worker_pane` (single tmux call + return).
   3. `tmux_ensure_keepalive_pane` (calls `tmux_pane_has_title` primitive + new pane + title + retile).
   4. `tmux_ensure_session` (top-level; calls `tmux_ensure_keepalive_pane` in branch 3).
   After each body, run pytest, confirm tests flip red to green without breaking others. Commit per body or small cluster.
8. **Replace `.sh` with shim** (transitional, marked `[s]`).
9. **Update `jot.sh` `cp` block** to copy `tmux_launcher_lib.py` into `$TMPDIR_INV` and set `PYTHONPATH`.
10. **Verify end-to-end** (live integration, not just pytest):
    - `bash tests/tmux-send-test.sh` GREEN.
    - `bash skills/jot/tests/jot-test-suite.sh` all PASS lines.
    - Live skill smokes on isolated tmux server (`-L verify-mig`):
      - `/jot some-idea` — `jot:keepalive` pane appears, worker pane spawns and runs to completion, `PROCESSED:` marker reaches input file.
      - `/todo park-this` — worker pane spawns, TODO file lands in `Todos/`.
      - `/debate some-topic` — three panes (Claude, Gemini, Codex) + moderator created, readiness probe returns True for each before send-keys begin.
      - `/plate` then `/plate --done` — worker daemon spawn reaches GREEN, parked plates replay as commits.
    - **Failing-verification design** (per feedback rule):
      - Readiness probe: point migrated function at a pane that does NOT contain `❯`; assert returns False within `timeout+0.5s`. If True, migration is broken.
      - Idempotency: run `tmux_ensure_session` twice; assert pane count stays at exactly 1 titled keepalive. If 2, migration is broken.
    - **TMPDIR_INV regression test**: start `/jot`, capture lib paths in `$TMPDIR_INV`, mutate source-tree `tmux_launcher_lib.py` (add syntax error), trigger follow-up jot operation in same daemon — must still succeed (reads frozen copy).
11. **Mark `[s]`** (shim survives until all bash callers migrate). Cannot mark `[x]` yet because at least one bash caller remains.

## RED test scenarios (pytest, `tests/test_tmux_launcher.py`)

Tmux mocking strategy: **live tmux integration** with isolated socket (`tmux -L <unique>`) so tests never collide with the user's tmux server. Composite functions interact with five+ tmux subcommands; mocking each is brittle. Bash self-tests already use live tmux. CI must have tmux installed (matches `tests/tmux-send-test.sh` precedent). Skip with `shutil.which('tmux')` guard if absent.

Fixtures:
- `tmux_socket` — yields unique `-L` flag, kills server in teardown.
- `running_session(tmux_socket)` — factory creating a disposable session, yields name.

### `tmux_ensure_session`
- `creates_session_when_missing` — call → `tmux has-session` returns 0; one window with given name; pane 0 title equals `keepalive_title`.
- `applies_session_options_on_create` — `show-options -t <s> -v pane-border-status` == `top`, `mouse` == `on`, `remain-on-exit` == `off`, `pane-border-format` == ` #{pane_title} `.
- `creates_window_when_session_exists_window_missing` — pre-create session; call with new window name → window exists, pane 0 has title.
- `idempotent_when_session_and_window_exist_with_keepalive` — call twice; pane count unchanged on second call.
- `adds_keepalive_pane_when_session_window_exist_no_keepalive` — pre-create session+window without titled pane; call → pane count +1, new pane has title.
- `returns_none` — function returns `None` (never a value).

### `tmux_ensure_keepalive_pane`
- `noop_when_pane_with_title_already_exists` — pane count unchanged.
- `creates_pane_when_title_missing` — exactly one new pane, has title, layout retiled (>1 pane visible via `list-panes -F '#{pane_active}'`).
- `propagates_cwd_to_new_pane` — `pane_current_path` matches requested `cwd`.
- `returns_none`.

### `tmux_split_worker_pane`
- `returns_pane_id_starting_with_percent` — return value matches `^%\d+$`.
- `pane_actually_runs_command` — split with `cmd="echo READY > /tmp/marker.$$"`, poll for marker file → exists within timeout.
- `raises_runtime_error_when_target_invalid` — bogus target → `RuntimeError`.

### `tmux_wait_for_claude_readiness`
- `returns_true_when_glyph_appears_in_pane` — spawn pane that prints `❯`; returns True within < timeout.
- `returns_false_on_timeout_with_no_glyph` — spawn pane running `sleep 30` with `timeout=1.0`; returns False; stderr contains `timed out after 1` and the pane id.
- `respects_custom_timeout_value` — wall time with `timeout=2.0` failing path between 1.5s and 3.0s.
- `polls_at_half_second_cadence` — count poll attempts via patched `subprocess.run` recorder in mock-only sub-test.

### Shim parity (bash)
- `bash_source_then_call_ensure_session_works` — `bash -c '. common/scripts/tmux-launcher.sh; tmux_ensure_session ...'` produces same tmux state as direct lib call.
- `bash_split_worker_pane_captures_via_dollar_paren` — `pid=$(tmux_split_worker_pane …); [[ "$pid" =~ ^%[0-9]+$ ]]`.
- `tmpdir_inv_copy_still_works` — copy shim + lib into tmpdir, set `PYTHONPATH`, run sourced call from that tmpdir; matches non-copied behavior.

## Risk callouts

1. **Detached process / daemon lifetime.** `keepalive_cmd` is long-running (`sleep infinity`, Claude Code TUI). Launcher does not own it after creation; tmux does. Do NOT add `subprocess.Popen(...).wait()` accidentally; pass command into `tmux new-session`/`new-window`/`split-window` as positional arg. Verify pane survives Python interpreter exit.
2. **TMPDIR_INV isolation.** `jot.sh` copies launcher into per-invocation tmpdir so plugin updates cannot mutate a running daemon's code. Python migration breaks this guarantee unless `tmux_launcher_lib.py` is also copied. Mitigation: copy lib next to shim and run with `PYTHONPATH=$TMPDIR_INV`. Behavioral parity preferred.
3. **Signal semantics.** Bash propagates SIGINT/SIGTERM into `tmux` subprocesses synchronously. Python interpreter adds a layer; invoke `subprocess.run` without `start_new_session=True` so tmux client signals propagate.
4. **`hide_output` migration.** Bash routes output to `/dev/null` only when `JOT_DEBUG` unset. Python equivalent must read same env var; avoid blanket `DEVNULL` redirect.
5. **`tmux capture-pane` UTF-8.** Readiness probe greps for `❯` (U+276F). Decode with `encoding='utf-8'`, `errors='replace'`. Never bytes-compare against a manually-encoded literal.
6. **Race on `tmux_pane_has_title`.** Two concurrent calls both observe "no titled pane" and both create one. Bash version has same bug; preserve parity; document as follow-up ticket.
7. **CI tmux availability.** Live-tmux tests need `tmux >= 3.0`. Gate with `shutil.which('tmux')`; skip with explicit message.
8. **`tmux_window_exists` exact-name match.** Use `==` not `startswith`/regex when delegating.

## Numbered TODO list

1. Confirm `tmux.sh` and `silencers.sh` migration status; if unmigrated, lib calls `tmux` via `subprocess.run` directly for the interim.
2. Mark `common/scripts/tmux-launcher.sh` as `[i]` in `MIGRATION_TO_PYTHON.md`.
3. Mark `[p]` (this plan committed).
4. Scaffold `common/scripts/tmux_launcher_lib.py` with four `print("TODO: ...")` stubs.
5. Write `tests/test_tmux_launcher.py` with all RED scenarios above; run pytest, confirm every test fails on assertion (not import).
6. Mark `[~]` in `MIGRATION_TO_PYTHON.md`.
7. GREEN bottom-up: implement `tmux_wait_for_claude_readiness`, then `tmux_split_worker_pane`, then `tmux_ensure_keepalive_pane`, then `tmux_ensure_session`. Commit per body. Pytest GREEN after each.
8. Replace `common/scripts/tmux-launcher.sh` body with bash shim defining the four function names as `_tl_py` wrappers.
9. Update `skills/jot/scripts/jot.sh` `cp` block to also copy `tmux_launcher_lib.py` into `$TMPDIR_INV` and prepend `$TMPDIR_INV` to `PYTHONPATH`.
10. Run `bash tests/tmux-send-test.sh` and `bash skills/jot/tests/jot-test-suite.sh` → both GREEN.
11. Run live skill smokes (jot, todo, debate, plate). Capture pane IDs and timestamps for evidence.
12. Run TMPDIR_INV regression test (mutate source after copy; daemon still works).
13. Mark `[s]` in `MIGRATION_TO_PYTHON.md` (shim survives; final delete deferred until last bash caller migrates).
14. **Final delete** of `tmux-launcher.sh` happens later, in a separate change, when the last caller (currently 18) is no longer bash. Mark `[x]` at that point.
