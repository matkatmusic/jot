# Bash to Python Migration Tracker

Inventory of every shell script in the repo, sorted into what will be
migrated to Python and what will not. Migrate-able items are checkboxes so progress can be tracked file-by-file.

**Before beginning**:
- pick an item labeled "Standalone" from the file list below that isn't marked as `[i]`, `[p]`, `[~]`, `[x]` or `[-]`.  mark it with `[i]`, indicating you're investigating the migration for this file before writing the plan for the migration. 
- generate your plan to migrate the file to python.  use the migration template below and follow it strictly.  
- write your plan to plans/migration_to_python using the following naming convention: path-to-file-file_name.md.  example: `/plans/migration_to_python/skills_todo_scripts_scan-open-todos.sh.md` which was created from `skills/todo/scripts/scan-open-todos.sh`. 

**After plan creation**:
- in this file: mark the file being migrated as IN PROGRESS: `[~]` so that other agents don't attempt to migrate the file.
- review the file being migrated and define its behavior as a spec.
A lot of bash tricks were used to get around bugs or side effects in how bash scripting works.  Python doesn't have those problems, so we should leverage python's improvements.
- follow the migration template below to migrate the file.

**Migration template** (per script, mirroring the `git.sh` pattern):
0. Create a numbered todo list for the plan that was generated.
1. USE STRICT RED-GREEN TDD beginning with adding pytest coverage in `tests/` matching the original behavior. These are RED tests that should fail immediately.  They should be written in plain english at first, expressing the expected behavior of the script as a spec.  example: 
```py
# Scenario: Verify that `<function>` correctly updates the latest commit's "convo-summary" message when a new commit is made. 
# Steps: 
# a branch has a commit from convo-id A.  
# another commit is made after from convo-id B. 
# The test should detect that the convo-id A commit has a 'convo-summary' message.  
# The test should then run the function to remove the convo-summary from that commit.   
# the test should assert the convo-id A commit does not have a convo-summary message.  
# The test should then run the function that feeds the previous convo-summary into the agent so the new convo-summary can be generated.  
# The function should write that new convo-summary onto the convo-id B commit.   
# The test should check that the convo-id B commit has this new convo-summary message.   
```

2. Move logic into a `*_lib.py` module under `common/scripts/` (or the
   skill's local Python dir).
3. Run `pytest` to verify that the RED tests pass.  
4. Revise implementations in the `*_lib.py` file until the tests pass.
5. Do not proceed to the arg parsing dispatcher step next until all tests pass (GREEN). 
6. If the script is sourced by other shells, add a `*_cli.py` argparse
   dispatcher and replace the `.sh` body with one-line Python shims to
   keep the source-able function names intact.
7. If the script is a hook entry point, replace the `.sh` body with a
   single `exec python3 <module> "$@"` line (or rewrite the hook config to invoke Python directly).  
8. Verify end-to-end (callers + integration tests) before checking the
   box below.

---

Checkbox per `.sh` file. Tick when migrated to Python.

Legend: 
`[ ]` to migrate, 
`[x]` migrated, 
`[i]` being investigated prior to writing the plan,  
`[p]` plan written for this file, 
`[~]` in progress,
`[!]` wont migrate (kept as bash on purpose, deleted later when no consumers remain), 
`[-]` discard / dead code.

**Migration class** (annotated on unmigrated entries to indicate ease):
- `(standalone)` — invoked only as a subprocess (`bash X.sh …`). **Easy**: body becomes a one-line `exec python3 …` per template step 7.
- `(entry-point)` — invoked by a hook config or as a top-level skill command, never by other shell scripts. **Easy**: rewrite the hook to call Python directly OR keep a one-line `exec python3 …` shim.
- `(sourced)` — sourced via `. file.sh` so callers use its functions. **Medium**: bash shim with function definitions delegating to a `_cli.py` per template step 6.
- `(mixed)` — both sourced AND invoked. **Hardest**: shim must preserve both modes.
- `(blocked)` — body sources an unmigrated `.sh` and delegates to one of its functions. **Gated**: cannot be migrated until the sourced dependency is migrated (or the needed function is carved out).

## common/scripts/

- [ ] common/scripts/lock.sh
- [!] common/scripts/silencers.sh — bash-only `hide_output`/`hide_errors`; delete once no `.sh` sources it
- [ ] common/scripts/tmux-launcher.sh
- [ ] common/scripts/tmux.sh

## scripts/

- [ ] scripts/orchestrator.sh

## skills/debate/scripts/

- [ ] skills/debate/scripts/debate-build-prompts.sh — `(mixed)` 103 lines
- [ ] skills/debate/scripts/debate-orchestrator.sh — `(entry-point)` 24 lines
- [ ] skills/debate/scripts/debate-tmux-orchestrator.sh — `(mixed)` 586 lines, calls tmux + claude
- [ ] skills/debate/scripts/debate.sh — `(sourced)` 479 lines
- [-] skills/debate/scripts/OLD_DISCARD/debate-build-prompts.sh
- [-] skills/debate/scripts/OLD_DISCARD/debate-orchestrator.sh
- [-] skills/debate/scripts/OLD_DISCARD/debate-session-start.sh
- [-] skills/debate/scripts/OLD_DISCARD/debate-tmux-orchestrator.sh
- [-] skills/debate/scripts/OLD_DISCARD/debate.sh

## skills/debate-abort/scripts/

- [ ] skills/debate-abort/scripts/debate-abort-orchestrator.sh — `(blocked)` 9 lines, sources `skills/debate/scripts/debate.sh` and calls `debate_abort_main`

## skills/debate-retry/scripts/

- [ ] skills/debate-retry/scripts/debate-retry-orchestrator.sh — `(blocked)` 9 lines, sources `skills/debate/scripts/debate.sh` and calls `debate_retry_main`

## skills/debate/tests/

- [ ] skills/debate/tests/agent-ls-permission-test.sh — `(standalone)` 69 lines, test
- [ ] skills/debate/tests/capacity-rotate-test.sh — `(standalone)` 169 lines, test
- [ ] skills/debate/tests/claude-plans-addir-test.sh — `(standalone)` 78 lines, test
- [ ] skills/debate/tests/detect-agents-timing-test.sh — `(standalone)` 146 lines, test
- [ ] skills/debate/tests/e2e-test.sh — `(standalone)` 279 lines, test
- [ ] skills/debate/tests/launch-agent-timeout-test.sh — `(standalone)` 174 lines, test
- [ ] skills/debate/tests/parallel-launch-timing-test.sh — `(standalone)` 149 lines, test
- [ ] skills/debate/tests/resume-integration-test.sh — `(standalone)` 454 lines, test
- [ ] skills/debate/tests/session-survives-daemon-exit-test.sh — `(standalone)` 83 lines, test
- [ ] skills/debate/tests/upfront-instructions-test.sh — `(standalone)` 114 lines, test
- [-] skills/debate/tests/archive/test.sh

## skills/jot/scripts/

- [ ] skills/jot/scripts/jot-orchestrator.sh — `(entry-point)` 12 lines
- [ ] skills/jot/scripts/jot-session-end.sh — `(entry-point)` 24 lines
- [ ] skills/jot/scripts/jot-session-start.sh — `(entry-point)` 56 lines, also sourced internally
- [ ] skills/jot/scripts/jot-state-lib.sh — `(sourced)` 54 lines, state-lib
- [ ] skills/jot/scripts/jot-stop.sh — `(entry-point)` 98 lines, also sourced internally
- [ ] skills/jot/scripts/jot.sh — `(entry-point)` 217 lines

## skills/jot/tests/

- [ ] skills/jot/tests/jot-diag-collect.sh — `(standalone)` 230 lines
- [ ] skills/jot/tests/jot-e2e-live.sh — `(standalone)` 436 lines
- [ ] skills/jot/tests/jot-test-suite.sh — `(standalone)` 412 lines, test

## skills/plate/scripts/

Per `skills/plate/PLATE STATE.md` §"Stage 2 dead-code purge": logic already migrated to `common/scripts/plate/plate_lib.py`; these scripts are unreferenced by `/plate` and slated for deletion (held briefly for revertability after live-validation).

- [-] skills/plate/scripts/branch-snapshot.sh — superseded by plate_lib.py
- [-] skills/plate/scripts/branch-snapshot.v2.sh — superseded by plate_lib.py
- [-] skills/plate/scripts/done.sh — superseded by plate_lib.py
- [-] skills/plate/scripts/drop.sh — superseded by plate_lib.py
- [-] skills/plate/scripts/list-paused-plates.sh — superseded by plate_lib.py
- [-] skills/plate/scripts/next.sh — superseded by plate_lib.py
- [ ] skills/plate/scripts/paths.sh
- [ ] skills/plate/scripts/plate-orchestrator.sh
- [ ] skills/plate/scripts/plate-session-start.sh
- [ ] skills/plate/scripts/plate-summary-stop.sh
- [ ] skills/plate/scripts/plate-worker-end.sh
- [ ] skills/plate/scripts/plate-worker-start.sh
- [ ] skills/plate/scripts/plate-worker-stop.sh
- [ ] skills/plate/scripts/plate.sh
- [-] skills/plate/scripts/push.sh — superseded by plate_lib.py
- [-] skills/plate/scripts/register-parent.sh — superseded by plate_lib.py
- [ ] skills/plate/scripts/render-tree.sh — KEEP per PLATE STATE.md (`--show` design deferred)
- [ ] skills/plate/scripts/show.sh
- [-] skills/plate/scripts/snapshot-stash.sh — superseded by plate_lib.py

## skills/plate/tests/

- [ ] skills/plate/tests/plate-claude-e2e.sh
- [ ] skills/plate/tests/plate-e2e-live.sh
- [ ] skills/plate/tests/test-done-smoke.sh
- [ ] skills/plate/tests/test-drop-smoke.sh
- [ ] skills/plate/tests/test-push-smoke.sh

## skills/todo/scripts/

- [ ] skills/todo/scripts/todo-launcher.sh — `(sourced)` 158 lines, launcher
- [ ] skills/todo/scripts/todo-orchestrator.sh — `(entry-point)` 12 lines
- [ ] skills/todo/scripts/todo-session-end.sh — `(entry-point)` 21 lines
- [ ] skills/todo/scripts/todo-session-start.sh — `(entry-point)` 48 lines
- [ ] skills/todo/scripts/todo-state-lib.sh — `(sourced)` 10 lines, state-lib
- [ ] skills/todo/scripts/todo-stop.sh — `(entry-point)` 72 lines
- [ ] skills/todo/scripts/todo.sh — `(entry-point)` 88 lines

## skills/todo/tests/

- [ ] skills/todo/tests/hook-ignores-other-prompts-test.sh — `(standalone)` 57 lines, test
- [ ] skills/todo/tests/hook-mktemp-pending-test.sh — `(standalone)` 65 lines, test
- [ ] skills/todo/tests/hook-not-git-repo-test.sh — `(standalone)` 41 lines, test
- [ ] skills/todo/tests/hook-writes-pending-test.sh — `(standalone)` 69 lines, test
- [ ] skills/todo/tests/instructions-template-renders-test.sh — `(standalone)` test (class inferred)
- [ ] skills/todo/tests/namespace-roundtrip-test.sh — `(standalone)` 57 lines, test

## skills/todo-clean/tests/

- [ ] skills/todo-clean/tests/frontmatter-parse-test.sh — `(standalone)` 32 lines, test

## skills/todo-list/scripts/

- [ ] skills/todo-list/scripts/todo-list-orchestrator.sh — `(entry-point)` 12 lines
- [ ] skills/todo-list/scripts/todo-list.sh — `(sourced)` 61 lines

## skills/todo-list/tests/

- [ ] skills/todo-list/tests/excludes-nnn-test.sh — `(standalone)` 53 lines, test
- [ ] skills/todo-list/tests/format-open-todos-test.sh — `(standalone)` 72 lines, test
- [ ] skills/todo-list/tests/namespace-roundtrip-test.sh — `(standalone)` 68 lines, test

## tests/

- [ ] tests/orchestrator-dispatch-todo-test.sh
- [ ] tests/tmux-send-test.sh

---

## DONE

Files already migrated. Each kept as a thin bash shim until all of its callers themselves migrate to Python (at which point the bash file can be deleted).

- [x] common/scripts/claude-launcher.sh — bash shim now delegates to `claude_launcher_cli.py` + `claude_launcher_lib.py`; file kept until 4 sourcers migrate
- [x] common/scripts/git.sh — bash shim now delegates to `git_cli.py` + `git_lib.py`; file kept until 7 sourcers migrate
- [x] common/scripts/hook-json.sh — bash shim now delegates to `hook_json_cli.py` + `hook_json_lib.py`; file kept until 9 sourcers migrate
- [x] common/scripts/invoke_command.sh — bash shim now delegates to `invoke_command_cli.py` + `invoke_command_lib.py`; file kept until tmux.sh migrates
- [x] common/scripts/permissions-seed.sh — bash shim now delegates to `permissions_seed_cli.py` + `permissions_seed_lib.py`; file kept until 4 sourcers migrate
- [x] common/scripts/platform.sh — bash shim now delegates to `platform_cli.py` + `platform_lib.py`; file kept until 5 sourcers migrate
- [x] skills/jot/scripts/scan-open-todos.sh — bash entry point now a one-line `exec python3` to `common/scripts/jot/scan_open_todos_cli.py` + `scan_open_todos_lib.py`
- [x] skills/todo/scripts/scan-open-todos.sh — bash entry point now a one-line `exec python3` to `common/scripts/todo/scan_open_todos_cli.py` + `scan_open_todos_lib.py`; different spec from jot's sibling (no status filter); file kept until todo-launcher.sh migrates
