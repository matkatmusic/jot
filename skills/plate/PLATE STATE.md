# /plate Skill — Current State and Gap to Shippable v1.0

_Snapshot: 2026-04-30_

## What the harness actually has (verified)

All 9 plate operations are **implemented + tested** in `skills/plate/tests/sequence/helpers.py`:

| Operation | Test location | Status |
|---|---|---|
| `plate_push` | helpers.py + test_sequence_01, 02, 04 | ✅ implemented + 3 sequence-level tests |
| `plate_done` | helpers.py + test_sequence_03, 04 | ✅ implemented + 2 sequence-level tests |
| `plate_drop` | helpers.py + test_sequence_05, 06 | ✅ implemented + 2 sequence-level tests |
| `plate_trash` | helpers.py + test_sequence_08 | ✅ both default and `clean_wt=True` modes |
| `plate_recycle` | helpers.py + test_sequence_10 | ✅ implemented |
| `plate_carry` | helpers.py + test_sequence_11 | ✅ implemented |
| `plate_next` | helpers.py + test_sequence_14 | ✅ implemented (semantic discrepancy noted) |
| `simulate_derived_agent` | helpers.py + test_sequence_12, 13 | ✅ first + second derived |
| `apply_patch` | helpers.py + test_sequence_07 | ✅ implemented + round-trip |

**78 passing tests, 0 failures.**

## What's actually missing for a shippable /plate (3 categories)

### A. Production wiring (the big gap)

The harness is **Python**. The `/plate` slash command users invoke calls **shell scripts** in `skills/plate/scripts/` that use a **different model** (stash-refs, not branch commits). The two implementations are not connected. To ship the branch-model design we just tested, you need ONE of:

1. **Wire shell scripts to call the Python helpers** (e.g., `push.sh` shells out to `python -c "from helpers import plate_push; plate_push(...)"`). Pays the ~50–100ms Python startup cost per call.
2. **Port the Python helpers back into shell** (`branch-snapshot.v2.sh` already exists for `push` but `done.sh`, `drop.sh`, etc., don't have branch-model versions). Manual translation work.
3. **Replace shell scripts entirely** with a single Python entry point. Cleanest, but changes the SKILL.md plumbing.

### B. Open design decisions in `plans/plate-walkthrough-log-2026-04-28.md`

Items still flagged as needing user decision:

- `--trash` patch granularity: per-plate (current impl) vs combined
- `--recycle` session selection when multiple trashed: most-recent default vs require timestamp
- `--carry` with clean WT: picker-only vs error
- `simulate_derived_agent`: production trigger (when does an "agent" actually become "derived"?)
- **`plate_next` semantics**: walkthrough spec says "deepest convo" (B), implementation returns parent-convo (A). `test_sequence_14` currently asserts the implementation; one of them needs to change.
- `.plate/` directory layout finalization (currently just `dropped/` and `trashed/`)
- JSON metadata layer — DESIGN.md §6 calls for `.plate/instances/<convoID>.json` tracking, harness doesn't have this
- EditFile per-agent file list (blocked on a hook that doesn't exist yet)
- Auto-`/plate` on `SessionExit` hook

### C. Untested error paths

The 14 sequence tests cover the **happy path** for each operation. From `plans/plate-test-scenarios.md`, these scenarios are documented but untested:

- Cherry-pick conflict during `plate_done` (branch advanced between push and done)
- `--drop` / `--trash` / `--recycle` with no plate branch existing
- Cross-repo patch portability (patch from repo A applies in repo B)
- Reflog recovery after `--done` deletes plate branch
- Cherry-pick aborted mid-sequence (cleanup behavior)

## Bottom line: what "delivered" looks like

Roughly **20–30 hours** of work split across:

1. **Decide on the model** (Python vs shell, branch vs stash-ref) — 1–2h discussion
2. **Wire the chosen path** — 6–10h (script bridge or full port)
3. **Resolve the design decisions above** — 4–6h (mostly choices, not coding)
4. **Add error-path tests** — 6–8h (cherry-pick conflicts, missing-plate paths, cross-repo portability)
5. **Production validation**: actually run `/plate` interactively in a real conversation, confirm hooks fire, JSON metadata writes correctly, etc. — 3–4h

The current state is a **strong foundation** — the canonical sequences are locked in and verified, and the hardest design decisions (branch model, per-plate patches in trash, derived agent trailers) are settled with tests. What's missing is mostly the plumbing to expose this work to actual users via the `/plate` command, plus ~5 unresolved design choices that you'd want signed off before shipping.
