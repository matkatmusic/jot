# Synthesis — Migration Plan for `/todo`, `/todo-clean`, `/todo-list` into the `jot` Plugin

> Note: `synthesis_instructions.txt` listed only `claude` and `codex`, but
> `r1_gemini.md` and `r2_gemini.md` are present on disk. This synthesis
> therefore folds in all three agents (Claude, Codex, Gemini) across both
> rounds, attributing arguments explicitly.

## 1. Topic

Reviewing the plan in `~/.claude/plans/the-skills-defined-in-snazzy-horizon.md`
to migrate `/todo`, `/todo-clean`, and `/todo-list` from a dotfiles submodule
into the first-party `jot` plugin.

## 2. Agreement

All three agents converge on the following:

- **Architecture is directionally correct.** Splitting by UX is right:
  `/todo` = foreground clarify + background enrich; `/todo-clean` =
  foreground-only (requires `AskUserQuestion`); `/todo-list` = synchronous
  in-hook renderer.
- **`emit_block`-silence invariant in the `/todo` dispatch path is correct**
  and the plan's citation of `plate_dispatch` as precedent is the strongest
  single piece of engineering in the document.
- **Reuse of `tmux-launcher` / `claude-launcher` / `permissions-seed` and
  the per-invocation `/tmp/todo.XXXXXX` copy-in pattern** is idiomatic and
  mirrors the proven `/jot` and `/plate` architectures.
- **Two blocking concurrency bugs** must be fixed before shipping:
  1. The `pending-${SESSION_ID}.json` filename is not unique per invocation
     and is overwritten by rapid same-session `/todo` reruns (data loss).
  2. The ID allocator in `scan-existing-todos.sh` is a non-atomic
     `max+1` computation; the claim-sentinel fix buried under "Known Risks"
     must be promoted into the first-pass implementation.
- **The foreground skill body cannot reliably learn its own `session_id`**
  to locate a session-keyed pending file; the handoff needs a deterministic,
  addressable path (à la `/plate`'s `pending-command.json`).

## 3. Disagreement

### 3a. What shape should the handoff file take?

- **Claude's final position (R2):** Stable filename *pattern* plus
  monotonic timestamp — `pending-<ISO8601-with-ms>.json` — consumed
  oldest-first by glob. Combines deterministic addressability with
  collision immunity across same-session reruns.
- **Codex's pushback (R2):** Agrees timestamping is directionally right
  but insists *seconds-resolution* timestamps (what the plan currently
  emits) can still collide in-second. Argues the real requirement is
  "unique per invocation" — UUID, nanosecond timestamp + entropy, or a
  hook-injected exact path.
- **Gemini's final position (R2):** Prefer a single stable pointer file
  (mirroring `/plate`) with optional `additionalContext` injection for
  multi-session safety.

**Strongest argument per side:**
- **Claude/Gemini:** Reuse the existing `/plate` handoff idiom — it's a
  known-good pattern, matches the codebase vocabulary, and is
  debuggable from disk.
- **Codex:** Correct observation that timestamp resolution matters;
  "stable filename" alone reintroduces the overwrite bug Claude's
  Issue 1 flagged, and "timestamped filename" alone is insufficient
  unless resolution beats the arrival rate.

### 3b. Severity of the transition-window and rollback issues

- **Claude (R1/R2):** Transition window (dotfiles symlink AND plugin
  skill both registered during rollout) is blocking for `/todo-clean`
  because skill-name resolution is ambiguous and there is no hook to
  short-circuit it. Rollback plan is required.
- **Codex (R2):** Concedes it is a real operational concern but
  downgrades to non-blocking, noting the plan already orders manual
  stale-symlink removal first and `dotfiles/install.sh` has an existing
  `/jot` precedent for stale-link removal.
- **Gemini (R2):** Endorses Claude's operational hygiene (symlink
  cleanup sequence + rollback) as "essential for production software."

### 3c. The `${HOME}` permissions anchor bug

- **Codex (R1):** Introduced this as blocking #3 — `expand_permissions.py`
  literally substitutes `${HOME}` with `/Users/...`, but a single leading
  `/` is project-root-anchored in this repo's permission docs, so the
  effective rule matches nothing.
- **Claude (R2):** Concedes fully, upgrades severity, and proposes
  auditing `${CWD}` and `${REPO_ROOT}` for the same class of bug.
- **Gemini (R2):** Concedes fully, endorses Codex's `~` anchor fix.
- **Codex (R2):** Reframes — this is a pre-existing latent defect the
  migration is *copying*, not introducing, and is a good opportunity to
  fix the anchor semantics across `/jot`, `/plate`, and `/todo`
  together.

*No disagreement on the fix itself; the disagreement is only on whether
the scope should stay local to `/todo` or expand to all jot skills.*

## 4. Strongest Arguments

- **Claude R1 (Issue 1):** Concrete scenario — `/todo idea-alpha`
  followed by `/todo idea-bravo` before the foreground skill finishes
  dispatching causes silent data loss. Directly contradicts the plan's
  own verification step (`after == before + 2`). This is the single
  strongest correctness argument across both rounds.
- **Codex R1 (Blocking #3 — `${HOME}` anchor):** Grep-verifiable proof
  of a silent-failure path the other two agents missed entirely. The
  worker's transcript-read permission silently does not exist at
  runtime.
- **Claude R2 (on Codex's handoff fix):** Shows Codex's stable
  `pending-command.json` proposal *re-introduces* the Issue-1 collision
  because `/todo` (unlike `/plate`) lacks single-flight synchronous
  dispatch. Forces the correct merged solution: stable *pattern* plus
  invocation uniqueness.
- **Codex R2 (inconsistency discoveries):** Two mismatches between the
  launcher's output sections and the worker prompt's expected input:
  - Launcher emits `## Git State` etc. but no `## Recent Conversation`,
    while the worker prompt expects the latter.
  - Worker is instructed to write `## Active plan` with a path under
    `.claude/plans/`, but the proposed permissions allowlist does not
    permit reads from that location.
  Both are immediately actionable and previously unraised.
- **Gemini R2 (integration point):** Correctly identifies that the R1
  consensus is unusually tight (3-for-3 on two blockers) and that the
  R2 value is in the asymmetric secondary findings, which is the right
  frame for the final path-forward bundle.

## 5. Weaknesses (arguments successfully challenged in R2)

- **Claude's R1 Option A (`additionalContext` injection):** Conceded
  in R2 after Codex's `/plate` precedent — more moving parts than a
  stable file, and harder to debug.
- **Codex's R1 "stable `pending-command.json`" proposal (as originally
  stated):** Challenged by Claude R2 — closes addressability but
  reopens the same-session-rerun collision. Codex R2 accepts this
  framing.
- **Claude's R1 fix using `TIMESTAMP` suffix:** Challenged by Codex R2 —
  the plan's `TIMESTAMP` is second-resolution; two rapid invocations
  in the same second still collide. Needs higher resolution or
  explicit per-invocation uniqueness token.
- **Gemini's R1 "direct context injection" as sole solution:** Gemini
  concedes in R2 that a stable pointer file is more debuggable and
  idiomatic.
- **Claude's R1 "low-priority" framing of the ID-claim sentinel:**
  Both Codex and Gemini successfully argue this must be first-pass,
  not "known risk" — Claude R2 agrees.

## 6. Path Forward

The merged merge-readiness bar is **four blocking fixes plus two
consistency fixes**, in priority order:

1. **[blocking — unanimous] Handoff file must be deterministically
   addressable AND unique per invocation.** Use
   `Todos/.todo-state/pending-<ISO8601-with-ns>-<pid>.json` (or any
   scheme that guarantees uniqueness beyond second resolution), and
   have the foreground skill body glob the directory and consume the
   oldest pending file. This resolves Claude-Issue-1 (collision),
   Codex-Blocking-1 (addressability), and Codex-R2's
   timestamp-resolution objection in one stroke.
2. **[blocking — unanimous] Promote the ID claim-sentinel to
   first-pass implementation.** Fold `scan-existing-todos.sh` so that
   (a) the initial scan reads `id-NNN.claim` files alongside
   `Todos/*.md` and `done/*.md`, and (b) the `set -C; : > sentinel`
   loop is the default allocation path. Worker deletes its `.claim`
   after successful write; failed runs leave cosmetically skipped IDs.
3. **[blocking — unanimous] Replace `${HOME}/.claude/projects/**` with
   `~/.claude/projects/**`** in `permissions.default.json`. Stop
   expanding `${HOME}` at the Python layer for this file. **Audit
   remaining `${CWD}` / `${REPO_ROOT}` uses** in the same file and in
   other jot skills (`/jot`, `/plate`) for the same anchor class bug
   while the context is fresh.
4. **[blocking — Claude, disputed by Codex] Explicit transition
   ordering for `/todo-clean`.** Publish plugin v1.1.0 → delete
   dotfiles symlinks in the same commit wave → then submodule deinit.
   Step 1 of cleanup must be an explicit required action, not a side
   effect of the next `install.sh` run. (Codex downgrades to
   non-blocking; Gemini and Claude flag blocking. Recommend treating
   as blocking given `/todo-clean`'s pure-model dispatch.)
5. **[consistency — Codex R2] Reconcile launcher output with worker
   prompt.** Either add `## Recent Conversation` to
   `todo-launcher.sh`'s output (mirroring `/jot`), or remove the
   worker prompt's dependence on it. Non-optional.
6. **[consistency — Codex R2] Reconcile worker permissions with worker
   instructions.** The worker is told to read/write `.claude/plans/`
   entries, but the allowlist lacks that permission. Either add the
   allow rule or remove the instruction. Non-optional.

**Non-blocking polish (defer to follow-up):**

- 4-token verb/noun heuristic floor before `AskUserQuestion` to
  prevent over-clarification on terse-but-specific ideas (Claude +
  Gemini).
- Rollback recipe stanza (Claude).
- `permissions.default.json.sha256` drift test (Claude; Codex notes
  `permissions_seed` already has three-state drift handling, so the
  test is useful but not gating).
- Fix doc drift: target-tree listing omits `scan-open-todos.sh` and
  `format_open_todos.py` (Codex secondary).
- `/todo-launcher.sh` take pending-file path as an explicit argument
  instead of reprobing `$PWD` + `git rev-parse` (Codex secondary).
- Self-contained `/todo-clean` verification that does not depend on a
  specific commit hash surviving rebase (Claude).

## 7. Confidence

**High** on items 1, 2, 3, 5, 6. Three agents agree independently on
items 1 and 2; items 3, 5, 6 are code-verifiable with explicit file and
line citations. The fixes are small, precedented in `/plate` / `/jot`,
and carry no architectural risk.

**Medium** on item 4 (transition-window ordering). Two agents call it
blocking; one downgrades. The risk is real but mitigations exist in the
plan; whether it is "blocking" depends on whether any
`/todo-clean` invocation during the rollout window is acceptable-as-
noise or a true incident.

**Low** on the non-blocking polish. Heuristic floors, rollback
stanzas, and doc-drift fixes are cheap and uncontroversial but not
load-bearing for correctness.

## 8. Open Questions

- **Does the UserPromptSubmit hook contract in the current Claude Code
  release support `additionalContext` injection?** Claude's R1 Option
  A depended on this; Gemini mentions it; Codex prefers not to rely on
  it. The chosen handoff-file design (path #1 above) sidesteps the
  question, but knowing the answer unlocks simpler alternatives.
- **What timestamp resolution is `date` producing in the plan's
  `TIMESTAMP` variable?** If the plan's `%Y-%m-%dT%H-%M-%S` stops at
  seconds, the collision window is real; Codex's nanosecond or
  UUID-plus-timestamp proposal is needed. If it already includes
  milliseconds or nanoseconds, Claude's simpler fix suffices.
- **Scope of the anchor-bug audit.** Codex R2 proposes fixing jot,
  plate, and todo together. Is the migration PR the right place, or
  should the anchor semantics fix land as a separate precursor PR so
  the `/todo` migration stays scoped to `/todo`?
- **Single-flight guarantee for `/todo-clean`.** Neither agent fully
  characterises what happens if two `/todo-clean` invocations overlap.
  The foreground-only design implies the second invocation would also
  prompt the user; is that a concern or accepted behaviour?
- **Are `.claim` sentinel files garbage-collected?** The path-forward
  leaves skipped IDs cosmetic-but-harmless after a failed run. If
  running long enough, does the `.todo-state/` directory need
  periodic cleanup, or are cosmetic gaps permanent and acceptable?
