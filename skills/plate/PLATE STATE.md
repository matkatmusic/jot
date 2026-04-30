# /plate Skill — Current State and Gap to Shippable v1.0

_Snapshot: 2026-04-30_

## What the harness actually has (verified)

All 9 plate operations are **implemented + tested** in `skills/plate/tests/sequence/helpers.py`:

| Operation | Test location | Status |
|---|---|---|
| `plate_push` | helpers.py + test_sequence_01, 02, 04 | ✅ implemented + 3 sequence-level tests |
| `plate_done` | helpers.py + test_sequence_03, 04, 18, 20 | ✅ implemented + happy-path + conflict-abort + reflog tests |
| `plate_drop` | helpers.py + test_sequence_05, 06, 15, 19 | ✅ implemented + missing-branch + cross-repo portability |
| `plate_trash` | helpers.py + test_sequence_08, 16 | ✅ default + `clean_wt=True` + missing-branch |
| `plate_recycle` | helpers.py + test_sequence_10, 17 | ✅ implemented + missing-session warning |
| `plate_carry` | helpers.py + test_sequence_11 | ✅ implemented |
| `plate_next` | helpers.py + test_sequence_14 | ✅ implemented (semantic discrepancy noted) |
| `simulate_derived_agent` | helpers.py + test_sequence_12, 13 | ✅ first + second derived |
| `apply_patch` | helpers.py + test_sequence_07, 19 | ✅ implemented + round-trip + cross-repo |

**90 passing tests, 0 failures.**

Recent additions (2026-04-30): missing-branch guards on `--drop` / `--trash` /
`--recycle` (warn on stderr, return None); cherry-pick conflict abort in
`plate_done` (restores HEAD/WT, preserves plate branch); test sequences
15–20 covering the previously-untested error paths.

## What's actually missing for a shippable /plate

### A. Production wiring (the big gap)

The harness is **Python**. The `/plate` slash command users invoke calls **shell scripts** in `skills/plate/scripts/` that use a **different model** (stash-refs, not branch commits). The two implementations are not connected. To ship the branch-model design we just tested, you need ONE of:

1. **Wire shell scripts to call the Python helpers** (e.g., `push.sh` shells out to `python -c "from helpers import plate_push; plate_push(...)"`). Pays the ~50–100ms Python startup cost per call.
2. **Port the Python helpers back into shell** (`branch-snapshot.v2.sh` already exists for `push` but `done.sh`, `drop.sh`, etc., don't have branch-model versions). Manual translation work.
3. **Replace shell scripts entirely** with a single Python entry point. Cleanest, but changes the SKILL.md plumbing.

### B. Open design decisions in `plans/plate-walkthrough-log-2026-04-28.md`

Items still flagged as needing user decision:

- `--carry` with clean WT: picker-only vs error
- `simulate_derived_agent`: production trigger (when does an "agent" actually become "derived"?)
- **`plate_next` semantics**: walkthrough spec says "deepest convo" (B), implementation returns parent-convo (A). `test_sequence_14` currently asserts the implementation; one of them needs to change.
- `.plate/` directory layout finalization (currently just `dropped/` and `trashed/`)
- JSON metadata layer — DESIGN.md §6 calls for `.plate/instances/<convoID>.json` tracking, harness doesn't have this
- EditFile per-agent file list (blocked on a hook that doesn't exist yet)
- Auto-`/plate` on `SessionExit` hook

## Bottom line: what "delivered" looks like

Roughly **15–25 hours** of work split across:

1. **Decide on the model** (Python vs shell, branch vs stash-ref) — 1–2h discussion
2. **Wire the chosen path** — 6–10h (script bridge or full port)
3. **Resolve the design decisions above** — 4–6h (mostly choices, not coding)
4. **Production validation**: actually run `/plate` interactively in a real conversation, confirm hooks fire, JSON metadata writes correctly, etc. — 3–4h

The current state is a **strong foundation** — the canonical sequences plus
the major error paths (missing-branch, cherry-pick conflict, cross-repo
patch portability, reflog recoverability) are locked in and verified, and
the hardest design decisions (branch model, per-plate patches in trash,
derived agent trailers, warn-and-exit on missing branch, abort-and-restore
on conflict) are settled with tests. What's missing is mostly the plumbing
to expose this work to actual users via the `/plate` command, plus the
remaining unresolved design choices that you'd want signed off before
shipping.
