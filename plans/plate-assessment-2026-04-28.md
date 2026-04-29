# `/plate` — assessment vs original intent (2026-04-28)

Source files reviewed: `skills/plate/DESIGN.md`, `skills/plate/SKILL.md`,
`skills/plate/scripts/{push,done,drop,next,snapshot-stash,branch-snapshot,branch-snapshot.v2}.sh`,
`plans/plate-status-2026-04-14.md`.

## TL;DR

The current implementation faithfully ships the **stash-ref / cumulative-tree** model
described in DESIGN.md §3–§7. It does **not** ship the **branch-based** model the
historic conversation pivoted toward — that work sits orphaned as
`branch-snapshot.sh` + `branch-snapshot.v2.sh`, neither wired into `push.sh`.

The user's "I'm on `fix` and want to hop to `feature`" scenario is the exact case
the branch model was conceived for, and the current stash-ref model does not
cleanly handle it. See "Scenario walkthrough" below.

## Coverage matrix (DESIGN.md → code)

| Design item                                | Implemented? | Where                             |
|--------------------------------------------|--------------|-----------------------------------|
| `/plate` push (snapshot + named ref)       | ✅           | `snapshot-stash.sh` + `push.sh`   |
| `/plate --done` (replay as commits)        | ✅           | `done.sh`                         |
| `/plate --drop` (patch + restore)          | ✅           | `drop.sh`                         |
| `/plate --next` (walk parent chain)        | ✅           | `next.sh` + `next_resume_point.py`|
| `/plate --show` (regen tree.md, $EDITOR)   | ✅           | `show.sh`                         |
| 3-way registration gate (paths 1/2/3)      | ✅           | hook + SKILL.md path-3 body       |
| 1:N delegation + cascade on `--done`       | ✅           | `cascade_parent_chain.py`         |
| Background-agent summarization (jot tmux)  | ✅           | `plate-orchestrator.sh` + workers |
| `instances/<convoID>.json` schema          | ✅           | `instance_rw.py`                  |
| Hedging fields + ≥90% self-verify          | ⚠️ partial   | prompt mentions; no enforcement   |
| Drift detection (rolling intent + nudge)   | ⚠️ partial   | `check_drift_alert.py` exists     |
| Cancel/resubmit dedup (parentUuid rule)    | ⚠️ unclear   | `transcript_parse.py` — verify    |
| `tree.md` render + `--show` flow           | ✅           | `render-tree.sh` + `render_tree.py` |
| Untracked-file capture on `/plate` push    | ❌ broken    | `snapshot-stash.sh` skips `-u`    |
| Branch-aware push/done                     | ❌ missing   | no branch model in `push.sh`/`done.sh` |
| `hooks/hooks.json`                         | ❌ missing   | flagged in status doc             |
| `dev-marketplace/.claude-plugin/marketplace.json` | ❌ missing | flagged in status doc            |

## What's *missing* relative to the user's mental model

1. **Working-tree is not cleaned by `/plate` push.** `snapshot-stash.sh` runs
   `git stash create` (no `-u`, no apply, no reset). The dirty working tree is
   left in place. The "set down the plate, hands empty" metaphor in DESIGN.md §2
   is not realized in code — the snapshot is captured, but the user's hands are
   still full.

2. **No branch awareness.** Plates record `branch` per §5, but `done.sh` commits
   to whatever branch is currently checked out at `--done` time (`git
   symbolic-ref --short HEAD`). If the user pushed plates on `fix` then ran
   `--done` while on `feature`, the replay would land on `feature`. There is no
   guard.

3. **Branch-based plate model orphaned.** `branch-snapshot.v2.sh` builds
   `<branch>-plate` chained commits via temp-index + `commit-tree`, which is
   the only path that survives a `git checkout` to an unrelated branch. It is
   not called by anything.

4. **Untracked files never captured on push.** `snapshot-stash.sh` does not pass
   `-u` to `git stash create`. (Note: `git stash create -u` is itself buggy per
   the v2 file's comment block — that's why v2 uses temp-index.) Either way,
   untracked files added between plates vanish from `--done` replay.

5. **`hooks/hooks.json` missing on disk.** Hook dispatch may be broken; status
   doc flagged this. Needs verification.

## ASCII walkthroughs (current stash-ref implementation)

Each diagram tracks **three independent state spaces**, kept in separate
columns so they don't run into each other:

  • Git refs/commits — what `git log --all` would show
  • Plate JSON — what's in `.plate/instances/<convoID>.json`
  • Working tree — clean (matches HEAD) or dirty (uncommitted edits)

Notation: `S1`, `S2` are stash-commit SHAs created by `git stash create`.
They are dangling commits kept alive by `refs/plates/<convoID>/<plate-id>`.
They are NOT on any branch — they sit off to the side.

### Initial state for `--done` and `--drop` walkthroughs

The user has run `/plate` twice on `fix`, accumulating two snapshots, then
made further edits without committing.

```
GIT                       PLATE JSON                       WORKING TREE
───                       ──────────                       ────────────
main:  A---B---C          stack:                           DIRTY
            \             [                                (edits made
fix:         F1 ←HEAD       { plate_id: P1,                 after S2 was
                              stash_sha: S1,                captured)
S1 (dangling)                 push_time_head_sha: F1 },
S2 (dangling)               { plate_id: P2,
                              stash_sha: S2,
refs:                         push_time_head_sha: F1 },
  refs/plates/<c>/P1 → S1  ]
  refs/plates/<c>/P2 → S2  completed: []
```

### `/plate --done`

`done.sh` walks the stack oldest-first, applies each plate's diff onto HEAD
as a real commit, then makes one final commit if the working tree still
differs from the last snapshot.

```
GIT                       PLATE JSON                       WORKING TREE
───                       ──────────                       ────────────
main:  A---B---C          stack: []                        CLEAN
            \             completed:                       (matches HEAD)
fix:         F1            [
              \              { plate_id: P1,
               C1            commit_sha: C1,
                \            completed_at: ... },
                 C2          { plate_id: P2,
                  \          commit_sha: C2,
                   C3 ←HEAD  completed_at: ... },
                          ]
refs:
  refs/plates/<c>/* DELETED
```

Where each new commit comes from:
  • C1 ← `git apply` of `diff(F1 .. S1)` on top of F1     (plate P1 replayed)
  • C2 ← `git apply` of `diff(S1 .. S2)` on top of C1     (plate P2 replayed)
  • C3 ← `git add -A && git commit` of remaining diff     (post-S2 WT changes)

⚠ GOTCHA: `done.sh` uses `git symbolic-ref --short HEAD` to determine which
branch to commit on. If you ran `--done` while checked out on `feature`
instead of `fix`, C1/C2/C3 would land on `feature`. Plate's per-plate
`branch` field is recorded but not enforced.

### `/plate --drop` (drops top plate, P2)

`drop.sh` saves the WT-vs-top-plate delta as a patch file outside git,
restores the working tree to the top plate's snapshot, then pops the plate.

```
GIT                       PLATE JSON                       WORKING TREE
───                       ──────────                       ────────────
main:  A---B---C          stack:                           = S2's tree
            \             [ { plate_id: P1, ... } ]        (P1 is now top;
fix:         F1 ←HEAD     completed: []                     post-S2 edits
                                                            are gone from
S1 (dangling, kept)       FILESYSTEM                        WT, but saved
                          ──────────                        in patch file)
refs:                     .plate/dropped/<c>/P2_<ts>.patch
  refs/plates/<c>/P1 → S1   = diff(S2 → pre-drop WT)
  refs/plates/<c>/P2 DELETED
```

Recover the dropped work later with `git apply <patch-file>`.

⚠ Untracked files that existed before `--drop` are captured in the patch
BUT remain on disk after `git checkout S2 -- .` (because checkout doesn't
delete untracked files). Reapplying the patch is then a no-op for them.

### `/plate --next`

Read-only. Walks `parent_ref` upward across instance JSONs to find the
nearest ancestor with a paused (un-`--done`'d) plate. No state changes —
prints a resume command to stdout.

```
INSTANCE TREE (read from .plate/instances/*.json)

  Instance A  (parent: none)
  └─ stack: [ "task 3" → state=delegated, delegated_to=[C] ]
      │
      └─ Instance C  (parent: A/task-3)        ← ▶ RESUME HERE
         └─ stack: [ "subtask 1" → state=paused ]
             │
             └─ Instance D  (parent: C/subtask-1)   ← current instance,
                                                       just ran --done

OUTPUT (printed to stdout)
  cd <cwd from C's instance JSON> && claude --resume <C convoID>
```

## Scenario walkthrough — "on `fix` dirty, want to peek at `feature`"

Initial:

```
main:    A---B---C
              \   \
fix:           F1            (HEAD; working tree DIRTY: idea-for-fix unsaved)
                  \
feature:           Ft1---Ft2
```

User wants to: hop to `feature`, investigate something, come back to `fix`
without losing (a) the dirty WT on `fix` and (b) any new idea sparked while
on `feature`.

### Path A — using `/plate` as currently implemented

```
1. On fix, run /plate
   → snapshot-stash.sh: STASH_SHA = git stash create
   → refs/plates/<conv>/P1 = STASH_SHA
   → instance.stack = [P1]
   → working tree STILL DIRTY  ← problem

2. git checkout feature
   → BLOCKED: "Your local changes to the following files would be overwritten"
   → user must `git stash` (real) or `git reset --hard` to proceed
   → if they `git stash`, that stash is OUTSIDE plate's tracking
   → if they `git reset --hard`, dW is gone unless plate's STASH_SHA captured
     it (it did capture tracked edits; untracked files are LOST because no -u)
```

The current implementation does not solve the scenario. `/plate` records the
state but does not free the working tree.

### Path B — what the orphaned branch model would give you

```
1. On fix, run /plate (hypothetical, using branch-snapshot.v2.sh)
   → builds tree T from temp-index (tracked + staged + untracked)
   → commit-tree T -p HEAD → C_plate
   → refs/heads/fix-plate = C_plate
   → git reset --hard HEAD     ← clean working tree
   → state:
       fix:        F1
       fix-plate:  F1---C_plate    (HEAD optionally moved here, or stays on fix)
       working tree: clean

2. git checkout feature                                       ← no longer blocked
   → state on feature, clean WT, scratch around freely

3. If you spark a new idea for feature, run /plate again:
   → branch-snapshot builds C_feature_plate from current WT
   → refs/heads/feature-plate = Ft2---C_feature_plate

4. git checkout fix-plate                                     ← back to fix WIP
   → working tree restored to exactly what you set down
   → continue editing
```

This is the workflow your historic 3-step test validated, where stash-pop
fails (because `git stash apply` after a checkout to an unrelated branch
either conflicts or corrupts) but `commit-tree`-based plate branches survive
intact.

### Path C — bridge using current tooling only (workaround)

If you stay on the current implementation today, the cleanest workaround is:

```
1. /plate            (records state, but WT still dirty)
2. git stash push -u (real stash, frees WT — but now plate AND stash refer to
                     overlapping but distinct snapshots; merge confusion at
                     --done time)
3. git checkout feature
4. ...investigate...
5. git checkout fix
6. git stash pop
7. /plate --done     (commits per plate; the real-stash pop work is captured
                     in the "final" commit since it differs from S1)
```

This works but is fragile: it relies on the user remembering the manual
`stash push -u` / `pop` and assumes no conflicts on pop. It also doesn't help
with the "new idea on feature" half — that idea has no plate home, since
plates are scoped to the active instance's stack and you'd be on a side
errand, not a delegated child.

## Open design questions to resolve

1. **Should `/plate` push clean the working tree?** (Foundational — everything
   else hinges on this.)
2. **If yes, by which mechanism?** (a) `git reset --hard` after `stash create`
   (matches current model but loses untracked files); (b) ship the branch
   model from `branch-snapshot.v2.sh` and `git reset --hard` to the parent
   commit; (c) something else.
3. **Should `done.sh` enforce "replay on the originating branch"?** Right now
   it commits wherever HEAD is.
4. **Branch model: adopt v2, write v3 (codex+gemini synthesis), or delete the
   orphans?**
5. **Cross-branch idea capture:** is the "new idea sparked while on feature"
   a plate on `feature`'s implicit instance, a sibling stack, or out of scope
   for plate entirely?
