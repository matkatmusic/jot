#!/bin/bash
# debate-tmux-orchestrator.sh — runs inside tmux orchestrator pane.
# Spawns agent panes per stage, monitors native transcripts for completion.
set -euo pipefail

main() {
  local DEBATE_DIR="$1"
  local WINDOW_TARGET="$2"
  local SETTINGS_FILE="$3"
  local CWD="$4"
  local REPO_ROOT="$5"
  local PLUGIN_ROOT="$6"

  local SCRIPTS_DIR
  SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  local STAGE_TIMEOUT=$((15 * 60))

  # Source tmux primitives
  source "$PLUGIN_ROOT/common/scripts/silencers.sh"
  source "$PLUGIN_ROOT/common/scripts/invoke_command.sh"
  source "$PLUGIN_ROOT/common/scripts/tmux.sh"
  source "$PLUGIN_ROOT/common/scripts/tmux-launcher.sh"

  # Read agents manifest
  local -a AGENTS
  while IFS= read -r line; do
    [ -n "$line" ] && AGENTS+=("$line")
  done < "$DEBATE_DIR/agents.txt"
  local AGENT_COUNT="${#AGENTS[@]}"

  # ── CLI command builder ──
  # Claude: stdin via < redirect. Gemini/Codex: prompt as argument via $(cat).
  build_agent_cmd() {
    local agent="$1" instructions="$2"
    case "$agent" in
      claude) echo "claude -p --settings $SETTINGS_FILE --add-dir $CWD --add-dir $REPO_ROOT < $instructions" ;;
      # gemini) echo "gemini -p \"Read $instructions\"" ;;
      gemini echo "gemini" ;;
      codex)  echo "cat '$instructions' | codex exec - --full-auto" ;;
    esac
  }

  # ── Native transcript paths ──
  # Gemini replaces underscores with hyphens in project dir names
  local gemini_project_name
  gemini_project_name=$(basename "$REPO_ROOT" | tr '_' '-')
  local GEMINI_CHATS_DIR="$HOME/.gemini/tmp/${gemini_project_name}/chats"
  local CODEX_SESSIONS_DIR="$HOME/.codex/sessions/$(date +%Y/%m/%d)"

  # ── find_transcript <agent> <prefix> ──
  # Claude: reads sidecar file written by debate-session-start.sh (deterministic)
  # Codex/Gemini: finds newest transcript file created after debate started
  find_transcript() {
    local agent="$1" prefix="$2"
    case "$agent" in
      claude)
        local sidecar="$DEBATE_DIR/transcript_claude_${prefix}.path"
        [ -f "$sidecar" ] && cat "$sidecar" ;;
      codex)
        find "$CODEX_SESSIONS_DIR" -name "rollout-*.jsonl" \
          -newer "$DEBATE_DIR/topic.md" -type f 2>/dev/null | sort -r | head -1 ;;
      gemini)
        find "$GEMINI_CHATS_DIR" -name "session-*.json" \
          -newer "$DEBATE_DIR/topic.md" -type f 2>/dev/null | sort -r | head -1 ;;
    esac
  }

  # ── is_agent_done <agent> <prefix> ──
  is_agent_done() {
    local agent="$1" prefix="$2"
    local output="$DEBATE_DIR/${prefix}_${agent}.md"

    # Primary: agent wrote its output file
    [ -s "$output" ] && return 0

    # Secondary: native transcript signals completion
    local transcript
    transcript=$(find_transcript "$agent" "$prefix")
    [ -z "$transcript" ] && return 1

    case "$agent" in
      codex)
        # Codex JSONL: last event has "task_complete"
        tail -1 "$transcript" 2>/dev/null | grep -q '"task_complete"' && return 0 ;;
      claude|gemini)
        # Staleness: file not modified for 15s = process exited
        local now mtime age
        now=$(date +%s)
        mtime=$(stat -f %m "$transcript" 2>/dev/null || stat -c %Y "$transcript" 2>/dev/null || echo "$now")
        age=$((now - mtime))
        [ "$age" -gt 15 ] && return 0 ;;
    esac
    return 1
  }

  # ── wait_for_stage <timeout> <prefix> ──
  wait_for_stage() {
    local timeout=$1 prefix=$2
    local elapsed=0
    while true; do
      local done_count=0
      local agent
      for agent in "${AGENTS[@]}"; do
        if is_agent_done "$agent" "$prefix"; then
          done_count=$((done_count + 1))
          local output="$DEBATE_DIR/${prefix}_${agent}.md"
          if [ ! -s "$output" ]; then
            printf "\n  [WARN] %s finished without writing %s\n" "$agent" "$(basename "$output")"
          fi
        fi
      done
      [ "$done_count" -eq "$AGENT_COUNT" ] && { printf "\n"; return 0; }
      [ "$elapsed" -ge "$timeout" ] && { printf "\n"; return 1; }
      sleep 5
      elapsed=$((elapsed + 5))
      printf "\r  Progress: %d/%d agents done (%ds / %ds)  " "$done_count" "$AGENT_COUNT" "$elapsed" "$timeout"
    done
  }

  # ── spawn_agent_panes <prefix> ──
  spawn_agent_panes() {
    local prefix="$1"
    local agent
    for agent in "${AGENTS[@]}"; do
      local instructions="$DEBATE_DIR/${prefix}_instructions_${agent}.txt"
      local cmd
      cmd=$(build_agent_cmd "$agent" "$instructions")

      # Claude: prepend sidecar env var so SessionStart hook writes transcript_path
      if [ "$agent" = "claude" ]; then
        local sidecar="$DEBATE_DIR/transcript_claude_${prefix}.path"
        cmd="DEBATE_TRANSCRIPT_SIDECAR=$sidecar $cmd"
      fi

      local pane_id
      pane_id=$(tmux_split_worker_pane "$WINDOW_TARGET" "$CWD" "$cmd")
      [ -n "$pane_id" ] && tmux_set_pane_title "$pane_id" "${agent}:${prefix}"
    done
    tmux_retile "$WINDOW_TARGET"
  }

  # ── Main flow ──

  echo "========================================"
  echo "  DEBATE ORCHESTRATOR"
  echo "  Dir: $DEBATE_DIR"
  echo "  Agents: ${AGENTS[*]} (${AGENT_COUNT})"
  echo "  Timeout: ${STAGE_TIMEOUT}s per stage"
  echo "========================================"
  echo ""

  # Stage 1
  echo "== STAGE 1: Independent Analysis =="
  spawn_agent_panes "r1"
  if ! wait_for_stage "$STAGE_TIMEOUT" "r1"; then
    echo "TIMEOUT: not all R1 responses received"; exec tail -f /dev/null
  fi
  echo "Stage 1 COMPLETE"; echo ""

  # Build R2 prompts
  echo "Building R2 prompts..."
  DEBATE_AGENTS="${AGENTS[*]}" bash "$SCRIPTS_DIR/debate-build-prompts.sh" r2 "$DEBATE_DIR" "$PLUGIN_ROOT"
  echo ""

  # Stage 2
  echo "== STAGE 2: Cross-Critique =="
  spawn_agent_panes "r2"
  if ! wait_for_stage "$STAGE_TIMEOUT" "r2"; then
    echo "TIMEOUT: not all R2 responses received"; exec tail -f /dev/null
  fi
  echo "Stage 2 COMPLETE"; echo ""

  # Build synthesis prompt
  echo "Building synthesis prompt..."
  DEBATE_AGENTS="${AGENTS[*]}" bash "$SCRIPTS_DIR/debate-build-prompts.sh" synthesis "$DEBATE_DIR" "$PLUGIN_ROOT"
  echo ""

  # Stage 3: synthesis
  echo "== STAGE 3: Synthesis =="
  local synth_sidecar="$DEBATE_DIR/transcript_claude_synthesis.path"
  local synth_cmd
  synth_cmd=$(build_agent_cmd "claude" "$DEBATE_DIR/synthesis_instructions.txt")
  synth_cmd="DEBATE_TRANSCRIPT_SIDECAR=$synth_sidecar $synth_cmd"
  local synth_pane
  synth_pane=$(tmux_split_worker_pane "$WINDOW_TARGET" "$CWD" "$synth_cmd")
  [ -n "$synth_pane" ] && tmux_set_pane_title "$synth_pane" "synthesis"
  tmux_retile "$WINDOW_TARGET"

  # Poll synthesis
  local elapsed=0
  while true; do
    if is_agent_done "claude" "synthesis"; then break; fi
    [ "$elapsed" -ge "$STAGE_TIMEOUT" ] && { echo "TIMEOUT: synthesis"; exec tail -f /dev/null; }
    sleep 5; elapsed=$((elapsed + 5))
    printf "\r  Synthesis: waiting... (%ds / %ds)  " "$elapsed" "$STAGE_TIMEOUT"
  done
  printf "\n"

  echo ""
  echo "========================================"
  echo "  DEBATE COMPLETE"
  echo "  Synthesis: $DEBATE_DIR/synthesis.md"
  echo "========================================"

  sleep 60
  tmux_kill_window "$WINDOW_TARGET" 2>/dev/null || true
}

main "$@"
