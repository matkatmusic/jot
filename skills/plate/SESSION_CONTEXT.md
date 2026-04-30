# Session Context — /plate Test Harness Build

_Snapshot: 2026-04-30. Branch: `fix-plate-bugs`._

## What this session accomplished

Built a Python test harness for the `/plate` skill from scratch to ~78 passing tests. The harness validates the **branch-model** implementation (each plate is a real git commit on `<branch>-plate`; derived agents on `<branch>-plate-derivedN`) end-to-end.

Core deliverables:
- `skills/plate/tests/sequence/helpers.py` — all 9 plate operations implemented in Python (`plate_push`, `plate_done`, `plate_drop`, `plate_trash`, `plate_recycle`, `plate_carry`, `plate_next`, `simulate_derived_agent`, `apply_patch`) plus ~40 helper utilities (git-plumbing wrappers, repo factories, assertion helpers, scenario callables)
- `skills/plate/tests/sequence/test_helpers.py` — 14 sequence integration tests (`test_sequence_01`–`14`) covering canonical workflows from the walkthrough log, plus 15 helper smoke tests
- `skills/plate/PLATE STATE.md` — gap analysis between current state and shippable v1.0

Run with: `rtk pytest skills/plate/tests/sequence/`

## Project state — quick read

- **Implementation**: complete in Python harness for the branch-model design
- **Tests**: 78 passing, 0 failing
- **Production wiring**: NOT done. The `/plate` slash command still calls shell scripts under `skills/plate/scripts/` that use a different (stash-ref) model. The harness and the production scripts are not connected.
- **Shippable v1.0**: blocked on (a) decision about branch vs stash-ref model, (b) wiring chosen path to the slash command, (c) ~5 open design decisions in `plans/plate-walkthrough-log-2026-04-28.md`. Estimated 20–30 hours.

See `PLATE STATE.md` (sibling file) for the full feature gap.

## Process patterns established this session

These are conventions in the test harness — follow them when extending:

1. **TDD with comment-driven specs**: each test starts as numbered English comments describing the canonical sequence, *then* gets filled with code, *then* the production code is written. Inline comments stay above the code line(s) that implement each step.

2. **Helper + helper-test pairing**: when extracting a named utility (e.g. `setUserConfigValue`, `createBranch`, `cleanWorkTree`), always write a `test_<name>` immediately. Both live in `helpers.py`.

3. **Scenario extraction for cross-fixture coverage**: shared workflow assertions live in `_check_*` callables in `helpers.py`. The per-function `test_*` (in `helpers.py`, against `makeTestRepoWithSingleCommit`) and the `test_sequence_NN` (in `test_helpers.py`, against `setup_repo`) both call the same scenario. Single source of truth, two fixtures exercised.

4. **Extract = replace**: when the user selects code and asks for a helper, write the helper AND replace the selected code with a call to it in the same turn. Don't make them ask twice. (Saved as memory.)

5. **No unreachable defensive code**: invariant-protected guards get removed (e.g. `if plateCount == 0` in `plate_done` was removed; `.get("convo-id", "UNKNOWN")` fallback was tightened to `["convo-id"]`). Comment in CLAUDE.md: "Don't add error handling for scenarios that can't happen."

6. **Topology-agnostic scenario assertions**: scenarios MUST avoid hardcoded branch names (use `getCurrentBranchName(repo)`), exact-equality on file lists (use `in` checks), and fixture-specific commit counts.

## Bugs surfaced and fixed during the session

These are real production bugs the test harness caught — useful as a reference for what kinds of issues the harness is good at finding:

- `plate_push` missing `git add -A` between `git read-tree HEAD` and `git write-tree` — captured HEAD's tree, not WT. All pushes silently no-op'd.
- Multiple kwarg mismatches: `branchExists(branchName=...)` vs signature `branchExists(name=...)`; same pattern for `setGitIndexFileForEnv`, `readGitTreeAt`. Surfaced as `TypeError`.
- `setup_repo` calling `checkOutBranch` without first creating the branch (after `checkOutBranch` lost its `-b` flag).
- `run()` strips trailing newlines (correct for `git rev-parse`) but `git apply` requires patch files to end with `\n` — fixed by appending `"\n"` at every patch-write site.
- `plate_trash(clean_wt=True)` was wiping its own just-saved `.plate/trashed/` patches via `git clean -fd` — fixed by adding `.plate/` to a `.gitignore` written by `setup_repo`.
- `modifyRandomlyChosenTrackedFile` ignored its `rng` parameter and used module-level `random.choice` — broke `performRandomEdit`'s seeded determinism contract once the tracked-file count grew past 1.

## Key gotchas / non-obvious knowledge

- **Pytest discovery**: only finds `test_*.py` files by default. Tests inside `helpers.py` (which has `test_*` functions) are *not* discovered when running the directory — must pass the path explicitly. Running `rtk pytest skills/plate/tests/sequence/` only collects from `test_helpers.py`.
- **`pytest` not on PATH** as `pytest` directly with this Python install — use `rtk pytest` (the rtk wrapper).
- **`monkeypatch.setattr(random.Random, "choice", ...)`** affects fresh `Random()` instances but NOT the module-level `random.choice` (a pre-bound method captured at import time). To make the patch fire, code must use `Random(seed).choice(...)`, not `random.choice(...)`.
- **Git refuses to checkout a branch that would clobber untracked files**, even with `git checkout -q`. To inspect a plate branch's contents without disturbing WT, use `git ls-tree -r --name-only <branch>` instead of checking it out.
- **Unborn HEAD**: after `git init -b main` with no commits, `git symbolic-ref --short HEAD` returns `"main"` but `refs/heads/main` does not yet exist. `branchExists(repo, "main")` returns `False` until the first commit.
- **`plate_next` semantic ambiguity**: walkthrough spec says "claude --resume B" (deepest convo); implementation returns parent-convo (A). `test_sequence_14` asserts the implementation; one or the other needs to change before shipping.

## Files to know

| Path | Purpose |
|---|---|
| `skills/plate/tests/sequence/helpers.py` | All Python plate ops + helpers + per-function unit tests + `_check_*` scenarios |
| `skills/plate/tests/sequence/test_helpers.py` | 15 helper smoke tests + 14 `test_sequence_NN` integration tests |
| `skills/plate/tests/sequence/conftest.py` | Pytest `repo` fixture (calls `setup_repo`) |
| `skills/plate/scripts/*.sh` | Production shell scripts (stash-ref model, NOT wired to harness) |
| `skills/plate/SKILL.md` | Slash-command dispatch + production behavior |
| `skills/plate/DESIGN.md` | Full design spec (some sections still aspirational) |
| `skills/plate/PLATE STATE.md` | Feature gap analysis + path to v1.0 |
| `plans/plate-walkthrough-log-2026-04-28.md` | Canonical git sequences + open design decisions |
| `plans/plate-test-scenarios.md` | Test matrix (untested scenarios still listed for follow-up) |
| `plans/plate-assessment-2026-04-28.md` | Branch-model vs stash-ref comparison |

## Where to pick up

If continuing the plate work:

1. **Easiest win**: implement the documented-but-untested error-path scenarios from `plans/plate-test-scenarios.md` (cherry-pick conflicts, missing-plate paths, cross-repo patch portability). Adds ~5–10 more tests; pure transcription.
2. **Highest leverage**: decide branch-model vs stash-ref, then wire the production `/plate` slash command to actually invoke the chosen implementation. Until this is done, the 78 passing tests don't ship to users.
3. **Resolve `plate_next` discrepancy**: pick whether the resume command should target the deepest convo (B) or the parent-convo (A); update either the impl or the spec to match.
4. **JSON metadata layer**: DESIGN.md §6 calls for `.plate/instances/<convoID>.json` with `stack[]`/`completed[]` — not yet in the harness. Will be needed for the `--list` and `--resume` user flows.
