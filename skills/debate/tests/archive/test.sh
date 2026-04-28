set -uo pipefail

# === setup ===
CLAUDE_PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/../../.." && pwd)}"
. "$CLAUDE_PLUGIN_ROOT/common/scripts/silencers.sh"
. "$CLAUDE_PLUGIN_ROOT/common/scripts/invoke_command.sh"
. "$CLAUDE_PLUGIN_ROOT/common/scripts/tmux.sh"
. "$CLAUDE_PLUGIN_ROOT/common/scripts/tmux-launcher.sh"

SESSION="debate"
WINDOW="test-$$"
WINDOW_TARGET="${SESSION}:${WINDOW}"
KEEPALIVE_CMD='exec sh -c '\''trap "" INT HUP TERM; printf "[debate test keepalive]\n"; exec tail -f /dev/null'\'''

DEBATE_DIR="/Users/matkatmusicllc/Programming/Charles/Programming/authv3_vps/Debates/2026-04-20T20-52-46_identify-the-1-issue-causing-customer-au"
AGENTS=(gemini codex claude)
STAGE_TIMEOUT=$((15 * 60))  # 15 min per round

# === agent lookup ===
agent_launch_cmd() {
  case "$1" in
    # --allowed-tools: bypass approval for read_file + write_file only
    # (minimum needed for the debate flow).
    gemini) echo "gemini --allowed-tools 'read_file,write_file'" ;;
    # -a never: codex never prompts for approval.
    # --add-dir: grants write access to $DEBATE_DIR (preferred per codex docs
    # over --sandbox danger-full-access for targeted write permissions).
    codex)  echo "codex -a never --add-dir '$DEBATE_DIR'" ;;
    claude) echo "claude" ;;
  esac
}
agent_ready_marker() {
  case "$1" in
    gemini) echo "Type your message or @path/to/file" ;;
    codex)  echo "/model to change" ;;
    claude) echo "Claude Code v" ;;
  esac
}

# === tmux helpers ===
new_empty_pane() {
  hide_output tmux_retile "$WINDOW_TARGET"
  tmux_new_pane "$WINDOW_TARGET" -c "$PWD" -P -F '#{pane_id}'
}

# launch_agent <pane_id> <label> <launch_cmd> <ready_marker> [timeout]
launch_agent() {
  local pane_id="$1" label="$2" launch_cmd="$3" ready_marker="$4"
  local timeout="${5:-30}"
  tmux_send_and_submit "$pane_id" "$launch_cmd"
  local elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    if hide_errors tmux capture-pane -t "$pane_id" -p | grep -qF "$ready_marker"; then
      echo "[test] $label ready after ${elapsed}s (pane $pane_id)"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  echo "[test] TIMEOUT: $label not ready within ${timeout}s" >&2
  return 1
}

# send_prompt <pane_id> <label> <instructions_file>
send_prompt() {
  local pane_id="$1" label="$2" instructions="$3"
  tmux_send_and_submit "$pane_id" "read $instructions and perform them"
  local marker
  marker=$(basename "$instructions")
  local elapsed=0
  while [ "$elapsed" -lt 10 ]; do
    if hide_errors tmux capture-pane -t "$pane_id" -p | grep -qF "$marker"; then
      echo "[test] $label prompt received after ${elapsed}s"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  echo "[test] TIMEOUT: $label did not echo prompt" >&2
  return 1
}

# wait_for_outputs <prefix> <timeout>
# Polls $DEBATE_DIR/<prefix>_<agent>.md for each agent, logs each completion, returns when all present.
wait_for_outputs() {
  local prefix="$1" timeout="$2"
  local reported=""
  local elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    local done_count=0
    local agent
    for agent in "${AGENTS[@]}"; do
      local out="$DEBATE_DIR/${prefix}_${agent}.md"
      if [ -s "$out" ]; then
        done_count=$((done_count + 1))
        case " $reported " in
          *" $agent "*) ;;
          *) printf '\n[test] %s: %s wrote %s (%ds)\n' "$prefix" "$agent" "$(basename "$out")" "$elapsed"
             reported="$reported $agent" ;;
        esac
      fi
    done
    if [ "$done_count" -eq "${#AGENTS[@]}" ]; then
      printf '[test] %s: all %d outputs present after %ds\n' "$prefix" "${#AGENTS[@]}" "$elapsed"
      return 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
    printf '\r[test] %s: %d/%d outputs (%ds/%ds)  ' "$prefix" "$done_count" "${#AGENTS[@]}" "$elapsed" "$timeout"
  done
  printf '\n[test] TIMEOUT: %s outputs incomplete after %ds\n' "$prefix" "$timeout" >&2
  return 1
}

# === phase 1: session + 5 panes ===
tmux_ensure_session "$SESSION" "$WINDOW" "$PWD" "$KEEPALIVE_CMD" 'debate: keepalive'
PANE_ORCHESTRATOR=$(new_empty_pane)
R1_PANES=()
for agent in "${AGENTS[@]}"; do
  R1_PANES+=("$(new_empty_pane)")
done
hide_output tmux_retile "$WINDOW_TARGET"
echo "[test] R1 panes: orchestrator=$PANE_ORCHESTRATOR agents=[${AGENTS[*]}]=[${R1_PANES[*]}]"
sleep 1

# === phase 2: build R1 instructions per agent ===
for agent in "${AGENTS[@]}"; do
  rm -f "$DEBATE_DIR/r1_${agent}.md"
done
DEBATE_AGENTS="${AGENTS[*]}" bash \
  "$CLAUDE_PLUGIN_ROOT/skills/debate/scripts/debate-build-prompts.sh" \
  r1 "$DEBATE_DIR" "$CLAUDE_PLUGIN_ROOT"

# === phase 3: launch R1 agents + send prompts ===
for i in "${!AGENTS[@]}"; do
  agent="${AGENTS[$i]}"; pane="${R1_PANES[$i]}"
  launch_agent "$pane" "$agent" "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" || exit 1
  send_prompt "$pane" "$agent" "$DEBATE_DIR/r1_instructions_${agent}.txt" || exit 1
done

# === phase 4: wait for all R1 outputs ===
wait_for_outputs r1 "$STAGE_TIMEOUT" || exit 1

# === phase 5: kill R1 agent panes ===
for i in "${!AGENTS[@]}"; do
  hide_errors tmux_kill_pane "${R1_PANES[$i]}"
done
hide_output tmux_retile "$WINDOW_TARGET"
echo "[test] R1 agent panes closed"

# === phase 6: build R2 instructions per agent ===
for agent in "${AGENTS[@]}"; do
  rm -f "$DEBATE_DIR/r2_${agent}.md"
done
DEBATE_AGENTS="${AGENTS[*]}" bash \
  "$CLAUDE_PLUGIN_ROOT/skills/debate/scripts/debate-build-prompts.sh" \
  r2 "$DEBATE_DIR" "$CLAUDE_PLUGIN_ROOT"

# === phase 7: spawn 3 fresh R2 panes + launch ===
R2_PANES=()
for agent in "${AGENTS[@]}"; do
  R2_PANES+=("$(new_empty_pane)")
done
hide_output tmux_retile "$WINDOW_TARGET"
echo "[test] R2 panes: agents=[${AGENTS[*]}]=[${R2_PANES[*]}]"
sleep 1

for i in "${!AGENTS[@]}"; do
  agent="${AGENTS[$i]}"; pane="${R2_PANES[$i]}"
  launch_agent "$pane" "$agent(r2)" "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" || exit 1
  send_prompt "$pane" "$agent(r2)" "$DEBATE_DIR/r2_instructions_${agent}.txt" || exit 1
done

# === phase 7.5: wait for all R2 outputs ===
wait_for_outputs r2 "$STAGE_TIMEOUT" || exit 1

# === phase 8: kill R2 agent panes ===
for i in "${!AGENTS[@]}"; do
  hide_errors tmux_kill_pane "${R2_PANES[$i]}"
done
hide_output tmux_retile "$WINDOW_TARGET"
echo "[test] R2 agent panes closed"

# === phase 9: build synthesis instructions ===
rm -f "$DEBATE_DIR/synthesis.md" "$DEBATE_DIR/synthesis_instructions.txt"
DEBATE_AGENTS="${AGENTS[*]}" bash \
  "$CLAUDE_PLUGIN_ROOT/skills/debate/scripts/debate-build-prompts.sh" \
  synthesis "$DEBATE_DIR" "$CLAUDE_PLUGIN_ROOT"

# === phase 10: launch Claude synthesis in the orchestrator pane ===
launch_agent "$PANE_ORCHESTRATOR" "synthesis" "claude" "Claude Code v" || exit 1
send_prompt "$PANE_ORCHESTRATOR" "synthesis" "$DEBATE_DIR/synthesis_instructions.txt" || exit 1

echo "[test] synthesis launched in pane $PANE_ORCHESTRATOR — monitor $DEBATE_DIR/synthesis.md"
