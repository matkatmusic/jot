# Round 1 — Codex

## Position

The direction is correct: moving `/debate` from one shared tmux session to one fresh tmux session per invocation is the right fix for the "second run silently disappears" failure mode. But the plan is **not committable as written**. It misses one functional requirement and one existing test/harness contract, and its concurrency story is weaker than the plan claims.

My bottom line: **take the session-per-invocation design, but do not implement this plan verbatim.**

## What The Plan Gets Right

- It targets the real coupling point: `debate_start_or_resume()` currently hardcodes a shared `debate` session and multiplexes debates by window name.
- It correctly identifies `spawn_terminal_if_needed "debate"` as part of the invisibility bug, because `platform.sh` only spawns Terminal when a session has no attached clients.
- It correctly changes daemon cleanup from window-scoped to session-scoped. Once there is exactly one debate per session, `tmux_kill_session` is the right blast radius.

The current production path really is still shared-session + dynamic-window:

```bash
debate_start_or_resume() {
  local window_name
  window_name="debate-$(basename "$DEBATE_DIR")"

  local keepalive_cmd='exec sh -c '\''trap "" INT HUP TERM; printf "[debate keepalive]\n"; exec tail -f /dev/null'\'''
  tmux_ensure_session debate "$window_name" "$CWD" "$keepalive_cmd" 'debate: keepalive'
  hide_errors tmux resize-window -t "debate:${window_name}" -x 200 -y 60

  local orch_log="$DEBATE_DIR/orchestrator.log"
  GEMINI_MODEL="$GEMINI_MODEL" CODEX_MODEL="$CODEX_MODEL" \
  DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" COMPOSITION_DRIFTED="$composition_drifted" \
    bash "$SCRIPTS_DIR/debate-tmux-orchestrator.sh" \
      "$DEBATE_DIR" "$window_name" "$SETTINGS_FILE" "$CWD" "$REPO_ROOT" "${CLAUDE_PLUGIN_ROOT}" \
      >> "$orch_log" 2>&1 </dev/null &
  disown

  spawn_terminal_if_needed "debate" "$LOG_FILE" "debate"
}
```

That architecture is exactly what the user asked to get rid of.

## Critical Issues In The Plan

### 1. The plan destroys the only recoverable attach target for a live debate

Today, the code can reconstruct the live tmux target from the debate directory name because the window name is derived from that directory basename:

```bash
if any_live_lock "$existing"; then
  emit_block "/debate: already running for this topic → tmux attach -t debate:debate-$(basename "$existing")"; exit 0
fi
...
if any_live_lock "$best"; then
  emit_block "/debate-retry: still running → tmux attach -t debate:debate-$(basename "$best")"; exit 0
fi
...
if any_live_lock "$best"; then
  emit_block "/debate-abort: debate is running. to force-kill: tmux kill-window -t debate:debate-$(basename "$best")"
  exit 0
fi
```

The proposed design changes both parts of that mapping:

- session becomes `debate-<N>`
- window becomes static `main`
- `N` is lowest-unused and therefore **not derivable from the debate directory name**

After that change, the three messages above become wrong, and the plan does not add any replacement mechanism. That is a real functional regression, not just stale messaging.

The lock files do not save the session either; they currently only save a literal `debate:` prefix plus pane id:

```bash
launch_agent() {
  local pane_id="$1" stage="$2" agent="$3" launch_cmd="$4" ready_marker="$5"
  local timeout="${6:-30}"
  printf 'debate:%s\n' "$pane_id" > "$DEBATE_DIR/.${stage}_${agent}.lock"
  tmux_send_and_submit "$pane_id" "$launch_cmd"
  ...
}
```

So once the plan lands, `/debate`, `/debate-retry`, and `/debate-abort` lose their ability to tell the user where the still-running debate actually lives.

The fix needs to be explicit. Either persist the session name (for example `session.txt`) or derive it from a live pane id. A complete tmux-based recovery helper would look like this:

```bash
live_debate_session() {
  local dir="$1" lock pane_id session
  for lock in "$dir"/.*.lock; do
    [ -f "$lock" ] || continue
    pane_id=$(sed -n 's|^[^:]*:\(%[0-9]*\)$|\1|p' "$lock")
    [ -z "$pane_id" ] && continue
    session=$(hide_errors tmux display-message -p -t "$pane_id" '#{session_name}')
    if [ -n "$session" ]; then
      printf '%s\n' "$session"
      return 0
    fi
  done
  return 1
}
```

Then the user-facing paths can remain correct:

```bash
if any_live_lock "$existing"; then
  live_session=$(live_debate_session "$existing") || live_session="<unknown>"
  emit_block "/debate: already running for this topic → tmux attach -t ${live_session}:main"
  exit 0
fi
```

Without this, the plan is incomplete.

### 2. Removing `SESSION="debate"` breaks the sourced daemon harness unless the plan updates it

The plan says to remove the hardcoded `SESSION="debate"` and make `SESSION` positional. That is fine for the normal script path, but the daemon also has a sourced test/harness mode:

```bash
if [ "${DEBATE_DAEMON_SOURCED:-0}" != 1 ]; then
  DEBATE_DIR="$1"
  WINDOW_NAME="$2"
  SETTINGS_FILE="$3"
  CWD="$4"
  REPO_ROOT="$5"
  PLUGIN_ROOT="$6"
fi

SESSION="debate"
WINDOW_TARGET="${SESSION}:${WINDOW_NAME}"
```

And the existing harness depends on that:

```bash
run_daemon_main() {
  (
    export DEBATE_DAEMON_SOURCED=1
    DEBATE_DIR="$debate_dir"
    WINDOW_NAME="debate-$(basename "$DEBATE_DIR")"
    SETTINGS_FILE="/tmp/fake-settings.json"
    CWD="$DEBATE_DIR"
    REPO_ROOT="$DEBATE_DIR"
    PLUGIN_ROOT="$CLAUDE_PLUGIN_ROOT"
    DEBATE_AGENTS="$agents_env"
    COMPOSITION_DRIFTED="$drift"
    GEMINI_MODEL=""
    CODEX_MODEL=""

    . "$PLUGIN_ROOT/skills/debate/scripts/debate-tmux-orchestrator.sh"
    ...
  )
}
```

If you delete `SESSION="debate"` and only add a seventh positional arg for the non-sourced path, this sourced path will hit `set -u` with `SESSION` unset the first time `WINDOW_TARGET="${SESSION}:${WINDOW_NAME}"` executes.

So the plan's "files not changed" / verification section is incomplete. At minimum, either:

- update the sourced harness to set `SESSION`, or
- make the daemon require `SESSION` in sourced mode too

A correct shape is:

```bash
if [ "${DEBATE_DAEMON_SOURCED:-0}" != 1 ]; then
  DEBATE_DIR="$1"
  SESSION="$2"
  WINDOW_NAME="$3"
  SETTINGS_FILE="$4"
  CWD="$5"
  REPO_ROOT="$6"
  PLUGIN_ROOT="$7"
fi

: "${SESSION:?SESSION required}"
WINDOW_TARGET="${SESSION}:${WINDOW_NAME}"
```

And then the harness must export `SESSION="debate-test"` or similar before sourcing.

### 3. The plan's race story is too weak for the requirement it is trying to satisfy

The plan proposes:

```bash
debate_next_session_name() {
  local n=1
  while hide_errors tmux has-session -t "debate-$n"; do
    n=$((n + 1))
  done
  printf 'debate-%d\n' "$n"
}
```

followed by:

```bash
session=$(debate_next_session_name)
tmux_ensure_session "$session" "$window_name" "$CWD" "$keepalive_cmd" 'debate: keepalive'
```

But `tmux_ensure_session()` is itself a non-atomic check-then-create sequence:

```bash
tmux_ensure_session() {
  local session="$1" window="$2" cwd="$3" keepalive_cmd="$4" keepalive_title="$5"
  if ! tmux_has_session "$session"; then
    tmux_new_session "$session" -n "$window" -c "$cwd" "$keepalive_cmd"
    ...
    return 0
  fi
  ...
}
```

Two concurrent `/debate` calls can both choose `debate-1`, one wins, and the other dies in `tmux_new_session`. The plan calls that "tolerable", but the user's directive was stronger than that: every invocation should create a fresh session. A valid invocation crashing because another valid invocation started at the same time is a correctness hole.

The easy fix is to retry on duplicate-session creation instead of treating it as fatal:

```bash
debate_create_unique_session() {
  local session
  while :; do
    session=$(debate_next_session_name)
    if tmux_new_session "$session" -n "main" -c "$CWD" "$keepalive_cmd"; then
      hide_output tmux_set_option_t "$session" remain-on-exit off
      hide_output tmux_set_option_t "$session" mouse on
      hide_output tmux_set_option_t "$session" pane-border-status top
      hide_output tmux_set_option_t "$session" pane-border-format ' #{pane_title} '
      hide_output tmux_set_pane_title "${session}:main.0" 'debate: keepalive'
      printf '%s\n' "$session"
      return 0
    fi
  done
}
```

That matches the plan's stateless naming idea without leaving concurrent starts to chance.

## Secondary Accuracy Notes

- The plan's line references have drifted. The main session/window block in `debate.sh` is at lines 207-258 now, not "~169-188". The daemon's `SESSION="debate"` is at line 32, not 27.
- The daemon comments and preconditions still describe a shared `debate` session. That is not a functional blocker, but if this change lands those comments become materially false and should be updated in the same patch.
- The verification step that expects exactly `debate-1` and `debate-2` is brittle if stale `debate-*` sessions already exist. Either pre-clean them or assert "two distinct `debate-*` sessions newly created for this run" instead of exact numeric names.

## Recommended Verdict

Approve the architectural direction, but require amendments before implementation:

1. Add live-session recovery or persist session identity.
2. Update the sourced daemon harness / tests for `SESSION`.
3. Make unique-session creation retry on duplicate instead of crashing.

With those changes, the plan is solid. Without them, it fixes the original symptom while introducing a new class of "running debate exists but the tooling cannot tell you where it is" failures.
