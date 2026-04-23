# R2 — Cross-Critique

**Summary of where I stand after reading gemini and codex:**

- Strong three-way convergence on 4 bugs. That convergence is itself evidence — independent readers with different priors flagged the same snippets.
- I concede **3 items** the others caught that I missed.
- I challenge **1 proposed fix** (gemini's `eval` solution) as strictly worse than the argv-array approach codex and I independently arrived at.
- I reaffirm **1 finding** (B2 — orchestrator dispatch) that neither other agent identified but which is the single most load-bearing bug in commits 14–15.

---

## 1. Three-way agreement — these 4 findings are real

All three of us independently identified:

| Bug | My label | Gemini label | Codex label |
|---|---|---|---|
| `$smoke_cmd` word-splitting in commit 2 | B1 | §1 | §3 |
| Hallucinated `debate_main_resume` in commit 14 | B3 | §2 | §1 |
| `ls r1_instructions_*.txt` guard too coarse in commit 9 | B4 | (absent) | §4 |
| `topic.md` equality via newline-stripping | F1 | §3 | §6 |

Gemini missed B4; otherwise all four are cross-validated. The four are blockers as a group: without B1, commit 2 gates all downstream commits to 0-available-agents; without B3/B4, resume paths deadlock or silently run half-armed; without F1, idempotence breaks on the next `TOPIC` that happens to carry a trailing newline from a heredoc or copy-paste.

---

## 2. Concessions — 3 issues I missed

### C1 — Resume reuses `DEBATE_DIR` but not the tmux window name (codex §2)

Codex is right. Verified against current HEAD:

```
skills/debate/scripts/debate.sh:180:  local window_name="debate-${TIMESTAMP}_${slug}"
skills/debate/scripts/debate.sh:201:  emit_block "/debate spawned (...) → Debates/${TIMESTAMP}_${slug}/synthesis.md (~10-30 min). View: tmux attach -t debate"
```

On resume, `TIMESTAMP` is re-computed at line 132 from `date +%Y-%m-%dT%H-%M-%S`, so the resumed daemon launches into a **new** tmux window and emits a success message pointing to a **non-existent** `Debates/${today_ts}_${slug}` path. The user sees the path, looks for the dir, and finds nothing — or opens the wrong (new, empty) tmux window. The `/debate-retry` and `/debate-abort` paths, which instruct the user to `tmux attach -t debate:...`, also break for the same reason.

My R1 described the broader resume hand-off (B3) but stopped short of checking every downstream `${TIMESTAMP}` reference. Codex's evidence is concrete and I concede the point.

**Fix (extending my B3 proposal):** whenever `RESUMING=1`, derive the window name and the emit-path from `DEBATE_DIR`:

```bash
local dir_basename window_name
dir_basename=$(basename "$DEBATE_DIR")
if [ "$RESUMING" = 1 ]; then
  window_name="debate-${dir_basename}"
else
  window_name="debate-${TIMESTAMP}_${slug}"
fi
...
emit_block "/debate $([ "$RESUMING" = 1 ] && printf resumed || printf spawned) (${agents_str// /, }) → Debates/${dir_basename}/synthesis.md (~10-30 min). View: tmux attach -t debate"
```

Codex's adjacent observation — that `tmux attach -t debate:$(basename "$best")` in the retry snippet omits the required `debate-` prefix — is also correct and follows from the same invariant fix. All emits should use `debate:${window_name}`, never reconstruct the target inline.

### C2 — `launch_agent` timeout orphans the lockfile with no FAILED.txt (gemini §4)

Gemini is right. Verified:

```
skills/debate/scripts/debate-tmux-orchestrator.sh:109:  echo "[orch] TIMEOUT: $label not ready within ${timeout}s" >&2
skills/debate/scripts/debate-tmux-orchestrator.sh:110:  return 1
skills/debate/scripts/debate-tmux-orchestrator.sh:209:  launch_agent ... || exit 1
```

Commit 13's FAILED.txt block lives inside `wait_for_outputs` (stage-completion timeout). A `launch_agent` timeout bypasses that block: it returns 1, the caller `exits 1`, the daemon dies, the per-stage lockfile remains on disk, and the `any_live_lock` check on the next `/debate` invocation sees a lockfile whose pane is also dead (so `pane_current_command` mismatch → stale → cleanable) — but only *after* the user re-invokes. The immediate symptom is: daemon vanishes, no FAILED.txt, no user-visible feedback, user thinks the run is still going.

My R1 passed over launch-time timeouts entirely. I concede.

**Fix:** either (a) promote `launch_agent` to write FAILED.txt before `return 1`, or (b) gate `launch_agent || exit 1` with a wrapper that writes FAILED.txt then exits. Option (a) requires `launch_agent` to know `$DEBATE_DIR` and `$stage` — neither is in its signature today. Cleanest shape:

```bash
# in debate-tmux-orchestrator.sh, wrap the call sites:
_launch_or_fail() {
  local stage="$1" agent="$2" pane="$3" cmd="$4" marker="$5"
  if ! launch_agent "$pane" "${agent}(${stage})" "$cmd" "$marker"; then
    printf '# debate FAILED\n\nstage: %s (launch)\nagent: %s\nreason: agent did not reach ready marker within timeout\npane: %s\n' \
      "$stage" "$agent" "$pane" > "$DEBATE_DIR/FAILED.txt"
    return 1
  fi
}
# call sites:
_launch_or_fail r1 "$agent" "${R1_PANES[$i]}" "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" || exit 1
```

The lockfile itself is handled by the next-invocation staleness check (plan §7), so we don't need to delete it here — but FAILED.txt makes the failure *visible*, which is the v1 invariant the plan claims to uphold.

### C3 — The "green after every commit" claim is unsupported (codex §5)

Codex is right. Verified: only `skills/debate/tests/test.sh` exists, it hard-codes a path outside this repo, and it spawns real external agents. There is no unit-level harness for topic matching, transcript matching, or lock cleanup — the exact helpers commits 10/11/13 introduce.

My R1 noted in passing that the plan "would benefit from a line-item invariant" but stopped short of flagging that the invariant *as-stated* is false. Codex is stronger here.

**Fix:** either downgrade the claim to "manual verification per commit", or add minimal shell harnesses for the three new pure functions (`find_matching_debate`, `any_live_lock`, the composition check). The second is cheap — these helpers take strings and paths and return strings/exit codes, so a shunit2-style or bats-style harness is a few dozen lines. Recommend doing it; it materially changes the plan's ship-readiness claim.

---

## 3. Disagreement — gemini's `eval` fix for B1 is worse than the argv-array fix

Gemini §1 proposes:

```bash
if eval "_run_with_timeout 30 $smoke_cmd" >/dev/null 2>&1; then
```

Codex §3 and I independently proposed passing the command as positional argv (`local -a base_cmd=("$@")` / `"${base_argv[@]}"`). Gemini's `eval` is strictly worse for three reasons:

1. **Security.** The smoke-test string is hard-coded today, but once the plan ships, any future addition (e.g., per-agent env, per-user custom flag via `$HOME/.debaterc`) that interpolates user-controllable bytes into `smoke_cmd` becomes an injection vector. `eval` + untrusted substring is a classic footgun. Arrays are immune.
2. **Correctness on edge cases.** The prompt literal `"Reply with exactly: ok"` contains a `:`. Inside `eval`, if anyone ever changes the prompt to contain a `$`, a backtick, or a glob metachar, it re-expands on every call. Arrays preserve bytes verbatim.
3. **Readability / debuggability.** `eval "_run_with_timeout 30 $smoke_cmd --model \"\$m\""` requires two levels of quoting analysis (outer literal, inner single-var with escaped `$`). A reader debugging a model-fallback failure has to simulate the shell twice. `"${base_argv[@]}" --model "$m"` has one level.

`eval` is never the right answer when the alternative is an array. I would not accept this fix in review. Use codex's / my variant.

Gemini's underlying diagnosis of B1 is correct — only the proposed fix is wrong.

---

## 4. Reaffirmation — B2 (orchestrator dispatch) is the #1 blocker

Neither gemini nor codex flagged B2. I reaffirm it with the direct evidence from my R1:

```
scripts/orchestrator.sh:29-48:
  case "$PROMPT" in
    ...
    "/debate"|"/debate "*|$'/debate\n'*) ...
    ...
    *) exit 0 ;;   ← /debate-retry and /debate-abort land here
  esac
```

Without the two new cases added to `scripts/orchestrator.sh`, commits 14 and 15 are *dead code*. The daemon never receives the dispatch; `debate.sh`'s inner case branches are unreachable; the user sees the slash command echo into the chat like regular text.

Codex §1 touched the adjacent issue — that `debate_retry_main` lacks `REPO_ROOT` and the helper sources — but did so at the `debate.sh` layer. The orchestrator-layer dispatch is a separate, earlier failure. Both fixes are required: dispatch + shared init.

Codex §6 also noted that "register the skill in `plugin.json`" is a hallucination because `.claude-plugin/plugin.json` is just package metadata in this repo. That's a supporting observation for B2: the plan's author assumed plugin.json was the dispatch table (it isn't), which led them to skip the real dispatch table (`scripts/orchestrator.sh`).

---

## 5. New consideration raised by reading the others

**A convergence on the topic-equality fix.** Gemini and codex both proposed `cmp -s` with a file or process-substitution. My F1 proposed the alternative — drop the trailing newline when writing, making `$(cat ...) = "$topic"` byte-accurate. Comparing the two:

- **My fix** (write without `\n`): one-line change, but leaves `topic.md` unterminated which is mildly annoying (`cat topic.md` runs into the next prompt) and leaves the comparison relying on the command-substitution newline-stripping behavior for any *future* multi-line topic.
- **cmp fix:** two-line change, handles multi-line topics, trailing-newline-agnostic, and the invariant is self-documenting (if `cmp -s` says equal, the bytes are equal).

Codex's variant uses `printf '%s\n' "$topic" | cmp -s - "$dir/topic.md"`, which is the cleanest. I concede — adopt the cmp approach over my newline-trim.

---

## 6. Updated punch list (merging all three R1s)

Before implementing, the plan needs these revisions. Numbered by severity:

1. **B2 — add `/debate-retry`, `/debate-abort` to `scripts/orchestrator.sh` case.** Without this, commits 14–15 are no-ops. (Me, only.)
2. **B1 — argv-as-array in commit 2, no `eval`.** (All three; my + codex's fix.)
3. **B3 + C1 — real shared entrypoint for resume, + rewrite `window_name` and the emit_block path to derive from `DEBATE_DIR`.** (Me + codex + gemini for the entrypoint; codex alone for the window naming.)
4. **B4 — per-agent presence check, not glob-existence, for `r[12]_instructions_*.txt`.** (Me + codex.)
5. **C2 — `_launch_or_fail` wrapper that writes FAILED.txt on launch-timeout.** (Gemini, only.)
6. **F1 with cmp — swap my newline-trim for codex's cmp-based equality.** (All three.)
7. **C3 — either downgrade "green after every commit" claim or add unit harnesses for the new pure helpers.** (Codex, only.)
8. **S1–S5 (my R1)** — apply inline during implementation; no additional commit count.

**Revised ship-readiness estimate:** ~60%. I said 70% in R1; the three concessions (window-naming, launch-timeout-FAILED.txt, overstated test loop) are each meaningful enough to drop 10 points between them. None individually forces a re-plan; collectively they reinforce codex's bottom line ("worth keeping, not literal-ready").

---

## 7. Meta-observation on the debate itself

What the three-way view adds over any single R1:

- **B1, B3, B4, F1 are load-bearing.** Three independent readings → very high confidence. Fix first.
- **B2 and C2 are load-bearing but only one reader caught each.** Single-source findings are higher variance; worth a second check during implementation. For B2 I've quoted the exact lines; for C2 gemini's evidence is concrete (line numbers 109–110 + 209). Both hold up.
- **The plan's weakness is a pattern, not a set of typos.** It was written by tracing *forward* from design decisions to code, without tracing *backward* from "user types `/debate-retry`" through the actual dispatch path. B2, B3, C1, and the plugin.json note all trace back to the same gap. A pre-implementation spike that runs `grep -rn '"/debate' skills/ scripts/ hooks/ .claude-plugin/` and maps every match to a code path would catch all four at once.
