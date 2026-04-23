#!/bin/bash
# debate-tmux-orchestrator.sh — background daemon that drives the full
# R1 → R2 → synthesis flow inside the 'debate' tmux session. Forked from
# debate.sh via: bash <this> ... >> orchestrator.log 2>&1 </dev/null &
#
# Preconditions (set up by debate.sh before forking):
#   - tmux session 'debate' exists with window $WINDOW_NAME and a keepalive pane
#   - $DEBATE_DIR/{topic.md,context.md,invoking_transcript.txt,r1_instructions_<agent>.txt} all present
#   - $DEBATE_AGENTS env var holds the space-separated agent list for this debate
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

# When sourced by the integration harness, the caller pre-sets these as
# env vars and sets DEBATE_DAEMON_SOURCED=1 to skip positional parsing.
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
# Harness installs its own (no-op) cleanup before calling daemon_main.
if [ "${DEBATE_DAEMON_SOURCED:-0}" != 1 ]; then
  trap cleanup EXIT
fi

: "${DEBATE_AGENTS:?DEBATE_AGENTS env var required}"
IFS=' ' read -r -a AGENTS <<< "$DEBATE_AGENTS"

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

# archive_debate
# Moves intermediate artifacts to $DEBATE_DIR/archive/. Keeps topic.md,
# synthesis.md, invoking_transcript.txt at top level. Called at the end
# of a fresh run AND at the top of the daemon when synthesis.md is
# already present (jump-to-archive on resume).
archive_debate() {
  echo "[orch] archiving intermediate files to $DEBATE_DIR/archive/"
  mkdir -p "$DEBATE_DIR/archive"
  local f
  for f in \
      "$DEBATE_DIR/context.md" \
      "$DEBATE_DIR/synthesis_instructions.txt" \
      "$DEBATE_DIR"/r1_instructions_*.txt \
      "$DEBATE_DIR"/r1_*.md \
      "$DEBATE_DIR"/r2_instructions_*.txt \
      "$DEBATE_DIR"/r2_*.md \
      ; do
    [ -f "$f" ] && mv "$f" "$DEBATE_DIR/archive/"
  done
  [ -f "$DEBATE_DIR/orchestrator.log" ] && mv "$DEBATE_DIR/orchestrator.log" "$DEBATE_DIR/archive/"
}

# clean_stale_locks <stage>
# For each .<stage>_<agent>.lock, verify (a) pane_id still exists and
# (b) pane_current_command matches the expected agent binary. Any failure
# → rm the lock.
clean_stale_locks() {
  local stage="$1"
  local lock agent pane_id current
  for lock in "$DEBATE_DIR"/.${stage}_*.lock; do
    [ -f "$lock" ] || continue
    agent=$(basename "$lock" .lock)
    agent="${agent#.${stage}_}"
    pane_id=$(sed -n 's|^debate:\(%[0-9]*\)$|\1|p' "$lock")
    if [ -z "$pane_id" ]; then rm -f "$lock"; continue; fi
    if ! hide_errors tmux list-panes -t "$WINDOW_TARGET" -F '#{pane_id}' | grep -qFx "$pane_id"; then
      rm -f "$lock"; continue
    fi
    current=$(hide_errors tmux display-message -p -t "$pane_id" '#{pane_current_command}')
    if [ "$current" != "$agent" ]; then rm -f "$lock"; fi
  done
}

# write_failed <stage> <reason>
# Emits $DEBATE_DIR/FAILED.txt with the stage, reason, timestamp, and a
# tmux capture-pane dump of every agent whose stage output is missing.
# Any caller (launch_agent, send_prompt, wait_for_outputs, wait_for_file)
# may invoke this; last writer wins — any of them is enough signal.
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

# launch_agent <pane_id> <stage> <agent> <launch_cmd> <ready_marker> [timeout]
launch_agent() {
  local pane_id="$1" stage="$2" agent="$3" launch_cmd="$4" ready_marker="$5"
  local timeout="${6:-30}"
  printf 'debate:%s\n' "$pane_id" > "$DEBATE_DIR/.${stage}_${agent}.lock"
  tmux_send_and_submit "$pane_id" "$launch_cmd"
  local elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    if hide_errors tmux capture-pane -t "$pane_id" -p | grep -qF "$ready_marker"; then
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

# send_prompt <pane_id> <stage> <agent> <instructions_file>
send_prompt() {
  local pane_id="$1" stage="$2" agent="$3" instructions="$4"
  tmux_send_and_submit "$pane_id" "read $instructions and perform them"
  local marker
  marker=$(basename "$instructions")
  # 30s window: detached daemon has no observer, so allow more slack than test.sh's
  # attended 10s before declaring the echo-verification a silent failure.
  local elapsed=0
  while [ "$elapsed" -lt 30 ]; do
    if hide_errors tmux capture-pane -t "$pane_id" -p | grep -qF "$marker"; then
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
        rm -f "$DEBATE_DIR/.${prefix}_${agent}.lock"
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
  write_failed "$prefix" "wait_for_outputs timeout after ${timeout}s"
  return 1
}

# wait_for_file <path> <timeout>
# Polls until the file is non-empty. Returns 0 on success, 1 on timeout.
wait_for_file() {
  local path="$1" timeout="$2"
  local elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    if [ -s "$path" ]; then
      rm -f "$DEBATE_DIR/.synthesis_claude.lock"
      printf '\n[orch] %s present after %ds\n' "$(basename "$path")" "$elapsed"
      return 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
    printf '\r[orch] waiting for %s (%ds/%ds)  ' "$(basename "$path")" "$elapsed" "$timeout"
  done
  printf '\n[orch] TIMEOUT: %s never written after %ds\n' "$(basename "$path")" "$timeout" >&2
  write_failed synthesis "wait_for_file timeout after ${timeout}s ($(basename "$path") missing)"
  return 1
}

# daemon_main
# Wraps the full R1→R2→synthesis→archive pipeline so a test harness can
# source this script (picking up all helper definitions) and invoke
# daemon_main with tmux / launch_agent / send_prompt stubbed.
daemon_main() {
echo "========================================"
echo "[orch] DEBATE DAEMON"
echo "[orch] Dir:     $DEBATE_DIR"
echo "[orch] Window:  $WINDOW_TARGET"
echo "[orch] Agents:  ${AGENTS[*]} (${#AGENTS[@]})"
echo "[orch] Timeout: ${STAGE_TIMEOUT}s per stage"
echo "[orch] Drift:   ${COMPOSITION_DRIFTED:-0}"
echo "========================================"

# Composition drifted: an agent appeared or a disappeared agent had
# complete outputs. Existing r2_*.md were built against a different
# roster, so every agent's R2 must re-run against the current roster.
# Clear R2 artifacts + synthesis_instructions so they rebuild fresh.
if [ "${COMPOSITION_DRIFTED:-0}" = 1 ]; then
  echo "[orch] composition drifted — clearing r2_*.md, r2_instructions_*.txt, synthesis_instructions.txt"
  rm -f "$DEBATE_DIR"/r2_*.md "$DEBATE_DIR"/r2_instructions_*.txt
  rm -f "$DEBATE_DIR"/.r2_*.lock
  rm -f "$DEBATE_DIR/synthesis_instructions.txt"
fi

# === R1: spawn agent panes, send prompts ===
clean_stale_locks r1
R1_PANES=()
for agent in "${AGENTS[@]}"; do
  R1_PANES+=("$(new_empty_pane)")
done
hide_output tmux_retile "$WINDOW_TARGET"
echo "[orch] R1 panes: agents=[${AGENTS[*]}]=[${R1_PANES[*]}]"
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

wait_for_outputs r1 "$STAGE_TIMEOUT" || exit 1

# Kill R1 panes
for i in "${!AGENTS[@]}"; do
  hide_errors tmux_kill_pane "${R1_PANES[$i]}"
done
hide_output tmux_retile "$WINDOW_TARGET"
echo "[orch] R1 agent panes closed"

# === R2: build prompts, spawn fresh panes ===
clean_stale_locks r2
# Per-agent R2 build: only missing files get built, full composition
# drives the "others" list in each agent's instructions.
for _a in "${AGENTS[@]}"; do
  [ -f "$DEBATE_DIR/r2_instructions_${_a}.txt" ] && continue
  DEBATE_AGENTS="${AGENTS[*]}" AGENT_FILTER="$_a" \
    bash "$PLUGIN_ROOT/skills/debate/scripts/debate-build-prompts.sh" \
    r2 "$DEBATE_DIR" "$PLUGIN_ROOT"
done

R2_PANES=()
for agent in "${AGENTS[@]}"; do
  R2_PANES+=("$(new_empty_pane)")
done
hide_output tmux_retile "$WINDOW_TARGET"
echo "[orch] R2 panes: agents=[${AGENTS[*]}]=[${R2_PANES[*]}]"
sleep 1
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

wait_for_outputs r2 "$STAGE_TIMEOUT" || exit 1

# Kill R2 panes
for i in "${!AGENTS[@]}"; do
  hide_errors tmux_kill_pane "${R2_PANES[$i]}"
done
hide_output tmux_retile "$WINDOW_TARGET"
echo "[orch] R2 agent panes closed"

# === Synthesis: build prompt, spawn single Claude pane ===
if [ -s "$DEBATE_DIR/synthesis.md" ]; then
  echo "[orch] synthesis already complete, skipping launch; running archive step"
  archive_debate
  echo "[orch] DEBATE COMPLETE — synthesis at $DEBATE_DIR/synthesis.md"
  exit 0
fi

clean_stale_locks synthesis
if [ ! -f "$DEBATE_DIR/synthesis_instructions.txt" ]; then
  DEBATE_AGENTS="${AGENTS[*]}" bash "$PLUGIN_ROOT/skills/debate/scripts/debate-build-prompts.sh" \
    synthesis "$DEBATE_DIR" "$PLUGIN_ROOT"
fi

SYNTH_PANE=$(new_empty_pane)
hide_output tmux_retile "$WINDOW_TARGET"
echo "[orch] synthesis pane: $SYNTH_PANE"
sleep 1
launch_agent "$SYNTH_PANE" synthesis claude "$(agent_launch_cmd claude)" "$(agent_ready_marker claude)" || exit 1
send_prompt  "$SYNTH_PANE" synthesis claude "$DEBATE_DIR/synthesis_instructions.txt" || exit 1

wait_for_file "$DEBATE_DIR/synthesis.md" "$STAGE_TIMEOUT" || exit 1

archive_debate
echo "[orch] DEBATE COMPLETE — synthesis at $DEBATE_DIR/synthesis.md"
}

# When run as a script (not sourced), execute the pipeline.
# The harness sources this file, defines stubs, calls daemon_main itself.
if [ "${DEBATE_DAEMON_SOURCED:-0}" != 1 ]; then
  daemon_main
fi
