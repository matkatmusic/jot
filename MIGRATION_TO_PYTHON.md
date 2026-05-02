# Bash to Python Migration Tracker

Inventory of every shell script in the repo, sorted into what will be
migrated to Python and what will not. Migrate-able items are checkboxes
so progress can be tracked file-by-file.

**Before beginning**:
- in this file: mark the file being migrated as IN PROGRESS: `[~]` so that other agents don't attempt to migrate the file.
- review the file being migrated and define its behavior as a spec.
A lot of bash tricks were used to get around bugs or side effects in how bash scripting works.  Python doesn't have those problems, so we should leverage python's improvements.

**Migration template** (per script, mirroring the `git.sh` pattern):
0. Create a numbered todo list for the plan that was generated.
1. Add pytest coverage in `tests/` matching the original behavior. These are RED tests that should fail immediately. 
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

Legend: `[ ]` to migrate, `[x]` migrated, `[~]` in progress, `[!]` wont migrate (kept as bash on purpose, deleted later when no consumers remain), `[-]` discard / dead code.

## common/scripts/

- [x] common/scripts/claude-launcher.sh — bash shim now delegates to `claude_launcher_cli.py` + `claude_launcher_lib.py`; file kept until 4 sourcers migrate
- [x] common/scripts/git.sh — bash shim now delegates to `git_cli.py` + `git_lib.py`; file kept until 7 sourcers migrate
- [x] common/scripts/hook-json.sh — bash shim now delegates to `hook_json_cli.py` + `hook_json_lib.py`; file kept until 9 sourcers migrate
- [x] common/scripts/invoke_command.sh — bash shim now delegates to `invoke_command_cli.py` + `invoke_command_lib.py`; file kept until tmux.sh migrates
- [ ] common/scripts/lock.sh
- [x] common/scripts/permissions-seed.sh — bash shim now delegates to `permissions_seed_cli.py` + `permissions_seed_lib.py`; file kept until 4 sourcers migrate
- [x] common/scripts/platform.sh — bash shim now delegates to `platform_cli.py` + `platform_lib.py`; file kept until 5 sourcers migrate
- [!] common/scripts/silencers.sh — bash-only `hide_output`/`hide_errors`; delete once no `.sh` sources it
- [ ] common/scripts/tmux-launcher.sh
- [ ] common/scripts/tmux.sh

## scripts/

- [ ] scripts/orchestrator.sh

## skills/debate/scripts/

- [ ] skills/debate/scripts/debate-build-prompts.sh
- [ ] skills/debate/scripts/debate-orchestrator.sh
- [ ] skills/debate/scripts/debate-tmux-orchestrator.sh
- [ ] skills/debate/scripts/debate.sh
- [-] skills/debate/scripts/OLD_DISCARD/debate-build-prompts.sh
- [-] skills/debate/scripts/OLD_DISCARD/debate-orchestrator.sh
- [-] skills/debate/scripts/OLD_DISCARD/debate-session-start.sh
- [-] skills/debate/scripts/OLD_DISCARD/debate-tmux-orchestrator.sh
- [-] skills/debate/scripts/OLD_DISCARD/debate.sh

## skills/debate-abort/scripts/

- [ ] skills/debate-abort/scripts/debate-abort-orchestrator.sh

## skills/debate-retry/scripts/

- [ ] skills/debate-retry/scripts/debate-retry-orchestrator.sh

## skills/debate/tests/

- [ ] skills/debate/tests/agent-ls-permission-test.sh
- [ ] skills/debate/tests/capacity-rotate-test.sh
- [ ] skills/debate/tests/claude-plans-addir-test.sh
- [ ] skills/debate/tests/detect-agents-timing-test.sh
- [ ] skills/debate/tests/e2e-test.sh
- [ ] skills/debate/tests/launch-agent-timeout-test.sh
- [ ] skills/debate/tests/parallel-launch-timing-test.sh
- [ ] skills/debate/tests/resume-integration-test.sh
- [ ] skills/debate/tests/session-survives-daemon-exit-test.sh
- [ ] skills/debate/tests/upfront-instructions-test.sh
- [-] skills/debate/tests/archive/test.sh

## skills/jot/scripts/

- [ ] skills/jot/scripts/jot-orchestrator.sh
- [ ] skills/jot/scripts/jot-session-end.sh
- [ ] skills/jot/scripts/jot-session-start.sh
- [ ] skills/jot/scripts/jot-state-lib.sh
- [ ] skills/jot/scripts/jot-stop.sh
- [ ] skills/jot/scripts/jot.sh
- [x] skills/jot/scripts/scan-open-todos.sh — bash entry point now a one-line `exec python3` to `common/scripts/jot/scan_open_todos_cli.py` + `scan_open_todos_lib.py`

## skills/jot/tests/

- [ ] skills/jot/tests/jot-diag-collect.sh
- [ ] skills/jot/tests/jot-e2e-live.sh
- [ ] skills/jot/tests/jot-test-suite.sh

## skills/plate/scripts/

- [ ] skills/plate/scripts/branch-snapshot.sh
- [ ] skills/plate/scripts/branch-snapshot.v2.sh
- [ ] skills/plate/scripts/done.sh
- [ ] skills/plate/scripts/drop.sh
- [ ] skills/plate/scripts/list-paused-plates.sh
- [ ] skills/plate/scripts/next.sh
- [ ] skills/plate/scripts/paths.sh
- [ ] skills/plate/scripts/plate-orchestrator.sh
- [ ] skills/plate/scripts/plate-session-start.sh
- [ ] skills/plate/scripts/plate-summary-stop.sh
- [ ] skills/plate/scripts/plate-worker-end.sh
- [ ] skills/plate/scripts/plate-worker-start.sh
- [ ] skills/plate/scripts/plate-worker-stop.sh
- [ ] skills/plate/scripts/plate.sh
- [ ] skills/plate/scripts/push.sh
- [ ] skills/plate/scripts/register-parent.sh
- [ ] skills/plate/scripts/render-tree.sh
- [ ] skills/plate/scripts/show.sh
- [ ] skills/plate/scripts/snapshot-stash.sh

## skills/plate/tests/

- [ ] skills/plate/tests/plate-claude-e2e.sh
- [ ] skills/plate/tests/plate-e2e-live.sh
- [ ] skills/plate/tests/test-done-smoke.sh
- [ ] skills/plate/tests/test-drop-smoke.sh
- [ ] skills/plate/tests/test-push-smoke.sh

## skills/todo/scripts/

- [ ] skills/todo/scripts/scan-open-todos.sh
- [ ] skills/todo/scripts/todo-launcher.sh
- [ ] skills/todo/scripts/todo-orchestrator.sh
- [ ] skills/todo/scripts/todo-session-end.sh
- [ ] skills/todo/scripts/todo-session-start.sh
- [ ] skills/todo/scripts/todo-state-lib.sh
- [ ] skills/todo/scripts/todo-stop.sh
- [ ] skills/todo/scripts/todo.sh

## skills/todo/tests/

- [ ] skills/todo/tests/hook-ignores-other-prompts-test.sh
- [ ] skills/todo/tests/hook-mktemp-pending-test.sh
- [ ] skills/todo/tests/hook-not-git-repo-test.sh
- [ ] skills/todo/tests/hook-writes-pending-test.sh
- [ ] skills/todo/tests/instructions-template-renders-test.sh
- [ ] skills/todo/tests/namespace-roundtrip-test.sh

## skills/todo-clean/tests/

- [ ] skills/todo-clean/tests/frontmatter-parse-test.sh

## skills/todo-list/scripts/

- [ ] skills/todo-list/scripts/todo-list-orchestrator.sh
- [ ] skills/todo-list/scripts/todo-list.sh

## skills/todo-list/tests/

- [ ] skills/todo-list/tests/excludes-nnn-test.sh
- [ ] skills/todo-list/tests/format-open-todos-test.sh
- [ ] skills/todo-list/tests/namespace-roundtrip-test.sh

## tests/

- [ ] tests/orchestrator-dispatch-todo-test.sh
- [ ] tests/tmux-send-test.sh
