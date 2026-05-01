# /plate Skill — State

_Snapshot: 2026-05-01 (post live-test polish)._ 141 passing tests. Live-tested: `/plate` push, generatePlateSummary trailer pipeline (end-to-end), auto-Terminal.app spawn.

## Live validation still pending

In dependency order — each is wired and unit-tested but hasn't been exercised in a real conversation yet:

1. **Per-repo log destination**: `<repo>/.plate/plate-log.txt` accumulates entries from both `plate.sh` and the spawned summary agent's hooks (PLATE_LOG_FILE export).
2. **Older-plate summary stripping**: run `/plate` twice in the same conversation; assert ONLY the new tip carries `convo-summary` after the second run completes.
3. **Auto-`/plate` on `SessionEnd`**: close a Claude conversation (without manually running `/plate`) in a dirty repo; assert a plate ref appears with the WIP captured.
4. **Drop / trash / recycle round-trip**, all four variants:
   - `/plate --drop` → `<repo>/.plate/trash/<branch>/<ts>_dropped_<sha>/{info.json, plate_001.patch}` layout appears.
   - `/plate --recycle --list` lists the dropped session.
   - `/plate --recycle` re-parents at `info.json::parent_sha_at_save` (NOT current HEAD).
   - `/plate --recycle <session-dir-name>` restores an explicit older session.
5. **Concurrent `/plate` from two repos**: fire `/plate` in two worktrees within ~5 seconds of each other; assert `tmux ls` shows two distinct sessions (`plate-summary-N`, `plate-summary-N+1`), each with its own pane and trailer-rewrite.
6. **Recycle abort on missing parent SHA**: manually delete the parent-branch commit referenced in `info.json`; `/plate --recycle` must error out cleanly without mutating the repo.

## Not implemented (deferred by design)

- **`/plate --show`** — slash-command variant exists but `cli.py::_cmd_show` returns literal `"TODO"`. Design (likely a `git log --graph` over `*-plate` refs, or a tree-of-stacks view) hasn't been written. `render_tree.sh` / `render_tree.py` are kept around in case the design lands.

## Known polish items (small, non-blocking)

- **`plate_drop` stderr leak**: `plate_drop` prints `warning: no plate branch...` to stderr; `2>&1` in `plate.sh` folds it into the user-visible `reason`. Suppress at source or filter in `cli.py`.
- **Stale SHA references in summaries**: the spawned agent reads the plate ref BEFORE the rebase-reword regenerates the tip SHA, so any commit-SHA the agent quotes in the summary text is one rewrite stale (still reachable via reflog, but confusing). Mitigation: tell the agent in `summary-agent.md` to reference files/changes, not SHAs.
- **`rtk` wrapper not used in agent's `next steps:`**: the spawned agent suggests bare `pytest …` rather than project-convention `rtk pytest …`. One-line note in `summary-agent.md`.
- **`convo-summary` template polish**: 5-section template (`what:` / `why:` / `how:` / `open questions:` / `next steps:`) lives in `skills/plate/summary-template.md`. Refinements (length cap, section ordering) are iterate-after-soak.

## Stage 2 dead-code purge (separate commit)

Old stash-ref + JSON-instance code paths still on disk but unreferenced by `/plate`. Hold for clean revertability after live-validation completes:

- `skills/plate/scripts/`: `push.sh`, `done.sh`, `drop.sh`, `next.sh`, `list-paused-plates.sh`, `register-parent.sh`, `snapshot-stash.sh`, `branch-snapshot.sh`, `branch-snapshot.v2.sh` (~10 files)
- `common/scripts/plate/`: `instance_rw.py`, `append_plate_to_stack.py`, `cascade_parent_chain.py`, `check_drift_alert.py`, `check_live_children.py`, `check_rolling_intent_refresh.py`, `clear_drift_alert.py`, `list_paused_plates.py`, `next_resume_point.py`, `print_resume_pointer.py`, `register_parent.py`, `verify_stash_refs.py`, `build_settings_json.py` (~13 files)
- KEEP: `transcript_parse.py` (used by future summary work), `render_tree.sh` / `render_tree.py` (kept around because `--show` design is deferred)
