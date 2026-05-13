# Test Coverage Audit - Codex

Generated: 2026-05-12

Source of truth: `docs/design/call_graph.md` and `docs/design/call_graph.json`.

Scope: compare call graph leaves against the pytest suite and identify paths that are untested or weakly/incorrectly tested.

## Method

- Parsed the generated call graph leaf IDs from `docs/design/call_graph.json`.
- Collected tests with `pytest --collect-only -q`: 986 tests collected.
- Ran a best-effort stdlib `trace` execution pass against pytest to identify terminal lines not executed by the suite.
- Used subagents to inspect test files in parallel for:
  - todo/jot lifecycle paths,
  - diagnostics/tmux/util paths,
  - orchestrator routing and plate summary paths.

Runtime note: the full trace run was affected by sandbox tmux socket permissions. Live tmux tests failed because tmux could not connect to `/private/tmp/tmux-501/default`. A non-live run still had one environment-sensitive failure in `tests/test_todo_send.py::test_todo_launcher_success` because the tmux-launch lock could not be acquired. Findings below are therefore based on source inspection plus best-effort execution evidence.

## Confirmed Untested Leaves

### Audit Rotation Cleanup

- `L#27`, `L#146`
- Production: `common/scripts/jot_lib.py:105-110`
- Path: `jot_rotateAudit` exception cleanup and re-raise after temp-file creation.
- Existing tests: `tests/test_jot_audit.py` covers missing file, short file, successful truncation, custom max, and no sidecar.
- Gap: no test forces `os.fdopen`, write, or `os.replace` failure after `mkstemp`, so temp cleanup and re-raise are untested.
- Why: current tests only exercise no-op and successful rotation paths; they never inject a mid-rotation failure after the temporary file exists.

### Todo Markdown Read Failure

- `L#32`
- Production: `common/scripts/todo_lib.py:581`
- Path: `_todo_has_open_status` catches `OSError` and returns `False`.
- Existing tests: `tests/test_todo_list.py` covers missing `Todos/`, no markdown, open/closed status, sorting, anchored match, first-ten-lines behavior, absolute paths, and string path input.
- Gap: no test makes `path.open()` raise `OSError`.
- Why: current tests use normal readable files, so they validate parsing rules but not the defensive unreadable-file branch.

### Todo Launcher Guard Rails

- `L#35-L#39`
- Production: `common/scripts/todo_lib.py:259-294`
- Paths:
  - missing `session_id`,
  - missing `idea`,
  - missing `pending_file_path`,
  - nonexistent pending file,
  - invalid/unreadable pending JSON.
- Existing tests: only `tests/test_todo_send.py::test_todo_launcher_success` directly covers `todo_launcher`.
- Gap: all guard/error returns are untested.
- Why: the only direct launcher test builds a fully valid pending request, so none of the argument or pending-file validation branches are reached.

### Todo Launcher Unavailable Fallbacks

- `L#41`, `L#43`, `L#45`, `L#47`
- Production: `common/scripts/todo_lib.py:311-318`, via `common/scripts/util_lib.py:114-116`
- Paths: `_util_hide_errors` fallback to `"(unavailable)"` for:
  - branch lookup,
  - recent commits,
  - uncommitted filenames,
  - open todo scan.
- Existing tests: `test_todo_launcher_success` stubs all four dependencies to succeed.
- Gap: no test makes any dependency raise.
- Why: current mocks model only the successful collector path, so `_util_hide_errors` is never asked to convert collector failures into `"(unavailable)"`.

### Todo Launcher Tmux Failures

- `L#116`, `L#120`
- Production: `common/scripts/todo_lib.py:416-429`
- Paths:
  - `tmux_splitWorkerPane` returns empty pane id,
  - lock/tmux setup raises and returns `1`.
- Existing tests: success path always returns `"%123"` and uses a successful fake `FileLock`.
- Gap: failure branches are untested.
- Why: current tmux and lock doubles always succeed, so the launcher never observes an empty pane id or lock/setup exception.

### Terminal Client Listing Helper

- `L#122-L#124`
- Production: `common/scripts/util_lib.py:256-268`
- Path: `_terminal_listTmuxClients` subprocess return handling.
- Existing tests: `tests/test_util_terminal.py` patches `_terminal_listTmuxClients` when testing `terminal_spawnIfNeeded`.
- Gap: direct helper behavior is not tested:
- Why: current terminal-spawn tests mock `_terminal_listTmuxClients` itself, so they test callers while bypassing the helper's subprocess handling.
  - tmux argv shape,
  - nonzero return gives empty string,
  - stdout passthrough,
  - `OSError` / `FileNotFoundError` returns empty string.

### Darwin Terminal Edge Cases

- `L#126`, `L#128`, `L#135`
- Production: `common/scripts/util_lib.py:175-213`, `common/scripts/util_lib.py:287-297`
- Paths:
  - `_terminal_appendAdvisory` `/dev/null` or missing-log guard,
  - `_terminal_appendAdvisory` `OSError` swallow,
  - Darwin `subprocess.Popen` failure in `terminal_spawnIfNeeded`.
- Existing tests: main Darwin spawn, missing osascript success advisory, non-Darwin advisory, and non-Darwin advisory write failure are covered.
- Gap: these Darwin-specific edge branches are not asserted.
- Why: current tests cover the common Darwin success and non-Darwin failure cases, but do not force Darwin advisory write failure or `Popen` failure.

### Diagnostic Tail Reads

- `L#213`, `L#214`, `L#250`, `L#251`
- Production: `common/scripts/util_lib.py:226-233`
- Call sites: `common/scripts/jot_lib.py:408`, `common/scripts/jot_lib.py:496`
- Paths:
  - successful tail of state `audit.log`,
  - `OSError` tail fallback,
  - successful tail of `JOT_LOG_FILE`,
  - `OSError` tail fallback.
- Existing tests: `tests/test_jot_diag.py` checks broad report sections and several state-dir cases.
- Gap: no test creates long audit/log files to verify tail length, and no test forces read failure.
- Why: current diagnostics tests mostly assert section presence and short fixture text, so they do not prove tail truncation or unreadable-log behavior.

### Tmux Diagnostics Session-Exists Branch

- `L#216-L#239`
- Production:
  - `common/scripts/tmux_lib.py:443-464`
  - `common/scripts/jot_lib.py:425-462`
- Paths:
  - `_tmux_session_exists("jot")` true/false/FileNotFoundError,
  - `_tmux_run` for `list-sessions`,
  - `_tmux_run` for `list-windows`,
  - `_tmux_run` for `list-panes`,
  - `_tmux_run` for pane start command,
  - `_tmux_run` for attached clients,
  - `_tmux_run` for pane capture,
  - `_tmux_run` FileNotFoundError fallbacks.
- Existing tests: `tests/test_jot_diag.py` incidentally calls `jot_collectDiagnostics`, but does not mock `_tmux_session_exists` true or assert the section-3 tmux command outputs.
- Gap: the entire "jot tmux session exists" diagnostics branch is effectively untested.
- Why: current diagnostics fixtures run in the default no-session environment and only check broad section text, so section 3 never enters the detailed tmux command path.

### Orchestrator None Return Fallbacks

- `L#264`
- Production: `scripts/jot_plugin_orchestrator.py:91`
- Path: `handleArgvDispatch` converts a matched route returning `None` into process rc `0`.
- Existing tests: argv stubs return explicit `0`.
- Gap: no argv route test returns `None`.
- Why: current dispatcher tests use handlers that always return an integer, so they never exercise the `None`-to-zero compatibility fallback.

- `L#272`, `L#278`, `L#284`, `L#290`, `L#296`, `L#302`, `L#308`
- Production: `scripts/jot_plugin_orchestrator.py:122`
- Path: `handleStdinDispatch` converts matched prompt handlers returning `None` into process rc `0` for:
  - `/jot`,
  - `/plate`,
  - `/debate`,
  - `/debate-retry`,
  - `/debate-abort`,
  - `/todo`,
  - `/todo-list`.
- Existing tests: prompt-route stubs return explicit `0`.
- Gap: no prompt dispatch test returns `None`.
- Why: current prompt dispatch tests use explicit integer-returning stubs for every route, leaving the matched-but-implicit-success path untested.

### Plate CLI Usage Error

- `L#163`
- Production: `common/scripts/plate/plate_cli.py:167`
- Path: `set-plate-summary` called with wrong arg count returns usage string.
- Existing tests: `skills/plate/tests/sequence/test_plate_cli.py::test_set_plate_summary_cli_routing` covers the happy routing path.
- Gap: no wrong-argument test for this variant.
- Why: current CLI tests call `set-plate-summary` with the correct three arguments, so the usage branch for malformed hook invocation is never reached.

### Plate Summary Trailer Utility Edges

- `L#176-L#180`
- Production: `common/scripts/plate/_rebase_reword_summary.py:72-117`, `common/scripts/plate/_rebase_reword_summary.py:142-165`
- Paths:
  - empty subject no-op,
  - subject replacement/truncation,
  - empty trailer-body formatting,
  - non-empty trailer-body formatting,
  - appending summary trailer around comment blocks.
- Existing tests: `skills/plate/tests/sequence/test_summary_pipeline.py` covers higher-level `plate_regenerateTipSummary` behavior for simple body-only payloads and realistic subject/body payloads.
- Gap: edge branches in the imported helper functions are not isolated.
- Why: current summary tests validate end-to-end trailer rewriting, but their fixtures do not target empty subjects, subject truncation, empty trailer bodies, or comment-block placement directly.

## Weak Or Incorrect Coverage

### `todo_launcher` Happy Path Is Too Monolithic

- Leaves: `L#40`, `L#42`, `L#44`, `L#46`, `L#141`
- Production: `common/scripts/todo_lib.py:311-432`
- Test: `tests/test_todo_send.py::test_todo_launcher_success`
- Issue: the single happy-path test mocks git state, open todo scanning, subprocess calls, permissions loading, lock acquisition, tmux operations, and terminal spawning all at once.
- Consequence: it proves a broad success route, but not:
  - generated input file content,
  - hook JSON contents,
  - sidecar write/rename behavior,
  - pane counter behavior,
  - the rendered unavailable values,
  - exact tmux command arguments.

### `todo_stop` Return-Before-Cleanup Contract Is Weak

- Leaf: `L#148`
- Production: `common/scripts/todo_lib.py:525-528`
- Tests: `tests/test_todo_stop.py` verifies kill/retile calls.
- Issue: tests patch `time.sleep`, removing the production delay inside the daemon cleanup thread.
- Consequence: they verify cleanup eventually happens, but not the documented contract that the hook returns before pane kill/retile completes.

### Plate Summary Stop Only Proves Subprocess Invocation

- Related leaves: `L#161-L#187`
- Production:
  - `common/scripts/plate_dispatcher.py`
  - `common/scripts/plate/plate_cli.py`
  - `common/scripts/plate/plate_lib.py`
- Tests: `tests/test_plate_set_summary_cli.py` and `skills/plate/tests/sequence/test_plate_cli.py`.
- Issue: `plate_summaryStop` tests mock `subprocess.run`, so they verify command forwarding to `plate_cli.py set-plate-summary`, not the actual CLI execution path.
- Consequence: the shell boundary is covered, but not the real integration:
  - `plate_summaryStop -> plate_cli.py set-plate-summary -> plate_regenerateTipSummary`.

## Confirmed Covered Areas

The audit also found several areas with meaningful coverage:

- `tmux_capturePane`: `L#3`, `L#4`, `L#151`, `L#152`
  - Covered by `tests/test_tmux_read.py`.
- `tmux_waitForClaudeReadiness`: `L#5`, `L#6`, `L#153`, `L#154`
  - Covered by `tests/test_tmux_monitor.py`.
- tmux send/submit paths: `L#8-L#11`
  - Covered by `tests/test_tmux_communicate.py` and jot session wiring tests.
- Main `terminal_spawnIfNeeded` behavior:
  - covered for empty session, attached clients, Darwin spawn, maximize variants, missing osascript, non-Darwin advisory, `/dev/null` non-Darwin, and non-Darwin advisory write failure.
- `plate-summary-watch`: `L#188-L#191`
  - Covered by timeout, ready-file, success, and env override tests.
- Basic `jot_collectDiagnostics` report generation:
  - Covered for report file creation, section banners, state-dir cases, dependency section, and return value.

## Highest-Value Test Additions

1. Add `todo_launcher` focused tests for guard returns, invalid pending JSON, `_util_hide_errors` fallbacks, empty pane id, and lock/tmux exception.
2. Add `jot_collectDiagnostics` tests that patch `_tmux_session_exists` true and `_tmux_run` outputs to assert section-3 tmux diagnostics.
3. Add direct tests for `_terminal_listTmuxClients`.
4. Add orchestrator tests where argv and prompt handlers return `None`.
5. Add `set-plate-summary` wrong-arg test and one end-to-end CLI integration test that does not mock `plate_regenerateTipSummary`.
6. Add `jot_rotateAudit` failure-in-cleanup test by forcing a failure after `mkstemp`.
