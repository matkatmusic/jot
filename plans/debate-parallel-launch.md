# /jot:debate — Parallel agent-launch refactor

**Goal:** spawn all R1/R2 agent CLIs concurrently instead of serially. Reduces stage-launch wall-clock from ~3×(boot+prompt) to ~1×(boot+prompt). For 3 agents with 120s ready-marker timeout + 30s prompt-echo timeout, worst-case savings ≈ 2 × 150s = 300s per stage.

## Decisions (settled via /grill-me)

| # | Decision | Rationale |
|---|----------|-----------|
| Q1 | Parallelize **full** `launch_agent` + `send_prompt` per agent (not just `launch_agent`) | Two phases are independent per agent (separate panes, separate lock files); single sync barrier; symmetric worker. |
| Q2 | **Wait-all-then-check** failure semantics (no `wait -n`, no fail-fast) | Bash 3.2 compatible (macOS); simpler; STAGE_TIMEOUT=900s already absorbs worst-case ~120s extra wait on sibling failure; `wait_for_outputs` writes diagnostic FAILED.txt with all 3 pane captures. |
| Q3 | Apply to **R1 and R2** (synthesis is single-agent, irrelevant) | Identical launch pattern; refactor once. |

## Out of scope

- Pane creation loop (`debate-tmux-orchestrator.sh:432-435` and `:475-477`) — already as parallel as tmux allows; not the bottleneck.
- Capacity-rotation path (`retry_pane_with_next_model`) — runs only inside `wait_for_outputs` after launches complete, so subshell state isolation does not affect it. No changes required.
- Synthesis stage (`:506-530`) — single agent, no parallelism possible.

## Implementation

### 1. New helper: `launch_agents_parallel`

Add to `debate-tmux-orchestrator.sh` between existing helpers and `daemon_main`. Replaces the inline launch+prompt loops in both rounds.

```bash
# launch_agents_parallel <stage> <panes_arrayname>
# Backgrounds (launch_agent && send_prompt) for every agent in $AGENTS
# whose r{stage}_<agent>.md is missing and lock is free. Waits for all
# workers; returns 0 iff every worker exited 0.
#
# bash 3.2 compat: no `wait -n`. PIDs collected into array, individual
# `wait $pid` calls capture rcs. State mutation in subshells (e.g. _stash
# writes) is intentionally not relied on here — capacity-rotation runs
# later in wait_for_outputs, in the main shell.
launch_agents_parallel() {
  local stage="$1" panes_var="$2"
  local pids=() agents_run=() i agent pane_id rc fail=0

  for i in "${!AGENTS[@]}"; do
    agent="${AGENTS[$i]}"
    eval "pane_id=\${${panes_var}[$i]}"

    if [ -s "$DEBATE_DIR/${stage}_${agent}.md" ]; then
      echo "[orch] ${stage}/${agent} already complete, skipping launch"
      hide_errors tmux_kill_pane "$pane_id"
      continue
    fi
    if [ -f "$DEBATE_DIR/.${stage}_${agent}.lock" ]; then
      echo "[orch] ${stage}/${agent} lock held by live pane, skipping launch"
      hide_errors tmux_kill_pane "$pane_id"
      continue
    fi

    (
      launch_agent "$pane_id" "$stage" "$agent" \
        "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" \
        || exit 1
      send_prompt "$pane_id" "$stage" "$agent" \
        "$DEBATE_DIR/${stage}_instructions_${agent}.txt" || exit 1
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

**Notes:**
- Subshell `( ... ) &` isolates each worker. The only state mutation in `launch_agent`/`send_prompt` is the per-agent lock file (filesystem, not env), so subshell isolation is fine.
- Worker rc=1 propagates via subshell `exit 1`; parent collects via `wait $pid`.
- `agents_run` array tracks which agents were actually backgrounded (parallels `pids`), so error messages name the right agent. Skipped agents are not included.
- No log-prefix mangling: `launch_agent`/`send_prompt` already prefix with `[orch] ${stage}/${agent}`. Interleaved output stays attributable.

### 2. R1 call site — replace `:438-452`

**Before:**
```bash
sleep 1
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

**After:**
```bash
sleep 1
launch_agents_parallel r1 R1_PANES || exit 1
```

### 3. R2 call site — replace `:481-495`

**Before:** equivalent serial loop using `R2_PANES` and `r2_*` paths.

**After:**
```bash
sleep 1
launch_agents_parallel r2 R2_PANES || exit 1
```

### 4. Synthesis stage — no change

Lines `:520-525` already launch a single Claude pane. Parallelism is undefined for n=1.

## Compat notes

- **Bash 3.2 (macOS).** No `wait -n`, no `declare -gA`, no namerefs. Helper uses positional `wait $pid` and pane-array access via `eval`, matching the rest of the file's idiom (see `_stash`/`_lookup` rationale at `:73-82`).
- **Test harness (`DEBATE_DAEMON_SOURCED=1`).** Harness sources the script and stubs `launch_agent` / `send_prompt` (per `:22-32`). Backgrounded shell-function stubs work normally; they execute in a subshell with the parent's function definitions inherited. The harness must not depend on launch ordering — verify before merge.
- **Capacity rotation.** `retry_pane_with_next_model` (`:178-201`) only fires inside `wait_for_outputs`, which is sequential and runs in the main daemon shell. The `_stash`/`eval` state mutations there continue to work. Parallelization touches only the launch phase.

## Verification (per ~/.claude/Rules/feedback_verify_work.md)

Design a test that **fails** if the launches are still serial:

1. **Timing assertion.** Add a temporary `date +%s` capture before and after `launch_agents_parallel r1`. Run a fresh debate. Expected: elapsed ≈ max(per-agent boot+prompt). Fail criterion: elapsed ≥ 1.5 × per-agent average (i.e. evidence of serialization).
2. **Concurrency proof.** During R1 launch, sample `tmux list-panes -t debate-N:main -F '#{pane_current_command}'` once at ~T+10s. Expected: 3 agent commands present simultaneously (`gemini`, `codex`, `claude`). Fail criterion: only 1 or 2 agent commands and the rest still in shell.
3. **Failure-path smoke.** Force one agent's launch to fail (e.g. point its CLI to a missing binary via `agent_launch_cmd` override in a harness test). Expected: helper returns 1, FAILED.txt written by `wait_for_outputs` with that agent's pane capture, daemon exits non-zero. Fail criterion: helper returns 0 or daemon hangs past STAGE_TIMEOUT.
4. **Resume-path regression.** Pre-create `r1_gemini.md` and `.r1_codex.lock`. Run the daemon. Expected: gemini and codex skipped, claude launched alone. Fail criterion: any of: gemini relaunched, codex pane killed despite live lock, claude not launched.

All four checks must pass before commit.

## Risk surface

| Risk | Mitigation |
|------|------------|
| Three concurrent `tmux send-keys` to different panes — tmux serializes server-side, so safe. | None needed; documented for reviewers. |
| Subshell can't propagate `_stash` mutations to parent. | Not relied on; capacity rotation runs post-launch in main shell. |
| Interleaved log output harder to read. | Existing `[orch] ${stage}/${agent}` prefix preserves attribution. |
| Worker subshell crashes before `launch_agent` writes its lock — `wait_for_outputs` won't see a lock to capture from. | Existing `write_failed` path falls back to `(no pane captured — lock file missing or malformed)`. Acceptable. |
| Test-harness ordering assumption. | Read harness before merge; if it asserts call-order on stubs, refactor to assert call-set instead. |
