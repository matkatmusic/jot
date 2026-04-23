=== USER (turn 1) ===
Are all questions needed for creating the plan for this feature answered?
=== END USER ===

=== ASSISTANT ===
One gap I missed: **archive step vs the exact-match scan.**

Current orchestrator archives `topic.md` into `<DEBATE_DIR>/archive/` on completion. So the exact-match scan `Debates/*/topic.md` would miss completed debates → Q6 residual "already done" short-circuit wouldn't fire.

Two fixes:

- **(a)** Stop archiving `topic.md` (and `agents.txt`, `invoking_transcript.txt`) — keep identity files at top level forever. Archive only round artifacts (R1/R2 outputs, instruction files, orchestrator.log).
- **(b)** Scan both locations: `Debates/*/topic.md` and `Debates/*/archive/topic.md`.

**Recommend (a).** Identity files are cheap, staying visible aids debugging; scan stays simple.

Pick (a) or (b) — then I believe we're done.
=== END ASSISTANT ===

=== USER (turn 2) ===
it would be great to get rid of agents.txt generation completely.
=== END USER ===

=== ASSISTANT ===
Doable. `agents.txt` has one job: record the original composition for resume-time comparison. `r1_instructions_<agent>.txt` already serves as a de-facto composition marker — debate.sh writes one per agent synchronously before forking.

Replace with:

- **Fresh debate**: debate.sh passes `DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}"` to the daemon via env (already the pattern used by `debate-build-prompts.sh`). No disk write.
- **Resume**: hook derives original composition from `ls $DEBATE_DIR/r1_instructions_*.txt` → extract `<agent>` from each filename. Compare today's `AVAILABLE_AGENTS` against that set → hard-fail if mismatch. Pass `DEBATE_AGENTS` via env.
- **Daemon**: replace the `while read < agents.txt` loop with `IFS=' ' read -r -a AGENTS <<< "$DEBATE_AGENTS"`.

`r1_instructions_<agent>.txt` becomes the de-facto identity marker. `debate-build-prompts.sh` already consumes `DEBATE_AGENTS` — no change.

---

Design is complete. Ready to start implementation on your go.
=== END ASSISTANT ===

=== USER (turn 3) ===
during archive step, ignore topic.md.  

regarding agents.txt, if agent availability is detected at runtime, there is no need for the file.  therefore, stop generating it.
=== END USER ===

=== ASSISTANT ===
Confirmed. Full design:

**Identity files kept at top level (never archived):** `topic.md`, `invoking_transcript.txt`, `synthesis.md`. No `agents.txt` — deleted entirely.

**Composition marker:** `r1_instructions_<agent>.txt` presence tells us who was in the original debate.

**Runtime state:** `AVAILABLE_AGENTS` / `GEMINI_MODEL` / `CODEX_MODEL` detected by hook, passed to daemon via env (`DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}"`).

**Lockfiles:** `.<stage>_<agent>.lock` containing `debate:<pane_id>`. Created after `new_empty_pane`, deleted in `wait_for_outputs` on output flip. Stale = pane gone OR `pane_current_command` ≠ agent binary.

**Skip logic (daemon):** per stage, per agent — skip launch if `<stage>_<agent>.md` exists; skip + wait if live lock; clean stale lock and launch otherwise.

**Dir selection:**
- `/debate <topic>` → exact `topic.md` match, most recent wins → complete: short-circuit with "already done" message; live: "already running" + tmux target; incomplete: resume
- `/debate-retry` → scan `invoking_transcript.txt` for today's `transcript_path`, most recent wins
- `/debate-abort` → same scan; live: refuse + show kill command; else `rm -rf`

**Fallback models:** `skills/debate/scripts/assets/model-fallbacks.json`, tried in order at smoke-test time. All exhausted → hard fail with `/debate-retry` / `/debate-abort` hint.

**Mid-debate failure:** daemon writes human-readable `FAILED.txt` (include pane capture) and exits. No push notification.

**Companion skills:** `skills/debate-retry/` and `skills/debate-abort/`, pass-through SKILL.md. Dispatch extended in `debate.sh` hook: `case "$PROMPT" in /debate) ...; /debate-retry) ...; /debate-abort) ...; esac`.

Ready to implement on your go.
=== END ASSISTANT ===

=== USER (turn 4) ===
write a plan file for the feature
=== END USER ===

=== ASSISTANT ===
Plan written to `plans/debate-resume.md`. 16 tiny commits, ordered so each intermediate state is coherent. Captures all 17 design decisions from the grill session, the verification scenario, and explicit out-of-scope items.
=== END ASSISTANT ===

=== USER (turn 5) ===
add code snippets to plan where code changes will occur.  do not show "before: " "after: ".  show only changed code and specific line numbers.
=== END USER ===

=== ASSISTANT ===
Plan updated. Each commit now has a concrete code snippet anchored to specific file paths + line numbers (against current HEAD). 16 commits total, no "before/after" framing — just the code that lands.
=== END ASSISTANT ===
