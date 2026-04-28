# Debate Synthesis — Parallel Debate Agent Launch Plan (`calm-squishing-eclipse.md`)

## 1. Topic
Should the `/jot:debate` orchestrator's plan to switch agent launch from serial to parallel (per `~/.claude/plans/calm-squishing-eclipse.md`) be approved, and if so, with what amendments?

## 2. Agreement
All three agents (Claude, Gemini, Codex) converge on:

- **Architecture is correct.** Backgrounding the `launch_agent` + `send_prompt` pair for each agent and reaping with a positional `wait "${pids[$i]}"` loop is the right approach for macOS Bash 3.2.
- **`wait -n` cannot be used.** Bash 3.2 lacks it; the positional PID barrier is the portable substitute.
- **The original `FAILED.txt` write path is unsafe** once launches are parallelized — direct redirection into the final filename will tear under concurrent writers.
- **A temp-file + rename approach is required** for atomic failure reporting.
- **Existing resume tests are launch-order tolerant** (they sort `.harness_invocations` before comparing) but only prove *compatibility*, not *concurrency*. New tests are needed.
- **Pane creation must remain serial** (tmux split-window ordering); only launch/prompt fan out.

## 3. Disagreement

### 3a. Is the plan's `.FAILED.txt.$$` tempfile fix correct?
- **Claude (R1) + Codex (R1):** **No.** On macOS Bash 3.2, `$$` is the parent shell's PID inside subshells and `$BASHPID` is unset. All concurrent workers share the same path and the original race survives. **Required fix:** `mktemp "$DEBATE_DIR/.FAILED.txt.XXXXXX"`.
- **Gemini (R1):** Proposed `.FAILED.tmp.$$` plus `mv -n`. **In R2 Gemini fully concedes** — the `$$` analysis was wrong and `mktemp` is needed.

### 3b. `mv -f` vs `mv -n` (failure-reporting policy)
- **Codex:** Use `mv -f` to preserve the plan's documented "last-writer-wins" semantics. Changing policy as a side effect of a refactor is out of scope.
- **Claude:** Agrees with `mv` (default = last-writer-wins).
- **Gemini (R1):** Suggested `mv -n` (first-writer-wins). Not defended in R2.

### 3c. Keep timing instrumentation permanent?
- **Claude:** Keep a single concise log line (`launch_agents_parallel: N workers, Xs wall`) permanently for cheap regression evidence.
- **Codex (R2):** Concedes the value; accepts if log stays readable.
- **Gemini:** Did not address.

## 4. Strongest Arguments

- **Claude's strongest:** Concrete demonstration of the `$$`/subshell race showing torn writes (`O_TRUNC` interleave + post-`mv` ENOENT) — the plan's own §4 fix re-introduces the race it was added to prevent.
- **Codex's strongest:** Explicit landing criteria with helper-level **timing test** (stub `launch_agent` with `sleep 2`, assert wall-clock < 4s) so serial regressions fail loudly. Also: distinguishing `write_failed` callers from `wait_for_outputs` callers in plan wording.
- **Gemini's strongest:** Surfacing the **fail-fast trade-off** — sequential `wait` means a fast failure on agent 3 isn't observed until agent 1's launch_timeout elapses (~120s extra). Acceptable under STAGE_TIMEOUT=900s, but should be documented.

## 5. Weaknesses (challenged in R2)

- **Gemini's `$$` tempfile** — retracted; `$$` collides across subshells on Bash 3.2.
- **Gemini's `mv -n`** — silently changes failure-reporting policy (first-wins vs last-wins). Both Claude and Codex flagged this as out-of-scope policy drift.
- **Plan's claim** that `$$` collisions are "harmless overwrite" — refuted by Claude and Codex with concrete subshell evidence and write-interleave timeline.
- **Claude's R1 understated** the value of an explicit helper-level timing test; conceded to Codex in R2.

## 6. Path Forward — Required Plan Amendments

**Blockers (all three agents agree):**
1. Replace `.FAILED.txt.$$` with `mktemp "$DEBATE_DIR/.FAILED.txt.XXXXXX"` followed by `mv -f` (preserve last-writer-wins).
2. Add a **helper-level timing test**: stub `launch_agent` with `sleep 2`, assert elapsed < 4s — fails loudly under serial regression.
3. Add a **concurrent `write_failed` race test**: triple-parallel invocation, assert exactly one `# debate FAILED` header and three `### <agent>` sections.

**Recommended (non-blocking):**
4. Keep a permanent one-line timing log in `launch_agents_parallel` for ongoing observability.
5. Document the fail-fast trade-off in plan §Trade-offs (`detection latency = max(launch_timeout)`; acceptable while STAGE_TIMEOUT ≥ 2× launch_timeout).
6. Clean up plan wording so failure diagnostics distinguish helper-worker failures from `wait_for_outputs` timeouts.
7. Document the lock-held-branch capacity gap as a pre-existing follow-up (out of scope for this refactor).

## 7. Confidence — **High**

All three agents converge on a single landing path. The two substantive disagreements (`$$` vs `mktemp`; `mv -n` vs `mv -f`) were resolved cleanly in R2 with Gemini conceding both points. The architecture itself drew zero structural objections. Concrete evidence (Bash 3.2 subshell behavior, harness compatibility, existing test sort) was reproduced and cross-verified across responses.

## 8. Open Questions

- **Lock-held resume branch:** When a worker skips launch because a live lock exists, the helper does not recheck capacity post-skip. Codex flagged as pre-existing; out of scope here but should be tracked.
- **Helper failures without `write_failed`:** If `launch_agent` itself dies before reaching the failure-write path, what diagnostic is captured? Codex raised; not fully resolved.
- **Test strategy nuance:** Codex notes correctness tests (overlap, race) and speed tests (wall-clock budget) should be separated to avoid flaky CI under loaded runners.
- **Whether to add `BASHPID` fallback elsewhere** in the codebase that may share the same latent assumption (audit not in scope of this plan).
