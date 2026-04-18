# Refactor Plan — `scripts/jot.sh` Generalization

**Branch:** `jot-generalizing-refactor`
**Created:** 2026-04-14
**Source file:** `scripts/jot.sh` (594 lines, ~30 KB)

---

## Problem Statement

`scripts/jot.sh` has grown to 594 lines and mixes six concerns:

1. `/jot` input parsing + durable-first file write (jot-specific).
2. The `INSTRUCTIONS` heredoc — a ~55-line prompt for the background worker (jot-specific).
3. Hook JSON helpers (`emit_block`, `check_requirements`) — generic.
4. tmux session/window/pane choreography (session creation, keepalive pane, worker pane split, retile) — generic and reusable.
5. Per-invocation `settings.json` generator + permissions allowlist expansion with a legacy-migration shim (generic with jot-specific inputs).
6. macOS Terminal auto-spawn helper (generic).

Other skills — `/debate` (planned, memory ref S190/1879) and possibly `/plate` — need to spawn background Claude instances in tmux panes using the exact same pattern. Today that pattern is locked inside `jot.sh`. Copy-pasting it is the current anti-pattern we want to avoid (and `/octo:debate` already failed by not reusing this code).

Secondary issue: inline `python3 -c '...'` blocks are hard to test, hard to edit, and hard to reason about. One block (permissions expander, ~40 lines) contains non-trivial logic with a legacy-format migration shim.

## Solution

Split `jot.sh` into a thin orchestrator that composes reusable libraries under `scripts/lib/`. Convert inline python to true `.py` scripts. Extract the `INSTRUCTIONS` heredoc to a template file. After the refactor:

- `jot.sh` drops to roughly 120 lines — argument parsing, enrichment gathering, and calls into `lib/*` functions.
- `/debate` and `/plate` can `source scripts/lib/tmux-launcher.sh` and `source scripts/lib/claude-launcher.sh` to get tmux spawning and per-invocation claude-launch plumbing with no duplication.
- Tests in `tests/jot-test-suite.sh` continue to pass unchanged. `tests/jot-e2e-live.sh` continues to pass unchanged.

## Commits

Each commit is intentionally tiny. Run `bash tests/jot-test-suite.sh all` after every commit. The order is chosen so every intermediate state is green.

1. **Add `scripts/lib/strip_stdin.py`** — a one-line helper that reads stdin and prints it stripped. Replace the two inline `python3 -c 'import sys; print(sys.stdin.read().strip())'` calls at lines 91 and 100 with `python3 "$SCRIPTS_DIR/lib/strip_stdin.py"`. No behavior change. Verify: test suite passes; IDEA and PROMPT still parse correctly.

2. **Add `scripts/lib/expand_permissions.py`** — pulls out the 40-line inline python at line 423 that loads `permissions.local.json`, auto-migrates legacy `Write(Todos/**)`/`Edit(Todos/**)` entries to absolute `//${REPO_ROOT}/Todos/**` form, and emits a JSON array with `${CWD}`, `${HOME}`, `${REPO_ROOT}` expanded. Invoke from `build_claude_cmd` as a subprocess. No behavior change. Verify: permissions-expansion test at `tests/jot-test-suite.sh:245` still passes; legacy-shim warning still fires on stderr when triggered.

3. **Add `scripts/lib/hook-json.sh`** — extract `emit_block` and a parametric `check_requirements`. The new `check_requirements` accepts required command names as arguments (e.g. `check_requirements jq python3 tmux claude`) so other hooks can declare their own dependency sets. Source it from `jot.sh`. No behavior change. Verify: all Phase 1 tests that depend on the block JSON format continue to pass.

4. **Add `scripts/lib/platform.sh`** — extract `spawn_terminal_if_needed`. Accept the tmux session name as an argument (default `jot`) so a `/debate` session can spawn Terminal attached to a `debate` session if we ever need that. Source it from `jot.sh`. Verify: manual live run still opens Terminal on first invocation.

5. **Add `scripts/assets/jot-instructions.md`** — move the `INSTRUCTIONS` heredoc body into a template file. `jot.sh` reads the file, substitutes `${REPO_ROOT}`, `${TIMESTAMP}`, `${BRANCH}`, `${INPUT_ABS}` via a simple python or bash expansion (prefer a small helper `scripts/lib/render_template.py` that refuses to leave unexpanded `${VAR}` tokens so a missing var is loud, not silent). Embedding via heredoc in `jot.sh` is replaced with: read file, expand, prepend to input.txt. **Risk point:** test 13 at `tests/jot-test-suite.sh:160` asserts the heredoc contains absolute `REPO_ROOT` paths — verify this test still passes after the template roundtrip.

6. **Add `scripts/lib/tmux-launcher.sh`** — extract every `tmux` invocation currently inside `phase2_launch_window` into named functions:
   - `tmux_ensure_session(session, window, cwd, keepalive_cmd)` — idempotent session+window+keepalive-pane creation with the SIGINT-trap-hardened keepalive shell.
   - `tmux_ensure_keepalive_pane(target, cwd, keepalive_cmd, title)` — probes for the keepalive pane by title (not index), re-creates if missing. Handles the "worker panes outlive keepalive and shift indices" edge case documented in the current code.
   - `tmux_split_worker_pane(target, cwd, cmd) → pane_id` — splits and returns the pane id on stdout, returns nonzero if empty.
   - `tmux_set_pane_title(pane_id, title)`.
   - `tmux_retile(target)` — wraps `select-layout tiled`.

   Rewrite `phase2_launch_window` in `jot.sh` to compose these functions. The global `tmux-launch.lock` acquisition stays in `jot.sh` (it is jot-state aware via `jot_lock_acquire`). No behavior change. Verify: `tests/jot-e2e-live.sh` passes; pane counter still increments 1→20→1; keepalive pane survives worker pane death.

7. **Add `scripts/lib/claude-launcher.sh`** — generalize `build_claude_cmd`. New signature:

   ```
   build_claude_cmd \
     --cwd <dir> \
     --add-dir <dir> [--add-dir <dir>...] \
     --settings-out <path> \
     --hooks-json <path-to-hooks-fragment> \
     --allow-json <path-to-allow-array> \
     [--tmpdir <dir>]
   ```

   Outputs: writes `settings.json` to the requested path; prints the resolved `claude ...` command on stdout.

   The function no longer hard-codes the jot SessionStart/Stop/SessionEnd hooks. Instead, `jot.sh` builds the hooks-json fragment from its three scripts (or, better, writes a small JSON file containing the hooks block and passes its path in). `/debate` will do the same with its own hooks.

   Lifecycle-safe worker launch (copying hook scripts into `TMPDIR_INV` so `claude plugin update` cannot delete them mid-run) is preserved: `claude-launcher.sh` takes a list of script paths to copy into `TMPDIR_INV` as a side effect, then rewrites the hooks-json fragment to point at the copies. Document this as the canonical pattern in the file header.

   Verify: unit tests pass; live e2e still works; settings.json still contains a valid `permissions.allow` array and hooks block.

8. **Add `scripts/lib/permissions-seed.sh`** — extract `jot_seed_permissions` (the three-state sha256 check: fresh install / match-prior-default / user-edited). It is only needed on first run and on plugin upgrade, so it stays separate from `expand_permissions.py`. `jot.sh` calls it once from the top of `phase2_launch_window`. No behavior change.

9. **Thin out `jot.sh`** — final pass. Delete now-unused local helpers. Move the `safe()` wrapper used for enrichment helper scripts (`git-branch.sh`, `git-commits.sh`, etc.) into `scripts/lib/safe-exec.sh` if any other script needs it (probably not — leave inline if single-use). Update the file header comment block to reflect the new module layout. Final size target: ~120 lines.

## Decision Document

- **Module boundaries** — seven new files under `scripts/lib/` (and one asset under `scripts/assets/`), each named for its single concern. Neutral, non-jot-prefixed names so `/debate` and `/plate` can source them without nominal coupling.
- **Python-vs-bash split** — any block longer than one logical statement becomes a real `.py` file. Reasons: easier to test with `pytest`, easier to read, no shell-quoting escape-hatch hell, and real stack traces when something fails.
- **`check_requirements` contract change** — becomes parametric (accepts command names as args). Callers declare their own required toolchain.
- **`build_claude_cmd` contract change** — no longer assumes jot's hook set or jot's permissions location. Caller supplies both. This is the primary reuse unlock.
- **`tmux-launcher.sh` is pure functions** — no hidden globals, no reliance on caller-set env vars. All inputs via arguments; all outputs via stdout or explicit file writes. Makes the module trivially testable and safely sourceable from unrelated scripts.
- **Locking ownership** — the global `tmux-launch.lock` (acquired from `CLAUDE_PLUGIN_DATA`) stays in `jot.sh`. `/debate` and `/plate` will acquire their own equivalent before calling `tmux_*` functions. The tmux lib itself does no locking. Keeps the lib stateless.
- **Hooks-json injection strategy** — caller writes a small JSON fragment (one file per invocation) with the hooks block; `claude-launcher.sh` splices it into the final `settings.json` via `jq`. Prevents heredoc-in-heredoc escaping pain.
- **Template expansion** — `render_template.py` refuses to leave `${VAR}` unexpanded. Loud failure is better than a prompt with literal `${REPO_ROOT}` reaching the background worker.
- **Keepalive pane semantics preserved** — SIGINT-trap shell wrapper, `tail -f /dev/null`, probe-by-title-not-index re-creation. These are battle-tested behaviors with a specific failure mode (session death cascade) documented in comments; do not simplify.
- **`jot-state-lib.sh`** — untouched. Already a proper lib with tight scope (lock + state dir). Leaving alone.
- **Plan file location** — `plans/jot-generalizing-refactor.md` (matches the `mattpocock_prd-to-plan` convention already used in this repo's adjacent tooling).

## Testing Decisions

- **What makes a good test for this work** — exercises external behavior: `settings.json` on disk has the expected shape; the INSTRUCTIONS prompt contains the expected absolute paths; a real tmux session spawns and the worker pane's claude receives a valid Read-and-follow-instructions prompt. We do **not** want tests that pin internal function names or argument orders — those are exactly what this refactor is rearranging.
- **Existing coverage** — `tests/jot-test-suite.sh` runs 400+ lines of assertions across Phase 1 (with `JOT_SKIP_LAUNCH=1`, stubs out tmux) and `phase2_tests` (Stop hook audit log). The critical assertions the refactor must not break:
  - Test 13 (line 160): the INSTRUCTIONS heredoc embeds absolute `REPO_ROOT` paths. Sensitive to commit 5.
  - Line 245 block: permissions expander handles `${CWD}`, `${HOME}`, `${REPO_ROOT}` and the legacy `Write(Todos/**)` migration. Sensitive to commit 2.
  - `phase2_tests` (Stop hook): audit log trim to last N lines when growing unbounded. Not directly touched by this refactor, but worth re-running.
- **Live coverage** — `tests/jot-e2e-live.sh` runs the real spawn path. Sensitive to commits 6 and 7. Run once after commit 7 lands; run again at the end.
- **No new test files** — the refactor is behavior-preserving. Adding parallel unit tests for the extracted functions is a nice-to-have but explicitly out of scope (keeps the change surface minimal and the commits tiny).
- **Prior art** — `tests/jot-test-suite.sh` is the model for any future unit tests on the new libs. `tests/jot-e2e-live.sh` is the model for live-tmux tests.

## Out of Scope

- Porting `jot-session-start.sh`, `jot-stop.sh`, or `jot-session-end.sh` to use the new libs. They are already small and focused; re-wiring them can be a follow-up once `/debate` lands.
- Any behavior change to `/jot`: the refactor is strictly mechanical.
- New tests for the extracted libs (can follow).
- Packaging concerns (marketplace manifest, plugin.json) — file additions under `scripts/lib/` do not change the plugin surface.
- `jot-state-lib.sh` — already appropriately scoped.
- `/debate` and `/plate` adoption of the new libs — separate work that unblocks _after_ this refactor lands.
- Python type hints or `pytest` scaffolding for the new `.py` files — can follow if the team wants it.

## Further Notes

- **Pre-commit hygiene** — check each commit keeps `shellcheck scripts/jot.sh scripts/lib/*.sh` clean; the current file is shellcheck-clean and the refactor should not introduce new warnings.
- **Log surface stability** — the log lines written to `$LOG_FILE` (timestamps, `jot:` prefix) are load-bearing for debugging. Preserve exact formats when moving code between files.
- **Branch workflow** — all commits land on `jot-generalizing-refactor`. Merge to `main` only after commit 9 lands and both test suites pass. No intermediate PR is required unless someone else needs to review.
- **Follow-up work unblocked by this refactor**:
  - `/debate` slash command (memory S190, 1867, 1879, 1884) — consumes `lib/tmux-launcher.sh`, `lib/claude-launcher.sh`, `lib/hook-json.sh`.
  - `/plate` branch-snapshot scripts (memory S188, 1864, 1866) — may optionally adopt `lib/hook-json.sh` if plate ever becomes a real hook (currently not).
