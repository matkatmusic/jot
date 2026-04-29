# `/plate` test scenarios — branch model

Inventory of red-green test cases for the branch-based `/plate`
implementation. Each scenario is a self-contained git command sequence
with a verifiable post-state.

Validated cases come from live sandbox runs (see
`plate-walkthrough-log-2026-04-28.md`). Untested cases are paper-design
only and need test scripts written.

Suggested layout: `skills/plate/tests/branch-model/test-<command>-<scenario>.sh`.
Each script: fresh `/tmp` repo → setup state → run plate sequence →
assert on `git log`, `git status --porcelain`, branch list, file
contents, patch file contents.

---

## Validated end-to-end (happy path only)

- [x] `/plate` push — **first invocation** creates `<branch>-plate` with one commit
- [x] `/plate` push — **subsequent invocation** extends the chain with another commit
- [x] `/plate` push — **mixed file states** (staged + unstaged + untracked) all captured into one plate commit
- [x] `/plate --done` — **clean case**: implicit pre-push skipped, `git reset --hard` + `git clean -fd`, cherry-pick chain onto `<branch>`, delete `<branch>-plate`, WT clean

## Untested

### `/plate` push

- [ ] Clean WT at push time → no-op with the message `"no changes to stack"`
- [ ] Background `reword` pass replacing the placeholder commit message with the structured DESIGN.md §7.3 message *(blocked on background-agent wiring)*
- [ ] Per-agent file-list staging instead of `git add -A --force` *(blocked on EditFile hook)*

### `/plate --done`

- [ ] Implicit pre-push **fires** when WT tree differs from plate tip tree (only the skip path is currently verified)
- [ ] Cherry-pick conflict (e.g., `<branch>` advanced between push and done) — abort and leave clean state, do not leave a half-applied chain

### `/plate --drop`

- [ ] Pop top plate from a multi-plate chain (rewinds `<branch>-plate` by one commit)
- [ ] Pop top plate when only one plate exists (deletes `<branch>-plate` entirely)
- [ ] `--drop` with no `<branch>-plate` exists (error path)
- [ ] Patch recovery: `git apply <patch>` from clean `<branch>` HEAD recreates the dropped plate's full state
- [ ] Patch correctly captures binary content via `--binary` flag

### `/plate --trash`

- [ ] Trash a multi-plate chain → single combined patch + delete branch
- [ ] WT cleanup mode (a) leave WT alone *(pending decision)*
- [ ] WT cleanup mode (b) `git reset --hard` + `git clean -fd` *(pending decision; only one of a/b will land)*
- [ ] `--trash` with no `<branch>-plate` (error path)

### `/plate --recycle`

- [ ] Replay a trashed stack into a fresh `<branch>-plate` via per-plate patches (Path 2)
- [ ] `--recycle` when `<branch>-plate` already exists (error)
- [ ] `--recycle <timestamp>` selects a specific trash session when multiple stored

### `/plate --carry`

- [ ] Phase A (push current WIP) + Phase B (switch to picked plate branch)
- [ ] `--carry` invoked with clean WT (picker only, no Phase A work to do)
- [ ] Untracked files restored to staged-add status

### `/plate --next`

- [ ] Walks the parent-trailer chain across `<base>-derived*` branches and emits the resume command

### Multi-agent delegation (sequential)

- [ ] New agent in a repo where `<branch>-plate` already exists → creates `<branch>-plate-derived1` with `parent-convo` and `parent-plate` trailers in its first commit
- [ ] Second derived agent at depth 2 → creates `<branch>-plate-derived2` (chained off `derived1`)
- [ ] `derived2 --done` while `derived3` exists → blocked with an explanatory error
- [ ] `derived2 --done` (no further descendants) → cherry-picks onto `derived1`, deletes `derived2`
- [ ] `delegated_to[]` derivation correctness: scan `<base>-derived*` branches and read first-commit trailers

### Cross-cutting

- [ ] `--drop` patch portability: patch generated in repo A applies cleanly in repo B at the same `<branch>` HEAD
- [ ] Reflog recovery: orphaned plate commits remain accessible after `--done` deletes their branch (until git gc)

---

## Total

- 4 validated (happy path)
- 22 untested

Most untested scenarios can be written today against the locked-in
sequences (push, `--done`, `--drop`, `--trash`). A handful are blocked
on upstream design work (background-agent reword, EditFile hook,
multi-agent delegation infrastructure).
