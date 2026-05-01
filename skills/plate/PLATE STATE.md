# /plate Skill — Current State and Gap to Shippable v1.0

_Snapshot: 2026-05-01 (evening — production wiring landed)_

## What the harness actually has (verified)

8 plate operations are **implemented + tested + wired to the `/plate` slash command** via `common/scripts/plate/cli.py` and `skills/plate/scripts/plate.sh` (`plate_carry` deprecated and removed):

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

**136 passing tests, 0 failures.**

### Recent additions

**2026-05-01 (evening) — production wiring landed (PLATE STATE.md §A resolved)**:

- `/plate` slash command now invokes `common/scripts/plate/cli.py` directly via the existing UserPromptSubmit hook (`scripts/orchestrator.sh`). All variants run inline — no `pending-*.json` drop files, no SKILL.md AskUserQuestion bridges, no foreground-claude detour.
- `skills/plate/scripts/plate.sh` rewritten to mirror `jot.sh::jot_main` shape: substring fast-path filter, strict prompt regex, hook JSON parse, `cli.py` exec, single `emit_block` per terminal exit, `ERR` trap.
- `skills/plate/SKILL.md` collapsed to /jot-style stub — front-matter `name`/`description` plus the same `# Task: do nothing.` body that tells the foreground claude not to react.
- `common/scripts/plate/cli.py` (NEW, 175 LoC) — single argv dispatcher for 8 variants: `push`, `done`, `drop`, `trash`, `recycle`, `next`, `next <#>`, `show` (currently returns `"TODO"`; design deferred). Uses `sys.path` injection to import `helpers.py` as `plate_lib` (proper move + test split deferred).
- `plate_next(repo, index)` signature change: `Optional[int]` → `Optional[str]`. CLI passes argv straight through; `_plate_next_jump` validates numeric-only via `str.isdigit()` before range check. New constant `PLATE_NEXT_NON_NUMERIC_MESSAGE = "--next <#>: <#> must be a number and not letters or symbols."`. `"-1"` migrated from range-check bucket → non-numeric bucket.
- 24 new tests: 16 in `test_cli.py` (mock-based variant routing + trailer kwarg propagation), 8 in `test_e2e_wiring.py` (hook JSON → `decision:"block"` JSON contract). E2E test suite proves the full pipeline (orchestrator → plate.sh → cli.py → plate_lib → emit_block) works end-to-end and that the substring fast-path silently bails on non-/plate prompts.
- Rigor checks done: disabled `isdigit()` guard → invalid-index test fails via `int("abc")` ValueError; pointed CLI_PATH at non-existent file → e2e test fails with "no such file" reason. Both restored.

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

### A. Production wiring — DONE 2026-05-01 (resolved)

`/plate` slash command now executes the branch-model code via `cli.py`. Plan was Option 3 from the prior version of this doc (single Python entry point); see "Recent additions" above for details. Old shell scripts and Python helpers tied to the stash-ref + JSON-instance model still exist on disk but are no longer reachable from `/plate`. Stage 2 (dead-code purge) remains as a follow-up commit (see §C below).

### B. Roadmap (in execution order)

1. ~~**Production wiring**~~ — DONE.
2. **Auto-`/plate` on `SessionExit` hook** — fire `plate_push` automatically when a Claude session ends. Wiring is in place; just needs a SessionExit hook entry that posts a `/plate`-equivalent payload to the orchestrator (or invokes `cli.py push` directly).
3. **`generatePlateSummary` (background tmux agent)** — fired post-plate-commit. Reads the repo and the convo's `transcript_path` (passed as context), produces the structured ~400-word summary, writes it to the new plate's `convo-summary` trailer, AND strips `convo-summary` trailers from earlier plate commits (only the latest plate carries a summary). `cli.py` currently calls a stub returning `None`; replace the stub when the agent ships.
4. **`convo-summary` format spec** — exact sections, ordering, and fields for the ~400-word block. Goal: a reader can pick up the work productively in under a minute.

### C. Dead-code purge (Stage 2 follow-up commit)

The branch-model wiring landed in parallel — old code paths still exist on disk but are unreferenced by `/plate`. Separate commit recommended for clean revertability:

- `skills/plate/scripts/`: `push.sh`, `done.sh`, `drop.sh`, `next.sh`, `list-paused-plates.sh`, `register-parent.sh`, `snapshot-stash.sh`, `branch-snapshot.sh`, `branch-snapshot.v2.sh` (~10 files)
- `common/scripts/plate/`: `instance_rw.py`, `append_plate_to_stack.py`, `cascade_parent_chain.py`, `check_drift_alert.py`, `check_live_children.py`, `check_rolling_intent_refresh.py`, `clear_drift_alert.py`, `list_paused_plates.py`, `next_resume_point.py`, `print_resume_pointer.py`, `register_parent.py`, `verify_stash_refs.py`, `build_settings_json.py` (~13 files)
- KEEP: `transcript_parse.py` (used by future summary work), `render_tree.sh` / `render_tree.py` (kept around since `--show` design is deferred)

Resolved (and removed from the open list) — preserved here so future readers see the trail of decisions:
- ~~Production wiring strategy choice~~ — Option 3 (single Python entry) selected and shipped.
- ~~`plate_next` semantics~~ — list/jump navigator across independent plates (not derived-chain walker).
- ~~JSON metadata layer~~ — replaced by commit trailers (`convo-id`, `parent-branch`, `convo-name`, `convo-summary`).
- ~~`--carry` with clean WT: picker-only vs error~~ — moot; `plate_carry` removed in favor of `plate_next`.
- ~~`simulate_derived_agent` production trigger~~ — kept only for explicit chained-delegation. Multi-agent same-branch attribution is now handled by `plate_push`'s shared-branch + transcript-extraction logic.
- ~~`.plate/` directory layout finalization~~ — only `dropped/` and `trashed/` live there; nothing else needs design.
- ~~EditFile per-agent file list~~ — was an artifact of the old JSON `files` field. The branch-model implementation captures plate trees as commits, so per-agent file lists are computable directly via `git diff <plate>~1..<plate> --name-only`. No hook needed.

## Bottom line: what "delivered" looks like

Stage 1 (production wiring) shipped 2026-05-01. Remaining work to v1.0:

1. **Stage 2 dead-code purge** — ~30 min. Separate commit; trivial deletes once Stage 1 lives in production.
2. **Auto-`/plate` on SessionExit** — ~30–60 min. Add hook entry that calls `cli.py push` with the session's transcript path.
3. **`convo-summary` format spec** — ~1–2 h. Small design doc; ordering, sections, length budget.
4. **`generatePlateSummary` background agent** — ~2–3 h. Tmux launcher + sub-agent prompt + post-commit trailer write + earlier-plate trailer strip.
5. **Cosmetic: suppress `plate_drop` stderr warning** that leaks through `2>&1` into the user-visible `reason` — ~10 min.
6. **Proper `helpers.py` → `plate_lib.py` move + test split** — ~1–2 h. Currently cli.py uses `sys.path` injection into the test tree; works but is a wart. Lower priority since plate isn't yet packaged.

**Total remaining: ~5–8 hours** spread across follow-ups. The user-facing `/plate` command is functional today.

The current state is a **complete, verified foundation with live wiring** — canonical sequences, major error paths, `plate_next` navigation with cross-machine summary handoff, shared-plate-branch attribution for multiple parallel agents, and the user-facing slash command are all locked in. Remaining work is auto-fire mechanics and summary-generation polish, not core capability.
