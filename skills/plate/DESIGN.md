# /plate — Design Spec

Consolidated design decisions from the grill-me interview session (2026-04-04 → 2026-04-09).
This document captures everything locked in. Unresolved questions are listed at the bottom.

---

## 1. Motivation

`/plate` is a memory-aid skill for tracking work-in-progress when the user switches tasks without committing. It answers the question: *"I was in the middle of something, got pulled away, and now I don't remember what I was doing or which stack of context I should return to."*

Shaped by real transcript analysis of the user's workflow. Key findings from retrospective walk-through:

- Plates represent **uncommitted work the user should have committed but didn't** before changing tasks.
- The failure mode isn't the data model — it's the user's own memory when attention is captured elsewhere.
- Debugging side-quests become plate-worthy when they accumulate enough to divert from the main task.
- A break of 5+ hours is implicitly a task boundary because context is lost.
- Opening a new claude tab for a subtask is conceptually equivalent to `git checkout -b` at HEAD.

---

## 2. Core Mental Model — Stack of Plates

- **Plate** = a snapshot of work-in-progress at the moment you set it down, with auto-captured metadata.
- **Instance** = a claude conversation (identified by its convoID). One instance per claude terminal tab / resumable conversation.
- **Stack** = each instance has a stack of paused/delegated plates. Top of stack = most recently pushed.
- **In-hand plate** = the live conversation. Not stored on the stack; stored implicitly as the active transcript.
- **Queue ≡ Instance.** Each instance has exactly one stack.

### Model (a): Stack contains only paused/delegated plates

The in-hand plate is never on the stack. `/plate` (push) takes the in-hand work, captures it, puts it on the stack, and leaves your hands empty for new work. This matches the physical metaphor: "I set down the plate I was holding to grab a new one."

### Delegation = Branching

Opening a new claude tab to handle a subtask is logically equivalent to `git checkout -b <child>` from the parent's HEAD at that moment. The child instance is a conceptual branch off the parent's work.

---

## 3. Storage Layout

All plate state lives at `<main-worktree>/.plate/`, auto-discovered via:
```bash
dirname "$(git rev-parse --git-common-dir)"
```

This ensures all worktrees of a single repo share one `.plate/` directory and one master `project.json`. `.plate/` is auto-appended to `.gitignore` on first creation.

```
<main-worktree>/.plate/
├── project.json                      # cross-instance relationships (delegation graph summary)
├── instances/
│   └── <convoID>.json                # source of truth: one file per claude instance
├── refs/plates/<convoID>/<plate-id>  # git refs keeping stash commits alive (optional: may live in .git/refs)
├── tree.md                           # derived human-readable view (regenerated lazily)
└── scripts/
    ├── render-tree.sh                # builds tree.md from all instance JSONs + project.json
    └── (other helpers)
```

**Concurrency:** sole user, sub-second parallel `/plate` calls are physically impossible. No locking needed. Direct overwrites everywhere.

---

## 4. Command Surface

All commands are zero-arg or flag-only. The user never types free-text messages after `/plate`.

| Command | Meaning |
|---|---|
| `/plate` | Push: set down the in-hand plate with auto-captured context. Hands empty. Snapshots working tree via `git stash create` + `git update-ref refs/plates/<convoID>/<plate-id> <stash-sha>` — a named ref, NOT an entry on the real `git stash` stack. |
| `/plate --done` | Finalize this instance: iterate all plates since the last git commit and commit each sequentially via stash replay. Replay mechanism: for each plate in push order, `git diff <prev-plate-ref>..<this-plate-ref> \| git apply && git commit -m "<plate synopsis>"`. Reads only the named refs under `refs/plates/<convoID>/`, never the real `git stash` stack. Cascades through the delegation chain. |
| `/plate --drop` | Abandon uncommitted work: save as a git patch file at `.plate/dropped/<convoID>/<plate-id>_<ts>.patch` via `git diff refs/plates/<convoID>/<plate-id> > <patch-file>`, capturing the delta from the top plate's snapshot to the current working tree. Recoverable via `git apply <patch-file>`. Stored **separately** from plate named refs and **NOT included in `--done` stash replay**. Then `git checkout refs/plates/<convoID>/<plate-id> -- .` to restore the top plate's state. Top plate removed from stack[] and its named ref deleted. |
| `/plate --next` | Walk the parent delegation chain upward until finding an ancestor with paused work. Print where to resume next, with an ASCII ancestor tree. |
| `/plate --show` | Regenerate `tree.md` and open in `$EDITOR`. |

(Future flags parked: `/plate --rename`, `/plate --prune` for archiving old completed plates, `/plate --tree` for whole-project view.)

---

## 5. Plate Content Fields

Every plate captures:

| Field | Description | Source |
|---|---|---|
| `plate_id` | Unique identifier (slugified timestamp or UUID) | Generated |
| `pushed_at` | ISO 8601 timestamp of the push | `date -u` |
| `state` | `paused` \| `delegated` \| `completed` | State machine |
| `delegated_to` | Array of child convoIDs (1:N allowed) | Updated on delegation events |
| `push_time_head_sha` | `git rev-parse HEAD` at push time | `git rev-parse HEAD` |
| `stash_sha` | SHA of `git stash create` — represents working-tree state at push | `git stash create` |
| `branch` | Git branch name at push | `git symbolic-ref --short HEAD` |
| `summary_action` | 1 sentence: what was being tried (concrete action) | Background agent |
| `summary_goal` | 1 sentence: broader goal the action served | Background agent |
| `summary_goal_hedge` | `{confidence: low\|med\|high, reason: string}` | Background agent |
| `hypothesis` | Reasoning / why-this-approach | Background agent |
| `hypothesis_hedge` | `{confidence: low\|med\|high, reason: string}` | Background agent |
| `files` | List of files touched since previous plate's `push_time_head_sha` (including intermediate-commit files — see §7.3) | `git diff --name-only` |
| `errors` | Up to 10 error messages from the time window since previous plate, both user-pasted and tool-result-origin | Background agent scan |
| `completed_at` | ISO timestamp, set on `--done` | On finalize |
| `commit_sha` | The git commit that represents this plate, set on `--done` | On finalize |

### Hedging & Reasons

Any field that can be uncertain (hypothesis, summary_goal, maybe others in future) has a companion `_hedge` slot with **confidence** (low/med/high) and a **reason** string explaining *why* the confidence is what it is. A low-confidence hypothesis isn't just `(inferred — confirm?)`; it must say *why* it was inferred (e.g., "user never explicitly stated motivation; derived from phrase 'I want to try' in U034").

### Rule: Every warning/hedge field MUST include its reason.

---

## 6. Instance (Source of Truth) Schema

`.plate/instances/<convoID>.json`:

```json
{
  "convo_id": "abc-123-...",
  "label": "auto-derived from stack[0].summary_action",
  "label_source": "auto | manual",
  "branch_at_registration": "feat/auth",
  "cwd": "/Users/matkatmusicllc/Programming/dotfiles",
  "created_at": "2026-04-09T12:34:56Z",
  "last_touched": "2026-04-09T13:45:12Z",

  "parent_ref": {
    "convo_id": "parent-convoID" | null,
    "plate_id": "parent-plate-id" | null
  },

  "rolling_intent": {
    "text": "one sentence of what user is currently trying to accomplish",
    "snapshot_at": "2026-04-09T13:40:00Z",
    "confidence": "low | medium | high"
  },

  "drift_alert": {
    "pending": false,
    "message": "",
    "generated_at": null
  },

  "stack": [
    {
      "plate_id": "2026-04-09T13-12-34_refactor-auth",
      "pushed_at": "2026-04-09T13:12:34Z",
      "state": "paused | delegated",
      "delegated_to": ["child-convoID", "..."],
      "push_time_head_sha": "abc123",
      "stash_sha": "def456",
      "branch": "feat/auth",
      "summary_action": "...",
      "summary_goal": "...",
      "summary_goal_hedge": {"confidence": "med", "reason": "..."},
      "hypothesis": "...",
      "hypothesis_hedge": {"confidence": "low", "reason": "..."},
      "files": ["src/auth.go", "config/auth.yaml"],
      "errors": ["Error: ..."],
      "completed_at": null,
      "commit_sha": null
    }
  ],

  "completed": [
    {
      "...": "same shape as stack entry, with the final two fields populated:",
      "completed_at": "2026-04-09T14:00:00Z",
      "commit_sha": "ghi789"
    }
  ]
}
```

**`cwd` field:** the absolute filesystem path of the instance's current working directory, captured at plate push time from the hook's input (`cwd` is present on every `UserPromptSubmit` transcript entry). Updated on every `/plate` push so the most recent value reflects where the instance was last active. Used by `/plate --done` and `/plate --next` to produce resume commands of the form `cd <cwd> && claude --resume <convoID>`.

**`completed_at` and `commit_sha` on `stack[]` entries:** always `null` while a plate sits in `stack[]`. These two fields are only populated when the plate is moved from `stack[]` into `completed[]` during `/plate --done` — at which point they record the completion timestamp and the git commit SHA produced by the stash replay. Treating them as explicit `null` rather than absent keeps the schema uniform across both arrays (same keys, just different values) so consumers never need to branch on field presence.

---

## 7. Rules & Semantics

### 7.1 Baseline for `files` field

- **First plate of a session:** file list = currently uncommitted vs `HEAD`.
- **Plate N ≥ 2:** file list = `(files changed between plate-(N-1).push_time_head_sha and current HEAD) UNION (currently uncommitted)`. Every file touched since the previous plate, including files that were committed in between.

### 7.2 Baseline for `errors` field

Extract errors from the time window spanning from the previous `/plate` push (or session start if none) to the current push. Max 10 most-recent within that window. Includes both user-pasted errors and tool-result-origin errors.

### 7.3 Git stash mechanism for commit replay

On every `/plate` push, the hook runs:
```bash
STASH_SHA=$(git stash create)
git update-ref "refs/plates/<convoID>/<plate-id>" "$STASH_SHA"
```

This creates a stash commit (without modifying the working tree) and keeps it alive via a named ref.

On `/plate --done`:
1. Walk `stack[]` in reverse order (oldest first).
2. For each plate, compute `git diff <prev plate stash_sha OR push_time_head_sha>..<this plate stash_sha>` and `git apply` it.
3. Create a commit with the plate's synopsis as the message.
4. Final commit captures any work done after the last plate.
5. Move plates from `stack[]` to `completed[]` with `completed_at` and `commit_sha` filled in.
6. Delete the stash refs under `refs/plates/<convoID>/`.

**Commit message format.** Each replay commit uses a structured title + body:

```
[plate] <plate.summary_action>

Goal: <plate.summary_goal>

Hypothesis: <plate.hypothesis>
  (confidence: <hypothesis_hedge.confidence>; reason: <hypothesis_hedge.reason>)

Errors encountered during this plate:
  - <errors[0]>
  - <errors[1]>
  ...

plate-id: <plate_id>
pushed-at: <pushed_at ISO timestamp>
```

The `[plate]` prefix marks these commits as plate-replayed (filterable via `git log --grep="^\[plate\]"`) and reminds the user to squash before pushing if they want a clean history. The `Goal`, `Hypothesis`, and `Errors` sections are omitted when their underlying plate fields are empty. The trailer (`plate-id` + `pushed-at`) is always present so a future tool can correlate commits back to plate metadata if the JSON archive is lost.

### 7.4 `/plate --drop` mechanics

The patch must capture **all** abandoned work — tracked modifications, staged changes, AND untracked files — so nothing valuable is lost to git formalities. This is done by snapshotting the full current state into a temporary stash commit (which `git stash create -u` builds in-memory without touching the stash stack, the index, or the working tree), then diffing from the plate ref to that snapshot.

```bash
# Build a full snapshot of the current state including untracked files.
# git stash create -u produces a dangling commit whose tree captures:
#   - tracked modifications
#   - staged changes
#   - untracked files (because of -u)
# It does NOT modify the stash stack, the index, or the working tree.
TEMP_SNAPSHOT=$(git stash create -u 2>/dev/null)

PATCH_FILE=".plate/dropped/<convoID>/<plate-id>_$(date +%s).patch"
mkdir -p "$(dirname "$PATCH_FILE")"

if [ -n "$TEMP_SNAPSHOT" ]; then
  # Full delta from plate snapshot → current state, including untracked files
  git diff "refs/plates/<convoID>/<plate-id>" "$TEMP_SNAPSHOT" > "$PATCH_FILE"
else
  # Working tree matches HEAD exactly — nothing to save
  : > "$PATCH_FILE"
fi

# Restore top plate state into the working tree (tracked files only)
git checkout "refs/plates/<convoID>/<plate-id>" -- .

# Remove top plate from stack[] and delete the named ref
git update-ref -d "refs/plates/<convoID>/<plate-id>"
```

Does NOT touch HEAD or destroy commits. Abandoned work is recoverable via `git apply <patch-file>` (or `git apply --3way` for merge conflicts). The patch file lives under `.plate/dropped/` and is **separate from plate named refs** — it is **not read by `/plate --done` stash replay**.

**Caveat:** after `git checkout`, any untracked files that existed at drop time remain in place in the working tree. They are also captured in the patch (because of the `-u` flag on `git stash create`), so re-applying the patch later is a no-op for those files (the content already matches). If the user wants a "clean" restore back to the exact plate state, they can run `git clean -fd` manually afterward — but by default the drop mechanism is conservative and leaves stray files in place rather than risk deleting unrelated work.

**Edge case — `--drop` with empty stack:** if the user runs `/plate --drop` and `stack[]` is empty (no plates were ever pushed in this instance, or all have been `--done`'d), the command exits with an error:

```
Error: no plates on the stack to drop.

If you want to discard all uncommitted changes and reset to HEAD instead, run one of:
  git stash push -u                            (recoverable via `git stash pop`)
  git reset --hard HEAD && git clean -fd       (destructive — no recovery)
```

The error explicitly suggests the safer recoverable command first. Plate does NOT silently no-op (the user invoked a destructive verb and expects feedback) and does NOT auto-perform the destructive reset (overloading `--drop` with implicit semantics is too easy to misuse).

---

## 8. Discovery & Registration

### 8.1 Hook three-way gate

On every `/plate` prompt, the `UserPromptSubmit` hook checks:

1. **This session has plate state** (`.plate/instances/<convoID>.json` exists) → suppress the prompt, spawn background-agent push. Fully silent.
2. **No state for this session, AND no plate state anywhere in this repo** → suppress prompt, background-register-as-top-level + push. Fully silent.
3. **No state for this session, but other instances in this repo DO have state** → don't suppress; let `/plate` reach the foreground. The skill body instructs claude to call `AskUserQuestion` with the parent dropdown, register + push, then respond with one-line confirmation.

### 8.2 Parent selection dropdown

When gate path 3 fires, the skill body first runs `bash .plate/scripts/list-paused-plates.sh` which globs all `.plate/instances/*.json` and prints the candidate list. Claude then calls `AskUserQuestion` with the question text *"Pick a parent plate (or top-level)"* and one option per candidate. Row format:

```
Top-level (no parent)
Instance X → "first plate synopsis" (paused Nm ago)
Instance Y → "another synopsis" (paused Nh ago)
...
```

Rows = one per **paused plate** across all instances in the repo. Completed plates are excluded. Each row's label is `<Instance label> → "<plate summary_action>" (paused Xm ago)` — instance first so the user can mentally locate "which tab," then disambiguate by what that tab was doing.

**Edge case — 0 candidates.** If the repo has instance files but no paused plates exist (all are completed or delegated), `list-paused-plates.sh` returns only the implicit "Top-level" row. In this case the skill body **skips the `AskUserQuestion` call entirely** and silently auto-registers as top-level. There is no real choice to present; forcing a confirmation is busywork.

**Edge case — 1+ candidates.** Always show the prompt. Even with a single paused plate, auto-attaching is risky (the candidate may be unrelated to the new convo).

### 8.3 Registration write-back

If parent chosen: write `parent_ref` to this instance's JSON AND add this convoID to the parent plate's `delegated_to[]` AND flip the parent plate's `state` from `paused` to `delegated`.

If top-level: write this instance's JSON with `parent_ref = null`.

Either way, proceed with the push **in the same skill-body invocation** (no two-step "register then re-run `/plate`" friction). The skill body responds with a one-line confirmation: `📌 plate registered + pushed: <synopsis>`.

---

## 9. Delegation (1:N) and Cascade

### 9.1 1:N allowed

A single parent plate may have multiple children. The parent stays in `delegated` state as long as **any** child is still alive and not `--done`.

### 9.2 Child `--done` cascades up

When a child instance runs `/plate --done`:
1. The child's hook writes the sequential commits for its own stack.
2. The hook then walks `parent_ref` upward. For the parent plate:
   - Remove this convoID from `delegated_to[]`.
   - If `delegated_to[]` becomes empty, flip the parent plate's `state` from `delegated` back to `paused`.
   - Otherwise, leave as `delegated`.
3. The walk stops at the first ancestor; cascading further up only happens when those ancestors themselves `--done`.

### 9.3 Parent `--done` with open children

If a parent runs `/plate --done` while it still has delegated plates whose `delegated_to[]` contains live children:
- Foreground-inject `AskUserQuestion`: `[Cancel] [Orphan children] [Keep link intact — commit anyway]`.
- **Orphan children:** parent commits; children's `parent_ref` becomes dangling (`convoID` still there but refers to a completed plate). Warning logged.
- **Keep link intact:** same as orphan but without the warning; acceptable if the user intentionally wants a completed ancestor.
- **Cancel:** abort the `--done`.

---

## 10. Active Tab Detection

`.plate/instances/<convoID>.json` has a `last_touched` field updated on every `UserPromptSubmit` hook firing. The `tree.md` renderer sorts instances by `last_touched` descending — the most-recently-typed-in instance floats to the top.

No OS-level focus detection. No heartbeats. Typing is the only active signal.

---

## 11. Drift Detection

### 11.1 Anchor: rolling-intent snapshot

The background agent generates a one-sentence *"what is the user currently trying to accomplish?"* and stores it in `rolling_intent.text`. This is the anchor recent turns get compared against.

### 11.2 Cadence

- **Snapshot refresh:** time-based, every 5 minutes of active conversation. Checked lazily at each `/plate` push — if `now - rolling_intent.snapshot_at > 5min`, regenerate.
- **Drift check:** only on `/plate` push (piggybacks on the background agent that's already running). Not on every `UserPromptSubmit`.

### 11.3 Nudge surface

When drift is detected, `drift_alert.pending` is set to `true` with a one-line message. The next `UserPromptSubmit` hook reads the flag and injects a system note telling claude to prefix its reply with:

> ⚠ This conversation has drifted from your intent: `<rolling_intent.text>`. Continue or `/plate` to capture & reset?

Flag cleared on emit (ack-once). Re-arms only if the rolling intent snapshot updates.

### 11.4 Check algorithm

One-shot micro-LLM call with the rolling-intent text + last ~3 conversation turns. The judge prompt asks *"is the user still working on the stated intent?"* and returns a structured verdict. Simpler than embeddings, more robust than keyword overlap. Reuses the background-agent infrastructure.

**Strictness: STRICT.** The judge only fires when it is highly confident the user has drifted. False positives erode trust fast — once the user sees a single wrong nudge, they will start ignoring all subsequent ones, and the feature is dead. False negatives are tolerable because real drift gets caught eventually via other signals (long time gaps, the user's own `/plate` cadence, etc.). When in doubt, the judge stays silent.

**Self-verification:** the background agent that generates `summary_action`, `summary_goal`, `hypothesis`, and `rolling_intent.text` MUST double-check its own output against the source transcript and be at least **90% certain** of each value before returning. If self-checked confidence falls below 90% for any field, the agent sets that field's `_hedge.confidence` to `low` (or `medium`) and writes a concrete `_hedge.reason` (e.g., "user never explicitly stated the goal; inferred from a single phrase in turn N"). This rule applies to every per-plate background invocation, not just drift detection.

---

## 12. Cancelled / resubmitted prompt deduplication

**Not time-based.** A user may legitimately cancel a prompt, switch conversations for hours, return, and resend — time-windowed dedup would falsely merge these cases.

**Not text-based.** A resubmit may be a revision with different text, not an identical copy — matching on message content misses real cancel-and-revise cases.

**Tree-structure-based.** Claude Code represents cancelled-and-resubmitted prompts as **branching siblings in the conversation tree**. When the user cancels a submission (Ctrl-C, network retry, edit-before-send, any other reason) and then sends a new prompt, both messages appear in the `.jsonl` transcript with the **same `parentUuid`**. The assistant only responds to the later one. Each user-message entry in the transcript has these relevant fields:

- `uuid` — unique ID of this user message
- `parentUuid` — ID of the message this one branches from (the prior turn it's answering)
- `promptId` — unique per client submission (different across cancel/resubmit)
- `timestamp` — ISO 8601

**Rule:** if two consecutive user messages in the transcript share the **same `parentUuid`**, the earlier one was cancelled/superseded. The `/plate` hook treats only the **LATER** message as the real turn and ignores the earlier one. No time window, no text match, no Ctrl-C marker required.

**This handles all cancel scenarios uniformly:**

| Scenario | Detection |
|---|---|
| Ctrl-C then identical resend | Same `parentUuid`, identical text |
| Ctrl-C then revised resend | Same `parentUuid`, different text |
| Network retry / client auto-resubmit | Same `parentUuid`, identical text |
| Fat-finger double-submit | Same `parentUuid`, identical text |
| Intentional re-type as a new turn | **Different** `parentUuid` — the conversation tree advanced between sends, so both count |

**Retrospective example:** U036 (line 354, 532 chars) and U037 (line 357, 679 chars) in transcript 01833f61 both have `parentUuid: 25b1253b-72a1-4a17-9a76-2b10649948b4`. They are cancel-and-revise siblings: U036 was the first attempt, U037 is a 147-character revision with more detail. The assistant at line 358 responds to U037 (via U037's uuid as its parent), not U036. Under this rule, U036 is de-duplicated and only U037 counts as a real user turn. The `[Request interrupted by user for tool use]` marker at line 353 is for an *earlier* tool-use interrupt, not the U036→U037 transition — the parentUuid equality is the authoritative signal.

**Supporting signal:** `[Request interrupted by user]` / `[Request interrupted by user for tool use]` markers still appear in the transcript and can help diagnose *why* a cancel happened, but they are not required for dedup detection. `parentUuid` equality alone is sufficient.

---

## 13. Render Architecture

`tree.md` is a derived view, not a source of truth. Produced by `scripts/render-tree.sh` which reads:
- All `.plate/instances/*.json` files
- `.plate/project.json`

And renders a nested markdown tree.

**When does `render-tree.sh` run?** On every `/plate` push as part of the background work (cheap, jot-style) AND standalone-callable from anywhere (`render-tree.sh` has no side effects beyond writing `tree.md`).

**Example `tree.md` output** (box-drawing tree, produced by `render-tree.sh`):

```
# Plate Tree — /Users/matkatmusicllc/Programming/dotfiles
Last rendered: 2026-04-09T14:00:00Z

Instance D  ← active tab                  (parent: Instance C → subtask 1)
├─ [ ] "sub-subtask β"                    (current — top of stack)
└─ [ ] "sub-subtask α"                    (paused, just now)

Instance C                                 (parent: Instance A → task 3)
└─ [ ] "subtask 1"                        (delegated → Instance D ↑)

Instance A
├─ [ ] "task 3 — refactor auth"           (delegated → Instance C ↑)
├─ [ ] "task 2 — extract config loader"   (paused 12m ago)
└─ [ ] "task 1 — rename TaskQueue"        (paused 47m ago)

Instance B
└─ [ ] "task A"                           (current, nothing on stack)

---
### Completed (click to expand)
<details>
...
</details>
```

**Example `/plate --done` stdout output** (ancestor chain + resume pointer, printed to stdout, separate from `tree.md`):

```
✔ Committed 3 plates in Instance D → main (sha1, sha2, sha3)

Instance A
└─ task 3 [delegated → C]
   └─ Instance C                    ← ▶ RESUME HERE
      └─ subtask 1 [paused — just un-delegated]
         └─ Instance D (done ✔)

To resume here, open a new terminal and run:
  cd /Users/matkatmusicllc/Programming/dotfiles && claude --resume <C-convoID>
```

Both outputs use the same box-drawing idiom (`├─`, `└─`). `tree.md` shows instances as top-level blocks with their plate stacks nested beneath; `/plate --done` walks the delegation chain vertically, alternating instance → plate → instance → plate, and appends a full `cd <project-root> && claude --resume <convoID>` command so the user can resume from any new terminal without needing to remember the project path.

The `<project-root>` value in the resume command comes from the instance's `cwd` field (added in §6), captured at plate push time from the hook's input (`cwd` is present on every `UserPromptSubmit` transcript entry).

---

## 14. Open Questions

All design decisions from §14 #0–#9 have been synthesized into the body of this document (§3, §4, §7, §8, §11, §13, and the Implementation Notes section). Items #10–#12 below are the only remaining open items: #10 is parked per user, #11 and #12 are investigation tasks rather than design questions to resolve.

10. **Future: should `/plate --done` auto-create a git branch when a child instance is spawned?** *Parked per user.* Defer until the basic plate flow is implemented and observed in real use; the answer depends on whether unbranched-but-delegated work causes friction in practice.

11. **Making plate state committable to the repository** — currently `.plate/` is auto-gitignored (§3), so patches, instance state, and stash refs live only on the computer that created them. **Problem:** if you push a plate or generate a `--drop` patch on Computer A, you cannot resume from Computer B or apply the patch elsewhere — the files never leave A. Investigate which parts of `.plate/` should become committable (`instances/*.json`? `dropped/*.patch`? named refs under `refs/plates/<convoID>/`?) and the implications: (a) git ref transfer — stash commits under `refs/plates/*` are dangling unless explicitly pushed via `git push origin 'refs/plates/*:refs/plates/*'`; (b) `tree.md` is derived and should remain gitignored; (c) sensitive-context leakage — plate synopses may contain info the user doesn't want in git history; (d) merge conflicts on shared repos (though currently sole user).

12. **Programmatic terminal-color tinting on delegation** — when a child instance is spawned (or when the user is in a delegated state), it would be useful to tint the IDE terminal pane's color so the user can visually distinguish parent from child tabs at a glance. Investigate whether VS Code / Antigravity expose an API or extension hook to set the terminal's background or accent color programmatically (per-pane or per-session), and whether claude's hooks can trigger that color change.

---

## Implementation Notes

### Languages

Hybrid shell + python. Shell for hook glue and git command invocation; python for JSON read/write and transcript parsing. Mirrors `/jot`'s split.

### Eventual home

The `jot` plugin repository (currently a submodule at `claude/skills/matkatmusic_claude_skills/`). Plate ships alongside jot when implemented.

### Hook event and dispatch

`/plate` and its variants are intercepted at the `UserPromptSubmit` hook. The hook regex matches `^/plate(\s+(--done|--drop|--next|--show))?$`. Dispatch by variant:

| Variant | Hook behavior | Skill body role |
|---|---|---|
| `/plate` (push) | Three-way gate (§8.1). Paths 1 & 2 suppress + spawn background agent. Path 3 lets the prompt through. | Skill body is empty for paths 1 & 2 (never executes). For path 3, skill body runs `list-paused-plates.sh`, calls `AskUserQuestion`, registers, and runs the push script — all in one shot. |
| `/plate --done` | Pass through (Bash + may trigger `AskUserQuestion` for orphaned children, see §9.3). | Skill body runs `bash .plate/scripts/done.sh`; user sees the ancestor-chain output naturally as a Bash tool result. |
| `/plate --drop` | Suppress + run `bash .plate/scripts/drop.sh` in the background. No user-visible conversation output. | Empty (never executes). |
| `/plate --next` | Pass through. | Skill body runs `bash .plate/scripts/next.sh`; user sees the chain walk + resume command as Bash output. |
| `/plate --show` | Pass through. | Skill body runs `bash .plate/scripts/show.sh`, which regenerates `tree.md` and opens it in `$EDITOR`. |

### Background agent invocation (jot pattern, separate session)

Reuse jot's exact tmux+claude mechanism. One tmux session named `plate` (separate from jot's `jot` session) acts as a container for background work. Each `/plate` invocation that needs LLM work creates a **new window** inside the `plate` session running a **fresh `claude` process**; the window's `cwd` is set via `tmux -c "$CWD"`. The hook writes an `INPUT_FILE` with the job payload; a per-window SessionStart hook reads it and uses `tmux send-keys` to trigger the new claude with the prompt *"Read \<INPUT_FILE\> and follow instructions"*. A per-window Stop hook verifies completion and cleans up. See `jot.sh` and `jot-session-start.sh` / `jot-stop.sh` for the canonical implementation.

### Cross-plate access (works with one-agent-per-invocation)

The per-plate agent has full read access to the entire `.plate/` directory. Even though each agent only WRITES to its own instance's JSON, it can READ any other instance's JSON during the job. This enables current and future cross-plate operations:

- **Cascade on `/plate --done`** — deterministic shell script walks parent chain and rewrites other instance JSONs directly (no LLM needed).
- **Path 3 parent dropdown** — `scripts/list-paused-plates.sh` globs all instance files (no LLM needed).
- **`tree.md` rendering** — `render-tree.sh` reads all instance files (no LLM needed).
- **Future cross-plate semantic drift** — a per-plate agent can include other instances' `rolling_intent.text` values in its drift-analysis prompt for project-wide drift detection. The one-agent-per-invocation constraint applies to LLM execution, not to filesystem access, so this is implementable without changing the architecture.

### Hook-side git snapshot (factored)

The `git stash create` + `git update-ref` work runs synchronously inside the hook via a factored script `scripts/snapshot-stash.sh` so it can be relocated to the background agent later if push latency becomes a problem. Synchronous execution guarantees snapshot fidelity (no risk of working-tree drift while waiting for the background agent to start).

### Background agent self-verification (≥90% confidence rule)

The agent's prompt MUST instruct it to double-check its own extracted `summary_action`, `summary_goal`, `hypothesis`, and `rolling_intent.text` fields against the source transcript before returning. The agent must be **at least 90% certain** of each value. If self-checked confidence falls below 90% for any field, the agent sets that field's `_hedge.confidence` to `low` (or `medium`) and writes a concrete `_hedge.reason` describing what made it uncertain (e.g., "user never explicitly stated the goal; inferred from a single phrase in turn N"). This rule applies to every per-plate background invocation. See also §11.4.

### Background agent prompt structure

Single-prompt + structured-JSON-output design. The background agent receives one prompt covering all extraction tasks (synopsis, hypothesis, files, errors, rolling-intent) and returns one JSON blob with all fields populated, including the `_hedge` companion fields. Modern LLMs handle multi-field structured output reliably; one LLM call per push keeps latency low; if any field is wrong, the user sees the hedge field's `confidence: low` + `reason` and can correct on pop.

### SessionStart freshness check on resume

When a user runs `claude --resume <convoID>` on an existing plate-tracked instance, the SessionStart hook performs a freshness check:

- Verify that all `stash_sha` refs under `refs/plates/<convoID>/` still exist (warn if GC'd).
- Verify that `push_time_head_sha` values are still reachable in the branch (warn if rewritten).
- Update `last_touched`.
- Clear stale `drift_alert.pending` flags.
- Re-render `tree.md`.

This catches reachability bugs early without requiring user action.

---

## 15. Retrospective Walk-Through Findings (Source: jot transcript 01833f61)

Key insights from walking through real task-switches in the user's transcript:

- **U069 (new-feature-idea)**: User got a new idea mid-implementation (tmux visibility for background claude). Would have `/plate`d before pivoting. Never returned to the old task — confirmed drift failure mode.
- **U042 (debugging side-quest)**: Brief investigation in a sibling repo to collect test data. Would NOT have `/plate`d — not every pivot is a plate moment. Threshold: side-work must accumulate enough to divert attention.
- **U036/U037 (lost focus)**: User explicitly said "I have lost the focus of what we're trying to solve here." Ctrl-C resend at 32-second gap. This is the recovery moment; auto-drift-detection is meant to prevent this.
- **U046 (5h break + new approach)**: After a long break, came back with a new architectural direction. Would have `/plate`d before the break. Never returned to the permission-error debugging. Breaks are implicit task boundaries.

These cases drove the decisions around:
- Plate content capturing *uncommitted work* + *hypothesis* + *errors* (not just conversation)
- Two-sentence summaries (action + broader goal), because the broader goal is forgotten fastest after breaks
- Drift detection based on rolling intent, not just top-of-stack
- Inline nudge surface (not silent) so drift is actually caught
