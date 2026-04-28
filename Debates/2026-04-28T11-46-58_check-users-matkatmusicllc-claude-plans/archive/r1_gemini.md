# Analysis of Parallel Launch Sequence Refactor

## Position
I strongly support the architectural shift to launch agents concurrently, but **I oppose executing the plan until the critical `write_failed` race condition is resolved.** The concurrency model provides significant wall-clock improvements, but moving `launch_agent` into background subshells turns the failure-reporting mechanism into a thread-safety hazard that will corrupt diagnostic logs precisely when they are most needed.

## Pros & Evidence of Benefit
Launching multi-agent shells (e.g., Claude Code, Gemini CLI, Codex) sequentially incurs heavy penalties due to synchronous network handshakes, auth checks, and Node/Python boot times. 

The strategy to encapsulate the launch in a subshell:
```bash
    (
      launch_agent "$pane_id" "$stage" "$agent" \
        "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" \
        || exit 1
      send_prompt "$pane_id" "$stage" "$agent" \
        "$DEBATE_DIR/${stage}_instructions_${agent}.txt" || exit 1
    ) &
```
This perfectly offloads the I/O bottleneck and cleanly traps failures via the `exit 1` propagation. Furthermore, the `wait_for_all` mechanism (`wait "$pid"`) is the correct native approach to barrier synchronization in macOS bash 3.2 environments, bypassing the lack of `wait -n`.

## Risks & The `write_failed` Race Condition
The most dangerous flaw in the current design stems from how `write_failed` handles file generation under concurrency. If a systemic event occurs (e.g., a network outage) causing multiple agents to timeout and fail simultaneously, multiple subshells will invoke `write_failed` at the exact same moment.

### Evidence of Code Risk
The current implementation assumes a "last writer wins" semantic, but bash I/O redirection does not buffer the entire block before writing:
```bash
write_failed() {
  local stage="$1" reason="$2"
  {
    printf '# debate FAILED\n\nstage: %s\nreason: %s\ntimestamp: %s\n\n' \
      "$stage" "$reason" "$(date -Iseconds)"
    printf '## missing agents\n'
    local agent lock pane_id
    for agent in "${AGENTS[@]}"; do
      # ... [loop logic] ...
      if [ -n "$pane_id" ]; then
        printf '```\n'
        hide_errors tmux capture-pane -t "$pane_id" -p -S -200 || printf '(pane capture unavailable)\n'
        printf '```\n'
      # ...
    done
  } > "$DEBATE_DIR/FAILED.txt"
}
```
Because the `{ ... } > "$DEBATE_DIR/FAILED.txt"` construct opens the file for truncation at the start of the block and then processes commands, concurrent executions will interleave their `printf` and `tmux capture-pane` streams. The result is a mangled, completely unreadable `FAILED.txt` file, actively destroying the diagnostic evidence of the crash.

## Concrete Solution
To ensure thread-safety across background workers, `write_failed` must use an atomic commit strategy. By writing the complete payload to a process-specific temporary file first, we can use `mv -n` (no-clobber) to guarantee that only the *first* failure cleanly writes the `FAILED.txt` file, while any concurrent failures discard their overlapping output safely.

### Corrected Implementation
```bash
write_failed() {
  local stage="$1" reason="$2"
  local tmp_file="$DEBATE_DIR/.FAILED.tmp.$$"

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
  } > "$tmp_file"

  # Atomic rename: -n prevents overwriting if another subshell already committed the FAILED.txt
  # The first failure is preserved completely intact.
  mv -n "$tmp_file" "$DEBATE_DIR/FAILED.txt" 2>/dev/null || rm -f "$tmp_file"
}
```

## Trade-offs
I acknowledge the trade-off in the `wait-all-then-check` logic inside `launch_agents_parallel`. Since we sequentially check `wait "${pids[$i]}"`, we lose the ability to fail-fast. A fast failure in the third agent won't be detected until the 120s timeout elapses for the first agent. While this theoretically extends failure response time, the 900s `STAGE_TIMEOUT` comfortably absorbs this delay. Given the hard constraint of macOS bash 3.2 compatibility, this trade-off is an acceptable cost for achieving robust parallelism. 

In conclusion: the logic for offloading the launch is completely sound, provided the I/O race condition in the failure path is secured via temporary files and atomic moves.