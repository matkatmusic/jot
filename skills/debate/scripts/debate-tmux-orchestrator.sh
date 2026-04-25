#!/bin/bash
# debate-tmux-orchestrator.sh — background daemon that drives the full
# R1 → R2 → synthesis flow inside this debate's tmux session. Forked from
# debate.sh via: bash <this> ... >> orchestrator.log 2>&1 </dev/null &
#
# Preconditions (set up by debate.sh before forking):
#   - tmux session $SESSION (named 'debate-<N>', unique per invocation) exists
#     with a single 'main' window and a titled keepalive pane
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
  SESSION="$2"
  WINDOW_NAME="$3"
  SETTINGS_FILE="$4"
  CWD="$5"
  REPO_ROOT="$6"
  PLUGIN_ROOT="$7"
fi

# Fail-fast: silent drift to a default 'debate' session is how the shared-
# session bug existed in the first place. The sourced-mode harness MUST
# export SESSION explicitly.
: "${SESSION:?SESSION required (exported by caller or set via positional \$2)}"

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
# 2. Intentionally do NOT kill the tmux session on exit. Matches test.sh's
#    behavior: the session survives so the user can `tmux attach -t $SESSION`
#    and inspect what each agent pane actually did when outputs are missing.
#    `/debate-abort` + session-picking debate_claim_session handle stale
#    sessions cleanly; concurrent invocations get fresh `debate-<N>` names.
cleanup() {
  local settings_dir
  settings_dir=$(dirname "$SETTINGS_FILE")
  case "$settings_dir" in
    /tmp/debate.*) rm -rf "$settings_dir" ;;
  esac
  # hide_errors tmux_kill_session "$SESSION"
}
# Harness installs its own (no-op) cleanup before calling daemon_main.
if [ "${DEBATE_DAEMON_SOURCED:-0}" != 1 ]; then
  trap cleanup EXIT
fi

: "${DEBATE_AGENTS:?DEBATE_AGENTS env var required}"
IFS=' ' read -r -a AGENTS <<< "$DEBATE_AGENTS"

# === agent lookup ===
# macOS ships bash 3.2 which lacks `declare -gA` + `local -n`. Per-agent state
# is therefore stored in plain scalars named CURRENT_MODEL_<agent> and
# TRIED_MODELS_<agent>, read via indirect expansion (${!var}) and written via
# eval. Pane arrays R1_PANES/R2_PANES are referenced by name string and
# accessed via eval rather than nameref.

_stash()  { eval "${1}_${2}=\"\$3\""; }
# Default to empty when the variable was never _stash-ed — agent_launch_cmd
# may run before init_agent_models in tests or when called from harnesses.
_lookup() { local _v="${1}_${2}"; eval "printf '%s' \"\${$_v:-}\""; }

init_agent_models() {
  local _a
  for _a in gemini codex claude; do
    _stash CURRENT_MODEL "$_a" ""
    _stash TRIED_MODELS  "$_a" ""
  done
  _stash CURRENT_MODEL gemini "${GEMINI_MODEL:-}"
  _stash CURRENT_MODEL codex  "${CODEX_MODEL:-}"
  _stash TRIED_MODELS  gemini "${GEMINI_MODEL:-}"
  _stash TRIED_MODELS  codex  "${CODEX_MODEL:-}"
}

agent_launch_cmd() {
  local a="$1"
  local m; m=$(_lookup CURRENT_MODEL "$a")
  case "$a" in
    # --allowed-tools bypasses approval for the tools the debate flow needs:
    # read_file (topic/context/other agents' outputs), write_file (r<N>_gemini.md),
    # and run_shell_command(ls) so gemini can probe directory contents without
    # blocking on an approval prompt no human is watching for.
    gemini)
      if [ -n "$m" ]; then
        echo "gemini --allowed-tools 'read_file,write_file,run_shell_command(ls)' --model '$m'"
      else
        echo "gemini --allowed-tools 'read_file,write_file,run_shell_command(ls)'"
      fi
      ;;
    # -a never: codex never prompts for approval (non-interactive-safe).
    # --add-dir: grants write access to $DEBATE_DIR (codex docs: prefer this
    # over --sandbox danger-full-access for targeted write permissions).
    codex)
      if [ -n "$m" ]; then
        echo "codex -a never --add-dir '$DEBATE_DIR' --model '$m'"
      else
        echo "codex -a never --add-dir '$DEBATE_DIR'"
      fi
      ;;
    # --settings grants Claude write perms to Debates/** (see assets/permissions.default.json).
    # --add-dir '$HOME/.claude/plans' is required because debate topics commonly
    # reference plan files at that path; without it, Claude blocks on a
    # workspace-boundary Read prompt that no human is there to approve
    # (Read(**) in permissions does NOT short-circuit the workspace gate).
    claude) echo "claude --settings '$SETTINGS_FILE' --add-dir '$CWD' --add-dir '$REPO_ROOT' --add-dir '$HOME/.claude/plans'" ;;
  esac
}
agent_ready_marker() {
  case "$1" in
    gemini) echo "Type your message or @path/to/file" ;;
    codex)  echo "/model to change" ;;
    claude) echo "Claude Code v" ;;
  esac
}
# Agent-CLI capacity/quota error strings. Matched against pane content during
# wait_for_outputs so we can rotate to the next fallback model automatically.
# ONE marker per line; grep -qF (literal) matches any.
agent_error_markers() {
  case "$1" in
    codex)  printf '%s\n' 'Selected model is at capacity' 'model is overloaded' ;;
    gemini) printf '%s\n' 'RESOURCE_EXHAUSTED' 'Quota exceeded' 'You exceeded your current quota' ;;
    claude) printf '%s\n' 'API Error: 529' 'overloaded_error' ;;
  esac
}
pane_has_capacity_error() {
  local pane_id="$1" agent="$2"
  local cap marker
  cap=$(hide_errors tmux capture-pane -t "$pane_id" -p -S -200 | tr -d '\033')
  while IFS= read -r marker; do
    [ -z "$marker" ] && continue
    if echo "$cap" | grep -qF "$marker"; then
      echo "$marker"
      return 0
    fi
  done < <(agent_error_markers "$agent")
  return 1
}
# Return the next fallback model for <agent> not already in TRIED_MODELS_<agent>.
# Empty string + rc=1 when the list is exhausted.
_next_fallback_model() {
  local agent="$1"
  local tried; tried=$(_lookup TRIED_MODELS "$agent")
  local fallbacks_json="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/assets/model-fallbacks.json"
  local m
  while IFS= read -r m; do
    [ -z "$m" ] && continue
    case ",$tried," in *,"$m",*) continue ;; esac
    echo "$m"
    return 0
  done < <(hide_errors jq -r --arg a "$agent" '.[$a][]?' "$fallbacks_json")
  return 1
}
# retry_pane_with_next_model <panes_array_name> <index> <agent> <stage>
# Tears down the current pane, picks the next fallback, spawns a fresh pane,
# and re-launches + re-prompts. <panes_array_name> is the *name* of a global
# array (e.g. "R1_PANES"); we access/mutate via eval for bash-3.2 compatibility.
retry_pane_with_next_model() {
  local panes_var="$1" i="$2" agent="$3" stage="$4"
  local next
  if ! next=$(_next_fallback_model "$agent"); then
    echo "[orch] $stage/$agent: no remaining fallback models; giving up" >&2
    return 1
  fi
  echo "[orch] $stage/$agent: capacity hit — rotating to model '$next'"
  _stash CURRENT_MODEL "$agent" "$next"
  local tried; tried=$(_lookup TRIED_MODELS "$agent")
  _stash TRIED_MODELS "$agent" "${tried},${next}"
  local current_pane
  eval "current_pane=\${${panes_var}[$i]}"
  hide_errors tmux_kill_pane "$current_pane"
  local new_pane; new_pane=$(new_empty_pane)
  eval "${panes_var}[$i]=\"\$new_pane\""
  hide_output tmux_retile "$WINDOW_TARGET"
  sleep 1
  launch_agent "$new_pane" "$stage" "$agent" \
    "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" || return 1
  send_prompt  "$new_pane" "$stage" "$agent" \
    "$DEBATE_DIR/${stage}_instructions_${agent}.txt" || return 1
  return 0
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
# 120s default covers Claude Code /remote-control async registration + shell rc
# (pyenv, nvm, zsh) cold-start cost. Tight under 900s STAGE_TIMEOUT when 3 agents
# boot serially (3×120=360s), but acceptable; bump STAGE_TIMEOUT if this grows.
# capture-pane uses -S -2000 so a marker scrolled off the visible area is still
# found, and tr -d '\033' strips ANSI escapes that can split the marker string.
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

# send_prompt <pane_id> <stage> <agent> <instructions_file>
# Same capture-pane hardening as launch_agent: -S -2000 scrollback + ANSI strip.
send_prompt() {
  local pane_id="$1" stage="$2" agent="$3" instructions="$4"
  tmux_send_and_submit "$pane_id" "read $instructions and perform them"
  local marker
  marker=$(basename "$instructions")
  # 30s window: detached daemon has no observer, so allow more slack than test.sh's
  # attended 10s before declaring the echo-verification a silent failure.
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

# wait_for_outputs <prefix> <timeout> <panes_arrayname>
# Assumes agents write outputs atomically (e.g. Claude's Write tool does
# temp-then-rename). If an agent streams or uses shell redirection, the
# `[ -s "$out" ]` check could fire on the first byte and racing kills
# the pane mid-stream. Keep this invariant in mind before swapping the
# launch command to any mode that doesn't write atomically.
#
# <panes_arrayname> is a bash nameref to the per-stage pane-id array (e.g.
# R1_PANES). Entries are mutated in place when retry_pane_with_next_model
# rotates to a fallback model, so subsequent iterations poll the new pane.
wait_for_outputs() {
  local prefix="$1" timeout="$2" panes_var="$3"
  local reported=""
  local elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    local done_count=0
    local i agent pane_id
    for i in "${!AGENTS[@]}"; do
      agent="${AGENTS[$i]}"
      local out="$DEBATE_DIR/${prefix}_${agent}.md"
      if [ -s "$out" ]; then
        rm -f "$DEBATE_DIR/.${prefix}_${agent}.lock"
        done_count=$((done_count + 1))
        case " $reported " in
          *" $agent "*) ;;
          *) printf '\n[orch] %s: %s wrote %s (%ds)\n' "$prefix" "$agent" "$(basename "$out")" "$elapsed"
             reported="$reported $agent" ;;
        esac
        continue
      fi
      # Capacity / quota detection: if this agent's pane shows a known error
      # marker, rotate to the next fallback model (kill + respawn + re-prompt).
      # Skip if no still-untried fallback exists (retry function logs + returns 1).
      eval "pane_id=\${${panes_var}[$i]}"
      if pane_has_capacity_error "$pane_id" "$agent" >/dev/null; then
        retry_pane_with_next_model "$panes_var" "$i" "$agent" "$prefix" || true
      fi
      continue
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
echo "[orch] Session: $SESSION"
echo "[orch] Window:  $WINDOW_TARGET"
echo "[orch] Agents:  ${AGENTS[*]} (${#AGENTS[@]})"
echo "[orch] Timeout: ${STAGE_TIMEOUT}s per stage"
echo "[orch] Drift:   ${COMPOSITION_DRIFTED:-0}"
echo "========================================"
init_agent_models

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

wait_for_outputs r1 "$STAGE_TIMEOUT" R1_PANES || exit 1

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

wait_for_outputs r2 "$STAGE_TIMEOUT" R2_PANES || exit 1

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
