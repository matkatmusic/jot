# R1 — Independent Analysis of `the-skills-defined-in-snazzy-horizon.md`

**Role:** Senior Systems Architect and Security Engineer. I am reviewing the migration of the `/todo`, `/todo-clean`, and `/todo-list` skills into the `jot` plugin, focusing on architectural robustness, concurrency safety, and UX consistency.

## Position

**The plan is well-conceived and aligns with the existing `jot` plugin architecture, but it contains two critical race conditions and one major UX bottleneck that must be addressed to ensure reliability in a high-velocity development environment.**

1.  **Critical Race Condition (Session-Level):** The use of a static `pending-${SESSION_ID}.json` filename will cause data loss if multiple `/todo` commands are issued in rapid succession.
2.  **Critical Race Condition (File-Level):** The `scan-existing-todos.sh` script lacks atomic locking, which can lead to ID collisions when multiple background workers are spawned simultaneously.
3.  **UX/Operational Gap:** The dependency on the model "knowing" its `session_id` to find the pending file is brittle and likely to fail without explicit context injection.

Everything else—the use of `tmux` for background enrichment, the "durable-first" write of `input.txt`, and the lifecycle hook pattern—is excellent and represents a mature approach to plugin design.

---

## Detailed Analysis & Evidence

### 1. The "Double-Tap" Collision (Blocking)

In `skills/todo/scripts/todo.sh`, the pending file is keyed only by `SESSION_ID`:

```bash
# todo.sh lines 84-85
STATE_DIR="$REPO_ROOT/Todos/.todo-state"
PENDING_FILE="$STATE_DIR/pending-${SESSION_ID}.json"
```

Because `SESSION_ID` remains constant for the duration of a Claude session, any `/todo` invocation that occurs before the previous one's foreground `SKILL.md` body deletes the file (Step 4 of `SKILL.md`) will **overwrite** the pending context.

**Scenario:**
1. User: `/todo implement auth` -> Writes `pending-abc.json` (idea: auth).
2. User: `/todo fix css` -> Overwrites `pending-abc.json` (idea: css).
3. Foreground Claude for "implement auth" wakes up, reads `pending-abc.json`, and starts clarifying "fix css". The "auth" idea is gone.

**Solution:** Append the `TIMESTAMP` to the filename to ensure uniqueness per invocation.

```bash
# Fix in todo.sh
PENDING_FILE="$STATE_DIR/pending-${SESSION_ID}-${TIMESTAMP}.json"
```

---

### 2. The ID Collision Race (Correctness)

The plan's `scan-existing-todos.sh` (Section 6) simply finds the max ID and adds one. This is non-atomic.

```bash
# scan-existing-todos.sh (vulnerable logic)
max=0
for f in "$TODOS"/[0-9][0-9][0-9]_*.md ...; do
  n=$((10#$n))
  if [ "$n" -gt "$max" ]; then max="$n"; fi
done
next=$((max + 1))
printf '%03d\n' "$next"
```

If two background workers run this script at the same time (e.g., after the user fires off two quick TODOs), they will both compute the same `next` ID. One will overwrite the other, or both will attempt to write to the same file path.

**Solution:** Implement an atomic claim sentinel.

```bash
# Corrected scan-existing-todos.sh snippet
next=$((max + 1))
padded=$(printf '%03d' "$next")

# Atomically claim the ID using 'set -C' (noclobber)
sentinel="$STATE_DIR/id-${padded}.claim"
while ! (set -C; : > "$sentinel") 2>/dev/null; do
  next=$((next + 1))
  padded=$(printf '%03d' "$next")
  sentinel="$STATE_DIR/id-${padded}.claim"
done
printf '%s\n' "$padded"
```

The background worker should then delete this `.claim` file after successfully writing the `.md` file.

---

### 3. Brittle Discovery of Pending Files

`SKILL.md` instructs the model to:
> Read the pending-context file: `Todos/.todo-state/pending-<session_id>.json`

This assumes the model knows its own `session_id`. While `session_id` is in the transcript, relying on the model to extract it and format a file path is less reliable than providing the path directly.

**Solution:** Use a well-known "latest" pointer or, preferably, inject the path into the conversation via the hook's `additionalContext` if supported by the plugin architecture.

---

### 4. UX Refinement: Over-Clarification

The `SKILL.md` (Step 2) uses a purely heuristic check for "vague" ideas. This risks annoying the user with questions for terse but clear commands (e.g., `/todo update README`).

**Recommendation:** Add a directive to the model to prioritize "implementability" over "word count". If the idea maps to a specific file or known recent commit, skip clarification.

---

## Technical Merits of the Plan

- **Decoupled Clarification:** Running `AskUserQuestion` in the foreground before spawning the worker is the correct UX choice. Background workers cannot interact with the user, so all "missing info" must be gathered upfront.
- **Hook Dispatch Invariant:** The plan correctly identifies that `emit_block` must be avoided in the `/todo` dispatch to allow the foreground skill to fire. This shows a deep understanding of the Claude plugin execution model.
- **Environment Isolation:** Copying lifecycle scripts into a `/tmp` directory ensures that the background worker's execution is not disrupted by plugin updates or directory changes.

## Summary

The migration is architecturally sound and follows established patterns. However, the **concurrency bugs (file collisions and ID races)** are high-risk and will lead to non-deterministic failures. Addressing these with timestamped pending files and atomic ID claims will make the system production-ready.
