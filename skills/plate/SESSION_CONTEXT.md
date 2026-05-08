# Session Context — /plate Test Harness + Production Wiring

_Snapshot: 2026-05-01 (late evening). Branch: `fix-plate-bugs`._

## What this file covers

A multi-session arc that built the `/plate` Python test harness, redesigned
its core operations, and shipped the production wiring. Live state today:

- **138 passing tests, 0 failures.**
- **`/plate` is functional end-to-end** as a slash command.
- **Auto-`/plate` fires on SessionEnd** — uncommitted WIP at conversation
  close lands on `<branch>-plate` automatically.
- **Roadmap to v1.0**: `generatePlateSummary` agent + `convo-summary`
  format spec + Stage 2 dead-code purge. Estimated ~5–8 h remaining.

Run with: `rtk pytest skills/plate/tests/sequence/test_helpers.py skills/plate/tests/sequence/test_plate_cli.py skills/plate/tests/sequence/test_plate_e2e_wiring.py skills/plate/tests/sequence/test_session_end_hook.py skills/plate/tests/sequence/helpers.py`

## Major changes by session

### 2026-04-30 morning — initial harness (~78 tests)
Built the harness from scratch around the **branch-model** implementation
(each plate is a real git commit on `<branch>-plate`). All 9 plate ops
implemented + tested. Error-path sequences (sequence_15–20): missing-branch
guards on `drop`/`trash`/`recycle`, cherry-pick conflict abort in
`plate_done`, cross-repo patch portability, reflog recoverability.

### 2026-04-30 afternoon — `plate_next` redesign + `plate_carry` removal
- `plate_next` became a list/jump navigator across independent plates.
  Five distinct return strings (local-resume, lost, self-index, invalid,
  empty), each a module-level constant. Thin delegator: `plate_next(repo,
  index=None)` → `_plate_next_list` (no index) or `_plate_next_jump`.
- `plate_carry` deleted (`plate_next` subsumed its role with better UX).
- `plate_push` gained `convo_id`, `convo_name`, `convo_summary` kwargs;
  always writes a `parent-branch:` trailer.
- New transcript helpers: `extractConvoNameFromTranscript`,
  `extractConvoCwdFromTranscript`, `localTranscriptIsReadable`.
- Solution B: `convo-summary` trailer carries the cross-machine handoff
  payload. Lost-path return tells next agent "summary text is available
  in plate branch commits."

### 2026-04-30 evening — multi-agent shared-plate-branch attribution
Replaced sibling-derived auto-detection (where each agent got its own
`<branch>-plate-derivedN` ref) with the **shared-branch + transcript
extraction model**. Multiple agents working on the same git branch all
push to the same `<branch>-plate` ref; per-agent attribution lives in
commit trailers; per-agent change isolation comes from parsing each
agent's transcript.

- New helpers: `findMyLastPlate`, `extractFilesEditedSinceTimestamp`,
  `extractFilesDeletedSinceTimestamp`, `_buildFullWtTree`,
  `_buildExtractedTree`.
- `plate_push` picks between full-WT-snapshot (same-author / first-time)
  and extracted-tree (mixed-author) based on the previous plate's
  `convo-id` trailer.
- Mixed-author path stages only files the current agent edited (per
  `Edit`/`Write`/`MultiEdit`/`NotebookEdit` `tool_use` entries) and
  removes only files it deleted (per `Bash` `rm`/`git rm` parsing,
  filtered to inside-repo paths tracked at the parent commit).
- Mental model: "selectively staging changes, varied author" —
  `git add <subset> && git commit --author=X`.
- Integration test verifies a 4-step Pa1 → Pb1 → Pa2 → Pb2 sequence
  including a deletion: each commit captures only its author's
  attributable changes.

### 2026-05-01 evening — production wiring landed
`/plate` slash command now executes the branch-model code via a single
Python entry point. Old shell scripts and Python helpers tied to the
stash-ref + JSON-instance model still exist on disk but are no longer
reachable from `/plate` (Stage 2 purge tracked in PLATE STATE.md).

- `common/scripts/plate/plate_cli.py` (NEW, 175 LoC) — single argv dispatcher
  for 8 variants: `push`, `done`, `drop`, `trash`, `recycle`, `next`,
  `next <#>`, `show` (currently returns `"TODO"`; design deferred).
  Uses `sys.path` injection to import `helpers.py` as `plate_lib`.
- `skills/plate/scripts/plate.sh` rewritten to mirror `jot.sh::jot_main`
  shape: substring fast-path filter, strict prompt regex, hook JSON
  parse, `cli.py` exec, single `emit_block` per terminal exit.
- `skills/plate/SKILL.md` collapsed to /jot-style stub.
- `plate_next(repo, index)` signature: `Optional[int]` → `Optional[str]`.
  CLI passes argv straight through; `_plate_next_jump` validates
  numeric-only via `str.isdigit()` before range check. New constant
  `PLATE_NEXT_NON_NUMERIC_MESSAGE`. `"-1"` migrated to non-numeric
  bucket.
- 24 new tests: 16 in `test_plate_cli.py` (mock-based variant routing +
  trailer kwarg propagation), 8 in `test_plate_e2e_wiring.py` (hook JSON →
  `decision:"block"` JSON contract).

### 2026-05-01 late evening — auto-`/plate` on SessionEnd
- `hooks/hooks.json` `SessionEnd` entry pipes payload through
  `jq '. + {prompt: "/plate"}'` into `scripts/jot-plugin-orchestrator.sh`. Routes
  through the standard `/plate` pipeline. No new scripts.
- Removed dead `SessionStart` entry that pointed at
  `plate-session-start.sh` (all four operations the script performed —
  `verify_stash_refs.py`, `instance_rw.py touch`, `clear_drift_alert.py`,
  `render-tree.sh` — were tied to the obsolete model).
- 2 new tests in `test_session_end_hook.py`.

## Process patterns established (still valid)

1. **TDD with comment-driven specs**: each test starts as numbered English
   comments describing the canonical sequence, *then* gets filled with
   code.
2. **Visual-diagram-first iteration on test design**: for each new
   integration test, propose an ASCII branch-state diagram and get user
   sign-off BEFORE writing test code.
3. **Helper + helper-test pairing**: when extracting a named utility,
   always write a `test_<name>` immediately. Both live in `helpers.py`.
4. **Scenario extraction for cross-fixture coverage**: shared workflow
   assertions live in `_check_*` callables in `helpers.py`. The
   per-function `test_*` and the `test_sequence_NN` both call the same
   scenario.
5. **Extract = replace**: when the user selects code and asks for a
   helper, write the helper AND replace the selected code with a call
   to it in the same turn.
6. **No unreachable defensive code**: invariant-protected guards get
   removed.
7. **Topology-agnostic scenario assertions**: avoid hardcoded branch
   names, exact-equality on file lists, and fixture-specific commit
   counts.
8. **Targeted pytest during development**: `rtk pytest <file>::<function>`.
   Run the full suite once before declaring done.
9. **Rigor checks (per `feedback_verify_work.md`)**: after each new test
   passes, temporarily disable the production code it covers and confirm
   the test fails. Targeted disabling beats upstream gating.
10. **Plain-english steps before code** (reinforced this arc): for each
    new test, write the numbered steps as comments first, get sign-off,
    then write code.
11. **Plans-with-pseudocode collapse implementation to mechanical typing**
    (lesson from production wiring): when a plan specifies variant
    tables, signatures, message text, and file targets, actual
    implementation is ~5% of an "open-spec" hours estimate. Don't pad
    estimates that high.

## Key gotchas / non-obvious knowledge

- **Pytest discovery**: only finds `test_*.py` files by default. Tests
  inside `helpers.py` are NOT discovered when running the directory —
  must pass the path explicitly.
- **`pytest` not on PATH** — use `rtk pytest`.
- **Git refuses to checkout a branch that would clobber untracked
  files**. To inspect a plate branch's contents without disturbing WT,
  use `git ls-tree -r --name-only <branch>` instead of checking it out.
- **Unborn HEAD**: `checkIfGitBranchExists(repo, "main")` returns `False` until
  the first commit, even though `git symbolic-ref` returns `"main"`.
- **Git trailers are single-line by spec**. `convo_summary` input is
  collapsed via `" ".join(text.split())`.
- **`git reset --hard <sha>` preserves untracked files**. Use
  `gitCleanWorkTree(repo)` (`git clean -fd`) to actually start fresh —
  but it skips ignored paths (e.g., `.plate/`), which is what we want.
- **Title resolution precedence in `plate_next` listing**: live
  transcript `customTitle` → `convo-name` trailer → parent-branch name
  → ref name. Implemented in `_resolvePlateTitle`.
- **`PLATE_NEXT_LOST_MESSAGE` is intentionally also returned in the
  remote-handoff case** (transcript not readable but `convo-summary`
  trailer present) — message tells next agent to read summary from git.
- **Hook output contract**: every `/plate` invocation ends with
  `emit_block "..."` + `exit 0`. `decision:"block"` tells Claude Code
  to show our `reason` text instead of forwarding the prompt to the
  model. Never use exit 2 (would surface stderr as model error).
- **Python stdout becomes user-facing copy**: the return value of every
  `plate_*` function is what the user sees in the conversation. String
  formatting in `plate_lib.py` is UX copy, not internal API.
- **`2>&1` in plate.sh leaks Python stderr into the user-visible reason**
  — `plate_drop`'s `warning: no plate branch...` line currently shows
  up. Cosmetic; suppress at source when fixing.
- **BSD `find` lacks `-printf`** on macOS. Use
  `find ... -exec stat -f '%m %N' {} +` instead of GNU `find -printf`.
- **`shlex.split("rm $(cat list.txt)")`** produces tokens like
  `'list.txt)'` — parens count as shell-expansion characters in the
  deletion-extractor's filter.
- **`str.isdigit()` rejects** letters, decimals, signs, mixed input,
  empty strings, whitespace, and symbols. Used as the `_plate_next_jump`
  numeric-only guard.

## Files to know

| Path | Purpose |
|---|---|
| `skills/plate/tests/sequence/helpers.py` | Plate ops + sub-functions + helpers + per-function unit tests + `_check_*` scenarios |
| `skills/plate/tests/sequence/test_helpers.py` | Helper smoke tests + `test_sequence_NN` integration tests |
| `skills/plate/tests/sequence/test_plate_cli.py` | Mock-based CLI argv routing + trailer kwarg propagation |
| `skills/plate/tests/sequence/test_plate_e2e_wiring.py` | Hook JSON → orchestrator → plate_cli.py → emit_block contract |
| `skills/plate/tests/sequence/test_session_end_hook.py` | Auto-`/plate` SessionEnd pipeline |
| `skills/plate/tests/sequence/conftest.py` | Pytest `repo` fixture |
| `common/scripts/plate/plate_cli.py` | Single Python entry point — production dispatcher |
| `skills/plate/scripts/plate.sh` | UserPromptSubmit hook → plate_cli.py wiring |
| `hooks/hooks.json` | UserPromptSubmit + SessionEnd hook entries |
| `scripts/jot-plugin-orchestrator.sh` | Central UserPromptSubmit dispatcher (jot/plate/debate/todo) |
| `skills/plate/SKILL.md` | Slash-command stub (collapsed to /jot-style) |
| `skills/plate/PLATE STATE.md` | Forward roadmap + dead-code purge list |
| `skills/plate/DESIGN.md` | Pre-refactor design spec (HISTORICAL — see banner) |
| `skills/plate/IMPLEMENTATION.md` | Pre-refactor engineering plan (HISTORICAL — see banner) |

## Where to pick up

Roadmap from PLATE STATE.md, in order:

1. **`generatePlateSummary` (background tmux agent)** — fired
   post-plate-commit. Reads the convo's `transcript_path`, produces the
   structured ~400-word summary, writes it to the new plate's
   `convo-summary` trailer, AND strips `convo-summary` trailers from
   earlier plate commits (only the latest plate carries a summary).
   `cli.py` currently calls a stub returning `None`; replace the stub
   when the agent ships.
2. **`convo-summary` format spec** — exact sections, ordering, fields
   for the ~400-word block. Goal: a reader picks up the work productively
   in under a minute.

Stage 2 / polish (separate commits):

- **Dead-code purge**: ~23 files in `skills/plate/scripts/` and
  `common/scripts/plate/` tied to the old stash-ref + JSON-instance
  model. Full list in PLATE STATE.md §C.
- **Cosmetic**: suppress `plate_drop` stderr warning that leaks through
  `2>&1` into the user-visible `reason`.
- **Proper `helpers.py` → `plate_lib.py` move + test split**: currently
  cli.py uses `sys.path` injection into the test tree. Lower priority.
- **`--show` variant design**: currently returns literal `"TODO"`.
