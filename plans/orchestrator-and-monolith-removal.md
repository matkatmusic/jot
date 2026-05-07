# Cleanup plan: reduce `scripts/jot_plugin_orchestrator.py` to a dispatcher; delete `scripts/test_monolith.py`

**Goal:**
1. `scripts/test_monolith.py` removed.
2. `scripts/jot_plugin_orchestrator.py` **kept** but reduced to a pure entry-point dispatcher: stdlib imports + `<x>_main` imports from `common/scripts/<x>_lib.py` + a routing table + `dispatch_main()` + `if __name__ == "__main__"` block. No business logic. Unmatched prompts return 0 (silent passthrough — matches `scripts/jot-plugin-orchestrator-historic.py:89-90` contract).
3. All `_lib.py` callees own their own logic; no test or lib file imports `jot_plugin_orchestrator` except `dispatch_main` consumers (if any).

**Branch:** `python-migration`
**Last verified green:** 2026-05-06, `pytest -x` = 748 passed.

The plan is 5 phases. Each phase ends with `pytest -x` GREEN before proceeding. No phase removes a file or symbol until its replacement is in place.

**UserPromptSubmit contract reminder:** when the hook script exits 0 with empty stdout, Claude Code proceeds with the user's prompt normally. That is the "not consumed" behavior. No JSON blob is needed for passthrough — only for `block` decisions.

---

## Phase 1 — Delete `scripts/test_monolith.py` and migration scaffolding

**Why first:** zero live consumers. Pure dead-code removal.

**Files to delete:**
- `scripts/test_monolith.py`
- `scripts/merge_todo.py`
- `scripts/_migration_workspace/_merge.py`
- `scripts/_migration_workspace/` (directory) if empty after the above

**Files NOT to touch:**
- `scripts/_migration_workspace/_failing/` if it contains active scratch tests (verify first with `ls`).

**Verification:**
1. `grep -rn "test_monolith\|_merge.py\|merge_todo" scripts/ common/ tests/` returns 0 hits in live code (matches in `plans/` are documentation, fine to leave).
2. `pytest -x` from repo root: 748 passed, 0 failed.

**Rollback:** `git -C <repo> checkout HEAD -- scripts/test_monolith.py scripts/merge_todo.py scripts/_migration_workspace/`

---

## Phase 2 — Sever production dependency in `util_lib.py`

**Why:** `common/scripts/util_lib.py:211,232` does `import jot_plugin_orchestrator as _mono` and calls `_mono.launch_agent(...)` / `_mono.send_prompt(...)`. **Neither name exists anywhere in the codebase** (verified via `grep -rn "def launch_agent\|def send_prompt" common/ scripts/` = 0 hits). Both shims always hit the `except ImportError/AttributeError` branch and return `False`. They are dead code masquerading as a fallback.

**Two options — pick one:**

**Option 2A (recommended): delete the shims.**
- Remove `_terminalLaunchAgent` (util_lib.py:200-219) and `_send_prompt` (util_lib.py:222-237) entirely.
- Find their callers with `grep -rn "_terminalLaunchAgent\|_send_prompt" common/ tests/`. If callers exist, either inline a clean call to the real `debate_lib` function or rewrite callers to use the canonical name directly.

**Option 2B: rewire to `debate_lib`.**
- Replace `import jot_plugin_orchestrator as _mono` with `from common.scripts import debate_lib as _mono`.
- Confirm `debate_lib.launch_agent` and `debate_lib.send_prompt` exist (`grep -n "^def launch_agent\|^def send_prompt" common/scripts/debate_lib.py`). If they don't, this option collapses into 2A.

**Preflight check (do this first):**
```
grep -n "^def launch_agent\|^def send_prompt\|^def debate_launchAgent\|^def debate_sendPromptToAgent" common/scripts/debate_lib.py
```
The bash-style names (`launch_agent`, `send_prompt`) likely never existed in Python — the lib uses `debate_launchAgent` / `debate_sendPromptToAgent`. That confirms Option 2A.

**Verification:**
1. `grep -rn "jot_plugin_orchestrator" common/scripts/` returns 0.
2. `pytest -x`: 748 passed.

**Rollback:** `git -C <repo> checkout HEAD -- common/scripts/util_lib.py`

---

## Phase 3 — Clean up the existing dispatcher; fix the wiring bug

**Why:** the dispatcher code (`_ARGV_DISPATCH`, `_PROMPT_DISPATCH`, `dispatch_main`) ALREADY EXISTS at `scripts/jot_plugin_orchestrator.py:294-362`. The problem is not that it needs to be written — it is that it never runs (two earlier `__main__` blocks short-circuit it) and the file is buried under ~50 lines of dead cruft from the abandoned monolith port. This phase is a focused cleanup, not a rewrite.

**Concrete defects to fix (all confirmed by reading the file):**

1. **Two `__main__` blocks fire before the dispatcher (CRITICAL):**
   - Line 212-220: a local `_main(argv)` that hardcodes `plate_summaryWatch`, plus `if __name__ == "__main__": raise SystemExit(_main(sys.argv[1:]))`. This always wins.
   - Line 273-278: a second `if __name__ == "__main__": sys.exit(jot_main())` that bypasses the dispatcher.
   - **Fix:** delete both. Add a single `if __name__ == "__main__": sys.exit(dispatch_main())` at the bottom of the file (after the `dispatch_main` definition).

2. **`debateRetry_main` and `debateAbort_main` are referenced in `_PROMPT_DISPATCH` (lines 314-315) but never imported.** Module loads (lambdas defer the lookup) but the routes `NameError` when triggered.
   - **Fix:** add to the `from common.scripts.debate_lib import (...)` block at line 111. Confirm both names exist with `grep -n "^def debateRetry_main\|^def debateAbort_main" common/scripts/debate_lib.py`.

3. **Duplicate imports (cosmetic, but should go):**
   - `jot_initState`, `jot_popFirstFromQueue`, `jot_rotateAudit`, `jot_sendPrompt` imported at lines 84-87 AND 100-108.
   - `claude_lib` imported at lines 75-77 AND 92-95.
   - Multiple separate `from common.scripts.jot_lib import (...)` blocks (84, 99, 206, 244, 273) should collapse into one.

4. **Dead module-level constants** (none referenced by `dispatch_main` itself):
   - `_DIAG_SECTION_RULE` (97), `_MAX_SESSIONS` (145), `time_sleep` shim (163), `_LOCK_PANE_RE` (169), `_AGENT_ERROR_MARKERS` (182), `_POLL_ATTEMPTS`/`_POLL_SLEEP` (225-228), `_SIDECAR_RETRIES`/`_SIDECAR_SLEEP` (233-236), `_AUDIT_MAX_LINES` (240), `_LOCK_LINE_RE` (249), `_PROMPT_RE_PLATE` (282-289), repeated `_HERE`/`_SCRIPTS`/`_THIS_DIR`/`_SCRIPTS_DIR` (142, 156, 159, 174, 177, 255, 258).
   - **Triage rule:** if `grep -rn "<NAME>" common/scripts/ tests/` shows usage outside the orchestrator, move the constant to the appropriate `_lib.py` and import it from there only if `dispatch_main` actually needs it. Otherwise delete.

5. **Unused stdlib imports** (lines 9-31): `glob`, `hashlib`, `errno`, `fcntl`, `shutil`, `signal`, `subprocess`, `tempfile`, `threading`, `time`, `deque`, `ThreadPoolExecutor`, `as_completed`, `dataclass`, `datetime`, `timezone`, `StringIO`, `TracebackType`, plus most of `typing` (`Any`, `Optional`, `Sequence`, `Type`, `TypedDict`). Keep only what `dispatch_main` actually uses: `json`, `sys`, `io`, `os` (only if any constant survives), `re` (only if any regex survives), `Path` (only if `_HERE` survives).
   - **Rule:** strip imports last, after constants are gone — that way removing an unused constant automatically frees its import.

6. **The dead `_main` function (lines 212-216)** is unused once its `__main__` block is removed. Delete it.

**Steps (in order):**
1. Delete the two stale `__main__` blocks (212-220, 273-278) and the dead `_main` function (212-216).
2. Add `debateRetry_main`, `debateAbort_main` to the `debate_lib` import block at line 111.
3. Append `if __name__ == "__main__": sys.exit(dispatch_main())` at the bottom.
4. Triage each dead constant in defect #4: move to a lib if used externally, delete otherwise.
5. Collapse duplicate imports (defect #3).
6. Strip unused stdlib imports last (defect #5).

**Preflight checks (run before edits):**
```
grep -n "^if __name__" scripts/jot_plugin_orchestrator.py
grep -n "^def debateRetry_main\|^def debateAbort_main" common/scripts/debate_lib.py
grep -rn "scripts/jot_plugin_orchestrator" .claude/ skills/ plugin.json 2>/dev/null
```
First should return 2 hits before fix, 1 after. Second should return 2 hits (confirms both names exist). Third lists hook registrations — must keep working.

**Verification:**
1. `pytest -x`: 748 passed.
2. `echo '' | python3 scripts/jot_plugin_orchestrator.py` exits 0 with empty stdout.
3. `echo '{"prompt":"/something-not-ours"}' | python3 scripts/jot_plugin_orchestrator.py` exits 0 with empty stdout (passthrough on unmatched).
4. `echo '{"prompt":"/jot test"}' | python3 scripts/jot_plugin_orchestrator.py` triggers `jot_main` (may exit nonzero in dev env if it tries to spawn a real worker; what matters is that the route fires, not the worker outcome).
5. `python3 scripts/jot_plugin_orchestrator.py /debate-retry` no longer raises `NameError`.
6. `wc -l scripts/jot_plugin_orchestrator.py`: target ~80-120 lines (down from 363).

**Rollback:** `git -C <repo> checkout HEAD -- scripts/jot_plugin_orchestrator.py`

---

## Phase 4 — Sweep test files off `jot_plugin_orchestrator` namespace

**Why:** the 6 live test files use the orchestrator as a monkeypatch namespace. Once phase 3 completes, the orchestrator no longer hosts the symbols they patch — patches will silently no-op (memory feedback 4042 / 4130).

**Files and the symbols each patches:**

| Test file | Patched names | Real owner |
|---|---|---|
| `tests/test_tmux_lib.py` | `jot_plugin_orchestrator.time` (22x) | `common.scripts.tmux_lib.time` if `time` is imported there; otherwise the call site's defining module |
| `tests/test_util_lib.py` | `tmux_sendAndSubmit`, `debate_writeFailed`, `time_sleep`, `time.sleep` | `tmux_lib`, `debate_lib`, `util_lib` |
| `tests/test_plate_lib.py` | `dispatch_main` import | `dispatch_lib` (after Phase 3) |
| `tests/test_jot_lib.py` | `FileLock`, `jot_initState`, `tmux_ensureSession`, `tmux_splitWorkerPane`, `tmux_setPaneTitle`, `tmux_retile`, `terminal_spawnIfNeeded`, `jot_buildClaudeCmd`, `dispatch_main` | `jot_lib`, `tmux_lib`, `util_lib`, `dispatch_lib` |
| `tests/test_debate_lib.py` | bare `import jot_plugin_orchestrator` (verify usage with grep) | n/a — likely just remove the import |
| `tests/test_todo_lib.py` | aliased `from common.scripts import todo_lib as jot_plugin_orchestrator` | rename alias to `mod` or drop alias |

**Sweep recipe (run as a subagent):**

For each test file:
1. Replace `monkeypatch.setattr(jot_plugin_orchestrator, "X", v)` with `monkeypatch.setattr("common.scripts.<owner>_lib.X", v)` (string form).
2. Replace `patch("jot_plugin_orchestrator.X")` with `patch("common.scripts.<owner>_lib.X")`.
3. Replace `patch.object(jot_plugin_orchestrator, "X", ...)` with `patch("common.scripts.<owner>_lib.X", ...)`.
4. Replace `jot_plugin_orchestrator.time.sleep` patches with patches against the module that *imports* `time` and calls `time.sleep` (usually the same lib that owns the function under test — see memory 4042: patch the importing module).
5. Replace `from jot_plugin_orchestrator import dispatch_main` with `from common.scripts.dispatch_lib import dispatch_main`.
6. Drop `import jot_plugin_orchestrator` lines that are no longer referenced.

**Caveat — `time.sleep` patches:** `monkeypatch.setattr(jot_plugin_orchestrator.time, "sleep", ...)` patches the **`time` module object itself** (since `jot_plugin_orchestrator.time` IS `time`). It is process-global and works regardless of which module called `time.sleep`. Replace with `monkeypatch.setattr("time.sleep", ...)` for the same effect.

**Verification:**
1. `grep -rn "jot_plugin_orchestrator" tests/` returns only `tests/DO_NOT_test_jot_plugin_orchestrator.py` (intentionally opted out by filename prefix).
2. `pytest -x`: 748 passed.

**Risk:** highest of the 5 phases. Misclassifying which lib owns a symbol = silent monkeypatch no-op = false-green tests. Spot-check by deliberately breaking one production function, running its test, and confirming it fails (sanity check the wiring).

**Rollback:** revert phase commits.

---

## Phase 5 — Verify dispatcher contract; resolve `DO_NOT_test_jot_plugin_orchestrator.py`

**Why last:** with phases 1-4 done, the orchestrator should be a thin dispatcher with zero non-routing code. This phase is the final audit.

**Audit checks (each must pass):**
1. `wc -l scripts/jot_plugin_orchestrator.py` — expected: roughly 50-80 lines. If significantly larger, locate any `def`/`class` that crept back in and move it to a `_lib.py`.
2. `grep -n "^def \|^class " scripts/jot_plugin_orchestrator.py` — should show only `dispatch_main` and possibly `_route`. No business helpers.
3. `grep -rn "jot_plugin_orchestrator" common/ tests/` — should be empty (or only `tests/DO_NOT_test_jot_plugin_orchestrator.py` if kept; see below).
4. `grep -rn "scripts/jot_plugin_orchestrator" .claude/ skills/ plugin.json 2>/dev/null` — should still show the hook registrations, all pointing at the same path.

**Decide on `tests/DO_NOT_test_jot_plugin_orchestrator.py`:**
- This file was named with a `DO_NOT_` prefix specifically so pytest skips it. Its purpose was to import the monolithic orchestrator at module level for inspection. After Phase 3 the orchestrator is trivial; the test is obsolete.
- **Option 5A (recommended): delete it.** Replace it with a small new file `tests/test_dispatcher.py` that tests the dispatcher contract directly:
  - Empty stdin -> exit 0.
  - Unmatched prompt -> exit 0, no stdout.
  - Matched prompt -> the corresponding `<x>_main` is called once with the prompt data.
  - `/jot:foo` is rewritten to `/foo` before routing.
  - argv mode: `dispatch_main(["/jot", "test"])` routes the same as stdin mode.
- **Option 5B:** leave the `DO_NOT_*` file in place as a frozen artifact. Lower value, lower effort.

**Verification:**
1. `pytest -x`: 748 + however many new dispatcher tests added (recommend 5-7 small tests).
2. Manual hook smoke from a real Claude Code session if available: `/jot foo` and `/todo foo` still spawn workers; an unrelated prompt (`/whatever`) is unaffected.

**Rollback:** revert phase commits.

---

## Execution notes

- Commit per phase. Phase commits are independent rollback points.
- Run `pytest -x` between every phase. Do not stack work across phases.
- Phase 4 is the right candidate for a subagent sweep (precise, repetitive, mechanical). Phases 1, 2, 3, 5 are small enough to do directly.
- If `pytest -x` is run against Homebrew's pytest (`/opt/homebrew/bin/pytest`) instead of pyenv's, results may diverge from CI. Standardize on `python -m pytest -x` if drift appears.
- No em-dash in any code or comment touched (project convention).
- Tests added/modified must keep the `# Scenario: / # Setup: / # Test action: / # Test verification:` step structure.

## Open questions to resolve before executing

1. **Phase 3 lib import set:** which `<x>_main` functions exist as the canonical entry points in each `_lib.py`? Confirm via `grep -n "^def .*_main\b" common/scripts/*_lib.py` before writing the dispatcher imports. Any historic `ROUTES` entry without a Python counterpart needs an explicit decision: implement, or drop.
2. **Phase 5: keep or delete `tests/DO_NOT_test_jot_plugin_orchestrator.py`?** Recommended: delete and replace with a small `tests/test_dispatcher.py`.
3. **Hook registration audit:** Confirm `scripts/jot_plugin_orchestrator.py` is the path referenced by every hook in `.claude/settings.json`, `plugin.json`, and any skill manifests. The phase 3 preflight grep covers this; record the answer in the phase 3 commit message.
