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

## FILES NEEDING MIGRATION

The graph below is one-layer per file: each block shows only that file's DIRECT dependencies. Recurse manually by jumping to the dependency's own block.

`(.py helpers)` flags Python scripts invoked as subprocess by the `.sh` — relevant because those `.py` files must remain runnable as the surrounding `.sh` migrates.

---

### scripts/

[ ] - scripts/jot-plugin-orchestrator.sh
|
| -- [ ] - common/scripts/silencers.sh
| -- [ ] - skills/jot/scripts/jot-orchestrator.sh                (subprocess)
| -- [ ] - skills/plate/scripts/plate-orchestrator.sh            (subprocess)
| -- [ ] - skills/debate/scripts/debate-orchestrator.sh          (subprocess)
| -- [ ] - skills/debate-retry/scripts/debate-retry-orchestrator.sh   (subprocess)
| -- [ ] - skills/debate-abort/scripts/debate-abort-orchestrator.sh   (subprocess)
| -- [ ] - skills/todo/scripts/todo-orchestrator.sh              (subprocess)
| -- [ ] - skills/todo-list/scripts/todo-list-orchestrator.sh    (subprocess)

[-] - scripts/orchestrator.sh
|
| -- byte-identical duplicate of jot-plugin-orchestrator.sh; not referenced by hooks/hooks.json — discard candidate

---

### common/scripts/

[ ] - common/scripts/claude-launcher.sh

[ ] - common/scripts/git.sh

[ ] - common/scripts/hook-json.sh
|
| -- (.py helpers) - inline python3 for emit_block JSON encoding

[ ] - common/scripts/invoke_command.sh

[ ] - common/scripts/lock.sh

[ ] - common/scripts/permissions-seed.sh

[ ] - common/scripts/platform.sh

[!] - common/scripts/silencers.sh

[ ] - common/scripts/tmux-launcher.sh

[ ] - common/scripts/tmux.sh

---

### skills/jot/scripts/

[ ] - skills/jot/scripts/jot-orchestrator.sh
|
| -- [ ] - skills/jot/scripts/jot.sh

[ ] - skills/jot/scripts/jot.sh
|
| -- [!] - common/scripts/silencers.sh
| -- [ ] - common/scripts/hook-json.sh
| -- [ ] - common/scripts/platform.sh
| -- [ ] - common/scripts/tmux-launcher.sh
| -- [ ] - common/scripts/claude-launcher.sh
| -- [ ] - common/scripts/permissions-seed.sh
| -- [ ] - common/scripts/git.sh
| -- [ ] - skills/jot/scripts/jot-state-lib.sh
| -- [ ] - skills/jot/scripts/scan-open-todos.sh                 (subprocess)
| -- (.py helpers) - common/scripts/jot/strip_stdin.py
| -- (.py helpers) - common/scripts/jot/expand_permissions.py
| -- (.py helpers) - common/scripts/jot/render_template.py
| -- (.py helpers) - skills/jot/scripts/capture-conversation.py

[ ] - skills/jot/scripts/jot-state-lib.sh
|
| -- [ ] - common/scripts/invoke_command.sh
| -- [ ] - common/scripts/tmux.sh
| -- [ ] - common/scripts/lock.sh

[ ] - skills/jot/scripts/jot-session-start.sh
|
| -- [ ] - common/scripts/tmux.sh                   (sourced via $(dirname "$0")/, copied into $TMPDIR_INV at launch)
| -- [ ] - common/scripts/tmux-launcher.sh          (same)

[ ] - skills/jot/scripts/jot-stop.sh
|
| -- [ ] - skills/jot/scripts/jot-state-lib.sh
| -- [!] - common/scripts/silencers.sh

[ ] - skills/jot/scripts/jot-session-end.sh

[ ] - skills/jot/scripts/scan-open-todos.sh

---

### skills/jot/tests/

[ ] - skills/jot/tests/jot-diag-collect.sh
|
| -- [ ] - common/scripts/tmux-launcher.sh

[ ] - skills/jot/tests/jot-e2e-live.sh
|
| -- [ ] - common/scripts/tmux-launcher.sh

[ ] - skills/jot/tests/jot-test-suite.sh
|
| -- [ ] - common/scripts/tmux-launcher.sh
| -- [ ] - skills/jot/scripts/jot-state-lib.sh
| -- [ ] - skills/jot/scripts/jot-session-end.sh    (subprocess)
| -- [ ] - skills/jot/scripts/jot-stop.sh           (subprocess)

---

### skills/plate/scripts/

[ ] - skills/plate/scripts/plate-orchestrator.sh
|
| -- [ ] - skills/plate/scripts/plate.sh

[ ] - skills/plate/scripts/plate.sh
|
| -- [!] - common/scripts/silencers.sh
| -- [ ] - common/scripts/hook-json.sh
| -- [ ] - common/scripts/git.sh
| -- (.py helpers) - common/scripts/plate/cli.py    (delegates all real work)

[ ] - skills/plate/scripts/plate-summary-stop.sh
|
| -- (.py helpers) - common/scripts/plate/cli.py    (or similar; verify on migration)

[ ] - skills/plate/scripts/plate-summary-watch.sh

---

### skills/plate/tests/

[ ] - skills/plate/tests/plate-claude-e2e.sh
|
| -- [!] - common/scripts/silencers.sh
| -- [ ] - common/scripts/git.sh
| -- [ ] - common/scripts/tmux.sh
| -- [ ] - common/scripts/tmux-launcher.sh

[ ] - skills/plate/tests/plate-e2e-live.sh
|
| -- [!] - common/scripts/silencers.sh
| -- [ ] - common/scripts/git.sh
| -- [ ] - common/scripts/tmux.sh
| -- [ ] - common/scripts/tmux-launcher.sh

[ ] - skills/plate/tests/test-done-smoke.sh
|
| -- needs verification — Explore agent reported `skills/plate/scripts/paths.sh` but `paths.sh` no longer exists in `skills/plate/scripts/` (only 4 .sh files there now); test may be stale or reference a TMPDIR copy

[ ] - skills/plate/tests/test-drop-smoke.sh
|
| -- needs verification — same as test-done-smoke.sh

[ ] - skills/plate/tests/test-push-smoke.sh
|
| -- needs verification — same as test-done-smoke.sh

---

### skills/debate/scripts/

[ ] - skills/debate/scripts/debate-orchestrator.sh
|
| -- [!] - common/scripts/silencers.sh
| -- [ ] - skills/debate/scripts/debate.sh

[ ] - skills/debate/scripts/debate.sh
|
| -- [!] - common/scripts/silencers.sh
| -- [ ] - common/scripts/hook-json.sh
| -- [ ] - common/scripts/platform.sh
| -- [ ] - common/scripts/tmux-launcher.sh
| -- [ ] - common/scripts/claude-launcher.sh
| -- [ ] - common/scripts/permissions-seed.sh
| -- [ ] - skills/debate/scripts/debate-build-prompts.sh         (subprocess)
| -- [ ] - skills/debate/scripts/debate-tmux-orchestrator.sh     (subprocess)
| -- (.py helpers) - confirmed via grep; specific paths TBD on migration

[ ] - skills/debate/scripts/debate-tmux-orchestrator.sh
|
| -- [!] - common/scripts/silencers.sh
| -- [ ] - common/scripts/invoke_command.sh
| -- [ ] - common/scripts/tmux.sh
| -- [ ] - common/scripts/tmux-launcher.sh
| -- [ ] - skills/debate/scripts/debate-build-prompts.sh         (subprocess)

[ ] - skills/debate/scripts/debate-build-prompts.sh
|
| -- (.py helpers) - confirmed via grep; specific paths TBD on migration

---

### skills/debate/tests/

[ ] - skills/debate/tests/agent-ls-permission-test.sh
|
| -- [ ] - skills/debate/scripts/debate-tmux-orchestrator.sh

[ ] - skills/debate/tests/capacity-rotate-test.sh
|
| -- [ ] - skills/debate/scripts/debate-tmux-orchestrator.sh

[ ] - skills/debate/tests/claude-plans-addir-test.sh
|
| -- [ ] - skills/debate/scripts/debate-tmux-orchestrator.sh

[ ] - skills/debate/tests/detect-agents-timing-test.sh
|
| -- [!] - common/scripts/silencers.sh
| -- [ ] - skills/debate/scripts/debate.sh

[ ] - skills/debate/tests/e2e-test.sh
|
| -- [!] - common/scripts/silencers.sh
| -- [ ] - common/scripts/platform.sh
| -- [ ] - skills/debate/scripts/debate-build-prompts.sh         (subprocess)
| -- [ ] - skills/debate/scripts/debate-tmux-orchestrator.sh     (subprocess)

[ ] - skills/debate/tests/launch-agent-timeout-test.sh
|
| -- [ ] - skills/debate/scripts/debate-tmux-orchestrator.sh

[ ] - skills/debate/tests/parallel-launch-timing-test.sh
|
| -- [ ] - skills/debate/scripts/debate-tmux-orchestrator.sh

[ ] - skills/debate/tests/resume-integration-test.sh
|
| -- [!] - common/scripts/silencers.sh
| -- [ ] - skills/debate/scripts/debate-tmux-orchestrator.sh
| -- [ ] - skills/debate/scripts/debate.sh
| -- [ ] - skills/debate/scripts/debate-build-prompts.sh         (subprocess)

[ ] - skills/debate/tests/session-survives-daemon-exit-test.sh
|
| -- [ ] - skills/debate/scripts/debate-tmux-orchestrator.sh

[ ] - skills/debate/tests/upfront-instructions-test.sh
|
| -- [!] - common/scripts/silencers.sh
| -- [ ] - common/scripts/hook-json.sh
| -- [ ] - skills/debate/scripts/debate.sh

---

### skills/debate-abort/scripts/

[ ] - skills/debate-abort/scripts/debate-abort-orchestrator.sh
|
| -- [ ] - skills/debate/scripts/debate.sh

---

### skills/debate-retry/scripts/

[ ] - skills/debate-retry/scripts/debate-retry-orchestrator.sh
|
| -- [ ] - skills/debate/scripts/debate.sh

---

### skills/todo/scripts/

[ ] - skills/todo/scripts/todo-orchestrator.sh
|
| -- [ ] - skills/todo/scripts/todo.sh

[ ] - skills/todo/scripts/todo.sh
|
| -- [!] - common/scripts/silencers.sh
| -- [ ] - common/scripts/hook-json.sh
| -- [ ] - common/scripts/git.sh
| -- (.py helpers) - common/scripts/jot/strip_stdin.py
| -- (.py helpers) - inline python3 -c for JSON encoding

[ ] - skills/todo/scripts/todo-launcher.sh
|
| -- [!] - common/scripts/silencers.sh
| -- [ ] - common/scripts/hook-json.sh
| -- [ ] - common/scripts/platform.sh
| -- [ ] - common/scripts/tmux.sh
| -- [ ] - common/scripts/tmux-launcher.sh
| -- [ ] - common/scripts/claude-launcher.sh
| -- [ ] - common/scripts/permissions-seed.sh
| -- [ ] - common/scripts/git.sh
| -- [ ] - common/scripts/lock.sh
| -- [ ] - skills/todo/scripts/todo-state-lib.sh
| -- (.py helpers) - confirmed via grep; specific paths TBD on migration

[ ] - skills/todo/scripts/todo-state-lib.sh

[ ] - skills/todo/scripts/todo-stop.sh
|
| -- [ ] - common/scripts/tmux.sh                   (sourced via $SCRIPT_DIR/, copied into $TMPDIR_INV at launch)
| -- [ ] - common/scripts/invoke_command.sh         (same)
| -- [!] - common/scripts/silencers.sh              (same)

[ ] - skills/todo/scripts/todo-session-start.sh

[ ] - skills/todo/scripts/todo-session-end.sh

[ ] - skills/todo/scripts/scan-open-todos.sh

---

### skills/todo/tests/

[ ] - skills/todo/tests/hook-ignores-other-prompts-test.sh

[ ] - skills/todo/tests/hook-mktemp-pending-test.sh

[ ] - skills/todo/tests/hook-not-git-repo-test.sh

[ ] - skills/todo/tests/hook-writes-pending-test.sh

[ ] - skills/todo/tests/instructions-template-renders-test.sh

[ ] - skills/todo/tests/namespace-roundtrip-test.sh

---

### skills/todo-clean/tests/

[ ] - skills/todo-clean/tests/frontmatter-parse-test.sh

---

### skills/todo-list/scripts/

[ ] - skills/todo-list/scripts/todo-list-orchestrator.sh
|
| -- [ ] - skills/todo-list/scripts/todo-list.sh

[ ] - skills/todo-list/scripts/todo-list.sh
|
| -- [!] - common/scripts/silencers.sh
| -- [ ] - common/scripts/hook-json.sh
| -- [ ] - common/scripts/git.sh
| -- (.py helpers) - confirmed via grep; specific paths TBD on migration

---

### skills/todo-list/tests/

[ ] - skills/todo-list/tests/excludes-nnn-test.sh

[ ] - skills/todo-list/tests/format-open-todos-test.sh

[ ] - skills/todo-list/tests/namespace-roundtrip-test.sh

---

### tests/

[ ] - tests/orchestrator-dispatch-todo-test.sh

[ ] - tests/tmux-send-test.sh
|
| -- [ ] - common/scripts/tmux.sh
| -- [ ] - common/scripts/tmux-launcher.sh

## DONE


