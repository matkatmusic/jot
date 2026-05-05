# Bash to Python Migration Tracker

Inventory of every shell script in the repo, sorted into what will be
migrated to Python and what will not. Migrate-able items are checkboxes so progress can be tracked file-by-file.

**Before beginning**:
- pick an unmarked file (no `[i]`, `[p]`, `[~]`, `[x]`, or `[-]`) from the list below. Mark it `[i]` so other agents skip it while you investigate.
- generate a plan following the migration template below. The plan's spine is the function table (template step 1). The behavior spec is per-function annotation, not the headline.
- write your plan to `plans/migration_to_python/` using the convention `path-to-file-file_name.md`. Example: `plans/migration_to_python/skills_todo_scripts_scan-open-todos.sh.md` from `skills/todo/scripts/scan-open-todos.sh`.

**After plan creation**:
- mark the file `[p]` (plan written) when the plan file is committed.
- when implementation starts, mark `[~]` (in progress) so other agents do not double-claim.
- bash often used tricks to work around shell limitations. Python does not have those limitations; favor idiomatic Python in the body, not a literal port.
- follow the migration template below.

**Migration philosophy** (read first; applies to every script):

- **1:1 name mapping.** Every bash function becomes a Python function with the same name. Rename only when the bash name is misleading or collides with a Python builtin; log any rename in the function table with a `was: <old>` note.
- **Return, do not echo.** Bash functions that `echo` a value become Python functions that `return` the value. Bash functions that mutate files or env still mutate; their Python equivalent returns `None`. Tests assert on return values or on file/env mutations, never on captured stdout.
- **No shims at end-state.** The only surviving shim in the repo is the hook entry that invokes `jot-plugin-orchestrator.py`. Every other `.sh` is deleted once its last caller imports the Python module directly.
- **Transitional shims allowed only mid-migration.** If an unmigrated `.sh` caller still needs to invoke a migrated module, replace the migrated script's body with a 2-line `.sh` that does `exec python3 -c 'from mod import fn; fn(...)' "$@"`. Mark such files `[s]` (see legend). Delete when the last bash caller migrates.

**Migration template** (per script, scaffold-first):

0. Create a numbered todo list mirroring the steps below.
1. **Inventory.** Read the source `.sh`. List every function. Produce a function table with columns: `name | Python signature (typed) | return type | one-line behavior note`. Add a `was: <old>` note for any rename. The table is the spine of the plan; the behavior spec attaches to each row, not above it.
2. **Scaffold.** Write `_lib.py` (target path declared in the plan) containing every function from the table. Each function: identical name (or rename with `was:` note), typed signature, declared return type, body of `print("TODO: <function_name>")` and nothing else. The module must import cleanly and be callable, but does no real work.
3. **RED tests.** Write pytest tests in `tests/` that import the scaffold and call each stub by name. Tests assert on return values or file/env side effects. With `print("TODO: ...")` bodies, every test fails on assertion (not on import).
4. **Confirm RED.** Run pytest. Every test fails for the expected reason. If a test errors on import or signature mismatch, fix the scaffold first, not the test.
5. **GREEN, one body at a time.** Implement function bodies bottom-up (callees before callers). After each body change, run pytest and confirm one or more tests flip from red to green without breaking others. Commit per body or per small cluster.
6. **Update callers.** Once all tests are GREEN, find every caller of the original `.sh`. Python callers: replace `subprocess.run(['bash', 'X.sh', ...])` with a Python `import` and direct call. Bash callers: install the transitional shim per the philosophy above, OR migrate the bash caller in the same change.
7. **Delete the `.sh`.** When no caller remains, remove the `.sh`. If a transitional shim is still required, keep its body as the 2-line exec form and mark `[s]`.
8. **Verify end-to-end.** Run live integration (hook firing, skill invocation), not just pytest. Mark `[x]` only after live verification.

---

Checkbox per `.sh` file. Tick when migrated to Python.

Legend:
`[ ]` to migrate,
`[x]` migrated (Python module is canonical, callers updated, original `.sh` deleted),
`[i]` being investigated prior to writing the plan,
`[p]` plan written for this file,
`[~]` in progress,
`[s]` transitional shim (Python module is canonical; `.sh` survives as a 2-line `exec python3 ...` shim because at least one bash caller has not yet migrated),
`[a]` absorbed into callers (no Python module created; the script existed only to work around bash limitations that Python lacks; callers use stdlib directly; `.sh` is deleted when its last caller migrates),
`[!]` wont migrate (kept as bash on purpose, deleted later when no consumers remain),
`[-]` discard / dead code.

The previous migration-class taxonomy (`standalone` / `entry-point` / `sourced` / `mixed` / `blocked`) is **deprecated**. Every script's destination is the same: a Python module imported by other Python modules. Each plan instead lists "Callers needing import-site updates" as a subsection.

## FILES NEEDING MIGRATION

The graph below is one-layer per file: each block shows only that file's DIRECT dependencies. Recurse manually by jumping to the dependency's own block.

`(.py helpers)` flags Python scripts invoked as subprocess by the `.sh` — relevant because those `.py` files must remain runnable as the surrounding `.sh` migrates.

---

### scripts/

[x] - scripts/jot-plugin-orchestrator.sh
|
| -- [ ] - common/scripts/silencers.sh
| -- [ ] - skills/jot/scripts/jot-orchestrator.sh                (subprocess)
| -- [ ] - skills/plate/scripts/plate-orchestrator.sh            (subprocess)
| -- [ ] - skills/debate/scripts/debate-orchestrator.sh          (subprocess)
| -- [ ] - skills/debate-retry/scripts/debate-retry-orchestrator.sh   (subprocess)
| -- [ ] - skills/debate-abort/scripts/debate-abort-orchestrator.sh   (subprocess)
| -- [ ] - skills/todo/scripts/todo-orchestrator.sh              (subprocess)
| -- [ ] - skills/todo-list/scripts/todo-list-orchestrator.sh    (subprocess)

[x] - scripts/orchestrator.sh (deleted; was an unreferenced symlink to jot-plugin-orchestrator.sh)

---

### common/scripts/

[p] - common/scripts/claude-launcher.sh

[~] - common/scripts/git.sh

[p] - common/scripts/hook-json.sh
|
| -- (.py helpers) - inline python3 for emit_block JSON encoding

[a] - common/scripts/invoke_command.sh

[a] - common/scripts/lock.sh

[p] - common/scripts/permissions-seed.sh

[p] - common/scripts/platform.sh

[!] - common/scripts/silencers.sh

[p] - common/scripts/tmux-launcher.sh

[p] - common/scripts/tmux.sh

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


