# Plan: Finish the python-migration branch

## Summary for the executing agent

The python-migration branch has migrated bash → Python for the jot plugin and removed `scripts/jot-plugin-orchestrator.sh`, `scripts/jot-plugin-orchestrator-historic.sh`, and `scripts/test_monolith.sh`. Hooks dispatch through `scripts/jot_plugin_orchestrator.py`. The argv dispatch contract (`_ARGV_DISPATCH`) was repaired with adapter lambdas plus regression tests.

The branch is **still not done.** Seven gaps below remain before declaring the migration complete. Each gap section is independently executable. Acceptance criteria at the bottom.

**Hard rules.**
- Do NOT run `pytest`. The end user runs it. Tell the user when each section is ready.
- Do NOT make git commits or run `git rm` / `git mv`. Use plain `rm` for deletions.
- Do NOT touch `.claude/agent-memory-local/**`, `plans/migration_to_python/**`, or `TO_DELETE/**` until step 3 (and only as that step prescribes).
- Preserve docstring/comment provenance anchors that mention `jot-plugin-orchestrator.sh` line numbers — they're navigation aids for future readers, not live calls.

---

## 1. E2E wire-contract coverage for non-`/plate` routes

**Why.** Today only `/plate` has an end-to-end wiring test (`skills/plate/tests/sequence/test_plate_e2e_wiring.py`) that pipes a hook JSON into `python3 scripts/jot_plugin_orchestrator.py` and asserts the JSON-out shape. The Python orchestrator routes 7 prompt prefixes plus 12 argv subcommands; six prompt routes and most argv subcommands have no parity test against the production entry point.

### Routes needing e2e tests

**Prompt routes** (7 total — all dispatched via stdin-mode `dispatch_main`):
- `/jot` (incl. namespaced `/jot:<skill>` rewrites)
- `/plate` (already covered by `test_plate_e2e_wiring.py` and `test_session_end_hook.py`)
- `/debate`
- `/debate-retry`
- `/debate-abort`
- `/todo`
- `/todo-list`

**Argv subcommands** (12 total — dispatched via `dispatch_main([subcmd, ...])`):
- `jot-session-start`, `jot-stop`, `jot-session-end`
- `scan-open-todos`, `todo-launcher`, `todo-stop`, `todo-session-start`, `todo-session-end`
- `plate-summary-stop`, `plate-summary-watch`
- `debate-tmux-orchestrator`
- `jot-diag-collect`

### What each test must do

Model on `skills/plate/tests/sequence/test_plate_e2e_wiring.py`. For each prompt route:

1. Build a representative hook JSON payload (`prompt`, `cwd`, `session_id`, `transcript_path`).
2. Pipe it via `subprocess.run(["python3", str(_ORCHESTRATOR), ...], input=payload, capture_output=True)`.
3. Assert one of:
   - `decision: "block"` JSON shape on stdout when the route blocks.
   - The post-condition produced (file written under `Todos/`, log line appended, etc.) when the route is meant to proceed.
4. Mock all external spawns (tmux, `claude` subprocess) so tests are hermetic. Use `monkeypatch.setenv("JOT_SKIP_LAUNCH", "1")` (or similar already-supported skip switches in the relevant `_lib.py`) to short-circuit terminal/Claude spawns.

For each argv subcommand, write a test that:
1. Builds the smallest valid argv (`["python3", str(_ORCHESTRATOR), subcmd, ...args]`).
2. Asserts the call returns rc=0 (or the documented non-zero) and the side-effect is observable (sidecar written, log line appended). When the subcommand depends on tmux/Claude, mock the spawn via env vars or patched callables.

Place tests under `skills/<skill>/tests/sequence/test_<skill>_e2e_wiring.py` for prompt routes and `tests/test_<skill>_argv_e2e.py` for argv subcommands. Keep them small — one happy-path test per route is enough; corner cases stay in unit tests.

### Done criteria for section 1
- Each of the 7 prompt routes has at least one e2e wiring test invoking `python3 scripts/jot_plugin_orchestrator.py` via subprocess.
- Each of the 12 argv subcommands has at least one e2e test of the same shape.
- All new tests pass when the user runs pytest.

---

## 2. Source-module deduplication: two `plate_lib.py` files

**Why.** The repo has both `common/scripts/plate_lib.py` (~281 lines, dispatcher-facing wrapper exporting `plate_summaryStop`, `plate_summaryWatch`, `plate_main`) and `common/scripts/plate/plate_lib.py` (~1700 lines, the runtime). Resolution depends on `sys.path` ordering — fragile.

### Steps

1. **Identify imports.** `grep -rn "from common.scripts.plate_lib\|import common.scripts.plate_lib\|from common.scripts.plate import\|from common.scripts.plate.plate_lib" --include="*.py" .` Snapshot every importer.
2. **Decide the canonical name.** Recommendation: keep `common/scripts/plate/plate_lib.py` (the runtime) and rename the 281-line file to `common/scripts/plate_dispatcher.py` (or fold its public symbols into `common/scripts/plate/__init__.py`).
3. **Update `scripts/jot_plugin_orchestrator.py`** to import from the new canonical location.
4. **Update every other importer** identified in step 1.
5. **Delete the obsolete file.**
6. **Run pytest** (user runs it). Expect zero regressions.

### Done criteria for section 2
- Exactly one `plate_lib.py` file in the tree (or none, if folded into `__init__.py`).
- All importers point at the canonical module.
- No `sys.path` ordering hack required for plate imports to resolve.

---

## 3. Archive / discard tree cleanup

**Why.** Three trees of legacy bash files survive:
- `skills/plate/scripts/archive/*.sh` (~17 files, pre-Python plate scripts)
- `skills/debate/scripts/OLD_DISCARD/*.sh` (~5 files)
- `TO_DELETE/**` (~50 .sh files plus support dirs — explicitly named for deletion)

### Steps

For each tree, in this order:

1. `grep -rn "<tree_path>" --include="*.py" --include="*.json" --include="*.md" --include="*.sh" .` excluding the tree itself. Confirm zero live references from outside the tree.
2. `find <tree_path> -name '*.sh' -exec grep -l 'jot-plugin-orchestrator\|test_monolith' {} +` to confirm nothing inside the tree is referenced live.
3. `rm -r <tree_path>` (NOT `git rm`).
4. Re-grep to confirm gone.

### Done criteria for section 3
- `skills/plate/scripts/archive/`, `skills/debate/scripts/OLD_DISCARD/`, and `TO_DELETE/` are removed from the working tree.
- No live importer or doc references the deleted paths (docstring/comment historical anchors are OK).

---

## 4. Drop legacy import shims

**Why.** Two re-export shims survive:
- `common/scripts/plate/plate_lib.py:134` — `from common.scripts.git_test_funcs_lib import *`
- `common/scripts/git_lib.py:18` — `from common.scripts.util_lib import run, currentTimestampMs`

Each shim exists for back-compat with importers that still pull these names from the wrong module. Each importer needs to point at the canonical module, then the shim line gets deleted.

### Steps

For each shim:

1. Identify importers. For the git_test_funcs shim: `grep -rn "from common.scripts.plate.plate_lib import.*\(test_helper_name1\|...\)" --include="*.py" .` (replace names with the actual symbols in `git_test_funcs_lib`). For the run/currentTimestampMs shim: `grep -rn "from common.scripts.git_lib import.*\(run\|currentTimestampMs\)" --include="*.py" .`.
2. Update each importer to import from the canonical module (`common.scripts.git_test_funcs_lib` and `common.scripts.util_lib` respectively).
3. Delete the shim line.
4. User runs pytest.

### Done criteria for section 4
- Both shim lines are removed.
- No importer of `git_test_funcs_lib` symbols routes through `plate.plate_lib`.
- No importer of `run` / `currentTimestampMs` routes through `git_lib`.

---

## 5. `_PROMPT_DISPATCH` regression coverage

**Why.** This branch added regression tests for `_ARGV_DISPATCH` (in `tests/test_jot_dispatch.py`). The prompt-routing path needs equivalent coverage so future refactors can't silently break stdin-mode dispatch.

### Steps

In `tests/test_jot_dispatch.py`, add a parametrized test analogous to `test_argv_dispatch_unpacks_args_positionally` that:

1. Stubs each `*_main` function (`jot_main`, `plate_main`, `debate_launch`, `debateRetry_main`, `debateAbort_main`, `todo_main`, `todoList_main`) with a recorder.
2. Rebuilds `_PROMPT_DISPATCH` so the lambdas resolve to the stubs.
3. Pipes a representative `{"prompt": "<prefix>"}` JSON payload through `dispatch_main([])`.
4. Asserts the stub was invoked exactly once.

Cover all 7 prefixes, including the `/jot:<skill>` namespace rewrite case (already partially covered by `test_dispatchMain_jot_namespace_normalises_to_bare_skill`).

### Done criteria for section 5
- Every entry in `_PROMPT_DISPATCH` has a regression test that goes through `dispatch_main`.
- Tests fail if the dispatch contract regresses (e.g., a future refactor passes the JSON differently).

---

## 6. `MIGRATION_TO_PYTHON.md` sweep

**Why.** This file is a planning artefact regenerated by `audit_gen.py`. After all the above sections land, regenerate and confirm no `NEEDS_*` markers remain. If the document is fully clean (zero outstanding migration items), delete it OR move it to `plans/archive/` as historical context.

### Steps

1. `python3 audit_gen.py > MIGRATION_TO_PYTHON.md` (run from worktree root).
2. `grep -n "NEEDS_" MIGRATION_TO_PYTHON.md` — must return zero hits.
3. If clean, decide with the user: delete or move to `plans/archive/python-migration-audit.md`.

### Done criteria for section 6
- No `NEEDS_*` markers in the regenerated audit doc.
- Audit doc deleted or archived per user direction.

---

## 7. Acceptance criteria (the migration is DONE when…)

The branch can ship the python-migration label when **all** of the following hold:

1. **Zero `*.sh` files** in `scripts/`, `common/`, and `skills/` (excluding any archive trees that have themselves been deleted by section 3). Verify: `find scripts common skills -name '*.sh'` returns nothing.
2. **Zero live references** to deleted bash files from `*.py` and `*.json`. Verify: `grep -rn 'jot-plugin-orchestrator\.sh\|test_monolith\.sh' --include="*.py" --include="*.json" .` returns ONLY docstring/comment provenance anchors (currently 4 in `common/scripts/jot_lib.py:605`, `common/scripts/debate_lib.py:1240/1365/1612`, plus `scripts/jot-plugin-orchestrator-historic.py:9` if kept).
3. **All 7 prompt routes have e2e parity tests** against `python3 scripts/jot_plugin_orchestrator.py` (section 1).
4. **All 12 argv subcommands have e2e parity tests** (section 1).
5. **`_PROMPT_DISPATCH` has full regression coverage** in `tests/test_jot_dispatch.py` (section 5).
6. **Exactly one `plate_lib.py`** in the tree (section 2).
7. **Zero legacy shims** (section 4).
8. **Zero `NEEDS_*` markers** in `MIGRATION_TO_PYTHON.md`, or the file is archived (section 6).
9. **pytest passes** with at least the prior baseline + new tests (≥ 877 + new). The user runs pytest.

When all 9 hold, the python-migration branch is ready for merge consideration. Plate-commit replay onto the parent branch is a separate merge-readiness step the user manages — do not bundle it into this scope.

---

## What this plan must NOT do

- Do not touch `.claude/agent-memory-local/**` or `plans/migration_to_python/**` — historical anchors for future debuggers.
- Do not migrate any file that was already correctly Python-native at the start of this work.
- Do not rewrite docstring/comment lines that anchor migration provenance to bash line numbers (`Mirrors X from jot-plugin-orchestrator.sh:NNNN-MMMM`).
- Do not run `git commit`, `git rm`, or `git mv` — the harness blocks them and the user manages git state.
- Do not run `pytest` — surface readiness to the user; the user runs it.
