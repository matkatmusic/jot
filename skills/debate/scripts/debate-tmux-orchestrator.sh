#!/bin/bash
# debate-tmux-orchestrator.sh — background daemon that drives the full
# R1 → R2 → synthesis flow inside the 'debate' tmux session. Forked from
# debate.sh via: bash <this> ... >> orchestrator.log 2>&1 </dev/null &
#
# Preconditions (set up by debate.sh before forking):
#   - tmux session 'debate' exists with window $WINDOW_NAME and a keepalive pane
#   - $DEBATE_DIR/{topic.md,context.md,agents.txt,r1_instructions_<agent>.txt} all present
#   - $SETTINGS_FILE is a claude settings.json granting writes to $DEBATE_DIR/**
#
# Pane-lifecycle rationale: agent panes are spawned just-in-time for each
# stage and killed when the stage completes (R1 panes go away before R2
# spawns; R2 panes go away before synthesis spawns). This differs from
# test.sh, which kept an idle "orchestrator" pane alive across stages —
# that was a test-harness artifact for the attended external driver. In
# production, the driver is this script (not a pane), so the persistent
# orchestrator pane served no purpose and was dropped.
set -uo pipefail

DEBATE_DIR="$1"
WINDOW_NAME="$2"
SETTINGS_FILE="$3"
CWD="$4"
REPO_ROOT="$5"
PLUGIN_ROOT="$6"

SESSION="debate"
WINDOW_TARGET="${SESSION}:${WINDOW_NAME}"
STAGE_TIMEOUT=$((15 * 60))

. "$PLUGIN_ROOT/common/scripts/silencers.sh"
. "$PLUGIN_ROOT/common/scripts/invoke_command.sh"
. "$PLUGIN_ROOT/common/scripts/tmux.sh"
. "$PLUGIN_ROOT/common/scripts/tmux-launcher.sh"

# Best-effort cleanup on daemon exit (success or failure). Fires via trap EXIT.
# 1. Remove the per-invocation settings tmpdir (/tmp/debate.XXXXXX) created by
#    debate.sh:debate_build_claude_cmd. Case-match guards against rm-ing a
#    misconfigured SETTINGS_FILE pointing anywhere else.
# 2. Kill this debate's window (keepalive + any surviving agent panes). The
#    window-scoped kill preserves concurrent debates running in the same session.
cleanup() {
  local settings_dir
  settings_dir=$(dirname "$SETTINGS_FILE")
  case "$settings_dir" in
    /tmp/debate.*) rm -rf "$settings_dir" ;;
  esac
  hide_errors tmux_kill_window "$WINDOW_TARGET"
}
trap cleanup EXIT

# Read agents manifest (bash-3-safe)
AGENTS=()
while IFS= read -r line; do
  [ -n "$line" ] && AGENTS+=("$line")
done < "$DEBATE_DIR/agents.txt"

# === agent lookup ===
agent_launch_cmd() {
  case "$1" in
    # --allowed-tools bypasses approval for exactly the tools the debate flow needs:
    # read_file (topic/context/other agents' outputs) + write_file (r<N>_gemini.md).
    # Any other tool use (shell, edit, glob) will still prompt — and since no one
    # is watching the pane, that will hit the stage timeout and surface as a failure.
    gemini) echo "gemini --allowed-tools 'read_file,write_file'" ;;
    # -a never: codex never prompts for approval (non-interactive-safe).
    # --add-dir: grants write access to $DEBATE_DIR (codex docs: prefer this
    # over --sandbox danger-full-access for targeted write permissions).
    codex)  echo "codex -a never --add-dir '$DEBATE_DIR'" ;;
    # --settings grants Claude write perms to Debates/** (see assets/permissions.default.json).
    claude) echo "claude --settings '$SETTINGS_FILE' --add-dir '$CWD' --add-dir '$REPO_ROOT'" ;;
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
  tmux_new_pane "$WINDOW_TARGET" -c "$CWD" -P -F '#{pane_id}'
}

# launch_agent <pane_id> <label> <launch_cmd> <ready_marker> [timeout]
launch_agent() {
  local pane_id="$1" label="$2" launch_cmd="$3" ready_marker="$4"
  local timeout="${5:-30}"
  tmux_send_and_submit "$pane_id" "$launch_cmd"
  local elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    if hide_errors tmux capture-pane -t "$pane_id" -p | grep -qF "$ready_marker"; then
      echo "[orch] $label ready after ${elapsed}s (pane $pane_id)"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  echo "[orch] TIMEOUT: $label not ready within ${timeout}s" >&2
  return 1
}

# send_prompt <pane_id> <label> <instructions_file>
send_prompt() {
  local pane_id="$1" label="$2" instructions="$3"
  tmux_send_and_submit "$pane_id" "read $instructions and perform them"
  local marker
  marker=$(basename "$instructions")
  # 30s window: detached daemon has no observer, so allow more slack than test.sh's
  # attended 10s before declaring the echo-verification a silent failure.
  local elapsed=0
  while [ "$elapsed" -lt 30 ]; do
    if hide_errors tmux capture-pane -t "$pane_id" -p | grep -qF "$marker"; then
      echo "[orch] $label prompt received after ${elapsed}s"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  echo "[orch] TIMEOUT: $label did not echo prompt" >&2
  return 1
}

# wait_for_outputs <prefix> <timeout>
# Assumes agents write outputs atomically (e.g. Claude's Write tool does
# temp-then-rename). If an agent streams or uses shell redirection, the
# `[ -s "$out" ]` check could fire on the first byte and racing kills
# the pane mid-stream. Keep this invariant in mind before swapping the
# launch command to any mode that doesn't write atomically.
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
          *) printf '\n[orch] %s: %s wrote %s (%ds)\n' "$prefix" "$agent" "$(basename "$out")" "$elapsed"
             reported="$reported $agent" ;;
        esac
      fi
    done
    if [ "$done_count" -eq "${#AGENTS[@]}" ]; then
      printf '[orch] %s: all %d outputs present after %ds\n' "$prefix" "${#AGENTS[@]}" "$elapsed"
      return 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
    printf '\r[orch] %s: %d/%d outputs (%ds/%ds)  ' "$prefix" "$done_count" "${#AGENTS[@]}" "$elapsed" "$timeout"
  done
  printf '\n[orch] TIMEOUT: %s outputs incomplete after %ds\n' "$prefix" "$timeout" >&2
  return 1
}

# wait_for_file <path> <timeout>
# Polls until the file is non-empty. Returns 0 on success, 1 on timeout.
wait_for_file() {
  local path="$1" timeout="$2"
  local elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    if [ -s "$path" ]; then
      printf '\n[orch] %s present after %ds\n' "$(basename "$path")" "$elapsed"
      return 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
    printf '\r[orch] waiting for %s (%ds/%ds)  ' "$(basename "$path")" "$elapsed" "$timeout"
  done
  printf '\n[orch] TIMEOUT: %s never written after %ds\n' "$(basename "$path")" "$timeout" >&2
  return 1
}

echo "========================================"
echo "[orch] DEBATE DAEMON"
echo "[orch] Dir:     $DEBATE_DIR"
echo "[orch] Window:  $WINDOW_TARGET"
echo "[orch] Agents:  ${AGENTS[*]} (${#AGENTS[@]})"
echo "[orch] Timeout: ${STAGE_TIMEOUT}s per stage"
echo "========================================"

# === R1: spawn agent panes, send prompts ===
R1_PANES=()
for agent in "${AGENTS[@]}"; do
  R1_PANES+=("$(new_empty_pane)")
done
hide_output tmux_retile "$WINDOW_TARGET"
echo "[orch] R1 panes: agents=[${AGENTS[*]}]=[${R1_PANES[*]}]"
sleep 1
for i in "${!AGENTS[@]}"; do
  agent="${AGENTS[$i]}"
  launch_agent "${R1_PANES[$i]}" "$agent(r1)" "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" || exit 1
  send_prompt  "${R1_PANES[$i]}" "$agent(r1)" "$DEBATE_DIR/r1_instructions_${agent}.txt" || exit 1
done

wait_for_outputs r1 "$STAGE_TIMEOUT" || exit 1

# Kill R1 panes
for i in "${!AGENTS[@]}"; do
  hide_errors tmux_kill_pane "${R1_PANES[$i]}"
done
hide_output tmux_retile "$WINDOW_TARGET"
echo "[orch] R1 agent panes closed"

# === R2: build prompts, spawn fresh panes ===
DEBATE_AGENTS="${AGENTS[*]}" bash "$PLUGIN_ROOT/skills/debate/scripts/debate-build-prompts.sh" \
  r2 "$DEBATE_DIR" "$PLUGIN_ROOT"

R2_PANES=()
for agent in "${AGENTS[@]}"; do
  R2_PANES+=("$(new_empty_pane)")
done
hide_output tmux_retile "$WINDOW_TARGET"
echo "[orch] R2 panes: agents=[${AGENTS[*]}]=[${R2_PANES[*]}]"
sleep 1
for i in "${!AGENTS[@]}"; do
  agent="${AGENTS[$i]}"
  launch_agent "${R2_PANES[$i]}" "$agent(r2)" "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" || exit 1
  send_prompt  "${R2_PANES[$i]}" "$agent(r2)" "$DEBATE_DIR/r2_instructions_${agent}.txt" || exit 1
done

wait_for_outputs r2 "$STAGE_TIMEOUT" || exit 1

# Kill R2 panes
for i in "${!AGENTS[@]}"; do
  hide_errors tmux_kill_pane "${R2_PANES[$i]}"
done
hide_output tmux_retile "$WINDOW_TARGET"
echo "[orch] R2 agent panes closed"

# === Synthesis: build prompt, spawn single Claude pane ===
DEBATE_AGENTS="${AGENTS[*]}" bash "$PLUGIN_ROOT/skills/debate/scripts/debate-build-prompts.sh" \
  synthesis "$DEBATE_DIR" "$PLUGIN_ROOT"

SYNTH_PANE=$(new_empty_pane)
hide_output tmux_retile "$WINDOW_TARGET"
echo "[orch] synthesis pane: $SYNTH_PANE"
sleep 1
launch_agent "$SYNTH_PANE" "synthesis" "$(agent_launch_cmd claude)" "$(agent_ready_marker claude)" || exit 1
send_prompt  "$SYNTH_PANE" "synthesis" "$DEBATE_DIR/synthesis_instructions.txt" || exit 1

wait_for_file "$DEBATE_DIR/synthesis.md" "$STAGE_TIMEOUT" || exit 1

# === archive intermediate files ===
# Keep only synthesis.md at the top level; stash inputs, round outputs,
# and the daemon log under archive/ so the deliverable is unambiguous.
echo "[orch] archiving intermediate files to $DEBATE_DIR/archive/"
mkdir -p "$DEBATE_DIR/archive"
for f in \
    "$DEBATE_DIR/topic.md" \
    "$DEBATE_DIR/context.md" \
    "$DEBATE_DIR/agents.txt" \
    "$DEBATE_DIR/synthesis_instructions.txt" \
    "$DEBATE_DIR"/r1_instructions_*.txt \
    "$DEBATE_DIR"/r1_*.md \
    "$DEBATE_DIR"/r2_instructions_*.txt \
    "$DEBATE_DIR"/r2_*.md \
    ; do
  [ -f "$f" ] && mv "$f" "$DEBATE_DIR/archive/"
done

echo "[orch] DEBATE COMPLETE — synthesis at $DEBATE_DIR/synthesis.md"

# Move the log last so the completion line lands in the pre-move file.
# Same-filesystem rename preserves the daemon's still-open stdout fd:
# Unix ties the fd to the inode, not the path, so writes after this
# rename continue to land in archive/orchestrator.log transparently.
[ -f "$DEBATE_DIR/orchestrator.log" ] && mv "$DEBATE_DIR/orchestrator.log" "$DEBATE_DIR/archive/"
