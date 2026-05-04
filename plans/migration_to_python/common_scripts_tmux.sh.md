# Migrate `common/scripts/tmux.sh` to Python

## Source

- File: `common/scripts/tmux.sh`
- Class: `(sourced)` — every caller pulls it via `source` / `.`. Never invoked as a subprocess.
- Size: ~830 lines bash. ~30 public `tmux_*` functions plus 7 in-file `_tests` suites.
- Dependency graph: leaf primitive layer over `invoke_command` (silencers/permissions). Sourced by `tmux-launcher.sh`, `platform.sh`, `jot-state-lib.sh`, `jot-session-start.sh`, `todo-session-start.sh`, `todo-stop.sh`, `todo-launcher.sh`, `debate-tmux-orchestrator.sh`, `plate-worker-start.sh` (archive), and the e2e test scripts. Migration is GATE for every other tmux-touching `.sh`.

## Caller list (excluding `tmux-launcher.sh`)

Sourced by:
- `common/scripts/platform.sh`
- `skills/jot/scripts/jot-state-lib.sh`
- `skills/jot/scripts/jot-session-start.sh`
- `skills/jot/scripts/jot-stop.sh` (transitively via `jot-state-lib.sh`)
- `skills/jot/scripts/jot.sh` (copies file into `$TMPDIR_INV`)
- `skills/todo/scripts/todo-session-start.sh`
- `skills/todo/scripts/todo-stop.sh`
- `skills/todo/scripts/todo-launcher.sh` (sources AND copies into `$TMPDIR_INV`)
- `skills/debate/scripts/debate-tmux-orchestrator.sh`
- `skills/debate/scripts/OLD_DISCARD/debate-tmux-orchestrator.sh` (dead)
- `skills/debate/tests/archive/test.sh` (archive)
- `skills/plate/scripts/archive/plate-worker-start.sh` (archive)
- `skills/plate/tests/plate-e2e-live.sh`, `skills/plate/tests/plate-claude-e2e.sh`
- `tests/tmux-send-test.sh`

Not invoked as subprocess anywhere. Pure `(sourced)` class.

## Behavior spec — per function

All functions wrap `invoke_command tmux <subcmd>` so they participate in the shared logging/permission seam. Python port must call `subprocess.run(["tmux", ...])` through a single `_invoke()` helper that mirrors `invoke_command` semantics (stdout passthrough, stderr passthrough, return code = exit code).

### Version / option group
1. `tmux_require_version(min_version)` — parse `tmux -V`, regex `[0-9]+\.[0-9]+`, use `packaging.version` or tuple compare. Returns 0 on satisfied, 1 + stderr msg otherwise.
2. `tmux_set_option(*args)` — passthrough to `tmux set-option`.
3. `tmux_set_option_t(target, name, value)` — `set-option -t <target>`.
4. `tmux_set_option_g(name, value)` — `set-option -g`.
5. `tmux_set_option_w(window_target, name, value)` — `set-option -w -t`.

### Session group
6. `tmux_has_session(session)` — `has-session -t`. Returns bool/exit code.
7. `tmux_new_session(session, *extra)` — `new-session -d -s <session>` + extra args (window, cwd, command).
8. `tmux_kill_session(session)` — `kill-session -t`.
9. `tmux_list_clients(session)` — `list-clients -t`. Stdout is the meaningful return.

### Pane group
10. `tmux_new_pane(target, *extra)` — `split-window -t`. When `-P -F '#{pane_id}'` in extras, stdout is the new pane id.
11. `tmux_kill_pane(pane_target)`.
12. `tmux_capture_pane(pane_target, lines=None)` — `capture-pane -p -t <t> [-S -<lines>]`. Stdout is captured buffer. CRITICAL primitive for the "capture-after-send" discipline.
13. `tmux_list_panes(target, *extra)` — default format `'#{pane_id} #{pane_title}'`. Extra args override.
14. `tmux_select_pane(pane_target)`.
15. `tmux_set_pane_title(pane_target, title)` — `select-pane -t <t> -T <title>`.

### Window group
16. `tmux_new_window(session, name, *extra)` — `new-window -t <s> -n <name>`.
17. `tmux_kill_window(window_target)`.
18. `tmux_list_windows(session, *extra)` — default format `'#{window_index} #{window_name}'`.
19. `tmux_window_exists(session, window_name)` — exact-name match against `list_windows` output.
20. `tmux_pane_has_title(target, title)` — exact-title match against `list_panes` titles.
21. `tmux_split_window(target, direction)` — `direction in {'h','v'}` -> `-h` / `-v`.

### Layout group
22. `tmux_select_layout(target, layout)` — accepts `even-horizontal | even-vertical | main-horizontal | main-vertical | tiled`.
23. `tmux_retile(target)` — alias for `select_layout(target, 'tiled')`.

### Send-keys group (capture-after-send discipline lives here)
24. `tmux_send_keys(target, text)` — `send-keys -t <t> <text>`. Does NOT append Enter.
25. `tmux_send_enter(target)` — `send-keys -t <t> Enter`.
26. `tmux_send_Ctrl_c(target)` — `send-keys -t <t> C-c`.
27. `tmux_send_and_submit(target, text)` — TWO separate `send-keys` calls (text, then Enter) on purpose — some TUIs drop Enter when bundled. Port must preserve the two-call pattern.
28. `tmux_cancel_and_send(target, text, label=None)` — encodes the `Capture tmux pane after every send` rule:
    - Loop up to 5 times: send `C-c`, sleep 0.2s, `capture_pane`, scan buffer for literal `'Ctrl-C'` marker, break when seen.
    - If retries > 0 and label non-empty: log `"[tmux] cancelled in-progress work: <label> (<n+1> Ctrl-C's)"` to stdout.
    - Then `send_and_submit(target, text)`.
    - Returns final `send_and_submit` exit code.
    Python port keeps the SAME loop count, sleep, marker, and log format (callers grep for it).

## Target Python module path

- `common/scripts/tmux_lib.py` — pure library. All public names match bash exactly (`tmux_require_version`, …, `tmux_cancel_and_send`).
- `common/scripts/tmux_cli.py` — argparse dispatcher. Subcommand per public function: `python3 tmux_cli.py send-keys <target> <text>`, `python3 tmux_cli.py capture-pane <target> [--lines N]`, etc. Subcommand names use hyphens; map to underscored library names.
- `common/scripts/tmux.sh` becomes a thin shim (see Shim section).

Rationale: matches the `git.sh` migration pattern (`git_lib.py` + `git_cli.py`) already established in this repo.

## `_cli.py` shim contract

Each subcommand:
- Reads positional args matching the bash signature 1:1.
- Forwards `*extra` argv tail unchanged via `argparse.REMAINDER` for the variadic functions (`new_session`, `new_pane`, `list_panes`, `list_windows`, `new_window`, `set_option`).
- Prints library stdout to stdout verbatim.
- Exits with library return code.
- `capture-pane` accepts an optional positional `[lines]` to mirror `tmux_capture_pane "$1" [lines]`.

## Shim (final `.sh` body)

```bash
#!/bin/bash
# tmux.sh — thin shim. Real implementation in tmux_lib.py / tmux_cli.py.
# Functions remain source-able so callers do not change.

_TMUX_CLI="$(dirname "${BASH_SOURCE[0]}")/tmux_cli.py"

tmux_require_version()  { python3 "$_TMUX_CLI" require-version "$@"; }
tmux_set_option()       { python3 "$_TMUX_CLI" set-option "$@"; }
tmux_set_option_t()     { python3 "$_TMUX_CLI" set-option-t "$@"; }
tmux_set_option_g()     { python3 "$_TMUX_CLI" set-option-g "$@"; }
tmux_set_option_w()     { python3 "$_TMUX_CLI" set-option-w "$@"; }
tmux_has_session()      { python3 "$_TMUX_CLI" has-session "$@"; }
tmux_new_session()      { python3 "$_TMUX_CLI" new-session "$@"; }
tmux_kill_session()     { python3 "$_TMUX_CLI" kill-session "$@"; }
tmux_list_clients()     { python3 "$_TMUX_CLI" list-clients "$@"; }
tmux_new_pane()         { python3 "$_TMUX_CLI" new-pane "$@"; }
tmux_kill_pane()        { python3 "$_TMUX_CLI" kill-pane "$@"; }
tmux_capture_pane()     { python3 "$_TMUX_CLI" capture-pane "$@"; }
tmux_list_panes()       { python3 "$_TMUX_CLI" list-panes "$@"; }
tmux_select_pane()      { python3 "$_TMUX_CLI" select-pane "$@"; }
tmux_set_pane_title()   { python3 "$_TMUX_CLI" set-pane-title "$@"; }
tmux_new_window()       { python3 "$_TMUX_CLI" new-window "$@"; }
tmux_kill_window()      { python3 "$_TMUX_CLI" kill-window "$@"; }
tmux_list_windows()     { python3 "$_TMUX_CLI" list-windows "$@"; }
tmux_window_exists()    { python3 "$_TMUX_CLI" window-exists "$@"; }
tmux_pane_has_title()   { python3 "$_TMUX_CLI" pane-has-title "$@"; }
tmux_split_window()     { python3 "$_TMUX_CLI" split-window "$@"; }
tmux_select_layout()    { python3 "$_TMUX_CLI" select-layout "$@"; }
tmux_retile()           { python3 "$_TMUX_CLI" retile "$@"; }
tmux_send_keys()        { python3 "$_TMUX_CLI" send-keys "$@"; }
tmux_send_enter()       { python3 "$_TMUX_CLI" send-enter "$@"; }
tmux_send_Ctrl_c()      { python3 "$_TMUX_CLI" send-ctrl-c "$@"; }
tmux_send_and_submit()  { python3 "$_TMUX_CLI" send-and-submit "$@"; }
tmux_cancel_and_send()  { python3 "$_TMUX_CLI" cancel-and-send "$@"; }
```

In-file `_tests` functions are dropped from the shim. Their behavior is recreated in `tests/test_tmux_lib.py` (live-tmux integration) — see RED scenarios.

## RED test scenarios (pytest)

Two tiers. Plain-English first, then failing assertions.

### Tier A — mocked `subprocess.run` (fast, deterministic)

Mock target: `common.scripts.tmux_lib._invoke`. Verify exact `tmux ...` argv assembled per call.

- `require_version_passes_when_installed_meets_min` — mock `tmux -V` -> `tmux 3.4`, call `tmux_require_version("3.0")` -> exit 0.
- `require_version_fails_when_below_min` — mock `tmux -V` -> `tmux 2.9`, call with `"3.0"` -> exit 1, stderr contains `"tmux 3.0+ required"`.
- `require_version_fails_when_tmux_missing` — `tmux -V` raises FileNotFoundError -> exit 1, stderr `"tmux is not installed"`.
- `set_option_t_builds_correct_argv` — call `tmux_set_option_t("s", "remain-on-exit", "off")` -> `_invoke` got `["tmux","set-option","-t","s","remain-on-exit","off"]`.
- `set_option_g_builds_correct_argv`
- `has_session_returns_zero_on_match`, `_returns_one_on_miss`
- `new_session_passes_extra_args_through` — `tmux_new_session("s","-n","w","-c","/tmp","sleep 99")` -> argv ends with those exact tokens.
- `capture_pane_omits_S_when_lines_none` — argv has no `-S`.
- `capture_pane_includes_negative_S_when_lines_set` — `lines=200` -> argv has `-S -200`.
- `list_panes_default_format_when_no_extra_args` — argv ends `-F #{pane_id} #{pane_title}`.
- `list_panes_uses_extra_args_when_provided` — extra `-F #{pane_title}` overrides default.
- `list_windows_default_format_vs_extra_args` — symmetric pair.
- `window_exists_matches_exact_name_only` — given `list_windows` output `"0 work\n1 worker\n"`, `tmux_window_exists("s","work")` -> 0; `_("s","wor")` -> 1.
- `pane_has_title_matches_exact_only` — given titles `"keepalive\nworker\n"`, exact-match semantics.
- `split_window_h_maps_to_dash_h` — direction `'h'` -> argv `["...","split-window","-h","-t","target"]`.
- `split_window_v_maps_to_dash_v`
- `split_window_rejects_other_directions` — `'x'` -> nonzero exit.
- `select_layout_passes_layout_string`
- `retile_calls_select_layout_with_tiled`
- `send_keys_does_not_append_enter` — argv exactly `["tmux","send-keys","-t",t,text]`, no `Enter`.
- `send_enter_sends_only_enter`
- `send_ctrl_c_sends_C_c`
- `send_and_submit_makes_two_separate_invoke_calls` — assert exactly TWO `_invoke` calls, first with `text`, second with `Enter`.
- `cancel_and_send_breaks_when_marker_seen_first_attempt` — `capture_pane` mock returns `"... Ctrl-C ..."` immediately. Exactly 1 `C-c`, no log line on stdout.
- `cancel_and_send_retries_up_to_five_times` — capture mock never shows marker. 5 `C-c` sent, then `send_and_submit` still runs.
- `cancel_and_send_logs_label_after_retry` — first capture has no marker, second does. With label `"work-1"`, stdout contains `"[tmux] cancelled in-progress work: work-1 (2 Ctrl-C's)"`.
- `cancel_and_send_silent_when_no_label_given` — retries occur but stdout has no `cancelled in-progress` line.
- `cancel_and_send_returns_send_and_submit_exit_code` — final submit exits 7 -> overall 7.
- `send_keys_propagates_subprocess_failure` — invoke returns nonzero -> function returns same code.

### Tier B — live tmux server (skip if `tmux` not on PATH or `TMUX_LIVE_TESTS` unset)

Use `pytest.fixture` that creates a unique session name `f"tmux-py-test-{os.getpid()}-{uuid4().hex[:6]}"` and tears it down. Wraps the existing bash `_tests` semantics.

- `live_new_session_then_has_session_then_kill_session_lifecycle`
- `live_send_keys_text_visible_in_capture` — send `"marker-<pid>"`, sleep 0.1, `capture_pane` contains marker.
- `live_send_keys_does_not_submit` — send `echo X`, capture must NOT show `X` output (Enter not pressed).
- `live_send_and_submit_executes_command` — send `"echo go-<pid>"`, sleep 0.3, capture shows `go-<pid>`.
- `live_cancel_and_send_cancels_running_sleep` — submit `sleep 10`, then `cancel_and_send(... "echo replaced-<pid>")`, replacement appears within ~1s (proves cancellation).
- `live_cancel_and_send_logs_label` — stdout from the call contains label.
- `live_window_exists_true_after_new_window_false_for_unknown`
- `live_split_window_creates_two_panes` — `list_panes` count goes from 1 to 2.
- `live_set_pane_title_then_pane_has_title_true`
- `live_capture_pane_with_lines_returns_more_data_than_without` — write 100 echo lines, compare `capture_pane(t)` vs `capture_pane(t, lines=200)` — second is strictly longer.
- `live_send_keys_fails_on_nonexistent_target` — return code != 0.

## Risk callouts

1. **Send-keys escape sequences.** tmux interprets tokens like `Enter`, `C-c`, `Space`, `\;`. The bash code passes raw strings — Python must NOT shell-quote text args, and must NOT split on whitespace. Pass via `subprocess.run(args_list)` with text as a single argv element.
2. **Two-call submit pattern is load-bearing.** `tmux_send_and_submit` MUST issue two separate `tmux send-keys` invocations; some TUIs (Claude Code, Gemini) drop a trailing `Enter` if bundled. Test asserts two `_invoke` calls.
3. **Timing-sensitive cancel loop.** The 0.2s sleep and 5-attempt cap are tuned to Claude Code TUI cancel-marker rendering. Do not change without re-running the live cancel test against an actual Claude pane.
4. **Capture-after-send discipline.** Per global memory rule, every send wrapper that needs to verify delivery must call `capture_pane` after. `tmux_cancel_and_send` is the canonical example — port preserves it. Document the rule at module top so future contributors do not "optimize" away the capture loop.
5. **Terminal width / wrapping.** `capture_pane` returns the visible buffer — long lines wrap and a substring may be split across rows. Tests must use `grep -F` style fixed-string contains, not regex anchors. Marker strings stay short (<40 chars).
6. **`#{...}` format strings.** Bash does not expand `#{pane_id}` because it is not `${...}`. Python equally must pass them as plain strings; only risk is f-string accidentally consuming `{`. Use raw strings or `.format()` avoidance.
7. **Variadic `${@:2}` semantics.** Bash splices remaining args. Python `argparse.REMAINDER` is the closest match but eats `--`; verify `new_session` extra args including `-c /path` and a trailing shell command (with spaces) survive intact.
8. **`invoke_command` parity.** The bash version routes every tmux call through `invoke_command` (logging + permission seam). Until `invoke_command.sh` is migrated, `_invoke()` must shell out to `bash -c 'source invoke_command.sh; invoke_command tmux ...'` OR replicate logging directly. Decision: replicate logging directly in Python — same env contract, no extra subshell — and document the parity assumption.
9. **`copied into $TMPDIR_INV` callers.** `jot.sh` and `todo-launcher.sh` `cp` the `.sh` into a sandbox dir and source it from there. The shim must remain a self-contained `.sh` that finds `tmux_cli.py` via `dirname "${BASH_SOURCE[0]}"` — but those callers also need to copy `tmux_lib.py` and `tmux_cli.py` alongside. **Dependent edit**: update both launcher scripts in the same commit to also `cp` the two `.py` files. Add an explicit pre-commit grep check: `grep -L 'tmux_lib.py' jot.sh todo-launcher.sh` must be empty.
10. **`tmux-launcher.sh` interaction.** Stays as bash for now (separate plan). It sources `tmux.sh`, so the function-name shim contract is what keeps it working. Any rename breaks `tmux-launcher`.

## Verification

1. `pytest tests/test_tmux_lib.py -v -k 'not live_'` -> GREEN (mocked tier).
2. `TMUX_LIVE_TESTS=1 pytest tests/test_tmux_lib.py -v -k live_` -> GREEN against real tmux.
3. `bash tests/tmux-send-test.sh` -> still passes against the shim.
4. `bash skills/plate/tests/plate-e2e-live.sh` -> still passes.
5. `bash skills/plate/tests/plate-claude-e2e.sh` -> still passes.
6. Smoke: `source common/scripts/tmux.sh && tmux_new_session smoke-$$ && tmux_has_session smoke-$$ && tmux_kill_session smoke-$$` exits 0.
7. Smoke: `source common/scripts/tmux-launcher.sh && tmux_ensure_session smoke2-$$ work /tmp 'sleep 5' keepalive && tmux_kill_session smoke2-$$` exits 0 (proves shim contract holds for downstream sourcer).
8. Failing-verification design: temporarily break `tmux_send_and_submit` to issue ONE invoke call instead of two; the live `live_send_and_submit_executes_command` test must FAIL. Restore.
9. Post-verification: every grep `tmux\.sh` caller still functions unmodified.

## Numbered TODO list (template steps 0-8)

0. Build this numbered list (this section).
1. Mark `common/scripts/tmux.sh` as `[i]` in `MIGRATION_TO_PYTHON.md` (every occurrence — there are ~10 lines listing it across orchestrator dependency tables).
2. Confirm this plan reviewed; flip `[i]` -> `[p]` in `MIGRATION_TO_PYTHON.md`.
3. Write RED tests in `tests/test_tmux_lib.py`:
   - Tier A mocked tests for every function listed in Behavior spec (~30 cases).
   - Tier B live tmux tests behind `TMUX_LIVE_TESTS` env gate.
   - Confirm all tests fail (no `tmux_lib.py` exists yet).
4. Flip `[p]` -> `[~]` in `MIGRATION_TO_PYTHON.md` so other agents stand down.
5. Implement `common/scripts/tmux_lib.py`:
   - `_invoke(*args)` helper -> `subprocess.run(["tmux", *args], text=True, ...)`, returns `CompletedProcess`-like with `.returncode`, `.stdout`, prints stderr passthrough.
   - All 28 public functions as pure Python; signatures mirror bash arg order.
   - `tmux_cancel_and_send` keeps the 5-attempt loop, 0.2s sleep, `Ctrl-C` literal marker scan, and exact log format `"[tmux] cancelled in-progress work: <label> (<n+1> Ctrl-C's)"`.
6. Implement `common/scripts/tmux_cli.py` argparse dispatcher with one subcommand per public function. Implement `capture-pane --lines` and the variadic forwards.
7. Run pytest until both tiers GREEN. Iterate `tmux_lib.py` until done. Do NOT touch the shim before this is done.
8. Replace `common/scripts/tmux.sh` body with the function-shim block above. Update `skills/jot/scripts/jot.sh` and `skills/todo/scripts/todo-launcher.sh` to also `cp tmux_lib.py` and `cp tmux_cli.py` into `$TMPDIR_INV`. Run full verification list (steps 1-9 in Verification). Flip `[~]` -> `[x]` in `MIGRATION_TO_PYTHON.md`. Note in tracker: `tmux-launcher.sh` (separate file) is now unblocked.

