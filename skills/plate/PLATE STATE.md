# /plate Skill — Current State and Gap to Shippable v1.0

_Snapshot: 2026-04-30_

## What the harness actually has (verified)

All 9 plate operations are **implemented + tested** in `skills/plate/tests/sequence/helpers.py`:

| Operation | Test location | Status |
|---|---|---|
| `plate_push` | helpers.py + test_sequence_01, 02, 04 | ✅ implemented + 3 sequence tests + convo trailer plumbing (`convo-id`, `convo-name`, `convo-summary`, `parent-branch`) |
| `plate_done` | helpers.py + test_sequence_03, 04, 18, 20 | ✅ happy-path + conflict-abort + reflog tests |
| `plate_drop` | helpers.py + test_sequence_05, 06, 15, 19 | ✅ implemented + missing-branch + cross-repo portability |
| `plate_trash` | helpers.py + test_sequence_08, 16 | ✅ default + `clean_wt=True` + missing-branch |
| `plate_recycle` | helpers.py + test_sequence_10, 17 | ✅ implemented + missing-session warning |
| `plate_carry` | helpers.py + test_sequence_11 | ✅ implemented |
| `plate_next` | helpers.py + test_sequence_21 | ✅ list/jump split — see "plate_next redesign" below |
| `simulate_derived_agent` | helpers.py + test_sequence_12, 13 | ✅ first + second derived |
| `apply_patch` | helpers.py + test_sequence_07, 19 | ✅ implemented + round-trip + cross-repo |

**110 passing tests, 0 failures.**

### Recent additions

**2026-04-30 (afternoon) — `plate_next` redesign**:

- `plate_push` gained optional `convo_id`, `convo_name`, `convo_summary` kwargs; always writes a `parent-branch:` trailer derived from `getCurrentBranchName(repo)`.
- `plate_next(repo, index=None)` now delegates to `_plate_next_list` (no index) or `_plate_next_jump` (index given). Old derived-chain semantics removed (`test_sequence_14` deleted).
- New helpers: `formatPlateAge`, `listPlateBranches`, `extractConvoNameFromTranscript`, `extractConvoCwdFromTranscript`, `localTranscriptIsReadable`.
- Three return paths in jump-mode: local-resume (`cd <cwd> && claude --resume <name>`), lost (`PLATE_NEXT_LOST_MESSAGE`), self-index no-op. Invalid-index returns `PLATE_NEXT_INVALID_INDEX_MESSAGE`. Empty list returns `PLATE_NEXT_EMPTY_LIST_MESSAGE`.
- Cross-machine handoff via Solution B: `convo-summary` trailer carries a structured ~400-word summary the next agent reads directly from git when the originating transcript file isn't on this machine.

**2026-04-30 (morning) — error-path tests**: missing-branch guards on `--drop` / `--trash` / `--recycle` (warn on stderr, return None); cherry-pick conflict abort in `plate_done` (restores HEAD/WT, preserves plate branch); test sequences 15–20 covering previously-untested error paths.

## What's actually missing for a shippable /plate

### A. Production wiring (the big gap)

The harness is **Python**. The `/plate` slash command users invoke calls **shell scripts** in `skills/plate/scripts/` that use a **different model** (stash-refs, not branch commits). The two implementations are not connected. To ship the branch-model design we just tested, you need ONE of:

1. **Wire shell scripts to call the Python helpers** (e.g., `push.sh` shells out to `python -c "from helpers import plate_push; plate_push(...)"`). Pays the ~50–100ms Python startup cost per call.
2. **Port the Python helpers back into shell** (`branch-snapshot.v2.sh` already exists for `push` but `done.sh`, `drop.sh`, etc., don't have branch-model versions). Manual translation work.
3. **Replace shell scripts entirely** with a single Python entry point. Cleanest, but changes the SKILL.md plumbing.

### B. Open design decisions

Items still flagged as needing user decision:

- `--carry` with clean WT: picker-only vs error
- `simulate_derived_agent`: production trigger (when does an "agent" actually become "derived"?)
- `.plate/` directory layout finalization (currently just `dropped/` and `trashed/`)
- EditFile per-agent file list (blocked on a hook that doesn't exist yet)
- Auto-`/plate` on `SessionExit` hook
- **`convo-summary` format spec** — exact 400-word structure TBD (sections, ordering, fields). Goal: a reader can pick up the work productively in under a minute.
- **`generatePlateSummary` implementation** — the agent code that produces the summary at push time (likely a sub-agent prompt, hook, or inline LLM call). Out of scope for the harness; in scope for the slash-command bridge.

Resolved this session and removed from the open list:
- ~~`plate_next` semantics~~ — list/jump navigator across independent plates (not derived-chain walker).
- ~~JSON metadata layer~~ — replaced by commit trailers (`convo-id`, `parent-branch`, `convo-name`, `convo-summary`).

## Bottom line: what "delivered" looks like

Roughly **12–20 hours** of work split across:

1. **Decide on the production wiring strategy** — 1–2h discussion
2. **Wire the chosen path** — 6–10h (script bridge or full port)
3. **Resolve the remaining design decisions above** — 3–4h
4. **Define the `convo-summary` format and wire `generatePlateSummary`** — 2–3h
5. **Production validation**: run `/plate` interactively in a real conversation, confirm hooks fire, trailers write, plate_next list/jump works end-to-end — 2–3h

The current state is a **strong foundation** — the canonical sequences, the major error paths (missing-branch, cherry-pick conflict, cross-repo patch portability, reflog recoverability), and `plate_next` navigation across independent plates with cross-machine summary handoff are all locked in and verified. What's missing is mostly the plumbing to expose this work to actual users via the `/plate` command, the `convo-summary` format, and the remaining design choices.
