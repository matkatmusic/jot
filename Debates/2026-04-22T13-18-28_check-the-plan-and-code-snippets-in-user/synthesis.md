# Debate Synthesis — Correctness Review of `plans/debate-resume.md`

## 1. Topic

Is `plans/debate-resume.md` implementation-ready as written? Specifically: are the code snippets in the plan's commits correct, and is the overall architecture sound for adding idempotent resume, `/debate-retry`, and `/debate-abort` to the debate skill?

## 2. Agreement

All three agents (claude, gemini, codex) converge on the same bottom line: **the architecture is sound, the snippets are not ship-ready.** The plan should be executed after a targeted revision pass, not thrown out.

Cross-validated findings (all three independently flagged):

- **Commit 2 word-splitting bug.** Passing smoke-test command lines as strings (`local smoke_cmd="$1"`) and expanding unquoted destroys quoting. Literal `"` bytes leak into argv, breaking every smoke test and forcing zero available agents from commit 2 onward.
- **Commit 14 hallucinated function.** `debate_main_resume` is not defined anywhere in HEAD or in the plan. The retry path doesn't compile.
- **Commit 10 topic-equality fragility.** `[ "$(cat "$dir/topic.md")" = "$topic" ]` relies on command substitution stripping trailing newlines. Works for single-line topics by accident; fails the stated "exact byte equality" invariant.
- **Architecture-level consensus.** Using `topic.md` as idempotence key, output files as completion truth, per-stage lockfiles for in-flight detection, keeping `topic.md` unarchived, and removing `agents.txt` — all three agents endorse these as correct.

Two-of-three findings:

- **Commit 9 instruction-rebuild guard too coarse** (claude + codex; gemini conceded in R2). `ls r[12]_instructions_*.txt` checks existence of *any* file, not completeness for the current `AVAILABLE_AGENTS` set. A partial prior run plus a newly-authenticated agent → missing instruction file → daemon sends nonexistent file → 15-minute stage timeout.
- **Plugin manifest is not a dispatch table** (claude + codex). The plan's "register in `.claude-plugin/plugin.json`" note is a hallucination; that file is metadata-only in this repo.

## 3. Disagreement

### 3.1 Fix for the word-splitting bug

- **Gemini (R1):** use `eval "_run_with_timeout 30 $smoke_cmd"`.
- **Claude + codex (R1):** pass argv as a bash array (`local -a base_cmd=("$@")`), no `eval`.

**Strongest argument per side:**
- Gemini's `eval` is shorter and keeps the caller-side ergonomics (one string per smoke test).
- Claude/codex's array approach is immune to shell injection, preserves bytes verbatim across future prompt edits (e.g. `$`, backticks, globs), and requires only one level of quoting analysis during review.

**Resolution:** Gemini conceded in R2. Argv arrays win decisively.

### 3.2 Fix for the topic-equality bug

- **Claude (R1):** drop the trailing newline when writing — `printf '%s' "$TOPIC" > topic.md`.
- **Gemini + codex (R1):** use `cmp -s` with a process substitution — `printf '%s\n' "$topic" | cmp -s - "$dir/topic.md"`.

**Strongest argument per side:**
- Claude's fix is a one-line change at the write site.
- Cmp-based fix handles multi-line topics, is trailing-newline-agnostic, and self-documents the invariant (exact bytes equal).

**Resolution:** Claude conceded in R2. Cmp wins for robustness.

### 3.3 Severity of B2 (outer orchestrator dispatch)

- **Claude (R1 + R2):** ranks this as the #1 blocker; without adding cases for `/debate-retry` and `/debate-abort` to `scripts/orchestrator.sh:29-48`, commits 14–15 are dead code.
- **Gemini + codex (R1):** missed the outer-dispatch layer entirely. Codex reached the inner `debate.sh` layer (uninitialized `REPO_ROOT`, missing helper sources); gemini went to the function-hallucination layer.

**Resolution:** Both other agents validated B2 in R2. Claude's framing stands — dispatch is the earliest failure point and must be fixed first.

## 4. Strongest Arguments

1. **Argv-array fix for commit 2 (claude + codex).** Three security/correctness/readability reasons against `eval` that Gemini accepted without pushback. This is the textbook bash pattern for exactly this problem.
2. **Tmux window-name + emit-path derivation from `DEBATE_DIR` on resume (codex §2, validated by claude in R2).** Commit 10 reuses `DEBATE_DIR` but leaves `window_name` and the `emit_block` success-message path deriving from a fresh `$TIMESTAMP`. Without the branch `if [ "$RESUMING" = 1 ]; then window_name="debate-$(basename "$DEBATE_DIR")"`, the resumed run spawns into a new tmux window and emits a path to a nonexistent directory. This propagates to `/debate-retry` and `/debate-abort` attach/kill instructions, making them unusable.
3. **Outer-layer dispatch in `scripts/orchestrator.sh` (claude, only).** Evidence cited with exact line ranges. This is the single most load-bearing single-source finding — without it, the retry and abort skills ship as dead code regardless of how well the inner implementation is written.
4. **Launch-time FAILED.txt (gemini §4, validated by claude + codex in R2).** Commit 13's FAILED.txt writer lives in `wait_for_outputs`, not `launch_agent`. A timeout during `launch_agent` returns 1, the caller `exit 1`s, and the daemon vanishes with no artifact. Violates decision 11's "failures must be visible."
5. **Completeness check for instruction files (claude + codex).** Per-agent presence loop, not glob-existence. Cheap to implement; blocks a 15-minute stall on a realistic "user authenticated a new agent between runs" scenario.

## 5. Weaknesses — Arguments Successfully Challenged in R2

- **Gemini's `eval` fix for B1.** Directly conceded: argv arrays are strictly better across security, correctness, and readability.
- **Claude's newline-trim fix for F1.** Directly conceded: cmp-based comparison handles multi-line topics without relying on command-substitution semantics.
- **Gemini's initial blind spot on commit 9.** Conceded: completeness check is required, not existence check.
- **Codex's initial framing of B2.** Reached the inner-layer symptom (uninitialized `REPO_ROOT` in `debate_retry_main`) but missed that the function is never dispatched to in the first place. Claude's outer-layer observation is the earlier failure.
- **Claude's initial pass over launch-time failures.** Conceded in R2: gemini's observation is concrete and load-bearing.
- **Claude's claim of "green after every commit" as only a "benefit to add invariant".** Conceded: codex showed the sole existing test hard-codes a path outside this repo and spawns real external agents. The claim in the plan is false as stated; downgrade or add unit harnesses.

## 6. Path Forward

Revise the plan, then implement. Apply in this order:

**Blockers (must fix before commit 2 lands):**

1. **Outer dispatch.** Add `"/debate-retry"|"/debate-abort"` to the case in `scripts/orchestrator.sh` alongside `/debate`.
2. **Commit 2 — argv arrays.** Signature `_try_agent_models <agent> <argv...>` (or `<argv...> --` sentinel). Never store commands as strings; never use `eval`.
3. **Shared hook init + resume entrypoint.** Add `init_hook_context` (sets `INPUT`, `CWD`, `REPO_ROOT`, `TRANSCRIPT_PATH`) and a single `debate_start_or_resume` body. `debate_retry_main` calls `init_hook_context`, finds `best`, sets `TOPIC`, `DEBATE_DIR`, `RESUMING=1`, then calls `debate_start_or_resume`. Delete the `debate_main_resume` reference.
4. **Resume-aware window name and emit path.** Branch `if [ "$RESUMING" = 1 ]` → `window_name="debate-$(basename "$DEBATE_DIR")"` and derive the emit-block path from `$DEBATE_DIR`, not `$TIMESTAMP`.
5. **Per-agent instruction-file completeness check.** Loop over `AVAILABLE_AGENTS`, rebuild if any expected file is missing. Apply to both R1 and R2 guards.
6. **Topic equality via cmp.** `printf '%s\n' "$topic" | cmp -s - "$dir/topic.md"` replaces string-equality via command substitution.
7. **FAILED.txt on launch-timeout.** Wrap `launch_agent` call sites with a `_launch_or_fail` helper that writes FAILED.txt before exiting, or extend `launch_agent`'s signature with `$DEBATE_DIR` + `$stage` and write there.

**Non-blockers (apply during implementation):**

8. Handle "new agent appeared" in commit 11 composition check — hard-fail with pointer to `/debate-abort`, symmetric to the "agent disappeared" case.
9. Drop `"claude": []` from `model-fallbacks.json` (absent key = no fallback).
10. Update the `debate-tmux-orchestrator.sh` header comment to reflect commit 4's deletion of `agents.txt`.
11. Differentiate first-invocation vs resume-time agent exhaustion messages (commit 16). `/debate-retry` hint only applies when a `DEBATE_DIR` exists.
12. Fold commit 5 into commit 10 (avoid the intermediate state where `invoking_transcript.txt` writes on resume).
13. Replace synthesis early-exit with "jump to archive" so the archive step always runs.
14. Downgrade "green after every commit" to "manual verification per commit" OR add shell unit harnesses for `find_matching_debate`, `any_live_lock`, and the composition check. Latter is preferred; few dozen lines per helper.
15. Document the pre-lock race window during `detect_available_agents` (30s+ per agent) — two same-topic `/debate` invocations within that window both classify as fresh runs. Either accept (document) or add a `hook_in_progress` sentinel written before detect.

## 7. Confidence

**High confidence** in the blocker list. Three independent readings with different priors converged on B1, B3, B4, F1. The remaining blockers (B2, C1, C2) were each single-source findings, but each was cited with exact line numbers from current HEAD and validated by the other agents in R2 without pushback.

**Medium confidence** that the blocker list is complete. The plan's weakness is a pattern — written forward from design decisions to code without tracing backward from "user types `/debate-retry`" through the dispatch stack. A grep-based spike (`grep -rn '"/debate' skills/ scripts/ hooks/ .claude-plugin/`) before implementation would surface anything the three agents missed in the dispatch path.

**High confidence** in the architectural decisions (topic.md as idempotence key, per-stage locks, output files as completion truth). Zero disagreement across three agents.

## 8. Open Questions

1. **Unit harness vs manual verification.** If the team adds shell harnesses for the new pure helpers (`find_matching_debate`, `any_live_lock`, composition check), the "green after every commit" claim holds. If not, downgrade the claim. Which path is accepted?
2. **Pre-lock race policy.** During the 30+ seconds of `detect_available_agents` smoke tests, a second `/debate <same topic>` invocation has no lockfile or DEBATE_DIR to find. Accept the race (document in out-of-scope) or add a `hook_in_progress.$$` sentinel? The debate did not reach consensus.
3. **Template-drift detection.** A prior run's `r[12]_instructions_*.txt` built against an older prompt template will be reused as-is after the completeness fix. Add a `.template_sha256` marker now, or defer? Claude flagged as non-blocker for v1.
4. **Exact resume semantics for new-agent case.** All three agents agree "agents gained" should hard-fail and require `/debate-abort` + re-run. Confirm the message wording and whether `/debate-abort` should clear synthesis-bound state too.
5. **`emit_block` wording on resume.** "resumed" vs "spawned" was proposed but not fully specified. Align messages across the three emit paths (fresh spawn, resume, retry).
