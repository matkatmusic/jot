# `/plate` live walkthrough log — 2026-04-28

Sandbox: `~/Programming/jot/plate-test/` (submodule, source at `~/Programming/plate-test/`).
Driven via tmux session `plate-test-0`.

## Initial topology

```
* Ft2 (feature)
* Ft1
* C  (main)
| * F1 (fix)
|/
* B
* A
```

Sandbox checked out on `fix` at F1 (`04e3932`). WT clean.

---

## Steps taken

### Step 1 — user edits `a.txt` on `fix`
Modified `a.txt` ("A" → "A dirty"), did not stage.
WT: `a.txt` modified (unstaged).

### Step 2 — user creates `scratch.txt` on `fix`
Wrote `scratch.txt` ("scratch note"), did not add.
WT: `a.txt` modified + `scratch.txt` untracked.

### Step 3 — first attempt: temp-index plumbing (exploratory)
Ran temp-index + `commit-tree` + `update-ref`. Worked but used
`git reset --hard HEAD` afterward which left `scratch.txt` untracked
in WT. Fix-plate at `32b2e21`. **Rejected** in favor of porcelain.

### Step 4 — second attempt: porcelain 6-step (locked in, then rolled back)
Ran:
```bash
git branch fix-plate
git checkout fix-plate
git add -A
git commit -m "plate: WIP on fix"
git checkout fix
git restore --source=fix-plate --worktree .
```
Fix-plate at `5e8558a`. WT preserved (a.txt modified-unstaged, scratch.txt
untracked). **Worked for first push, but rolled back** — see Step 5.

### Step 5 — user edits `fix.txt` on `fix` (further in-hand work)
Added 3 lines to `fix.txt`. WT now: `a.txt` mod (same as on fix-plate),
`fix.txt` mod (NEW), `scratch.txt` untracked.

### Step 6 — subsequent `/plate` push: porcelain hits a wall
Tried to extend the porcelain 6-step to subsequent pushes by replacing
step 2 with `git checkout -m fix-plate` (3-way merge-checkout). Identified
structurally that this introduces unavoidable conflicts when fix and
fix-plate diverge for the same files: the merge has no way to tell which
of (HEAD, target, WT) is "the truth" since WT *already contains* the
diffs that distinguish fix-plate from fix. **This is where the historic
branch-plate work stopped.**

### Step 7 — canonical `/plate` push sequence (locked in)

Plumbing, uniform for first AND subsequent pushes. No merging, no checkouts,
no conflicts possible.

```bash
TMP_INDEX=$(mktemp -t plate-index)
GIT_INDEX_FILE="$TMP_INDEX" git read-tree HEAD
GIT_INDEX_FILE="$TMP_INDEX" git add -A --force
TREE=$(GIT_INDEX_FILE="$TMP_INDEX" git write-tree)
if git show-ref --verify --quiet refs/heads/<branch>-plate; then
  PARENT=$(git rev-parse <branch>-plate)
else
  PARENT=$(git rev-parse HEAD)
fi
NEW=$(git commit-tree "$TREE" -p "$PARENT" -m "plate: WIP on <branch>")
git update-ref refs/heads/<branch>-plate "$NEW"
rm -f "$TMP_INDEX"
```

Properties:
- HEAD never moves
- Real index never touched
- WT never touched (so the "preserve dirty WT visibly" semantic is
  automatic — no checkout dance, no restore step)
- New commit's TREE = current WT (fix HEAD + WT changes, ignoring
  fix-plate's prior tree → matches the user's "fix overwrites fix-plate"
  semantic)
- New commit's PARENT = fix-plate tip if branch exists, else fix HEAD
  → discrete chain on fix-plate

**Status: live-tested in the sandbox** (subsequent push case). fix-plate
advanced `5e8558a` → `cf16e5c`, parent linkage correct. Diff vs parent =
only `fix.txt` (+3 lines), the new delta since the previous plate.
HEAD still on fix at F1. WT untouched (a.txt mod, fix.txt mod,
scratch.txt untracked).

Final topology after Step 7:
```
* cf16e5c (fix-plate) plate: WIP on fix    ← P2
* 5e8558a             plate: WIP on fix    ← P1
* 04e3932 (HEAD → fix) F1
```

### Step 8 — third `/plate` push (varied edits including a staged file)
WT prepared with: `a.txt` modified, `fix.txt` modified, `scratch.txt`
untracked, `scratch2.txt` staged-new. Ran the same canonical plumbing
sequence from Step 7. fix-plate advanced `cf16e5c` → `fe30366`. Diff
vs parent = the 3 deltas since previous plate. Confirmed: plumbing
handles mixed staged/unstaged/untracked content with no special cases.

### Step 9 — canonical `/plate --done` sequence (locked in)

Cherry-pick + implicit pre-push. Aligns with DESIGN.md §7.3 (one
commit per plate, applied sequentially; final commit captures
post-last-plate work; plate refs deleted).

```bash
BRANCH=$(git symbolic-ref --short HEAD)
PLATE="${BRANCH}-plate"

# Step 0 — implicit pre-push (only commits if WT differs from plate tip,
# to avoid empty commits). Maintains the invariant: every byte in WT
# is also captured on $PLATE before destructive ops below.
TMP_INDEX=$(mktemp -t plate-index)
GIT_INDEX_FILE="$TMP_INDEX" git read-tree HEAD
GIT_INDEX_FILE="$TMP_INDEX" git add -A --force
TREE=$(GIT_INDEX_FILE="$TMP_INDEX" git write-tree)
PLATE_TIP_TREE=$(git rev-parse "${PLATE}^{tree}")
if [ "$TREE" != "$PLATE_TIP_TREE" ]
then
  PARENT=$(git rev-parse "$PLATE")
  NEW=$(git commit-tree "$TREE" -p "$PARENT" \
          -m "plate: pre-done capture for ${BRANCH}")
  git update-ref "refs/heads/${PLATE}" "$NEW"
fi
rm -f "$TMP_INDEX"

# Step 1 — clean WT. Safe: invariant guarantees data is on $PLATE.
git reset --hard
git clean -fd

# Step 2 — apply each plate as a new commit on $BRANCH (oldest-first).
git cherry-pick "HEAD..${PLATE}"

# Step 3 — delete plate branch. -D required: cherry-picked SHAs differ
# from originals so $PLATE isn't reachable from $BRANCH (would block -d).
git branch -D "${PLATE}"
```

**Status: live-tested in the sandbox.** fix advanced from F1 to a
3-commit chain `abbe6da → c0d1964 → 70c52ed` (new SHAs from
cherry-pick). fix-plate deleted. WT clean. Step 0 correctly skipped
(WT matched plate tip exactly — no empty commit produced).

Final topology after Step 9:
```
* 70c52ed (HEAD → fix) plate: WIP on fix    ← P3' (cherry-picked)
* c0d1964              plate: WIP on fix    ← P2' (cherry-picked)
* abbe6da              plate: WIP on fix    ← P1' (cherry-picked)
* 04e3932 (origin/fix) F1
```

**Key insight on "nothing gets lost":** the rule is system-level, not
command-level. `git reset --hard` and `git clean -fd` are locally
destructive but globally non-destructive *because the invariant from
Step 0 guarantees the data lives on `$PLATE`*. If Step 0 ever fails
or is skipped incorrectly, those local destructions become real data
loss — so the conditional in Step 0 must be conservative (only skip
when WT tree EXACTLY matches plate tip tree).

---

## Open decisions / edge cases

Items surfaced during the walkthrough that still need a decision.
Grouped by which command's design exposed each one.

- **`/plate` push** (Step 7 sequence locked in)
  - [x] Empty-WIP behavior: when WT is clean at push time, no-op with the message **"no changes to stack"**
  - [x] Commit message structure: initial commit lands with the placeholder `plate: WIP on <branch>` (keeps `/plate` foreground response fast), then a **background tmux agent uses `git rebase -i` with `reword`** to replace it with the structured DESIGN.md §7.3 message (`[plate] <action>` + Goal/Hypothesis/Errors/plate-id body) once the agent has generated it

- **`/plate --done`** (Step 9 sequence locked in)
  - [ ] JSON metadata layer: `.plate/instances/<convoID>.json` `stack[]` → `completed[]` bookkeeping per DESIGN.md §6 / §7.3 step 5
  - [x] Per-plate structured commit messages: filled in by the background-agent `reword` pass at push time (see `/plate` push item above), so by the time `--done` cherry-picks, each plate already carries its full structured message
  - [ ] Cascade through parent-chain delegation (DESIGN.md §9) — out of scope for current walkthrough

- **`/plate --drop`**
  - [ ] Patch base: `<branch>` HEAD (cumulative, portable, recommended) vs top-plate-parent (delta only, only valid from previous plate's tree state)
  - [ ] WT semantic divergence from DESIGN.md §7.4: original spec restores WT to top-plate-tree (abandon post-plate experimentation); user's new semantic leaves WT untouched (abandon plate metadata only) — confirm new direction
  - [ ] Patch path: full `.plate/dropped/<convoID>/<plate-id>_<ts>.patch` (DESIGN.md §3) vs sandbox-simple `.plate/dropped/<branch>-plate_<ts>.patch`
  - [ ] Single-plate-remaining edge case: `git branch -D <branch>-plate` (recommended) vs rewind ref to where `<branch>` HEAD already is (functionally a no-op)

- **`/plate --trash`**
  - [ ] WT cleanup: (a) leave WT alone — matches `--drop` pattern, but creates redundancy between WT and patch contents; (b) `git reset --hard` + `git clean -fd` — clean end state, but destructive of any post-last-plate WT edits not in the patch
  - [ ] Patch granularity: single combined patch vs per-plate patches (decision linked to `--recycle` choice below)

- **`/plate --recycle`** (proposed; not yet formally adopted)
  - [ ] Adopt at all? (Symmetric to `--trash` — restore deleted plates from saved patches.)
  - [ ] Path 1 (single recovered plate from a combined patch — loses commit boundaries) vs Path 2 (per-plate replay; recommended; preserves chain shape)
  - [ ] Behavior when multiple trash sessions are stored: default to most recent vs require explicit timestamp argument
  - [ ] Naming: `--recycle` (consistent with the dish metaphor: set down → drop / trash → recycle / wash) vs `--restore` / `--untrash`

- **`/plate --carry`** (proposed earlier; not walked through yet)
  - [ ] After Phase B (pick a plate to resume), is the consumed plate branch deleted? Recommended: yes
  - [ ] `--carry` invoked with clean WT (no current work to set down): show picker only vs error
  - [ ] Untracked files restored via `--carry`: appear as staged-add (recommended) vs untracked-again

- **`/plate --next`** (read-only chain walk; nothing pending)

- **Multi-agent delegation** (sequential first; parallel deferred)
  - [x] Branch naming: child agent's plate branch is `<base>-derivedN`, where N increases with chain depth (`derived1` is built off `<branch>-plate`'s tip, `derived2` is built off `derived1`, etc.). Strictly linear chain — no flat sibling numbering.
  - [x] Match-detection trigger: when an agent's `/plate` runs and a `<branch>-plate` (or any `<base>-derivedN`) already exists, treat self as a derived agent regardless of WT tree state. The mere existence of the parent branch is the signal.
  - [x] `delegated_to` storage: NOT amended into parent commit. The derived agent's first commit carries `parent-convo: <id>` and `parent-plate: <SHA>` trailers. The inverse view (parent's `delegated_to[]`) is computed on demand by scanning `<base>-derived*` branches and reading their first-commit trailers. No cross-branch amends. No timing dependency.
  - [x] `--done` rule: a derived agent's `--done` cherry-picks its plate-branch commits onto its **immediate parent plate branch** (not onto `<branch>` directly). E.g., `derived2 --done` → cherry-pick onto `derived1`, then delete `derived2`. **Block `--done`** if any `derivedN+1` exists — the chain must collapse depth-first.
  - [x] Parallel siblings (multiple agents spawning from the same parent simultaneously): **deferred**. The structural blocker is shared WT — `git add -A` in `/plate` push would capture both agents' edits. Will revisit once the per-agent change-attribution layer is in place.

- **Per-agent change attribution** (replaces `git add -A` in `/plate` push)
  - [ ] Implement an EditFile/Write/Bash hook that records every file the agent has touched in this session (per-agent file log).
  - [ ] Revise the locked-in `/plate` push (Step 7) to stage only the per-agent file list instead of `git add -A --force`. This makes the canonical push correct under both sequential and parallel multi-agent scenarios.
  - [ ] Edge case: user pastes a command that modifies files outside the agent's tool calls (e.g., a manual `make` or `npm install`). Those files won't be in the per-agent log. Decide whether to capture them anyway, or treat them as "shared WT pollution" the user has to manage explicitly.

- **Cross-cutting**
  - [ ] Finalize `.plate/` directory layout for the branch model (`instances/`, `dropped/`, `trashed/`, etc.) — DESIGN.md §3 covers the stash-ref model only
  - [ ] How `<convoID>` is determined in production (Claude session ID? convo-file path? we've been using a static `<branch>-plate` shape in the sandbox)
  - [ ] Patch portability: encode the base SHA in the patch filename or comment so `git apply` knows where it should land
  - [ ] Auto-`/plate` push on `SessionExit` hook (filed in `plate-todos.md`)
  - [ ] DESIGN.md §11 drift detection — out of scope for git-mechanics walkthrough but pending overall
