# R2 — Claude: Cross-Critique

## Convergence map

| Claim | Claude R1 | Gemini R1 | Codex R1 |
|---|---|---|---|
| Plan diagnosis is directionally correct | ✅ | ✅ | ✅ |
| Bug B (literal `/` in Bash rules) fix is right | ✅ | ✅ | ✅ |
| `release-claim.sh` helper supersedes inline `rm` | ✅ (keep both) | ✅ (keep both) | ✅ (**drop** rm rule entirely) |
| Step-8 instruction text must be written | ✅ snippet | ✅ snippet | ✅ snippet |
| `permissions-expand-test.sh` body must be written | ✅ snippet | ✅ snippet | ✅ snippet |
| `release-claim-test.sh` body must be written | ✅ snippet | ✅ snippet | ✅ implied |
| Migration: shim must inject `Read` rules so v1.1.0 installs get the fix | ✅ load-bearing | ✅ noted | ❌ **missed** |
| Bug A blast radius is *partial* (shim already covers Write/Edit) | ✅ | ❌ treats as full | ❌ treats as full |
| `v1.1.1` already tagged/published — must ship as `v1.1.2` | ❌ **missed** | ❌ **missed** | ✅ **caught** |
| Permissions test must whitelist `~/.claude/projects/**` (not blanket `//`) | ❌ over-broad | ❌ over-broad | ✅ **caught** |

## Concessions to Codex

### 1. Version number — concede fully
I missed it; Gemini missed it. Codex is right: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, and local tag `v1.1.1` already point at `b3bd67e`, a metadata-only bump. Shipping the runtime fixes under that same `v1.1.1` would silently retag a public version. **Correct action: ship as `v1.1.2`** unless the user can confirm `v1.1.1` was never published. My CHANGELOG snippet (R1 §7) and Gemini's both used the wrong header — both must be relabeled `## [1.1.2] — 2026-04-24`.

### 2. Permission-expansion test assertion — concede fully
My R1 §3 test sketch and Gemini's both encoded the plan's faulty rule "every `Read(/Write(/Edit(` body starts with `//` or `~/`." Codex correctly notes that the project ships `Read(~/.claude/projects/**)` as a home-anchored rule that the worker uses for cross-project transcript reads; a blanket `//`-or-`~/` assertion accidentally permits future regressions where a `${REPO_ROOT}/` rule degrades to `~/REPO_ROOT/`. **Codex's needle-list assertion is the correct shape** — assert each expected rule by exact string, plus an unexpanded-`${IDENT}` guard. My R1 test should be replaced with Codex's body verbatim.

### 3. `release-claim.sh` hardening — concede partially
My R1 helper validated `NNN` only. Codex additionally validates that `REPO_ROOT` is absolute and that the resolved `TARGET` matches `$STATE_DIR/id-[0-9][0-9][0-9].claim` exactly. That second check is what stops a future `release-claim.sh /etc 999` (or symlink-injection in `Todos/.todo-state/`) from turning the helper into a general `rm` primitive. **Adopt Codex's body** — the cost is six lines and the property is `helper cannot delete anything outside the sentinel directory`.

## Where Codex is wrong (or incomplete)

### A. Codex misses the migration-path defect — this is the load-bearing R1 finding
Codex's "recommended corrected plan" assumes that fixing `permissions.default.json` reaches users on next install. **It does not.** `common/scripts/permissions-seed.sh` implements three-state install logic: any user who already ran v1.1.0 has `${CLAUDE_PLUGIN_DATA}/todo-permissions.local.json` classified as `modified-by-user` (because v1.1.0 wrote it under that label), and v1.1.2 will *not* overwrite it. Without extending `expand_permissions.py` to inject the four absolute-path Read/Write/Edit rules at runtime — exactly the shim mechanism that already exists for `Write(//…/Todos/**)` and `Edit(//…/Todos/**)` — every v1.1.0 → v1.1.2 upgrader sees zero runtime change.

This is the single most expensive defect in the plan. Codex's "recompute sha256, bump version, ship" sequence is necessary but not sufficient; **without the shim extension, v1.1.2 is a cosmetic release.** I hold my R1 §2 position and add: Gemini independently arrived at the same conclusion ("must ensure the `expand_permissions.py` shim also covers these rules to support existing installs"), so this is two-of-three and load-bearing.

### B. Codex's "drop the inline `rm` rule entirely" is right *if* §A is fixed
Codex is correct that the inline `Bash(rm -f /${REPO_ROOT}/Todos/.todo-state/id-*.claim:*)` is brittle (wildcard inside a permission string). But the proposed `Bash(bash /${REPO_ROOT}/skills/todo/scripts/release-claim.sh:*)` rule still must reach existing installs — so the shim's required-rules list must include the new helper invocation, not just the path-anchor rules. My R1 §2 shim snippet should be augmented:

```python
required = [
    "Read(//${REPO_ROOT}/Todos/**)",
    "Write(//${REPO_ROOT}/Todos/**)",
    "Edit(//${REPO_ROOT}/Todos/**)",
    "Read(//${REPO_ROOT}/.claude/plans/**)",
    "Bash(bash /${REPO_ROOT}/skills/todo/scripts/scan-existing-todos.sh:*)",
    "Bash(bash /${REPO_ROOT}/skills/todo/scripts/release-claim.sh:*)",
]
```

(Note the `/` vs `//` distinction: path-anchor rules use `//`; `Bash(bash …)` rules use a literal single `/` because `lstrip("/")` strips one slash and the worker invokes `bash /…`.)

## Where Gemini is wrong (or weak)

### C. Gemini's test scope inherits the plan's flaw
Gemini's `permissions-expand-test.sh` uses `grep -qF '"Read(//Users/test/project/Todos/**)"'` — that specific assertion is fine, but Gemini does not assert *absence* of unexpanded `${IDENT}` placeholders, and does not assert that the `Bash()` rules contain a literal leading `/`. A regression that re-broke Bug B would pass Gemini's test. Codex's body covers both gaps; adopt Codex's.

### D. Gemini's Bug A correction text is too soft on the migration risk
Gemini says "must ensure the `expand_permissions.py` shim also covers these rules to support existing installs" but does not provide the shim diff. Without the diff, the recommendation is ignorable. I provided the diff in my R1 §2; Codex provided none. **The merged plan needs my diff.**

## New considerations raised by reading R1s together

### E. The "drop inline `rm` rule" decision interacts with §A
If we drop the inline rule (Codex's preference, which I concede is cleaner) **and** we extend the shim (my preference, which Codex didn't address), then the shim must inject the new helper-Bash rule too. That's why the augmented `required` list in §B above includes `Bash(bash /${REPO_ROOT}/skills/todo/scripts/release-claim.sh:*)`. Neither R1 alone covers this composition.

### F. The CHANGELOG entry must explain user-visible behavior, not just file changes
My R1 CHANGELOG draft listed bug fixes by category but used the wrong version header. Corrected:

```markdown
## [1.1.2] — 2026-04-24

### Fixed
- Worker permissions: `Read(/Write(/Edit(` rules in
  `permissions.default.json` now use `//${REPO_ROOT}/...` so they expand to
  filesystem-absolute paths. `Bash()` rules now contain a literal `/` before
  `${REPO_ROOT}`. Without these the worker silently denied every
  `Todos/` and `.claude/plans/` access.
- New `skills/todo/scripts/release-claim.sh` replaces the brittle inline
  `rm` permission rule for sentinel cleanup.

### Migration
- v1.1.0 installs whose `${CLAUDE_PLUGIN_DATA}/todo-permissions.local.json`
  was classified `modified-by-user` would not have received the bundled-default
  fix. v1.1.2's `expand_permissions.py` shim now injects the four
  absolute-path Read/Write/Edit rules and the two Bash helper rules at
  runtime, so existing installs receive the fix transparently and need
  no manual action.

### Note
- v1.1.1 was a metadata-only bump (commit b3bd67e). v1.1.2 is the first
  release containing the runtime permission fixes.
```

That last "Note" line discharges Codex's stale-tag concern publicly.

## Final position

**Approve a merged plan that combines:**
1. Codex's release-versioning correction (`v1.1.2`, both metadata files).
2. Codex's needle-list test body for `permissions-expand-test.sh` (replaces the over-broad `//` assertion in my R1 and Gemini's R1).
3. Codex's hardened `release-claim.sh` (REPO_ROOT-absolute + target-path whitelist).
4. **My R1 §2 shim-extension diff, augmented per §B above** to also inject the two `Bash(bash /${REPO_ROOT}/...)` helper rules. This is the load-bearing addition Codex missed.
5. My R1 §3 step-8 instruction wording.
6. My R1 §4 sha256 sidecar command.
7. The corrected CHANGELOG entry above.

Codex is the strongest R1 on shipping mechanics (versioning, test precision, helper hardening). My R1 is the strongest on upgrade-path runtime correctness (the shim extension). Gemini's R1 corroborates the migration concern but contributes no novel snippet. **None of the three R1s alone produces a correct v1.1.2; the merge does.**
