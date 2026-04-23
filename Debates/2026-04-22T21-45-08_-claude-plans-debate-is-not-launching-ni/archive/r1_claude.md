# Review: `~/.claude/plans/debate-is-not-launching-nifty-reddy.md`

## Position

The plan is **directionally correct** (a fresh per-invocation tmux session cleanly fixes the `spawn_terminal_if_needed` short-circuit) but **not safe to execute as written**. It has four substantive bugs — a broken race-tolerance claim, a stale `debate:` session prefix left in three user-facing messages, a missed positional-arg update in the test harness, and at least two incorrect line-number citations — plus one shaky root-cause claim. All of these would bite on execution.

Below, each objection cites the file/line/snippet.

---

## 1. Race-tolerance claim is wrong — the tmux helpers do not fail on duplicate session, they silently attach

The plan writes (lines 25–31 of the plan):

```bash
debate_next_session_name() {
  local n=1
  while hide_errors tmux has-session -t "debate-$n"; do
    n=$((n + 1))
  done
  printf 'debate-%d\n' "$n"
}
```

…and justifies the TOCTOU window with:

> Small race (two /debate calls picking the same N simultaneously) is tolerable: `tmux_new_session` in `ensure_session` will fail on the duplicate and the hook will surface that via its ERR trap.

That is not what `tmux_ensure_session` does. Actual code (`common/scripts/tmux-launcher.sh:12-29`):

```bash
tmux_ensure_session() {
  local session="$1" window="$2" cwd="$3" keepalive_cmd="$4" keepalive_title="$5"
  if ! tmux_has_session "$session"; then
    tmux_new_session "$session" -n "$window" -c "$cwd" "$keepalive_cmd"
    ...
    return 0
  fi
  if ! tmux_window_exists "$session" "$window"; then
    tmux_new_window "$session" "$window" -c "$cwd" "$keepalive_cmd"
    ...
    return 0
  fi
  tmux_ensure_keepalive_pane "${session}:${window}" "$cwd" "$keepalive_cmd" "$keepalive_title"
}
```

Tracing two parallel `/debate` calls that both pick `n=1`:

1. Call A: `tmux_has_session debate-1` → **false** → `tmux_new_session debate-1` succeeds.
2. Call B (~ms later): `tmux_has_session debate-1` → **true now** → skips session creation → `tmux_window_exists debate-1 main` → **true** (A just made it) → `tmux_ensure_keepalive_pane` → adds a second keepalive to A's window.

There is no duplicate-session error. Call B silently joins call A's session. Both daemons then fight over the same pane roster, and the very bug the plan is trying to fix (invisible second invocation) re-appears — just wearing a different hat.

**Fix shape the plan should have used — atomic claim via `tmux_new_session`:**

```bash
debate_claim_session() {
  local n=1
  while ! tmux_new_session "debate-$n" -d -n main -c "$CWD" "$1"; do
    n=$((n + 1))
    [ "$n" -gt 64 ] && return 1   # sanity ceiling
  done
  printf 'debate-%d\n' "$n"
}
```

`tmux new-session -d -s name` is the atomic check-and-create. Loop-on-failure is the standard lockless-counter pattern; there is no TOCTOU window because the racing call fails with "duplicate session: debate-1" and advances to `n=2`. This is strictly better than "tolerate the race" because the current approach does not tolerate it.

---

## 2. Stale `debate:` session prefix left in three user-facing messages

The plan enumerates changes to `debate.sh:debate_start_or_resume` and `debate-tmux-orchestrator.sh:cleanup`, but misses three messages elsewhere in `debate.sh` that hardcode `debate:`. Current code:

```bash
# debate.sh:291
emit_block "/debate: already running for this topic → tmux attach -t debate:debate-$(basename "$existing")"; exit 0
# debate.sh:349
emit_block "/debate-retry: still running → tmux attach -t debate:debate-$(basename "$best")"; exit 0
# debate.sh:383
emit_block "/debate-abort: debate is running. to force-kill: tmux kill-window -t debate:debate-$(basename "$best")"
```

Under the plan, the session is `debate-N` (not `debate`) and the window is `main` (not `debate-<dirname>`). After the plan lands, these three messages tell the user to attach to a session+window pair that does not exist. The user would run `tmux attach -t debate:debate-2026-04-22...` and get "no sessions" — exactly the UX failure the plan is meant to prevent.

The plan must also resolve which live-debate's session these are referencing. Because the plan drops the `<ts>_<slug>`-derived window name, the running-debate's session number is no longer derivable from the dir path. Two options, both needing a plan change:

- **(a) Persist the session name** — write `tmux-session.txt` into `$DEBATE_DIR` at start, read it when checking `any_live_lock`, emit the correct message.
- **(b) Re-derive from live panes** — `any_live_lock` already has the pane_id; `tmux display-message -t "$pane_id" '#{session_name}'` recovers the session.

Option (a) is simpler. Either way, the plan as written produces broken instructions to the user.

---

## 3. `resume-integration-test.sh` is broken by the positional-arg change, but the plan says tests stay untouched

The plan says (line 113):

> `skills/debate/tests/test.sh` — hand-driven spec that predates the skill extraction. Leave alone.

But there is a *second* test harness, `skills/debate/tests/resume-integration-test.sh`, that **does** run in CI-style shape and sources the orchestrator directly:

```bash
# resume-integration-test.sh:220-233 (paraphrased to show the shape)
(
  export DEBATE_DAEMON_SOURCED=1
  DEBATE_DIR="$debate_dir"
  WINDOW_NAME="debate-$(basename "$DEBATE_DIR")"
  SETTINGS_FILE="/tmp/fake-settings.json"
  CWD="$DEBATE_DIR"
  REPO_ROOT="$DEBATE_DIR"
  PLUGIN_ROOT="$CLAUDE_PLUGIN_ROOT"
  ...
  . "$PLUGIN_ROOT/skills/debate/scripts/debate-tmux-orchestrator.sh"
  ...
  daemon_main
)
```

Under the plan, `debate-tmux-orchestrator.sh` gains a new positional parameter `SESSION="$2"` **and deletes the literal `SESSION="debate"`**. The harness pathway is guarded by `DEBATE_DAEMON_SOURCED=1`, which skips positional parsing. So `SESSION` ends up unset, and `set -u` (line 19 of the orchestrator) will fire on the first reference to `$SESSION` inside e.g. `WINDOW_TARGET="${SESSION}:${WINDOW_NAME}"`.

**Concrete failure** — the harness would crash here:

```bash
# debate-tmux-orchestrator.sh:33 (current)
WINDOW_TARGET="${SESSION}:${WINDOW_NAME}"
#   → after the plan: SESSION is unset in the sourced harness
#   → bash: SESSION: unbound variable
```

The plan must either:
- Add `SESSION` to the list of env vars the harness sets before sourcing, **or**
- Keep `SESSION="debate"` as a **default** in the orchestrator (e.g. `: "${SESSION:=debate}"` or `SESSION="${SESSION:-debate}"`) and override from positional args when not sourced.

I'd pick the second — it's one line and protects the harness and any future callers that source the daemon:

```bash
# top of debate-tmux-orchestrator.sh, replacing the current SESSION="debate"
: "${SESSION:=debate}"   # default; overridden by positional arg below when run as a script
if [ "${DEBATE_DAEMON_SOURCED:-0}" != 1 ]; then
  DEBATE_DIR="$1"
  SESSION="$2"
  WINDOW_NAME="$3"
  ...
fi
```

The plan's "Files NOT changed" section explicitly claims the test harness is orthogonal. That is false for this harness.

---

## 4. Line-number citations are off, and this matters for hand-application

The plan instructs modifications at specific line ranges; both major ones are wrong:

| Plan says | Actual state |
|---|---|
| `debate.sh` "Replace the `window_name` / `tmux_ensure_session` / `tmux resize-window` block: **currently ~lines 169–188**" | Target block is at `debate.sh:208-242` (inside `debate_start_or_resume`). Lines 169-188 are the tail of `check_resume_feasibility` — a completely different function. |
| `debate-tmux-orchestrator.sh` "currently hardcoded `SESSION="debate"` **at line 27**" | Actual location is `debate-tmux-orchestrator.sh:32`. Line 27 is `CWD="$4"` — one of the positional-arg reads. |

Also, the plan's "Update the daemon fork to pass `$session`" snippet shows the orchestrator call with `$window_name` already in the arg list:

```bash
# plan's proposed snippet
bash "$SCRIPTS_DIR/debate-tmux-orchestrator.sh" \
    "$DEBATE_DIR" "$session" "$window_name" "$SETTINGS_FILE" "$CWD" "$REPO_ROOT" "${CLAUDE_PLUGIN_ROOT}" \
    >> "$orch_log" 2>&1 </dev/null &
```

But the plan also says (§Approach): "One window per session (static name `main`)." If every session has one static window named `main`, `window_name` is dead weight — it should be either removed from the arg list or the plan should state why it's retained (e.g., future multi-window debates). This is a small design incoherence: the plan simultaneously (a) reduces to one window per session, (b) hardcodes its name to `main`, and (c) still threads it through as a positional arg. Pick one.

---

## 5. Root-cause claim for the "no orchestrator.log" symptom is under-evidenced

From the plan's Context section:

> The second+ `/debate` call in a session produces a `Debates/<ts>_<slug>/` directory with the input instructions, but no `orchestrator.log` — the daemon's pane-creation side effects never materialise.

The daemon fork (`debate.sh:247-250`):

```bash
bash "$SCRIPTS_DIR/debate-tmux-orchestrator.sh" \
    "$DEBATE_DIR" "$window_name" "$SETTINGS_FILE" "$CWD" "$REPO_ROOT" "${CLAUDE_PLUGIN_ROOT}" \
    >> "$orch_log" 2>&1 </dev/null &
```

The `>> "$orch_log" 2>&1` redirect creates `orchestrator.log` as soon as the forked bash opens it. If no `orchestrator.log` appears, **the fork itself didn't run** (or ran and bash silently exited before opening the redirect, which is essentially impossible here). That's inconsistent with the plan's stated root cause of "shared-session window-per-call being invisible" — shared-session invisibility would still produce an orchestrator.log, it just wouldn't be visible in a new Terminal window.

Two possibilities the plan should have separated:

- **Hypothesis A (what plan fixes):** orchestrator.log IS created but the user can't see the pane because `spawn_terminal_if_needed` short-circuits. → fresh session fixes UX; the daemon was fine all along.
- **Hypothesis B (what plan claims):** orchestrator.log is literally absent. → the daemon fork never executed. → fresh session alone would not fix this; something upstream (e.g., `debate_build_claude_cmd` crashing, `trap ... ERR` firing before the fork) is silently killing the hook.

If the user's report is literally "no orchestrator.log", the plan's fix may not resolve the bug. The plan should have `ls Debates/<ts>_<slug>/` evidence from a failing run before committing to the fresh-session hypothesis. The Verification section's step 1 says "Expected before fix: second invocation's Debates/<ts>_<slug>/ has no orchestrator.log" — that's stated as an assumption, not a reproduced baseline.

---

## 6. Lowest-unused-N is a good choice, but worth one counter-argument

The plan argues for lowest-unused vs. monotonic (§Approach). Agree on the conclusion, but one risk the plan elides: **the numbers are user-visible and reusable**. If a user opens `tmux attach -t debate-1`, the daemon finishes, session is killed, next `/debate` is also `debate-1` — the user's old attach command now points at a different debate. This is a foot-gun for anyone who keeps a terminal around.

Mitigation is tiny — include the debate slug in the window title (`tmux rename-window` or `tmux_set_pane_title`) so `tmux ls` shows the topic:

```bash
hide_output tmux_set_pane_title "${session}:${window_name}.0" "debate: ${slug}"
```

Not a blocker, but the plan's stated rationale ("keeps session names short") would be more honest if it acknowledged the reuse risk alongside.

---

## Summary — what must change before execution

1. **(Blocker) Atomic claim via `tmux_new_session` loop** — replace `debate_next_session_name` with a real check-and-create. The current version has a real race, not a tolerable one.
2. **(Blocker) Update the three user-facing "attach to debate:…" messages** in `debate.sh:291,349,383`, plus a persistence mechanism (`tmux-session.txt` in `$DEBATE_DIR`) so they can resolve the live session.
3. **(Blocker) Either add `SESSION` to `resume-integration-test.sh:220` env block, or make `SESSION` defaulted in the orchestrator.** Otherwise the integration harness crashes under `set -u`.
4. **(Required) Fix the line-number citations** — `169-188` and `line 27` are wrong.
5. **(Recommended) Revisit the root cause claim** — run the bug live and confirm orchestrator.log is literally absent vs. merely unseen. Update §Verification §1 to include real baseline evidence.
6. **(Nice-to-have) Rename the window to include the topic slug** so reused session numbers aren't confusing.

With (1)–(4) addressed, the plan is safe to execute. Without them, applying the plan as written will replace one bug with two (invisible shared-session + broken attach instructions) and break the integration test suite.
