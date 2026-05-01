# /plate Skill — Current State and Gap to Shippable v1.0

_Snapshot: 2026-05-01_

## What the harness actually has (verified)

8 plate operations are **implemented + tested** in `skills/plate/tests/sequence/helpers.py` (`plate_carry` deprecated and removed):

| Operation | Test location | Status |
|---|---|---|
| `plate_push` | helpers.py + test_sequence_01, 02, 04 | ✅ shared-branch model + convo trailer plumbing (`convo-id`, `convo-name`, `convo-summary`, `parent-branch`) + multi-agent same-branch attribution via transcript extraction |
| `plate_done` | helpers.py + test_sequence_03, 04, 18, 20 | ✅ happy-path + conflict-abort + reflog tests |
| `plate_drop` | helpers.py + test_sequence_05, 06, 15, 19 | ✅ implemented + missing-branch + cross-repo portability |
| `plate_trash` | helpers.py + test_sequence_08, 16 | ✅ default + `clean_wt=True` + missing-branch |
| `plate_recycle` | helpers.py + test_sequence_10, 17 | ✅ implemented + missing-session warning |
| `plate_next` | helpers.py + test_sequence_21 | ✅ list/jump split — subsumes plate_carry's role |
| `simulate_derived_agent` | helpers.py + test_sequence_12, 13 | ✅ explicit chained-delegation only (the sibling auto-detection model was replaced by shared-branch + extraction) |
| `apply_patch` | helpers.py + test_sequence_07, 19 | ✅ implemented + round-trip + cross-repo |

**112 passing tests, 0 failures.**

### Recent additions

**2026-05-01 — multi-agent shared-plate-branch attribution**:

- Replaced sibling-derived auto-detection with the shared-plate-branch + transcript-extraction model. Multiple agents working on the same git branch all push to the same `<branch>-plate` ref; per-agent attribution lives in commit trailers; per-agent change isolation comes from parsing each agent's transcript.
- New helpers: `findMyLastPlate`, `extractFilesEditedSinceTimestamp`, `extractFilesDeletedSinceTimestamp`, `_buildFullWtTree`, `_buildExtractedTree`.
- `plate_push` now picks between full-WT-snapshot (same-author / first-time) and extracted-tree (mixed-author) based on the previous plate's `convo-id` trailer. The mixed-author path stages only files the current agent edited (per `Edit`/`Write`/`MultiEdit`/`NotebookEdit` tool_use entries) and removes only files the agent deleted (per `Bash` `rm`/`git rm` parsing, filtered to inside-repo paths tracked at the parent commit).
- Integration test verifies a 4-step Pa1 → Pb1 → Pa2 → Pb2 sequence including a deletion: each commit captures only its author's attributable changes; the other agent's intervening unplated WT edits stay in WT for their own next plate.

**2026-04-30 (late afternoon) — `plate_carry` removed**: deprecated and deleted. `plate_next(repo, index)` subsumes carry's job with better UX — index-based picker, automatic pre-push, lands HEAD on the target's parent branch with the plate's tree as actionable WIP, and emits a resume command. The two helper tests + sequence_11 were removed.

**2026-04-30 (afternoon) — `plate_next` redesign**:

- `plate_push` gained optional `convo_id`, `convo_name`, `convo_summary` kwargs; always writes a `parent-branch:` trailer derived from `getCurrentBranchName(repo)`.
- `plate_next(repo, index=None)` now delegates to `_plate_next_list` (no index) or `_plate_next_jump` (index given). Old derived-chain semantics removed (`test_sequence_14` deleted).
- New helpers: `formatPlateAge`, `listPlateBranches`, `extractConvoNameFromTranscript`, `extractConvoCwdFromTranscript`, `localTranscriptIsReadable`.
- Three return paths in jump-mode: local-resume (`cd <cwd> && claude --resume <name>`), lost (`PLATE_NEXT_LOST_MESSAGE`), self-index no-op. Invalid-index returns `PLATE_NEXT_INVALID_INDEX_MESSAGE`. Empty list returns `PLATE_NEXT_EMPTY_LIST_MESSAGE`.
- Cross-machine handoff via Solution B: `convo-summary` trailer carries a structured ~400-word summary the next agent reads directly from git when the originating transcript file isn't on this machine.

**2026-04-30 (morning) — error-path tests**: missing-branch guards on `--drop` / `--trash` / `--recycle` (warn on stderr, return None); cherry-pick conflict abort in `plate_done` (restores HEAD/WT, preserves plate branch); test sequences 15–20 covering previously-untested error paths.

## What's actually missing for a shippable /plate

### A. Production wiring (the big gap, blocks all of §B's roadmap items)

The harness is **Python**. The `/plate` slash command users invoke calls **shell scripts** in `skills/plate/scripts/` that use a **different model** (stash-refs, not branch commits). The two implementations are not connected. To ship the branch-model design we just tested, you need ONE of:

1. **Wire shell scripts to call the Python helpers** (e.g., `push.sh` shells out to `python -c "from helpers import plate_push; plate_push(...)"`). Pays the ~50–100ms Python startup cost per call.
2. **Port the Python helpers back into shell** (`branch-snapshot.v2.sh` already exists for `push` but `done.sh`, `drop.sh`, etc., don't have branch-model versions). Manual translation work.
3. **Replace shell scripts entirely** with a single Python entry point. Cleanest, but changes the SKILL.md plumbing.

### B. Roadmap (in execution order)

1. **Production wiring** (§A above) — single shell entry point that invokes the Python delegating function, which calls the existing library code in `helpers.py`.
2. **Auto-`/plate` on `SessionExit` hook** — fire `plate_push` automatically when a Claude session ends. Requires the production wiring to be in place so the hook has something to call.
3. **`generatePlateSummary` (background tmux agent)** — fired post-plate-commit. Reads the repo and the convo's `transcript_path` (passed as context), produces the structured ~400-word summary, writes it to the new plate's `convo-summary` trailer, AND strips `convo-summary` trailers from earlier plate commits (only the latest plate carries a summary).
4. **`convo-summary` format spec** — exact sections, ordering, and fields for the ~400-word block. Goal: a reader can pick up the work productively in under a minute.

Resolved (and removed from the open list) — preserved here so future readers see the trail of decisions:
- ~~`plate_next` semantics~~ — list/jump navigator across independent plates (not derived-chain walker).
- ~~JSON metadata layer~~ — replaced by commit trailers (`convo-id`, `parent-branch`, `convo-name`, `convo-summary`).
- ~~`--carry` with clean WT: picker-only vs error~~ — moot; `plate_carry` removed in favor of `plate_next`.
- ~~`simulate_derived_agent` production trigger~~ — kept only for explicit chained-delegation. Multi-agent same-branch attribution is now handled by `plate_push`'s shared-branch + transcript-extraction logic.
- ~~`.plate/` directory layout finalization~~ — only `dropped/` and `trashed/` live there; nothing else needs design.
- ~~EditFile per-agent file list~~ — was an artifact of the old JSON `files` field. The branch-model implementation captures plate trees as commits, so per-agent file lists are computable directly via `git diff <plate>~1..<plate> --name-only`. No hook needed.

## Bottom line: what "delivered" looks like

Roughly **10–17 hours** of work in this order:

1. **Decide on the production wiring strategy** — 1–2h discussion.
2. **Wire the chosen path** — 6–10h (script bridge or full port).
3. **Implement auto-`/plate` on SessionExit** — 1–2h once wiring is in.
4. **Define `convo-summary` format spec + wire `generatePlateSummary`** — 2–3h.
5. **Production validation**: run `/plate` interactively in a real conversation, confirm hooks fire, trailers write, plate_next list/jump works end-to-end, multi-agent shared-branch flow holds — 2–3h.

The current state is a **strong foundation** — the canonical sequences, the major error paths (missing-branch, cherry-pick conflict, cross-repo patch portability, reflog recoverability), `plate_next` navigation across independent plates with cross-machine summary handoff, and shared-plate-branch attribution for multiple parallel agents are all locked in and verified. What's missing is the plumbing to expose this work to actual users via the `/plate` command and the auto-fire mechanics around it.
