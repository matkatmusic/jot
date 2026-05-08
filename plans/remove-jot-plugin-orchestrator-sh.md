# Plan: Remove `scripts/jot-plugin-orchestrator.sh`

## Summary for the executing agent

The python-migration branch has migrated almost everything from bash to Python. `hooks/hooks.json` now invokes `scripts/jot_plugin_orchestrator.py` directly (UserPromptSubmit + SessionEnd). The 146KB legacy `scripts/jot-plugin-orchestrator.sh` is no longer wired into hooks, **but three live Python `_lib.py` files plus two test files still spawn it as a subprocess** for tmux-launched Claude sessions and for argv subcommands. That's the remaining work.

The Python orchestrator (`scripts/jot_plugin_orchestrator.py`) has `_ARGV_DISPATCH` entries naming every subcommand the bash file is invoked with — but **the dispatch contract is broken** (see "Critical pre-work" below). This is NOT a clean subprocess-target swap; the dispatcher must be fixed first.

Goal: every live (non-comment) reference to `jot-plugin-orchestrator.sh` is gone, all 877 baseline tests still pass, and `scripts/jot-plugin-orchestrator.sh` plus `scripts/jot-plugin-orchestrator-historic.sh` are deleted.

## Critical pre-work — fix the dispatch contract

`scripts/jot_plugin_orchestrator.py:98` invokes argv subcommands as `fn(argv[1:])` — passing the remaining argv list as a single positional argument. But every dispatched function takes typed positional args:

| Subcommand | Lib function | Signature | Bash invocation (positional args) |
|---|---|---|---|
| `jot-session-start` | `jot_sessionStart(input_file, tmpdir_inv)` | 2 args | `'{input_file}' '{tmpdir_inv}'` |
| `jot-stop` | `jot_stop(input_file, tmpdir_inv, state_dir, *, background_kill=...)` | 3 args + kwargs | `'{input_file}' '{tmpdir_inv}' '{state_dir}'` |
| `jot-session-end` | `jot_sessionEnd(tmpdir_inv)` | 1 arg | `'{tmpdir_inv}'` |
| `todo-session-start` | `todo_sessionStart(input_file, tmpdir_inv)` | 2 args | same shape |
| `todo-stop` | `todo_stop(...)` | (read full sig before editing) | `'{input_file}' '{tmpdir_inv}' '{state_dir}'` |
| `todo-session-end` | `todo_sessionEnd(tmpdir_inv)` | 1 arg | `'{tmpdir_inv}'` |
| `debate-tmux-orchestrator` | `debate_tmuxOrchestrator(...)` | (read full sig) | 7 args (debate_dir, session, window_name, settings_file, cwd, repo_root, plugin_root) |

So `jot_sessionEnd(["/tmp/foo"])` would crash with `TypeError: tmpdir_inv must be str` (or similar). The current dispatch is dead code — it has never actually been invoked with these subcommands; if it had, those code paths would error.

**Fix this before swapping any call site.** Two viable shapes (executing agent picks one):

**Option A — adapter dict** (recommended): wrap each entry in a lambda that unpacks argv into the lib function's positional contract.

```python
_ARGV_DISPATCH = {
    "jot-session-start":     lambda argv: jot_sessionStart(*argv),
    "jot-stop":              lambda argv: jot_stop(*argv),
    "jot-session-end":       lambda argv: jot_sessionEnd(*argv),
    "todo-session-start":    lambda argv: todo_sessionStart(*argv),
    "todo-stop":             lambda argv: todo_stop(*argv),
    "todo-session-end":      lambda argv: todo_sessionEnd(*argv),
    "debate-tmux-orchestrator": lambda argv: debate_tmuxOrchestrator(*argv),
    # for the rest (todo-launcher, scan-open-todos, plate-summary-stop, plate-summary-watch, jot-diag-collect):
    # check whether anything still spawns them; if so, give them adapters too.
}
```

**Option B — change every lib function to accept `argv: list[str]`** and have it parse internally. This is a much larger refactor and risks breaking direct unit-test callers that pass typed kwargs. AVOID unless you can prove no test calls these functions positionally.

After implementing Option A, write at minimum one regression test per subcommand that invokes `dispatch_main(["<subcmd>", "arg1", "arg2", ...])` and verifies the underlying lib function was called with the expected positional args (use a monkeypatch). This protects against the dispatch contract regressing again.

## Live call sites (the work surface)

### 1. `common/scripts/jot_lib.py`

Two distinct uses, both in the `jot_buildClaudeCmd` flow:

**1a. File copy (line 133–136)**: copies the bash orchestrator into a tmpdir so the launched Claude pane has a self-contained orchestrator file path. Replace with copying `scripts/jot_plugin_orchestrator.py` instead.

```python
# CURRENT
shutil.copy(
    f"{claude_plugin_root}/scripts/jot-plugin-orchestrator.sh",
    f"{tmpdir_inv}/jot-plugin-orchestrator.sh",
)
# TARGET
shutil.copy(
    f"{claude_plugin_root}/scripts/jot_plugin_orchestrator.py",
    f"{tmpdir_inv}/jot_plugin_orchestrator.py",
)
```

**1b. Hook commands (lines 158–170)**: the hooks.json body it generates currently invokes `bash …jot-plugin-orchestrator.sh <subcmd>`. Change every line to `python3 …jot_plugin_orchestrator.py <subcmd>`.

```python
# CURRENT (3 occurrences)
'  "SessionStart": [{"hooks": [{"type": "command", "command": "bash '
f"{tmpdir_inv}/jot-plugin-orchestrator.sh jot-session-start '{input_file}' '{tmpdir_inv}'"
'"}]}],\n'

# TARGET
'  "SessionStart": [{"hooks": [{"type": "command", "command": "python3 '
f"{tmpdir_inv}/jot_plugin_orchestrator.py jot-session-start '{input_file}' '{tmpdir_inv}'"
'"}]}],\n'
```

Apply the same change at the `Stop` and `SessionEnd` lines (lines 163–170).

**1c. Diagnostic check (line 574)**: this just verifies the file exists — change the path to point at the .py file.

```python
# CURRENT
os.path.join(plugin_root, "scripts/jot-plugin-orchestrator.sh"),
# TARGET
os.path.join(plugin_root, "scripts/jot_plugin_orchestrator.py"),
```

### 2. `common/scripts/todo_lib.py` (lines 401–404)

Same pattern as jot_lib.py 1b. Three hook strings inside a JSON literal:

```python
# CURRENT
"SessionStart": [{"hooks": [{"type": "command", "command": f"bash {tmpdir_inv}/jot-plugin-orchestrator.sh todo-session-start '{input_file}' '{tmpdir_inv}'"}]}],
"Stop":         [{"hooks": [{"type": "command", "command": f"bash {tmpdir_inv}/jot-plugin-orchestrator.sh todo-stop '{input_file}' '{tmpdir_inv}' '{state_dir}'"}]}],
"SessionEnd":   [{"hooks": [{"type": "command", "command": f"bash {tmpdir_inv}/jot-plugin-orchestrator.sh todo-session-end '{tmpdir_inv}'"}]}]

# TARGET
"SessionStart": [{"hooks": [{"type": "command", "command": f"python3 {tmpdir_inv}/jot_plugin_orchestrator.py todo-session-start '{input_file}' '{tmpdir_inv}'"}]}],
"Stop":         [{"hooks": [{"type": "command", "command": f"python3 {tmpdir_inv}/jot_plugin_orchestrator.py todo-stop '{input_file}' '{tmpdir_inv}' '{state_dir}'"}]}],
"SessionEnd":   [{"hooks": [{"type": "command", "command": f"python3 {tmpdir_inv}/jot_plugin_orchestrator.py todo-session-end '{tmpdir_inv}'"}]}]
```

Note: todo_lib also needs to copy the .py file into tmpdir_inv if it doesn't already do so (jot_lib does the copy in its own `jot_buildClaudeCmd`). Search todo_lib for its copy site (likely `shutil.copy` near the top of the analogous build function). If todo_lib relies on jot_lib's copy because they share a tmpdir_inv, no extra copy needed — verify by reading todo_lib end-to-end before assuming.

### 3. `common/scripts/debate_lib.py` (lines 1935–1946)

The `debate_launch` flow runs the bash orchestrator with the `debate-tmux-orchestrator` argv subcommand as a daemon (`subprocess.Popen`):

```python
# CURRENT
daemon_cmd = [
    "bash",
    str(Path(plugin_root) / "scripts" / "jot-plugin-orchestrator.sh"),
    "debate-tmux-orchestrator",
    ...
]
# TARGET
daemon_cmd = [
    "python3",
    str(Path(plugin_root) / "scripts" / "jot_plugin_orchestrator.py"),
    "debate-tmux-orchestrator",
    ...
]
```

The daemon's argv contract (`debate-tmux-orchestrator` takes 7 positional args) must be implemented in `_ARGV_DISPATCH`. Confirm `debate_tmuxOrchestrator(argv)` accepts the same positional layout the bash function did. Read `_ARGV_DISPATCH["debate-tmux-orchestrator"]` and the function it points at, and compare against the 7 args in `debate_lib.py:1937–1946`.

### 4a. `skills/plate/tests/sequence/test_session_end_hook.py` (line 19)

Sister e2e test to `test_plate_e2e_wiring.py` (which was already migrated to .py). Update the same way:

```python
# CURRENT
_ORCHESTRATOR = _REPO_ROOT / "scripts" / "jot-plugin-orchestrator.sh"
# TARGET
_ORCHESTRATOR = _REPO_ROOT / "scripts" / "jot_plugin_orchestrator.py"
```

Then change the subprocess invocation in that test from `["bash", str(_ORCHESTRATOR), …]` to `["python3", str(_ORCHESTRATOR), …]` — read the test body to confirm the exact line.

This test exercises SessionEnd → `/plate` injection. Before swapping, run the test against the current .sh to confirm baseline-green, then run against the .py to confirm parity. If parity fails, the dispatcher's `_PROMPT_DISPATCH["/plate"]` flow has a bug that needs fixing before deletion.

### 4b. `tests/test_jot_buildcmd.py` (lines 21, 98)

Test fixtures that write a fake `jot-plugin-orchestrator.sh` for `jot_buildClaudeCmd` to copy. After the source change in 1a, these tests need the fake file renamed:

```python
# CURRENT
(plugin_root / "scripts/jot-plugin-orchestrator.sh").write_text("# fake orchestrator\n")
# TARGET
(plugin_root / "scripts/jot_plugin_orchestrator.py").write_text("# fake orchestrator\n")
```

```python
# CURRENT
copied = plugin_layout["tmp_inv"] / "jot-plugin-orchestrator.sh"
# TARGET
copied = plugin_layout["tmp_inv"] / "jot_plugin_orchestrator.py"
```

Both lines must be updated together with the source changes; if you change only the source, these tests fail.

### 5. Documentation references (no code change required, but update for accuracy)

- `README.md` lines 11, 55, 64 — descriptions of how the hook works. Rewrite to reference the .py orchestrator.
- `plans/migration_to_python/scripts_jot-plugin-orchestrator.sh.md` — old planning doc. Optional: leave as historical record, or move to `plans/archive/`.
- `.claude/agent-memory-local/octo-personas-python-pro/*.md` — agent memory pointing at bash line numbers as historical anchors. **Do not modify** — these are historical context, not live code.
- `common/scripts/*.py` docstring/comment references to bash line numbers (e.g., `debate_lib.py:1240` "Mirrors debate_tmux_orchestrator() from jot-plugin-orchestrator.sh") — leave as historical anchors.

## Order of operations

0. **Capture baseline**: run `pytest 2>&1 | tail -3` from worktree root and record the passing count (must be 877). Any change to that number at the end of this work is a regression.

1. **Fix `_ARGV_DISPATCH` (Critical pre-work above)**. Add adapter lambdas that unpack argv. Verify by importing the orchestrator in a Python REPL and calling `dispatch_main(["jot-session-end", "/tmp/foo"])` — it should attempt to run `jot_sessionEnd("/tmp/foo")` (mock filesystem ops or expect a benign error, not a TypeError).

2. **Read each lib function's full positional signature** before swapping any call site. `todo_stop` and `debate_tmuxOrchestrator` were not fully read in this plan — get their exact arg counts and verify the bash invocations in `todo_lib.py:402-404` and `debate_lib.py:1935-1946` match. If a lib function has more positional args than the bash call provides, the .sh has been doing something with `$@` you may not have spotted; STOP and surface it.

3. **Edit `common/scripts/jot_lib.py`**: 1a (copy), 1b (3 hook lines), 1c (diag path at L574).

4. **Edit `common/scripts/todo_lib.py`**: 3 hook lines (L402–404). Also verify whether todo_lib copies the orchestrator file into tmpdir_inv itself or relies on a sibling (jot_lib does). If todo_lib doesn't do the copy, the hook command at runtime would point at a missing file — it must rely on jot_lib's copy. Trace the call ordering.

5. **Edit `common/scripts/debate_lib.py`**: swap `bash` → `python3` and `.sh` → `.py` in `daemon_cmd` (L1935-1946).

6. **Edit `skills/plate/tests/sequence/test_session_end_hook.py`**: swap `_ORCHESTRATOR` path and the bash subprocess invocation.

7. **Edit `tests/test_jot_buildcmd.py`**: update both fixture references (L21, L98). Read the rest of the test body — any other test in that file may grep the generated hook JSON for the substring `"bash "` or `".sh"`. Update those expectations too.

8. **Grep for residual expectations in tests**: `grep -rn 'bash.*orchestrator\|jot-plugin-orchestrator\.sh' tests/ skills/` — anything that's not a docstring/comment is a missed call site.

9. **Run pytest**. Must show 877 passing (or higher if you added new dispatch regression tests in step 1). If LOWER, a call site was missed or the dispatcher fix has a bug. Diagnose before deleting the bash file.

10. **Delete `scripts/jot-plugin-orchestrator.sh`** via plain `rm` (NOT `git rm` — that is blocked by the harness hook in this environment).

11. **Also delete** `scripts/jot-plugin-orchestrator-historic.sh` (90B stub — no live references). For `scripts/test_monolith.sh` (117KB), run `grep -rn "test_monolith.sh" --include="*.py" --include="*.sh" --include="*.json" --include="*.md"` first — if any LIVE call site exists, leave it and surface to the user. Otherwise delete.

12. **Final pytest** — must still show ≥877 passing.

13. **Final grep** — `grep -rn "jot-plugin-orchestrator\.sh" --include="*.py" --include="*.json"` should return only docstring/comment hits in `common/scripts/jot_lib.py:605`, `common/scripts/debate_lib.py:1240,1365,1612`, and `scripts/jot-plugin-orchestrator-historic.py:9` (if not deleted). All other .py/.json hits must be gone.

## Verification

**Hard requirement: pytest must show ≥877 passing tests at the end (baseline established 2026-05-07).** A drop in pass count means a regression.

- `grep -rn "jot-plugin-orchestrator\.sh" --include="*.py" --include="*.json" .` should return ONLY docstring/comment hits (provenance anchors at `jot_lib.py:605`, `debate_lib.py:1240/1365/1612`). No live import, subprocess, or hook-JSON hits.
- `grep -rn "bash.*jot-plugin-orchestrator\|bash.*orchestrator\.sh" --include="*.py" --include="*.json" .` returns zero hits.
- `pytest` from worktree root passes with 877+ tests.
- Manual smoke: `echo '{"prompt":"/plate --next","cwd":"/tmp/some-empty-repo","session_id":"x","transcript_path":""}' | CLAUDE_PLUGIN_ROOT=$REPO CLAUDE_PLUGIN_DATA=/tmp/d PLATE_LOG_FILE=/tmp/d/log python3 $REPO/scripts/jot_plugin_orchestrator.py` returns `{"decision":"block","reason":"No changes plated"}` JSON. (Pre-create `/tmp/some-empty-repo` with `git init` + an initial empty commit.)
- Manual smoke for an argv subcommand (post-dispatcher-fix): `python3 $REPO/scripts/jot_plugin_orchestrator.py jot-session-end /tmp/nonexistent` should fail with a CLEAR error (FileNotFoundError or similar), NOT a `TypeError: jot_sessionEnd() got an unexpected argument` or `missing 1 required positional argument`. The clean error proves the adapter is unpacking argv correctly.
- `ls scripts/jot-plugin-orchestrator.sh scripts/jot-plugin-orchestrator-historic.sh` should both return "No such file or directory".

## Hard rules

- **Do NOT make git commits.** Leave the working tree dirty.
- **Do NOT use `git rm` or `git mv`** — the harness hook blocks them. Use plain `rm` for deletions.
- **Do NOT touch** `.claude/agent-memory-local/**`, `TO_DELETE/**`, or `plans/migration_to_python/**` (historical artefacts).
- **Preserve all docstring/comment references** to `jot-plugin-orchestrator.sh` line numbers — they are migration provenance anchors that future debuggers rely on.
- If you discover an argv contract mismatch in step 1, STOP and report. Do not invent argv translation.

## Critical files

| Path | Role |
|---|---|
| `scripts/jot_plugin_orchestrator.py` | The replacement target (already implemented; verify `_ARGV_DISPATCH`) |
| `scripts/jot-plugin-orchestrator.sh` | The 146KB legacy file to delete after migration |
| `common/scripts/jot_lib.py` | Live call site (file copy + 3 hooks + diag check) |
| `common/scripts/todo_lib.py` | Live call site (3 hooks; verify copy logic) |
| `common/scripts/debate_lib.py` | Live call site (Popen daemon) |
| `tests/test_jot_buildcmd.py` | Tests that mock the orchestrator file — must rename in lockstep |
| `skills/plate/tests/sequence/test_session_end_hook.py` | E2E test that subprocess-spawns the .sh — must swap target |
| `hooks/hooks.json` | Already migrated to .py — do not touch |

## Post-task: write the "migration-complete" plan

After the .sh removal lands and 877+ tests are green, the python-migration branch is **still not finished** — there are remaining gaps that block declaring the migration done. As the final step of this task, **write a follow-up plan to `plans/python-migration-complete.md`** that another agent can execute. The follow-up plan must address every item below. Do NOT execute these items in this task; only enumerate them in the new plan with enough detail that an executing agent can pick it up cold.

### Items the follow-up plan must cover

**1. E2E wire-contract coverage for non-/plate routes.** Today only `/plate` has an end-to-end test (`test_plate_e2e_wiring.py`) that pipes a hook JSON into `scripts/jot_plugin_orchestrator.py` and asserts the JSON-out shape. The Python orchestrator also routes:
- `/jot`, `/jot:<skill>` namespace rewriting
- `/debate`, `/debate-retry`, `/debate-abort`
- `/todo`, `/todo-list`
plus 12 argv subcommands (`jot-session-start`, `jot-stop`, `jot-session-end`, `scan-open-todos`, `todo-launcher`, `todo-stop`, `todo-session-start`, `todo-session-end`, `plate-summary-stop`, `plate-summary-watch`, `debate-tmux-orchestrator`, `jot-diag-collect`).

The follow-up plan must specify a parity e2e test per route — at minimum one test per top-level prompt and one per argv subcommand — modeled on `test_plate_e2e_wiring.py`. Each test pipes a representative input through `python3 scripts/jot_plugin_orchestrator.py` and asserts the JSON-out (or the post-conditions: file written, tmux pane created and torn down, log line appended). For tmux/Claude-spawning routes, the tests must mock the spawn so they're hermetic.

**2. Legacy `scripts/test_monolith.sh` disposition.** 117KB test harness referenced by some pre-Python-migration unit tests. The follow-up plan must:
- Audit live references (`grep -rn test_monolith\.sh`) and decide: rewrite the depending tests to target Python entrypoints, OR mark the bash harness as TO_DELETE and migrate dependent tests in lockstep.
- Delete `scripts/test_monolith.sh` once nothing references it.

**3. Archive/discard tree cleanup.** Three trees of dead .sh files exist:
- `skills/plate/scripts/archive/*.sh` (~17 files; pre-Python plate scripts)
- `skills/debate/scripts/OLD_DISCARD/*.sh` (~5 files)
- `TO_DELETE/**` (~50 .sh files plus support directories — name explicitly says delete-me)

The follow-up plan must verify zero live references (grep) for each tree, then `rm -r` them.

**4. Source-module deduplication.** Two `plate_lib.py` files exist (281-line `common/scripts/plate_lib.py` orchestrator-facing dispatcher; 1700-line `common/scripts/plate/plate_lib.py` runtime). Flat-import resolution depends on `sys.path` ordering; this is fragile. The follow-up plan must:
- Identify which one is the canonical, runtime-used module.
- Eliminate the other (rename it, fold it into the canonical, or delete if dead).
- Update every importer.

**5. Drop legacy import shims.** `common/scripts/plate/plate_lib.py:134` has `from common.scripts.git_test_funcs_lib import *` as a back-compat re-export. `common/scripts/git_lib.py:18` has `from common.scripts.util_lib import run, currentTimestampMs` as a re-export. The follow-up plan must enumerate every importer that relies on these shims (grep), update them to import from the canonical module directly, then delete the shim lines.

**6. Argv-dispatch coverage tests.** This task introduces adapter lambdas in `_ARGV_DISPATCH` plus regression tests. The follow-up plan must extend that coverage to ensure: (a) every entry in `_ARGV_DISPATCH` has at least one test that goes through `dispatch_main`; (b) the prompt-routing path (`_PROMPT_DISPATCH`) has the same coverage for `/jot`, `/debate*`, `/todo*`. Without this, future refactors can silently break the dispatch contract again.

**7. Migration-complete acceptance criteria.** The follow-up plan must explicitly list the conditions under which the python-migration branch can be considered DONE:
- Zero `*.sh` files in `scripts/`, `common/`, `skills/` (excluding archive trees that have themselves been deleted).
- Zero live references to any deleted .sh from `*.py` source.
- All 7 prompt routes and all 12 argv subcommands have e2e parity tests against the Python orchestrator.
- pytest baseline: ≥ (877 + new tests) passing.
- `MIGRATION_TO_PYTHON.md` regenerated via `python3 audit_gen.py > MIGRATION_TO_PYTHON.md` shows no `NEEDS_*` markers (or the planning artifact is itself deleted).

### What the follow-up plan must NOT do

- Do not require touching `.claude/agent-memory-local/**` or `plans/migration_to_python/**` — historical anchors.
- Do not require migrating files that were already correctly Python-native at the start of this work — only files still containing live bash dependencies or migration leftovers.
- Do not bundle plate-commit replay onto the parent branch into the migration scope — that's a separate merge-readiness step the user manages.
