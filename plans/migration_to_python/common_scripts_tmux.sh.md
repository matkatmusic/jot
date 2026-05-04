# Migrate `common/scripts/tmux.sh` to Python

## Source

- File: `common/scripts/tmux.sh` (~825 lines bash)
- Companion: `common/scripts/tmux-launcher.sh` sources it; not migrated here.
- Sourced by callers only; never invoked as subprocess.
- Leaf primitive layer over `invoke_command` (silencers/permissions). Migration unblocks every other tmux-touching `.sh`.

## Target

- `common/scripts/tmux_lib.py` (single Python module, library-only).
- Pure imports. No CLI shim, no `_cli.py`, no `.sh` shim. Once all callers migrate, `tmux.sh` is deleted.
- `_tests` bash sub-functions are dropped; behavior recreated in `tests/test_tmux_lib.py`.

## Function table (spine)

Columns: `name | Python signature | return type | one-line behavior note`. All names map 1:1 from bash. No renames.

### Version / option group
| name | signature | return | note |
|---|---|---|---|
| `tmux_require_version` | `(min_version: str) -> int` | `int` | Parse `tmux -V`, return 0 if installed >= min, else 1 (stderr msg). |
| `tmux_set_option` | `(*args: str) -> int` | `int` | Passthrough to `tmux set-option`. |
| `tmux_set_option_t` | `(target: str, name: str, value: str) -> int` | `int` | `set-option -t <target> <name> <value>`. |
| `tmux_set_option_g` | `(name: str, value: str) -> int` | `int` | `set-option -g <name> <value>`. |
| `tmux_set_option_w` | `(window_target: str, name: str, value: str) -> int` | `int` | `set-option -w -t <target> <name> <value>`. |

### Session group
| name | signature | return | note |
|---|---|---|---|
| `tmux_has_session` | `(session: str) -> int` | `int` | `has-session -t <s>`. 0 exists, 1 missing. |
| `tmux_new_session` | `(session: str, *extra: str) -> int` | `int` | `new-session -d -s <s>` plus extras (`-n`, `-c`, trailing cmd). |
| `tmux_kill_session` | `(session: str) -> int` | `int` | `kill-session -t <s>`. |
| `tmux_list_clients` | `(session: str) -> tuple[int, str]` | `(rc, stdout)` | Stdout is meaningful; return both rc and captured text. |

### Pane group
| name | signature | return | note |
|---|---|---|---|
| `tmux_new_pane` | `(target: str, *extra: str) -> tuple[int, str]` | `(rc, stdout)` | `split-window -t`. When `-P -F '#{pane_id}'` in extras, stdout is the new pane id. |
| `tmux_kill_pane` | `(pane_target: str) -> int` | `int` | `kill-pane -t`. |
| `tmux_capture_pane` | `(pane_target: str, lines: int \| None = None) -> tuple[int, str]` | `(rc, stdout)` | `capture-pane -p -t <t> [-S -<lines>]`. CRITICAL primitive for capture-after-send. |
| `tmux_list_panes` | `(target: str, *extra: str) -> tuple[int, str]` | `(rc, stdout)` | Default format `'#{pane_id} #{pane_title}'`. Extra args override. |
| `tmux_select_pane` | `(pane_target: str) -> int` | `int` | `select-pane -t`. |
| `tmux_set_pane_title` | `(pane_target: str, title: str) -> int` | `int` | `select-pane -t <t> -T <title>`. |

### Window group
| name | signature | return | note |
|---|---|---|---|
| `tmux_new_window` | `(session: str, name: str, *extra: str) -> int` | `int` | `new-window -t <s> -n <name>`. |
| `tmux_kill_window` | `(window_target: str) -> int` | `int` | `kill-window -t`. |
| `tmux_list_windows` | `(session: str, *extra: str) -> tuple[int, str]` | `(rc, stdout)` | Default format `'#{window_index} #{window_name}'`. |
| `tmux_window_exists` | `(session: str, window_name: str) -> bool` | `bool` | Exact-name match against `list_windows`. Returns True/False, not exit code. |
| `tmux_pane_has_title` | `(target: str, title: str) -> bool` | `bool` | Exact-title match against `list_panes` titles. |
| `tmux_split_window` | `(target: str, direction: str) -> int` | `int` | `direction in {'h','v'}` -> `-h` / `-v`. Other values return nonzero. |

### Layout group
| name | signature | return | note |
|---|---|---|---|
| `tmux_select_layout` | `(target: str, layout: str) -> int` | `int` | layout in `{even-horizontal, even-vertical, main-horizontal, main-vertical, tiled}`. |
| `tmux_retile` | `(target: str) -> int` | `int` | Calls `tmux_select_layout(target, 'tiled')`. |

### Send-keys group (capture-after-send discipline)
| name | signature | return | note |
|---|---|---|---|
| `tmux_send_keys` | `(target: str, text: str) -> int` | `int` | `send-keys -t <t> <text>`. Does NOT append Enter. Pass text as single argv element. |
| `tmux_send_enter` | `(target: str) -> int` | `int` | `send-keys -t <t> Enter`. |
| `tmux_send_Ctrl_c` | `(target: str) -> int` | `int` | `send-keys -t <t> C-c`. Bash name kept verbatim (mixed case is intentional). |
| `tmux_send_and_submit` | `(target: str, text: str) -> int` | `int` | TWO separate `send-keys` calls (text, sleep 0.5, Enter). Two-call pattern is load-bearing; some TUIs drop bundled Enter. |
| `tmux_cancel_and_send` | `(target: str, text: str, label: str \| None = None) -> int` | `int` | See per-function notes; encodes the capture-after-send retry rule. |

Internal helper (not in bash, new to Python):
| name | signature | return | note |
|---|---|---|---|
| `_invoke` | `(*args: str) -> subprocess.CompletedProcess` | `CompletedProcess` | Single seam mirroring `invoke_command tmux ...`. `subprocess.run(["tmux", *args], text=True, capture_output=True)`, prints stderr passthrough, returns the completed process. All public functions go through this. |

Total public functions: 28. Plus 1 private helper.

## Per-function notes (critical detail)

- `tmux_require_version`: regex `[0-9]+\.[0-9]+` against `tmux -V`. Use tuple compare on `tuple(int(x) for x in match.split('.'))`. FileNotFoundError -> rc=1, stderr `"[tmux] tmux is not installed"`. Below-min -> rc=1, stderr `"[tmux] tmux <min>+ required (found <installed>)"`.
- `tmux_capture_pane`: lines=None means no `-S` flag. lines=N means append `-S`, `-N` (negative). Returns `(rc, stdout)` so callers can scan the buffer without re-shelling.
- `tmux_list_panes` / `tmux_list_windows`: when `extra` is empty, append the default `-F` format. When extra is non-empty, pass extra verbatim (callers explicitly override format).
- `tmux_window_exists` / `tmux_pane_has_title`: bash returns exit code, but Python idiom is bool. Tests assert on the bool, not stdout. `was: <old>` not needed (name unchanged), but return-type change is documented.
- `tmux_split_window`: validate direction. `'h' -> '-h'`, `'v' -> '-v'`, anything else returns rc=1 without invoking tmux.
- `tmux_send_keys`: pass `text` as a single argv element. Do NOT shell-quote, do NOT split on whitespace. tmux interprets tokens like `Enter`, `C-c`, `Space`, `\;` itself.
- `tmux_send_and_submit`: must issue exactly TWO `_invoke` calls with a `time.sleep(0.5)` between them. Bundling Enter into the first call breaks Claude Code / Gemini TUIs.
- `tmux_cancel_and_send` (capture-after-send pattern, CRITICAL):
  1. Loop up to 5 times: send `C-c`, `time.sleep(0.2)`, `tmux_capture_pane(target)`, scan buffer for literal `'Ctrl-C'` substring (note: prior observation 3607 flagged a real-tmux bug where the marker may render as `^C`; port keeps `'Ctrl-C'` to match bash and is verified live; if live test fails, fix is a separate bug-fix change, not part of this migration).
  2. If `attempt > 0` and `label` is non-empty, print `f"[tmux] cancelled in-progress work: {label} ({attempt + 1} Ctrl-C's)"` to stdout. Exact format; callers grep for it.
  3. Call `tmux_send_and_submit(target, text)`; return its rc.
  4. Sleep, marker string, retry count, and log format are all load-bearing. Do not change without re-running live cancel test against a real Claude pane.

Module-top docstring must explicitly document the capture-after-send rule so future contributors do not "optimize" away the retry loop.

## Callers needing import-site updates

Per `MIGRATION_TO_PYTHON.md` philosophy: every `.sh` ends as a Python module imported directly. Each caller below is listed with its required action.

Direct sourcers (15 found):

1. `common/scripts/tmux-launcher.sh` -- not yet migrated. Action: install transitional `[s]` shim on `tmux.sh` (2-line `exec python3 -c 'from tmux_lib import <fn>; ...'` per function) until tmux-launcher migrates. OR migrate tmux-launcher in same change.
2. `common/scripts/platform.sh` -- not yet migrated. Action: same transitional shim path.
3. `skills/jot/scripts/jot-state-lib.sh` -- not yet migrated. Action: shim.
4. `skills/jot/scripts/jot-session-start.sh` -- not yet migrated. Action: shim.
5. `skills/jot/scripts/jot-stop.sh` -- transitive via jot-state-lib.sh. Action: covered by #3's shim.
6. `skills/jot/scripts/jot.sh` -- not yet migrated AND copies `tmux.sh` into `$TMPDIR_INV`. Action: shim, AND update `cp` block to also copy `tmux_lib.py` alongside the shim. Pre-commit grep guard: `grep -L 'tmux_lib.py' jot.sh` must be empty.
7. `skills/todo/scripts/todo-session-start.sh` -- not yet migrated. Action: shim.
8. `skills/todo/scripts/todo-stop.sh` -- not yet migrated. Action: shim.
9. `skills/todo/scripts/todo-launcher.sh` -- not yet migrated AND copies `tmux.sh` into `$TMPDIR_INV`. Action: shim, AND update `cp` block to also copy `tmux_lib.py`. Same grep guard as #6.
10. `skills/debate/scripts/debate-tmux-orchestrator.sh` -- not yet migrated. Action: shim.
11. `skills/debate/scripts/OLD_DISCARD/debate-tmux-orchestrator.sh` -- dead code. Action: none (left to die with directory).
12. `skills/debate/tests/archive/test.sh` -- archive. Action: none.
13. `skills/plate/scripts/archive/plate-worker-start.sh` -- archive. Action: none.
14. `skills/plate/tests/plate-e2e-live.sh` -- live e2e. Action: shim keeps it working; verify in step 8.
15. `skills/plate/tests/plate-claude-e2e.sh` -- live e2e. Action: shim keeps it working; verify in step 8.
16. `tests/tmux-send-test.sh` -- repo-level test. Action: shim keeps it working; verify in step 8.

Subprocess callers: none.

Per migration philosophy: while any of #1-#10, #14-#16 remain bash, `tmux.sh` survives marked `[s]` (transitional shim, body is `exec python3 -c ...` per function). Only when ALL bash sourcers migrate or are deleted does `tmux.sh` get removed.

## RED tests (`tests/test_tmux_lib.py`)

Pytest. Two tiers. Tests assert on return values and side effects. No stdout-shape assertions except for the one mandated log line in `tmux_cancel_and_send`.

### Tier A -- mocked `_invoke` (fast, deterministic)

Mock target: `common.scripts.tmux_lib._invoke`. Verify exact `tmux ...` argv assembled per call AND verify the function's return value.

Cases:
- `require_version_passes_when_installed_meets_min` -- mock `tmux -V` -> `tmux 3.4`, call with `"3.0"` -> returns 0.
- `require_version_fails_when_below_min` -- returns 1.
- `require_version_fails_when_tmux_missing` -- FileNotFoundError -> returns 1.
- `set_option_t_builds_correct_argv` -- argv `["set-option","-t","s","remain-on-exit","off"]`, returns 0.
- `set_option_g_builds_correct_argv`.
- `set_option_w_builds_correct_argv`.
- `has_session_returns_zero_on_match`, `has_session_returns_one_on_miss`.
- `new_session_passes_extra_args_through` -- `new_session("s","-n","w","-c","/tmp","sleep 99")` -> argv ends with those tokens in order.
- `kill_session_builds_correct_argv`.
- `list_clients_returns_rc_and_stdout`.
- `new_pane_returns_pane_id_when_dash_P_in_extras` -- mock stdout `"%42\n"`, return value `(0, "%42\n")`.
- `kill_pane_builds_correct_argv`.
- `capture_pane_omits_S_when_lines_none` -- argv has no `-S`.
- `capture_pane_includes_negative_S_when_lines_set` -- `lines=200` -> argv has `-S` `-200`.
- `capture_pane_returns_rc_and_stdout`.
- `list_panes_default_format_when_no_extra_args`.
- `list_panes_uses_extra_args_when_provided`.
- `list_windows_default_format_vs_extra_args`.
- `select_pane_builds_correct_argv`.
- `set_pane_title_builds_correct_argv`.
- `new_window_passes_extra_args_through`.
- `kill_window_builds_correct_argv`.
- `window_exists_returns_true_for_exact_match` -- mock list_windows stdout `"work\nworker\n"`, returns True for `"work"`, False for `"wor"`.
- `pane_has_title_returns_true_for_exact_match`.
- `split_window_h_maps_to_dash_h`.
- `split_window_v_maps_to_dash_v`.
- `split_window_rejects_other_directions` -- returns nonzero, no `_invoke` call made.
- `select_layout_passes_layout_string`.
- `retile_calls_select_layout_with_tiled` -- assert exactly one underlying invocation with `tiled`.
- `send_keys_does_not_append_enter` -- argv exactly `["send-keys","-t",t,text]`.
- `send_enter_sends_only_enter`.
- `send_Ctrl_c_sends_C_c`.
- `send_and_submit_makes_two_separate_invoke_calls` -- exactly TWO `_invoke` calls; first with text, second with `Enter`. Sleep is mocked.
- `cancel_and_send_breaks_when_marker_seen_first_attempt` -- capture mock returns `"... Ctrl-C ..."` immediately. Exactly 1 `C-c` invoke, no log line.
- `cancel_and_send_retries_up_to_five_times` -- capture never shows marker. Exactly 5 `C-c` invokes, then `send_and_submit` runs.
- `cancel_and_send_logs_label_after_retry` -- capsys captures stdout `"[tmux] cancelled in-progress work: work-1 (2 Ctrl-C's)"`.
- `cancel_and_send_silent_when_no_label` -- capsys stdout has no `cancelled in-progress` line.
- `cancel_and_send_returns_send_and_submit_exit_code` -- final submit rc=7 -> overall rc=7.
- `send_keys_propagates_subprocess_failure` -- invoke rc=1 -> function returns 1.

### Tier B -- live tmux server (skip if `tmux` not on PATH or env `TMUX_LIVE_TESTS` unset)

Pytest fixture creates unique session `f"tmux-py-test-{os.getpid()}-{uuid4().hex[:6]}"` and tears down. Replaces the bash `_tests` semantics. Side-effect assertions only.

- `live_session_lifecycle` -- has_session false; new_session; has_session true; kill_session; has_session false.
- `live_send_keys_text_visible_in_capture` -- send `f"marker-{pid}"`, sleep 0.1, capture contains marker.
- `live_send_keys_does_not_submit` -- send `"echo X"`, capture does NOT show `X` output (Enter not pressed).
- `live_send_and_submit_executes_command` -- send `f"echo go-{pid}"`, sleep 0.3, capture shows `f"go-{pid}"`.
- `live_cancel_and_send_cancels_running_sleep` -- submit `sleep 10`, then `cancel_and_send(... f"echo replaced-{pid}")`, replacement appears within ~1s.
- `live_cancel_and_send_logs_label` -- capsys captures label string from the call.
- `live_window_exists_true_after_new_window_false_for_unknown`.
- `live_split_window_creates_two_panes` -- pane count goes 1 -> 2.
- `live_set_pane_title_then_pane_has_title_true`.
- `live_capture_pane_with_lines_returns_more_data_than_without` -- write 100 echo lines; lines=200 capture strictly longer than default capture.
- `live_send_keys_fails_on_nonexistent_target` -- returns nonzero.
- `live_set_option_t_remain_on_exit_off_round_trips` via `tmux show-options -t <s> -v remain-on-exit`.

## Risk callouts

1. **Send-keys escape sequences.** Pass `text` as one argv element; never shell-quote, never split on whitespace.
2. **Two-call submit is load-bearing.** Must be two separate `tmux send-keys` invocations.
3. **Timing-sensitive cancel loop.** 0.2s sleep, 5-attempt cap, `'Ctrl-C'` literal marker -- all tuned for Claude Code TUI. Do not change without live verification.
4. **Capture-after-send discipline.** Document at module top.
5. **Terminal width / wrapping.** capture buffer wraps long lines. Tests use fixed-string substring contains. Markers stay short (<40 chars).
6. **`#{...}` format strings.** Pass as plain strings; avoid f-strings consuming `{`.
7. **Variadic extras.** Bash `${@:2}` -> Python `*extra: str`. Verify `-c /path` and trailing shell-command-with-spaces survive intact.
8. **`invoke_command` parity.** Until `invoke_command.sh` is migrated, replicate logging directly inside `_invoke()` (no extra subshell). Document the parity assumption.
9. **Copied-into-`$TMPDIR_INV` callers.** `jot.sh` and `todo-launcher.sh` `cp` the source. Same-commit edit: also copy `tmux_lib.py`. Pre-commit grep guard: `grep -L 'tmux_lib.py' jot.sh todo-launcher.sh` must be empty.
10. **`tmux-launcher.sh` interaction.** Stays bash; relies on the transitional shim (or its own future migration) to keep `tmux_*` names available.

## Numbered TODO list (template steps 0-8)

0. Create this numbered list.
1. Mark `common/scripts/tmux.sh` as `[i]` in `MIGRATION_TO_PYTHON.md` (every line that lists it).
2. Confirm plan reviewed; flip `[i]` -> `[p]`.
3. **Scaffold.** Write `common/scripts/tmux_lib.py` containing every function from the function table. Each: identical name, typed signature, declared return type, body of `print("TODO: <function_name>")` and nothing else. Module imports cleanly; functions callable; no real tmux work.
4. **RED tests.** Write `tests/test_tmux_lib.py`. Tier A (mocked, ~38 cases) + Tier B (live, env-gated). Tests import the scaffold and call each stub by name. Assert on return values and file/env side effects only -- never on captured stdout except the mandated cancel-log line.
5. **Confirm RED.** Run `pytest tests/test_tmux_lib.py -v`. Every test fails on assertion (not on import). If anything errors on import or signature mismatch, fix scaffold first.
6. Flip `[p]` -> `[~]` in tracker.
7. **GREEN, callees first.** Implement bodies bottom-up, one or a small cluster at a time. Run pytest after each; confirm tests flip red -> green without breaking others. Commit per body or cluster. Order:
   1. `_invoke` helper (foundational seam).
   2. Version + option group: `tmux_require_version`, `tmux_set_option`, `tmux_set_option_t`, `tmux_set_option_g`, `tmux_set_option_w`.
   3. Session group: `tmux_has_session`, `tmux_new_session`, `tmux_kill_session`, `tmux_list_clients`.
   4. Pane primitives: `tmux_kill_pane`, `tmux_select_pane`, `tmux_set_pane_title`, `tmux_capture_pane`, `tmux_new_pane`, `tmux_list_panes`.
   5. Window primitives: `tmux_kill_window`, `tmux_new_window`, `tmux_list_windows`, then derived `tmux_window_exists`, `tmux_pane_has_title`, `tmux_split_window`.
   6. Layout: `tmux_select_layout`, then `tmux_retile`.
   7. Send primitives: `tmux_send_keys`, `tmux_send_enter`, `tmux_send_Ctrl_c`.
   8. Send composites: `tmux_send_and_submit` (depends on send_keys + send_enter), then `tmux_cancel_and_send` (depends on send_Ctrl_c + capture_pane + send_and_submit).
8. **Update callers.** For each entry in the Callers section: install transitional `[s]` shim on `tmux.sh` whose body is one `exec python3 -c 'from tmux_lib import <fn>; sys.exit(<fn>(*sys.argv[1:]))'` line per public function, OR migrate the bash caller in the same change. Update `jot.sh` and `todo-launcher.sh` to copy `tmux_lib.py` into `$TMPDIR_INV`. Run full live verification (Tier B pytest + repo-level e2e tests). Mark `[s]`.
9. **Delete.** Once every bash sourcer in the Callers list (excluding archive/dead) has migrated to Python, delete `common/scripts/tmux.sh` and remove the shim. Mark `[x]`.
10. **End-to-end verify.** `pytest tests/test_tmux_lib.py -v` GREEN; `TMUX_LIVE_TESTS=1 pytest -v -k live_` GREEN; `bash tests/tmux-send-test.sh` passes (against shim); `bash skills/plate/tests/plate-e2e-live.sh` passes; `bash skills/plate/tests/plate-claude-e2e.sh` passes. Failing-verification check: temporarily break `tmux_send_and_submit` to issue ONE invoke instead of two -- live `live_send_and_submit_executes_command` MUST fail. Restore.
