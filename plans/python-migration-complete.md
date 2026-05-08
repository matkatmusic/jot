# Plan: Finish the python-migration branch

## Summary for the executing agent

The python-migration branch has migrated bash → Python for the jot plugin and removed `scripts/jot-plugin-orchestrator.sh`, `scripts/jot-plugin-orchestrator-historic.sh`, and `scripts/test_monolith.sh`. Hooks dispatch through `scripts/jot_plugin_orchestrator.py`. The argv dispatch contract (`_ARGV_DISPATCH`) was repaired with adapter lambdas plus regression tests.

The branch is **still not done.** Seven gaps below remain before declaring the migration complete. Each gap section is independently executable. Acceptance criteria at the bottom.

**Hard rules.**
- Do NOT run `pytest`. The end user runs it. Surface readiness when each section is ready.
- Do NOT make git commits or run `git rm` / `git mv`. Use plain `rm` for deletions.
- Do NOT touch `.claude/agent-memory-local/**`, `plans/migration_to_python/**`, or `TO_DELETE/**` until section 3 (and only as that section prescribes).
- Preserve docstring/comment provenance anchors that mention `jot-plugin-orchestrator.sh` line numbers — they're navigation aids for future readers, not live calls.

---

## How to apply RED-GREEN-TDD to every section below

This plan is bound by `RED_GREEN_TDD.md`. Before writing any test or source line in a section:

1. **Plain English behavior first.** Write down — in the test docstring or in the section's notes — the *behavior* you intend to prove or change, with no code. Identify every noun (object, value, state) and every verb (action, transition).
2. **Name correctly.** Variables/objects: name what they ARE. Functions: name what they DO. Use `<domain>_<verbPhrase>` for functions (`tmux_spawnSession`, `git_createCommit`). Tests: `test_<behavior_being_tested>`.
3. **RED.** Write the failing test with step-based behavioral comments using exactly these markers:
   - `# Scenario:` — one-line description of the behavior under test
   - `# Setup:` — preconditions
   - `# Test action:` — the single action being exercised
   - `# Test verification:` — the assertion(s) that prove the behavior held
   One behavior per test. Prefer many tiny tests over one fat test.
4. **GREEN.** Write the minimum code in *separate functions* called from the test to make it pass. Do not add behavior the test does not demand.
5. **Refactor** only after green. No speculative scope.

When a section adds tests for *already-implemented* behavior (sections 1 and 5), the RED phase still applies in form: write the test as if the behavior didn't exist yet, watch it fail by stubbing the implementation out (or by deliberately running it before the wiring is in place), and only then claim green. This prevents writing tests that pass for the wrong reason.

---

## 1. E2E wire-contract coverage for non-`/plate` routes

### Behavior to prove (plain English)

When a hook JSON payload containing one of seven prompt prefixes is piped on stdin to `python3 scripts/jot_plugin_orchestrator.py`, the orchestrator routes the payload to the correct `*_main` entry point and that entry point produces its documented side effect (block-decision JSON on stdout, file written under `Todos/`, audit log line appended, etc.). When one of twelve argv subcommands is invoked with positional args, the orchestrator routes argv[1:] through the corresponding adapter lambda into the lib function with the correct positional contract, and that lib function produces its documented side effect.

### Routes needing e2e tests

**Prompt routes** (7 total — dispatched via stdin-mode `dispatch_main`):
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

### TDD steps for each route

For every prompt prefix `<prefix>` and every argv subcommand `<subcmd>`:

1. **RED** — write `test_<route>_e2e_routes_to_<libfn>` (one test per route) inside `skills/<skill>/tests/sequence/test_<skill>_e2e_wiring.py` (prompt) or `tests/test_<skill>_argv_e2e.py` (argv).

   Test body must follow the four-marker structure:

   ```python
   def test_jotPrompt_e2e_routes_to_jot_main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
       # Scenario: a hook JSON with prompt "/jot foo" must reach jot_main and emit
       # the documented block-decision when launch is skipped.
       # Setup: build a minimal valid plugin env, skip the tmux/Claude spawn,
       # capture stdout from a real subprocess invocation of the orchestrator.
       env, payload = e2e_buildJotPromptFixture(tmp_path)
       # Test action: pipe the payload through `python3 scripts/jot_plugin_orchestrator.py`.
       result = e2e_runOrchestratorWithStdin(env=env, stdin=payload)
       # Test verification: stdout contains the expected decision shape.
       decision = e2e_parseHookDecision(result.stdout)
       assert decision["decision"] == "block"
       assert "no idea provided" in decision["reason"]
   ```

   Helper functions (`e2e_buildJotPromptFixture`, `e2e_runOrchestratorWithStdin`, `e2e_parseHookDecision`) are introduced in step 2; at this point they don't exist, so the test fails to import (RED).

2. **GREEN** — implement the e2e helpers in a single shared module `tests/_e2e_lib.py` (or per-skill conftest if it must be local). Each helper does ONE thing per its name:
   - `e2e_buildJotPromptFixture(tmp_path)` — returns `(env_dict, json_payload_str)` for a representative `/jot` invocation. Add one factory per route.
   - `e2e_runOrchestratorWithStdin(env, stdin)` — invokes `subprocess.run(["python3", str(_ORCHESTRATOR), ...], input=stdin, capture_output=True, text=True, env=env)` and returns the CompletedProcess.
   - `e2e_parseHookDecision(stdout)` — `json.loads` the last non-empty line of stdout (mirrors how Claude Code reads the hook reply).
3. **Hermetic guard** — every prompt-route fixture must short-circuit terminal/Claude spawns. Use existing skip switches (`JOT_SKIP_LAUNCH`, etc.) in the relevant `_lib.py`. If a route has no skip switch, add one in the lib and write its own RED-GREEN test for the skip switch behavior before reusing it in the e2e fixture.
4. **One behavior per test.** Do NOT bundle "happy path + missing-arg + namespace rewrite" into one test. Each is its own `test_*` function.
5. **Argv subcommand tests** mirror the same shape but invoke `dispatch_main([subcmd, *args])` from a Python-level test (no subprocess required) using monkeypatched lib functions to capture positional args. The argv adapter regression test in `tests/test_jot_dispatch.py` already demonstrates the pattern; extend it with side-effect assertions where each lib fn produces an observable file/log entry.

### Done criteria for section 1
- Each of the 7 prompt routes has at least one `test_<prefix>_e2e_routes_to_<libfn>` covering the happy path.
- Each of the 12 argv subcommands has at least one `test_<subcmd>_argv_invokes_<libfn>_with_positional_args`.
- Every test uses the four-marker comment structure.
- Every test asserts a single observable behavior (block decision shape, file written, log line appended, etc.).
- All tests pass when the user runs pytest.

---

## 2. Source-module deduplication: two `plate_lib.py` files

### Behavior to prove (plain English)

After consolidation, importing the canonical plate symbols (`plate_main`, `plate_summaryStop`, `plate_summaryWatch`, plus the runtime helpers) returns exactly one implementation regardless of `sys.path` ordering. The orchestrator and every other importer resolve the same module object; no shim re-export remains.

### TDD steps

1. **RED — capture the current importer surface.**
   Write `test_plate_lib_singleSourceOfTruth` in `tests/test_plate_module_layout.py`:

   ```python
   def test_plate_lib_singleSourceOfTruth() -> None:
       # Scenario: only one module on sys.path defines plate_main.
       # Setup: import via every documented path; collect the resolved module file.
       resolved_files = plate_collectAllPlateLibModuleFiles()
       # Test action / verification: every importer resolves to the same file.
       assert len(set(resolved_files)) == 1
   ```

   `plate_collectAllPlateLibModuleFiles` must walk every importer in the codebase (grep first to enumerate them) and return the `.__file__` of each resolved module. Initially this returns two distinct paths; the test fails (RED).

2. **GREEN — pick the canonical module and rename / fold the other.**
   Recommendation: keep `common/scripts/plate/plate_lib.py` (the runtime); rename `common/scripts/plate_lib.py` to `common/scripts/plate_dispatcher.py` (or fold its public symbols into `common/scripts/plate/__init__.py`). Update every importer identified by:
   ```
   grep -rn "from common.scripts.plate_lib\|import common.scripts.plate_lib\|from common.scripts.plate import\|from common.scripts.plate.plate_lib" --include="*.py" .
   ```
3. **Verify** — re-run the test. It should now report exactly one resolved file.
4. **Delete** the obsolete file via plain `rm`.

### Done criteria for section 2
- `test_plate_lib_singleSourceOfTruth` passes.
- Exactly one `plate_lib.py` (or none, if folded into `__init__.py`) exists in the tree.
- All importers point at the canonical module.
- No `sys.path` ordering hack required.

---

## 3. Archive / discard tree cleanup

### Behavior to prove (plain English)

After cleanup, three legacy bash trees no longer exist on disk, and no live Python or JSON file references any path inside them.

### TDD steps

There is no behavior change in production code here, so the "test" is a structural assertion. Add `tests/test_legacy_archive_treesRemoved.py`:

```python
def test_legacyArchiveTrees_areRemoved() -> None:
    # Scenario: three pre-Python bash trees must be deleted.
    # Setup: enumerate the expected-gone roots.
    expected_gone = legacy_archiveTreeRoots()
    # Test action: check each on disk.
    still_present = [p for p in expected_gone if p.exists()]
    # Test verification: zero remaining.
    assert still_present == []


def test_noLiveReferencesToDeletedArchiveTrees() -> None:
    # Scenario: no .py/.json file may reference the deleted trees.
    # Setup: gather sources to grep.
    references = legacy_grepArchiveTreeReferences()
    # Test verification: zero hits outside docstrings/comments.
    assert references == []
```

`legacy_archiveTreeRoots()` returns `[Path("skills/plate/scripts/archive"), Path("skills/debate/scripts/OLD_DISCARD"), Path("TO_DELETE")]`. `legacy_grepArchiveTreeReferences()` shells out to `grep` for each tree path and filters out hits inside the trees themselves and inside `.md` plan/history files.

Both tests fail RED while the trees still exist. Then:

1. For each tree: run `grep -rn "<tree_path>" --include="*.py" --include="*.json"` excluding the tree itself. Confirm zero live hits.
2. `rm -r <tree_path>`.
3. Re-run the tests; both go GREEN.

### Done criteria for section 3
- Both tests pass.
- `skills/plate/scripts/archive/`, `skills/debate/scripts/OLD_DISCARD/`, and `TO_DELETE/` are removed.

---

## 4. Drop legacy import shims

### Behavior to prove (plain English)

Every importer of `git_test_funcs_lib` symbols imports them directly from `common.scripts.git_test_funcs_lib`. Every importer of `run` and `currentTimestampMs` imports them directly from `common.scripts.util_lib`. Neither shim line exists in the source.

### TDD steps

For each shim:

1. **RED** — write `test_<shim>_isRemoved` in `tests/test_legacy_shimsRemoved.py`:

   ```python
   def test_gitTestFuncsLibShim_isRemovedFromPlateLib() -> None:
       # Scenario: the back-compat re-export of git_test_funcs_lib is gone.
       # Setup: read the canonical module file.
       text = Path("common/scripts/plate/plate_lib.py").read_text()
       # Test action / verification: the shim line is absent.
       assert "from common.scripts.git_test_funcs_lib import *" not in text
   ```

   Repeat for the `run, currentTimestampMs` shim in `common/scripts/git_lib.py`.

2. **GREEN** — for each shim:
   a. `grep -rn` to enumerate every importer that depends on the shim.
   b. Update each importer to point at the canonical module directly.
   c. Delete the shim line.
   d. Re-run the test; it goes GREEN.

3. Add one `test_<symbol>_resolvesFromCanonical` per shim that imports the symbol from its canonical home and asserts the import succeeds — protects against the canonical module being broken in a future refactor.

### Done criteria for section 4
- Both `test_<shim>_isRemoved` tests pass.
- Both `test_<symbol>_resolvesFromCanonical` tests pass.
- Both shim lines are deleted from source.

---

## 5. `_PROMPT_DISPATCH` regression coverage

### Behavior to prove (plain English)

When `dispatch_main` receives a stdin JSON payload whose `prompt` field starts with one of seven known prefixes, the orchestrator invokes exactly the right `*_main` function with the original JSON forwarded on stdin. The `/jot:<skill>` namespace rewrite swaps the prefix and forwards the rewritten JSON. No prefix invokes more than one entry point. An unknown prefix invokes none.

### TDD steps

1. **RED** — extend `tests/test_jot_dispatch.py` with one parametrized test per known prefix:

   ```python
   @pytest.mark.parametrize("prefix,target_attr", [
       ("/jot",          "jot_main"),
       ("/plate",        "plate_main"),
       ("/debate",       "debate_launch"),
       ("/debate-retry", "debateRetry_main"),
       ("/debate-abort", "debateAbort_main"),
       ("/todo",         "todo_main"),
       ("/todo-list",    "todoList_main"),
   ])
   def test_promptDispatch_routesPrefixToMatchingMain(monkeypatch, prefix, target_attr):
       # Scenario: a "/<prefix> ..." prompt invokes its matching *_main exactly once.
       # Setup: stub the target_attr on the orchestrator module; rebuild _PROMPT_DISPATCH.
       calls: list = []
       _stub_prompt_disp(monkeypatch, target_attr, calls, prefix)
       payload = json.dumps({"prompt": f"{prefix} fixture"})
       monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
       # Test action: dispatch with no argv (stdin mode).
       rc = dispatch_main([])
       # Test verification: rc=0 and the stub was called exactly once.
       assert rc == 0
       assert len(calls) == 1
   ```

   Add a separate test for the namespace rewrite case (one behavior per test):

   ```python
   def test_promptDispatch_rewritesJotNamespaceToBareSkill(monkeypatch):
       # Scenario: "/jot:todo-list ..." rewrites to "/todo-list ..." and routes accordingly.
       # Setup: stub todoList_main; payload uses the namespaced prefix.
       ...
   ```

   And a tripwire test for unknown prefixes:

   ```python
   def test_promptDispatch_unknownPrefixInvokesNothing(monkeypatch):
       # Scenario: a prompt that does not match any known prefix is a no-op.
       ...
   ```

2. **GREEN** — most of these will pass against the existing implementation. If any fails, that's a real bug surfaced by the test; fix it minimally.

### Done criteria for section 5
- Every entry in `_PROMPT_DISPATCH` has a matching `test_promptDispatch_*` regression test.
- The namespace rewrite case has its own test.
- The unknown-prefix tripwire test exists and passes.

---

## 6. `MIGRATION_TO_PYTHON.md` sweep

### Behavior to prove (plain English)

After all prior sections land, regenerating the audit document via `audit_gen.py` produces a file with no remaining `NEEDS_*` markers; either the file is then deleted or moved to `plans/archive/`.

### TDD steps

1. **RED** — add `tests/test_migrationAudit_isClean.py`:

   ```python
   def test_migrationAuditDocument_hasNoNeedsMarkers() -> None:
       # Scenario: regenerated audit doc must report zero outstanding migration items.
       # Setup: regenerate via audit_gen.py.
       audit_text = audit_regenerateMigrationDocument()
       # Test action / verification: no NEEDS_* token in the doc.
       assert "NEEDS_" not in audit_text
   ```

   `audit_regenerateMigrationDocument()` shells out to `python3 audit_gen.py` and returns stdout. Initially fails RED while real gaps remain.

2. **GREEN** — close every gap surfaced by `audit_gen.py` in earlier sections. Re-run the test until clean.

3. **After green** — confer with the user: delete `MIGRATION_TO_PYTHON.md` or move it to `plans/archive/python-migration-audit.md`.

### Done criteria for section 6
- `test_migrationAuditDocument_hasNoNeedsMarkers` passes.
- The audit doc is deleted or archived.

---

## 7. Acceptance criteria (the migration is DONE when…)

The python-migration branch can ship when **all** of the following hold:

1. **Zero `*.sh` files** in `scripts/`, `common/`, and `skills/`. Verify: `find scripts common skills -name '*.sh'` returns nothing.
2. **Zero live references** to deleted bash files from `*.py` and `*.json`. Verify: `grep -rn 'jot-plugin-orchestrator\.sh\|test_monolith\.sh' --include="*.py" --include="*.json" .` returns ONLY docstring/comment provenance anchors.
3. **All 7 prompt routes have e2e tests** (section 1).
4. **All 12 argv subcommands have e2e tests** (section 1).
5. **`_PROMPT_DISPATCH` has full regression coverage** (section 5).
6. **Exactly one `plate_lib.py`** in the tree (section 2).
7. **Zero legacy shims** (section 4).
8. **Zero `NEEDS_*` markers** in `MIGRATION_TO_PYTHON.md`, or the file is archived (section 6).
9. **Every new test follows the four-marker structure** (`# Scenario:` / `# Setup:` / `# Test action:` / `# Test verification:`) and tests one behavior per function. Verify by spot-grep.
10. **Every new function name conforms to `<domain>_<verbPhrase>`** (`e2e_buildJotPromptFixture`, `legacy_archiveTreeRoots`, `audit_regenerateMigrationDocument`, …). No bare nouns or generic helpers.
11. **pytest passes** with at least the prior baseline + new tests (≥ 877 + new). The user runs pytest.

When all 11 hold, the python-migration branch is ready for merge consideration. Plate-commit replay onto the parent branch is a separate merge-readiness step the user manages — do not bundle it into this scope.

---

## What this plan must NOT do

- Do not skip the RED phase. A test that passes the first time it is run is not a verified test; deliberately break the implementation or the import to confirm the test reports a real failure, then restore.
- Do not bundle multiple behaviors into one test. Split until each `test_*` function exercises exactly one observable behavior.
- Do not introduce generic helpers (`run_test`, `setup_env`). Helpers must be named for what they do (`e2e_runOrchestratorWithStdin`, `legacy_grepArchiveTreeReferences`).
- Do not touch `.claude/agent-memory-local/**` or `plans/migration_to_python/**` — historical anchors for future debuggers.
- Do not migrate any file that was already correctly Python-native at the start of this work.
- Do not rewrite docstring/comment lines that anchor migration provenance to bash line numbers.
- Do not run `git commit`, `git rm`, or `git mv` — the harness blocks them and the user manages git state.
- Do not run `pytest` — surface readiness to the user; the user runs it.
