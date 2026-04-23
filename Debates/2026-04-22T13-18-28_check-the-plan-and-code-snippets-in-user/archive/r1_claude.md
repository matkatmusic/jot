# R1 — Correctness Review of `plans/debate-resume.md`

**Position:** The plan is **conceptually sound but not ship-ready**. Four blocking bugs in the code snippets would break the first execution. Several smaller gaps would cause incorrect behavior in recoverable edge cases. Verdict: do a targeted revision pass before coding any of the commits. Below I cite each defect with the exact source snippet, file:line anchor, and concrete fix.

---

## BLOCKERS — the plan as written will not execute correctly

### B1 — Commit 2: `$smoke_cmd` word-splitting destroys the smoke-test argument

**File:** plan §2 (`skills/debate/scripts/debate.sh` rewrite, lines 26–62).

**The snippet (plan, as-is):**

```bash
_try_agent_models() {
  local agent="$1"; shift
  local smoke_cmd="$1"; shift
  ...
  if _run_with_timeout 30 $smoke_cmd >/dev/null 2>&1; then
    ...
  if _run_with_timeout 30 $smoke_cmd --model "$m" >/dev/null 2>&1; then
  ...
}

_try_agent_models gemini 'gemini -p "Reply with exactly: ok"'
_try_agent_models codex  'codex exec "Reply with exactly: ok" --full-auto'
```

**Why it breaks:** `smoke_cmd` holds the literal string `gemini -p "Reply with exactly: ok"`. The expansion `$smoke_cmd` is unquoted, so bash word-splits on `IFS` whitespace *after* quote removal has already run (quote removal only applies to literal tokens in source, not to the contents of a variable). The `"` characters therefore become **literal bytes** inside the split tokens. Gemini receives:

```
argv[0]=gemini
argv[1]=-p
argv[2]="Reply        ← literal opening quote
argv[3]=with
argv[4]=exactly:
argv[5]=ok"           ← literal closing quote
argv[6]=--model
argv[7]=gemini-2.5-pro
```

That is **not** the same invocation as today's working `_run_with_timeout 30 gemini -p "Reply with exactly: ok"` (which passes a single argument). Gemini will reject it or answer a different prompt, the smoke test will fail, and **every fallback model on the list is declared dead** — even when all are healthy. Net effect: /debate boots, hits commit 2's loop, exits with "needs ≥2 agents" regardless of actual agent health. Feature is non-functional from commit 2 onward until this is fixed.

Evidence it matters now: the current HEAD (lines 35, 53) passes the prompt as a literal argument specifically to avoid this.

**Concrete fix — use an array, not a string:**

```bash
# _try_agent_models <agent> <-- followed by the smoke argv as positional args,
# terminated by the sentinel "--". Trailing args are prepended to every model try.
_try_agent_models() {
  local agent="$1"; shift
  local -a base_argv=()
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do
    base_argv+=("$1"); shift
  done
  shift  # consume the --
  local fallbacks_json="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/assets/model-fallbacks.json"
  local -a models=()
  while IFS= read -r line; do models+=("$line"); done \
    < <(jq -r --arg a "$agent" '.[$a][]?' "$fallbacks_json")

  if [ "${#models[@]}" -eq 0 ]; then
    if _run_with_timeout 30 "${base_argv[@]}" >/dev/null 2>&1; then
      printf ''
      return 0
    fi
    return 1
  fi
  local m
  for m in "${models[@]}"; do
    if _run_with_timeout 30 "${base_argv[@]}" --model "$m" >/dev/null 2>&1; then
      printf '%s' "$m"
      return 0
    fi
    hide_errors printf '%s debate: %s model %s failed smoke test\n' \
      "$(date -Iseconds)" "$agent" "$m" >> "$LOG_FILE"
  done
  return 1
}

# Call sites:
if GEMINI_MODEL=$(_try_agent_models gemini gemini -p "Reply with exactly: ok" --); then
  AVAILABLE_AGENTS+=(gemini)
fi
if CODEX_MODEL=$(_try_agent_models codex codex exec "Reply with exactly: ok" --full-auto --); then
  AVAILABLE_AGENTS+=(codex)
fi
```

The `--` sentinel lets the caller pass a variable-length argv that contains spaces in a single arg, without any quoting games inside the function.

---

### B2 — Commit 14: `/debate-retry` and `/debate-abort` never reach `debate.sh`

**Evidence from the existing dispatcher — `scripts/orchestrator.sh:29-48`:**

```bash
case "$PROMPT" in
  "/jot"|"/jot "*|$'/jot\n'*)   ... ;;
  "/plate"|"/plate "*|$'/plate\n'*) ... ;;
  "/debate"|"/debate "*|$'/debate\n'*)
    printf '%s' "$INPUT" | bash "$PLUGIN_ROOT/skills/debate/scripts/debate-orchestrator.sh"
    ;;
  "/todo"|"/todo "*|$'/todo\n'*) ... ;;
  "/todo-list"|"/todo-list "*|$'/todo-list\n'*) ... ;;
  *)
    exit 0
    ;;
esac
```

**Why the plan breaks:** `/debate-retry` and `/debate-abort` are distinct slash commands, not `/debate`-prefixed. They fall into the `*) exit 0;;` branch of `scripts/orchestrator.sh` and **never get dispatched to `debate-orchestrator.sh`**. The plan edits `debate.sh` internal dispatch at lines 108–121, but control never reaches that code for the two new commands. Commits 14 + 15 are inert.

The plan's only note on this is a throwaway line: *"Register the skill in the plugin manifest (.claude-plugin/plugin.json — location TBD, mirror the /debate registration)"* — but `/debate` is **not** registered in `plugin.json` (see `.claude-plugin/plugin.json`, which lists zero skills). `/debate` is wired through `hooks/hooks.json` → `scripts/orchestrator.sh`. That file is the single source of dispatch.

**Concrete fix — edit `scripts/orchestrator.sh` (add two case arms alongside /debate):**

```bash
  "/debate"|"/debate "*|$'/debate\n'*|"/debate-retry"|"/debate-abort")
    printf '%s' "$INPUT" | bash "$PLUGIN_ROOT/skills/debate/scripts/debate-orchestrator.sh"
    ;;
```

Then `debate.sh`'s inner `case "$PROMPT" in /debate-retry) ...` fans out as planned.

---

### B3 — Commit 14: `debate_main_resume "$best"` is not defined anywhere

Plan §14 snippet ends with:

```bash
debate_retry_main() {
  ...
  TOPIC=$(cat "$best/topic.md")
  # Delegate to the standard resume path.
  debate_main_resume "$best"
}
```

`debate_main_resume` is not defined in the plan or in HEAD. The plan also restructures `debate_main` (commit 10) to do the resume detection internally when given a topic. So the intended call is `debate_main` after setting `TOPIC` and forcing the function to re-classify as RESUMING. But `debate_main`'s classification is driven by scanning `Debates/*/topic.md` — which works only because commit 4 stopped archiving `topic.md`.

**Concrete fix — don't introduce a ghost function; reuse `debate_main` with `DEBATE_DIR` pre-seeded:**

```bash
debate_retry_main() {
  # (same scan as planned, producing $best)
  ...
  [ -z "$best" ] && { emit_block "/debate-retry: no debate found in this conversation"; return; }
  if [ -f "$best/synthesis.md" ]; then
    emit_block "/debate-retry: last debate is already complete, see $best/synthesis.md"
    return
  fi
  if any_live_lock "$best"; then
    emit_block "/debate-retry: debate is still running → tmux attach -t debate:$(basename "$best")"
    return
  fi

  TOPIC=$(cat "$best/topic.md")
  DEBATE_DIR="$best"
  RESUMING=1                           # signals debate_main to skip dir-scan + identity writes
  FORCE_EXISTING="$best"               # cheaper than rescanning — debate_main can honor it
  debate_main
}
```

And in `debate_main`, between commit 10's classification and the identity-file writes, add:

```bash
if [ -n "${FORCE_EXISTING:-}" ]; then
  DEBATE_DIR="$FORCE_EXISTING"
  RESUMING=1
else
  # existing find_matching_debate classification (commit 10)
fi
```

The plan doesn't have to name it `FORCE_EXISTING` — but it does need *some* hand-off mechanism, and hand-waving "delegate to the standard resume path" is not an implementation.

---

### B4 — Commit 9: partial or composition-changed instruction set never regenerates

Plan §9:

```bash
if ! ls "$DEBATE_DIR"/r1_instructions_*.txt >/dev/null 2>&1; then
  DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" \
    bash "$SCRIPTS_DIR/debate-build-prompts.sh" r1 "$DEBATE_DIR" "${CLAUDE_PLUGIN_ROOT}"
fi
```

**Failure mode:** "already present" means "at least one file exists" — not "all files for current `AVAILABLE_AGENTS` exist". Commit 11's composition check rejects resumes where an *original* agent is gone, but it does **not** reject resumes where AVAILABLE_AGENTS has *gained* an agent (user authenticated codex between runs). In that case:

- `r1_instructions_claude.txt` exists → `ls` succeeds → skip rebuild
- `r1_instructions_codex.txt` **missing**
- daemon loop `for agent in "${AGENTS[@]}"` reaches codex, calls `send_prompt ... "$DEBATE_DIR/r1_instructions_codex.txt"` → codex reads a nonexistent file → errors silently in its TUI → stage times out 15 minutes later → `FAILED.txt` written

**Concrete fix — verify set equality, not existence:**

```bash
r1_rebuild_needed=0
for agent in "${AVAILABLE_AGENTS[@]}"; do
  [ -f "$DEBATE_DIR/r1_instructions_${agent}.txt" ] || { r1_rebuild_needed=1; break; }
done
if [ "$r1_rebuild_needed" = 1 ]; then
  DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" \
    bash "$SCRIPTS_DIR/debate-build-prompts.sh" r1 "$DEBATE_DIR" "${CLAUDE_PLUGIN_ROOT}"
fi
```

Apply the same per-agent-presence check to the R2 rebuild and a single-file check for synthesis.

This also sidesteps a subtler case: if a previous run's `r1_instructions_*.txt` was generated against a different prompt template (template edit between runs), the plan's `ls` guard reuses a stale file. The set-equality fix doesn't catch that; add a `.template_sha256` marker if you want to be strict. Not a blocker for v1.

---

## LIKELY-CORRECT-BUT-FRAGILE

### F1 — Commit 10: `topic.md` equality comparison works by accident (via command substitution newline-stripping)

Plan §10:

```bash
if [ "$(cat "$dir/topic.md")" = "$topic" ]; then
```

`topic.md` is written with a trailing newline (HEAD line 160: `printf '%s\n' "$TOPIC" > "$DEBATE_DIR/topic.md"`), but `$TOPIC` has none. The comparison still works because bash's `$(...)` strips trailing newlines from command substitution output. This is correct behavior, but fragile — a future refactor that reads via `mapfile`, `read`, or a file-diff-based check will reintroduce the newline and silently miss every match.

**Recommendation:** Document the invariant explicitly with a comment, OR eliminate the asymmetry by writing without the trailing newline:

```bash
# debate.sh line 160
printf '%s' "$TOPIC" > "$DEBATE_DIR/topic.md"
```

Cheap insurance.

### F2 — Commit 6: lockfile liveness race at stage startup

Plan §6 writes the lock *before* `tmux_send_and_submit`. Plan §7 declares a lock stale if `pane_current_command != agent`. In the ~200ms window between pane creation and the agent binary actually starting, `pane_current_command` is `bash` or `sh` (the shell running inside the pane before the agent is invoked). This is fine for a single daemon (commit 7 only runs `clean_stale_locks` at stage start, not concurrently), but `any_live_lock` in commit 10 — called from a **second invocation's** hook — checks only pane existence, not command. So concurrent `/debate <same topic>` within 200ms of the first launch will classify correctly (both see live lock).

The real edge case: commit 11's resume-time composition check runs **after** `detect_available_agents`, which itself invokes smoke tests that can take up to 30s per agent. If a second `/debate <same topic>` fires during those 30s, the first invocation hasn't yet written any lock, and the second won't find one — it proceeds to classify as "incomplete, resume" and runs in parallel. Two daemons racing against the same `DEBATE_DIR`.

**Mitigation — write a "hook in progress" sentinel before detect_available_agents:**

```bash
# debate.sh, right after mkdir of DEBATE_DIR (or right after find_matching_debate returns a resume target):
local hook_lock="$DEBATE_DIR/.hook_in_progress.$$"
printf '%s\n' "pid:$$ started:$(date -Iseconds)" > "$hook_lock"
trap "rm -f '$hook_lock'" EXIT
# ... existing work ...
# before fork:
rm -f "$hook_lock"
# (daemon takes over liveness via per-stage lockfiles)
```

And `any_live_lock` walks `.hook_in_progress.*` too. Not a must-have for v1, but worth adding a comment documenting the race.

### F3 — Commit 8: synthesis early-exit `[ -s synthesis.md ] && exit 0` skips the archive step

Plan §8:

> (...) Synthesis is single-agent so the guard is `[ -s "$DEBATE_DIR/synthesis.md" ] && exit 0`

The daemon's archive loop (current lines 261–277) runs *after* synthesis success. If synthesis.md exists but archive never ran (e.g., daemon was killed between `wait_for_file` returning and `mv` executing), this `exit 0` leaves the directory un-archived forever. The hook-level short-circuit in commit 10 then fires `"/debate: already complete, see synthesis.md"` on every subsequent `/debate <topic>` invocation, but the intermediate files stay visible at top level.

In practice this is caught by commit 10's short-circuit — users see synthesis.md and are fine. But the scan logic that finds "complete" debates relies on `synthesis.md` existing, not on archive being done. So this is only cosmetic, not functional. **Recommendation:** replace `exit 0` with "jump to archive":

```bash
if [ -s "$DEBATE_DIR/synthesis.md" ]; then
  echo "[orch] synthesis already present; skipping to archive"
else
  # pre-allocate synth pane, launch_agent, send_prompt, wait_for_file
  ...
fi
# archive loop runs unconditionally below
```

### F4 — Commit 13: `local` inside `{ ... }` command group — works, but only because the enclosing scope is a function

Plan §13's FAILED.txt block uses `local lock pane_id` inside a `{ ... }` command group. This is legal because `{ ... }` is not a subshell (unlike `( ... )`) — it shares the function's scope. Confirm the block stays inside `wait_for_outputs` after future refactors; if someone moves it to top-level, `local` silently becomes a syntax error. A one-line comment pinning the invariant would save a future reader.

---

## SMALLER ISSUES

### S1 — Commit 3: stale comment in `debate-tmux-orchestrator.sh` header

HEAD line 8 says:

```
#   - $DEBATE_DIR/{topic.md,context.md,agents.txt,r1_instructions_<agent>.txt} all present
```

Commit 3 deletes `agents.txt`. Update the comment to match, else future readers spend time hunting a file that doesn't exist.

### S2 — Commit 16: `/debate-retry` hint on first-invocation failure is misleading

Plan §16:

```bash
emit_block "/debate: needs ≥2 agents, got: ${AVAILABLE_AGENTS[*]}. All fallback models for missing agents failed smoke tests. Next: '/debate-retry' later when quotas reset, or '/debate-abort' to clean up."
```

On a *first* `/debate <topic>` that fails agent detection, no `DEBATE_DIR` exists and commit 5's `invoking_transcript.txt` was never written. `/debate-retry` would then emit `"/debate-retry: no debate found in this conversation"` — confusing for the user who was just told to run it.

**Fix — differentiate first-invocation vs resume-time exhaustion:**

```bash
if [ "${#AVAILABLE_AGENTS[@]}" -lt 2 ]; then
  emit_block "/debate: needs ≥2 agents, got: ${AVAILABLE_AGENTS[*]}. Fallback models exhausted. Wait for quota reset and re-invoke '/debate <topic>'."
  exit 0
fi
```

Keep the `/debate-retry` hint only in the **resume-time** composition-mismatch branch (commit 11), where there actually is a debate to retry.

### S3 — Commit 5 is fully subsumed by commit 10

Plan §5 writes `invoking_transcript.txt` after `mkdir -p "$DEBATE_DIR"`. Plan §10 then gates that exact write (and topic.md, context.md) behind `[ "$RESUMING" = 0 ]`. Commit 5's output is correct only in the fresh-debate branch — which is what commit 10 also produces.

**Recommendation:** fold commit 5 into commit 10 (one commit instead of two). Reduces review surface and eliminates the ordering dance of "move TRANSCRIPT_PATH extraction before line 157". The plan's commit granularity is generally a strength, but this split produces an intermediate state (commit 5 applied, commit 10 not) where `invoking_transcript.txt` is written even on resumes — harmless but incoherent with the eventual invariant.

### S4 — `model-fallbacks.json` with `"claude": []` is misleading

Plan §1:

```json
{
  "gemini": ["gemini-2.5-pro", "gemini-3-flash-preview"],
  "codex": [],
  "claude": []
}
```

Claude never falls back (the Claude CLI uses its own default). Keeping the empty key suggests "Claude has no fallbacks yet, add some" — inviting future misconfiguration. Either:

- Drop the `claude` key entirely and document that absent keys mean "no fallback, smoke-test with default args".
- Or add a comment in the file: `"_note": "claude uses its CLI default; listing here is unused."` (JSON doesn't allow `//` comments).

I'd drop it.

### S5 — Commit 11 doesn't cover "new agent appeared" case

Commit 11 hard-fails only when original ⊄ available. It does not handle available ⊋ original (user authenticated a new agent between runs). The existing debate was built for N agents; introducing a new agent mid-stream changes R2 prompts (every agent critiques every other) and synthesis. Easiest policy: treat "agents gained" as "agents changed" and hard-fail with the same message, pointing user at `/debate-abort` to clean up and re-run fresh.

```bash
# Add after the missing-check in commit 11:
local avail added=""
for avail in "${AVAILABLE_AGENTS[@]}"; do
  case " ${original[*]} " in
    *" $avail "*) ;;
    *) added="$added $avail" ;;
  esac
done
if [ -n "$added" ]; then
  emit_block "/debate: cannot resume, new agents now available:${added}. Run '/debate-abort' to clean up, then re-invoke '/debate <topic>' for a fresh run with the full roster."
  exit 0
fi
```

Cheap insurance against a corrupted mid-debate.

---

## CORRECT AS-PLANNED (explicit acknowledgement so the green bits don't get lost)

- **Commit 4** (archive exclusions) is tight — only 3 file patterns removed from the mv loop, and topic.md/invoking_transcript.txt both remain top-level for the exact-match scan. Line range 266–275 matches HEAD.
- **Commit 7** (`clean_stale_locks`) correctly handles empty globs via `[ -f "$lock" ] || continue`, and the two-gate liveness check (pane exists + pane_current_command matches) is the right semantics.
- **Commit 12** (delete FAILED.txt at resume) is a one-liner that makes the "failed then recovered" state-machine coherent. Nothing to critique.
- **Commit 15** (`/debate-abort`) is correct *given* B2 is fixed. The refuse-on-live-lock path matches the orthogonal design: `tmux kill-window` is the user-facing override.
- **The overall design decisions table** (17 items) is consistent with itself and with the problem statement. I reviewed each row against the commits and found no contradictions.

---

## Assessment & Recommendation

**Ship-readiness of the plan: ~70%.** The design is correct; the snippets need a revision pass.

**Order to fix before implementing:**

1. **B1 — argv-as-array fix in commit 2.** Without this, nothing past commit 2 runs.
2. **B2 — add `/debate-retry` and `/debate-abort` to `scripts/orchestrator.sh` dispatch.** Otherwise commits 14–15 are no-ops.
3. **B3 — replace `debate_main_resume` hand-wave with a real `DEBATE_DIR`-preseed call to `debate_main`.** Otherwise commit 14 doesn't compile.
4. **B4 — per-agent instruction-file presence check, not a set-membership glob.** Otherwise the composition-change resume case hangs for 15 minutes before surfacing failure.
5. **F1, F3, S1, S2, S3, S4, S5** — incorporate during implementation, not as separate commits.

After those five revisions, the plan is ready to execute. The commit ordering is sound (every intermediate state is a working tree with zero broken tests — though the plan would benefit from a line-item "run `bash skills/debate/tests/*.sh` after each commit" invariant; currently it's mentioned once at the top).

**One meta-observation:** the plan is unusually thorough (17 design decisions, explicit out-of-scope section, concrete verification scenarios per commit) — all good. But the code snippets weren't re-checked against the live source of `skills/debate/scripts/debate-orchestrator.sh` and `scripts/orchestrator.sh`. Both of those files are part of the dispatch path for any new slash command, and skipping them is what produced B2 + B3. A final pass that traces "user types `/debate-retry`" from keystroke → `hooks/hooks.json` → `scripts/orchestrator.sh` → `skills/debate/scripts/debate-orchestrator.sh` → `debate.sh:debate_retry_main` would have caught it before the plan was written.
