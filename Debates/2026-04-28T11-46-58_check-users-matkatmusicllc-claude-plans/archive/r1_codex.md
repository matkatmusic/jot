# Round 1 Codex Analysis: `/jot:debate` Parallel Agent Launch

## Position

The plan is directionally correct: R1 and R2 should fan out the full `launch_agent + send_prompt` pair per agent and use one wait-all barrier. That preserves the existing stage model while removing the avoidable serial boot cost.

I would not land the plan exactly as written. The proposed `write_failed` atomicity fix uses `"$DEBATE_DIR/.FAILED.txt.$$"`, but on the target macOS Bash 3.2 environment `$$` is shared by subshell workers and `$BASHPID` is not available. That means concurrent workers can still write the same tempfile inode, so the fix does not actually prevent torn diagnostics. Use `mktemp` in `DEBATE_DIR` instead.

I would also add at least one automated concurrency assertion. The existing resume harness is likely compatible because it sorts invocation lines before comparing, but it does not prove launches are concurrent.

## Current Code Facts

The current R1 and R2 launch loops are serial. Each agent blocks on `launch_agent`, then blocks on `send_prompt`, before the next agent begins.

```bash
# skills/debate/scripts/debate-tmux-orchestrator.sh:438-452
for i in "${!AGENTS[@]}"; do
  agent="${AGENTS[$i]}"
  if [ -s "$DEBATE_DIR/r1_${agent}.md" ]; then
    echo "[orch] r1/${agent} already complete, skipping launch"
    hide_errors tmux_kill_pane "${R1_PANES[$i]}"
    continue
  fi
  if [ -f "$DEBATE_DIR/.r1_${agent}.lock" ]; then
    echo "[orch] r1/${agent} lock held by live pane, skipping launch (wait_for_outputs will observe)"
    hide_errors tmux_kill_pane "${R1_PANES[$i]}"
    continue
  fi
  launch_agent "${R1_PANES[$i]}" r1 "$agent" "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" || exit 1
  send_prompt  "${R1_PANES[$i]}" r1 "$agent" "$DEBATE_DIR/r1_instructions_${agent}.txt" || exit 1
done
```

```bash
# skills/debate/scripts/debate-tmux-orchestrator.sh:481-495
for i in "${!AGENTS[@]}"; do
  agent="${AGENTS[$i]}"
  if [ -s "$DEBATE_DIR/r2_${agent}.md" ]; then
    echo "[orch] r2/${agent} already complete, skipping launch"
    hide_errors tmux_kill_pane "${R2_PANES[$i]}"
    continue
  fi
  if [ -f "$DEBATE_DIR/.r2_${agent}.lock" ]; then
    echo "[orch] r2/${agent} lock held by live pane, skipping launch (wait_for_outputs will observe)"
    hide_errors tmux_kill_pane "${R2_PANES[$i]}"
    continue
  fi
  launch_agent "${R2_PANES[$i]}" r2 "$agent" "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" || exit 1
  send_prompt  "${R2_PANES[$i]}" r2 "$agent" "$DEBATE_DIR/r2_instructions_${agent}.txt" || exit 1
done
```

The failure writer is currently a direct truncate-and-write to `FAILED.txt`, so parallel launch introduces a real concurrent-writer risk:

```bash
# skills/debate/scripts/debate-tmux-orchestrator.sh:257-278
write_failed() {
  local stage="$1" reason="$2"
  {
    printf '# debate FAILED\n\nstage: %s\nreason: %s\ntimestamp: %s\n\n' \
      "$stage" "$reason" "$(date -Iseconds)"
    printf '## missing agents\n'
    local agent lock pane_id
    for agent in "${AGENTS[@]}"; do
      [ -s "$DEBATE_DIR/${stage}_${agent}.md" ] && continue
      printf '\n### %s\n' "$agent"
      lock="$DEBATE_DIR/.${stage}_${agent}.lock"
      pane_id=$(sed -n 's|^debate:\(%[0-9]*\)$|\1|p' "$lock" 2>/dev/null)
      if [ -n "$pane_id" ]; then
        printf '```\n'
        hide_errors tmux capture-pane -t "$pane_id" -p -S -200 || printf '(pane capture unavailable)\n'
        printf '```\n'
      else
        printf '(no pane captured — lock file missing or malformed)\n'
      fi
    done
  } > "$DEBATE_DIR/FAILED.txt"
}
```

## Critical Plan Bug: `.$$` Tempfile Is Not Unique

The plan correctly identifies that `FAILED.txt` should be written via temp file plus rename. The proposed tempfile name is wrong:

```bash
write_failed() {
  local stage="$1" reason="$2"
  local tmpfile="$DEBATE_DIR/.FAILED.txt.$$"
  {
    printf '# debate FAILED\n\nstage: %s\nreason: %s\ntimestamp: %s\n\n' \
      "$stage" "$reason" "$(date -Iseconds)"
    printf '## missing agents\n'
    local agent lock pane_id
    for agent in "${AGENTS[@]}"; do
      [ -s "$DEBATE_DIR/${stage}_${agent}.md" ] && continue
      printf '\n### %s\n' "$agent"
      lock="$DEBATE_DIR/.${stage}_${agent}.lock"
      pane_id=$(sed -n 's|^debate:\(%[0-9]*\)$|\1|p' "$lock" 2>/dev/null)
      if [ -n "$pane_id" ]; then
        printf '```\n'
        hide_errors tmux capture-pane -t "$pane_id" -p -S -200 || printf '(pane capture unavailable)\n'
        printf '```\n'
      else
        printf '(no pane captured — lock file missing or malformed)\n'
      fi
    done
  } > "$tmpfile"
  mv "$tmpfile" "$DEBATE_DIR/FAILED.txt"
}
```

That does not make each writer independent. In Bash, `$$` is the PID of the original shell, not the subshell. The project targets macOS Bash 3.2, and in this local environment `$BASHPID` is not present:

```bash
bash -lc 'echo parent:$$:${BASHPID:-none}; ( echo child:$$:${BASHPID:-none} )'
# parent:60972:none
# child:60972:none
```

With the proposed code, three failing workers all use the same path:

```bash
(
  write_failed r1 "launch_agent timeout for claude after 120s"
) &
(
  write_failed r1 "launch_agent timeout for gemini after 120s"
) &
(
  write_failed r1 "launch_agent timeout for codex after 120s"
) &
wait
```

This can still tear output:

1. Worker A opens `.FAILED.txt.<daemon-pid>` and starts writing.
2. Worker B opens the same path, truncating or sharing the same filename race.
3. Worker A renames that path to `FAILED.txt`.
4. Worker B may continue writing through its already-open fd to the inode that is now visible as `FAILED.txt`, or may fail its final `mv` if the path no longer exists.

So `.$$` does not merely risk harmless overwrite. It can preserve the same concurrent write interleaving the plan is trying to eliminate.

## Required Fix

Use `mktemp` inside `DEBATE_DIR`, then rename. This gives each concurrent caller a distinct file on the same filesystem as `FAILED.txt`, so the final `mv` is atomic and last-rename-wins with internally consistent content.

```bash
write_failed() {
  local stage="$1" reason="$2"
  local tmpfile

  tmpfile=$(mktemp "$DEBATE_DIR/.FAILED.txt.XXXXXX") || return 1

  if ! {
    printf '# debate FAILED\n\nstage: %s\nreason: %s\ntimestamp: %s\n\n' \
      "$stage" "$reason" "$(date -Iseconds)"
    printf '## missing agents\n'

    local agent lock pane_id
    for agent in "${AGENTS[@]}"; do
      [ -s "$DEBATE_DIR/${stage}_${agent}.md" ] && continue

      printf '\n### %s\n' "$agent"
      lock="$DEBATE_DIR/.${stage}_${agent}.lock"
      pane_id=$(sed -n 's|^debate:\(%[0-9]*\)$|\1|p' "$lock" 2>/dev/null)

      if [ -n "$pane_id" ]; then
        printf '```\n'
        hide_errors tmux capture-pane -t "$pane_id" -p -S -200 || printf '(pane capture unavailable)\n'
        printf '```\n'
      else
        printf '(no pane captured — lock file missing or malformed)\n'
      fi
    done
  } > "$tmpfile"; then
    rm -f "$tmpfile"
    return 1
  fi

  if ! mv -f "$tmpfile" "$DEBATE_DIR/FAILED.txt"; then
    rm -f "$tmpfile"
    return 1
  fi
}
```

This also makes the plan's proposed "no `.FAILED.txt.*` tempfiles linger" check meaningful. With `.$$`, that check is not reliable because all workers target the same temp path.

## Parallel Helper Assessment

The helper shape is correct: skip completed outputs, skip live locks, background the full launch-and-prompt pair, wait for all PIDs, then return failure if any worker failed.

I would implement it with the same Bash 3.2 constraints the file already follows:

```bash
launch_agents_parallel() {
  local stage="$1" panes_var="$2"
  local pids=() agents_run=()
  local i agent pane_id fail

  fail=0

  for i in "${!AGENTS[@]}"; do
    agent="${AGENTS[$i]}"
    eval "pane_id=\${${panes_var}[$i]}"

    if [ -s "$DEBATE_DIR/${stage}_${agent}.md" ]; then
      echo "[orch] ${stage}/${agent} already complete, skipping launch"
      hide_errors tmux_kill_pane "$pane_id"
      continue
    fi

    if [ -f "$DEBATE_DIR/.${stage}_${agent}.lock" ]; then
      echo "[orch] ${stage}/${agent} lock held by live pane, skipping launch (wait_for_outputs will observe)"
      hide_errors tmux_kill_pane "$pane_id"
      continue
    fi

    (
      launch_agent "$pane_id" "$stage" "$agent" \
        "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" \
        || exit 1

      send_prompt "$pane_id" "$stage" "$agent" \
        "$DEBATE_DIR/${stage}_instructions_${agent}.txt" \
        || exit 1
    ) &

    pids+=("$!")
    agents_run+=("$agent")
  done

  for i in "${!pids[@]}"; do
    if ! wait "${pids[$i]}"; then
      echo "[orch] ${stage}/${agents_run[$i]} worker exited non-zero" >&2
      fail=1
    fi
  done

  return "$fail"
}
```

Then replace only the two serial launch loops:

```bash
launch_agents_parallel r1 R1_PANES || exit 1
wait_for_outputs r1 "$STAGE_TIMEOUT" R1_PANES || exit 1
```

```bash
launch_agents_parallel r2 R2_PANES || exit 1
wait_for_outputs r2 "$STAGE_TIMEOUT" R2_PANES || exit 1
```

The single-agent synthesis stage should remain unchanged.

## Failure Semantics

The plan's "wait-all-then-check" decision is the right one. It avoids a common partial-parallelization bug where the first failure exits the parent while other workers are still booting. Waiting every PID also makes the log deterministic enough to diagnose which workers failed.

One wording issue: the plan says existing `wait_for_outputs` writes diagnostic `FAILED.txt` on any worker failure. With the proposed `launch_agents_parallel r1 R1_PANES || exit 1`, `wait_for_outputs` is not called after a helper failure. The timeout paths inside `launch_agent` and `send_prompt` already call `write_failed`, so diagnostics still exist for the primary expected worker failures:

```bash
launch_agent() {
  local pane_id="$1" stage="$2" agent="$3" launch_cmd="$4" ready_marker="$5"
  local timeout="${6:-120}"
  printf 'debate:%s\n' "$pane_id" > "$DEBATE_DIR/.${stage}_${agent}.lock"
  tmux_send_and_submit "$pane_id" "$launch_cmd"
  local elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    if hide_errors tmux capture-pane -t "$pane_id" -p -S -2000 \
         | tr -d '\033' | grep -qF "$ready_marker"; then
      echo "[orch] ${stage}/${agent} ready after ${elapsed}s (pane $pane_id)"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  echo "[orch] TIMEOUT: ${stage}/${agent} not ready within ${timeout}s" >&2
  write_failed "$stage" "launch_agent timeout for $agent after ${timeout}s"
  return 1
}
```

```bash
send_prompt() {
  local pane_id="$1" stage="$2" agent="$3" instructions="$4"
  tmux_send_and_submit "$pane_id" "read $instructions and perform them"
  local marker
  marker=$(basename "$instructions")
  local elapsed=0
  while [ "$elapsed" -lt 30 ]; do
    if hide_errors tmux capture-pane -t "$pane_id" -p -S -2000 \
         | tr -d '\033' | grep -qF "$marker"; then
      echo "[orch] ${stage}/${agent} prompt received after ${elapsed}s"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  echo "[orch] TIMEOUT: ${stage}/${agent} did not echo prompt" >&2
  write_failed "$stage" "send_prompt timeout for $agent after 30s"
  return 1
}
```

So the behavior is acceptable, but the plan should state it accurately: launch/prompt timeouts write diagnostics from the worker; stage-output timeouts write diagnostics from `wait_for_outputs`.

## Test Coverage Assessment

The plan is right that the existing resume integration assertions sort invocation lines:

```bash
r1_invocations=$(grep '^r1 ' "$d/.harness_invocations" 2>/dev/null | sort | tr '\n' ' ')
[ "$r1_invocations" = "r1 gemini " ] && pass "T8: R1 launched only gemini" || fail "T8: R1 invocations='$r1_invocations'"

r2_invocations=$(grep '^r2 ' "$d/.harness_invocations" 2>/dev/null | sort | tr '\n' ' ')
[ "$r2_invocations" = "r2 claude r2 codex r2 gemini " ] && pass "T8: R2 launched all 3 agents (drift cleared)" || fail "T8: R2 invocations='$r2_invocations'"
```

The daemon harness stubs also make the parallel change mostly compatible:

```bash
launch_agent() {
  local pane_id="$1" stage="$2" agent="$3"
  printf 'debate:%s\n' "$pane_id" > "$DEBATE_DIR/.${stage}_${agent}.lock"
  return 0
}

send_prompt() {
  local pane_id="$1" stage="$2" agent="$3" instructions="$4"
  local out
  case "$stage" in
    r1)        out="$DEBATE_DIR/r1_${agent}.md" ;;
    r2)        out="$DEBATE_DIR/r2_${agent}.md" ;;
    synthesis) out="$DEBATE_DIR/synthesis.md" ;;
  esac
  printf '%s %s\n' "$stage" "$agent" >> "$DEBATE_DIR/.harness_invocations"
  printf 'FAKE %s output from %s\n' "$stage" "$agent" > "$out"
  return 0
}
```

But compatibility is not the same as verification. With `sleep()` stubbed to `:`, the resume test will pass whether the launch loop is serial or parallel. I would add a specific helper-level test that fails under serial execution:

```bash
test_launch_agents_parallel_overlaps_workers() {
  mk_test_env
  local repo="$TEST_REPO"
  local d="$repo/Debates/2025-01-01T00-00-00_parallel"
  mkdir -p "$d"

  (
    export DEBATE_DAEMON_SOURCED=1
    export SESSION="debate-test-$$"
    DEBATE_DIR="$d"
    WINDOW_NAME="main"
    SETTINGS_FILE="/tmp/fake-settings.json"
    CWD="$DEBATE_DIR"
    REPO_ROOT="$DEBATE_DIR"
    PLUGIN_ROOT="$CLAUDE_PLUGIN_ROOT"
    DEBATE_AGENTS="claude gemini codex"
    export DEBATE_DIR WINDOW_NAME SETTINGS_FILE CWD REPO_ROOT PLUGIN_ROOT DEBATE_AGENTS

    . "$PLUGIN_ROOT/skills/debate/scripts/debate-tmux-orchestrator.sh"

    tmux_kill_pane() { :; }
    agent_launch_cmd() { echo "fake $1"; }
    agent_ready_marker() { echo "ready $1"; }

    launch_agent() {
      local pane_id="$1" stage="$2" agent="$3"
      printf '%s %s %s\n' "$stage" "$agent" "$(date +%s)" >> "$DEBATE_DIR/.starts"
      command sleep 2
      printf 'debate:%s\n' "$pane_id" > "$DEBATE_DIR/.${stage}_${agent}.lock"
      return 0
    }

    send_prompt() {
      local pane_id="$1" stage="$2" agent="$3" instructions="$4"
      printf '%s %s\n' "$stage" "$agent" >> "$DEBATE_DIR/.prompts"
      return 0
    }

    R1_PANES=("%1" "%2" "%3")
    start=$(date +%s)
    launch_agents_parallel r1 R1_PANES
    rc=$?
    end=$(date +%s)
    elapsed=$((end - start))

    [ "$rc" -eq 0 ] || exit 10
    [ "$elapsed" -lt 4 ] || exit 11
    [ "$(wc -l < "$DEBATE_DIR/.starts" | tr -d ' ')" = 3 ] || exit 12
    [ "$(wc -l < "$DEBATE_DIR/.prompts" | tr -d ' ')" = 3 ] || exit 13
  )

  local rc=$?
  if [ "$rc" -eq 0 ]; then
    pass "parallel helper overlaps three 2s launches"
  else
    fail "parallel helper did not overlap launches (rc=$rc)"
  fi

  rm -rf "$repo"
}
```

This test should complete in roughly two seconds after the helper exists. A serial launch would take roughly six seconds and fail the `elapsed < 4` assertion.

I would also add the plan's concurrent `write_failed` race test, but only after changing `write_failed` to `mktemp`. A complete harness-level version can avoid real agent CLIs:

```bash
test_write_failed_concurrent_writers_are_well_formed() {
  mk_test_env
  local repo="$TEST_REPO"
  local d="$repo/Debates/2025-01-01T00-00-00_failed-race"
  mkdir -p "$d"

  (
    export DEBATE_DAEMON_SOURCED=1
    export SESSION="debate-test-$$"
    DEBATE_DIR="$d"
    WINDOW_NAME="main"
    SETTINGS_FILE="/tmp/fake-settings.json"
    CWD="$DEBATE_DIR"
    REPO_ROOT="$DEBATE_DIR"
    PLUGIN_ROOT="$CLAUDE_PLUGIN_ROOT"
    DEBATE_AGENTS="claude gemini codex"
    export DEBATE_DIR WINDOW_NAME SETTINGS_FILE CWD REPO_ROOT PLUGIN_ROOT DEBATE_AGENTS

    . "$PLUGIN_ROOT/skills/debate/scripts/debate-tmux-orchestrator.sh"

    printf 'debate:%%1\n' > "$DEBATE_DIR/.r1_claude.lock"
    printf 'debate:%%2\n' > "$DEBATE_DIR/.r1_gemini.lock"
    printf 'debate:%%3\n' > "$DEBATE_DIR/.r1_codex.lock"

    tmux() {
      case "$1" in
        capture-pane)
          printf 'captured pane output for %s\n' "$4"
          return 0
          ;;
      esac
      return 0
    }

    write_failed r1 "timeout claude" &
    write_failed r1 "timeout gemini" &
    write_failed r1 "timeout codex" &
    wait

    [ "$(grep -c '^# debate FAILED$' "$DEBATE_DIR/FAILED.txt")" = 1 ] || exit 20
    [ "$(grep -c '^### ' "$DEBATE_DIR/FAILED.txt")" = 3 ] || exit 21
    grep -q '^### claude$' "$DEBATE_DIR/FAILED.txt" || exit 22
    grep -q '^### gemini$' "$DEBATE_DIR/FAILED.txt" || exit 23
    grep -q '^### codex$' "$DEBATE_DIR/FAILED.txt" || exit 24
    ! ls "$DEBATE_DIR"/.FAILED.txt.* >/dev/null 2>&1 || exit 25
  )

  local rc=$?
  if [ "$rc" -eq 0 ]; then
    pass "concurrent write_failed leaves one well-formed FAILED.txt"
  else
    fail "concurrent write_failed race check failed (rc=$rc)"
  fi

  rm -rf "$repo"
}
```

## Other Risks and Trade-Offs

The subshell state concern is acceptable. `launch_agent` and `send_prompt` communicate by tmux and files, not by mutating parent shell variables. Capacity rotation state (`CURRENT_MODEL_*`, `TRIED_MODELS_*`) is used later in `wait_for_outputs` and in `retry_pane_with_next_model`, which still runs in the main shell.

Concurrent `tmux send-keys` to different panes is acceptable. tmux serializes commands server-side, and the helper sends each worker to a distinct pane id.

The lock-held branch remains semantically odd but is not made worse by the plan. Both current and proposed code create a new pane, discover an existing lock, kill the newly created pane, and rely on the existing locked pane to finish. `wait_for_outputs` still indexes the new pane array for capacity checks, so it will not inspect the old locked pane for capacity errors. That is a pre-existing resume limitation, not a blocker for launch parallelization.

The plan's manual real-debate verification is useful but should not be the only proof. The change is small enough that a helper-level timing test is worth adding, because it catches accidental re-serialization immediately.

## Recommended Landing Criteria

Land the plan only with these amendments:

1. Keep the shared `launch_agents_parallel` helper and use it for both R1 and R2.
2. Replace the `.$$` tempfile proposal with `mktemp "$DEBATE_DIR/.FAILED.txt.XXXXXX"` plus `mv -f`.
3. Update the plan wording around failure diagnostics: worker launch/prompt failures write `FAILED.txt`; `wait_for_outputs` only runs after successful launch/prompt fanout.
4. Add an automated helper-level overlap test so serial execution fails loudly.
5. Add a concurrent `write_failed` test after the `mktemp` fix.

With those changes, the parallel launch design is sound and should materially reduce cold-start wall time without changing the debate stage contract.
