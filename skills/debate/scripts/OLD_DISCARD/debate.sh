#!/bin/bash
# debate.sh — function definitions for the /debate hook.
# Sourced by debate-orchestrator.sh. No side effects when sourced.

# ── Provider detection (3-stage: binary + credentials + smoke test) ──

# Bash-native timeout (macOS lacks GNU timeout)
_run_with_timeout() {
  local secs=$1; shift
  "$@" &
  local pid=$!
  ( sleep "$secs" && kill "$pid" 2>/dev/null ) &
  local watchdog=$!
  wait "$pid" 2>/dev/null
  local rc=$?
  kill "$watchdog" 2>/dev/null
  wait "$watchdog" 2>/dev/null
  return $rc
}

detect_available_agents() {
  AVAILABLE_AGENTS=(claude)

  if command -v gemini >/dev/null 2>&1; then
    if [[ -f "$HOME/.gemini/oauth_creds.json" ]] || [[ -n "${GEMINI_API_KEY:-}" ]] || [[ -n "${GOOGLE_API_KEY:-}" ]]; then
      if _run_with_timeout 30 gemini -p "Reply with exactly: ok" >/dev/null 2>&1; then
        AVAILABLE_AGENTS+=(gemini)
      else
        hide_errors printf '%s debate: gemini smoke test failed\n' "$(date -Iseconds)" >> "$LOG_FILE"
      fi
    else
      hide_errors printf '%s debate: gemini no auth credentials\n' "$(date -Iseconds)" >> "$LOG_FILE"
    fi
  fi

  if command -v codex >/dev/null 2>&1; then
    if [[ -f "$HOME/.codex/auth.json" ]] || [[ -n "${OPENAI_API_KEY:-}" ]]; then
      if _run_with_timeout 30 codex exec "Reply with exactly: ok" --full-auto >/dev/null 2>&1; then
        AVAILABLE_AGENTS+=(codex)
      else
        hide_errors printf '%s debate: codex smoke test failed\n' "$(date -Iseconds)" >> "$LOG_FILE"
      fi
    else
      hide_errors printf '%s debate: codex no auth credentials\n' "$(date -Iseconds)" >> "$LOG_FILE"
    fi
  fi
}

# ── Claude settings builder ──

debate_build_claude_cmd() {
  TMPDIR_INV=$(mktemp -d /tmp/debate.XXXXXX)
  SETTINGS_FILE="$TMPDIR_INV/settings.json"

  local permissions_file="${CLAUDE_PLUGIN_DATA}/debate-permissions.local.json"
  local default_file="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/assets/permissions.default.json"
  local default_sha_file="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/assets/permissions.default.json.sha256"
  local prior_sha_file="${CLAUDE_PLUGIN_DATA}/debate-permissions.default.sha256"
  mkdir -p "${CLAUDE_PLUGIN_DATA}"
  permissions_seed "$permissions_file" "$default_file" "$default_sha_file" "$prior_sha_file" "$LOG_FILE" "debate"

  local allow_json
  allow_json=$(CWD="$CWD" HOME="$HOME" REPO_ROOT="$REPO_ROOT" \
    python3 "${CLAUDE_PLUGIN_ROOT}/common/scripts/jot/expand_permissions.py" "$permissions_file")

  # Copy session-start hook to TMPDIR_INV for lifecycle safety (same as jot)
  cp "${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/debate-session-start.sh" "$TMPDIR_INV/debate-session-start.sh"

  local hooks_json_file="$TMPDIR_INV/hooks.json"
  cat > "$hooks_json_file" <<JSON
{
  "SessionStart": [{"hooks": [{"type": "command", "command": "bash $TMPDIR_INV/debate-session-start.sh"}]}]
}
JSON

  build_claude_cmd "$SETTINGS_FILE" "$allow_json" "$hooks_json_file" "$CWD" "$REPO_ROOT" > /dev/null
}

# ── Main entry point ──

debate_main() {
  : "${CLAUDE_PLUGIN_ROOT:?debate plugin env not set}"
  : "${CLAUDE_PLUGIN_DATA:?debate plugin env not set}"

  local SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts"

  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/silencers.sh"
  LOG_FILE="${DEBATE_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/debate-log.txt}"
  hide_errors mkdir -p "$(dirname "$LOG_FILE")"

  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/hook-json.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/platform.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/tmux-launcher.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/claude-launcher.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/permissions-seed.sh"

  INPUT=$(cat)
  case "$INPUT" in
    *'"/debate'*) ;;
    *) exit 0 ;;
  esac

  hide_errors printf '%s HOOK_INPUT %s\n' "$(date -Iseconds)" "$INPUT" >> "$LOG_FILE"
  check_requirements "debate" jq python3 tmux claude

  PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""')
  PROMPT="${PROMPT#"${PROMPT%%[![:space:]]*}"}"
  if [[ "$PROMPT" != "/debate" && "$PROMPT" != "/debate "* ]]; then
    exit 0
  fi

  TOPIC="${PROMPT#/debate}"
  TOPIC="${TOPIC# }"
  if [ -z "$TOPIC" ]; then
    emit_block "debate: no topic provided. Usage: /debate <topic>"
    exit 0
  fi

  CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
  [ -z "$CWD" ] && CWD="$PWD"
  TIMESTAMP=$(date +%Y-%m-%dT%H-%M-%S)

  REPO_ROOT=$(hide_errors git -C "$CWD" rev-parse --show-toplevel) || REPO_ROOT=""
  if [ -z "$REPO_ROOT" ]; then
    emit_block "debate requires a git repository."
    exit 0
  fi

  trap 'rc=$?; emit_block "debate crashed at line $LINENO (rc=$rc)"; exit 0' ERR

  # Detect available agents
  # TODO: restore detect_available_agents after smoke testing
  AVAILABLE_AGENTS=(claude gemini)
  # detect_available_agents
  if [ "${#AVAILABLE_AGENTS[@]}" -lt 2 ]; then
    emit_block "debate requires at least 2 agents. Found: ${AVAILABLE_AGENTS[*]}. Install gemini or codex."
    exit 0
  fi

  # Create debate directory with slug
  local slug
  slug=$(printf '%s' "$TOPIC" | tr '[:upper:]' '[:lower:]' | tr -cs '[:alnum:]' '-' | head -c 40 | sed 's/-$//')
  DEBATE_DIR="$REPO_ROOT/Debates/${TIMESTAMP}_${slug}"
  mkdir -p "$DEBATE_DIR"

  # Write topic + agents manifest
  printf '%s\n' "$TOPIC" > "$DEBATE_DIR/topic.md"
  printf '%s\n' "${AVAILABLE_AGENTS[@]}" > "$DEBATE_DIR/agents.txt"

  # Extract conversation context from calling session (same as jot)
  TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | hide_errors jq -r '.transcript_path // empty')
  local capture_script="$HOME/Programming/dotfiles/claude/hooks/scripts/capture-conversation.py"
  if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ] && [ -f "$capture_script" ]; then
    python3 "$capture_script" "$TRANSCRIPT_PATH" > "$DEBATE_DIR/context.md" 2>/dev/null || true
  else
    printf '(no conversation context available)\n' > "$DEBATE_DIR/context.md"
  fi

  # Build R1 instruction files
  DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" \
    bash "$SCRIPTS_DIR/debate-build-prompts.sh" r1 "$DEBATE_DIR" "${CLAUDE_PLUGIN_ROOT}"

  # Build claude settings (permissions + session-start hook)
  debate_build_claude_cmd

  # Ensure tmux session and window
  local window_name="debate-${TIMESTAMP}_${slug}"
  local keepalive_cmd='exec sh -c '\''trap "" INT HUP TERM; printf "[debate orchestrator]\n"; exec tail -f /dev/null'\'''
  tmux_ensure_session debate "$window_name" "$CWD" "$keepalive_cmd" 'debate: keepalive'
  local window_target="debate:${window_name}"

  # Set window large enough for multiple panes (detached sessions default to 80x24)
  hide_errors tmux resize-window -t "$window_target" -x 200 -y 60

  # Keep dead panes visible
  hide_output tmux_set_option_w "$window_target" remain-on-exit on

  # Spawn orchestrator pane (drives all stages)
  local orch_cmd="bash '$SCRIPTS_DIR/debate-tmux-orchestrator.sh' '$DEBATE_DIR' '$window_target' '$SETTINGS_FILE' '$CWD' '$REPO_ROOT' '${CLAUDE_PLUGIN_ROOT}'"
  local ORCH_PANE
  ORCH_PANE=$(tmux_split_worker_pane "$window_target" "$CWD" "$orch_cmd")
  [ -n "$ORCH_PANE" ] && tmux_set_pane_title "$ORCH_PANE" "orchestrator"

  tmux_retile "$window_target"
  spawn_terminal_if_needed "debate" "$LOG_FILE" "debate"

  local agents_str="${AVAILABLE_AGENTS[*]}"
  emit_block "/debate spawned (${agents_str// /, }) → Debates/${TIMESTAMP}_${slug}/synthesis.md (~10-30 min). View: tmux attach -t debate"
  exit 0
}
