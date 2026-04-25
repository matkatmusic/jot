# Synthesis — Plan Audit: `mighty-exploring-kitten.md`

## 1. Topic
Whether the plan to fix `/todo` worker runtime permission failures is correct, complete, and safe to execute as written.

## 2. Agreement

All three agents converge on the technical core:

- **Bug A (path anchoring)**: `permissions.default.json` rules use `${REPO_ROOT}/...`, which `expand_permissions.py:28` strips to `Users/.../Todos/**` (cwd-relative) instead of `//Users/.../Todos/**` (filesystem-absolute). Fix: prepend `//` to repo-root rules.
- **Bug B (Bash leading slash)**: `Bash(bash ${REPO_ROOT}/...)` expands without the literal `/` the worker actually invokes. Fix: write `Bash(bash /${REPO_ROOT}/...)`.
- **Bug C (`rm` rule)**: brittle wildcard inside a permission string; replace with a dedicated `release-claim.sh` helper.
- **Plan gaps**: missing concrete bodies for `permissions-expand-test.sh`, `release-claim-test.sh`, and the `todo-instructions.md` step-8 rewrite.
- **Verdict shape**: all three issue *Approve with mandatory revisions*.

## 3. Disagreement

### 3a. Migration path defect — does fixing the bundled file reach existing users?
- **Claude (R1, R2)**: Existing v1.1.0 installs have `todo-permissions.local.json` classified `modified-by-user`; `permissions-seed.sh` will not overwrite. Without extending the `expand_permissions.py` shim to inject the missing `Read` rules at runtime, the bundled fix has zero effect on the affected user base. Strongest argument: the shim already exists for `Write`/`Edit` — extending it is six lines and load-bearing.
- **Codex (R2)**: Reads `permissions-seed.sh:20-25,60-64` and `todo-launcher.sh:100-105`; simulates upgrade locally. For *untouched* installs (where installed sha == prior sha), the file IS overwritten on upgrade. Strongest argument: empirical simulation contradicts Claude's "every upgrader is broken" framing — only user-edited installs need the shim hardening.
- **Gemini**: Sided with Claude in R1; refined in R2 to "real failure restricted to `Read` operations" (echoing Claude's R1 §1) and recommends shim extension regardless.

### 3b. Versioning collision
- **Codex (R1, R2)**: `plugin.json`, `marketplace.json`, and tag `v1.1.1` already exist at commit `b3bd67e` (metadata-only bump). Plan's "bump 1.1.0 → 1.1.1" is stale. R2 softens: must preflight whether `v1.1.1` was actually pushed/published before deciding `1.1.1` reuse vs. `1.1.2`.
- **Claude, Gemini**: Both missed it in R1; both conceded fully in R2.

### 3c. Bug A blast radius
- **Claude (R1)**: Partial — shim already injects `Write(//...)` and `Edit(//...)`. Only `Read` rules and the Bash rule are broken at runtime today.
- **Codex, Gemini (R1)**: Treated as full Read/Write/Edit denial. Both conceded in R2 after Claude pointed to `expand_permissions.py:41-49`.

### 3d. Test assertion shape
- **Codex**: Plan's "every `Read(` starts with `//`" assertion is wrong — `Read(~/.claude/projects/**)` is intentionally home-anchored. Use a needle-list assertion against expected exact strings plus an unexpanded-`${IDENT}` guard.
- **Claude, Gemini (R1)**: Both wrote over-broad assertions; both conceded in R2.

## 4. Strongest Arguments

- **Codex** — Versioning collision (§3b): `git show --stat v1.1.1` is decisive evidence the release section is unsafe to execute verbatim.
- **Codex** — Test precision (§3d): the home-anchored counterexample (`Read(~/.claude/projects/**)`) is concrete and would cause the plan's test to false-positive.
- **Claude** — Bug A scope narrowing (§3c): the existing shim diff at `expand_permissions.py:41-49` is on disk and contradicts the plan's "every Read/Write/Edit denied" framing.
- **Claude** — Migration shim diff (§3a): provides exact six-line code to extend coverage, the only argument that produces an actionable change rather than a release note.

## 5. Weaknesses (challenged in R2)

- **Claude R1's "every upgrader is broken"** — overstated. Codex's empirical seed-script simulation proves untouched installs DO receive the bundled fix on upgrade. The shim extension is justified for user-edited installs only, not as the universal upgrade path.
- **Codex R1's "every Read/Write/Edit denied"** — overstated. The Write/Edit shim already exists; only `Read` rules and the broken `Bash(...)` rule have live runtime exposure.
- **Codex R1's "release as v1.1.2" stated as certainty** — Codex self-corrects in R2: the precise action is *preflight whether v1.1.1 is published*, then decide.
- **Claude R1 + Gemini R1 test assertion** — both encoded the plan's over-broad rule and would silently allow regressions that degrade `${REPO_ROOT}` to `~/REPO_ROOT/`.
- **Gemini R1 overall** — corroborates but contributes no novel snippet; weaker than the other two on independent validation.

## 6. Path Forward

Execute a merged plan combining the strongest contributions from each agent:

1. **Bundled defaults** (`skills/todo/scripts/assets/permissions.default.json`): use `//` for repo-root path rules; literal `/` in `Bash(bash /${REPO_ROOT}/...)`; drop the inline `rm` rule entirely (Codex).
2. **Helper script** (`skills/todo/scripts/release-claim.sh`): three-digit `NNN` regex guard, `set -euo pipefail`. **Adopt Codex's hardened body** — it additionally validates that `REPO_ROOT` is absolute and that the resolved `TARGET` matches `$STATE_DIR/id-[0-9][0-9][0-9].claim` exactly, so the helper cannot be coerced into a general `rm` primitive via symlink or traversal.
   - **Canonical body** → `archive/r1_codex.md` §3 ("The `rm` rule discussion is directionally right…").
   - Claude's weaker NNN-only body → `archive/r1_claude.md` §4 (use only for the matching test fixtures, not the shipped script).
   - Ratification of "adopt Codex's body" → `archive/r2_claude.md` "Concessions to Codex" §3.
3. **Shim extension** (`common/scripts/jot/expand_permissions.py`): inject the missing `Read(//${REPO_ROOT}/Todos/**)`, `Read(//${REPO_ROOT}/.claude/plans/**)`, plus the two helper-`Bash(bash /${REPO_ROOT}/skills/todo/scripts/scan-existing-todos.sh:*)` and `…release-claim.sh:*)` rules. Required for user-edited v1.1.0 installs (Claude); harmless redundancy for untouched installs.
   - **Canonical diff** (concrete `required = [...]` list + extended `LEGACY_PATTERNS` tuple) → `archive/r1_claude.md` §2 "Concrete fix — extend the shim to also inject the missing `Read` rules".
   - Augmentation requirement (also inject the two Bash helper rules) → `archive/r2_claude.md` §B and "Final position" item 4.
4. **Tests**: Codex's needle-list `permissions-expand-test.sh` with absence-of-`${IDENT}` guard, plus Claude's `release-claim-test.sh` (covers happy path, idempotence, bad-NNN rejection, unrelated-sentinel preservation).
   - **Verbatim `permissions-expand-test.sh` body** (7-needle list, env seeding, leftover-`${IDENT}` guard, PASS/FAIL wording) → `archive/r1_codex.md` §2 "The proposed `permissions-expand-test.sh` assertion is too broad".
   - **Verbatim `release-claim-test.sh` body** (happy path, idempotence, `../../etc/passwd` injection attempt, unrelated-sentinel preservation check on `id-008`, missing-args) → `archive/r1_claude.md` §4 "Bug C — plan's snippet is correct; here is the matching test".
   - Weaker Gemini alternative (happy-path only; do **not** use as-is) → `archive/r1_gemini.md` "Missing Code Snippets §3".
   - Ratification "Codex's needle-list is the correct shape" → `archive/r2_claude.md` "Concessions to Codex" §2.
5. **Step-8 rewrite** (`todo-instructions.md`): explicit `bash ${SCRIPTS_DIR}/release-claim.sh ${REPO_ROOT} <NNN>` wording — `${...}` substituted by `render_template.py` before worker reads it.
   - **Canonical rewrite text** → `archive/r1_gemini.md` "Missing Code Snippets §1 — `todo-instructions.md` Step 8 Rewrite".
   - Ratification → Claude R1 §5 and R2 "Final position" item 5.
6. **Sha256 sidecar**: recompute `permissions.default.json.sha256`.
   - **Exact command** → `archive/r1_claude.md` §6 "Plan §4 — give the user the actual command". Claude R1 Risk 1 also pins the **ordering**: regenerate the sidecar as the *last* pre-commit step, after all JSON edits are frozen.
7. **Versioning**: preflight `git ls-remote --tags origin v1.1.1` and registry state. If published → ship `v1.1.2`; if local-only → user decision. Update both `plugin.json` and `marketplace.json` (incl. nested `metadata.version` and per-plugin entries).
   - Origin of the collision finding → `archive/r1_codex.md` §1 "Do not ship this as `v1.1.1`".
   - R2 softening to "preflight then decide" → `archive/r2_codex.md` "New considerations" bullet 3.
   - Dual-file update requirement (`plugin.json` + `marketplace.json` with nested `metadata.version`) → Codex R1 §1 final paragraph.
8. **CHANGELOG**: explain user-visible behavior, the migration scenario, and the v1.1.1-was-metadata-only note.
   - **Canonical entry text** (v1.1.2-numbered, Fixed / Migration / Note sections) → `archive/r2_claude.md` "New considerations raised by reading R1s together §F — The CHANGELOG entry must explain user-visible behavior". Use this verbatim; supersedes the earlier v1.1.1-numbered draft in `archive/r1_claude.md` §7.
9. **Upgrade verification**: test fresh install, untouched-existing install, and user-edited install paths separately.
   - Enumeration of the three scenarios → `archive/r2_codex.md` "New considerations" bullet 2. **Gap: no agent produced concrete commands, expected outputs, or pass/fail criteria for any of the three scenarios.** This artifact is not in R1 or R2 and must be authored before execution. Starting point: trace `common/scripts/permissions-seed.sh:20-25,60-64` + `todo-launcher.sh:100-105` (the code paths Codex R2 cites) to derive what each scenario's state transition looks like, then assert on it.

## 7. Confidence

**High** for items 1–6 and 9. All three agents converge on the technical fixes; R2 cross-critiques resolved the open disputes (blast radius, test shape, migration scope) with concrete code references.

**Medium** for item 7. The version number depends on a fact (was `v1.1.1` published?) that none of the agents could prove from local repo state; the preflight check is necessary before the answer is determinable.

## 8. Open Questions

1. Is `v1.1.1` already pushed to the GitHub remote and/or registered in any plugin marketplace? Decides `1.1.1` reuse vs. `1.1.2`.
2. What fraction of users have `modified-by-user`-classified `todo-permissions.local.json`? Determines whether the shim extension is load-bearing or belt-and-suspenders.
3. Should the plan also audit the `Read(${HOME}/.claude/projects/**)` rule in `assets/permissions.default.json:8` (Claude R1 §8 noted as separate audit)?
4. Does the `${HOME}` vs. `~/` distinction in Claude Code's matcher warrant a project-wide convention check?
