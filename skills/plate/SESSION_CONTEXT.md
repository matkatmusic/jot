# Session Context — /plate Test Harness Build

_Snapshot: 2026-04-30 (afternoon). Branch: `fix-plate-bugs`._

## What this session accomplished

This file covers two consecutive sessions that built and then redesigned the
`/plate` skill's Python test harness.

**Morning session (~78 tests)**: built the harness from scratch around the
**branch-model** implementation (each plate is a real git commit on
`<branch>-plate`). All 9 plate operations implemented + tested. Error-path
sequences (sequence_15–20) added: missing-branch guards on
`drop`/`trash`/`recycle`, cherry-pick conflict abort in `plate_done`,
cross-repo patch portability, reflog recoverability.

**Afternoon session (~111 tests, current)**: redesigned `plate_next`,
removed `plate_carry`, and added derived-agent detection inside `plate_push`.
See "Major changes this session" below.

Run with: `rtk pytest skills/plate/tests/sequence/test_helpers.py skills/plate/tests/sequence/helpers.py`

## Major changes this session (afternoon)

### 1. `plate_next` redesigned as a list/jump navigator

Old semantics: walk the parent-chain across `<base>-derived*` branches
and emit a `claude --resume <parent-convo>` string. Removed.

New semantics: **`/plate --next`** prints a numbered list of every plate
branch in the repo, sorted by tip-commit time descending, with a
`(current)` marker on the entry whose ref equals `<currentBranch>-plate`.
**`/plate --next <#>`** captures current WIP (implicit `plate_push`),
clears the WT, checks out the target plate's `parent-branch`, restores
the target plate's tree onto WT as unstaged WIP, and emits a resume
command.

Five distinct return strings — each constant lives at module level:

| Path | Return |
|---|---|
| Local resume | `"resume with: cd <cwd> && claude --resume <title>"` (transcript readable on this machine) |
| Lost | `PLATE_NEXT_LOST_MESSAGE` (transcript not readable here, regardless of summary trailer presence) |
| Self-index | `"already on plate '<title>'; worktree unchanged"` (target == current plate) |
| Invalid index | `PLATE_NEXT_INVALID_INDEX_MESSAGE` (out of range, zero, or negative) |
| Empty list | `PLATE_NEXT_EMPTY_LIST_MESSAGE` (no plate refs in repo) |

The function is a thin delegator: `plate_next(repo, index=None)` →
`_plate_next_list(repo, plates)` (no index) or
`_plate_next_jump(repo, plates, index)` (with index). Both sub-functions
get their plate list from `listPlateBranches(repo)`, so listing order
and jump indexing share one source of truth.

### 2. `plate_carry` removed

`plate_next` subsumes carry's role with better UX (index-based picker,
automatic pre-push, lands HEAD on target's parent branch with plate's
tree as actionable WIP). The function, helper-test, and `test_sequence_11`
were deleted.

### 3. Derived-agent detection in `plate_push`

When two agents work in the same repo (typically: user opens a second
terminal and starts a parallel Claude session), each agent's `/plate`
should not collide on the same `<branch>-plate` ref. `plate_push` now
detects this via the `convo-id` trailer:

| Condition | Target |
|---|---|
| No plate exists | `<branch>-plate`, parent = HEAD |
| `convo_id` matches base plate's owner | `<branch>-plate`, parent = base tip (advance) |
| `convo_id` is `None` | same as above (legacy / no-trailer mode) |
| `convo_id` matches an existing `<branch>-plate-derivedN`'s owner | that derivedN, parent = derivedN tip |
| Different `convo_id`, no matching derivedN | next sibling `<branch>-plate-derived(N+1)`, parent = base tip |

Multiple derived agents land as **siblings** (each parented to the base
plate's tip), not as a chain. The logic is in `_resolveTargetPlate`.

### 4. New transcript helpers

For reading Claude Code JSONL session files:

- `extractConvoNameFromTranscript(path)` — last `customTitle` event;
  fallback to session id if no rename.
- `extractConvoCwdFromTranscript(path)` — first `cwd` field in the file.
- `localTranscriptIsReadable(path)` — gate for local-resume vs lost path.

Plus `formatPlateAge` and `listPlateBranches` for the listing.

### 5. `plate_push` trailer plumbing

`plate_push(repo, convo_id=None, convo_name=None, convo_summary=None)`.
Always writes a `parent-branch:` trailer (auto from `getCurrentBranchName`).
Conditional trailers when kwargs are non-None: `convo-id`, `convo-name`,
`convo-summary`. The `branch=` kwarg was dropped.

Multi-line `convo_summary` input is collapsed to a single space-joined
line (git trailers are single-line by spec). Final structured format for
the ~400-word summary is TBD.

### 6. Solution B: cross-machine handoff via summary trailer

When a plate is created locally, `convo-id` trailer points at the
local-machine `transcript_path` (e.g. `~/.claude/projects/.../<id>.jsonl`).
That path doesn't migrate when a teammate clones the repo.

Solution: `convo-summary` trailer carries a structured ~400-word
summary. On a remote machine, `plate_next` jump-mode hits the lost path
and tells the next agent "summary text is available in plate branch
commits." The next agent reads `git log <plate-branch>` to find the
summary and primes a fresh session with it.

### 7. Doc sync via banners

`DESIGN.md` and `IMPLEMENTATION.md` are heavily based on the pre-refactor
stash-ref + JSON metadata model. Rather than rewriting them, both got a
"⚠️ HISTORICAL — DO NOT TREAT AS CURRENT BEHAVIOR" banner at the top
pointing to `PLATE STATE.md`, `helpers.py`, and `SESSION_CONTEXT.md` as
the operational truth.

## Project state — quick read

- **Implementation**: complete in Python harness for the branch-model design.
- **Tests**: 111 passing, 0 failing.
- **Production wiring**: NOT done. The `/plate` slash command still calls
  shell scripts under `skills/plate/scripts/` that use a different
  (stash-ref) model. The harness and the production scripts are not
  connected.
- **Shippable v1.0**: blocked on (a) decision about branch vs stash-ref
  model and how to wire the chosen path to the slash command,
  (b) defining the `convo-summary` 400-word format spec,
  (c) wiring `generatePlateSummary` (the agent that produces the summary
  at push time), (d) ~3 remaining design decisions in PLATE STATE.md §B.
  Estimated 12–20 hours.

See `PLATE STATE.md` (sibling file) for the full feature gap.

## Process patterns established this session

These are conventions in the test harness — follow them when extending:

1. **TDD with comment-driven specs**: each test starts as numbered English
   comments describing the canonical sequence, *then* gets filled with
   code. Inline comments stay above the code line(s) that implement each
   step. **(Reinforced this session)** — test 4b was rewritten in this
   format after being coded directly the first time. Pattern: write the
   plain-english steps first, verify the logic makes sense before coding.

2. **Visual-diagram-first iteration on test design**: for each new
   integration test, propose an ASCII branch-state diagram and get user
   sign-off BEFORE writing test code. The user reviews the topology as a
   "would this catch the bugs we care about" gut-check.

3. **Helper + helper-test pairing**: when extracting a named utility
   (e.g. `setUserConfigValue`, `formatPlateAge`, `extractConvoCwdFromTranscript`),
   always write a `test_<name>` immediately. Both live in `helpers.py`.

4. **Scenario extraction for cross-fixture coverage**: shared workflow
   assertions live in `_check_*` callables in `helpers.py`. The
   per-function `test_*` (in `helpers.py`, against
   `makeTestRepoWithSingleCommit`) and the `test_sequence_NN` (in
   `test_helpers.py`, against `setup_repo`) both call the same scenario.
   Single source of truth, two fixtures exercised.

5. **Extract = replace**: when the user selects code and asks for a
   helper, write the helper AND replace the selected code with a call
   to it in the same turn. Don't make them ask twice. (Saved as memory.)

6. **No unreachable defensive code**: invariant-protected guards get
   removed. Comment in CLAUDE.md: "Don't add error handling for scenarios
   that can't happen."

7. **Topology-agnostic scenario assertions**: scenarios MUST avoid
   hardcoded branch names (use `getCurrentBranchName(repo)`),
   exact-equality on file lists (use `in` checks), and fixture-specific
   commit counts.

8. **Targeted pytest during development**: run only the specific tests
   under change with `rtk pytest <file>::<function>`. Don't run the full
   suite repeatedly. After all targeted tests pass, run the full suite
   once before declaring done.

9. **Rigor checks (per `feedback_verify_work.md`)**: after each new test
   passes, temporarily disable the production code it covers and confirm
   the test fails. Targeted disabling (commenting out the specific
   return/branch the test asserts) is more precise than upstream gating.

## Bugs surfaced and fixed during the session

These are real bugs the test harness caught — useful as a reference for
what kinds of issues the harness is good at finding:

**Morning session:**
- `plate_push` missing `git add -A` between `git read-tree HEAD` and
  `git write-tree` — captured HEAD's tree, not WT. All pushes silently
  no-op'd.
- Multiple kwarg mismatches (`branchExists(branchName=...)` vs signature
  `branchExists(name=...)`; same for `setGitIndexFileForEnv`,
  `readGitTreeAt`).
- `setup_repo` calling `checkOutBranch` without first creating the
  branch.
- `run()` strips trailing newlines (correct for `git rev-parse`) but
  `git apply` requires patch files to end with `\n` — fixed by appending
  `"\n"` at every patch-write site.
- `plate_trash(clean_wt=True)` was wiping its own just-saved
  `.plate/trashed/` patches via `git clean -fd` — fixed by adding
  `.plate/` to a `.gitignore` written by `setup_repo`.
- `modifyRandomlyChosenTrackedFile` ignored its `rng` parameter and used
  module-level `random.choice` — broke `performRandomEdit`'s seeded
  determinism contract.

**Afternoon session:**
- `_buildTwoBranchPlateTopology` left `investigation.txt` as an
  untracked file after resetting `fix-y` from B1 back to B3 (`git reset
  --hard` doesn't remove untracked files). The leftover file leaked
  across branch switches and got captured by subsequent `plate_push`
  calls in unrelated tests. Fix: `cleanWorkTree(repo)` after the reset
  in the topology helper.

## Key gotchas / non-obvious knowledge

- **Pytest discovery**: only finds `test_*.py` files by default. Tests
  inside `helpers.py` (which has `test_*` functions) are *not* discovered
  when running the directory — must pass the path explicitly. Running
  `rtk pytest skills/plate/tests/sequence/` only collects from
  `test_helpers.py`. To pick up the helpers tests too, run
  `rtk pytest skills/plate/tests/sequence/test_helpers.py skills/plate/tests/sequence/helpers.py`.
- **`pytest` not on PATH** as `pytest` directly with this Python install
  — use `rtk pytest` (the rtk wrapper).
- **Git refuses to checkout a branch that would clobber untracked
  files**, even with `git checkout -q`. To inspect a plate branch's
  contents without disturbing WT, use `git ls-tree -r --name-only
  <branch>` instead of checking it out.
- **Unborn HEAD**: after `git init -b main` with no commits,
  `git symbolic-ref --short HEAD` returns `"main"` but `refs/heads/main`
  does not yet exist. `branchExists(repo, "main")` returns `False` until
  the first commit.
- **Git trailers are single-line by spec**. `convo_summary` input is
  collapsed via `" ".join(text.split())` to satisfy this.
- **`git reset --hard <sha>` preserves untracked files**. If a workflow
  creates files (via `plate_push` writing `investigation.txt` as part of
  WT before snapshot, etc.) that aren't part of any commit, those files
  survive subsequent resets and branch switches. `cleanWorkTree(repo)`
  (`git clean -fd`) is needed to actually start fresh — but it skips
  ignored paths (e.g., `.plate/`), which is what we want.
- **Title resolution precedence in plate_next listing**: live transcript
  `customTitle` (when readable) → `convo-name` trailer → parent-branch
  name → ref name. Implemented in `_resolvePlateTitle`.
- **`PLATE_NEXT_LOST_MESSAGE` is intentionally also returned in the
  remote-handoff case** (transcript not readable but `convo-summary`
  trailer present). The user simplified this from a separate
  `--append-system-prompt` return because the message itself tells the
  next agent "summary text is available in plate branch commits" — the
  agent reads it directly from git.

## Files to know

| Path | Purpose |
|---|---|
| `skills/plate/tests/sequence/helpers.py` | All Python plate ops + sub-functions + helpers + per-function unit tests + `_check_*` scenarios |
| `skills/plate/tests/sequence/test_helpers.py` | Helper smoke tests + `test_sequence_NN` integration tests (gaps where deleted: `_14` plate_next old chain semantics; `_11` plate_carry removal) |
| `skills/plate/tests/sequence/conftest.py` | Pytest `repo` fixture (calls `setup_repo`) |
| `skills/plate/scripts/*.sh` | Production shell scripts (stash-ref model, NOT wired to harness) |
| `skills/plate/SKILL.md` | Slash-command dispatch + production behavior |
| `skills/plate/DESIGN.md` | Pre-refactor design spec (HISTORICAL — see banner) |
| `skills/plate/IMPLEMENTATION.md` | Pre-refactor engineering plan (HISTORICAL — see banner) |
| `skills/plate/PLATE STATE.md` | Feature gap analysis + path to v1.0 (current operational truth) |
| `plans/plate-walkthrough-log-2026-04-28.md` | Canonical git sequences |
| `plans/plate-test-scenarios.md` | Test matrix |
| `plans/plate-assessment-2026-04-28.md` | Branch-model vs stash-ref comparison |
| `~/.claude/plans/review-skills-plate-plate-state-md-and-functional-neumann.md` | Active implementation plan for the `plate_next` redesign |

## Where to pick up

If continuing the plate work:

1. **Highest leverage**: decide branch-model vs stash-ref, then wire the
   production `/plate` slash command to actually invoke the chosen
   implementation. Until this is done, the 111 passing tests don't ship
   to users.
2. **Define the `convo-summary` 400-word format spec**. Goal: a reader
   can pick up the work productively in under a minute. Specific
   sections (intent / what's been tried / what's blocking / next steps?)
   are TBD. The trailer plumbing is in place; only the format is missing.
3. **Wire `generatePlateSummary`** — the agent code (sub-agent prompt,
   hook, or inline LLM call) that produces the summary at plate-push
   time. Out of scope for the harness; in scope for the slash-command
   bridge.
4. **Resolve remaining design decisions** in PLATE STATE.md §B
   (`simulate_derived_agent` production trigger is now resolved; what
   remains: derived-agent's role overall now that detection is in
   plate_push, `.plate/` directory layout, EditFile per-agent file list,
   auto-`/plate` on `SessionExit`).
5. **Optional cleanup**: `simulate_derived_agent` and the related tests
   (sequence_12, sequence_13) still test the old "chained derived
   agents" model that the new `plate_push` derived-detection doesn't
   produce (deriveds are now siblings, not chains). Decide whether to
   delete `simulate_derived_agent` (and its tests) or rewrite them
   against the sibling model.
