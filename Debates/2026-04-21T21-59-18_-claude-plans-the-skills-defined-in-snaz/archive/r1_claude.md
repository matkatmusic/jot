# R1 — Independent Analysis of `the-skills-defined-in-snazzy-horizon.md`

**Role:** senior plugin/CLI engineer reviewing a migration plan that moves three
skills (`/todo`, `/todo-clean`, `/todo-list`) from a dotfiles submodule into the
jot plugin. I am reviewing for correctness, UX safety, and maintainability — not
for rewrites.

## Position

**The plan is directionally correct and ~90% merge-ready, but has three concrete
correctness bugs and four UX/operational issues that should be fixed before
shipping.** In priority order:

1. **Blocking bug:** pending-context filename keyed only on `session_id` breaks
   rapid `/todo` reruns in the same session.
2. **Blocking bug:** the foreground `SKILL.md` body has no reliable way to
   discover its own pending file — the plan silently relies on the model knowing
   `session_id`, which it doesn't.
3. **Correctness risk:** numeric-ID race between concurrent workers is labeled
   "low priority" but the claim-sentinel fix is written half in prose, half in
   bash, and never hooked into `scan-existing-todos.sh`'s actual output.
4. UX: vague-idea detection is a pure model heuristic with a fail mode
   (over-asking on terse-but-valid ideas).
5. UX: `/todo-list` post-skill-discovery behavior is undefined when both the
   plugin-side hook AND the dotfiles symlink are live during transition.
6. Ops: no rollback plan.
7. Hygiene: `permissions.default.json.sha256` drift is not enforced by a
   pre-commit check.

Everything else in the plan — file layout, reuse of `tmux-launcher`/
`claude-launcher`/`permissions-seed`, the bg-worker PROCESSED-marker
contract, the split between fg-clarify and bg-enrich — is idiomatic for this
codebase and mirrors proven `/jot` and `/plate` patterns.

## Strengths worth keeping

- **Durable-first write** (input.txt before launch) matches `/jot` and is the
  correct choice; a launcher crash still leaves the user's idea on disk.
- **`emit_block` NOT called in the `/todo` fg-dispatch path** (plan §1 invariant)
  is precisely the right observation — calling it would short-circuit skill
  dispatch. The callout citing `plate.sh::plate_dispatch` as precedent is
  accurate and the strongest single piece of engineering in the plan.
- **Per-invocation `/tmp/todo.XXXXXX` with copied-in hooks** (plan §4) protects
  against mid-run plugin updates. The SessionEnd path-safety guard
  (`/tmp/todo.*|/private/tmp/todo.*`) is tight.
- **`/todo-list` as a python-free-stdlib in-hook renderer** is right. No tmux
  worker for a read-only list; `emit_block` is the whole interaction.
- **`/todo-clean` staying foreground-only** correctly matches its interactive
  UX — `AskUserQuestion` CANNOT execute in a bg worker (no user to answer), so
  porting the existing SKILL.md verbatim is the right call.

## Concrete issues

### Issue 1 (blocking): pending-file name collides on same-session reruns

`todo.sh` (plan §2) writes:

```bash
PENDING_FILE="$STATE_DIR/pending-${SESSION_ID}.json"
...
cat > "$PENDING_FILE" <<JSON
{
  "session_id": "$SESSION_ID",
  ...
  "idea": $IDEA_JSON,
  "timestamp": "$TIMESTAMP",
  ...
}
JSON
```

`session_id` is constant for the entire Claude Code session. If the user runs
`/todo idea-alpha` and then, before the foreground skill body finishes dispatching
(race window: seconds, not millis, because of any `AskUserQuestion` prompt),
runs `/todo idea-bravo`, the second hook invocation **overwrites**
`pending-${SESSION_ID}.json` with idea-bravo's context. idea-alpha is lost:
the fg skill body, when it finally gets to step 1, reads a bravo-shaped
pending file and spawns a bravo worker — but Claude's prompt context still
says `/todo idea-alpha`, so one of the two ideas gets dropped entirely.

This is NOT hypothetical — the verification section §`/todo` — numeric ID
monotonicity explicitly runs `/todo idea alpha` followed by `/todo idea bravo`
and expects `after == before + 2`. If the user triggers them rapid-fire, that
test fails.

**Fix (complete):**

```bash
# todo.sh — replace the single-key pending file with a timestamp-qualified one.
# TIMESTAMP is already set a few lines above and is monotonic because the
# hook runs sequentially in the kernel-scheduled userland order.
PENDING_FILE="$STATE_DIR/pending-${SESSION_ID}-${TIMESTAMP}.json"
```

And in `SKILL.md` step 1 (plan §3), change the discovery rule from
"Read `pending-<session_id>.json`" to:

```
Glob for Todos/.todo-state/pending-<session_id>-*.json, sort by filename
(lexical sort == chronological because TIMESTAMP is zero-padded ISO), pick
the OLDEST unread one, and record which timestamp you chose so that on
subsequent `/todo` dispatches within the same session you read successive
files instead of the same one.
```

Cost: one env var change + a three-line SKILL.md edit. Benefit: correctness
under legitimate user flow.

### Issue 2 (blocking): SKILL.md has no mechanism to learn its own `session_id`

Step 1 of the fg skill body (plan §3) says:

> Read the pending-context file:
> ```
> Todos/.todo-state/pending-<session_id>.json
> ```
> Where `<session_id>` is your current session ID (available in the transcript
> metadata).

**Claude does not know its own `session_id` at tool-call time.** The Agent
SDK exposes transcripts, but the model sees neither `session_id` nor
`transcript_path` in its prompt unless something injects them. The UserPromptSubmit
hook DOES know these (it reads them from stdin JSON), but the hook is explicitly
forbidden from calling `emit_block` in this code path (plan §1 invariant), so
it cannot communicate the session_id to the model.

What the plan is tacitly assuming is that the model will `ls Todos/.todo-state/`,
find the ONE pending file, and read it. That works only because there's
exactly one active `/todo` at a time per session — which is precisely what
Issue 1 violates.

**Fix (complete):** write the pending file to a canonical *per-invocation*
path that the hook prints to a location the model CAN read without knowing
session_id. Two options, either one closes the gap:

**Option A — inject path via an invisible prompt rewrite** (cleanest, matches
how `/plate --done` works today):

```bash
# todo.sh, after writing PENDING_FILE:
# Use additionalContext to hand the pending-file path to the fg claude
# without replacing the user's prompt. See UserPromptSubmit hook JSON shape.
printf '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"%s"}}\n' \
  "TODO_PENDING_FILE=$PENDING_FILE"
exit 0
```

Then SKILL.md §1 reads `$TODO_PENDING_FILE` from the conversation's injected
context rather than reconstructing it.

**Option B — if `additionalContext` isn't available in the current hook contract,**
have the hook write a single well-known pointer file:

```bash
# todo.sh
POINTER="$STATE_DIR/.latest"
printf '%s\n' "$PENDING_FILE" > "$POINTER.tmp" && mv "$POINTER.tmp" "$POINTER"
```

SKILL.md §1 reads `Todos/.todo-state/.latest`, gets the full pending-file
path, then reads that. Still needs Issue 1's timestamp qualifier so concurrent
sessions don't stomp on each other's pointers — use
`$STATE_DIR/.latest-${SESSION_ID}` instead if that matters.

Option A is more correct; Option B is more portable.

### Issue 3 (correctness): claim-sentinel for ID race is not wired up

Plan §"Known Risks" lines 1289–1301 show a sentinel-file atomic-claim pattern:

```bash
sentinel="$REPO_ROOT/Todos/.todo-state/id-${next_padded}.claim"
while ! (set -C; : > "$sentinel") 2>/dev/null; do
  next=$((next + 1))
  next_padded=$(printf '%03d' "$next")
  sentinel="$REPO_ROOT/Todos/.todo-state/id-${next_padded}.claim"
done
printf '%s\n' "$next_padded"
```

But `scan-existing-todos.sh` as shown in plan §6 does NOT include this — it
prints the bare computed next-ID with no claim. The sentinel snippet lives
only in prose under "Known Risks." The plan labels this low priority, but
the verification (§numeric ID monotonicity) expects `after == before + 2`
after two back-to-back `/todo` runs. Two bg workers could both scan, both
compute 005, both overwrite — and the `Todos/*.md` directory would be left
with one file at ID 005 and idea-alpha's or idea-bravo's content, but not
both. The second TODO is silently lost.

**Fix (complete):** fold the sentinel into `scan-existing-todos.sh` as the
default behavior. Full replacement script:

```bash
#!/bin/bash
# scan-existing-todos.sh — atomically claim and print the next 3-digit TODO ID.
set -uo pipefail

REPO_ROOT="${1:?repo_root required}"
TODOS="$REPO_ROOT/Todos"
DONE="$TODOS/done"
CLAIMS="$TODOS/.todo-state"
mkdir -p "$CLAIMS"

max=0
shopt -s nullglob
for f in "$TODOS"/[0-9][0-9][0-9]_*.md "$DONE"/[0-9][0-9][0-9]_*.md \
         "$CLAIMS"/id-[0-9][0-9][0-9].claim; do
  base=$(basename "$f")
  # Strip leading "id-" if present (claim files), then take first 3 chars.
  base="${base#id-}"
  n="${base:0:3}"
  n=$((10#$n))
  if [ "$n" -gt "$max" ]; then max="$n"; fi
done
shopt -u nullglob

next=$((max + 1))
padded=$(printf '%03d' "$next")

# Atomically claim. `set -C` makes `: >` fail if the target exists.
# Race: if two workers compute the same `$next`, only one wins the claim.
while ! (set -C; : > "$CLAIMS/id-${padded}.claim") 2>/dev/null; do
  next=$((next + 1))
  padded=$(printf '%03d' "$next")
done

printf '%s\n' "$padded"
```

The worker instructions (plan §7, step 7) already overwrite input.txt with
`PROCESSED: <path>` as the success signal; add a line:

> 9. After step 8 prints the absolute TODO path, delete the claim sentinel:
>    `${REPO_ROOT}/Todos/.todo-state/id-${NNN}.claim`. If the run fails before
>    step 7, the sentinel is left behind — future scans will skip that ID and
>    the gap is cosmetic but harmless.

Cost: 10 lines of bash, zero new dependencies. Benefit: verification §numeric
ID monotonicity passes reliably.

### Issue 4 (UX): vague-idea heuristic over-asks on terse valid ideas

SKILL.md step 2 (plan §3):

> Inspect the `idea` field. If it is empty, or clearly underspecified (examples
> of vague: "fix that thing", "do the thing", "clean up stuff", "add a
> feature"), use `AskUserQuestion` with 1–3 targeted questions.

This is a pure model judgment call. The failure mode: user types `/todo
skip git-ignored files` — terse but fully specific, probably does NOT need
clarification — and the model decides "this is 4 words, I should ask."
Net effect: the clarify step becomes a chore instead of a safety net.

**Fix (optional, low-risk):** add a two-line heuristic floor BEFORE invoking
`AskUserQuestion`:

```
If the idea is ≥ 6 tokens AND contains both a verb (add, fix, remove,
rename, refactor, test, document, migrate, etc.) and a noun (file path,
function name, feature label), SKIP clarification entirely. Only invoke
AskUserQuestion when the idea is < 4 tokens OR has no verb.
```

Even if the model occasionally under-asks, the bg worker still writes a file
— the TODO just ends up with `## Context` being thinner. That's recoverable;
an annoying over-ask session is not.

### Issue 5 (UX): transition window when dotfiles symlink AND plugin skill are both live

Plan cleanup order (step 1 → step 6) leaves a period where `~/.claude/skills/
matkatmusic_claude_skills_todo-list` (dotfiles symlink) AND the jot-plugin
`todo-list` skill are both registered. Claude's skill-discovery mechanism
will see both; behavior is undefined (likely picks one, might pick wrong).

This is most visible for `/todo-clean`, which is dispatched purely by the
model's skill-name resolution (no UserPromptSubmit hook to short-circuit it).

**Fix:** reorder cleanup to

1. Ship plugin v1.1.0 (publish).
2. IMMEDIATELY (same commit wave): remove the three stale symlinks in
   `~/.claude/skills/`.
3. THEN run `submodule deinit` + `git rm` in dotfiles.
4. Commit dotfiles with both the symlink-cleanup `install.sh` addition and
   the submodule removal.

The plan's step ordering (1=symlinks, 2=submodule, 5=install.sh) actually
matches this, but "step 1 happens automatically on next install.sh run after
step 2" is too loose. Make step 1 a REQUIRED explicit action.

### Issue 6 (ops): no rollback plan

If `/todo` breaks after v1.1.0 ships — say the bg worker's permissions allowlist
is wrong and the worker gets stuck asking for permissions the user never sees —
the plan has no revert recipe. Two lines in the plan would suffice:

```
## Rollback
- Revert plugin to v1.0.0: `claude plugin install --version 1.0.0 jot@matkatmusic-jot`.
- Re-add dotfiles submodule: `git -C ~/Programming/dotfiles checkout HEAD~1 -- .gitmodules
  claude/skills/matkatmusic_claude_skills && git submodule update --init`.
```

### Issue 7 (hygiene): `permissions.default.json.sha256` drift

The plan includes the regen command but doesn't hook it into a test or
pre-commit. A future edit to `permissions.default.json` that forgets the
sha will cause `permissions-seed.sh` to either silently overwrite a user's
local modifications or refuse to seed — both are confusing.

**Fix (complete):** add a trivial test at `skills/todo/tests/permissions-sha-sync.sh`:

```bash
#!/bin/bash
set -euo pipefail
SCRIPTS_DIR="$(cd "$(dirname "$0")/../scripts" && pwd)"
expected=$(shasum -a 256 "$SCRIPTS_DIR/assets/permissions.default.json" \
           | awk '{print $1}')
actual=$(cat "$SCRIPTS_DIR/assets/permissions.default.json.sha256")
if [ "$expected" != "$actual" ]; then
  echo "FAIL: permissions.default.json.sha256 is stale"
  echo "  expected: $expected"
  echo "  actual:   $actual"
  echo "  fix: shasum -a 256 $SCRIPTS_DIR/assets/permissions.default.json | awk '{print \$1}' > $SCRIPTS_DIR/assets/permissions.default.json.sha256"
  exit 1
fi
echo "PASS: sha in sync"
```

Run from CI or the existing `tests/` harness.

## Smaller observations (non-blocking)

- `todo-stop.sh` backgrounds a subshell that calls `tmux_kill_pane` after
  `sleep 0.5`. Functions sourced into the parent are inherited into the
  subshell via `( )` — correct — but worth a one-line comment at the
  `( sleep 0.5 ... ) &` line saying so, because future readers will wonder
  how the subshell knows about `tmux_kill_pane` after SessionEnd wipes the
  tmpdir that held `tmux.sh`.

- `format_open_todos.py` hand-rolled frontmatter parser accepts only flat
  `key: value` lines. If a TODO's `title` ever contains newlines or YAML
  flow-style (`[a, b]`), the parser silently produces wrong output. The
  jot TODO-writer today emits flat single-line titles, so this is latent,
  but worth a comment at the top of the parser saying it is
  "flat-YAML-subset only — if TODOs start using multi-line fields, switch
  to pyyaml."

- Plan §"Verification — /todo-clean" depends on commit `901f78e add /debate
  skill` being in `git log --since=2026-04-15 -- .`. If that commit is ever
  rebased or cherry-picked into a different hash, the verification's PASS
  criterion silently passes against a different commit. Replace with a
  self-contained verification that creates a test commit whose message
  exactly mirrors the test TODO's idea, so the test is insensitive to git
  history churn.

- `.claude-plugin/plugin.json` keyword diff adds `todo-list` and
  `todo-clean` but not `todo`. Probably deliberate because the existing
  `todo` keyword covers it — confirm.

- `/todo-clean` SKILL.md doesn't mention `check_requirements` equivalent.
  If the host lacks `git`, the skill will fail mid-run on the first
  `git log` call. Since this is a pure-model skill there's no shell-side
  preflight — the SKILL.md body should add a first step: "Confirm git is
  available by running `git --version`; if not, reply 'todo-clean requires
  git' and stop."

## Summary

Fix the two blocking issues (pending-file naming + session_id discovery)
and the correctness issue (claim sentinel in `scan-existing-todos.sh`), and
this plan is merge-ready. The structural decisions — foreground-clarify +
background-enrich for `/todo`, pure-foreground for `/todo-clean`, in-hook
formatter for `/todo-list` — are all correct and align with the established
jot/plate/debate patterns. The other four issues are polish; they would be
caught in testing but are cheaper to fix now.

The plan's biggest underrated strength is its explicit acknowledgement of
the `emit_block`-silence invariant and its precedent citation. Its biggest
underrated weakness is assuming the foreground model can learn `session_id`
on its own — which it cannot, and which the fix is small but unambiguous.
