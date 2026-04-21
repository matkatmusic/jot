# Round 1 Analysis

## Position

The implementation in `@skills/debate/scripts/` is **partially accurate, but not fully faithful** to the finalized flow proven in `@skills/debate/tests/test.sh`.

My view: the extraction preserved the **main round sequencing correctly** and did carry over the most important control-flow fix (`wait_for_outputs r2` before killing R2 panes), but it also introduced at least **two material behavioral deviations**:

1. it removed the dedicated orchestrator pane that `test.sh` explicitly kept alive for synthesis
2. it kept the test harness's fixed 3-agent assumption in production code, even though the wrapper already contains provider-detection logic and claims broader `/debate` behavior

So this was not a bad extraction, but it was also not a precise one. I would call it **accurate on the skeleton, inaccurate on key operational details**.

## What Was Extracted Correctly

The core R1 -> R2 -> synthesis sequencing from `test.sh` did make it into `debate-tmux-orchestrator.sh`.

Evidence:

```bash
# test.sh
wait_for_outputs r1 "$STAGE_TIMEOUT" || exit 1

for i in "${!AGENTS[@]}"; do
  hide_errors tmux_kill_pane "${R1_PANES[$i]}"
done

DEBATE_AGENTS="${AGENTS[*]}" bash \
  "$CLAUDE_PLUGIN_ROOT/skills/debate/scripts/debate-build-prompts.sh" \
  r2 "$DEBATE_DIR" "$CLAUDE_PLUGIN_ROOT"

for i in "${!AGENTS[@]}"; do
  agent="${AGENTS[$i]}"; pane="${R2_PANES[$i]}"
  launch_agent "$pane" "$agent(r2)" "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" || exit 1
  send_prompt "$pane" "$agent(r2)" "$DEBATE_DIR/r2_instructions_${agent}.txt" || exit 1
done

wait_for_outputs r2 "$STAGE_TIMEOUT" || exit 1
```

```bash
# debate-tmux-orchestrator.sh
wait_for_outputs r1 "$STAGE_TIMEOUT" || exit 1

for i in "${!AGENTS[@]}"; do
  hide_errors tmux_kill_pane "${R1_PANES[$i]}"
done

DEBATE_AGENTS="${AGENTS[*]}" bash "$PLUGIN_ROOT/skills/debate/scripts/debate-build-prompts.sh" \
  r2 "$DEBATE_DIR" "$PLUGIN_ROOT"

for i in "${!AGENTS[@]}"; do
  agent="${AGENTS[$i]}"
  launch_agent "${R2_PANES[$i]}" "$agent(r2)" "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" || exit 1
  send_prompt  "${R2_PANES[$i]}" "$agent(r2)" "$DEBATE_DIR/r2_instructions_${agent}.txt" || exit 1
done

wait_for_outputs r2 "$STAGE_TIMEOUT" || exit 1
```

That is the critical backbone of the workflow, and it was ported faithfully.

## Material Inaccuracy 1: The Orchestrator Pane Was Removed

`test.sh` does not merely create "some pane later for synthesis." It creates a **dedicated orchestrator pane up front**, keeps it through R1 and R2, then reuses that exact pane for synthesis.

Reference flow:

```bash
# test.sh
tmux_ensure_session "$SESSION" "$WINDOW" "$PWD" "$KEEPALIVE_CMD" 'debate: keepalive'
PANE_ORCHESTRATOR=$(new_empty_pane)
R1_PANES=()
for agent in "${AGENTS[@]}"; do
  R1_PANES+=("$(new_empty_pane)")
done
...
launch_agent "$PANE_ORCHESTRATOR" "synthesis" "claude" "Claude Code v" || exit 1
send_prompt "$PANE_ORCHESTRATOR" "synthesis" "$DEBATE_DIR/synthesis_instructions.txt" || exit 1
```

Extracted implementation:

```bash
# debate.sh
tmux_ensure_session debate "$window_name" "$CWD" "$keepalive_cmd" 'debate: keepalive'
```

```bash
# debate-tmux-orchestrator.sh
R1_PANES=()
for agent in "${AGENTS[@]}"; do
  R1_PANES+=("$(new_empty_pane)")
done
...
SYNTH_PANE=$(new_empty_pane)
hide_output tmux_retile "$WINDOW_TARGET"
echo "[orch] synthesis pane: $SYNTH_PANE"
launch_agent "$SYNTH_PANE" "synthesis" "$(agent_launch_cmd claude)" "$(agent_ready_marker claude)" || exit 1
send_prompt  "$SYNTH_PANE" "synthesis" "$DEBATE_DIR/synthesis_instructions.txt" || exit 1
```

Why this matters:

- It changes the visual and architectural model from `keepalive + orchestrator + workers` to `keepalive + workers`, then later `keepalive + synthesis`.
- It means the implementation did **not actually extract phase 1 and phase 10 as written**; it rewrote them.
- The prior conversation explicitly described pane 1 as the synthesis/orchestrator pane, so this is not a harmless refactor. It is a behavior change.

This is the clearest evidence that the implementation was not fully accurate to the tested flow.

## Material Inaccuracy 2: Test-Only Agent Assumptions Leaked Into Production

The wrapper contains real provider-detection logic, but the actual entrypoint ignores it and hardcodes all three agents:

```bash
detect_available_agents() {
  AVAILABLE_AGENTS=(claude)
  ...
  if command -v gemini >/dev/null 2>&1; then
    ...
    AVAILABLE_AGENTS+=(gemini)
  fi
  ...
  if command -v codex >/dev/null 2>&1; then
    ...
    AVAILABLE_AGENTS+=(codex)
  fi
}
```

```bash
# debate_main
# Fixed agent list for the TUI-driven flow. Detection logic preserved
# above (detect_available_agents) for a future re-enable.
AVAILABLE_AGENTS=(gemini codex claude)
if [ "${#AVAILABLE_AGENTS[@]}" -lt 2 ]; then
  emit_block "debate requires at least 2 agents. Found: ${AVAILABLE_AGENTS[*]}."
  exit 0
fi
```

Why this is inaccurate:

- In `test.sh`, hardcoding `AGENTS=(gemini codex claude)` is fine because the test is a controlled harness.
- In `/debate`, this becomes a product behavior decision. The extraction should either:
  - call `detect_available_agents`, or
  - explicitly validate that all three binaries/auth states are present before spawning.
- As written, the production wrapper inherits a test assumption without adapting it to real runtime conditions.

That is exactly the kind of mistake that happens when code is extracted mechanically from a test: the happy-path assumptions come along too.

## Smaller Deltas

These are less serious, but still relevant:

- The script waits for `synthesis.md` to be written before logging completion, while `test.sh` stops at "synthesis launched." I consider this an acceptable extension, not a bug.
- `test.sh` explicitly deletes old `r1_*.md`, `r2_*.md`, and `synthesis.md` files before each stage. The production path skips that, but because it creates a fresh timestamped debate directory, the omission is functionally harmless.

## Overall Assessment

If the question is "did the implementation successfully port the central debate loop from the test harness?", the answer is **yes**.

If the question is "was it an accurate implementation of the finalized `test.sh` flow?", the answer is **no, not completely**.

My judgment:

- **Accurate:** round ordering, prompt generation stages, waiting for R1/R2 outputs, killing worker panes, background daemon model
- **Inaccurate:** orchestrator-pane preservation, and promotion of test-only fixed-agent assumptions into production hook code

So the implementation was **good enough to prove the concept**, but **not accurate enough to claim it cleanly extracted the finalized flow without semantic drift**.

## What I Would Change

I would make two concrete corrections:

1. create the orchestrator pane up front in the tmux window and pass its pane id into the daemon so synthesis reuses it exactly as `test.sh` does
2. stop hardcoding `AVAILABLE_AGENTS=(gemini codex claude)` in `debate_main`; either call `detect_available_agents` or fail early with an explicit "missing gemini/codex" requirement if the product truly requires all three

Those two changes would move the implementation from "mostly extracted" to "actually faithful."
