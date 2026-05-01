# /plate Skill — Current State and Gap to Shippable v1.0

_Snapshot: 2026-05-01 (overnight — generatePlateSummary tmux agent wired)_

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

**140 passing tests, 0 failures.**

Auto-`/plate` on session end is wired: `hooks/hooks.json`'s `SessionEnd` entry pipes the hook payload through `jq '. + {prompt: "/plate"}'` into `scripts/orchestrator.sh`. Belt-and-suspenders `[ "$PLATE_SKIP_AUTO" = "1" ] && exit 0` guard prevents re-entrant fires from the spawned summary agent.

generatePlateSummary is wired: after each successful `cli.py push`, `common/scripts/plate/spawn_summary_agent.py` fires a tmux pane running a claude agent with `skills/plate/scripts/prompts/summary-agent.md` as its first message. The agent reads the plate branch + transcript, writes a 5-section summary (per `skills/plate/summary-template.md`) to a tempdir output file. The pane's per-invocation SessionEnd hook (`plate-summary-stop.sh`) calls `cli.py set-plate-summary` which runs `plate_lib.rewriteBranchTipSummary` — a `git rebase -i` reword (in a detached worktree) driven by `_rebase_reword_summary.py` that strips `convo-summary` trailers from older commits and adds the new one to the tip.

## Roadmap (in execution order)

1. **`convo-summary` format spec polish** — current 5-section template (`what:`, `why:`, `how:`, `open questions:`, `next steps:`) lives in `skills/plate/summary-template.md`. Live validation across real conversations may surface refinements (length cap, ordering, missing fields). Treat as iterate-after-soak rather than block-before-ship.

## Dead-code purge (Stage 2 follow-up commit)

Old stash-ref + JSON-instance code paths still exist on disk but are unreferenced by `/plate`. Separate commit recommended for clean revertability:

- `skills/plate/scripts/`: `push.sh`, `done.sh`, `drop.sh`, `next.sh`, `list-paused-plates.sh`, `register-parent.sh`, `snapshot-stash.sh`, `branch-snapshot.sh`, `branch-snapshot.v2.sh` (~10 files)
- `common/scripts/plate/`: `instance_rw.py`, `append_plate_to_stack.py`, `cascade_parent_chain.py`, `check_drift_alert.py`, `check_live_children.py`, `check_rolling_intent_refresh.py`, `clear_drift_alert.py`, `list_paused_plates.py`, `next_resume_point.py`, `print_resume_pointer.py`, `register_parent.py`, `verify_stash_refs.py`, `build_settings_json.py` (~13 files)
- KEEP: `transcript_parse.py` (used by future summary work), `render_tree.sh` / `render_tree.py` (kept around since `--show` design is deferred)

## Known polish items

- **Cosmetic**: `plate_drop` prints `warning: no plate branch...` to stderr; `2>&1` in plate.sh leaks it into the user-visible `reason`. Suppress in plate_drop or filter in cli.py.
- **Proper `helpers.py` → `plate_lib.py` move + test split** — currently cli.py uses `sys.path` injection into the test tree. Works but is a wart. Lower priority since plate isn't yet packaged.
- **`--show` variant** currently returns literal `"TODO"`; design deferred.

## Bottom line

`/plate` is functional today, including auto-fire on SessionEnd and async summary generation. Remaining work to v1.0: dead-code purge (~30 min), live-validate the summary agent against real conversations (~30 min), polish items (~1 h). Core capability is complete.

## Live validation needed (before declaring shipped)

- Open a real Claude conversation in a git repo.
- Make a code change, run `/plate`. Assert `git log <branch>-plate -1` shows convo-id/convo-name/parent-branch trailers immediately, and the convo-summary trailer materializes ~30s later (when the spawned tmux agent finishes).
- Run `/plate` again with another change. Assert ONLY the new tip has `convo-summary`; the prior tip's summary has been stripped.
- Close the conversation (no `/plate`). Assert SessionEnd auto-fire creates a plate with the WIP captured.
