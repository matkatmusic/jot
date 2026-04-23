# Debate Synthesis — `~/.claude/plans/debate-is-not-launching-nifty-reddy.md`

## 1. Topic
Is the plan to replace `/debate`'s shared `debate` tmux session with an ephemeral per-invocation `debate-<N>` session safe to execute as written?

## 2. Agreement
All three agents converge on the following:

- **Architectural direction is correct.** Session-per-invocation is the right fix for the `spawn_terminal_if_needed "debate"` early-return bug that causes the second `/debate` call to silently disappear.
- **Cleanup blast radius should be session-scoped.** Replacing `tmux_kill_window` with `tmux_kill_session` is the right move once each debate owns its session.
- **Plan is not committable as written.** Even Gemini, who initially approved, retracts in R2.
- **Line-number citations in the plan are stale.** Two independent verifications converge: target block in `debate.sh` is at ~208-258 (not 169-188), and the `SESSION="debate"` hardcode is at orchestrator line 32 (not 27).
- **`resume-integration-test.sh` will crash under `set -u`** if `SESSION` becomes purely positional without a fallback in sourced mode.
- **Three user-facing `emit_block` messages at `debate.sh:291,349,383`** still hardcode `tmux attach -t debate:debate-<basename>` and must be updated — the new `debate-<N>` session name is not derivable from the debate directory path.

## 3. Disagreement

### 3a. Is the naming race "tolerable" (R1 only)?
- **Gemini R1 (weaker side):** Two concurrent `/debate` calls racing on the same `N` is acceptable because `tmux_ensure_session` will "fail loudly" and the ERR trap surfaces it. No lockfile warranted.
- **Claude R1 + Codex R1 (stronger side):** False — `tmux_ensure_session` does not fail on duplicate; it silently falls through to `tmux_window_exists` / `tmux_ensure_keepalive_pane`, so the loser joins the winner's session. The fix is one loop using `tmux new-session` as the atomic primitive.
- **Resolution (R2):** Gemini concedes. Unanimous: race is a blocker; use atomic-claim or retry-on-duplicate loop.

### 3b. How to recover the live session name for messaging?
- **Claude R1:** Persist `tmux-session.txt` in `$DEBATE_DIR` (option a) or derive from live pane id (option b). Recommends (a) as simpler.
- **Codex R1:** Derive from live pane id using `tmux display-message -p -t "$pane_id" '#{session_name}'` on the lock-file's pane id.
- **Resolution (R2):** Claude retracts (a) and adopts Codex's (b) — self-healing, reuses existing lock state, no new on-disk artifact.

### 3c. Fail-fast vs default for sourced `SESSION`
- **Claude R1:** `: "${SESSION:=debate}"` — default papers over harness drift.
- **Codex R1:** `: "${SESSION:?SESSION required}"` — fail fast, harness must explicitly export `SESSION`.
- **Resolution (R2):** Claude concedes; `:?` form wins for correctness signals.

### 3d. Keepalive-pane duplication side effect
- **Claude R1:** Race loser's `tmux_ensure_keepalive_pane` adds a second keepalive to the winner's window.
- **Codex R2 correction:** Not necessarily — `tmux_ensure_keepalive_pane` checks `tmux_pane_has_title`, so if winner already titled it `keepalive`, loser silently no-ops.
- **Resolution:** The silent-session-reuse bug still exists and still violates the requirement. The mechanism is narrower than Claude's r1 trace stated.

## 4. Strongest Arguments

1. **Claude R1 §1 — code trace disproving Gemini's "fails loudly" defense.** Single most load-bearing argument in the debate: forced Gemini to retract and converted the race from a noted risk to an agreed blocker.
2. **Codex R1 §1 — `live_debate_session` helper.** Cleanest recovery design; reuses existing lock files, no new state file, authoritative on session renames.
3. **Codex R1 §2 — `:?` fail-fast for sourced `SESSION`.** Better correctness signal than a silent default; Claude conceded.
4. **Codex R2 §"missing-orchestrator.log"** — direct empirical test (`bash ... >> orch_log 2>&1` creates the file before script body runs) strengthens Claude R1 §5's challenge to the plan's root-cause framing.
5. **Claude R1 §4 + Codex R1 §Secondary — independent line-number verification.** Two independent greps converged on 208-258 / line 32; high confidence.
6. **Codex R1 §Secondary — verification brittleness** if stale `debate-*` sessions exist. Claude conceded and proposed "diff vs. pre-run list" over kill-all.

## 5. Weaknesses — Arguments Challenged in R2

- **Gemini R1 — "race is tolerable".** Factually disproved by Claude's code trace; Gemini retracts in R2.
- **Gemini R1 — "tests out of scope".** Plan-level boundary failed to distinguish the out-of-scope `test.sh` from the active `resume-integration-test.sh`; Gemini concedes in R2.
- **Claude R1 §1 — "loser adds a second keepalive pane".** Codex R2 shows `tmux_pane_has_title` guard prevents the duplicate pane; the harm is silent session reuse, not pane duplication. Bug remains, mechanism narrows.
- **Claude R1 §2 — `tmux-session.txt` persistence.** Retracted in R2 in favor of Codex's pane-id derivation.
- **Claude R1 §3 — `: "${SESSION:=debate}"` default.** Retracted in R2 in favor of Codex's `:?` fail-fast.
- **Plan §Verification — "expect exactly debate-1, debate-2".** Brittle if stale sessions exist (Codex); all agents agree verification must assert the diff, not fixed names.

## 6. Path Forward — Consolidated Blocker List

**Blockers (must land before execution):**

1. **Atomic/retry session creation.** Replace `debate_next_session_name` with a `tmux new-session`-based loop that advances `n` on collision (Claude's `debate_claim_session` or Codex's `debate_create_unique_session` — structurally equivalent).
2. **Live-session recovery.** Implement Codex's `live_debate_session` helper. Update the three `emit_block` messages at `debate.sh:291,349,383` to resolve the live session via lock-file pane id and tell the user `tmux attach -t <session>:main`.
3. **`SESSION` in sourced daemon mode.** Use `: "${SESSION:?SESSION required}"` in `debate-tmux-orchestrator.sh`. Update `resume-integration-test.sh:221-237` to export `SESSION` explicitly before sourcing.
4. **Correct line citations.** `debate.sh` ~208-258 (not 169-188); orchestrator line 32 (not 27).

**Required (same patch):**

5. **Verification diff-based assertion.** Capture `debate-*` session list before the run; assert "two new sessions appeared" rather than "debate-1 and debate-2 exist". Do not auto-kill stale sessions.
6. **Update stale "shared debate session" comments** in `debate-tmux-orchestrator.sh` header/inline + `skills/debate/README.md:14`.

**Recommended (cheap to verify, expensive to be wrong about):**

7. **Reproduce the reported failure.** Confirm whether `orchestrator.log` is literally absent or present-but-unseen. Shell redirection opens the log before the script body, so absence would indicate an upstream fork failure — a second bug the plan does not fix. Update §Verification step 1 baseline from the reproduction.

**Nice-to-have:**

8. **Pane title includes topic slug** so reused `debate-N` numbers are not confusing to users who keep attach commands around.

## 7. Confidence — **High**

Reasoning:
- All three agents converge on the same blocker list after R2.
- Two independent code traces (Claude, Codex) corroborate each other on the race mechanism, line numbers, harness breakage, and recovery requirement.
- Gemini's initial disagreement was grounded in a factual error about `tmux_ensure_session` behavior; Gemini retracts in R2 with citations.
- Codex's R2 empirical test of shell-redirect-then-fail is concrete supporting evidence, not just code reading.

The one remaining uncertainty (§7 recommended) is about whether the root-cause hypothesis fully explains the reported symptom, not about the safety of the proposed amendments.

## 8. Open Questions

1. **Is `orchestrator.log` literally absent in the reported failure, or present and unseen?** Plan asserts absence; shell-redirection semantics suggest presence. Answer changes whether this plan closes the whole bug or only part. Requires one reproduction in a scratch directory.
2. **Session-number reuse UX risk.** After `debate-1` dies, next invocation becomes `debate-1`. Users with a stale attach command in scrollback will land in the wrong debate. Nobody besides Claude engaged; unresolved whether the slug-in-pane-title mitigation is worth the line of code or should be deferred.
3. **Is the one-window-per-session `window_name` argument dead weight?** Claude R1 flagged the plan still threads `window_name` through positional args despite hardcoding it to `main`. Not discussed in R2 — small design incoherence remains.
