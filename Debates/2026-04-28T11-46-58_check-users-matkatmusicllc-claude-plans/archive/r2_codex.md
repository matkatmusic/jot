# Round 2 Codex Cross-Critique

## Executive Position

All three Round 1 responses agree on the main architecture: keep pane creation serial, then fan out the full `launch_agent + send_prompt` pair per agent, wait for every worker PID, and leave synthesis alone. That consensus is well-supported by the current code at `skills/debate/scripts/debate-tmux-orchestrator.sh:438-452` and `:481-495`, where both R1 and R2 currently block on each agent before starting the next.

The remaining blocker is the failure-path atomicity fix. Claude and my Round 1 response identify the same critical flaw in the plan: `"$DEBATE_DIR/.FAILED.txt.$$"` is not a unique tempfile in background subshells on the target macOS Bash 3.2 environment. Gemini correctly identifies the concurrent `write_failed` race, but its proposed fix still uses `$$`, so it preserves the same core collision bug.

I would land the plan only with a `mktemp`-based `write_failed` fix and at least one automated overlap test.

## Agreement Across Responses

### The helper shape is correct

Everyone supports backgrounding the combined launch and prompt sequence:

```bash
(
  launch_agent "$pane_id" "$stage" "$agent" \
    "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" \
    || exit 1
  send_prompt "$pane_id" "$stage" "$agent" \
    "$DEBATE_DIR/${stage}_instructions_${agent}.txt" || exit 1
) &
```

That is the right granularity. Backgrounding only `launch_agent` would still serialize prompt delivery and leave avoidable wall-clock time in the stage startup path.

### Bash 3.2 requires a simple PID barrier

Claude, Gemini, and I all agree that `wait -n` is unavailable for the target environment. The plan's `pids[]` plus positional `wait "${pids[$i]}"` loop is the right portable mechanism. It trades fail-fast reporting for deterministic cleanup of all worker children, which is acceptable for this daemon.

### The current `write_failed` implementation is unsafe after parallelization

The current implementation redirects an entire block directly to `FAILED.txt`:

```bash
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

That was tolerable while launch/prompt failures were serial. After fanout, `launch_agent` and `send_prompt` can call `write_failed` concurrently from multiple worker subshells (`:302`, `:326`). Direct truncating writes to the same destination are not safe.

### Existing resume tests are compatible, not sufficient

The plan correctly notes that resume harness assertions sort invocation lines before comparing. The current test confirms this:

```bash
r1_invocations=$(grep '^r1 ' "$d/.harness_invocations" 2>/dev/null | sort | tr '\n' ' ')
r2_invocations=$(grep '^r2 ' "$d/.harness_invocations" 2>/dev/null | sort | tr '\n' ' ')
```

That means the existing tests should not fail merely because launch order changes. But Claude and I agree this is only compatibility evidence. It does not prove that launches overlap; a serial implementation can still pass.

## Disagreements and Corrections

### The plan's `.$$` atomicity fix is not acceptable

The plan says `$$` collisions are harmless because concurrent callers produce equivalent diagnostics. That is wrong for two reasons.

First, `$$` is the same in subshells on the target Bash:

```bash
$ bash -c 'echo "parent $$ BASHPID=${BASHPID:-UNSET}"; ( echo "child $$ BASHPID=${BASHPID:-UNSET}" )'
parent 76076 BASHPID=UNSET
child 76076 BASHPID=UNSET
```

Second, colliding temp paths are not just harmless overwrites. Each worker opens the same path with `>`, truncates it, streams multiple commands into it, then attempts to rename it. Those writes can interleave or truncate each other before any `mv` happens. The proposed tempfile does not isolate writers, so it does not fix the original race.

Claude made this argument cleanly and I fully agree with it.

### Gemini's `mv -n` recommendation changes semantics and still uses the wrong tempfile

Gemini proposes:

```bash
local tmp_file="$DEBATE_DIR/.FAILED.tmp.$$"
...
mv -n "$tmp_file" "$DEBATE_DIR/FAILED.txt" 2>/dev/null || rm -f "$tmp_file"
```

The `$$` problem remains, so concurrent workers can still share a single temp path.

The `mv -n` choice also changes the documented semantics. The current comment says:

```bash
# may invoke this; last writer wins — any of them is enough signal.
```

First-failure-wins is defensible, but it is a different policy. I would not slip that in as part of the parallel launch refactor. Preserve last-writer-wins with `mv -f` unless there is a separate decision to prefer the earliest failure snapshot.

### The plan overstates where diagnostics come from after worker failure

The original plan says that on any worker rc != 0, existing `wait_for_outputs` writes diagnostic `FAILED.txt`. With the proposed call site:

```bash
launch_agents_parallel r1 R1_PANES || exit 1
wait_for_outputs r1 "$STAGE_TIMEOUT" R1_PANES || exit 1
```

`wait_for_outputs` will not run after a helper failure. That is acceptable because the expected helper failures already call `write_failed` inside `launch_agent` or `send_prompt`. But the plan should state the actual behavior:

- launch/prompt timeout diagnostics are written by the worker subshell
- stage-output timeout diagnostics are written later by `wait_for_outputs`
- if a worker returns nonzero before its callee writes diagnostics, the helper currently only logs `[orch] ... worker exited non-zero`

That last case is probably rare, but the wording matters for debugging.

## Strongest Arguments from Other Agents

Claude's strongest contribution is the permanent observability suggestion. I did not emphasize this enough in Round 1. A concise log line from the helper, such as launch wall-clock and number of workers started, would provide cheap regression evidence in `orchestrator.log`. I would keep it if the log remains readable.

Gemini's strongest contribution is pointing out the fail-fast trade-off explicitly. Sequential `wait "$pid"` means an early failure in a later PID may not be reported until earlier workers finish. I still accept the trade-off because Bash 3.2 limits the options and all workers need to be reaped anyway, but the behavior should be understood.

## Required Amendment

Use `mktemp` in `DEBATE_DIR`, then atomic rename:

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

This preserves the existing last-writer-wins policy while ensuring each individual writer builds a complete, private diagnostic file before the atomic rename.

## New Considerations

### Helper failures without `write_failed`

The helper should either rely only on callees that write diagnostics before returning nonzero, or write a fallback `FAILED.txt` if any worker fails and no `FAILED.txt` exists. I would not add that fallback unless a concrete non-timeout failure path is found, but it is worth checking during implementation.

### Lock-held resume remains a pre-existing limitation

The lock-held branch kills the newly created pane and relies on an existing live pane:

```bash
if [ -f "$DEBATE_DIR/.r1_${agent}.lock" ]; then
  echo "[orch] r1/${agent} lock held by live pane, skipping launch (wait_for_outputs will observe)"
  hide_errors tmux_kill_pane "${R1_PANES[$i]}"
  continue
fi
```

`wait_for_outputs` still indexes the new pane array for capacity checks, not the pane ID from the lock. Parallel launch does not make this worse, but the comment "wait_for_outputs will observe" is only true for output files, not capacity rotation of the old locked pane.

### Test strategy should distinguish correctness from speed

Manual tmux observation is useful, but the implementation should include a deterministic harness test where three fake `launch_agent` calls sleep for a real short duration and the helper must complete below the serial threshold. The current resume tests can pass under both serial and parallel behavior.

A concurrent `write_failed` test should also be added after the `mktemp` change. It should assert exactly one header, exactly one section per missing agent, and no `.FAILED.txt.*` tempfiles left behind.

## Landing Criteria

I would approve the plan with these changes:

1. Add the shared `launch_agents_parallel` helper and use it for R1 and R2.
2. Replace the plan's `.$$` tempfile with `mktemp "$DEBATE_DIR/.FAILED.txt.XXXXXX"`.
3. Use `mv -f` to preserve the current last-writer-wins failure-reporting policy.
4. Correct the diagnostic-flow wording around helper failure versus `wait_for_outputs` failure.
5. Add a helper-level overlap test that fails under serial execution.
6. Add a concurrent `write_failed` test that would catch torn diagnostics.

With those amendments, the architecture is sound and the refactor should deliver the intended cold-start wall-clock reduction without weakening failure diagnostics.
