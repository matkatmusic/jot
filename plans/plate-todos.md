# `/plate` — future work / TODOs

Living list of design ideas and follow-up work surfaced during walkthroughs
but not part of any current locked-in sequence.

## Open items

- **Auto-`/plate` on `SessionExit` hook.** When a Claude session ends and
  the WT has uncommitted file changes (tracked mods OR untracked files),
  fire an implicit `/plate` push so the in-flight context isn't lost.
  Same "nothing gets lost" invariant we established for `/plate --done`,
  but applied at session-exit boundaries. Mechanic: a `SessionExit` hook
  runs the canonical plumbing push (locked in 2026-04-28, see
  `plate-walkthrough-log-2026-04-28.md` Step 7) against the current
  branch's plate ref. Skip-if-clean check should match the one we use in
  `--done`'s pre-push (only commit if WT tree differs from plate tip
  tree, to avoid empty commits). Filed 2026-04-28.
